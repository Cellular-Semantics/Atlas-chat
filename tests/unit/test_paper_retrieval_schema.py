"""Schema regression for paper_retrieval.schema.json.

Golden fixtures for each route the waterfall can end on, and for the drift the
schema exists to reject. The cross-field rules that a schema cannot express are
checked here too, against the same fixtures, because the pair is what the hook
runs and either half passing alone is not enough.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from atlas_chat.services.paper_fetch import (
    PaperFetchError,
    cross_check_retrieval,
    validate_retrieval,
)

from atlas_chat.schemas import load_schema

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "paper_retrieval"

GOOD = ["jats.good.json", "pdf.good.json", "ask.good.json"]
BAD = [
    "unknown-field.bad.json",
    "unknown-route.bad.json",
    "bad-outcome.bad.json",
    "no-attempts.bad.json",
]


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", GOOD)
def test_good_fixtures_validate(name: str) -> None:
    jsonschema.validate(load(name), load_schema("paper_retrieval.schema.json"))


@pytest.mark.parametrize("name", BAD)
def test_bad_fixtures_are_rejected(name: str) -> None:
    with pytest.raises(PaperFetchError):
        validate_retrieval(load(name))


@pytest.mark.parametrize("name", GOOD)
def test_good_fixtures_are_also_self_consistent(name: str) -> None:
    assert cross_check_retrieval(load(name)) == []


def test_the_schema_itself_is_well_formed() -> None:
    schema = load_schema("paper_retrieval.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_schema_rejects_fields_it_does_not_declare() -> None:
    """Drift has to fail loudly: a field nothing reads is a field nothing checks."""
    assert load_schema("paper_retrieval.schema.json")["additionalProperties"] is False


def test_a_record_needs_a_doi_a_route_and_its_attempts() -> None:
    required = load_schema("paper_retrieval.schema.json")["required"]
    assert set(required) == {"doi", "route", "attempts"}
