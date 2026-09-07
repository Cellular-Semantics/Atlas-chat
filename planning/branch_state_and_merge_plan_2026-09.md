# Branch state and merge plan (September 2026)

Written to answer one question: **which branch should the MVP work fork from?**
Short answer — `dev`, as the repo convention already says. An earlier draft of the
consolidation plan named `feature/lit-search-mvp` as the base. That was wrong, and it
contradicted the convention that features fork from `dev` and `dev` merges to `main`
once end-to-end works.

What *was* meant by "step 0: consolidate" is: **merge the two outstanding feature
branches down to `dev`**, after which everything forks from `dev` like everything else.

---

## What each piece of planned work depends on

| work | depends on | on `dev` today? |
|---|---|---|
| #40 lightweight PDF text extraction (PR #44) | `services/_pdf_parser.py`, `services/supplement_store.py` | **yes** — correctly based |
| #41 supplement extraction + prose/tabular manifest split | supplement store + triage | **yes** — can start now |
| #41 folding supplement prose into the whole-paper context | `services/jats_reader.py` job files | no — `feature/lit-search-mvp` |
| #42 subatlas prioritisation at setup | `services/subatlas_contributors.py`, `subatlas_consistency*` schemas + hook | no — `feature/subatlas-consistency` |
| evidence record + report contract | `paper_router`, `jats_reader`, gather-evidence reader, `check_attribution` / `check_source_tags` | no — `feature/lit-search-mvp` |
| stage3b regression gate | `experiments/stage3b/` | no — `test/retrieval-matrix` (additive directory, trivially portable) |

**Consequence for #41:** it splits cleanly. The extraction and manifest-schema half can
proceed off `dev` now, alongside PR #44. Only the fold-into-context half waits on the
`lit-search-mvp` merge.

**Consequence for #42:** genuinely blocked until #34 lands on `dev`.

---

## Merge state, measured

Both feature branches merge into `dev` **cleanly and individually** —
`git merge-tree --write-tree dev <branch>` returns exit 0 for each.

They conflict only with **each other**, in four files:

| file | nature of the conflict |
|---|---|
| `CLAUDE.md` | being rewritten wholesale — the resolution is throwaway |
| `.claude/agents/synthesize-report.md` | being revised as part of the synthesis spec |
| `.gitignore` | trivial |
| `src/atlas_chat/atlas_chat/validation/report_checker.py` | **the real one** — `lit-search-mvp` adds `check_attribution`, `subatlas-consistency` adds `check_defining_paper`, and both are wanted |

### Suggested order

1. `feature/subatlas-consistency` → `dev`
2. `feature/lit-search-mvp` → `dev`

That way the newer CLAUDE.md rewrite wins the throwaway conflicts, and the one
substantive resolution — keeping both checkers in `report_checker.py` — happens once.

### Before merging #34, eyeball the size

`feature/subatlas-consistency` carries **266,817 lines of
`projects/test_projects/hca_reproductive/cas.json`** (pretty-printed). It is a
legitimate test asset and the project we want to test against, but it should be a
conscious decision rather than a surprise. `projects/test_projects/hdca_neurons/cas.json`
adds a further 8,264 lines, for a project that is itself blocked — its
`label_provenance.json` holds two marginals of a cross-tab rather than the join, so
`transferred_annotations` cannot be produced and the subatlas steps have nothing to run
on there.

Branch totals vs `dev`: `lit-search-mvp` 45 files, +3,513/−218;
`subatlas-consistency` 45 files, +282,197/−93 (the bulk being the two CAS+ documents).

---

## Why this matters beyond tidiness

Until those two merges happen, three of the planned work items have no correct base:
they either fork from a feature branch (breaking the convention and guaranteeing a
painful reconciliation later) or wait. Unblocking the merges converts "#42 and the
evidence-record work are blocked" into "everything forks from `dev`", which is the
precondition for the rest of the MVP sequence.
