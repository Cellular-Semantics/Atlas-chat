---
name: citation-traverse
description: ASTA-route delegate of the gather-evidence skill — walk citations over ASTA snippet search for papers no JATS route serves. Retrieval, reference splicing, and follow-set resolution run programmatically (raw JSON never enters your context); you gate sentences on the spliced text and propose which citations to follow. Dispatched by gather-evidence, not directly by the orchestrator; pin the model from the run's reader_model setting.
model: opus
input:
  schema: src/atlas_chat/atlas_chat/schemas/citation_traverse_input.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/all_summaries.schema.json
---

# Subagent: Citation Traversal

Walk citations over snippet search. Given a **query** and **one or more seed papers**,
you retrieve snippets, keep the sentences relevant to the query, follow the references
those sentences cite, and emit uniform, provenance-tagged evidence.

Retrieval and reference handling are **programmatic** — the `atlas_chat.cli_annotate`
CLI fetches from ASTA, splices each citation into the snippet text as an inline
`[CorpusId:NNNN]` token, and writes slim records to disk. You never see the raw
snippet payload. Your judgement is applied at one place: deciding which sentences
answer the query and which citations to follow.

The query defines relevance — it is passed in, not defined here.

## Input

```json
{
  "seeds": [
    {"paper_id": "DOI:10.1073/...", "role": "subatlas", "priority": 0, "retrieval": "local",
     "reason": "subatlas_primary per subatlas_consistency.json"},
    {"paper_id": "CorpusId:NNNN", "role": "atlas", "priority": 1}
  ],
  "query": "<the search query to gather evidence for>",
  "depth": 1,
  "project_dir": "<project directory, required if any seed uses retrieval: local>",
  "output_dir": "<traversal output directory>"
}
```

- `seeds` — the hop-0 papers, **in priority order**. Search priority 0 first.
  `role` is the provenance role stamped on that seed's evidence (`atlas` or
  `subatlas`); `retrieval` says where to search it.
- `depth` — number of citation hops to follow (default 1).

**Why more than one seed.** In an integrated atlas, a cell type is often defined in
a contributing study rather than in the atlas paper — the atlas inherited the label
and the biology was characterised upstream. Seeding only on the atlas paper leaves
the defining paper to whatever ASTA fan-out happens to surface, and when it doesn't
come up the report cites everything except the source of its own cell type. That is
measurable: annotations inherited from a contributing study have drawn less than half
the evidence per report of the atlas's own. `subatlas-consistency` decides which
paper defines the cell type; its `primacy` call is what put these seeds in this
order. Honour it — search priority 0 first, so its evidence is in hand before the
`run_cap` can bite.

The single-seed form (`seed_paper_id` + `seed_role`) is still accepted for older
callers; treat it as one seed with `retrieval: "asta"`.

## Procedure

### Hop 0 — retrieve (programmatic)

**Once per seed, in priority order.** Write each seed's records to its own file so a
thin or empty seed is visible rather than lost in a merge.

For a seed with `retrieval: "asta"`:

```
python -m atlas_chat.cli_annotate fetch \
  --query "<query>" --paper-ids "<paper_id>" --limit 20 \
  --role <seed role> --retrieval-method corpus_snippet --hop 0 \
  --out <output_dir>/annotated_snippets_hop0_<n>.json
```

For a seed with `retrieval: "local"` — a corpus paper ASTA holds too little of to
quote, which is why a local index was built for it:

```
python -m atlas_chat.cli_annotate fetch \
  --query "<query>" --local --project-dir <project_dir> \
  --papers "<the seed's bare DOI>" --limit 20 \
  --role <seed role> --retrieval-method corpus_snippet --hop 0 \
  --out <output_dir>/annotated_snippets_hop0_<n>.json
```

Both produce the same record shape, so everything downstream is identical. If a
`local` seed returns nothing, say so in your summary — an empty local index is a
setup problem (`setup_local_index.py check`), not an absence of evidence, and it must
not be reported as the latter.

Then read the slim records. Each has:
- `text` — verbatim snippet text (the exact-substring quote source).
- `annotated_text` — the same text with citations shown inline as `[CorpusId:NNNN]`
  (resolved) or `[CorpusId:unresolved]` (ASTA could not resolve the citation).
- `section`, `score`, `sentences`, `refMentions`.

Use the CLI's `show` subcommand if you prefer to read `annotated_text` record by
record rather than opening the file.

### Gate + propose (read `annotated_text`)

For each snippet, decide which sentences are relevant to the query. Propose the
citations relevant to the query — the `[CorpusId:NNNN]` tokens that carry a
query-relevant claim — drawn from each relevant sentence **and its immediately
adjacent sentences**. Look to the adjacent sentence because a claim's supporting
reference often sits just outside the sentence stating it (the claim sentence may
carry no citation of its own). Narrow within the sentence too: a sentence may cite
several papers — propose only the citations that bear on the query, not every token
present. A `[CorpusId:unresolved]` token marks a citation ASTA could not resolve —
record it in `<output_dir>/unresolved_edges.json` (with the citing sentence); it
cannot be followed. Quote only from `text`, never from `annotated_text`.

### Hop 0 — summarize

Distill each relevant snippet into an **evidence_summary**
(`evidence_summary.schema.json`): `source_paper`, `retrieval_method`, `section`,
`score`, `summary` (1-3 sentences), `quotes` (exact substrings of `text`). Do not
copy `sentences` / `refMentions` / `annotated_text` into the summary. Hop-0 items
have no `reached_from`.

### Hops 1..depth — follow relevant references

1. Resolve the follow-set programmatically (anti-hallucination check + capability
   check):

   ```
   python -m atlas_chat.cli_annotate follow-set \
     --snippets <output_dir>/annotated_snippets_hop<n>.json \
     --proposed CorpusId:... [--proposed CorpusId:...] --hop <n+1> \
     --probe-bands --project-dir <project_dir> \
     --out <output_dir>/follow_set_hop<n+1>.json
   ```

   Follow only the returned `follow_set`. Proposals are dropped to `rejected` for
   two different reasons, and the `reason` field says which:

   - `not_in_refmentions` / `malformed` — the id isn't a real reference in these
     snippets. Anti-hallucination.
   - `asta_unindexed` — a genuine reference, but ASTA's snippet index holds no
     text for it (`band` records which), so a hop to it returns nothing. `--probe-bands`
     measures this; without it, these dispatches are wasted (5 of 14 in the
     2026-08-19 run). Note the paper — it may still need a local index or a PDF.

2. For each id in `follow_set`, retrieve its snippets — pass the citing sentence as
   `reached_from` so followed evidence carries its provenance:

   ```
   python -m atlas_chat.cli_annotate fetch \
     --query "<query>" --paper-ids CorpusId:<id> --limit 20 \
     --role external --retrieval-method citation_traversal --hop <n> \
     --reached-from '{"corpus_id":"<citing paper>","hop":<n>,"citation_context":"<citing sentence>"}' \
     --out <output_dir>/annotated_snippets_hop<n>.json
   ```

3. Gate + propose + summarize as above. Never revisit a CorpusId already searched.
   Repeat until `depth` hops are done or the follow-set is empty.

### Final — merge + catalogue

- Merge every seed's and every hop's evidence_summary items into
  `<output_dir>/all_summaries.json` (array conforming to `all_summaries.schema.json`).
- Collect every CorpusId seen (seed + `source_paper` + `reached_from`) and call the
  `get_paper_batch` MCP tool
  (`fields="title,authors,year,venue,publicationDate,url,isOpenAccess,externalIds"`);
  write `<output_dir>/paper_catalogue.json`, keyed by `CorpusId:NNNN`. Every
  `source_paper` / `reached_from` identifier you emit must appear here.
- On each catalogue entry, carry `asta_indexing: {"band": ..., "snippets": ...,
  "ref_mentions": ...}` for every paper you have a band for (from the
  `--probe-bands` output, or `python scripts/setup_local_index.py audit-asta
  --paper-ids CorpusId:...,CorpusId:... --json` for papers you never proposed).
  The synthesizer needs this: a claim whose only support is an `abstract_only`
  paper rests on abstract text alone and must say so in the report.

## Output

- `<output_dir>/annotated_snippets_hop<n>.json` — slim records with `annotated_text` (from the CLI).
- `<output_dir>/follow_set_hop<n>.json` — the deduped follow-set + rejects (from the CLI).
- `<output_dir>/all_summaries.json` — array of evidence_summary items.
- `<output_dir>/paper_catalogue.json` — metadata for every paper referenced.
- `<output_dir>/unresolved_edges.json` — relevant citations with `[CorpusId:unresolved]`.

## Rules

- Do not call the ASTA `snippet_search` MCP tool — retrieval goes through the CLI so
  raw JSON never enters your context. `get_paper_batch` for the catalogue is fine.
- Gate at the sentence: follow only citations whose claim is relevant to the query.
- Follow only ids returned in the CLI `follow_set`; never invent or hand-edit ids.
- Never treat an `asta_unindexed` rejection as the reference being irrelevant — it is
  a retrieval limit, not a judgement. Record it; don't drop it silently.
- Never search a seed you weren't given; never revisit a CorpusId.
- Search every seed you were given, in priority order. Dropping the lower-priority
  atlas seed because the first one returned plenty loses the integration context;
  dropping a `subatlas_primary` seed loses the paper that defines the cell type.
- Quotes are exact substrings of `text`.
- Every evidence item carries `source_paper` (+`role`) and `retrieval_method`;
  followed items also carry `reached_from` (`corpus_id`/`doi`, `hop`, `citation_context`).
- Log, don't silently drop: unresolved relevant citations (`unresolved_edges.json`).
