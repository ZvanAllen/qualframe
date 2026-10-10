"""Bounded, descriptive comparisons of multiple frozen raw coding runs."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from statistics import mean

from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import compare_raw_payloads, raw_coding_payload

METRICS = ("code_jaccard", "exact_span_jaccard", "coverage_jaccard")
GROUPS = ("same_configuration", "different_configuration", "unknown_configuration")


def _configuration_pair(left: dict, right: dict) -> str:
    a, b = left.get("configuration_fingerprint"), right.get("configuration_fingerprint")
    if not a or not b:
        return "unknown_configuration"
    return "same_configuration" if a == b else "different_configuration"


def compare_collection(payloads: list[dict], unavailable: list[dict] | None = None) -> dict:
    """Retain failures and undefined scores; never infer independent observations."""
    unavailable = unavailable or []
    ids = [p["run_id"] for p in payloads] + [p["run_id"] for p in unavailable]
    if not 2 <= len(ids) <= 10 or len(ids) != len(set(ids)):
        raise ValueError("Choose 2 to 10 distinct coding runs.")
    payloads = sorted(payloads, key=lambda p: p["run_id"])
    pairs, blocked = [], []
    for left, right in itertools.combinations(payloads, 2):
        try:
            pair = compare_raw_payloads(left, right)
        except ValueError as exc:
            blocked.append(dict(left=left["run_id"], right=right["run_id"], reason=str(exc)))
            continue
        pair["configuration_relation"] = _configuration_pair(left, right)
        pairs.append(pair)
    summaries = {}
    for group in GROUPS:
        observations = [p for p in pairs if p["configuration_relation"] == group]
        summary = {"eligible_pairs": len(observations), "metrics": {}}
        for metric in METRICS:
            values = [
                p["summary"][metric] for p in observations if p["summary"][metric] is not None
            ]
            summary["metrics"][metric] = dict(
                defined_pairs=len(values),
                undefined_pairs=len(observations) - len(values),
                mean=mean(values) if values else None,
                minimum=min(values) if values else None,
                maximum=max(values) if values else None,
            )
        summaries[group] = summary
    total_pairs = len(ids) * (len(ids) - 1) // 2
    return dict(
        kind="qualframe_repeat_comparison_v1",
        metric_version="raw_overlap_v1",
        selected_run_ids=sorted(ids),
        runs=payloads,
        unavailable_runs=sorted(unavailable, key=lambda p: p["run_id"]),
        selected_run_count=len(ids),
        usable_run_count=len(payloads),
        possible_pairs=total_pairs,
        eligible_pairs=len(pairs),
        unavailable_pairs=total_pairs - len(pairs) - len(blocked),
        incompatible_pairs=blocked,
        summaries=summaries,
        pairs=pairs,
        interpretation="Descriptive raw-output overlap; no human reference or accuracy estimate. Pairwise observations share runs and are not independent. Means weight defined pairs equally; they are not pooled corpus estimates.",
        configuration_policy="Same configuration requires identical nonempty full frozen configuration fingerprints, including provider, prompts, framework and administrative settings. Different fingerprints do not establish a model-only effect. Missing fingerprints remain unknown.",
        empty_policy="An empty union is undefined, never perfect agreement. Undefined and unavailable pairs remain in the report.",
    )


def build_repeat_report(
    repo_root: Path, run_roots: list[Path], *, experiment_context: dict | None = None
) -> dict:
    ids = [p.name for p in run_roots]
    if not 2 <= len(ids) <= 10 or len(ids) != len(set(ids)):
        raise ValueError("Choose 2 to 10 distinct coding runs.")
    payloads, unavailable = [], []
    for root in run_roots:
        try:
            payload = raw_coding_payload(repo_root, root)
            if payload["run_id"] != root.name:
                raise ValueError("Run folder and manifest identities differ.")
            payloads.append(payload)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            unavailable.append(dict(run_id=root.name, reason=str(exc)))
    report = compare_collection(payloads, unavailable)
    if experiment_context:
        report["experiment"] = experiment_context
    return report


def write_repeat_report(
    repo_root: Path,
    artifacts_root: Path,
    run_roots: list[Path],
    *,
    dry_run: bool = False,
    expected_report_id: str | None = None,
    experiment_context: dict | None = None,
) -> Path:
    if any(p.resolve().parent != artifacts_root.resolve() for p in run_roots):
        raise ValueError("Choose coding runs directly within the study artifacts folder.")
    report = build_repeat_report(repo_root, run_roots, experiment_context=experiment_context)
    if expected_report_id is not None and snapshot_identity(report) != expected_report_id:
        raise ValueError(
            "Coding outputs changed since this report was displayed; rebuild the evaluation before saving."
        )
    path = artifacts_root / "comparison_reports" / f"stability-{snapshot_identity(report)}.json"
    if not dry_run:
        if path.exists():
            if snapshot_identity(json.loads(path.read_text(encoding="utf-8"))) != snapshot_identity(
                report
            ):
                raise ValueError("Saved report content does not match its identity.")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, indent=2, ensure_ascii=False))
    return path


def experiment_report_scope(project_path: Path, experiment_id: str) -> tuple[list[str], dict]:
    from qualframe.repeat_execution import read_repeat_plan

    envelope = read_repeat_plan(project_path, experiment_id)
    plan = envelope["plan"]
    ids = plan["run_ids"]
    if not 2 <= len(ids) <= 10 or any(
        not r or Path(r).name != r or r in {".", ".."} or "/" in r or chr(92) in r for r in ids
    ):
        raise ValueError("The experiment contains invalid run identities.")
    return ids, dict(
        experiment_id=experiment_id,
        plan_id=envelope["plan_id"],
        configuration_fingerprint=plan["configuration_fingerprint"],
        scope="All planned repeats, including failed and not-started runs.",
    )
