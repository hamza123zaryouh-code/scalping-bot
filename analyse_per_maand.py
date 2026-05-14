"""Per-maand overzicht: max winst / max verlies / netto P&L in EUR — V11 ADX20"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta

KAPITAAL = 160_000.0
EUR_RATE = 1.17
FTMO_DAG = 8_000.0 * EUR_RATE
FTMO_TOT = 16_000.0 * EUR_RATE
MAANDEN  = 13

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rsi_fn(c, p=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))
def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([(hi-lo), (hi-cl.shift(1)).abs(), (lo-cl.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(com=p-1, adjust=False).mean()
def adx_fn(hi, lo, cl, p=14):
    u = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u; mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p-1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p-1, adjust=False).mean() / at
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p-1, adjust=False).mean().fillna(0)

# Data laden
e = datetime.utcnow(); s = e - timedelta(days=MAANDEN*31 + 30)
print("  Data laden (GC=F H1)...")
df = yf.download("GC=F", start=s.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"),
                 interval="1h", progress=False, auto_adjust=True)
df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
df.index = pd.to_datetime(df.index, utc=True)
df = df[["open","high","low","close","volume"]].dropna()

# Indicatoren
d = df.copy()
d["rsi14"] = rsi_fn(d["close"], 14)
d["rsi14_p"] = d["rsi14"].shift(1)
d["ema21"] = ema(d["close"], 21)
d["atr_h1"] = atr_fn(d["high"], d["low"], d["close"], 14)
d["atr_ma20"] = d["atr_h1"].rolling(20).mean()

h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
h4["e21"] = ema(h4["close"], 21); h4["e50"] = ema(h4["close"], 50); h4["e200"] = ema(h4["close"], 200)
h4["slope"] = h4["e21"] - h4["e21"].shift(3)
h4["adx"] = adx_fn(h4["high"], h4["low"], h4["close"], 14)
h4["atr"] = atr_fn(h4["high"], h4["low"], h4["close"], 14)

def regime(row):
    bull = row["e21"] > row["e50"]; bear = row["e21"] < row["e50"]
    if bull and row["adx"] >= 25 and row["slope"] > 0 and row["e50"] > row["e200"]: return "STERK_BULL"
    elif bull and row["adx"] >= 15: return "ZWAK_BULL"
    elif bear and row["adx"] >= 25 and row["slope"] < 0 and row["e50"] < row["e200"]: return "STERK_BEAR"
    elif bear and row["adx"] >= 15: return "ZWAK_BEAR"
    else: return "CHOPPY"

h4["regime"] = h4.apply(regime, axis=1)
d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
d["h4_adx"] = h4["adx"].reindex(d.index, method="ffill").fillna(0)
d["h4_atr"] = h4["atr"].reindex(d.index, method="ffill")

d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
d1["de50"] = ema(d1["close"], 50); d1["de200"] = ema(d1["close"], 200)
d1["trend"] = np.where(
    (d1["close"] > d1["de50"]) & (d1["de50"] > d1["de200"]), "bull",
    np.where((d1["close"] < d1["de50"]) & (d1["de50"] < d1["de200"]), "bear", "neutral")
)
d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bull")
d = d.dropna(subset=["rsi14","ema21","atr_h1","h4_atr","h4_regime"])

def sessie(uur, dow):
    if dow == 0 and uur < 10: return "blocked"
    if dow == 4 and uur >= 14: return "blocked"
    if 8 <= uur < 12 or 13 <= uur < 17: return "premium"
    if 7 <= uur < 8 or 17 <= uur < 19: return "standard"
    return "blocked"

# Backtest (V11 ADX20 parameters)
kap = KAPITAAL * EUR_RATE; piek = kap
trs = []; dag_info = {}
ip = False
entry = sl = tp = sla = risk_usd = richting = sig_type = ot = None

for i in range(50, len(d)):
    b = d.iloc[i]; dat = b.name.date(); uur = b.name.hour; dow = b.name.weekday()
    if dat not in dag_info:
        dag_info[dat] = {"verlies": 0.0, "ns": 0, "nw": 0}

    if (piek - kap) >= FTMO_TOT:
        if ip:
            exit_p = float(b["close"])
            pnl_usd = richting * (exit_p - entry) / sla * risk_usd
            kap += pnl_usd
            trs.append({"in": ot, "uit": b.name, "pnl_usd": pnl_usd,
                        "pnl_eur": pnl_usd / EUR_RATE, "result": "FAIL", "type": sig_type})
            ip = False
        break

    if ip:
        cur = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])
        if richting == 1  and (cur - entry) >= sla and sl < entry: sl = entry
        if richting == -1 and (entry - cur) >= sla and sl > entry: sl = entry
        hit_sl = (richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)
        hit_tp = (richting == 1 and hi >= tp) or (richting == -1 and lo <= tp)
        if hit_sl or hit_tp:
            exit_p = tp if hit_tp else sl
            pnl_usd = richting * (exit_p - entry) / sla * risk_usd
            if pnl_usd < 0:
                dv = dag_info[dat]["verlies"]
                if dv + abs(pnl_usd) > FTMO_DAG:
                    pnl_usd = -(FTMO_DAG - dv)
                dag_info[dat]["verlies"] += abs(pnl_usd)
            kap += pnl_usd
            if kap > piek: piek = kap
            trs.append({"in": ot, "uit": b.name, "pnl_usd": pnl_usd,
                        "pnl_eur": pnl_usd / EUR_RATE, "result": "TP" if hit_tp else "SL", "type": sig_type})
            ip = False

    if ip: continue
    dv = dag_info[dat]["verlies"]; ns = dag_info[dat]["ns"]; nw = dag_info[dat]["nw"]
    tier = sessie(uur, dow)
    if tier == "blocked" or dv >= FTMO_DAG * 0.65: continue

    regime_v = b["h4_regime"]
    if regime_v == "CHOPPY" or b["d1_trend"] == "neutral": continue

    rsi14 = float(b["rsi14"]); rsi14_p = float(b["rsi14_p"]) if not pd.isna(b["rsi14_p"]) else rsi14
    close = float(b["close"]); ema21_v = float(b["ema21"])
    atr_h1 = float(b["atr_h1"]); atr_h4 = float(b["h4_atr"])
    atr_ma = float(b["atr_ma20"]) if not pd.isna(b["atr_ma20"]) else atr_h1
    h4_adx_v = float(b["h4_adx"])

    if atr_h4 < 5.0 or atr_h1 > 2.5 * atr_ma or h4_adx_v < 20: continue

    long_ok  = (rsi14_p < 50) and (rsi14 >= 50) and (close > ema21_v)
    short_ok = (rsi14_p > 50) and (rsi14 <= 50) and (close < ema21_v)
    sterk = regime_v in ("STERK_BULL", "STERK_BEAR")
    sig = None

    if long_ok and regime_v in ("STERK_BULL", "ZWAK_BULL") and b["d1_trend"] == "bull":
        if sterk and ns < 3: sig = ("long", "STERK_LONG", 0.012, 3.0)
        elif not sterk and nw < 2 and tier == "premium": sig = ("long", "ZWAK_LONG", 0.007, 2.0)
    elif short_ok and regime_v in ("STERK_BEAR", "ZWAK_BEAR") and b["d1_trend"] == "bear":
        if sterk and ns < 3: sig = ("short", "STERK_SHORT", 0.012, 3.0)

    if not sig: continue
    if tier == "standard" and "ZWAK" in sig[1]: continue

    richting_str, sig_type, risk_pct, tp_r = sig
    richting = 1 if richting_str == "long" else -1
    entry = close; sla = 0.5 * atr_h4; sl = entry - richting * sla; tp = entry + richting * tp_r * sla
    dd_pct = (piek - kap) / piek
    if dd_pct > 0.06: risk_pct *= 0.40
    elif dd_pct > 0.03: risk_pct *= 0.65
    risk_usd = kap * risk_pct; ot = b.name; ip = True
    if sterk: dag_info[dat]["ns"] += 1
    else: dag_info[dat]["nw"] += 1

# Rapport
df_t = pd.DataFrame(trs)
df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
df_t["pnl_eur"] = df_t["pnl_eur"].astype(float)

print()
print("=" * 76)
print("  V11 ADX20 — PER MAAND: MAX WINST / MAX VERLIES / NETTO (EUR)")
print("  FTMO account: €160.000  |  Dag-limiet: €8.000  |  Totaal: €16.000")
print("=" * 76)
print(f"  {'Maand':<10} {'Trades':>6}  {'Max WINST':>11}  {'Max VERLIES':>12}  {'Netto P&L':>11}  {'%':>7}  Oordeel")
print("  " + "-" * 74)

totaal_pnl = 0.0
for maand, grp in df_t.groupby("maand"):
    n = len(grp)
    max_w = grp["pnl_eur"].max()
    max_v = grp["pnl_eur"].min()
    netto = grp["pnl_eur"].sum()
    pct_mnd = netto / KAPITAAL * 100
    totaal_pnl += netto

    if netto >= 8000:  oordeel = "*** FTMO DOEL GEHAALD!"
    elif netto >= 4800: oordeel = "++ EXCELLENT (>3%)"
    elif netto >= 3200: oordeel = "+  GOED (>2%)"
    elif netto > 0:    oordeel = "+  POSITIEF"
    elif netto >= -3200: oordeel = "-  KLEIN VERLIES"
    else:              oordeel = "-- ZWAAR VERLIES"

    print(f"  {str(maand):<10} {n:>6}  €{max_w:>+9,.0f}  €{max_v:>+10,.0f}  €{netto:>+9,.0f}  {pct_mnd:>+6.2f}%  {oordeel}")

print("  " + "-" * 74)
all_max_w = df_t["pnl_eur"].max()
all_max_v = df_t["pnl_eur"].min()
print(f"  {'TOTAAL':<10} {len(df_t):>6}  €{all_max_w:>+9,.0f}  €{all_max_v:>+10,.0f}  €{totaal_pnl:>+9,.0f}  {totaal_pnl/KAPITAAL*100:>+6.2f}%")
print("=" * 76)
print()
print("  SAMENVATTING:")
mnd_grp = df_t.groupby("maand")["pnl_eur"].sum()
print(f"  Beste maand netto  : €{mnd_grp.max():+,.0f} ({mnd_grp.idxmax()})")
print(f"  Slechtste maand    : €{mnd_grp.min():+,.0f} ({mnd_grp.idxmin()})")
print(f"  Beste trade        : €{all_max_w:+,.0f}")
print(f"  Slechtste trade    : €{all_max_v:+,.0f}")
print(f"  Positieve maanden  : {(mnd_grp > 0).sum()}/{len(mnd_grp)}")
print(f"  Maanden >= 5%      : {(mnd_grp >= KAPITAAL*0.05).sum()}/{len(mnd_grp)}")
print(f"  FTMO Dag-limiet    : €8.000 per dag (max verlies op 1 dag)")
print(f"  FTMO Totaal-limiet : €16.000 totaal")
print("=" * 76)
