from __future__ import annotations

from pathlib import Path

import pytest

from qualframe.io.excel_io import (
    REQUIRED_COLUMNS,
    match_domain_sheets,
    validate_workbook,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOKS_DIR = REPO_ROOT / "data/raw/workbooks"
CFIR_DOMAINS = [
    "Innovation",
    "Outer Setting",
    "Inner Setting",
    "Individuals",
    "Implementation Process",
    "Outcomes Addendum",
]


# --- match_domain_sheets ---

def test_match_domain_sheets_exact() -> None:
    sheets = ["Innovation", "Outer Setting", "Inner Setting"]
    result = match_domain_sheets(sheets, ["Innovation", "Outer Setting"])
    assert result == {"Innovation": "Innovation", "Outer Setting": "Outer Setting"}


def test_match_domain_sheets_with_domain_suffix() -> None:
    sheets = ["Innovation Domain", "Outer Setting", "Inner Setting"]
    result = match_domain_sheets(sheets, ["Innovation"])
    assert result["Innovation"] == "Innovation Domain"


def test_match_domain_sheets_missing() -> None:
    sheets = ["Outer Setting"]
    result = match_domain_sheets(sheets, ["Innovation", "Outer Setting"])
    assert result["Innovation"] is None
    assert result["Outer Setting"] == "Outer Setting"


def test_match_domain_sheets_case_insensitive() -> None:
    sheets = ["innovation domain"]
    result = match_domain_sheets(sheets, ["Innovation"])
    assert result["Innovation"] == "innovation domain"


# --- validate_workbook (real files) ---

real_workbooks = sorted(WORKBOOKS_DIR.glob("*.xlsx"))


@pytest.mark.skipif(not real_workbooks, reason="No workbooks in data/raw/workbooks")
@pytest.mark.parametrize("wb_path", real_workbooks)
def test_real_workbooks_pass_validation(wb_path: Path) -> None:
    result = validate_workbook(wb_path, REQUIRED_COLUMNS, CFIR_DOMAINS)
    assert result.valid, (
        f"{wb_path.name} failed validation — "
        f"missing domains: {result.missing_domain_sheets}, "
        f"column issues: {result.column_issues}"
    )
    assert result.missing_domain_sheets == []
    assert result.column_issues == {}


# --- validate_workbook (synthetic) ---

def test_validate_workbook_reports_missing_domains(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Outer Setting"
    ws.append(["CFIR Domain", "CFIR Construct", "Quote", "Explanation"])
    path = tmp_path / "partial.xlsx"
    wb.save(path)

    result = validate_workbook(path, REQUIRED_COLUMNS, ["Innovation", "Outer Setting"])
    assert not result.valid
    assert "Innovation" in result.missing_domain_sheets
    assert "Outer Setting" not in result.missing_domain_sheets


def test_validate_workbook_reports_missing_columns(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Innovation"
    ws.append(["CFIR Domain", "CFIR Construct"])  # missing Quote and Explanation
    path = tmp_path / "bad_cols.xlsx"
    wb.save(path)

    result = validate_workbook(path, REQUIRED_COLUMNS, ["Innovation"])
    assert not result.valid
    assert "Innovation" in result.column_issues
    assert "Quote" in result.column_issues["Innovation"]
    assert "Explanation" in result.column_issues["Innovation"]
