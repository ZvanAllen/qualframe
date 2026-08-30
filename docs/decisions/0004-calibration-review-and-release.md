# 0004: Calibration, review, and release

- Status: accepted
- Date: 2026-08-02

## Decision

Complete human review is required during calibration in the first release. After calibration, the researcher may select complete review, risk-based review, random quality-control sampling, or a combination.

The first release has no role-based restrictions on locking configurations, approving continued spend, adjudicating items, or releasing exports. All actions remain timestamped and append-only.

## Consequences

Role and permission infrastructure is deferred without weakening provenance. Model-reported confidence is not treated as calibrated certainty and cannot be the sole review-routing signal.
