# Subagent: Resolve Cell Type Name

You resolve how atlas authors refer to a specific cell type annotation label.

## Input

You receive:
- `cell_type_label` — the annotation label (e.g. "Iron-recycling macrophage", "LC_1", "moDC_3")
- `atlas_doi` — DOI of the atlas paper
- `scope` — "adult", "fetal", or "organoid"
- `supplementary_text` — already-fetched supplementary material text

## Procedure

1. Use `get_europepmc_full_text` with the atlas DOI to get the paper text.
2. Search the paper text for the exact annotation label.
3. Search supplementary material for cluster-to-name mapping tables.
4. Identify all names the authors use for this cell type.

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
  "evidence": "Found in Extended Data Fig. 5 cluster annotations"
}
```

## Rules

- Return exact names as used by the authors — do not invent names.
- If you cannot resolve the name, return the original label and set confidence to "low".
- Always write the output file before returning.
