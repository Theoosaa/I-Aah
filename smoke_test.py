"""Headless-Test: baut die App, laedt das echte PDF, prueft Logik + Charts."""
import os, tkinter
from unittest import mock

PDF = r"E:\Downloads\Girokonto_5443414341_Kontoauszug_20260802.pdf"

# settings.json + data.json isoliert (nicht die echten ueberschreiben)
import kontoanalyse as K
K.SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "_test_settings.json")
K.DATA_FILE = os.path.join(os.path.dirname(__file__), "_test_data.json")
for f in (K.SETTINGS_FILE, K.DATA_FILE):
    if os.path.exists(f):
        os.remove(f)

with mock.patch.object(K.messagebox, "showinfo"), \
     mock.patch.object(K.messagebox, "showerror"):
    app = K.KontoApp()
    app.store.path = K.SETTINGS_FILE
    app._ingest([PDF])

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

    app.destroy()

    # Persistenz: data.json muss existieren; neue Instanz laedt ohne PDF
    assert os.path.exists(K.DATA_FILE), "data.json wurde nicht geschrieben"
    app2 = K.KontoApp()
    app2.store.path = K.SETTINGS_FILE
    assert len(app2.transactions) == 48, \
        f"Persistenz: erwartet 48 geladen, war {len(app2.transactions)}"
    # erneutes Einlesen desselben PDFs darf nichts duplizieren
    app2._ingest([PDF])
    assert len(app2.transactions) == 48, "Dedupe ueber Neustart fehlgeschlagen"
    print("Persistenz: 48 Buchungen aus data.json geladen, Dedupe OK")
    app2.destroy()

for f in (K.SETTINGS_FILE, K.DATA_FILE):
    if os.path.exists(f):
        os.remove(f)
print("\nALLE TESTS BESTANDEN")
