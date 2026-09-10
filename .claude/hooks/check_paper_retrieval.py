#!/usr/bin/env python
"""Claude Code hook: validate a paper's retrieval.json.

Runs as a PostToolUse hook on Write/Edit. Fires only for a ``retrieval.json``,
which is a name nothing else in the project uses.

Both checks come from the service rather than being restated here — the schema
is the source of truth and the cross-field rules live next to the code that
writes records:

* :func:`atlas_chat.services.paper_fetch.validate_retrieval` — shape.
* :func:`atlas_chat.services.paper_fetch.cross_check_retrieval` — the rules a
  schema cannot express, e.g. a record claiming a route with nothing stored.

Exit codes:
    0 — valid, or not a retrieval record
    2 — validation failed (Claude sees stderr and self-corrects)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or Path(file_path).name != "retrieval.json":
        return 0

    # Prefer what is on disk: PostToolUse runs after the write, and an Edit
    # carries no full content in tool_input.
    raw = tool_input.get("content", "")
    path = Path(file_path)
    if path.exists():
        raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        print("retrieval record is empty", file=sys.stderr)
        return 2

    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"retrieval record is not valid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        from atlas_chat.services.paper_fetch import (
            PaperFetchError,
            cross_check_retrieval,
            validate_retrieval,
        )
    except ImportError as exc:  # pragma: no cover - environment guard
        print(f"cannot import paper_fetch to validate: {exc}", file=sys.stderr)
        return 0

    errors: list[str] = []
    try:
        validate_retrieval(record)
    except PaperFetchError as exc:
        errors.append(str(exc))
    else:
        errors.extend(cross_check_retrieval(record))

    if not errors:
        return 0

    print("PAPER RETRIEVAL VALIDATION FAILED", file=sys.stderr)
    print(f"Fix these issues in {file_path}:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
