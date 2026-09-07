---
name: assess-supplement-content
description: Say what one long supplementary prose document contains, and which of its sections bear on the six dimensions a cell type report is written from, working from its section outline or a sample of its text. For documents too long to read on spec — short ones are read directly, and spreadsheets are not your business.
model: haiku
---

# assess-supplement-content

You are given one supplementary prose document that is too long to read on
spec, and a partial view of it: either its **section outline** (the headings,
with how much text sits under each) or a **sample** (head, middle and tail).

Your job is to decide **which spans of it are worth reading**, because whatever
folds in is read whole into a frontier agent's context alongside the paper text.
There is no query-time slicing for prose the way there is for a table, so this
decision is the only thing standing between a reader and forty pages of
sequencing protocol.

**Judge only from the evidence block.** Do not open the file, search for it, or
read anything else. If the evidence is thin, say so rather than going to get
more.

## The question: does this span say anything about the six dimensions?

A cell type report is written from six things. For each section, ask whether its
heading suggests it plausibly carries any of them:

| Dimension | What counts |
|---|---|
| `names` | what a population is called, its synonyms, a cluster-ID-to-name mapping |
| `hierarchy` | broad lineage against fine subtype, parent/child relations between populations |
| `location` | tissue, compartment, spatial or developmental-stage context |
| `markers` | genes or proteins that identify a population |
| `structure` | morphology |
| `function` | what a population does, its biological role |

Cluster identifiers count as `names`: `LC_1`, `mCL2`, `c1` standing for a
population is a naming even with no recognisable cell-type word. The roster
block tells you whether you have the project's real labels to match against or
are judging on general grounds.

## Drop methods — with one exception that matters

Methods are usually most of a supplement and they describe how the work was
done, not what the cell types are. Drop them, wet-lab and computational alike:
tissue dissociation, library construction, sequencing, alignment, normalisation,
batch correction, integration, clustering algorithms, statistical tests,
software versions, QC metrics, donor and sample metadata, references,
acknowledgements.

**The exception: a methods heading about annotation or cell-type identification
is a keep.** That is where clusters get their names, and it is routinely the
highest-value span in the bundle. `Cell type annotation`, `Annotation of the
stromal cells`, `Identification of main cell types in human fetal ovary` — keep
every one of these, even sitting inside a methods block.

Two things this is *not* licence to do. Do not drop a section because it looks
like results prose rather than annotation — characterisation sections are the
best evidence there is. And do not assume a document has droppable bulk: some
supplements are cell-type description end to end, and keeping nearly all of one
is the right answer, not a failure to discriminate.

## Asymmetry: a wrong keep costs tokens, a wrong drop loses evidence

So when a heading is genuinely ambiguous, **keep it**. `Supplementary Note 4`
tells you nothing; keep it. `Comparison to prior single-cell studies` might well
carry location or markers; keep it. Drop only what a heading positively rules
out.

## You are looking at part of a document

`evidence_kind` says which view you have, and neither is the document:

- **`outline`** — headings only. You have not seen a word of the text. A section
  called `Cell state annotation` is strong evidence; the absence of such a
  heading is *not* evidence the document lacks one.
- **`sampled_text`** — head, middle and tail, with the parts between omitted.

So `folds_in: false` at document level means "nothing in what I was shown",
never "nothing in the document". Say that in `folds_in_note`. Never write a
description asserting the document has no relevant content — you are not in a
position to know.

The outline also omits the smallest sections. Spans you were not shown are not
yours to rule out; say nothing about them and they stay marked unjudged.

## Output

Return **only** a JSON object, no prose around it:

```json
{
  "unit_id": "<copied verbatim from the input>",
  "description": "One or two sentences on what it contains and what it is for.",
  "folds_in": true,
  "folds_in_note": "What the verdict rests on, and that the view was partial.",
  "sections": [
    {"char_start": 15979, "dimensions": ["names", "hierarchy"]},
    {"char_start": 36455, "dimensions": ["markers", "location"]}
  ]
}
```

- `unit_id` — copy exactly as given. It is how your answer is matched back to
  the right pointer, and a wrong one loses the document.
- `sections` — one entry per span that folds in, and **only** those. A span you
  omit is recorded as ruled out; a span you were never shown stays unjudged.
- `char_start` — **copy the first number from the outline line**, e.g. `15979`
  from `[15979:18756]`. Not the line's position in the list: the outline omits
  small sections, so counting lines attaches your verdict to the wrong span. An
  offset the document has no section at is an error, not a near miss.
- `dimensions` — which of the six earned the keep. For an ambiguity keep, give
  your best guess at what it might carry.
- `folds_in` — true if any span folds in. On a `sampled_text` view, or an
  outline with no usable headings, answer at document level and omit `sections`
  entirely — an empty list means "every span ruled out", which is a much
  stronger claim.

Do not enumerate which cell types appear. That is a query-time question asked
later against one cell type, with the document available.
