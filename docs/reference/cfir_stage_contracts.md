# Opt-in CFIR stage contracts

Version 2 is an offline-tested, post-parse structural and QA contract for the
preserved `prompts/cfir/final/01..05` sequence. It does not change those prompts,
the legacy pipeline, v1 schema, historical artifacts, or existing study settings.
No real-data run has been rerun or validated under v2. It is separate from the
provider-native constraints used by reviewed-snapshot synthesis.

Use a new study/configuration and run ID with:

```yaml
structured_output:
  enforce: true
  spec: config/schemas/cfir_stage_outputs_v2.yaml
```

The separate [example manifest](../../examples/project_template/project_transcript_scoped.yaml)
uses a mock provider and review gates. Its default provider produces a placeholder,
not a schema-valid CFIR result; use it for preparation or supply cached synthetic
responses for execution tests. Provider-backed use requires separate configuration,
governance and cost approval. Merely naming the v2 file with `enforce: false` does
not activate it. The existing transcript template remains unchanged.

| Stage | Required columns and scope | Framework QA selected by v2 |
|---|---|---|
| Transcript coding | CFIR Domain, CFIR Construct, Quote, Page Number, Explanation; values from all six configured domain/addendum partitions must appear | Required columns, prompt identity |
| Parent roll-up | Same five columns; permits the five determinant domains and Outcomes Addendum | Required columns, prompt identity |
| Context enrichment | Same five columns and permitted values | Required columns, prompt identity |
| Network synthesis | CFIR Domain, CFIR Construct, Combined Evidence Quotes, Synthesized Explanation, Source File(s); the five determinant domains must appear; Outcomes Addendum is outside scope | Required columns, prompt identity |
| Cross-network synthesis | Combined quotation/explanation columns; four network-valence columns; Overall Valence; Valence Explanation; Source File(s); Innovation only | Required columns, prompt identity, allowed network labels, valence exclusivity, source/network-valence coverage |

All stages require the exact configured column order and at least one parsed data
row. An empty or incomplete output is blocked for explicit review of the contract
and source coverage, rather than treated as demonstrated absence. Overall Valence
uses Facilitator, Barrier, Mixed or Neutral; Neutral/Unclear names a network-level
column, not an allowed overall value. Values are checked literally, without fuzzy
label repair.

The scope checks examine row values, not semantic completeness or every construct's
presence. Roll-up's preserved prompt mentions five worksheets while also giving
Outcomes Addendum instructions; v2 permits addendum rows without claiming that the
prompt unambiguously guarantees six-sheet coverage. Context column preservation
and quotation fidelity relative to upstream/source text need separate comparisons.
The cross-network prompt names Innovation explicitly; this contract does not
expand it into all-domain synthesis.

`StageOutputRule.qa_rules` is optional. Omitted/null keeps the legacy framework-wide
rule list and required columns. An explicit list selects that stage's framework QA
and uses its contract's required columns; an empty list disables only framework QA,
not schema or directed-method checks. Unknown rule names fail configuration loading.
Structural failures block later stages and validated export. Other framework QA
findings enter the review queue; they do not become semantic-error counts or add a
new automatic stage gate.

For v2, network Source File(s) values are participant/source IDs, so the cross-network
valence coverage rule does not apply. Cross-network Source File(s) values are network
labels, so the existing allowed-label, exclusivity and coverage checks still apply.
These checks establish membership consistency, not appropriate valence assignment.

The configuration lock hashes the schema file. Each scoped artifact also records a
hash of the parsed structural/QA contract. Before saving a scoped plan or executing,
the runner checks any existing plan, lock, manifest and stage artifacts for compatible
bindings. Legacy, unknown or differently bound artifacts require a new run ID; they
are not silently revalidated or adopted. Compatible resume reuses saved artifacts
and reconstructs the final-manifest QA inventory without rewriting raw artifacts.
Legacy contracts retain their existing behavior.

Synthetic verification covers the five-stage flow, true cross-network QA conflicts,
header/domain failures, unknown rules, configuration changes, interrupted execution
and resumed validation gates. Real-data behavior, complete construct/source coverage,
semantic support and a separately versioned broader synthesis method remain unverified.
