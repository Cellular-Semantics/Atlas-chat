#!/usr/bin/env python
"""Claude Code hook: validate subatlas_read_plan.json.

PostToolUse on Write/Edit when the target is named ``subatlas_read_plan.json``.
Checks the schema, then the rules that make the plan trustworthy as a derived
artefact:

* every question traces to an overlap in the sibling ``subatlas_scores.json``,
  with the same numbers — the plan is a cut of the scores, not a second opinion;
* a question marked ``included_by: "synonym"`` really is named by a CAS+ synonym
  of one of its atlas cell sets, under the sign-safe comparison (``CDKN1A+`` must
  not match ``CDKN1A-``);
* a question marked ``included_by: "f1"`` actually cleared the recorded floor;
* ``nested_under`` points at another atlas cell set in the same question, and no
  atlas cell set that another one is nested under survives — the coarser claimant
  is dropped in favour of the more specific one.

The sibling scores file is looked for beside the plan; if it is absent the
cross-checks are skipped rather than failed.

Exit codes:
    0 — valid, not a subatlas_read_plan.json, or jsonschema unavailable
    2 — validation failed (stderr is fed back for self-correction)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path("src/atlas_chat/atlas_chat/schemas")
SCHEMA_PATH = SCHEMA_DIR / "subatlas_read_plan.schema.json"
TARGET = "subatlas_read_plan.json"
SIBLING = "subatlas_scores.json"
TOLERANCE = 1e-4
REGENERATE = (
    "This file is derived, not authored — regenerate it with "
    "`python -m atlas_chat.cli_subatlas_scores` rather than hand-editing:"
)

_SEPARATORS = re.compile(r"[\s_\-/]+")
_TRAILING_SIGN = re.compile(r"([+-])$")


def _normalise(label: str) -> tuple[str, str]:
    """Mirror of services.subatlas_scoring.normalise_label — kept in step with it."""
    text = label.strip().casefold()
    match = _TRAILING_SIGN.search(text)
    sign = match.group(1) if match else ""
    if sign:
        text = text[:-1]
    return _SEPARATORS.sub("", text), sign


def _targets(file_path: str) -> bool:
    return bool(file_path) and Path(file_path).name == TARGET


def _schema_errors(data: Any) -> list[str]:
    if not SCHEMA_PATH.exists():
        return []
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(SCHEMA_PATH.read_text())
    scores_schema = SCHEMA_DIR / "subatlas_scores.schema.json"
    if scores_schema.exists():
        from referencing import Registry, Resource

        loaded = json.loads(scores_schema.read_text())
        registry = Registry().with_resource(
            loaded.get("$id", "subatlas_scores.schema.json"),
            Resource.from_contents(loaded),
        )
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
    else:
        validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    ]


def _index_scores(scores: Any) -> tuple[dict[tuple[str, str, str, str], dict], dict[str, set]]:
    """(paper, subatlas label, labelset, atlas label) -> overlap; plus synonyms per cell set."""
    overlaps: dict[tuple[str, str, str, str], dict] = {}
    synonyms: dict[str, set] = {}
    for cell_set in scores.get("cell_sets") or []:
        key = f"{cell_set.get('labelset')}/{cell_set.get('cell_label')}"
        synonyms[key] = {_normalise(s) for s in cell_set.get("synonyms") or []}
        for overlap in cell_set.get("overlaps") or []:
            overlaps[
                (
                    str(overlap.get("subatlas_paper")),
                    str(overlap.get("subatlas_cell_label")),
                    str(cell_set.get("labelset")),
                    str(cell_set.get("cell_label")),
                )
            ] = overlap
    return overlaps, synonyms


def _cross_field_errors(data: Any, scores: Any | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["(root): expected an object"]

    thresholds = data.get("thresholds") or {}
    f1_floor = thresholds.get("f1_floor", 0.0)
    min_cells = thresholds.get("min_overlap_cells", 0)
    degraded = bool(data.get("degraded"))
    overlaps, synonyms = _index_scores(scores) if scores else ({}, {})

    for paper in data.get("papers") or []:
        for question in paper.get("questions") or []:
            label = question.get("subatlas_cell_label", "")
            tag = f"{paper.get('subatlas_paper')}::{label}"
            refs = question.get("atlas_cell_sets") or []
            included_by = question.get("included_by")

            if degraded and included_by == "f1":
                errors.append(
                    f"{tag}: included_by is 'f1' on a degraded run, where f1 was never computed"
                )
            if not degraded and included_by == "purity_only":
                errors.append(
                    f"{tag}: included_by is 'purity_only' but this run has a partition, "
                    "so f1 was available"
                )

            accessions = {r["cell_set_accession"] for r in refs if r.get("cell_set_accession")}
            for ref in refs:
                ref_tag = f"{tag} -> {ref.get('labelset')}/{ref.get('cell_label')}"
                nested = ref.get("nested_under")
                if nested and nested not in accessions:
                    errors.append(
                        f"{ref_tag}: nested_under {nested!r} is not an atlas cell set "
                        "listed in this question"
                    )
                if ref.get("cell_set_accession") and any(
                    other.get("nested_under") == ref["cell_set_accession"] for other in refs
                ):
                    errors.append(
                        f"{ref_tag}: a more specific atlas cell set in this question is "
                        "nested under it, so this coarser one should have been dropped"
                    )
                if not scores:
                    continue
                key = (
                    str(paper.get("subatlas_paper")),
                    str(label),
                    str(ref.get("labelset")),
                    str(ref.get("cell_label")),
                )
                overlap = overlaps.get(key)
                if overlap is None:
                    errors.append(
                        f"{ref_tag}: no matching overlap in {SIBLING} — every question "
                        "must trace to a scored overlap"
                    )
                    continue
                for field in ("overlap_cells", "purity", "fraction_of_subatlas_set", "f1"):
                    if (
                        field in ref
                        and field in overlap
                        and abs(float(ref[field]) - float(overlap[field])) > TOLERANCE
                    ):
                        errors.append(
                                f"{ref_tag}: {field} {ref[field]} disagrees with "
                                f"{SIBLING} ({overlap[field]})"
                            )
                if (
                    ref.get("overlap_shape")
                    and overlap.get("overlap_shape")
                    and ref["overlap_shape"] != overlap["overlap_shape"]
                ):
                    errors.append(
                        f"{ref_tag}: overlap_shape {ref['overlap_shape']!r} disagrees "
                        f"with {SIBLING} ({overlap['overlap_shape']!r})"
                    )
                if ref.get("matched_synonym"):
                    cell_set_key = f"{ref.get('labelset')}/{ref.get('cell_label')}"
                    pair = _normalise(ref["matched_synonym"])
                    if pair != _normalise(label):
                        errors.append(
                            f"{ref_tag}: matched_synonym {ref['matched_synonym']!r} does "
                            f"not match {label!r} under the sign-safe comparison"
                        )
                    elif cell_set_key in synonyms and pair not in synonyms[cell_set_key]:
                        errors.append(
                            f"{ref_tag}: matched_synonym {ref['matched_synonym']!r} is not "
                            "a CAS+ synonym of this atlas cell set"
                        )

            if included_by == "synonym" and not any(r.get("matched_synonym") for r in refs):
                errors.append(
                    f"{tag}: included_by is 'synonym' but no atlas cell set records the "
                    "matched_synonym that force-included it"
                )
            if included_by == "f1":
                if any(r.get("overlap_cells", 0) < min_cells for r in refs):
                    errors.append(
                        f"{tag}: included_by is 'f1' but an atlas cell set falls below "
                        f"min_overlap_cells {min_cells}"
                    )
                if refs and all(r.get("f1", 0.0) < f1_floor for r in refs):
                    errors.append(
                        f"{tag}: included_by is 'f1' but no atlas cell set reaches "
                        f"f1_floor {f1_floor}"
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

    scores = None
    sibling = Path(file_path).with_name(SIBLING)
    if sibling.exists():
        try:
            scores = json.loads(sibling.read_text())
        except json.JSONDecodeError:
            scores = None

    errors = _schema_errors(data) + _cross_field_errors(data, scores)
    if not errors:
        return 0

    print("SUBATLAS READ PLAN VALIDATION FAILED", file=sys.stderr)
    print(REGENERATE, file=sys.stderr)
    for error in errors[:40]:
        print(f"  - {error}", file=sys.stderr)
    if len(errors) > 40:
        print(f"  ... and {len(errors) - 40} more", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
