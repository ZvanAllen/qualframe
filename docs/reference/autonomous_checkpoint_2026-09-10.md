# Autonomous development checkpoint — September 10, 2026

## Latest follow-on

Reviewed-input synthesis now runs through the approved provider, supports a focused
statement reviewer, and exports immutable reviewed JSON with complete decision
history. Native output schemas were added after a malformed live response. The
fresh fictional browser upload completed coding and reviewed synthesis through
both OpenAI and Anthropic. Recorded cost: USD0.00057445 OpenAI and USD0.008351
Anthropic. Full suite: 169 passed, 1 skipped; both offline demos passed. Desktop and 390px summary
review checks passed, including navigation, visible edits and complete-review
progress. The research workspace retains six resolved proposals out of 203.

See [the API results and limits](api_synthesis_results_2026-09-10.md) and
[the usable synthesis workflow](reviewed_synthesis_preparation.md).
The earlier checkpoint below describes the preparation-only increment; its API,
test-count and pending-execution statements are superseded by this follow-on.

## Earlier delivered increment

- Selected-transcript snapshots: freeze the fully reviewed portion of a study,
  record exclusions, preserve older versions, and keep unrelated review changes
  from invalidating the chosen subset. The source-linked matrix follows that scope.
- Compare runs: descriptive code overlap, exact coded-passage overlap and coded-text
  coverage overlap; per-code details, differing quotations, exclusions, separate
  absence proposals, pooled denominators and immutable JSON reports. The browser
  and `qualframe-eval compare` share the implementation. Human edits are excluded.
- Synthesis preparation: a current reviewed snapshot, per-transcript or combined
  scope, versioned instructions and an immutable local input plan. A response
  validator checks code/scope citation membership. No synthesis requests or
  generated findings are produced by this increment.
- Updated setup instructions, capability register, architecture, workflows and
  methodological boundaries. Original AMN prompts remain unchanged.

## Verification

- Full test suite: **162 passed, 1 skipped** on Windows/Python 3.11. The skip is
  the optional private-workbook check. New tests cover boundary shifts, empty sets,
  excluded proposals, mismatched inputs, changed artifacts, isolation from human
  edits, subset freshness, plan scope and invalid synthesis citations.
- Both offline demonstrations passed: generic two-transcript/four-record review
  and cached five-stage CFIR with nine Excel exports and the expected seeded conflict.
- Browser checks: comparison selection/save/download link; selected-source freeze;
  remembered subset choices; synthesis scope/preparation/instruction display;
  desktop and 390px layouts without document-level horizontal overflow. Wide
  evidence tables scroll within their own containers.
- Automated public-file screening passed for **204 allowlisted files**. A source
  archive was unpacked into a new folder; both demos ran successfully from that
  copy using this machine's installed dependencies. Python isolation mode first
  exposed a dependency available only in the user environment; this was not a
  clean-environment installation test. Clean Windows/macOS installation remains pending.
- The research workspace was relaunched successfully. Existing research decisions
  were preserved. No new external model calls, publication or remote pushes occurred.

The local review archive and its hash inventory are in `artifacts/release`.
Generated studies, raw research inputs, private workbooks, credentials and Git
history are excluded. This is a review candidate, not an approved public release.

## Review path

Use the synthetic browser-workflow study to inspect Compare runs and Analyze
evidence without changing research decisions. Its second mock run is deterministic;
100% overlap verifies the comparison machinery, not LLM performance. The real CFIR
study continues at human review and cannot prepare synthesis until its selected
transcript has completed review.

See [comparison definitions](raw_run_comparison_protocol.md) and
[synthesis preparation](reviewed_synthesis_preparation.md).

## Next steps in dependency order

1. Complete the fresh real-transcript browser/API trial under the applicable
   provider/data/spending approval. Add a deliberate no-evidence checkpoint for
   completed transcripts with zero proposals.
2. Add metadata-defined groups and failed-job recovery; pilot the now-implemented
   costed execution, source-linked summary review and stale-result tracking.
3. Build sequential repeat orchestration and freeze the publication evaluation
   design: units, repeats, sample, failures/exclusions, clustering and uncertainty.
   Descriptive pairwise overlap does not establish accuracy or population reliability.
4. Finish CFIR library attribution/redistribution checks, clean Windows/macOS setup
   and pilot usability trials, then landing-page evidence and real-interface video.
