"""German messages for the errors the lower layers raise (their own texts are English)."""

from typing import Final

from iaah.core.errors import (
    CategoryError,
    CategoryFileError,
    CsvMappingError,
    DataUnreadableError,
    DuplicateCategoryError,
    FallbackCategoryError,
    IaahError,
    KeywordConflictError,
    PasswordRequiredError,
    SplitError,
    StatementParseError,
    StorageError,
    UnknownCategoryError,
    UnsupportedVersionError,
    WrongPasswordError,
)
from iaah.core.storage import AlreadyRunningError
from iaah.export.files import ExportError
from iaah.export.summary import SummaryFileError

APP_TITLE: Final = "I-Aah"
GENERIC: Final = "Unerwarteter Fehler."
INVALID_CATEGORY_INPUT: Final = (
    "Ungültige Eingabe. Ein Name darf nicht leer sein, ein Stichwort braucht einen Buchstaben "
    "oder eine Ziffer, ein Budget ist ein Betrag ab 0 € in ganzen Cent."
)

# Most specific first; the first matching type gives the message.
MESSAGES: Final[tuple[tuple[type[IaahError], str], ...]] = (
    (AlreadyRunningError, "I-Aah läuft bereits. Bitte das andere Fenster verwenden."),
    (WrongPasswordError, "Das Passwort ist falsch."),
    (PasswordRequiredError, "Die Daten sind verschlüsselt – bitte das Passwort eingeben."),
    (UnsupportedVersionError, "Die Daten stammen aus einer neueren I-Aah-Version."),
    (
        DataUnreadableError,
        "Die Datendatei lässt sich nicht lesen (gesperrt, ohne Zugriffsrechte oder keine "
        "normale Datei). Sie bleibt unverändert – bitte den Datenordner prüfen.",
    ),
    (StorageError, "Die Daten konnten nicht gelesen oder gespeichert werden."),
    (StatementParseError, "Die Datei konnte nicht als Kontoauszug gelesen werden."),
    (CsvMappingError, "In der CSV-Datei wurden Datum oder Betrag nicht erkannt."),
    (CategoryFileError, "Die Kategorien-Datei ist fehlerhaft."),
    (SummaryFileError, "Die Zusammenfassung ist fehlerhaft."),
    (
        SplitError,
        "Die Teile ergeben nicht den Buchungsbetrag (jeder Teil braucht das Vorzeichen "
        "der Buchung, jede Kategorie höchstens einmal).",
    ),
    (
        FallbackCategoryError,
        "Auffang-Kategorien (Einkommen, Sonstiges) lassen sich weder "
        "löschen noch in ihrer Art ändern.",
    ),
)


def error_message(error: IaahError) -> str:
    """The German text for ``error``, naming what the error names (file, category, keyword)."""
    if isinstance(error, ExportError):
        return f"{error.path} konnte nicht geschrieben werden (in einem anderen Programm offen?)."
    if isinstance(error, KeywordConflictError):
        return f"Das Stichwort „{error.keyword}“ gehört schon zu „{error.owner}“."
    if isinstance(error, DuplicateCategoryError):
        return f"Die Kategorie „{error.name}“ gibt es schon."
    if isinstance(error, UnknownCategoryError):
        return f"Die Kategorie „{error.name}“ gibt es nicht."
    if isinstance(error, CategoryError) and not isinstance(error, FallbackCategoryError):
        return INVALID_CATEGORY_INPUT
    return next((text for kind, text in MESSAGES if isinstance(error, kind)), GENERIC)
