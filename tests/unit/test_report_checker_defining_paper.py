"""The defining-paper exit condition.

Where subatlas-consistency calls a contributing paper `subatlas_primary`, that
paper is where the cell type was actually characterised — the atlas inherited the
label. Until this check existed, a report could omit it silently, and did: 10 of
11 retinal reports in one run never mentioned the study every one of their cells
came from. Hence a hard failure rather than a warning.
"""

from __future__ import annotations

import json

import pytest
from atlas_chat.validation.report_checker import check_defining_paper, validate_report

pytestmark = pytest.mark.unit

ULRICH = "10.1073/pnas.2404775121"


def _consistency(call="subatlas_primary", doi=ULRICH, paper="celltype_Ulrich2024"):
    primacy = {"call": call, "reason": "..."}
    if paper:
        primacy["primary_paper"] = paper
    if doi:
        primacy["primary_doi"] = doi
    if call == "co_equal":
        primacy["co_equal_papers"] = [paper]
    return {"primacy": primacy}


def _catalogue(*dois):
    return {f"CorpusId:{i}": {"doi": d, "title": "t"} for i, d in enumerate(dois, start=1)}


def test_no_errors_when_the_defining_paper_is_reached_and_cited():
    errors = check_defining_paper(
        _consistency(), _catalogue(ULRICH), f"...see (Ulrich et al., 2024). DOI: {ULRICH}"
    )
    assert errors == []


def test_fails_when_traversal_never_reached_the_defining_paper():
    errors = check_defining_paper(
        _consistency(), _catalogue("10.1/something-else"), f"cited anyway {ULRICH}"
    )
    assert len(errors) == 1
    assert "missing from paper_catalogue.json" in errors[0]
    assert "Seed traversal on it" in errors[0]


def test_fails_when_the_report_does_not_cite_it():
    """Reaching the paper is not the same as using it."""
    errors = check_defining_paper(_consistency(), _catalogue(ULRICH), "a report citing nothing")
    assert len(errors) == 1
    assert "does not appear in the report" in errors[0]


def test_both_failures_are_reported_together():
    errors = check_defining_paper(_consistency(), {}, "nothing here")
    assert len(errors) == 2


def test_fails_when_primacy_names_no_doi_to_check_against():
    errors = check_defining_paper(
        _consistency(doi=None), _catalogue(ULRICH), f"report mentioning {ULRICH}"
    )
    assert len(errors) == 1
    assert "no primary_doi" in errors[0]


@pytest.mark.parametrize("call", ["atlas_primary", "co_equal"])
def test_nothing_to_check_when_the_atlas_is_primary_or_sources_are_co_equal(call):
    """Only a subatlas_primary claim asserts one paper defines the cell type."""
    assert check_defining_paper(_consistency(call=call), {}, "") == []


def test_nothing_to_check_without_a_consistency_file():
    assert check_defining_paper({}, {}, "") == []


def test_doi_matching_is_case_insensitive():
    errors = check_defining_paper(
        {
            "primacy": {
                "call": "subatlas_primary",
                "primary_paper": "P",
                "primary_doi": "10.1/ABC",
                "reason": "r",
            }
        },
        {"CorpusId:1": {"doi": "10.1/abc"}},
        "cited as 10.1/abc",
    )
    assert errors == []


# ---------------------------------------------------------------- wired in


def test_validate_report_applies_the_check(tmp_path):
    traversal = tmp_path / "traversal"
    traversal.mkdir()
    (traversal / "all_summaries.json").write_text("[]")
    (traversal / "paper_catalogue.json").write_text(json.dumps(_catalogue("10.1/atlas")))
    (traversal / "subatlas_consistency.json").write_text(json.dumps(_consistency()))
    report = tmp_path / "report.md"
    report.write_text("# A cell type\n\nNo mention of where it came from.\n")

    passed, errors = validate_report(report, traversal)
    assert not passed
    assert any("celltype_Ulrich2024" in e for e in errors)


def test_validate_report_is_unaffected_when_the_step_has_not_run(tmp_path):
    traversal = tmp_path / "traversal"
    traversal.mkdir()
    (traversal / "all_summaries.json").write_text("[]")
    (traversal / "paper_catalogue.json").write_text("{}")
    report = tmp_path / "report.md"
    report.write_text("# A cell type\n")
    passed, errors = validate_report(report, traversal)
    assert passed, errors


def test_validate_report_tolerates_a_consistency_array(tmp_path):
    """A whole-project pass writes an array; per-cell-type validation ignores it."""
    traversal = tmp_path / "traversal"
    traversal.mkdir()
    (traversal / "all_summaries.json").write_text("[]")
    (traversal / "paper_catalogue.json").write_text("{}")
    (traversal / "subatlas_consistency.json").write_text(json.dumps([_consistency()]))
    report = tmp_path / "report.md"
    report.write_text("# A cell type\n")
    passed, _ = validate_report(report, traversal)
    assert passed
