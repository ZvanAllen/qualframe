"""Descriptive pairwise comparisons of immutable raw coding, never adjudicated labels."""

from __future__ import annotations

import json
from pathlib import Path
from qualframe.directed_analysis import validate_evidence_span_against_source
from qualframe.evidence_review import load_evidence_review_records, blocking_review_issues
from qualframe.io.files import sha256_for_file
from qualframe.io.transcript_io import transcript_to_text
from qualframe.reviewed_analysis import snapshot_identity, _within
from qualframe.study_progress import transcript_progress


def raw_coding_payload(repo_root: Path, run_root: Path) -> dict:
    index = run_root / "evidence_review/index.json"
    if not index.exists():
        raise ValueError("Prepare evidence review for both runs before comparing raw outputs.")
    data = json.loads(index.read_text(encoding="utf-8"))
    plan = json.loads((run_root / "run_plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    progress = transcript_progress(run_root, run_root / "__unused_review__", [], repo_root)
    if not progress or not all(row["completed"] for row in progress):
        raise ValueError("Both runs need completed coding for the full frozen transcript cohort.")
    sources = {
        i["path"].replace("\\", "/"): i["sha256"]
        for i in plan["discovered_inputs"]
        if i["kind"] == "transcript"
    }
    stage_by_source = {}
    for call in plan["planned_stage_runs"]:
        key = call.get("input_path", "").replace("\\", "/")
        if key in sources:
            stage_by_source.setdefault(key, call["stage_id"])
    texts = {}
    for path, digest in sources.items():
        source = _within(repo_root, path)
        if sha256_for_file(source) != digest:
            raise ValueError("Source content changed since the selected run.")
        texts[path] = transcript_to_text(source)
    codebook = data.get("codebook", {})
    known = {c["id"] for c in codebook.get("codes", [])}
    if not known:
        raise ValueError("A frozen codebook is required for comparison.")
    records, excluded, absences = [], [], []
    artifact_hashes = {}
    for record in load_evidence_review_records(index):
        source = record.source_path.replace("\\", "/")
        if source not in sources or record.stage_id != stage_by_source[source]:
            continue
        if record.source_sha256 != sources[source]:
            raise ValueError("Evidence index source identity differs from the run plan.")
        if record.artifact_path not in artifact_hashes:
            artifact_hashes[record.artifact_path] = sha256_for_file(
                _within(run_root, record.artifact_path)
            )
        if artifact_hashes[record.artifact_path] != record.artifact_sha256:
            raise ValueError("Model artifact changed after evidence indexing.")
        code = record.assignment.code_id if record.assignment else record.proposed_code_id
        item = dict(
            record_id=record.record_id,
            source=source,
            code_id=code,
            model=record.model,
            provider=record.provider,
            prompt_sha256=record.prompt_sha256,
            artifact_sha256=record.artifact_sha256,
            anchoring_method=record.anchoring_method,
        )
        if record.record_kind == "absence":
            if code in known:
                absences.append(item)
            else:
                excluded.append(dict(item, issues=["Unknown code in absence proposal"]))
            continue
        issues = blocking_review_issues(record, texts[source])
        span = record.evidence_span
        if code not in known:
            issues.append("Unknown code")
        if span is None:
            issues.append("Missing source span")
        else:
            try:
                validate_evidence_span_against_source(span, texts[source])
            except ValueError as exc:
                issues.append(str(exc))
        if issues:
            excluded.append(dict(item, issues=sorted(set(issues))))
            continue
        records.append(
            dict(item, start=span.start_offset, end=span.end_offset, exact_text=span.exact_text)
        )
    return dict(
        kind="qualframe_raw_comparison_input_v1",
        run_id=manifest["run_id"],
        project_id=manifest["project_id"],
        configuration_fingerprint=manifest.get("configuration_fingerprint"),
        configuration_assets=manifest.get("configuration_assets", []),
        codebook=codebook,
        sources=sources,
        run_cost_usd=manifest.get("run_cost_usd"),
        index_sha256=sha256_for_file(index),
        artifact_hashes=artifact_hashes,
        included=records,
        excluded=excluded,
        absences=absences,
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _intervals(items: list[dict]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((i["start"], i["end"]) for i in items):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def interval_overlap(left: list[dict], right: list[dict]) -> tuple[int, int]:
    a, b = _intervals(left), _intervals(right)
    i = j = intersection = 0
    while i < len(a) and j < len(b):
        intersection += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    union = sum(e - s for s, e in a) + sum(e - s for s, e in b) - intersection
    return intersection, union


def restrict_to_common_sources(left: dict, right: dict) -> tuple[dict, dict, list[str]]:
    """Limit two payloads to the transcripts both runs coded (same path and hash).

    Used when one run coded a sample of the study. Returns the restricted payloads and the
    transcripts left out of the comparison.
    """
    common = {path for path, digest in left["sources"].items() if right["sources"].get(path) == digest}
    if not common:
        raise ValueError("These runs have no transcripts in common, so they can't be compared.")
    omitted = sorted((set(left["sources"]) | set(right["sources"])) - common)

    def keep(payload: dict) -> dict:
        trimmed = dict(payload)
        trimmed["sources"] = {path: digest for path, digest in payload["sources"].items() if path in common}
        for key in ("included", "excluded", "absences"):
            if key in payload:
                trimmed[key] = [item for item in payload[key] if item.get("source") in common]
        return trimmed

    return keep(left), keep(right), omitted


def _codebook_identity(codebook: dict) -> str:
    """Codebook identity for comparison. CFIR catalogues gained an Outcomes Addendum "section"
    field in October 2026; it does not change any code, so it is left out here."""
    codes = [{k: v for k, v in code.items() if k != "section"} for code in codebook.get("codes", [])]
    return snapshot_identity(dict(codebook, codes=codes))


def compare_raw_payloads(left: dict, right: dict) -> dict:
    if left["run_id"] == right["run_id"]:
        raise ValueError("Choose two distinct runs.")
    if left["project_id"] != right["project_id"] or left["sources"] != right["sources"]:
        raise ValueError(
            "Runs must belong to the same study and use the same transcript paths and hashes."
        )
    if _codebook_identity(left["codebook"]) != _codebook_identity(right["codebook"]):
        raise ValueError("Runs must use the same frozen codebook; code mapping is not inferred.")
    rows = []
    for source in sorted(left["sources"]):
        a = [i for i in left["included"] if i["source"] == source]
        b = [i for i in right["included"] if i["source"] == source]
        ca, cb = {i["code_id"] for i in a}, {i["code_id"] for i in b}
        sa = {(i["code_id"], i["start"], i["end"]) for i in a}
        sb = {(i["code_id"], i["start"], i["end"]) for i in b}
        by_code = []
        for code in sorted(ca | cb):
            ai = [i for i in a if i["code_id"] == code]
            bi = [i for i in b if i["code_id"] == code]
            common, union = interval_overlap(ai, bi)
            by_code.append(
                dict(
                    code_id=code,
                    shared_characters=common,
                    union_characters=union,
                    left_spans=len({(i["start"], i["end"]) for i in ai}),
                    right_spans=len({(i["start"], i["end"]) for i in bi}),
                    coverage_jaccard=_ratio(common, union),
                )
            )
        common = sum(c["shared_characters"] for c in by_code)
        union = sum(c["union_characters"] for c in by_code)
        rows.append(
            dict(
                source=source,
                left_codes=len(ca),
                right_codes=len(cb),
                code_intersection=len(ca & cb),
                code_union=len(ca | cb),
                code_jaccard=_ratio(len(ca & cb), len(ca | cb)),
                exact_intersection=len(sa & sb),
                exact_union=len(sa | sb),
                exact_span_jaccard=_ratio(len(sa & sb), len(sa | sb)),
                shared_characters=common,
                union_characters=union,
                coverage_jaccard=_ratio(common, union),
                left_only_spans=[list(x) for x in sorted(sa - sb)],
                right_only_spans=[list(x) for x in sorted(sb - sa)],
                by_code=by_code,
            )
        )
    summary, totals = {}, {}
    for name, num, den in [
        ("code_jaccard", "code_intersection", "code_union"),
        ("exact_span_jaccard", "exact_intersection", "exact_union"),
        ("coverage_jaccard", "shared_characters", "union_characters"),
    ]:
        totals[name] = dict(intersection=sum(r[num] for r in rows), union=sum(r[den] for r in rows))
        summary[name] = _ratio(totals[name]["intersection"], totals[name]["union"])
    return dict(
        kind="qualframe_pairwise_comparison_v1",
        metric_version="raw_overlap_v1",
        scope="source-validated raw proposals only; excludes unresolved proposals and all human edits",
        interpretation="descriptive pairwise agreement, not accuracy or population reliability",
        empty_policy="undefined (null) when both sets are empty; not perfect agreement",
        left=left,
        right=right,
        summary=summary,
        totals=totals,
        transcripts=rows,
    )


def write_comparison(
    repo_root: Path, left_root: Path, right_root: Path, *, dry_run: bool = False
) -> Path:
    report = compare_raw_payloads(
        raw_coding_payload(repo_root, left_root), raw_coding_payload(repo_root, right_root)
    )
    identity = snapshot_identity(report)
    path = left_root / "comparisons" / f"comparison-{identity}.json"
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if snapshot_identity(json.loads(path.read_text(encoding="utf-8"))) != identity:
                raise ValueError("Stored comparison content has changed.")
        else:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
    return path
