# hdca_neurons — the second subatlas-consistency case

`project = "test_projects/hdca_neurons"`

HDCA v2, the pan-organ human developmental atlas (Webb et al. 2026, DOI
`10.64898/2026.03.30.714220`). 119 cell sets across two labelsets
(`refined_celltype` rank 0, `broad_celltype` rank 1), migrated here from the flat
`cell_type_annotations.json` on `origin/HDCA_Neurons`.

This is the case the subatlas-consistency work was motivated by, and the one that
is **not yet runnable**. Read on before trying.

## Blocked: the provenance here is marginal, not joint

`label_provenance.json` records, per cell set, a list of contributing studies with
counts *and, separately*, a list of author labels with counts:

```json
"AUTONOMIC_NCCS_SCPS": {
  "n_cells": 15860,
  "studies": [["whole_embryo", 10670, 0.673], ["Suo_et_al_2022_Science_Elmentaite2020", 1198, 0.076], ...],
  "top_author_labels": [["NCC-SCP early autonomic", 3739, 0.236], ["GLIAL", 1703, 0.107], ...]
}
```

Two marginals of a cross-tab, not the cross-tab. It can say *that* Suo 2022
contributed 1,198 cells and *that* 1,703 cells were called `GLIAL`, but not
whether those are the same cells. `transferred_annotations` needs the join, so it
is **absent from `cas.json`** — and `subatlas_contributors` / `subatlas-consistency`
therefore have nothing to work on here. Inventing a pairing would be worse than
leaving it out, so the marginals are preserved verbatim under each annotation's
`author_annotation_fields` (`contributing_studies_marginal`,
`author_labels_marginal`) and nothing pretends to be provenance that isn't.

`subatlas_resolver.read_provenance_labels` still falls back to
`label_provenance.json`, so subatlas *paper discovery* works — 18 contributing
studies, none with a DOI attached, so each needs the Semantic Scholar guess and
user review.

### To unblock

Re-extract the joint table from the source zarr and load it:

```bash
python .claude/skills/anndata-zarr-summary/run.py <hdca_v2_20260311_f2.zarr URL> \
  --cell-type-col refined_celltype \
  --transfer-cols study original_author_annotation \
  --out-dir projects/test_projects/hdca_neurons/zarr_summary

python -m atlas_chat.cli_cas transfer \
  --cas projects/test_projects/hdca_neurons/cas.json \
  --transfers projects/test_projects/hdca_neurons/zarr_summary/label_transfers__refined_celltype.json \
  --labelset refined_celltype \
  --source "study=..." --source "original_author_annotation=..."
```

The `source.dataset_url` on this project is a cellatlas.io viewer page, not a
resolvable zarr, so **the store URL has to come from somewhere else** before this
can run. That is the one thing standing in the way.

Note the two transfer columns answer different questions and both are wanted:
`study` says which paper the cells came from, `original_author_annotation` says
what they were called. Crossed jointly against `refined_celltype` they give the
(cell set × paper × upstream label) triple that `transferred_annotations` models.

## Acceptance targets

`provenance_evidence.md` (carried over) is a **hand-written** reconstruction of
exactly what this pipeline now automates — produced out-of-band during the May
2026 run, when 10 of 11 retinal reports failed to cite the study every one of
their cells came from. Treat it as the answer key, not as an input. Once the joint
table is loaded, two cell sets are the test:

- **`AMACRINE_CELL`** (n=78) — 100% from Sridhar et al. 2020, 98.7% of cells
  keeping that paper's own label `AC`. Should come out `exact match`,
  high purity, `primacy: subatlas_primary` on Sridhar. This is the clean
  inherited-label case, and the one the old pipeline got wrong.
- **`DL5_NEURON`** (n=3842) — 66.2% labelled `DL5 neuron`, but 17.6% `radial
  glia`, 8.6% `radial glia hindbrain`, 7.5% `excitatory neuron`, and 100% of the
  cells are HDCA's own whole-embryo data, not inherited at all. Should come out
  with **no published contributor** (whole_embryo has no paper),
  `no_dominant_contributor`, `primacy: atlas_primary`, and a purity caveat — the
  cluster is a transitional dP5→dI5 population, not a clean cell state.

The contrast is the point: one label is a faithful inheritance, the other is an
impure de-novo call, and the same numbers have to produce both verdicts.

## Not committed

Only `cas.json`, `label_provenance.json`, `provenance_evidence.md` and this README
are tracked. `traversal_output/`, `reports/`, `local_index/` and `zarr_summary/`
are ignored.
