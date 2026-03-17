# Subagent: Synthesize Cell Type Report

You generate a structured markdown report about a cell type, grounded entirely in the evidence collected by previous workflow steps.

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

The hook at `.claude/hooks/check_report_refs.py` automatically validates the report on write. If validation fails, you will see the errors in stderr — fix them and rewrite the report.

## Report Format

```markdown
# {Cell Type Full Name} ({annotation_label})
Atlas: {atlas_title} (DOI: {doi})
Scope: {scope}

## Summary
Brief overview (2-3 sentences).

## Location
> "exact quote" — [Author2024](CorpusId:NNN) Title

Claim grounded by quote.

## Function
> "exact quote" — [Author2024](CorpusId:NNN) Title

## Markers
| Gene | Evidence | Source |
|------|----------|--------|
| CD207 | > "quote about marker" | [Author2024](CorpusId:NNN) |

## Structure / Morphology
...

## References
- CorpusId:NNNNNNN | Author et al. (Year) "Title" — DOI:xxx
```

## Critical Rules

1. Every claim MUST be grounded by an exact quote from the evidence files.
2. Quotes must be exact substrings of the source text — do not paraphrase.
3. Every CorpusId in the report MUST appear in `paper_catalogue.json`.
4. If you lack evidence for a section, write "No evidence found in traversed literature."
5. The Markers table must only include genes with explicit evidence.
6. If the hook rejects the report, read the error messages and fix the specific issues.
