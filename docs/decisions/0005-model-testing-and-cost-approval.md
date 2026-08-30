# 0005: Model testing and cost approval

- Status: accepted
- Date: 2026-08-02

## Decision

Functional system tests use the cheapest appropriate generally available API model. Method evaluation uses a sequential benchmark of relevant OpenAI and Anthropic models and supported effort settings on synthetic challenges and then an approved human-coded calibration sample.

Provider-backed analysis records usage and cost. Before a request expected to cross each cumulative USD 20 threshold, the run pauses, attempts email notification, and requires explicit local approval. Every live project also declares an absolute spending ceiling.

Notification addresses and credentials are local secrets and are never committed.

## Consequences

Ordinary tests and public demonstrations use mock or cached providers. A successful cheap-model smoke test demonstrates system function, not qualitative-analysis validity.
