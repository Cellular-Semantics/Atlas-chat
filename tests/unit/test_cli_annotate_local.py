"""`cli_annotate fetch --local` — retrieval from the project's own snippet index.

Without this path, a corpus paper at ``status: local`` is unreachable from the
agentic route. Those are exactly the papers that most often *define* an inherited
cell type: a subatlas gets a local index built from JATS or a publisher PDF
precisely because ASTA holds too little of it to quote. The local index previously
only fed the programmatic graph, so the two runtimes were not equivalent.

Both sources must produce the same ``annotated_snippet`` record shape, so
downstream steps cannot tell them apart.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from atlas_chat import cli_annotate
from atlas_chat.services import local_snippet_index as lsi

pytestmark = pytest.mark.unit


class _FakeEmbedder:
    """Two axes: how 'atlas' and how 'subatlas' a text is."""

    def encode(self, texts, convert_to_numpy=True, **kwargs):
        out = []
        for t in texts:
            low = t.lower()
            out.append([float("atlas" in low), float("apcv" in low or "venule" in low)])
        return np.array(out)


def _write_paper(project_dir: Path, slug: str, doi: str, role: str, text: str, vec):
    p_dir = project_dir / "local_index" / "papers" / slug
    (p_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (p_dir / "snippet_index").mkdir(parents=True, exist_ok=True)
    chunk = {
        "chunk_id": 0,
        "section": "Results",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
    }
    (p_dir / "chunks" / "chunks.jsonl").write_text(json.dumps(chunk) + "\n")
    np.save(p_dir / "chunks" / "embeddings.npy", np.array([vec]))
    (p_dir / "chunks" / "window_index.json").write_text(
        json.dumps({"n_chunks": 1, "n_windows": 1, "rows": [0]})
    )
    paper_meta = {
        "corpus_id": lsi._local_corpus_id(doi),
        "title": f"Paper {slug}",
        "authors": "Test, A.",
        "year": 2024,
        "doi": doi,
        "url": f"https://doi.org/{doi}",
    }
    (p_dir / "snippet_index" / "snippets.json").write_text(
        json.dumps(
            [
                {
                    "chunk_id": 0,
                    "paper": paper_meta,
                    "snippet": {
                        "text": text,
                        "section": "Results",
                        "annotations": {"refMentions": []},
                    },
                }
            ]
        )
    )
    manifest = {
        "version": lsi.MANIFEST_VERSION,
        "slug": slug,
        "doi": doi,
        "role": role,
        "source_type": "jats",
        "paper": paper_meta,
        "n_chunks": 1,
    }
    (p_dir / "manifest.json").write_text(json.dumps(manifest))
    return manifest


ATLAS_DOI = "10.1/atlas"
ULRICH_DOI = "10.1073/pnas.2404775121"


@pytest.fixture
def project(tmp_path, monkeypatch):
    # Slugs are derived from the DOI in a real index, and `search(papers=...)`
    # filters on that derivation — so a fixture with arbitrary slug names would
    # make the paper filter silently match nothing.
    atlas_slug = lsi.paper_slug(ATLAS_DOI)
    ulrich_slug = lsi.paper_slug(ULRICH_DOI)
    _write_paper(
        tmp_path,
        atlas_slug,
        ATLAS_DOI,
        "atlas",
        "Atlas integration methods for the reproductive atlas",
        [1.0, 0.0],
    )
    _write_paper(
        tmp_path,
        ulrich_slug,
        ULRICH_DOI,
        "subatlas",
        "activated post-capillary venules (aPCV) upregulated SELE and ICAM1",
        [0.0, 1.0],
    )
    corpus = lsi._empty_corpus(ATLAS_DOI)
    corpus["papers"] = [
        {"slug": atlas_slug, "doi": ATLAS_DOI, "role": "atlas", "n_chunks": 1},
        {"slug": ulrich_slug, "doi": ULRICH_DOI, "role": "subatlas", "n_chunks": 1},
    ]
    (tmp_path / "local_index" / "corpus.json").write_text(json.dumps(corpus))

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = lambda *a, **k: _FakeEmbedder()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    lsi._load_index.cache_clear()
    lsi._get_embedder.cache_clear()
    return tmp_path


def _fetch_local(project, out, **extra):
    argv = [
        "fetch",
        "--query",
        "aPCV definition and markers",
        "--local",
        "--project-dir",
        str(project),
        "--role",
        "subatlas",
        "--retrieval-method",
        "corpus_snippet",
        "--out",
        str(out),
    ]
    for key, value in extra.items():
        argv += [f"--{key.replace('_', '-')}", value]
    return cli_annotate.main(argv)


def test_local_fetch_produces_annotated_snippet_records(project, tmp_path):
    out = tmp_path / "snips.json"
    assert _fetch_local(project, out) == 0
    records = json.loads(out.read_text())
    assert records
    record = records[0]
    # Same shape as an ASTA fetch: text to quote from, annotated_text to gate on,
    # provenance stamped.
    assert "text" in record and "annotated_text" in record
    assert record["source_paper"]["role"] == "subatlas"
    assert record["retrieval_method"] == "corpus_snippet"


def test_records_validate_against_the_annotated_snippet_schema(project, tmp_path):
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "src/atlas_chat/atlas_chat/schemas/annotated_snippet.schema.json"
        ).read_text()
    )
    out = tmp_path / "snips.json"
    _fetch_local(project, out)
    records = json.loads(out.read_text())
    assert records, "no snippets retrieved — an empty result must not pass as valid"
    validator = Draft202012Validator(schema)
    for record in records:
        assert list(validator.iter_errors(record)) == []


def test_papers_filter_restricts_to_one_contributor(project, tmp_path):
    out = tmp_path / "snips.json"
    _fetch_local(project, out, papers=ULRICH_DOI)
    records = json.loads(out.read_text())
    assert len(records) == 1
    assert "aPCV" in records[0]["text"]


def test_roles_filter_excludes_the_atlas_paper(project, tmp_path):
    out = tmp_path / "snips.json"
    _fetch_local(project, out, roles="subatlas")
    records = json.loads(out.read_text())
    assert len(records) == 1
    assert "10.1/atlas" not in {r["source_paper"].get("doi") for r in records}


def test_source_paper_doi_falls_back_to_the_requested_paper(project, tmp_path):
    """Local corpus ids are synthetic `local_<hash>`; the DOI is what resolves."""
    out = tmp_path / "snips.json"
    _fetch_local(project, out, papers=ULRICH_DOI)
    source = json.loads(out.read_text())[0]["source_paper"]
    assert source["doi"] == ULRICH_DOI


def test_local_requires_a_project_dir(tmp_path, capsys):
    rc = cli_annotate.main(
        [
            "fetch",
            "--query",
            "x",
            "--local",
            "--role",
            "subatlas",
            "--retrieval-method",
            "corpus_snippet",
            "--out",
            str(tmp_path / "o.json"),
        ]
    )
    assert rc == 2
    assert "--local requires --project-dir" in capsys.readouterr().err


def test_the_summary_line_says_which_source_was_used(project, tmp_path, capsys):
    _fetch_local(project, tmp_path / "snips.json")
    assert "fetch (local index)" in capsys.readouterr().out
