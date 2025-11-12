
from __future__ import annotations
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

def plot_soc(df: pd.DataFrame, out_png: Path, title: str = "SoC-Verlauf") -> None:
    plt.figure(figsize=(12, 3.4))
    plt.plot(df["timestamp"], df["soc_pct"], lw=0.9, label="SoC [%]")
    plt.ylim(0, 100)
    plt.ylabel("SoC [%]")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()

def plot_power(df: pd.DataFrame, out_png: Path, title: str = "Leistung (15-min)") -> None:
    plt.figure(figsize=(12, 3.6))
    plt.plot(df["timestamp"], df["cmd_power_mw"], lw=1.0, drawstyle="steps-pre", label="P_cmd [MW]")
    plt.axhline(0, ls="--", lw=0.8)
    plt.ylabel("MW")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()

def plot_pct_net(df_in: pd.DataFrame, out_png: Path, title: str = "Netto-Aktivierung (%)") -> None:
    plt.figure(figsize=(12, 3.2))
    plt.plot(df_in["timestamp"], df_in["pct_net"], lw=0.7, label="pct_net [%]")
    plt.axhline(0, ls="--", lw=0.8)
    plt.ylabel("%")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()


def plot_activation_rates(df: pd.DataFrame, out_png: Path, title: str = "Aktivierungsquoten (SRL+ / SRL−)") -> None:
    """
    Plottet SRL+ Aktivierungsquote positiv (pct_pos) und SRL− als negative Werte (-pct_neg).
    Erwartet Spalten: timestamp, pct_pos, pct_neg (siehe ensure_pct_cols).
    """
    import matplotlib.pyplot as plt

    if not {"pct_pos", "pct_neg"}.issubset(df.columns):
        raise KeyError("Erwarte Spalten 'pct_pos' und 'pct_neg' (ensure_pct_cols vor dem Plotten aufrufen).")

    plt.figure(figsize=(12, 3.6))
    plt.plot(df["timestamp"], df["pct_pos"], lw=0.9, label="SRL+ [%]")
    plt.plot(df["timestamp"], -df["pct_neg"], lw=0.9, label="SRL− [%] (negiert)")
    plt.axhline(0, ls="--", lw=0.8)
    plt.ylabel("%")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()


def plot_soc_with_bounds(df: pd.DataFrame, out_png: Path, title: str = "SoC mit Grenzen") -> None:
    """
    Plottet SoC[%] mit roten Grenzlinien bei 0% und 100%.
    Werte dürfen <0 bzw. >100 sein (Overflow sichtbar).
    """
    plt.figure(figsize=(12, 3.4))
    plt.plot(df["timestamp"], df["soc_pct"], lw=0.9, label="SoC [%]")
    # explizit gewünschte Farbe: rot für Grenzen
    plt.axhline(0,  color="red", lw=1.0)
    plt.axhline(100, color="red", lw=1.0)
    plt.ylabel("SoC [%]")
    plt.xlabel("Zeit")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()

def plot_power_components_fixed_bias(df: pd.DataFrame, out_png: Path, title: str = "Leistung: SRL + Bias (gestapelt)") -> None:
    """
    Erwartet Spalten: timestamp, market_power_mw, bias_power_mw, cmd_power_mw
    Für kurze Fenster (<= 96 Intervalle = 1 Tag) werden gestapelte Säulen gezeichnet.
    Für längere Fenster fallback auf Linien (übersichtlicher).
    """
    if not {"market_power_mw","bias_power_mw","cmd_power_mw"}.issubset(df.columns):
        raise KeyError("Erwarte Spalten: market_power_mw, bias_power_mw, cmd_power_mw")

    d = df.copy()
    n = len(d)
    ts = d["timestamp"]

    M = d["market_power_mw"].astype(float)
    B = d["bias_power_mw"].astype(float)
    C = d["cmd_power_mw"].astype(float)

    if n <= 96:
        # Gestapelte Säulen (positiv/negativ getrennt)
        x = np.arange(n)
        width = 0.9  # schmal für Lesbarkeit

        M_pos = M.clip(lower=0.0)
        B_pos = B.clip(lower=0.0)
        M_neg = M.clip(upper=0.0)
        B_neg = B.clip(upper=0.0)

        # Positive Stapel
        plt.figure(figsize=(12, 3.8))
        plt.bar(x, M_pos, width=width, label="SRL-Anteil (pos/neg)", linewidth=0)       # keine Farbvorgabe
        plt.bar(x, B_pos, width=width, bottom=M_pos, linewidth=0)

        # Negative Stapel (bottom ist bereits negativ)
        plt.bar(x, M_neg, width=width, linewidth=0)
        plt.bar(x, B_neg, width=width, bottom=M_neg, linewidth=0)

        # Setpoint als feine Linie/Marker
        plt.plot(x, C, lw=0.9, marker=".", ms=3, label="Setpoint (P_cmd)")

        plt.axhline(0, ls="--", lw=0.8)
        plt.ylabel("MW")
        plt.title(title)
        # Ticks: wenige, dafür human-readable
        idx = np.linspace(0, n-1, num=min(8, n), dtype=int)
        plt.xticks(idx, [ts.iloc[i].strftime("%d.%m %H:%M") for i in idx], rotation=30, ha="right")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_png, dpi=150); plt.close()
    else:
        # Linien-Darstellung für lange Fenster
        plt.figure(figsize=(12, 3.6))
        plt.plot(ts, M, lw=0.8, label="SRL-Anteil")
        plt.plot(ts, B, lw=0.8, label="Bias-Anteil")
        plt.plot(ts, C, lw=0.9, label="Setpoint (P_cmd)")
        plt.axhline(0, ls="--", lw=0.8)
        plt.ylabel("MW")
        plt.title(title)
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_png, dpi=150); plt.close()

def plot_soc_with_target(df: pd.DataFrame, out_png: Path,
                         target_soc_pct: float = 50.0,
                         deadband_pct: float = 0.0,
                         title: str = "SoC mit Grenzen & Zielband") -> None:
    """
    Erwartet Spalten: timestamp, soc_pct
    Zeichnet rote Grenzlinien (0%/100%) + Ziel-SoC (optional Deadband).
    """
    if not {"soc_pct","timestamp"}.issubset(df.columns):
        raise KeyError("Erwarte Spalten: timestamp, soc_pct")

    ts = df["timestamp"]
    soc = df["soc_pct"].astype(float)

    plt.figure(figsize=(12, 3.6))
    plt.plot(ts, soc, lw=0.9, label="SoC [%]")

    # explizit gewünschte rote Grenzen
    plt.axhline(0, color="red", lw=1.0)
    plt.axhline(100, color="red", lw=1.0)

    # Ziel + Deadband
    plt.axhline(target_soc_pct, ls="--", lw=0.9, label=f"Ziel SoC = {target_soc_pct:.0f}%")
    if deadband_pct and deadband_pct > 0:
        lo = target_soc_pct - deadband_pct
        hi = target_soc_pct + deadband_pct
        lo = max(lo, -5)   # kleine visuelle Sicherheiten
        hi = min(hi, 105)
        plt.fill_between(ts, lo, hi, alpha=0.1, label="Deadband")

    plt.ylim(min(soc.min(), -5), max(soc.max(), 105))
    plt.ylabel("%"); plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150); plt.close()


def plot_budget_utilization(df: pd.DataFrame, out_png: Path,
                            title: str = "Budget-Nutzung (Market vs. Bias)") -> None:
    """
    Erwartet Spalten:
      - market_budget_max_mw, bias_budget_max_mw
      - market_power_mw, bias_power_mw
    """
    need = {"market_budget_max_mw","bias_budget_max_mw","market_power_mw","bias_power_mw","timestamp"}
    if not need.issubset(df.columns):
        raise KeyError(f"Erwarte Spalten: {need}")

    eps = 1e-9
    mb = df["market_budget_max_mw"].astype(float).replace(0, np.nan)
    bb = df["bias_budget_max_mw"].astype(float).replace(0, np.nan)
    mu = (df["market_power_mw"].abs() / (mb + eps)) * 100.0
    bu = (df["bias_power_mw"].abs() / (bb + eps)) * 100.0

    plt.figure(figsize=(12, 3.4))
    plt.plot(df["timestamp"], mu, lw=0.9, label="Market-Budget [%]")
    plt.plot(df["timestamp"], bu, lw=0.9, label="Bias-Budget [%]")
    plt.axhline(100, ls="--", lw=0.8)
    plt.ylabel("%"); plt.title(title); plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150); plt.close()


def plot_cum_energy_components(df: pd.DataFrame, out_png: Path,
                               title: str = "Kumulierte Energieanteile (|SRL| vs. |Bias|)") -> None:
    """
    Erwartet Spalten: timestamp, market_power_mw, bias_power_mw
    Summiert |P|*Δt (Δt=0.25 h) separat und plottet kumulativ.
    """
    if not {"market_power_mw","bias_power_mw","timestamp"}.issubset(df.columns):
        raise KeyError("Erwarte Spalten: timestamp, market_power_mw, bias_power_mw")

    dt = 0.25
    e_m = (df["market_power_mw"].abs() * dt).astype(float).cumsum()
    e_b = (df["bias_power_mw"].abs() * dt).astype(float).cumsum()

    plt.figure(figsize=(12, 3.4))
    plt.plot(df["timestamp"], e_m, lw=1.0, label="|SRL|-Energie [MWh]")
    plt.plot(df["timestamp"], e_b, lw=1.0, label="|Bias|-Energie [MWh]")
    plt.ylabel("MWh"); plt.title(title)
    plt.legend(); plt.tight_layout()
    plt.savefig(out_png, dpi=150); plt.close()


def plot_power_components_bars_with_setpoint(
    df: pd.DataFrame,
    out_png: Path,
    title: str = "SRL & Korrektur (gestapelt) + Setpoint",
    max_intervals: int = 96,
    bar_width: float = 0.9,
    connect_line: bool = True,   # durchgängige Linie
    step_line: bool = True,      # als Stufenlinie (15-min konstant)
    show_segments: bool = False, # kurze Striche zusätzlich
    bar_mode: str = "always",    # "auto" | "always" | "off" (erzwinge Balken)
) -> None:
    """
    Erwartet Spalten: timestamp, market_power_mw, bias_power_mw, cmd_power_mw
    Balken identisch zu plot_power_components_bars_with_soc (Farben/Stack):
      - SRL+ (blau, positiv)
      - SRL− (orange, negativ)
      - Korrektur (grün, pos/neg auf SRL gestapelt)
    Setpoint (P_cmd) als schwarze Linie/Step.
    """
    need = {"timestamp","market_power_mw","bias_power_mw","cmd_power_mw"}
    if not need.issubset(df.columns):
        raise KeyError(f"Erwarte Spalten: {need}")

    d = df.sort_values("timestamp").reset_index(drop=True)
    n = len(d)
    x = np.arange(n)

    M = d["market_power_mw"].astype(float).to_numpy()
    B = d["bias_power_mw"].astype(float).to_numpy()
    C = d["cmd_power_mw"].astype(float).to_numpy()

    M_pos = np.clip(M, 0, None)      # SRL+
    M_neg = np.clip(M, None, 0)      # SRL−
    B_pos = np.clip(B, 0, None)      # Korrektur (entladen)
    B_neg = np.clip(B, None, 0)      # Korrektur (laden)

    use_bars = (bar_mode == "always") or (bar_mode == "auto" and n <= max_intervals)

    if use_bars:
        fig, ax = plt.subplots(figsize=(12, 4.2))

        # --- Balken identisch wie in plot_power_components_bars_with_soc ---
        ax.bar(x, M_pos, width=bar_width, color="blue",   alpha=0.8, label="SRL+ (blau)",   linewidth=0)
        ax.bar(x, B_pos, width=bar_width, color="green",  alpha=0.8, label="Korrektur (grün)", linewidth=0, bottom=M_pos)
        ax.bar(x, M_neg, width=bar_width, color="orange", alpha=0.8, label="SRL− (orange)", linewidth=0)
        ax.bar(x, B_neg, width=bar_width, color="green",  alpha=0.8, linewidth=0, bottom=M_neg)

        # Setpoint
        half = bar_width / 2.0
        if show_segments:
            for i in range(n):
                ax.hlines(C[i], x[i]-half, x[i]+half, colors="black", linewidth=1.0, zorder=6)

        if connect_line:
            if step_line:
                ax.step(x, C, where="mid", color="black", lw=1.2, label="Setpoint (P_cmd)", zorder=7)
            else:
                ax.plot(x, C, color="black", lw=1.2, label="Setpoint (P_cmd)", zorder=7)
        else:
            ax.plot(x, C, "k.", ms=2, label="Setpoint (P_cmd)", zorder=7)

        ax.axhline(0, ls="--", lw=0.8)
        ax.set_ylabel("MW")
        ax.set_title(title)

        ts = pd.to_datetime(d["timestamp"])
        idx = np.linspace(0, n - 1, num=min(8, n), dtype=int)
        ax.set_xticks(idx)
        ax.set_xticklabels([ts.iloc[i].strftime("%d.%m %H:%M") for i in idx], rotation=30, ha="right")

        # Legende deduplizieren
        h1, l1 = ax.get_legend_handles_labels()
        uniq = dict(zip(l1, h1))
        ax.legend(uniq.values(), uniq.keys(), loc="upper left")

        fig.tight_layout()
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
    else:
        # Fallback (lange Fenster): Linien
        plt.figure(figsize=(12, 3.6))
        plt.plot(d["timestamp"], M, lw=0.8, label="SRL")
        plt.plot(d["timestamp"], B, lw=0.8, label="Korrektur")
        plt.plot(d["timestamp"], C, lw=1.0, label="Setpoint (P_cmd)")
        plt.axhline(0, ls="--", lw=0.8)
        plt.ylabel("MW"); plt.title(title); plt.legend()
        plt.tight_layout(); plt.savefig(out_png, dpi=150); plt.close()

def plot_power_components_bars_with_soc(
    df: pd.DataFrame,
    out_png: Path,
    title: str = "SRL & Korrektur (gestapelt) + SoC",
    max_intervals: int = 96,
    bar_width: float = 0.9,
    target_soc_pct: float | None = None,
    deadband_pct: float = 0.0,
    connect_line: bool = True,       # NEU: SoC-Punkte verbinden
    show_segments: bool = True,      # NEU: kurze SoC-Segmente pro Intervall anzeigen
) -> None:
    """
    Erwartet Spalten: timestamp, market_power_mw, bias_power_mw, cmd_power_mw, soc_pct
    - Gestapelte Säulen: SRL+ (blau), SRL− (orange), Korrektur (grün; pos/neg)
    - Pro Intervall eine kurze schwarze Horizontallinie auf der RECHTEN y-Achse (= SoC [%])
    Hinweis: Einheiten unterscheiden sich (MW vs %). Die SoC-Linie 'liegt' nicht physikalisch zwischen den Säulen.
    """
    need = {"timestamp","market_power_mw","bias_power_mw","cmd_power_mw","soc_pct"}
    if not need.issubset(df.columns):
        raise KeyError(f"Erwarte Spalten: {need}")

    d = df.sort_values("timestamp").reset_index(drop=True)
    n = len(d)
    x = np.arange(n)

    M = d["market_power_mw"].astype(float).to_numpy()
    B = d["bias_power_mw"].astype(float).to_numpy()
    SOC = d["soc_pct"].astype(float).to_numpy()

    M_pos = np.clip(M, 0, None)      # SRL+
    M_neg = np.clip(M, None, 0)      # SRL-
    B_pos = np.clip(B, 0, None)      # Korrektur (entladen)
    B_neg = np.clip(B, None, 0)      # Korrektur (laden)

    fig, ax = plt.subplots(figsize=(12, 4.4))

    # Gestapelte Balken (linke Achse in MW)
    ax.bar(x, M_pos, width=bar_width, color="blue",   alpha=0.8, label="SRL+ (blau)",   linewidth=0)
    ax.bar(x, B_pos, width=bar_width, color="green",  alpha=0.8, label="Korrektur (grün)", linewidth=0, bottom=M_pos)
    ax.bar(x, M_neg, width=bar_width, color="orange", alpha=0.8, label="SRL− (orange)", linewidth=0)
    ax.bar(x, B_neg, width=bar_width, color="green",  alpha=0.8, linewidth=0, bottom=M_neg)

    ax.axhline(0, ls="--", lw=0.8)
    ax.set_ylabel("MW")

    # Rechte Achse: SoC [%] als kurze schwarze Linien pro Intervall
    ax2 = ax.twinx()
    half = bar_width / 2.0
    if show_segments:
        for i in range(n):
            ax2.hlines(SOC[i], x[i]-half, x[i]+half, colors="black", linewidth=1.0, zorder=5)
    
    if connect_line:
        ax2.plot(x, SOC, color="black", lw=1.2, label="SoC [%] (rechte Achse)", zorder=6)
    else:
        ax2.plot(x, SOC, "k.", ms=2, label="SoC [%] (rechte Achse)", zorder=6)

    ax2.set_ylabel("SoC [%]")

    # Ziel & Deadband (optional) auf rechter Achse
    if target_soc_pct is not None:
        ax2.axhline(target_soc_pct, ls="--", lw=0.9)
        if deadband_pct and deadband_pct > 0:
            lo = target_soc_pct - deadband_pct
            hi = target_soc_pct + deadband_pct
            ax2.fill_between(x, lo, hi, alpha=0.08)

    # X-Ticks schön beschriften (≤ 96 Intervalle empfohlen)
    ts = pd.to_datetime(d["timestamp"])
    idx = np.linspace(0, n - 1, num=min(8, n), dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([ts.iloc[i].strftime("%d.%m %H:%M") for i in idx], rotation=30, ha="right")

    # Gemeinsamer Titel + Legende (unique)
    ax.set_title(title)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    lab2handle = {**dict(zip(l1, h1)), **dict(zip(l2, h2))}
    ax.legend(lab2handle.values(), lab2handle.keys(), loc="lower left")

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)

def plot_power_components_bars_with_soc2(
    df: pd.DataFrame,
    out_png: Path,
    title: str = "SRL & Korrektur (gestapelt) + SoC",
    max_intervals: int = 96,
    bar_width: float = 0.9,
    target_soc_pct: float | None = None,
    deadband_pct: float = 0.0,
    connect_line: bool = True,
    show_segments: bool = False,
    color_alpha: float = 0.55,     # NEU: Transparenz für alle farbigen Elemente
    line_alpha_fallback: float = 0.65,  # NEU: Linien-Alpha im Fallback
) -> None:
    need = {"timestamp","market_power_mw","bias_power_mw","cmd_power_mw","soc_pct"}
    if not need.issubset(df.columns):
        raise KeyError(f"Erwarte Spalten: {need}")

    d = df.sort_values("timestamp").reset_index(drop=True)
    n = len(d); x = np.arange(n)

    M = d["market_power_mw"].astype(float).to_numpy()
    B = d["bias_power_mw"].astype(float).to_numpy()
    SOC = d["soc_pct"].astype(float).to_numpy()

    M_pos = np.clip(M, 0, None);  M_neg = np.clip(M, None, 0)
    B_pos = np.clip(B, 0, None);  B_neg = np.clip(B, None, 0)

    fig, ax = plt.subplots(figsize=(12, 4.4))

    # Balken mit reduzierter Sättigung (alpha)
    ax.bar(x, M_pos, width=bar_width, color="blue",   alpha=color_alpha, label="SRL+ (blau)",   linewidth=0)
    ax.bar(x, B_pos, width=bar_width, color="green",  alpha=color_alpha, label="Korrektur (grün)", linewidth=0, bottom=M_pos)
    ax.bar(x, M_neg, width=bar_width, color="orange", alpha=color_alpha, label="SRL− (orange)", linewidth=0)
    ax.bar(x, B_neg, width=bar_width, color="green",  alpha=color_alpha, linewidth=0, bottom=M_neg)

    ax.axhline(0, ls="--", lw=0.8)
    ax.set_ylabel("MW")

    # Rechte Achse: SoC [%] – schwarz, deckend
    ax2 = ax.twinx()
    half = bar_width / 2.0
    if show_segments:
        for i in range(n):
            ax2.hlines(SOC[i], x[i]-half, x[i]+half, colors="black", linewidth=1.0, zorder=5)
    if connect_line:
        ax2.plot(x, SOC, color="black", lw=1.2, label="SoC [%] (rechte Achse)", zorder=6)
    else:
        ax2.plot(x, SOC, "k.", ms=2, label="SoC [%] (rechte Achse)", zorder=6)
    ax2.set_ylabel("SoC [%]")

    # Zielband optional
    if target_soc_pct is not None:
        ax2.axhline(target_soc_pct, ls="--", lw=0.9)
        if deadband_pct and deadband_pct > 0:
            lo = target_soc_pct - deadband_pct
            hi = target_soc_pct + deadband_pct
            ax2.fill_between(x, lo, hi, alpha=0.08)  # bleibt dezent

    ts = pd.to_datetime(d["timestamp"])
    idx = np.linspace(0, n - 1, num=min(8, n), dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([ts.iloc[i].strftime("%d.%m %H:%M") for i in idx], rotation=30, ha="right")

    ax.set_title(title)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    lab2handle = {**dict(zip(l1, h1)), **dict(zip(l2, h2))}
    ax.legend(lab2handle.values(), lab2handle.keys(), loc="upper left")

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)

def plot_power_components_bars_with_setpoint2(
    df: pd.DataFrame,
    out_png: Path,
    title: str = "SRL & Korrektur (gestapelt) + Setpoint",
    max_intervals: int = 96,
    bar_width: float = 0.9,
    connect_line: bool = True,
    step_line: bool = True,
    show_segments: bool = False,
    bar_mode: str = "always",
    color_alpha: float = 0.55,       # NEU: Transparenz für Balken
    line_alpha_fallback: float = 0.65,  # NEU: Linien-Alpha im Fallback
) -> None:
    need = {"timestamp","market_power_mw","bias_power_mw","cmd_power_mw"}
    if not need.issubset(df.columns):
        raise KeyError(f"Erwarte Spalten: {need}")

    d = df.sort_values("timestamp").reset_index(drop=True)
    n = len(d); x = np.arange(n)

    M = d["market_power_mw"].astype(float).to_numpy()
    B = d["bias_power_mw"].astype(float).to_numpy()
    C = d["cmd_power_mw"].astype(float).to_numpy()

    M_pos = np.clip(M, 0, None);  M_neg = np.clip(M, None, 0)
    B_pos = np.clip(B, 0, None);  B_neg = np.clip(B, None, 0)

    use_bars = (bar_mode == "always") or (bar_mode == "auto" and n <= max_intervals)

    if use_bars:
        fig, ax = plt.subplots(figsize=(12, 4.2))

        # Balken identisch wie bei SOC-Plot, aber mit Transparenz
        ax.bar(x, M_pos, width=bar_width, color="blue",   alpha=color_alpha, label="SRL+ (blau)",   linewidth=0)
        ax.bar(x, B_pos, width=bar_width, color="green",  alpha=color_alpha, label="Korrektur (grün)", linewidth=0, bottom=M_pos)
        ax.bar(x, M_neg, width=bar_width, color="orange", alpha=color_alpha, label="SRL− (orange)", linewidth=0)
        ax.bar(x, B_neg, width=bar_width, color="green",  alpha=color_alpha, linewidth=0, bottom=M_neg)

        # Setpoint – schwarz, deckend
        half = bar_width / 2.0
        if show_segments:
            for i in range(n):
                ax.hlines(C[i], x[i]-half, x[i]+half, colors="black", linewidth=1.0, zorder=6)
        if connect_line:
            if step_line:
                ax.step(x, C, where="mid", color="black", lw=1.2, label="Setpoint (P_cmd)", zorder=7)
            else:
                ax.plot(x, C, color="black", lw=1.2, label="Setpoint (P_cmd)", zorder=7)
        else:
            ax.plot(x, C, "k.", ms=2, label="Setpoint (P_cmd)", zorder=7)

        ax.axhline(0, ls="--", lw=0.8)
        ax.set_ylabel("MW"); ax.set_title(title)

        ts = pd.to_datetime(d["timestamp"])
        idx = np.linspace(0, n - 1, num=min(8, n), dtype=int)
        ax.set_xticks(idx)
        ax.set_xticklabels([ts.iloc[i].strftime("%d.%m %H:%M") for i in idx], rotation=30, ha="right")

        h1, l1 = ax.get_legend_handles_labels()
        uniq = dict(zip(l1, h1))
        ax.legend(uniq.values(), uniq.keys(), loc="upper left")

        fig.tight_layout()
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
    else:
        # Fallback (lange Fenster): Linien mit reduzierter Deckung
        plt.figure(figsize=(12, 3.6))
        plt.plot(d["timestamp"], M, lw=0.8, alpha=line_alpha_fallback, label="SRL")
        plt.plot(d["timestamp"], B, lw=0.8, alpha=line_alpha_fallback, label="Korrektur")
        plt.plot(d["timestamp"], C, lw=1.0, color="black", label="Setpoint (P_cmd)")
        plt.axhline(0, ls="--", lw=0.8)
        plt.ylabel("MW"); plt.title(title); plt.legend()
        plt.tight_layout(); plt.savefig(out_png, dpi=150); plt.close()
