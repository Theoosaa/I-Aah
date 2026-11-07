# I-Aah – Kontoanalyse

I-Aah liest **Kontoauszüge der ING (PDF)** und **CSV-Exporte vieler Banken** ein, ordnet jede
Buchung über Stichwörter einer Kategorie zu und wertet deine Ausgaben über Monate und Jahre aus.
Alles, was du einmal zuordnest, gilt auch für künftige Auszüge. Die Daten bleiben auf deinem
Rechner – auf Wunsch verschlüsselt.

## Was das Programm kann

- **Import:** ING-Girokonto-PDFs (auch viele auf einmal, ganze Ordner) und CSV-Dateien mit
  automatischer oder eigener Spaltenzuordnung. Doppelte Buchungen werden erkannt, der
  Saldo jedes PDF-Auszugs wird nachgerechnet.
- **Zuordnen:** Kategorien bestehen aus Stichwortlisten. Was kein Stichwort trifft, landet in
  einer Auffang-Kategorie und gilt als *offen*. Zuordnen per farbigem Knopf, Tasten 1–9 oder
  Rechtsklick; Buchungen lassen sich auf mehrere Kategorien aufteilen; alles ist rückgängig
  zu machen.
- **Stichwort-Vorschläge:** Nach einer Zuordnung von Hand schlägt das Programm Stichwörter vor
  und zeigt vorher, wie viele Buchungen sie träfen. Regeln entstehen nie heimlich.
- **PDF-Prüfung:** der Original-Auszug mit farbig markierten Buchungen – so siehst du, ob alles
  erkannt wurde und welche Zeilen nicht als Buchung zählen.
- **Auswertung:** 13 Diagramme, Kennzahlen mit Vergleich zur Vorperiode, Klick auf ein Segment
  zeigt die Buchungen dahinter.
- **Budgets** je Kategorie mit Ampel.
- **Export:** Buchungen als CSV/Excel, Zusammenfassung als CSV/Text, markiertes Auszug-PDF,
  PDF-Report.
- **Dunkles Design**, **Passwortschutz**, **Kommandozeile** (`iaah-cli`).

## Installation

Voraussetzung: **Python 3.12 oder neuer** (entwickelt mit 3.14). Unter Linux zusätzlich Tk:
`sudo apt install python3-tk`.

Im Ordner des Programms (Windows, PowerShell):

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Unter Linux/macOS lauten die ersten beiden Zeilen `python3 -m venv .venv` und
`source .venv/bin/activate`.

## Starten

```powershell
iaah
```

(bei aktivierter Umgebung, sonst `.venv\Scripts\iaah.exe` – die Datei kannst du auch per
Doppelklick oder über eine Desktop-Verknüpfung starten). Alternativ: `python -m iaah`.

Ohne Python geht es mit der fertigen `I-Aah.exe` (siehe [Windows-Programm bauen](#windows-programm-bauen)).

## Erste Schritte

1. **Datei → Kontoauszüge importieren (PDF, CSV)…** (Strg+O) und einen oder mehrere Auszüge
   wählen. Mehrere Dateien werden im Hintergrund gelesen; am Ende fasst eine Meldung zusammen,
   was neu war, was schon bekannt war und welche Monate in der Reihe fehlen.
2. Im Tab **Transaktionen** mit **Nächste offene ▶** (F3) durch die Buchungen gehen, die noch
   kein Stichwort getroffen hat, und sie per Knopf oder Taste 1–9 zuordnen.
3. Unter **Stichwort vorschlagen** ein passendes Stichwort **übernehmen** – dann wird der
   Empfänger künftig automatisch erkannt.
4. Im Tab **Auswertung** Zeitraum und Diagramm wählen.

Jeden Monat genügt es, den neuen Auszug zu importieren – alles Bisherige bleibt gespeichert.

## Die Tabs

### Transaktionen

- **Filter:** Zeitraum, Kategorie, Suche (Empfänger, Verwendungszweck, Buchungsart), Konto,
  Typ (Ausgaben/Einnahmen), Betrag von … bis … (ohne Vorzeichen), *nur offene*.
  **Filter zurücksetzen** stellt alles zurück.
- **Tabelle:** Klick auf eine Spaltenüberschrift sortiert (▲/▼), die Zeilenfarbe ist die
  Farbe der Kategorie. Das Zeichen vor der Kategorie sagt, wie sie zustande kam:

  | Zeichen | Bedeutung |
  |---|---|
  | (keins) | ein Stichwort hat getroffen |
  | `?` | offen – kein Stichwort, Auffang-Kategorie *Sonstiges* bzw. *Einkommen* |
  | `✎` | von Hand zugeordnet |
  | `÷` | aufgeteilt auf mehrere Kategorien |

- **Ausgewählte Buchung** (rechts): alle Texte der Buchung, die Herkunft der Kategorie und die
  Knöpfe zum Zuordnen. Mehrere markierte Zeilen werden gemeinsam zugeordnet.
  **Aufteilen…** verteilt den Betrag auf mehrere Kategorien, **Automatisch** nimmt eine
  Zuordnung von Hand zurück, **+ Neue Kategorie** legt eine Kategorie an und ordnet sie gleich zu.
- **Stichwort vorschlagen:** erscheint nach einer Zuordnung von Hand. Jeder Vorschlag nennt,
  wie viele Buchungen er trifft und bei wie vielen er die Kategorie ändern würde.
- **Rechtsklick:** Kategorie zuweisen, Aufteilen…, Automatisch zuordnen,
  In der PDF-Prüfung zeigen. **Doppelklick** öffnet die Buchung in der PDF-Prüfung.
- Die Statuszeile unten zählt die angezeigten Buchungen und ihre Summen.

### PDF-Prüfung

Zeigt einen importierten Auszug als Bild, jede Buchung farbig hinterlegt; Buchungen, deren
Kategorie du von Hand geändert hast, sind dunkel umrandet. Oben wählst du den Auszug, blätterst
mit ◀ ▶ und zoomst mit − + (oder Strg+Mausrad). Ein Klick auf eine Markierung wählt die
Buchung; das Zuordnen geht auch hier mit den Knöpfen oder den Tasten 1–9.
**Vorher (nur Stichwörter) zeigen** blendet deine Zuordnungen von Hand aus. Die Liste
**Nicht verwendete Zeilen** nennt Zeilen, die das Programm nicht zu einer Buchung gezählt hat,
mit Grund (z. B. „neben der Buchungsspalte“, „zu weit unter der Buchung“). Ganz oben stehen
auffällige Zeilen mit Datum und Betrag, aber ohne Buchung – dort könnte eine Buchung fehlen.
Briefkopf und Hinweistexte erscheinen nur, wenn sie so auffällig sind.

Die PDF-Prüfung braucht die Original-Datei am Ort des Imports. Hast du die PDFs verschoben,
importiere sie am neuen Ort noch einmal – das Programm erkennt sie und merkt sich den neuen Ort.

### Auswertung

Oben **Zeitraum** (Gesamt, ein Jahr oder ein Monat) und **Diagramm**. Die Kacheln zeigen
Einnahmen, Ausgaben, Netto gespart und Sparquote – bei einem Jahr oder Monat mit Vergleich zur
Vorperiode (▲/▼, grün = besser) – sowie *Ø Ausgaben / Monat* mit der Zahl der Monate, über die
gemittelt wird. Unter jedem Diagramm erklärt eine Zeile (ⓘ),
was es zeigt; steht dort ein Klick-Tipp, öffnet ein Klick auf ein Segment die zugehörigen
Buchungen. Die Werkzeugleiste darunter kann zoomen und das Bild speichern.

Diagramme: Überblick: Cashflow & Sparquote · Ausgaben nach Kategorie · Geldfluss (Sankey) ·
Kategorie-Vergleich zur Vorperiode · Kategorie-Entwicklung über Zeit · Ausgaben je Kategorie je
Monat (gestapelt) · Jahresvergleich · Fixkosten vs. variabel (Abos erkennen) · Budget-Ampel ·
Top-Empfänger · Kalender-Heatmap · Echter Kontostand · Saldo-Verlauf (relativ).

Kategorien der Art *Ignoriert* (z. B. Umbuchungen aufs eigene Sparkonto) zählen weder bei
Einnahmen, Ausgaben und Sparquote noch in Kategorie-, Budget- oder Empfänger-Diagrammen mit.
*Echter Kontostand* und *Saldo-Verlauf* zeigen dagegen alle Buchungen, so wie das Konto sie
sieht. Erstattungen mindern die Ausgaben ihrer Kategorie.

### Budgets

Ein Monatsbudget je Ausgaben-Kategorie, daneben der Ø-Ist-Wert je Monat im oben gewählten
Zeitraum. Die Spalte *Stand* zeigt, wie voll das Budget ist (bis 80 % im Rahmen, bis 100 % fast
erreicht, darüber überzogen – grün, gelb, rot); dasselbe zeigt das Diagramm *Budget-Ampel*.
Leer oder 0 bedeutet: kein Budget. **Budgets speichern** übernimmt alle Eingaben auf einmal.

### Kategorien

Links die Liste (▲/▼ ändert die Reihenfolge – sie bestimmt die Tasten 1–9), rechts die
gewählte Kategorie: Name, **Farbe…**, **Art** (Ausgabe, Einnahme, Ignoriert), Monatsbudget und
die **Stichwörter** (Hinzufügen, Ändern, Entfernen). **Löschen** nennt vorher, wie viele
Zuordnungen von Hand an der Kategorie hängen, und entfernt sie mit (Strg+Z holt alles zurück).
*Sonstiges* und *Einkommen* sind die Auffang-Kategorien: Sie lassen sich weder löschen noch in
ihrer Art ändern.

## Menüs

**Datei**
- *Kontoauszüge importieren (PDF, CSV)…* – eine oder mehrere Dateien.
- *Alle PDFs eines Ordners importieren…* – alle PDFs direkt im Ordner (ohne Unterordner).
- *CSV mit eigener Spaltenzuordnung…* – wenn die automatische Erkennung danebenliegt: Kopfzeile,
  Datum, Betrag, Empfänger und Verwendungszweck selbst wählen, mit Vorschau. Erkennt der normale
  Import die Spalten gar nicht, öffnet sich derselbe Dialog von selbst.
- *Exportieren*
  - *Buchungen (gefiltert) als CSV…* – die im Tab *Transaktionen* angezeigten Buchungen,
    `;`-getrennt, Dezimalkomma (öffnet direkt in Excel); eine aufgeteilte Buchung ergibt eine
    Zeile je Teil.
  - *Buchungen (gefiltert) als Excel…* – dasselbe als `.xlsx`.
  - *Zusammenfassung je Kategorie als CSV…* / *als Text…* – Ausgaben und Einnahmen je
    Kategorie, ebenfalls für die angezeigten Buchungen.
  - *Markiertes Kontoauszug-PDF…* – der Original-Auszug mit farbigen Balken hinter jeder
    Buchung und einer Legende.
  - *Report des Auswertungs-Zeitraums als PDF…* – Deckblatt mit Kennzahlen und die wichtigsten
    Diagramme.
- *Alte I-Aah-Daten übernehmen…* – siehe [Umstieg von der alten Version](#umstieg-von-der-alten-version).
- *Bibliothek leeren…* – entfernt alle importierten Auszüge und Buchungen; Kategorien und
  Zuordnungen von Hand bleiben.
- *Beenden*

**Bearbeiten:** Rückgängig (Strg+Z) · Wiederholen (Strg+Y) · Nächste offene Buchung (F3) ·
Auswahl automatisch zuordnen · Überflüssige manuelle Zuordnungen entfernen (solche, die
ohnehin dasselbe Ergebnis wie die Stichwörter hätten).

**Kategorien:** Neue Kategorie… · Kategorien aus Datei laden… (ersetzt alle aktuellen
Kategorien und Stichwörter; Strg+Z macht es rückgängig) · Kategorien speichern unter… (JSON
oder CSV, siehe unten).

**Ansicht:** Dunkles Design · die fünf Tabs (Strg+1 … Strg+5).

**Datenschutz:** Passwort festlegen oder ändern… · Passwort entfernen… · Beschädigte Kopien
löschen…

**Hilfe:** Datenordner öffnen · Über I-Aah.

## Tastenkürzel

| Taste | Wirkung |
|---|---|
| Strg+O | Kontoauszüge importieren |
| Strg+Z / Strg+Y | Rückgängig / Wiederholen für Kategorien und Zuordnungen (nicht, solange der Cursor in einem Eingabefeld steht) |
| F3 | Nächste offene Buchung |
| 1 … 9 | markierte Buchungen der 1. … 9. Kategorie zuordnen (Transaktionen, PDF-Prüfung) |
| Strg+1 … Strg+5 | Tab wechseln |

## Kategorien und Stichwörter

- Ein Stichwort trifft, wenn es im **Empfänger** oder im **Verwendungszweck** am Anfang eines
  Wortes steht. Groß- und Kleinschreibung, Umlaute und Akzente spielen keine Rolle (`ä` = `ae`,
  `ß` = `ss`).
- Treffen mehrere Stichwörter, gewinnt das **längste** („amazon prime“ vor „amazon“).
- Ein Stichwort gehört genau einer Kategorie; das Programm meldet Überschneidungen.
- Stichwörter einer Einnahmen-Kategorie treffen nur Geldeingänge.
- Ohne Treffer: Ausgaben → **Sonstiges**, Einnahmen → **Einkommen**. Solche Buchungen gelten
  als „offen“, bis du sie zuordnest – auch das Bestätigen der Auffang-Kategorie per Knopf zählt
  als Entscheidung (`✎`).
- Eine Zuordnung von Hand oder eine Aufteilung hat immer Vorrang vor den Stichwörtern.

**Dateiformate** für *Kategorien aus Datei laden…* und *Kategorien speichern unter…*: am
einfachsten erzeugst du eine Vorlage mit *Kategorien speichern unter…*.

- JSON: `{"version": 1, "categories": [{"name": …, "color": "#rrggbb", "kind": "expense" | "income" | "ignored", "budget": "250.00", "keywords": […]}]}`.
  In eigenen JSON-Dateien muss je eine Kategorie `"role": "expense_fallback"` bzw.
  `"income_fallback"` tragen.
- CSV: Spalten `name;color;kind;role;budget;keywords`, Stichwörter durch `|` getrennt.
- Kategorie-Dateien des Projekts *budgets* (JSON oder CSV) werden ebenfalls gelesen. CSV- und
  *budgets*-Dateien ohne Auffang-Kategorien bekommen *Sonstiges* und *Einkommen* automatisch.

## Wo liegen die Daten?

Nicht im Programmordner, sondern im Benutzer-Datenordner (**Hilfe → Datenordner öffnen**):

- Windows: `%LOCALAPPDATA%\I-Aah`
- Linux: `~/.local/share/I-Aah`, macOS: `~/Library/Application Support/I-Aah`
- Anderer Ort: Umgebungsvariable `IAAH_HOME` setzen.

| Datei | Inhalt |
|---|---|
| `library.json` | Kategorien, Stichwörter, Budgets, importierte Auszüge (mit Pfad zur PDF), Buchungen und deine Zuordnungen – verschlüsselt, sobald ein Passwort festgelegt ist |
| `library.json.bak` | die vorige Fassung, bei jedem Speichern erneuert |
| `ui_state.json` | Fenstergröße, Design, Tab, Zeitraum, Diagramm – nie verschlüsselt, enthält keine Buchungsdaten |
| `iaah.lock` | verhindert, dass das Programm zweimal läuft |

Gespeichert wird nach jeder Änderung, immer zuerst in eine temporäre Datei. Ist `library.json`
beschädigt, legt das Programm sie als `library.json.damaged-<Zeit>` beiseite und lädt die
Sicherung; es löscht dabei nichts. Gibt es keine lesbare Sicherung, fragt es, ob es die
beschädigten Dateien beiseitelegen und leer starten soll („Nein“ beendet es). Lässt sich die
Datei gar nicht lesen (gesperrt, keine Zugriffsrechte), meldet es das und beendet sich, ohne
etwas zu verändern. Beiseitegelegte Kopien entfernt *Datenschutz → Beschädigte Kopien
löschen…*.

**Passwortschutz:** *Datenschutz → Passwort festlegen oder ändern…* verschlüsselt
`library.json` und die Sicherung (AES über Fernet, Schlüssel per PBKDF2 aus dem Passwort).
Beim Start fragt das Programm nach dem Passwort. **Ohne Passwort sind die Daten nicht zu
retten** – merk es dir gut.

## Umstieg von der alten Version

Die alte I-Aah-Version (`kontoanalyse.py`) speicherte alles als `settings.json` und
`data.json` im Programmordner. So übernimmst du die Daten:

1. Neue Version starten. Startest du sie im alten Programmordner (z. B. `iaah` in einer
   Konsole, die dort steht), bietet das Programm die Übernahme beim ersten Start gleich an;
   sonst **Datei → Alte I-Aah-Daten übernehmen…** und den alten Programmordner wählen.
2. War `data.json` verschlüsselt, fragt das Programm nach dem alten Passwort. Die neuen Daten
   werden dann gleich mit demselben Passwort verschlüsselt gespeichert.
3. Ein Bericht zeigt, was übernommen wurde: Kategorien mit Farben und Budgets, Regeln als
   Stichwörter, Zuordnungen von Hand und Aufteilungen, Buchungen. Er listet auch, was nicht
   übernommen werden konnte (z. B. Regex-Regeln, die sich nicht in ein Stichwort übersetzen
   lassen, oder Betragsgrenzen von Regeln) und welche Buchungen jetzt automatisch eine andere
   Kategorie bekommen.

Die alten Dateien werden nur gelesen, nie verändert. Übernommen wird nur in eine noch leere
Bibliothek; vorhandene eigene Kategorien oder Zuordnungen werden nicht ohne Rückfrage ersetzt.
Danach kannst du die alten Dateien (`settings.json`, `data.json`, `ui_state.json` und ihre
`.bak`) archivieren oder löschen – Fenstergröße und Filter der alten Version werden nicht
übernommen. Alte Buchungen haben keine
Position im PDF – importiere die Auszüge einmal neu, dann erscheinen sie auch in der
PDF-Prüfung (doppelt gezählt wird dabei nichts).

## Kommandozeile

`iaah-cli --help` zeigt alle Befehle, `iaah-cli <Befehl> --help` deren Optionen.
`iaah-cli -v <Befehl> …` (`-v` vor dem Befehl) zeigt bei Fehlern Details.

```powershell
# Erkennung prüfen: Buchungen, Saldo-Abgleich, auffällige Zeilen (mit --lines jede Zeile).
# Rückgabewert: 0 = alles in Ordnung, 1 = etwas ansehen, 2 = Datei nicht lesbar / falscher Aufruf
iaah-cli check Auszug.pdf

# Summen je Kategorie als Text (Bildschirm), CSV (zusammenfassung.csv), Diagramm (ausgaben.png)
# und/oder PDF-Report (report.pdf) im Ordner --output-dir
iaah-cli summary Auszüge\*.pdf --period 2026 --format text csv chart report --output-dir Auswertung

# … mit Buchungen, Kategorien und Zuordnungen der App (nur lesend; fragt bei Passwortschutz
# nach dem Passwort)
iaah-cli summary --library --period 2026-07

# … oder mit einer Kategorie-Datei
iaah-cli summary Auszug.pdf --categories kategorien.json

# Markiertes PDF (Standard: <Name>_markiert.pdf daneben)
iaah-cli highlight Auszug.pdf -o markiert.pdf

# Mehrere Zusammenfassungen (CSV) addieren – jede in einen eigenen Ordner schreiben, weil
# summary immer zusammenfassung.csv heißt
iaah-cli summary Januar.pdf --format csv --output-dir januar
iaah-cli summary Februar.pdf --format csv --output-dir februar
iaah-cli merge januar\zusammenfassung.csv februar\zusammenfassung.csv --format text csv --output-dir gesamt
```

## Windows-Programm bauen

Eine eigenständige `I-Aah.exe`, die ohne Python läuft:

```powershell
pip install -e ".[build]"
pyinstaller --noconfirm --clean --onefile --windowed --name I-Aah `
  --paths src `
  --collect-data iaah `
  --collect-data pdfminer --collect-data reportlab `
  --add-data "LICENSE;." --add-data "LICENSES;LICENSES" `
  src\iaah\__main__.py
```

Das Ergebnis liegt in `dist\I-Aah.exe`; die Zwischendateien (`build\`, `I-Aah.spec`) kannst du
löschen. Die `.exe` nutzt denselben Datenordner wie die installierte Version. Jeder Start dauert
einige Sekunden, weil sich das Programm zuerst in einen temporären Ordner entpackt.

## Hinweise

- PDFs: getestet mit Girokonto-Auszügen der ING. Andere Banken haben ein anderes Layout –
  für sie ist der CSV-Import da.
- Manche ING-PDFs enthalten Umlaute in einer kaputten Schriftkodierung; Anzeige und
  Stichwort-Suche reparieren die bekannten Fälle.

## Entwicklung

Aufbau, Regeln für den Code, Tests und Werkzeuge stehen in [AGENTS.md](AGENTS.md);
`pip install -e ".[dev]"` installiert pytest, ruff und mypy.

## Lizenz

MIT – siehe [LICENSE](LICENSE). Teile des Codes stammen aus dem Projekt *budgets*
(MIT, © 2026 nikluep), siehe [LICENSES/budgets-MIT.txt](LICENSES/budgets-MIT.txt).
