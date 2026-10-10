# Importing a historical assisted reference

The offline Python adapter imports frozen JSON quotation inventories as `historical_human_reviewed_ai_assisted` evidence. It creates a separate comparison object; it does not create accept events, change research files, alter reviewed snapshots, or call a provider. This increment is covered by synthetic regression tests. It does not establish the semantic validity of an archive or imply that a real research comparison has been completed.

Use the [archival comparator protocol](archival_comparator_protocol.md) to define the study and claim boundaries first. The adapter supports one selected evidence layer and an explicit source cohort per comparison. A source-attributed group quotation and a cross-group quotation are separate layers even when their wording is identical. Do not pool their repeated copies as independent evidence.

## Frozen import contract

`qualframe.archival_reference.load_archival_reference(import_path, *, source_root, reference_root, layer, source_ids=None)` returns a `qualframe_archival_reference_v1` dictionary. It performs no writes. All inventoried source files and reference files must be available and pass their hashes, including sources outside a requested subset. Use a new manifest for deliberate changes.

The input is UTF-8 JSON with this structure. Identifiers, paths and quotations below are synthetic. Replace hash placeholders with computed hashes; they are not accepted literal values.

```json
{
  "kind": "qualframe_archival_reference_import_v1",
  "reference_id": "historical-synthetic-v1",
  "project_id": "synthetic-study",
  "origin": "historical_human_reviewed_ai_assisted",
  "review_provenance": {
    "statement": "Final assisted outputs were reviewed; item-level logs were not retained.",
    "basis": "researcher_attestation",
    "item_level_history_available": false,
    "independent_human_coding": false
  },
  "codebook": {
    "id": "synthetic-cfir",
    "codes": [{
      "id": "parent-a", "label": "A. Practice", "raw_label": "A. Practice",
      "parent_label": "", "definition": "Synthetic definition.", "domain": "INNOVATION DOMAIN"
    }]
  },
  "codebook_sha256": "HASH_OF_CANONICAL_CODEBOOK_JSON",
  "source_mapping": {
    "transcripts/example.txt": {
      "source_id": "benchmark-source-CANONICAL_ID",
      "original_path": "transcripts/example.txt",
      "sha256": "SOURCE_FILE_HASH",
      "extracted_text_sha256": "EXTRACTED_SOURCE_TEXT_HASH"
    }
  },
  "reference_files": {
    "evidence": {"path": "evidence.json", "sha256": "REFERENCE_FILE_HASH"}
  },
  "parent_projection": {"parent-a": "parent-a"},
  "entries": [{
    "record_id": "historical-quote-1", "layer": "group_evidence",
    "source": "benchmark-source-CANONICAL_ID", "code_id": "parent-a", "domain": "Innovation",
    "original_code_label": "A. Practice",
    "reference_file": "evidence", "json_pointer": "/quotes/0",
    "body_start": 1, "body_end": 11,
    "anchor": {"start": 0, "end": 10, "method": "exact"},
    "issues": [], "audit": {"attribution_basis": "explicit source identifier"}
  }],
  "coverage": {
    "extraction_complete": true,
    "statement": "Complete inventory of this selected JSON quotation array; not exhaustive source coding."
  }
}
```

For this example, `evidence.json` might contain `{"quotes": ["\"Alpha beta\" - synthetic speaker"]}`. `body_start` and `body_end` select `Alpha beta` within that original JSON string. They are Python character offsets with an exclusive end. The separate `anchor` offsets address the extracted transcript. If the optional anchor is omitted, the adapter derives candidates; if supplied, it must agree with the independently derived unique match and method. Original quotation strings, body bounds, supplied audit data and issues are retained.

Use `benchmark_inputs.build_source_mapping(source_root, source_paths)` for canonical source IDs and source hashes, `reviewed_analysis.snapshot_identity(codebook)` for canonical JSON hashes, and `io.files.sha256_for_file` for file hashes. The mapping key locates a source under `source_root`. `original_path` retains its canonical identity when an identical source was copied into a managed study. Source and reference paths must stay inside their declared roots after resolution. References currently address JSON string cells; extracting another file format requires a separately frozen extraction and provenance record.

Keep the complete original codebook, including duplicate catalog entries. `build_parent_projection(codebook)` maps a child to a unique exact `raw_label` parent in the same domain. Freeze and review that mapping in the manifest. Missing or ambiguous mappings remain excluded; the importer does not choose a similar label. Duplicate code IDs cannot support included spans. Literal CFIR domain names, case differences and the `Domain` suffix are accepted aliases; substantive domain synonyms are not inferred.

An extraction script is responsible for assigning the original source, code and domain from verifiable identifiers. Put unresolved or conflicting attribution, extraction defects and other blocking observations in each entry's `issues`. The importer preserves these issues and cannot promote that record merely because some text happens to match. Optional `audit` fields are provenance, not instructions or silently inferred adjudications. Unknown labels and unresolved sources remain in the exclusion inventory. An unknown source cannot be allocated to a particular source subset and therefore remains an explicitly unresolved exclusion when selecting that layer.

## Source linking and scope

The versioned anchor policy is `archival_exact_typographic_whitespace_v1`:

1. Find all case-sensitive literal matches; a unique match is eligible.
2. If no literal match exists, collapse whitespace, normalize curly quotation marks/apostrophes, and map en/em dashes to hyphens. Case is preserved. Retain the original character-offset mapping and verify the reverse source slice.
3. Exclude ambiguous and absent matches. A supplied candidate does not resolve ambiguity. Case folding, punctuation deletion, word-sequence matching and semantic similarity are outside this policy.

Normalization is cached per source during an import. The original quotation and transcript are unchanged. Derived offsets are modern source bindings, not recovered historical coded boundaries.

The common scope is Innovation, Outer Setting, Inner Setting, Individuals and Implementation Process. Outcomes Addendum entries, other selected layers and known sources outside the selected cohort are retained in `out_of_scope`, with reasons. In-scope unresolved entries remain in `excluded`. The eligibility fraction is `included / (included + excluded)`. Every original entry remains accounted for; scope exclusions and absence declarations are separate counts. The archive does not create negative decisions from missing rows.

Imported records retain multiplicity. Inventory metadata also reports unique `(source, projected parent, start, end)` spans and duplicate entries. Only the matching sets collapse duplicates, within the selected layer. Match details retain every contributing record ID.

## Comparing new outputs

```python
from qualframe.archival_comparison import compare_archival_reference

report = compare_archival_reference(
    new_payload, archival_payload,
    source_texts=verified_texts_by_canonical_source_id,
    minimum_shorter_span_overlap=0.50,
    include_boundary_sensitivity=True,
)
```

`new_payload` uses the existing raw benchmark input shape, full original codebook and canonical source cohort. Both inputs must belong to the same study. Source text hashes, supplied extraction mappings, included offsets and exact source slices are verified before scoring. The archival content hash must remain intact. The returned `qualframe_archival_comparison_v1` report freezes both projected inputs, original codebook/projection provenance, input hashes, exclusions and a content-derived report ID.

The new input must declare the same `benchmark_provenance.quote_anchoring_policy`. Use `archival_quote_alignment.align_model_quotes_for_archive(payload, source_texts)` to create a separate symmetric input from a compatible frozen benchmark payload. The helper revalidates existing included quotations and can recover excluded records only when their source/code identities are unambiguous and their existing blocking issues are entirely within its known quote-only issue set. It retains the original input, exclusions and transformation audit. Code, attribution and semantic issues remain excluded.

Relabeling an existing payload is not a conversion. The comparator itself does not reconstruct eligibility. Different or unspecified policies raise an error by default. An explicit `allow_asymmetric_anchoring=True` creates a report marked `asymmetric_anchoring_sensitivity_only`, with a distinct identity and both policy labels; it cannot support a common-policy primary claim. Projected comparison payloads have their own kind and content hashes, with original payload kinds, hashes and codebooks retained in provenance.

The exploratory primary matching edge requires the same source and projected parent code and `intersection / shorter span length >= 0.50`. This threshold is a prespecified convention, not a validated CFIR threshold. The report also provides 0.25 and 0.75 sensitivities. Deterministic maximum-cardinality bipartite matching prevents one quotation from matching several quotations, including when a greedy assignment would lose a valid pair.

For unique new items P, eligible archival items H and matched pairs M, the report gives `M/P` as **new-output matched fraction**, `M/H` as **archival annotation recovery**, and `2M/(P+H)` as retrieval Dice. A zero denominator is null; both-empty Dice is null and one-empty Dice is zero. Per-source and per-parent support and matched counts accompany the aggregate. The equal-weight source summary is descriptive and is not an uncertainty estimate.

Expanded historical context can contain a new quotation despite low IoU, and the matching text may concern surrounding context rather than the original coded focus. Longer historical passages can increase retrieval. Neither matched nor unmatched items establish construct correctness, exhaustiveness or hallucination. Optional exact/IoU results are explicitly boundary-overlap sensitivities, not original coded-boundary accuracy. Independent human accuracy, inter-human agreement, causal review benefit and researcher time savings remain outside this adapter's claims.

Real report payloads include source-linked quotations. Keep those outputs private under study governance. This module provides Python helpers; it does not by itself expose a browser upload workflow, freeze a research protocol or publish a report.
