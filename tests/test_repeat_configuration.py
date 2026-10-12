from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qualframe.configuration_lock import _embedded_asset
from qualframe.models import ProviderConfig
from qualframe.repeat_configuration import automatic_stability_groups, locked_run_configuration


def _save(root, *, provider=None, assets=None):
    root.mkdir(parents=True, exist_ok=True)
    provider = provider or dict(name="openai", model="test-model", temperature=0, max_tokens=800,
                               reasoning_effort="low", anthropic_effort=None, api_mode="responses", base_url=None)
    assets = assets or [dict(kind=kind, id=key, sha256=key + "-hash", path=f"studies/{root.parent.name}/{key}")
                        for kind, key in [("provider", "openai"), ("framework", "framework"),
                        ("pipeline", "pipeline"), ("prompt_set", "prompts"), ("prompt", "first"),
                        ("prompt", "last"), ("method", "method"), ("codebook", "codebook"),
                        ("project", root.parent.name), ("cost_policy", "cost"), ("pricing_snapshot", "price")]]
    (root / "run_settings.json").write_text(json.dumps(dict(provider=provider, method_id="method")))
    (root / "analysis_configuration_lock.json").write_text(json.dumps(dict(assets=assets)))
    return provider, assets


@pytest.mark.parametrize("setting,value", [("name", "another"), ("model", "new-model"), ("temperature", .7),
    ("max_tokens", 1600), ("reasoning_effort", "high"), ("anthropic_effort", "high"),
    ("api_mode", "chat_completions"), ("base_url", "http://localhost:11434/v1")])
def test_provider_setting_changes_split_repeat_groups(tmp_path, setting, value):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    provider, _ = _save(left)
    _save(right, provider={**provider, setting: value})
    groups, skipped = automatic_stability_groups([("one:run", left), ("two:run", right)])
    assert groups == [] and skipped == []


@pytest.mark.parametrize("kind,asset_id", [("prompt", "first"), ("method", "method"), ("codebook", "codebook")])
def test_every_prompt_and_method_and_codebook_hash_defines_group(tmp_path, kind, asset_id):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    _, assets = _save(left)
    changed = deepcopy(assets)
    next(a for a in changed if a["kind"] == kind and a["id"] == asset_id)["sha256"] = "changed"
    _save(right, assets=changed)
    assert automatic_stability_groups([("one:run", left), ("two:run", right)])[0] == []


def test_cross_study_paths_project_and_spending_do_not_split_groups(tmp_path):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    _, assets = _save(left)
    other = deepcopy(assets)
    for asset in other:
        asset["path"] = asset["path"].replace("one", "two")
        if asset["kind"] in {"project", "cost_policy", "pricing_snapshot"}:
            asset.update(id="different", sha256="different")
    _save(right, assets=list(reversed(other)))
    groups, skipped = automatic_stability_groups([("one:run", left), ("two:run", right)])
    assert len(groups) == 1 and groups[0]["members"] == ["one:run", "two:run"] and not skipped
    assert len([a for a in groups[0]["assets"] if a["kind"] == "prompt"]) == 2


def test_missing_or_incomplete_records_are_not_automatically_grouped(tmp_path):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    _, assets = _save(left)
    _save(right, assets=[a for a in assets if a["kind"] != "codebook"])
    (left / "run_settings.json").write_text("not json")
    groups, skipped = automatic_stability_groups([("one:run", left), ("two:run", right)])
    assert not groups and len(skipped) == 2


def test_page_builder_groups_other_study_runs_and_records_group_settings(tmp_path, monkeypatch):
    import qualframe.qualbench_ui as ui
    local, other = tmp_path / "local/run", tmp_path / "other/run"
    _save(local); _save(other)
    app = SimpleNamespace(artifacts_dir=local.parent, repo_root=tmp_path, exports_dir=tmp_path / "out",
                          runner=SimpleNamespace(project=SimpleNamespace(project_id="study")))
    monkeypatch.setattr(ui, "_runs", lambda app: ["run"])
    monkeypatch.setattr(ui, "_references", lambda app: [])
    monkeypatch.setattr(ui, "_other_study_runs", lambda app: {"other:run": (other, "Other run")})
    monkeypatch.setattr(ui, "_run_label", lambda app, rid: "Local run")
    monkeypatch.setattr(ui, "run_coding_set", lambda repo, root: dict(set_id=root.name))
    captured = {}
    def build(sets, **kwargs):
        captured.update(kwargs)
        return dict(transcripts=[], coding_sets=[dict(set_id=s["set_id"], label=s["label"]) for s in sets])
    monkeypatch.setattr(ui, "build_qualbench", build)
    monkeypatch.setattr(ui, "write_qualbench", lambda report, folder: captured.update(report=report))
    ui.build_qualbench_form(app, dict(study_identity=["study"], run=["run", "other:run"]))
    assert captured["stability_groups"] == [["run", "other:run"]]
    assert captured["report"]["stability_configurations"][0]["provider"]["max_tokens"] == 800


def test_study_specific_credential_names_do_not_split_effective_provider_groups(tmp_path):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    raw_hashes = []
    for root, key_env in ((left, "QUALFRAME_ONE_OPENAI_KEY"), (right, "QUALFRAME_TWO_OPENAI_KEY")):
        provider = ProviderConfig(name="openai", model="same-model", api_key_env=key_env)
        _, assets = _save(root, provider=provider.model_dump(exclude={"api_key_env"}))
        locked_provider = _embedded_asset("provider", provider.name, provider).model_dump(mode="json")
        raw_hashes.append(locked_provider["sha256"])
        assets = [asset for asset in assets if asset["kind"] != "provider"] + [locked_provider]
        _save(root, provider=provider.model_dump(exclude={"api_key_env"}), assets=assets)
    assert raw_hashes[0] != raw_hashes[1]
    groups, skipped = automatic_stability_groups([("one:run", left), ("two:run", right)])
    assert len(groups) == 1 and groups[0]["members"] == ["one:run", "two:run"] and not skipped
    assert all(asset["kind"] != "provider" for asset in groups[0]["assets"])
    assert "api_key_env" not in groups[0]["provider"]
    assert groups[0]["provider"]["model"] == "same-model"


@pytest.mark.parametrize("missing", sorted(set(ProviderConfig.model_fields) - {"api_key_env"}))
def test_missing_persisted_provider_field_is_not_filled_with_a_default(tmp_path, missing):
    left, right = tmp_path / "one/run", tmp_path / "two/run"
    provider = ProviderConfig(name="openai", model="same-model").model_dump(exclude={"api_key_env"})
    del provider[missing]
    _save(left, provider=provider)
    _save(right, provider=provider)
    groups, skipped = automatic_stability_groups([("one:run", left), ("two:run", right)])
    assert groups == [] and len(skipped) == 2


@pytest.mark.parametrize("provider_asset", [None, {"kind": "provider", "id": "openai", "sha256": ""}])
def test_complete_saved_settings_still_require_a_valid_locked_provider_asset(tmp_path, provider_asset):
    root = tmp_path / "one/run"
    provider, assets = _save(root)
    assets = [asset for asset in assets if asset["kind"] != "provider"]
    if provider_asset is not None:
        assets.append(provider_asset)
    _save(root, provider=provider, assets=assets)
    assert locked_run_configuration(root)["eligible"] is False
