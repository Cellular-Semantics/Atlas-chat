# Subagent: Synthesize Cell Type Report

You generate a well-written markdown report about a cell type, grounded
entirely in the evidence collected by previous workflow steps.

## Input

You read these files from `{traversal_dir}`:
- `name_resolution.json` — resolved names and tissue context
- `supplementary_findings.json` — markers, annotations, evidence quotes
- `all_summaries.json` — citation traversal summaries with quotes
- `paper_catalogue.json` — metadata for all referenced papers

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
7. If the hook rejects the report, read the error messages and fix the specific issues.
