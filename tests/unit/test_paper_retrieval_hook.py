"""PostToolUse hook regression for check_paper_retrieval.py.

Drives the hook via subprocess, like the other hook regressions: a valid record
exits 0, one that breaks the schema or the cross-field rules exits 2 with the
reason on stderr, and a file that is not a retrieval record is ignored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "paper_retrieval"
HOOK = REPO_ROOT / ".claude" / "hooks" / "check_paper_retrieval.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def run_hook(file_path: str, payload: object) -> subprocess.CompletedProcess:
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


PATH = "projects/x/local_index/papers/10.1234_y/retrieval.json"


@pytest.mark.parametrize("name", ["jats.good.json", "pdf.good.json", "ask.good.json"])
def test_hook_accepts_a_valid_record(name: str) -> None:
    result = run_hook(PATH, load(name))
    assert result.returncode == 0, result.stderr


def test_hook_rejects_a_record_that_breaks_the_schema() -> None:
    result = run_hook(PATH, load("unknown-route.bad.json"))
    assert result.returncode == 2
    assert "VALIDATION FAILED" in result.stderr


def test_hook_rejects_a_record_that_claims_a_route_with_nothing_stored() -> None:
    """Passes the schema, fails the reader — which is what cross-checking is for."""
    record = {
        "doi": "10.1234/x",
        "route": "europepmc",
        "attempts": [{"route": "europepmc", "outcome": "ok"}],
    }
    result = run_hook(PATH, record)
    assert result.returncode == 2
    assert "path is missing" in result.stderr


def test_hook_ignores_other_files() -> None:
    result = run_hook("projects/x/cas.json", {"nonsense": True})
    assert result.returncode == 0


def test_hook_rejects_an_empty_record() -> None:
    hook_input = json.dumps({"tool_input": {"file_path": PATH, "content": "   "}})
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=hook_input,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
