# Synthetic browser/API verification — September 10, 2026

This verifies software behavior, not coding quality, scientific validity or a model
ranking. No private transcript or research adjudication was used in this round.
The operator identity "Synthetic API QA" denotes agent-performed fixture inspection,
not a human research evaluator or a reference-standard qualitative judgment.

The owner authorized up to USD5 each for OpenAI and Anthropic. The test used a
stricter USD5 combined ceiling in one separate synthetic study. Keys remained in
the local app process. No credential values were written to these records.

| Provider/model | Completed API responses | Recorded token cost (USD) |
|---|---:|---:|
| OpenAI gpt-5-nano-2025-08-07, minimal reasoning | 3 coding + 2 synthesis | 0.00057445 |
| Anthropic claude-haiku-4-5-20251001, temperature 0 | 3 coding + 1 synthesis | 0.00835100 |
| Combined | 9 | 0.00892545 |

Output limit: 4,000 tokens per request. Rates were checked against the official
[OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5-nano)
and [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing).
Costs use API-reported tokens and saved prices, including a malformed response;
they are not invoice reconciliation. One additional OpenAI connection attempt was
blocked by the network-disabled execution sandbox. OS-level socket-denial evidence
was saved and an append-only zero-token reconciliation recorded before retrying.
The original request reservation was preserved. No model retry was automatic.

## What was exercised

- Browser creation of a synthetic study with the starter codebook and two fixtures.
- Fresh upload through the browser file picker of a third, wholly fictional TXT.
- Provider configuration, dated prices, governed transfer and spending approval,
  no-call plan, background paid execution and automatic evidence preparation.
- Source-highlighted review of the uploaded transcript: three proposals per provider.
  Both sets were accepted during synthetic QA, then frozen as explicit one-source
  subsets. The two other fixtures were excluded from both synthesis plans.
- Three proposed synthesis statements per provider, citation/code/scope validation,
  statement editing, acceptance and immutable reviewed JSON exports. These edits
  exercise the review mechanism; they are not independent scientific adjudication.
- Full suite: 169 passed, 1 skipped on Windows/Python 3.11. Both offline demos passed.
  One generic-demo directory rename first hit a transient Windows access-denied
  error; a fresh run succeeded. No clean-machine or macOS claim is made.
- Desktop and 390px browser checks: stacked source/summary cards, usable decision
  controls, complete-review progress, summary navigation and export links. No
  document-level horizontal overflow. The original research workspace was reopened
  with its existing six resolved decisions preserved; no research decisions were made here.

## Failures and limitations observed

OpenAI produced an empty invalid coding row for one starter fixture and an empty,
unparsed table for the other. The uploaded transcript produced three valid exact
quotations. The malformed row was rejected during fixture QA; the unparsed source
remained incomplete and was excluded from synthesis. Anthropic produced seven
source-valid proposals across all three transcripts. Its first two fixture sources
remain unreviewed. Full-cohort comparison is deliberately blocked because the
OpenAI cohort includes an incomplete output. No agreement score is claimed here.

The initial unconstrained OpenAI synthesis contained a JSON comment and failed
parsing after usage was recorded. Its raw response and charge remain preserved;
it never became a reviewable or exportable synthesis. Native JSON-schema constraints
were then implemented for both providers. A separately approved OpenAI job and the
Anthropic job passed structural and citation-membership checks without response repair.

Valid structure did not guarantee well-bounded interpretation. Proposed summaries
introduced wording about multiple individuals or encounters from a single account,
or added a care context not established by the selected passage. Synthetic QA edits
narrowed those claims. This motivates evaluation of semantic support, scope errors
and omitted evidence alongside agreement and stability. These examples are too few
and not independently assessed to report rates or compare model quality.

Browser testing found and fixed invalid edit offsets blocking Reject/Decide later,
and restart rendering that called a previously attempted run an untouched plan.
Remaining work includes empty-output review, metadata grouping, failed multi-scope
synthesis recovery, richer export formats, repeated-run orchestration and pilot testing.

## Local evidence inventory

The ignored study `studies/synthesis-api-20260910` contains source imports, provider
versions, run plans, request records, responses, evidence actions, snapshots,
synthesis decisions and exports. Coding runs: `20260910T184239Z` (OpenAI) and
`20260910T185203Z` (Anthropic). Synthesis jobs remain under each coding run's
`analysis/synthesis` directory. The local receipt is
`artifacts/api-synthesis-verification-20260910.json`. Generated runs and credentials
are excluded from the public source archive. Original AMN prompts are unchanged.
