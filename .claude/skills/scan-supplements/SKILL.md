---
name: scan-supplements
description: Extract markers and annotations about a cell type from a corpus paper's supplementary material via the supplement store — manifest-directed, store-CLI-only access, provenance on every finding. Runs for the atlas paper and for any contributing subatlas paper whose store exists.
input:
  schema: src/atlas_chat/atlas_chat/schemas/supplement_manifest.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/supplementary_findings.schema.json
---

# Skill: Scan Supplements

Supplements carry the evidence body text cannot: DEG tables, cluster-to-name
mappings, marker lists. This skill extracts what a store's manifest points at for
one cell type — from the **store on disk**, never by fetching mid-run.

Supersedes the `scan-supplements` subagent's fetch-into-context procedure. The
store is built once per paper at setup (`index-supplements` skill /
`cli_supplements fetch`); if a paper has no store, that is a setup gap to report,
not something to work around with MCP fetching here.

## Inputs

- `cell_type_label` + `resolved_names` (+ aliases from `query_decomposition.json`)
- `source_paper` — the paper whose store to scan:
  `{ "doi": "...", "corpus_id": "...", "role": "atlas" | "subatlas" }`.
  Run this skill once per corpus paper with a store — the atlas, and each
  contributing subatlas the seeds name.
- `store` — store root (e.g. `projects/{project}/supplements`); always an
  explicit argument, never derived.
- Output path for `supplementary_findings.json`.

## Procedure

**Everything that touches bytes goes through the store CLI** — a supplementary
table can run to hundreds of thousands of rows; `Read` on one wrecks your
context for no gain.

1. `python -m atlas_chat.cli_supplements show --store <store> --doi <doi>` —
   the manifest: which file/sheet/page holds what (`content_type`:
   `deg_results`, `cluster_annotation`, `marker_list`, `cell_metadata`, …).
2. Pick the entries that could describe this cell type: DEG tables, cluster
   annotation tables, marker lists — plus anything whose description names the
   cell type or a resolved name.
3. For each, `outline` (columns/sheets), then `slice`/`text` narrowly — filter
   to rows matching the label or resolved names rather than pulling whole
   sheets.
4. Extract markers (with evidence type and, for DEG tables, the ranking column
   you used — say which; "top markers" is ambiguous across `scores` vs
   `logfoldchanges`), other findings, and exact quotes.
5. Every finding carries `source_paper` (copied from input — never assume the
   atlas), `retrieval_method: "supplement"`, and a `supplement_ref` locator
   `{ "file": "...", "sheet": "...", "table": "..." }`.

## Output

`supplementary_findings.json` conforming to
`supplementary_findings.schema.json` (PostToolUse-hook validated):
`markers[]`, `other_findings[]`, `evidence_quotes[]`, each with the provenance
trio above.

## Rules

- Quotes must be exact substrings of the sliced/extracted text.
- Do not hallucinate markers — only what the table or text explicitly states.
- Gene lists come from the table itself, with the sheet/block recorded — merged
  column blocks with unequal lengths are common; never read across blocks.
- If the store lacks this paper (or has no manifest), write an empty findings
  file and report the gap — "no store" must stay distinguishable from "nothing
  in the supplements".
- `source_paper` must resolve to an entry in `paper_catalogue.json`.
