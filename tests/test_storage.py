"""Data directory: atomic writes, backups, recovery, encryption switches, instance lock."""

import base64
import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import IO, Final

import pytest

from iaah.core import storage
from iaah.core.category_io import default_catalog
from iaah.core.crypto import MAGIC, is_encrypted
from iaah.core.document import document_to_json
from iaah.core.errors import (
    PasswordRequiredError,
    StorageError,
    UnsupportedVersionError,
    WrongPasswordError,
)
from iaah.core.library import Library
from iaah.core.models import Transaction
from iaah.core.storage import (
    AlreadyRunningError,
    DataPaths,
    DataStore,
    InstanceLock,
    atomic_write,
    backup_of,
)

FAST_ITERATIONS: Final = 1_000
SECRET_PAYEE: Final = "Geheimer Empfänger"


@pytest.fixture(autouse=True)
def fast_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("iaah.core.crypto.ITERATIONS", FAST_ITERATIONS)


def _library(payee: str = SECRET_PAYEE) -> Library:
    txn = Transaction(date(2026, 7, 1), "", payee, "", Decimal("-1.00"), "x.pdf")
    return Library(transactions=[txn])


def _payee(store: DataStore) -> str:
    return store.load()[1].transactions[0].payee


def _two_versions(paths: DataPaths, password: str | None = None) -> DataStore:
    """A store whose backup holds payee "alt" and whose data file holds "neu"."""
    store = DataStore(paths)
    if password is None:
        store.save(default_catalog(), _library("alt"))
    else:
        store.enable_encryption(password, default_catalog(), _library("alt"))
    store.save(default_catalog(), _library("neu"))
    return store


# -- files ------------------------------------------------------------------------------------


def test_atomic_write_copies_the_previous_version(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "f.json"
    atomic_write(path, b"one")
    atomic_write(path, b"two")
    assert path.read_bytes() == b"two"
    assert backup_of(path).read_bytes() == b"one"
    assert sorted(p.name for p in path.parent.iterdir()) == ["f.json", "f.json.bak"]


def test_a_blocked_backup_neither_blocks_saving_nor_loading(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.save(default_catalog(), _library("alt"))
    backup_of(paths.data).mkdir()  # can be neither replaced nor read
    store.save(default_catalog(), _library("neu"))
    assert _payee(store) == "neu"
    assert not store.needs_password()


def test_an_unreadable_backup_without_data_file_is_no_first_start(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    backup_of(paths.data).mkdir()  # e.g. locked by a virus scanner
    store = DataStore(paths)
    with pytest.raises(StorageError):
        store.load()
    with pytest.raises(StorageError, match="not loaded"):
        store.save(default_catalog(), Library())


def test_first_start_gives_defaults(tmp_path: Path) -> None:
    store = DataStore(DataPaths(tmp_path))
    catalog, library = store.load()
    assert list(catalog) == list(default_catalog())
    assert library.transactions == []
    assert not store.has_data()
    assert not store.needs_password()
    assert store.load_ui_state() == {}


def test_save_and_load(tmp_path: Path) -> None:
    store = DataStore(DataPaths(tmp_path))
    store.save(default_catalog(), _library())
    store.save_ui_state({"theme": "dark"})
    _, library = DataStore(DataPaths(tmp_path)).load()
    assert library.transactions == _library().transactions
    assert store.load_ui_state() == {"theme": "dark"}
    assert store.has_data()


# -- recovery ---------------------------------------------------------------------------------


def test_damaged_file_is_set_aside_and_recovered_from_backup(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    store = _two_versions(paths)
    paths.data.write_bytes(b"{ damaged")
    assert _payee(store) == "alt"
    assert store.recovered_from_backup
    assert store.damaged_copy is not None
    assert store.damaged_copy.read_bytes() == b"{ damaged"
    assert store.damaged_copies() == [store.damaged_copy]

    store.save(default_catalog(), _library("weiter"))  # never touches the damaged copy
    assert store.damaged_copy.read_bytes() == b"{ damaged"
    assert _payee(DataStore(paths)) == "weiter"
    assert backup_of(paths.data).exists()


def test_damaged_file_without_backup_raises_and_stays(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    paths.data.write_bytes(b"{ damaged")
    with pytest.raises(StorageError):
        DataStore(paths).load()
    assert paths.data.read_bytes() == b"{ damaged"


def test_a_newer_version_is_never_recovered(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    _two_versions(paths)
    newer = json.loads(paths.data.read_text(encoding="utf-8")) | {"version": 99}
    paths.data.write_text(json.dumps(newer), encoding="utf-8")
    store = DataStore(paths)
    with pytest.raises(UnsupportedVersionError):
        store.load()
    assert store.damaged_copies() == []
    with pytest.raises(StorageError, match="not loaded"):  # nor overwritten by a save
        store.save(default_catalog(), _library("alt"))
    with pytest.raises(StorageError, match="not loaded"):
        store.enable_encryption("geheim", default_catalog(), _library("alt"))
    assert json.loads(paths.data.read_text(encoding="utf-8"))["version"] == 99


def test_a_failed_load_revokes_an_earlier_save(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.save(default_catalog(), _library("alt"))  # this session wrote the file ...
    newer = json.loads(paths.data.read_text(encoding="utf-8")) | {"version": 99}
    paths.data.write_text(json.dumps(newer), encoding="utf-8")  # ... a newer version replaced it
    with pytest.raises(UnsupportedVersionError):
        store.load()
    with pytest.raises(StorageError, match="not loaded"):
        store.save(default_catalog(), _library("alt"))


def test_no_save_without_the_password(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).enable_encryption("geheim", default_catalog(), _library())
    store = DataStore(paths)
    with pytest.raises(PasswordRequiredError):
        store.load()  # the user cancels the password prompt
    with pytest.raises(StorageError, match="not loaded"):
        store.save(default_catalog(), Library())
    assert is_encrypted(paths.data.read_bytes())


def test_recovery_refuses_when_the_damaged_file_cannot_be_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    store = _two_versions(paths)
    paths.data.write_bytes(b"{ damaged")
    monkeypatch.setattr(storage, "damaged_copy_of", lambda *_: tmp_path / "missing" / "x")
    with pytest.raises(StorageError, match="aside"):
        store.load()
    assert paths.data.read_bytes() == b"{ damaged"


def test_damaged_encrypted_file_is_recovered_from_backup(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    _two_versions(paths, "geheim")
    paths.data.write_bytes(paths.data.read_bytes()[:-20])  # truncated token
    fresh = DataStore(paths)
    fresh.unlock("geheim")
    assert _payee(fresh) == "alt"
    assert fresh.recovered_from_backup


def test_damaged_salt_is_recovered_from_backup(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    _two_versions(paths, "geheim")
    iterations, _, token = paths.data.read_bytes()[len(MAGIC) :].split(b"\n", 2)
    other_salt = base64.b64encode(bytes(16))
    paths.data.write_bytes(MAGIC + iterations + b"\n" + other_salt + b"\n" + token)
    fresh = DataStore(paths)
    fresh.unlock("geheim")  # fits the backup only
    assert _payee(fresh) == "alt"
    assert fresh.recovered_from_backup


def test_damaged_plain_file_with_encrypted_backup_asks_for_the_password(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    _two_versions(paths, "geheim")
    paths.data.write_bytes(b"{ damaged")
    fresh = DataStore(paths)
    with pytest.raises(PasswordRequiredError):
        fresh.load()
    assert paths.data.exists()  # nothing moved before the backup could be read
    fresh.unlock("geheim")
    assert _payee(fresh) == "alt"


def test_read_only_store_touches_nothing(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    _two_versions(paths)
    paths.data.write_bytes(b"{ damaged")
    (tmp_path / "library.json.tmp").write_bytes(b"leftover")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    store = DataStore(paths, read_only=True)
    assert _payee(store) == "alt"
    assert store.recovered_from_backup
    assert store.damaged_copy is None
    writes: list[Callable[[], None]] = [
        lambda: store.save(default_catalog(), _library()),
        lambda: store.enable_encryption("geheim", default_catalog(), _library()),
        lambda: store.save_ui_state({"theme": "dark"}),
    ]
    for write in writes:
        with pytest.raises(StorageError, match="read-only"):
            write()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_read_only_store_creates_no_directory(tmp_path: Path) -> None:
    store = DataStore(DataPaths(tmp_path / "nie-angelegt"), read_only=True)
    assert store.load()[1].transactions == []
    assert not (tmp_path / "nie-angelegt").exists()


# -- encryption -------------------------------------------------------------------------------


def _no_plaintext(directory: Path) -> bool:
    secret = SECRET_PAYEE.encode()
    return all(secret not in path.read_bytes() for path in directory.iterdir())


def test_enabling_encryption_leaves_no_plaintext_copy(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.save(default_catalog(), _library())
    store.save(default_catalog(), _library())  # creates a plaintext backup
    store.enable_encryption("geheim", default_catalog(), _library())
    assert is_encrypted(paths.data.read_bytes())
    assert is_encrypted(backup_of(paths.data).read_bytes())
    assert _no_plaintext(tmp_path)


def test_password_round_trip(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).enable_encryption("geheim", default_catalog(), _library())
    fresh = DataStore(paths)
    assert fresh.needs_password()
    with pytest.raises(PasswordRequiredError):
        fresh.load()
    with pytest.raises(WrongPasswordError):
        fresh.unlock("falsch")
    fresh.unlock("geheim")
    assert fresh.load()[1].transactions == _library().transactions

    fresh.disable_encryption(default_catalog(), _library())
    assert not fresh.encrypted
    assert not is_encrypted(paths.data.read_bytes())
    assert not is_encrypted(backup_of(paths.data).read_bytes())


def _fail_writes_to(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    original = storage.replace_atomically

    def flaky(path: Path, data: bytes) -> None:
        if path == target:
            raise PermissionError(path)
        original(path, data)

    monkeypatch.setattr(storage, "replace_atomically", flaky)


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == storage.TEMP_SUFFIX)


@pytest.mark.parametrize("fail_backup", [True, False])
def test_a_failed_enable_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_backup: bool
) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.save(default_catalog(), _library())
    _fail_writes_to(monkeypatch, backup_of(paths.data) if fail_backup else paths.data)
    with pytest.raises(StorageError):
        store.enable_encryption("geheim", default_catalog(), _library())
    assert not store.encrypted
    assert not is_encrypted(paths.data.read_bytes())
    assert not is_encrypted(backup_of(paths.data).read_bytes())  # follows the data file again
    assert not DataStore(paths).needs_password()


def test_a_failed_disable_leaves_no_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.enable_encryption("geheim", default_catalog(), _library())
    _fail_writes_to(monkeypatch, paths.data)
    with pytest.raises(StorageError):
        store.disable_encryption(default_catalog(), _library())
    assert store.encrypted
    assert _no_plaintext(tmp_path)
    assert _leftovers(tmp_path) == []


def test_interrupted_enable_is_tidied_on_load(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).enable_encryption("geheim", default_catalog(), _library("alt"))
    plain = document_to_json(default_catalog(), _library("neu")).encode()
    paths.data.write_bytes(plain)  # crash after the backup was written: data file still plain
    fresh = DataStore(paths)
    assert not fresh.needs_password()
    assert _payee(fresh) == "neu"
    assert backup_of(paths.data).read_bytes() == plain


def test_interrupted_disable_is_tidied_on_load(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).enable_encryption("geheim", default_catalog(), _library())
    plain = document_to_json(default_catalog(), _library()).encode()
    backup_of(paths.data).write_bytes(plain)  # crash after the backup was written
    (tmp_path / "library.json.tmp").write_bytes(plain)  # ... while writing the data file
    fresh = DataStore(paths)
    assert fresh.needs_password()
    fresh.unlock("geheim")
    fresh.load()
    assert _no_plaintext(tmp_path)
    assert _leftovers(tmp_path) == []


def test_wrong_password_wins_over_a_damaged_backup(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).enable_encryption("geheim", default_catalog(), _library())
    backup_of(paths.data).write_bytes(MAGIC + b"kaputt")
    with pytest.raises(WrongPasswordError):
        DataStore(paths).unlock("falsch")


def test_empty_password_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="password"):
        DataStore(DataPaths(tmp_path)).enable_encryption("", default_catalog(), Library())


# -- UI state ---------------------------------------------------------------------------------


def test_damaged_ui_state_is_ignored(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    paths.ui_state.write_bytes(b"\xff not json")
    assert DataStore(paths).load_ui_state() == {}


def test_ui_state_holds_only_layout_keys(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    with pytest.raises(ValueError, match="konto"):
        store.save_ui_state({"theme": "dark", "konto": "123"})
    with pytest.raises(ValueError, match="chart"):
        store.save_ui_state({"chart": {"konto": "123"}})
    store.save_ui_state({"panes": [300, 0.5], "tab": "Auswertung"})
    legacy_like = {"theme": "dark", "filters": {"konto": "123"}, "chart": {"konto": "123"}}
    paths.ui_state.write_text(json.dumps(legacy_like), encoding="utf-8")
    assert store.load_ui_state() == {"theme": "dark"}


# -- instance lock ----------------------------------------------------------------------------


def test_instance_lock(tmp_path: Path) -> None:
    path = DataPaths(tmp_path).lock
    with InstanceLock(path), pytest.raises(AlreadyRunningError):
        InstanceLock(path).acquire()
    with InstanceLock(path):  # released after the first one ended
        pass


def test_unopenable_lock_file_is_a_storage_error(tmp_path: Path) -> None:
    (tmp_path / "datei").write_bytes(b"")
    with pytest.raises(StorageError) as caught:
        InstanceLock(tmp_path / "datei" / "iaah.lock").acquire()
    assert not isinstance(caught.value, AlreadyRunningError)


def test_release_closes_the_file_even_if_unlocking_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[IO[bytes]] = []

    def failing_unlock(handle: IO[bytes]) -> None:
        seen.append(handle)
        raise OSError("unlock failed")

    lock = InstanceLock(DataPaths(tmp_path).lock)
    lock.acquire()
    monkeypatch.setattr(storage, "_unlock", failing_unlock)
    lock.release()
    assert seen[0].closed


def test_data_paths_honour_iaah_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAAH_HOME", str(tmp_path))
    assert DataPaths.default().data == tmp_path / "library.json"
    monkeypatch.delenv("IAAH_HOME")
    assert DataPaths.default().root.name == "I-Aah"
