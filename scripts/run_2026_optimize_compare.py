"""
XAUUSD 2026 — Parameter Optimalisatie Vergelijking
====================================================
Vergelijkt 3 scenario's om te zien welke in 2 maanden €16.000 haalt.
Toont weekoverzicht per scenario.

Gebruik:
    python scripts/run_2026_optimize_compare.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService
from core.strategy_engine import DEFAULT_CFG

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def clr(val: float, fmt: str = "+.2f") -> str:
    c = GREEN if val > 0 else (RED if val < 0 else YELLOW)
    return f"{c}{val:{fmt}}{RESET}"


def hdr(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")


def sec(title: str) -> None:
    pad = max(1, 62 - len(title))
    print(f"\n{BOLD}{YELLOW}-- {title} {'-' * pad}{RESET}")


SCENARIOS = {
    "HUIDIG (Standaard)": {
        **DEFAULT_CFG,
        "_label": "conservatief",
        "_color": YELLOW,
    },
    "BALANCED (2x Risk)": {
        **DEFAULT_CFG,
        "risk_a": 0.0080,  # 2x
        "risk_b": 0.0060,  # 2x
        "risk_c": 0.0050,  # 2x
        "cooldown_h": 1,  # 2h -> 1h
        "adx_min": 12,  # 14 -> 12
        "max_dag": 8,  # 6 -> 8
        "_label": "balanced",
        "_color": CYAN,
    },
    "AGRESSIEF (3x Risk)": {
        **DEFAULT_CFG,
        "risk_a": 0.0120,  # 3x
        "risk_b": 0.0090,  # 3x
        "risk_c": 0.0075,  # 3x
        "cooldown_h": 1,  # 1h
        "adx_min": 10,  # 14 -> 10 (meer signalen)
        "max_dag": 10,  # 10/dag
        "sl_dag_max": 3,  # 2 -> 3 SL's per dag
        "tp1_r": 1.5,
        "tp2_r": 3.0,  # 2.5 -> 3.0
        "tp3_r": 5.0,  # 4.0 -> 5.0
        "_label": "agressief",
        "_color": RED,
    },
}

TARGET = 16_000.0
CAPITAL = 160_000.0
START = date(2026, 1, 1)
END = date(2026, 5, 14)


def run_scenario(svc: BacktestService, name: str, params: dict, df_feat: pd.DataFrame) -> dict:
    clean = {k: v for k, v in params.items() if not k.startswith("_")}
    req = BacktestRequest(
        start_date=str(START),
        end_date=str(END),
        starting_capital=CAPITAL,
        strategy_params=clean,
    )
    cfg = svc._build_cfg(req)
    raw_trades, _ = svc._run_backtest_engine(df_feat, cfg, CAPITAL)

    if not raw_trades:
        return {"name": name, "trades": [], "error": "Geen trades"}

    df = pd.DataFrame(raw_trades)
    df["in_dt"] = pd.to_datetime(df["in"], utc=True, errors="coerce")
    df["uit_dt"] = pd.to_datetime(df["uit"], utc=True, errors="coerce")
    df["pnl"] = df["pnl"].astype(float)

    # Alleen 2026 trades
    start_ts = pd.Timestamp(START, tz="UTC")
    df = df[df["in_dt"] >= start_ts].reset_index(drop=True)

    df["cum_pnl"] = df["pnl"].cumsum()

    # Stop bij target
    hit = df[df["cum_pnl"] >= TARGET]
    if not hit.empty:
        stop_i = int(hit.index[0])
        stop_dt = df.iloc[stop_i]["uit_dt"]
        days = (stop_dt - pd.Timestamp(START, tz="UTC")).days + 1
        df_used = df.iloc[: stop_i + 1].copy()
        target_hit = True
    else:
        df_used = df.copy()
        days = (END - START).days
        stop_dt = None
        target_hit = False

    pnl_s = df_used["pnl"]
    wins = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]
    cum_eq = pnl_s.cumsum() + CAPITAL
    peak = cum_eq.cummax()
    dd_pct = (peak - cum_eq) / peak * 100
    max_dd = float(dd_pct.max()) if len(dd_pct) else 0.0
    pf = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0

    weekly = svc._build_weekly_summary(df_used.rename(columns={"in": "in", "uit": "uit"}), CAPITAL)

    return {
        "name": name,
        "params": clean,
        "df": df_used,
        "weekly": weekly,
        "total_pnl": float(pnl_s.sum()),
        "final_cap": CAPITAL + float(pnl_s.sum()),
        "n_trades": len(df_used),
        "win_rate": float((pnl_s > 0).mean()) if not pnl_s.empty else 0.0,
        "profit_factor": pf,
        "max_dd": max_dd,
        "target_hit": target_hit,
        "days_to_target": days if target_hit else None,
        "stop_dt": stop_dt,
        "error": None,
        "color": params["_color"],
    }


def main() -> None:
    hdr(f"XAUUSD 2026 — Welke instelling haalt €{TARGET:,.0f} in 2 maanden?")
    print(f"  Startkapitaal : EUR {CAPITAL:,.0f}")
    print(f"  Periode       : {START} - {END}")
    print(f"  Winstdoel     : +EUR {TARGET:,.0f}  (binnen 2 maanden = voor 2026-03-01)")
    print()

    svc = BacktestService()
    print("  Data laden...")
    df_raw = svc._fetch_data(START, END)
    df_feat = svc._engine.prepare_features(df_raw)
    print(f"  {len(df_feat)} H1 bars geladen. Scenarios draaien...\n")

    results = []
    for name, params in SCENARIOS.items():
        print(f"  Scenario: {params['_color']}{BOLD}{name}{RESET}...")
        try:
            r = run_scenario(svc, name, params, df_feat)
            results.append(r)
        except Exception as e:
            print(f"    {RED}FOUT: {e}{RESET}")

    # ── VERGELIJKINGSTABEL ───────────────────────────────────────
    sec("SCENARIO VERGELIJKING")
    print(
        f"  {'Scenario':<26} {'Trades':>7} {'Winst':>14} "
        f"{'Win%':>6} {'PF':>5} {'Max DD':>7} {'Doel?':>10} {'Wanneer':>16}"
    )
    print(f"  {'-' * 26} {'-' * 7} {'-' * 14} {'-' * 6} {'-' * 5} {'-' * 7} {'-' * 10} {'-' * 16}")

    for r in results:
        if r["error"]:
            print(f"  {r['name']:<26} FOUT: {r['error']}")
            continue
        hit_str = f"{GREEN}JA{RESET}" if r["target_hit"] else f"{RED}NEE{RESET}"
        when_str = r["stop_dt"].strftime("%d %b %Y") if r["stop_dt"] else f"{RED}> {END}{RESET}"
        days_str = f"({r['days_to_target']} dgn)" if r["days_to_target"] else ""
        print(
            f"  {r['color']}{BOLD}{r['name']:<26}{RESET} "
            f"{r['n_trades']:>7} "
            f"{clr(r['total_pnl'], '+,.0f'):>23} "
            f"{r['win_rate'] * 100:>5.1f}% "
            f"{r['profit_factor']:>5.2f} "
            f"{RED if r['max_dd'] > 5 else YELLOW}{r['max_dd']:>6.1f}%{RESET} "
            f"{hit_str:>19}  "
            f"{when_str} {days_str}"
        )

    # ── PARAMETERS TABEL ─────────────────────────────────────────
    sec("PARAMETER WIJZIGINGEN")
    print(f"  {'Parameter':<20} {'Huidig':>10} {'Balanced':>12} {'Agressief':>12}  Uitleg")
    print(f"  {'-' * 20} {'-' * 10} {'-' * 12} {'-' * 12}  {'-' * 30}")
    param_rows = [
        ("risk_a", "0.40%", "0.80%", "1.20%", "Risk voor A-signalen (EMA Cross)"),
        ("risk_b", "0.30%", "0.60%", "0.90%", "Risk voor B/C/E-signalen"),
        ("risk_c", "0.25%", "0.50%", "0.75%", "Risk voor D/F-signalen"),
        ("cooldown_h", "2 uur", "1 uur", "1 uur", "Wachttijd tussen trades"),
        ("adx_min", "14", "12", "10", "Min. trendsterkte (lager=meer trades)"),
        ("max_dag", "6", "8", "10", "Max trades per dag"),
        ("tp2_r", "2.5x", "2.5x", "3.0x", "TP2 reward ratio"),
        ("tp3_r", "4.0x", "4.0x", "5.0x", "TP3 reward ratio (runners)"),
    ]
    for row in param_rows:
        print(f"  {row[0]:<20} {row[1]:>10} {CYAN}{row[2]:>12}{RESET} {RED}{row[3]:>12}{RESET}  {row[4]}")

    # ── WEEKOVERZICHT PER SCENARIO ───────────────────────────────
    for r in results:
        if r["error"] or not r["weekly"]:
            continue
        sec(f"WEEKOVERZICHT — {r['name']}")
        print(
            f"  {'Week':<10} {'Start':>13} {'Eind':>13} {'Trades':>7} {'P&L':>14} {'Win%':>6} {'Cum.winst':>12}  Status"
        )
        print(f"  {'-' * 10} {'-' * 13} {'-' * 13} {'-' * 7} {'-' * 14} {'-' * 6} {'-' * 12}  {'-' * 10}")

        cum = 0.0
        for w in r["weekly"]:
            cum += float(w.pnl)
            hit_mark = (
                f"  {GREEN}<-- DOEL!{RESET}" if cum >= TARGET and r["target_hit"] and w == r["weekly"][-1] else ""
            )
            target_bar = f"{GREEN}" if cum >= TARGET else ""
            target_end = RESET if cum >= TARGET else ""
            print(
                f"  {str(w.week):<10} "
                f"EUR {float(w.start_equity):>9,.0f} "
                f"EUR {float(w.end_equity):>9,.0f} "
                f"{int(w.trades):>7} "
                f"{clr(float(w.pnl), '+,.0f'):>23} "
                f"{float(w.win_rate) * 100:>5.1f}% "
                f"{target_bar}{clr(cum, '+,.0f'):>21}{target_end}"
                f"{hit_mark}"
            )

    # ── AANBEVELING ─────────────────────────────────────────────
    hdr("AANBEVELING")
    hit_results = [r for r in results if r.get("target_hit") and not r.get("error")]
    if hit_results:
        best = min(hit_results, key=lambda x: x["days_to_target"] or 9999)
        print(f"  Aanbevolen scenario : {best['color']}{BOLD}{best['name']}{RESET}")
        print(f"  Doel bereikt op     : {BOLD}{best['stop_dt'].strftime('%d %B %Y')}{RESET}")
        print(f"  Dagen nodig         : {BOLD}{best['days_to_target']}{RESET}")
        print(f"  Max drawdown        : {RED if best['max_dd'] > 5 else YELLOW}{best['max_dd']:.1f}%{RESET}")
        print()
        print(f"  {BOLD}Gebruik deze strategy_params in de backtest:{RESET}")
        clean = {k: v for k, v in best["params"].items() if not k.startswith("_")}
        for k, v in clean.items():
            orig = DEFAULT_CFG.get(k)
            changed = orig is not None and orig != v
            marker = f" {GREEN}<-- GEWIJZIGD (was {orig}){RESET}" if changed else ""
            print(f"    {k:<16}: {v}{marker}")
    else:
        print(f"  {RED}Geen scenario haalt €{TARGET:,.0f} binnen de testperiode.{RESET}")
        best = max([r for r in results if not r.get("error")], key=lambda x: x["total_pnl"])
        print(f"  Beste resultaat: {best['name']} met {clr(best['total_pnl'], '+,.0f')} EUR")
        print()
        print(f"  {YELLOW}Tip: Verhoog risk_a/b/c verder of verleng de periode naar 3 maanden.{RESET}")

    print()


if __name__ == "__main__":
    main()
