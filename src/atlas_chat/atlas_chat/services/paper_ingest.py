"""Assemble what a reading agent is given about one paper, before any question.

A paper is read whole rather than retrieved from: within a single paper there is
nothing for a ranker to buy that reading the text does not already give. So the
job here is not selection but assembly — gather the text a reader needs, keep
the parts that must not be confused with each other apart, and say what could
not be included.

Three things are kept separate rather than concatenated, because each answers a
different kind of question and misreading one as another is a real error:

* **narrative** — the body prose, in document order, with its headings.
* **legends** — figure and table captions. A caption is not body prose, and a
  quote drawn from one should not read as though the authors wrote it in the
  text. Captions cannot be dropped either: naming information often appears in
  a caption and nowhere else.
* **cited sentences** — sentences carrying a citation, with the references they
  resolve to. A citation marks a claim as inherited rather than made here, and
  the resolved reference is an exact onward target rather than a search result.
  Available only from tagged XML.

Supplementary prose is folded in from the paper's supplement manifest, which
records which spans bear on describing cell types. Only those spans are carried.
Tables are deliberately absent: prose has to be read whole because it cannot be
sliced by a query, whereas a table can, and some are far too large to read.

Nothing here calls a model, and nothing here fetches a paper: the text is taken
from a path the caller supplies.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Rough characters per token, for reporting size rather than for billing.
CHARS_PER_TOKEN = 4

#: Sections whose titles say they describe how the work was done rather than
#: what was found, or that carry no findings at all.
_PROCESS_SECTION_TITLES = re.compile(
    r"^(methods?|materials and methods|online methods|star.{0,2}methods|"
    r"experimental procedures|acknowledge?ments?|author contributions|"
    r"competing interests|data availability|code availability|references)\b",
    re.I,
)

#: A section describing how populations were named or told apart is kept even
#: where it sits among process description, because that is where cluster
#: identifiers acquire the names everything downstream refers to them by.
_NAMING_SECTION_TITLES = re.compile(
    r"annotat|nomenclature|identificat|cell.?type|cell.?state|celltype|labell?ing",
    re.I,
)


class PaperIngestError(RuntimeError):
    """Raised when the supplied paper text cannot be assembled at all."""


@dataclass
class PaperIngest:
    """One paper's readable content, assembled and accounted for."""

    source_path: str
    source_kind: str
    narrative_text: str
    paper: dict[str, str] = field(default_factory=dict)
    excluded_sections: list[dict[str, Any]] = field(default_factory=list)
    legends: list[dict[str, str]] = field(default_factory=list)
    cited_sentences: list[dict[str, Any]] = field(default_factory=list)
    references: dict[str, Any] = field(default_factory=dict)
    supplement_prose: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] = field(default_factory=dict)
    limit_tokens: int | None = None
    truncated: bool = False
    gaps: list[dict[str, str]] = field(default_factory=list)

    @property
    def estimated_tokens(self) -> int:
        chars = len(self.narrative_text)
        chars += sum(len(item["text"]) for item in self.legends)
        chars += sum(len(item["text"]) for item in self.supplement_prose)
        chars += sum(len(item["text"]) for item in self.cited_sentences)
        return chars // CHARS_PER_TOKEN

    def to_dict(self) -> dict[str, Any]:
        source: dict[str, Any] = {"path": self.source_path, "kind": self.source_kind}
        source.update(self.retrieval)
        out: dict[str, Any] = {
            "source": source,
            "narrative": {
                "text": self.narrative_text,
                "n_chars": len(self.narrative_text),
            },
            "budget": {
                "estimated_tokens": self.estimated_tokens,
                "truncated": self.truncated,
            },
        }
        if self.limit_tokens is not None:
            out["budget"]["limit_tokens"] = self.limit_tokens
        if self.paper:
            out["paper"] = dict(self.paper)
        for key, value in (
            ("excluded_sections", self.excluded_sections),
            ("legends", self.legends),
            ("cited_sentences", self.cited_sentences),
            ("supplement_prose", self.supplement_prose),
            ("gaps", self.gaps),
        ):
            if value:
                out[key] = value
        if self.references:
            out["references"] = self.references
        return out


# ------------------------------------------------------------------
# Article text
# ------------------------------------------------------------------


def split_sections(
    pairs: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Partition ``(section, paragraph)`` pairs into kept prose and held-out sections.

    Process description is held out on two grounds. A section is held out when its
    own title says it is process description. It is also held out when it follows
    the last section titled Discussion: process description is frequently split
    into many specifically-titled leaf sections that say nothing about what they
    are collectively, and their position is the only thing that identifies them.

    A section whose title is about how populations were named or distinguished is
    kept either way.

    Where there is no section titled Discussion, position says nothing and only
    the title test applies.

    Args:
        pairs: paragraphs in document order, each with the heading above it.

    Returns:
        The pairs to read, and a record of each held-out section with the number
        of characters held out with it.
    """
    last_discussion = max(
        (
            i
            for i, (section, _) in enumerate(pairs)
            if (section or "").strip().lower() == "discussion"
        ),
        default=None,
    )
    kept: list[tuple[str, str]] = []
    excluded: dict[str, int] = {}
    for index, (section, text) in enumerate(pairs):
        heading = (section or "").strip()
        by_title = bool(_PROCESS_SECTION_TITLES.match(heading))
        by_position = last_discussion is not None and index > last_discussion
        if (by_title or by_position) and not _NAMING_SECTION_TITLES.search(heading):
            excluded[section] = excluded.get(section, 0) + len(text)
        else:
            kept.append((section, text))
    return kept, [{"heading": h, "n_chars": n} for h, n in excluded.items()]


def render(pairs: list[tuple[str, str]]) -> str:
    """Join ``(section, paragraph)`` pairs into text with headings interleaved."""
    parts: list[str] = []
    current: str | None = None
    for section, text in pairs:
        if section != current:
            if section:
                parts.append(f"\n## {section}\n")
            current = section
        parts.append(text)
    return "\n".join(parts).strip()


def extract_legends(xml: str) -> list[dict[str, str]]:
    """Figure and table captions, each with the authors' label where present."""
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", xml, count=1))
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    legends: list[dict[str, str]] = []
    for wrap in root.iter():
        if wrap.tag not in ("fig", "table-wrap"):
            continue
        caption_el = wrap.find("caption")
        if caption_el is None:
            continue
        caption = re.sub(r"\s+", " ", " ".join(caption_el.itertext())).strip()
        if not caption:
            continue
        label_el = wrap.find("label")
        label = (
            re.sub(r"\s+", " ", " ".join(label_el.itertext())).strip()
            if label_el is not None
            else ""
        )
        legends.append({"label": label, "text": caption} if label else {"text": caption})
    return legends


def _cited_sentences(xml: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from atlas_chat.services._jats_parser import parse_jats_citations

    cited, refs = parse_jats_citations(xml)
    sentences = [
        {
            "text": cs.text,
            "section": cs.section,
            "ref_ids": list(cs.ref_ids),
        }
        for cs in cited
    ]
    lookup = {
        ref_id: {
            key: value
            for key, value in (
                ("doi", ref.doi),
                ("pmid", ref.pmid),
                ("title", ref.title),
                ("year", ref.year),
                ("first_author", ref.first_author),
            )
            if value
        }
        for ref_id, ref in refs.items()
    }
    return sentences, lookup


# ------------------------------------------------------------------
# Supplementary prose
# ------------------------------------------------------------------


def _spans_of(pointer: dict[str, Any], text: str) -> tuple[str, list[str]]:
    """The text to carry from one prose pointer, and the headings it came from.

    A pointer judged section-wise carries only the spans marked as folding in;
    one judged as a whole carries the whole document.
    """
    sections = pointer.get("sections") or []
    picked = [s for s in sections if s.get("folds_in")]
    if not picked:
        return text, []
    parts = [text[s["char_start"] : s["char_end"]] for s in picked]
    return "\n\n".join(p.strip() for p in parts if p.strip()), [
        s.get("heading", "") for s in picked
    ]


def supplement_prose(
    store_root: str | Path, doi: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Prose spans from a paper's supplement manifest that fold into a read.

    Args:
        store_root: the supplement store holding this paper's manifest.
        doi: the paper whose manifest to read.

    Returns:
        The spans to carry, and a gap for each pointer that should have folded in
        but whose text could not be read.
    """
    from atlas_chat.services.supplement_store import load_manifest

    root = Path(store_root)
    manifest = load_manifest(root, doi)
    if manifest is None:
        return [], [{"what": f"supplements for {doi}", "reason": "no manifest in the store"}]

    carried: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for pointer in manifest.get("prose") or []:
        if not pointer.get("folds_in"):
            continue
        rel = pointer.get("text_file")
        if not rel:
            gaps.append(
                {
                    "what": pointer.get("file_id", "supplementary prose"),
                    "reason": "folds in, but the manifest records no extracted text",
                }
            )
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            gaps.append({"what": rel, "reason": f"extracted text unreadable: {exc}"})
            continue
        span, headings = _spans_of(pointer, text)
        if not span.strip():
            gaps.append({"what": rel, "reason": "folds in, but the spans marked are empty"})
            continue
        item: dict[str, Any] = {"text": span, "n_chars": len(span), "text_file": rel}
        for key in ("file_id", "member_path", "description"):
            if pointer.get(key):
                item[key] = pointer[key]
        if headings:
            item["headings"] = headings
        carried.append(item)
    return carried, gaps


# ------------------------------------------------------------------
# Assembly
# ------------------------------------------------------------------


def _fit(ingest: PaperIngest, limit_tokens: int) -> None:
    """Drop content to fit a ceiling, lowest precedence first, recording each drop.

    Precedence is the order the caller reads in: the article's own prose first,
    then its captions, then supplementary prose. So supplementary prose goes
    first and the narrative is only cut when nothing else is left to give.
    """
    ingest.limit_tokens = limit_tokens
    if ingest.estimated_tokens <= limit_tokens:
        return

    while ingest.supplement_prose and ingest.estimated_tokens > limit_tokens:
        dropped = ingest.supplement_prose.pop()
        ingest.truncated = True
        ingest.gaps.append(
            {
                "what": dropped.get("text_file", "supplementary prose"),
                "reason": "dropped to fit the read budget",
            }
        )

    if ingest.estimated_tokens > limit_tokens and ingest.legends:
        n = len(ingest.legends)
        ingest.legends = []
        ingest.truncated = True
        ingest.gaps.append(
            {"what": f"{n} figure and table captions", "reason": "dropped to fit the read budget"}
        )

    if ingest.estimated_tokens > limit_tokens:
        keep = limit_tokens * CHARS_PER_TOKEN
        original = len(ingest.narrative_text)
        ingest.narrative_text = ingest.narrative_text[:keep]
        ingest.truncated = True
        ingest.gaps.append(
            {
                "what": "the paper's narrative text",
                "reason": (
                    f"cut in document order at {keep} of {original} characters "
                    "to fit the read budget; the tail is unread"
                ),
            }
        )


def retrieval_of(text_path: Path) -> dict[str, Any]:
    """How the text beside this file arrived, where retrieval left a record.

    Retrieval writes its record one level above the source it fetched. Reading
    it here means a reader of the assembled paper is told where the text came
    from as well as how it was parsed — a PDF a user supplied and one pulled from
    a repository are the same to a parser and not the same to a grounding check.

    Args:
        text_path: The file the paper is being assembled from.

    Returns:
        The route and where it came from, or nothing where retrieval left no
        record — which is the normal case for a file assembled by hand.
    """
    record_path = text_path.parent.parent / "retrieval.json"
    if not record_path.is_file():
        return {}
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring unreadable retrieval record %s: %s", record_path, exc)
        return {}
    return {key: record[key] for key in ("route", "url", "retrieved_at") if record.get(key)}


def ingest_paper(
    text_path: str | Path,
    *,
    kind: str | None = None,
    doi: str | None = None,
    store_root: str | Path | None = None,
    limit_tokens: int | None = None,
) -> PaperIngest:
    """Assemble one paper's readable content from a file on disk.

    Args:
        text_path: tagged article XML, or plain text recovered from a PDF.
        kind: ``"jats"`` or ``"pdf_text"``. Inferred from the suffix when omitted.
        doi: the paper's DOI, recorded on the result and used to find its
            supplements. Without it no supplementary prose is looked for.
        store_root: the supplement store to take prose from.
        limit_tokens: ceiling on the assembled read. Content is dropped lowest
            precedence first and every drop is recorded as a gap.

    Returns:
        The assembled content, with what it cost and what is missing.

    Raises:
        PaperIngestError: the file cannot be read, or holds no prose at all.
    """
    path = Path(text_path)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PaperIngestError(f"cannot read {path}: {exc}") from exc

    resolved_kind = kind or ("jats" if path.suffix.lower() in (".xml", ".jats") else "pdf_text")
    ingest = PaperIngest(source_path=str(path), source_kind=resolved_kind, narrative_text="")
    ingest.retrieval = retrieval_of(path)
    if doi:
        ingest.paper["doi"] = doi

    if resolved_kind == "jats":
        from atlas_chat.services.local_snippet_index import extract_body_segments

        try:
            segments = extract_body_segments(raw)
        except ET.ParseError as exc:
            raise PaperIngestError(f"{path} is not parseable as article XML: {exc}") from exc
        kept, excluded = split_sections([(seg.section, seg.text) for seg in segments])
        ingest.narrative_text = render(kept)
        ingest.excluded_sections = excluded
        ingest.legends = extract_legends(raw)
        ingest.cited_sentences, ingest.references = _cited_sentences(raw)
    else:
        ingest.narrative_text = raw.strip()
        ingest.gaps.append(
            {
                "what": "cited sentences and the reference list",
                "reason": (
                    "the text came from a PDF, which carries no reference markup, "
                    "so no citation can be resolved from it"
                ),
            }
        )
        ingest.gaps.append(
            {
                "what": "guaranteed reading order",
                "reason": (
                    "the text came from a PDF, whose paragraphs are each internally "
                    "coherent but whose order across a column boundary is not "
                    "guaranteed, so a quote spanning one may not correspond to "
                    "anything a reader of the article would see"
                ),
            }
        )

    if not ingest.narrative_text.strip():
        raise PaperIngestError(f"{path} yielded no prose")

    if store_root is not None:
        if doi:
            carried, gaps = supplement_prose(store_root, doi)
            ingest.supplement_prose = carried
            ingest.gaps.extend(gaps)
        else:
            ingest.gaps.append(
                {
                    "what": "supplementary prose",
                    "reason": "a store was given but no DOI, so its manifest cannot be found",
                }
            )

    if limit_tokens is not None:
        _fit(ingest, limit_tokens)

    return ingest


def write_ingest(ingest: PaperIngest, out_path: str | Path) -> Path:
    """Write an assembled ingest as JSON, having validated it against its schema.

    Validation runs before the write, so an object that does not conform is never
    left on disk for something downstream to read.

    Raises:
        jsonschema.ValidationError: the assembled object does not conform.
    """
    import jsonschema  # type: ignore[import-untyped]

    from atlas_chat.schemas import load_schema

    payload = ingest.to_dict()
    jsonschema.validate(payload, load_schema("paper_ingest.schema.json"))
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_paper_ingest",
        description="Assemble one paper's readable content for a reading agent.",
    )
    parser.add_argument("--text", required=True, help="article XML, or text from a PDF")
    parser.add_argument("--out", required=True, help="where to write the assembled JSON")
    parser.add_argument("--kind", choices=["jats", "pdf_text"], help="default: from the suffix")
    parser.add_argument("--doi", help="recorded on the result; needed to find supplements")
    parser.add_argument("--store", help="supplement store to take prose from")
    parser.add_argument("--limit-tokens", type=int, help="ceiling on the assembled read")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s"
    )
    try:
        ingest = ingest_paper(
            args.text,
            kind=args.kind,
            doi=args.doi,
            store_root=args.store,
            limit_tokens=args.limit_tokens,
        )
    except PaperIngestError as exc:
        print(str(exc))
        return 2
    path = write_ingest(ingest, args.out)
    print(
        f"ingest: kind={ingest.source_kind} narrative_chars={len(ingest.narrative_text)} "
        f"legends={len(ingest.legends)} cited_sentences={len(ingest.cited_sentences)} "
        f"supplement_prose={len(ingest.supplement_prose)} "
        f"tokens~{ingest.estimated_tokens} truncated={ingest.truncated} "
        f"gaps={len(ingest.gaps)} -> {path}"
    )
    return 0
