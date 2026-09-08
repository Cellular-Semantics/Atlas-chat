"""Retrieve a paper's supplementary material into the supplement store.

The companion to :mod:`atlas_chat.services.supplement_store`, which owns disk
layout and the manifest. This module only gets bytes, and records how it got
them (or why it couldn't) in the manifest the store already defines.

The waterfall
-------------

The order below is not a guess; it comes from probing the 22 papers of the
reproductive-atlas corpus (Springer Nature, Cell Press, AAAS, JCI, Wiley,
Oxford, PNAS, and a bioRxiv preprint):

1. **Article XML** (``jats_listing``). Europe PMC's ``fullTextXML`` yields the
   filenames *and* the publisher's captions, which exist nowhere else and often
   describe the contents better than anything recoverable from the bytes.
   Available for 14 of 22.
2. **Europe PMC bundle** (``europepmc_bundle``). One zip per article, whose
   members are named exactly as the article XML lists them, so wanted files can
   be extracted and the figure images that bloat the zip skipped. Its virtue is
   that it needs no per-publisher knowledge at all. Streamed under a byte cap:
   observed 14–28 MB for most papers, but a 34-file PNAS paper exceeded 60 MB
   and the prenatal skin atlas exceeds 445 MB because of a supplementary video.
3. **Publisher-direct** (``publisher_direct``). Per-file, needing a URL template
   per publisher. Only Springer Nature is implemented, because its ESM stem is
   derivable from the DOI alone (verified on 8 of 8 Springer papers in the
   corpus) — for others, a template can be added when a corpus needs it.
4. **bioRxiv** (``biorxiv``). A preprint has no PMC record, so the three rungs
   above are all blind to it, but the preprint server lists its supplements on
   a page of its own and serves each file individually. That page supplies
   both the listing (with the author's labels) and the bytes, so this route
   stands in for rungs 1 and 3 at once for the papers it covers.
5. **Manual** (``manual``). Recorded as a gap naming the file and where to get
   it. The route of last resort for closed-access papers, and for anything
   published where none of the above reaches.

Two traps this module exists to avoid
-------------------------------------

*The bundle endpoint returns HTTP 200 with an empty body* for a PMC paper whose
full text is not open — 165 bytes, not a zip. Written naively that is an empty
archive recorded as a success, and the paper looks like it has no supplements.
It is detected and recorded as ``unavailable``.

*A missing supplement asked for on every run.* Every route that fails stamps
``retrieval.attempted_at``, and a later run skips it unless a retry is
requested. That is the negative cache.

.. code-block:: bash

    python -m atlas_chat.cli_supplements fetch --store S --doi 10.1038/...
    python -m atlas_chat.cli_supplements fetch --store S --cas projects/X/cas.json
"""

from __future__ import annotations

import logging
import re
import tempfile
import urllib.parse
import zipfile
from collections import Counter
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from atlas_chat.services.fetch_preprint import biorxiv_metadata
from atlas_chat.services.supplement_store import (
    MANIFEST_VERSION,
    SupplementStoreError,
    _dedupe_gaps,
    _merge_files,
    _rel,
    _sha256,
    files_dir,
    inventory_from_jats,
    load_manifest,
    media_type,
    paper_dir,
    write_manifest,
)

logger = logging.getLogger(__name__)

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

#: Ceiling on the Europe PMC bundle. Measured over the reproductive-atlas
#: corpus: most bundles are 10-30 MB, a 34-file PNAS article is 197 MB (mostly
#: figure images, which we then discard), and the prenatal skin atlas exceeds
#: 445 MB because of a supplementary video. 250 MB therefore keeps every corpus
#: paper reachable while still refusing the video outliers, which are better
#: served per-file. Above the cap the download is abandoned and the next route
#: takes over.
DEFAULT_BUNDLE_CAP_BYTES = 250 * 1024 * 1024

#: Bundle bytes are spooled to disk beyond this, so a generous cap costs disk
#: rather than RAM.
BUNDLE_SPOOL_TO_DISK_BYTES = 32 * 1024 * 1024

#: Never treated as supplementary content worth storing. Europe PMC's bundle
#: includes the article's figure images, which are most of its bulk.
FIGURE_SUFFIXES = {".gif", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


TIMEOUT = httpx.Timeout(30.0, read=180.0)


class SupplementFetchError(RuntimeError):
    """Raised when a fetch cannot proceed at all (bad DOI, no network)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------
# Identifiers and the article XML
# ------------------------------------------------------------------


def resolve_pmcid(client: httpx.Client, doi: str) -> tuple[str, str]:
    """Resolve a DOI to its PMCID via Europe PMC.

    Returns:
        ``(pmcid, title)``; the PMCID is empty when Europe PMC has no PMC record,
        which is the signal that only a manual route remains.
    """
    resp = client.get(
        f"{EUROPEPMC}/search",
        params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 1, "resultType": "core"},
    )
    resp.raise_for_status()
    results = resp.json().get("resultList", {}).get("result", [])
    if not results:
        logger.info("%s: not in Europe PMC", doi)
        return "", ""
    record = results[0]
    pmcid = record.get("pmcid") or ""
    logger.info("%s -> %s", doi, pmcid or "(no PMCID)")
    return pmcid, record.get("title") or ""


def fetch_jats(client: httpx.Client, pmcid: str, dest: Path) -> Path | None:
    """Save the article XML, the source of both filenames and captions.

    Returns None when Europe PMC has the record but not its full text — a real
    case in the corpus (3 of 17 PMC papers), and the point at which the caption
    route is gone even though a PMCID exists.
    """
    resp = client.get(f"{EUROPEPMC}/{pmcid}/fullTextXML")
    if resp.status_code != 200:
        logger.info("%s: fullTextXML %s — no article XML, so no captions", pmcid, resp.status_code)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resp.text, encoding="utf-8")
    return dest


# ------------------------------------------------------------------
# Route: Europe PMC bundle
# ------------------------------------------------------------------


class BundleResult:
    """Outcome of one bundle attempt.

    ``archive`` is None unless bytes arrived and parsed as a zip; ``reason``
    always explains what happened, because that string ends up in the manifest.
    """

    def __init__(self, archive: zipfile.ZipFile | None, reason: str, size: int = 0):
        self.archive = archive
        self.reason = reason
        self.size = size


def fetch_bundle(
    client: httpx.Client, pmcid: str, cap: int = DEFAULT_BUNDLE_CAP_BYTES
) -> BundleResult:
    """Stream the article's supplement bundle, abandoning it above ``cap``.

    Europe PMC serves every supplement for an article as one zip with no way to
    select files, so the only protection against a half-gigabyte download is to
    stop reading. The stream spools to a temporary file past
    ``BUNDLE_SPOOL_TO_DISK_BYTES``, so a 197 MB bundle costs disk rather than
    RAM and the cap can stay generous.
    """
    # Not a context manager: on success the buffer is handed to a ZipFile that
    # the caller reads from, so it must outlive this function. The ZipFile keeps
    # it alive and closing that releases it.
    buffer = tempfile.SpooledTemporaryFile(  # noqa: SIM115
        max_size=BUNDLE_SPOOL_TO_DISK_BYTES
    )
    url = f"{EUROPEPMC}/{pmcid}/supplementaryFiles"
    with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            return BundleResult(None, f"bundle returned HTTP {resp.status_code}")
        for chunk in resp.iter_bytes(1 << 20):
            buffer.write(chunk)
            if buffer.tell() > cap:
                return BundleResult(
                    None,
                    f"bundle exceeds the {cap}-byte cap (still growing at "
                    f"{buffer.tell()} bytes); abandoned",
                    buffer.tell(),
                )

    size = buffer.tell()
    if size == 0:
        return BundleResult(None, "bundle is empty (HTTP 200, zero bytes)", 0)

    buffer.seek(0)
    if not zipfile.is_zipfile(buffer):
        # The endpoint answers 200 with a short non-zip body for PMC papers whose
        # full text is not open. Recording that as success would make the paper
        # look as though it has no supplements.
        return BundleResult(
            None,
            f"bundle is not a zip ({size} bytes) — Europe PMC has no open "
            "supplementary files for this article",
            size,
        )
    buffer.seek(0)
    return BundleResult(zipfile.ZipFile(buffer), "ok", size)


def _is_figure(name: str) -> bool:
    return Path(name).suffix.lower() in FIGURE_SUFFIXES


#: Formats whose first bytes let us check that a payload is what it claims.
#: xlsx and docx are zip containers; a PDF starts with %PDF.
ZIP_CONTAINER_TYPES = {"xlsx", "docx", "zip"}


def verify_payload(path: Path, media: str) -> tuple[bool, str]:
    """Check that retrieved bytes are structurally the format they claim.

    A route can hand back a file that is the wrong size and unopenable, and
    Europe PMC does: its bundle for PMC8648563 carries an 18.5 MB copy of a
    workbook the publisher serves at 35.7 MB, truncated so that no zip reader
    can open it. Extracted faithfully and recorded with a checksum, that looks
    authoritative and only fails much later, during indexing.

    Cheap enough to run on every file — it reads a header, or a zip's central
    directory, not the payload.

    Returns:
        ``(ok, note)``; the note names the problem when ok is False.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"not readable: {exc}"
    if size == 0:
        return False, "zero bytes"

    if media in ZIP_CONTAINER_TYPES:
        if not zipfile.is_zipfile(path):
            return False, (
                f"claims to be {media} but is not a readable zip container "
                f"({size} bytes) — truncated or corrupt at source"
            )
    elif media == "pdf":
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return False, f"claims to be a PDF but has no %PDF header ({size} bytes)"
    return True, "ok"


def is_non_evidence(entry: dict[str, Any]) -> bool:
    """Whether a file's own caption rules it out before any bytes move.

    Only the certain cases — a Reporting Summary or a Peer Review file cannot
    describe a cell type. The list lives in
    :mod:`atlas_chat.services.supplement_triage`, which owns what counts as
    relevant; this is the same judgement applied earlier, where it saves a
    download rather than an inspection.
    """
    from atlas_chat.services.supplement_triage import classify_caption

    return classify_caption(entry) is not None


# ------------------------------------------------------------------
# Route: publisher-direct
# ------------------------------------------------------------------


def springer_url(doi: str, filename: str) -> str | None:
    """Springer Nature's static host, which serves ESM files individually.

    Worth having even though the bundle needs no templates: Springer articles
    are the bulk of most corpora, and this fetches one 122 KB workbook where the
    bundle would fetch everything around it.
    """
    if not doi.startswith("10.1038/"):
        return None
    quoted = urllib.parse.quote(f"art:{doi}", safe="")
    return f"https://static-content.springer.com/esm/{quoted}/MediaObjects/{filename}"


def springer_esm_stem(doi: str) -> str | None:
    """The ESM filename stem implied by a Springer DOI.

    ``10.1038/s41586-024-08002-x`` -> ``41586_2024_8002_``. The DOI carries a
    three-digit year and a zero-padded article number, both of which the
    filename renders differently; verified against 8 of 8 Springer papers in the
    reproductive-atlas corpus. Only needed when the article XML is unavailable
    and filenames must be guessed rather than read.
    """
    match = re.match(r"10\.1038/s(\d+)-(\d{3})-(\d+)-", doi)
    if not match:
        return None
    journal, year, article = match.groups()
    return f"{journal}_2{year}_{int(article)}_"


#: DOI prefix -> URL builder. Add a publisher when a corpus needs one; the
#: bundle route covers most cases without any of this.
PUBLISHER_URL_BUILDERS = {"10.1038": springer_url}


def publisher_direct_url(doi: str, filename: str) -> str | None:
    """URL for one supplement on its publisher's host, if we know the shape."""
    builder = PUBLISHER_URL_BUILDERS.get(doi.split("/")[0])
    return builder(doi, filename) if builder else None


def fetch_one_file(client: httpx.Client, url: str, dest: Path) -> tuple[bool, str]:
    """Download one file. Returns ``(ok, note)``."""
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                for chunk in resp.iter_bytes(1 << 20):
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


# ------------------------------------------------------------------
# Route: bioRxiv
# ------------------------------------------------------------------

BIORXIV_CONTENT = "https://www.biorxiv.org/content"

#: One supplement's markup on the page. Splitting on the container class rather
#: than matching a nested structure keeps the parse tolerant of the surrounding
#: page changing around it.
BIORXIV_ENTRY_MARKER = "supplementary-material-expansion"
BIORXIV_LINK = re.compile(r'href="([^"]+/embed/[^"?]+)[^"]*"')
BIORXIV_LABEL = re.compile(r'supplementary-material-label"[^>]*>([^<]+)<')


def biorxiv_get(url: str) -> tuple[bytes | None, str]:
    """GET one URL from bioRxiv, which serves nothing to an ordinary client.

    The site is behind a bot filter that answers a plain HTTP request with a
    challenge page rather than an error, so the request has to present a
    browser's TLS fingerprint — the same approach, and the same optional
    dependency, as fetching a preprint's JATS.

    Returns:
        ``(payload, note)``; the note says what went wrong when payload is None.
    """
    try:
        from curl_cffi import requests as cf_requests  # type: ignore[import-not-found]
    except ImportError:
        return None, "curl_cffi not installed (uv sync --extra text-access)"
    try:
        resp = cf_requests.get(url, impersonate="chrome120", timeout=180)
    except Exception as exc:  # curl_cffi raises its own error hierarchy
        return None, f"{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    return resp.content, "ok"


def parse_supplement_page(page: str) -> list[dict[str, Any]]:
    """Read the file list off a bioRxiv supplementary-material page.

    Returns:
        Manifest ``files`` entries with ``status: "listed"``, each carrying the
        download URL the page gave for it, since it encodes a posting date that
        cannot be derived from the DOI.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in page.split(BIORXIV_ENTRY_MARKER)[1:]:
        link = BIORXIV_LINK.search(chunk)
        if not link:
            continue
        url = unescape(link.group(1))
        file_id = url.rsplit("/", 1)[-1]
        if file_id in seen:
            continue
        seen.add(file_id)
        entry: dict[str, Any] = {
            "file_id": file_id,
            "media_type": media_type(file_id),
            "status": "listed",
            "retrieval": {"route": "biorxiv", "url": url},
        }
        label = BIORXIV_LABEL.search(chunk)
        if label:
            entry["label"] = unescape(label.group(1)).strip()
        out.append(entry)
    return out


def biorxiv_listing(doi: str) -> list[dict[str, Any]]:
    """List a bioRxiv preprint's supplements, if the DOI is one.

    bioRxiv has issued more than one DOI prefix, so being a preprint is not
    something the DOI can be pattern-matched for: the test is whether bioRxiv's
    own metadata service knows the paper. It also supplies the version number,
    which the content URL needs.

    Returns:
        Manifest ``files`` entries, empty for a paper bioRxiv does not host or
        whose page could not be read.
    """
    meta = biorxiv_metadata(doi)
    if not meta:
        return []
    version = meta.get("version") or "1"
    url = f"{BIORXIV_CONTENT}/{doi}v{version}.supplementary-material"
    payload, note = biorxiv_get(url)
    if payload is None:
        logger.info("%s: bioRxiv supplement page unreadable — %s", doi, note)
        return []
    listed = parse_supplement_page(payload.decode("utf-8", errors="replace"))
    logger.info("%s: bioRxiv lists %d supplementary file(s)", doi, len(listed))
    return listed


# ------------------------------------------------------------------
# The negative cache
# ------------------------------------------------------------------


def should_attempt(entry: dict[str, Any], retry: bool) -> bool:
    """Whether to try fetching this file now.

    A file already on disk is never re-fetched. A file whose routes were tried
    and failed is not retried either, unless asked — that is what keeps a
    permanently missing supplement from being requested on every run. Passing
    ``retry`` ignores the cache, which is what you want after a publisher fixes
    a broken link or a paper goes open access.
    """
    if entry.get("status") == "present":
        return False
    if retry:
        return True
    return not entry.get("retrieval", {}).get("attempted_at")


# ------------------------------------------------------------------
# The waterfall
# ------------------------------------------------------------------


def fetch_supplements(
    store_root: Path,
    doi: str,
    bundle_cap: int = DEFAULT_BUNDLE_CAP_BYTES,
    use_bundle: bool = True,
    retry: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Retrieve what can be retrieved for one paper, and record the rest.

    Walks the routes in the module docstring's order, writing every outcome into
    the paper's manifest: bytes on disk with the route that produced them, or a
    status and a ``gaps`` entry saying what a human would have to do. It never
    raises for an unreachable paper — being unable to fetch a closed-access
    supplement is an expected result, not an error.

    Args:
        store_root: Store root; the paper's directory is created under it.
        doi: Paper to fetch for.
        bundle_cap: Byte ceiling on the Europe PMC bundle.
        use_bundle: Set False to skip the bundle route entirely (useful when you
            know the article is one of the video-carrying outliers).
        retry: Ignore the negative cache and try previously failed files again.
        client: An open httpx client, for callers batching many papers.

    Returns:
        The manifest, written to disk.
    """
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=TIMEOUT)
    try:
        return _fetch(store_root, doi, bundle_cap, use_bundle, retry, client)
    finally:
        if owns_client:
            client.close()


def _fetch(
    store_root: Path,
    doi: str,
    bundle_cap: int,
    use_bundle: bool,
    retry: bool,
    client: httpx.Client,
) -> dict[str, Any]:
    manifest = load_manifest(store_root, doi) or {
        "manifest_version": MANIFEST_VERSION,
        "paper": {"doi": doi},
        "files": [],
    }
    # Gaps carry over between runs, so they are deduplicated on write and any
    # gap about a file we have since retrieved is retired. A marker field would
    # be cleaner but the schema (rightly) rejects unknown keys.
    prior_gaps: list[dict[str, Any]] = list(manifest.get("gaps", []))
    gaps: list[dict[str, Any]] = []
    bundle_failure: str | None = None

    pmcid, _title = resolve_pmcid(client, doi)
    if pmcid:
        manifest["paper"]["pmcid"] = pmcid

    # --- route 1: the article XML, for filenames and captions ---------
    listed: list[dict[str, Any]] = []
    if pmcid:
        jats = fetch_jats(client, pmcid, paper_dir(store_root, doi) / "source" / "paper.jats.xml")
        if jats is not None:
            listed = inventory_from_jats(jats)
        else:
            gaps.append(
                {
                    "file_id": doi,
                    "reason": (
                        f"Europe PMC has {pmcid} but serves no article XML, so the "
                        "publisher's supplement filenames and captions are unavailable"
                    ),
                    "action": "drop the supplements into incoming/ and run adopt",
                }
            )
    else:
        # No PMC record, so the listing has to come from wherever the paper
        # itself is published. For a preprint that is the preprint server.
        listed = biorxiv_listing(doi)
        if not listed:
            gaps.append(
                {
                    "file_id": doi,
                    "reason": "no PMC record in Europe PMC, so no programmatic route exists",
                    "action": f"download from https://doi.org/{doi} into incoming/ and run adopt",
                }
            )

    if listed:
        manifest["files"] = _merge_files(manifest.get("files", []), listed)

    skipped = 0
    for entry in manifest.get("files", []):
        if entry.get("status") == "listed" and is_non_evidence(entry):
            entry["status"] = "skipped"
            entry["retrieval"] = {
                "route": "none",
                "note": "publishing artefact by its own caption, not evidence",
            }
            entry["relevance"] = "irrelevant"
            entry["relevance_note"] = f"caption: {entry.get('caption') or entry.get('label')}"
            skipped += 1
    if skipped:
        logger.info("%s: skipping %d process artefact(s)", doi, skipped)

    wanted = [
        entry
        for entry in manifest.get("files", [])
        if should_attempt(entry, retry)
        and entry.get("status") != "skipped"
        and media_type(entry["file_id"]) != "video"
    ]
    logger.info("%s: %d file(s) to fetch", doi, len(wanted))

    # --- route 2: the bundle ------------------------------------------
    # Try it when there are files to get, and *also* when the article XML gave us
    # no listing at all: a paper with no open full text can still have open
    # supplements, and the bundle is the only way to find out. Without this the
    # unlisted-adoption path below is unreachable.
    if pmcid and use_bundle and (wanted or not listed):
        result = fetch_bundle(client, pmcid, cap=bundle_cap)
        if result.archive is not None:
            with result.archive as archive:
                members = {Path(info.filename).name: info for info in archive.infolist()}
                for entry in wanted:
                    info = members.get(entry["file_id"])
                    if info is None or _is_figure(info.filename):
                        continue
                    dest = files_dir(store_root, doi) / entry["file_id"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, dest.open("wb") as out:
                        out.write(src.read())
                    ok, note = verify_payload(dest, media_type(entry["file_id"]))
                    if not ok:
                        # Leave it for the next route rather than storing bytes
                        # nothing can open.
                        logger.warning("  %s from bundle: %s", entry["file_id"], note)
                        dest.unlink(missing_ok=True)
                        entry["retrieval"] = {
                            "route": "europepmc_bundle",
                            "attempted_at": _now(),
                            "note": note,
                        }
                        continue
                    _mark_present(entry, store_root, doi, dest, "europepmc_bundle", url=None)
                # Files in the bundle the article XML never mentioned: keep them,
                # since a supplement absent from the listing is still a supplement.
                if not listed:
                    _adopt_unlisted(archive, members, manifest, store_root, doi)
        else:
            logger.info("%s: bundle unusable — %s", doi, result.reason)
            # Held rather than recorded now: if a later route gets the files, the
            # bundle's failure is a detail of how, not a gap in what we have.
            bundle_failure = result.reason

    # --- route 3: publisher-direct ------------------------------------
    for entry in wanted:
        if entry.get("status") == "present":
            continue
        url = publisher_direct_url(doi, entry["file_id"])
        if url is None:
            continue
        dest = files_dir(store_root, doi) / entry["file_id"]
        ok, note = fetch_one_file(client, url, dest)
        if ok:
            ok, note = verify_payload(dest, media_type(entry["file_id"]))
        if ok:
            _mark_present(entry, store_root, doi, dest, "publisher_direct", url=url)
        else:
            dest.unlink(missing_ok=True)
            entry["status"] = "failed"
            entry["retrieval"] = {
                "route": "publisher_direct",
                "url": url,
                "attempted_at": _now(),
                "note": note,
            }

    # --- route 4: the preprint server ---------------------------------
    for entry in wanted:
        if entry.get("status") == "present":
            continue
        retrieval = entry.get("retrieval", {})
        if retrieval.get("route") != "biorxiv":
            continue
        url = retrieval.get("url")
        dest = files_dir(store_root, doi) / entry["file_id"]
        payload, note = biorxiv_get(url)
        if payload is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            ok, note = verify_payload(dest, media_type(entry["file_id"]))
        else:
            ok = False
        if ok:
            _mark_present(entry, store_root, doi, dest, "biorxiv", url=url)
        else:
            dest.unlink(missing_ok=True)
            entry["status"] = "failed"
            entry["retrieval"] = {
                "route": "biorxiv",
                "url": url,
                "attempted_at": _now(),
                "note": note,
            }

    # --- route 5: nothing left but a person --------------------------
    for entry in wanted:
        if entry.get("status") == "present":
            continue
        if entry.get("status") != "failed":
            entry["status"] = "unavailable"
            entry["retrieval"] = {
                "route": "none",
                "attempted_at": _now(),
                "note": "no route reached this file",
            }
        gaps.append(
            {
                "file_id": entry["file_id"],
                "reason": f"not retrieved: {entry['retrieval'].get('note', 'no route')}",
                "action": "drop it into incoming/ and run adopt",
            }
        )

    still_missing = [f for f in manifest.get("files", []) if f.get("status") != "present"]
    if bundle_failure and (still_missing or not manifest.get("files")):
        gaps.append(
            {
                "file_id": doi,
                "reason": bundle_failure,
                "action": "add a publisher-direct template, or drop the files into incoming/",
            }
        )

    retrieved = {f["file_id"] for f in manifest.get("files", []) if f.get("status") == "present"}
    kept = [gap for gap in prior_gaps if gap.get("file_id") not in retrieved]
    manifest["gaps"] = _dedupe_gaps(kept + gaps)
    write_manifest(store_root, doi, manifest)
    present = sum(1 for f in manifest["files"] if f.get("status") == "present")
    logger.info("%s: %d/%d file(s) present", doi, present, len(manifest["files"]))
    return manifest


def _mark_present(
    entry: dict[str, Any],
    store_root: Path,
    doi: str,
    dest: Path,
    route: str,
    url: str | None,
) -> None:
    entry.update(
        {
            "media_type": media_type(entry["file_id"]),
            "size_bytes": dest.stat().st_size,
            "path": _rel(store_root, dest),
            "status": "present",
            "retrieval": {
                "route": route,
                "retrieved_at": _now(),
                "sha256": _sha256(dest),
            },
        }
    )
    if url:
        entry["retrieval"]["url"] = url
    logger.info("  %s via %s (%d bytes)", entry["file_id"], route, entry["size_bytes"])


def _adopt_unlisted(
    archive: zipfile.ZipFile,
    members: dict[str, Any],
    manifest: dict[str, Any],
    store_root: Path,
    doi: str,
) -> None:
    """Take bundle members when the article XML gave us no listing to match.

    Without the XML there are no captions and no filenames, so the bundle is all
    we have. Figures are skipped; everything else is stored under the name the
    bundle used.
    """
    extra: list[dict[str, Any]] = []
    for name, info in members.items():
        if _is_figure(name):
            continue
        dest = files_dir(store_root, doi) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, dest.open("wb") as out:
            out.write(src.read())
        entry: dict[str, Any] = {"file_id": name, "status": "listed"}
        _mark_present(entry, store_root, doi, dest, "europepmc_bundle", url=None)
        extra.append(entry)
    if extra:
        manifest["files"] = _merge_files(manifest.get("files", []), extra)


def fetch_corpus(
    store_root: Path,
    cas: dict[str, Any],
    bundle_cap: int = DEFAULT_BUNDLE_CAP_BYTES,
    use_bundle: bool = True,
    retry: bool = False,
) -> list[dict[str, Any]]:
    """Fetch supplements for every paper a CAS+ document names.

    One client is shared across the corpus. A paper that cannot be fetched does
    not stop the others: the failure lands in that paper's manifest.
    """
    from atlas_chat.services.supplement_store import corpus_papers

    papers = corpus_papers(cas)
    out: list[dict[str, Any]] = []
    with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
        for paper in papers:
            try:
                manifest = fetch_supplements(
                    store_root,
                    paper["doi"],
                    bundle_cap=bundle_cap,
                    use_bundle=use_bundle,
                    retry=retry,
                    client=client,
                )
                files = manifest.get("files", [])
                counted = Counter(f.get("status", "?") for f in files)
                out.append(
                    {
                        "doi": paper["doi"],
                        "role": paper.get("role"),
                        "files": len(files),
                        "present": counted["present"],
                        # Deliberately skipped is not a shortfall: counting it as
                        # one makes a paper whose only miss was a peer-review PDF
                        # look incomplete.
                        "skipped": counted["skipped"],
                        "missing": counted["failed"] + counted["unavailable"] + counted["listed"],
                        "gaps": len(manifest.get("gaps", [])),
                    }
                )
            except (httpx.HTTPError, SupplementStoreError, SupplementFetchError) as exc:
                logger.warning("%s: %s", paper["doi"], exc)
                out.append({"doi": paper["doi"], "error": f"{type(exc).__name__}: {exc}"})
    return out
