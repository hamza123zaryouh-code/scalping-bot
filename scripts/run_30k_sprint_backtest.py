"""
XAUUSD V18 Sprint Backtest — €30.000 in 60 dagen
=================================================
Test de V18 "30K Sprint" configuratie.

Verbeteringen t.o.v. V17:
  - risk_a: 1.2% → 2.0% (+67%) | KZ: tot 3.0%
  - risk_b: 0.9% → 1.5%
  - risk_c: 0.75% → 1.2%
  - TP3: 5.0R → 6.5R (grotere runners)
  - Cooldown: 1h → 0.5h (meer entries)
  - Kill zone boost: +25% → +50%
  - Weekly compound: +10% budget na winstgevende week (max +50%)

Gebruik:
    python scripts/run_30k_sprint_backtest.py
    python scripts/run_30k_sprint_backtest.py --capital 160000 --target 30000 --days 60
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService
from core.strategy_engine import DEFAULT_CFG, V18_CFG

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

SIG_TYPES = ["A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"]


def clr(val: float, fmt: str = "+.2f") -> str:
    c = GREEN if val > 0 else (RED if val < 0 else YELLOW)
    return f"{c}{val:{fmt}}{RESET}"


def hdr(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 76}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}")


def sec(title: str) -> None:
    pad = max(1, 66 - len(title))
    print(f"\n{BOLD}{YELLOW}-- {title} {'-' * pad}{RESET}")


def run_sprint_backtest(capital: float, target: float, start: date, end: date) -> None:
    n_days = (end - start).days
    hdr(f"XAUUSD V18 SPRINT — €{target:,.0f} in {n_days} dagen")
    print(f"  Startkapitaal : {BOLD}EUR {capital:,.0f}{RESET}")
    print(f"  Winstdoel     : {BOLD}{GREEN}+EUR {target:,.0f} ({target / capital * 100:.1f}%){RESET}")
    print(f"  Periode       : {start} - {end} ({n_days} dagen)")
    print(f"  Strategie     : {BOLD}V18 Sprint (risk 2.0%/1.5%/1.2%, KZ+50%, compound){RESET}")
    print(f"  FTMO limiet   : Max 6% DD = EUR {capital * 0.06:,.0f}\n")

    # Toon config vergelijking
    sec("V17 → V18 CONFIGURATIEVERGELIJKING")
    changes = [
        ("risk_a", DEFAULT_CFG["risk_a"], V18_CFG["risk_a"], "%"),
        ("risk_b", DEFAULT_CFG["risk_b"], V18_CFG["risk_b"], "%"),
        ("risk_c", DEFAULT_CFG["risk_c"], V18_CFG["risk_c"], "%"),
        ("tp3_r", DEFAULT_CFG["tp3_r"], V18_CFG["tp3_r"], "R"),
        ("tp2_r", DEFAULT_CFG["tp2_r"], V18_CFG["tp2_r"], "R"),
        ("tp1_pct", DEFAULT_CFG["tp1_pct"], V18_CFG["tp1_pct"], "%"),
        ("cooldown_h", DEFAULT_CFG["cooldown_h"], V18_CFG["cooldown_h"], "h"),
        ("max_dag", DEFAULT_CFG["max_dag"], V18_CFG["max_dag"], ""),
        ("sl_dag_max", DEFAULT_CFG["sl_dag_max"], V18_CFG["sl_dag_max"], ""),
        ("kz_mult", DEFAULT_CFG["kz_mult"], V18_CFG["kz_mult"], "x"),
        ("adx_min", DEFAULT_CFG["adx_min"], V18_CFG["adx_min"], ""),
    ]
    print(f"  {'Parameter':<14} {'V17':>8} {'V18':>8} {'Δ':>8}  Impact")
    print(f"  {'-' * 14} {'-' * 8} {'-' * 8} {'-' * 8}  {'-' * 30}")
    for name, old, new, unit in changes:
        if unit == "%":
            delta = f"+{(new - old) / old * 100:.0f}%"
            old_s = f"{old * 100:.2f}%"
            new_s = f"{new * 100:.2f}%"
        elif unit in ("R", "x", "h"):
            delta = f"+{new - old:.1f}{unit}" if new > old else f"{new - old:.1f}{unit}"
            old_s, new_s = f"{old}{unit}", f"{new}{unit}"
        else:
            delta = f"+{int(new - old)}" if new > old else str(int(new - old))
            old_s, new_s = str(int(old)), str(int(new))
        arrow = f"{GREEN}↑{RESET}" if new > old else f"{RED}↓{RESET}"
        print(f"  {name:<14} {old_s:>8} {GREEN}{new_s:>8}{RESET} {delta:>8}  {arrow}")

    svc = BacktestService()
    print(f"\n  Data laden voor {start} → {end}...")

    try:
        df_raw = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as e:
        print(f"\n{RED}FOUT bij data laden: {e}{RESET}")
        sys.exit(1)

    print(f"  {len(df_feat)} H1 bars geladen.\n")

    req = BacktestRequest(
        start_date=str(start),
        end_date=str(end),
        starting_capital=capital,
    )

    # Run BEIDE configs voor vergelijking
    cfg_v17 = svc._build_cfg(req, use_v18=False)
    cfg_v18 = svc._build_cfg(req, use_v18=True)

    print(f"  {BOLD}Backtest V17 (baseline)...{RESET}")
    try:
        trades_v17, _ = svc._run_backtest_engine(df_feat, cfg_v17, capital)
    except Exception as e:
        print(f"  {RED}V17 backtest mislukt: {e}{RESET}")
        trades_v17 = []

    print(f"  {BOLD}Backtest V18 (sprint)...{RESET}")
    try:
        trades_v18, _ = svc._run_backtest_engine(df_feat, cfg_v18, capital)
    except Exception as e:
        print(f"\n{RED}FOUT bij V18 backtest: {e}{RESET}")
        sys.exit(1)

    if not trades_v18:
        print(f"{RED}Geen trades gegenereerd.{RESET}")
        sys.exit(1)

    # ── VERWERK V18 TRADES ───────────────────────────────────────
    df18 = pd.DataFrame(trades_v18)
    df18["in_dt"] = pd.to_datetime(df18["in"], utc=True, errors="coerce")
    df18["uit_dt"] = pd.to_datetime(df18["uit"], utc=True, errors="coerce")
    df18["pnl"] = df18["pnl"].astype(float)

    start_ts = pd.Timestamp(start, tz="UTC")
    df18 = df18[df18["in_dt"] >= start_ts].reset_index(drop=True)
    df18["cum_pnl"] = df18["pnl"].cumsum()
    df18["sig_type"] = df18.get("type", pd.Series(["UNKNOWN"] * len(df18)))

    # ── VERWERK V17 TRADES (voor vergelijking) ───────────────────
    if trades_v17:
        df17 = pd.DataFrame(trades_v17)
        df17["in_dt"] = pd.to_datetime(df17["in"], utc=True, errors="coerce")
        df17 = df17[df17["in_dt"] >= start_ts].reset_index(drop=True)
        df17["pnl"] = df17["pnl"].astype(float)
        v17_pnl = float(df17["pnl"].sum())
        v17_trades = len(df17)
        v17_wr = float((df17["pnl"] > 0).mean()) * 100
        eq17 = df17["pnl"].cumsum() + capital
        peak17 = eq17.cummax()
        v17_dd = float(((peak17 - eq17) / peak17 * 100).max())
    else:
        v17_pnl = v17_trades = v17_wr = v17_dd = 0.0

    # Stop bij winstdoel
    hit_idx = df18[df18["cum_pnl"] >= target].index
    if not hit_idx.empty:
        stop_idx = int(hit_idx[0])
        reached_pnl = float(df18.iloc[stop_idx]["cum_pnl"])
        stop_time = df18.iloc[stop_idx]["uit_dt"]
        days_to_target = (stop_time - pd.Timestamp(start, tz="UTC")).days + 1
        doel_bereikt = True
    else:
        stop_idx = len(df18) - 1
        reached_pnl = float(df18["cum_pnl"].iloc[-1])
        days_to_target = n_days
        doel_bereikt = False

    df18_used = df18.iloc[: stop_idx + 1].copy()

    total_pnl = float(df18_used["pnl"].sum())
    final_cap = capital + total_pnl
    n_trades = len(df18_used)
    pnl_s = df18_used["pnl"]
    wins = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]
    wr = float((pnl_s > 0).mean()) * 100
    pf = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    cum_eq = pnl_s.cumsum() + capital
    peak = cum_eq.cummax()
    dd_pct = (peak - cum_eq) / peak * 100
    max_dd = float(dd_pct.max())
    ftmo_ok = max_dd < 6.0
    daily_avg = total_pnl / max(days_to_target, 1)

    # ── VERGELIJKING V17 vs V18 ──────────────────────────────────
    sec("V17 vs V18 VERGELIJKING")
    print(f"  {'Metric':<28} {'V17 (basis)':>14} {'V18 (sprint)':>14} {'Boost':>8}")
    print(f"  {'-' * 28} {'-' * 14} {'-' * 14} {'-' * 8}")
    metrics_cmp = [
        ("Totale winst", v17_pnl, total_pnl, "EUR"),
        ("Aantal trades", v17_trades, n_trades, "n"),
        ("Win rate", v17_wr, wr, "%"),
        ("Max drawdown", v17_dd, max_dd, "%"),
        ("Daggemiddelde", v17_pnl / n_days if n_days else 0, daily_avg, "EUR"),
    ]
    for label, old_v, new_v, unit in metrics_cmp:
        boost = ((new_v / old_v) - 1) * 100 if old_v != 0 else 0
        boost_str = f"{GREEN}+{boost:.0f}%{RESET}" if boost > 0 else f"{RED}{boost:.0f}%{RESET}"
        if unit == "EUR":
            print(f"  {label:<28} {clr(old_v, '+,.0f'):>23} {clr(new_v, '+,.0f'):>23} {boost_str:>17}")
        elif unit == "%":
            print(f"  {label:<28} {old_v:>13.1f}% {new_v:>13.1f}% {boost_str:>17}")
        else:
            print(f"  {label:<28} {int(old_v):>14} {int(new_v):>14} {boost_str:>17}")

    # ── OVERALL STATISTIEKEN V18 ─────────────────────────────────
    sec("V18 SPRINT — STATISTIEKEN")
    rows = [
        ("Totale winst", f"{clr(total_pnl, '+,.2f')} EUR"),
        ("Eindsaldo", f"EUR {final_cap:,.2f}"),
        ("Totaal rendement", f"{clr(total_pnl / capital * 100, '+.2f')}%"),
        ("", ""),
        ("Totaal trades", str(n_trades)),
        ("Dagen actief", f"{days_to_target} dagen"),
        ("Daggemiddelde", f"{clr(daily_avg, '+,.2f')} EUR/dag"),
        ("Win rate", f"{wr:.1f}%"),
        ("Profit factor", f"{pf:.2f}"),
        ("Max drawdown", f"{RED}{max_dd:.2f}%{RESET} (limiet: 6%)"),
        ("FTMO veiligheid", f"{capital * 0.06 - capital * max_dd / 100:,.0f} EUR marge"),
        ("FTMO goedgekeurd", f"{GREEN}JA{RESET}" if ftmo_ok else f"{RED}NEE{RESET}"),
    ]
    for label, val in rows:
        if label:
            print(f"  {label:<28} {val}")
        else:
            print()

    # ── WINSTDOEL STATUS ─────────────────────────────────────────
    sec("WINSTDOEL STATUS")
    if doel_bereikt:
        print(f"  {GREEN}{BOLD}*** WINSTDOEL €{target:,.0f} BEREIKT! ***{RESET}")
        print(f"  Datum bereikt  : {BOLD}{stop_time.strftime('%d %B %Y')}{RESET}")
        print(f"  Dagen nodig    : {BOLD}{days_to_target} dagen{RESET} (doel: {n_days} dagen)")
        print(f"  Trades nodig   : {BOLD}{n_trades} trades{RESET}")
        if days_to_target < n_days:
            buffer = n_days - days_to_target
            print(f"  {GREEN}Doel bereikt {buffer} dagen vroeger dan gepland!{RESET}")
    else:
        pct_done = reached_pnl / target * 100
        shortfall = target - reached_pnl
        print(f"  {YELLOW}Winstdoel NIET bereikt in {n_days} dagen.{RESET}")
        print(f"  Bereikte winst : {clr(reached_pnl, '+,.2f')} EUR ({pct_done:.1f}% van doel)")
        print(f"  Tekort         : {RED}EUR {shortfall:,.0f}{RESET}")
        print("  Tip: Verhoog risk_a of verleng periode.")

    # ── WEEKOVERZICHT ────────────────────────────────────────────
    sec("WEEKOVERZICHT")
    print(f"  {'Week':<10} {'Start':>12} {'Eind':>12} {'Trades':>7} {'P&L':>12} {'Ret%':>7} {'Cum. Winst':>14}")
    print(f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 7} {'-' * 12} {'-' * 7} {'-' * 14}")

    df18_used["date"] = df18_used["in_dt"].dt.date
    df18_used["week"] = df18_used["in_dt"].dt.to_period("W").astype(str)
    wk_eq = capital
    cum_w = 0.0
    for wk, grp in df18_used.groupby("week"):
        wpnl = float(grp["pnl"].sum())
        cum_w += wpnl
        wk_end = wk_eq + wpnl
        wret = wpnl / wk_eq * 100 if wk_eq > 0 else 0
        marker = f" {GREEN}** DOEL{RESET}" if cum_w >= target and wk == df18_used["week"].iloc[stop_idx] else ""
        print(
            f"  {str(wk):<10} "
            f"EUR {wk_eq:>8,.0f} "
            f"EUR {wk_end:>8,.0f} "
            f"{len(grp):>7} "
            f"{clr(wpnl, '+,.0f'):>21} "
            f"{clr(wret, '+.1f'):>14}% "
            f"{clr(cum_w, '+,.0f'):>23}"
            f"{marker}"
        )
        wk_eq = wk_end

    # ── SIGNAALTYPE PRESTATIES ───────────────────────────────────
    sec("PRESTATIES PER SIGNAALTYPE (V18)")
    print(f"  {'Type':<14} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12} {'KZ bonus':>10}")
    print(f"  {'-' * 14} {'-' * 8} {'-' * 7} {'-' * 14} {'-' * 12} {'-' * 10}")
    for st in SIG_TYPES:
        sub = df18_used[df18_used["sig_type"] == st]
        if sub.empty:
            continue
        n = len(sub)
        wr_s = (sub["pnl"] > 0).mean() * 100
        tot = sub["pnl"].sum()
        avg = sub["pnl"].mean()
        base_risk = V18_CFG.get(
            "risk_a" if st == "A_EMACROSS" else "risk_b" if st in ("B_MACDCROSS", "E_BOS", "C_MOMENTUM") else "risk_c"
        )
        kz_risk = base_risk * V18_CFG["kz_mult"] * 100
        print(f"  {st:<14} {n:>8} {wr_s:>6.1f}% {clr(tot, '+,.2f'):>23} {clr(avg, '+,.2f'):>21} {kz_risk:>9.2f}%")

    # ── EQUITY CURVE ─────────────────────────────────────────────
    sec("EQUITY CURVE V18 (ASCII)")
    equities = [capital] + list(df18_used["pnl"].cumsum() + capital)
    target_line = capital + target
    mn, mx = min(equities), max(equities)
    span = mx - mn if mx != mn else 1
    step = max(1, len(equities) // 70)
    pts = equities[::step]
    rows_h = 14

    for r in range(rows_h, -1, -1):
        threshold = mn + span * (r / rows_h)
        is_target = abs(threshold - target_line) < span / rows_h
        label = f"EUR {threshold:>10,.0f} |"
        if is_target:
            label = f"{YELLOW}EUR {threshold:>10,.0f} |{RESET}"
            line = "".join("X" if p >= threshold else " " for p in pts)
            print(f"  {label} {line}  {YELLOW}<-- €{target:,.0f} DOEL{RESET}")
        else:
            line = "".join("X" if p >= threshold else " " for p in pts)
            print(f"  {label} {line}")

    t0 = df18_used["in_dt"].iloc[0].strftime("%Y-%m-%d")
    t1 = df18_used["uit_dt"].iloc[-1].strftime("%Y-%m-%d")
    print(f"  {'':>16}{'-' * (len(pts) + 2)}")
    print(f"  {'':>17}{t0}{'':>{max(1, len(pts) - 22)}}{t1}")

    # ── SAMENVATTING ─────────────────────────────────────────────
    hdr("SAMENVATTING — V18 SPRINT")
    print(f"  Strategie     : {BOLD}V18 Sprint (2.0% / 1.5% / 1.2% risico){RESET}")
    target_status = (
        f"{GREEN}{BOLD}BEREIKT in {days_to_target} dagen{RESET}" if doel_bereikt else f"{RED}NIET bereikt{RESET}"
    )
    print(f"  Winstdoel     : {target_status}")
    print(f"  Totale winst  : {BOLD}{clr(total_pnl, '+,.2f')} EUR{RESET}")
    print(f"  Daggemiddelde : {BOLD}{clr(daily_avg, '+,.2f')} EUR/dag{RESET}")
    print(f"  Max drawdown  : {RED}{max_dd:.2f}%{RESET} (FTMO limiet: 6%)")
    print(f"  FTMO status   : {f'{GREEN}GESLAAGD{RESET}' if ftmo_ok else f'{RED}GEZAKT{RESET}'}")
    print(f"  V17 → V18     : {clr(total_pnl - v17_pnl, '+,.0f')} EUR extra winst")
    print()

    # ── LIVE BOT INSTRUCTIE ──────────────────────────────────────
    sec("ACTIVEER V18 IN LIVE BOT")
    print("  In core/strategy_engine.py is V18_CFG klaar.")
    print("  Om de live bot te updaten naar V18:")
    print("    from core.strategy_engine import V18_CFG")
    print("    # Gebruik V18_CFG in plaats van DEFAULT_CFG")
    print()

    # CSV opslaan
    out = Path("results/backtests")
    out.mkdir(parents=True, exist_ok=True)
    df18_used.drop(columns=["in_dt", "uit_dt", "cum_pnl", "date", "week"], errors="ignore").to_csv(
        out / "trades_v18_sprint_30k.csv", index=False
    )
    print("  Trades opgeslagen: results/backtests/trades_v18_sprint_30k.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V18 Sprint Backtest — €30k in 60 dagen")
    parser.add_argument("--capital", type=float, default=160_000.0, help="Startkapitaal (default: 160000)")
    parser.add_argument("--target", type=float, default=30_000.0, help="Winstdoel EUR (default: 30000)")
    parser.add_argument("--days", type=int, default=60, help="Max dagen (default: 60)")
    parser.add_argument("--start", type=str, default="2026-01-01")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = start_date + timedelta(days=args.days)

    run_sprint_backtest(
        capital=args.capital,
        target=args.target,
        start=start_date,
        end=end_date,
    )
