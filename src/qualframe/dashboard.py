from __future__ import annotations

import html
import json
import mimetypes
import threading
from dataclasses import dataclass, field
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
    append_evidence_review_action,
    export_evidence_review_package,
    latest_evidence_action_by_record,
    load_evidence_review_records,
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
from qualframe.study_setup import StudyWorkspace
from qualframe.web_forms import UploadedFile, parse_multipart_form
from qualframe.workspace_ui import render_workspace


_MAX_HTTP_BODY = 26 * 1024 * 1024
_LOCAL_EXECUTION_PROVIDERS = {"mock", "cached_demo"}


@dataclass
class ExecutionJob:
    run_id: str
    status: str = "running"
    progress: list[str] = field(default_factory=list)
    error: str | None = None


class DashboardApp:
    """Loopback-only controller for run inspection and human review actions."""

    def __init__(self, runner: ProjectRunner) -> None:
        self.repo_root = runner.repo_root
        self.study_workspace = StudyWorkspace(self.repo_root)
        self._jobs: dict[str, ExecutionJob] = {}
        self._job_lock = threading.Lock()
        self._activate_runner(runner)

    def _activate_runner(self, runner: ProjectRunner) -> None:
        if runner.repo_root != self.repo_root:
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
        runs = self.list_runs()
        selected = run_id if run_id in runs else (runs[0] if runs else None)
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
        presentation = (
            '<p class="muted"><a href="/presentation">Open the cached CFIR evidence report</a></p>'
            if (self.repo_root / "demo/presentation/index.html").exists() else ""
        )
        return self._render_workspace_page(
            title="Study workspace",
            intro="A reproducible path from source material to reviewed evidence. Your study, methods, and decisions in one place.",
            body=selector + message_html + detail + presentation,
            head=refresh,
        )

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
        message_html = f"<div class='message'>{html.escape(message)}</div>" if message else ""
        error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
        body = f"""<div class="banner"><strong>No model request is made during setup.</strong> Source files are copied and hashed; originals are never modified.</div>
{message_html}{error_html}
<section><form method="post" action="/study/create">
<div class="grid">
<label>Study title<input name="title" maxlength="120" required placeholder="Example: Community service experience study"></label>
<label>Study ID <span class="muted">(optional)</span><input name="study_id" pattern="[a-z0-9][a-z0-9-]{{1,62}}[a-z0-9]" placeholder="created-from-title"></label>
<label>Analysis method<select name="template"><option value="generic_directed">Directed content analysis</option><option value="cfir">CFIR reference workflow</option></select></label>
<label>Data classification<select name="data_classification"><option value="synthetic">Synthetic</option><option value="deidentified">Deidentified research data</option><option value="sensitive">Sensitive research data</option></select></label>
</div>
<p><label class="check"><input type="checkbox" name="include_synthetic_fixtures" value="yes" checked><span>Include the two checked-in synthetic transcripts and starter codebook. Available only when classification is Synthetic.</span></label></p>
<p class="muted">Directed content analysis uses a configurable example codebook and mock provider. CFIR preserves the six domain-by-domain coding passes and uses cached synthetic responses by default. Both choices can be revised through versioned configuration later.</p>
<button type="submit">Create local study</button></form></section>
"""
        return self._render_workspace_page(
            title="Create a study",
            intro="Start with a question, a codebook, and your sources. Create a local workspace with a reproducible analysis method.",
            body=body,
        )

    def render_imports(self, message: str = "", error: str = "") -> str:
        message_html = f"<div class='message'>{html.escape(message)}</div>" if message else ""
        error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
        try:
            project_path = self._managed_project_path()
            records = self.study_workspace.source_records(project_path)
        except ValueError as exc:
            forms = (
                f"<section><h2>Managed study required</h2><p>{html.escape(str(exc))}</p>"
                "<p><a href='/setup'>Create a local study first</a>.</p></section>"
            )
        else:
            counts = {
                kind: sum(record.source_kind == kind for record in records)
                for kind in ("transcript", "codebook", "metadata")
            }
            forms = f"""
<div class="cards"><div class="card"><span>Transcripts</span><strong>{counts['transcript']}</strong></div><div class="card"><span>Codebooks</span><strong>{counts['codebook']}</strong></div><div class="card"><span>Metadata files</span><strong>{counts['metadata']}</strong></div></div>
<section><h2>Import transcript</h2><p>Accepted formats: UTF-8 text and Word DOCX, up to 25 MB. Filenames must be unique across the study.</p>
<form method="post" action="/import/transcript" enctype="multipart/form-data" class="grid">
<label>Transcript file<input type="file" name="upload" accept=".txt,.docx" required></label>
<label>Study group or site<input name="group_label" maxlength="80" value="Ungrouped" required></label>
<label>Researcher name<input name="actor" required></label><label>Reason for import<input name="rationale" required></label>
<button type="submit">Import transcript</button></form></section>
<section><h2>Import codebook version</h2><p>Accepted format: QualFrame YAML. IDs, hierarchy, definitions, and version are validated before the project reference changes. The previous codebook remains on disk.</p>
<form method="post" action="/import/codebook" enctype="multipart/form-data" class="grid">
<label>Codebook YAML<input type="file" name="upload" accept=".yaml,.yml" required></label>
<label>Researcher name<input name="actor" required></label><label>Reason for change<input name="rationale" required></label>
<button type="submit">Import codebook version</button></form></section>
<section><h2>Import metadata</h2><p>Accepted format: UTF-8 CSV with a unique <code>source_filename</code> column. Every filename must already be registered as a transcript.</p>
<form method="post" action="/import/metadata" enctype="multipart/form-data" class="grid">
<label>Metadata CSV<input type="file" name="upload" accept=".csv" required></label>
<label>Researcher name<input name="actor" required></label><label>Reason for import<input name="rationale" required></label>
<button type="submit">Import metadata version</button></form></section>"""
        return self._render_workspace_page(
            title="Import study files",
            intro=(
                "Files are copied into the managed study, validated, hashed, and recorded. "
                "Existing study files are never overwritten."
            ),
            body=message_html + error_html + forms,
        )

    def render_configure(self, message: str = "", error: str = "") -> str:
        message_html = f"<div class='message'>{html.escape(message)}</div>" if message else ""
        error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
        try:
            self._managed_project_path()
        except ValueError as exc:
            body = (
                error_html
                + f"<section><h2>Managed study required</h2><p>{html.escape(str(exc))}</p>"
                "<p><a href='/setup'>Create a local study first</a>.</p></section>"
            )
        else:
            method = self.runner.method
            if method is None:
                body = error_html + "<section><p>No method is configured.</p></section>"
            else:
                def selected(value: str, current: str) -> str:
                    return " selected" if value == current else ""

                cfir_partition = self.runner.pipeline.id.startswith("transcript_cfir")
                if cfir_partition:
                    partition_control = (
                        "<input type='hidden' name='partition_strategy' value='per_top_level_category'>"
                        "<p><strong>Codebook partitioning:</strong> one call per CFIR domain. "
                        "This reference-workflow setting is shown read-only because the active CFIR pipeline enforces domain iterations.</p>"
                    )
                else:
                    partition_control = f"""<label>Codebook partitioning<select name="partition_strategy">
<option value="full_codebook"{selected('full_codebook', method.partitioning.strategy)}>One call with the full codebook</option>
<option value="per_top_level_category"{selected('per_top_level_category', method.partitioning.strategy)}>One call per top-level category</option>
</select></label>"""
                overlap_checked = " checked" if method.coding.allow_overlapping_spans else ""
                body = message_html + error_html + f"""
<section><h2>Method version {html.escape(method.version)}</h2>
<form method="post" action="/method/update">
<div class="grid">
<label>Meaning-unit segmentation<select name="segmentation_strategy">
<option value="model_proposed"{selected('model_proposed', method.segmentation.strategy)}>Model proposes meaning units</option>
<option value="researcher_presegmented"{selected('researcher_presegmented', method.segmentation.strategy)}>Researcher-presegmented input</option>
<option value="sentence"{selected('sentence', method.segmentation.strategy)}>Sentence units</option>
<option value="paragraph"{selected('paragraph', method.segmentation.strategy)}>Paragraph units</option></select></label>
<label>Context before (sentences)<input type="number" min="0" max="10" name="context_before" value="{method.context.before}" required></label>
<label>Context after (sentences)<input type="number" min="0" max="10" name="context_after" value="{method.context.after}" required></label>
<label>Coding cardinality<select name="coding_cardinality"><option value="single_label"{selected('single_label', method.coding.cardinality)}>One code per meaning unit</option><option value="multi_label"{selected('multi_label', method.coding.cardinality)}>Multiple codes permitted</option></select></label>
{partition_control}
</div>
<p><label class="check"><input type="checkbox" name="allow_overlapping_spans" value="yes"{overlap_checked}><span>Allow overlapping evidence spans</span></label></p>
<div class="grid"><label>Researcher name<input name="actor" required></label><label>Reason for new method version<input name="rationale" required></label></div>
<button type="submit">Create new method version</button></form></section>
<section><h2>What is enforced now</h2><ul><li>The selected policy is versioned and included in the configuration fingerprint.</li><li>Generic coding requests receive the segmentation, context, cardinality, overlap, and partition instructions.</li><li>Generic top-level partitioning changes the actual request plan and execution fan-out.</li><li>Returned code IDs and single/multi-label limits are checked and routed to review.</li></ul><p class="muted">Provider-native schema constraints and complete evidence-offset enforcement remain experimental and are not implied by this editor.</p></section>"""
        return self._render_workspace_page(
            title="Configure analysis method",
            intro="Revisions create a new method file and append-only change record; prior run configurations remain intact.",
            body=body,
        )

    def _render_workspace_page(
        self, *, title: str, intro: str, body: str, head: str = "",
    ) -> str:
        active = {"Create a study": "setup", "Import study files": "imports",
                  "Configure analysis method": "configure",
                  "Review exact evidence": "evidence"}.get(title, "overview")
        evidence_run = next(
            (run for run in self.list_runs()
             if (self.artifacts_dir / run / "evidence_review/index.json").exists()), None
        )
        return render_workspace(
            title=title, intro=intro, body=body, head=head, active=active,
            study=self.runner.project.title or self.runner.project.project_id,
            classification=self.runner.project.data_classification or "not declared",
            provider=self.runner.project.provider.name,
            evidence_url=f"/evidence?{urlencode({'run_id': evidence_run})}" if evidence_run else None,
        )

    def handle_upload(
        self,
        path: str,
        fields: dict[str, list[str]],
        files: dict[str, UploadedFile],
    ) -> str:
        project_path = self._managed_project_path()
        upload = files.get("upload")
        if upload is None:
            raise ValueError("Choose a file to import.")

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
                group_label=field("group_label", "Ungrouped"),
            )
        elif path == "/import/codebook":
            record = self.study_workspace.import_codebook(**common)
        elif path == "/import/metadata":
            record = self.study_workspace.import_metadata(**common)
        else:
            raise ValueError("Unknown import action.")
        self._refresh_runner()
        return f"Imported {record.original_filename}; SHA-256 {record.sha256}."

    def handle_method_update(self, form: dict[str, list[str]]) -> str:
        def required(name: str) -> str:
            value = form.get(name, [""])[0].strip()
            if not value:
                raise ValueError(f"Missing required field: {name}")
            return value

        partition_strategy = required("partition_strategy")
        if self.runner.pipeline.id.startswith("transcript_cfir"):
            partition_strategy = "per_top_level_category"
        update = MethodPolicyUpdate(
            segmentation_strategy=required("segmentation_strategy"),
            context_before=int(required("context_before")),
            context_after=int(required("context_after")),
            coding_cardinality=required("coding_cardinality"),
            allow_overlapping_spans=(
                form.get("allow_overlapping_spans", [""])[0] == "yes"
            ),
            partition_strategy=partition_strategy,
        )
        path = self.study_workspace.update_method_policy(
            project_manifest_path=self._managed_project_path(),
            update=update,
            actor=required("actor"),
            rationale=required("rationale"),
        )
        self._refresh_runner()
        return f"Created method version {path.stem.replace('_', ' ')}."

    def render_evidence(
        self,
        *,
        run_id: str,
        item_id: str = "",
        message: str = "",
        error: str = "",
    ) -> str:
        self._managed_project_path()
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        index_path = artifact_root / "evidence_review" / "index.json"
        if not index_path.exists():
            raise FileNotFoundError("Prepare the evidence review index first.")
        records = load_evidence_review_records(index_path)
        if not records:
            body = "<section><p>No offset-bearing directed-coding rows were found.</p></section>"
            return self._render_workspace_page(
                title="Review exact evidence",
                intro="No reviewable evidence records are available for this run.",
                body=body,
            )
        selected = next((record for record in records if record.record_id == item_id), records[0])
        selected_index = records.index(selected)
        review_dir = self.review_dir / run_id
        actions = latest_evidence_action_by_record(review_dir)
        action = actions.get(selected.record_id)
        resolved = sum(
            1
            for record in records
            if record.record_id in actions and actions[record.record_id].decision != "defer"
        )
        previous_link = (
            f"<a href='/evidence?{urlencode({'run_id': run_id, 'item': records[selected_index - 1].record_id})}'>Previous</a>"
            if selected_index > 0
            else "Previous"
        )
        next_link = (
            f"<a href='/evidence?{urlencode({'run_id': run_id, 'item': records[selected_index + 1].record_id})}'>Next</a>"
            if selected_index + 1 < len(records)
            else "Next"
        )
        span = selected.evidence_span
        exact_text = span.exact_text if span else selected.proposed_exact_text
        context = selected.context_text or exact_text
        position = context.find(exact_text)
        if position >= 0:
            evidence_html = (
                html.escape(context[:position])
                + f"<mark>{html.escape(exact_text)}</mark>"
                + html.escape(context[position + len(exact_text) :])
            )
        else:
            evidence_html = f"<mark>{html.escape(exact_text)}</mark>"
        issue_html = (
            "<div class='error'><strong>Validation issues</strong><ul>"
            + "".join(f"<li>{html.escape(issue)}</li>" for issue in selected.validation_issues)
            + "</ul></div>"
            if selected.validation_issues
            else "<div class='message'>Exact text, offsets, source hash, and code ID validated.</div>"
        )
        status = action.decision if action else "unreviewed"
        code_options = ""
        if self.runner.codebook:
            for code in self.runner.codebook.codes:
                chosen = selected.assignment and code.id == selected.assignment.code_id
                code_options += (
                    f"<option value='{html.escape(code.id)}'{' selected' if chosen else ''}>"
                    f"{html.escape(code.label)} ({html.escape(code.id)})</option>"
                )
        start = span.start_offset if span else selected.proposed_start_offset
        end = span.end_offset if span else selected.proposed_end_offset
        message_html = f"<div class='message'>{html.escape(message)}</div>" if message else ""
        error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
        export_paths = [
            path
            for path in (self.exports_dir / run_id).glob("reviewed_evidence_package.*")
        ] if (self.exports_dir / run_id).exists() else []
        export_links = "".join(
            f"<li>{self._file_link(path, path.name)}</li>" for path in sorted(export_paths)
        )
        export_control = (
            f"<form method='post' action='/export-evidence'><input type='hidden' name='run_id' value='{html.escape(run_id)}'><input type='hidden' name='item' value='{html.escape(selected.record_id)}'><button type='submit'>Export reviewed evidence package</button></form>"
            if resolved == len(records)
            else f"<p>Resolve all items before export. {len(records) - resolved} remain unreviewed or deferred.</p>"
        )
        queue_links = ""
        for index, record in enumerate(records):
            latest = actions.get(record.record_id)
            decision = latest.decision if latest else "unreviewed"
            target = "/evidence?" + urlencode({"run_id": run_id, "item": record.record_id})
            queue_links += (
                f'<li><a href="{html.escape(target)}" aria-current="{str(record == selected).lower()}">'
                f'<span>{index + 1:02d} &nbsp; {html.escape(Path(record.source_path).name)}'
                f' · {html.escape(record.code_label or "Unresolved")}</span>'
                f'<span class="queue-status">{html.escape(decision)}</span></a></li>'
            )
        assignment_heading = "Mock assignment" if self.runner.project.provider.name == "mock" else "AI-assisted assignment"
        body = message_html + error_html + f"""
<div class="review-summary"><div><span class="kicker">HUMAN REVIEW</span><br><strong>{resolved} / {len(records)} resolved</strong><div class="progress-track"><div class="progress-fill" style="width:{100 * resolved / len(records):.1f}%"></div></div></div><div><span class="kicker">CURRENT DECISION</span><br><strong>{html.escape(status.title())}</strong></div><div class="record-navigation">{previous_link}<span class="muted">Item {selected_index + 1} of {len(records)}</span>{next_link}</div></div>
<div class="review-layout"><div><section><div class="section-top"><h2>Exact evidence</h2><span class="mini-tag">SOURCE-LINKED</span></div><div class="source-meta"><strong>{html.escape(Path(selected.source_path).name)}</strong> &nbsp; / &nbsp; Source context with coded span highlighted</div><p class="evidence">{evidence_html}</p>{issue_html}<p><strong>Code:</strong> {html.escape(selected.code_label or (selected.assignment.code_id if selected.assignment else 'Unresolved'))}</p><p>{html.escape(selected.code_definition or 'No code definition is available.')}</p></section>
<section><h2>{assignment_heading}</h2><p>{html.escape(selected.assignment.rationale if selected.assignment and selected.assignment.rationale else 'No model rationale was supplied.')}</p><p class="muted">This is an AI-assisted coding proposal, not a research finding or human interpretation.</p></section>

<section><div class="section-top"><h2>Evidence queue</h2><span class="muted">{len(records)} items</span></div><ul class="queue-list">{queue_links}</ul></section>
<section><h2>Provenance</h2><details><summary>Show technical record</summary><dl><dt>Source</dt><dd>{html.escape(selected.source_path)}</dd><dt>Source SHA-256</dt><dd><code>{selected.source_sha256}</code></dd><dt>Offsets</dt><dd>{selected.proposed_start_offset}–{selected.proposed_end_offset}</dd><dt>Run / stage</dt><dd>{html.escape(run_id)} / {html.escape(selected.stage_id)}</dd><dt>Artifact SHA-256</dt><dd><code>{selected.artifact_sha256}</code></dd><dt>Prompt SHA-256</dt><dd><code>{selected.prompt_sha256}</code></dd><dt>Configuration</dt><dd><code>{html.escape(selected.configuration_fingerprint or 'Unavailable')}</code></dd><dt>Provider / model</dt><dd>{html.escape(selected.provider or 'Unavailable')} / {html.escape(selected.model or 'Unavailable')}</dd></dl></details></section>
</div><div><section class="review-form"><div class="kicker">YOUR INTERPRETATION</div><h2>Record review decision</h2><form method="post" action="/evidence-action"><input type="hidden" name="run_id" value="{html.escape(run_id)}"><input type="hidden" name="item" value="{html.escape(selected.record_id)}"><div class="grid"><label>Decision<select name="decision"><option value="accept">Accept</option><option value="edit">Edit</option><option value="reject">Reject</option><option value="defer">Defer</option></select></label><label>Researcher name<input name="reviewer" required></label></div><details><summary>Edit span or code</summary><div class="grid"><label>Evidence start offset<input type="number" min="0" name="edited_start" value="{start}"></label><label>Evidence end offset<input type="number" min="1" name="edited_end" value="{end}"></label><label>Code for an edit<select name="edited_code_id">{code_options}</select></label></div></details><label>Rationale<textarea name="rationale" required></textarea></label><button type="submit">Append review action</button></form><p class="muted">Offset and code fields are used only for Edit. Original model output and prior actions remain unchanged.</p></section>
<section><h2>Traceable export</h2>{export_control}<ul>{export_links}</ul><p class="muted">The package contains reviewed evidence and methods provenance. It is not an automatic findings report.</p></section></div></div>"""
        return self._render_workspace_page(
            title="Review exact evidence",
            intro="Read the source. Weigh the code. Keep the interpretation yours.",
            body=body,
        )

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
<section><h2>Execution progress</h2><p>This page refreshes every two seconds. Closing it does not stop the local background job.</p><ul>{progress}</ul><p class="muted">Only mock or checked-in cached execution can be started from this interface.</p></section>"""
        if job is not None and job.status == "failed" and not manifest_path.exists():
            return f"""<section><h2>Execution failed</h2><p>{html.escape(job.error or 'Unknown local execution error.')}</p><form method="post" action="/execute"><input type="hidden" name="run_id" value="{html.escape(run_id)}"><button type="submit">Resume this local run</button></form></section>"""
        if not manifest_path.exists() and pause_path.exists():
            pause = CostPauseRecord.model_validate_json(
                pause_path.read_text(encoding="utf-8")
            )
            return self._render_cost_pause(run_id, pause, pause_path)
        if not manifest_path.exists() and (artifact_root / "run_plan.json").exists():
            plan = RunPlan.model_validate_json(
                (artifact_root / "run_plan.json").read_text(encoding="utf-8")
            )
            return self._render_planned_run(run_id, plan, artifact_root / "run_plan.json")
        manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        review_root = self.review_dir / run_id
        export_root = self.exports_dir / run_id
        review_items = sorted(review_root.glob("*.json")) if review_root.exists() else []
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
            action = adjudications.get(item_rel)
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
            review_rows = "<tr><td colspan='4'>No queued review items.</td></tr>"

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
            export_links = "<li>No exports created yet.</li>"
        export_form = f"""<form method="post" action="/export" class="inline">
<input type="hidden" name="run_id" value="{html.escape(run_id)}"><button type="submit">Create or refresh exports</button></form>"""

        return f"""
<div class="cards">
<div class="card"><div class="label">Project</div><div class="value">{html.escape(self.runner.project.project_id.replace('_', ' ').title())}</div></div>
<div class="card"><div class="label">Run</div><div class="value">{html.escape(run_id.replace('_', ' '))}</div></div>
<div class="card"><div class="label">Status</div><div class="value">{html.escape(manifest.status)}</div></div>
<div class="card"><div class="label">QA / structured failures</div><div class="value">{manifest.qa_failure_count} / {manifest.structured_output_failure_count}</div></div>
<div class="card"><div class="label">Release</div><div class="value">{html.escape(manifest.release_status)}</div></div>
<div class="card"><div class="label">This run cost</div><div class="value">{f'USD {manifest.run_cost_usd:.4f}' if manifest.run_cost_usd is not None else 'Not tracked'}</div></div>
<div class="card"><div class="label">Project cost</div><div class="value">{f'USD {manifest.project_cost_usd:.4f}' if manifest.project_cost_usd is not None else 'Not tracked'}</div></div>
</div>
{gate_form}{release_form}{evidence_section}
<section><h2>Pipeline artifacts</h2><table><thead><tr><th>Stage</th><th>Artifacts</th></tr></thead><tbody>{stage_rows}</tbody></table>
<p>{self._file_link(manifest_path, "Run manifest")}</p><details><summary>Artifact files</summary><ul>{''.join(artifact_links)}</ul></details></section>
<section><h2>Review queue and adjudication</h2><table><thead><tr><th>Item</th><th>Issue</th><th>Reason</th><th>Latest action</th></tr></thead><tbody>{review_rows}</tbody></table></section>
<section><h2>Exports</h2>{export_form}<ul>{export_links}</ul></section>"""

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
{execution_control}<p class="muted">External-provider execution and advanced filters remain command-line operations in the current increment.</p></section>"""

    def _local_execution_control(self, run_id: str, label: str) -> str:
        if self.runner.project.provider.name not in _LOCAL_EXECUTION_PROVIDERS:
            return ""
        try:
            self._managed_project_path()
        except ValueError:
            return ""
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

    def start_local_execution(self, run_id: str) -> None:
        project_path = self._managed_project_path()
        provider_name = self.runner.project.provider.name
        if provider_name not in _LOCAL_EXECUTION_PROVIDERS:
            raise PermissionError(
                "Browser execution is limited to mock and checked-in cached providers."
            )
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        plan_path = artifact_root / "run_plan.json"
        if not plan_path.exists():
            raise ValueError("Create a dry-run plan before starting local execution.")
        plan = RunPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if plan.project_id != self.runner.project.project_id:
            raise ValueError("Run plan belongs to a different study.")
        with self._job_lock:
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

        run_id = required("run_id")
        artifact_root = self._run_root(self.artifacts_dir, run_id)
        review_root = self.review_dir / run_id

        if path == "/execute":
            self.start_local_execution(run_id)
            return run_id, "Started local background execution."

        if path == "/prepare-evidence":
            index_path = write_evidence_review_index(
                project_manifest_path=self._managed_project_path(),
                run_id=run_id,
            )
            count = len(load_evidence_review_records(index_path))
            return run_id, f"Prepared {count} exact-evidence review item(s)."

        if path == "/evidence-action":
            item_id = required("item")
            index_path = artifact_root / "evidence_review" / "index.json"
            records = load_evidence_review_records(index_path)
            record = next((item for item in records if item.record_id == item_id), None)
            if record is None:
                raise ValueError("Evidence review item was not found in this run.")
            decision = required("decision")
            edited_start = int(required("edited_start")) if decision == "edit" else None
            edited_end = int(required("edited_end")) if decision == "edit" else None
            edited_code_id = required("edited_code_id") if decision == "edit" else None
            action = append_evidence_review_action(
                record=record,
                source_path=resolve_repo_path(self.repo_root, record.source_path),
                review_dir=review_root,
                artifact_root=artifact_root,
                decision=decision,
                reviewer=required("reviewer"),
                rationale=required("rationale"),
                edited_start=edited_start,
                edited_end=edited_end,
                edited_code_id=edited_code_id,
            )
            return run_id, f"Recorded evidence decision {action.decision}."

        if path == "/export-evidence":
            written = export_evidence_review_package(
                project_manifest_path=self._managed_project_path(),
                run_id=run_id,
                require_released=(
                    self.runner.project.governance.enforce_review_gates
                    and self.runner.project.governance.require_release_for_export
                ),
            )
            return run_id, f"Exported {len(written)} reviewed evidence file(s)."

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
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
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
            length = int(self.headers.get("Content-Length", "0"))
            if length > _MAX_HTTP_BODY:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            body = self.rfile.read(length)
            request_path = urlparse(self.path).path
            if request_path.startswith("/import/"):
                try:
                    fields, files = parse_multipart_form(
                        self.headers.get("Content-Type", ""), body
                    )
                    message = app.handle_upload(request_path, fields, files)
                except (ValueError, FileExistsError) as exc:
                    location = "/imports?" + urlencode({"error": str(exc)})
                else:
                    location = "/imports?" + urlencode({"message": message})
                self._redirect(location)
                return

            try:
                form = parse_qs(body.decode("utf-8"))
            except UnicodeDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid form encoding")
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
                        {
                            "message": (
                                f"Created {created.title} with "
                                f"{created.imported_source_count} imported source file(s)."
                            )
                        }
                    )
                self._redirect(location)
                return
            try:
                run_id, message = app.handle_action(request_path, form)
            except (ValueError, PermissionError, json.JSONDecodeError) as exc:
                run_id = form.get("run_id", [""])[0]
                message = f"Action failed: {exc}"
            if request_path in {"/prepare-evidence", "/evidence-action", "/export-evidence"}:
                params = {
                    "run_id": run_id,
                    "item": form.get("item", [""])[0],
                    "message": message,
                }
                location = "/evidence?" + urlencode(params)
            else:
                location = "/?" + urlencode({"run_id": run_id, "message": message})
            self._redirect(location)

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


def serve_dashboard(project_yaml: Path, port: int = 8765) -> None:
    runner = ProjectRunner(project_yaml.resolve())
    app = DashboardApp(runner)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"QualFrame local study workspace: http://127.0.0.1:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
