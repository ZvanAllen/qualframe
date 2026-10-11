"""Confirm whether a failed paid request was charged, so coding can resume.

When a request to a hosted model fails (the account ran out of credit, the connection dropped),
QualFrame can't know whether the provider charged for it. It sends nothing more until the
researcher says. "Not charged" records zero usage; "charged" records the tokens from the
provider's usage page. Both are recorded with the researcher's name and the request's error.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

e = html.escape


def _request_record(app, row: dict) -> dict:
    path = app.artifacts_dir / str(row.get("run_id", "")) / "requests" / f"{row['request_id']}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _what(row: dict) -> str:
    label = str(row.get("input_label", "")).replace("\\", "/")
    source, _, part = label.partition("::")
    name = Path(source).stem if source else "a transcript"
    return f"{name} ({part})" if part else name


def _when(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %B, %H:%M")
    except (TypeError, ValueError):
        return ""


def _error(record: dict) -> str:
    message = str(record.get("error_message") or "").strip()
    kind = str(record.get("error_type") or "").strip()
    if message:
        return message
    return f"{kind} (no message was saved)" if kind else "Not recorded"


def render_unresolved_usage(app, cost) -> str:
    """A form for each request whose charge is unknown."""
    rows = cost.unresolved_requests()
    if not rows:
        return ""
    forms = ""
    for row in rows:
        record = _request_record(app, row)
        elapsed = record.get("elapsed_seconds")
        seconds = f"{float(elapsed):.1f} seconds" if isinstance(elapsed, (int, float)) else "Not recorded"
        forms += f'''<form method="post" action="/usage/resolve" class="usage-resolve">
<input type="hidden" name="request_id" value="{e(row['request_id'])}"><input type="hidden" name="run_id" value="{e(str(row.get('run_id', '')))}">
<p>A request to {e(str(row.get('model', 'the model')))} failed{' on ' + e(_when(row.get('timestamp_utc', ''))) if _when(row.get('timestamp_utc', '')) else ''}
while coding {e(_what(row))}.</p>
<dl><dt>Error</dt><dd>{e(_error(record))}</dd><dt>Failed after</dt><dd>{e(seconds)}</dd>
<dt>Most it could have cost</dt><dd>${float(row.get('estimated_cost_usd', 0)):.2f}</dd></dl>
<fieldset><legend>Was it charged?</legend>
<label class="check"><input type="radio" name="charged" value="no" checked><span><strong>No.</strong> It failed before the model wrote anything, for example because the account had run out of credit. A failure within a few seconds almost always means this; if you're unsure, check the provider's usage page.</span></label>
<label class="check"><input type="radio" name="charged" value="yes"><span><strong>Yes.</strong> Enter the tokens the provider's usage page shows for it.</span></label>
<div class="token-fields"><label>Input tokens<input type="number" name="input_tokens" min="0" step="1" inputmode="numeric"></label>
<label>Output tokens<input type="number" name="output_tokens" min="0" step="1" inputmode="numeric"></label></div>
</fieldset>
<label>Note (optional)<input name="note" maxlength="300"></label>
<button>Save and continue</button></form>'''
    count = len(rows)
    return (f'<section class="usage-panel"><h2>Was the failed request charged?</h2>'
            f'<p>QualFrame can\'t tell whether the provider charged for {"this request" if count == 1 else f"these {count} requests"}, '
            f'so it won\'t send any more until you say. Nothing was retried, and the coding already saved is kept.</p>'
            f'{forms}</section>')


def resolve_usage(app, form: dict[str, list[str]]) -> tuple[str, str]:
    """Record the researcher's answer for one failed request. Returns (run id, message)."""
    from qualframe.providers.base import LLMUsage

    def field(name: str) -> str:
        return form.get(name, [""])[0].strip()

    app.fill_identity(form, "Confirmed whether a failed request was charged")
    reviewer = form["reviewer"][0]
    request_id, run_id = field("request_id"), field("run_id")
    cost = app.runner._build_cost_controller(run_id=run_id or "reconciliation", artifact_root=app.artifacts_dir / (run_id or "."))
    if cost is None:
        raise ValueError("This study has no model and spending limit set.")
    row = next((r for r in cost.unresolved_requests() if r["request_id"] == request_id), None)
    if row is None:
        raise ValueError("That request has already been resolved, or isn't part of this study.")
    record = _request_record(app, row)
    note = field("note")
    if field("charged") == "yes":
        try:
            input_tokens, output_tokens = int(field("input_tokens") or 0), int(field("output_tokens") or 0)
        except ValueError as exc:
            raise ValueError("Enter the token counts as whole numbers.") from exc
        if input_tokens < 0 or output_tokens < 0 or input_tokens + output_tokens == 0:
            raise ValueError("Enter the input and output tokens shown on the provider's usage page.")
        usage = LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        rationale = "Researcher reported the provider charged for this failed request."
        evidence = "Token counts entered from the provider's usage page by the researcher."
    else:
        usage = LLMUsage(input_tokens=0, output_tokens=0)
        rationale = "Researcher confirmed the provider did not charge: the request failed before any output."
        evidence = (f"Researcher confirmation. Request record requests/{request_id}.json: "
                    f"{_error(record)[:300]}; failed after {record.get('elapsed_seconds', 'unknown')} s.")
    if note:
        rationale += " Note: " + note
    saved = cost.reconcile_request(request_id=request_id, usage=usage, reviewer=reviewer,
                                   rationale=rationale, evidence_reference=evidence)
    left = len(cost.unresolved_requests())
    outcome = f"Recorded ${saved.calculated_cost_usd:.2f} for the failed request." if saved.calculated_cost_usd else \
        "Recorded that the failed request was not charged."
    return str(row.get("run_id", run_id)), outcome + (" You can resume the run." if not left else
                                                       f" {left} more failed request{'s' if left > 1 else ''} to confirm.")
