# Kontoanalyse

Ein Python-Programm mit Oberfläche, das **ING-DiBa Girokonto-Kontoauszüge (PDF)**
einliest und deine **Ausgaben nach Kategorien** auswertet. Einmal getroffene
Zuordnungen werden gespeichert, sodass jeder neue Monatsauszug automatisch
kategorisiert wird. Mehrere Auszüge lassen sich gleichzeitig laden, um ein
ganzes Jahr mit Grafiken zu analysieren.

## Neu in Version 2

- **Budgets je Kategorie** mit Ampel (grün/gelb/rot) – eigener Tab „Budgets“ +
  Diagramm „Budget-Ampel“.
- **Echter Kontostand-Verlauf** aus dem Auszug (Alter/Neuer Saldo) inkl.
  automatischem **Saldo-Abgleich** beim Import.
- **Abo-/Fixkosten-Erkennung** mit Monats- **und Jahreskosten** und nächstem
  voraussichtlichen Buchungsdatum.
- **Drill-down:** Klick auf ein Diagramm-Segment zeigt die zugehörigen Buchungen.
- **Buchung aufteilen** (ein Betrag auf mehrere Kategorien), **interne
  Umbuchungen** ausschließen (zählen nicht als Ausgabe/Einnahme),
  **Rückerstattungen** mindern die Kategorieausgabe statt als Einkommen zu zählen.
- **Bessere Regeln:** spezifischste Regel gewinnt, optional **Regex** und
  **Betragsgrenzen**.
- **Schnell-Zuordnen:** „Nächste offene ▶“, Zifferntasten **1–9**, **Undo (Strg+Z)**,
  Kategorie direkt in der Tabelle per Doppelklick ändern.
- **Filter** nach Konto, Betrag (von–bis) und Typ (Ein-/Ausgaben).
- **Export:** CSV, Excel (mit `openpyxl`) und **PDF-Report**.
- **Mehrkonten:** Konto/IBAN werden erkannt und sind filterbar.
- **Robustheit:** atomare Schreibvorgänge mit `.bak`-Backup; Fenstergröße und
  letzte Filter werden gemerkt.

## Installation (einmalig)

```bash
pip install -r requirements.txt
```

## Starten

Doppelklick auf **`Start.bat`** – oder:

```bash
python kontoanalyse.py
```

## Bedienung

**1. Auszüge laden**
- „PDF(s) laden“ – ein oder mehrere Kontoauszüge auswählen (Strg/Shift = Mehrfachauswahl).
- „Ordner laden“ – alle PDFs eines Ordners auf einmal (z. B. ein ganzes Jahr).
- Doppelt geladene Buchungen werden automatisch erkannt und nicht doppelt gezählt.
- **Buchungen bleiben gespeichert** (in `data.json`) und werden beim nächsten Start
  automatisch geladen. Du musst also **nicht jedes Mal alle PDFs neu einlesen** –
  jeden Monat einfach nur den neuen Auszug per „PDF(s) laden“ hinzufügen. Zum
  kompletten Neuaufbau: Menü *Datei → Geladene Auszüge zurücksetzen*.

**2. Tab „Transaktionen“**
- Alle Buchungen in einer Tabelle, farblich nach Kategorie.
- Oben filtern nach **Monat**, **Kategorie** und **Suchtext**; Spalten durch Klick sortierbar.
- Zuordnen:
  - Eine oder mehrere Zeilen markieren → unten Kategorie wählen → **„Zuordnen“**
    (oder Doppelklick / Rechtsklick → „Kategorie zuweisen“).
  - Ist **„Als Regel merken (Empfänger)“** aktiv, merkt sich das Programm den
    Empfänger. Der gleiche Empfänger wird künftig – auch in neuen Auszügen –
    automatisch dieser Kategorie zugeordnet.

**3. Tab „Auswertung“**

Ganz oben **Kennzahlen-Kacheln** mit Vergleich zur Vorperiode (▲▼):
Einnahmen · Ausgaben · Netto gespart · **Sparquote** · Ø Ausgaben/Monat.
Wählst du einen einzelnen Monat, wird automatisch mit dem Vormonat verglichen;
ein Jahr wird mit dem Vorjahr verglichen.

Darunter das gewählte Diagramm – jedes mit einer **Erklärzeile (ⓘ)**, die sagt,
was es aussagt und über welchen Zeitraum:

- **Überblick: Cashflow & Sparquote** – grün Einnahmen, rot Ausgaben, blaue Linie
  = was übrig bleibt, %-Zahl = Sparquote. Die Startansicht.
- **Ausgaben nach Kategorie** – Ring mit Gesamtsumme in der Mitte.
- **Kategorie-Vergleich zur Vorperiode** – farbig = aktuell, grau = Vorperiode;
  zeigt sofort, wo es teurer/günstiger wurde.
- **Kategorie-Entwicklung über Zeit** – Top-5-Kategorien als Linien über Monate.
- **Ausgaben je Kategorie je Monat (gestapelt)** – Monatssummen nach Kategorie.
- **Fixkosten vs. variabel (Abos erkennen)** – trennt wiederkehrende Zahlungen
  (Miete, Abos, Versicherungen) von variablen Ausgaben und listet erkannte Abos
  mit monatlichem Betrag. Braucht ≥ 2 geladene Monate.
- **Top-Empfänger** – größte Kostenverursacher.
- **Saldo-Verlauf** – kumulierte Entwicklung.

Zeitraum wählbar: **Alle · einzelnes Jahr · einzelner Monat**. Die
Navigationsleiste erlaubt Zoomen und Speichern als Bild.

**4. Tab „Kategorien & Regeln“**
- Eigene Kategorien anlegen, umfärben, löschen.
- Regeln (Stichwort → Kategorie) direkt bearbeiten. Ein Stichwort greift, wenn es
  im Empfänger oder Verwendungszweck vorkommt (Groß-/Kleinschreibung egal).

## Wo wird gespeichert?

Alles landet in **`settings.json`** neben dem Programm:
- `categories` – deine Kategorien + Farben
- `rules` – gelernte/eigene Zuordnungsregeln
- `overrides` – manuelle Zuordnungen einzelner Buchungen

Die eingelesenen **Buchungen** liegen getrennt davon in `data.json` und werden
beim Start automatisch geladen (siehe „Auszüge laden“).

> **Datenschutz / Git:** `settings.json` (enthält u. a. echte Empfänger in den
> Regeln/Overrides) und `data.json` (deine Buchungen) sind **persönliche Daten**
> und gehören **nicht** ins Git-Repository. Beide sollten in `.gitignore` stehen.

## Dateien

| Datei | Zweck |
|-------|-------|
| `kontoanalyse.py` | Hauptprogramm mit Oberfläche |
| `parser.py`       | PDF-Einleser (Buchungen extrahieren) |
| `settings.json`   | Kategorien, Regeln, Zuordnungen (persönlich – nicht committen) |
| `data.json`       | gespeicherte Buchungen (persönlich – nicht committen) |
| `smoke_test.py`   | Automatischer Test gegen ein echtes PDF |
| `Start.bat`       | Bequemer Start unter Windows |

## Hinweise

- Getestet mit ING-DiBa Girokonto-Auszügen. Andere Banken haben ein anderes
  PDF-Layout; dafür müsste `parser.py` angepasst werden.
- Manche Umlaute sind in den ING-PDFs im Font kaputt hinterlegt; die Anzeige
  gleicht das so gut wie möglich aus. Auf die Zuordnung hat das keinen Einfluss,
  da sie über gleichbleibende Stichwörter läuft.
