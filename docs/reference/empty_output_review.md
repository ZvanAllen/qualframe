# Explicit review of zero-proposal coding outputs

A completed coding response with no proposals now has a source-level review
checkpoint. Study progress links to the original transcript, the frozen codebook,
and the original model response. The researcher can confirm zero proposals,
request a new coding run, or defer. Confirmation also requires an explicit check
that the source was read with the codebook and a recorded reason. The researcher
name is remembered for later reviews.

Confirmation records that this particular reviewed output retains no coded
passages. It does not establish that the codebook concepts are absent from the
transcript. Requesting new coding records an outstanding decision; it does not
submit another provider request or change the previous output.

## Structural gate

The parser now preserves an explicit header-only Markdown table as a sheet with
zero rows. Plain prose, missing output, missing separators, malformed headers,
empty placeholder rows, and unfinished output are not accepted as empty tables.
The checkpoint independently checks original response text against the frozen
framework's required columns and, when enabled, the stage's output schema.
A schema requiring data rows still blocks a wholly empty output. Each declared
partition/domain needs its own complete response. Existing CFIR artifacts that
filled unparsed domain responses with empty lists do not bypass this check.

The conservative first implementation requires a complete header-only table with
no narrative mixed into the empty response. Historical outputs are never rewritten
or silently reclassified from a failure into a reviewed absence. Unrecognized
response shapes remain blocked for inspection or a new run. Populated coding
rows with no prepared evidence records also cannot use this checkpoint.

## Provenance and downstream use

Decisions append to `review_queue/<run>/empty_outputs/actions.jsonl`. Each decision
binds the original source bytes and extracted text, coding artifact bytes and
prompt hashes, run-plan hash, review-index hash, and configuration identity.
A decision from an earlier browser page is rejected if those inputs changed.
The latest matching decision controls progress; defer and needs-new-coding keep
the source outstanding. Earlier actions remain readable.

Only explicit current confirmations count as fully reviewed. Reviewed snapshots
can include these sources with zero retained spans; their source-level decisions
and full decision history are kept separately from code-level absence records,
rejected proposals, and exact evidence. Excluded source paths remain recorded.
Changes to included decisions or inputs make the previous snapshot stale; changes
to an excluded transcript's decision do not alter that snapshot.

## Browser integration

- GET `/empty-output?run_id=...&source=...` calls
  `empty_output_ui.render_empty_output_review(app, run_id, source_path, message)`.
- POST `/empty-output/review` calls `handle_empty_output_action(app, form)` and
  redirects to the same run/source. The helper returns `(run_id, message)`.
- Fields: `run_id`, `study_identity`, `source`, `binding`, `reviewer`, `rationale`,
  `decision` (`confirm_empty`, `needs_recoding`, or `defer`), and
  `source_checked=yes` for confirmation only.

The core append helper supports dry-run validation without writing a decision.
No provider requests are made by this workflow. Ordinary tests use synthetic
transcripts and an in-process provider returning explicit empty tables.
