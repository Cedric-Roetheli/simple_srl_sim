# file: plot_storage_power_with_bias.py
# Zweck: Speicher-Leistung (P_cmd) aus SRL-CSV rekonstruieren und als % von Y plotten
# Anpassungen: (1) Es wird NUR P_cmd geplottet. (2) Bias-Linien hart auf ±30 %.

import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ---------- CLI ----------
p = argparse.ArgumentParser(description="Plot Speicherleistung (nur P_cmd) mit festen Bias-Leitlinien ±30 %")
p.add_argument("--csv", dest="csv_path", required=True, help="Pfad zur CSV (z. B. srl_activation_vs_awarded_2024.csv)")
p.add_argument("--power-mw", type=float, default=1.0, help="Y: Nennleistung in MW (default: 1.0)")
p.add_argument("--cap-mwh", type=float, default=2.0, help="X: Kapazität in MWh (default: 2.0)")
p.add_argument("--soc0", type=float, default=50.0, help="Start-SoC in % (default: 50)")
p.add_argument("--bias-share-pct", type=float, default=20.0, help="(Modell) Bias-Reserve in % von Y (default: 20)")
p.add_argument("--target-soc-pct", type=float, default=50.0, help="Ziel-SoC in % (default: 50)")
p.add_argument("--deadband-pct", type=float, default=3.0, help="Deadband ± um Ziel-SoC (default: 3)")
p.add_argument("--overflow", action="store_true", help="Overflow erlauben (sonst No-Overflow)")
p.add_argument("--compare-to", choices=["awarded", "offered"], default="awarded",
               help="Basis für Fallback-Berechnung von pct_net (default: awarded)")
# Zeitfenster
p.add_argument("--start", type=str, help="Start-Zeitpunkt (z. B. 2024-07-01 oder 2024-07-01T06:00)")
p.add_argument("--end", type=str, help="End-Zeitpunkt EXKLUSIV (z. B. 2024-08-01 oder 2024-07-31T23:00)")
p.add_argument("--iso-year", type=int, help="ISO-Jahr für Wochenfilter (z. B. 2024)")
p.add_argument("--iso-weeks", type=str, help="ISO-Wochen (z. B. '20-24' oder '5,7,9')")
p.add_argument("--out", type=str, default="storage_power_cmd_percent.png", help="Ausgabedatei (PNG)")
args = p.parse_args()

# ---------- Konfiguration ----------
CSV_PATH = Path(args.csv_path)
POWER_MW = args.power_mw
CAP_MWH  = args.cap_mwh
SOC0_PCT = args.soc0
BIAS_SHARE_PCT = args.bias_share_pct         # wirkt nur im Modell
TARGET_SOC_PCT = args.target_soc_pct
DEADBAND_PCT   = args.deadband_pct
OVERFLOW       = args.overflow
COMPARE_TO     = args.compare_to
OUT_PNG        = args.out

MAX_Y_PCT      = 110.0                       # Achsenlimit ±110 %
BIAS_GUIDE_PCT = 30.0                        # VISUELLE Leitlinien: fest auf ±30 %

# ---------- Daten laden ----------
df = pd.read_csv(CSV_PATH)

# Zeitspalte
has_ts = "timestamp" in df.columns
if has_ts:
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

# Helpers
def safe_div(a, b):
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    out = np.zeros_like(a)
    mask = np.abs(b) > 1e-12
    out[mask] = a[mask] / b[mask]
    return out

def parse_iso_weeks(s: str):
    s = (s or "").strip()
    if not s:
        return None
    weeks = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            lo, hi = (a, b) if a <= b else (b, a)
            weeks.update(range(lo, hi + 1))
        else:
            weeks.add(int(part))
    return weeks

def parse_endpoint(txt: str, is_end: bool):
    ts = pd.to_datetime(txt, errors="raise")
    if is_end and (len(txt) <= 10):  # "YYYY-MM-DD" -> exklusiv, +1 Tag
        ts = ts + pd.Timedelta(days=1)
    return ts

# pct_net bereitstellen (falls fehlt)
if "pct_net" not in df.columns:
    pos = df.get("pos_power_mw", pd.Series(np.zeros(len(df))))
    neg = df.get("neg_power_mw", pd.Series(np.zeros(len(df))))
    if COMPARE_TO == "awarded":
        base_pos = df.get("awarded_plus_mw",  pd.Series(np.nan, index=df.index))
        base_neg = df.get("awarded_minus_mw", pd.Series(np.nan, index=df.index))
    else:
        base_pos = df.get("offered_plus_mw",  df.get("awarded_plus_mw",  pd.Series(np.nan, index=df.index)))
        base_neg = df.get("offered_minus_mw", df.get("awarded_minus_mw", pd.Series(np.nan, index=df.index)))
    pct_pos = 100.0 * safe_div(pos, base_pos)
    pct_neg = 100.0 * safe_div(neg, base_neg)
    df["pct_net"] = pct_pos - pct_neg

# ---------- Zeitfenster anwenden ----------
mask = pd.Series(True, index=df.index)

if args.iso_year is not None:
    if "iso_year" not in df.columns:
        if not has_ts:
            raise SystemExit("ISO-Filter benötigt 'iso_year/iso_week' ODER eine 'timestamp'-Spalte.")
        isoy = df["timestamp"].dt.isocalendar().year
        isow = df["timestamp"].dt.isocalendar().week
        df["iso_year"] = isoy.astype(int)
        df["iso_week"] = isow.astype(int)
    mask &= (df["iso_year"].astype(int) == int(args.iso_year))

if args.iso_weeks:
    weeks = parse_iso_weeks(args.iso_weeks)
    if weeks:
        if "iso_week" not in df.columns:
            if not has_ts:
                raise SystemExit("ISO-Filter benötigt 'iso_year/iso_week' ODER eine 'timestamp'-Spalte.")
            df["iso_week"] = df["timestamp"].dt.isocalendar().week.astype(int)
        mask &= df["iso_week"].astype(int).isin(sorted(weeks))

if args.start:
    if not has_ts:
        raise SystemExit("--start benötigt eine 'timestamp'-Spalte.")
    t0 = parse_endpoint(args.start, is_end=False)
    mask &= (df["timestamp"] >= t0)

if args.end:
    if not has_ts:
        raise SystemExit("--end benötigt eine 'timestamp'-Spalte.")
    t1 = parse_endpoint(args.end, is_end=True)
    mask &= (df["timestamp"] < t1)

df = df.loc[mask].reset_index(drop=True)
if len(df) == 0:
    raise SystemExit("Filter hat keine Daten übriggelassen.")

# ---------- Zeitschritt dt erkennen (Fallback 15 min) ----------
if has_ts and len(df) >= 2:
    deltas = df["timestamp"].diff().dropna().dt.total_seconds()
    dt_h = float(deltas.median() / 3600.0) if len(deltas) and deltas.median() > 0 else 0.25
else:
    dt_h = 0.25

# ---------- Bias-Mechanismus & Simulation ----------
p_bias_max = POWER_MW * (BIAS_SHARE_PCT / 100.0)
market_clip = POWER_MW - p_bias_max

soc = np.zeros(len(df) + 1, dtype=float)
soc[0] = SOC0_PCT

p_req  = POWER_MW * (df["pct_net"].astype(float).to_numpy() / 100.0)
p_mkt  = np.clip(p_req, -market_clip, +market_clip)
p_cmd  = np.zeros(len(df), dtype=float)

lower_band = TARGET_SOC_PCT - DEADBAND_PCT
upper_band = TARGET_SOC_PCT + DEADBAND_PCT

for i in range(len(df)):
    s_prev = soc[i]
    # Bias aus s_prev Richtung Deadband-Kante (kein Lookahead)
    if lower_band <= s_prev <= upper_band:
        p_b = 0.0
    else:
        if s_prev < lower_band:
            delta_s = lower_band - s_prev
            p_b = - (delta_s / 100.0) * CAP_MWH / dt_h
        else:  # s_prev > upper_band
            delta_s = s_prev - upper_band
            p_b = + (delta_s / 100.0) * CAP_MWH / dt_h
    # Deckelung durch Bias-Reserve
    p_b = float(np.clip(p_b, -p_bias_max, +p_bias_max))

    p_cand = p_mkt[i] + p_b
    p_cand = float(np.clip(p_cand, -POWER_MW, +POWER_MW))

    if not OVERFLOW:
        s_next_free = s_prev - p_cand * dt_h * 100.0 / CAP_MWH
        if s_next_free > 100.0:
            p_cand = (s_prev - 100.0) * CAP_MWH / (dt_h * 100.0)
        elif s_next_free < 0.0:
            p_cand = (s_prev - 0.0) * CAP_MWH / (dt_h * 100.0)

    p_cmd[i] = p_cand
    soc[i+1] = s_prev - p_cmd[i] * dt_h * 100.0 / CAP_MWH

pct_cmd = 100.0 * p_cmd / POWER_MW

# ---------- Plot (nur P_cmd + feste Leitlinien) ----------
ts = df["timestamp"] if has_ts else pd.RangeIndex(len(df))
plt.figure(figsize=(12, 5))
plt.plot(ts, pct_cmd, linewidth=0.9, label="P_cmd")

# Hilfslinien ±100 %
plt.axhline(100, linestyle="--", linewidth=1)
plt.axhline(-100, linestyle="--", linewidth=1)

# Feste Bias-Leitlinien bei ±30 %
plt.axhline(+BIAS_GUIDE_PCT, linestyle=":", linewidth=1.2)
plt.axhline(-BIAS_GUIDE_PCT, linestyle=":", linewidth=1.2)

plt.ylim(-MAX_Y_PCT, +MAX_Y_PCT)
plt.ylabel("Leistung des Speichers [% von Y]")
plt.xlabel("Zeit" if has_ts else "Index")
plt.title(f"P_cmd  | feste Bias-Linien bei ±{int(BIAS_GUIDE_PCT)} %")
plt.legend(loc="upper right", ncol=1, fontsize=9)
plt.grid(True, axis="y", linewidth=0.3)
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=150)
print(f"Plot gespeichert: {OUT_PNG}  (dt={dt_h:.4f} h, N={len(df)})")
