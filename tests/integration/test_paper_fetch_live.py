"""The retrieval waterfall against the real services.

One paper per rung, each chosen because that is where it actually lands. These
run against live APIs on purpose: the rungs exist because of how these services
behave, and a mock would only restate what we already believed.

They are also a canary. If Europe PMC starts serving the article XML for a paper
recorded here as unavailable, or a publisher stops blocking a download, the
failure is the news.
"""

from __future__ import annotations

import pytest
from atlas_chat.services.paper_fetch import (
    candidates,
    contact_email,
    fetch_paper,
    looks_readable,
    paper_dir,
    preprint_metadata,
)

pytestmark = pytest.mark.integration


def test_a_contact_address_is_available() -> None:
    """Fail hard rather than skip: without this the resolver rung cannot run,
    and a silently skipped rung looks like a paper that is not open access."""
    assert contact_email(), (
        "no contact address for the open-access resolver; set "
        "ATLAS_CHAT_CONTACT_EMAIL or a git user.email"
    )


def test_europepmc_serves_article_xml(tmp_path) -> None:
    record = fetch_paper("10.1038/s41467-020-20358-y", tmp_path)

    assert record.route == "europepmc"
    assert record.kind == "jats"
    source = paper_dir(tmp_path, record.doi) / record.path
    assert source.read_text(encoding="utf-8", errors="replace").lstrip().startswith("<?xml")
    assert record.text_file is None, "article XML is read directly, not extracted"


def test_the_preprint_server_serves_jats_past_cloudflare(tmp_path) -> None:
    """Also covers bioRxiv's newer DOI prefix, which is not 10.1101."""
    record = fetch_paper("10.64898/2026.06.10.731198", tmp_path)

    assert record.route == "preprint_server"
    assert record.kind == "jats"
    assert record.title


def test_medrxiv_is_reached_as_well_as_biorxiv() -> None:
    """The details API is shared and the servers use the same DOI prefix, so only
    asking bioRxiv loses medRxiv silently rather than noisily."""
    import httpx

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        meta, server, unreachable = preprint_metadata("10.1101/2023.10.21.23297352", client)
    assert not unreachable, f"the details API did not answer: {unreachable}"
    assert server == "medrxiv", f"expected medRxiv to answer, got {server!r}"
    assert meta and meta.get("jatsxml")


def test_the_resolver_finds_a_pdf_and_it_extracts_to_readable_text(tmp_path) -> None:
    """A closed-access paper with an open manuscript in a repository — the case
    the resolver rung exists for."""
    record = fetch_paper("10.1016/j.devcel.2023.07.014", tmp_path)

    assert record.route == "unpaywall"
    assert record.kind == "pdf"
    assert record.text_quality and looks_readable(record.text_quality)
    text = (paper_dir(tmp_path, record.doi) / record.text_file).read_text(encoding="utf-8")
    assert len(text) > 20_000

    used = [loc for loc in record.oa_candidates if loc.get("used")]
    assert len(used) == 1
    assert used[0]["version"], "the version has to be recorded — it is what says whether"
    " this is the paper or a manuscript of it"


def test_a_paper_no_route_can_reach_is_recorded_rather_than_raising(tmp_path) -> None:
    """Not open access anywhere. Asking the user is the route, and the record
    has to say enough for the ask to be actionable."""
    record = fetch_paper("10.1126/science.adx0659", tmp_path)

    assert record.route == "none"
    assert record.gap
    assert record.title and record.title in record.gap["what"]
    assert "adopt" in record.gap["action"]
    assert {a.route for a in record.attempts} == {"europepmc", "preprint_server", "unpaywall"}
    assert all(a.outcome != "skipped" for a in record.attempts), (
        "every rung should have actually run; a skipped rung means nothing was learnt"
    )


def test_an_unreachable_paper_is_not_re_fetched_without_a_retry(tmp_path) -> None:
    first = fetch_paper("10.1126/science.adx0659", tmp_path)
    second = fetch_paper("10.1126/science.adx0659", tmp_path)
    assert second.attempted_at == first.attempted_at


def test_a_fetched_paper_reads_back_as_a_candidate(tmp_path) -> None:
    """What the fetcher stores and what the drop-zone reader recognises are the
    same kinds of file, so a stored paper is a fair test of the reader."""
    fetch_paper("10.1038/s41467-020-20358-y", tmp_path)
    found = candidates(tmp_path)

    assert len(found) == 1
    assert found[0]["kind"] == "jats"
    assert found[0]["title"]
