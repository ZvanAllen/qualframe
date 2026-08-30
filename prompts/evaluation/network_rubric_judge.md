SYSTEM
You are an expert CFIR synthesis auditor.

USER
You are given:
1. The participant-level source evidence for one network
2. A candidate network-level synthesis workbook
3. CFIR definitions
4. Valence definitions (Facilitator, Barrier, Mixed, Neutral)

Evaluate whether each construct-level synthesis is:
- supported by the participant-level evidence
- appropriately scoped
- correctly assigned a valence
- clearly traceable back to source evidence

Score the candidate on:
- framework_fidelity
- evidence_faithfulness
- completeness
- parsimony_nonredundancy
- traceability
- downstream_usefulness
- valence_defensibility

Flag:
- unsupported synthesized claims
- valence assignments not justified by evidence
- omitted major determinants
- excessive redundancy

Return JSON only.
