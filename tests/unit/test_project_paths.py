"""Unit tests for resolving a project's paths from its name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_chat.services.project_paths import ProjectNotFound, main, resolve

pytestmark = pytest.mark.unit

DOI = "10.1234/atlas"


def _project(root: Path, name: str, *, under: str = "projects", doi: str | None = DOI) -> Path:
    d = root / under / name
    d.mkdir(parents=True)
    source = {"title": "An atlas"} | ({"doi": doi} if doi else {})
    (d / "cas.json").write_text(json.dumps({"source": source, "annotations": []}))
    return d


def _paper(project: Path, doi: str = DOI) -> Path:
    from atlas_chat.services.local_snippet_index import paper_slug

    src = project / "local_index" / "papers" / paper_slug(doi) / "source"
    src.mkdir(parents=True)
    path = src / "paper.jats.xml"
    path.write_text("<article/>")
    return path


def test_a_project_is_found_under_projects(tmp_path):
    _project(tmp_path, "a")
    assert resolve("a", repo_root=tmp_path).project_dir.name == "a"


def test_a_nested_project_must_be_named_with_its_subdirectory(tmp_path):
    _project(tmp_path, "b", under="projects/test_projects")
    assert resolve("test_projects/b", repo_root=tmp_path).project_dir.name == "b"
    with pytest.raises(ProjectNotFound):
        resolve("b", repo_root=tmp_path)


def test_a_bare_name_never_reaches_past_projects(tmp_path):
    """A test project standing in for a working atlas of the same name is not a
    mistake anyone would catch by reading the output."""
    real = _project(tmp_path, "shared")
    _project(tmp_path, "shared", under="projects/test_projects")
    assert resolve("shared", repo_root=tmp_path).project_dir == real


def test_a_name_that_only_resolves_deeper_says_where_it_is(tmp_path):
    _project(tmp_path, "b", under="projects/test_projects")
    with pytest.raises(ProjectNotFound) as exc:
        resolve("b", repo_root=tmp_path)
    assert "test_projects/b" in str(exc.value)


def test_a_path_may_be_given_instead_of_a_name(tmp_path):
    d = _project(tmp_path, "a")
    assert resolve(str(d), repo_root=tmp_path).cas == d / "cas.json"


def test_an_unknown_project_says_where_it_looked(tmp_path):
    with pytest.raises(ProjectNotFound) as exc:
        resolve("nope", repo_root=tmp_path)
    assert "projects/nope" in str(exc.value)


def test_the_doi_and_title_come_from_the_cas_document(tmp_path):
    _project(tmp_path, "a")
    p = resolve("a", repo_root=tmp_path)
    assert p.doi == DOI
    assert p.title == "An atlas"


def test_a_cached_paper_is_found_by_its_doi(tmp_path):
    d = _project(tmp_path, "a")
    expected = _paper(d)
    assert resolve("a", repo_root=tmp_path).paper_text == expected


def test_a_missing_paper_is_a_gap_rather_than_a_path_to_nothing(tmp_path):
    _project(tmp_path, "a")
    p = resolve("a", repo_root=tmp_path)
    assert p.paper_text is None
    assert any("no paper text" in g for g in p.gaps)


def test_a_project_with_no_doi_says_so(tmp_path):
    _project(tmp_path, "a", doi=None)
    p = resolve("a", repo_root=tmp_path)
    assert p.paper_text is None
    assert any("no DOI" in g for g in p.gaps)


def test_a_store_in_the_corpus_is_preferred(tmp_path):
    d = _project(tmp_path, "a")
    (d / "supplements").mkdir()
    corpus = tmp_path / "corpus" / "a" / "supplements"
    corpus.mkdir(parents=True)
    assert (
        resolve("a", repo_root=tmp_path, corpus_root=tmp_path / "corpus").supplement_store == corpus
    )


def test_a_store_inside_the_project_is_used_when_the_corpus_has_none(tmp_path):
    d = _project(tmp_path, "a")
    (d / "supplements").mkdir()
    p = resolve("a", repo_root=tmp_path, corpus_root=tmp_path / "empty")
    assert p.supplement_store == d / "supplements"


def test_no_store_anywhere_is_a_gap_naming_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_CHAT_CORPUS_ROOT", raising=False)
    _project(tmp_path, "a")
    p = resolve("a", repo_root=tmp_path)
    assert p.supplement_store is None
    assert any("ATLAS_CHAT_CORPUS_ROOT" in g for g in p.gaps)


def test_the_corpus_root_falls_back_to_the_environment(tmp_path, monkeypatch):
    _project(tmp_path, "a")
    corpus = tmp_path / "corpus" / "a" / "supplements"
    corpus.mkdir(parents=True)
    monkeypatch.setenv("ATLAS_CHAT_CORPUS_ROOT", str(tmp_path / "corpus"))
    assert resolve("a", repo_root=tmp_path).supplement_store == corpus


def test_the_traversal_directory_is_created(tmp_path):
    d = _project(tmp_path, "a")
    p = resolve("a", repo_root=tmp_path)
    assert p.traversal_output == d / "traversal_output"
    assert p.traversal_output.is_dir()


def test_cli_prints_the_paths(tmp_path, capsys):
    d = _project(tmp_path, "a")
    _paper(d)
    assert main(["paths", "--project", "a", "--repo-root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["doi"] == DOI
    assert out["paper_text"].endswith("paper.jats.xml")


def test_cli_exits_nonzero_for_an_unknown_project(tmp_path, capsys):
    assert main(["paths", "--project", "nope", "--repo-root", str(tmp_path)]) == 2
    assert "no cas.json" in capsys.readouterr().out


# --- the annotation hierarchy ------------------------------------------------


def _hierarchy(tmp_path: Path) -> dict:
    """A parent with two children, one of which does not say what it is."""
    return {
        "source": {"doi": DOI},
        "annotations": [
            {
                "labelset": "L3",
                "cell_label": "Macrophages",
                "cell_set_accession": "M",
                "n_cells": 100,
                "synonyms": ["Mac"],
            },
            {
                "labelset": "L4",
                "cell_label": "Immune_Mac_LYVE1hi",
                "cell_fullname": "Macrophages LYVE1+",
                "cell_set_accession": "A",
                "parent_cell_set_accession": "M",
                "n_cells": 60,
            },
            {
                "labelset": "L4",
                "cell_label": "Immune_oLAM",
                "cell_fullname": "Ovarian lipid-associated macrophages",
                "cell_set_accession": "B",
                "parent_cell_set_accession": "M",
                "n_cells": 40,
            },
        ],
    }


def _labels(text: str) -> list[str]:
    return [line.split("\t")[1] for line in text.splitlines()[1:]]


def test_the_outline_has_a_line_per_annotation_and_a_header(tmp_path):
    from atlas_chat.services.project_paths import outline

    text = outline(_hierarchy(tmp_path))
    assert text.splitlines()[0].startswith("labelset\tlabel")
    assert _labels(text) == ["Macrophages", "Immune_Mac_LYVE1hi", "Immune_oLAM"]


def test_a_full_name_identical_to_the_label_is_left_blank(tmp_path):
    from atlas_chat.services.project_paths import outline

    row = outline(_hierarchy(tmp_path)).splitlines()[1].split("\t")
    assert row[1] == "Macrophages"
    assert row[2] == ""


def test_the_parent_is_named_so_a_subtree_is_visible(tmp_path):
    from atlas_chat.services.project_paths import outline

    rows = [line.split("\t") for line in outline(_hierarchy(tmp_path)).splitlines()[1:]]
    assert {r[3] for r in rows if r[1].startswith("Immune")} == {"Macrophages"}


def test_matching_the_label_alone_would_miss_most_of_them(tmp_path):
    """The reason selection resolves to a subtree rather than a match: a cell
    type's label need not contain the word for what it is."""
    from atlas_chat.services.project_paths import outline

    by_label = [
        a["cell_label"]
        for a in _hierarchy(tmp_path)["annotations"]
        if "macrophage" in a["cell_label"].lower()
    ]
    assert by_label == ["Macrophages"]
    assert _labels(outline(_hierarchy(tmp_path), under="Macrophages")) == [
        "Immune_Mac_LYVE1hi",
        "Immune_oLAM",
    ]


def test_match_covers_the_full_name_and_synonyms(tmp_path):
    from atlas_chat.services.project_paths import outline

    assert len(_labels(outline(_hierarchy(tmp_path), match="macrophage"))) == 3
    assert _labels(outline(_hierarchy(tmp_path), match="mac")) == [
        "Macrophages",
        "Immune_Mac_LYVE1hi",
        "Immune_oLAM",
    ]


def test_a_labelset_narrows_to_one_level(tmp_path):
    from atlas_chat.services.project_paths import outline

    assert _labels(outline(_hierarchy(tmp_path), labelset="L3")) == ["Macrophages"]


def test_synonyms_are_left_out_unless_asked_for(tmp_path):
    from atlas_chat.services.project_paths import outline

    assert "synonyms" not in outline(_hierarchy(tmp_path)).splitlines()[0]
    assert "Mac" in outline(_hierarchy(tmp_path), synonyms=True).splitlines()[1]


def test_cli_outline_prints_the_hierarchy(tmp_path, capsys):
    d = _project(tmp_path, "a")
    (d / "cas.json").write_text(json.dumps(_hierarchy(tmp_path)))
    assert main(["outline", "--project", "a", "--repo-root", str(tmp_path)]) == 0
    assert "Immune_oLAM" in capsys.readouterr().out
