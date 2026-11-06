"""Parse results and the per-line report behind the PDF review tab and ``iaah-cli check``.

``ParsedStatement`` lives here rather than in ``models`` because it carries the report, and the
report refers to layout lines; keeping it out of ``models`` avoids an import cycle.
"""

from collections import Counter
from dataclasses import dataclass, field

from iaah.core.models import StatementInfo, Transaction
from iaah.core.parsing.layout import LineDiagnosis, LineStatus


@dataclass(frozen=True, slots=True)
class ParseReport:
    """How a statement file was read.

    ``suspicious`` lists lines shaped like a booking (date and amount) that did not become one;
    lines with status ``BAD_HEAD`` looked like a booking head but could not be read. Both are
    worth a look when a new statement layout appears. ``skipped_rows`` holds the indexes of
    CSV rows without a valid date or amount.
    """

    lines: tuple[LineDiagnosis, ...] = ()
    dropped_words: int = 0
    skipped_rows: tuple[int, ...] = ()
    suspicious: tuple[LineDiagnosis, ...] = ()

    def with_status(self, status: LineStatus) -> tuple[LineDiagnosis, ...]:
        """All lines that received ``status``."""
        return tuple(diagnosis for diagnosis in self.lines if diagnosis.status is status)

    def counts(self) -> dict[LineStatus, int]:
        """Number of lines per status."""
        return dict(Counter(diagnosis.status for diagnosis in self.lines))

    @property
    def has_problems(self) -> bool:
        """Whether anything may have been missed: suspicious or unreadable booking lines."""
        return bool(self.suspicious or self.with_status(LineStatus.BAD_HEAD))


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    """Everything one statement file yields."""

    info: StatementInfo
    transactions: tuple[Transaction, ...]
    report: ParseReport = field(default_factory=ParseReport)
