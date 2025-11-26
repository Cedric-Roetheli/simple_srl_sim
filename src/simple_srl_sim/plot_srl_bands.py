# file: plot_srl_bands.py
# SRL-Bänder ohne P_cmd:
#  - SRL+:  +30..+100 % (hellgrau)
#  - SRL−:  -30..-100 % (hellgrau)
#  - Mitte: -30..+30 % grob schraffiert
#  - Y: -110..+110 %, Hilfslinien bei ±100 %

import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
import matplotlib.patches as mpatches
import matplotlib as mpl

# grobe Schraffur
mpl.rcParams["hatch.linewidth"] = 1.5  # dicker = grober

p = argparse.ArgumentParser(description="SRL-Bänder (ohne P_cmd) plotten")
p.add_argument("--csv", required=True, help="Pfad zur CSV (z. B. srl_activation_vs_awarded_2024.csv)")
p.add_argument("--out", default="srl_bands.png", help="Ausgabedatei (PNG)")
args = p.parse_args()

csv_path = Path(args.csv)
df = pd.read_csv(csv_path)

# X-Achse (Zeit, falls vorhanden)
has_ts = "timestamp" in df.columns
if has_ts:
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if len(df) == 0:
        raise SystemExit("Keine gültigen Zeitstempel gefunden.")
    x = df["timestamp"]
    x_min, x_max = x.min(), x.max()
else:
    if len(df) == 0:
        raise SystemExit("CSV ist leer.")
    x = range(len(df))
    x_min, x_max = 0, len(df) - 1

fig, ax = plt.subplots(figsize=(12, 5))

# Ausdehnung über die gesamte Breite
ax.set_xlim(x_min, x_max)
ax.set_ylim(-110, 110)

# Hilfslinien ±100 %
ax.axhline(100, linestyle="--", linewidth=1.5)
ax.axhline(-100, linestyle="--", linewidth=1.5)
ax.axhline(30,  linestyle="--", linewidth=1.5)
ax.axhline(-30, linestyle="--", linewidth=1.5)


# Bänder: leichte graue Färbung
ax.axhspan(30, 100,  facecolor="0.9", zorder=0)   # SRL+
ax.axhspan(-100, -30, facecolor="0.9", zorder=0)  # SRL−

# Mitte schraffieren (robust via Rectangle + Daten-Y / Achsen-X)
trans = mtransforms.blended_transform_factory(ax.transAxes, ax.transData)
mid_rect = mpatches.Rectangle(
    (0.0, -30), 1.0, 60,                 # x=0..1 (volle Breite), y=-30..+30
    transform=trans,
    facecolor="none",
    edgecolor="0.6",                      # Farbe der Schraffur
    hatch="//",                           # grobe Schraffur
    linewidth=0.0,
    zorder=0
)
ax.add_patch(mid_rect)

# Labels (größer)
ax.text(0.5, 65,  "SRL+", ha="center", va="center", transform=trans, fontsize=18)
ax.text(0.5, -65, "SRL−", ha="center", va="center", transform=trans, fontsize=18)

ax.set_ylabel("Leistung [% von Y]")
ax.set_xlabel("Zeit" if has_ts else "Index")
ax.set_title("Vorhaltung der Leistung für SRL")

# Grid AUS (verhindert feine Hintergrundlinien)
ax.grid(False)

fig.tight_layout()
fig.savefig(args.out, dpi=150)
print(f"Plot gespeichert: {args.out}")
