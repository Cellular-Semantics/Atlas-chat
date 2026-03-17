"""Citation traversal via ASTA (Semantic Scholar) snippet search.

Uses ``deep_research_client.providers.asta.AstaProvider`` to search for
relevant snippets, then follows citations to the configured depth.

This is the programmatic equivalent of the citation-traverse Claude Code skill.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from deep_research_client.models import ProviderConfig
from deep_research_client.providers.asta import AstaProvider, AstaPaper, AstaSnippet

logger = logging.getLogger(__name__)

ASTA_FIELDS = "title,authors,abstract,year,venue,url,publicationDate,tldr,journal"


def _make_provider() -> AstaProvider:
    """Create an AstaProvider with the ASTA_API_KEY from environment."""
    api_key = os.getenv("ASTA_API_KEY", "")
    if not api_key:
        raise ValueError("ASTA_API_KEY not set in environment")

    config = ProviderConfig(
        name="asta",
        api_key=api_key,
        enabled=True,
    )
    return AstaProvider(config, None)


def _snippet_to_dict(s: AstaSnippet) -> dict[str, Any]:
    """Convert an AstaSnippet to a serializable dict."""
    return {
        "snippet": s.snippet,
        "paper_id": s.paper_id,
        "title": s.title,
        "authors": s.authors,
        "year": s.year,
        "url": s.url,
        "score": s.score,
    }


def _paper_to_catalogue_entry(p: AstaPaper) -> dict[str, Any]:
    """Convert an AstaPaper to a paper catalogue entry."""
    return {
        "title": p.title,
        "authors": p.authors,
        "year": p.year,
        "venue": p.venue or p.journal,
        "doi": p.doi,
        "pmid": p.pmid,
        "url": p.url,
        "abstract": p.abstract[:500] if p.abstract else "",
        "tldr": p.tldr,
    }


async def _search_depth(
    provider: AstaProvider,
    query: str,
    seed_ids: list[str],
    depth: int,
    max_snippets_per_depth: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Run snippet search at increasing depth.

    Depth 0: search with the query directly.
    Depth 1+: search within papers that cited the depth-0 results.

    Returns:
        (all_summaries, paper_catalogue) where all_summaries is a list of
        snippet dicts and paper_catalogue maps CorpusId → paper metadata.
    """
    import httpx

    all_snippets: list[dict[str, Any]] = []
    catalogue: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=180) as http_client:
        # Depth 0: direct snippet search
        logger.info("Depth 0: snippet search for query: %s", query[:100])
        try:
            snippets_0 = await provider._search_snippets(http_client, query, [])
        except Exception as exc:
            logger.warning("Snippet search failed: %s", exc)
            snippets_0 = []

        # Collect paper IDs from depth-0 snippets
        paper_ids_0 = list({s.paper_id for s in snippets_0 if s.paper_id})

        # Fetch paper metadata — builds catalogue and paperId→CorpusId map
        if paper_ids_0:
            try:
                raw = await provider._call_tool(http_client, "get_paper_batch", {
                    "ids": paper_ids_0[:50],
                    "fields": f"{ASTA_FIELDS},externalIds",
                })
                papers_list = raw.get("result", raw) if isinstance(raw, dict) else raw
                if isinstance(papers_list, list):
                    for p_data in papers_list:
                        if not p_data or not isinstance(p_data, dict):
                            continue
                        ext_ids = p_data.get("externalIds") or {}
                        corpus_id = str(ext_ids.get("CorpusId", ""))
                        paper_id = p_data.get("paperId", "")
                        key = f"CorpusId:{corpus_id}" if corpus_id else paper_id

                        authors = [
                            a.get("name", "")
                            for a in (p_data.get("authors") or [])
                        ]
                        catalogue[key] = {
                            "title": p_data.get("title", ""),
                            "authors": authors,
                            "year": p_data.get("year"),
                            "venue": p_data.get("venue", ""),
                            "doi": ext_ids.get("DOI", ""),
                            "pmid": ext_ids.get("PubMed", ""),
                            "url": p_data.get("url", ""),
                            "abstract": (p_data.get("abstract") or "")[:500],
                            "tldr": (p_data.get("tldr") or {}).get("text", ""),
                        }
                logger.info("Fetched metadata for %d papers", len(catalogue))
            except Exception as exc:
                logger.warning("Paper batch fetch failed: %s", exc)

        # Now build snippet dicts with CorpusId references.
        # ASTA snippet paper_ids ARE CorpusIds (numeric strings).
        for s in snippets_0:
            d = _snippet_to_dict(s)
            d["depth"] = 0
            d["corpus_id"] = f"CorpusId:{s.paper_id}" if s.paper_id else ""
            all_snippets.append(d)

        # Depth 1+: broader search
        if depth >= 1 and paper_ids_0:
            logger.info("Depth 1: broader snippet search")
            try:
                # Broaden query slightly for depth 1
                broad_query = query.split(":")[0]  # drop the "location, structure..." suffix
                snippets_1 = await provider._search_snippets(
                    http_client, broad_query, []
                )
                for s in snippets_1:
                    d = _snippet_to_dict(s)
                    d["depth"] = 1
                    d["corpus_id"] = f"CorpusId:{s.paper_id}" if s.paper_id else ""
                    # Avoid duplicates
                    if not any(
                        existing["snippet"] == d["snippet"]
                        for existing in all_snippets
                    ):
                        all_snippets.append(d)
            except Exception as exc:
                logger.warning("Depth 1 snippet search failed: %s", exc)

    logger.info(
        "Traversal complete: %d snippets, %d papers in catalogue",
        len(all_snippets),
        len(catalogue),
    )
    return all_snippets, catalogue


async def traverse(
    query: str,
    seed_ids: list[str],
    depth: int = 1,
    output_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Async entry point for citation traversal.

    Args:
        query: Search query (e.g. "Iron-recycling macrophage fetal skin").
        seed_ids: Seed paper IDs (CorpusId or DOI format).
        depth: Traversal depth (0 = snippets only, 1 = +citations).
        output_dir: Optional directory to save intermediate results.

    Returns:
        (all_summaries, paper_catalogue) tuple.
    """
    provider = _make_provider()
    return await _search_depth(provider, query, seed_ids, depth)
