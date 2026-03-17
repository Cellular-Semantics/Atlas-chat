# CellSem Agentic Workflow - Development Guide

**Template for building robust agentic workflows with integrated validation**

This CLAUDE.md should be copied to each new agentic workflow project and customized for that project's specifics.

---

## Development Philosophy

### Core Principle: Scope Rings

**Every project follows this sequence:**

```
Ring 0 (MVP - Ship First):     Core value proposition
Ring 1 (After validation):     User-requested enhancements
Ring 2 (If valuable):          Advanced features
Ring 3 (Speculative):          Experiments
```

**RULE: Cannot work on Ring N+1 until Ring N is shipped and validated with users**

### Ring Graduation

When Ring 0 is complete (all scope items checked off below) and you are helping with Ring 1
work, remind the developer:

> "Ring 0 appears complete. Before starting Ring 1, run:
> `python scripts/graduate-ring.py --to 1`
> This raises the coverage floor to 80%, adds mypy to both the pre-commit hook and CI,
> and keeps hook and CI consistent. Review the diff before committing."

The project starts at Ring 0 (60% coverage, no mypy). `graduate-ring.py --to 1` patches
`.githooks/pre-commit`, `.github/workflows/test.yml`, and `pyproject.toml` in place.

**Timeline:**
(treat week numbers as relative timings/durations here - actual agentic dev may be faster)
- Week 0: Validate constraints
- Week 1-2: Build Ring 0
- Week 2-3: Ship & get user feedback
- Week 4+: Iterate based on feedback

---

## Understanding the Scaffold

This template provides **infrastructure** and **optional patterns**. See `SCAFFOLD_GUIDE.md` for complete decision trees.

### Infrastructure (Keep Always)

These prevent technical debt and ensure consistency:

- ✅ **JSON schemas in `schemas/`** - Schema-first design (generate Pydantic models programmatically)
- ✅ **YAML prompts co-located with agents/services** - Declarative, versionable prompts
- ✅ **Prompt naming convention**: `{agent_name}.prompt.yaml` or `{service_name}.{purpose}.prompt.yaml`
  - Examples: `agents/annotator.prompt.yaml`, `services/deepsearch.query.prompt.yaml`
  - Easy to find: `find . -name "*.prompt.yaml"`
  - Easy to review: `git diff **/*.prompt.yaml`
- ✅ **Test structure** - `unit/` and `integration/` with pytest markers
- ✅ **Tooling configs** - pytest, ruff, mypy, sphinx in `pyproject.toml`
- ✅ **Dotenv bootstrap** - Environment management via `.env` files
- ✅ **`experiments/` directory** - Exploratory scripts and Week 0 validation probes;
  excluded from coverage, mypy, and ruff; not subject to TDD
- ✅ **`AGENT.md`** - Run-mode agent instructions; references canonical prompts and
  schemas via `@` imports; keep separate from `CLAUDE.md` (dev instructions)
- ✅ **`.claude/commands/`** - Claude Code skills; `/run-workflow` switches to run mode

### Optional Components (Evaluate for Ring 0)

These are proven patterns - use if Ring 0 needs them, otherwise DELETE:

- **`graphs/`** - Multi-step workflow orchestration
  - Keep if: Complex branching workflows needed
  - Delete if: Single agent or linear flow sufficient
  - See: `src/atlas_chat/graphs/README.md`

- **`validation/`** - Cross-cutting validation logic
  - Keep if: Shared validation across 2+ services
  - Delete if: Simple Pydantic validation sufficient
  - See: `src/atlas_chat/validation/README.md`

- **`agents/example_agent.py`** - Example agent with infrastructure patterns
  - EXAMPLE code: Replace with your domain logic
  - INFRASTRUCTURE patterns: Keep schema-first, prompt-first approach

- **`deep-research-client` dependency**
  - Keep if: Using Perplexity/deep research in Ring 0
  - Delete if: Not needed for MVP (remove from `pyproject.toml`)

### Week 0 Includes Scaffold Review

1. Define Ring 0 scope (update sections below)
2. Review `SCAFFOLD_GUIDE.md` decision trees
3. **Delete unused optional components** (graphs/, validation/, etc.)
4. **Remove unused dependencies** (deep-research-client if not needed)
5. Keep infrastructure, replace example code with domain logic
6. Update README.md with your project description

**Key Principle**: Infrastructure ≠ premature abstraction. Schema files and prompt files are infrastructure that prevent technical debt.

### Prompt File Organization

**INFRASTRUCTURE**: Always store prompts in separate YAML files (not hardcoded in code).

**Location**: Co-locate prompts with the agents/services that use them.

**Naming Convention**: Use `.prompt.yaml` suffix for easy discoverability:
- `{agent_name}.prompt.yaml` - For single-purpose agents
- `{service_name}.{purpose}.prompt.yaml` - For services with multiple prompts

**Examples**:
- `src/atlas_chat/agents/annotator.prompt.yaml`
- `src/atlas_chat/services/deepsearch.query.prompt.yaml`
- `src/atlas_chat/services/deepsearch.summary.prompt.yaml`

**Benefits**:
- Easy discovery: `find . -name "*.prompt.yaml"`
- Clear ownership: prompt lives next to implementation
- Easy review: `git diff **/*.prompt.yaml`
- Grepable: search for prompt changes across project
- Version controlled: track prompt evolution in git

**Pattern**:
```yaml
# Co-located with agent/service that uses it
system_prompt: |
  You are an AI assistant specialized in {domain}.

user_prompt: |
  Process this {task_type}: {input_data}

presets:
  openai-gpt4:
    provider: openai
    model: gpt-4
    temperature: 0.1
```

**Load in code**:
```python
from pathlib import Path
import yaml

def load_prompt(prompt_file: str) -> dict:
    """Load co-located prompt file."""
    prompt_path = Path(__file__).parent / prompt_file
    return yaml.safe_load(prompt_path.read_text())

# Usage
prompt_config = load_prompt("my_agent.prompt.yaml")
```

---

## Project-Specific Configuration

**[CUSTOMIZE THIS SECTION FOR EACH PROJECT]**

### Ring 0 Scope (MVP)
<!-- Define your minimum viable product -->
- [ ] Core feature 1
- [ ] Core feature 2
- [ ] Basic output format

**STOP after Ring 0. Share with users. Get feedback.**

### Ring 1 Scope (After User Validation)
<!-- Features to consider after Ring 0 feedback -->
- [ ] TBD based on user feedback

### Architecture Vision
<!-- Document your core architectural decisions -->

**Core design:**
- Service pattern: [describe]
- Schema-first: Pydantic models from JSON schema
- Configuration: [describe preset system]

**What NOT to do yet:**
- ❌ Don't add multi-provider support unless clearly stated use case (wait for 2nd provider need)
- ❌ Don't build abstract base classes (wait for 2+ concrete cases)
- ❌ Don't optimize for scale (wait for scale problems) BUT - also warn of any poorly scaling or costly anti-patterns (e.g. multiple LLM calls passing the same info)

### Known Constraints
<!-- Document tested facts about external services -->
<!-- Update this as you discover API quirks -->

**Example:**
```markdown
## Perplexity deep reasearch API (Tested YYYY-MM-DD)
- ❌ Does NOT respect JSON schema in system prompt
- ✅ DOES work with schema in user message as part of request for larger report
- Tested: 10/10 successful parses
```

---

## Week 0: Validation Phase (REQUIRED)

**Before writing production code:**

### 1. Test External Services (1-2 days)
- Write 5-10 simple test scripts for each external API
- Document behavior quirks in CONSTRAINTS.md
- Test edge cases, error modes, rate limits
- **Deliverable:** CONSTRAINTS.md with tested facts

### 2. Create Scope Rings (1 day)
- Define Ring 0 (MVP) clearly - what's the minimum value?
- Identify Ring 1 candidates (defer until feedback)
- **Deliverable:** SCOPE_RINGS.md

### 3. Update This CLAUDE.md
- Fill in Ring 0 scope above
- Document architectural decisions
- List what NOT to do yet
- **Deliverable:** Project-specific CLAUDE.md

**Week 0 prevents:** Building elaborate systems on wrong assumptions

---

## Test-Driven Development

### Integration Tests: ALWAYS Required

**From Day 1:**
- Integration tests with REAL external services
- Tests FAIL HARD if no API keys
- Forces validation against real behavior
- Catches API quirks immediately

**Example:**
```python
@pytest.mark.integration
def test_perplexity_json_output():
    """Test real Perplexity API with JSON schema."""
    if not os.getenv("PERPLEXITY_API_KEY"):
        pytest.fail("PERPLEXITY_API_KEY required for integration tests")

    # Test with real API
    result = query_perplexity(...)
    assert valid_json(result)
```

### TDD: When to Use

**Use TDD for:**
- ✅ Parsers, validators, data transformers (clear inputs/outputs)
- ✅ Bug fixes (red → green → refactor)
- ✅ Core domain logic (once understood)

**Don't use TDD for:**
- ❌ Exploratory prototypes
- ❌ Trying different prompt strategies
- ❌ Initial API integration experiments

**TDD Workflow:**
```bash
# 1. Red: Write failing test
uv run pytest tests/test_parser.py -k test_new_feature  # Should fail

# 2. Green: Minimal implementation
# ... write code ...
uv run pytest tests/test_parser.py -k test_new_feature  # Should pass

# 3. Refactor: Improve while tests stay green
```

### Coverage Targets

**Ring 0 (low strictness — selected at project generation):**
- **Enforced on commit: 60%** — pre-commit hook runs `pytest --cov`; commits fail below this
- Focus on critical paths; integration tests count more than unit coverage
- `experiments/` is excluded from all coverage calculations

**Ring 1+ (high strictness — selected at project generation):**
- **Enforced on commit: 80%** — same mechanism, higher threshold
- mypy also blocks commits in this mode

---

## Code Quality: Phase-Appropriate Standards

### MVP Phase / Ring 0 (low strictness): Pragmatic

**Focus:** Deliver value, validate approach

```bash
# Pre-commit hook runs automatically on each commit:
uv run ruff check --fix src/ tests/    # Lint (blocks commit)
uv run ruff format --check src/ tests/ # Format (blocks commit)
uv run pytest -m unit --cov           # Unit tests + 60% coverage (blocks commit)

# mypy runs in CI but does NOT block commits in this mode:
uv run mypy src/                       # Type checking (encouraged locally)

# Exploratory work goes here — excluded from all checks:
# experiments/
```

**Standards:**
- ✅ Integration tests (required from day 1)
- ✅ Type hints (encouraged; not blocking commits in low-strictness mode)
- ✅ Linting and formatting (enforced on commit)
- ✅ Coverage: **60% enforced on commit** (not just a target — commits fail below this)
- ✅ Pre-commit hook active from day 1 (ruff + coverage; mypy in CI only)
- ✅ `experiments/` is the home for exploratory scripts — write freely, no TDD required

### Post-MVP Phase (Week 4+): Strict

**Focus:** Sustainable, maintainable code

```bash
# Install pre-commit hooks
uv run pre-commit install

# These now run automatically on commit
uv run pytest --cov --cov-fail-under=80
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format src/ tests/

```

**Standards:**
- ✅ Pre-commit hooks enforced
- ✅ Type checking enforced (mypy)
- ✅ Linting enforced (ruff)
- ✅ Coverage: 80%+ required
- ✅ CI/CD checks

**When to transition:** After Ring 0 shipped, user feedback received, code patterns stabilizing

---

## Testing Commands (using uv)

```bash
# Environment setup
uv sync --dev            # Install all dependencies including dev tools

# Running tests
uv run pytest                    # All tests
uv run pytest -m unit           # Unit tests only (CI uses this)
uv run pytest -m integration    # Integration tests (local only)
uv run pytest --cov             # With coverage
uv run pytest --cov --cov-fail-under=60   # MVP phase
uv run pytest --cov --cov-fail-under=80   # Post-MVP phase

# Code quality
uv run mypy src/                      # Type check
uv run ruff check --fix src/ tests/   # Lint + auto-fix
uv run ruff format src/ tests/        # Format

# Documentation
python scripts/check-docs.py          # Build and check docs
cd docs && uv run sphinx-build . _build/html -W  # Alternative

# Pre-commit (Post-MVP)
uv run pre-commit install             # Install hooks
uv run pre-commit run --all-files     # Run on all files

# Dependencies
uv add requests              # Runtime dependency
uv add --dev pytest          # Dev dependency
```

---

## Required Test Structure

```
tests/
├── unit/                    # Fast, isolated, no external deps
│   ├── test_parsers.py
│   ├── test_validators.py
│   └── ...
├── integration/             # Real external services
│   ├── test_perplexity.py
│   ├── test_deepsearch.py
│   └── ...
└── conftest.py             # Shared fixtures
```

**All tests must use markers:**
```python
@pytest.mark.unit          # Unit test
@pytest.mark.integration   # Integration test
```

**Integration test requirements:**
- Real API connections (no mocks)
- Fail hard if no credentials
- Document expected behavior
- Test error modes (rate limits, network failures)

---

## Integration Testing Strategy

### Local Development (Real APIs)
- Integration tests REQUIRE real API keys
- Tests FAIL HARD if credentials missing
- Forces validation against real services
- Run: `uv run pytest -m integration`

### CI/GitHub Actions (Unit Tests Only)
- NO integration tests in CI (avoid API costs/mocking)
- Only unit tests (fast, reliable)
- Run: `uv run pytest -m unit`

**Rationale:**
- Local: Mandatory real API testing ensures quality
- CI: Simple, fast validation
- Avoids mock complexity and false confidence

---

## FORBIDDEN Patterns

**Never:**
- ❌ Mock data for integration tests (use real APIs)
- ❌ Simulated API responses in integration tests
- ❌ Skipping tests with `pytest.mark.skip` (fix or remove)
- ❌ Ring 1+ features before Ring 0 ships
- ❌ Building generic architecture before specific case works
- ❌ Rewriting existing code without documented reason

**Required:**
- ✅ Real API integration tests from Day 1
- ✅ Ship Ring 0 within 2-3 weeks
- ✅ Get user feedback before Ring 1
- ✅ Extend existing code when possible

---

## Architecture Requirements

### Schema-First Pattern

**JSON Schema is source of truth:  Use it to generate pydanitc models**
```python
# 1. Define JSON schema (not Pydantic)
schema = {
    "type": "object",
    "properties": {...},
    "additionalProperties": False
}

# 2. Generate Pydantic model from JSON schema
# Use cellsem-llm-client utilities
Model = create_model_from_json_schema(schema)

# 3. Validate and correct LLM outputs
result = Model.model_validate(llm_output)  # Strict validation
# OR
result = Model.model_validate(llm_output, strict=False)  # Drop extra fields with warning
```

**Modular schemas:**
- Separate business logic from domain (biology)
- Reusable components
- Shared between core and validation packages

### Core Libraries

**Use:**
- `cellsem-llm-client` for LLM agents and generation of pydantic models
- `deepsearch-client` for DeepSearch queries
- `pydantic-ai` for orchestration graphs

**DeepSearch calls belong in services layer, not scattered through code**

### Orchestration: PydanticAI Graphs

```python
# Define workflow as graph
workflow = Graph()
workflow.add_node("query", query_agent)
workflow.add_node("validate", validation_agent)
workflow.add_edge("query", "validate")

# Declarative, inspectable, debuggable
result = workflow.run(input_data)
```

### Declarative Workflows

**Prefer declarative over imperative:**

**Prompts in YAML:**
```yaml
# prompts/gene_annotation.yaml
system_prompt: |
  You are a gene program annotator.
  {instructions}

user_prompt: |
  Analyze these genes: {gene_list}

presets:
  perplexity-sonar:
    provider: perplexity
    model: sonar-pro
    temperature: 0.1
```

**Benefits:**
- Easy to modify without code changes
- Versioned separately from logic
- Testable in isolation
- Self-documenting

### Transparency & Debuggability

**Required:**
- ✅ Save intermediate outputs at each step
- ✅ Structured output directory: `outputs/{project}/{query}/{timestamp}/`
  - `provenance.json` is always written **first** (before any LLM calls, including dry-runs)
- ✅ Ability to resume from any step
- ✅ Dry-run mode (show all prompts/calls without executing; still writes provenance.json)

**Example:**
```python
# Save intermediate results
def run_workflow(input_data, output_dir, start_step=None):
    if start_step is None or start_step <= 1:
        result1 = step1(input_data)
        save_json(result1, f"{output_dir}/step1_output.json")
    else:
        result1 = load_json(f"{output_dir}/step1_output.json")

    if start_step is None or start_step <= 2:
        result2 = step2(result1)
        save_json(result2, f"{output_dir}/step2_output.json")
    # ...
```

---

## Scripts & CLI

### Core Runner Script

**Every workflow needs a runner supporting:**

```bash
# Single run
workflow-runner --input genes.txt --output results/

# Batch mode
workflow-runner --batch inputs/ --output results/

# Dry run (show plan without executing)
workflow-runner --input genes.txt --dry-run

# Resume from step
workflow-runner --input genes.txt --output results/ --resume-from step3
```

**Requirements:**
- Distributed with package (installed as console script)
- Single run, batch, and dry-run modes
- Clear progress output
- Error handling with helpful messages

**Anti-pattern:** Encoding workflow logic in scripts instead of core package

---

## Repository Structure

### Two-Package Architecture (UV Workspace)

This project uses **UV workspace** to manage two separately publishable packages:

```
atlas_chat/
├── pyproject.toml                           # UV workspace configuration
├── src/
│   ├── atlas_chat/      # CORE PACKAGE
│   │   ├── pyproject.toml                   # Core package config
│   │   └── atlas_chat/  # Source code
│   │       ├── __init__.py                  # Bootstrap with dotenv
│   │       ├── agents/                      # Agent orchestration
│   │       │   └── *.prompt.yaml            # Co-located prompts
│   │       ├── graphs/                      # Workflow graphs (OPTIONAL)
│   │       ├── schemas/                     # JSON schemas (source of truth)
│   │       ├── services/                    # LLM + API integrations
│   │       │   └── *.prompt.yaml            # Co-located prompts
│   │       ├── utils/                       # Supporting utilities
│   │       └── validation/                  # Cross-cutting validations (OPTIONAL)
│   └── atlas_chat_validation_tools/  # VALIDATION PACKAGE (OPTIONAL)
│       ├── pyproject.toml                   # Validation package config
│       └── atlas_chat_validation_tools/
│           ├── comparisons/                 # Compare workflow runs
│           ├── metrics/                     # Quality metrics
│           └── visualizations/              # Analysis plots
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
├── scripts/
│   └── check-docs.py
├── SCAFFOLD_GUIDE.md                        # Scaffold decision guide
└── CLAUDE.md                                # This file
```

**Core package** (`atlas_chat`):
- **Always keep**: Contains all workflow logic
- **Owns schemas**: Only location for JSON schemas
- **Prompts co-located**: `*.prompt.yaml` files next to agents/services
- Publish: `pip install atlas_chat`

**Validation package** (`atlas_chat_validation_tools`):
- **OPTIONAL**: Delete entire directory if Ring 0 doesn't need validation tooling
- **Depends on core**: Imports schemas and models from core package
- **No schema duplication**: Uses `from atlas_chat.schemas import ...`
- Publish: `pip install atlas_chat-validation-tools`

**UV Workspace benefits:**
- Single `uv sync` installs both packages in development mode
- Shared lockfile (`uv.lock`) for reproducibility
- Independent publishing to PyPI
- Clear dependency graph (validation → core)

---

## Environment Configuration

**ALWAYS use dotenv:**
```python
from dotenv import load_dotenv
load_dotenv()

# Then use os.getenv()
api_key = os.getenv("PERPLEXITY_API_KEY")
```

**Precedence:**
1. Constructor parameters (explicit)
2. Environment variables (.env file)
3. Sensible defaults

**Never:**
- ❌ Hardcode secrets
- ❌ Commit .env files
- ❌ Use `os.getenv()` without `load_dotenv()`

---

## Documentation Requirements

**Google-style docstrings:**
```python
def query_deepsearch(gene_list: list[str], model: str = "sonar-pro") -> dict:
    """Query DeepSearch API for gene program annotation.

    Args:
        gene_list: List of gene symbols to annotate
        model: DeepSearch model to use (default: sonar-pro)

    Returns:
        Dictionary containing annotation results with keys:
        - programs: List of identified gene programs
        - citations: Supporting references
        - confidence: Confidence scores

    Raises:
        APIError: If DeepSearch request fails
        ValidationError: If response doesn't match schema

    Example:
        .. code-block:: python

            result = query_deepsearch(["TP53", "BRCA1"])
            programs = result["programs"]
    """
```

**RST syntax in docstrings:**
- Use `.. code-block:: python` (not markdown backticks)
- Check with: `python scripts/check-docs.py`

**Documentation structure:**
- Auto-generated API docs (Sphinx + AutoAPI)
- Manual guides in docs/ (MyST markdown)
- ALWAYS run docs check before committing

---

## Planning Requirements

### For Each Feature

**Include:**
1. Clear, testable goal
2. Integration test demonstrating real API behavior
3. Error handling for actual failure modes:
   - Network failures
   - Malformed data
   - Rate limits
   - Authentication errors
4. Critique: Potential issues/risks with approach

**Template:**
```markdown
## Feature: [Name]

### Goal
[What value does this provide?]

### Integration Test
[How will we test with real APIs?]

### Error Modes
- Network failure: [handling]
- Malformed response: [handling]
- Rate limit: [handling]

### Critique
- Risk 1: [mitigation]
- Risk 2: [mitigation]
```

### MVP Definition

**Each feature is not complete until:**
- ✅ Real integration test passes
- ✅ Error handling implemented
- ✅ Documented in code and docs

---

## Decision Checklist

**Before writing production code, verify:**

- [ ] **Week 0 complete?** CONSTRAINTS.md, SCOPE_RINGS.md, CLAUDE.md updated
- [ ] **Is this Ring 0?** If no, STOP until Ring 0 ships
- [ ] **Have we tested the external API?** Integration test first
- [ ] **Can we extend existing code?** Don't rewrite without reason
- [ ] **Is architecture documented in CLAUDE.md?** Agent needs guidance
- [ ] **Are we in Week 3+ without user feedback?** Time to share

---

## Red Flags: Stop and Review

**Warning signs:**
- [ ] Ring 1+ features before Ring 0 ships
- [ ] Rewriting existing code without documented reason
- [ ] Building custom generic architecture (use/contribute to template)
- [ ] Week 3+ without sharing with users
- [ ] No integration tests with real APIs
- [ ] Missing architectural vision in CLAUDE.md

**If any checked:** Pause. Review [[development-principles]]. Refocus on Ring 0.

---

## Success Metrics

**Ship fast:**
- Ring 0 shipped: Week 2-3 (not Week 5+)
- User feedback: Week 3
- Ring 1 decisions: Based on feedback

**Build right:**
- Integration tests from Day 1
- Real API validation (no mocks)
- Coverage: 60% (MVP) → 80% (Post-MVP)
- Sustainable patterns (template infrastructure)

**Iterate smart:**
- Rapid experiments + user feedback
- Extend existing code when possible
- Contribute patterns back to template

---

## References

- [[development-principles]] - Lessons from Langpa retrospective
- [[workflows]] - Integration with research workflows
- CellSemAgenticWorkflow template repository - [URL]

---

## Customization Checklist

**When starting new project from this template:**

- [ ] Fill in "Ring 0 Scope" section above
- [ ] Document architectural decisions
- [ ] List "What NOT to do yet"
- [ ] Complete Week 0 validation
- [ ] Create CONSTRAINTS.md
- [ ] Create SCOPE_RINGS.md
- [ ] Update this CLAUDE.md with project specifics
- [ ] Share this with agent for each session

**This CLAUDE.md guides the agent. Keep it updated as decisions evolve.**
