# Review completion and synthesis workflow — September 9, 2026

## Current behaviour

The focused reviewer saves append-only accept, edit, reject, and defer decisions. Once every proposal is resolved, the reviewed JSON/Excel export becomes available, subject to the study's release rules. Completion does not automatically call a model or generate findings. The current 1A study stops at coding for review.

Typography-only CFIR matches can now be confirmed with Accept and next. This rechecks the unique source location and exact stored span; unresolved quotes or unknown constructs still require correction. Existing indexes and raw quotations remain unchanged. The original formatting diagnostic stays in technical provenance. Reviewer identity is retained per study after a successful decision and can be changed explicitly. Model quotations and explanations are expanded by default; the edit-code selector is always visible.

## Proposed study progress view (not implemented)

Use an explicit selected analysis version/run set, never sum repeated model runs as new transcripts. Show imported transcripts, coding completed/failed/not started, proposals awaiting review, accepted/changed/rejected/deferred counts, and transcripts with all proposals resolved. Include a transcript table with Resume review actions and a separate synthesis-readiness state.

Derive coding completion from successful stage artifacts, not from whether any code was found. A transcript with zero proposals needs an explicit no-evidence review checkpoint; zero proposals must not silently mean reviewed. A partial domain run is not a completed transcript. Keep prior model configurations visible through a run selector and distinguish them from the selected study analysis.

## Proposed post-review workflow (not implemented)

1. Finish review for the selected transcripts. Deferred or unresolved proposals block inclusion. Allow an explicitly selected subset, with excluded sources recorded.
2. Freeze a reviewed-evidence snapshot. Include accepted source spans and latest edited assignments; exclude rejected proposals. Keep absence decisions separately, not as quoted evidence. Record review-action IDs, source/codebook/configuration hashes, and snapshot identity.
3. Explore a construct-by-case/group matrix linked to source passages. Counts describe coding coverage, not importance or prevalence without a defined denominator.
4. Choose synthesis scope and grouping: participant/case, site/network, or all selected transcripts. AMN network is a study-specific metadata option. Parent roll-up and context expansion remain optional and preserve the exact evidence span separately.
5. Preview the versioned synthesis instructions, included evidence, provider, call count, and cost. Explicitly start a new synthesis job. Do not resume the historical raw-output pipeline as a shortcut for reviewed-data synthesis.
6. Review AI-proposed construct summaries, patterns, variations, and negative cases with links to every supporting evidence record. Researcher memos and themes remain distinct from generated suggestions. Require accept/edit/reject decisions before promoting a summary into the findings workspace.
7. Export reviewed coding, reviewed synthesis, supporting evidence links, review history, and methods metadata. Later coding edits create a new snapshot and flag dependent syntheses as stale.

## Existing reference assets

`config/pipelines/transcript_cfir.yaml` defines coding, participant parent-construct roll-up, context enrichment, participant-to-network synthesis, and cross-network synthesis. `prompts/cfir/final/04_group_level_synthesis.md` combines participant evidence by CFIR construct; `05_final_synthesis.md` explicitly names eight AMN networks. These are preserved reference assets, not generic theme-generation prompts. The runner currently passes previous-stage model artifacts; a reviewed-evidence input adapter and new versioned prompts are required for the proposed workflow.

## Recommended implementation order

Study progress with explicit run/version selection; reviewed snapshot and export checkpoint; evidence-linked matrix; configurable within-group synthesis; cross-group synthesis with human review and stale-result tracking. Keep the agreement/stability evaluation work separate from human synthesis decisions and compare the frozen raw model outputs as planned.

## Framework library

The current study's CFIR definitions come from its already imported workbook and frozen review catalog. They are not yet a bundled library for every new installation. A built-in CFIR option should identify framework edition, attribution, source, and version/hash while preserving custom workbook import. Other frameworks can follow the same versioned-library design later.

Verification: 147 tests passed, one skipped; both offline demos passed. Browser checks confirmed enabled acceptance for the existing normalized proposal, visible code selection, remembered reviewer from prior actions, and desktop/narrow layouts without horizontal overflow. No live model calls or research adjudications were made during these checks.

Study progress implementation checkpoint: selected-run overview delivered; 149 tests passed, one skipped; offline demos passed. Desktop and 390px browser checks verified the real study's 5/203 resolved count and resume link. Transcript-level failure diagnosis and zero-proposal review checkpoints remain future work; these cases are not shown as fully reviewed.
