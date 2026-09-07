"""cli_annotate route / read / follow-check — the JATS-native traversal commands.

follow-check is the anti-hallucination gate for JATS nodes: the reference list is
closed, so a proposal not in the paper's own cited_sentences must be rejected, a
real one accepted with its citing sentence attached, and an already-traversed
target deduplicated rather than refetched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_chat.services.local_snippet_index import paper_slug

from atlas_chat import cli_annotate

pytestmark = pytest.mark.unit

DOI = "10.1038/s41586-024-08002-x"
XML = """<article><body><sec><title>Results</title>
<p>Macrophages arise from the yolk sac<sup><xref ref-type="bibr" rid="R1">1</xref></sup>.
Unrelated sentence.</p>
</sec></body>
<back><ref-list><ref id="R1"><element-citation>
<article-title>Yolk sac origins</article-title>
<name><surname>Goh</surname></name><year>2023</year>
<pub-id pub-id-type="doi">10.1000/goh</pub-id>
</element-citation></ref></ref-list></back></article>"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    src = tmp_path / "local_index" / "papers" / paper_slug(DOI) / "source"
    src.mkdir(parents=True)
    (src / "paper.jats.xml").write_text(XML)
    return tmp_path


def test_route_cache_hit(project: Path, capsys) -> None:
    rc = cli_annotate.main(
        ["route", "--paper", f"DOI:{DOI}", "--project-dir", str(project), "--no-probe"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["method"] == "jats"
    assert out["source"] == "cache"


def test_read_writes_job_and_marks_traversed(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "paper.json"
    traversed = tmp_path / "out" / "traversed.json"
    rc = cli_annotate.main(
        [
            "read",
            "--paper",
            f"DOI:{DOI}",
            "--project-dir",
            str(project),
            "--out",
            str(out),
            "--traversed",
            str(traversed),
        ]
    )
    assert rc == 0
    job = json.loads(out.read_text())
    assert "yolk sac" in job["narrative_text"]
    assert job["cited_sentences"][0]["resolved_refs"][0]["doi"] == "10.1000/goh"
    assert job["route"]["method"] == "jats"
    assert DOI in json.loads(traversed.read_text())


def test_read_non_jats_route_exits_3(tmp_path: Path, monkeypatch, capsys) -> None:
    from atlas_chat.services import paper_router

    monkeypatch.setattr(
        paper_router,
        "resolve_route",
        lambda *a, **k: paper_router.Route("CorpusId:9", None, "asta", band="full"),
    )
    rc = cli_annotate.main(["read", "--paper", "CorpusId:9", "--out", str(tmp_path / "x.json")])
    assert rc == 3
    assert json.loads(capsys.readouterr().out)["method"] == "asta"


def _job_file(tmp_path: Path, project: Path) -> Path:
    out = tmp_path / "paper.json"
    cli_annotate.main(
        ["read", "--paper", f"DOI:{DOI}", "--project-dir", str(project), "--out", str(out)]
    )
    return out


def test_follow_check_accepts_real_ref(project: Path, tmp_path: Path) -> None:
    job = _job_file(tmp_path, project)
    out = tmp_path / "follow.json"
    rc = cli_annotate.main(
        ["follow-check", "--paper-json", str(job), "--proposed", "R1", "--out", str(out)]
    )
    assert rc == 0
    result = json.loads(out.read_text())
    assert len(result["follow"]) == 1
    target = result["follow"][0]
    assert target["doi"] == "10.1000/goh"
    assert "yolk sac" in target["citation_context"]
    assert result["rejected"] == []


def test_follow_check_accepts_doi_form(project: Path, tmp_path: Path) -> None:
    job = _job_file(tmp_path, project)
    out = tmp_path / "follow.json"
    cli_annotate.main(
        [
            "follow-check",
            "--paper-json",
            str(job),
            "--proposed",
            "DOI:10.1000/goh",
            "--out",
            str(out),
        ]
    )
    result = json.loads(out.read_text())
    assert len(result["follow"]) == 1


def test_follow_check_rejects_invented_ref(project: Path, tmp_path: Path) -> None:
    job = _job_file(tmp_path, project)
    out = tmp_path / "follow.json"
    cli_annotate.main(
        ["follow-check", "--paper-json", str(job), "--proposed", "R99", "--out", str(out)]
    )
    result = json.loads(out.read_text())
    assert result["follow"] == []
    assert result["rejected"][0]["reason"] == "not_in_reference_list"


def test_follow_check_dedups_against_traversed(project: Path, tmp_path: Path) -> None:
    from atlas_chat.services import paper_router

    job = _job_file(tmp_path, project)
    traversed = tmp_path / "traversed.json"
    paper_router.mark_traversed(traversed, "10.1000/goh")
    out = tmp_path / "follow.json"
    cli_annotate.main(
        [
            "follow-check",
            "--paper-json",
            str(job),
            "--proposed",
            "R1",
            "--traversed",
            str(traversed),
            "--out",
            str(out),
        ]
    )
    result = json.loads(out.read_text())
    assert result["follow"] == []
    assert result["rejected"][0]["reason"] == "already_traversed"
