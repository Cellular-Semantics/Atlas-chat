# Atlas Chat — Codebase Overview

---

## 1. Top-Level Directory Structure

| Directory / File | Responsibility |
|---|---|
| `src/atlas_chat/` | Core Python package — CLI, PydanticAI graph, agents, services, validation |
| `src/atlas_chat_validation_tools/` | Stub package (scaffolded, not yet implemented) for offline report comparison / metrics |
| `src/github_app_posting/` | Standalone package for posting GitHub issues via GitHub App auth (bot identity, no personal token) |
| `src/schemas/` | Shared JSON schema — `cell_type_annotations.schema.json` (the project config format) |
| `.claude/agents/` | Claude Code subagent system prompts (`.md` files) for the agentic workflow |
| `.claude/commands/` | Claude Code slash commands: `/chat` and `/run-workflow` |
| `.claude/hooks/` | PostToolUse hooks run by Claude Code on file writes (report validation, CL mapping validation, CL term request validation) |
| `.claude/skills/` | Reusable Claude Code skills (`anndata-zarr-summary`, `local-paper-index`, `load-project-context`) |
| `.mcp.json` | MCP server definitions (artl-mcp, Semantic Scholar/ASTA, Playwright, OLS4, paper-search) |
| `projects/` | One directory per atlas project; each contains `cell_type_annotations.json` and generated output |
| `docs/` | CL definition guidelines, relations guide, NTR template, preprint citation options |
| `planning/` | Internal design notes and post-mortems (not loaded at runtime) |
| `scripts/` | CLI shims and maintenance scripts (legacy entrypoint, ring graduation, local index setup) |
| `tests/unit/` | Fast unit tests (local snippet index, JATS parser, PDF parser) |
| `tests/integration/` | Real-API integration tests (run locally only, skipped in CI) |
| `CLAUDE.md` | Loaded by Claude Code as the orchestrator's operating manual |
| `CLAUDE_dev.md` | Development conventions for agents editing this codebase |

---

## 2. Entry Points

**Programmatic CLI** (`atlas-report` console script):
- Defined in `src/atlas_chat/pyproject.toml`: `atlas-report = "atlas_chat.cli:main"`
- Source: `src/atlas_chat/atlas_chat/cli.py:main()`
- Legacy shim: `scripts/generate_report.py` (thin wrapper, calls the same graph)

**Agentic (Claude Code) workflows:**
- `/run-workflow` → `.claude/commands/run-workflow.md` → spawns orchestrator following `CLAUDE.md`

**Supplementary prose CLI:**
- `python -m atlas_chat.cli_supplement_prose` — `units` extracts every prose supplement
  (docx, PDF, txt) to disk and hands back one block per document: the whole text when it is
  short, its PDF section outline or a head/middle/tail sample when it is not. `record` merges
  what a reader concluded into the manifest's `prose`; `cas-uptake` notes that a pointer fed
  CAS+. Spreadsheets are untouched — those are `cli_supplements` outline/slice.

**Local index CLI** (secondary entry point within `local_snippet_index.py`):
- `src/atlas_chat/atlas_chat/services/local_snippet_index.py:main()` — `build`, `add`, `remove`, `list`, `search` subcommands

**GitHub App posting CLI:**
- `gh-app-post` → `src/github_app_posting/github_app_posting/cli.py:main()`

---

## 3. Core Flow — Programmatic Path

Starting from `atlas-report --project fetal_skin_atlas --cell-type "Iron-recycling macrophage"`:

```
cli.py:main()
  └── _run_single()
        ├── load_project_config("fetal_skin_atlas")
        │     └── atlas_paper.py:AtlasConfig.from_project()
        │           reads projects/fetal_skin_atlas/cell_type_annotations.json
        └── asyncio.run(run_report_graph(config, cell_type, depth, provider, model))
              └── report_graph.py:run_report_graph()
                    ├── llm/factory.py:create_agent()
                    │     └── cellsem_llm_client.create_litellm_agent()
                    │           reads ANTHROPIC_API_KEY / OPENAI_API_KEY from env
                    └── report_graph.Graph.run(FetchSupplements(), state, deps)
```

**Graph nodes** (each is a `pydantic_graph.BaseNode`), executed in sequence:

| Step | Node | What it does |
|---|---|---|
| 1 | `FetchSupplements` | Calls `europepmc.resolve_identifiers(doi)` → gets PMCID; calls `europepmc.get_full_text()` and `get_supplementary_text()` via HTTPS to EBI; saves `atlas_full_text.txt` |
| 2 | `ResolveName` | Calls LLM via `_llm_call(agent, "name_resolver", ...)` which loads `name_resolver.prompt.yaml`, renders it, sends to the LLM; saves `name_resolution.json` |
| 3 | `FanOut` | Creates two async tasks — `_scan_supplements` + `_citation_traverse` — and awaits both with `asyncio.gather()` |
| 3a | `_scan_supplements` | LLM call with `supplementary_scanner.prompt.yaml`; saves `supplementary_findings.json` |
| 3b | `_citation_traverse` | Calls `citation_traverser.traverse()` (ASTA/Semantic Scholar snippet search, up to depth 3); optionally calls `traverse_local()` for a local vector index; merges results; runs `_summarize_snippets()` (LLM batches via `snippet_summarizer.prompt.yaml`); saves `raw_snippets.json`, `all_summaries.json`, `paper_catalogue.json` |
| 4 | `SynthesizeReport` | LLM call with `report_synthesizer.prompt.yaml` combining all evidence; saves draft report to `reports/{cell_type}.md` |
| 5 | `ValidateReport` | Calls `report_checker.validate_report()` — checks every blockquote is a verbatim substring of evidence, every DOI exists in catalogue; on failure routes back to `SynthesizeReport` (max 2 retries) |
| 6 | `SaveReport` | Writes final report; returns path |

**Agentic path** (via `/run-workflow`): identical steps but Claude Code orchestrates them using MCP tools directly, following the same CLAUDE.md sequence, with the same subagent prompts and output JSON contracts.

---

## 4. Key Abstractions

**`AtlasConfig`** (`atlas_paper.py:17`) — dataclass loaded from `cell_type_annotations.json`. Single source of truth for DOI, title, annotations list, and derived paths. Has `traversal_dir(cell_type)` and `reports_dir()` factory methods that create directories on access.

**`ReportState` / `ReportDeps`** (`report_graph.py:39,61`) — PydanticAI graph state/deps pattern. `ReportState` is mutable (threaded through every node), `ReportDeps` is immutable (injected once). This keeps node logic free of constructor arguments.

**`AgentConnection`** (`cellsem_llm_client`) — external LiteLLM wrapper. All LLM calls go through `agent.query()` or `agent.query_with_schema()`. The factory (`llm/factory.py:create_agent()`) is the only place that touches provider names and API keys.

**`_llm_call()`** (`report_graph.py:75`) — internal helper that: loads a YAML prompt file → renders template variables → calls the agent. Keeps prompt management out of node logic.

**`AstaProvider`** (`deep_research_client`) — wraps Semantic Scholar's snippet search API. Used by `citation_traverser.py` for ASTA snippet search and by the MCP server for the agentic path.

**Local snippet index** (`local_snippet_index.py`) — self-contained vector search engine: JATS XML or PDF → paragraph segments → chunks → sentence-transformers embeddings (`all-MiniLM-L6-v2`) → ASTA-shape `snippets.json`. The `search()` function returns the same dict shape as ASTA snippets, so downstream code is source-agnostic. Multi-paper corpus model with one `atlas` paper and zero or more `subatlas` papers. `@lru_cache` on `_load_index()` keeps embeddings in memory across calls.

A chunk (~2800 chars) is the unit stored and returned, but the model only reads 256 word pieces, so each chunk is embedded as one or more overlapping windows that fit and `chunks/window_index.json` maps every row of `embeddings.npy` back to its chunk. A chunk scores as the best of its windows and is returned once, with its full text. Indexes built before this carry truncated vectors and no window index; `_load_index()` skips them with a warning, and `setup_local_index.py rebuild` re-embeds a whole corpus from the sources on disk (reusing the cached reference resolution, which is far slower than the embedding).

**`report_checker.py`** — shared between the Python graph (node `ValidateReport`) and the Claude Code hook (`.claude/hooks/check_report_refs.py`). `check_quotes()` does normalised substring matching with ellipsis splitting; `check_references()` validates DOIs and CorpusIds against the catalogue.

**Prompt YAML files** — co-located with agents in `src/atlas_chat/atlas_chat/agents/*.prompt.yaml`. Each has `system_prompt` / `user_prompt` keys with `{variable}` placeholders. `prompt_loader.py:render_prompt()` uses `str.format_map` with a default-passthrough dict so missing variables are left intact rather than raising.

**Claude Code subagent definitions** — `.claude/agents/*.md` files, each loaded as a subagent context for one workflow step (name resolver, supplement scanner, citation traverser, report synthesizer, ontology term lookup, CL term request drafter). These parallel the YAML prompts but are used by the agentic path.

---

## 5. API Keys and Credentials

| Variable | File where consumed | Service |
|---|---|---|
| `ANTHROPIC_API_KEY` | `src/atlas_chat/atlas_chat/llm/factory.py:84` | Anthropic LLM calls (default provider) |
| `OPENAI_API_KEY` | `src/atlas_chat/atlas_chat/llm/factory.py:84` | OpenAI LLM calls (alternative provider) |
| `ASTA_API_KEY` | `src/atlas_chat/atlas_chat/services/citation_traverser.py:25` | Semantic Scholar snippet search (ASTA) |
| `ASTA_API_KEY` | `.mcp.json:18` — HTTP header `x-api-key` | Same service, via MCP in agentic path |
| `ATLAS_CHAT_GH_TOKEN` | `CLAUDE.md:245` — extracted from `.env` via grep | Personal GitHub token for posting CL NTR issues (optional, human-confirmed step) |
| `GITHUB_APP_ID` | `src/github_app_posting/github_app_posting/config.py:12` | GitHub App ID for bot posting (alternative to personal token) |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `src/github_app_posting/github_app_posting/config.py:13` | Path to RSA private key for GitHub App JWT signing |
| `GITHUB_APP_INSTALLATION_ID` | `src/github_app_posting/github_app_posting/config.py:14` | GitHub App installation ID |

All keys are loaded from a `.env` file at the repo root (via `python-dotenv`, called by `cellsem_llm_client.load_environment()` in `factory.py:64`). No secrets are hardcoded in source.

The GitHub App private key file path is configured separately — the key itself lives at the filesystem path specified in `GITHUB_APP_PRIVATE_KEY_PATH` or `~/.config/github_app_posting/config.json`.

---

## 6. Major Dependencies

| Package | Role |
|---|---|
| `pydantic-ai` / `pydantic_graph` | Graph orchestration — `BaseNode`, `Graph`, `GraphRunContext`. Each pipeline step is a typed node with explicit state threading |
| `cellsem-llm-client` (git dep) | LiteLLM wrapper (`AgentConnection`); `load_environment()` loads `.env`; `create_litellm_agent()` builds the agent |
| `deep-research-client` (git dep) | `AstaProvider` for Semantic Scholar snippet search; `AstaPaper`, `AstaSnippet` model types |
| `httpx` | HTTP client for Europe PMC REST API (`europepmc.py`), Semantic Scholar batch lookups, GitHub App token exchange |
| `pydantic` | Data models (`AtlasConfig`, `PaperIdentifiers`, `GitHubAppConfig`), JSON schema validation |
| `pyyaml` | Loads `.prompt.yaml` files |
| `jsonschema` | Used in hooks to validate `cl_mapping.json` and `cl_term_request.json` against JSON schemas |
| `python-dotenv` | `.env` loading (delegated to `cellsem_llm_client`) |
| `sentence-transformers` | `all-MiniLM-L6-v2` embeddings for local snippet index (optional dep under `[local-index]` extra) |
| `numpy` | Vector math for cosine similarity in local search |
| `pymupdf4llm` | PDF-to-markdown extraction, used by the supplement store and the local index (optional dep under `[text-access]` extra) |
| `curl-cffi` | Fetching preprint JATS past Cloudflare (optional dep under `[text-access]` extra) |
| `PyJWT` + `cryptography` | GitHub App JWT minting in `github_app_posting/auth.py` |
| `ruff`, `mypy`, `pytest`, `sphinx` | Dev tooling (lint, type check, tests, docs) |

---

## 7. Flags and Attention Items

**Git dependencies unpinned** — two packages are installed from GitHub `@main` with no content hash:
- `cellsem-llm-client @ git+https://github.com/Cellular-Semantics/cellsem_llm_client.git@main`
- `deep-research-client @ git+https://github.com/monarch-initiative/deep-research-client.git@main`

A breaking upstream change would silently break the install without changing `uv.lock`.

**`atlas_chat_validation_tools` is a stub** — all three submodules (`comparisons/`, `metrics/`, `visualizations/`) are empty `__init__.py` files with README stubs. It is present in the workspace but has no runnable code.

**Coverage threshold is 0** (`pyproject.toml` — `fail_under = 0`). The CI gate exists but is not enforcing meaningful coverage yet (noted in ROADMAP as intentional, to be ratcheted up).

**Integration tests skip in CI** (`.github/workflows/test.yml:56–57`). They require real API keys and must be run locally before pushing.

**`ATLAS_CHAT_GH_TOKEN` extraction is fragile** — `CLAUDE.md` reads it from `.env` using `grep ATLAS_CHAT_GH_TOKEN .env | cut -d= -f2`. This breaks if the line has a comment, trailing whitespace, or quote wrapping.

**`europepmc.get_full_text()` strips XML with a regex** (`europepmc.py:93` — `re.sub(r"<[^>]+>", " ", resp.text)`). It is a fast approximation, not a lossless parse. The local index JATS parser (`local_snippet_index.py`) uses `xml.etree.ElementTree` for higher-fidelity extraction.

**Unauthenticated Semantic Scholar batch calls** — `_resolve_dois_to_corpus_ids()` (`local_snippet_index.py:362`) hits the public S2 batch API without an API key. Heavy use or CI could hit 429s. The function has exponential back-off but only 3 attempts.

**Planning artefacts** — `planning/` contains a post-mortem and a design doc dated March 2026 describing known prompt-loosening work and a performance issue with `Inf_mono` reports. Worth reading before tuning prompts.
