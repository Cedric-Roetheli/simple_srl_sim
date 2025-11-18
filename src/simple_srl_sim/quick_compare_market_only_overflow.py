# quick_compare_market_only_overflow.py
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

DT = 0.25  # 15 min in Stunden

def pick_col(cols, *cands):
    lower = {c.lower(): c for c in cols}
    for c in cands:
        if c in lower:
            return lower[c]
    return None

def load_input(csv_path: Path):
    df = pd.read_csv(csv_path)
    ts_col = pick_col(df.columns, "timestamp", "time", "datetime")
    if ts_col is None:
        raise KeyError("Keine Timestamp-Spalte gefunden (erwarte timestamp/time/datetime)")
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.rename(columns={ts_col: "timestamp"})

    ppos = pick_col(df.columns, "pct_pos_vs_awarded", "pct_pos", "pct_pos_vs_offered")
    pneg = pick_col(df.columns, "pct_neg_vs_awarded", "pct_neg", "pct_neg_vs_offered")
    if ppos is None or pneg is None:
        raise KeyError("Keine Aktivierungs-Percent-Spalten (pct_pos_*, pct_neg_*) gefunden")

    df["pct_net"] = df[ppos].astype(float) - df[pneg].astype(float)

    price_pos = pick_col(df.columns,
                         "price_pos_chf_per_mwh","srl_pos_price_chf_per_mwh","price_pos","pos_price")
    price_neg = pick_col(df.columns,
                         "price_neg_chf_per_mwh","srl_neg_price_chf_per_mwh","price_neg","neg_price")
    if price_pos is None or price_neg is None:
        raise KeyError("Keine Preis-Spalten gefunden (pos/neg).")
    df = df.rename(columns={price_pos: "price_pos", price_neg: "price_neg"})
    return df[["timestamp","pct_net","price_pos","price_neg"]].sort_values("timestamp").reset_index(drop=True)

def simulate_market_only(df, cap_mwh, power_mw, soc0_pct, allow_overflow):
    soc = np.clip(cap_mwh * soc0_pct / 100.0,
                  -np.inf if allow_overflow else 0.0,
                  +np.inf if allow_overflow else cap_mwh)
    Pmax = float(power_mw)
    ts = []
    for _, r in df.iterrows():
        pct = float(r["pct_net"])
        P_req = Pmax * pct / 100.0
        if allow_overflow:
            P_cmd = max(-Pmax, min(P_req, Pmax))
            E_cmd = P_cmd * DT
            soc   = soc - E_cmd
        else:
            H_plus  = min(Pmax, soc / DT)               # max entladen
            H_minus = min(Pmax, (cap_mwh - soc) / DT)   # max laden
            P_cmd   = max(-H_minus, min(P_req, H_plus))
            E_cmd   = P_cmd * DT
            soc     = np.clip(soc - E_cmd, 0.0, cap_mwh)
        ts.append((r["timestamp"], P_cmd))
    return pd.DataFrame(ts, columns=["timestamp","cmd_power_mw"])

def kpis_from_power(sim_df, prices_df, prefix: str):
    d = sim_df.merge(prices_df[["timestamp","price_pos","price_neg"]], on="timestamp", how="inner")
    p = d["cmd_power_mw"].astype(float)
    e_pos = (p.clip(lower=0)  * DT)
    e_neg = (-p.clip(upper=0) * DT)
    rev   = (e_pos * d["price_pos"]) + (e_neg * d["price_neg"])
    wavg_pos = (e_pos * d["price_pos"]).sum() / e_pos.sum() if e_pos.sum() > 0 else np.nan
    wavg_neg = (e_neg * d["price_neg"]).sum() / e_neg.sum() if e_neg.sum() > 0 else np.nan
    return {
        f"{prefix}_pos_mwh": float(e_pos.sum()),
        f"{prefix}_neg_mwh": float(e_neg.sum()),
        f"{prefix}_abs_mwh": float((e_pos + e_neg).sum()),
        f"{prefix}_net_mwh": float(e_pos.sum() - e_neg.sum()),
        f"{prefix}_mean_abs_mw": float(p.abs().mean()),
        f"{prefix}_rev_chf": float(rev.sum()),
        f"{prefix}_wavg_pos_chf": float(wavg_pos),
        f"{prefix}_wavg_neg_chf": float(wavg_neg),
        f"{prefix}_intervals": int(len(d)),
    }

def main():
    ap = argparse.ArgumentParser(description="Vergleich market_only: ohne vs mit Overflow (Energie & Revenue)")
    ap.add_argument("--input", required=True)
    ap.add_argument("--cap-mwh", type=float, required=True)
    ap.add_argument("--power-mw", type=float, required=True)
    ap.add_argument("--soc0-pct", type=float, default=50.0)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--outdir", default="out/market_only_overflow_compare_quick")
    args = ap.parse_args()

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    df = load_input(Path(args.input))
    if args.start: df = df[df["timestamp"] >= pd.to_datetime(args.start)]
    if args.end:   df = df[df["timestamp"] <= pd.to_datetime(args.end)]

    sim_no = simulate_market_only(df, args.cap_mwh, args.power_mw, args.soc0_pct, allow_overflow=False)
    sim_ov = simulate_market_only(df, args.cap_mwh, args.power_mw, args.soc0_pct, allow_overflow=True)

    prices = df[["timestamp","price_pos","price_neg"]].copy()
    k_no = kpis_from_power(sim_no, prices, "no_ov")
    k_ov = kpis_from_power(sim_ov, prices, "ov")
    k_diff = {
        "diff_pos_mwh": k_ov["ov_pos_mwh"] - k_no["no_ov_pos_mwh"],
        "diff_neg_mwh": k_ov["ov_neg_mwh"] - k_no["no_ov_neg_mwh"],
        "diff_abs_mwh": k_ov["ov_abs_mwh"] - k_no["no_ov_abs_mwh"],
        "diff_net_mwh": k_ov["ov_net_mwh"] - k_no["no_ov_net_mwh"],
        "diff_mean_abs_mw": k_ov["ov_mean_abs_mw"] - k_no["no_ov_mean_abs_mw"],
        "diff_rev_chf": k_ov["ov_rev_chf"] - k_no["no_ov_rev_chf"],
    }

    kpi = pd.DataFrame([{**k_no, **k_ov, **k_diff,
                         "cap_mwh": args.cap_mwh, "power_mw": args.power_mw, "soc0_pct": args.soc0_pct,
                         "start": args.start, "end": args.end, "input_csv": str(Path(args.input))}])
    kpi_path = outdir / "market_only_overflow_kpis.csv"
    kpi.to_csv(kpi_path, index=False)

    ts = (sim_no.rename(columns={"cmd_power_mw":"p_no_ov"})
          .merge(sim_ov.rename(columns={"cmd_power_mw":"p_ov"}), on="timestamp", how="inner")
          .merge(prices, on="timestamp", how="inner"))
    ts["e_no_pos_mwh"] = ts["p_no_ov"].clip(lower=0)  * DT
    ts["e_no_neg_mwh"] = (-ts["p_no_ov"]).clip(upper=0) * DT
    ts["e_ov_pos_mwh"] = ts["p_ov"].clip(lower=0)     * DT
    ts["e_ov_neg_mwh"] = (-ts["p_ov"]).clip(upper=0)  * DT
    ts["rev_no_chf"]   = ts["e_no_pos_mwh"] * ts["price_pos"] + ts["e_no_neg_mwh"] * ts["price_neg"]
    ts["rev_ov_chf"]   = ts["e_ov_pos_mwh"] * ts["price_pos"] + ts["e_ov_neg_mwh"] * ts["price_neg"]
    ts["rev_diff_chf"] = ts["rev_ov_chf"] - ts["rev_no_chf"]

    ts_path = outdir / "market_only_overflow_compare_timeseries.csv"
    ts.to_csv(ts_path, index=False)

    print("OUT KPIs :", kpi_path.resolve())
    print("OUT TS   :", ts_path.resolve())

if __name__ == "__main__":
    main()
