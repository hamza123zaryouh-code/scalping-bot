"""
V27b Optimalisatie — Alles-in-TP3 aanpak voor 8k+/maand
=========================================================
Geen partiële sluitingen — volledige positie naar hoog TP-doel.
Logica: breakeven bij 1.5R, daarna trailing, volledig sluiten bij 6-12R.

Gebruik:
    python scripts/optimize_v27b.py
"""
from __future__ import annotations

import sys
import argparse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from backend.services.backtest_service import BacktestService
from core.strategy_engine import V26_CFG

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

CAPITAL      = 160_000.0
FTMO_DAG_EUR = 6_000.0
FTMO_TOT_PCT = 0.10
FTMO_FLOOR   = CAPITAL * (1 - FTMO_TOT_PCT)
MAX_LOT      = 6.0

BASE = {
    **V26_CFG,
    "max_lot_size": MAX_LOT,
    "max_daily_loss_eur": FTMO_DAG_EUR,
}


def build_configs() -> list[tuple[str, dict]]:
    cfgs: list[tuple[str, dict]] = []

    # ── A. Referentie: V26 standaard (partiële sluitingen) ──────────
    cfgs.append(("V26_ref_partieel", dict(BASE)))

    # ── B. Alles naar TP3 — C_MOMENTUM STERK_BULL ──────────────────
    for tp3r in [5.0, 6.0, 7.0, 8.0, 10.0, 12.0]:
        for risk in [0.018, 0.020, 0.022, 0.025]:
            c = {
                **BASE,
                "tp1_pct": 0.0,
                "tp2_pct": 0.0,
                "tp3_r":   tp3r,
                "risk_b":  risk,
                "breakeven_r": 1.5,
            }
            cfgs.append((f"ALLIN_TP{int(tp3r)}R_R{int(risk*1000)}", c))

    # ── C. Klein TP1 (10%), rest naar hoog TP3 ──────────────────────
    for tp3r in [6.0, 8.0, 10.0]:
        for risk in [0.018, 0.022, 0.025]:
            c = {
                **BASE,
                "tp1_pct": 0.10,
                "tp2_pct": 0.0,
                "tp3_r":   tp3r,
                "risk_b":  risk,
                "breakeven_r": 1.5,
            }
            cfgs.append((f"TP1_10p_TP3_{int(tp3r)}R_R{int(risk*1000)}", c))

    # ── D. Alles naar TP3 + BULL regime ─────────────────────────────
    for c_adx in [21, 22, 23, 24]:
        for tp3r in [6.0, 8.0]:
            for risk in [0.018, 0.020, 0.022]:
                c = {
                    **BASE,
                    "c_momentum_allow_bull": True,
                    "c_momentum_min_adx": c_adx,
                    "tp1_pct": 0.0,
                    "tp2_pct": 0.0,
                    "tp3_r":   tp3r,
                    "risk_b":  risk,
                    "breakeven_r": 1.5,
                }
                cfgs.append((f"BULL{c_adx}_TP3_{int(tp3r)}R_R{int(risk*1000)}", c))

    # ── E. Alles naar TP3 + ruimere SL (sl_atr=2.0) ─────────────────
    for tp3r in [6.0, 8.0]:
        for risk in [0.018, 0.022]:
            c = {
                **BASE,
                "sl_atr":  2.0,
                "tp1_pct": 0.0,
                "tp2_pct": 0.0,
                "tp3_r":   tp3r,
                "risk_b":  risk,
                "breakeven_r": 1.5,
            }
            cfgs.append((f"SLWIDE_TP3_{int(tp3r)}R_R{int(risk*1000)}", c))

    # ── F. Alles naar TP3 + hoog risico + BULL ───────────────────────
    for tp3r in [8.0, 10.0]:
        for risk in [0.025, 0.030]:
            c = {
                **BASE,
                "c_momentum_allow_bull": True,
                "c_momentum_min_adx": 22,
                "tp1_pct": 0.0,
                "tp2_pct": 0.0,
                "tp3_r":   tp3r,
                "risk_b":  risk,
                "breakeven_r": 1.5,
            }
            cfgs.append((f"BULL22_TP3_{int(tp3r)}R_R{int(risk*1000)}", c))

    return cfgs


def run_cfg(svc: BacktestService, df_feat: pd.DataFrame, cfg: dict) -> dict | None:
    try:
        trades_raw, _ = svc._run_backtest_engine(df_feat, cfg, CAPITAL)
    except Exception as exc:
        return {"error": str(exc)}

    if not trades_raw:
        return None

    df = pd.DataFrame(trades_raw)
    df["in_dt"]   = pd.to_datetime(df["in"], utc=True, errors="coerce")
    df["pnl"]     = df["pnl"].astype(float)
    df["lot_size"] = df.get("lot_size", pd.Series([0.01] * len(df))).astype(float)

    pnl_s  = df["pnl"]
    wins   = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]

    total_pnl  = float(pnl_s.sum())
    n_trades   = len(df)
    wr         = float((pnl_s > 0).mean()) * 100 if n_trades > 0 else 0.0
    pf         = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    avg_win    = float(wins.mean())  if not wins.empty  else 0.0
    avg_loss   = float(losses.mean()) if not losses.empty else 0.0
    expectancy = float(pnl_s.mean()) if n_trades > 0 else 0.0

    if "cum_equity" in df.columns and df["cum_equity"].notna().any():
        cum_eq = df["cum_equity"].astype(float)
    else:
        cum_eq = pnl_s.cumsum() + CAPITAL

    min_equity   = float(cum_eq.min())
    ftmo_dd_ok   = min_equity >= FTMO_FLOOR
    max_lot_used = float(df["lot_size"].max())
    lot_ok       = max_lot_used <= MAX_LOT + 0.01

    df["trade_date"] = df["in_dt"].dt.date
    daily_pnl = df.groupby("trade_date")["pnl"].sum()
    worst_day = float(daily_pnl.min())
    daily_ok  = abs(worst_day) <= FTMO_DAG_EUR + 1

    ftmo_ok   = ftmo_dd_ok and lot_ok and daily_ok

    peak       = cum_eq.cummax()
    max_dd_pct = float(((peak - cum_eq) / peak * 100).max())

    ret_per_trade = pnl_s / CAPITAL
    sharpe = 0.0
    if len(ret_per_trade) > 1 and float(ret_per_trade.std(ddof=0)) > 0:
        sharpe = float(ret_per_trade.mean() / ret_per_trade.std(ddof=0) * np.sqrt(252))

    df["month_str"] = df["in_dt"].dt.tz_localize(None).dt.to_period("M").astype(str)
    monthly_pnl     = df.groupby("month_str")["pnl"].sum()
    months_total    = len(monthly_pnl)
    avg_monthly     = float(total_pnl / max(months_total, 1))
    min_monthly     = float(monthly_pnl.min()) if not monthly_pnl.empty else 0.0
    months_8k       = int((monthly_pnl >= 8000).sum())

    monthly_trades  = df.groupby("month_str")["pnl"].count()
    avg_trades_pm   = float(monthly_trades.mean()) if not monthly_trades.empty else 0.0

    # Resultaat per sluitmethode (TP1/TP2/TP3/SL)
    result_col = df.get("result", pd.Series(["?"] * len(df)))
    result_dist = {}
    if "result" in df.columns:
        for res in ["TP1", "TP2", "TP3", "SL", "BE", "RESET", "FTMO"]:
            sub = df[df["result"] == res]
            if not sub.empty:
                result_dist[res] = {"n": len(sub), "total": float(sub["pnl"].sum()), "avg": float(sub["pnl"].mean())}

    return {
        "total_pnl": total_pnl,
        "n_trades": n_trades,
        "avg_trades_pm": avg_trades_pm,
        "wr": wr,
        "pf": pf,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "sharpe": sharpe,
        "max_dd_pct": max_dd_pct,
        "min_equity": min_equity,
        "worst_day": worst_day,
        "avg_monthly": avg_monthly,
        "min_monthly": min_monthly,
        "months_total": months_total,
        "months_8k": months_8k,
        "ftmo_ok": ftmo_ok,
        "result_dist": result_dist,
    }


def main(start: date, end: date) -> None:
    svc = BacktestService()

    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}  V27b OPTIMALISATIE — ALLES-IN-TP3 AANPAK{RESET}")
    print(f"{BOLD}{CYAN}  {start} t/m {end} | Doel: 8.000+ EUR/maand FTMO-veilig{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

    print("  Data laden...")
    try:
        df_raw  = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as exc:
        print(f"{RED}Fout: {exc}{RESET}")
        sys.exit(1)

    print(f"  {len(df_raw)} H1 bars geladen\n")

    configs = build_configs()
    print(f"  {len(configs)} configuraties te testen...\n")

    results: list[tuple[str, dict]] = []

    for i, (name, cfg) in enumerate(configs, 1):
        m = run_cfg(svc, df_feat, cfg)
        if m is None or "error" in m:
            err = m.get("error", "geen trades")[:35] if m else "geen trades"
            print(f"  [{i:>3}/{len(configs)}] {name:<40} SKIP ({err})")
            continue

        ftmo_clr = GREEN if m["ftmo_ok"] else RED
        ftmo_lbl = "OK" if m["ftmo_ok"] else "FAIL"
        mnd_clr  = GREEN if m["avg_monthly"] >= 8000 else (YELLOW if m["avg_monthly"] >= 4000 else RED)

        print(
            f"  [{i:>3}/{len(configs)}] {name:<40} "
            f"Totaal: {GREEN if m['total_pnl']>0 else RED}{m['total_pnl']:>+10,.0f}{RESET}  "
            f"~{mnd_clr}{m['avg_monthly']:>+7,.0f}{RESET}/mnd  "
            f"T:{m['n_trades']:>3}  WR:{m['wr']:>5.1f}%  "
            f"DD:{m['max_dd_pct']:>5.2f}%  "
            f"[{ftmo_clr}{ftmo_lbl}{RESET}]"
        )
        results.append((name, m))

    results.sort(key=lambda x: x[1]["total_pnl"], reverse=True)

    # ── TOP 15 ─────────────────────────────────────────────────────
    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}  TOP 15 — gesorteerd op P&L totaal{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")
    print(f"  {'#':<3} {'Naam':<40} {'P&L totaal':>12} {'€/mnd':>9} {'T':>4} {'T/mnd':>6} "
          f"{'WR%':>6} {'PF':>6} {'DD%':>6} {'8k-mnd':>6} {'FTMO':>6}")
    print(f"  {'-'*3} {'-'*40} {'-'*12} {'-'*9} {'-'*4} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")

    for rank, (name, m) in enumerate(results[:15], 1):
        ftmo_lbl = f"{GREEN}OK{RESET}" if m["ftmo_ok"] else f"{RED}FAIL{RESET}"
        mnd_clr  = GREEN if m["avg_monthly"] >= 8000 else (YELLOW if m["avg_monthly"] >= 4000 else RED)
        pnl_clr  = GREEN if m["total_pnl"] > 0 else RED
        print(
            f"  {rank:<3} {name:<40} "
            f"{pnl_clr}{m['total_pnl']:>+12,.0f}{RESET} "
            f"{mnd_clr}{m['avg_monthly']:>+9,.0f}{RESET} "
            f"{m['n_trades']:>4} "
            f"{m['avg_trades_pm']:>6.1f} "
            f"{m['wr']:>5.1f}% "
            f"{m['pf']:>6.2f} "
            f"{m['max_dd_pct']:>5.2f}% "
            f"{m['months_8k']:>6} "
            f"{ftmo_lbl}"
        )

    # ── FTMO-veilige 8k+ configs ────────────────────────────────────
    elite = [(n, m) for n, m in results if m["ftmo_ok"] and m["avg_monthly"] >= 8000]
    if elite:
        print(f"\n{BOLD}{GREEN}{'=' * 80}{RESET}")
        print(f"{BOLD}{GREEN}  {len(elite)} CONFIG(S) MET 8.000+/MAAND EN FTMO-VEILIG{RESET}")
        print(f"{BOLD}{GREEN}{'=' * 80}{RESET}")
        for name, m in elite:
            print(f"\n  {BOLD}{name}{RESET}")
            print(f"    P&L totaal   : EUR {m['total_pnl']:+,.0f}")
            print(f"    Per maand    : EUR {m['avg_monthly']:+,.0f}")
            print(f"    Min maand    : EUR {m['min_monthly']:+,.0f}")
            print(f"    Mnd met 8k+ : {m['months_8k']}/{m['months_total']}")
            print(f"    Trades       : {m['n_trades']} ({m['avg_trades_pm']:.1f}/mnd)")
            print(f"    Win rate     : {m['wr']:.1f}%  |  PF: {m['pf']:.2f}")
            print(f"    Sharpe       : {m['sharpe']:.2f}")
            print(f"    Max DD       : {m['max_dd_pct']:.2f}%")
            print(f"    Slechtste dag: EUR {m['worst_day']:+,.0f}")
            if m.get("result_dist"):
                print(f"    Sluitingen:")
                for res, rd in m["result_dist"].items():
                    print(f"      {res:<6}: {rd['n']:>3} trades  totaal {rd['total']:>+10,.0f}  gem {rd['avg']:>+8,.0f}")
    else:
        print(f"\n{YELLOW}Geen FTMO-veilige config met 8.000+/maand gevonden.{RESET}")

        # Beste FTMO-veilige config tonen
        safe = [(n, m) for n, m in results if m["ftmo_ok"]]
        if safe:
            best_name, best = safe[0]
            print(f"\n{YELLOW}Beste FTMO-veilige config: {best_name}{RESET}")
            print(f"  P&L totaal   : EUR {best['total_pnl']:+,.0f}")
            print(f"  Per maand    : EUR {best['avg_monthly']:+,.0f}")
            print(f"  Min maand    : EUR {best['min_monthly']:+,.0f}")
            print(f"  Trades       : {best['n_trades']} ({best['avg_trades_pm']:.1f}/mnd)")
            print(f"  Win rate     : {best['wr']:.1f}%  |  PF: {best['pf']:.2f}")
            print(f"  Sharpe       : {best['sharpe']:.2f}")
            print(f"  Max DD       : {best['max_dd_pct']:.2f}%")
            if best.get("result_dist"):
                print(f"  Sluitingen:")
                for res, rd in best["result_dist"].items():
                    print(f"    {res:<6}: {rd['n']:>3}  totaal EUR {rd['total']:>+9,.0f}  gem EUR {rd['avg']:>+8,.0f}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-17")
    parser.add_argument("--end",   default="2026-05-17")
    args = parser.parse_args()
    main(date.fromisoformat(args.start), date.fromisoformat(args.end))
