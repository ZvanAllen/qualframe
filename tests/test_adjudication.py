from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualframe.adjudication import (
    append_adjudication_action,
    latest_adjudication_by_item,
    load_adjudication_actions,
)
from qualframe.io.files import sha256_for_file


def test_adjudication_is_append_only_and_edits_create_derived_artifacts(tmp_path: Path) -> None:
    review_dir = tmp_path / "review_queue" / "run-1"
    artifact_root = tmp_path / "artifacts" / "run-1"
    review_dir.mkdir(parents=True)
    item = review_dir / "qa_item.json"
    item.write_text(
        json.dumps({"rule_id": "one_network_one_valence", "row_data": {"Quote": "synthetic"}}),
        encoding="utf-8",
    )
    original_sha = sha256_for_file(item)

    approved = append_adjudication_action(
        review_dir=review_dir,
        artifact_root=artifact_root,
        run_id="run-1",
        item_path=item,
        decision="approve",
        reviewer="reviewer-1",
        rationale="The synthetic item is acceptable for this test.",
    )
    edited = append_adjudication_action(
        review_dir=review_dir,
        artifact_root=artifact_root,
        run_id="run-1",
        item_path=item,
        decision="edit",
        reviewer="reviewer-2",
        rationale="Resolve the deliberately seeded valence conflict.",
        edited_row={"Facilitator Networks": "Synthetic Network Alpha", "Barrier Networks": ""},
    )

    assert sha256_for_file(item) == original_sha
    assert approved.derived_artifact_path is None
    assert edited.derived_artifact_path is not None
    derived_path = artifact_root / edited.derived_artifact_path
    derived = json.loads(derived_path.read_text(encoding="utf-8"))
    assert derived["source_review_item_sha256"] == original_sha
    assert derived["edited_row"]["Barrier Networks"] == ""
    assert len(load_adjudication_actions(review_dir)) == 2
    assert latest_adjudication_by_item(review_dir)["qa_item.json"].decision == "edit"


def test_edit_requires_edited_row(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    item = review_dir / "item.json"
    review_dir.mkdir()
    item.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="requires"):
        append_adjudication_action(
            review_dir=review_dir,
            artifact_root=tmp_path / "artifacts",
            run_id="run-1",
            item_path=item,
            decision="edit",
            reviewer="reviewer",
            rationale="Needs a row.",
        )
