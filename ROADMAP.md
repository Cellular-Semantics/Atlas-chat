# Roadmap

## 1. Switch to unified queries with cost tracking

**Status:** Not started

The `cellsem_llm_client` library provides `query_unified()` — a single method that combines schema enforcement, tool calling, and usage tracking. The graph currently uses the older `query()` and `query_with_schema()` methods, which discard token counts and cost data.

**Goal:** Replace all LLM calls in `report_graph.py` with `query_unified(..., track_usage=True)`. Accumulate `UsageMetrics` on `ReportState` across all nodes (ResolveName, SnippetSummarizer batches, ScanSupplements, SynthesizeReport + retries). Print a cost summary at the end of each run, and in batch mode, a cumulative total.

**What this enables:**
- Per-run cost reporting (input/output/cached/thinking tokens + USD estimate)
- Batch cost forecasting (run one, extrapolate)
- Provider comparison (same report, Anthropic vs OpenAI cost)

**Effort:** Small. The calls already return structured output; the change is mechanical — swap method, collect `result.usage`, sum at the end.

## 2. LLM-driven citation traversal via tool calling

**Status:** Not started — needs design

The current citation traverser (`citation_traverser.py`) calls `AstaProvider` directly: it runs a fixed snippet search, broadens the query at depth 1, and returns everything. The LLM has no say in which papers are followed or which results are irrelevant.

The agentic workflow (Claude Code) does this differently — the LLM decides which snippets matter, which CorpusIds to follow, and when to stop. This produces more focused evidence and avoids noise from irrelevant citations.

**Goal:** Give the programmatic pipeline the same capability by wiring Semantic Scholar as LLM tools via `query_unified()` with tool calling.

**How it would work:**
1. Define Semantic Scholar tools (`snippet_search`, `get_paper`, `get_paper_batch`, `get_citations`) as `cellsem_llm_client.tools.Tool` objects with handlers that call the ASTA API.
2. Replace the fixed traversal loop with a `query_unified()` call that gives the LLM access to these tools plus a system prompt describing the traversal strategy.
3. The LLM decides: which snippets are relevant, which papers to follow up on, when the evidence is sufficient to stop.
4. The library's `_run_tool_loop` handles the multi-turn conversation automatically.

The library already supports this pattern — `query_unified` accepts `tools` and `tool_handlers`, runs a tool-call loop (up to `max_turns`), and optionally tracks usage across all turns.

Alternatively, `cellsem_llm_client.tools.mcp_source.load_mcp_tools()` can bridge MCP servers directly into LiteLLM tool format, which would let the programmatic pipeline use the same ASTA MCP server as the agentic workflow without duplicating tool definitions.

**What this enables:**
- Selective citation following — the LLM skips irrelevant papers instead of fetching everything
- Deeper traversal without proportional noise — depth 2+ becomes practical
- Convergence between programmatic and agentic workflows — same decision-making, different execution mode
- Cost tracking across the full traversal (via `track_usage=True`)

**Trade-offs to consider:**
- More LLM calls = higher cost per run (but potentially fewer wasted tokens on irrelevant evidence)
- Non-determinism — the LLM may follow different paths on re-runs
- Need to decide: use Tool objects with direct ASTA API handlers, or bridge the MCP server? MCP bridging is simpler (no duplicate code) but adds a process dependency.

**Effort:** Medium. Needs a new traversal prompt, tool definitions, and changes to the FanOut node. The snippet summarizer step may become unnecessary if the LLM extracts quotes during traversal.

## 3. Repository structure cleanup

**Status:** Not started — requires careful planning

The project has an oddly nested structure from early development, with some duplication between levels (e.g. `src/atlas_chat/atlas_chat/`, schemas in multiple locations). This makes navigation confusing and risks divergence between duplicated files.

**Goal:** Flatten to a conventional Python package layout. Eliminate duplicated files and consolidate schemas, prompts, and config into canonical locations.

**Approach — must be done carefully:**
- Work on a dedicated branch, not main
- Audit every file to identify duplicates, dead code, and misplaced assets before moving anything
- Update all internal imports, entry points, pyproject.toml paths, and tool references
- End-to-end test all three modes (programmatic single + batch, agentic workflow, chat) before merging
- Verify: `uv sync`, `atlas-report --dry-run`, a real single-cell run, the agentic `/run-workflow`, and `/chat` all still work
- Keep the PR atomic — structure changes only, no feature work mixed in

**Risk:** High if done carelessly — broken imports, missing prompt files, or stale paths in AGENT.md/CHAT.md could silently break workflows. The careful branch + full test pass mitigates this.

## 4. Project generation workflow

**Status:** Not started — needs design

Currently, setting up a new atlas project requires manually authoring `cell_type_annotations.json` with the atlas DOI, title, and a list of cell type annotations with labels, scope, and granularity. This is tedious for large atlases and error-prone for users unfamiliar with the schema.

**Goal:** An `atlas-generate-project` command (or `/generate-project` in Claude Code) that creates a project config from an atlas source, with two input paths:

### Path A: From an online atlas (Playwright)
1. User provides a URL to an online atlas (e.g. CellxGene, HCA, or similar)
2. Playwright navigates to the atlas and extracts cell type annotations from the UI — labels, hierarchy, metadata
3. The LLM resolves the atlas DOI from the page content or linked publications
4. Generates `cell_type_annotations.json` with all discovered annotations

### Path B: From user-provided tabular data
1. User provides a CSV/TSV/spreadsheet with cell type annotations (at minimum a label column)
2. The LLM infers or asks for: atlas DOI, scope, granularity, and any missing metadata
3. Generates `cell_type_annotations.json`, mapping columns to schema fields

### Shared post-processing
- Validate the generated config against `cell_type_annotation.schema.json`
- Resolve DOI → PMCID via Europe PMC to confirm the atlas paper is accessible
- Optionally deduplicate annotations that appear at multiple granularity levels
- Interactive review: show the user the proposed config and let them edit before saving

**What this enables:**
- Lower barrier to entry — users don't need to understand the JSON schema
- Faster onboarding of new atlases
- Consistent annotation metadata (scope/granularity inferred rather than guessed)

**Effort:** Medium-large. Playwright extraction is atlas-specific and will need per-platform adapters (or a generic strategy that works across common atlas UIs). The CSV path is simpler and should come first.
