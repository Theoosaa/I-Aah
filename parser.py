"""PDF-Parser fuer ING-DiBa / Sparkassen-aehnliche Girokonto-Kontoauszuege.

Liefert ein ``Statement`` mit Buchungen (``Transaction``) und Metadaten
(Konto, IBAN, alter/neuer Saldo). Der Parser ist bewusst tolerant: Einnahmen
(ohne Minuszeichen) und Ausgaben (mit '-') werden erkannt, Folgezeilen mit
Verwendungszweck werden der jeweiligen Buchung zugeordnet, Kopf-/Fusszeilen
werden herausgefiltert.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date

import pdfplumber

# Hauptzeile einer Buchung:  "01.07.2026 Lastschrift REWE ... -11,49"
_MAIN_RE = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+(-?\d[\d.]*,\d{2})$"
)

# Monat/Jahr aus "Kontoauszug Juli 2026"
_MONTHS = {
    "januar": 1, "februar": 2, "maerz": 3, "märz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
_PERIOD_RE = re.compile(r"Kontoauszug\s+([A-Za-zÄÖÜäöü�]+)\s+(\d{4})")
_ALTER_RE = re.compile(r"Alter Saldo\s+(-?[\d.]+,\d{2})")
_NEUER_RE = re.compile(r"Neuer Saldo\s+(-?[\d.]+,\d{2})")
_IBAN_RE = re.compile(r"IBAN\s+([A-Z]{2}[0-9A-Z ]{13,34})")
_KONTO_RE = re.compile(r"Nummer\s+(\d{6,})")

# Zeilen, die zum Seiten-Kopf/-Fuss gehoeren und NICHT Verwendungszweck sind.
_FOOTER_PREFIXES = (
    "ING-DiBa", "Seite ", "T_", "Datum ", "Herr", "Frau", "IBAN", "BIC",
    "Alter Saldo", "Neuer Saldo", "Einger", "Auszugsnummer", "Kontoauszug",
    "Buchung", "Girokonto Nummer", "Wirbitten", "DieING", "Zugang",
    "dassIhr", "Gutschrift nicht", "beiuns", "dieU", "Steuernummer",
    "Vorsitzende", "Michael Cl",
)

# Typische erste Woerter einer Buchung -> "Buchungsart".
_BOOKING_TYPES = (
    "Lastschrift", "Gutschrift", "Gehalt/Rente", "Gehalt", "Rente",
    "Ueberweisung", "Überweisung", "Echtzeitüberweisung", "Echtzeit�berweisung",
    "Dauerauftrag", "Kartenzahlung", "Bargeldauszahlung", "Entgelt",
    "Zinsen", "Storno",
)


@dataclass
class Transaction:
    datum: date
    buchungsart: str
    empfaenger: str          # Gegenpartei / Merchant (Basis fuer Zuordnung)
    zweck: str               # zusaetzlicher Verwendungszweck (Detailzeilen)
    betrag: float            # negativ = Ausgabe, positiv = Einnahme
    monat: str               # "YYYY-MM"
    quelle: str              # Dateiname
    konto: str = ""          # Kontonummer (fuer Mehrkonten)
    kategorie: str = "Nicht zugeordnet"

    @property
    def key(self) -> str:
        """Stabiler Schluessel fuer manuelle Zuordnungen / Dedupe."""
        return f"{self.datum.isoformat()}|{self.betrag:.2f}|{self.empfaenger}"

    @property
    def match_text(self) -> str:
        """Text, gegen den Regeln (Stichwoerter) geprueft werden."""
        return f"{self.empfaenger} {self.zweck}".upper()

    def to_dict(self) -> dict:
        """Fuer die persistente Speicherung (ohne Kategorie – wird neu berechnet)."""
        return {"datum": self.datum.isoformat(), "buchungsart": self.buchungsart,
                "empfaenger": self.empfaenger, "zweck": self.zweck,
                "betrag": self.betrag, "monat": self.monat, "quelle": self.quelle,
                "konto": self.konto}

    @staticmethod
    def from_dict(d: dict) -> "Transaction":
        y, m, day = (int(x) for x in d["datum"].split("-"))
        return Transaction(
            datum=date(y, m, day), buchungsart=d.get("buchungsart", ""),
            empfaenger=d.get("empfaenger", ""), zweck=d.get("zweck", ""),
            betrag=float(d["betrag"]), monat=d.get("monat", f"{y:04d}-{m:02d}"),
            quelle=d.get("quelle", ""), konto=d.get("konto", ""))


@dataclass
class Statement:
    """Ein Kontoauszug: Metadaten + Buchungen."""
    quelle: str
    konto: str = ""
    iban: str = ""
    monat: str = ""
    alter_saldo: float | None = None
    neuer_saldo: float | None = None
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def summe(self) -> float:
        return sum(t.betrag for t in self.transactions)

    @property
    def reconciles(self) -> bool | None:
        """True/False, ob Buchungssumme zur Saldodifferenz passt (oder None)."""
        if self.alter_saldo is None or self.neuer_saldo is None:
            return None
        return abs((self.alter_saldo + self.summe) - self.neuer_saldo) < 0.01


def _parse_amount(raw: str) -> float:
    neg = raw.strip().startswith("-")
    digits = raw.replace(".", "").replace("-", "").replace(",", ".").strip()
    val = float(digits)
    return -val if neg else val


def _split_type(desc: str) -> tuple[str, str]:
    """Trennt Buchungsart vom Empfaenger."""
    for t in _BOOKING_TYPES:
        if desc.startswith(t):
            rest = desc[len(t):].strip()
            return t, rest or desc
    parts = desc.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", desc


def _is_footer(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    for p in _FOOTER_PREFIXES:
        if s.startswith(p):
            return True
    return False


def parse_pdf(path: str) -> Statement:
    """Liest einen Kontoauszug (Buchungen + Metadaten) aus einem PDF."""
    quelle = os.path.basename(path)
    lines: list[str] = []
    period_month = period_year = None
    stmt = Statement(quelle=quelle)

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                if period_month is None:
                    m = _PERIOD_RE.search(line)
                    if m:
                        period_month = _MONTHS.get(m.group(1).lower())
                        period_year = int(m.group(2))
                # Metadaten (nur erstes Vorkommen zaehlt)
                if stmt.alter_saldo is None:
                    a = _ALTER_RE.search(line)
                    if a:
                        stmt.alter_saldo = _parse_amount(a.group(1))
                if stmt.neuer_saldo is None:
                    n = _NEUER_RE.search(line)
                    if n:
                        stmt.neuer_saldo = _parse_amount(n.group(1))
                if not stmt.iban:
                    ib = _IBAN_RE.search(line)
                    if ib:
                        stmt.iban = ib.group(1).replace(" ", "").strip()
                if not stmt.konto:
                    k = _KONTO_RE.search(line)
                    if k:
                        stmt.konto = k.group(1)
                lines.append(line)

    if period_year and period_month:
        stmt.monat = f"{period_year:04d}-{period_month:02d}"
    # Fallback-Konto: aus IBAN ableiten, falls keine Nummer gefunden
    if not stmt.konto and stmt.iban:
        stmt.konto = stmt.iban[-10:]

    transactions: list[Transaction] = []
    current: Transaction | None = None
    zweck_lines: list[str] = []

    def flush():
        nonlocal current, zweck_lines
        if current is not None:
            current.zweck = " ".join(zweck_lines).strip()
            transactions.append(current)
        current = None
        zweck_lines = []

    for line in lines:
        m = _MAIN_RE.match(line.strip())
        if m:
            flush()
            datum_str, desc, betrag_str = m.groups()
            d = date(int(datum_str[6:10]), int(datum_str[3:5]), int(datum_str[0:2]))
            art, empf = _split_type(desc.strip())
            current = Transaction(
                datum=d,
                buchungsart=art,
                empfaenger=empf,
                zweck="",
                betrag=_parse_amount(betrag_str),
                monat=f"{d.year:04d}-{d.month:02d}",
                quelle=quelle,
                konto=stmt.konto,
            )
        else:
            if current is not None and not _is_footer(line):
                s = line.strip()
                # fuehrendes Valuta-Datum aus Detailzeile entfernen
                s = re.sub(r"^\d{2}\.\d{2}\.\d{4}\s+", "", s)
                if s:
                    zweck_lines.append(s)
    flush()
    stmt.transactions = transactions
    return stmt


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        st = parse_pdf(p)
        print(f"\n{p}: {len(st.transactions)} Buchungen  Konto={st.konto} "
              f"IBAN={st.iban} {st.monat}")
        print(f"  Alter Saldo {st.alter_saldo}  Neuer Saldo {st.neuer_saldo}  "
              f"Summe {st.summe:.2f}  stimmt={st.reconciles}")
        for t in st.transactions[:6]:
            print(f"  {t.datum} | {t.buchungsart:16.16} | {t.empfaenger:28.28} | "
                  f"{t.betrag:10.2f} | {t.zweck[:36]}")
