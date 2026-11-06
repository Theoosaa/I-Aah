"""CSV import: decoding, header detection, column mapping and row parsing."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from iaah.core.errors import CsvMappingError
from iaah.core.parsing.csv_import import (
    CsvField,
    decode_table,
    find_header,
    guess_mapping,
    import_table,
    load_table,
    parse_rows,
    read_csv,
)

# Shape of an ING CSV export: preamble, then a header where "Saldo" precedes "Betrag" and
# "Buchungstext" precedes "Verwendungszweck".
ING_EXPORT: Final = (
    "Umsatzanzeige;Datei erstellt am: 01.08.2026\n"
    "IBAN;DE00 0000\n"
    "\n"
    "Buchung;Valuta;Auftraggeber/Empfänger;Buchungstext;Verwendungszweck;Saldo;Währung;Betrag;Währung\n"
    "01.07.2026;01.07.2026;REWE Markt;Lastschrift;Einkauf;1.000,00;EUR;-12,34;EUR\n"
    "02.07.2026;02.07.2026;Arbeitgeber GmbH;Gehalt;Gehalt Juli;2.234,56;EUR;1.234,56;EUR\n"
    "Kontostand;;;;;;;;\n"
)
# Column names of a Sparkasse CAMT export ("Lastschrift Ursprungsbetrag" before "Betrag").
SPARKASSE_HEADER: Final = (
    '"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";'
    '"Glaeubiger ID";"Mandatsreferenz";"Kundenreferenz (End-to-End)";"Sammlerreferenz";'
    '"Lastschrift Ursprungsbetrag";"Auslagenersatz Ruecklastschrift";'
    '"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";'
    '"Waehrung";"Info"'
)
# Column names of a DKB export.
DKB_HEADER: Final = (
    '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";'
    '"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz"'
)


def _header(line: str) -> tuple[str, ...]:
    return decode_table(f"{line}\n".encode()).rows[0]


def test_decode_cp1252_with_semicolons() -> None:
    table = decode_table(ING_EXPORT.encode("cp1252"))
    assert table.encoding == "cp1252"
    assert table.delimiter == ";"
    assert len(table.rows) == 6  # the empty line is dropped


def test_decode_utf8_with_bom_and_commas() -> None:
    table = decode_table("﻿Datum,Betrag\n2026-07-01,12.50\n".encode())
    assert table.encoding == "utf-8-sig"
    assert table.delimiter == ","
    assert table.rows[0] == ("Datum", "Betrag")


def test_delimiter_is_chosen_by_consistent_columns() -> None:
    raw = b"Datum;Betrag;Zweck\n01.07.2026;-1,00;a, b, c, d, e\n"
    assert decode_table(raw).delimiter == ";"


def test_ing_header_and_mapping() -> None:
    rows = decode_table(ING_EXPORT.encode()).rows
    assert find_header(rows) == 2
    assert guess_mapping(rows[2]) == {
        CsvField.DATE: 0,
        CsvField.AMOUNT: 7,
        CsvField.PAYEE: 2,
        CsvField.PURPOSE: 4,
    }


def test_preamble_with_keywords_is_not_a_header() -> None:
    # "Umsatzanzeige" contains "umsatz"; "Datei" no longer counts as "date" (whole words only),
    # and even a preamble that did map both columns would fail the booking probe.
    rows = decode_table(ING_EXPORT.encode()).rows
    assert CsvField.DATE not in guess_mapping(rows[0])
    assert find_header(rows) == 2
    fake_header = ("Datum erstellt", "Umsatzanzeige")
    assert find_header([fake_header, ("IBAN", "DE00")]) is None


def test_sparkasse_mapping_prefers_exact_amount_column() -> None:
    assert guess_mapping(_header(SPARKASSE_HEADER)) == {
        CsvField.DATE: 1,
        CsvField.AMOUNT: 14,
        CsvField.PAYEE: 11,
        CsvField.PURPOSE: 4,
    }


def test_dkb_mapping() -> None:
    mapping = guess_mapping(_header(DKB_HEADER))
    assert (mapping[CsvField.DATE], mapping[CsvField.AMOUNT]) == (0, 8)
    assert mapping[CsvField.PURPOSE] == 5


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        # "buchung" must not claim "Buchungstext" as the date column.
        (
            ("Wertstellungsdatum", "Buchungstext", "Empfänger", "Betrag"),
            {CsvField.DATE: 0, CsvField.AMOUNT: 3, CsvField.PAYEE: 2, CsvField.PURPOSE: 1},
        ),
        # "wert" must not claim "Wertstellung" as the amount column.
        (
            ("Buchungstag", "Wertstellung", "Umsatzart", "Buchungsbetrag"),
            {CsvField.DATE: 0, CsvField.AMOUNT: 3},
        ),
    ],
)
def test_generic_keywords_match_whole_words_only(
    header: tuple[str, ...], expected: dict[CsvField, int]
) -> None:
    assert guess_mapping(header) == expected


def test_delimiter_with_balance_lines_in_preamble() -> None:
    raw = (
        b"Alter Kontostand;1.000,00 EUR\n"
        b"Neuer Kontostand;1.200,00 EUR\n"
        b"Buchungstag;Betrag;Verwendungszweck\n"
        b"01.07.2026;-1,00;a\n"
        b"02.07.2026;201,00;b\n"
    )
    table = decode_table(raw)
    assert table.delimiter == ";"
    assert len(import_table(table, "x.csv").transactions) == 2


def test_one_column_is_never_mapped_twice() -> None:
    mapping = guess_mapping(("Buchungstext", "Datum", "Betrag"))
    assert mapping == {CsvField.DATE: 1, CsvField.AMOUNT: 2, CsvField.PURPOSE: 0}


def test_header_accepted_when_a_later_row_is_a_booking() -> None:
    raw = b"Datum;Betrag;Zweck\n;-1,00;vorgemerkt\n01.07.2026;-2,00;gebucht\n"
    statement = import_table(decode_table(raw), "x.csv")
    assert [txn.amount for txn in statement.transactions] == [Decimal("-2.00")]
    assert statement.report.skipped_rows == (1,)


def test_import_table_reads_bookings_and_reports_skipped_rows() -> None:
    statement = import_table(decode_table(ING_EXPORT.encode()), "export.csv")
    rewe, salary = statement.transactions
    assert (rewe.booking_date, rewe.payee, rewe.amount) == (
        date(2026, 7, 1),
        "REWE Markt",
        Decimal("-12.34"),
    )
    assert (salary.purpose, salary.amount) == ("Gehalt Juli", Decimal("1234.56"))
    assert statement.info.total == Decimal("1222.22")
    assert statement.info.reconciles is None
    assert statement.report.skipped_rows == (5,)


def test_whole_amounts_with_thousands_dot_are_german() -> None:
    raw = b"Datum;Betrag\n01.07.2026;2.000\n02.07.2026;-1,50\n"
    amounts = [txn.amount for txn in import_table(decode_table(raw), "x.csv").transactions]
    assert amounts == [Decimal("2000"), Decimal("-1.50")]


def test_english_number_column() -> None:
    raw = b'Date,Amount,Payee\n2026-07-01,"-1,234.50",Shop\n2026-07-02,12.5,Shop\n'
    amounts = [txn.amount for txn in import_table(decode_table(raw), "x.csv").transactions]
    assert amounts == [Decimal("-1234.50"), Decimal("12.5")]


def test_payee_falls_back_to_purpose() -> None:
    rows = [("01.07.2026", "-5,00", "", "Kartenzahlung Bäckerei Schmidt am Markt 12")]
    mapping = {CsvField.DATE: 0, CsvField.AMOUNT: 1, CsvField.PAYEE: 2, CsvField.PURPOSE: 3}
    (txn,) = parse_rows(rows, mapping, "x.csv").transactions
    assert txn.payee == "Kartenzahlung Bäckerei Schmidt"


def test_manual_mapping_with_header_row() -> None:
    table = decode_table(b"a;b\nx;y\n01.07.2026;-1,00\n")
    statement = import_table(table, "x.csv", {CsvField.DATE: 0, CsvField.AMOUNT: 1}, header_row=1)
    assert [txn.amount for txn in statement.transactions] == [Decimal("-1.00")]


def test_missing_header_raises() -> None:
    with pytest.raises(CsvMappingError):
        import_table(decode_table(b"foo;bar\n1;2\n"), "x.csv")


def test_unmapped_required_column_raises() -> None:
    with pytest.raises(CsvMappingError, match="amount"):
        parse_rows([("01.07.2026",)], {CsvField.DATE: 0}, "x.csv")


def test_file_wrappers(tmp_path: Path) -> None:
    path = tmp_path / "umsatz.csv"
    path.write_bytes(ING_EXPORT.encode("cp1252"))
    assert load_table(path).rows[0][0] == "Umsatzanzeige"
    statement = read_csv(path)
    assert statement.info.source == "umsatz.csv"
    assert len(statement.transactions) == 2
