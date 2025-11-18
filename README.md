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
CLI – Schnellstart
1) Market-only (ohne Bias), No-Overflow
bash
Code kopieren
python -m simple_srl_sim.cli ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --outdir .\out\run_market_only_no_overflow ^
  --no-overflow
2) Market + Bias-Reserve (fixed share), No-Overflow
bash
Code kopieren
python -m simple_srl_sim.cli ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --bias-share-pct 20 --target-soc-pct 50 --deadband-pct 3 ^
  --outdir .\out\run_bias_no_overflow ^
  --no-overflow
3) Dasselbe mit Overflow
Füge --overflow hinzu (der SoC darf temporär <0 %/>100 % werden, nur (Y) begrenzt).

YAML-Konfiguration (empfohlen)
Lege z. B. config.yml an:

yaml
Code kopieren
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
Run:

bash
Code kopieren
python -m simple_srl_sim.cli --config .\config.yml
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
python -m simple_srl_sim.compare_market_only_overflow ^
  --input .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --compare-to awarded ^
  --cap-mwh 2 --power-mw 1 --soc0-pct 50 ^
  --price-csv .\out\2024_ymax_100\srl_activation_vs_awarded_2024.csv ^
  --outdir .\out\market_only_overflow_compare
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
tbd. – intern Eniwa; Rückfragen an cedric.roetheli@eniwa.ch
