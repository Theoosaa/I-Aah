"""Workspace: importing files by suffix, entries, saving and loading."""

import os
from pathlib import Path

import pytest

from iaah.core.category_io import default_catalog
from iaah.core.errors import CsvMappingError, StatementParseError
from iaah.core.library import Library
from iaah.core.storage import DataPaths, DataStore
from iaah.core.workspace import Workspace, file_sha256

CSV = (
    "Buchungstag;Betrag;Auftraggeber/Empfänger;Verwendungszweck\n"
    "01.07.2026;-12,34;REWE Markt;Einkauf\n"
)


def _workspace() -> Workspace:
    return Workspace(default_catalog(), Library())


def test_import_csv_and_build_entries(tmp_path: Path) -> None:
    path = tmp_path / "umsatz.csv"
    path.write_text(CSV, encoding="utf-8")
    workspace = _workspace()
    assert workspace.is_empty()
    assert workspace.import_file(path).added == 1
    assert workspace.import_file(path).already_imported  # by hash, without parsing again
    assert not workspace.is_empty()
    (entry,) = workspace.entries()
    assert entry.category == "Lebensmittel"
    assert workspace.library.statements[0].sha256 == file_sha256(path)


def test_importing_a_moved_file_updates_its_location(tmp_path: Path) -> None:
    old = tmp_path / "alt" / "umsatz.csv"
    new = tmp_path / "neu" / "umsatz.csv"
    for path in (old, new):
        path.parent.mkdir()
        path.write_text(CSV, encoding="utf-8")
    workspace = _workspace()
    workspace.import_file(old)
    result = workspace.import_file(new)
    assert result.already_imported and result.relocated
    assert workspace.library.statements[0].path == str(new)
    assert len(workspace.library.transactions) == 1


def test_unsupported_or_unreadable_files(tmp_path: Path) -> None:
    workspace = _workspace()
    with pytest.raises(StatementParseError):
        workspace.import_file(tmp_path / "auszug.txt")
    with pytest.raises(StatementParseError):
        workspace.import_file(tmp_path / "fehlt.csv")
    broken = tmp_path / "kaputt.csv"
    broken.write_text("foo;bar\n1;2\n", encoding="utf-8")
    with pytest.raises(CsvMappingError):
        workspace.import_file(broken)


def test_save_and_load(tmp_path: Path) -> None:
    store = DataStore(DataPaths(tmp_path))
    workspace = _workspace()
    workspace.catalog.add_keyword("Shopping", "kaufhaus")
    workspace.save(store)
    loaded = Workspace.load(store)
    assert loaded.catalog.category_of_keyword("kaufhaus") == "Shopping"


@pytest.mark.skipif(not os.environ.get("IAAH_SAMPLE_PDF"), reason="IAAH_SAMPLE_PDF not set")
def test_import_sample_pdf_twice() -> None:
    workspace = _workspace()
    path = Path(os.environ["IAAH_SAMPLE_PDF"])
    assert workspace.import_file(path).added == 48
    assert workspace.import_file(path).already_imported
