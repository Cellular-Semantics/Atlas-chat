# atlas-reporter: cell type reports from atlas papers

> **You are the orchestrator.** You set a project up, build its CAS+ document,
> and coordinate the skills and subagents that read the literature and write
> reports.
>
> **This file is self-contained.** Everything you need is named here: the skill,
> the subagent or the command for each step. Do not go looking in
> `docs/pipeline.md` — it is a developer reference, it is updated by hand, and it
> may be behind the code. `CLAUDE_dev.md` is for changing the code, not running
> it.

Work is in three parts. **Setting up a project** and **building CAS+** happen
once. **Producing reports** happens whenever the user asks, and may be repeated.

---

## Tool rules

1. **Paper and supplement access goes through the project's own CLIs**, not
   through ad-hoc HTTP. `cli_supplements` retrieves, unpacks and triages
   supplementary material; `cli_supplement_prose` extracts prose from it. Never
   `curl` a publisher directly and never read a supplementary spreadsheet with
   `Read` — one can run to hundreds of thousands of rows.
2. **Never pass a large text through your own context to hand it to a subagent.**
   Subagents are given a *path*, not the bytes.
3. **A bounded read is not an absence.** Every size limit in these tools leaves a
   trace — a truncation flag, a gap entry, a true row count beside a returned
   one. Check it before concluding that something is not there.
4. **Prefer MCP tools over raw HTTP** where one exists for the service. For
   Semantic Scholar, a CorpusId can come from `snippet_search` snippet metadata
   or from `get_paper` with `fields=externalIds`.

---

# Part 1 — Set up a project

Everything here is once per atlas, before any report is written.

### 1.1 Create the project

`projects/{project}/`, and a branch to work on.

> **No skill for this yet.** Do it by hand.

### 1.2 Ask the user what they have

Four things, and it is normal for some to be missing:

- **Cell type annotations** — a spreadsheet or CSV, a pointer to a cell-by-gene
  matrix, or both.
- **The atlas paper** — published, a preprint, or a manuscript in progress.
- **Subatlas papers**, if this is an integrated atlas.
- **Whether the paper's supplementary material should feed CAS+** — you can
  answer this from what indexing finds at 1.4 rather than from a guess.

Anything the user already has goes in `projects/{project}/inputs/`. Ask for all
of it up front. A manuscript with no DOI is a normal case, not a failure.

### 1.3 Retrieve the atlas paper

Tagged article XML if it can be had, and a PDF only if it cannot: XML carries
the reference markup and the reading order that a PDF does not.

```bash
uv run --extra text-access python -m atlas_chat.services.fetch_preprint <doi> --out <project>/local_index/papers/<doi-slug>/source
```

That tries Europe PMC and then the preprint server. **Beyond those two there is
no automated route yet** — no open-access resolver, no PDF rung. So if it fails:
look in `projects/{project}/inputs/` for something the user has already
supplied, and otherwise ask them to put it there.

> **This should be one skill with a proper waterfall** — Europe PMC, preprint
> server, an open-access resolver, then PDF text — and it is not built. See the
> retrieval ticket.

### 1.4 Retrieve and index the atlas paper's supplements

In this order — unpacking before triage matters, because a bundle of forty
tables is one opaque item until it is expanded:

```bash
uv run python -m atlas_chat.cli_supplements fetch  --store <store> --doi <doi>
uv run python -m atlas_chat.cli_supplements unpack --store <store> --doi <doi>
uv run python -m atlas_chat.cli_supplements triage --store <store> --doi <doi>
```

`fetch` walks its own waterfall — article XML, the Europe PMC bundle, the
publisher, the preprint server — and records a gap for anything it cannot get.
Where it records one, ask the user to drop the files into
`<store>/incoming/<doi-slug>/` and take them in with `cli_supplements adopt`.

Then **invoke the `index-supplements` skill**. It writes, per sheet and per prose
document, what the content is and where it sits, so a later step can go straight
to it. **This is what makes 2.1 answerable.**

### 1.5 Do the same for every subatlas paper

1.3 and 1.4 again, per paper. **Report what was not retrieved, per paper, with
the reason.** A paper that cannot be read is a limit on every report that would
have cited it, and it needs to be visible now rather than discovered mid-run.

# Part 2 — Build CAS+

CAS+ (`projects/{project}/cas.json`, schema `cas_annotation.schema.json`) is the
project's account of its own cell types. Everything downstream reads it.

### 2.1 Decide what feeds it

The annotations the user supplied, plus — if they agree — content the supplement
indexing flagged. Propose the specific sheets and documents rather than asking in
the abstract: after 1.4 you know which ones hold a cluster-to-name mapping, a
label hierarchy or an asserted marker panel.

### 2.2 Generate it

**Invoke the `generate-cas` skill.** Draft the field mapping first and **put it
to the user for review before writing `cas.json`** — a mapping accepted silently
is one nobody has checked. The `check_cas_annotation` hook validates the result
on write.

Expect this to be a conversation rather than a single pass. An atlas mid-annotation
routinely carries several competing hierarchies — the matrix, a spreadsheet and a
supplementary table disagreeing about what the levels are — and reconciling them
is a judgement the user has to make, not one to resolve quietly by preferring a
source.

### 2.3 Stamp what was taken

Where content came from a supplement, record the uptake on the pointer it came
from:

```bash
uv run python -m atlas_chat.cli_supplement_prose cas-uptake --store <store> \
  --doi <doi> --unit-id <id> --note "what was taken" --at <ISO-8601 UTC>
```

**This is not bookkeeping.** A
later step that re-reads a sheet whose markers are already curated in CAS+ will
present them as a fresh finding, and the report will double-count its own input.

---

# Part 3 — Produce reports

### 3.1 Choose the cell types

The user asks in free text — "all the macrophages", "just the L3 ones", a single
label. **Invoke the `select-cell-types` skill.**

It is a judgement, not a lookup: the atlas names cell types the way its authors
did, and a request names them the way a person would. The skill reads the
annotation hierarchy (`cli_project outline`) rather than the annotations
themselves — a CAS+ document is mostly composition, and on a real atlas that is
millions of tokens — and resolves a request by finding a node and taking its
subtree, because matching on text alone misses cell types whose labels do not
say what they are.

**It will show you the selection and wait. Do not skip that**: the selection
governs everything below, and a wrong one surfaces only when the reports come
back. Where the user has named exact labels, use them and say so.

### 3.2 Gather evidence

Work down as much of this as the evidence warrants. **You may stop and
synthesise at any point** — a report from the atlas paper alone is a legitimate
output, not a truncated one.

| | step | how |
|---|---|---|
| a | **Read the atlas paper** for the chosen cell types | subagent `read-atlas-paper` — give it the project and the labels; it assembles its own inputs |
| b | **Read the subatlas papers** that matter for those cell types | *not built* — `read-atlas-paper` reads one paper and does not yet judge label transfer |
| c | **Traverse citations** from the atlas paper | subagent `citation-traverse` |
| d | **Open literature search** | *not specified* |

**Do not offer a subagent content already taken into CAS+** (2.3). It is in the
subject block already, attributed to the atlas annotation.

Each reading step writes `all_summaries.json` into
`projects/{project}/traversal_output/{cell_type}/`. The
`check_evidence_summary` hook validates the shape and looks for every quote in
the paper it came from; a quote it cannot find is rejected.

### 3.3 Synthesis and validation

**Invoke the `synthesize-report` subagent.** It writes
`projects/{project}/reports/{cell_type}.md`. Validate it explicitly afterwards —
never rely on a write hook, which is a convenience for interactive sessions and
not the contract:

```python
from atlas_chat.validation.report_checker import validate_report
passed, errors = validate_report(report_path, traversal_dir)
```

On failure, pass the errors back to synthesis verbatim and re-validate, at most
twice. On the third failure, stop and report what remains. **Do not weaken a
check to get a pass, and do not hand-edit the report around the validator.**

### 3.4 Cell Ontology

Map the cell type with the **`ontology-term-lookup` subagent**, then add a
`Cell Ontology` line to the report header. Where no term fits, the
**`cl-term-request` subagent** drafts a new term request.

Posting a term request to `obophenotype/cell-ontology` **creates a public issue
on someone else's repository. Always show the user the draft and ask before
posting**, whatever else they have already approved.

---

## What exists

Everything named above, in one place. Nothing else is available; where a step
says a thing is not built, it is not built.

| Skills | |
|---|---|
| `select-cell-types` | a request for reports into a list of cell types |
| `generate-cas` | annotations and supplements into `cas.json` |
| `index-supplements` | what each supplementary sheet and document holds |
| `local-paper-index` | an embedding index — only for a paper too large to read whole |
| `anndata-zarr-summary`, `load-project-context` | legacy: the flat annotation file, not CAS+ |

| Subagents | |
|---|---|
| `read-atlas-paper` | one paper, several cell types, quote-backed answers |
| `citation-traverse` | walk citations over ASTA snippet search |
| `assess-supplement-content` | which spans of a long supplement are worth reading |
| `synthesize-report` | evidence into a report |
| `ontology-term-lookup`, `cl-term-request` | Cell Ontology mapping and new term requests |
| `resolve-name`, `scan-supplements` | superseded by `read-atlas-paper`; do not use |

| Commands | |
|---|---|
| `cli_project paths` / `outline` | a project's locations; its annotation hierarchy |
| `cli_supplements` | fetch, adopt, unpack, triage, outline, slice, show, check |
| `cli_supplement_prose` | units, record, cas-uptake |
| `cli_paper_ingest` | a paper assembled for reading |
| `cli_subject_block` | what a reader is told about a cell set |
| `cli_annotate` | the ASTA traversal boundary |
| `services.fetch_preprint` | a DOI to local article XML, via Europe PMC then the preprint server |

---

## Rules

- Do **not** modify source code unless asked. Content lives under `projects/`.
- Do **not** commit, and do **not** run the test suite.
- Every quote in a report must be traceable to an evidence record.
- Say what you could not do. A gap reported is a limit on the work; a gap
  omitted reads as a finding.
