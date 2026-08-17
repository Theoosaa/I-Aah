"""Farbig markiertes Konto-PDF.

Erzeugt eine Kopie des Original-Kontoauszugs, bei der hinter jeder Buchung
ein halbtransparenter Farbbalken in der Farbe ihrer Kategorie liegt, plus
eine angehaengte Legende (Kategorie -> Farbe).

Bewusst ein *eigenstaendiger*, koordinaten-bewusster Lesepfad: der
Haupt-Parser (:func:`parser.parse_pdf`, textbasiert mit Saldo-Abgleich)
bleibt voellig unberuehrt. Hier werden die Woerter *mit Koordinaten*
gelesen, rein nach vertikaler Naehe zu Zeilen geclustert und die
Buchungs-Hauptzeilen ueber dieselbe Regex (:data:`parser._MAIN_RE`)
erkannt – so behaelt jede Buchung ihre Bounding-Box und laesst sich
farbig hinterlegen. Verwendungszweck-Folgezeilen darunter (gleiche
Spalte, kleiner Abstand) werden zur selben Buchung dazugerechnet, damit
Haupt- und Detailzeile als ein Block markiert werden.

Optionale Abhaengigkeiten: ``pypdf`` (Zusammenfuehren) und ``reportlab``
(Overlay/Legende zeichnen). Fehlen sie, wirft :func:`create_highlighted_pdf`
einen ``ImportError`` mit klarer Meldung – die uebrige App laeuft ohne sie.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import date
from typing import Callable, Iterator

import pdfplumber

from parser import _MAIN_RE, _is_footer, _parse_amount

# --- optionale Zeichen-/Merge-Bibliotheken (lazy, mit klarer Fehlermeldung) --
_MISSING_MSG = (
    "Für das markierte PDF fehlen Pakete.\n"
    "Bitte installieren mit:\n\n    pip install pypdf reportlab"
)


def _require_libs():
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: F401
        from reportlab.lib.colors import HexColor, black  # noqa: F401
        from reportlab.lib.pagesizes import A4  # noqa: F401
        from reportlab.pdfgen import canvas  # noqa: F401
    except ImportError as e:  # pragma: no cover - abhaengig von Installation
        raise ImportError(_MISSING_MSG) from e


# ---------------------------------------------------------------------------
# Koordinaten-Transformation (pdfplumber top-down -> reportlab bottom-up)
# ---------------------------------------------------------------------------
def _to_reportlab(bbox, page_height: float, padding: float = 2.0):
    """(x0, top, x1, bottom) in PDF-Punkten (Ursprung oben-links) ->
    (x, y, breite, hoehe) fuer reportlab (Ursprung unten-links).

    Liefert immer positive Breite/Hoehe."""
    x0, top, x1, bottom = bbox
    left = x0 - padding
    right = x1 + padding
    y0 = page_height - bottom - padding      # untere Kante (kleineres y)
    y1 = page_height - top + padding          # obere Kante
    return left, y0, right - left, y1 - y0


# ---------------------------------------------------------------------------
# Woerter -> Zeilen (rein vertikale Naehe; keine Spaltentrennung)
# ---------------------------------------------------------------------------
def _words_to_lines(words: list[dict], tolerance: float = 3.0) -> list[dict]:
    """Clustert pdfplumber-Woerter (``extract_words``) allein nach
    vertikaler Position zu Zeilen. Rueckgabe je Zeile:
    ``{'text','x0','x1','top','bottom'}``, von oben nach unten sortiert."""
    usable = [w for w in words if w.get("upright", True)]
    ordered = sorted(usable, key=lambda w: (round(w["top"]), w["x0"]))

    rows: list[list[dict]] = []
    for w in ordered:
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])

    lines: list[dict] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        lines.append({
            "text": " ".join(w["text"] for w in row),
            "x0": min(w["x0"] for w in row),
            "x1": max(w["x1"] for w in row),
            "top": min(w["top"] for w in row),
            "bottom": max(w["bottom"] for w in row),
        })
    lines.sort(key=lambda ln: (ln["top"], ln["x0"]))
    return lines


def _union(a, b):
    if a is None:
        return b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


class _Booking:
    __slots__ = ("page", "datum", "betrag", "bbox", "zweck_bbox", "category")

    def __init__(self, page, datum, betrag, bbox):
        self.page = page
        self.datum = datum
        self.betrag = betrag
        self.bbox = bbox
        self.zweck_bbox = None
        self.category = "Nicht zugeordnet"


def _iter_bookings(
    pdf_path: str,
    *,
    column_tolerance: float = 15.0,
    max_line_gap: float = 20.0,
    max_continuation_lines: int = 12,
) -> Iterator[_Booking]:
    """Liest ``pdf_path`` koordinaten-bewusst und liefert je Buchung ein
    :class:`_Booking` mit Bounding-Box(en). Erkennt Hauptzeilen ueber
    :data:`parser._MAIN_RE`; passende Folgezeilen (gleiche Spalte, kleiner
    vertikaler Abstand, kein Footer) werden in ``zweck_bbox`` aufgenommen."""
    with pdfplumber.open(pdf_path) as pdf:
        for pageno, page in enumerate(pdf.pages, start=1):
            lines = _words_to_lines(page.extract_words(keep_blank_chars=False))
            current: _Booking | None = None
            cur_x0 = cur_x1 = last_top = 0.0
            cont = 0

            for ln in lines:
                m = _MAIN_RE.match(ln["text"].strip())
                if m:
                    if current is not None:
                        yield current
                    datum_str, _desc, betrag_str = m.groups()
                    try:
                        d = date(int(datum_str[6:10]), int(datum_str[3:5]),
                                 int(datum_str[0:2]))
                        amt = _parse_amount(betrag_str)
                    except (ValueError, IndexError):
                        current = None
                        continue
                    current = _Booking(
                        pageno, d, amt,
                        (ln["x0"], ln["top"], ln["x1"], ln["bottom"]))
                    cur_x0, cur_x1, last_top, cont = (
                        ln["x0"], ln["x1"], ln["top"], 0)
                    continue

                if current is None or cont >= max_continuation_lines:
                    continue
                # andere Spalte (Randnotiz / Seitenstempel) -> ignorieren,
                # aber vertikale Position vermerken
                if (ln["x0"] < cur_x0 - column_tolerance
                        or ln["x1"] > cur_x1 + column_tolerance):
                    last_top = ln["top"]
                    continue
                if ln["top"] - last_top > max_line_gap:
                    yield current
                    current = None
                    continue
                if _is_footer(ln["text"]):
                    last_top = ln["top"]
                    continue
                current.zweck_bbox = _union(
                    current.zweck_bbox,
                    (ln["x0"], ln["top"], ln["x1"], ln["bottom"]))
                last_top = ln["top"]
                cont += 1

            if current is not None:
                yield current


# ---------------------------------------------------------------------------
# Oeffentliche Funktion
# ---------------------------------------------------------------------------
def create_highlighted_pdf(
    pdf_path: str,
    output_path: str,
    resolve: Callable[[date, float], str | None],
    color_of: Callable[[str], str],
    *,
    alpha: float = 0.35,
    default_color: str = "#dddddd",
) -> tuple[int, list[str]]:
    """Schreibt eine markierte Kopie von ``pdf_path`` nach ``output_path``.

    ``resolve(datum, betrag)`` liefert je Buchung den Kategorienamen (oder
    ``None`` -> "Nicht zugeordnet"); ``color_of(name)`` liefert die
    Hex-Farbe. Rueckgabe: ``(anzahl_markiert, benutzte_kategorien)``.

    Wirft ``ImportError`` (klare Meldung), falls ``pypdf``/``reportlab``
    fehlen.
    """
    _require_libs()
    from pypdf import PdfReader, PdfWriter

    bookings = list(_iter_bookings(pdf_path))
    for b in bookings:
        b.category = resolve(b.datum, b.betrag) or "Nicht zugeordnet"

    by_page: dict[int, list[_Booking]] = defaultdict(list)
    for b in bookings:
        by_page[b.page].append(b)

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for pageno, page in enumerate(reader.pages, start=1):
        page_bookings = by_page.get(pageno)
        if page_bookings:
            _overlay(page, page_bookings, color_of, alpha, default_color)
        writer.add_page(page)

    # Legende nur fuer tatsaechlich vorkommende Kategorien (stabile Reihenfolge)
    used: list[str] = []
    for b in bookings:
        if b.category not in used:
            used.append(b.category)
    writer.add_page(_legend_page(used, color_of, default_color))

    with open(output_path, "wb") as f:
        writer.write(f)
    return len(bookings), used


def _overlay(page, bookings, color_of, alpha, default_color) -> None:
    from pypdf import PdfReader
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    width = float(page.mediabox.width)
    height = float(page.mediabox.height)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFillAlpha(alpha)
    for b in bookings:
        try:
            c.setFillColor(HexColor(color_of(b.category) or default_color))
        except (ValueError, TypeError):
            c.setFillColor(HexColor(default_color))
        for bbox in (b.bbox, b.zweck_bbox):
            if bbox is None:
                continue
            x, y, w, h = _to_reportlab(bbox, height)
            c.rect(x, y, w, h, fill=1, stroke=0)
    c.save()
    buf.seek(0)

    overlay_page = PdfReader(buf).pages[0]
    page.merge_page(overlay_page, over=False)  # Farbe hinter den Text


def _legend_page(categories, color_of, default_color):
    from pypdf import PdfReader
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pw, ph = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(black)
    c.drawString(50, ph - 60, "Legende: Kategorie-Farben")

    c.setFont("Helvetica", 12)
    y = ph - 100
    box = 14
    for name in categories:
        try:
            c.setFillColor(HexColor(color_of(name) or default_color))
        except (ValueError, TypeError):
            c.setFillColor(HexColor(default_color))
        c.rect(50, y - box + 3, box, box, fill=1, stroke=0)
        c.setFillColor(black)
        c.drawString(50 + box + 10, y, name)
        y -= box + 10
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 12)
            y = ph - 60
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]
