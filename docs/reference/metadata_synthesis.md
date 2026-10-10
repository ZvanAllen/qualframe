# Metadata scopes for reviewed synthesis

Implemented September 11, 2026. These controls organize source-linked, reviewed
passages using an imported CSV field. They do not estimate participant prevalence,
independent case counts, statistical differences, or semantic validity.

## Researcher workflow

1. Import transcripts and a UTF-8 metadata CSV through the source library. The CSV
   needs `source_filename` plus one or more grouping columns. Each row names an
   original imported transcript filename exactly; folder labels are not used to
   infer metadata. Duplicate or ambiguous filename links are rejected.
2. Complete the required source review and freeze the intended transcript subset.
3. Under **Prepare synthesis**, open **Group summaries using imported metadata**.
   Choose a field, keep the values to include, and explicitly decide how to handle
   missing metadata: require every source to have a value, exclude missing values,
   or include a separate missing-value scope.
4. Prepare the plan and inspect frozen group membership, exclusions, and the
   code-by-group matrix. No API request occurs during preparation.
5. Use the existing provider preflight and approval to generate proposed summaries.
   Review every statement against its cited passages before exporting.

Leading/trailing spaces in values are trimmed; case and other spelling are
preserved. Repeated equal values combine the corresponding sources. Each source
belongs to exactly one value for the chosen field. Missing rows and blank values
are both treated as missing. A literal value named `[missing value]` stays distinct
from the missing-value scope. Field-by-field preparation avoids implying that
crossed fields or hierarchical group comparisons are already implemented.

## Frozen inputs and freshness

Metadata plans use `qualframe_synthesis_plan_v2`. They preserve:

- the current imported metadata path, SHA-256, decoded CSV content, and import record;
- each snapshot source's registered filename/path/hash linkage and metadata values;
- field, selected values, explicit missing policy, and stable group identities;
- all included sources, sources excluded by the snapshot, and sources excluded by
  the grouping selection, with reasons;
- the frozen codebook, reviewed evidence snapshot and original versioned prompt.

Metadata and transcript import paths must remain inside the managed study.
Imported metadata bytes and source bytes are checked against their import hashes.
The execution preflight rebuilds the plan from current reviewed evidence and the
active metadata version. Importing a new version or altering an imported file
invalidates execution/review/export through the current-input gates; historical
plan and response files remain readable. Existing per-transcript and combined
`qualframe_synthesis_plan_v1` plans remain unchanged and usable: metadata is not
retroactively made a dependency of those scopes.

The complete metadata CSV is preserved locally in the plan and therefore in an
export containing that plan. Provider inputs contain the chosen scope definition,
source paths, code definitions and retained passages, not the other CSV columns.
Normal study governance and transfer approval still apply to the selected inputs.

## Matrix and interpretation

Each matrix cell counts distinct `(source_path, start, end)` spans for a code.
Expanding a nonzero cell exposes the exact passages and links to the frozen source
view. Multiple retained proposals for an identical source span/code do not inflate
the cell count. The full frozen codebook remains visible, including zero cells.

A selected metadata scope with no retained passages stays in the plan and matrix,
but does not create a model request. Preparing synthesis still requires at least
one retained passage in the selected scopes overall. Zero cells and omitted calls
mean no retained evidence in these inputs; they do not establish absence. Sources
are not treated as participants, groups are not treated as independent samples,
and repeated transcripts are not silently deduplicated into cases.

## Verification and remaining scope

Synthetic tests exercise current and missing metadata, selected-source subsets,
value exclusions, repeated and case-distinct values, literal missing labels,
changed metadata, path boundaries, invalid CSV columns, cross-group citation
rejection, frozen matrices, mock synthesis, and old-plan compatibility. No live
provider calls or private research materials are needed for these checks.

Multiple grouping fields, manual case definitions, longitudinal joins, overlap
between selected groups, and inferential group comparisons remain future work.
