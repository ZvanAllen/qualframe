"""Replay recorded coding responses for the offline demo study.

A recording is a folder of responses captured from a real model run over the bundled
demo transcripts (``scripts/record_demo.py``) or written as clearly labelled
illustrations. Responses are looked up by the SHA-256 of the transcript text and the
codebook partition named in the request, so a recording can only answer for the exact
transcript it was made from. The provider never opens a network connection.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens

_APP_ROOT = Path(__file__).resolve().parents[3]
_PARTITION = re.compile(r"Codebook partition for this request: (.+?)\.?\s*$", re.MULTILINE)


def transcript_from_prompt(user_prompt: str) -> str | None:
    marker = "Transcript:\n\n"
    if marker not in user_prompt:
        return None
    return user_prompt.split(marker, 1)[1].split("\n\n---\n\n", 1)[0]


def recording_key(user_prompt: str) -> str | None:
    transcript = transcript_from_prompt(user_prompt)
    if transcript is None:
        return None
    match = _PARTITION.search(user_prompt)
    partition = match.group(1).strip() if match else "full_codebook"
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
    safe_partition = re.sub(r"[^A-Za-z0-9_-]+", "-", partition).strip("-") or "full"
    return f"{digest}__{safe_partition}"


def _starts_with_instructions(user_prompt: str, sha256: str) -> bool:
    """True if the request begins with the instructions the recording was made with."""
    separator = "\n\n---\n\n"
    index = user_prompt.find(separator)
    while index >= 0:
        if hashlib.sha256(user_prompt[:index].encode("utf-8")).hexdigest() == sha256:
            return True
        index = user_prompt.find(separator, index + 1)
    return False


def recordings_root() -> Path:
    return _APP_ROOT / "demo" / "recordings"


def load_recording_info(recording: str, root: Path | None = None) -> dict:
    folder = (root or recordings_root()) / recording
    info_path = folder / "recording.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Recording '{recording}' is not installed.")
    return json.loads(info_path.read_text(encoding="utf-8"))


class RecordedProvider(LLMProvider):
    name = "recorded"

    def __init__(self, recording: str, root: Path | None = None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", recording or ""):
            raise ValueError("Recorded provider needs a valid recording name.")
        self.recording = recording
        self.folder = (root or recordings_root()) / recording
        self.info = load_recording_info(recording, root)
        self.model = recording

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        expected = self.info.get("prompt_sha256")
        if expected and not _starts_with_instructions(user_prompt, expected):
            raise ValueError(
                "These recorded responses were made with QualFrame's standard coding instructions, "
                "and this study now uses different ones. Choose a model to code with the edited instructions."
            )
        key = recording_key(user_prompt)
        path = self.folder / "responses" / f"{key}.txt" if key else None
        if path is None or not path.exists():
            raise FileNotFoundError(
                "This recording has no response for this transcript. Recordings only "
                "replay the demo transcripts they were made from."
            )
        text = path.read_text(encoding="utf-8")
        return LLMResponse(
            text=text,
            model=f"recorded:{self.recording}",
            provider=self.name,
            usage=LLMUsage(
                input_tokens=estimate_tokens(system_prompt + user_prompt),
                output_tokens=estimate_tokens(text),
            ),
        )
