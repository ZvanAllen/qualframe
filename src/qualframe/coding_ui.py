"""Run coding: choose a model, see what a run will send and cost, and start it."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from qualframe.app_workspace import researcher_name
from qualframe.config import resolve_repo_path
from qualframe.directed_analysis import partition_codebook
from qualframe.io.transcript_io import transcript_to_text
from qualframe.provider_setup import STANDARD_KEY_ENV
from qualframe.providers.base import estimate_tokens
from qualframe.ui_kit import e, identity_fields, notices, plural, provider_display

OFFLINE_PROVIDERS = {"mock", "recorded", "cached_demo"}
# How much text is kept with each coded passage: (label, (unit, before, after)).
CONTEXT_PRESETS = {
    "quote": ("Just the quotation", ("sentences", 0, 0)),
    "sentence": ("The quotation and a sentence either side", ("sentences", 1, 1)),
    "turn": ("The whole answer (speaker turn)", ("turns", 0, 0)),
    "question": ("The whole answer and the question before it", ("turns", 1, 0)),
}
_PROMPT_OVERHEAD_TOKENS = 900
# Calibrated against recorded runs (October 2026). Provider tokenizers counted about 1.5 times
# the characters/4 heuristic; current models wrote about one output token per transcript token
# and spent 1,000 to 2,000 hidden reasoning tokens per request. Kept on the high side.
_INPUT_TOKEN_FACTOR = 1.5
_OUTPUT_PER_TRANSCRIPT_TOKEN = 1.2
_REASONING_TOKENS_PER_REQUEST = 1800
# The CFIR reference prompts ask for a row for every construct in each domain, so each domain's
# answer is long whatever the transcript says. Calibrated on the AMN Study A sample runs
# (October 2026): Claude Sonnet 5.5 wrote about 9,000 tokens per domain for an 8,500-word
# transcript; GPT-6.1 Sol wrote far less. Kept at the Sonnet figure.
_CFIR_OUTPUT_PER_TRANSCRIPT_TOKEN = 0.55
_CFIR_OUTPUT_PER_REQUEST = 2500


def load_presets(app) -> tuple[str, list[dict]]:
    """Model presets ship with the app, so model names and prices update when QualFrame does."""
    from qualframe.app_workspace import APP_ROOT

    path = APP_ROOT / "config/model_presets.yaml"
    if not path.exists():
        path = resolve_repo_path(app.repo_root, "config/model_presets.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return str(data.get("checked_on", "")), list(data.get("presets", []))


def is_local_endpoint(base_url: str | None) -> bool:
    host = urlparse(base_url or "").hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"}


def estimate_study(app) -> dict:
    """Rough request and token counts for coding every transcript once. Not a billing figure."""
    runner = app.runner
    files = runner._transcript_files()
    transcript_tokens = [estimate_tokens(transcript_to_text(path)) for path in files]
    per_domain = False
    if runner.codebook is not None and runner.method is not None:
        groups = partition_codebook(runner.codebook, runner.method.partitioning)
        codebook_tokens = [estimate_tokens(json.dumps([c.model_dump() for c in codes])) for codes in groups.values()]
    else:
        reference = runner._load_reference_file("codebook") or ""
        per_domain = any(s.domain_iterations for s in runner.pipeline.stages)
        codebook_tokens = [estimate_tokens(reference)] * (6 if per_domain else 1)
    requests = len(files) * len(codebook_tokens)
    groups = max(1, len(codebook_tokens))
    input_tokens = int(_INPUT_TOKEN_FACTOR * sum(t + c + _PROMPT_OVERHEAD_TOKENS for t in transcript_tokens for c in codebook_tokens))
    if per_domain:
        output_tokens = sum(int(_CFIR_OUTPUT_PER_TRANSCRIPT_TOKEN * t) + _CFIR_OUTPUT_PER_REQUEST
                            for t in transcript_tokens for _ in codebook_tokens)
    else:
        output_tokens = sum(int(_OUTPUT_PER_TRANSCRIPT_TOKEN * t / groups) + _REASONING_TOKENS_PER_REQUEST
                            for t in transcript_tokens for _ in codebook_tokens)
    return {"transcripts": len(files), "requests": requests, "input_tokens": input_tokens, "output_tokens": output_tokens}


def cost_for(estimate: dict, input_rate: float, output_rate: float) -> float:
    return (estimate["input_tokens"] * input_rate + estimate["output_tokens"] * output_rate) / 1_000_000


def _money(value: float) -> str:
    if value == 0:
        return "$0"
    if value < 0.01:
        return "under $0.01"
    return f"about ${value:,.2f}"


def _current_rates(app) -> tuple[float, float, float | None]:
    provider = app.runner.project.provider.name
    if provider in OFFLINE_PROVIDERS:
        return 0.0, 0.0, None
    try:
        cost = app.runner._build_cost_controller(run_id="settings", artifact_root=app.artifacts_dir)
    except (ValueError, OSError):
        cost = None
    if cost is None:
        return 0.0, 0.0, None
    return cost.pricing.input_per_million_usd, cost.pricing.output_per_million_usd, cost.policy.absolute_limit_usd


def _offline_choices(app) -> list[dict]:
    if app.runner.project.data_classification != "synthetic":
        return []
    from qualframe.demo_study import available_recordings

    choices = [
        {"id": f"recorded:{info['id']}", "label": info.get("label", info["id"]),
         "summary": info.get("description", "Recorded responses."), "offline": True}
        for info in available_recordings()
    ]
    choices.append({"id": "mock", "label": "Offline test model",
                    "summary": "Returns placeholder output for testing the workflow. Not real coding.", "offline": True})
    return choices


def _model_section(app, estimate: dict) -> str:
    project = app.runner.project
    provider = project.provider
    checked_on, presets = load_presets(app)
    current_key = ""
    if provider.name == "recorded":
        current_key = f"recorded:{provider.model}"
    elif provider.name == "mock":
        current_key = "mock"
    else:
        for preset in presets:
            if preset["provider"] == provider.name and (preset.get("model") == provider.model or preset["provider"] == "openai_compatible") \
                    and (preset.get("base_url") or None) in {None, "", provider.base_url} :
                current_key = preset["id"]
                break
    cards = []
    for choice in _offline_choices(app):
        checked = " checked" if choice["id"] == current_key else ""
        cards.append(
            f'<label class="choice"><input type="radio" name="preset" value="{e(choice["id"])}"{checked} data-offline="1">'
            f'<span><strong>{e(choice["label"])}</strong><small>{e(choice["summary"])}</small><em>Offline, no cost</em></span></label>'
        )
    preset_data = {}
    for preset in presets:
        price = cost_for(estimate, float(preset.get("input_rate") or 0), float(preset.get("output_rate") or 0))
        price_text = ("Runs on this computer, no cost" if preset.get("local") else
                      "Your endpoint's prices" if preset["provider"] == "openai_compatible" else
                      f"{_money(price)} for this study")
        checked = " checked" if preset["id"] == current_key else ""
        cards.append(
            f'<label class="choice"><input type="radio" name="preset" value="{e(preset["id"])}"{checked}>'
            f'<span><strong>{e(preset["label"])}</strong><small>{e(preset.get("summary", ""))}</small><em>{e(price_text)}</em></span></label>'
        )
        preset_data[preset["id"]] = {k: preset.get(k) for k in (
            "provider", "model", "base_url", "api_mode", "reasoning_effort", "temperature", "max_tokens",
            "input_rate", "output_rate", "pricing_source", "key_hint", "local")}
        env_name = STANDARD_KEY_ENV.get(preset["provider"])
        preset_data[preset["id"]]["env_key"] = env_name if env_name and os.getenv(env_name) else ""
    input_rate, output_rate, limit = _current_rates(app)
    name = researcher_name(app.repo_root)
    values = provider.model_dump()
    preset_json = json.dumps(preset_data).replace("</", "<\\/")
    temperature = "" if values.get("temperature") is None else values["temperature"]
    return f'''<section><div class="section-head"><h2>1. Choose a model</h2><span class="muted">Now using: {e(provider_display(provider.name, provider.model))}</span></div>
<p>Each transcript is sent with your codebook and the coding instructions. Cost estimates use {plural(estimate["transcripts"], "transcript")} in this study and list prices checked on {e(checked_on)}; your provider's bill is what counts.</p>
<form method="post" action="/provider/save" id="model-form" autocomplete="off">
<fieldset><legend class="sr-only">Model</legend><div class="choices">{"".join(cards)}</div></fieldset>
<div id="model-fields">
<div class="grid">
<label>Model name<input name="model" value="{e(provider.model or "") if provider.name not in OFFLINE_PROVIDERS else ""}" required><small id="model-hint">The provider's exact model identifier.</small></label>
<label data-for="endpoint">Endpoint address<input name="base_url" type="url" value="{e(provider.base_url or "")}" placeholder="http://localhost:11434/v1"><small>For Azure OpenAI, use https://YOUR-RESOURCE.openai.azure.com/openai/v1/</small></label>
<label>Spending limit for this study (USD)<input name="absolute_limit_usd" type="number" min="0.01" max="10000" step="0.01" value="{e(str(limit if limit else 5))}" required><small>Coding pauses before any request that could go past this amount.</small></label>
</div>
<div class="grid key-row" data-for="key">
<label>API key<input name="api_key" type="password" autocomplete="new-password"><small id="key-hint">Kept in memory only while QualFrame is open. Never saved to study files.</small></label>
<label class="check" data-for="env-key"><input type="checkbox" name="use_environment_key" value="yes" checked><span>Use the key already set on this computer (<code id="env-name"></code>)</span></label>
</div>
<label class="check" data-for="consent"><input name="governance_confirmed" type="checkbox" value="yes"><span id="consent-text">My ethics approval and data agreements allow sending these transcripts to this provider.</span></label>
<details><summary>Advanced settings</summary><div class="grid">
<label>Maximum output tokens per request<input name="max_tokens" type="number" min="128" max="64000" value="{e(str(values.get("max_tokens") or 16000))}" required></label>
<label>Temperature<input name="temperature" type="number" min="0" max="1" step="0.1" value="{e(str(temperature))}" placeholder="Provider default"><small>Leave blank for reasoning models.</small></label>
<label data-for="openai">Reasoning effort<select name="reasoning_effort"><option value="">Provider default</option><option>none</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select></label>
<input type="hidden" name="api_mode" value="{e(values.get("api_mode") or "chat_completions")}"><input type="hidden" name="provider" value="{e(provider.name)}">
<label>Input price per million tokens (USD)<input name="input_rate" type="number" min="0" step="any" value="{e(str(input_rate))}" required></label>
<label>Output price per million tokens (USD)<input name="output_rate" type="number" min="0" step="any" value="{e(str(output_rate))}" required></label>
<label>Prices checked on<input name="pricing_date" type="date" value="{e(checked_on or date.today().isoformat())}" required></label>
<label>Pricing page<input name="pricing_source" type="url"></label>
</div></details>
</div>
{identity_fields(name, note_label="Add a note about this choice")}
<div class="actions"><button>Use this model</button></div></form>
<script type="application/json" id="preset-data">{preset_json}</script>
<script>(()=>{{const f=document.getElementById('model-form'),data=JSON.parse(document.getElementById('preset-data').textContent);
const fields=document.getElementById('model-fields');
function show(sel,on){{for(const el of f.querySelectorAll('[data-for="'+sel+'"]')){{el.hidden=!on;for(const i of el.querySelectorAll('input,select'))i.disabled=!on;}}}}
function apply(initial){{const c=f.querySelector('input[name=preset]:checked');if(!c){{fields.hidden=true;return;}}
 const offline=c.dataset.offline==='1';fields.hidden=offline;f.action=offline?'/provider/offline':'/provider/save';
 for(const i of fields.querySelectorAll('input,select'))if(!i.closest('[data-for]'))i.disabled=offline;
 if(offline)return;const p=data[c.value];
 if(!initial){{for(const k of ['model','base_url','max_tokens','input_rate','output_rate','pricing_source'])if(f.elements[k]&&p[k]!==undefined&&p[k]!==null)f.elements[k].value=p[k];
  f.elements.temperature.value=p.temperature===null||p.temperature===undefined?'':p.temperature;f.elements.reasoning_effort.value=p.reasoning_effort||'';}}
 f.elements.provider.value=p.provider;f.elements.api_mode.value=p.api_mode||'chat_completions';
 show('endpoint',p.provider==='openai_compatible');show('openai',p.provider==='openai');
 show('key',!p.local);show('env-key',!!p.env_key&&!p.local);document.getElementById('env-name').textContent=p.env_key;
 document.getElementById('key-hint').textContent=(p.key_hint||'')+' Kept in memory only while QualFrame is open.';
 show('consent',!p.local);f.elements.governance_confirmed.required=!p.local;}}
f.addEventListener('change',ev=>{{if(ev.target.name==='preset')apply(false);}});apply(true);
f.addEventListener('submit',()=>{{const c=f.querySelector('input[name=preset]:checked');if(c&&data[c.value]&&data[c.value].local){{const g=f.elements.governance_confirmed;g.disabled=false;g.checked=true;}}}});
}})();</script></section>'''


def _method_section(app) -> str:
    method = app.runner.method
    if method is None:
        return ""
    cfir = app.runner.pipeline.id.startswith("transcript_cfir")

    def sel(value: str, current: str) -> str:
        return " selected" if value == current else ""

    partition = (
        "<input type='hidden' name='partition_strategy' value='per_top_level_category'>"
        "<p class='muted'>The CFIR workflow sends one request per CFIR domain.</p>"
        if cfir else
        f'''<label>How much of the codebook goes in each request<select name="partition_strategy">
<option value="full_codebook"{sel("full_codebook", method.partitioning.strategy)}>The whole codebook at once</option>
<option value="per_top_level_category"{sel("per_top_level_category", method.partitioning.strategy)}>One request per top-level category</option></select>
<small>Splitting by category means more requests but less for the model to juggle in each.</small></label>''')
    current = (method.context.unit, method.context.before, method.context.after)
    preset = next((key for key, (_, value) in CONTEXT_PRESETS.items() if value == current), "custom")
    kept = CONTEXT_PRESETS[preset][0] if preset != "custom" else (
        f"{method.context.before} before and {method.context.after} after, in {method.context.unit}")
    summary = (
        f"{'Several codes' if method.coding.cardinality == 'multi_label' else 'One code'} per passage, "
        f"{'whole codebook per request' if method.partitioning.strategy == 'full_codebook' else 'one request per category'}, "
        f"keeps {kept[0].lower() + kept[1:]}"
    )
    checked = lambda key: " checked" if key == preset else ""
    preset_options = "".join(
        f'<label class="check"><input type="radio" name="context_preset" value="{key}"{checked(key)}><span>{e(label)}</span></label>'
        for key, (label, _) in CONTEXT_PRESETS.items()
    ) + f'<label class="check"><input type="radio" name="context_preset" value="custom"{checked("custom")}><span>Custom (below)</span></label>'
    return f'''<section><details class="method-options"><summary>Coding options <span class="muted">({e(summary)})</span></summary>
<form method="post" action="/method/update">
<fieldset class="kept-text"><legend>Text kept with each code</legend>{preset_options}
<small>The highlighted quotation stays the evidence. The surrounding text is saved with it, shown in review and results, and exported. More context helps later steps such as suggesting themes.</small>
<details class="custom-context"><summary>Custom context</summary><div class="grid">
<label>Before the passage<input type="number" min="0" max="10" name="context_before" value="{method.context.before}" required></label>
<label>After the passage<input type="number" min="0" max="10" name="context_after" value="{method.context.after}" required></label>
<label>Measured in<select name="context_unit"><option value="sentences"{sel("sentences", method.context.unit)}>Sentences</option><option value="turns"{sel("turns", method.context.unit)}>Speaker turns (always the whole turn)</option><option value="paragraphs"{sel("paragraphs", method.context.unit)}>Paragraphs</option><option value="characters"{sel("characters", method.context.unit)}>Characters</option></select></label></div></details></fieldset>
<div class="grid">
<label>Codes per passage<select name="coding_cardinality"><option value="multi_label"{sel("multi_label", method.coding.cardinality)}>A passage can receive several codes</option><option value="single_label"{sel("single_label", method.coding.cardinality)}>One code per passage</option></select></label>
{partition}

<label>Passages chosen by<select name="segmentation_strategy"><option value="model_proposed"{sel("model_proposed", method.segmentation.strategy)}>The model</option><option value="sentence"{sel("sentence", method.segmentation.strategy)}>Sentences</option><option value="paragraph"{sel("paragraph", method.segmentation.strategy)}>Paragraphs</option><option value="researcher_presegmented"{sel("researcher_presegmented", method.segmentation.strategy)}>Pre-segmented by the researcher</option></select></label>
</div><label class="check"><input type="checkbox" name="allow_overlapping_spans" value="yes"{" checked" if method.coding.allow_overlapping_spans else ""}><span>Coded passages may overlap</span></label>
{identity_fields(researcher_name(app.repo_root), note_label="Add a note about this change")}
<p class="muted">Changes save a new method version. Earlier runs keep the version they used.</p><button class="secondary">Save coding options</button></form></details></section>'''


def _run_section(app, estimate: dict, blockers: list[str]) -> str:
    project = app.runner.project
    provider = project.provider
    input_rate, output_rate, limit = _current_rates(app)
    offline = provider.name in OFFLINE_PROVIDERS
    local = provider.name == "openai_compatible" and is_local_endpoint(provider.base_url)
    cost = cost_for(estimate, input_rate, output_rate)
    facts = [
        f"<li><strong>{plural(estimate['transcripts'], 'transcript')}</strong></li>",
        f"<li><strong>{plural(estimate['requests'], 'request')}</strong> to {e(provider_display(provider.name, provider.model))}</li>",
        f"<li>Estimated cost <strong>{e(_money(cost) if not (offline or local) else '$0')}</strong>"
        + (f" (limit ${limit:,.2f})" if limit else "") + "</li>",
    ]
    if blockers:
        items = "".join(f"<li>{b}</li>" for b in blockers)
        return f'<section><h2>2. Start coding</h2><ul class="facts">{"".join(facts)}</ul><div class="notice"><p>Before you can start:</p><ul>{items}</ul></div></section>'
    if offline:
        destination = "Nothing leaves this computer."
        approval = ""
    elif local:
        destination = f"Transcripts go to the local server at {e(provider.base_url or '')} and stay on this computer."
        approval = ('<label class="check"><input name="live_confirmed" type="checkbox" value="yes" required>'
                    '<span>Start coding with this local model.</span></label>')
    else:
        destination = (f"Each transcript and your codebook will be sent to {e(provider_display(provider.name, provider.model))}. "
                       "Requests are not retried automatically.")
        approval = ('<label class="check"><input name="live_confirmed" type="checkbox" value="yes" required>'
                    f'<span>Send the chosen transcripts to this provider and allow spending up to '
                    f'${limit or 0:,.2f} for this study.</span></label>')
    return f'''<section><h2>2. Start coding</h2><ul class="facts">{"".join(facts)}</ul><p>{destination}</p>
<form method="post" action="/coding/start">{_scope_fields(app, estimate, cost)}{approval}{identity_fields(researcher_name(app.repo_root), note_label="Add a note about this run")}
<div class="actions"><button class="big">Start coding</button></div></form>
<p class="muted">You can watch progress here and start reviewing as soon as coding finishes.</p></section>'''


def _scope_fields(app, estimate: dict, cost: float) -> str:
    """Code every transcript, or a sample first to check the output and the cost."""
    files = app.runner._transcript_files()
    if len(files) < 2:
        return ""
    per = cost / max(1, estimate["transcripts"])
    groups: dict[str, list] = {}
    for path in files:
        groups.setdefault(path.parent.name, []).append(path)
    boxes = "".join(
        f'<fieldset class="sample-group"><legend>{e(group)}</legend>' + "".join(
            f'<label class="check"><input type="checkbox" name="sample" value="{e(path.relative_to(app.repo_root).as_posix())}">'
            f'<span>{e(path.stem)}</span></label>' for path in members) + "</fieldset>"
        for group, members in groups.items())
    each = f" (about {_money(per)} each)" if per >= 0.005 else ""
    return (f'<fieldset class="scope"><legend>Transcripts to code</legend>'
            f'<label class="check"><input type="radio" name="scope" value="all" checked><span>All {len(files)} transcripts</span></label>'
            f'<label class="check"><input type="radio" name="scope" value="sample"><span>A sample to check the output and cost first{each}</span></label>'
            f'<details class="sample-picker"><summary>Choose the sample</summary><div class="sample-groups">{boxes}</div></details></fieldset>')


def coding_blockers(app) -> list[str]:
    runner = app.runner
    blockers = []
    if not runner._transcript_files():
        blockers.append('<a href="/imports">Add at least one transcript.</a>')
    cfir = any(s.domain_iterations for s in runner.pipeline.stages)
    if runner.codebook is None and not cfir:
        blockers.append('<a href="/codebook">Add a codebook.</a>')
    provider = runner.project.provider
    if provider.name in OFFLINE_PROVIDERS and runner.project.data_classification != "synthetic":
        blockers.append("Choose a model above. Offline test models are only for test-data studies.")
    if provider.name not in OFFLINE_PROVIDERS:
        try:
            cost = runner._build_cost_controller(run_id="settings", artifact_root=app.artifacts_dir)
        except (ValueError, OSError):
            cost = None
        if cost is None:
            blockers.append("Choose a model above and save it with a spending limit.")
        elif cost.unresolved_requests():
            blockers.append("An earlier request's usage is unconfirmed. Open the run details to resolve it.")
        env = provider.api_key_env or ""
        if not (provider.name == "openai_compatible" and is_local_endpoint(provider.base_url)) and not os.getenv(env):
            blockers.append("Enter your API key above. Keys are kept only while QualFrame is open.")
    if cfir and project_reference_missing(app):
        blockers.append('<a href="/codebook">Import the CFIR reference workbook.</a>')
    return blockers


def project_reference_missing(app) -> bool:
    if app.runner.project.data_classification == "synthetic":
        return False
    reference = resolve_repo_path(app.repo_root, app.runner.project.paths["reference"]) / "codebook.xlsx"
    return not Path(reference).exists()


def _runs_by_instructions(app) -> dict[str, list[str]]:
    """Prompt hash -> run ids, from each run's configuration lock."""
    used: dict[str, list[str]] = {}
    if not app.artifacts_dir.exists():
        return used
    for lock in sorted(app.artifacts_dir.glob("*/analysis_configuration_lock.json")):
        try:
            assets = json.loads(lock.read_text(encoding="utf-8")).get("assets", [])
        except (OSError, ValueError):
            continue
        for asset in assets:
            if asset.get("kind") == "prompt" and asset.get("sha256"):
                used.setdefault(asset["sha256"], []).append(lock.parent.name)
    return used


def _instructions_section(app) -> str:
    from qualframe.coding_instructions import current_instructions, instruction_versions

    project_path = app._managed_project_path()
    try:
        _, _, text, label = current_instructions(app.repo_root, project_path)
        versions = instruction_versions(app.repo_root, project_path)
    except ValueError as exc:
        return f'<section><details class="method-options"><summary>Coding instructions</summary><p class="muted">{e(str(exc))}</p></details></section>'
    used = _runs_by_instructions(app)
    rows = ""
    for version in versions:
        runs = used.get(version.sha256, [])
        when = f"{e(version.created_by or '')}, {e(version.created_at_utc[:10])}" if version.created_at_utc else "Included with QualFrame"
        action = ("<strong>In use</strong>" if version.current else
                  f'<form method="post" action="/instructions/use"><input type="hidden" name="framework_ref" value="{e(version.framework_ref)}">'
                  '<button class="secondary">Use this version</button></form>')
        rows += (f"<tr><td>{e(version.label)}<br><span class='muted'>SHA-256 {e(version.sha256[:12])}</span></td><td>{when}</td>"
                 f"<td>{e(', '.join(runs)) if runs else '<span class=muted>None yet</span>'}</td><td>{action}</td></tr>")
    table = (f'<table class="versions"><thead><tr><th>Version</th><th>Saved</th><th>Runs that used it</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
             if len(versions) > 1 else "")
    return f'''<section><details class="method-options" id="instructions"><summary>Coding instructions <span class="muted">({e(label)})</span></summary>
<p>These instructions go to the model with each transcript, followed by your coding options, the transcript and the codebook. Editing saves a new version; the standard instructions are never changed, and earlier runs keep the version they used. To see the effect of a change, code with each version and use Compare runs.</p>
{table}
<form method="post" action="/instructions/save" class="instructions-form">
<label>Instructions<textarea name="instructions" rows="18" spellcheck="true">{e(text)}</textarea>
<small>Keep the Output section: QualFrame needs the JSON format it describes. Recorded demo runs only replay the standard instructions.</small></label>
<label>Name for this version<input name="label" required maxlength="120" placeholder="For example: Shorter quotations"></label>
{identity_fields(researcher_name(app.repo_root), note_label="Why this change")}
<button class="secondary">Save as a new version</button></form></details></section>'''


def render_coding(app, message: str = "", error: str = "") -> str:
    estimate = estimate_study(app)
    body = (notices(message, error) + _model_section(app, estimate)
            + _run_section(app, estimate, coding_blockers(app)) + _method_section(app) + _instructions_section(app))
    return app._render_workspace_page(
        title="Run coding", intro="Choose a model and start coding. Every proposal comes back to you for review.",
        body=body, active="configure")
