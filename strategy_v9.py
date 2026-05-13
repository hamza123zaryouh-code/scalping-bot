"""
XAUUSD Strategy v9 — H4 ATR | Long+Short | Regime Risk Tiers
=============================================================
Drie vaste kern-features (niet configureerbaar):
  1. H4 ATR stop placement  — stop past bij de grotere H4-schommelingen
  2. Long + Short signalen  — STERK_BULL/ZWAK_BULL = long, STERK_BEAR/ZWAK_BEAR = short
  3. Regime risk tiers      — 1.5% in sterke trend, 0.8% in zwakke, SKIP bij choppy

Varianten testen SL-multiplier, TP-ratio, RSI-drempel en sessievenster.
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL = 160_000.0
EUR_RATE = 1.17
FTMO_DAG = 8_000.0 * EUR_RATE   # €8,000 → $9,360  (FTMO €160k account: 5% daily)
FTMO_TOT = 16_000.0 * EUR_RATE  # €16,000 → $18,720 (FTMO €160k account: 10% total)
MAANDEN  = 13

# ─── INDICATOREN ──────────────────────────────────────────────────────────────

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([hi-lo, (hi-cl.shift(1)).abs(), (lo-cl.shift(1)).abs()], axis=1).max(axis=1)
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

# ─── DATA ─────────────────────────────────────────────────────────────────────

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
    d["rsi5"]   = rsi_fn(d["close"], 5)
    d["rsi14"]  = rsi_fn(d["close"], 14)
    d["atr_h1"] = atr_fn(d["high"], d["low"], d["close"], 14)

    # H4 indicatoren
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope"] = h4["e21"] - h4["e21"].shift(3)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["atr"]   = atr_fn(h4["high"], h4["low"], h4["close"], 14)  # ← kern: H4 ATR voor stop
    h4["rsi14"] = rsi_fn(h4["close"], 14)

    def regime(row):
        bull = row["e21"] > row["e50"]
        bear = row["e21"] < row["e50"]
        adx  = row["adx"]
        sl3  = row["slope"]
        if   bull and adx >= 26 and sl3 > 0 and row["e50"] > row["e200"]: return "STERK_BULL"
        elif bull and adx >= 18:                                            return "ZWAK_BULL"
        elif bear and adx >= 26 and sl3 < 0 and row["e50"] < row["e200"]: return "STERK_BEAR"
        elif bear and adx >= 18:                                            return "ZWAK_BEAR"
        else:                                                                return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)

    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")   # H4 ATR

    # D1 trend
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bull")
    d["d1_e200"]  = d1["de200"].reindex(d.index, method="ffill")

    return d.dropna(subset=["rsi5","atr_h1","h4_atr","h4_regime","d1_trend"])

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────

def backtest(df, cfg):
    # Kern risk tiers (1.5% sterk / 0.8% zwak / choppy=skip — altijd actief)
    risk_sterk = cfg.get("risk_sterk", 0.015)   # sterke trend
    risk_zwak  = cfg.get("risk_zwak",  0.008)   # zwakke trend
    # stop/tp
    sl_m    = cfg.get("sl",  1.0)   # veelvoud van H4 ATR
    tp_m    = cfg.get("tp",  3.0)   # R:R
    be_m    = cfg.get("be",  1.0)   # break-even trigger (veelvoud van SL dist)
    # RSI entry-drempel
    rsi_ov  = cfg.get("rsi_ov", 30)   # oververkocht/overkocht drempel (sterk)
    rsi_zwk = cfg.get("rsi_zwk", 35)  # drempel voor zwakke regimes
    # sessie & daglimieten
    s0, s1  = cfg.get("s0", 7), cfg.get("s1", 19)
    max_dag = cfg.get("max_dag", 2)
    dag_stop = cfg.get("dag_stop", 0.65)   # stop nieuwe trades als dagverlies > x% van FTMO_DAG

    kap = KAPITAAL; piek = KAPITAAL
    trs = []; dag_v = {}
    ip = False
    entry = sl = tp = sla = risk_usd = richting = sig_type = ot = None
    bd = False

    for i in range(50, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour

        if dat not in dag_v:
            dag_v[dat] = {"verlies": 0.0, "count": 0}

        # FTMO totaallimiet
        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p  = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                             "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"FAIL","type":sig_type})
                ip = False
            bd = True; break

        # Open positie beheren
        if ip:
            if richting == 1:
                if (b["close"] - entry) >= be_m * sla and sl < entry:
                    sl = entry   # break-even
            else:
                if (entry - b["close"]) >= be_m * sla and sl > entry:
                    sl = entry
            hit_sl = (richting ==  1 and b["low"]  <= sl) or (richting == -1 and b["high"] >= sl)
            hit_tp = (richting ==  1 and b["high"] >= tp) or (richting == -1 and b["low"]  <= tp)
            if hit_sl or hit_tp:
                exit_p  = tp if hit_tp else sl
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                if pnl_usd < 0:
                    dv = dag_v[dat]["verlies"]
                    if dv + abs(pnl_usd) > FTMO_DAG:
                        pnl_usd = -(FTMO_DAG - dv)
                    dag_v[dat]["verlies"] += abs(pnl_usd)
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                             "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,
                             "result":"TP" if hit_tp else "SL","type":sig_type})
                ip = False

        # Nieuw signaal zoeken
        if not ip:
            dv = dag_v[dat]["verlies"]
            dc = dag_v[dat]["count"]
            if not (s0 <= uur < s1) or dv >= FTMO_DAG * dag_stop or dc >= max_dag:
                continue

            regime  = b["h4_regime"]
            d1_bull = b["d1_trend"] == "bull"
            d1_bear = b["d1_trend"] == "bear"
            rsi5    = float(b["rsi5"])
            atr_h4  = float(b["h4_atr"])

            # CHOPPY → skip (kern feature #3)
            if regime == "CHOPPY":
                continue

            sig = None

            # ── LONG signalen (H4 bullish + D1 bullish) ──────────────────────
            if regime == "STERK_BULL" and d1_bull and rsi5 < rsi_ov:
                sig = ("long", "STERK_LONG", risk_sterk)
            elif regime == "ZWAK_BULL" and d1_bull and rsi5 < rsi_zwk:
                sig = ("long", "ZWAK_LONG", risk_zwak)

            # ── SHORT signalen (H4 bearish + D1 bearish) ─────────────────────
            elif regime == "STERK_BEAR" and d1_bear and rsi5 > (100 - rsi_ov):
                sig = ("short", "STERK_SHORT", risk_sterk)
            elif regime == "ZWAK_BEAR" and d1_bear and rsi5 > (100 - rsi_zwk):
                sig = ("short", "ZWAK_SHORT", risk_zwak)

            if sig:
                richting_str, sig_type, risk_pct = sig
                richting = 1 if richting_str == "long" else -1
                entry    = float(b["close"])
                sla      = sl_m * atr_h4   # kern feature #1: H4 ATR stop
                sl       = entry - richting * sla
                tp       = entry + richting * tp_m * sla

                # Drawdown-schaling
                dd_pct = (piek - kap) / piek
                if   dd_pct > 0.06: risk_pct *= 0.50
                elif dd_pct > 0.03: risk_pct *= 0.75

                risk_usd = kap * risk_pct
                ot = b.name; ip = True
                dag_v[dat]["count"] += 1

    if ip and not bd:
        exit_p  = float(df.iloc[-1]["close"])
        pnl_usd = richting * (exit_p - entry) / sla * risk_usd
        kap += pnl_usd
        trs.append({"in":ot,"uit":df.index[-1],"rich":richting,"entry":entry,"exit":exit_p,
                    "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"OPEN","type":sig_type})
    return trs, kap, bd

# ─── RAPPORT ──────────────────────────────────────────────────────────────────

def rapport(trs, kap_eind, failed, label):
    pnl_usd = kap_eind - KAPITAAL
    pnl_eur = pnl_usd / EUR_RATE
    print(); print("="*70); print(f"  {label}"); print("="*70)
    if not trs:
        print("  Geen trades."); print("="*70); return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    n   = len(df_t)
    wr  = 100 * (df_t["pnl_usd"] > 0).mean()
    gw  = df_t[df_t["pnl_usd"] > 0]["pnl_usd"].sum()
    gl  = df_t[df_t["pnl_usd"] < 0]["pnl_usd"].abs().sum()
    pf  = gw / gl if gl > 0 else 999.0
    dagen   = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    gem_mnd = pnl_eur / (dagen / 30.44)
    gem_wk  = pnl_eur / (dagen / 7)
    mnd_pct = pnl_eur / EUR_RATE / KAPITAAL * 100 / (dagen / 30.44)

    cap_lp = KAPITAAL; pk_lp = KAPITAAL; max_dd = 0.0
    for t in trs:
        cap_lp += t["pnl_usd"]
        if cap_lp > pk_lp: pk_lp = cap_lp
        dd = pk_lp - cap_lp
        if dd > max_dd: max_dd = dd

    status = "CHALLENGE GEFAALD" if failed else "GESLAAGD"
    doel_s = "BEREIKT!" if mnd_pct >= 5 else f"{5-mnd_pct:.1f}% tekort"

    print(f"  Kapitaal : $ {KAPITAAL:>10,.0f}  ->  $ {kap_eind:>10,.0f}")
    print(f"  P&L      : $ {pnl_usd:>+10,.0f}  (EUR {pnl_eur:>+10,.0f})")
    print(f"  Gem/maand: EUR {gem_mnd:>+8,.0f} ({mnd_pct:+.2f}%/mnd)  Doel 5%: {doel_s}")
    print(f"  Max DD   : EUR {max_dd/EUR_RATE:>8,.0f}  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
    print(f"  Challenge: {status}")
    sig_cnt = df_t["type"].value_counts()
    print(f"  Signalen : {dict(sig_cnt)}")
    print()

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_usd","count"),
        win=("pnl_usd", lambda x: (x>0).sum()),
        pnl_eur=("pnl_eur","sum"),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["win"] / mnd["trades"]
    mnd["pct_mnd"] = mnd["pnl_eur"] / EUR_RATE / KAPITAAL * 100
    mnd["gem_week"]= mnd["pnl_eur"] / 21 * 5

    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7} {'Gem/week':>10}")
    print("  " + "-"*60)
    for _, r in mnd.iterrows():
        flag = " *** DOEL" if r["pct_mnd"] >= 5 else (" *** TOP" if r["pnl_eur"] > 3000 else (" --- ZWAK" if r["pnl_eur"] < -3000 else ""))
        print(f"  {str(r['maand']):<10} {r['trades']:>6}  {r['win_pct']:>4.1f}%  EUR {r['pnl_eur']:>8,.0f}  {r['pct_mnd']:>6.2f}%  EUR {r['gem_week']:>+8,.0f}{flag}")
    print("="*70)

    return {"label":label,"pnl_eur":pnl_eur,"gem_mnd":gem_mnd,"gem_wk":gem_wk,
            "maand_pct":mnd_pct,"trades":n,"wr":wr,"pf":pf,
            "max_dd_eur":max_dd/EUR_RATE,"status":status,"mnd":mnd}

# ─── VARIANTEN ────────────────────────────────────────────────────────────────
# Kern is gefixeerd: H4 ATR stop, long+short, 1.5%/0.8%/choppy-skip
# Varianten differentiëren op SL/TP/RSI/sessie

VARIANTEN = {
    "V9-Basis": {
        "desc": "H4 ATR 1×, TP 3:1, RSI 30/35, sessie 07-19",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.0, "be":1.0,
        "rsi_ov":30, "rsi_zwk":35,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
    "V9-SL08-TP3": {
        "desc": "Smallere stop (0.8× H4 ATR), TP 3:1",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":0.8, "tp":3.0, "be":0.8,
        "rsi_ov":30, "rsi_zwk":35,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
    "V9-SL12-TP4": {
        "desc": "Ruimere stop (1.2× H4 ATR), TP 4:1 — meer lucht",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.2, "tp":4.0, "be":1.2,
        "rsi_ov":30, "rsi_zwk":35,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
    "V9-RSIStreng": {
        "desc": "Strenge RSI drempels (25/30) — alleen extreme pullbacks",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.0, "be":1.0,
        "rsi_ov":25, "rsi_zwk":30,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
    "V9-RSIRuim": {
        "desc": "Ruimere RSI (35/40), meer signalen, hogere TP 3.5:1",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.5, "be":1.0,
        "rsi_ov":35, "rsi_zwk":40,
        "s0":7, "s1":19, "max_dag":3, "dag_stop":0.65,
    },
    "V9-Risk2pct": {
        "desc": "Hogere risk: 2.0%/1.0%, H4 ATR 1×, TP 3:1",
        "risk_sterk":0.020, "risk_zwak":0.010,
        "sl":1.0, "tp":3.0, "be":1.0,
        "rsi_ov":30, "rsi_zwk":35,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
    "V9-SterkeAlleen": {
        "desc": "Alleen STERK_BULL/STERK_BEAR (zwak=0%), TP 3.5:1",
        "risk_sterk":0.015, "risk_zwak":0.000,
        "sl":1.0, "tp":3.5, "be":1.0,
        "rsi_ov":30, "rsi_zwk":35,
        "s0":7, "s1":19, "max_dag":2, "dag_stop":0.65,
    },
}

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("="*70)
    print("  XAUUSD STRATEGIE v9 | H4 ATR | LONG+SHORT | REGIME RISK TIERS")
    print("="*70)
    print("  Kern (gefixeerd):")
    print("    #1  Stop = H4 ATR x multiplier")
    print("    #2  Long bij BULL-regime + D1 bull | Short bij BEAR-regime + D1 bear")
    print("    #3  Risk: 1.5% (sterk) / 0.8% (zwak) / SKIP (choppy)")
    print()

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren + regimes bouwen...")
    df = bereid_voor(df_raw)

    h4_atr_gem = df["h4_atr"].mean()
    h1_atr_gem = df["atr_h1"].mean()
    regime_cnt = df["h4_regime"].value_counts()
    d1_bull_pct = 100 * (df["d1_trend"] == "bull").mean()

    print(f"  H4 ATR gem: ${h4_atr_gem:.1f}  |  H1 ATR gem: ${h1_atr_gem:.1f}  |  Ratio: {h4_atr_gem/h1_atr_gem:.1f}×")
    print(f"  Met H4 ATR: SL ~${1.0*h4_atr_gem:.1f}  TP ~${3.0*h4_atr_gem:.1f}")
    print(f"  D1 bull: {d1_bull_pct:.1f}%  |  D1 bear: {100-d1_bull_pct:.1f}%")
    print(f"  Regime verdeling (H1 bars):")
    for r, c in regime_cnt.items():
        pct = 100 * c / len(df)
        tradeable = "" if r == "CHOPPY" else " <- tradeable"
        print(f"    {r:<15}: {c:>5} bars ({pct:>4.1f}%){tradeable}")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind, failed = backtest(df, cfg)
        res = rapport(trs, kap_eind, failed, naam)
        if res: resultaten.append(res)

    # Eindoverzicht
    print(); print("="*70)
    print("  EINDOVERZICHT"); print("="*70)
    print(f"  {'Variant':<22} {'EUR P&L':>10} {'%/mnd':>7} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD EUR':>10}  Status")
    print("  "+"-"*80)

    geslaagd = [r for r in resultaten if r["status"] == "GESLAAGD"]
    gefaald  = [r for r in resultaten if r["status"] != "GESLAAGD"]

    for r in sorted(geslaagd, key=lambda x: -x["maand_pct"]) + sorted(gefaald, key=lambda x: -x["maand_pct"]):
        mark = " *** BESTE" if geslaagd and r == sorted(geslaagd, key=lambda x: -x["maand_pct"])[0] else ""
        doel = " DOEL!"    if r["maand_pct"] >= 5 else ""
        print(f"  {r['label']:<22} EUR {r['pnl_eur']:>+8,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  EUR {r['max_dd_eur']:>7,.0f}"
              f"  {r['status']}{mark}{doel}")
    print("="*70)

    if geslaagd:
        beste = sorted(geslaagd, key=lambda x: -x["maand_pct"])[0]
        mnd = beste["mnd"]
        mnd_doel = (mnd["pct_mnd"] >= 5).sum()
        mnd_pos  = (mnd["pnl_eur"] > 0).sum()
        mnd_tot  = len(mnd)
        print(f"\n  BESTE: {beste['label']}")
        print(f"  WR: {beste['wr']:.1f}%  PF: {beste['pf']:.2f}  Gem/maand: {beste['maand_pct']:+.2f}%")
        print(f"  Positieve maanden: {mnd_pos}/{mnd_tot}  |  Maanden >=5%: {mnd_doel}/{mnd_tot}")
        print(f"  Beste maand: EUR {mnd['pnl_eur'].max():+,.0f} ({mnd['pct_mnd'].max():+.2f}%)")
        if beste["maand_pct"] >= 5:
            print(f"\n  DOEL 5-8%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 2:
            print(f"\n  {beste['maand_pct']:.2f}%/maand — {5-beste['maand_pct']:.1f}% onder 5%-doel.")
        else:
            print(f"\n  Strategie verbetering nodig om 5%/maand te halen.")
    print("="*70)

if __name__ == "__main__":
    main()
