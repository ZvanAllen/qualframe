"""A methods record for one coding run: what was sent, to which model, and what the reviewers decided.

Everything is read from files the run already wrote. Nothing here calls a model.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from qualframe.config import resolve_repo_path
from qualframe.evidence_review import is_researcher_addition, load_evidence_review_actions, latest_evidence_action_by_record, load_review_timing, load_run_records
from qualframe.ui_kit import provider_display, run_model

_DECISIONS = {"accept": "accepted", "edit": "changed", "reject": "rejected", "defer": "left for later"}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _instructions_label(app, sha256: str | None) -> str:
    try:
        from qualframe.coding_instructions import instruction_versions

        labels = {v.sha256: v.label for v in instruction_versions(app.repo_root, app._managed_project_path())}
    except (OSError, ValueError):
        labels = {}
    return labels.get(sha256 or "", "")


def build_methods_record(app, run_id: str) -> dict:
    root = app._run_root(app.artifacts_dir, run_id)
    review_root = app.review_dir / run_id
    plan = _read(root / "run_plan.json")
    manifest = _read(root / "run_manifest.json")
    settings = _read(root / "run_settings.json")
    lock = _read(root / "analysis_configuration_lock.json")
    assets = {a.get("kind"): a for a in lock.get("assets", [])}
    provider, model = run_model(root)
    provider_settings = settings.get("provider") or {"name": provider, "model": model}
    method_settings = {}
    method_asset = assets.get("method", {})
    if method_asset.get("path"):
        try:
            method = yaml.safe_load(resolve_repo_path(app.repo_root, method_asset["path"]).read_text(encoding="utf-8"))
            method_settings = {
                "codes_per_passage": method.get("coding", {}).get("cardinality"),
                "codebook_per_request": method.get("partitioning", {}).get("strategy"),
                "passage_segmentation": method.get("segmentation", {}).get("strategy"),
                "context_saved": method.get("context"),
                "quotation_location": method.get("evidence_location"),
            }
        except (OSError, ValueError, AttributeError):
            pass
    transcripts = [
        {"file": Path(item["path"]).name, "group": Path(item["path"]).parent.name, "sha256": item.get("sha256")}
        for item in plan.get("discovered_inputs", []) if item.get("kind") == "transcript"
    ]
    index = root / "evidence_review/index.json"
    everything = load_run_records(index, review_root) if index.exists() else []
    records = [r for r in everything if not is_researcher_addition(r)]
    latest = latest_evidence_action_by_record(review_root) if review_root.exists() else {}
    all_actions = load_evidence_review_actions(review_root) if review_root.exists() else []
    additions = [r for r in everything if is_researcher_addition(r)
                 and not (r.record_id in latest and latest[r.record_id].decision == "reject")]
    timing = load_review_timing(review_root) if review_root.exists() else {}
    proposal_ids = {r.record_id for r in records}
    seconds = sorted(timing[a.action_id] for a in all_actions if a.action_id in timing and a.record_id in proposal_ids)
    decisions = Counter(latest[r.record_id].decision if r.record_id in latest else "undecided" for r in records)
    needs_location = [r for r in records if r.anchoring_method in {"unresolved_exact_quote", "normalized_quote_candidate"}]
    resolved_location = Counter(latest[r.record_id].decision if r.record_id in latest else "undecided" for r in needs_location)
    times = sorted(a.timestamp_utc for a in all_actions)
    comparisons = sorted(p.name for p in (root / "comparisons").glob("comparison-*.json")) if (root / "comparisons").exists() else []
    project = app.runner.project
    codebook_asset = assets.get("codebook", {})
    prompt_asset = assets.get("prompt", {})
    return {
        "study": project.title or project.project_id,
        "data_classification": project.data_classification,
        "run_id": run_id,
        "qualframe_version": settings.get("qualframe_version"),
        "started_at_utc": settings.get("started_at_utc"),
        "completed_at_utc": manifest.get("completed_at_utc"),
        "model": {"label": provider_display(provider, model), **{k: v for k, v in provider_settings.items() if v is not None}},
        "prompt": {"path": prompt_asset.get("path"), "sha256": prompt_asset.get("sha256"),
                   "label": _instructions_label(app, prompt_asset.get("sha256"))},
        "codebook": {"id": settings.get("codebook_id") or plan.get("codebook_id"), "version": settings.get("codebook_version"),
                     "path": codebook_asset.get("path"), "sha256": codebook_asset.get("sha256"),
                     "codes": len(app.runner.codebook.codes) if app.runner.codebook else None},
        "method": method_settings,
        "configuration_fingerprint": manifest.get("configuration_fingerprint") or plan.get("configuration_fingerprint"),
        "transcripts": transcripts,
        "requests_planned": len(plan.get("planned_stage_runs", [])),
        "recorded_cost_usd": manifest.get("run_cost_usd"),
        "review": {
            "proposals": len(records),
            "decisions": dict(decisions),
            "reviewers": sorted({a.reviewer for a in all_actions}),
            "first_decision_utc": times[0] if times else None,
            "last_decision_utc": times[-1] if times else None,
            "decision_events": len(all_actions),
            "needed_manual_location": len(needs_location),
            "needed_manual_location_outcomes": dict(resolved_location),
            "added_by_researchers": len(additions),
            "added_by_code": dict(Counter(r.code_label or r.proposed_code_id for r in additions)),
            "timed_decisions": len(seconds),
            "median_seconds_per_decision": seconds[len(seconds) // 2] if seconds else None,
        },
        "saved_comparisons": comparisons,
    }


def methods_paragraph(record: dict) -> str:
    model = record["model"]
    review = record["review"]
    decisions = review["decisions"]
    per_request = {"full_codebook": "the whole codebook in each request",
                   "per_top_level_category": "one top-level codebook category per request"}.get(
        record["method"].get("codebook_per_request"), "the codebook")
    reviewers = ", ".join(review["reviewers"]) or "[reviewer]"
    codes = record["codebook"].get("codes") or "[N]"
    version = record.get("qualframe_version") or "[version]"
    located = review["needed_manual_location"]
    location_sentence = (
        f" Each proposed quotation was located in the transcript automatically; {located} "
        f"whose quotation could not be located exactly were resolved by the reviewer."
        if located else " Each proposed quotation was located in the transcript automatically."
    )
    return (
        f"Directed content analysis was supported by QualFrame {version} (van Allen, 2026), open-source software that "
        f"applies a predefined codebook to interview transcripts using a large language model and presents each proposed "
        f"code with its source passage for human review. {model['label']} coded {len(record['transcripts'])} transcripts "
        f"against a {codes}-code codebook using "
        + ("QualFrame's directed-coding instructions" if record["prompt"].get("label") in ("", "QualFrame standard instructions")
           else f"edited coding instructions (\"{record['prompt']['label']}\", provided as supplementary material)")
        + f", with {per_request}."
        f"{location_sentence} {reviewers} reviewed all {review['proposals']} proposals, accepting "
        f"{decisions.get('accept', 0)}, changing the code or passage of {decisions.get('edit', 0)}, and rejecting "
        f"{decisions.get('reject', 0)}"
        + (f"; {decisions.get('defer', 0) + decisions.get('undecided', 0)} were not yet decided" if decisions.get('defer', 0) + decisions.get('undecided', 0) else "")
        + "."
        + (f" The reviewer{'s' if len(review['reviewers']) > 1 else ''} also coded {review['added_by_researchers']} "
           f"passage{'s' if review['added_by_researchers'] != 1 else ''} that the model had not proposed."
           if review.get("added_by_researchers") else "")
    )


def methods_markdown(record: dict) -> str:
    model = record["model"]
    lines = [
        f"# Methods record: {record['study']}",
        "",
        "## Suggested methods paragraph",
        "",
        methods_paragraph(record),
        "",
        "## Run",
        "",
        f"- Run ID: {record['run_id']}",
        f"- QualFrame version: {record['qualframe_version']}",
        f"- Started: {record['started_at_utc']}; completed: {record['completed_at_utc']}",
        f"- Configuration fingerprint (SHA-256): {record['configuration_fingerprint']}",
        f"- Requests planned: {record['requests_planned']}; recorded cost (USD): {record['recorded_cost_usd']}",
        "",
        "## Model",
        "",
        *[f"- {key}: {value}" for key, value in model.items()],
        "",
        "## Instructions and codebook",
        "",
        f"- Prompt: {record['prompt']['path']} (SHA-256 {record['prompt']['sha256']})",
        f"- Codebook: {record['codebook']['id']} version {record['codebook']['version']}, {record['codebook']['codes']} codes "
        f"({record['codebook']['path']}, SHA-256 {record['codebook']['sha256']})",
        *[f"- {key.replace('_', ' ')}: {value}" for key, value in record["method"].items()],
        "",
        "## Transcripts",
        "",
        *[f"- {t['group']}/{t['file']} (SHA-256 {t['sha256']})" for t in record["transcripts"]],
        "",
        "## Human review",
        "",
        f"- Proposals: {record['review']['proposals']}",
        *[f"- {_DECISIONS.get(k, k)}: {v}" for k, v in record["review"]["decisions"].items()],
        f"- Reviewers: {', '.join(record['review']['reviewers'])}",
        f"- Decisions recorded between {record['review']['first_decision_utc']} and {record['review']['last_decision_utc']} "
        f"({record['review']['decision_events']} decision events, including revisions)",
        f"- Proposals whose quotation needed manual location: {record['review']['needed_manual_location']} "
        f"(outcomes: {record['review']['needed_manual_location_outcomes']})",
        f"- Passages coded by reviewers that the model had not proposed: {record['review']['added_by_researchers']}"
        + (f" ({', '.join(f'{k}: {v}' for k, v in record['review']['added_by_code'].items())})" if record['review']['added_by_code'] else ""),
        f"- Median time per decision: {record['review']['median_seconds_per_decision']} seconds "
        f"({record['review']['timed_decisions']} timed decisions)" if record['review']['timed_decisions'] else "- Decision times: not recorded",
        "",
    ]
    if record["saved_comparisons"]:
        lines += ["## Saved comparisons", "", *[f"- {name}" for name in record["saved_comparisons"]], ""]
    return "\n".join(lines)


def render_methods_page(app, run_id: str) -> str:
    import html
    from urllib.parse import urlencode

    e = html.escape
    record = build_methods_record(app, run_id)
    paragraph = methods_paragraph(record)
    query = lambda fmt: "/methods?" + urlencode({"run_id": run_id, "format": fmt})
    review = record["review"]
    rows = "".join(
        f"<tr><th>{e(label)}</th><td>{e(str(value))}</td></tr>" for label, value in [
            ("Model", record["model"]["label"]),
            ("Model settings", ", ".join(f"{k}: {v}" for k, v in record["model"].items() if k not in {"label"})),
            ("Instructions", f"{record['prompt']['path']} (SHA-256 {str(record['prompt']['sha256'])[:12]}…)"),
            ("Codebook", f"{record['codebook']['id']} version {record['codebook']['version']}, {record['codebook']['codes']} codes"),
            ("Transcripts", len(record["transcripts"])),
            ("Requests", record["requests_planned"]),
            ("Reviewers", ", ".join(review["reviewers"]) or "None yet"),
            ("Decisions", ", ".join(f"{v} {_DECISIONS.get(k, k)}" for k, v in review["decisions"].items())),
            ("Quotations located by hand", review["needed_manual_location"]),
            ("Codes added by reviewers", review["added_by_researchers"]),
            ("Median time per decision", f'{review["median_seconds_per_decision"]} seconds' if review["median_seconds_per_decision"] is not None else "Not recorded"),
            ("QualFrame version", record["qualframe_version"] or "not recorded (run started before version 0.9)"),
        ])
    body = f'''<section><h2>Suggested methods paragraph</h2><p class="muted">Generated from this run's records. Edit it to fit your study and journal.</p>
<textarea class="methods-text" rows="9" readonly>{e(paragraph)}</textarea>
<div class="actions"><a class="button" href="{e(query("md"))}">Download methods record (Markdown)</a><a href="{e(query("json"))}">Download as JSON</a></div></section>
<section><h2>Details</h2><table><tbody>{rows}</tbody></table>
<p class="muted">See <a href="https://github.com/ZvanAllen/qualframe/blob/main/docs/reporting.md">Reporting QualFrame in your methods</a> for what reviewers usually ask.</p></section>'''
    return app._render_workspace_page(title="Methods record", intro="What this run sent, to which model, and what was decided in review.", body=body, active="analysis")
