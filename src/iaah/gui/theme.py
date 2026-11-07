"""Colors, fonts and ttk styles of the light and the dark theme (from the legacy app).

Widgets take every color and font from here; category colors come from the catalog and are
only tinted here for table rows.
"""

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Final

from iaah.charts.style import DARK as DARK_CHART
from iaah.charts.style import LIGHT as LIGHT_CHART
from iaah.charts.style import ChartTheme

FAMILY: Final = "Segoe UI"
SIZE: Final = 9
SMALL_SIZE: Final = 8
TITLE_SIZE: Final = 11
KPI_SIZE: Final = 15
FONT: Final = (FAMILY, SIZE)
FONT_BOLD: Final = (FAMILY, SIZE, "bold")
FONT_SMALL: Final = (FAMILY, SMALL_SIZE)
FONT_TITLE: Final = (FAMILY, TITLE_SIZE, "bold")
FONT_STATUS: Final = (FAMILY, TITLE_SIZE, "bold")
FONT_KPI: Final = (FAMILY, KPI_SIZE, "bold")
FONT_MONO: Final = ("Consolas", SIZE)
PAD: Final = 6
PAD_SMALL: Final = 3
PAD_LARGE: Final = 12
ROW_HEIGHT: Final = 24
SMALL_BUTTON: Final = 3  # characters: arrow and zoom buttons
TTK_THEME: Final = "clam"
RGB_MAX: Final = 255
HEX_DIGITS: Final = 2
HEX_BASE: Final = 16
CHANNELS: Final = 3
LUMINANCE: Final = (0.299, 0.587, 0.114)  # perceived brightness of r, g, b
DARK_TEXT_ABOVE: Final = 150.0  # brighter backgrounds get black text
BLACK: Final = "#000000"
WHITE: Final = "#ffffff"


@dataclass(frozen=True, slots=True)
class Palette:
    """One theme."""

    name: str
    bg: str
    card: str
    fg: str
    muted: str
    field: str  # entries, lists, tables
    selection: str
    tint_to: str  # category colors are mixed towards this for table rows
    tint: float  # how far (0–1)
    good: str
    bad: str
    warn: str
    outline: str  # selection frame on the review page
    chart: ChartTheme


LIGHT: Final = Palette(
    "light",
    "#f0f0f0",
    "#f3f5f7",
    "#222222",
    "#666666",
    "#ffffff",
    "#cfe3ff",
    "#ffffff",
    0.82,
    "#2e7d32",
    "#c62828",
    "#b26a00",
    "#000000",
    LIGHT_CHART,
)
DARK: Final = Palette(
    "dark",
    "#232629",
    "#2b2f33",
    "#e6e6e6",
    "#a0a0a0",
    "#2b2f33",
    "#37474f",
    "#2b2f33",
    0.72,
    "#66bb6a",
    "#ef5350",
    "#ffca28",
    "#ffffff",
    DARK_CHART,
)
PALETTES: Final = {LIGHT.name: LIGHT, DARK.name: DARK}


def apply(root: tk.Tk, palette: Palette) -> None:
    """Style every ttk widget and the classic Tk widgets for ``palette``."""
    style = ttk.Style(root)
    style.theme_use(TTK_THEME)
    _base(style, palette)
    _tables(style, palette)
    _classic(root, palette)


def _base(style: ttk.Style, palette: Palette) -> None:
    style.configure(
        ".",
        background=palette.bg,
        foreground=palette.fg,
        font=FONT,
        fieldbackground=palette.field,
        bordercolor=palette.muted,
    )
    style.configure("TNotebook", background=palette.bg)
    style.configure("TNotebook.Tab", background=palette.card, padding=(PAD_LARGE, PAD_SMALL))
    style.map("TNotebook.Tab", background=[("selected", palette.bg)])
    style.configure("Card.TFrame", background=palette.card)
    style.configure("Card.TLabel", background=palette.card)
    style.configure("Muted.TLabel", foreground=palette.muted)
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("Status.TLabel", font=FONT_STATUS)
    style.configure("Good.TLabel", foreground=palette.good)
    style.configure("Bad.TLabel", foreground=palette.bad)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.field)],
        foreground=[("readonly", palette.fg)],
    )
    for widget in ("TEntry", "TCombobox", "TSpinbox"):  # a visible text cursor in dark mode
        style.configure(widget, insertcolor=palette.fg)
    for widget in ("TRadiobutton", "TCheckbutton"):
        style.map(
            widget,
            background=[("disabled", palette.bg), ("active", palette.bg)],
            foreground=[("disabled", palette.muted)],
        )
    style.configure("Small.TButton", width=SMALL_BUTTON)


def _tables(style: ttk.Style, palette: Palette) -> None:
    style.configure(
        "Treeview",
        background=palette.field,
        fieldbackground=palette.field,
        foreground=palette.fg,
        rowheight=ROW_HEIGHT,
    )
    style.map(
        "Treeview",
        background=[("selected", palette.selection)],
        foreground=[("selected", palette.fg)],
    )
    style.configure(
        "Treeview.Heading", font=FONT_BOLD, background=palette.card, foreground=palette.fg
    )


def _classic(root: tk.Tk, palette: Palette) -> None:
    """Classic Tk widgets read the option database when they are created (the matplotlib
    toolbar recolors its icons from it); existing ones are restyled by hand."""
    root.configure(background=palette.bg)
    for pattern, value in _options(palette):
        root.option_add(pattern, value)
    _restyle(root, palette)


def _options(palette: Palette) -> tuple[tuple[str, str], ...]:
    return (
        ("*Listbox.background", palette.field),
        ("*Listbox.foreground", palette.fg),
        ("*Listbox.selectBackground", palette.selection),
        ("*Listbox.selectForeground", palette.fg),
        ("*Text.background", palette.field),
        ("*Text.foreground", palette.fg),
        ("*Text.insertBackground", palette.fg),
        ("*Menu.background", palette.card),
        ("*Menu.foreground", palette.fg),
        ("*Canvas.background", palette.bg),
        ("*Toplevel.background", palette.bg),
        ("*Frame.background", palette.bg),
        ("*Label.background", palette.bg),
        ("*Label.foreground", palette.fg),
        ("*Button.background", palette.card),
        ("*Button.foreground", palette.fg),
        ("*Button.activeBackground", palette.selection),
        ("*Checkbutton.background", palette.bg),
        ("*Checkbutton.foreground", palette.fg),
        ("*Checkbutton.selectColor", palette.selection),
    )


def _restyle(widget: tk.Misc, palette: Palette) -> None:
    """Recolor existing lists, texts and canvases (category swatches and buttons keep theirs)."""
    for child in widget.winfo_children():
        if isinstance(child, tk.Listbox):
            child.configure(
                background=palette.field,
                foreground=palette.fg,
                selectbackground=palette.selection,
                selectforeground=palette.fg,
            )
        elif isinstance(child, tk.Text):
            child.configure(background=palette.field, foreground=palette.fg)
        elif isinstance(child, tk.Canvas):
            child.configure(background=palette.bg)
        _restyle(child, palette)


def tint(color: str, palette: Palette) -> str:
    """A category color mixed towards the background – for table rows."""
    source, target = _rgb(color), _rgb(palette.tint_to)
    mixed = (round(s + (t - s) * palette.tint) for s, t in zip(source, target, strict=True))
    return _hex(tuple(mixed))


def text_on(color: str) -> str:
    """Black or white, whichever reads better on ``color``."""
    brightness = sum(w * c for w, c in zip(LUMINANCE, _rgb(color), strict=True))
    return BLACK if brightness > DARK_TEXT_ABOVE else WHITE


def _rgb(color: str) -> tuple[int, int, int]:
    digits = color.lstrip("#")
    starts = range(0, CHANNELS * HEX_DIGITS, HEX_DIGITS)
    red, green, blue = (int(digits[start : start + HEX_DIGITS], HEX_BASE) for start in starts)
    return red, green, blue


def _hex(rgb: tuple[int, ...]) -> str:
    return "#" + "".join(f"{min(max(value, 0), RGB_MAX):02x}" for value in rgb)
