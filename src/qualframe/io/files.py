from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_for_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
