# Step 2d – Library, workspace, storage and migration

## Modules

| Module | Responsibility |
|---|---|
| `core/library.py` | `StoredStatement`, `Library` (statements, transactions, manual assignments), import with de-duplication. |
| `core/workspace.py` | `Workspace` = catalog + library; operations that must touch both (rename/remove category, import). |
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

## Tests

`test_library.py` (hash skip, multiset de-dup, enrichment), `test_storage.py` (round trip of
library and catalog, atomic write keeps `.bak`, encryption round trip, wrong password, legacy
`IAAHENC1` blob readable, `IAAH_HOME`), `test_migration.py` (synthetic legacy files covering
every row of the table above).
