# Review – Step 5 (clean-up, README, Windows build)

Independent review against `AGENTS.md` and `docs/design/05-cleanup.md`. The reviewer checked
every factual claim of the README against the code and ran every `iaah-cli` example on a
synthetic statement. It also checked that nothing still refers to the deleted files and rebuilt
the exe into a scratch folder: the exe started with the default categories (window captured with
`PrintWindow` only). One high finding – a code bug, not a README error – 2 medium, 12 low and a
handful of nits.

Verified as correct: menu labels, order and actions; tab and button texts; shortcuts (digit keys
ignore Ctrl, undo/redo skip text fields); table markers; filters; keyword matching (word start,
umlaut/ß/accent folding, longest keyword, income keywords only for money in, fallback by sign);
budget thresholds; category file formats and the reading of *budgets* files; data paths,
`IAAH_HOME`, backup and damaged copies, encryption, instance lock, read-only `--library`; the
migration gates; export contents; the 13 chart titles; both README anchors; entry points and
package data in a wheel; the PyInstaller flags.

After revision: 683 tests green, 5 skipped (9 of 9 green against the real reference statement
with `IAAH_SAMPLE_PDF`), ruff/format/mypy clean; the exe was rebuilt with the corrected command
and started.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | Migrating **encrypted** legacy data stored it **unencrypted**: `_adopt` ignored the legacy password, and `Session.adopt` saved with the store's cipher, which is `None` on a first start. | **Fixed.** `migrate_from` passes the legacy password on; `Session.adopt(…, password)` writes the adopted data encrypted right away (`enable_encryption`, never a plain save first) unless the data already has a password of its own. Test: the new `library.json` is encrypted, contains no payee in plain text, and opens with the old password. |
| 2 | med | README: `-v` works only before the command. | **Fixed.** „`iaah-cli -v <Befehl> …` (`-v` vor dem Befehl)“. |
| 3 | med | README: *Ignoriert* „zählt in keiner Auswertung“ – but *Echter Kontostand* and *Saldo-Verlauf* show all bookings. | **Fixed.** Now names where ignored categories count and where not. |
| 4 | low | *Kategorien aus Datei laden…* replaces everything – not said. | **Fixed.** |
| 5 | low | The fallback role is required in own JSON files; CSV and *budgets* files get the fallbacks added. | **Fixed.** |
| 6 | low | `--library` also uses the app's bookings and asks for the password. | **Fixed.** |
| 7 | low | `merge` example: `summary` always writes `zusammenfassung.csv`; a second run overwrites the first. | **Fixed.** The example writes each month into its own folder, then merges them. |
| 8 | low | Budgets tab: own period and the *Stand* column (traffic light) not described. | **Fixed.** |
| 9 | low | A one-file exe unpacks on *every* start, not only the first. | **Fixed.** |
| 10 | low | „mit Passwort verschlüsselt“ read as always encrypted. | **Fixed.** „verschlüsselt, sobald ein Passwort festgelegt ist“. |
| 11 | low | Damaged data without a backup (question, „Nein“ quits) not described. | **Fixed**, together with the unreadable-file case. |
| 12 | low | `py -3.14` exists only on Windows. | **Fixed.** Linux/macOS: `python3 -m venv .venv`. |
| 13 | low | The migration report also lists changed automatic categories and dropped amount limits; legacy `ui_state.json` is not taken over. | **Fixed.** |
| 14 | low | Broken umlauts: matching repairs only the known words too. | **Fixed.** |
| 15 | low | `.gitignore` missed `kategorien.json`, `zusammenfassung*.txt`, `ausgaben.png`, `library.json.damaged-*`, `iaah.lock` – files with personal data. | **Fixed.** Rules added and checked with `git check-ignore`; no tracked file is ignored. The design note's "nothing to add" is corrected. |
| 16 | low | The exe bundled `iaah-*.dist-info/direct_url.json` (via `--copy-metadata`), which holds the path of the developer's checkout. | **Fixed.** The version now has a single source, `iaah.__version__` (pyproject reads it via `[tool.setuptools.dynamic]`). Nothing needs the installed metadata at run time, so `--copy-metadata` is gone from the build command. |
| 17 | nit | German wording (lines 97, 186); suggestion count includes the booking itself; the Ø card shows a month count, not a comparison; balance reconciled only for PDFs; confirming the fallback by hand gives `✎`; *Löschen* also removes the decisions (undo restores them) and the fallbacks' kind is fixed; review-tab navigation (◀ ▶, − +, Ctrl+wheel, dark outline) missing; the mapping dialog also opens automatically; `check` exit codes and output file names undocumented; text summary printed `57.6 %`; stale legacy `.pyc` in the local `__pycache__/`. | **Fixed:** all README points; the text summary now prints `57,6 %` (test added). **Not changed:** the local `__pycache__/` is ignored and never committed – it can be deleted by hand. |
