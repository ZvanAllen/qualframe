# Repeated coding for within-configuration stability

The browser's **Repeat coding** workspace prepares 2–10 sequential coding runs of
one current configuration on one explicit transcript cohort. It supports the first
per-transcript coding stage, including CFIR domain iterations and generic codebook
partitions. Every repeat has its own run ID, frozen plan, configuration lock,
model artifacts, request usage records and evidence-review index. Preparing or
executing repeats never accepts coding proposals or initiates synthesis.

## Researcher workflow

1. Configure the study's provider, codebook, coding policies and spending ceiling.
2. Open Repeat coding, select transcripts and choose 2–10 repeats.
3. Prepare the plan. Preparation sends no provider requests. Inspect the frozen
   configuration, expected requests, conservative total allowance, study spend and
   remaining budget.
4. Enter the researcher's identity and reason. For OpenAI or Anthropic, explicitly
   approve governed transfer of the selected study data and codebook and the
   remaining spending. The configured API key must be available in this app session.
5. Start the sequence. Refresh progress as needed. One application job runs at a
   time, and an OS-held experiment lock prevents overlapping workers.
6. Inspect source-linked proposals for each run or open the evaluation for the
   entire frozen experiment. Its report includes every planned run, with reasons
   for incomplete or excluded runs; eligible pairs receive descriptive stability
   metrics. Retain unsuccessful runs and exclusions when interpreting results.

## Preservation and recovery

Before each repeat, QualFrame reloads the project and checks the original
configuration fingerprint, transcript file hashes, selected stage and exact
request hashes. Before each provider call, the actual rendered request must match
the frozen forecast. Calls use the existing durable reservations and project usage
ledger. SDK retries are disabled. The sum of conservative allowances for remaining
repeats must fit within the current study ceiling; per-request interval approvals
still apply.

Execution stops on provider failure, unresolved usage, incomplete output,
structured validation failure or a changed input. No later repeat starts. Every
successful repeat receives a completion receipt that binds the plan, manifest,
configuration lock, model artifacts and evidence index by SHA-256. These receipts
are rechecked before completed work is skipped.

Resume is explicit, requires the current unchanged configuration and applicable
approval, and preserves completed repeats and completed transcript artifacts.
If a transcript stopped partway through its domain/partition requests, those
requests restart when that transcript resumes; the earlier response records and
charges remain in the ledger. The remaining allowance counts an incomplete repeat
in full. Unknown request usage must be reconciled before any new paid request.
Malformed completed artifacts are preserved and block continuation; preparing a
new experiment after correcting configuration is a separate decision.

The experiment lock is released by the operating system on process termination.
An interrupted worker therefore does not require deleting its lock file. A
provider request may still have unresolved usage after interruption; releasing the
worker lock never bypasses reconciliation.

## Scope of evidence

Ordinary verification uses synthetic sources and mock responses. Deterministic
mock repetition verifies execution and reporting plumbing and is not empirical
evidence of model stability. The runner does not switch model configurations,
select an optimal model, estimate human-reference validity or provide inferential
statistics. Pairwise comparisons from the same set of repeats are dependent;
agreement is descriptive and does not establish correctness, saturation or
interpretive quality. Real studies need a declared comparison sample and reporting
design before repeated outputs are used for scientific performance claims.

Developer entry points are `prepare_repeats`, `repeat_preflight` and
`execute_repeats` in `qualframe.repeat_execution`. Both preparation and execution
have a no-call `dry_run` option. Experiment metadata stays inside the managed
study's `experiments/` folder, and coding outputs remain under the usual study
artifact and review paths.
