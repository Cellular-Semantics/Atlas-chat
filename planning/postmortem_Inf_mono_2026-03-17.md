# Postmortem: Inf_mono Report Run (2026-03-17)

**Cell type**: Inf_mono (Inflammatory monocyte)
**Project**: fetal_skin_atlas
**Scope**: adult (from Reynolds et al. 2021 integrated annotations)
**Outcome**: Report generated, validation passed, 7 papers cited

---

## What Went Well

- **Name resolution was correct** despite the label never appearing in the paper text. The key insight — that `Inf_mono` originates from Reynolds et al. 2021 adult skin annotations integrated "with original annotations" — was found in the Gopee full text.
- **Snippet search was highly effective**. The Semantic Scholar ASTA MCP `snippet_search` tool returned high-quality, contextual evidence with exact quotes and CorpusIds for citing papers. This was the backbone of the evidence corpus.
- **CorpusId extraction from snippet metadata** was the correct solution. Gopee's CorpusId came from `paper.corpusId` in snippet results; Reynolds' came from `matchedPaperCorpusId` in a Gopee snippet's reference annotation (ref [10]). This was elegant but took too long to reach.
- **Final report quality is solid** — 7 papers, all quotes traceable, all references in catalogue.

---

## Problems Identified

### 1. Tool misuse: curl / WebFetch instead of MCP
**Occurrences**: Twice — once with `curl` against the S2 API, once with `WebFetch` against the same endpoint.
**Root cause**: The S2 MCP `get_paper` tool doesn't expose `corpusId` as a requestable field. When the agent hit this gap, it defaulted to raw HTTP instead of working within the MCP toolset.
**Impact**: ~2 wasted turns + user frustration.

### 2. Over-reliance on `get_europepmc_full_text` instead of supplements / snippets
**Occurrences**: Multiple attempts to fetch full text for both Gopee and Reynolds papers.
**Root cause**: Full text was fetched to search for `Inf_mono` mentions, but the label only exists in the dataset metadata, not the paper prose. For Reynolds, the full text API returned empty/errored silently 3 times.
**Impact**: ~3-4 wasted turns. User correctly flagged this.

### 3. Single-line JSON files broke grep workflows
**Problem**: Europe PMC MCP tools save results as single-line JSON. Initial `Grep` calls found nothing because the content was one enormous line. Agent fell back to `Bash` with `python3 -c` to extract + search.
**Impact**: ~2 wasted turns debugging the search approach.

### 4. CorpusId retrieval was a saga
**Problem**: Spent ~6 turns trying to get CorpusIds for Reynolds and Gopee. Tried: `get_paper` (doesn't return it), `search_paper_by_title` (doesn't return it), `search_papers_by_relevance` (doesn't return it), `get_paper_batch` (doesn't return it), `get_citations` (doesn't return it), then the forbidden `curl` and `WebFetch`.
**Root cause**: The S2 MCP tool schema doesn't include `corpusId` in the available fields list. The only way to get it is from `snippet_search` results (which include `paper.corpusId` and `matchedPaperCorpusId`).
**Impact**: This was the single biggest time sink — probably 30%+ of total run time.

### 5. No supplement data for the source atlas (Reynolds)
**Problem**: `get_pmc_supplemental_material("PMC7611557")` returned "No Supplementary Material is available." The cluster annotation tables that define `Inf_mono` are in the Reynolds supplementary data, but they weren't accessible via the PMC OA API.
**Impact**: Name resolution had to be done purely from literature inference rather than direct evidence. Confidence is high but the evidence chain is indirect.

### 6. Gopee supplements were peer review, not annotation tables
**Problem**: The 330K character supplement file for the Gopee paper was mostly the peer review file, not supplementary tables with cluster annotations.
**Impact**: Supplement scanning (Step 4a) yielded no direct `Inf_mono` marker data from the atlas paper itself.

---

## Suggestions for Improvement

### A. AGENT.md / Workflow Design

1. **Add a CorpusId retrieval pattern to AGENT.md**: Document that `snippet_search` is the canonical way to get CorpusIds via MCP. Something like:
   > To get a paper's CorpusId, use `snippet_search` with `paper_ids` parameter — the response includes `paper.corpusId`. For referenced papers, check `matchedPaperCorpusId` in snippet annotations.

2. **Add a "source atlas" resolution step**: When a cell type's scope indicates it comes from an integrated external dataset (e.g., adult annotations from Reynolds integrated into Gopee), the workflow should explicitly identify the source atlas early and pivot supplementary fetching to that paper.

3. **Handle supplement unavailability gracefully**: Add a fallback path in the workflow for when supplements aren't available via PMC OA. Options: try `get_europepmc_pdf_as_markdown` for the supplement PDF, or skip to snippet search with marker-focused queries.

4. **Use snippet search for name resolution** (not full text retrieval): The `snippet_search` tool should be the primary method for resolving cell type names. Search the seed paper (via `paper_ids`) with the annotation label and synonyms. This avoids the fragile full text download → grep → parse cycle entirely, and returns pre-chunked, relevance-ranked text with reference annotations built in.

5. **Use snippet search to discover supplementary material links**: Papers often reference their supplementary tables/figures in the main text (e.g., "see Supplementary Table 3 for cluster markers"). Snippet search with queries like `"supplementary table cluster annotation markers"` scoped to the atlas paper could identify which supplement files to target before fetching them. This is a candidate for future testing.

### B. Tool Usage Rules

6. **Never use curl/WebFetch for APIs that have MCP tools**: This should be an explicit rule in AGENT.md or CLAUDE.md. If an MCP tool has a gap (like missing `corpusId`), the correct response is to use a different MCP query pattern, not to bypass MCP.

7. **Pre-extract JSON before grepping MCP output files**: When MCP tools save large results to disk as JSON, always extract the text content with `python3 -c "import json..."` before searching. Add this as a known pattern.

8. **Prefer `snippet_search` over `get_europepmc_full_text` for evidence gathering**: The full text tool is fragile (silent failures, huge output). Snippet search returns pre-chunked, relevance-ranked text with built-in reference annotations. It should be the primary evidence-gathering tool for both name resolution and citation traversal.

### C. Efficiency

9. **Parallelize better**: Steps 3 (name resolution) and 4b (citation traverse) could overlap more. The snippet searches for markers and function could run while name resolution is still being confirmed.

10. **Limit supplement fetching attempts**: Set a max of 2 attempts for full text / supplement retrieval per paper. If both fail, move on to snippet search immediately.

11. **Batch paper lookups**: Use `get_paper_batch` early to pre-fetch metadata for all papers that will appear in the catalogue, rather than one-at-a-time lookups.

---

## Time Estimate Breakdown (approximate)

| Phase | Turns | Notes |
|-------|-------|-------|
| Config + setup | 2 | Clean |
| Supplement fetching | 6 | JSON extraction issues, silent API failures |
| Name resolution | 4 | Good, but interleaved with supplement debugging |
| CorpusId retrieval | 6 | Biggest bottleneck — tool gap |
| Citation traverse (snippets) | 3 | Efficient, best part of the run |
| Report synthesis + validation | 3 | Clean |
| **Wasted on tool misuse** | **~4** | curl, WebFetch, redundant full text attempts |

**Total**: ~24 turns. Could likely be **12-15** with the improvements above.

---

## Action Items

- [ ] Update AGENT.md with CorpusId retrieval pattern (suggestion 1)
- [ ] Update AGENT.md with source atlas resolution step (suggestion 2)
- [ ] Update AGENT.md with snippet_search as primary name resolution tool (suggestion 4)
- [ ] Add tool usage rules to AGENT.md or CLAUDE.md (suggestions 6-8)
- [ ] Test snippet_search for supplementary material discovery (suggestion 5) — future round
- [ ] Consider updating S2 MCP server to expose corpusId in `get_paper` responses
