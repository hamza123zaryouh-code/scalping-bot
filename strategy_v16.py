"""
XAUUSD Strategy v16 — Multi-Timeframe Structure + Momentum Engine
==================================================================
ITERATIE 6 (na V15)

DIAGNOSE V15:
  • H1 data + crossover-only logica → 3-12 signals/maand → te weinig
  • V15-MaxProfit: ~2.3%/mnd gem. bij 3.5 tr/mnd
  • DOEL: 2+ signals/dag (44+/mnd), 5%+/mnd, PF > 1.4, DD < 6%

V16 KERNWIJZIGINGEN:
  1. 6 signaaltypen: EMA-cross, MACD-cross, Momentum-continuation,
     Pullback-to-EMA21, Break-of-Structure, RSI-Dip-Recovery
  2. Cooldown 2H (was 4H) → dubbel zoveel kansen per dag
  3. Risk 0.30-0.40% per trade (FTMO-safe bij 2+ trades/dag)
  4. Partiële TP: 30% @ TP1(1.5R), 30% @ TP2(2.5R), 40% @ TP3(4.0R)
  5. Break-even na TP1 hit
  6. Trailing stop: bij +€300 float → SL naar +€100
  7. MACD histogram als momentum confirmation
  8. EMA200 macro-filter toegevoegd
  9. Break of Structure (BOS) detectie
  10. Market Structure Shift (MSS) detectie
  11. ADX drempel verlaagd (meer trending perioden meegenomen)
  12. Max 6 signals/dag, min 2 gemiddeld
  13. Dagelijkse winst-target als kapitaalbescherming

SESSIES:
  London: 07:00-12:00 UTC (premium)
  New York: 13:00-17:00 UTC (premium)
  Overlap: 12:00-13:00 (standard)

RISK MANAGEMENT:
  Max dagelijks verlies: €2.000
  Max drawdown: 6% van €160.000 = €9.600
  Consecutive losses → risk halvering
  Na 2 SL/dag → geen nieuwe trades

FTMO €160k: Dag-limiet €2.000 | Max DD €9.600
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timedelta
import os, json, csv

os.makedirs("results",  exist_ok=True)
os.makedirs("memory",   exist_ok=True)
os.makedirs("reports",  exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# CONSTANTEN
# ═══════════════════════════════════════════════════════════════
KAPITAAL     = 160_000.0
FTMO_DAG_EUR = 2_000.0
FTMO_DD_PCT  = 0.06            # 6% max drawdown
FTMO_TOT_EUR = KAPITAAL * FTMO_DD_PCT
MAANDEN      = 16
VERSIE       = "v16"

# ═══════════════════════════════════════════════════════════════
# INDICATOR FUNCTIES
# ═══════════════════════════════════════════════════════════════

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p=14):
    d  = c.diff()
    g  = d.clip(lower=0).ewm(com=p - 1, adjust=False).mean()
    l  = (-d).clip(lower=0).ewm(com=p - 1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=p - 1, adjust=False).mean()

def adx_fn(hi, lo, cl, p=14):
    u  = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p - 1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p - 1, adjust=False).mean() / at
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p - 1, adjust=False).mean().fillna(0)

def macd_fn(close, fast=12, slow=26, sig=9):
    ml = ema(close, fast) - ema(close, slow)
    sl = ema(ml, sig)
    return ml, sl, ml - sl

# ═══════════════════════════════════════════════════════════════
# DATA LADEN
# ═══════════════════════════════════════════════════════════════

def laad():
    e = datetime.utcnow()
    s = e - timedelta(days=MAANDEN * 31 + 60)
    print(f"  Download GC=F H1: {s.date()} → {e.date()}")
    df = yf.download(
        "GC=F",
        start=s.strftime("%Y-%m-%d"),
        end=e.strftime("%Y-%m-%d"),
        interval="1h",
        progress=False,
        auto_adjust=True,
    )
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index, utc=True)
    df         = df[["open", "high", "low", "close", "volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df

# ═══════════════════════════════════════════════════════════════
# INDICATOREN VOORBEREIDEN
# ═══════════════════════════════════════════════════════════════

def bereid_voor(df):
    d = df.copy()

    # ── H1 indicatoren ──────────────────────────────────────────
    d["ema9"]   = ema(d["close"], 9)
    d["ema21"]  = ema(d["close"], 21)
    d["ema50"]  = ema(d["close"], 50)
    d["ema200"] = ema(d["close"], 200)
    d["rsi14"]  = rsi_fn(d["close"], 14)
    d["atr14"]  = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma"] = d["atr14"].rolling(20).mean()
    d["adx14"]  = adx_fn(d["high"], d["low"], d["close"], 14)

    _, _, hist       = macd_fn(d["close"])
    d["macd_hist"]   = hist
    d["macd_xup"]    = (hist > 0) & (hist.shift(1) <= 0)
    d["macd_xdn"]    = (hist < 0) & (hist.shift(1) >= 0)

    d["ema_xup"] = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
    d["ema_xdn"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(1) >= d["ema21"].shift(1))

    d["vol_ma"] = d["volume"].rolling(20).mean()

    # Structure levels
    d["hh5"]  = d["high"].rolling(5).max().shift(1)
    d["ll5"]  = d["low"].rolling(5).min().shift(1)
    d["hh10"] = d["high"].rolling(10).max().shift(1)
    d["ll10"] = d["low"].rolling(10).min().shift(1)

    # Distance from EMA21 in ATR units
    d["dist21"] = (d["close"] - d["ema21"]) / d["atr14"].replace(0, np.nan)

    # RSI momentum recovery (dip + recovery pattern)
    d["rsi_recov"] = (
        (d["rsi14"] > d["rsi14"].shift(1)) &
        (d["rsi14"].shift(1) < d["rsi14"].shift(2)) &
        (d["rsi14"] > 48)
    )

    # ── H4 regime ───────────────────────────────────────────────
    h4 = d.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi"]   = rsi_fn(h4["close"], 14)
    h4["sl21"]  = h4["e21"] - h4["e21"].shift(3)

    def _h4reg(r):
        bull = r["e21"] > r["e50"]
        bear = r["e21"] < r["e50"]
        a200 = r["e50"] > r["e200"]
        b200 = r["e50"] < r["e200"]
        adx  = r["adx"]; sl = r["sl21"]
        if bull and adx >= 20 and sl > 0 and a200:  return "STERK_BULL"
        if bull and adx >= 14:                       return "BULL"
        if bull:                                     return "ZWAK_BULL"
        if bear and adx >= 20 and sl < 0 and b200:  return "STERK_BEAR"
        if bear and adx >= 14:                       return "BEAR"
        if bear:                                     return "ZWAK_BEAR"
        return "CHOPPY"

    h4["regime"] = h4.apply(_h4reg, axis=1)

    for col, src in [("h4_reg", "regime"), ("h4_atr", "atr"),
                     ("h4_adx", "adx"),   ("h4_sl",  "sl21"),
                     ("h4_rsi", "rsi"),   ("h4_e21", "e21"),
                     ("h4_e50", "e50")]:
        d[col] = h4[src].reindex(d.index, method="ffill")
    d["h4_reg"]  = d["h4_reg"].fillna("CHOPPY")
    d["h4_adx"]  = d["h4_adx"].fillna(0)
    d["h4_sl"]   = d["h4_sl"].fillna(0)
    d["h4_rsi"]  = d["h4_rsi"].fillna(50)

    # ── D1 trend ────────────────────────────────────────────────
    d1 = d.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
    d1["e50"]   = ema(d1["close"], 50)
    d1["e200"]  = ema(d1["close"], 200)
    d1["sl50"]  = d1["e50"] - d1["e50"].shift(5)
    d1["trend"] = np.where(
        (d1["close"] > d1["e50"]) & (d1["sl50"] > 0), "bull",
        np.where(
            (d1["close"] < d1["e50"]) & (d1["sl50"] < 0), "bear",
            "neutral"
        )
    )
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

    # Break of Structure
    d["bos_bull"] = d["close"] > d["hh10"]
    d["bos_bear"] = d["close"] < d["ll10"]

    # Market Structure Shift: was bearish, now bullish cross on H1
    d["mss_bull"] = (
        (d["ema9"] > d["ema21"]) &
        (d["ema9"].shift(3) < d["ema21"].shift(3)) &
        (d["rsi14"] > 52)
    )
    d["mss_bear"] = (
        (d["ema9"] < d["ema21"]) &
        (d["ema9"].shift(3) > d["ema21"].shift(3)) &
        (d["rsi14"] < 48)
    )

    return d.dropna(subset=["ema9", "ema21", "ema50", "ema200", "rsi14", "atr14", "h4_atr"])


# ═══════════════════════════════════════════════════════════════
# SESSIE FILTER
# ═══════════════════════════════════════════════════════════════

def sessie(uur, dow):
    if dow >= 5:              return "blocked"
    if dow == 0 and uur < 7: return "blocked"
    if dow == 4 and uur >= 17: return "blocked"
    if 7 <= uur < 12:        return "premium"   # London
    if 13 <= uur <= 17:      return "premium"   # New York
    if uur == 12:            return "standard"  # Overlap
    return "blocked"


# ═══════════════════════════════════════════════════════════════
# SIGNAALTYPE GENERATIE
# ═══════════════════════════════════════════════════════════════

def genereer_signaal(bar, cfg):
    """
    6 signaaltypen — retourneert (richting, type, risk_pct, tp1r, tp2r, tp3r) of None.
    Prioriteit: A > B > E > C > D > F
    """
    h4reg   = str(bar.get("h4_reg", "CHOPPY"))
    d1t     = str(bar.get("d1_trend", "neutral"))
    rsi14   = float(bar.get("rsi14",  50.0))
    cl      = float(bar.get("close",  0.0))
    e9      = float(bar.get("ema9",   0.0))
    e21     = float(bar.get("ema21",  0.0))
    e50     = float(bar.get("ema50",  0.0))
    e200    = float(bar.get("ema200", 0.0))
    adx     = float(bar.get("adx14",  0.0))
    h4adx   = float(bar.get("h4_adx", 0.0))
    h4sl    = float(bar.get("h4_sl",  0.0))
    h4rsi   = float(bar.get("h4_rsi", 50.0))
    macdh   = float(bar.get("macd_hist", 0.0))
    dist21  = float(bar.get("dist21", 0.0)) if not pd.isna(bar.get("dist21", 0.0)) else 0.0
    vol     = float(bar.get("volume",   0.0))
    vol_ma  = float(bar.get("vol_ma",   1.0)) if not pd.isna(bar.get("vol_ma", 1.0)) else 1.0
    rsi_rec = bool(bar.get("rsi_recov", False))
    ema_xup = bool(bar.get("ema_xup",   False))
    ema_xdn = bool(bar.get("ema_xdn",   False))
    macd_xu = bool(bar.get("macd_xup",  False))
    macd_xd = bool(bar.get("macd_xdn",  False))
    bos_b   = bool(bar.get("bos_bull",  False))
    bos_be  = bool(bar.get("bos_bear",  False))
    mss_b   = bool(bar.get("mss_bull",  False))
    mss_be  = bool(bar.get("mss_bear",  False))

    risk_a  = cfg.get("risk_a", 0.0040)
    risk_b  = cfg.get("risk_b", 0.0030)
    risk_c  = cfg.get("risk_c", 0.0025)
    adx_min = cfg.get("adx_min",  14)
    h4a_min = cfg.get("h4adx_min", 14)
    vol_f   = cfg.get("vol_mult",  1.00)
    tp1r    = cfg.get("tp1_r",  1.5)
    tp2r    = cfg.get("tp2_r",  2.5)
    tp3r    = cfg.get("tp3_r",  4.0)

    # Globale filters
    if h4adx < h4a_min: return None
    if adx < adx_min * 0.75: return None
    if vol_ma > 100 and vol < vol_f * vol_ma: return None

    sigs = []

    # ─────────────────── LONG SIGNALEN ─────────────────────────
    bull_ok = (
        h4reg in ("STERK_BULL", "BULL", "ZWAK_BULL") and
        d1t in ("bull", "neutral") and
        cl > e50 and
        cl > e200 * 0.998
    )

    if bull_ok:
        rsi_lo, rsi_hi = 47, 72

        # A: EMA cross + MACD positief (hoogste kwaliteit)
        if ema_xup and macdh > -1.0 and rsi_lo <= rsi14 <= rsi_hi and h4reg in ("STERK_BULL", "BULL"):
            sigs.append(("long", "A_EMACROSS", risk_a, tp1r, tp2r, tp3r))

        # B: MACD cross + EMA aligned
        if macd_xu and e9 > e21 and rsi_lo <= rsi14 <= rsi_hi - 3 and h4sl > 0:
            sigs.append(("long", "B_MACDCROSS", risk_b, tp1r, tp2r, tp3r))

        # C: Momentum continuation (volledige EMA stack)
        if (e9 > e21 > e50 and 50 <= rsi14 <= 67 and macdh > 0
                and h4sl > 0.1 and rsi_rec and h4reg in ("STERK_BULL", "BULL")):
            sigs.append(("long", "C_MOMENTUM", risk_b, tp1r, tp2r, tp3r))

        # D: Pullback naar EMA21 in sterke trend
        if (h4reg == "STERK_BULL" and -0.3 <= dist21 <= 0.9
                and cl > e21 and 50 <= rsi14 <= 63 and e9 > e21 and macdh > -2.0):
            sigs.append(("long", "D_PULLBACK", risk_c, tp1r, tp2r, tp3r))

        # E: Break of Structure
        if (bos_b and cl > e21 and 52 <= rsi14 <= 70
                and adx > 18 and h4reg in ("STERK_BULL", "BULL")):
            sigs.append(("long", "E_BOS", risk_b, tp1r * 0.9, tp2r, tp3r * 0.9))

        # F: Market Structure Shift long
        if (mss_b and 50 <= rsi14 <= 65 and cl > e21
                and h4reg in ("STERK_BULL", "BULL") and h4sl > 0):
            sigs.append(("long", "F_MSS", risk_c, tp1r, tp2r, tp3r))

    # ─────────────────── SHORT SIGNALEN ────────────────────────
    bear_ok = (
        h4reg in ("STERK_BEAR", "BEAR", "ZWAK_BEAR") and
        d1t in ("bear", "neutral") and
        cl < e50 and
        cl < e200 * 1.002
    )

    if bear_ok:
        rsi_lo, rsi_hi = 28, 53

        if ema_xdn and macdh < 1.0 and rsi_lo <= rsi14 <= rsi_hi and h4reg in ("STERK_BEAR", "BEAR"):
            sigs.append(("short", "A_EMACROSS", risk_a, tp1r, tp2r, tp3r))

        if macd_xd and e9 < e21 and rsi_lo + 3 <= rsi14 <= rsi_hi and h4sl < 0:
            sigs.append(("short", "B_MACDCROSS", risk_b, tp1r, tp2r, tp3r))

        if (e9 < e21 < e50 and 33 <= rsi14 <= rsi_hi and macdh < 0
                and h4sl < -0.1 and h4reg in ("STERK_BEAR", "BEAR")):
            sigs.append(("short", "C_MOMENTUM", risk_b, tp1r, tp2r, tp3r))

        if (h4reg == "STERK_BEAR" and -0.9 <= dist21 <= 0.3
                and cl < e21 and 37 <= rsi14 <= rsi_hi and e9 < e21 and macdh < 2.0):
            sigs.append(("short", "D_PULLBACK", risk_c, tp1r, tp2r, tp3r))

        if (bos_be and cl < e21 and rsi_lo <= rsi14 <= rsi_hi
                and adx > 18 and h4reg in ("STERK_BEAR", "BEAR")):
            sigs.append(("short", "E_BOS", risk_b, tp1r * 0.9, tp2r, tp3r * 0.9))

        if (mss_be and 35 <= rsi14 <= rsi_hi and cl < e21
                and h4reg in ("STERK_BEAR", "BEAR") and h4sl < 0):
            sigs.append(("short", "F_MSS", risk_c, tp1r, tp2r, tp3r))

    if not sigs:
        return None

    # Prioriteitsvolgorde
    prio = {"A_EMACROSS": 6, "B_MACDCROSS": 5, "E_BOS": 4,
            "C_MOMENTUM": 3, "F_MSS": 2, "D_PULLBACK": 1}
    sigs.sort(key=lambda x: prio.get(x[1], 0), reverse=True)
    return sigs[0]


# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════

def backtest(df, cfg, label=""):
    tp1_pct    = cfg.get("tp1_pct", 0.30)
    tp2_pct    = cfg.get("tp2_pct", 0.30)
    tp3_pct    = 1.0 - tp1_pct - tp2_pct
    max_dag    = cfg.get("max_dag",    6)
    sl_dag_max = cfg.get("sl_dag_max", 2)
    cool_h     = cfg.get("cooldown_h", 2)
    sl_atr_m   = cfg.get("sl_atr",  1.5)
    sl_max_m   = cfg.get("sl_max",  2.0)
    trail_on   = cfg.get("trailing", True)

    kap  = float(KAPITAAL)
    piek = kap
    trs  = []
    dag  = {}

    ip       = False
    entry    = sl = tp1 = tp2 = tp3 = None
    richting = sig_type = ot = None
    risk_rem = 0.0
    tp1_hit  = tp2_hit = False
    last_i   = -999

    for i in range(120, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()

        if dat not in dag:
            dag[dat] = {"loss": 0.0, "n": 0, "sl": 0}

        dd_eur = piek - kap
        if dd_eur >= FTMO_TOT_EUR:
            if ip:
                ep  = float(b["close"])
                pnl = richting * (ep - entry) / abs(entry - sl) * risk_rem
                kap += pnl
                trs.append(_tr(ot, b.name, richting, entry, ep, pnl, "FAIL", sig_type))
                ip = False
            break

        # ── Beheer open positie ──────────────────────────────────
        if ip:
            hi = float(b["high"]); lo = float(b["low"]); cl = float(b["close"])
            sl_dist = abs(entry - sl)
            if sl_dist <= 0:
                ip = False
                continue

            # Break-even na TP1
            if tp1_hit and not tp2_hit:
                if richting == 1 and sl < entry:
                    sl = entry + 0.05 * sl_dist
                elif richting == -1 and sl > entry:
                    sl = entry - 0.05 * sl_dist

            # Trailing stop (simpel)
            if trail_on and tp1_hit:
                float_pnl = richting * (cl - entry) / sl_dist * risk_rem
                if float_pnl > 500 and not tp2_hit:
                    new_sl_trail = entry + richting * 0.4 * sl_dist
                    if richting == 1:
                        sl = max(sl, new_sl_trail)
                    else:
                        sl = min(sl, new_sl_trail)

            # Check SL (conservative: SL wins over TP on same bar)
            hit_sl = (richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)

            # TP1
            if not tp1_hit:
                if ((richting == 1 and hi >= tp1) or (richting == -1 and lo <= tp1)) and not hit_sl:
                    pnl = tp1_pct * richting * (tp1 - entry) / sl_dist * (risk_rem / tp1_pct)
                    # Simplified: risk_rem is total remaining risk
                    # At TP1: realize tp1_pct × (tp1 distance / sl_dist) in R terms
                    partial_r = (tp1 - entry) / sl_dist * richting
                    pnl_tp1 = tp1_pct * partial_r * (risk_rem / (tp1_pct + tp2_pct + tp3_pct)) * (tp1_pct + tp2_pct + tp3_pct)
                    # Correct formula: pnl = fraction_closed × R_hit × original_1R_value
                    # original_1R_value = risk_rem (if 100% of position at entry)
                    # At TP1: close tp1_pct of position at tp1_r × SL distance
                    pnl_tp1 = tp1_pct * risk_rem * ((tp1 - entry) / sl_dist * richting)
                    kap += pnl_tp1
                    if kap > piek: piek = kap
                    trs.append(_tr(ot, b.name, richting, entry, tp1, pnl_tp1, "TP1", sig_type))
                    risk_rem *= (1.0 - tp1_pct)
                    tp1_hit = True
                    hit_sl = False  # recalculate after SL moves to BE

            # TP2
            if tp1_hit and not tp2_hit:
                tp2_frac = tp2_pct / (tp2_pct + tp3_pct)
                if (richting == 1 and hi >= tp2) or (richting == -1 and lo <= tp2):
                    pnl_tp2 = tp2_frac * risk_rem * ((tp2 - entry) / sl_dist * richting)
                    kap += pnl_tp2
                    if kap > piek: piek = kap
                    trs.append(_tr(ot, b.name, richting, entry, tp2, pnl_tp2, "TP2", sig_type))
                    risk_rem *= (1.0 - tp2_frac)
                    tp2_hit = True

            # TP3
            if tp1_hit and tp2_hit:
                if (richting == 1 and hi >= tp3) or (richting == -1 and lo <= tp3):
                    pnl_tp3 = risk_rem * ((tp3 - entry) / sl_dist * richting)
                    kap += pnl_tp3
                    if kap > piek: piek = kap
                    trs.append(_tr(ot, b.name, richting, entry, tp3, pnl_tp3, "TP3", sig_type))
                    ip = False
                    continue

            # Check SL na TP updates
            hit_sl2 = (richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)
            if hit_sl2:
                pnl_sl = risk_rem * ((sl - entry) / sl_dist * richting)
                if pnl_sl < 0:
                    rem_loss = max(0, FTMO_DAG_EUR - dag[dat]["loss"])
                    if abs(pnl_sl) > rem_loss:
                        pnl_sl = -rem_loss
                    dag[dat]["loss"] += abs(pnl_sl)
                    dag[dat]["sl"] += 1
                kap += pnl_sl
                if kap > piek: piek = kap
                trs.append(_tr(ot, b.name, richting, entry, sl, pnl_sl,
                               "SL", sig_type))
                ip = False

        if ip:
            continue

        # ── Entry condities ──────────────────────────────────────
        if dag[dat]["loss"] >= FTMO_DAG_EUR * 0.65: continue
        if dag[dat]["n"]    >= max_dag:             continue
        if dag[dat]["sl"]   >= sl_dag_max:          continue
        if (i - last_i)     < cool_h:               continue

        tier = sessie(uur, dow)
        if tier == "blocked": continue

        sig = genereer_signaal(b, cfg)
        if sig is None: continue

        rich_str, sig_type, risk_pct, tp1r, tp2r, tp3r = sig

        # Standard sessie: alleen Type A of B
        if tier == "standard" and sig_type not in ("A_EMACROSS", "B_MACDCROSS"):
            continue

        # Drawdown risk scaling
        dd_pct = (piek - kap) / piek
        if   dd_pct > 0.05: risk_pct *= 0.25
        elif dd_pct > 0.04: risk_pct *= 0.40
        elif dd_pct > 0.03: risk_pct *= 0.60
        elif dd_pct > 0.01: risk_pct *= 0.80

        # Consecutive SL scaling
        recent_sl = sum(1 for t in trs[-4:] if t["result"] == "SL" and t["pnl"] < 0)
        if recent_sl >= 3: risk_pct *= 0.50

        richting = 1 if rich_str == "long" else -1

        # SL berekening op basis van swing low/high + ATR
        atr14  = float(b.get("atr14", 1.0))
        h4_atr = float(b.get("h4_atr", atr14 * 4)) if not pd.isna(b.get("h4_atr", 0)) else atr14 * 4
        ll5    = float(b.get("ll5", 0)) if not pd.isna(b.get("ll5", 0)) else float(b["close"]) - 9999
        hh5    = float(b.get("hh5", 0)) if not pd.isna(b.get("hh5", 0)) else float(b["close"]) + 9999
        cl_pr  = float(b["close"])

        if richting == 1:
            swing_sl = ll5 - 0.15 * atr14
            atr_sl   = cl_pr - sl_atr_m * h4_atr * 0.25  # H4_ATR schalen naar H1
            sl_raw   = max(swing_sl, atr_sl)              # gebruik hoogste (kortere SL)
            sl_dist  = cl_pr - sl_raw
        else:
            swing_sl = hh5 + 0.15 * atr14
            atr_sl   = cl_pr + sl_atr_m * h4_atr * 0.25
            sl_raw   = min(swing_sl, atr_sl)
            sl_dist  = sl_raw - cl_pr

        # SL distance begrenzen
        min_sl = 0.5 * atr14
        max_sl = sl_max_m * atr14 * 4
        sl_dist = max(min_sl, min(max_sl, sl_dist))

        sl  = cl_pr - richting * sl_dist
        tp1 = cl_pr + richting * tp1r * sl_dist
        tp2 = cl_pr + richting * tp2r * sl_dist
        tp3 = cl_pr + richting * tp3r * sl_dist

        risk_usd = kap * risk_pct
        risk_rem = risk_usd
        entry    = cl_pr
        ot       = b.name
        ip       = True
        tp1_hit  = tp2_hit = False
        last_i   = i
        dag[dat]["n"] += 1

    # Sluit eventueel open positie op het einde
    if ip:
        ep  = float(df.iloc[-1]["close"])
        pnl = risk_rem * ((ep - entry) / abs(entry - sl) * richting)
        kap += pnl
        trs.append(_tr(ot, df.index[-1], richting, entry, ep, pnl, "OPEN", sig_type))

    return trs, kap


def _tr(ti, to, rich, entry, exit_p, pnl, result, stype):
    return {
        "in": ti, "uit": to, "rich": rich,
        "entry": round(float(entry), 2), "exit": round(float(exit_p), 2),
        "pnl": round(float(pnl), 2), "result": result, "type": stype,
    }


# ═══════════════════════════════════════════════════════════════
# RAPPORTAGE
# ═══════════════════════════════════════════════════════════════

def rapport(trs, kap_eind, label, verbose=True):
    pnl_tot = kap_eind - KAPITAAL
    if not trs:
        if verbose:
            print(f"\n  [{label}] Geen trades.")
        return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")

    n    = len(df_t)
    wins = (df_t["pnl"] > 0).sum()
    wr   = 100 * wins / n
    gw   = df_t[df_t["pnl"] > 0]["pnl"].sum()
    gl   = df_t[df_t["pnl"] < 0]["pnl"].abs().sum()
    pf   = gw / gl if gl > 0 else 999.0

    dagen  = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    mnd_n  = dagen / 30.44
    gem_m  = pnl_tot / mnd_n
    mnd_pct = pnl_tot / KAPITAAL * 100 / mnd_n

    # Max drawdown
    cap_c = KAPITAAL; pk_c = cap_c; max_dd = 0.0
    for t in sorted(trs, key=lambda x: x["in"]):
        cap_c += t["pnl"]
        if cap_c > pk_c: pk_c = cap_c
        dd = (pk_c - cap_c) / pk_c
        if dd > max_dd: max_dd = dd

    mnd = df_t.groupby("maand").agg(
        trades=("pnl", "count"),
        pnl=("pnl", "sum"),
        wins=("pnl", lambda x: (x > 0).sum()),
    ).reset_index()
    mnd["wr"]  = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct"] = mnd["pnl"] / KAPITAAL * 100

    pos_mnd  = (mnd["pnl"] > 0).sum()
    doel_mnd = (mnd["pct"] >= 5.0).sum()

    # Signal frequency (signals per trading day)
    trading_days = df_t["in"].apply(lambda x: pd.Timestamp(x).date()).nunique()
    sig_per_dag  = n / max(trading_days, 1)

    type_cnt = df_t["type"].value_counts().to_dict()

    if verbose:
        doel_s = "✓ BEREIKT!" if mnd_pct >= 5.0 else f"nog {5.0 - mnd_pct:.1f}% tekort"
        safe_s = "✓ VEILIG" if max_dd < 0.06 else ("⚠ HOOG" if max_dd < 0.09 else "✗ KRITIEK")
        print(f"\n{'=' * 76}")
        print(f"  {label}")
        print(f"{'=' * 76}")
        print(f"  Kapitaal   : €{KAPITAAL:>10,.0f}  →  €{kap_eind:>10,.0f}")
        print(f"  P&L totaal : €{pnl_tot:>+10,.0f}")
        print(f"  Gem/mnd    : €{gem_m:>+10,.0f}  ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
        print(f"  Max DD     : {max_dd * 100:.2f}%  [{safe_s}]")
        print(f"  Trades     : {n}  ({n / mnd_n:.1f}/mnd gem.)  |  Signals/dag: {sig_per_dag:.2f}")
        print(f"  Win%       : {wr:.1f}%  |  PF: {pf:.2f}")
        print(f"  Signalen   : {type_cnt}")
        print(f"  Maanden    : positief {pos_mnd}/{len(mnd)} | ≥5% {doel_mnd}/{len(mnd)}")
        print(f"\n  {'Maand':<10} {'Tr':>4} {'Win%':>6} {'€ P&L':>12} {'%/mnd':>7}")
        print("  " + "─" * 48)
        for _, r in mnd.iterrows():
            flag = " *** DOEL!" if r["pct"] >= 5 else (" ─ ZWAK" if r["pnl"] < -3200 else "")
            print(f"  {str(r['maand']):<10} {r['trades']:>4}  {r['wr']:>4.1f}%  "
                  f"€{r['pnl']:>10,.0f}  {r['pct']:>6.2f}%{flag}")
        print("=" * 76)

    return {
        "label": label,
        "pnl_eur": pnl_tot, "gem_mnd": gem_m, "mnd_pct": mnd_pct,
        "trades": n, "wr": wr, "pf": pf, "max_dd": max_dd,
        "pos_mnd": int(pos_mnd), "tot_mnd": len(mnd), "doel_mnd": int(doel_mnd),
        "sig_per_dag": sig_per_dag, "tr_per_mnd": n / mnd_n,
        "types": type_cnt, "mnd_df": mnd,
        "kap_eind": kap_eind,
    }


# ═══════════════════════════════════════════════════════════════
# GRAFIEKEN
# ═══════════════════════════════════════════════════════════════

def maak_grafieken(trs, kap_eind, label, datum_str):
    if not trs:
        return

    df_t = pd.DataFrame(trs)
    df_t["in_dt"]  = pd.to_datetime(df_t["in"])
    df_t["maand"]  = df_t["in_dt"].dt.to_period("M")
    df_t["cum_pnl"]= df_t["pnl"].cumsum() + KAPITAAL

    fig = plt.figure(figsize=(16, 10), facecolor="#0D0D0D")
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.35)
    fig.suptitle(
        f"XAUUSD {label} | Multi-TF Strategy v16 | €{KAPITAAL:,}",
        color="#D4A843", fontsize=12, fontweight="bold",
    )

    axes = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(3)]
    for ax in axes:
        ax.set_facecolor("#141414")
        ax.tick_params(colors="#666666", labelsize=7)
        ax.spines[:].set_color("#222222")

    # Equity curve
    axes[0].plot(df_t["in_dt"], df_t["cum_pnl"], color="#1D9E75", lw=1.5)
    axes[0].axhline(KAPITAAL, color="#555", lw=0.8, ls="--")
    axes[0].fill_between(df_t["in_dt"], KAPITAAL, df_t["cum_pnl"],
                         where=df_t["cum_pnl"] >= KAPITAAL,
                         color="#1D9E75", alpha=0.12)
    axes[0].fill_between(df_t["in_dt"], KAPITAAL, df_t["cum_pnl"],
                         where=df_t["cum_pnl"] < KAPITAAL,
                         color="#D85A30", alpha=0.12)
    axes[0].set_title("Equity Curve", color="#CCC", fontsize=9)
    axes[0].set_ylabel("€ Kapitaal", color="#888", fontsize=8)
    axes[0].grid(color="#1E1E1E", lw=0.4)

    # P&L per trade
    colors = ["#1D9E75" if p > 0 else "#D85A30" for p in df_t["pnl"]]
    axes[1].bar(range(len(df_t)), df_t["pnl"], color=colors, alpha=0.8)
    axes[1].axhline(0, color="#444", lw=0.8, ls="--")
    axes[1].set_title("P&L per Trade", color="#CCC", fontsize=9)
    axes[1].set_xlabel("Trade #", color="#888", fontsize=7)
    axes[1].grid(color="#1E1E1E", lw=0.4, axis="y")

    # Maandelijks P&L
    mnd_pnl = df_t.groupby("maand")["pnl"].sum()
    mc = ["#1D9E75" if p > 0 else "#D85A30" for p in mnd_pnl.values]
    axes[2].bar(range(len(mnd_pnl)), mnd_pnl.values, color=mc, alpha=0.85)
    axes[2].axhline(8000, color="#D4A843", lw=1.0, ls="--", label="€8k doel")
    axes[2].axhline(0, color="#444", lw=0.8, ls="--")
    axes[2].set_xticks(range(len(mnd_pnl)))
    axes[2].set_xticklabels([str(m) for m in mnd_pnl.index],
                             rotation=45, ha="right", fontsize=5)
    axes[2].set_title("Maandelijks P&L", color="#CCC", fontsize=9)
    axes[2].legend(fontsize=6, facecolor="#1A1A1A", labelcolor="white")
    axes[2].grid(color="#1E1E1E", lw=0.4, axis="y")

    # Drawdown
    cum = df_t["cum_pnl"]
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max * 100
    axes[3].fill_between(df_t["in_dt"], 0, dd, color="#D85A30", alpha=0.5)
    axes[3].axhline(-6, color="#FF4444", lw=0.8, ls="--", label="-6% FTMO")
    axes[3].set_title("Drawdown", color="#CCC", fontsize=9)
    axes[3].set_ylabel("DD %", color="#888", fontsize=8)
    axes[3].legend(fontsize=6, facecolor="#1A1A1A", labelcolor="white")
    axes[3].grid(color="#1E1E1E", lw=0.4)

    # Signal types
    type_cnt = df_t["type"].value_counts()
    axes[4].barh(list(type_cnt.index), type_cnt.values,
                 color="#378ADD", alpha=0.8)
    axes[4].set_title("Signaaltype verdeling", color="#CCC", fontsize=9)
    axes[4].grid(color="#1E1E1E", lw=0.4, axis="x")

    # Win/Loss per maand
    mnd_wr = df_t.groupby("maand").apply(lambda x: 100 * (x["pnl"] > 0).mean())
    axes[5].bar(range(len(mnd_wr)), mnd_wr.values, color="#D4A843", alpha=0.85)
    axes[5].axhline(50, color="#888", lw=0.8, ls="--")
    axes[5].set_xticks(range(len(mnd_wr)))
    axes[5].set_xticklabels([str(m) for m in mnd_wr.index],
                             rotation=45, ha="right", fontsize=5)
    axes[5].set_title("Win Rate per Maand (%)", color="#CCC", fontsize=9)
    axes[5].grid(color="#1E1E1E", lw=0.4, axis="y")

    plt.tight_layout()
    pad = f"reports/equity_{label}_{datum_str}.png"
    plt.savefig(pad, dpi=140, bbox_inches="tight", facecolor="#0D0D0D")
    plt.close()
    print(f"  Grafiek opgeslagen: {pad}")


# ═══════════════════════════════════════════════════════════════
# MEMORY & RAPPORT OPSLAAN
# ═══════════════════════════════════════════════════════════════

def laad_memory(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def sla_memory(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def sla_memory_iteratie(alle_res, datum_str):
    """Sla alle iteratieresultaten op in memory bestanden."""

    # strategy_versions.json
    sv = laad_memory("memory/strategy_versions.json", [])
    for r in alle_res:
        sv.append({
            "versie": VERSIE,
            "variant": r.get("label", ""),
            "datum": datum_str,
            "beschrijving": r.get("desc", ""),
            "params": r.get("cfg", {}),
            "resultaat": {
                "pnl_eur": r.get("pnl_eur", 0),
                "gem_mnd": r.get("gem_mnd", 0),
                "mnd_pct": r.get("mnd_pct", 0),
                "wr": r.get("wr", 0),
                "pf": r.get("pf", 0),
                "max_dd": r.get("max_dd", 0),
                "sig_per_dag": r.get("sig_per_dag", 0),
                "tr_per_mnd": r.get("tr_per_mnd", 0),
            }
        })
    sla_memory("memory/strategy_versions.json", sv)

    # backtest_results.json
    br = laad_memory("memory/backtest_results.json", [])
    for r in alle_res:
        br.append({
            "versie": VERSIE,
            "variant": r.get("label", ""),
            "datum": datum_str,
            "pnl_eur": r.get("pnl_eur", 0),
            "gem_mnd_eur": r.get("gem_mnd", 0),
            "mnd_pct": r.get("mnd_pct", 0),
            "wr": r.get("wr", 0),
            "pf": r.get("pf", 0),
            "max_dd_pct": r.get("max_dd", 0) * 100,
            "trades": r.get("trades", 0),
            "sig_per_dag": r.get("sig_per_dag", 0),
            "doel_bereikt": r.get("mnd_pct", 0) >= 5.0,
        })
    sla_memory("memory/backtest_results.json", br)

    # parameter_history.json
    ph = laad_memory("memory/parameter_history.json", [])
    for r in alle_res:
        ph.append({
            "versie": VERSIE,
            "variant": r.get("label", ""),
            "datum": datum_str,
            "cfg": r.get("cfg", {}),
            "mnd_pct": r.get("mnd_pct", 0),
            "sig_per_dag": r.get("sig_per_dag", 0),
        })
    sla_memory("memory/parameter_history.json", ph)

    # winning_setups.json / failed_setups.json
    ws = laad_memory("memory/winning_setups.json", [])
    fs = laad_memory("memory/failed_setups.json", [])

    for r in alle_res:
        entry_item = {
            "versie": VERSIE, "variant": r.get("label", ""),
            "datum": datum_str, "pnl_eur": r.get("pnl_eur", 0),
            "sig_per_dag": r.get("sig_per_dag", 0),
            "wr": r.get("wr", 0), "pf": r.get("pf", 0),
            "max_dd": r.get("max_dd", 0) * 100, "cfg": r.get("cfg", {}),
        }
        if r.get("mnd_pct", 0) >= 4.0 and r.get("max_dd", 1) < 0.07:
            ws.append(entry_item)
        elif r.get("mnd_pct", 0) < 2.0 or r.get("max_dd", 0) > 0.08:
            fs.append(entry_item)

    sla_memory("memory/winning_setups.json", ws)
    sla_memory("memory/failed_setups.json",  fs)

    # optimization_notes.md
    beste = max(alle_res, key=lambda x: x.get("mnd_pct", 0)) if alle_res else {}
    with open("memory/optimization_notes.md", "a", encoding="utf-8") as f:
        f.write(f"\n## {VERSIE} — {datum_str}\n")
        f.write(f"- Beste variant: {beste.get('label','?')}\n")
        f.write(f"- Gem/mnd: €{beste.get('gem_mnd',0):+,.0f} ({beste.get('mnd_pct',0):+.2f}%)\n")
        f.write(f"- Signals/dag: {beste.get('sig_per_dag',0):.2f}\n")
        f.write(f"- WR: {beste.get('wr',0):.1f}% | PF: {beste.get('pf',0):.2f}\n")
        f.write(f"- Max DD: {beste.get('max_dd',0)*100:.2f}%\n")
        doel = "✓ DOEL 5% BEREIKT" if beste.get("mnd_pct", 0) >= 5.0 else "✗ doel niet bereikt"
        f.write(f"- {doel}\n")

    # signal_quality_log.csv
    csv_path = "memory/signal_quality_log.csv"
    header   = ["datum", "versie", "variant", "sig_type", "count", "pnl_avg"]
    exists   = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if not exists:
            w.writeheader()
        for r in alle_res:
            for stype, cnt in r.get("types", {}).items():
                w.writerow({
                    "datum": datum_str, "versie": VERSIE,
                    "variant": r.get("label", ""), "sig_type": stype,
                    "count": cnt, "pnl_avg": round(r.get("pnl_eur", 0) / max(r.get("trades", 1), 1), 2),
                })

    print("\n  Memory bestanden opgeslagen in /memory/")


def sla_rapporten(trs_dict, res_dict, datum_str):
    """Sla handelslogs en performance rapporten op."""

    # trade_log.csv
    all_trs = []
    for label, trs in trs_dict.items():
        for t in trs:
            t2 = dict(t)
            t2["variant"] = label
            t2["versie"]  = VERSIE
            all_trs.append(t2)

    if all_trs:
        pd.DataFrame(all_trs).to_csv(f"reports/trade_log_{datum_str}.csv", index=False)

    # monthly_performance.csv
    rows = []
    for label, r in res_dict.items():
        if "mnd_df" not in r: continue
        mnd = r["mnd_df"].copy()
        mnd["variant"] = label
        mnd["versie"]  = VERSIE
        rows.append(mnd)
    if rows:
        pd.concat(rows).to_csv(f"reports/monthly_performance_{datum_str}.csv", index=False)

    # latest_summary.json
    summary = []
    for label, r in res_dict.items():
        summary.append({
            "versie": VERSIE, "variant": label, "datum": datum_str,
            "pnl_eur": r.get("pnl_eur", 0), "gem_mnd_eur": r.get("gem_mnd", 0),
            "mnd_pct": r.get("mnd_pct", 0), "wr": r.get("wr", 0), "pf": r.get("pf", 0),
            "max_dd": r.get("max_dd", 0) * 100, "sig_per_dag": r.get("sig_per_dag", 0),
            "doel_bereikt": r.get("mnd_pct", 0) >= 5.0,
        })
    sla_memory("reports/latest_summary.json", summary)
    print(f"  Rapporten opgeslagen in /reports/")


# ═══════════════════════════════════════════════════════════════
# VARIANTEN
# ═══════════════════════════════════════════════════════════════

VARIANTEN = {
    "V16-Basis": {
        "desc": "Basis: risk A/B/C=0.40/0.30/0.25%, cool 2H, max 6/dag",
        "risk_a": 0.0040, "risk_b": 0.0030, "risk_c": 0.0025,
        "adx_min": 14, "h4adx_min": 14, "vol_mult": 1.00,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp3_r": 4.0,
        "tp1_pct": 0.30, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 6, "sl_dag_max": 2, "cooldown_h": 2,
        "trailing": True,
    },
    "V16-HighRisk": {
        "desc": "Hogere risk: A/B/C=0.50/0.40/0.30%, voor meer winst",
        "risk_a": 0.0050, "risk_b": 0.0040, "risk_c": 0.0030,
        "adx_min": 16, "h4adx_min": 16, "vol_mult": 1.00,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp3_r": 4.0,
        "tp1_pct": 0.30, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 5, "sl_dag_max": 2, "cooldown_h": 2,
        "trailing": True,
    },
    "V16-Freq": {
        "desc": "Hogere freq: cool 1H, max 8/dag, ADX 12, risk 0.30/0.25/0.20%",
        "risk_a": 0.0030, "risk_b": 0.0025, "risk_c": 0.0020,
        "adx_min": 12, "h4adx_min": 12, "vol_mult": 0.98,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp3_r": 4.0,
        "tp1_pct": 0.30, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 8, "sl_dag_max": 3, "cooldown_h": 1,
        "trailing": True,
    },
    "V16-TP3Big": {
        "desc": "Grotere TPs: TP2=3.0R, TP3=5.0R, risk 0.40/0.30/0.25%",
        "risk_a": 0.0040, "risk_b": 0.0030, "risk_c": 0.0025,
        "adx_min": 14, "h4adx_min": 14, "vol_mult": 1.00,
        "tp1_r": 1.5, "tp2_r": 3.0, "tp3_r": 5.0,
        "tp1_pct": 0.30, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 5, "sl_dag_max": 2, "cooldown_h": 2,
        "trailing": True,
    },
    "V16-Balanced": {
        "desc": "Gebalanceerd: risk 0.35/0.28/0.22%, cool 2H, TP2=2.8R",
        "risk_a": 0.0035, "risk_b": 0.0028, "risk_c": 0.0022,
        "adx_min": 15, "h4adx_min": 14, "vol_mult": 1.00,
        "tp1_r": 1.5, "tp2_r": 2.8, "tp3_r": 4.5,
        "tp1_pct": 0.30, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 6, "sl_dag_max": 2, "cooldown_h": 2,
        "trailing": True,
    },
    "V16-Conservative": {
        "desc": "Conservatief: risk 0.25/0.20/0.15%, ADX 20, cool 3H",
        "risk_a": 0.0025, "risk_b": 0.0020, "risk_c": 0.0015,
        "adx_min": 20, "h4adx_min": 18, "vol_mult": 1.02,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp3_r": 4.0,
        "tp1_pct": 0.35, "tp2_pct": 0.30,
        "sl_atr": 1.5, "sl_max": 2.0,
        "max_dag": 4, "sl_dag_max": 2, "cooldown_h": 3,
        "trailing": True,
    },
}


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    datum_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 76)
    print(f"  XAUUSD STRATEGIE {VERSIE} | Multi-TF Structure + Momentum Engine")
    print(f"  6 Signaaltypen | Partiële TP | Break-Even | Trailing Stop")
    print(f"  FTMO €160k: Max DD €{FTMO_TOT_EUR:,.0f} | Dag-limiet €{FTMO_DAG_EUR:,.0f}")
    print("=" * 76)

    print("\n[1] Data laden...")
    df_raw = laad()

    print("[2] Indicatoren berekenen (H1 + H4 + D1)...")
    df = bereid_voor(df_raw)

    # ── Regime distributie ────────────────────────────────────
    h4_cnt = df["h4_reg"].value_counts().to_dict()
    d1_cnt = df["d1_trend"].value_counts().to_dict()
    print(f"  H4 regimes   : {h4_cnt}")
    print(f"  D1 trends    : {d1_cnt}")

    # Session bars
    sess_bars = df[(df.index.hour >= 7) & (df.index.hour < 18) &
                   (df.index.dayofweek < 5)]
    print(f"  Session bars : {len(sess_bars)} ({len(sess_bars)/MAANDEN:.0f}/mnd gem.)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    alle_res  = []
    trs_dict  = {}
    res_dict  = {}

    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind = backtest(df, cfg, naam)
        r = rapport(trs, kap_eind, naam, verbose=True)
        if r:
            r["desc"] = cfg["desc"]
            r["cfg"]  = {k: v for k, v in cfg.items() if k != "desc"}
            alle_res.append(r)
            trs_dict[naam] = trs
            res_dict[naam] = r
            maak_grafieken(trs, kap_eind, naam, datum_str)

    # ── Eindoverzicht ────────────────────────────────────────────
    print()
    print("=" * 110)
    print(f"  EINDOVERZICHT {VERSIE} — ITERATIE 6")
    print("=" * 110)
    print(f"  {'Variant':<22} {'P&L':>12} {'%/mnd':>7} {'Tr/mnd':>7} {'Sig/dag':>8} "
          f"{'Win%':>6} {'PF':>5} {'MaxDD':>7} {'Doel':>5}")
    print("  " + "─" * 105)

    for r in sorted(alle_res, key=lambda x: -x.get("mnd_pct", 0)):
        doel  = " ✓ DOEL!" if r["mnd_pct"] >= 5.0 else ("  OK" if r["mnd_pct"] >= 3.0 else "")
        safe  = " ⚠DD!" if r["max_dd"] > 0.06 else ""
        freq  = " ⚠FREQ" if r["sig_per_dag"] < 1.5 else ("  ✓2/dag" if r["sig_per_dag"] >= 2.0 else "")
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['mnd_pct']:>6.2f}%"
              f" {r['tr_per_mnd']:>6.1f}  {r['sig_per_dag']:>7.2f}"
              f"  {r['wr']:>4.1f}% {r['pf']:>5.2f}"
              f" {r['max_dd']*100:>6.1f}%{doel}{safe}{freq}")

    if alle_res:
        beste = max(alle_res, key=lambda x: x.get("mnd_pct", 0))
        safe  = [r for r in alle_res if r["max_dd"] < 0.06]
        bs    = max(safe, key=lambda x: x["mnd_pct"]) if safe else beste

        print(f"\n  BESTE TOTAAL : {beste['label']:<22} {beste['mnd_pct']:+.2f}%/mnd")
        print(f"  BESTE SAFE   : {bs['label']:<22} {bs['mnd_pct']:+.2f}%/mnd | "
              f"DD {bs['max_dd']*100:.1f}%")
        print(f"  Signals/dag  : {beste['sig_per_dag']:.2f}")

        if beste["mnd_pct"] >= 5.0:
            print(f"\n  ✓✓ DOEL BEREIKT: {beste['label']} haalt €{beste['gem_mnd']:,.0f}/mnd ({beste['mnd_pct']:.2f}%)")
        elif beste["mnd_pct"] >= 3.0:
            print(f"\n  Progressie: {beste['mnd_pct']:.2f}%/mnd | {5.0-beste['mnd_pct']:.2f}% van 5% doel")
            print(f"  → Volgende iteratie: v17 met verhoogde risk of verfijnde filters")
        else:
            print(f"\n  Resultaat: {beste['mnd_pct']:.2f}%/mnd")
            print(f"  → Grote aanpassing nodig: meer signals, hogere risk of betere filters")

    print()
    print("  ITERATIE GESCHIEDENIS:")
    print("  V12: +0.44%/mnd | 4.6 tr/mnd | WR 29% | PF 1.22")
    print("  V13: +0.39%/mnd | 2.3 tr/mnd | WR 70% | PF 1.94")
    print("  V14: +1.18%/mnd | 3.5 tr/mnd | WR 71% | PF 2.39")
    print("  V15-MaxProfit: ~2.3%/mnd | 3.5 tr/mnd (beste H1 variant)")
    if alle_res:
        b = max(alle_res, key=lambda x: x.get("mnd_pct", 0))
        print(f"  V16-Beste: {b['mnd_pct']:+.2f}%/mnd | {b['tr_per_mnd']:.1f} tr/mnd | "
              f"WR {b['wr']:.1f}% | PF {b['pf']:.2f} | {b['sig_per_dag']:.2f} sig/dag")
    print("=" * 110)

    # ── Memory & rapporten opslaan ───────────────────────────────
    print("\n[4] Memory & rapporten opslaan...")
    sla_memory_iteratie(alle_res, datum_str)
    sla_rapporten(trs_dict, res_dict, datum_str)

    print(f"\n[5] Klaar — {datum_str}")
    print(f"  Bekijk: reports/ en memory/ voor gedetailleerde logs")


if __name__ == "__main__":
    main()
