"""Exception hierarchy of the core layer.

Messages are English and meant for logs; GUI and CLI catch these types and show their own
German text.
"""


class IaahError(Exception):
    """Base class for every error raised deliberately by iaah."""


class StatementParseError(IaahError):
    """A file could not be read as a bank statement."""


class CsvMappingError(IaahError):
    """The date or amount column of a CSV export could not be determined."""


class CategoryError(IaahError):
    """An operation on the category catalog would break one of its rules."""


class UnknownCategoryError(CategoryError):
    """No category with this name exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"unknown category: {name!r}")
        self.name = name


class DuplicateCategoryError(CategoryError):
    """A category with this name already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"category already exists: {name!r}")
        self.name = name


class KeywordConflictError(CategoryError):
    """The keyword already belongs to another category."""

    def __init__(self, keyword: str, owner: str) -> None:
        super().__init__(f"keyword {keyword!r} already belongs to {owner!r}")
        self.keyword = keyword
        self.owner = owner


class FallbackCategoryError(CategoryError):
    """A fallback category cannot be removed, re-kinded, or be missing."""


class SplitError(IaahError):
    """A split does not add up to the booking it divides."""


class CategoryFileError(IaahError):
    """A category file could not be read."""


class StorageError(IaahError):
    """A data file could not be read or written."""


class PasswordRequiredError(StorageError):
    """The data is encrypted and no password was given."""


class WrongPasswordError(StorageError):
    """The password does not decrypt the data."""


class DataUnreadableError(StorageError):
    """The data file exists but cannot be read right now (locked, no permission) – not damage;
    nothing may be set aside because of it."""


class UnsupportedVersionError(StorageError):
    """The data file was written by a newer program version – never treated as damage."""
