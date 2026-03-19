# Validation - Cross-cutting Concerns

**Status**: OPTIONAL (currently empty)

## Purpose

This directory is for validation logic that is:
- **Shared** across multiple services/agents
- **Cross-cutting** (not specific to one component)
- **Complex** enough to warrant centralization

## Keep This Directory If

Your Ring 0 MVP has:

- ✅ **Complex business rules** used across multiple components
- ✅ **Schema validations** beyond simple Pydantic models
- ✅ **Data quality checks** applied to multiple data sources
- ✅ **Compliance validations** (HIPAA, GDPR, etc.) affecting multiple services

## Delete This Directory If

Your Ring 0 MVP has:

- ❌ **Simple validations** handled by Pydantic models
- ❌ **Service-specific validation** (keep in service layer)
- ❌ **No duplicated validation logic** across components

## Ring 0 Guidance

**Most projects should DELETE this directory for Ring 0.**

Why? Because:
1. You likely don't have duplicated validation logic yet
2. Premature abstraction adds complexity
3. Better to keep validation in service layer until patterns emerge

**Add validation/ in Ring 1+** when you discover:
- Same validation logic copy-pasted across 2+ components
- Complex validation rules that deserve their own module
- Clear separation between business logic and validation needed

## Example Use Cases (Ring 1+)

### Service Registration Validation

```python
# validation/service_registry.py
def ensure_services_registered(
    service_names: list[str],
    available: list[str]
) -> None:
    """Validate all required services are registered."""
    missing = set(service_names) - set(available)
    if missing:
        raise ValueError(f"Missing services: {missing}")
```

### Workflow Output Validation

```python
# validation/workflow_output.py
from jsonschema import validate
from atlas-chat.schemas import load_schema

def validate_workflow_output(data: dict) -> None:
    """Validate output against workflow_output.schema.json."""
    schema = load_schema("workflow_output.schema.json")
    validate(instance=data, schema=schema)
```

### Cross-service Data Quality

```python
# validation/data_quality.py
def validate_gene_list(genes: list[str]) -> list[str]:
    """Validate and normalize gene symbols across services."""
    # Complex validation shared by multiple services
    # - Format checking
    # - Normalization
    # - Duplicate removal
    pass
```

## Alternative Approaches for Ring 0

### Option 1: Validation in Pydantic Models

```python
# Simple validations in domain models
from pydantic import BaseModel, field_validator

class GeneQuery(BaseModel):
    genes: list[str]

    @field_validator('genes')
    @classmethod
    def validate_gene_format(cls, v: list[str]) -> list[str]:
        # Validation logic here
        return v
```

### Option 2: Validation in Service Layer

```python
# Keep validation close to where it's used
class DeepSearchService:
    def query(self, genes: list[str]) -> dict:
        # Validate inputs
        self._validate_genes(genes)
        # Execute query
        return self._execute_query(genes)

    def _validate_genes(self, genes: list[str]) -> None:
        # Service-specific validation
        pass
```

## When to Centralize Validation

Wait until you see these patterns:

1. **Duplication**: Same validation in 2+ places
2. **Complexity**: Validation logic is complex enough to test independently
3. **Reuse**: Multiple services need identical validation
4. **Compliance**: Regulatory requirements span multiple components

## Decision Tree

```
Do you have validation logic used in 2+ components?
├─ NO → DELETE validation/ directory
│        Keep validation in Pydantic models or service methods
│
└─ YES → Is it complex enough to test independently?
    ├─ NO → Consider extracting to shared utility first
    │        Don't need full validation/ module yet
    │
    └─ YES → Move to validation/ directory
             Add comprehensive tests
             Document validation rules
```

## See Also

- `SCAFFOLD_GUIDE.md` - Full decision tree for optional components
- `CLAUDE.md` - Ring-based development philosophy (defer abstraction)
- [Pydantic Validators](https://docs.pydantic.dev/latest/concepts/validators/) - Built-in validation patterns
