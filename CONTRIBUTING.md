# Contributing

QualFrame is an early research prototype released under the MIT license. Small, testable changes with explicit capability boundaries are welcome.

- Use Python 3.11+ and run `python -m pytest -q`.
- Use synthetic fixtures and mock/cached providers; no live model calls in CI.
- Never include identifiable transcripts, private codebooks, credentials, notification recipients, or derived research outputs.
- Preserve source files, exact prompt wording, framework labels, and prior review actions.
- Analysis-setting changes must preserve version and provenance semantics.
- Verify UI changes in the actual browser using synthetic data.
- Update `docs/capability_status.md` when behavior changes. Software tests are not methodological validation.

Issue reports should contain only a minimal synthetic reproduction, expected behavior, observed behavior, and environment information. Keep secrets and real research content out of screenshots and logs.
