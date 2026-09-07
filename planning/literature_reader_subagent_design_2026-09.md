# The literature-reading subagent: ingest, staged questions, output

Design note, not an implementation. One subagent, one paper, a batch of cell types, a
staged sequence of questions, and one consolidated output conforming to the evidence
record (#46).

Written against `dev` as of 2026-09-07, with #34 and #39 kept for reference only.

---

## 0. What exists, and the one thing that does not

| needed for ingest | state on `dev` |
|---|---|
| flagged supplementary prose | **in place** — `services/supplement_prose.py` + `assess-supplement-content` (haiku) |
| supplementary table legends as prose | **in place** — same path |
| PDF / docx text | **in place** — #44, `text-access` extra |
| CAS+ annotations, synonyms, transfer stats | **in place** — #50 |
| subatlas read plan (which papers, which questions) | on `feature/subatlas-scoring`, not merged |
| **paper narrative text + figure legends, whole** | **nothing on `dev`** |

`paper_router` and `jats_reader` live only on `feature/lit-search-mvp`, now
reference-only. So the subagent's primary input — the paper itself — has no producer on
`dev`. **This is the blocker, and it should be its own ticket**: a whole-text reader that
emits narrative prose, figure legends held separately, and cited sentences with their
resolved references. Everything below assumes it.

Why legends must be separate rather than spliced into prose: measured on Gopee, the
abbreviation expansions for `ASDC`, `DC1`, `DC2`, `LC`, `LE`, `LTi`, `HSC`, `MEMP` and
`pDC` have **zero** body-prose occurrences — Fig. 1's legend carries a literal glossary.
Splice them in and you lose the naming vocabulary; drop them and you lose it too.

---

## 1. Ingest specification

What is loaded into context before any question is asked, in precedence order. The order
matters because it is also the truncation order when the budget binds.

1. **Paper narrative text**, whole, methods held aside. ~10k tokens for Gopee, ~12k for
   the reproductive preprint — both comfortable.
2. **Figure and table legends**, as their own block, labelled as legends.
3. **The subject block** — for each cell type assigned to this read:
   - the atlas label, its CAS+ `synonyms`, `marker_gene_evidence`, and `composition`
     context (tissue, stage, organism)
   - its position in the labelset hierarchy — parent and children labels
   - for a subatlas paper: the read plan's question for this subatlas cell set,
     **including the set statistics** (see §2b)
4. **Flagged supplementary prose** — the spans `assess-supplement-content` kept, plus
   any short prose unit read whole. Supplementary table legends are part of this and are
   high value: they are where Supplementary Table 22 announces itself as the DEG table
   for the four macrophage subsets.

**Not loaded: differential-expression table contents.** Those are queried afterwards,
per candidate gene, deterministically. Supplementary Table 5 in Gopee's bundle is 95 MB
and 396,877 rows; Table 22 is 550 genes for one subset. Prose folds in whole, tables are
sliced on demand — the format decides.

**A budget note that needs a decision.** Over the 22-paper reproductive corpus the prose
units come to ~125k tokens before flagging and ~72k after. That is a corpus total, not a
per-paper figure, but for a supplement-heavy paper the flagged prose can exceed the
paper text. So the ingest needs a stated token budget, the precedence order above, and a
recorded gap when it truncates — never a silent drop.

---

## 2. The questions, in series

Series, not parallel, because each stage supplies vocabulary the next one needs.

### 2a. Grounding — first, and it has to be first

> For each subject below, what does **this paper** call it? Give every form the paper
> uses: the full name in running prose, abbreviations, cluster identifiers, and any
> alternative name. Quote the sentence or legend each form appears in. If the paper
> never refers to this population, say so.

This precedes the transfer judgement, not the other way round: you cannot judge whether
two labels mean the same thing until you know what this paper's label denotes in its own
words.

Two hard-won rules for this stage:

- **A synonym must denote the same set of cells.** A subset, a sibling, a broader class,
  or the same name in another experimental system does not qualify. Mechanical synonym
  assembly on Gopee produced `lyve1+ macrophage` as an alternative name for
  `Macrophage` — a cell type's own subset offered as its synonym. A judgement pass
  accepted 26 candidates and **rejected 11** across six distinct kinds.
- **Every accepted form carries a verbatim span.** Nothing on prior knowledge alone.

Rejections are worth keeping, not discarding: they are what a later run must not
re-accept.

### 2b. Transfer judgement — subatlas papers only

**Part of this is upstream, and the split matters.** Raised in review as an open
question; the answer is that two different relations are being conflated.

| relation | who decides | from what |
|---|---|---|
| the **set** relation — how the cells overlap | **upstream, deterministic, no model** | CAS+ `transferred_annotations`: overlap cells, purity, fraction of the subatlas set, F1, partition shape, nesting, whether a CAS synonym matched |
| the **semantic** relation — whether the labels mean the same thing | **this subagent** | the paper's own definition of its label, quoted |

The set relation is already computed by `subatlas_scoring` and carried on
`subatlas_read_plan.json`. The subagent must be **given** it and must not recompute it —
re-deriving arithmetic from a suggestive label string is the specific failure the
contributors module was written to prevent.

So the question is:

> This paper assigned `<n>` cells to its own population `<compared_label>`, which the
> atlas calls `<atlas label>`. That is `<overlap_shape>` overlap at purity `<p>`, and
> `<compared_label>` accounts for `<f>` of this paper's population.
>
> From this paper's text: what does `<compared_label>` denote — definition, markers,
> location, quoted? What was it distinguished *from*? What were its differential
> expression results computed against? Is it the same population as `<atlas label>`,
> broader, narrower, a different partition, or in contradiction?

**The output records both relations and whether they agree**, because the disagreement is
the finding:

| set relation | semantic relation | reading |
|---|---|---|
| 1:1 | equivalent | exact — good, uninteresting |
| nested | broader | resolution difference. Expected. *Not* corroboration |
| **1:1** | **different concept** | **relabelling — the interesting case** |
| spans / splits | equivalent | the atlas lumped or split against this study's partition |
| any | contradictory definition | genuine contradiction: report loudest |

Two distinctions to carry through: **consistent is not supporting** — a study that called
all its cells "endothelial cell" agrees with an atlas venous subtype the way it agrees
with anything. And **unreachable is not disagreeing** — where the paper's own words were
never read, confidence is low and no definition may be asserted.

### 2c. Per-cell-type questions — the six dimensions

The flagging agent already commits us to six, and they are the right six:

| dimension | question |
|---|---|
| `names` | answered at 2a |
| `hierarchy` | What broader class does this paper place the population in, and what does it subdivide it into? |
| `location` | Where is it found — tissue, compartment, developmental stage — and **how was that established**: imaging, spatial data, or reported from elsewhere? |
| `markers` | Which genes does this paper name as characterising it? Quote the sentence. **If the marker set is attributed to earlier work rather than derived here, say so and name the reference.** |
| `structure` | Any description of its morphology. |
| `function` | What is it said to do, and on what basis? |

`hierarchy` has no home in the report structure as #47 currently specifies it — see §4.

Contract for every answer, unchanged and validated: answer only from the supplied text;
quote verbatim, one continuous run, never spliced; `found: false` where the text does not
answer, which is a correct and expected outcome.

---

## 3. Output

One array of evidence records per #46 — `answer` as model prose, `quotes` as verbatim
source text, `source_paper.role`, `retrieval_method`, `cited_sentence`, `supports`
(identity / characterisation / both).

Plus two record kinds specific to the stages above:

- a **grounding record** per subject: accepted forms with spans, rejected candidates with
  the reason, and a confidence
- a **transfer record** per (atlas cell set, subatlas cell set): the set relation as
  given, the semantic relation as judged, whether they agree, the quoted upstream
  definition, and an evidence status saying whether the paper's own words were read

Marker records get their per-gene rows **after** this read, from the deterministic table
lookup, using the candidate genes this stage surfaced.

---

## 4. Consequences for #47

1. **`hierarchy` is a sixth dimension with no section.** It bears on identity and on
   Cell Ontology mapping — where the paper places a population in its own lineage is
   evidence about what the population is. Either it joins the `Identity and prior
   characterisation` section or it earns a line in the header alongside the CL mapping.
2. **Grounding output drives the report title.** The title should be the name the authors
   use in running prose, which is a 2a output, not the CAS+ label. The existing
   `LYVE1++` / `LYVE1+` case is exactly this.
3. **Rejected synonyms should survive into the record**, even though they never appear in
   the report. They are the guard against a later run re-accepting them.
4. The four questions #47 specifies for a disagreeing study are right, and are now
   §2b — but they must be asked **with the set statistics supplied**, not from the label
   alone.
