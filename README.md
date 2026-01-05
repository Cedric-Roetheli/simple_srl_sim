# Simple SRL Simulator

Simulation eines Batteriespeichers im Schweizer SRL-Kontext (SRL+/SRL−) auf 15-Minuten-Basis. Unterstützt **reinen Marktmodus** und **Markt + SoC-Korrektur (Bias)**, wahlweise **mit** oder **ohne Overflow**. Enthält Werkzeuge zum **Vergleich Overflow vs. No-Overflow** inkl. Energie- und Revenue-KPIs sowie aussagekräftige Plots.

> Dieses README ersetzt die erste, abgespeckte Iteration („Market-Only“) und erweitert sie um Bias-Reserve, Overflow-Vergleich, KPIs und neue Plots.

---

## Kernidee

- Der Speicher nimmt in jeder Viertelstunde am Markt teil, sobald die **Netto-Aktivierungsquote** ≠ 0 ist.  
- Er liefert (SRL+) oder nimmt auf (SRL−) die geforderte **Netto-Leistung**, begrenzt durch **Nennleistung (Y)** und – im Modus *ohne Overflow* – durch die **Energiegrenzen** (SoC 0–100 % bei Kapazität (X)).  
- Optional reservieren wir einen festen Anteil der Leistung für eine **SoC-Korrektur** (Bias) in Richtung Ziel-SoC; die Korrektur sieht **nicht** in das aktuelle Intervall, sondern basiert nur auf dem **Endzustand des Vorintervalls** (Deadband vermeidet unnötige Korrekturen).

---

## Daten & Spalten

### Markt-/Preisdaten (CSV)
Erwartete Spalten (mindestens):
- `timestamp` (ISO, 15-min Raster)
- **Aktivierung**:
  - direkt: `pct_net` (%), **oder**
  - abgeleitet aus: `pct_pos`, `pct_neg` **oder** `pos_power_mw`, `neg_power_mw` + `offered_*` / `awarded_*` (per `--compare-to offered|awarded`)
- **Preise** (optional, für Revenue/KPIs):  
  `price_pos` (= CHF/MWh für (P≥0)), `price_neg` (= CHF/MWh für (P<0))  
  (Alias-Namen wie `price_pos_chf_per_mwh`, `srl_pos_price_chf_per_mwh` werden automatisch erkannt.)

### Aus Excel bauen (optional)
Wenn du Swissgrid-Excel (`EnergieUebersichtCH-2024.xlsx`) und Marktergebnis-CSV hast, kannst du mit `build_market_csv.py` ein konsolidiertes CSV mit Timestamp, Aktivierung und Preisen erstellen (siehe Tools unten).

---

## Installation

```bash
# im Repo-Root
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate
# Editierbare Installation (empfohlen) – findet das src-Layout zuverlässig
pip install -e .
```

---

## CLI – Schnellstart

1) Market-only (ohne Bias), No-Overflow
Code kopieren
```bash
python -m simple_srl_sim.cli ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --outdir .\out\run_market_only_no_overflow ^
  --no-overflow
```
2) Market + Bias-Reserve (fixed share), No-Overflow
Code kopieren
```bash
python -m simple_srl_sim.cli ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --bias-share-pct 20 --target-soc-pct 50 --deadband-pct 3 ^
  --outdir .\out\run_bias_no_overflow ^
  --no-overflow
```
3) Dasselbe mit Overflow
Füge --overflow hinzu (der SoC darf temporär <0 %/>100 % werden, nur (Y) begrenzt).

YAML-Konfiguration (empfohlen)
Lege z. B. config.yml an:

yaml
Code kopieren
```bash
input: ".\\out\\2024_ymax_100\\srl_activation_vs_awarded_2024.csv"
compare_to: "awarded"        # oder "offered"

cap_mwh: 2
power_mw: 1
soc0_pct: 50

mode: "market_bias"          # "market_only" | "market_bias"
overflow: false              # true = Overflow

bias:
  share_pct: 20              # Anteil der Leistung Y für Korrektur
  target_soc_pct: 50
  deadband_pct: 3
  apply_only_if_needed: true # Korrektur nur, wenn außerhalb Deadband
  no_lookahead: true         # Korrektur kennt aktuelles Intervall nicht

time_window:
  start: "2024-03-01"
  end:   "2024-03-07"

plots:
  power_components: true
  energy_components: true
  # Power-Plot: schwarze Linie = „Netto-Leistung (gefahren)”
  net_mode: "cmd"            # "cmd" (gefahren) oder "market_minus_bias" (theoretisch)
  max_intervals: 96
  color_alpha: 0.55
  # Energy-Plot: SoC rechts mit fester Skala
  show_cum_net: false
  soc_ylim: [-10, 110]
```
Run:

bash
Code kopieren
```bash
python -m simple_srl_sim.cli --config .\config.yml
```
Mechanik (kurz)
Zeitschritt: Δt = 0.25 h.

Netto-Anforderung: P_req = Y · pct_net/100.

Marktanteil: Clipping auf ±(Y − P_bias,max) (bei Bias-Reserve), sonst ±Y.

Bias-Korrektur: Basierend auf dem End-SoC des Vorintervalls; nur so viel wie nötig bis zur Deadband-Kante, begrenzt durch P_bias,max.

Setpoint: P_cmd = P_markt + P_bias.

No-Overflow: zusätzlich Energie-Headroom (SoC 0–100 %); Overflow: nur Leistung Y limitiert.

SoC-Update: s_{t+1} = s_t − P_cmd·Δt.

Revenue (optional) pro Intervall: signierte Energie E = P_cmd·Δt × richtungsabhängiger Preis (pos/neg).

Plots
Leistungskomponenten (power_components.png)
Gestapelte Balken: SRL+/SRL−/Korrektur; schwarze Linie = Netto-Leistung (gefahren).

Energiekomponenten + SoC (energy_components.png)
Gestapelte Energiebalken pro Intervall; rechte SoC-Achse fix [−10 %, 110 %], rote Referenzlinien bei 0 % und 100 %; SoC-Linie durchgehend.

Für sehr lange Zeitfenster schalten die Funktionen automatisch auf Linien-Darstellung (Lesbarkeit).

KPIs & Overflow-Vergleich
Vergleichsskript
Modul ausführen (editiert installiert oder PYTHONPATH=src gesetzt):

bash
Code kopieren
```bash
python -m simple_srl_sim.compare_market_only_overflow ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --price-csv .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --outdir .\out\market_only_overflow_compare
```
Outputs

market_only_overflow_compare_timeseries.csv
(p_no_ov, p_ov, Energie pro Intervall, Preise, Revenue je Intervall)

market_only_overflow_kpis.csv
Summen & Mittel: *_pos_mwh, *_neg_mwh, *_abs_mwh, *_rev_chf, *_mean_abs_mw, gew. Preise etc.

Optionaler Kurzbericht:
summarize_overflow_kpis.py erzeugt market_only_overflow_compare_summary.(csv|xlsx) mit:

Ohne Overflow | Mit Overflow | Differenz (ov − no)
(Gesamtenergie, Entladen/Laden, Nettoenergie, mittlere |P|, Revenue, Ø-Preise, Intervalle)

Hinweis Revenue:
Revenue wird aus signierter Energie und richtungsabhängigem Preis gebildet. So werden negative Preise korrekt abgebildet (z. B. Laden bei P<0 kann Einnahme sein).

Fehlerbehebung (typisch)
Modul nicht gefunden:
pip install -e . im Repo-Root oder set PYTHONPATH=%CD%\\src (PowerShell: $env:PYTHONPATH="$PWD\\src").

Keine Outputs beim Modul-Run:
Stelle sicher, dass am Ende der Datei if __name__ == "__main__": main() steht.

Pfadverwechslungen bei OneDrive:
Verwende absolute Pfade bei --input und --outdir oder Variablen wie $PWD.

Lizenz / Kontakt
tbd. – intern Eniwa; Rückfragen an @cedric.roetheli.

---

# Erweiterungen (Stand: 2025-11-26)

Die folgenden Funktionen ergänzen das bestehende Projekt **ohne** bestehende Inhalte zu ersetzen. Sie sind rückwärtskompatibel und optional einsetzbar.

## 1) Wöchentliche Nichtverfügbarkeit & Pönalen
**Datei:** `compute_srl_penalty_weeks.py`

Berechnet pro ISO‑Woche die Nichtverfügbarkeit (MW·s) in SRL+/- und leitet daraus die Pönale nach Swissgrid‑Logik ab (Schwellwert standardmäßig **0,1 %**, volumengewichtete Kapazitätspreise, **Faktor 10**, **Mindestpönale 250 CHF/Woche**).

**Wichtige Optionen**
- `--csv` Eingabe‑CSV (Simulation)
- `--price-csv` Swissgrid‑Auktionen (Kapazitätspreise)
- `--offer-up / --offer-down` Angebot in MW (symmetrisch oder einseitig)
- `--gate-by pct_net|market_power|cmd_power` (Defizite nur in aktiver Richtung zählen)
- `--leniency 0..1` **Ein‑Knopf‑Entschärfung** für 15‑min‑Bins (0 = streng, 1 = praxisnah)

**Beispiel (beide Richtungen, praxisnah):**
```powershell
python compute_srl_penalty_weeks.py `
  --csv ".\sim_market_only.csv" `
  --price-csv ".\2024-PRL-SRL-TRL-Ergebnis.csv" `
  --offer-up 0.2 --offer-down 0.2 `
  --gate-by pct_net `
  --leniency 0.6 `
  --out-summary ".\out\weekly_availability_summary.csv" `
  --out-plot ".\out\penalty_weeks_soc.png" `
  --out-penalty-bar ".\out\penalty_weeks_bar.png"
```

**Outputs**
- `weekly_availability_summary.csv` – Wochenwerte inkl. Defizit‑Prozent und Pönalen
- `penalty_weeks_soc.png` – SoC‑Verlauf mit rot markierten Pönale‑Wochen
- `penalty_weeks_bar.png` – Balken (Pönalen je Woche)

---

## 2) Jahresvergleich: Korrektur vs. Nichtlieferung (2024)
**Datei:** `compare_correction_vs_non_delivery_2024.py`

Vergleicht zwei Betriebsweisen eines Speichers:
- **A „mit Korrektur“**: Differenz *korrigiert vs. unkorri­giert* wird **energieseitig** bepreist (Tarif oder BG).
- **B „ohne Korrektur“**: **Nichtlieferungen** (UP/DOWN) werden als **Ausgleichsenergie** bewertet; **Pönalen** optional integrierbar oder deaktivierbar.

**Inputs**
- `--sim-corrected` (z. B. `sim_fixed_bias.csv`)
- `--sim-uncorrected` (z. B. `sim_market_only.csv`; erkennt auch `mkt_power_mw`)
- `--bg-prices-csv` (UTC, 15‑min), `--capacity-prices-csv` (für Pönalen, wenn aktiv)
- `--offer-up / --offer-down`, `--leniency`

**Bewertung A (Korrektur)**
- `--correction-pricing tariff|bg` (Default: `tariff`)
- `--tariff-import-ct 22` (Bezug), `--tariff-export-ct 0.06` (Rückspeisung)  
  *(1 Rp/kWh = 10 CHF/MWh)*

**Bewertung B (Nichtlieferung)**
- `--non-delivery-cost-mode cashflow|cost`  
  *cashflow erlaubt negative BG‑Preise; cost klemmt <0 auf 0 (nicht‑negativ)*
- `--no-penalties` → Pönalen komplett ausblenden (nur Energieeffekte)
  
**Beispiel (ohne Pönalen, A=Tarif, B=„cost“):**
```powershell
python compare_correction_vs_non_delivery_2024.py `
  --sim-corrected ".\sim_fixed_bias.csv" `
  --sim-uncorrected ".\sim_market_only.csv" `
  --bg-prices-csv ".\swissgrid_balance_energy_prices_2024_timeseries_UTC.csv" `
  --capacity-prices-csv ".\2024-PRL-SRL-TRL-Ergebnis.csv" `
  --offer-up 0.2 --offer-down 0.2 `
  --leniency 0.6 `
  --correction-pricing tariff `
  --tariff-import-ct 22 `
  --tariff-export-ct 0.06 `
  --no-penalties `
  --non-delivery-cost-mode cost `
  --out-summary ".\out\correction_vs_non_delivery_2024_summary.csv" `
  --out-weekly ".\out\non_delivery_weekly.csv" `
  --out-bar ".\out\comparison_bar.png"
```

**Outputs**
- `correction_vs_non_delivery_2024_summary.csv` – Jahres‑KPIs A/B
- `non_delivery_weekly.csv` – Wochenwerte (bei `--no-penalties` Pönale‑Spalten = 0)
- `comparison_bar.png` – Balken A vs. B

**Hinweis BG_long vs. BG_short**
- Fehlende **UP‑Lieferung** → **BG_short** (zukaufen)  
- Fehlende **DOWN‑Lieferung** → **BG_long** (abnehmen)

---

## 3) Visualisierung: Ausgleichsenergie vs. Ausfälle
**Datei:** `plot_non_delivery_vs_bg.py`

Erzeugt zwei Grafiken, die das Timing‑Phänomen sichtbar machen:
1. **BG_short** (Linie) + **UP‑Nichtlieferungen** (Kreuze; Größe ~ MWh)
2. **BG_long**  (Linie) + **DOWN‑Nichtlieferungen** (Kreuze)

**Beispiel**
```powershell
python plot_non_delivery_vs_bg.py `
  --sim ".\sim_market_only.csv" `
  --bg-csv ".\swissgrid_balance_energy_prices_2024_timeseries_UTC.csv" `
  --offer-up 0.2 --offer-down 0.2 `
  --leniency 0.6 `
  --up-color "#e63946" `
  --down-color "darkgoldenrod" `
  --out-short-png ".\out\non_delivery_vs_bg_short.png" `
  --out-long-png  ".\out\non_delivery_vs_bg_long.png"
```

---

## Praktische Hinweise
- **PowerShell‑Zeilenumbruch**: Backtick \` als **allerletztes Zeichen** der Zeile (ohne Leerzeichen).  
- **Zeitzone**: BG‑CSV ist *UTC* – Simu‑Timestamps ebenfalls auf UTC bringen.  
- **Leniency‑Startwerte**: `0.5–0.7` für 15‑min‑Daten häufig praxistauglich.  
- **Einseitiges Angebot**: Nicht angebotene Richtung auf `0.0` setzen.

---

## Changelog
- **2025-11-26**: Ergänzt um Pönale‑Berechnung, Jahresvergleich Korrektur vs. Nichtlieferung, sowie BG‑Preis‑Plots. Bestehende Inhalte bleiben unverändert.
