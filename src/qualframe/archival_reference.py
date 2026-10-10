"""Read-only, hash-bound import of historical human-reviewed assisted evidence.

Imported offsets are derived source links, never historical adjudication events.
Public examples must use synthetic records; real quotations stay in private files.
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from qualframe.cfir_review import normalized_with_offsets
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.transcript_io import transcript_to_text
from qualframe.reviewed_analysis import snapshot_identity

ORIGIN = "historical_human_reviewed_ai_assisted"
SHARED_DOMAINS = (
    "Innovation",
    "Outer Setting",
    "Inner Setting",
    "Individuals",
    "Implementation Process",
)
ANCHOR_POLICY = "archival_exact_typographic_whitespace_v1"


def canonical_domain(value: str | None) -> str | None:
    """Literal CFIR case/domain-suffix aliases only; original labels are retained."""
    if not isinstance(value, str):
        return None
    aliases = {
        alias.lower(): name
        for name in (*SHARED_DOMAINS, "Outcomes Addendum")
        for alias in (name, name + " Domain")
    }
    return aliases.get(value.strip().lower())


def _catalog(codebook: dict) -> tuple[dict[str, dict], set[str]]:
    codes = codebook.get("codes")
    required = {"id", "label", "raw_label", "parent_label", "definition", "domain"}
    if (
        not isinstance(codes, list)
        or not codes
        or any(
            not isinstance(c, dict)
            or not required <= c.keys()
            or any(not isinstance(c[k], str) for k in required)
            or not c["id"]
            for c in codes
        )
    ):
        raise ValueError("An archival import needs the complete frozen CFIR catalog.")
    counts = Counter(c["id"] for c in codes)
    duplicates = {key for key, count in counts.items() if count > 1}
    return {c["id"]: c for c in codes if c["id"] not in duplicates}, duplicates


def build_parent_projection(codebook: dict) -> dict[str, str]:
    """Resolve exact parent names in the same domain; omit ambiguous/missing parents."""
    known, _ = _catalog(codebook)
    result = {}
    for identifier, code in sorted(known.items()):
        if not code["parent_label"]:
            result[identifier] = identifier
            continue
        parents = [
            p
            for p in known.values()
            if not p["parent_label"]
            and p["raw_label"] == code["parent_label"]
            and canonical_domain(p["domain"]) == canonical_domain(code["domain"])
            and canonical_domain(p["domain"]) is not None
        ]
        if len(parents) == 1:
            result[identifier] = parents[0]["id"]
    return result


def validate_parent_projection(codebook: dict, projection: dict) -> None:
    expected = build_parent_projection(codebook)
    if not isinstance(projection, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or expected.get(key) != value
        for key, value in projection.items()
    ):
        raise ValueError("Parent projection must follow unique exact same-domain catalog parents.")


def _within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("Import paths must be nonblank relative paths.")
    candidate = Path(relative.replace("\\", "/"))
    if candidate.is_absolute() or candidate.drive:
        raise ValueError("Import paths must be relative to their declared root.")
    path = (root.resolve() / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Import path leaves its declared root.")
    return path


def _pointer(data: object, pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Each archival quotation needs a JSON pointer.")
    value = data
    try:
        for part in pointer[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not key.isdigit() or str(int(key)) != key:
                    raise ValueError("Invalid JSON array pointer.")
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise ValueError("JSON pointer does not address a quotation.")
    except (IndexError, KeyError) as exc:
        raise ValueError("JSON pointer does not exist in the frozen reference.") from exc
    if not isinstance(value, str):
        raise ValueError("JSON pointer must resolve to one quotation string.")
    return value


def _normalized(text: str) -> tuple[str, list[tuple[int, int]]]:
    # Explorer's declared typography tier also treats en/em dash as hyphen.
    return normalized_with_offsets(text.translate(str.maketrans({"–": "-", "—": "-"})))


def _locations(text: str, needle: str) -> list[tuple[int, int]]:
    result, cursor = [], 0
    while needle and (start := text.find(needle, cursor)) >= 0:
        result.append((start, start + len(needle)))
        cursor = start + 1
    return result


def strict_quote_candidates(
    source: str,
    quote: str,
    *,
    normalized_source: tuple[str, list[tuple[int, int]]] | None = None,
) -> tuple[str | None, list[tuple[int, int]]]:
    exact = _locations(source, quote)
    if exact:
        return "exact", exact
    needle = _normalized(quote)[0].strip()
    value, offsets = normalized_source if normalized_source is not None else _normalized(source)
    spans = [(offsets[a][0], offsets[b - 1][1]) for a, b in _locations(value, needle)]
    for start, end in spans:
        if _normalized(source[start:end])[0].strip() != needle:
            raise ValueError("Normalized archival match failed source-slice verification.")
    return ("typographic_whitespace" if spans else None), spans


def _entry_identity(entries: list[dict]) -> None:
    if not isinstance(entries, list):
        raise ValueError("Archival entries must be a list.")
    seen = set()
    for row in entries:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("record_id"), str)
            or not row["record_id"]
        ):
            raise ValueError("Archival entries need stable nonblank record IDs.")
        if row["record_id"] in seen:
            raise ValueError("Archival record IDs must be unique across layers.")
        seen.add(row["record_id"])
        if not isinstance(row.get("issues", []), list) or any(
            not isinstance(v, str) for v in row.get("issues", [])
        ):
            raise ValueError("Archival issues must be explicit strings.")


def load_archival_reference(
    import_path: Path,
    *,
    source_root: Path,
    reference_root: Path,
    layer: str,
    source_ids: list[str] | None = None,
) -> dict:
    """Verify a frozen import manifest; select one layer/cohort without any writes.

    Every source/file hash is rechecked, including inventoried but unselected sources.
    Quote bodies use explicit half-open offsets within a frozen JSON pointer string.
    Unknown labels/attribution and non-unique anchors are retained as exclusions.
    """
    digest = sha256_for_file(import_path)
    manifest = json.loads(import_path.read_text(encoding="utf-8-sig"))
    if (
        manifest.get("kind") != "qualframe_archival_reference_import_v1"
        or manifest.get("origin") != ORIGIN
    ):
        raise ValueError("Select a versioned historical human-reviewed AI-assisted import.")
    for key in ("reference_id", "project_id"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"Archival import requires {key}.")
    review = manifest.get("review_provenance", {})
    if not isinstance(review, dict) or not review.get("statement") or not review.get("basis"):
        raise ValueError("Retain the stated historical review provenance and its basis.")
    if review.get("independent_human_coding") is True:
        raise ValueError(
            "This adapter does not label assisted analysis as independent human coding."
        )
    codebook = manifest["codebook"]
    if snapshot_identity(codebook) != manifest.get("codebook_sha256"):
        raise ValueError("Frozen codebook hash differs.")
    known, duplicate_ids = _catalog(codebook)
    projection = manifest["parent_projection"]
    validate_parent_projection(codebook, projection)
    mapping = manifest["source_mapping"]
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("An explicit canonical source mapping is required.")
    sources, texts, paths = {}, {}, []
    for relative, entry in mapping.items():
        path = _within(source_root, relative)
        _within(source_root, entry["original_path"])
        identifier = (
            "benchmark-source-"
            + snapshot_identity(
                {"original_path": entry["original_path"], "sha256": entry["sha256"]}
            )[:24]
        )
        if identifier != entry["source_id"] or identifier in sources:
            raise ValueError("Canonical source identity is invalid or duplicated.")
        text = transcript_to_text(path)
        if (
            sha256_for_file(path) != entry["sha256"]
            or sha256_for_text(text) != entry["extracted_text_sha256"]
        ):
            raise ValueError("Source file or extracted-text hash differs from the frozen import.")
        sources[identifier], texts[identifier] = entry["sha256"], text
        paths.append((path, entry["sha256"]))
    selected = set(sources if source_ids is None else source_ids)
    if (
        not selected
        or not selected <= sources.keys()
        or (source_ids is not None and len(selected) != len(source_ids))
    ):
        raise ValueError("Choose a nonempty, unique subset of canonical source IDs.")
    documents, file_hashes = {}, {}
    for key, entry in manifest["reference_files"].items():
        path = _within(reference_root, entry["path"])
        if sha256_for_file(path) != entry["sha256"]:
            raise ValueError("Reference file hash differs from the frozen import.")
        documents[key] = json.loads(path.read_text(encoding="utf-8-sig"))
        file_hashes[key] = entry["sha256"]
        paths.append((path, entry["sha256"]))
    entries = manifest["entries"]
    _entry_identity(entries)
    if not isinstance(layer, str) or layer not in {entry.get("layer") for entry in entries}:
        raise ValueError("Select one declared archival evidence layer.")
    included, excluded, outside = [], [], []
    normalized_sources = {identifier: _normalized(texts[identifier]) for identifier in selected}
    for original in entries:
        item = deepcopy(original)
        issues = list(item.get("issues", []))
        alias = item["reference_file"]
        if alias not in documents:
            raise ValueError("Quotation references an undeclared frozen file.")
        quotation = _pointer(documents[alias], item["json_pointer"])
        item.update(original_quotation=quotation, reference_file_sha256=file_hashes[alias])
        start, end = item.get("body_start"), item.get("body_end")
        valid_body = type(start) is int and type(end) is int and 0 <= start < end <= len(quotation)
        body = quotation[start:end] if valid_body else ""
        item.update(
            proposed_quotation=body,
            original_code_id=item.get("code_id"),
            original_domain=item.get("domain"),
        )
        domain = canonical_domain(item.get("domain"))
        item["canonical_domain"] = domain
        outside_reasons = []
        if item.get("layer") != layer:
            outside_reasons.append("outside_selected_layer")
        if item.get("source") in sources and item["source"] not in selected:
            outside_reasons.append("outside_selected_source_cohort")
        if domain == "Outcomes Addendum":
            outside_reasons.append("outside_shared_five_domain_scope")
        if outside_reasons:
            outside.append(dict(item, scope_exclusions=outside_reasons))
            continue
        code = known.get(item.get("code_id"))
        if not valid_body or not body.strip():
            issues.append("missing_or_invalid_quote_body")
        if item.get("source") not in selected:
            issues.append("unresolved_source_attribution")
        if item.get("code_id") in duplicate_ids:
            issues.append("ambiguous_catalog_code_id")
        elif code is None:
            issues.append("unresolved_code_id")
        elif canonical_domain(code["domain"]) != domain or domain is None:
            issues.append("code_domain_mismatch")
        if code is not None and code["id"] not in projection:
            issues.append("unresolved_parent_projection")
        anchor = item.get("anchor")
        if anchor is not None and (
            not isinstance(anchor, dict)
            or anchor.get("method") not in {"exact", "typographic_whitespace"}
        ):
            issues.append("anchor_outside_strict_policy")
        if valid_body and item.get("source") in selected:
            method, spans = strict_quote_candidates(
                texts[item["source"]], body, normalized_source=normalized_sources[item["source"]]
            )
            item["derived_anchor_candidates"] = [
                dict(start=a, end=b, method=method) for a, b in spans
            ]
            if len(spans) != 1:
                issues.append(
                    "ambiguous_source_anchor" if spans else "quote_not_found_under_strict_policy"
                )
            elif (
                anchor is not None
                and isinstance(anchor, dict)
                and (
                    type(anchor.get("start")) is not int
                    or type(anchor.get("end")) is not int
                    or (anchor["start"], anchor["end"]) != spans[0]
                    or anchor.get("method") != method
                )
            ):
                issues.append("audited_anchor_differs_from_verified_source_match")
            if len(spans) == 1 and not issues:
                a, b = spans[0]
                item.update(
                    start=a, end=b, exact_text=texts[item["source"]][a:b], anchoring_method=method
                )
        if issues:
            excluded.append(dict(item, issues=sorted(set(issues))))
        else:
            included.append(dict(item, issues=[]))
    if sha256_for_file(import_path) != digest or any(
        sha256_for_file(path) != expected for path, expected in paths
    ):
        raise ValueError("An archival input changed during import.")
    selected_mapping = {
        key: deepcopy(value) for key, value in mapping.items() if value["source_id"] in selected
    }
    unique_spans = {
        (item["source"], projection[item["code_id"]], item["start"], item["end"])
        for item in included
    }
    result = dict(
        kind="qualframe_archival_reference_v1",
        reference_id=manifest["reference_id"],
        run_id="archival:" + manifest["reference_id"],
        project_id=manifest["project_id"],
        origin=ORIGIN,
        configuration_fingerprint=None,
        configuration_assets=[],
        run_cost_usd=None,
        index_sha256=None,
        codebook=deepcopy(codebook),
        sources={key: sources[key] for key in sorted(selected)},
        artifact_hashes=file_hashes,
        included=included,
        excluded=excluded,
        absences=[],
        out_of_scope=outside,
        parent_projection=deepcopy(projection),
        layer=layer,
        shared_domains=list(SHARED_DOMAINS),
        coverage=deepcopy(manifest.get("coverage", {})),
        review_provenance=deepcopy(review),
        benchmark_provenance=dict(
            origin=ORIGIN,
            import_sha256=digest,
            codebook_sha256=snapshot_identity(codebook),
            source_mapping=selected_mapping,
            source_mapping_sha256=snapshot_identity(selected_mapping),
            original_source_mapping_sha256=snapshot_identity(mapping),
            original_source_count=len(sources),
            selected_source_count=len(selected),
            quote_anchoring_policy=ANCHOR_POLICY,
            offsets_origin="newly_derived_source_bindings",
            independent_human_reference=False,
            adjudication_actions_created=0,
            ambiguous_catalog_code_ids=sorted(duplicate_ids),
            parent_projection_sha256=snapshot_identity(projection),
        ),
        inventory_counts=dict(
            total_entries=len(entries),
            included_entries=len(included),
            excluded_entries=len(excluded),
            out_of_scope_entries=len(outside),
            unique_parent_spans=len(unique_spans),
            duplicate_entries=len(included) - len(unique_spans),
            eligibility_denominator=len(included) + len(excluded),
            eligible_fraction=len(included) / (len(included) + len(excluded))
            if included or excluded
            else None,
        ),
    )
    result["content_sha256"] = snapshot_identity(result)
    return result
