# src/simple_srl_sim/build_market_csv.py
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

DT_H = 0.25  # 15-min

POS_PRICE_NAME = "Durchschnittliche positive Sekundär-Regelenergie Preise\nAverage positive secondary control energy prices"
NEG_PRICE_NAME = "Durchschnittliche negative Sekundär-Regelenergie Preise\nAverage negative secondary control energy prices"

def load_excel_energy_price(xlsx: Path) -> pd.DataFrame:
    dt = pd.read_excel(xlsx, sheet_name="Datetime")
    ts = pd.to_datetime(dt.iloc[1:, 0]).rename("timestamp").reset_index(drop=True)

    zr = pd.read_excel(xlsx, sheet_name="Zeitreihen0h15")
    # Energie G/H (kWh), 1. Datenzeile = "kWh"
    pos_kwh = pd.to_numeric(zr.iloc[1:, 6], errors="coerce").reset_index(drop=True)
    neg_kwh = pd.to_numeric(zr.iloc[1:, 7], errors="coerce").reset_index(drop=True)

    # Preise V/W oder per exakten Namen
    if POS_PRICE_NAME in zr.columns and NEG_PRICE_NAME in zr.columns:
        pos_price = pd.to_numeric(zr[POS_PRICE_NAME].iloc[1:], errors="coerce").reset_index(drop=True)
        neg_price = pd.to_numeric(zr[NEG_PRICE_NAME].iloc[1:], errors="coerce").reset_index(drop=True)
    else:
        pos_price = pd.to_numeric(zr.iloc[1:, 21], errors="coerce").reset_index(drop=True)
        neg_price = pd.to_numeric(zr.iloc[1:, 22], errors="coerce").reset_index(drop=True)

    n = min(len(ts), len(pos_kwh), len(neg_kwh), len(pos_price), len(neg_price))
    ts = ts.iloc[:n]

    # SRL- in Excel ist oft negativ: Betrag bilden
    pos_energy_mwh = (pos_kwh.iloc[:n].clip(lower=0) / 1000.0)
    neg_energy_mwh = ((-neg_kwh.iloc[:n].clip(upper=0)) / 1000.0)

    df = pd.DataFrame({
        "timestamp": ts.to_numpy(),
        "pos_energy_mwh": pos_energy_mwh.to_numpy(),
        "neg_energy_mwh": neg_energy_mwh.to_numpy(),
        "price_pos_chf_per_mwh": pos_price.iloc[:n].to_numpy(),
        "price_neg_chf_per_mwh": neg_price.iloc[:n].to_numpy(),
    })
    df["pos_power_mw"] = df["pos_energy_mwh"] / DT_H
    df["neg_power_mw"] = df["neg_energy_mwh"] / DT_H
    return df

def load_weekly_awarded_from_ergebnis(csv_path: Path) -> pd.DataFrame:
    d = pd.read_csv(csv_path, sep=";")
    d = d[d["Ausschreibung"].str.startswith("SRL_", na=False)].copy()
    d["dir"] = np.where(d["Beschreibung"].str.contains(r"SRL\+", regex=True, na=False), "plus",
                 np.where(d["Beschreibung"].str.contains(r"SRL-", regex=True, na=False), "minus", None))
    d = d[d["dir"].notna()]
    m = d["Ausschreibung"].str.extract(r"SRL_(\d{2})_KW(\d{2})")
    d["iso_year"] = 2000 + m[0].astype(int)
    d["iso_week"] = m[1].astype(int)
    grp = d.groupby(["iso_year","iso_week","dir"], as_index=False)["Zugesprochenes Volumen"].sum()
    piv = grp.pivot(index=["iso_year","iso_week"], columns="dir", values="Zugesprochenes Volumen").fillna(0.0)
    piv = piv.rename(columns={"plus": "awarded_plus_mw", "minus": "awarded_minus_mw"}).reset_index()
    return piv

def add_week_mapping(df_15min: pd.DataFrame) -> pd.DataFrame:
    iso = df_15min["timestamp"].dt.isocalendar()
    d = df_15min.copy()
    d["iso_year"] = iso.year.astype(int)
    d["iso_week"] = iso.week.astype(int)
    return d

def compute_pct_vs_awarded(df: pd.DataFrame) -> pd.DataFrame:
    eps = 1e-9
    d = df.copy()
    d["pct_pos_vs_awarded"] = np.where(d["awarded_plus_mw"]  > eps, 100.0 * d["pos_power_mw"] / d["awarded_plus_mw"].clip(lower=eps), 0.0)
    d["pct_neg_vs_awarded"] = np.where(d["awarded_minus_mw"] > eps, 100.0 * d["neg_power_mw"] / d["awarded_minus_mw"].clip(lower=eps), 0.0)
    d["pct_net"] = d["pct_pos_vs_awarded"] - d["pct_neg_vs_awarded"]
    return d

def build_market_csv_from_files(xlsx: str | Path, ergebnis: str | Path, out_csv: str | Path) -> pd.DataFrame:
    xlsx = Path(xlsx); ergebnis = Path(ergebnis); out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    ex = load_excel_energy_price(xlsx)
    wk = load_weekly_awarded_from_ergebnis(ergebnis)
    ex = add_week_mapping(ex)
    df = ex.merge(wk, on=["iso_year","iso_week"], how="left")
    for c in ["awarded_plus_mw","awarded_minus_mw"]:
        if c not in df.columns: df[c] = 0.0
        df[c] = df[c].fillna(0.0)
    df = compute_pct_vs_awarded(df)
    # Spaltenreihenfolge
    cols = ["timestamp","pos_power_mw","neg_power_mw",
            "awarded_plus_mw","awarded_minus_mw",
            "pct_pos_vs_awarded","pct_neg_vs_awarded","pct_net",
            "price_pos_chf_per_mwh","price_neg_chf_per_mwh",
            "pos_energy_mwh","neg_energy_mwh","iso_year","iso_week"]
    cols = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
    df = df[cols]
    df.to_csv(out_csv, index=False)
    return df

def main():
    ap = argparse.ArgumentParser(description="Baue 15-min Markt-CSV (Leistung, Prozent vs Awarded, Preise) aus Excel + Ergebnis-CSV.")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--ergebnis", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    df = build_market_csv_from_files(args.xlsx, args.ergebnis, args.out)
    print(f"OK -> {args.out} | n={len(df)} | {df['timestamp'].min()} .. {df['timestamp'].max()}")

if __name__ == "__main__":
    main()
