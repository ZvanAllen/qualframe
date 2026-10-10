# Raw coding comparison: implemented protocol v1

Implemented September 10, 2026. This is an engineering protocol for descriptive
pairwise comparison. It is not the full publication evaluation protocol. See
[evaluation protocol](evaluation_protocol.md) and [workplan](workplan_2026-09-07.md).

## Inputs and eligibility

Choose two different indexed coding runs in the same study. They must have the
same transcript paths and original-file hashes and the same frozen codebook
content. All planned coding partitions for the cohort must have successful,
structured artifacts. Partial or failed runs are blocked, not converted to
negative codes. Source and model-artifact hashes are rechecked.

Comparisons use original model proposals and the immutable evidence index, never
human-edited assignments. Accepted normalization of unique typography-only CFIR
quotations follows the stored anchoring policy and retains exact source offsets
and raw-artifact provenance. Ambiguous, missing, invalid or unknown-code
proposals are excluded from overlap calculations and reported separately.
Unknown-code absence proposals are also excluded. Known-code absence proposals
are counted separately; they are not quoted evidence or negative labels in the
metrics. A high score with many excluded proposals may overstate whole-output
agreement. Report exclusion counts with every result.

## Measures

Jaccard overlap is intersection divided by union. The standard definition is
specified in the [scikit-learn metric documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.jaccard_score.html).
QualFrame implements the following explicit units without adding that dependency:

| Measure | Unit within each transcript | What it captures |
|---|---|---|
| Code overlap | Set of code IDs with at least one valid retained raw proposal | Coarse construct presence; independent of passage boundaries |
| Exact coded-passage overlap | Set of `(code ID, start, end)` tuples | Identical assignments and source boundaries |
| Coded-text coverage overlap | Set of `(code ID, Unicode character position)` pairs | Partial passage overlap within the same code |

Source offsets are zero-based Python Unicode code-point positions in the extracted
text, with an exclusive end. They are not bytes, tokens, sentences, people or
browser UTF-16 positions. Repeated identical assignments are deduplicated within
a metric. Overlapping and adjacent intervals are merged within each code. A
character assigned two codes contributes once to each code, intentionally.

For example, one run codes `[0, 10)` and another `[5, 15)` under the same code:
code overlap is 1, exact overlap is 0, and coverage overlap is 5/15. If only one
set is empty, overlap is 0. If both are empty, the value is undefined (`null`),
not perfect agreement. Zero-union transcripts contribute no weight to a pooled
score and remain visible in the per-transcript report.

Each aggregate pools the transcript intersections and unions, then divides. It
is not the arithmetic mean of transcript scores. Numerators, denominators,
per-code coverage, distinct passage counts, exact differences, exclusions and
source quotations are preserved in the JSON report.

## Reproduction and interpretation

Use **Compare runs** in the browser, then **Save frozen comparison**. Alternatively:

```bash
qualframe-eval compare studies/example/project.yaml --left run-a --right run-b --dry-run
qualframe-eval compare studies/example/project.yaml --left run-a --right run-b
```

Replace the example manifest and IDs with existing indexed runs. The report is
content-addressed and stored under the first run's `comparisons` folder. Repeating
an unchanged comparison reuses it without overwriting. It includes both raw input
payloads, source/index/artifact/configuration identities, codebook content, prompt
hashes and the run's recorded cost when available. No provider requests are made.
The other historical `qualframe-eval` commands remain scaffolds.

These statistics describe a pair, not coding accuracy or chance-corrected
reliability. Within-configuration stability needs repeated independent runs;
between-configuration agreement needs controlled inputs and declared differences.
Neither label follows merely from two run IDs. No confidence interval, kappa,
alpha, fixed-unit positive agreement, or population inference is implemented in
this increment. The existing manuscript/evaluation plan needs a frozen sampling,
repeat-count, missing-output and clustering protocol before publication claims.
Synthetic identical mock scores test the software, not LLM performance.
