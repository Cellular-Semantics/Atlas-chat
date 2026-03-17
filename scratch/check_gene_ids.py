#!/usr/bin/env python3
"""
PreToolUse hook: validate GeneDescriptor {symbol, ncbi_gene_id} pairs.

For every {symbol: X, ncbi_gene_id: NCBIGene:N} dict in newly written text:
  1. Validate NCBIGene CURIE format (fast, always — blocks on bad format)
  2. Cross-check symbol against NCBI Gene via eutils (batched, cached)
     — blocks only on confirmed mismatches; silent-passes on network failure

Cache: ~/.cache/evidencell/ncbigene.json
  Maps numeric gene ID → {"symbol": "SST", "checked_at": "YYYY-MM-DD"}
  Stale-cache sweeps are a CI/QC job, not a hook concern.

Batching: all uncached IDs in the new text are sent in ONE eutils call,
so a file with 10 novel genes costs one HTTP round-trip (~300–500 ms).

Exit codes (Claude Code hook protocol):
  0 = allow edit
  2 = block edit (stderr shown to Claude for self-correction)

Portable to evidencell: update CACHE_PATH and KB_PATTERN only.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

CACHE_PATH = Path.home() / ".cache" / "evidencell" / "ncbigene.json"

EUTILS_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=gene&retmode=json&id={ids}"
)

TIMEOUT = 5  # seconds; silent-pass on timeout

NCBIGENE_RE = re.compile(r"^NCBIGene:(\d+)$")

SEP = "─" * 60


# ── Path filter ─────────────────────────────────────────────────────────────

def matches_kb(path: Path) -> bool:
    parts = path.parts
    return "kb" in parts and "mappings" in parts and path.suffix == ".yaml"


# ── Extract new text only ───────────────────────────────────────────────────

def new_text(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    if tool_name == "MultiEdit":
        return "\n".join(e.get("new_string", "") for e in tool_input.get("edits", []))
    return ""


# ── Find gene pairs ─────────────────────────────────────────────────────────

def find_gene_pairs(obj) -> list[tuple[str, str]]:
    """
    Yield (symbol, ncbi_gene_id) for every dict that has both keys,
    recursively traversing lists and dicts.
    """
    pairs: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        if "symbol" in obj and "ncbi_gene_id" in obj:
            sym = obj.get("symbol")
            gid = obj.get("ncbi_gene_id")
            if isinstance(sym, str) and isinstance(gid, str):
                pairs.append((sym, gid))
        for v in obj.values():
            pairs.extend(find_gene_pairs(v))
    elif isinstance(obj, list):
        for item in obj:
            pairs.extend(find_gene_pairs(item))
    return pairs


# ── Cache helpers ────────────────────────────────────────────────────────────

def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass  # Cache write failures are non-fatal


# ── NCBI eutils batch lookup ─────────────────────────────────────────────────

def fetch_symbols(numeric_ids: list[str]) -> dict[str, str]:
    """
    Fetch official gene symbols for a list of numeric NCBI Gene IDs.
    Returns {numeric_id: official_symbol}.  Empty dict on any error.
    """
    if not numeric_ids:
        return {}
    url = EUTILS_URL.format(ids=",".join(numeric_ids))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("result", {})
        return {
            nid: result[nid]["name"]
            for nid in numeric_ids
            if nid in result and "name" in result[nid]
        }
    except Exception:
        return {}  # Network/parse failure — caller treats as "skip live check"


# ── Main ─────────────────────────────────────────────────────────────────────

def block(reason: str) -> None:
    print(f"\n  ❌ EDIT BLOCKED: {reason}", file=sys.stderr)
    print(f"{SEP}\n", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name not in ("Edit", "MultiEdit", "Write"):
        sys.exit(0)

    file_path = Path(tool_input.get("file_path", ""))
    if not matches_kb(file_path):
        sys.exit(0)

    text = new_text(tool_name, tool_input)
    if not text.strip():
        sys.exit(0)

    # Parse YAML — if it fails, the main schema hook will catch it
    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load(text) or {}
    except Exception:
        sys.exit(0)

    pairs = find_gene_pairs(doc)
    if not pairs:
        sys.exit(0)

    print(f"\n{SEP}", file=sys.stderr)
    print(f"Gene ID check  ·  {file_path.name}", file=sys.stderr)
    print(SEP, file=sys.stderr)

    # ── Step 1: format check (always, fast) ──────────────────────────────────
    format_errors: list[str] = []
    valid_pairs: list[tuple[str, str, str]] = []  # (symbol, curie, numeric_id)

    for symbol, curie in pairs:
        m = NCBIGENE_RE.match(curie)
        if not m:
            format_errors.append(
                f"  ✗ '{curie}' is not a valid NCBIGene CURIE (expected NCBIGene:<digits>)"
            )
        else:
            valid_pairs.append((symbol, curie, m.group(1)))

    if format_errors:
        for e in format_errors:
            print(e, file=sys.stderr)
        block("invalid NCBIGene CURIE format — fix the IDs listed above")

    # ── Step 2: symbol cross-check via eutils (batched + cached) ─────────────
    cache = load_cache()
    today = date.today().isoformat()

    uncached_ids = [nid for _, _, nid in valid_pairs if nid not in cache]

    if uncached_ids:
        print(f"  Fetching {len(uncached_ids)} gene(s) from NCBI eutils...", file=sys.stderr)
        fetched = fetch_symbols(uncached_ids)
        if fetched:
            for nid, official in fetched.items():
                cache[nid] = {"symbol": official, "checked_at": today}
            save_cache(cache)
        else:
            print("  ⚠  eutils unreachable — skipping live symbol check", file=sys.stderr)
            print(f"  ✓ Format OK ({len(valid_pairs)} gene(s)); live check skipped", file=sys.stderr)
            print(f"{SEP}\n", file=sys.stderr)
            sys.exit(0)

    # ── Step 3: compare symbols ───────────────────────────────────────────────
    mismatch_errors: list[str] = []
    for symbol, curie, nid in valid_pairs:
        if nid not in cache:
            continue  # ID not returned by eutils — skip silently
        official = cache[nid]["symbol"]
        if symbol.lower() != official.lower():
            mismatch_errors.append(
                f"  ✗ {curie}: claimed symbol '{symbol}', "
                f"NCBI official is '{official}' "
                f"(species capitalisation differences are OK — check manually if unsure)"
            )

    if mismatch_errors:
        for e in mismatch_errors:
            print(e, file=sys.stderr)
        block("gene symbol/ID mismatch — correct the symbol or the NCBIGene ID")

    print(f"  ✓ All {len(valid_pairs)} gene(s) OK", file=sys.stderr)
    print(f"{SEP}\n", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
