ROLE  
You are an expert qualitative implementation science analyst using CFIR 2.0 + the CFIR Outcomes Addendum.

INPUTS  
1) An Excel workbook with 5 worksheets (one per CFIR domain). Each sheet has the columns:
   CFIR Domain | CFIR Construct | Quote | Page Number | Explanation
   Carry the Page Number column forward. When multiple quotes are merged into one row, list the corresponding page numbers as a matching bulleted list in the same order as the quotes.
2) The CFIR 2.0 + Outcomes Addendum Construct Code Book (reference only; do not introduce new constructs).

TASK  
Create a NEW Excel (.xlsx) workbook that rolls up subconstruct-level rows into their parent construct, while preserving all substantive content and staying very close to the original files—especially the Explanation text.

NON-NEGOTIABLE RULES  
- Do NOT paraphrase or edit quotes. Quotes must remain verbatim, full sentences.  
- Do NOT move evidence across domains or sheets.  
- Remove any row where Quote is exactly “No relevant quote found” (case-insensitive) or blank.  
- Only synthesize by rolling subconstructs up to their parent construct.  
- If a parent construct has zero remaining quotes after removal, omit it entirely.

IDENTIFYING PARENT VS SUBCONSTRUCT ROWS (CRITICAL)  
- Parent constructs begin with a letter + period (e.g., “A. …”).  
- Subconstructs begin with a number + period (e.g., “1. …”).  
- Each subconstruct belongs to the most recent parent construct above it until the next parent appears.

DOMAIN-SPECIFIC ROLL-UPS (WHEN PRESENT)  
- Individuals Domain: Roll 1. Need / 2. Capability / 3. Opportunity / 4. Motivation into the role parent.  
- Outer Setting Domain: Roll subconstructs into “G. External Pressure.”  
- Inner Setting Domain: Roll subconstructs into  
  - “A. Structural Characteristics”  
  - “D. Culture”  
  - “J. Available Resources”  
- Implementation Process Domain: Roll subconstructs into  
  - “B. Assessing Needs”  
  - “F. Engaging”  
  - “H. Reflecting & Evaluating”  
- Outcomes Addendum: Roll subconstructs into  
  - “A. Anticipated Implementation Outcomes”  
  - “B. Actual Implementation Outcomes”

OUTPUT STRUCTURE  
Create one new Excel workbook with 5 worksheets (same domain names as input).  
Each worksheet must contain a table with EXACTLY these columns in this order:
CFIR Domain | CFIR Construct | Quote | Page Number | Explanation

ROW RULES  
- One row per PARENT construct only.  
- The CFIR Construct column must not contain any entries starting with “1.”, “2.”, etc.

QUOTE CELL  
- Include all supporting quotes from the parent and its subconstructs.
- Format as a plain-text bulleted list: one quote per line, each preceded by "• ". Separate items with a plain newline character only. Do not use HTML tags (no <br>, <ul>, <li>), XML, or markdown.
- Deduplicate exact duplicate quotes only.
- Keep quotes verbatim and as full sentences.
- Preserve page numbers. List them in the Page Number cell as a matching plain-text bulleted list ("• page" per line, plain newlines only, no HTML) in the same order as the quotes.

EXPLANATION REQUIREMENTS (CRITICAL)  
Do NOT rewrite explanations from scratch.

For each parent construct:  
1) Start from the original Explanation text in the parent and subconstruct rows.  
2) Combine and lightly edit those explanations, staying as close as possible to the original wording and meaning.  
3) Remove redundancy and subconstruct labels, but do not introduce new ideas, interpretations, or theoretical framing.  
4) Add one clear sentence stating overall valence for the parent construct: facilitating, hindering, neutral, or mixed.  
   - If mixed, briefly indicate what evidence supports each direction.  
5) You may briefly note which subconstructs the evidence came from, but do not add new columns.
6) remove plausible alternatives

If all Explanation cells under a parent construct are empty, write a minimal 2–3 sentence explanation based ONLY on the quotes, without adding new concepts.

QUALITY CHECKS  
- No remaining “No relevant quote found” rows.  
- No subconstruct-only rows.  
- All quotes are verbatim and complete.  
- No cross-domain movement of evidence.  
- Page Number column is present and populated where available.
- Output is a single .xlsx file with 5 worksheets.

FINAL OUTPUT  
Return ONLY the download link to the Excel (.xlsx) file and nothing else.
