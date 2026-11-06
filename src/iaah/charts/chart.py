"""What a chart builder returns, the chart kinds of the analysis tab and their German texts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from matplotlib.artist import Artist
from matplotlib.figure import Figure

from iaah.charts.style import ChartTheme, add_axes, new_figure, show_message, themed


class ChartKind(StrEnum):
    """The charts of the analysis tab, in menu order."""

    OVERVIEW = "overview"
    CATEGORIES = "categories"
    FLOW = "flow"
    COMPARISON = "comparison"
    TREND = "trend"
    STACKED = "stacked"
    YEARS = "years"
    FIXED_COSTS = "fixed_costs"
    BUDGET = "budget"
    MERCHANTS = "merchants"
    CALENDAR = "calendar"
    BALANCE = "balance"
    CUMULATIVE = "cumulative"


class DrillKind(StrEnum):
    """What a click on a chart element selects."""

    CATEGORY = "category"  # value: category name
    MERCHANT = "merchant"  # value: merchants.merchant_key
    DAY = "day"  # value: ISO date


@dataclass(frozen=True, slots=True)
class DrillTarget:
    """A clickable chart element; the GUI hit-tests ``artist.contains(event)``."""

    artist: Artist
    kind: DrillKind
    value: str


@dataclass(frozen=True, slots=True)
class Chart:
    """A built figure and its clickable elements."""

    figure: Figure
    targets: tuple[DrillTarget, ...] = ()


def message_chart(message: str, theme: ChartTheme) -> Chart:
    """A chart that only explains why there is nothing to draw."""
    with themed(theme):
        figure = new_figure()
        show_message(add_axes(figure, theme), message, theme)
    return Chart(figure)


TITLES: Final[dict[ChartKind, str]] = {
    ChartKind.OVERVIEW: "Überblick: Cashflow & Sparquote",
    ChartKind.CATEGORIES: "Ausgaben nach Kategorie",
    ChartKind.FLOW: "Geldfluss (Sankey)",
    ChartKind.COMPARISON: "Kategorie-Vergleich zur Vorperiode",
    ChartKind.TREND: "Kategorie-Entwicklung über Zeit",
    ChartKind.STACKED: "Ausgaben je Kategorie je Monat (gestapelt)",
    ChartKind.YEARS: "Jahresvergleich",
    ChartKind.FIXED_COSTS: "Fixkosten vs. variabel (Abos erkennen)",
    ChartKind.BUDGET: "Budget-Ampel",
    ChartKind.MERCHANTS: "Top-Empfänger",
    ChartKind.CALENDAR: "Kalender-Heatmap",
    ChartKind.BALANCE: "Echter Kontostand",
    ChartKind.CUMULATIVE: "Saldo-Verlauf (relativ)",
}

CAPTIONS: Final[dict[ChartKind, str]] = {
    ChartKind.OVERVIEW: (
        "Pro Monat des gewählten Zeitraums: grün = Einnahmen, rot = Ausgaben, die blaue Linie "
        "ist, was übrig bleibt (Netto). Die Prozentzahl ist die Sparquote. Ignorierte "
        "Kategorien (z. B. Umbuchungen) zählen nie mit."
    ),
    ChartKind.CATEGORIES: (
        "Wofür ist im gewählten Zeitraum das Geld geflossen? Jeder Ring-Abschnitt ist eine "
        "Kategorie, in der Mitte stehen die Gesamtausgaben. Erstattungen mindern ihre "
        "Kategorie. Klick auf einen Abschnitt zeigt die Buchungen."
    ),
    ChartKind.FLOW: (
        "Wohin fließen die Einnahmen des gewählten Zeitraums? Von links verzweigen die Ströme "
        "zu den Ausgabe-Kategorien und zum gesparten Rest. Die Breite eines Stroms entspricht "
        "dem Betrag."
    ),
    ChartKind.COMPARISON: (
        "Jede Kategorie im gewählten Monat oder Jahr (farbig) neben dem Zeitraum davor (grau), "
        "z. B. Juli neben Juni. Zeigt sofort, wo du mehr oder weniger ausgegeben hast."
    ),
    ChartKind.TREND: (
        "Monatliche Ausgaben der fünf größten Kategorien des gewählten Zeitraums. Steigende "
        "Linien = wachsende Ausgaben. Am besten mit einem ganzen Jahr oder dem gesamten Zeitraum."
    ),
    ChartKind.STACKED: (
        "Ausgaben je Monat des gewählten Zeitraums, aufgeteilt nach Kategorie. Die Balkenhöhe "
        "ist die Monatssumme – ideal, um Ausreißer-Monate und ihre Ursache zu finden."
    ),
    ChartKind.YEARS: (
        "Monatsausgaben aller geladenen Jahre übereinander (eine Linie je Jahr, Januar bis "
        "Dezember), unabhängig vom gewählten Zeitraum. Braucht Auszüge aus mindestens zwei Jahren."
    ),
    ChartKind.FIXED_COSTS: (
        "Trennt im gewählten Zeitraum feste, wiederkehrende Zahlungen (gleicher Empfänger in "
        "mehreren Monaten, ähnlicher Betrag – Miete, Abos, Versicherungen) von variablen "
        "Ausgaben. Rechts die erkannten Zahlungen mit Monatsbetrag. Braucht mindestens zwei Monate."
    ),
    ChartKind.BUDGET: (
        "Monatsbudgets je Kategorie, hochgerechnet auf die Monate des gewählten Zeitraums: grün "
        "= im Rahmen, gelb = über 80 %, rot = überzogen. Budgets legst du im Tab „Budgets“ fest."
    ),
    ChartKind.MERCHANTS: (
        "Die Empfänger, an die im gewählten Zeitraum am meisten Geld ging – unabhängig von der "
        "Kategorie. Zahlungen über PayPal oder Karte zählen beim eigentlichen Händler."
    ),
    ChartKind.CALENDAR: (
        "Jeder Tag des gewählten Zeitraums ein Kästchen, je dunkler, desto höher die Ausgaben "
        "(ohne Abzug von Erstattungen). Zeigt Muster wie teure Wochenenden oder Monatsanfänge."
    ),
    ChartKind.BALANCE: (
        "Der tatsächliche Kontostand laut den Auszügen des gewählten Zeitraums: alter Saldo "
        "plus Buchungen, je Konto eine Linie. CSV-Exporte nennen keinen Saldo und fehlen hier."
    ),
    ChartKind.CUMULATIVE: (
        "Summe aller Buchungen ab dem ersten Tag des gewählten Zeitraums. Steigt die Kurve, "
        "legst du Geld zurück; fällt sie, gibst du mehr aus, als hereinkommt."
    ),
}
