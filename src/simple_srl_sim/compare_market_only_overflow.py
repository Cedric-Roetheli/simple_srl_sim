# src/simple_srl_sim/compare_market_only_overflow.py
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from .analyzer import load_year_csv, ensure_pct_cols, slice_timeframe
from .storage import Config, simulate_market_only

DT = 0.25  # 15 Minuten in Stunden

def _read_prices(price_csv: Path) -> pd.DataFrame:
    dfp = pd.read_csv(price_csv)
    # Spaltennamen robust finden
    cols = {c.lower(): c for c in dfp.columns}
    def pick(*names):
        for n in names:
            if n in cols: return cols[n]
        raise KeyError(f"Spalte nicht gefunden; erwarte eine von {names} in {list(dfp.columns)}")

    ts_col = pick("timestamp", "time", "datetime")
    ppos   = pick("price_pos_chf_per_mwh", "pos_price", "price_pos", "price_pos_mwh", "srl_pos_price_chf_per_mwh")
    pneg   = pick("price_neg_chf_per_mwh", "neg_price", "price_neg", "price_neg_mwh", "srl_neg_price_chf_per_mwh")

    out = dfp[[ts_col, ppos, pneg]].copy()
    out.columns = ["timestamp", "price_pos", "price_neg"]
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    return out

def _kpis_from_power(sim_df: pd.DataFrame, prefix: str, prices_df: pd.DataFrame) -> dict:
    DT = 0.25  # 15 min
    d = sim_df[["timestamp","cmd_power_mw"]].merge(
        prices_df[["timestamp","price_pos","price_neg"]], on="timestamp", how="inner"
    )
    p = d["cmd_power_mw"].astype(float)
    E = p * DT  # signierte Energie [MWh]
    price = np.where(p >= 0, d["price_pos"].to_numpy(), d["price_neg"].to_numpy())
    rev = float((E * price).sum())

    e_pos = float((p.clip(lower=0)  * DT).sum())
    e_neg = float((-p.clip(upper=0) * DT).sum())
    wavg_pos = (( (p.clip(lower=0)*DT) * d["price_pos"]).sum()/e_pos) if e_pos>0 else np.nan
    wavg_neg = (( (-p.clip(upper=0)*DT) * d["price_neg"]).sum()/e_neg) if e_neg>0 else np.nan

    return {
        f"{prefix}_pos_mwh": e_pos,
        f"{prefix}_neg_mwh": e_neg,
        f"{prefix}_abs_mwh": e_pos + e_neg,
        f"{prefix}_net_mwh": e_pos - e_neg,
        f"{prefix}_mean_abs_mw": float(p.abs().mean()),
        f"{prefix}_rev_chf": rev,
        f"{prefix}_wavg_pos_chf": float(wavg_pos),
        f"{prefix}_wavg_neg_chf": float(wavg_neg),
        f"{prefix}_intervals": int(len(d)),
    }


def main():
    ap = argparse.ArgumentParser(description="Vergleich: market_only mit vs. ohne Overflow (Energie & Erlöse)")
    ap.add_argument("--input", required=True, help="CSV mit Aktivierungsdaten (z.B. srl_activation_vs_awarded_2024.csv)")
    ap.add_argument("--compare-to", choices=["offered","awarded"], default="awarded")
    ap.add_argument("--cap-mwh", type=float, required=True)
    ap.add_argument("--power-mw", type=float, required=True)
    ap.add_argument("--soc0-pct", type=float, default=50.0)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--price-csv", required=True, help="15-min Preiszeitreihe mit timestamp, price_pos, price_neg")
    ap.add_argument("--outdir", default="out/market_only_overflow_compare")
    args = ap.parse_args()

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # 1) Daten + Prozente
    df = load_year_csv(args.input)
    df = slice_timeframe(df, args.start, args.end)
    df = ensure_pct_cols(df, compare_to=args.compare_to)

    # 2) zwei Simulationen: market_only ohne/mit Overflow
    base_cfg = dict(cap_mwh=args.cap_mwh, power_mw=args.power_mw, soc0_pct=args.soc0_pct)
    sim_no = simulate_market_only(df, Config(**base_cfg, allow_overflow=False))
    sim_ov = simulate_market_only(df, Config(**base_cfg, allow_overflow=True))

    # 3) Preise einlesen & join keys
    prices = _read_prices(Path(args.price_csv))

    # 4) KPIs berechnen
    k_no = _kpis_from_power(sim_no.rename(columns={"cmd_power_mw":"cmd_power_mw"}), "no_ov", prices)
    k_ov = _kpis_from_power(sim_ov.rename(columns={"cmd_power_mw":"cmd_power_mw"}), "ov",    prices)

    # 5) Differenzen (Overflow - NoOverflow)
    k_diff = {
        "diff_pos_mwh":     k_ov["ov_pos_mwh"]  - k_no["no_ov_pos_mwh"],
        "diff_neg_mwh":     k_ov["ov_neg_mwh"]  - k_no["no_ov_neg_mwh"],
        "diff_abs_mwh":     k_ov["ov_abs_mwh"]  - k_no["no_ov_abs_mwh"],
        "diff_net_mwh":     k_ov["ov_net_mwh"]  - k_no["no_ov_net_mwh"],
        "diff_mean_abs_mw": k_ov["ov_mean_abs_mw"] - k_no["no_ov_mean_abs_mw"],
        "diff_rev_chf":     k_ov["ov_rev_chf"]  - k_no["no_ov_rev_chf"],
        "intervals":        k_no["no_ov_intervals"],  # nach merge identisch erwartet
    }

    # 6) KPI-Tabelle speichern
    kpi_df = pd.DataFrame([{
        **k_no, **k_ov, **k_diff,
        "cap_mwh": args.cap_mwh,
        "power_mw": args.power_mw,
        "soc0_pct": args.soc0_pct,
        "compare_to": args.compare_to,
        "start": args.start, "end": args.end,
        "price_csv": str(Path(args.price_csv)),
        "input_csv": str(Path(args.input)),
    }])
    kpi_path = outdir / "market_only_overflow_kpis.csv"
    kpi_df.to_csv(kpi_path, index=False)

    # 7) Zeitreihe (für Transparenz/Validierung)
    ts = (sim_no[["timestamp","cmd_power_mw"]].rename(columns={"cmd_power_mw":"p_no_ov"})
          .merge(sim_ov[["timestamp","cmd_power_mw"]].rename(columns={"cmd_power_mw":"p_ov"}), on="timestamp", how="inner")
          .merge(prices, on="timestamp", how="inner"))
    ts["e_no_pos_mwh"] = (ts["p_no_ov"].clip(lower=0)  * DT)
    ts["e_no_neg_mwh"] = (-ts["p_no_ov"].clip(upper=0) * DT)
    ts["e_ov_pos_mwh"] = (ts["p_ov"].clip(lower=0)     * DT)
    ts["e_ov_neg_mwh"] = (-ts["p_ov"].clip(upper=0)    * DT)
    ts["rev_no_chf"]   = ts["e_no_pos_mwh"] * ts["price_pos"] + ts["e_no_neg_mwh"] * ts["price_neg"]
    ts["rev_ov_chf"]   = ts["e_ov_pos_mwh"] * ts["price_pos"] + ts["e_ov_neg_mwh"] * ts["price_neg"]
    ts["rev_diff_chf"] = ts["rev_ov_chf"] - ts["rev_no_chf"]

    ts_path = outdir / "market_only_overflow_compare_timeseries.csv"
    ts.to_csv(ts_path, index=False)

    # 8) Kurz-Output
    print("=== MARKET ONLY: KPIs ===")
    print(f"NO-OV  | |E|={k_no['no_ov_abs_mwh']:.3f} MWh,  Rev={k_no['no_ov_rev_chf']:.2f} CHF,  ⟨|P|⟩={k_no['no_ov_mean_abs_mw']:.3f} MW")
    print(f"OV     | |E|={k_ov['ov_abs_mwh']:.3f} MWh,  Rev={k_ov['ov_rev_chf']:.2f} CHF,  ⟨|P|⟩={k_ov['ov_mean_abs_mw']:.3f} MW")
    print(f"DIFF   | |E|={k_diff['diff_abs_mwh']:.3f} MWh, Rev={k_diff['diff_rev_chf']:.2f} CHF, ⟨|P|⟩={k_diff['diff_mean_abs_mw']:.3f} MW")
    print(f"OUT KPIs : {kpi_path}")
    print(f"OUT TS   : {ts_path}")


if __name__ == "__main__":
    main()
