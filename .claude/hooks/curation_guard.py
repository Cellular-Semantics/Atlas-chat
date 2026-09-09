#!/usr/bin/env python3
"""PreToolUse hook: keep content sessions out of the infrastructure.

The guard covers this repository and nothing else — scratch files, other
checkouts and ``~/.claude`` are none of its business. Within the repository
there are two zones. ``projects/`` and ``planning/`` hold content — per-atlas
reports, traversal output, notes — and anyone may write there. Everything else
is infrastructure: source, schemas, hooks, agents, skills, tests, docs and the
root files.

Who may write infrastructure:

**Untrusted users** — no. The write is blocked and the agent is told to
capture the request as a note under ``planning/`` instead.

**Trusted users** (git ``user.email`` in :data:`TRUSTED_USERS`) — yes, but not
until ``CLAUDE_dev.md`` has been loaded into the session. Until then the write
is blocked with an instruction to read it. The agent reads the guide and
retries, so the block clears itself; the point is that nobody edits the
infrastructure without the conventions in front of them.

Acknowledgement is read from the session transcript that Claude Code passes in
the hook payload, by looking for the guide's own title line. Where no
transcript is available the check cannot run, and trusted users are allowed
through.

Exit codes:
  0 — allow the write
  2 — block the write; stderr goes back to the agent

https://docs.anthropic.com/en/docs/claude-code/hooks#exit-code-2-behavior
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Git emails permitted to write infrastructure, once they have read the guide.
TRUSTED_USERS = {
    "dosumis@gmail.com",
    "do12@sanger.ac.uk",
}

#: Top-level directories anyone may write.
CONTENT_ZONES = ("projects", "planning")

#: The guide a trusted user must have loaded before touching infrastructure.
DEV_GUIDE = "CLAUDE_dev.md"

_REPO_ROOT = Path(__file__).resolve().parents[2]

_WRITE_TOOLS = ("Write", "Edit", "MultiEdit")


def current_user() -> str | None:
    """Return the current git ``user.email``, or None if unavailable.

    ``ATLAS_CHAT_HOOK_USER`` overrides it, so tests can drive the hook without
    touching git config: unset falls through to git, empty string means no
    configured user, anything else is used as-is.
    """
    override = os.environ.get("ATLAS_CHAT_HOOK_USER")
    if override is not None:
        return override or None
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def is_content_path(file_path: Path) -> bool:
    """True if the path is inside a content zone of this repository."""
    try:
        parts = file_path.resolve().relative_to(_REPO_ROOT).parts
    except (ValueError, OSError):
        return False
    return bool(parts) and parts[0] in CONTENT_ZONES


def is_in_repo(file_path: Path) -> bool:
    """True if the path is inside this repository at all."""
    try:
        file_path.resolve().relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return False
    return True


def guide_marker() -> str | None:
    """Return the dev guide's title line, used as proof it was loaded.

    Taken from the file rather than hardcoded, so retitling the guide keeps
    both sides in step.
    """
    try:
        with (_REPO_ROOT / DEV_GUIDE).open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("# "):
                    return line.strip()
    except OSError:
        return None
    return None


def guide_was_read(transcript_path: str | None) -> bool:
    """True if the dev guide's content appears in the session transcript.

    Catches any route by which the content reached the model — the Read tool,
    ``cat`` through Bash, or an ``@CLAUDE_dev`` import. Returns True when there
    is no transcript to check, since the question cannot be answered and the
    caller has already established trust.
    """
    if not transcript_path:
        return True
    path = Path(transcript_path)
    if not path.is_file():
        return True

    marker = guide_marker()
    needles = [f"@{Path(DEV_GUIDE).stem}"]
    if marker:
        needles.append(marker)

    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    text = json.dumps(json.loads(line), ensure_ascii=False)
                except (json.JSONDecodeError, ValueError):
                    text = line
                if any(needle in text for needle in needles):
                    return True
    except OSError:
        return True
    return False


def _block(message: list[str]) -> None:
    print("\n" + "=" * 68, file=sys.stderr)
    for line in message:
        print(line, file=sys.stderr)
    print("=" * 68 + "\n", file=sys.stderr)
    sys.exit(2)


def reject_untrusted(file_path: Path, user: str | None) -> None:
    _block(
        [
            "BLOCKED: this session may not write infrastructure.",
            "",
            f"Target: {file_path}",
            f"User:   {user or '(no git user.email set)'}",
            "",
            "Writable zones: " + ", ".join(f"{zone}/" for zone in CONTENT_ZONES),
            "",
            "Everything else in this repository — src/, tests/, docs/,",
            ".claude/, root files — is infrastructure and needs a trusted git",
            "identity. Paths outside the repository are unaffected.",
            "",
            "Capture the request as a note under planning/ and stop.",
        ]
    )


def reject_unread_guide(file_path: Path, user: str | None) -> None:
    _block(
        [
            f"BLOCKED: read {DEV_GUIDE} before editing infrastructure.",
            "",
            f"Target: {file_path}",
            f"User:   {user}",
            "",
            f"You are trusted to change infrastructure, but {DEV_GUIDE} has not",
            "been loaded in this session. It carries the conventions this change",
            "has to follow — schema-first, declared input/output shapes, the",
            "validator-hook requirement, testing and writing style.",
            "",
            f"Read {DEV_GUIDE}, then make the edit again.",
        ]
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name", "") not in _WRITE_TOOLS:
        sys.exit(0)

    raw_path = payload.get("tool_input", {}).get("file_path", "")
    if not raw_path:
        sys.exit(0)

    file_path = Path(raw_path)
    if not is_in_repo(file_path) or is_content_path(file_path):
        sys.exit(0)

    user = current_user()
    if user not in TRUSTED_USERS:
        reject_untrusted(file_path, user)

    if not guide_was_read(payload.get("transcript_path")):
        reject_unread_guide(file_path, user)

    sys.exit(0)


if __name__ == "__main__":
    main()
