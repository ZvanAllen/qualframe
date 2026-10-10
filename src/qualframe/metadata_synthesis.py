"""Versioned, source-linked CSV metadata scopes for reviewed analysis."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from qualframe.config import load_project_manifest
from qualframe.io.files import sha256_for_file
from qualframe.models import SourceImportRecord
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.study_setup import StudyWorkspace


def _study_path(repo_root: Path, study_root: Path, value: str) -> Path:
    path = (repo_root / value.replace("\\", "/")).resolve()
    if not path.is_relative_to(study_root.resolve()):
        raise ValueError("Metadata linkage leaves the managed study boundary.")
    return path


def read_metadata_catalog(project_path: Path, source_paths: list[str]) -> dict:
    """Read the active imported version; never infer links from basenames or folders."""
    project_path = project_path.resolve()
    repo_root = project_path.parents[2]
    study_root = StudyWorkspace(repo_root).managed_study_root(project_path)
    project = load_project_manifest(project_path)
    if not project.metadata_file or not project.source_manifest:
        raise ValueError("Import a metadata CSV in the source library before grouping summaries.")
    metadata = _study_path(repo_root, study_root, project.metadata_file)
    manifest = _study_path(repo_root, study_root, project.source_manifest)
    records = [
        SourceImportRecord.model_validate_json(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record.source_kind == "metadata"
        and _study_path(repo_root, study_root, record.destination_path) == metadata
    ]
    if len(matching) != 1:
        raise ValueError("The active metadata version needs one verified import record.")
    digest = sha256_for_file(metadata)
    if matching[0].sha256 != digest:
        raise ValueError("Metadata changed after import. Import a new metadata version.")
    content = metadata.read_bytes().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    fields = reader.fieldnames or []
    if (
        "source_filename" not in fields
        or any(not name.strip() for name in fields)
        or len(set(fields)) != len(fields)
    ):
        raise ValueError("Metadata requires unique nonblank column names and source_filename.")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Each metadata row must match the CSV columns.")
    names = [row["source_filename"].strip() for row in rows]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Metadata source_filename values must be nonblank and unique.")
    by_name = dict(zip(names, rows, strict=True))
    transcripts = [record for record in records if record.source_kind == "transcript"]
    original_names = [record.original_filename for record in transcripts]
    if len({name.casefold() for name in original_names}) != len(original_names):
        raise ValueError("Imported transcript filenames are ambiguous for metadata linkage.")
    if set(names) - set(original_names):
        raise ValueError("Metadata references a source outside the study import manifest.")
    by_path = {}
    for record in transcripts:
        source = _study_path(repo_root, study_root, record.destination_path)
        if source in by_path:
            raise ValueError("A source has duplicate metadata import links.")
        by_path[source] = record
    linked = []
    for source_name in sorted(set(p.replace("\\", "/") for p in source_paths)):
        source = _study_path(repo_root, study_root, source_name)
        record = by_path.get(source)
        if record is None:
            raise ValueError(
                "A reviewed source has no transcript import record for metadata linkage."
            )
        if sha256_for_file(source) != record.sha256:
            raise ValueError("A metadata-linked transcript changed after import.")
        row = by_name.get(record.original_filename)
        linked.append(
            dict(
                source_path=source_name,
                source_id=record.source_id,
                source_sha256=record.sha256,
                original_filename=record.original_filename,
                has_metadata_row=row is not None,
                values={
                    field: row[field].strip() if row else ""
                    for field in fields
                    if field != "source_filename"
                },
            )
        )
    return dict(
        project_id=project.project_id,
        metadata_path=metadata.relative_to(repo_root).as_posix(),
        metadata_sha256=digest,
        metadata_content=content,
        metadata_import=matching[0].model_dump(mode="json"),
        fields=[field for field in fields if field != "source_filename"],
        sources=linked,
    )


def freeze_metadata_grouping(
    catalog: dict, field: str, *, values: list[str] | None = None, missing_policy: str = "error"
) -> dict:
    if field not in catalog["fields"]:
        raise ValueError("Choose a field from the current metadata version.")
    if missing_policy not in {"error", "exclude", "separate"}:
        raise ValueError(
            "Choose whether missing metadata blocks, excludes, or forms a separate scope."
        )
    available = {row["values"][field] for row in catalog["sources"] if row["values"][field]}
    selected = available if values is None else {value for value in values if value != ""}
    if selected - available:
        raise ValueError("A selected metadata value is absent from this reviewed snapshot.")
    missing = [row["source_path"] for row in catalog["sources"] if not row["values"][field]]
    if missing and missing_policy == "error":
        raise ValueError(
            f"{len(missing)} reviewed source(s) have no value for {field}. "
            "Choose an explicit missing-value policy or import corrected metadata."
        )
    groups, excluded = {}, []
    for row in catalog["sources"]:
        value = row["values"][field]
        if not value and missing_policy != "separate":
            excluded.append(dict(source_path=row["source_path"], reason="missing_metadata"))
            continue
        if value and value not in selected:
            excluded.append(
                dict(source_path=row["source_path"], reason="unselected_metadata_value")
            )
            continue
        definition = dict(field=field, kind="value" if value else "missing", value=value or None)
        identity = snapshot_identity(definition)[:16]
        group = groups.setdefault(
            identity,
            dict(
                group_id=identity,
                definition=definition,
                label=f'{field}: "{value}"' if value else f"{field}: [missing value]",
                source_paths=[],
            ),
        )
        group["source_paths"].append(row["source_path"])
    if not groups:
        raise ValueError("Select at least one metadata value or include a missing-value scope.")
    return dict(
        kind="qualframe_metadata_grouping_v1",
        field=field,
        selected_values=sorted(selected),
        missing_policy=missing_policy,
        groups=sorted(groups.values(), key=lambda group: (group["label"], group["group_id"])),
        missing_sources=missing,
        excluded_sources=excluded,
        catalog=catalog,
    )


def metadata_group_matrix(plan: dict) -> list[dict]:
    """Frozen counts of unique source spans; records remain linked to their sources."""
    grouping = plan.get("metadata_grouping")
    if not grouping:
        return []
    calls = {call["group_id"]: call["input"] for call in plan["calls"]}
    codes = {code["id"]: code for code in plan["codebook"]["codes"]}
    result = []
    for group in grouping["groups"]:
        evidence = calls.get(group["group_id"], {}).get("evidence", [])
        for code_id, code in sorted(codes.items()):
            items = [item for item in evidence if item["code_id"] == code_id]
            spans = {(item["source_path"], item["start"], item["end"]) for item in items}
            result.append(
                dict(
                    group_id=group["group_id"],
                    group_label=group["label"],
                    code_id=code_id,
                    code_label=code["label"],
                    source_paths=group["source_paths"],
                    distinct_spans=len(spans),
                    evidence=items,
                )
            )
    return result
