# 0009 — Researcher-first version 1

Accepted October 10, 2026, at the hand-off of development from the September prototype sessions.

The owner's direction: build something researchers will use, for anyone doing directed content analysis, and move the project forward. The September work produced a careful engine (versioned configuration, exact-quotation anchoring, append-only review, cost control) but the interface exposed that engine's vocabulary, and most effort had gone into evaluation tooling and cautious documentation. Version 1 reverses the emphasis without weakening the engine.

## Decisions

**The interface follows the researcher's task, not the engine's stages.** Pages are Home, Overview, Transcripts, Codebook, Coding, Review, Results and Compare. Engine terms (freeze, lock, fingerprint, partition, stage) appear only in optional details and downloaded records. Every page reads state from the study folder; nothing in the interface invents counts.

**One install, one studies folder.** `qualframe start` opens the app with no study needed. Studies, settings and editable templates live in a workspace folder (default `~/QualFrame`, or `QUALFRAME_HOME`), separate from the code. Templates are copied into it once and never overwritten, so researcher edits survive upgrades. This also lets the engine's existing repository-relative paths work unchanged.

**A demo that works offline.** The demo study uses six fictional transcripts and replays recorded coding responses. Recordings are labelled by kind: illustrative (hand-written to exercise the interface) or recorded from a named model. The interface says which. A real-model recording replaces the illustrative one before the public release.

**Current models, hosted or local.** Presets cover current OpenAI and Anthropic models with prices and the date they were checked. Any OpenAI-compatible endpoint (Ollama, LM Studio, a university or Azure deployment) can be used; plain HTTP is allowed only for the researcher's own computer. Offline test providers are refused on studies not marked synthetic, so nobody reviews mock output as if it were real.

**Version 3 coding instructions return JSON.** The model returns a list of codings (passage, exact quotation, code ID, rationale). OpenAI and Anthropic receive a strict schema with the codebook's code IDs as an enum; other endpoints are asked for the same JSON in the prompt. Output is converted into the existing review records, so anchoring and review are unchanged. The CFIR prompts and the version 2 table format remain available and unmodified.

**Identity is asked once.** The researcher's name is stored in workspace settings and attached to every decision; a note is optional. Review records keep the reviewer, time and note as before.

**Reporting is generated from records.** Each run writes `run_settings.json` (software version, provider settings without keys, codebook and method IDs). The Methods record page drafts a methods paragraph and offers the full record as Markdown or JSON.

**Evaluation tooling stays, in the background.** Run comparison is a plain page (codes in common, same text, identical passages, per-transcript differences). The benchmark and archival-comparator tools remain available but are not part of the main path. Methodological evaluation is research to report, not a gate on everyday use.

## What does not change

Sources and prior outputs are never overwritten. A proposal becomes evidence only if its quotation is located exactly once or a person locates it. Every hosted request is estimated against the study's spending limit before it is sent, with no automatic retries. Released prompts are never edited. Real research data never enters the repository.

## Superseded guidance

`docs/reference/workplan_2026-09-07.md` and `docs/reference/capability_status.md` described the September plan and status. They are kept for the record; the current guides (`docs/guide.md`, `docs/models-and-data.md`, `docs/development.md`) and this decision take precedence.
