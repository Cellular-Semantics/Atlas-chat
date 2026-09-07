"""Schema regression for name_resolution.schema.json (the grounder output).

Formalises the resolve-name → query-decomposer contract: required label /
resolved_names / source_paper, source_paper needing a role + at least one id, and
additionalProperties teeth.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from atlas_chat.schemas import load_schema

FIXTURES = Path(__file__).parent / "fixtures" / "name_resolution"
SCHEMA = "name_resolution.schema.json"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _errors(data: object) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(SCHEMA))
    return [e.message for e in validator.iter_errors(data)]


@pytest.mark.unit
def test_schema_is_well_formed() -> None:
    jsonschema.Draft202012Validator.check_schema(load_schema(SCHEMA))


@pytest.mark.unit
def test_good_validates() -> None:
    assert _errors(_load("name_resolution.good.json")) == []


@pytest.mark.unit
def test_requires_source_paper() -> None:
    data = _load("name_resolution.good.json")
    del data["source_paper"]
    assert _errors(data)


@pytest.mark.unit
def test_source_paper_requires_role_and_id() -> None:
    # The bad fixture's source_paper is empty (no role, no doi/corpus_id).
    assert _errors(_load("name_resolution.bad.json"))


@pytest.mark.unit
def test_additional_properties_closed() -> None:
    data = _load("name_resolution.good.json")
    data["bogus_field"] = 1
    assert _errors(data)
