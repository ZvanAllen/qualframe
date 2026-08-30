from __future__ import annotations

import json
from pathlib import Path

from qualframe.config import load_disagreement_spec
from qualframe.models import StageArtifact
from qualframe.qa.disagreement import detect_disagreements, write_disagreement_records


REPO_ROOT = Path(__file__).resolve().parents[1]


def _artifact(explanation: str, *, include_row: bool = True) -> StageArtifact:
    rows = (
        [
            {
                "CFIR Domain": "Implementation Process",
                "CFIR Construct": "H. Reflecting and Evaluating",
                "Quote": "Synthetic quote",
                "Explanation": explanation,
            }
        ]
        if include_row
        else []
    )
    return StageArtifact(
        run_id="comparison-run",
        stage_id="cross_network_synthesis",
        input_path="synthetic",
        input_sha256="a" * 64,
        prompt_ref="cross_network_synthesis",
        prompt_sha256="b" * 64,
        response_text="synthetic",
        model="cached",
        provider="cached_demo",
        timestamp_utc="2026-08-02T00:00:00+00:00",
        parsed_output={"Implementation Process": rows},
    )


def test_detect_disagreement_preserves_comparison_provenance(tmp_path: Path) -> None:
    spec = load_disagreement_spec(REPO_ROOT / "config/disagreement/cfir_default.yaml")
    records = detect_disagreements(
        run_id="comparison-run",
        left=_artifact("First interpretation"),
        right=_artifact("Second interpretation"),
        left_label="left_artifact.json",
        right_label="right_artifact.json",
        spec=spec,
    )

    assert len(records) == 1
    record = records[0]
    assert record.field == "Explanation"
    assert record.status == "pending"
    assert record.left_prompt_sha256 == "b" * 64
    assert record.identity["CFIR Construct"] == "H. Reflecting and Evaluating"

    written = write_disagreement_records(records, tmp_path)
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["kind"] == "disagreement"
    assert payload["status"] == "pending"


def test_missing_row_is_a_disagreement() -> None:
    spec = load_disagreement_spec(REPO_ROOT / "config/disagreement/cfir_default.yaml")
    records = detect_disagreements(
        run_id="comparison-run",
        left=_artifact("Present"),
        right=_artifact("", include_row=False),
        left_label="left.json",
        right_label="right.json",
        spec=spec,
    )
    assert [record.field for record in records] == ["__row_presence__"]
