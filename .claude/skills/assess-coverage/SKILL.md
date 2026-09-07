---
name: assess-coverage
description: Judge per-aspect, in-scope evidence coverage of a cell type's gathered evidence, producing the coverage.json that drives free-search escalation and the synthesizer's honesty contract.
input:
  schema: src/atlas_chat/atlas_chat/schemas/query_decomposition.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/coverage.schema.json
---

# Skill: Assess Coverage

After gather-evidence (and scan-supplements), decide per aspect whether the
evidence is enough to write that report section — and record it, so escalation
and honesty are driven by an artifact rather than by impression.

## Inputs

- `query_decomposition.json` — the five aspects and the `scope`
  (organism / developmental stage / tissue)
- `all_summaries.json` — the gathered evidence
- `supplementary_findings.json` — markers found in supplements count toward the
  `markers` aspect (that is where marker evidence usually lives)
- Output path for `coverage.json`

## Procedure

Count first, judge second:

1. For each aspect, collect the evidence items that address it (an item
   addresses an aspect if its summary/quotes answer that aspect's question —
   most items were produced as per-aspect answers and are unambiguous).
2. Mark each item in-scope or off-scope against `scope`: the source paper's
   organism / stage / tissue context. `reached_from` and catalogue metadata say
   what the source paper studied; when unsure, off-scope.
3. Status per aspect:
   - `covered` — ≥2 in-scope items with quotes, or 1 unambiguous in-scope item
     plus supplement support.
   - `thin` — exactly 1 in-scope item, or several items that are all weak
     (abstract-only sources, tangential mentions).
   - `absent` — nothing, or off-scope only (also set `off_scope_only: true`).
4. Write `coverage.json` (hook-validated). Keep `note` short and factual —
   e.g. "markers only from organoid comparison" — the synthesizer reads it.

## Rules

- Do not inflate: quote-less prose in a summary is not evidence.
- Structure is genuinely absent from most transcriptomic atlases — `absent` is a
  normal, correct outcome, not a failure to look.
- Off-scope evidence is not discarded — it stays available to the synthesizer
  with the mismatch stated — but it never upgrades an aspect's status.
