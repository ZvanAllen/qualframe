from pathlib import Path

import pytest
import yaml

from qualframe.config import load_project_manifest
from qualframe.configuration_lock import create_configuration_lock
from qualframe.decision_style import DECIDE_EACH_CODE_PROMPT
from test_decision_style import make_study


@pytest.mark.parametrize("other_enabled", [False, True])
def test_shared_prompt_ref_locks_every_executed_prompt(tmp_path: Path, other_enabled: bool) -> None:
    project_path, _ = make_study(tmp_path, "decide_each_code")
    project = load_project_manifest(project_path)
    pipeline_path = tmp_path / project.pipeline
    pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
    coding = pipeline["stages"][0]
    pipeline["stages"].insert(0, dict(
        coding, id="non_coding_with_same_ref", enabled=other_enabled, input_source="previous_stage",
    ))
    pipeline_path.write_text(yaml.safe_dump(pipeline), encoding="utf-8")

    before = create_configuration_lock(project_path)
    paths = {asset.path for asset in before.assets if asset.kind == "prompt"}
    expected = {DECIDE_EACH_CODE_PROMPT}
    if other_enabled:
        expected.add("prompts/directed/v3/directed_coding.md")
    assert paths == expected

    for prompt_path in sorted(expected):
        old = create_configuration_lock(project_path)
        prompt = tmp_path / prompt_path
        prompt.write_text(prompt.read_text(encoding="utf-8") + "\nSynthetic changed instruction.\n", encoding="utf-8")
        revised = create_configuration_lock(project_path)
        assert revised.fingerprint_sha256 != old.fingerprint_sha256
