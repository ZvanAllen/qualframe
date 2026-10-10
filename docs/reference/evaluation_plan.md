# Evaluation plan

This plan now has two layers: a generic directed-analysis product evaluation and the existing CFIR/AMN reference evaluation. See `evaluation_protocol.md` for method-specific statistical cautions and `model_evaluation_and_cost_control.md` for provider screening and spending controls.

## Why evaluation matters

The next methodological advance is not only to automate the workflow, but to measure where automation helps and where it still needs human repair.

## Recommended comparisons

1. human-only workflow
2. AI-assisted workflow with current staged prompts
3. AI-assisted workflow with structured response schemas
4. two-model adjudication workflow
5. workbook-first vs transcript-first pipelines
6. single-label vs multi-label coding where methodologically appropriate
7. full-codebook vs top-level-category partitioning
8. complete vs sampled post-calibration review

## Candidate measures

### Process measures
- time to first draft output
- time to final adjudicated output
- number of review flags
- number of reruns per stage
- number of prompt changes required

### Output quality measures
- source traceability pass rate
- valence exclusivity pass rate
- sheet/column compliance
- construct naming accuracy
- human-rated faithfulness to evidence
- proportion of outputs requiring substantive rewrite

### Comparative measures
- agreement between human and AI-assisted outputs
- agreement across models
- agreement before and after quote-context enrichment
- exact evidence-span validity
- unitization or segmentation disagreement
- per-code precision and recall where defensible
- human accept/edit/reject/defer rates
- review time, latency, and cost

## Evaluation corpora

### Generic product corpus

Build a checked-in synthetic challenge set with flat and hierarchical codebooks, single-label and multi-label cases, boundary ambiguity, rare codes, unsupported-evidence traps, metadata groups, and known review-queue triggers.

Use a separately governed, approved human-coded calibration sample for method validation. Do not commit raw research transcripts or sensitive derived evidence.

### CFIR reference corpus

Build a small de-identified benchmark set with:
- 3 to 5 participant workbooks
- 2 network-level synthesis examples
- 1 cross-network AMN example
- 1 rating example

## Reporting recommendation

Every evaluation run should capture:
- framework spec version
- pipeline version
- prompt-set version
- provider/model metadata
- input hashes
- reviewer decisions
- coding and partition policies
- usage and cost records
- pricing snapshot
