# Preparing an independent human reference

Status: proposed study procedure and data contract, not an implemented human-reference import feature.

Scope update, 12 September 2026: this remains an optional extension for claims requiring independent human coding. The first CFIR paper will use the [historical human-reviewed comparator protocol](archival_comparator_protocol.md), with no new human annotation required and narrower agreement/reproducibility claims. Do not describe the archived AI-assisted analysis as independent human-only coding.

## Before coding

Freeze the source extraction method and hashes, CFIR codebook version, unitization rules, coding cardinality, context policy, and the permitted use of parent/subconstruct labels. Record how a reviewer should handle uncertain, absent, contradictory and multiply coded evidence. The archived model outputs must not be visible to researchers providing independent reference coding.

Separate calibration material from the evaluation cohort. Two researchers independently code the full evaluation sources, including uncoded regions; preserve their first-pass annotations. Record training and CFIR experience. A third discussion/adjudication step can produce a consensus reference, with disagreements and rationales retained. Consensus is an operational study reference, not a claim that interpretation has a single objectively correct answer.

## Minimal future import contract

| File or field | Purpose |
|---|---|
| Source manifest | Stable source ID, original file hash, extracted-text hash and extraction version |
| Annotation identity | Unique annotation ID, anonymized coder ID, coding session/version |
| Source span | Source ID, zero-based start, exclusive end, exact source text; keep display context separately |
| Code assignment | Frozen codebook ID/version and exact code ID; one row per code on a span |
| Origin | independent_human, consensus, model, or human_edit_of_model; never infer from acceptance |
| Coverage declaration | Sources/units fully inspected, genuinely empty decisions, incomplete/missing observations |
| Reference version | Immutable ID linking annotations, source set, codebook, instructions and consensus procedure |
| Review rationale | Optional uncertainty/disagreement note and consensus evidence; retain original records |

A blank annotation file is not evidence that a source contains no applicable codes. Require a separate completed-coverage declaration before treating it as an empty set. An unknown source, edited transcript, offset mismatch, unknown code or duplicate annotation identity must fail validation. Exact duplicates of source/code/start/end can be counted once for set metrics while remaining visible as duplicates. Legitimate multiple codes on one passage remain separate assignments.

## Planned comparisons

- Human A versus human B before consensus: describe the reference task's own annotation variability.
- Each model/repeat versus each human coder: preserve variability between individual researchers.
- Each model/repeat versus consensus: report reference-relative precision, recall and F1 under the frozen exact/overlap rules.
- Assisted versus independent workflow: a separate comparison of time, edits, missed passages and semantic quality, using an allocation/order design that accounts for learning and recall.

For model-reference matching, let M be matched pairs, P model spans and H reference spans. Precision is M/P, recall M/H, and F1 is 2M/(P+H). Both-empty F1 is undefined; one-empty F1 is zero. If the reference's coverage is incomplete, recall and completeness cannot be computed for the unreviewed material. Invalid model proposals must remain reported alongside valid-subset scores; do not silently discard them and call the remaining score whole-output accuracy.

Kappa/alpha requires a separate declared common-unit design. Do not line up independent span rows by position or discretize every source character into an independent observation. Chance-corrected results must identify units, rater structure, label multiplicity, missing states and prevalence effects. [Artstein and Poesio, 2008](https://aclanthology.org/J08-4004/), [Marchal et al., 2022](https://aclanthology.org/2022.coling-1.322/).

## What assumed acceptance means

The AMN functional pilot assumes model proposals accepted to exercise downstream stages. Those assumptions are neither independent human annotations nor measured acceptance decisions. They must not enter human-reference precision/recall, human-human agreement, empirical accept rates, or researcher time-savings results.

See [candidate metrics](benchmark_candidate_metrics.md) and [implemented span metric definitions](benchmark_metric_notes.md).
