"""Start-up and legacy migration, with every dialog replaced by scripted answers (no display)."""

import json
import tkinter as tk
from collections.abc import Iterable
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Final, cast

import pytest

from iaah.core.category_io import default_catalog
from iaah.core.library import Library
from iaah.core.storage import DataPaths, DataStore
from iaah.core.workspace import Workspace
from iaah.gui import startup
from iaah.gui.session import Session

ROOT: Final = cast(tk.Misc, object())  # never touched: every dialog is replaced
FAST_ITERATIONS: Final = 1_000
LEGACY_SETTINGS: Final[dict[str, Any]] = {
    "version": 2,
    "categories": [{"name": "Lebensmittel", "color": "#123456"}],
    "rules": [{"keyword": "REWE", "category": "Lebensmittel"}],
    "budgets": {},
    "overrides": {},
}


@pytest.fixture(autouse=True)
def fast_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("iaah.core.crypto.ITERATIONS", FAST_ITERATIONS)


class Script:
    """Scripted dialog answers, and every message the user would have seen."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        passwords: Iterable[str] = (),
        answers: Iterable[bool] = (),
    ) -> None:
        self.passwords = list(passwords)
        self.answers = list(answers)
        self.messages: list[str] = []
        script = self

        class ScriptedPasswordDialog:
            def __init__(self, *_args: object) -> None:
                pass

            def show(self) -> str | None:
                return script.passwords.pop(0) if script.passwords else None

        monkeypatch.setattr(startup, "PasswordDialog", ScriptedPasswordDialog)
        for name in ("showerror", "showinfo", "showwarning"):
            monkeypatch.setattr(messagebox, name, self._note)
        monkeypatch.setattr(messagebox, "askyesno", self._answer)
        monkeypatch.setattr(startup, "show_text", self._report)

    def _note(self, _title: str, message: str, **_options: object) -> str:
        self.messages.append(message)
        return "ok"

    def _answer(self, _title: str, message: str, **_options: object) -> bool:
        self.messages.append(message)
        return self.answers.pop(0)

    def _report(self, _parent: object, title: str, _text: str) -> None:
        self.messages.append(title)


def _files(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir()) if path.is_file()}


def _encrypted(folder: Path) -> DataStore:
    store = DataStore(DataPaths(folder))
    store.enable_encryption("geheim", default_catalog(), Library())
    return DataStore(DataPaths(folder))


# -- opening the data -------------------------------------------------------------------------


def test_a_wrong_password_and_cancel_quit_without_touching_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _encrypted(tmp_path)
    before = _files(tmp_path)
    script = Script(monkeypatch, passwords=["falsch"])
    assert startup.open_workspace(ROOT, store) is None
    assert script.messages == ["Das Passwort ist falsch."]
    assert _files(tmp_path) == before


def test_the_right_password_opens_the_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _encrypted(tmp_path)
    Script(monkeypatch, passwords=["falsch", "geheim"])
    assert startup.open_workspace(ROOT, store) is not None


def test_newer_or_unreadable_data_quits_with_a_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = DataPaths(tmp_path)
    DataStore(paths).save(default_catalog(), Library())
    newer = json.loads(paths.data.read_text(encoding="utf-8")) | {"version": 99}
    paths.data.write_text(json.dumps(newer), encoding="utf-8")
    script = Script(monkeypatch)
    assert startup.open_workspace(ROOT, DataStore(paths)) is None
    assert "neueren" in script.messages[-1]

    unreadable = DataPaths(tmp_path / "gesperrt")
    unreadable.data.mkdir(parents=True)  # exists, but cannot be read as a file
    assert startup.open_workspace(ROOT, DataStore(unreadable)) is None
    assert "unverändert" in script.messages[-1]
    assert unreadable.data.is_dir()  # nothing set aside


def test_damaged_data_is_set_aside_only_when_the_user_agrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = DataPaths(tmp_path)
    paths.data.write_bytes(b"{ damaged")
    Script(monkeypatch, answers=[False, True])
    assert startup.open_workspace(ROOT, DataStore(paths)) is None
    assert paths.data.read_bytes() == b"{ damaged"

    workspace = startup.open_workspace(ROOT, DataStore(paths))
    assert workspace is not None
    assert workspace.is_empty()
    assert not paths.data.exists()
    assert [copy.read_bytes() for copy in DataStore(paths).damaged_copies()] == [b"{ damaged"]


def test_recovery_from_the_backup_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = DataPaths(tmp_path)
    store = DataStore(paths)
    store.save(default_catalog(), Library())
    store.save(default_catalog(), Library())  # now there is a backup
    paths.data.write_bytes(b"{ damaged")
    script = Script(monkeypatch)
    assert startup.open_workspace(ROOT, DataStore(paths)) is not None
    assert "Sicherungskopie geladen" in script.messages[-1]
    assert "damaged" in script.messages[-1]  # names the set-aside copy


# -- legacy data ------------------------------------------------------------------------------


def _legacy_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "alt"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps(LEGACY_SETTINGS), encoding="utf-8")
    return folder


def test_the_start_offers_legacy_data_only_to_a_pristine_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = _legacy_folder(tmp_path)
    script = Script(monkeypatch, answers=[True])
    session = Session(Workspace(default_catalog(), Library()))
    assert startup.offer_migration(ROOT, session, folder)
    assert session.catalog.get("Lebensmittel").color == "#123456"
    assert "Übernahme der alten Daten" in script.messages  # the report

    own = Session(Workspace(default_catalog(), Library()))
    own.add_category("Haustier")
    assert not startup.offer_migration(ROOT, own, folder)  # not even asked
    assert "Haustier" in own.catalog
    fresh = Session(Workspace(default_catalog(), Library()))
    assert not startup.offer_migration(ROOT, fresh, tmp_path)  # no legacy files there


def test_the_menu_refuses_a_library_with_statements(
    monkeypatch: pytest.MonkeyPatch, workspace: Workspace
) -> None:
    script = Script(monkeypatch)
    session = Session(workspace)
    startup.choose_and_migrate(ROOT, session)
    assert script.messages == [startup.NOT_EMPTY]


def test_the_menu_asks_before_replacing_own_categories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = _legacy_folder(tmp_path)
    monkeypatch.setattr(filedialog, "askdirectory", lambda **_options: str(folder))
    session = Session(Workspace(default_catalog(), Library()))
    session.add_category("Haustier")
    script = Script(monkeypatch, answers=[False, True])
    startup.choose_and_migrate(ROOT, session)
    assert "Haustier" in session.catalog  # "Nein" keeps them
    assert "ersetzt deine" in script.messages[0]
    startup.choose_and_migrate(ROOT, session)
    assert "Haustier" not in session.catalog
