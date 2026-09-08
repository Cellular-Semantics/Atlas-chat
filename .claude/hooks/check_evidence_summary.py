#!/usr/bin/env python
"""Claude Code hook: check evidence_summary output, in shape and in substance.

Fires as a PostToolUse hook on Write/Edit to ``all_summaries.json`` (an array of
evidence_summary items) or any ``*evidence_summary.json`` (a single item).

Two checks. The shape is validated against ``evidence_summary.schema.json``. The
quotes are then looked for in the text they came from: job files under
``papers/`` beside the output, or one level above it, are searched, and a
quote found in none of them is rejected. Searching rather than trusting is the
point — a writer that names its own source can name it wrongly, whereas a
search cannot.

Where no job file sits beside the output there is nothing to search, so the
quote check says it could not run and the shape check stands alone. That is the
case for evidence gathered from remote snippets, whose text never lands here.

Exit codes:
    0 — valid, or file is not an evidence-summary file, or jsonschema unavailable
    2 — validation failed (Claude sees stderr and self-corrects)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_PATH = Path("src/atlas_chat/atlas_chat/schemas/evidence_summary.schema.json")


def _targets(file_path: str) -> bool:
    name = Path(file_path).name
    return name == "all_summaries.json" or name.endswith("evidence_summary.json")


def _errors(data: object, schema: dict) -> list[str]:
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    # all_summaries.json is an array of items; a lone evidence_summary is an object.
    items = data if isinstance(data, list) else [data]
    errors: list[str] = []
    for i, item in enumerate(items):
        prefix = f"[{i}]" if isinstance(data, list) else ""
        for err in sorted(validator.iter_errors(item), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in err.absolute_path)
            loc = f"{prefix}.{path}" if path else (prefix or "(root)")
            errors.append(f"{loc}: {err.message}")
    return errors


def _quote_errors(data: object, file_path: Path) -> list[str]:
    """Look for every quote in the job files beside the output, if there are any."""
    try:
        from atlas_chat.validation.quote_search import check_items, load_sources
    except ImportError:
        return []

    # Beside the output, and one level up: a read covering several cell types
    # produces one job file and one output directory per cell type, so the
    # shared paper sits above them rather than being copied into each.
    searched = [file_path.parent / "papers", file_path.parent.parent / "papers"]
    job_paths = sorted({p for d in searched for p in d.glob("*.json")})
    if not job_paths:
        print(
            "no job files under " + " or ".join(str(d) for d in searched) + " — quotes not checked",
            file=sys.stderr,
        )
        return []

    sources = load_sources(job_paths)
    if not sources:
        print("job files hold no quotable text — quotes not checked", file=sys.stderr)
        return []

    items = data if isinstance(data, list) else [data]
    return check_items([i for i in items if isinstance(i, dict)], sources)


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or not _targets(file_path):
        return 0

    content = tool_input.get("content", "")
    if not content:
        print(f"{Path(file_path).name} is empty", file=sys.stderr)
        return 2

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"{Path(file_path).name} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not SCHEMA_PATH.exists():
        return 0
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        print("jsonschema not available — skipping evidence_summary check", file=sys.stderr)
        return 0

    errors = _errors(data, json.loads(SCHEMA_PATH.read_text()))
    if not errors:
        errors = _quote_errors(data, Path(file_path))
    if not errors:
        return 0

    print("EVIDENCE_SUMMARY VALIDATION FAILED", file=sys.stderr)
    print(f"Fix these issues and rewrite {Path(file_path).name}:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
