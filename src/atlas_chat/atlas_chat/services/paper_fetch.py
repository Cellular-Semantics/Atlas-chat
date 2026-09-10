"""Get a paper's text, and say how it arrived.

Retrieval is the first thing a project does and the thing most likely to come up
short: a third of a real subatlas corpus is not reachable from Europe PMC, and
some of it is not reachable at all. So this is a waterfall rather than a single
call, and every rung it reaches is recorded — including the rungs that ran and
found nothing, which is what stops a paper nobody can get being re-requested on
every later pass.

The rungs, in order:

* **local** — the text is already here from an earlier run. Not a route: where
  this succeeds the existing record is kept exactly as it stands, so a paper
  supplied by hand last week still reads as supplied rather than as cached.
* **europepmc** — tagged article XML for the paper's PMC record.
* **preprint_server** — the JATS bioRxiv or medRxiv hosts. Behind Cloudflare, so
  fetched with TLS impersonation.
* **unpaywall** — an open-access location, which is usually a PDF. Whether a
  location is the paper or a preprint of it is a judgement, so every location the
  resolver named is recorded rather than only the one used.
* **ask** — nothing worked. This is a route on the record with a gap saying what
  to find and where to put it, not a failure: for some papers it is the only
  route there is.

Text is recovered from a PDF eagerly, because a PDF that extracts to almost
nothing is a scan and that has to be visible before anything tries to read it.
Such text is marked: it carries no reference markup, so no citation can be
resolved from it, and its reading order is not guaranteed across a column
boundary.

Nothing here knows this repository's layout. The caller says which directory the
papers live under; a paper's own directory is named from its DOI, and holds its
source, any recovered text, and the record describing both.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PREPRINT_DETAILS = "https://api.biorxiv.org/details"

#: Preprint servers sharing the bioRxiv details API. Both are tried: a DOI one
#: does not host costs a single cheap lookup, and medRxiv holds a good deal of
#: the clinical single-cell literature.
PREPRINT_SERVERS = ("biorxiv", "medrxiv")

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

#: Environment variable naming a contact address. Open-access resolvers require
#: one on every request; sending a placeholder instead would be rude and is
#: grounds for being blocked, so the rung reports having no address rather than
#: inventing one.
CONTACT_ENV = "ATLAS_CHAT_CONTACT_EMAIL"

RECORD_NAME = "retrieval.json"
SOURCE_DIR = "source"
JATS_NAME = "paper.jats.xml"
PDF_NAME = "paper.pdf"
TEXT_NAME = "paper.txt"

#: Suffixes that could hold a paper. A supplementary spreadsheet in the same
#: directory is not a candidate, and neither is a figure.
PAPER_SUFFIXES = (".pdf", ".xml", ".jats", ".nxml")

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]*[A-Za-z0-9]")

#: Below this, recovered text is not a paper. A scanned PDF extracts to a
#: handful of very short fragments, which is the case this exists to catch.
MIN_READABLE_CHARS = 2000


class PaperFetchError(RuntimeError):
    """Raised when a retrieval cannot even be attempted, or a record is unusable."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------
# The record
# ------------------------------------------------------------------


@dataclass
class Attempt:
    """One rung of the waterfall and what it did."""

    route: str
    outcome: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"route": self.route, "outcome": self.outcome}
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Context:
    """What every rung is given: a shared client and a contact address.

    The address is here rather than read from the environment inside each rung so
    that a caller can pass one without changing the process it is running in.
    """

    client: httpx.Client
    contact: str | None = None


@dataclass
class Fetched:
    """Bytes a rung produced, and what it knows about them."""

    kind: str
    body: bytes
    url: str | None = None
    title: str | None = None


@dataclass
class Retrieval:
    """How one paper's text arrived, conforming to ``paper_retrieval.schema.json``."""

    doi: str
    route: str = "none"
    kind: str | None = None
    path: str | None = None
    text_file: str | None = None
    sha256: str | None = None
    url: str | None = None
    title: str | None = None
    retrieved_at: str | None = None
    attempted_at: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    oa_candidates: list[dict[str, Any]] = field(default_factory=list)
    text_quality: dict[str, Any] | None = None
    gap: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"doi": self.doi, "route": self.route}
        for key in (
            "kind",
            "path",
            "text_file",
            "sha256",
            "url",
            "title",
            "retrieved_at",
            "attempted_at",
        ):
            value = getattr(self, key)
            if value:
                out[key] = value
        out["attempts"] = [a.to_dict() for a in self.attempts]
        if self.oa_candidates:
            out["oa_candidates"] = self.oa_candidates
        if self.text_quality:
            out["text_quality"] = self.text_quality
        if self.gap:
            out["gap"] = self.gap
        return out


def from_dict(payload: dict[str, Any]) -> Retrieval:
    """Rebuild a record read back from disk."""
    known = {
        key: payload.get(key)
        for key in (
            "doi",
            "route",
            "kind",
            "path",
            "text_file",
            "sha256",
            "url",
            "title",
            "retrieved_at",
            "attempted_at",
            "text_quality",
            "gap",
        )
    }
    return Retrieval(
        **{k: v for k, v in known.items() if v is not None},
        attempts=[Attempt(**a) for a in payload.get("attempts") or []],
        oa_candidates=list(payload.get("oa_candidates") or []),
    )


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def validate_retrieval(record: dict[str, Any]) -> None:
    """Validate against ``paper_retrieval.schema.json``.

    Raises:
        PaperFetchError: On the first schema violation, with the JSON path.
    """
    import jsonschema  # type: ignore[import-untyped]

    from atlas_chat.schemas import load_schema

    try:
        jsonschema.validate(record, load_schema("paper_retrieval.schema.json"))
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "(root)"
        raise PaperFetchError(f"retrieval record invalid at {location}: {exc.message}") from exc


def cross_check_retrieval(record: dict[str, Any]) -> list[str]:
    """Consistency rules the schema cannot express.

    The schema pins the shape; these are the rules that make a record *mean*
    something. A record claiming a route with nothing stored, or recovered text
    with no account of its size, passes schema validation and misleads a reader.

    Returns:
        Human-readable problems, empty if the record is consistent.
    """
    problems: list[str] = []
    route = record.get("route")
    attempts = record.get("attempts") or []
    succeeded = [a for a in attempts if a.get("outcome") == "ok"]

    if route == "none":
        for key in ("kind", "path", "sha256", "text_file", "retrieved_at"):
            if record.get(key):
                problems.append(f"route is 'none' but {key} is set")
        if not record.get("gap"):
            problems.append("route is 'none' but no gap says what to ask for")
        if succeeded:
            problems.append(
                f"route is 'none' but attempt '{succeeded[0].get('route')}' is recorded as ok"
            )
    else:
        for key in ("kind", "path", "sha256", "retrieved_at"):
            if not record.get(key):
                problems.append(f"route is '{route}' but {key} is missing")
        if record.get("gap"):
            problems.append(f"route is '{route}' but a gap is recorded as well")
        if len(succeeded) != 1:
            problems.append(
                f"expected exactly one attempt with outcome 'ok', found {len(succeeded)}"
            )
        elif succeeded[0].get("route") not in (route, "local"):
            problems.append(
                f"route is '{route}' but the successful attempt was '{succeeded[0].get('route')}'"
            )

    if record.get("kind") == "jats" and record.get("text_file"):
        problems.append("a JATS source is read directly and should carry no text_file")
    if record.get("text_file") and not record.get("text_quality"):
        problems.append("text_file is set but text_quality does not say how much text there is")
    if record.get("text_quality") and not record.get("text_file"):
        problems.append("text_quality is set but no text_file was written")

    used = [loc for loc in record.get("oa_candidates") or [] if loc.get("used")]
    if len(used) > 1:
        problems.append(f"{len(used)} open-access locations are marked as used")
    if used and route != "unpaywall":
        problems.append(f"an open-access location is marked used but the route is '{route}'")

    return problems


# ------------------------------------------------------------------
# Where a paper's things live
# ------------------------------------------------------------------


def paper_dir(out_root: str | Path, doi: str) -> Path:
    """The directory holding one paper's source, text and record."""
    from atlas_chat.services.local_snippet_index import paper_slug

    return Path(out_root) / paper_slug(doi)


def read_record(out_root: str | Path, doi: str) -> Retrieval | None:
    """The record for this paper, or ``None`` where none has been written."""
    path = paper_dir(out_root, doi) / RECORD_NAME
    if not path.is_file():
        return None
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise PaperFetchError(f"cannot read {path}: {exc}") from exc


def write_record(record: Retrieval, out_root: str | Path) -> Path:
    """Write a record as JSON, having validated it first.

    Validation runs before the write, so a record that does not conform is never
    left on disk for a later step to trust.

    Raises:
        PaperFetchError: The record does not conform, or is not self-consistent.
    """
    payload = record.to_dict()
    validate_retrieval(payload)
    problems = cross_check_retrieval(payload)
    if problems:
        raise PaperFetchError("retrieval record is not self-consistent: " + "; ".join(problems))
    directory = paper_dir(out_root, record.doi)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECORD_NAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------
# Recovering text from a PDF
# ------------------------------------------------------------------


def pdf_text(pdf_path: str | Path) -> tuple[str, dict[str, Any]]:
    """Recover readable text from a PDF, with an account of what came out.

    Uses the extractor the rest of the project reads PDFs with
    (:func:`atlas_chat.services._pdf_parser.extract_pdf_segments`), which
    reassembles multi-column layouts into paragraphs. Text inside figures is
    dropped: it is a stream of axis labels and panel tags, and it is not quotable
    prose.

    Args:
        pdf_path: The PDF to read.

    Returns:
        The text, and its size and shape. A scan yields a handful of very short
        segments, which is what the shape is for.

    Raises:
        PaperFetchError: The extractor is not installed.
    """
    try:
        from atlas_chat.services._pdf_parser import extract_pdf_segments
    except ImportError as exc:  # pragma: no cover - environment guard
        raise PaperFetchError(f"cannot read PDFs without the [text-access] extra: {exc}") from exc

    segments = [s for s in extract_pdf_segments(pdf_path) if s.section != "IN_FIGURE"]
    parts: list[str] = []
    current: str | None = None
    for segment in segments:
        if segment.section != current:
            if segment.section and segment.section != "BODY":
                parts.append(f"\n## {segment.section}\n")
            current = segment.section
        parts.append(segment.text)
    text = "\n".join(parts).strip()

    quality: dict[str, Any] = {"n_segments": len(segments), "n_chars": len(text)}
    if segments:
        quality["mean_chars_per_segment"] = round(
            sum(len(s.text) for s in segments) / len(segments), 1
        )
    sample = "\n\n".join(s.text for s in segments[:3])[:600]
    if sample:
        quality["sample"] = sample
    return text, quality


def looks_readable(quality: dict[str, Any]) -> bool:
    """Whether recovered text is worth reading at all.

    A deliberately blunt test on total size. It catches the case it exists for —
    a PDF of page images, which extracts to nearly nothing — and leaves the finer
    judgement, whether the reading order survived, to a reader who can see the
    text.
    """
    return int(quality.get("n_chars", 0)) >= MIN_READABLE_CHARS


# ------------------------------------------------------------------
# Storing what a rung produced
# ------------------------------------------------------------------


def _store(record: Retrieval, out_root: str | Path, fetched: Fetched) -> None:
    """Write the bytes into the paper's directory and describe them on the record."""
    directory = paper_dir(out_root, record.doi) / SOURCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = JATS_NAME if fetched.kind == "jats" else PDF_NAME
    target = directory / name
    target.write_bytes(fetched.body)

    record.kind = fetched.kind
    record.path = f"{SOURCE_DIR}/{name}"
    record.sha256 = hashlib.sha256(fetched.body).hexdigest()
    record.retrieved_at = _now()
    if fetched.url:
        record.url = fetched.url
    if fetched.title and not record.title:
        record.title = fetched.title

    if fetched.kind == "pdf":
        text, quality = pdf_text(target)
        text_path = directory / TEXT_NAME
        text_path.write_text(text, encoding="utf-8")
        record.text_file = f"{SOURCE_DIR}/{TEXT_NAME}"
        record.text_quality = quality


# ------------------------------------------------------------------
# The rungs
# ------------------------------------------------------------------


def contact_email(explicit: str | None = None) -> str | None:
    """A contact address for a resolver that requires one.

    Precedence is the project's usual one: an explicit argument, then the
    environment, then the checkout's git identity — which means it works without
    setup for someone working in their own clone, and is overridable for anyone
    else.
    """
    if explicit:
        return explicit
    from_env = os.getenv(CONTACT_ENV)
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    address = result.stdout.strip()
    return address or None


def _rung_europepmc(doi: str, record: Retrieval, ctx: Context) -> Fetched | None:
    """Tagged article XML for the paper's PMC record.

    A paper can have a PMC record and still have no article XML behind it: an
    author-manuscript deposit is catalogued but not open, and its ``fullTextXML``
    answers 404. That is 'unavailable' rather than 'failed' — there is nothing
    here to retry.
    """
    try:
        response = ctx.client.get(
            f"{EUROPEPMC_BASE}/search",
            params={
                "query": f'DOI:"{doi}"',
                "format": "json",
                "pageSize": 1,
                "resultType": "core",
            },
        )
        response.raise_for_status()
        results = (response.json().get("resultList") or {}).get("result") or []
    except Exception as exc:
        record.attempts.append(Attempt("europepmc", "failed", f"search errored: {exc}"))
        return None

    if not results:
        record.attempts.append(
            Attempt("europepmc", "unavailable", "no Europe PMC record for this DOI")
        )
        return None

    result = results[0]
    if result.get("title") and not record.title:
        record.title = str(result["title"]).rstrip(".")
    pmcid = result.get("pmcid")
    if not pmcid:
        record.attempts.append(
            Attempt("europepmc", "unavailable", "Europe PMC record carries no PMCID")
        )
        return None

    url = f"{EUROPEPMC_BASE}/{pmcid}/fullTextXML"
    try:
        xml = ctx.client.get(url, timeout=90)
    except Exception as exc:
        record.attempts.append(Attempt("europepmc", "failed", f"{pmcid} fullTextXML: {exc}"))
        return None
    if xml.status_code != 200:
        record.attempts.append(
            Attempt(
                "europepmc",
                "unavailable",
                f"{pmcid} is catalogued but its fullTextXML returned "
                f"{xml.status_code} (open access: {result.get('isOpenAccess', 'unknown')})",
            )
        )
        return None
    if "<article" not in xml.text[:4000]:
        record.attempts.append(
            Attempt("europepmc", "unavailable", f"{pmcid} fullTextXML is not a JATS article")
        )
        return None

    record.attempts.append(Attempt("europepmc", "ok", f"article XML for {pmcid}"))
    return Fetched(kind="jats", body=xml.content, url=url, title=record.title)


def preprint_metadata(
    doi: str, client: httpx.Client
) -> tuple[dict[str, Any] | None, str, list[str]]:
    """The preprint servers' record for this DOI, and which server has it.

    Both servers share one details API, and a DOI a server does not host answers
    cheaply, so asking both is also the cheapest test of whether a paper is a
    preprint at all.

    A server that answers "no posts found" and a server that does not answer are
    reported separately, because they mean opposite things: the first settles
    that the paper is not a preprint, and the second settles nothing. Recording
    an outage as the former would leave a preprint permanently marked as not one.

    Returns:
        The record and the server holding it, and the servers that failed to
        answer at all.
    """
    unreachable: list[str] = []
    for server in PREPRINT_SERVERS:
        try:
            response = client.get(f"{PREPRINT_DETAILS}/{server}/{doi}/na/json", timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.info("%s details lookup failed for %s: %s", server, doi, exc)
            unreachable.append(f"{server}: {type(exc).__name__}")
            continue
        messages = data.get("messages") or [{}]
        if messages[0].get("status") != "ok":
            continue
        collection = data.get("collection") or []
        if collection:
            return collection[0], server, unreachable
    return None, "", unreachable


def _normalize_jats_url(url: str) -> str:
    """Collapse the doubled slashes the details API sometimes returns.

    Highwire answers 404 for the literal path and 200 for the collapsed one.
    """
    scheme, _, rest = url.partition("://")
    return scheme + "://" + re.sub(r"/{2,}", "/", rest)


def _rung_preprint_server(doi: str, record: Retrieval, ctx: Context) -> Fetched | None:
    """The JATS a preprint server hosts, fetched past Cloudflare.

    A plain request gets a challenge page, so this needs TLS impersonation. That
    lives behind an optional extra, and its absence is 'skipped': nothing was
    learnt about the paper.
    """
    meta, server, unreachable = preprint_metadata(doi, ctx.client)
    if not meta:
        answered = [s for s in PREPRINT_SERVERS if not any(u.startswith(s) for u in unreachable)]
        if unreachable:
            # Some server never answered, so "not a preprint" is not established.
            record.attempts.append(
                Attempt(
                    "preprint_server",
                    "failed",
                    f"could not reach {'; '.join(unreachable)}"
                    + (f" ({' and '.join(answered)} say they do not host it)" if answered else ""),
                )
            )
        else:
            record.attempts.append(
                Attempt(
                    "preprint_server",
                    "unavailable",
                    f"not hosted by {' or '.join(PREPRINT_SERVERS)}",
                )
            )
        return None

    if meta.get("title") and not record.title:
        record.title = str(meta["title"]).rstrip(".")
    jats_url = meta.get("jatsxml")
    if not jats_url:
        record.attempts.append(
            Attempt("preprint_server", "unavailable", f"{server} record carries no JATS URL")
        )
        return None
    jats_url = _normalize_jats_url(jats_url)

    try:
        from curl_cffi import requests as impersonating
    except ImportError:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "skipped",
                f"{server} hosts JATS at {jats_url} but getting past Cloudflare needs "
                "curl_cffi (uv sync --extra text-access)",
            )
        )
        return None

    try:
        response = impersonating.get(jats_url, impersonate="chrome120", timeout=90)
    except Exception as exc:
        record.attempts.append(Attempt("preprint_server", "failed", f"{jats_url}: {exc}"))
        return None
    if response.status_code != 200:
        record.attempts.append(
            Attempt("preprint_server", "failed", f"{jats_url} returned {response.status_code}")
        )
        return None
    text = response.text
    if "<article" not in text[:4000]:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "failed",
                f"{jats_url} did not return a JATS article, most likely a Cloudflare challenge",
            )
        )
        return None

    record.attempts.append(Attempt("preprint_server", "ok", f"JATS from {server}"))
    return Fetched(kind="jats", body=response.content, url=jats_url, title=record.title)


def oa_locations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The open-access locations in a resolver's answer, best first, deduplicated.

    The resolver's own preferred location is put first and the rest follow,
    because the preferred one frequently names only a landing page while a later
    one has the PDF itself. Its vocabulary for host and version is carried
    through unchanged: mapping it onto ours would make a value it adds later look
    invalid, and the distinction that matters here — a submitted version is the
    manuscript before review, so a location offering only that is a preprint of
    the paper — is one a reader makes, not one to bake in.
    """
    ordered: list[dict[str, Any]] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        ordered.append(best)
    for location in payload.get("oa_locations") or []:
        if isinstance(location, dict):
            ordered.append(location)

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for location in ordered:
        url = location.get("url") or ""
        pdf = location.get("url_for_pdf") or ""
        if not url and not pdf:
            continue
        key = (url, pdf)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, Any] = {}
        for source_key, target_key in (
            ("url", "url"),
            ("url_for_pdf", "url_for_pdf"),
            ("host_type", "host_type"),
            ("version", "version"),
        ):
            value = location.get(source_key)
            if value:
                entry[target_key] = str(value)
        out.append(entry)
    return out


def download_pdf(url: str, ctx: Context) -> tuple[bytes | None, str]:
    """Download a PDF, working around hosts that fingerprint the client.

    Several publishers and repositories answer an ordinary Python HTTP client
    with a 403 or a challenge page while serving the same URL to a browser. The
    project already keeps TLS impersonation for the preprint server, and it is
    the difference between getting a paper and not on at least one host in the
    reference corpus, so it is tried first here too. Neither client gets past a
    host that genuinely requires a subscription.

    Args:
        url: The PDF link.
        ctx: The shared client, used when impersonation is unavailable.

    Returns:
        The bytes and an empty note, or ``None`` and why not. A response that is
        not a PDF is a failure however healthy its status code: a challenge page
        arrives as a cheerful 200.
    """
    attempts: list[str] = []
    # The two clients return their own Response classes; only status_code and
    # content are read, so the getters are typed by what they have in common.
    getters: list[tuple[str, Callable[[], Any]]] = []
    try:
        from curl_cffi import requests as impersonating
    except ImportError:
        pass
    else:
        getters.append(
            ("impersonated", lambda: impersonating.get(url, impersonate="chrome120", timeout=120))
        )
    getters.append(("plain", lambda: ctx.client.get(url, timeout=120, follow_redirects=True)))

    for name, get in getters:
        try:
            response = get()
        except Exception as exc:
            attempts.append(f"{name}: {exc}")
            continue
        if response.status_code != 200:
            attempts.append(f"{name}: returned {response.status_code}")
            continue
        body = response.content
        if not body.startswith(b"%PDF"):
            attempts.append(f"{name}: returned {len(body)} bytes that are not a PDF")
            continue
        return body, ""
    return None, "could not be downloaded (" + "; ".join(attempts) + ")"


def _rung_unpaywall(doi: str, record: Retrieval, ctx: Context) -> Fetched | None:
    """An open-access PDF, where a resolver knows of one.

    Every location the resolver named is recorded, used or not, because deciding
    whether a location is the paper or a preprint of it cannot be done after the
    fact from a URL. Only locations naming the PDF directly are downloaded: a
    landing page would have to be scraped, which is fragile enough that the ask
    route is the better answer.
    """
    address = contact_email(ctx.contact)
    if not address:
        record.attempts.append(
            Attempt(
                "unpaywall",
                "skipped",
                "an open-access resolver needs a contact address; set "
                f"{CONTACT_ENV} or a git user.email",
            )
        )
        return None

    url = f"{UNPAYWALL_BASE}/{urllib.parse.quote(doi)}?{urllib.parse.urlencode({'email': address})}"
    try:
        response = ctx.client.get(url, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        record.attempts.append(Attempt("unpaywall", "failed", f"lookup errored: {exc}"))
        return None

    if payload.get("title") and not record.title:
        record.title = str(payload["title"]).rstrip(".")
    locations = oa_locations(payload)
    record.oa_candidates = locations

    if not payload.get("is_oa") or not locations:
        record.attempts.append(
            Attempt("unpaywall", "unavailable", "no open-access location for this DOI")
        )
        return None

    with_pdf = [loc for loc in locations if loc.get("url_for_pdf")]
    if not with_pdf:
        described = "; ".join(
            f"{loc.get('host_type', 'unknown host')}/{loc.get('version', 'unknown version')}"
            for loc in locations
        )
        record.attempts.append(
            Attempt(
                "unpaywall",
                "unavailable",
                f"{len(locations)} open-access location(s) but none names a PDF ({described}); "
                "only landing pages are on offer",
            )
        )
        return None

    failures: list[str] = []
    for location in with_pdf:
        pdf_url = location["url_for_pdf"]
        body, note = download_pdf(pdf_url, ctx)
        if body is None:
            failures.append(f"{pdf_url} {note}")
            continue
        location["used"] = True
        record.attempts.append(
            Attempt(
                "unpaywall",
                "ok",
                f"PDF from {location.get('host_type', 'unknown host')} "
                f"({location.get('version', 'unknown version')})",
            )
        )
        return Fetched(kind="pdf", body=body, url=pdf_url, title=record.title)

    record.attempts.append(
        Attempt(
            "unpaywall",
            "failed",
            f"{len(with_pdf)} PDF link(s) named but none downloaded: " + "; ".join(failures),
        )
    )
    return None


#: The waterfall, in order. Each rung takes the DOI, the record it appends its
#: attempt to, and a shared client; it returns bytes or nothing.
RUNGS: tuple[tuple[str, Any], ...] = (
    ("europepmc", _rung_europepmc),
    ("preprint_server", _rung_preprint_server),
    ("unpaywall", _rung_unpaywall),
)


# ------------------------------------------------------------------
# The waterfall
# ------------------------------------------------------------------


def settled(record: Retrieval) -> bool:
    """Whether an earlier failure to retrieve this paper is worth believing.

    The negative cache exists so that a paper nobody can get is not re-requested
    on every pass. It should only hold where the rungs actually answered. A rung
    that broke, or that could not run because something was not installed, has
    established nothing about the paper — and if that counted as settled, an
    afternoon's outage would leave a retrievable paper permanently marked as
    unreachable.
    """
    return all(attempt.outcome == "unavailable" for attempt in record.attempts)


def _reusable(out_root: str | Path, doi: str) -> Retrieval | None:
    """An existing record whose stored bytes are still there and unchanged."""
    record = read_record(out_root, doi)
    if record is None or record.route == "none" or not record.path:
        return None
    source = paper_dir(out_root, doi) / record.path
    if not source.is_file():
        return None
    if record.sha256 and hashlib.sha256(source.read_bytes()).hexdigest() != record.sha256:
        logger.info("%s: stored source no longer matches its digest, re-fetching", doi)
        return None
    return record


def _gap_for(doi: str, record: Retrieval, out_root: str | Path) -> dict[str, str]:
    """What to ask a user for, said in terms they can act on.

    Where a resolver named an open-access landing page it could not download
    from, that page is the best place to send someone: it is a copy of the paper
    that is free to read, and the only reason it is not here already is that the
    host will not serve it to a script.
    """
    named = f'"{record.title}" ({doi})' if record.title else doi
    reasons = "; ".join(
        f"{a.route} {a.outcome}" + (f" — {a.note}" if a.note else "") for a in record.attempts
    )
    pages = [loc["url"] for loc in record.oa_candidates if loc.get("url")]
    where = (
        f"an open-access copy is at {pages[0]}"
        if pages
        else f"the paper is at https://doi.org/{doi}"
    )
    return {
        "what": named,
        "reason": f"no route produced the text: {reasons}",
        "action": (
            f"{where} — download the PDF or article XML, put it anywhere the project "
            "keeps supplied inputs, and take it in with "
            f"`cli_paper adopt --out {out_root} --doi {doi} --file <path>`"
        ),
    }


def fetch_paper(
    doi: str,
    out_root: str | Path,
    *,
    retry: bool = False,
    allow_pdf: bool = True,
    contact: str | None = None,
    timeout: float = 60.0,
) -> Retrieval:
    """Walk the waterfall for one paper and write its record.

    Args:
        doi: The paper to get.
        out_root: Directory the papers live under. This paper gets its own
            subdirectory, named from its DOI.
        retry: Try the routes again for a paper an earlier run could not get.
            Without this, a paper already recorded as unreachable is left alone —
            which is the point of recording it.
        allow_pdf: Whether to accept a PDF. Turning this off keeps a corpus to
            tagged article XML, at the cost of the papers only available as PDFs.
        contact: Contact address for a resolver that requires one. Defaults to
            the environment, then the git identity.
        timeout: Per-request timeout, in seconds.

    Returns:
        The record, already written to disk. A record with route ``none`` is a
        normal outcome and carries a gap saying what to ask the user for.
    """
    reused = _reusable(out_root, doi)
    if reused is not None:
        logger.info("%s: already here via %s", doi, reused.route)
        return reused

    previous = read_record(out_root, doi)
    if previous is not None and previous.route == "none" and not retry and settled(previous):
        logger.info("%s: recorded as unreachable by every route; pass retry to try again", doi)
        return previous

    record = Retrieval(doi=doi, attempted_at=_now())
    if previous is not None and previous.title:
        record.title = previous.title

    address = contact_email(contact)
    headers = {"User-Agent": f"atlas-chat paper retrieval ({address or 'no contact address'})"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        ctx = Context(client=client, contact=address)
        fetched: Fetched | None = None
        for name, rung in RUNGS:
            fetched = rung(doi, record, ctx)
            if fetched is None:
                continue
            if fetched.kind == "pdf" and not allow_pdf:
                record.attempts[-1] = Attempt(
                    name,
                    "skipped",
                    f"a PDF was available at {fetched.url} but PDFs were declined",
                )
                fetched = None
                continue
            break

    if fetched is None:
        record.route = "none"
        record.gap = _gap_for(doi, record, out_root)
    else:
        record.route = next(a.route for a in reversed(record.attempts) if a.outcome == "ok")
        _store(record, out_root, fetched)

    write_record(record, out_root)
    return record


# ------------------------------------------------------------------
# Taking in a file a user supplied
# ------------------------------------------------------------------


def _kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".xml", ".jats", ".nxml"):
        return "jats"
    raise PaperFetchError(
        f"{path.name} is neither a PDF nor article XML; a paper has to be one or the other"
    )


def adopt(doi: str, out_root: str | Path, file_path: str | Path) -> Retrieval:
    """Take a file a user supplied and record it as this paper's source.

    A supplied file is a route like any other, and for some papers it is the only
    route there is. What it is not is unchecked: a PDF that is really an HTML
    error page, or XML that is really a landing page, would otherwise be read as
    the paper.

    Args:
        doi: The paper the file is.
        out_root: Directory the papers live under.
        file_path: The file, wherever the user put it.

    Returns:
        The record, already written.

    Raises:
        PaperFetchError: The file is missing, the wrong sort of thing, or does not
            contain what its extension claims.
    """
    source = Path(file_path)
    if not source.is_file():
        raise PaperFetchError(f"no such file: {source}")
    kind = _kind_of(source)
    body = source.read_bytes()

    if kind == "pdf" and not body.startswith(b"%PDF"):
        raise PaperFetchError(f"{source.name} has a .pdf name but does not start with %PDF")
    if kind == "jats":
        head = body[:4000].decode("utf-8", errors="replace")
        if "<article" not in head:
            raise PaperFetchError(
                f"{source.name} has an XML name but no <article> element in its opening — "
                "a saved landing page rather than article XML?"
            )

    record = Retrieval(doi=doi, route="manual", attempted_at=_now())
    existing = read_record(out_root, doi)
    if existing is not None and existing.title:
        record.title = existing.title
    record.attempts.append(Attempt("manual", "ok", f"supplied by hand, copied from {source}"))

    _store(record, out_root, Fetched(kind=kind, body=body))

    write_record(record, out_root)
    return record


# ------------------------------------------------------------------
# Reading a bag of supplied files
# ------------------------------------------------------------------


def _xml_identity(path: Path) -> tuple[str | None, str | None]:
    """The DOI and title an article XML declares, from its opening."""
    import xml.etree.ElementTree as ET

    try:
        head = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    doi = None
    for match in _DOI_RE.finditer(head[:200_000]):
        doi = match.group(0)
        break
    title = None
    try:
        root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", head, count=1))
        for element in root.iter():
            tag = element.tag.split("}", 1)[-1]
            if tag == "article-title":
                title = re.sub(r"\s+", " ", " ".join(element.itertext())).strip()
                break
    except ET.ParseError:
        pass
    return doi, title


def _pdf_identity(path: Path) -> tuple[str | None, str | None]:
    """The DOI and a title guess from a PDF's first page.

    Only the first page is read. Reading a whole PDF to work out which paper it
    is would cost as much as reading the paper.
    """
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore[no-redef,import-untyped]
        except ImportError:
            return None, None
    try:
        with pymupdf.open(path) as document:
            if not len(document):
                return None, None
            text = document[0].get_text()
    except Exception:
        return None, None

    doi = None
    for match in _DOI_RE.finditer(text):
        doi = match.group(0).rstrip(".,;)")
        break
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 25]
    return doi, lines[0] if lines else None


def candidates(inputs_dir: str | Path) -> list[dict[str, Any]]:
    """Every file under a directory that could be a paper, described well enough to place.

    A drop zone is a flat bag with papers, spreadsheets and figures in it, and
    nobody is asked to name files a particular way. So this says what each
    candidate is — the DOI it declares, the title it opens with, how big it is —
    and leaves matching files to papers to a reader, which is a judgement and not
    a pattern match.

    Args:
        inputs_dir: The directory to look in, searched recursively.

    Returns:
        One entry per candidate, in path order.
    """
    root = Path(inputs_dir)
    if not root.is_dir():
        raise PaperFetchError(f"no such directory: {root}")

    out: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in PAPER_SUFFIXES:
            continue
        kind = "pdf" if path.suffix.lower() == ".pdf" else "jats"
        doi, title = _pdf_identity(path) if kind == "pdf" else _xml_identity(path)
        entry: dict[str, Any] = {
            "path": str(path),
            "relative_path": str(path.relative_to(root)),
            "kind": kind,
            "n_bytes": path.stat().st_size,
        }
        if doi:
            entry["doi"] = doi
        if title:
            entry["title"] = title[:300]
        if kind == "pdf" and doi is None and title is None:
            entry["note"] = (
                "could not be read; PyMuPDF is missing (uv sync --extra text-access) "
                "or the PDF has no text on page 1"
            )
        out.append(entry)
    return out
