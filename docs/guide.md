# User guide

How each part of QualFrame works, and the choices you can make. For a first walkthrough, start with [Getting started](getting-started.md).

## Studies

A study holds one set of transcripts, one active codebook, and any number of coding runs. Each study is a folder under `QualFrame/studies/` in your home directory. **All studies** lists them; the left-hand panel shows where the current study stands.

The data type you choose when creating a study (de-identified, sensitive, or test data) is shown at the top of every page as a reminder. Test-data studies can use the offline test models; other studies cannot, so real data is never coded with placeholder output by mistake.

## Sources

**Transcripts.** Word (.docx) and plain-text (.txt) files up to 25 MB. QualFrame copies each file into the study, records a SHA-256 hash of the original, and never changes it. Word files are converted to plain text paragraph by paragraph; that text is what the model sees and what review highlights. Expand a transcript on the Sources page to check the converted text.

Speaker labels such as `Interviewer:` and `Participant:` at the start of a line are shown in bold during review. The model is asked to code participant speech, not interviewer questions.

**Groups.** Give a site or group name when you add transcripts. Results show groups as column headings.

**Participant information.** A CSV file with one row per transcript and a `source_filename` column matching each file name exactly. Other columns (site, role, years in practice) can be used to group summaries.

## Codebook

QualFrame applies one codebook at a time. Codes can be flat or nested (a parent code with child codes). Each code needs an **ID**, a **name**, and a **definition**; **include** and **exclude** guidance and **examples** are optional but help the model.

**Importing from Excel.** Put one code per row. QualFrame previews the sheet, suggests which columns hold which fields, and checks the codebook before saving: duplicate IDs, missing definitions, unknown parent codes and circular hierarchies are reported. Formulas must be pasted as values. The original workbook and the column mapping are kept with the study.

**Changing the codebook.** Importing again creates a new version. Earlier runs keep the version they used, so their results still make sense.

**How the codebook reaches the model.** By default the whole codebook goes in each request. For long codebooks you can send one top-level category per request instead (**Run coding**, then **Coding options**). That means more requests, but each one asks the model to consider fewer codes.

## Run coding

**Choosing a model.** See [Models and data](models-and-data.md). The model cards show an estimated cost for your study based on its length and the provider's list prices, which are recorded in `config/model_presets.yaml` with the date they were checked.

**Spending limit.** Hosted runs need a limit for the study. Before each request, QualFrame estimates the most it could cost and pauses rather than go over the limit. Reported usage from each response is added to the study's cost record. Estimates are not bills; check your provider's dashboard.

**API keys.** Paste a key on the Run coding page and it is kept in memory only until you close QualFrame. To avoid re-entering it, put it in a `.env` file in the QualFrame application folder (see `.env.example`) as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; QualFrame then offers to use it. Keys are never written into study files or exports.

**What is sent.** For each transcript (and each codebook part, if split): the coding instructions, the analysis settings, the transcript text, and the codebook. Nothing else from your computer is sent.

**Coding options.**
- *Codes per passage*: one, or several.
- *How much of the codebook goes in each request*: all of it, or one top-level category at a time.
- *Context saved*: how many sentences before and after each coded passage are saved with it in exports. This doesn't change what is coded.
- *Overlapping passages*: whether two coded passages may overlap.

Each change saves a new method version. Runs record exactly which version they used.

**What happens during a run.** Requests are sent one at a time. Each response is saved as soon as it arrives, then checked: every quotation is searched for in the transcript, and every code is checked against the codebook. If QualFrame is closed or a request fails, open **Run details** and resume; completed requests are not sent again. Failed requests are never retried automatically.

## Review

Each proposal shows the code, its definition and guidance, the model's reason, and the highlighted passage in the transcript.

| Key | Action |
| --- | --- |
| A | Accept the proposal as it is |
| R | Reject it |
| L | Leave it for later |
| C | Change the code |
| U | Use the text you selected in the transcript as the passage |
| N | Add a code the model missed, for the text you selected |
| J / K | Next / previous proposal |

To change a passage, select the right text in the transcript, press **U**, then **Save change and continue**. You can change the code and the passage together. A note is optional and is saved with the decision.

**Codes the model missed.** Reviewing proposals only catches codes the model applied wrongly; it can't show what the model left out. When you notice a passage that should be coded, select it, press **N** (or open *Add a code the model missed*), choose the code and add it. Your additions appear at the end of the proposal list, count in Results and exports like accepted proposals, and are reported separately in the methods record. You can remove an addition later; the removal is recorded too.

**Proposals that need your help.** If the model's quotation can't be found in the transcript, or appears more than once, the proposal can't be accepted as it is. Select the passage yourself or reject it. If the quotation differs from the transcript only in punctuation or spacing (curly quotes, hyphen variants, extra spaces), QualFrame highlights the transcript's own text and says so; accepting it records the transcript's wording, never the model's.

**Time per decision.** QualFrame notes how long each proposal was open (only while the window is visible) and saves it alongside the decision. The methods record reports the median, which is useful when describing review effort.

**Nothing is overwritten.** Every decision is added to the study's review record with your name and the time. Changing your mind adds a new decision; the history is kept.

**Transcripts with no proposals.** If the model proposed nothing for a transcript, Results asks you to confirm that before counting the transcript as reviewed.

## Results

Results counts the passages you kept for each code in each transcript, grouped by site. Select a number to read those passages, or a total to read them across all transcripts. Counts are passages, not people, and a zero means nothing was kept, not that a topic was absent.

Results are saved as a snapshot that records exactly which decisions they include. If you change a decision later, Results tells you and offers to update.

**Export to Excel** writes the reviewed coding, with each passage, code, decision, reviewer and source details, to an Excel workbook and a JSON file in the study's `exports` folder.

**Draft summaries (optional).** From Results you can ask a model to draft a short summary for each code from your kept passages. Every sentence must cite the passages it relies on, and you review each sentence like a coding proposal. Summaries are a writing aid, not findings.

## Compare runs

Run the same study again with another model, or the same model twice, then open **Compare runs**:

- **Codes in common**: for each transcript, of the codes either run applied, the share both applied.
- **Same text, same code**: how much of the coded text overlaps, code by code.
- **Identical passages**: same code with exactly the same start and end.

Open a transcript to read the passages only one run coded. Comparisons use the models' original proposals, before your review, and neither run is treated as correct. **Repeat runs** (under More) runs the same configuration several times to see how stable a model is on your data.

## The CFIR reference workflow

Choosing *CFIR reference workflow* for a new study sets up the staged pipeline from the AMN study: one request per CFIR domain, then roll-up, context, network and cross-network steps. Its prompts are kept word for word in [`prompts/cfir/final`](../prompts/cfir/final). Import the CFIR construct workbook on the Codebook page; QualFrame does not include it. New CFIR studies stop after the first coding step so you can review before anything is synthesised.
