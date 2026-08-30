# Framework generalization

## Core idea

Generalization comes from separating the **analysis method**, **codebook/framework**, **pipeline**, **prompt set**, **review policy**, **provider profile**, and **analysis plan**. It does not come from renaming CFIR stages or rewriting CFIR prompts by hand for every project.

The first generic method is directed or framework-based qualitative content analysis. CFIR is its mature reference configuration.

## What should vary by framework

- domain list
- construct hierarchy
- roll-up rules
- allowed labels or ratings
- QA rules
- output schemas
- prompt mappings
- default codebook partitioning strategy

## What should stay stable

- project manifest
- artifact logging
- provider adapter interface
- run planning
- review queue
- provenance capture
- exact evidence-span representation
- usage and cost accounting

## What should vary by project

- segmentation strategy
- exact context-window policy
- single-label or multi-label coding
- overlapping-span policy
- full-codebook, top-level-category, or custom code groups
- calibration sample and promotion criteria
- complete, risk-based, or random review policy
- metadata dimensions and planned comparisons
- provider/model configurations and spending ceiling

## Good next frameworks after CFIR

Once CFIR is stable, likely candidates include:
- TDF
- NPT
- RE-AIM determinant or planning workflows
- project-specific codebooks

## Recommended implementation pattern

Define the directed-analysis method separately from each codebook/framework. Use a framework YAML spec and prompt-set mapping, and create stage adapters only when a framework needs special handling.

Treat current AMN stages as follows:

- six CFIR domain calls: `per_top_level_category` partitioning, enabled by default for CFIR
- construct roll-up: optional hierarchical aggregation
- quote-context enrichment: configurable context capture with exact evidence stored separately
- network synthesis: grouping by a project metadata field
- cross-network synthesis: optional cross-group analysis

That allows:
- strict deductive mode
- hybrid mode
- exploratory mode

without changing the entire software package.
