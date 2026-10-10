# Directed coding with exact-quotation anchoring — version 2

Apply only the supplied study codebook to the transcript. Identify exact supporting passages. Copy each quotation verbatim from the transcript; do not paraphrase, change punctuation, join separated passages, or include context that is not part of the evidence. Do not invent findings, participants, or codes.

Return only a markdown table with these columns:

| Meaning Unit ID | Evidence Start | Evidence End | Exact Evidence | Code ID | Rationale |
|---|---|---|---|---|---|

Write the literal value `auto` in both Evidence Start and Evidence End. Do not count characters, sentences, lines, or words. The application will search the immutable extracted transcript for the Exact Evidence text and calculate offsets only if that quotation occurs exactly once. Missing or repeated quotations require researcher review; they are never assigned to the first occurrence silently. Do not lengthen a coded passage solely to make its location unique.

The resulting application offsets use zero-based Unicode character positions in the complete extracted transcript, with an inclusive start and exclusive end. They are calculated by the application, not model-proposed locations. Extra before/after context is stored separately from the coded quotation.

Use one row per evidence/code assignment. Reuse the meaning-unit ID when applying multiple permitted codes to the same passage. Apply the most specific supported code in a hierarchy; do not add its ancestors automatically. A parent code may be used when its definition is supported but no child is sufficiently supported. Follow the configured single-label or multi-label policy. Code only participant material relevant to the codebook, not interviewer instructions or fixture labels.

For a passage containing a literal pipe character, encode that character as `&#124;` within the table cell. Encode a literal ampersand as `&amp;` first, so quotation text round-trips without ambiguity. Do not emit HTML tags or convert other punctuation. This format remains experimental and requires human review; successful software execution is not research validation.
