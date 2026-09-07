#!/usr/bin/env python
"""Claude Code hook: validate subatlas_scores.json.

PostToolUse on Write/Edit when the target is named ``subatlas_scores.json``.
Checks the schema, then re-derives every ratio from the denominators recorded
alongside it — this file is arithmetic, so a wrong number is a bug rather than a
matter of judgement.

Also enforces the one rule that cannot be expressed in JSON Schema: a run with
``partition.basis == "none"`` never knew a subatlas cell set's atlas-wide size, so
it must not carry ``fraction_of_subatlas_set`` or ``f1`` at all.

Exit codes:
    0 — valid, not a subatlas_scores.json, or jsonschema unavailable
    2 — validation failed (stderr is fed back for self-correction)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path("src/atlas_chat/atlas_chat/schemas/subatlas_scores.schema.json")
TARGET = "subatlas_scores.json"
TOLERANCE = 1e-4
REGENERATE = (
    "This file is derived, not authored — regenerate it with "
    "`python -m atlas_chat.cli_subatlas_scores` rather than hand-editing:"
)


def _targets(file_path: str) -> bool:
    return bool(file_path) and Path(file_path).name == TARGET


def _schema_errors(data: Any) -> list[str]:
    if not SCHEMA_PATH.exists():
        return []
    try:
        import jsonschema
    except ImportError:
        return []
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    return [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    ]


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _arithmetic_errors(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["(root): expected an object"]

    degraded = bool(data.get("degraded"))
    basis = (data.get("partition") or {}).get("basis")
    if degraded != (basis == "none"):
        errors.append(
            f"degraded is {degraded} but partition.basis is {basis!r} — "
            "a run is degraded exactly when no partition was found"
        )

    for cell_set in data.get("cell_sets") or []:
        where = f"{cell_set.get('labelset')}/{cell_set.get('cell_label')}"
        n_cells = cell_set.get("n_cells")
        for overlap in cell_set.get("overlaps") or []:
            label = overlap.get("subatlas_cell_label")
            tag = f"{where} <- {overlap.get('subatlas_paper')}::{label}"
            cells = overlap.get("overlap_cells", 0)
            contribution = overlap.get("subatlas_contribution_cells", 0)

            if cells > contribution:
                errors.append(
                    f"{tag}: overlap_cells {cells} exceeds "
                    f"subatlas_contribution_cells {contribution}"
                )
            if contribution and not _close(overlap.get("purity", 0), cells / contribution):
                errors.append(
                    f"{tag}: purity {overlap.get('purity')} != "
                    f"{cells}/{contribution} = {cells / contribution:.4f}"
                )

            total = overlap.get("subatlas_set_total_cells")
            fraction = overlap.get("fraction_of_subatlas_set")
            if degraded and (fraction is not None or "f1" in overlap):
                errors.append(
                    f"{tag}: this run has no partition, so a subatlas cell set's "
                    "atlas-wide size was never known — fraction_of_subatlas_set and "
                    "f1 must be absent"
                )
            if total and fraction is not None:
                if cells > total:
                    errors.append(
                        f"{tag}: overlap_cells {cells} exceeds the subatlas cell set's "
                        f"atlas-wide total {total}"
                    )
                if not _close(fraction, cells / total):
                    errors.append(
                        f"{tag}: fraction_of_subatlas_set {fraction} != "
                        f"{cells}/{total} = {cells / total:.4f}"
                    )
            if "f1" in overlap and fraction is not None:
                purity = overlap.get("purity", 0)
                expected = (
                    2 * fraction * purity / (fraction + purity) if (fraction + purity) else 0.0
                )
                if not _close(overlap["f1"], expected):
                    errors.append(
                        f"{tag}: f1 {overlap['f1']} is not the harmonic mean of "
                        f"fraction_of_subatlas_set {fraction} and purity {purity} "
                        f"(expected {expected:.4f})"
                    )
            if (
                "fraction_of_atlas_set" in overlap
                and n_cells
                and not _close(overlap["fraction_of_atlas_set"], cells / n_cells)
            ):
                errors.append(
                    f"{tag}: fraction_of_atlas_set {overlap['fraction_of_atlas_set']} "
                    f"!= {cells}/{n_cells} = {cells / n_cells:.4f}"
                )
    return errors


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not _targets(file_path):
        return 0

    content = tool_input.get("content", "")
    if not content and Path(file_path).exists():
        content = Path(file_path).read_text()
    if not content:
        print(f"{TARGET} is empty", file=sys.stderr)
        return 2

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"{TARGET} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    errors = _schema_errors(data) + _arithmetic_errors(data)
    if not errors:
        return 0

    print("SUBATLAS SCORES VALIDATION FAILED", file=sys.stderr)
    print(REGENERATE, file=sys.stderr)
    for error in errors[:40]:
        print(f"  - {error}", file=sys.stderr)
    if len(errors) > 40:
        print(f"  ... and {len(errors) - 40} more", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
