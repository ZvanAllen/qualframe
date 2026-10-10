# Evaluating against a historical human-reviewed analysis

Status: proposed comparison protocol, 12 September 2026. This is the selected design for the first CFIR methods/evaluation paper. New independent human coding is optional future work, not a requirement for this design. The private archive has been inspected offline; a general archival-reference importer and completed research comparisons are not implied.

## Study question and claim boundary

Evaluate whether a frozen AI-assisted CFIR workflow produces reproducible, traceable outputs, how model and effort settings affect those outputs, and how they agree with a specified historical analysis reviewed by the original research team. Describe that comparator as **historical human-reviewed, AI-assisted analysis**. Review of an AI-assisted analysis is meaningful human work even when per-code decision logs were not retained.

The archive does not establish independent human-only coding, inter-human reliability, exhaustive transcript coverage, or the causal benefit of adjudication. A new output absent from the archive may contain defensible additional evidence. An archival quotation that cannot be matched automatically is an unresolved source-linking observation, not proof of fabrication or a wrong interpretation.

Historical prompts and model families may overlap with the evaluated method. Disclose this dependence, iterative development on the corpus, and unavailable original settings. Agreement with that reference does not demonstrate general superiority of one model or external validity across studies.

## Preserve provenance without reconstructing decisions

Keep a private, versioned reference manifest containing:

- Original relative paths, selected version rationale, SHA-256 hashes, file sizes and scope.
- A review-provenance statement attributed to its source: researcher attestation, manuscript description, retained comments or tracking records.
- Explicitly unknown fields, including per-item reviewers, decision times, pre-review outputs or complete model configuration where unavailable.
- Original analysis layer: participant coding, context-expanded evidence, group synthesis or cross-group synthesis.
- Source and codebook identities, extraction version, deterministic alias/hierarchy mapping, and derived record IDs.
- Source-link status and matching transformation for every selected quotation, with ambiguous and unmatched entries retained.
- Deduplication, truncation and coverage declarations; absence of a row is not a reviewed negative decision.

Preserve bytes where authorized and feasible, and verify private copies against the manifest. Source offsets added during import are newly derived bindings, not recovered historical annotations. Never convert the attestation into invented per-item accept events or backdate modern review actions.

## Compare equivalent layers

Project new labels to the historical parent constructs only for the archival comparison, using a frozen codebook hierarchy. Keep original labels and child-level results for new-run comparisons. Restrict the reference comparison to shared domains; report any addendum separately.

Prefer attributed participant evidence and group quotations over compressed cross-group quotation cells. Context-expanded quotations do not reconstruct the original coded span. Keep their source-linked coverage separate from model-proposed coding boundaries. A synthesized paragraph citing several participants must not be assigned wholesale to each participant.

Use exact matching and explicitly recorded whitespace/typographic normalization first. Case folding, page-marker removal and punctuation-only matching require separate sensitivity outputs. Semantic similarity must not silently create source offsets or merge distinct quotations. Record single, ambiguous and absent matches separately.

Deduplicate source/code/span combinations within each comparison layer while retaining multiplicity in the audit. Do not pool copies of the same evidence from participant, group and cross-group layers as independent support. Source-link coverage and resulting exclusions must appear beside every reference comparison.

## Candidate measurements

| Question | Measurement | Interpretation |
|---|---|---|
| Do repeated fresh runs agree? | Same-code one-to-one span-overlap F1, exact F1 and coded-text coverage Jaccard | Reproducibility under the frozen source, segmentation, code and model configuration |
| How does changing the model/effort change coding? | Paired per-transcript differences in agreement, output volume, completion, latency and cost | Method/configuration dependence; neither model is the reference truth |
| Is selected historical evidence recovered? | Matched historical items / eligible historical items | Recovery of the defined archival evidence set, not recall of all relevant transcript content |
| What fraction of new evidence matches the archive? | Matched new items / eligible new items | Agreement with the archive; unmatched new items are not automatically errors |
| Do common parent labels and source coverage agree? | Parent-code coverage, supported-label distributions and one-to-one set agreement under a declared context policy | Agreement after an explicit projection; not child-code or original-boundary accuracy |
| Do downstream summaries preserve their evidence relationships? | Valid source/group membership, missing/duplicate citations, declared domain coverage and export completion | Structural traceability, not semantic faithfulness |
| Do historical categorical findings agree? | Per-construct/group nominal valence agreement with a confusion table, where the same rating categories exist | Concordance with historical ratings; do not turn categories into an unrecorded strength scale |

For a fully inventoried finite eligible archive H, eligible new set P and one-to-one matches M, report M/H, M/P and 2M/(P+H), along with all three counts. A zero denominator is undefined; set F1 is undefined when both sets are empty and zero when just one is empty. The finite archival denominator can be complete even though the archive does not exhaust relevant transcript content. Missing archival files or unresolved extraction coverage require a subset label; they must not be called a complete reference.

Use exact/overlap span scoring primarily for comparisons between new coding runs with the same boundary policy. Historical context expansion can materially change overlap scores. For the archive, make evidence retrieval and declared code/coverage comparisons primary, and treat raw boundary overlap as a sensitivity analysis with that limitation.

Construct-presence agreement becomes uninformative when almost every construct is populated. Always show prevalence/support, and do not choose a headline metric because its value is high. Kappa/alpha requires shared units and an explicit rater/label design; generated rows are not aligned annotation units. See [Artstein and Poesio](https://aclanthology.org/J08-4004/) and [Marchal et al.](https://aclanthology.org/2022.coling-1.322/).

## Reporting without new human evaluation

Primary results may cover repeated-run stability, model/effort agreement, historical-reference concordance, structural validity and measured API performance. Semantic embedding similarity is exploratory textual similarity unless separately validated for the target judgment. Do not promote an uncalibrated AI judge to an independent human reference.

Do not report independent human accuracy, full-source omission rates, empirical accept/edit/reject rates, inter-human reliability, semantic correctness percentages, or researcher time savings without the corresponding evidence. Synthetic assumed acceptance remains a functional testing device. Standard methodological interpretation and manuscript preparation still require researcher effort; removing new annotation does not make the study effort-free.

Freeze the cohort, configurations, repeats, normalization, matching, eligibility and analysis before the new benchmark. Separate development sources from the new evaluation subset, while acknowledging historical corpus reuse. Summarize paired results at source level; repeated runs, overlapping quotations and all pairwise comparisons are dependent. Account for group structure and avoid treating the count of model calls as the statistical sample size.

The [independent-human protocol](human_reference_benchmark_protocol.md) remains an optional extension for broader accuracy, semantic-quality or workflow-efficiency claims. See [candidate metrics](benchmark_candidate_metrics.md) and [implemented metric contracts](benchmark_metric_notes.md). Study-specific records and real examples stay outside public documentation.
