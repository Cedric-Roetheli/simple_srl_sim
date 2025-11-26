
import argparse
import re
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# ------------------ Helpers ------------------

def ensure_headrooms(df):
    """
    Ensure columns 'headroom_discharge_mw' (SRL+) and 'headroom_charge_mw' (SRL-) exist.
    If missing, derive them from symmetric power limits:
      positive_limit = market_budget_max_mw
      negative_limit = -market_budget_max_mw
      headroom_discharge = max(0, positive_limit - market_power_mw)
      headroom_charge    = max(0, market_power_mw - negative_limit) = max(0, market_budget_max_mw + market_power_mw)
    """
    if ('headroom_discharge_mw' in df.columns) and ('headroom_charge_mw' in df.columns):
        return df
    if ('market_budget_max_mw' in df.columns) and ('market_power_mw' in df.columns):
        lim = pd.to_numeric(df['market_budget_max_mw'], errors='coerce').fillna(0.0)
        pwr = pd.to_numeric(df['market_power_mw'], errors='coerce').fillna(0.0)
        df = df.copy()
        df['headroom_discharge_mw'] = (lim - pwr).clip(lower=0.0)
        df['headroom_charge_mw'] = (lim + pwr).clip(lower=0.0)
        return df
    raise ValueError("Missing headroom columns and cannot derive from market_* columns.")


def infer_offers(df, q=0.95):
    up = round(float(np.nanquantile(df['headroom_discharge_mw'], q)), 3)
    down = round(float(np.nanquantile(df['headroom_charge_mw'], q)), 3)
    if up <= 0: up = float(df['headroom_discharge_mw'].max())
    if down <= 0: down = float(df['headroom_charge_mw'].max())
    up = round(float(up), 3)
    down = round(float(down), 3)
    return up, down

def compute_dt_seconds(df):
    deltas = df['timestamp'].diff().dt.total_seconds().dropna()
    if len(deltas) == 0:
        return 900.0
    med = float(np.median(deltas))
    if not np.isfinite(med) or med <= 0:
        med = 900.0
    return med

def iso_year_week(ts):
    iso = ts.isocalendar()
    return int(iso[0]), int(iso[1])

def extract_kw(ausschreibung):
    # Parse 'SRL_24_KW01' -> (2024, 1). Fallback: try 'KWxx' anywhere.
    if not isinstance(ausschreibung, str):
        return None, None
    m = re.search(r'(\d{2})_KW(\d{2})', ausschreibung)
    if m:
        year = 2000 + int(m.group(1))
        week = int(m.group(2))
        return year, week
    m2 = re.search(r'KW\s*?(\d{1,2})', ausschreibung)
    if m2:
        return None, int(m2.group(1))
    return None, None


def apply_direction_gating(df, mode, gate_abs_pct=0.0):
    """
    mode ∈ {None, 'pct_net', 'market_power', 'cmd_power'}.
    Binary gating by direction:
      - if mode='pct_net': up gate when pct_net > 0, down gate when pct_net < 0
      - if mode='market_power': up gate when market_power_mw > 0 (discharge), down gate when < 0 (charge)
      - if mode='cmd_power': same but using cmd_power_mw
    If mode is None, no gating (conservative).
    """
    if not mode or str(mode).lower() in ['none','false','0']:
        return df, None
    mode = str(mode).lower()
    df = df.copy()
    if mode == 'pct_net' and 'pct_net' in df.columns:
        thr = float(gate_abs_pct)
        up_mask = (df['pct_net'] > thr).astype(float)
        down_mask = (df['pct_net'] < -thr).astype(float)
    elif mode == 'market_power' and 'market_power_mw' in df.columns:
        up_mask = (df['market_power_mw'] > 0).astype(float)
        down_mask = (df['market_power_mw'] < 0).astype(float)
    elif mode == 'cmd_power' and 'cmd_power_mw' in df.columns:
        up_mask = (df['cmd_power_mw'] > 0).astype(float)
        down_mask = (df['cmd_power_mw'] < 0).astype(float)
    else:
        return df, None  # silently fall back to no gating
    df['gate_up'] = up_mask
    df['gate_down'] = down_mask
    return df, mode

# ------------------ Core logic ------------------

def weekly_penalties(df, offer_up_mw, offer_down_mw, threshold_pct=0.1, bin_duty=1.0, epsilon_mw=0.0, grace_minutes=0.0):
    dt_s = compute_dt_seconds(df)
    eff_dt = float(bin_duty) * dt_s
    df = df.copy()
    df['deficit_up_mw'] = (offer_up_mw - df['headroom_discharge_mw'] - float(epsilon_mw)).clip(lower=0.0)
    df['deficit_down_mw'] = (offer_down_mw - df['headroom_charge_mw'] - float(epsilon_mw)).clip(lower=0.0)
    df['deficit_up_mws'] = df['deficit_up_mw'] * eff_dt * (df['gate_up'] if 'gate_up' in df.columns else 1.0)
    df['deficit_down_mws'] = df['deficit_down_mw'] * eff_dt * (df['gate_down'] if 'gate_down' in df.columns else 1.0)
    df['seconds'] = dt_s

    iso_keys = df['timestamp'].apply(lambda t: iso_year_week(t))
    df['iso_year'] = [y for y, w in iso_keys]
    df['iso_week'] = [w for y, w in iso_keys]

    grp = df.groupby(['iso_year', 'iso_week'], as_index=False).agg(
        seconds_total=('seconds','sum'),
        up_mws=('deficit_up_mws','sum'),
        down_mws=('deficit_down_mws','sum'),
    )
    # Apply weekly grace minutes (per direction)
    grace_s = max(0.0, float(grace_minutes)) * 60.0
    if grace_s > 0:
        grp['up_mws'] = (grp['up_mws'] - np.minimum(grp['up_mws'], offer_up_mw * grace_s)).clip(lower=0.0)
        grp['down_mws'] = (grp['down_mws'] - np.minimum(grp['down_mws'], offer_down_mw * grace_s)).clip(lower=0.0)

    grp['denom_up_mws'] = offer_up_mw * grp['seconds_total']
    grp['denom_down_mws'] = offer_down_mw * grp['seconds_total']
    grp['pct_deficit_up'] = np.where(grp['denom_up_mws']>0, 100.0 * grp['up_mws'] / grp['denom_up_mws'], 0.0)
    grp['pct_deficit_down'] = np.where(grp['denom_down_mws']>0, 100.0 * grp['down_mws'] / grp['denom_down_mws'], 0.0)
    grp['penalty_up'] = grp['pct_deficit_up'] > threshold_pct
    grp['penalty_down'] = grp['pct_deficit_down'] > threshold_pct
    grp['penalty_any'] = grp['penalty_up'] | grp['penalty_down']
    return grp

def compute_week_grid(min_ts, max_ts):
    start = (min_ts - timedelta(days=min_ts.isoweekday()-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    grid = [start]
    while grid[-1] <= max_ts:
        grid.append(grid[-1] + timedelta(days=7))
    return grid

def week_bounds(df):
    bounds = {}
    for (y,w), sub in df.groupby(df['timestamp'].apply(lambda t: (t.isocalendar()[0], t.isocalendar()[1]))):
        d = sub['timestamp'].iloc[0]
        monday = (d - timedelta(days=d.isoweekday()-1)).replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = monday + timedelta(days=7)
        bounds[(int(y), int(w))] = (monday, week_end)
    return bounds

# ------------------ Plots ------------------

def plot_soc_with_penalty_weeks(df, weekly, outfile_png):
    fig, ax = plt.subplots(figsize=(12, 4))
    # Blue SoC line
    soc_line, = ax.plot(df['timestamp'], df['soc_pct'], label='SoC', color='blue')
    ax.set_xlabel('Time'); ax.set_ylabel('SoC [%]')
    ax.set_title('SoC mit Wochenrastern; Rot hinterlegt = Nichtverfügbarkeit von Regelleistung')
    # Red shaded penalty weeks
    bounds = week_bounds(df)
    for _, row in weekly.iterrows():
        if row['penalty_any']:
            y, w = int(row['iso_year']), int(row['iso_week'])
            start, end = bounds.get((y,w), (None, None))
            if start is not None and end is not None:
                ax.axvspan(start, end, color='red', alpha=0.12)
    # Thin weekly grid lines
    min_ts, max_ts = df['timestamp'].min(), df['timestamp'].max()
    for dt in compute_week_grid(min_ts, max_ts):
        ax.axvline(dt, linewidth=0.5, alpha=0.5)
    # Legend
    red_patch = Patch(facecolor='red', alpha=0.25, label='Nichtverfügbarkeit von Regelleistung')
    ax.legend(handles=[soc_line, red_patch], loc='upper left')
    fig.tight_layout()
    fig.savefig(outfile_png, dpi=150)

def plot_weekly_penalties_bar(weekly_df, outfile_png):
    labels = weekly_df.apply(lambda r: f"{int(r['iso_year'])}-W{int(r['iso_week']):02d}", axis=1)
    values = weekly_df['penalty_chf_total'].fillna(0.0).values
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(range(len(values)), values)
    ax.set_xticks(range(len(values)))
    if len(labels) > 0:
        step = max(1, len(labels)//20)
        shown = [lbl if i % step == 0 else "" for i, lbl in enumerate(labels)]
        ax.set_xticklabels(shown, rotation=45, ha='right')
    ax.set_ylabel('CHF')
    ax.set_title('Pönale (Nichtverfügbarkeit SRL) pro Woche')
    fig.tight_layout()
    fig.savefig(outfile_png, dpi=150)

# ------------------ Prices & Money ------------------

def read_weekly_capacity_prices(price_csv_path):
    dfp = pd.read_csv(price_csv_path, sep=";")
    dfp = dfp[dfp['Beschreibung'].str.contains("Secondary control", na=False)].copy()
    dfp = dfp[dfp['Land'] == 'CH']
    years, weeks = [], []
    for a in dfp['Ausschreibung']:
        y, w = extract_kw(a)
        years.append(y)
        weeks.append(w)
    dfp['iso_year'] = years
    dfp['iso_week'] = weeks
    dfp['iso_year'] = dfp['iso_year'].fillna(2024).astype(int)
    for col in ['Zugesprochenes Volumen','Angebotspreis']:
        dfp[col] = pd.to_numeric(dfp[col], errors='coerce')
    up = dfp[dfp['Beschreibung'].str.contains("SRL\\+", regex=True, na=False)]
    down = dfp[dfp['Beschreibung'].str.contains("SRL\\-", regex=True, na=False)]
    def wavg(g):
        w = g['Zugesprochenes Volumen'].clip(lower=0)
        p = g['Angebotspreis']
        if w.sum() > 0:
            return (p * w).sum() / w.sum()
        return np.nan
    price_up = up.groupby(['iso_year','iso_week']).apply(wavg).reset_index(name='price_up_chf_per_mw_h')
    price_down = down.groupby(['iso_year','iso_week']).apply(wavg).reset_index(name='price_down_chf_per_mw_h')
    prices = pd.merge(price_up, price_down, on=['iso_year','iso_week'], how='outer')
    return prices

def attach_prices_and_compute_money(weekly, prices, min_penalty_chf=250.0):
    out = weekly.merge(prices, on=['iso_year','iso_week'], how='left')
    out['up_mwh'] = out['up_mws'] / 3600.0
    out['down_mwh'] = out['down_mws'] / 3600.0
    out['penalty_chf_up_raw'] = np.where(out['penalty_up'],
                                         out['up_mwh'] * out['price_up_chf_per_mw_h'] * 10.0, 0.0)
    out['penalty_chf_down_raw'] = np.where(out['penalty_down'],
                                           out['down_mwh'] * out['price_down_chf_per_mw_h'] * 10.0, 0.0)
    out['penalty_chf_total_raw'] = out['penalty_chf_up_raw'] + out['penalty_chf_down_raw']
    out['penalty_min_applied'] = (out['penalty_any']) & (out['penalty_chf_total_raw'] > 0) & (out['penalty_chf_total_raw'] < min_penalty_chf)
    out['penalty_chf_total'] = out['penalty_chf_total_raw']
    out.loc[out['penalty_min_applied'], 'penalty_chf_total'] = min_penalty_chf
    # Compat directional totals
    out['penalty_chf_up'] = out['penalty_chf_up_raw']
    out['penalty_chf_down'] = out['penalty_chf_down_raw']
    return out

# ------------------ Main ------------------

def main():
    parser = argparse.ArgumentParser(description="Weekly SRL non-availability penalties (CHF) + plots.")
    parser.add_argument("--csv", type=str, default="/mnt/data/sim_market_only.csv", help="Path to simulation CSV")
    parser.add_argument("--offer-up", type=float, default=None, help="Committed SRL up (MW). If not set, inferred from headroom.")
    parser.add_argument("--offer-down", type=float, default=None, help="Committed SRL down (MW). If not set, inferred from headroom.")
    parser.add_argument("--threshold", type=float, default=0.1, help="Penalty threshold in % MWs deficit (default 0.1)")
    parser.add_argument("--leniency", type=float, default=None, help="Single knob 0..1: 0=strict (Swissgrid-like), 1=relaxed (realistic for 15-min data). Overrides bin-duty, gate-abs-pct, epsilon-mw, grace-minutes, and slightly raises threshold.")
    parser.add_argument("--price-csv", type=str, default="/mnt/data/2024-PRL-SRL-TRL-Ergebnis.csv", help="Swissgrid auction results CSV (for prices)")
    parser.add_argument("--gate-by", type=str, default=None, help="Direction gating: none|pct_net|market_power|cmd_power")
    parser.add_argument("--gate-abs-pct", type=float, default=0.0, help="Absolute pct threshold for gating when using pct_net (e.g., 5.0)")
    parser.add_argument("--bin-duty", type=float, default=1.0, help="Assumed fraction of each bin with deficit active (0..1), e.g., 0.3")
    parser.add_argument("--epsilon-mw", type=float, default=0.0, help="Ignore shortfalls below this MW (noise guard), e.g., 0.01")
    parser.add_argument("--grace-minutes", type=float, default=0.0, help="Per week & direction free minutes of full shortfall before penalties")
    parser.add_argument("--out-summary", type=str, default="weekly_availability_summary.csv")
    parser.add_argument("--out-plot", type=str, default="penalty_weeks_soc.png")
    parser.add_argument("--out-penalty-bar", type=str, default="penalty_weeks_bar.png")
    args = parser.parse_args()

    # Resolve paths and ensure output dirs
    csv_path = Path(args.csv); price_path = Path(args.price_csv)
    if not csv_path.is_absolute(): csv_path = (Path.cwd() / csv_path).resolve()
    if not price_path.is_absolute(): price_path = (Path.cwd() / price_path).resolve()
    out_summary = Path(args.out_summary); out_plot = Path(args.out_plot); out_bar = Path(args.out_penalty_bar)
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_plot.parent.mkdir(parents=True, exist_ok=True)
    out_bar.parent.mkdir(parents=True, exist_ok=True)

    # Load simulation
    df = pd.read_csv(csv_path, parse_dates=['timestamp'])
    df = ensure_headrooms(df)
    df, gate_mode = apply_direction_gating(df, args.gate_by, args.gate_abs_pct)
    required = ['timestamp', 'headroom_discharge_mw', 'headroom_charge_mw', 'soc_pct']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    offer_up, offer_down = args.offer_up, args.offer_down
    # --- Single-knob leniency mapping (0..1) ---
    if args.leniency is not None:
        L = max(0.0, min(1.0, float(args.leniency)))
        # Map single knob to multiple internal relaxations
        #  - bin_duty:   1.0 -> 0.3  (count only 30% of each 15-min bin at L=1)
        #  - gate_abs_pct: 0 -> 7%   (require |pct_net| >= 7% to count direction at L=1)
        #  - epsilon_mw: 0 -> 0.01MW (ignore <10kW shortfalls at L=1)
        #  - grace_minutes: 0 -> 6   (free 6 min/wk & dir at L=1)
        #  - threshold: 0.1% -> 0.15% (slightly looser)
        if not hasattr(args, 'bin_duty'): args.bin_duty = 1.0
        if not hasattr(args, 'gate_abs_pct'): args.gate_abs_pct = 0.0
        if not hasattr(args, 'epsilon_mw'): args.epsilon_mw = 0.0
        if not hasattr(args, 'grace_minutes'): args.grace_minutes = 0.0
        args.bin_duty      = 1.0 - 0.7 * L
        args.gate_abs_pct  = 0.0 + 7.0 * L
        args.epsilon_mw    = 0.0 + 0.01 * L
        args.grace_minutes = 0.0 + 6.0 * L
        args.threshold     = float(args.threshold) * (1.0 + 0.5 * L)

    if offer_up is None or offer_down is None:
        inf_up, inf_down = infer_offers(df)
        if offer_up is None: offer_up = inf_up
        if offer_down is None: offer_down = inf_down

    weekly = weekly_penalties(df, offer_up, offer_down, threshold_pct=args.threshold, bin_duty=args.bin_duty, epsilon_mw=args.epsilon_mw, grace_minutes=args.grace_minutes)

    # Prices + money
    prices = read_weekly_capacity_prices(price_path)
    weekly_money = attach_prices_and_compute_money(weekly, prices)

    # Save CSV
    cols = [
        'iso_year','iso_week',
        'seconds_total','denom_up_mws','up_mws','pct_deficit_up','penalty_up',
        'denom_down_mws','down_mws','pct_deficit_down','penalty_down','penalty_any',
        'price_up_chf_per_mw_h','price_down_chf_per_mw_h',
        'up_mwh','down_mwh',
        'penalty_chf_up_raw','penalty_chf_down_raw','penalty_chf_total_raw',
        'penalty_min_applied','penalty_chf_total'
    ]
    weekly_money = weekly_money.sort_values(['iso_year','iso_week'])
    weekly_money.to_csv(out_summary, index=False, columns=cols)

    # Plots
    plot_soc_with_penalty_weeks(df, weekly_money, out_plot)
    plot_weekly_penalties_bar(weekly_money, out_bar)

    # Console summary
    hits = weekly_money[weekly_money['penalty_any']]
    total = float(weekly_money['penalty_chf_total'].sum())
    print(f"Running: {__file__}")
    print(f"Inferred offers: up={offer_up:.3f} MW, down={offer_down:.3f} MW")
    print(f"Weeks with penalties (any direction): {len(hits)} of {len(weekly_money)} total.")
    print(f"TOTAL penalties (CHF): {total:,.2f}")
    if not hits.empty:
        view = hits[['iso_year','iso_week','pct_deficit_up','pct_deficit_down','penalty_chf_total']]
        print(view.to_string(index=False))

if __name__ == "__main__":
    main()