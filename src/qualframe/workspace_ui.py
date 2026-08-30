"""Shared, dependency-free presentation for the local researcher workspace."""
from __future__ import annotations

import html
from pathlib import Path


def render_workspace(
    *, title: str, intro: str, body: str, study: str,
    classification: str, provider: str, active: str = "overview", head: str = "",
    evidence_url: str | None = None,
) -> str:
    """Render engine-supplied content; never infer completion or approval states."""
    css = (Path(__file__).parent / "static" / "workspace.css").read_text(encoding="utf-8")
    links = [("overview", "/", "01", "Study overview"),
             ("setup", "/setup", "+", "Create a study"),
             ("imports", "/imports", "02", "Source library"),
             ("configure", "/configure", "03", "Analysis method")]
    if evidence_url:
        links.append(("evidence", html.escape(evidence_url), "04", "Evidence review"))
    navigation = "".join(
        f'<a href="{url}" class="nav-link{" active" if key == active else ""}"'
        f' aria-current="{str(key == active).lower()}">'
        f'<span class="nav-number">{number}</span>{label}</a>'
        for key, url, number, label in links
    )
    local = provider in {"mock", "cached_demo"}
    mode = "Offline mock" if provider == "mock" else "Offline cached" if local else "External provider configured"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · QualFrame</title>{head}<style>{css}</style></head>
<body><a class="skip-link" href="#main">Skip to content</a>
<aside class="sidebar"><a class="brand" href="/" aria-label="QualFrame home"><span class="brand-mark">q<span>f</span></span><span>QualFrame<small>RESEARCH WORKSPACE</small></span></a>
<div class="sidebar-label">CURRENT STUDY</div><div class="study-name">{html.escape(study)}</div>
<nav aria-label="Study navigation">{navigation}</nav>
<div class="sidebar-note"><span class="sidebar-label">HUMAN-SUPERVISED BY DESIGN</span><p>Every code, connected to evidence.<br>Every decision, traceable.</p></div>
<div class="sidebar-bottom"><span class="status-dot"></span> Local workspace <span class="version">v0.1</span><small>Single researcher · Research prototype</small></div></aside>
<div class="app"><header class="topbar"><span>Workspace <span class="breadcrumb">/ {html.escape(title)}</span></span><div class="topbar-badges"><span class="badge">{html.escape(classification.title())} data</span><span class="mode"><span class="status-dot"></span>{mode}</span></div></header>
<main id="main"><div class="page-heading"><div class="eyebrow">DIRECTED QUALITATIVE ANALYSIS</div><h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p></div>
{body}
<footer>QualFrame · Human interpretation remains human-owned.<span>Single-user, loopback-only interface. Not authenticated or deployment-ready.</span></footer>
</main></div></body></html>'''
