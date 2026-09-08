"""Unit tests for what a reading agent is told about a cell set."""

from __future__ import annotations

import json

import jsonschema
import pytest
from atlas_chat.services.subject_block import (
    SubjectBlockError,
    build_all,
    main,
)

from atlas_chat.schemas import load_schema

pytestmark = pytest.mark.unit


def _cas() -> dict:
    def values(pairs):
        return [{"author_value": v, "cell_ratio": r} for v, r in pairs]

    return {
        "labelsets": [{"name": "fine"}, {"name": "broad"}],
        "annotations": [
            {
                "labelset": "broad",
                "cell_label": "Parent",
                "cell_fullname": "Parent",
                "cell_set_accession": "P",
                "n_cells": 100,
            },
            {
                "labelset": "fine",
                "cell_label": "Subject",
                "cell_fullname": "The subject in full",
                "cell_set_accession": "S",
                "parent_cell_set_accession": "P",
                "n_cells": 60,
                "synonyms": ["Subj"],
                "marker_gene_evidence": ["GENE1"],
                "cell_ontology_term_id": "CL:0000000",
                "composition": {
                    "organ": {
                        "category": "tissue",
                        "values": values([("Kept", 0.9), ("Dropped", 0.001)]),
                    },
                    "region": {
                        "category": "tissue",
                        "values": values([("AlsoKept", 0.5)]),
                    },
                    "stage": {
                        "category": "development_stage",
                        "values": values([("Adult", 1.0)]),
                    },
                    "diagnosis": {
                        "category": "disease",
                        "values": values([("Excluded", 1.0)]),
                    },
                    "untyped": {"values": values([("AlsoExcluded", 1.0)])},
                },
            },
            {
                "labelset": "fine",
                "cell_label": "Child",
                "cell_set_accession": "C",
                "parent_cell_set_accession": "S",
                "n_cells": 20,
            },
        ],
    }


def _subject() -> dict:
    return build_all(_cas(), ["Subject"])[0]


def test_identity_and_relations_are_carried():
    b = _subject()
    assert b["cell_label"] == "Subject"
    assert b["cell_fullname"] == "The subject in full"
    assert b["labelset"] == "fine"
    assert b["n_cells"] == 60
    assert b["synonyms"] == ["Subj"]
    assert b["parent"] == "Parent"
    assert b["children"] == ["Child"]


def test_children_are_present_so_a_subdivision_is_not_taken_for_a_synonym():
    """An alternative name has to denote the same cells; without the children
    that rule cannot be applied to a candidate."""
    assert "Child" in _subject()["children"]


def test_a_fullname_identical_to_the_label_is_not_repeated():
    b = build_all(_cas(), ["Parent"])[0]
    assert "cell_fullname" not in b


def test_context_carries_only_the_named_categories():
    ctx = _subject()["context"]
    assert set(ctx) == {"tissue", "development_stage"}
    assert "disease" not in ctx


def test_an_untyped_descriptor_is_not_context():
    """Absence of a category claims nothing, so it cannot be read as context."""
    flat = json.dumps(_subject())
    assert "AlsoExcluded" not in flat


def test_columns_reporting_the_same_category_are_kept_apart():
    """Different granularities of the same category are different statements."""
    assert _subject()["context"]["tissue"] == {"organ": ["Kept"], "region": ["AlsoKept"]}


def test_values_below_the_floor_are_dropped():
    assert "Dropped" not in json.dumps(_subject())


def test_the_floor_is_the_callers_choice():
    b = build_all(_cas(), ["Subject"], min_ratio=0.0)[0]
    assert b["context"]["tissue"]["organ"] == ["Kept", "Dropped"]


def test_the_categories_are_the_callers_choice():
    b = build_all(_cas(), ["Subject"], categories=("disease",))[0]
    assert set(b["context"]) == {"disease"}


def test_nothing_stating_the_biology_the_reader_must_find_is_included():
    """Supplying markers or an ontology term invites the reader to recognise
    them in the text rather than find them."""
    flat = json.dumps(_subject())
    assert "GENE1" not in flat
    assert "CL:0000000" not in flat


def test_a_cell_set_with_no_context_omits_the_key_rather_than_writing_it_empty():
    assert "context" not in build_all(_cas(), ["Child"])[0]


def test_an_unknown_label_is_an_error_not_a_missing_block():
    """A silently missing subject is a cell type nobody was asked about."""
    with pytest.raises(SubjectBlockError):
        build_all(_cas(), ["Subject", "Nonexistent"])


def test_blocks_come_back_in_the_order_asked_for():
    labels = ["Child", "Subject", "Parent"]
    assert [b["cell_label"] for b in build_all(_cas(), labels)] == labels


def test_all_cell_sets_when_none_are_named():
    assert len(build_all(_cas())) == 3


def test_every_block_validates_against_the_schema():
    schema = load_schema("subject_block.schema.json")
    for block in build_all(_cas()):
        jsonschema.validate(block, schema)


def test_cli_writes_blocks_and_reports_their_size(tmp_path, capsys):
    cas = tmp_path / "cas.json"
    cas.write_text(json.dumps(_cas()), encoding="utf-8")
    out = tmp_path / "blocks.json"
    assert main(["--cas", str(cas), "--label", "Subject", "--out", str(out)]) == 0
    assert json.loads(out.read_text())[0]["cell_label"] == "Subject"
    assert "1 subject blocks" in capsys.readouterr().out


def test_cli_exits_nonzero_on_an_unknown_label(tmp_path, capsys):
    cas = tmp_path / "cas.json"
    cas.write_text(json.dumps(_cas()), encoding="utf-8")
    assert main(["--cas", str(cas), "--label", "Nope"]) == 2
    assert "not in the document" in capsys.readouterr().out
