from pathlib import Path

import pytest
import yaml
from test_reviewed_analysis import decide
from test_synthesis_plan import reviewed

from qualframe.dashboard import DashboardApp
from qualframe.metadata_synthesis import metadata_group_matrix, read_metadata_catalog
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.reviewed_analysis import freeze_reviewed_snapshot, load_snapshot
from qualframe.study_setup import StudyWorkspace
from qualframe.synthesis_execution import current_plan, execute_synthesis
from qualframe.synthesis_plan import (
    build_synthesis_plan,
    validate_synthesis_response,
    write_synthesis_plan,
)
from qualframe.synthesis_review import read_job
from qualframe.synthesis_ui import render_synthesis_preparation


def import_metadata(project, content):
    return StudyWorkspace(project.parents[2]).import_metadata(
        project_manifest_path=project,
        filename="metadata.csv",
        content=content.encode("utf-8"),
        actor="Synthetic QA",
        rationale="Check grouping behavior",
    )


def source_names(snapshot):
    return [Path(source).name for source in snapshot["payload"]["source_paths"]]


def metadata_fixture(tmp_path):
    project, run_id, root, review, records, path = reviewed(tmp_path)
    snapshot = load_snapshot(path)
    names = source_names(snapshot)
    import_metadata(project, f"source_filename,site,time\n{names[0]},East,T1\n{names[1]},West,T1\n")
    return project, run_id, root, review, records, path


def build(project, root, review, path, **kwargs):
    return build_synthesis_plan(
        project.parents[2],
        root,
        review,
        path,
        "metadata",
        project_path=project,
        metadata_field="site",
        **kwargs,
    )


def test_metadata_plan_freezes_source_links_subsets_and_matrix(tmp_path):
    project, _, root, review, _, path = metadata_fixture(tmp_path)
    plan = build(project, root, review, path)
    assert plan["kind"] == "qualframe_synthesis_plan_v2"
    assert len(plan["calls"]) == 2
    grouping = plan["metadata_grouping"]
    assert grouping["catalog"]["metadata_sha256"]
    assert "source_filename,site,time" in grouping["catalog"]["metadata_content"]
    assert grouping["selected_values"] == ["East", "West"]
    assert all("metadata_content" not in call["input"] for call in plan["calls"])
    cells = metadata_group_matrix(plan)
    assert len(cells) == 2 * len(plan["codebook"]["codes"])
    assert sum(cell["distinct_spans"] for cell in cells) == 4
    subset = build(project, root, review, path, metadata_values=["East"])
    assert len(subset["included_sources"]) == len(subset["excluded_sources"]) == 1
    assert (
        subset["metadata_grouping"]["excluded_sources"][0]["reason"] == "unselected_metadata_value"
    )
    selected = subset["included_sources"]
    frozen_subset = freeze_reviewed_snapshot(
        project.parents[2], root, review, "QA", selected_sources=selected
    )
    selection = build(project, root, review, frozen_subset)
    assert selection["included_sources"] == selected
    assert len(selection["excluded_sources"]) == 1
    assert selection["metadata_grouping"]["selected_values"] == ["East"]
    first, second = plan["calls"]
    item = first["input"]["evidence"][0]
    with pytest.raises(ValueError, match="outside its reviewed"):
        validate_synthesis_response(
            plan,
            first["group_id"],
            {
                "summaries": [
                    {
                        "code_id": item["code_id"],
                        "statements": [
                            {
                                "text": "Wrong group",
                                "evidence_ids": [second["input"]["evidence"][0]["evidence_id"]],
                            }
                        ],
                    }
                ]
            },
        )
    with pytest.raises(ValueError, match="absent"):
        build(project, root, review, frozen_subset, metadata_values=["West"])
    with pytest.raises(ValueError, match="Select at least one"):
        build(project, root, review, path, metadata_values=[""])


def test_metadata_missing_rows_values_and_literal_missing_label(tmp_path):
    project, _, root, review, _, path = metadata_fixture(tmp_path)
    names = source_names(load_snapshot(path))
    import_metadata(project, f"source_filename,site\n{names[0]},[missing value]\n")
    with pytest.raises(ValueError, match="1 reviewed source"):
        build(project, root, review, path)
    excluded = build(project, root, review, path, missing_policy="exclude")
    assert len(excluded["excluded_sources"]) == 1
    separate = build(project, root, review, path, missing_policy="separate")
    groups = separate["metadata_grouping"]["groups"]
    assert len(groups) == 2
    assert len({g["group_id"] for g in groups}) == len({g["label"] for g in groups}) == 2
    assert {g["definition"]["kind"] for g in groups} == {"value", "missing"}
    assert (
        len(
            build(project, root, review, path, metadata_values=[], missing_policy="separate")[
                "calls"
            ]
        )
        == 1
    )
    import_metadata(project, f"source_filename,site\n{names[0]},East\n{names[1]},   \n")
    assert (
        len(build(project, root, review, path, missing_policy="exclude")["excluded_sources"]) == 1
    )


def test_metadata_values_preserve_case_and_same_values_merge_sources(tmp_path):
    project, _, root, review, _, path = metadata_fixture(tmp_path)
    names = source_names(load_snapshot(path))
    import_metadata(project, f"source_filename,site\n{names[0]}, East \n{names[1]},East\n")
    plan = build(project, root, review, path)
    assert len(plan["calls"]) == 1 and len(plan["calls"][0]["input"]["source_paths"]) == 2
    assert len(plan["calls"][0]["input"]["evidence"]) == 4
    import_metadata(project, f"source_filename,site\n{names[0]},East\n{names[1]},east\n")
    assert len(build(project, root, review, path)["calls"]) == 2


def test_metadata_changes_invalidate_new_plan_but_leave_original_scopes_usable(tmp_path):
    project, _, root, review, _, path = metadata_fixture(tmp_path)
    old_path = write_synthesis_plan(project.parents[2], root, review, path, "selected_cohort")
    old_bytes = old_path.read_bytes()
    meta_path = write_synthesis_plan(
        project.parents[2],
        root,
        review,
        path,
        "metadata",
        project_path=project,
        metadata_field="site",
    )
    identity = meta_path.stem[15:]
    runner = ProjectRunner(project)
    current_plan(runner, root, identity)
    job = execute_synthesis(
        project,
        root,
        identity,
        fingerprint=runner.configuration_lock.fingerprint_sha256,
        actor="QA",
        rationale="Synthetic metadata workflow",
    )
    assert len(read_job(job)[2]) == 4
    assert current_plan(runner, root, old_path.stem[15:])["kind"] == "qualframe_synthesis_plan_v1"
    names = source_names(load_snapshot(path))
    import_metadata(project, f"source_filename,site\n{names[0]},Central\n{names[1]},West\n")
    with pytest.raises(ValueError):
        current_plan(ProjectRunner(project), root, identity)
    assert read_job(job)[1]["metadata_grouping"]["selected_values"] == ["East", "West"]
    current_plan(ProjectRunner(project), root, old_path.stem[15:])
    assert old_path.read_bytes() == old_bytes
    catalog = read_metadata_catalog(project, load_snapshot(path)["payload"]["source_paths"])
    (project.parents[2] / catalog["metadata_path"]).write_text(
        "Changed after import", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="changed after import"):
        build(project, root, review, path)


def test_metadata_empty_group_stays_visible_without_a_model_request(tmp_path):
    project, _, root, review, records, path = metadata_fixture(tmp_path)
    emptied = records[0].source_path
    for record in records:
        if record.source_path == emptied:
            decide(project, root, review, record, "reject")
    path = freeze_reviewed_snapshot(project.parents[2], root, review, "QA")
    plan = build(project, root, review, path)
    assert len(plan["metadata_grouping"]["groups"]) == 2 and len(plan["calls"]) == 1
    assert plan["sources_without_retained_evidence"] == [emptied.replace("\\", "/")]
    empty_cells = [
        cell
        for cell in metadata_group_matrix(plan)
        if emptied.replace("\\", "/") in cell["source_paths"]
    ]
    assert len(empty_cells) == len(plan["codebook"]["codes"])
    assert all(cell["distinct_spans"] == 0 for cell in empty_cells)


def test_metadata_safe_path_linking(tmp_path):
    project, _, root, review, _, path = metadata_fixture(tmp_path)
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["metadata_file"] = "../outside.csv"
    project.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="study boundary"):
        build(project, root, review, path)
    data["metadata_file"] = f"studies/{project.parent.name}/data/reference/metadata_v1.csv"
    data["source_manifest"] = "../outside.jsonl"
    project.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="study boundary"):
        build(project, root, review, path)


def test_metadata_ui_exposes_scope_selection_and_frozen_matrix(tmp_path):
    project, run_id, root, review, _, path = metadata_fixture(tmp_path)
    write_synthesis_plan(
        project.parents[2],
        root,
        review,
        path,
        "metadata",
        project_path=project,
        metadata_field="site",
    )
    app = DashboardApp(ProjectRunner(project))
    page = render_synthesis_preparation(app, root, load_snapshot(path), True)
    assert 'name="metadata_field" value="site"' in page
    assert 'name="metadata_value" value="West" checked' in page
    assert "Code-by-metadata-group matrix" in page
    assert "Missing values for site" in page
    assert "not participant frequencies" in page
    assert "source=" in page


def test_metadata_rejects_duplicate_columns_and_missing_import(tmp_path):
    project, _, root, review, _, path = reviewed(tmp_path)
    with pytest.raises(ValueError, match="Import a metadata CSV"):
        build(project, root, review, path)
    names = source_names(load_snapshot(path))
    import_metadata(project, f"source_filename,site,site\n{names[0]},East,West\n")
    with pytest.raises(ValueError, match="unique nonblank column"):
        build(project, root, review, path)


def test_metadata_normalizes_registered_paths_without_basename_fallback(tmp_path):
    import json

    project, _, root, review, _, path = metadata_fixture(tmp_path)
    snapshot = load_snapshot(path)
    manifest = project.parent / "source_import_manifest.jsonl"
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    for record in records:
        record["destination_path"] = record["destination_path"].replace("/", chr(92))
    manifest.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    catalog = read_metadata_catalog(
        project, [source.replace("/", chr(92)) for source in snapshot["payload"]["source_paths"]]
    )
    assert [row["source_path"] for row in catalog["sources"]] == sorted(
        snapshot["payload"]["source_paths"]
    )
    build(project, root, review, path)
    first = snapshot["payload"]["source_paths"][0]
    with pytest.raises(ValueError, match="no transcript import record"):
        read_metadata_catalog(project, [str(Path(first).parent / "other" / Path(first).name)])
