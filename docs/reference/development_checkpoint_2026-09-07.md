# Development checkpoint — September 7, 2026

## Baseline

Development now uses a clean clone of the public history at `public_app/` in the enclosing workspace, starting at `ffa4b44`. The historical research workspace and previous release snapshot are preserved. Source/tests/configuration/prompts were inventoried against the historical workspace; only generated egg-info metadata was historical-only. No missing product module required copying from the research archive. The public version's UI and source-file/extracted-text hash fix remain present.

See `baseline_inventory_2026-09-07.json` for compared paths. The inventory is a planning checkpoint, not an immutable release manifest of the ongoing changes.

## Implemented increment

- Excel codebook upload, worksheet/header selection, column mapping, validated preview, and explicit version activation.
- Original workbook and conversion provenance retained alongside normalized codebook versions.
- Duplicate IDs, unknown/cyclic hierarchy, formulas, missing values, duplicate mappings, altered previews, and repeated commits checked.
- Optional study group field in transcript import; generic studies already have no mandatory roll-up/synthesis stages.
- Context unit editing (sentences, paragraphs, characters), exact-only zero context, and expansion around multi-sentence spans. Paragraphs follow extracted source line boundaries; sentence splitting is a deterministic heuristic.
- Canonical-document scope updated to agreement/stability first, Windows/macOS, one operator per study, and November 11 delivery.
- macOS added to the offline CI matrix; remote execution and clean macOS installation testing remain pending.

## Evaluation design follow-up

The supplied manuscript is a proposed comparative design with unpopulated results. Its methodological themes are useful, but completed-run/validation language must be reconciled with actual evidence before use. Preserve original model decisions during normalization, define shared analysis units independent of model IDs, distinguish API repeatability from deterministic report computation, and specify evaluator validation separately from coding robustness. The private manuscript is not bundled with this checkout.

## Next increment

Complete generic context/aggregation settings and integrate provider/budget configuration with browser execution. Follow with a synthetic live end-to-end verification under an explicitly approved ceiling, then the agreement/stability runner. Do not infer that those later milestones are complete from this checkpoint.

## Provider preparation increment

Provider/model, standard output settings, dated pricing, spending ceiling, and governance confirmation can now be saved through the local interface. Session-only credentials are excluded from persistent study files. Original and revised project configurations are retained; a changed configuration invalidates old preflight plans. Browser requests reject unexpected Host/Origin values. Unknown provider names fail rather than substituting mock output. New generic studies reference complete review. Live browser execution, reasoning/effort settings, retry accounting, and live validation remain pending.

## Verification

- Windows local suite: 117 passed, 1 skipped.
- Both offline demos passed after provider preparation changes: five-stage cached run exported nine workbooks; generic demo materialized four valid evidence records from two synthetic transcripts.
- Browser: synthetic Excel upload, mapping, validation, and activation; paragraph-context version editing; synthetic provider/budget save without a key or API call. Desktop and 390-pixel layouts inspected; narrow forms changed to one column.
- New modules passed targeted lint; Git whitespace check passed.
- Automated public-content audit passed (167 selected files at this checkpoint); no publication performed.
- macOS CI is configured but has not been run from this local change. No live API verification occurred.


## Paid-execution increment — September 7, 2026

Supersedes earlier pending statements about browser provider execution, effort controls and attempt accounting: OpenAI/Anthropic paid browser dispatch is implemented with explicit current-plan approval, session-key checks and one active app job. OpenAI Responses/reasoning effort and Anthropic effort controls are versioned and retained in the editor. Automatic retries are disabled for these two adapters; durable request reservations, unresolved-usage blocking, completion-status capture, and audited command-line reconciliation are implemented. See [paid execution](paid_execution.md).

Offline verification: 130 tests passed, one skipped; both synthetic demos passed (five-stage cached CFIR with nine Excel exports, generic mock study with four valid evidence records). Current live API behavior remains unverified. Two synthetic preflights are prepared with separate USD 0.50 ceilings, pending owner approval and keys. No spending or publishing occurred. macOS execution, an installed-user trial, and the scientific benchmark remain pending.

Browser QA confirmed saved provider values, a fresh preflight from an existing study, and legible desktop/390px-wide approval controls. No paid-submit action was taken. Final release dry-run screened 169 selected public files with no findings.


## API test update — September 8

Owner approved USD 1 total for the prepared synthetic verification. OpenAI was not submitted because its key was unavailable; one Anthropic request returned HTTP 401, with no output or token usage. No retry or second transcript call followed. Current live coding remains unverified. The exact-stem transcript filter was repaired and unmatched filters now fail before a provider call. See [test checkpoint](api_smoke_checkpoint_2026-09-08.md).


## Corrected-key test results — September 8

Both providers now authenticate and one real coding call per provider completed. Combined recorded token cost: USD 0.00268165. Parsing/raw Excel exports succeeded, but all six coding rows had invalid model-proposed character offsets. The missing validation warning was fixed and regression-tested; reviewed exports remain blocked. Two remaining planned calls were not sent. This supersedes the earlier credential blocker, but does not establish valid end-to-end evidence coding. See [current results](api_smoke_results_2026-09-08.md).


## Exact-quotation contract — September 8

New generic studies now use a version 2 exact-quotation contract. Unique matches produce source-validated automatic spans; repeated/missing matches remain flagged. Raw model locations and the artifact's contract are retained, and the reviewer sees the location method. Existing v1 evidence is not repaired retroactively. See [decision 0007](../decisions/0007-exact-quotation-anchoring.md).

The two remaining approved live calls completed: each provider returned two uniquely anchored source-valid coding rows. Across v1 and v2, four successful coding calls cost USD 0.0050812 in recorded token charges (OpenAI USD 0.0016042; Anthropic USD 0.003477). No more live calls were sent. These tiny synthetic checks validate this software path, not agreement/stability or qualitative accuracy. Live evidence is left unreviewed for the owner to inspect.

Final checks for the quotation-anchoring increment: 142 tests passed, one skipped; both offline demos passed; the public release dry-run screened 178 files with no findings. Browser review shows the automatic anchoring notice, valid evidence, and unreviewed decisions. The app is being opened on the OpenAI v2 synthetic study for owner exploration; its API key is not retained in the browsing server process.
