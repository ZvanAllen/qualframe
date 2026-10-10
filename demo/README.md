# Demo material

Everything here is fictional and safe to share.

| Folder | What it is |
| --- | --- |
| `datasets/ai-scribe/` | The demo study opened by **Open the demo study** in the app: six fictional interviews about adopting an AI documentation assistant, a 15-code codebook (YAML and Excel) and participant information. See its README. |
| `recordings/` | Coding responses replayed by the demo study so it works without a model or an API key. Each recording's `recording.json` names the model, its settings, the prompt hash, token usage and cost. The `demo-illustrative-*` recordings are hand-written codings used by the tests and are not offered in the app. To make a new one, see `scripts/record_demo.py` and [docs/development.md](../docs/development.md). |
| `fixtures/`, `cached_responses/`, `config/`, `project/`, `presentation/` | The September 2026 CFIR interview demo, kept for the engine's tests. Run it with `python scripts/run_interview_demo.py`; see [docs/reference/interview_demo_handover.md](../docs/reference/interview_demo_handover.md). |

To try QualFrame, you don't need any of these files directly: run `qualframe start` and choose **Open the demo study**.
