# UI/UX assessment and improvement plan — September 8, 2026

## Scope and conclusion

Assessment of the running local application: overview, study creation, source import, configuration, and exact-evidence review. Evidence includes live page structure and a desktop review screenshot using synthetic API results. No user decisions were changed. This is an expert walkthrough, not a participant usability study or WCAG conformance certification. Large-study performance and assistive-technology behavior remain unmeasured.

The interface has a coherent visual foundation. The most valuable next investment is a clearer study workflow and faster evidence review. A cosmetic redesign alone would leave the main obstacles intact.

## What to retain

- Quiet green palette, readable quotations, distinct evidence highlighting, and separate researcher decision panel.
- Visible study classification and provider state; explicit distinction between AI proposals and human interpretation.
- Source-linked evidence, expandable provenance, versioned changes, and reviewed-export gating.
- Semantic headings, labelled controls, navigation landmarks, and a skip link visible in the inspected page structure.

## Observed findings and priorities

| Priority | Observed behavior | Consequence and proposed improvement | Acceptance criterion |
|---|---|---|---|
| P0 | Overview shows `completed`, `not_required`, and “No queued review items” while evidence review shows 0/2 resolved. | Execution, automated QA, human review, and release are different states. Show each explicitly with one next action. | An unreviewed run says “Coding finished · Human review pending”; QA success never implies research readiness. |
| P0 | Overview offers raw Excel exports; the review page blocks reviewed exports until all items are resolved. | Distinguish “Raw model output — unreviewed” from “Reviewed evidence package” wherever downloads appear. | Every download has a review status; unresolved evidence blocks only the reviewed package and explains why. |
| P0 | New-study page still displays the current study’s classification/provider badges; Synthetic is the default classification. | Separate application navigation from the study being created. Require an intentional choice between a demo and real research setup. | A researcher cannot mistake the old study’s badges for the new study’s configuration. |
| P1 | Source library shows counts and upload forms, but no list of the imported transcripts or active codebook. | Add a searchable source inventory, transcript preview, metadata coverage, active codebook tree, and version history. | After import, users can find the source, inspect extracted text, and identify the active codebook without filesystem access. |
| P1 | No visible open-study selector; run choice is on overview, with technical run IDs. | Add open/recent studies, readable run names, and persistent selected study/run context. | Users can reopen a study and navigate to the same run’s review/export without changing context accidentally. |
| P1 | Evidence editing relies on numeric offsets; the queue has no visible filters or search. | Build text-selection editing with a keyboard alternative, searchable hierarchical code picker, review filters, and save-and-next. | A researcher can adjust a quote and code without calculating offsets; repeated text remains tied to the selected source location. |
| P1 | “Append review action” exposes storage terminology; reviewer name is repeatedly requested. | Use “Save decision” and “Save and next”; retain an editable local operator identity and show saved/history feedback. | Review history stays append-only; navigating away from an unsaved edit warns the user. |
| P1 | Provider setup exposes exact model IDs, both providers’ effort fields, token prices, API mode, and pricing-source fields together. | Offer verified, dated provider/model presets with advanced settings. Show only applicable controls and preserve the exact configuration in provenance. | A supported setup can be completed without researching API syntax; unsupported combinations are explained before spending. |
| P1 | Form-heavy configuration and imports require many separate actions without a compact readiness summary. | Guide users through Sources → Codebook → Coding settings → Preview and run; make missing prerequisites actionable. | Preflight explains selected sources, six-domain or other call fan-out, transfer scope, cost estimate, ceiling, and review requirement. |
| P2 | Overview includes a cached CFIR report link in a generic study and technical artifact tables. | Put demonstrations in a clearly separate entry point; move artifact browsing into advanced details. | Study outputs cannot be confused with unrelated demonstration results. |
| P2 | The inspected review case contains only two very short synthetic items. | Validate long transcripts, large codebooks, hundreds of assignments, empty/failed runs, long labels, and narrow windows before release. | Record measured interaction/rendering behavior and successful task completion on realistic synthetic fixtures. |

## Proposed workspace structure

Application: **Open study / Create study / Try demo**.

Within a study: **Overview · Sources · Codebook · Coding runs · Review · Compare · Export**.

Settings hold provider configuration and advanced method policies. Overview presents current readiness and the next meaningful action. Compare should appear only when implemented, with explicit prerequisites rather than fabricated metrics. Preserve direct links to a particular run and review item.

Review layout: a compact filterable assignment list, a central transcript pane with exact evidence and optional context, and a code/decision panel. On smaller windows these become ordered panels rather than compressed columns. Code guidance must remain visible while deciding. Technical offsets and hashes remain available in details.

## Implementation sequence

1. **Workflow clarity:** unify status language and export labels; correct setup context; create consistent run identity and next-action summaries. Verify against unreviewed, partially reviewed, failed, paused, and released fixtures.
2. **Real-study vertical slice:** source inventory and preview, CFIR workbook preview, one-transcript preflight, and a clearly bounded CFIR results view. Legacy CFIR outputs need a dedicated exact-evidence normalization adapter before using the generic reviewer; do not invent offsets or silently reinterpret historical rows.
3. **Review ergonomics:** selectable spans, codebook search/tree, filters, save-and-next, identity retention, decision history, keyboard operation, and unsaved-change handling.
4. **Setup simplification and comparisons:** dated provider presets, cost/error recovery, and the agreement/stability workspace using frozen runs. Explicitly separate code-label disagreement from segmentation disagreement and unreviewed from adjudicated results.
5. **Visual refinement and release rehearsal:** tighten typography/spacing, reduce repetitive technical copy, verify accessibility and responsive behavior, then record a synthetic demonstration and create the landing-page materials.

These are dependency-ordered increments, not month-long phases. Complete the first two before broad visual redesign. Use the real-transcript walkthrough to refine requirements, then use synthetic equivalents for public UI testing and recordings. Keep the October 28 demo freeze ahead of the November 11 tutorial.

## Tools and design workflow

Continue with the existing in-app browser for rendered inspection and interaction tests. Extract reusable page templates/components and design tokens from the current Python-rendered interface as changes justify it. A wholesale React migration is not a prerequisite; reconsider only if transcript selection and comparison interactions materially exceed the current structure.

- [Vercel Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md): useful review checklist for semantics, focus, forms, navigation state, and long-content behavior. Use a reviewed pinned revision when adding it to a repeatable project workflow.
- [Anthropic frontend-design skill](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): useful for a deliberate visual direction and iterative screenshot critique. Adapt its advice to a research workspace; it does not establish accessibility or scientific validity.
- [WCAG 2.2 quick reference](https://www.w3.org/WAI/WCAG22/quickref/): accessibility acceptance baseline. Check keyboard access, visible/unobscured focus, contrast, labels/errors, reflow, and target sizes rather than relying on appearance.

No new plugin was installed. Figma is optional if shared design files become useful. Existing Remotion tooling is appropriate after the workflow stabilizes; image generation is optional for promotional assets rather than evidence or product screenshots.

## Usability verification

Recruit 3–5 intended researchers for formative sessions, explicitly not a representative performance evaluation. Ask them to open/create a study, find an imported source, confirm a codebook, explain the data transfer and budget, start a small approved run, edit/reject evidence, find an unresolved item, and export the right package. Record task completion, assistance required, errors, time, and their interpretation of readiness labels. Resolve misleading states before optimizing speed. Separately test keyboard-only operation, narrow windows, zoom, and Windows/macOS startup.

## Remaining decisions

The first real-data walkthrough also identified a source-location requirement: DOCX nonbreaking spaces and quotation typography can defeat literal matching even when wording is preserved. The CFIR normalization adapter should retain raw model text, distinguish formatting differences from changed wording, map reviewed matches back to original extracted-text offsets, and route ambiguous or altered excerpts to human review. A normalized text match alone must not be labelled exact-source validation. Temporary read-only study review aids do not replace the persistent adjudication workflow.

The proposed direction is a restrained research workspace with evidence review as its central activity. Confirm any stronger visual preference during mockup review. Real-data API use remains subject to the selected study’s provider/governance and explicit budget approval; UI evaluation does not grant that approval.
