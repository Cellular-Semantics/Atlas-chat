---
name: validate-report
description: Run the report validation contract (exact quotes, resolvable DOIs, source tags, blockquote attribution) against a written report and drive the synthesis retry loop. Explicit orchestrator step — never hook-dependent.
input:
  schema: src/atlas_chat/atlas_chat/schemas/workflow_output.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/workflow_output.schema.json
---

# Skill: Validate Report

The canonical grounding check. Runs after every synthesis, in the main context —
one Python call, no subagent:

```python
from atlas_chat.validation.report_checker import validate_report
passed, errors = validate_report(report_path, traversal_dir)
```

Checks (all in `src/atlas_chat/atlas_chat/validation/report_checker.py`):

1. **Quotes** — every blockquote is an exact substring of the evidence corpus
   (all_summaries quotes/snippets + supplementary evidence). Quotes are checked
   against the text of the evidence record they came from, so each is validated
   against the rendering it was actually read in.
2. **References** — every DOI in the report resolves to a paper_catalogue entry.
3. **Source tags** — every evidence-backed claim's provenance tags are
   consistent (`check_source_tags`); a report whose literature evidence is
   entirely `free_search` draws a **warning** (name resolution or seeding
   likely failed), not a failure.
4. **Attribution** — every blockquote is followed by an attribution line
   (`— Author et al. (Year)`). A verifiable quote with no attribution is the
   reference failure this catches.

## Retry loop

On failure: pass the error list back to the synthesize-report subagent verbatim
and re-validate — max 2 retries. On the third failure, stop and report the
remaining errors to the user; do not weaken a check to get a pass, and do not
hand-edit the report around the validator.

The `check_report_refs.py` write hook is an optional extra guard for interactive
sessions — this explicit step is the contract and must run regardless.
