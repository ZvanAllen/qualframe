# Repeated-run report protocol v1

The local **Compare runs → Evaluate multiple runs** view and `qualframe-eval stability PROJECT --run ID --run ID` command describe the original coding outputs from 2–10 selected runs. They never modify human decisions or contact a provider. A prepared repeat experiment links to a report containing every planned run, including failures and runs not started. A manually selected report records its selected run IDs explicitly.

## Scope and denominators

Each usable run must have completed coding for its full frozen transcript cohort, a frozen codebook, current source hashes, and unchanged indexed artifacts. Pairwise comparisons require the same study, identical transcript paths and hashes, and identical frozen codebook content. Failed runs and incompatible pairs are retained with reasons; they are not converted to zero agreement or silently dropped.

The report lists selected and usable run counts, all possible pairs, eligible pairs, unavailable pairs, incompatible pairs, included proposals, invalid/excluded proposals, and valid absence declarations. Invalid proposal rate uses included plus excluded proposals; valid absence declarations are separate. Scores cover the valid subset, which may overstate whole-output agreement.

The [raw pairwise protocol](raw_run_comparison_protocol.md) defines code-set Jaccard, exact coded-span Jaccard, and code-by-character coverage Jaccard. Coverage counts Unicode character positions separately for each code; text assigned two codes contributes to each. Overlapping intervals within one code are merged. No common fixed segmentation is invented. An empty union is undefined, never 100%.

## Repetition and configuration

Identical nonempty full configuration fingerprints define within-configuration comparisons. This is deliberately strict: provider, prompts, method, framework and administrative settings are included. Different fingerprints establish a different frozen configuration, not a model-only effect. Missing fingerprints remain unknown.

For each relationship and metric, report defined/eligible pair counts and the equally weighted pairwise mean, minimum and maximum. These are descriptive statistics. The same run appears in several pairs, so pairwise values are dependent. Do not interpret their count as an independent sample size. No confidence intervals, kappa, alpha, human-reference accuracy, thematic validity or general reliability claim is produced.

## Frozen reports

JSON reports preserve raw comparison payloads, pairwise numerators/denominators, excluded items, configuration/source/artifact/index identities, all selected runs and failure reasons. Experiment reports additionally bind the prepared experiment and plan identity. The filename hashes the report content. The browser Save action checks that the report still matches the version displayed; a changed output requires rebuilding it. Existing report downloads are checked against their identity.

For a publishable evaluation, preregister the cohort and selection rules, repeat counts, specific model/effort configurations, prompt/codebook versions, fixed-unit or span design, exclusions, missing-output treatment and aggregation. Freeze a human-reference calibration set before any accuracy analysis. The current tiny synthetic smoke tests establish software behavior only.
