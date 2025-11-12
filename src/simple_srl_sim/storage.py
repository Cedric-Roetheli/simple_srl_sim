# src/simple_srl_sim/storage.py
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np

DT_H = 0.25  # 15 min

@dataclass
class Config:
    cap_mwh: float
    power_mw: float
    soc0_pct: float = 50.0
    allow_overflow: bool = False
    # fixed_bias-Parameter
    target_soc_pct: float = 50.0
    bias_share_pct: float = 0.0
    bias_deadband_pct: float = 0.0
    # NEU: Bias-Entscheidung aus Vorintervall (True = dein gewünschtes Verhalten)
    bias_decide_from_prev: bool = True

def simulate_market_only(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    d = df.copy()
    if "pct_net" not in d.columns:
        raise KeyError("pct_net fehlt; ensure_pct_cols() vorher ausführen.")
    n = len(d)
    cap = float(cfg.cap_mwh)
    Pmax = float(cfg.power_mw)
    soc = np.clip(cap * cfg.soc0_pct / 100.0,
                  -np.inf if cfg.allow_overflow else 0.0,
                  +np.inf if cfg.allow_overflow else cap)

    out = []
    for i in range(n):
        pct = float(d.iloc[i]["pct_net"])

        if cfg.allow_overflow:
            H_plus = Pmax; H_minus = Pmax
        else:
            H_plus  = min(Pmax, soc / DT_H)         # Entladen
            H_minus = min(Pmax, (cap - soc) / DT_H) # Laden

        P_req = Pmax * pct / 100.0
        P_mkt = max(-H_minus, min(P_req, H_plus))
        P_cmd = P_mkt
        E_cmd = P_cmd * DT_H

        soc = soc - E_cmd if cfg.allow_overflow else np.clip(soc - E_cmd, 0.0, cap)
        out.append({
            "timestamp": d.iloc[i]["timestamp"],
            "pct_net": pct,
            "mkt_power_mw": P_mkt,
            "cmd_power_mw": P_cmd,
            "executed_mwh": E_cmd,
            "soc_pct": 100.0 * soc / cap if cap > 0 else 0.0,
        })

    return pd.DataFrame(out)

def simulate_market_fixed_bias(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    fixed_bias mit zwei Entscheidungs-Varianten:
      - cfg.bias_decide_from_prev = True  -> Bias wird NUR auf Basis des Endzustands
        des VORIGEN Intervalls bestimmt (keine Kenntnis des aktuellen SRL-Anteils).
      - cfg.bias_decide_from_prev = False -> (alter Lookahead) Bias berücksichtigt
        die aktuelle SRL innerhalb des Intervalls (dev_end nach P_mkt).

    Vorzeichen: +P = entladen (SRL+), -P = laden (SRL-).
    """
    d = df.copy()
    if "pct_net" not in d.columns:
        raise KeyError("pct_net fehlt; ensure_pct_cols() vorher ausführen.")

    cap   = float(cfg.cap_mwh)
    Pmax  = float(cfg.power_mw)
    P_bias_max = Pmax * max(0.0, min(100.0, cfg.bias_share_pct)) / 100.0
    P_mkt_max  = Pmax - P_bias_max

    target_pct    = float(cfg.target_soc_pct)
    deadband_pct  = float(cfg.bias_deadband_pct)
    target_mwh    = cap * target_pct / 100.0
    deadband_mwh  = cap * abs(deadband_pct) / 100.0
    DT = DT_H

    # Start-SoC (Ende letztes Intervall)
    soc = np.clip(cap * cfg.soc0_pct / 100.0,
                  -np.inf if cfg.allow_overflow else 0.0,
                  +np.inf if cfg.allow_overflow else cap)

    rows = []
    for _, row in d.iterrows():
        pct = float(row["pct_net"])

        # 1) Marktanteil innerhalb Markt-Budget
        P_req_full = Pmax * pct / 100.0
        P_mkt = max(-P_mkt_max, min(P_req_full, P_mkt_max))

        # 2) Abweichung VOR Intervall (Ende t-1), nur daraus wird ggf. Bias bestimmt
        dev_prev_mwh = soc - target_mwh
        dev_prev_pct = 100.0 * dev_prev_mwh / cap if cap > 0 else 0.0

        if cfg.bias_decide_from_prev:
            # --- NEU: Bias nur aus Vorzustand (keine Kenntnis von P_mkt) ---
            if abs(dev_prev_mwh) <= deadband_mwh + 1e-12:
                P_bias_need = 0.0
            elif dev_prev_mwh > deadband_mwh:
                # zu hoch -> Entladen (positiv), Minimalleistung, um bis Bandkante zu kommen
                P_bias_need = (dev_prev_mwh - deadband_mwh) / DT
            else:  # dev_prev_mwh < -deadband_mwh
                # zu niedrig -> Laden (negativ)
                P_bias_need = (dev_prev_mwh + deadband_mwh) / DT
        else:
            # --- ALT: Bias berücksichtigt aktuelle SRL im selben Intervall ---
            dev_end_no_bias = dev_prev_mwh - P_mkt * DT
            if abs(dev_end_no_bias) <= deadband_mwh + 1e-12:
                P_bias_need = 0.0
            elif dev_end_no_bias > deadband_mwh:
                P_bias_need = (dev_end_no_bias - deadband_mwh) / DT
            else:
                P_bias_need = (dev_end_no_bias + deadband_mwh) / DT

        # 3) Bias auf Budget begrenzen
        P_bias = max(-P_bias_max, min(P_bias_need, P_bias_max))

        # 4) Gesamt-Setpoint
        P_cmd_pref = P_mkt + P_bias

        if cfg.allow_overflow:
            P_cmd = P_cmd_pref
            E_cmd = P_cmd * DT
            soc   = soc - E_cmd
        else:
            H_plus  = min(Pmax, soc / DT)           # max Entladeleistung
            H_minus = min(Pmax, (cap - soc) / DT)   # max Ladeleistung
            P_cmd   = max(-H_minus, min(P_cmd_pref, H_plus))
            E_cmd   = P_cmd * DT
            soc     = np.clip(soc - E_cmd, 0.0, cap)

        # 5) Diagnose-Spalten
        # „falsche Richtung“ gemessen am Vorzustand:
        # dev_prev>0 -> man sollte entladen (+); dev_prev<0 -> man sollte laden (−).
        wrong_way = (dev_prev_mwh >  deadband_mwh and P_bias < 0) or \
                    (dev_prev_mwh < -deadband_mwh and P_bias > 0)

        # Nur für Reporting (kein Einfluss): hypothetische Abweichungen
        dev_end_market_only = dev_prev_mwh - P_mkt * DT          # ohne Bias
        dev_end_actual      = dev_prev_mwh - P_cmd * DT          # mit Bias

        rows.append({
            "timestamp": row["timestamp"],
            "pct_net": pct,
            "market_budget_max_mw": P_mkt_max,
            "bias_budget_max_mw": P_bias_max,
            "market_power_mw": P_mkt,
            "bias_power_need_mw": P_bias_need,   # theoretisch nötig (vor Budget-Clip)
            "bias_power_mw": P_bias,             # tatsächlich genutzt (nach Budget-Clip)
            "cmd_power_mw": P_cmd,
            "executed_mwh": E_cmd,
            "soc_pct": 100.0 * soc / cap if cap > 0 else 0.0,
            # Diagnose:
            "dev_prev_mwh": dev_prev_mwh,
            "dev_prev_pct": dev_prev_pct,
            "dev_end_market_only_mwh": dev_end_market_only,
            "dev_end_actual_mwh": dev_end_actual,
            "bias_wrong_way": bool(wrong_way),
        })

    return pd.DataFrame(rows)

