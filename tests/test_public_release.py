from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import hashlib
import json
import zipfile

import pytest


spec = spec_from_file_location("public_packager", Path(__file__).resolve().parents[1] / "scripts/package_public_release.py")
packager = module_from_spec(spec)
spec.loader.exec_module(packager)


def test_selection_excludes_private_and_generated_directories(tmp_path):
    for name in ("README.md", ".env", ".env.example", "data/raw/person.txt", "studies/private/project.yaml",
                 "artifacts/response.json", "demo/presentation/index.html", "src/qualframe.egg-info/PKG-INFO",
                 "src/qualframe/example.py", "demo/fixtures/transcripts/synthetic.txt"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    selected = {path.relative_to(tmp_path).as_posix() for path in packager.public_files(tmp_path)}
    assert selected == {"README.md", ".env.example", "src/qualframe/example.py", "demo/fixtures/transcripts/synthetic.txt"}


def test_secret_screen_reports_path_not_secret(tmp_path):
    path = tmp_path / "README.md"
    token = "sk-" + "a" * 32
    path.write_text(token, encoding="utf-8")
    findings = packager.audit(tmp_path, [path])
    assert findings == ["provider_token: README.md"]
    assert token not in str(findings)


def test_examples_must_have_blank_settings(tmp_path):
    path = tmp_path / ".env.example"
    path.write_text("EXAMPLE=not-blank", encoding="utf-8")
    assert packager.audit(tmp_path, [path]) == ["Nonblank setting in .env.example"]


def test_broken_documentation_link_fails_audit(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("[missing](docs/missing.md)", encoding="utf-8")
    assert packager.audit(tmp_path, [path])


def test_link_to_existing_but_excluded_private_file_fails(tmp_path):
    private = tmp_path / "studies/private/results.json"
    private.parent.mkdir(parents=True)
    private.write_text("{}", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("[results](studies/private/results.json)", encoding="utf-8")
    assert packager.audit(tmp_path, [readme]) == ["Broken or excluded local Markdown link: README.md"]


@pytest.mark.parametrize("separator", ["/", "\\", "\\\\"])
def test_personal_paths_are_detected_without_echoing_them(tmp_path, separator):
    private_path = separator.join(["C:", "Users", "private-person", "study"])
    path = tmp_path / "README.md"
    path.write_text(private_path, encoding="utf-8")
    findings = packager.audit(tmp_path, [path])
    assert findings == ["personal_path: README.md"]
    assert "private-person" not in str(findings)


def test_root_file_links_are_rejected_before_reading(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text("not for distribution", encoding="utf-8")
    try:
        (tmp_path / "README.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable on this host.")
    with pytest.raises(ValueError, match="Linked or escaped"):
        packager.public_files(tmp_path)


def test_private_file_and_hash_references_are_blocked(tmp_path):
    payload = b"private synthetic fixture for this test"
    fingerprint = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "README.md"
    path.write_bytes(payload)
    assert packager.audit(tmp_path, [path], forbidden_hashes={fingerprint}) == ["private_file_fingerprint: README.md"]
    path.write_text(fingerprint, encoding="utf-8")
    assert packager.audit(tmp_path, [path], forbidden_hashes={fingerprint}) == ["private_hash_reference: README.md"]


def _archive_fixture(tmp_path, entries=None):
    archive = tmp_path / "candidate.zip"
    entries = entries or {"README.md": b"Public example"}
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, payload in entries.items():
            zipped.writestr("qualframe/" + name, payload)
    inventory = {"file_count": len(entries), "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                 "files": [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                           for name, payload in entries.items()]}
    manifest = archive.with_suffix(".manifest.json")
    manifest.write_text(json.dumps(inventory), encoding="utf-8")
    return archive, manifest


def test_archive_verifies_exact_inventory(tmp_path):
    archive, manifest = _archive_fixture(tmp_path)
    assert packager.verify_archive(archive, manifest)["file_count"] == 1


def test_archive_modification_is_rejected(tmp_path):
    archive, manifest = _archive_fixture(tmp_path)
    with zipfile.ZipFile(archive, "a") as zipped:
        zipped.writestr("qualframe/extra.txt", "unreviewed")
    with pytest.raises(ValueError, match="checksum"):
        packager.verify_archive(archive, manifest)


@pytest.mark.parametrize("entries", [{"../escape.txt": b"no"}, {"README.md": b"one", "readme.md": b"two"}])
def test_archive_rejects_unsafe_and_case_colliding_members(tmp_path, entries):
    archive, manifest = _archive_fixture(tmp_path, entries)
    with pytest.raises(ValueError, match="Unsafe|case-colliding"):
        packager.verify_archive(archive, manifest)


def test_release_trial_does_not_inherit_credentials_or_user_configuration(tmp_path, monkeypatch):
    helper_spec = spec_from_file_location("release_trial", Path(__file__).resolve().parents[1] / "scripts/release_preflight.py")
    helper = module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    monkeypatch.setattr(helper.os, "environ", {"PATH": "safe-path", "SYSTEMROOT": "system-root",
                                               "OPENAI_API_KEY": "synthetic-not-a-key",
                                               "HTTPS_PROXY": "not-forwarded", "PYTHONPATH": "not-forwarded",
                                               "PIP_INDEX_URL": "not-forwarded", "HOME": "not-forwarded"})
    child = helper.clean_environment(tmp_path)
    assert child["PATH"] == "safe-path"
    assert child["SYSTEMROOT"] == "system-root"
    assert child["PIP_NO_INDEX"] == "1"
    assert child["PIP_CONFIG_FILE"] == helper.os.devnull
    assert child["HOME"] == str(tmp_path / "local-home")
    assert not {"OPENAI_API_KEY", "HTTPS_PROXY", "PYTHONPATH", "PIP_INDEX_URL"}.intersection(child)


def test_release_contains_mit_license_and_citation():
    import tomllib
    import yaml

    root = Path(__file__).resolve().parents[1]
    selected = {path.relative_to(root).as_posix() for path in packager.public_files(root)}
    assert {"LICENSE", "CITATION.cff"} <= selected
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "Copyright (c) 2026 Zack van Allen" in license_text
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["license"]["file"] == "LICENSE"
    citation = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["cff-version"] == "1.2.0"
    assert citation["license"] == "MIT"
    assert citation["version"] == metadata["project"]["version"]
    assert citation["authors"] == [{"family-names": "van Allen", "given-names": "Zack"}]
    assert citation["repository-code"] == "https://github.com/ZvanAllen/qualframe"
    assert "not an additional condition" in citation["message"]
