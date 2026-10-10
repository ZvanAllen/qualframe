# Development notes

## Setup

```bash
uv venv -p 3.12 && source .venv/bin/activate     # Windows: .venv\Scripts\activate
uv pip install -e ".[dev,llm]"                    # or: pip install -e ".[dev,llm]"
python -m pytest -q
qualframe start --workspace /tmp/qualframe-dev    # a throwaway studies folder
```

Python 3.11 and 3.12 are supported; CI runs both on Windows, macOS and Linux. Tests use synthetic fixtures and offline providers only and never call a model.

## Layout

| Path | What it is |
| --- | --- |
| `src/qualframe/pipeline/project_runner.py` | The engine: builds a run plan, sends requests, saves every response as an artifact, records hashes and costs |
| `src/qualframe/evidence_review.py`, `evidence_anchoring.py` | Turns model output into review records and locates each quotation in the transcript |
| `src/qualframe/providers/` | OpenAI, Anthropic, OpenAI-compatible endpoints, offline mock, recorded responses |
| `src/qualframe/cost_control.py` | Spending limits, request reservations and the usage ledger |
| `src/qualframe/dashboard.py` | The local web server and actions (standard library `http.server`, no web framework) |
| `src/qualframe/*_ui.py`, `workspace_ui.py`, `static/` | Pages, shared layout, stylesheet, review keyboard script, bundled fonts |
| `src/qualframe/study_setup.py`, `app_workspace.py` | Creating studies, imports, and the studies folder |
| `config/` | Method, framework, pipeline, codebook and model-preset templates (YAML) |
| `prompts/` | Versioned prompt files. Never edit a released prompt; add a new version |
| `demo/datasets/`, `demo/recordings/` | The fictional demo study and replayable coding runs |
| `docs/decisions/` | Design decisions, numbered |
| `docs/reference/` | Earlier design notes, protocols and development records |

Pages are server-rendered HTML strings. Keep it that way unless an interaction clearly needs more: it keeps installation to a few pure-Python packages and makes every page testable without a browser.

## Principles

- **The engine's files are the truth.** Pages read state from the study folder; they never invent counts or statuses.
- **Nothing is overwritten.** Imports, method changes, review decisions and results are new versions or appended records.
- **Exact evidence.** A proposal becomes evidence only if its quotation is found exactly once in the transcript, or a person locates it.
- **No silent spending.** No automatic retries; every hosted request is estimated against the study's limit first.
- **Plain language in the interface.** Name things by what researchers do, not by how the code works.

## Recording demo responses

The demo study replays recorded responses so it works offline. To record a real model over the six fictional demo transcripts (about $0.15 to $0.25 with a mid-priced model):

```bash
python scripts/record_demo.py --name claude-sonnet-5-5-2026-10 --label "Claude Sonnet 5.5" \
    --preset anthropic-sonnet-5-5 --yes
```

A preset from `config/model_presets.yaml` supplies the model, settings and prices; keys come from the environment or a `.env` file in the repository folder. Spending is capped at $1 by default (`--limit-usd`). Then set `PRIMARY_RECORDING` or `COMPARISON_RECORDINGS` in `src/qualframe/demo_study.py`. Each `recording.json` stores the provider settings, prompt hash, token usage and estimated cost.

## Checks before a release

```bash
python -m pytest -q
python scripts/run_workspace_demo.py --no-serve
python scripts/run_interview_demo.py
python scripts/package_public_release.py --output artifacts/release.zip   # screens files for keys, personal paths and emails
```

Also open the app, run the demo end to end, and check pages at a narrow window width.
