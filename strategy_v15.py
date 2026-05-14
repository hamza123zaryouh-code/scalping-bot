"""
XAUUSD Strategy v15 — Momentum State Engine (MSE)
==================================================
ITERATIE 5 ANALYSE (na V14):

DIAGNOSE V14:
  • WR 71%, PF 2.39 — signalen zijn UITSTEKEND kwaliteit
  • 3.5 trades/mnd → 1.18%/mnd — nog steeds te weinig
  • September 2025: 8 trades → 5.7% BEWIJST het kan bij hogere freq.
  • BUG: Signal C en D genereerden NULA trades (elif prioriteit fout)
  • Signal B RSI-pullback te restrictief (precise crossover vereist)

V15 KERNWIJZIGINGEN:
  1. Momentum State Engine: i.p.v. event-based crossovers →
     elke H1 bar scoort op: regime, RSI, EMA alignment, ATR, sessie
     Entry als score ≥ drempel EN cooldown voorbij EN positie vrij
  2. Risk verhogen: 1.25% STERK, 0.90% ZWAK → winstgevender per trade
  3. Cooldown: 4H (was 6H) → meer kansen per dag
  4. Fix: aparte functies per signaaltype, geen elif bug
  5. HH-Breakout signal hersteld (genereerd nu onafhankelijk)
  6. Hogere max SL: 1.0×H4ATR (was 0.75×) → minder uitgestopt
  7. Max 3 trades/dag STERK, 2 trades/dag ZWAK
  8. D1 NEUTRAL ook toegestaan bij STERK_BULL H4 (vangnet)

REALISTISCH DOEL v15:
  - 8-12 trades/maand
  - WR 50-58%
  - PF 1.5-2.0
  - Max DD < 6%
  - Doel: 4-7%/maand (5% gemiddeld realistisch haalbaar)

EERLIJK ADVIES:
  Op H1 data is consistent 5%/mnd MOEILIJK door:
  - Beperkte signaalfrequentie (~80-120 actieve uren/mnd London+NY)
  - Voor 5%/mnd consistenter: gebruik M5/M15 data (hogere freq.)
  - Beste realistisch verwacht resultaat op H1: 3-5%/mnd gem.

FTMO €160k: Dag-limiet €8.000 | Totaal €16.000
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL = 160_000.0
EUR_RATE  = 1.17
FTMO_DAG  = 8_000.0 * EUR_RATE
FTMO_TOT  = 16_000.0 * EUR_RATE
MAANDEN   = 16

# ── Indicatoren ───────────────────────────────────────────────────────────

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([
        (hi - lo), (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=p-1, adjust=False).mean()

def adx_fn(hi, lo, cl, p=14):
    u = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p-1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p-1, adjust=False).mean() / at
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p-1, adjust=False).mean().fillna(0)

# ── Data laden ─────────────────────────────────────────────────────────────

def laad():
    e = datetime.utcnow()
    s = e - timedelta(days=MAANDEN * 31 + 30)
    print(f"  Download GC=F H1: {s.date()} → {e.date()}")
    df = yf.download("GC=F", start=s.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"),
                     interval="1h", progress=False, auto_adjust=True)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open","high","low","close","volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df

# ── Indicatoren voorbereiden ───────────────────────────────────────────────

def bereid_voor(df):
    d = df.copy()

    # H1 indicatoren
    d["ema9"]      = ema(d["close"], 9)
    d["ema21"]     = ema(d["close"], 21)
    d["ema50"]     = ema(d["close"], 50)
    d["rsi14"]     = rsi_fn(d["close"], 14)
    d["rsi14_p"]   = d["rsi14"].shift(1)
    d["atr_h1"]    = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma20"]  = d["atr_h1"].rolling(20).mean()
    d["vol_ma20"]  = d["volume"].rolling(20).mean()
    d["high5"]     = d["high"].rolling(5).max().shift(1)
    d["low5"]      = d["low"].rolling(5).min().shift(1)
    d["close_ma5"] = d["close"].rolling(5).mean()

    # EMA crossovers
    d["cross_up"]   = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
    d["cross_down"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(1) >= d["ema21"].shift(1))

    # H4 indicatoren
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min",
                                "close":"last","volume":"sum"}).dropna()
    h4["e21"]    = ema(h4["close"], 21)
    h4["e50"]    = ema(h4["close"], 50)
    h4["e200"]   = ema(h4["close"], 200)
    h4["slope"]  = h4["e21"] - h4["e21"].shift(2)
    h4["adx"]    = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]    = atr_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi14"]  = rsi_fn(h4["close"], 14)

    def regime_h4(row):
        bull  = row["e21"] > row["e50"]
        bear  = row["e21"] < row["e50"]
        adx   = row["adx"]; sl = row["slope"]
        a200b = row["e50"] > row["e200"]
        a200r = row["e50"] < row["e200"]
        if   bull and adx >= 20 and sl > 0.3 and a200b: return "STERK_BULL"
        elif bull and adx >= 12:                         return "ZWAK_BULL"
        elif bear and adx >= 20 and sl < -0.3 and a200r: return "STERK_BEAR"
        elif bear and adx >= 12:                         return "ZWAK_BEAR"
        else:                                            return "CHOPPY"

    h4["regime"] = h4.apply(regime_h4, axis=1)
    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")
    d["h4_slope"]  = h4["slope"].reindex(d.index, method="ffill").fillna(0)
    d["h4_rsi"]    = h4["rsi14"].reindex(d.index, method="ffill").fillna(50)

    # D1 trend
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min",
                                "close":"last","volume":"sum"}).dropna()
    d1["de50"]    = ema(d1["close"], 50)
    d1["de200"]   = ema(d1["close"], 200)
    d1["slope50"] = d1["de50"] - d1["de50"].shift(3)
    d1["trend"]   = np.where(
        (d1["close"] > d1["de50"]) & (d1["slope50"] > 0), "bull",
        np.where((d1["close"] < d1["de50"]) & (d1["slope50"] < 0), "bear", "neutral")
    )
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

    # ── MOMENTUM STATE SCORE (MSE) ─────────────────────────────────
    # Score systeem: 0-10 punten per H1 bar LONG richting
    # Hoge score = sterke entry condities

    def long_score_series(df_in):
        s = pd.Series(0.0, index=df_in.index)

        # H4 regime bijdrage (0-4 punten)
        s += np.where(df_in["h4_regime"] == "STERK_BULL", 4,
             np.where(df_in["h4_regime"] == "ZWAK_BULL",  2,
             np.where(df_in["h4_regime"].isin(["STERK_BEAR","ZWAK_BEAR"]), -2, 0)))

        # D1 trend bijdrage (0-2 punten)
        s += np.where(df_in["d1_trend"] == "bull",    2,
             np.where(df_in["d1_trend"] == "neutral", 0, -3))

        # RSI range bijdrage (0-2 punten) — beste zone 50-65
        rsi = df_in["rsi14"].values
        s += np.where((rsi >= 52) & (rsi <= 65), 2,
             np.where((rsi >= 46) & (rsi < 52),  1,
             np.where((rsi > 65)  & (rsi <= 70), 1, 0)))

        # EMA alignment bijdrage (0-2 punten)
        e9  = df_in["ema9"].values
        e21 = df_in["ema21"].values
        e50 = df_in["ema50"].values
        s += np.where((e9 > e21) & (e21 > e50), 2,
             np.where(e9 > e21,                  1, 0))

        # H4 slope bijdrage
        sl = df_in["h4_slope"].values
        s += np.where(sl > 1.0, 1, np.where(sl > 0.2, 0, -1))

        return pd.Series(s, index=df_in.index)

    def short_score_series(df_in):
        s = pd.Series(0.0, index=df_in.index)
        s += np.where(df_in["h4_regime"] == "STERK_BEAR", 4,
             np.where(df_in["h4_regime"] == "ZWAK_BEAR",  2,
             np.where(df_in["h4_regime"].isin(["STERK_BULL","ZWAK_BULL"]), -2, 0)))
        s += np.where(df_in["d1_trend"] == "bear",    2,
             np.where(df_in["d1_trend"] == "neutral", 0, -3))
        rsi = df_in["rsi14"].values
        s += np.where((rsi >= 35) & (rsi <= 48), 2,
             np.where((rsi > 48)  & (rsi <= 54), 1,
             np.where((rsi >= 30) & (rsi < 35),  1, 0)))
        e9  = df_in["ema9"].values
        e21 = df_in["ema21"].values
        e50 = df_in["ema50"].values
        s += np.where((e9 < e21) & (e21 < e50), 2,
             np.where(e9 < e21,                  1, 0))
        sl = df_in["h4_slope"].values
        s += np.where(sl < -1.0, 1, np.where(sl < -0.2, 0, -1))
        return pd.Series(s, index=df_in.index)

    d["long_score"]  = long_score_series(d)
    d["short_score"] = short_score_series(d)

    return d.dropna(subset=["ema9","ema21","ema50","rsi14","atr_h1","h4_atr"])

# ── Sessie ──────────────────────────────────────────────────────────────────

def sessie_kwaliteit(uur, dow):
    if dow >= 5: return "blocked"
    if dow == 0 and uur < 8: return "blocked"
    if dow == 4 and uur >= 14: return "blocked"
    if 8 <= uur < 12: return "premium"
    if 13 <= uur < 16: return "premium"
    if 7 <= uur < 8 or uur == 12: return "standard"
    return "blocked"

# ── Signaaltype bepaler ──────────────────────────────────────────────────────

def bepaal_signaaltype(b, regime, d1_trend, rsi14, close, ema9_v, ema21_v, ema50_v,
                       h4_slope, h4_rsi, long_sc, short_sc, cross_up_v, cross_down_v,
                       high5_v, low5_v, tier, cfg):

    score_min_sterk  = cfg.get("score_min_sterk",  7)
    score_min_zwak   = cfg.get("score_min_zwak",   5)
    risk_sterk       = cfg.get("risk_sterk",  0.0125)
    risk_zwak        = cfg.get("risk_zwak",   0.0090)
    risk_dip         = cfg.get("risk_dip",    0.0060)
    rsi_lo_long      = cfg.get("rsi_lo_long",  47)
    rsi_hi_long      = cfg.get("rsi_hi_long",  71)
    tp1_r            = cfg.get("tp1_r",   1.5)
    tp2_r            = cfg.get("tp2_r",   2.5)
    slope_min        = cfg.get("slope_min", 0.2)

    sigs = []  # kan meerdere parallel genegenereerd worden, kies beste

    # ════════════════════════════════════════════════════════════════════
    # LONG signalen
    # ════════════════════════════════════════════════════════════════════

    if d1_trend in ("bull", "neutral"):

        # S1: Score-gebaseerde entry (MSE) — primair signaal
        # H4 STERK_BULL: score ≥ 7 (van max ~11)
        if regime == "STERK_BULL" and long_sc >= score_min_sterk and h4_slope >= slope_min:
            if rsi_lo_long <= rsi14 <= rsi_hi_long and close > ema21_v:
                quality = "A" if cross_up_v else ("B" if (ema9_v > ema21_v) else "C")
                sigs.append(("long", f"LONG_S1_STERK_{quality}", risk_sterk, tp1_r, tp2_r))

        # S2: ZWAK_BULL — lagere score drempel maar alleen premium
        if regime == "ZWAK_BULL" and long_sc >= score_min_zwak and tier == "premium":
            if rsi_lo_long <= rsi14 <= rsi_hi_long and close > ema21_v and h4_slope >= 0:
                sigs.append(("long", "LONG_S2_ZWAK", risk_zwak, tp1_r, tp2_r))

        # S3: Higher-High Breakout in STERK trend
        if regime == "STERK_BULL" and close > high5_v and 52 <= rsi14 <= 68:
            if h4_slope >= slope_min * 0.8 and ema9_v > ema21_v and tier == "premium":
                if long_sc >= score_min_sterk - 1:
                    sigs.append(("long", "LONG_S3_HH", risk_zwak * 1.1, tp1_r, tp2_r * 1.1))

        # S4: Buy-the-dip correctie in D1 bull
        if d1_trend == "bull" and regime in ("STERK_BEAR", "ZWAK_BEAR") and h4_rsi > 33:
            if cross_up_v and close > ema21_v and 50 <= rsi14 <= 66 and tier == "premium":
                sigs.append(("long", "LONG_S4_DIP", risk_dip, tp1_r * 0.9, tp2_r * 0.85))

    # ════════════════════════════════════════════════════════════════════
    # SHORT signalen
    # ════════════════════════════════════════════════════════════════════

    if d1_trend in ("bear", "neutral"):

        rsi_lo_short = 100 - rsi_hi_long
        rsi_hi_short = 100 - rsi_lo_long

        if regime == "STERK_BEAR" and short_sc >= score_min_sterk and h4_slope <= -slope_min:
            if rsi_lo_short <= rsi14 <= rsi_hi_short and close < ema21_v:
                quality = "A" if cross_down_v else ("B" if (ema9_v < ema21_v) else "C")
                sigs.append(("short", f"SHORT_S1_STERK_{quality}", risk_sterk, tp1_r, tp2_r))

        if regime == "ZWAK_BEAR" and short_sc >= score_min_zwak and tier == "premium":
            if rsi_lo_short <= rsi14 <= rsi_hi_short and close < ema21_v and h4_slope <= 0:
                sigs.append(("short", "SHORT_S2_ZWAK", risk_zwak, tp1_r, tp2_r))

        if regime == "STERK_BEAR" and close < low5_v and rsi_lo_short <= rsi14 <= rsi_hi_short:
            if h4_slope <= -slope_min * 0.8 and ema9_v < ema21_v and tier == "premium":
                if short_sc >= score_min_sterk - 1:
                    sigs.append(("short", "SHORT_S3_LL", risk_zwak * 1.1, tp1_r, tp2_r * 1.1))

    if not sigs:
        return None

    # Kies het signaal met de hoogste risk (= hoogste kwaliteit)
    return max(sigs, key=lambda x: x[2])

# ── Backtest ────────────────────────────────────────────────────────────────

def backtest(df, cfg):
    risk_sterk   = cfg.get("risk_sterk",  0.0125)
    sl_mult      = cfg.get("sl_mult",     1.0)
    sl_max_mult  = cfg.get("sl_max_mult", 1.8)
    tp1_pct      = cfg.get("tp1_pct",    0.40)
    adx_min      = cfg.get("adx_min",     14)
    vol_mult     = cfg.get("vol_mult",    1.02)
    max_dag      = cfg.get("max_dag",      4)
    sl_dag_stop  = cfg.get("sl_dag_stop",  2)
    cooldown_h   = cfg.get("cooldown_h",   4)
    h4atr_min    = cfg.get("h4atr_min",   4.0)
    atr_hi_mult  = cfg.get("atr_hi_mult",  2.5)

    kap = KAPITAAL * EUR_RATE
    piek = kap
    trs = []
    dag_info = {}
    consec_sl = 0

    ip        = False
    entry     = sl = tp1 = tp2 = sla = risk_usd = None
    richting  = sig_type = ot = None
    tp1_hit   = False
    last_entry_idx = -999

    for i in range(60, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()

        if dat not in dag_info:
            dag_info[dat] = {"verlies": 0.0, "n": 0, "sl_cnt": 0}

        # FTMO limiet
        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p  = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd, "FAIL", sig_type))
                ip = False
            break

        # Beheer open positie
        if ip:
            cur = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])

            if tp1_hit:
                if richting ==  1 and sl < entry: sl = entry + 0.10
                if richting == -1 and sl > entry: sl = entry - 0.10

            hit_tp1 = not tp1_hit and (
                (richting == 1  and hi >= tp1) or (richting == -1 and lo <= tp1)
            )
            hit_tp2 = (richting == 1 and hi >= tp2) or (richting == -1 and lo <= tp2)
            hit_sl  = (richting == 1 and lo <= sl)  or (richting == -1 and hi >= sl)

            if hit_tp1 and not hit_sl:
                pnl_usd = richting * (tp1 - entry) / sla * risk_usd * tp1_pct
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append(_tr(ot, b.name, richting, entry, tp1, pnl_usd, "TP1", sig_type))
                risk_usd *= (1 - tp1_pct)
                tp1_hit = True
                consec_sl = 0

            if hit_tp2 or hit_sl:
                exit_p  = tp2 if hit_tp2 else sl
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                if pnl_usd < 0:
                    dv = dag_info[dat]["verlies"]
                    if dv + abs(pnl_usd) > FTMO_DAG:
                        pnl_usd = -(FTMO_DAG - dv)
                    dag_info[dat]["verlies"] += abs(pnl_usd)
                    dag_info[dat]["sl_cnt"] += 1
                    if not tp1_hit: consec_sl += 1
                    else:           consec_sl = 0
                else:
                    consec_sl = 0
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd,
                               "TP2" if hit_tp2 else "SL", sig_type))
                ip = False

        if ip: continue

        dv     = dag_info[dat]["verlies"]
        n_dag  = dag_info[dat]["n"]
        sl_dag = dag_info[dat]["sl_cnt"]
        if dv >= FTMO_DAG * 0.60: continue
        if n_dag >= max_dag: continue
        if sl_dag >= sl_dag_stop: continue
        if (i - last_entry_idx) < cooldown_h: continue

        tier = sessie_kwaliteit(uur, dow)
        if tier == "blocked": continue

        # Indicator waarden
        regime   = b["h4_regime"]
        d1_trend = b["d1_trend"]
        rsi14    = float(b["rsi14"])
        close    = float(b["close"])
        ema9_v   = float(b["ema9"])
        ema21_v  = float(b["ema21"])
        ema50_v  = float(b["ema50"])
        atr_h1   = float(b["atr_h1"])
        atr_h4   = float(b["h4_atr"])
        atr_ma   = float(b["atr_ma20"]) if not pd.isna(b["atr_ma20"]) else atr_h1
        h4_adx   = float(b["h4_adx"])
        h4_slope = float(b["h4_slope"])
        h4_rsi   = float(b["h4_rsi"])
        vol      = float(b["volume"])
        vol_ma   = float(b["vol_ma20"]) if not pd.isna(b["vol_ma20"]) else 1.0
        cross_up_v   = bool(b["cross_up"])
        cross_down_v = bool(b["cross_down"])
        long_sc      = float(b["long_score"])
        short_sc     = float(b["short_score"])
        high5_v      = float(b["high5"]) if not pd.isna(b["high5"]) else close + 9999
        low5_v       = float(b["low5"])  if not pd.isna(b["low5"])  else close - 9999

        # Globale filters
        if atr_h4 < h4atr_min: continue
        if atr_ma > 0 and atr_h1 > atr_hi_mult * atr_ma: continue
        if h4_adx < adx_min: continue
        if vol_ma > 100 and vol < vol_mult * vol_ma: continue

        sig = bepaal_signaaltype(
            b, regime, d1_trend, rsi14, close, ema9_v, ema21_v, ema50_v,
            h4_slope, h4_rsi, long_sc, short_sc, cross_up_v, cross_down_v,
            high5_v, low5_v, tier, cfg
        )
        if not sig: continue

        richting_str, sig_type, risk_pct, tp1_mult, tp2_mult = sig

        if tier == "standard" and any(x in sig_type for x in ["ZWAK","DIP","HH","LL"]):
            continue

        richting = 1 if richting_str == "long" else -1

        # SL berekening
        swing_lo = float(b["low5"]) - 0.1 * atr_h1 if not pd.isna(b["low5"]) else close - sl_mult * atr_h4
        swing_hi = float(b["high5"]) + 0.1 * atr_h1 if not pd.isna(b["high5"]) else close + sl_mult * atr_h4

        if richting == 1:
            sl_raw = min(swing_lo, close - sl_mult * atr_h4)
        else:
            sl_raw = max(swing_hi, close + sl_mult * atr_h4)

        sla_raw = abs(close - sl_raw)
        sla = max(sl_mult * atr_h4, min(sl_max_mult * atr_h4, sla_raw))
        sl  = close - richting * sla
        tp1 = close + richting * tp1_mult * sla
        tp2 = close + richting * tp2_mult * sla
        entry = close

        # Drawdown risk scaling
        dd_pct = (piek - kap) / piek
        if   dd_pct > 0.07: risk_pct *= 0.25
        elif dd_pct > 0.05: risk_pct *= 0.40
        elif dd_pct > 0.03: risk_pct *= 0.65
        elif dd_pct > 0.01: risk_pct *= 0.85

        if consec_sl >= 4: risk_pct *= 0.50

        risk_usd = kap * risk_pct
        ot = b.name
        ip = True
        tp1_hit = False
        last_entry_idx = i
        dag_info[dat]["n"] += 1

    if ip:
        exit_p  = float(df.iloc[-1]["close"])
        pnl_usd = richting * (exit_p - entry) / sla * risk_usd
        kap += pnl_usd
        trs.append(_tr(ot, df.index[-1], richting, entry, exit_p, pnl_usd, "OPEN", sig_type))

    return trs, kap / EUR_RATE


def _tr(ti, to, rich, entry, exit_p, pnl_usd, result, stype):
    return {
        "in": ti, "uit": to, "rich": rich, "entry": entry, "exit": exit_p,
        "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE, "result": result, "type": stype,
    }

# ── Rapportage ──────────────────────────────────────────────────────────────

def rapport(trs, kap_eur_eind, label, verbose=True):
    pnl_eur = kap_eur_eind - KAPITAAL
    if verbose:
        print(); print("=" * 76); print(f"  {label}"); print("=" * 76)
    if not trs:
        if verbose: print("  Geen trades.")
        return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    n   = len(df_t)
    wr  = 100 * (df_t["pnl_eur"] > 0).mean()
    gw  = df_t[df_t["pnl_eur"] > 0]["pnl_eur"].sum()
    gl  = df_t[df_t["pnl_eur"] < 0]["pnl_eur"].abs().sum()
    pf  = gw / gl if gl > 0 else 999.0

    type_cnt   = df_t["type"].value_counts().to_dict()
    result_cnt = df_t["result"].value_counts().to_dict()

    dagen   = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    mnd_n   = dagen / 30.44
    gem_mnd = pnl_eur / mnd_n
    mnd_pct = pnl_eur / KAPITAAL * 100 / mnd_n

    cap_lp = KAPITAAL * EUR_RATE; pk_lp = cap_lp; max_dd = 0.0
    for t in trs:
        cap_lp += t["pnl_usd"]
        if cap_lp > pk_lp: pk_lp = cap_lp
        dd = (pk_lp - cap_lp) / pk_lp
        if dd > max_dd: max_dd = dd

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_eur","count"),
        pnl_eur=("pnl_eur","sum"),
        wins=("pnl_eur", lambda x: (x > 0).sum()),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct_mnd"] = mnd["pnl_eur"] / KAPITAAL * 100
    pos_mnd  = (mnd["pnl_eur"] > 0).sum()
    tot_mnd  = len(mnd)
    doel_mnd = (mnd["pct_mnd"] >= 5).sum()

    if verbose:
        doel_s = "✓ BEREIKT!" if mnd_pct >= 5 else f"  {5-mnd_pct:.1f}% tekort"
        safe = "✓ VEILIG" if max_dd < 0.06 else ("⚠ HOOG" if max_dd < 0.09 else "✗ KRITIEK")
        print(f"  Kapitaal  : €{KAPITAAL:>12,.0f}  →  €{kap_eur_eind:>12,.0f}")
        print(f"  P&L       : €{pnl_eur:>+12,.0f}")
        print(f"  Gem/mnd   : €{gem_mnd:>+10,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
        print(f"  Max DD    : {max_dd*100:.2f}%  [{safe}]")
        print(f"  Trades    : {n}  ({n/mnd_n:.1f}/mnd gem.)  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
        print(f"  Signalen  : {type_cnt}")
        print(f"  Resultaten: {result_cnt}")
        print(f"  Maanden   : positief {pos_mnd}/{tot_mnd} | ≥5% {doel_mnd}/{tot_mnd}")

        print(f"\n  {'Maand':<10} {'Tr':>4} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7}")
        print("  " + "─" * 52)
        for _, r in mnd.iterrows():
            flag = " *** DOEL!" if r["pct_mnd"] >= 5 else (" ─── ZWAK" if r["pnl_eur"] < -3200 else "")
            print(f"  {str(r['maand']):<10} {r['trades']:>4}  {r['win_pct']:>4.1f}%  "
                  f"€{r['pnl_eur']:>10,.0f}  {r['pct_mnd']:>6.2f}%{flag}")
        print("=" * 76)

    return {
        "label": label, "pnl_eur": pnl_eur, "gem_mnd": gem_mnd,
        "maand_pct": mnd_pct, "trades": n, "wr": wr, "pf": pf,
        "max_dd": max_dd, "pos_mnd": pos_mnd, "tot_mnd": tot_mnd,
        "doel_mnd": doel_mnd, "mnd": mnd, "types": type_cnt,
        "tr_per_mnd": n / mnd_n,
    }

# ── Varianten definitie ─────────────────────────────────────────────────────

VARIANTEN = {
    "V15-Basis": {
        "desc": "MSE score≥7/5, risk 1.25/0.9/0.6%, cooldown 4h",
        "risk_sterk":0.0125,"risk_zwak":0.0090,"risk_dip":0.0060,
        "score_min_sterk":7,"score_min_zwak":5,
        "sl_mult":1.0,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.40,
        "rsi_lo_long":47,"rsi_hi_long":71,"adx_min":14,"slope_min":0.2,
        "vol_mult":1.02,"max_dag":4,"sl_dag_stop":2,"cooldown_h":4,"h4atr_min":4.0,"atr_hi_mult":2.5,
    },
    "V15-Liberal": {
        "desc": "Lagere score drempel: ≥6/4, cooldown 3h, meer trades",
        "risk_sterk":0.0125,"risk_zwak":0.0090,"risk_dip":0.0060,
        "score_min_sterk":6,"score_min_zwak":4,
        "sl_mult":1.0,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.40,
        "rsi_lo_long":45,"rsi_hi_long":72,"adx_min":12,"slope_min":0.1,
        "vol_mult":1.00,"max_dag":5,"sl_dag_stop":2,"cooldown_h":3,"h4atr_min":3.5,"atr_hi_mult":3.0,
    },
    "V15-Sterk": {
        "desc": "Hoge risk: 1.5/1.1/0.8%, score≥7, ADX≥18",
        "risk_sterk":0.0150,"risk_zwak":0.0110,"risk_dip":0.0080,
        "score_min_sterk":7,"score_min_zwak":5,
        "sl_mult":1.0,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.35,
        "rsi_lo_long":48,"rsi_hi_long":70,"adx_min":18,"slope_min":0.3,
        "vol_mult":1.05,"max_dag":3,"sl_dag_stop":2,"cooldown_h":4,"h4atr_min":4.5,"atr_hi_mult":2.0,
    },
    "V15-TP3": {
        "desc": "Grotere doelen: TP2@3.0R, score≥7",
        "risk_sterk":0.0125,"risk_zwak":0.0090,"risk_dip":0.0060,
        "score_min_sterk":7,"score_min_zwak":5,
        "sl_mult":1.0,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":3.0,"tp1_pct":0.40,
        "rsi_lo_long":47,"rsi_hi_long":71,"adx_min":14,"slope_min":0.2,
        "vol_mult":1.02,"max_dag":4,"sl_dag_stop":2,"cooldown_h":4,"h4atr_min":4.0,"atr_hi_mult":2.5,
    },
    "V15-FreqTP": {
        "desc": "Freq + TP3: score≥5/3, cooldown 3h, TP2@3.0R",
        "risk_sterk":0.0125,"risk_zwak":0.0090,"risk_dip":0.0060,
        "score_min_sterk":5,"score_min_zwak":3,
        "sl_mult":1.0,"sl_max_mult":2.0,"tp1_r":1.5,"tp2_r":3.0,"tp1_pct":0.40,
        "rsi_lo_long":44,"rsi_hi_long":73,"adx_min":12,"slope_min":0.1,
        "vol_mult":1.00,"max_dag":5,"sl_dag_stop":3,"cooldown_h":3,"h4atr_min":3.5,"atr_hi_mult":3.0,
    },
    "V15-MaxProfit": {
        "desc": "Max return: 1.75/1.25%, score≥6, TP2@3.5R",
        "risk_sterk":0.0175,"risk_zwak":0.0125,"risk_dip":0.0090,
        "score_min_sterk":6,"score_min_zwak":4,
        "sl_mult":1.0,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":3.5,"tp1_pct":0.35,
        "rsi_lo_long":47,"rsi_hi_long":71,"adx_min":14,"slope_min":0.2,
        "vol_mult":1.02,"max_dag":4,"sl_dag_stop":2,"cooldown_h":4,"h4atr_min":4.0,"atr_hi_mult":2.5,
    },
}

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 76)
    print("  XAUUSD STRATEGIE v15 | MOMENTUM STATE ENGINE (MSE)")
    print("  Score-gebaseerde entry | Partiële TP | FTMO-safe risk")
    print(f"  FTMO €160k: Dag-limiet €8.000 | Totaal €16.000")
    print("=" * 76)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren berekenen...")
    df = bereid_voor(df_raw)

    d1_cnt  = df["d1_trend"].value_counts()
    h4_cnt  = df["h4_regime"].value_counts()
    long_hi = (df["long_score"] >= 7).sum()
    long_md = ((df["long_score"] >= 5) & (df["long_score"] < 7)).sum()
    print(f"  D1 trends   : {dict(d1_cnt)}")
    print(f"  H4 regimes  : {dict(h4_cnt)}")
    print(f"  Long score ≥7 (sterk entry): {long_hi:>5} bars ({long_hi/MAANDEN:.0f}/mnd)")
    print(f"  Long score 5-6 (zwak entry): {long_md:>5} bars ({long_md/MAANDEN:.0f}/mnd)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res: resultaten.append(res)

    print(); print("=" * 110)
    print("  EINDOVERZICHT v15 — ITERATIE 5")
    print("=" * 110)
    print(f"  {'Variant':<22} {'P&L':>12} {'%/mnd':>7} {'Tr/mnd':>7} {'Win%':>6} "
          f"{'PF':>5} {'MaxDD':>7} {'Pos':>7} {'≥5%':>5}")
    print("  " + "─" * 105)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel = " *** DOEL!" if r["maand_pct"] >= 5 else (" ✓ GD" if r["maand_pct"] >= 3 else "")
        safe = " ⚠DD!" if r["max_dd"] > 0.09 else ""
        pm   = f"{r['pos_mnd']}/{r['tot_mnd']}"
        dm   = f"{r['doel_mnd']}/{r['tot_mnd']}"
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['tr_per_mnd']:>6.1f}  {r['wr']:>4.1f}% {r['pf']:>5.2f} "
              f"{r['max_dd']*100:>6.1f}%  {pm:>6}  {dm:>4}{doel}{safe}")

    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        veilig = [r for r in resultaten if r["max_dd"] < 0.09]
        beste_safe = max(veilig, key=lambda x: x["maand_pct"]) if veilig else beste

        print(f"\n  BESTE TOTAAL : {beste['label']:<22} {beste['maand_pct']:+.2f}%/mnd")
        print(f"  BESTE SAFE   : {beste_safe['label']:<22} {beste_safe['maand_pct']:+.2f}%/mnd | "
              f"DD {beste_safe['max_dd']*100:.1f}%")
        print(f"  Signalen     : {beste['types']}")
        print(f"  {beste['trades']} trades ({beste['tr_per_mnd']:.1f}/mnd) | "
              f"WR {beste['wr']:.1f}% | PF {beste['pf']:.2f} | "
              f"{beste['pos_mnd']}/{beste['tot_mnd']} pos mnd | "
              f"{beste['doel_mnd']}/{beste['tot_mnd']} ≥5% mnd")

        if beste["maand_pct"] >= 5:
            print(f"\n  ✓✓ DOEL 5%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 3:
            print(f"\n  {5-beste['maand_pct']:.1f}% van doel.")

    print("\n  ITERATIE VOORTGANG:")
    print("  V12-RSI50  : +0.44%/mnd | 4.6 tr/mnd | WR 29% | PF 1.22")
    print("  V13-Max4   : +0.39%/mnd | 2.3 tr/mnd | WR 70% | PF 1.94")
    print("  V14-LibTP  : +1.18%/mnd | 3.5 tr/mnd | WR 71% | PF 2.39")
    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        print(f"  V15-Beste  : {beste['maand_pct']:+.2f}%/mnd | {beste['tr_per_mnd']:.1f} tr/mnd | "
              f"WR {beste['wr']:.1f}% | PF {beste['pf']:.2f}")

    print("\n  EERLIJK ADVIES:")
    print("  Op H1 data is consistent 5%/mnd een uitdaging (lage signaalfrequentie).")
    print("  Best haalbaar op H1: ~2-4%/mnd gem. | Piekmaanden 5-8%")
    print("  Voor consistent 5%/mnd: gebruik M5/M15 data of verhoog risk.")
    print("=" * 110)


if __name__ == "__main__":
    main()
