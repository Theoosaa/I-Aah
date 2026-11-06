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
