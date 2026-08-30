# Prompt inventory

The files in `prompts/cfir/final/` were extracted verbatim from the supplied `CFIR Prompts.xlsx` workbook.

Interpretation rule used:
- final prompts were taken from the rightmost colored prompt cell in each task row on `Sheet1`
- black-filled cells were treated as older/retired prompt versions

## Inventory

### Row 2 — Coding each transcript to CFIR
- Source cell: `Sheet1!C2`
- File: `prompts/cfir/final/01_row2_coding_each_transcript_to_cfir_ambiguous_variant.md`
- Notes: Task label suggests transcript-level coding, but the extracted final prompt text behaves like a workbook-mediated parent-construct roll-up prompt. Treat as an archived/ambiguous variant until the team confirms whether a separate final transcript-coding prompt exists.

### Row 3 — Synthesizing any subconstructs up to their constructs for EACH participant
- Source cell: `Sheet1!C3`
- File: `prompts/cfir/final/02_row3_rollup_subconstructs_to_parent_constructs.md`
- Notes: Recommended default prompt for participant-level subconstruct-to-parent-construct roll-up.

### Row 4 — Synthesize at the network level
- Source cell: `Sheet1!H4`
- File: `prompts/cfir/final/03_row4_synthesize_at_network_level.md`
- Notes: Recommended default prompt for participant-to-network synthesis.

### Row 5 — Synthesize across networks
- Source cell: `Sheet1!D5`
- File: `prompts/cfir/final/04_row5_synthesize_across_networks.md`
- Notes: Recommended default prompt for domain-specific cross-network synthesis.

### Row 6 — Rate each construct using the rating scale
- Source cell: `Sheet1!B6`
- File: `prompts/cfir/final/05_row6_rate_each_construct_using_rating_scale.md`
- Notes: Recommended rating-stage prompt; depends on a separate rating rubric workbook.

### Row 7 — Adding context to quotes at the individual transcript level
- Source cell: `Sheet1!B7`
- File: `prompts/cfir/final/06_row7_add_context_to_quotes.md`
- Notes: Optional pre-processing prompt for quote-context enrichment at the participant transcript level.

## Recommended default mapping for v0.1

- `participant_parent_construct_rollup` → row 3 prompt
- `participant_to_network_synthesis` → row 4 prompt
- `cross_network_synthesis` → row 5 prompt
- `construct_rating` → row 6 prompt
- `quote_context_enrichment` → row 7 prompt

## Open issue

The row-2 task label says `Coding each transcript to CFIR`, but the extracted final prompt text behaves like a workbook-mediated roll-up task. The repo therefore treats it as an archived/ambiguous variant until the team confirms whether a separate final transcript-coding prompt should be added.