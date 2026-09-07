---
name: resolve-name
description: Resolve how atlas authors refer to a cell type annotation label, and identify which corpus paper (atlas or subatlas) the annotation actually comes from — establishing the source_paper/role used by all downstream evidence provenance.
model: sonnet
---

# Subagent: Resolve Cell Type Name

You resolve how atlas authors refer to a specific cell type annotation label.

## Input

You receive:
- `cell_type_label` — the annotation label (e.g. "Iron-recycling macrophage", "LC_1", "moDC_3")
- `provided_synonyms` — any `synonyms` already recorded for this cell type in the
  CAS+ annotation (may be empty). **Union** these with the names you find in the
  paper; never discard a provided synonym just because you did not re-find it.
- `atlas_doi` — DOI of the atlas paper
- `atlas_corpus_id` — CorpusId of the atlas paper (if known)
- `scope` — "adult", "fetal", or "organoid"
- `supplementary_text` — already-fetched supplementary material text

## Procedure

1. **Primary**: Use `snippet_search` with `paper_ids` scoped to the atlas
   paper (by CorpusId or DOI). Search for the annotation label and likely
   synonyms. This returns relevance-ranked chunks and avoids fragile full
   text download → grep cycles.
2. Search supplementary material (already fetched) for cluster-to-name
   mapping tables.
3. If snippet search is insufficient, fall back to `get_europepmc_full_text`
   (max 2 attempts).
4. Identify all names the authors use for this cell type, and **union** them with
   `provided_synonyms` (from CAS) into `resolved_names` — deduped, including the
   original label.
5. **Identify the source paper of the annotation.** Usually the annotation is
   the atlas authors' own (`role: atlas`). But when the label was integrated
   from an upstream study (e.g. adult annotations from a subatlas paper mapped
   into the atlas), the annotation actually belongs to that **subatlas** paper.
   Record which paper it is in `source_paper` — downstream steps
   (scan-supplements, citation-traverse) use this to tag every piece of
   evidence with the correct paper and role. See the source-tagging design in
   issue #12.

## Shared Prompt

Follow the instructions in:
@src/atlas_chat/atlas_chat/agents/name_resolver.prompt.yaml

## Output

Write `{traversal_dir}/name_resolution.json`:

```json
{
  "label": "Iron-recycling macrophage",
  "resolved_names": ["Iron-recycling macrophage", "HRG+ macrophage"],
  "scope": "fetal",
  "tissue_context": "fetal skin",
  "confidence": "high",
  "evidence": "Found in Extended Data Fig. 5 cluster annotations",
  "source_paper": {
    "doi": "10.1038/s41586-024-08002-x",
    "corpus_id": "CorpusId:2762329",
    "role": "atlas"
  }
}
```

`source_paper.role` is `atlas` when the annotation is the atlas authors' own, or
`subatlas` when it was integrated from an upstream corpus paper. This object is
handed to `scan-supplements` (as its `source_paper` input) and to
`citation-traverse` (as `seed_role`), so the same paper/role labels flow through
all evidence provenance.

## Rules

- Return exact names as used by the authors — do not invent names.
- If you cannot resolve the name, return the original label and set confidence to "low".
- Always record `source_paper` (which corpus paper the annotation belongs to, and its role).
- Always write the output file before returning.
