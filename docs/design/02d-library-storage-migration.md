# Step 2d – Library, workspace, storage and migration

## Modules

| Module | Responsibility |
|---|---|
| `core/library.py` | `StoredStatement`, `Library` (statements, transactions, manual assignments), import with de-duplication. |
| `core/workspace.py` | `Workspace` = catalog + library; operations that must touch both (import, re-categorize). Renaming/removing categories together with their decisions already lives in `Categorizer` (step 2b) – the workspace delegates. |
| `core/storage.py` | Data directory, atomic writes with `.bak`, JSON codecs for library and UI state, encryption. |
| `core/migration.py` | One-way import of the legacy `settings.json` / `data.json`. |

## Library and import

```python
@dataclass(frozen=True, slots=True)
class StoredStatement: info: StatementInfo; path: str | None; sha256: str | None

class Library:
    statements: list[StoredStatement]; transactions: list[Transaction]; assignments: ManualAssignments
    add(parsed: ParsedStatement, path: Path | None, sha256: str | None) -> ImportResult
    months() -> list[str]; reset()

@dataclass(frozen=True, slots=True)
class ImportResult: added: int; duplicates: int; enriched: int; already_imported: bool
```

* A file whose SHA-256 is already in the library is skipped as a whole.
* Otherwise bookings are de-duplicated as a **multiset** of `Transaction.key`: two identical
  coffees on the same day in one statement stay two bookings, while re-importing an
  overlapping CSV adds nothing twice.
* A duplicate that brings a `Placement` replaces a stored booking without one (`enriched`) –
  this is how migrated legacy bookings gain bounding boxes when their PDF is imported again.
* The statement path is stored so the PDF review tab can reopen it; a missing file is
  reported by the GUI, not an error here.

## Storage

* Data directory: `IAAH_HOME` if set, else `platformdirs.user_data_dir("I-Aah", appauthor=False)`
  (Windows: `%LOCALAPPDATA%\I-Aah`). Files: `categories.json`, `library.json`, `ui_state.json`.
* `atomic_write(path, data: bytes)`: write `*.tmp`, fsync, keep the previous file as `*.bak`,
  replace – a crash never leaves a half-written file (legacy behaviour, now with `pathlib`).
* JSON schema with `"version": 1`; money as decimal strings, dates ISO, bounding boxes as lists.
* **Encryption** (optional, for `library.json`): Fernet with a PBKDF2-HMAC-SHA256 key.
  New files use `IAAHENC2\n<iterations>\n<salt>\n<token>` with 600 000 iterations (current
  OWASP guidance); legacy `IAAHENC1` files (200 000 iterations) stay readable. The key is
  derived once per session and kept in a `Cipher` object. Wrong password → `WrongPasswordError`.

## Migration from the legacy app

`find_legacy_files(directory)` → `LegacyFiles(settings, data)`;
`migrate(legacy, defaults) -> Migration(catalog, library, report)`. The legacy files are only
read, never changed.

| Legacy | New |
|---|---|
| category `name`, `color` | same; `exclude: true` → kind `IGNORED` |
| `Einkommen` | kind `INCOME`, role `INCOME_FALLBACK` |
| `Sonstiges` | role `EXPENSE_FALLBACK` |
| `Nicht zugeordnet` | dropped (unmatched bookings fall back automatically) |
| missing defaults | `Ignoriert` and missing fallbacks added from the default catalog |
| rule `keyword → category` | keyword (normalized) appended to that category |
| regex rule / amount bounds | literal regex becomes a keyword; everything else is listed in the report |
| keyword claimed twice | first wins, conflict listed in the report |
| `budgets` | `Category.budget` |
| `overrides` (str / split list) | manual assignment / split, key rebuilt with the normalized payee |
| `data.json` transactions + statements | `Library` (no placements until the PDF is imported again) |

**Re-splitting legacy payees.** The new parser splits `Gutschrift/Dauerauftrag X` into type
`Gutschrift/Dauerauftrag` and payee `X`; the legacy parser stored payee `/Dauerauftrag X`
(3 bookings in the real data, no manual assignments affected). Migration rebuilds the head text
from the legacy type and payee and splits it again with `split_booking_type`, so migrated keys
equal those of a fresh PDF import and re-importing does not create duplicates.

`MigrationReport` lists counts and every dropped or changed item, and – because matching moves
from substring to token-start – how many bookings get a different automatic category than
before. The GUI shows it once after migrating.

## Refinements before implementation

1. **One persistence object for the GUI:** `DataStore(paths, cipher=None)` with
   `load_catalog`/`save_catalog`, `load_library`/`save_library`, `needs_password`, `unlock`,
   `enable_encryption`/`disable_encryption`, plus raw `load_ui_state`/`save_ui_state` (the GUI
   owns that schema). When encryption is on, **both** `library.json` and `categories.json` are
   encrypted – keywords name the user's merchants too.
2. **Legacy statements upgrade in place:** importing a PDF whose file name matches a migrated
   statement without hash replaces that statement (path and hash added), and its bookings are
   enriched with placements and the clean purpose text of the new parser (legacy purposes are
   glued, see review 2c).
3. **Legacy colors:** a category keeps its legacy color only if the user changed it; untouched
   legacy default colors (saturated) are replaced by the default catalog's pastel color of the
   same name, or the next free palette color.
4. **Override keys** are rebuilt through the legacy bookings: legacy key → legacy booking →
   re-split payee → new key. Overrides without a booking get the normalized payee part.
5. **Report of changed automatic categories:** the legacy matcher (uppercase substring, longest
   keyword, regex and amount bounds) is re-implemented in `migration.py` only to compare; the
   report lists every booking without a manual decision whose automatic category differs.
6. `Workspace.import_file(path)` picks the reader by suffix (`.pdf` → ING, `.csv` → CSV
   import) and computes the SHA-256; `Workspace.entries()` builds the analysis entries.
7. Encrypted legacy `data.json` (`IAAHENC1`) needs the password once; the migrated library is
   then saved with the new format (`IAAHENC2`, fresh salt, 600 000 iterations).

## Revisions after review (see `docs/review/02d-library-storage-migration.md`)

* **One data file** (`library.json`) holds catalog *and* library (`core/document.py`). Two
  files could be saved half (rename touches both) and an interrupted password change could
  leave them under two keys; one atomic write rules both out. `DataStore.load()` /
  `save(catalog, library)` replace the per-file methods; category files remain for
  import/export through `category_io`.
* Module split: `core/crypto.py` (cipher, envelopes), `core/document.py` (format),
  `core/storage.py` (paths, atomic write, backup recovery, `InstanceLock`, `DataStore`).
* Atomic write copies the current file to `*.bak` and replaces it in one rename – the file
  never disappears; a damaged file is recovered from the backup (`recovered_from_backup`).
  `enable_encryption` / `disable_encryption` rewrite the backup in the new form (first
  revision: deleted it – see the second review), so no copy in the old form stays behind.
  `InstanceLock` (OS file lock) keeps a second instance out.
* De-duplication requires a compatible account (equal or unknown on one side).
* `Workspace.import_file` checks the hash before parsing; `is_empty()`; migration is offered
  only while `DataStore.has_data()` is false. The design's `find_legacy_files` became
  `has_legacy_files` + `read_legacy` returning `LegacyData`.
* Migration: legacy→default name aliases for colors and default keywords; free colors are
  chosen against the catalog being built; splits are checked against the booking amount with
  cent rounding absorbed, "unassigned" parts go to the expense fallback; the report compares
  with what the legacy app showed on its own payee text.

## Revisions after the second review

* **Recovery never destroys newer data.** A damaged data file is moved to
  `library.json.damaged-<time>` (a name no save writes to) *after* the backup decoded and
  *before* it is used; if the move fails, loading stops with `StorageError`. A document from a
  newer program version raises `UnsupportedVersionError` and is never "recovered". Damaged
  copies may hold plaintext, so `DataStore.damaged_copies()` lets the GUI list them when
  encryption is switched on.
* **Encryption switch:** `_switch` writes the backup in the new form first, then the data file,
  and changes the session's cipher only after both succeeded. A failure leaves the data file
  in the old form and the session using it.
* **Encryption follows the data file:** `needs_password` looks at the data file (the backup
  only when there is none). Because the switch writes the backup first, an interrupted enable
  leaves a plain data file with an encrypted backup (no password needed), an interrupted
  disable the reverse; either way `load` copies the data file over the backup and deletes
  leftover `*.tmp` files, so no plaintext survives the next start. A copy encrypted with a key
  other than the session's counts as damaged. When the password fits neither copy,
  `WrongPasswordError` wins over a damaged-copy error.
* **Backups are best effort when saving:** written via `*.bak.tmp` + rename, a locked backup is
  logged and skipped. When *loading* without a data file, an unreadable backup raises – it
  must never look like a first start.
* **Only loaded data is overwritten:** `save` and the encryption switch require that the
  session's last `load` succeeded (or that there is no data); a failed load revokes that, so a
  newer-version file, a file whose password prompt was cancelled or a damaged file without
  backup is never replaced. Starting over after such a failure is a deliberate GUI action
  (step 4: move the file aside, then save).
* Malformed content of any kind (absurdly long numbers, deep nesting, infinite page numbers,
  iteration counts beyond `MAX_ITERATIONS`) is a `StorageError`, so recovery is tried.
* `InstanceLock`: an unopenable lock file is a `StorageError` (not "already running");
  `release` always closes the file.
* **Accounts:** migrated bookings take the account of their statement; CSV imports read the
  IBAN from the lines above the header (`find_iban`) and derive the account like the PDF
  parser (`account_from_iban`). Only CSV files without IBAN still yield account-less bookings.
* Decisions whose legacy booking is gone get the unglued payee ("/Dauerauftrag X" → "X").
* **UI state** is never encrypted and therefore restricted to `UI_STATE_KEYS` (layout and
  look) with scalar or number-list values; anything else raises on save and is dropped on load.
  String values must be view identifiers, never account, payee or category names. The GUI step
  extends the set deliberately.

## Tests

`test_library.py` (hash skip, multiset de-dup, enrichment), `test_storage.py` (round trip of
library and catalog, atomic write keeps `.bak`, encryption round trip, wrong password, legacy
`IAAHENC1` blob readable, `IAAH_HOME`), `test_migration.py` (synthetic legacy files covering
every row of the table above).
