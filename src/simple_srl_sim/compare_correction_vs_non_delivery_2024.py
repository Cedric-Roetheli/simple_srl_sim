
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# -------------------- helpers --------------------

def parse_ts(path, ts_col='timestamp', utc=True):
    df = pd.read_csv(path)
    # Try typical timestamp columns
    if ts_col in df.columns:
        df[ts_col] = pd.to_datetime(df[ts_col], utc=utc, errors='coerce')
    elif 'timestamp_utc' in df.columns:
        df[ts_col] = pd.to_datetime(df['timestamp_utc'], utc=True, errors='coerce')
    elif 'timestamp_local' in df.columns:
        df[ts_col] = pd.to_datetime(df['timestamp_local'], errors='coerce')
        if utc:
            # assume local is already UTC if no tz; otherwise user should provide utc col
            pass
    else:
        raise ValueError(f"No timestamp column found in {path}")
    return df

def ensure_headrooms(df):
    # Ensure headroom_discharge_mw (SRL+) and headroom_charge_mw (SRL-) exist
    if 'headroom_discharge_mw' in df.columns and 'headroom_charge_mw' in df.columns:
        return df
    if ('market_budget_max_mw' in df.columns) and ('market_power_mw' in df.columns):
        lim = pd.to_numeric(df['market_budget_max_mw'], errors='coerce').fillna(0.0)
        pwr = pd.to_numeric(df['market_power_mw'], errors='coerce').fillna(0.0)
        df = df.copy()
        df['headroom_discharge_mw'] = (lim - pwr).clip(lower=0.0)
        df['headroom_charge_mw']    = (lim + pwr).clip(lower=0.0)
        return df
    raise ValueError("Missing headroom columns and cannot derive from market_* columns.")

def apply_direction_gating(df, mode, gate_abs_pct=0.0):
    if (not mode) or str(mode).lower() in ['none','false','0']:
        return df, None
    mode = str(mode).lower()
    df = df.copy()
    if mode == 'pct_net' and 'pct_net' in df.columns:
        thr = float(gate_abs_pct)
        df['gate_up'] = (df['pct_net'] > thr).astype(float)
        df['gate_down'] = (df['pct_net'] < -thr).astype(float)
        return df, mode
    if mode == 'market_power' and 'market_power_mw' in df.columns:
        df['gate_up'] = (df['market_power_mw'] > 0).astype(float)
        df['gate_down'] = (df['market_power_mw'] < 0).astype(float)
        return df, mode
    return df, None

def iso_year_week(ts):
    iso = ts.isocalendar()
    return int(iso[0]), int(iso[1])

def read_bg_prices(bg_csv_path):
    bg = pd.read_csv(bg_csv_path)
    # Expect columns: timestamp_utc, BG_long_ct_per_kWh, BG_short_ct_per_kWh
    if 'timestamp_utc' not in bg.columns:
        raise ValueError("BG price CSV must have 'timestamp_utc' column.")
    bg['timestamp_utc'] = pd.to_datetime(bg['timestamp_utc'], utc=True, errors='coerce')
    for c in ['BG_long_ct_per_kWh','BG_short_ct_per_kWh']:
        if c not in bg.columns:
            raise ValueError(f"BG price CSV missing column {c}")
    # Convert to CHF/MWh: 1 ct/kWh = 10 CHF/MWh
    bg['BG_long_CHF_per_MWh'] = pd.to_numeric(bg['BG_long_ct_per_kWh'], errors='coerce') * 10.0
    bg['BG_short_CHF_per_MWh'] = pd.to_numeric(bg['BG_short_ct_per_kWh'], errors='coerce') * 10.0
    return bg[['timestamp_utc','BG_long_CHF_per_MWh','BG_short_CHF_per_MWh']]

# ---- penalty engine (compact) ----

def extract_kw(ausschreibung):
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


def read_weekly_capacity_prices(price_csv_path):
    dfp = pd.read_csv(price_csv_path, sep=";")
    dfp = dfp[dfp['Beschreibung'].str.contains("Secondary control", na=False)].copy()
    dfp = dfp[dfp['Land'] == 'CH']
    years, weeks = [], []
    for a in dfp['Ausschreibung']:
        y, w = extract_kw(a); years.append(y); weeks.append(w)
    dfp['iso_year'] = pd.Series(years).fillna(2024).astype(int)
    dfp['iso_week'] = weeks
    dfp['Zugesprochenes Volumen'] = pd.to_numeric(dfp['Zugesprochenes Volumen'], errors='coerce').clip(lower=0)
    dfp['Angebotspreis'] = pd.to_numeric(dfp['Angebotspreis'], errors='coerce')

    up = dfp[dfp['Beschreibung'].str.contains("SRL\\+", regex=True, na=False)].copy()
    dn = dfp[dfp['Beschreibung'].str.contains("SRL\\-", regex=True, na=False)].copy()

    # Weighted averages: sum(p*w)/sum(w)
    def wavg_df(df, colname):
        if df.empty:
            return pd.DataFrame(columns=['iso_year','iso_week', colname])
        df = df.copy()
        df['w'] = df['Zugesprochenes Volumen']
        df['pw'] = df['Angebotspreis'] * df['w']
        out = df.groupby(['iso_year','iso_week'], as_index=False).agg(sum_w=('w','sum'), sum_pw=('pw','sum'))
        out[colname] = np.where(out['sum_w']>0, out['sum_pw']/out['sum_w'], np.nan)
        return out[['iso_year','iso_week', colname]]

    price_up = wavg_df(up, 'price_up_chf_per_mw_h')
    price_dn = wavg_df(dn, 'price_down_chf_per_mw_h')
    prices = pd.merge(price_up, price_dn, on=['iso_year','iso_week'], how='outer')
    return prices
def weekly_penalties_core(df, offer_up_mw, offer_down_mw, threshold_pct, bin_duty, epsilon_mw, grace_minutes):
    # compute dt and effective duty
    ts = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
    dt_s = ts.diff().dt.total_seconds().median()
    if not np.isfinite(dt_s) or dt_s<=0: dt_s=900.0
    eff_dt = float(bin_duty) * dt_s

    # deficits per bin (MW*s)
    up_def_mw = (offer_up_mw - df['headroom_discharge_mw'] - float(epsilon_mw)).clip(lower=0.0)
    dn_def_mw = (offer_down_mw - df['headroom_charge_mw'] - float(epsilon_mw)).clip(lower=0.0)
    up_mws = up_def_mw * eff_dt * (df['gate_up'] if 'gate_up' in df.columns else 1.0)
    dn_mws = dn_def_mw * eff_dt * (df['gate_down'] if 'gate_down' in df.columns else 1.0)

    # group to iso week
    iso = ts.dt.isocalendar()
    df2 = pd.DataFrame({
        'iso_year': iso.year.astype(int).values,
        'iso_week': iso.week.astype(int).values,
        'up_mws': up_mws.values,
        'down_mws': dn_mws.values,
        'seconds': eff_dt
    })
    grp = df2.groupby(['iso_year','iso_week'], as_index=False).agg(
        seconds_total=('seconds','sum'),
        up_mws=('up_mws','sum'),
        down_mws=('down_mws','sum')
    )

    # grace minutes (per direction)
    grace_s = max(0.0, float(grace_minutes)) * 60.0
    if grace_s>0:
        grp['up_mws'] = (grp['up_mws'] - np.minimum(grp['up_mws'], offer_up_mw*grace_s)).clip(lower=0.0)
        grp['down_mws'] = (grp['down_mws'] - np.minimum(grp['down_mws'], offer_down_mw*grace_s)).clip(lower=0.0)

    denom_up = offer_up_mw * grp['seconds_total']
    denom_dn = offer_down_mw * grp['seconds_total']

    grp['pct_deficit_up'] = np.where(denom_up>0, 100.0 * grp['up_mws']/denom_up, 0.0)
    grp['pct_deficit_down'] = np.where(denom_dn>0, 100.0 * grp['down_mws']/denom_dn, 0.0)
    grp['penalty_up'] = grp['pct_deficit_up'] > threshold_pct
    grp['penalty_down'] = grp['pct_deficit_down'] > threshold_pct
    grp['penalty_any'] = grp['penalty_up'] | grp['penalty_down']
    grp['denom_up_mws'] = denom_up
    grp['denom_down_mws'] = denom_dn
    return grp

def attach_penalty_money(weekly, prices):
    out = weekly.merge(prices, on=['iso_year','iso_week'], how='left')
    out['up_mwh'] = out['up_mws'] / 3600.0
    out['down_mwh'] = out['down_mws'] / 3600.0
    out['penalty_chf_up_raw'] = np.where(out['penalty_up'], out['up_mwh'] * out['price_up_chf_per_mw_h'] * 10.0, 0.0)
    out['penalty_chf_down_raw'] = np.where(out['penalty_down'], out['down_mwh'] * out['price_down_chf_per_mw_h'] * 10.0, 0.0)
    out['penalty_chf_total_raw'] = out['penalty_chf_up_raw'] + out['penalty_chf_down_raw']
    # weekly minimum 250 CHF if any penalty in that week
    out['penalty_min_applied'] = (out['penalty_any']) & (out['penalty_chf_total_raw']>0) & (out['penalty_chf_total_raw']<250.0)
    out['penalty_chf_total'] = out['penalty_chf_total_raw']
    out.loc[out['penalty_min_applied'],'penalty_chf_total'] = 250.0
    return out

def map_leniency(leniency, threshold_base=0.1):
    L = max(0.0, min(1.0, float(leniency)))
    bin_duty      = 1.0 - 0.7 * L     # 1.0 -> 0.3
    gate_abs_pct  = 0.0 + 7.0 * L     # 0 -> 7%
    epsilon_mw    = 0.0 + 0.01 * L    # 0 -> 0.01 MW
    grace_minutes = 0.0 + 6.0 * L     # 0 -> 6 min
    threshold     = threshold_base * (1.0 + 0.5 * L)  # 0.1% -> 0.15%
    return bin_duty, gate_abs_pct, epsilon_mw, grace_minutes, threshold

# -------------------- main workflow --------------------

def run(args):
    # Load sims
    df_corr = parse_ts(args.sim_corrected, ts_col='timestamp', utc=True)
    df_unc  = parse_ts(args.sim_uncorrected, ts_col='timestamp', utc=True)

    # Ensure headrooms and gating
    df_corr = ensure_headrooms(df_corr)
    df_unc  = ensure_headrooms(df_unc)

    # Apply gating by pct_net (comes from both; we take from corrected to be safe)
    bin_duty, gate_abs_pct, epsilon_mw, grace_minutes, threshold = map_leniency(args.leniency)
    df_corr, _ = apply_direction_gating(df_corr, 'pct_net', gate_abs_pct)
    df_unc,  _ = apply_direction_gating(df_unc,  'pct_net', gate_abs_pct)

    # Align time indexes (inner join on timestamp)
    mp_corr = 'market_power_mw' if 'market_power_mw' in df_corr.columns else ('mkt_power_mw' if 'mkt_power_mw' in df_corr.columns else None)
    if mp_corr is None:
        raise ValueError('Corrected file must have market_power_mw or mkt_power_mw')
    df_corr = df_corr[['timestamp', mp_corr, 'headroom_discharge_mw','headroom_charge_mw','gate_up','gate_down'] + ([c for c in ['pct_net','soc_pct'] if c in df_corr.columns])].copy()
    df_corr = df_corr.rename(columns={mp_corr:'market_power_mw'})
    mp_unc = 'market_power_mw' if 'market_power_mw' in df_unc.columns else ('mkt_power_mw' if 'mkt_power_mw' in df_unc.columns else None)
    if mp_unc is None:
        raise ValueError('Uncorrected file must have market_power_mw or mkt_power_mw')
    df_unc  = df_unc[['timestamp', mp_unc, 'headroom_discharge_mw','headroom_charge_mw','gate_up','gate_down'] + ([c for c in ['pct_net','soc_pct'] if c in df_unc.columns])].copy()
    df_unc = df_unc.rename(columns={mp_unc:'market_power_mw'})
    merged = pd.merge(df_corr, df_unc, on='timestamp', suffixes=('_corr','_unc'), how='inner')

    # BG prices (UTC) -> merge
    bg = read_bg_prices(args.bg_prices_csv)
    merged = pd.merge_asof(merged.sort_values('timestamp'), bg.rename(columns={'timestamp_utc':'timestamp'}).sort_values('timestamp'), on='timestamp', direction='nearest', tolerance=pd.Timedelta('15min'))
    price_long = pd.to_numeric(merged['BG_long_CHF_per_MWh'], errors='coerce')
    price_short = pd.to_numeric(merged['BG_short_CHF_per_MWh'], errors='coerce')
    if merged['BG_long_CHF_per_MWh'].isna().any():
        merged[['BG_long_CHF_per_MWh','BG_short_CHF_per_MWh']] = merged[['BG_long_CHF_per_MWh','BG_short_CHF_per_MWh']].fillna(method='ffill').fillna(method='bfill')

    # Determine dt hours (assume constant 15-min if missing)
    ts = pd.to_datetime(merged['timestamp'], utc=True, errors='coerce')
    dt_s = ts.diff().dt.total_seconds().median()
    if not np.isfinite(dt_s) or dt_s<=0: dt_s=900.0
    dt_h = dt_s/3600.0
    eff_dt_h = dt_h * bin_duty

    # ------------- A) Cost of correction -------------
    # deltaP = corrected - uncorrected
    dP = pd.to_numeric(merged['market_power_mw_corr'], errors='coerce') - pd.to_numeric(merged['market_power_mw_unc'], errors='coerce')
    # energy delta in MWh (signed)
    dE_MWh = dP * eff_dt_h

    if args.correction_pricing == "tariff":
        # Convert tariffs from ct/kWh to CHF/MWh (1 ct/kWh = 10 CHF/MWh)
        import_price = float(args.tariff_import_ct) * 10.0   # CHF/MWh
        export_price = float(args.tariff_export_ct) * 10.0   # CHF/MWh
        # Extra import (dE<0) is a cost; extra export (dE>0) is a revenue (reduces cost)
        corr_cashflow = ((-dE_MWh).clip(lower=0.0) * import_price) - (dE_MWh.clip(lower=0.0) * export_price)
    else:
        # value with BG prices (conservative):
        # inject more (dE>0) => use BG_long; absorb more (dE<0) => use BG_short
        price_long = pd.to_numeric(merged['BG_long_CHF_per_MWh'], errors='coerce')
        price_short= pd.to_numeric(merged['BG_short_CHF_per_MWh'], errors='coerce')
        corr_cashflow = (dE_MWh.clip(lower=0.0) * price_long) + ((-dE_MWh).clip(lower=0.0) * price_short)
    # interpret cost: positive = cost, negative = benefit
    correction_cost_chf = float(corr_cashflow.sum())

    # ------------- B) Non-delivery cost + penalties -------------
    offer_up, offer_down = float(args.offer_up), float(args.offer_down)

    # Shortfalls (MW) in gated directions, based on uncorrected headrooms
    up_short_mw = (offer_up - merged['headroom_discharge_mw_unc']).clip(lower=0.0) * merged['gate_up_unc']
    dn_short_mw = (offer_down - merged['headroom_charge_mw_unc']).clip(lower=0.0) * merged['gate_down_unc']

    # Apply epsilon_mw (ignore tiny)
    up_short_mw = (up_short_mw - epsilon_mw).clip(lower=0.0)
    dn_short_mw = (dn_short_mw - epsilon_mw).clip(lower=0.0)

    # Energy shortfall per bin (MWh) with duty factor
    up_short_mwh = up_short_mw * eff_dt_h
    dn_short_mwh = dn_short_mw * eff_dt_h

    # Imbalance cost mapping: missing UP delivery => SHORT; missing DOWN delivery => LONG
    if args.non_delivery_cost_mode == 'cashflow':
        non_delivery_cost_chf = float((up_short_mwh * price_short + dn_short_mwh * price_long).sum())
    else:
        # cost mode (non-negative): short (buy) cost = max(up*BG_short,0); long (sell) cost = max(-dn*BG_long,0)
        comp_up = up_short_mwh * price_short
        comp_dn = dn_short_mwh * price_long
        non_delivery_cost_chf = float(comp_up.clip(lower=0.0).sum() + (-comp_dn).clip(lower=0.0).sum())
    non_delivery_energy_mwh = float((up_short_mwh + dn_short_mwh).sum())

    # Weekly penalties on uncorrected series
    pen_df = merged[['timestamp','headroom_discharge_mw_unc','headroom_charge_mw_unc','gate_up_unc','gate_down_unc']].rename(columns={
        'headroom_discharge_mw_unc':'headroom_discharge_mw',
        'headroom_charge_mw_unc':'headroom_charge_mw',
        'gate_up_unc':'gate_up',
        'gate_down_unc':'gate_down'
    }).copy()

    weekly = weekly_penalties_core(pen_df, offer_up, offer_down, threshold, bin_duty, epsilon_mw, grace_minutes)
    prices = read_weekly_capacity_prices(args.capacity_prices_csv)
    weekly_money = attach_penalty_money(weekly, prices).sort_values(['iso_year','iso_week'])
    penalty_total_chf = float(weekly_money['penalty_chf_total'].sum())

    # Apply no-penalties option
    if args.no_penalties:
        penalty_total_chf = 0.0
        # Also zero the weekly penalty columns for clarity in the CSV
        for col in ['penalty_chf_total','penalty_chf_total_raw','penalty_chf_up_raw','penalty_chf_down_raw','penalty_min_applied']:
            if col in weekly_money.columns:
                if col == 'penalty_min_applied':
                    weekly_money[col] = False
                else:
                    weekly_money[col] = 0.0


    # Outputs
    summary = pd.DataFrame([{
        'offer_up_mw': offer_up,
        'offer_down_mw': offer_down,
        'leniency': float(args.leniency),
        'dt_minutes_effective': eff_dt_h*60.0,
        'A_correction_energy_MWh': float(dE_MWh.abs().sum()),
        'A_correction_cost_CHF' : correction_cost_chf,
        'B_non_delivery_energy_MWh': non_delivery_energy_mwh,
        'B_non_delivery_cost_CHF'  : non_delivery_cost_chf,
        'B_penalties_CHF'          : penalty_total_chf,
        'B_total_CHF'              : non_delivery_cost_chf + penalty_total_chf,
        'Diff_B_minus_A_CHF'       : (non_delivery_cost_chf + penalty_total_chf) - correction_cost_chf
    }])

    return summary, weekly_money

def plot_compare(summary_df, out_png):
    # Simple bars: A vs B totals
    a = float(summary_df['A_correction_cost_CHF'].iloc[0])
    b = float(summary_df['B_total_CHF'].iloc[0])
    labels = ['Korrektur (A)', 'ohne Korrektur(B)']
    values = [a, b]
    fig, ax = plt.subplots(figsize=(6,4))
    ax.bar(labels, values)
    ax.set_ylabel('CHF')
    ax.set_title('Jahreskosten 2024: mit Korrektur vs. ohne Korrektur')
    for i,v in enumerate(values):
        ax.text(i, v, f"{v:,.0f}", ha='center', va='bottom', rotation=0)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)

def main():
    parser = argparse.ArgumentParser(description="Compare correction costs vs non-delivery + penalties for 2024.")
    parser.add_argument("--sim-corrected", type=str, default="/mnt/data/sim_fixed_bias.csv")
    parser.add_argument("--sim-uncorrected", type=str, default="/mnt/data/sim_market_only.csv")
    parser.add_argument("--bg-prices-csv", type=str, default="/mnt/data/swissgrid_balance_energy_prices_2024_timeseries_UTC.csv")
    parser.add_argument("--capacity-prices-csv", type=str, default="/mnt/data/2024-PRL-SRL-TRL-Ergebnis.csv")
    parser.add_argument("--offer-up", type=float, default=0.2)
    parser.add_argument("--offer-down", type=float, default=0.2)
    parser.add_argument("--leniency", type=float, default=0.6)
    parser.add_argument("--correction-pricing", type=str, default="tariff", choices=["tariff","bg"], help="How to price correction energy: fixed tariff or BG prices")
    parser.add_argument("--tariff-import-ct", type=float, default=22.0, help="Import tariff in Rp/ct per kWh (e.g., 22 Rp/kWh)")
    parser.add_argument("--tariff-export-ct", type=float, default=0.06, help="Export feed-in tariff in Rp/ct per kWh (e.g., 0.06 Rp/kWh)")
    parser.add_argument("--out-summary", type=str, default="/mnt/data/correction_vs_non_delivery_2024_summary.csv")
    parser.add_argument("--out-weekly", type=str, default="/mnt/data/non_delivery_weekly.csv")
    parser.add_argument("--out-bar", type=str, default="/mnt/data/comparison_bar.png")
    parser.add_argument("--no-penalties", action="store_true", help="If set, exclude weekly penalties from B (report-only non-delivery costs).")
    parser.add_argument("--non-delivery-cost-mode", type=str, default="cashflow", choices=["cashflow","cost"], help="cashflow: signed settlement (can be <0); cost: non-negative (clamped by direction).")
    args = parser.parse_args()

    summary, weekly = run(args)
    summary.to_csv(args.out_summary, index=False)
    weekly.to_csv(args.out_weekly, index=False)
    plot_compare(summary, args.out_bar)

    print(summary.to_string(index=False))
    print(f"Saved: {args.out_summary}")
    print(f"Saved: {args.out_weekly}")
    print(f"Saved: {args.out_bar}")

if __name__ == "__main__":
    main()
