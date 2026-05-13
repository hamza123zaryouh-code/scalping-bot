"""
XAUUSD Strategy v8 - Regime-Bewust | Doel: 5-8% per maand
============================================================
Doel: EUR 8,000-12,800/maand (5-8% op $160k account)

Wiskunde achter het doel:
  5% = $8,000/maand => 8 trades x 35% WR x 3:1 @ 2% risk => EV $1,280/trade
  8% = $12,800/maand => 8 trades x 40% WR x 3:1 @ 2% risk => EV $1,920/trade

Aanpak:
  - Marktregime detecteren (sterk trend / zwak trend / choppy)
  - Alleen handelen in STERKE trend (ADX > 26, alles aligned)
  - Hogere risk (2%) in beste omstandigheden
  - Lage risk (1%) of overslaan in slechte omstandigheden
  - Lange + Korte signalen in respective trendrichtingen
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL  = 160_000.0
EUR_RATE  = 1.17
FTMO_DAG  = 6_000.0 * EUR_RATE   # $7,020
FTMO_TOT  = 16_000.0 * EUR_RATE  # $18,720
MAANDEN   = 13

# ─── INDICATOREN ──────────────────────────────────────────────────────────────
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([hi-lo,(hi-cl.shift(1)).abs(),(lo-cl.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(com=p-1, adjust=False).mean()

def adx_fn(hi, lo, cl, p=14):
    u = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u; mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi,lo,cl,p).replace(0, np.nan)
    pdi = 100*pm.ewm(com=p-1,adjust=False).mean()/at
    mdi = 100*mm.ewm(com=p-1,adjust=False).mean()/at
    dx  = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(com=p-1,adjust=False).mean().fillna(0)

# ─── DATA ─────────────────────────────────────────────────────────────────────
def laad():
    e = datetime.utcnow(); s = e - timedelta(days=MAANDEN*31+30)
    print(f"  Download GC=F H1: {s.date()} - {e.date()}")
    df = yf.download("GC=F",start=s.strftime("%Y-%m-%d"),end=e.strftime("%Y-%m-%d"),
                     interval="1h",progress=False,auto_adjust=True)
    df.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open","high","low","close","volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} - {df.index[-1].date()})")
    return df

def bereid_voor(df):
    d = df.copy()
    # H1
    d["rsi5"]   = rsi_fn(d["close"], 5)
    d["rsi14"]  = rsi_fn(d["close"], 14)
    d["atr"]    = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma"] = d["atr"].rolling(50).mean()
    d["e21_h1"] = ema(d["close"], 21)

    # H4
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["e200"]  = ema(h4["close"], 200)
    h4["slope3"]= h4["e21"] - h4["e21"].shift(3)
    h4["slope6"]= h4["e21"] - h4["e21"].shift(6)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi14"] = rsi_fn(h4["close"], 14)

    # Regime per H4 bar:
    # STERK_BULL: e21>e50>e200, slope>0, adx>26
    # ZWAK_BULL:  e21>e50, slope>=0, adx>=18
    # STERK_BEAR: e21<e50<e200, slope<0, adx>26
    # ZWAK_BEAR:  e21<e50, slope<=0, adx>=18
    # CHOPPY: rest
    def regime(row):
        bull = row["e21"] > row["e50"]
        bear = row["e21"] < row["e50"]
        adx  = row["adx"]
        sl3  = row["slope3"]
        if bull and adx >= 26 and sl3 > 0 and row["e50"] > row["e200"]:
            return "STERK_BULL"
        elif bull and adx >= 18 and sl3 >= 0:
            return "ZWAK_BULL"
        elif bear and adx >= 26 and sl3 < 0 and row["e50"] < row["e200"]:
            return "STERK_BEAR"
        elif bear and adx >= 18 and sl3 <= 0:
            return "ZWAK_BEAR"
        else:
            return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)

    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_slope"]  = h4["slope3"].reindex(d.index, method="ffill").fillna(0)

    # D1
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")
    d["d1_trend"]= d1["trend"].reindex(d.index, method="ffill").fillna("bear")
    d["d1_e200"] = d1["de200"].reindex(d.index, method="ffill")

    return d.dropna(subset=["rsi5","atr","atr_ma","h4_regime","d1_trend"])

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
def backtest(df, cfg):
    risk_sterk  = cfg.get("risk_sterk", 0.020)   # 2% in sterke trend
    risk_zwak   = cfg.get("risk_zwak", 0.010)    # 1% in zwakke trend
    sl_m        = cfg.get("sl", 1.3)
    tp_m        = cfg.get("tp", 3.5)
    be_m        = cfg.get("be", 1.2)
    rsi_sterk   = cfg.get("rsi_sterk", 28)       # RSI drempel voor sterke trend
    rsi_zwak    = cfg.get("rsi_zwak", 32)        # RSI drempel voor zwakke trend
    s0, s1      = cfg.get("s0", 7), cfg.get("s1", 19)
    max_dag     = cfg.get("max_dag", 2)
    handel_zwak = cfg.get("handel_zwak", True)   # ook in zwakke trend handelen?
    atr_max_m   = cfg.get("atr_max", 1.8)
    dag_stop    = cfg.get("dag_stop", 0.60)

    kap  = KAPITAAL; piek = KAPITAAL
    trs  = []; dag_v = {}
    ip   = False
    entry = sl = tp = sla = risk_usd = richting = sig_type = ot = None
    bd   = False

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

        # Beheer open positie
        if ip:
            if richting == 1:
                if (b["close"] - entry) >= be_m * sla and sl < entry:
                    sl = entry
            else:
                if (entry - b["close"]) >= be_m * sla and sl > entry:
                    sl = entry
            hit_sl = (richting==1 and b["low"]<=sl) or (richting==-1 and b["high"]>=sl)
            hit_tp = (richting==1 and b["high"]>=tp) or (richting==-1 and b["low"]<=tp)
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

        # Signaal zoeken
        if not ip:
            in_sessie = s0 <= uur < s1
            dv        = dag_v[dat]["verlies"]
            dc        = dag_v[dat]["count"]
            if not in_sessie or dv >= FTMO_DAG * dag_stop or dc >= max_dag:
                continue

            regime   = b["h4_regime"]
            d1_bull  = b["d1_trend"] == "bull"
            d1_bear  = b["d1_trend"] == "bear"
            rsi5_v   = float(b["rsi5"])
            atr_v    = float(b["atr"])
            atr_ma_v = float(b["atr_ma"])

            # Volatiliteitsfilter
            if atr_ma_v > 0 and atr_v > atr_max_m * atr_ma_v:
                continue

            sig = None

            # STERKE BULL: 2% risk, RSI5 < rsi_sterk
            if regime == "STERK_BULL" and d1_bull and rsi5_v < rsi_sterk:
                sig = ("long", "STERK_LONG", risk_sterk)

            # ZWAKKE BULL: 1% risk, RSI5 < rsi_zwak
            elif handel_zwak and regime == "ZWAK_BULL" and d1_bull and rsi5_v < rsi_zwak:
                sig = ("long", "ZWAK_LONG", risk_zwak)

            # STERKE BEAR: 2% risk, RSI5 > (100-rsi_sterk)
            elif regime == "STERK_BEAR" and d1_bear and rsi5_v > (100 - rsi_sterk):
                sig = ("short", "STERK_SHORT", risk_sterk)

            # ZWAKKE BEAR: 1% risk, RSI5 > (100-rsi_zwak)
            elif handel_zwak and regime == "ZWAK_BEAR" and d1_bear and rsi5_v > (100 - rsi_zwak):
                sig = ("short", "ZWAK_SHORT", risk_zwak)

            if sig is not None:
                richting_str, sig_type, risk_pct = sig
                richting = 1 if richting_str == "long" else -1
                entry    = float(b["close"])
                sla      = sl_m * atr_v
                sl       = entry - richting * sla
                tp       = entry + richting * tp_m * sla

                # Dynamisch risico: halveer bij drawdown > 5%
                dd_pct = (piek - kap) / piek
                if dd_pct > 0.05:
                    risk_pct *= 0.5
                elif dd_pct > 0.025:
                    risk_pct *= 0.75

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

    print(); print("=" * 70)
    print(f"  {label}"); print("=" * 70)

    if not trs:
        print("  Geen trades."); print("=" * 70)
        return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    n   = len(df_t)
    wr  = 100 * (df_t["pnl_usd"] > 0).mean()
    gw  = df_t[df_t["pnl_usd"] > 0]["pnl_usd"].sum()
    gl  = df_t[df_t["pnl_usd"] < 0]["pnl_usd"].abs().sum()
    pf  = gw / gl if gl > 0 else 999.0
    dagen = max((pd.to_datetime(df_t["uit"].max())-pd.to_datetime(df_t["in"].min())).days, 1)
    gem_wk = pnl_eur / (dagen/7)
    gem_mnd = pnl_eur / (dagen/30.44)

    cap_lp = KAPITAAL; pk_lp = KAPITAAL; max_dd = 0.0
    for t in trs:
        cap_lp += t["pnl_usd"]
        if cap_lp > pk_lp: pk_lp = cap_lp
        dd = pk_lp - cap_lp
        if dd > max_dd: max_dd = dd

    maand_pct = pnl_eur / EUR_RATE / KAPITAAL * 100 / (dagen/30.44)
    status = "CHALLENGE GEFAALD" if failed else "GESLAAGD"

    print(f"  Kapitaal : $ {KAPITAAL:>10,.0f} -> $ {kap_eind:>10,.0f}")
    print(f"  P&L      : $ {pnl_usd:>+10,.0f}  (EUR {pnl_eur:>+10,.0f})")
    print(f"  Gem/maand: EUR {gem_mnd:>+8,.0f}  ({maand_pct:+.2f}%/maand)  |  Doel 5-8%: {'BEREIKT' if 5.0 <= maand_pct <= 10 else f'tekort {5.0-maand_pct:.1f}%' if maand_pct < 5 else 'BOVEN DOEL'}")
    print(f"  Gem/week : EUR {gem_wk:>+8,.0f}  |  Max DD: $ {max_dd:>8,.0f} (EUR {max_dd/EUR_RATE:>+7,.0f})")
    print(f"  Trades {n:>3}  |  Win% {wr:.1f}%  |  PF {pf:.2f}  |  Challenge: {status}")

    # Signaalverdeling
    type_cnt = df_t["type"].value_counts()
    print(f"  Signalen : {dict(type_cnt)}")
    print()

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_usd","count"),
        win=("pnl_usd", lambda x: (x > 0).sum()),
        pnl_eur=("pnl_eur","sum"),
    ).reset_index()
    mnd["win_pct"]  = 100 * mnd["win"] / mnd["trades"]
    mnd["gem_week"] = mnd["pnl_eur"] / 21 * 5
    mnd["pct_mnd"]  = mnd["pnl_eur"] / EUR_RATE / KAPITAAL * 100

    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7} {'Gem/week':>10}")
    print("  " + "-" * 60)
    for _, r in mnd.iterrows():
        flag = " *** DOEL" if r["pct_mnd"] >= 5 else (" *** TOP" if r["pnl_eur"] > 3000 else (" --- ZWAK" if r["pnl_eur"] < -3000 else ""))
        print(f"  {str(r['maand']):<10} {r['trades']:>6}  {r['win_pct']:>4.1f}%  EUR {r['pnl_eur']:>8,.0f}  {r['pct_mnd']:>6.2f}%  EUR {r['gem_week']:>+8,.0f}{flag}")
    print("=" * 70)

    return {"label":label,"pnl_eur":pnl_eur,"gem_wk":gem_wk,"gem_mnd":gem_mnd,
            "maand_pct":maand_pct,"trades":n,"wr":wr,"pf":pf,
            "max_dd_eur":max_dd/EUR_RATE,"status":status,
            "mnd_data": mnd}

# ─── VARIANTEN ────────────────────────────────────────────────────────────────
VARIANTEN = {
    "V8-Basis": {
        "desc": "Regime-filter, STERK 2%, ZWAK 1%",
        "risk_sterk":0.020,"risk_zwak":0.010,
        "sl":1.3,"tp":3.5,"be":1.2,
        "rsi_sterk":28,"rsi_zwak":32,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"atr_max":1.8,"dag_stop":0.60,
    },
    "V8-ConservatieveRisk": {
        "desc": "Regime-filter, STERK 1.5%, ZWAK 0.8%",
        "risk_sterk":0.015,"risk_zwak":0.008,
        "sl":1.3,"tp":3.5,"be":1.2,
        "rsi_sterk":28,"rsi_zwak":32,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"atr_max":1.8,"dag_stop":0.60,
    },
    "V8-SterkeAlleen": {
        "desc": "Alleen sterke trend (ADX>26), 2% risk, max kwaliteit",
        "risk_sterk":0.020,"risk_zwak":0.000,
        "sl":1.3,"tp":3.5,"be":1.2,
        "rsi_sterk":28,"rsi_zwak":32,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":False,"atr_max":1.8,"dag_stop":0.60,
    },
    "V8-HogeTP": {
        "desc": "Regime-filter, TP 4x, STERK 1.8%",
        "risk_sterk":0.018,"risk_zwak":0.009,
        "sl":1.3,"tp":4.0,"be":1.5,
        "rsi_sterk":28,"rsi_zwak":32,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"atr_max":1.8,"dag_stop":0.60,
    },
    "V8-RSIRuim": {
        "desc": "Ruimere RSI drempels (35/40), meer signalen",
        "risk_sterk":0.015,"risk_zwak":0.008,
        "sl":1.3,"tp":3.0,"be":1.0,
        "rsi_sterk":35,"rsi_zwak":40,
        "s0":7,"s1":19,"max_dag":3,
        "handel_zwak":True,"atr_max":1.8,"dag_stop":0.65,
    },
}

def main():
    print("=" * 70)
    print("  XAUUSD STRATEGIE v8 | REGIME-BEWUST | DOEL: 5-8%/MAAND")
    print("=" * 70)
    print(f"  Doel: EUR {0.05*KAPITAAL/EUR_RATE:,.0f} - {0.08*KAPITAAL/EUR_RATE:,.0f}/maand")
    print(f"  FTMO: Dag $7,020 (EUR 6k) | Totaal $18,720 (EUR 16k)")

    print("\n[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren + regime bouwen...")
    df = bereid_voor(df_raw)

    # Toon regime verdeling
    regime_cnt = df["h4_regime"].value_counts()
    print(f"  Regime verdeling (H1 bars):")
    for r, c in regime_cnt.items():
        pct = 100 * c / len(df)
        print(f"    {r:<15}: {c:>5} bars ({pct:>4.1f}%)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind, failed = backtest(df, cfg)
        res = rapport(trs, kap_eind, failed, naam)
        if res: resultaten.append(res)

    # Eindoverzicht
    print(); print("=" * 70)
    print("  EINDOVERZICHT — gesorteerd op gemiddelde % per maand")
    print("=" * 70)
    print(f"  {'Variant':<26} {'EUR P&L':>10} {'%/mnd':>7} {'Gem/week':>10} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD EUR':>10}  Status")
    print("  " + "-" * 95)

    geslaagd = [r for r in resultaten if r["status"] == "GESLAAGD"]
    gefaald  = [r for r in resultaten if r["status"] != "GESLAAGD"]

    for r in sorted(geslaagd, key=lambda x: -x["maand_pct"]) + sorted(gefaald, key=lambda x: -x["maand_pct"]):
        mark = " *** BESTE" if geslaagd and r == sorted(geslaagd, key=lambda x: -x["maand_pct"])[0] else ""
        doel = " DOEL!" if r["maand_pct"] >= 5 else ""
        print(f"  {r['label']:<26} EUR {r['pnl_eur']:>+8,.0f} {r['maand_pct']:>6.2f}%  "
              f"EUR {r['gem_wk']:>+7,.0f} {r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  "
              f"EUR {r['max_dd_eur']:>7,.0f}  {r['status']}{mark}{doel}")

    print("=" * 70)
    print()

    # Maandanalyse beste variant
    if geslaagd:
        beste = sorted(geslaagd, key=lambda x: -x["maand_pct"])[0]
        print(f"  BESTE VARIANT: {beste['label']}")
        print(f"  Gem/maand : EUR {beste['gem_mnd']:+,.0f} ({beste['maand_pct']:+.2f}%/maand)")
        print(f"  Win Rate  : {beste['wr']:.1f}%  |  PF: {beste['pf']:.2f}")
        print(f"  Max DD    : EUR {beste['max_dd_eur']:,.0f} (FTMO limiet EUR 16,000)")
        print()
        mnd = beste["mnd_data"]
        mnd_doel = (mnd["pct_mnd"] >= 5).sum()
        mnd_positief = (mnd["pnl_eur"] > 0).sum()
        mnd_totaal = len(mnd)
        print(f"  Maandstatistieken ({mnd_totaal} maanden):")
        print(f"    Positieve maanden: {mnd_positief}/{mnd_totaal} ({100*mnd_positief/mnd_totaal:.0f}%)")
        print(f"    Maanden >= 5% doel: {mnd_doel}/{mnd_totaal} ({100*mnd_doel/mnd_totaal:.0f}%)")
        print(f"    Beste maand  : EUR {mnd['pnl_eur'].max():>+,.0f} ({mnd['pct_mnd'].max():+.2f}%)")
        print(f"    Slechtste mnd: EUR {mnd['pnl_eur'].min():>+,.0f} ({mnd['pct_mnd'].min():+.2f}%)")

        if beste["maand_pct"] >= 5:
            print(f"\n  DOEL 5-8%/MAAND: BEREIKT met gemiddeld {beste['maand_pct']:.2f}%")
        elif beste["maand_pct"] >= 3:
            print(f"\n  Bijna: {beste['maand_pct']:.2f}%/maand - {5-beste['maand_pct']:.1f}% tekort voor 5%-doel")
            print(f"  Met {5/beste['maand_pct']:.1f}x groter account (${160000*5/max(beste['maand_pct'],0.1):,.0f}) haal je EUR 6k/week")
        else:
            print(f"\n  Huidige strategie: {beste['maand_pct']:.2f}%/maand")
            print(f"  Voor 5%/maand: strategie verbetering of groter account nodig")
    print("=" * 70)

if __name__ == "__main__":
    main()
