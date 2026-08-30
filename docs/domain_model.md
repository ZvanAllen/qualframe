# QualFrame domain model

## Purpose

This document defines the stable product concepts that should remain consistent across the Python engine, local application, configuration files, database indexes, artifacts, review queues, and exports.

## Configuration layers

QualFrame separates concerns that are currently combined in the AMN CFIR configuration:

1. **Study manifest** — project identity, paths, data governance, metadata fields, and selected configuration assets.
2. **Method specification** — directed-analysis policies such as segmentation, coding cardinality, context, calibration, and review.
3. **Codebook or framework specification** — codes, definitions, hierarchy, examples, exclusions, allowed labels, and framework-specific QA.
4. **Pipeline specification** — ordered and optional execution stages.
5. **Prompt set** — versioned mappings from task identifiers to file-backed prompts.
6. **Provider profile** — provider, exact model or snapshot, provider-specific effort settings, output limits, and retry policy.
7. **Analysis plan** — metadata dimensions, comparisons, matrices, negative-case rules, and requested exports.
8. **Cost policy** — currency, approval increments, project ceiling, notification adapter, and reconciliation rules.

The locked analysis configuration references immutable versions or hashes of all eight layers.

## Core objects

### Study

A local research project containing sources, metadata, codebooks, configurations, runs, reviews, analysis outputs, and exports.

Required identity fields:

- `study_id`
- `title`
- `created_at`
- `data_classification`
- `governance_profile`

### Source document

An immutable imported transcript or approved source file.

Required provenance fields:

- source identifier
- original filename and media type
- SHA-256 hash
- import timestamp
- participant or case identifier
- source text encoding
- metadata linkage

Source content is never overwritten. Corrections create a new source version with explicit lineage.

### Study metadata

Researcher-defined attributes associated with a participant, case, transcript, site, group, or time point. AMN networks become one example of a metadata field rather than a core platform concept.

Metadata definitions record name, type, allowed values, missing-value policy, and whether the field may appear in exports.

### Codebook version

An immutable version of a flat or hierarchical directed-analysis codebook.

Each code may contain:

- stable code identifier
- display label
- parent identifier
- definition
- inclusion guidance
- exclusion guidance
- examples
- optional valence or rating labels
- active or retired status

Changing a locked codebook creates a new version and never mutates prior run provenance.

### Analysis configuration version

A complete, immutable snapshot of the method, codebook, pipeline, prompts, provider profile, analysis plan, review policy, and cost policy used for a run.

Suggested states:

- `draft`
- `calibrating`
- `calibration_review`
- `locked`
- `superseded`

Locking is permitted for the individual researcher in the first release. Every transition is recorded.

### Meaning unit

A bounded unit of transcript content considered for coding. It may be:

- imported from researcher-presegmented data
- proposed automatically from sentences or paragraphs
- proposed by a model
- created or adjusted during review

A meaning unit retains exact source offsets and may contain one or more evidence spans.

### Evidence span

The canonical evidence-linked object. It identifies the exact source text supporting a code assignment.

Required fields:

- stable span identifier
- source document identifier and hash
- start and end offsets
- exact source text hash
- speaker label when available
- separately stored context-window offsets
- creation method and version

The exact span, surrounding context, and model rationale are distinct fields.

### Code assignment

The application of one codebook code to one meaning unit or evidence span.

Required fields:

- assignment identifier
- evidence or meaning-unit identifier
- codebook version and code identifier
- assignment origin: human, model, imported, or adjudicated
- provider, model, prompt, schema, and run provenance when model-generated
- optional rationale
- validation and review state

Project policy determines cardinality:

- `single_label`: one assignment per meaning unit
- `multi_label`: multiple assignments permitted

Overlap between spans is independently configurable.

### Calibration set

A versioned subset of source material with human-coded assignments and completed human review. It is the reference set for comparing candidate model configurations.

The set records sampling method, human coding status, adjudication status, codebook version, and evaluation results. It should not be described as a universal gold standard unless the research method supports that claim.

### Model configuration

A provider-specific execution configuration, not just a model name.

It records:

- provider and exact model identifier or snapshot
- API endpoint or adapter version
- reasoning, effort, or thinking configuration
- temperature and sampling settings
- maximum output
- structured-output capability and selected schema
- prompt-caching settings
- pricing snapshot identifier

Provider-specific controls are preserved rather than forced into a misleading universal scale.

### Run

A resumable execution of a locked configuration over a declared input set.

Suggested states:

- `planned`
- `running`
- `paused_for_cost_approval`
- `paused_for_review`
- `failed_recoverable`
- `completed`
- `released`

A run owns a manifest, plan, request records, raw responses, parsed artifacts, QA results, review links, usage ledger, and hashes.

### Provider request

One external or cached provider interaction. It records request identity, inputs by hash, prompt hash, provider settings, timestamps, latency, retry lineage, response identity, token usage, estimated cost, actual cost, and error state.

### Cost threshold and approval

A cumulative spending boundary within a study or run. The initial default interval is USD 20.

Before a request expected to cross a threshold, QualFrame creates a pending approval, pauses the run, and attempts the configured notification. Approval is append-only and records threshold, estimate, actor, timestamp, and decision. Notification delivery failure does not silently approve spending.

### QA finding

A deterministic or model-assisted concern linked to an artifact, evidence span, assignment, configuration, or run. It records rule version, severity, evidence, and routing outcome.

Model-reported confidence may be stored but is not treated as calibrated probability by default.

### Review item

A queue entry created by calibration requirements, complete-review policy, risk rules, random sampling, disagreement, schema failure, or manual routing.

### Review action

An append-only accept, edit, reject, defer, comment, lock, cost approval, or release action. Edits create derived records and preserve the original model output.

### Analysis output

A reproducible view computed from reviewed or explicitly selected assignments. Examples include code-by-group matrices, code frequencies, co-occurrence, negative cases, evidence tables, and comparisons across metadata values or time points.

AI-assisted narrative suggestions remain labeled as suggestions until incorporated into a human-authored memo.

### Export and release

An export packages selected evidence, matrices, review history, configuration hashes, and methods metadata. Release records who initiated the export and which reviewed configuration and run it represents. Initial release is not role-restricted.

## CFIR reference-method mapping

- CFIR domains map to top-level codebook categories.
- Six per-domain model calls map to the `per_top_level_category` partition strategy.
- Participant construct roll-up maps to optional hierarchical aggregation.
- Quote context enrichment maps to a context policy; exact evidence remains separate.
- AMN network synthesis maps to metadata-defined grouping.
- Cross-network synthesis maps to optional cross-group analysis.

The existing AMN pipeline remains valid and does not need to be rewritten before the generic contracts are implemented.

## Storage direction

The first product remains local-first:

- immutable source and run artifacts: file-backed and hashed
- operational indexes, UI state, and append-only actions: local SQLite
- human-readable exchange: Excel, CSV, and methods documents
- machine-readable exchange: JSON and YAML

The artifact store remains authoritative for reproducibility. SQLite must not become the only copy of evidence or run provenance.
