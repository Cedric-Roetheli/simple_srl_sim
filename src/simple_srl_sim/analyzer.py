from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Optional

EPS = 1e-9

def load_year_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

def slice_timeframe(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if start:
        start_ts = pd.to_datetime(start)
        df = df[df["timestamp"] >= start_ts]
    if end:
        end_ts = pd.to_datetime(end)
        df = df[df["timestamp"] <= end_ts]
    return df.reset_index(drop=True)

def ensure_pct_cols(df: pd.DataFrame, compare_to: str = "offered") -> pd.DataFrame:
    """
    Stellt sicher, dass folgende Spalten verfügbar sind:
    - pct_pos, pct_neg (positiv/negativ, in %)
    - pct_net = pct_pos - pct_neg
    Eingangsquellen:
      * bereits vorhandene pct_pos_vs_<base>/pct_neg_vs_<base>  (base = offered/awarded)
      * oder Berechnung aus pos/neg_power_mw relativ zu <base>_plus/minus_mw
      * oder (Fallback) vorhandene pct_net bleibt erhalten (pos/neg nicht ableitbar)
    """
    d = df.copy()
    base = compare_to if compare_to in {"offered", "awarded"} else "offered"

    pos_named = f"pct_pos_vs_{base}"
    neg_named = f"pct_neg_vs_{base}"
    plus_base = f"{base}_plus_mw"
    minus_base = f"{base}_minus_mw"

    # 1) Falls benannte Prozentspalten existieren -> auf Standardnamen abbilden
    if pos_named in d.columns and neg_named in d.columns:
        d["pct_pos"] = pd.to_numeric(d[pos_named], errors="coerce")
        d["pct_neg"] = pd.to_numeric(d[neg_named], errors="coerce")
        d["pct_net"] = d["pct_pos"] - d["pct_neg"]
        return d

    # 2) Sonst aus Leistung & Basis-MW berechnen, falls möglich
    have_power = {"pos_power_mw", "neg_power_mw"}.issubset(d.columns)
    have_base  = {plus_base, minus_base}.issubset(d.columns)
    if have_power and have_base:
        d["pct_pos"] = 100.0 * pd.to_numeric(d["pos_power_mw"], errors="coerce") / np.maximum(pd.to_numeric(d[plus_base], errors="coerce"), EPS)
        d["pct_neg"] = 100.0 * pd.to_numeric(d["neg_power_mw"], errors="coerce") / np.maximum(pd.to_numeric(d[minus_base], errors="coerce"), EPS)
        d["pct_net"] = d["pct_pos"] - d["pct_neg"]
        return d

    # 3) Fallback: nur pct_net vorhanden (pos/neg nicht verfügbar)
    if "pct_net" in d.columns and "pct_pos" not in d.columns:
        # nichts weiter möglich
        return d

    # Wenn hier gelandet, fehlen die nötigen Spalten
    raise KeyError("Konnte Aktivierungsprozente nicht bestimmen: "
                   f"erwarte entweder pct_pos/pct_neg vs {base} oder pos/neg_power_mw + {plus_base}/{minus_base}.")
