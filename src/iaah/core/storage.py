"""Where and how personal data is stored.

Everything lives in the user data directory, never in the working tree: ``IAAH_HOME`` if set,
else ``platformdirs.user_data_dir("I-Aah")`` (Windows: ``%LOCALAPPDATA%\\I-Aah``).

* One data file (``library.json``) holds catalog and library (see ``document.py``), optionally
  encrypted (``crypto.py``). UI state is a separate, never encrypted file restricted to
  layout keys (``UI_STATE_KEYS``).
* Writes go to a temporary file first; the current file is *copied* to ``*.bak`` (best
  effort) and then replaced in one atomic step – the data file never disappears.
* A damaged data file is moved aside to ``library.json.damaged-<time>`` – a name no save ever
  writes to – before the backup is loaded, so recovering can never destroy newer data. A file
  from a newer program version is not damage and is never "recovered".
* Switching encryption on or off rewrites the backup in the new form first, then the data
  file; the session switches only when both writes succeeded. Loading makes a backup left in
  the other form by an interrupted switch follow the data file again and deletes leftover
  temporary files.
* A session may only save data it loaded (or a directory without data), so a file it could
  not read is never overwritten.
* ``InstanceLock`` keeps a second running instance from overwriting the first one's data.
"""

import json
import logging
import os
import shutil
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Final, Self

import platformdirs

from iaah.core.categories import CategoryCatalog
from iaah.core.category_io import default_catalog
from iaah.core.crypto import Cipher, decrypt, is_encrypted, unlock
from iaah.core.document import document_from_json, document_to_json
from iaah.core.errors import (
    DataUnreadableError,
    PasswordRequiredError,
    StorageError,
    UnsupportedVersionError,
    WrongPasswordError,
)
from iaah.core.library import Library

# mypy only narrows literal sys.platform checks, hence the literals below.
if sys.platform == "win32":  # noqa: PLR2004
    import msvcrt
else:
    import fcntl

APP_NAME: Final = "I-Aah"
HOME_ENV: Final = "IAAH_HOME"
DATA_FILE: Final = "library.json"
UI_STATE_FILE: Final = "ui_state.json"
LOCK_FILE: Final = "iaah.lock"
BACKUP_SUFFIX: Final = ".bak"
TEMP_SUFFIX: Final = ".tmp"
DAMAGED_INFIX: Final = ".damaged-"
DAMAGED_STAMP: Final = "%Y%m%d-%H%M%S-%f"
GLOB_ANY: Final = "*"
ENCODING: Final = "utf-8"
LOCKED_BYTES: Final = 1
RENAME_ATTEMPTS: Final = 6
RENAME_PAUSE: Final = 0.05  # seconds; six attempts outlast a reader's open file handle
# The UI state is never encrypted, so it may only hold layout and look – nothing naming an
# account, payee or category (the legacy app stored its account filter there). Extend
# deliberately.
UI_STATE_KEYS: Final = frozenset(
    {"geometry", "theme", "tab", "panes", "columns", "period", "chart"}
)

logger: Final = logging.getLogger(__name__)


class AlreadyRunningError(StorageError):
    """Another instance holds the data directory."""


@dataclass(frozen=True, slots=True)
class DataPaths:
    """The files of one data directory."""

    root: Path

    @classmethod
    def default(cls) -> Self:
        """``IAAH_HOME`` or the platform's user data directory."""
        override = os.environ.get(HOME_ENV)
        root = Path(override) if override else Path(platformdirs.user_data_dir(APP_NAME, False))
        return cls(root)

    @property
    def data(self) -> Path:
        """Catalog and library."""
        return self.root / DATA_FILE

    @property
    def ui_state(self) -> Path:
        """Window size, theme, open tab."""
        return self.root / UI_STATE_FILE

    @property
    def lock(self) -> Path:
        """Held while an instance runs."""
        return self.root / LOCK_FILE


# -- files ------------------------------------------------------------------------------------


def backup_of(path: Path) -> Path:
    """The ``*.bak`` next to ``path``."""
    return path.with_name(path.name + BACKUP_SUFFIX)


def damaged_copy_of(path: Path, moment: datetime) -> Path:
    """Where a damaged ``path`` is set aside – a name no save ever writes to."""
    return path.with_name(f"{path.name}{DAMAGED_INFIX}{moment.strftime(DAMAGED_STAMP)}")


def atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` without ever leaving ``path`` missing or half written.

    The new content is flushed to a temporary file; the current file is copied to ``*.bak``
    (best effort: a locked or unreadable backup must not block saving); then one atomic
    rename puts the new file in place.
    """
    temp = _write_temp(path, data)
    _keep_backup(path)
    _rename(temp, path)


def replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` in one atomic step, without touching its backup."""
    _rename(_write_temp(path, data), path)


def _rename(source: Path, target: Path) -> None:
    """Atomically replace ``target``. On Windows a reader that has the target open for a
    moment (``iaah-cli --library``, a virus scanner) makes the rename fail with
    ``PermissionError``, so it is retried briefly before giving up."""
    for _ in range(RENAME_ATTEMPTS - 1):
        try:
            source.replace(target)
            return
        except PermissionError:
            time.sleep(RENAME_PAUSE)
    source.replace(target)


def _temp_of(path: Path) -> Path:
    return path.with_name(path.name + TEMP_SUFFIX)


def _write_temp(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp_of(path)
    with temp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return temp


def _keep_backup(path: Path) -> None:
    """Copy ``path`` to its backup via a temporary file, so the backup is never half written."""
    if not path.exists():
        return
    backup = backup_of(path)
    temp = _temp_of(backup)
    try:
        shutil.copyfile(path, temp)
        _rename(temp, backup)
    except OSError:
        logger.warning("could not update the backup %s", backup)


def _remove_temps(path: Path) -> None:
    """Delete leftover temporary files of ``path`` and its backup (a crash or failed write may
    leave them, possibly unencrypted). Never needed: a rename either happened or not."""
    for temp in (_temp_of(path), _temp_of(backup_of(path))):
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not delete the temporary file %s", temp)


def _read(path: Path) -> bytes | None:
    """The file's bytes, ``None`` if it does not exist; ``DataUnreadableError`` if it exists
    but cannot be read (locked, no permission, a folder) – that is not damage."""
    try:
        return path.read_bytes() if path.exists() else None
    except OSError as error:
        raise DataUnreadableError(f"cannot read {path}") from error


def _read_optional(path: Path) -> bytes | None:
    """Like ``_read``, but an unreadable file counts as missing (for backups)."""
    try:
        return _read(path)
    except StorageError:
        logger.warning("ignoring the unreadable file %s", path)
        return None


def _encode(cipher: Cipher | None, catalog: CategoryCatalog, library: Library) -> bytes:
    data = document_to_json(catalog, library).encode(ENCODING)
    return cipher.encrypt(data) if cipher is not None else data


# -- single instance ------------------------------------------------------------------------

if sys.platform == "win32":  # noqa: PLR2004

    def _lock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, LOCKED_BYTES)

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, LOCKED_BYTES)

else:

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class InstanceLock:
    """An OS-level lock on a file in the data directory; released automatically when the
    process ends, also after a crash. Use as a context manager or acquire/release."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> None:
        """Take the lock; ``AlreadyRunningError`` if another process holds it,
        ``StorageError`` if the lock file cannot be opened at all."""
        if self._handle is not None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open("a+b")
        except OSError as error:
            raise StorageError(f"cannot open {self._path}") from error
        try:
            _lock(handle)
        except OSError as error:
            handle.close()
            raise AlreadyRunningError(f"{self._path} is locked by another instance") from error
        self._handle = handle

    def release(self) -> None:
        """Give the lock back (no-op if not held). Closing the file releases it even when
        unlocking fails."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        except OSError:
            logger.warning("could not unlock %s; closing it releases the lock", self._path)
        finally:
            handle.close()

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.release()


# -- the store ------------------------------------------------------------------------------------


def _is_layout_value(value: object) -> bool:
    """A scalar, or a list of numbers (pane positions, column widths) – no nested objects that
    could carry personal data past the key whitelist."""
    if isinstance(value, list):
        return all(isinstance(item, int | float) for item in value)
    return value is None or isinstance(value, str | int | float)


class DataStore:
    """Loads and saves catalog, library and UI state of one data directory.

    The caller holds the ``InstanceLock``. Saving requires that this session owns the data –
    it loaded it successfully, or there was none – so a file that could not be loaded (newer
    version, no password given, damaged without backup) is never overwritten.

    A ``read_only`` store (``iaah-cli --library``) never touches the directory: it needs no
    lock (every write is an atomic rename, so it reads either version), loads a damaged data
    file's backup without moving anything, tidies nothing and refuses to save.
    """

    paths: DataPaths
    recovered_from_backup: bool  # the last load() used the backup
    damaged_copy: Path | None  # where the last load() set a damaged data file aside

    def __init__(
        self, paths: DataPaths, cipher: Cipher | None = None, *, read_only: bool = False
    ) -> None:
        self.paths = paths
        self._cipher = cipher
        self._read_only = read_only
        self._owns_data = False
        self.recovered_from_backup = False
        self.damaged_copy = None

    @property
    def encrypted(self) -> bool:
        """Whether saving encrypts."""
        return self._cipher is not None

    def has_data(self) -> bool:
        """Whether a data file (or its backup) exists – false on first start."""
        return self.paths.data.exists() or backup_of(self.paths.data).exists()

    def needs_password(self) -> bool:
        """Whether ``unlock`` must come first: the data file – or, without one, its backup – is
        encrypted. ``load`` still raises ``PasswordRequiredError`` in the rare case that a
        damaged unencrypted data file leaves only an encrypted backup."""
        if self._cipher is not None:
            return False
        main, backup = self._candidates()
        primary = main if main is not None else backup
        return primary is not None and is_encrypted(primary)

    def unlock(self, password: str) -> None:
        """Derive the key from ``password`` with the data file, or with the backup if the data
        file cannot be decrypted. ``WrongPasswordError`` if the password fits neither."""
        failures: list[StorageError] = []
        for blob in self._candidates():
            if blob is None or not is_encrypted(blob):
                continue
            try:
                _, self._cipher = unlock(blob, password)
                return
            except StorageError as failure:
                failures.append(failure)
        wrong = [failure for failure in failures if isinstance(failure, WrongPasswordError)]
        raise (wrong or failures or [PasswordRequiredError("nothing to unlock")])[0]

    def load(self) -> tuple[CategoryCatalog, Library]:
        """Catalog and library: defaults on first start, the backup if the data file is damaged.

        The damaged file is moved to ``damaged_copy`` first, so no later save can overwrite
        it. A file that needs the password or comes from a newer program version is not
        damage: those errors propagate. Leftovers of an interrupted write are tidied up.
        """
        self.recovered_from_backup = False
        self.damaged_copy = None
        self._owns_data = False  # until this load succeeds: what is on disk may be newer
        main = _read(self.paths.data)
        result = self._load_backup_only() if main is None else self._load_main(main)
        self._owns_data = True
        if not self._read_only:
            _remove_temps(self.paths.data)
        return result

    def save(self, catalog: CategoryCatalog, library: Library) -> None:
        """Write catalog and library in one atomic step; the previous version becomes the
        backup."""
        self._require_ownership()
        try:
            atomic_write(self.paths.data, _encode(self._cipher, catalog, library))
        except OSError as error:
            raise StorageError(f"cannot write {self.paths.data}") from error
        self._owns_data = True

    def enable_encryption(self, password: str, catalog: CategoryCatalog, library: Library) -> None:
        """Encrypt from now on (also to change the password); see ``_switch``."""
        if not password:
            raise ValueError("password must not be empty")
        self._switch(Cipher.create(password), catalog, library)

    def disable_encryption(self, catalog: CategoryCatalog, library: Library) -> None:
        """Store unencrypted from now on; see ``_switch``."""
        self._switch(None, catalog, library)

    def damaged_copies(self) -> list[Path]:
        """Damaged data files set aside by earlier loads. They may hold unencrypted data, so
        the GUI lists them when encryption is switched on."""
        return sorted(self.paths.root.glob(self.paths.data.name + DAMAGED_INFIX + GLOB_ANY))

    def start_over(self) -> list[Path]:
        """After a load that failed with damage (not a newer version, not a missing password):
        move data file and backup aside – kept as damaged copies, never deleted – so the app can
        start empty. Returns where they went; afterwards this session owns the (empty) data."""
        self._require_writable()
        damaged = damaged_copy_of(self.paths.data, datetime.now())
        moved: list[Path] = []
        for source, target in ((self.paths.data, damaged), (backup_of(self.paths.data),
                                                            backup_of(damaged))):  # fmt: skip
            if not source.exists():
                continue
            try:
                source.replace(target)
            except OSError as error:
                raise StorageError(f"cannot move {source} aside") from error
            moved.append(target)
        self._owns_data = True
        return moved

    def load_ui_state(self) -> dict[str, Any]:
        """Window and view settings; empty if missing or unreadable (never essential). Entries
        outside ``UI_STATE_KEYS`` or with nested values are dropped."""
        try:
            blob = _read(self.paths.ui_state)
            state = json.loads(blob.decode(ENCODING)) if blob else {}
        except (StorageError, UnicodeDecodeError, ValueError, RecursionError):
            return {}
        if not isinstance(state, dict):
            return {}
        return {
            key: value
            for key, value in state.items()
            if key in UI_STATE_KEYS and _is_layout_value(value)
        }

    def save_ui_state(self, state: Mapping[str, Any]) -> None:
        """Store window and view settings. Never encrypted, hence restricted to
        ``UI_STATE_KEYS`` with scalar or number-list values (``ValueError`` otherwise); string
        values must be view identifiers, never account, payee or category names."""
        self._require_writable()
        rejected = sorted(
            key for key, value in state.items()
            if key not in UI_STATE_KEYS or not _is_layout_value(value)
        )  # fmt: skip
        if rejected:
            raise ValueError(f"not allowed in the unencrypted UI state: {rejected}")
        try:
            atomic_write(self.paths.ui_state, json.dumps(state, indent=1).encode(ENCODING))
        except OSError as error:
            raise StorageError(f"cannot write {self.paths.ui_state}") from error

    def _require_ownership(self) -> None:
        self._require_writable()
        if not self._owns_data and self.has_data():
            raise StorageError("refusing to overwrite data this session has not loaded")

    def _require_writable(self) -> None:
        if self._read_only:
            raise StorageError("this data store is read-only")

    def _switch(self, cipher: Cipher | None, catalog: CategoryCatalog, library: Library) -> None:
        """Rewrite backup and data file in the new form – the backup first, so after success no
        copy in the old form is left. If a write fails, ``StorageError`` is raised, the data
        file still holds the old form, the session keeps using it, and the backup is made to
        follow the data file again (best effort; ``load`` repeats that after a crash)."""
        self._require_ownership()
        blob = _encode(cipher, catalog, library)
        try:
            replace_atomically(backup_of(self.paths.data), blob)
            replace_atomically(self.paths.data, blob)
        except OSError as error:
            _keep_backup(self.paths.data)
            _remove_temps(self.paths.data)
            raise StorageError(f"cannot rewrite {self.paths.data}") from error
        self._cipher = cipher
        self._owns_data = True

    def _candidates(self) -> tuple[bytes | None, bytes | None]:
        """Data file and backup; an unreadable backup counts as missing."""
        return _read(self.paths.data), _read_optional(backup_of(self.paths.data))

    def _load_backup_only(self) -> tuple[CategoryCatalog, Library]:
        """No data file: a first start – or a crash or recovery left only the backup. Here an
        unreadable backup raises: it must never look like a first start."""
        backup = _read(backup_of(self.paths.data))
        if backup is None:
            return default_catalog(), Library()
        result = self._decode(backup)
        self.recovered_from_backup = True
        return result

    def _load_main(self, main: bytes) -> tuple[CategoryCatalog, Library]:
        backup = _read_optional(backup_of(self.paths.data))
        try:
            result = self._decode(main)
        except (PasswordRequiredError, UnsupportedVersionError):
            raise
        except StorageError:
            if backup is None:
                raise
            return self._recover(backup)
        mixed = backup is not None and is_encrypted(backup) != is_encrypted(main)
        if mixed and not self._read_only:
            _keep_backup(self.paths.data)  # an interrupted switch: the backup follows the file
        return result

    def _recover(self, backup: bytes) -> tuple[CategoryCatalog, Library]:
        result = self._decode(backup)
        if not self._read_only:
            self.damaged_copy = self._set_aside()
        self.recovered_from_backup = True
        return result

    def _set_aside(self) -> Path:
        """Move the damaged data file out of the way; refusing to go on if that fails, since
        the next save would otherwise replace it."""
        target = damaged_copy_of(self.paths.data, datetime.now())
        try:
            self.paths.data.replace(target)
        except OSError as error:
            raise StorageError(f"cannot move the damaged {self.paths.data} aside") from error
        logger.warning("damaged data file moved to %s", target)
        return target

    def _decode(self, blob: bytes) -> tuple[CategoryCatalog, Library]:
        if is_encrypted(blob):
            blob = self._decrypt(blob)
        try:
            text = blob.decode(ENCODING)
        except UnicodeDecodeError as error:
            raise StorageError(f"{self.paths.data.name} is not UTF-8") from error
        return document_from_json(text)

    def _decrypt(self, blob: bytes) -> bytes:
        if self._cipher is None:
            raise PasswordRequiredError(f"{self.paths.data.name} is encrypted")
        try:
            return decrypt(blob, self._cipher)
        except PasswordRequiredError as error:
            # Unlocked with the other copy's key: this copy is damaged or stale.
            raise StorageError("copy encrypted with a different key") from error
