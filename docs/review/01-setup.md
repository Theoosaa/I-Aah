# Review – Step 1 (project setup)

Independent review against `AGENTS.md` and `docs/design/01-setup.md`. 14 findings; each is
listed with its disposition. All checks green afterwards: pytest (4), ruff check, ruff format,
mypy (`src` + `tests`).

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | "German only in `gui/` and `cli.py`" is unkeepable: chart captions, export headers, bank keywords. | **Fixed.** Language section now allows UI German in `gui/`, `cli.py`, `charts/`, `export/`; German *data* in `core` as `Final` constants; default category names in `src/iaah/data/`. |
| 2 | high | `core/export` contradicts "core never imports matplotlib" (PDF report uses matplotlib). | **Fixed.** Exports move to top-level `iaah/export/` (deviation from the plan, recorded here). Dependency arrows spelled out. |
| 3 | med | Several promises not enforced: core importing tkinter/matplotlib, magic strings, nesting, unannotated globals, blind `except`, module docstrings. | **Fixed** where tooling exists: `tests/test_architecture.py` enforces layer imports (probed with forbidden imports – fails as expected); `BLE`, `D100`, `D104` selected; `allow-magic-value-types = []`. **Review-only** (no stable tool support): magic values outside comparisons, nesting depth (PLR1702 is preview), `Final` on globals – AGENTS.md now separates "enforced" from "checked in review". |
| 4 | med | `RUF001/003` reject `–` and `×` used in German UI text. | **Fixed.** `allowed-confusables = ["–", "×"]`. |
| 5 | med | `ignore_missing_imports` silently weakens strict mode; pdfplumber entry dead. | **Fixed.** Added `types-openpyxl`, `types-reportlab`; override removed. |
| 6 | med | Tool version floors make lint results version-dependent. | **Fixed.** `ruff==0.17.4`, `mypy==2.4.1`. |
| 7 | med | Builds would ship budgets code without its notice; no project license. | **Fixed:** `setuptools>=77`, `license-files = ["LICENSES/*.txt"]` (verified in installed metadata); origin header rule for ported modules added to AGENTS.md; PyInstaller `--add-data LICENSES` noted for step 5. **Resolved later:** the owner chose MIT – `LICENSE`, `license = "MIT"`. |
| 8 | med | `.gitignore`: bank CSV/XLSX exports not ignored; unanchored names hide tool configs; fixtures blocked; duplicates. | **Fixed.** Personal files anchored to the root, `*.csv`/`*.xlsx` added, `!tests/fixtures/**`, duplicates removed. Verified with `git check-ignore --no-index`. |
| 9 | med | `settings.json` is in commit 02368cc on `origin`. **Decided:** the owner rewrites the history and force-pushes as the very last step of the unification, following instructions given then. It was frozen with `--skip-worktree`, so only the init version is published. Now untracked. |
| 10 | low | `iaah-cli` and `python -m iaah` documented but not yet present. | **Fixed.** AGENTS.md has a status note; layout table lists `__main__.py` and `gui/app.py`. Entry points arrive in steps 3/4. |
| 11 | low | Setup block mislabelled, no PowerShell activation, no Linux Tk hint, `.exe` reference dangling. | **Fixed** (PowerShell block, cmd/Linux variants, `python3-tk`). The `.exe` command is written into the README in step 5. |
| 12 | low | Tests not type-checked; pytest import mode collisions; lax pytest settings. | **Fixed.** mypy checks `tests/` too (tests no longer exempt from `ANN`); `--import-mode=importlib`, `--strict-markers`, `xfail_strict`, `filterwarnings = error`. |
| 13 | low | numpy used by legacy code but undeclared; Pillow declared but unused. | **No change.** numpy is legacy-only and the new code avoids it (rule added). Pillow is needed by the GUI PDF view (step 4). |
| 14 | low | Money rule silent on JSON and chart boundary. | **Fixed.** Decimal strings in JSON; charts accept `Decimal` and convert internally. |
| – | note | PyInstaller likely needs `--copy-metadata iaah` for `version("iaah")`. | **Deferred** to step 5 (verified there with a real build). |

Also found while revising: ruff 0.17 formats Python blocks inside Markdown, which rewrote the
pseudo-code in design notes – `docs` is excluded from ruff. The architecture test now reads
files as `utf-8-sig`, because a BOM made `ast.parse` fail for the wrong reason.
