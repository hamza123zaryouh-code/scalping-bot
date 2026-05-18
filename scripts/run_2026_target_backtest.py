"""
XAUUSD 2026 Backtest — Stop bij €16.000 winst
==============================================
Draait backtest voor 2026. Stopt zodra cumulatieve winst >= €16.000.
Toont volledige weekoverzicht tot het stopp-punt.

Gebruik:
    python scripts/run_2026_target_backtest.py
    python scripts/run_2026_target_backtest.py --capital 160000 --target 16000
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

SIG_TYPES = ["A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"]


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


def run_2026_target(capital: float, target: float, start: date, end: date) -> None:
    hdr(f"XAUUSD 2026 — Stop bij +€{target:,.0f} winst")
    print(f"  Startkapitaal : {BOLD}EUR {capital:,.0f}{RESET}")
    print(f"  Winstdoel     : {BOLD}{GREEN}+EUR {target:,.0f}{RESET}")
    print(f"  Periode       : {start} - {end}")
    print("  Data          : Gold Futures GC=F H1 via yfinance\n")

    svc = BacktestService()
    print("  Data laden en indicatoren berekenen...")

    try:
        df_raw  = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as e:
        print(f"\n{RED}FOUT bij data laden: {e}{RESET}")
        sys.exit(1)

    print(f"  {len(df_feat)} H1 bars geladen. Backtest wordt uitgevoerd...\n")

    req = BacktestRequest(
        start_date=str(start),
        end_date=str(end),
        starting_capital=capital,
    )
    cfg = svc._build_cfg(req)

    try:
        raw_trades, _ = svc._run_backtest_engine(df_feat, cfg, capital)
    except Exception as e:
        print(f"\n{RED}FOUT bij backtest: {e}{RESET}")
        sys.exit(1)

    if not raw_trades:
        print(f"{RED}Geen trades gegenereerd in deze periode.{RESET}")
        sys.exit(1)

    # ── Stop zodra cumulatieve winst >= target ──────────────────
    trades_df = pd.DataFrame(raw_trades)
    trades_df["in_dt"]  = pd.to_datetime(trades_df["in"],  utc=True, errors="coerce")
    trades_df["uit_dt"] = pd.to_datetime(trades_df["uit"], utc=True, errors="coerce")
    trades_df["pnl"]    = trades_df["pnl"].astype(float)

    # Filter: alleen trades die GEOPEND zijn na start_date (buffer periode uitsluiten)
    start_ts = pd.Timestamp(start, tz="UTC")
    trades_df = trades_df[trades_df["in_dt"] >= start_ts].reset_index(drop=True)

    if trades_df.empty:
        print(f"{RED}Geen trades gegenereerd na {start}.{RESET}")
        sys.exit(1)

    print(f"  {len(trades_df)} trades gevonden in 2026.\n")

    trades_df["cum_pnl"] = trades_df["pnl"].cumsum()
    hit_idx = trades_df[trades_df["cum_pnl"] >= target].index

    if hit_idx.empty:
        max_pnl = trades_df["cum_pnl"].iloc[-1]
        print(f"{YELLOW}Winstdoel van €{target:,.0f} nog NIET bereikt in deze periode.{RESET}")
        print(f"  Maximale winst bereikte: {clr(max_pnl, '+,.2f')} EUR")
        print(f"  Alle {len(trades_df)} trades worden getoond.\n")
        stop_idx = len(trades_df) - 1
    else:
        stop_idx = int(hit_idx[0])
        stop_trade = trades_df.iloc[stop_idx]
        reached_pnl = float(stop_trade["cum_pnl"])
        stop_time   = stop_trade["uit_dt"]
        print(f"  {GREEN}{BOLD}WINSTDOEL BEREIKT!{RESET}")
        print(f"  Datum/tijd   : {BOLD}{stop_time.strftime('%Y-%m-%d %H:%M UTC')}{RESET}")
        print(f"  Trade nr.    : {stop_idx + 1}")
        print(f"  Cumulatieve winst: {clr(reached_pnl, '+,.2f')} EUR\n")

    # Filter trades t/m stopp-punt
    trades_df = trades_df.iloc[:stop_idx + 1].copy()

    trades_df["date"]     = trades_df["in_dt"].dt.date
    trades_df["month"]    = trades_df["in_dt"].dt.to_period("M").astype(str)
    trades_df["sig_type"] = trades_df.get("type", pd.Series(["UNKNOWN"] * len(trades_df)))

    total_pnl   = float(trades_df["pnl"].sum())
    final_cap   = capital + total_pnl
    n_trades    = len(trades_df)
    pnl_s       = trades_df["pnl"]
    wins        = pnl_s[pnl_s > 0]
    losses      = pnl_s[pnl_s < 0]
    wr          = float((pnl_s > 0).mean())
    pf          = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    cum_eq      = pnl_s.cumsum() + capital
    peak        = cum_eq.cummax()
    dd_pct      = ((peak - cum_eq) / peak * 100)
    max_dd      = float(dd_pct.max())
    ftmo_ok     = max_dd < 6.0

    # Tijdsduur
    if n_trades > 0:
        t_start = trades_df["in_dt"].iloc[0]
        t_end   = trades_df["uit_dt"].iloc[stop_idx]
        n_days_traded = (t_end - t_start).days + 1
    else:
        n_days_traded = 0

    # ── OVERALL STATISTIEKEN ─────────────────────────────────────
    sec("OVERALL STATISTIEKEN")
    rows = [
        ("Totale winst/verlies",  f"{clr(total_pnl, '+,.2f')} EUR"),
        ("Eindsaldo",             f"EUR {final_cap:,.2f}"),
        ("Totaal rendement",      f"{clr(total_pnl / capital * 100, '+.2f')}%"),
        ("",                      ""),
        ("Totaal trades",         str(n_trades)),
        ("Handelsdagen actief",   f"{n_days_traded} dagen"),
        ("Win rate",              f"{wr * 100:.1f}%"),
        ("Profit factor",         f"{pf:.2f}"),
        ("Max drawdown",          f"{RED}{max_dd:.2f}%{RESET}"),
        ("Gem. win/trade",        f"{clr(float(wins.mean()) if not wins.empty else 0, '+,.2f')} EUR"),
        ("Gem. loss/trade",       f"{clr(float(losses.mean()) if not losses.empty else 0, '+,.2f')} EUR"),
        ("Verwacht per trade",    f"{clr(float(pnl_s.mean()), '+,.2f')} EUR"),
        ("FTMO goedgekeurd",      f"{GREEN}JA (< 6%){RESET}" if ftmo_ok else f"{RED}NEE{RESET}"),
    ]
    for label, val in rows:
        if label:
            print(f"  {label:<28} {val}")
        else:
            print()

    # ── WEEKOVERZICHT ────────────────────────────────────────────
    sec("WEEKOVERZICHT — TOT WINSTDOEL BEREIKT")
    print(f"  {'Week':<10} {'Start (EUR)':>14} {'Eind (EUR)':>14} "
          f"{'Trades':>7} {'P&L (EUR)':>14} {'Ret%':>7} {'Win%':>7} {'Cum. winst':>14}")
    print(f"  {'-'*10} {'-'*14} {'-'*14} {'-'*7} {'-'*14} {'-'*7} {'-'*7} {'-'*14}")

    ws = svc._build_weekly_summary(
        trades_df.rename(columns={"in": "in", "uit": "uit"}), capital
    )

    cum_profit = 0.0
    for w_row in ws:
        cum_profit += float(w_row.pnl)
        target_hit = cum_profit >= target
        marker = f" {GREEN}** DOEL!{RESET}" if target_hit and ws.index(w_row) == ws.index(ws[-1]) else ""
        print(
            f"  {str(w_row.week):<10} "
            f"EUR {float(w_row.start_equity):>10,.0f} "
            f"EUR {float(w_row.end_equity):>10,.0f} "
            f"{int(w_row.trades):>7} "
            f"{clr(float(w_row.pnl), '+,.2f'):>23} "
            f"{clr(float(w_row.return_pct), '+.2f'):>16}% "
            f"{float(w_row.win_rate)*100:>6.1f}% "
            f"{clr(cum_profit, '+,.0f'):>23}"
            f"{marker}"
        )

    # ── SIGNAALTYPE PRESTATIES ───────────────────────────────────
    sec("PRESTATIES PER SIGNAALTYPE")
    print(f"  {'Type':<14} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12}")
    print(f"  {'-'*14} {'-'*8} {'-'*7} {'-'*14} {'-'*12}")
    for st in SIG_TYPES:
        sub = trades_df[trades_df["sig_type"] == st]
        if sub.empty:
            continue
        n    = len(sub)
        wr_s = (sub["pnl"] > 0).mean() * 100
        tot  = sub["pnl"].sum()
        avg  = sub["pnl"].mean()
        print(f"  {st:<14} {n:>8} {wr_s:>6.1f}% {clr(tot, '+,.2f'):>23} {clr(avg, '+,.2f'):>21}")

    # ── EQUITY CURVE ─────────────────────────────────────────────
    sec("EQUITY CURVE (ASCII)")
    equities = [capital] + list(trades_df["pnl"].cumsum() + capital)
    target_line = capital + target
    mn, mx = min(equities), max(equities)
    span = mx - mn if mx != mn else 1
    step = max(1, len(equities) // 65)
    pts  = equities[::step]
    rows_h = 12

    for r in range(rows_h, -1, -1):
        threshold = mn + span * (r / rows_h)
        is_target = abs(threshold - target_line) < span / rows_h
        label = f"EUR {threshold:>10,.0f} |"
        if is_target:
            label = f"{YELLOW}EUR {threshold:>10,.0f} |{RESET}"
            line  = "".join("X" if p >= threshold else " " for p in pts)
            print(f"  {label} {line}  {YELLOW}<< EUR {target:,.0f} DOEL{RESET}")
        else:
            line  = "".join("X" if p >= threshold else " " for p in pts)
            print(f"  {label} {line}")

    # Datum as
    if n_trades > 0:
        t0 = trades_df["in_dt"].iloc[0].strftime("%Y-%m-%d")
        t1 = trades_df["uit_dt"].iloc[-1].strftime("%Y-%m-%d")
    else:
        t0, t1 = str(start), str(end)
    print(f"  {'':>16}{'-' * (len(pts) + 2)}")
    print(f"  {'':>17}{t0}{'':>{max(1, len(pts) - 22)}}{t1}")

    # ── SAMENVATTING ─────────────────────────────────────────────
    hdr("SAMENVATTING")
    if not hit_idx.empty:
        stop_trade = pd.DataFrame(raw_trades).iloc[stop_idx]
        stop_dt = pd.to_datetime(stop_trade["uit"], utc=True)
        days_to_target = (stop_dt - pd.Timestamp(start, tz="UTC")).days + 1
        print(f"  Winstdoel bereikt  : {BOLD}{GREEN}JA — €{target:,.0f}{RESET}")
        print(f"  Datum bereikt      : {BOLD}{stop_dt.strftime('%d %B %Y')}{RESET}")
        print(f"  Dagen nodig        : {BOLD}{days_to_target} dagen{RESET}")
        print(f"  Trades nodig       : {BOLD}{n_trades} trades{RESET}")
    else:
        print(f"  Winstdoel bereikt  : {RED}NEE{RESET}")

    print(f"  Totale winst       : {BOLD}{clr(total_pnl, '+,.2f')} EUR{RESET}")
    print(f"  Eindsaldo          : {BOLD}EUR {final_cap:,.2f}{RESET}")
    print(f"  Max drawdown       : {RED}{max_dd:.2f}%{RESET}")
    print(f"  FTMO status        : {f'{GREEN}GESLAAGD{RESET}' if ftmo_ok else f'{RED}GEZAKT{RESET}'}")
    print()

    # CSV opslaan
    out = Path("results/backtests")
    out.mkdir(parents=True, exist_ok=True)
    tag = f"2026_target_{int(target)}"
    trades_df.drop(columns=["in_dt", "uit_dt", "date", "month", "cum_pnl"], errors="ignore").to_csv(
        out / f"trades_{tag}.csv", index=False
    )
    print(f"  Trades opgeslagen in results/backtests/trades_{tag}.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="2026 backtest — stop bij winstdoel")
    parser.add_argument("--capital", type=float, default=160_000.0)
    parser.add_argument("--target",  type=float, default=16_000.0, help="Winstdoel in EUR")
    parser.add_argument("--start",   type=str,   default="2026-01-01")
    parser.add_argument("--end",     type=str,   default="2026-05-14")
    args = parser.parse_args()

    run_2026_target(
        capital=args.capital,
        target=args.target,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
