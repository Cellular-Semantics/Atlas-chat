"""Integration tests for the bioRxiv supplement route against the real site.

No mocks. bioRxiv answers a plain HTTP client with a bot challenge rather than
an error, so the route depends on both the metadata API and the impersonating
client behaving as they did when it was written; these tests fail hard if
either changes shape.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_chat.services import supplement_fetch as fetch
from atlas_chat.services import supplement_store as store

pytestmark = pytest.mark.integration

# A preprint with several supplementary workbooks and no PMC record, so every
# other rung of the waterfall is blind to it.
PREPRINT = "10.64898/2026.06.10.731198"


@pytest.fixture
def client():
    with httpx.Client(follow_redirects=True, timeout=fetch.TIMEOUT) as c:
        yield c


def test_metadata_lookup_identifies_the_preprint() -> None:
    """How the route decides a DOI is a preprint, and which version to ask for."""
    meta = fetch.biorxiv_metadata(PREPRINT)

    assert meta is not None
    assert meta["doi"] == PREPRINT
    assert meta["version"].isdigit()


def test_metadata_lookup_declines_a_journal_doi() -> None:
    assert fetch.biorxiv_metadata("10.1038/s41588-024-01873-w") is None


def test_the_supplement_page_lists_files_with_labels() -> None:
    listed = fetch.biorxiv_listing(PREPRINT)

    assert listed, "the preprint's supplement page should list files"
    assert all(entry["retrieval"]["route"] == "biorxiv" for entry in listed)
    assert all(entry["retrieval"]["url"].startswith("https://") for entry in listed)
    # The author's labels are the only description of the files there is.
    assert any(entry.get("label") for entry in listed)


def test_a_listed_file_downloads_and_opens() -> None:
    listed = fetch.biorxiv_listing(PREPRINT)
    workbook = next(entry for entry in listed if entry["media_type"] == "xlsx")

    payload, note = fetch.biorxiv_get(workbook["retrieval"]["url"])

    assert payload is not None, note
    assert payload[:4] == b"PK\x03\x04", "an xlsx is a zip container"


def test_preprint_is_fully_retrieved_end_to_end(tmp_path, client) -> None:
    manifest = fetch.fetch_supplements(tmp_path, PREPRINT, client=client)

    store.validate_manifest(manifest)
    assert store.cross_check_manifest(manifest) == []
    assert manifest["files"]
    assert manifest["gaps"] == []
    for entry in manifest["files"]:
        assert entry["status"] == "present"
        assert entry["retrieval"]["route"] == "biorxiv"
        assert (tmp_path / entry["path"]).stat().st_size == entry["size_bytes"]
        assert len(entry["retrieval"]["sha256"]) == 64


def test_a_retrieved_workbook_is_immediately_indexable(tmp_path, client) -> None:
    """What fetch writes, the store must be able to outline."""
    manifest = fetch.fetch_supplements(tmp_path, PREPRINT, client=client)

    workbook = next(f for f in manifest["files"] if f["media_type"] == "xlsx")
    outline = store.outline_file(tmp_path / workbook["path"])

    assert outline["tables"]
