"""CLI for getting a paper's text.

Thin entry point so retrieval is usable without a Claude Code session:

.. code-block:: bash

    python -m atlas_chat.cli_paper fetch --out P --doi 10.1038/s41586-024-08002-x
    python -m atlas_chat.cli_paper fetch --out P --cas projects/x/cas.json
    python -m atlas_chat.cli_paper candidates --inputs projects/x/inputs
    python -m atlas_chat.cli_paper adopt --out P --doi D --file paper.pdf
    python -m atlas_chat.cli_paper show --out P --doi D
    python -m atlas_chat.cli_paper text --pdf paper.pdf

The implementation lives in :mod:`atlas_chat.services.paper_fetch`.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from atlas_chat.services.paper_fetch import (
    PaperFetchError,
    Retrieval,
    adopt,
    candidates,
    cross_check_retrieval,
    fetch_paper,
    looks_readable,
    paper_dir,
    pdf_text,
    read_record,
)

logger = logging.getLogger(__name__)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def read_dois(args: argparse.Namespace) -> list[str]:
    """The papers to work on, from whichever way the caller named them.

    Three ways, because projects hold their paper lists three ways: DOIs on the
    command line, a CAS+ document naming an atlas and its subatlas papers, or a
    plain file with one DOI per line — which is how a project that has not yet
    filled in its CAS+ ``subatlas_papers`` block keeps the list.
    """
    dois: list[str] = list(args.doi or [])

    if args.cas:
        from atlas_chat.services.supplement_store import corpus_papers

        cas = json.loads(Path(args.cas).read_text(encoding="utf-8"))
        dois.extend(paper["doi"] for paper in corpus_papers(cas))

    if args.doi_file:
        for line in Path(args.doi_file).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                dois.append(stripped)

    seen: set[str] = set()
    unique: list[str] = []
    for doi in dois:
        if doi not in seen:
            seen.add(doi)
            unique.append(doi)
    if not unique:
        raise PaperFetchError("no DOIs given; pass --doi, --cas or --doi-file")
    return unique


def summarise(record: Retrieval, out_root: str | Path) -> dict[str, Any]:
    """One line's worth of what happened to a paper, for a batch report."""
    row: dict[str, Any] = {"doi": record.doi, "route": record.route}
    if record.kind:
        row["kind"] = record.kind
    if record.title:
        row["title"] = record.title[:90]
    if record.text_quality:
        row["n_chars"] = record.text_quality.get("n_chars")
        row["readable"] = looks_readable(record.text_quality)
    elif record.path:
        row["n_chars"] = (paper_dir(out_root, record.doi) / record.path).stat().st_size
    if record.route == "none" and record.gap:
        row["reason"] = record.gap.get("reason")
        row["action"] = record.gap.get("action")
    return row


def _cmd_fetch(args: argparse.Namespace) -> int:
    dois = read_dois(args)
    rows: list[dict[str, Any]] = []
    failures = 0
    for doi in dois:
        try:
            record = fetch_paper(
                doi,
                args.out,
                retry=args.retry,
                allow_pdf=not args.no_pdf,
                contact=args.contact,
            )
        except PaperFetchError as exc:
            failures += 1
            rows.append({"doi": doi, "route": "error", "reason": str(exc)})
            continue
        rows.append(summarise(record, args.out))
    _print({"papers": rows, "n": len(rows), "n_errors": failures})
    # A paper nobody can retrieve is a normal outcome and not an error; a paper
    # the tool broke on is.
    return 1 if failures else 0


def _cmd_adopt(args: argparse.Namespace) -> int:
    record = adopt(args.doi, args.out, args.file)
    if record.text_quality and not looks_readable(record.text_quality):
        print(
            f"warning: {args.file} yielded only {record.text_quality['n_chars']} characters "
            "of text — is it a scan?",
        )
    _print(record.to_dict())
    return 0


def _cmd_candidates(args: argparse.Namespace) -> int:
    _print({"candidates": candidates(args.inputs)})
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    record = read_record(args.out, args.doi)
    if record is None:
        print(f"no retrieval record for {args.doi} under {args.out}")
        return 2
    payload = record.to_dict()
    problems = cross_check_retrieval(payload)
    if problems:
        payload["_problems"] = problems
    _print(payload)
    return 1 if problems else 0


def _cmd_text(args: argparse.Namespace) -> int:
    text, quality = pdf_text(args.pdf)
    destination = Path(args.out) if args.out else Path(args.pdf).with_suffix(".txt")
    destination.write_text(text, encoding="utf-8")
    quality["path"] = str(destination)
    quality["readable"] = looks_readable(quality)
    _print(quality)
    return 0 if quality["readable"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_paper",
        description="Get a paper's text, and record how it arrived.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    out = argparse.ArgumentParser(add_help=False)
    out.add_argument(
        "--out",
        required=True,
        help="directory the papers live under; each gets a subdirectory named from its DOI",
    )

    fetch = sub.add_parser("fetch", parents=[out], help="walk the retrieval waterfall")
    fetch.add_argument("--doi", action="append", help="repeatable")
    fetch.add_argument("--cas", help="CAS+ document naming the atlas and its subatlas papers")
    fetch.add_argument("--doi-file", help="file with one DOI per line")
    fetch.add_argument(
        "--retry",
        action="store_true",
        help="try again for papers an earlier run recorded as unreachable",
    )
    fetch.add_argument(
        "--no-pdf",
        action="store_true",
        help="accept only tagged article XML, declining papers available solely as PDFs",
    )
    fetch.add_argument("--contact", help="contact address for the open-access resolver")

    adopt_cmd = sub.add_parser("adopt", parents=[out], help="take in a file a user supplied")
    adopt_cmd.add_argument("--doi", required=True)
    adopt_cmd.add_argument("--file", required=True, help="the PDF or article XML")

    cand = sub.add_parser("candidates", help="what in a drop zone could be a paper")
    cand.add_argument("--inputs", required=True, help="directory to look in, searched recursively")

    show = sub.add_parser("show", parents=[out], help="a paper's retrieval record")
    show.add_argument("--doi", required=True)

    text = sub.add_parser("text", help="recover text from a PDF and say how much came out")
    text.add_argument("--pdf", required=True)
    text.add_argument("--out", help="default: the PDF's path with a .txt suffix")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    handlers = {
        "fetch": _cmd_fetch,
        "adopt": _cmd_adopt,
        "candidates": _cmd_candidates,
        "show": _cmd_show,
        "text": _cmd_text,
    }
    try:
        return handlers[args.command](args)
    except PaperFetchError as exc:
        print(str(exc))
        return 2


__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
