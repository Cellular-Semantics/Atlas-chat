"""Validate a project's CAS+ document.

One implementation, three callers: the ``cas_annotation`` Claude Code hook, the
``cli_cas`` command line, and CI over the committed test-project fixtures. They
must not drift, so all three read the file from disk through
:func:`validate_cas_file` rather than validating whatever a caller happens to
hold in memory.

Two layers of checking:

* **Shape** — the JSON Schema at ``cas_annotation.schema.json``.
* **Cross-field rules the schema cannot express** — references that must
  resolve, and counts that must agree. These are reported as warnings by
  default and as errors under ``strict``, because a CAS+ document is filled in
  across passes and a partially-populated one is legitimately incomplete rather
  than wrong.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..schemas import load_schema

CAS_SCHEMA = "cas_annotation.schema.json"


def schema_errors(document: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Return JSON Schema violations, one readable line each."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema or load_schema(CAS_SCHEMA))
    errors: list[str] = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path)):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(f"{location or '(root)'}: {error.message}")
    return errors


def cross_field_errors(document: Any) -> list[str]:
    """Return violations of rules the JSON Schema cannot express.

    Every rule here is skipped when the field it depends on is absent — the
    point is to catch a document that contradicts itself, not one that is
    merely incomplete.
    """
    if not isinstance(document, dict):
        return []

    problems: list[str] = []
    annotations = document.get("annotations") or []
    labelsets = document.get("labelsets") or []

    declared = {ls.get("name") for ls in labelsets if isinstance(ls, dict)}
    accessions = {
        a.get("cell_set_accession")
        for a in annotations
        if isinstance(a, dict) and a.get("cell_set_accession")
    }
    registry = {
        p.get("label")
        for p in (document.get("source") or {}).get("subatlas_papers") or []
        if isinstance(p, dict)
    }

    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            continue
        where = annotation.get("cell_set_accession") or f"annotations[{index}]"

        labelset = annotation.get("labelset")
        if labelset is not None and labelset not in declared:
            problems.append(f"{where}: labelset {labelset!r} is not declared in labelsets")

        parent = annotation.get("parent_cell_set_accession")
        if parent is not None and parent not in accessions:
            problems.append(
                f"{where}: parent_cell_set_accession {parent!r} matches no cell_set_accession"
            )
        if parent is not None and parent == annotation.get("cell_set_accession"):
            problems.append(f"{where}: parent_cell_set_accession points at itself")

        problems.extend(_composition_errors(where, annotation))
        problems.extend(_transfer_errors(where, annotation, registry))

    problems.extend(_subatlas_paper_errors(document))
    return problems


def _composition_errors(where: str, annotation: dict[str, Any]) -> list[str]:
    """A composition category partitions the cell set, so its counts sum to n_cells."""
    problems: list[str] = []
    n_cells = annotation.get("n_cells")
    if n_cells is None:
        return problems
    for name, category in (annotation.get("composition") or {}).items():
        if not isinstance(category, dict):
            continue
        values = category.get("values") or []
        counts = [v.get("cell_count") for v in values if isinstance(v, dict)]
        if not counts or any(c is None for c in counts):
            continue
        total = sum(counts)
        if total != n_cells:
            problems.append(
                f"{where}: composition.{name} cell_count sums to {total}, but n_cells is {n_cells}"
            )
    return problems


def _transfer_errors(
    where: str, annotation: dict[str, Any], registry: set[str | None]
) -> list[str]:
    """Transferred annotations reference a registered study and agree on the denominator."""
    problems: list[str] = []
    transfers = annotation.get("transferred_annotations") or []
    n_cells = annotation.get("n_cells")
    contributions: dict[str, set[int]] = defaultdict(set)

    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue
        paper = transfer.get("subatlas_paper")
        if paper is not None and registry and paper not in registry:
            problems.append(f"{where}: subatlas_paper {paper!r} is not in source.subatlas_papers")

        count = transfer.get("cell_count")
        if count is not None and n_cells is not None and count > n_cells:
            problems.append(
                f"{where}: transferred {transfer.get('transferred_cell_label')!r} "
                f"cell_count {count} exceeds n_cells {n_cells}"
            )

        contribution = transfer.get("subatlas_contribution_cells")
        if contribution is not None:
            key = paper or transfer.get("source_labelset") or transfer.get("source_taxonomy")
            if key is not None:
                contributions[str(key)].add(contribution)

    for key, seen in contributions.items():
        if len(seen) > 1:
            problems.append(
                f"{where}: subatlas_contribution_cells disagrees for {key!r}: "
                f"{sorted(seen)} — it is one count per (cell set, study)"
            )
    return problems


def _subatlas_paper_errors(document: dict[str, Any]) -> list[str]:
    """A study's own cell sets partition its contribution, so they sum to total_cells."""
    problems: list[str] = []
    for paper in (document.get("source") or {}).get("subatlas_papers") or []:
        if not isinstance(paper, dict):
            continue
        total = paper.get("total_cells")
        cell_sets = paper.get("cell_sets")
        if total is None or not cell_sets:
            continue
        counts = [s.get("n_cells") for s in cell_sets if isinstance(s, dict)]
        if any(c is None for c in counts):
            continue
        summed = sum(counts)
        if summed != total:
            problems.append(
                f"source.subatlas_papers[{paper.get('label')!r}]: cell_sets n_cells "
                f"sums to {summed}, but total_cells is {total}"
            )
    return problems


def validate_cas_document(document: Any, *, strict: bool = False) -> tuple[bool, list[str]]:
    """Validate an already-parsed CAS+ document. Returns ``(passed, messages)``."""
    errors = schema_errors(document)
    if errors:
        return False, errors

    warnings = cross_field_errors(document)
    if not warnings:
        return True, []
    if strict:
        return False, warnings
    return True, [f"warning: {w}" for w in warnings]


def validate_cas_file(path: str | Path, *, strict: bool = False) -> tuple[bool, list[str]]:
    """Validate the CAS+ document at ``path``, reading it from disk.

    Reading the file rather than trusting a caller's copy is the whole point: it
    is what lets one implementation serve an agent's edit, a script's write and
    a CI run alike.
    """
    target = Path(path)
    if not target.exists():
        return False, [f"{target}: no such file"]
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [f"{target}: not valid JSON: {exc}"]
    except OSError as exc:
        return False, [f"{target}: could not be read: {exc}"]
    return validate_cas_document(document, strict=strict)


__all__ = [
    "CAS_SCHEMA",
    "cross_field_errors",
    "schema_errors",
    "validate_cas_document",
    "validate_cas_file",
]
