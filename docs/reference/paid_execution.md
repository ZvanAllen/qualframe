# Paid execution and request accounting

Implemented September 7, 2026, with later synthetic API verification and an owner-approved private real-data pilot. Current execution and research-validation boundaries are recorded in `capability_status.md`.

## Researcher workflow

1. In Analysis method, enter the provider, exact model, output-token limit, API mode/effort where supported, official pricing source, and study ceiling. A blank temperature omits that parameter.
2. Confirm study-data governance and save. Keys remain in the app process; no model call occurs.
3. Create a new dry-run plan. Existing studies can create new plans from Analysis method.
4. Review the provider/model, source count, planned calls and ceiling. Enter researcher identity and rationale, then explicitly approve paid coding. A changed configuration invalidates the approval.
5. Review outputs and exact source evidence before release/export. API success is not evidence of research validity.

OpenAI Responses uses `max_output_tokens`, `reasoning.effort`, and `store=False`. Original Chat Completions configurations remain supported. Anthropic forwards its separate `output_config.effort`; thinking remains at the model default. Effort availability varies by exact model, and unsupported options fail explicitly rather than being silently changed. Advanced Anthropic thinking-budget controls and a live-tested model compatibility catalog remain pending.

Sources checked September 7: [OpenAI Responses](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort).

## Request and cost records

OpenAI and Anthropic SDK retries and adapter retries are disabled. Each attempt has a durable reservation before submission. Responses retain completion status, normalized token usage, returned model/response ID and elapsed time under the run's `requests` folder. Incomplete or empty responses are recorded, then rejected before coding output is accepted. Failure records store exception type, not exception text that might contain sensitive request details.

By default, a missing response, process interruption, or missing usage leaves the request unresolved and blocks subsequent paid submissions across restarts. An exclusive cost-check file prevents two processes from reserving at once. A crash during that short check leaves a lock requiring inspection; the app never silently clears it. Browser jobs are serialized within one app instance.

Local cost estimates use UTF-8 text bytes plus framing allowance, the configured output maximum, and the highest configured applicable token rates. These are local estimates, not a billing guarantee. Verified current prices and provider billing reconciliation remain necessary. Recorded totals exclude unresolved amounts. Ordinary execution blocks rather than treating that amount as zero. The explicitly opted-in recovery mechanism below may retain a separately documented conservative budget hold; it never represents that hold as actual usage.

The legacy Google adapter retains its previous retry behavior and is not enabled for paid browser execution. The new attempt guarantees apply to OpenAI and Anthropic.

## Reconcile an uncertain request

The `qualframe reconcile-usage` command defaults to dry-run. Supply the project, request ID, mutually exclusive input/output/cache/reasoning counts, reviewer, rationale, and provider evidence reference. Use `--no-dry-run` only after verifying those counts against provider records or support confirmation. Zero usage requires evidence that the request was not billed; a timeout alone does not establish this.

Reconciliation appends an audit record and a replacement usage record using the original request's pricing snapshot. Earlier estimated records remain preserved. Totals count the latest record per request once. Reconciliation neither resumes execution nor repeats a call. A browser reconciliation form and automatic provider-billing retrieval remain pending.

## Prepared synthetic smoke test

Two separate studies under `studies/api-verification-*-20260907` each contain the same two checked-in synthetic transcripts and generic codebook. Each has a saved preflight and a USD 0.50 study ceiling. Four calls total are planned, sequentially, without retries or model substitution:

- OpenAI `gpt-5.4-nano-2026-03-17`: Responses, low effort, temperature omitted, 4,000 maximum output/reasoning tokens per call. Standard pricing entered: USD 0.20 input / 1.25 output per million tokens. [Official model page](https://developers.openai.com/api/docs/models/gpt-5.4-nano).
- Anthropic `claude-haiku-4-5-20251001`: Messages, provider-default effort/thinking, temperature omitted, 4,000 maximum output tokens per call. Standard pricing entered: USD 1 input / 5 output per million tokens. This model does not support the effort parameter. [Official model page](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

Preparation is not execution approval. Stop on failure, incomplete output, malformed coding, or uncertain usage. If successful, inspect coding structure, exact-evidence linkage, review queue, usage records, and exports. Report model validity separately from software execution. Do not generalize these four calls into performance or agreement claims.


## Explicit recovery with a conservative budget hold

The engine supports a separate, append-only unresolved-request budget hold. Ordinary browser and CLI jobs continue to require reconciliation. A developer-operated continuation must explicitly opt into holds, verify that the failed local attempt has terminated, and document a defensible maximum for its exact provider/model, token limits, applicable service-tier rates, endpoint, tools and retry behavior. The ordinary UTF-8 estimate alone is insufficient evidence.

`hold_unresolved_request` defaults to dry-run and requires the existing request identity, recorder, rationale, bound evidence and continuation authorization. It binds the hold to the original reservation hash and refuses duplicate, nonfinite, nonpositive or smaller-than-reservation amounts. Recording a hold does not resume execution. `unresolved_requests()` remains truthful and provider-confirmed usage reconciliation is unchanged.

Opted-in preflight counts known usage and each unresolved reserve once against the same study ceiling and approval intervals. Any new, unheld unresolved attempt blocks again. Later evidence-based reconciliation replaces that request's hold in exposure calculations without deleting the original audit history. A charge larger than its hold is recorded in full and may stop further execution.

The September 11 private pilot preserves three unresolved attempts under conservative holds totaling USD10.20, inside the original shared USD20 ceiling. The first hold used full-model capacity at the highest verified Fast token rates; later holds retain their individual request-bound evidence. The 48k downstream continuations reserve at least USD2.744 per new request, covering the 400,000-token context limit and 48,000 output/reasoning tokens at the reviewed Fast rates. A higher ordinary estimate is never lowered. Each subsequent request must still pass the shared ceiling; enough budget for one request does not guarantee that all remaining requests fit. See [OpenAI model limits](https://developers.openai.com/api/docs/models/gpt-5.2) and [official pricing](https://developers.openai.com/api/docs/pricing) (older-model rows are available in the page's Markdown version).

The private continuation counts a known terminal response's standard-rate cost calculation once only when its returned `default` or `flex` tier, normalized token counts, request/response IDs, provider/model, run/stage/input identity, reservation and pricing snapshot are verified together. Terminal `incomplete` or `failed` status can establish recorded usage without making the output usable. Recorded usage without that complete proof is counted at twice its standard-rate calculation for exposure. Estimated or unresolved attempts retain their existing reservation/hold once; they are not invented token usage or billed as zero. Current totals are read from the private completion receipt and shared ledger, not copied into a changing public cost claim.

Three explicit configuration versions were required: 24k/medium coding and roll-ups, 48k/medium for one context output, then 48k/low for remaining context and synthesis. Across them the completed test-only composite retains 32 attempts: 27 completed, two incomplete with usage, and three unknown. It preserves both incomplete predecessor runs and their raw outputs. This private recovery does not enable ordinary browser recovery, automatic billing retrieval, or a claim that all outputs came from one configuration. The preserved network prompt specifies five CFIR domains and excludes Outcomes Addendum; the final cross-network prompt explicitly targets Innovation only. Completing these configured calls does not establish synthesis across all domains. The completion receipt retains raw QA flags; stage-specific rule/schema alignment remains a separate next step before further research synthesis.


Responses transport consumes streamed events while retaining the final response object, completion status, normalized usage and returned service tier. It preserves the configured analytical request and `store=False`. A partial stream is never accepted as complete coding, no automatic retry is added, and the client closes on success or error. The private continuation additionally used an explicitly reviewed HTTP/2 transport that accepts a terminal provider event without requiring a later stream EOF. Completed terminal events were exercised in the pilot; this does not establish a network-failure diagnosis or general transport reliability. A streamed response object is not evidence of provider-native schema enforcement for the legacy CFIR output tables.
