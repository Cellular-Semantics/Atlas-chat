# Mock-up: questions → evidence records → report section

Worked end to end on one real cell type, with real numbers, to make #46 and #47
judgeable. Nothing here is invented: the statistics come from Supplementary Table 22 of
Gopee et al. (2024), read out of the supplement store; the historical-marker quote is
from a paper the existing pipeline actually surfaced.

**Subject.** Atlas annotation `LYVE1++ macrophage` (the atlas prose says `LYVE1+`),
Gopee et al. 2024, prenatal human skin.

---

## 1. What each paper is asked

Three different reads, three different question sets. All share the same contract:
answer only from the supplied text, quote verbatim, decline when the text does not
answer.

### 1a. The atlas paper — batched over many cell types

> For each subject below, answer these questions from the supplied paper text and
> figure legends only.
>
> 1. **Markers.** Which genes does this paper name as characterising the subject?
>    Quote the sentence. If the paper attributes the marker set to earlier work rather
>    than deriving it here, say so and name the reference.
> 2. **Location.** Where in the tissue is the subject found, and how was that
>    established — imaging, spatial transcriptomics, or reported from elsewhere?
> 3. **Structure.** Any description of the subject's morphology.
> 4. **Function.** What is the subject said to do, and on what basis?
>
> For each: quote verbatim, or set `found: false`. Declining is correct and expected.

### 1b. A differential-expression table — a lookup, not a read

Not a model question at all. Given candidate gene symbols, query the table and return
what is there. **The table's own header states the comparison, in the authors' words**,
so it travels with the numbers:

> "DEG analysis for macrophage subpopulations (computed for each macrophage
> subpopulation vs rest of myeloid cells)"
> — Gopee et al. (2024), Supplementary Table 22, sheet header

Candidates come from three places: the atlas annotation's own marker field, genes the
atlas prose asserts, and genes prior literature associates with this cell type.

### 1c. A contributing study that used a different label

Asked once per subatlas cell set, not per atlas cell set:

> 1. What does your label `<compared_label>` denote? Definition, markers, location — quoted.
> 2. What did you distinguish it *from*? Name the alternatives it was separated from.
> 3. What were your differential-expression results computed against?
> 4. Is your label a superset, a subset, or a different partition of `<atlas label>`?

---

## 2. What comes back

### 2a. A prose record (location) — unchanged in shape from today

```json
{
  "cell_label": "LYVE1++ macrophage",
  "aspect": "location",
  "found": true,
  "answer": "Co-located dermally with WNT2+ fibroblasts and adjacent to CD31+ endothelial cells; established by multiplex RNAscope and immunofluorescence, not inferred.",
  "quotes": [
    "Consistent with this finding, multiplex RNAscope and immunofluorescence staining showed LYVE1+ and TML macrophages in close proximity to endothelial cells (Fig. 4a and Supplementary Video 1)."
  ],
  "source_paper": { "role": "atlas", "doi": "10.1038/s41586-024-08002-x" },
  "retrieval_method": "full_text",
  "cited_sentence": false,
  "supports": ["characterisation", "identity"]
}
```

`answer` is model prose. `quotes` is verbatim source text. **Only `quotes` is ever
matched against a report blockquote** — the separation that #43's `s["summary"]` finding
showed has to be structural.

`supports: ["characterisation", "identity"]` — location does both. For a classically
defined cell type, position is part of the definition.

### 2b. A marker record — where structure earns its place

```json
{
  "cell_label": "LYVE1++ macrophage",
  "aspect": "markers",
  "found": true,
  "source_paper": { "role": "atlas", "doi": "10.1038/s41586-024-08002-x" },
  "retrieval_method": "supplement_table",
  "locator": "Supplementary Table 22, Sheet1",
  "comparison": "DEG analysis for macrophage subpopulations (computed for each macrophage subpopulation vs rest of myeloid cells)",
  "comparison_is_author_text": true,
  "n_genes_reported": 550,
  "genes": [
    { "symbol": "LYVE1",   "rank": 3,  "score": 147.04, "log2fc": 4.28, "padj": 0.0 },
    { "symbol": "F13A1",   "rank": 5,  "score": 145.05, "log2fc": 3.90, "padj": 0.0 },
    { "symbol": "FOLR2",   "rank": 9,  "score": 129.45, "log2fc": 3.17, "padj": 0.0 },
    { "symbol": "MRC1",    "rank": 14, "score": 120.97, "log2fc": 3.01, "padj": 0.0 },
    { "symbol": "STAB1",   "rank": 18, "score": 115.76, "log2fc": 2.68, "padj": 0.0 },
    { "symbol": "CD163",   "rank": 36, "score": 92.19,  "log2fc": 2.20, "padj": 0.0 },
    { "symbol": "TIMD4",   "rank": 58, "score": 71.31,  "log2fc": 3.73, "padj": 0.0 },
    { "symbol": "SLC40A1", "rank": null, "absent": true }
  ]
}
```

Every number above is real, read from the store.

### 2c. A historical-marker record

```json
{
  "cell_label": "LYVE1++ macrophage",
  "aspect": "markers",
  "found": true,
  "answer": "A five-gene core signature reported for yolk-sac-derived tissue macrophages.",
  "quotes": [
    "CD163 + MRC1 + macrophages thus expressed the core signature (CD163, MRC1, F13A1, FOLR2, and LYVE1) of macrophages isolated from the embryonic yolk sac as well as yolk-sac-derived macrophages in adult human tissues (Dick et al., 2022)."
  ],
  "source_paper": { "role": "external", "doi": "10.1084/jem.20230675" },
  "retrieval_method": "free_search",
  "cited_sentence": true,
  "context_mismatch": "adult human dorsal root ganglia",
  "asserted_genes": ["CD163", "MRC1", "F13A1", "FOLR2", "LYVE1"],
  "supports": ["identity"]
}
```

---

## 3. The one place structure is genuinely needed

**The consistency question is a join over gene symbol**, across three sources:

| gene | measured here (rank / log2FC) | asserted by atlas authors | reported previously |
|---|---|---|---|
| LYVE1 | 3 / 4.28 | yes | yes (Lund et al.) |
| F13A1 | 5 / 3.90 | — | yes |
| FOLR2 | 9 / 3.17 | — | yes |
| MRC1 | 14 / 3.01 | — | yes |
| STAB1 | 18 / 2.68 | — | — |
| CD163 | **36** / 2.20 | — | yes |
| TIMD4 | 58 / 3.73 | — | — |
| SLC40A1 | **not in 550** | — | — |

Three things this table shows that free prose would not reliably deliver:

1. **All five previously reported signature genes are confirmed here** — a complete,
   checkable consistency finding. In prose across ~20 records, a model completing a
   five-row join by narrative has no obligation to report the row it missed. The same
   argument as #34's "a verdict for every contributor": structure makes silence visible.
2. **Two of the five sit outside any top-20 cut** — CD163 at rank 36, and TIMD4 at 58.
   Reading markers off the top of the list loses them. This is the concrete case for
   looking candidates up rather than taking the head of the table.
3. **`SLC40A1` is absent, and that absence means nothing.** SLC40A1 is the
   *iron-recycling* macrophage's marker; the comparison here is against the rest of the
   myeloid cells, which includes iron-recycling macrophages. Reported without its
   comparison, "SLC40A1 is absent from LYVE1+ macrophages" reads as a finding. Reported
   with it, it is a non-result.

**So: a minimal per-gene row, for markers only.** Structure and function stay prose —
this is a join key over a shared identifier for an inherently tabular comparison, not a
controlled vocabulary for experimental method.

**On evidence vs assertion:** outside markers, the existing fields carry it
(`source_paper.role`, `retrieval_method`, `cited_sentence`) and prose does the rest.
Inside markers it is a column of the join, above, rather than a separate taxonomy.

---

## 4. What the report says

> ## Markers
>
> Differential expression against the remaining myeloid cells identifies a marker set
> led by DAB2, RNASE1, LYVE1, SELENOP and F13A1 (Gopee et al., 2024 [atlas],
> Supplementary Table 22, 550 genes reported):
>
> > "DEG analysis for macrophage subpopulations (computed for each macrophage
> > subpopulation vs rest of myeloid cells)"
> >
> > — Gopee et al. (2024), Supplementary Table 22
>
> This set is consistent with previously reported markers of yolk-sac-derived tissue
> macrophages. Lund et al. (2024) [free literature search], working in adult human
> dorsal root ganglia rather than prenatal skin, describe a five-gene core signature —
> CD163, MRC1, F13A1, FOLR2 and LYVE1 — of which all five are significantly enriched
> here (ranks 36, 14, 5, 9 and 3 of 550; log2FC 2.2–4.3, adjusted P < 0.001 throughout):
>
> > "CD163 + MRC1 + macrophages thus expressed the core signature (CD163, MRC1, F13A1,
> > FOLR2, and LYVE1) of macrophages isolated from the embryonic yolk sac as well as
> > yolk-sac-derived macrophages in adult human tissues (Dick et al., 2022)."
> >
> > — Lund et al. (2024)
>
> Several of these markers point forward to the cell's location and function. MRC1
> (CD206), STAB1 and FOLR2 are receptors characteristic of perivascular tissue-resident
> macrophages, consistent with the perivascular position described below.
>
> ## References
>
> - Gopee NH et al. (2024). "A prenatal skin atlas…". *Nature*. DOI: … — **atlas paper**
> - Suo C et al. (2022). "Mapping the developing human immune system…". *Science*. DOI: … — **subatlas paper**
> - Lund H et al. (2024). "CD163+ macrophages monitor…". *J Exp Med*. DOI: … — **free literature search**

Compare with the current output, which lists the top twelve genes by rank with no
statistics, no comparison, and the source class written into the prose as
"(free literature search)".

---

## 5. Summary of the change to #46

- **Add** a per-gene row on marker records: symbol, the statistics as reported, and
  whether the gene was looked for and not found. Plus, on the record, the comparison as
  author text and the number of genes reported.
- **Do not add** an evidence-type key outside markers.
- Everything else in #46 as written.
