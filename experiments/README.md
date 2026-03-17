# experiments/

Home for exploratory scripts and Week 0 validation work.

## Purpose

- **Week 0 validation scripts** — quick probes against external APIs to document
  constraints before writing production code (see `CLAUDE.md` → Week 0 section)
- **Exploratory prototypes** — trying different prompt strategies, testing API shapes,
  or sketching data transformations before committing to a design
- **One-off analysis scripts** — ad-hoc queries not part of the repeatable test suite

## Rules

- **Not subject to TDD**: scripts here do not need tests
- **Not subject to type checking**: mypy does not scan this directory
- **Not subject to linting**: ruff does not lint or format this directory
- **Excluded from coverage**: pytest-cov omits this directory

## When to graduate code out of here

Once an exploratory script proves a pattern that will be used in production,
move the logic into `src/atlas-chat/` and write tests for it there.
Leave the original script here as a record — it provides context for *why* the
production implementation was designed the way it was.
