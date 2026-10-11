# Changelog

## Unreleased

- **Add codes the model missed.** Select a passage during review and press N to add a code. Additions count in results and exports, are marked as researcher additions, and are reported in the methods record.
- **Review time.** Each decision records how long the proposal was open; the methods record reports the median.
- **Typography-tolerant locating.** Quotations that differ from the transcript only in quotation marks, hyphen variants or spacing are located and highlighted for confirmation instead of left for manual search.
- **Text kept with each code.** Coding options offer just the quotation, a sentence either side, the whole answer (speaker turn), or the answer with the question before it. The kept text is shaded around the highlight in review, shown in Results and exported. Edits and additions use the run's setting.
- **Editable coding instructions.** Run coding has a *Coding instructions* panel: edit the instructions and save them as a named version, switch between versions, and see which runs used each. The standard instructions are never changed. Compare runs shows what differs between two runs (model, instructions, coding options), and the methods record names the instructions used. Recorded demo responses refuse to stand in for edited instructions.
- **Sample runs.** Start coding on a chosen sample of transcripts to check the output and the cost before a full run. Compare runs compares a sample run with a full run on the transcripts both coded.
- **CFIR workbooks** with explanatory "Note:" rows between constructs now import.
- **Clearer errors.** A failed model request now says why (for example a missing key) instead of only that it failed.
- The placeholder name "Unnamed researcher" is no longer saved as your name.
- **Demo:** a third recorded run, gpt-oss-20b running locally through Ollama.

## 0.9.0 (10 October 2026)

First researcher-facing release: a local app with a demo study, model presets for hosted and local models, keyboard-driven review, results by code and transcript, run comparison and a methods record. Archived on Zenodo.
