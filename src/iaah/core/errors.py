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
