# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Bank-agnostic page geometry: words → lines → booking blocks.

Words are clustered into lines purely by vertical position – splitting a row by horizontal
gaps is unreliable (fonts, kerning, justification). Unrelated text at a similar height, such as
margin notes or page stamps, is rejected one level up: a line only continues a booking if it
lies inside the booking's column span and close below it.

What a line *is* (booking head, malformed head, page noise, plain text) is bank-specific; the
caller injects a classifier. Every line receives a ``LineStatus`` explaining what happened to
it. Everything here is pure – no pdfplumber, no I/O.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Self

from iaah.core.models import BBox, Region

LINE_TOLERANCE: Final = 3.0  # points: words whose tops differ less share one line
LEFT_TO_RIGHT: Final = "ltr"


class LineKind(StrEnum):
    """What a bank-specific classifier says a line is."""

    HEAD = "head"  # a valid booking head
    BAD_HEAD = "bad_head"  # shaped like a booking head but unreadable
    END = "end"  # marks the end of the booking list (e.g. closing balance)
    NOISE = "noise"  # known page header or footer
    TEXT = "text"  # anything else; may continue a booking


# Gets the whole line, so banks can use geometry (e.g. "the amount column is reached").
type LineClassifier = Callable[[Line], LineKind]


class LineStatus(StrEnum):
    """What happened to a line while grouping pages into bookings."""

    HEAD = "head"  # starts a booking
    DETAIL = "detail"  # continues the open booking
    BAD_HEAD = "bad_head"  # looks like a booking but could not be read; closes the open one
    END = "end"  # end of the booking list; closes the open booking
    NOISE = "noise"  # known page header or footer
    NO_OPEN_BOOKING = "no_open_booking"  # no booking to continue
    OUTSIDE_COLUMN = "outside_column"  # beside the booking's column span
    GAP_TOO_LARGE = "gap_too_large"  # too far below; closes the open booking
    DETAIL_LIMIT = "detail_limit"  # the open booking already has enough detail lines


@dataclass(frozen=True, slots=True)
class Word:
    """A word as extracted by pdfplumber, reduced to what layout needs."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    upright: bool = True
    direction: str = LEFT_TO_RIGHT

    @classmethod
    def from_pdfplumber(cls, raw: Mapping[str, Any]) -> Self:
        """Build from a ``page.extract_words()`` dict; missing flags mean upright, left-to-right."""
        return cls(
            text=str(raw["text"]),
            x0=float(raw["x0"]),
            x1=float(raw["x1"]),
            top=float(raw["top"]),
            bottom=float(raw["bottom"]),
            upright=bool(raw.get("upright", True)),
            direction=str(raw.get("direction", LEFT_TO_RIGHT)),
        )

    @property
    def readable(self) -> bool:
        """Rotated or mirrored text (stamps, margin codes) has no usable reading order."""
        return self.upright and self.direction == LEFT_TO_RIGHT


@dataclass(frozen=True, slots=True)
class Line:
    """One visual line of a page."""

    page: int
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def bbox(self) -> BBox:
        """Bounding box of the whole line."""
        return (self.x0, self.top, self.x1, self.bottom)


@dataclass(frozen=True, slots=True)
class PageLines:
    """Lines of one page plus the number of unreadable words that were dropped."""

    lines: tuple[Line, ...]
    dropped_words: int


@dataclass(frozen=True, slots=True)
class LineDiagnosis:
    """A line together with its status and, if accepted, the index of its block."""

    line: Line
    status: LineStatus
    block: int | None = None


@dataclass(slots=True)
class Block:
    """A booking's lines: one head line and its detail (purpose) lines."""

    head: Line
    details: list[Line] = field(default_factory=list)

    @property
    def detail_regions(self) -> tuple[Region, ...]:
        """One region per page, each the union of that page's detail lines."""
        pages = sorted({line.page for line in self.details})
        return tuple(
            Region(page, _union(ln for ln in self.details if ln.page == page)) for page in pages
        )


@dataclass(frozen=True, slots=True)
class BlockRules:
    """Thresholds for accepting a detail line, in PDF points."""

    column_tolerance: float = 15.0
    max_line_gap: float = 20.0
    max_detail_lines: int = 12


DEFAULT_BLOCK_RULES: Final = BlockRules()

# Line kinds that close the open booking, and the status they are reported with.
_CLOSING_KINDS: Final[dict[LineKind, LineStatus]] = {
    LineKind.BAD_HEAD: LineStatus.BAD_HEAD,
    LineKind.END: LineStatus.END,
}


@dataclass(frozen=True, slots=True)
class Grouping:
    """Blocks of a document and the diagnosis of every line."""

    blocks: tuple[Block, ...]
    diagnoses: tuple[LineDiagnosis, ...]


def group_words_into_lines(
    words: Sequence[Word], page: int, tolerance: float = LINE_TOLERANCE
) -> PageLines:
    """Cluster words into lines by vertical position, dropping unreadable words."""
    readable = [word for word in words if word.readable]
    ordered = sorted(readable, key=lambda word: (round(word.top), word.x0))

    rows: list[list[Word]] = []
    for word in ordered:
        if rows and abs(word.top - rows[-1][0].top) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])

    lines = sorted((_row_to_line(row, page) for row in rows), key=lambda ln: (ln.top, ln.x0))
    return PageLines(tuple(lines), len(words) - len(readable))


def group_lines_into_blocks(
    lines: Iterable[Line],
    classify: LineClassifier,
    rules: BlockRules = DEFAULT_BLOCK_RULES,
) -> Grouping:
    """Group the lines of a whole document (page by page, top to bottom) into booking blocks.

    A booking that is still open at the end of a page continues on the next one: the first
    text line there is not subject to the gap rule, only to the column rule.
    """
    builder = _BlockBuilder(classify, rules)
    for line in lines:
        builder.feed(line)
    return builder.result()


def _row_to_line(row: list[Word], page: int) -> Line:
    row.sort(key=lambda word: word.x0)
    return Line(
        page=page,
        text=" ".join(word.text for word in row),
        x0=min(word.x0 for word in row),
        x1=max(word.x1 for word in row),
        top=min(word.top for word in row),
        bottom=max(word.bottom for word in row),
    )


def _union(lines: Iterable[Line]) -> BBox:
    boxes = [line.bbox for line in lines]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


class _BlockBuilder:
    """State machine behind ``group_lines_into_blocks``."""

    def __init__(self, classify: LineClassifier, rules: BlockRules) -> None:
        self._classify = classify
        self._rules = rules
        self._blocks: list[Block] = []
        self._diagnoses: list[LineDiagnosis] = []
        self._open: Block | None = None
        self._page: int | None = None
        self._last_top: float | None = None  # None right after a page break

    def feed(self, line: Line) -> None:
        if line.page != self._page:
            self._page = line.page
            self._last_top = None

        kind = self._classify(line)
        if kind is LineKind.HEAD:
            self._start(line)
            return
        if kind in _CLOSING_KINDS:
            self._open = None
            self._record(line, _CLOSING_KINDS[kind])
            return
        if kind is LineKind.NOISE:
            self._record(line, LineStatus.NOISE)
            return
        self._record(line, self._absorb(line))

    def result(self) -> Grouping:
        return Grouping(tuple(self._blocks), tuple(self._diagnoses))

    def _start(self, line: Line) -> None:
        self._open = Block(head=line)
        self._blocks.append(self._open)
        self._last_top = line.top
        self._record(line, LineStatus.HEAD)

    def _record(self, line: Line, status: LineStatus) -> None:
        accepted = status in (LineStatus.HEAD, LineStatus.DETAIL)
        block = len(self._blocks) - 1 if accepted else None
        self._diagnoses.append(LineDiagnosis(line, status, block))

    def _absorb(self, line: Line) -> LineStatus:
        """Attach a text line to the open block if it qualifies; return why or why not."""
        block = self._open
        if block is None:
            return LineStatus.NO_OPEN_BOOKING
        if not self._inside_column(block, line):
            # We did pass this height, just with unrelated content; the gap check below
            # must not count it as a jump.
            self._last_top = line.top
            return LineStatus.OUTSIDE_COLUMN
        if self._last_top is not None and line.top - self._last_top > self._rules.max_line_gap:
            self._open = None
            return LineStatus.GAP_TOO_LARGE
        if len(block.details) >= self._rules.max_detail_lines:
            return LineStatus.DETAIL_LIMIT
        block.details.append(line)
        self._last_top = line.top
        return LineStatus.DETAIL

    def _inside_column(self, block: Block, line: Line) -> bool:
        tolerance = self._rules.column_tolerance
        return block.head.x0 - tolerance <= line.x0 and line.x1 <= block.head.x1 + tolerance
