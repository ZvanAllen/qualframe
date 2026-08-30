from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from qualframe.models import DisagreementRecord, DisagreementSpec, StageArtifact


def _normalized(value: str | None, case_sensitive: bool) -> str:
    collapsed = " ".join((value or "").split())
    return collapsed if case_sensitive else collapsed.casefold()


def _row_index(
    artifact: StageArtifact,
    identity_columns: list[str],
) -> dict[tuple[str, tuple[str, ...]], dict[str, str]]:
    index: dict[tuple[str, tuple[str, ...]], dict[str, str]] = {}
    for sheet, rows in (artifact.parsed_output or {}).items():
        for row in rows:
            identity = tuple(str(row.get(column, "")).strip() for column in identity_columns)
            index[(sheet, identity)] = row
    return index


def detect_disagreements(
    *,
    run_id: str,
    left: StageArtifact,
    right: StageArtifact,
    left_label: str,
    right_label: str,
    spec: DisagreementSpec,
) -> list[DisagreementRecord]:
    """Compare two structured artifacts and return unresolved disagreement records."""
    if left.stage_id != right.stage_id:
        raise ValueError("Artifacts must come from the same stage for disagreement detection.")

    left_rows = _row_index(left, spec.identity_columns)
    right_rows = _row_index(right, spec.identity_columns)
    records: list[DisagreementRecord] = []
    detected_at = datetime.now(timezone.utc).isoformat()

    for sheet, identity_values in sorted(set(left_rows) | set(right_rows)):
        left_row = left_rows.get((sheet, identity_values))
        right_row = right_rows.get((sheet, identity_values))
        identity = dict(zip(spec.identity_columns, identity_values, strict=True))
        if left_row is None or right_row is None:
            fields = ["__row_presence__"]
        else:
            fields = spec.compare_columns or sorted(
                (set(left_row) | set(right_row)) - set(spec.identity_columns)
            )

        for field in fields:
            if field == "__row_presence__":
                left_value = "present" if left_row is not None else None
                right_value = "present" if right_row is not None else None
            else:
                left_value = None if left_row is None else str(left_row.get(field, ""))
                right_value = None if right_row is None else str(right_row.get(field, ""))
            if _normalized(left_value, spec.case_sensitive) == _normalized(
                right_value, spec.case_sensitive
            ):
                continue
            records.append(
                DisagreementRecord(
                    record_id=f"disagreement-{uuid4().hex}",
                    run_id=run_id,
                    stage_id=left.stage_id,
                    spec_id=spec.id,
                    sheet=sheet,
                    identity=identity,
                    field=field,
                    left_value=left_value,
                    right_value=right_value,
                    left_artifact=left_label,
                    right_artifact=right_label,
                    left_prompt_sha256=left.prompt_sha256,
                    right_prompt_sha256=right.prompt_sha256,
                    left_input_sha256=left.input_sha256,
                    right_input_sha256=right.input_sha256,
                    detected_at_utc=detected_at,
                )
            )
    return records


def write_disagreement_records(records: list[DisagreementRecord], review_dir: Path) -> list[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in records:
        path = review_dir / f"{record.record_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        written.append(path)
    return written
