"""
XAUUSD Strategy v14 — Trend Continuation + Pullback Engine
============================================================
ITERATIE 4 ANALYSE (na V13):

DIAGNOSE V13:
  • Win rate 70%, PF 1.94 — signaalKWALITEIT is uitstekend
  • Slechts 2-3 trades/maand — fundamenteel te weinig
  • Root cause: EMA9/21 crossover = enkel aan START van trend
    In sterke trends (maart-sept 2025) bleef EMA9 weken boven EMA21
    → geen crossovers = geen signalen

V14 OPLOSSING: Multi-signal engine
  Signal A (Crossover):    EMA9 kruist boven EMA21          ← was V13
  Signal B (RSI Pullback): H1 RSI daalt naar 45-53, herstelt naar >55
                           EMA9 > EMA21 al (trend intact)   ← NIEUW
  Signal C (HL Pattern):   Close > 4-bar high, RSI >52, EMA9>EMA21 ← NIEUW
  Signal D (Session Open): Eerste kwaliteitsbar na London/NY open
                           Regime + momentum aligned        ← NIEUW

VERWACHT V14:
  - 12-20 trades/maand
  - Win rate 45-55%
  - PF 1.4-1.8
  - Max drawdown < 5%
  - Doel: 5-8%/maand

COOLDOWN: max 1 trade per 6 bars (6 uur gap)
RISK: 1.0% STERK, 0.75% ZWAK, 0.5% DIP
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

# ── Technische indicatoren ──────────────────────────────────────────────

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([
        (hi - lo),
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=p-1, adjust=False).mean()

def adx_fn(hi, lo, cl, p=14):
    u  = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p-1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p-1, adjust=False).mean() / at
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p-1, adjust=False).mean().fillna(0)

# ── Data laden ────────────────────────────────────────────────────────

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

# ── Indicatoren voorbereiding ─────────────────────────────────────────

def bereid_voor(df):
    d = df.copy()

    # H1 indicatoren
    d["ema9"]     = ema(d["close"], 9)
    d["ema21"]    = ema(d["close"], 21)
    d["ema50"]    = ema(d["close"], 50)
    d["rsi14"]    = rsi_fn(d["close"], 14)
    d["rsi14_p"]  = d["rsi14"].shift(1)
    d["rsi14_2p"] = d["rsi14"].shift(2)
    d["atr_h1"]   = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma20"] = d["atr_h1"].rolling(20).mean()
    d["vol_ma20"] = d["volume"].rolling(20).mean()
    d["high4"]    = d["high"].rolling(4).max().shift(1)   # 4-bar high (excl huidige bar)
    d["low4"]     = d["low"].rolling(4).min().shift(1)    # 4-bar low

    # EMA crossovers (H1)
    d["cross_up"]   = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
    d["cross_down"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(1) >= d["ema21"].shift(1))

    # EMA alignment checks
    d["ema_bull"] = (d["ema9"] > d["ema21"]) & (d["ema21"] > d["ema50"])  # volledig bull stack
    d["ema_bear"] = (d["ema9"] < d["ema21"]) & (d["ema21"] < d["ema50"])  # volledig bear stack

    # RSI pullback detectie
    d["rsi_pb_ok"] = (d["rsi14_p"].between(44, 54)) & (d["rsi14"] > 55)  # dip → herstel
    d["rsi_pb_sh"] = (d["rsi14_p"].between(46, 56)) & (d["rsi14"] < 45)  # bear pullback

    # Swing lows/highs
    d["swing_low5"]  = d["low"].rolling(5).min()
    d["swing_high5"] = d["high"].rolling(5).max()

    # H4 indicatoren
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min",
                                "close":"last","volume":"sum"}).dropna()
    h4["e9"]    = ema(h4["close"], 9)
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope"] = h4["e21"] - h4["e21"].shift(2)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi14"] = rsi_fn(h4["close"], 14)
    h4["vol_ma"] = h4["volume"].rolling(10).mean()

    def regime_h4(row):
        bull     = row["e21"] > row["e50"]
        bear     = row["e21"] < row["e50"]
        adx_v    = row["adx"]
        sl       = row["slope"]
        a200b    = row["e50"] > row["e200"]
        a200br   = row["e50"] < row["e200"]
        if   bull and adx_v >= 22 and sl >  0.5 and a200b:  return "STERK_BULL"
        elif bull and adx_v >= 13:                            return "ZWAK_BULL"
        elif bear and adx_v >= 22 and sl < -0.5 and a200br:  return "STERK_BEAR"
        elif bear and adx_v >= 13:                            return "ZWAK_BEAR"
        else:                                                 return "CHOPPY"

    h4["regime"] = h4.apply(regime_h4, axis=1)
    d["h4_regime"]  = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]     = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]     = h4["atr"].reindex(d.index, method="ffill")
    d["h4_slope"]   = h4["slope"].reindex(d.index, method="ffill").fillna(0)
    d["h4_rsi"]     = h4["rsi14"].reindex(d.index, method="ffill").fillna(50)

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

    return d.dropna(subset=["ema9","ema21","ema50","rsi14","atr_h1","h4_atr"])

# ── Sessie filter ─────────────────────────────────────────────────────

def sessie_kwaliteit(uur, dow):
    if dow >= 5: return "blocked"
    if dow == 0 and uur < 8: return "blocked"
    if dow == 4 and uur >= 14: return "blocked"
    if 8 <= uur < 12: return "premium"    # London Open
    if 13 <= uur < 16: return "premium"   # NY Open
    if 7 <= uur < 8 or uur == 12: return "standard"
    return "blocked"

# ── Backtest ─────────────────────────────────────────────────────────

def backtest(df, cfg):
    risk_sterk  = cfg.get("risk_sterk",  0.010)
    risk_zwak   = cfg.get("risk_zwak",   0.0075)
    risk_dip    = cfg.get("risk_dip",    0.005)
    sl_mult     = cfg.get("sl_mult",     0.75)   # SL = sl_mult × H4 ATR
    sl_max_mult = cfg.get("sl_max_mult", 1.5)
    tp1_r       = cfg.get("tp1_r",       1.5)
    tp2_r       = cfg.get("tp2_r",       2.5)
    tp1_pct     = cfg.get("tp1_pct",     0.40)
    rsi_lo      = cfg.get("rsi_lo",      48)
    rsi_hi      = cfg.get("rsi_hi",      70)
    adx_min     = cfg.get("adx_min",     15)
    slope_min   = cfg.get("slope_min",   0.2)
    vol_mult    = cfg.get("vol_mult",    1.05)
    max_dag     = cfg.get("max_dag",      4)
    sl_dag_stop = cfg.get("sl_dag_stop",  2)
    cooldown_h  = cfg.get("cooldown_h",   6)    # min uren tussen entries
    h4atr_min   = cfg.get("h4atr_min",   4.5)
    atr_hi_mult = cfg.get("atr_hi_mult",  2.5)

    kap = KAPITAAL * EUR_RATE
    piek = kap
    trs = []
    dag_info = {}
    consec_sl = 0

    ip         = False
    entry      = sl = tp1 = tp2 = sla = risk_usd = None
    richting   = sig_type = ot = None
    tp1_hit    = False
    last_entry_idx = -999  # cooldown tracker

    for i in range(60, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()

        if dat not in dag_info:
            dag_info[dat] = {"verlies": 0.0, "n": 0, "sl_cnt": 0}

        # FTMO totaallimiet
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

            # Break-even na TP1
            if tp1_hit:
                if richting ==  1 and sl < entry: sl = entry + 0.10
                if richting == -1 and sl > entry: sl = entry - 0.10

            hit_tp1 = not tp1_hit and (
                (richting == 1  and hi >= tp1) or
                (richting == -1 and lo <= tp1)
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

        # Daglimieten
        dv     = dag_info[dat]["verlies"]
        n_dag  = dag_info[dat]["n"]
        sl_dag = dag_info[dat]["sl_cnt"]
        if dv >= FTMO_DAG * 0.60: continue
        if n_dag >= max_dag: continue
        if sl_dag >= sl_dag_stop: continue

        # Cooldown check
        if (i - last_entry_idx) < cooldown_h: continue

        tier = sessie_kwaliteit(uur, dow)
        if tier == "blocked": continue

        # Indicator waarden
        regime   = b["h4_regime"]
        d1_trend = b["d1_trend"]
        rsi14    = float(b["rsi14"])
        rsi14_p  = float(b["rsi14_p"]) if not pd.isna(b["rsi14_p"]) else rsi14
        rsi14_2p = float(b["rsi14_2p"]) if not pd.isna(b["rsi14_2p"]) else rsi14_p
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
        ema_bull_v   = bool(b["ema_bull"])
        ema_bear_v   = bool(b["ema_bear"])
        rsi_pb_ok_v  = bool(b["rsi_pb_ok"])
        rsi_pb_sh_v  = bool(b["rsi_pb_sh"])
        swing_lo     = float(b["swing_low5"])
        swing_hi     = float(b["swing_high5"])
        high4_v      = float(b["high4"]) if not pd.isna(b["high4"]) else close
        low4_v       = float(b["low4"])  if not pd.isna(b["low4"])  else close

        # Globale filters
        if atr_h4 < h4atr_min: continue
        if atr_ma > 0 and atr_h1 > atr_hi_mult * atr_ma: continue  # spike filter
        if h4_adx < adx_min: continue

        # Volume filter
        if vol_ma > 100 and vol < vol_mult * vol_ma: continue

        sig = None
        bull_regime = regime in ("STERK_BULL", "ZWAK_BULL")
        sterk_bull  = regime == "STERK_BULL"
        bear_regime = regime in ("STERK_BEAR", "ZWAK_BEAR")
        sterk_bear  = regime == "STERK_BEAR"

        # ════════════════════════════════════════════════════════════
        # LONG SIGNALEN (D1 bull)
        # ════════════════════════════════════════════════════════════
        if d1_trend == "bull":

            # ── Signal A: EMA9/21 Crossover (STERK of ZWAK Bull) ─────
            if cross_up_v and bull_regime and h4_slope >= slope_min:
                if rsi_lo <= rsi14 <= rsi_hi and close > ema50_v:
                    r = risk_sterk if sterk_bull else risk_zwak
                    if tier == "premium" or sterk_bull:
                        sig = ("long", "LONG_A_CROSS", r, tp1_r, tp2_r)

            # ── Signal B: RSI Pullback binnen lopende trend (STERK) ───
            # EMA9 al boven EMA21 (trend intact) + RSI daalde naar 44-53 en herstelt
            elif sterk_bull and ema9_v > ema21_v and h4_slope >= slope_min * 0.5:
                if rsi_pb_ok_v and close > ema21_v and tier == "premium":
                    sig = ("long", "LONG_B_PB", risk_sterk * 0.85, tp1_r, tp2_r)

            # ── Signal C: Higher-High Breakout binnen bull EMA stack ──
            # EMA stack volledig bull, close breekt boven 4-bar high, RSI 52-67
            elif ema_bull_v and sterk_bull and h4_slope >= slope_min:
                if close > high4_v and 52 <= rsi14 <= 67:
                    if tier == "premium" and rsi14 > rsi14_p:  # RSI stijgt
                        sig = ("long", "LONG_C_HH", risk_zwak, tp1_r * 0.9, tp2_r * 0.85)

            # ── Signal D: EMA9/21 cross in ZWAK_BULL (premium only) ──
            elif regime == "ZWAK_BULL" and cross_up_v and h4_slope >= 0:
                if rsi_lo <= rsi14 <= rsi_hi and close > ema21_v and tier == "premium":
                    sig = ("long", "LONG_D_ZWAK", risk_zwak * 0.8, tp1_r, tp2_r)

            # ── Signal E: Buy-the-dip — H4 bear correctie in D1 bull ─
            elif regime in ("STERK_BEAR", "ZWAK_BEAR") and h4_rsi > 32:
                if cross_up_v and close > ema21_v and 50 <= rsi14 <= 65:
                    if tier == "premium":
                        sig = ("long", "LONG_E_DIP", risk_dip, tp1_r * 0.85, tp2_r * 0.8)

        # ════════════════════════════════════════════════════════════
        # SHORT SIGNALEN (D1 bear)
        # ════════════════════════════════════════════════════════════
        elif d1_trend == "bear":

            # Signal A: Crossover
            if cross_down_v and bear_regime and h4_slope <= -slope_min:
                if (100-rsi_hi) <= rsi14 <= (100-rsi_lo) and close < ema50_v:
                    r = risk_sterk if sterk_bear else risk_zwak
                    if tier == "premium" or sterk_bear:
                        sig = ("short", "SHORT_A_CROSS", r, tp1_r, tp2_r)

            # Signal B: RSI pullback in bear trend
            elif sterk_bear and ema9_v < ema21_v and h4_slope <= -slope_min * 0.5:
                if rsi_pb_sh_v and close < ema21_v and tier == "premium":
                    sig = ("short", "SHORT_B_PB", risk_sterk * 0.85, tp1_r, tp2_r)

            # Signal C: Lower-Low breakdown
            elif ema_bear_v and sterk_bear and h4_slope <= -slope_min:
                if close < low4_v and 33 <= rsi14 <= 48:
                    if tier == "premium" and rsi14 < rsi14_p:
                        sig = ("short", "SHORT_C_LL", risk_zwak, tp1_r * 0.9, tp2_r * 0.85)

        if not sig: continue

        richting_str, sig_type, risk_pct, tp1_mult, tp2_mult = sig

        # Standard tier: geen ZWAK/DIP/HH/PB
        if tier == "standard" and any(x in sig_type for x in ["ZWAK","DIP","HH","PB","LL"]):
            continue

        richting = 1 if richting_str == "long" else -1

        # SL berekening
        if richting == 1:
            sl_swing_v = swing_lo - 0.1 * atr_h1
            sl_raw     = min(sl_swing_v, close - sl_mult * atr_h4)
        else:
            sl_swing_v = swing_hi + 0.1 * atr_h1
            sl_raw     = max(sl_swing_v, close + sl_mult * atr_h4)

        sla_raw = abs(close - sl_raw)
        sla = max(sl_mult * atr_h4, min(sl_max_mult * atr_h4, sla_raw))
        sl  = close - richting * sla
        tp1 = close + richting * tp1_mult * sla
        tp2 = close + richting * tp2_mult * sla
        entry = close

        # Drawdown-gebaseerde risk scaling
        dd_pct = (piek - kap) / piek
        if   dd_pct > 0.06: risk_pct *= 0.30
        elif dd_pct > 0.04: risk_pct *= 0.50
        elif dd_pct > 0.02: risk_pct *= 0.75

        # Consecutive loss protection
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
        "in": ti, "uit": to, "rich": rich,
        "entry": entry, "exit": exit_p,
        "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE,
        "result": result, "type": stype,
    }

# ── Rapportage ────────────────────────────────────────────────────────

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
        trades=("pnl_eur", "count"),
        pnl_eur=("pnl_eur", "sum"),
        wins=("pnl_eur", lambda x: (x > 0).sum()),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct_mnd"] = mnd["pnl_eur"] / KAPITAAL * 100
    pos_mnd  = (mnd["pnl_eur"] > 0).sum()
    tot_mnd  = len(mnd)
    doel_mnd = (mnd["pct_mnd"] >= 5).sum()

    if verbose:
        doel_s = "✓ BEREIKT!" if mnd_pct >= 5 else f"  {5-mnd_pct:.1f}% tekort"
        print(f"  Kapitaal  : €{KAPITAAL:>12,.0f}  →  €{kap_eur_eind:>12,.0f}")
        print(f"  P&L       : €{pnl_eur:>+12,.0f}")
        print(f"  Gem/mnd   : €{gem_mnd:>+10,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
        safe = "✓ VEILIG" if max_dd < 0.06 else ("⚠ GRENS" if max_dd < 0.10 else "✗ OVERSCHR")
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

# ── Varianten ─────────────────────────────────────────────────────────

VARIANTEN = {
    "V14-Basis": {
        "desc": "Alle signalen, 1.0/0.75/0.5%, cooldown 6h, max 4/dag",
        "risk_sterk":0.010,"risk_zwak":0.0075,"risk_dip":0.005,
        "sl_mult":0.75,"sl_max_mult":1.5,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.40,
        "rsi_lo":48,"rsi_hi":70,"adx_min":15,"slope_min":0.2,
        "vol_mult":1.05,"max_dag":4,"sl_dag_stop":2,"cooldown_h":6,"h4atr_min":4.5,"atr_hi_mult":2.5,
    },
    "V14-Sterk": {
        "desc": "Hoog risk: 1.25/1.0/0.7%, ADX≥20, slope≥0.5",
        "risk_sterk":0.0125,"risk_zwak":0.010,"risk_dip":0.007,
        "sl_mult":0.8,"sl_max_mult":1.5,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.35,
        "rsi_lo":50,"rsi_hi":68,"adx_min":20,"slope_min":0.5,
        "vol_mult":1.10,"max_dag":3,"sl_dag_stop":2,"cooldown_h":6,"h4atr_min":5.0,"atr_hi_mult":2.0,
    },
    "V14-Freq": {
        "desc": "Meer trades: cooldown 4h, max 5/dag, slope≥0.1",
        "risk_sterk":0.010,"risk_zwak":0.0075,"risk_dip":0.005,
        "sl_mult":0.75,"sl_max_mult":1.5,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.40,
        "rsi_lo":46,"rsi_hi":72,"adx_min":13,"slope_min":0.1,
        "vol_mult":1.02,"max_dag":5,"sl_dag_stop":3,"cooldown_h":4,"h4atr_min":4.0,"atr_hi_mult":3.0,
    },
    "V14-TP3": {
        "desc": "Grotere doelen: TP2 @3.0R",
        "risk_sterk":0.010,"risk_zwak":0.0075,"risk_dip":0.005,
        "sl_mult":0.75,"sl_max_mult":1.5,"tp1_r":1.5,"tp2_r":3.0,"tp1_pct":0.40,
        "rsi_lo":48,"rsi_hi":70,"adx_min":15,"slope_min":0.2,
        "vol_mult":1.05,"max_dag":4,"sl_dag_stop":2,"cooldown_h":6,"h4atr_min":4.5,"atr_hi_mult":2.5,
    },
    "V14-SL1x": {
        "desc": "Strakker SL: 0.6×ATR, risk 1.1%, meer trades mogelijk",
        "risk_sterk":0.011,"risk_zwak":0.0085,"risk_dip":0.006,
        "sl_mult":0.60,"sl_max_mult":1.2,"tp1_r":1.5,"tp2_r":2.5,"tp1_pct":0.40,
        "rsi_lo":48,"rsi_hi":70,"adx_min":15,"slope_min":0.2,
        "vol_mult":1.05,"max_dag":4,"sl_dag_stop":2,"cooldown_h":5,"h4atr_min":4.5,"atr_hi_mult":2.5,
    },
    "V14-LibTP": {
        "desc": "Liberal + TP3: max signalen, ruime doelen",
        "risk_sterk":0.010,"risk_zwak":0.0075,"risk_dip":0.005,
        "sl_mult":0.75,"sl_max_mult":1.8,"tp1_r":1.5,"tp2_r":3.0,"tp1_pct":0.40,
        "rsi_lo":45,"rsi_hi":72,"adx_min":13,"slope_min":0.1,
        "vol_mult":1.02,"max_dag":5,"sl_dag_stop":3,"cooldown_h":4,"h4atr_min":4.0,"atr_hi_mult":3.0,
    },
}

# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 76)
    print("  XAUUSD STRATEGIE v14 | MULTI-SIGNAL CONTINUATION ENGINE")
    print("  A:Crossover B:Pullback C:HH-Breakout D:ZWAK E:Dip")
    print(f"  FTMO €160k — Doel 5%/mnd | Cooldown 4-6h | Partiële TP")
    print("=" * 76)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren berekenen...")
    df = bereid_voor(df_raw)

    d1_cnt      = df["d1_trend"].value_counts()
    h4_cnt      = df["h4_regime"].value_counts()
    cross_up_n  = df["cross_up"].sum()
    rsi_pb_n    = df["rsi_pb_ok"].sum()
    ema_bull_n  = df["ema_bull"].sum()
    print(f"  D1 trends   : {dict(d1_cnt)}")
    print(f"  H4 regimes  : {dict(h4_cnt)}")
    print(f"  Signalen potentieel (raw, per {MAANDEN} mnd):")
    print(f"    EMA9/21 cross up   : {cross_up_n:>4} ({cross_up_n/MAANDEN:.1f}/mnd)")
    print(f"    RSI pullback ok    : {rsi_pb_n:>4} ({rsi_pb_n/MAANDEN:.1f}/mnd)")
    print(f"    EMA bull stack     : {ema_bull_n:>4} ({ema_bull_n/MAANDEN:.1f}/mnd)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res: resultaten.append(res)

    print(); print("=" * 110)
    print("  EINDOVERZICHT v14 | ITERATIE 4"); print("=" * 110)
    print(f"  {'Variant':<20} {'P&L':>12} {'%/mnd':>7} {'Tr/mnd':>7} {'Win%':>6} "
          f"{'PF':>5} {'MaxDD':>7} {'Pos':>7} {'≥5%':>5}")
    print("  " + "─" * 105)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel = " *** DOEL!" if r["maand_pct"] >= 5 else (" ✓ GD" if r["maand_pct"] >= 3 else "")
        safe = " ⚠DD!" if r["max_dd"] > 0.09 else ""
        pm   = f"{r['pos_mnd']}/{r['tot_mnd']}"
        dm   = f"{r['doel_mnd']}/{r['tot_mnd']}"
        print(f"  {r['label']:<20} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['tr_per_mnd']:>6.1f}  {r['wr']:>4.1f}% {r['pf']:>5.2f} "
              f"{r['max_dd']*100:>6.1f}%  {pm:>6}  {dm:>4}{doel}{safe}")

    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        veilig = [r for r in resultaten if r["max_dd"] < 0.09]
        beste_safe = max(veilig, key=lambda x: x["maand_pct"]) if veilig else beste

        print(f"\n  BESTE TOTAAL : {beste['label']:<20} {beste['maand_pct']:+.2f}%/mnd")
        print(f"  BESTE SAFE   : {beste_safe['label']:<20} {beste_safe['maand_pct']:+.2f}%/mnd | "
              f"DD {beste_safe['max_dd']*100:.1f}%")
        print(f"  Signalen     : {beste['types']}")
        avg_mnd = beste['trades'] / beste['tot_mnd']
        print(f"  {beste['trades']} trades ({avg_mnd:.1f}/mnd) | WR {beste['wr']:.1f}% | "
              f"PF {beste['pf']:.2f} | {beste['pos_mnd']}/{beste['tot_mnd']} pos mnd | "
              f"{beste['doel_mnd']}/{beste['tot_mnd']} ≥5%")

        if beste["maand_pct"] >= 5:
            print(f"\n  ✓✓ DOEL 5%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 3:
            print(f"\n  {5-beste['maand_pct']:.1f}% van doel — aanpassen voor iteratie 5.")
        else:
            print(f"\n  {5-beste['maand_pct']:.1f}% van doel — fundamentele aanpassing nodig.")

    print("\n  ITERATIE OVERZICHT:")
    print("  V12-RSI50  : +0.44%/mnd | 4.6 tr/mnd | WR 29% | PF 1.22")
    print("  V13-Max4   : +0.39%/mnd | 2.3 tr/mnd | WR 70% | PF 1.94 (kwaliteit ↑, frequentie ↓)")
    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        print(f"  V14-Beste  : {beste['maand_pct']:+.2f}%/mnd | {beste['tr_per_mnd']:.1f} tr/mnd | "
              f"WR {beste['wr']:.1f}% | PF {beste['pf']:.2f}")
    print("=" * 110)


if __name__ == "__main__":
    main()
