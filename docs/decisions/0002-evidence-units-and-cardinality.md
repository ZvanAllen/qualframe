# 0002: Evidence units and coding cardinality

- Status: accepted
- Date: 2026-08-02

## Decision

The canonical analytic object is an exact evidence span with stable source offsets. Meaning units may be model-proposed, automatically segmented, researcher-presegmented, or edited during review.

Projects configure `single_label` or `multi_label` coding. Overlapping spans are configurable. Exact evidence, surrounding context, code assignments, and model rationale remain separate fields.

## Consequences

Workbook rows cannot remain the canonical internal representation. Reviewer edits create derived records without changing source transcripts or raw provider responses.
