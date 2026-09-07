"""Route a paper to the best available text source: local JATS, fetch, or ASTA.

One waterfall for every node in a literature traversal — the seed paper and every
followed citation alike:

1. **Local cache** — ``{project}/local_index/papers/<slug>/source/paper.jats.xml``
   (the same layout ``local_snippet_index.build_paper_index`` writes, so anything
   the router fetches is reusable by a later index build, and vice versa).
2. **Europe PMC** — raw ``fullTextXML`` for papers with a PMCID.
3. **Preprint fetch** — ``fetch_preprint`` for bioRxiv-shaped sources.
4. **ASTA** — snippet access only, gated on the indexing band from
   ``asta_indexing`` (``full`` / ``partial`` are servable; the rest are not).
5. **Unreachable** — recorded with the reason, never silently dropped.

The ordering is evidence-based (see ``planning/retrieval_architecture_decision``
on the ``dev`` branch): JATS full text has none of ASTA's coverage gaps
(introductions, figure captions, rendering drift), so whenever we can hold the
text we use it; ASTA is the fallback, not the default.

The module also owns the per-run **seen-set** (``traversed.json``): one paper must
be processed once per run regardless of which route serves it and regardless of
whether one hop knows it by DOI and another by CorpusId.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Route methods
JATS = "jats"
ASTA = "asta"
UNREACHABLE = "unreachable"

# ASTA bands that can actually serve body text (see services.asta_indexing)
_SERVABLE_BANDS = {"full", "partial"}

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


@dataclass
class Route:
    """Where a paper's text comes from, and why."""

    paper_id: str  # the identifier as given (DOI:..., CorpusId:..., or bare DOI)
    doi: str | None
    method: str  # "jats" | "asta" | "unreachable"
    source: str | None = None  # "cache" | "europepmc" | "preprint" (jats only)
    cache_path: str | None = None  # paper.jats.xml path when method == "jats"
    band: str | None = None  # ASTA indexing band, when probed
    reason: str | None = None  # detail for "unreachable" / probe failures

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_id(paper_id: str) -> tuple[str | None, str | None]:
    """Split an identifier into ``(doi, corpus_id)`` — at most one is non-None.

    Accepts ``DOI:10.x/...``, a bare DOI, or ``CorpusId:NNNN``.
    """
    pid = paper_id.strip()
    if pid.lower().startswith("doi:"):
        return pid[4:].strip(), None
    if pid.lower().startswith("corpusid:"):
        return None, "CorpusId:" + pid.split(":", 1)[1].strip()
    if _DOI_RE.match(pid):
        return pid, None
    return None, None


def canonical_key(paper_id: str) -> str:
    """The seen-set key: lowercase DOI when one exists, else the id verbatim."""
    doi, corpus_id = normalize_id(paper_id)
    if doi:
        return doi.lower()
    return corpus_id or paper_id.strip()


def _source_dir(project_dir: Path, doi: str) -> Path:
    from atlas_chat.services.local_snippet_index import paper_slug

    return project_dir / "local_index" / "papers" / paper_slug(doi) / "source"


def _cached_jats(project_dir: Path, doi: str) -> Path | None:
    path = _source_dir(project_dir, doi) / "paper.jats.xml"
    return path if path.exists() and path.stat().st_size > 0 else None


def _fetch_europepmc_xml(doi: str) -> str | None:
    """Raw JATS ``fullTextXML`` from Europe PMC, or None.

    Unlike ``europepmc.get_full_text`` this keeps the markup — the citation
    parser and legend extraction need the XML, not stripped prose.
    """
    import httpx

    from atlas_chat.services.europepmc import BASE_URL, resolve_identifiers

    ids = resolve_identifiers(doi)
    if not ids.pmcid:
        return None
    url = f"{BASE_URL}/{ids.pmcid}/fullTextXML"
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(url)
    except Exception as exc:  # network failure is a routing outcome, not a crash
        logger.warning("EuropePMC fullTextXML fetch failed for %s: %s", doi, exc)
        return None
    if resp.status_code != 200 or not resp.text.strip():
        return None
    # A JATS body is what makes the route useful; an abstract-only or error
    # payload should fall through to the next rung.
    if "<body" not in resp.text:
        logger.info("EuropePMC XML for %s has no <body>; treating as unavailable", doi)
        return None
    return resp.text


def _try_preprint(doi: str, dest_dir: Path) -> Path | None:
    from atlas_chat.services.fetch_preprint import PreprintFetchError, fetch_preprint

    try:
        fetched = fetch_preprint(doi, dest_dir)
    except PreprintFetchError as exc:
        logger.info("Preprint fetch failed for %s: %s", doi, exc)
        return None
    except Exception as exc:
        logger.warning("Preprint fetch errored for %s: %s", doi, exc)
        return None
    return fetched.jats_path


def _probe_band(paper_id: str, project_dir: Path | None) -> tuple[str | None, str | None]:
    """ASTA indexing band for the paper, using the project cache when possible.

    Returns ``(band, error)``.
    """
    import asyncio

    from atlas_chat.services import asta_indexing

    try:
        report = asyncio.run(asta_indexing.probe_cached(paper_id, project_dir=project_dir))
    except Exception as exc:
        logger.warning("ASTA probe failed for %s: %s", paper_id, exc)
        return None, str(exc)
    return report.band, None


def resolve_route(
    paper_id: str,
    project_dir: Path | str | None = None,
    *,
    fetch: bool = True,
    probe_asta: bool = True,
) -> Route:
    """Decide how to read one paper, fetching JATS to the project cache en route.

    Args:
        paper_id: ``DOI:...``, bare DOI, or ``CorpusId:NNNN``.
        project_dir: project root (for the JATS cache and the ASTA band cache).
            Without it, only the fetch-to-nowhere rungs are skipped and the
            probe is uncached.
        fetch: when False, only the cache and probe rungs run (no network fetch
            of full text) — used by callers that just need to know the route.
        probe_asta: when False, skip the ASTA rung entirely.
    """
    project = Path(project_dir) if project_dir is not None else None
    doi, corpus_id = normalize_id(paper_id)

    if doi is None and corpus_id is None:
        return Route(paper_id=paper_id, doi=None, method=UNREACHABLE, reason="unparseable id")

    # Rung 1-3 need a DOI (JATS is fetched by DOI/PMCID); CorpusId-only papers
    # go straight to the ASTA rung.
    if doi is not None:
        if project is not None:
            cached = _cached_jats(project, doi)
            if cached:
                return Route(paper_id, doi, JATS, source="cache", cache_path=str(cached))

        if fetch:
            xml = _fetch_europepmc_xml(doi)
            if xml is not None:
                if project is not None:
                    dest = _source_dir(project, doi)
                    dest.mkdir(parents=True, exist_ok=True)
                    path = dest / "paper.jats.xml"
                    path.write_text(xml)
                    return Route(paper_id, doi, JATS, source="europepmc", cache_path=str(path))
                # No project to cache into: still a JATS route, caller gets the
                # text via a temp write by the CLI layer.
                return Route(paper_id, doi, JATS, source="europepmc")

            if project is not None:
                dest = _source_dir(project, doi)
                dest.mkdir(parents=True, exist_ok=True)
                jats_path = _try_preprint(doi, dest)
                if jats_path is not None:
                    return Route(paper_id, doi, JATS, source="preprint", cache_path=str(jats_path))

    if probe_asta:
        probe_id = f"DOI:{doi}" if doi else (corpus_id or paper_id)
        band, err = _probe_band(probe_id, project)
        if band in _SERVABLE_BANDS:
            return Route(paper_id, doi, ASTA, band=band)
        reason = f"asta band: {band}" if band else f"asta probe failed: {err}"
        return Route(paper_id, doi, UNREACHABLE, band=band, reason=reason)

    return Route(paper_id, doi, UNREACHABLE, reason="no JATS route; ASTA probe skipped")


# ---------------------------------------------------------------------------
# Per-run seen-set
# ---------------------------------------------------------------------------


def load_traversed(path: Path | str) -> dict[str, dict[str, Any]]:
    """Load the run's seen-set (``{}`` when absent or unreadable)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("traversed.json unreadable at %s; treating as empty", p)
        return {}
    return data if isinstance(data, dict) else {}


def is_traversed(path: Path | str, paper_id: str) -> bool:
    return canonical_key(paper_id) in load_traversed(path)


def mark_traversed(path: Path | str, paper_id: str, info: dict[str, Any] | None = None) -> None:
    """Record a paper as processed this run (idempotent; merges ``info``)."""
    p = Path(path)
    data = load_traversed(p)
    key = canonical_key(paper_id)
    entry = data.get(key, {})
    entry.update(info or {})
    entry.setdefault("paper_id", paper_id)
    data[key] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
