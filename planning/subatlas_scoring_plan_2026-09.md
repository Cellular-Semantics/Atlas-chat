# Subatlas contribution scoring at setup — implementation plan

**Issue:** [#42](https://github.com/Cellular-Semantics/Atlas-reporter/issues/42) · **Date:** 2026-09-05 · **Branch:** to fork from `dev`


## Context

An atlas cell set often inherits its name from a contributing study. CAS+ records
that as `transferred_annotations`, but nothing on `dev` reads it. The consequence
was measured in `planning/report_coverage_audit_2026-08.md`: annotations inherited
from a contributing study drew 1.4 evidence items per report against 3.0 for the
atlas's own, with *more* unsourced prose, because retrieval always started from the
atlas paper and the paper that actually defines those cell types was often never
read.

This ticket builds the deterministic half of the fix, and only that half. At project
setup, score how each atlas cell set overlaps the cell sets of each contributing
paper, apply a cutoff, and emit a **read plan**: which papers to read, which of
*their* cell sets to ask about, which atlas cell sets those bear on, and what the
shape of the overlap looks like from the numbers alone. No model call anywhere in it.

Everything downstream — reading the papers, judging concordance from their words,
writing it into reports — is out of scope. The read plan is the deliverable.

**Branch:** fork from `dev`.

**Relationship to `feature/subatlas-consistency` (PR #34):** that branch is not
expected to merge. Take ideas and shapes from it, not the branch itself.

---

## Vocabulary

The atlas is the thing doing the integrating. A contributing study defines its own
cell sets; the atlas pulls cells out of those and puts them into cell sets of its
own. Two independent groupings of the same cells, each with its own names — keep
them apart in every field name, docstring and message.

| Term | Means | In CAS+ |
|---|---|---|
| **atlas cell set** | a cell set the atlas defines | an `annotations[]` entry |
| **atlas label** | what the atlas calls it | `cell_label` |
| **subatlas cell set** | a cell set a contributing study defines; its size *as integrated* is however many cells of it reached the atlas | implied by a `transferred_cell_label` under one `subatlas_paper` |
| **subatlas label** | what that study calls it | `transferred_cell_label` |
| **overlap** | cells belonging to both an atlas cell set and a subatlas cell set | `transferred_annotations[].cell_count` |
| **contribution** | every cell of one atlas cell set that came from one subatlas, whatever that subatlas called it | summed per paper |

Most cells in an atlas cell set typically come from studies other than the one being
scored — that is why the denominators below are what they are.

## The numbers

Worked example, with every quantity a different order of magnitude so nothing can be
misread:

> The atlas integrates subatlas cell set **`fu`**. **500** of its cells reach the
> atlas. **120** of those go into the atlas cell set **`bar`**. `bar` holds **4,000**
> cells in total, **150** of which came from that subatlas.

**`overlap_cells` = 120.** The size of the intersection. A guard against reading
anything into a handful of cells.

**`fraction_of_subatlas_set` = 120 / 500 = 0.24.** *Of `fu`, this much came here.*
The headline number: it says whether `bar` accounts for `fu`, or is one of several
places `fu` ended up. (`reverse_share` on the other branch; the recall side.)

**`purity` = 120 / 150 = 0.80.** *Of what this subatlas contributed to `bar`, this
much is `fu`.* The denominator is the subatlas's contribution, **not** all 4,000
cells of `bar` — the rest came from other studies that never saw these cells, and
counting them would penalise a study for cells it had no part in.
(`within_source_share` on the other branch; the precision side.)

**`fraction_of_atlas_set` = 120 / 4000 = 0.03.** *Of `bar`, this much is `fu`.*
**Recorded, never gated.** It is confounded by every other study's cells, so a low
value says more about how many studies fed `bar` than about the correspondence.

**`f1`** is the harmonic mean of `fraction_of_subatlas_set` and `purity`, and it is
what the cutoff is applied to.

### Why `fraction_of_subatlas_set` alone is not enough

It looks like the one number that matters — "nearly all of `fu` came here" sounds
like a one-to-one mapping. Measured on `hca_reproductive`, it isn't. **575 pairs**
have ≥90% of a subatlas cell set landing in a single atlas cell set, and **405 of
those have purity below 0.5**. The extreme cases are a coarse atlas cell set
absorbing a fine subatlas one whole:

| atlas cell set | subatlas cell set | of subatlas set | purity |
|---|---|---|---|
| `Mesenchymal` (L1) | OvarySanger `Theca_Atr` | 1.00 (383/383) | 0.00 |
| `Mesenchymal` (L1) | OvarySanger `SMCs` | 1.00 (474/474) | 0.00 |
| `Fallopian Tube secretory epithelial` | Ulrich 2022 `secretory cell` | 1.00 | 1.00 |

The first two say only that `Mesenchymal` is enormous and holds dozens of other cell
sets from the same study. The third is a real one-to-one. Nothing but purity
separates them.

Purity is partly recoverable downstream — a reader who sees every subatlas cell set
that fed an atlas cell set can infer it — but the cutoff runs before any reader, so
it needs the number itself.

---

## Decisions already made

- Gate on `f1`, with all three numbers and both denominators recorded on every
  record, so a threshold change is a diff over a committed file, not a re-run.
- `fraction_of_subatlas_set`'s denominator is **derived**, not read from CAS+. No CAS+
  schema change.
- Two output files: the scores, and the read plan derived from them.

---

## Findings that shape the design

Measured on the three projects available. Numbers reproduce exactly.

### 1. Only one of the three numbers needs a partition — and hierarchy is not guaranteed

To size a subatlas cell set atlas-wide, sum its overlaps across a set of atlas cell
sets that covers every cell exactly once. `overlap_cells` and
`purity` need no such thing, and no `n_cells` either.

The three projects to hand are all different, so **do not assume a hierarchy, and do
not assume a labelset covers the atlas**:

| project | parent links | labelsets | `n_cells` | partition |
|---|---|---|---|---|
| `hca_reproductive` | yes | 4 | complete | leaves of the hierarchy — 210 sets, exactly 2,235,448 cells, matching the coarsest labelset |
| `hdca_neurons` | **no** | 2 | complete | labelset totals disagree — 1,687,408 vs 131,103 — so neither is validated |
| `fetal_skin_atlas` | yes | 2 | **absent** | none available |

So: find the partition, don't assume it.

1. If any cell set carries `parent_cell_set_accession`, the candidate is the
   **leaves** — cell sets that are nobody's parent. On `hca_reproductive` the leaves
   span three different labelsets (167 L4, 39 L3, 4 L2), which is exactly why "take
   the finest labelset" is wrong: L4 alone misses 319,107 cells and would inflate
   `fraction_of_subatlas_set` by up to 2.7× (`aPCV`'s denominator comes out 876 against
   a true 2,402).
2. Otherwise each labelset is a candidate, finest first.
3. A candidate is usable only if every cell set in it has `n_cells`, and — where
   there is more than one candidate — the totals agree. `hdca_neurons` fails this and
   must fail loudly, not silently pick the bigger one.
4. Record the choice on the output: which cell sets, how many cells, and how it was
   chosen.

**When no partition is available**, emit `overlap_cells` and
`purity` only, omit `fraction_of_subatlas_set` and `f1`, mark the run
`degraded`, and gate on `purity` plus `min_overlap_cells` instead. Say so
on the read plan. Never guess a denominator.

### 2. `f1` alone discards the subatlas cell set the atlas authors actually adopted

The atlas cell set `Activated post-capillary venous endothelial` lists `aPCV` in its
CAS+ `synonyms` — Ulrich 2024's name for one of *its* cell sets. Of the eight
subatlas cell sets overlapping it, `aPCV` ranks seventh:

| paper | subatlas cell set | overlap | purity | fraction_of_subatlas_set | f1 |
|---|---|---|---|---|---|
| Weigert 2025 | `endothelial cell` | 1168 | 1.000 | 0.244 | 0.393 |
| Ulrich 2024 | `Capillary` | 197 | 0.593 | 0.119 | 0.198 |
| Ulrich 2024 | **`aPCV`** | 37 | 0.111 | 0.015 | **0.027** |

The top hit agrees with a venous subtype the way it agrees with anything. The one the
authors named is nearly last, because an asserted correspondence is invisible to an
overlap statistic. So a CAS+ `synonyms` entry naming a subatlas cell set
**force-includes that pair regardless of `f1`**, marked `included_by: "synonym"`.

### 3. That synonym match needs care, and the obvious version is wrong

39 of 312 atlas cell sets carry synonyms (52 in total) — a small, high-value
correction, not a mass mechanism. Two traps, both real here:

- **Punctuation is not noise.** Stripping it collapses `PV-MYH11_CDKN1A+` and
  `PV-MYH11_CDKN1A-` into one string, so the synonym naming the CDKN1A-positive
  subatlas cell set matches the negative one — **6 sign-flipped pairs across three
  atlas cell sets**, on opposite marker states. Normalise sign-safely: casefold,
  squash `_ - /` and whitespace, but **keep a trailing `+`/`-`**. Still catches the
  benign variants (`ePV2`↔`ePV_2`, `Endo_cycling`↔`Endo_Cycling`, `TIP`↔`Tip`);
  crossings drop to zero. 29 clean pairs.
- **Match only within that atlas cell set's own provenance.** Matching against every
  subatlas label in the atlas produced 2 pairs where the atlas cell set had received
  no cells of that subatlas cell set at all — an overlap of zero.

Do **not** strip the `Modular nomenclature:` prefix that 10 synonyms carry: it yields
no extra matches and is machinery for nothing.

### 4. One subatlas cell set often spans several atlas cell sets — key the plan by the subatlas cell set

3 of 23 synonym-matched subatlas cell sets are claimed by more than one atlas cell
set. On `hca_reproductive` these happen to be nested (an L2 parent and its two L4
children, cells adding up exactly: `PV-MYH11_CDKN1A+` = 6470 + 3122 = 9592), but the
general case is simply **splitting** — one upstream cell set cut across several atlas
ones — and that occurs with or without a hierarchy.

So key the read plan by (paper, subatlas cell set): one question, one read, listing
every atlas cell set it overlaps. `nested_under` is recorded **only where
`parent_cell_set_accession` exists** and one claimant is a descendant of another;
with flat annotation the field is simply absent and the co-claimants are still
listed. Nothing in the design requires a hierarchy.

---

## What gets built

### Schemas (source of truth, written first)

`src/atlas_chat/atlas_chat/schemas/`, both `additionalProperties: false`. The field
names below are deliberately self-describing; note in each description which name the
other branch used, so the two can be reconciled later.

**`subatlas_scores.schema.json`** — the measurement.

Document level: `thresholds`; `partition` (`basis`: `hierarchy_leaves` |
`labelset` | `none`, plus `n_cell_sets`, `total_cells`, `labelset` where relevant,
and `reason` when `none`); `degraded` (true when there is no partition); the
sensitivity table.

Per atlas cell set: `cell_label`, `labelset`, `cell_set_accession`, `n_cells`, and
`overlaps[]`. Per overlap: `subatlas_paper`, `doi`, `subatlas_cell_label`,
`overlap_cells`, `subatlas_contribution_cells` and `subatlas_set_total_cells` (both denominators,
so every ratio is auditable), `purity`, `fraction_of_subatlas_set`,
`f1`, `fraction_of_atlas_set`. Overlaps below the recording floor roll up per (atlas
cell set, paper) into a `tail` block naming the papers, so exclusions stay visible.

**`subatlas_read_plan.schema.json`** — the policy applied to it.

Keyed by paper: `subatlas_paper`, `doi`, `status`, `asta_band` (passed through from
`source.subatlas_papers[]`), and `questions[]`. One question per subatlas cell set:
`subatlas_cell_label`, `overlap_shape`, `included_by` (`f1` | `synonym` |
`purity_only` in degraded runs), and `atlas_cell_sets[]` — each with
`cell_label`, `labelset`, `cell_set_accession`, the three numbers, and `nested_under`
only where the hierarchy supports it. Top level: `degraded`, and `gaps[]` for
contributors with no DOI and atlas cell sets that ended with nothing.

### Service

**`src/atlas_chat/atlas_chat/services/subatlas_scoring.py`** — new, stdlib only, a
pure function of the CAS+ document. `build_parser`/`main` live in the service; the
`cli_*` module is a thin re-export, matching `cli_contributors.py`'s shape.

```python
def find_partition(cas_doc) -> dict          # basis, cell sets, total, or reason it failed
def score(cas_doc, *, thresholds=None, non_paper_labels=()) -> dict
def read_plan(scores, cas_doc, *, thresholds=None) -> dict
def sensitivity(cas_doc, *, floors=(...)) -> list[dict]
def build_parser() -> argparse.ArgumentParser
def main(argv=None) -> int
```

In order:

1. **Find the partition** per §1 above; record basis and total, or the reason none
   was found.
2. **Size each subatlas cell set**: sum `overlap_cells` per (paper, subatlas label)
   across the partition.
3. **Per atlas cell set** with provenance, group `transferred_annotations` by paper
   (key `subatlas_paper`, falling back to `source_taxonomy`; strip a `DOI:` prefix;
   resolve against `source.subatlas_papers[]` by `label`). Sum each
   subatlas's contribution to the atlas cell set, then compute the numbers per overlap.
4. **Gate**: `f1 >= f1_floor` and `overlap_cells >= min_overlap_cells`; or, degraded,
   `purity >= purity_floor` and `overlap_cells >= min_overlap_cells`; **or** force-included by a sign-safe synonym match scoped to
   that atlas cell set's own provenance.
5. **`overlap_shape`**, from the numbers alone — this is what tells a reader what to
   ask the paper:
   - `fraction_of_subatlas_set` high, `purity` high → `one_to_one`
   - `purity` high, `fraction_of_subatlas_set` low → `atlas_set_within_subatlas_set` (the atlas split the subatlas cell set; this is one piece)
   - `fraction_of_subatlas_set` high, `purity` low → `subatlas_set_within_atlas_set` (the atlas cell set absorbed this one along with others from the same study)
   - both low → `weak` (only ever present when force-included by synonym)
   - no partition → `unknown`
6. **Read plan**: invert to paper → subatlas cell set → claimant atlas cell sets;
   add `nested_under` only where parent links exist. A paper with real provenance and
   no DOI is a named gap, held apart from "excluded for being small".
7. **Sensitivity**: papers, subatlas cell sets, atlas cell sets and overlaps
   surviving across a spread of `f1` floors — printed every run, recorded on the
   scores file.

A project with no `transferred_annotations` anywhere produces nothing and says so, so
the step is conditional.

### CLI

`src/atlas_chat/atlas_chat/cli_subatlas_scores.py` — thin re-export.

```
python -m atlas_chat.cli_subatlas_scores \
  --cas projects/{project}/cas.json \
  --scores-out projects/{project}/subatlas_scores.json \
  --plan-out   projects/{project}/subatlas_read_plan.json \
  [--f1-floor 0.2] [--min-overlap-cells 25] [--sensitivity]
```

Paths are arguments, never derived from a project name.

### Hooks

`.claude/hooks/check_subatlas_scores.py` and `check_subatlas_read_plan.py`,
registered in `.claude/settings.json`. Schema validation plus the arithmetic: both
shares and `f1` recompute from the recorded denominators within tolerance; a record
carrying `fraction_of_subatlas_set` on a run with `partition.basis: "none"` is rejected;
every read-plan question traces to an overlap in the scores file; a question marked
`included_by: "synonym"` really does match a CAS+ synonym under the sign-safe rule.
Follow `check_subatlas_contributors.py` on the other branch, including its message
pointing at regeneration rather than hand-editing.

Note: `.claude/settings.json` on `feature/subatlas-consistency` has a malformed hook
block (a duplicated `"type"` key, one entry missing `type`). Don't copy it.

### Test data

Bring `projects/test_projects/hca_reproductive/cas.json` across from
`feature/subatlas-consistency` — the only project with real joint provenance.
**Strip `source_label_cell_count` from every transferred item**: `dev`'s
`TransferredAnnotation` is closed (`additionalProperties: false`) so the file will
not otherwise validate, and removing it makes the derivation the sole source, which
is what should be under test.

Also bring `projects/test_projects/hdca_neurons/cas.json` — it is the flat,
no-hierarchy, disagreeing-labelsets case, and without it the partition logic is only
ever exercised on the one project it was designed against.

### Tests

`tests/unit/`, every test marked `@pytest.mark.unit`:

- **Partition**: leaves chosen and validated on a hierarchy; a flat single labelset
  used directly; disagreeing labelsets with no parent links refused; missing
  `n_cells` refused. Each case asserts on `partition.basis` and `reason`.
- **Degraded run**: with no partition, `purity` is still emitted,
  `fraction_of_subatlas_set` and `f1` are absent, `overlap_shape` is `unknown`, and the
  gate falls back to `purity` alone.
- `purity` uses the subatlas's contribution to the atlas cell set as its
  denominator, not the atlas cell set's `n_cells`.
- **Sign-safe synonym matching**: `PV-MYH11_CDKN1A+` does not match
  `PV-MYH11_CDKN1A-`; `ePV2` matches `ePV_2` and `TIP` matches `Tip`; a synonym
  naming a subatlas cell set with no overlap in that atlas cell set yields nothing.
- **The `aPCV` regression**: eight overlaps, `aPCV` at 37 cells / 0.111 / 0.015 /
  0.027, excluded by `f1` and included by synonym.
- **Multi-claim**: `PV-MYH11_CDKN1A+` yields one question listing three atlas cell
  sets; with parent links two carry `nested_under`, and with the links removed the
  same three are listed and no `nested_under` appears.
- Each `overlap_shape` branch, and both gates at boundary values.
- Good/bad golden fixtures under `tests/unit/fixtures/subatlas/` for both schemas,
  following `tests/unit/test_cl_mapping_schema.py`.
- Hooks driven by subprocess, following `tests/unit/test_curation_guard.py`.
- CLI: both files written, exit codes, sensitivity output.

---

## Open, deliberately

The **`f1` floor and `min_overlap_cells` are not fixed by this plan.** The
distribution has no knee — deciles are flat — so any value is a policy choice, and
the ticket's own comment says the cell floor in particular needs eyeballing first (at
a 50-cell floor, `Schwanns immature/promyelinating` is dropped despite 35 of its 35
cells coming from a single paper). Build the scorer, run `--sensitivity` over
`hca_reproductive`, look at what each floor drops, then set the defaults in a
follow-up commit with the evidence in the message. Provisional during development:
`f1_floor 0.2`, `min_overlap_cells 25`.

## Verification

```bash
uv run pytest -m unit --cov          # incl. the aPCV, partition and sign-safe regressions
uv run ruff check src/ tests/ && uv run mypy src/

uv run python -m atlas_chat.cli_subatlas_scores \
  --cas projects/test_projects/hca_reproductive/cas.json \
  --scores-out /tmp/scores.json --plan-out /tmp/plan.json --sensitivity
```

Then check by hand:

- `partition.basis` is `hierarchy_leaves`, 210 cell sets, 2,235,448 cells; 7,488
  overlaps scored across 303 atlas cell sets.
- The read plan names papers from the nine in `source.subatlas_papers[]`, and
  `celltype_OvarySanger2026` appears under `gaps[]` — a large contributor with no DOI
  to read.
- Ulrich 2024's questions include `aPCV` with `included_by: "synonym"`, and
  `PV-MYH11_CDKN1A+` appears once listing three atlas cell sets, not three times.
- Run against `hdca_neurons` and confirm it refuses the partition and produces a
  degraded plan that says why, rather than inventing a denominator.
- Run against `fetal_skin_atlas` (no `transferred_annotations`) and confirm it
  reports nothing to do rather than failing.
- Write both files through Claude Code so the PostToolUse hooks fire, then
  hand-corrupt one number and confirm rejection.

---

## Implementation notes (2026-09-05)

Three things the plan did not anticipate, all found by running against real data
before writing tests:

**`overlap_shape` belongs on the (atlas cell set, subatlas cell set) pair, not on
the question.** The first cut put it on the question, which made
`PV-MYH11_CDKN1A+` `one_to_one` while its five claimants ranged from 0.15 to 0.78
purity. It now sits on each `atlas_cell_sets[]` entry.

**A separate `shape_high` threshold, default 0.5.** The first cut read shapes off
`f1_floor` (0.2), which called a 0.39/0.29 overlap `one_to_one`. Whether an
overlap is worth asking about and whether it looks one-to-one are different
judgements and need different numbers.

**Coarser claimants are dropped when a finer one is present.** Where the CAS+
document has a hierarchy, every ancestor of a genuine claimant also overlaps and
clears the cutoff, so the same question arrived once per level — the `aPCV`
question listed L1 `Endothelial`, L2 and L3 `Capillary endothelial` and only then
the L4 cell set that carries the synonym. Collapsing to the most specific
claimants (459 dropped on the reference project, recorded per question as
`n_coarser_dropped`) also sharpens the finding: Ulrich's `aPCV` cells mostly went
into the atlas's `Capillary endothelial`, with only 37 into the cell set the atlas
named `aPCV`. That discordance is the thing worth asking about. With flat
annotation there is nothing to collapse and the co-claimants are listed as before.

### Measured on `hca_reproductive` at the provisional defaults

`f1_floor` 0.2, `min_overlap_cells` 25, `record_floor` 0.02, `shape_high` 0.5:

- partition `hierarchy_leaves`, 210 cell sets, 2,235,448 cells, spanning L2/L3/L4
- 2,961 overlaps scored across 303 atlas cell sets
- read plan: 245 questions across 9 papers; 223 included by `f1`, 22 by synonym
- 90 questions have more than one claimant — the atlas split that subatlas cell set
- shapes over 378 claimants: 161 `one_to_one`, 141 `atlas_set_within_subatlas_set`,
  39 `subatlas_set_within_atlas_set`, 37 `weak`
- zero marker-sign crossings
- `celltype_OvarySanger2026` reported as a gap twice over: no DOI to read, and
  registry status `unresolved`

### Still open

- The `f1_floor` / `min_overlap_cells` defaults, as the plan says — run
  `--sensitivity` and look at what each floor drops before fixing them.
- Wiring the step into the setup sequence (`CLAUDE.md` / `docs/functional_spec.md`)
  is not done: the CLI and its outputs exist, but nothing calls them yet.

