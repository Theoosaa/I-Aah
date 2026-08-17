"""Headless-Test: baut die App, laedt das echte PDF, prueft Logik + Charts."""
import os, tkinter
from unittest import mock

PDF = r"E:\Downloads\Girokonto_5443414341_Kontoauszug_20260802.pdf"

# settings.json + data.json + ui_state.json isoliert (nicht die echten ueberschreiben)
import kontoanalyse as K
K.SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "_test_settings.json")
K.DATA_FILE = os.path.join(os.path.dirname(__file__), "_test_data.json")
K.UI_FILE = os.path.join(os.path.dirname(__file__), "_test_ui.json")
for f in (K.SETTINGS_FILE, K.DATA_FILE, K.UI_FILE,
          K.SETTINGS_FILE + ".bak", K.DATA_FILE + ".bak"):
    if os.path.exists(f):
        os.remove(f)

with mock.patch.object(K.messagebox, "showinfo"), \
     mock.patch.object(K.messagebox, "showerror"):
    app = K.KontoApp()
    app.store.path = K.SETTINGS_FILE
    app._ingest([PDF], threaded=False)

    print("Buchungen:", len(app.transactions))
    assert len(app.transactions) == 48, "erwartete 48 Buchungen"

    inc = sum(t.betrag for t in app.transactions if t.betrag > 0)
    exp = sum(t.betrag for t in app.transactions if t.betrag < 0)
    print(f"Einnahmen {inc:.2f}  Ausgaben {exp:.2f}  Saldo {inc+exp:.2f}")
    assert abs((inc + exp) - 1288.32) < 0.01, "Saldo stimmt nicht"

    # Auto-Kategorisierung: Einnahmen -> Einkommen, ein paar Lebensmittel-Regeln
    cats = {}
    for t in app.transactions:
        cats[t.kategorie] = cats.get(t.kategorie, 0) + 1
    print("Kategorien:", cats)
    assert cats.get("Einkommen", 0) >= 2, "Einnahmen nicht als Einkommen erkannt"
    assert "Lebensmittel" in cats, "Lebensmittel-Regel griff nicht"

    # Manuelles Zuordnen + Regel merken
    t0 = app.transactions[0]
    app._row_map = {}
    iid = app.tree.get_children()[0]
    app.tree.selection_set(iid)
    app._row_map[iid] = t0
    app.remember_rule.set(True)
    app.assign_cat.set("Miete & Wohnen")
    app._assign_selected()
    assert t0.kategorie == "Miete & Wohnen"
    assert any(r["category"] == "Miete & Wohnen" for r in app.store.rules), "Regel nicht gespeichert"
    print("Zuordnung + Regel OK, Regelanzahl:", len(app.store.rules))

    # settings.json wurde geschrieben und ist wieder ladbar
    import json
    with open(K.SETTINGS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    assert data["rules"] and data["categories"], "settings.json unvollstaendig"
    assert data["overrides"], "override nicht gespeichert"

    # Eigene Kategorie im GUI anlegen (Dialog gemockt) + gleich zuweisen
    class FakeDialog:
        def __init__(self, *a, **k):
            self.result = ("Urlaub", "#123456")
    with mock.patch.object(K, "CategoryDialog", FakeDialog):
        iid2 = app.tree.get_children()[1]
        app.tree.selection_set(iid2)
        app._row_map[iid2] = app.transactions[1]
        app._quick_add_category()
    assert "Urlaub" in app.store.category_names(), "neue Kategorie fehlt"
    assert "Urlaub" in app.assign_cat["values"], "Dropdown nicht aktualisiert"
    assert app.transactions[1].kategorie == "Urlaub", "nicht direkt zugewiesen"
    assert app.store.color_of("Urlaub") == "#123456", "Farbe nicht gespeichert"
    print("Neue Kategorie via GUI + Direktzuweisung OK")

    # Charts: jeden Typ einmal zeichnen (darf nicht crashen)
    for i in range(len(K.CHART_TYPES)):
        app.chart_type.current(i)
        app.draw_chart()
    print(f"Alle {len(K.CHART_TYPES)} Diagrammtypen gezeichnet OK")

    # Synthetischer Vormonat (Juni) fuer Vergleich/Trend/Abo + KPI-Deltas
    import copy, datetime
    for t in list(app.transactions):
        if t.monat != "2026-07":
            continue
        c = copy.copy(t)
        c.datum = t.datum.replace(month=6, day=min(t.datum.day, 28))
        c.monat = "2026-06"
        app.transactions.append(c)
    app._rebuild_month_filters()

    assert len(app._period_txns("2026")) == len(app.transactions), "Jahresfilter falsch"
    assert len(app._period_txns("2026-06")) == 48, "Monatsfilter falsch"
    assert app._prev_period("2026-07") == "2026-06"
    assert app._prev_period("2026") == "2025"
    assert app._prev_period("Alle") is None

    app.chart_month.set("2026-07")               # hat jetzt Vorperiode Juni
    for i in range(len(K.CHART_TYPES)):
        app.chart_type.current(i)
        app.draw_chart()
    # KPI-Deltas muessen gesetzt sein (Juli vs Juni)
    assert app.kpi_cards["expense"]["value"].cget("text"), "KPI-Wert leer"
    print("Vergleich/Trend/Abo mit 2 Monaten + KPI-Deltas OK")

    # Neue Features: Parser-Metadaten, Reconciliation, Split, Exclude, Budget, Export
    st = K.parse_pdf(PDF)
    assert st.konto and st.iban and st.alter_saldo is not None, "Statement-Metadaten fehlen"
    assert st.reconciles is True, "Reconciliation sollte stimmen"
    assert len(app.statements) >= 1, "Statement-Meta nicht gespeichert"

    # Split: erste Buchung 60/40 aufteilen
    t0 = app.transactions[0]
    half = round(t0.betrag / 2, 2)
    app.store.set_split(t0, [{"category": "Lebensmittel", "betrag": half},
                             {"category": "Sonstiges", "betrag": round(t0.betrag - half, 2)}])
    parts = app.store.parts(t0)
    assert len(parts) == 2 and abs(sum(p[1] for p in parts) - t0.betrag) < 0.01, "Split falsch"

    # Exclude: interne Umbuchung zaehlt nicht als Ausgabe
    inc1, exp1 = app._income_expense(app.transactions)
    app.store.set_excluded("Sparen/Anlage", True)
    inc2, exp2 = app._income_expense(app.transactions)
    assert exp2 <= exp1, "Ausschluss senkt Ausgaben nicht"
    app.store.set_excluded("Sparen/Anlage", False)

    # Regel-Prioritaet: laengeres Stichwort gewinnt
    app.store.add_rule("VISA", "Shopping")
    app.store.add_rule("VISA REWE 435 HANNOVER", "Lebensmittel")
    tt = K.Transaction.from_dict({"datum": "2026-07-01", "buchungsart": "Lastschrift",
                                  "empfaenger": "VISA REWE 435 HANNOVER", "zweck": "",
                                  "betrag": -10.0, "monat": "2026-07", "quelle": "x"})
    assert app.store._rule_category(tt) == "Lebensmittel", "Regel-Prioritaet falsch"

    # Betragsgrenze
    app.store.add_rule("MIETE", "Miete & Wohnen", amount_min=500)
    tlow = K.Transaction.from_dict({"datum": "2026-07-01", "buchungsart": "x",
                                    "empfaenger": "MIETE klein", "zweck": "",
                                    "betrag": -50.0, "monat": "2026-07", "quelle": "x"})
    assert app.store._rule_category(tlow) != "Miete & Wohnen", "Betragsgrenze ignoriert"

    # Budget setzen + Budget-Chart
    app.store.set_budget("Lebensmittel", 300)
    app.chart_type.set(K.CHART_BUDGET)
    app.draw_chart()
    print("Metadaten/Split/Exclude/Regeln/Budget OK")

    # CSV-Export
    import csv, tempfile
    csvpath = os.path.join(os.path.dirname(__file__), "_test_export.csv")
    with mock.patch.object(K.filedialog, "asksaveasfilename", return_value=csvpath):
        app.export_csv()
    assert os.path.exists(csvpath), "CSV nicht exportiert"
    os.remove(csvpath)

    # CSV-Import (Auto-Erkennung, deutsches Zahlenformat)
    csvin = os.path.join(os.path.dirname(__file__), "_test_import.csv")
    with open(csvin, "w", encoding="utf-8") as f:
        f.write("Buchungstag;Betrag;Auftraggeber/Empfänger;Verwendungszweck\n")
        f.write("01.07.2026;-12,34;REWE Markt;Einkauf\n")
        f.write("02.07.2026;1.234,56;Arbeitgeber GmbH;Gehalt Juli\n")
    st_csv = K.parse_csv(csvin)
    assert len(st_csv.transactions) == 2, "CSV-Import Zeilenzahl falsch"
    assert abs(st_csv.transactions[1].betrag - 1234.56) < 0.01, "CSV-Betrag falsch"
    assert abs(st_csv.transactions[0].betrag + 12.34) < 0.01, "CSV-Vorzeichen falsch"
    os.remove(csvin)
    print("CSV-Import (Auto) OK")

    # UI-State speichern/laden
    app._save_ui_state()
    assert os.path.exists(K.UI_FILE), "UI-State nicht gespeichert"
    print("CSV-Export + UI-State OK")

    # Markiertes Konto-PDF (koordinaten-bewusster Lesepfad + Overlay)
    import highlight
    bookings = list(highlight._iter_bookings(PDF))
    assert len(bookings) == 48, f"Highlight-Parser: erwartet 48, war {len(bookings)}"
    src_dates = sorted((t.datum, round(t.betrag, 2)) for t in K.parse_pdf(PDF).transactions)
    hi_dates = sorted((b.datum, round(b.betrag, 2)) for b in bookings)
    assert src_dates == hi_dates, "Highlight- und Text-Parser uneinig (Datum/Betrag)"
    try:
        import pypdf, reportlab  # noqa: F401
        have_pdf_libs = True
    except ImportError:
        have_pdf_libs = False
    if have_pdf_libs:
        st_hi = K.parse_pdf(PDF)
        buckets = {}
        for t in st_hi.transactions:
            buckets.setdefault((t.datum, round(t.betrag, 2)), []).append(
                app.store.categorize(t))
        def _resolve(d, a):
            q = buckets.get((d, round(a, 2)))
            return q.pop(0) if q else None
        outpdf = os.path.join(os.path.dirname(__file__), "_test_markiert.pdf")
        n, cats = highlight.create_highlighted_pdf(
            PDF, outpdf, _resolve, app.store.color_of)
        assert n == 48, f"markiert: erwartet 48, war {n}"
        assert cats, "keine Kategorien in Legende"
        from pypdf import PdfReader
        src_pages = len(PdfReader(PDF).pages)
        out_pages = len(PdfReader(outpdf).pages)
        assert out_pages == src_pages + 1, "Legendenseite fehlt"
        os.remove(outpdf)
        print(f"Markiertes PDF: 48 Buchungen, {len(cats)} Kategorien, +Legende OK")
    else:
        print("Markiertes PDF: Overlay übersprungen (pypdf/reportlab fehlen), Parser OK")

    # Dark Mode: umschalten und alle Charts fehlerfrei zeichnen
    app._dark_var.set(True)
    app._toggle_theme()
    assert app.theme == "dark", "Theme nicht umgeschaltet"
    for i in range(len(K.CHART_TYPES)):
        app.chart_type.current(i)
        app.draw_chart()
    app._dark_var.set(False)
    app._toggle_theme()
    print("Dark Mode + alle Charts OK")

    app.destroy()

    # Persistenz: data.json muss existieren; neue Instanz laedt ohne PDF
    assert os.path.exists(K.DATA_FILE), "data.json wurde nicht geschrieben"
    app2 = K.KontoApp()
    app2.store.path = K.SETTINGS_FILE
    assert len(app2.transactions) == 48, \
        f"Persistenz: erwartet 48 geladen, war {len(app2.transactions)}"
    # erneutes Einlesen desselben PDFs darf nichts duplizieren
    app2._ingest([PDF], threaded=False)
    assert len(app2.transactions) == 48, "Dedupe ueber Neustart fehlgeschlagen"
    print("Persistenz: 48 Buchungen aus data.json geladen, Dedupe OK")
    app2.destroy()

    # Verschlüsselung: aktivieren, verschlüsselt speichern, mit Passwort neu laden
    if K.KontoApp._crypto() is not None:
        app3 = K.KontoApp()
        app3.store.path = K.SETTINGS_FILE
        n_before = len(app3.transactions)
        app3._enc_salt = os.urandom(16)
        app3._enc_key = app3._derive_key("geheim", app3._enc_salt)
        app3._encrypted = True
        app3._save_data()
        app3.destroy()
        with open(K.DATA_FILE, "rb") as f:
            assert f.read(8) == b"IAAHENC1", "nicht verschlüsselt gespeichert"
        import tkinter.simpledialog as sd
        with mock.patch.object(sd, "askstring", return_value="geheim"):
            app4 = K.KontoApp()
            app4.store.path = K.SETTINGS_FILE
        assert len(app4.transactions) == n_before, "verschlüsselt laden fehlgeschlagen"
        app4.destroy()
        print("Verschlüsselung: Speichern/Laden mit Passwort OK")
    else:
        print("Verschlüsselung übersprungen (cryptography fehlt)")

for f in (K.SETTINGS_FILE, K.DATA_FILE, K.UI_FILE,
          K.SETTINGS_FILE + ".bak", K.DATA_FILE + ".bak"):
    if os.path.exists(f):
        os.remove(f)
print("\nALLE TESTS BESTANDEN")
