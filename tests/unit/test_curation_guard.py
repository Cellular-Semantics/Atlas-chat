"""PreToolUse hook regression for curation_guard.py.

Drives the hook via subprocess (like the other hook regressions), setting the
git identity through ``ATLAS_CHAT_HOOK_USER``. Pins the three decisions the
hook makes: content zones are open to everyone, infrastructure needs a trusted
identity, and a trusted identity also needs CLAUDE_dev.md in the session.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "curation_guard.py"

TRUSTED = "dosumis@gmail.com"
UNTRUSTED = "someone-else@example.com"


def _run(
    file_path: str,
    user: str,
    *,
    tool: str = "Write",
    transcript: Path | None = None,
) -> subprocess.CompletedProcess:
    payload: dict[str, object] = {
        "tool_name": tool,
        "tool_input": {"file_path": str(REPO_ROOT / file_path)},
    }
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"ATLAS_CHAT_HOOK_USER": user, "PATH": "/usr/bin:/bin"},
    )


def _transcript(tmp_path: Path, *lines: object) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def _guide_title() -> str:
    for line in (REPO_ROOT / "CLAUDE_dev.md").read_text().splitlines():
        if line.startswith("# "):
            return line
    raise AssertionError("CLAUDE_dev.md has no title line")


# --- content zones: open to everyone ---------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("user", [TRUSTED, UNTRUSTED, ""])
@pytest.mark.parametrize(
    "path",
    ["projects/x/reports/a.md", "planning/note.md"],
)
def test_content_zones_are_open(user: str, path: str, tmp_path: Path) -> None:
    result = _run(path, user, transcript=_transcript(tmp_path, {"type": "user"}))
    assert result.returncode == 0, result.stderr


# --- infrastructure: trusted identity required ------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "src/atlas_chat/atlas_chat/services/atlas_paper.py",
        "tests/unit/test_thing.py",
        "docs/pipeline.md",
        ".claude/hooks/check_report_refs.py",
        "CLAUDE.md",
    ],
)
def test_untrusted_cannot_write_infrastructure(path: str, tmp_path: Path) -> None:
    result = _run(path, UNTRUSTED, transcript=_transcript(tmp_path, {"type": "user"}))
    assert result.returncode == 2
    assert "may not write infrastructure" in result.stderr


@pytest.mark.unit
def test_no_git_identity_is_untrusted(tmp_path: Path) -> None:
    result = _run("src/thing.py", "", transcript=_transcript(tmp_path, {"type": "user"}))
    assert result.returncode == 2
    assert "no git user.email set" in result.stderr


# --- infrastructure: trusted, but the guide must be in the session ----------


@pytest.mark.unit
def test_trusted_blocked_until_guide_is_read(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, {"type": "user", "message": "make a change"})
    result = _run("src/thing.py", TRUSTED, transcript=transcript)
    assert result.returncode == 2
    assert "CLAUDE_dev.md before editing infrastructure" in result.stderr


@pytest.mark.unit
def test_trusted_allowed_once_guide_content_is_in_transcript(tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path,
        {"type": "user", "message": "read the guide"},
        {"type": "user", "message": {"content": _guide_title() + "\n\nsome body"}},
    )
    result = _run("src/thing.py", TRUSTED, transcript=transcript)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_guide_title_survives_json_escaping(tmp_path: Path) -> None:
    """The title has an em dash; transcripts store it escaped."""
    escaped = json.dumps({"content": _guide_title()})  # — in the raw line
    assert "\\u2014" in escaped or "—" not in _guide_title()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(escaped + "\n")
    result = _run("src/thing.py", TRUSTED, transcript=transcript)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_at_import_counts_as_reading_the_guide(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path, {"type": "user", "message": "@CLAUDE_dev"})
    result = _run("src/thing.py", TRUSTED, transcript=transcript)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_trusted_allowed_when_no_transcript_available() -> None:
    result = _run("src/thing.py", TRUSTED)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_untrusted_still_blocked_without_a_transcript() -> None:
    result = _run("src/thing.py", UNTRUSTED)
    assert result.returncode == 2


# --- scope ------------------------------------------------------------------


@pytest.mark.unit
def test_non_write_tools_are_ignored(tmp_path: Path) -> None:
    result = _run("src/thing.py", UNTRUSTED, tool="Read")
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_missing_file_path_is_ignored() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Write", "tool_input": {}}),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"ATLAS_CHAT_HOOK_USER": UNTRUSTED, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("user", [TRUSTED, UNTRUSTED, ""])
def test_paths_outside_the_repository_are_not_our_business(user: str, tmp_path: Path) -> None:
    """Scratch files, other checkouts, ~/.claude — the guard covers this repo only."""
    for target in (tmp_path / "scratch.txt", Path.home() / ".claude" / "settings.json"):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}}),
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"ATLAS_CHAT_HOOK_USER": user, "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, f"{target}: {result.stderr}"
