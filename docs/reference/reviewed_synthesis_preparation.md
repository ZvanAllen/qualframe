# Reviewed evidence synthesis

Implemented September 10, 2026: preparation, explicitly approved provider execution,
source-linked summary review and immutable JSON export. This is descriptive
within-code synthesis, not automatic theme discovery or publication-ready findings.

1. Complete evidence review for the transcripts to include. In **Analyze evidence**,
   select the sources and freeze a snapshot. Exclusions remain explicit.
2. Choose a scope per transcript or combine the selected transcripts. Prepare the
   plan and inspect the versioned instructions, code definitions and exact passages.
3. Review the configured provider, request count, conservative allowance and study
   ceiling. Enter a reason and explicitly approve transfer/spending, then generate.
4. Refresh the summary review page while the background job runs. Assess each
   statement beside the cited passages. Accept, reject, defer or edit its text and
   citations. Return to an earlier statement using the summary selector.
5. Resolve all proposed statements, then export the reviewed synthesis JSON. It
   preserves the plan, execution configuration, schema, raw-response hashes,
   accepted/edited statements, rejected IDs, latest decisions and complete review history.

Only retained reviewed evidence and the relevant code definitions enter the model
request. Rejected proposals and absence decisions stay in the snapshot audit record.
A snapshot with no retained passages cannot start synthesis. Empty returned summary
sets are reported explicitly and are not exported as evidence of construct absence.
A source file is not assumed to equal one participant; a subset does not represent
the entire study. Custom metadata groups remain pending.

Each job preserves its own input plan, execution record, schema, request inputs,
responses and status under the original coding run's analysis/synthesis directory.
Before every request, the runner checks source/review freshness and configuration.
Stale results remain readable; new decisions and new exports are blocked until a
current reviewed snapshot and synthesis are generated. Prior exports remain historical.

OpenAI Responses/Chat Completions and Anthropic Messages receive the versioned
JSON schema in `config/schemas/reviewed_synthesis_v1.json`. Support depends on the
selected API model. This constrains response structure; local validation additionally
checks that each cited evidence ID belongs to its scope and code. Neither establishes
support in meaning. The researcher still assesses interpretation and missing cases.
See the [OpenAI schema documentation](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Anthropic schema documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
The Anthropic adapter uses the SDK's extra-body support for compatibility with older
installed SDKs. Unsupported models fail explicitly; there is no automatic retry.

Synthesis shares the study cost ledger, reservations and approval boundaries used
by coding. The local allowance includes the schema and output-token limit; it is
not a provider billing guarantee. Unknown usage blocks subsequent paid requests.
Partial or malformed responses and their charges remain preserved. Failed multi-scope
jobs do not yet resume; generate a separately approved new job after addressing the
cause. Starting a replacement never overwrites an earlier response.

Historical AMN prompts are unchanged. The new file-backed synthesis v1 prompt is
separate from the cached five-stage AMN reference workflow, which uses prior-stage
raw outputs and is not the reviewed-input workflow described here.
