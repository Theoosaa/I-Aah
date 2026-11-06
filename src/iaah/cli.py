# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""``iaah-cli``: check statements, summarize, mark PDFs and merge summaries from the shell.

Stateless by default: files in, outputs out. ``--library`` reads the app's data directory –
catalog and manual decisions – through a read-only store: it takes no lock, moves, tidies and
saves nothing. Output and messages are German; option names stay English.
"""

import argparse
import getpass
import io
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final

from iaah.charts.categories import donut_chart
from iaah.charts.gallery import ChartInput, category_colors
from iaah.charts.style import LIGHT, period_label
from iaah.core.analysis.ledger import Period, in_period
from iaah.core.category_io import default_catalog, load_catalog
from iaah.core.errors import (
    CategoryFileError,
    CsvMappingError,
    IaahError,
    PasswordRequiredError,
    StatementParseError,
    StorageError,
    UnsupportedVersionError,
    WrongPasswordError,
)
from iaah.core.library import Library
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.parsing.ing import read_statement
from iaah.core.parsing.layout import LineDiagnosis, LineStatus
from iaah.core.storage import DataPaths, DataStore
from iaah.core.text import format_euro
from iaah.core.workspace import Workspace
from iaah.export.files import ExportError, ensure_folder, figure_png, write_export
from iaah.export.marked_pdf import marked_name, write_marked_pdf
from iaah.export.report import write_report
from iaah.export.summary import (
    Summary,
    SummaryFileError,
    merge_summaries,
    read_csv_summary,
    render_text_summary,
    summarize,
    write_csv_summary,
)

EXIT_OK: Final = 0
EXIT_PROBLEMS: Final = 1  # check found something worth a look
EXIT_ERROR: Final = 2  # bad input; argparse uses the same code
PASSWORD_ATTEMPTS: Final = 3
GLOB_CHARACTERS: Final = frozenset("*?[")
UTF8: Final = "utf-8"

FORMAT_TEXT: Final = "text"
FORMAT_CSV: Final = "csv"
FORMAT_CHART: Final = "chart"
FORMAT_REPORT: Final = "report"
SUMMARY_FORMATS: Final = (FORMAT_TEXT, FORMAT_CSV, FORMAT_CHART, FORMAT_REPORT)
MERGE_FORMATS: Final = (FORMAT_TEXT, FORMAT_CSV, FORMAT_CHART)
SUMMARY_CSV: Final = "zusammenfassung.csv"
CHART_PNG: Final = "ausgaben.png"
REPORT_PDF: Final = "report.pdf"
MERGED_TITLE: Final = "Zusammengeführte Zusammenfassungen"
LINE_LABEL_WIDTH: Final = 19

STATUS_LABELS: Final[dict[LineStatus, str]] = {
    LineStatus.HEAD: "Buchung",
    LineStatus.DETAIL: "Fortsetzung",
    LineStatus.BAD_HEAD: "unlesbare Buchung",
    LineStatus.END: "Ende der Buchungen",
    LineStatus.NOISE: "Kopf-/Fußzeile",
    LineStatus.NO_OPEN_BOOKING: "ohne Buchung",
    LineStatus.OUTSIDE_COLUMN: "neben der Spalte",
    LineStatus.GAP_TOO_LARGE: "zu großer Abstand",
    LineStatus.DETAIL_LIMIT: "zu viele Zeilen",
}


class UsageError(IaahError):
    """A problem with the command line itself; the message is already German."""


# Most specific first: the first matching type gives the message.
ERROR_MESSAGES: Final[tuple[tuple[type[IaahError], str], ...]] = (
    (WrongPasswordError, "Falsches Passwort."),
    (PasswordRequiredError, "Die I-Aah-Daten sind verschlüsselt."),
    (UnsupportedVersionError, "Die I-Aah-Daten stammen aus einer neueren Programmversion."),
    (StorageError, "Die I-Aah-Daten konnten nicht gelesen werden."),
    (StatementParseError, "Die Datei konnte nicht als Kontoauszug gelesen werden."),
    (CsvMappingError, "In der CSV-Datei wurden Datum oder Betrag nicht erkannt."),
    (CategoryFileError, "Die Kategorien-Datei ist fehlerhaft."),
    (SummaryFileError, "Die Zusammenfassung ist fehlerhaft."),
)
GENERIC_ERROR: Final = "Unerwarteter Fehler."

type Command = Callable[[argparse.Namespace], int]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of ``iaah-cli``; returns the exit code."""
    _utf8_console()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = _parser().parse_args(argv)
    command: Command = args.run
    try:
        return command(args)
    except IaahError as error:
        print(f"Fehler: {german_message(error)}", file=sys.stderr)
        if args.verbose:
            print(f"Details: {error.__cause__ or error!r}", file=sys.stderr)
        return EXIT_ERROR


def german_message(error: IaahError) -> str:
    """The German text for an error."""
    if isinstance(error, UsageError):
        return str(error)
    if isinstance(error, ExportError):
        return f"{error.path} konnte nicht geschrieben werden (in einem anderen Programm offen?)."
    return next((text for kind, text in ERROR_MESSAGES if isinstance(error, kind)), GENERIC_ERROR)


# -- arguments --------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iaah-cli", description="Kontoauszüge prüfen, auswerten und markieren."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Fehlerdetails zeigen")
    commands = parser.add_subparsers(required=True, metavar="BEFEHL")
    _check_arguments(commands.add_parser("check", help="Erkennung und Saldo-Abgleich prüfen"))
    _summary_arguments(commands.add_parser("summary", help="Ausgaben und Einnahmen je Kategorie"))
    _highlight_arguments(commands.add_parser("highlight", help="Buchungen im PDF markieren"))
    _merge_arguments(commands.add_parser("merge", help="Zusammenfassungen (CSV) addieren"))
    return parser


def _check_arguments(check: argparse.ArgumentParser) -> None:
    check.add_argument("pdfs", nargs="+", metavar="PDF", help="Kontoauszüge (auch *.pdf)")
    check.add_argument("--lines", action="store_true", help="jede Zeile mit ihrem Status zeigen")
    check.set_defaults(run=_run_check)


def _summary_arguments(summary: argparse.ArgumentParser) -> None:
    summary.add_argument("files", nargs="*", metavar="DATEI", help="PDF- oder CSV-Auszüge")
    summary.add_argument("--period", type=_period, default=Period.all_time(),
                         help="Zeitraum: 2026 oder 2026-07 (Standard: alles)")  # fmt: skip
    _format_arguments(summary, SUMMARY_FORMATS)
    _category_arguments(summary)
    summary.set_defaults(run=_run_summary)


def _highlight_arguments(highlight: argparse.ArgumentParser) -> None:
    highlight.add_argument("pdf", type=Path, metavar="PDF", help="Kontoauszug")
    highlight.add_argument("-o", "--output", type=Path, default=None,
                           help="Zieldatei (Standard: <Name>_markiert.pdf daneben)")  # fmt: skip
    _category_arguments(highlight)
    highlight.set_defaults(run=_run_highlight)


def _merge_arguments(merge: argparse.ArgumentParser) -> None:
    merge.add_argument("csvs", nargs="+", metavar="CSV", help="Zusammenfassungen (auch *.csv)")
    _format_arguments(merge, MERGE_FORMATS)
    merge.set_defaults(run=_run_merge)


def _format_arguments(parser: argparse.ArgumentParser, formats: Sequence[str]) -> None:
    parser.add_argument("--format", nargs="+", choices=formats, default=[FORMAT_TEXT],
                        help="Ausgaben (Standard: text)")  # fmt: skip
    parser.add_argument("--output-dir", type=Path, default=Path(),
                        help="Ordner für Dateien (Standard: aktueller Ordner)")  # fmt: skip


def _category_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--categories", type=Path, help="Kategorien-Datei (JSON oder CSV)")
    source.add_argument("--library", action="store_true",
                        help="Kategorien und Zuordnungen der App nutzen (nur lesend)")  # fmt: skip


def _period(text: str) -> Period:
    try:
        return Period.parse(text)
    except ValueError as error:
        message = f"kein Zeitraum: {text!r} (z. B. 2026 oder 2026-07)"
        raise argparse.ArgumentTypeError(message) from error


# -- commands ---------------------------------------------------------------------------------


def _run_check(args: argparse.Namespace) -> int:
    """Check every file, even after an unreadable one; the worst result is the exit code."""
    worst = EXIT_OK
    for path in expand(args.pdfs):
        try:
            parsed = _read_statement(path)
        except UsageError as error:
            print(f"Fehler: {error}", file=sys.stderr)
            worst = EXIT_ERROR
            continue
        print(render_check(path.name, parsed, all_lines=args.lines))
        if not passes(parsed):
            worst = max(worst, EXIT_PROBLEMS)
    return worst


def _run_summary(args: argparse.Namespace) -> int:
    if not args.files and not args.library:
        raise UsageError("Dateien angeben oder --library verwenden.")
    workspace = _workspace(args)
    for path in expand(args.files):
        _import(workspace, path)
    summary = summarize(in_period(workspace.entries(), args.period))
    title = f"Zeitraum: {period_label(args.period)}"
    _write_outputs(summary, args, category_colors(workspace.catalog), title)
    if FORMAT_REPORT in args.format:
        target = _output(args, REPORT_PDF)
        write_report(ChartInput.of_workspace(workspace, args.period), target)
        print(f"Report gespeichert: {target}")
    return EXIT_OK


def _run_highlight(args: argparse.Namespace) -> int:
    source: Path = args.pdf
    target: Path = args.output or marked_name(source)
    if target.resolve() == source.resolve():
        raise UsageError("Die Zieldatei darf nicht der Kontoauszug selbst sein.")
    parsed = _read_statement(source)
    if not parsed.transactions:
        raise UsageError(f"{source.name}: keine Buchungen erkannt – nichts zu markieren.")
    result = write_marked_pdf(source, target, parsed.transactions, _workspace(args).categorizer)
    print(f"{result.marked} Buchungen in {len(result.legend)} Kategorien markiert: {target}")
    if result.skipped:
        print(f"{result.skipped} Buchungen ohne markierbare Position (z. B. gedrehte Seiten).")
    return EXIT_OK


def _run_merge(args: argparse.Namespace) -> int:
    summary = merge_summaries(_read_summary(path) for path in expand(args.csvs))
    _write_outputs(summary, args, category_colors(default_catalog()), MERGED_TITLE)
    return EXIT_OK


def _write_outputs(
    summary: Summary, args: argparse.Namespace, colors: dict[str, str], title: str
) -> None:
    if FORMAT_TEXT in args.format:
        print(render_text_summary(summary))
    if FORMAT_CSV in args.format:
        target = _output(args, SUMMARY_CSV)
        write_csv_summary(summary, target)
        print(f"Zusammenfassung gespeichert: {target}")
    if FORMAT_CHART in args.format:
        target = _output(args, CHART_PNG)
        figure = donut_chart(summary.expenses, colors, LIGHT).figure
        figure.suptitle(title)
        write_export(target, figure_png(figure))
        print(f"Diagramm gespeichert: {target}")


def _output(args: argparse.Namespace, name: str) -> Path:
    return ensure_folder(args.output_dir) / name


def _read_statement(path: Path) -> ParsedStatement:
    """Parse a PDF statement; the error names the file (as do the two helpers below)."""
    try:
        return read_statement(path)
    except IaahError as error:
        raise _about(path, error) from error


def _import(workspace: Workspace, path: Path) -> None:
    try:
        workspace.import_file(path)
    except IaahError as error:
        raise _about(path, error) from error


def _read_summary(path: Path) -> Summary:
    try:
        return read_csv_summary(path)
    except IaahError as error:
        raise _about(path, error) from error


def _about(path: Path, error: IaahError) -> UsageError:
    return UsageError(f"{path.name}: {german_message(error)}")


# -- check report -----------------------------------------------------------------------------


def passes(parsed: ParsedStatement) -> bool:
    """No problems: bookings found, balances agree (where stated), no suspicious lines."""
    balanced = parsed.info.reconciles is not False
    return bool(parsed.transactions) and balanced and not parsed.report.has_problems


def render_check(name: str, parsed: ParsedStatement, all_lines: bool = False) -> str:
    """The ``check`` report of one statement."""
    count, total = len(parsed.transactions), format_euro(parsed.info.total)
    lines = [
        name,
        f"  Buchungen:       {count}   Summe: {total}",
        f"  Saldo-Abgleich:  {balance_check(parsed)}",
        f"  Zeilen:          {_status_counts(parsed)}",
    ]
    problems = [*parsed.report.with_status(LineStatus.BAD_HEAD), *parsed.report.suspicious]
    if problems:
        lines.append("  Auffällige Zeilen (sehen nach einer Buchung aus, wurden aber keine):")
        lines.extend(f"    {_line(diagnosis)}" for diagnosis in problems)
    if all_lines:
        lines.append("  Alle Zeilen:")
        lines.extend(f"    {_line(diagnosis)}" for diagnosis in parsed.report.lines)
    return "\n".join(lines)


def balance_check(parsed: ParsedStatement) -> str:
    """Opening balance plus bookings against the closing balance, in words."""
    info = parsed.info
    if info.opening_balance is None or info.closing_balance is None:
        return "nicht prüfbar (der Auszug nennt keinen alten und neuen Saldo)"
    expected = info.opening_balance + info.total
    if expected == info.closing_balance:
        return f"ok ({format_euro(info.opening_balance)} + Buchungen = {format_euro(expected)})"
    stated, difference = info.closing_balance, info.closing_balance - expected
    return (
        f"ABWEICHUNG: erwartet {format_euro(expected)}, Auszug nennt {format_euro(stated)} "
        f"(Differenz {format_euro(difference)})"
    )


def _status_counts(parsed: ParsedStatement) -> str:
    counts = parsed.report.counts()
    present = (status for status in LineStatus if status in counts)
    return ", ".join(f"{STATUS_LABELS[status]} {counts[status]}" for status in present)


def _line(diagnosis: LineDiagnosis) -> str:
    label = STATUS_LABELS[diagnosis.status]
    return f"S. {diagnosis.line.page}  {label:<{LINE_LABEL_WIDTH}} {diagnosis.line.text}"


# -- helpers ----------------------------------------------------------------------------------


def expand(patterns: Iterable[str]) -> list[Path]:
    """Paths, with a pattern in the file name (``auszuege\\*.pdf``) expanded – Windows shells
    do not do it. An existing file is taken as it is (``Auszug [1].pdf``); a pattern that
    matches nothing is an error, not silence."""
    paths: list[Path] = []
    for pattern in map(Path, patterns):
        if pattern.exists() or not GLOB_CHARACTERS.intersection(pattern.name):
            paths.append(pattern)
            continue
        matches = sorted(pattern.parent.glob(pattern.name))
        if not matches:
            raise UsageError(f"Keine Datei passt zu {pattern}.")
        paths.extend(matches)
    return paths


def _workspace(args: argparse.Namespace) -> Workspace:
    """Catalog from ``--categories``, the app's data (``--library``) or the defaults."""
    if args.library:
        return _library_workspace()
    catalog = load_catalog(args.categories) if args.categories else default_catalog()
    return Workspace(catalog, Library())


def _library_workspace() -> Workspace:
    store = DataStore(DataPaths.default(), read_only=True)
    if store.needs_password():
        _unlock(store)
    try:
        workspace = Workspace.load(store)
    except PasswordRequiredError:  # damaged data file, encrypted backup
        _unlock(store)
        workspace = Workspace.load(store)
    if store.recovered_from_backup:
        print("Hinweis: Die Datendatei ist beschädigt, verwendet wird die Sicherungskopie. "
              "Die App repariert das beim nächsten Start.", file=sys.stderr)  # fmt: skip
    return workspace


def _unlock(store: DataStore) -> None:
    for attempt in range(1, PASSWORD_ATTEMPTS + 1):
        try:
            store.unlock(getpass.getpass("Passwort der I-Aah-Daten: "))
            return
        except WrongPasswordError:
            if attempt == PASSWORD_ATTEMPTS:
                raise
            print("Falsches Passwort, bitte noch einmal.", file=sys.stderr)


def _utf8_console() -> None:
    """Umlauts and € on old Windows consoles (budgets' ``ensure_utf8_console``)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding=UTF8)
