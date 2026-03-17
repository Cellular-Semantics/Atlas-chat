"""Europe PMC REST API client for the programmatic graph path.

Provides identifier resolution, full text retrieval, and supplementary
material listing — the programmatic equivalents of the artl-mcp MCP tools.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from atlas_chat.services.atlas_paper import PaperIdentifiers

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
TIMEOUT = 30


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronous GET to Europe PMC REST API."""
    url = f"{BASE_URL}/{path}"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------
# Identifier resolution
# ------------------------------------------------------------------

def resolve_identifiers(doi: str) -> PaperIdentifiers:
    """Resolve a DOI to all available identifiers via Europe PMC search.

    Returns:
        PaperIdentifiers with doi, pmid, pmcid, corpus_id fields populated.
    """
    logger.info("Resolving identifiers for DOI: %s", doi)

    data = _get("search", {
        "query": f'DOI:"{doi}"',
        "format": "json",
        "pageSize": 1,
        "resultType": "core",
    })

    results = data.get("resultList", {}).get("result", [])
    if not results:
        logger.warning("No Europe PMC results for DOI: %s", doi)
        return PaperIdentifiers(doi=doi)

    paper = results[0]
    pmid = paper.get("pmid")
    pmcid = paper.get("pmcid")

    ids = PaperIdentifiers(
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
    )
    logger.info("Resolved: pmid=%s pmcid=%s", pmid, pmcid)
    return ids


# ------------------------------------------------------------------
# Full text
# ------------------------------------------------------------------

def get_full_text(doi: str) -> str:
    """Fetch full text of a paper from Europe PMC (if available in PMC OA).

    Falls back to abstract if full text is not available.
    """
    # First resolve to get the source/id for full text retrieval
    ids = resolve_identifiers(doi)

    # Try PMC full text XML endpoint
    if ids.pmcid:
        try:
            url = f"{BASE_URL}/{ids.pmcid}/fullTextXML"
            with httpx.Client(timeout=60) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    # Strip XML tags for a rough text version
                    text = re.sub(r"<[^>]+>", " ", resp.text)
                    text = re.sub(r"\s+", " ", text).strip()
                    logger.info("Got full text for %s (%d chars)", ids.pmcid, len(text))
                    return text
        except Exception as exc:
            logger.warning("Full text fetch failed for %s: %s", ids.pmcid, exc)

    # Fallback: return abstract from search result
    data = _get("search", {
        "query": f'DOI:"{doi}"',
        "format": "json",
        "pageSize": 1,
        "resultType": "core",
    })
    results = data.get("resultList", {}).get("result", [])
    if results:
        abstract = results[0].get("abstractText", "")
        logger.info("Using abstract for DOI %s (%d chars)", doi, len(abstract))
        return abstract

    return ""


# ------------------------------------------------------------------
# Supplementary material
# ------------------------------------------------------------------

def get_supplementary_text(pmcid: str) -> str:
    """Fetch supplementary file listing for a PMC article.

    Uses the Europe PMC supplementary files endpoint.
    Returns a concatenated text summary of available supplements.
    """
    if not pmcid:
        return ""

    logger.info("Fetching supplementary files for %s", pmcid)

    try:
        # Europe PMC supplementary materials endpoint
        url = f"{BASE_URL}/{pmcid}/supplementaryFiles"
        with httpx.Client(timeout=60) as client:
            resp = client.get(url, params={"format": "json"})
            if resp.status_code != 200:
                logger.warning("Supplementary files not available for %s", pmcid)
                return ""

            # Response may be binary/gzipped — handle encoding gracefully
            try:
                data = resp.json()
            except Exception:
                logger.warning("Supplementary response not JSON for %s", pmcid)
                return ""

            files = data.get("supplementaryFiles", {}).get("supplementaryFile", [])
            if not files:
                return ""

            parts = []
            for f in files:
                label = f.get("label", "")
                caption = f.get("caption", "")
                if label or caption:
                    parts.append(f"[{label}] {caption}")

            text = "\n".join(parts)
            logger.info("Found %d supplementary files for %s", len(files), pmcid)
            return text
    except Exception as exc:
        logger.warning("Failed to fetch supplementary files for %s: %s", pmcid, exc)
        return ""
