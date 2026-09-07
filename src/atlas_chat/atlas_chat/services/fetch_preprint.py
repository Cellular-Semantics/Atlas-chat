"""Resolve a DOI to a local JATS XML file for fresh preprints.

Tries three paths in order: EuropePMC full text → bioRxiv JATS via curl_cffi
(Cloudflare-friendly TLS impersonation) → Playwright fallback. Returns a
FetchedPreprint dataclass identifying the source used.

This sits in front of the local snippet index (services/local_snippet_index.py)
so the rest of the pipeline doesn't care how the JATS arrived.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"


class PreprintFetchError(RuntimeError):
    """Raised when every fetch path fails. Carries which paths were tried."""

    def __init__(self, doi: str, attempts: list[tuple[str, str]]):
        self.doi = doi
        self.attempts = attempts
        msg = f"Could not fetch JATS for {doi}. Attempts:\n" + "\n".join(
            f"  - {src}: {reason}" for src, reason in attempts
        )
        super().__init__(msg)


@dataclass
class FetchedPreprint:
    doi: str
    jats_path: Path
    source_used: str  # "europepmc" | "biorxiv_curlcffi" | "biorxiv_playwright"
    title: str | None = None
    authors: str | None = None
    year: int | None = None


# ------------------------------------------------------------------
# Path 1: EuropePMC
# ------------------------------------------------------------------


def _try_europepmc(doi: str, out_path: Path) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{EUROPEPMC_BASE}/search",
                params={
                    "query": f'DOI:"{doi}"',
                    "format": "json",
                    "pageSize": 1,
                    "resultType": "core",
                },
            )
            resp.raise_for_status()
            results = resp.json().get("resultList", {}).get("result", [])
            if not results:
                return False, "DOI not found in EuropePMC search"
            pmcid = results[0].get("pmcid")
            if not pmcid:
                return False, "no PMCID in EuropePMC record"
            xml_resp = client.get(f"{EUROPEPMC_BASE}/{pmcid}/fullTextXML", timeout=60)
            if xml_resp.status_code != 200:
                return False, f"fullTextXML returned {xml_resp.status_code}"
            out_path.write_text(xml_resp.text)
            return True, f"fetched from EuropePMC PMC {pmcid}"
    except Exception as exc:
        return False, f"exception: {exc}"


# ------------------------------------------------------------------
# Path 2: bioRxiv API → JATS URL → curl_cffi
# ------------------------------------------------------------------


def _biorxiv_metadata(doi: str) -> dict | None:
    """Hit api.biorxiv.org/details (no CF) for the JATS URL + metadata."""
    url = f"{BIORXIV_API}/{doi}/na/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as fh:
            data = json.load(fh)
        if data.get("messages", [{}])[0].get("status") != "ok":
            return None
        coll = data.get("collection", [])
        return coll[0] if coll else None
    except Exception as exc:
        logger.warning("biorxiv metadata fetch failed: %s", exc)
        return None


def _normalize_jats_url(url: str) -> str:
    """bioRxiv's API sometimes returns paths with a doubled slash (e.g.
    `early/2026/03/23//2026.03.20.713219.source.xml`). Highwire returns 404
    for those literal paths but accepts the collapsed form."""
    scheme, _, rest = url.partition("://")
    return scheme + "://" + re.sub(r"/{2,}", "/", rest)


def _try_biorxiv_curlcffi(meta: dict, out_path: Path) -> tuple[bool, str]:
    jats_url = meta.get("jatsxml")
    if not jats_url:
        return False, "no jatsxml URL in bioRxiv metadata"
    jats_url = _normalize_jats_url(jats_url)
    try:
        from curl_cffi import requests as cf_requests  # type: ignore[import-not-found]
    except ImportError:
        return False, "curl_cffi not installed (uv sync --extra text-access)"
    try:
        resp = cf_requests.get(jats_url, impersonate="chrome120", timeout=60)
        if resp.status_code != 200:
            return False, f"jatsxml returned {resp.status_code}"
        text = resp.text
        if "<article" not in text[:2000]:
            return False, "response is not a JATS article (likely CF challenge)"
        out_path.write_text(text)
        return True, "fetched via curl_cffi (chrome120 impersonation)"
    except Exception as exc:
        return False, f"curl_cffi exception: {exc}"


# ------------------------------------------------------------------
# Path 3: Playwright fallback
# ------------------------------------------------------------------


def _try_playwright(meta: dict, out_path: Path) -> tuple[bool, str]:
    jats_url = meta.get("jatsxml")
    if not jats_url:
        return False, "no jatsxml URL"
    jats_url = _normalize_jats_url(jats_url)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        return False, "playwright not installed"
    try:
        # Need to navigate to a biorxiv page first to get CF cookies, then
        # use the in-browser fetch with credentials.
        doi = meta.get("doi", "")
        seed_url = f"https://www.biorxiv.org/content/{doi}v{meta.get('version', 1)}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(seed_url, timeout=30000)
            text = page.evaluate(
                "async (url) => {"
                " const r = await fetch(url, {credentials: 'include'});"
                " return r.ok ? await r.text() : null;"
                "}",
                jats_url,
            )
            browser.close()
        if not text or "<article" not in text[:2000]:
            return False, "Playwright fetched but content not a JATS article"
        out_path.write_text(text)
        return True, "fetched via Playwright fallback"
    except Exception as exc:
        return False, f"Playwright exception: {exc}"


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def fetch_preprint(doi: str, out_dir: Path) -> FetchedPreprint:
    """Fetch JATS XML for a preprint, trying EuropePMC then bioRxiv paths.

    Writes `paper.jats.xml` inside out_dir. Raises PreprintFetchError if
    every path fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    jats_path = out_dir / "paper.jats.xml"
    attempts: list[tuple[str, str]] = []

    # Path 1: EuropePMC
    ok, reason = _try_europepmc(doi, jats_path)
    attempts.append(("europepmc", reason))
    if ok:
        logger.info("fetch_preprint(%s): %s", doi, reason)
        return FetchedPreprint(doi=doi, jats_path=jats_path, source_used="europepmc")

    # Paths 2 + 3 need bioRxiv metadata first
    meta = _biorxiv_metadata(doi)
    if not meta:
        attempts.append(("biorxiv_api", "metadata lookup failed"))
        raise PreprintFetchError(doi, attempts)

    # Path 2: curl_cffi
    ok, reason = _try_biorxiv_curlcffi(meta, jats_path)
    attempts.append(("biorxiv_curlcffi", reason))
    if ok:
        logger.info("fetch_preprint(%s): %s", doi, reason)
        return _populate(doi, jats_path, "biorxiv_curlcffi", meta)

    # Path 3: Playwright
    ok, reason = _try_playwright(meta, jats_path)
    attempts.append(("biorxiv_playwright", reason))
    if ok:
        logger.info("fetch_preprint(%s): %s", doi, reason)
        return _populate(doi, jats_path, "biorxiv_playwright", meta)

    raise PreprintFetchError(doi, attempts)


def _populate(doi: str, jats_path: Path, source: str, meta: dict) -> FetchedPreprint:
    year_match = re.match(r"(\d{4})", meta.get("date", ""))
    return FetchedPreprint(
        doi=doi,
        jats_path=jats_path,
        source_used=source,
        title=meta.get("title"),
        authors=meta.get("authors"),
        year=int(year_match.group(1)) if year_match else None,
    )


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("doi", help="Preprint DOI, e.g. 10.1101/2026.03.20.713219")
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        result = fetch_preprint(args.doi, args.out)
    except PreprintFetchError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), default=str, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
