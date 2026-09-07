"""Schema + hook regression for query_decomposition.schema.json (Layer B).

Pins well-formedness, the minimal valid decomposition, the fixed-5-aspects
constraint, the seed-role enum, additionalProperties teeth, and the
check_query_decomposition PostToolUse hook (subprocess 0/2/ignore).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from atlas_chat.schemas import load_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "decomposition"
SCHEMA = "query_decomposition.schema.json"
HOOK = REPO_ROOT / ".claude" / "hooks" / "check_query_decomposition.py"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _errors(data: object) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(SCHEMA))
    return [e.message for e in validator.iter_errors(data)]


def _run_hook(file_path: str, payload: object) -> subprocess.CompletedProcess:
    hook_input = json.dumps(
        {"tool_input": {"file_path": file_path, "content": json.dumps(payload)}}
    )
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=hook_input,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@pytest.mark.unit
def test_schema_is_well_formed() -> None:
    jsonschema.Draft202012Validator.check_schema(load_schema(SCHEMA))


@pytest.mark.unit
def test_minimal_good_validates() -> None:
    assert _errors(_load("query_decomposition.minimal.good.json")) == []


@pytest.mark.unit
def test_rich_good_validates() -> None:
    assert _errors(_load("query_decomposition.good.json")) == []


@pytest.mark.unit
def test_requires_all_five_aspects() -> None:
    # The bad fixture has only four aspects.
    assert _errors(_load("query_decomposition.bad.json"))


@pytest.mark.unit
def test_rejects_unknown_aspect_name() -> None:
    data = _load("query_decomposition.minimal.good.json")
    data["aspects"][0]["name"] = "other"
    assert _errors(data)


@pytest.mark.unit
def test_seed_role_enum_enforced() -> None:
    data = _load("query_decomposition.minimal.good.json")
    data["seed"]["role"] = "external"
    assert _errors(data)


@pytest.mark.unit
def test_additional_properties_closed() -> None:
    data = _load("query_decomposition.minimal.good.json")
    data["bogus_field"] = 1
    assert _errors(data)


@pytest.mark.unit
def test_hook_accepts_good() -> None:
    r = _run_hook(
        "projects/x/traversal_output/ct/query_decomposition.json",
        _load("query_decomposition.good.json"),
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.unit
def test_hook_rejects_bad() -> None:
    r = _run_hook(
        "projects/x/traversal_output/ct/query_decomposition.json",
        _load("query_decomposition.bad.json"),
    )
    assert r.returncode == 2
    assert "VALIDATION FAILED" in r.stderr


@pytest.mark.unit
def test_hook_ignores_other_files() -> None:
    r = _run_hook("projects/x/notes.txt", {"anything": 1})
    assert r.returncode == 0
