---
name: synthesize-report
description: Write the evidence-grounded cell type report from the gathered evidence, coverage verdicts, supplement findings and CAS+ annotation — sections driven by the decomposition aspects, absence stated honestly, every literature claim quote-backed.
input:
  schema: src/atlas_chat/atlas_chat/schemas/coverage.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/workflow_output.schema.json
---

# Skill: Synthesize Report

Produce `reports/{cell_type}.md`. Dispatch the write to a subagent
(model: `sonnet` — pin it explicitly) reading these files from the traversal
directory; do not paste their contents into the dispatch:

- `query_decomposition.json` — subject, scope, the five aspects (section order)
- `name_resolution.json`, `supplementary_findings.json`
- `all_summaries.json` — the ONLY source of blockquotes
- `paper_catalogue.json` — the ONLY source of DOIs; carries each paper's
  `route` and `asta_indexing` band
- `coverage.json` — which aspects have evidence and which are absent
- The cell type's CAS+ annotation — CAS `marker_gene_evidence` /
  `cell_ontology_term_id` are paraphrased, cited facts (not blockquotes)

Follow the shared prompt
`@src/atlas_chat/atlas_chat/agents/report_synthesizer.prompt.yaml`, plus:

## Structure

Title + header (Atlas, DOI, Scope), `Sources:` line (see below), `## Summary`,
then **one section per aspect in decomposition order** (`location` → Location,
`structure` → Structure / Morphology, `function` → Function, `markers` →
Markers, `marker_roles` → Marker roles), then `## References`.

## Honesty contract

1. An aspect whose coverage status is `absent` or `absent_after_free_search`
   gets exactly: **"No evidence found in traversed literature."** — no generic
   cell-biology padding, no latent-knowledge prose. This is a correct outcome,
   not a defect to write around.
2. Blockquotes come **only** from the `quotes` arrays of `all_summaries.json`
   items, character for character, each followed by an attribution line
   (`— Author et al. (Year)`). Supplement/name-resolution/CAS evidence is
   paraphrased with inline citation, never blockquoted.
3. Off-scope evidence (species/stage/tissue mismatch vs `scope`) may be used
   only with the mismatch stated in the sentence using it.
4. Caveats, per the paper catalogue entry of a claim's only supporting paper:
   - `asta_indexing.band: abstract_only` → say the claim rests on the abstract;
     full text was not retrievable.
   - `route: asta_snippet_bound` on a paper citations were followed from →
     citation-following there was limited to what the search surfaced.
   - `retrieval_method: free_search` items → mark inline, e.g.
     "(free literature search)" — these did not come from the atlas's citation
     neighbourhood.
5. Every DOI in References must exist in `paper_catalogue.json`. No invented
   DOIs, no invented author names.

## Sources header

After the title block add one line, counted from `all_summaries.json` +
`supplementary_findings.json` retrieval methods:

`Sources: N corpus evidence items, M citation-traversal, K supplement, J free-search`

## Validation loop

The `validate-report` skill runs next; if it returns errors, they come back to
this skill's subagent verbatim for a rewrite (max 2 retries). Fix the listed
issues only — do not restructure a passing report.
