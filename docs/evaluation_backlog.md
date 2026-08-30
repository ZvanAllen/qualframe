# Implementation backlog for evaluation layer

## A. Data normalization
- [ ] implement workbook schema reader for transcript / network / cross-network files
- [ ] implement canonical CFIR construct normalization
- [ ] add placeholder row detection with logging
- [ ] add stable row ID assignment
- [ ] add quote text normalization for duplicate detection
- [ ] add source-span mapping support

## B. Metrics engine
- [ ] transcript-level structural metrics
- [ ] transcript-level agreement metrics
- [ ] transcript-level redundancy metrics
- [ ] reviewer burden metrics
- [ ] network-level valence metrics
- [ ] cross-network network-set metrics
- [ ] cross-network instability metrics

## C. AI judging
- [ ] blinded candidate pack builder
- [ ] evaluator prompt runner
- [ ] JSON schema validation
- [ ] evaluator result parser
- [ ] seeded-error validation workflow

## D. Human adjudication support
- [ ] disagreement case sampler
- [ ] adjudication CSV template
- [ ] adjudication summary metrics
- [ ] join adjudication outcomes back to model outputs

## E. Reporting
- [ ] manuscript table builders
- [ ] metrics reference CSVs
- [ ] disagreement heatmaps
- [ ] cross-network valence instability heatmap
- [ ] markdown summary report

## F. CLI/API surface
- [ ] `qualframe-eval normalize`
- [ ] `qualframe-eval metrics`
- [ ] `qualframe-eval judge`
- [ ] `qualframe-eval seeded-errors`
- [ ] `qualframe-eval report`
- [ ] `qualframe-eval run`

## G. Tests
- [ ] construct normalization tests
- [ ] duplicate quote detection tests
- [ ] Jaccard/kappa tests
- [ ] valence comparison tests
- [ ] schema validation tests
- [ ] seeded-error harness tests
