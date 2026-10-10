# API smoke-test results — September 8, 2026

## Current result

Both corrected keys successfully authenticated. One coding call completed through each real API on SYN-01, using the approved pinned models and original prepared configuration. API connectivity, response parsing, token-usage accounting and raw Excel export worked. Exact-offset validity failed for both models, so the remaining two planned calls were not sent, following the stop-on-malformed-output rule.

| Check | OpenAI GPT-5.4 nano | Anthropic Haiku 4.5 |
|---|---:|---:|
| Completed coding calls | 1 | 1 |
| Parsed coding rows | 4 | 2 |
| Exact quotations found in source | 4 | 2 |
| Valid model-proposed character spans | 0 | 0 |
| Explicitly flagged evidence rows after validation fix | 4 | 2 |
| Rows preserved in raw Excel export | 4 | 2 |
| Reviewed evidence export blocked | Yes | Yes |
| Recorded token cost, USD | 0.00111065 | 0.001571 |

Combined recorded token cost: **USD 0.00268165** against the approved USD 1 ceiling. This is calculated from API-reported token counts and saved prices, not an invoice reconciliation. The earlier HTTP 401 was separately resolved as zero model tokens on the evidence of authentication rejection before inference; its reservation and audit trail remain preserved. No uncertainty was cleared by deleting a record.

## Defects exposed and handled

1. The legacy transcript filter failed to recognize a hyphenated exact filename and initially produced an empty run. The runner now supports exact stems and rejects unmatched filters before provider construction.
2. Both models used 2/2 and 3/3 as Evidence Start/End, apparently treating them as sentence/unit numbers. Those are invalid empty character spans. Their quotations occur verbatim, but quotation matching alone is not validated model-proposed offsets.
3. The evidence-index builder created no span but also omitted an explicit validation issue for start >= end or empty text. It now flags those conditions. Three regression cases cover empty/reversed-invalid offsets and empty evidence. Earlier index snapshots are preserved next to the regenerated indexes.
4. The existing v1 contract prompt names Evidence Start/End but never defines zero-based character offsets, exclusive ends, or the exact text coordinate system. The original version was preserved; it should be replaced by a new version before additional paid coding validation.

Reviewed evidence cannot be accepted or exported while invalid/unresolved. Raw Excel exports intentionally preserve the original model rows for inspection; they are not validated research outputs. No human adjudication was fabricated and no automatic quotation-to-offset repair was substituted for model output.

## Next implementation gate

Create a versioned evidence-location contract that explicitly defines offsets against normalized source text. Prefer deterministic source anchoring with preserved raw model proposals and clearly marked repairs, or stable source units, over relying on models to count characters. Ambiguous or repeated quotations must remain review items. Test the new contract offline before using the two remaining planned calls under the existing budget. Also define whether parents and children should both be coded: OpenAI emitted parent plus child labels while Anthropic emitted only children in this tiny fixture. This is a policy choice, not an established model-performance difference.

These are software smoke tests, not publishable agreement, stability, accuracy, or superiority results. Only one synthetic source text was exercised per provider. No real research transcripts were sent and nothing was published.

## Local artifacts

- Machine-readable result: artifacts/api_test_results_20260908.json.
- Original responses, normalized usage, costs, approval and reconciliation: studies/api-verification-{openai,anthropic}-20260907.
- Raw exports: each study's exports/api-smoke-pending-approval folder.

Final offline verification: 134 tests passed, one skipped; both offline demos passed.
