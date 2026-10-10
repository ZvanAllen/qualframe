# Working on QualFrame

QualFrame is open-source software for AI-assisted directed content analysis: a researcher brings transcripts and a codebook, a model proposes codes with exact quotations, and the researcher reviews every proposal. Read `README.md`, `docs/development.md` and `docs/decisions/0009-researcher-first-v1.md` before making changes. Documents in `docs/reference/` record the September 2026 prototype phase and are not current guidance.

## Guardrails

- Never commit real research inputs, derived research outputs, private codebooks or workbooks, credentials, or notification recipients. Examples and tests use the fictional fixtures under `demo/` and `tests/`.
- No live model calls or spending without the owner's explicit approval. Tests and CI use offline or recorded providers only.
- Never edit a released prompt or overwrite sources, prior outputs or review records. Add a new version instead.
- The study folder is the source of truth. Pages read state from it; never invent counts, statuses or capabilities in the interface.
- Interface text names what researchers do, in plain language. Engine terms belong in details and downloaded records.
- Keep the stack small: Python 3.11+, standard-library web server, server-rendered HTML, no front-end build step.

## Before finishing a change

Run `python -m pytest -q`. For interface changes, open the app (`qualframe start --workspace <tmp>`), go through the demo study, and check the pages at desktop and narrow widths. Do not publish or push without owner approval.
