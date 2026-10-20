"""Rebuild the fictional 2 x 2 QualBench example from saved responses, without a network.

Run from a source checkout: python scripts/run_qualbench_example.py --output PATH
The output must not already exist. All intermediate studies are temporary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qualframe.app_workspace import ensure_workspace  # noqa: E402
from qualframe.config import load_codebook_spec, load_method_spec  # noqa: E402
from qualframe.demo_study import run_recording  # noqa: E402
from qualframe.directed_analysis import partition_codebook  # noqa: E402
from qualframe.io.transcript_io import transcript_to_text  # noqa: E402
from qualframe.models import CodebookPartitionPolicy, MethodPolicyUpdate  # noqa: E402
from qualframe.pipeline.project_runner import ProjectRunner  # noqa: E402
from qualframe.providers.recorded_provider import recording_key  # noqa: E402
from qualframe.qualbench import build_qualbench, reference_coding_set, run_coding_set, write_qualbench  # noqa: E402
from qualframe.study_setup import StudyWorkspace  # noqa: E402

DATASET = REPO_ROOT / "demo/datasets/ai-scribe"
RECORDINGS = REPO_ROOT / "demo/recordings"
TABLES_START = "<!-- QUALBENCH_EXAMPLE_TABLES_START -->"
TABLES_END = "<!-- QUALBENCH_EXAMPLE_TABLES_END -->"
REFERENCE_STATEMENT = (
    "Illustrative coder A is a hand-written coding of the fictional demo, not an independent "
    "human annotation or a gold standard. It records positives only. All document-code units "
    "are assessed; a unit with no recorded application is treated as an implicit negative, not an explicit absence decision."
)


class Cell(NamedTuple):
    recording: str
    model: str
    style: str
    division: str
    legacy: bool = False

    @property
    def label(self) -> str:
        style = "find" if self.style == "find_passages" else "decide"
        division = "whole" if self.division == "full_codebook" else "by group"
        return f"{self.model}: {style} / {division}"


CELLS = tuple(
    Cell(recording, model, style, division, legacy)
    for model, prefix, original in (
        ("Sonnet", "sonnet-5-5", "claude-sonnet-5-5-2026-10"),
        ("Sol", "gpt-6-1-sol", "gpt-6-1-sol-2026-10"),
    )
    for recording, style, division, legacy in (
        (original, "find_passages", "full_codebook", True),
        (f"{prefix}-find-by-group-2026-10", "find_passages", "per_top_level_category", False),
        (f"{prefix}-decide-whole-2026-10", "decide_each_code", "full_codebook", False),
        (f"{prefix}-decide-by-group-2026-10", "decide_each_code", "per_top_level_category", False),
    )
)
REFERENCE_CELL = Cell("demo-illustrative-a", "Illustrative coder A", "find_passages", "full_codebook", True)


def _text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def expected_keys(cell: Cell) -> set[str]:
    codebook = load_codebook_spec(DATASET / "codebook.yaml")
    transcripts = sorted((DATASET / "transcripts").rglob("*.txt"))
    if len(transcripts) != 6 or sum(code.active for code in codebook.codes) != 15:
        raise ValueError("The example requires the unchanged six-document, 15-active-code demo.")
    groups = partition_codebook(codebook, CodebookPartitionPolicy(strategy=cell.division))
    return {
        recording_key(f"Codebook partition for this request: {group}.\n\n"
                      f"Transcript:\n\n{transcript_to_text(path)}\n\n---\n\n")
        for path in transcripts for group in groups
    }


def validate_recording(cell: Cell, recordings: Path = RECORDINGS) -> dict:
    """Fail before replay when a required cell is absent, partial or configured differently."""
    folder = recordings / cell.recording
    path = folder / "recording.json"
    if not path.is_file():
        raise ValueError(f"Required recording is missing: {cell.recording}. No example was generated.")
    info = json.loads(path.read_text(encoding="utf-8"))
    prompt = ("prompts/directed/v3/directed_coding.md" if cell.style == "find_passages"
              else "prompts/directed/v4/decide_each_code.md")
    keys = expected_keys(cell)
    actual = {p.stem for p in (folder / "responses").glob("*.txt")}
    expected = {"id": cell.recording, "dataset": "ai-scribe", "requests": len(keys),
                "prompt_sha256": _text_sha256(REPO_ROOT / prompt)}
    if not cell.legacy:
        expected.update(complete=True, status="completed", expected_requests=len(keys),
                        completed_requests=len(keys), coding_style=cell.style,
                        partition_strategy=cell.division,
                        codebook_division="full_codebook" if cell.division == "full_codebook" else "top_level_categories")
    if not cell.legacy:
        codebook = load_codebook_spec(DATASET / "codebook.yaml")
        expected["codebook_sha256"] = hashlib.sha256(codebook.model_dump_json(indent=2).encode("utf-8")).hexdigest()
        expected["prompt_file"] = prompt
        method = load_method_spec(REPO_ROOT / "config/methods/directed_content_analysis_v3.yaml")
        policy = method.model_dump(mode="json", exclude={"id", "version", "name"})
        policy["coding"]["decision_style"] = cell.style
        policy["partitioning"]["strategy"] = cell.division
        if cell.style == "decide_each_code":
            policy["evidence_location"] = "unique_exact_quote"
        expected["method_policy"] = policy
        expected["transcripts"] = sorted([
            {"file": path.name, "sha256": hashlib.sha256(transcript_to_text(path).encode("utf-8")).hexdigest()}
            for path in (DATASET / "transcripts").rglob("*.txt")
        ], key=lambda row: row["file"])
        expected["response_sha256"] = {key: _text_sha256(folder / "responses" / f"{key}.txt")
                                        for key in sorted(actual)}
    for field, value in expected.items():
        observed = info.get(field)
        if field == "method_policy" and isinstance(observed, dict):
            observed = {key: item for key, item in observed.items() if key != "name"}
        if observed != value:
            raise ValueError(f"{cell.recording}: incomplete or mismatched {field}; expected {value!r}.")
    if actual != keys:
        raise ValueError(f"{cell.recording}: response keys differ (missing {len(keys - actual)}, extra {len(actual - keys)}).")
    for key in sorted(keys):
        if not (folder / "responses" / f"{key}.txt").read_text(encoding="utf-8").strip():
            raise ValueError(f"{cell.recording}: empty saved response {key}.")
    if cell == REFERENCE_CELL:
        if info.get("kind") != "illustrative":
            raise ValueError("Coder A must remain explicitly illustrative.")
    else:
        if info.get("kind") != "model" or info.get("response_status") != ["completed"]:
            raise ValueError(f"{cell.recording}: recording does not contain completed model responses.")
        provider = info.get("provider_settings", {})
        configured = dict(name="anthropic", model="claude-sonnet-5-5", api_mode="chat_completions",
                          max_tokens=16000, temperature=None) if cell.model == "Sonnet" else dict(
                              name="openai", model="gpt-6.1-sol", api_mode="responses",
                              max_tokens=16000, temperature=None, reasoning_effort="low")
        for field, value in configured.items():
            if provider.get(field) != value:
                raise ValueError(f"{cell.recording}: mismatched provider setting {field}; expected {value!r}.")
        field = "estimated_cost_usd" if cell.legacy else "actual_cost_usd"
        cost = info.get(field)
        if isinstance(cost, bool) or not isinstance(cost, (float, int)) or not math.isfinite(cost) or cost < 0:
            raise ValueError(f"{cell.recording}: original recording cost is unavailable.")
        if not cell.legacy and (info.get("cost_is_estimated") is not False
                                or info.get("cost_source") != "provider_usage_ledger"):
            raise ValueError(f"{cell.recording}: original usage is not settled.")
    return info


def _replay_cell(workspace: Path, cell: Cell) -> dict:
    manager = StudyWorkspace(workspace)
    created = manager.create_from_dataset(dataset_root=DATASET, title=cell.label, study_id=cell.recording)
    project = workspace / created.project_manifest_path
    method = ProjectRunner(project).method
    assert method is not None
    manager.update_method_policy(
        project_manifest_path=project,
        update=MethodPolicyUpdate(segmentation_strategy=method.segmentation.strategy,
                                  context_unit=method.context.unit, context_before=method.context.before,
                                  context_after=method.context.after, coding_cardinality=method.coding.cardinality,
                                  allow_overlapping_spans=method.coding.allow_overlapping_spans,
                                  coding_decision_style=cell.style, partition_strategy=cell.division),
        actor="Fictional example replay", rationale="Replay this cell's recorded instruction style and division.",
    )
    run_recording(project, cell.recording, cell.recording)
    coding = run_coding_set(workspace, project.parent / "artifacts" / cell.recording)
    # RecordedProvider's estimates and replay timing are not original hosted usage.
    coding.update(usage=None, usage_records=[], usage_ledger_available=False, usage_ledger_path=None)
    coding["label"] = cell.label
    return coding


def _original_usage(profile: dict, cell: Cell, info: dict) -> None:
    """Attach aggregate original usage only for the complete six-document cohort.

    Old recordings have aggregate token counts and a rounded estimated cost, with no
    request ledger. Do not invent per-document/request allocations or elapsed time.
    """
    if profile["transcripts"] != 6:
        raise ValueError("Original aggregate usage can only describe the complete six-document cohort.")
    cost = info["estimated_cost_usd"] if cell.legacy else info["actual_cost_usd"]
    tokens = info.get("usage_breakdown", info.get("reported_usage", {}))
    source = f"demo/recordings/{cell.recording}/recording.json"
    note = ("Original recording metadata; legacy estimated cost and aggregate tokens. "
            "No historical request-level or elapsed-time data are available." if cell.legacy else
            "Original completed recording usage ledger total, preserved in recording metadata; not an invoice.")
    totals = dict(requests=info["requests"], cost_usd=cost, cost_is_estimated=cell.legacy,
                  elapsed_seconds=None, usage_note=note,
                  **{field: tokens.get(field) for field in ("input_tokens", "output_tokens",
                     "cached_input_tokens", "cache_write_tokens", "reasoning_tokens")})
    profile.update(model=info["provider_settings"]["model"], provider=info["provider_settings"]["name"],
                   original_recording=cell.recording, original_usage_source=source,
                   original_cost_source="legacy_recording_estimate" if cell.legacy else info["cost_source"],
                   usage_ledger_path=None)
    for prefix in ("", "cohort_", "whole_run_"):
        profile.update({prefix + field: value for field, value in totals.items()})
    for field, value in totals.items():
        if field not in {"cost_is_estimated", "usage_note"}:
            profile[f"cohort_{field}_per_transcript"] = value / 6 if value is not None else None


def example_numbers(report: dict) -> dict:
    """Stable numeric data underlying the documentation; omit timestamps and temporary paths."""
    reference = report["reference"]["set_id"]
    overall = [row for row in report["presence"] if row["comparison"] == "versus reference"
               and row["scope_kind"] == "all"]
    prevalence = []
    for level in ("code", "parent code"):
        row = next(row for row in overall if row["level"] == level)
        positives = row["both"] + row["right_only"]
        prevalence.append(dict(level=level, units=row["n_units"], positive=positives,
                               negative=row["n_units"] - positives, prevalence=positives / row["n_units"]))
    return dict(
        bootstrap_settings=report["bootstrap_settings"], reference=report["reference"],
        reference_records_explicit_absences=report["reference_records_explicit_absences"],
        prevalence=prevalence,
        presence=[row for row in overall if row["level"] == "code"],
        intervals=[row for row in report["bootstrap"] if row["level"] == "code" and row["scope_kind"] == "all"],
        passages=[row for row in report["passages"] if row["right"] == reference and row["scope_kind"] == "all"],
        profiles=[{key: row.get(key) for key in (
            "set_id", "label", "model", "provider", "coded_passages", "passages_located", "located_exactly",
            "quotations_not_found", "no_decision_count", "share_located", "requests", "cost_usd",
            "cost_is_estimated", "original_cost_source", "original_usage_source")}
            for row in report["coding_sets"] if row["kind"] != "reference"],
    )


def _number(value: float | None, places: int = 3) -> str:
    return "undefined" if value is None else f"{value:.{places}f}"


def _table(headers: list[str], rows: list[list]) -> str:
    return "\n".join("| " + " | ".join(map(str, row)) + " |" for row in
                     [headers, ["---"] * len(headers), *rows])


def render_key_tables(report: dict) -> str:
    """Return the exact deterministic block maintained in docs/examples/qualbench-2x2.md."""
    numbers = example_numbers(report)
    labels = {cell.recording: cell.label for cell in CELLS}
    labels.update({"baseline:always-present": "Every code present", "baseline:always-absent": "Every code absent"})
    intervals = {(row["kind"], row["left"], row["right"], row["metric"]): row for row in numbers["intervals"]}
    reference = report["reference"]["set_id"]

    def interval(kind, left, right, metric):
        row = intervals[(kind, left, right, metric)]
        return f"{_number(row['estimate'])} [{_number(row['lower_95'])}, {_number(row['upper_95'])}]"

    sections = [
        "All rates below are fractions. Intervals are 95% document-bootstrap percentile intervals. "
        "Sonnet means Claude Sonnet 5.5; Sol means GPT-6.1 Sol.",
        "### Reference prevalence",
        _table(["Level", "Assessed units", "Positive", "Implicit negative", "Prevalence"],
               [[r["level"], r["units"], r["positive"], r["negative"], _number(r["prevalence"])]
                for r in numbers["prevalence"]]),
        "### Code presence versus illustrative coder A",
        _table(["Coding set", "Sensitivity", "Specificity", "Balanced accuracy [95% CI]", "MCC [95% CI]"],
               [[labels[r["left"]], _number(r["sensitivity"]), _number(r["specificity"]),
                 interval("estimate", r["left"], reference, "balanced_accuracy"),
                 interval("estimate", r["left"], reference, "mcc")] for r in numbers["presence"]]),
    ]
    paired = []
    for model in ("Sonnet", "Sol"):
        for left, right in combinations([c for c in CELLS if c.model == model], 2):
            paired.append([f"{left.label} minus {right.label}",
                           interval("paired_difference", left.recording, right.recording, "balanced_accuracy"),
                           interval("paired_difference", left.recording, right.recording, "mcc")])
    sections += ["### Paired differences between the saved cells",
                 _table(["Left minus right", "Balanced accuracy difference [95% CI]", "MCC difference [95% CI]"], paired),
                 "All six within-model cell contrasts are shown. These contrasts describe individual saved runs, "
                 "not replicated model or configuration effects. Valid and undefined draw counts are retained in `bootstrap.csv`.",
                 "### Located passage agreement versus illustrative coder A",
                 _table(["Coding set", "Scope", "Model passages", "Reference passages", "Exact F1", "IoU >= 0.5 F1", "Coded-text Jaccard"],
                        [[labels[r["left"]], r["scope"], r["left_passages"], r["right_passages"],
                          _number(r["f1_exact"]), _number(r["f1_iou_half"]), _number(r["coded_text_jaccard"])]
                         for r in numbers["passages"]]),
                 "### Quotation location and original recording cost",
                 _table(["Coding set", "Proposed passages", "Located", "Exact", "Unlocated", "Omitted decisions", "Requests", "Original USD", "Cost source"],
                        [[r["label"], r["coded_passages"], r["passages_located"], r["located_exactly"],
                          r["quotations_not_found"], r["no_decision_count"], r["requests"], _number(r["cost_usd"], 6),
                          "Legacy estimate" if r["cost_is_estimated"] else "Usage ledger"] for r in numbers["profiles"]]),
                 "A presence value of zero means no observed positive application, including when a decide-every-code "
                 "response omitted a requested decision. An omitted decision is not an explicit absence. "
                 "Find-passages requests do not require a decision for every code; zero omissions in those cells "
                 "does not mean explicit decisions were requested.",
                 "Offline replay costs USD 0. The costs above describe the original hosted recordings. "
                 "No elapsed-time measurements from replay are used. Undefined statistics remain undefined."]
    return "\n\n".join(sections)


def build_example(output_dir: Path, *, bootstrap: int = 2000, seed: int = 1) -> dict:
    """Replay all eight cells and illustrative A, write a report, and return that report."""
    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}. Choose a new folder.")
    metadata = {cell.recording: validate_recording(cell) for cell in (*CELLS, REFERENCE_CELL)}
    with tempfile.TemporaryDirectory(prefix="qualframe-fictional-example-") as temporary:
        workspace = ensure_workspace(Path(temporary), app_root=REPO_ROOT).root
        sets = [_replay_cell(workspace, cell) for cell in CELLS]
        illustrative = _replay_cell(workspace, REFERENCE_CELL)
        illustrative.update(run_id="reference:illustrative-a", label="Illustrative coder A",
                            statement=REFERENCE_STATEMENT, independent_human_coding=False)
        reference = reference_coding_set(illustrative)
        report = build_qualbench(sets, reference=reference, bootstrap=bootstrap, seed=seed,
                                cluster_by_folder=False)
        if len(report["transcripts"]) != 6 or report["codes"] != 15 or report["exclusions"]:
            raise ValueError("The example did not retain its complete six-document, 15-code cohort.")
        by_id = {row["set_id"]: row for row in report["coding_sets"]}
        for cell in CELLS:
            _original_usage(by_id[cell.recording], cell, metadata[cell.recording])
        report["example_recordings"] = metadata
        report["example_provenance"] = {
            "dataset": "demo/datasets/ai-scribe", "reference": REFERENCE_CELL.recording,
            "replay_cost_usd": 0, "temporary_studies_removed": True,
            "legacy_identity_limit": "The two original model recordings and illustrative A predate dataset/codebook hashes; "
                                     "their saved instruction hashes and exact response keys are checked against the bundled demo.",
            "usage_scope": "Original aggregate recording totals describe all six compared documents. "
                           "No original per-document allocations or elapsed times are inferred from replay.",
        }
    write_qualbench(report, output_dir)
    (output_dir / "example_numbers.json").write_text(json.dumps(example_numbers(report), indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "example_tables.md").write_text(render_key_tables(report) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output folder (existing folders are refused).")
    args = parser.parse_args()
    report = build_example(args.output)
    print(f"Rebuilt eight fictional coding sets against Illustrative coder A: {args.output}")
    print(f"Bootstrap: {report['bootstrap_settings']['replicates']} draws, seed 1, documents. Replay API cost: USD 0.")


if __name__ == "__main__":
    main()
