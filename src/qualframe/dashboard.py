from __future__ import annotations

import html
import json
import mimetypes
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from qualframe.adjudication import append_adjudication_action, latest_adjudication_by_item
from qualframe.config import resolve_repo_path
from qualframe.cost_control import append_cost_approval
from qualframe.cost_control import CostApprovalRequired
from qualframe.evidence_review import (
    add_researcher_coding,
    append_evidence_review_action,
    export_evidence_review_package,
    latest_evidence_action_by_record,
    load_evidence_review_records,
    load_run_records,
    record_review_timing,
    run_context_policy,
    write_evidence_review_index,
)
from qualframe.governance import append_gate_action, append_release_action, approved_gate_ids
from qualframe.io.export import export_run
from qualframe.models import (
    CostPauseRecord,
    CreatedStudy,
    MethodPolicyUpdate,
    RunManifest,
    RunPlan,
    StudyCreationRequest,
)
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.qa.inventory import review_item_paths
from qualframe.study_setup import StudyWorkspace
from qualframe.web_forms import UploadedFile, parse_multipart_form
from qualframe.excel_import_workflow import ExcelImportWorkflow
from qualframe.codebook_import_ui import mapping_view, confirmation_view
from qualframe.provider_setup import ProviderSetup, save_provider_setup
from qualframe.provider_setup_ui import provider_setup_form
from qualframe.workspace_ui import render_workspace


_MAX_HTTP_BODY = 26 * 1024 * 1024
_LOCAL_EXECUTION_PROVIDERS = {"mock", "cached_demo", "recorded"}
_PAID_EXECUTION_PROVIDERS = {"openai", "anthropic", "openai_compatible"}


@dataclass
class ExecutionJob:
    run_id: str
    status: str = "running"
    progress: list[str] = field(default_factory=list)
    error: str | None = None


class DashboardApp:
    """Loopback-only controller for run inspection and human review actions."""

    def __init__(self, runner: ProjectRunner | None = None, workspace_root: Path | None = None) -> None:
        if runner is None and workspace_root is None:
            raise ValueError("Give a study or a workspace folder.")
        self.repo_root = (workspace_root or runner.repo_root).resolve()
        self.study_workspace = StudyWorkspace(self.repo_root)
        self._jobs: dict[str, ExecutionJob] = {}
        self._job_lock = threading.Lock()
        self.runner: ProjectRunner | None = None
        if runner is not None:
            self._activate_runner(runner)

    @property
    def researcher(self) -> str:
        from qualframe.app_workspace import researcher_name
        return researcher_name(self.repo_root)

    def fill_identity(self, form: dict[str, list[str]], default_reason: str) -> dict[str, list[str]]:
        """Use the remembered researcher name and a default note when the form leaves them blank."""
        from qualframe.app_workspace import write_settings
        from qualframe.app_workspace import PLACEHOLDER_NAME

        supplied = (form.get("actor", [""])[0] or form.get("reviewer", [""])[0]).strip()
        if supplied == PLACEHOLDER_NAME:
            supplied = ""
        name = supplied or self.researcher
        if supplied and not self.researcher:
            write_settings(self.repo_root, researcher_name=supplied)
        name = name or PLACEHOLDER_NAME
        form["actor"] = [name]
        form["reviewer"] = [name]
        if not form.get("rationale", [""])[0].strip():
            form["rationale"] = [default_reason]
        return form

    def _activate_runner(self, runner: ProjectRunner) -> None:
        if runner.repo_root.resolve() != self.repo_root:
            raise ValueError("Created study must remain inside the QualFrame workspace.")
        self.runner = runner
        self.artifacts_dir = resolve_repo_path(self.repo_root, runner.project.paths["artifacts"])
        self.review_dir = resolve_repo_path(self.repo_root, runner.project.paths["review_queue"])
        self.exports_dir = resolve_repo_path(self.repo_root, runner.project.paths["exports"])
        self.logs_dir = resolve_repo_path(
            self.repo_root, runner.project.paths.get("logs", "logs")
        )

    def create_study(self, form: dict[str, list[str]]) -> CreatedStudy:
        request = StudyCreationRequest(
            title=form.get("title", [""])[0],
            study_id=form.get("study_id", [""])[0].strip() or None,
            data_classification=form.get("data_classification", [""])[0],
            template=form.get("template", ["generic_directed"])[0],
            include_synthetic_fixtures=(
                form.get("include_synthetic_fixtures", [""])[0] == "yes"
            ),
        )
        created = self.study_workspace.create(request)
        project_path = self.repo_root / created.project_manifest_path
        self._activate_runner(ProjectRunner(project_path))
        return created

    def _managed_project_path(self) -> Path:
        self.study_workspace.managed_study_root(self.runner.project_manifest_path)
        return self.runner.project_manifest_path

    def _refresh_runner(self) -> None:
        self._activate_runner(ProjectRunner(self.runner.project_manifest_path))

    def list_runs(self) -> list[str]:
        if not self.artifacts_dir.exists():
            return []
        return sorted(
            (
                path.name
                for path in self.artifacts_dir.iterdir()
                if path.is_dir()
                and (
                    (path / "run_manifest.json").exists()
                    or (path / "cost_pause.json").exists()
                    or (path / "run_plan.json").exists()
                )
            ),
            key=lambda name: (
                max((self.artifacts_dir / name / filename).stat().st_mtime_ns
                    for filename in ("run_manifest.json", "cost_pause.json", "run_plan.json")
                    if (self.artifacts_dir / name / filename).exists()), name),
            reverse=True,
        )

    def _run_root(self, base: Path, run_id: str) -> Path:
        if run_id not in self.list_runs():
            raise ValueError("Unknown run ID.")
        resolved = (base / run_id).resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise ValueError("Run path escaped its configured root.")
        return resolved

    def _file_link(self, path: Path, label: str) -> str:
        roots = {
            "artifacts": self.artifacts_dir.resolve(),
            "review_queue": self.review_dir.resolve(),
            "exports": self.exports_dir.resolve(),
        }
        resolved = path.resolve()
        for category, root in roots.items():
            if resolved.is_relative_to(root):
                relative = resolved.relative_to(root).as_posix()
                target = f"{category}/{relative}"
                return f"<a href='/file?{urlencode({'path': target})}'>{html.escape(label)}</a>"
        raise ValueError("Dashboard file link escaped configured output roots.")

    def resolve_file(self, relative_path: str) -> Path:
        category, separator, remainder = relative_path.partition("/")
        roots = {
            "artifacts": self.artifacts_dir.resolve(),
            "review_queue": self.review_dir.resolve(),
            "exports": self.exports_dir.resolve(),
        }
        root = roots.get(category)
        if not separator or root is None:
            raise FileNotFoundError(relative_path)
        candidate = (root / remainder).resolve()
        if not candidate.exists() or not candidate.is_relative_to(root):
            raise FileNotFoundError(relative_path)
        return candidate

    def render(self, run_id: str | None = None, message: str = "") -> str:
        if not run_id:
            from qualframe.overview_ui import render_overview
            return render_overview(self, message)
        return self.render_run_page(run_id, message)

    def render_run_page(self, run_id: str | None = None, message: str = "") -> str:
        runs = self.list_runs()
        preferred = run_id or getattr(self, '_selected_run', None)
        selected = preferred if preferred in runs else (runs[0] if runs else None)
        self._selected_run = selected
        run_links = "".join(
            f"<option value='{html.escape(item)}' {'selected' if item == selected else ''}>"
            f"{html.escape(item)}</option>"
            for item in runs
        )
        message_html = f"<div class='message'>{html.escape(message)}</div>" if message else ""

        if selected is None:
            detail = self._render_study_overview()
        else:
            detail = self._render_run(selected)

        job = self._job_snapshot(selected) if selected else None
        refresh = (
            '<meta http-equiv="refresh" content="2">'
            if job is not None and job.status == "running"
            else ""
        )
        selector = (
            f'<div class="run-selector"><form method="get" action="/" class="inline">'
            f'<label>Recorded run<select name="run_id">{run_links}</select></label>'
            '<button type="submit">Open run</button></form></div>' if runs else ""
        )
        from qualframe.study_progress import render_study_progress
        study_progress = render_study_progress(self, selected)
        presentation = (
            '<p class="muted"><a href="/presentation">Open the cached CFIR evidence report</a></p>'
            if self.runner.project.provider.name == 'cached_demo' and (self.repo_root / "demo/presentation/index.html").exists() else ""
        )
        from qualframe.ui_kit import provider_display, run_model
        provider, model = run_model(self.artifacts_dir / selected) if selected else (None, None)
        title = f"Run: {provider_display(provider, model)}" if provider else "Run details"
        back = '<p><a href="/">Back to study overview</a></p>'
        return self._render_workspace_page(
            title=title,
            intro="Progress, review status, and the full record of this coding run.",
            body=back + message_html + self._run_next_step(selected) + study_progress + detail + presentation,
            head=refresh, active="overview",
        )

    def _run_next_step(self, run_id: str | None) -> str:
        if not run_id:
            return ""
        job = self._job_snapshot(run_id)
        if job is not None and job.status == "running":
            return ('<div class="next-up"><div><h2>Coding in progress</h2><p>This page updates every two seconds. '
                    'You can leave it and come back; coding continues in the background.</p></div></div>')
        index = self.artifacts_dir / run_id / "evidence_review/index.json"
        if index.exists():
            from qualframe.study_status import review_counts
            counts = review_counts(self, run_id)
            url = "/evidence?" + urlencode({"run_id": run_id})
            if counts.total and counts.remaining:
                return (f'<div class="next-up"><div><h2>Ready for review</h2><p>{counts.remaining} of {counts.total} '
                        f'proposals need your decision.</p></div><a class="button" href="{html.escape(url)}">Review proposals</a></div>')
        return ""

    def _render_study_overview(self) -> str:
        plan = self.runner.build_run_plan()
        project_name = self.runner.project.title or self.runner.project.project_id
        classification = self.runner.project.data_classification or "not declared"
        provider = self.runner.project.provider.name
        method = self.runner.method.name if self.runner.method else "Not configured"
        source_count = len(plan.discovered_inputs)
        call_count = len(plan.planned_stage_runs)
        fingerprint = plan.configuration_fingerprint or "Not available"
        safety = (
            "Local mock mode; no external request"
            if provider == "mock"
            else "Cached synthetic mode; no external request"
            if provider == "cached_demo"
            else f"External provider configured: {provider}"
        )
        return f"""
<div class="cards">
<div class="card"><div class="label">Study</div><div class="value">{html.escape(project_name)}</div></div>
<div class="card"><div class="label">Data classification</div><div class="value">{html.escape(classification.title())}</div></div>
<div class="card"><div class="label">Method</div><div class="value">{html.escape(method)}</div></div>
<div class="card"><div class="label">Provider mode</div><div class="value">{html.escape(safety)}</div></div>
<div class="card"><div class="label">Imported inputs</div><div class="value">{source_count}</div></div>
<div class="card"><div class="label">Planned stage calls</div><div class="value">{call_count}</div></div>
</div>
<section><h2>Preflight</h2><p>No completed or paused runs exist for this study. Previewing a run plan records the exact inputs, stage calls, hashes, and configuration identity without contacting a model.</p>
<p><strong>Configuration:</strong> <code>{html.escape(fingerprint)}</code></p>
<form method="post" action="/plan"><button type="submit">Create dry-run plan</button></form></section>"""

    def render_setup(self, message: str = "", error: str = "") -> str:
        from qualframe.ui_kit import notices
        body = f"""{notices(message, error)}
<section><form method="post" action="/study/create">
<label>Study name<input name="title" maxlength="120" required placeholder="For example: Clinician experiences of virtual care"></label>
<fieldset><legend>Approach</legend><div class="choices">
<label class="choice"><input type="radio" name="template" value="generic_directed" checked><span><strong>Directed content analysis</strong><small>Apply your own codebook, imported from Excel. Works for any deductive framework.</small></span></label>
<label class="choice"><input type="radio" name="template" value="cfir"><span><strong>CFIR reference workflow</strong><small>The staged CFIR pipeline from the AMN study: one request per CFIR domain, with roll-up and synthesis steps.</small></span></label>
</div></fieldset>
<fieldset><legend>What kind of data will this study hold?</legend><div class="choices">
<label class="choice"><input type="radio" name="data_classification" value="deidentified" required><span><strong>De-identified research data</strong><small>Interviews with identifying details removed.</small></span></label>
<label class="choice"><input type="radio" name="data_classification" value="sensitive"><span><strong>Sensitive research data</strong><small>May still contain identifying or sensitive details. Prefer a local model.</small></span></label>
<label class="choice"><input type="radio" name="data_classification" value="synthetic"><span><strong>Test or synthetic data</strong><small>Made-up material for trying things out. Enables the offline test models.</small></span></label>
</div></fieldset>
<p class="muted">Creating a study makes a folder on this computer. Nothing is sent anywhere until you start a coding run.</p>
<details><summary>Optional: choose the study folder name</summary><label>Folder name<input name="study_id" pattern="[a-z0-9][a-z0-9-]{{1,62}}[a-z0-9]" placeholder="made from the study name"><small>Lowercase letters, numbers and hyphens.</small></label></details>
<div class="actions"><button class="big">Create study</button></div></form></section>
"""
        return self._render_workspace_page(
            title="New study",
            intro="Name your study and say what kind of data it will hold. You'll add transcripts and a codebook next.",
            body=body, active="setup",
        )

    def _unmanaged_page(self, title: str, active: str, exc: Exception) -> str:
        body = (f"<section><h2>Read-only study</h2><p>{html.escape(str(exc))}</p>"
                "<p>This study was opened from a project file rather than your studies folder, so imports and "
                "settings can't be changed here. <a href='/setup'>Create a study</a> to work with your own files.</p></section>")
        return self._render_workspace_page(title=title, intro="", body=body, active=active)

    def render_imports(self, message: str = "", error: str = "") -> str:
        from qualframe.sources_ui import render_sources
        try:
            self._managed_project_path()
        except ValueError as exc:
            return self._unmanaged_page("Sources", "imports", exc)
        return render_sources(self, message, error)

    def render_codebook(self, message: str = "", error: str = "") -> str:
        from qualframe.sources_ui import render_codebook
        try:
            self._managed_project_path()
        except ValueError as exc:
            return self._unmanaged_page("Codebook", "codebook", exc)
        return render_codebook(self, message, error)

    def render_configure(self, message: str = "", error: str = "") -> str:
        from qualframe.coding_ui import render_coding
        try:
            self._managed_project_path()
        except ValueError as exc:
            return self._unmanaged_page("Run coding", "configure", exc)
        return render_coding(self, message, error)

    def render_home(self, message: str = "", error: str = "") -> str:
        from qualframe.home_ui import render_home
        return render_home(self, message, error)

    def _render_workspace_page(
        self, *, title: str, intro: str, body: str, head: str = "", active: str | None = None,
        page_title: str | None = None, wide: bool = False,
    ) -> str:
        if active is None:
            active = {"Create a study": "setup", "Import study files": "imports",
                      "Import Excel codebook": "codebook", "Review Excel codebook": "codebook", "Check codebook mapping": "codebook",
                      "Configure analysis method": "configure",
                      "Review exact evidence": "evidence", "Analyze reviewed evidence": "analysis", "Review proposed summaries": "analysis",
                      "Compare coding runs": "compare", "Detailed span benchmark": "compare", "Evaluate repeat runs": "repeats",
                      "Repeat coding": "repeats", "Review empty coding output": "evidence"}.get(title, "overview")
        if self.runner is None or active in {"home"}:
            page = render_workspace(title=title, intro=intro, body=body, head=head, active=active, study=None)
            return page.replace("<title> · QualFrame</title>", f"<title>{html.escape(page_title or 'QualFrame')}</title>")
        from qualframe.study_status import study_steps
        from qualframe.ui_kit import name_prompt
        body = name_prompt(self.researcher, getattr(self, "_current_path", "/")) + body
        project = self.runner.project
        tools = [("compare", "/compare", "Compare runs"), ("repeats", "/repeats", "Repeat runs"),
                 ("history", "/?" + urlencode({"run_id": self.list_runs()[0]}) if self.list_runs() else "/", "Run details")]
        return render_workspace(
            title=title, intro=intro, body=body, head=head, active=active,
            study=project.title or project.project_id,
            classification=project.data_classification or "",
            provider=project.provider.name, model=project.provider.model,
            steps=study_steps(self), tools=tools, wide=wide,
            study_detail="Synthetic demo data" if project.data_classification == "synthetic" else "",
        )

    def handle_upload(
        self,
        path: str,
        fields: dict[str, list[str]],
        files: dict[str, UploadedFile],
    ) -> str:
        project_path = self._managed_project_path()
        uploads = files.get("upload") or []
        if not isinstance(uploads, list):
            uploads = [uploads]
        if not uploads:
            raise ValueError("Choose a file to import.")
        defaults = {"/import/transcript": "Added transcript", "/import/codebook": "Imported codebook",
                    "/import/cfir": "Imported CFIR reference workbook", "/import/metadata": "Imported participant information"}
        self.fill_identity(fields, defaults.get(path, "Imported file"))
        if len(uploads) > 1:
            if path != "/import/transcript":
                raise ValueError("Choose one file.")
            added = [self._import_one(path, fields, item, project_path) for item in uploads]
            self._refresh_runner()
            return f"Added {len(added)} transcripts."
        record = self._import_one(path, fields, uploads[0], project_path)
        self._refresh_runner()
        return f"Imported {record.original_filename}."

    def _import_one(self, path: str, fields: dict[str, list[str]], upload: UploadedFile, project_path: Path):
        def field(name: str, default: str = "") -> str:
            return fields.get(name, [default])[0]

        common = {
            "project_manifest_path": project_path,
            "filename": upload.filename,
            "content": upload.content,
            "actor": field("actor"),
            "rationale": field("rationale"),
        }
        if path == "/import/transcript":
            record = self.study_workspace.import_transcript(
                **common,
                group_label=field("group_label", "") or "Ungrouped",
            )
        elif path == "/import/codebook":
            record = self.study_workspace.import_codebook(**common)
        elif path == '/import/cfir':
            from qualframe.cfir_import import import_reference
            record = import_reference(self.study_workspace, project_path, upload.filename, upload.content,
                field('actor'), field('rationale'))
        elif path == "/import/metadata":
            record = self.study_workspace.import_metadata(**common)
        else:
            raise ValueError("Unknown import action.")
        return record

    def handle_instructions(self, path: str, form: dict[str, list[str]]) -> str:
        from qualframe.coding_instructions import save_instructions, use_instructions

        project_path = self._managed_project_path()
        if path == "/instructions/save":
            self.fill_identity(form, "Edited the coding instructions")
            save_instructions(self.study_workspace, project_path, text=form.get("instructions", [""])[0],
                              label=form.get("label", [""])[0], actor=form["actor"][0], rationale=form["rationale"][0])
            message = "Saved a new version of the coding instructions. New runs will use it."
        else:
            self.fill_identity(form, "Switched coding instructions")
            use_instructions(self.study_workspace, project_path, framework_ref=form.get("framework_ref", [""])[0],
                             actor=form["actor"][0], rationale=form["rationale"][0])
            message = "Switched the coding instructions. New runs will use this version."
        self._activate_runner(ProjectRunner(project_path))
        return message

    def handle_method_update(self, form: dict[str, list[str]]) -> str:
        self.fill_identity(form, "Changed coding options")

        def required(name: str) -> str:
            value = form.get(name, [""])[0].strip()
            if not value:
                raise ValueError(f"Missing required field: {name}")
            return value

        partition_strategy = required("partition_strategy")
        if self.runner.pipeline.id.startswith("transcript_cfir"):
            partition_strategy = "per_top_level_category"
        from qualframe.coding_ui import CONTEXT_PRESETS

        preset = form.get("context_preset", ["custom"])[0]
        if preset in CONTEXT_PRESETS:
            unit, before, after = CONTEXT_PRESETS[preset][1]
            form["context_unit"], form["context_before"], form["context_after"] = [unit], [str(before)], [str(after)]
        update = MethodPolicyUpdate(
            segmentation_strategy=required("segmentation_strategy"),
            context_before=int(required("context_before")),
            context_unit=form.get("context_unit", ["sentences"])[0],
            context_after=int(required("context_after")),
            coding_cardinality=required("coding_cardinality"),
            allow_overlapping_spans=(
                form.get("allow_overlapping_spans", [""])[0] == "yes"
            ),
            partition_strategy=partition_strategy,
        )
        self.study_workspace.update_method_policy(
            project_manifest_path=self._managed_project_path(),
            update=update,
            actor=required("actor"),
            rationale=required("rationale"),
        )
        self._refresh_runner()
        return "Saved coding options as a new method version."

    def render_evidence(
        self,
        *,
        run_id: str,
        item_id: str = "",
        message: str = "",
        error: str = "",
    ) -> str:
        from qualframe.review_ui import render_review
        return render_review(self, run_id=run_id, item_id=item_id, message=message, error=error)

    def _render_run(self, run_id: str) -> str:
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        manifest_path = artifact_root / "run_manifest.json"
        pause_path = artifact_root / "cost_pause.json"
        job = self._job_snapshot(run_id)
        if job is not None and job.status == "running":
            progress = "".join(
                f"<li>{html.escape(item)}</li>" for item in job.progress[-10:]
            ) or "<li>Preparing the local run.</li>"
            return f"""
<div class="cards"><div class="card"><div class="label">Run</div><div class="value">{html.escape(run_id)}</div></div><div class="card"><div class="label">Status</div><div class="value">Running locally</div></div><div class="card"><div class="label">Provider</div><div class="value">{html.escape(self.runner.project.provider.name)}</div></div></div>
<section><h2>Execution progress</h2><p>This page refreshes every two seconds. Closing it does not stop the local background job.</p><ul>{progress}</ul><p class="muted">Provider requests follow the approved configuration and study budget.</p></section>"""
        if job is not None and job.status == "failed" and not manifest_path.exists():
            return f"""<section><h2>Execution failed</h2><p>{html.escape(job.error or 'Unknown local execution error.')}</p>{self._local_execution_control(run_id, "Resume this run")}</section>"""
        if not manifest_path.exists() and pause_path.exists():
            pause = CostPauseRecord.model_validate_json(
                pause_path.read_text(encoding="utf-8")
            )
            return self._render_cost_pause(run_id, pause, pause_path)
        if not manifest_path.exists() and any((artifact_root / "requests").glob("*.json")):
            return ("<section><h2>Coding incomplete</h2><p>This run has recorded request "
                    "attempts but no completed run manifest. Request records and charges are preserved. "
                    "Resolve any uncertain usage before resuming.</p>"
                    + self._local_execution_control(run_id, "Resume this run") + "</section>")
        if not manifest_path.exists() and (artifact_root / "run_plan.json").exists():
            plan = RunPlan.model_validate_json(
                (artifact_root / "run_plan.json").read_text(encoding="utf-8")
            )
            return self._render_planned_run(run_id, plan, artifact_root / "run_plan.json")
        manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        review_root = self.review_dir / run_id
        export_root = self.exports_dir / run_id
        review_items = review_item_paths(artifact_root, review_root, manifest.model_dump())
        adjudications = latest_adjudication_by_item(review_root) if review_root.exists() else {}
        evidence_index = artifact_root / "evidence_review" / "index.json"
        if evidence_index.exists():
            evidence_records = load_evidence_review_records(evidence_index)
            evidence_actions = latest_evidence_action_by_record(review_root)
            evidence_resolved = sum(
                1
                for record in evidence_records
                if record.record_id in evidence_actions
                and evidence_actions[record.record_id].decision != "defer"
            )
            evidence_section = f"""<section><h2>Exact-evidence review</h2><p>{evidence_resolved} of {len(evidence_records)} items resolved.</p><p><a href="/evidence?{urlencode({'run_id': run_id})}">Open exact-evidence reviewer</a></p></section>"""
        else:
            evidence_section = f"""<section><h2>Exact-evidence review</h2><p>Prepare source-linked review records from offset-bearing parsed rows.</p><form method="post" action="/prepare-evidence"><input type="hidden" name="run_id" value="{html.escape(run_id)}"><button type="submit">Prepare exact-evidence review</button></form></section>"""

        stage_counts: dict[str, int] = {}
        artifact_links: list[str] = []
        for rel in manifest.artifact_paths:
            path = artifact_root / rel
            stage = Path(rel).parts[0]
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            artifact_links.append(f"<li>{self._file_link(path, rel)}</li>")
        stage_rows = "".join(
            f"<tr><td>{html.escape(stage.replace('_', ' ').title())}</td><td>{count}</td></tr>"
            for stage, count in stage_counts.items()
        )

        review_rows = ""
        for item_path in review_items:
            payload = json.loads(item_path.read_text(encoding="utf-8"))
            item_rel = item_path.relative_to(review_root).as_posix()
            action = adjudications.get(item_rel) or adjudications.get(str(item_path.relative_to(review_root)))
            issue = payload.get("rule_id") or payload.get("field") or payload.get("kind", "review")
            reason = payload.get("reason") or (
                f"{payload.get('left_value')} versus {payload.get('right_value')}"
                if payload.get("kind") == "disagreement"
                else "Pending review"
            )
            status = action.decision if action else "pending"
            review_rows += (
                f"<tr><td>{self._file_link(item_path, item_path.name)}</td>"
                f"<td>{html.escape(str(issue))}</td><td>{html.escape(str(reason))}</td>"
                f"<td>{html.escape(status)}</td></tr>"
            )
            review_rows += f"""<tr><td colspan="4">
<form method="post" action="/adjudicate" class="inline">
<input type="hidden" name="run_id" value="{html.escape(run_id)}"><input type="hidden" name="item" value="{html.escape(item_rel)}">
<label>Decision<select name="decision"><option>approve</option><option>edit</option><option>reject</option><option>defer</option></select></label>
<label>Reviewer<input name="reviewer" required></label><label>Rationale<input name="rationale" required></label>
<label>Edited row JSON<textarea name="edited_row_json" placeholder='Required only for edit'></textarea></label>
<button type="submit">Record review action</button></form></td></tr>"""
        if not review_rows:
            review_rows = "<tr><td colspan='4'>No automated QA flags. Human evidence review is tracked separately.</td></tr>"

        gate_form = ""
        if self.runner.project.governance.enforce_review_gates and manifest.pending_gate:
            resume_control = self._local_execution_control(
                run_id, "Resume locally after recording approval"
            )
            gate_form = f"""<section><h2>Enforced gate</h2><p>Waiting at <code>{html.escape(manifest.pending_gate)}</code>.</p>
<form method="post" action="/gate" class="inline"><input type="hidden" name="run_id" value="{html.escape(run_id)}">
<input type="hidden" name="stage_id" value="{html.escape(manifest.pending_gate)}">
<label>Decision<select name="decision"><option>approve</option><option>reject</option></select></label>
<label>Reviewer<input name="reviewer" required></label><label>Rationale<input name="rationale" required></label>
<button type="submit">Record gate action</button></form>{resume_control}</section>"""

        release_form = ""
        if (
            self.runner.project.governance.enforce_review_gates
            and manifest.status == "completed"
            and manifest.release_status != "released"
        ):
            release_form = f"""<section><h2>Release</h2><form method="post" action="/release" class="inline">
<input type="hidden" name="run_id" value="{html.escape(run_id)}">
<label>Reviewer<input name="reviewer" required></label><label>Rationale<input name="rationale" required></label>
<button type="submit">Release run for export</button></form></section>"""

        exports = sorted(export_root.glob("*.xlsx")) if export_root.exists() else []
        export_links = "".join(f"<li>{self._file_link(path, path.name)}</li>" for path in exports)
        if not export_links:
            export_links = "<li>No exports yet.</li>"
        export_form = f"""<form method="post" action="/export" class="inline-link">
<input type="hidden" name="run_id" value="{html.escape(run_id)}"><button type="submit" class="secondary">Export the model's raw output (unreviewed)</button></form>"""
        status_word = {'completed': 'Coding finished', 'awaiting_review': 'Coding finished, waiting at a review gate',
                       'blocked_validation': 'Stopped: some output did not match the expected format'}.get(manifest.status, manifest.status)
        cost = (f'USD {manifest.run_cost_usd:.4f} (study total USD {manifest.project_cost_usd or 0:.4f})'
                if manifest.run_cost_usd is not None else 'Not tracked (offline model)')
        from qualframe.ui_kit import friendly_time
        facts = (f'<dl class="run-facts"><dt>Status</dt><dd>{html.escape(status_word)}</dd>'
                 f'<dt>Finished</dt><dd>{html.escape(friendly_time(manifest.completed_at_utc))}</dd>'
                 f'<dt>Recorded cost</dt><dd>{html.escape(cost)}</dd>'
                 f'<dt>Automated checks</dt><dd>{manifest.qa_failure_count} format flag(s), {manifest.structured_output_failure_count} validation failure(s)</dd>'
                 f'<dt>Run ID</dt><dd><code>{html.escape(run_id)}</code></dd>'
                 f'<dt>Configuration fingerprint</dt><dd><code>{html.escape(manifest.configuration_fingerprint or "not recorded")}</code></dd></dl>')
        qa_section = (f'<section><h2>Automated checks to review</h2><p>These flags come from format checks on the model output, separate from your evidence review.</p>'
                      f'<table><thead><tr><th>Item</th><th>Issue</th><th>Reason</th><th>Latest action</th></tr></thead><tbody>{review_rows}</tbody></table></section>'
                      if review_items else "")
        return f"""
<section><h2>About this run</h2>{facts}</section>
{gate_form}{release_form}{evidence_section if not evidence_index.exists() else ""}{qa_section}
<section><h2>Files</h2><p>Everything this run produced is kept in the study folder. The run record lists every input and prompt with its hash.</p>
<ul><li>{self._file_link(manifest_path, "Run record (JSON)")}</li></ul>
<details><summary>Model output files ({len(artifact_links)})</summary><ul>{''.join(artifact_links)}</ul></details>
<details><summary>Raw output export</summary><p>Raw output is the model's proposals before your review. For your findings, use the reviewed export on the Results page.</p>{export_form}<ul>{export_links}</ul></details>
<table class="compact"><thead><tr><th>Stage</th><th>Output files</th></tr></thead><tbody>{stage_rows}</tbody></table></section>"""

    def _render_planned_run(
        self,
        run_id: str,
        plan: RunPlan,
        plan_path: Path,
    ) -> str:
        stage_counts: dict[str, int] = {}
        for item in plan.planned_stage_runs:
            stage_counts[item.stage_id] = stage_counts.get(item.stage_id, 0) + 1
        stage_rows = "".join(
            f"<tr><td>{html.escape(stage.replace('_', ' ').title())}</td><td>{count}</td></tr>"
            for stage, count in stage_counts.items()
        ) or "<tr><td colspan='2'>No stage calls are currently planned.</td></tr>"
        study_name = self.runner.project.title or self.runner.project.project_id
        classification = self.runner.project.data_classification or "not declared"
        execution_control = self._local_execution_control(
            run_id,
            f"Run locally with {self.runner.project.provider.name}",
        )
        return f"""
<div class="cards">
<div class="card"><div class="label">Study</div><div class="value">{html.escape(study_name)}</div></div>
<div class="card"><div class="label">Data classification</div><div class="value">{html.escape(classification.title())}</div></div>
<div class="card"><div class="label">Run</div><div class="value">{html.escape(run_id.replace('_', ' '))}</div></div>
<div class="card"><div class="label">Status</div><div class="value">Dry-run plan</div></div>
<div class="card"><div class="label">Inputs</div><div class="value">{len(plan.discovered_inputs)}</div></div>
<div class="card"><div class="label">Planned stage calls</div><div class="value">{len(plan.planned_stage_runs)}</div></div>
</div>
<section><h2>Planned workflow</h2><p>No model request was sent. This plan records the configuration and work that execution would perform.</p>
<table><thead><tr><th>Stage</th><th>Planned calls</th></tr></thead><tbody>{stage_rows}</tbody></table>
<p><strong>Configuration:</strong> <code>{html.escape(plan.configuration_fingerprint or 'Not available')}</code></p>
<p>{self._file_link(plan_path, "Open machine-readable run plan")}</p>
{execution_control}<p class="muted">Paid execution requires explicit approval of the current plan; advanced filters remain command-line operations.</p></section>"""

    def _local_execution_control(self, run_id: str, label: str) -> str:
        try:
            self._managed_project_path()
        except ValueError:
            return ""
        if self.runner.project.provider.name not in _LOCAL_EXECUTION_PROVIDERS:
            if self.runner.project.provider.name not in _PAID_EXECUTION_PROVIDERS:
                return ""
            plan_path = self._run_root(self.artifacts_dir, run_id) / "run_plan.json"
            if not plan_path.exists():
                return ""
            plan = RunPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
            cost = self.runner._build_cost_controller(run_id=run_id, artifact_root=plan_path.parent)
            if cost is None:
                return "<p>Configure a provider, verified prices, and a study ceiling first.</p>"
            if cost.unresolved_requests():
                return "<p>Prior request usage is unresolved. Reconcile the preserved request record before starting another paid run.</p>"
            return f'''<form method="post" action="/execute">
<input type="hidden" name="run_id" value="{html.escape(run_id)}">
<input type="hidden" name="fingerprint" value="{html.escape(plan.configuration_fingerprint or '')}">
<p>Paid coding: {html.escape(self.runner.project.provider.name)} / {html.escape(self.runner.project.provider.model or '')}. Study ceiling: USD {cost.policy.absolute_limit_usd:.2f}. Recorded usage cost: USD {cost.project_cost_usd():.4f}.</p>
<p>Selected source text and codebook will be sent to this provider. Local token estimates are not a provider billing guarantee. Uncertain requests pause for reconciliation.</p>
<label>Researcher name<input name="actor" required></label>
<label>Reason for this run<input name="rationale" required></label>
<label class="check"><input name="live_confirmed" type="checkbox" value="yes" required>I approve sending this study material and spending up to the displayed study ceiling.</label>
<button type="submit">Approve and start paid coding</button></form>'''
        return f"""<form method="post" action="/execute"><input type="hidden" name="run_id" value="{html.escape(run_id)}"><button type="submit">{html.escape(label)}</button></form><p class="muted">This uses only the configured local mock or checked-in cache. It does not contact an external model API.</p>"""

    def _job_snapshot(self, run_id: str | None) -> ExecutionJob | None:
        if not run_id:
            return None
        with self._job_lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            return ExecutionJob(
                run_id=job.run_id,
                status=job.status,
                progress=list(job.progress),
                error=job.error,
            )

    def start_local_execution(self, run_id: str, *, approval: dict[str, str] | None = None) -> None:
        project_path = self._managed_project_path()
        provider_name = self.runner.project.provider.name
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        plan_path = artifact_root / "run_plan.json"
        if not plan_path.exists():
            raise ValueError("Create a dry-run plan before starting local execution.")
        plan = RunPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if plan.project_id != self.runner.project.project_id:
            raise ValueError("Run plan belongs to a different study.")
        if not plan.discovered_inputs:
            raise ValueError('Import a transcript before starting coding.')
        if any(stage.domain_iterations for stage in self.runner.pipeline.stages) and self.runner.project.data_classification != 'synthetic':
            reference = resolve_repo_path(self.repo_root, self.runner.project.paths['reference']) / 'codebook.xlsx'
            if not reference.exists():
                raise ValueError('Import the CFIR reference workbook before starting coding.')
        live = provider_name not in _LOCAL_EXECUTION_PROVIDERS
        if not live and self.runner.project.data_classification != "synthetic":
            raise PermissionError("Offline test models only run on test-data studies. Choose a model on the Run coding page.")
        if live:
            import os
            from qualframe.configuration_lock import create_configuration_lock
            if provider_name not in _PAID_EXECUTION_PROVIDERS:
                raise PermissionError("This provider is not enabled for browser execution.")
            approval = approval or {}
            if approval.get("live_confirmed") != "yes":
                raise PermissionError("Paid execution requires explicit study-data and spending approval.")
            actor, rationale = self.study_workspace._validate_action_fields(
                approval.get("actor", ""), approval.get("rationale", ""))
            fingerprint = create_configuration_lock(project_path).fingerprint_sha256
            if not plan.configuration_fingerprint or approval.get("fingerprint") != plan.configuration_fingerprint or fingerprint != plan.configuration_fingerprint:
                raise ValueError("Configuration changed; create and approve a new preflight plan.")
            cost = self.runner._build_cost_controller(run_id=run_id, artifact_root=artifact_root)
            if cost is None:
                raise ValueError("Paid execution requires pricing and an absolute study ceiling.")
            if cost.unresolved_requests():
                raise ValueError("Prior request usage is unresolved. Reconcile it before starting another paid run.")
            from qualframe.coding_ui import is_local_endpoint
            local_endpoint = provider_name == "openai_compatible" and is_local_endpoint(self.runner.project.provider.base_url)
            if not local_endpoint and not os.getenv(self.runner.project.provider.api_key_env or ""):
                raise ValueError("Enter your API key in provider settings for this app session.")
        with self._job_lock:
            if any(job.status == "running" for job in self._jobs.values()):
                raise ValueError("A study run is already in progress.")
            if live:
                import uuid
                (artifact_root / f"execution-approval-{uuid.uuid4().hex}.json").write_text(
                    json.dumps({"actor": actor, "rationale": rationale,
                                "configuration_fingerprint": fingerprint,
                                "absolute_limit_usd": cost.policy.absolute_limit_usd,
                                "governance_confirmed": True,
                                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                "run_id": run_id}, indent=2), encoding="utf-8")
            prior = self._jobs.get(run_id)
            if prior is not None and prior.status == "running":
                raise ValueError("This local run is already in progress.")
            self._jobs[run_id] = ExecutionJob(run_id=run_id)
        thread = threading.Thread(
            target=self._execute_local_job,
            args=(project_path, plan, run_id),
            name=f"qualframe-{run_id}",
            daemon=True,
        )
        thread.start()

    def _execute_local_job(self, project_path: Path, plan: RunPlan, run_id: str) -> None:
        def progress(stage_id: str) -> None:
            with self._job_lock:
                self._jobs[run_id].progress.append(f"Running stage: {stage_id}")

        try:
            runner = ProjectRunner(project_path)
            manifest_path = runner.execute_run_plan(
                plan,
                run_id,
                progress_callback=progress,
            )
            manifest = RunManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if manifest.status in {'completed', 'awaiting_review'}:
                write_evidence_review_index(project_manifest_path=project_path, run_id=run_id)
        except CostApprovalRequired as exc:
            with self._job_lock:
                self._jobs[run_id].status = "paused"
                self._jobs[run_id].progress.append(str(exc))
        except Exception as exc:  # surfaced in the local job panel and resumable
            with self._job_lock:
                self._jobs[run_id].status = "failed"
                self._jobs[run_id].error = f"{type(exc).__name__}: {exc}"
        else:
            with self._job_lock:
                self._jobs[run_id].status = manifest.status
                self._jobs[run_id].progress.append(
                    f"Run finished with status: {manifest.status}"
                )

    def _render_cost_pause(
        self,
        run_id: str,
        pause: CostPauseRecord,
        pause_path: Path,
    ) -> str:
        remaining = max(pause.absolute_limit_usd - pause.current_cost_usd, 0)
        notification = pause.notification_status.replace("_", " ")
        error = (
            f"<p class='muted'>Notification detail: {html.escape(pause.notification_error)}</p>"
            if pause.notification_error
            else ""
        )
        resume_control = self._local_execution_control(
            run_id, "Resume locally after recording approval"
        )
        return f"""
<div class="cards">
<div class="card"><div class="label">Project</div><div class="value">{html.escape(pause.project_id.replace('_', ' ').title())}</div></div>
<div class="card"><div class="label">Run</div><div class="value">{html.escape(run_id.replace('_', ' '))}</div></div>
<div class="card"><div class="label">Status</div><div class="value">Paused for cost approval</div></div>
<div class="card"><div class="label">Spent so far</div><div class="value">USD {pause.current_cost_usd:.4f}</div></div>
<div class="card"><div class="label">Projected after next request</div><div class="value">USD {pause.projected_cost_usd:.4f}</div></div>
<div class="card"><div class="label">Remaining absolute ceiling</div><div class="value">USD {remaining:.4f}</div></div>
</div>
<section><h2>Review spending boundary</h2>
<p>The next request for <strong>{html.escape(pause.stage_id)}</strong> on <strong>{html.escape(pause.input_label)}</strong> may cross the USD {pause.threshold_usd:.2f} boundary. No request was sent.</p>
<p>Email notification: <strong>{html.escape(notification)}</strong>. Email delivery never approves this request.</p>{error}
<form method="post" action="/cost" class="inline">
<input type="hidden" name="run_id" value="{html.escape(run_id)}">
<input type="hidden" name="threshold_usd" value="{pause.threshold_usd}">
<label>Decision<select name="decision"><option value="approve">Approve this boundary</option><option value="stop">Stop the run</option></select></label>
<label>Researcher name<input name="reviewer" required></label>
<label>Reason<textarea name="rationale" required></textarea></label>
<button type="submit">Record decision</button></form>
{resume_control}<p class="muted">The runner rechecks the append-only approval record before submitting any request.</p>
<p>{self._file_link(pause_path, "Open cost pause record")}</p></section>"""

    def handle_app_action(self, path: str, form: dict[str, list[str]]) -> str:
        """Application-level actions; returns the redirect location."""
        if path == "/settings/name":
            from qualframe.app_workspace import write_settings
            name = form.get("researcher_name", [""])[0].strip()
            if not name:
                raise ValueError("Enter your name.")
            write_settings(self.repo_root, researcher_name=name[:120])
            back = form.get("back", ["/home"])[0]
            if not back.startswith("/") or back.startswith("//"):
                back = "/home"
            joiner = "&" if "?" in back else "?"
            return back + joiner + urlencode({"message": f"Decisions will be recorded as {name}."})
        if path == "/demo":
            with self._job_lock:
                if any(job.status == "running" for job in self._jobs.values()):
                    raise ValueError("Wait for the current run to finish before opening the demo.")
            from qualframe.demo_study import create_demo_study
            created, project_path, run_id = create_demo_study(self.repo_root)
            self._activate_runner(ProjectRunner(project_path))
            self._selected_run = run_id
            return "/?" + urlencode({"message": "Demo study ready: six fictional interviews, coded with recorded responses. Nothing was sent anywhere."})
        if path == "/provider/offline":
            choice = form.get("preset", [""])[0]
            project_path = self._managed_project_path()
            if self.runner.project.data_classification != "synthetic":
                raise ValueError("Offline test models are available only for synthetic studies.")
            import yaml
            data = yaml.safe_load(project_path.read_text(encoding="utf-8"))
            if choice == "mock":
                data["provider"] = {"name": "mock", "model": "synthetic-contract-fixture", "temperature": 0.0, "max_tokens": 4000}
            elif choice.startswith("recorded:"):
                from qualframe.providers.recorded_provider import load_recording_info
                recording = choice.removeprefix("recorded:")
                load_recording_info(recording)
                data["provider"] = {"name": "recorded", "model": recording, "temperature": None, "max_tokens": 16000}
            else:
                raise ValueError("Choose a model.")
            data.pop("cost_policy", None)
            data.pop("pricing_snapshot", None)
            temporary = project_path.with_name(".project-offline.yaml")
            temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            temporary.replace(project_path)
            self._refresh_runner()
            return "/configure?" + urlencode({"message": "Offline model selected. Nothing will be sent anywhere."})
        if path == "/coding/start":
            self._managed_project_path()
            from qualframe.coding_ui import coding_blockers
            blockers = coding_blockers(self)
            if blockers:
                raise ValueError("Finish setting up the run first.")
            self.fill_identity(form, "Started coding run")
            run_id = self.runner._make_run_id()
            plan = self.runner.build_run_plan()
            self.runner.save_run_plan(plan, run_id)
            approval = {k: v[0] for k, v in form.items()}
            approval["fingerprint"] = plan.configuration_fingerprint or ""
            self.start_local_execution(run_id, approval=approval)
            self._selected_run = run_id
            return "/?" + urlencode({"run_id": run_id})
        raise ValueError("Unknown action.")

    def handle_action(self, path: str, form: dict[str, list[str]]) -> tuple[str, str]:
        def required(name: str) -> str:
            value = form.get(name, [""])[0].strip()
            if not value:
                raise ValueError(f"Missing required field: {name}")
            return value

        if path == "/plan":
            run_id = self.runner._make_run_id()
            plan = self.runner.build_run_plan()
            self.runner.save_run_plan(plan, run_id)
            return run_id, "Created a dry-run plan. No model request was sent."

        if path == '/study/open':
            with self._job_lock:
                if any(job.status == 'running' for job in self._jobs.values()):
                    raise ValueError('Wait for the current run before opening another study.')
                name = required('study_id')
                project_path = (self.repo_root / 'studies' / name / 'project.yaml').resolve()
                self.study_workspace.managed_study_root(project_path)
                self._activate_runner(ProjectRunner(project_path))
            return '', 'Opened study.'

        if path in {'/repeats/prepare', '/repeats/start', '/repeats/resume'}:
            from qualframe.repeat_ui import prepare_repeat_form, start_repeat_job
            if path == '/repeats/prepare':
                form['experiment'] = [prepare_repeat_form(self, form)]
                return '', 'Prepared repeated coding. No model requests sent.'
            form['experiment'] = [start_repeat_job(self, form)]
            return '', 'Started sequential repeated coding.'

        if path == '/benchmark/save':
            from qualframe.benchmark_ui import save_benchmark_form
            return save_benchmark_form(self, form)
        if path == '/stability/save':
            if required('study_identity') != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study.')
            self._managed_project_path()
            from qualframe.repeat_comparison import write_repeat_report, experiment_report_scope
            experiment_context = None
            if form.get('experiment', [''])[0]:
                ids, experiment_context = experiment_report_scope(self._managed_project_path(), required('experiment'))
                roots = [self.artifacts_dir / r for r in ids]
            else:
                roots = [self._run_root(self.artifacts_dir, r) for r in form.get('run', [])]
            written = write_repeat_report(self.repo_root, self.artifacts_dir, roots,
                expected_report_id=required('report_id'), experiment_context=experiment_context)
            return '', f'Saved frozen evaluation {written.stem[10:22]}.'

        if path == '/empty-output/review':
            from qualframe.empty_output_ui import handle_empty_output_action
            return handle_empty_output_action(self, form)

        run_id = required("run_id")
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        review_root = self.review_dir / run_id

        if path == "/execute":
            self.start_local_execution(run_id, approval={k: v[0] for k, v in form.items()})
            return run_id, "Started local background execution."

        if path == "/prepare-evidence":
            index_path = write_evidence_review_index(
                project_manifest_path=self._managed_project_path(),
                run_id=run_id,
            )
            count = len(load_evidence_review_records(index_path))
            return run_id, f"Prepared {count} exact-evidence review item(s)."

        if path == "/evidence-action":
            self.fill_identity(form, "")
            item_id = required("item")
            index_path = artifact_root / "evidence_review" / "index.json"
            records = load_run_records(index_path, review_root)
            record = next((item for item in records if item.record_id == item_id), None)
            if record is None:
                raise ValueError("Evidence review item was not found in this run.")
            if form.get('study_identity', [self.runner.project.project_id])[0] != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study. Reopen it before recording a decision.')
            decision = required("decision")
            prior = latest_evidence_action_by_record(review_root).get(item_id)
            if decision == 'accept' and prior and prior.derived_artifact_path:
                derived = json.loads((artifact_root / prior.derived_artifact_path).read_text(encoding='utf-8'))
                decision = 'edit'
                form['edited_start'] = [str(derived['evidence_span']['start_offset'])]
                form['edited_end'] = [str(derived['evidence_span']['end_offset'])]
                form['edited_code_id'] = [derived['assignment']['code_id']]
            edited_start = int(required("edited_start")) if decision == "edit" else None
            edited_end = int(required("edited_end")) if decision == "edit" else None
            edited_code_id = required("edited_code_id") if decision == "edit" else None
            catalog = json.loads(index_path.read_text(encoding='utf-8')).get('codebook') or {}
            codes = catalog.get('codes') or ([c.model_dump() for c in self.runner.codebook.codes] if self.runner.codebook else [])
            if decision == 'edit' and edited_code_id not in {c['id'] for c in codes}:
                raise ValueError('Choose a code from this review codebook.')
            rationale = form.get('rationale', [''])[0].strip() or {'accept': 'Accepted proposal.', 'reject': 'Rejected proposal.', 'edit': 'Changed code or source passage.', 'defer': 'Deferred for later review.'}.get(decision, 'Recorded decision.')
            action = append_evidence_review_action(
                record=record,
                source_path=resolve_repo_path(self.repo_root, record.source_path),
                review_dir=review_root,
                artifact_root=artifact_root,
                decision=decision,
                reviewer=required("reviewer"),
                rationale=rationale,
                edited_start=edited_start,
                edited_end=edited_end,
                edited_code_id=edited_code_id,
                codebook_id=catalog.get("id"), codebook_version=catalog.get("version"),
                context_policy=run_context_policy(self._managed_project_path(), artifact_root),
            )
            try:
                record_review_timing(review_root, action.action_id, float(form.get('seconds_on_item', ['0'])[0] or 0))
            except ValueError:
                pass
            self.review_dir.mkdir(parents=True, exist_ok=True)
            (self.review_dir / 'reviewer.json').write_text(json.dumps({'name': required('reviewer')}), encoding='utf-8')
            if form.get('advance', [''])[0] == 'yes':
                latest = latest_evidence_action_by_record(review_root)
                position = records.index(record)
                ordered = records[position+1:] + records[:position]
                next_record = next((r for r in ordered if r.record_id not in latest or latest[r.record_id].decision == 'defer'), None)
                form['item'] = [next_record.record_id if next_record else record.record_id]
            return run_id, f"Recorded evidence decision {action.decision}."

        if path == "/evidence-add":
            self.fill_identity(form, "")
            if form.get('study_identity', [self.runner.project.project_id])[0] != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study. Reopen it before adding a code.')
            try:
                start, end = int(required("added_start")), int(required("added_end"))
            except ValueError:
                raise ValueError("Select the passage in the transcript first.") from None
            added = add_researcher_coding(
                project_manifest_path=self._managed_project_path(), run_id=run_id,
                source_path=required("source_path"), start=start, end=end,
                code_id=required("added_code_id"), reviewer=required("reviewer"),
                rationale=form.get("rationale", [""])[0],
            )
            form['item'] = [form.get('item', [added.record_id])[0] or added.record_id]
            return run_id, f"Added {added.code_label or added.proposed_code_id}."

        if path == '/synthesis/start':
            from qualframe.synthesis_workspace import start_synthesis_job
            form['job'] = [start_synthesis_job(self, run_id, form)]
            return run_id, 'Started synthesis. Review the proposed summaries when ready.'

        if path in {'/synthesis/review', '/synthesis/export'}:
            if required('study_identity') != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study.')
            from qualframe.synthesis_review import job_root, read_job, review_statement, latest_summary_actions, export_synthesis
            from qualframe.synthesis_execution import current_plan
            target = job_root(artifact_root, required('job'))
            status, plan, records = read_job(target)
            current_plan(ProjectRunner(self._managed_project_path()), artifact_root, status['plan_id'])
            if path == '/synthesis/export':
                output = export_synthesis(target, inputs_current=True)
                return run_id, f'Exported reviewed synthesis {output.stem[-12:]}.'
            review_statement(target, required('item'), decision=required('decision'),
                reviewer=required('reviewer'), rationale=form.get('rationale',[''])[0],
                edited_text=form.get('edited_text',[''])[0], evidence_ids=form.get('evidence_id',[]))
            (self.review_dir/'reviewer.json').write_text(json.dumps({'name':required('reviewer')}),encoding='utf-8')
            actions=latest_summary_actions(target)
            position=next(i for i,r in enumerate(records) if r['statement_id']==required('item'))
            next_item=next((r for r in records[position+1:]+records[:position+1] if actions.get(r['statement_id'],{}).get('decision') not in {'accept','edit','reject'}),None)
            form['item']=[next_item['statement_id'] if next_item else '']
            return run_id, 'Recorded summary decision.'

        if path == '/comparison/save':
            if required('study_identity') != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study.')
            from qualframe.run_comparison import write_comparison
            path = write_comparison(self.repo_root, artifact_root, self._run_root(self.artifacts_dir, required('right_id')))
            return run_id, f'Saved comparison {path.stem[11:23]}.'

        if path == '/analysis/prepare-synthesis':
            if required('study_identity') != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study.')
            identity = required('snapshot')
            if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
                raise ValueError('Select a frozen evidence snapshot.')
            from qualframe.synthesis_plan import write_synthesis_plan
            written = write_synthesis_plan(self.repo_root, artifact_root, review_root,
                artifact_root/'analysis'/f'snapshot-{identity}.json', required('grouping'),
                project_path=self._managed_project_path(),
                metadata_field=form.get('metadata_field', [''])[0],
                metadata_values=form.get('metadata_value'),
                missing_policy=form.get('missing_policy', ['error'])[0])
            return run_id, f'Prepared synthesis plan {written.stem[15:27]}. No model requests sent.'

        if path == "/analysis/freeze":
            if required('study_identity') != self.runner.project.project_id:
                raise ValueError('This tab belongs to another study. Reopen analysis before freezing.')
            from qualframe.reviewed_analysis import freeze_reviewed_snapshot
            freeze_reviewed_snapshot(self.repo_root, artifact_root, review_root, required('reviewer'), selected_sources=form.get('source', []))
            return run_id, 'Results saved as a snapshot.'

        if path == "/export-evidence":
            written = export_evidence_review_package(
                project_manifest_path=self._managed_project_path(),
                run_id=run_id,
                require_released=(
                    self.runner.project.governance.enforce_review_gates
                    and self.runner.project.governance.require_release_for_export
                ),
            )
            return run_id, "Exported the reviewed coding (Excel and JSON). Download links are below." if form.get("return_to", [""])[0] == "analysis" else "Exported the reviewed coding (Excel and JSON)."

        if path == "/cost":
            pause_path = artifact_root / "cost_pause.json"
            if not pause_path.exists():
                raise ValueError("This run has no active cost pause.")
            pause = CostPauseRecord.model_validate_json(
                pause_path.read_text(encoding="utf-8")
            )
            threshold = float(required("threshold_usd"))
            if threshold != pause.threshold_usd:
                raise ValueError("Cost threshold does not match the persisted pause.")
            action = append_cost_approval(
                self.logs_dir / "cost_approvals.jsonl",
                project_id=pause.project_id,
                run_id=run_id,
                threshold_usd=threshold,
                decision=required("decision"),
                reviewer=required("reviewer"),
                rationale=required("rationale"),
            )
            instruction = (
                " Resume the same run to continue."
                if action.decision == "approve"
                else " The run remains stopped."
            )
            return run_id, f"Recorded cost decision {action.action_id}.{instruction}"

        if path == "/adjudicate":
            edited_text = form.get("edited_row_json", [""])[0].strip()
            edited_row: dict[str, str] | None = None
            if edited_text:
                decoded = json.loads(edited_text)
                if not isinstance(decoded, dict):
                    raise ValueError("Edited row JSON must be an object.")
                edited_row = {str(key): str(value) for key, value in decoded.items()}
            action = append_adjudication_action(
                review_dir=review_root,
                artifact_root=artifact_root,
                run_id=run_id,
                item_path=review_root / required("item"),
                decision=required("decision"),
                reviewer=required("reviewer"),
                rationale=required("rationale"),
                edited_row=edited_row,
            )
            return run_id, f"Recorded adjudication action {action.action_id}."

        if path == "/gate":
            stage_id = required("stage_id")
            index = artifact_root / 'evidence_review/index.json'
            if index.exists() and required('decision') == 'approve':
                latest = latest_evidence_action_by_record(review_root)
                if any(r.stage_id == stage_id and (r.record_id not in latest or latest[r.record_id].decision == 'defer') for r in load_evidence_review_records(index)):
                    raise ValueError('Resolve every coding proposal before approving this review gate.')
            manifest = RunManifest.model_validate_json(
                (artifact_root / "run_manifest.json").read_text(encoding="utf-8")
            )
            if not self.runner.project.governance.enforce_review_gates:
                raise ValueError("This project does not enforce review gates.")
            if manifest.pending_gate != stage_id:
                raise ValueError("The selected stage is not the run's pending gate.")
            action = append_gate_action(
                artifact_root,
                run_id=run_id,
                stage_id=stage_id,
                decision=required("decision"),
                reviewer=required("reviewer"),
                rationale=required("rationale"),
            )
            return run_id, f"Recorded gate action {action.action_id}; resume the same run when ready."

        if path == "/release":
            required_gates = {
                stage.id
                for stage in self.runner.pipeline.stages
                if stage.enabled and stage.prompt_ref and stage.review_gate
            }
            missing = required_gates - approved_gate_ids(artifact_root)
            if missing:
                raise ValueError("Unapproved gates remain: " + ", ".join(sorted(missing)))
            action = append_release_action(
                artifact_root,
                run_id=run_id,
                reviewer=required("reviewer"),
                rationale=required("rationale"),
            )
            return run_id, f"Released run with action {action.action_id}."

        if path == "/export":
            written = export_run(
                run_id,
                artifact_root,
                self.exports_dir,
                require_released=(
                    self.runner.project.governance.enforce_review_gates
                    and self.runner.project.governance.require_release_for_export
                ),
                require_validated=self.runner.project.structured_output.enforce,
            )
            return run_id, f"Exported {len(written)} workbook(s)."

        raise ValueError("Unknown dashboard action.")


def make_handler(app: DashboardApp) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def _local_request_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if host not in allowed or (origin is not None and origin != f"http://{host}"):
                self.send_error(HTTPStatus.FORBIDDEN, "Use the local QualFrame browser address.")
                return False
            return True

        def do_GET(self) -> None:
            if not self._local_request_allowed():
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            kept = {k: v[0] for k, v in query.items() if k not in {"message", "error"}}
            app._current_path = parsed.path + ("?" + urlencode(kept) if kept else "")
            if parsed.path.startswith("/static/"):
                self._send_static(parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/download/example-codebook.xlsx":
                from qualframe.app_workspace import APP_ROOT
                data = (APP_ROOT / "demo/datasets/ai-scribe/codebook.xlsx").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="example-codebook.xlsx"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            message = query.get("message", [""])[0]
            error = query.get("error", [""])[0]
            if parsed.path == "/home" or (app.runner is None and parsed.path not in {"/setup"}):
                self._send_html(app.render_home(message, error).encode("utf-8"))
                return
            if parsed.path in {"/review", "/results"}:
                from qualframe.study_status import review_run
                run = review_run(app)
                if run is None:
                    self._redirect("/?" + urlencode({"message": "Run coding first; review opens when proposals are ready."}))
                else:
                    target = "/evidence?" if parsed.path == "/review" else "/analysis?"
                    self._redirect(target + urlencode({"run_id": run}))
                return
            if parsed.path == "/methods":
                from qualframe.methods_record import build_methods_record, methods_markdown, render_methods_page
                run = query.get("run_id", [""])[0]
                try:
                    fmt = query.get("format", [""])[0]
                    if fmt in {"md", "json"}:
                        record = build_methods_record(app, run)
                        data = (methods_markdown(record) if fmt == "md" else json.dumps(record, indent=2)).encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/markdown; charset=utf-8" if fmt == "md" else "application/json")
                        self.send_header("Content-Disposition", f'attachment; filename="methods-record-{run}.{fmt}"')
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    content = render_methods_page(app, run)
                except (ValueError, OSError) as exc:
                    content = app._render_workspace_page(title="Methods record", intro="", body=f"<div class='error'>{html.escape(str(exc))}</div>", active="analysis")
                self._send_html(content.encode("utf-8"))
                return
            if parsed.path in {"/codebook", "/sources"}:
                content = app.render_codebook(message, error) if parsed.path == "/codebook" else app.render_imports(message, error)
                self._send_html(content.encode("utf-8"))
                return
            if parsed.path == "/codebook/excel":
                try:
                    workflow = ExcelImportWorkflow(app.study_workspace, app._managed_project_path())
                    body = mapping_view(workflow, {k: v[0] for k, v in query.items()})
                    content = app._render_workspace_page(title="Import Excel codebook", intro="Preview, map, and validate your codebook.", body=body)
                except ValueError as exc:
                    content = app.render_imports(error=str(exc))
                self._send_html(content.encode("utf-8"))
                return
            if parsed.path == "/setup":
                content = app.render_setup(
                    message=query.get("message", [""])[0],
                    error=query.get("error", [""])[0],
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path == "/imports":
                content = app.render_imports(
                    message=query.get("message", [""])[0],
                    error=query.get("error", [""])[0],
                ).encode("utf-8")
                self._send_html(content)
                return
            if parsed.path == "/configure":
                content = app.render_configure(
                    message=query.get("message", [""])[0],
                    error=query.get("error", [""])[0],
                ).encode("utf-8")
                self._send_html(content)
                return
            if parsed.path in {'/stability', '/repeats', '/empty-output'}:
                try:
                    if parsed.path == '/stability':
                        from qualframe.stability_ui import render_stability
                        content = render_stability(app, query.get('run', []), query.get('message', [''])[0], query.get('experiment', [''])[0])
                    elif parsed.path == '/repeats':
                        from qualframe.repeat_ui import render_repeats
                        content = render_repeats(app, query.get('experiment', [''])[0], query.get('message', [''])[0])
                    else:
                        from qualframe.empty_output_ui import render_empty_output_review
                        content = render_empty_output_review(app, query.get('run_id', [''])[0], query.get('source', [''])[0], query.get('message', [''])[0])
                except (ValueError, OSError, RuntimeError) as exc:
                    content = app._render_workspace_page(title='Review and evaluation', intro='The requested view could not be prepared.', body=f'<p>{html.escape(str(exc))}</p><a href="/compare">Compare runs</a>')
                self._send_html(content.encode('utf-8'))
                return
            if parsed.path == '/benchmark':
                from qualframe.benchmark_ui import render_benchmark
                try:
                    content = render_benchmark(app, query.get('left', [''])[0], query.get('right', [''])[0], query.get('message', [''])[0])
                except (ValueError, OSError, RuntimeError) as exc:
                    content = app._render_workspace_page(title='Detailed span benchmark', intro='The selected runs cannot be benchmarked.', body=f'<p>{html.escape(str(exc))}</p><a href="/compare">Choose runs</a>')
                self._send_html(content.encode('utf-8'))
                return
            if parsed.path == '/compare':
                from qualframe.comparison_ui import render_comparison
                try:
                    content = render_comparison(app, query.get('left',[''])[0], query.get('right',[''])[0], query.get('message',[''])[0])
                except (ValueError, OSError) as exc:
                    content = app._render_workspace_page(title='Compare coding runs', intro='The selected runs cannot be compared.', body=f'<p>{html.escape(str(exc))}</p><a href="/compare">Choose runs</a>')
                self._send_html(content.encode('utf-8'))
                return
            if parsed.path == '/synthesis':
                from qualframe.synthesis_workspace import render_synthesis_review
                try:
                    content=render_synthesis_review(app, query.get('run_id',[''])[0], query.get('job',[''])[0], query.get('item',[''])[0], query.get('message',[''])[0])
                except (ValueError,OSError,RuntimeError) as exc:
                    content=app._render_workspace_page(title='Review proposed summaries',intro='Open a synthesis job from Analyze evidence.',body=f'<p>{html.escape(str(exc))}</p>')
                self._send_html(content.encode("utf-8"))
                return
            if parsed.path == "/analysis":
                from qualframe.analysis_ui import render_analysis
                try:
                    content = render_analysis(app, query.get('run_id', [''])[0],
                        query.get('snapshot', [''])[0], query.get('code', [''])[0],
                        query.get('source', [''])[0], query.get('message', [''])[0])
                except (ValueError, OSError) as exc:
                    content = app._render_workspace_page(title='Analyze reviewed evidence',
                        intro='Select a reviewed run to begin.', body=f'<p>{html.escape(str(exc))}</p>')
                self._send_html(content.encode('utf-8'))
                return
            if parsed.path == "/evidence":
                try:
                    content = app.render_evidence(
                        run_id=query.get("run_id", [""])[0],
                        item_id=query.get("item", [""])[0],
                        message=query.get("message", [""])[0],
                        error=query.get("error", [""])[0],
                    ).encode("utf-8")
                except (ValueError, FileNotFoundError) as exc:
                    content = app._render_workspace_page(
                        title="Review exact evidence",
                        intro="The evidence review workspace could not be opened.",
                        body=f"<div class='error'>{html.escape(str(exc))}</div>",
                    ).encode("utf-8")
                self._send_html(content)
                return
            if parsed.path == "/presentation":
                presentation = app.repo_root / "demo" / "presentation" / "index.html"
                if not presentation.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content = presentation.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path == "/file":
                try:
                    path = app.resolve_file(query.get("path", [""])[0])
                except FileNotFoundError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                data = path.read_bytes()
                mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
                self.end_headers()
                self.wfile.write(data)
                return

            content = app.render(
                run_id=query.get("run_id", [None])[0],
                message=query.get("message", [""])[0],
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self) -> None:
            if not self._local_request_allowed():
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > _MAX_HTTP_BODY:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            body = self.rfile.read(length)
            request_path = urlparse(self.path).path
            if app.runner is None and request_path not in {"/demo", "/study/open", "/study/create", "/settings/name"}:
                self._redirect("/home")
                return
            if request_path.startswith("/import/"):
                back = "/codebook" if request_path in {"/import/codebook", "/import/cfir", "/import/excel"} else "/imports"
                fetch = self.headers.get("X-Requested-With") == "fetch"
                try:
                    fields, files = parse_multipart_form(
                        self.headers.get("Content-Type", ""), body, allow_multiple=True,
                    )
                    if request_path == "/import/excel":
                        uploads = files.get("upload") or []
                        if not uploads:
                            raise ValueError("Choose an Excel workbook.")
                        app.fill_identity(fields, "Imported codebook from Excel")
                        workflow = ExcelImportWorkflow(app.study_workspace, app._managed_project_path())
                        token = workflow.stage(uploads[0].filename, uploads[0].content,
                            fields.get("actor", [""])[0], fields.get("rationale", [""])[0])
                        self._redirect("/codebook/excel?" + urlencode({"token": token}))
                        return
                    message = app.handle_upload(request_path, fields, files)
                except (ValueError, FileExistsError) as exc:
                    if fetch:
                        self._send_text("ERROR " + str(exc))
                        return
                    location = back + "?" + urlencode({"error": str(exc)})
                else:
                    if fetch:
                        self._send_text("OK " + message)
                        return
                    location = back + "?" + urlencode({"message": message})
                self._redirect(location)
                return
            if request_path in {"/demo", "/settings/name", "/provider/offline", "/coding/start"}:
                try:
                    form = parse_qs(body.decode("utf-8"))
                    location = app.handle_app_action(request_path, form)
                except (ValueError, OSError, RuntimeError, PermissionError, FileExistsError) as exc:
                    fallback = {"/demo": "/home", "/settings/name": "/home"}.get(request_path, "/configure")
                    location = fallback + "?" + urlencode({"error": str(exc)})
                self._redirect(location)
                return

            try:
                form = parse_qs(body.decode("utf-8"))
            except UnicodeDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid form encoding")
                return
            if request_path in {"/codebook/preview", "/codebook/commit"}:
                options = {k: v[0] for k, v in form.items()}
                try:
                    workflow = ExcelImportWorkflow(app.study_workspace, app._managed_project_path())
                    if request_path == "/codebook/commit":
                        record = workflow.commit(options.get("token", ""), options)
                        app._refresh_runner()
                        self._redirect("/imports?" + urlencode({"message": f"Imported {record.original_filename}. Original workbook and mapping preserved."}))
                        return
                    content = app._render_workspace_page(title="Review Excel codebook", intro="Check the codes before changing the active version.", body=confirmation_view(workflow, options))
                except (ValueError, FileExistsError) as exc:
                    back = "/codebook/excel?" + urlencode({k: options[k] for k in ("token", "sheet", "header_row") if k in options})
                    content = app._render_workspace_page(title="Check codebook mapping", intro="Your active codebook has not changed.", body=f'<section><p class="error">{html.escape(str(exc))}</p><a href="{html.escape(back)}">Return to mapping</a></section>')
                self._send_html(content.encode("utf-8"))
                return
            if request_path == "/provider/save":
                try:
                    with app._job_lock:
                        if any(job.status == "running" for job in app._jobs.values()):
                            raise ValueError("Wait for the active run to finish before changing provider settings.")
                        app.fill_identity(form, "Chose model for coding")
                        values = {k: v[0] for k, v in form.items()}
                        settings = ProviderSetup.model_validate({
                            k: (values.get(k) == "yes" if k == "governance_confirmed" else (values.get(k) or None))
                            for k in ProviderSetup.model_fields if k in values})
                        save_provider_setup(app.study_workspace, app._managed_project_path(), settings,
                            actor=values.get("actor", ""), rationale=values.get("rationale", ""),
                            api_key=values.get("api_key", ""),
                            use_environment_key=values.get("use_environment_key") == "yes")
                        app._refresh_runner()
                except ValueError as exc:
                    message = str(exc)
                    if "validation error" in message:
                        message = "Check the model settings: " + "; ".join(
                            line.strip() for line in message.splitlines()[1:] if line.strip() and not line.strip().startswith("For further"))
                    self._redirect("/configure?" + urlencode({"error": message}))
                else:
                    self._redirect("/configure?" + urlencode({"message": "Model saved. No request has been sent."}))
                return
            if request_path in {"/instructions/save", "/instructions/use"}:
                try:
                    message = app.handle_instructions(request_path, form)
                except (ValueError, FileExistsError) as exc:
                    location = "/configure?" + urlencode({"error": str(exc)}) + "#instructions"
                else:
                    location = "/configure?" + urlencode({"message": message}) + "#instructions"
                self._redirect(location)
                return
            if request_path == "/method/update":
                try:
                    message = app.handle_method_update(form)
                except (ValueError, FileExistsError) as exc:
                    location = "/configure?" + urlencode({"error": str(exc)})
                else:
                    location = "/configure?" + urlencode({"message": message})
                self._redirect(location)
                return
            if request_path == "/study/create":
                try:
                    created = app.create_study(form)
                except (ValueError, FileExistsError) as exc:
                    location = "/setup?" + urlencode({"error": str(exc)})
                else:
                    location = "/?" + urlencode(
                        {"message": f"Created {created.title}. Next, add your transcripts and codebook."}
                    )
                self._redirect(location)
                return
            try:
                run_id, message = app.handle_action(request_path, form)
            except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
                run_id = form.get("run_id", [""])[0]
                message = f"Action failed: {exc}"
            if request_path.startswith('/repeats/'):
                self._redirect('/repeats?' + urlencode({'experiment':form.get('experiment',[''])[0], 'message':message}))
                return
            if request_path == '/benchmark/save':
                self._redirect('/benchmark?' + urlencode({'left':run_id, 'right':form.get('right_id', [''])[0], 'message':message}))
                return
            if request_path == '/stability/save':
                self._redirect('/stability?' + urlencode({'run':form.get('run', []), 'experiment':form.get('experiment', [''])[0], 'message':message}, doseq=True))
                return
            if request_path == '/empty-output/review':
                self._redirect('/empty-output?' + urlencode({'run_id':run_id, 'source':form.get('source',[''])[0], 'message':message}))
                return
            if request_path.startswith('/synthesis/'):
                self._redirect('/synthesis?' + urlencode({'run_id':run_id,'job':form.get('job',[''])[0],'item':form.get('item',[''])[0],'message':message}))
                return
            if request_path == '/comparison/save':
                self._redirect('/compare?' + urlencode({'left':run_id, 'right':form.get('right_id',[''])[0], 'message':message}))
                return
            if request_path in {'/analysis/freeze', '/analysis/prepare-synthesis'}:
                self._redirect('/analysis?' + urlencode({'run_id':run_id, 'snapshot':form.get('snapshot',[''])[0], 'message':message}))
                return
            if request_path == "/export-evidence" and form.get("return_to", [""])[0] == "analysis":
                self._redirect("/analysis?" + urlencode({"run_id": run_id, "message": message}))
                return
            if request_path in {"/prepare-evidence", "/evidence-action", "/evidence-add", "/export-evidence"}:
                params = {
                    "run_id": run_id,
                    "item": form.get("item", [""])[0],
                    "message": message,
                }
                location = "/evidence?" + urlencode(params)
            else:
                location = "/?" + urlencode({"run_id": run_id, "message": message})
            self._redirect(location)

        def _send_static(self, name: str) -> None:
            static_root = (Path(__file__).parent / "static").resolve()
            target = (static_root / name).resolve()
            if not target.is_file() or not target.is_relative_to(static_root):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            types = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2"}
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", types.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600" if target.suffix == ".woff2" else "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, text: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, content: bytes) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return DashboardHandler


def _qualframe_already_running(port: int) -> bool:
    from urllib.request import urlopen
    try:
        with urlopen(f"http://127.0.0.1:{port}/static/workspace.css", timeout=2) as response:
            return b"QualFrame workspace" in response.read(300)
    except OSError:
        return False


def serve_dashboard(project_yaml: Path | None = None, port: int = 8765, *, workspace: Path | None = None,
                    open_browser: bool = False) -> None:
    runner = ProjectRunner(project_yaml.resolve()) if project_yaml else None
    app = DashboardApp(runner, workspace_root=workspace)
    server = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(app))
            port = candidate
            break
        except OSError:
            if open_browser and _qualframe_already_running(candidate):
                url = f"http://127.0.0.1:{candidate}/"
                print(f"QualFrame is already running at {url}; opening it.")
                import webbrowser
                webbrowser.open(url)
                return
    if server is None:
        raise SystemExit(f"Ports {port} to {port + 9} are busy. Start with --port to choose another.")
    url = f"http://127.0.0.1:{port}/"
    print(f"QualFrame is running at {url}")
    print("Keep this window open while you work. Press Ctrl+C to stop.")
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
