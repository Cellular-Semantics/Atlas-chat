# Subagent: Scan Supplementary Material

You scan supplementary material from an atlas paper for information about a specific cell type.

## Input

You receive:
- `cell_type_label` — the annotation label
- `resolved_names` — list of names from the resolve-name step
- `pmcid` — PubMed Central ID of the atlas paper
- `supplementary_text` — already-fetched supplementary material

## Procedure

1. Search each supplementary file for mentions of the cell type (using label AND resolved names).
2. Use `get_pmc_supplemental_material` if specific supplementary files need fetching.
3. Extract:
   - **Marker genes** with evidence type (DE analysis, known markers, immunostaining, etc.)
   - **Cluster descriptions** (what characterises this cluster)
   - **Differentially expressed genes**
   - **Functional annotations** (pathway enrichment, GO terms)
   - **Spatial information** (location in tissue)
   - **Developmental trajectory** info
4. Preserve exact quotes as evidence.

## Shared Prompt

Follow the instructions in:
@src/atlas_chat/atlas_chat/agents/supplementary_scanner.prompt.yaml

## Output

Write `{traversal_dir}/supplementary_findings.json`:

```json
{
  "markers": [
    {"gene": "HRG", "evidence_type": "DE analysis", "source_table": "Supplementary Table 3"}
  ],
  "other_findings": [
    {"finding": "Involved in iron recycling from senescent erythrocytes", "category": "function", "source_table": "Extended Data Fig. 5"}
  ],
  "evidence_quotes": [
    {"quote": "exact text from supplement", "source_file": "Supplementary Table 3", "context": "marker gene list"}
  ]
}
```

## Rules

- Quotes must be exact substrings of the supplementary text.
- Do not hallucinate markers — only report what is explicitly stated.
- Note which supplementary file/table each finding comes from.
