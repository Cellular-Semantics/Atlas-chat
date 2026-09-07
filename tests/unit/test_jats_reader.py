"""jats_reader: whole narrative text, separate legends, cited sentences, truncation.

The reader job is the contract between the routing layer and the reader subagent;
these pin what goes in (narrative without legends or Methods), what is kept aside
(legends, methods), and that the oversized fallback truncates visibly.
"""

from __future__ import annotations

import pytest

from atlas_chat.services import jats_reader

pytestmark = pytest.mark.unit

XML = """<article>
  <front><article-meta>
    <abstract><p>Skin cells were mapped.</p></abstract>
  </article-meta></front>
  <body>
    <sec>
      <title>Results</title>
      <p>Macrophages seed the skin early
        <sup><xref ref-type="bibr" rid="R1">1</xref></sup>.
        They express LYVE1.</p>
      <fig id="f1"><label>Fig. 1</label>
        <caption><p>Overview. TML, TREM2+ microglia-like.</p></caption>
      </fig>
      <p>Dermal papilla cells aggregate.</p>
    </sec>
    <sec>
      <title>Methods</title>
      <p>Cells were dissociated with enzymes.</p>
    </sec>
  </body>
  <back><ref-list>
    <ref id="R1"><element-citation>
      <article-title>Macrophage origins</article-title>
      <name><surname>Goh</surname></name>
      <year>2023</year>
      <pub-id pub-id-type="doi">10.1000/goh</pub-id>
    </element-citation></ref>
  </ref-list></back>
</article>"""


@pytest.fixture()
def xml_path(tmp_path):
    p = tmp_path / "paper.jats.xml"
    p.write_text(XML)
    return p


def test_narrative_has_body_not_legend_not_methods(xml_path) -> None:
    reading = jats_reader.read_paper(xml_path, doi="10.1/x")
    assert "Macrophages seed the skin early" in reading.narrative_text
    assert "Dermal papilla cells aggregate" in reading.narrative_text
    assert "TREM2+ microglia-like" not in reading.narrative_text  # legend not spliced
    assert "dissociated with enzymes" not in reading.narrative_text  # Methods excluded
    assert "dissociated with enzymes" in reading.methods_text
    assert reading.doi == "10.1/x"


def test_legends_extracted_separately(xml_path) -> None:
    reading = jats_reader.read_paper(xml_path)
    assert len(reading.legends) == 1
    assert reading.legends[0].startswith("Fig. 1:")
    assert "TREM2+ microglia-like" in reading.legends[0]


def test_cited_sentences_resolved(xml_path) -> None:
    reading = jats_reader.read_paper(xml_path)
    assert reading.cited_sentences, "expected at least one cited sentence"
    cs = reading.cited_sentences[0]
    assert "Macrophages seed the skin early" in cs["text"]
    assert cs["ref_ids"] == ["R1"]
    assert cs["resolved_refs"][0]["doi"] == "10.1000/goh"
    assert reading.ref_lookup["R1"]["first_author"] == "Goh"


def test_not_truncated_within_budget(xml_path) -> None:
    reading = jats_reader.read_paper(xml_path, budget_tokens=40_000)
    assert reading.truncated is False


def test_oversized_truncates_and_flags(tmp_path) -> None:
    paras = "".join(
        f"<p>Filler paragraph {i} about unrelated topics repeated words.</p>" for i in range(200)
    )
    xml = (
        "<article><body><sec><title>Results</title>"
        "<p>The dermal condensate expresses FOXD1 and SOX2.</p>"
        f"{paras}</sec></body></article>"
    )
    p = tmp_path / "paper.jats.xml"
    p.write_text(xml)
    # Budget far below total; the query should keep the relevant paragraph.
    reading = jats_reader.read_paper(p, query="dermal condensate markers", budget_tokens=100)
    assert reading.truncated is True
    assert "FOXD1" in reading.narrative_text
    assert reading.n_chars_total > 100 * 4
    assert len(reading.narrative_text) <= 100 * 4 + 50  # headings overhead only


def test_bm25_ranks_relevant_segment_first() -> None:
    segments = [
        ("Results", "The weather was mild that year."),
        ("Results", "Iron-recycling macrophages express SLC40A1 and CD5L."),
        ("Results", "Sequencing depth averaged fifty thousand reads."),
    ]
    order = jats_reader._bm25_rank(segments, "iron recycling macrophage markers")
    assert order[0] == 1
