# Model evaluation and cost control

## Purpose

QualFrame must demonstrate that provider-backed analysis works with real models while keeping model selection evidence-based, reproducible, and financially controlled.

Provider documentation and pricing change over time. Model identifiers, capabilities, effort controls, and pricing must be reviewed at test time and stored as dated snapshots rather than treated as permanent documentation facts.

## Two test modes

### Functional smoke test

Purpose: verify request submission, response handling, usage capture, validation, provenance, QA routing, resume, and export.

- use the cheapest appropriate generally available model
- use synthetic fixtures by default
- run the smallest representative stage and input
- do not infer methodological quality from a successful smoke test

### Calibration benchmark

Purpose: compare model configurations against a reviewed human-coded calibration set.

A configuration includes provider, exact model identifier, effort or thinking controls, prompt version, structured-output settings, codebook partitioning, context policy, and sampling parameters.

The eventual benchmark matrix should cover relevant generally available OpenAI and Anthropic models and their supported effort levels. It should not run every configuration over a full study before screening.

## Sequential benchmark design

1. Run every candidate configuration on a small synthetic challenge set.
2. Eliminate configurations that fail basic evidence, schema, or stability requirements.
3. Run surviving configurations on an approved human-coded calibration sample.
4. Complete human review of all calibration results.
5. Compare quality, revision burden, latency, and cost.
6. Promote the least expensive configuration meeting declared criteria.
7. Consider selective escalation for ambiguous or failed items only when evaluation shows a benefit.

## Evaluation dimensions

At minimum, record:

- exact evidence-span validity
- codebook fidelity
- per-code precision and recall where the reference design permits them
- false-positive and false-negative patterns
- unitization or segmentation disagreement
- multi-label cardinality errors
- unsupported rationale rate
- schema and QA failure counts
- human accept, edit, reject, and defer rates
- revision burden and review time
- latency and failure/retry rate
- input, cached-input, output, and reasoning usage where reported
- estimated and reconciled cost

Kappa or alpha may be reported only where the unit of analysis and rater design make the statistic defensible. No single accuracy score should hide rare-code or boundary failures.

## Provider-neutral configuration

QualFrame preserves provider-specific settings rather than implying that all reasoning controls are equivalent. A normalized benchmark record may contain:

- `provider`
- `model_id`
- `model_snapshot`
- `effort_mode`
- `effort_value`
- `thinking_mode`
- `thinking_budget`
- `temperature`
- `max_output_tokens`
- `structured_output_mode`
- `prompt_cache_mode`

Unsupported settings are recorded as unavailable rather than silently ignored.

## Usage ledger

**Current implementation:** executed requests append normalized available usage, request/response identity, a pre-call estimate, the dated pricing snapshot, calculated cost, and run/project totals to the local JSONL ledger. OpenAI, Anthropic, Google, mock, and cached adapters use the same usage contract. Provider retry-attempt lineage, latency, provider-billing reconciliation, and live pricing snapshots remain to be implemented or verified before a model benchmark. The only checked-in pricing snapshot is a zero-cost mock fixture.

Every provider request records request and response identifiers; study, run, stage, source, and configuration identifiers; provider and model; timestamps and latency; reported usage; pricing snapshot; pre-call estimate; post-call calculated cost; provider-reported cost when available; retry lineage; and cumulative run and study cost.

Provider cost data is periodically reconciled against official usage records when available. Local calculations remain labeled as estimates until reconciled.

## Cost approval policy

**Current implementation:** cost-controlled projects must configure a paired cost policy and exact provider/model pricing snapshot. `qualframe run` fails closed above the absolute ceiling and persists `cost_pause.json` before an unapproved interval crossing. `qualframe approve-cost` appends an `approve` or `stop` action; approval never occurs by email. SMTP delivery is implemented but has not been live-tested.

The initial default is a cumulative USD 20 approval interval.

Before each external request:

1. estimate the maximum reasonable cost of the request
2. compare projected cumulative spend with the next threshold and absolute project ceiling
3. persist a pending approval and pause before sending if the request may cross a boundary
4. attempt email notification through the configured adapter
5. require an explicit local approval action before continuing
6. execute the approved request and reconcile actual usage
7. advance the next threshold by USD 20

An API request cannot be interrupted safely after submission solely to satisfy a cost boundary. Pre-call reservation reduces but cannot eliminate estimate variance.

## Email notifications

Notification addresses and sender credentials are secrets or local settings and are never committed. Repository examples contain environment-variable names only.

The notification contains the threshold, current and projected spend, study and run identity, paused status, and local approval instructions. Delivery failure does not approve or resume a run.

## Safety and automation boundaries

- No live API model calls occur in ordinary unit tests or continuous integration.
- Cached or mock providers cover deterministic tests.
- Live benchmark commands are explicit and cost-gated.
- Public demonstrations use cached synthetic results by default.
- Real transcripts require the active project's governance approval and provider configuration.
- Provider keys, notification addresses, and pricing credentials are excluded from manifests and exports.
- Each live run requires an explicit absolute project ceiling in addition to interval approvals.

## Promotion record

A model configuration becomes a project default only through a versioned promotion record containing the calibration set, codebook version, metrics, known failure patterns, reviewer decision, date, pricing snapshot, and scope of intended use.

Passing a functional smoke test is never described as validation for qualitative analysis quality.
