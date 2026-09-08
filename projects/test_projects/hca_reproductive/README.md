# test_projects/hca_reproductive

`project = "test_projects/hca_reproductive"`

The HCA pan-organ female reproductive atlas — Cohen et al. (2026), bioRxiv
`10.64898/2026.06.10.731198`. 2,235,448 cells, 291 donors, 27 datasets, five organs
(ovary, fallopian tube, uterus, cervix, vagina) across the lifespan.

It is here because it is the only project with real **joint** integration provenance:
303 of its 312 cell sets carry `transferred_annotations` — 7,488 entries across 9
contributing studies, with ratios reaching down to 0.0002. That long tail is what any
contributor cutoff has to survive.

## Where `cas.json` came from

Copied verbatim (byte-identical) from `projects/HCA_reproductive_atlas_v1/cas.json` on
branch `origin/HCA_reproductive_atlas_v1`, which is where it is maintained. It was built
there from the atlas h5ad `obs` (2.24M cells × 66 columns, pulled obs-only over HTTP
range reads) plus the authors' supplementary tables.

Validates against `cas_annotation.schema.json` with 0 errors.

## What was checked before copying

Every count re-derived independently from the source `obs` parquet, joining on
`composition.celltype_HCA_fine`. Across all 312 annotations and all 7,488 transferred
entries: **0 mismatches** on `n_cells`, `cell_count`, `cell_ratio` and
`subatlas_contribution_cells`, with no entry missing and none spurious.

## Shape worth knowing

- **`cell_label` is the author's verbatim code; `cell_fullname` is the long name.**
  `Endo_ven_apcv` / `Activated post-capillary venous endothelial`.
- **The join key to `obs` is `composition.celltype_HCA_fine`** — present on all 312
  annotations, carrying `cell_count`/`cell_ratio` per code, summing to `n_cells`. A leaf
  has one code; the 74 rollup sets have several (`Adventitial fibroblasts` has three).
  Codes are bijective with the 212 in `obs`, pairwise disjoint within a labelset, and
  L1/L2 each cover 100% of cells — so either is usable as a partition.
- **Labelsets L1–L4 are the master nomenclature** from `cell_ontology_mapping.xlsx`,
  ranks 3→0. Note this is a *third* hierarchy: not the obs clustering tiers
  (`celltype_HCA_lineage ⊃ _broad ⊃ celltype_HCA ⊃ _fine`) and not the obs nomenclature
  tiers (`ontology_level1–4`). See `notes/ANNOTATION_HIERARCHIES.md` on the atlas branch.
- **`source.subatlas_papers` is not populated** — contributing studies are identified per
  entry by `source_labelset` (the obs column, e.g. `celltype_Ulrich2024`) and
  `source_taxonomy` (a DOI). Anything needing the registry, or
  `SubatlasPaper.cell_sets[]` as the `fraction_of_subatlas_set` denominator, has to add
  it. Both are direct counts from the parquet.

## The cell set to develop against

`Endo_ven_apcv` / *Activated post-capillary venous endothelial* (`HCArepro:L4:0204`,
n=4851, synonym `aPCV`). Its six contributors split cleanly into the two cases a
consistency step has to tell apart:

| Source | of the set | purity (of that study's 4851-set contribution) |
|---|---|---|
| Weigert 2025 | 24.1% | `endothelial cell` 1168/1168 = 100% |
| Ulrich 2022 | 8.2% | `blood vessel endothelial cell` 396/396 = 100% |
| **Ulrich 2024** | **6.8%** | **`Capillary` 197/332 = 59%, `tPCV` 22%, `aPCV` 11%** |
| García-Alonso 2021 | 5.7% | `Endothelial ACKR1` 276/277 = 99.6% |
| HECA | 5.5% | `Venous` 263/266 = 98.9% |
| Ovary Sanger 2026 | 0.4% | `Endo_Cap` 19/21 = 90% |

Weigert and Ulrich 2022 are pure but uninformatively coarse — they agree with the atlas
only in the sense that "endothelial cell" agrees with everything. Ulrich 2024 is the
interesting one: the atlas's own synonym for this set is `aPCV`, which is Ulrich 2024's
**11% minority** label for these cells, while 59% of them were called `Capillary`. Any
step that just reports the dominant upstream label gets this backwards — and note that
`cell_ratio` alone (6.8%) hides the disagreement entirely; it only appears against
`subatlas_contribution_cells`.

## Not committed

Per the test-project convention, only `cas.json` and this README are tracked.
`traversal_output/`, `reports/`, `selections/`, `runs/` and `local_index/` are ignored.

Two large inputs live outside the repo and are needed for anything that recomputes counts
or reads papers:

- the `obs` parquet (150 MB) — on the `Atlas-reporter_three` checkout under
  `projects/HCA_reproductive_atlas_v1/h5ad_obs/`, rebuildable via `pull_obs.py` there
  (Sanger VPN required);
- the paper corpus (494 MB) — `Atlas-reporter-corpora/hca_reproductive/`, holding
  retrieved supplements for the atlas and its 21 subatlas publications, plus prose units.
  Rebuildable from its own `corpus.json`.
