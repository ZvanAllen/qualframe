# Reviewed analysis increment — September 10, 2026

## Implemented

- Analyze evidence navigation from the selected run and the completed reviewer.
- Readiness checks requiring completed coding and complete review for every frozen-plan transcript. Empty outputs remain blocked until an explicit no-evidence transcript checkpoint is implemented.
- Immutable, content-addressed reviewed snapshots with dry-run support. Accepted and latest edited spans/assignments are retained; rejected and absence proposals are separate. Repeated freezing of unchanged inputs reuses the existing snapshot.
- Source-file, exact-span, model-artifact, reviewed-record, and derived-edit lineage checks before freezing. Snapshot content integrity is checked when loaded.
- Older snapshots remain available; later review/input changes show a stale-snapshot notice rather than overwriting historical evidence.
- A code-by-transcript matrix of distinct retained spans, with count-to-frozen-passage links and a separate link to the current review record. Counts are not participant prevalence or importance; parent codes are not implicitly rolled up.
- Downloadable frozen JSON for local analysis. This is a versioned research artifact, not automatic findings or a released publication package.

## Verification

153 tests passed, one optional private-workbook test skipped. Both offline demos passed. Browser verification used two disposable synthetic studies: one exercised accept/edit/reject, export, freeze, matrix drill-down, mouse-selected span editing, stale-snapshot detection, and creation of a second snapshot; the other was created through the browser with synthetic fixtures, then previewed, run with mock coding, fully reviewed, exported, and frozen. Desktop and 390px layouts were inspected.

The browser study used the built-in synthetic fixture import. A fresh file-upload-to-paid-API walkthrough remains unverified. The existing 1A research decisions were not changed and no new external model calls were made.

## Next work

1. Explicit transcript-level no-evidence review checkpoint and source-subset selection.
2. Reviewed snapshot input adapter for configurable group synthesis; new versioned prompts, evidence citations, summary review, and stale-result tracking. Preserve the AMN reference prompts.
3. Frozen raw-run agreement/stability comparison with a declared unitization design, separate from adjudicated snapshots.
4. Versioned framework library, installation trials on Windows/macOS, and public demo packaging.

## Boundaries

The current analysis scope is one selected run and all transcripts in its frozen plan. It does not merge repeated model runs, infer metadata groups, generate themes, run synthesis, or compute agreement statistics. A local snapshot is not cryptographically authenticated against a malicious local operator. Full provenance remains inspectable; application checks detect ordinary source/output drift.

Later September 10 increment: selected-transcript snapshots now record exclusions;
raw-run comparison and synthesis-input preparation are implemented. The earlier
full-cohort-only limitation is superseded. See
[updated checkpoint](autonomous_checkpoint_2026-09-10.md).
