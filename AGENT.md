# atlas-chat: Cell Type Report Generation

> **You are the orchestrator agent.** You coordinate subagents to produce
> evidence-grounded cell type reports from atlas papers.
> For development instructions, see `CLAUDE_dev.md`.

---

## Shared Prompts

These YAML files are the canonical prompts — shared between this agentic
workflow and the programmatic Python graph.

@src/atlas_chat/atlas_chat/agents/name_resolver.prompt.yaml
@src/atlas_chat/atlas_chat/agents/supplementary_scanner.prompt.yaml
@src/atlas_chat/atlas_chat/agents/report_synthesizer.prompt.yaml
@src/atlas_chat/atlas_chat/agents/orchestrator.prompt.yaml

---

## Workflow Sequence

Given a **project name** and **cell type label**:

### 1. Load Project Config

Read `projects/{project}/cell_type_annotations.json`:
- Extract atlas DOI, title
- Validate the cell type label exists in annotations
- Get scope and granularity for the cell type

### 2. Fetch Supplementary Material

Use MCP tools directly (single call, no subagent needed):
1. `get_all_identifiers_from_europepmc(doi)` → get PMCID
2. `get_pmc_supplemental_material(pmcid)` → list available supplements
3. Fetch relevant supplement files (tables, figures with legends)

Store supplementary text for downstream steps.

### 3. Resolve Name → subagent: `resolve-name`

**Input:**
- Cell type label, atlas DOI, scope
- Supplementary text from step 2

**Output:** `projects/{project}/traversal_output/{cell_type}/name_resolution.json`

**Contract:**
```json
{
  "label": "Iron-recycling macrophage",
  "resolved_names": ["Iron-recycling macrophage", "HRG+ macrophage"],
  "scope": "fetal",
  "tissue_context": "fetal skin",
  "confidence": "high",
  "evidence": "Found in cluster annotations table"
}
```

### 4. Parallel: Scan Supplements + Citation Traverse

These two steps are independent after name resolution. Run them in parallel.

#### 4a. Scan Supplements → subagent: `scan-supplements`

**Input:**
- PMCID, cell type label + resolved names
- Supplementary text from step 2

**Output:** `projects/{project}/traversal_output/{cell_type}/supplementary_findings.json`

**Contract:**
```json
{
  "markers": [{"gene": "HRG", "evidence_type": "DE analysis", "source_table": "..."}],
  "other_findings": [{"finding": "...", "category": "function", "source_table": "..."}],
  "evidence_quotes": [{"quote": "exact text", "source_file": "...", "context": "..."}]
}
```

#### 4b. Citation Traverse → subagent: `citation-traverse`

**Input:**
- Seed paper ID (CorpusId from identifier resolution, or `DOI:{doi}`)
- Query: `"{label} / {resolved_name} in {scope} {tissue}: location, structure, function, markers"`
- Depth: 1 (default), configurable up to 3

**Output:**
- `projects/{project}/traversal_output/{cell_type}/all_summaries.json`
- `projects/{project}/traversal_output/{cell_type}/paper_catalogue.json`

### 5. Synthesize Report → subagent: `synthesize-report`

**Input:** Reads all output files from steps 3-4.

**Output:** `projects/{project}/reports/{cell_type}.md`

The write hook (`.claude/hooks/check_report_refs.py`) automatically validates:
- All quotes are exact substrings of evidence
- All CorpusId references exist in paper_catalogue.json

**If hook rejects:** The synthesize-report subagent sees the errors in stderr
and retries with corrections (max 2 retries).

---

## Output Layout

```
projects/{project}/
├── cell_type_annotations.json
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

---

## Report Format

```markdown
# {Cell Type Full Name} ({annotation_label})
Atlas: {atlas_title} (DOI: {doi})
Scope: {scope}

## Summary
Brief overview (2-3 sentences).

## Location
> "exact quote" — [Author2024](CorpusId:NNN) Title

Claim grounded by quote.

## Function
> "exact quote" — [Author2024](CorpusId:NNN) Title

## Markers
| Gene | Evidence | Source |
|------|----------|--------|
| GENE | > "quote about marker" | [Author2024](CorpusId:NNN) |

## Structure / Morphology
...

## References
- CorpusId:NNNNNNN | Author et al. (Year) "Title" — DOI:xxx
```

---

## Validation Rules

Shared validation logic in `src/atlas_chat/atlas_chat/validation/report_checker.py`:

1. **Quote check**: Every blockquoted text (`> "..."`) must be a substring of
   the evidence corpus (all_summaries.json quotes + supplementary evidence quotes).
2. **Reference check**: Every `CorpusId:NNN` in the report must appear as a key
   in `paper_catalogue.json`.

Same logic, two feedback loops:
- **Agentic**: Hook exits 2 → Claude sees stderr → self-corrects
- **Programmatic**: Graph validation node → routes back to synthesis with error list

---

## Rules

- Do **not** write or modify source code unless the user explicitly asks.
- Do **not** run the test suite.
- Do **not** commit changes.
- All quotes in the final report must be traceable to traversal evidence files.
- Use the test cell type "Iron-recycling macrophage" (fetal scope) from the
  fetal_skin_atlas project for verification runs.
