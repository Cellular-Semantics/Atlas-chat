---
name: retrieve-paper
description: Get a paper's text — tagged article XML where it can be had, an open-access PDF where it cannot, and a specific ask where neither works. Walks Europe PMC, the preprint servers and an open-access resolver, records how each paper actually arrived, and matches files a user has already dropped somewhere to the papers they are. Needs the [text-access] extra (curl_cffi, PyMuPDF).
output:
  schema: src/atlas_chat/atlas_chat/schemas/paper_retrieval.schema.json
---

# retrieve-paper

Getting the text is the first thing a project needs and the thing most likely to
come up short. On a real subatlas corpus of 22 papers, Europe PMC serves 14, a
preprint server one, an open-access resolver one, and six are not reachable by
any automated route at all. **Those six are the job**, as much as the sixteen:
asking a user for a paper is a route, and an ask that names the paper and where
to find a free copy is worth far more than a line saying retrieval failed.

The schema is the contract and documents its own fields. Read it rather than
looking for the field list here.

## Requirements

- The `[text-access]` extra: `uv sync --extra text-access` (curl_cffi for hosts
  that fingerprint the client, PyMuPDF for reading PDFs).
- A contact address for the open-access resolver, which requires one on every
  request: `ATLAS_CHAT_CONTACT_EMAIL`, or the checkout's `git config user.email`.
  Without it that rung reports itself skipped and you will under-count what is
  retrievable.

## The mechanical half

Everything that touches bytes is in `atlas_chat.services.paper_fetch`, behind a
CLI. Use it rather than fetching papers yourself: a paper is megabytes and none
of it should pass through your context.

```bash
# Walk the waterfall. Repeatable --doi, or a whole corpus at once.
uv run --extra text-access python -m atlas_chat.cli_paper fetch \
  --out <papers-root> --doi <doi> [--retry] [--no-pdf] [--contact <email>]
uv run --extra text-access python -m atlas_chat.cli_paper fetch \
  --out <papers-root> --cas <cas.json>          # atlas + its subatlas papers
uv run --extra text-access python -m atlas_chat.cli_paper fetch \
  --out <papers-root> --doi-file <file>         # one DOI per line

# What in a drop zone could be a paper: the DOI each file declares, its opening
# title, its size. Recursive.
uv run --extra text-access python -m atlas_chat.cli_paper candidates --inputs <dir>

# Take one of those files in as a given paper.
uv run --extra text-access python -m atlas_chat.cli_paper adopt \
  --out <papers-root> --doi <doi> --file <path>

# One paper's record, with any inconsistency flagged.
uv run python -m atlas_chat.cli_paper show --out <papers-root> --doi <doi>

# Recover text from a PDF on its own, and see how much came out.
uv run --extra text-access python -m atlas_chat.cli_paper text --pdf <path>
```

`fetch` is idempotent and cheap to re-run: a paper already here is not
re-fetched, and a paper recorded as unreachable is not re-attempted until you
pass `--retry`. Run it over the whole corpus first and work from what comes back.

## What is yours to judge

The CLI decides nothing that needs judgement. Four things do.

### Which file in a drop zone is which paper

A drop zone is a flat bag — papers, supplementary spreadsheets and figures
together, named however they arrived (`media-1.pdf`, `2026.06.10.731198v1.full.pdf`).
Nobody is asked to sort it, so you sort it. `candidates` gives you each file's
declared DOI, its opening title and its size; match those against the papers you
are missing and `adopt` each one. Where a file declares no DOI and its title is
ambiguous, ask rather than guess — adopting the wrong file files a paper under
another paper's DOI, and nothing downstream will catch it.

### Whether a resolver's hit is the paper or a manuscript of it

`oa_candidates` on the record carries each location's `version` and `host_type`
verbatim. A `submittedVersion` in a repository is the manuscript before peer
review: the science is usually the same, but the text is not the published text,
so a quote from it may not appear in the article a reader opens. Where the paper
was taken from one, **say so when you report the retrieval** — it is a caveat
about provenance that a later reader cannot recover from the text alone.

### Whether a PDF became something worth reading

`text_quality` says how much came out and shows the opening. A scan of page
images extracts to a few short fragments; a paper extracts to tens of thousands
of characters in whole sentences. The CLI flags the blatant case, but read the
sample: text that is the right size and still gibberish is a real outcome.

Recovered PDF text is worse than article XML in two specific ways, and both
matter downstream:

- **No reference markup.** No citation can be resolved from it, so citation
  traversal has nothing to walk.
- **No guaranteed reading order across a column boundary.** Each paragraph is
  internally coherent, but a quote spanning a boundary may correspond to nothing
  a reader of the article would ever see.

So prefer XML where there is a choice, and where there is not, treat what you
get as usable rather than equivalent.

### When to stop and what to ask for

When every rung has run, stop. Do not go looking for the PDF yourself: the hosts
that block the CLI block you too, and a paper behind a subscription is not a
puzzle to solve. Report the papers with `route: none` as a list, each with the
free copy the record found (`gap.action` already names it) and the `adopt`
command to run afterwards. **Ask for all of them in one go**, not one at a time.

## Reporting a corpus

Give the user a table of DOI, route, and size, and then the gaps. Say what the
routes mean rather than only naming them — `unpaywall / pdf` and `europepmc /
jats` are not the same quality of source. Be straight about the count: a corpus
where six of twenty-two papers need asking for is a normal result, and rounding
it off to "mostly retrieved" hides work the user has to do.
