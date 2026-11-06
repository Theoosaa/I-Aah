"""``iaah-cli`` end to end with the synthetic statement PDF and CSV files."""

import getpass
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from iaah.cli import EXIT_ERROR, EXIT_OK, EXIT_PROBLEMS, expand, main
from iaah.core.category_io import catalog_to_json, default_catalog
from iaah.core.parsing.ing import read_statement
from iaah.core.storage import DataPaths, DataStore, InstanceLock
from iaah.core.workspace import Workspace

CSV_STATEMENT = (
    "Buchung;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n"
    "05.07.2026;REWE Markt;Einkauf;-20,00\n"
    "06.07.2026;Kino am Markt;Film;-12,50\n"
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The app's data directory lives in the test's temporary folder."""
    home = tmp_path / "home"
    monkeypatch.setenv("IAAH_HOME", str(home))
    monkeypatch.setattr("iaah.core.crypto.ITERATIONS", 1_000)
    return home


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "umsaetze.csv"
    path.write_text(CSV_STATEMENT, encoding="utf-8")
    return path


# -- check ------------------------------------------------------------------------------------


def test_check_a_clean_statement(statement_pdf: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(statement_pdf)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Buchungen:       3   Summe: 2.405,70 €" in out
    assert "Saldo-Abgleich:  ok" in out
    assert "Auffällige Zeilen" not in out
    assert "Alle Zeilen" not in out


def test_check_lists_every_line_on_request(
    statement_pdf: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check", "--lines", str(statement_pdf)])
    out = capsys.readouterr().out
    assert "S. 2  Fortsetzung" in out
    assert "S. 1  Buchung " in out


def test_check_reports_a_balance_mismatch(
    build_statement_pdf: Callable[[str], bytes], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "falsch.pdf"
    path.write_bytes(build_statement_pdf("3.400,00"))
    assert main(["check", str(path)]) == EXIT_PROBLEMS
    assert "ABWEICHUNG" in capsys.readouterr().out


def test_check_a_file_that_is_no_pdf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "kaputt.pdf"
    path.write_bytes(b"kein PDF")
    assert main(["check", str(path)]) == EXIT_ERROR
    assert "nicht als Kontoauszug gelesen" in capsys.readouterr().err


# -- summary ----------------------------------------------------------------------------------


def test_summary_of_pdf_and_csv(
    statement_pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "aus"
    code = main(["summary", str(statement_pdf), str(_csv(tmp_path)), "--format", "text", "csv",
                 "chart", "report", "--output-dir", str(out_dir)])  # fmt: skip
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Lebensmittel" in out and "74,30 €" in out  # REWE in PDF and CSV
    assert "Freizeit" in out  # "Kino" from the CSV
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "ausgaben.png", "report.pdf", "zusammenfassung.csv",
    ]  # fmt: skip
    assert len(PdfReader(out_dir / "report.pdf").pages) > 1


def test_summary_imports_a_file_only_once(
    statement_pdf: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["summary", str(statement_pdf)])
    once = capsys.readouterr().out
    main(["summary", str(statement_pdf), str(statement_pdf)])
    assert capsys.readouterr().out == once


def test_summary_period_filter(statement_pdf: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["summary", str(statement_pdf), "--period", "2026-08"])
    assert "(keine Buchungen)" in capsys.readouterr().out
    with pytest.raises(SystemExit) as invalid:
        main(["summary", str(statement_pdf), "--period", "Juli"])
    assert invalid.value.code == EXIT_ERROR


def test_summary_needs_files_or_the_library(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary"]) == EXIT_ERROR
    assert "--library" in capsys.readouterr().err


def test_summary_with_a_category_file(
    statement_pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = default_catalog()
    catalog.add("Drogerie", color="#123456")
    catalog.add_keyword("Drogerie", "drogerie am eck")
    path = tmp_path / "kategorien.json"
    path.write_text(catalog_to_json(catalog), encoding="utf-8")
    main(["summary", str(statement_pdf), "--categories", str(path)])
    assert "Drogerie" in capsys.readouterr().out


# -- highlight --------------------------------------------------------------------------------


def test_highlight_writes_beside_the_source(
    statement_pdf: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["highlight", str(statement_pdf)]) == EXIT_OK
    target = statement_pdf.with_name(f"{statement_pdf.stem}_markiert.pdf")
    assert len(PdfReader(target).pages) == 3
    assert "3 Buchungen in 3 Kategorien markiert" in capsys.readouterr().out


def test_highlight_never_overwrites_the_source(
    statement_pdf: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = statement_pdf.read_bytes()
    assert main(["highlight", str(statement_pdf), "-o", str(statement_pdf)]) == EXIT_ERROR
    assert statement_pdf.read_bytes() == before
    assert "Kontoauszug selbst" in capsys.readouterr().err


# -- merge ------------------------------------------------------------------------------------


def test_merge_with_a_pattern(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name, amount in (("a.csv", "10,00"), ("b.csv", "5,50")):
        (tmp_path / name).write_text(f"Typ;Kategorie;Betrag (EUR)\nAusgabe;Wohnen;{amount}\n",
                                     encoding="utf-8")  # fmt: skip
    assert main(["merge", str(tmp_path / "*.csv"), "--format", "text"]) == EXIT_OK
    assert "15,50 €" in capsys.readouterr().out


def test_expand_keeps_plain_paths_and_expands_patterns(tmp_path: Path) -> None:
    (tmp_path / "x.pdf").write_bytes(b"")
    (tmp_path / "y.pdf").write_bytes(b"")
    assert expand([str(tmp_path / "*.pdf")]) == [tmp_path / "x.pdf", tmp_path / "y.pdf"]
    assert expand(["fehlt.pdf"]) == [Path("fehlt.pdf")]


# -- the app's data (--library) ---------------------------------------------------------------


def _store_with_decision(statement_pdf: Path, home: Path, password: str | None = None) -> None:
    """The app's data: the statement imported, the drugstore booking assigned to Gesundheit."""
    workspace = Workspace(default_catalog(), DataStore(DataPaths(home)).load()[1])
    workspace.import_file(statement_pdf)
    drugstore = read_statement(statement_pdf).transactions[2]
    workspace.categorizer.assign(drugstore, "Gesundheit")
    store = DataStore(DataPaths(home))
    if password:
        store.enable_encryption(password, workspace.catalog, workspace.library)
    else:
        workspace.save(store)


def test_library_decisions_apply(
    statement_pdf: Path, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store_with_decision(statement_pdf, isolated_home)
    stored = (isolated_home / "library.json").read_bytes()
    assert main(["summary", "--library"]) == EXIT_OK
    assert "Gesundheit" in capsys.readouterr().out
    assert main(["highlight", str(statement_pdf), "--library"]) == EXIT_OK
    assert (isolated_home / "library.json").read_bytes() == stored  # read-only


def test_encrypted_library_asks_for_the_password(
    statement_pdf: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _store_with_decision(statement_pdf, isolated_home, password="geheim")
    answers = iter(["falsch", "geheim"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    assert main(["summary", "--library"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Falsches Passwort, bitte noch einmal." in captured.err
    assert "Gesundheit" in captured.out


def test_wrong_password_three_times(
    statement_pdf: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _store_with_decision(statement_pdf, isolated_home, password="geheim")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "falsch")
    assert main(["summary", "--library"]) == EXIT_ERROR
    assert "Fehler: Falsches Passwort." in capsys.readouterr().err


def test_library_works_while_the_app_runs(
    statement_pdf: Path, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store_with_decision(statement_pdf, isolated_home)
    with InstanceLock(DataPaths(isolated_home).lock):
        assert main(["summary", "--library"]) == EXIT_OK
    assert "Gesundheit" in capsys.readouterr().out


def test_library_never_changes_the_data_directory(
    statement_pdf: Path, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store_with_decision(statement_pdf, isolated_home)
    store = DataStore(DataPaths(isolated_home))
    Workspace.load(store).save(store)  # a second save creates the backup
    (isolated_home / "library.json").write_bytes(b"{ damaged")
    (isolated_home / "library.json.tmp").write_bytes(b"leftover")
    before = {path.name: path.read_bytes() for path in isolated_home.iterdir()}
    assert main(["summary", "--library"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "Sicherungskopie" in captured.err
    assert "Gesundheit" in captured.out
    assert {path.name: path.read_bytes() for path in isolated_home.iterdir()} == before


def test_library_without_app_data_creates_nothing(statement_pdf: Path, isolated_home: Path) -> None:
    assert main(["summary", str(statement_pdf), "--library"]) == EXIT_OK
    assert not isolated_home.exists()


# -- errors become German messages ------------------------------------------------------------


def test_a_pattern_without_match_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", str(tmp_path / "*.pdf")]) == EXIT_ERROR
    assert "Keine Datei passt" in capsys.readouterr().err


def test_highlight_refuses_a_pdf_without_bookings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "rechnung.pdf"
    canvas = Canvas(str(path))
    canvas.drawString(70, 700, "Rechnung Nr. 4711")
    canvas.save()
    assert main(["highlight", str(path)]) == EXIT_ERROR
    assert "keine Buchungen erkannt" in capsys.readouterr().err
    assert not (tmp_path / "rechnung_markiert.pdf").exists()


def test_write_failures_are_reported(
    statement_pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "datei.txt"
    blocker.write_text("x", encoding="utf-8")
    code = main(["summary", str(statement_pdf), "--format", "csv", "--output-dir", str(blocker)])
    assert code == EXIT_ERROR
    assert "nicht geschrieben werden" in capsys.readouterr().err
    missing = tmp_path / "fehlt" / "x.pdf"
    assert main(["-v", "highlight", str(statement_pdf), "-o", str(missing)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "nicht geschrieben werden" in err
    assert "Details:" in err


def test_merge_chart_with_a_refund_surplus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "a.csv"
    path.write_text("Typ;Kategorie;Betrag (EUR)\nAusgabe;Wohnen;10,00\nAusgabe;Erstattung;-5,00\n",
                    encoding="utf-8")  # fmt: skip
    code = main(["merge", str(path), "--format", "text", "chart", "--output-dir", str(tmp_path)])
    assert code == EXIT_OK
    assert (tmp_path / "ausgaben.png").read_bytes().startswith(b"\x89PNG")
    assert "-5,00 €" in capsys.readouterr().out


def test_category_file_and_library_exclude_each_other(tmp_path: Path) -> None:
    path = tmp_path / "k.json"
    path.write_text(json.dumps({"version": 1, "categories": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["summary", "x.pdf", "--library", "--categories", str(path)])
