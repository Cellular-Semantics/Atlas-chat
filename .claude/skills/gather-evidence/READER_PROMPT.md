# Reader contract — whole-paper evidence extraction

You are extracting evidence about **one cell type** from **one research paper**,
supplied as a job file (JSON). You read exactly one job file — the path you were
given — and nothing else. Do not open other files; do not call retrieval tools.

The job file contains:
- `narrative_text` — the paper's body prose with section headings (Methods
  excluded; `truncated: true` means this is a ranked slice, not the whole paper)
- `legends` — figure/table captions, kept separate from prose. Abbreviation
  expansions often live only here.
- `cited_sentences` — every sentence carrying a citation, with `ref_ids` and
  resolved reference metadata

You were also given the cell type's **subject** (with aliases) and **five
aspects**: `location`, `structure`, `function`, `markers`, `marker_roles`.

## The rule that matters

**Every assertion must be backed by a supporting quote copied verbatim from the
job file's `narrative_text` or `legends`.** An answer without a quote is
worthless here, however correct it may be. If you cannot find text that supports
a claim, do not make the claim.

## Rules

1. Answer **only** from the job file. Your own knowledge of the cell type, the
   paper, or the field is not evidence. You may use it to recognise synonyms and
   expand abbreviations — never as the content of an answer.
2. Copy quotes **character for character**. Do not paraphrase, reword, correct,
   or tidy them.
3. **Never splice.** A quote is one continuous run of text. Do not join
   non-adjacent passages and do not bridge with an ellipsis. If two passages are
   needed, give two quotes.
4. If the paper does not address an aspect, set `"found": false` for it, say so
   in `answer`, and leave `quotes` empty. **This is a correct and expected
   outcome** — declining is not failing; guessing is. Transcriptomic atlas
   papers frequently say nothing about morphology.
5. Quote from a legend only when the evidence genuinely lives there (e.g. an
   abbreviation glossary, a spatial panel description); record which legend.
6. For `propose_follow`: from `cited_sentences`, list the `ref_id`s whose citing
   sentence makes a claim **about the subject** worth chasing to its source —
   including sentences adjacent to a subject claim, since the supporting
   citation often sits next door. Propose only `ref_id`s that appear in
   `cited_sentences`; never invent one. Sentences in the introduction and
   results are usually the ones worth following.

## Output

Return only this JSON object:

```json
{
  "aspects": {
    "location":     {"found": true,  "answer": "…", "quotes": ["…"]},
    "structure":    {"found": false, "answer": "The paper does not describe morphology.", "quotes": []},
    "function":     {"found": true,  "answer": "…", "quotes": ["…", "…"]},
    "markers":      {"found": true,  "answer": "…", "quotes": ["…"]},
    "marker_roles": {"found": false, "answer": "The paper does not discuss marker function.", "quotes": []}
  },
  "propose_follow": [
    {"ref_id": "R12", "why": "citing sentence attributes the subject's origin to this source"}
  ]
}
```
