"""Turn a cached JATS file into a reader job: whole narrative text + citations.

The evidence-reading architecture reads papers **whole** — a retrieved slice tied
whole-paper reading on accuracy in every measurement (Stages 2 and 3b on the
``test/retrieval-matrix`` branch) while carrying a retrieval-miss tail, so within
one paper there is nothing for a ranker to buy. This module prepares everything a
reader subagent needs from one paper, in one deterministic pass:

- **narrative text** — body paragraphs with section headings, via
  ``local_snippet_index.extract_body_segments`` (which carries the #35/#37
  extraction fixes: no legend splicing, document order, non-prose dropped);
- **figure legends** — extracted *separately*, never spliced into prose. Legends
  carry the abbreviation glossaries that resolve cell-type names (Stage 3b: nine
  labels had zero body-prose occurrences and only a Fig. 1 legend expansion);
- **cited sentences** — sentence → reference links with resolved DOIs, via the
  vendored ``_jats_parser``. This is what makes citation traversal from a JATS
  node exact: the follow target is markup, not a search result.

Oversized papers (rare) fall back to a BM25-ranked slice of segments rather than
the whole text; the output records that truncation happened so nothing downstream
mistakes a slice for the paper.
"""

from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Rough chars-per-token used across the retrieval experiments.
_CHARS_PER_TOKEN = 4
DEFAULT_BUDGET_TOKENS = 40_000

# Section titles that are process description, not biology. They stay out of the
# reader's narrative text by default: Methods is ~46% of a Nature atlas paper's
# body and contained no citable cell-type evidence in any measured item set.
_METHODS_TITLES = re.compile(
    r"^(methods?|materials and methods|online methods|star.?methods)", re.I
)


@dataclass
class PaperReading:
    """Everything a reader subagent needs from one paper."""

    doi: str | None
    narrative_text: str  # section-headed paragraphs, Methods excluded
    methods_text: str  # kept separately; available, not default reading
    legends: list[str] = field(default_factory=list)
    cited_sentences: list[dict[str, Any]] = field(default_factory=list)
    ref_lookup: dict[str, dict[str, Any]] = field(default_factory=dict)
    truncated: bool = False  # narrative_text is a ranked slice, not the paper
    n_chars_total: int = 0  # pre-truncation narrative size

    def to_dict(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "narrative_text": self.narrative_text,
            "methods_text": self.methods_text,
            "legends": self.legends,
            "cited_sentences": self.cited_sentences,
            "ref_lookup": self.ref_lookup,
            "truncated": self.truncated,
            "n_chars_total": self.n_chars_total,
        }


def _extract_legends(xml: str) -> list[str]:
    """Figure and table captions, each prefixed with its label where present."""
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", xml, count=1))
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    legends: list[str] = []
    for wrap in root.iter():
        if wrap.tag not in ("fig", "table-wrap"):
            continue
        label_el = wrap.find("label")
        caption_el = wrap.find("caption")
        if caption_el is None:
            continue
        caption = re.sub(r"\s+", " ", " ".join(caption_el.itertext())).strip()
        if not caption:
            continue
        label = (
            re.sub(r"\s+", " ", " ".join(label_el.itertext())).strip()
            if label_el is not None
            else ""
        )
        legends.append(f"{label}: {caption}" if label else caption)
    return legends


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bm25_rank(
    segments: list[tuple[str, str]], query: str, k1: float = 1.5, b: float = 0.75
) -> list[int]:
    """Indices of ``segments`` ranked by BM25 score against ``query``.

    Stdlib-only — this fallback must not pull the embedding stack into a
    just-in-time path. Segments are ``(section, text)`` pairs.
    """
    docs = [_tokenize(t) for _, t in segments]
    if not docs:
        return []
    avgdl = sum(len(d) for d in docs) / len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs)
    q_terms = _tokenize(query)
    scores: list[float] = []
    for d in docs:
        tf = Counter(d)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * len(d) / avgdl) if avgdl else tf[term] + k1
            score += idf * tf[term] * (k1 + 1) / denom
        scores.append(score)
    return sorted(range(n), key=lambda i: scores[i], reverse=True)


def read_paper(
    xml_path: Path | str,
    *,
    doi: str | None = None,
    query: str | None = None,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> PaperReading:
    """Build a :class:`PaperReading` from a cached JATS file.

    Args:
        xml_path: path to ``paper.jats.xml``.
        doi: recorded on the output (provenance; not derived from the XML).
        query: used only if the paper exceeds ``budget_tokens`` — BM25-ranks
            segments so the slice keeps the most relevant paragraphs. Without a
            query an oversized paper is truncated in document order.
        budget_tokens: narrative budget before the truncation fallback fires.
    """
    from atlas_chat.services._jats_parser import parse_jats_citations
    from atlas_chat.services.local_snippet_index import extract_body_segments

    xml = Path(xml_path).read_text()

    segments = extract_body_segments(xml)
    pairs = [(seg.section, seg.text) for seg in segments]

    # Where does narrative end? Nature-style JATS has no section titled
    # "Methods" — methods prose sits in leaf sections *after* Discussion
    # ("Tissue acquisition and processing", …). So: when a Discussion section
    # exists, everything through its last paragraph is narrative and everything
    # after is methods; title-matched methods sections are methods wherever
    # they sit. Without a Discussion, only the title match applies.
    last_discussion = max(
        (i for i, (sec, _) in enumerate(pairs) if (sec or "").strip().lower() == "discussion"),
        default=None,
    )
    narrative: list[tuple[str, str]] = []
    methods: list[tuple[str, str]] = []
    for i, (section, text) in enumerate(pairs):
        after_discussion = last_discussion is not None and i > last_discussion
        if after_discussion or _METHODS_TITLES.match(section or ""):
            methods.append((section, text))
        else:
            narrative.append((section, text))

    n_chars_total = sum(len(t) for _, t in narrative)
    budget_chars = budget_tokens * _CHARS_PER_TOKEN
    truncated = n_chars_total > budget_chars

    if truncated:
        order = _bm25_rank(narrative, query) if query else list(range(len(narrative)))
        kept: set[int] = set()
        used = 0
        for idx in order:
            seg_len = len(narrative[idx][1])
            if used + seg_len > budget_chars:
                continue
            kept.add(idx)
            used += seg_len
        # Restore document order so rank order is invisible to the reader
        # (Stage 3b prepared contexts the same way).
        narrative_kept = [narrative[i] for i in sorted(kept)]
        logger.warning(
            "Paper over budget (%d chars > %d): keeping %d of %d segments",
            n_chars_total,
            budget_chars,
            len(narrative_kept),
            len(narrative),
        )
        narrative = narrative_kept

    def _render(segs: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        current = None
        for section, text in segs:
            if section != current:
                parts.append(f"\n## {section}\n" if section else "\n")
                current = section
            parts.append(text)
        return "\n".join(parts).strip()

    cited, refs = parse_jats_citations(xml)

    return PaperReading(
        doi=doi,
        narrative_text=_render(narrative),
        methods_text=_render(methods),
        legends=_extract_legends(xml),
        cited_sentences=[
            {
                "text": cs.text,
                "section": cs.section,
                "ref_ids": cs.ref_ids,
                "resolved_refs": [
                    {
                        "ref_id": r.ref_id,
                        "doi": r.doi,
                        "pmid": r.pmid,
                        "title": r.title,
                        "year": r.year,
                        "first_author": r.first_author,
                    }
                    for r in cs.resolved_refs
                ],
            }
            for cs in cited
        ],
        ref_lookup={
            rid: {
                "doi": r.doi,
                "pmid": r.pmid,
                "title": r.title,
                "year": r.year,
                "first_author": r.first_author,
            }
            for rid, r in refs.items()
        },
        truncated=truncated,
        n_chars_total=n_chars_total,
    )
