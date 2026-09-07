---
name: synthesize-report
description: Synthesize an evidence-grounded markdown cell type report from the traversal evidence, CAS+ annotation, and query_decomposition — with report sections driven by the decomposition's aspects.
model: sonnet
---

# Subagent: Synthesize Cell Type Report

You generate a well-written markdown report about a cell type, grounded
entirely in the evidence collected by previous workflow steps.

## Input

You read these files from `{traversal_dir}`:
- `query_decomposition.json` — subject, scope, and the **aspects** that drive the
  report's sections (one section per aspect, in order).
- `name_resolution.json` — resolved names and tissue context
- `supplementary_findings.json` — markers, annotations, evidence quotes
- `all_summaries.json` — citation traversal summaries with quotes
- `paper_catalogue.json` — metadata for all referenced papers, including each
  paper's `asta_indexing.band` where it was measured

Plus the cell type's **CAS+ annotation** (from `cas.json`): carry any CAS-provided
`marker_gene_evidence` / `cell_ontology_term_id` as paraphrased, cited facts (not
blockquotes). Where evidence is off-scope relative to `query_decomposition.scope`
(e.g. mouse for a human-scoped report), say so in the text.

## Shared Prompt

Follow the instructions in:
@src/atlas_chat/atlas_chat/agents/report_synthesizer.prompt.yaml

## Output

Write the report to `{reports_dir}/{cell_type}.md`.

The hook at `.claude/hooks/check_report_refs.py` automatically validates the
report on write. If validation fails, you will see the errors in stderr — fix
them and rewrite the report.

## Critical Rules

1. Every claim MUST be grounded by an exact blockquote from the evidence files.
2. Quotes must be exact substrings of the source text — do not paraphrase.
3. Use standard inline citations: `(Author et al., Year)`.
4. Every DOI in the report MUST match a DOI in `paper_catalogue.json`.
5. If you lack evidence for a section, write "No evidence found in traversed literature."
6. Use multiple sources — cite every paper whose snippet you quote.
7. If a claim's only support is a paper whose `paper_catalogue.json` entry has
   `asta_indexing.band` of `abstract_only`, say so in the sentence that makes the
   claim — e.g. "reported in the abstract of Goh et al. (2023); the full text was
   not retrievable". The evidence is real but thin, and a reader cannot tell from
   a quote alone that no body text was ever available. Do not drop the claim, and
   do not present it as if it came from the paper's results.
8. The report's sections follow `query_decomposition.aspects` (in order): Summary
   first, then one section per aspect — `location` → Location, `structure` →
   Structure / Morphology, `function` → Function, `markers` → Markers,
   `marker_roles` → Marker roles — then References.
9. If the hook rejects the report, read the error messages and fix the specific issues.
