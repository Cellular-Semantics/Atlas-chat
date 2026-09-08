---
name: generate-cas
description: Generate a project's CAS+ config (projects/{project}/cas.json) from whatever source(s) are available — a bare list of cell-type labels, a spreadsheet/CSV, an AnnData h5ad/zarr obs, a CELLxGENE dataset, or a paper's supplementary table. Lifts any starting point up to the CAS+ contract so the rest of the workflow has one input shape. Deliberately lightweight; the schema is the spec.
---

# generate-cas

Produce `projects/{project}/cas.json` conforming to
`src/atlas_chat/atlas_chat/schemas/cas_annotation.schema.json`. That schema is the
contract and is **self-documenting** — read its field descriptions and follow them;
do not reproduce them here.

Invoked from workflow Step 1 when a project has no valid `cas.json` yet. CAS+
supersedes the legacy flat `cell_type_annotations.json`.

## Inputs

You are given a **project name** and one or more **sources**. Sources can be any of:
a bare list of cell-type labels, a CSV/XLSX table, an AnnData `.h5ad`/`.zarr` store
(read **obs only** — never the expression matrix), a CELLxGENE dataset, or a paper
supplementary table.

Some fields are not derivable from the data — **ask the user** rather than guess:
- the atlas **DOI** (and title, if not in the source),
- the **organism** (unless present as an obs/table column),
- **field roles** — which column(s) are the **cell-type label(s)**, which are coarser
  **hierarchy / granularity tiers** (→ ranked labelsets), which are **context
  covariates** (organism / developmental stage / tissue → `composition`), and which
  to ignore. Confirm the label column even when it looks obvious.

> A future obs-field classifier (in progress on `cxg-entrypoint-reader-discovery`)
> will propose these field roles automatically; until it lands, ask the user.

## Procedure (lightweight)

1. Identify the source(s) and **assay the available fields first** (`pandas`/
   `openpyxl` for tables; `anndata`/`zarr` for obs — obs only, never the matrix; a
   text list directly). For each column record its dtype (categorical vs
   continuous), cardinality, and a few example values. Mark as **auto-excluded** the
   **continuous / numeric** columns (QC metrics such as counts or percent-mito,
   embeddings, per-cell floats) and the **identifier-like / high-cardinality
   categoricals** (cell barcodes, per-cell IDs, index-like columns — distinct-value
   count approaching the cell count): these are not per-label categories and would
   massively bloat `cas.json`.
2. **Present that field inventory to the user** — the candidate columns with their
   dtype / cardinality / example values, and what was auto-excluded and why — and
   **ask them to assign roles**: cell-type label(s), hierarchy / granularity tiers,
   context covariates, or ignore; plus anything not derivable (DOI, organism).
   Listing the actual fields lets the user choose from what is really there; confirm
   the label column even when it looks obvious.
3. For each chosen categorical covariate, summarise per label — near-constant → a
   scalar; otherwise keep the distribution (`{author_value, share}`) — which maps
   onto CAS+ `composition`.
4. Map to CAS+ (let the schema descriptions guide the exact shape):
   - `source`: `{doi, title, ...}` (+ `organism`/`links` where known).
   - `labelsets`: one per cell-type column; set `rank` by granularity if known.
   - `annotations`: one per label, `cell_label` = the verbatim label, tied to its
     `labelset`. Carry hierarchy (`parent_cell_set_accession` / lineage), `synonyms`,
     `marker_gene_evidence`, `cell_ontology_term_id` **only if the source already
     provides them** — do not invent them (downstream steps resolve names, markers,
     and ontology terms). Fold CxG-style context (organism / developmental stage /
     tissue) into `composition` with ontology CURIEs where obvious; put remaining
     unmapped author columns in `author_annotation_fields`.
   - Leave optional fields **absent** when unknown — downstream consumers are
     presence-aware.
5. Write `projects/{project}/cas.json`, then **validate it explicitly**:

   ```bash
   uv run python -m atlas_chat.cli_cas validate --cas projects/{project}/cas.json
   ```

   Exit 0 is valid, 1 invalid; read the errors and rewrite until it passes. Run
   this whatever wrote the file — if you built the CAS+ with a script rather
   than by writing it directly, the check still applies and is the only thing
   that will catch a malformed document at the point it was made.

   Warnings name cross-field problems the schema cannot express (a dangling
   parent, counts that do not sum). They do not fail the run, because CAS+ is
   filled in across passes — but read them: on a document you have just
   finished, a warning is usually a real defect. Add `--strict` to fail on them.

   The `check_cas_annotation` PostToolUse hook runs the same checks as a
   backstop; it is not a substitute for the explicit call.

## Minimal case

A bare list of labels + a DOI is enough:

```json
{
  "title": "<atlas title>",
  "source": { "doi": "10.xxxx/..." },
  "labelsets": [ { "name": "author_cell_type" } ],
  "annotations": [ { "labelset": "author_cell_type", "cell_label": "<label>" }, ... ]
}
```

## Rules

- **obs only** — never download or read the expression matrix.
- **Do not invent** markers, synonyms, or ontology terms. Carry them only if the
  source states them; otherwise leave absent for downstream steps to fill.
- Prefer asking the user over guessing DOI / organism / which column is the label.
- Output is `projects/{project}/cas.json`; validate it with `cli_cas validate` (the hook is a backstop, not the primary check).
