"""The retrieval waterfall: what it tries, in what order, and what it records.

The rungs themselves are stubbed. What matters here is the accounting — that a
rung which ran and found nothing is distinguishable from one that could not run
at all, and that a paper nobody could get is recorded as such rather than
silently retried forever.
"""

from __future__ import annotations

import json

import pytest
from atlas_chat.services.paper_fetch import (
    Attempt,
    Fetched,
    PaperFetchError,
    Retrieval,
    adopt,
    candidates,
    cross_check_retrieval,
    fetch_paper,
    looks_readable,
    oa_locations,
    paper_dir,
    read_record,
    write_record,
)

from atlas_chat.services import paper_fetch

pytestmark = pytest.mark.unit

DOI = "10.1234/example.2024.001"

JATS = b"""<?xml version="1.0"?>
<article><front><article-meta>
<article-title>A worked example of something</article-title>
</article-meta></front><body><sec><title>Results</title>
<p>The cells were counted and then counted again.</p></sec></body></article>
"""


def stub(kind: str | None, outcome: str = "ok", note: str = "stub"):
    """A rung that either produces bytes or records why it did not."""

    def rung(doi: str, record: Retrieval, ctx: object) -> Fetched | None:
        record.attempts.append(Attempt(rung.route_name, outcome, note))  # type: ignore[attr-defined]
        if kind is None:
            return None
        return Fetched(kind=kind, body=JATS, url="https://example.org/paper", title="Example")

    return rung


def rungs(*specs):
    """Build a RUNGS tuple from ``(name, kind, outcome)`` triples."""
    built = []
    for name, kind, outcome in specs:
        rung = stub(kind, outcome)
        rung.route_name = name  # type: ignore[attr-defined]
        built.append((name, rung))
    return tuple(built)


# ------------------------------------------------------------------
# Order and accounting
# ------------------------------------------------------------------


def test_first_rung_that_works_wins_and_later_rungs_are_not_tried(tmp_path, monkeypatch):
    monkeypatch.setattr(
        paper_fetch,
        "RUNGS",
        rungs(
            ("europepmc", "jats", "ok"),
            ("preprint_server", "jats", "ok"),
        ),
    )
    record = fetch_paper(DOI, tmp_path)

    assert record.route == "europepmc"
    assert [a.route for a in record.attempts] == ["europepmc"]


def test_every_rung_reached_is_recorded_including_the_ones_that_found_nothing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        paper_fetch,
        "RUNGS",
        rungs(
            ("europepmc", None, "unavailable"),
            ("preprint_server", None, "failed"),
            ("unpaywall", "pdf", "ok"),
        ),
    )
    monkeypatch.setattr(
        paper_fetch, "pdf_text", lambda p: ("text " * 600, {"n_segments": 12, "n_chars": 3000})
    )

    record = fetch_paper(DOI, tmp_path)

    assert record.route == "unpaywall"
    assert [(a.route, a.outcome) for a in record.attempts] == [
        ("europepmc", "unavailable"),
        ("preprint_server", "failed"),
        ("unpaywall", "ok"),
    ]


def test_a_rung_that_could_not_run_is_skipped_not_unavailable(tmp_path, monkeypatch):
    """'skipped' means nothing was learnt about the paper, which is not the same
    as the rung having looked and found nothing. Only the latter is evidence."""
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("unpaywall", None, "skipped")))
    record = fetch_paper(DOI, tmp_path)

    assert record.route == "none"
    assert record.attempts[0].outcome == "skipped"


def test_no_route_produces_a_gap_naming_the_paper_and_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", None, "unavailable")))
    record = fetch_paper(DOI, tmp_path)

    assert record.route == "none"
    assert record.gap is not None
    assert DOI in record.gap["what"]
    assert "unavailable" in record.gap["reason"]
    assert "adopt" in record.gap["action"]


# ------------------------------------------------------------------
# Not doing the same work twice
# ------------------------------------------------------------------


def test_a_paper_already_here_is_not_re_fetched(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", "jats", "ok")))
    first = fetch_paper(DOI, tmp_path)

    calls: list[str] = []

    def exploding(doi, record, ctx):
        calls.append(doi)
        raise AssertionError("should not have been called")

    monkeypatch.setattr(paper_fetch, "RUNGS", (("europepmc", exploding),))
    second = fetch_paper(DOI, tmp_path)

    assert not calls
    assert second.retrieved_at == first.retrieved_at


def test_reuse_keeps_the_original_route_rather_than_recording_a_cache_hit(tmp_path):
    """A paper supplied by hand last week still reads as supplied."""
    supplied = tmp_path / "dropped.xml"
    supplied.write_bytes(JATS)
    adopt(DOI, tmp_path / "papers", supplied)

    again = fetch_paper(DOI, tmp_path / "papers")
    assert again.route == "manual"


def test_a_paper_recorded_as_unreachable_is_left_alone_until_a_retry_is_asked_for(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", None, "unavailable")))
    fetch_paper(DOI, tmp_path)

    calls: list[str] = []

    def counting(doi, record, ctx):
        calls.append(doi)
        record.attempts.append(Attempt("europepmc", "unavailable", "still nothing"))
        return None

    monkeypatch.setattr(paper_fetch, "RUNGS", (("europepmc", counting),))
    fetch_paper(DOI, tmp_path)
    assert calls == []

    fetch_paper(DOI, tmp_path, retry=True)
    assert calls == [DOI]


def test_changed_bytes_on_disk_mean_the_cache_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", "jats", "ok")))
    fetch_paper(DOI, tmp_path)
    (paper_dir(tmp_path, DOI) / "source" / "paper.jats.xml").write_bytes(
        b"<article>other</article>"
    )

    calls: list[str] = []

    def counting(doi, record, ctx):
        calls.append(doi)
        record.attempts.append(Attempt("europepmc", "ok", "re-fetched"))
        return Fetched(kind="jats", body=JATS)

    monkeypatch.setattr(paper_fetch, "RUNGS", (("europepmc", counting),))
    fetch_paper(DOI, tmp_path)
    assert calls == [DOI]


# ------------------------------------------------------------------
# Declining a PDF
# ------------------------------------------------------------------


def test_declining_pdfs_records_that_one_was_available(tmp_path, monkeypatch):
    """Refusing a PDF must not read as the paper being unavailable — it was
    available, and the caller chose not to take it."""
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("unpaywall", "pdf", "ok")))
    record = fetch_paper(DOI, tmp_path, allow_pdf=False)

    assert record.route == "none"
    assert record.attempts[0].outcome == "skipped"
    assert "declined" in (record.attempts[0].note or "")


# ------------------------------------------------------------------
# Taking in a supplied file
# ------------------------------------------------------------------


def test_adopting_article_xml_records_it_as_a_route(tmp_path):
    supplied = tmp_path / "somebody-sent-this.xml"
    supplied.write_bytes(JATS)

    record = adopt(DOI, tmp_path / "papers", supplied)

    assert record.route == "manual"
    assert record.kind == "jats"
    assert (paper_dir(tmp_path / "papers", DOI) / record.path).read_bytes() == JATS
    assert record.text_file is None


def test_adopting_rejects_a_file_that_is_not_what_its_name_claims(tmp_path):
    """A saved landing page with a .pdf name would otherwise be read as the paper."""
    fake = tmp_path / "paper.pdf"
    fake.write_bytes(b"<html><body>Access denied</body></html>")

    with pytest.raises(PaperFetchError, match="does not start with %PDF"):
        adopt(DOI, tmp_path / "papers", fake)


def test_adopting_rejects_xml_that_is_not_an_article(tmp_path):
    fake = tmp_path / "paper.xml"
    fake.write_bytes(b"<?xml version='1.0'?><html><body>Sign in</body></html>")

    with pytest.raises(PaperFetchError, match="no <article> element"):
        adopt(DOI, tmp_path / "papers", fake)


def test_adopting_rejects_a_spreadsheet(tmp_path):
    supplement = tmp_path / "media-3.xlsx"
    supplement.write_bytes(b"PK\x03\x04")

    with pytest.raises(PaperFetchError, match="neither a PDF nor article XML"):
        adopt(DOI, tmp_path / "papers", supplement)


# ------------------------------------------------------------------
# Reading a drop zone
# ------------------------------------------------------------------


def test_candidates_describes_papers_and_ignores_everything_else(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a-paper.xml").write_bytes(JATS)
    (tmp_path / "nested" / "another.xml").write_bytes(JATS)
    (tmp_path / "media-3.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / "figure.png").write_bytes(b"\x89PNG")

    found = candidates(tmp_path)

    assert [c["relative_path"] for c in found] == ["a-paper.xml", "nested/another.xml"]
    assert found[0]["title"] == "A worked example of something"
    assert found[0]["kind"] == "jats"


def test_candidates_reports_the_doi_a_file_declares(tmp_path):
    (tmp_path / "p.xml").write_bytes(
        b"<article><front><article-id pub-id-type='doi'>10.1234/example.2024.001</article-id>"
        b"<article-title>T</article-title></front><body><p>x</p></body></article>"
    )
    found = candidates(tmp_path)
    assert found[0]["doi"] == DOI


def test_candidates_on_a_missing_directory_says_so(tmp_path):
    with pytest.raises(PaperFetchError, match="no such directory"):
        candidates(tmp_path / "not-here")


# ------------------------------------------------------------------
# Judging recovered text
# ------------------------------------------------------------------


def test_a_scan_does_not_look_readable():
    assert not looks_readable({"n_segments": 3, "n_chars": 41})


def test_a_paper_looks_readable():
    assert looks_readable({"n_segments": 180, "n_chars": 76344})


# ------------------------------------------------------------------
# Reading an open-access resolver's answer
# ------------------------------------------------------------------


def test_locations_are_deduplicated_with_the_preferred_one_first():
    """The resolver repeats its preferred location inside the full list."""
    payload = {
        "is_oa": True,
        "best_oa_location": {
            "url": "https://a",
            "host_type": "publisher",
            "version": "publishedVersion",
        },
        "oa_locations": [
            {"url": "https://a", "host_type": "publisher", "version": "publishedVersion"},
            {"url": "https://b", "url_for_pdf": "https://b.pdf", "host_type": "repository"},
        ],
    }
    assert [loc["url"] for loc in oa_locations(payload)] == ["https://a", "https://b"]


def test_a_preferred_location_without_a_pdf_does_not_hide_a_later_one_that_has_one():
    payload = {
        "is_oa": True,
        "best_oa_location": {"url": "https://doi.org/x", "version": "publishedVersion"},
        "oa_locations": [
            {"url": "https://doi.org/x", "version": "publishedVersion"},
            {
                "url": "https://repo",
                "url_for_pdf": "https://repo.pdf",
                "version": "submittedVersion",
            },
        ],
    }
    with_pdf = [loc for loc in oa_locations(payload) if loc.get("url_for_pdf")]
    assert [loc["url_for_pdf"] for loc in with_pdf] == ["https://repo.pdf"]


def test_the_resolvers_own_vocabulary_is_carried_through_unchanged():
    """A value the resolver adds later must not read as invalid."""
    payload = {
        "is_oa": True,
        "oa_locations": [
            {"url": "https://x", "host_type": "something_new", "version": "acceptedVersion"}
        ],
    }
    assert oa_locations(payload)[0]["host_type"] == "something_new"


def test_a_paper_that_is_not_open_access_yields_no_locations():
    assert oa_locations({"is_oa": False, "best_oa_location": None, "oa_locations": []}) == []


# ------------------------------------------------------------------
# The record's own consistency
# ------------------------------------------------------------------


def test_a_record_claiming_a_route_with_nothing_stored_is_rejected():
    problems = cross_check_retrieval(
        {"doi": DOI, "route": "europepmc", "attempts": [{"route": "europepmc", "outcome": "ok"}]}
    )
    assert any("path is missing" in p for p in problems)


def test_a_record_with_no_route_but_a_stored_file_is_rejected():
    problems = cross_check_retrieval(
        {"doi": DOI, "route": "none", "path": "source/paper.pdf", "attempts": []}
    )
    assert any("path is set" in p for p in problems)


def test_recovered_text_without_its_size_is_rejected():
    problems = cross_check_retrieval(
        {
            "doi": DOI,
            "route": "manual",
            "kind": "pdf",
            "path": "source/paper.pdf",
            "sha256": "a" * 64,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "text_file": "source/paper.txt",
            "attempts": [{"route": "manual", "outcome": "ok"}],
        }
    )
    assert any("text_quality" in p for p in problems)


def test_a_jats_record_carrying_recovered_text_is_rejected():
    problems = cross_check_retrieval(
        {
            "doi": DOI,
            "route": "europepmc",
            "kind": "jats",
            "path": "source/paper.jats.xml",
            "sha256": "a" * 64,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "text_file": "source/paper.txt",
            "text_quality": {"n_segments": 1, "n_chars": 10},
            "attempts": [{"route": "europepmc", "outcome": "ok"}],
        }
    )
    assert any("read directly" in p for p in problems)


def test_a_used_location_on_a_route_that_is_not_the_resolver_is_rejected():
    problems = cross_check_retrieval(
        {
            "doi": DOI,
            "route": "manual",
            "kind": "pdf",
            "path": "source/paper.pdf",
            "sha256": "a" * 64,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "attempts": [{"route": "manual", "outcome": "ok"}],
            "oa_candidates": [{"url": "https://x", "used": True}],
        }
    )
    assert any("marked used" in p for p in problems)


def test_an_inconsistent_record_is_never_written(tmp_path):
    record = Retrieval(doi=DOI, route="europepmc")
    with pytest.raises(PaperFetchError, match="not self-consistent"):
        write_record(record, tmp_path)
    assert not (paper_dir(tmp_path, DOI) / "retrieval.json").exists()


def test_a_written_record_reads_back_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", "jats", "ok")))
    written = fetch_paper(DOI, tmp_path)
    reloaded = read_record(tmp_path, DOI)

    assert reloaded is not None
    assert reloaded.to_dict() == written.to_dict()


def test_records_written_by_the_waterfall_conform_to_the_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("europepmc", None, "unavailable")))
    fetch_paper(DOI, tmp_path)
    payload = json.loads((paper_dir(tmp_path, DOI) / "retrieval.json").read_text())

    paper_fetch.validate_retrieval(payload)
    assert cross_check_retrieval(payload) == []


# ------------------------------------------------------------------
# What the negative cache is entitled to believe
# ------------------------------------------------------------------


def test_a_rung_that_broke_does_not_settle_the_question(tmp_path, monkeypatch):
    """An outage must not leave a retrievable paper permanently marked unreachable."""
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("preprint_server", None, "failed")))
    fetch_paper(DOI, tmp_path)

    calls: list[str] = []

    def counting(doi, record, ctx):
        calls.append(doi)
        record.attempts.append(Attempt("preprint_server", "ok", "the server is back"))
        return Fetched(kind="jats", body=JATS)

    monkeypatch.setattr(paper_fetch, "RUNGS", (("preprint_server", counting),))
    record = fetch_paper(DOI, tmp_path)

    assert calls == [DOI], "a paper that failed on an outage should be tried again"
    assert record.route == "preprint_server"


def test_a_rung_that_could_not_run_does_not_settle_the_question(tmp_path, monkeypatch):
    """Installing the missing dependency should be enough; no --retry needed."""
    monkeypatch.setattr(paper_fetch, "RUNGS", rungs(("unpaywall", None, "skipped")))
    fetch_paper(DOI, tmp_path)

    calls: list[str] = []

    def counting(doi, record, ctx):
        calls.append(doi)
        record.attempts.append(Attempt("unpaywall", "unavailable", "genuinely not open"))
        return None

    monkeypatch.setattr(paper_fetch, "RUNGS", (("unpaywall", counting),))
    fetch_paper(DOI, tmp_path)
    assert calls == [DOI]


def test_rungs_that_all_answered_do_settle_the_question(tmp_path, monkeypatch):
    """The point of the cache: a paper genuinely behind a paywall is asked for
    once, not on every pass."""
    monkeypatch.setattr(
        paper_fetch,
        "RUNGS",
        rungs(
            ("europepmc", None, "unavailable"),
            ("unpaywall", None, "unavailable"),
        ),
    )
    fetch_paper(DOI, tmp_path)

    def exploding(doi, record, ctx):
        raise AssertionError("should not have been called")

    monkeypatch.setattr(paper_fetch, "RUNGS", (("europepmc", exploding),))
    assert fetch_paper(DOI, tmp_path).route == "none"


def test_an_unreachable_preprint_server_is_failed_not_unavailable(monkeypatch):
    """'not hosted by biorxiv or medrxiv' is a claim about the paper; a timeout
    is a claim about the network, and they must not read the same."""
    from atlas_chat.services.paper_fetch import Context, _rung_preprint_server

    monkeypatch.setattr(
        paper_fetch,
        "preprint_metadata",
        lambda doi, client: (None, "", ["medrxiv: ReadTimeout"]),
    )
    record = Retrieval(doi=DOI)
    assert _rung_preprint_server(DOI, record, Context(client=None)) is None
    assert record.attempts[0].outcome == "failed"
    assert "medrxiv" in (record.attempts[0].note or "")


def test_both_servers_answering_no_is_unavailable(monkeypatch):
    from atlas_chat.services.paper_fetch import Context, _rung_preprint_server

    monkeypatch.setattr(paper_fetch, "preprint_metadata", lambda doi, client: (None, "", []))
    record = Retrieval(doi=DOI)
    assert _rung_preprint_server(DOI, record, Context(client=None)) is None
    assert record.attempts[0].outcome == "unavailable"
