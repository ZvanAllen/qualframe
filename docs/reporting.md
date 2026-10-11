# Reporting QualFrame in your methods

Reviewers of AI-assisted qualitative work usually ask: which model, with what instructions, applied to what, how humans checked the output, and what was changed. QualFrame keeps all of this with each study, so you can answer precisely.

## What to report

Open **Results**, then **Methods record**. It fills in a draft methods paragraph from the run's records and lets you download the details as Markdown or JSON. The table below says where each detail comes from, if you need to check it.

| Item | Where it is recorded |
| --- | --- |
| QualFrame version, model, provider and settings | `artifacts/<run>/run_settings.json` (no API keys) |
| Dates | `run_settings.json` (start) and `run_manifest.json` (finish) |
| Coding instructions | The prompt file listed in `analysis_configuration_lock.json`, with its SHA-256 hash |
| Codebook and version | The codebook file listed in the same lock file, with its hash |
| How the codebook was sent | The method file listed in the lock file (`partitioning`) |
| Transcripts | `run_plan.json`, with each file's SHA-256 hash |
| Human review | `review_queue/<run>/`: every decision with reviewer, time and note; summarised in the reviewed export |
| Quotations located by hand | Review records whose location method is not `unique exact quote`, and their decisions |
| Codes reviewers added | `review_queue/<run>/evidence/additions.jsonl`; marked "Added by researcher" in exports |
| Time spent reviewing | `review_queue/<run>/evidence/timing.jsonl` (seconds per decision, while the window was visible) |
| Agreement between runs, if used | A comparison saved from Compare runs |

## Template paragraph

Adapt this to your study; replace the bracketed parts.

> Directed content analysis was supported by QualFrame [version] (van Allen, 2026), open-source software that applies a predefined codebook to interview transcripts using a large language model and presents each proposed code with its source passage for human review. Transcripts were de-identified before analysis. [Model, provider and version, e.g. Claude Sonnet 5.5 via the Anthropic API / a locally hosted gpt-oss-20b model] coded each transcript against the [N]-code codebook using QualFrame's version 3 directed-coding instructions, with [the whole codebook / one top-level category] per request. Each proposed quotation was located in the transcript automatically; proposals whose quotation could not be located exactly were resolved manually. [Reviewer(s)] reviewed every proposal, accepting [n], changing the code or passage of [n], and rejecting [n]. [If applicable: To assess consistency, the transcripts were also coded with [second model]; the two runs shared [x]% of codes per transcript.] The review records, prompts and configuration are available [on request / in the supplementary material].

## Citing the software

van Allen, Z. (2026). *QualFrame: AI-assisted directed content analysis you can check* (Version 0.9) [Computer software]. https://github.com/ZvanAllen/qualframe

GitHub's **Cite this repository** button gives the same citation in other formats. If a DOI is listed on the repository page, cite the DOI for the version you used.

## Being clear about what the software did

- Say that a human reviewed every proposal, and who.
- Report rejected and changed proposals, not only accepted ones, and how many codes reviewers added that the model missed.
- Avoid describing agreement between runs as accuracy or reliability against a human standard.
- If you used the optional summary drafts, say so, and that they were edited and checked against the cited passages.
- Note any transcripts excluded from results and why.
