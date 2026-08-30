# Privacy and governance

## Public snapshot

This repository contains source code, configuration, prompts authorized for publication, and explicitly fictional demonstration fixtures. It excludes raw research inputs, private reference workbooks, derived research outputs, credentials, notification recipients, and internal run reports.

Do not upload real transcripts or sensitive exports in issues, pull requests, screenshots, or examples. Source hashes and pseudonyms do not, by themselves, make a dataset anonymous.

## Local-first is not local inference

The browser application runs on the local loopback address. The offline demonstrations use only mock/cached providers. Configuring an external provider for a CLI run can send the selected text outside the machine.

Before real research use, the researcher must confirm consent, institutional requirements, provider suitability, retention terms, and the authorized input/output destinations. A data-classification label is not an access-control or consent-enforcement system.

## Implemented safeguards and limits

- Non-overwriting study imports, source hashes, and versioned assets.
- Append-only local review actions; no authenticated reviewer identity.
- Browser execution restricted to managed mock/cached jobs.
- Optional stage/release gates; projects must explicitly enable them.
- Cost ceilings and approval pauses when the cost policy and exact model pricing are configured.
- Credentials read from local environment settings, not committed examples.
- Generated study, artifact, log, review, export, and raw-data folders ignored by Git.

These controls do not replace deployment security or project governance. The local HTTP server has no multi-user authentication and must not be exposed to a network. This prototype is not a production clinical system.

## Future work

Additional provider-policy enforcement, deployment hardening, local inference, and institutional endpoints require implementation and validation. Do not infer those capabilities from target specifications.
