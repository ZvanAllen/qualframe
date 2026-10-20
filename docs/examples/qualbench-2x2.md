# A worked QualBench comparison

> Six fictional interviews and a 15-code codebook. These numbers show what QualBench reports; they say nothing about which model, instruction style or codebook division works better. With six documents the intervals are very wide.

Some displayed intervals are numerically narrow, and the baseline intervals are fixed. These intervals reflect resampling the six saved fictional interviews; they do not measure variation across new studies or repeated model runs.

This example compares two instruction styles and two ways of dividing the codebook, separately for Claude Sonnet 5.5 and GPT-6.1 Sol. It uses only the bundled [AI documentation assistant demo](../../demo/datasets/ai-scribe/README.md).

## Design

Each model has four coding sets:

| Instruction style | Codebook division | Requests across six interviews |
| --- | --- | ---: |
| Find passages | Whole codebook | 6 |
| Find passages | One parent group per request | 24 |
| Decide every code | Whole codebook | 6 |
| Decide every code | One parent group per request | 24 |

The four groups contain 4, 4, 4 and 3 codes, including their parent codes. All 15 codes are active. Parent-level results are a separate projection of the coding onto four groups; they are not extra code-level observations.

The find/whole recordings were made on 10 October 2026 and are reused unchanged. The other six sets were recorded for this example. Every cell has a 16,000-token output limit, including any hidden reasoning. This explicitly overrides the current presets' 32,000-token default to match the reused recordings. GPT-6.1 Sol uses low reasoning effort. Recording metadata preserves the dates, model settings, prompt hashes and usage; these are individual recorded runs, not repeated samples of each configuration.

## Reference

The reference is **Illustrative coder A**, a hand-written coding included with the demo. It is not a human gold standard, an independent annotation exercise, or evidence of model accuracy on research data. No new human codings were created for this comparison.

A records positive applications only, without explicit absence decisions. QualBench therefore counts all 90 document-code units (6 interviews x 15 codes) as assessed. A code with no recorded application is an implicit negative, not a documented absence decision. There are no document or unit exclusions.

## Rebuild offline

From the repository root, with the normal development dependencies installed:

```bash
python scripts/run_qualbench_example.py --output artifacts/qualbench-2x2-example
```

The command creates a temporary study from the fictional dataset, replays the eight saved coding sets and the illustrative reference, and writes the comparison to the chosen output folder. It makes no model calls and incurs no API cost. Choose a new output folder on later rebuilds; existing folders are preserved. Generated studies and reports are not committed.

The comparison uses **2,000 bootstrap draws, seed 1, and document resampling**. Each draw samples six whole interviews with replacement. All coding sets use the same draw for paired differences. The two fictional sites are not resampled as clusters. Code units within an interview are kept together. The reported intervals are 95% percentile intervals; undefined replicates are omitted, with their counts retained in the report. Six interviews provide very limited information about uncertainty.

## Reading the report

- `coding_sets.csv` shows coding volume, quotation location and usage. The example supplies original recording costs rather than assigning a hosted charge to offline replay. Older recordings provide an estimated total; newer ones retain the usage-ledger calculation. These are usage-based costs, not provider invoices.
- `presence.csv` compares code application on assessed document-code units. Sensitivity is the fraction of reference positives recovered; specificity is the fraction of reference negatives left negative. Balanced accuracy averages those two fractions. MCC summarizes all four cells of the binary comparison. An undefined value is shown as undefined, not zero.
- The every-code-present and every-code-absent baselines ignore the interview text. They show how the reference's prevalence affects a trivial prediction. They are not additional model runs.
- `bootstrap.csv` supplies intervals for balanced accuracy and MCC, as well as F1 and kappa, and paired differences between coding sets. A paired difference is left minus right on the same sampled interviews. Positive and negative signs describe the named contrast only.
- `passages.csv` compares the text behind the codes. **All pairs** includes the full compared cohort; **shared positives** restricts comparisons to document-code pairs with at least one located passage in each set. A high agreement value in the latter scope does not account for codes applied by only one set. Unlocated quotations cannot supply located spans for these measures.
- `codes.csv`, `units.csv` and `report.json` retain the detailed estimates, assessment masks and metadata. The deterministic tables below are checked against a fresh offline rebuild by the test suite.

## Example figures

<!-- QUALBENCH_EXAMPLE_TABLES_START -->

All rates below are fractions. Intervals are 95% document-bootstrap percentile intervals. Sonnet means Claude Sonnet 5.5; Sol means GPT-6.1 Sol.

### Reference prevalence

| Level | Assessed units | Positive | Implicit negative | Prevalence |
| --- | --- | --- | --- | --- |
| code | 90 | 37 | 53 | 0.411 |
| parent code | 24 | 20 | 4 | 0.833 |

### Code presence versus illustrative coder A

| Coding set | Sensitivity | Specificity | Balanced accuracy [95% CI] | MCC [95% CI] |
| --- | --- | --- | --- | --- |
| Sonnet: find / whole | 0.973 | 0.887 | 0.930 [0.915, 0.941] | 0.848 [0.790, 0.875] |
| Sonnet: find / by group | 0.973 | 0.774 | 0.873 [0.843, 0.906] | 0.736 [0.632, 0.827] |
| Sonnet: decide / whole | 0.973 | 0.792 | 0.883 [0.858, 0.911] | 0.754 [0.667, 0.830] |
| Sonnet: decide / by group | 0.973 | 0.679 | 0.826 [0.767, 0.856] | 0.652 [0.593, 0.701] |
| Sol: find / whole | 0.973 | 0.868 | 0.920 [0.890, 0.955] | 0.828 [0.758, 0.912] |
| Sol: find / by group | 0.973 | 0.642 | 0.807 [0.782, 0.826] | 0.620 [0.537, 0.681] |
| Sol: decide / whole | 0.973 | 0.717 | 0.845 [0.808, 0.882] | 0.685 [0.565, 0.789] |
| Sol: decide / by group | 0.973 | 0.491 | 0.732 [0.655, 0.794] | 0.498 [0.370, 0.629] |
| Every code present | 1.000 | 0.000 | 0.500 [0.500, 0.500] | undefined [undefined, undefined] |
| Every code absent | 0.000 | 1.000 | 0.500 [0.500, 0.500] | undefined [undefined, undefined] |

### Paired differences between the saved cells

| Left minus right | Balanced accuracy difference [95% CI] | MCC difference [95% CI] |
| --- | --- | --- |
| Sonnet: find / whole minus Sonnet: find / by group | 0.057 [0.022, 0.093] | 0.112 [0.039, 0.194] |
| Sonnet: find / whole minus Sonnet: decide / whole | 0.047 [0.020, 0.073] | 0.094 [0.038, 0.153] |
| Sonnet: find / whole minus Sonnet: decide / by group | 0.104 [0.068, 0.163] | 0.196 [0.138, 0.274] |
| Sonnet: find / by group minus Sonnet: decide / whole | -0.009 [-0.037, 0.025] | -0.018 [-0.070, 0.041] |
| Sonnet: find / by group minus Sonnet: decide / by group | 0.047 [0.000, 0.132] | 0.084 [0.000, 0.207] |
| Sonnet: decide / whole minus Sonnet: decide / by group | 0.057 [0.016, 0.118] | 0.102 [0.032, 0.188] |
| Sol: find / whole minus Sol: find / by group | 0.113 [0.069, 0.167] | 0.208 [0.121, 0.301] |
| Sol: find / whole minus Sol: decide / whole | 0.075 [0.042, 0.103] | 0.143 [0.070, 0.217] |
| Sol: find / whole minus Sol: decide / by group | 0.189 [0.106, 0.293] | 0.331 [0.171, 0.497] |
| Sol: find / by group minus Sol: decide / whole | -0.038 [-0.093, 0.008] | -0.065 [-0.154, 0.013] |
| Sol: find / by group minus Sol: decide / by group | 0.075 [0.021, 0.139] | 0.122 [0.034, 0.222] |
| Sol: decide / whole minus Sol: decide / by group | 0.113 [0.052, 0.212] | 0.187 [0.086, 0.347] |

All six within-model cell contrasts are shown. These contrasts describe individual saved runs, not replicated model or configuration effects. Valid and undefined draw counts are retained in `bootstrap.csv`.

### Located passage agreement versus illustrative coder A

| Coding set | Scope | Model passages | Reference passages | Exact F1 | IoU >= 0.5 F1 | Coded-text Jaccard |
| --- | --- | --- | --- | --- | --- | --- |
| Sonnet: find / whole | all pairs | 92 | 64 | 0.346 | 0.513 | 0.393 |
| Sonnet: find / whole | shared positives | 85 | 63 | 0.365 | 0.541 | 0.429 |
| Sonnet: find / by group | all pairs | 126 | 64 | 0.242 | 0.453 | 0.309 |
| Sonnet: find / by group | shared positives | 106 | 63 | 0.272 | 0.509 | 0.357 |
| Sonnet: decide / whole | all pairs | 92 | 64 | 0.321 | 0.462 | 0.311 |
| Sonnet: decide / whole | shared positives | 79 | 63 | 0.352 | 0.507 | 0.355 |
| Sonnet: decide / by group | all pairs | 138 | 64 | 0.267 | 0.396 | 0.273 |
| Sonnet: decide / by group | shared positives | 107 | 63 | 0.318 | 0.471 | 0.336 |
| Sol: find / whole | all pairs | 130 | 64 | 0.155 | 0.381 | 0.311 |
| Sol: find / whole | shared positives | 116 | 63 | 0.168 | 0.413 | 0.340 |
| Sol: find / by group | all pairs | 155 | 64 | 0.110 | 0.265 | 0.233 |
| Sol: find / by group | shared positives | 120 | 63 | 0.131 | 0.317 | 0.295 |
| Sol: decide / whole | all pairs | 135 | 64 | 0.101 | 0.201 | 0.251 |
| Sol: decide / whole | shared positives | 110 | 63 | 0.116 | 0.231 | 0.288 |
| Sol: decide / by group | all pairs | 167 | 64 | 0.069 | 0.147 | 0.182 |
| Sol: decide / by group | shared positives | 116 | 63 | 0.089 | 0.190 | 0.245 |

### Quotation location and original recording cost

| Coding set | Proposed passages | Located | Exact | Unlocated | Omitted decisions | Requests | Original USD | Cost source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sonnet: find / whole | 92 | 92 | 92 | 0 | 0 | 6 | 0.216600 | Legacy estimate |
| Sonnet: find / by group | 126 | 126 | 126 | 0 | 0 | 24 | 0.437956 | Usage ledger |
| Sonnet: decide / whole | 92 | 92 | 92 | 0 | 9 | 6 | 0.185116 | Usage ledger |
| Sonnet: decide / by group | 138 | 138 | 138 | 0 | 0 | 24 | 0.359546 | Usage ledger |
| Sol: find / whole | 130 | 130 | 130 | 0 | 0 | 6 | 0.146800 | Legacy estimate |
| Sol: find / by group | 155 | 155 | 155 | 0 | 0 | 24 | 0.244748 | Usage ledger |
| Sol: decide / whole | 135 | 135 | 135 | 0 | 0 | 6 | 0.170714 | Usage ledger |
| Sol: decide / by group | 167 | 167 | 167 | 0 | 0 | 24 | 0.274024 | Usage ledger |

A presence value of zero means no observed positive application, including when a decide-every-code response omitted a requested decision. An omitted decision is not an explicit absence. Find-passages requests do not require a decision for every code; zero omissions in those cells does not mean explicit decisions were requested.

Offline replay costs USD 0. The costs above describe the original hosted recordings. No elapsed-time measurements from replay are used. Undefined statistics remain undefined.

<!-- QUALBENCH_EXAMPLE_TABLES_END -->

These values describe only these saved fictional-demo responses and the illustrative reference.
