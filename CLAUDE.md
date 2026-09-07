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

## Tool Usage Rules

1. **Never use `curl` or `WebFetch` for APIs that have MCP tools or a project
   CLI.** Semantic Scholar, Europe PMC, and PubMed Central all have MCP tools;
   paper text access goes through `python -m atlas_chat.cli_annotate`.

2. **Literature evidence is JATS-first, whole-text, via the CLI.**
   `cli_annotate route` decides each paper's access route (local JATS cache →
   Europe PMC → preprint fetch → ASTA), `read` writes a whole-text reader job
   file, and ASTA `snippet_search` is the *fallback* for papers no JATS route
   serves — not the default. Never open raw JATS XML in your context and never
   paste a job file's text into a dispatch: readers get the job-file *path*.

3. **CorpusId retrieval**: `snippet_search` responses carry `paper.corpusId` in
   snippet metadata, and `matchedPaperCorpusId` for referenced papers within
   snippets. `get_paper` can also return it via `fields=externalIds`.

4. **Batch paper lookups**: Use `get_paper_batch` early to pre-fetch metadata
   for all papers that will appear in the catalogue.

5. **Supplements come from the store on disk** (`cli_supplements`), populated at
   setup — never fetched into agent context mid-run. A paper with no store is a
   setup gap to report, not something to fetch around.

6. **Pre-extract JSON before grepping MCP output**: When MCP tools save
   large results as single-line JSON, use `python3 -c "import json..."` to
   extract and search — do not grep raw JSON files.

## Run Settings

- **`reader_model`** — the model pinned on every evidence-reading subagent
  (gather-evidence and free-search readers). Default **`opus`** (measured:
  reader model moved results more than any retrieval choice; the cheaper
  model's losses are confident, quote-backed wrong answers). Set per run;
  every dispatch names its model explicitly and records it in
  `reader_provenance.json` — never rely on model inheritance.
- Structural steps (resolve-name, query-decomposer, scan-supplements,
  synthesize-report, CL steps) stay on `sonnet`.

---

## Workflow Sequence

Given a **project name** and a **query** — a free-text specification of which cell
types to report on, optionally with contextual restrictions (e.g. "all fibroblasts",
"fibroblasts in adult tissue", or a single cell-type label):

### 1. Load Project Config (CAS+)

The project config is a **CAS+** document at `projects/{project}/cas.json`
(schema: `src/atlas_chat/atlas_chat/schemas/cas_annotation.schema.json`). CAS+
supersedes the legacy flat `cell_type_annotations.json`.

- **If `projects/{project}/cas.json` exists and validates**, load it and move on.
- **Otherwise**, invoke the `generate-cas` skill
  (`.claude/skills/generate-cas/SKILL.md`) to build it from the project's
  source(s), asking the user for anything not derivable (DOI, organism, which
  column is the cell-type label). The `check_cas_annotation` PostToolUse hook
  enforces schema compliance on write.

From the loaded CAS+ document:
- Extract atlas DOI + title from `source`.
- Validate the requested cell type label exists as an annotation `cell_label`.
- Read its `labelset` (granularity) and context from `composition`
  (e.g. developmental stage / organism / tissue).
- **If an annotation's provenance points to an integrated subatlas** (via
  `transferred_annotations[].subatlas_paper` / `source_taxonomy`), identify that
  source paper early and pivot supplementary fetching to it.

> Migration note: downstream steps below still reference the legacy `label` /
> `scope` fields; their input contracts move to CAS+ `cell_label` / `composition`
> as part of the query-decomposer work.

### 1b. Select target cell types (from the query)

Interpret the **query** against the CAS+ annotations to choose which cell types to
report on. Match flexibly — as a knowledgeable curator would — on `cell_label`,
`lineage` / hierarchy, and `synonyms`; apply any contextual restriction in the query
(developmental stage, tissue, organism, disease, …) as a filter over each
annotation's `composition`. Do **not** impose a rigid query grammar: a query like
"all fibroblasts" or "fibroblasts in adult tissue" is interpreted directly, and a
bare cell-type label selects just that annotation.

Record the resolved selection to `projects/{project}/selections/{slug}.json` for
provenance (slug derived from the query text):

```json
{
  "query": "fibroblasts in adult tissue",
  "context": { "developmental_stage": "adult" },
  "cas_source": "projects/{project}/cas.json",
  "selected": [
    { "cell_label": "...", "cell_set_accession": "...", "labelset": "..." }
  ]
}
```

**Steps 2–9 below run once per selected cell type.** The query's contextual
restriction carries forward as that cell type's scope.

### 2. Check the Supplement Store

Supplements live in the on-disk store at `projects/{project}/supplements/`
(manifest per paper). Check it covers the corpus papers this run needs — the
atlas, plus any subatlas paper the annotations' provenance points at:

```
python -m atlas_chat.cli_supplements papers --store projects/{project}/supplements
```

If a needed paper is missing, populate it once (setup, not per cell type):
`python -m atlas_chat.cli_supplements fetch --store <store> --doi <doi>`, then
the `index-supplements` skill to build its content manifest. If retrieval fails
(closed access), record the gap and continue — `scan-supplements` reports "no
store" distinctly from "nothing found". Do not fetch supplement bytes into
agent context mid-run.

### 3. Resolve Name → subagent: `resolve-name`

**Primary method**: Use `snippet_search` with `paper_ids` parameter scoped to
the atlas paper. This avoids fragile full text download → grep → parse cycles
and returns relevance-ranked text.

**Input:**
- CAS+ annotation for the cell type: `cell_label`, plus any CAS `synonyms`
  (`provided_synonyms` — resolve-name **unions** these with paper-found names)
- Atlas DOI; scope/tissue from the annotation's `composition`
- Supplementary text from step 2

**Output:** `projects/{project}/traversal_output/{cell_type}/name_resolution.json`
(schema: `src/atlas_chat/atlas_chat/schemas/name_resolution.schema.json`)

**Contract:**
```json
{
  "label": "Iron-recycling macrophage",
  "resolved_names": ["Iron-recycling macrophage", "HRG+ macrophage"],
  "scope": "fetal",
  "tissue_context": "fetal skin",
  "confidence": "high",
  "evidence": "Found in cluster annotations table",
  "source_paper": { "corpus_id": "CorpusId:2762329", "doi": "10.1038/s41586-024-08002-x", "role": "atlas" }
}
```

### 3b. Decompose query → subagent: `query-decomposer`

For each selected cell type, dispatch `query-decomposer` with its CAS+ annotation,
`name_resolution.json`, and the query's context. It writes
`projects/{project}/traversal_output/{cell_type}/query_decomposition.json`
(schema: `src/atlas_chat/atlas_chat/schemas/query_decomposition.schema.json`):
grounding (`subject`, `aliases`, `non_subject_terms`, `scope`, `seed`) plus one
authored query per fixed aspect (`location, structure, function, markers,
marker_roles`) and a `combined_query`. Validated by the `check_query_decomposition`
PostToolUse hook.

### 4. Parallel: Gather Evidence + Scan Supplements

These two steps are independent after step 3b. Run them in parallel.

#### 4a. Gather Evidence → skill: `gather-evidence`

The literature-search core: JATS-first whole-text reading with ASTA fallback,
plus citation traversal (depth ≤ 2). Follow
`.claude/skills/gather-evidence/SKILL.md`.

**Input** (`gather_evidence_input.schema.json`):
- `seeds` — priority-ordered: the paper that defines the cell type first
  (a subatlas paper when `transferred_annotations` / name resolution's
  `source_paper` says so), then the atlas paper.
- `decomposition_path` — step 3b's `query_decomposition.json`
- `depth` (default 1, max 2), `k_per_paper`, `run_cap`
- `reader_model` — from Run Settings (default `opus`)
- `project_dir`, `output_dir`

**Output:**
- `projects/{project}/traversal_output/{cell_type}/all_summaries.json`
- `projects/{project}/traversal_output/{cell_type}/paper_catalogue.json`
- plus `traversed.json`, `gaps.json`, `reader_provenance.json`

(The `citation-traverse` subagent remains as the ASTA-route procedure the skill
delegates to; it is no longer dispatched directly by the orchestrator.)

#### 4b. Scan Supplements → skill: `scan-supplements`

Store-backed extraction (`.claude/skills/scan-supplements/SKILL.md`). Run once
per corpus paper with a store — the atlas and each seed subatlas paper.

**Output:** `projects/{project}/traversal_output/{cell_type}/supplementary_findings.json`

### 4c. Assess Coverage → skill: `assess-coverage`

Judge per-aspect, in-scope coverage over `all_summaries.json` +
`supplementary_findings.json` against the decomposition's `scope`
(`.claude/skills/assess-coverage/SKILL.md`).

**Output:** `projects/{project}/traversal_output/{cell_type}/coverage.json`

### 4d. Free Search (conditional) → skill: `free-search`

Only for aspects `coverage.json` marks `thin`/`absent`: one unscoped ASTA
search per aspect (keyword query + scope terms), evidence tagged `free_search`,
coverage updated — an aspect that still gains nothing becomes
`absent_after_free_search` (`.claude/skills/free-search/SKILL.md`).

### 5. Synthesize Report → skill: `synthesize-report`

Follow `.claude/skills/synthesize-report/SKILL.md`: sections in decomposition-
aspect order, `Sources:` header, absent aspects rendered exactly as
"No evidence found in traversed literature.", caveats for abstract-only /
snippet-bound / free-search support.

**Output:** `projects/{project}/reports/{cell_type}.md`

### 6. Validate Report → skill: `validate-report` (explicit — not hook-dependent)

Follow `.claude/skills/validate-report/SKILL.md`: quote grounding, DOI
resolution, source tags, blockquote attribution — then the retry loop (errors
back to `synthesize-report`, max 2 retries).

**Note:** The Claude Code write hook (`.claude/hooks/check_report_refs.py`) is
an *optional extra guard* for interactive sessions — it is NOT the primary
validation mechanism. The correction loop must work without it.

### 7. Map to Cell Ontology → subagent: `ontology-term-lookup`

After the report passes validation, map the cell type to the Cell Ontology.

**Input:**
- Report path from step 5
- Cell type label
- Output path: `projects/{project}/traversal_output/{cell_type}/cl_mapping.json`

**Output:** `projects/{project}/traversal_output/{cell_type}/cl_mapping.json`

The subagent searches OLS4 for CL terms, compares definitions against the
report content, and classifies the match as exact, broad, narrow, or none
using SKOS vocabulary. Output conforms to the JSON Schema at
`src/atlas_chat/atlas_chat/schemas/cl_mapping.schema.json` and is validated
by a PostToolUse hook.

### 8. Insert CL Mapping into Report Header

After the CL mapping JSON is written, insert the mapping metadata into the
report header block (between the title line and `## Summary`). Read
`cl_mapping.json` and add a `Cell Ontology` line:

- **Exact match:**
  `Cell Ontology: [basal cell of epidermis](http://purl.obolibrary.org/obo/CL_0002187) (CL:0002187, exact match)`
- **Broad match:**
  `Cell Ontology: [keratinocyte](http://purl.obolibrary.org/obo/CL_0000312) (CL:0000312, broad match — no exact CL term)`
- **No match:**
  `Cell Ontology: No CL term (new term needed)`

The PURL format is `http://purl.obolibrary.org/obo/CL_NNNNNNN` (underscore,
not colon).

### 9. Draft CL Term Request (conditional) → subagent: `cl-term-request`

**Only run this step if** `cl_mapping.json` has `"new_term_needed": true`.

**Input:**
- Report path from step 5
- CL mapping path from step 7
- Output path: `projects/{project}/traversal_output/{cell_type}/cl_term_request.json`

**Output:** `projects/{project}/traversal_output/{cell_type}/cl_term_request.json`

The subagent generates a draft new term request following:
- CL definition guidelines (`docs/LLM_prompt_guidelines_for_CL_definitions.md`)
- CL relations guide (`docs/relations_guide.md`)
- CL NTR issue template (`docs/cl_new_term_request_template.md`)

Output includes structured JSON (definition, parent, axioms, synonyms,
references) and a pre-rendered `ntr_markdown` field ready to paste into a
GitHub issue on `obophenotype/cell-ontology`. The JSON is validated by a
PostToolUse hook against the schema at
`src/atlas_chat/atlas_chat/schemas/cl_term_request.schema.json`.

### 10. Post CL Term Request to GitHub (conditional, requires confirmation)

**Only run this step if:**
- Step 9 produced a `cl_term_request.json`
- A GitHub token with `public_repo` scope is available
- The user explicitly confirms they want to post

**This step modifies an external shared repository. Always ask the user
before posting.** Show them the `ntr_markdown` content and the target repo
first.

**Authentication:** Pass the token via `GH_TOKEN` so the user's default `gh`
credentials are unaffected. The token must have `public_repo` scope.

**Procedure:**

1. Read `cl_term_request.json` and extract `suggested_label` and `ntr_markdown`.
2. Show the user the draft issue title and body for review.
3. On confirmation, post:

```bash
GH_TOKEN=$(grep ATLAS_CHAT_GH_TOKEN .env | cut -d= -f2) gh issue create \
  --repo obophenotype/cell-ontology \
  --title "[NTR] {suggested_label}" \
  --label "new term request" \
  --body "$ntr_markdown"
```

4. Record the returned issue URL in the report header, appending it to the
   Cell Ontology line:
   `Cell Ontology: ... (broad match — NTR: obophenotype/cell-ontology#NNN)`

**Never post without user confirmation.** This creates a public issue on an
external repository.

**Note:** A GitHub App-based alternative (`gh-app-post` CLI) is implemented
at `src/github_app_posting/` for future use — posts as a bot identity without
a personal token.

---

## Output Layout

```
projects/{project}/
├── cas.json
├── selections/{slug}.json
├── supplements/papers/<doi-slug>/{manifest.json, files/}
├── local_index/papers/<doi-slug>/source/paper.jats.xml   # JATS cache (router-fed)
├── traversal_output/{cell_type}/
│   ├── name_resolution.json
│   ├── query_decomposition.json
│   ├── papers/paper_<n>.json          # reader job files (whole text + citations)
│   ├── traversed.json                 # per-run seen-set
│   ├── gaps.json                      # unreachable papers, with reasons
│   ├── reader_provenance.json         # model per reader job
│   ├── supplementary_findings.json
│   ├── all_summaries.json
│   ├── coverage.json
│   └── paper_catalogue.json
└── reports/
    └── {cell_type}.md
```

---

## Report Format

Reports use standard academic citation style. See the shared prompt at
`src/atlas_chat/atlas_chat/agents/report_synthesizer.prompt.yaml` for full
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

Shared validation logic in `src/atlas_chat/atlas_chat/validation/report_checker.py`:

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
