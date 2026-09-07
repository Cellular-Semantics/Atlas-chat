# hca_reproductive — subatlas-consistency development project

`project = "test_projects/hca_reproductive"`

The HCA pan-organ female reproductive atlas (Cohen et al. 2026, DOI
`10.64898/2026.06.10.731198`). It is here because it is the only project with real
**joint** integration provenance: 303 of its 312 cell sets carry
`transferred_annotations`, 7,488 in total, across 9 contributing studies — with counts
and ratios reaching down to 0.0002. That long tail is the thing the cutoff has to
survive.

## Where it came from

`cas.json` was migrated from `projects/HCA_reproductive_atlas_v1/cas_draft.json` on
branch `origin/HCA_reproductive_atlas_v1`, which predates the current schema. The
migration (a) dropped annotation-level `rank` (it lives on the labelsets), (b) moved the
13 descriptor columns from `author_annotations` into `composition` and dropped the four
`celltype_HCA_*` columns as duplicates of the L1–L4 labelsets, (c) mapped `comment` to
`rationale`, and (d) filled in two fields the draft could not have had:

- `subatlas_paper` on every transferred annotation, keyed to a new
  `source.subatlas_papers` registry built from the same column→DOI map the draft's
  `source_taxonomy` strings came from;
- `source_label_cell_count` — each transferred label's atlas-wide total, summed over the
  210 **leaf** cell sets (which partition the atlas exactly: 2,235,448 cells, matching
  the L1/L2 totals). Summing over all 312 annotations would multiply-count through the
  hierarchy.

The draft was never schema-validated, because `check_cas_annotation.py` only fires on
files named `cas.json`. This one validates.

## The cell set to develop against

`Activated post-capillary venous endothelial` (`HCArepro:L4:0204`, n=4851). Its six
contributors split cleanly into the two cases the consistency step has to tell apart:

| Source | contribution | purity | reverse share of dominant label |
|---|---|---|---|
| Weigert 2025 | 24.1% | `endothelial cell` 100% | — |
| Ulrich 2022 | 8.2% | `blood vessel endothelial cell` 100% | — |
| **Ulrich 2024** | **6.8%** | **`Capillary` 59% / `tPCV` 22% / `aPCV` 11%** | `Capillary` 197/1656 = 12% |
| García-Alonso 2021 | 5.7% | `Endothelial ACKR1` 100% | 276/5413 = 5% |
| HECA | 5.5% | `Venous` 99% | — |
| Ovary Sanger 2026 | 0.4% | `Endo_Cap` 90% | — |

Weigert and Ulrich 2022 are pure but uninformatively coarse — they agree with the atlas
only in the sense that "endothelial cell" agrees with everything. Ulrich 2024 is the
interesting one: the atlas's own synonym for this set is `aPCV`, which is Ulrich 2024's
**11% minority** label for these cells, while 59% of them were called `Capillary`. Any
consistency step that just reports the dominant upstream label gets this backwards.

## Not committed

Per the test-project convention, only `cas.json` and this README are tracked.
`traversal_output/`, `reports/`, `selections/`, `runs/` and `local_index/` are ignored.
The 21 subatlas PDFs live on the original branch under
`projects/HCA_reproductive_atlas_v1/subatlas_pubs/` and need copying in before the
corpus can be built.
