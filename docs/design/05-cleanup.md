# Step 5 – Clean-up, README, Windows build

Last step of the unification: the legacy single-file app leaves the repository, the README
becomes the German manual of the new app, and the `.exe` build is a documented command instead
of a batch file. No production code changes apart from configuration.

## Removed files

| File | Replaced by |
|---|---|
| `kontoanalyse.py` | `iaah.gui` (`iaah` / `python -m iaah`) |
| `parser.py` | `iaah.core.parsing` (`ing`, `layout`, `diagnostics`, `csv_import`) |
| `highlight.py` | `iaah.export.marked_pdf` |
| `smoke_test.py` | `tests/test_sample_statement.py` and `tests/test_workspace.py` with `IAAH_SAMPLE_PDF` (the old script wrote test files next to itself and hard-coded the statement path) |
| `Start.bat` | the `iaah` GUI entry point (`.venv\Scripts\iaah.exe`) or the built `I-Aah.exe` |
| `build_exe.bat` | the PyInstaller command in the README |
| `requirements.txt` | `pyproject.toml` (dependencies and the `dev`/`build` extras) |

The personal legacy files in the working copy (`settings.json`, `data.json`, `ui_state.json`
and their `.bak`) are untracked and ignored; this step does not touch them. The README explains
how to take them over (*Datei → Alte I-Aah-Daten übernehmen…*) and that they can be archived or
deleted afterwards.

## Configuration

* `pyproject.toml`: the legacy names leave `extend-exclude` (only `docs` stays).
* `AGENTS.md`: status says the unification is complete; the legacy-file remark goes.
* `.gitignore` already covers `build/`, `dist/` and `*.spec` – nothing to add.

## Deviation from the plan: no `categories.example.json`

The plan listed an example category file in the repository root. It is dropped:

* the default catalog already ships as `src/iaah/data/default_categories.json` (package data);
* *Kategorien → Kategorien speichern unter…* writes the current catalog as JSON or CSV – the best
  template, with the user's own names;
* a second copy would drift from the real default.

The README documents both file formats briefly instead.

## README (German user manual)

1. What I-Aah does (one paragraph) and the feature list.
2. Installation: Python ≥ 3.12, venv, `pip install -e .`; Tk on Linux.
3. Start: `iaah`, `python -m iaah`, or the `.exe`.
4. First steps: import → assign → keyword suggestions → analysis.
5. The five tabs, one section each.
6. Menus: every entry with what it does; exports name format and content.
7. Keyboard shortcuts (table).
8. Categories and keywords: matching (normalised text, longest keyword wins), fallbacks
   *Sonstiges*/*Einkommen*, *Ignoriert*, manual decisions and splits; file formats.
9. Where data lives (`%LOCALAPPDATA%\I-Aah`, `IAAH_HOME`), backups, damaged copies, password.
10. Switching from the old version (migration; old files stay untouched).
11. Command line `iaah-cli` (`check`, `summary`, `highlight`, `merge`) with examples.
12. Building the Windows `.exe`.
13. Development (pointer to `AGENTS.md`), licence and third-party notice.

Texts follow the GUI labels exactly (copied from `gui/app.py` and the tabs).

## Windows build

```powershell
pip install -e ".[build]"
pyinstaller --noconfirm --clean --onefile --windowed --name I-Aah `
  --paths src `
  --collect-data iaah --copy-metadata iaah `
  --collect-data pdfminer --collect-data reportlab `
  --add-data "LICENSE;." --add-data "LICENSES;LICENSES" `
  src\iaah\__main__.py
```

* `--paths src` – finds the package even if the editable install uses an import hook.
* `--collect-data iaah` – the bundled default catalog (`importlib.resources`).
* `--copy-metadata iaah` – `iaah.__version__` reads the installed metadata; without it the
  import fails inside the `.exe`.
* `pdfminer` ships CMap files, `reportlab` its standard fonts – both are data, not code.
  matplotlib, Tk and cryptography are covered by PyInstaller's own hooks.
* `LICENSE`/`LICENSES` travel with the binary (MIT notice of *budgets*).

Verification: build once, start `dist\I-Aah.exe` with `IAAH_HOME` set to an empty scratch folder,
check that the window opens and the default categories are there, close it.

## Checks

`pytest`, `ruff check .`, `ruff format --check .`, `mypy`. No new tests: no behaviour changes.
A grep confirms no remaining references to the removed files outside `docs/`.

## Afterwards (done by the user)

Remove `settings.json` from the Git history (`git filter-repo --path settings.json
--invert-paths`, re-add the remote, force push). Step-by-step instructions follow after this
step is committed.
