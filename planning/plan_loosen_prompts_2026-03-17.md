# Plan: Loosen Shared Prompts + Align Report Format + Agentic Procedural Fixes

## Context

Two sets of improvements needed, targeting different layers:

**A. Content & format** (shared prompts → affects both runtimes): The programmatic graph produces minimal reports while the example in `scratch/iron_recycling_macrophages_report.md` shows the target quality: narrative synthesis, `(Author et al., Year)` citations, standard references, rich content.

**B. Agentic procedural** (AGENT.md + agent markdown → affects agentic only): The `planning/postmortem_Inf_mono_2026-03-17.md` documents tool misuse (curl instead of MCP), CorpusId retrieval saga, over-reliance on full text, and supplement fetching failures.

These are orthogonal and layer cleanly:
- **Shared `.prompt.yaml`** → content/format quality → both runtimes
- **Agent `.md` files + `AGENT.md`** → procedural patterns → agentic only
- **Validation `report_checker.py`** → DOI-based ref checking → both runtimes

## Part A: Content & Format (shared prompts)

### 1. `src/atlas_chat/agents/report_synthesizer.prompt.yaml`

**system_prompt** — loosen:
- Remove rigid markdown template
- Standard academic citation: `(Author et al., Year)` inline
- Standard references: `Author et al. (Year). "Title". *Journal*. DOI:xxx`
- Keep: quotes must be exact substrings, don't fabricate
- Add: encourage narrative context around quotes, subsections, multiple sources

**user_prompt** — keep evidence injection, but:
- Replace rigid template with section guidelines + one example showing style
- Describe citation/reference format by example, not template

### 2. Validation: `src/atlas_chat/validation/report_checker.py`

- `check_references`: switch from CorpusId to DOI-based
  - Extract DOIs from report (`10.\d{4,}/\S+`)
  - Check against catalogue DOI values
- `check_quotes`: no change (already checks `> "..."` against evidence)

### 3. `AGENT.md` — Report Format section

- Update example to use `(Author et al., Year)` citations
- Standard references format
- DOI links instead of CorpusId inline

### 4. `.claude/agents/synthesize-report.md`

- Remove duplicate format template (defer to shared YAML prompt)
- Update Critical Rules for DOI-based citation format

## Part B: Agentic Procedural Fixes (from postmortem)

### 5. `AGENT.md` — Workflow improvements

From postmortem suggestions:
- **(1) CorpusId retrieval pattern**: Document that `snippet_search` is the canonical way to get CorpusIds. Response includes `paper.corpusId` and `matchedPaperCorpusId`.
- **(2) Source atlas resolution**: When scope indicates integrated external annotations, explicitly identify and pivot to the source atlas.
- **(4) Snippet search for name resolution**: Primary tool for resolving names — not full text retrieval. Search seed paper via `paper_ids` param.
- **(6) Never curl/WebFetch for MCP-covered APIs**: Explicit rule.
- **(8) Prefer snippet_search over full text**: Primary evidence-gathering tool.
- **(10) Limit supplement fetch attempts**: Max 2, then move on.
- **(11) Batch paper lookups**: Use `get_paper_batch` early.

### 6. `.claude/agents/resolve-name.md`

Add: use `snippet_search` with `paper_ids` to search atlas paper, not full text retrieval.

### 7. `.claude/agents/citation-traverse.md`

Add: CorpusId comes from snippet metadata, not `get_paper` fields. Document the pattern.

## Files to Modify

| File | Change | Layer |
|------|--------|-------|
| `src/.../agents/report_synthesizer.prompt.yaml` | Loosen format, standard citations | Shared |
| `src/.../validation/report_checker.py` | DOI-based ref validation | Shared |
| `AGENT.md` | Report format + procedural workflow fixes | Agentic |
| `.claude/agents/synthesize-report.md` | Remove dup template, DOI citations | Agentic |
| `.claude/agents/resolve-name.md` | snippet_search for name resolution | Agentic |
| `.claude/agents/citation-traverse.md` | CorpusId retrieval pattern | Agentic |

## Verification

1. `--dry-run` shows updated prompts
2. Full run: `uv run python scripts/generate_report.py --project fetal_skin_atlas --cell-type "Iron-recycling macrophage" --provider openai -v`
3. Output should resemble `scratch/iron_recycling_macrophages_report.md`:
   - Multiple references (>3 papers), narrative around quotes
   - `(Author et al., Year)` inline, standard references with DOI
4. Validation catches fabricated quotes and unknown DOIs
