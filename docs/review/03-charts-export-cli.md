# Review – Step 3 (charts, exports, `iaah-cli`)

Independent review against `AGENTS.md` and `docs/design/03-charts-export-cli.md`. No high
findings; 6 medium, 7 low, nits and test gaps. The reviewer confirmed layering, typing,
formula-injection defence, summary CSV round trips, split stripes and drill targets, privacy of
chart labels, and parity with all 13 legacy charts, the CSV/Excel export and the report.

After revision: 603 tests green, ruff/format/mypy clean. Real statements (read-only, outputs
in a scratch folder): `check` reconciles all five, `highlight` marks 48 bookings – overlay
rectangles identical to before the geometry fix (those PDFs start at 0,0) –, `summary
--library` with an empty data folder writes CSV, chart and report and creates no folder.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | med | Marked PDF: the media-box offset was added twice (pdfplumber's x is absolute, `y = height - top`); marks missed the text on PDFs whose box does not start at 0,0. | **Fixed.** No offset added. New test checks with pdfplumber that every overlay rectangle encloses its words, for a box at 0,0 and one at 20,30. |
| 2 | med | `--library` changed the data directory: it set a damaged file aside, deleted temp files, created folder and lock file. | **Fixed.** `DataStore(read_only=True)`: no lock, no set-aside, no tidying, every write refused; the CLI uses it and notes when it read the backup. Tests compare the whole directory before and after, also for a damaged file and a missing folder. |
| 3 | med | Labels went through mathtext: a payee `Shop $\foo$` crashed the merchants chart and the report. | **Fixed.** `text.parse_math: False` in the theme; test draws such a payee. |
| 4 | med | The summary dropped categories whose refunds outweigh spending, so its net differed from the KPIs (and the donut centre). | **Fixed.** `core.analysis.totals.category_totals` keeps them with a negative amount; summary totals now equal `totals()`. The donut lists them below the ring ("Mehr erstattet als ausgegeben: …"). |
| 5 | med | Write errors (output folder is a file, missing folder, file open in a viewer) escaped as raw `OSError`. | **Fixed.** `export/files.py`: every export writes through `write_export`/`ensure_folder` and raises `ExportError`; the CLI prints a German message, `-v` adds details. |
| 6 | med | `merge --format chart` crashed on negative or zero amounts. | **Fixed** with 4: the donut shows positive amounts only. |
| 7 | low | All-time calendar labelled its first column with the Monday's month. | **Fixed.** Labelled by the first day inside the range. |
| 8 | low | Budget title said "0 Monat(e)" while limits used one month. | **Fixed.** Title and limits use the same count. |
| 9 | low | Control characters in a payee broke the Excel export. | **Fixed.** Stripped (openpyxl's `ILLEGAL_CHARACTERS_RE`). |
| 10 | low | Marks on rotated pages landed off the text. | **Fixed.** Rotated pages stay unmarked and count as skipped; the CLI says so. |
| 11 | low | `check`/`merge` with a pattern matching nothing and `highlight` on a PDF without bookings succeeded silently. | **Fixed.** German error, exit code 2; nothing is written. |
| 12 | low | Sankey broke with ≥ 50 categories. | **Fixed.** At most 12 bands; the smallest categories share "Übrige Kategorien (n)" (not clickable). |
| 13 | low | Legend: characters outside the PDF font showed as ■, long names overlapped the columns. | **Fixed.** `printable`: cut to 36 characters, unknown characters become `?`. |
| 14 | nit | English detail in CLI errors; missing ported-code header; CLI donut without period; cover wording "kein Auszug importiert"; duplicated color mapping; private `argparse._SubParsersAction`; long names collapsing charts; unbounded calendar. | **Fixed:** details only with `-v`; header added; chart PNG titled with the period; cover says "Monate ohne Buchungen: Dez 25"; `category_colors` shared; subparsers configured without the private type; names cut to 28 characters (`style.short`). **Accepted:** the all-time calendar has one cell per day (six years ≈ 2 150 cells, built and drawn in 1.5 s after adding cells without per-patch autoscaling). |

Test gaps closed: geometry test with pdfplumber (finding 1), summary net against `totals()`
with a refund surplus, read-only directory comparisons, all-time calendar labels, CLI write
failures, merge chart with negative amounts, `$` in payees, rotated pages, control characters.
