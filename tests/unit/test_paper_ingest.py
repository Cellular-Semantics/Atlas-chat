"""Unit tests for assembling one paper's readable content."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from atlas_chat.services.paper_ingest import (
    CHARS_PER_TOKEN,
    PaperIngestError,
    extract_legends,
    ingest_paper,
    main,
    render,
    split_sections,
    supplement_prose,
    write_ingest,
)

from atlas_chat.schemas import load_schema

pytestmark = pytest.mark.unit


ARTICLE = """<article>
  <front><article-meta><abstract><p>An abstract sentence.</p></abstract></article-meta></front>
  <body>
    <sec><title>Results</title>
      <p>A population was identified in the tissue.</p>
      <p>It resembles one described before <xref ref-type="bibr" rid="R1">1</xref>.</p>
      <fig><label>Fig. 1</label><caption><p>ABC, a longer name for ABC.</p></caption></fig>
    </sec>
    <sec><title>Discussion</title><p>A closing thought.</p></sec>
    <sec><title>Methods</title><p>Cells were dissociated and sequenced.</p></sec>
  </body>
  <back><ref-list>
    <ref id="R1"><element-citation>
      <person-group><name><surname>Someone</surname></name></person-group>
      <article-title>An earlier description</article-title>
      <year>2020</year>
      <pub-id pub-id-type="doi">10.1234/earlier</pub-id>
    </element-citation></ref>
  </ref-list></back>
</article>
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


def test_split_sections_holds_out_process_sections_and_records_their_size():
    kept, excluded = split_sections(
        [("Results", "aaa"), ("Methods", "bbbb"), ("Discussion", "cc"), ("Methods", "d")]
    )
    assert [s for s, _ in kept] == ["Results", "Discussion"]
    assert excluded == [{"heading": "Methods", "n_chars": 5}]


def test_without_a_discussion_section_only_the_title_test_applies():
    """Position says nothing when there is no boundary to be after."""
    kept, excluded = split_sections([("", "orphan prose"), ("Tissue processing", "protocol")])
    assert len(kept) == 2
    assert excluded == []


def test_sections_after_the_last_discussion_are_held_out():
    kept, excluded = split_sections(
        [
            ("Results", "a finding"),
            ("Discussion", "a closing thought"),
            ("Tissue acquisition and processing", "a protocol"),
            ("H&E staining and imaging", "another protocol"),
        ]
    )
    assert [s for s, _ in kept] == ["Results", "Discussion"]
    assert {s["heading"] for s in excluded} == {
        "Tissue acquisition and processing",
        "H&E staining and imaging",
    }


def test_a_naming_section_is_kept_wherever_it_sits():
    """Cluster identifiers acquire their names in these sections."""
    kept, _ = split_sections(
        [
            ("Discussion", "a closing thought"),
            ("Tissue acquisition and processing", "a protocol"),
            ("Data integration and annotation", "clusters were named"),
            ("Methods", "a protocol"),
            ("Cell type annotation", "more naming"),
        ]
    )
    assert [s for s, _ in kept] == [
        "Discussion",
        "Data integration and annotation",
        "Cell type annotation",
    ]


def test_render_writes_each_heading_once():
    text = render([("Results", "one"), ("Results", "two"), ("Discussion", "three")])
    assert text.count("## Results") == 1
    assert text.index("## Results") < text.index("## Discussion")


def test_extract_legends_keeps_the_authors_label():
    legends = extract_legends(ARTICLE)
    assert legends == [{"label": "Fig. 1", "text": "ABC, a longer name for ABC."}]


# ------------------------------------------------------------------
# Assembly from article XML
# ------------------------------------------------------------------


def test_legend_text_is_not_in_the_narrative(tmp_path):
    """A caption must not read as though the authors wrote it in the body."""
    ingest = ingest_paper(_write(tmp_path, "article.xml", ARTICLE))
    assert "a longer name for ABC" in ingest.legends[0]["text"]
    assert "a longer name for ABC" not in ingest.narrative_text


def test_narrative_holds_results_and_discussion_but_not_methods(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "article.xml", ARTICLE))
    assert "A population was identified" in ingest.narrative_text
    assert "A closing thought" in ingest.narrative_text
    assert "dissociated and sequenced" not in ingest.narrative_text
    assert [s["heading"] for s in ingest.excluded_sections] == ["Methods"]
    assert ingest.excluded_sections[0]["n_chars"] > 0


def test_cited_sentences_resolve_to_the_reference_list(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "article.xml", ARTICLE), doi="10.1234/paper")
    assert ingest.cited_sentences, "a sentence carrying a citation should be recorded"
    assert any("R1" in cs["ref_ids"] for cs in ingest.cited_sentences)
    assert ingest.references["R1"]["doi"] == "10.1234/earlier"
    assert ingest.paper["doi"] == "10.1234/paper"


def test_pdf_text_records_that_no_citation_can_be_resolved(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "paper.txt", "Some recovered prose."))
    assert ingest.source_kind == "pdf_text"
    assert ingest.cited_sentences == []
    assert any("reference markup" in gap["reason"] for gap in ingest.gaps)


def test_empty_text_is_an_error_not_an_empty_ingest(tmp_path):
    with pytest.raises(PaperIngestError):
        ingest_paper(_write(tmp_path, "empty.txt", "   \n  "))


def test_unparseable_xml_is_an_error(tmp_path):
    with pytest.raises(PaperIngestError):
        ingest_paper(_write(tmp_path, "broken.xml", "<article><body>"))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(PaperIngestError):
        ingest_paper(tmp_path / "absent.xml")


# ------------------------------------------------------------------
# Supplementary prose
# ------------------------------------------------------------------


def _store_with_prose(tmp_path: Path, doi: str, pointers: list[dict]) -> Path:
    from atlas_chat.services.supplement_store import manifest_path

    root = tmp_path / "store"
    path = manifest_path(root, doi)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"manifest_version": 1, "paper": {"doi": doi}, "prose": pointers}),
        encoding="utf-8",
    )
    return root


def test_only_spans_marked_as_folding_in_are_carried(tmp_path):
    doi = "10.1234/paper"
    text = "KEEP THIS SPAN\n\nDROP THIS SPAN"
    root = _store_with_prose(
        tmp_path,
        doi,
        [
            {
                "file_id": "s1",
                "text_file": "extracted/s1.txt",
                "folds_in": True,
                "sections": [
                    {"heading": "Naming", "char_start": 0, "char_end": 14, "folds_in": True},
                    {"heading": "Protocol", "char_start": 16, "char_end": 30, "folds_in": False},
                ],
            }
        ],
    )
    (root / "extracted").mkdir(parents=True)
    (root / "extracted" / "s1.txt").write_text(text, encoding="utf-8")

    carried, gaps = supplement_prose(root, doi)
    assert gaps == []
    assert carried[0]["text"] == "KEEP THIS SPAN"
    assert carried[0]["headings"] == ["Naming"]


def test_a_pointer_without_section_picks_is_carried_whole(tmp_path):
    doi = "10.1234/paper"
    root = _store_with_prose(
        tmp_path, doi, [{"file_id": "s1", "text_file": "s1.txt", "folds_in": True}]
    )
    (root / "s1.txt").write_text("The whole document.", encoding="utf-8")
    carried, gaps = supplement_prose(root, doi)
    assert carried[0]["text"] == "The whole document."
    assert "headings" not in carried[0]
    assert gaps == []


def test_prose_that_does_not_fold_in_is_omitted_not_summarised(tmp_path):
    doi = "10.1234/paper"
    root = _store_with_prose(
        tmp_path, doi, [{"file_id": "s1", "text_file": "s1.txt", "folds_in": False}]
    )
    (root / "s1.txt").write_text("Sequencing protocol.", encoding="utf-8")
    carried, gaps = supplement_prose(root, doi)
    assert carried == []
    assert gaps == []


def test_unreadable_extracted_text_is_a_gap_not_a_silent_omission(tmp_path):
    doi = "10.1234/paper"
    root = _store_with_prose(
        tmp_path, doi, [{"file_id": "s1", "text_file": "missing.txt", "folds_in": True}]
    )
    carried, gaps = supplement_prose(root, doi)
    assert carried == []
    assert len(gaps) == 1 and "unreadable" in gaps[0]["reason"]


def test_no_manifest_is_a_gap(tmp_path):
    carried, gaps = supplement_prose(tmp_path / "store", "10.1234/absent")
    assert carried == []
    assert "no manifest" in gaps[0]["reason"]


def test_a_store_without_a_doi_cannot_be_used_and_says_so(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "a.xml", ARTICLE), store_root=tmp_path / "store")
    assert any("no DOI" in gap["reason"] for gap in ingest.gaps)


# ------------------------------------------------------------------
# Budget
# ------------------------------------------------------------------


def test_supplementary_prose_is_dropped_before_the_papers_own_text(tmp_path):
    doi = "10.1234/paper"
    root = _store_with_prose(
        tmp_path, doi, [{"file_id": "s1", "text_file": "s1.txt", "folds_in": True}]
    )
    (root / "s1.txt").write_text("x" * 4000, encoding="utf-8")

    ingest = ingest_paper(
        _write(tmp_path, "a.xml", ARTICLE), doi=doi, store_root=root, limit_tokens=200
    )
    assert ingest.truncated
    assert ingest.supplement_prose == []
    assert "A population was identified" in ingest.narrative_text
    assert any("read budget" in gap["reason"] for gap in ingest.gaps)


def test_narrative_is_only_cut_when_nothing_else_is_left_to_give(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "a.xml", ARTICLE), limit_tokens=1)
    assert ingest.truncated
    assert ingest.legends == []
    assert len(ingest.narrative_text) <= CHARS_PER_TOKEN
    assert any("unread" in gap["reason"] for gap in ingest.gaps)


def test_a_read_within_budget_is_not_marked_truncated(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "a.xml", ARTICLE), limit_tokens=100_000)
    assert ingest.truncated is False
    assert ingest.gaps == []


# ------------------------------------------------------------------
# The written object
# ------------------------------------------------------------------


def test_written_ingest_validates_against_its_schema(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "a.xml", ARTICLE), doi="10.1234/paper")
    out = write_ingest(ingest, tmp_path / "ingest.json")
    payload = json.loads(out.read_text())
    jsonschema.validate(payload, load_schema("paper_ingest.schema.json"))
    assert payload["source"]["kind"] == "jats"
    assert payload["narrative"]["n_chars"] == len(ingest.narrative_text)


def test_empty_collections_are_omitted_rather_than_written_as_empty(tmp_path):
    ingest = ingest_paper(_write(tmp_path, "p.txt", "Recovered prose."))
    payload = ingest.to_dict()
    assert "legends" not in payload
    assert "supplement_prose" not in payload


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def test_cli_writes_an_ingest_and_reports_what_it_holds(tmp_path, capsys):
    out = tmp_path / "ingest.json"
    code = main(
        ["--text", str(_write(tmp_path, "a.xml", ARTICLE)), "--out", str(out), "--doi", "10.1/x"]
    )
    assert code == 0
    assert json.loads(out.read_text())["paper"]["doi"] == "10.1/x"
    assert "narrative_chars=" in capsys.readouterr().out


def test_cli_exits_nonzero_when_the_text_cannot_be_assembled(tmp_path, capsys):
    code = main(
        [
            "--text",
            str(_write(tmp_path, "empty.txt", "  ")),
            "--out",
            str(tmp_path / "ingest.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "ingest.json").exists()
    assert "no prose" in capsys.readouterr().out


# ------------------------------------------------------------------
# Where the text came from, folded in from retrieval
# ------------------------------------------------------------------


def _fetched_paper(tmp_path, kind: str, record: dict) -> Path:
    """A paper laid out the way retrieval leaves one."""
    import json as _json

    source = tmp_path / "papers" / "10.1234_x" / "source"
    source.mkdir(parents=True)
    name = "paper.jats.xml" if kind == "jats" else "paper.txt"
    text = (
        "<article><body><sec><title>Results</title><p>Cells were counted twice.</p>"
        "</sec></body></article>"
        if kind == "jats"
        else "Cells were counted twice, and then a third time for luck."
    )
    (source / name).write_text(text, encoding="utf-8")
    (source.parent / "retrieval.json").write_text(_json.dumps(record), encoding="utf-8")
    return source / name


@pytest.mark.unit
def test_the_route_the_text_arrived_by_is_carried_onto_the_ingest(tmp_path):
    """A parser cannot tell a supplied PDF from a fetched one; the record can."""
    path = _fetched_paper(
        tmp_path,
        "pdf",
        {
            "doi": "10.1234/x",
            "route": "unpaywall",
            "url": "https://repo.example/paper.pdf",
            "retrieved_at": "2026-09-10T14:54:06+00:00",
            "attempts": [],
        },
    )
    source = ingest_paper(path, doi="10.1234/x").to_dict()["source"]

    assert source["kind"] == "pdf_text"
    assert source["route"] == "unpaywall"
    assert source["url"] == "https://repo.example/paper.pdf"


@pytest.mark.unit
def test_a_paper_with_no_retrieval_record_still_ingests(tmp_path):
    """Assembling a file by hand is normal and must not require a record."""
    path = tmp_path / "paper.txt"
    path.write_text("Cells were counted twice.", encoding="utf-8")

    source = ingest_paper(path).to_dict()["source"]
    assert "route" not in source


@pytest.mark.unit
def test_an_unreadable_retrieval_record_is_ignored_rather_than_fatal(tmp_path):
    path = _fetched_paper(
        tmp_path, "jats", {"doi": "10.1234/x", "route": "europepmc", "attempts": []}
    )
    (path.parent.parent / "retrieval.json").write_text("{ not json", encoding="utf-8")

    source = ingest_paper(path, doi="10.1234/x").to_dict()["source"]
    assert "route" not in source


@pytest.mark.unit
def test_pdf_text_records_both_of_the_things_it_cannot_support(tmp_path):
    """No reference markup, and no guaranteed order across a column boundary."""
    path = tmp_path / "paper.txt"
    path.write_text("Cells were counted twice.", encoding="utf-8")

    gaps = [g["what"] for g in ingest_paper(path).gaps]
    assert "cited sentences and the reference list" in gaps
    assert "guaranteed reading order" in gaps
