from __future__ import annotations

from qualframe.models import StageOutputSpec


def validate_stage_output(
    stage_id: str,
    parsed_output: dict[str, list[dict[str, str]]] | None,
    spec: StageOutputSpec,
) -> list[str]:
    """Return stage-specific structural validation issues for parsed output."""
    rule = spec.stages.get(stage_id)
    if rule is None:
        return [f"No structured-output rule is defined for stage '{stage_id}'."]
    if not parsed_output:
        return ["No structured tables were parsed from the provider response."]

    issues: list[str] = []
    total_rows = sum(len(rows) for rows in parsed_output.values())
    if rule.require_rows and total_rows == 0:
        issues.append("Parsed output contains no data rows.")
    for sheet, rows in parsed_output.items():
        for row_index, row in enumerate(rows):
            missing = [column for column in rule.required_columns if column not in row]
            if missing:
                issues.append(
                    f"Sheet '{sheet}' row {row_index} is missing columns: {', '.join(missing)}."
                )
    return issues
