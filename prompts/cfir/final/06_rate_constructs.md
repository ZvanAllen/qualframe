TBC

You are an implementation science analyst with expertise in CFIR qualitative coding and construct rating.

You are given TWO Excel workbooks:
1) A CFIR coding workbook (multiple sheets). Each sheet contains rows with columns:
   - CFIR Domain
   - CFIR Construct
   - Quote
   - Page Number
   - Explanation
2) A CFIR rating rubric workbook that contains:
   - An "Introduction" sheet with general guidance
   - A "CFIR Construct Scales" sheet with one row per construct and anchor descriptions for ratings

GOAL
For each of the 6 sheets in the CFIR coding workbook:
- Add a new column immediately after “Explanation” called: Rating
- Populate Rating for every data row using the rubric instructions and the construct-specific anchors in “CFIR Construct Scales”.

RATING VALUES
Use exactly one of: -2, -1, 0, X, 1, 2
- -2 = opposite of construct strongly present (strong barrier / strong negative valence)
- -1 = opposite of construct present (barrier / negative valence)
- 0  = construct absent / not evidenced in the quote+explanation
- X  = mixed data (credible evidence in BOTH directions OR conflicting evidence)
- 1  = construct present (facilitator / positive valence)
- 2  = construct strongly present (strong facilitator / strong positive valence)

UNIPOLAR SCALES
In “CFIR Construct Scales”, some constructs are Unipolar (the rubric row will indicate Unipolar and/or show N/A for negative anchors).
- For Unipolar constructs, valid ratings are typically: 0, 1, 2 (and X if mixed).
- Do NOT assign -1 or -2 when the rubric indicates N/A for negative anchors.

HOW TO APPLY THE RUBRIC (PER ROW / PER QUOTE)
For each row in each CFIR coding sheet:
1) Read CFIR Construct, Quote, and Explanation.
2) Look up the matching construct row in the rubric (“CFIR Construct Scales”) by exact construct name.
3) Use:
   - the construct definition
   - the scale stem
   - the anchor descriptions for each rating level
   to choose the best-fitting rating.
4) Use ONLY the evidence in Quote + Explanation (do not invent context).
5) If there is not enough evidence to rate, leave Rating blank and flag it in a summary list as “Needs review”.

MISSING OR NON-RATEABLE CONSTRUCTS
If the construct name from the coding workbook is NOT found in the rubric sheet:
- Leave Rating blank (or “NA” if you must write something)
- Record it in a “Missing rubric” list in the summary.

OUTPUT
- Save a NEW workbook (do not overwrite the original) with the Rating column added and filled.
- Preserve sheet names and existing columns.
- Provide:
  (a) the saved file
  (b) a summary table: counts of rated rows, blanks (“Needs review”), and “Missing rubric” rows by sheet
  (c) a list of constructs that were missing from the rubric (unique values)

IMPLEMENTATION NOTES (USE PYTHON)
Use Python (openpyxl and/or pandas) to:
- Load both workbooks
- Build a tidy lookup table from “CFIR Construct Scales”:
    construct name → definition, scale stem, anchors (-2,-1,0,X,+1,+2), and scale type (bipolar/unipolar)
- Iterate each coding sheet row-by-row and write the Rating value into the new column
- Save the updated workbook

Be careful: the rubric sheet contains domain header rows; ignore those and only keep rows with actual construct names.
Also handle minor whitespace differences in construct names (strip spaces).
