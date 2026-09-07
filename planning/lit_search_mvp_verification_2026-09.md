# Lit-search MVP — build verification (2026-09-01)

Branch `feature/lit-search-mvp` (worktree `../lit-search-mvp`), built per the
approved plan against `planning/retrieval_architecture_decision_2026-08.md`
(dev worktree). This note records what was verified at each layer, live where
the layer touches an external service, so the next session can pick up at the
end-to-end run without re-deriving state.

## What is on the branch

1. **Cherry-picks**: #34's `seeds` array + `cli_annotate fetch --local`
   (commit `2e3d54b`); query-decomposer Layer A (step 1b selection) + Layer B
   (query-decomposer agent, schema, hook) + `name_resolution.schema.json`.
2. **Phase 1** (`services/paper_router.py`, `services/jats_reader.py`,
   `cli_annotate route/read/follow-check`, `full_text` retrieval_method).
3. **Phase 2**: six skills (`gather-evidence` + READER_PROMPT, `assess-coverage`,
   `free-search`, `scan-supplements`, `synthesize-report`, `validate-report`),
   `coverage` + `gather_evidence_input` schemas, `check_coverage` hook,
   CLAUDE.md workflow rewrite (JATS-first tool rules, Run Settings with
   `reader_model`, steps 2/4/4a–4d/5/6 as skill invocations).
4. **Phase 3**: `check_attribution` in `report_checker.validate_report`.

## Verified — unit (449 pass, ruff clean, mypy at baseline)

- Router waterfall rung order and band gating (every network boundary
  monkeypatched); seen-set id-space bridging (DOI ↔ CorpusId forms).
- jats_reader: narrative/legend separation, cited-sentence resolution,
  oversized-truncation with BM25 keep-the-relevant-segment.
- follow-check: accepts real ref_ids and DOI forms, rejects invented refs,
  dedups against traversed.json.
- Schema regression: coverage (five fixed aspects, absent_after_free_search),
  gather input, retrieval_method enum sync across schema files, hook exit codes.
- Attribution: attributed pass, orphan fails, back-to-back quotes each carry
  their own obligation.

## Verified — live (real endpoints, 2026-09-01)

| check | result |
|---|---|
| `route` Gopee (10.1038/s41586-024-08002-x) | `jats` via EuropePMC, cached to the project |
| `read` Gopee | narrative 39,696 chars (~10k tok — matches the stage3b corpus measure), methods 59,885 kept aside, **134 cited sentences**, 109 refs / 96 with DOI (matches the citation-traversal survey), 15 legends |
| `follow-check` CR5/CR58/CR999 | CR5+CR58 followed with citing sentences attached; CR999 rejected `not_in_reference_list`. CR5's citing sentence is the "macrophages seed the skin as early as 6 PCW" sentence **absent from ASTA's copy** — the JATS path carries what ASTA drops |
| hop-1 `read` Suo (10.1126/science.abo0510, AAAS) | 103 refs / 99 with DOI — the #37 acceptance numbers; both papers in traversed.json |
| `route` 10.1016/0378-3782(91)90155-V (1991, no PMC) | ASTA probe live → band `unindexed` → `unreachable` with reason recorded — the honest-gap rung |
| **Reader smoke test** (Opus subagent, READER_PROMPT, Gopee job file, subject "Iron-recycling macrophage") | 5/5 quotes exact substrings (one from a legend); structure/markers/marker_roles **declined honestly** — markers correctly identified as living in supplementary tables, not narrative; 7/7 follow proposals are real refs; proposed CR5 (Suo) as the marker source — the subatlas-seeding behaviour the architecture wants |

The Nature-JATS methods discovery from the live run: no section is titled
"Methods"; methods prose sits in leaf sections after Discussion. jats_reader
now cuts narrative at the last Discussion section (commit `d735033`).

## Not yet verified — next session

1. **End-to-end run** — needs a session started **inside**
   `../lit-search-mvp` (skills/agents load from the launch dir). Project
   `test_projects/fetal_skin_atlas`, query "Iron-recycling macrophage",
   `reader_model: opus`. Expect: markers from the supplement store (Table 22),
   structure section reading "No evidence found in traversed literature.",
   validation green including attribution.
2. **Stage3b harness re-run** against the gather-evidence path (16 cell types,
   55 items) — the regression number for the release check. Target ≥ 44/55,
   zero fabricated quotes.
3. ASTA-route delegate live (a `band: full` paper with no PMC text) — band
   gating is pinned in unit tests against #28's live-calibrated fixtures, but
   the delegate procedure hasn't run under the new skill.
