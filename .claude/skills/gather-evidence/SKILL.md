---
name: gather-evidence
description: Gather quote-grounded literature evidence for one cell type from its seed papers (atlas + contributing subatlases) and their citations. Routes every paper JATS-first (whole-text read by a pinned-model subagent) with ASTA snippets as the fallback, follows citations up to the depth cap, and emits provenance-tagged evidence summaries.
input:
  schema: src/atlas_chat/atlas_chat/schemas/gather_evidence_input.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/all_summaries.schema.json
---

# Skill: Gather Evidence

Produce `all_summaries.json` + `paper_catalogue.json` for one cell type: evidence
items with verbatim quotes, each tagged with its source paper, role, retrieval
method, and (for followed citations) the citing sentence it was reached from.

Two access routes, decided **per paper** by `cli_annotate route`:

- **JATS** (preferred): the whole narrative text is read in one pass by a reader
  subagent. Fuller text than ASTA (introductions, captions), and quotes validate
  against the exact text stored in the job file.
- **ASTA** (fallback): the existing snippet procedure. Coarser, lossier — the
  catalogue records `"route": "asta_snippet_bound"` so the synthesizer can caveat.

Never call ASTA `snippet_search` MCP tools directly and never open raw JATS XML
in your context — all retrieval goes through the CLI.

## Inputs

Per `gather_evidence_input.schema.json`. Paths are given to you; do not derive
them from a project name. `reader_model` defaults to `opus` — **pass it
explicitly on every reader dispatch** (never rely on model inheritance) and
record it per job in `<output_dir>/reader_provenance.json`.

Read `decomposition_path` first: `subject`, `aliases`, `scope`, and the five
`aspects` define what the readers are asked and what counts as relevant.

## Procedure

Maintain `<output_dir>/traversed.json` (the CLI writes it) and a running count
against `run_cap`. Process seeds in priority order — search **every** seed you
were given; dropping a lower-priority seed because an earlier one returned
plenty loses the integration context.

### Per paper (seed or followed citation)

1. **Route**:
   `python -m atlas_chat.cli_annotate route --paper <id> --project-dir <project_dir>`

2. **JATS route** →
   `python -m atlas_chat.cli_annotate read --paper <id> --project-dir <project_dir> --out <output_dir>/papers/paper_<n>.json --traversed <output_dir>/traversed.json --query "<combined_query>"`

   Then dispatch **one reader subagent** for the paper (model: `reader_model`),
   with the contract in `READER_PROMPT.md` (same directory as this skill). The
   reader gets the job-file path and answers **all five aspects in a single
   read** — the context is identical per aspect, so serial per-aspect dispatch
   buys nothing. It returns, as JSON:
   - per-aspect: `found`, `answer`, `quotes` (verbatim substrings of the job
     file's `narrative_text` or `legends`)
   - `propose_follow`: the `ref_id`s of citations worth following — only where
     the citing sentence bears on the subject, drawn from `cited_sentences`.

   Convert each found aspect answer into evidence_summary items:
   `retrieval_method: "full_text"`, `source_paper` = this paper (+role),
   `summary` = the reader's answer, `quotes` = its quotes. Followed papers also
   carry `reached_from` (`doi`/`corpus_id`, `hop`, `citation_context`).
   If the job file has `"truncated": true`, note it on the catalogue entry.

3. **ASTA route** → the snippet procedure (unchanged from the citation-traverse
   subagent): `cli_annotate fetch` scoped to the paper with `combined_query`,
   gate sentences on `annotated_text`, summarize relevant snippets
   (`retrieval_method: "corpus_snippet"` for seeds, `"citation_traversal"` for
   followed papers), propose follow candidates from `[CorpusId:NNNN]` tokens and
   validate them with `cli_annotate follow-set --probe-bands`.

4. **Unreachable route** → record the paper in `<output_dir>/gaps.json` with the
   route's `reason` and, for followed citations, the citing sentence that wanted
   it. A gap is a retrieval limit, not a judgement of irrelevance — never drop it
   silently.

### Citation hops (depth ≥ 1)

For a JATS paper, validate the reader's proposals:

```
python -m atlas_chat.cli_annotate follow-check \
  --paper-json <output_dir>/papers/paper_<n>.json \
  --proposed <ref_id> [--proposed ...] \
  --traversed <output_dir>/traversed.json \
  --out <output_dir>/follow_hop<n>.json
```

Follow only the returned `follow` list (the reference list is closed — a
rejected proposal was never in it), capped at `k_per_paper` per paper and
`run_cap` overall. Each followed paper goes through **Per paper** above at
hop+1, stopping at `depth`. Prefer follows whose citing sentences sit in
Introduction/Results — that is where defining citations live.

### Finish

- Merge every paper's evidence items into `<output_dir>/all_summaries.json`
  (array conforming to `all_summaries.schema.json`; the PostToolUse hook
  validates it).
- Build `<output_dir>/paper_catalogue.json` keyed by `CorpusId:NNNN` or
  `DOI:...`: title/authors/year/venue/doi (via the `get_paper_batch` MCP tool
  for ASTA-known papers; from the job file's `ref_lookup`/route metadata
  otherwise). On each entry record `route`: `"jats_full_text"` or
  `"asta_snippet_bound"`, plus `asta_indexing` band where probed. Every
  `source_paper` / `reached_from` id you emitted must appear here.
- Write `<output_dir>/reader_provenance.json`: job file → model used.

## Rules

- Quotes are exact substrings of the text the reader was shown; never splice.
- Every evidence item carries `source_paper` (+`role`) and `retrieval_method`;
  followed items also carry `reached_from` with the citing sentence.
- Never follow an id the CLI did not return in `follow`/`follow_set`.
- Never revisit a paper in `traversed.json`; never search a seed you weren't given.
- An empty result for a seed is a finding — say so in your summary; do not pad.
