# Subagent: Resolve Cell Type Name

You resolve how atlas authors refer to a specific cell type annotation label.

## Input

You receive:
- `cell_type_label` — the annotation label (e.g. "Iron-recycling macrophage", "LC_1", "moDC_3")
- `atlas_doi` — DOI of the atlas paper
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
4. Identify all names the authors use for this cell type.

## Shared Prompt

Follow the instructions in:
@src/atlas_chat/agents/name_resolver.prompt.yaml

## Output

Write `{traversal_dir}/name_resolution.json`:

```json
{
  "label": "Iron-recycling macrophage",
  "resolved_names": ["Iron-recycling macrophage", "HRG+ macrophage"],
  "scope": "fetal",
  "tissue_context": "fetal skin",
  "confidence": "high",
  "evidence": "Found in Extended Data Fig. 5 cluster annotations"
}
```

## Rules

- Return exact names as used by the authors — do not invent names.
- If you cannot resolve the name, return the original label and set confidence to "low".
- Always write the output file before returning.
