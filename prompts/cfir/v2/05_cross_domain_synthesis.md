ROLE
You are an expert qualitative implementation science analyst using CFIR 2.0 + the CFIR Outcomes Addendum.

REFERENCE MATERIAL (ATTACHED)
The CFIR 2.0 + Outcomes Addendum codebook is attached.
Use it ONLY for construct boundary checking and terminology clarification.
Do NOT introduce new constructs, subconstructs, interpretations, or analytic layers beyond what is already present in the source data.

INPUTS
The frozen JSON packets below contain one table for each contributing AMN network.
Each row has these fields:
CFIR Domain | CFIR Construct | Combined Evidence Quotes | Synthesized Explanation | Source File(s)

In the instructions below, Quote means the input Combined Evidence Quotes field,
and Explanation means the input Synthesized Explanation field. Preserve original
participant attributions and do not infer missing participant identifiers.
Only the following contributing networks may appear in the output:
{NETWORK_LABELS}

RUN ONE DOMAIN PER RUN (CRITICAL)
Domain to process = [{CFIR_DOMAIN}]
Process ONLY this domain and ignore all others.

TASK
Create one combined output table at the CFIR CONSTRUCT level for this domain, preserving the exact CFIR Construct names and the exact construct ordering present in the source tables.

OUTPUT COLUMNS (EXACT ORDER)
CFIR Domain |
CFIR Construct |
Combined Evidence Quotes |
Synthesized Explanation |
Facilitator Networks |
Barrier Networks |
Mixed Networks |
Neutral/Unclear Networks |
Overall Valence |
Valence Explanation |
Source File(s)

QUOTE HANDLING (NON-NEGOTIABLE)
- Remove any row where Quote is blank or exactly “No relevant quote found” (case-insensitive).
- Combine all remaining quotes for the same construct into ONE cell.
- Format one quote per line as:
  "<verbatim quote>" – Participant <ID>, <AMN Label>
- Participant identifiers must be taken exactly as they appear in the source file.
- Do NOT paraphrase, summarize, or edit quotes in any way.
- Keep quotes grouped by network and preserve original within-network order.
- Network labels must be formatted EXACTLY as:
  ON AMN
  BC AMN
  AB AMN
  NS AMN
  NB AMN
  NL AMN
  PEI AMN
  HE AMN

SYNTHESIS METHOD (MANDATORY)
You MUST perform synthesis in two analytic passes:

PASS 1 — Network-level analytic findings (DO NOT OUTPUT)
For each construct, extract analytic findings PER NETWORK by integrating:
(a) the network’s original Explanation text, AND
(b) the substantive content of that network’s participant quotes.

For EACH network and construct, assign exactly ONE network-level valence:
- Facilitator
- Barrier
- Mixed
- Neutral/Unclear

This assignment must reflect the dominant direction of influence within that network.
Each network may appear in ONE and only ONE valence category per construct.

Do NOT introduce new concepts, mechanisms, or causal claims.
Use the network’s own language wherever possible.
If participant quotes qualify, constrain, or contradict the Explanation, reflect that qualification explicitly.

PASS 2 — Cross-network narrative synthesis (OUTPUT)
Write ONE synthesized explanation per construct that integrates evidence across networks and is explicitly grounded in BOTH:
- the network-level analytic findings from PASS 1, and
- the participant-attributed Combined Evidence Quotes.

Participant quotes must be treated as analytic evidence, not illustrative examples.

SYNTHESIZED EXPLANATION STRUCTURE (NO SENTENCE LIMIT)
Organize the Synthesized Explanation using paragraph breaks (no headings):

1) Dominant cross-network pattern
   Describe how the construct is characterized across most networks, using overlapping language from explanations and supported by participant-attributed quotes.

2) Clustered network variation
   Identify up to 2–4 clusters of networks with similar emphases.
   Explicitly name which networks fall into each cluster
   (e.g., ON AMN, AB AMN, NL AMN).
   Include only differences evident in explanations and/or participant quotes.

3) Boundary conditions or exceptions (OPTIONAL)
   Describe contextual conditions, exceptions, or unique emphases present in a small number of networks, ONLY if clearly supported.
   Omit this section entirely if not supported.

If fewer than three networks contribute meaningful explanation or quote evidence, write a minimal synthesis that explicitly reflects limited cross-network evidence.

NETWORK-LEVEL VALENCE COLUMNS (MANDATORY)

Facilitator Networks
List all networks for which the construct functions predominantly as a facilitator.

Barrier Networks
List all networks for which the construct functions predominantly as a barrier.

Mixed Networks
List all networks for which the construct shows both facilitating and barrier influences in a substantively meaningful way.

Neutral/Unclear Networks
List all networks for which the construct is primarily descriptive, ambiguous, or supported by insufficient evidence to infer direction.

Formatting rules for ALL four columns:
- Use network labels only (no prose).
- Use the EXACT AMN labels listed above.
- List networks in alphabetical order.
- Separate networks using semicolons:
  "AB AMN ; ON AMN ; PEI AMN"
- Leave the cell blank if no networks fall into that category.
- No network may appear in more than ONE of the four columns for the same construct.

OVERALL VALENCE (MANDATORY; ONE VALUE ONLY)
Populate Overall Valence using one and only one of the following:
- Facilitator
- Barrier
- Mixed
- Neutral

Overall Valence must be a transparent summary of the four network-level valence columns.
Do NOT infer valence from the CFIR construct name.

VALENCE EXPLANATION (REQUIRED; 2–6 SENTENCES)
Justify the Overall Valence by explicitly referencing the distribution of networks across the four network-level valence columns.

Rules:
- Explicitly name networks (e.g., “ON AMN, AB AMN, and NL AMN functioned as facilitators…”).
- Explain how countervailing patterns were weighed.
- If Overall Valence = Mixed, clearly describe what is facilitating vs hindering and where.
- If Overall Valence = Neutral, explicitly state why directional inference is not supported.
- Anchor all claims in the original Explanation text and/or participant quotes.
- Do NOT introduce mechanisms, causal claims, or interpretations beyond the source data.

SOURCE FILE(S)
List all networks that contributed data to the construct using the format:
"ON AMN ; AB AMN ; NL AMN"

QA AND VALIDATION (MANDATORY; DO NOT OUTPUT)
Before finalizing the output table, perform the following checks for EACH construct and correct any issues found:

1) Network Valence Exclusivity Check
- Each contributing network appears in EXACTLY ONE of:
  Facilitator Networks, Barrier Networks, Mixed Networks, Neutral/Unclear Networks.
- No network appears in more than one of these columns.
- All networks listed in Source File(s) appear in one of the four valence columns.

2) Valence–Synthesis Alignment Check
- The Synthesized Explanation is consistent with the distribution shown in the four network-level valence columns.
- The Overall Valence is defensible given the network-level distribution.
- If Overall Valence = Facilitator or Barrier, the majority of contributing networks align with that direction.
- If Overall Valence = Mixed, both facilitating and barrier patterns are substantively represented.
- If Overall Valence = Neutral, most networks fall under Neutral/Unclear or evidence is explicitly limited.

3) Quote and Evidence Integrity Check
- All retained quotes are verbatim and correctly attributed.
- Network-level valence assignments are traceable to the Explanation text and/or participant quotes.

4) Formatting and Structural Check
- Column order matches the required output exactly.
- Network labels are formatted consistently.
- Semicolon delimiters are used correctly.
- No additional columns, headings, or commentary are added.
