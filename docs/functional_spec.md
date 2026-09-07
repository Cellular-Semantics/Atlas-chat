## Atlas-reporter functional spec for processing and reporting.

### Setup:
- Init:  
    - Request atlas name. --> set up new branch and project directory structure (check we are on main first!)
    - Request submit primary paper + any subatlas papers + annotations (spreadsheet, CxG matrix file or link).  Links are acceptable, or files dropped into input folder in project
    - Paper indexing:
        - Test what papers are reliably available on ASTA?  Test what papers are reliably available as JATS-XML from PMC --> download and index those that are (?).  Attempt to retrieve supplementary material to disk and inspect/index for utility.  
    - Initial report on papers: 
        - What papers & supplementary material are reliably available and what need some manual assist (download)
    - Annotation processing:
        - Functional spec:
            - Process annotation files to CAS+
                - Sources: spreadsheets, h5ad, Zarr or other CELLxGENE. For remote files, prefer remote access and downloading only obs.
                - Check for known schema compliance (e.g. CxG; CAP). Categorise obs fields (columns/keys) as categorical or not (i.e. exclude fields with numeric values and string literals that are likely cell identifiers (1:1 with cells or close to that))
                - Attempt automated matching non-standard fields to cell type annotation fields & CxG standard metadata types. 
    - Initial report on annotations:
        - Report on cell type annotations available + any hierarchy.  If multiple sources exist Questions if multiple clashing sources?
        - Markers available, if so are they derived (e.g. DEGs) or just asserted. If no derived markers provided, ask authors if they are available.
        - Are subatlas annotations available (e.g. as annotations on CellxGene matrix?)

### Output report functional spec.

- Report should be a mini-paper using standard scientific prose and focussing on scientific assertions and data, not on the process of generating the report.  All assertions derived from the literature MUST be backed up by a supporting quote. All quotes must be validated against source.  All IDs (ontology, gene, pub) must be validated.  The report MUST end with a standard biblio/reference section

- When requested, for each annotation, generate a report with full names, synonyms, markers, location, structure function + attempted mapping to CL.  Use the atlas paper + subatlas papers + their citations as preferred source, opening out to free literature search if needed.  Prefer identical context (species, stage, location) for evidence/assertions of cell type properties, but it is OK to use evidence from other sources if this is all that is available or judged to be informative as long as that context is made clear. 
- If markers are available with annotations
    - Distinguish asserted markers from derived markers (DEGs, NS-Forest or any other suitable algorithm).
    - For any asserted marker or marker from the literature, compare to derived markers.  If these markers do not validate identity based DEGs evidence, note any limitations on DEG evidence that might explain (e.g. only top 20 DEGs provided; DEG context is extremely broad (e.g. comparing to whole embryo)).
- For each cell type, report on consistency/inconsistency with subatlas annotations.   This will need some cuttoff to remove long-tail noise.  If possible, try to explain any differences based on markers.
- If location is provided from data in atlas, subatlas, note this location and the nature of the evidence (e.g. spatial transcritpomics)
- Generate draft new CL terms on request and, on request, post these to the CL tracker.  If requested, definitions should be partly based on the atlas being reported on - referencing the annotated cell-set as reference data and folding in location from spatial transcriptomics if available.