# src/simple_srl_sim/cli.py
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

from .analyzer import load_year_csv, ensure_pct_cols, slice_timeframe
from .storage import Config, simulate_market_only, simulate_market_fixed_bias
from .plotting import plot_soc, plot_soc_with_bounds, plot_power, plot_pct_net, plot_activation_rates, plot_cum_energy_components, plot_budget_utilization, plot_soc_with_target, plot_power_components_fixed_bias, plot_power_components_bars_with_setpoint2, plot_power_components_bars_with_soc2, plot_energy_components3, plot_power_components2
from .build_market_csv import build_market_csv_from_files

def run_sim(input_csv: Path, compare_to: str, cap_mwh: float, power_mw: float, soc0_pct: float,
            outdir: Path, start: str | None = None, end: str | None = None,
            allow_overflow: bool = False,
            mode: str = "market_only",
            target_soc_pct: float = 50.0,
            bias_share_pct: float = 0.0,
            bias_deadband_pct: float = 0.0):
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_year_csv(str(input_csv))
    df = slice_timeframe(df, start, end)
    df = ensure_pct_cols(df, compare_to=compare_to)

    cfg = Config(
        cap_mwh=cap_mwh, power_mw=power_mw, soc0_pct=soc0_pct, allow_overflow=allow_overflow,
        target_soc_pct=target_soc_pct, bias_share_pct=bias_share_pct, bias_deadband_pct=bias_deadband_pct
    )

    if mode == "fixed_bias":
        sim = simulate_market_fixed_bias(df, cfg)
        csv_name = "sim_fixed_bias.csv"
    else:
        sim = simulate_market_only(df, cfg)
        csv_name = "sim_market_only.csv"

    out_csv = outdir / csv_name
    sim.to_csv(out_csv, index=False)

    # cli.py (innerhalb run_sim, NACH sim.to_csv(...))
    if mode == "fixed_bias":
        try:
            # 1) Komponenten-Plot
            plot_power_components_fixed_bias(sim, outdir / "power_components_fixed_bias.png",
                                            title="Leistung: SRL + Bias (gestapelt)")

            # 2) SoC inkl. Zielband
            plot_soc_with_target(sim, outdir / "soc_with_target.png",
                                target_soc_pct=target_soc_pct, deadband_pct=bias_deadband_pct,
                                title="SoC mit Grenzen & Zielband")

            # 3) Budget-Nutzung
            plot_budget_utilization(sim, outdir / "budget_utilization.png",
                                    title="Budget-Nutzung (Market vs. Bias)")

            # 4) Kumulative Energie
            plot_cum_energy_components(sim, outdir / "cum_energy_components.png",
                                    title="Kumulierte Energieanteile (|SRL| vs. |Bias|)")
            
            #plot_power_components_bars_with_setpoint2(sim, outdir / "power_components_bars_with_setpoint.png",
                                    #connect_line=True, step_line=True, show_segments=False,
                                    #bar_mode="always"  # <- Balken identisch zur SOC-Version, Setpoint als Linie)
            #)
            
            #plot_power_components_bars_with_soc2(sim, outdir / "power_components_bars_with_soc.png",
                                #    title="SRL & Korrektur (gestapelt) + SoC (rechte Achse)",
                                #   target_soc_pct=target_soc_pct,
                                #    deadband_pct=bias_deadband_pct,
                                #    connect_line=True,
                                #    show_segments=False,
                                #    max_intervals=10**9
                                #)

            plot_power_components2(
                                    sim,
                                    outdir / "power_components2.png",
                                    title="Leistungskomponenten (SRL & Korrektur)",
                                    bar_width=0.9,
                                    max_intervals=10**9,
                                    color_alpha=0.55,
                                    show_net=True,
                                    net_mode="cmd",      # alternativ: "market_minus_bias"
                                    step_line=True,
                                )
            #plot_energy_components2(
                                    #sim,
                                    #outdir / "energy_components2.png",
                                    #title="Energiekomponenten (SRL & Korrektur) + SoC (rechte Achse)",
                                    #bar_width=0.9,
                                    #max_intervals=10**9,
                                    #color_alpha=0.55,
                                    #show_cum_net=False,
                                    #show_soc=True,        # SoC an
                                    #connect_line=True,    # Linie verbinden
                                    #show_segments=False,  # KEINE kleinen Segment-Striche
                                    #target_soc_pct=target_soc_pct,
                                    #deadband_pct=bias_deadband_pct,
                                #)
            plot_energy_components3(
                                    sim,
                                    outdir / "energy_components3.png",
                                    title="Energiekomponenten (SRL & Korrektur) + SoC",
                                    bar_width=0.9,
                                    max_intervals=10**9,
                                    color_alpha=0.55,
                                    show_cum_net=False,
                                    show_soc=True,
                                    connect_line=True,
                                    show_segments=False,
                                    target_soc_pct=target_soc_pct,
                                    deadband_pct=bias_deadband_pct,
                                    fix_axes=True,
                                    soc_ylim=(-10, 110),
                                )


        except Exception as e:
            print(f"[WARN] Zusatzplots (fixed_bias) konnten nicht erstellt werden: {e}")


    # Plots
    plot_pct_net(df, outdir / "pct_net.png", title="Netto-Aktivierung (%)")
    plot_activation_rates(df, outdir / "activation_rates.png", title="Aktivierungsquoten (SRL+ / SRL−; SRL− negativ)")
    plot_soc(sim, outdir / "soc.png", title=f"SoC – X={cap_mwh} MWh, Y={power_mw} MW")
    plot_soc_with_bounds(sim, outdir / "soc_overflow.png", title="SoC mit Grenzen (Overflow sichtbar)")
    plot_power(sim, outdir / "power.png", title=f"Leistung – X={cap_mwh} MWh, Y={power_mw} MW")

    print(f"CSV: {out_csv}")
    print("Spalten enthalten (fixed_bias): market_power_mw, bias_power_mw, cmd_power_mw, soc_pct") if mode=="fixed_bias" else None
    print(f"PNG: {outdir/'pct_net.png'}")
    print(f"PNG: {outdir/'activation_rates.png'}")
    print(f"PNG: {outdir/'soc.png'}")
    print(f"PNG: {outdir/'soc_overflow.png'}")
    print(f"PNG: {outdir/'power.png'}")

def main():
    ap = argparse.ArgumentParser(description="Simple SRL storage simulator with YAML config")
    ap.add_argument("--config", help="Pfad zu config.yml")
    # Overrides
    ap.add_argument("--input")
    ap.add_argument("--compare-to", choices=["offered","awarded"])
    ap.add_argument("--cap-mwh", type=float)
    ap.add_argument("--power-mw", type=float)
    ap.add_argument("--soc0-pct", type=float)
    ap.add_argument("--outdir")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--allow-overflow", action="store_true")
    ap.add_argument("--mode", choices=["market_only","fixed_bias"])
    ap.add_argument("--target-soc-pct", type=float)
    ap.add_argument("--bias-share-pct", type=float)
    ap.add_argument("--bias-deadband-pct", type=float)
    args = ap.parse_args()

    cfg = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    # Optionaler Build-Step
    build = (cfg.get("build") or {})
    if build.get("enabled"):
        xlsx = Path(build["xlsx"]); ergebnis = Path(build["ergebnis"]); out_csv = Path(build["out_csv"])
        print(f"[BUILD] {xlsx} + {ergebnis} -> {out_csv}")
        build_market_csv_from_files(xlsx, ergebnis, out_csv)

    # Sim-Parameter (YAML + CLI-Override)
    sim = (cfg.get("sim") or {})
    input_csv = Path(args.input or sim.get("input") or build.get("out_csv", ""))
    compare_to = args.compare_to or sim.get("compare_to", "offered")
    cap_mwh = float(args.cap_mwh if args.cap_mwh is not None else sim.get("cap_mwh"))
    power_mw = float(args.power_mw if args.power_mw is not None else sim.get("power_mw"))
    soc0_pct = float(args.soc0_pct if args.soc0_pct is not None else sim.get("soc0_pct", 50.0))
    outdir = Path(args.outdir or sim.get("outdir", "out/first_iter"))
    start = args.start or sim.get("start"); end = args.end or sim.get("end")
    allow_overflow = bool(args.allow_overflow or sim.get("allow_overflow", False))

    mode = args.mode or sim.get("mode", "market_only")
    target_soc_pct = float(args.target_soc_pct if args.target_soc_pct is not None else sim.get("target_soc_pct", 50.0))
    bias_share_pct = float(args.bias_share_pct if args.bias_share_pct is not None else sim.get("bias_share_pct", 0.0))
    bias_deadband_pct = float(args.bias_deadband_pct if args.bias_deadband_pct is not None else sim.get("bias_deadband_pct", 0.0))

    if not input_csv:
        raise SystemExit("Kein input CSV gefunden. Setze sim.input oder build.enabled + build.out_csv.")
    run_sim(input_csv, compare_to, cap_mwh, power_mw, soc0_pct, outdir,
            start=start, end=end, allow_overflow=allow_overflow,
            mode=mode, target_soc_pct=target_soc_pct, bias_share_pct=bias_share_pct, bias_deadband_pct=bias_deadband_pct)

if __name__ == "__main__":
    main()
