"""Identify the executing source checkout without inspecting study data.

Installed distributions and source archives have no Git provenance. These fields
describe a point in time; an existing run must keep the values recorded at start.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import TypedDict


class CodeProvenance(TypedDict):
    git_commit: str | None
    git_dirty: bool | None


def get_code_provenance() -> CodeProvenance:
    """Return the executing package's commit and working-tree state, if known.

    The package location, not the current directory or study root, selects the
    checkout. A tracked package initializer distinguishes source checkouts from
    a distribution installed in a virtual environment inside another repository.
    Git only reads metadata; it cannot refresh the index or invoke a filesystem
    monitor. Missing Git, an unreadable checkout, or an unborn HEAD is harmless.
    """
    unknown: CodeProvenance = {"git_commit": None, "git_dirty": None}
    try:
        package = Path(__file__).resolve().parent
        checkout = next((parent for parent in package.parents if (parent / ".git").exists()), None)
        if checkout is None:
            return unknown
        initializer = (package / "__init__.py").relative_to(checkout).as_posix()
        # Repository-selection variables must not redirect Git to an unrelated
        # checkout. No environment values are included in the returned record.
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(checkout), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=True, timeout=5, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()

        git("ls-files", "--error-unmatch", "--", initializer)
        commit = git("rev-parse", "--verify", "HEAD")
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit):
            return unknown
        dirty = bool(git("status", "--porcelain=v1", "--untracked-files=normal"))
        return {"git_commit": commit, "git_dirty": dirty}
    except (OSError, ValueError, subprocess.SubprocessError):
        return unknown
