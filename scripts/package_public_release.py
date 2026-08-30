"""Audit an explicit public file selection and optionally produce a clean ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "AGENTS.md", "CONTRIBUTING.md", "LICENSE", "LICENSE.md", "CITATION.cff",
              ".gitignore", ".env.example", "pyproject.toml", "ruff.toml", "Makefile"}
DIRECTORIES = ("src", "config", "prompts", "tests", "examples", "scripts", "docs", ".github",
               "demo/fixtures", "demo/cached_responses", "demo/config", "demo/project")
SUFFIXES = {".py", ".css", ".md", ".yaml", ".yml", ".json", ".txt", ".png"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "provider_token": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,})\b"),
    "personal_path": re.compile(r"[A-Z]:\\Users\\[^\s\\]+|/" + r"Users/[^/\s]+/", re.I),
    "email_address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
}


def public_files(root: Path) -> list[Path]:
    paths = [root / name for name in ROOT_FILES if (root / name).is_file()]
    if (root / "demo/README.md").is_file():
        paths.append(root / "demo/README.md")
    for directory in DIRECTORIES:
        for path in (root / directory).rglob("*"):
            if any(part == "__pycache__" or part.endswith(".egg-info") for part in path.parts):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Linked or escaped release path: {path.relative_to(root)}")
            if path.is_file():
                if path.suffix not in SUFFIXES:
                    raise ValueError(f"Unapproved file type: {path.relative_to(root)}")
                paths.append(path)
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def audit(root: Path, paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".png":
            if not relative.startswith("docs/images/"):
                findings.append(f"Image outside reviewed screenshots: {relative}")
            continue  # Screenshots require separate visual review.
        text = path.read_text(encoding="utf-8")
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
                destination = (path.parent / target.split("#")[0]).resolve()
                if not destination.is_relative_to(root.resolve()) or not destination.exists():
                    findings.append(f"Broken local Markdown link: {relative} -> {target}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Audit without writing an archive.")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/release/qualframe-public.zip")
    args = parser.parse_args()
    paths = public_files(ROOT)
    findings = audit(ROOT, paths)
    if findings:
        print(json.dumps({"status": "blocked", "findings": findings}, indent=2))
        return 1
    manifest = {
        "status": "automated_screen_passed_manual_review_also_required",
        "file_count": len(paths),
        "excluded": ["research data", "generated runs", "private reference workbooks", "credentials", "git history"],
        "files": [{"path": path.relative_to(ROOT).as_posix(),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "bytes": path.stat().st_size} for path in paths],
    }
    if not args.dry_run:
        output = args.output.resolve()
        receipt = output.with_suffix(".manifest.json")
        if output.exists() or receipt.exists():
            raise FileExistsError("Archive or receipt already exists; choose a new output path.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, "qualframe/" + path.relative_to(ROOT).as_posix())
        manifest["archive_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Archive: {output}")
        print(f"Inventory: {receipt}")
    print(f"Automated screen passed: {len(paths)} selected public files. No generated study/run folders included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
