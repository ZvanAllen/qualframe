# QualFrame product one-pager

## Working concept

QualFrame is a **human-supervised, evidence-linked platform** for reproducible AI-assisted directed qualitative content analysis.

It starts with the mature transcript-first CFIR workflow developed in the AMN project and turns the validated engine into a usable local workspace for study setup, calibration, coding, review, analysis, and export. CFIR is the first reference method rather than the permanent product boundary.

## Problem

Many AI-assisted qualitative workflows rely on long prompts, ad hoc chat sessions, and weak provenance. They are difficult to reproduce, audit, review systematically, or adapt across projects.

QualFrame uses a stronger pattern:

- bounded and configurable stages
- exact evidence spans linked to immutable sources
- versioned codebooks, prompts, methods, and model settings
- complete calibration review and configurable later review
- visible model usage and cost controls
- human-owned interpretation

## First product boundary

Build a local-first application for an individual researcher that can:

1. create a study and import transcripts, metadata, and a codebook
2. configure exact-span segmentation, single- or multi-label coding, context, and codebook partitioning
3. human-code and completely review a calibration sample
4. compare real model configurations and lock a versioned analysis protocol
5. run resumable coding with progress, usage, and cost visibility
6. pause for approval before cumulative USD 20 spending thresholds
7. accept, edit, reject, or defer evidence-linked codes
8. explore metadata-defined subgroup patterns
9. export evidence, matrices, review history, and a methods appendix

## Differentiation

QualFrame is not a generic AI chat window. It is designed around:

- framework-aware and method-aware configuration
- evidence-linked coding
- calibration before full-study analysis
- audit-trail-first outputs
- explicit human review
- directed and framework-based qualitative analysis
- usability and performance as first-class requirements

## Current foundation

The repository already contains a working Python runner, provider adapters, versioned prompts, artifact manifests and hashes, deterministic QA, review queues, traceable Excel export, crash recovery, local governance controls, post-parse validation, a loopback dashboard, and a synthetic cached demonstration. Generic directed-analysis method, codebook, evidence-span, coding-cardinality, partitioning, review/analysis/cost-policy, and configuration-lock contracts are also implemented.

The current implementation is still developer-operated and CFIR/AMN-oriented. It is not yet the general researcher-facing platform described above.

## What remains planned

- researcher-facing meaning-unit segmentation and evidence editing
- calibration and post-calibration review workflow integration
- calibration and model-comparison workspace
- normalized provider usage and cost ledger
- USD 20 email approval pauses
- local-first researcher application
- generic metadata analysis and methods export
- later multi-user roles and hosted deployment

## Success criteria

An individual researcher can complete the full workflow through the local interface with synthetic data, repeat calibration with an approved real sample, inspect every code against exact evidence, control spending, review required items, compare study groups, and export a reproducible package without editing Python or YAML.

See `product_specification.md` for the canonical scope and `capability_status.md` for implemented-versus-planned status.
