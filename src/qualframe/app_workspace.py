"""Where a researcher's studies live, kept apart from the application code.

The application ships method templates, prompts, and demo material inside its
own checkout. A *workspace* is the folder that holds a researcher's studies
(``<workspace>/studies/<study-id>/project.yaml``). Studies resolve shared
templates relative to the workspace, so the first launch copies the bundled
templates into it. Existing workspace files are never overwritten: prompt and
configuration files are versioned assets, and a study's recorded hashes must
keep matching the files it used.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]

# Folders a study may reference by workspace-relative path.
_RESOURCE_DIRS = ("config", "prompts", "demo/fixtures")
_SETTINGS_FILE = "qualframe_settings.json"


def default_workspace() -> Path:
    """Return the researcher's workspace folder (``QUALFRAME_HOME`` or ``~/QualFrame``).

    The default sits in the home folder rather than Documents so that it is not
    swept into a cloud-synced folder by default; research data stays local unless
    the researcher chooses otherwise.
    """
    configured = os.getenv("QUALFRAME_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / "QualFrame"


@dataclass(frozen=True)
class WorkspaceSync:
    root: Path
    copied: int
    is_app_checkout: bool


def ensure_workspace(root: Path, *, app_root: Path = APP_ROOT) -> WorkspaceSync:
    """Create the workspace and add any bundled templates it does not have yet."""
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "studies").mkdir(exist_ok=True)
    if root == app_root.resolve():
        return WorkspaceSync(root=root, copied=0, is_app_checkout=True)
    copied = 0
    for relative in _RESOURCE_DIRS:
        source_root = app_root / relative
        if not source_root.is_dir():
            continue
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            target = root / source.relative_to(app_root)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(
            "This folder holds your QualFrame studies.\n\n"
            "studies/   one folder per study: imported sources, codebooks, runs, review decisions and exports\n"
            "config/    method templates copied from the application (safe to leave alone)\n"
            "prompts/   versioned prompt files copied from the application\n\n"
            "Back up this folder like any other research data. Keep identifiable data out of\n"
            "cloud-synced locations unless your ethics approval allows it.\n",
            encoding="utf-8",
        )
    return WorkspaceSync(root=root, copied=copied, is_app_checkout=False)


def list_study_manifests(root: Path) -> list[Path]:
    studies = root / "studies"
    if not studies.is_dir():
        return []
    manifests = [path for path in studies.glob("*/project.yaml") if path.is_file()]
    return sorted(manifests, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def read_settings(root: Path) -> dict:
    path = root / _SETTINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(root: Path, **updates: str) -> dict:
    settings = read_settings(root)
    settings.update({key: value for key, value in updates.items() if value is not None})
    path = root / _SETTINGS_FILE
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temporary.replace(path)
    return settings


PLACEHOLDER_NAME = "Unnamed researcher"


def researcher_name(root: Path) -> str:
    name = str(read_settings(root).get("researcher_name", "")).strip()
    # Earlier versions could save the placeholder as if it were a name; treat it as unset.
    return "" if name == PLACEHOLDER_NAME else name
