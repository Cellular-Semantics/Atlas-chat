"""Find a quote in the text it claims to come from.

An evidence item asserts something and offers quotes as the grounds. The only
way to know a quote is real is to look for it, so nothing here trusts a claim
about where text came from — it searches, and the search reports where the text
was found. That is stronger than asking a writer to name its source, because a
name can be wrong in a way a search cannot.

A paper read produces one job file holding several distinct bodies of text: the
narrative, each figure legend, and each supplementary prose document. They are
kept apart in the job file because they are different kinds of thing, and they
stay apart here, so a quote found in a caption is known to have come from a
caption rather than from the body.

Whitespace is normalised before matching and nothing else is. The sources are
re-wrapped from article XML and from Word, so line breaks differ from the
original while the words do not; anything looser would start accepting text the
author did not write.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: Sections of a job file that hold quotable text, in the order a reader meets them.
NARRATIVE = "narrative"


def normalise(text: str) -> str:
    """Collapse runs of whitespace, so a rewrap does not defeat a match."""
    return re.sub(r"\s+", " ", text).strip()


def sources_from_job(job: dict[str, Any]) -> dict[str, str]:
    """The quotable bodies of text in one job file, keyed by where they came from.

    Args:
        job: a paper ingest object.

    Returns:
        Normalised text per source. Keys are ``narrative``, ``legend:<label>``
        and ``supplement:<file id>``.
    """
    sources: dict[str, str] = {}
    narrative = (job.get("narrative") or {}).get("text")
    if narrative:
        sources[NARRATIVE] = normalise(narrative)
    for index, legend in enumerate(job.get("legends") or []):
        label = legend.get("label") or str(index)
        sources[f"legend:{label}"] = normalise(legend.get("text", ""))
    for item in job.get("supplement_prose") or []:
        name = item.get("file_id") or item.get("text_file") or "supplement"
        sources[f"supplement:{name}"] = normalise(item.get("text", ""))
    return {k: v for k, v in sources.items() if v}


def locate(quote: str, sources: dict[str, str]) -> list[str]:
    """Which sources contain this quote.

    Args:
        quote: the text as recorded.
        sources: as returned by :func:`sources_from_job`.

    Returns:
        The keys of every source containing it — empty when the quote is not in
        any of them, which is the answer that matters.
    """
    needle = normalise(quote)
    if not needle:
        return []
    return [name for name, text in sources.items() if needle in text]


def load_sources(job_paths: list[Path]) -> dict[str, str]:
    """Merge the sources of several job files, prefixing each key with its file."""
    merged: dict[str, str] = {}
    for path in job_paths:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for name, text in sources_from_job(job).items():
            merged[f"{path.stem}/{name}"] = text
    return merged


def check_items(items: list[dict[str, Any]], sources: dict[str, str]) -> list[str]:
    """Report every quote that cannot be found in the supplied text.

    Args:
        items: evidence items, each with a ``quotes`` list.
        sources: as returned by :func:`load_sources`.

    Returns:
        One message per unfindable quote. Empty when every quote was located.
    """
    problems: list[str] = []
    for index, item in enumerate(items):
        for quote in item.get("quotes") or []:
            if not locate(quote, sources):
                excerpt = normalise(quote)[:120]
                problems.append(f"[{index}] quote not found in any source: {excerpt!r}")
    return problems
