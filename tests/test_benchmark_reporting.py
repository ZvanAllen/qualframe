import json

import pytest
from test_benchmark_metrics import payload

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.benchmark_reporting import (
    benchmark_csv,
    render_benchmark_html,
    write_benchmark_bundle,
)


def example():
    left = payload("left", [("s1", "c1", 0, 10)])
    right = payload("right", [("s1", "c1", 0, 5), ("s1", "c1", 5, 10)])
    return build_benchmark_report(left, right)


def test_immutable_bundle_dry_run_repeat_and_tampering(tmp_path):
    report = example()
    path = write_benchmark_bundle(report, tmp_path, dry_run=True)
    assert not path.parent.exists()
    assert write_benchmark_bundle(report, tmp_path) == path
    assert json.loads((path.parent / "report.json").read_text(encoding="utf-8")) == report
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    write_benchmark_bundle(report, tmp_path)
    assert before == {p.name: p.read_bytes() for p in path.parent.iterdir()}
    path.write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="Stored benchmark bundle changed"):
        write_benchmark_bundle(report, tmp_path)
    assert path.read_text() == "modified"


def test_report_escapes_labels_and_does_not_display_quotations():
    report = example()
    report["inputs"]["left"]["run_id"] = "<script>alert(1)</script>"
    report["inputs"]["left"]["included"][0]["exact_text"] = "Private quotation never displayed"
    html = render_benchmark_html(report)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "Private quotation never displayed" not in html
    assert "66.7%" in html and "not measure qualitative accuracy" in " ".join(html.split())


def test_csv_formula_guard_and_undefined_values():
    report = example()
    report["by_code"][0]["code_label"] = "  =HYPERLINK(unsafe)"
    exported = benchmark_csv(report)
    assert "'  =HYPERLINK(unsafe)" in exported
    assert "None" not in exported and "null" not in exported


def test_display_revision_preserves_existing_scientific_report(tmp_path, monkeypatch):
    from qualframe import benchmark_reporting

    report = example()
    original = write_benchmark_bundle(report, tmp_path)
    first_bytes = original.read_bytes()
    monkeypatch.setattr(benchmark_reporting, "BUNDLE_FORMAT_VERSION", "test-display-revision")
    revised = write_benchmark_bundle(report, tmp_path)
    assert revised.parent != original.parent and original.read_bytes() == first_bytes
    assert (original.parent / "report.json").read_bytes() == (
        revised.parent / "report.json"
    ).read_bytes()


def test_casefold_sensitivity_is_visible_per_side_and_does_not_mutate_report():
    from qualframe.reviewed_analysis import snapshot_identity

    report = example()
    assert "Quotation anchoring sensitivity" not in render_benchmark_html(report)
    report["inputs"]["left"]["benchmark_provenance"] = dict(
        quote_anchoring_policy="unique_casefold_quote_sensitivity_v1",
        code_label_policy="qualified_delimiters_v2",
        quote_anchoring_sensitivity=dict(
            strict_counts=dict(included=5), sensitivity_counts=dict(included=7)
        ),
    )
    identity = snapshot_identity(report)
    html = render_benchmark_html(report)
    assert "Quotation anchoring sensitivity" in html
    assert "unique_casefold_quote_sensitivity_v1" in html
    assert "qualified_delimiters_v2" in html
    assert "5 under strict anchoring; 7 under sensitivity" in html
    assert "Right: Strict quotation anchoring" in html
    assert html.index("Quotation anchoring sensitivity") < html.index('<div class="cards">')
    assert "separate strict report" in html
    assert snapshot_identity(report) == identity
    report["inputs"]["left"]["benchmark_provenance"]["quote_anchoring_policy"] = (
        "<script>bad</script>"
    )
    assert "<script>bad" not in render_benchmark_html(report)
