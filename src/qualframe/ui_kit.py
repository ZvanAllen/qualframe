"""Small presentation helpers shared by the workspace pages."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

e = html.escape


def plural(count: int, word: str, plural_word: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural_word or word + 's')}"


def notices(message: str = "", error: str = "") -> str:
    out = ""
    if message:
        out += f'<div class="message" role="status">{e(message)}</div>'
    if error:
        out += f'<div class="error" role="alert">{e(error)}</div>'
    return out


def friendly_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    return moment.strftime("%d %b %Y, %H:%M").lstrip("0")


def run_time_from_id(run_id: str) -> str:
    try:
        moment = datetime.strptime(run_id, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return ""
    return moment.strftime("%d %b %Y, %H:%M UTC").lstrip("0")


def identity_fields(name: str, *, note_label: str = "Add a note", note_placeholder: str = "") -> str:
    """Researcher identity for the audit trail: asked once, then carried silently."""
    who = (
        f'<input type="hidden" name="actor" value="{e(name)}"><input type="hidden" name="reviewer" value="{e(name)}">'
        if name else ""
    )
    note = (
        f'<details class="note-field"><summary>{e(note_label)}</summary>'
        f'<label class="visually-plain">Note<textarea name="rationale" rows="2" placeholder="{e(note_placeholder)}"></textarea></label></details>'
    )
    return who + note


def provider_display(provider: str | None, model: str | None) -> str:
    if not provider:
        return "Unknown model"
    if provider == "recorded":
        recording = (model or "").removeprefix("recorded:")
        try:
            from qualframe.providers.recorded_provider import load_recording_info

            return load_recording_info(recording).get("label", recording)
        except (OSError, ValueError):
            return recording or "Recorded responses"
    if provider == "mock":
        return "Offline demo model"
    names = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "openai_compatible": "Endpoint"}
    return f"{names.get(provider, provider)} {model or ''}".strip()


def run_model(artifact_root: Path) -> tuple[str | None, str | None]:
    """Provider and model recorded in the first artifact of a run."""
    manifest = artifact_root / "run_manifest.json"
    try:
        paths = json.loads(manifest.read_text(encoding="utf-8")).get("artifact_paths", [])
        for rel in paths:
            artifact = json.loads((artifact_root / rel).read_text(encoding="utf-8"))
            return artifact.get("provider"), artifact.get("model")
    except (OSError, ValueError):
        pass
    return None, None


def name_prompt(name: str, back: str) -> str:
    """One slim prompt for the researcher's name, shown until it is set."""
    if name:
        return ""
    return (
        '<form class="name-banner" method="post" action="/settings/name">'
        f'<input type="hidden" name="back" value="{e(back)}">'
        '<label>Your name <small>Recorded with your imports and coding decisions. You only need to enter it once.</small>'
        '<input name="researcher_name" required autocomplete="name"></label><button class="secondary">Save</button></form>'
    )
