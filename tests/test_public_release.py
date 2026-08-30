from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


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
