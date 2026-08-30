"""Normalization helpers for workbook comparisons.

Pending implementation:
- canonical CFIR construct label mapping
- placeholder row removal with logging
- stable row ID generation
- quote text normalization for duplicate detection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizationLog:
    removed_rows: list[dict[str, Any]] = field(default_factory=list)
    relabeled_constructs: list[dict[str, Any]] = field(default_factory=list)


def normalize_construct_label(label: str) -> str:
    """Return canonical CFIR construct label. Not yet implemented."""
    raise NotImplementedError


def normalize_quote_text(text: str) -> str:
    """Return normalized quote text for duplicate detection. Not yet implemented."""
    raise NotImplementedError
