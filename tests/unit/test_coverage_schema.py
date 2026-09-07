"""Schema regression for coverage.json and gather_evidence_input.

Coverage drives the escalation ladder and the synthesizer's honesty contract, so
its shape is pinned: all five aspects present, no extras, and the
absent_after_free_search verdict representable.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from atlas_chat.schemas import load_schema

pytestmark = pytest.mark.unit

ASPECTS = ("location", "structure", "function", "markers", "marker_roles")


def _coverage(**overrides):
    doc = {
        "cell_label": "Iron-recycling macrophage",
        "assessed_from": "traversal_output/iron/all_summaries.json",
        "aspects": {a: {"status": "covered", "in_scope_items": 2} for a in ASPECTS},
    }
    doc.update(overrides)
    return doc


def _validate(doc, schema_name):
    jsonschema.Draft202012Validator(load_schema(schema_name)).validate(doc)


def test_coverage_good() -> None:
    _validate(_coverage(), "coverage.schema.json")


def test_coverage_absent_after_free_search_representable() -> None:
    doc = _coverage()
    doc["aspects"]["structure"] = {
        "status": "absent_after_free_search",
        "in_scope_items": 0,
        "off_scope_only": False,
        "note": "transcriptomic atlas; no morphology described",
    }
    _validate(doc, "coverage.schema.json")


def test_coverage_missing_aspect_rejected() -> None:
    doc = _coverage()
    del doc["aspects"]["markers"]
    with pytest.raises(jsonschema.ValidationError):
        _validate(doc, "coverage.schema.json")


def test_coverage_unknown_aspect_rejected() -> None:
    doc = _coverage()
    doc["aspects"]["vibes"] = {"status": "covered", "in_scope_items": 1}
    with pytest.raises(jsonschema.ValidationError):
        _validate(doc, "coverage.schema.json")


def test_coverage_bad_status_rejected() -> None:
    doc = _coverage()
    doc["aspects"]["markers"]["status"] = "fine"
    with pytest.raises(jsonschema.ValidationError):
        _validate(doc, "coverage.schema.json")


def _gather_input(**overrides):
    doc = {
        "seeds": [{"paper_id": "DOI:10.1038/s41586-024-08002-x", "role": "atlas", "priority": 0}],
        "decomposition_path": "traversal_output/iron/query_decomposition.json",
        "project_dir": "projects/test_projects/fetal_skin_atlas",
        "output_dir": "traversal_output/iron",
    }
    doc.update(overrides)
    return doc


def test_gather_input_good() -> None:
    _validate(_gather_input(), "gather_evidence_input.schema.json")


def test_gather_input_full() -> None:
    _validate(
        _gather_input(depth=2, k_per_paper=5, run_cap=20, reader_model="sonnet"),
        "gather_evidence_input.schema.json",
    )


def test_gather_input_empty_seeds_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(_gather_input(seeds=[]), "gather_evidence_input.schema.json")


def test_gather_input_bad_role_rejected() -> None:
    doc = _gather_input(seeds=[{"paper_id": "DOI:10.1/x", "role": "external"}])
    with pytest.raises(jsonschema.ValidationError):
        _validate(doc, "gather_evidence_input.schema.json")


def test_gather_input_depth_over_cap_rejected() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(_gather_input(depth=3), "gather_evidence_input.schema.json")


def test_retrieval_method_enum_in_sync() -> None:
    """all_summaries and evidence_summary must agree on the enum incl. full_text."""

    def enum_of(name):
        schema = load_schema(name)
        defs = schema.get("$defs", {})
        if "retrieval_method" in defs:
            return defs["retrieval_method"]["enum"]
        return schema["properties"]["retrieval_method"]["enum"]

    a = enum_of("all_summaries.schema.json")
    b = enum_of("evidence_summary.schema.json")
    assert a == b
    assert "full_text" in a


def test_hook_rejects_bad_coverage(tmp_path) -> None:
    """The check_coverage hook exits 2 on an invalid coverage.json write."""
    import subprocess
    import sys

    bad = _coverage()
    del bad["aspects"]["function"]
    payload = json.dumps(
        {
            "tool_input": {
                "file_path": str(tmp_path / "coverage.json"),
                "content": json.dumps(bad),
            }
        }
    )
    proc = subprocess.run(
        [sys.executable, ".claude/hooks/check_coverage.py"],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "COVERAGE VALIDATION FAILED" in proc.stderr

    good = json.dumps(
        {
            "tool_input": {
                "file_path": str(tmp_path / "coverage.json"),
                "content": json.dumps(_coverage()),
            }
        }
    )
    proc = subprocess.run(
        [sys.executable, ".claude/hooks/check_coverage.py"],
        input=good,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
