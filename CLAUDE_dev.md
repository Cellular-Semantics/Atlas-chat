# atlas-chat — Developer Guide (agentic workflows & skills)


**How to build and extend this project's agentic workflow, skills, and supporting code.**

> **This is the dev-mode guide. Load it explicitly when doing development work.**
> The default session loads `CLAUDE.md` (the run/content workflow). This file is
> for *building* the workflow — its skills, subagents, schemas, validators, and
> the Python utilities they call.

> **Deprecated — programmatic path.** This project began with a parallel
> **programmatic** PydanticAI graph (`src/.../graphs/`, the `atlas-report` CLI in
> `cli.py`). That path is deprecated and retained for reference / regression
> comparison only. **Build new functionality as agentic orchestrations (skills /
> subagents), not as graph nodes.** See "Deprecated: programmatic path" at the end.

---

## Writing style

Avoid CLAUDE-ish! 

Write/interact like a human being.  Write like a literate senior developer, using plain English.  Some chattiness and humour is OK, but standard claude-code prose structure is increasinhly exahausting to read. Avoid flight metaphors (lands), no seams please. Don't develop your own terminology in one response to use in the next...  

Examples:
Write "The data is correct, but the format is hard to read"
NOT: "The data clears the correctness gate, readability not substance is the load-bearing blocker"

ALWAYS AVOID THE LATTER PATTERN - I don't want to hear about gates or load-bearing blockers and I don't want to see plain English mangled into constructions like this.

Some particularly egregious past examples:

"The agent's context/session already is its run state — forcing it to also marshal a batch manifest is ceremony."

"That's not defensive hygiene, it's the absence of a trust anchor showing through."

"every seam I hit sits exactly there. That's not coincidence."

"So the inversion converts one type-2 enumerative question (retrieval-hostile, needs a union over scattered passages) into a batch of type-1 localised verifications (retrieval-easy)."

(In this example you invented a typology and one response and then folded into subsequent responses)

"This is the cheap way to build the span-grounded gold I was pushing for. Generate candidates from priors, sweep lexically (free), then human-adjudicate a 5-way relation label on a short span"

(5-way relation label???!!! Really??!!!)


## Schema-first commandment

**JSON Schema is the single source of truth.** Define the shape as a JSON Schema
file under `src/atlas_chat/atlas_chat/schemas/`, then generate Pydantic models from
it — never hand-write a Pydantic model that duplicates a schema.

```python
# 1. Define JSON schema (schemas/*.schema.json) — source of truth
# 2. Generate a Pydantic model from it (cellsem-llm-client utilities)
Model = create_model_from_json_schema(schema)
# 3. Validate / correct structured output
result = Model.model_validate(llm_output)            # strict
result = Model.model_validate(llm_output, strict=False)  # drop extras with warning
```

Load schemas with the existing helper rather than re-reading files:

```python
from atlas_chat.schemas import load_schema
schema = load_schema("cl_mapping.schema.json")
```

**Schema principles:**
- `additionalProperties: false` on objects — reject drift.
- Separate domain (biology) shapes from business/process shapes.
- Reuse components; the validation package imports from `atlas_chat.schemas`, never
  re-declares.

---

## DO NOT OVERFIT

In discussion and development of prompts, skills, schemas we will inevitably use examples in discussion and testing.  Be very careful about making generalising assumptions about the shape of inputs based on the limited examples you have seen.  If you do make such assumptions in a proposal/plan  - examine them all critically - are they needed, do they fit the most general/minimal use cases & ASK before assuming.

Details of examples, test results and plans DO NOT belong in prompts, schema descriptions, code doc or comments. 

## DO NOT OVERENGINEER

When prosing increased complexity in workflow, skill, schema, code - ask if it is necessary.  Be particularly wary of bespoke enmum fillers in schemas.  Are they really necessary?  Do they represent some semi-abitrary, congintent set of possible fillers or do they both plausibly cover the domain AND do useful work.

## Modular orchestrations with declared shapes

The agentic workflow is built from small, composable **orchestration units** — a
`.claude` skill (`.claude/skills/*/SKILL.md`) or subagent (`.claude/agents/*.md`).
Each unit **declares its contract in YAML front-matter**: the input object it
expects and the output object it produces. Shapes are not described in prose —
they **reference declared JSON Schemas** (the schema-first commandment above).

```yaml
---
name: ontology-term-lookup
description: ...
model: sonnet
input:
  schema: src/atlas_chat/atlas_chat/schemas/ontology_lookup_input.schema.json
output:
  schema: src/atlas_chat/atlas_chat/schemas/cl_mapping.schema.json
---
```

**Why:**
- **Composability** — the output of one orchestration is the typed input of the
  next. The workflow in `CLAUDE.md` is a sequence of these contracts
  (name_resolution → supplementary_findings + all_summaries → report → cl_mapping
  → cl_term_request).
- **Enforced at the boundary** — a `PostToolUse` hook validates the produced object
  against the named **output** schema (e.g. `check_cl_mapping.py` →
  `cl_mapping.schema.json`, `check_cl_term_request.py` →
  `cl_term_request.schema.json`). Add a validator hook whenever you add an output
  schema, and register it in `.claude/settings.json`.
- **Discoverable** — `grep -rn "schema:" .claude/agents .claude/skills` lists every
  contract in the workflow.



**Build it so it can be lifted out.** When adding functionality, ask: *how would someone
use this in a different project?* Not because we plan to package everything, but because
the answer forces the right boundaries. A unit that can be lifted out is one that doesn't
reach into our repo layout, doesn't assume our directory names, and states what it needs.

In practice:
- **Take paths as input; don't derive them.** `projects/{project}/...` belongs in the
  orchestrator's call, not baked into the skill or the service it calls. A skill that
  computes its own output path is welded to this repo.
- **Depend on the schema, not on the project.** The contract is the JSON Schema and the
  object it describes. Anything that reads `cas.json` should accept a CAS+ document, not
  a project name it resolves itself.
- **Put the real work in `services/` behind a CLI.** The skill/subagent is thin — it
  decides and gates; the service does the fetching, parsing and writing, and is callable
  by anything (`python -m atlas_chat.cli_annotate ...` is the pattern). Reusable code
  should never require a Claude Code session to run.
- **Keep atlas-reporter-specific glue in the orchestration layer**, so the underlying
  service stays general. `local_snippet_index` is a paper index that happens to be used
  by this workflow, not a piece of this workflow.
- **Name the external requirements** — API keys, optional extras, network services — in
  the unit's front-matter or docstring rather than assuming the ambient environment.

If a new piece of functionality can't be described without referring to atlas-reporter's
directory structure, that's the signal to split it.

**Conventions:**
- One orchestration = one clear input shape + one output shape. If a unit needs two
  unrelated outputs, it is probably two orchestrations.
- Input schema name mirrors the unit: `{unit}_input.schema.json`. Output schema is
  the domain object it yields.
- `ontology-term-lookup` is the worked exemplar. **Retrofitting the remaining
  subagents and skills (`resolve-name`, `scan-supplements`, `citation-traverse`,
  `synthesize-report`, `cl-term-request`, and the `.claude/skills/*`) with
  `input:`/`output:` front-matter and matching schemas is follow-up work** — do it
  as you touch each one.


### Anti Hallucination check

***CRITICAL SPECIFICATION!***

Build infrastructure to ensure tha all JSON artefacts and markdown reports written by agents are checked for halluncination whenever they are written/edited.:
 - Validate all JSON against schema
 - Check ontology name:ID pairs against authoritative source
 - Check publication IDs (DOIs etc) against authoritative source on metadata (e.g. titles) 

 Use Claude hooks to drive this process - write/edit triggers check for changes in output files triggering programatic checks. Specific errors are fed back to agent to fix.  As a backup, orchestration should also trigger checks in case the agent has edited output files using code and so not triggered the claude hook.


---

## Definition of done: the pipeline doc

`docs/pipeline.md` is the implementation map — for each stage of processing, what
runs, what it reads and writes, which schema its output conforms to, and which hook
checks it. It is ordered by the chain of processing, from project setup through
literature search to a finished report.

**A piece of work is not complete until `docs/pipeline.md` reflects it.** Update it
in the same commit as the change, on the branch where the change happens, so the
doc arrives with the merge. That covers a new or changed skill, subagent, service,
CLI, schema or hook; a change to what a stage reads or writes; and anything that
closes or opens one of the gaps the doc lists.

It also carries a "Not yet incorporated" section describing work finished on other
branches. Move an entry out of that section as part of merging it.

Single file for now, on purpose — the workflow is changing too fast for the
bookkeeping of managed subdocuments to pay off. Split it (per-skill and per-agent
pages, say) once the churn settles.

---

## Testing

### Test-driven where it pays

**Use TDD for:** parsers, validators, data transformers (clear in/out); bug fixes
(red → green → refactor); core domain logic once understood.

**Skip TDD for:** exploratory prototypes, prompt-strategy spikes, first-cut API
integration. Exploratory work lives in `experiments/` (excluded from coverage,
mypy, ruff; not subject to TDD).

### Required test structure

```
tests/
├── unit/          # fast, isolated, no external deps   (@pytest.mark.unit)
├── integration/   # REAL external services              (@pytest.mark.integration)
└── conftest.py
```

- **Every test carries a marker** (`@pytest.mark.unit` / `@pytest.mark.integration`).
- **Integration tests use real APIs** — no mocks, no simulated responses. They must
  **fail hard** if credentials are missing (not skip), so quirks surface immediately.
- **CI runs unit tests only** (`uv run pytest -m unit`); integration runs locally.

### Regression tests for validation

The validation logic and orchestration contracts are the project's quality
backbone — they need a **growing regression suite** that pins behaviour as the
workflow evolves:

- **Schema regression** — for each output schema, keep good/bad golden fixtures and
  assert the schema (and any cross-field rules) accept/reject them. The CL-mapping
  baseline lives in `tests/unit/test_cl_mapping_schema.py`: it validates fixtures
  against `cl_mapping.schema.json` and checks the `match_type ↔ skos_mapping` and
  `new_term_needed` consistency rules enforced by `check_cl_mapping.py`. Extend this
  pattern for `cl_term_request` and each new contract.
- **Hook regression** — `tests/unit/test_curation_guard.py` pins the curation-mode
  write gate (allow `projects/` + `planning/`, block everything else, developer
  override). Drive hooks via subprocess with `ATLAS_CHAT_HOOK_USER` set.
- **Report-validation regression** — `validate_report()` and its pure helpers
  (`check_quotes`, `check_references` in `report_checker.py`) are the contract for
  quote/reference grounding; assert their behaviour on known inputs (see ROADMAP
  "Golden-data regression").

These run in CI and must pass before merge. When you change an orchestration's
output or a validator, update the golden fixtures in the same commit.

### Coverage targets

Commits must pass `pytest --cov` above the floor set in `pyproject.toml`
(`fail_under`). Ratchet the floor up as tests are added; do not lower it. Integration
tests are excluded from CI but count locally.

### Commands (uv)

```bash
uv sync --dev                     # install deps incl. dev tools
uv run pytest                     # all tests
uv run pytest -m unit             # unit only (CI)
uv run pytest -m integration      # integration (local, needs API keys)
uv run pytest --cov               # with coverage
uv run mypy src/                  # type check
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
uv run pre-commit run --all-files
python scripts/check-docs.py      # build & check docs
```

---

## Code quality

Pre-commit hook runs automatically on each commit:

```bash
uv run ruff check --fix src/ tests/      # lint (blocks commit)
uv run ruff format --check src/ tests/   # format (blocks commit)
uv run pytest -m unit --cov              # unit + coverage floor (blocks commit)
uv run mypy src/                         # type check (encouraged locally; CI only initially)
```

---

## Environment configuration

Always bootstrap with dotenv; never hardcode secrets or commit `.env`.

```python
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("SOME_API_KEY")
```

**Precedence:** explicit constructor args → environment (`.env`) → sensible defaults.

**Tracing:** Langfuse tracing of the programmatic graph is opt-in via
`--trace` / `ATLAS_CHAT_TRACING=1` (module: `atlas_chat.observability`; guide:
`docs/tracing.md`). Off by default — no client, no export. The agentic
(Claude Code) workflow is traced separately, via Langfuse's Claude Code
integration; see the same guide.

---

## Documentation

Google-style docstrings with RST code blocks (`.. code-block:: python`, not markdown
backticks). Auto-generated API docs (Sphinx + AutoAPI); manual guides in `docs/`
(MyST markdown). Run `python scripts/check-docs.py` before committing.

---

## Repository structure

```
atlas-chat/
├── CLAUDE.md            # default: run/content workflow (the orchestrator's instructions)
├── CLAUDE_dev.md        # this file: developer guide
├── .claude/
│   ├── settings.json    # hooks (curation guard + validators), permissions, MCP servers
│   ├── agents/          # subagents — orchestration units (declare input/output shapes)
│   ├── skills/          # skills — orchestration units (declare input/output shapes)
│   ├── commands/        # /run-workflow etc.
│   └── hooks/           # curation_guard.py + check_*.py output validators
├── src/
│   └── atlas_chat/atlas_chat/
│       ├── schemas/     # JSON schemas — source of truth
│       ├── agents/      # *.prompt.yaml canonical prompts
│       ├── services/    # API integrations (e.g. local_snippet_index, fetch_preprint)
│       ├── validation/  # report_checker.py and cross-cutting validators
│       ├── utils/
│       └── graphs/      # DEPRECATED programmatic PydanticAI graph (reference only)
├── projects/            # CONTENT — per-atlas reports & traversal output (curation zone)
├── planning/            # notes, postmortems, dev requests (curation zone)
└── tests/{unit,integration}/
```

Prompts are co-located with the code/agents that use them, always as `*.prompt.yaml`
(`find . -name "*.prompt.yaml"`; review with `git diff '**/*.prompt.yaml'`).

---

## Curation-mode hook (how it works)

The default session is curation/content mode. `.claude/hooks/curation_guard.py`
(`PreToolUse` on `Edit|MultiEdit|Write`, registered in `.claude/settings.json`) lets
non-developer users write **only** under `projects/` and `planning/`, and blocks
everything else (`src/`, `.claude/`, schemas, docs, root files, anything outside the
repo). The repo developer is recognised by `git config user.email` (in `TRUSTED_USERS`)
and bypasses the gate; tests override the identity via `ATLAS_CHAT_HOOK_USER`. To do
dev work you either have the trusted git identity or run an explicit dev session.

---

## Forbidden / required

**Never:**
- ❌ Mock or simulate responses in integration tests (use real APIs).
- ❌ Skip tests with `pytest.mark.skip` (fix or remove).
- ❌ Build generic abstractions before a specific case works.
- ❌ Rewrite working code without a documented reason.
- ❌ Add new functionality to the deprecated programmatic graph.

**Required:**
- ✅ Real integration tests from day 1.
- ✅ Every orchestration declares input/output shapes referencing JSON Schemas.
- ✅ A validator hook for every output schema, registered in `.claude/settings.json`.
- ✅ Regression fixtures updated in the same commit as a contract/validator change.
- ✅ Extend existing code in preference to rewriting.

---

## Decision checklist (before writing production code)

- [ ] Is the data shape captured as a JSON Schema (source of truth)?
- [ ] Does the orchestration declare `input:`/`output:` front-matter pointing at schemas?
- [ ] Is there an output-validator hook + regression fixture?
- [ ] Have we tested the real external API (integration test first)?
- [ ] Can we extend existing code instead of rewriting?

---

## Deprecated: programmatic path

Retained for reference and regression comparison only — **do not extend**:

- `src/atlas_chat/atlas_chat/cli.py` — the `atlas-report` console script.
- `src/atlas_chat/atlas_chat/graphs/` — `report_graph.py`, `graph_agent.py`,
  `definitions.py` (PydanticAI graph orchestration, `pydantic-graph`).
- `deep-research-client` usage tied to the graph path.

New orchestration goes in `.claude/agents/` and `.claude/skills/` as units with
declared shapes (above). Note: `services/local_snippet_index.py` and
`services/fetch_preprint.py` are **not** part of the deprecated path — they back the
agentic `local-paper-index` skill and remain supported.
