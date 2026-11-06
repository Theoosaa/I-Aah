# Review – Step 2d (library, workspace, storage, migration)

Independent review against `AGENTS.md` and `docs/design/02d-library-storage-migration.md`.
13 findings (1 high, 6 medium, 6 low). The reviewer confirmed on the real legacy files: 329
bookings, 11 statements, 16 categories, all 51 manual assignments still applying to the same
bookings, nothing dropped; re-importing a migrated statement PDF enriched 59 bookings and kept
the assignments.

After revision: 410 tests green, ruff/format/mypy clean. Real-data dry run (scratch directory,
legacy files verified unchanged by hash): 16 categories with distinct colors, 115 keywords
(default keywords via name aliases), 51 assignments, 329 bookings, 0 dropped, 1 booking with a
different automatic category (listed in the report); after enabling encryption the directory
holds only the encrypted data file; the encrypted round trip is exact.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | After setting a password the `.bak` files kept the old **plaintext** data. | **Fixed.** `enable_encryption`/`disable_encryption` rewrite and delete the backup; test asserts that no file in the directory contains the payee in plain text. |
| 2 | med | Interrupted password change between two files locked the user out. | **Fixed by design change:** catalog and library live in one file, written atomically. |
| 3 | med | Backup only read when the main file is missing; damaged file blocked loading; crash window between two renames. | **Fixed.** Copy to `.bak`, then one atomic rename; damaged main file (incl. undecryptable) falls back to the backup and sets `recovered_from_backup`; `unlock` tries both copies. |
| 4 | med | No guard against a second instance. | **Fixed.** `InstanceLock` (msvcrt/fcntl lock, released on exit or crash). |
| 5 | med | De-duplication ignored the account – same fee on two accounts lost one booking. | **Fixed.** Matches need equal accounts or an unknown one (migrated/CSV bookings). |
| 6 | med | `next_color()` checked against the defaults, so three categories got the same color; renamed defaults got no keywords. | **Fixed.** Free colors against the catalog being built; legacy→default name aliases for color and keywords. |
| 7 | med/low | Splits validated against their own sum (rounding lost a cent); "unassigned" part dropped the split. | **Fixed.** Validated against the legacy booking amount, rounding absorbed by the largest part, "unassigned" parts go to the expense fallback. |
| 8 | low | Legacy matcher used the re-split payee; positive "unassigned" bookings mis-reported. | **Fixed.** Matches on the legacy payee text and reports what the legacy app showed ("Nicht zugeordnet" included). |
| 9 | low | Untyped errors (`assignments: []`, NaN amounts, invalid legacy colour, zero iterations, UI-state I/O). | **Fixed.** All surface as `StorageError` (or `{}` for UI state); amounts must be finite whole cents; an invalid legacy colour gets a free one. |
| 10 | low | `set_password("")` silently disabled encryption. | **Fixed.** `enable_encryption` (empty password → `ValueError`) and `disable_encryption`. |
| 11 | low | `repr` of `Cipher` showed the key, of `LegacyData` all legacy data. | **Fixed.** `field(repr=False)`; tests check it. |
| 12 | low | Legacy and codec field names as inline strings. | **Fixed.** `L_*` and `KEY_*` constants. |
| 13 | – | API: migration overwrites existing data; repeat import parsed before hashing; design names outdated. | **Fixed/documented.** Migration offered only without data (`has_data`, `Workspace.is_empty`); hash checked first; design updated. |

## Second round (data loss and data leaks)

Focused re-review of the revised storage, document and migration code. 10 findings
(1 high, 3 medium, 5 low, nits).

After revision: 423 tests green, ruff/format/mypy clean. Real-data dry run (scratch
directory, legacy files verified unchanged by hash): 16 categories, 115 keywords,
51 assignments, 329 bookings, 0 dropped, 1 changed; **0 bookings without account** (270
before); after enabling encryption the directory holds `library.json` and `library.json.bak`,
both encrypted, no plaintext payee in any file; encrypted round trip exact; importing five
statement PDFs added 54, enriched 65 migrated bookings, all 51 decisions still apply.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | After recovering from the backup, the next save overwrote the newer (damaged) data file – the old state became permanent; a newer document version counted as damage. | **Fixed.** The damaged file is moved to `library.json.damaged-<time>` before the backup is used (load stops if the move fails); `UnsupportedVersionError` for newer versions is never recovered. |
| 2 | med | A locked `.bak` survived `enable_encryption` in plaintext (`unlink` failed). | **Fixed.** The switch overwrites the backup with the new form first; if that fails, nothing changes and `StorageError` is raised. |
| 3 | med | The cipher was set before the rewrite; a failed write left the session "encrypted" with a plaintext file. | **Fixed.** The cipher is committed only after both writes; tests for a failing backup and a failing data write. |
| 4 | med | A damaged encryption header (other salt) blocked recovery; an interrupted disable asked for a password. | **Fixed.** A copy under a different key counts as damaged; `needs_password` follows the data file; wrong-password wins over a damaged backup in `unlock`. |
| 5 | low | An unreadable `.bak` blocked load and save; the backup copy could be half written. | **Fixed.** Backup via `.bak.tmp` + rename, best effort with a log warning; unreadable backup counts as missing. |
| 6 | low | `InstanceLock` raised a raw `PermissionError`; the handle leaked if unlocking raised. | **Fixed.** Open failure → `StorageError`; `release` closes in `finally`; one platform branch defines `_lock`/`_unlock`. |
| 7 | low/med | 270 of 329 migrated bookings had no account, so they matched bookings of any account during de-duplication; CSV imports had none either. | **Fixed.** Migration takes the statement's account; CSV reads the IBAN above the header. CSV files without IBAN remain account-less (documented). |
| 8 | low | A decision without booking kept the glued payee `/Dauerauftrag X`. | **Fixed.** `_unglued` drops the second half of a compound booking type. |
| 9 | low | The unencrypted UI state could hold an account number (legacy filters did). | **Fixed.** `UI_STATE_KEYS` whitelist: unknown keys raise on save and are dropped on load. |
| 10 | – | A stale `*.tmp` may survive a crash. | **Accepted.** It is overwritten by the next write of the same file; the switch rewrites both temporary files. |
| 11 | nit | `recovered_from_backup` unannotated; unnamed `" "` in migration. | **Fixed.** Class-level annotations; `SPACE` constant. |

## Third round (verification of the second-round fixes)

The reviewer confirmed second-round items 1, 2, 4, 6, 7, 8, 10 (enable) and 11 against the
code and with reproductions. It found six more items, including two data-loss paths it
reproduced. After revision: 433 tests green, ruff/format/mypy clean. All of the reviewer's
reproduction scenarios now end safely, either with a typed error or with no plaintext left.
The real-data dry run gives results identical to round two.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | med/high | Data file missing (after a recovery) and the backup locked by a scanner: `load` returned an **empty library**; two saves later the data was gone. | **Fixed.** Without a data file the backup is read strictly; unreadable → `StorageError`, never defaults. |
| 2 | med | `save`/encryption switch did not require a successful `load`; saving after `UnsupportedVersionError` or a cancelled password prompt destroyed the newer file. | **Fixed.** The session must own the data: set by a successful load (or no data) and by its own writes; **revoked at the start of every load**, so an earlier save does not count. |
| 3 | low/med | Failed or interrupted disable left a plaintext backup/temp file while the session stayed encrypted; the design mislabelled the mixed states. | **Fixed.** A failed switch makes the backup follow the data file and deletes temps; `load` repairs mixed states after a crash; design corrected; tests for both directions. |
| 4 | low | Raw `ValueError`/`RecursionError`/`OverflowError` from huge numbers, deep nesting, an infinite page number or a huge iteration count. | **Fixed.** All become `StorageError` (so recovery is tried); `MAX_ITERATIONS` bounds key derivation; same for the legacy JSON reader. |
| 5 | low | The UI-state whitelist checked top-level keys only; nested values could hold an account. | **Fixed.** Values must be scalars or number lists; rule for string values documented. |
| 6 | nit | `recovered_from_backup` stayed set when setting aside failed; a second `load` after a recovery reports "recovered" again; `IAAHENC1` as `library.json` is rejected; test constants not `Final`; magic string compared in a test. | **Fixed:** flags are set only after the move; constants `Final`; boolean test parameter. **Accepted:** the second load *does* read the backup, and the data file is gone by then, so "recovered" is true. The app never writes `IAAHENC1` to `library.json`; rejecting such a file with `StorageError` is safe. |
