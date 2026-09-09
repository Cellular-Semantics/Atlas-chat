# Atlas Reporter

**v0.1 — working alpha.**

> ⚠️ **Warning: this is a working alpha.** A beta release, **v1.0, is due by
> Monday 14 September 2026**. The beta is optimised for ease of use,
> efficiency, completeness and accuracy; it has an improved representation of
> atlas annotation and better support for collecting evidence and comparing
> against subatlases. Expect the v0.1 layout and interfaces to change.

## Overview

Cell types in online single-cell atlases are typically annotated with short and sometimes obscure names. Understanding what these names mean — and what is known about the cell types they describe — requires looking up the atlas paper and following its citations. While this scholarly workflow remains essential, it creates a significant barrier to efficient and effective browsing of online atlases.

Atlas Reporter automates the scholarly legwork: it reads the atlas paper and the papers it cites, and produces evidence-grounded reports about the cell types in an atlas.

## What It Does

**Starting point:** an *annotation representation* of an atlas — a spreadsheet
of cell type labels, or the annotation metadata from a cell-by-gene matrix —
plus the *atlas paper* that describes it.

**On request, Atlas Reporter:**

- **Generates cell type reports** — for a named cell type, it resolves how the
  atlas authors actually refer to it, mines the paper's supplementary material
  for markers and annotations, traverses the paper's references and searches
  the wider literature for supporting evidence, and synthesises a markdown
  report in which every claim is backed
  by an exact quote from a source paper.
- **Drafts Cell Ontology terms** — it maps the cell type to an existing Cell
  Ontology (CL) term where one fits, and where none does, drafts a new term
  request (definition, parent, axioms, synonyms, references) ready to post as a
  GitHub issue.

## Design Principles

- **Source transparency** — Every claim is backed by a direct quote from a source paper, so users can judge the evidence for themselves.
- **Literature navigation** — Quotes are linked to their source papers, enabling users to move quickly from a summary to the primary literature.
- **Complement, not replace** — Atlas Reporter lowers the barrier to efficient browsing; it does not substitute for careful scholarly reading of the original papers.

## Hallucination Detection

LLMs can fabricate quotes and identifiers. Atlas Reporter treats this as a first-class problem.

- Every blockquote in a generated report is verified against the original text before the report is saved. The validator checks that each quoted passage is a verbatim substring of a source paper (normalising whitespace, dashes, and smart quotes; handling ellipsis-separated segments).
- Every DOI and CorpusId reference is checked against the paper catalogue.
- If any check fails, the report is fed back to the LLM to fix, along with details of the error (up to two retries).

**What this guarantees:** quoted text in a final report actually appears in the cited source. DOIs are correct.

**What it does not guarantee:** that the surrounding narrative accurately interprets those quotes, or that the most relevant literature was found. Users should always follow quotes back to their source papers to assess context.

## Getting Started

### Prerequisites

- **Claude Code**, run from a clone of this repository.
- **An ASTA API key** — required for literature search and citation traversal.
  Request one from
  [allenai.org/asta/resources](https://allenai.org/asta/resources); it is free
  for academic researchers with proof of affiliation. Put it in a `.env` file
  in the repository root:

  ```
  ASTA_API_KEY=...
  ```

  This is the only key needed to generate reports. No Anthropic API key is
  required — Claude Code provides the model.

- **A GitHub token** *(optional)* — only needed to post new Cell Ontology term
  requests to the CL tracker. It must have permission to open issues on public
  repositories.

### Installation

```bash
git clone git@github.com:Cellular-Semantics/Atlas-reporter.git && cd Atlas-reporter
uv sync
```

### Setting up your atlas

1. **Branch.** Make a branch for your atlas — reports and evidence files are
   written into the repository.

   ```bash
   git checkout -b atlas/my-atlas-name
   ```

2. **Make a new directory under `projects/`.**

   ```bash
   mkdir -p projects/my_atlas_name/inputs
   ```

3. **Start Claude Code and give it your atlas.** Run `claude` in the repository
   directory — the MCP servers in `.mcp.json` load automatically — then tell it
   about your atlas. It needs two things:

   - **A publication describing the atlas** — a draft manuscript, a preprint,
     or a published paper.
   - **An annotation representation** — a spreadsheet, a CSV, or an annotated
     cell-by-gene matrix.

   Supply either as **local files placed under
   `projects/my_atlas_name/inputs/`**, as **links to the files**, or as a
   **DOI/PMID** for the publication.

4. **Agree the annotations file.** The agent generates
   `projects/my_atlas_name/cell_type_annotations.json` in discussion with you —
   confirming the atlas source and the cell type labels it has read out of your
   annotation representation (see [Project
   Configuration](#project-configuration) below).

5. **Request reports.** Once the annotations file is agreed, prompt for a
   report on a single cell type or on a set of cell types. Reports are
   generated from the atlas paper combined with citation traversal and free
   literature search, and are written to
   `projects/my_atlas_name/reports/{cell_type}.md`.

6. **Cell Ontology mapping and new terms.** Mapping to the Cell Ontology
   happens automatically as part of report generation. Cell types with no
   suitable existing CL term need a new term request; once you have reviewed
   the draft, it can be posted automatically to the CL tracker
   (`obophenotype/cell-ontology`), provided you have a GitHub token with
   permission to post to public repositories.

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
- If your annotation lives in an AnnData-zarr store, the `anndata-zarr-summary`
  skill can generate this file from the store's `obs/` metadata without
  downloading the expression matrix.

## How It Works

### Report Generation Pipeline

1. **FetchSupplements** — Resolve the atlas DOI to a PMCID via Europe PMC, fetch full text and supplementary file listings.
2. **ResolveName** — Identify the author-used terminology for the cell type in the atlas paper.
3. **ScanSupplements + CitationTraverse** *(parallel)* — Extract markers and findings from supplements, and combine citation traversal from the atlas paper with free literature search to build a paper catalogue with verified exact quotes.
4. **SynthesizeReport** — Generate a markdown report from all collected evidence.
5. **ValidateReport** — Check that every blockquoted passage is a substring of the evidence corpus and that all referenced papers exist in the catalogue. On failure, retry synthesis (up to 2 retries).
6. **SaveReport** — Write the final validated report to `projects/{project}/reports/{cell_type}.md`.
7. **Cell Ontology mapping and new term request** — Map the cell type to CL, record the mapping in the report header, and draft an NTR where no term fits.

The orchestrator follows `CLAUDE.md` and delegates to specialised subagents in `.claude/agents/`.

### Output Structure

```
projects/{project}/
├── inputs/                              # Your atlas publication and annotation files
├── cell_type_annotations.json           # Project configuration (agreed with the agent)
├── traversal_output/{cell_type}/
│   ├── atlas_full_text.txt              # Fetched atlas paper text
│   ├── name_resolution.json             # Resolved cell type names
│   ├── supplementary_findings.json      # Extracted markers and findings
│   ├── raw_snippets.json                # Raw citation snippets
│   ├── all_summaries.json               # Processed summaries with verified quotes
│   ├── paper_catalogue.json             # Metadata for all discovered papers
│   ├── cl_mapping.json                  # Cell Ontology mapping
│   └── cl_term_request.json             # Draft new term request (if needed)
└── reports/
    └── {cell_type}.md                   # Final validated report
```

### Validation

Reports are validated before saving:

- **Quote checking** — Every `> "..."` blockquote must be a substring of the evidence corpus (with normalisation for whitespace, dashes, smart quotes, and ellipsis segments).
- **Reference checking** — Every DOI or CorpusId in the report must exist in the paper catalogue.

If validation fails, the synthesis step is retried with specific error feedback (up to 2 retries).

## Dependencies and Integrations

### External Services (via MCP)

| Service | Tools Used |
|---|---|
| [ARTL MCP](https://github.com/vrothenbergUSD/artl-mcp) (Europe PMC) | Full text, supplements, ID resolution, PDF-to-markdown |
| [Semantic Scholar](https://www.semanticscholar.org/) (Asta) | Snippet search, paper metadata, citation traversal |
| [OLS4](https://www.ebi.ac.uk/ols4/) | Cell Ontology term lookup |
| Playwright | Browser automation (available but not central to current workflow) |

### Python Utilities

The Python package (`src/atlas_chat/`) provides supporting utilities used by the workflow:

| Module | Role |
|---|---|
| `services/local_snippet_index.py` | Local vector index for preprints not yet in ASTA |
| `services/fetch_preprint.py` | JATS XML fetch for bioRxiv preprints |
| `validation/report_checker.py` | Shared quote and reference validation logic |
| `schemas/*.schema.json` | JSON schemas — source of truth for all output shapes |

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `ASTA_API_KEY` | Yes | Literature search and citation traversal via Asta / Semantic Scholar. Free for academic researchers — request at [allenai.org/asta/resources](https://allenai.org/asta/resources). |
| `ATLAS_CHAT_GH_TOKEN` | No | Posting new Cell Ontology term requests to `obophenotype/cell-ontology`. Needs permission to open issues on public repositories. |

## Development

This project uses Claude Code for agentic development. Load [`CLAUDE_dev.md`](CLAUDE_dev.md) as context when working on the codebase:

```
/load CLAUDE_dev.md
```

It covers schema-first design, testing conventions, and the curation-mode write guard.

```bash
# Run tests
uv run pytest -m unit
uv run pytest -m integration   # requires API keys; skipped in CI

# Lint and type check
uv run ruff check src/ tests/
uv run mypy src/
```
