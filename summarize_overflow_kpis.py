# summarize_overflow_kpis.py
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

def main():
    ap = argparse.ArgumentParser(description="Übersichtliche Vergleichstabelle (ohne/mit Overflow)")
    ap.add_argument("--kpi-csv", required=True, help="z.B. out\\market_only_overflow_compare\\market_only_overflow_kpis.csv")
    ap.add_argument("--outdir", default="out")
    args = ap.parse_args()

    kpi = pd.read_csv(args.kpi_csv)
    row = kpi.iloc[-1].to_dict()

    def getv(key, default=np.nan):
        try: return float(row.get(key, default))
        except Exception: return np.nan

    # Label -> (no_ov_key, ov_key, diff_key or None -> compute ov - no)
    spec = [
        ("Gesamtenergie |E| [MWh]",          "no_ov_abs_mwh",    "ov_abs_mwh",    "diff_abs_mwh"),
        ("Energie Entladen E+ [MWh]",        "no_ov_pos_mwh",    "ov_pos_mwh",    "diff_pos_mwh"),
        ("Energie Laden E- [MWh]",           "no_ov_neg_mwh",    "ov_neg_mwh",    "diff_neg_mwh"),
        ("Nettoenergie [MWh]",               "no_ov_net_mwh",    "ov_net_mwh",    "diff_net_mwh"),
        ("⟨|P|⟩ mittlere abs. Leistung [MW]","no_ov_mean_abs_mw", "ov_mean_abs_mw","diff_mean_abs_mw"),
        ("Erlös/Revenue [CHF]",              "no_ov_rev_chf",    "ov_rev_chf",    "diff_rev_chf"),
        ("Ø-Preis SRL+ [CHF/MWh] (gew.)",    "no_ov_wavg_pos_chf","ov_wavg_pos_chf", None),
        ("Ø-Preis SRL− [CHF/MWh] (gew.)",    "no_ov_wavg_neg_chf","ov_wavg_neg_chf", None),
        ("Anzahl Intervalle [#]",            "no_ov_intervals",  "ov_intervals",  "intervals"),
    ]

    rows = []
    for label, k_no, k_ov, k_diff in spec:
        v_no = getv(k_no); v_ov = getv(k_ov)
        if k_diff and (k_diff in row):
            v_diff = getv(k_diff)
        else:
            v_diff = v_ov - v_no if (np.isfinite(v_no) and np.isfinite(v_ov)) else np.nan
        rows.append((label, v_no, v_ov, v_diff))

    df = pd.DataFrame(rows, columns=["Kennzahl", "Ohne Overflow", "Mit Overflow", "Differenz (ov−no)"])

    # Runden für saubere Darstellung
    def round_val(lbl, val):
        if pd.isna(val): return val
        if "Preis" in lbl or "Revenue" in lbl or "Erlös" in lbl: return round(val, 2)
        if "Leistung" in lbl: return round(val, 3)
        if "Intervalle" in lbl: return int(round(val))
        return round(val, 3)

    for col in ["Ohne Overflow", "Mit Overflow", "Differenz (ov−no)"]:
        df[col] = [round_val(lbl, v) for lbl, v in zip(df["Kennzahl"], df[col])]

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    out_csv  = outdir / "market_only_overflow_compare_summary.csv"
    out_xlsx = outdir / "market_only_overflow_compare_summary.xlsx"
    df.to_csv(out_csv, index=False)
    df.to_excel(out_xlsx, index=False)

    print("OK →", out_csv)
    print("OK →", out_xlsx)

if __name__ == "__main__":
    main()
