"""Unit tests for the supplement store's mechanical half.

Everything here is in/out: JATS parsing, archive expansion, outlining a
workbook, slicing a region, and the manifest cross-checks. Fixtures are built in
tmp_path rather than committed, so the suite carries no binaries.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from atlas_chat.services import supplement_store as store

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <body>
    <supplementary-material id="MOESM1" xlink:href="paper_MOESM1_ESM.xlsx">
      <label>Supplementary Tables</label>
      <caption><p>Supplementary Tables 1-40.</p></caption>
    </supplementary-material>
    <supplementary-material id="MOESM2" xlink:href="paper_MOESM2_ESM.mp4">
      <label>Supplementary Video 1</label>
      <caption><p>3D view of
      co-localization.</p></caption>
    </supplementary-material>
    <supplementary-material id="MOESM3">
      <media xlink:href="paper_MOESM3_ESM.pdf"/>
      <caption><p>Reporting Summary</p></caption>
    </supplementary-material>
    <supplementary-material id="dupe" xlink:href="paper_MOESM1_ESM.xlsx"/>
  </body>
</article>
"""


@pytest.fixture
def jats_file(tmp_path: Path) -> Path:
    path = tmp_path / "paper.jats.xml"
    path.write_text(JATS)
    return path


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    """A workbook shaped like a real supplement: a title row above the header."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "table.xlsx"
    wb = openpyxl.Workbook()
    legend = wb.active
    legend.title = "Legend"
    legend.append(["Sheet", "Contents"])
    legend.append(["DEGs", "Differential expression per cluster"])

    degs = wb.create_sheet("DEGs")
    degs.append(["Supplementary Table 12 | DEGs by cluster", None, None])
    degs.append(["gene", "avg_log2FC", "p_val_adj"])
    for index in range(5):
        degs.append([f"GENE{index}", 1.5 + index, 0.001])
    wb.save(path)
    return path


def _minimal_manifest(doi: str = "10.1038/test") -> dict:
    return {
        "manifest_version": store.MANIFEST_VERSION,
        "paper": {"doi": doi},
        "files": [],
    }


# ------------------------------------------------------------------
# Inventory
# ------------------------------------------------------------------


def test_inventory_reads_labels_and_captions(jats_file: Path) -> None:
    entries = store.inventory_from_jats(jats_file)

    assert [entry["file_id"] for entry in entries] == [
        "paper_MOESM1_ESM.xlsx",
        "paper_MOESM2_ESM.mp4",
        "paper_MOESM3_ESM.pdf",
    ]
    tables = entries[0]
    assert tables["label"] == "Supplementary Tables"
    assert tables["caption"] == "Supplementary Tables 1-40."
    assert tables["media_type"] == "xlsx"
    assert tables["status"] == "listed"
    assert tables["retrieval"] == {"route": "jats_listing"}


def test_inventory_normalises_whitespace_in_captions(jats_file: Path) -> None:
    entries = store.inventory_from_jats(jats_file)
    video = next(e for e in entries if e["media_type"] == "video")
    assert video["caption"] == "3D view of co-localization."


def test_inventory_finds_href_on_nested_media(jats_file: Path) -> None:
    entries = store.inventory_from_jats(jats_file)
    pdf = next(e for e in entries if e["media_type"] == "pdf")
    assert pdf["file_id"] == "paper_MOESM3_ESM.pdf"
    assert "label" not in pdf


def test_inventory_returns_empty_for_article_without_supplements(tmp_path: Path) -> None:
    path = tmp_path / "bare.xml"
    path.write_text('<?xml version="1.0"?><article><body/></article>')
    assert store.inventory_from_jats(path) == []


# ------------------------------------------------------------------
# Adopting manual drops
# ------------------------------------------------------------------


def test_adopt_copies_files_and_carries_captions_over(
    tmp_path: Path, jats_file: Path, workbook: Path
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "paper_MOESM1_ESM.xlsx").write_bytes(workbook.read_bytes())
    (incoming / "README.md").write_text("not a supplement")
    (incoming / ".DS_Store").write_text("nor this")

    manifest = store.adopt_manual_files(
        store_root=tmp_path / "store",
        doi="10.1038/test",
        incoming=incoming,
        listed=store.inventory_from_jats(jats_file),
        paper={"pmcid": "PMC11578897"},
    )

    by_id = {entry["file_id"]: entry for entry in manifest["files"]}
    adopted = by_id["paper_MOESM1_ESM.xlsx"]
    assert adopted["status"] == "present"
    assert adopted["retrieval"]["route"] == "manual"
    assert len(adopted["retrieval"]["sha256"]) == 64
    # The caption from the article XML survives adoption.
    assert adopted["caption"] == "Supplementary Tables 1-40."
    # Files we know of but never fetched stay listed.
    assert by_id["paper_MOESM2_ESM.mp4"]["status"] == "listed"
    # README and dotfiles are not supplements.
    assert "README.md" not in by_id and ".DS_Store" not in by_id
    assert manifest["paper"] == {"doi": "10.1038/test", "pmcid": "PMC11578897"}
    assert (tmp_path / "store" / adopted["path"]).exists()


def test_adopt_is_idempotent(tmp_path: Path, workbook: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "table.xlsx").write_bytes(workbook.read_bytes())
    root = tmp_path / "store"

    first = store.adopt_manual_files(root, "10.1038/test", incoming)
    second = store.adopt_manual_files(root, "10.1038/test", incoming)

    assert len(second["files"]) == len(first["files"]) == 1
    assert second["files"][0]["retrieval"]["sha256"] == (first["files"][0]["retrieval"]["sha256"])


def test_adopt_rejects_missing_incoming(tmp_path: Path) -> None:
    with pytest.raises(store.SupplementStoreError, match="does not exist"):
        store.adopt_manual_files(tmp_path / "store", "10.1038/test", tmp_path / "nope")


def test_present_file_does_not_regress_to_listed(tmp_path: Path) -> None:
    existing = [{"file_id": "a.xlsx", "status": "present", "path": "p/a.xlsx"}]
    incoming = [{"file_id": "a.xlsx", "status": "listed", "caption": "Tables 1-40"}]

    merged = store._merge_files(existing, incoming)

    assert merged[0]["status"] == "present"
    assert merged[0]["path"] == "p/a.xlsx"
    assert merged[0]["caption"] == "Tables 1-40"


# ------------------------------------------------------------------
# Unpacking
# ------------------------------------------------------------------


def _store_with_archive(tmp_path: Path, members: dict[str, bytes]) -> Path:
    root = tmp_path / "store"
    files = store.files_dir(root, "10.1038/test")
    files.mkdir(parents=True)
    archive = files / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)
    manifest = _minimal_manifest()
    manifest["files"] = [
        {
            "file_id": "bundle.zip",
            "media_type": "zip",
            "status": "present",
            "path": store._rel(root, archive),
            "size_bytes": archive.stat().st_size,
        }
    ]
    store.write_manifest(root, "10.1038/test", manifest)
    return root


def test_unpack_records_members_and_extracts(tmp_path: Path) -> None:
    root = _store_with_archive(
        tmp_path, {"tables/Table 1.csv": b"gene,lfc\nA,1\n", "notes.txt": b"hello"}
    )

    manifest = store.unpack_archives(root, "10.1038/test")

    members = {m["member_path"]: m for m in manifest["files"][0]["members"]}
    assert members["tables/Table 1.csv"]["extracted"] is True
    assert (root / members["tables/Table 1.csv"]["path"]).read_text().startswith("gene")
    assert manifest.get("gaps", []) == []


def test_unpack_skips_oversized_media_but_keeps_big_tables(tmp_path: Path) -> None:
    root = _store_with_archive(
        tmp_path,
        {"big.mp4": b"x" * 2048, "big_table.xlsx": b"y" * 2048},
    )

    manifest = store.unpack_archives(root, "10.1038/test", size_cap=1024, tabular_size_cap=4096)

    members = {m["member_path"]: m for m in manifest["files"][0]["members"]}
    assert members["big.mp4"]["extracted"] is False
    # A large supplementary table is usually the one worth having.
    assert members["big_table.xlsx"]["extracted"] is True
    reasons = [gap["reason"] for gap in manifest["gaps"]]
    assert any("above the 1024-byte cap" in reason for reason in reasons)
    assert not any("big_table" in gap.get("member_path", "") for gap in manifest["gaps"])


def test_unpack_records_nested_archive_as_gap(tmp_path: Path) -> None:
    root = _store_with_archive(tmp_path, {"inner.zip": b"PK\x03\x04 not really"})

    manifest = store.unpack_archives(root, "10.1038/test")

    gap = next(g for g in manifest["gaps"] if g["member_path"] == "inner.zip")
    assert "nested archives are not expanded" in gap["reason"]
    assert "incoming/" in gap["action"]


def test_re_unpacking_clears_stale_gaps(tmp_path: Path) -> None:
    """Raising a cap must retire the gap the old cap produced."""
    root = _store_with_archive(tmp_path, {"big_table.xlsx": b"y" * 2048})

    tight = store.unpack_archives(root, "10.1038/test", tabular_size_cap=1024)
    assert len(tight["gaps"]) == 1

    loose = store.unpack_archives(root, "10.1038/test", tabular_size_cap=4096)
    assert loose["gaps"] == []


def test_unpack_refuses_path_traversal(tmp_path: Path) -> None:
    root = _store_with_archive(tmp_path, {"../escape.csv": b"gene\n"})

    manifest = store.unpack_archives(root, "10.1038/test")

    member = manifest["files"][0]["members"][0]
    assert member["extracted"] is False
    assert any("escapes the archive root" in gap["reason"] for gap in manifest["gaps"])
    assert not (tmp_path / "escape.csv").exists()


# ------------------------------------------------------------------
# Outline
# ------------------------------------------------------------------


def test_outline_xlsx_lists_sheets_and_guesses_header_row(workbook: Path) -> None:
    outline = store.outline_file(workbook)

    assert [table["locator"] for table in outline["tables"]] == ["Legend", "DEGs"]
    degs = outline["tables"][1]
    # Row 0 is the "Supplementary Table 12 | ..." title; the header is row 1.
    assert degs["header_row_guess"] == 1
    assert degs["rows"][1] == ["gene", "avg_log2FC", "p_val_adj"]
    assert degs["n_rows"] == 7


def test_outline_is_bounded_by_sample_size(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "wide.xlsx"
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.append([f"col{i}" for i in range(60)])
    for row in range(200):
        sheet.append([row] * 60)
    wb.save(path)

    outline = store.outline_file(path, sample_rows=3, max_cols=5)

    table = outline["tables"][0]
    assert len(table["rows"]) == 3
    assert all(len(row) <= 5 for row in table["rows"])
    # The real dimensions are still reported.
    assert table["n_rows"] == 201
    assert table["n_cols"] == 60
    assert table["truncated_cols"] is True


def test_outline_clips_long_cells(tmp_path: Path) -> None:
    path = tmp_path / "long.csv"
    path.write_text("header\n" + "x" * 5000 + "\n")

    table = store.outline_file(path)["tables"][0]

    assert len(table["rows"][1][0]) <= store.OUTLINE_CELL_CHARS + 1


def test_outline_delimited_sniffs_tabs(tmp_path: Path) -> None:
    path = tmp_path / "degs.tsv"
    path.write_text("gene\tlfc\nA\t1\nB\t2\n")

    table = store.outline_file(path)["tables"][0]

    assert table["delimiter"] == "\t"
    assert table["n_rows"] == 3
    assert table["rows"][0] == ["gene", "lfc"]


def test_outline_docx_reads_tables(tmp_path: Path) -> None:
    """Supplementary Information docs carry cluster-annotation tables."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = f"""<?xml version="1.0"?>
    <w:document xmlns:w="{ns}"><w:body><w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>cluster</w:t></w:r></w:p></w:tc>
             <w:tc><w:p><w:r><w:t>annotation</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>c1</w:t></w:r></w:p></w:tc>
             <w:tc><w:p><w:r><w:t>Iron-recycling macrophage</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl></w:body></w:document>"""
    path = tmp_path / "si.docx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document)

    tables = store.outline_file(path)["tables"]

    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["cluster", "annotation"]
    assert tables[0]["rows"][1][1] == "Iron-recycling macrophage"


def test_outline_unsupported_kind_says_so(tmp_path: Path) -> None:
    path = tmp_path / "figure.png"
    path.write_bytes(b"\x89PNG")

    outline = store.outline_file(path)

    assert outline["tables"] == []
    assert "no outline support" in outline["note"]


# ------------------------------------------------------------------
# Slice
# ------------------------------------------------------------------


def test_slice_reads_one_region(workbook: Path) -> None:
    result = store.read_slice(workbook, locator="DEGs", start=2, limit=2, header_row=1)

    assert result["header"] == ["gene", "avg_log2FC", "p_val_adj"]
    assert result["returned"] == 2
    assert result["rows"][0][0] == "GENE0"


def test_slice_selects_columns(workbook: Path) -> None:
    result = store.read_slice(
        workbook, locator="DEGs", start=2, limit=1, header_row=1, columns=["gene"]
    )

    assert result["header"] == ["gene"]
    assert result["rows"] == [["GENE0"]]


def test_slice_rejects_unknown_column(workbook: Path) -> None:
    with pytest.raises(store.SupplementStoreError, match="columns not in header"):
        store.read_slice(workbook, locator="DEGs", header_row=1, columns=["nope"])


def test_slice_rejects_unknown_locator(workbook: Path) -> None:
    with pytest.raises(store.SupplementStoreError, match="no table 'Missing'"):
        store.read_slice(workbook, locator="Missing")


def test_slice_defaults_to_first_table(tmp_path: Path) -> None:
    path = tmp_path / "one.csv"
    path.write_text("gene,lfc\nA,1\n")

    result = store.read_slice(path, start=1, limit=1, header_row=0)

    assert result["header"] == ["gene", "lfc"]
    assert result["rows"] == [["A", "1"]]


# ------------------------------------------------------------------
# Manifest validation
# ------------------------------------------------------------------


def test_write_manifest_refuses_invalid(tmp_path: Path) -> None:
    manifest = _minimal_manifest()
    manifest["files"] = [{"file_id": "a.xlsx", "status": "invented"}]

    with pytest.raises(store.SupplementStoreError, match="manifest invalid"):
        store.write_manifest(tmp_path, "10.1038/test", manifest)

    assert not store.manifest_path(tmp_path, "10.1038/test").exists()


def test_write_manifest_rejects_unknown_field(tmp_path: Path) -> None:
    manifest = _minimal_manifest()
    manifest["surprise"] = True

    with pytest.raises(store.SupplementStoreError):
        store.write_manifest(tmp_path, "10.1038/test", manifest)


def test_round_trip(tmp_path: Path) -> None:
    manifest = _minimal_manifest()
    manifest["files"] = [
        {"file_id": "a.xlsx", "status": "present", "path": "papers/x/files/a.xlsx"}
    ]

    store.write_manifest(tmp_path, "10.1038/test", manifest)

    assert store.load_manifest(tmp_path, "10.1038/test") == manifest
    assert store.load_manifest(tmp_path, "10.1038/other") is None


def test_load_manifest_reports_corrupt_json(tmp_path: Path) -> None:
    path = store.manifest_path(tmp_path, "10.1038/test")
    path.parent.mkdir(parents=True)
    path.write_text("{not json")

    with pytest.raises(store.SupplementStoreError, match="not valid JSON"):
        store.load_manifest(tmp_path, "10.1038/test")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(
            lambda m: m["files"].append({"file_id": "b.xlsx", "status": "present"}),
            "no path",
            id="present-without-path",
        ),
        pytest.param(
            lambda m: m["files"].append(
                {"file_id": "b.xlsx", "status": "listed", "path": "p/b.xlsx"}
            ),
            "but has a path",
            id="listed-with-path",
        ),
        pytest.param(
            lambda m: m["tables"].append(
                {
                    "file_id": "ghost.xlsx",
                    "content_type": "deg_results",
                    "description": "d",
                    "evidence": "headers",
                }
            ),
            "unknown file_id",
            id="table-points-nowhere",
        ),
        pytest.param(
            lambda m: m["tables"].append(
                {
                    "file_id": "bundle.zip",
                    "content_type": "deg_results",
                    "description": "d",
                    "evidence": "headers",
                }
            ),
            "names no member_path",
            id="archive-without-member",
        ),
        pytest.param(
            lambda m: m["tables"].append(
                {
                    "file_id": "bundle.zip",
                    "member_path": "not/in/archive.xlsx",
                    "content_type": "deg_results",
                    "description": "d",
                    "evidence": "headers",
                }
            ),
            "is not a member of",
            id="member-not-in-archive",
        ),
        pytest.param(
            lambda m: m["tables"].append(
                {
                    "file_id": "missing.xlsx",
                    "content_type": "marker_list",
                    "description": "d",
                    "evidence": "caption",
                }
            ),
            "status 'unavailable'",
            id="table-on-unavailable-file",
        ),
    ],
)
def test_cross_check_catches_unusable_manifests(mutate, expected: str) -> None:
    manifest = _minimal_manifest()
    manifest["files"] = [
        {"file_id": "a.xlsx", "status": "present", "path": "p/a.xlsx"},
        {
            "file_id": "bundle.zip",
            "media_type": "zip",
            "status": "present",
            "path": "p/bundle.zip",
            "members": [{"member_path": "tables/Table 1.xlsx"}],
        },
        {"file_id": "missing.xlsx", "status": "unavailable"},
    ]
    manifest["tables"] = []
    mutate(manifest)

    # These all satisfy the schema; only the cross-check catches them.
    store.validate_manifest(manifest)
    problems = store.cross_check_manifest(manifest)

    assert any(expected in problem for problem in problems), problems


def test_cross_check_passes_a_good_manifest() -> None:
    manifest = _minimal_manifest()
    manifest["files"] = [
        {
            "file_id": "bundle.zip",
            "media_type": "zip",
            "status": "present",
            "path": "p/bundle.zip",
            "members": [{"member_path": "tables/Table 1.xlsx", "extracted": True}],
        }
    ]
    manifest["tables"] = [
        {
            "file_id": "bundle.zip",
            "member_path": "tables/Table 1.xlsx",
            "locator": "DEGs",
            "content_type": "deg_results",
            "description": "DE of each fine cluster against its broad lineage.",
            "columns": [{"name": "gene"}, {"name": "avg_log2FC"}],
            "header_row": 1,
            "evidence": "headers",
        }
    ]

    store.validate_manifest(manifest)
    assert store.cross_check_manifest(manifest) == []


def test_touch_indexed_at(tmp_path: Path) -> None:
    store.write_manifest(tmp_path, "10.1038/test", _minimal_manifest())

    manifest = store.touch_indexed_at(tmp_path, "10.1038/test")

    assert manifest["indexed_at"].endswith("+00:00")
    assert store.load_manifest(tmp_path, "10.1038/test")["indexed_at"]


# ------------------------------------------------------------------
# CAS+ integration
# ------------------------------------------------------------------


def test_corpus_papers_takes_atlas_and_subatlases() -> None:
    cas = {
        "source": {
            "doi": "10.1038/atlas",
            "title": "An atlas",
            "pmcid": "PMC1",
            "subatlas_papers": [
                {"label": "Suo 2022", "doi": "10.1126/science.abo0510"},
                {"label": "No DOI yet", "status": "unresolved"},
            ],
        }
    }

    papers = store.corpus_papers(cas)

    assert papers[0] == {
        "doi": "10.1038/atlas",
        "role": "atlas",
        "title": "An atlas",
        "pmcid": "PMC1",
    }
    # A subatlas paper with no DOI cannot be keyed, so it is not a store entry.
    assert [p["doi"] for p in papers] == ["10.1038/atlas", "10.1126/science.abo0510"]
    assert papers[1]["role"] == "subatlas"


def test_corpus_papers_tolerates_a_bare_cas() -> None:
    assert store.corpus_papers({}) == []


# ------------------------------------------------------------------
# Store layout
# ------------------------------------------------------------------


def test_layout_is_keyed_by_doi_slug(tmp_path: Path) -> None:
    root = tmp_path / "supplements"

    assert store.paper_dir(root, "10.1038/s41586-024-08002-x").name == (
        "10.1038_s41586-024-08002-x"
    )
    assert store.manifest_path(root, "10.1038/X").name == "manifest.json"
    assert store.files_dir(root, "10.1038/X").name == "files"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Table 1.xlsx", "xlsx"),
        ("data.CSV", "csv"),
        ("notes.tsv", "tsv"),
        ("si.docx", "docx"),
        ("bundle.zip", "zip"),
        ("movie.mp4", "video"),
        ("panel.tiff", "image"),
        ("weird.h5ad", "other"),
    ],
)
def test_media_type(name: str, expected: str) -> None:
    assert store.media_type(name) == expected


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def test_cli_inventory(jats_file: Path, capsys: pytest.CaptureFixture) -> None:
    assert store.main(["inventory", "--jats", str(jats_file)]) == 0

    entries = json.loads(capsys.readouterr().out)
    assert len(entries) == 3


def test_cli_check_reports_bad_manifest(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = store.manifest_path(tmp_path, "10.1038/test")
    path.parent.mkdir(parents=True)
    manifest = _minimal_manifest()
    manifest["tables"] = [
        {
            "file_id": "ghost.xlsx",
            "content_type": "other",
            "description": "d",
            "evidence": "caption",
        }
    ]
    path.write_text(json.dumps(manifest))

    code = store.main(["check", "--store", str(tmp_path), "--doi", "10.1038/test"])

    assert code == 1
    assert "unknown file_id" in capsys.readouterr().err


def test_cli_check_passes_good_manifest(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    store.write_manifest(tmp_path, "10.1038/test", _minimal_manifest())

    code = store.main(["check", "--store", str(tmp_path), "--doi", "10.1038/test"])

    assert code == 0
    assert "manifest OK" in capsys.readouterr().out


def test_cli_show_missing_manifest_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    code = store.main(["show", "--store", str(tmp_path), "--doi", "10.1038/test"])

    assert code == 1
    assert "no manifest" in capsys.readouterr().err


def test_cli_papers(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cas = tmp_path / "cas.json"
    cas.write_text(json.dumps({"source": {"doi": "10.1038/atlas"}}))

    assert store.main(["papers", "--cas", str(cas)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["role"] == "atlas"


# ------------------------------------------------------------------
# Header detection — shapes taken from real publisher supplements
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "expected", "note"),
    [
        pytest.param(
            [
                ["Prenatal skin metadata"],
                ["Sanger_id", "Donor", "PCW", "Sorting"],
                ["4834STDY7002879", "F16", "8", "CD45P"],
            ],
            1,
            "title row above the header",
            id="title-then-header",
        ),
        pytest.param(
            [
                ["DEG analysis for macrophage subpopulations"],
                ["", "LYVE1+ macrophages", "", "", "", "", "", "MHCII macrophages"],
                ["", "names", "scores", "logfoldchanges", "pvals", "pvals_adj"],
                ["", "DAB2", "150.68", "4.18", "0", "0"],
            ],
            2,
            "title, then a group-label row, then the header",
            id="title-group-header",
        ),
        pytest.param(
            [
                ["Prenatal skin cell DEGs"],
                ["", "All celltypes, annotation fine"],
                ["", "genes", "cluster", "top_frac", "frac_diff", "logfoldchanges"],
                ["0", "AC007381.1", "ASDC", "0.4657", "0.2263", "9.89"],
            ],
            2,
            "header no wider than its data — column count alone picks the data row",
            id="header-same-width-as-data",
        ),
        pytest.param(
            [
                ["LR: Reindeer trained_to_Prenatal skin prediction probabilities"],
                ["", "Original_labels", "LR_assignment", "0", "1", "2", "3", "4"],
                [
                    "AAACCTGG-1",
                    "LYVE1++ macrophage",
                    "1",
                    "2.9e-11",
                    "0.80",
                    "0.0009",
                    "0.09",
                    "0.04",
                ],
            ],
            1,
            "header whose own column names are numbers",
            id="numeric-header",
        ),
        pytest.param(
            [["GENE1", "1.2", "0.05"], ["GENE2", "2.4", "0.01"]],
            0,
            "no header at all",
            id="headerless",
        ),
        pytest.param([], 0, "empty sample", id="empty"),
    ],
)
def test_header_row_guess(rows: list[list[str]], expected: int, note: str) -> None:
    assert store._header_row_guess(rows) == expected, note


# ------------------------------------------------------------------
# Text extraction
# ------------------------------------------------------------------


def _docx(path: Path, paragraphs: list[str]) -> Path:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>',
        )
    return path


def test_extract_text_reads_a_legends_document(tmp_path: Path) -> None:
    """The legends doc characterises a whole bundle and is prose, not a table."""
    path = _docx(
        tmp_path / "legends.docx",
        [
            "Supplementary Table 22: DEGs between macrophage subsets.",
            "Differential expression analysis results between macrophage subsets.",
        ],
    )

    result = store.extract_text(path)

    assert "Supplementary Table 22" in result["text"]
    assert result["truncated"] is False
    assert result["chars"] == len(result["text"])
    # outline sees nothing in it, which is why extract_text exists.
    assert store.outline_file(path)["tables"] == []


def test_extract_text_truncates_to_budget(tmp_path: Path) -> None:
    path = _docx(tmp_path / "long.docx", ["word " * 500] * 20)

    result = store.extract_text(path, max_chars=100)

    assert len(result["text"]) == 100
    assert result["truncated"] is True
    assert result["chars"] > 100


def test_extract_text_declines_unsupported_kinds(tmp_path: Path) -> None:
    path = tmp_path / "figure.png"
    path.write_bytes(b"\x89PNG\r\n")

    result = store.extract_text(path)

    assert result["text"] == ""
    assert "no text extraction for" in result["note"]


def test_extract_text_reports_why_a_pdf_yielded_nothing(tmp_path: Path) -> None:
    """A PDF that cannot be read must say so — an empty string alone would read
    as 'this file holds nothing', which is how scans get written off."""
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 truncated")

    result = store.extract_text(path)

    assert result["text"] == ""
    assert result["note"]


@pytest.mark.parametrize("op", ["outline", "text"])
def test_missing_file_is_an_error_not_an_empty_result(tmp_path: Path, op: str) -> None:
    """An empty result for a bad path would read as 'this file holds nothing'."""
    missing = tmp_path / "nope.xlsx"

    with pytest.raises(store.SupplementStoreError, match="no such file"):
        if op == "outline":
            store.outline_file(missing)
        else:
            store.extract_text(missing)


def test_cli_text(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = _docx(tmp_path / "legends.docx", ["Supplementary Table 1: Sample metadata."])

    assert store.main(["text", "--file", str(path), "--max-chars", "20"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["truncated"] is True
    assert len(payload["text"]) == 20


def test_manifest_paper_block_stays_minimal(tmp_path: Path) -> None:
    """Corpus metadata belongs to CAS+, not to a fetch cache that can drift."""
    manifest = _minimal_manifest()
    manifest["paper"]["role"] = "atlas"

    with pytest.raises(store.SupplementStoreError):
        store.write_manifest(tmp_path, "10.1038/test", manifest)


# ------------------------------------------------------------------
# No limit is silent
# ------------------------------------------------------------------


def test_outline_flags_both_truncations_against_true_size(tmp_path: Path) -> None:
    """A caller must be able to tell a whole table from the top of a big one."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "big.xlsx"
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.append([f"col{i}" for i in range(50)])
    for row in range(100):
        sheet.append([row] * 50)
    wb.save(path)

    table = store.outline_file(path, sample_rows=3, max_cols=5)["tables"][0]

    assert table["truncated_rows"] is True
    assert table["truncated_cols"] is True
    assert table["n_rows"] == 101
    assert table["n_cols"] == 50


def test_outline_does_not_flag_truncation_for_a_small_table(tmp_path: Path) -> None:
    path = tmp_path / "small.csv"
    path.write_text("gene,lfc\nA,1\nB,2\n")

    table = store.outline_file(path)["tables"][0]

    assert table["truncated_rows"] is False
    assert table["truncated_cols"] is False


def test_header_detection_survives_a_small_sample(tmp_path: Path) -> None:
    """Asking to *see* two rows must not degrade the header guess.

    Real case: Supplementary Table 5 of the prenatal skin atlas has two title
    rows above its header, so `--rows 2` would otherwise report row 0.
    """
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "titled.xlsx"
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.append(["LR: prediction probabilities"])
    sheet.append(["Overall"])
    sheet.append(["barcode", "predicted", "12-14", "15-17"])
    sheet.append(["AAAC-1", "12-14", 0.37, 0.31])
    wb.save(path)

    table = store.outline_file(path, sample_rows=2)["tables"][0]

    assert table["header_row_guess"] == 2
    # Still only returns what was asked for.
    assert len(table["rows"]) == 2


def test_outline_counts_rows_when_the_workbook_omits_its_dimensions() -> None:
    """openpyxl read-only reports None for max_row on some publisher files.

    Passing that through puts a null where every consumer expects a count — and
    `n_rows` is what tells a reader a table needs slicing rather than opening.
    """

    class DimensionlessSheet:
        title = "Sheet1"
        max_row = None
        max_column = None

        def iter_rows(self, values_only=False, max_row=None, max_col=None):
            rows = [("gene", "lfc", None), ("A", 1.0, None), ("B", 2.0, None)]
            for index, row in enumerate(rows):
                if max_row is not None and index >= max_row:
                    return
                yield row[:max_col] if max_col else row

    assert store._xlsx_dimensions(DimensionlessSheet()) == (3, 2)


def test_a_large_declared_extent_is_trusted_without_streaming() -> None:
    """Scanning a 396,880-row sheet costs 18s; its declaration has held up."""

    class Sheet:
        max_row = store.VERIFY_ROWS_AT_OR_BELOW + 1
        max_column = 12

        def iter_rows(self, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("should not stream above the verify threshold")

    assert store._xlsx_dimensions(Sheet()) == (store.VERIFY_ROWS_AT_OR_BELOW + 1, 12)


def test_a_small_declared_extent_is_verified() -> None:
    """Publisher sheets declare a round extent when formatting ran past the data.

    Real case: sheets in the Garcia-Alonso 2021 supplement declare 1000 rows for
    9 rows of content, and n_rows is what tells a reader to slice rather than
    read whole.
    """

    class InflatedSheet:
        max_row = 1000  # declared
        max_column = 10

        def iter_rows(self, values_only=False, max_row=None, max_col=None):
            yield ("Organoid Cluster:", "SOX9+LGR5-")
            yield ("Lumenal 1", 0.4)
            for _ in range(998):
                yield (None, None)

    assert store._xlsx_dimensions(InflatedSheet()) == (2, 2)


def test_xlsx_dimensions_ignores_trailing_empty_rows() -> None:
    """Formatting applied past the data must not inflate the row count.

    Real case: a subject table with 35 rows of data in a sheet formatted to row
    1000 reported 1000, which tells a reader to slice a table small enough to
    read whole.
    """

    class FormattedFarSheet:
        max_row = None
        max_column = None

        def iter_rows(self, values_only=False, max_row=None, max_col=None):
            yield ("Subject", "Age", None)
            yield ("S1", 59, None)
            yield ("S2", 65, None)
            for _ in range(200):  # formatted, but empty
                yield (None, None, None)

    assert store._xlsx_dimensions(FormattedFarSheet()) == (3, 2)


def test_xlsx_dimensions_ignores_whitespace_only_cells() -> None:
    class Sheet:
        max_row = None
        max_column = None

        def iter_rows(self, values_only=False, max_row=None, max_col=None):
            yield ("gene", "lfc")
            yield ("A", 1.0)
            yield ("   ", "")

    assert store._xlsx_dimensions(Sheet()) == (2, 2)
