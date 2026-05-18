"""
XAUUSD V21 Backtest - Doel: EUR20-40k/maand, geen verlies weken
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService
from core.strategy_engine import V21_CFG

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


CAPITAL = 160_000.0
START = date(2025, 10, 1)
END = date(2026, 5, 18)

hdr(f"XAUUSD V21 BACKTEST - Doel EUR20-40k/maand | Geen verlies weken")
print(f"  Startkapitaal : {BOLD}EUR {CAPITAL:,.0f}{RESET}")
print(f"  Periode       : {START} -> {END} ({(END - START).days} dagen)")
print(f"  Strategie     : V21 (1.4%/1.1%/0.85% risk, weekly stop -2%, dagwinst-lock +2.5%)")
print(f"  FTMO limiet   : Max 10% DD = EUR {CAPITAL * 0.10:,.0f}")

svc = BacktestService()
print(f"\n  Data laden...")

try:
    df_raw = svc._fetch_data(START, END)
    df_feat = svc._engine.prepare_features(df_raw)
except Exception as e:
    print(f"\n{RED}FOUT bij data laden: {e}{RESET}")
    sys.exit(1)

print(f"  {len(df_feat)} H1 bars geladen.")

req = BacktestRequest(start_date=str(START), end_date=str(END), starting_capital=CAPITAL)
cfg = {**V21_CFG}

print(f"  Backtest V21 draaien...")
trades, final_cap = svc._run_backtest_engine(df_feat, cfg, CAPITAL)

if not trades:
    print(f"{RED}Geen trades gegenereerd.{RESET}")
    sys.exit(1)

df = pd.DataFrame(trades)
df["in_dt"] = pd.to_datetime(df["in"], utc=True, errors="coerce")
df["uit_dt"] = pd.to_datetime(df["uit"], utc=True, errors="coerce")
df["pnl"] = df["pnl"].astype(float)

start_ts = pd.Timestamp(START, tz="UTC")
df = df[df["in_dt"] >= start_ts].reset_index(drop=True)
df["cum_pnl"] = df["pnl"].cumsum()
df["sig_type"] = df.get("type", pd.Series(["?"] * len(df)))

# ── GLOBALE STATISTIEKEN ─────────────────────────────────────────
total_pnl = float(df["pnl"].sum())
n_trades = len(df)
wins = df["pnl"][df["pnl"] > 0]
losses = df["pnl"][df["pnl"] < 0]
wr = float((df["pnl"] > 0).mean()) * 100
pf = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
cum_eq = df["pnl"].cumsum() + CAPITAL
peak = cum_eq.cummax()
dd_series = (peak - cum_eq) / peak * 100
max_dd = float(dd_series.max())
daily_avg = total_pnl / max((END - START).days, 1)
monthly_avg = total_pnl / max((END - START).days / 30, 1)
ftmo_ok = max_dd < 10.0

sec("GLOBALE STATISTIEKEN")
stats = [
    ("Totale winst", f"{clr(total_pnl, '+,.2f')} EUR"),
    ("Eindsaldo", f"EUR {CAPITAL + total_pnl:,.2f}"),
    ("Maandgemiddelde", f"{clr(monthly_avg, '+,.0f')} EUR/maand"),
    ("Daggemiddelde", f"{clr(daily_avg, '+,.2f')} EUR/dag"),
    ("Aantal trades", str(n_trades)),
    ("Win rate", f"{wr:.1f}%"),
    ("Profit factor", f"{pf:.2f}"),
    ("Max drawdown", f"{RED if max_dd > 6 else GREEN}{max_dd:.2f}%{RESET}"),
    ("FTMO status", f"{GREEN}GESLAAGD{RESET}" if ftmo_ok else f"{RED}GEZAKT{RESET}"),
]
for label, val in stats:
    print(f"  {label:<22} {val}")

# ── WEEKOVERZICHT ────────────────────────────────────────────────
sec("WEEKOVERZICHT")
print(f"  {'Week':<12} {'Trades':>7} {'Winst':>8} {'Verlies':>8} {'WR%':>6} {'P&L':>12} {'Week%':>7} {'Cum P&L':>14} {'Status':>10}")
print(f"  {'-' * 12} {'-' * 7} {'-' * 8} {'-' * 8} {'-' * 6} {'-' * 12} {'-' * 7} {'-' * 14} {'-' * 10}")

df["week"] = df["in_dt"].dt.to_period("W").astype(str)
df["month"] = df["in_dt"].dt.to_period("M").astype(str)

wk_eq = CAPITAL
cum_w = 0.0
verlies_weken = 0
winst_weken = 0

for wk, grp in df.groupby("week"):
    wpnl = float(grp["pnl"].sum())
    cum_w += wpnl
    wk_end = wk_eq + wpnl
    wret = wpnl / wk_eq * 100 if wk_eq > 0 else 0
    n_w = len(grp)
    n_wins = int((grp["pnl"] > 0).sum())
    n_loss = int((grp["pnl"] < 0).sum())
    wr_w = n_wins / n_w * 100 if n_w > 0 else 0

    if wpnl > 0:
        status = f"{GREEN}WIN{RESET}"
        winst_weken += 1
    elif wpnl < 0:
        status = f"{RED}VERLIES{RESET}"
        verlies_weken += 1
    else:
        status = f"{YELLOW}FLAT{RESET}"

    print(
        f"  {str(wk):<12} "
        f"{n_w:>7} "
        f"{n_wins:>8} "
        f"{n_loss:>8} "
        f"{wr_w:>5.0f}% "
        f"{clr(wpnl, '+,.0f'):>21} "
        f"{clr(wret, '+.1f'):>14}% "
        f"{clr(cum_w, '+,.0f'):>23} "
        f"  {status}"
    )
    wk_eq = wk_end

print(f"\n  Winst weken  : {GREEN}{winst_weken}{RESET}")
print(f"  Verlies weken: {RED}{verlies_weken}{RESET}")
total_weeks = winst_weken + verlies_weken
if total_weeks > 0:
    print(f"  Winstweek %  : {GREEN}{winst_weken / total_weeks * 100:.0f}%{RESET} van alle weken")

# ── MAANDOVERZICHT ───────────────────────────────────────────────
sec("MAANDOVERZICHT")
print(f"  {'Maand':<10} {'Trades':>7} {'P&L':>14} {'Return%':>9} {'Max DD%':>9} {'Status':>10}")
print(f"  {'-' * 10} {'-' * 7} {'-' * 14} {'-' * 9} {'-' * 9} {'-' * 10}")

m_eq = CAPITAL
for mo, mgrp in df.groupby("month"):
    mpnl = float(mgrp["pnl"].sum())
    mret = mpnl / m_eq * 100 if m_eq > 0 else 0
    m_cum = mgrp["pnl"].cumsum() + m_eq
    m_peak = m_cum.cummax()
    m_dd = float(((m_peak - m_cum) / m_peak * 100).max()) if len(m_cum) > 0 else 0
    n_m = len(mgrp)
    doel_ok = 20_000 <= mpnl <= 50_000
    status = f"{GREEN}IN DOEL{RESET}" if doel_ok else (f"{YELLOW}TE LAAG{RESET}" if mpnl < 20_000 else f"{CYAN}BOVEN DOEL{RESET}")
    print(
        f"  {str(mo):<10} "
        f"{n_m:>7} "
        f"{clr(mpnl, '+,.0f'):>23} "
        f"{clr(mret, '+.1f'):>16}% "
        f"{m_dd:>8.2f}% "
        f"  {status}"
    )
    m_eq += mpnl

# ── MAX DRAWDOWN DETAIL ──────────────────────────────────────────
sec("MAX DRAWDOWN DETAIL")
dd_idx = int(dd_series.idxmax())
dd_start_equity = float(peak.iloc[dd_idx])
dd_end_equity = float(cum_eq.iloc[dd_idx])
dd_eur = dd_start_equity - dd_end_equity
print(f"  Max drawdown      : {RED}{max_dd:.2f}%{RESET} = EUR {dd_eur:,.0f}")
print(f"  Op datum          : {df['in_dt'].iloc[min(dd_idx, len(df)-1)].strftime('%Y-%m-%d')}")
print(f"  Equity op piek    : EUR {dd_start_equity:,.0f}")
print(f"  Equity op diepste : EUR {dd_end_equity:,.0f}")
print(f"  FTMO daggrens     : EUR 5,000 per dag")
print(f"  FTMO totaalgrens  : EUR {CAPITAL * 0.10:,.0f} (10%)")
print(f"  Marge over        : {GREEN}EUR {CAPITAL * 0.10 - dd_eur:,.0f}{RESET}")

# ── SIGNAALTYPE PRESTATIES ───────────────────────────────────────
sec("PRESTATIES PER SIGNAALTYPE")
print(f"  {'Type':<14} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12}")
print(f"  {'-' * 14} {'-' * 8} {'-' * 7} {'-' * 14} {'-' * 12}")
for st in ["A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"]:
    sub = df[df["sig_type"] == st]
    if sub.empty:
        continue
    n = len(sub)
    wr_s = float((sub["pnl"] > 0).mean()) * 100
    tot = float(sub["pnl"].sum())
    avg = float(sub["pnl"].mean())
    print(f"  {st:<14} {n:>8} {wr_s:>6.1f}% {clr(tot, '+,.2f'):>23} {clr(avg, '+,.2f'):>21}")

# ── EQUITY CURVE ─────────────────────────────────────────────────
sec("EQUITY CURVE (ASCII)")
equities = [CAPITAL] + list(cum_eq)
mn, mx = min(equities), max(equities)
span = mx - mn if mx != mn else 1
step = max(1, len(equities) // 65)
pts = equities[::step]
rows_h = 12
target_20k = CAPITAL + 20_000 * ((END - START).days / 30)

for r in range(rows_h, -1, -1):
    threshold = mn + span * (r / rows_h)
    label = f"EUR {threshold:>10,.0f} |"
    line = "".join("#" if p >= threshold else " " for p in pts)
    print(f"  {label} {line}")

t0 = df["in_dt"].iloc[0].strftime("%Y-%m-%d")
t1 = df["uit_dt"].iloc[-1].strftime("%Y-%m-%d")
print(f"  {'':>17}{'-' * (len(pts) + 1)}")
print(f"  {'':>17}{t0}{'':>{max(1, len(pts) - 22)}}{t1}")

# ── SAMENVATTING ─────────────────────────────────────────────────
hdr("SAMENVATTING V21")
print(f"  Maandgemiddelde : {BOLD}{clr(monthly_avg, '+,.0f')} EUR/maand{RESET}")
print(f"  Max drawdown    : {RED}{max_dd:.2f}%{RESET}  (EUR {dd_eur:,.0f})")
print(f"  Win rate        : {wr:.1f}%  |  Profit factor: {pf:.2f}")
print(f"  Winst weken     : {GREEN}{winst_weken}{RESET} / Verlies weken: {RED}{verlies_weken}{RESET}  ({winst_weken / max(total_weeks,1) * 100:.0f}% positief)")
print(f"  FTMO            : {f'{GREEN}GESLAAGD{RESET}' if ftmo_ok else f'{RED}GEZAKT{RESET}'}")
print()

# Opslaan
out = Path("results/backtests")
out.mkdir(parents=True, exist_ok=True)
df.drop(columns=["in_dt", "uit_dt", "cum_pnl", "week", "month"], errors="ignore").to_csv(
    out / "trades_v21.csv", index=False
)
print(f"  Trades opgeslagen: results/backtests/trades_v21.csv")
