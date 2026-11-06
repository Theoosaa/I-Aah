# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Page geometry: one test per grouping rule, each also checking the diagnosed status."""

from typing import Final

from iaah.core.models import Region
from iaah.core.parsing.layout import (
    BlockRules,
    Grouping,
    Line,
    LineKind,
    LineStatus,
    Word,
    group_lines_into_blocks,
    group_words_into_lines,
)

HEAD: Final = "14.03.2026 REWE SAGT DANKE -85,32"
NEXT_HEAD: Final = "15.03.2026 STARBUCKS -6,75"
BAD_HEAD: Final = "16.03.2026 Lastschrift ohne Betrag"


def _word(text: str, x0: float, top: float, width: float = 30.0, **flags: object) -> Word:
    return Word.from_pdfplumber(
        {"text": text, "x0": x0, "x1": x0 + width, "top": top, "bottom": top + 10, **flags}
    )


def _line(text: str, x0: float, top: float, width: float = 100.0, page: int = 1) -> Line:
    return Line(page=page, text=text, x0=x0, x1=x0 + width, top=top, bottom=top + 10)


def _classify(line: Line) -> LineKind:
    if line.text in {HEAD, NEXT_HEAD}:
        return LineKind.HEAD
    if line.text == BAD_HEAD:
        return LineKind.BAD_HEAD
    if line.text.startswith("Neuer Saldo"):
        return LineKind.END
    if line.text.startswith("Seite "):
        return LineKind.NOISE
    return LineKind.TEXT


def _group(lines: list[Line], rules: BlockRules | None = None) -> Grouping:
    return group_lines_into_blocks(lines, _classify, rules or BlockRules())


def _statuses(lines: list[Line], rules: BlockRules | None = None) -> list[LineStatus]:
    return [diagnosis.status for diagnosis in _group(lines, rules).diagnoses]


# -- words -> lines ---------------------------------------------------------------------------


def test_words_cluster_by_vertical_position() -> None:
    words = [
        _word("REWE", x0=100, top=101),
        _word("14.03.2026", x0=50, top=100, width=45),
        _word("-85,32", x0=135, top=100, width=25),
        _word("15.03.2026", x0=50, top=130, width=45),
    ]
    result = group_words_into_lines(words, page=3)
    assert [line.text for line in result.lines] == ["14.03.2026 REWE -85,32", "15.03.2026"]
    assert result.lines[0].bbox == (50, 100, 160, 111)
    assert result.lines[0].page == 3


def test_unreadable_words_are_dropped_and_counted() -> None:
    words = [
        _word("14.03.2026", x0=50, top=100),
        _word("HCILUARTREV", x0=512, top=100, upright=False),
        _word("mirrored", x0=300, top=100, direction="rtl"),
    ]
    result = group_words_into_lines(words, page=1)
    assert [line.text for line in result.lines] == ["14.03.2026"]
    assert result.dropped_words == 2


def test_empty_page() -> None:
    assert group_words_into_lines([], page=1).lines == ()


# -- lines -> blocks --------------------------------------------------------------------------


def test_head_with_details_forms_one_block() -> None:
    lines = [_line(HEAD, 50, 100), _line("Verwendungszweck", 50, 112), _line("Ref 1", 50, 124)]
    result = _group(lines)
    assert len(result.blocks) == 1
    assert [d.text for d in result.blocks[0].details] == ["Verwendungszweck", "Ref 1"]
    assert result.blocks[0].detail_regions == (Region(1, (50, 112, 150, 134)),)
    assert [d.block for d in result.diagnoses] == [0, 0, 0]


def test_block_without_details_has_no_detail_regions() -> None:
    assert _group([_line(HEAD, 50, 100)]).blocks[0].detail_regions == ()


def test_next_head_closes_block() -> None:
    lines = [_line(HEAD, 50, 100), _line("Zweck", 50, 112), _line(NEXT_HEAD, 50, 124)]
    result = _group(lines)
    assert len(result.blocks) == 2
    assert [d.block for d in result.diagnoses] == [0, 0, 1]


def test_bad_head_closes_booking_instead_of_joining_it() -> None:
    lines = [_line(HEAD, 50, 100), _line(BAD_HEAD, 50, 112), _line("sein Zweck", 50, 124)]
    result = _group(lines)
    assert result.blocks[0].details == []
    assert [d.status for d in result.diagnoses] == [
        LineStatus.HEAD,
        LineStatus.BAD_HEAD,
        LineStatus.NO_OPEN_BOOKING,
    ]


def test_line_outside_column_is_rejected() -> None:
    lines = [_line(HEAD, 50, 100), _line("Randnotiz", 480, 112), _line("Zweck", 50, 124)]
    assert _statuses(lines) == [LineStatus.HEAD, LineStatus.OUTSIDE_COLUMN, LineStatus.DETAIL]


def test_large_gap_closes_booking() -> None:
    lines = [_line(HEAD, 50, 100), _line("Fußzeile", 50, 250), _line("weiter", 50, 262)]
    statuses = _statuses(lines, BlockRules(max_line_gap=20))
    assert statuses == [LineStatus.HEAD, LineStatus.GAP_TOO_LARGE, LineStatus.NO_OPEN_BOOKING]


def test_detail_limit() -> None:
    lines = [_line(HEAD, 50, 100)] + [_line(f"Zeile {i}", 50, 112 + i * 12) for i in range(3)]
    statuses = _statuses(lines, BlockRules(max_detail_lines=2))
    assert statuses[-1] is LineStatus.DETAIL_LIMIT
    assert statuses.count(LineStatus.DETAIL) == 2


def test_gap_is_reported_before_detail_limit() -> None:
    lines = [_line(HEAD, 50, 100), _line("Zeile", 50, 112), _line("Fußzeile", 50, 400)]
    assert _statuses(lines, BlockRules(max_detail_lines=1))[-1] is LineStatus.GAP_TOO_LARGE


def test_lines_before_first_booking_and_noise() -> None:
    lines = [_line("Kontoauszug", 50, 50), _line(HEAD, 50, 100), _line("Seite 2", 50, 112)]
    assert _statuses(lines) == [LineStatus.NO_OPEN_BOOKING, LineStatus.HEAD, LineStatus.NOISE]


def test_noise_does_not_extend_the_gap_window() -> None:
    # Noise right below a booking must not let a far-away footer count as a detail.
    lines = [_line(HEAD, 50, 100), _line("Seite 1", 50, 200), _line("Fußzeile", 50, 210)]
    assert _statuses(lines)[-1] is LineStatus.GAP_TOO_LARGE


def test_booking_continues_on_next_page() -> None:
    lines = [
        _line(HEAD, 50, 700),
        _line("Zweck Teil 1", 50, 712),
        _line("Seite 2", 50, 40, page=2),
        _line("Zweck Teil 2", 50, 60, page=2),
        _line(NEXT_HEAD, 50, 80, page=2),
    ]
    result = _group(lines)
    first = result.blocks[0]
    assert [line.text for line in first.details] == ["Zweck Teil 1", "Zweck Teil 2"]
    assert [region.page for region in first.detail_regions] == [1, 2]


def test_end_marker_stops_carry_over_to_next_page() -> None:
    # Regression: text on the page after the closing balance was appended to the last booking.
    lines = [
        _line(HEAD, 50, 700),
        _line("Zweck", 50, 712),
        _line("Neuer Saldo 1.000,00", 50, 724),
        _line("Kunden-Information", 50, 60, page=2),
    ]
    result = _group(lines)
    assert [line.text for line in result.blocks[0].details] == ["Zweck"]
    assert [d.status for d in result.diagnoses][-2:] == [
        LineStatus.END,
        LineStatus.NO_OPEN_BOOKING,
    ]


def test_empty_input() -> None:
    result = _group([])
    assert result.blocks == ()
    assert result.diagnoses == ()
