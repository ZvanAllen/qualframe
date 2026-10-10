# QualFrame evaluation protocol

Status: historical CFIR/AMN manuscript planning scaffold. The candidate measures, AI-auditing design and manuscript tables below are not claims that those analyses were completed or validated. Current implemented span metrics and prospective design choices are documented in [candidate benchmark metrics](benchmark_candidate_metrics.md), [metric definitions](benchmark_metric_notes.md) and [human-reference preparation](human_reference_benchmark_protocol.md).

## Scope

The existing levels and metrics below define the CFIR/AMN reference evaluation. They do not define a universal directed-analysis benchmark. Generic product evaluation uses the stable evidence, assignment, calibration, review, usage, and cost objects in `domain_model.md`, with method-specific metrics declared per study.

## Study purpose

Planned purpose: compare frozen GPT, Claude, and Gemini outputs under a declared CFIR pipeline and evaluation design. Historical outputs with changed prompts or incomplete configuration provenance support exploratory diagnostics; they do not establish a controlled model comparison.

## Analytic levels

### Level A: transcript-level coded workbook

Unit: a model-generated coded workbook for one transcript.

### Level B: network-level aggregated workbook

Unit: a model-generated network synthesis workbook.

### Level C: cross-network aggregated workbook

Unit: a construct-level row in the final cross-network workbook.

## Evaluation architecture

1. deterministic quantitative metrics
2. blinded AI rubric-based auditing
3. targeted human adjudication subset

## Normalization requirements

- map literal aliases to canonical CFIR labels only under an explicit, versioned rule; retain original labels and unmapped/ambiguous exclusions
- normalize domain/sheet notation only when identity is unambiguous; never replace conflicting assignments with the predominant domain
- retain placeholder and absence classifications in an audit, with declared inclusion/exclusion denominators rather than silent deletion
- preserve stable row IDs
- preserve source span identifiers where available

Default literal/typographic quotation matching and opt-in casefold-only sensitivity results have separate policy identities. Semantic remapping, fuzzy passage repair and punctuation/word-sequence matching are not default benchmark normalization. A high score in an included subset does not validate excluded proposals or establish whole-output agreement.

## Transcript-level metrics

- total rows
- unique normalized constructs
- rows per domain
- construct presence matrix
- pairwise Jaccard similarity
- candidate pairwise Cohen's kappa, only after a common unit and rater design are frozen
- mean / median quote length
- rows per 1,000 transcript words
- duplicate quote ratio
- repeated quote use within same construct
- repeated quote use across multiple constructs
- human accept/edit/reject rate
- median review time

## Network-level metrics

- constructs retained into synthesis
- evidence compression ratio
- pairwise valence agreement
- candidate pairwise valence kappa, with shared units, missingness and categories declared
- explanation length
- number of source rows/quotes referenced

## Cross-network metrics

- constructs retained
- number of networks represented per construct
- Jaccard similarity of facilitator/barrier/mixed/neutral network sets
- percentage agreement on overall valence
- candidate kappa on overall valence, under an explicit common-unit design
- directional instability rate
- count of constructs requiring manual repair

## AI rubric dimensions

Transcript and network levels:
- framework_fidelity
- evidence_faithfulness
- completeness
- parsimony_nonredundancy
- boundary_handling
- traceability
- downstream_usefulness

Cross-network additions:
- valence_defensibility
- network_grouping_defensibility

## Seeded-error evaluator validation

Build a challenge set containing:
- wrong construct assignment
- unsupported explanation
- duplicate evidence represented as distinct findings
- missing major determinant
- wrong valence
- wrong network placement

Summarize evaluator sensitivity by error type before relying on the evaluator in the main study.

## Human adjudication subset

Review:
- stratified subset from each level
- all high-disagreement cases
- all evaluator-flagged major concerns

Track:
- accept/edit/reject
- time
- brief reason for major changes

## Primary manuscript outputs

- transcript comparison table
- network valence agreement table
- cross-network instability table
- AI rubric score table
- seeded-error validation table
- human adjudication table

## Generic directed-analysis extension

Every non-CFIR benchmark must declare:

- analysis method and codebook version
- unitization and segmentation policy
- single-label or multi-label policy
- overlapping-span policy
- codebook partition strategy
- human-coded calibration sampling and adjudication status
- provider/model configurations and pricing snapshot
- per-code and aggregate metrics appropriate to the rater design
- exact-span validity and evidence-faithfulness rules
- review burden, latency, failures, and cost

Do not compare models only on aggregate accuracy. Report rare-code behavior, boundary errors, unsupported evidence, cardinality errors, and human revision burden.

Kappa or alpha requires a defensible common unit and rater design. When model and human segment boundaries differ, report unitization disagreement separately rather than forcing misleading agreement statistics.

Functional smoke tests with the cheapest model verify system operation only. Model configurations are promoted for analysis use only after the sequential process in `model_evaluation_and_cost_control.md` and complete calibration review.

## September 11 feasibility evidence

The private three-transcript pilot completes the configured five-stage test sequence through a composite of three configurations: coding/roll-ups at 24k/medium, one context output at 48k/medium, and remaining context/synthesis at 48k/low. Its 12 outputs and preserved attempt history establish functional execution under a test-only acceptance assumption. The preserved network prompt specifies five CFIR domains and excludes Outcomes Addendum; the final cross-network prompt explicitly targets Innovation only. Completing these configured calls does not establish synthesis across all domains. They do not fulfill the manuscript's independent human-reference, semantic-audit or controlled repeated-run designs. Detailed real-data results remain private; prospective evaluation still needs a frozen protocol and independently prepared references. Global QA rules were not aligned with the synthesis output contracts; retain their historical flags without treating them as generated-column deviations or semantic errors. Version stage-specific QA and schema contracts to match the preserved stage prompts, then plan explicit domain scope for any broader synthesis before further research synthesis. Preserve existing prompts/results; any all-domain extension requires a separately declared prompt/pipeline version.
