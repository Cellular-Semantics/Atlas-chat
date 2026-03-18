---
name: load-project-context
description: Load and index all available evidence for an atlas-chat project. Reads cell_type_annotations.json, resolves the atlas CorpusId, scans existing traversal output, and builds a merged session-level paper catalogue.
---

Load the project context for atlas-chat chat mode.

## Usage

`/load-project-context {project}`

Where `{project}` is the name of a directory under `projects/`
(e.g. `fetal_skin_atlas`).

## Steps

### 1. Load project config

Read `projects/{project}/cell_type_annotations.json`.

Extract:
- Atlas DOI and title
- All cell type labels (for reporting coverage)

If the file does not exist, stop and tell the user the project was not found.
List available directories under `projects/` to help them correct it.

### 2. Resolve atlas CorpusId

Call:

```
snippet_search(
    query="{atlas title}",
    paper_ids="DOI:{atlas_doi}",
    limit=1
)
```

Extract `paper.corpusId` from the first result's metadata. This is the
**session atlas CorpusId** — retain it for the duration of the session.

If `snippet_search` returns no results, try:

```
search_paper_by_title(title="{atlas title}", limit=1)
```

and use the returned `paperId` as CorpusId.

### 3. Scan traversal output

List all subdirectories of `projects/{project}/traversal_output/`.

For each subdirectory that contains a `paper_catalogue.json`:
- Read the file (use `python3 -c "import json; ..."` to parse it if large)
- Collect all entries into a running merged catalogue, deduplicated by `corpusId`

Keep track of which cell types have traversal output.

### 4. Report summary

Output a concise summary:

```
Project loaded: {atlas title}
DOI: {atlas_doi}
CorpusId: {atlas_corpus_id}

Cell types: {total in annotations.json} defined, {N} with traversal output
Papers in merged catalogue: {unique count}

Cell types with cached evidence:
  - Iron-recycling macrophage
  - ...
```

### 5. Retain session state

Keep the following in working context for the rest of the session:
- Atlas DOI, title, CorpusId
- Project name and path
- Merged paper catalogue (all entries, deduplicated)
- List of cell types with traversal output

This state is used by CHAT.md question routing to avoid redundant MCP calls.
