# 0007 — Exact-quotation anchoring for new generic studies

September 8, 2026. Implements the owner's request to address invalid model-generated evidence offsets.

New generic studies use the version 2 prompt, framework mapping, and method with `evidence_location: unique_exact_quote`. The model returns verbatim evidence and `auto` location markers. The app computes a location only for a unique literal match against the normalized extracted source. Unicode character offsets are zero-based with an exclusive end. Duplicate, overlapping duplicate, missing, or blank matches remain unresolved review items. This contract does not ask the model to count characters.

Raw responses and parsed cells remain unchanged. Each stage artifact records its evidence-location contract; review records retain raw markers and proposed offsets separately from derived EvidenceSpan values. Automatically located spans carry creation_method=automatic, and the interface and reviewed exports identify the anchoring method. Two in anchor_match_count means two or more matches. Existing artifacts default to their original model-offset contract; changing the active study method never retroactively repairs a run.

Version 2 also asks for the most specific supported hierarchical code and does not automatically duplicate ancestors. This is an explicit prompt policy, not a measured model advantage or a universal qualitative-method requirement. Complete human review remains necessary.

Two live calls, one per approved provider, produced four source-valid automatically anchored assignments on the synthetic fixture. This is smoke-test evidence only. More diverse transcripts, repeated quotations, long passages, and researcher review are required before research-validity claims. The older invalid-offset runs remain available for inspection.
