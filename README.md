
# Simple SRL Simulator (Market-Only) — first iteration

**Was es macht:** simuliert einen Speicher (Kapazität `X` [MWh], Nennleistung `Y` [MW])
rein nach dem *Netto-SRL-Aktivierungssignal* — **ohne** Bias, **ohne** Recovery.  
Es wird **nur der Markt** gefahren und hart an physikalischen Grenzen geklippt.

## Eingabedatei
Eine CSV mit mindestens:
- `timestamp` (ISO), 15-min Raster
- **Eines** dieser Sets:
  - `pct_net` (%): Netto-Aktivierung (SRL+ minus SRL−), **oder**
  - `pos_power_mw`, `neg_power_mw`, **und** `offered_plus_mw`, `offered_minus_mw` (bzw. `awarded_*`)

Wenn `pct_net` fehlt, wird es aus `pos/neg` relativ zu `--compare-to` (`offered`/`awarded`) berechnet:
```
pct_pos = 100 * pos_power_mw / max(offered_plus_mw, eps)
pct_neg = 100 * neg_power_mw / max(offered_minus_mw, eps)
pct_net = pct_pos - pct_neg
```

## Modell
- Zeitschritt: Δt = 0.25 h
- Headroom:
  - Entladen:  H⁺ = min(Y, s/Δt)
  - Laden:     H⁻ = min(Y, (X−s)/Δt)
- Marktleistung: Pᵐ = clip(Y * pct_net/100, −H⁻, +H⁺)
- Setpoint: P^{cmd} = Pᵐ
- SoC-Update: s_{t+1} = s_t − P^{cmd} Δt (Clipping auf [0, X])

## Installation (optional)
```
pip install -e .
```

## Ausführen
```
python -m simple_srl_sim.cli   --input out/2024_ymax_100/srl_activation_vs_offered_2024.csv   --compare-to offered   --cap-mwh 2   --power-mw 1   --soc0-pct 50   --outdir out/first_iter
```

## Outputs
- CSV: `<prefix>_sim_market_only.csv` mit u. a. `timestamp, pct_net, mkt_power_mw, cmd_power_mw, executed_mwh, soc_pct`
- Plots:
  - `<prefix>_soc.png`  (SoC-Verlauf)
  - `<prefix>_power.png` (Leistung, steps-pre)
  - `<prefix>_pct_net.png` (Netto-Aktivierung %)
