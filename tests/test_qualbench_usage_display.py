import json
import re
from types import SimpleNamespace

from qualframe.qualbench import build_qualbench
from qualframe.qualbench_ui import _report_html
from test_qualbench import _set


def _page(tmp_path, profile):
    report = build_qualbench([_set("one", []), _set("two", [])])
    report["coding_sets"][0].update(profile)
    (tmp_path / "report.json").write_text(json.dumps(report))
    app = SimpleNamespace(_file_link=lambda path, label: label)
    return _report_html(app, tmp_path)


def test_historical_costs_are_not_relabelled_as_cohort_costs(tmp_path):
    page = _page(tmp_path, dict(cost_usd=9, elapsed_seconds=5))
    first = re.search(r"<tbody><tr>(.*?)</tr>", page).group(1)
    values = re.findall(r"<td[^>]*>(.*?)</td>", first)
    assert values[5:9] == ["n/a", "n/a", "$9.00", "5 s"]


def test_unknown_cohort_cost_and_estimates_are_visible(tmp_path):
    page = _page(tmp_path, dict(cohort_cost_usd=None, cohort_elapsed_seconds=0,
        whole_run_cost_usd=5, whole_run_elapsed_seconds=2, whole_run_cost_is_estimated=True,
        cohort_usage_note="Cost ledger is missing; cost and token totals are unknown."))
    assert "Usage coverage and estimates" in page
    assert "Cost ledger is missing" in page and "Whole run: includes estimated costs." in page
    first = re.search(r"<tbody><tr>(.*?)</tr>", page).group(1)
    assert re.findall(r"<td[^>]*>(.*?)</td>", first)[5:9] == ["n/a", "0 s", "$5.00", "2 s"]
