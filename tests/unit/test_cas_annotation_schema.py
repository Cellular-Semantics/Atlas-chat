"""Schema regression for the CAS+ cell-annotation collection.

Pins cas_annotation.schema.json: well-formedness, the minimal valid document
(the floor for the "simple list + paper" starting point), the local extensions
(nullable parent, transferred-annotation subatlas_paper/source_labelset), and the
additionalProperties teeth on the root / Labelset / DataProvenance objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from atlas_chat.schemas import load_schema

FIXTURES = Path(__file__).parent / "fixtures" / "cas"
SCHEMA = "cas_annotation.schema.json"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def _errors(data: object) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(SCHEMA))
    return [e.message for e in validator.iter_errors(data)]


@pytest.mark.unit
def test_schema_is_well_formed() -> None:
    jsonschema.Draft202012Validator.check_schema(load_schema(SCHEMA))


@pytest.mark.unit
def test_minimal_document_validates() -> None:
    # The floor for a "simple list of annotations + a paper" starting point.
    assert _errors(_load("cas_annotation.minimal.good.json")) == []


@pytest.mark.unit
def test_rich_document_validates() -> None:
    assert _errors(_load("cas_annotation.good.json")) == []


@pytest.mark.unit
def test_annotation_requires_cell_label() -> None:
    assert _errors(_load("cas_annotation.bad.json"))


@pytest.mark.unit
def test_parent_cell_set_accession_is_nullable() -> None:
    data = _load("cas_annotation.good.json")
    assert data["annotations"][0]["parent_cell_set_accession"] is None
    assert _errors(data) == []


@pytest.mark.unit
def test_transferred_annotation_carries_subatlas_and_source_labelset() -> None:
    data = _load("cas_annotation.good.json")
    ta = data["annotations"][0]["transferred_annotations"][0]
    assert ta["subatlas_paper"] == "Smith2021"
    assert ta["source_labelset"] == "celltype_Smith2021"
    assert _errors(data) == []


@pytest.mark.unit
def test_root_additional_properties_are_closed() -> None:
    data = _load("cas_annotation.minimal.good.json")
    data["bogus_top_level"] = 1
    assert _errors(data)


@pytest.mark.unit
def test_annotation_additional_properties_are_closed() -> None:
    data = _load("cas_annotation.minimal.good.json")
    data["annotations"][0]["bogus_field"] = 1
    assert _errors(data)


@pytest.mark.unit
def test_labelset_additional_properties_are_closed() -> None:
    data = _load("cas_annotation.minimal.good.json")
    data["labelsets"][0]["bogus_field"] = 1
    assert _errors(data)


# --------------------------------------------------------------------------
# ASTA indexing band (#22)
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_subatlas_papers_carry_the_asta_indexing_band() -> None:
    """Band and ingest route are separate axes and both round-trip."""
    papers = _load("cas_annotation.good.json")["source"]["subatlas_papers"]
    served, built = papers[0], papers[1]

    assert served["status"] == "asta"
    assert served["asta_indexing"]["band"] == "full"

    # The point of keeping the two fields apart: ASTA holds only this paper's
    # abstract, yet its text is available locally because the JATS build worked.
    assert built["status"] == "local"
    assert built["source_type"] == "jats"
    assert built["asta_indexing"]["band"] == "abstract_only"

    assert _errors(_load("cas_annotation.good.json")) == []


@pytest.mark.unit
@pytest.mark.parametrize("band", ["full", "partial", "abstract_only", "unindexed", "not_in_s2"])
def test_every_band_value_is_accepted(band: str) -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["asta_indexing"]["band"] = band
    assert _errors(data) == []


@pytest.mark.unit
def test_unknown_band_is_rejected() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["asta_indexing"]["band"] = "FULL"
    assert _errors(data)


@pytest.mark.unit
def test_asta_indexing_requires_a_band() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["asta_indexing"] = {"snippets": 30}
    assert _errors(data)


@pytest.mark.unit
def test_asta_indexing_additional_properties_are_closed() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["asta_indexing"]["bogus_field"] = 1
    assert _errors(data)


@pytest.mark.unit
def test_asta_indexing_counts_cannot_be_negative() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["asta_indexing"]["snippets"] = -1
    assert _errors(data)


@pytest.mark.unit
def test_source_type_is_constrained() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][1]["source_type"] = "docx"
    assert _errors(data)


# --- the descriptions are the specification --------------------------------


def _walk_properties(node: object, path: str) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    if not isinstance(node, dict):
        return found
    for name, subschema in (node.get("properties") or {}).items():
        found.append((f"{path}.{name}", subschema))
        found.extend(_walk_properties(subschema, f"{path}.{name}"))
    if "items" in node:
        found.extend(_walk_properties(node["items"], f"{path}[]"))
    return found


def _all_properties() -> list[tuple[str, dict]]:
    schema = load_schema(SCHEMA)
    found = _walk_properties(schema, "(root)")
    for name, definition in (schema.get("$defs") or {}).items():
        found.extend(_walk_properties(definition, name))
    return found


@pytest.mark.unit
def test_every_field_has_a_description() -> None:
    """An agent populates this document from the schema, so an undescribed
    field is an unpopulatable one. Adding a field means describing it."""
    bare = [p for p, s in _all_properties() if not (s.get("description") or "").strip()]
    assert bare == []


# --- assembled from a dataset ----------------------------------------------


@pytest.mark.unit
def test_document_without_paper_provenance_validates() -> None:
    """A document assembled from a dataset does not yet know its paper.
    Completeness is checked where a field is used, not where it is written."""
    assert (
        _errors(
            {
                "labelsets": [{"name": "celltype"}],
                "annotations": [{"labelset": "celltype", "cell_label": "AC"}],
            }
        )
        == []
    )


@pytest.mark.unit
def test_data_provenance_records_several_sources() -> None:
    data = _load("cas_annotation.minimal.good.json")
    data["data_provenance"] = {
        "source_type": "h5ad + supplementary table",
        "sources": ["atlas.h5ad", "media-2.xlsx"],
        "n_cells_total": 4212,
        "script_path": "projects/x/ingest/extract.py",
    }
    assert _errors(data) == []


@pytest.mark.unit
def test_source_type_is_free_text() -> None:
    """Sources include R frames, mtx directories and combinations; a closed
    list would be wrong for the next atlas."""
    data = _load("cas_annotation.minimal.good.json")
    data["data_provenance"] = {"source_type": "seurat rds via SeuratDisk"}
    assert _errors(data) == []


@pytest.mark.unit
def test_data_provenance_rejects_unknown_fields() -> None:
    data = _load("cas_annotation.minimal.good.json")
    data["data_provenance"] = {"source_type": "local_h5ad", "obs_column": "celltype"}
    assert _errors(data) != []


# --- the subatlas denominators ---------------------------------------------


@pytest.mark.unit
def test_subatlas_paper_carries_its_cell_sets() -> None:
    """The denominator for fraction_of_subatlas_set: each contributing cell
    set's size across the whole atlas, stated once per study."""
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["cell_sets"] = [
        {"source_labelset": "celltype_Smith2021", "cell_label": "AC", "n_cells": 412},
        {"source_labelset": "celltype_Smith2021", "cell_label": "imGlia", "n_cells": 96},
    ]
    assert _errors(data) == []


@pytest.mark.unit
def test_transferred_annotation_carries_the_contribution() -> None:
    """The denominator for purity: the study's whole contribution to this
    cell set, whatever it called the cells."""
    data = _load("cas_annotation.good.json")
    data["annotations"][0]["transferred_annotations"][0]["subatlas_contribution_cells"] = 78
    assert _errors(data) == []


@pytest.mark.unit
@pytest.mark.parametrize("value", [-1, 1.5, "78"])
def test_contribution_must_be_a_non_negative_integer(value: object) -> None:
    data = _load("cas_annotation.good.json")
    data["annotations"][0]["transferred_annotations"][0]["subatlas_contribution_cells"] = value
    assert _errors(data) != []


@pytest.mark.unit
def test_subatlas_cell_set_requires_a_label_and_a_count() -> None:
    data = _load("cas_annotation.good.json")
    data["source"]["subatlas_papers"][0]["cell_sets"] = [{"source_labelset": "celltype"}]
    assert _errors(data) != []


@pytest.mark.unit
def test_atlas_paper_without_a_doi_validates() -> None:
    """A pre-submission manuscript has no DOI. What matters downstream is that
    the paper can be cited or read, which a title and a local text satisfy —
    and that is checked where the paper is used, not where it is written."""
    data = _load("cas_annotation.minimal.good.json")
    data["source"] = {
        "title": "A cell atlas of the human female reproductive system",
        "authors": ["Anon A"],
        "local_text_path": "projects/x/papers/manuscript.md",
    }
    assert _errors(data) == []


@pytest.mark.unit
def test_atlas_paper_with_only_a_doi_validates() -> None:
    """The other order: the curator supplies an identifier and the rest is
    resolved in a later pass."""
    data = _load("cas_annotation.minimal.good.json")
    data["source"] = {"doi": "10.1038/s41586-024-08002-x"}
    assert _errors(data) == []


# --- what kind of descriptor a composition entry holds ----------------------


def _with_composition(composition: dict) -> object:
    data = _load("cas_annotation.minimal.good.json")
    data["annotations"][0]["composition"] = composition
    return data


CATEGORIES = [
    "tissue",
    "development_stage",
    "disease",
    "assay",
    "organism",
    "sex",
    "self_reported_ethnicity",
    "tissue_type",
    "suspension_type",
    "cross_cutting_cell_type",
    "unclassified",
]


def _category_branches() -> list[dict]:
    return load_schema(SCHEMA)["$defs"]["CompositionCategory"]["properties"]["category"]["oneOf"]


@pytest.mark.unit
def test_the_category_values_are_the_ones_expected() -> None:
    """Spelled out here as well as in the schema: adding or renaming a category
    is a contract change and should have to be made in two places."""
    assert [b["const"] for b in _category_branches()] == CATEGORIES


@pytest.mark.unit
@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_value_is_accepted(category: str) -> None:
    assert (
        _errors(
            _with_composition(
                {"a_column": {"category": category, "values": [{"author_value": "x"}]}}
            )
        )
        == []
    )


@pytest.mark.unit
def test_unknown_category_is_rejected() -> None:
    assert _errors(
        _with_composition(
            {"a_column": {"category": "karyotype", "values": [{"author_value": "x"}]}}
        )
    )


@pytest.mark.unit
def test_a_descriptor_with_no_category_validates() -> None:
    """Entries written before typing existed stay valid. Absence claims nothing
    either way, which is why a descriptor that was looked at and did not fit
    says so with `unclassified` instead."""
    assert _errors(_with_composition({"a_column": {"values": [{"author_value": "x"}]}})) == []


@pytest.mark.unit
def test_a_descriptor_that_fits_nothing_says_so_rather_than_being_forced() -> None:
    """Forcing a plausible-but-wrong category is worse than declining, and
    declining has to be sayable for the classification to be auditable."""
    assert (
        _errors(
            _with_composition(
                {"a_column": {"category": "unclassified", "values": [{"author_value": "x"}]}}
            )
        )
        == []
    )


@pytest.mark.unit
def test_several_descriptors_may_share_a_category() -> None:
    """Recording a descriptor at more than one granularity is common, and the
    entries are not interchangeable, so both are kept."""
    assert (
        _errors(
            _with_composition(
                {
                    "coarse": {"category": "tissue", "values": [{"author_value": "x"}]},
                    "fine": {"category": "tissue", "values": [{"author_value": "y"}]},
                }
            )
        )
        == []
    )


@pytest.mark.unit
def test_every_category_value_is_described() -> None:
    """The point of spelling the values out as branches rather than a bare enum
    is that each carries its own definition where an editor will see it.
    Collapsing them back to an enum would validate identically and lose that."""
    branches = _category_branches()
    undescribed = [b.get("const") for b in branches if not (b.get("description") or "").strip()]
    assert undescribed == []
    assert len(branches) == len({b["const"] for b in branches})
