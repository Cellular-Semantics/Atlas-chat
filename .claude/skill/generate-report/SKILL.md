---
name: generate-report
description: Generate a structured, evidence-grounded cell type report from an atlas project. Fetches supplementary material, resolves cell type names, traverses citations, and synthesizes a validated markdown report.
---

# Generate Cell Type Report

You orchestrate the full report generation workflow as defined in AGENT.md.

## Input

`$ARGUMENTS` contains:
- `--project` followed by the project directory name (e.g. `fetal_skin_atlas`)
- `--cell-type` followed by the cell type label (e.g. `"Iron-recycling macrophage"`)
- `--depth N` (optional, default 1, max 3)

If arguments are missing, ask the user.

## Procedure

Follow the orchestration sequence defined in AGENT.md:

1. **Load project config**: Read `projects/{project}/cell_type_annotations.json` to get atlas DOI, title, and validate the cell type label exists.

2. **Fetch supplementary material**: Use `get_all_identifiers_from_europepmc` with the atlas DOI to get the PMCID, then use `get_pmc_supplemental_material` to fetch supplements.

3. **Resolve name**: Dispatch to the `resolve-name` subagent.
   - Pass: cell type label, atlas DOI, scope, supplementary text
   - Wait for: `{traversal_dir}/name_resolution.json`

4. **Parallel: Scan supplements + Citation traverse**:
   - Dispatch `scan-supplements` subagent with supplementary text + resolved names
   - Dispatch `citation-traverse` subagent with seed paper ID + query built from resolved name
   - Wait for both to complete

5. **Synthesize report**: Dispatch `synthesize-report` subagent.
   - It reads all output files and writes the report
   - The write hook validates automatically
   - If hook rejects, the subagent retries (max 2 times)

## Output Layout

```
projects/{project}/
├── traversal_output/{cell_type}/
│   ├── name_resolution.json
│   ├── supplementary_findings.json
│   ├── depth_0_snippets.json
│   ├── depth_0_summaries.json
│   ├── all_summaries.json
│   └── paper_catalogue.json
└── reports/
    └── {cell_type}.md
```

## Completion

Print a summary:
```
REPORT GENERATED
================
Cell type: {label}
Resolved names: {names}
Scope: {scope}
Papers discovered: N
Summaries with quotes: M
Report: projects/{project}/reports/{cell_type}.md
```
