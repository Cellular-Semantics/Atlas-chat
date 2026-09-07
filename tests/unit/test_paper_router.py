"""Routing waterfall: local JATS cache -> EuropePMC -> preprint -> ASTA -> unreachable.

The route decision is the one place the JATS-first policy lives; these tests pin
each rung and the fall-through order, with every network boundary monkeypatched
(unit tests are isolated; the real endpoints are exercised in integration tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_chat.services.local_snippet_index import paper_slug

from atlas_chat.services import paper_router

pytestmark = pytest.mark.unit

DOI = "10.1038/s41586-024-08002-x"
XML = "<article><body><sec><title>Results</title><p>Cells.</p></sec></body></article>"


def _cache_xml(project: Path, doi: str, xml: str = XML) -> Path:
    src = project / "local_index" / "papers" / paper_slug(doi) / "source"
    src.mkdir(parents=True)
    path = src / "paper.jats.xml"
    path.write_text(xml)
    return path


# ---------------------------------------------------------------- id handling


def test_normalize_id_forms() -> None:
    assert paper_router.normalize_id(f"DOI:{DOI}") == (DOI, None)
    assert paper_router.normalize_id(DOI) == (DOI, None)
    assert paper_router.normalize_id("CorpusId:123") == (None, "CorpusId:123")
    assert paper_router.normalize_id("garbage") == (None, None)


def test_canonical_key_is_doi_case_insensitive() -> None:
    assert paper_router.canonical_key(f"DOI:{DOI.upper()}") == DOI.lower()
    assert paper_router.canonical_key("CorpusId:9") == "CorpusId:9"


# ---------------------------------------------------------------- waterfall


def test_cache_hit_short_circuits_all_fetching(tmp_path, monkeypatch) -> None:
    path = _cache_xml(tmp_path, DOI)

    def boom(*a, **k):  # any network call is a test failure
        raise AssertionError("network rung reached despite cache hit")

    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", boom)
    monkeypatch.setattr(paper_router, "_try_preprint", boom)
    monkeypatch.setattr(paper_router, "_probe_band", boom)

    route = paper_router.resolve_route(f"DOI:{DOI}", tmp_path)
    assert route.method == paper_router.JATS
    assert route.source == "cache"
    assert route.cache_path == str(path)


def test_europepmc_fetch_writes_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", lambda doi: XML)
    route = paper_router.resolve_route(DOI, tmp_path)
    assert route.method == paper_router.JATS
    assert route.source == "europepmc"
    assert Path(route.cache_path).read_text() == XML
    # Second call now hits the cache
    route2 = paper_router.resolve_route(DOI, tmp_path)
    assert route2.source == "cache"


def test_preprint_rung_after_europepmc_miss(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", lambda doi: None)

    def fake_preprint(doi: str, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / "paper.jats.xml"
        p.write_text(XML)
        return p

    monkeypatch.setattr(paper_router, "_try_preprint", fake_preprint)
    route = paper_router.resolve_route(DOI, tmp_path)
    assert route.method == paper_router.JATS
    assert route.source == "preprint"


@pytest.mark.parametrize(
    ("band", "expected_method"),
    [
        ("full", paper_router.ASTA),
        ("partial", paper_router.ASTA),
        ("abstract_only", paper_router.UNREACHABLE),
        ("unindexed", paper_router.UNREACHABLE),
        ("not_in_s2", paper_router.UNREACHABLE),
    ],
)
def test_asta_rung_gates_on_band(tmp_path, monkeypatch, band, expected_method) -> None:
    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", lambda doi: None)
    monkeypatch.setattr(paper_router, "_try_preprint", lambda doi, dest: None)
    monkeypatch.setattr(paper_router, "_probe_band", lambda pid, proj: (band, None))
    route = paper_router.resolve_route(DOI, tmp_path)
    assert route.method == expected_method
    assert route.band == band
    if expected_method == paper_router.UNREACHABLE:
        assert band in (route.reason or "")


def test_corpusid_only_skips_jats_rungs(tmp_path, monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("JATS rung reached for a CorpusId-only paper")

    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", boom)
    monkeypatch.setattr(paper_router, "_try_preprint", boom)
    monkeypatch.setattr(paper_router, "_probe_band", lambda pid, proj: ("full", None))
    route = paper_router.resolve_route("CorpusId:123", tmp_path)
    assert route.method == paper_router.ASTA


def test_unparseable_id_is_unreachable(tmp_path) -> None:
    route = paper_router.resolve_route("not-an-id", tmp_path)
    assert route.method == paper_router.UNREACHABLE
    assert route.reason == "unparseable id"


def test_probe_failure_is_unreachable_not_crash(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_router, "_fetch_europepmc_xml", lambda doi: None)
    monkeypatch.setattr(paper_router, "_try_preprint", lambda doi, dest: None)
    monkeypatch.setattr(paper_router, "_probe_band", lambda pid, proj: (None, "boom"))
    route = paper_router.resolve_route(DOI, tmp_path)
    assert route.method == paper_router.UNREACHABLE
    assert "boom" in route.reason


# ---------------------------------------------------------------- seen-set


def test_traversed_roundtrip_and_id_space_bridging(tmp_path) -> None:
    path = tmp_path / "traversed.json"
    assert not paper_router.is_traversed(path, DOI)
    paper_router.mark_traversed(path, f"DOI:{DOI}", {"method": "jats"})
    # Same paper under a different id form is still seen
    assert paper_router.is_traversed(path, DOI)
    assert paper_router.is_traversed(path, f"DOI:{DOI.upper()}")
    # Merge, don't clobber
    paper_router.mark_traversed(path, DOI, {"hop": 1})
    data = json.loads(path.read_text())
    entry = data[DOI.lower()]
    assert entry["method"] == "jats"
    assert entry["hop"] == 1


def test_traversed_unreadable_is_empty(tmp_path) -> None:
    path = tmp_path / "traversed.json"
    path.write_text("{broken")
    assert paper_router.load_traversed(path) == {}
