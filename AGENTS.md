# QualFrame public snapshot

Build a human-supervised, local-first platform for reproducible, evidence-linked, AI-assisted directed qualitative content analysis. CFIR is the first reference method; preserve its exact prompt wording and framework labels.

Before product changes, read `docs/product_specification.md`, `docs/domain_model.md`, `docs/user_workflows.md`, `docs/model_evaluation_and_cost_control.md`, and `docs/capability_status.md`. Target specifications are not proof of implementation.

## Guardrails

- Preserve sources and prior outputs. Generated work belongs in `studies/`, `data/working/`, `artifacts/`, `review_queue/`, `exports/`, or `logs/`.
- Never commit real research inputs, derived research outputs, private reference workbooks, credentials, or notification recipients.
- Public examples and ordinary tests use synthetic fixtures and mock/cached providers.
- External model calls require explicit provider configuration, governance approval, an absolute ceiling, and applicable spending approval.
- Preserve prompt text; revisions require versioned assets.
- Python engine state and verified runs are authoritative. Never invent UI metrics or imply planned features work.
- Use small typed Python 3.11+ modules, side effects at the edges, and dry-run support for major commands.
- Preserve unrelated changes and completed work.

## Verification

Run `python -m pytest -q` and both offline demos for execution changes. Check UI changes at desktop and narrow widths. Update architecture, roadmap, and capability status when relevant. Do not publish without owner approval and a reviewed file inventory.
