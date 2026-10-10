# Demo guide

## Five-minute interactive walkthrough

Run `python scripts/run_workspace_demo.py` and open the printed local review URL.

1. **Frame the problem:** reproducible directed coding needs more than a model response; it needs evidence, a declared method, and a record of human decisions.
2. **Identify the boundary:** two fictional transcripts; deterministic mock assignments; no API requests or claims of coding accuracy.
3. **Inspect one record:** exact highlighted span, surrounding context, code definition, rationale, and expandable provenance.
4. **Record a decision:** accept or edit with a researcher name and rationale. An edit creates a derived record; source text and prior actions remain intact.
5. **Show the release gate:** export remains unavailable until all four records have a non-deferred decision. Resolve them and export the JSON/Excel package.
6. **Inspect the method editor:** segmentation, context, cardinality, overlap, and partitioning are versioned. Do not imply that calibration or every policy editor exists.

## Optional CFIR walkthrough

Run `python scripts/run_interview_demo.py` and open the generated `demo/presentation/index.html` as a local file.

This separate read-only report shows five executed reference stages, nine artifacts, nine Excel exports, and one deliberately contradictory cached row routed to QA. It demonstrates the real runner/parser/QA/export paths. It is not evidence of new live model performance.

The generic review demo and legacy CFIR table demo have different output contracts. The legacy CFIR-to-exact-span adapter is still planned.

## Before a presentation

- Run the tests and both offline demonstrations.
- Use only the provided synthetic fixtures.
- Check that the browser shows synthetic data and an offline provider.
- Do not reuse a study ID that already exists; the launcher intentionally refuses overwrite.
- Keep the application on loopback. It has no multi-user authentication.
- Describe calibration, model benchmarking, metadata analysis, and direct selection editing as planned.
