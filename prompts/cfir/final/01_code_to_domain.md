You are an expert qualitative implementation science researcher using the Consolidated Framework for Implementation Research (CFIR).

TASK
Code the transcript for ONE CFIR domain only: {CFIR_DOMAIN}.
For this domain, include EVERY construct and subconstruct (if defined) exactly as named and in the same order as in the CFIR Construct Code Book. Use verbatim, full-sentence quotes only from the transcript.

INPUTS
The full transcript (with page numbers if available).
The CFIR Construct Code Book.
(Optional) A domain-filtered table from a prior pass for {CFIR_DOMAIN}. If provided, use it as the primary pool of candidate segments, but consult the full transcript for context or missed evidence.

BEGIN WITH A SHORT CHECKLIST (3–7 bullets)
Before producing the table, provide a brief checklist summarizing your approach, including:
Full read-through of the transcript.
Identification of candidate segments for {CFIR_DOMAIN}.
Matching segments to constructs using codebook definitions.
Handling ambiguity or overlapping constructs.
Verification that all constructs are covered.
Keep this checklist as plain text.

OUTPUT (REQUIRED)
Produce a table for the domain {CFIR_DOMAIN} with the following exact column order:
CFIR Domain | CFIR Construct | Quote | Page Number | Explanation

Table rules:
Use one row per quote.
You may include multiple rows per construct if quotes are clearly distinct and non-overlapping.
Quotes must be verbatim and full sentences.
If Page Number is unknown, leave the cell blank.
If no evidence fits a construct, use: Quote = "No relevant quote found"; Page Number = blank; Explanation = brief rationale referencing the construct definition.

CODING INSTRUCTIONS
Work strictly within {CFIR_DOMAIN}.
Use the CFIR Construct Code Book as the sole source of truth for construct names, order, and definitions.
Do not paraphrase, summarize, or introduce external content.
In Explanation, explicitly tie the quote to the construct definition and indicate whether the evidence is facilitating, hindering, or neutral, with brief justification.
If a quote could fit multiple constructs within {CFIR_DOMAIN}, select the best fit and note plausible alternatives in the Explanation.
If a segment previously tagged to {CFIR_DOMAIN} appears to belong to another domain, do not recode it here; note the misfit briefly in the Explanation and proceed.

Return the table using the markdown format described in your system instructions.
