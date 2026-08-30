# QualFrame user workflows

## Experience goal

An individual qualitative researcher should be able to complete a governed directed-analysis workflow without writing code, editing YAML, or navigating artifact folders. Technical provenance remains available through evidence and methods views rather than dominating the primary interface.

The first application is local-first and opens in a browser. UX quality, methodological clarity, and performance are equal acceptance concerns.

## Workspace 1: Set up and calibrate

**Current implemented slice:** the loopback workspace creates a local study from the generic directed-analysis or CFIR template; records synthetic/deidentified/sensitive classification; imports and hashes bounded transcript/codebook/metadata formats; versions core method policies; creates no-call preflight plans; runs managed mock/cached work in the background; and reviews/exports source-linked generic evidence. Calibration coding and the remaining provider/review/analysis/cost editors remain planned.

### Create a study

The researcher names the study, chooses a data-classification profile, and sees a clear statement of what stays local and what may be sent to a configured provider.

### Import sources and metadata

The researcher imports transcripts and a metadata table. QualFrame validates identifiers, duplicate files, hashes, encodings, missing metadata, and unsupported formats before analysis.

### Import or select a codebook

The researcher may choose the CFIR template or import a flat or hierarchical codebook. Definitions, examples, exclusions, hierarchy, and allowed labels are previewed before use.

### Configure coding

The researcher chooses:

- segmentation strategy
- exact context window
- single-label or multi-label coding
- overlapping-span policy
- full-codebook, top-level-category, or custom codebook partitioning
- provider and model configuration
- calibration sample
- post-calibration review policy
- metadata dimensions for later analysis

CFIR defaults to one coding pass per domain because that strategy produced sufficient quality in the AMN GPT-5.1 Pro work. The UI explains that the setting is configurable rather than presenting it as universal.

### Human-code the calibration sample

The researcher codes or imports human coding for the selected sample. QualFrame provides exact-span tools and codebook guidance.

### Run candidate models

The researcher first performs a low-cost functional check, then may run a configured benchmark matrix. The interface shows configurations, progress, latency, token use, cost, validation failures, and per-code comparisons.

### Complete calibration review and lock

All calibration items require human review in the first release. The researcher resolves disagreements, may revise the draft codebook or settings, and then locks a new analysis configuration version. Revising a locked configuration creates another version.

## Workspace 2: Run and review

### Preflight

Before live execution, QualFrame shows:

- transcript and call counts
- selected provider configurations
- estimated cost range
- next approval threshold
- review policy
- data-governance confirmation
- exact configuration version and hashes

### Run and monitor

Coding runs in resumable background work. The interface reports completed, active, queued, paused, failed, and review-required work without exposing raw logs as the primary progress view.

The researcher may close and reopen the local interface without losing completed work. Retry and resume preserve request lineage.

### Cost approval

When the next request may cross a USD 20 cumulative threshold, the run pauses. QualFrame shows the estimate, spend to date, next work item, and remaining project ceiling; it also attempts the configured email notification. The researcher approves or stops the run through an append-only action.

### Review evidence

The main review screen shows:

- exact highlighted evidence
- surrounding transcript context
- assigned code or codes
- codebook definition and guidance
- model rationale when present
- provenance and QA reasons in an expandable panel

The researcher may accept, edit, reject, defer, or comment. Edits never overwrite the source evidence or raw model response.

**Current implemented boundary:** accept, edit, reject, and defer are available for generic offset-bearing artifacts. Exact offsets and source hashes are revalidated, context remains separate, and edits create derived span/assignment records. Comment-only actions, direct text-selection editing, and legacy CFIR row normalization remain planned.

### Review policies

After calibration, a project may require:

- complete review
- deterministic risk queues
- disagreement queues
- random quality-control samples
- combinations of these policies

Model-reported confidence is one possible signal and is not treated as calibrated certainty.

## Workspace 3: Analyze and export

### Explore reviewed coding

The researcher filters by code, participant, source, metadata field, review status, provider configuration, or run version. The interface supports code-by-group matrices, co-occurrence, negative-case retrieval, and comparisons across groups or time points.

Every aggregate links back to the underlying evidence spans.

### Write memos

QualFrame may help retrieve evidence or suggest a draft structure, but memos and findings remain human-authored. AI-generated suggestions are visibly labeled and are not automatically promoted to findings.

### Release and export

The researcher selects a reviewed run and creates an export containing chosen tables, evidence, matrices, review summaries, and a generated methods appendix. Initial release is not role-restricted, but the action is recorded.

**Current implemented boundary:** a fully resolved generic evidence review can create parallel JSON and Excel packages containing reviewed coding, review history, source/artifact/prompt hashes, configuration identity, and bounded methods metadata. Matrices and the full generated methods appendix remain planned.

## Target public demonstration workflow (not fully implemented)

The target demonstration uses synthetic fixtures. The full story below remains a design target; calibration and subgroup matrices are not implemented. The current runnable demos are described in the root README.

1. create a study
2. select CFIR
3. inspect the per-domain coding strategy
4. compare a human-coded calibration sample with a low-cost model
5. lock the configuration
6. run coding and inspect progress and cost
7. resolve a deliberately flagged evidence item
8. view a subgroup matrix linked to evidence
9. export a methods and evidence package

Cached results remain available so the demonstration does not depend on network or model availability.

## UX and performance requirements

- Primary actions use research language rather than engine terminology.
- Long work is backgrounded, resumable, and visibly progressing.
- Tables remain responsive through pagination or virtualization.
- Errors identify the affected item and recovery action.
- Evidence, interpretation, AI suggestion, and simulation are visually distinct.
- Synthetic/demo status is always visible.
- Keyboard navigation and accessible labels are required for core workflows.
- The interface must not imply that configuration is locked, review is complete, or an export is released unless the underlying engine confirms it.
