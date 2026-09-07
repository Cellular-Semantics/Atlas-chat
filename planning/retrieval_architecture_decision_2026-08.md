# Retrieval architecture decision — MVP scope (2026-08-31)

Written to close out the retrieval-strategy question the roadmap left open (§5, "the biggest
lever on report quality and the place we are genuinely stuck"). The experiments on
`test/retrieval-matrix` (Stages 1, 2, 3b, citation traversal, availability survey) are now
extensive enough to decide an architecture rather than run more arms first. This records the
decision, what it requires building, and an MVP sequence. Superseded pieces of ROADMAP.md §5
should be pointed here rather than re-litigated.

**Priority order for this decision, as given:** full functionality and accuracy first,
efficiency second, MVP soon. Where the evidence and that priority order point the same way,
the call is easy; where they don't, that's flagged explicitly.

---

## 1. Model pinning — flagging a tension before locking it in

The steer was to pin Sonnet everywhere for subagents. Stage 3b's clearest finding cuts the
other way: **reader model moved results more than any retrieval configuration** — Opus beat
Sonnet 40-to-6 in net disagreements, by up to 11 items on one arm, against a 5-item maximum
spread between retrieval backends. Sonnet's losses cluster in `substituted` and `overreach` —
it answers confidently where Opus correctly declines. That is precisely the failure mode that
survives quote validation (the quote is real; the claim isn't) and is exactly what "accuracy
critical" should weigh against.

**Decision, pending explicit override:** pin **Opus** for the evidence-gathering / reading
role (citation-traverse, scan-supplements) where a wrong-but-quoted claim is the risk. Sonnet
stays fine for structural steps with no accuracy finding against it — name resolution, CL
mapping, synthesis (synthesis is a different task, see §5). This is the one place in this
document where I'm overriding the stated default rather than just implementing it, because the
experiment that was run to answer exactly this question said the opposite. Revert to Sonnet
everywhere with one line changed in each agent's front-matter if the cost matters more than
this data suggests.

---

## 2. Sources and priority

**Primary atlas paper + subatlas papers, prioritised by contribution.** This is already mostly
built: PR #34 (open, unverified but substantively complete) adds `transferred_annotations`,
the contribution/purity/reverse-share metrics, and a calibrated cutoff (≥5% contribution ∧
≥50 cells) for which subatlas papers matter for a given cell set. Use that cutoff to decide
which subatlas papers are in-scope sources for a cell type, not the roadmap's rejected
`cell_ratio` alone. Other source types (arbitrary literature) stay explicitly out of MVP scope,
addable later without changing this design.

---

## 3. Per-paper retrieval: JATS-first, whole-text by default

**Waterfall: local JATS-XML index first, ASTA only when JATS is unavailable.** This matches
the availability survey (JATS full text has none of ASTA's coverage gaps — introductions,
captions, rendering drift) and the explicit steer not to worry about version mismatch (the
Suo case). Simpler than the roadmap's three-way `asta → jats → needs_pdf`: collapse to two
rungs for MVP (`jats` / `asta`), leave the PDF rung (#13) as a follow-on for the ~48% neither
route reaches.

**Within one paper, read the whole narrative text — don't retrieve.** This is the one place
the evidence and "avoid complexity" point at the same answer. Stage 2 and Stage 3b both found
a retrieved slice ties whole-paper reading on accuracy (44/55 both, 20-21/21 both); retrieval's
only argument was cost. An atlas paper's narrative text is ~10-24k tokens — well inside a
subagent's context. So: **skip within-paper snippet retrieval for MVP.** No hybrid index, no
chunk ranking, no RRF, for any paper you can read whole. This removes an entire subsystem
(local dense embedding, its window-fix machinery, BM25 fusion) from the MVP critical path
without giving anything up on accuracy per the data in hand — it only gives up the ~10x token
saving Stage 1 measured, which is exactly the trade the stated priority order asks for.

Retrieval earns its place only where the search space is larger than one paper — i.e. hop 2 of
citation traversal (§4) and the case of a paper too large to read whole. Keep `local_snippet_index` and the RRF hybrid available for that case; don't build new capability around it for MVP.

**Consequence for the supplement store (#21):** unaffected — supplements are read via the
manifest + `cli_supplements slice`/`show`, not narrative-text retrieval. That store already
exists (PRs #29/#31) and stays exactly as built.

---

## 4. Citation traversal: two hops, JATS-native path is mostly new

**Depth capped at 2, as asked.** The citation-traversal experiments only tested the ASTA path;
here's what a JATS-native path needs, and what already exists.

**What already exists and is directly reusable:**
- `services/_jats_parser.py` (`parse_jats_citations`) already resolves every citing sentence
  to a specific reference and a `ResolvedRef` (DOI/title/authors) — this *is* "reaching the
  cited paper" for a JATS-indexed source, and it's a stronger result than ASTA's: no search is
  needed to find the target, because the sentence-to-reference link is direct markup, not an
  inference. The 88-97% resolution numbers measured for ASTA don't even apply here; this is
  closer to 100% modulo the AAAS `<mixed-citation>` gap (fixed in #37) and unresolvable
  markers.
- `services/citation_traverser.py:traverse_local` exists but only does within-paper retrieval
  — no hop, no reference following. **This is the gap.**
- The ASTA path's `traverse_annotated` / `cli_annotate fetch` / follow-set resolution is the
  full pattern to mirror, not reuse directly (it's ASTA-specific).

**What needs building (new, not on any branch as far as I can see):**
1. A `traverse_local_citations` (or equivalent) that: reads the seed paper's JATS, runs
   `parse_jats_citations`, gates each `CitedSentence` for relevance to the query (this is the
   one place a model judgement is needed — same role citation-traverse plays for ASTA today),
   and for each followed citation, resolves the target paper through the *same* JATS-first/
   ASTA waterfall (§3) rather than assuming it's fetchable.
2. Because a JATS-native seed already tells you exactly which paper a citation targets, the
   ASTA-only "search the reference list to find the right paper" step (the first of the
   citation-traversal experiment's two hops) is **unnecessary here** — you already know the
   target. What's needed at hop ≥1 is simpler than the ASTA path: fetch the resolved target
   (waterfall, §3), read it whole or the section around the citing context if it's large, and
   extract evidence the same way hop 0 does. This is good news for MVP scope — it's less new
   code than the ASTA-parity design implied, not more.
3. Hop 2 (following citations from a hop-1 paper) reuses the same two functions recursively,
   capped at depth 2.
4. PR #34 (open) already added a `seeds` array to `citation_traverse_input.schema.json` and
   `cli_annotate fetch --local` per its own PR description — worth pulling that piece in during
   this build rather than re-deriving it, independent of whether the rest of #34 (subatlas
   consistency judgement) is ready to merge.

**Where ASTA still matters for citation traversal:** any cited paper neither locally indexed
nor JATS-fetchable falls back to ASTA exactly as atlas-level retrieval does (§3). At that point
the citation-traversal experiment's two-hop, keyword-query, reference-list-scoped design is the
right one, and is already validated (19/19 paper identification, 97% passage extraction given
the right paper).

---

## 5. The one accuracy risk this doesn't touch: synthesis

Every experiment above is about retrieval and reading. Stage 2 positively ruled out the
reading step as the source of unsourced prose (1 fabrication in 231 reads, absence reported
18/18), and the citation-traversal work separately showed a flatly contradicted claim passes
every check currently run. Both point at synthesis, and it has never been measured — a report
audit already found 60% of one project's reports had unsourced sections. This is the highest-
value unmeasured thing in the whole pipeline and it sits downstream of everything in this
document. Given "accuracy critical," I'd run one cheap synthesis probe (same item set, ask for
a report *section* instead of an answer, check what enters unsourced) before calling the MVP
retrieval/synthesis pipeline done — it's a half-day of harness reuse (Stage 2's precompute →
subagent → deterministic-score pattern), not a new experimental design.

---

## 6. Subagent isolation — conservative for MVP, revisit later

No experiment here tested cross-agent isolation directly; Stage 2/3b's "leak check" only
caught quote contamination *within* an agent given multiple job files, not isolation between
agents. Per the steer: keep the current one-subagent-per-orchestration-step pattern (separate
dispatch for resolve-name, scan-supplements, citation-traverse per cell type) rather than
introducing shared sessions or per-paper-batched agents (the efficiency win described in
`efficient_workflow_design.md`) until that's specifically tested. Note for later: the per-paper
batching design is the main lever on the $597/119-cell-type cost problem, and is now easier to
justify testing given whole-text reading (§3) makes each dispatch larger per call — worth
prioritising once MVP ships.

---

## 7. MVP build sequence

Roughly in dependency order; each is small given how much already exists.

1. **Merge PR #20** (Layer A query-driven selection) — orthogonal, already flagged mergeable.
2. **Pull in #34's `seeds` schema addition and `cli_annotate fetch --local`** as a standalone
   piece, independent of the rest of #34's subatlas-consistency judgement (which stays gated on
   its own verification run).
3. **Build `traverse_local_citations`** (§4) — the one genuinely new piece of retrieval code.
   Depth-capped at 2, JATS-first/ASTA-fallback resolution for followed citations, whole-text
   reading at each hop per §3.
4. **Rewire `citation-traverse` agent / `CLAUDE.md` step 4b** to call the JATS-native path when
   the seed (and follow targets) are locally indexed, falling back to the existing ASTA path
   agent-for-agent otherwise. Keep both live; this is a routing change, not a rewrite of either.
5. **Drop within-paper snippet retrieval from the production path** (§3) — simplifies
   `scan-supplements` and hop-0 evidence gathering to "read the whole narrative text," with the
   supplement store handling tables separately as it already does.
6. **Pin Opus for citation-traverse and scan-supplements, Sonnet elsewhere** (§1), or Sonnet
   everywhere if the override is confirmed.
7. **Run the synthesis probe** (§5) before declaring the MVP's evidence pipeline trustworthy.
8. **Rebuild local snippet indexes** (#30) only where retrieval is still used post-(5) — i.e.
   hop-2 citation targets too large to read whole, and any paper exceeding context budget.
9. **Close #36** (rendering-aware quote validation) — still needed because ASTA fallback
   remains in the design at both the atlas-source and citation-hop levels.

Deliberately deferred past MVP: the PDF rung (#13), per-paper batched evidence gathering
(§6), and any query-decomposition beyond what already helps (per-axis keyword queries only at
the citation reference-list hop, which this design mostly avoids needing by using markup
resolution instead of search).

---

## 8. Accumulating evidence going forward

Keep the pattern that already worked across four experiment lines: precompute contexts to
disk, dispatch subagent reads on quota, score deterministically wherever possible, judge only
what can't be decided by rule, write findings to a dated `planning/*.md` file, and never derive
an answer key from prose. Turn Stage 3b's harness (`experiments/stage3b/`) into the
regression fixture ROADMAP §9 asks for: re-run it (or a version pointed at the new JATS-native
citation path) whenever retrieval or synthesis changes, and log results in a running comparison
rather than a one-off report, so the MVP's behaviour is tunable against evidence rather than
re-argued each time.
