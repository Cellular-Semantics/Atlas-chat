# Atlas Chat

## Overview

Cell types in online single-cell atlases are typically annotated with short and sometimes obscure names. Understanding what these names mean — and what is known about the cell types they describe — requires looking up the atlas paper and following its citations. While this scholarly workflow remains essential, it creates a significant barrier to efficient and effective browsing of online atlases.

Atlas Chat addresses this problem by enabling researchers to explore the literature associated with online atlases directly, without leaving their browsing context.

## What It Does

Atlas Chat supports three complementary modes of operation:

1. **Cell type reports (programmatic)** — A PydanticAI graph pipeline that generates structured reports for individual cell types, drawn from the atlas paper and its cited literature. Run via the `atlas-report` CLI.

2. **Cell type reports (agentic)** — An interactive Claude Code workflow (`/run-workflow`) that achieves the same result using MCP tools and subagents. Useful for exploratory runs and debugging.

3. **Chat across the literature** — An interactive Claude Code mode (`/chat`) for asking questions spanning the primary atlas paper and any papers it cites, with answers grounded in the source material.

All three modes produce output backed by exact quotes from source papers, allowing users to assess accuracy and navigate directly to the primary literature.

## Design Principles

- **Source transparency** — Every claim is backed by a direct quote from a source paper, so users can judge the evidence for themselves.
- **Literature navigation** — Quotes are linked to their source papers, enabling users to move quickly from a summary to the primary literature.
- **Complement, not replace** — Atlas Chat lowers the barrier to efficient browsing, not to substitute for careful scholarly reading of the original papers.

## Hallucination Detection

LLMs fabricate quotes. Atlas Chat treats this as a first-class problem.

Every blockquote in a generated report is verified against the collected evidence corpus before the report is saved. The validator checks that each quoted passage is a verbatim substring of a source paper (normalising whitespace, dashes, and smart quotes; handling ellipsis-separated segments). Every DOI and CorpusId reference is checked against the paper catalogue. If any check fails, the report is regenerated with explicit error feedback — up to two retries.

**What this guarantees:** quoted text in a final report actually appears in the cited source. **What it does not guarantee:** that the surrounding narrative accurately interprets those quotes, or that the most relevant literature was found. Users should always follow quotes back to their source papers to assess context.

## Quick Start

### Installation

```bash
# Clone and install
git clone <repo-url> && cd atlas_chat
uv sync
```

Create a `.env` file in the repository root with the required API keys:

```
ANTHROPIC_API_KEY=sk-...
ASTA_API_KEY=...
# Optional, only needed for OpenAI provider:
OPENAI_API_KEY=sk-...
```

### Generate a Single Report

```bash
atlas-report --project fetal_skin_atlas --cell-type "Iron-recycling macrophage"
```

### Generate All Reports (Batch Mode)

```bash
# Generate reports for every annotation in the project
atlas-report --project fetal_skin_atlas --batch

# Only fill gaps — skip cell types that already have a report
atlas-report --project fetal_skin_atlas --batch --no-stomp

# Preview what would happen without running anything
atlas-report --project fetal_skin_atlas --batch --no-stomp --dry-run
```

### CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--project NAME` | *(required)* | Project directory name under `projects/` |
| `--cell-type LABEL` | | Single cell type label (mutually exclusive with `--batch`) |
| `--batch` | | Generate reports for all annotations (mutually exclusive with `--cell-type`) |
| `--no-stomp` | off | Skip cell types whose report file already exists |
| `--depth N` | 1 | Citation traversal depth (max 3) |
| `--dry-run` | off | Show execution plan without making LLM calls |
| `--provider` | anthropic | LLM provider: `anthropic` or `openai` |
| `--model` | *(provider default)* | LiteLLM model ID, e.g. `claude-sonnet-4-20250514`, `gpt-4.1` |
| `--verbose` / `-v` | off | Enable DEBUG logging and full stack traces |

The legacy invocation `uv run python scripts/generate_report.py ...` still works via a thin shim.

## Project Configuration

Each atlas project lives in `projects/{project_name}/` and is defined by a single file, `cell_type_annotations.json`:

```json
{
  "source": {
    "doi": "10.1038/s41586-024-08002-x",
    "title": "A prenatal skin atlas reveals immune regulation of human skin morphogenesis"
  },
  "annotations": [
    {
      "label": "Iron-recycling macrophage",
      "granularity": "fine",
      "scope": "fetal"
    },
    {
      "label": "DC1",
      "granularity": "fine",
      "scope": "adult"
    }
  ]
}
```

- `source.doi` is required. `pmcid` and `corpus_id` can be pre-populated to skip runtime resolution.
- Each annotation requires `label`; `granularity` (`fine`/`broad`) and `scope` (`fetal`/`adult`/`organoid`) are optional.
- The schema is defined in `src/schemas/cell_type_annotation.schema.json`.

## How It Works

### Report Generation Pipeline

Both the programmatic and agentic workflows follow the same six-step sequence:

1. **FetchSupplements** — Resolve the atlas DOI to a PMCID via Europe PMC, fetch full text and supplementary file listings.
2. **ResolveName** — LLM call to identify the author-used terminology for the cell type in the atlas paper.
3. **ScanSupplements + CitationTraverse** *(parallel)* — LLM-driven extraction of markers and findings from supplements, plus Semantic Scholar snippet search at configurable depth to build a paper catalogue with verified exact quotes.
4. **SynthesizeReport** — LLM call to generate a markdown report from all collected evidence.
5. **ValidateReport** — Check that every blockquoted passage is a substring of the evidence corpus and that all referenced papers exist in the catalogue. On failure, retry synthesis (up to 2 retries).
6. **SaveReport** — Write the final validated report to `projects/{project}/reports/{cell_type}.md`.

### Output Structure

```
projects/{project}/
├── cell_type_annotations.json           # Project configuration (user-authored)
├── traversal_output/{cell_type}/
│   ├── atlas_full_text.txt              # Fetched atlas paper text
│   ├── name_resolution.json             # Resolved cell type names
│   ├── supplementary_findings.json      # Extracted markers and findings
│   ├── raw_snippets.json                # Raw citation snippets
│   ├── all_summaries.json               # Processed summaries with verified quotes
│   └── paper_catalogue.json             # Metadata for all discovered papers
└── reports/
    └── {cell_type}.md                   # Final validated report
```

### Validation

Reports are validated before saving:

- **Quote checking** — Every `> "..."` blockquote must be a substring of the evidence corpus (with normalisation for whitespace, dashes, smart quotes, and ellipsis segments).
- **Reference checking** — Every DOI or CorpusId in the report must exist in the paper catalogue.

If validation fails, the synthesis step is retried with specific error feedback (up to 2 retries).

## Interactive Modes (Claude Code)

These modes require a Claude Code session with the project's MCP servers configured (see `.claude/settings.local.json`).

### Agentic Workflow

```
/run-workflow
```

Launches the same report generation pipeline interactively, using MCP tools and Claude Code subagents. The orchestrator follows `AGENT.md` and delegates to specialised subagents in `.claude/agents/`.

### Literature Chat

```
/chat
```

An interactive question-answering mode for exploring the atlas literature. Loads the project's cached evidence and routes questions through Semantic Scholar snippet search. Writes any new traversal data to `traversal_output/_chat/` to avoid modifying existing cell type directories.

## Dependencies and Integrations

### Python Dependencies

| Package | Role |
|---|---|
| [pydantic-ai](https://ai.pydantic.dev/) | Graph orchestration (`pydantic_graph`) |
| [cellsem-llm-client](https://github.com/Cellular-Semantics/cellsem_llm_client) | LiteLLM agent wrapper |
| [deep-research-client](https://github.com/monarch-initiative/deep-research-client) | Semantic Scholar snippet search (`AstaProvider`) |
| pydantic, pyyaml, jsonschema, python-dotenv | Data validation, config, schema |

### External Services (via MCP)

| Service | Tools Used |
|---|---|
| [ARTL MCP](https://github.com/vrothenbergUSD/artl-mcp) (Europe PMC) | Full text, supplements, ID resolution, PDF-to-markdown |
| [Semantic Scholar](https://www.semanticscholar.org/) (Asta) | Snippet search, paper metadata, citation traversal |
| Playwright | Browser automation (available but not central to current workflow) |

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (if using Anthropic) | Anthropic API access |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API access |
| `ASTA_API_KEY` | Yes | Semantic Scholar API access (programmatic traversal) |

## Development

```bash
# Run tests
uv run pytest tests/unit -m unit
uv run pytest tests/integration -m integration

# Lint and type check
uv run ruff check .
uv run mypy .
```
