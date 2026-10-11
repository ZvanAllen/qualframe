"""Audit an explicit public file selection and optionally produce a clean ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "LICENSE.md", "CITATION.cff",
              ".gitignore", ".env.example", "pyproject.toml", "ruff.toml", "Makefile", "CLAUDE.md",
              "Start QualFrame.bat", "start-qualframe.command", "demo/README.md", "uv.lock", "CHANGELOG.md"}
DIRECTORIES = ("src", "config", "prompts", "tests", "examples", "scripts", "docs", ".github",
               "demo/fixtures", "demo/cached_responses", "demo/config", "demo/project",
               "demo/datasets", "demo/recordings")
SUFFIXES = {".py", ".css", ".js", ".md", ".yaml", ".yml", ".json", ".txt", ".png", ".woff2", ".xlsx", ".csv",
            ".bat", ".command", ".sh", ".ps1"}
BINARY_LOCATIONS = {".woff2": "src/qualframe/static/fonts/", ".xlsx": "demo/datasets/"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "provider_token": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,})\b"),
    "personal_path": re.compile(r"[A-Z]:(?:\\+|/)Users(?:\\+|/)[^\s\\/]+|/" + r"(?:Users|home)/[^/\s]+/", re.I),
    "email_address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
}


def validate_selected_path(root: Path, path: Path) -> None:
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Linked or escaped release path: {path.relative_to(root)}")


def public_files(root: Path) -> list[Path]:
    paths = [root / name for name in ROOT_FILES if (root / name).is_file()]
    if (root / "demo/README.md").is_file():
        paths.append(root / "demo/README.md")
    for directory in DIRECTORIES:
        validate_selected_path(root, root / directory)
        for path in (root / directory).rglob("*"):
            if any(part == "__pycache__" or part.endswith(".egg-info") for part in path.parts):
                continue
            validate_selected_path(root, path)
            if path.is_file():
                if path.suffix not in SUFFIXES:
                    raise ValueError(f"Unapproved file type: {path.relative_to(root)}")
                paths.append(path)
    for path in paths:
        validate_selected_path(root, path)
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def audit(root: Path, paths: list[Path], *, forbidden_hashes: set[str] | None = None,
          contents: dict[Path, bytes] | None = None) -> list[str]:
    findings: list[str] = []
    selected = {path.resolve() for path in paths}
    for path in paths:
        validate_selected_path(root, path)
        relative = path.relative_to(root).as_posix()
        payload = contents[path] if contents is not None else path.read_bytes()
        if forbidden_hashes and hashlib.sha256(payload).hexdigest() in forbidden_hashes:
            findings.append(f"private_file_fingerprint: {relative}")
        if path.suffix == ".png":
            if not relative.startswith("docs/images/"):
                findings.append(f"Image outside reviewed screenshots: {relative}")
            continue  # Screenshots require separate visual review.
        if path.suffix in BINARY_LOCATIONS:
            if not relative.startswith(BINARY_LOCATIONS[path.suffix]):
                findings.append(f"Binary file outside its approved folder: {relative}")
            continue  # Bundled fonts and the demo workbook are reviewed assets.
        text = payload.decode("utf-8")
        if forbidden_hashes and any(value in text.lower() for value in forbidden_hashes):
            findings.append(f"private_hash_reference: {relative}")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")  # Never echo the matched value.
        if path.name == ".env.example":
            for line in text.splitlines():
                if line.strip() and not line.lstrip().startswith("#") and line.partition("=")[2].strip():
                    findings.append("Nonblank setting in .env.example")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                destination = (path.parent / unquote(target.split("#")[0].split("?")[0].strip("<>"))).resolve()
                in_archive = destination in selected or (
                    destination.is_dir() and any(item.is_relative_to(destination) for item in selected)
                )
                if not destination.is_relative_to(root.resolve()) or not in_archive:
                    findings.append(f"Broken or excluded local Markdown link: {relative}")
    return findings


def verify_archive(archive_path: Path, manifest_path: Path) -> dict:
    """Verify the exact inventoried payload before an offline installation trial."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != manifest.get("archive_sha256"):
        raise ValueError("Archive checksum does not match its inventory.")
    expected: dict[str, dict] = {}
    for record in manifest["files"]:
        relative = record["path"]
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise ValueError("Unsafe inventory path.")
        member = "qualframe/" + relative
        if member.casefold() in {name.casefold() for name in expected}:
            raise ValueError("Duplicate or case-colliding inventory path.")
        expected[member] = record
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) != len(expected) or {item.filename for item in members} != set(expected):
            raise ValueError("Archive members differ from its inventory.")
        for item in members:
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive contains a symbolic link.")
            payload = archive.read(item)
            record = expected[item.filename]
            if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError("Archive member checksum differs from its inventory.")
    if manifest["file_count"] != len(expected):
        raise ValueError("Inventory file count differs from its entries.")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Audit without writing an archive.")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/release/qualframe-public.zip")
    parser.add_argument("--private-fingerprints", type=Path,
                        help="Optional local JSON array of private file/text SHA-256 values; never copied into the archive.")
    args = parser.parse_args()
    forbidden_hashes: set[str] = set()
    if args.private_fingerprints:
        values = json.loads(args.private_fingerprints.read_text(encoding="utf-8"))
        if not isinstance(values, list) or any(not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value) for value in values):
            raise ValueError("Private fingerprints must be a JSON array of SHA-256 strings.")
        forbidden_hashes = {value.lower() for value in values}
    paths = public_files(ROOT)
    contents = {path: path.read_bytes() for path in paths}
    findings = audit(ROOT, paths, forbidden_hashes=forbidden_hashes, contents=contents)
    if findings:
        print(json.dumps({"status": "blocked", "findings": findings}, indent=2))
        return 1
    manifest = {
        "status": "automated_screen_passed_manual_review_also_required",
        "file_count": len(paths),
        "private_fingerprints_checked": len(forbidden_hashes),
        "excluded": ["research data", "generated runs", "private reference workbooks", "credentials", "git history"],
        "files": [{"path": path.relative_to(ROOT).as_posix(),
                   "sha256": hashlib.sha256(contents[path]).hexdigest(),
                   "bytes": len(contents[path])} for path in paths],
    }
    if not args.dry_run:
        output = args.output.resolve()
        receipt = output.with_suffix(".manifest.json")
        if output.exists() or receipt.exists():
            raise FileExistsError("Archive or receipt already exists; choose a new output path.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.writestr("qualframe/" + path.relative_to(ROOT).as_posix(), contents[path])
        manifest["archive_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify_archive(output, receipt)
        print(f"Archive: {output}")
        print(f"Inventory: {receipt}")
    print(f"Automated screen passed: {len(paths)} selected public files. No generated study/run folders included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
