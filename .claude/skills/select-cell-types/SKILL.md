---
name: select-cell-types
description: Turn a request for reports — "all macrophages", "just the L3 ones", a single label — into the list of cell types to read for, by reading the atlas's annotation hierarchy rather than its annotations. Use when a user asks for reports and has not named exact labels.
---

# Skill: select cell types

A request for reports names cell types the way a person would, and the atlas
names them the way its authors did. Closing that gap is a judgement, and this
is where it is made — before a long run rather than during one.

## Do not load the annotations

A CAS+ document is mostly `composition`: the breakdown of every descriptor over
every cell. On a real atlas that is millions of tokens, and none of it says what
a cell type is called or where it sits.

Load the hierarchy instead:

```bash
uv run python -m atlas_chat.cli_project outline --project <project> [--synonyms]
```

One line per annotation — labelset, label, full name, parent, cell count — at
roughly a two-hundredth of the size. Read it whole.

## Which project

```bash
uv run python -m atlas_chat.cli_project paths --project <project>
```

Where `projects/` holds exactly one project, use it without asking. Where it
holds several, list them and ask. A project filed in a subdirectory is named
with it, `test_projects/<name>`: a bare name never reaches past `projects/`,
because a test project standing in for a working atlas of the same name is not
a mistake anyone would catch by reading the output.

## Find the node, then take what is under it

**Text matching alone is not enough, and fails quietly.** A cell type's label
need not contain the word for what it is, and siblings' labels need not
resemble each other. Asking for macrophages on one real atlas:

| | |
|---|---|
| substring over the label alone | 1 of 7 |
| substring over label, full name and synonyms | 7 |
| the subtree under the population called `Macrophages` | its 6 children, exactly |

Two of those six are named for where they are and what they contain, and say
nothing about being macrophages. A match would drop them and return an answer
that looks right.

So: **find candidate roots by text, then take the subtree.** `--under <label>`
does the second part. Fall back to a flat match only when nothing resolves to a
node — and say that you have.

For the same reason, **do not narrow before loading**. `--match` and
`--labelset` are for an atlas too large to read whole; used routinely they hide
the structure that makes the subtree visible.

## Say what you decided, and check

The request is vague on purpose, so answering it means making calls the user did
not make. State them:

- whether a parent is included as well as its children — "all macrophages" may
  mean the six subtypes, or those plus the population they belong to;
- anything left out as a cell state rather than a cell type;
- anything included on a resemblance you are not sure of.

**Then show the selection — labels and cell counts — and wait.** A count is
often what tells someone they did not mean to include something, and a
selection governs everything downstream: getting it wrong is discovered when
the reports come back.

Record the request and what it resolved to alongside the run, so the judgement
can be reviewed later rather than reconstructed.

## Then

Hand the labels to the reading step. It takes a project and a list of cell
types and assembles everything else itself.
