"""Bookings as CSV and Excel."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from iaah.core.workspace import Workspace
from iaah.export.tables import (
    COLUMNS,
    BookingRow,
    booking_rows,
    bookings_workbook,
    defuse,
    render_bookings_csv,
    write_bookings_csv,
    write_bookings_excel,
)


def _rows(workspace: Workspace) -> list[BookingRow]:
    return booking_rows(workspace.entries())


def test_one_row_per_entry_in_date_order(workspace: Workspace) -> None:
    rows = _rows(workspace)
    assert len(rows) == len(workspace.entries())  # the split booking yields two rows
    assert [row.day for row in rows] == sorted(row.day for row in rows)
    split = [row for row in rows if row.payee == "Drogerie am Eck"]
    assert [(row.category, row.amount) for row in split] == [
        ("Lebensmittel", Decimal("-25.00")),
        ("Gesundheit", Decimal("-15.00")),
    ]
    assert {row.kind for row in rows} == {"Ausgabe", "Einnahme", "Ignoriert"}


def test_csv_is_german(workspace: Workspace) -> None:
    text = render_bookings_csv(_rows(workspace)[:1])
    header, first = text.splitlines()
    assert header == ";".join(COLUMNS)
    expected = [
        "01.11.2025", "1234567890", "Gehalt/Rente", "Arbeitgeber GmbH", "Gehalt", "2500,00",
        "Einkommen", "Einnahme",
    ]  # fmt: skip
    assert first == ";".join(expected)


def test_formulas_from_senders_are_defused(workspace: Workspace) -> None:
    row = replace(_rows(workspace)[0], purpose='=HYPERLINK("http://x","klick")', payee="@SUM(A1)")
    line = render_bookings_csv([row]).splitlines()[1]
    assert ";'@SUM(A1);" in line
    assert "'=HYPERLINK" in line
    assert defuse("Miete") == "Miete"
    assert defuse("-Rabatt") == "'-Rabatt"


def test_csv_file_has_a_bom(workspace: Workspace, tmp_path: Path) -> None:
    path = tmp_path / "buchungen.csv"
    write_bookings_csv(_rows(workspace), path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_workbook_has_real_dates_numbers_and_plain_text(
    workspace: Workspace, tmp_path: Path
) -> None:
    row = replace(_rows(workspace)[0], purpose="=1+1")
    path = tmp_path / "buchungen.xlsx"
    write_bookings_excel([row], path)
    sheet = load_workbook(path).worksheets[0]
    assert [cell.value for cell in sheet[1]] == list(COLUMNS)
    day, _, _, _, purpose, amount, *_ = sheet[2]
    assert day.value == datetime(2025, 11, 1)
    assert day.number_format == "DD.MM.YYYY"
    assert amount.value == 2500
    assert "€" in amount.number_format
    assert (purpose.value, purpose.data_type) == ("=1+1", "s")  # text, not a formula
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:H2"


def test_control_characters_do_not_break_the_workbook(workspace: Workspace, tmp_path: Path) -> None:
    row = replace(_rows(workspace)[0], payee="Bäcker\x0bEcke\x00")
    path = tmp_path / "buchungen.xlsx"
    write_bookings_excel([row], path)
    assert load_workbook(path).worksheets[0]["D2"].value == "BäckerEcke"


def test_empty_workbook_has_the_header_only() -> None:
    sheet = bookings_workbook([]).worksheets[0]
    assert sheet.max_row == 1
    assert sheet.title == "Buchungen"
