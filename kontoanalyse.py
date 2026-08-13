"""Kontoanalyse - GUI zum Einlesen und Auswerten von Girokonto-Kontoauszuegen.

Features
--------
* Ein oder mehrere Kontoauszug-PDFs (ING-DiBa) laden - auch ein ganzes Jahr.
* Buchungen werden automatisch nach gespeicherten Regeln Kategorien zugeordnet.
* Manuelles Zuordnen per Rechtsklick oder Auswahl + Button.
* Einmal zugeordnete Empfaenger werden als Regel in settings.json gespeichert
  und beim naechsten Auszug automatisch wiedererkannt.
* Auswertung mit sinnvollen Graphen (Kuchen, Balken je Monat, gestapelt, Verlauf).

Start:  python kontoanalyse.py
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from collections import defaultdict
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import (  # noqa: E402
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.figure import Figure  # noqa: E402

from parser import Transaction, parse_pdf  # noqa: E402

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "settings.json")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data.json")
UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ui_state.json")
UNASSIGNED = "Nicht zugeordnet"
INCOME_CAT = "Einkommen"
SCHEMA_VERSION = 2


def atomic_write_json(path: str, data) -> None:
    """Schreibt JSON sicher: erst in Temp-Datei, Backup der alten, dann ersetzen.

    Verhindert Datenverlust, falls das Programm mitten im Schreiben abstuerzt.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        try:
            bak = f"{path}.bak"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(path, bak)
        except OSError:
            pass
    os.replace(tmp, path)

# ---------------------------------------------------------------------------
# Standard-Kategorien (Name -> Farbe) und ein paar Start-Regeln fuer typische
# deutsche Haendler. Alles ist spaeter im Tab "Kategorien & Regeln" editierbar.
# ---------------------------------------------------------------------------
DEFAULT_CATEGORIES = [
    {"name": "Einkommen",      "color": "#2e7d32"},
    {"name": "Miete & Wohnen", "color": "#6d4c41"},
    {"name": "Lebensmittel",   "color": "#43a047"},
    {"name": "Restaurant/Cafe","color": "#fb8c00"},
    {"name": "Transport",      "color": "#1e88e5"},
    {"name": "Versicherung",   "color": "#8e24aa"},
    {"name": "Abonnements",    "color": "#d81b60"},
    {"name": "Freizeit",       "color": "#00acc1"},
    {"name": "Shopping",       "color": "#5e35b1"},
    {"name": "Gesundheit",     "color": "#e53935"},
    {"name": "Bargeld",        "color": "#757575"},
    {"name": "Sparen/Anlage",  "color": "#00897b"},
    {"name": "Sonstiges",      "color": "#546e7a"},
    {"name": UNASSIGNED,       "color": "#bdbdbd"},
]

# Farbvorschlaege fuer neue Kategorien (gut unterscheidbar).
CATEGORY_PALETTE = [
    "#5e35b1", "#00897b", "#f4511e", "#3949ab", "#c0ca33", "#00acc1",
    "#8e24aa", "#7cb342", "#fb8c00", "#039be5", "#d81b60", "#6d4c41",
    "#43a047", "#e53935", "#1e88e5", "#fdd835", "#546e7a", "#ad1457",
]

DEFAULT_RULES = [
    {"keyword": "REWE", "category": "Lebensmittel"},
    {"keyword": "ALDI", "category": "Lebensmittel"},
    {"keyword": "LIDL", "category": "Lebensmittel"},
    {"keyword": "EDEKA", "category": "Lebensmittel"},
    {"keyword": "PENNY", "category": "Lebensmittel"},
    {"keyword": "KAUFLAND", "category": "Lebensmittel"},
    {"keyword": "BIOMARKT", "category": "Lebensmittel"},
    {"keyword": "DENN S", "category": "Lebensmittel"},
    {"keyword": "SCHAEFERS", "category": "Restaurant/Cafe"},
    {"keyword": "BAECKER", "category": "Restaurant/Cafe"},
    {"keyword": "DM ", "category": "Gesundheit"},
    {"keyword": "ROSSMANN", "category": "Gesundheit"},
    {"keyword": "APOTHEKE", "category": "Gesundheit"},
    {"keyword": "DB VERTRIEB", "category": "Transport"},
    {"keyword": "DEUTSCHE BAHN", "category": "Transport"},
    {"keyword": "TANKSTELLE", "category": "Transport"},
    {"keyword": "ARAL", "category": "Transport"},
    {"keyword": "SHELL", "category": "Transport"},
    {"keyword": "NETFLIX", "category": "Abonnements"},
    {"keyword": "SPOTIFY", "category": "Abonnements"},
    {"keyword": "AMAZON PRIME", "category": "Abonnements"},
    {"keyword": "VERS", "category": "Versicherung"},
    {"keyword": "MIETE", "category": "Miete & Wohnen"},
    {"keyword": "GEHALT", "category": "Einkommen"},
]


# ---------------------------------------------------------------------------
# Diagrammtypen + erklaerende Bildunterschriften (Kernstueck der Auswertung)
# ---------------------------------------------------------------------------
CHART_OVERVIEW = "Überblick: Cashflow & Sparquote"
CHART_PIE = "Ausgaben nach Kategorie"
CHART_COMPARE = "Kategorie-Vergleich zur Vorperiode"
CHART_TREND = "Kategorie-Entwicklung über Zeit"
CHART_STACKED = "Ausgaben je Kategorie je Monat (gestapelt)"
CHART_RECURRING = "Fixkosten vs. variabel (Abos erkennen)"
CHART_TOP = "Top-Empfänger"
CHART_BALANCE = "Saldo-Verlauf (relativ)"
CHART_REAL_BALANCE = "Echter Kontostand"
CHART_BUDGET = "Budget-Ampel"

CHART_TYPES = [CHART_OVERVIEW, CHART_PIE, CHART_COMPARE, CHART_TREND,
               CHART_STACKED, CHART_RECURRING, CHART_BUDGET, CHART_TOP,
               CHART_REAL_BALANCE, CHART_BALANCE]

CHART_CAPTIONS = {
    CHART_OVERVIEW:
        "Pro Monat: grün = Einnahmen, rot = Ausgaben, die blaue Linie ist was "
        "übrig bleibt (Netto). Die Prozentzahl ist deine Sparquote. Auf einen "
        "Blick: Nimmst du Monat für Monat mehr ein als du ausgibst?",
    CHART_PIE:
        "Wofür ist im gewählten Zeitraum das Geld geflossen? Jeder Ring-"
        "Abschnitt ist eine Kategorie, in der Mitte stehen die Gesamtausgaben. "
        "Am aussagekräftigsten für einen einzelnen Monat.",
    CHART_COMPARE:
        "Vergleicht jede Kategorie mit dem vorherigen Zeitraum (z. B. Juli vs. "
        "Juni). Farbig = aktuell, grau = Vorperiode. Zeigt sofort, wo du mehr "
        "oder weniger ausgegeben hast. Zeitraum: einzelner Monat oder Jahr.",
    CHART_TREND:
        "Entwicklung der 5 größten Kategorien über mehrere Monate. Steigende "
        "Linien = wachsende Ausgaben. Am besten mit Zeitraum „Alle“ oder einem "
        "ganzen Jahr.",
    CHART_STACKED:
        "Gesamtausgaben je Monat, aufgeschlüsselt nach Kategorie (Farbe). Die "
        "Balkenhöhe ist die Monatssumme – ideal, um Ausreißer-Monate und deren "
        "Ursache zu erkennen.",
    CHART_RECURRING:
        "Trennt feste, wiederkehrende Zahlungen (Miete, Abos, Versicherungen – "
        "Empfänger, die in mehreren Monaten auftauchen) von variablen Ausgaben. "
        "Rechts die erkannten Abos mit monatlichem Betrag. Braucht ≥ 2 Monate.",
    CHART_TOP:
        "Die Empfänger, an die im Zeitraum am meisten Geld ging – unabhängig "
        "von der Kategorie. Deckt einzelne große Kostenverursacher auf.",
    CHART_BALANCE:
        "Kumulierter Verlauf von Einnahmen minus Ausgaben ab dem ersten "
        "geladenen Tag. Steigt die Kurve, legst du Geld zurück; fällt sie, gibst "
        "du mehr aus als reinkommt.",
    CHART_REAL_BALANCE:
        "Der tatsächliche Kontostand aus dem Auszug (Alter Saldo + Buchungen). "
        "Zeigt den echten Verlauf deines Guthabens – je Konto eine Linie.",
    CHART_BUDGET:
        "Deine Monatsbudgets je Kategorie als Ampel: grün = im Rahmen, gelb = "
        "fast erreicht, rot = überzogen. Budgets legst du im Tab „Budgets“ fest. "
        "Am aussagekräftigsten für einen einzelnen Monat.",
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def eur(value: float) -> str:
    """1234.5 -> '1.234,50 EUR' (deutsches Format)."""
    s = f"{abs(value):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    sign = "-" if value < 0 else ""
    return f"{sign}{s} €"


# Bekannte Woerter, in denen der ING-Font den Umlaut als "�" ausgibt.
_UMLAUT_FIXES = {
    "Echtzeit�berweisung": "Echtzeitüberweisung",
    "�berweisung": "Überweisung",
    "f�r": "für", "Geb�hr": "Gebühr", "Geb�hren": "Gebühren",
    "zur�ck": "zurück", "R�ck": "Rück", "verg�tung": "vergütung",
    "M�ller": "Müller", "K�ln": "Köln", "M�nchen": "München",
    "Gesch�ft": "Geschäft", "H�ndler": "Händler", "Geb�ude": "Gebäude",
}


def clean_display(text: str) -> str:
    """Kaputte Umlaute aus dem PDF-Font fuer die Anzeige gerade ruecken.

    Nur bekannte Woerter werden ersetzt; unbekannte "�" bleiben stehen, damit
    nicht faelschlich ue fuer oe/ae/ss eingesetzt wird.
    """
    for bad, good in _UMLAUT_FIXES.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


class Store:
    """Verwaltet settings.json: Kategorien, Regeln und manuelle Zuordnungen."""

    def __init__(self, path: str = SETTINGS_FILE):
        self.path = path
        self.categories: list[dict] = []
        self.rules: list[dict] = []
        self.overrides: dict = {}          # key -> str ODER Liste von Splits
        self.budgets: dict = {}            # kategorie -> Monatsbudget (float)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.categories = data.get("categories") or list(DEFAULT_CATEGORIES)
                self.rules = data.get("rules") or []
                self.overrides = data.get("overrides") or {}
                self.budgets = data.get("budgets") or {}
                return
            except (json.JSONDecodeError, OSError):
                pass
        # Erststart: falls vorhanden aus der committbaren Vorlage seeden,
        # sonst aus den Code-Standardwerten.
        example = os.path.join(os.path.dirname(self.path), "settings.example.json")
        if os.path.exists(example):
            try:
                with open(example, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.categories = data.get("categories") or list(DEFAULT_CATEGORIES)
                self.rules = data.get("rules") or list(DEFAULT_RULES)
                self.overrides = {}
                self.budgets = {}
                self.save()
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.categories = list(DEFAULT_CATEGORIES)
        self.rules = list(DEFAULT_RULES)
        self.overrides = {}
        self.budgets = {}
        self.save()

    def save(self):
        data = {
            "version": SCHEMA_VERSION,
            "categories": self.categories,
            "rules": self.rules,
            "budgets": self.budgets,
            "overrides": self.overrides,
        }
        atomic_write_json(self.path, data)

    # -- Kategorien -------------------------------------------------------
    def category_names(self) -> list[str]:
        return [c["name"] for c in self.categories]

    def color_of(self, name: str) -> str:
        for c in self.categories:
            if c["name"] == name:
                return c["color"]
        return "#bdbdbd"

    def add_category(self, name: str, color: str):
        if name and name not in self.category_names():
            self.categories.insert(len(self.categories) - 1,
                                   {"name": name, "color": color})
            self.save()

    def remove_category(self, name: str):
        if name in (UNASSIGNED, INCOME_CAT):
            return
        self.categories = [c for c in self.categories if c["name"] != name]
        self.rules = [r for r in self.rules if r["category"] != name]
        self.overrides = {k: v for k, v in self.overrides.items()
                          if not _override_uses(v, name)}
        self.budgets.pop(name, None)
        self.save()

    def is_excluded(self, name: str) -> bool:
        """True fuer Kategorien, die nicht als Einnahme/Ausgabe zaehlen
        (interne Umbuchungen aufs eigene Sparkonto o. ae.)."""
        for c in self.categories:
            if c["name"] == name:
                return bool(c.get("exclude"))
        return False

    def set_excluded(self, name: str, value: bool):
        for c in self.categories:
            if c["name"] == name:
                c["exclude"] = bool(value)
        self.save()

    # -- Budgets ----------------------------------------------------------
    def get_budget(self, name: str):
        return self.budgets.get(name)

    def set_budget(self, name: str, amount):
        if amount is None or amount <= 0:
            self.budgets.pop(name, None)
        else:
            self.budgets[name] = float(amount)
        self.save()

    # -- Regeln -----------------------------------------------------------
    def add_rule(self, keyword: str, category: str, regex: bool = False,
                 amount_min=None, amount_max=None):
        keyword = keyword.strip()
        if not keyword:
            return
        rule = {"keyword": keyword, "category": category}
        if regex:
            rule["regex"] = True
        if amount_min is not None:
            rule["min"] = float(amount_min)
        if amount_max is not None:
            rule["max"] = float(amount_max)
        # bestehende Regel mit gleichem Stichwort (+ Regex-Flag) aktualisieren
        for i, r in enumerate(self.rules):
            if r["keyword"].upper() == keyword.upper() and \
                    bool(r.get("regex")) == regex:
                self.rules[i] = rule
                self.save()
                return
        self.rules.append(rule)
        self.save()

    def remove_rule(self, keyword: str):
        self.rules = [r for r in self.rules
                      if r["keyword"].upper() != keyword.upper()]
        self.save()

    def _rule_matches(self, r: dict, t: Transaction) -> bool:
        amt = abs(t.betrag)
        if r.get("min") is not None and amt < r["min"]:
            return False
        if r.get("max") is not None and amt > r["max"]:
            return False
        kw = r["keyword"]
        if r.get("regex"):
            try:
                return re.search(kw, t.match_text, re.IGNORECASE) is not None
            except re.error:
                return False
        return kw.upper() in t.match_text

    # -- Zuordnung --------------------------------------------------------
    def _rule_category(self, t: Transaction):
        """Kategorie der spezifischsten passenden Regel (laengstes Stichwort)."""
        best, best_len = None, -1
        for r in self.rules:
            if self._rule_matches(r, t) and len(r["keyword"]) > best_len:
                best, best_len = r["category"], len(r["keyword"])
        return best

    def categorize(self, t: Transaction) -> str:
        """Primaerkategorie (fuer Tabelle/Anzeige)."""
        ov = self.overrides.get(t.key)
        if isinstance(ov, list) and ov:
            return "Aufgeteilt" if len(ov) > 1 else ov[0].get("category", UNASSIGNED)
        if isinstance(ov, str):
            return ov
        cat = self._rule_category(t)
        if cat:
            return cat
        if t.betrag > 0:
            return INCOME_CAT
        return UNASSIGNED

    def parts(self, t: Transaction):
        """Liste (kategorie, betrag) – beruecksichtigt aufgeteilte Buchungen."""
        ov = self.overrides.get(t.key)
        if isinstance(ov, list) and ov:
            return [(p.get("category", UNASSIGNED), float(p.get("betrag", 0.0)))
                    for p in ov]
        return [(self.categorize(t), t.betrag)]

    def set_override(self, t: Transaction, category: str):
        self.overrides[t.key] = category
        self.save()

    def set_split(self, t: Transaction, splits: list):
        """splits = Liste von {'category':..., 'betrag':...} (Vorzeichen wie Buchung)."""
        self.overrides[t.key] = splits
        self.save()

    def clear_override(self, t: Transaction):
        self.overrides.pop(t.key, None)
        self.save()


def _override_uses(value, name: str) -> bool:
    """Ob ein Override-Wert (str oder Split-Liste) eine Kategorie verwendet."""
    if isinstance(value, list):
        return any(p.get("category") == name for p in value)
    return value == name


# ---------------------------------------------------------------------------
# Haupt-Anwendung
# ---------------------------------------------------------------------------
class KontoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kontoanalyse")
        self.geometry("1250x780")
        self.minsize(1000, 640)

        self.store = Store()
        self.transactions: list[Transaction] = []
        self._seen: set[tuple] = set()          # Dedupe
        self.loaded_files: list[str] = []
        self.statements: list[dict] = []        # Auszugs-Metadaten (Saldo etc.)
        self._undo_stack: list = []             # fuer Undo von Zuordnungen

        self._build_style()
        self._build_menu()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._build_tab_transactions()
        self._build_tab_analysis()
        self._build_tab_budgets()
        self._build_tab_settings()

        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())
        self._refresh_category_widgets()
        self._load_data()                 # zuletzt gespeicherte Buchungen laden
        self._rebuild_month_filters()
        self._load_ui_state()             # Fenstergroesse + letzte Filter
        self.refresh_table()
        self._update_status()

        self.bind_all("<Control-z>", lambda e: self.undo_assignment())
        for n in range(1, 10):
            self.bind(f"<Key-{n}>", self._on_number_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- Style ----------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Big.TLabel", font=("Segoe UI", 11, "bold"))

    def _build_menu(self):
        m = tk.Menu(self)
        filem = tk.Menu(m, tearoff=0)
        filem.add_command(label="PDF(s) laden…", command=self.load_pdfs)
        filem.add_command(label="Ordner laden…", command=self.load_folder)
        filem.add_separator()
        exp = tk.Menu(filem, tearoff=0)
        exp.add_command(label="Buchungen als CSV…", command=self.export_csv)
        exp.add_command(label="Buchungen als Excel…", command=self.export_excel)
        exp.add_command(label="Monats-/Jahresreport als PDF…", command=self.export_report)
        filem.add_cascade(label="Exportieren", menu=exp)
        filem.add_separator()
        filem.add_command(label="Geladene Auszüge zurücksetzen",
                          command=self.reset_transactions)
        filem.add_separator()
        filem.add_command(label="Beenden", command=self._on_close)
        m.add_cascade(label="Datei", menu=filem)
        self.config(menu=m)

    # ---- Tab 1: Transaktionen ------------------------------------------
    def _build_tab_transactions(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Transaktionen  ")

        # Toolbar
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Button(bar, text="PDF(s) laden", command=self.load_pdfs).pack(side="left")
        ttk.Button(bar, text="Ordner laden", command=self.load_folder).pack(side="left", padx=(6, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Monat:").pack(side="left")
        self.filter_month = ttk.Combobox(bar, width=12, state="readonly", values=["Alle"])
        self.filter_month.set("Alle")
        self.filter_month.pack(side="left", padx=(3, 10))
        self.filter_month.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        ttk.Label(bar, text="Kategorie:").pack(side="left")
        self.filter_cat = ttk.Combobox(bar, width=18, state="readonly", values=["Alle"])
        self.filter_cat.set("Alle")
        self.filter_cat.pack(side="left", padx=(3, 10))
        self.filter_cat.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        ttk.Label(bar, text="Suche:").pack(side="left")
        self.search_var = tk.StringVar()
        se = ttk.Entry(bar, textvariable=self.search_var, width=20)
        se.pack(side="left", padx=(3, 8))
        self.search_var.trace_add("write", lambda *a: self.refresh_table())

        # zweite Filterzeile
        bar2 = ttk.Frame(tab)
        bar2.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(bar2, text="Konto:").pack(side="left")
        self.filter_konto = ttk.Combobox(bar2, width=14, state="readonly", values=["Alle"])
        self.filter_konto.set("Alle")
        self.filter_konto.pack(side="left", padx=(3, 10))
        self.filter_konto.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        ttk.Label(bar2, text="Typ:").pack(side="left")
        self.filter_type = ttk.Combobox(bar2, width=12, state="readonly",
                                        values=["Alle", "Nur Ausgaben", "Nur Einnahmen"])
        self.filter_type.set("Alle")
        self.filter_type.pack(side="left", padx=(3, 10))
        self.filter_type.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        ttk.Label(bar2, text="Betrag von").pack(side="left")
        self.filter_min = tk.StringVar()
        ttk.Entry(bar2, textvariable=self.filter_min, width=8).pack(side="left", padx=3)
        ttk.Label(bar2, text="bis").pack(side="left")
        self.filter_max = tk.StringVar()
        ttk.Entry(bar2, textvariable=self.filter_max, width=8).pack(side="left", padx=3)
        self.filter_min.trace_add("write", lambda *a: self.refresh_table())
        self.filter_max.trace_add("write", lambda *a: self.refresh_table())
        ttk.Button(bar2, text="Filter zurücksetzen",
                   command=self._reset_filters).pack(side="left", padx=(10, 0))
        ttk.Button(bar2, text="Nächste offene ▶", command=self._focus_next_unassigned
                   ).pack(side="right")

        # Tabelle
        cols = ("datum", "art", "empfaenger", "zweck", "betrag", "kategorie")
        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True, padx=8)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        headings = {
            "datum": ("Datum", 90), "art": ("Buchungsart", 130),
            "empfaenger": ("Empfänger", 250), "zweck": ("Verwendungszweck", 300),
            "betrag": ("Betrag", 110), "kategorie": ("Kategorie", 150),
        }
        for c, (txt, w) in headings.items():
            self.tree.heading(c, text=txt, command=lambda cc=c: self._sort_by(cc))
            anchor = "e" if c == "betrag" else "w"
            self.tree.column(c, width=w, anchor=anchor,
                             stretch=(c in ("empfaenger", "zweck")))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._sort_state = {}

        # Kontextmenue + Inline-Bearbeitung
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Double-1>", self._on_tree_double)

        # untere Leiste: zuordnen
        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Label(bottom, text="Kategorie zuweisen:").pack(side="left")
        self.assign_cat = ttk.Combobox(bottom, width=20, state="readonly")
        self.assign_cat.pack(side="left", padx=(4, 3))
        ttk.Button(bottom, text="＋ Neu", width=6,
                   command=self._quick_add_category).pack(side="left", padx=(0, 6))
        self.remember_rule = tk.BooleanVar(value=True)
        ttk.Button(bottom, text="Zuordnen", command=self._assign_selected).pack(side="left")
        ttk.Checkbutton(bottom, text="Als Regel merken (Empfänger)",
                        variable=self.remember_rule).pack(side="left", padx=(8, 0))
        self.status = ttk.Label(bottom, text="", style="Big.TLabel")
        self.status.pack(side="right")

    # ---- Tab 2: Auswertung ---------------------------------------------
    def _build_tab_analysis(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Auswertung  ")

        ctrl = ttk.Frame(tab)
        ctrl.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(ctrl, text="Zeitraum:").pack(side="left")
        self.chart_month = ttk.Combobox(ctrl, width=12, state="readonly", values=["Alle"])
        self.chart_month.set("Alle")
        self.chart_month.pack(side="left", padx=(4, 14))
        self.chart_month.bind("<<ComboboxSelected>>", lambda e: self.draw_chart())
        ttk.Label(ctrl, text="Diagramm:").pack(side="left")
        self.chart_type = ttk.Combobox(ctrl, width=42, state="readonly", values=list(CHART_TYPES))
        self.chart_type.current(0)
        self.chart_type.pack(side="left", padx=(4, 12))
        self.chart_type.bind("<<ComboboxSelected>>", lambda e: self.draw_chart())
        ttk.Button(ctrl, text="Aktualisieren", command=self.draw_chart).pack(side="left")

        # KPI-Kacheln mit Vergleich zur Vorperiode
        self.kpi_frame = ttk.Frame(tab)
        self.kpi_frame.pack(fill="x", padx=6, pady=6)
        self.kpi_cards = {}
        for key, title in [("income", "Einnahmen"), ("expense", "Ausgaben"),
                           ("net", "Netto gespart"), ("rate", "Sparquote"),
                           ("avg", "Ø Ausgaben / Monat")]:
            self.kpi_cards[key] = self._make_kpi_card(self.kpi_frame, title)

        self.fig = Figure(figsize=(9, 4.6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=(0, 2))
        self._drill = []
        self.canvas.mpl_connect("button_press_event", self._on_chart_click)

        self.chart_caption = tk.Label(tab, text="", justify="left", anchor="w",
                                      wraplength=1150, fg="#555",
                                      font=("Segoe UI", 9))
        self.chart_caption.pack(fill="x", padx=12, pady=(0, 2))
        NavigationToolbar2Tk(self.canvas, tab).update()

    def _make_kpi_card(self, parent, title):
        card = tk.Frame(parent, bg="#f3f5f7", bd=1, relief="solid")
        card.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(card, text=title, bg="#f3f5f7", fg="#667",
                 font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(6, 0))
        val = tk.Label(card, text="–", bg="#f3f5f7", fg="#222",
                       font=("Segoe UI", 15, "bold"))
        val.pack(anchor="w", padx=10)
        delta = tk.Label(card, text="", bg="#f3f5f7", fg="#888",
                         font=("Segoe UI", 8))
        delta.pack(anchor="w", padx=10, pady=(0, 6))
        return {"value": val, "delta": delta}

    # ---- Tab 3: Kategorien & Regeln ------------------------------------
    def _build_tab_settings(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Kategorien & Regeln  ")

        left = ttk.LabelFrame(tab, text="Kategorien")
        left.pack(side="left", fill="both", expand=False, padx=8, pady=8)
        self.cat_list = tk.Listbox(left, width=26, height=18, font=("Segoe UI", 10))
        self.cat_list.pack(padx=6, pady=6, fill="both", expand=True)
        self.cat_list.bind("<<ListboxSelect>>", lambda e: None)
        cbtn = ttk.Frame(left)
        cbtn.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(cbtn, text="Neu…", command=self._add_category_dialog).pack(side="left")
        ttk.Button(cbtn, text="Farbe…", command=self._recolor_category).pack(side="left", padx=4)
        ttk.Button(cbtn, text="Löschen", command=self._delete_category).pack(side="left")
        ttk.Button(left, text="Als interne Umbuchung an/aus",
                   command=self._toggle_exclude).pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(left, text="Interne Umbuchungen (z. B. aufs eigene Sparkonto)\n"
                             "zählen nicht als Einnahme/Ausgabe.  Mit ⊘ markiert.",
                  foreground="#666", font=("Segoe UI", 8), justify="left").pack(
            anchor="w", padx=6, pady=(0, 6))

        right = ttk.LabelFrame(tab, text="Regeln  (Stichwort  →  Kategorie)")
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.rule_tree = ttk.Treeview(right, columns=("kw", "cat"), show="headings", height=16)
        self.rule_tree.heading("kw", text="Stichwort (im Empfänger/Zweck)")
        self.rule_tree.heading("cat", text="Kategorie")
        self.rule_tree.column("kw", width=280)
        self.rule_tree.column("cat", width=180)
        self.rule_tree.pack(fill="both", expand=True, padx=6, pady=6)
        rbtn = ttk.Frame(right)
        rbtn.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(rbtn, text="Regel hinzufügen…", command=self._add_rule_dialog).pack(side="left")
        ttk.Button(rbtn, text="Regel löschen", command=self._delete_rule).pack(side="left", padx=4)
        ttk.Label(right, text="Tipp: Zuordnungen im Tab „Transaktionen“ erzeugen "
                              "solche Regeln automatisch. Regeln können auch Regex "
                              "und Betragsgrenzen haben (Regel hinzufügen…).",
                  foreground="#666", wraplength=380, justify="left").pack(
            anchor="w", padx=6, pady=(0, 6))

    # ---- Tab: Budgets --------------------------------------------------
    def _build_tab_budgets(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Budgets  ")
        ttk.Label(tab, text="Monatsbudget je Kategorie (leer/0 = keins). Die "
                            "„Budget-Ampel“ im Tab „Auswertung“ nutzt diese Werte.",
                  foreground="#555").pack(anchor="w", padx=12, pady=(10, 2))
        head = ttk.Frame(tab)
        head.pack(fill="x", padx=12)
        ttk.Label(head, text="Kategorie", width=24, font=("Segoe UI", 9, "bold")
                  ).pack(side="left")
        ttk.Label(head, text="Budget €/Monat", width=16, font=("Segoe UI", 9, "bold")
                  ).pack(side="left")
        ttk.Label(head, text="Ø Ist €/Monat", font=("Segoe UI", 9, "bold")
                  ).pack(side="left")
        self.budget_rows = ttk.Frame(tab)
        self.budget_rows.pack(fill="both", expand=True, padx=12, pady=4)
        self.budget_vars = {}
        ttk.Button(tab, text="Budgets speichern",
                   command=self._save_budgets).pack(pady=8)
        self._refresh_budget_tab()

    def _refresh_budget_tab(self):
        if not hasattr(self, "budget_rows"):
            return
        for w in self.budget_rows.winfo_children():
            w.destroy()
        self.budget_vars = {}
        totals = self._cat_expense_totals(self.transactions)
        nmonths = len(self._months()) or 1
        for c in self.store.categories:
            name = c["name"]
            if name in (INCOME_CAT, UNASSIGNED) or c.get("exclude"):
                continue
            row = ttk.Frame(self.budget_rows)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, width=24, anchor="w",
                     bg=self._tint(c["color"])).pack(side="left")
            b = self.store.get_budget(name)
            var = tk.StringVar(value=("" if not b else f"{b:.0f}"))
            ttk.Entry(row, textvariable=var, width=16).pack(side="left", padx=2)
            avg = totals.get(name, 0) / nmonths
            ttk.Label(row, text=eur(avg), foreground="#888").pack(side="left", padx=6)
            self.budget_vars[name] = var

    def _save_budgets(self):
        for name, var in self.budget_vars.items():
            try:
                val = float(var.get().replace(",", ".").strip()) if var.get().strip() else 0
            except ValueError:
                val = 0
            self.store.set_budget(name, val)
        messagebox.showinfo("Budgets", "Budgets gespeichert.")
        self.draw_chart()

    # ================================================================
    # Laden
    # ================================================================
    def load_pdfs(self):
        paths = filedialog.askopenfilenames(
            title="Kontoauszug-PDF(s) wählen",
            filetypes=[("PDF-Dateien", "*.pdf"), ("Alle Dateien", "*.*")])
        if paths:
            self._ingest(paths)

    def load_folder(self):
        folder = filedialog.askdirectory(title="Ordner mit Kontoauszügen wählen")
        if not folder:
            return
        paths = [os.path.join(folder, f) for f in os.listdir(folder)
                 if f.lower().endswith(".pdf")]
        if not paths:
            messagebox.showinfo("Kontoanalyse", "Keine PDF-Dateien im Ordner gefunden.")
            return
        self._ingest(sorted(paths))

    def _ingest(self, paths):
        added = files = errors = 0
        err_msgs, warn_msgs = [], []
        for p in paths:
            try:
                stmt = parse_pdf(p)
            except Exception as ex:  # noqa: BLE001
                errors += 1
                err_msgs.append(f"{os.path.basename(p)}: {ex}")
                continue
            if not stmt.transactions:
                warn_msgs.append(f"{stmt.quelle}: keine Buchungen erkannt "
                                 "(anderes PDF-Format?)")
                continue
            files += 1
            if stmt.quelle not in self.loaded_files:
                self.loaded_files.append(stmt.quelle)
            # Reconciliation-Check (Buchungssumme vs. Saldodifferenz)
            if stmt.reconciles is False:
                diff = (stmt.alter_saldo + stmt.summe) - stmt.neuer_saldo
                warn_msgs.append(f"{stmt.quelle}: Saldo stimmt nicht "
                                 f"(Differenz {eur(diff)}) – evtl. Buchung übersehen.")
            self._remember_statement(stmt)
            for t in stmt.transactions:
                sig = (t.datum, round(t.betrag, 2), t.empfaenger, t.zweck)
                if sig in self._seen:
                    continue
                self._seen.add(sig)
                t.kategorie = self.store.categorize(t)
                self.transactions.append(t)
                added += 1
        self.transactions.sort(key=lambda x: (x.datum, x.empfaenger))
        self._save_data()                 # dauerhaft sichern
        self._rebuild_month_filters()
        self.refresh_table()
        self.draw_chart()
        self._update_status()
        gaps = self._missing_months()
        msg = (f"{files} Datei(en) verarbeitet, {added} neue Buchungen hinzugefügt.\n"
               f"Gesamt gespeichert: {len(self.transactions)} Buchungen "
               f"aus {len(self._months())} Monat(en).")
        if added == 0 and files:
            msg += "\n\n(Diese Auszüge waren bereits geladen – nichts Neues.)"
        if gaps:
            msg += "\n\nFehlende Monate in der Reihe: " + ", ".join(gaps)
        if warn_msgs:
            msg += "\n\nHinweise:\n" + "\n".join(warn_msgs)
        if errors:
            msg += f"\n\n{errors} Datei(en) fehlerhaft:\n" + "\n".join(err_msgs)
        messagebox.showinfo("Kontoanalyse", msg)

    def _remember_statement(self, stmt):
        """Metadaten eines Auszugs (fuer echten Saldo/Reconciliation) merken."""
        meta = {"konto": stmt.konto, "iban": stmt.iban, "monat": stmt.monat,
                "alter_saldo": stmt.alter_saldo, "neuer_saldo": stmt.neuer_saldo,
                "quelle": stmt.quelle}
        # pro (Konto, Monat) nur einen Eintrag
        self.statements = [s for s in self.statements
                           if not (s["konto"] == stmt.konto and s["monat"] == stmt.monat)]
        self.statements.append(meta)

    def _missing_months(self) -> list[str]:
        """Lueckende Monate zwischen erstem und letztem geladenen Monat."""
        months = self._months()
        if len(months) < 2:
            return []
        have = set(months)
        y0, m0 = int(months[0][:4]), int(months[0][5:7])
        y1, m1 = int(months[-1][:4]), int(months[-1][5:7])
        gaps = []
        y, m = y0, m0
        while (y, m) <= (y1, m1):
            key = f"{y:04d}-{m:02d}"
            if key not in have:
                gaps.append(key)
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return gaps

    def reset_transactions(self):
        if messagebox.askyesno("Zurücksetzen",
                               "Alle gespeicherten Buchungen entfernen?\n"
                               "(Kategorien und Regeln bleiben erhalten.)"):
            self.transactions.clear()
            self._seen.clear()
            self.loaded_files.clear()
            self.statements.clear()
            self._save_data()
            self._rebuild_month_filters()
            self.refresh_table()
            self.draw_chart()
            self._update_status()

    # ---- Persistenz der Buchungen (data.json) ---------------------------
    def _load_data(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        self.loaded_files = data.get("files", [])
        self.statements = data.get("statements", [])
        for d in data.get("transactions", []):
            try:
                t = Transaction.from_dict(d)
            except (KeyError, ValueError):
                continue
            sig = (t.datum, round(t.betrag, 2), t.empfaenger, t.zweck)
            if sig in self._seen:
                continue
            self._seen.add(sig)
            t.kategorie = self.store.categorize(t)
            self.transactions.append(t)
        self.transactions.sort(key=lambda x: (x.datum, x.empfaenger))

    def _save_data(self):
        try:
            payload = {"version": SCHEMA_VERSION,
                       "files": self.loaded_files,
                       "statements": self.statements,
                       "transactions": [t.to_dict() for t in self.transactions]}
            atomic_write_json(DATA_FILE, payload)
        except OSError:
            pass

    # ================================================================
    # Tabelle
    # ================================================================
    def _months(self) -> list[str]:
        return sorted({t.monat for t in self.transactions})

    def _rebuild_month_filters(self):
        months = self._months()
        self.filter_month.configure(values=["Alle"] + months)
        if self.filter_month.get() not in ["Alle"] + months:
            self.filter_month.set("Alle")
        # Zeitraum der Auswertung: Alle + Jahre + einzelne Monate
        years = sorted({m[:4] for m in months})
        periods = ["Alle"] + years + months
        self.chart_month.configure(values=periods)
        if self.chart_month.get() not in periods:
            self.chart_month.set("Alle")
        # Konten
        kontos = sorted({t.konto for t in self.transactions if t.konto})
        self.filter_konto.configure(values=["Alle"] + kontos)
        if self.filter_konto.get() not in ["Alle"] + kontos:
            self.filter_konto.set("Alle")

    def _refresh_category_widgets(self):
        names = self.store.category_names()
        self.filter_cat.configure(values=["Alle"] + names)
        if self.filter_cat.get() not in ["Alle"] + names:
            self.filter_cat.set("Alle")
        self.assign_cat.configure(values=names)
        if self.assign_cat.get() not in names:
            self.assign_cat.set(names[0] if names else "")
        # Zeilenfarben-Tags
        for c in self.store.categories:
            self.tree.tag_configure(f"cat::{c['name']}", background=self._tint(c["color"]))
        # Kategorienliste im Settings-Tab (⊘ = interne Umbuchung/ausgeschlossen)
        self.cat_list.delete(0, tk.END)
        for c in self.store.categories:
            mark = " ⊘" if c.get("exclude") else ""
            self.cat_list.insert(tk.END, f"  {c['name']}{mark}")
            self.cat_list.itemconfig(tk.END, {"bg": self._tint(c["color"]),
                                              "selectbackground": c["color"]})
        # Regeltabelle
        for i in self.rule_tree.get_children():
            self.rule_tree.delete(i)
        for r in self.store.rules:
            self.rule_tree.insert("", tk.END, values=(r["keyword"], r["category"]))

    @staticmethod
    def _tint(hex_color: str, factor: float = 0.82) -> str:
        """Helle, dezente Variante einer Farbe fuer Zeilenhintergruende."""
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _filtered(self) -> list[Transaction]:
        fm = self.filter_month.get()
        fc = self.filter_cat.get()
        fk = self.filter_konto.get()
        ft = self.filter_type.get()
        q = self.search_var.get().strip().lower()

        def _num(s):
            try:
                return float(s.replace(",", ".").strip())
            except ValueError:
                return None
        vmin, vmax = _num(self.filter_min.get()), _num(self.filter_max.get())
        out = []
        for t in self.transactions:
            if fm != "Alle" and t.monat != fm:
                continue
            if fc != "Alle" and t.kategorie != fc:
                continue
            if fk != "Alle" and t.konto != fk:
                continue
            if ft == "Nur Ausgaben" and t.betrag >= 0:
                continue
            if ft == "Nur Einnahmen" and t.betrag <= 0:
                continue
            if vmin is not None and abs(t.betrag) < vmin:
                continue
            if vmax is not None and abs(t.betrag) > vmax:
                continue
            if q and q not in (t.empfaenger + " " + t.zweck + " " + t.buchungsart).lower():
                continue
            out.append(t)
        return out

    def _reset_filters(self):
        self.filter_month.set("Alle")
        self.filter_cat.set("Alle")
        self.filter_konto.set("Alle")
        self.filter_type.set("Alle")
        self.filter_min.set("")
        self.filter_max.set("")
        self.search_var.set("")
        self.refresh_table()

    def _focus_next_unassigned(self):
        """Waehlt die naechste nicht zugeordnete Buchung in der Tabelle aus."""
        children = self.tree.get_children()
        sel = self.tree.selection()
        start = 0
        if sel:
            try:
                start = children.index(sel[-1]) + 1
            except ValueError:
                start = 0
        order = list(children[start:]) + list(children[:start])
        for iid in order:
            t = self._row_map.get(iid)
            if t is not None and t.kategorie == UNASSIGNED:
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
                return
        messagebox.showinfo("Fertig", "Keine offenen Buchungen mehr – alles zugeordnet. 🎉")

    def _on_number_key(self, event):
        """Zifferntasten 1–9 weisen der Auswahl die n-te Kategorie zu."""
        if self.focus_get() is not self.tree:
            return
        try:
            idx = int(event.char) - 1
        except (ValueError, TypeError):
            return
        names = self.store.category_names()
        if 0 <= idx < len(names) and self.tree.selection():
            self._assign_txns(self._selected_txns(), names[idx])

    def refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._row_map = {}
        for t in self._filtered():
            iid = self.tree.insert(
                "", tk.END,
                values=(t.datum.strftime("%d.%m.%Y"),
                        clean_display(t.buchungsart),
                        clean_display(t.empfaenger),
                        clean_display(t.zweck)[:80],
                        eur(t.betrag),
                        t.kategorie),
                tags=(f"cat::{t.kategorie}",))
            self._row_map[iid] = t
        self._update_status()

    def _sort_by(self, col):
        rev = self._sort_state.get(col, False)
        keyfn = {
            "datum": lambda t: t.datum,
            "art": lambda t: t.buchungsart.lower(),
            "empfaenger": lambda t: t.empfaenger.lower(),
            "zweck": lambda t: t.zweck.lower(),
            "betrag": lambda t: t.betrag,
            "kategorie": lambda t: t.kategorie.lower(),
        }[col]
        self.transactions.sort(key=keyfn, reverse=rev)
        self._sort_state[col] = not rev
        self.refresh_table()

    # ================================================================
    # Zuordnen
    # ================================================================
    def _selected_txns(self) -> list[Transaction]:
        return [self._row_map[i] for i in self.tree.selection() if i in self._row_map]

    def _on_tree_double(self, event):
        """Doppelklick auf Spalte „Kategorie“ = Inline-Dropdown, sonst zuordnen."""
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if col != "#6":                       # nur Kategorie-Spalte
            self._assign_selected()
            return
        t = self._row_map.get(row)
        if t is None:
            return
        x, y, w, h = self.tree.bbox(row, col)
        cb = ttk.Combobox(self.tree, values=self.store.category_names(),
                          state="readonly")
        cb.set(t.kategorie)
        cb.place(x=x, y=y, width=w, height=h)
        cb.focus_set()
        cb.event_generate("<Button-1>")

        def commit(_=None):
            val = cb.get()
            cb.destroy()
            if val and val != t.kategorie:
                self._assign_txns([t], val)
        cb.bind("<<ComboboxSelected>>", commit)
        cb.bind("<FocusOut>", lambda e: cb.destroy())
        cb.bind("<Escape>", lambda e: cb.destroy())

    def _assign_selected(self, category: str | None = None):
        txns = self._selected_txns()
        if not txns:
            messagebox.showinfo("Zuordnen", "Bitte zuerst eine oder mehrere Buchungen auswählen.")
            return
        category = category or self.assign_cat.get()
        if not category:
            return
        self._assign_txns(txns, category)

    def _snapshot(self):
        """Zustand der Overrides fuer Undo sichern (max. 25 Schritte)."""
        self._undo_stack.append(dict(self.store.overrides))
        if len(self._undo_stack) > 25:
            self._undo_stack.pop(0)

    def undo_assignment(self):
        if not self._undo_stack:
            return
        self.store.overrides = self._undo_stack.pop()
        self.store.save()
        self._recategorize_all()
        self._refresh_category_widgets()
        self.refresh_table()
        self.draw_chart()

    def _assign_txns(self, txns, category):
        """Weist eine feste Liste von Buchungen einer Kategorie zu."""
        self._snapshot()
        for t in txns:
            self.store.set_override(t, category)
            t.kategorie = category
            if self.remember_rule.get() and t.empfaenger.strip():
                self.store.add_rule(t.empfaenger.strip(), category)
        self._recategorize_all()
        self._refresh_category_widgets()
        self.refresh_table()
        self.draw_chart()

    def _clear_override_selected(self):
        txns = self._selected_txns()
        if not txns:
            return
        self._snapshot()
        for t in txns:
            self.store.clear_override(t)
        self._recategorize_all()
        self.refresh_table()
        self.draw_chart()

    def _recategorize_all(self):
        for t in self.transactions:
            t.kategorie = self.store.categorize(t)

    def _show_context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        sub = tk.Menu(menu, tearoff=0)
        for name in self.store.category_names():
            sub.add_command(label=name, command=lambda n=name: self._assign_selected(n))
        sub.add_separator()
        sub.add_command(label="➕ Neue Kategorie…", command=self._quick_add_category)
        menu.add_cascade(label="Kategorie zuweisen", menu=sub)
        menu.add_command(label="Buchung aufteilen…", command=self._split_selected)
        menu.add_command(label="Automatisch zuordnen (Override entfernen)",
                         command=self._clear_override_selected)
        menu.add_separator()
        menu.add_command(label="Regel aus Empfänger erstellen…",
                         command=self._rule_from_selection)
        menu.tk_popup(event.x_root, event.y_root)

    def _split_selected(self):
        txns = self._selected_txns()
        if len(txns) != 1:
            messagebox.showinfo("Aufteilen", "Bitte genau eine Buchung auswählen.")
            return
        SplitDialog(self, self.store, txns[0], on_done=self._after_split)

    def _after_split(self):
        self._recategorize_all()
        self.refresh_table()
        self.draw_chart()

    def _rule_from_selection(self):
        txns = self._selected_txns()
        if not txns:
            return
        RuleDialog(self, self.store, default_kw=txns[0].empfaenger.strip(),
                   on_done=self._after_settings_change)

    # ================================================================
    # Kategorien-/Regel-Editor
    # ================================================================
    def _after_settings_change(self):
        self._recategorize_all()
        self._refresh_category_widgets()
        self.refresh_table()
        self.draw_chart()

    def _next_default_color(self) -> str:
        """Waehlt eine noch nicht benutzte Farbe aus einer Palette."""
        used = {c["color"].lower() for c in self.store.categories}
        for col in CATEGORY_PALETTE:
            if col.lower() not in used:
                return col
        return CATEGORY_PALETTE[len(self.store.categories) % len(CATEGORY_PALETTE)]

    def _add_category_dialog(self) -> str | None:
        """Oeffnet den Neu-Dialog. Gibt den Namen zurueck oder None."""
        dlg = CategoryDialog(self, existing=self.store.category_names(),
                             default_color=self._next_default_color())
        if not dlg.result:
            return None
        name, color = dlg.result
        self.store.add_category(name, color)
        self._after_settings_change()
        return name

    def _quick_add_category(self):
        """Neue Kategorie anlegen und – wenn Zeilen markiert sind – gleich zuweisen."""
        txns = self._selected_txns()   # vor dem Dialog sichern (Tabelle wird neu gebaut)
        name = self._add_category_dialog()
        if not name:
            return
        self.assign_cat.set(name)
        if txns:
            self._assign_txns(txns, name)

    def _recolor_category(self):
        from tkinter.colorchooser import askcolor
        sel = self.cat_list.curselection()
        if not sel:
            return
        name = self.store.categories[sel[0]]["name"]
        color = askcolor(title=f"Farbe für {name}")[1]
        if color:
            self.store.categories[sel[0]]["color"] = color
            self.store.save()
            self._after_settings_change()

    def _delete_category(self):
        sel = self.cat_list.curselection()
        if not sel:
            return
        name = self.store.categories[sel[0]]["name"]
        if name in (UNASSIGNED, INCOME_CAT):
            messagebox.showinfo("Kategorien", f"„{name}“ kann nicht gelöscht werden.")
            return
        if messagebox.askyesno("Löschen", f"Kategorie „{name}“ und zugehörige Regeln löschen?"):
            self.store.remove_category(name)
            self._after_settings_change()

    def _toggle_exclude(self):
        sel = self.cat_list.curselection()
        if not sel:
            messagebox.showinfo("Interne Umbuchung",
                                "Bitte links eine Kategorie auswählen.")
            return
        name = self.store.categories[sel[0]]["name"]
        if name in (UNASSIGNED, INCOME_CAT):
            return
        self.store.set_excluded(name, not self.store.is_excluded(name))
        self._after_settings_change()

    def _add_rule_dialog(self):
        RuleDialog(self, self.store, on_done=self._after_settings_change)

    def _delete_rule(self):
        sel = self.rule_tree.selection()
        if not sel:
            return
        kw = self.rule_tree.item(sel[0])["values"][0]
        self.store.remove_rule(str(kw))
        self._after_settings_change()

    # ================================================================
    # Auswertung
    # ================================================================
    # -- Zeitraum-Helfer --------------------------------------------------
    def _period_txns(self, period) -> list[Transaction]:
        if period is None:
            return []
        if period == "Alle":
            return list(self.transactions)
        if len(period) == 4 and period.isdigit():          # ganzes Jahr
            return [t for t in self.transactions if t.monat[:4] == period]
        return [t for t in self.transactions if t.monat == period]

    def _prev_period(self, period):
        if period == "Alle":
            return None
        if len(period) == 4 and period.isdigit():
            return str(int(period) - 1)
        y, m = int(period[:4]), int(period[5:7])
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        return f"{y:04d}-{m:02d}"

    # -- Aggregations-Kern (beruecksichtigt Splits, Ausschluss, Refunds) --
    def _income_expense(self, txns):
        """(Einnahmen, Ausgaben). Interne Umbuchungen (exclude) zaehlen nicht,
        Rueckerstattungen (positiver Betrag in Ausgabekategorie) mindern die
        Ausgaben statt als Einnahme zu zaehlen."""
        income = expense = 0.0
        for t in txns:
            for cat, amt in self.store.parts(t):
                if self.store.is_excluded(cat):
                    continue
                if cat == INCOME_CAT:
                    if amt > 0:
                        income += amt
                    else:
                        expense += -amt
                else:
                    expense += -amt
        return income, expense

    def _cat_expense_totals(self, txns) -> dict:
        """kategorie -> Ausgaben (netto). Ohne Einkommen und ausgeschlossene."""
        d = defaultdict(float)
        for t in txns:
            for cat, amt in self.store.parts(t):
                if cat == INCOME_CAT or self.store.is_excluded(cat):
                    continue
                d[cat] += -amt
        return {k: v for k, v in d.items()}

    def _month_cat_expense(self, txns, month, cat) -> float:
        s = 0.0
        for t in txns:
            if t.monat != month:
                continue
            for c, amt in self.store.parts(t):
                if c == cat:
                    s += -amt
        return s

    def _kpis(self, txns) -> dict:
        income, expense = self._income_expense(txns)
        net = income - expense
        rate = (net / income * 100) if income > 0 else None
        nmonths = len({t.monat for t in txns}) or 1
        return {"income": income, "expense": expense, "net": net,
                "rate": rate, "avg": expense / nmonths, "nmonths": nmonths}

    def _clear_kpis(self):
        for c in self.kpi_cards.values():
            c["value"].config(text="–", fg="#222")
            c["delta"].config(text="", fg="#888")

    def _update_kpis(self, data, period):
        cur = self._kpis(data)
        prev_period = self._prev_period(period)
        prev_txns = self._period_txns(prev_period) if prev_period else []
        prev = self._kpis(prev_txns) if prev_txns else None

        self.kpi_cards["income"]["value"].config(text=eur(cur["income"]), fg="#2e7d32")
        self.kpi_cards["expense"]["value"].config(text=eur(cur["expense"]), fg="#c62828")
        self.kpi_cards["net"]["value"].config(
            text=eur(cur["net"]), fg="#2e7d32" if cur["net"] >= 0 else "#c62828")
        self.kpi_cards["rate"]["value"].config(
            text=(f"{cur['rate']:.0f} %" if cur["rate"] is not None else "–"), fg="#222")
        self.kpi_cards["avg"]["value"].config(text=eur(cur["avg"]), fg="#222")
        self.kpi_cards["avg"]["delta"].config(
            text=f"Basis: {cur['nmonths']} Monat(e)", fg="#999")

        def delta(key, cur_v, prev_v, higher_better, pct=True, suffix=""):
            lbl = self.kpi_cards[key]["delta"]
            if prev is None or cur_v is None or prev_v is None:
                lbl.config(text="", fg="#999")
                return
            diff = cur_v - prev_v
            if pct and abs(prev_v) > 1e-9:
                txt = f"{'▲' if diff >= 0 else '▼'} {abs(diff/prev_v*100):.0f}% ggü. Vorperiode"
            else:
                txt = f"{'▲' if diff >= 0 else '▼'} {abs(diff):.0f}{suffix} ggü. Vorperiode"
            good = (diff >= 0) == higher_better
            lbl.config(text=txt, fg="#2e7d32" if good else "#c62828")

        delta("income", cur["income"], prev["income"] if prev else None, True)
        delta("expense", cur["expense"], prev["expense"] if prev else None, False)
        delta("net", cur["net"], prev["net"] if prev else None, True)
        if prev and prev["rate"] is not None and cur["rate"] is not None:
            delta("rate", cur["rate"], prev["rate"], True, pct=False, suffix=" %-Pkt.")
        else:
            self.kpi_cards["rate"]["delta"].config(text="", fg="#999")

    # -- Zeichnen ---------------------------------------------------------
    def draw_chart(self):
        if not hasattr(self, "fig"):
            return
        self.fig.clear()
        period = self.chart_month.get()
        data = self._period_txns(period)
        kind = self.chart_type.get()
        if not self.transactions:
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "Noch keine Daten geladen.\nOben „PDF(s) laden“.",
                    ha="center", va="center", fontsize=13, color="#888")
            ax.axis("off")
            self._clear_kpis()
            self.chart_caption.config(text="")
            self.canvas.draw()
            return

        self._update_kpis(data, period)
        self._drill = []            # klickbare Flaechen fuer Drill-down
        self._render_chart(kind, data, period)

        hint = "   (Tipp: auf ein Segment klicken zeigt die Buchungen)" \
            if self._drill else ""
        self.chart_caption.config(text="ⓘ  " + CHART_CAPTIONS.get(kind, "") + hint)
        try:
            self.fig.tight_layout()
        except Exception:  # noqa: BLE001
            pass
        self.canvas.draw()

    def _render_chart(self, kind, data, period):
        """Zeichnet den gewaehlten Diagrammtyp auf self.fig (ohne Canvas-Update)."""
        if kind == CHART_OVERVIEW:
            self._chart_overview(data)
        elif kind == CHART_PIE:
            self._chart_pie(data)
        elif kind == CHART_COMPARE:
            self._chart_category_compare(period)
        elif kind == CHART_TREND:
            self._chart_category_trend(data)
        elif kind == CHART_STACKED:
            self._chart_stacked(data)
        elif kind == CHART_RECURRING:
            self._chart_recurring(data)
        elif kind == CHART_BUDGET:
            self._chart_budget(data, period)
        elif kind == CHART_TOP:
            self._chart_top_payees(data)
        elif kind == CHART_REAL_BALANCE:
            self._chart_real_balance(period)
        elif kind == CHART_BALANCE:
            self._chart_balance(data)

    def _cat_color(self, name):
        return self.store.color_of(name)

    def _chart_overview(self, data):
        months = sorted({t.monat for t in data})
        ax = self.fig.add_subplot(111)
        inc, exp = [], []
        for m in months:
            i, e = self._income_expense([t for t in data if t.monat == m])
            inc.append(i)
            exp.append(e)
        net = [i - e for i, e in zip(inc, exp)]
        x = list(range(len(months)))
        w = 0.38
        ax.bar([i - w / 2 for i in x], inc, w, label="Einnahmen", color="#2e7d32")
        ax.bar([i + w / 2 for i in x], exp, w, label="Ausgaben", color="#e53935")
        ax.plot(x, net, color="#1e88e5", marker="o", lw=2, label="Netto (gespart)")
        ax.axhline(0, color="#999", lw=0.8)
        for i, (inc_i, net_i) in enumerate(zip(inc, net)):
            if inc_i > 0:
                ax.annotate(f"{net_i / inc_i * 100:.0f}%", (i, net_i),
                            textcoords="offset points", xytext=(0, 9),
                            ha="center", fontsize=8, color="#1565c0", fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax.set_xlim(-0.7, len(months) - 0.3)
        ax.set_ylabel("EUR")
        ax.set_title("Cashflow je Monat – was bleibt übrig? (%=Sparquote)")
        ax.legend(frameon=False, fontsize=8)
        ax.grid(axis="y", alpha=0.3)

    def _chart_pie(self, data):
        totals = {k: v for k, v in self._cat_expense_totals(data).items() if v > 0}
        ax = self.fig.add_subplot(111)
        if not totals:
            ax.text(0.5, 0.5, "Keine Ausgaben im Zeitraum.", ha="center")
            ax.axis("off")
            return
        items = sorted(totals.items(), key=lambda x: -x[1])
        labels = [k for k, _ in items]
        sizes = [v for _, v in items]
        colors = [self._cat_color(k) for k in labels]
        wedges, _texts, autotexts = ax.pie(
            sizes, colors=colors, autopct=lambda p: f"{p:.0f}%",
            startangle=90, pctdistance=0.78,
            wedgeprops=dict(width=0.42, edgecolor="white"))
        for at in autotexts:
            at.set_fontsize(8)
        for w, lab in zip(wedges, labels):
            self._drill.append((w, "category", lab))
        ax.text(0, 0, f"gesamt\n{eur(sum(sizes))}", ha="center", va="center",
                fontsize=10, fontweight="bold")
        ax.legend(wedges, [f"{l}  ({eur(s)})" for l, s in zip(labels, sizes)],
                  loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, frameon=False)
        ax.set_title("Ausgaben nach Kategorie")

    def _chart_category_compare(self, period):
        cur = self._period_txns(period)
        prev_period = self._prev_period(period)
        prev = self._period_txns(prev_period) if prev_period else []
        ax = self.fig.add_subplot(111)
        if period == "Alle" or not prev:
            ax.text(0.5, 0.5, "Kein Vorzeitraum zum Vergleichen.\n"
                    "Wähle oben einen einzelnen Monat oder ein Jahr.",
                    ha="center", va="center", color="#888")
            ax.axis("off")
            return

        cd, pdv = self._cat_expense_totals(cur), self._cat_expense_totals(prev)
        cats = sorted(set(cd) | set(pdv), key=lambda c: -cd.get(c, 0))[:10][::-1]
        if not cats:
            ax.text(0.5, 0.5, "Keine Ausgaben im Zeitraum.", ha="center")
            ax.axis("off")
            return
        y = list(range(len(cats)))
        h = 0.4
        ax.barh([i + h / 2 for i in y], [cd.get(c, 0) for c in cats], h,
                color=[self._cat_color(c) for c in cats], label=f"{period}")
        ax.barh([i - h / 2 for i in y], [pdv.get(c, 0) for c in cats], h,
                color="#cccccc", label=f"Vorperiode ({prev_period})")
        ax.set_yticks(y)
        ax.set_yticklabels(cats, fontsize=8)
        ax.set_xlabel("EUR")
        ax.set_title(f"Kategorien: {period} vs. {prev_period}")
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        ax.grid(axis="x", alpha=0.3)

    def _chart_category_trend(self, data):
        months = sorted({t.monat for t in data})
        ax = self.fig.add_subplot(111)
        if len(months) < 2:
            ax.text(0.5, 0.5, "Zu wenig Monate für einen Trend.\n"
                    "Lade mehrere Auszüge und wähle Zeitraum „Alle“.",
                    ha="center", va="center", color="#888")
            ax.axis("off")
            return
        totals = self._cat_expense_totals(data)
        top = [c for c, _ in sorted(totals.items(), key=lambda x: -x[1])[:5]]
        x = list(range(len(months)))
        for c in top:
            vals = [self._month_cat_expense(data, m, c) for m in months]
            ax.plot(x, vals, marker="o", lw=2, label=c, color=self._cat_color(c))
        ax.set_xticks(x)
        ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("EUR / Monat")
        ax.set_title("Kategorie-Entwicklung (Top 5)")
        ax.legend(frameon=False, fontsize=8)
        ax.grid(alpha=0.3)

    def _chart_recurring(self, data):
        months = sorted({t.monat for t in data})
        nm = len(months)
        if nm < 2:
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "Abo-/Fixkosten-Erkennung braucht mindestens 2 Monate.\n"
                    "Lade mehrere Kontoauszüge und wähle Zeitraum „Alle“.",
                    ha="center", va="center", color="#888")
            ax.axis("off")
            return
        groups = defaultdict(lambda: {"total": 0.0, "months": set(),
                                      "amounts": [], "name": ""})
        for t in data:
            if t.betrag >= 0:
                continue
            key = t.empfaenger.strip().upper()
            g = groups[key]
            g["total"] += -t.betrag
            g["months"].add(t.monat)
            g["amounts"].append(-t.betrag)
            g["name"] = clean_display(t.empfaenger)

        # Ein echtes Abo/Fixkosten: taucht in mehreren Monaten auf (min. min(3, Monate)),
        # etwa eine Buchung pro Monat und mit konstantem Betrag (geringe Schwankung).
        min_months = min(3, nm)

        def _is_recurring(g):
            n_mon = len(g["months"])
            if n_mon < min_months:
                return False
            if len(g["amounts"]) > n_mon * 1.6:      # zu viele Buchungen/Monat -> variabel
                return False
            mean = sum(g["amounts"]) / len(g["amounts"])
            if mean <= 0:
                return False
            var = sum((a - mean) ** 2 for a in g["amounts"]) / len(g["amounts"])
            cv = (var ** 0.5) / mean                 # Variationskoeffizient
            return cv < 0.35

        recurring = {k: g for k, g in groups.items() if _is_recurring(g)}
        fixed_total = sum(g["total"] for g in recurring.values())
        var_total = sum(g["total"] for k, g in groups.items() if k not in recurring)

        ax1 = self.fig.add_subplot(1, 2, 1)
        if fixed_total + var_total > 0:
            ax1.pie([fixed_total, var_total], colors=["#6d4c41", "#90a4ae"],
                    autopct=lambda p: f"{p:.0f}%", startangle=90,
                    wedgeprops=dict(width=0.42, edgecolor="white"),
                    textprops=dict(fontsize=8, color="white"))
        ax1.legend(["Fixkosten", "Variabel"], loc="lower center",
                   bbox_to_anchor=(0.5, -0.15), frameon=False, fontsize=8, ncol=2)
        monthly_fixed = fixed_total / nm
        ax1.set_title(f"Fixkosten ≈ {eur(monthly_fixed)}/Monat\n"
                      f"= {eur(monthly_fixed * 12)}/Jahr", fontsize=9)

        ax2 = self.fig.add_subplot(1, 2, 2)
        top = sorted(recurring.values(), key=lambda g: -g["total"])[:10]
        if top:
            labels, monthly = [], []
            for g in top:
                mth = g["total"] / len(g["months"])
                # naechstes voraussichtliches Datum: letzter Monat + 1
                last = max(g["months"])
                ly, lm = int(last[:4]), int(last[5:7])
                lm += 1
                if lm == 13:
                    ly, lm = ly + 1, 1
                labels.append(f"{g['name'][:22]}  (≈{ly:04d}-{lm:02d})")
                monthly.append(mth)
            labels, monthly = labels[::-1], monthly[::-1]
            ax2.barh(range(len(labels)), monthly, color="#6d4c41")
            for i, v in enumerate(monthly):
                ax2.text(v, i, f" {eur(v)}/M · {eur(v * 12)}/J", va="center", fontsize=6.5)
            ax2.set_yticks(range(len(labels)))
            ax2.set_yticklabels(labels, fontsize=7)
            ax2.set_xlabel("≈ EUR / Monat")
            ax2.set_title("Erkannte Abos (nächste Buchung ≈)", fontsize=9)
            ax2.grid(axis="x", alpha=0.3)
        else:
            ax2.text(0.5, 0.5, "Keine wiederkehrenden Zahlungen erkannt.",
                     ha="center", color="#888")
            ax2.axis("off")

    def _chart_stacked(self, data):
        months = sorted({t.monat for t in data})
        cats = [c for c in self.store.category_names() if c != INCOME_CAT]
        ax = self.fig.add_subplot(111)
        x = list(range(len(months)))
        bottom = [0.0] * len(months)
        any_data = False
        cats = [c for c in cats if not self.store.is_excluded(c)]
        for cat in cats:
            vals = [self._month_cat_expense(data, m, cat) for m in months]
            if sum(vals) == 0:
                continue
            any_data = True
            ax.bar(x, vals, bottom=bottom, label=cat, color=self._cat_color(cat))
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_xticks(x)
        ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("EUR")
        ax.set_title("Ausgaben je Kategorie je Monat")
        if any_data:
            ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, frameon=False)
        ax.grid(axis="y", alpha=0.3)

    def _chart_balance(self, data):
        ordered = sorted(data, key=lambda t: t.datum)
        xs, ys, run = [], [], 0.0
        for t in ordered:
            run += t.betrag
            xs.append(t.datum)
            ys.append(run)
        ax = self.fig.add_subplot(111)
        ax.plot(xs, ys, marker="", color="#1e88e5")
        ax.fill_between(xs, ys, alpha=0.15, color="#1e88e5")
        ax.axhline(0, color="#999", lw=0.8)
        ax.set_ylabel("Kumulierter Saldo (EUR)")
        ax.set_title("Saldo-Verlauf (relativ zum Startpunkt)")
        ax.grid(alpha=0.3)
        self.fig.autofmt_xdate()

    def _chart_top_payees(self, data):
        totals = defaultdict(float)
        for t in data:
            if t.betrag < 0:
                totals[clean_display(t.empfaenger)] += -t.betrag
        items = sorted(totals.items(), key=lambda x: -x[1])[:12]
        ax = self.fig.add_subplot(111)
        if not items:
            ax.text(0.5, 0.5, "Keine Ausgaben im Zeitraum.", ha="center")
            ax.axis("off")
            return
        labels = [k[:28] for k, _ in items][::-1]
        full = [k for k, _ in items][::-1]
        vals = [v for _, v in items][::-1]
        bars = ax.barh(labels, vals, color="#5e35b1")
        ax.set_xlabel("EUR")
        ax.set_title("Top-Empfänger nach Ausgaben")
        for i, v in enumerate(vals):
            ax.text(v, i, f" {eur(v)}", va="center", fontsize=7)
        for bar, name in zip(bars, full):
            self._drill.append((bar, "payee", name))
        ax.grid(axis="x", alpha=0.3)

    def _chart_real_balance(self, period):
        ax = self.fig.add_subplot(111)
        metas = [s for s in self.statements if s.get("alter_saldo") is not None]
        if period != "Alle":
            if len(period) == 4 and period.isdigit():
                metas = [s for s in metas if s.get("monat", "")[:4] == period]
            else:
                metas = [s for s in metas if s.get("monat") == period]
        if not metas:
            ax.text(0.5, 0.5, "Kein Kontostand in den geladenen Auszügen gefunden.\n"
                    "(PDF muss „Alter/Neuer Saldo“ enthalten.)",
                    ha="center", va="center", color="#888")
            ax.axis("off")
            return
        by = defaultdict(list)
        for s in metas:
            by[s.get("konto", "")].append(s)
        for konto, slist in by.items():
            slist = sorted(slist, key=lambda s: s.get("monat", ""))
            xs, ys = [], []
            for s in slist:
                bal = s["alter_saldo"]
                mtx = sorted([t for t in self.transactions
                              if t.konto == konto and t.monat == s["monat"]],
                             key=lambda t: t.datum)
                if mtx:
                    xs.append(mtx[0].datum)
                    ys.append(bal)
                for t in mtx:
                    bal += t.betrag
                    xs.append(t.datum)
                    ys.append(bal)
            if xs:
                ax.plot(xs, ys, lw=1.8,
                        label=(f"…{konto[-4:]}" if konto else "Konto"))
                ax.fill_between(xs, ys, alpha=0.10)
        ax.axhline(0, color="#999", lw=0.8)
        ax.set_ylabel("Kontostand (EUR)")
        ax.set_title("Echter Kontostand-Verlauf")
        ax.grid(alpha=0.3)
        if len(by) > 1:
            ax.legend(frameon=False, fontsize=8)
        self.fig.autofmt_xdate()

    def _chart_budget(self, data, period):
        ax = self.fig.add_subplot(111)
        budgets = {c: v for c, v in self.store.budgets.items() if v > 0}
        if not budgets:
            ax.text(0.5, 0.5, "Noch keine Budgets gesetzt.\n"
                    "Lege sie im Tab „Budgets“ fest.",
                    ha="center", va="center", color="#888")
            ax.axis("off")
            return
        nmonths = len({t.monat for t in data}) or 1
        totals = self._cat_expense_totals(data)
        cats = sorted(budgets, key=lambda c: -(totals.get(c, 0) / (budgets[c] * nmonths)))
        cats = cats[::-1]
        for i, c in enumerate(cats):
            limit = budgets[c] * nmonths
            spent = totals.get(c, 0)
            frac = spent / limit if limit else 0
            color = "#2e7d32" if frac <= 0.8 else ("#f9a825" if frac <= 1.0 else "#c62828")
            ax.barh(i, limit, color="#eeeeee", height=0.6)
            bar = ax.barh(i, min(spent, limit), color=color, height=0.6)
            if spent > limit:
                ax.barh(i, spent - limit, left=limit, color="#c62828",
                        height=0.6, alpha=0.5)
            ax.text(max(spent, limit), i,
                    f"  {eur(spent)} / {eur(limit)}  ({frac * 100:.0f}%)",
                    va="center", fontsize=7)
            for b in bar:
                self._drill.append((b, "category", c))
        ax.set_yticks(list(range(len(cats))))
        ax.set_yticklabels(cats, fontsize=8)
        ax.set_xlabel("EUR")
        ax.set_title(f"Budget-Ampel  ({nmonths} Monat(e) im Zeitraum)")
        ax.grid(axis="x", alpha=0.3)

    # -- Drill-down -------------------------------------------------------
    def _on_chart_click(self, event):
        if event.inaxes is None or not getattr(self, "_drill", None):
            return
        for artist, kind, val in self._drill:
            try:
                hit, _ = artist.contains(event)
            except Exception:  # noqa: BLE001
                hit = False
            if hit:
                self._show_drill(kind, val)
                return

    def _show_drill(self, kind, val):
        period = self.chart_month.get()
        data = self._period_txns(period)
        if kind == "category":
            rows = [t for t in data
                    if any(c == val for c, _ in self.store.parts(t))]
        else:
            rows = [t for t in data if clean_display(t.empfaenger) == val]
        if rows:
            self._open_txn_window(f"Buchungen – {val}  ({period})",
                                  sorted(rows, key=lambda t: t.datum))

    def _open_txn_window(self, title, rows):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("720x420")
        cols = ("datum", "empfaenger", "zweck", "betrag", "kategorie")
        tv = ttk.Treeview(win, columns=cols, show="headings")
        for c, txt, w in [("datum", "Datum", 80), ("empfaenger", "Empfänger", 200),
                          ("zweck", "Zweck", 220), ("betrag", "Betrag", 90),
                          ("kategorie", "Kategorie", 110)]:
            tv.heading(c, text=txt)
            tv.column(c, width=w, anchor="e" if c == "betrag" else "w")
        for t in rows:
            tv.insert("", tk.END, values=(
                t.datum.strftime("%d.%m.%Y"), clean_display(t.empfaenger),
                clean_display(t.zweck)[:60], eur(t.betrag), t.kategorie))
        tv.pack(fill="both", expand=True, padx=6, pady=6)
        total = sum(t.betrag for t in rows)
        ttk.Label(win, text=f"{len(rows)} Buchungen   Summe: {eur(total)}",
                  font=("Segoe UI", 10, "bold")).pack(anchor="e", padx=10, pady=(0, 8))

    # ================================================================
    def _on_tab_changed(self):
        idx = self.nb.index(self.nb.select())
        if idx == 1:
            self.draw_chart()
        elif idx == 2:
            self._refresh_budget_tab()

    # ================================================================
    # Export
    # ================================================================
    def export_csv(self):
        rows = self._filtered()
        if not rows:
            messagebox.showinfo("Export", "Keine Buchungen zum Exportieren "
                                "(evtl. Filter aktiv).")
            return
        path = filedialog.asksaveasfilename(
            title="Als CSV speichern", defaultextension=".csv",
            filetypes=[("CSV-Datei", "*.csv")])
        if not path:
            return
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Datum", "Konto", "Buchungsart", "Empfänger",
                        "Verwendungszweck", "Betrag", "Kategorie"])
            for t in rows:
                w.writerow([t.datum.strftime("%d.%m.%Y"), t.konto,
                            clean_display(t.buchungsart), clean_display(t.empfaenger),
                            clean_display(t.zweck), f"{t.betrag:.2f}".replace(".", ","),
                            t.kategorie])
        messagebox.showinfo("Export", f"{len(rows)} Buchungen gespeichert:\n{path}")

    def export_excel(self):
        rows = self._filtered()
        if not rows:
            messagebox.showinfo("Export", "Keine Buchungen zum Exportieren.")
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            messagebox.showinfo(
                "Excel-Export",
                "Für den Excel-Export fehlt das Paket „openpyxl“.\n"
                "Installiere es mit:\n\n    pip install openpyxl\n\n"
                "Alternativ funktioniert der CSV-Export (öffnet auch in Excel).")
            return
        path = filedialog.asksaveasfilename(
            title="Als Excel speichern", defaultextension=".xlsx",
            filetypes=[("Excel-Datei", "*.xlsx")])
        if not path:
            return
        wb = Workbook()
        ws = wb.active
        ws.title = "Buchungen"
        ws.append(["Datum", "Konto", "Buchungsart", "Empfänger",
                   "Verwendungszweck", "Betrag", "Kategorie"])
        for t in rows:
            ws.append([t.datum, t.konto, clean_display(t.buchungsart),
                       clean_display(t.empfaenger), clean_display(t.zweck),
                       t.betrag, t.kategorie])
        wb.save(path)
        messagebox.showinfo("Export", f"{len(rows)} Buchungen gespeichert:\n{path}")

    def export_report(self):
        if not self.transactions:
            messagebox.showinfo("Report", "Keine Daten geladen.")
            return
        path = filedialog.asksaveasfilename(
            title="Report als PDF speichern", defaultextension=".pdf",
            filetypes=[("PDF-Datei", "*.pdf")])
        if not path:
            return
        from matplotlib.backends.backend_pdf import PdfPages
        period = self.chart_month.get()
        data = self._period_txns(period)
        k = self._kpis(data)
        saved = self.fig
        try:
            with PdfPages(path) as pdf:
                cover = Figure(figsize=(8.3, 11.7))
                ax = cover.add_subplot(111)
                ax.axis("off")
                lines = [
                    "Kontoanalyse – Report", f"Zeitraum: {period}", "",
                    f"Einnahmen:      {eur(k['income'])}",
                    f"Ausgaben:       {eur(k['expense'])}",
                    f"Netto gespart:  {eur(k['net'])}",
                    f"Sparquote:      "
                    + (f"{k['rate']:.0f} %" if k['rate'] is not None else "–"),
                    f"Ø Ausgaben/Mon: {eur(k['avg'])}",
                    f"Monate:         {k['nmonths']}",
                ]
                ax.text(0.06, 0.95, "\n".join(lines), va="top",
                        family="monospace", fontsize=13)
                pdf.savefig(cover)
                for kind in (CHART_OVERVIEW, CHART_PIE, CHART_BUDGET,
                             CHART_TOP, CHART_REAL_BALANCE):
                    self.fig = Figure(figsize=(11, 7))
                    self._drill = []
                    try:
                        self._render_chart(kind, data, period)
                        self.fig.tight_layout()
                    except Exception:  # noqa: BLE001
                        pass
                    pdf.savefig(self.fig)
        finally:
            self.fig = saved
            self.draw_chart()
        messagebox.showinfo("Export", f"Report gespeichert:\n{path}")

    # ================================================================
    # UI-Zustand (Fenstergroesse + letzte Filter) merken
    # ================================================================
    def _load_ui_state(self):
        if not os.path.exists(UI_FILE):
            return
        try:
            with open(UI_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        g = data.get("geometry")
        if g:
            try:
                self.geometry(g)
            except tk.TclError:
                pass
        fl = data.get("filters", {})
        for name, widget in [("month", self.filter_month), ("cat", self.filter_cat),
                             ("konto", self.filter_konto), ("type", self.filter_type),
                             ("chart_period", self.chart_month),
                             ("chart_type", self.chart_type)]:
            v = fl.get(name)
            if v and v in widget.cget("values"):
                widget.set(v)

    def _save_ui_state(self):
        data = {"geometry": self.geometry(),
                "filters": {"month": self.filter_month.get(),
                            "cat": self.filter_cat.get(),
                            "konto": self.filter_konto.get(),
                            "type": self.filter_type.get(),
                            "chart_period": self.chart_month.get(),
                            "chart_type": self.chart_type.get()}}
        try:
            atomic_write_json(UI_FILE, data)
        except OSError:
            pass

    def _on_close(self):
        self._save_ui_state()
        self.destroy()

    def _update_status(self):
        n = len(self.transactions)
        unassigned = sum(1 for t in self.transactions if t.kategorie == UNASSIGNED)
        inc, exp = self._income_expense(self.transactions)
        txt = f"{n} Buchungen"
        if n:
            txt += f"   |   Einnahmen {eur(inc)}   Ausgaben {eur(-exp)}"
            if unassigned:
                txt += f"   |   {unassigned} offen"
        self.status.config(text=txt)


# ---------------------------------------------------------------------------
# kleine Dialoge
# ---------------------------------------------------------------------------
class CategoryDialog(tk.Toplevel):
    """Neue Kategorie: Name + Farbe in einem Fenster, mit Live-Vorschau."""

    def __init__(self, parent, existing, default_color="#546e7a"):
        super().__init__(parent)
        self.title("Neue Kategorie")
        self.result = None
        self.existing = {e.lower() for e in existing}
        self.color = default_color
        self.transient(parent)
        self.resizable(False, False)
        self.grab_set()

        ttk.Label(self, text="Name der Kategorie:").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 2))
        self.name = tk.StringVar()
        ent = ttk.Entry(self, textvariable=self.name, width=30)
        ent.grid(row=1, column=0, columnspan=2, padx=16, sticky="we")
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._ok())

        ttk.Label(self, text="Farbe:").grid(row=2, column=0, sticky="w",
                                            padx=16, pady=(12, 2))
        self.swatch = tk.Label(self, width=6, relief="groove", bg=self.color)
        self.swatch.grid(row=3, column=0, padx=(16, 4), sticky="w")
        ttk.Button(self, text="Ändern…", command=self._pick_color).grid(
            row=3, column=1, sticky="w")

        self.err = ttk.Label(self, text="", foreground="#c62828")
        self.err.grid(row=4, column=0, columnspan=2, padx=16, sticky="w", pady=(6, 0))

        btn = ttk.Frame(self)
        btn.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Button(btn, text="Anlegen", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btn, text="Abbrechen", command=self.destroy).pack(side="left", padx=4)
        self.name.trace_add("write", lambda *a: self.err.config(text=""))
        self.wait_window()

    def _pick_color(self):
        from tkinter.colorchooser import askcolor
        col = askcolor(color=self.color, title="Farbe wählen")[1]
        if col:
            self.color = col
            self.swatch.config(bg=col)

    def _ok(self):
        name = self.name.get().strip()
        if not name:
            self.err.config(text="Bitte einen Namen eingeben.")
            return
        if name.lower() in self.existing:
            self.err.config(text="Diese Kategorie gibt es schon.")
            return
        self.result = (name, self.color)
        self.destroy()


class RuleDialog(tk.Toplevel):
    def __init__(self, parent, store: Store, default_kw="", on_done=None):
        super().__init__(parent)
        self.title("Regel")
        self.store = store
        self.on_done = on_done
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text="Stichwort / Muster (im Empfänger oder Zweck):").pack(
            anchor="w", padx=16, pady=(14, 2))
        self.kw = tk.StringVar(value=default_kw)
        ttk.Entry(self, textvariable=self.kw, width=44).pack(padx=16)
        self.regex = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Als regulären Ausdruck (Regex) behandeln",
                        variable=self.regex).pack(anchor="w", padx=16, pady=(4, 0))
        amt = ttk.Frame(self)
        amt.pack(anchor="w", padx=16, pady=(6, 0))
        ttk.Label(amt, text="nur bei Betrag von").pack(side="left")
        self.amin = tk.StringVar()
        ttk.Entry(amt, textvariable=self.amin, width=8).pack(side="left", padx=4)
        ttk.Label(amt, text="bis").pack(side="left")
        self.amax = tk.StringVar()
        ttk.Entry(amt, textvariable=self.amax, width=8).pack(side="left", padx=4)
        ttk.Label(amt, text="€ (optional)").pack(side="left")
        ttk.Label(self, text="Kategorie:").pack(anchor="w", padx=16, pady=(10, 2))
        self.cat = ttk.Combobox(self, width=42, state="readonly",
                                values=store.category_names())
        if store.category_names():
            self.cat.current(0)
        self.cat.pack(padx=16)
        b = ttk.Frame(self)
        b.pack(pady=12)
        ttk.Button(b, text="Speichern", command=self._save).pack(side="left", padx=4)
        ttk.Button(b, text="Abbrechen", command=self.destroy).pack(side="left", padx=4)
        self.wait_window()

    def _save(self):
        kw = self.kw.get().strip()
        cat = self.cat.get()

        def num(s):
            try:
                return float(s.replace(",", ".").strip())
            except ValueError:
                return None
        if kw and cat:
            self.store.add_rule(kw, cat, regex=self.regex.get(),
                                amount_min=num(self.amin.get()),
                                amount_max=num(self.amax.get()))
            if self.on_done:
                self.on_done()
        self.destroy()


class SplitDialog(tk.Toplevel):
    """Teilt eine Buchung auf mehrere Kategorien auf (Betraege müssen aufgehen)."""

    def __init__(self, parent, store: Store, txn, on_done=None):
        super().__init__(parent)
        self.title("Buchung aufteilen")
        self.store = store
        self.txn = txn
        self.on_done = on_done
        self.rows = []
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text=f"{clean_display(txn.empfaenger)}  ({eur(txn.betrag)})",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(self, text="Betraege mit gleichem Vorzeichen wie die Buchung "
                             "eingeben; die Summe muss passen.",
                  foreground="#666", font=("Segoe UI", 8)).pack(anchor="w", padx=14)
        self.body = ttk.Frame(self)
        self.body.pack(padx=14, pady=8, fill="x")
        # vorhandene Splits laden, sonst 2 leere Zeilen
        existing = store.overrides.get(txn.key)
        if isinstance(existing, list) and existing:
            for p in existing:
                self._add_row(p.get("category"), p.get("betrag"))
        else:
            self._add_row(txn.kategorie, round(txn.betrag, 2))
            self._add_row(UNASSIGNED, 0.0)
        self.info = ttk.Label(self, text="", font=("Segoe UI", 9))
        self.info.pack(anchor="w", padx=14)
        b = ttk.Frame(self)
        b.pack(pady=10)
        ttk.Button(b, text="Zeile +", command=lambda: self._add_row(UNASSIGNED, 0.0)
                   ).pack(side="left", padx=4)
        ttk.Button(b, text="Speichern", command=self._save).pack(side="left", padx=4)
        ttk.Button(b, text="Abbrechen", command=self.destroy).pack(side="left", padx=4)
        self._update_info()
        self.wait_window()

    def _add_row(self, category, betrag):
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=2)
        cat = ttk.Combobox(row, width=24, state="readonly",
                           values=self.store.category_names())
        cat.set(category or UNASSIGNED)
        cat.pack(side="left")
        amt = tk.StringVar(value=f"{betrag:.2f}".replace(".", ","))
        e = ttk.Entry(row, textvariable=amt, width=12)
        e.pack(side="left", padx=6)
        amt.trace_add("write", lambda *a: self._update_info())
        self.rows.append((cat, amt))

    def _parsed(self):
        out = []
        for cat, amt in self.rows:
            try:
                v = float(amt.get().replace(",", ".").strip())
            except ValueError:
                v = 0.0
            if cat.get() and abs(v) > 0:
                out.append({"category": cat.get(), "betrag": v})
        return out

    def _update_info(self):
        s = sum(p["betrag"] for p in self._parsed())
        diff = round(self.txn.betrag - s, 2)
        ok = abs(diff) < 0.01
        self.info.config(
            text=f"Summe {eur(s)}  /  Buchung {eur(self.txn.betrag)}   "
                 + ("✓ passt" if ok else f"⚠ Differenz {eur(diff)}"),
            foreground="#2e7d32" if ok else "#c62828")
        return ok

    def _save(self):
        if not self._update_info():
            messagebox.showwarning("Aufteilen",
                                   "Die Summe der Teilbeträge muss dem "
                                   "Buchungsbetrag entsprechen.")
            return
        parts = self._parsed()
        if len(parts) < 2:
            messagebox.showinfo("Aufteilen", "Mindestens zwei Teile angeben "
                                "(sonst normal zuordnen).")
            return
        self.store.set_split(self.txn, parts)
        if self.on_done:
            self.on_done()
        self.destroy()


if __name__ == "__main__":
    app = KontoApp()
    app.mainloop()
