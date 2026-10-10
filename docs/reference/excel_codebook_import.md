# Import an Excel codebook

Create or open a managed study, then choose **Source library → Import an Excel codebook**.

1. Upload a standard `.xlsx` workbook and record your name and reason for the change.
2. Select the worksheet and header row. Check the first five rows shown in the preview.
3. Map **Code ID**, **Code label**, and **Definition**. These fields are required for each populated data row. IDs should be stored as text in Excel, especially if they contain leading zeros.
4. Optionally map parent code IDs, inclusion/exclusion guidance, and examples. Put each example on its own line within the cell. Leave parent mapping blank for a flat codebook.
5. Validate and preview the codes, then select **Import this codebook version**.

The active codebook changes only on the final import. Original workbook bytes, their hash, the column mapping, the converted YAML, and its hash are preserved in the study. Previous versions and completed runs are not overwritten. Repeating the same confirmation is rejected; use a new upload for a new version.

The reader supports one table per selected worksheet, up to 10,000 data rows plus a header and 100 columns, with a 25 MB compressed / 100 MB expanded limit. The header may be within the first 100 rows. Remove explanatory/footer rows from the selected table. Blank rows are ignored. Duplicate headings are identified by their column letters. Formulas and Excel errors are rejected; paste their intended values before importing. Dates and booleans must be represented explicitly as text. Merged layouts and automatic reconstruction of hierarchies are not supported.

Duplicate IDs, unknown parents, hierarchy cycles, missing required values, invalid mappings, and changed preview sources block import. Framework validity and coding quality still require methodological review; structural validation does not establish either.

Current boundary: this importer supplies the generic directed-analysis codebook. The legacy CFIR pipeline retains its separately configured reference workbook and prompts; importing a generic codebook does not rewrite that legacy workflow.
