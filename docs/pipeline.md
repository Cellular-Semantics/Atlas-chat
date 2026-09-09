# The pipeline: what is actually built

**Developer reference. Describes the `dev` branch as it stands.**

This is the implementation map for atlas-chat: for each stage of processing, what
runs, what it reads and writes, which schema the output conforms to, and which
hook checks it. It is ordered by the chain of processing — project setup through
literature search to a finished report — not by directory.

It is deliberately more detailed and more developer-facing than `README.md`.

Three neighbouring documents, so you know when to look elsewhere:

- `CLAUDE.md` is the orchestrator's operating instructions — what to do at each
  step, in the imperative. It is organised as project setup, CAS+ construction
  and report production, and defers to this file for what exists; where the two
  disagree, this file describes the code.
- `CLAUDE_dev.md` is how to build and extend the workflow: conventions, testing,
  the schema-first rule.
- `README.md` is the project overview for people who are not going to read either
  of the above. It was last updated in June 2026 and is out of date.

**Keeping it current:** a piece of work is not finished until this file reflects
it. Update it in the same commit as the change, on the branch where the change
happens.

**Scope:** everything below is present on `dev` unless stated otherwise. A large
amount of functionality is finished but still sitting on feature branches — see
[Not yet incorporated](#not-yet-incorporated).

---

## 1. Project setup and inputs

A project is a directory under `projects/{project}/`. The one required input is a
CAS+ document describing the atlas and its cell-type annotations.

**CAS+ config** — `projects/{project}/cas.json`, conforming to
`schemas/cas_annotation.schema.json`. Carries the atlas `source` (DOI, title),
the `composition` context (organism, stage, tissue), and the annotation list, each
with a `cell_label` and `labelset`. Where an annotation came from an integrated
upstream study, `transferred_annotations[]` records the subatlas paper and source
taxonomy. Checked on write by `.claude/hooks/check_cas_annotation.py`.

**Skill `generate-cas`** builds that document from whatever the project actually
has: a bare list of labels, a spreadsheet or CSV, an AnnData `h5ad`/zarr `obs`, a
CELLxGENE dataset, or a paper's supplementary table. It asks the user for anything
not derivable from the source. This is the one place that normalises input shape;
everything downstream can assume CAS+.

**Skill `anndata-zarr-summary`** fetches `obs/` only from an AnnData-zarr store
(never the expression matrix), over http(s), gs or file URLs, zarr v2 or v3. It
produces per-cell-type co-annotation summaries and a `cell_type_annotations.json`.
Note that this emits the *legacy flat* annotation file, not CAS+.

**Skill `load-project-context`** reads the project's annotations, resolves the
atlas CorpusId, scans any existing traversal output, and builds a session-level
merged paper catalogue. Also still on the legacy flat file.

**`services/atlas_paper.py`** holds the config dataclasses (`AtlasConfig`,
`PaperIdentifiers`, `AtlasPaperData`) and `load_project_config()`.

## 2. Working out which papers are in scope

An atlas paper is rarely the only source. Cell types are frequently transferred in
from upstream studies, and the evidence for a given label may live entirely in one
of those.

**`services/subatlas_resolver.py`** turns integration provenance into a list of
papers. `parse_label()` and `read_provenance_labels()` read study labels out of the
annotation data; `discover()` proposes candidate subatlas papers; `ingest()` adds
them to the project corpus. Library only — no CLI yet.

**`services/asta_indexing.py`** probes how much of a given paper ASTA actually
indexed, and classifies it into a band (`probe()`, `classify_rows()`,
`IndexingReport`). Results are cached (`probe_cached()`, `cached_bands()`,
`clear_cache()`). This matters downstream: where a paper's band is
`abstract_only`, only title and abstract were ever searchable, and the report
synthesiser is instructed to say so in any claim resting on it.

## 3. Supplementary material

Markers and cluster-to-name mappings usually live in supplements rather than the
paper body, so this gets its own subsystem: fetch, store, triage, index.

**Fetch — `services/supplement_fetch.py`.** `resolve_pmcid()` and `fetch_jats()`
get the paper; `fetch_bundle()` pulls the EuropePMC supplementary bundle, with
`publisher_direct_url()` / `springer_url()` as a fallback where the bundle is
absent. A preprint has no PMC record, so `biorxiv_listing()` /
`parse_supplement_page()` / `biorxiv_get()` read the file list off the preprint
server's own supplementary-material page and fetch each file from it (needs the
`[text-access]` extra for the impersonating HTTP client).
`verify_payload()` and `is_non_evidence()` discard junk. `should_attempt()`
holds the retry policy. `fetch_supplements()` does one paper, `fetch_corpus()` does
the project's whole paper set. Library only — no CLI.

**Store — `services/supplement_store.py`**, with
`python -m atlas_chat.cli_supplements` as the entry point. An on-disk store keyed
by paper, holding the files plus a manifest that records what each file, sheet or
page contains. Subcommands: `inventory` (build a manifest skeleton from JATS
captions), `adopt` (take in manually downloaded files), `unpack` (archives),
`outline` (structure of a spreadsheet or document), `text`, `slice` (read a named
locator without opening the whole file), `show`, `check`, `papers`. The manifest
conforms to `schemas/supplement_manifest.schema.json` and is checked on write by
`.claude/hooks/check_supplement_manifest.py`. `cross_check_manifest()` and
`validate_manifest()` provide the same checks programmatically.

**Triage — `services/supplement_triage.py`.** Decides cheaply which files are worth
indexing at all, from column signatures and captions: `classify_table()`,
`classify_caption()`, `looks_per_cell()`, `triage_paper()`, `sheet_candidates()`,
`indexable()`. The point is to avoid opening a 2 GB per-cell metadata table to
discover it holds no cell-type names.

**Skill `index-supplements`** drives the above: reads captions first, opens files
only when captions do not answer the question, and writes the manifest. Declares
`supplement_manifest.schema.json` as its output. Needs the `[supplements]` extra
(openpyxl).

## 4. Resolving the name and the source paper

**Subagent `resolve-name`.** Takes an annotation label — often an abbreviation like
`LC_1` or `F2` — and finds how the authors actually refer to that cell type, using
snippet search scoped to the paper plus the supplement store. It also decides
*which* paper the annotation genuinely comes from, atlas or subatlas, and emits the
`source_paper` / `role` pair that every downstream piece of evidence carries for
provenance.

Prompt: `agents/name_resolver.prompt.yaml`. Output written to
`projects/{project}/traversal_output/{cell_type}/name_resolution.json`.

No declared input or output schema yet — the contract is prose in `CLAUDE.md`. The
schema exists on the `query-decomposer` branch.

## 5. Scanning supplements for a cell type

**Subagent `scan-supplements`.** Given the resolved names and the supplement store,
extracts marker genes with their evidence type, plus any other findings (function,
spatial location, developmental timing) and exact supporting quotes. Every finding
records its parent paper explicitly and a locator back into the store — the parent
is not assumed to be the atlas.

Prompt: `agents/supplementary_scanner.prompt.yaml`. Output:
`supplementary_findings.json`, conforming to
`schemas/supplementary_findings.schema.json`. Declares its output schema in
front-matter, but no validator hook is registered for it.

## 5a. Choosing which cell types to report on

A request names cell types the way a person would; the atlas names them the way
its authors did. The `select-cell-types` skill closes that gap in the
orchestrator's own context, because it is a judgement that has to be put to the
user rather than guessed at.

It reads `cli_project outline` — the annotation hierarchy, at roughly a
two-hundredth of the size of the CAS+ document, whose bulk is composition — and
resolves a request by finding a node and taking its subtree. Text matching alone
is not sufficient and fails quietly: on the reference project, asking for
macrophages by label alone finds one of seven, because two of the six subtypes
are named for where they are and say nothing about being macrophages.

## 6a. Reading a paper whole

`read-atlas-paper` (opus) is given a project name and the cell types to read
for, and nothing else. It resolves the project's paths with
`services/project_paths.py`, assembles the paper with `paper_ingest` and the
subject blocks with `subject_block`, then answers a fixed set of questions about each:
naming first, since the names it finds are what it searches with for everything
after, then location, markers, structure and function. Every assertion must
carry a verbatim quote, and each answer states not only what the paper says but
what the paper did to establish it — the claim and its basis are frequently
different sentences, and the basis is often in a figure legend.

It writes one `all_summaries.json` per cell type, into that cell type's
traversal directory. Cell types are taken in series with each one's subject
block immediately before its own questions.

## 6. Citation traversal and evidence gathering

The core of the literature search. A query is run against ASTA (Semantic Scholar)
snippet search seeded on a known paper; the results are annotated programmatically;
the agent reads only the slim annotated text and decides which citations to follow;
the loop repeats to the configured depth.

The design rule is that raw ASTA payloads never enter a model context. Retrieval,
reference splicing and follow-set resolution all run in Python.

**`cli_annotate.py`** — `python -m atlas_chat.cli_annotate` — is the sanctioned
boundary. Subcommands:

- `fetch` — call `snippet_search`, splice reference tokens into the sentence text,
  write slim `annotated_snippet` records to disk, print only counts and a path.
- `follow-set` — intersect the agent's proposed CorpusIds with the ids the
  annotator actually emitted; write the deduped follow set plus rejects.
- `show` — print one record's `annotated_text` and sentence spans.

**`services/snippet_annotator.py`** does the work behind it: `project_snippet()`,
`project_response()`, `resolve_follow_set()`.

**`services/citation_traverser.py`** holds the traversal itself: `traverse()`,
`traverse_annotated()` (ASTA), and `traverse_local()` (local index).

**Local snippet index.** Where ASTA has not indexed a paper — fresh preprints,
closed-access journals — `services/local_snippet_index.py` builds an ASTA-shaped
index locally and traversal runs over both, merging results; local snippets are
marked `source_method: "local_snippet"`. CLI:
`python -m atlas_chat.services.local_snippet_index` with `build`, `add`, `remove`,
`rebuild`, `check`, `list`, `search`. Supporting modules: `fetch_preprint.py` (DOI
to local JATS), `_jats_parser.py` (sentence-level citation associations from JATS),
`_pdf_parser.py` (PDF to paragraph segments). Driven by the `local-paper-index`
skill. Needs the `[local-index]` extra (sentence-transformers, PyMuPDF).

**Subagent `citation-traverse`.** Declares
`schemas/citation_traverse_input.schema.json` in and
`schemas/all_summaries.schema.json` out. It judges which spliced sentences are
genuinely about the cell type and proposes which citations to follow; it does not
call ASTA itself.

Outputs: `all_summaries.json` and `paper_catalogue.json` in the traversal
directory. Individual records are checked by `check_annotated_snippet.py`,
`check_follow_set.py` and `check_evidence_summary.py` against
`annotated_snippet.schema.json`, `follow_set.schema.json` and
`evidence_summary.schema.json`.

`EvidenceSummary` carries two optional fields alongside its provenance:
`aspect`, which keeps the question being answered out of the prose, and
`found`, which distinguishes a source that is silent from a question nobody
asked. Both are optional because citation traversal has no aspect to give and
writes only what it found. What binds every producer is the quote rule: an item
may have an empty `quotes` list only where `found` is explicitly false.
`check_evidence_summary.py` enforces the shape and then looks for each quote in
the job files under `papers/` beside the output, via
`validation/quote_search.py`. Searching rather than trusting is deliberate — the
search reports where the text was found, and a source a writer names can be
named wrongly. Where no job file sits beside the output there is nothing to
search, and the hook says so rather than passing quietly.

## 7. Report synthesis

**Subagent `synthesize-report`** reads `name_resolution.json`,
`supplementary_findings.json`, `all_summaries.json` and `paper_catalogue.json`, and
writes `projects/{project}/reports/{cell_type}.md`.

Prompt: `agents/report_synthesizer.prompt.yaml`, which is canonical and is imported
by `CLAUDE.md`. The rules that matter: blockquotes may only be used for text
verified as an exact substring of traversal evidence; supplement and name-resolution
evidence is paraphrased with an inline citation instead; DOIs come only from the
paper catalogue; where a paper's ASTA band is `abstract_only`, the claim says so.

The subagent file has no YAML front-matter, so it declares no input or output
schema.

## 8. Validation

**`validation/report_checker.py`** — `validate_report(report_path, traversal_dir)`
returning `(passed, errors)`, built on the pure helpers `check_quotes()` and
`check_references()`. Quote checking normalises whitespace, dashes and smart quotes
and handles ellipsis-separated segments. Reference checking confirms every DOI in
the report appears in the paper catalogue.

The orchestrator calls this explicitly after synthesis and feeds any errors back to
`synthesize-report`, up to two retries. `.claude/hooks/check_report_refs.py` runs
the same checks on write as an extra guard for interactive sessions, but the
correction loop does not depend on it.

## 9. Cell Ontology mapping

**Subagent `ontology-term-lookup`** searches OLS4 for CL terms using the report's
own description plus alternative phrasings, compares candidate definitions against
the report content, and classifies the match as exact, broad, narrow or none using
SKOS vocabulary. Writes `cl_mapping.json`, conforming to
`schemas/cl_mapping.schema.json`, checked by `.claude/hooks/check_cl_mapping.py`
(which also enforces the `match_type` ↔ `skos_mapping` and `new_term_needed`
consistency rules).

The mapping is then written into the report header as a `Cell Ontology:` line with
a PURL of the form `http://purl.obolibrary.org/obo/CL_NNNNNNN`.

This is the worked exemplar for the input/output front-matter convention.

## 10. New term request

Runs only when `cl_mapping.json` has `new_term_needed: true`.

**Subagent `cl-term-request`** drafts a CL new term request from the report and the
mapping, following `docs/LLM_prompt_guidelines_for_CL_definitions.md`,
`docs/relations_guide.md` and `docs/cl_new_term_request_template.md`. Produces
`cl_term_request.json` — structured fields plus a pre-rendered `ntr_markdown` ready
to paste into a GitHub issue — conforming to
`schemas/cl_term_request.schema.json` and checked by
`.claude/hooks/check_cl_term_request.py`.

## 11. Posting to GitHub

Optional, and never without explicit user confirmation, since it opens a public
issue on `obophenotype/cell-ontology`. The current route is `gh issue create` with
a `public_repo`-scoped token supplied as `GH_TOKEN` so the user's own credentials
are untouched. The issue URL is appended to the report's Cell Ontology line.

`src/github_app_posting/` implements a GitHub App alternative that posts under a
bot identity without a personal token. Built, not yet wired into the workflow.

---

## Cross-cutting

### Schemas and their validator hooks

| Schema | Written by | Hook |
| --- | --- | --- |
| `cas_annotation` | `generate-cas` | `check_cas_annotation.py` |
| `supplement_manifest` | `index-supplements`, supplement store | `check_supplement_manifest.py` |
| `annotated_snippet` | `cli_annotate fetch` | `check_annotated_snippet.py` |
| `follow_set` | `cli_annotate follow-set` | `check_follow_set.py` |
| `evidence_summary` | `citation-traverse`, `read-atlas-paper` | `check_evidence_summary.py` |
| `all_summaries` | `citation-traverse` | none |
| `supplementary_findings` | `scan-supplements` | none |
| `citation_traverse_input` | orchestrator | n/a (input) |
| `cl_mapping` | `ontology-term-lookup` | `check_cl_mapping.py` |
| `cl_term_request` | `cl-term-request` | `check_cl_term_request.py` |
| report markdown | `synthesize-report` | `check_report_refs.py` |

Also present: `run_provenance` (used by `utils/provenance.py`), `workflow_output`
(referenced from `validation/`), and `example_input` (example agent only).

All hooks are registered as `PostToolUse` on `Write|Edit|MultiEdit` in
`.claude/settings.json`.

### Command-line entry points

Everything reusable is callable without a Claude Code session:

| Command | What it does |
| --- | --- |
| `python -m atlas_chat.cli_project` | `paths`: a project's locations, from its name under `projects/`. `outline`: its annotation hierarchy |
| `python -m atlas_chat.cli_paper_ingest` | a paper plus its indexed supplementary prose, assembled for reading |
| `python -m atlas_chat.cli_subject_block` | what a reader is told about a cell set, from CAS+ |
| `python -m atlas_chat.cli_supplement_prose` | supplementary prose: units, record, cas-uptake |
| `python -m atlas_chat.cli_supplements` | supplement store: inventory, adopt, unpack, outline, text, slice, show, check, fetch, triage, papers |
| `python -m atlas_chat.cli_annotate` | traversal boundary: fetch, follow-set, show |
| `python -m atlas_chat.services.local_snippet_index` | local index: build, add, remove, rebuild, check, list, search |
| `python -m atlas_chat.services.fetch_preprint` | DOI to local JATS |
| `python -m atlas_chat.services._jats_parser` | JATS citation extraction |

`/run-workflow` (`.claude/commands/run-workflow.md`) switches a session into
content mode by loading `CLAUDE.md`.

### Where CAS+ lives

CAS+ is owned here, in Atlas-reporter. `cxg-author-probe`
(github.com/Cellular-Semantics/cxg-author-probe) stops at its three wire schemas
— `probe-v1`, `picks-v1`, `pulled-v1`: it handles dataset formats, describes obs
columns, picks the author cell-type columns and pulls them. It has no opinion
about CAS.

This needs stating explicitly because the repository has argued both ways. A
July 2026 plan pushed CAS assembly upstream, making the module produce CAP+ and
Atlas-reporter merely consume it; that position was later reversed. The
consequence of the reversal is visible: `schemas/cas-v1.schema.json` on the
module's unmerged `cas-annotation-upstream` branch is a near-copy of our
`cas_annotation.schema.json` — identical `Annotation` definitions, differing only
in `schema_version`/`data_provenance` upstream against `AstaIndexing` here, plus
a looser `required`. Two copies, already drifting in both directions.

Reconciling them into the one here, and porting the module's CAS assembler down
rather than merging it up, are in
`planning/plan_cxg_probe_integration_2026-09.md`. Until that happens, treat
`src/atlas_chat/atlas_chat/schemas/cas_annotation.schema.json` as the only
authority and the upstream branch as unadopted.

That plan also settles how atlases are ingested. Extraction is improvised per
atlas by an agent, under the rule that **the agent writes the script and the
numbers come from the library** — a small set of functions with correctness rules
that must hold identically across projects (profiling, assembly, validation, the
summary). Ingest is iterative rather than single-pass: which papers are subatlases
is setup knowledge, so CAS+ is enriched across passes, each with its script saved
alongside its output. The schema's field descriptions are therefore the
specification an agent works from; every field now carries one, and a test keeps
it that way.

`cas_annotation.schema.json` also carries the two denominators the subatlas
overlap measures divide by — `SubatlasPaper.cell_sets[]` and
`TransferredAnnotation.subatlas_contribution_cells` — both direct counts from the
per-cell table. `title` and `source` are no longer required at the root, since a
document assembled from a dataset does not yet know its paper.

The module is not yet a dependency on `dev`, and has no release — 0.1.0, no tags,
no PyPI.

### Known gaps on `dev`

Real discrepancies, listed so nobody rediscovers them:

- **`curation_guard.py` does not exist on `dev`.** `CLAUDE_dev.md` documents it
  as a `PreToolUse` hook restricting non-developer writes to `projects/` and
  `planning/`, and describes a regression test for it. The original lives on
  `feat/orchestration-contracts`, and its behaviour did not match that
  description. A reconstruction is on `feature/curation-guard` — see below.
- **No validator hook** for `supplementary_findings`, though it has a schema.
  `CLAUDE_dev.md` requires one per output schema. (`all_summaries.json` is
  covered: `check_evidence_summary.py` fires on it.)
- **Most subagents declare no input/output front-matter** —
  `resolve-name`, `cl-term-request` and `synthesize-report` declare nothing;
  `scan-supplements` declares output only. Retrofitting these is the follow-up work
  named in `CLAUDE_dev.md`.
- **Legacy annotation file still in use.** `load-project-context` and
  `anndata-zarr-summary` work with the flat `cell_type_annotations.json`, not CAS+.
- **No CLI** for `subatlas_resolver`, which is otherwise service-shaped.
  `supplement_fetch` is reachable as `cli_supplements fetch`.
- **Two CAS schemas exist**, one here and one on an unmerged `cxg-author-probe`
  branch — see [Where CAS+ lives](#where-cas-lives).

### Not yet incorporated

Finished or near-finished work sitting on branches, not merged into `dev`.
`planning/branch_state_and_merge_plan_2026-09.md` holds the merge plan.
`feat/orchestration-contracts` is an older, partly-reverted branch: it holds
eight input/output schemas and front-matter for all six subagents, some of it
overfitted. Worth picking over, not merging.

- **`feature/curation-guard`** — `curation_guard.py` reconstructed from
  `feat/orchestration-contracts` and rebuilt: `projects/` and `planning/` open to
  everyone, all other paths writable only by a trusted git identity, and only once
  `CLAUDE_dev.md` has been loaded into the session (checked against the session
  transcript). With `tests/unit/test_curation_guard.py` and a corrected
  `CLAUDE_dev.md` description.
- **`feature/pdf-text-extract`** (6 commits ahead) — PDF text extraction as a
  service, CLI and skill; describing supplement units with Haiku subagents.
- **`feature/lit-search-mvp`** (9 ahead) — query-driven selection of target cell
  types over CAS+ and per-cell-type aspect decomposition; JATS-first routing and a
  whole-text reader (`paper_router`, `jats_reader`); literature search as skills
  (`gather-evidence`, `coverage`, `free-search`); blockquote attribution checking in
  report validation; seeding traversal on the paper that defines the cell type.
- **`feature/subatlas-consistency`** (5 ahead) — integration provenance produced
  from `obs`; the subatlas contributor cutoff and its two denominators; the
  consistency judgement and primacy call.
- **`feature/subatlas-scoring`** (1 ahead) — scoring atlas cell sets against
  subatlas cell sets, and cutting a read plan. Implements the four overlap
  measures (`purity`, `fraction_of_subatlas_set`, `fraction_of_atlas_set`, `f1`)
  over `subatlas_scores.schema.json`. It derives the per-subatlas-cell-set total
  post hoc, by summing across a partition of the atlas, which fails on atlases
  with no usable partition (a `degraded` run, where `fraction_of_subatlas_set`
  and `f1` cannot be computed). The plan is to record that total at ingest
  instead, where it is a direct count — see
  `planning/plan_cxg_probe_integration_2026-09.md`. Merge this branch rather
  than recomputing the measures.
- **`query-decomposer`** (4 ahead, 23 behind) — the earlier home of the layer A/B
  work now also carried on `lit-search-mvp`, plus `test_projects/` run tracking.
  Largely superseded.
- **`test/retrieval-matrix`** (12 ahead) — retrieval experiments, harness and
  write-ups. Findings and data, not pipeline code.

### Deprecated

Kept for reference and regression comparison. Do not extend.

- **`cli.py`** — the `atlas-report` console script.
- **`graphs/`** — `report_graph.py`, `graph_agent.py`, `definitions.py`, the
  PydanticAI graph orchestration.
- **`llm/`** — `create_agent()` over `cellsem_llm_client`, the provider-neutral
  factory used by the graph. This is the LLM-calling code, and it is deprecated
  along with the pattern: model calls belong in subagents, not in Python. Services
  prepare inputs and record outputs; they do not call a model.
- **`agents/example_agent.py`** and `example_agent.prompt.yaml`.
- The graph-era prompt YAMLs are a mixed case: `name_resolver`,
  `supplementary_scanner`, `report_synthesizer` and `orchestrator` remain canonical
  and are imported by `CLAUDE.md`; `snippet_summarizer.prompt.yaml` belongs to the
  graph path only.
- `services/europepmc.py` is documented as a client "for the programmatic graph
  path".
