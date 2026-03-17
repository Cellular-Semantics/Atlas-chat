"""Shared validation logic for cell-type reports.

Consumed by:
1. Claude Code hook (``.claude/hooks/check_report_refs.py``) — exits 2 on failure
2. PydanticAI graph — validation node routes failures back to synthesis
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def check_quotes(
    report_md: str,
    summaries: list[dict[str, object]],
    atlas_snippets: list[str],
) -> list[str]:
    """Return error messages for quotes in the report not found in evidence.

    Extracts all blockquote lines (``> "..."``), then checks each against the
    concatenated evidence corpus (traversal summaries + atlas snippets).

    Args:
        report_md: The full markdown report text.
        summaries: List of per-snippet summary dicts, each expected to contain
            a ``"quotes"`` key with a list of strings.
        atlas_snippets: Raw text snippets from the atlas paper / supplements.

    Returns:
        List of error strings.  Empty means all quotes verified.
    """
    errors: list[str] = []

    # Build evidence corpus from all summary quotes and atlas snippets
    evidence_texts: list[str] = list(atlas_snippets)
    for s in summaries:
        for q in s.get("quotes", []):  # type: ignore[union-attr]
            if isinstance(q, str):
                evidence_texts.append(q)
        # Also include the summary text itself as context
        if isinstance(s.get("summary"), str):
            evidence_texts.append(s["summary"])  # type: ignore[arg-type]
        # ASTA snippet search results use "snippet" key
        if isinstance(s.get("snippet"), str):
            evidence_texts.append(s["snippet"])  # type: ignore[arg-type]

    evidence_corpus = "\n".join(evidence_texts)

    # Extract quoted text from blockquotes: > "some text"
    quote_pattern = re.compile(r'>\s*"([^"]+)"')
    for match in quote_pattern.finditer(report_md):
        quote = match.group(1)
        # Check if the quote appears as a substring in any evidence source
        if not _quote_in_evidence(quote, evidence_texts):
            errors.append(f'Quote not found in evidence: "{quote[:80]}..."')

    return errors


def _quote_in_evidence(quote: str, evidence_texts: list[str]) -> bool:
    """Check if a quote is a substring of any evidence text.

    Uses case-insensitive matching and allows minor whitespace differences.
    """
    normalised_quote = _normalise_ws(quote.lower())
    for text in evidence_texts:
        if normalised_quote in _normalise_ws(text.lower()):
            return True
    return False


def _normalise_ws(text: str) -> str:
    """Collapse runs of whitespace to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def check_references(
    report_md: str,
    catalogue: dict[str, object],
) -> list[str]:
    """Return error messages for reference IDs in the report not in the catalogue.

    Scans for ``CorpusId:NNN`` patterns in the report and verifies each
    against the paper catalogue.

    Args:
        report_md: The full markdown report text.
        catalogue: Paper catalogue dict, keyed by corpus ID string.

    Returns:
        List of error strings.  Empty means all references verified.
    """
    errors: list[str] = []

    # Build set of known IDs from catalogue keys (normalised)
    known_ids: set[str] = set()
    for key in catalogue:
        # Accept keys like "2762329", "CorpusId:2762329"
        clean = str(key).replace("CorpusId:", "").strip()
        known_ids.add(clean)

    # Find all CorpusId references in the report
    ref_pattern = re.compile(r"CorpusId:(\d+)")
    found_ids = set(ref_pattern.findall(report_md))

    for cid in sorted(found_ids):
        if cid not in known_ids:
            errors.append(f"Unknown reference CorpusId:{cid} — not in paper catalogue")

    return errors


def validate_report(
    report_path: Path,
    traversal_dir: Path,
) -> tuple[bool, list[str]]:
    """Full validation of a generated report against its evidence files.

    Args:
        report_path: Path to the markdown report file.
        traversal_dir: Directory containing traversal output files
            (``all_summaries.json``, ``paper_catalogue.json``).

    Returns:
        Tuple of ``(passed, errors)`` where *passed* is ``True`` when there
        are no validation errors.
    """
    report_md = report_path.read_text()

    # Load summaries
    summaries_path = traversal_dir / "all_summaries.json"
    summaries: list[dict[str, object]] = []
    if summaries_path.exists():
        summaries = json.loads(summaries_path.read_text())

    # Load paper catalogue
    catalogue_path = traversal_dir / "paper_catalogue.json"
    catalogue: dict[str, object] = {}
    if catalogue_path.exists():
        catalogue = json.loads(catalogue_path.read_text())

    # Load any atlas snippets (supplementary findings have evidence_quotes)
    atlas_snippets: list[str] = []
    supp_path = traversal_dir / "supplementary_findings.json"
    if supp_path.exists():
        supp_data = json.loads(supp_path.read_text())
        for eq in supp_data.get("evidence_quotes", []):
            if isinstance(eq, dict) and isinstance(eq.get("quote"), str):
                atlas_snippets.append(eq["quote"])
            elif isinstance(eq, str):
                atlas_snippets.append(eq)

    # Include atlas paper full text if saved during fetch step
    fulltext_path = traversal_dir / "atlas_full_text.txt"
    if fulltext_path.exists():
        atlas_snippets.append(fulltext_path.read_text())

    errors: list[str] = []
    errors.extend(check_quotes(report_md, summaries, atlas_snippets))
    errors.extend(check_references(report_md, catalogue))

    return (len(errors) == 0, errors)
