# QualFrame capability status

Implementation claims must be supported by code and verified runs. This file is a concise status map; implementation and test evidence remain authoritative.

Status terms:

- **Implemented** — present in the local codebase.
- **Validated** — exercised successfully in the stated environment or fixture scope.
- **Reference-only** — works for the AMN/CFIR method but is not yet generalized.
- **Planned** — agreed target with no completed general implementation.

## Current capabilities

Public snapshot update (2026-08-30): the local workspace now uses a shared responsive interface with source/context and review panels, an evidence queue, explicit classification/provider badges, and a synthetic no-network launcher. This is a presentation and reproducibility improvement, not new methodological validation. See `verification.md` for release checks.

| Capability | Status | Boundary |
|---|---|---|
| Typed project/framework/pipeline configuration | Implemented | Current schemas remain CFIR-oriented in places |
| Anthropic, OpenAI, Google, mock, and cached-demo adapters | Implemented | Provider availability and credentials vary |
| Dry-run, filters, resume, and crash recovery | Implemented | Python runner is authoritative |
| Versioned prompts, request artifacts, hashes, and manifests | Implemented | Existing file-backed artifact model |
| Deterministic QA and review-queue routing | Implemented | Rules vary by stage and framework |
| Excel export with traceability | Implemented | Current exports follow existing parsed formats |
| Enforced stage gates and release controls | Implemented | Opt-in, local single-user controls |
| Explicit disagreement comparison | Implemented | Does not automatically run multiple coders or models |
| Append-only adjudication actions | Implemented | Local workflow, no role authorization |
| Post-parse structured validation | Implemented | Provider-native constrained generation is not implemented |
| Loopback researcher workspace | Validated | Study creation, bounded imports, core method editing, preflight, background mock/cached execution and resume, run/review/export views, and cost-pause decisions; still incomplete and local-only |
| Safe browser-started execution/resume | Validated | Managed studies only; background progress for `mock` and checked-in `cached_demo`; external API providers remain CLI-only and cost-gated |
| Synthetic cached interview demo | Validated | Demonstration fixtures only |
| AMN transcript-first CFIR pipeline | Reference-only | Contains AMN network and stage assumptions |
| Generic directed-analysis method and policy models | Implemented | Typed configuration contracts; no calibration UI yet |
| Versioned flat/hierarchical codebook model | Implemented | YAML loading, hierarchy validation, and stable IDs |
| Exact meaning-unit, evidence-span, and assignment models | Validated | Generic offset-bearing coding rows materialize against immutable source hashes; legacy CFIR table normalization remains planned |
| Exact-evidence review workspace | Validated | Highlights exact source wording and separate context; shows code guidance, rationale, and provenance; accept/edit/reject/defer actions are append-only. Numeric offset editing is the bounded first UX |
| Reviewed evidence JSON/Excel package | Validated | Export is blocked until every evidence item is resolved; includes evidence, review history, hashes, configuration identity, and methods fields; not an automatic findings report |
| Single-label and multi-label validation | Implemented | Assignment-set enforcement is project-configurable |
| Full, top-level-category, and custom codebook partitioning | Implemented | Deterministic contract helper; CFIR defaults to top-level domains |
| Analysis configuration fingerprint and lock artifact | Validated | Method, codebook/framework, pipeline, prompts, provider, review, analysis, and cost assets are hashed |
| Generic synthetic contract project | Validated | Mock-only plan and execution; prompt is not validated for research use |
| Normalized provider usage and cost ledger | Validated | OpenAI, Anthropic, Google, mock, and cached adapters normalize available usage; deterministic tests verify pricing and cumulative totals; retry-attempt lineage remains planned |
| Pre-call cost ceilings and interval approvals | Validated | Exact provider/model pricing is required; projected crossings pause before submission and local approve/stop actions are append-only; only a zero-cost mock pricing snapshot is checked in |
| Email notification adapter for cost pauses | Implemented, unverified delivery | SMTP configuration stays local; missing or failed delivery preserves the pause and never approves execution |
| Local study creation with declared classification | Validated | Browser flow creates a study-specific manifest and versioned method without YAML editing |
| Validated local source import and source manifest | Validated | Non-overwriting TXT/DOCX transcripts, YAML codebooks, and UTF-8 CSV metadata are copied/versioned, hashed, and recorded; no bulk mapper or rich designer |
| Core researcher method-policy editor | Validated | Versions segmentation, context, single/multi-label, overlap, and full/per-top-level partition settings; CFIR domain iteration remains enforced by its reference pipeline |
| Generic method policy enforcement in execution | Validated | Generic requests receive the chosen policy; partitioning changes actual call fan-out; parsed code/cardinality violations route to review. Provider-native schema enforcement and complete offset checking remain planned |
| Researcher-facing dry-run preflight | Validated | Shows inputs, planned stage calls, provider safety mode, and configuration identity without model execution |

## Confirmed target capabilities

| Capability | Status | First boundary |
|---|---|---|
| Local-first researcher application | Partial | Study setup/import, core method configuration, preflight, safe local execution/resume, generic exact-evidence review/export, run inspection, and cost decisions exist; calibration and legacy CFIR evidence normalization do not |
| Researcher-facing generic method configuration | Partial | Core coding policy is editable and versioned; provider, review, analysis, cost, and custom partition-group editors remain planned |
| Evidence-span coding and editing workflow | Partial | Generic source-linked review and derived edits are validated; direct span-selection UX, calibration coding, and legacy CFIR normalization remain planned |
| Calibration workspace and full calibration review | Planned | Human-coded reference sample |
| Provider/model/effort benchmark harness | Planned | Sequential screening before full-study runs |
| Risk-based, random, or complete post-calibration review | Planned | Individual researcher selects policy |
| Generic metadata group analysis | Planned | Matrices, comparisons, and evidence retrieval |
| Traceable methods appendix | Planned | Configuration, review, model, and provenance details |

## Explicitly later

- authenticated multi-user roles and permissions
- hosted multi-tenant service
- provider-native structured-output enforcement across all adapters
- automatic exhaustive parallel model execution over full studies
- inductive thematic-analysis product mode
- automatic publication-ready interpretation

Update this file whenever a capability crosses a status boundary. Do not mark a capability validated solely because its code exists.
