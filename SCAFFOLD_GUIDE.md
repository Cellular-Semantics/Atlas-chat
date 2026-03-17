# Project Scaffold Guide

This guide helps you understand the generated project structure and decide what to keep for your Ring 0 MVP.

## Two-Package Architecture

This project uses a **two-package structure** managed as a UV workspace for separation of concerns:

### 1. Core Package: `atlas_chat`

**Always Keep**: This is your main workflow package.

**Location**: `src/atlas_chat/`

**Contains**:
- Agents, services, orchestration
- Core business logic
- Schemas (source of truth - **only location for schemas**)
- Prompts (co-located with agents/services)

**Publish**: `pip install atlas_chat`

### 2. Validation Package: `atlas_chat_validation_tools`

**OPTIONAL**: Delete entire directory if not needed for Ring 0.

**Location**: `src/atlas_chat_validation_tools/`

**Contains**:
- Workflow output comparison tools (`comparisons/`)
- Quality metrics (`metrics/` - precision, recall, F1, etc.)
- Visualizations (`visualizations/` - heatmaps, ROC curves, plots)

**Depends on**: Core package (imports schemas and models from core)

**Publish**: `pip install atlas_chat-validation-tools`

**Keep if**:
- Need to compare workflow runs
- Need quality metrics for evaluation
- Need visualizations for analysis
- Building tools for workflow validation

**Delete if**:
- No comparison/analysis needed in Ring 0
- Simple workflows without evaluation needs
- Not building validation tooling

### UV Workspace Benefits

- **Single `uv sync`**: Installs both packages in development mode
- **Shared lockfile**: `uv.lock` ensures reproducibility across team
- **Local development**: Edit either package, changes reflected immediately
- **Independent publishing**: Each package can be published to PyPI separately
- **Clear dependencies**: Validation depends on core, not vice versa

---

## Infrastructure (Always Keep)

These components prevent technical debt and ensure consistency across all projects:

- **`src/atlas_chat/__init__.py`** - Bootstrap with dotenv loading
- **`src/atlas_chat/schemas/`** - JSON schemas directory (schema-first design)
- **`*.prompt.yaml` files** - Co-located with agents/services that use them
- **`tests/unit/`** and **`tests/integration/`** - Testing structure with pytest markers
- **`pyproject.toml`**, tooling configs - Development infrastructure (ruff, mypy, pytest, sphinx)
- **`.github/workflows/`** - CI/CD pipeline
- **`.githooks/`** - Pre-commit quality checks
- **`experiments/`** - Exploratory scripts and Week 0 validation probes; excluded from
  coverage, mypy, and ruff; not subject to TDD; graduate proven patterns into `src/` with tests
- **`AGENT.md`** - Run-mode agent instructions; uses `@` imports to reference canonical
  prompts/schemas; customize the "Workflow Steps" section for your domain; never merge
  dev rules into this file
- **`.claude/commands/run-workflow.md`** - Claude Code skill (`/run-workflow`) that loads
  AGENT.md and switches the session to workflow-agent mode

---

## Dual-Mode Architecture

This project serves two purposes from one repo:

| Mode | Entry point | Who uses it |
| --- | --- | --- |
| **Dev** | `CLAUDE.md` (auto-loaded) | Developer building/extending the package |
| **Run** | `AGENT.md` (explicit load) | Agent executing the workflow for users |

**Shared assets** (single source of truth):
- `src/.../schemas/*.schema.json` — constrain output in both modes
- `src/.../agents/*.prompt.yaml` — define behaviour in both modes
- Python package — programmatic implementation of the same workflow logic

`AGENT.md` references the shared assets via `@` imports (Claude Code's native
file-import feature). The Python code reads them via `yaml.safe_load()` and
`json.load()`. Same files, different consumers, zero duplication.

### Prompt File Naming Convention

**Always use `.prompt.yaml` suffix** for easy identification and discoverability:

**Examples:**
- `src/atlas_chat/agents/annotator.prompt.yaml` - Single prompt for agent
- `src/atlas_chat/services/deepsearch.query.prompt.yaml` - Specific purpose
- `src/atlas_chat/services/deepsearch.summary.prompt.yaml` - Another purpose

**Benefits:**
- Easy to find all prompts: `find . -name "*.prompt.yaml"`
- Clear ownership: prompt lives next to code that uses it
- Easy to review: `git diff **/*.prompt.yaml`
- Grepable: search for prompt-related changes across project
- Version controlled: track prompt evolution in git

---

## Optional Components (Evaluate for Ring 0)

### `graphs/` - Workflow Orchestration

**Keep if** your Ring 0 needs:
- Multi-step workflows with branching logic
- Complex dependencies between steps
- Dynamic routing based on runtime conditions
- Type-safe workflow definitions

**Delete if**:
- Single agent or linear flow sufficient
- Simple sequential operations
- No branching or complex routing needed

**Provided**: Working example of pydantic-ai graph orchestration with typed dependencies

---

### `validation/` - Cross-cutting Validations

**Keep if** your Ring 0 has:
- Complex validation logic used across multiple services
- Business rules that span multiple components
- Schema validations beyond simple Pydantic models

**Delete if**:
- Simple validation in service layer is sufficient
- No shared validation logic across components

**Ring 0 guidance**: Likely not needed. Add in Ring 1+ if you discover duplicated validation logic.

**Alternative**: Keep validation in service layer until pattern emerges (don't premature abstract).

**Provided**: Empty directory with README explaining usage patterns

---

### `agents/` - Agent Classes

**Keep if** your Ring 0 has:
- Multiple agents with shared patterns
- Complex agent coordination
- Agent orchestration needs

**Delete if**:
- Single simple agent is sufficient
- No shared patterns between agents yet

**Provided**: Example agent demonstrating schema-first and prompt-first patterns

---

### `deep-research-client` Integration

**Keep if** your Ring 0 needs:
- Deep research workflows
- Perplexity API integration
- Literature search and synthesis

**Delete if**:
- Not using deep research capabilities in Ring 0
- Different research tool needed

**Action**: Remove from `pyproject.toml` dependencies if not needed

---

## Example Code (Replace with Domain Logic)

Files and code marked with `# EXAMPLE` comments are working demonstrations:

- **Purpose**: Show proven patterns (schema-first, prompt-first, co-located prompts)
- **Action**: Replace with your domain-specific logic
- **Keep**: The patterns and infrastructure
- **Maintain**: Test structure and documentation style

---

## Week 0 Checklist

Use this checklist during your Week 0 validation phase:

- [ ] **Define Ring 0 scope** in CLAUDE.md (update "Ring 0 Scope" section)
- [ ] **Review each directory** against your Ring 0 requirements
- [ ] **Delete unused optional components** (graphs/, validation/, agents/ if not needed)
- [ ] **Remove unused dependencies** from pyproject.toml (e.g., deep-research-client)
- [ ] **Replace example code** with first real use case
- [ ] **Update README.md** with your project description and purpose
- [ ] **Create .env file** with required API keys
- [ ] **Run integration tests** to validate API access
- [ ] **Document architectural decisions** in CLAUDE.md

---

## Decision Tree

```
Is your Ring 0 a single, simple agent?
├─ YES → Delete: graphs/, validation/, example agents/
│         Keep: schemas/, tests/, tooling, one real agent
│
└─ NO → Multi-step workflow?
    ├─ YES → Keep: graphs/, agents/
    │         Evaluate: validation/ (probably defer to Ring 1)
    │
    └─ NO → Linear multi-agent?
            Keep: agents/
            Delete: graphs/, validation/
```

---

## Common Patterns to Follow

### 1. Schema-First Design

```python
# schemas/my_input.schema.json
{
  "$comment": "Define business logic in JSON schema first",
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "max_results": {"type": "integer", "default": 10}
  },
  "required": ["query"]
}

# Then generate Pydantic model programmatically
# (using cellsem-llm-client utilities)
```

### 2. Prompt-First Design

```yaml
# agents/my_agent.prompt.yaml
system_prompt: |
  You are an AI assistant specialized in {domain}.

user_prompt: |
  {task_description}

presets:
  openai-gpt4:
    provider: openai
    model: gpt-4
    temperature: 0.1
```

```python
# agents/my_agent.py
def load_prompt(prompt_file: str) -> dict:
    """Load co-located prompt file."""
    prompt_path = Path(__file__).parent / prompt_file
    return yaml.safe_load(prompt_path.read_text())
```

### 3. Test Structure

```python
# tests/unit/test_parser.py
@pytest.mark.unit
def test_parser_logic():
    """Fast, isolated, no external dependencies."""
    pass

# tests/integration/test_api.py
@pytest.mark.integration
def test_real_api_connection():
    """Real API, fail hard if no credentials."""
    if not os.getenv("API_KEY"):
        pytest.fail("API_KEY required for integration tests")
    # Test with real API
```

---

## Questions?

- Review `CLAUDE.md` for full development philosophy and ring-based approach
- See directory-specific `README.md` files for detailed component guidance
- Check `README.md` for quick start and architecture overview

---

**Remember**: Infrastructure ≠ premature abstraction. Schema files, prompt files, and testing patterns are infrastructure that prevent technical debt.
