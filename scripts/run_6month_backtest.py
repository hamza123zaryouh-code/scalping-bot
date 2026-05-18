"""
XAUUSD 6-Maanden Backtest - Nov 2025 t/m Mei 2026
==================================================
Constraints:
  - Max lot size : 6.0 lots (hard cap)
  - Max dagelijks verlies : €8,000 (FTMO limiet)
  - Max totaal drawdown : €16,000 / 10% (FTMO limiet)
  - Strategie : V18 Sprint Config

Gebruik:
    python scripts/run_6month_backtest.py
    python scripts/run_6month_backtest.py --capital 160000 --start 2025-11-17
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from backend.services.backtest_service import BacktestService
from core.strategy_engine import V18_CFG, V19_CFG, V20_CFG

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

SIG_TYPES = ["A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"]
FTMO_MAX_LOT = 6.0
FTMO_MAX_DAG_EUR = 6_000.0  # €6k daggrens — extra accountbescherming (was €8k)
FTMO_MAX_TOT_PCT = 0.10  # 10% totaal
FTMO_DD_WARN_PCT = 0.05  # 5% waarschuwing


def clr(val: float, fmt: str = "+.2f") -> str:
    c = GREEN if val > 0 else (RED if val < 0 else YELLOW)
    return f"{c}{val:{fmt}}{RESET}"


def hdr(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}")


def sec(title: str) -> None:
    pad = max(1, 70 - len(title))
    print(f"\n{BOLD}{YELLOW}-- {title} {'-' * pad}{RESET}")


def ftmo_badge(ok: bool) -> str:
    return f"{GREEN}{BOLD}GESLAAGD OK{RESET}" if ok else f"{RED}{BOLD}GEZAKT FAIL{RESET}"


def build_v18_cfg_6m(capital: float) -> dict:
    """V18 config met harde FTMO 6-maanden constraints."""
    cfg = dict(V18_CFG)
    cfg["max_lot_size"] = FTMO_MAX_LOT
    cfg["max_daily_loss_eur"] = FTMO_MAX_DAG_EUR
    return cfg


def build_v19_cfg_6m(capital: float) -> dict:
    """V19 config — verbeterde strategie met verliesweek-bescherming."""
    cfg = dict(V19_CFG)
    cfg["max_lot_size"] = FTMO_MAX_LOT
    cfg["max_daily_loss_eur"] = FTMO_MAX_DAG_EUR
    return cfg


def build_v20_cfg_6m(capital: float) -> dict:
    """V20 config — stabiel €20-40k/maand met 3-weken reset systeem."""
    cfg = dict(V20_CFG)
    cfg["max_lot_size"] = FTMO_MAX_LOT
    cfg["max_daily_loss_eur"] = FTMO_MAX_DAG_EUR
    return cfg


def run_6month_backtest(capital: float, start: date, end: date, version: str = "V20") -> None:
    n_days = (end - start).days
    hdr(f"XAUUSD 6-MAANDEN BACKTEST — {start} t/m {end}")
    print(f"  Startkapitaal   : {BOLD}EUR {capital:,.0f}{RESET}")
    print(f"  Periode         : {start} -> {end} ({n_days} kalenderdagen)")
    print(f"  Strategie       : {BOLD}{version} Sprint Config{RESET}")
    print(f"  Max lot size    : {BOLD}{RED}{FTMO_MAX_LOT} lots (hard cap){RESET}")
    print(f"  Max dagl. verlies: {BOLD}{RED}EUR {FTMO_MAX_DAG_EUR:,.0f}{RESET}")
    print(
        f"  Max totaal DD   : {BOLD}{RED}{FTMO_MAX_TOT_PCT * 100:.0f}% = EUR {capital * FTMO_MAX_TOT_PCT:,.0f}{RESET}"
    )

    svc = BacktestService()
    if version == "V20":
        cfg = build_v20_cfg_6m(capital)
    elif version == "V19":
        cfg = build_v19_cfg_6m(capital)
    else:
        cfg = build_v18_cfg_6m(capital)

    sec("DATA LADEN")
    print(f"  GC=F (Gold Futures) H1 data ophalen voor {start} -> {end}...")
    try:
        df_raw = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as e:
        print(f"\n{RED}FOUT bij data laden: {e}{RESET}")
        sys.exit(1)

    start_ts = pd.Timestamp(start, tz="UTC")
    df_period = df_feat[df_feat.index >= start_ts]
    print(f"  {len(df_raw)} H1 bars totaal geladen | {len(df_period)} bars in de periode")

    sec("BACKTEST UITVOEREN")
    print(
        f"  {version} Config: risk_a={cfg['risk_a'] * 100:.1f}% | "
        f"risk_b={cfg['risk_b'] * 100:.1f}% | risk_c={cfg['risk_c'] * 100:.1f}%"
    )
    print(f"  TP ratios: TP1={cfg['tp1_r']}R | TP2={cfg['tp2_r']}R | TP3={cfg['tp3_r']}R")
    print(f"  Lot cap: {cfg['max_lot_size']} lots | Dagverlies cap: EUR {cfg['max_daily_loss_eur']:,.0f}")
    weekly_boost = cfg.get("compound_boost", 1.1) * 100 - 100
    print(f"  Weekly compound: {'AAN' if cfg.get('weekly_compound') else 'UIT'} (+{weekly_boost:.0f}%/wk)")
    print()

    try:
        trades_raw, final_cap = svc._run_backtest_engine(df_feat, cfg, capital)
    except Exception as e:
        print(f"\n{RED}FOUT bij backtest: {e}{RESET}")
        sys.exit(1)

    if not trades_raw:
        print(f"{RED}Geen trades gegenereerd in de periode.{RESET}")
        sys.exit(1)

    # Filter op de 6-maanden periode
    df = pd.DataFrame(trades_raw)
    df["in_dt"] = pd.to_datetime(df["in"], utc=True, errors="coerce")
    df["uit_dt"] = pd.to_datetime(df["uit"], utc=True, errors="coerce")
    df["pnl"] = df["pnl"].astype(float)
    df["lot_size"] = df.get("lot_size", pd.Series([0.01] * len(df))).astype(float)
    df["sig_type"] = df.get("type", pd.Series(["UNKNOWN"] * len(df)))
    df["result"] = df.get("result", pd.Series(["UNKNOWN"] * len(df)))

    df = df[df["in_dt"] >= start_ts].reset_index(drop=True)

    if df.empty:
        print(f"{RED}Geen trades in de 6-maanden periode gevonden.{RESET}")
        sys.exit(1)

    # ── CORE METRICS ─────────────────────────────────────────────
    pnl_s = df["pnl"]
    wins = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]
    total_pnl = float(pnl_s.sum())
    n_trades = len(df)
    wr = float((pnl_s > 0).mean()) * 100
    pf = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = float(losses.mean()) if not losses.empty else 0.0
    expectancy = float(pnl_s.mean())

    # Use cum_equity from trade records (accounts for V20 banked profit across reset cycles)
    if "cum_equity" in df.columns and df["cum_equity"].notna().any():
        cum_eq = df["cum_equity"].astype(float)
    else:
        cum_eq = pnl_s.cumsum() + capital
    peak = cum_eq.cummax()
    dd_abs = peak - cum_eq
    dd_pct_s = dd_abs / peak * 100
    max_dd_pct = float(dd_pct_s.max())
    max_dd_eur = float(dd_abs.max())

    # Sharpe (trade-based)
    ret_per_trade = pnl_s / capital
    sharpe = 0.0
    if len(ret_per_trade) > 1 and float(ret_per_trade.std(ddof=0)) > 0:
        sharpe = float(ret_per_trade.mean() / ret_per_trade.std(ddof=0) * np.sqrt(252))

    calmar = (total_pnl / capital * 100) / max_dd_pct if max_dd_pct > 0 else 0.0
    trading_days = int(df["in_dt"].dt.normalize().nunique())
    daily_avg = total_pnl / max(trading_days, 1)

    # ── FTMO checks (correcte FTMO regel: verlies vanaf startkapitaal) ──────
    # FTMO "Max Loss" = equity mag nooit < startkapitaal * (1 - 10%) = €144k
    # Dit is ANDERS dan piek-naar-trog drawdown!
    min_equity = float(cum_eq.min())
    ftmo_abs_loss = max(0.0, capital - min_equity)  # verlies t.o.v. start
    ftmo_abs_loss_pct = ftmo_abs_loss / capital * 100
    ftmo_floor = capital * (1.0 - FTMO_MAX_TOT_PCT)  # €144,000
    ftmo_dd_ok = min_equity >= ftmo_floor  # equity boven FTMO vloer

    max_lot_used = float(df["lot_size"].max())
    lot_cap_ok = max_lot_used <= FTMO_MAX_LOT + 0.01

    df["trade_date"] = df["in_dt"].dt.date
    daily_pnl = df.groupby("trade_date")["pnl"].sum()
    worst_day_loss = float(daily_pnl.min())
    daily_dd_ok = abs(worst_day_loss) <= FTMO_MAX_DAG_EUR + 1

    ftmo_passed = ftmo_dd_ok and lot_cap_ok and daily_dd_ok

    # ── OVERALL STATISTIEKEN ─────────────────────────────────────
    sec("6-MAANDEN STATISTIEKEN (OVERALL)")
    stats = [
        ("Totale winst/verlies", f"{clr(total_pnl, '+,.2f')} EUR"),
        ("Totaal rendement", f"{clr(total_pnl / capital * 100, '+.2f')}%"),
        ("Eindsaldo", f"EUR {capital + total_pnl:,.2f}"),
        ("", ""),
        ("Totaal trades", f"{n_trades}"),
        ("Handelsdagen", f"{trading_days} dagen (van {n_days} kalender)"),
        ("Daggemiddelde", f"{clr(daily_avg, '+,.2f')} EUR/dag"),
        ("", ""),
        ("Win rate", f"{wr:.1f}%"),
        ("Profit factor", f"{pf:.2f}"),
        ("Gemiddelde winst", f"{clr(avg_win, '+,.2f')} EUR"),
        ("Gemiddelde verlies", f"{clr(avg_loss, '+,.2f')} EUR"),
        ("Expectancy/trade", f"{clr(expectancy, '+,.2f')} EUR"),
        ("Sharpe ratio", f"{sharpe:.2f}"),
        ("Calmar ratio", f"{calmar:.2f}"),
    ]
    for label, val in stats:
        if label:
            print(f"  {label:<28} {val}")
        else:
            print()

    # ── FTMO COMPLIANCE ANALYSE ──────────────────────────────────
    sec("FTMO COMPLIANCE ANALYSE")
    print(f"  {'Check':<35} {'Waarde':>15} {'Limiet':>12} {'Status':>12}")
    print(f"  {'-' * 35} {'-' * 15} {'-' * 12} {'-' * 12}")

    checks = [
        # Correcte FTMO regel: equity mag nooit onder startkapitaal - 10%
        ("Min equity (FTMO vloer)", f"EUR {min_equity:,.0f}", f">= EUR {ftmo_floor:,.0f}", ftmo_dd_ok),
        (
            "Max verlies v/a start (FTMO)",
            f"EUR {ftmo_abs_loss:,.0f} ({ftmo_abs_loss_pct:.2f}%)",
            f"EUR {capital * FTMO_MAX_TOT_PCT:,.0f} (10%)",
            ftmo_dd_ok,
        ),
        # Piek-naar-trog DD (risicobeheer indicator, niet de FTMO regel zelf)
        ("Piek-naar-trog DD %", f"{max_dd_pct:.2f}%", "info", True),
        ("Max lot size gebruikt", f"{max_lot_used:.2f} lots", f"{FTMO_MAX_LOT:.1f} lots", lot_cap_ok),
        ("Slechtste dag (verlies)", f"EUR {abs(worst_day_loss):,.0f}", f"EUR {FTMO_MAX_DAG_EUR:,.0f}", daily_dd_ok),
    ]

    for label, val, lim, ok in checks:
        status = f"{GREEN}OK OK{RESET}" if ok else f"{RED}FAIL FAIL{RESET}"
        print(f"  {label:<35} {val:>15} {lim:>12} {status:>21}")

    print(f"\n  FTMO EINDOORDEEL: {ftmo_badge(ftmo_passed)}")
    if not ftmo_passed:
        print(f"  {RED}! Één of meer FTMO limieten overschreden — zie boven.{RESET}")

    # Dagelijks verlies distributie
    bad_days = daily_pnl[daily_pnl < -FTMO_MAX_DAG_EUR * 0.5]
    if not bad_days.empty:
        print(f"\n  {YELLOW}Dagen met verlies > 50% daggrens (EUR {FTMO_MAX_DAG_EUR * 0.5:,.0f}):{RESET}")
        for d, v in bad_days.items():
            pct_of_limit = abs(v) / FTMO_MAX_DAG_EUR * 100
            bar = "X" * int(pct_of_limit / 5)
            print(f"    {d}  EUR {v:+,.0f}  {pct_of_limit:.0f}% van daggrens  {RED}{bar}{RESET}")
    else:
        print(f"\n  {GREEN}Geen dagen met verlies > 50% daggrens — uitstekend!{RESET}")

    # ── MAANDOVERZICHT ────────────────────────────────────────────
    sec("MAANDOVERZICHT")
    df["month"] = df["in_dt"].dt.to_period("M").astype(str)
    monthly = (
        df.groupby("month")
        .agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            win_rate=("pnl", lambda s: float((s > 0).mean()) * 100),
            avg_trade=("pnl", "mean"),
            max_lot=("lot_size", "max"),
        )
        .reset_index()
    )

    monthly_target = cfg.get("monthly_profit_target", 0.0)
    monthly_min = cfg.get("monthly_min_target", 0.0)
    months_hit_target = 0
    months_in_range = 0

    running = capital
    print(
        f"  {'Maand':<10} {'Start':>12} {'Trades':>7} {'Win%':>6} {'P&L':>12} "
        f"{'Ret%':>7} {'Max Lot':>9} {'Saldo':>12} {'Doel':>8}"
    )
    print(f"  {'-' * 10} {'-' * 12} {'-' * 7} {'-' * 6} {'-' * 12} {'-' * 7} {'-' * 9} {'-' * 12} {'-' * 8}")
    for _, row in monthly.iterrows():
        p = float(row["pnl"])
        ret = p / running * 100 if running > 0 else 0
        new_bal = running + p
        ml = float(row["max_lot"])
        lot_flag = f"{RED}!" if ml > FTMO_MAX_LOT else ""
        if monthly_target > 0:
            if p >= monthly_target:
                doel_flag = f"{GREEN}TARGET{RESET}"
                months_hit_target += 1
            elif monthly_min > 0 and p >= monthly_min:
                doel_flag = f"{YELLOW}IN RANGE{RESET}"
                months_in_range += 1
            elif p >= 0:
                doel_flag = f"{YELLOW}POSITIEF{RESET}"
            else:
                doel_flag = f"{RED}VERLIES{RESET}"
        else:
            doel_flag = ""
        print(
            f"  {str(row['month']):<10} "
            f"EUR {running:>8,.0f} "
            f"{int(row['trades']):>7} "
            f"{float(row['win_rate']):>5.1f}% "
            f"{clr(p, '+,.0f'):>21} "
            f"{clr(ret, '+.1f'):>14}% "
            f"{ml:>7.2f}{lot_flag}{RESET:>2} "
            f"EUR {new_bal:>8,.0f} "
            f"{doel_flag}"
        )
        running = new_bal

    if monthly_target > 0:
        total_months = len(monthly)
        print(
            f"\n  Maanddoel (EUR {monthly_target:,.0f}): "
            f"{GREEN}{months_hit_target}/{total_months}{RESET} maanden bereikt  |  "
            f"In range (EUR {monthly_min:,.0f}-{monthly_target:,.0f}): "
            f"{YELLOW}{months_in_range}/{total_months}{RESET} maanden"
        )

    # ── V20 RESET CYCLE STATISTIEKEN ─────────────────────────────
    reset_weeks_cfg = cfg.get("reset_weeks", 0)
    if reset_weeks_cfg > 0:
        sec(f"V20 RESET CYCLE STATISTIEKEN (elke {reset_weeks_cfg} weken)")
        reset_trades = df[df["result"] == "RESET"]
        n_resets = len(reset_trades)
        print(f"  Aantal reset-momenten : {n_resets}")
        print(f"  Reset-kapitaal        : EUR {cfg.get('reset_capital', capital):,.0f}")
        if n_resets > 0:
            total_banked = final_cap - capital
            print(f"  Totaal gecumuleerd    : EUR {total_banked:+,.0f}  ({total_banked / capital * 100:+.1f}%)")
        print(f"  Maanddoel stop        : EUR {monthly_target:,.0f}/maand")
        print(
            f"  Verwachte jaaropbrengst: EUR {total_pnl / 6 * 12:+,.0f}  "
            f"({total_pnl / capital / 6 * 12 * 100:.1f}% per jaar)"
        )

    # ── WEEKOVERZICHT ────────────────────────────────────────────
    sec("WEEKOVERZICHT (LAATSTE 26 WEKEN)")
    df["week"] = df["in_dt"].dt.to_period("W").astype(str)
    weekly = (
        df.groupby("week")
        .agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            win_rate=("pnl", lambda s: float((s > 0).mean()) * 100),
            worst_trade=("pnl", "min"),
        )
        .reset_index()
        .sort_values("week")
    )

    wk_eq = capital
    cum_w = 0.0
    print(f"  {'Week':<12} {'Start':>12} {'Trades':>7} {'Win%':>6} {'P&L':>12} {'Ret%':>7} {'Cum Winst':>12}")
    print(f"  {'-' * 12} {'-' * 12} {'-' * 7} {'-' * 6} {'-' * 12} {'-' * 7} {'-' * 12}")
    for _, row in weekly.iterrows():
        wpnl = float(row["pnl"])
        cum_w += wpnl
        wret = wpnl / wk_eq * 100 if wk_eq > 0 else 0
        wwr = float(row["win_rate"])
        print(
            f"  {str(row['week']):<12} "
            f"EUR {wk_eq:>8,.0f} "
            f"{int(row['trades']):>7} "
            f"{wwr:>5.1f}% "
            f"{clr(wpnl, '+,.0f'):>21} "
            f"{clr(wret, '+.1f'):>14}% "
            f"{clr(cum_w, '+,.0f'):>21}"
        )
        wk_eq += wpnl

    # ── SIGNAALTYPE PRESTATIES ───────────────────────────────────
    sec("PRESTATIES PER SIGNAALTYPE")
    print(f"  {'Type':<14} {'Trades':>7} {'Win%':>6} {'P&L Totaal':>14} {'Gem/trade':>12} {'Max Lot':>9} {'Worst':>10}")
    print(f"  {'-' * 14} {'-' * 7} {'-' * 6} {'-' * 14} {'-' * 12} {'-' * 9} {'-' * 10}")
    for st in SIG_TYPES:
        sub = df[df["sig_type"] == st]
        if sub.empty:
            continue
        n = len(sub)
        wr_s = (sub["pnl"] > 0).mean() * 100
        tot = sub["pnl"].sum()
        avg = sub["pnl"].mean()
        ml = float(sub["lot_size"].max())
        worst = float(sub["pnl"].min())
        lot_flag = f"{RED}!" if ml > FTMO_MAX_LOT else " "
        print(
            f"  {st:<14} {n:>7} {wr_s:>5.1f}% "
            f"{clr(tot, '+,.0f'):>23} "
            f"{clr(avg, '+,.0f'):>21} "
            f"{ml:>7.2f}{lot_flag} "
            f"{clr(worst, '+,.0f'):>19}"
        )

    # ── LOT SIZE ANALYSE ─────────────────────────────────────────
    sec("LOT SIZE ANALYSE (FTMO CAP: 6 LOTS)")
    lot_bins = [0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.005, 999]
    lot_labels = ["<0.5", "0.5-1", "1-2", "2-3", "3-4", "4-5", "5-6", ">6"]
    df["lot_bin"] = pd.cut(df["lot_size"], bins=lot_bins, labels=lot_labels, right=False)
    lot_dist = df.groupby("lot_bin", observed=True).agg(
        count=("lot_size", "size"),
        pnl=("lot_size", lambda s: df.loc[s.index, "pnl"].sum()),
    )
    print(f"  {'Lot range':<10} {'Trades':>8} {'% van totaal':>14} {'P&L':>14}")
    print(f"  {'-' * 10} {'-' * 8} {'-' * 14} {'-' * 14}")
    for bin_label, row in lot_dist.iterrows():
        pct = row["count"] / n_trades * 100 if n_trades > 0 else 0
        flag = f" {RED}(>CAP!){RESET}" if bin_label == ">6" and row["count"] > 0 else ""
        print(
            f"  {str(bin_label):<10} {int(row['count']):>8} {pct:>13.1f}% {clr(float(row['pnl']), '+,.0f'):>23}{flag}"
        )
    print(
        f"\n  Max lot gebruikt: {BOLD}{max_lot_used:.2f}{RESET} lots  "
        f"(cap: {FTMO_MAX_LOT})  "
        f"{'OK Binnen limiet' if lot_cap_ok else f'{RED}FAIL CAP OVERSCHREDEN{RESET}'}"
    )

    # ── DRAWDOWN ANALYSE ─────────────────────────────────────────
    sec("DRAWDOWN ANALYSE")
    print(f"  Piek-naar-trog DD     : {RED}{max_dd_pct:.2f}%{RESET} = EUR {max_dd_eur:,.0f}  (risicobeheer indicator)")
    print(f"  Min equity bereikt    : EUR {min_equity:,.0f}")
    print(f"  FTMO vloer (90%)      : EUR {ftmo_floor:,.0f}")
    ftmo_equity_marge = min_equity - ftmo_floor
    print(
        f"  FTMO equity marge     : {GREEN if ftmo_equity_marge > 0 else RED}EUR {ftmo_equity_marge:,.0f}{RESET}  "
        f"({'boven vloer — VEILIG' if ftmo_equity_marge > 0 else 'ONDER VLOER — FAIL'})"
    )
    print(f"  Max verlies v/a start : EUR {ftmo_abs_loss:,.0f} ({ftmo_abs_loss_pct:.2f}%)")
    print(f"  FTMO Max Loss limiet  : EUR {capital * FTMO_MAX_TOT_PCT:,.0f} (10%)")
    print(
        f"  Worst single day      : EUR {worst_day_loss:+,.0f}  "
        f"({abs(worst_day_loss) / FTMO_MAX_DAG_EUR * 100:.0f}% van daggrens)"
    )

    # Drawdown periodes
    in_dd = False
    dd_periods = []
    dd_start_idx = None
    for idx in range(len(dd_pct_s)):
        v = float(dd_pct_s.iloc[idx])
        if v > 1.0 and not in_dd:
            in_dd = True
            dd_start_idx = idx
        elif v < 0.1 and in_dd:
            dd_periods.append((dd_start_idx, idx, float(dd_pct_s.iloc[dd_start_idx:idx].max())))
            in_dd = False

    if dd_periods:
        worst_dds = sorted(dd_periods, key=lambda x: -x[2])[:5]
        print("\n  Top drawdown periodes:")
        for s, e, peak_dd in worst_dds:
            try:
                t_start = df["in_dt"].iloc[s].strftime("%Y-%m-%d") if s < len(df) else "?"
                t_end = df["in_dt"].iloc[min(e, len(df) - 1)].strftime("%Y-%m-%d")
                print(f"    {t_start} -> {t_end}  max {peak_dd:.2f}%")
            except Exception:
                pass

    # ── EQUITY CURVE ASCII ────────────────────────────────────────
    sec("EQUITY CURVE (6 MAANDEN)")
    equities = [capital] + list(cum_eq)
    mn, mx = min(equities), max(equities)
    span = mx - mn if mx != mn else 1
    step = max(1, len(equities) // 72)
    pts = equities[::step]
    rows_h = 12
    ftmo_floor = capital * (1 - FTMO_MAX_TOT_PCT)

    for r in range(rows_h, -1, -1):
        threshold = mn + span * (r / rows_h)
        is_floor = abs(threshold - ftmo_floor) < span / rows_h
        is_start = abs(threshold - capital) < span / rows_h
        label = f"EUR {threshold:>10,.0f} |"
        if is_floor:
            label = f"{RED}EUR {threshold:>10,.0f} |{RESET}"
            line = "".join("X" if p >= threshold else "·" for p in pts)
            print(f"  {label} {line}  {RED}<-- FTMO floor{RESET}")
        elif is_start:
            label = f"{YELLOW}EUR {threshold:>10,.0f} |{RESET}"
            line = "".join("X" if p >= threshold else "·" for p in pts)
            print(f"  {label} {line}  {YELLOW}<-- Start{RESET}")
        else:
            line = "".join("X" if p >= threshold else "·" for p in pts)
            print(f"  {label} {line}")

    t0 = df["in_dt"].iloc[0].strftime("%Y-%m-%d") if not df.empty else str(start)
    t1 = df["uit_dt"].iloc[-1].strftime("%Y-%m-%d") if not df.empty else str(end)
    print(f"  {'':>16}{'-' * (len(pts) + 2)}")
    print(f"  {'':>17}{t0}{'':>{max(1, len(pts) - 22)}}{t1}")

    # ── SAMENVATTING ─────────────────────────────────────────────
    hdr(f"SAMENVATTING — 6 MAANDEN ({version} SPRINT CONFIG)")
    summary = [
        ("Periode", f"{start} -> {end} ({n_days} dagen)"),
        ("Startkapitaal", f"EUR {capital:,.0f}"),
        ("Eindsaldo", f"{BOLD}EUR {final_cap:,.2f}{RESET}"),
        ("Totale winst", f"{BOLD}{clr(total_pnl, '+,.2f')} EUR{RESET}"),
        ("Totaal rendement", f"{clr(total_pnl / capital * 100, '+.2f')}%"),
        ("Daggemiddelde", f"{clr(daily_avg, '+,.2f')} EUR/dag"),
        ("", ""),
        ("Trades", f"{n_trades} total | {trading_days} handelsdagen"),
        ("Win rate", f"{wr:.1f}%"),
        ("Profit factor", f"{pf:.2f}"),
        ("Sharpe ratio", f"{sharpe:.2f}"),
        ("Calmar ratio", f"{calmar:.2f}"),
        ("", ""),
        ("Piek-naar-trog DD", f"{RED}{max_dd_pct:.2f}%{RESET} = EUR {max_dd_eur:,.0f}"),
        ("FTMO min equity", f"EUR {min_equity:,.0f} (vloer: EUR {ftmo_floor:,.0f})"),
        ("Max lot gebruikt", f"{max_lot_used:.2f} lots (cap: {FTMO_MAX_LOT})"),
        ("Slechtste dag", f"EUR {worst_day_loss:+,.0f} (max: EUR {FTMO_MAX_DAG_EUR:,.0f})"),
        ("", ""),
        ("FTMO Resultaat", ftmo_badge(ftmo_passed)),
    ]
    for label, val in summary:
        if label:
            print(f"  {label:<22} {val}")
        else:
            print()

    # ── CSV OPSLAAN ───────────────────────────────────────────────
    out_dir = Path("results/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"backtest_6m_{start}_{end}.csv"
    df.drop(columns=["in_dt", "uit_dt", "trade_date", "month", "week", "lot_bin"], errors="ignore").to_csv(
        csv_path, index=False
    )
    print(f"\n  Trades opgeslagen: {csv_path}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XAUUSD 6-maanden backtest met FTMO constraints (lot≤6, dag≤€8k)")
    parser.add_argument("--capital", type=float, default=160_000.0, help="Startkapitaal (default: 160000)")
    parser.add_argument(
        "--start", type=str, default="2025-11-17", help="Startdatum (default: 2025-11-17 = 6 maanden geleden)"
    )
    parser.add_argument("--end", type=str, default="2026-05-17", help="Einddatum (default: 2026-05-17 = vandaag)")
    parser.add_argument("--v19", action="store_true", help="Gebruik V19 config i.p.v. V20 (standaard: V20)")
    parser.add_argument("--v18", action="store_true", help="Gebruik V18 config i.p.v. V20 (standaard: V20)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    if args.v18:
        ver = "V18"
    elif args.v19:
        ver = "V19"
    else:
        ver = "V20"

    run_6month_backtest(
        capital=args.capital,
        start=start_date,
        end=end_date,
        version=ver,
    )
