"""The *Datei ▸ Exportieren* actions: ask for a target file, write it, report the result.

Bookings and summaries cover the current filter of the transactions tab; the report covers the
period chosen on the analysis tab.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Final

from iaah.core.analysis.ledger import Entry, Period, build_entries
from iaah.core.parsing.ing import read_statement
from iaah.export.marked_pdf import marked_name, write_marked_pdf
from iaah.export.report import write_report
from iaah.export.summary import summarize, write_csv_summary, write_text_summary
from iaah.export.tables import booking_rows, write_bookings_csv, write_bookings_excel
from iaah.gui.host import Host

CSV: Final = (".csv", "CSV-Datei (Semikolon, für Excel)")
XLSX: Final = (".xlsx", "Excel-Arbeitsmappe")
TXT: Final = (".txt", "Textdatei")
PDF: Final = (".pdf", "PDF-Datei")
NOTHING: Final = "Keine Buchungen in der aktuellen Auswahl (Filter prüfen)."
PROTECTED: Final = "Ein Export darf keinen importierten Kontoauszug überschreiben."
BOOKINGS_NAME: Final = "buchungen"
SUMMARY_NAME: Final = "zusammenfassung"
ALL_TIME: Final = "gesamt"


def _target(
    parent: tk.Misc, host: Host, title: str, kind: tuple[str, str], initial: str
) -> Path | None:
    """Ask for the file to write; ``None`` if cancelled or if it is an imported statement –
    an export must never replace one."""
    extension, description = kind
    chosen = filedialog.asksaveasfilename(
        parent=parent,
        title=title,
        defaultextension=extension,
        initialfile=initial + extension,
        filetypes=[(description, f"*{extension}")],
    )
    if not chosen:
        return None
    if host.session.is_statement_file(Path(chosen)):
        host.status(PROTECTED)
        return None
    return Path(chosen)


def _filtered_entries(host: Host) -> list[Entry]:
    session = host.session
    return build_entries([row.transaction for row in session.rows()], session.categorizer)


def bookings(parent: tk.Misc, host: Host, excel: bool) -> None:
    """The filtered bookings as CSV or Excel (one row per split part)."""
    entries = _filtered_entries(host)
    if not entries:
        host.status(NOTHING)
        return
    kind = XLSX if excel else CSV
    target = _target(parent, host, "Buchungen exportieren", kind, BOOKINGS_NAME)
    if target is None:
        return
    rows = booking_rows(entries)
    write = write_bookings_excel if excel else write_bookings_csv
    if host.run(lambda: write(rows, target)):
        host.status(f"{len(rows)} Zeilen gespeichert: {target}")


def summary(parent: tk.Misc, host: Host, text: bool) -> None:
    """Spending and income per category of the filtered bookings, as CSV or text."""
    entries = _filtered_entries(host)
    if not entries:
        host.status(NOTHING)
        return
    target = _target(
        parent, host, "Zusammenfassung exportieren", TXT if text else CSV, SUMMARY_NAME
    )
    if target is None:
        return
    result = summarize(entries)
    write = write_text_summary if text else write_csv_summary
    if host.run(lambda: write(result, target)):
        host.status(f"Zusammenfassung gespeichert: {target}")


def report(parent: tk.Misc, host: Host, period: Period) -> None:
    """The PDF report of ``period``: cover with KPIs and the report charts."""
    if not host.session.transactions:
        host.status("Noch keine Buchungen importiert.")
        return
    target = _target(
        parent, host, "Report als PDF speichern", PDF, f"report {str(period) or ALL_TIME}"
    )
    if target is not None and host.run(
        lambda: write_report(host.session.chart_input(period), target)
    ):
        host.status(f"Report gespeichert: {target}")


def marked_pdf(parent: tk.Misc, host: Host) -> None:
    """A copy of a statement PDF with every booking underlaid in its category color."""
    chosen = filedialog.askopenfilename(
        parent=parent, title="Kontoauszug (PDF) wählen", filetypes=[(PDF[1], f"*{PDF[0]}")]
    )
    if not chosen:
        return
    source = Path(chosen)
    suggested = marked_name(source)
    target = _target(parent, host, "Markiertes PDF speichern", PDF, suggested.stem)
    if target is None:
        return
    if target.resolve() == source.resolve():
        host.status(PROTECTED)
        return

    def write() -> None:
        parsed = read_statement(source)
        result = write_marked_pdf(source, target, parsed.transactions, host.session.categorizer)
        host.status(
            f"{result.marked} Buchungen in {len(result.legend)} Kategorien markiert: {target}"
        )

    host.run(write)
