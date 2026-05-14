"""
XAUUSD Strategy v12 — Buy The Dip Expert
=========================================
CRUCIALE INZICHT na analyse V11:
  D1 trend = 99.7% BULL (goud in massieve bull run 2025-2026)
  H4 BEAR perioden = correcties BINNEN de bull trend = KOOPKANSEN
  STERK_BEAR + D1 BULL = niet shorten, maar WACHTEN op herstel om long te gaan

STRATEGIE:
  1. D1 = BULL (macro richting)
  2. H4 regime bepaalt entry-kwaliteit:
     - STERK_BULL / ZWAK_BULL → trend-continuatie longs (RSI pullback naar <45)
     - ZWAK_BEAR / STERK_BEAR → "buy the dip" longs als RSI-14 herstelt boven 45
  3. H1 entry: RSI-14 daalt onder drempel → stijgt terug boven drempel (V-reversal)
  4. H1 close > H1 EMA21 als bevestiging

SHORT signalen: ALLEEN als D1 = bear (zelden → <1% van de tijd)

RESULTAAT VERWACHTING:
  - 15-25 trades/maand (2-3× meer dan V11)
  - WR 40-55% (entries op correctie-bottoms in bull trend)
  - PF 1.5-2.5
  - Doel: 5-8%/maand

FTMO €160k: Dag-limiet €8.000 | Totaal €16.000
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL  = 160_000.0
EUR_RATE  = 1.17
FTMO_DAG  = 8_000.0 * EUR_RATE
FTMO_TOT  = 16_000.0 * EUR_RATE
MAANDEN   = 13

# ── Indicatoren ────────────────────────────────────────────────────────────────

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
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p-1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p-1, adjust=False).mean() / at
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p-1, adjust=False).mean().fillna(0)

# ── Data & voorbereiding ───────────────────────────────────────────────────────

def laad():
    e = datetime.utcnow()
    s = e - timedelta(days=MAANDEN*31 + 30)
    print(f"  Download GC=F H1: {s.date()} – {e.date()}")
    df = yf.download("GC=F", start=s.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"),
                     interval="1h", progress=False, auto_adjust=True)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open","high","low","close","volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} – {df.index[-1].date()})")
    return df

def bereid_voor(df):
    d = df.copy()

    # H1
    d["rsi14"]    = rsi_fn(d["close"], 14)
    d["rsi14_p"]  = d["rsi14"].shift(1)
    d["ema9"]     = ema(d["close"], 9)
    d["ema21"]    = ema(d["close"], 21)
    d["ema50"]    = ema(d["close"], 50)
    d["atr_h1"]   = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma20"] = d["atr_h1"].rolling(20).mean()

    # H4
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min",
                                 "close":"last","volume":"sum"}).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope"] = h4["e21"] - h4["e21"].shift(3)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi14"] = rsi_fn(h4["close"], 14)

    def regime(row):
        bull = row["e21"] > row["e50"]
        bear = row["e21"] < row["e50"]
        adx  = row["adx"]
        sl3  = row["slope"]
        if   bull and adx >= 25 and sl3 > 0 and row["e50"] > row["e200"]: return "STERK_BULL"
        elif bull and adx >= 13:                                            return "ZWAK_BULL"
        elif bear and adx >= 25 and sl3 < 0 and row["e50"] < row["e200"]: return "STERK_BEAR"
        elif bear and adx >= 13:                                            return "ZWAK_BEAR"
        else:                                                                return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)
    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")
    d["h4_rsi"]    = h4["rsi14"].reindex(d.index, method="ffill").fillna(50)

    # D1
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min",
                                 "close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(
        (d1["close"] > d1["de50"]) & (d1["de50"] > d1["de200"]), "bull",
        np.where((d1["close"] < d1["de50"]) & (d1["de50"] < d1["de200"]), "bear", "neutral")
    )
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bull")

    return d.dropna(subset=["rsi14","ema9","ema21","atr_h1","h4_atr","h4_regime"])

# ── Sessie ─────────────────────────────────────────────────────────────────────

def sessie_tier(uur, dow):
    if dow == 0 and uur < 10: return "blocked"
    if dow == 4 and uur >= 14: return "blocked"
    if 8 <= uur < 12 or 13 <= uur < 17: return "premium"
    if 7 <= uur < 8 or 17 <= uur < 19: return "standard"
    return "blocked"

# ── Backtest ───────────────────────────────────────────────────────────────────

def backtest(df, cfg):
    # Risk-instellingen
    risk_trend  = cfg.get("risk_trend",  0.010)   # % risico in bull-regime (trend)
    risk_dip    = cfg.get("risk_dip",    0.008)   # % risico bij "buy the dip" (bear-regime in bull)
    sl_mult     = cfg.get("sl_mult",     0.6)     # SL = sl_mult × H4 ATR
    tp_trend    = cfg.get("tp_trend",    2.5)     # RR voor trend-entries
    tp_dip      = cfg.get("tp_dip",     2.0)     # RR voor dip-entries (meer conservatief)
    be_mult     = cfg.get("be_mult",     1.0)     # break-even na 1× SL dist winst
    # RSI drempels
    rsi_pull    = cfg.get("rsi_pull",    45)      # pullback drempel in bull regime
    rsi_dip     = cfg.get("rsi_dip",     40)      # oversold drempel voor "buy the dip"
    rsi_recov   = cfg.get("rsi_recov",   48)      # herstel boven deze waarde = entry voor dip
    max_pd      = cfg.get("max_pd",       3)      # max trades/dag (totaal)

    kap = KAPITAAL * EUR_RATE; piek = kap
    trs = []; dag_info = {}
    ip = False
    entry = sl = tp = sla = risk_usd = richting = sig_type = ot = None

    for i in range(50, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()

        if dat not in dag_info:
            dag_info[dat] = {"verlies": 0.0, "n": 0}

        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd, "FAIL", sig_type))
                ip = False
            break

        if ip:
            cur = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])
            if richting == 1  and (cur - entry) >= be_mult * sla and sl < entry: sl = entry
            if richting == -1 and (entry - cur) >= be_mult * sla and sl > entry: sl = entry
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
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd,
                               "TP" if hit_tp else "SL", sig_type))
                ip = False

        if ip: continue

        dv = dag_info[dat]["verlies"]
        n  = dag_info[dat]["n"]

        tier = sessie_tier(uur, dow)
        if tier == "blocked": continue
        if dv >= FTMO_DAG * 0.65: continue
        if n >= max_pd: continue

        regime   = b["h4_regime"]
        d1_trend = b["d1_trend"]
        rsi14    = float(b["rsi14"])
        rsi14_p  = float(b["rsi14_p"]) if not pd.isna(b["rsi14_p"]) else rsi14
        close    = float(b["close"])
        ema21_v  = float(b["ema21"])
        ema50_v  = float(b["ema50"])
        atr_h1   = float(b["atr_h1"])
        atr_h4   = float(b["h4_atr"])
        atr_ma   = float(b["atr_ma20"]) if not pd.isna(b["atr_ma20"]) else atr_h1
        h4_adx   = float(b["h4_adx"])

        if atr_h4 < 4.0: continue
        if atr_h1 > 3.0 * atr_ma: continue   # volatiliteitsspike

        sig = None

        # ══════════════════════════════════════════════════════════════════════
        # LONG signalen (primair — D1 BULL)
        # ══════════════════════════════════════════════════════════════════════
        if d1_trend == "bull":

            # 1. TREND CONTINUATIE: H4 bull regime + RSI pullback naar <rsi_pull → herstel
            if regime in ("STERK_BULL", "ZWAK_BULL") and h4_adx >= 15:
                # RSI daalde onder rsi_pull en stijgt nu terug (pullback hersteld)
                pullback_ok = (rsi14_p < rsi_pull) and (rsi14 >= rsi_pull)
                ema_ok      = close > ema21_v   # boven middellange MA
                if pullback_ok and ema_ok:
                    kw = "TREND" if regime == "STERK_BULL" else "ZWAK_TREND"
                    rk = risk_trend if regime == "STERK_BULL" else risk_dip
                    tp_r = tp_trend if regime == "STERK_BULL" else tp_dip
                    sig  = ("long", f"LONG_{kw}", rk, tp_r)

            # 2. BUY THE DIP: H4 bear regime (correctie in D1 bull) → koop op herstel
            elif regime in ("STERK_BEAR", "ZWAK_BEAR") and h4_adx >= 13:
                # RSI daalde naar oversold en herstelt nu (correctie-bodem gevonden)
                dip_ok      = (rsi14_p < rsi_dip) and (rsi14 >= rsi_recov)
                # H1 prijs moet terug boven EMA21 stijgen (momentum keert)
                ema_recover = close > ema21_v
                # Veiligheidscheck: H4 RSI ook niet meer in vrije val
                h4_rsi_ok   = float(b["h4_rsi"]) > 30
                if dip_ok and ema_recover and h4_rsi_ok:
                    sig = ("long", "LONG_DIP", risk_dip, tp_dip)

            # 3. CHOPPY met sterke H1 momentum (minder frequent)
            elif regime == "CHOPPY" and tier == "premium" and h4_adx < 13:
                choppy_ok = (rsi14_p < 42) and (rsi14 >= 50) and (close > ema50_v)
                if choppy_ok:
                    sig = ("long", "LONG_CHOPPY", risk_dip * 0.6, tp_dip * 0.8)

        # ══════════════════════════════════════════════════════════════════════
        # SHORT signalen (zeldzaam — alleen echte D1 BEAR)
        # ══════════════════════════════════════════════════════════════════════
        elif d1_trend == "bear":
            if regime in ("STERK_BEAR", "ZWAK_BEAR") and h4_adx >= 15:
                short_ok = (rsi14_p > (100 - rsi_pull)) and (rsi14 <= (100 - rsi_pull))
                ema_ok   = close < ema21_v
                if short_ok and ema_ok:
                    sig = ("short", "SHORT_TREND", risk_trend, tp_trend)

        if not sig: continue
        if tier == "standard" and "ZWAK" in sig[1]: continue   # standard: geen zwak

        richting_str, sig_type, risk_pct, tp_r = sig
        richting = 1 if richting_str == "long" else -1
        entry    = close
        sla      = sl_mult * atr_h4
        sl       = entry - richting * sla
        tp       = entry + richting * tp_r * sla

        dd_pct = (piek - kap) / piek
        if   dd_pct > 0.06: risk_pct *= 0.40
        elif dd_pct > 0.03: risk_pct *= 0.65

        risk_usd = kap * risk_pct
        ot = b.name; ip = True
        dag_info[dat]["n"] += 1

    if ip:
        exit_p = float(df.iloc[-1]["close"])
        pnl_usd = richting * (exit_p - entry) / sla * risk_usd
        kap += pnl_usd
        trs.append(_tr(ot, df.index[-1], richting, entry, exit_p, pnl_usd, "OPEN", sig_type))

    return trs, kap / EUR_RATE

def _tr(ti, to, rich, entry, exit_p, pnl_usd, result, stype):
    return {"in": ti, "uit": to, "rich": rich, "entry": entry, "exit": exit_p,
            "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE,
            "result": result, "type": stype}

# ── Rapport ────────────────────────────────────────────────────────────────────

def rapport(trs, kap_eur_eind, label, verbose=True):
    pnl_eur = kap_eur_eind - KAPITAAL
    if verbose:
        print(); print("="*72); print(f"  {label}"); print("="*72)
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

    # Signaaltype verdeling
    type_cnt = df_t["type"].value_counts().to_dict()

    dagen  = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    mnd_n  = dagen / 30.44
    gem_mnd= pnl_eur / mnd_n
    mnd_pct= pnl_eur / KAPITAAL * 100 / mnd_n

    cap_lp = KAPITAAL * EUR_RATE; pk_lp = cap_lp; max_dd = 0.0
    for t in trs:
        cap_lp += t["pnl_usd"]
        if cap_lp > pk_lp: pk_lp = cap_lp
        dd = pk_lp - cap_lp
        if dd > max_dd: max_dd = dd

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_eur","count"), pnl_eur=("pnl_eur","sum"),
        wins=("pnl_eur", lambda x: (x>0).sum()),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct_mnd"] = mnd["pnl_eur"] / KAPITAAL * 100
    pos_mnd = (mnd["pnl_eur"] > 0).sum(); tot_mnd = len(mnd)
    doel_mnd = (mnd["pct_mnd"] >= 5).sum()

    if verbose:
        doel_s = "BEREIKT!" if mnd_pct >= 5 else f"{5-mnd_pct:.1f}% tekort"
        print(f"  Kapitaal : €{KAPITAAL:>12,.0f}  →  €{kap_eur_eind:>12,.0f}")
        print(f"  P&L      : €{pnl_eur:>+12,.0f}")
        print(f"  Gem/maand: €{gem_mnd:>+10,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
        print(f"  Max DD   : €{max_dd/EUR_RATE:>8,.0f}  (FTMO limiet €16.000) {'⚠ GEVAARLIJK' if max_dd/EUR_RATE > 14000 else '✓ VEILIG'}")
        print(f"  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
        print(f"  Signaaltypen: {type_cnt}")
        print(f"  Maanden: positief {pos_mnd}/{tot_mnd} | ≥5% {doel_mnd}/{tot_mnd}")

        print(f"\n  {'Maand':<10} {'Tr':>4} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7}")
        print("  " + "-"*50)
        for _, r in mnd.iterrows():
            flag = " *** DOEL!" if r["pct_mnd"] >= 5 else (" --- ZWAK" if r["pnl_eur"] < -4000 else "")
            print(f"  {str(r['maand']):<10} {r['trades']:>4}  {r['win_pct']:>4.1f}%  €{r['pnl_eur']:>10,.0f}  {r['pct_mnd']:>6.2f}%{flag}")
        print("="*72)

    return {"label":label,"pnl_eur":pnl_eur,"gem_mnd":gem_mnd,
            "maand_pct":mnd_pct,"trades":n,"wr":wr,"pf":pf,
            "max_dd_eur":max_dd/EUR_RATE,"pos_mnd":pos_mnd,"tot_mnd":tot_mnd,
            "doel_mnd":doel_mnd,"mnd":mnd,"types":type_cnt}

# ── Varianten ──────────────────────────────────────────────────────────────────

VARIANTEN = {
    "V12-Basis": {
        "desc": "Trend(1%) + Dip(0.8%), SL 0.6×H4ATR, TP 2.5/2.0",
        "risk_trend":0.010, "risk_dip":0.008,
        "sl_mult":0.6, "tp_trend":2.5, "tp_dip":2.0,
        "be_mult":1.0, "rsi_pull":45, "rsi_dip":40, "rsi_recov":48, "max_pd":3,
    },
    "V12-TP3": {
        "desc": "Grotere doelen: TP 3.0/2.5",
        "risk_trend":0.010, "risk_dip":0.008,
        "sl_mult":0.6, "tp_trend":3.0, "tp_dip":2.5,
        "be_mult":1.0, "rsi_pull":45, "rsi_dip":40, "rsi_recov":48, "max_pd":3,
    },
    "V12-Risk15": {
        "desc": "Hogere risk: 1.5%/1.0%, TP 2.5/2.0",
        "risk_trend":0.015, "risk_dip":0.010,
        "sl_mult":0.6, "tp_trend":2.5, "tp_dip":2.0,
        "be_mult":1.0, "rsi_pull":45, "rsi_dip":40, "rsi_recov":48, "max_pd":3,
    },
    "V12-RSI50": {
        "desc": "Strenger pullback (RSI<50), dip herstel RSI<35→>50",
        "risk_trend":0.010, "risk_dip":0.008,
        "sl_mult":0.6, "tp_trend":2.5, "tp_dip":2.0,
        "be_mult":1.0, "rsi_pull":50, "rsi_dip":35, "rsi_recov":50, "max_pd":3,
    },
    "V12-SL04": {
        "desc": "Strakke SL (0.4×H4ATR), meer risico ruimte → hogere risk",
        "risk_trend":0.012, "risk_dip":0.008,
        "sl_mult":0.4, "tp_trend":2.5, "tp_dip":2.0,
        "be_mult":1.0, "rsi_pull":45, "rsi_dip":40, "rsi_recov":48, "max_pd":4,
    },
    "V12-Max4": {
        "desc": "Max 4 trades/dag, risk 1.2%/0.9%",
        "risk_trend":0.012, "risk_dip":0.009,
        "sl_mult":0.6, "tp_trend":2.5, "tp_dip":2.0,
        "be_mult":1.0, "rsi_pull":45, "rsi_dip":40, "rsi_recov":48, "max_pd":4,
    },
}

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("="*72)
    print("  XAUUSD STRATEGIE v12 | BUY THE DIP | DOEL: 5–8%/MAAND")
    print("  Trend + Buy-the-dip LONG in D1 BULL | Correcties = kansen")
    print("  FTMO €160k: Dag-limiet €8.000 | Totaal €16.000")
    print("="*72)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren bouwen...")
    df = bereid_voor(df_raw)

    regime_cnt = df["h4_regime"].value_counts()
    d1_cnt     = df["d1_trend"].value_counts()
    bull_bars  = (df["d1_trend"] == "bull").sum()
    print(f"  D1 verdeling: {dict(d1_cnt)}")
    print(f"  → D1 BULL: {bull_bars}/{len(df)} bars ({100*bull_bars/len(df):.1f}%)")
    print(f"  H4 regimes in D1-BULL periode:")
    bull_df = df[df["d1_trend"] == "bull"]
    for r, c in bull_df["h4_regime"].value_counts().items():
        pct = 100 * c / len(bull_df)
        note = " ← DIP KANSEN" if r in ("STERK_BEAR","ZWAK_BEAR") else " ← TREND KANSEN"
        print(f"    {r:<15}: {c:>5} bars ({pct:>4.1f}%){note}")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res: resultaten.append(res)

    print(); print("="*72)
    print("  EINDOVERZICHT v12"); print("="*72)
    print(f"  {'Variant':<22} {'EUR P&L':>12} {'%/mnd':>7} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD':>10} {'Pos/Tot':>8}")
    print("  "+"-"*90)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel  = " *** DOEL!" if r["maand_pct"] >= 5 else (" ✓ TOP" if r["maand_pct"] >= 3 else "")
        safe  = " ⚠ DD!" if r["max_dd_eur"] > 16000 else ""
        pm    = f"{r['pos_mnd']}/{r['tot_mnd']}"
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  €{r['max_dd_eur']:>7,.0f}  {pm:>8}{doel}{safe}")

    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        print(f"\n  BESTE VARIANT: {beste['label']}")
        print(f"  {beste['maand_pct']:+.2f}%/mnd | WR {beste['wr']:.1f}% | PF {beste['pf']:.2f}")
        print(f"  Maanden positief: {beste['pos_mnd']}/{beste['tot_mnd']}")
        print(f"  Maanden ≥5%: {beste['doel_mnd']}/{beste['tot_mnd']}")
        print(f"  Signaaltypen: {beste['types']}")
        if beste["maand_pct"] >= 5:
            print(f"\n  ✓✓ DOEL 5-8%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 3:
            print(f"\n  {5-beste['maand_pct']:.1f}% van 5%-doel — goede basis.")
        else:
            print(f"\n  {5-beste['maand_pct']:.1f}% van 5%-doel — verdere optimalisatie nodig.")
    print("="*72)

if __name__ == "__main__":
    main()
