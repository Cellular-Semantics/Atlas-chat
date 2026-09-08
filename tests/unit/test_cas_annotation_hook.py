"""PostToolUse hook regression for check_cas_annotation.py.

Drives the hook via subprocess (like the other hook regressions). The hook reads
the document **from disk**, so every case here writes a real file: that is the
behaviour under test, not an implementation detail. Three call shapes are
covered, because the hook is registered for all of them:

* ``Write`` — carries ``file_path`` and ``content``;
* ``Edit`` — carries ``file_path`` but no ``content`` (the shape that used to
  fail spuriously with "cas.json is empty");
* ``Bash`` — carries neither, standing in for an agent's script writing the
  file, which the hook catches by noticing the bytes on disk moved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "cas"
HOOK = REPO_ROOT / ".claude" / "hooks" / "check_cas_annotation.py"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _run(hook_input: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _project(tmp_path: Path, payload: object, name: str = "cas.json") -> Path:
    target = tmp_path / "projects" / "p"
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.unit
def test_write_accepts_valid_cas(tmp_path: Path) -> None:
    path = _project(tmp_path, _load("cas_annotation.minimal.good.json"))
    r = _run(
        {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "ignored"}},
        tmp_path,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.unit
def test_write_rejects_invalid_cas(tmp_path: Path) -> None:
    path = _project(tmp_path, _load("cas_annotation.bad.json"))
    r = _run(
        {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "ignored"}},
        tmp_path,
    )
    assert r.returncode == 2
    assert "VALIDATION FAILED" in r.stderr


@pytest.mark.unit
def test_edit_shape_has_no_content_and_still_validates(tmp_path: Path) -> None:
    """An Edit carries old_string/new_string, never content — it must not fail for that."""
    path = _project(tmp_path, _load("cas_annotation.minimal.good.json"))
    r = _run(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b"},
        },
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert "is empty" not in r.stderr


@pytest.mark.unit
def test_edit_shape_still_catches_an_invalid_document(tmp_path: Path) -> None:
    path = _project(tmp_path, _load("cas_annotation.bad.json"))
    r = _run(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b"},
        },
        tmp_path,
    )
    assert r.returncode == 2
    assert "VALIDATION FAILED" in r.stderr


@pytest.mark.unit
def test_validates_what_is_on_disk_not_what_the_tool_reported(tmp_path: Path) -> None:
    """The claimed content is irrelevant; the file is the source of truth."""
    path = _project(tmp_path, _load("cas_annotation.bad.json"))
    claimed = json.dumps(_load("cas_annotation.minimal.good.json"))
    r = _run(
        {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": claimed}},
        tmp_path,
    )
    assert r.returncode == 2, "a valid-looking content payload must not excuse a bad file"


@pytest.mark.unit
def test_bash_catches_a_document_written_by_code(tmp_path: Path) -> None:
    """No file_path at all — the script path, caught by the change scan."""
    bash = {"tool_name": "Bash", "tool_input": {"command": "python build_cas.py"}}

    _project(tmp_path, _load("cas_annotation.minimal.good.json"))
    assert _run(bash, tmp_path).returncode == 0  # first run records the baseline

    _project(tmp_path, _load("cas_annotation.bad.json"))  # a script rewrites it
    r = _run(bash, tmp_path)
    assert r.returncode == 2
    assert "VALIDATION FAILED" in r.stderr


@pytest.mark.unit
def test_bash_is_quiet_when_nothing_changed(tmp_path: Path) -> None:
    bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    _project(tmp_path, _load("cas_annotation.bad.json"))
    assert _run(bash, tmp_path).returncode == 0, "baseline run must not fire"
    assert _run(bash, tmp_path).returncode == 0, "unchanged file must not fire"


@pytest.mark.unit
def test_ignores_non_cas_files(tmp_path: Path) -> None:
    path = _project(tmp_path, {"anything": 1}, name="notes.json")
    r = _run(
        {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "{}"}},
        tmp_path,
    )
    assert r.returncode == 0
