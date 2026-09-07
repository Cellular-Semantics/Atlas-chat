"""Score how atlas cell sets overlap the cell sets of contributing studies.

Two independent groupings of the same cells are in play, and this module never
conflates them:

* an **atlas cell set** is one the atlas defines — a CAS+ ``annotations[]`` entry,
  named by ``cell_label``;
* a **subatlas cell set** is one a contributing study defines — named by
  ``transferred_cell_label``, its size *as integrated* being however many of its
  cells reached the atlas.

``transferred_annotations`` is the joint table of the two. Three ratios come out of
it, and the denominators are the whole point:

``purity``
    ``overlap_cells / subatlas_contribution_cells`` — of what this study contributed
    to this atlas cell set, the fraction that is this one subatlas cell set. The
    denominator is the study's contribution and deliberately **not** ``n_cells``:
    most cells in an atlas cell set usually came from other studies that never saw
    them, and counting those would penalise a study for cells it had no part in.

``fraction_of_subatlas_set``
    ``overlap_cells / subatlas_set_total_cells`` — of the subatlas cell set, the
    fraction that landed here. Needs the subatlas cell set's atlas-wide size, which
    is summed over a partition (see :func:`find_partition`).

``fraction_of_atlas_set``
    ``overlap_cells / n_cells``. Recorded, never gated — confounded by every other
    study's cells.

The cutoff is applied to the harmonic mean of the first two. Neither alone will do.
On the reference project 575 overlaps have ``fraction_of_subatlas_set >= 0.9`` and
405 of those have ``purity < 0.5``: a coarse atlas cell set that absorbed a fine
subatlas one whole scores perfectly on the first ratio and means nothing.

One rule sits outside the arithmetic. Where an atlas cell set's CAS+ ``synonyms``
name a subatlas cell set, that overlap is included whatever its f1, because an
asserted correspondence is invisible to an overlap statistic — on the reference
project the atlas's own synonym ``aPCV`` scores f1 0.027 and ranks seventh of eight.
The match is sign-safe (``CDKN1A+`` must not match ``CDKN1A-``) and scoped to the
atlas cell set's own provenance.

No model call is involved anywhere in this module.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_F1_FLOOR = 0.2
DEFAULT_MIN_OVERLAP_CELLS = 25
DEFAULT_PURITY_FLOOR = 0.5
DEFAULT_RECORD_FLOOR = 0.02
DEFAULT_SHAPE_HIGH = 0.5
DEFAULT_SENSITIVITY_FLOORS = (0.05, 0.1, 0.2, 0.3, 0.5)

_DOI_PREFIX = "DOI:"
_SEPARATORS = re.compile(r"[\s_\-/]+")
_TRAILING_SIGN = re.compile(r"([+-])$")

__all__ = [
    "DEFAULT_F1_FLOOR",
    "DEFAULT_MIN_OVERLAP_CELLS",
    "DEFAULT_PURITY_FLOOR",
    "DEFAULT_RECORD_FLOOR",
    "DEFAULT_SHAPE_HIGH",
    "Thresholds",
    "build_parser",
    "find_partition",
    "main",
    "normalise_label",
    "read_plan",
    "score",
    "sensitivity",
]


@dataclass(frozen=True)
class Thresholds:
    """Cutoff policy, recorded on every output so a change is a visible diff."""

    f1_floor: float = DEFAULT_F1_FLOOR
    min_overlap_cells: int = DEFAULT_MIN_OVERLAP_CELLS
    purity_floor: float = DEFAULT_PURITY_FLOOR
    record_floor: float = DEFAULT_RECORD_FLOOR
    shape_high: float = DEFAULT_SHAPE_HIGH

    def to_dict(self) -> dict[str, Any]:
        return {
            "f1_floor": self.f1_floor,
            "min_overlap_cells": self.min_overlap_cells,
            "purity_floor": self.purity_floor,
            "record_floor": self.record_floor,
            "shape_high": self.shape_high,
        }


def normalise_label(label: str) -> tuple[str, str]:
    """Normalise a cell-set name for comparison, keeping marker sign.

    Case, underscores, hyphens, slashes and whitespace are noise: ``ePV2`` and
    ``ePV_2`` are the same cell set, as are ``TIP`` and ``Tip``. A **trailing**
    ``+`` or ``-`` is not noise — ``PV-MYH11_CDKN1A+`` and ``PV-MYH11_CDKN1A-`` are
    opposite marker states, and squashing them together produced six cross-matches
    on the reference project.

    Returns:
        ``(base, sign)``, where ``sign`` is ``"+"``, ``"-"`` or ``""``.

    .. code-block:: python

        normalise_label("ePV_2")             # ("epv2", "")
        normalise_label("PV-MYH11_CDKN1A+")  # ("pvmyh11cdkn1a", "+")
    """
    text = label.strip().casefold()
    match = _TRAILING_SIGN.search(text)
    sign = match.group(1) if match else ""
    if sign:
        text = text[:-1]
    return _SEPARATORS.sub("", text), sign


def _contributor_key(item: Mapping[str, Any]) -> str:
    return str(item.get("subatlas_paper") or item.get("source_taxonomy") or "")


def _registry(cas_doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    source = cas_doc.get("source") or {}
    return {
        str(paper["label"]): paper
        for paper in source.get("subatlas_papers") or []
        if paper.get("label")
    }


def _doi_of(key: str, entry: Mapping[str, Any] | None) -> str | None:
    if entry and entry.get("doi"):
        return str(entry["doi"])
    if key.startswith(_DOI_PREFIX):
        return key[len(_DOI_PREFIX) :]
    if key.startswith("10."):
        return key
    return None


def _f1(a: float, b: float) -> float:
    return 2 * a * b / (a + b) if (a + b) else 0.0


def find_partition(cas_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Find a set of atlas cell sets covering every cell exactly once.

    Needed only to size a subatlas cell set atlas-wide. Found, never assumed:
    annotation is not always hierarchical, and one labelset does not always cover
    the atlas.

    1. If any cell set carries ``parent_cell_set_accession``, the candidate is the
       **leaves** — cell sets that are no other cell set's parent. These commonly
       span several labelsets, which is exactly why "take the finest labelset" is
       wrong: on the reference project the finest labelset alone misses 319,107 of
       2,235,448 cells and inflates ``fraction_of_subatlas_set`` by up to 2.7x.
    2. Otherwise each labelset is a candidate, finest (most cell sets) first.
    3. A candidate is usable only if every cell set in it carries ``n_cells``, and,
       where there is more than one candidate, the totals agree.

    Returns:
        A ``partition`` object for the scores document. ``basis`` is ``"none"`` when
        nothing was usable, with ``reason`` saying why; the caller then runs
        degraded rather than guessing a denominator.
    """
    annotations = list(cas_doc.get("annotations") or [])
    if not annotations:
        return {"basis": "none", "reason": "the CAS+ document has no annotations"}

    parents = {
        a["parent_cell_set_accession"] for a in annotations if a.get("parent_cell_set_accession")
    }

    def _describe(
        cell_sets: Sequence[Mapping[str, Any]], basis: str, **extra: Any
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "basis": basis,
            "n_cell_sets": len(cell_sets),
            "total_cells": sum(int(a.get("n_cells") or 0) for a in cell_sets),
            "labelsets_spanned": sorted({str(a.get("labelset", "")) for a in cell_sets}),
        }
        out.update(extra)
        return out

    if parents:
        leaves = [a for a in annotations if a.get("cell_set_accession") not in parents]
        missing = [a for a in leaves if a.get("n_cells") is None]
        if missing:
            return {
                "basis": "none",
                "reason": (
                    f"{len(missing)} of {len(leaves)} leaf cell sets have no n_cells, "
                    "so a subatlas cell set's atlas-wide size cannot be summed"
                ),
            }
        return _describe(leaves, "hierarchy_leaves")

    by_labelset: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for a in annotations:
        by_labelset[str(a.get("labelset", ""))].append(a)

    usable: dict[str, int] = {}
    for name, cell_sets in by_labelset.items():
        if any(a.get("n_cells") is None for a in cell_sets):
            continue
        usable[name] = sum(int(a["n_cells"]) for a in cell_sets)

    if not usable:
        return {
            "basis": "none",
            "reason": (
                "no labelset has n_cells on every cell set, and there is no "
                "hierarchy to take leaves from"
            ),
        }
    if len(usable) > 1 and len(set(usable.values())) > 1:
        totals = ", ".join(f"{k}={v}" for k, v in sorted(usable.items()))
        return {
            "basis": "none",
            "reason": (
                "candidate labelsets disagree on the atlas total and there are no "
                f"parent links to take leaves from ({totals}); none can be validated "
                "as covering the atlas"
            ),
        }

    chosen = max(usable, key=lambda name: len(by_labelset[name]))
    return _describe(by_labelset[chosen], "labelset", labelset=chosen)


def _subatlas_set_totals(
    cas_doc: Mapping[str, Any], partition: Mapping[str, Any]
) -> dict[tuple[str, str], int]:
    """Size every subatlas cell set atlas-wide by summing over the partition."""
    if partition.get("basis") == "none":
        return {}
    annotations = list(cas_doc.get("annotations") or [])
    parents = {
        a["parent_cell_set_accession"] for a in annotations if a.get("parent_cell_set_accession")
    }
    if partition["basis"] == "hierarchy_leaves":
        members: Iterable[Mapping[str, Any]] = (
            a for a in annotations if a.get("cell_set_accession") not in parents
        )
    else:
        members = (a for a in annotations if a.get("labelset") == partition.get("labelset"))

    totals: dict[tuple[str, str], int] = defaultdict(int)
    for annotation in members:
        for item in annotation.get("transferred_annotations") or []:
            key = (_contributor_key(item), str(item.get("transferred_cell_label", "")))
            totals[key] += int(item.get("cell_count") or 0)
    return dict(totals)


def _shape(fraction_of_subatlas_set: float | None, purity: float, thresholds: Thresholds) -> str:
    if fraction_of_subatlas_set is None:
        return "unknown"
    high = thresholds.shape_high
    sub_high = fraction_of_subatlas_set >= high
    pure = purity >= high
    if sub_high and pure:
        return "one_to_one"
    if pure and not sub_high:
        return "atlas_set_within_subatlas_set"
    if sub_high and not pure:
        return "subatlas_set_within_atlas_set"
    return "weak"


def score(
    cas_doc: Mapping[str, Any],
    *,
    thresholds: Thresholds | None = None,
    non_paper_labels: Sequence[str] = (),
    cas_source: str = "",
    sensitivity_floors: Sequence[float] = DEFAULT_SENSITIVITY_FLOORS,
) -> dict[str, Any]:
    """Measure every atlas cell set's overlap with every subatlas cell set.

    Pure: no network, no model, no filesystem. Conforms to
    ``subatlas_scores.schema.json``.

    Args:
        cas_doc: A CAS+ document.
        thresholds: Cutoff policy; defaults recorded on the output.
        non_paper_labels: Provenance keys that are not studies at all (e.g.
            ``whole_embryo``), excluded from scoring.
        cas_source: Path recorded on the output for provenance.
        sensitivity_floors: f1 floors to report the effect of.
    """
    thresholds = thresholds or Thresholds()
    partition = find_partition(cas_doc)
    degraded = partition["basis"] == "none"
    totals = _subatlas_set_totals(cas_doc, partition)
    registry = _registry(cas_doc)
    excluded = set(non_paper_labels)

    cell_sets: list[dict[str, Any]] = []
    unpublished: dict[str, dict[str, Any]] = {}

    for annotation in cas_doc.get("annotations") or []:
        items = [
            item
            for item in annotation.get("transferred_annotations") or []
            if _contributor_key(item) and _contributor_key(item) not in excluded
        ]
        if not items:
            continue

        n_cells = annotation.get("n_cells")
        contribution: dict[str, int] = defaultdict(int)
        for item in items:
            contribution[_contributor_key(item)] += int(item.get("cell_count") or 0)

        overlaps: list[dict[str, Any]] = []
        tail: dict[str, dict[str, Any]] = {}

        for item in items:
            key = _contributor_key(item)
            overlap_cells = int(item.get("cell_count") or 0)
            denominator = contribution[key]
            if not denominator:
                continue
            purity = round(overlap_cells / denominator, 4)
            entry = registry.get(key)
            doi = _doi_of(key, entry)

            if doi is None:
                record = unpublished.setdefault(
                    key,
                    {"subatlas_paper": key, "n_atlas_cell_sets": 0, "overlap_cells": 0},
                )
                record["overlap_cells"] += overlap_cells
                if entry and entry.get("status"):
                    record["status"] = str(entry["status"])

            subatlas_label = str(item.get("transferred_cell_label", ""))
            if purity < thresholds.record_floor:
                rolled = tail.setdefault(
                    key,
                    {"subatlas_paper": key, "n_subatlas_cell_sets": 0, "overlap_cells": 0},
                )
                rolled["n_subatlas_cell_sets"] += 1
                rolled["overlap_cells"] += overlap_cells
                continue

            overlap: dict[str, Any] = {
                "subatlas_paper": key,
                "subatlas_cell_label": subatlas_label,
                "overlap_cells": overlap_cells,
                "subatlas_contribution_cells": denominator,
                "purity": purity,
            }
            if doi:
                overlap["doi"] = doi
            if item.get("source_labelset"):
                overlap["source_labelset"] = str(item["source_labelset"])
            if n_cells:
                overlap["fraction_of_atlas_set"] = round(overlap_cells / int(n_cells), 4)

            fraction: float | None = None
            total = totals.get((key, subatlas_label))
            if not degraded and total:
                fraction = round(overlap_cells / total, 4)
                overlap["subatlas_set_total_cells"] = total
                overlap["fraction_of_subatlas_set"] = fraction
                overlap["f1"] = round(_f1(fraction, purity), 4)
            overlap["overlap_shape"] = _shape(fraction, purity, thresholds)
            overlaps.append(overlap)

        for key in {o["subatlas_paper"] for o in overlaps} | set(tail):
            if key in unpublished:
                unpublished[key]["n_atlas_cell_sets"] += 1

        overlaps.sort(
            key=lambda o: (-o.get("f1", o["purity"]), o["subatlas_paper"], o["subatlas_cell_label"])
        )

        entry_out: dict[str, Any] = {
            "cell_label": str(annotation.get("cell_label", "")),
            "labelset": str(annotation.get("labelset", "")),
            "overlaps": overlaps,
        }
        if annotation.get("cell_set_accession"):
            entry_out["cell_set_accession"] = str(annotation["cell_set_accession"])
        if n_cells is not None:
            entry_out["n_cells"] = int(n_cells)
        if annotation.get("synonyms"):
            entry_out["synonyms"] = [str(s) for s in annotation["synonyms"]]
        if tail:
            entry_out["tail"] = sorted(tail.values(), key=lambda t: t["subatlas_paper"])
        cell_sets.append(entry_out)

    out: dict[str, Any] = {
        "cas_source": cas_source,
        "partition": partition,
        "thresholds": thresholds.to_dict(),
        "degraded": degraded,
        "cell_sets": cell_sets,
    }
    source = cas_doc.get("source") or {}
    if source.get("doi"):
        out["atlas_doi"] = str(source["doi"])
    if unpublished:
        out["unpublished"] = sorted(unpublished.values(), key=lambda u: u["subatlas_paper"])
    if not degraded and sensitivity_floors:
        out["sensitivity"] = sensitivity(out, floors=sensitivity_floors)
    return out


def sensitivity(
    scores: Mapping[str, Any], *, floors: Sequence[float] = DEFAULT_SENSITIVITY_FLOORS
) -> list[dict[str, Any]]:
    """Report how the surviving set changes across candidate f1 floors.

    The f1 distribution has no knee, so any floor is a policy choice rather than a
    discovered boundary. Recording the effect makes a later change a diff.
    """
    rows: list[dict[str, Any]] = []
    for floor in floors:
        overlaps = 0
        atlas_sets: set[str] = set()
        subatlas_sets: set[tuple[str, str]] = set()
        papers: set[str] = set()
        for cell_set in scores.get("cell_sets") or []:
            for overlap in cell_set["overlaps"]:
                if overlap.get("f1", 0.0) < floor:
                    continue
                overlaps += 1
                atlas_sets.add(f"{cell_set['labelset']}/{cell_set['cell_label']}")
                subatlas_sets.add((overlap["subatlas_paper"], overlap["subatlas_cell_label"]))
                papers.add(overlap["subatlas_paper"])
        rows.append(
            {
                "f1_floor": floor,
                "n_overlaps": overlaps,
                "n_atlas_cell_sets": len(atlas_sets),
                "n_subatlas_cell_sets": len(subatlas_sets),
                "n_papers": len(papers),
            }
        )
    return rows


def _synonym_index(cell_set: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    return {normalise_label(s): s for s in cell_set.get("synonyms") or []}


def read_plan(
    scores: Mapping[str, Any],
    cas_doc: Mapping[str, Any],
    *,
    thresholds: Thresholds | None = None,
    scores_source: str = "",
) -> dict[str, Any]:
    """Cut the scores down to what to read and what to ask.

    Keyed by study, then by subatlas cell set: one subatlas cell set often spans
    several atlas cell sets, and that is still one question and one read. Conforms
    to ``subatlas_read_plan.schema.json``.
    """
    thresholds = thresholds or Thresholds(**scores.get("thresholds", {}))
    degraded = bool(scores.get("degraded"))
    registry = _registry(cas_doc)
    parents = {
        str(a.get("cell_set_accession")): str(a.get("parent_cell_set_accession"))
        for a in cas_doc.get("annotations") or []
        if a.get("cell_set_accession") and a.get("parent_cell_set_accession")
    }

    # (paper, subatlas cell set) -> question under construction
    questions: dict[tuple[str, str], dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []

    for cell_set in scores.get("cell_sets") or []:
        synonyms = _synonym_index(cell_set)
        kept_here = 0
        for overlap in cell_set["overlaps"]:
            matched_synonym = synonyms.get(normalise_label(overlap["subatlas_cell_label"]))
            if overlap["overlap_cells"] < thresholds.min_overlap_cells and not matched_synonym:
                continue
            if matched_synonym:
                included_by = "synonym"
            elif degraded:
                if overlap["purity"] < thresholds.purity_floor:
                    continue
                included_by = "purity_only"
            else:
                if overlap.get("f1", 0.0) < thresholds.f1_floor:
                    continue
                included_by = "f1"

            kept_here += 1
            key = (overlap["subatlas_paper"], overlap["subatlas_cell_label"])
            question = questions.get(key)
            if question is None:
                question = {
                    "subatlas_cell_label": overlap["subatlas_cell_label"],
                    "included_by": included_by,
                    "atlas_cell_sets": [],
                }
                if overlap.get("source_labelset"):
                    question["source_labelset"] = overlap["source_labelset"]
                if overlap.get("subatlas_set_total_cells"):
                    question["subatlas_set_total_cells"] = overlap["subatlas_set_total_cells"]
                questions[key] = question
            elif included_by == "synonym":
                # An asserted correspondence outranks one that merely cleared f1.
                question["included_by"] = "synonym"

            ref: dict[str, Any] = {
                "cell_label": cell_set["cell_label"],
                "labelset": cell_set["labelset"],
                "overlap_cells": overlap["overlap_cells"],
                "purity": overlap["purity"],
                "overlap_shape": overlap["overlap_shape"],
            }
            if cell_set.get("cell_set_accession"):
                ref["cell_set_accession"] = cell_set["cell_set_accession"]
            if "fraction_of_subatlas_set" in overlap:
                ref["fraction_of_subatlas_set"] = overlap["fraction_of_subatlas_set"]
            if "f1" in overlap:
                ref["f1"] = overlap["f1"]
            if matched_synonym:
                ref["matched_synonym"] = matched_synonym
            question["atlas_cell_sets"].append(ref)

        if not kept_here:
            gaps.append(
                {
                    "kind": "no_surviving_overlap",
                    "detail": "every overlap fell below the cutoff",
                    "cell_label": cell_set["cell_label"],
                    "labelset": cell_set["labelset"],
                }
            )

    # Collapse to the most specific claimants, then record nesting among what is
    # left. Where the CAS+ document has a hierarchy, every ancestor of a genuine
    # claimant also overlaps and clears the cutoff, so the same cells arrive at
    # several granularities and the same question would be asked once per level.
    # The finest claimant is the one that carries the comparison. With flat
    # annotation there are no ancestors and none of this does anything.
    for question in questions.values():
        by_accession = {
            ref["cell_set_accession"]: ref
            for ref in question["atlas_cell_sets"]
            if ref.get("cell_set_accession")
        }
        subsumed: set[str] = set()
        for accession in by_accession:
            ancestor = parents.get(accession)
            while ancestor:
                if ancestor in by_accession:
                    subsumed.add(ancestor)
                ancestor = parents.get(ancestor)
        if subsumed:
            question["n_coarser_dropped"] = len(subsumed)
            question["atlas_cell_sets"] = [
                ref
                for ref in question["atlas_cell_sets"]
                if ref.get("cell_set_accession") not in subsumed
            ]
            by_accession = {k: v for k, v in by_accession.items() if k not in subsumed}

        for accession, ref in by_accession.items():
            ancestor = parents.get(accession)
            while ancestor:
                if ancestor in by_accession:
                    ref["nested_under"] = ancestor
                    break
                ancestor = parents.get(ancestor)
        question["atlas_cell_sets"].sort(key=lambda r: (-r["overlap_cells"], r["cell_label"]))

    papers: dict[str, dict[str, Any]] = {}
    for (paper_key, _label), question in sorted(questions.items()):
        paper = papers.get(paper_key)
        if paper is None:
            entry = registry.get(paper_key)
            paper = {"subatlas_paper": paper_key, "questions": []}
            doi = _doi_of(paper_key, entry)
            if doi:
                paper["doi"] = doi
            if entry and entry.get("status"):
                paper["status"] = str(entry["status"])
            band = ((entry or {}).get("asta_indexing") or {}).get("band")
            if band:
                paper["asta_band"] = str(band)
            papers[paper_key] = paper
        paper["questions"].append(question)

    for record in scores.get("unpublished") or []:
        gaps.append(
            {
                "kind": "no_publication",
                "detail": (
                    f"{record['overlap_cells']} cells across "
                    f"{record['n_atlas_cell_sets']} atlas cell sets, with no DOI to read"
                ),
                "subatlas_paper": record["subatlas_paper"],
            }
        )
    for paper in papers.values():
        if paper.get("status") in {"unresolved", "needs_pdf"}:
            gaps.append(
                {
                    "kind": "unreachable_text",
                    "detail": f"registry status is {paper['status']}",
                    "subatlas_paper": paper["subatlas_paper"],
                }
            )
    if degraded:
        gaps.insert(
            0,
            {
                "kind": "no_partition",
                "detail": (
                    (scores.get("partition") or {}).get("reason", "no usable partition")
                    + "; questions were selected on purity alone and every overlap shape is unknown"
                ),
            },
        )

    out: dict[str, Any] = {
        "cas_source": scores.get("cas_source", ""),
        "scores_source": scores_source,
        "thresholds": {
            "f1_floor": thresholds.f1_floor,
            "min_overlap_cells": thresholds.min_overlap_cells,
            "purity_floor": thresholds.purity_floor,
        },
        "degraded": degraded,
        "papers": sorted(
            papers.values(), key=lambda p: (-len(p["questions"]), p["subatlas_paper"])
        ),
    }
    if scores.get("atlas_doi"):
        out["atlas_doi"] = scores["atlas_doi"]
    if gaps:
        out["gaps"] = gaps
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_subatlas_scores",
        description=(
            "Score atlas cell sets against the cell sets of contributing studies, "
            "and emit a read plan saying which studies to read and what to ask."
        ),
    )
    parser.add_argument("--cas", type=Path, required=True, help="Path to a CAS+ document.")
    parser.add_argument("--scores-out", type=Path, help="Where to write subatlas_scores.json.")
    parser.add_argument("--plan-out", type=Path, help="Where to write subatlas_read_plan.json.")
    parser.add_argument("--f1-floor", type=float, default=DEFAULT_F1_FLOOR)
    parser.add_argument("--min-overlap-cells", type=int, default=DEFAULT_MIN_OVERLAP_CELLS)
    parser.add_argument("--purity-floor", type=float, default=DEFAULT_PURITY_FLOOR)
    parser.add_argument("--record-floor", type=float, default=DEFAULT_RECORD_FLOOR)
    parser.add_argument(
        "--shape-high",
        type=float,
        default=DEFAULT_SHAPE_HIGH,
        help="Above this, a ratio counts as high when reading off overlap_shape.",
    )
    parser.add_argument(
        "--non-paper-label",
        action="append",
        default=[],
        help="A provenance key that is not a study (e.g. whole_embryo). Repeatable.",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Print how the surviving set changes across candidate f1 floors.",
    )
    return parser


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cas_doc = json.loads(args.cas.read_text())
    except FileNotFoundError:
        print(f"no such CAS+ document: {args.cas}")
        return 2

    thresholds = Thresholds(
        f1_floor=args.f1_floor,
        min_overlap_cells=args.min_overlap_cells,
        purity_floor=args.purity_floor,
        record_floor=args.record_floor,
        shape_high=args.shape_high,
    )
    scores = score(
        cas_doc,
        thresholds=thresholds,
        non_paper_labels=args.non_paper_label,
        cas_source=str(args.cas),
    )

    if not scores["cell_sets"]:
        print(
            f"{args.cas}: no annotation carries transferred_annotations, "
            "so there is nothing to score and no subatlas paper to read."
        )
        return 0

    plan = read_plan(
        scores,
        cas_doc,
        thresholds=thresholds,
        scores_source=str(args.scores_out) if args.scores_out else "",
    )

    partition = scores["partition"]
    if scores["degraded"]:
        print(f"DEGRADED: {partition.get('reason')}")
        print("  purity only; fraction_of_subatlas_set and f1 were not computed.")
    else:
        spanned = ", ".join(partition.get("labelsets_spanned") or [])
        print(
            f"partition: {partition['basis']} — {partition['n_cell_sets']} cell sets, "
            f"{partition['total_cells']} cells, spanning {spanned}"
        )
    n_overlaps = sum(len(c["overlaps"]) for c in scores["cell_sets"])
    n_questions = sum(len(p["questions"]) for p in plan["papers"])
    print(f"scored {n_overlaps} overlaps across {len(scores['cell_sets'])} atlas cell sets")
    print(f"read plan: {n_questions} questions across {len(plan['papers'])} papers")
    for gap in plan.get("gaps") or []:
        if gap["kind"] != "no_surviving_overlap":
            print(f"  gap ({gap['kind']}): {gap.get('subatlas_paper', '')} {gap['detail']}")

    if args.sensitivity and scores.get("sensitivity"):
        print("\nf1 floor sensitivity (no knee in the distribution — this is policy):")
        print("  floor   overlaps  atlas sets  subatlas sets  papers")
        for row in scores["sensitivity"]:
            print(
                f"  {row['f1_floor']:<6} {row['n_overlaps']:>8} {row['n_atlas_cell_sets']:>11}"
                f" {row['n_subatlas_cell_sets']:>14} {row['n_papers']:>7}"
            )

    if args.scores_out:
        _write(args.scores_out, scores)
    if args.plan_out:
        _write(args.plan_out, plan)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
