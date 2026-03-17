---
name: citation-traverse
description: Given seed paper IDs and a query, trace citation chains via ASTA snippet search. Searches within seed papers, extracts referenced paper IDs, then searches within those — repeating to a configurable depth. Summarizes each snippet individually as it is returned. Does NOT discover seeds — use find-seeds or provide IDs directly.
---

# Citation Traversal

You trace citation chains through scientific literature. You are given seed papers and a query — you search within those papers, extract the papers they reference, then search within those referenced papers. You repeat to a configurable depth.

**You summarize each snippet independently as it is returned.** You do NOT synthesize across snippets — that happens downstream.

You do NOT search for seed papers. Seeds are provided to you.

## Input

`$ARGUMENTS` contains:
- A research query (free text)
- `--seeds` followed by comma-separated paper IDs (CorpusId:NNN, DOI:..., PMID:NNN, or PMCID:NNN format)
- `--depth N` (optional, default 1, max 3)
- `--output-dir path` (optional, default `traversal_output/`)

If no `--seeds` are provided, check if there is a `seeds.json` file in the output dir and use those.

## Per-snippet processing

For EVERY snippet returned by snippet_search, immediately produce a structured summary BEFORE looking at the next snippet. This is extraction, not synthesis — treat each snippet in isolation.

For each snippet, produce:

```json
{
  "source_corpus_id": "2762329",
  "source_title": "Salivary Glands",
  "section": "Mucous cells",
  "snippet_score": 0.57,
  "summary": "1-3 sentence summary of content relevant to the query. Ignore irrelevant content.",
  "quotes": [
    "exact quote from snippet supporting a specific claim",
    "another exact quote if relevant"
  ],
  "ref_corpus_ids": ["22612890", "46562341"],
  "depth": 0
}
```

Rules for per-snippet summaries:
- **Summarize only what is relevant to the query.** Skip boilerplate.
- **Quotes must be exact substrings of the snippet text.** Do not paraphrase.
- **Keep 1-3 quotes per snippet.** Pick the most informative.
- **Each summary is independent.** Do not reference other snippets.

## Procedure

### Depth 0: Search within seed papers

1. Call `snippet_search(query="<query>", paper_ids="<seed_ids>", limit=20)`
   - If more than 50 seed IDs, split into parallel calls.
2. **Process each snippet** — produce a per-snippet summary (see above).
3. Extract referenced CorpusIds directly from the ASTA snippet results:
   - Look for `corpusId` fields in the snippet_search response metadata
   - Scan snippet text for CorpusId patterns
   - Collect all unique corpus IDs referenced by the snippets
4. Save to disk:
   - `{output_dir}/depth_0_snippets.json` — raw snippet_search response (provenance)
   - `{output_dir}/depth_0_summaries.json` — array of per-snippet summaries

### Depth 1..N: Follow references

5. Take `unique_corpus_ids` from previous depth's refs.
6. Remove already-visited IDs (maintain visited set across all depths).
7. If fewer than 3 new IDs, stop — diminishing returns.
8. Call `snippet_search(query="<query>", paper_ids="CorpusId:<new_ids>", limit=20)`
   - If more than 50 IDs, split into parallel calls.
9. **Process each snippet** — same per-snippet summary as above, with `depth` set accordingly.
10. Extract CorpusIds from snippet results, save all files to disk.
11. Repeat until depth limit or no new IDs.

### Final: Resolve metadata

12. Collect ALL unique corpus IDs from all depths (seeds + discovered).
13. Call `get_paper_batch(ids=[...], fields="title,authors,year,venue,publicationDate,url,isOpenAccess,doi")`
14. Save to `{output_dir}/paper_catalogue.json`

## Output

Save a combined summaries file — `{output_dir}/all_summaries.json` — merging summaries from all depths.

Print a traversal summary:

```
TRAVERSAL COMPLETE
==================
Query: <query>
Seeds: N papers
Depth reached: M

Per depth:
  Depth 0: X snippets, Y summaries, Z refs (K new)
  Depth 1: X snippets, Y summaries, Z refs (K new)

Total unique papers discovered: N
Total summaries with quotes: M

Files written:
  {output_dir}/depth_0_snippets.json
  {output_dir}/depth_0_summaries.json
  {output_dir}/depth_0_refs.json
  ...
  {output_dir}/all_summaries.json
  {output_dir}/paper_catalogue.json
```

## Rules

- **Summarize each snippet as it is returned.** Do not batch or synthesize.
- **Never search for seeds.** Only traverse from what you're given.
- **Maintain a visited set.** Never search the same corpus ID twice.
- **Write files incrementally.** Each depth's results are saved before proceeding to the next.
- **Raw snippets stay on disk.** They are saved for provenance but not passed to synthesis.
- Only the per-snippet summaries and quotes flow upward to the synthesis stage.
- If snippet_search returns empty for some papers, note them but continue.
