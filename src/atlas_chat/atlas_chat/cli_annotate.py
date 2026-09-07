"""Agent-facing CLI for programmatic citation traversal.

Keeps raw ASTA snippet payloads out of the agent's context. Three subcommands:

- ``fetch``: call ASTA ``snippet_search`` (via the project's ``AstaProvider``) — or,
  with ``--local``, the project's own snippet index — splice reference tokens, and
  write slim ``annotated_snippet`` records to disk. Prints only a tiny summary
  (counts + path) to stdout. Both sources produce the same record shape, so a
  paper ASTA cannot serve is still quotable and traversable.
- ``follow-set``: intersect the agent's proposed CorpusIds with the ids the
  annotator emitted, writing the deduped follow-set + rejects.
- ``show``: print a record's ``annotated_text`` (+ sentence spans) so the agent can
  read slim content without opening the raw file.

The agent never calls the ASTA MCP tool directly — this service is the sanctioned
programmatic boundary (same layer as ``services.citation_traverser``), so raw JSON
never enters the model context regardless of response size.

Examples::

    python -m atlas_chat.cli_annotate fetch \\
        --query "TML macrophages: location, function, markers" \\
        --paper-ids CorpusId:273400864 --limit 20 \\
        --role atlas --retrieval-method corpus_snippet --hop 0 \\
        --out out/annotated_snippets_hop0.json

    python -m atlas_chat.cli_annotate fetch \\
        --query "aPCV: definition, markers, cluster identity" \\
        --local --project-dir projects/test_projects/hca_reproductive \\
        --papers 10.1073/pnas.2404775121 --limit 20 \\
        --role subatlas --retrieval-method corpus_snippet --hop 0 \\
        --out out/subatlas_snippets.json

    python -m atlas_chat.cli_annotate follow-set \\
        --snippets out/annotated_snippets_hop0.json \\
        --proposed CorpusId:248122197 --proposed CorpusId:260956290 \\
        --hop 1 --out out/follow_set_hop1.json

    python -m atlas_chat.cli_annotate show \\
        --snippets out/annotated_snippets_hop0.json --index 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from atlas_chat.services import snippet_annotator

ROLES = ("atlas", "subatlas", "external")
RETRIEVAL_METHODS = (
    "corpus_snippet",
    "supplement",
    "citation_traversal",
    "free_search",
    "full_text",
)


async def _fetch_raw(query: str, paper_ids: str, limit: int) -> Any:
    """Call ASTA ``snippet_search`` and return the raw normalized payload."""
    import httpx

    from atlas_chat.services.citation_traverser import _make_provider

    provider = _make_provider()
    arguments: dict[str, Any] = {"query": query, "limit": limit}
    if paper_ids:
        arguments["paper_ids"] = paper_ids
    async with httpx.AsyncClient(timeout=180) as http_client:
        return await provider._call_tool(http_client, "snippet_search", arguments)


def _local_to_asta_item(row: dict[str, Any]) -> dict[str, Any]:
    """Re-nest a ``local_snippet_index.search`` row into the raw ASTA item shape.

    The local index stores its snippets ASTA-shaped, but ``search`` flattens them
    for its own return value (``snippet`` is the text, not the object). Undo that
    so the one deterministic projection in ``snippet_annotator`` handles both
    sources — otherwise the local path grows a parallel implementation of
    reference splicing, which is exactly what must not diverge.
    """
    return {
        "score": row.get("score", 0.0),
        "paper": {
            "corpusId": row.get("corpus_id") or row.get("paper_id"),
            "title": row.get("title", ""),
            "authors": row.get("authors", ""),
            "year": row.get("year"),
            "doi": row.get("doi", ""),
        },
        "snippet": {
            "text": row.get("snippet", ""),
            "section": row.get("section", ""),
            "annotations": {"refMentions": (row.get("annotations") or {}).get("refMentions") or []},
        },
    }


def _fetch_local_records(
    args: argparse.Namespace, reached_from: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Search the project's local snippet index instead of ASTA.

    ASTA is blind to a good part of the corpus by construction: a subatlas sits at
    ``status: local`` *because* the ASTA probe found too little of it to quote, so a
    local index was built from JATS or a publisher PDF. Without this path those
    papers are unreachable from the agentic route — the local index only ever fed
    the programmatic graph, so the two runtimes were not equivalent. They are the
    papers that most often define an inherited cell type.

    Each record is projected individually so its ``source_paper`` carries **that
    paper's DOI**. Local corpus ids are synthetic (``local_<hash>``) and Semantic
    Scholar cannot resolve them, so the DOI is the identifier that has to survive
    into ``paper_catalogue.json``.
    """
    from atlas_chat.services import local_snippet_index

    rows = local_snippet_index.search(
        Path(args.project_dir),
        args.query,
        k=args.limit,
        papers=[d.strip() for d in args.papers.split(",") if d.strip()] or None,
        roles=[r.strip() for r in args.roles.split(",") if r.strip()] or None,
    )
    records: list[dict[str, Any]] = []
    for row in rows:
        if row.get("score", 0.0) < args.score_threshold:
            continue
        source_paper: dict[str, Any] = {"role": args.role}
        if row.get("doi"):
            source_paper["doi"] = row["doi"]
        records.append(
            snippet_annotator.project_snippet(
                _local_to_asta_item(row),
                source_paper=source_paper,
                retrieval_method=args.retrieval_method,
                reached_from=reached_from,
            )
        )
    return records


def _fallback_source_id(paper_ids: str) -> dict[str, str]:
    """Derive a source-paper id from the first --paper-ids token (fallback only)."""
    first = paper_ids.split(",")[0].strip() if paper_ids else ""
    if first.startswith("DOI:"):
        return {"doi": first[len("DOI:") :]}
    if first.startswith("CorpusId:") and first[len("CorpusId:") :].isdigit():
        return {"corpus_id": first}
    return {}


def _apply_id_fallback(records: list[dict[str, Any]], fallback: dict[str, str]) -> None:
    """Ensure every record's source_paper carries an id (ASTA usually supplies one)."""
    for record in records:
        source = record["source_paper"]
        if "corpus_id" not in source and "doi" not in source:
            source.update(fallback)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _cmd_fetch(args: argparse.Namespace) -> int:
    if args.local and not args.project_dir:
        print("--local requires --project-dir", file=sys.stderr)
        return 2

    reached_from: dict[str, Any] | None = None
    if args.reached_from:
        try:
            reached_from = json.loads(args.reached_from)
        except json.JSONDecodeError as exc:
            print(f"--reached-from is not valid JSON: {exc}", file=sys.stderr)
            return 2

    if args.local:
        records = _fetch_local_records(args, reached_from)
        fallback = f"DOI:{args.papers.split(',')[0].strip()}" if args.papers else ""
    else:
        raw = asyncio.run(_fetch_raw(args.query, args.paper_ids, args.limit))
        records = snippet_annotator.project_response(
            raw,
            source_paper={"role": args.role},
            retrieval_method=args.retrieval_method,
            reached_from=reached_from,
            score_threshold=args.score_threshold,
        )
        fallback = args.paper_ids
    _apply_id_fallback(records, _fallback_source_id(fallback))

    out = Path(args.out)
    _write_json(out, records)
    n_refs = sum(len(r.get("refMentions", [])) for r in records)
    n_resolved = sum(1 for r in records for m in r.get("refMentions", []) if m.get("resolved"))
    source = "local index" if args.local else "ASTA"
    print(
        f"fetch ({source}): {len(records)} snippets, "
        f"{n_refs} refMentions ({n_resolved} resolved) -> {out}"
    )
    return 0


def _probe_candidate_bands(proposed: list[str], project_dir: str | None) -> dict[str, str]:
    """Measure each proposed paper's ASTA indexing band (one call per paper).

    Only well-formed ``CorpusId:NNNN`` proposals are probed; malformed ones are
    rejected by ``resolve_follow_set`` anyway. A probe failure is logged and the
    id left unjudged, so a transient ASTA error can never silently prune a real
    reference.
    """
    from atlas_chat.services import asta_indexing

    bands: dict[str, str] = {}
    for candidate in dict.fromkeys(c.strip() for c in proposed):
        if not candidate.startswith("CorpusId:"):
            continue
        try:
            report = asyncio.run(asta_indexing.probe_cached(candidate, project_dir=project_dir))
        except Exception as exc:  # noqa: BLE001 - never prune on a probe failure
            print(f"  probe failed for {candidate}, not judging: {exc}", file=sys.stderr)
            continue
        bands[candidate] = report.band
    return bands


def _cmd_follow_set(args: argparse.Namespace) -> int:
    snippets = json.loads(Path(args.snippets).read_text(encoding="utf-8"))
    bands = _probe_candidate_bands(args.proposed, args.project_dir) if args.probe_bands else None
    result = snippet_annotator.resolve_follow_set(
        snippets, args.proposed, hop=args.hop, bands=bands
    )
    out = Path(args.out)
    _write_json(out, result)
    print(
        f"follow-set: {len(result['follow_set'])} to follow, "
        f"{len(result['rejected'])} rejected -> {out}"
    )
    if bands:
        dead = [r for r in result["rejected"] if r["reason"] == "asta_unindexed"]
        if dead:
            print(
                "  skipped (no text in ASTA): "
                + ", ".join(f"{r['corpus_id']}={r['band']}" for r in dead)
            )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    snippets = json.loads(Path(args.snippets).read_text(encoding="utf-8"))
    indices = [args.index] if args.index is not None else range(len(snippets))
    for i in indices:
        record = snippets[i]
        print(f"--- [{i}] section={record.get('section', '')} score={record.get('score')}")
        print(record.get("annotated_text", record.get("text", "")))
        print(f"sentences: {record.get('sentences', [])}")
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    from atlas_chat.services import paper_router

    route = paper_router.resolve_route(
        args.paper,
        args.project_dir or None,
        fetch=not args.no_fetch,
        probe_asta=not args.no_probe,
    )
    print(json.dumps(route.to_dict(), indent=2))
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    """Route a paper and, when JATS serves it, write a reader job file.

    The job file carries the whole narrative text, legends, and the resolved
    cited sentences — everything a reader subagent needs, no raw XML and no
    further tool calls in its context. When the route is ASTA the command
    prints the route and exits 3 so the caller falls back to ``fetch``.
    """
    from atlas_chat.services import jats_reader, paper_router

    route = paper_router.resolve_route(args.paper, args.project_dir or None)
    if route.method != paper_router.JATS:
        print(json.dumps(route.to_dict(), indent=2))
        print(f"not a JATS route ({route.method}); use `fetch` for ASTA", file=sys.stderr)
        return 3
    if not route.cache_path:
        print("JATS route with no cached file (no --project-dir?)", file=sys.stderr)
        return 2

    reading = jats_reader.read_paper(
        route.cache_path,
        doi=route.doi,
        query=args.query or None,
        budget_tokens=args.budget_tokens,
    )
    job = reading.to_dict()
    job["route"] = route.to_dict()
    out = Path(args.out)
    _write_json(out, job)
    if args.traversed:
        paper_router.mark_traversed(
            args.traversed, args.paper, {"method": "jats", "source": route.source}
        )
    print(
        f"read: doi={route.doi} source={route.source} "
        f"narrative_chars={len(reading.narrative_text)} "
        f"cited_sentences={len(reading.cited_sentences)} legends={len(reading.legends)} "
        f"truncated={reading.truncated} -> {out}"
    )
    return 0


def _cmd_follow_check(args: argparse.Namespace) -> int:
    """Validate proposed follow targets against a paper's actual reference list.

    The JATS counterpart of ``follow-set``: proposals are ``ref_id``s (or DOIs)
    from the reader; anything not present in the paper's ``cited_sentences`` is
    rejected (anti-hallucination — the reference list is closed). Accepted
    targets are deduplicated against the run's ``traversed.json``.
    """
    from atlas_chat.services import paper_router

    job = json.loads(Path(args.paper_json).read_text(encoding="utf-8"))
    cited = job.get("cited_sentences", [])
    ref_lookup = job.get("ref_lookup", {})

    by_ref_id: dict[str, dict[str, Any]] = {}
    by_doi: dict[str, dict[str, Any]] = {}
    for cs in cited:
        for rid in cs.get("ref_ids", []):
            by_ref_id.setdefault(rid, cs)
        for r in cs.get("resolved_refs", []):
            if r.get("doi"):
                by_doi.setdefault(r["doi"].lower(), cs)

    follow: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for proposed in args.proposed:
        p = proposed.strip()
        cs = by_ref_id.get(p)
        ref = ref_lookup.get(p)
        doi_key = p.lower().removeprefix("doi:")
        if cs is None and doi_key in by_doi:
            cs = by_doi[doi_key]
            ref = next(
                (r for r in ref_lookup.values() if (r.get("doi") or "").lower() == doi_key),
                None,
            )
        if cs is None or ref is None:
            rejected.append({"proposed": p, "reason": "not_in_reference_list"})
            continue
        doi = ref.get("doi")
        if not doi:
            rejected.append({"proposed": p, "reason": "no_resolvable_identifier", "ref": ref})
            continue
        key = paper_router.canonical_key(doi)
        if key in seen_targets:
            continue
        if args.traversed and paper_router.is_traversed(args.traversed, doi):
            rejected.append({"proposed": p, "reason": "already_traversed", "doi": doi})
            continue
        seen_targets.add(key)
        follow.append(
            {
                "ref_id": p if p in by_ref_id else ref.get("doi"),
                "doi": doi,
                "title": ref.get("title"),
                "year": ref.get("year"),
                "first_author": ref.get("first_author"),
                "citation_context": cs.get("text", ""),
                "section": cs.get("section", ""),
            }
        )

    result = {"follow": follow, "rejected": rejected}
    _write_json(Path(args.out), result)
    print(f"follow-check: {len(follow)} to follow, {len(rejected)} rejected -> {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas_chat.cli_annotate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="ASTA snippet_search -> slim annotated records")
    fetch.add_argument("--query", required=True)
    fetch.add_argument("--paper-ids", default="", help="comma-separated seed ids (CorpusId:/DOI:)")
    fetch.add_argument("--limit", type=int, default=20)
    fetch.add_argument("--role", choices=ROLES, required=True)
    fetch.add_argument("--retrieval-method", choices=RETRIEVAL_METHODS, required=True)
    fetch.add_argument(
        "--hop", type=int, default=0, help="informational; used for the --out filename"
    )
    fetch.add_argument(
        "--reached-from", default="", help="JSON object stamped on every record (hop>=1)"
    )
    fetch.add_argument(
        "--local",
        action="store_true",
        help="search the project's local snippet index instead of ASTA. Needed for "
        "corpus papers at status 'local' — ASTA holds too little of them to quote, "
        "which is why they were built locally in the first place.",
    )
    fetch.add_argument(
        "--project-dir", default="", help="project directory (required with --local)"
    )
    fetch.add_argument(
        "--papers",
        default="",
        help="with --local: comma-separated DOIs to restrict the search to",
    )
    fetch.add_argument(
        "--roles",
        default="",
        help="with --local: comma-separated paper roles to restrict to (e.g. subatlas)",
    )
    fetch.add_argument("--score-threshold", type=float, default=0.0)
    fetch.add_argument("--out", required=True)
    fetch.set_defaults(func=_cmd_fetch)

    fs = sub.add_parser("follow-set", help="proposed ∩ real refMentions (anti-hallucination)")
    fs.add_argument("--snippets", required=True, help="annotated_snippets_hop<n>.json")
    fs.add_argument(
        "--proposed", action="append", default=[], help="a proposed CorpusId (repeatable)"
    )
    fs.add_argument("--hop", type=int, default=None)
    fs.add_argument(
        "--probe-bands",
        action="store_true",
        help="probe each candidate's ASTA indexing depth and skip papers ASTA "
        "holds no text for (one extra call per candidate, cached)",
    )
    fs.add_argument(
        "--project-dir",
        default=None,
        help="project directory whose config caches probed bands (with --probe-bands)",
    )
    fs.add_argument("--out", required=True)
    fs.set_defaults(func=_cmd_follow_set)

    show = sub.add_parser("show", help="print slim annotated_text for a record")
    show.add_argument("--snippets", required=True)
    show.add_argument("--index", type=int, default=None)
    show.set_defaults(func=_cmd_show)

    route = sub.add_parser(
        "route", help="decide how a paper is read: local JATS -> fetch -> ASTA -> unreachable"
    )
    route.add_argument("--paper", required=True, help="DOI:..., bare DOI, or CorpusId:NNNN")
    route.add_argument("--project-dir", default="", help="project root (JATS + band caches)")
    route.add_argument(
        "--no-fetch", action="store_true", help="only check caches and probe; no network fetch"
    )
    route.add_argument("--no-probe", action="store_true", help="skip the ASTA rung")
    route.set_defaults(func=_cmd_route)

    read = sub.add_parser(
        "read", help="route a paper and write a whole-text reader job file (JATS routes)"
    )
    read.add_argument("--paper", required=True, help="DOI:..., bare DOI, or CorpusId:NNNN")
    read.add_argument("--project-dir", default="", help="project root (JATS + band caches)")
    read.add_argument("--out", required=True, help="job-file path for the reader subagent")
    read.add_argument(
        "--query",
        default="",
        help="used only if the paper exceeds the budget: BM25-ranks kept segments",
    )
    read.add_argument("--budget-tokens", type=int, default=40_000)
    read.add_argument(
        "--traversed", default="", help="run seen-set path; marks this paper processed"
    )
    read.set_defaults(func=_cmd_read)

    fc = sub.add_parser(
        "follow-check",
        help="validate proposed citations against the paper's actual reference list",
    )
    fc.add_argument("--paper-json", required=True, help="the `read` output job file")
    fc.add_argument(
        "--proposed", action="append", default=[], help="a ref_id or DOI to follow (repeatable)"
    )
    fc.add_argument("--traversed", default="", help="run seen-set path; dedups targets")
    fc.add_argument("--out", required=True)
    fc.set_defaults(func=_cmd_follow_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
