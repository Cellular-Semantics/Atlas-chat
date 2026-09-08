"""What a reading agent is told about a cell set before it is asked anything.

A CAS+ annotation is far too large to put in front of a reader: most of it is
the composition breakdown, which runs to hundreds of values because it records
every descriptor of every cell. Nearly all of that is donor and sample detail
that says nothing about the cell type and would crowd out the paper.

So this selects. Two rules, both of which have to be given rather than guessed:

* **which descriptor categories count as context** — where and when the cells
  were sampled, rather than everything recorded about the donors they came from;
* **a floor on how much of the cell set a value must account for** — the
  distributions have long tails of single-cell values.

The categories are named rather than the columns, so the same call works on an
atlas whose columns are named differently.

Two things are deliberately absent. Anything stating the biology the reader is
being asked to find — markers, ontology terms — stays out, because supplying it
invites the reader to recognise it in the text rather than find it. And children
are included precisely so that a subdivision is not offered back as another name
for the whole.

Nothing here calls a model.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Descriptor categories that say where and when the cells were sampled, as
#: against what was recorded about their donors.
CONTEXT_CATEGORIES = ("tissue", "development_stage")

#: A descriptor value is carried when it accounts for at least this much of the
#: cell set.
DEFAULT_MIN_RATIO = 0.01


class SubjectBlockError(RuntimeError):
    """Raised when a requested cell set is not in the document."""


def _relations(annotations: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Accession → label, and accession → the labels of its children."""
    label_of = {
        a["cell_set_accession"]: a["cell_label"] for a in annotations if a.get("cell_set_accession")
    }
    children: dict[str, list[str]] = {}
    for a in annotations:
        parent = a.get("parent_cell_set_accession")
        if parent:
            children.setdefault(parent, []).append(a["cell_label"])
    return label_of, children


def _context(
    annotation: dict[str, Any], categories: tuple[str, ...], min_ratio: float
) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for column, entry in (annotation.get("composition") or {}).items():
        category = entry.get("category")
        if category not in categories:
            continue
        ranked = sorted(entry.get("values") or [], key=lambda v: -(v.get("cell_ratio") or 0))
        kept = [str(v["author_value"]) for v in ranked if (v.get("cell_ratio") or 0) >= min_ratio]
        if kept:
            out.setdefault(category, {})[column] = kept
    return out


def build(
    annotation: dict[str, Any],
    *,
    label_of: dict[str, str],
    children: dict[str, list[str]],
    categories: tuple[str, ...] = CONTEXT_CATEGORIES,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> dict[str, Any]:
    """Assemble the block for one annotation.

    Args:
        annotation: the CAS+ annotation.
        label_of: accession → label, for naming the parent.
        children: accession → child labels.
        categories: descriptor categories to carry as context.
        min_ratio: floor on a value's share of the cell set.

    Returns:
        The block, with absent parts omitted rather than written empty.
    """
    block: dict[str, Any] = {"cell_label": annotation["cell_label"]}
    fullname = annotation.get("cell_fullname")
    if fullname and fullname != annotation["cell_label"]:
        block["cell_fullname"] = fullname
    block["labelset"] = annotation["labelset"]
    block["n_cells"] = annotation.get("n_cells", 0)

    if annotation.get("synonyms"):
        block["synonyms"] = list(annotation["synonyms"])
    parent = label_of.get(annotation.get("parent_cell_set_accession") or "")
    if parent:
        block["parent"] = parent
    kids = children.get(annotation.get("cell_set_accession") or "")
    if kids:
        block["children"] = sorted(kids)

    context = _context(annotation, categories, min_ratio)
    if context:
        block["context"] = context
    return block


def build_all(
    cas_doc: dict[str, Any],
    cell_labels: list[str] | None = None,
    *,
    categories: tuple[str, ...] = CONTEXT_CATEGORIES,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> list[dict[str, Any]]:
    """Blocks for the named cell sets, in the order asked for.

    Args:
        cas_doc: the CAS+ document.
        cell_labels: which cell sets to build for. All of them when omitted.
        categories: descriptor categories to carry as context.
        min_ratio: floor on a value's share of the cell set.

    Returns:
        One block per requested label.

    Raises:
        SubjectBlockError: a requested label is not in the document. A silently
            missing subject would become a cell type nobody was asked about.
    """
    annotations = cas_doc.get("annotations") or []
    label_of, children = _relations(annotations)
    by_label: dict[str, dict[str, Any]] = {a["cell_label"]: a for a in annotations}

    wanted = cell_labels if cell_labels is not None else [a["cell_label"] for a in annotations]
    missing = [label for label in wanted if label not in by_label]
    if missing:
        raise SubjectBlockError(f"not in the document: {', '.join(sorted(missing))}")

    return [
        build(
            by_label[label],
            label_of=label_of,
            children=children,
            categories=categories,
            min_ratio=min_ratio,
        )
        for label in wanted
    ]


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_subject_block",
        description="Assemble what a reading agent is told about one or more cell sets.",
    )
    parser.add_argument("--cas", required=True, help="the CAS+ document")
    parser.add_argument("--label", action="append", help="repeatable; all cell sets when omitted")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=DEFAULT_MIN_RATIO,
        help=f"floor on a value's share of the cell set (default {DEFAULT_MIN_RATIO})",
    )
    parser.add_argument(
        "--category",
        action="append",
        help=f"repeatable; default {' '.join(CONTEXT_CATEGORIES)}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cas_doc = json.loads(Path(args.cas).read_text(encoding="utf-8"))
    try:
        blocks = build_all(
            cas_doc,
            args.label,
            categories=tuple(args.category) if args.category else CONTEXT_CATEGORIES,
            min_ratio=args.min_ratio,
        )
    except SubjectBlockError as exc:
        print(str(exc))
        return 2
    payload = json.dumps(blocks, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        chars = sum(len(json.dumps(b)) for b in blocks)
        print(f"{len(blocks)} subject blocks, {chars:,} chars -> {args.out}")
    else:
        print(payload)
    return 0
