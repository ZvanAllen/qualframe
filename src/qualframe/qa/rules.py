from __future__ import annotations

from dataclasses import dataclass, field


# Columns that carry per-network valence ratings in cross-network output
_NETWORK_VALENCE_COLUMNS = [
    "Facilitator Networks",
    "Barrier Networks",
    "Mixed Networks",
    "Neutral/Unclear Networks",
]


@dataclass
class QARuleResult:
    rule_id: str
    passed: bool
    details: str


@dataclass
class ReviewQueueItem:
    run_id: str
    stage_id: str
    rule_id: str
    row_index: int | None  # None for artifact-level rules
    row_data: dict | None
    reason: str


# ---------------------------------------------------------------------------
# Individual rule functions
# ---------------------------------------------------------------------------

def check_network_valence_exclusivity(row: dict[str, str]) -> QARuleResult:
    """No network label should appear in more than one valence column."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for column in _NETWORK_VALENCE_COLUMNS:
        raw = row.get(column, "")
        if not raw:
            continue
        labels = {item.strip() for item in raw.split(";") if item.strip()}
        overlap = seen.intersection(labels)
        duplicates.update(overlap)
        seen.update(labels)

    passed = not duplicates
    details = "No duplicated network labels across valence columns." if passed else (
        "Duplicated network labels found across valence columns: " + ", ".join(sorted(duplicates))
    )
    return QARuleResult(rule_id="one_network_one_valence", passed=passed, details=details)


def check_required_keys(row: dict[str, str], required: list[str]) -> QARuleResult:
    """All required column keys must be present in the row."""
    missing = [key for key in required if key not in row]
    return QARuleResult(
        rule_id="required_columns_present",
        passed=not missing,
        details="Missing keys: " + ", ".join(missing) if missing else "All required keys present.",
    )


def check_allowed_network_labels(
    row: dict[str, str], allowed_labels: list[str]
) -> QARuleResult:
    """Every network label in valence columns must be in the framework's allowed list."""
    allowed_set = set(allowed_labels)
    unexpected: set[str] = set()

    for col in _NETWORK_VALENCE_COLUMNS:
        for label in row.get(col, "").split(";"):
            label = label.strip()
            if label and label not in allowed_set:
                unexpected.add(label)

    passed = not unexpected
    details = (
        "All network labels are allowed." if passed
        else "Unexpected network labels: " + ", ".join(sorted(unexpected))
    )
    return QARuleResult(rule_id="allowed_network_labels_only", passed=passed, details=details)


def check_source_files_covered_by_valence(row: dict[str, str]) -> QARuleResult:
    """Every source listed should appear in at least one network valence column."""
    sources = {s.strip() for s in row.get("Source File(s)", "").split(";") if s.strip()}
    if not sources:
        return QARuleResult(
            rule_id="source_files_covered_by_valence_columns",
            passed=True,
            details="No source files column present; skipping.",
        )

    in_valence: set[str] = set()
    for col in _NETWORK_VALENCE_COLUMNS:
        for label in row.get(col, "").split(";"):
            in_valence.add(label.strip())

    uncovered = sources - in_valence - {""}
    passed = not uncovered
    details = (
        "All source files covered by at least one valence column." if passed
        else "Sources missing from valence columns: " + ", ".join(sorted(uncovered))
    )
    return QARuleResult(
        rule_id="source_files_covered_by_valence_columns", passed=passed, details=details
    )


def check_prompt_version_present(prompt_sha256: str | None) -> QARuleResult:
    """The artifact must record a non-empty prompt SHA256."""
    passed = bool(prompt_sha256)
    return QARuleResult(
        rule_id="prompt_version_required",
        passed=passed,
        details="Prompt SHA256 recorded." if passed else "prompt_sha256 is missing or empty.",
    )


# ---------------------------------------------------------------------------
# Dispatcher: run all applicable rules against one artifact's parsed output
# ---------------------------------------------------------------------------

def run_qa_on_artifact(
    run_id: str,
    stage_id: str,
    prompt_sha256: str | None,
    parsed_output: dict[str, list[dict[str, str]]] | None,
    allowed_network_labels: list[str],
    required_columns: list[str],
    enabled_rules: list[str] | None = None,
) -> list[ReviewQueueItem]:
    """Run all applicable QA rules and return a list of ReviewQueueItems for failures."""
    failures: list[ReviewQueueItem] = []

    active = set(enabled_rules) if enabled_rules is not None else {
        "required_columns_present",
        "one_network_one_valence",
        "allowed_network_labels_only",
        "source_files_covered_by_valence_columns",
        "prompt_version_required",
    }

    if "prompt_version_required" in active:
        result = check_prompt_version_present(prompt_sha256)
        if not result.passed:
            failures.append(ReviewQueueItem(
                run_id=run_id,
                stage_id=stage_id,
                rule_id=result.rule_id,
                row_index=None,
                row_data=None,
                reason=result.details,
            ))

    if not parsed_output:
        return failures

    for sheet_name, rows in parsed_output.items():
        for i, row in enumerate(rows):
            checks = {
                "required_columns_present": check_required_keys(row, required_columns),
                "one_network_one_valence": check_network_valence_exclusivity(row),
                "allowed_network_labels_only": check_allowed_network_labels(
                    row, allowed_network_labels
                ),
                "source_files_covered_by_valence_columns": (
                    check_source_files_covered_by_valence(row)
                ),
            }
            for rule_id in active:
                rule_result = checks.get(rule_id)
                if rule_result is None:
                    continue
                if not rule_result.passed:
                    failures.append(ReviewQueueItem(
                        run_id=run_id,
                        stage_id=stage_id,
                        rule_id=rule_result.rule_id,
                        row_index=i,
                        row_data={"sheet": sheet_name, **row},
                        reason=rule_result.details,
                    ))

    return failures
