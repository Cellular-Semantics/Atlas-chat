# What the existing reports actually contain

**August 2026.** A read-only audit of every report we have already generated, scored
against the output requirements in `docs/functional_spec.md`. No new runs, no API calls,
no code changes — the point is to find out where the pipeline falls short before deciding
what to build or test next.

The spec sentence this is aimed at:

> When requested, for each annotation, generate a report with full names, synonyms,
> markers, location, structure function + attempted mapping to CL. Use the atlas paper +
> subatlas papers + their citations as preferred source, opening out to free literature
> search if needed.

That gives three questions: is each named aspect covered; did the evidence come from the
preferred sources in the preferred order; and is the evidence in the right biological
context (with the mismatch stated when it isn't).

## The corpus

| Project | Reports | Generated | Evidence dirs |
|---|---|---|---|
| `fetal_skin_atlas` | 159 | April 2026 | 130 |
| `HDCA_neurons` | 24 | May 2026 | 16 |
| `HCA_reproductive_atlas_v1` | 2 | August 2026 | 2 |

185 reports in total. All three predate the evidence provenance tagging added in #12/#15
(merged 14 Aug) — the reproductive atlas missed it by two days. That limits what can be
said about source discipline; see finding 4.

---

## 1. The honest-absence path is never taken

Not one report in 185 says "no evidence found". The synthesizer prompt requires it when
evidence is lacking, and the spec requires every assertion drawn from the literature to
carry a supporting quote. What happens instead is that thin sections get filled with
unsourced prose.

Counting substantive sections (30+ words) that contain **no quote and no inline citation**:

| Aspect | `fetal_skin_atlas` | `HDCA_neurons` |
|---|---|---|
| Markers | 27/145 (19%) | 0/24 |
| Location | 59/142 (42%) | 0/24 |
| Function | 52/153 (34%) | 0/12 |
| Structure | 20/22 (91%) | 0/6 |
| **Reports with at least one** | **95/159 (60%)** | **0/24** |

`Melanoblasts_organoid` is the clean example. Its Markers section reads:

> Melanoblasts are characterised by expression of melanocyte lineage transcription factors
> (MITF, SOX10) and neural crest markers, while lacking full expression of melanin
> biosynthesis enzymes (TYR, TYRP1, DCT) that define mature melanocytes.

No quote, no citation, no reference section anywhere in the report. Location and Function
are the same. The one blockquote in the whole report is about organoid differentiation
timing, not about melanoblasts. Every gene symbol there came from the model, not from a
source.

This matters more than any retrieval question. A report with unsourced sections looks
complete, so nothing downstream — not the validator, not a reader skimming — registers
that the evidence was never found. Absence and sufficiency are indistinguishable in the
current output.

## 2. Sourcing tracks evidence volume

The same corpus, grouped by how much evidence the traversal actually collected:

| Evidence collected | Reports | Mean unsourced sections |
|---|---|---|
| No evidence file at all | 29 | 1.83 |
| 1-2 summaries | 60 | 1.10 |
| 3-5 summaries | 44 | 0.68 |
| 6+ summaries | 26 | 0.35 |

Monotonic, and it does not reach zero even at the top. So this is two problems, not one:
retrieval doesn't return enough, *and* synthesis papers over the gap instead of declaring
it. Fixing only the first would leave the second in place — and the second is much cheaper
to fix.

## 3. The two corpora are not comparable, and the roadmap has the reference set wrong

| | `fetal_skin_atlas` | `HDCA_neurons` |
|---|---|---|
| Median evidence summaries | 3 | 9 |
| Median distinct source papers | 2 | 9 |
| Median blockquotes per report | 3 | 12 |
| Median references | 3 | 13 |
| Median words | 643 | 2024 |
| Reports resting on a single source | 51/130 (39%) | 0/16 |
| Reports with unsourced sections | 95/159 | 0/24 |

`ROADMAP.md` §9 names the April 2026 fetal-skin reports as "the quality bar". On these
numbers that is wrong. The fetal-skin corpus is broad but mostly thin, with a good tail of
around 25 rich reports; the HDCA neuron set is uniformly well-sourced. If we want a
reference corpus, it is the HDCA set plus that fetal-skin tail — not the fetal-skin corpus
as a whole. Any gold-passage work should be drawn accordingly.

## 4. Source discipline is not measurable from what we have

No evidence file in any of the three projects carries `source_paper.role` or
`retrieval_method`. Partial recovery is possible from `paper_catalogue.json`, which some
runs tagged ad hoc — 67 of 159 fetal-skin reports have any tag at all, and the vocabulary
drifted across eight spellings (`atlas`, `atlas_paper`, `atlas_source`, `primary_atlas`,
`seed_paper`, `citation_traverse`, `free_search`, `snippet_search`). Normalising those:

- atlas 80, traversed citation 267, free search 34 — free search around 9% where tagged.

That is the only quantitative statement available, over 42% of one project. The
distinction the spec cares about — did we open out to free search *because the preferred
sources were exhausted*, or because traversal failed to reach what was there — is not
recoverable at all, because both look identical once the tag is missing.

The same drift shows up in the evidence files themselves: seven different JSON shapes
across `all_summaries.json`, with at least three vocabularies for "which paper did this
come from" (`source_corpus_id`, `corpusId`, `doi`, a nested `paper` object). This is what
the schema-plus-hook regime introduced later was for; the corpora simply predate it.

**Consequence for the plan:** measuring source discipline needs a small instrumented
re-run on the current pipeline. It cannot be done retrospectively.

## 5. Subatlas-derived annotations are underserved

Splitting the fetal-skin reports by where the annotation came from:

| Annotation origin | Reports | Mean summaries | Mean unsourced sections |
|---|---|---|---|
| Prenatal skin (the atlas itself) | 128 | 3.0 | 0.93 |
| Skin organoid (Lee 2020, a subatlas) | 31 | 1.4 | 1.26 |

Annotations inherited from a contributing study get less than half the evidence and more
unsourced prose. That is the spec's source preference failing at the seed: traversal was
run from the atlas paper, and the subatlas paper that actually defines those cell types
was never used as a starting point. `resolve-name` on `dev` now identifies the source
paper and CAS+ carries `transferred_annotations`, so the information needed to fix this
exists — it just isn't driving where traversal starts.

## 6. Aspect coverage

Headings are nearly always present; content behind them is the issue.

- **Markers, location, function** — a section exists in 99-100% of reports, but see
  finding 1 for how many are unsourced.
- **Structure / morphology** — present in 22 of 159 fetal-skin reports (14%) and 6 of 24
  HDCA reports, and 91% of the fetal-skin ones are unsourced. Effectively uncovered.
- **Synonyms** — explicit synonym language appears in 6-8% of reports. The spec asks for
  full names *and* synonyms per annotation; CAS+ has a `synonyms` field, and the
  query-decomposer branch already unions CAS synonyms with paper-found names, but nothing
  currently reports them as an output.
- **CL mapping** — present in 100% of fetal-skin and HDCA reports (broad 103 / exact 50 /
  one "no term" for fetal skin). This is the best-covered requirement in the spec.

## 7. Reference grounding

Checking every DOI cited in a report against every evidence file for that cell type:

- `fetal_skin_atlas` — 24 of 494 cited DOIs (5%) appear in no evidence file, across 9
  reports.
- `HDCA_neurons` — 65 of 138 (47%), concentrated in five reports. The `DL*_NEURON` series
  is the worst: `DL2_NEURON` cites 21 DOIs of which 18 have no evidence trail.

Some of this is bookkeeping rather than fabrication — evidence files were not always
written for every report — but a reference with no evidence trail is indistinguishable
from a fabricated one, which is the point of the check.

## 8. Context match — not adequately measurable here

Off-context cues (adult, mouse, blood, tumour, in vitro) appear a median of 4-5 times per
report, against a median of 1-3 explicit context-flagging phrases. Only one report has
many off-context cues and no flagging at all. Reading a sample, the good reports do flag
it well — `ASDC` separates "prenatal skin" from "blood and lymphoid organs" and "inflamed
tissues" into distinct subsections, which is exactly what the spec asks for.

But keyword counting cannot tell whether a specific claim was properly qualified, and no
evidence file records the organism, stage or tissue of the source paper, so there is
nothing to compare the annotation's context against. Judging this properly needs either
hand adjudication on a sample or context tagging on the evidence — probably both.

---

## What this suggests for the order of work

The retrieval matrix was going to be first. On this evidence it should not be.

1. **Make absence explicit and enforceable.** A section with substantive prose and no
   quote or citation should fail validation, and "no evidence found" should be the
   required alternative. This is the largest single quality gap (60% of the fetal-skin
   corpus), it is cheap, and it needs no retrieval work at all. It also makes every later
   measurement honest: once absence is declared rather than papered over, coverage becomes
   directly countable instead of inferred.
2. **Seed traversal from the subatlas paper** where the annotation came from. Finding 5 is
   a source-order failure, not a retrieval-quality failure, and the data to fix it is
   already in CAS+.
3. **Instrumented re-run on a small set** — 10-20 cell types on the current pipeline, with
   provenance tags present, to get the source-discipline numbers that finding 4 says
   cannot be recovered retrospectively. This is also what tells us whether free search is
   a last resort or a symptom.
4. **Then the retrieval matrix**, aimed at whatever the re-run shows to be genuinely
   missing rather than at retrieval quality in the abstract.

Reference corpus for any of this: the HDCA neuron set plus the ~25 well-sourced
fetal-skin reports, not the fetal-skin corpus as a whole.

---

## How this was measured, and what it doesn't tell you

Scoring was regex over the committed markdown and JSON — section detection, blockquote and
inline-citation counting, DOI extraction, evidence-file parsing across the seven shapes
found. Numbers to treat with care:

- "Unsourced" means no blockquote and no `(Author, Year)` in that section. A section
  citing a source in prose without parentheses would be miscounted. Spot-checked against
  hand-read reports; two counting bugs were found and fixed during the audit (indented
  blockquotes under bullets, and a nested `{"papers": {...}}` catalogue shape), both of
  which had inflated the failure counts before correction.
- Nothing here judges whether a claim is *true*, whether a quote is faithful to its
  source, or whether the retrieval could have found something better. Quotes were not
  re-validated against source text.
- Context match (finding 8) is the weakest measure in this document and should be treated
  as "not yet assessed" rather than "assessed and adequate".

The scoring script is in the session scratchpad, not the repo — it is throwaway analysis,
not a validator. If any of these become recurring measures they belong in
`validation/` with tests.
