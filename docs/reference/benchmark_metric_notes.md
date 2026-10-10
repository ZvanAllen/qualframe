# Benchmark metric notes: labelled source spans

Implementation: `qualframe.benchmark_metrics.build_benchmark_report(left, right)`.
The scorer accepts the source-validated dictionaries returned by `raw_coding_payload`
and produces a separate `qualframe_benchmark_report_v1`. Existing pairwise and
repeated-report v1 schemas remain unchanged. This increment makes no provider calls.

## What the scores can establish

**Stability** describes variation across separately generated outputs under one
frozen configuration and source cohort. **Between-configuration agreement** describes
how those outputs coincide when configurations differ. Neither establishes that the
codes are appropriate, evidence is interpreted faithfully, important material was
found, or summaries are useful to researchers.

**Reference agreement** requires an explicitly designated comparator and an accurate
account of its origin. An independently prepared human reference supports a different
claim from a historical human-reviewed, AI-assisted analysis. The latter can support
archival evidence recovery and concordance under the [archival protocol](archival_comparator_protocol.md),
with context, source-link coverage and finite-reference limits stated. It does not
establish independent human coding or full-source completeness. The span scorer here
remains a new-run agreement scorer; the archival adapter records its own origin and
context-sensitive retrieval policy. Assumed acceptance during a functional test
cannot supply either kind of human reference, empirical acceptance rates or measured
review effort.

**Semantic validity** requires a separate assessment of construct fit, contextual
support, omission, and interpretation. Source-hash/quotation checks and valid
citation IDs establish traceability, not semantic support. Blinded expert review
and the existing seeded-error evaluator protocol address that different question.

## Implemented comparison policy

The existing comparator enforces identical study, source paths/hashes and codebook
content. Matching occurs only between spans under the same source and exact code.
No parent-code equivalence, semantic code mapping, textual paraphrase alignment,
or cross-transcript matching is inferred.

Exact duplicates of `(source, code, start, end)` count once in span support. Every
original proposal ID remains available, and duplicate counts/rates are reported
separately. Different codes on the same source span are distinct assignments.

Frozen catalogs are preserved verbatim. Per-code scoring uses each code ID once,
so repeated catalog rows cannot double the match count. Diagnostics list duplicate
IDs, labels and entry counts. IDs with distinct catalog entries are ambiguous:
they retain one zero-support code row, and included spans using them cause scoring
to stop. Identical duplicate entries are counted once. Excluded ambiguous proposals
remain visible in validity counts; the scorer does not silently repair the catalog.
Offsets refer to Python Unicode code points, with exclusive end; separate display
context does not contribute to the coded span.

| Measure | Matching rule | Purpose |
|---|---|---|
| Exact F1/Dice | Same code, source, start and end | Strict assignment and boundary agreement |
| Overlap F1 at IoU 0.25 | One-to-one span matches with intersection/union at least 0.25 | Broad boundary sensitivity |
| Overlap F1 at IoU 0.50 | Same, with threshold 0.50 | Intermediate boundary sensitivity |
| Overlap F1 at IoU 0.75 | Same, with threshold 0.75 | Stricter boundary sensitivity |

These three overlap thresholds are prespecified QualFrame sensitivity choices,
not established cutoffs for qualitative correctness. Report them together; do not
select the most favorable threshold after observing model results.

For each source/code and threshold, the algorithm finds a **maximum-cardinality
one-to-one matching** using augmenting paths. Canonical source/code/offset ordering
and breadth-first traversal make ties deterministic. It does not optimize total
IoU among tied maximum-cardinality matchings; diagnostics reflect the recorded
matching policy. This prevents one long excerpt from counting as matches to many
short excerpts. A split/merge can consequently have perfect coded-text coverage
and imperfect span F1, a useful distinction in segmentation behavior.

If `M` is the number of matched span pairs and `L`, `R` are unique left/right span
counts:

- F1/Dice = `2M / (L + R)`.
- Left matched fraction = `M / L`; right matched fraction = `M / R`.
- The two fractions are not called precision/recall when both sides are models.
- Both sets empty: F1 and both fractions are `null` (undefined).
- One set empty: F1 is zero; the empty side's fraction is undefined.
- Failed or missing model output is unavailable, never an empty annotation set.

Exact F1 is a monotonic transformation of exact Jaccard (`2J/(1+J)`), so it does
not provide independent corroborating evidence. Its value is familiar reporting
and reuse of an explicit matched-span count contract.

The summary pools matched counts and span counts across sources/codes. A separate
macro score averages defined per-code F1 values, with undefined-code counts shown.
Common codes can dominate pooled results; macro results can be unstable for rare
codes. Per-code support and source-level results must accompany either aggregate.
Matched-pair diagnostics retain IoU and signed boundary shifts plus aggregate
absolute shifts. They describe only matched spans and can appear favorable when
many unmatched spans were excluded from those diagnostics.

Validity reporting retains included, excluded, and valid absence-declaration counts.
The exclusion-rate denominator is included plus excluded proposals. Known-code
absence declarations stay separate, as in the original comparator. Span overlap
scores concern the valid subset; a high score after many exclusions is not high
whole-output agreement.

## Kappa, multilabel labels and unitization

Model-generated rows are not shared units. Applying nominal kappa to row positions,
or silently taking the intersection of two label sets, does not solve unitization
and can distort agreement. A later fixed-unit benchmark should freeze shared source
segments first, preserve multilabel vectors and missing-output states, then report
per-code contingency counts, positive agreement and declared multilabel summaries.
Transcript-by-code presence already supplies a possible *coarse* common unit, but
must not be described as passage-level agreement or participant prevalence.

Any kappa/alpha option needs a named unit, rater design, chance model, missing policy,
and treatment of overlapping labels. Rare codes and skewed marginal distributions
can make chance-corrected statistics unstable or undefined. Unitizing-alpha variants
are a separate methodological choice; ordinary nominal alpha is not a substitute
for boundary evaluation. A few AMN transcripts are a functional/descriptive pilot,
not a basis for general reliability thresholds or model promotion.

Pairwise run scores share runs. Spans within transcripts, and transcripts within a
study grouping, may also be dependent. Future uncertainty estimates must follow the
sampling design and resample appropriate clusters, rather than treating every span
or pair as independent. An AMN network should only be treated as a sampling cluster
when that matches the research design.

## Primary sources informing these choices

- [Chen et al. (2023), A Unified View of Evaluation Metrics for Structured Prediction](https://aclanthology.org/2023.emnlp-main.795/): derives set matching, one-to-one constraints, and normalized F1/Dice. QualFrame's thresholded maximum-cardinality rule is an explicit task-specific choice within that framework.
- [Lee and Sun (2019), A Study on Agreement in PICO Span Annotations](https://arxiv.org/abs/1904.09557), [published DOI](https://doi.org/10.1145/3331184.3331352): shows why exact boundaries and relaxed span agreement can yield different conclusions in biomedical annotation. It does not validate QualFrame's chosen IoU thresholds or CFIR coding quality.
- [Marchal et al. (2022), Establishing Annotation Quality in Multi-label Annotations](https://aclanthology.org/2022.coling-1.322/): examines how label multiplicity and distributions affect agreement and naive intersection-based kappa adaptations.
- [Artstein and Poesio (2008), Inter-Coder Agreement for Computational Linguistics](https://aclanthology.org/J08-4004/): distinguishes classification and unitizing, and analyzes prevalence and marginal-distribution effects on agreement coefficients.
- [Krippendorff's author-provided reliability and corrected unitizing resources](https://www.asc.upenn.edu/krippendorffs-alpha-reliability): provides separate multivalued and unitizing families, including corrected material for the content-analysis textbook.
- [scikit-learn F1 documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.f1_score.html): specifies per-label, micro/macro averaging and undefined-denominator conventions. QualFrame explicitly preserves undefined scores as null.

The literature motivates distinct dimensions and transparent definitions. It does
not supply a universal quality score or justify substituting model consensus for
expert assessment.

## Historical normalization sensitivity

The historical adapter defaults to `legacy_v1`, preserving the original parser behavior. An explicitly requested `qualified_delimiters_v2` sensitivity policy also recognizes whitespace-delimited hyphens/en-dashes/em-dashes between literal CFIR parent and child labels, after the existing code-prefix normalization. Both labels must identify one code within the domain. It does not equate synonyms, general labels or substantively different constructs. Original construct text, aliases, sources, artifacts, prompt hashes and each normalization version remain recorded; prior report identities and review behavior are preserved.

A formatting limitation in the parser is not evidence of poor model coding. Compare the two policies and disclose exclusions before interpreting differences. Present-day catalog normalization does not establish which complete codebook/configuration governed a historical run.

### Opt-in casefold-only quotation sensitivity

`qualframe.benchmark_quote_sensitivity.casefold_quote_sensitivity(payload, source_texts)`
returns a separate derived benchmark input. Supply extracted text keyed by canonical
source ID; the function verifies each text against the frozen source-mapping hash
and extracted-text hash. It leaves the original payload, CFIR review behavior,
sources, quotations, code labels and existing scientific reports unchanged.

Only an excluded quotation with an already unique valid catalog code and no other
blocking issue can enter this sensitivity. After the existing whitespace and quote
typography normalization, Unicode casefold matching must find one occurrence. Its
offset mapping must recover an original source slice that normalizes and casefolds
back to the complete quotation. This final check rejects partial matches inside
Unicode expansions. Ambiguous matches, unmatched quotations, unresolved codes and
other issues remain excluded. Source/provenance mismatches abort the transformation.

The derived input records the policy and Unicode version, strict input hash,
original normalization version, original strict issues, every attempted candidate,
and before/after inclusion counts. Code-label sensitivity remains a separate named
policy. Standalone reports show the quotation policy and inclusion counts for each
side before the scores. Compare sensitivity results with the strict report and
disclose how much eligible support depends on normalization; an increased score
or inclusion count does not establish semantic correctness or human approval.

Punctuation removal, approximate or word-sequence matching, shortened quotations,
and code-label repair are outside this option. Such exploratory diagnostics must
not enter scored spans without a separately specified and justified method.

Standalone display bundles carry a display-format version in their directory name separately from the scientific report identity. Later display changes can create a new bundle without overwriting frozen scientific reports.
