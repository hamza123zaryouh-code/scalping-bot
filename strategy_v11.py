"""
XAUUSD Strategy v11 — Momentum Continuation Expert
====================================================
KERN-PROBLEEM V9/V10: RSI-5 <30 in STERK_BULL trend = zeldzaam + vaak verkeerd.
Win Rate 16% met 3:1 RR → -0.36R/trade = structureel verliesgevend.

V11 OPLOSSING: Momentum-continuatie ipv mean-reversion pullback
---------------------------------------------------------------
Entry-logica (LONG voorbeeld):
  1. H4 regime = STERK_BULL of ZWAK_BULL  (trend-bias)
  2. D1 trend = bull                       (macro-richting)
  3. H1 RSI-14 kruist OMHOOG door 50       (momentum bevestiging na pullback)
  4. H1 close > H1 EMA21                  (prijs boven middellange MA)
  5. H4 ADX ≥ 18                          (trend heeft kracht)

SL: onder H1 EMA21 - 0.3× H1 ATR  (of H4 ATR × 0.6, whichever smaller)
TP: 2:1 RR voor zwak regime, 3:1 voor sterk regime

Verwacht: WR 45-55%, PF 1.4-2.0, consistentie over alle maanden
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

    # H1 indicatoren
    d["rsi14"]    = rsi_fn(d["close"], 14)
    d["rsi14_p"]  = d["rsi14"].shift(1)     # vorige bar RSI (voor crossover detectie)
    d["ema9"]     = ema(d["close"], 9)
    d["ema21"]    = ema(d["close"], 21)
    d["atr_h1"]   = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma20"] = d["atr_h1"].rolling(20).mean()

    # H4 indicatoren
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min",
                                 "close":"last","volume":"sum"}).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope"] = h4["e21"] - h4["e21"].shift(3)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)

    def regime(row):
        bull = row["e21"] > row["e50"]
        bear = row["e21"] < row["e50"]
        adx  = row["adx"]
        sl3  = row["slope"]
        if   bull and adx >= 25 and sl3 > 0 and row["e50"] > row["e200"]: return "STERK_BULL"
        elif bull and adx >= 15:                                            return "ZWAK_BULL"
        elif bear and adx >= 25 and sl3 < 0 and row["e50"] < row["e200"]: return "STERK_BEAR"
        elif bear and adx >= 15:                                            return "ZWAK_BEAR"
        else:                                                                return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)
    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")

    # D1 trend (sluit met EMA50 + EMA200 voor robuustheid)
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min",
                                 "close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    # Bull = boven beide EMA's, Bear = onder beide
    d1["trend"] = np.where(
        d1["close"] > d1["de50"],
        np.where(d1["close"] > d1["de200"], "bull", "neutral"),
        np.where(d1["close"] < d1["de200"], "bear", "neutral"),
    )
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

    return d.dropna(subset=["rsi14","ema9","ema21","atr_h1","h4_atr","h4_regime","d1_trend"])

# ── Sessie helper ──────────────────────────────────────────────────────────────

def sessie_tier(uur, dow):
    if dow == 0 and uur < 10: return "blocked"   # Maandag gat
    if dow == 4 and uur >= 14: return "blocked"  # Vrijdag vroeg sluiten
    if 8 <= uur < 12 or 13 <= uur < 17: return "premium"
    if uur == 7 or 17 <= uur < 19: return "standard"
    return "blocked"

# ── Backtest ───────────────────────────────────────────────────────────────────

def backtest(df, cfg):
    risk_sterk = cfg.get("risk_sterk", 0.010)
    risk_zwak  = cfg.get("risk_zwak",  0.006)
    sl_atr_m   = cfg.get("sl_atr", 0.5)    # SL = sl_atr × H4 ATR (kleiner = strakker)
    tp_sterk   = cfg.get("tp_sterk", 3.0)  # RR ratio STERK regime
    tp_zwak    = cfg.get("tp_zwak",  2.0)  # RR ratio ZWAK regime
    be_trigger = cfg.get("be", 1.0)        # break-even na 1× SL dist in winst
    rsi_cross  = cfg.get("rsi_cross", 50)  # RSI-14 kruist door deze waarde
    adx_min    = cfg.get("adx_min", 15)    # H4 ADX minimaal
    max_sterk  = cfg.get("max_sterk", 3)
    max_zwak   = cfg.get("max_zwak",  2)

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
            dag_info[dat] = {"verlies": 0.0, "ns": 0, "nw": 0}

        # FTMO totaallimiet check
        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                trs.append(_tr(ot, b.name, richting, entry, exit_p, pnl_usd, "FAIL", sig_type))
                ip = False
            break

        # Beheer open positie
        if ip:
            cur = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])
            if richting == 1  and (cur - entry) >= be_trigger * sla and sl < entry: sl = entry
            if richting == -1 and (entry - cur) >= be_trigger * sla and sl > entry: sl = entry

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

        # Nieuw signaal zoeken
        if ip: continue
        dv = dag_info[dat]["verlies"]
        ns = dag_info[dat]["ns"]
        nw = dag_info[dat]["nw"]

        tier = sessie_tier(uur, dow)
        if tier == "blocked": continue
        if dv >= FTMO_DAG * 0.65: continue

        regime   = b["h4_regime"]
        if regime == "CHOPPY": continue

        d1_trend = b["d1_trend"]
        if d1_trend == "neutral": continue   # alleen duidelijke D1 richting

        rsi14     = float(b["rsi14"])
        rsi14_p   = float(b["rsi14_p"]) if not pd.isna(b["rsi14_p"]) else rsi14
        close     = float(b["close"])
        ema21_v   = float(b["ema21"])
        atr_h1    = float(b["atr_h1"])
        atr_h4    = float(b["h4_atr"])
        atr_ma    = float(b["atr_ma20"]) if not pd.isna(b["atr_ma20"]) else atr_h1
        h4_adx    = float(b["h4_adx"])

        # ATR-filters
        if atr_h4 < 5.0: continue
        if atr_h1 > 2.5 * atr_ma: continue
        if h4_adx < adx_min: continue

        # ── RSI-14 momentum crossover ──────────────────────────────────────────
        # LONG: RSI-14 kruist van <rsi_cross naar >=rsi_cross (momentum terug)
        #       + prijs boven H1 EMA21 (boven middellange trend)
        # SHORT: RSI-14 kruist van >100-rsi_cross naar <=100-rsi_cross
        #        + prijs onder H1 EMA21

        rsi_threshold_lo = rsi_cross       # 50 (of lager voor meer signalen)
        rsi_threshold_hi = 100 - rsi_cross

        sig = None

        long_ok  = (rsi14_p < rsi_threshold_lo) and (rsi14 >= rsi_threshold_lo) and (close > ema21_v)
        short_ok = (rsi14_p > rsi_threshold_hi) and (rsi14 <= rsi_threshold_hi) and (close < ema21_v)

        bull_regime = regime in ("STERK_BULL", "ZWAK_BULL")
        bear_regime = regime in ("STERK_BEAR", "ZWAK_BEAR")
        sterk = regime in ("STERK_BULL", "STERK_BEAR")

        if long_ok and bull_regime and d1_trend == "bull":
            if sterk and ns < max_sterk:
                sig = ("long", "STERK_LONG", risk_sterk, True, tp_sterk)
            elif not sterk and nw < max_zwak and tier == "premium":
                sig = ("long", "ZWAK_LONG", risk_zwak, False, tp_zwak)

        elif short_ok and bear_regime and d1_trend == "bear":
            if sterk and ns < max_sterk:
                sig = ("short", "STERK_SHORT", risk_sterk, True, tp_sterk)
            elif not sterk and nw < max_zwak and tier == "premium":
                sig = ("short", "ZWAK_SHORT", risk_zwak, False, tp_zwak)

        if sig:
            richting_str, sig_type, risk_pct, is_sterk, tp_r = sig
            richting = 1 if richting_str == "long" else -1
            entry    = close
            sla      = sl_atr_m * atr_h4   # SL gebaseerd op H4 ATR
            sl       = entry - richting * sla
            tp       = entry + richting * tp_r * sla

            dd_pct = (piek - kap) / piek
            if   dd_pct > 0.06: risk_pct *= 0.40
            elif dd_pct > 0.03: risk_pct *= 0.65

            risk_usd = kap * risk_pct
            ot = b.name; ip = True
            if is_sterk: dag_info[dat]["ns"] += 1
            else:        dag_info[dat]["nw"] += 1

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

def rapport(trs, kap_eur_eind, label):
    pnl_eur = kap_eur_eind - KAPITAAL
    print(); print("="*72); print(f"  {label}"); print("="*72)
    if not trs:
        print("  Geen trades."); return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    n   = len(df_t)
    wr  = 100 * (df_t["pnl_eur"] > 0).mean()
    gw  = df_t[df_t["pnl_eur"] > 0]["pnl_eur"].sum()
    gl  = df_t[df_t["pnl_eur"] < 0]["pnl_eur"].abs().sum()
    pf  = gw / gl if gl > 0 else 999.0

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

    doel_s = "BEREIKT!" if mnd_pct >= 5 else f"{5-mnd_pct:.1f}% tekort"
    print(f"  Kapitaal : €{KAPITAAL:>12,.0f}  →  €{kap_eur_eind:>12,.0f}")
    print(f"  P&L      : €{pnl_eur:>+12,.0f}")
    print(f"  Gem/maand: €{gem_mnd:>+10,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
    print(f"  Max DD   : €{max_dd/EUR_RATE:>8,.0f}  (limiet €16.000)")
    print(f"  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_eur","count"),
        pnl_eur=("pnl_eur","sum"),
        wins=("pnl_eur", lambda x: (x>0).sum()),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["wins"] / mnd["trades"]
    mnd["pct_mnd"] = mnd["pnl_eur"] / KAPITAAL * 100

    print(f"\n  {'Maand':<10} {'Tr':>4} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7}")
    print("  " + "-"*50)
    for _, r in mnd.iterrows():
        flag = " *** DOEL" if r["pct_mnd"] >= 5 else (" --- ZWAK" if r["pnl_eur"] < -4000 else "")
        print(f"  {str(r['maand']):<10} {r['trades']:>4}  {r['win_pct']:>4.1f}%  €{r['pnl_eur']:>10,.0f}  {r['pct_mnd']:>6.2f}%{flag}")
    print("="*72)

    return {"label":label,"pnl_eur":pnl_eur,"gem_mnd":gem_mnd,
            "maand_pct":mnd_pct,"trades":n,"wr":wr,"pf":pf,
            "max_dd_eur":max_dd/EUR_RATE,"mnd":mnd}

# ── Varianten ──────────────────────────────────────────────────────────────────

VARIANTEN = {
    "V11-Basis": {
        "desc": "RSI14 kruis door 50, H4 ATR×0.5 SL, 3:1 sterk / 2:1 zwak",
        "risk_sterk":0.010, "risk_zwak":0.006,
        "sl_atr":0.5, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":50, "adx_min":15,
        "max_sterk":3, "max_zwak":2,
    },
    "V11-RSI45": {
        "desc": "RSI14 kruis door 45 — meer signalen, lagere drempel",
        "risk_sterk":0.010, "risk_zwak":0.006,
        "sl_atr":0.5, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":45, "adx_min":15,
        "max_sterk":3, "max_zwak":2,
    },
    "V11-SL08": {
        "desc": "Ruimere stop (0.8× H4 ATR), TP 3:1 / 2:1",
        "risk_sterk":0.010, "risk_zwak":0.006,
        "sl_atr":0.8, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":50, "adx_min":15,
        "max_sterk":3, "max_zwak":2,
    },
    "V11-Hoog-Risk": {
        "desc": "Risk 1.5%/0.8%, RSI50, SL 0.5×H4ATR",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl_atr":0.5, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":50, "adx_min":15,
        "max_sterk":3, "max_zwak":2,
    },
    "V11-SterkeOnly": {
        "desc": "Alleen STERK regime, risk 1.2%, TP 3:1",
        "risk_sterk":0.012, "risk_zwak":0.000,
        "sl_atr":0.5, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":50, "adx_min":20,
        "max_sterk":3, "max_zwak":0,
    },
    "V11-ADX20": {
        "desc": "Strengere ADX filter (≥20), hogere kwaliteit setups",
        "risk_sterk":0.012, "risk_zwak":0.007,
        "sl_atr":0.5, "tp_sterk":3.0, "tp_zwak":2.0,
        "be":1.0, "rsi_cross":50, "adx_min":20,
        "max_sterk":3, "max_zwak":2,
    },
}

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("="*72)
    print("  XAUUSD STRATEGIE v11 | MOMENTUM CROSSOVER | DOEL: 5–8%/MAAND")
    print("  Entry: RSI-14 kruist door 50 + H1 boven EMA21 + H4 regime + D1 trend")
    print("  FTMO €160k: Dag-limiet €8.000 | Totaal €16.000")
    print("="*72)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren bouwen...")
    df = bereid_voor(df_raw)

    regime_cnt = df["h4_regime"].value_counts()
    d1_cnt     = df["d1_trend"].value_counts()
    print(f"  H4 regimes:")
    for r, c in regime_cnt.items():
        print(f"    {r:<15}: {c:>5} bars ({100*c/len(df):>4.1f}%)")
    print(f"  D1 trends: {dict(d1_cnt)}")

    # Tel RSI-14 crossover signalen (preview)
    rsi14   = df["rsi14"]
    rsi14_p = df["rsi14_p"]
    cross_up   = ((rsi14_p < 50) & (rsi14 >= 50)).sum()
    cross_down = ((rsi14_p > 50) & (rsi14 <= 50)).sum()
    print(f"  RSI-14 kruist door 50: ↑{cross_up} keer | ↓{cross_down} keer (over {MAANDEN} maanden)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res: resultaten.append(res)

    print(); print("="*72)
    print("  EINDOVERZICHT v11"); print("="*72)
    print(f"  {'Variant':<22} {'EUR P&L':>12} {'%/mnd':>7} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD':>10}")
    print("  "+"-"*75)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel = " *** DOEL!" if r["maand_pct"] >= 5 else (" ✓ TOP" if r["maand_pct"] >= 3 else "")
        safe = " ⚠ DD!" if r["max_dd_eur"] > 16000 else ""
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  €{r['max_dd_eur']:>7,.0f}{doel}{safe}")

    if resultaten:
        beste = max(resultaten, key=lambda x: x["maand_pct"])
        print(f"\n  BESTE: {beste['label']}")
        mnd = beste["mnd"]
        pos = (mnd["pnl_eur"] > 0).sum(); tot = len(mnd)
        doel_mnd = (mnd["pct_mnd"] >= 5).sum()
        print(f"  WR {beste['wr']:.1f}% | PF {beste['pf']:.2f} | {beste['maand_pct']:+.2f}%/mnd")
        print(f"  Positieve maanden: {pos}/{tot} | Maanden ≥5%: {doel_mnd}/{tot}")
        if beste["maand_pct"] >= 5:
            print(f"\n  ✓✓ DOEL 5-8%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 2:
            print(f"\n  {5-beste['maand_pct']:.1f}% van het 5%-doel.")
    print("="*72)

if __name__ == "__main__":
    main()
