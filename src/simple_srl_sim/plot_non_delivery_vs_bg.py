
import argparse
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def map_leniency(L: float):
    L = max(0.0, min(1.0, float(L)))
    bin_duty      = 1.0 - 0.7 * L   # 1.0 -> 0.3
    gate_abs_pct  = 7.0 * L         # 0   -> 7 %
    epsilon_mw    = 0.01 * L        # 0   -> 0.01 MW
    return bin_duty, gate_abs_pct, epsilon_mw

def load_bg_prices(bg_csv: Path) -> pd.DataFrame:
    bg = pd.read_csv(bg_csv)
    if 'timestamp_utc' not in bg.columns:
        raise ValueError("BG-CSV muss 'timestamp_utc' enthalten.")
    bg['timestamp_utc'] = pd.to_datetime(bg['timestamp_utc'], utc=True, errors='coerce')
    for c in ['BG_long_ct_per_kWh','BG_short_ct_per_kWh']:
        if c not in bg.columns:
            raise ValueError(f"BG-CSV Spalte fehlt: {c}")
        bg[c] = pd.to_numeric(bg[c], errors='coerce')
    # 1 ct/kWh = 10 CHF/MWh
    bg['BG_long_CHF_per_MWh']  = bg['BG_long_ct_per_kWh']  * 10.0
    bg['BG_short_CHF_per_MWh'] = bg['BG_short_ct_per_kWh'] * 10.0
    return bg[['timestamp_utc','BG_long_CHF_per_MWh','BG_short_CHF_per_MWh']].dropna()

def compute_non_delivery_points(sim_csv: Path, offer_up: float, offer_down: float, leniency: float):
    df = pd.read_csv(sim_csv, parse_dates=['timestamp'])
    # required columns
    need = ['timestamp','pct_net']
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Spalte {c} fehlt in {sim_csv}.")
    # headrooms (either provided or derive from market_*)
    if 'headroom_discharge_mw' in df.columns and 'headroom_charge_mw' in df.columns:
        hr_up = pd.to_numeric(df['headroom_discharge_mw'], errors='coerce')
        hr_dn = pd.to_numeric(df['headroom_charge_mw'], errors='coerce')
    elif {'market_budget_max_mw','market_power_mw'}.issubset(df.columns):
        lim = pd.to_numeric(df['market_budget_max_mw'], errors='coerce').fillna(0.0)
        pwr = pd.to_numeric(df['market_power_mw'], errors='coerce').fillna(0.0)
        hr_up = (lim - pwr).clip(lower=0.0)
        hr_dn = (lim + pwr).clip(lower=0.0)
    else:
        raise ValueError("Headrooms fehlen und können nicht abgeleitet werden.")

    # leniency mapping & gating
    bin_duty, gate_abs_pct, epsilon_mw = map_leniency(leniency)
    ts = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
    dt_s = ts.diff().dt.total_seconds().median()
    if not np.isfinite(dt_s) or dt_s <= 0:
        dt_s = 900.0
    eff_dt_h = (dt_s/3600.0) * bin_duty

    gate_up = (pd.to_numeric(df['pct_net'], errors='coerce') > gate_abs_pct).astype(float)
    gate_dn = (pd.to_numeric(df['pct_net'], errors='coerce') < -gate_abs_pct).astype(float)

    up_short_mw = (float(offer_up) - hr_up).clip(lower=0.0) * gate_up
    dn_short_mw = (float(offer_down) - hr_dn).clip(lower=0.0) * gate_dn

    up_short_mw = (up_short_mw - epsilon_mw).clip(lower=0.0)
    dn_short_mw = (dn_short_mw - epsilon_mw).clip(lower=0.0)

    out = pd.DataFrame({
        'timestamp': ts,
        'up_short_mwh': (up_short_mw * eff_dt_h).astype(float),
        'dn_short_mwh': (dn_short_mw * eff_dt_h).astype(float),
    })
    return out

def thin_points(df_pts: pd.DataFrame, col: str, frac: float, cap: int) -> pd.DataFrame:
    if df_pts.empty:
        return df_pts
    thr = df_pts[col].quantile(max(0.0, 1.0 - frac))
    df_big = df_pts[df_pts[col] >= thr].copy()
    if len(df_big) > cap:
        return df_big.nlargest(cap, col).copy()
    return df_big

def make_plots(sim_csv: Path, bg_csv: Path, offer_up: float, offer_down: float,
               leniency: float, up_color: str, down_color: str,
               out_short_png: Path, out_long_png: Path,
               keep_frac: float, cap_points: int):
    # Compute non-delivery energy per bin
    nd = compute_non_delivery_points(sim_csv, offer_up, offer_down, leniency)
    # Load BG prices
    bg = load_bg_prices(bg_csv)
    # Merge asof
    merged = pd.merge_asof(nd.sort_values('timestamp'),
                           bg.rename(columns={'timestamp_utc':'timestamp'}).sort_values('timestamp'),
                           on='timestamp', direction='nearest', tolerance=pd.Timedelta('15min'))

    # Filter points with non-zero shortfall
    up_nd = merged[merged['up_short_mwh'] > 0].copy()
    dn_nd = merged[merged['dn_short_mwh'] > 0].copy()

    up_plot = thin_points(up_nd, 'up_short_mwh', keep_frac, cap_points)
    dn_plot = thin_points(dn_nd, 'dn_short_mwh', keep_frac, cap_points)

    # Plot 1: BG_short + UP non-delivery (crosses in desired color)
    fig1, ax1 = plt.subplots(figsize=(12, 4))
    ax1.plot(merged['timestamp'], merged['BG_short_CHF_per_MWh'])
    if not up_plot.empty:
        size = (up_plot['up_short_mwh'] / max(1e-12, up_plot['up_short_mwh'].max())) * 80.0 + 10.0
        ax1.scatter(up_plot['timestamp'], up_plot['BG_short_CHF_per_MWh'],
                    s=size, marker='x', c=up_color, linewidths=1.0)
    ax1.set_title('BG_short (CHF/MWh) und UP‑Nichtlieferungen (Größe ~ MWh)')
    ax1.set_xlabel('Zeit'); ax1.set_ylabel('CHF/MWh')
    fig1.tight_layout(); fig1.savefig(out_short_png, dpi=150)

    # Plot 2: BG_long + DOWN non-delivery (crosses in desired color)
    fig2, ax2 = plt.subplots(figsize=(12, 4))
    ax2.plot(merged['timestamp'], merged['BG_long_CHF_per_MWh'])
    if not dn_plot.empty:
        size = (dn_plot['dn_short_mwh'] / max(1e-12, dn_plot['dn_short_mwh'].max())) * 80.0 + 10.0
        ax2.scatter(dn_plot['timestamp'], dn_plot['BG_long_CHF_per_MWh'],
                    s=size, marker='x', c=down_color, linewidths=1.0)
    ax2.set_title('BG_long (CHF/MWh) und DOWN‑Nichtlieferungen (Größe ~ MWh)')
    ax2.set_xlabel('Zeit'); ax2.set_ylabel('CHF/MWh')
    fig2.tight_layout(); fig2.savefig(out_long_png, dpi=150)

def main():
    ap = argparse.ArgumentParser(description="Plotte BG-Preise und Nichtlieferungen (UP/DOWN) mit farbigen Kreuz-Markern.")
    ap.add_argument("--sim", type=str, default="/mnt/data/sim_market_only.csv", help="Pfad zur unkorri­gierten Simulation (CSV).")
    ap.add_argument("--bg-csv", type=str, default="/mnt/data/swissgrid_balance_energy_prices_2024_timeseries_UTC.csv", help="BG-Preis-CSV.")
    ap.add_argument("--offer-up", type=float, default=0.2, help="Angebot SRL+ (MW)")
    ap.add_argument("--offer-down", type=float, default=0.2, help="Angebot SRL- (MW)")
    ap.add_argument("--leniency", type=float, default=0.6, help="0..1 Lockerung (0=streng, 1=locker)")
    ap.add_argument("--up-color", type=str, default="crimson", help="Farbe für UP-Kreuze (z. B. 'crimson' oder '#d62728')")
    ap.add_argument("--down-color", type=str, default="royalblue", help="Farbe für DOWN-Kreuze")
    ap.add_argument("--keep-frac", type=float, default=0.25, help="obere Fraktion nach Energie, die geplottet wird (0..1)")
    ap.add_argument("--cap-points", type=int, default=2000, help="max. Anzahl Punkte pro Plot")
    ap.add_argument("--out-short-png", type=str, default="/mnt/data/non_delivery_vs_bg_short.png")
    ap.add_argument("--out-long-png",  type=str, default="/mnt/data/non_delivery_vs_bg_long.png")
    args = ap.parse_args()

    make_plots(
        sim_csv=Path(args.sim),
        bg_csv=Path(args.bg_csv),
        offer_up=args.offer_up,
        offer_down=args.offer_down,
        leniency=args.leniency,
        up_color=args.up_color,
        down_color=args.down_color,
        out_short_png=Path(args.out_short_png),
        out_long_png=Path(args.out_long_png),
        keep_frac=args.keep_frac,
        cap_points=args.cap_points
    )

if __name__ == "__main__":
    main()
