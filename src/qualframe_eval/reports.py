"""Report builders for manuscript-ready tables and summaries."""

from __future__ import annotations

from pathlib import Path


def ensure_output_dir(path: str | Path) -> Path:
    """Create output directory (and parents) if it does not exist."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
