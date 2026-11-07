# Review – Step 4 (GUI)

Independent review against `AGENTS.md` and `docs/design/04-gui.md`, reproduced on synthetic
data in a scratch folder. 2 high, 5 medium, 11 low findings and one group of nits. The reviewer
confirmed undo/redo (failed changes leave no step), keyword acceptance with prune, catalog
rename/remove/replace, KPI deltas, drill-down by split parts, the review hit test and
before/after boxes, start-up paths that must not touch files (wrong password then cancel,
damaged with "Nein", newer version: byte-identical), the save guard, the worker never touching
Tk or the session, and no leaks after 50 refreshes.

After revision: 660 tests green, 5 skipped (real-statement regressions without
`IAAH_SAMPLE_PDF`), ruff/format/mypy clean. Screenshots of every tab in light and dark at the
minimum size 1000×640 checked.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | With encrypted data the app hung at start-up: the password dialog was transient for the hidden main window and stayed invisible; the hung process held the instance lock. | **Fixed.** `Dialog` is transient only when its owner is viewable; `show()` deiconifies, lifts and focuses. New Tk smoke test: a dialog on a withdrawn root is viewable and not transient. |
| 2 | high | *Alte I-Aah-Daten übernehmen* replaced existing categories, keywords and decisions whenever no statement was imported (the hint even recommended *Bibliothek leeren* first); the start-up offer came back on every start. | **Fixed.** `Session.is_pristine()` (default catalog, empty library, no decisions) gates the start-up offer. The menu entry needs an empty library and, if categories or decisions exist, an explicit confirmation naming what is replaced. Test: legacy data only goes into a pristine state. |
| 3 | med | Closing the "Einlesen…" window wedged the importer (`busy` stayed true); any unexpected exception in `_poll`/`_work` did the same. | **Fixed.** The progress window ignores close; `_poll` reschedules in `finally`, `_finish` resets `busy` in `finally`, `_work` always posts the end marker and reports an unforeseen parser error as `StatementParseError`. Tests: end marker after errors, known hashes skipped without parsing. |
| 4 | med | App-wide shortcuts fired inside modal dialogs and entry fields (Ctrl+Z in the password dialog undid an assignment, Ctrl+O opened the import). | **Fixed.** `App._shortcut` ignores events from other toplevels; Ctrl+Z/Ctrl+Y leave entry and text fields their own undo. |
| 5 | med | Live filters cost 270–425 ms per key with 5 000 bookings (every key release rebuilt options and buttons and resolved all bookings). | **Fixed.** Filters wait 150 ms after the last key and refresh only the table; resolutions are cached until the data changes; cheap filters run before the costly ones. |
| 6 | med | The analysis tab drew every chart twice. | **Fixed.** `draw_idle()`; the caption wraps on `<Configure>` instead of a fixed width. |
| 7 | med | Betrag and Kategorie were invisible at 1000×640 (850 px of columns in ~530 px, no horizontal scrollbar). | **Fixed.** Narrower base widths, side panel 330 px, horizontal scrollbar. At 1000×640 Betrag is visible (after the second round: ends at 529 of 531 px) and Kategorie is one scroll away (the row tint and the side panel show it too); at the default 1250×780 all columns fit. |
| 8 | low | The review tab kept the statement PDF open (Windows could not move or delete it). | **Fixed.** pdfplumber reads the file from memory (`BytesIO`). |
| 9 | low | The budgets tab dropped typed values on refresh or undo. | **Fixed.** Typed but unsaved values survive a refresh. |
| 10 | low | Ctrl+Z with nothing to undo said "Rückgängig gemacht." and refreshed everything. | **Fixed.** Reports "Nichts rückgängig zu machen." / "Nichts zu wiederholen." and refreshes nothing. |
| 11 | low | The category filter went stale after rename, remove or undo (0 rows, unlisted value). | **Fixed.** The session renames the filter with the category and clears it when the category is gone. Test added. |
| 12 | low | Start-up called every storage error "beschädigt" and offered to set healthy but unreadable (e.g. locked) data aside; a missing data file read from the backup was also reported as damaged. | **Fixed.** New `DataUnreadableError` (core) for read errors: message and exit, nothing moved. The recovery note distinguishes a missing from a damaged data file. Tests in `test_storage.py`. |
| 13 | low | *Passwort festlegen* deleted the damaged copies before the password was entered and claimed "nur noch verschlüsselt" when copies were kept. | **Fixed.** New password first, then the question about the copies; the message says when unencrypted copies remain. |
| 14 | low | Keyword suggestions were offered for open bookings (accepting one closed the booking without a decision); the condition sat in the widget. | **Fixed.** `Session.suggestions` returns suggestions only for manual decisions. Test added. |
| 15 | low | The status line counted whole split bookings under a category filter. | **Fixed.** `view_totals(rows, category)` counts only the matching part. Test added. |
| 16 | low | Dark mode: black text cursor; analysis caption cut at 1000 px; with 0 bookings no import hint but "Alles zugeordnet 🎉". | **Fixed.** `insertcolor` for entry, combobox, spinbox and the classic Text; caption wraps with the window; empty table shows an import hint. |
| 17 | low | Report and summary exports could overwrite an imported statement PDF. | **Fixed.** Every export target goes through `exports._target`, which refuses imported statement files. Test added. |
| 18 | low | Undocumented parity differences: context menu without *Stichwort vorschlagen…* but with *In der PDF-Prüfung zeigen*; *Beschädigte Kopien löschen…* always shown; the review tab numbers its buttons 1–9 but the keys only worked in the table. | **Fixed:** keys 1–9 also work on the review canvas and list. **Accepted and documented** in the design note: suggestions sit permanently in the side panel, so the context menu offers the jump to the PDF review instead; the copies entry is always shown and says when there is nothing to delete (a menu that changes with the disk state is harder to find). |
| 19 | nit | Decision logic in widgets (review row building and matching, duplicated amount validation); dead `Session.index_of`; `PAD * 2` and inline literals; 38-line `_menu_file`; `rstrip(" ⊘")` strips a character set; no-op changes create an undo step; a maximized window was saved as a huge plain size. | **Fixed:** `viewmodel.review_rows`/`position_of`, `Session.statement_of`, `viewmodel.budget_from_text` shared by both tabs; `index_of` removed; `PAD_LARGE` and named constants; export menu split off; kind names from a mapping instead of stripping; no-op changes leave no undo step and do not save; a zoomed window is stored as `zoomed`. |

Test gaps closed: Tk smoke tests (`tests/test_gui_smoke.py`, skipped without a display: hidden
owner dialog, every tab in both themes, importer worker), migration gate, no-op undo, filter
follows rename/removal, suggestions only after manual decisions, split totals, resolution cache,
budget text, export target guard, `start_over` without files and read-only, unreadable data file
is no damage.

Left open after the first round and closed in the second: start-up flows with patched dialogs,
undo across rename/remove/recolor/kind and `UNDO_LIMIT`, `error_message` texts,
`exports._filtered_entries`.

## Second round

The reviewer verified the rows above with probes on synthetic data: 1, 2, 5, 6, 8, 10, 12–14
and 19 hold; 3, 4, 7, 9, 11, 15–18 hold with the remarks below. One high and one medium finding
came from the revision itself. After revision: 682 tests green, 5 skipped, ruff/format/mypy
clean; the Tk smoke tests pass three times in a row.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 20 | high | Ctrl+1…5 switched the tab **and** assigned the selected bookings: Tk lets a plain `"2"` binding match Ctrl+2, and the widget binding runs before the app-wide one. | **Fixed.** `widgets.bind_digits` binds 1–9 for the table, the review canvas and the review list and ignores events with Ctrl held. Smoke test generates Ctrl+2 (tab switches, nothing assigned) and 2 (assigns). |
| 21 | med | Budgets tab (row 9 revisited): an input counted as typed whenever it differed from the *new* stored value, so undo and budgets set on the categories tab were hidden – and saved back. | **Fixed.** The tab remembers what each entry showed at the last refresh; `viewmodel.unsaved_budgets` keeps only inputs changed since then and not equal to the stored budget. Unit test plus smoke test (type, refresh, save, undo, change elsewhere). |
| 22 | low | A failing `_finish` left the importer polling forever and skipped the summary. | **Fixed.** `_poll` finishes once the end marker is taken; `_finish` calls `on_done` in `finally`. Smoke test with a failing step. |
| 23 | low | Exports under a category filter contained the other split parts (row 15 revisited). | **Fixed.** `_filtered_entries` keeps only the filtered category's entries, as the status line. Test added. |
| 24 | low | *Kategorien speichern unter…* could overwrite an imported CSV statement (row 17 revisited). | **Fixed.** Same guard as the exports. Smoke test. |
| 25 | low | Betrag clipped by ~11 px at 1000×640; the disposition of row 7 mentioned a `minwidth` that does not exist. | **Fixed.** Buchungsart 95 → 82 px; row 7 corrected. |
| 26 | low (uncertain) | Closing the main window while a CSV-mapping dialog is open could destroy widgets the import still uses. | **Fixed defensively.** `App.quit` refuses while an import runs or a modal dialog holds the grab, with a status note. |
| 27 | nit | Context menu leaked a `tk.Menu` per right-click; Ctrl+Z ignored on read-only comboboxes; `DataUnreadableError` text spoke of a lock only; English `OSError` text in the review tab; unused loop variable; duplicate `except` branches; the visible tab built twice at start; 30-line `show_entries`; no missing months after the menu's CSV import; mypy override for all of `iaah.gui`; undoing a rename clears the filter instead of restoring it; design note still said damaged copies are shown only if present. | **Fixed:** the last menu is destroyed before a new one; read-only comboboxes do not count as text fields; message names lock, permissions or a non-file; German text with the path; loop over `KIND_NAMES`; one `except StorageError`; the start refreshes again only after a migration; columns and cells extracted; missing months reported; override limited to the Tk modules. **Accepted:** the filter is view state, not data – clearing it after an undone rename is safe and visible. Design note corrected. |
| 28 | — | Own finding while writing the README: a statement imported before but now in another folder was skipped as "already imported" with its old path, so the PDF review could not find it any more. | **Fixed.** `Library.relocate` (core) stores the new location for a known hash; `Workspace.import_file`, `Library.add` and the GUI importer use it, the summary lists "Bereits importiert, neuer Speicherort übernommen". Tests in core and session. |

Test gaps closed: `tests/test_gui_startup.py` (password wrong/right/cancel, newer and unreadable
data, damaged with "Nein"/"Ja", recovery report, start-up and menu migration gates – all with
scripted dialogs, files compared byte for byte), undo across every category change and
`UNDO_LIMIT`, a failed save keeps the undo step, `error_message`, filtered exports, unsaved budget
inputs, the real `Dialog.show()` with grab, key routing, importer failure path, category-save
guard, relocated statements.
