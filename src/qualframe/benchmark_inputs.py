"""Read-only normalization of explicitly selected historical CFIR coding.

This adapter supplies descriptive benchmark inputs, never human reference labels.
It does not infer equivalent sources from filenames or repair substantive codes.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

from qualframe.cfir_review import cfir_records
from qualframe.directed_analysis import validate_evidence_span_against_source
from qualframe.evidence_review import blocking_review_issues
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import StageArtifact
from qualframe.reviewed_analysis import snapshot_identity

NORMALIZATION_VERSION = "historical_cfir_benchmark_v1"


def _relative(root: Path, value: str | Path) -> tuple[str, Path]:
    root = root.resolve()
    path = Path(str(value).replace("\\", "/"))
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Benchmark input path is outside its declared root.")
    return path.relative_to(root).as_posix(), path


def build_source_mapping(repo_root: Path, source_paths: list[str | Path]) -> dict:
    """Bind canonical source IDs to original paths, file bytes, and extracted text.

    A copied managed-study source may reuse an entry only when both hashes match.
    The original path disambiguates identical transcripts registered separately.
    """
    mapping = {}
    for value in source_paths:
        relative, path = _relative(repo_root, value)
        if relative in mapping:
            raise ValueError("Choose each source once.")
        digest = sha256_for_file(path)
        mapping[relative] = dict(
            source_id="benchmark-source-"
            + snapshot_identity({"original_path": relative, "sha256": digest})[:24],
            original_path=relative,
            sha256=digest,
            extracted_text_sha256=sha256_for_text(transcript_to_text(path)),
        )
    return mapping


def historical_cfir_payload(
    repo_root: Path,
    run_root: Path,
    source_paths: list[str | Path],
    codebook: dict,
    *,
    benchmark_id: str,
    source_mapping: dict | None = None,
    artifact_paths: dict[str, list[str] | str] | None = None,
    expected_domains: list[str] | None = None,
    code_label_policy: str = "legacy_v1",
) -> dict:
    """Normalize selected stage-one artifacts without changing original artifacts.

    Manifest discovery is conservative. Supply ``artifact_paths`` explicitly for
    historical runs whose final resume manifest omitted earlier-stage outputs.
    All selected domains must exist and contain structured CFIR rows. Unverified
    empty partitions block normalization rather than becoming negative labels.
    """
    if code_label_policy not in {"legacy_v1", "qualified_delimiters_v2"}:
        raise ValueError("Unknown CFIR code-label normalization policy.")
    if not benchmark_id.strip() or not source_paths:
        raise ValueError("A benchmark ID and at least one source are required.")
    repo_root, run_root = repo_root.resolve(), run_root.resolve()
    selected = [_relative(repo_root, value)[0] for value in source_paths]
    if len(set(selected)) != len(selected):
        raise ValueError("Choose each source once.")
    codes = copy.deepcopy(codebook.get("codes", []))
    required = {"id", "label", "raw_label", "parent_label", "definition", "domain"}
    if not codes or any(not required <= set(code) for code in codes):
        raise ValueError("Supply the frozen CFIR reference codebook catalog.")
    identifiers = [code["id"] for code in codes]
    duplicate_ids = sorted({value for value in identifiers if identifiers.count(value) > 1})
    # Historical catalogs may contain repeated footnotes. Preserve that catalog
    # as frozen, but never treat an ambiguous identifier as a comparable label.
    known = set(identifiers) - set(duplicate_ids)
    manifest_path, plan_path = run_root / "run_manifest.json", run_root / "run_plan.json"
    if not manifest_path.exists():
        raise ValueError("A historical run manifest is required.")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    manifest = SimpleNamespace(
        run_id=manifest_data["run_id"],
        configuration_fingerprint=manifest_data.get("configuration_fingerprint"),
    )
    declared = {
        _relative(repo_root, entry["path"])[0]: entry.get("sha256")
        for entry in plan.get("discovered_inputs", [])
        if entry.get("kind") == "transcript"
    }
    if declared and any(source not in declared for source in selected):
        raise ValueError("Selected source was not in the historical frozen cohort.")
    mapping = (
        copy.deepcopy(source_mapping)
        if source_mapping is not None
        else build_source_mapping(repo_root, selected)
    )
    mapping = {_relative(repo_root, key)[0]: value for key, value in mapping.items()}
    if set(mapping) != set(selected):
        raise ValueError("Explicit source mapping must cover exactly the selected sources.")
    sources, texts = {}, {}
    for source in selected:
        _, path = _relative(repo_root, source)
        entry = mapping[source]
        if not {"source_id", "original_path", "sha256", "extracted_text_sha256"} <= set(entry):
            raise ValueError("Source mapping must retain original path and both source hashes.")
        identity = (
            "benchmark-source-"
            + snapshot_identity(
                {"original_path": entry["original_path"], "sha256": entry["sha256"]}
            )[:24]
        )
        if identity != entry["source_id"] or identity in sources:
            raise ValueError("Source mapping identity is invalid or duplicated.")
        texts[source] = transcript_to_text(path)
        if (
            sha256_for_file(path) != entry["sha256"]
            or sha256_for_text(texts[source]) != entry["extracted_text_sha256"]
        ):
            raise ValueError("Source content differs from the immutable source mapping.")
        if declared.get(source) and declared[source] != entry["sha256"]:
            raise ValueError("Source content changed since the historical run plan.")
        sources[identity] = entry["sha256"]

    supplied = None
    if artifact_paths is not None:
        supplied = {_relative(repo_root, key)[0]: value for key, value in artifact_paths.items()}
        if set(supplied) != set(selected):
            raise ValueError("Explicit artifact mapping must cover exactly the selected sources.")
    candidates = []
    if supplied is not None:
        for source, values in supplied.items():
            for value in [values] if isinstance(values, str) else values:
                candidates.append((source, value))
    else:
        candidates = [(None, value) for value in manifest_data.get("artifact_paths", [])]
    chosen: dict[str, list[tuple[str, Path, StageArtifact]]] = {source: [] for source in selected}
    seen = set()
    artifact_hashes = {}
    for expected_source, value in candidates:
        relative, path = _relative(run_root, value)
        if relative in seen:
            raise ValueError("An artifact may be selected only once.")
        seen.add(relative)
        artifact = StageArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if artifact.stage_id != "transcript_to_cfir":
            if supplied is not None:
                raise ValueError("Only original transcript_to_cfir artifacts can be normalized.")
            continue
        source, _ = _relative(repo_root, artifact.input_path)
        if supplied is not None and source != expected_source:
            raise ValueError("Artifact source differs from the explicit artifact mapping.")
        if source not in chosen:
            continue
        if artifact.run_id != manifest.run_id or artifact.input_sha256 != mapping[source]["sha256"]:
            raise ValueError("Artifact run/source identity differs from its declared provenance.")
        if artifact.structured_output_valid is False or not artifact.parsed_output:
            raise ValueError("A selected coding artifact is malformed or has no parsed output.")
        chosen[source].append((relative, path, artifact))
        artifact_hashes[relative] = sha256_for_file(path)

    included, excluded, absences, domain_inventory = [], [], [], {}
    prompt_hashes = set()
    alias_audit = []
    for source, entries in chosen.items():
        if not entries:
            raise ValueError(
                "No selected stage-one artifact; supply an explicit artifact mapping "
                "when a legacy resume manifest omits it."
            )
        domains = [
            str(call["domain"])
            for call in plan.get("planned_stage_runs", [])
            if call.get("stage_id") == "transcript_to_cfir"
            and call.get("domain")
            and _relative(repo_root, call.get("input_path", ""))[0] == source
        ]
        required_domains = set(expected_domains if expected_domains is not None else domains)
        if not required_domains:
            raise ValueError(
                "Declare expected CFIR domains when the historical plan does not retain them."
            )
        present_domains = [
            domain for _, _, artifact in entries for domain in artifact.parsed_output
        ]
        if (
            len(set(present_domains)) != len(present_domains)
            or set(present_domains) != required_domains
        ):
            raise ValueError(
                "Selected artifacts must cover each expected CFIR domain exactly once."
            )
        domain_inventory[mapping[source]["source_id"]] = sorted(required_domains)
        for relative, path, artifact in entries:
            prompt_hashes.add(artifact.prompt_sha256)
            for domain, rows in artifact.parsed_output.items():
                if not rows:
                    raise ValueError(
                        "An empty historical domain requires separate verified "
                        "empty-output evidence."
                    )
                for number, row in enumerate(rows, 1):
                    if not {"CFIR Construct", "Quote"} <= set(row):
                        excluded.append(
                            dict(
                                record_id="invalid-row-"
                                + sha256_for_text(f"{relative}:{domain}:{number}")[:20],
                                source=mapping[source]["source_id"],
                                code_id=None,
                                artifact_sha256=artifact_hashes[relative],
                                prompt_sha256=artifact.prompt_sha256,
                                artifact_path=relative,
                                sheet_name=domain,
                                row_index=number,
                                model=artifact.model,
                                provider=artifact.provider,
                                issues=[
                                    "Malformed CFIR row: required construct or "
                                    "quotation column missing"
                                ],
                            )
                        )
            records = cfir_records(
                artifact=artifact,
                artifact_rel=relative,
                artifact_path=path,
                source_path=repo_root / source,
                repo_root=repo_root,
                manifest=manifest,
                codes=codes,
                codebook_hash=codebook.get("version") or snapshot_identity(codebook),
                code_label_policy=code_label_policy,
            )
            for record in records:
                code = record.assignment.code_id if record.assignment else record.proposed_code_id
                raw_row = artifact.parsed_output[record.sheet_name][record.row_index - 1]
                item = dict(
                    record_id=record.record_id,
                    source=mapping[source]["source_id"],
                    code_id=code,
                    model=record.model,
                    provider=record.provider,
                    prompt_sha256=record.prompt_sha256,
                    artifact_sha256=record.artifact_sha256,
                    anchoring_method=record.anchoring_method,
                    artifact_path=relative,
                    sheet_name=record.sheet_name,
                    row_index=record.row_index,
                    original_construct=raw_row["CFIR Construct"],
                    original_domain=raw_row.get("CFIR Domain"),
                    proposed_quotation=record.proposed_exact_text,
                    rationale=record.proposed_rationale,
                )
                if (
                    code_label_policy == "qualified_delimiters_v2"
                    and code in known
                    and len(re.split(r"\s+[–—-]\s+", str(raw_row["CFIR Construct"]))) == 2
                ):
                    alias = dict(
                        policy=code_label_policy,
                        original_label=raw_row["CFIR Construct"],
                        canonical_code_id=code,
                        canonical_label=record.code_label,
                        domain=record.sheet_name,
                        artifact_path=relative,
                        row_index=record.row_index,
                        record_id=record.record_id,
                    )
                    item["code_label_normalization"] = alias
                    alias_audit.append(alias)
                if record.record_kind == "absence":
                    (absences if code in known else excluded).append(
                        item
                        if code in known
                        else dict(
                            item,
                            issues=[
                                "Ambiguous duplicate identifier in frozen codebook"
                                if code in duplicate_ids
                                else "Unknown code in absence proposal"
                            ],
                        )
                    )
                    continue
                issues = blocking_review_issues(record, texts[source])
                span = record.evidence_span
                if code not in known:
                    issues.append(
                        "Ambiguous duplicate identifier in frozen codebook"
                        if code in duplicate_ids
                        else "Unknown code"
                    )
                if span is None:
                    issues.append("Missing source span")
                else:
                    try:
                        validate_evidence_span_against_source(span, texts[source])
                    except ValueError as exc:
                        issues.append(str(exc))
                if issues:
                    excluded.append(dict(item, issues=sorted(set(issues))))
                else:
                    included.append(
                        dict(
                            item,
                            start=span.start_offset,
                            end=span.end_offset,
                            exact_text=span.exact_text,
                        )
                    )
    origin = dict(
        project_id=manifest_data.get("project_id"),
        run_id=manifest.run_id,
        manifest_sha256=sha256_for_file(manifest_path),
        plan_sha256=sha256_for_file(plan_path) if plan_path.exists() else None,
        artifact_selection="explicit operator mapping" if supplied is not None else "run manifest",
        source_mapping=mapping,
        source_mapping_sha256=snapshot_identity(mapping),
        selected_original_sources=selected,
        excluded_original_sources=[
            dict(path=path, sha256=digest, reason="outside explicitly selected benchmark subset")
            for path, digest in sorted(declared.items())
            if path not in selected
        ],
        original_cohort_known=bool(declared),
        expected_domains=domain_inventory,
        prompt_sha256s=sorted(prompt_hashes),
        original_configuration_available=bool(manifest.configuration_fingerprint),
        normalization_version=NORMALIZATION_VERSION,
        ambiguous_catalog_code_ids=duplicate_ids,
        normalization_policy=(
            "CFIR catalog alias/parent matching and unique exact/typography "
            "anchoring; substantive disagreements retained"
        ),
        human_reference=False,
        cohort_cost_policy=(
            "original whole-run cost retained separately; selected-cohort cost not inferred"
        ),
        original_run_cost_usd=manifest_data.get("run_cost_usd"),
    )
    if code_label_policy != "legacy_v1":
        origin["normalization_version"] = "historical_cfir_benchmark_qualified_delimiters_v2"
        origin["code_label_policy"] = code_label_policy
        origin["normalization_policy"] += (
            "; explicitly qualified parent-child dash delimiters matched literally"
        )
        origin["code_label_aliases"] = alias_audit
    return dict(
        kind="qualframe_raw_comparison_input_v1",
        run_id=manifest.run_id,
        project_id=benchmark_id,
        configuration_fingerprint=manifest.configuration_fingerprint,
        configuration_assets=manifest_data.get("configuration_assets", []),
        codebook=copy.deepcopy(codebook),
        sources=sources,
        run_cost_usd=None,
        index_sha256=None,
        artifact_hashes=artifact_hashes,
        included=included,
        excluded=excluded,
        absences=absences,
        benchmark_provenance=origin,
    )
