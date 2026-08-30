# 0003: CFIR domain partitioning

- Status: accepted
- Date: 2026-08-02

## Decision

CFIR defaults to one coding call per top-level domain. The AMN workflow found that this was necessary for sufficient quality with GPT-5.1 Pro.

Codebook partitioning remains configurable. Supported target strategies are full codebook, one call per top-level category, and researcher-defined code groups.

## Consequences

The CFIR default is preserved as an empirical reference-method decision rather than hard-coded as a universal requirement. Partition strategy and groups belong in the locked configuration and run manifest.
