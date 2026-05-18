"""
XAUUSD V22 Multi-Paar Backtest - XAUUSD + EURUSD + GBPUSD
Doel: EUR 16k+/maand, min 2 posities/dag, geen verlies weken
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.services.backtest_service import BacktestService, SYMBOL_SPECS
from core.strategy_engine import V22_CFG

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"

CAPITAL   = 160_000.0
SYMBOLS   = ["XAUUSD", "EURUSD", "GBPUSD"]
START     = date(2025, 10, 1)
END       = date(2026, 5, 18)
N_DAYS    = (END - START).days
MONTHLY_TARGET = 16_000.0


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


# ── HEADER ────────────────────────────────────────────────────────
hdr(f"V22 MULTI-PAAR BACKTEST  |  Doel: EUR {MONTHLY_TARGET:,.0f}+/maand")
print(f"  Paren          : {', '.join(SYMBOLS)}")
print(f"  Startkapitaal  : {BOLD}EUR {CAPITAL:,.0f}{RESET}")
print(f"  Periode        : {START} -> {END} ({N_DAYS} dagen)")
print(f"  Risico         : 1.2% / 0.95% / 0.75% per signaaltype")
print(f"  Bescherming    : Weekly stop -2%, dagwinst-lock +2.5%")
print(f"  Max gelijktijdig: 2 posities over alle paren")

svc = BacktestService()
cfg = dict(V22_CFG)

print(f"\n  Data laden voor {len(SYMBOLS)} paren...")

try:
    trades, final_cap = svc.run_multi_symbol(SYMBOLS, START, END, CAPITAL, cfg)
except Exception as e:
    print(f"\n{RED}FOUT: {e}{RESET}")
    sys.exit(1)

if not trades:
    print(f"{RED}Geen trades gegenereerd.{RESET}")
    sys.exit(1)

# ── VERWERK TRADES ────────────────────────────────────────────────
df = pd.DataFrame(trades)
df["in_dt"]  = pd.to_datetime(df["in"],  utc=True, errors="coerce")
df["uit_dt"] = pd.to_datetime(df["uit"], utc=True, errors="coerce")
df["pnl"]    = df["pnl"].astype(float)

start_ts = pd.Timestamp(START, tz="UTC")
df = df[df["in_dt"] >= start_ts].reset_index(drop=True)

# Paar uit type-veld halen (formaat "XAUUSD:B_MACDCROSS" of gewoon "B_MACDCROSS")
def extract_pair(t: str) -> str:
    if ":" in str(t):
        sym = str(t).split(":")[0]
        return sym if sym in SYMBOL_SPECS else "XAUUSD"
    return "XAUUSD"

def extract_sig(t: str) -> str:
    if ":" in str(t):
        return str(t).split(":", 1)[1]
    return str(t)

df["pair"]     = df["type"].apply(extract_pair)
df["sig_type"] = df["type"].apply(extract_sig)
df["cum_pnl"]  = df["pnl"].cumsum()
df["week"]     = df["in_dt"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
df["month"]    = df["in_dt"].dt.to_period("M").astype(str)
df["day"]      = df["in_dt"].dt.date

# ── GLOBALE STATISTIEKEN ─────────────────────────────────────────
total_pnl   = float(df["pnl"].sum())
n_trades    = len(df)
wins        = df["pnl"][df["pnl"] > 0]
losses      = df["pnl"][df["pnl"] < 0]
wr          = float((df["pnl"] > 0).mean()) * 100
pf          = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
cum_eq      = df["pnl"].cumsum() + CAPITAL
peak        = cum_eq.cummax()
dd_series   = (peak - cum_eq) / peak * 100
max_dd      = float(dd_series.max())
monthly_avg = total_pnl / max(N_DAYS / 30, 1)
daily_avg   = total_pnl / max(N_DAYS, 1)
ftmo_ok     = max_dd < 10.0

# Dagen met min 2 trades
days_2plus = int((df.groupby("day")["pnl"].count() >= 2).sum())
total_active_days = df["day"].nunique()

sec("GLOBALE STATISTIEKEN")
stats = [
    ("Totale winst",       f"{clr(total_pnl, '+,.0f')} EUR"),
    ("Eindsaldo",          f"EUR {CAPITAL + total_pnl:,.0f}"),
    ("Maandgemiddelde",    f"{clr(monthly_avg, '+,.0f')} EUR/maand"),
    ("Daggemiddelde",      f"{clr(daily_avg, '+,.0f')} EUR/dag"),
    ("Totaal trades",      f"{n_trades}  ({n_trades / max(N_DAYS/7, 1):.1f}/week)"),
    ("Dagen >= 2 trades",  f"{GREEN}{days_2plus}{RESET} / {total_active_days} actieve dagen ({days_2plus/max(total_active_days,1)*100:.0f}%)"),
    ("Win rate",           f"{wr:.1f}%"),
    ("Profit factor",      f"{pf:.2f}"),
    ("Max drawdown",       f"{RED if max_dd > 6 else GREEN}{max_dd:.2f}%{RESET}  (EUR {(peak.iloc[dd_series.argmax()]-cum_eq.iloc[dd_series.argmax()]):.0f})"),
    ("FTMO status",        f"{GREEN}GESLAAGD{RESET}" if ftmo_ok else f"{RED}GEZAKT{RESET}"),
    ("Maanddoel >= 16k",   f"{GREEN}JA{RESET}" if monthly_avg >= MONTHLY_TARGET else f"{YELLOW}Gedeeltelijk{RESET}"),
]
for label, val in stats:
    print(f"  {label:<26} {val}")

# ── PER-PAAR STATISTIEKEN ────────────────────────────────────────
sec("PRESTATIES PER PAAR")
print(f"  {'Paar':<10} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12} {'Bijdrage':>10}")
print(f"  {'-'*10} {'-'*8} {'-'*7} {'-'*14} {'-'*12} {'-'*10}")
for pair in SYMBOLS:
    sub = df[df["pair"] == pair]
    if sub.empty:
        print(f"  {pair:<10} {'(geen trades)':>40}")
        continue
    n = len(sub)
    wr_p = float((sub["pnl"] > 0).mean()) * 100
    tot  = float(sub["pnl"].sum())
    avg  = float(sub["pnl"].mean())
    pct  = tot / max(abs(total_pnl), 1) * 100
    print(f"  {pair:<10} {n:>8} {wr_p:>6.1f}% {clr(tot, '+,.0f'):>23} {clr(avg, '+,.0f'):>21} {pct:>9.1f}%")

# ── WEEKOVERZICHT ────────────────────────────────────────────────
sec("WEEKOVERZICHT")
print(f"  {'Week':<12} {'Trades':>7} {'WR%':>5} {'P&L':>12} {'Week%':>7} {'Cum P&L':>14} {'Status':>9}")
print(f"  {'-'*12} {'-'*7} {'-'*5} {'-'*12} {'-'*7} {'-'*14} {'-'*9}")

wk_eq = CAPITAL
cum_w = 0.0
winst_weken = verlies_weken = 0

for wk, grp in df.groupby("week"):
    wpnl = float(grp["pnl"].sum())
    cum_w += wpnl
    wk_end = wk_eq + wpnl
    wret   = wpnl / max(wk_eq, 1) * 100
    n_w    = len(grp)
    wr_w   = float((grp["pnl"] > 0).mean()) * 100
    if wpnl > 0:
        status = f"{GREEN}WIN{RESET}"; winst_weken += 1
    elif wpnl < 0:
        status = f"{RED}VERLIES{RESET}"; verlies_weken += 1
    else:
        status = f"{YELLOW}FLAT{RESET}"
    print(
        f"  {str(wk):<12} "
        f"{n_w:>7} "
        f"{wr_w:>4.0f}% "
        f"{clr(wpnl, '+,.0f'):>21} "
        f"{clr(wret, '+.1f'):>14}% "
        f"{clr(cum_w, '+,.0f'):>23} "
        f"  {status}"
    )
    wk_eq = wk_end

total_weeks = winst_weken + verlies_weken
print(f"\n  Winst weken  : {GREEN}{winst_weken}{RESET} / Verlies weken: {RED}{verlies_weken}{RESET} "
      f"({winst_weken/max(total_weeks,1)*100:.0f}% positief)")

# ── MAANDOVERZICHT ───────────────────────────────────────────────
sec("MAANDOVERZICHT")
print(f"  {'Maand':<10} {'Trades':>7} {'P&L':>14} {'Return%':>9} {'Max DD%':>9} {'Status':>12}")
print(f"  {'-'*10} {'-'*7} {'-'*14} {'-'*9} {'-'*9} {'-'*12}")

m_eq = CAPITAL
for mo, mgrp in df.groupby("month"):
    mpnl = float(mgrp["pnl"].sum())
    mret = mpnl / max(m_eq, 1) * 100
    m_cum = mgrp["pnl"].cumsum() + m_eq
    m_peak = m_cum.cummax()
    m_dd = float(((m_peak - m_cum) / m_peak * 100).max()) if len(m_cum) > 0 else 0.0
    n_m = len(mgrp)
    if mpnl >= MONTHLY_TARGET:
        status = f"{GREEN}IN DOEL{RESET}"
    elif mpnl >= MONTHLY_TARGET * 0.5:
        status = f"{YELLOW}HALF{RESET}"
    elif mpnl >= 0:
        status = f"{YELLOW}TE LAAG{RESET}"
    else:
        status = f"{RED}VERLIES{RESET}"
    print(
        f"  {str(mo):<10} {n_m:>7} "
        f"{clr(mpnl, '+,.0f'):>23} "
        f"{clr(mret, '+.1f'):>16}% "
        f"{m_dd:>8.2f}%  "
        f" {status}"
    )
    m_eq += mpnl

# ── SIGNAALTYPE PRESTATIES ───────────────────────────────────────
sec("PRESTATIES PER SIGNAALTYPE (alle paren)")
sigs = ["A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"]
print(f"  {'Type':<14} {'Trades':>8} {'Win%':>7} {'Totaal P&L':>14} {'Gem/trade':>12}")
print(f"  {'-'*14} {'-'*8} {'-'*7} {'-'*14} {'-'*12}")
for st in sigs:
    sub = df[df["sig_type"] == st]
    if sub.empty:
        continue
    n = len(sub)
    wr_s = float((sub["pnl"] > 0).mean()) * 100
    tot  = float(sub["pnl"].sum())
    avg  = float(sub["pnl"].mean())
    print(f"  {st:<14} {n:>8} {wr_s:>6.1f}% {clr(tot, '+,.0f'):>23} {clr(avg, '+,.0f'):>21}")

# ── DAGELIJKSE ACTIVITEIT ─────────────────────────────────────────
sec("DAGELIJKSE ACTIVITEIT (trades per dag distributie)")
day_counts = df.groupby("day")["pnl"].count()
dist = day_counts.value_counts().sort_index()
for n_trades_day, count in dist.items():
    bar_len = int(count / max(dist.max(), 1) * 30)
    marker = f"{GREEN}[{RESET}" if n_trades_day >= 2 else f"  "
    print(f"  {n_trades_day} trade(s)/dag: {count:>3}x  {marker}{'#' * bar_len}")

# ── MAX DRAWDOWN DETAIL ──────────────────────────────────────────
sec("MAX DRAWDOWN DETAIL")
dd_idx = int(dd_series.idxmax())
dd_eur = float(peak.iloc[dd_idx] - cum_eq.iloc[dd_idx])
print(f"  Max drawdown      : {RED}{max_dd:.2f}%{RESET}  =  EUR {dd_eur:,.0f}")
print(f"  Op datum          : {df['in_dt'].iloc[min(dd_idx, len(df)-1)].strftime('%Y-%m-%d')}")
print(f"  FTMO totaalgrens  : EUR {CAPITAL*0.10:,.0f}")
print(f"  Marge over        : {GREEN}EUR {CAPITAL*0.10 - dd_eur:,.0f}{RESET}")

# ── EQUITY CURVE ─────────────────────────────────────────────────
sec("EQUITY CURVE (ASCII)")
equities = [CAPITAL] + list(cum_eq)
mn, mx = min(equities), max(equities)
span = mx - mn if mx != mn else 1
step = max(1, len(equities) // 65)
pts  = equities[::step]
rows_h = 12

for r in range(rows_h, -1, -1):
    threshold = mn + span * (r / rows_h)
    line = "".join("#" if p >= threshold else " " for p in pts)
    print(f"  EUR {threshold:>10,.0f} | {line}")

t0 = df["in_dt"].iloc[0].strftime("%Y-%m-%d")
t1 = df["uit_dt"].iloc[-1].strftime("%Y-%m-%d")
print(f"  {'':>17}{'-' * (len(pts) + 1)}")
print(f"  {'':>17}{t0}{'':>{max(1, len(pts) - 22)}}{t1}")

# ── SAMENVATTING ─────────────────────────────────────────────────
hdr("SAMENVATTING V22 MULTI-PAAR")
print(f"  Paren           : {', '.join(SYMBOLS)}")
print(f"  Maandgemiddelde : {BOLD}{clr(monthly_avg, '+,.0f')} EUR/maand{RESET}  "
      f"({'IN DOEL' if monthly_avg >= MONTHLY_TARGET else 'ONDER DOEL'})")
print(f"  Max drawdown    : {RED}{max_dd:.2f}%{RESET}  (EUR {dd_eur:,.0f})")
print(f"  Win rate        : {wr:.1f}%  |  Profit factor: {pf:.2f}")
print(f"  Trades/week     : {n_trades / max(N_DAYS/7, 1):.1f}  "
      f"|  Dagen >= 2 trades: {days_2plus/max(total_active_days,1)*100:.0f}%")
print(f"  Winst weken     : {GREEN}{winst_weken}{RESET} / Verlies weken: {RED}{verlies_weken}{RESET}  "
      f"({winst_weken/max(total_weeks,1)*100:.0f}% positief)")
print(f"  FTMO            : {f'{GREEN}GESLAAGD{RESET}' if ftmo_ok else f'{RED}GEZAKT{RESET}'}")
print()

# Opslaan
out = Path("results/backtests")
out.mkdir(parents=True, exist_ok=True)
df.drop(columns=["in_dt", "uit_dt", "cum_pnl", "week", "month", "day"], errors="ignore").to_csv(
    out / "trades_v22_multi.csv", index=False
)
print(f"  Trades opgeslagen: results/backtests/trades_v22_multi.csv")
