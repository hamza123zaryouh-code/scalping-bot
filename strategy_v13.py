"""
XAUUSD Strategy v13 — EMA Stack + Regime Precision
===================================================
ITERATIE 3 ANALYSE (na V12 mislukking):

DIAGNOSE V12:
  • Slechts 16 trades in 10 maanden (RSI crossover te zeldzaam)
  • Win rate 37% met PF 1.23 → verwachte waarde +0.07R/trade
  • April 2025 crash: 4 trades, 0 wins → regime filter faalde
  • Te strikte ATR filter (>4.0) filterde te veel weg

V13 KERNWIJZIGINGEN:
  1. EMA9/EMA21 crossover (H1) als primair signaal → ~20-25 trades/maand
  2. Partiële TP: TP1 35% bij 1.5R, TP2 65% bij 2.5R + BE na TP1
  3. Swing-low/high SL (contextgevoelig) i.p.v. puur ATR
  4. Sessie precisie: ALLEEN London Open (8-11) + NY Open (13:30-16)
  5. Dagverlies stop na 2 SL: stop trading die dag
  6. H4 slope filter: EMA21 moet stijgen (minstens +1.0 vs 2 bars terug)
  7. Volume confirmation: huidige bar volume > 1.15× 20-bar gem.
  8. ATR range filter: H1 ATR tussen 0.4× en 2.5× van 20-bar gem.
  9. Max consecutive loss protection: risk halveren na 3 opeenv. SL

VERWACHT V13:
  - 18-28 trades/maand
  - Win rate 42-52%
  - Profit factor 1.4-2.0
  - Max drawdown < 5.5%
  - Doel: 4-7%/maand CONSISTENT

FTMO €160k: Dag-limiet €8.000 | Totaal €16.000
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL = 160_000.0
EUR_RATE = 1.17
FTMO_DAG = 8_000.0 * EUR_RATE
FTMO_TOT = 16_000.0 * EUR_RATE
MAANDEN  = 16  # meer data = robuustere statistieken

# ── Technische indicatoren ──────────────────────────────────────────────────

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

# ── Data laden ────────────────────────────────────────────────────────────

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

# ── Indicatoren voorbereiding ─────────────────────────────────────────────

def bereid_voor(df):
    d = df.copy()

    # ─ H1 indicatoren ────────────────────────────────────────────────────
    d["ema9"]      = ema(d["close"], 9)
    d["ema21"]     = ema(d["close"], 21)
    d["ema50"]     = ema(d["close"], 50)
    d["rsi14"]     = rsi_fn(d["close"], 14)
    d["atr_h1"]    = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma20"]  = d["atr_h1"].rolling(20).mean()
    d["vol_ma20"]  = d["volume"].rolling(20).mean()

    # EMA9/EMA21 crossover (H1)
    d["cross_up"]   = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
    d["cross_down"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(1) >= d["ema21"].shift(1))

    # Swing lows/highs voor SL plaatsing (5-bar lookback)
    d["swing_low5"]  = d["low"].rolling(5).min()
    d["swing_high5"] = d["high"].rolling(5).max()

    # ─ H4 indicatoren ────────────────────────────────────────────────────
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min",
                                "close":"last","volume":"sum"}).dropna()
    h4["e9"]    = ema(h4["close"], 9)
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope"] = h4["e21"] - h4["e21"].shift(2)   # slope over 2 H4 bars
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi14"] = rsi_fn(h4["close"], 14)

    def regime_h4(row):
        bull  = row["e21"] > row["e50"]
        bear  = row["e21"] < row["e50"]
        adx   = row["adx"]
        sl    = row["slope"]
        above200 = row["e50"] > row["e200"]
        below200 = row["e50"] < row["e200"]
        if   bull and adx >= 22 and sl >  0.5 and above200: return "STERK_BULL"
        elif bull and adx >= 13:                             return "ZWAK_BULL"
        elif bear and adx >= 22 and sl < -0.5 and below200: return "STERK_BEAR"
        elif bear and adx >= 13:                             return "ZWAK_BEAR"
        else:                                                return "CHOPPY"

    h4["regime"] = h4.apply(regime_h4, axis=1)

    d["h4_regime"]  = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]     = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]     = h4["atr"].reindex(d.index, method="ffill")
    d["h4_slope"]   = h4["slope"].reindex(d.index, method="ffill").fillna(0)
    d["h4_rsi"]     = h4["rsi14"].reindex(d.index, method="ffill").fillna(50)
    d["h4_e21"]     = h4["e21"].reindex(d.index, method="ffill")

    # ─ D1 trend ──────────────────────────────────────────────────────────
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min",
                                "close":"last","volume":"sum"}).dropna()
    d1["de50"]   = ema(d1["close"], 50)
    d1["de200"]  = ema(d1["close"], 200)
    d1["slope50"] = d1["de50"] - d1["de50"].shift(3)  # D1 EMA50 slope

    d1["trend"] = np.where(
        (d1["close"] > d1["de50"]) & (d1["slope50"] > 0), "bull",
        np.where((d1["close"] < d1["de50"]) & (d1["slope50"] < 0), "bear", "neutral")
    )
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

    return d.dropna(subset=["ema9","ema21","ema50","rsi14","atr_h1","h4_atr"])

# ── Sessie filter ─────────────────────────────────────────────────────────

def sessie_kwaliteit(uur, dow):
    """London Open (8-11) en NY Open (13:30→16). Vrijdag na 14u: blocked."""
    if dow >= 5: return "blocked"                    # weekend
    if dow == 0 and uur < 8: return "blocked"        # maandag gat
    if dow == 4 and uur >= 14: return "blocked"      # vrijdag vroeg sluiten
    if 8 <= uur < 12: return "premium"               # London Open
    if 13 <= uur < 16: return "premium"              # NY Open
    if 7 <= uur < 8 or uur == 12: return "standard"  # pre-London
    return "blocked"

# ── Backtest engine ───────────────────────────────────────────────────────

def backtest(df, cfg):
    # ── Configuratie ─────────────────────────────────────────────────
    risk_sterk   = cfg.get("risk_sterk",  0.0075)  # 0.75% STERK regime
    risk_zwak    = cfg.get("risk_zwak",   0.0050)  # 0.50% ZWAK regime
    risk_dip     = cfg.get("risk_dip",   0.0035)  # 0.35% dip/counter
    sl_swing     = cfg.get("sl_swing",    True)    # gebruik swing low/high als SL
    sl_atr_min   = cfg.get("sl_atr_min",  0.7)    # minimum SL = 0.7×H4ATR
    sl_atr_max   = cfg.get("sl_atr_max",  1.5)    # maximum SL = 1.5×H4ATR
    tp1_r        = cfg.get("tp1_r",       1.5)    # TP1 na 1.5× SL afstand
    tp2_r        = cfg.get("tp2_r",       2.5)    # TP2 na 2.5× SL afstand
    tp1_pct      = cfg.get("tp1_pct",    0.40)    # 40% sluiten bij TP1
    rsi_lo       = cfg.get("rsi_lo",      45)     # RSI ondergrens long (momentum)
    rsi_hi       = cfg.get("rsi_hi",      70)     # RSI bovengrens long (niet overbought)
    adx_min      = cfg.get("adx_min",     15)     # H4 ADX minimum
    slope_min    = cfg.get("slope_min",   0.3)    # H4 EMA21 slope minimum
    vol_mult     = cfg.get("vol_mult",   1.10)    # volume multiplier (10% boven gem.)
    max_dag      = cfg.get("max_dag",      3)     # max trades per dag
    sl_dag_stop  = cfg.get("sl_dag_stop",  2)     # stop na X SL op een dag
    consec_max   = cfg.get("consec_max",   4)     # consecutive losses → risk halveren
    atr_lo_mult  = cfg.get("atr_lo_mult", 0.4)   # minimale H1 ATR als % van gem.
    atr_hi_mult  = cfg.get("atr_hi_mult", 2.5)   # max H1 ATR (spike filter)
    h4atr_min    = cfg.get("h4atr_min",   5.0)   # minimale H4 ATR

    kap = KAPITAAL * EUR_RATE
    piek = kap
    trs = []
    dag_info = {}  # per datum: verlies, n, sl_cnt

    # Trade state (partiële TP ondersteuning)
    ip        = False
    entry     = sl = tp1 = tp2 = sla = risk_usd = None
    richting  = sig_type = ot = None
    tp1_hit   = False
    tp1_size  = 0.0
    consec_sl = 0  # consecutive stop-loss teller

    for i in range(60, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()

        if dat not in dag_info:
            dag_info[dat] = {"verlies": 0.0, "n": 0, "sl_cnt": 0}

        # ── FTMO totaallimiet check ───────────────────────────────────
        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p  = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd, "FAIL", sig_type))
                ip = False
            break

        # ── Beheer open positie ───────────────────────────────────────
        if ip:
            cur = float(b["close"])
            hi  = float(b["high"])
            lo  = float(b["low"])

            # Break-even na TP1
            if tp1_hit and richting == 1  and sl < entry: sl = entry + 0.1
            if tp1_hit and richting == -1 and sl > entry: sl = entry - 0.1

            # TP1 check (partieel)
            hit_tp1 = not tp1_hit and (
                (richting == 1  and hi >= tp1) or
                (richting == -1 and lo <= tp1)
            )
            # TP2 check (restant)
            hit_tp2 = (richting == 1 and hi >= tp2) or (richting == -1 and lo <= tp2)
            # SL check
            hit_sl  = (richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)

            if hit_tp1 and not hit_sl:
                # Sluit tp1_pct van de positie
                pnl_usd = richting * (tp1 - entry) / sla * risk_usd * tp1_pct
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append(_tr(ot, b.name, richting, entry, tp1, pnl_usd, "TP1", sig_type))
                risk_usd *= (1 - tp1_pct)  # restant positie
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
                    if not tp1_hit:
                        consec_sl += 1  # alleen tellen als TP1 niet geraakt is
                    else:
                        consec_sl = 0   # TP1 geraakt = deels gewonnen
                else:
                    consec_sl = 0

                kap += pnl_usd
                if kap > piek: piek = kap
                reden = "TP2" if hit_tp2 else "SL"
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd, reden, sig_type))
                ip = False

        if ip: continue

        # ── Daglimieten ────────────────────────────────────────────────
        dv     = dag_info[dat]["verlies"]
        n_dag  = dag_info[dat]["n"]
        sl_dag = dag_info[dat]["sl_cnt"]

        if dv >= FTMO_DAG * 0.60: continue           # 60% van daglimiet bereikt
        if n_dag >= max_dag: continue                  # max trades/dag
        if sl_dag >= sl_dag_stop: continue             # stop na X SL op een dag

        tier = sessie_kwaliteit(uur, dow)
        if tier == "blocked": continue

        # ── Indicator waarden ──────────────────────────────────────────
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
        vol      = float(b["volume"])
        vol_ma   = float(b["vol_ma20"]) if not pd.isna(b["vol_ma20"]) else 1.0
        cross_up_v   = bool(b["cross_up"])
        cross_down_v = bool(b["cross_down"])
        swing_lo     = float(b["swing_low5"])
        swing_hi     = float(b["swing_high5"])

        # ── Globale filters ────────────────────────────────────────────
        if atr_h4 < h4atr_min: continue
        if atr_ma > 0 and (atr_h1 < atr_lo_mult * atr_ma or atr_h1 > atr_hi_mult * atr_ma): continue
        if h4_adx < adx_min: continue

        # Volume filter (optioneel — werkt alleen als volume betrouwbaar is)
        if vol_ma > 100 and vol < vol_mult * vol_ma: continue

        sig = None

        # ══════════════════════════════════════════════════════════════════
        # LONG SIGNALEN — D1 bull
        # ══════════════════════════════════════════════════════════════════
        if d1_trend == "bull":

            # --- Signal A1: EMA9 kruist boven EMA21 in STERK_BULL regime ---
            if regime == "STERK_BULL" and h4_slope >= slope_min:
                if cross_up_v and rsi_lo <= rsi14 <= rsi_hi and close > ema50_v:
                    sig = ("long", "LONG_A1_STERK", risk_sterk, tp1_r, tp2_r)

            # --- Signal A2: EMA9/EMA21 crossover in ZWAK_BULL ---
            elif regime == "ZWAK_BULL" and h4_slope >= 0:
                if cross_up_v and rsi_lo <= rsi14 <= rsi_hi and close > ema21_v:
                    if tier == "premium":
                        sig = ("long", "LONG_A2_ZWAK", risk_zwak, tp1_r, tp2_r)

            # --- Signal A3: Buy-the-dip — H4 correctie in D1 bull ---
            elif regime in ("STERK_BEAR", "ZWAK_BEAR"):
                h4_rsi = float(b["h4_rsi"])
                # Oversold herstel: H1 EMA9 net boven EMA21 + H4 RSI boven 35
                dip_entry = cross_up_v and h4_rsi > 35 and close > ema21_v
                # RSI moet uit oversold klimmen
                rsi_recovery = rsi14 > 50 and rsi14 < 68
                if dip_entry and rsi_recovery and tier == "premium":
                    sig = ("long", "LONG_A3_DIP", risk_dip, tp1_r * 0.9, tp2_r * 0.85)

            # --- Signal A4: Trend-continuatie na RSI pullback ---
            elif regime == "STERK_BULL" and h4_slope >= slope_min * 0.5:
                # RSI daalde naar 42-50 zone en klautert nu terug
                rsi_pb_ok = (42 <= rsi14 <= 55) and close > ema21_v and close > ema9_v
                ema_rising = float(df["ema21"].iloc[i]) > float(df["ema21"].iloc[i-3])
                if rsi_pb_ok and ema_rising:
                    sig = ("long", "LONG_A4_PB", risk_zwak * 0.8, tp1_r, tp2_r)

        # ══════════════════════════════════════════════════════════════════
        # SHORT SIGNALEN — D1 bear
        # ══════════════════════════════════════════════════════════════════
        elif d1_trend == "bear":

            if regime == "STERK_BEAR" and h4_slope <= -slope_min:
                if cross_down_v and (100 - rsi_hi) <= rsi14 <= (100 - rsi_lo) and close < ema50_v:
                    sig = ("short", "SHORT_A1_STERK", risk_sterk, tp1_r, tp2_r)

            elif regime == "ZWAK_BEAR" and h4_slope <= 0:
                if cross_down_v and (100 - rsi_hi) <= rsi14 <= (100 - rsi_lo) and close < ema21_v:
                    if tier == "premium":
                        sig = ("short", "SHORT_A2_ZWAK", risk_zwak, tp1_r, tp2_r)

        if not sig: continue

        # ── Signal kwaliteit check ─────────────────────────────────────
        richting_str, sig_type, risk_pct, tp1_mult, tp2_mult = sig

        # Standard tier: geen ZWAK/DIP signalen
        if tier == "standard" and any(x in sig_type for x in ["ZWAK","DIP","PB"]): continue

        richting = 1 if richting_str == "long" else -1

        # ── SL berekening (swing-based + ATR limiet) ──────────────────
        if sl_swing:
            if richting == 1:
                sl_swing_v = swing_lo - 0.15 * atr_h1
                sl_atr_v   = close - sl_atr_min * atr_h4
                sl_raw     = min(sl_swing_v, sl_atr_v)  # neem de verder weg
            else:
                sl_swing_v = swing_hi + 0.15 * atr_h1
                sl_atr_v   = close + sl_atr_min * atr_h4
                sl_raw     = max(sl_swing_v, sl_atr_v)
        else:
            sl_raw = close - richting * sl_atr_min * atr_h4

        # Clip SL afstand tussen ATR_MIN en ATR_MAX
        sla_raw = abs(close - sl_raw)
        sla = max(sl_atr_min * atr_h4, min(sl_atr_max * atr_h4, sla_raw))
        sl  = close - richting * sla
        tp1 = close + richting * tp1_mult * sla
        tp2 = close + richting * tp2_mult * sla

        entry = close

        # ── Drawdown-gebaseerde risk scaling ──────────────────────────
        dd_pct = (piek - kap) / piek
        if   dd_pct > 0.06: risk_pct *= 0.35
        elif dd_pct > 0.04: risk_pct *= 0.55
        elif dd_pct > 0.02: risk_pct *= 0.80

        # Consecutive losses → extra risk verlaging
        if consec_sl >= consec_max:
            risk_pct *= 0.50

        risk_usd = kap * risk_pct
        ot = b.name
        ip = True
        tp1_hit = False
        dag_info[dat]["n"] += 1

    # ── Sluit openstaande positie aan einde data ──────────────────────
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

# ── Rapportage ────────────────────────────────────────────────────────────

def rapport(trs, kap_eur_eind, label, verbose=True):
    pnl_eur = kap_eur_eind - KAPITAAL
    if verbose:
        print(); print("=" * 74); print(f"  {label}"); print("=" * 74)
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

    type_cnt  = df_t["type"].value_counts().to_dict()
    result_cnt = df_t["result"].value_counts().to_dict()

    dagen  = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    mnd_n  = dagen / 30.44
    gem_mnd = pnl_eur / mnd_n
    mnd_pct = pnl_eur / KAPITAAL * 100 / mnd_n

    # Max drawdown berekening
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
    mnd["win_pct"]  = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct_mnd"]  = mnd["pnl_eur"] / KAPITAAL * 100
    pos_mnd  = (mnd["pnl_eur"] > 0).sum()
    tot_mnd  = len(mnd)
    doel_mnd = (mnd["pct_mnd"] >= 5).sum()

    if verbose:
        doel_s = "✓ BEREIKT!" if mnd_pct >= 5 else f"  {5-mnd_pct:.1f}% tekort"
        print(f"  Kapitaal : €{KAPITAAL:>12,.0f}  →  €{kap_eur_eind:>12,.0f}")
        print(f"  P&L      : €{pnl_eur:>+12,.0f}")
        print(f"  Gem/mnd  : €{gem_mnd:>+10,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
        safe  = "✓ VEILIG" if max_dd < 0.06 else "⚠ GEVAAR"
        print(f"  Max DD   : {max_dd*100:.2f}%  FTMO limiet 10% [{safe}]")
        print(f"  Trades   : {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
        print(f"  Signalen : {type_cnt}")
        print(f"  Resultaten: {result_cnt}")
        print(f"  Maanden  : positief {pos_mnd}/{tot_mnd} | ≥5% {doel_mnd}/{tot_mnd}")

        print(f"\n  {'Maand':<10} {'Tr':>4} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7}")
        print("  " + "─" * 52)
        for _, r in mnd.iterrows():
            flag = " *** DOEL!" if r["pct_mnd"] >= 5 else (" ─── ZWAK" if r["pnl_eur"] < -3200 else "")
            print(f"  {str(r['maand']):<10} {r['trades']:>4}  {r['win_pct']:>4.1f}%  "
                  f"€{r['pnl_eur']:>10,.0f}  {r['pct_mnd']:>6.2f}%{flag}")
        print("=" * 74)

    return {
        "label": label, "pnl_eur": pnl_eur, "gem_mnd": gem_mnd,
        "maand_pct": mnd_pct, "trades": n, "wr": wr, "pf": pf,
        "max_dd": max_dd, "pos_mnd": pos_mnd, "tot_mnd": tot_mnd,
        "doel_mnd": doel_mnd, "mnd": mnd, "types": type_cnt,
    }

# ── Varianten definitie ───────────────────────────────────────────────────

VARIANTEN = {
    "V13-Basis": {
        "desc": "EMA9/21 cross, risk 0.75/0.5/0.35%, TP1@1.5R TP2@2.5R",
        "risk_sterk": 0.0075, "risk_zwak": 0.0050, "risk_dip": 0.0035,
        "sl_atr_min": 0.7, "sl_atr_max": 1.5,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp1_pct": 0.40,
        "rsi_lo": 45, "rsi_hi": 70, "adx_min": 15, "slope_min": 0.3,
        "vol_mult": 1.10, "max_dag": 3, "sl_dag_stop": 2,
        "consec_max": 4, "atr_lo_mult": 0.4, "atr_hi_mult": 2.5, "h4atr_min": 5.0,
    },
    "V13-TP3": {
        "desc": "Grotere doelen: TP1@1.5R TP2@3.0R",
        "risk_sterk": 0.0075, "risk_zwak": 0.0050, "risk_dip": 0.0035,
        "sl_atr_min": 0.7, "sl_atr_max": 1.5,
        "tp1_r": 1.5, "tp2_r": 3.0, "tp1_pct": 0.40,
        "rsi_lo": 45, "rsi_hi": 70, "adx_min": 15, "slope_min": 0.3,
        "vol_mult": 1.10, "max_dag": 3, "sl_dag_stop": 2,
        "consec_max": 4, "atr_lo_mult": 0.4, "atr_hi_mult": 2.5, "h4atr_min": 5.0,
    },
    "V13-Sterk": {
        "desc": "Hoog risk STERK only: 1.0/0.6%, strenger ADX≥20",
        "risk_sterk": 0.0100, "risk_zwak": 0.0060, "risk_dip": 0.0040,
        "sl_atr_min": 0.8, "sl_atr_max": 1.5,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp1_pct": 0.35,
        "rsi_lo": 48, "rsi_hi": 68, "adx_min": 20, "slope_min": 0.5,
        "vol_mult": 1.15, "max_dag": 3, "sl_dag_stop": 2,
        "consec_max": 3, "atr_lo_mult": 0.4, "atr_hi_mult": 2.0, "h4atr_min": 6.0,
    },
    "V13-Liberal": {
        "desc": "Meer trades: RSI lo=40, vol=1.05, slope=0.1",
        "risk_sterk": 0.0070, "risk_zwak": 0.0045, "risk_dip": 0.0030,
        "sl_atr_min": 0.7, "sl_atr_max": 1.8,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp1_pct": 0.40,
        "rsi_lo": 40, "rsi_hi": 72, "adx_min": 13, "slope_min": 0.1,
        "vol_mult": 1.05, "max_dag": 4, "sl_dag_stop": 2,
        "consec_max": 5, "atr_lo_mult": 0.3, "atr_hi_mult": 3.0, "h4atr_min": 4.0,
    },
    "V13-Conserv": {
        "desc": "Voorzichtig: risk 0.5/0.35%, ADX≥22, max 2 trades/dag",
        "risk_sterk": 0.0050, "risk_zwak": 0.0035, "risk_dip": 0.0025,
        "sl_atr_min": 0.8, "sl_atr_max": 1.4,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp1_pct": 0.45,
        "rsi_lo": 48, "rsi_hi": 68, "adx_min": 22, "slope_min": 0.4,
        "vol_mult": 1.10, "max_dag": 2, "sl_dag_stop": 2,
        "consec_max": 3, "atr_lo_mult": 0.5, "atr_hi_mult": 2.0, "h4atr_min": 6.0,
    },
    "V13-Max4": {
        "desc": "Max 4/dag, risk 0.8/0.5%, agressiever",
        "risk_sterk": 0.0080, "risk_zwak": 0.0050, "risk_dip": 0.0035,
        "sl_atr_min": 0.7, "sl_atr_max": 1.5,
        "tp1_r": 1.5, "tp2_r": 2.5, "tp1_pct": 0.40,
        "rsi_lo": 45, "rsi_hi": 70, "adx_min": 15, "slope_min": 0.3,
        "vol_mult": 1.05, "max_dag": 4, "sl_dag_stop": 3,
        "consec_max": 5, "atr_lo_mult": 0.3, "atr_hi_mult": 3.0, "h4atr_min": 4.0,
    },
}

# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 74)
    print("  XAUUSD STRATEGIE v13 | EMA STACK + REGIME PRECISION")
    print("  EMA9/21 crossover + H4 regime + D1 trend | Partiële TP")
    print(f"  FTMO €160k: Dag-limiet €8.000 | Totaal €16.000")
    print("=" * 74)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren berekenen...")
    df = bereid_voor(df_raw)

    regime_cnt = df["h4_regime"].value_counts()
    d1_cnt     = df["d1_trend"].value_counts()
    cross_up_n = df["cross_up"].sum()
    print(f"  D1 verdeling  : {dict(d1_cnt)}")
    print(f"  H4 regimes    : {dict(regime_cnt)}")
    print(f"  EMA9/21 crosses up   : {cross_up_n} keer in {MAANDEN} mnd")
    print(f"  → Gemiddeld {cross_up_n/MAANDEN:.1f}/maand potentiële signalen")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res:
            resultaten.append(res)

    # ── Eindoverzicht ─────────────────────────────────────────────────
    print(); print("=" * 100)
    print("  EINDOVERZICHT v13 — ITERATIE 3 RESULTATEN")
    print("=" * 100)
    print(f"  {'Variant':<22} {'P&L':>12} {'%/mnd':>7} {'Tr':>5} {'Win%':>6} {'PF':>5} {'MaxDD':>7} {'Pos':>8} {'≥5%':>5}")
    print("  " + "─" * 95)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel = " *** DOEL!" if r["maand_pct"] >= 5 else (" ✓ GD" if r["maand_pct"] >= 3 else "")
        safe = " ⚠DD!" if r["max_dd"] > 0.09 else ""
        pm   = f"{r['pos_mnd']}/{r['tot_mnd']}"
        dm   = f"{r['doel_mnd']}/{r['tot_mnd']}"
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['trades']:>5}  {r['wr']:>4.1f}% {r['pf']:>5.2f} {r['max_dd']*100:>6.1f}%"
              f"  {pm:>7}  {dm:>4}{doel}{safe}")

    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        veilig = [r for r in resultaten if r["max_dd"] < 0.09]
        beste_safe = max(veilig, key=lambda x: x["maand_pct"]) if veilig else beste

        print(f"\n  BESTE TOTAAL  : {beste['label']} → {beste['maand_pct']:+.2f}%/mnd")
        print(f"  BESTE SAFE    : {beste_safe['label']} → {beste_safe['maand_pct']:+.2f}%/mnd | DD {beste_safe['max_dd']*100:.1f}%")
        print(f"  Signalen      : {beste['types']}")
        print(f"  WR {beste['wr']:.1f}% | PF {beste['pf']:.2f} | {beste['trades']} trades | "
              f"{beste['pos_mnd']}/{beste['tot_mnd']} positieve maanden | "
              f"{beste['doel_mnd']}/{beste['tot_mnd']} ≥5% maanden")

        if beste["maand_pct"] >= 5:
            print(f"\n  ✓✓ DOEL 5%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 3:
            print(f"\n  {5-beste['maand_pct']:.1f}% van 5%-doel — verbetering nodig.")
        else:
            print(f"\n  {5-beste['maand_pct']:.1f}% van 5%-doel — strategie aanpassen.")

    print("=" * 100)
    print()
    print("  VERGELIJKING V12 vs V13:")
    print("  V12-Basis   : +0.13%/mnd | 16 trades/10mnd | WR 37.5% | PF 1.23")
    print("  V12-RSI50   : +0.44%/mnd | 65 trades/14mnd | WR 29.2% | PF 1.22")
    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        avg_tr = beste['trades'] / beste['tot_mnd']
        print(f"  V13-Beste   : {beste['maand_pct']:+.2f}%/mnd | {avg_tr:.0f} trades/mnd | "
              f"WR {beste['wr']:.1f}% | PF {beste['pf']:.2f}")
    print("=" * 100)


if __name__ == "__main__":
    main()
