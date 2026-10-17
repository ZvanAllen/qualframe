# Changelog

## 0.11.0 (17 October 2026)

- **Shared-positive passage agreement.** Passage tables retain pooled measurements and add a scope restricted to document × code pairs with located passages on both sides, with pair and passage counts.
- **Precise code provenance.** New runs and QualBench reports record the executing code's Git commit and whether its checkout has uncommitted changes. Methods records show both; older or non-Git records remain readable with unavailable provenance identified.
- **Unlabelled review notes.** CFIR workbook and table imports retain nonempty cells under blank headers using column-letter note keys. Coding and labelled notes are unchanged; existing references are not rewritten.
- **Paired reference comparisons.** `--second-reference` adds sensitivity, specificity, balanced accuracy and MCC for each coding set and deterministic baseline on units assessed in both references, with second-minus-first intervals from shared document or folder draws.

- **QualBench assessment masks.** Explicit-absence references leave unassessed document × code units out of every presence measure. Unit/domain and document exclusion files support sensitivity analyses with reason-level audit tables and conservative parent assessment.
- **Absence-sensitive comparisons.** Sensitivity, specificity, balanced accuracy, MCC, every-code-present/absent baselines, and per-code prevalence/confusion tables. Undefined values remain blank.
- **Document bootstrap intervals.** Optional seeded document or folder-then-document resampling, including paired coding-set differences on the same draws, with defined/undefined replicate counts.
- **Word-normalized quotation candidates.** Model proposals and reference imports try unique case/punctuation-normalized word matches after exact/typography matching, retain original offsets, and require researcher confirmation. QualBench counts these candidates separately.

## 0.10.0 (15 October 2026)

- A study can be classified as **Published or public documents** (articles, reports, policy documents with no participant data). It is treated as real data, like de-identified data.

- **Coding style choice.** General directed studies can find passages that fit (the existing default) or decide on every active code in each codebook part. The new style uses a separate versioned prompt, creates explicit absence records, and reports omitted codes as no decisions in run QA and QualBench profiles. Coding options save the style as a new method version and retain existing custom groups. The instructions panel shows the fixed decision prompt while preserving the study's editable Find passages instructions. Published CFIR reference prompts remain unchanged.

- **Repeated reference quotations.** Table and CFIR imports preserve alternative locations as one annotation. QualBench matches any candidate under the same one-to-one rule, omits ambiguous locations from character-overlap totals with explicit counts, and reports unique/repeated/unanchored reference passages. Existing saved references remain readable and require a new import to gain alternatives.

- **Optional Active column.** Excel codebook imports accept yes/no, true/false and 1/0, with blank or missing values active by default. Inactive codes can remain hierarchy parents without being offered to the model. Import previews and the example workbook include Active.

- **Active-code presence units.** QualBench excludes inactive codes from code-level presence and stability universes while retaining their parent hierarchy. Reports show active and parent universe sizes and warn about differing active flags; older missing flags remain active.

- **Unique transcript labels.** Sources sharing a filename use relative paths in QualBench presence, passage and unit-level rows, preventing pooled counts and distorted transcript means.

- **Codebook compatibility warnings.** QualBench names changed code definitions, labels, parents and other code content while allowing comparison by matching IDs. Display-only section changes are ignored.

- **Unknown usage stays unknown.** QualBench follows saved ledger locations and reports missing costs/tokens as null with a note. Profiles retain estimated-cost flags and recorded cache/reasoning token categories; historical reports retain whole-run cost labels.

- **Live command-line status.** Running workers publish a heartbeat at least every 30 seconds. Status distinguishes running/stopped and lists active requests as in flight. Confirmation and duplicate execution are blocked while active, and same-second starts cannot overwrite another run.

- **Reference provenance.** Reference import forms and the import command can record independent human coding explicitly, defaulting to false. Reports display the importer's declaration alongside its provenance statement.

- **Comparable resource totals.** QualBench reports request, token, cost and time totals for the common transcript cohort and first coding step, with per-transcript means. Whole-run totals remain separately labelled, including later synthesis steps.

- **Repeat configurations.** QualBench groups runs, including runs from other studies, by all saved provider settings and locked coding asset hashes. Spending limits, prices and study paths do not define a repeat. The report shows the settings used; incomplete historical records are left ungrouped.

- **Review-time median.** Even numbers of timed decisions now use the mean of the two middle values.

- **Add codes the model missed.** Select a passage during review and press N to add a code. Additions count in results and exports, are marked as researcher additions, and are reported in the methods record.
- **Review time.** Each decision records how long the proposal was open; the methods record reports the median.
- **Typography-tolerant locating.** Quotations that differ from the transcript only in quotation marks, hyphen variants or spacing are located and highlighted for confirmation instead of left for manual search.
- **Text kept with each code.** Coding options offer just the quotation, a sentence either side, the whole answer (speaker turn), or the answer with the question before it. The kept text is shaded around the highlight in review, shown in Results and exported. Edits and additions use the run's setting.
- **Editable coding instructions.** Run coding has a *Coding instructions* panel: edit the instructions and save them as a named version, switch between versions, and see which runs used each. The standard instructions are never changed. Compare runs shows what differs between two runs (model, instructions, coding options), and the methods record names the instructions used. Recorded demo responses refuse to stand in for edited instructions.
- **Sample runs.** Start coding on a chosen sample of transcripts to check the output and the cost before a full run. Compare runs compares a sample run with a full run on the transcripts both coded.
- **QualBench.** A new page under More measures agreement among coding runs, and with an earlier coding of the same transcripts: which codes were applied (percent agreement, Cohen's kappa, Gwet's AC1, and precision, recall and F1 against an earlier coding), which passages were coded, and stability across repeat runs (Krippendorff's alpha), with cost and time per run. Reports are saved as tidy CSV tables with their definitions. An earlier coding kept as a table (document, code, optional quotation; CSV or Excel) can be imported as a reference in any study, and an earlier CFIR coding in the published workbook format can be imported in a CFIR study, from the QualBench page (or with `scripts/qualbench.py import-reference`). Runs from another study with the same transcripts can be compared too (matched by file content; `--run STUDY-ID:RUN-ID` on the command line), for example the CFIR workbook coded with QualFrame's general instructions in a second study.
- **CFIR construct matching.** Construct names written with their outline numbers ("H. Innovation Deliverers: 4. Motivation", "II.B.1. Actual Implementation Outcomes: Adoption", "E.3 Opportunity", "F2. Innovation Recipients (Engaging)") now match the codebook. Unreviewed CFIR runs prepared before this change are re-checked from their saved answers when the study opens. CFIR review items keep the run's *Text kept with each code* setting, and the CFIR cost estimate allows for the long answers the reference prompts produce.
- **CFIR workbooks** with explanatory "Note:" rows between constructs now import.
- **Recovering from a failed paid request.** When a request fails (for example the account runs out of credit), the run's details page now asks whether it was charged: one click for "no", or the token counts from the provider's usage page for "yes". The run can then resume where it stopped; this used to need the command line. The error message is saved with the request.
- **Coding from the command line.** `qualframe code`, `resume`, `status` and `confirm-request` start, continue and monitor runs without the app, for scripts and for assistants running a study unattended. Spending steps can be approved in advance, on the record, up to an amount you name.
- **"Not sure" for a failed request.** After a power cut or lost connection, the failed request can be counted at the most it could have cost.
- **Spending checks in one step.** When a run pauses at a spending check (every $20 by default), its page now offers *Approve and continue*, which records the approval and resumes the run, or *Stop the run here*. Before, approving and resuming were two separate forms, and resuming without approving paused the run again.
- **Resuming never pays twice.** A resumed run reuses every answer it already received, including the finished parts of a transcript coded one domain or category at a time. Before, those parts were requested again.
- **Resuming after changing spending settings.** Raising the spending limit or saving the model again no longer stops a run from resuming, as long as everything that shapes the coding (model and its settings, instructions, codebook, options) is unchanged. Other changes still need a new run, and the page now says so.
- **Claude Haiku 5.5 preset** allows 64,000 output tokens. Haiku thinks before answering and the thinking counts toward the limit, so 32,000 was too few for a large CFIR domain. The output-limit error now says so and where to change the setting.
- **Clearer errors.** A failed model request now says why (for example a missing key) instead of only that it failed.
- The placeholder name "Unnamed researcher" is no longer saved as your name.
- **Demo:** a third recorded run, gpt-oss-20b running locally through Ollama.

## 0.9.0 (10 October 2026)

First researcher-facing release: a local app with a demo study, model presets for hosted and local models, keyboard-driven review, results by code and transcript, run comparison and a methods record. Archived on Zenodo.
