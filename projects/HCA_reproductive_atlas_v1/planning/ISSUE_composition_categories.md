# [schema] Composition: carry the descriptor category as a field, not in the key

`Composition` is keyed by "CxG descriptor category (tissue, development_stage, assay,
disease, sex, self_reported_ethnicity, organism) or an open semantic key (e.g.
germ_layer) for non-CxG descriptors", with each value a `CompositionCategory`.

Putting the category in the *key* forces a choice that real obs tables cannot make.

## The problem, from a live object

`projects/HCA_reproductive_atlas_v1` (2.24M cells) carries **three** obs columns that
are all anatomy, at different grains:

| obs column | grain | example values |
|---|---|---|
| `Organ` | organ | Uterus, Fallopian Tube, Ovary, Vagina |
| `Organ_part` | sub-organ | Endometrium, … |
| `Tissue_ROI` | region of interest within a part | … |

There is no 1:1 map onto `tissue`. Collapsing all three into one `tissue` key loses two
of them; picking one and inventing open keys for the rest (`organ_part`, `tissue_roi`)
means the category is no longer discoverable — a consumer asking "what anatomy do I have"
must know the local key names. The same applies to `Developmental_stage` vs
`Gestational_age_pcw` vs `Postnatal_age_years` vs `Tanner Stage` (four columns, one
`development_stage` category), and to `Disease` vs `Clinical_diagnosis` vs
`Observed_pathology` vs `Sampled_site_condition`.

We therefore key on the verbatim obs column name and set no category at all, which
complies but throws the categorisation away.

## Proposal

Move the category inside `CompositionCategory` as an optional field:

```json
"composition": {
  "Organ":      { "author_field_name": "Organ",      "category": "tissue", "values": [...] },
  "Organ_part": { "author_field_name": "Organ_part", "category": "tissue", "values": [...] },
  "Tissue_ROI": { "author_field_name": "Tissue_ROI", "category": "tissue", "values": [...] },
  "Target_cell_population": { "author_field_name": "Target_cell_population", "values": [...] }
}
```

- Keys stay stable and non-lossy: one entry per obs column, verbatim.
- `category` is **optional** — not everything has to fit one. `Target_cell_population`,
  `Menstrual_stage` and `Specimen_type` have no CxG category and simply omit it.
- Several columns may share a category, which is the case that keys cannot express.
- A consumer wanting "all anatomy" filters on `category == "tissue"` instead of
  guessing key names.

Suggested values: `tissue`, `development_stage`, `disease`, `assay`, `sex`,
`self_reported_ethnicity`, `organism` — recommended, not a closed enum, so an object
can name a category the list does not cover.

## Note

Also worth deciding whether cell-type labelsets belong in `composition` at all. This
object's `composition` currently carries four Axis A cell-type columns
(`celltype_HCA_fine`, `celltype_HCA`, `celltype_HCA_broad`, `celltype_HCA_lineage`)
because they are distributions with counts and there is nowhere else for them:
they are not descriptors, and `TransferredAnnotation` is for labels inherited from
*contributing* datasets, whereas these are the object's own. If `composition` gains a
category vocabulary they will need a home — a `cell_type` category, or a separate slot.
