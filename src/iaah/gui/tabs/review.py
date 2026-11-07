# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""PDF review: the statement page with every booking in its category color.

*Vorher* shows what keywords alone decide, *Nachher* the current state; bookings a decision
changed are outlined. A click on a box selects the booking, the buttons on the right assign it.
The second list shows lines the parser did not use, suspicious ones first.
"""

import tkinter as tk
from functools import partial
from io import BytesIO
from pathlib import Path
from tkinter import ttk
from typing import Final

import pdfplumber
from pdfplumber.pdf import PDF
from PIL import Image, ImageColor, ImageDraw, ImageTk
from PIL.Image import Image as PilImage

from iaah.core.errors import IaahError
from iaah.core.geometry import to_target_box
from iaah.core.library import StoredStatement
from iaah.core.models import Transaction
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.gui.host import Host
from iaah.gui.texts import error_message
from iaah.gui.theme import FONT_TITLE, PAD, PAD_LARGE
from iaah.gui.viewmodel import (
    ReviewBox,
    UnusedLine,
    booking_at,
    position_of,
    review_boxes,
    review_rows,
    unused_lines,
)
from iaah.gui.widgets import CategoryButtons, ColumnSpec, ScrolledTree

POINTS_PER_INCH: Final = 72.0
BASE_DPI: Final = 100.0
ZOOMS: Final = (0.75, 1.0, 1.25, 1.5, 2.0)
START_ZOOM: Final = 1
FILL_ALPHA: Final = 80  # of 255
OUTLINE_WIDTH: Final = 2
THIN_OUTLINE: Final = 1
TRANSPARENT: Final = (0, 0, 0, 0)
CONTROL_MASK: Final = 0x0004  # Tk event state bit of the Ctrl key
SELECTION_PADDING: Final = 4.0
CHANGED_OUTLINE: Final = "#333333"
SELECTION_TAG: Final = "selection"
PANEL_WIDTH: Final = 420
COMBO_WIDTH: Final = 46
DIGITS: Final = "123456789"
NO_STATEMENT: Final = "Kein PDF-Kontoauszug mit vorhandener Datei importiert."
BOOKING_COLUMNS: Final = (
    ColumnSpec("day", "Datum", 75),
    ColumnSpec("payee", "Empfänger", 115, stretch=True),
    ColumnSpec("amount", "Betrag", 85, "e"),
    ColumnSpec("category", "Kategorie", 105),
)
LINE_COLUMNS: Final = (
    ColumnSpec("page", "S.", 30),
    ColumnSpec("reason", "Grund", 140),
    ColumnSpec("text", "Zeile", 200, stretch=True),
)


class ReviewTab(ttk.Frame):
    """Statement picker and page view left, bookings, buttons and unused lines right."""

    def __init__(self, parent: tk.Misc, host: Host) -> None:
        super().__init__(parent, padding=PAD)
        self.host = host
        self._statements: list[StoredStatement] = []
        self._statement: StoredStatement | None = None
        self._parsed: ParsedStatement | None = None
        self._pdf: PDF | None = None
        self._pages: dict[tuple[int, int], PilImage] = {}  # (page, zoom) -> rendered page
        self._page = 1
        self._zoom = START_ZOOM
        self._selected: int | None = None  # index into the statement's transactions
        self._unused: list[UnusedLine] = []
        self._photo: ImageTk.PhotoImage | None = None  # keeps the image alive
        self.before = tk.BooleanVar(value=False)
        self._build_toolbar()
        self._build_canvas()
        self._build_panel()
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

    # -- building ---------------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, PAD))
        ttk.Label(bar, text="Kontoauszug:").pack(side="left")
        self.picker = ttk.Combobox(bar, state="readonly", width=COMBO_WIDTH)
        self.picker.pack(side="left", padx=PAD)
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self._open(self.picker.current()))
        ttk.Button(bar, text="◀", style="Small.TButton", command=lambda: self._turn(-1)).pack(
            side="left"
        )
        self.page_label = ttk.Label(bar, text="")
        self.page_label.pack(side="left", padx=PAD)
        ttk.Button(bar, text="▶", style="Small.TButton", command=lambda: self._turn(1)).pack(
            side="left"
        )
        ttk.Button(bar, text="-", style="Small.TButton", command=lambda: self._zoom_by(-1)).pack(
            side="left", padx=(PAD, 0)
        )
        ttk.Button(bar, text="+", style="Small.TButton", command=lambda: self._zoom_by(1)).pack(
            side="left"
        )
        ttk.Checkbutton(
            bar, text="Vorher (nur Stichwörter) zeigen", variable=self.before, command=self._draw
        ).pack(side="left", padx=PAD_LARGE)

    def _build_canvas(self) -> None:
        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="nsew")
        self.canvas = tk.Canvas(frame, highlightthickness=0)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)
        for digit in DIGITS:  # keys 1–9 assign like on the transactions tab
            self.canvas.bind(digit, partial(self._on_digit, int(digit)))

    def _build_panel(self) -> None:
        panel = ttk.Frame(self, width=PANEL_WIDTH, padding=(PAD_LARGE, 0, 0, 0))
        panel.grid(row=1, column=1, sticky="ns")
        panel.grid_propagate(False)
        panel.rowconfigure(1, weight=2)
        panel.rowconfigure(5, weight=1)
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="Buchungen", font=FONT_TITLE).grid(row=0, column=0, sticky="w")
        self.bookings = ScrolledTree(panel, BOOKING_COLUMNS, selectmode="browse")
        self.bookings.grid(row=1, column=0, sticky="nsew")
        self.bookings.tree.bind("<<TreeviewSelect>>", lambda _e: self._pick_from_list())
        for digit in DIGITS:
            self.bookings.tree.bind(digit, partial(self._on_digit, int(digit)))
        self.buttons = CategoryButtons(panel, self._assign)
        self.buttons.grid(row=2, column=0, sticky="w", pady=PAD)
        self.message = ttk.Label(panel, text="", style="Muted.TLabel")
        self.message.grid(row=3, column=0, sticky="w")
        ttk.Label(panel, text="Nicht verwendete Zeilen", font=FONT_TITLE).grid(
            row=4, column=0, sticky="w", pady=(PAD, 0)
        )
        self.lines = ScrolledTree(panel, LINE_COLUMNS, selectmode="browse")
        self.lines.grid(row=5, column=0, sticky="nsew")
        self.lines.tree.bind("<<TreeviewSelect>>", lambda _e: self._jump_to_line())

    # -- opening ------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Statement list, then page and lists for the current state."""
        self._statements = self.host.session.reviewable()
        self.picker.configure(values=[self._label(s) for s in self._statements])
        self.buttons.set_categories([(c.name, c.color) for c in self.host.session.catalog])
        if self._statement not in self._statements:
            self._open(0 if self._statements else -1)
            return
        self._fill_lists()
        self._draw()

    @staticmethod
    def _label(stored: StoredStatement) -> str:
        period = stored.info.period or "ohne Monat"
        return f"{period}   {stored.info.source}"

    def _open(self, position: int) -> None:
        self._close()
        if position < 0:
            self.message.configure(text=NO_STATEMENT)
            self.canvas.delete("all")
            self.bookings.fill([])
            self.lines.fill([])
            return
        self._statement = self._statements[position]
        self.picker.current(position)
        try:
            self._parsed = self.host.session.open_statement(self._statement)
            # Read into memory: an open file would be locked on Windows while I-Aah runs.
            self._pdf = pdfplumber.open(BytesIO(Path(self._statement.path or "").read_bytes()))
        except (IaahError, OSError) as error:
            message = error_message(error) if isinstance(error, IaahError) else str(error)
            self.message.configure(text=message)
            return
        self._page, self._selected = 1, None
        self._fill_lists()
        self._draw()

    def _close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()
        self._pdf, self._parsed, self._statement = None, None, None
        self._pages.clear()

    def show_booking(self, txn: Transaction) -> bool:
        """Open the statement of ``txn`` and select it; ``False`` if it has no reviewable PDF."""
        self._statements = self.host.session.reviewable()
        statement = self.host.session.statement_of(txn)
        if statement is None:
            return False
        self._open(self._statements.index(statement))
        match = position_of(self._transactions(), txn)
        if match is not None:
            self._select(match)
        return True

    def _transactions(self) -> tuple[Transaction, ...]:
        return self._parsed.transactions if self._parsed else ()

    # -- lists --------------------------------------------------------------------------------

    def _fill_lists(self) -> None:
        rows = review_rows(self._transactions(), self.host.session.categorizer)
        self.bookings.fill((str(index), cells, ()) for index, cells in enumerate(rows))
        report_lines = unused_lines(self._parsed.report) if self._parsed else []
        self._unused = report_lines
        self.lines.fill(
            (str(n), (str(line.page), line.reason, line.text), ())
            for n, line in enumerate(report_lines)
        )
        count = len(self._transactions())
        self.message.configure(
            text=f"{count} Buchungen, {len(report_lines)} Zeilen nicht verwendet"
        )
        if self._selected is not None:
            self.bookings.show([str(self._selected)])

    def _pick_from_list(self) -> None:
        selected = self.bookings.selected()
        if selected and int(selected[0]) != self._selected:
            self._select(int(selected[0]))

    def _jump_to_line(self) -> None:
        selected = self.lines.selected()
        if not selected:
            return
        line: UnusedLine = self._unused[int(selected[0])]
        self._page = line.page
        self._draw()

    # -- page ---------------------------------------------------------------------------------

    def _scale(self) -> float:
        return BASE_DPI * ZOOMS[self._zoom] / POINTS_PER_INCH

    def _render(self) -> PilImage | None:
        if self._pdf is None or not 1 <= self._page <= len(self._pdf.pages):
            return None
        key = (self._page, self._zoom)
        if key not in self._pages:
            page = self._pdf.pages[self._page - 1]
            rendered = page.to_image(resolution=BASE_DPI * ZOOMS[self._zoom]).original
            self._pages[key] = rendered.convert("RGBA")
        return self._pages[key]

    def _draw(self) -> None:
        image = self._render()
        self.canvas.delete("all")
        if image is None:
            return
        boxes = review_boxes(self._transactions(), self.host.session.categorizer, self.before.get())
        overlay = Image.new("RGBA", image.size, TRANSPARENT)
        _draw_boxes(ImageDraw.Draw(overlay), self._transactions(), boxes, self._page, self._scale())
        self._photo = ImageTk.PhotoImage(Image.alpha_composite(image, overlay))
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))
        pages = len(self._pdf.pages) if self._pdf else 0
        self.page_label.configure(text=f"Seite {self._page} / {pages}")
        self._outline_selection()

    def _outline_selection(self) -> None:
        self.canvas.delete(SELECTION_TAG)
        if self._selected is None:
            return
        placement = self._transactions()[self._selected].placement
        for region in placement.regions if placement else ():
            if region.page == self._page:
                box = to_target_box(region.bbox, self._scale(), SELECTION_PADDING)
                self.canvas.create_rectangle(
                    *box, outline=self.host.palette.outline, width=OUTLINE_WIDTH, tags=SELECTION_TAG
                )

    def _select(self, index: int) -> None:
        self._selected = index
        placement = self._transactions()[index].placement
        if placement is not None and placement.head.page != self._page:
            self._page = placement.head.page
            self._draw()
        else:
            self._outline_selection()
        self.bookings.show([str(index)])

    def _click(self, event: "tk.Event[tk.Canvas]") -> None:
        self.canvas.focus_set()  # so the keys 1–9 reach the canvas
        point = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        index = booking_at(self._transactions(), self._page, point, self._scale())
        if index is not None:
            self._select(index)

    def _turn(self, step: int) -> None:
        pages = len(self._pdf.pages) if self._pdf else 0
        if 1 <= self._page + step <= pages:
            self._page += step
            self._draw()

    def _zoom_by(self, step: int) -> None:
        self._zoom = min(max(self._zoom + step, 0), len(ZOOMS) - 1)
        self._draw()

    def _wheel(self, event: "tk.Event[tk.Canvas]") -> None:
        if isinstance(event.state, int) and event.state & CONTROL_MASK:
            self._zoom_by(1 if event.delta > 0 else -1)
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_digit(self, number: int, _event: object) -> None:
        names = self.host.session.catalog.names()
        if number <= len(names):
            self._assign(names[number - 1])

    def _assign(self, category: str) -> None:
        if self._selected is None:
            self.message.configure(text="Erst eine Buchung anklicken.")
            return
        txn = self._transactions()[self._selected]
        self.host.run(lambda: self.host.session.assign_to([txn], category))


def _draw_boxes(
    draw: ImageDraw.ImageDraw,
    transactions: tuple[Transaction, ...],
    boxes: list[ReviewBox],
    page: int,
    scale: float,
) -> None:
    """Translucent boxes in the category color; changed bookings get a dark outline."""
    for box in boxes:
        placement = transactions[box.index].placement
        fill = (*ImageColor.getrgb(box.color)[:3], FILL_ALPHA)
        outline = CHANGED_OUTLINE if box.changed else box.color
        for region in placement.regions if placement else ():
            if region.page == page:
                draw.rectangle(
                    to_target_box(region.bbox, scale),
                    fill=fill,
                    outline=outline,
                    width=OUTLINE_WIDTH if box.changed else THIN_OUTLINE,
                )
