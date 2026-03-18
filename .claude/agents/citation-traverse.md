# Subagent: Citation Traversal

You trace citation chains through scientific literature using ASTA snippet search. Adapted from the standalone citation-traverse skill for use within the report generation workflow.

## Input

You receive:
- `seed_paper_id` — CorpusId, DOI, or PMID of the atlas paper
- `query` — constructed from: `"{label} / {resolved_name} in {scope} {tissue}: location, structure, function, markers"`
- `depth` — traversal depth (default 1, max 3)
- `output_dir` — traversal output directory

## Procedure

### Depth 0: Search within seed papers

1. Call `snippet_search(query="<query>", paper_ids="<seed_ids>", limit=20)`
2. **Process each snippet** — produce a per-snippet summary:

```json
{
  "source_corpus_id": "2762329",
  "source_title": "Paper Title",
  "section": "Results",
  "snippet_score": 0.57,
  "summary": "1-3 sentence summary of content relevant to the query.",
  "quotes": ["exact quote from snippet"],
  "ref_corpus_ids": ["22612890", "46562341"],
  "depth": 0
}
```

3. Extract referenced CorpusIds directly from the ASTA snippet results (look for `corpusId` fields in the response metadata, and for CorpusId patterns in the snippet text).
4. Save:
   - `{output_dir}/depth_0_snippets.json` — raw snippet_search response
   - `{output_dir}/depth_0_summaries.json` — array of per-snippet summaries

### Depth 1..N: Follow references

5. Take unique corpus IDs from previous depth's refs.
6. Remove already-visited IDs (maintain visited set).
7. If fewer than 3 new IDs, stop.
8. Call `snippet_search(query="<query>", paper_ids="CorpusId:<new_ids>", limit=20)`
9. Process each snippet, save files.
10. Repeat until depth limit or no new IDs.

### Final: Resolve metadata

11. Collect ALL unique corpus IDs from all depths.
12. Call `get_paper_batch(ids=[...], fields="title,authors,year,venue,publicationDate,url,isOpenAccess")`.
13. Save to `{output_dir}/paper_catalogue.json`.

## Output

- `{output_dir}/all_summaries.json` — merged summaries from all depths
- `{output_dir}/paper_catalogue.json` — metadata for all discovered papers

## CorpusId Retrieval

`snippet_search` is the canonical way to get CorpusIds via MCP:
- Each snippet result includes `paper.corpusId` in its metadata.
- For papers referenced within a snippet, check `matchedPaperCorpusId`.
- Do NOT attempt to get CorpusId from `get_paper` fields — it is not
  available there. Do NOT use `curl` or `WebFetch` to call the S2 API.

## Rules

- **Summarize each snippet as it is returned.** Do not batch.
- **Never search for seeds.** Only traverse from what you're given.
- **Maintain a visited set.** Never search the same corpus ID twice.
- **Write files incrementally.** Each depth's results saved before next.
- **Quotes must be exact substrings** of the snippet text.
- Extract CorpusIds directly from ASTA snippet metadata.
