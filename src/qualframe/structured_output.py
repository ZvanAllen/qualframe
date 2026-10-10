from __future__ import annotations

import hashlib
import json

from qualframe.models import StageOutputSpec


def scoped_contract_sha256(spec: StageOutputSpec | None) -> str | None:
    """Bind explicit stage QA and structural policy; legacy specs remain unbound."""
    if spec is None or not any(rule.qa_rules is not None for rule in spec.stages.values()):
        return None
    payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
            if rule.exact_column_order and list(row) != rule.required_columns:
                issues.append(
                    f"Sheet '{sheet}' row {row_index} columns must exactly match "
                    f"this order: {', '.join(rule.required_columns)}."
                )
            for column, allowed in rule.allowed_values.items():
                if column in row and row[column] not in allowed:
                    issues.append(
                        f"Sheet '{sheet}' row {row_index} has an out-of-scope value "
                        f"for '{column}': {row[column]!r}."
                    )
    for column, required in rule.required_values.items():
        present = {row.get(column) for rows in parsed_output.values() for row in rows}
        missing_values = [value for value in required if value not in present]
        if missing_values:
            issues.append(f"Missing required values for '{column}': {', '.join(missing_values)}.")
    return issues
