"""The retrieval CLI's own logic: which papers it works on, and what it reports.

The fetching is covered elsewhere. What is here is the part that decides what to
fetch — a project keeps its paper list in more than one shape, and reading the
wrong one silently does the wrong corpus.
"""

from __future__ import annotations

import argparse
import json

import pytest
from atlas_chat.cli_paper import build_parser, main, read_dois, summarise
from atlas_chat.services.paper_fetch import Retrieval

pytestmark = pytest.mark.unit


def args(**kwargs) -> argparse.Namespace:
    defaults = {"doi": None, "cas": None, "doi_file": None}
    return argparse.Namespace(**{**defaults, **kwargs})


def test_dois_can_be_named_on_the_command_line():
    assert read_dois(args(doi=["10.1234/a", "10.1234/b"])) == ["10.1234/a", "10.1234/b"]


def test_a_cas_document_yields_the_atlas_and_its_subatlas_papers(tmp_path):
    cas = tmp_path / "cas.json"
    cas.write_text(
        json.dumps(
            {
                "source": {
                    "doi": "10.1234/atlas",
                    "subatlas_papers": [{"label": "Smith_2020", "doi": "10.1234/sub"}],
                }
            }
        )
    )
    assert read_dois(args(cas=str(cas))) == ["10.1234/atlas", "10.1234/sub"]


def test_a_plain_list_is_read_with_blanks_and_comments_ignored(tmp_path):
    """A project whose CAS+ has no subatlas block keeps its list this way."""
    listing = tmp_path / "subatlas_pubs"
    listing.write_text("10.1234/a\n\n# a note\n  10.1234/b  \n")
    assert read_dois(args(doi_file=str(listing))) == ["10.1234/a", "10.1234/b"]


def test_a_doi_named_twice_is_fetched_once_and_order_is_kept(tmp_path):
    """The reproductive atlas's own list repeats a DOI."""
    listing = tmp_path / "pubs"
    listing.write_text("10.1234/b\n10.1234/a\n10.1234/b\n")
    assert read_dois(args(doi=["10.1234/a"], doi_file=str(listing))) == [
        "10.1234/a",
        "10.1234/b",
    ]


def test_naming_no_papers_at_all_is_an_error():
    from atlas_chat.services.paper_fetch import PaperFetchError

    with pytest.raises(PaperFetchError, match="no DOIs given"):
        read_dois(args())


def test_a_retrieved_paper_is_summarised_with_its_route_and_size(tmp_path):
    record = Retrieval(
        doi="10.1234/a",
        route="unpaywall",
        kind="pdf",
        text_quality={"n_segments": 180, "n_chars": 76344},
    )
    row = summarise(record, tmp_path)

    assert row["route"] == "unpaywall"
    assert row["n_chars"] == 76344
    assert row["readable"] is True


def test_a_paper_needing_an_ask_is_summarised_with_what_to_do(tmp_path):
    record = Retrieval(
        doi="10.1234/a",
        route="none",
        gap={"what": "the paper", "reason": "nothing worked", "action": "adopt it"},
    )
    row = summarise(record, tmp_path)

    assert row["reason"] == "nothing worked"
    assert row["action"] == "adopt it"


def test_show_on_a_paper_nobody_has_fetched_says_so(tmp_path, capsys):
    assert main(["show", "--out", str(tmp_path), "--doi", "10.1234/a"]) == 2
    assert "no retrieval record" in capsys.readouterr().out


def test_every_subcommand_is_reachable():
    parser = build_parser()
    for command in ("fetch", "adopt", "candidates", "show", "text"):
        assert command in parser.parse_args([command, *_minimal_args(command)]).command


def _minimal_args(command: str) -> list[str]:
    return {
        "fetch": ["--out", "p"],
        "adopt": ["--out", "p", "--doi", "d", "--file", "f"],
        "candidates": ["--inputs", "i"],
        "show": ["--out", "p", "--doi", "d"],
        "text": ["--pdf", "f"],
    }[command]
