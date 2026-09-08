"""Unit tests for the shared CAS+ checker and its CLI.

The cross-field rules are the point: they catch documents a JSON Schema calls
valid. Each is asserted to fire on a contradiction and stay silent on a merely
incomplete document, since CAS+ is filled in across passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_chat.cli_cas import main as cli_main
from atlas_chat.validation.cas_checker import (
    cross_field_errors,
    validate_cas_document,
    validate_cas_file,
)


def _doc(**overrides) -> dict:
    base = {
        "labelsets": [{"name": "L1"}],
        "annotations": [
            {
                "labelset": "L1",
                "cell_label": "a",
                "cell_set_accession": "X:1",
                "n_cells": 100,
            }
        ],
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_clean_document_passes() -> None:
    passed, messages = validate_cas_document(_doc())
    assert passed and messages == []


@pytest.mark.unit
def test_schema_violation_fails() -> None:
    passed, messages = validate_cas_document({"labelsets": [], "annotations": [{}]})
    assert not passed
    assert any("labelset" in m for m in messages)


@pytest.mark.unit
def test_undeclared_labelset_is_caught() -> None:
    doc = _doc()
    doc["annotations"][0]["labelset"] = "nope"
    assert any("is not declared" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_dangling_parent_is_caught() -> None:
    doc = _doc()
    doc["annotations"][0]["parent_cell_set_accession"] = "X:missing"
    assert any("matches no cell_set_accession" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_self_parent_is_caught() -> None:
    doc = _doc()
    doc["annotations"][0]["parent_cell_set_accession"] = "X:1"
    assert any("points at itself" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_composition_counts_must_sum_to_n_cells() -> None:
    doc = _doc()
    doc["annotations"][0]["composition"] = {
        "tissue": {"values": [{"author_value": "skin", "cell_count": 60}]}
    }
    assert any("sums to 60" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_composition_without_counts_is_not_flagged() -> None:
    """Incomplete is not wrong — a category with no counts says nothing to contradict."""
    doc = _doc()
    doc["annotations"][0]["composition"] = {"tissue": {"values": [{"author_value": "skin"}]}}
    assert cross_field_errors(doc) == []


@pytest.mark.unit
def test_disagreeing_contribution_denominator_is_caught() -> None:
    """The rule plan_cxg_probe_integration_2026-09.md asks for by name."""
    doc = _doc()
    doc["annotations"][0]["transferred_annotations"] = [
        {"transferred_cell_label": "a", "source_labelset": "s", "subatlas_contribution_cells": 30},
        {"transferred_cell_label": "b", "source_labelset": "s", "subatlas_contribution_cells": 31},
    ]
    assert any("disagrees" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_agreeing_contribution_denominator_is_fine() -> None:
    doc = _doc()
    doc["annotations"][0]["transferred_annotations"] = [
        {"transferred_cell_label": "a", "source_labelset": "s", "subatlas_contribution_cells": 30},
        {"transferred_cell_label": "b", "source_labelset": "s", "subatlas_contribution_cells": 30},
    ]
    assert cross_field_errors(doc) == []


@pytest.mark.unit
def test_transferred_count_cannot_exceed_the_cell_set() -> None:
    doc = _doc()
    doc["annotations"][0]["transferred_annotations"] = [
        {"transferred_cell_label": "a", "cell_count": 101}
    ]
    assert any("exceeds n_cells" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_unregistered_subatlas_paper_is_caught() -> None:
    doc = _doc(source={"subatlas_papers": [{"label": "known"}]})
    doc["annotations"][0]["transferred_annotations"] = [
        {"transferred_cell_label": "a", "subatlas_paper": "unknown"}
    ]
    assert any("not in source.subatlas_papers" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_subatlas_cell_sets_must_sum_to_total_cells() -> None:
    doc = _doc(
        source={
            "subatlas_papers": [
                {
                    "label": "s",
                    "total_cells": 100,
                    "cell_sets": [{"cell_label": "x", "n_cells": 90}],
                }
            ]
        }
    )
    assert any("sums to 90" in m for m in cross_field_errors(doc))


@pytest.mark.unit
def test_warnings_pass_by_default_and_fail_under_strict() -> None:
    doc = _doc()
    doc["annotations"][0]["parent_cell_set_accession"] = "X:missing"
    passed, messages = validate_cas_document(doc)
    assert passed and any(m.startswith("warning:") for m in messages)
    assert validate_cas_document(doc, strict=True)[0] is False


@pytest.mark.unit
def test_missing_and_malformed_files_report_rather_than_raise(tmp_path: Path) -> None:
    assert validate_cas_file(tmp_path / "absent.json")[0] is False
    broken = tmp_path / "cas.json"
    broken.write_text("{not json")
    passed, messages = validate_cas_file(broken)
    assert not passed and any("not valid JSON" in m for m in messages)


@pytest.mark.unit
def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    good = tmp_path / "cas.json"
    good.write_text(json.dumps(_doc()))
    assert cli_main(["validate", "--cas", str(good)]) == 0

    bad = tmp_path / "bad" / "cas.json"
    bad.parent.mkdir()
    bad.write_text(json.dumps({"annotations": [{}]}))
    assert cli_main(["validate", "--cas", str(bad)]) == 1
    assert cli_main(["validate"]) == 2


@pytest.mark.unit
def test_cli_discovers_cas_files(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "cas.json").write_text(json.dumps({"annotations": [{}]}))
    assert cli_main(["validate", "--discover", str(tmp_path), "--quiet"]) == 1


@pytest.mark.unit
def test_committed_test_project_fixtures_validate() -> None:
    """CI gate: every fixture the workflow is developed against must be valid."""
    root = Path(__file__).resolve().parents[2] / "projects" / "test_projects"
    fixtures = sorted(root.rglob("cas.json"))
    assert fixtures, "no test-project CAS+ fixtures found"
    for fixture in fixtures:
        passed, messages = validate_cas_file(fixture)
        assert passed, f"{fixture}: {messages}"
