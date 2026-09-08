#!/usr/bin/env python
"""Claude Code hook: validate a project's CAS+ document.

Runs as a PostToolUse hook on ``Write|Edit|MultiEdit`` and on ``Bash``. It
covers the two ways a ``cas.json`` changes during a session:

* **An agent edits it.** The tool reports a ``file_path``; if that is a
  ``cas.json``, it is validated.
* **An agent's code writes it.** A script run through Bash reports no file path
  at all, so the hook instead re-validates any ``cas.json`` under ``projects/``
  whose size or mtime moved since the last run. A small cache under
  ``.claude/`` keeps the common case to a few ``stat`` calls rather than a
  parse of every document.

The file is read **from disk** in both cases. An earlier version validated
``tool_input["content"]``, which meant it checked what an agent said it was
writing rather than what landed — invisible to scripts, and a spurious failure
on ``Edit``, whose input carries ``old_string``/``new_string`` and no
``content`` at all.

Checks come from the package rather than being restated here:
:func:`atlas_chat.validation.cas_checker.validate_cas_file` — schema shape plus
the cross-field rules a schema cannot express (warnings by default, since a
CAS+ document is filled in across passes).

Exit codes:
    0 — valid, nothing relevant changed, or the checker is unavailable
    2 — validation failed (Claude sees stderr and self-corrects)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CACHE = Path(".claude/.cas_state.json")
SEARCH_ROOT = Path("projects")


def _is_cas(file_path: str) -> bool:
    return bool(file_path) and Path(file_path).name == "cas.json"


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _changed_on_disk() -> list[Path]:
    """CAS+ documents whose bytes moved since the last run of this hook."""
    if not SEARCH_ROOT.is_dir():
        return []
    try:
        previous = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}

    current: dict[str, str] = {}
    changed: list[Path] = []
    for path in sorted(SEARCH_ROOT.rglob("cas.json")):
        try:
            mark = _fingerprint(path)
        except OSError:
            continue
        key = str(path)
        current[key] = mark
        if previous.get(key) != mark:
            changed.append(path)

    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(current, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass

    # First ever run: record the baseline, do not report every project as changed.
    return [] if not previous else changed


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    file_path = hook_input.get("tool_input", {}).get("file_path", "")

    targets: list[Path] = []
    if _is_cas(file_path):
        targets.append(Path(file_path))
    else:
        targets.extend(_changed_on_disk())

    if not targets:
        return 0

    try:
        from atlas_chat.validation.cas_checker import validate_cas_file
    except ImportError:
        print("atlas_chat not importable — skipping cas_annotation check", file=sys.stderr)
        return 0

    failed = False
    for target in targets:
        passed, messages = validate_cas_file(target)
        if passed:
            continue
        failed = True
        print("CAS_ANNOTATION VALIDATION FAILED", file=sys.stderr)
        print(f"Fix these issues in {target}:", file=sys.stderr)
        for message in messages:
            print(f"  - {message}", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
