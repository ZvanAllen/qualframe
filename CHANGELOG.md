# Changelog

## Unreleased

- **Add codes the model missed.** Select a passage during review and press N to add a code. Additions count in results and exports, are marked as researcher additions, and are reported in the methods record.
- **Review time.** Each decision records how long the proposal was open; the methods record reports the median.
- **Typography-tolerant locating.** Quotations that differ from the transcript only in quotation marks, hyphen variants or spacing are located and highlighted for confirmation instead of left for manual search.
- **Text kept with each code.** Coding options offer just the quotation, a sentence either side, the whole answer (speaker turn), or the answer with the question before it. The kept text is shaded around the highlight in review, shown in Results and exported. Edits and additions use the run's setting.
- **Editable coding instructions.** Run coding has a *Coding instructions* panel: edit the instructions and save them as a named version, switch between versions, and see which runs used each. The standard instructions are never changed. Compare runs shows what differs between two runs (model, instructions, coding options), and the methods record names the instructions used. Recorded demo responses refuse to stand in for edited instructions.
- **Sample runs.** Start coding on a chosen sample of transcripts to check the output and the cost before a full run. Compare runs compares a sample run with a full run on the transcripts both coded.
- **QualBench.** A new page under More measures agreement among coding runs, and with an earlier coding of the same transcripts: which codes were applied (percent agreement, Cohen's kappa, Gwet's AC1, and precision, recall and F1 against an earlier coding), which passages were coded, and stability across repeat runs (Krippendorff's alpha), with cost and time per run. Reports are saved as tidy CSV tables with their definitions. An earlier CFIR coding in the published table format can be imported as a reference from the QualBench page (or with `scripts/qualbench.py import-reference`).
- **CFIR construct matching.** Construct names written with their outline numbers ("H. Innovation Deliverers: 4. Motivation", "II.B.1. Actual Implementation Outcomes: Adoption", "E.3 Opportunity", "F2. Innovation Recipients (Engaging)") now match the codebook. Unreviewed CFIR runs prepared before this change are re-checked from their saved answers when the study opens. CFIR review items keep the run's *Text kept with each code* setting, and the CFIR cost estimate allows for the long answers the reference prompts produce.
- **CFIR workbooks** with explanatory "Note:" rows between constructs now import.
- **Clearer errors.** A failed model request now says why (for example a missing key) instead of only that it failed.
- The placeholder name "Unnamed researcher" is no longer saved as your name.
- **Demo:** a third recorded run, gpt-oss-20b running locally through Ollama.

## 0.9.0 (10 October 2026)

First researcher-facing release: a local app with a demo study, model presets for hosted and local models, keyboard-driven review, results by code and transcript, run comparison and a methods record. Archived on Zenodo.
