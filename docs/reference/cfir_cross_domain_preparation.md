# Preparing broader CFIR cross-network synthesis

The preserved legacy prompt and runner synthesize Innovation only. The new
`cfir_synthesis_preparation` module is a separate **preparation-only** workflow
that creates one versioned request per selected core CFIR domain. It makes no API
calls, records no human decisions and does not change a completed run.

## Input and scope

Supply explicit network labels mapped to saved participant-to-network artifacts,
a frozen codebook catalog, and a statement describing the real provenance/review
status of those inputs. The input files must be parsed outputs from one run,
bound to their network identities, with the five-column network contract and all
five determinant domains represented. The Outcomes Addendum is outside this plan.
A smaller set of networks is allowed and remains explicit.

The new prompt at `prompts/cfir/v2/05_cross_domain_synthesis.md` derives from the
preserved final prompt. Its documented changes are a domain placeholder, a
contributing-network placeholder, and an explicit interpretation of the actual
network input columns. The existing final prompt is untouched. Network inputs use
`Combined Evidence Quotes` and `Synthesized Explanation`; the new prompt explains
how these correspond to its quotation and explanation instructions.

## Interface

```python
from qualframe.cfir_synthesis_preparation import (
    build_cross_domain_plan, write_cross_domain_plan, validate_prepared_response,
)

plan = build_cross_domain_plan(
    repo_root,
    network_artifacts,
    frozen_codebook,
    input_provenance="Describe the actual source and review state here.",
)
destination = write_cross_domain_plan(plan, private_output_root, dry_run=True)
# Remove dry_run only to write a local preparation bundle, not to execute an API.
```

The content-addressed folder contains the plan and one request text per domain.
It retains input, prompt, schema and codebook hashes and marks provider settings,
execution and spending approval as absent. Real source-derived bundles must stay
private. The writer refuses differing or incomplete existing bundles.

`validate_prepared_response` checks a supplied response against its prepared
single-domain contract, including source-network membership and valence exclusivity.
It is a post-parse check, not a provider-native schema or a semantic-quality score.
Unknown networks, wrong domains, missing headers and conflicting valence assignments
are detectable. Correct interpretation, complete construct coverage and faithful
quotation content require other evidence.

## Before funded execution

Choose immutable main-study inputs, exact model settings, governance, the approved
aggregate ceiling and request accounting before adding a dispatcher. This preparer
is not an executable configuration for the legacy runner. Keep fixed-input stage
stability separate from a chained experiment in which newly generated network
outputs become the cross-network inputs; those designs measure different sources
of variation. Input snapshot selection must precede synthesis results.

Synthetic tests exercise five distinct requests, exact input identities, changed
run/network bindings, domain/valence failures, dry-run behavior and preserved
bundles. Preparation from already completed research outputs establishes local
input compatibility only; it is not a new generated or reviewed synthesis.
