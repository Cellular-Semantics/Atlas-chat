#!/usr/bin/env python
"""Claude Code hook: validate report quotes and references on write.

Invoked as a post-tool hook when a Write tool targets a file matching
``projects/*/reports/*.md``.  Calls the shared validation logic in
``atlas_chat.validation.report_checker``.

Exit codes:
    0 — validation passed (or file is not a report)
    2 — validation failed (Claude sees stderr and self-corrects)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    """Read hook input from stdin and validate if it's a report write."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0  # Not a JSON hook call, skip

    # Extract the file path from the hook input
    tool_input = hook_input.get("tool_input", {})
    file_path_str = tool_input.get("file_path", "")

    if not file_path_str:
        return 0

    file_path = Path(file_path_str)

    # Only validate files matching projects/*/reports/*.md
    parts = file_path.parts
    try:
        proj_idx = parts.index("projects")
    except ValueError:
        return 0

    # Check pattern: projects/{name}/reports/{cell_type}.md
    if len(parts) <= proj_idx + 3:
        return 0
    if parts[proj_idx + 2] != "reports" or not file_path.suffix == ".md":
        return 0

    # Derive traversal_dir from the report path
    # projects/{project}/reports/{cell_type}.md
    # → projects/{project}/traversal_output/{cell_type_stem}/
    project_dir = file_path.parents[1]
    cell_type = file_path.stem
    traversal_dir = project_dir / "traversal_output" / cell_type

    if not traversal_dir.exists():
        # No traversal data yet — cannot validate
        print(
            f"Warning: no traversal data at {traversal_dir}, skipping validation",
            file=sys.stderr,
        )
        return 0

    # Import and run validation
    try:
        from atlas_chat.validation.report_checker import validate_report

        passed, errors = validate_report(file_path, traversal_dir)
    except ImportError:
        print(
            "Warning: atlas_chat not installed, skipping report validation",
            file=sys.stderr,
        )
        return 0
    except Exception as exc:
        print(f"Warning: validation error: {exc}", file=sys.stderr)
        return 0

    if passed:
        return 0

    # Validation failed — output errors to stderr so Claude sees them
    print("REPORT VALIDATION FAILED", file=sys.stderr)
    print("Fix these issues and regenerate the report:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
