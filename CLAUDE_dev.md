# atlas-chat — Development Guide

> For running the workflow, see `AGENT.md`.
> For the chat interface, see `CHAT.md`.
> For the implementation roadmap, see `ROADMAP.md`.

---

## What this project does

Generate evidence-grounded cell type reports from atlas papers and their citation networks. Three execution modes share the same validation logic, prompt templates, and output structure:

| Mode | Entry point | How it works |
|------|-------------|--------------|
| **Programmatic** | `atlas-report` CLI | PydanticAI graph orchestrates services and agents |
| **Agentic** | `/run-workflow` | Claude Code orchestrator delegates to subagents via MCP tools |
| **Chat** | `/chat` | Interactive Q&A against cached traversal evidence |

---

## Package Layout

```
src/atlas_chat/
  __init__.py
  cli.py                 # Entry point: atlas-report
  agents/                # Agentic LLM loops + co-located prompt YAMLs
  graphs/                # Orchestration (PydanticAI graph nodes)
  schemas/               # JSON schemas (source of truth)
  services/              # API calls + one-shot LLM calls + LLM factory
  utils/                 # General utilities (prompt_loader, provenance)
  validation/            # Cross-cutting validation logic (report_checker)
  pyproject.toml
```

### Directory roles

The key distinction is **who controls the flow**:

| Directory | Role | Controls flow? |
|-----------|------|----------------|
| `agents/` | Agentic LLM calls — multi-turn tool loops where the LLM decides the path | LLM controls |
| `services/` | API calls + one-shot LLM calls (prompt → response). Also houses the LLM factory. | Caller controls |
| `graphs/` | Orchestration — PydanticAI graph nodes that call services and agents | Graph controls |
| `schemas/` | JSON schemas → Pydantic models derived programmatically | N/A |
| `utils/` | General utilities | N/A |
| `validation/` | Cross-cutting validation logic shared across modes | N/A |

**Agent vs Service:**
- **Service**: `query()`, `query_with_schema()` — one-shot, even with a thinking model. The caller decides what happens next.
- **Agent**: `query_unified(tools=..., tool_handlers=..., max_turns=N)` — multi-turn tool loop. The LLM decides which tools to call, interprets results, and decides when to stop. The caller sets the budget.

### Prompt files

All prompts live as `.prompt.yaml` files co-located with the agents/services that use them. Loaded via `utils/prompt_loader.py`.

```
agents/name_resolver.prompt.yaml
agents/supplementary_scanner.prompt.yaml
agents/snippet_summarizer.prompt.yaml
agents/report_synthesizer.prompt.yaml
agents/orchestrator.prompt.yaml
```

### Shared assets (single source of truth)

These files are consumed by both the programmatic and agentic workflows:
- `schemas/*.schema.json` — constrain output in both modes
- `agents/*.prompt.yaml` — define behaviour in both modes
- `validation/report_checker.py` — validation logic used by graph nodes and Claude Code hooks

`AGENT.md` references shared assets via `@` imports. Python code reads them via `yaml.safe_load()` and `json.load()`.

---

## Agentic workflow structure

The agentic mode uses Claude Code subagents defined as markdown:

```
.claude/
  agents/
    resolve-name.md         # Name resolution specialist
    scan-supplements.md     # Supplementary material scanner
    citation-traverse.md    # Citation graph traverser
    synthesize-report.md    # Report writer
  commands/
    run-workflow.md         # /run-workflow skill (loads AGENT.md)
    chat.md                 # /chat skill (loads CHAT.md)
  skills/
    load-project-context.md # /load-project-context for chat sessions
  hooks/
    check_report_refs.py    # PostToolUse validation guard
```

---

## Data flow

```
Project Config (cell_type_annotations.json)
    │
    ▼
FetchSupplements → Europe PMC API (or MCP in agentic mode)
    │
    ▼
ResolveName → one-shot LLM call (service)
    │
    ├─► ScanSupplements → one-shot LLM call (service)
    │
    └─► CitationTraverse → agentic tool loop (agent)
    │
    ▼
SynthesizeReport → one-shot LLM call (service)
    │
    ▼
ValidateReport → pure logic (validation/report_checker.py)
    ├─ Pass → SaveReport
    └─ Fail (< 2 retries) → SynthesizeReport with error feedback
```

Intermediate outputs saved to `projects/{project}/traversal_output/{cell_type}/`.
Final reports saved to `projects/{project}/reports/{cell_type}.md`.

---

## External dependencies

| Library | Purpose |
|---------|---------|
| `cellsem-llm-client` | LLM agent creation, `query_unified()` with tool calling and usage tracking |
| `deep-research-client` | `AstaProvider` — Semantic Scholar API wrapper |
| `pydantic-ai` | Graph orchestration (`pydantic_graph`) |
| `pyyaml` | Prompt YAML loading |
| `jsonschema` | Schema validation |

### MCP servers (agentic mode only)

| Server | Tools |
|--------|-------|
| `Asta_semanticscholar` | `snippet_search`, `get_paper`, `get_paper_batch`, `get_citations` |
| `artl-mcp` | `search_europepmc_papers`, `get_europepmc_paper_by_id`, `get_europepmc_full_text`, `get_pmc_supplemental_material` |

---

## Development commands

```bash
uv sync                              # Install dependencies
uv run atlas-report --help           # CLI usage

# Quality checks (also run by .githooks/pre-commit)
uv run ruff check --fix src/ tests/  # Lint
uv run ruff format --check src/ tests/  # Format
uv run pytest -m unit --cov          # Unit tests + coverage

# Integration tests (requires API keys in .env)
uv run pytest -m integration

# Smoke checks (no API keys needed)
uv run python scripts/e2e_smoke.py
```

---

## Testing strategy

- **Unit tests** (`tests/unit/`): Fast, no external deps. Use `@pytest.mark.unit`.
- **Integration tests** (`tests/integration/`): Real API calls. Use `@pytest.mark.integration`. Fail hard if no credentials.
- **Smoke checks** (`scripts/e2e_smoke.py`): Verify imports, prompt loading, path references, and golden-data validation without API calls.

Coverage threshold ratchets up as tests are added (see ROADMAP). Currently 0% — being built during the agentic refactor phase.

---

## Rules for development

- Extend existing code when possible — don't rewrite without reason
- Schema-first: define JSON schemas, derive Pydantic models programmatically
- Prompts in YAML files, never hardcoded
- Save intermediate outputs at each step for debuggability
- All quotes in reports must be traceable to evidence files
- Integration tests use real APIs, not mocks
- `experiments/` is excluded from all quality checks — use it for exploratory work

---

## Key files

| File | Role |
|------|------|
| `cli.py` | Entry point, batch orchestration, dry-run |
| `graphs/report_graph.py` | 6-node PydanticAI graph |
| `services/atlas_paper.py` | Config loading, path helpers |
| `services/citation_traverser.py` | ASTA snippet search + depth traversal |
| `services/europepmc.py` | ID resolution, full text, supplements |
| `validation/report_checker.py` | Quote + DOI validation (shared by graph + hook) |
| `utils/prompt_loader.py` | YAML loading + template rendering |
| `AGENT.md` | Agentic workflow instructions |
| `CHAT.md` | Chat mode instructions |
| `ROADMAP.md` | Implementation plan with phased delivery |
