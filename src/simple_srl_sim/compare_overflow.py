# src/simple_srl_sim/compare_overflow.py
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from .analyzer import load_year_csv, ensure_pct_cols, slice_timeframe
from .storage import Config, simulate_market_only
from .plotting import plot_soc_with_bounds  # nutzt rote Grenzlinien
import matplotlib.pyplot as plt

DT_H = 0.25

def _metrics(df: pd.DataFrame, pcol: str, thr: float = 0.01) -> dict:
    p = df[pcol].astype(float)
    e_out = float((p.clip(lower=0) * DT_H).sum())
    e_in  = float((-p.clip(upper=0) * DT_H).sum())
    d = {
        "pos_mwh": e_out,
        "neg_mwh": e_in,
        "net_mwh": e_out - e_in,
        "mean_abs_mw": float(p.abs().mean()),
        "p_max_mw": float(p.max()),
        "p_min_mw": float(p.min()),
        "activation_share": float((p.abs() > thr).mean()),
    }
    return d

def _plot_soc_compare(df_no: pd.DataFrame, df_ov: pd.DataFrame, out_png: Path, title: str) -> None:
    plt.figure(figsize=(12, 3.6))
    plt.plot(df_no["timestamp"], df_no["soc_pct"], lw=0.9, label="SoC ohne Overflow")
    plt.plot(df_ov["timestamp"], df_ov["soc_pct"], lw=0.9, label="SoC mit Overflow")
    # Grenzen explizit rot (gewünscht)
    plt.axhline(0,  color="red", lw=1.0)
    plt.axhline(100, color="red", lw=1.0)
    plt.ylabel("SoC [%]")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()

def _plot_power_compare(df_no: pd.DataFrame, df_ov: pd.DataFrame, out_png: Path, title: str) -> None:
    import matplotlib.pyplot as plt
    plt.figure(figsize=(12, 3.6))

    # 1) Overflow zuerst (Hintergrund): dünner, transparenter, ggf. gestrichelt
    plt.plot(
        df_ov["timestamp"], df_ov["cmd_power_mw"],
        lw=0.8, alpha=0.6, ls="--", drawstyle="steps-pre",
        label="P mit Overflow", zorder=1
    )

    # 2) Ohne Overflow obenauf: dicker, volle Deckung
    plt.plot(
        df_no["timestamp"], df_no["cmd_power_mw"],
        lw=1.8, drawstyle="steps-pre",
        label="P ohne Overflow", zorder=3
    )

    plt.axhline(0, ls="--", lw=0.8, zorder=0)
    plt.ylabel("MW"); plt.xlabel("Zeit"); plt.title(title)

    # Legende: „ohne Overflow“ zuerst anzeigen
    handles, labels = plt.gca().get_legend_handles_labels()
    plt.legend(handles[::-1], labels[::-1])

    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()


def _plot_power_diff_signed(df_no: pd.DataFrame, df_ov: pd.DataFrame, out_png: Path, title: str) -> None:
    import matplotlib.pyplot as plt
    d = pd.DataFrame({
        "timestamp": df_no["timestamp"],
        "diff_mw": df_ov["cmd_power_mw"].to_numpy() - df_no["cmd_power_mw"].to_numpy()
    })
    plt.figure(figsize=(12, 3.2))
    plt.plot(d["timestamp"], d["diff_mw"], lw=0.8, label="ΔP = P(Overflow) − P(ohne)")
    plt.axhline(0, ls="--", lw=0.8)
    plt.ylabel("MW"); plt.xlabel("Zeit"); plt.title(title)
    plt.legend(); plt.tight_layout(); plt.savefig(out_png, dpi=150); plt.close()

def _plot_power_diff_in_dir(cmp_df: pd.DataFrame, out_png: Path, title: str) -> None:
    import matplotlib.pyplot as plt
    plt.figure(figsize=(12, 3.2))
    plt.plot(cmp_df["timestamp"], cmp_df["delta_in_dir_mw"], lw=0.8,
             label="ΔP in Marktrichtung = sign(Preq)·ΔP")
    plt.axhline(0, ls="--", lw=0.8)
    plt.ylabel("MW"); plt.xlabel("Zeit"); plt.title(title)
    plt.legend(); plt.tight_layout(); plt.savefig(out_png, dpi=150); plt.close()


def main():
    ap = argparse.ArgumentParser(description="Vergleich: Simulation ohne Overflow vs. mit Overflow")
    ap.add_argument("--input", required=True, help="Markt-CSV mit pct_net (z. B. aus build_market_csv.py)")
    ap.add_argument("--compare-to", choices=["offered","awarded"], default="awarded")
    ap.add_argument("--cap-mwh", type=float, required=True)
    ap.add_argument("--power-mw", type=float, required=True)
    ap.add_argument("--soc0-pct", type=float, default=50.0)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--activation-threshold-mw", type=float, default=0.01)
    args = ap.parse_args()

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # Eingangsdaten
    df = load_year_csv(args.input)
    df = slice_timeframe(df, args.start, args.end)
    df = ensure_pct_cols(df, compare_to=args.compare_to)

    # Marktanforderung (für Reporting)
    df["req_power_mw"] = args.power_mw * df["pct_net"] / 100.0

    # Sim 1: ohne Overflow
    cfg_no = Config(cap_mwh=args.cap_mwh, power_mw=args.power_mw, soc0_pct=args.soc0_pct, allow_overflow=False)
    sim_no = simulate_market_only(df, cfg_no).rename(columns={
        "cmd_power_mw": "cmd_power_no_ov_mw",
        "soc_pct": "soc_no_ov_pct"
    })

    # Sim 2: mit Overflow
    cfg_ov = Config(cap_mwh=args.cap_mwh, power_mw=args.power_mw, soc0_pct=args.soc0_pct, allow_overflow=True)
    sim_ov = simulate_market_only(df, cfg_ov).rename(columns={
        "cmd_power_mw": "cmd_power_ov_mw",
        "soc_pct": "soc_ov_pct"
    })

    # Zusammenführen
    keep_cols = ["timestamp","pct_net","req_power_mw"]
    cmp_df = df[keep_cols].merge(
        sim_no[["timestamp","cmd_power_no_ov_mw","soc_no_ov_pct"]],
        on="timestamp", how="left"
    ).merge(
        sim_ov[["timestamp","cmd_power_ov_mw","soc_ov_pct"]],
        on="timestamp", how="left"
    )



    eps = 1e-6
    cmp_df["delta_mw"] = cmp_df["cmd_power_ov_mw"] - cmp_df["cmd_power_no_ov_mw"]
    cmp_df["delta_abs_mw"] = cmp_df["cmd_power_ov_mw"].abs() - cmp_df["cmd_power_no_ov_mw"].abs()

    # Richtung des Marktsignals (mit Toleranz)
    req = cmp_df["req_power_mw"].to_numpy()
    req_sign = np.where(req > eps, 1.0, np.where(req < -eps, -1.0, 0.0))
    cmp_df["req_sign"] = req_sign
    cmp_df["delta_in_dir_mw"] = cmp_df["delta_mw"] * cmp_df["req_sign"]

    # einfache Flags (sollten i.d.R. nicht negativ sein)
    cmp_df["viol_abs"] = cmp_df["delta_abs_mw"] < -1e-6
    cmp_df["viol_in_dir"] = (cmp_df["delta_in_dir_mw"] < -1e-6) & (cmp_df["req_sign"] != 0)


    # CSV raus
    out_csv = outdir / "compare_overflow.csv"
    cmp_df.to_csv(out_csv, index=False)

    # --- KPI-Vergleich (neu & konsistent) ---
    dt = 0.25

    # Basis: bereits vorhandene Kennzahlen aus _metrics(...)
    met_no = _metrics(cmp_df.rename(columns={"cmd_power_no_ov_mw":"cmd_power_mw"}), "cmd_power_mw", thr=args.activation_threshold_mw)
    met_ov = _metrics(cmp_df.rename(columns={"cmd_power_ov_mw":"cmd_power_mw"}), "cmd_power_mw", thr=args.activation_threshold_mw)

    # Unmet-Dekomposition: req vs. delivered (Beträge)
    r   = cmp_df["req_power_mw"].abs().to_numpy()
    pno = cmp_df["cmd_power_no_ov_mw"].abs().to_numpy()
    pov = cmp_df["cmd_power_ov_mw"].abs().to_numpy()

    unmet_no_mwh = float(np.clip(r - pno, 0, None).sum() * dt)   # ohne Overflow (Power- + Energie-Limit)
    unmet_ov_mwh = float(np.clip(r - pov, 0, None).sum() * dt)   # mit Overflow  (≈ reines Power-Limit)
    delta_abs_mwh = float(np.clip(pov - pno, 0, None).sum() * dt)  # Overflow-Mehrmenge (nur Energie-Limit)
    identity_gap_mwh = unmet_no_mwh - unmet_ov_mwh - delta_abs_mwh  # ~0 (Rundung)

    # Richtungs-korrigiertes ΔP: sollte >= 0 sein
    eps = 1e-6
    req_sign = np.where(cmp_df["req_power_mw"] > eps, 1.0,
                np.where(cmp_df["req_power_mw"] < -eps, -1.0, 0.0))
    delta_mw = (cmp_df["cmd_power_ov_mw"] - cmp_df["cmd_power_no_ov_mw"]).to_numpy()
    delta_in_dir_mw = delta_mw * req_sign
    sum_delta_in_dir_mwh = float(np.clip(delta_in_dir_mw, 0, None).sum() * dt)

    # einfache Konsistenzzähler
    neg_delta_abs_count  = int(((pov - pno) < -1e-6).sum())                       # |P_ov| < |P_no|  (sollte 0 sein)
    neg_delta_in_dir_count = int(((delta_in_dir_mw < -1e-6) & (req_sign != 0)).sum())  # ΔP entgegen Marktrichtung

    # KPI-Tabelle bauen
    kpi_df = pd.DataFrame([
        {
            "scenario": "ohne_overflow",
            **met_no,
            "unmet_market_mwh": unmet_no_mwh,
        },
        {
            "scenario": "mit_overflow",
            **met_ov,
            "unmet_market_mwh": unmet_ov_mwh,  # ≈ Power-Limit
        },
        {
            "scenario": "delta(ov-no)",
            "pos_mwh":          met_ov["pos_mwh"]  - met_no["pos_mwh"],
            "neg_mwh":          met_ov["neg_mwh"]  - met_no["neg_mwh"],
            "net_mwh":          met_ov["net_mwh"]  - met_no["net_mwh"],
            "mean_abs_mw":      met_ov["mean_abs_mw"] - met_no["mean_abs_mw"],
            "activation_share": met_ov["activation_share"] - met_no["activation_share"],
            # Peaks bleiben leer/sinnlos für Delta
        },
        {
            "scenario": "checks",
            "unmet_no_mwh":          unmet_no_mwh,
            "unmet_ov_mwh":          unmet_ov_mwh,
            "delta_abs_mwh":         delta_abs_mwh,
            "sum_delta_in_dir_mwh":  sum_delta_in_dir_mwh,
            "identity_gap_mwh":      identity_gap_mwh,
            "neg_delta_abs_count":   neg_delta_abs_count,
            "neg_delta_in_dir_count":neg_delta_in_dir_count,
        }
    ])

    # Speichern
    kpi_path = outdir / "compare_overflow_kpis.csv"
    kpi_df.to_csv(kpi_path, index=False)
    print(f"OUT: {kpi_path}")


    # Plots
    # SoC-Overlays (nutzen vorhandene Funktion für Grenzen)
    tmp_no = pd.DataFrame({"timestamp": cmp_df["timestamp"], "soc_pct": cmp_df["soc_no_ov_pct"]})
    tmp_ov = pd.DataFrame({"timestamp": cmp_df["timestamp"], "soc_pct": cmp_df["soc_ov_pct"]})
    _plot_soc_compare(tmp_no, tmp_ov, outdir / "soc_compare.png", "SoC – ohne vs. mit Overflow")
    plot_soc_with_bounds(tmp_ov, outdir / "soc_overflow_only.png", "SoC mit Overflow (Grenzen sichtbar)")

    # Power-Overlays + Differenz
    tmp_no_p = pd.DataFrame({"timestamp": cmp_df["timestamp"], "cmd_power_mw": cmp_df["cmd_power_no_ov_mw"]})
    tmp_ov_p = pd.DataFrame({"timestamp": cmp_df["timestamp"], "cmd_power_mw": cmp_df["cmd_power_ov_mw"]})
    _plot_power_compare(tmp_no_p, tmp_ov_p, outdir / "power_compare.png", "Leistung – ohne vs. mit Overflow")
    _plot_power_diff_signed(tmp_no_p, tmp_ov_p, outdir / "power_diff_signed.png",
                        "ΔP (Overflow − ohne) – roh (kann ± sein)")
    _plot_power_diff_in_dir(cmp_df, outdir / "power_diff_in_direction.png",
                        "ΔP in Marktrichtung (sollte ≥ 0 sein)")


    # --- Konsolenoutput (neu & konsistent) ---
    delta_summary = {
        "pos_mwh": round(met_ov["pos_mwh"] - met_no["pos_mwh"], 3),
        "neg_mwh": round(met_ov["neg_mwh"] - met_no["neg_mwh"], 3),
        "net_mwh": round(met_ov["net_mwh"] - met_no["net_mwh"], 3),
        "mean_abs_mw": round(met_ov["mean_abs_mw"] - met_no["mean_abs_mw"], 3),
        "activation_share": round(met_ov["activation_share"] - met_no["activation_share"], 4),
    }

    print("=== KPIs (ohne Overflow) ===", met_no)
    print("=== KPIs (mit Overflow)  ===", met_ov)
    print("=== Delta (ov - no)      ===", delta_summary)

    print(
        "Unmet (ohne) = {:.3f} MWh | "
        "Unmet (mit, Power-Limit) = {:.3f} MWh | "
        "Overflow-Mehrmenge = {:.3f} MWh | "
        "Identitäts-Lücke = {:.3f} MWh"
        .format(unmet_no_mwh, unmet_ov_mwh, delta_abs_mwh, identity_gap_mwh)
    )

    print(
        "ΔP in Marktrichtung (Summe) = {:.3f} MWh | "
        "neg_delta_abs_count = {} | "
        "neg_delta_in_dir_count = {}"
        .format(sum_delta_in_dir_mwh, neg_delta_abs_count, neg_delta_in_dir_count)
    )

    print(f"OUT (Zeitreihe): {out_csv}")
    print(f"OUT (KPIs): {kpi_path}")
    print("PNGs:", ", ".join([
        "soc_compare.png",
        "soc_overflow_only.png",
        "power_compare.png",
        "power_diff_signed.png",
        "power_diff_in_direction.png",
    ]))

    
if __name__ == "__main__":
    main()
