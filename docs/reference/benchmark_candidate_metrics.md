# Candidate benchmark protocol for QualFrame

Status: candidate protocol and implemented descriptive span scorer, 11 September 2026. Thresholds and rubric anchors below are choices to test before freezing a publication protocol. The private AMN pilot is a feasibility exercise. It does not establish a validated instrument, a model ranking, or human-reference accuracy.

Scope update, 12 September 2026: the selected first-paper design uses a [historical human-reviewed, AI-assisted comparator](archival_comparator_protocol.md). New independent human coding, blinded semantic ratings and timed workflow evaluation below are optional extensions for broader claims. The current paper focuses on reproducibility, model/effort agreement, historical-reference concordance and measured operational performance. No new human annotation is required for that narrower design.

## Recommended measurement set

Use a small dashboard of distinct measures rather than a single quality score. Agreement can be high when both coders make the same mistake; valid quotations can still have inappropriate codes.

| Dimension | Candidate primary measure | Supporting measures and denominator | Current status |
|---|---|---|---|
| Output and evidence validity | Included proposals / (included + excluded proposals) | Report both counts; valid absence declarations separately; missing/unparsed domains, unknown codes, unanchored/ambiguous quotations and duplicates | Implemented checks and private pilot audit |
| Passage and code agreement | Same-code, one-to-one overlap F1 at span IoU >= 0.50 | Exact F1; IoU 0.25 and 0.75 sensitivity; left/right matched fractions; per-code and per-transcript support | Implemented local scorer |
| Coded-text coverage | Same-code character-coverage Jaccard | Transcript-code set Jaccard and code frequencies, with both-empty results undefined | Existing comparator |
| Repeated-run stability | Distribution of the above across repeated outputs under a frozen configuration | Every planned attempt, failures, exclusions and costs; per-transcript results | Repeated-run reports implemented; real controlled repeats still needed |
| Agreement with independent human coding | Reference-relative precision, recall and F1 using the same declared span rule | Two independent human coders before consensus, human-human agreement, then a separately adjudicated reference | Reference material and import protocol needed |
| Semantic quality | Blinded expert ratings of construct fit and contextual support | Completeness, redundancy, boundary handling, defensible valence and synthesis claims; anchored ordinal rubric plus not assessable | Candidate rubric; no validated automated judge |
| Researcher burden and cost | Active review minutes per 1,000 source words and per transcript | Accept/edit/reject/defer counts, added missed passages, editing extent, all API attempt costs, latency and failure rate | Cost/action records exist; active-time instrumentation and prospective study needed |
| Synthesis quality | Supported claims / assessable claims under blinded review | Citation membership, source/group preservation, omitted or contradictory evidence, barrier/facilitator reversals | Structural checks exist; semantic review required |

The candidate primary span measure accepts boundary differences only when the same code and source agree and the intersection is at least half the union of the two passages. A maximum-cardinality one-to-one matching prevents a long excerpt matching several shorter excerpts and inflating agreement. Report 0.25/0.50/0.75 together; these are sensitivity choices, not established CFIR correctness thresholds. Exact F1 and exact Jaccard express the same ordering and should not be counted as independent confirmation. [Chen et al., 2023](https://aclanthology.org/2023.emnlp-main.795/).

The validity fraction is `included / (included + excluded)` under the report's declared source/code/quotation policy. Valid absence declarations are outside this denominator, and duplicates remain in proposal counts while contributing only once to span-set support. A zero denominator is undefined. Missing or failed outputs remain unavailable rather than becoming valid empty outputs. This measures scoring eligibility, not correctness, completeness or semantic support; report each side's counts alongside its overlap scores.

Report pooled matched-count F1, macro average over codes with at least one span in either output, and each transcript's result. Always display support for rare codes and counts excluded from scoring. A large pool of jointly absent codes must not inflate agreement. Separate boundary agreement from code agreement because segmentation differences can substantially change apparent agreement. [Lee and Sun, 2019](https://arxiv.org/abs/1904.09557).

## Three comparisons that need different designs

1. **Model versus model:** same source files, codebook, prompt contract and analysis method; deliberately change the model/effort factor. A historical comparison with changed prompts or an unknown frozen configuration is exploratory. No side is labelled truth.
2. **Run versus repeated run:** freeze provider snapshot, effort, all other settings, codebook, prompt hashes and cohort; generate separate repeats. Temperature settings alone do not establish determinism. Report all attempts, not just the most successful pair.
3. **AI versus human:** human coders work independently from the full transcript, including passages the AI missed. Preserve their original coding before consensus. Compare human-human and AI-human results under the same unit/matching policy; describe consensus as the study reference, not objective truth. Review of AI suggestions can instead assess an assisted workflow, but does not by itself measure independent recall.

Do not compute ordinary kappa by aligning generated row numbers. Kappa/alpha needs a common unit, a rater design and a declared treatment of overlapping labels, missing observations and chance agreement. A later fixed-unit study could freeze shared meaning units and retain a binary vector for each code. Transcript-by-code presence is a coarse common unit, but it is not passage agreement. Unitizing alpha is a separate method, not an automatic replacement for nominal alpha. [Artstein and Poesio, 2008](https://aclanthology.org/J08-4004/), [Marchal et al., 2022](https://aclanthology.org/2022.coling-1.322/).

## Candidate semantic review rubric

Start with four observable ratings and retain structured reasons. Use three anchored categories, plus **not assessable**. A score of 2 means the stated criterion is met, 1 means a material but repairable problem, and 0 means a major failure. These are provisional anchors to calibrate with researchers, not interval-scaled numbers to combine into a total.

| Criterion | 2: criterion met | 1: repair needed | 0: major failure |
|---|---|---|---|
| Construct fit | Passage supports the assigned construct under the frozen definition | Construct is plausible but a boundary/definition ambiguity needs correction | Assigned construct is unsupported or contradicted |
| Contextual support | Quotation and surrounding context support the interpretation | Context changes qualification, actor or scope enough to require an edit | Interpretation reverses or invents the source meaning |
| Synthesis faithfulness | Each substantive claim is supported by its cited material with appropriate scope | At least one qualification or citation needs repair | A central claim is unsupported, invented or reverses evidence |
| Valence defensibility, when applicable | Direction and explanation follow the study's explicit rating rules | Direction is plausible but needs qualification or better justification | Barrier/facilitator reversal or unsupported direction |

Completeness requires a full-source or independent-reference assessment; it cannot be inferred from reviewing only generated quotations. Record omissions as added passages/constructs with source links. Assess redundancy separately so legitimate multiple codes on one passage are not penalized.

Use the CFIR study's declared rating procedure. Nominal labels such as mixed/neutral/barrier/facilitator are not automatically points on a -2 to +2 scale. Preserve group membership and make clear that counts of coded passages do not measure determinant prevalence. [CFIR tools and templates](https://cfirguide.org/cfir-tools-templates).

A future AI judge should receive blinded, randomly ordered outputs without model labels. First calibrate against expert ratings using both clean controls and human-verified seeded errors, including wrong-construct, fabricated-quotation, omitted-material, source-group swap and valence-reversal cases. Measure error detection and false alarms by error type before using judge scores in a comparison. Generic judge results do not transfer automatically to CFIR; position, verbosity and self-preference biases need testing. [Zheng et al., 2023](https://arxiv.org/abs/2306.05685).

## Current AMN pilot

The owner-approved private cohort contains three AMN transcripts across two networks. Source identifiers and original network labels are preserved in the private pilot manifest. The functional composite uses GPT-5.2 snapshot 2025-12-11 and the preserved five-stage CFIR prompt sequence across three explicitly frozen configurations: 24k/medium for coding and participant roll-ups, 48k/medium for one context output, and 48k/low for remaining context and synthesis. All model proposals are assumed accepted **only to exercise the legacy pipeline**. No human review decisions are fabricated and no production study is adjudicated by this assumption.

The completed configured test sequence links 12 source/stage outputs and 12 Excel exports. The preserved network prompt specifies five CFIR domains and excludes Outcomes Addendum; the final cross-network prompt explicitly targets Innovation only. Completing these configured calls does not establish synthesis across all domains. Across all configurations, 32 attempts retain 27 completed responses, two incomplete responses with usage, and three unknown charges. The original shared USD20 pilot ceiling and USD10.20 conservative holds remain in force; mutable cost totals and detailed real-data metrics stay in private receipts. This is a functional test of the legacy CFIR pipeline, which consumes prior raw artifacts. It does not validate the separate reviewed-snapshot synthesis workflow, native schema enforcement of this reference pipeline, or fresh real-transcript browser-upload execution.

The preserved QA flags reflect a rule-applicability mismatch: global coding-column requirements were applied to synthesis tables, and a cross-network source/valence rule was applied to network tables. Generated headers matched the preserved stage prompts. The raw flags remain in the private audit; their count is not a semantic-error rate or evidence of schema validation. The QA inventory repair preserves those findings and does not silently change the rules.

The two predecessor runs remain incomplete and unchanged. Mixed downstream configurations cannot be presented as a controlled single-configuration pipeline result. Coding-only comparisons retain their original coding configuration and explicitly frozen source/codebook/normalization identities; neither assumed acceptance nor pipeline completion creates human-reference accuracy or semantic validity evidence.

Use preserved Claude and Gemini outputs for local method checks and comparison coverage. Keep the original prompts, code assignments, source hashes and full configuration uncertainty visible. Do not repair disagreement by assigning every conflicting observation to its predominant domain. Exact alias normalization is acceptable; substantive code remapping needs a separately declared analysis.

The pilot has three transcripts in two networks. It supports descriptive feasibility results and debugging, not confidence intervals, population reliability, or a landing-page model-performance claim. Spans share transcripts; run pairs share runs. A later uncertainty design should use paired resampling at appropriate transcript/group clusters with a sufficiently large independent sample.

## Publication-oriented next experiment

- Version stage-specific QA and schema contracts to match the preserved stage prompts, then plan explicit domain scope for any broader synthesis before further research synthesis. Preserve existing prompts/results; any all-domain extension requires a separately declared prompt/pipeline version.
- Freeze a protocol before selecting a winner: cohort, codebook version, source units, conditions, repeats, metrics, exclusions, matching thresholds and planned uncertainty.
- Separate calibration/development material from held-out evaluation transcripts, respecting study/network structure where relevant.
- If pursuing independent-human accuracy claims in a later extension, have two researchers independently code the evaluation subset; preserve pre-consensus annotations and record consensus separately.
- For the selected archival design, instead freeze the historical reference, its review provenance and finite coverage; retain the independent-human procedure above only if broader human-accuracy claims are pursued.
- Run a modest balanced model/effort grid with identical prompt contracts and separately generated repeats, preserving every failed attempt and all costs.
- Review a probability sample for interpretable quality/error rates. A targeted disagreement sample is useful for diagnosis but cannot alone estimate overall error rates without the sampling design/weights.
- Add a timed assisted-versus-unassisted workflow comparison if claiming saved researcher time. Synthetic acceptance supplies no such evidence.
- Publish an auditable metric implementation and synthetic challenge set first. Publish real-data performance only after validation, with permissions and explicit task/population limits.

## Paper2 revisions to resolve before reporting results

The local manuscript is an early draft whose comparative results tables remain placeholders. Treat its past-tense claims about completed comparisons as planned analyses until supported by verified artifacts.

- Remove the proposed harmonization step that retains the predominant domain assignment; it would erase the disagreement being measured.
- Name the unit and reference design before retaining kappa/alpha or accuracy claims.
- Reconcile the semantic rubric with its prompts: the network rubric's dimension count differs, one boundary dimension is absent, and the cross-network prompt lacks a consistent explicit score. Replace ungrounded completeness percentages with an assessable denominator.
- Separate independent human reference coding, human review of model proposals, and assumed test acceptance throughout methods/results.
- Correct the Scaling hermeneutics citation to [Dunivin, 2025, EPJ Data Science 14:28](https://link.springer.com/article/10.1140/epjds/s13688-025-00548-8). Check remaining bibliographic details against primary records.
- Cite the [2022 CFIR update](https://doi.org/10.1186/s13012-022-01245-0) and [Outcomes Addendum](https://doi.org/10.1186/s13012-021-01181-5) consistently with the actual codebook version.

See [implemented metric definitions](benchmark_metric_notes.md) for exact denominator, matching, duplicate, undefined-score and provenance contracts.
