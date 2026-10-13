"""Shared, dependency-free presentation for the local researcher workspace."""
from __future__ import annotations

import html
from dataclasses import dataclass

e = html.escape

_CLASSIFICATION_LABELS = {
    "synthetic": "Synthetic data",
    "published": "Published documents",
    "deidentified": "De-identified data",
    "sensitive": "Sensitive data",
}


@dataclass(frozen=True)
class Step:
    """One stage of the study sequence shown in the sidebar."""

    key: str
    label: str
    url: str
    detail: str = ""
    state: str = "todo"  # done | next | todo


def model_label(provider: str, model: str | None = None) -> tuple[str, str]:
    """Return (label, dot class) describing where coding requests go."""
    if provider == "mock":
        return "Offline demo model", "offline"
    if provider in {"cached_demo", "recorded"}:
        return "Recorded responses (offline)", "offline"
    if provider == "openai_compatible":
        return f"Endpoint model {model or ''}".strip(), "paid"
    names = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google"}
    name = names.get(provider, provider)
    return (f"{name} {model}" if model else f"External provider configured: {name}"), "paid"


def _default_steps(active: str, evidence_url: str | None) -> list[Step]:
    steps = [
        Step("imports", "Sources", "/imports"),
        Step("codebook", "Codebook", "/codebook"),
        Step("configure", "Run coding", "/configure"),
    ]
    if evidence_url:
        steps.append(Step("evidence", "Review", evidence_url))
        steps.append(Step("analysis", "Results", evidence_url.replace("/evidence?", "/analysis?")))
    return steps


def render_steps(steps: list[Step], active: str) -> str:
    items = []
    for index, step in enumerate(steps, start=1):
        mark = "&#10003;" if step.state == "done" else str(index)
        current = ' aria-current="page"' if step.key == active else ""
        detail = f"<small>{e(step.detail)}</small>" if step.detail else ""
        items.append(
            f'<li class="step {e(step.state)}"><a href="{e(step.url)}"{current}>'
            f'<span class="step-mark" aria-hidden="true">{mark}</span>'
            f'<span><strong>{e(step.label)}</strong>{detail}</span></a></li>'
        )
    return '<ol class="steps">' + "".join(items) + "</ol>"


def render_workspace(
    *, title: str, intro: str, body: str, study: str | None,
    classification: str = "", provider: str = "", active: str = "overview", head: str = "",
    evidence_url: str | None = None, study_picker: str = "", steps: list[Step] | None = None,
    model: str | None = None, wide: bool = False, study_detail: str = "", tools: list[tuple[str, str, str]] | None = None,
    workspace_note: str = "",
) -> str:
    """Render engine-supplied content; never infer completion or approval states."""
    status = ""
    if study is not None and active != "setup":
        label = _CLASSIFICATION_LABELS.get(classification, f"{classification.title()} data" if classification else "Data not classified")
        model_text, dot = model_label(provider, model)
        status = (
            f'<span class="pill {e(classification)}">{e(label)}</span>'
            f'<span class="pill"><span class="dot {dot}"></span>{e(model_text)}</span>'
        )
    if study is None:
        sidebar = ""
        shell_class = "shell no-study"
    else:
        sequence = steps if steps is not None else _default_steps(active, evidence_url)
        tool_links = tools if tools is not None else [("compare", "/compare", "Compare runs")]
        tool_html = "".join(
            f'<a href="{e(url)}"{" aria-current=page" if key == active else ""}>{e(label)}</a>'
            for key, url, label in tool_links
        )
        sidebar = (
            '<aside class="studybar" aria-label="Study navigation">'
            f'<a class="study-title" href="/">{e(study)}'
            f'{f"<small>{e(study_detail)}</small>" if study_detail else ""}</a>'
            f'<nav aria-label="Study steps">{render_steps(sequence, active)}</nav>'
            f'<div class="more-tools"><h2>More</h2>{tool_html}</div>'
            f'{study_picker}'
            f'<p class="studybar-foot">{e(workspace_note) or "Runs on this computer. Nothing is uploaded unless you start a run with an external model."}</p>'
            "</aside>"
        )
        shell_class = "shell" + (" wide" if wide else "")
    page_head = (
        f'<header class="page-head"><h1>{e(title)}</h1>'
        f'{f"<p>{e(intro)}</p>" if intro else ""}</header>'
    ) if title else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · QualFrame</title><link rel="icon" href="data:,">{head}<link rel="stylesheet" href="/static/workspace.css"></head>
<body><a class="skip-link" href="#main">Skip to content</a>
<header class="appbar"><a class="wordmark" href="/home"><span>Qual</span>Frame</a>
<nav class="appbar-links" aria-label="Application"><a href="/home"{' aria-current="page"' if active == "home" else ""}>All studies</a><a href="/setup"{' aria-current="page"' if active == "setup" else ""}>New study</a></nav>
<div class="appbar-status">{status}</div></header>
<div class="{shell_class}">{sidebar}
<main id="main">{page_head}
{body}
<footer class="appfoot">QualFrame proposes codes; you decide. Every decision is kept with its source passage.</footer>
</main></div></body></html>'''
