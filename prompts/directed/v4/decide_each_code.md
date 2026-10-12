# Directed content analysis: decide every code, version 1

You are assisting a qualitative researcher with directed (deductive) content analysis. Apply the codebook supplied with this request to the document. For every code in it, decide whether the document contains evidence for that code. The researcher will check every decision, so faithful quotation matters, and so does not missing a code that applies.

## How to decide

1. Read the whole document before deciding.
2. Work through every code supplied, in order. For each code, look for passages that fit its definition and inclusion guidance and are not ruled out by its exclusion guidance.
3. If one or more passages fit, give each as a separate coding with an exact quotation.
4. If no passage fits, record the code as absent, with a one-sentence reason.
5. Every code supplied must appear in your answer at least once, either as a coding or as absent.
6. Code the substance the codebook is about. Do not code headings, reference lists, or interviewer or facilitator questions.
7. Use the most specific code that fits. Do not code a group heading or parent code that is not offered as a code.

## Quotations

- Copy each quotation exactly as it appears in the document: the same words, spelling, punctuation and capitalisation. Do not paraphrase, correct, shorten with ellipses, or join separate passages.
- The application locates each quotation by searching the document for it. Keep the quotation to the relevant passage, but make sure it is long enough to occur only once in the document.

## Output

Return one JSON object and nothing else, in this form:

{"decisions": [{"code_id": "id from the codebook", "present": true, "quote": "exact document text", "rationale": "why the passage fits the code"}, {"code_id": "another id", "present": false, "quote": "", "rationale": "why no passage fits"}]}

- Give one entry per quotation for a code that is present, and exactly one entry with "present": false and an empty quote for a code that is absent.
- code_id: the code's id exactly as written in the codebook.
