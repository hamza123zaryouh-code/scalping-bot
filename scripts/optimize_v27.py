"""
V27 Optimalisatie — Zoek naar 8k+/maand configuratie
=====================================================
Laadt data éénmalig, test tientallen configuraties systematisch.
Sorteert op totale P&L. Toont top-10.

Gebruik:
    python scripts/optimize_v27.py
    python scripts/optimize_v27.py --start 2025-11-17 --end 2026-05-17
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

CAPITAL       = 160_000.0
FTMO_DAG_EUR  = 6_000.0
FTMO_TOT_PCT  = 0.10
FTMO_FLOOR    = CAPITAL * (1 - FTMO_TOT_PCT)   # 144,000
MAX_LOT       = 6.0

BASE = {
    **V26_CFG,
    "max_lot_size": MAX_LOT,
    "max_daily_loss_eur": FTMO_DAG_EUR,
}


def build_configs() -> list[tuple[str, dict]]:
    """Bouw alle te testen configuraties."""
    cfgs: list[tuple[str, dict]] = []

    # ── 1. Baseline V26 ─────────────────────────────────────────────
    cfgs.append(("V26_baseline", dict(BASE)))

    # ── 2. C_MOMENTUM: BULL toelaten met strengere ADX ──────────────
    for adx in [21, 22, 23, 24, 25, 26]:
        c = {**BASE, "c_momentum_allow_bull": True, "c_momentum_min_adx": adx}
        cfgs.append((f"CMOM_BULL_adx{adx}", c))

    # ── 3. B_MACDCROSS terug — alleen STERK_BULL, hoge ADX ──────────
    for b_adx in [20, 22, 24, 26]:
        c = {
            **BASE,
            "disabled_signals": ["A_EMACROSS", "D_PULLBACK", "E_BOS", "F_MSS"],
            "b_macd_require_strong": True,
            "b_macd_min_adx": b_adx,
        }
        cfgs.append((f"B_MACD_adx{b_adx}", c))

    # ── 4. C_MOMENTUM BULL + B_MACDCROSS STERK ──────────────────────
    for c_adx in [22, 24]:
        for b_adx in [22, 24]:
            c = {
                **BASE,
                "disabled_signals": ["A_EMACROSS", "D_PULLBACK", "E_BOS", "F_MSS"],
                "c_momentum_allow_bull": True,
                "c_momentum_min_adx": c_adx,
                "b_macd_require_strong": True,
                "b_macd_min_adx": b_adx,
            }
            cfgs.append((f"CMOM{c_adx}+BMACD{b_adx}", c))

    # ── 5. D_PULLBACK terug — strikte filters, STERK_BULL only ──────
    for p_adx in [20, 22, 24]:
        c = {
            **BASE,
            "disabled_signals": ["A_EMACROSS", "B_MACDCROSS", "E_BOS", "F_MSS"],
            "pullback_min_adx": p_adx,
            "pullback_min_h4_slope": 0.30,
        }
        cfgs.append((f"D_PULL_adx{p_adx}", c))

    # ── 6. Risico verhogen (C_MOMENTUM only) ────────────────────────
    for risk in [0.020, 0.022, 0.025]:
        c = {**BASE, "risk_b": risk}
        cfgs.append((f"RISK_{int(risk * 1000)}bps", c))

    # ── 7. C_MOMENTUM BULL + hoger risico ───────────────────────────
    for c_adx in [22, 24]:
        for risk in [0.020, 0.022, 0.025]:
            c = {
                **BASE,
                "c_momentum_allow_bull": True,
                "c_momentum_min_adx": c_adx,
                "risk_b": risk,
            }
            cfgs.append((f"BULL{c_adx}_R{int(risk * 1000)}", c))

    # ── 8. TP structuur variaties (C_MOMENTUM only) ─────────────────
    for tp1p in [0.35, 0.40, 0.50]:
        for tp3r in [4.0, 6.0, 7.0]:
            c = {**BASE, "tp1_pct": tp1p, "tp3_r": tp3r}
            cfgs.append((f"TP1p{int(tp1p*100)}_TP3r{int(tp3r)}", c))

    # ── 9. C_MOMENTUM BULL + hoger risico + betere TP ───────────────
    for c_adx in [22, 24]:
        for risk in [0.020, 0.022]:
            for tp3r in [5.0, 6.0]:
                c = {
                    **BASE,
                    "c_momentum_allow_bull": True,
                    "c_momentum_min_adx": c_adx,
                    "risk_b": risk,
                    "tp3_r": tp3r,
                }
                cfgs.append((f"FULL_BULL{c_adx}_R{int(risk*1000)}_TP3_{int(tp3r)}", c))

    # ── 10. B_MACD + BULL + verhoogd risico ─────────────────────────
    for b_adx in [22, 24]:
        for c_adx in [22, 24]:
            for risk in [0.020, 0.022]:
                c = {
                    **BASE,
                    "disabled_signals": ["A_EMACROSS", "D_PULLBACK", "E_BOS", "F_MSS"],
                    "c_momentum_allow_bull": True,
                    "c_momentum_min_adx": c_adx,
                    "b_macd_require_strong": True,
                    "b_macd_min_adx": b_adx,
                    "risk_b": risk,
                }
                cfgs.append((f"B{b_adx}+C{c_adx}_R{int(risk*1000)}", c))

    return cfgs


def run_cfg(svc: BacktestService, df_feat: pd.DataFrame, cfg: dict) -> dict | None:
    """Voer één backtest uit en retourneer metrics dict."""
    try:
        trades_raw, final_cap = svc._run_backtest_engine(df_feat, cfg, CAPITAL)
    except Exception as exc:
        return {"error": str(exc)}

    if not trades_raw:
        return None

    df = pd.DataFrame(trades_raw)
    df["in_dt"] = pd.to_datetime(df["in"], utc=True, errors="coerce")
    df["pnl"] = df["pnl"].astype(float)
    df["lot_size"] = df.get("lot_size", pd.Series([0.01] * len(df))).astype(float)
    df["sig_type"] = df.get("type", pd.Series(["?"] * len(df)))

    start_ts = df["in_dt"].min()
    if pd.isna(start_ts):
        return None

    pnl_s = df["pnl"]
    wins   = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]

    total_pnl = float(pnl_s.sum())
    n_trades  = len(df)
    wr        = float((pnl_s > 0).mean()) * 100 if n_trades > 0 else 0.0
    pf        = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    avg_win   = float(wins.mean())  if not wins.empty   else 0.0
    avg_loss  = float(losses.mean()) if not losses.empty else 0.0
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
    daily_pnl      = df.groupby("trade_date")["pnl"].sum()
    worst_day      = float(daily_pnl.min())
    daily_ok       = abs(worst_day) <= FTMO_DAG_EUR + 1

    ftmo_ok = ftmo_dd_ok and lot_ok and daily_ok

    # Max drawdown (piek-naar-trog)
    peak       = cum_eq.cummax()
    dd_abs     = peak - cum_eq
    max_dd_pct = float((dd_abs / peak * 100).max())

    # Sharpe
    ret_per_trade = pnl_s / CAPITAL
    sharpe = 0.0
    if len(ret_per_trade) > 1 and float(ret_per_trade.std(ddof=0)) > 0:
        sharpe = float(ret_per_trade.mean() / ret_per_trade.std(ddof=0) * np.sqrt(252))

    # Maandelijkse verdeling
    df["month"] = df["in_dt"].dt.to_period("M").astype(str)
    monthly_pnl  = df.groupby("month")["pnl"].sum()
    months_profit = int((monthly_pnl > 0).sum())
    months_total  = len(monthly_pnl)
    avg_monthly   = float(total_pnl / max(months_total, 1))
    min_monthly   = float(monthly_pnl.min()) if not monthly_pnl.empty else 0.0

    # Trades per maand
    monthly_trades = df.groupby("month")["pnl"].count()
    avg_trades_pm  = float(monthly_trades.mean()) if not monthly_trades.empty else 0.0

    # Signaalverdeling
    sig_breakdown = {}
    for st in df["sig_type"].unique():
        sub = df[df["sig_type"] == st]
        sig_breakdown[st] = {
            "n": len(sub),
            "wr": float((sub["pnl"] > 0).mean() * 100),
            "total": float(sub["pnl"].sum()),
            "avg": float(sub["pnl"].mean()),
        }

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
        "months_profit": months_profit,
        "months_total": months_total,
        "ftmo_ok": ftmo_ok,
        "sig_breakdown": sig_breakdown,
    }


def main(start: date, end: date) -> None:
    svc = BacktestService()

    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}  V27 OPTIMALISATIE — {start} t/m {end}{RESET}")
    print(f"{BOLD}{CYAN}  Doel: 8.000+ EUR/maand | FTMO-veilig | Max DD < 8%{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

    print("  Data laden (éénmalig)...")
    try:
        df_raw  = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as exc:
        print(f"{RED}Data laden mislukt: {exc}{RESET}")
        sys.exit(1)

    start_ts  = pd.Timestamp(start, tz="UTC")
    df_feat   = df_feat[df_feat.index >= start_ts]
    print(f"  {len(df_raw)} H1 bars geladen | {len(df_feat)} bars in periode\n")

    configs = build_configs()
    print(f"  {len(configs)} configuraties te testen...\n")

    results: list[tuple[str, dict]] = []

    for i, (name, cfg) in enumerate(configs, 1):
        metrics = run_cfg(svc, df_feat, cfg)
        if metrics is None or "error" in metrics:
            err = metrics.get("error", "geen trades") if metrics else "geen trades"
            print(f"  [{i:>3}/{len(configs)}] {name:<35} SKIP ({err[:40]})")
            continue

        ftmo_flag = f"{GREEN}FTMO-OK{RESET}" if metrics["ftmo_ok"] else f"{RED}FTMO-FAIL{RESET}"
        monthly_clr = GREEN if metrics["avg_monthly"] >= 8000 else (YELLOW if metrics["avg_monthly"] >= 4000 else RED)

        print(
            f"  [{i:>3}/{len(configs)}] {name:<35} "
            f"Totaal: {GREEN if metrics['total_pnl'] > 0 else RED}{metrics['total_pnl']:>+10,.0f}{RESET} EUR  "
            f"~{monthly_clr}{metrics['avg_monthly']:>+7,.0f}{RESET}/mnd  "
            f"T:{metrics['n_trades']:>3}  WR:{metrics['wr']:>5.1f}%  "
            f"PF:{metrics['pf']:>5.2f}  DD:{metrics['max_dd_pct']:>5.2f}%  "
            f"{ftmo_flag}"
        )

        results.append((name, metrics))

    # ── TOP 10 SORTEREN ──────────────────────────────────────────────
    results.sort(key=lambda x: x[1]["total_pnl"], reverse=True)

    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}  TOP 10 CONFIGURATIES (gesorteerd op totale P&L){RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

    print(f"  {'#':<3} {'Naam':<35} {'P&L totaal':>12} {'€/maand':>10} {'Trades':>7} "
          f"{'T/mnd':>6} {'WR%':>6} {'PF':>6} {'DD%':>6} {'FTMO':>10}")
    print(f"  {'-'*3} {'-'*35} {'-'*12} {'-'*10} {'-'*7} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*10}")

    top10 = results[:10]
    for rank, (name, m) in enumerate(top10, 1):
        ftmo_flag = f"{GREEN}OK{RESET}" if m["ftmo_ok"] else f"{RED}FAIL{RESET}"
        monthly_clr = GREEN if m["avg_monthly"] >= 8000 else (YELLOW if m["avg_monthly"] >= 4000 else RED)
        pnl_clr = GREEN if m["total_pnl"] > 0 else RED
        print(
            f"  {rank:<3} {name:<35} "
            f"{pnl_clr}{m['total_pnl']:>+12,.0f}{RESET} "
            f"{monthly_clr}{m['avg_monthly']:>+10,.0f}{RESET} "
            f"{m['n_trades']:>7} "
            f"{m['avg_trades_pm']:>6.1f} "
            f"{m['wr']:>5.1f}% "
            f"{m['pf']:>6.2f} "
            f"{m['max_dd_pct']:>5.2f}% "
            f"{ftmo_flag}"
        )

    # ── BESTE CONFIGURATIE DETAIL ────────────────────────────────────
    if top10:
        best_name, best = top10[0]
        print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
        print(f"{BOLD}{CYAN}  BESTE CONFIGURATIE: {best_name}{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

        lines = [
            ("Totale P&L",       f"EUR {best['total_pnl']:+,.0f}"),
            ("Gem. per maand",   f"EUR {best['avg_monthly']:+,.0f}"),
            ("Min. maand",       f"EUR {best['min_monthly']:+,.0f}"),
            ("Winstgevende mnd", f"{best['months_profit']}/{best['months_total']}"),
            ("",                 ""),
            ("Totaal trades",    f"{best['n_trades']} ({best['avg_trades_pm']:.1f}/mnd)"),
            ("Win rate",         f"{best['wr']:.1f}%"),
            ("Profit factor",    f"{best['pf']:.2f}"),
            ("Gem. winst",       f"EUR {best['avg_win']:+,.0f}"),
            ("Gem. verlies",     f"EUR {best['avg_loss']:+,.0f}"),
            ("Expectancy",       f"EUR {best['expectancy']:+,.0f}/trade"),
            ("Sharpe ratio",     f"{best['sharpe']:.2f}"),
            ("",                 ""),
            ("Max drawdown",     f"{best['max_dd_pct']:.2f}%"),
            ("Min equity",       f"EUR {best['min_equity']:,.0f} (vloer: EUR {FTMO_FLOOR:,.0f})"),
            ("Slechtste dag",    f"EUR {best['worst_day']:+,.0f}"),
            ("FTMO",             "GESLAAGD" if best["ftmo_ok"] else "GEZAKT"),
        ]
        for lbl, val in lines:
            if lbl:
                print(f"    {lbl:<22} {val}")
            else:
                print()

        if best.get("sig_breakdown"):
            print(f"\n  {'Signaal':<16} {'Trades':>7} {'WR%':>6} {'Totaal':>12} {'Gem/trade':>12}")
            print(f"  {'-'*16} {'-'*7} {'-'*6} {'-'*12} {'-'*12}")
            for sig, sb in sorted(best["sig_breakdown"].items(), key=lambda x: -x[1]["total"]):
                pnl_clr = GREEN if sb["total"] > 0 else RED
                print(
                    f"  {sig:<16} {sb['n']:>7} {sb['wr']:>5.1f}% "
                    f"{pnl_clr}{sb['total']:>+12,.0f}{RESET} "
                    f"{pnl_clr}{sb['avg']:>+12,.0f}{RESET}"
                )

    # ── FTMO-veilige configs met 8k+/mnd ────────────────────────────
    elite = [(n, m) for n, m in results if m["ftmo_ok"] and m["avg_monthly"] >= 8000]
    if elite:
        print(f"\n{BOLD}{GREEN}{'=' * 80}{RESET}")
        print(f"{BOLD}{GREEN}  CONFIGURATIES MET 8.000+/MAAND EN FTMO-VEILIG ({len(elite)} gevonden){RESET}")
        print(f"{BOLD}{GREEN}{'=' * 80}{RESET}\n")
        for name, m in elite:
            print(
                f"  {name:<35}  "
                f"EUR {m['total_pnl']:>+10,.0f}  "
                f"~{m['avg_monthly']:>+8,.0f}/mnd  "
                f"{m['n_trades']} trades  "
                f"WR {m['wr']:.1f}%  "
                f"DD {m['max_dd_pct']:.2f}%"
            )
    else:
        print(f"\n{YELLOW}Geen FTMO-veilige config gevonden met 8.000+/maand.{RESET}")
        # Toon beste FTMO-veilige config
        ftmo_safe = [(n, m) for n, m in results if m["ftmo_ok"]]
        if ftmo_safe:
            best_safe_name, best_safe = ftmo_safe[0]
            print(f"{YELLOW}Beste FTMO-veilige config: {best_safe_name} -> "
                  f"EUR {best_safe['avg_monthly']:+,.0f}/maand{RESET}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V27 Optimalisatie — zoek naar 8k+/maand config")
    parser.add_argument("--start", default="2025-11-17")
    parser.add_argument("--end",   default="2026-05-17")
    args = parser.parse_args()
    main(date.fromisoformat(args.start), date.fromisoformat(args.end))
