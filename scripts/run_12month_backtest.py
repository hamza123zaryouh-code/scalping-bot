"""
XAUUSD V17 Backtest — Uitgebreide Analyse
==========================================
Toont: week/maand P&L, max dagverlies, signalen per maand per type.

Gebruik:
    python scripts/run_12month_backtest.py --capital 160000 --start 2026-01-01 --end 2026-03-31
    python scripts/run_12month_backtest.py --capital 160000 --year 2025
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
    print(f"\n{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")


def sec(title: str) -> None:
    pad = max(1, 62 - len(title))
    print(f"\n{BOLD}{YELLOW}-- {title} {'-' * pad}{RESET}")


def run_backtest(capital: float, start: date, end: date) -> None:
    hdr(f"XAUUSD V18 SPRINT - 12 MAANDEN BACKTEST  ({start} -> {end})")
    print(f"  Startkapitaal : {BOLD}EUR {capital:,.0f}{RESET}")
    print(f"  Periode       : {start} -> {end}  ({(end - start).days} dagen)")
    print(f"  Strategie     : {BOLD}V18 Sprint (risk 2.0%/1.5%/1.2%, KZ+50%, compound){RESET}")
    print(f"  FTMO-regel    : Stop als equity < EUR {capital * 0.90:,.0f} (10% balans-verlies)")
    print("  Data          : Gold Futures GC=F H1 via yfinance\n")

    # ── Data ophalen via BacktestService intern ──────────────────
    svc = BacktestService()
    print("  Data laden en indicatoren berekenen...")

    try:
        df_raw = svc._fetch_data(start, end)
        df_feat = svc._engine.prepare_features(df_raw)
    except Exception as e:
        print(f"\n{RED}FOUT bij data laden: {e}{RESET}")
        sys.exit(1)

    print(f"  {len(df_feat)} H1 bars geladen. Backtest wordt uitgevoerd...\n")

    # Bouw config
    req = BacktestRequest(
        start_date=str(start),
        end_date=str(end),
        starting_capital=capital,
    )
    cfg = svc._build_cfg(req, use_v18=True)

    # ── Engine draaien — raw trades ophalen ─────────────────────
    # Balance-based FTMO: stop alleen als equity < startkapitaal * 90%
    # (echte FTMO-regel: max 10% verlies t.o.v. startbalans, niet t.o.v. piek)
    try:
        raw_trades, final_cap = svc._run_backtest_engine(
            df_feat,
            cfg,
            capital,
            ftmo_floor_pct=0.10,
            ftmo_balance_based=True,
        )
    except Exception as e:
        print(f"\n{RED}FOUT bij backtest: {e}{RESET}")
        sys.exit(1)

    if not raw_trades:
        print(f"{RED}Geen trades gegenereerd in deze periode.{RESET}")
        sys.exit(1)

    trades_df = pd.DataFrame(raw_trades)
    trades_df["in_dt"] = pd.to_datetime(trades_df["in"], utc=True, errors="coerce")
    trades_df["uit_dt"] = pd.to_datetime(trades_df["uit"], utc=True, errors="coerce")
    trades_df["pnl"] = trades_df["pnl"].astype(float)
    trades_df["date"] = trades_df["in_dt"].dt.date
    trades_df["month"] = trades_df["in_dt"].dt.to_period("M").astype(str)
    trades_df["sig_type"] = trades_df.get("type", pd.Series(["UNKNOWN"] * len(trades_df)))

    total_pnl = trades_df["pnl"].sum()
    n_days = (end - start).days
    n_weeks = n_days / 7
    n_months = n_days / 30.44

    # ── Metrics ─────────────────────────────────────────────────
    pnl_s = trades_df["pnl"]
    wins = pnl_s[pnl_s > 0]
    losses = pnl_s[pnl_s < 0]
    cum_eq = pnl_s.cumsum() + capital
    peak = cum_eq.cummax()
    dd_pct = (peak - cum_eq) / peak * 100
    max_dd = float(dd_pct.max())
    pf = float(wins.sum() / losses.abs().sum()) if not losses.empty else 99.0
    wr = float((pnl_s > 0).mean())
    sharpe = 0.0
    if len(pnl_s) > 1:
        ret = pnl_s / capital
        sharpe = float(ret.mean() / ret.std(ddof=0) * (252**0.5)) if ret.std(ddof=0) > 0 else 0.0
    ftmo_ok = max_dd < 6.0

    lots = trades_df.get("lot_size", pd.Series([0.01] * len(trades_df))).astype(float)
    lot_min = float(lots.min())
    lot_max = float(lots.max())
    lot_gem = float(lots.mean())

    sec("OVERALL STATISTIEKEN")
    rows = [
        ("Totale winst/verlies", f"{clr(total_pnl, '+,.2f')} EUR"),
        ("Totaal rendement", f"{clr(total_pnl / capital * 100, '+.2f')}%"),
        ("Eindsaldo", f"EUR {final_cap:,.2f}"),
        ("", ""),
        ("Gem. per week", f"{clr(total_pnl / max(n_weeks, 1), '+,.2f')} EUR"),
        ("Gem. per maand", f"{clr(total_pnl / max(n_months, 1), '+,.2f')} EUR"),
        ("", ""),
        ("Totaal trades", str(len(trades_df))),
        ("Win rate", f"{wr * 100:.1f}%"),
        ("Profit factor", f"{pf:.2f}"),
        ("Sharpe ratio", f"{sharpe:.2f}"),
        ("Max drawdown", f"{RED}{max_dd:.2f}%{RESET}"),
        ("Gem. win/trade", f"{clr(float(wins.mean()) if not wins.empty else 0, '+,.2f')} EUR"),
        ("Gem. loss/trade", f"{clr(float(losses.mean()) if not losses.empty else 0, '+,.2f')} EUR"),
        ("Verwacht per trade", f"{clr(float(pnl_s.mean()), '+,.2f')} EUR"),
        ("", ""),
        ("Lotsize (min)", f"{lot_min:.2f} lots"),
        ("Lotsize (gem.)", f"{lot_gem:.2f} lots"),
        ("Lotsize (max)", f"{lot_max:.2f} lots  (bij hogere equity via compound)"),
        ("FTMO goedgekeurd", f"{GREEN}JA (< 6%){RESET}" if ftmo_ok else f"{RED}NEE{RESET}"),
    ]
    for label, val in rows:
        if label:
            print(f"  {label:<28} {val}")
        else:
            print()

    # ── MAX DAGVERLIES ───────────────────────────────────────────
    sec("MAX DAGVERLIES ANALYSE")
    daily = (
        trades_df.groupby("date")["pnl"].agg(dag_pnl="sum", trades="count", wins=lambda s: (s > 0).sum()).reset_index()
    )
    daily["verlies_days"] = daily["dag_pnl"] < 0

    worst_day = daily.loc[daily["dag_pnl"].idxmin()]
    best_day = daily.loc[daily["dag_pnl"].idxmax()]
    verlies_dgn = daily[daily["dag_pnl"] < 0]
    winst_dgn = daily[daily["dag_pnl"] > 0]

    ftmo_dag_lim = capital * 0.05  # 5% dag limiet

    print(
        f"  {'Slechtste dag':<28} {RED}{worst_day['date']}{RESET}  "
        f"verlies: {RED}{worst_day['dag_pnl']:+,.2f} EUR{RESET}  "
        f"({worst_day['trades']:.0f} trades)"
    )
    print(
        f"  {'Beste dag':<28} {GREEN}{best_day['date']}{RESET}  "
        f"winst: {GREEN}{best_day['dag_pnl']:+,.2f} EUR{RESET}  "
        f"({best_day['trades']:.0f} trades)"
    )
    avg_loss_day = float(verlies_dgn["dag_pnl"].mean()) if not verlies_dgn.empty else 0
    print(f"  {'Gem. verliesdag':<28} {clr(avg_loss_day, '+,.2f')} EUR")
    print(
        f"  {'Gem. winstdag':<28} {clr(float(winst_dgn['dag_pnl'].mean()) if not winst_dgn.empty else 0, '+,.2f')} EUR"
    )
    print(f"  {'Totaal verliesdagen':<28} {len(verlies_dgn)} van {len(daily)} handelsdagen")
    print(f"  {'FTMO dag-limiet (5%)':<28} EUR {ftmo_dag_lim:,.2f}")
    over_limit = daily[daily["dag_pnl"] < -ftmo_dag_lim]
    if over_limit.empty:
        print(f"  {'Dagen boven dag-limiet':<28} {GREEN}0 (FTMO veilig){RESET}")
    else:
        print(f"  {'Dagen boven dag-limiet':<28} {RED}{len(over_limit)} dag(en)!{RESET}")

    # Top 5 slechtste dagen
    print(f"\n  {BOLD}Top 5 slechtste handelsdagen:{RESET}")
    print(f"  {'Datum':<14} {'P&L (EUR)':>14} {'Trades':>8} {'% van kap':>10}")
    print(f"  {'-' * 14} {'-' * 14} {'-' * 8} {'-' * 10}")
    for _, row in daily.nsmallest(5, "dag_pnl").iterrows():
        pct = row["dag_pnl"] / capital * 100
        print(
            f"  {str(row['date']):<14} {clr(row['dag_pnl'], '+,.2f'):>23} "
            f"{int(row['trades']):>8} {clr(pct, '+.2f'):>19}%"
        )

    # ── SIGNALEN PER MAAND ───────────────────────────────────────
    sec("SIGNALEN PER MAAND PER TYPE")

    sig_month = trades_df.groupby(["month", "sig_type"]).size().unstack(fill_value=0)
    # Zorg dat alle types aanwezig zijn
    for st in SIG_TYPES:
        if st not in sig_month.columns:
            sig_month[st] = 0
    sig_month = sig_month.reindex(columns=SIG_TYPES, fill_value=0)
    sig_month["TOTAAL"] = sig_month.sum(axis=1)

    # Header
    col_w = 11
    header = f"  {'Maand':<10}"
    for st in SIG_TYPES:
        short = st.split("_")[0]  # A, B, C, D, E, F
        header += f" {short:>{col_w}}"
    header += f" {'TOTAAL':>{col_w}}"
    print(header)
    print(f"  {'-' * 10}" + f" {'-' * col_w}" * (len(SIG_TYPES) + 1))

    for month, row in sig_month.iterrows():
        line = f"  {str(month):<10}"
        for st in SIG_TYPES:
            v = int(row[st])
            line += f" {v:>{col_w}}"
        tot = int(row["TOTAAL"])
        line += f" {BOLD}{tot:>{col_w}}{RESET}"
        print(line)

    # Totaalrij
    totals = sig_month.sum()
    line = f"  {'TOTAAL':<10}"
    for st in SIG_TYPES:
        line += f" {BOLD}{int(totals[st]):>{col_w}}{RESET}"
    line += f" {BOLD}{CYAN}{int(totals['TOTAAL']):>{col_w}}{RESET}"
    print(f"  {'-' * 10}" + f" {'-' * col_w}" * (len(SIG_TYPES) + 1))
    print(line)

    # Win rate per signaaltype
    sec("WIN RATE & P&L PER SIGNAALTYPE")
    print(f"  {'Type':<14} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12} {'Gem lot':>9}")
    print(f"  {'-' * 14} {'-' * 8} {'-' * 7} {'-' * 14} {'-' * 12} {'-' * 9}")
    for st in SIG_TYPES:
        sub = trades_df[trades_df["sig_type"] == st]
        if sub.empty:
            continue
        n = len(sub)
        wr_s = (sub["pnl"] > 0).mean() * 100
        tot = sub["pnl"].sum()
        avg = sub["pnl"].mean()
        lot_avg = float(sub.get("lot_size", pd.Series([0.01] * n)).mean())
        print(f"  {st:<14} {n:>8} {wr_s:>6.1f}% {clr(tot, '+,.2f'):>23} {clr(avg, '+,.2f'):>21} {lot_avg:>8.2f}")

    # ── MAANDOVERZICHT ───────────────────────────────────────────
    sec("MAANDOVERZICHT")
    print(f"  {'Maand':<10} {'Trades':>8} {'P&L (EUR)':>14} {'Ret%':>7} {'Win%':>7} {'Saldo':>14}")
    print(f"  {'-' * 10} {'-' * 8} {'-' * 14} {'-' * 7} {'-' * 7} {'-' * 14}")

    running = capital
    for month, grp in trades_df.groupby("month"):
        n = len(grp)
        mpnl = grp["pnl"].sum()
        mwr = (grp["pnl"] > 0).mean() * 100
        mret = mpnl / running * 100 if running > 0 else 0.0
        running += mpnl
        print(
            f"  {str(month):<10} {n:>8} {clr(mpnl, '+,.2f'):>23} "
            f"{clr(mret, '+.2f'):>16}% {mwr:>6.1f}% "
            f"EUR {running:>10,.0f}"
        )

    # ── WEEKOVERZICHT ────────────────────────────────────────────
    sec("WEEKOVERZICHT")
    print(f"  {'Week':<10} {'Start (EUR)':>14} {'Eind (EUR)':>14} {'Trades':>7} {'P&L':>12} {'Ret%':>7} {'Win%':>7}")
    print(f"  {'-' * 10} {'-' * 14} {'-' * 14} {'-' * 7} {'-' * 12} {'-' * 7} {'-' * 7}")

    if hasattr(svc, "_build_weekly_summary"):
        ws = svc._build_weekly_summary(trades_df.rename(columns={"in": "in", "uit": "uit"}), capital)
        for w_row in ws:
            print(
                f"  {str(w_row.week):<10} EUR {float(w_row.start_equity):>10,.0f} "
                f"EUR {float(w_row.end_equity):>10,.0f} {int(w_row.trades):>7} "
                f"{clr(float(w_row.pnl), '+,.2f'):>21} "
                f"{clr(float(w_row.return_pct), '+.2f'):>16}% "
                f"{float(w_row.win_rate) * 100:>6.1f}%"
            )

    # ── EQUITY CURVE ─────────────────────────────────────────────
    sec("EQUITY CURVE (ASCII)")
    equities = [capital] + list(trades_df["pnl"].cumsum() + capital)
    mn, mx = min(equities), max(equities)
    span = mx - mn if mx != mn else 1
    step = max(1, len(equities) // 65)
    pts = equities[::step]
    rows_h = 12

    for r in range(rows_h, -1, -1):
        threshold = mn + span * (r / rows_h)
        label = f"EUR {threshold:>10,.0f} |"
        line = "".join("X" if p >= threshold else " " for p in pts)
        print(f"  {label} {line}")

    print(f"  {'':>16}{'-' * (len(pts) + 2)}")
    print(f"  {'':>17}{start}{'':>{max(1, len(pts) - 22)}}{end}")

    # ── SAMENVATTING ─────────────────────────────────────────────
    hdr("SAMENVATTING")
    status = f"{GREEN}WINSTGEVEND{RESET}" if total_pnl > 0 else f"{RED}VERLIESLATEND{RESET}"
    print(f"  Status              : {BOLD}{status}{RESET}")
    print(f"  Totale winst        : {BOLD}{clr(total_pnl, '+,.2f')} EUR{RESET}")
    print(f"  Gem. per maand      : {BOLD}{clr(total_pnl / max(n_months, 1), '+,.2f')} EUR{RESET}")
    print(f"  Gem. per week       : {BOLD}{clr(total_pnl / max(n_weeks, 1), '+,.2f')} EUR{RESET}")
    print(f"  Max dagverlies      : {RED}{float(daily['dag_pnl'].min()):+,.2f} EUR{RESET}  ({str(worst_day['date'])})")
    print(f"  Max drawdown        : {RED}{max_dd:.2f}%{RESET}")
    print(f"  FTMO status         : {f'{GREEN}GESLAAGD{RESET}' if ftmo_ok else f'{RED}GEZAKT{RESET}'}")
    print()

    # CSV opslaan
    _save_reports(trades_df, daily, sig_month, start, end)


def _save_reports(trades_df, daily, sig_month, start, end) -> None:
    out = Path("results/backtests")
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{start}_{end}"

    trades_df.drop(columns=["in_dt", "uit_dt", "date", "month"], errors="ignore").to_csv(
        out / f"trades_{tag}.csv", index=False
    )
    daily.to_csv(out / f"dagelijks_{tag}.csv", index=False)
    sig_month.to_csv(out / f"signalen_per_maand_{tag}.csv")
    print("  Rapporten opgeslagen in results/backtests/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XAUUSD backtest met dagverlies & signaalanalyse")
    parser.add_argument("--capital", type=float, default=160_000.0)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    args = parser.parse_args()

    today = date.today()

    if args.start and args.end:
        s = date.fromisoformat(args.start)
        e = date.fromisoformat(args.end)
    elif args.year:
        s = date(args.year, 1, 1)
        e = date(args.year, 12, 31)
    else:
        e = today - timedelta(days=1)
        s = date(today.year - 1, today.month, today.day)

    run_backtest(capital=args.capital, start=s, end=e)
