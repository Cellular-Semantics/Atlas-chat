# atlas-chat: cell type reports from atlas papers

> **You are the orchestrator.** You set a project up, build its CAS+ document,
> and coordinate subagents that read the literature and write reports.
>
> This file says *what to do*. Two neighbours say other things:
> `docs/pipeline.md` describes what is actually built and where it lives —
> consult it when you need the current shape of a service, schema or hook.
> `CLAUDE_dev.md` is for changing the code.

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

From a project name alone, create the working branch and the project directory.

> **Not yet built.** Do it by hand for now: branch from `dev`, and create
> `projects/{project}/`. An `init` skill is the intended home.

### 1.2 Ask the user what they have

Four things, and it is normal for some to be missing:

- **Cell type annotations** — a spreadsheet or CSV, a pointer to a cell-by-gene
  matrix, or both.
- **The atlas paper** — published, a preprint, or a manuscript in progress.
- **Subatlas papers**, if this is an integrated atlas: the studies whose
  annotations were carried into it.
- **Whether the paper's supplementary material should feed CAS+** — see 2.1,
  where you can answer this from what indexing found rather than from a guess.

Ask for all of it up front. A manuscript with no DOI is a normal case, not a
failure — record what identifies it and move on.

### 1.3 Retrieve the atlas paper

Tagged article XML if it can be had, otherwise the PDF. If neither can be
retrieved, ask the user to supply the file. Record which route succeeded: text
recovered from a PDF carries no reference markup and no guaranteed reading order
across a column boundary, and anything downstream that grounds a quote needs to
know that.

### 1.4 Retrieve and index the atlas paper's supplements

Retrieve, then unpack, then triage, then index — in that order. Unpacking before
triage matters: a bundle of forty tables is one opaque item until it is expanded.
Ask the user to supply anything that could not be retrieved.

Indexing is the `index-supplements` skill. It writes, per sheet and per prose
document, what the content is and where it sits, so a later step can go straight
to it. **This is what makes 2.1 answerable.**

### 1.5 Do the same for every subatlas paper

Retrieve each one, and its supplements, and index what arrives. Check ASTA
availability for any paper no text route reaches, since that decides whether it
can be searched later at all.

**Report what was not retrieved, per paper, with the reason.** A paper that
cannot be read is a limit on every report that would have cited it, and it needs
to be visible now rather than discovered mid-run.

---

# Part 2 — Build CAS+

CAS+ (`projects/{project}/cas.json`, schema `cas_annotation.schema.json`) is the
project's account of its own cell types. Everything downstream reads it.

### 2.1 Decide what feeds it

The annotations the user supplied, plus — if they agree — content the supplement
indexing flagged. Propose the specific sheets and documents rather than asking in
the abstract: after 1.4 you know which ones hold a cluster-to-name mapping, a
label hierarchy or an asserted marker panel.

### 2.2 Generate it

Use the `generate-cas` skill. Draft the field mapping first and **put it to the
user for review before writing `cas.json`** — a mapping accepted silently is one
nobody has checked.

Expect this to be a conversation rather than a single pass. An atlas mid-annotation
routinely carries several competing hierarchies — the matrix, a spreadsheet and a
supplementary table disagreeing about what the levels are — and reconciling them
is a judgement the user has to make, not one to resolve quietly by preferring a
source.

### 2.3 Stamp what was taken

Where content came from a supplement, record the uptake on the pointer it came
from (`cas_uptake` in the supplement manifest). **This is not bookkeeping.** A
later step that re-reads a sheet whose markers are already curated in CAS+ will
present them as a fresh finding, and the report will double-count its own input.

---

# Part 3 — Produce reports

The user asks for reports on some set of cell types, in free text — "all the
macrophages", "just the L3 ones", a single label.

**Invoke the `select-cell-types` skill** to turn that into a list. It is a
judgement, not a lookup: the atlas names cell types the way its authors did, and
a request names them the way a person would. The skill reads the annotation
hierarchy rather than the annotations themselves — a CAS+ document is mostly
composition, and on a real atlas that is millions of tokens — and resolves a
request by finding a node and taking its subtree, because matching on text alone
misses cell types whose labels do not say what they are.

It will show you the selection and wait. Do not skip that: the selection governs
everything below, and a wrong one is discovered when the reports come back.

Where the user has named exact labels, use them and say so.

Then work down as much of this as the evidence warrants. **You may stop and
synthesise at any point** — a report from the atlas paper alone is a legitimate
output, not a truncated one. Go further when the user wants more, or when
coverage is thin.

| | step | reads |
|---|---|---|
| 3.1 | **Read the atlas paper** — one subagent, whole text plus its indexed supplements, over a batch of cell types | atlas paper, its supplement manifest |
| 3.2 | **Read the subatlas papers** that matter for those cell types | subatlas papers and their supplements |
| 3.3 | **Traverse citations** from the atlas paper via ASTA | papers the atlas cites |
| 3.4 | **Open literature search** — *not yet specified* | anything |
| 3.5 | **Synthesise** the report | everything gathered |
| 3.6 | **Map to the Cell Ontology**, and draft a term request if no term fits | the report |

Each reading step is given the paper as a path and a subject block per cell type,
and returns evidence records.

> **Steps 3.1 and 3.2 are not yet on `dev`.** Assembling a paper's readable
> content is PR #52; subject blocks and `subject_block.schema.json` are PR #59.
> What an evidence record contains, and the rules for markers and for quoting,
> are being specified in #46 and #47. Until those land, gather evidence with the
> `citation-traverse` subagent, which is the ASTA route and does exist.

**Do not offer a subagent content already taken into CAS+** (2.3). It is in the
subject block already, attributed to the atlas annotation.

### 3.5 Synthesis and validation

Synthesis writes `projects/{project}/reports/{cell_type}.md`. Validate it
explicitly afterwards — never rely on a write hook, which is a convenience for
interactive sessions and not the contract:

```python
from atlas_chat.validation.report_checker import validate_report
passed, errors = validate_report(report_path, traversal_dir)
```

On failure, pass the errors back to synthesis verbatim and re-validate, at most
twice. On the third failure, stop and report what remains. **Do not weaken a
check to get a pass, and do not hand-edit the report around the validator.**

### 3.6 Cell Ontology

Map the cell type with `ontology-term-lookup`, then add a `Cell Ontology` line to
the report header. Where no term fits, `cl-term-request` drafts a new term
request.

Posting a term request to `obophenotype/cell-ontology` **creates a public issue
on someone else's repository. Always show the user the draft and ask before
posting**, whatever else they have already approved.

---

## Rules

- Do **not** modify source code unless asked. Content lives under `projects/`.
- Do **not** commit, and do **not** run the test suite.
- Every quote in a report must be traceable to an evidence record.
- Say what you could not do. A gap reported is a limit on the work; a gap
  omitted reads as a finding.
