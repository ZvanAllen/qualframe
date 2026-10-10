# QualFrame product specification

## November 2026 release scope (owner decision, September 7)

The first public beta serves research teams through one operator per study on Windows and macOS, with local storage and user-supplied API keys. Excel codebooks and inter-configuration agreement/within-configuration stability are first-release priorities. Human-reference calibration, validated model promotion, and sampled review are subsequent extensions; sections describing those workflows below are future targets, not prerequisites or completed validation for this beta. Complete human review remains the initial release policy. Tutorial: November 11; demo freeze: October 28. See `decisions/0006-public-beta-scope.md` and `workplan_2026-09-07.md`.

## Status and authority

This document defines the agreed target product. The Python implementation and verified runs remain authoritative for claims about what currently works. `docs/capability_status.md` distinguishes implemented, validated, and planned capabilities.

## Vision

QualFrame is a human-supervised workspace for reproducible, evidence-linked, AI-assisted directed qualitative content analysis.

CFIR is the first mature reference method. The product is intended to support broader deductive and framework-based analysis through configurable methods, codebooks, coding policies, review policies, and analysis plans.

QualFrame is not a generic transcript chatbot and is not a transcript-to-publication autopilot.

## Initial user

The first product is designed for a research team working through one local operator who needs to:

- set up a study without editing source code
- import transcripts, metadata, and a codebook
- compare agreement and stability across frozen model runs
- configure and lock a reproducible analysis protocol
- run and monitor model-backed coding
- review exact evidence spans and adjudicate flagged items
- explore code patterns across study groups or time points
- export evidence, matrices, review history, and methods metadata

Multi-user roles and permission restrictions are later extensions. In the initial version, the researcher may lock configurations, approve continued spending, review outputs, and release exports.

## Methodological scope

The first supported product category is broad deductive or framework-based qualitative content analysis, including directed content analysis. A project supplies an initial codebook or framework rather than asking the model to invent findings or an unconstrained thematic structure.

The product must support:

- flat or hierarchical codebooks
- single-label or multi-label coding
- exact, traceable evidence spans
- configurable meaning-unit segmentation
- optional codebook partitioning across multiple model calls
- optional hierarchy roll-up
- configurable surrounding-context policies
- project-defined participant or study metadata
- complete or sampled post-calibration review
- framework-specific QA rules and output schemas

Hybrid and exploratory analysis may be added later but must be labeled separately from directed analysis.

## Current foundation

The repository currently contains a working developer-operated Python engine, a CFIR transcript-first reference pipeline, provider adapters, versioned prompts, artifact hashing and manifests, deterministic QA, review queues, Excel export, crash recovery, local governance controls, post-parse structured validation, and a loopback-only dashboard.

The current AMN pipeline remains a protected reference implementation. Its network labels, prompt wording, source files, and analysis artifacts must not be silently generalized or rewritten.

## Target product boundary for the first usable release

The first usable product will support one local researcher and one study at a time with:

1. local study creation
2. transcript and metadata import
3. flat or hierarchical codebook import
4. a CFIR template and a generic directed-analysis template
5. configurable segmentation, context, coding cardinality, and codebook partitioning
6. a frozen comparison sample
7. low-cost provider-backed functional execution
8. per-code agreement and within-configuration stability comparison
9. a locked, versioned analysis configuration
10. resumable background coding with progress and cost visibility
11. exact evidence-span review with accept, edit, reject, and defer actions
12. complete evidence review; sampled policies are later work
13. subgroup code matrices and evidence retrieval
14. traceable Excel and JSON export with a methods appendix
15. pre-call cost approvals at cumulative USD 20 intervals

## Confirmed product decisions

### Local-first application

The first end-user product is a local-first browser application. The Python engine remains authoritative for execution and provenance. Local application state may use SQLite, while immutable run artifacts remain file-backed and hashed. Hosting, accounts, and multi-tenant cloud storage are not part of the first release.

### Evidence and meaning units

The canonical analytic object is an exact transcript evidence span with stable source offsets. A meaning unit may be proposed by a model or imported from researcher-presegmented data and may be edited during review without overwriting the source transcript.

Surrounding context is stored separately from the exact coded span. A reviewer must always be able to distinguish quoted evidence, context, code assignment, and model rationale.

### Coding cardinality

Projects choose either:

- `single_label`: exactly one code assignment per meaning unit
- `multi_label`: one or more code assignments per meaning unit

Overlapping spans are supported as a configurable policy. Optional maximum-code constraints may be added at project level.

### CFIR codebook partitioning

The AMN experience found one model call per CFIR top-level domain necessary for sufficient quality with GPT-5.1 Pro. CFIR therefore defaults to per-domain calls. This is an empirical reference-method decision, not a universal rule.

Other projects may choose one pass over the full codebook, one pass per top-level category, or researcher-defined code groups. The selected strategy is part of the locked analysis configuration and run manifest.

### Review and release

Complete human review is the first-release default. Human-reference calibration and sampled review policies are later extensions. No role-based restriction is applied initially, but all lock, approval, review, and release actions are timestamped and append-only.

### Codebook evolution

Changing a locked codebook creates a new version. Existing artifacts are never silently rewritten. The system identifies affected material and requires an explicit rerun or documented decision not to rerun.

### Providers and spending

Subscription-based Codex or chat tools may support product development and supervised setup work. Reproducible qualitative analysis uses configured provider APIs so the model, request settings, usage, cost, and response artifacts can be recorded.

The system pauses before a request expected to cross each cumulative USD 20 threshold, sends an email notification through a configured notification adapter, and requires an explicit approval action before continuing. Provider credentials and notification addresses are never committed.

## Product principles

1. Evidence traceability is a visible user benefit, not hidden plumbing.
2. Human interpretation remains visibly human-owned.
3. Configuration changes create versions rather than mutating completed work.
4. UX, methodological quality, and performance are equal product requirements.
5. The interface uses progressive disclosure; researchers should not need to browse technical artifact folders.
6. Live model calls are explicit, budgeted, resumable, and auditable.
7. Synthetic fixtures power tests and public demonstrations.
8. Real research data follows project-level consent, institutional policy, provider, retention, and repository rules.
9. Public materials distinguish implemented, validated, experimental, and planned capabilities.

## Initial non-goals

- multi-user authentication and role-based authorization
- cloud hosting or multi-tenant deployment
- automatic publication-ready findings
- autonomous interpretation without researcher review
- universal support for inductive thematic analysis
- automatic acceptance of model confidence as calibrated certainty
- running every model configuration over a full study before calibration

## Success criteria

The first release is successful when an individual researcher can complete the end-to-end workflow through the local interface using synthetic data, repeat it with an approved provider-backed comparison sample, understand progress and spend, inspect every code against exact evidence, review required items, compare metadata-defined groups, and export a reproducible methods and evidence package without editing Python or YAML.
