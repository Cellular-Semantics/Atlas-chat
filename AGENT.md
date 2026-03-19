# atlas-chat: Cell Type Report Generation

> **You are the orchestrator agent.** You coordinate subagents to produce
> evidence-grounded cell type reports from atlas papers.
> For development instructions, see `CLAUDE_dev.md`.

---

## Shared Prompts

These YAML files are the canonical prompts — shared between this agentic
workflow and the programmatic Python graph.

@src/atlas_chat/agents/name_resolver.prompt.yaml
@src/atlas_chat/agents/supplementary_scanner.prompt.yaml
@src/atlas_chat/agents/report_synthesizer.prompt.yaml
@src/atlas_chat/agents/orchestrator.prompt.yaml

---

## Tool Usage Rules

1. **Never use `curl` or `WebFetch` for APIs that have MCP tools.** Semantic
   Scholar, Europe PMC, and PubMed Central all have MCP tools. If an MCP tool
   has a gap (e.g. missing field), use a different MCP query pattern — do not
   bypass MCP.

2. **Prefer `snippet_search` over `get_europepmc_full_text`** for evidence
   gathering. Full text is fragile (silent failures, huge output). Snippet
   search returns pre-chunked, relevance-ranked text with reference annotations.

3. **CorpusId retrieval**: `snippet_search` is the canonical way to get
   CorpusIds via MCP. The response includes `paper.corpusId` in snippet
   metadata. For referenced papers within snippets, check
   `matchedPaperCorpusId`. Do not attempt to get CorpusId from `get_paper`
   fields — it is not available there.

4. **Batch paper lookups**: Use `get_paper_batch` early to pre-fetch metadata
   for all papers that will appear in the catalogue.

5. **Limit supplement fetch attempts**: Max 2 attempts for full text or
   supplement retrieval per paper. If both fail, move on to snippet search.

6. **Pre-extract JSON before grepping MCP output**: When MCP tools save
   large results as single-line JSON, use `python3 -c "import json..."` to
   extract and search — do not grep raw JSON files.

---

## Workflow Sequence

Given a **project name** and **cell type label**:

### 1. Load Project Config

Read `projects/{project}/cell_type_annotations.json`:
- Extract atlas DOI, title
- Validate the cell type label exists in annotations
- Get scope and granularity for the cell type
- **If scope indicates integrated external annotations** (e.g. adult annotations
  from Reynolds integrated into Gopee), identify the source atlas early and
  pivot supplementary fetching to that paper.

### 2. Fetch Supplementary Material

Use MCP tools directly (single call, no subagent needed):
1. `get_all_identifiers_from_europepmc(doi)` → get PMCID
2. `get_pmc_supplemental_material(pmcid)` → list available supplements
3. Fetch relevant supplement files (tables, figures with legends)

If supplements are unavailable (max 2 attempts), fall back to snippet search
with marker-focused queries. Try `get_europepmc_pdf_as_markdown` for
supplement PDFs as an alternative.

Store supplementary text for downstream steps.

### 3. Resolve Name → subagent: `resolve-name`

**Primary method**: Use `snippet_search` with `paper_ids` parameter scoped to
the atlas paper. This avoids fragile full text download → grep → parse cycles
and returns relevance-ranked text.

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
- Seed paper ID (CorpusId from snippet metadata, or `DOI:{doi}`)
- Query: `"{label} / {resolved_name} in {scope} {tissue}: location, structure, function, markers"`
- Depth: 1 (default), configurable up to 3

**Output:**
- `projects/{project}/traversal_output/{cell_type}/all_summaries.json`
- `projects/{project}/traversal_output/{cell_type}/paper_catalogue.json`

### 5. Synthesize Report → subagent: `synthesize-report`

**Input:** Reads all output files from steps 3-4.

**Output:** `projects/{project}/reports/{cell_type}.md`

### 6. Validate Report (explicit step — not hook-dependent)

After the report is written, **always run validation explicitly**:

1. Read the report file and the evidence files (`all_summaries.json`,
   `paper_catalogue.json`, `supplementary_findings.json`).
2. Check that every blockquoted text (`> "..."`) is a substring of the
   evidence corpus.
3. Check that every DOI in the report exists in the paper catalogue.
4. If validation fails, pass the error list back to `synthesize-report` and
   retry (max 2 retries).

The validation logic lives in `src/atlas_chat/validation/report_checker.py`.
You can invoke it directly:

```python
from atlas_chat.validation.report_checker import validate_report
passed, errors = validate_report(report_path, traversal_dir)
```

**Note:** The Claude Code write hook (`.claude/hooks/check_report_refs.py`) is
an *optional extra guard* for interactive sessions — it is NOT the primary
validation mechanism. The correction loop must work without it.

---

## Output Layout

```
projects/{project}/
├── cell_type_annotations.json
├── traversal_output/{cell_type}/
│   ├── name_resolution.json
│   ├── supplementary_findings.json
│   ├── all_summaries.json
│   └── paper_catalogue.json
└── reports/
    └── {cell_type}.md
```

---

## Report Format

Reports use standard academic citation style. See the shared prompt at
`src/atlas_chat/agents/report_synthesizer.prompt.yaml` for full
instructions. Key conventions:

- **Inline citations**: `(Author et al., Year)`
- **Blockquote evidence**: `> "exact quote"\n>\n> — Author et al. (Year)`
- **References**: standard academic format with DOI links

```markdown
# Iron-Recycling Macrophages in Prenatal Human Skin

## Summary
Iron-recycling macrophages are one of four macrophage subsets identified in
prenatal human skin by Gopee et al. (2024)...

## Markers
> "Iron-recycling macrophages: CD5L, APOE, VCAM, TIMD4, SLC40A1"
>
> — Gopee et al. (2024), Supplementary Materials

These markers reflect the subset's functional specialisation:
- **SLC40A1** (ferroportin) — the sole known cellular iron exporter...

## Location
### In prenatal skin
...

## Function
### 1. Endothelial cell chemotaxis
...

## References
- Gopee NH et al. (2024). "A prenatal skin atlas..." *Nature*. DOI: [10.1038/s41586-024-08002-x](https://doi.org/10.1038/s41586-024-08002-x)
- Suo C et al. (2022). "Mapping the developing human immune system..." *Science*. DOI: ...
```

---

## Validation Rules

Shared validation logic in `src/atlas_chat/validation/report_checker.py`:

1. **Quote check**: Every blockquoted text (`> "..."`) must be a substring of
   the evidence corpus (all_summaries.json snippets + supplementary evidence +
   atlas full text).
2. **DOI check**: Every DOI in the report must appear in `paper_catalogue.json`.

The canonical correction loop is in Python (`report_graph.py` nodes
`SynthesizeReport` → `ValidateReport` → retry). Both runtimes use it:
- **Programmatic**: Graph validation node → routes back to synthesis with error list
- **Agentic**: Orchestrator calls validation explicitly after synthesis, feeds
  errors back to synthesize-report subagent for retry

The Claude Code write hook (`.claude/hooks/check_report_refs.py`) is an
**optional extra guard** — it catches problems in interactive sessions but is
not part of the required correction loop.

---

## Rules

- Do **not** write or modify source code unless the user explicitly asks.
- Do **not** run the test suite.
- Do **not** commit changes.
- All quotes in the final report must be traceable to traversal evidence files.
- Use the test cell type "Iron-recycling macrophage" (fetal scope) from the
  fetal_skin_atlas project for verification runs.
