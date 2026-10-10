# API smoke-test checkpoint — September 8, 2026

Owner approved the prepared four-call synthetic test with a USD 1 total ceiling (USD 0.50 per provider). No model substitution or automatic retry was authorized or performed.

## Observed outcomes

- OpenAI: no API request submitted. No usable OpenAI key was found in the current process or the two project .env locations checked. Prepared model remains gpt-5.4-nano-2026-03-17.
- Anthropic: one submission to claude-haiku-4-5-20251001 was rejected with HTTP 401 / AuthenticationError. No model output or usage totals were returned. No second transcript request or retry was sent.
- No successful live coding, evidence review, or export was established. Zero settled cost is recorded; actual provider billing was not verified. The failed request remains unresolved in the request ledger rather than being automatically treated as free.

The initial single-source attempt made no request because the legacy participant-prefix filter did not recognize SYN-01. It produced an empty manifest. The runner now accepts an exact source filename stem in addition to the legacy participant-prefix match, and rejects unmatched filters before provider construction. The offline regression test checks that exactly one hyphenated source executes and that no unmatched run folder is created.

## Resume prerequisites

Supply a valid Anthropic key and an OpenAI key locally, without putting them in chat, source control, or study exports. Credentials can be entered in the local app's session-only provider form. Review/reconcile the rejected Anthropic request against provider evidence before retrying; do not remove its reservation or assume usage from the local estimate. Existing user approval for this same synthetic test and the USD 1 total ceiling persists; replacement credentials do not require a new budget approval.

Request records and owner approval are in the Anthropic study's artifacts/api-smoke-pending-approval folder. The failed test contains only synthetic study material. No raw research transcripts were transmitted. No publication or push was performed.

Offline verification after the filter fix: 131 tests passed, one skipped; both offline demos passed.


## Corrected-key test results — September 8

Both providers now authenticate and one real coding call per provider completed. Combined recorded token cost: USD 0.00268165. Parsing/raw Excel exports succeeded, but all six coding rows had invalid model-proposed character offsets. The missing validation warning was fixed and regression-tested; reviewed exports remain blocked. Two remaining planned calls were not sent. This supersedes the earlier credential blocker, but does not establish valid end-to-end evidence coding. See [current results](api_smoke_results_2026-09-08.md).
