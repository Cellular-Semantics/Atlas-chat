"""Unit tests for atlas/subatlas cell set overlap scoring.

The fixtures below are deliberately small and hand-checkable. The one large
regression — the reference project's ``aPCV`` case — lives at the end and pins the
behaviour the whole design turns on: an overlap the atlas authors asserted, which
no overlap statistic can see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from atlas_chat.services.subatlas_scoring import (
    Thresholds,
    find_partition,
    main,
    normalise_label,
    read_plan,
    score,
    sensitivity,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "src/atlas_chat/atlas_chat/schemas"
HCA_CAS = REPO_ROOT / "projects/test_projects/hca_reproductive/cas.json"
HDCA_CAS = REPO_ROOT / "projects/test_projects/hdca_neurons/cas.json"
FETAL_CAS = REPO_ROOT / "projects/test_projects/fetal_skin_atlas/cas.json"


def _validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / name).read_text())
    scores = json.loads((SCHEMA_DIR / "subatlas_scores.schema.json").read_text())
    from referencing import Registry, Resource

    registry = Registry().with_resource(
        scores.get("$id", "subatlas_scores.schema.json"), Resource.from_contents(scores)
    )
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _transfer(paper: str, label: str, cells: int) -> dict[str, Any]:
    return {
        "transferred_cell_label": label,
        "subatlas_paper": paper,
        "cell_count": cells,
    }


def _cas(annotations: list[dict[str, Any]], **source: Any) -> dict[str, Any]:
    return {
        "title": "Test atlas",
        "source": {"doi": "10.1000/test", **source},
        "labelsets": sorted(
            ({"name": a["labelset"]} for a in annotations),
            key=lambda ls: ls["name"],
        ),
        "annotations": annotations,
    }


# --------------------------------------------------------------------------
# normalise_label
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("ePV2", "ePV_2"),
        ("TIP", "Tip"),
        ("Endo_cycling", "Endo_Cycling"),
        ("blood vessel endothelial", "blood-vessel-endothelial"),
        ("  PCV ", "pcv"),
    ],
)
def test_separators_and_case_are_noise(a: str, b: str) -> None:
    assert normalise_label(a) == normalise_label(b)


def test_a_trailing_marker_sign_is_not_noise() -> None:
    """The failure this rule exists for: opposite marker states must not merge.

    Stripping punctuation collapses these two into one string, which on the
    reference project matched the synonym for the CDKN1A-positive cell set against
    the negative one, six times over.
    """
    assert normalise_label("PV-MYH11_CDKN1A+") != normalise_label("PV-MYH11_CDKN1A-")
    assert normalise_label("PV-MYH11_CDKN1A+") == normalise_label("pv myh11 cdkn1a+")


# --------------------------------------------------------------------------
# find_partition
# --------------------------------------------------------------------------


def test_hierarchy_leaves_are_preferred_and_may_span_labelsets() -> None:
    cas = _cas(
        [
            {"labelset": "L1", "cell_label": "Root", "cell_set_accession": "A", "n_cells": 100},
            {
                "labelset": "L2",
                "cell_label": "Left",
                "cell_set_accession": "B",
                "parent_cell_set_accession": "A",
                "n_cells": 60,
            },
            {
                "labelset": "L2",
                "cell_label": "Right",
                "cell_set_accession": "C",
                "parent_cell_set_accession": "A",
                "n_cells": 40,
            },
        ]
    )
    partition = find_partition(cas)
    assert partition["basis"] == "hierarchy_leaves"
    assert partition["n_cell_sets"] == 2
    assert partition["total_cells"] == 100


def test_a_flat_single_labelset_is_used_directly() -> None:
    cas = _cas(
        [
            {"labelset": "celltype", "cell_label": "A", "n_cells": 10},
            {"labelset": "celltype", "cell_label": "B", "n_cells": 20},
        ]
    )
    partition = find_partition(cas)
    assert partition["basis"] == "labelset"
    assert partition["labelset"] == "celltype"
    assert partition["total_cells"] == 30


def test_disagreeing_labelsets_with_no_hierarchy_are_refused() -> None:
    """Never pick the bigger one: neither can be shown to cover the atlas."""
    cas = _cas(
        [
            {"labelset": "broad", "cell_label": "A", "n_cells": 10},
            {"labelset": "fine", "cell_label": "B", "n_cells": 90},
            {"labelset": "fine", "cell_label": "C", "n_cells": 10},
        ]
    )
    partition = find_partition(cas)
    assert partition["basis"] == "none"
    assert "disagree" in partition["reason"]


def test_missing_n_cells_is_refused() -> None:
    cas = _cas(
        [
            {"labelset": "L1", "cell_label": "Root", "cell_set_accession": "A"},
            {
                "labelset": "L2",
                "cell_label": "Leaf",
                "cell_set_accession": "B",
                "parent_cell_set_accession": "A",
            },
        ]
    )
    partition = find_partition(cas)
    assert partition["basis"] == "none"
    assert "n_cells" in partition["reason"]


def test_real_projects_take_all_three_partition_branches() -> None:
    assert find_partition(json.loads(HCA_CAS.read_text()))["basis"] == "hierarchy_leaves"
    hdca = find_partition(json.loads(HDCA_CAS.read_text()))
    assert hdca["basis"] == "none" and "disagree" in hdca["reason"]
    fetal = find_partition(json.loads(FETAL_CAS.read_text()))
    assert fetal["basis"] == "none" and "n_cells" in fetal["reason"]


# --------------------------------------------------------------------------
# the three ratios
# --------------------------------------------------------------------------


@pytest.fixture
def worked_example() -> dict[str, Any]:
    """The plan's worked example, as a CAS+ document.

    The atlas integrates subatlas cell set ``fu``; 500 of its cells reach the
    atlas, 120 of them into atlas cell set ``bar``. ``bar`` holds 4,000 cells, 150
    of which came from that study.
    """
    return _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "cell_set_accession": "bar",
                "n_cells": 4000,
                "transferred_annotations": [
                    _transfer("X", "fu", 120),
                    _transfer("X", "other", 30),
                ],
            },
            {
                "labelset": "fine",
                "cell_label": "elsewhere",
                "cell_set_accession": "elsewhere",
                "n_cells": 5000,
                "transferred_annotations": [_transfer("X", "fu", 380)],
            },
        ]
    )


def test_the_three_ratios_use_three_different_denominators(
    worked_example: dict[str, Any],
) -> None:
    scores = score(worked_example, thresholds=Thresholds(record_floor=0.0))
    bar = next(c for c in scores["cell_sets"] if c["cell_label"] == "bar")
    fu = next(o for o in bar["overlaps"] if o["subatlas_cell_label"] == "fu")

    assert fu["overlap_cells"] == 120
    # purity: of what X contributed to bar (150), the fraction that is fu
    assert fu["subatlas_contribution_cells"] == 150
    assert fu["purity"] == pytest.approx(0.8)
    # fraction_of_subatlas_set: of fu atlas-wide (500), the fraction that came here
    assert fu["subatlas_set_total_cells"] == 500
    assert fu["fraction_of_subatlas_set"] == pytest.approx(0.24)
    # fraction_of_atlas_set: of bar (4000) — recorded, never gated
    assert fu["fraction_of_atlas_set"] == pytest.approx(0.03)
    assert fu["f1"] == pytest.approx(2 * 0.8 * 0.24 / (0.8 + 0.24), abs=1e-4)


def test_purity_is_not_measured_against_the_atlas_cell_set(
    worked_example: dict[str, Any],
) -> None:
    """A study is not marked down for cells it never sequenced."""
    scores = score(worked_example, thresholds=Thresholds(record_floor=0.0))
    bar = next(c for c in scores["cell_sets"] if c["cell_label"] == "bar")
    fu = next(o for o in bar["overlaps"] if o["subatlas_cell_label"] == "fu")
    assert fu["purity"] != pytest.approx(120 / 4000)


@pytest.mark.parametrize(
    ("here", "elsewhere", "other_from_same_study", "expected"),
    [
        (90, 10, 5, "one_to_one"),
        (10, 90, 0, "atlas_set_within_subatlas_set"),
        (95, 5, 900, "subatlas_set_within_atlas_set"),
        (30, 70, 70, "weak"),
    ],
)
def test_overlap_shape_reads_off_the_two_ratios(
    here: int, elsewhere: int, other_from_same_study: int, expected: str
) -> None:
    transfers = [_transfer("X", "fu", here)]
    if other_from_same_study:
        transfers.append(_transfer("X", "other", other_from_same_study))
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "n_cells": 10_000,
                "transferred_annotations": transfers,
            },
            {
                "labelset": "fine",
                "cell_label": "elsewhere",
                "n_cells": 10_000,
                "transferred_annotations": [_transfer("X", "fu", elsewhere)],
            },
        ]
    )
    scores = score(cas, thresholds=Thresholds(record_floor=0.0))
    bar = next(c for c in scores["cell_sets"] if c["cell_label"] == "bar")
    fu = next(o for o in bar["overlaps"] if o["subatlas_cell_label"] == "fu")
    assert fu["overlap_shape"] == expected


def test_shape_high_is_separate_from_the_inclusion_floor() -> None:
    """0.39 purity against 0.29 of the subatlas cell set is not one-to-one.

    Reusing ``f1_floor`` (0.2) as the shape cutoff said it was.
    """
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "n_cells": 10_000,
                "transferred_annotations": [
                    _transfer("X", "fu", 390),
                    _transfer("X", "other", 610),
                ],
            },
            {
                "labelset": "fine",
                "cell_label": "elsewhere",
                "n_cells": 10_000,
                "transferred_annotations": [_transfer("X", "fu", 943)],
            },
        ]
    )
    scores = score(cas, thresholds=Thresholds(record_floor=0.0))
    bar = next(c for c in scores["cell_sets"] if c["cell_label"] == "bar")
    fu = next(o for o in bar["overlaps"] if o["subatlas_cell_label"] == "fu")
    assert fu["purity"] == pytest.approx(0.39)
    assert fu["fraction_of_subatlas_set"] == pytest.approx(0.2926, abs=1e-3)
    assert fu["overlap_shape"] == "weak"


# --------------------------------------------------------------------------
# degraded runs
# --------------------------------------------------------------------------


@pytest.fixture
def no_partition_cas() -> dict[str, Any]:
    return _cas(
        [
            {
                "labelset": "broad",
                "cell_label": "big",
                "n_cells": 10,
                "transferred_annotations": [
                    _transfer("X", "fu", 8),
                    _transfer("X", "other", 2),
                ],
            },
            {
                "labelset": "fine",
                "cell_label": "small",
                "n_cells": 90,
                "transferred_annotations": [_transfer("X", "fu", 50)],
            },
            {"labelset": "fine", "cell_label": "tiny", "n_cells": 10},
        ]
    )


def test_a_degraded_run_keeps_purity_and_omits_the_rest(
    no_partition_cas: dict[str, Any],
) -> None:
    scores = score(no_partition_cas, thresholds=Thresholds(record_floor=0.0))
    assert scores["degraded"] is True
    assert scores["partition"]["basis"] == "none"
    big = next(c for c in scores["cell_sets"] if c["cell_label"] == "big")
    fu = next(o for o in big["overlaps"] if o["subatlas_cell_label"] == "fu")
    assert fu["purity"] == pytest.approx(0.8)
    assert "fraction_of_subatlas_set" not in fu
    assert "f1" not in fu
    assert fu["overlap_shape"] == "unknown"


def test_a_degraded_plan_gates_on_purity_and_says_why(
    no_partition_cas: dict[str, Any],
) -> None:
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1, purity_floor=0.5)
    scores = score(no_partition_cas, thresholds=thresholds)
    plan = read_plan(scores, no_partition_cas, thresholds=thresholds)
    assert plan["degraded"] is True
    kinds = {gap["kind"] for gap in plan["gaps"]}
    assert "no_partition" in kinds
    questions = [q for p in plan["papers"] for q in p["questions"]]
    assert questions and all(q["included_by"] == "purity_only" for q in questions)
    # 'other' is 0.2 pure and must not survive the purity floor
    assert {q["subatlas_cell_label"] for q in questions} == {"fu"}


# --------------------------------------------------------------------------
# synonym force-inclusion
# --------------------------------------------------------------------------


@pytest.fixture
def synonym_cas() -> dict[str, Any]:
    """An atlas cell set naming a subatlas cell set that scores far too low to survive."""
    return _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "named",
                "cell_set_accession": "named",
                "n_cells": 5000,
                "synonyms": ["ePV_2"],
                "transferred_annotations": [
                    _transfer("X", "ePV2", 30),
                    _transfer("X", "bulk", 970),
                ],
            },
            {
                "labelset": "fine",
                "cell_label": "elsewhere",
                "cell_set_accession": "elsewhere",
                "n_cells": 5000,
                "transferred_annotations": [_transfer("X", "ePV2", 2000)],
            },
        ]
    )


def test_a_synonym_force_includes_an_overlap_f1_would_discard(
    synonym_cas: dict[str, Any],
) -> None:
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=25)
    scores = score(synonym_cas, thresholds=thresholds)
    named = next(c for c in scores["cell_sets"] if c["cell_label"] == "named")
    epv = next(o for o in named["overlaps"] if o["subatlas_cell_label"] == "ePV2")
    assert epv["f1"] < thresholds.f1_floor

    plan = read_plan(scores, synonym_cas, thresholds=thresholds)
    question = next(
        q for p in plan["papers"] for q in p["questions"] if q["subatlas_cell_label"] == "ePV2"
    )
    assert question["included_by"] == "synonym"
    ref = next(r for r in question["atlas_cell_sets"] if r["cell_label"] == "named")
    assert ref["matched_synonym"] == "ePV_2"


def test_a_synonym_naming_a_cell_set_with_no_overlap_does_nothing() -> None:
    """Matching must be scoped to this atlas cell set's own provenance.

    Unscoped, the reference project produced two pairs whose intersection was empty.
    """
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "claimant",
                "n_cells": 100,
                "synonyms": ["OSE"],
                "transferred_annotations": [_transfer("X", "something else", 100)],
            },
            {
                "labelset": "fine",
                "cell_label": "holder",
                "n_cells": 100,
                "transferred_annotations": [_transfer("Y", "OSE", 100)],
            },
        ]
    )
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    plan = read_plan(score(cas, thresholds=thresholds), cas, thresholds=thresholds)
    claimant_questions = [
        q
        for p in plan["papers"]
        for q in p["questions"]
        if any(r["cell_label"] == "claimant" for r in q["atlas_cell_sets"])
    ]
    assert all(q["included_by"] != "synonym" for q in claimant_questions)


def test_a_synonym_does_not_cross_a_marker_sign() -> None:
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "positive set",
                "n_cells": 1000,
                "synonyms": ["PV-MYH11_CDKN1A+"],
                "transferred_annotations": [_transfer("X", "PV-MYH11_CDKN1A-", 900)],
            }
        ]
    )
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    plan = read_plan(score(cas, thresholds=thresholds), cas, thresholds=thresholds)
    refs = [r for p in plan["papers"] for q in p["questions"] for r in q["atlas_cell_sets"]]
    assert not any(r.get("matched_synonym") for r in refs)


# --------------------------------------------------------------------------
# read plan shape
# --------------------------------------------------------------------------


@pytest.fixture
def split_cas() -> dict[str, Any]:
    """One subatlas cell set split across two atlas cell sets, under a common parent."""
    return _cas(
        [
            {
                "labelset": "L1",
                "cell_label": "parent",
                "cell_set_accession": "P",
                "n_cells": 2000,
                "transferred_annotations": [_transfer("X", "fu", 1000)],
            },
            {
                "labelset": "L2",
                "cell_label": "child a",
                "cell_set_accession": "A",
                "parent_cell_set_accession": "P",
                "n_cells": 1000,
                "transferred_annotations": [_transfer("X", "fu", 600)],
            },
            {
                "labelset": "L2",
                "cell_label": "child b",
                "cell_set_accession": "B",
                "parent_cell_set_accession": "P",
                "n_cells": 1000,
                "transferred_annotations": [_transfer("X", "fu", 400)],
            },
        ]
    )


def test_one_subatlas_cell_set_is_one_question_however_many_atlas_sets_it_spans(
    split_cas: dict[str, Any],
) -> None:
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    plan = read_plan(score(split_cas, thresholds=thresholds), split_cas, thresholds=thresholds)
    questions = [q for p in plan["papers"] for q in p["questions"]]
    assert len(questions) == 1
    assert {r["cell_label"] for r in questions[0]["atlas_cell_sets"]} == {"child a", "child b"}


def test_coarser_claimants_are_dropped_when_a_finer_one_is_present(
    split_cas: dict[str, Any],
) -> None:
    """Every ancestor of a genuine claimant also overlaps; asking once per level is waste."""
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    plan = read_plan(score(split_cas, thresholds=thresholds), split_cas, thresholds=thresholds)
    question = plan["papers"][0]["questions"][0]
    assert question["n_coarser_dropped"] == 1
    assert "parent" not in {r["cell_label"] for r in question["atlas_cell_sets"]}


def test_flat_annotation_lists_co_claimants_and_records_no_nesting() -> None:
    """Nothing in the design needs a hierarchy — the split is still reported."""
    cas = _cas(
        [
            {
                "labelset": "celltype",
                "cell_label": "a",
                "n_cells": 1000,
                "transferred_annotations": [_transfer("X", "fu", 600)],
            },
            {
                "labelset": "celltype",
                "cell_label": "b",
                "n_cells": 1000,
                "transferred_annotations": [_transfer("X", "fu", 400)],
            },
        ]
    )
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    plan = read_plan(score(cas, thresholds=thresholds), cas, thresholds=thresholds)
    question = plan["papers"][0]["questions"][0]
    assert len(question["atlas_cell_sets"]) == 2
    assert "n_coarser_dropped" not in question
    assert all("nested_under" not in r for r in question["atlas_cell_sets"])


def test_a_study_with_no_doi_is_a_named_gap() -> None:
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "n_cells": 100,
                "transferred_annotations": [_transfer("UnpublishedStudy", "fu", 100)],
            }
        ],
        subatlas_papers=[{"label": "UnpublishedStudy", "status": "unresolved"}],
    )
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=1)
    scores = score(cas, thresholds=thresholds)
    assert scores["unpublished"][0]["subatlas_paper"] == "UnpublishedStudy"
    plan = read_plan(scores, cas, thresholds=thresholds)
    assert {gap["kind"] for gap in plan["gaps"]} >= {"no_publication", "unreachable_text"}


def test_an_atlas_cell_set_losing_every_overlap_is_reported_not_dropped() -> None:
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "thin",
                "n_cells": 10_000,
                "transferred_annotations": [_transfer("X", "fu", 3)],
            }
        ]
    )
    thresholds = Thresholds(record_floor=0.0, min_overlap_cells=25)
    plan = read_plan(score(cas, thresholds=thresholds), cas, thresholds=thresholds)
    assert any(
        gap["kind"] == "no_surviving_overlap" and gap["cell_label"] == "thin"
        for gap in plan["gaps"]
    )


def test_a_project_with_no_provenance_scores_nothing() -> None:
    cas = _cas([{"labelset": "fine", "cell_label": "a", "n_cells": 10}])
    assert score(cas)["cell_sets"] == []


def test_the_tail_names_the_studies_it_aggregated() -> None:
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "n_cells": 10_000,
                "transferred_annotations": [
                    _transfer("X", "big", 9990),
                    _transfer("X", "speck", 10),
                ],
            }
        ]
    )
    scores = score(cas, thresholds=Thresholds(record_floor=0.02))
    bar = scores["cell_sets"][0]
    assert {o["subatlas_cell_label"] for o in bar["overlaps"]} == {"big"}
    assert bar["tail"] == [{"subatlas_paper": "X", "n_subatlas_cell_sets": 1, "overlap_cells": 10}]


def test_non_paper_labels_are_excluded() -> None:
    cas = _cas(
        [
            {
                "labelset": "fine",
                "cell_label": "bar",
                "n_cells": 100,
                "transferred_annotations": [
                    _transfer("whole_embryo", "unassigned", 60),
                    _transfer("X", "fu", 40),
                ],
            }
        ]
    )
    scores = score(cas, thresholds=Thresholds(record_floor=0.0), non_paper_labels=["whole_embryo"])
    papers = {o["subatlas_paper"] for c in scores["cell_sets"] for o in c["overlaps"]}
    assert papers == {"X"}


def test_sensitivity_is_monotonic() -> None:
    scores = score(json.loads(HCA_CAS.read_text()))
    counts = [row["n_overlaps"] for row in scores["sensitivity"]]
    assert counts == sorted(counts, reverse=True)
    assert sensitivity(scores, floors=(0.0,))[0]["n_overlaps"] >= counts[0]


# --------------------------------------------------------------------------
# schema conformance and the reference regression
# --------------------------------------------------------------------------


def test_real_output_conforms_to_both_schemas() -> None:
    cas = json.loads(HCA_CAS.read_text())
    scores = score(cas, cas_source=str(HCA_CAS))
    plan = read_plan(scores, cas, scores_source="subatlas_scores.json")
    _validator("subatlas_scores.schema.json").validate(scores)
    _validator("subatlas_read_plan.schema.json").validate(plan)


def test_the_reference_partition_reproduces_the_documented_numbers() -> None:
    partition = find_partition(json.loads(HCA_CAS.read_text()))
    assert partition["basis"] == "hierarchy_leaves"
    assert partition["n_cell_sets"] == 210
    assert partition["total_cells"] == 2_235_448
    assert partition["labelsets_spanned"] == ["L2", "L3", "L4"]


def test_the_apcv_case_is_excluded_by_f1_and_included_by_synonym() -> None:
    """The case the synonym rule exists for.

    The atlas cell set ``Activated post-capillary venous endothelial`` lists
    ``aPCV`` — Ulrich 2024's name for one of its own cell sets — among its CAS+
    synonyms. On the numbers alone that overlap is 37 cells at f1 0.027, ranking
    near the bottom, while a study that called everything ``endothelial cell``
    ranks top. No overlap statistic can recover an asserted correspondence.
    """
    cas = json.loads(HCA_CAS.read_text())
    scores = score(cas)
    cell_set = next(
        c
        for c in scores["cell_sets"]
        if c["cell_label"] == "Activated post-capillary venous endothelial"
        and c["labelset"] == "L4"
    )
    assert cell_set["n_cells"] == 4851
    assert "aPCV" in cell_set["synonyms"]

    apcv = next(
        o
        for o in cell_set["overlaps"]
        if o["subatlas_paper"] == "celltype_Ulrich2024" and o["subatlas_cell_label"] == "aPCV"
    )
    assert apcv["overlap_cells"] == 37
    assert apcv["subatlas_set_total_cells"] == 2402
    assert apcv["purity"] == pytest.approx(0.1114, abs=1e-3)
    assert apcv["fraction_of_subatlas_set"] == pytest.approx(0.0154, abs=1e-3)
    assert apcv["f1"] == pytest.approx(0.0271, abs=1e-3)
    assert apcv["f1"] < Thresholds().f1_floor

    plan = read_plan(scores, cas)
    question = next(
        q
        for p in plan["papers"]
        if p["subatlas_paper"] == "celltype_Ulrich2024"
        for q in p["questions"]
        if q["subatlas_cell_label"] == "aPCV"
    )
    assert question["included_by"] == "synonym"
    ref = next(
        r
        for r in question["atlas_cell_sets"]
        if r["cell_label"] == "Activated post-capillary venous endothelial"
    )
    assert ref["matched_synonym"] == "aPCV"


def test_the_reference_project_produces_no_marker_sign_crossings() -> None:
    cas = json.loads(HCA_CAS.read_text())
    plan = read_plan(score(cas), cas)
    crossings = [
        (q["subatlas_cell_label"], r["matched_synonym"])
        for p in plan["papers"]
        for q in p["questions"]
        for r in q["atlas_cell_sets"]
        if r.get("matched_synonym")
        and r["matched_synonym"][-1:] in "+-"
        and q["subatlas_cell_label"][-1:] in "+-"
        and r["matched_synonym"][-1] != q["subatlas_cell_label"][-1]
    ]
    assert crossings == []


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_writes_both_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scores_out = tmp_path / "subatlas_scores.json"
    plan_out = tmp_path / "subatlas_read_plan.json"
    code = main(
        [
            "--cas",
            str(HCA_CAS),
            "--scores-out",
            str(scores_out),
            "--plan-out",
            str(plan_out),
            "--sensitivity",
        ]
    )
    assert code == 0
    assert "hierarchy_leaves" in capsys.readouterr().out
    _validator("subatlas_scores.schema.json").validate(json.loads(scores_out.read_text()))
    _validator("subatlas_read_plan.schema.json").validate(json.loads(plan_out.read_text()))


def test_cli_says_nothing_to_do_for_a_project_with_no_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "subatlas_scores.json"
    code = main(["--cas", str(FETAL_CAS), "--scores-out", str(out)])
    assert code == 0
    assert "nothing to score" in capsys.readouterr().out
    assert not out.exists()


def test_cli_reports_a_missing_cas_document(tmp_path: Path) -> None:
    assert main(["--cas", str(tmp_path / "absent.json")]) == 2
