# Retrieval test items — draft for review

**57 candidate items** (47 in the main set, 10 in the abstraction addendum at the end) drawn from two papers that are available as JATS-XML:

- **Atlas** — Gopee et al. 2024, *A prenatal skin atlas…* (`10.1038/s41586-024-08002-x`, PMC11578897)
- **Subatlas** — Suo et al. 2022, *Mapping the developing human immune system across organs*
  (`10.1126/science.abo0510`, PMC7612819). Cited by the atlas, and the source of its
  macrophage subset comparisons.

Reynolds 2021 and Lee 2020 — the other two subatlas papers — have PMC records but
Europe PMC serves no XML for either (404). Same pattern the supplement study found: a PMC
record is not full text.

## How these were chosen

Items were found by **reading**, not by searching. Every attributed claim in each paper was
enumerated exhaustively via the JATS citation parser (134 cited sentences in the atlas, 89
in Suo) and read through; uncited findings sentences were pulled section by section. No
query was run against either paper to find an item. That matters — if items are located
with ASTA, ASTA wins the comparison by construction.

## What to do with this

For each item: **approve**, **cut**, or **reword**. Worth cutting an item if:

- the answer is arguable, or depends on interpretation
- the span doesn't really answer the question on its own
- it's so easy that every method will get it (a couple of these are deliberate, as a floor)
- for D items: the claim could reasonably be attributed to a different reference

Aim is roughly 30 survivors. Levels are deliberately uneven — D (citation-following) is
over-weighted because it's the one the spec's source ordering actually rests on.

**Spans are verbatim** from the JATS body text, trimmed at clean boundaries. Superscript
reference markers appear inline as digits (e.g. `PCW3`) — that's how they sit in the text.

---

## A. Literal lookup — the answer is stated in one sentence

*Floor cases. Any method that misses these is broken.*

**A1.** When do prenatal hair follicles start forming?
**A.** Between 11 and 14 post-conception weeks.
**Where.** Gopee · Main
**Span.** "Prenatal HFs start forming between 11 and 14 post-conception weeks (PCW)"

**A2.** At what age does prenatal human skin lose the ability to heal without scarring?
**A.** After 24 PCW.
**Where.** Gopee · Scarless healing and potential macrophage contribution
**Span.** "Prenatal human skin is able to heal without scarring but loses this capacity after 24 PCW"

**A3.** How early do macrophages seed prenatal skin?
**A.** As early as 6 PCW.
**Where.** Gopee · Main
**Span.** "immune cells such as macrophages seed the skin as early as 6 PCW and express a range of pro-inflammatory genes"

**A4.** When do sebaceous and apocrine gland cells mature?
**A.** After 16 PCW — and they were not captured at the stages sampled.
**Where.** Gopee · Epidermal placode and matrix formation
**Span.** "Sebaceous and apocrine gland cells, which mature after 16 PCW, were not captured at these stages."

**A5.** Which markers define the dermal papilla (Dp) as it forms?
**A.** NDP+, SOX2+.
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "the Dc becomes encapsulated at its base as the Dp (NDP+, SOX2+)"

**A6.** What developmental window does the Suo atlas cover, and which organs?
**A.** Weeks 4–17 post-conception; yolk sac, prenatal spleen and skin generated, plus six further organs integrated.
**Where.** Suo · Main
**Span.** "We generated single-cell RNA sequencing (scRNA-seq) data from yolk sac, prenatal spleen, and skin, and integrated publicly available cell atlases of six additional organs, spanning weeks 4 to 17 post-conception"

**A7.** Which markers were highest in the putative prenatal B1 cells?
**A.** CD5, CD27, SPN (CD43), plus CCR10.
**Where.** Suo · Identification of putative prenatal B1 cells
**Span.** "These putative B1 cells had the highest expression of CD5, CD27, and SPN(CD43), consistent with previously reported markers"

---

## B. Located fact — needs the right passage, one hop of reading

**B1.** Where are Treg cells found in prenatal skin, and from what age?
**A.** Within and around hair follicles rather than interfollicular skin, from 15 PCW.
**Where.** Gopee · Epidermal placode and matrix formation
**Span.** "RNAscope (FOXP3+) and immunofluorescence staining (FOXP3+) showed that Treg cells were primarily located within and around HFs compared to interfollicular skin as early as 15 PCW"

**B2.** Which cell types do macrophages co-locate with in prenatal skin?
**A.** Endothelial and neural cells, in the early and late neurovascular microenvironments (ME1, ME5).
**Where.** Gopee · Single-cell atlas of human prenatal skin
**Span.** "Macrophages co-located with endothelial and neural cells in 'early and late neurovascular microenvironments' (ME1 and ME5, respectively)"

**B3.** What does the atlas say TML macrophages co-locate with, besides endothelium?
**A.** Schwann cells, in the early neurovascular microenvironment (ME1).
**Where.** Gopee · Macrophages in cutaneous neural differentiation
**Span.** "TML macrophages were also predicted to co-locate with Schwann cells in prenatal skin ('early neurovascular microenvironment', ME1)"

**B4.** Which gene newly identified in DPYSL2+ basal cells is upregulated along the ORS/CL trajectory?
**A.** AGR2 (alongside previously reported BARX2 and SOX9).
**Where.** Gopee · Epidermal placode and matrix formation
**Span.** "we identified new genes upregulated by DPYSL2+ basal cells, such as AGR2, and previously reported genes related to ORS differentiation (BARX2 and SOX9)"

**B5.** Which genes are expressed as pre-Dc cells aggregate into the dermal condensate?
**A.** COL6A3, MFAP4, PTK7 — collagen fibril formation and cell adhesion.
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "Genes implicated in collagen fibril formation and cell adhesion (COL6A3, MFAP4 and PTK7) were expressed as the pre-Dc cells aggregated into the Dc"

**B6.** Which ligand–receptor pair is proposed to drive pre-Dc migration, and which cells express each side?
**A.** CXCL12 on pre-Dc cells interacting with ACKR3 on epidermal basal cells.
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "Receptor–ligand analysis predicted interactions between CXCL12 expressed by pre-Dc cells (Extended Data Fig. 4g,h) with ACKR3 on epidermal basal cells"

**B7.** Where were B cell progenitors localised in the Suo atlas?
**A.** Gut submucosa, and thymus-associated tissue.
**Where.** Suo · System-wide blood and immune cell development
**Span.** "found B cell progenitors were localized in the submucosa of the gut, in thymus-assoc"
*(span truncated in source dump — needs re-reading in full before approval)*

---

## C. Within-paper synthesis — needs two or more passages

**C1.** What is the evidence that prenatal skin fibroblasts acquire scar-promoting properties later in gestation?
**A.** Prenatal fibroblasts upregulate immune-suppression and regeneration genes (CD200, RAMP2, MDK) relative to adult; pro-inflammatory fibroblast genes (APOE, IGFBP7, ITM2A) rise in the HOXC5+ → PEAR1+ transition; WNT2+ and PEAR1+ fibroblasts express senescence, cytokine and collagen genes (CDKN1A, IL1R1, POSTN).
**Where.** Gopee · Scarless healing — three passages

**C2.** Why does the atlas argue antigen presentation is not a key early macrophage function?
**A.** Macrophages express pro-inflammatory genes from 6 PCW but MHC class II genes are decoupled from these before 11 PCW.
**Where.** Gopee · Main — two adjacent passages

**C3.** On what grounds are prenatal skin TML macrophages linked to microglia?
**A.** Shared expression profile (P2RY12, CX3CR1, OLFML3) with microglia-like macrophages of other developing organs, plus high correlation with embryonic brain microglia and co-expression of immune-inhibitory genes.
**Where.** Gopee · Scarless healing — two passages

**C4.** What evidence suggests the papillary/reticular fibroblast distinction emerges later in humans than in mice?
**A.** In mice the split is reported by ~e12.5; human prenatal fibroblasts did not significantly express papillary markers such as COL13A1.
**Where.** Gopee · HF mesenchymal differentiation — two passages

**C5.** How does the atlas support the claim that macrophages promote vascular network formation?
**A.** Predicted reciprocal macrophage–endothelial interactions; comparison with a blood vessel organoid lacking immune cells showing limited vasculature; NicheNet identifying macrophage VEGFA as a top upstream ligand for GATA2 differences.
**Where.** Gopee · Macrophages support prenatal skin angiogenesis — three passages

---

## D. Citation-following — which reference backs the claim, and what did it show

*Two parts each: (i) surface the right reference from the citing sentence; (ii) find the
supporting passage inside that reference. Part (ii) is only testable where the cited paper
is itself retrievable — noted per item.*

**D1.** The atlas says macrophages seed skin by 6 PCW with MHCII decoupled before 11 PCW. Which paper is that from?
**Cites.** Suo 2022 — `10.1126/science.abo0510` *(retrievable — part ii testable)*
**Where.** Gopee · Main

**D2.** Which paper provides the hair-bearing skin organoid model the atlas uses for validation?
**Cites.** Lee 2020 — `10.1038/s41586-020-2352-3` *(no served XML — part i only)*
**Where.** Gopee · Main

**D3.** Which datasets does the atlas leverage for adult skin and adult hair follicle comparison?
**Cites.** Reynolds 2021 — `10.1126/science.aba6500`; Takahashi 2020 — `10.1016/j.jid.2019.07.726`
**Where.** Gopee · Main

**D4.** The claim that prenatal skin interfaces with amniotic fluid in a sterile environment — attributed to whom?
**Cites.** Kennedy 2023 — `10.1038/s41586-022-05546-8`
**Where.** Gopee · Main

**D5.** Which references support Treg cells localising around the hair follicle in late second trimester and postnatal skin?
**Cites.** Ali 2017 — `10.1016/j.cell.2017.05.002`; Dhariwala 2020 — `10.1016/j.xcrm.2020.100132`
**Where.** Gopee · Epidermal placode and matrix formation

**D6.** Which paper is the source for the claim that prenatal skin loses scarless healing after 24 PCW?
**Cites.** Larson 2010 — `10.1097/PRS.0b013e3181eae781`
**Where.** Gopee · Scarless healing

**D7.** Which reference backs the role of macrophages in wound healing in postnatal mouse and adult human skin?
**Cites.** Wynn 2016 — `10.1016/j.immuni.2016.02.015`
**Where.** Gopee · Scarless healing

**D8.** Which papers identified the yolk-sac derived TREM2+ macrophages that share a profile with microglia?
**Cites.** Bian 2020 — `10.1038/s41586-020-2316-7`; Goh 2023 — `10.1126/science.add7564`
**Where.** Gopee · Scarless healing
*Note: Goh is abstract-only in ASTA — a deliberate hard case.*

**D9.** Which reference supports macrophages contributing to the skin peripheral nervous system in mouse skin?
**Cites.** Kolter 2020 — `10.4049/jimmunol.1901077`
**Where.** Gopee · Macrophages in cutaneous neural differentiation

**D10.** Which references support macrophage involvement in developmental and cancer-related angiogenesis?
**Cites.** Gu 2022 — `10.1111/febs.15848`; Fantin 2010 — `10.1182/blood-2009-12-257832`
**Where.** Gopee · Macrophages support prenatal skin angiogenesis

**D11.** Which paper reports pro-angiogenic macrophages across diverse human developing tissues?
**Cites.** Wang 2023 — `10.1016/j.cell.2023.08.019`
**Where.** Gopee · Macrophages support prenatal skin angiogenesis
*Note: zero snippets in ASTA in the Aug 2026 run — the hardest case in the set.*

**D12.** Which reference underpins the claim that the papillary/reticular fibroblast split occurs by ~e12.5 in mice?
**Cites.** Driskell 2013 — `10.1038/nature12783`
**Where.** Gopee · HF mesenchymal differentiation

---

## E. Supplement — locating and extracting

*Where markers actually live, and where body-text retrieval should do worst. Split into
locating the right table (the easy half) and pulling values out of it (the real test).*

**Inspect these yourself at:**
`projects/test_projects/fetal_skin_atlas/supplements/papers/10.1038_s41586-024-08002-x/`
— `manifest.json` is the index; the 40 tables are unpacked under `files/…__unpacked/`.
The files are gitignored (373 MB), so they exist locally only; the manifest is committed.

### E-locate

**E1.** Where are the differentially expressed genes for the prenatal skin macrophage subsets (TML, iron-recycling, LYVE1+, MHC-II+)?
**A.** Supplementary Table 22.

**E2.** Which table holds differential expression across all fine-grained cell states in the whole prenatal skin dataset?
**A.** Supplementary Table 3.

**E3.** Which table compares prenatal skin fibroblasts against healthy adult skin fibroblasts?
**A.** Supplementary Table 13.

### E-extract

*All answers below were read directly from Supplementary Table 22. Three things about its
layout, all of which a method has to get right before reading a single gene:*

- *Four merged column blocks (B2:F2, H2:L2, N2:R2, T2:X2), one per subset.*
- *The blocks have **different lengths** — LYVE1+ 550 genes, TML 283, iron-recycling 82,
  MHC-II 41. The sheet is not one rectangular table; sorting it as a whole scrambles every
  block against the others, and row n in one block has nothing to do with row n in another.*
- *Each block is pre-sorted by `scores` descending (verified monotonic), so file order is
  score order. **"Top markers" is therefore ambiguous**: `scores` is the Wilcoxon
  z-statistic and `logfoldchanges` is the effect size, and they give different answers.
  `pvals` is derived from `scores`, so it adds no independent ordering — and it cannot
  rank the top of the list at all, since 128 of the LYVE1+ p-values are exactly 0.
  Every item below states which column it ranks on.*

**E4.** What are the top five differentially expressed genes for LYVE1+ macrophages, ranked by `scores`?
**A.** DAB2, RNASE1, LYVE1, SELENOP, F13A1.

**E5.** What are the top five for TML macrophages, ranked by `scores`?
**A.** C3, RGS1, ITM2B, OLFML3, LINC02712.

**E6.** What are the top five for iron-recycling macrophages, ranked by `scores`?
**A.** CD74, APOC1, CD68, HLA-DPA1, HLA-DMA.
*Note: ranked by `scores` these are MHC class II genes rather than iron-handling genes.
That is an artefact of the ranking column, not a mislabelled block — see E11, where the
same subset ranked by effect size puts VCAM1 second. Worth keeping as a pair with E11.*

**E7.** Where does SLC40A1 (ferroportin) rank among the iron-recycling macrophage DEGs, and with what log fold change?
**A.** Rank 22, log fold change 2.1.
*Requires scanning the block rather than reading the top rows — the identity-defining
marker is not near the top.*

**E8.** Which macrophage subsets have TREM2 in their DEG list?
**A.** TML (rank 15, lfc 4.3) and iron-recycling (rank 11, lfc 3.9). Not LYVE1+ or MHC-II.
*Cross-block — cannot be answered from one column.*

**E9.** What was each macrophage subset compared against in this analysis?
**A.** The rest of the myeloid cells — stated in the table's own title row, not in its column headers.

**E10.** What is the log fold change for OLFML3 in TML macrophages?
**A.** 6.59.

**E11.** What are the top five DEGs for LYVE1+ and for iron-recycling macrophages ranked by `logfoldchanges` rather than `scores`?
**A.** LYVE1+: SPP1, RNASE1, HS3ST2, CCL13, SELENOP. Iron-recycling: APOC1, VCAM1, KCNMA1, APOC2, ABCC3.
*Pairs with E4 and E6. Only RNASE1 and SELENOP survive the change of ranking column for
LYVE1+. Tests whether a method states the basis of its ranking rather than silently
taking file order.*

**E12.** How many genes are listed for each macrophage subset in this table?
**A.** LYVE1+ 550, TML 283, iron-recycling 82, MHC-II 41.
*Tests reading each block's extent — they differ, and a method assuming a rectangular
table will get this wrong or read genes from the wrong subset.*

## F. Absent — the paper does not answer these

*Included to measure whether a method reports absence or invents an answer. A confident
answer here is a worse failure than a miss above.*

**F1.** What is the electrophysiological profile of prenatal skin Merkel cells?
**Expected.** Not addressed — no electrophysiology in this atlas.

**F2.** How many TREM2+ microglia-like macrophages are present per mm² of prenatal dermis?
**Expected.** Not reported as a density.

**F3.** What is the effect of maternal smoking on prenatal skin macrophage composition?
**Expected.** Not studied.

**F4.** Which HLA haplotypes were present in the prenatal skin donors?
**Expected.** Not reported (donor metadata covers age and tissue, not HLA typing).

---

## Notes for whoever runs the comparison

- **B7's span is truncated** in the working dump and must be re-read in full before use.
- **D-part-(ii)** is only testable for D1 among the retrievable subatlas papers, since
  Lee and Reynolds have no served XML. If we want more part-(ii) coverage, the cited
  papers would need fetching individually — worth deciding before approval.
- The set is **atlas-heavy** (33 of 40 from Gopee). That reflects what's retrievable, not a
  design choice. Suo carries 3 items; if you want the subatlas side weighted more, say so
  and I'll mark more from it.
- Suo's references resolve to nothing through our JATS parser (AAAS `<mixed-citation>`
  format, see the parser gap noted separately), so no D items are drawn from Suo.

---

# Addendum — items requiring abstraction

The set above mostly asks questions using words the paper itself uses. That under-tests the
thing most likely to separate methods: questions where **the relation term, the entity, or
both** differ from the text. "What is the function of X" when the paper never writes
"function"; "what markers does Y express" when the paper never writes "marker" and simply
names genes.

A lexical search fails these unless you already know the answer — you cannot grep for
"marker" and you cannot grep for the gene names without having them. A dense index may or
may not bridge it. A model reading the passage should find it trivial. That makes this the
discriminating class for the whole comparison.

## Proposed tagging

Tag **every** item (including those above) on one axis, and report recall split by it:

- `none` — question wording matches the text
- `term` — the relation word is absent from the text (function, marker, location)
- `entity` — the cell type or gene is named differently from the text (abbreviation,
  synonym, full name)
- `both`

My suggested tags for the existing set: A1–A7 and B1–B6 are mostly `none`, except **A5**
(`entity` — asks via "Dp") and **A7** (`none` — the text says "markers" explicitly, which
makes it a useful control). The D items are all `none` on this axis; they test a different
thing.

## Pairs

Where possible the same fact is asked twice, once matching the text and once abstracted.
The gap between a pair is a direct measure of the abstraction penalty for a method, with
the underlying passage held constant:

- **A5 ↔ B16** — dermal papilla markers, abbreviation vs full name and "marker"
- **A7 ↔ B12** — markers of a cell type, with "markers" in the text vs without

---

**B8.** What is the function of TREM2+ microglia-like macrophages in relation to skin nerves?
**Tag.** `term`
**A.** They co-locate with and interact with Schwann cells, contributing to synapse formation and axon guidance, and may support establishment of the skin peripheral nervous system.
**Where.** Gopee · Macrophages in cutaneous neural differentiation
**Span.** "TML macrophages were predicted to interact with Schwann cells, contributing to synapse formation and axon guidance (VEGFA–NRP1, VEGFA–NRP2, SEMA3C–NRP2 and SEMA3E–PLXND1)"
*Caveat: the word "functions" does appear once nearby, attached to brain microglia rather than to TML macrophages — so a lexical hit is possible but points at the wrong subject. Medium difficulty by design; cut it if you'd rather the class were clean.*

**B9.** What is the role of macrophages in prenatal skin blood vessel formation?
**Tag.** `term`
**A.** Reciprocal macrophage–endothelial signalling supporting angiogenesis, chemotaxis and migration; macrophage-expressed VEGFA is a top upstream ligand regulating endothelial GATA2.
**Where.** Gopee · Macrophages support prenatal skin angiogenesis
**Span.** "Predicted ligand–receptor interactions were consistent with reciprocal communication between macrophages and endothelial cells to support angiogenesis, chemotaxis and cell migration"

**B10.** What does CXCL14 do in prenatal hair follicle matrix cells?
**Tag.** `term`
**A.** It is a chemokine reported to recruit regulatory T cells; matrix cells upregulate it relative to adult hair follicles.
**Where.** Gopee · Epidermal placode and matrix formation
**Span.** "increased expression of genes involved in chemotaxis, such as CXCL14, a chemokine previously reported to recruit regulatory T (Treg) cells"

**B11.** Which genes mark the dermal condensate?
**Tag.** `both` (no "marker" in text; entity given as "Dc")
**A.** FAM3C and EFNB1.
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "The Dc, for which formation is accompanied by invagination of the placode, expressed FAM3C and EFNB1"

**B12.** What markers distinguish prenatal skin fibroblasts from adult skin fibroblasts?
**Tag.** `term`
**A.** CD200 (immune suppression), RAMP2 (inflammation regulation), MDK (tissue regeneration).
**Where.** Gopee · Scarless healing
**Span.** "prenatal skin fibroblasts had upregulated genes involved in immune suppression (CD200), regulation of inflammation (for example, RAMP2) and tissue regeneration (MDK)"

**B13.** Which genes identify TREM2+ microglia-like macrophages?
**Tag.** `term`
**A.** P2RY12, CX3CR1, OLFML3 (shared microglial profile); plus CX3CR1 and SYT11 among immunomodulatory genes.
**Where.** Gopee · Scarless healing
**Span.** "yolk-sac derived TREM2+ macrophages that share an expression profile (P2RY12, CX3CR1 and OLFML3) with microglia-like macrophages from other developing organs"

**B14.** Which genes characterise WNT2+ and PEAR1+ prenatal fibroblasts?
**Tag.** `term`
**A.** CDKN1A (senescence), IL1R1 (cytokine pathways), POSTN (collagen deposition).
**Where.** Gopee · Scarless healing
**Span.** "WNT2+ and PEAR1+ prenatal fibroblasts expressed several genes involved in cellular senescence (CDKN1A), cytokine pathways (for example, IL1R1) and collagen deposition (for example, POSTN)"

**B15.** Where do pre-dermal condensate cells migrate to, and which genes rise as they do?
**Tag.** `entity` (text uses "pre-Dc")
**A.** Towards the epidermis; ADAMST1 (cell adhesion), CLDN11 (cell–cell contacts), CXCL12 (directed migration).
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "genes involved in regulation of cell adhesion (ADAMST1), cell–cell contacts (CLDN11) and directed migration (CXCL12) were upregulated as pre-Dc cells migrated towards the epidermis"

**B16.** What is the marker profile of the dermal papilla?
**Tag.** `both` — pairs with **A5**
**A.** NDP+, SOX2+.
**Where.** Gopee · HF mesenchymal differentiation
**Span.** "the Dc becomes encapsulated at its base as the Dp (NDP+, SOX2+)"

**B17.** Which genes do prenatal skin microglia-like macrophages share with brain microglia?
**Tag.** `entity`
**A.** P2RY12, CX3CR1, OLFML3; and the population correlates highly with embryonic brain microglia.
**Where.** Gopee · Scarless healing
**Span.** "Prenatal skin TREM2+ microglia-like (TML) macrophages were highly correlated with embryonic brain microglia"

---

That brings the draft to **50 items**. If 50 is too many to review, the A group is the most
cuttable — those are floor cases and four or five would do.
