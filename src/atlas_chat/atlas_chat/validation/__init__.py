"""Workflow-level validation rules that inspect graphs, schemas, and services."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from jsonschema import ValidationError, validate

from ..schemas import load_schema


def validate_workflow_output(payload: Dict[str, Any]) -> None:
    """Validate a workflow output payload against the canonical JSON schema."""
    schema = load_schema("workflow_output.schema.json")
    validate(instance=payload, schema=schema)


def ensure_services_registered(service_names: Iterable[str], available: Iterable[str]) -> None:
    """Ensure every service used in a workflow is registered in the services layer."""
    missing: List[str] = sorted(set(service_names) - set(available))
    if missing:
        raise ValidationError(f"Unregistered services referenced: {missing}")


__all__ = ["validate_workflow_output", "ensure_services_registered"]
