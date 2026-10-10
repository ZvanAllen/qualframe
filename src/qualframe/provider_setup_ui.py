# ruff: noqa: E501
"""Researcher-facing provider preparation form."""

from datetime import date
from html import escape


def provider_setup_form(provider: str, model: str | None, values: dict | None = None) -> str:
    values = values or {}
    def selected(name: str) -> str:
        return " selected" if provider == name else ""
    markup = f'''<section><h2>Provider and study budget</h2>
<p>Prepare an API configuration without sending data or spending money. Saving enables a no-call preflight. Starting a paid run requires a separate confirmation.</p>
<p>Your files stay in this local study. A live coding request sends the selected source text and codebook to your chosen API provider. Confirm your study permits that transfer before configuring a provider.</p>
<form action="/provider/save" method="post" class="grid" autocomplete="off">
<label>API provider<select name="provider"><option value="openai"{selected("openai")}>OpenAI</option><option value="anthropic"{selected("anthropic")}>Anthropic</option></select></label>
<label>Exact API model ID<input name="model" value="{escape(model or "") if provider in {"openai", "anthropic"} else ""}" required></label>
<label>Output token limit<input name="max_tokens" type="number" min="128" max="64000" value="4000" required></label>
<label>Temperature<input name="temperature" type="number" min="0" max="1" step="0.1" placeholder="Provider default; leave blank for reasoning"></label>
<label>OpenAI API mode<select name="api_mode"><option value="chat_completions">Chat Completions / Anthropic Messages</option><option value="responses">OpenAI Responses (reasoning models)</option></select></label>
<label>OpenAI reasoning effort<select name="reasoning_effort"><option value="">Provider default</option><option>none</option><option>minimal</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select></label>
<p>Effort requires OpenAI Responses and a blank temperature. Supported efforts depend on the exact model; unavailable settings fail explicitly. Anthropic effort also requires a blank temperature and a model that supports effort. Thinking uses the selected model's default. No requests retry automatically.</p>
<label>Anthropic effort<select name="anthropic_effort"><option value="">Provider default</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select></label>
<label>Study spending ceiling (USD)<input name="absolute_limit_usd" type="number" min="0.01" max="10000" step="0.01" required></label>
<label>Input price per million tokens (USD)<input name="input_rate" type="number" min="0.000001" step="any" required></label>
<label>Output price per million tokens (USD)<input name="output_rate" type="number" min="0.000001" step="any" required></label>
<label>Pricing checked on<input name="pricing_date" type="date" value="{date.today().isoformat()}" required></label>
<label>Official pricing source<input name="pricing_source" type="url" required></label>
<p>Use current standard token prices from your provider. Cache discounts are not assumed. Cost pauses retain the existing email notification adapter; email delivery requires local SMTP setup and is not verified here.</p>
<label>API key for this app session<input name="api_key" type="password" autocomplete="new-password"></label>
<p>A supplied key is kept only in this app process, never in study files or exports. Leave blank to retain a key already available to this process. Re-enter it after restarting the app.</p>
<label>Researcher name<input name="actor" required></label><label>Reason for configuration<textarea name="rationale" required></textarea></label>
<label class="check"><input name="governance_confirmed" type="checkbox" value="yes" required> This study permits sending its selected material to this provider.</label>
<button>Save provider and budget</button></form></section>'''

    # Populate only declared configuration controls, never identity or credentials.
    import re
    for name in ("max_tokens", "temperature", "absolute_limit_usd", "input_rate", "output_rate", "pricing_date", "pricing_source"):
        if name not in values:
            continue
        value = escape(str(values[name]) if values[name] is not None else "", quote=True)
        pattern = rf'<input name="{name}"[^>]*>'
        def fill(match, value=value):
            tag = re.sub(r' value="[^"]*"', "", match.group(0))
            return tag[:-1] + f' value="{value}">'
        markup = re.sub(pattern, fill, markup)
    for name in ("api_mode", "reasoning_effort", "anthropic_effort"):
        value = values.get(name) or ""
        pattern = rf'<select name="{name}">(.*?)</select>'
        def choose(match, value=value, name=name):
            content = match.group(1).replace(" selected", "")
            content = content.replace(f'<option value="{value}">', f'<option value="{value}" selected>')
            content = content.replace(f'<option>{value}</option>', f'<option selected>{value}</option>')
            return f'<select name="{name}">{content}</select>'
        markup = re.sub(pattern, choose, markup)
    preset = '''<section><h2>Quick setup</h2><p>Apply a dated configuration, then review your study ceiling and data permission below.</p><button type="button" id="gpt52-preset">Use GPT-5.2 · medium reasoning</button><p class="muted">Snapshot 2025-12-11. Standard pricing checked September 8, 2026. You can change every setting before saving.</p></section>'''
    script = '''<script>(()=>{const f=document.querySelector('form[action="/provider/save"]');
    function providerFields(){const openai=f.elements.provider.value==='openai';for(const name of ['api_mode','reasoning_effort','anthropic_effort']){const el=f.elements[name];el.closest('label').hidden=name==='anthropic_effort'?openai:!openai;el.disabled=el.closest('label').hidden;}}
    f.elements.provider.addEventListener('change',providerFields);providerFields();
    document.getElementById('gpt52-preset').addEventListener('click',()=>{const values={provider:'openai',model:'gpt-5.2-2025-12-11',api_mode:'responses',reasoning_effort:'medium',temperature:'',max_tokens:'24000',input_rate:'1.75',output_rate:'14',pricing_date:'2026-09-08',pricing_source:'https://developers.openai.com/api/docs/models/gpt-5.2'};for(const [k,v] of Object.entries(values))f.elements[k].value=v;providerFields();f.elements.absolute_limit_usd.focus();});
    })();</script>'''
    return preset + markup + script
