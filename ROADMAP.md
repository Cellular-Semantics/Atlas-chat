# Roadmap

## Implementation Order

| Phase | What | Branch | Tests Written During |
|-------|------|--------|----------------------|
| 0 | End-to-end acceptance spec | main | `scripts/e2e_smoke.py` — smoke checks only |
| 1 | Repository cleanup | `cleanup/flatten-package-structure` | Smoke checks must pass before merge |
| 2 | Agentic refactor (items 1+2 merged) | `feature/llm-driven-traversal` | Unit tests for stable modules + tool defs |
| 3 | Project generation | `feature/project-generation` | Schema validation, CSV parsing tests |

Phases 2 and 3 can run in parallel after Phase 1 merges.

---

## Phase 0: End-to-End Acceptance Criteria

Before any structural changes, define what "nothing broke" means. This is a specification, not a test suite — a script (`scripts/e2e_smoke.py`) that verifies all three modes without API calls.

### Programmatic mode
- `uv sync` succeeds
- `atlas-report --project fetal_skin_atlas --cell-type "Macro_1" --dry-run` exits 0
- `from atlas_chat.validation.report_checker import validate_report` imports successfully
- `from atlas_chat.services.atlas_paper import load_project_config` loads config and returns DOI
- `validate_report(report_path, traversal_dir)` passes for 3 existing reports (Macro_1, Treg, NK)

### Agentic mode
- All `@` path references in AGENT.md resolve to real files
- All paths in `.claude/agents/*.md` resolve
- `.claude/hooks/check_report_refs.py` imports `atlas_chat.validation.report_checker`
- All 5 prompt YAMLs load via `load_prompt()`

### Chat mode
- CHAT.md path references resolve
- `/load-project-context` can locate project data

### Golden-data regression
- Pick 3 representative reports. Run `validate_report()` against their traversal data. These must pass. This catches changes to validation logic or evidence format assumptions.
- `check_quotes` and `check_references` are pure functions; their behaviour on known inputs is the regression contract.

---

## Phase 1: Repository Structure Cleanup

**Status:** Not started
**Branch:** `cleanup/flatten-package-structure`
**Prerequisite:** Phase 0 smoke script exists and passes

### Problem

Oddly nested `src/atlas_chat/atlas_chat/` structure from early scaffolding. Schemas duplicated between `src/schemas/` and the inner package. Empty shadow directories at the outer level.

### Target layout

```
src/atlas_chat/
  __init__.py
  cli.py
  agents/        ← prompt YAMLs
  graphs/
  llm/
  schemas/       ← consolidated (merge both locations)
  services/
  utils/
  validation/
  pyproject.toml
```

### Sequence

1. Audit and document what lives where
2. Flatten: move `src/atlas_chat/atlas_chat/*` up one level, delete inner directory
3. Update internal imports (package name `atlas_chat` stays the same)
4. Update all `@` path references in AGENT.md, CHAT.md, `.claude/agents/*.md`
5. Consolidate schemas into `src/atlas_chat/schemas/`
6. Fix `prompt_loader.py` `_AGENTS_DIR` path calculation (one fewer nesting level)
7. Update `pyproject.toml` paths (setuptools find, coverage source, mypy packages)
8. Decide on `atlas_chat_validation_tools` — keep or remove empty stubs
9. Run Phase 0 smoke checks — all must pass before merge

**Rules:** Structure changes only. No feature work. No logic changes.

**Highest-risk breakage points:**
- `prompt_loader.py` `_AGENTS_DIR` — navigates `parent.parent`; after flattening this is wrong
- AGENT.md `@` imports — if not updated, agentic workflow silently can't find prompts

---

## Phase 2: Agentic Refactor — LLM-Driven Traversal with Cost Tracking

**Status:** Not started — needs design
**Branch:** `feature/llm-driven-traversal`
**Merges ROADMAP items 1 (unified queries) and 2 (LLM-driven traversal)**

### Why merge items 1 and 2

The whole point of `query_unified()` is to support tool-calling loops with usage tracking — exactly what LLM-driven traversal needs. Doing cost tracking first without the traversal refactor means touching the same code twice.

### Design philosophy: priorities, not procedures

The current programmatic traverser is rigid: fixed snippet search, broaden at depth 1, return everything. The agentic path lets the LLM decide. The refactored programmatic path should adopt the agentic philosophy with budget constraints:

**Give the LLM priorities, not steps:**
1. First: find direct evidence about this cell type in the seed paper
2. Second: if the seed paper references other studies of this cell type, follow those
3. Third: broaden to the cell type in other tissue contexts if direct evidence is thin
4. Stop when evidence covers markers, function, and location — or after N tool calls

**Constrain cost, not behaviour.** Set `max_turns` on `query_unified()` to cap total tool calls. Track usage via `track_usage=True`. This is a budget guardrail, not a behaviour script.

**Do not overfit to the fetal_skin_atlas reports.** The 34 existing reports are a validation baseline, not a training set. The refactored pipeline should produce reports of comparable quality but not identical content (different traversal paths, different quotes). The regression test is: `validate_report()` passes on newly generated reports.

### Atlas paper full text

AGENT.md currently says "Prefer `snippet_search` over `get_europepmc_full_text`." This is correct for agentic sessions (huge output, fragile download). But the programmatic path already fetches full text (FetchSupplements node).

**Resolution:** Keep the snippet-first guidance for the agentic workflow. For the programmatic path, make full text available as a tool the LLM can query on demand — a `search_atlas_full_text(query)` tool that does local text search against the already-fetched document. The traversal prompt should mention it as a fallback: "If snippet search does not cover methodology or supplementary table references, search the atlas paper full text."

This matters because subtle decisions (e.g. which annotations are integrated from external sources, tissue-specific terminology) often require reading the methods or figure legends — information that snippet search may not surface.

### Sequence

1. Define Semantic Scholar tools as `cellsem_llm_client.tools.Tool` objects (or bridge via `load_mcp_tools()` if ASTA MCP server is already running)
2. Replace `citation_traverser.py` with `services/llm_traverser.py` — same interface, LLM-driven internals
3. Replace `_llm_call()` in `report_graph.py` with `query_unified(..., track_usage=True)`
4. Accumulate `UsageMetrics` on `ReportState`, print cost summary per run and per batch
5. Simplify or remove `_summarize_snippets` if the LLM extracts quotes during traversal
6. Add `search_atlas_full_text` tool for the programmatic traversal

### Tests written during this phase
- Unit tests for `report_checker.py` (stable pure logic — the validation contract)
- Unit tests for `atlas_paper.py` (config loading, path helpers)
- Unit tests for `prompt_loader.py` (YAML loading, template rendering)
- Unit tests for new tool definitions (serialization, handler dispatch)
- Integration test (marked, skipped without API keys): single cell type end-to-end

### Trade-offs
- More LLM calls = higher cost per run, but fewer wasted tokens on irrelevant evidence
- Non-determinism — different paths on re-runs; the validation contract is deterministic even if content is not
- Tool bridge vs direct handlers: MCP bridging is simpler but adds a process dependency

---

## Phase 3: Project Generation Workflow

**Status:** Not started — needs design
**Branch:** `feature/project-generation`
**Independent of Phase 2 — can develop in parallel after Phase 1**

### Problem

Setting up a new atlas project requires manually authoring `cell_type_annotations.json` — tedious for large atlases and error-prone for unfamiliar users.

### Goal

An `atlas-generate-project` command (or `/generate-project` in Claude Code) that creates project config from an atlas source.

### Path A: From user-provided tabular data (first)
1. User provides CSV/TSV with cell type annotations (minimum: label column)
2. LLM infers or asks for: atlas DOI, scope, granularity, missing metadata
3. Generates `cell_type_annotations.json`, mapping columns to schema fields

### Path B: From an online atlas (second, Playwright)
1. User provides URL to online atlas (CellxGene, HCA, etc.)
2. Playwright extracts cell type annotations from the UI
3. LLM resolves atlas DOI from page content or linked publications
4. Generates `cell_type_annotations.json`

### Shared post-processing
- Validate against `cell_type_annotation.schema.json`
- Resolve DOI → PMCID via Europe PMC
- Optionally deduplicate annotations at multiple granularity levels
- Interactive review before saving

### Tests written during this phase
- Unit tests for schema validation
- Unit tests for CSV/TSV column mapping
- Integration test for DOI → PMCID resolution

---

## Coverage Ratchet (ongoing, not a discrete phase)

Tests are written during Phases 1–3, not as a standalone effort. The 60% coverage threshold should be adjusted:

- After Phase 1: lower to 0% or write `report_checker` + `atlas_paper` unit tests to reach ~30%
- After Phase 2: should reach 40–60% from tests written during the refactor
- Ratchet up as new code is added

The pre-commit hook should enforce whatever the current floor is, not an aspirational target that forces bypass.
