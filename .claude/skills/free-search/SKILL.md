---
name: free-search
description: Last-resort escalation for aspects the corpus and its citations could not cover — an unscoped ASTA search per thin/absent aspect, evidence tagged free_search, with an honest absent_after_free_search verdict when even that returns nothing.
input:
  schema: src/atlas_chat/atlas_chat/schemas/coverage.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/all_summaries.schema.json
---

# Skill: Free Search

Invoked **only** for aspects `coverage.json` marks `thin` or `absent` after
gather-evidence has run. Free search is the bottom of the escalation ladder:
corpus papers → their citations → the open literature. Its evidence is tagged so
a reader can see it did not come from the atlas's own citation neighbourhood —
a report built mostly from free search is a signal that name resolution or
seeding failed, and the validator warns on it.

## Inputs

- `coverage.json` — which aspects to escalate
- `query_decomposition.json` — the per-aspect queries, `aliases`, and `scope`
- `all_summaries.json` + `paper_catalogue.json` — to append to
- `reader_model` (default `opus`) — pinned on any reader dispatch

## Procedure

Per thin/absent aspect:

1. Build the query: the aspect's `aspects[].query` in **keyword form** plus the
   `scope` terms (keyword queries measurably beat claim-form queries on
   multi-paper search spaces; scope terms keep results in context). Include an
   alias when the primary name is rare in the literature.

2. Search, unscoped — no `--paper-ids`:

   ```
   python -m atlas_chat.cli_annotate fetch \
     --query "<keyword aspect query + scope terms>" --limit 20 \
     --role external --retrieval-method free_search --hop 0 \
     --out <output_dir>/free_search_<aspect>.json
   ```

3. Gate the returned records for actual relevance to the subject **and** scope —
   free search over the whole literature returns plausible-looking noise;
   sibling cell types and other species are the common traps. Keep only records
   whose text genuinely bears on this cell type in (or informatively near) this
   scope.

4. Summarize keepers into evidence items exactly as gather-evidence does
   (`retrieval_method: "free_search"`, quotes verbatim from record `text`),
   append them to `all_summaries.json`, and add their papers to
   `paper_catalogue.json` (via `get_paper_batch`).

5. Update `coverage.json`: an aspect that gained in-scope evidence moves to
   `covered`/`thin` accordingly; an aspect that gained nothing becomes
   **`absent_after_free_search`** — that verdict is what obliges the report
   section to read "No evidence found in traversed literature." Do not launder
   an empty result into a weaker status.

## Rules

- One search per aspect, plus at most one refined retry if the first query was
  obviously mis-phrased. Stop gracefully; effort is capped.
- Off-scope evidence found here may be kept only with its context recorded —
  it does not upgrade coverage status.
- Never quote from your own knowledge to fill a gap; the gap is the finding.
