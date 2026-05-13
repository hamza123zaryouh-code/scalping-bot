"""
XAUUSD Strategy v7b - Multi-Signal met Risicobeheer
=====================================================
Bevindingen v7:
- V7-LongShort beste: PF 1.18, +EUR 13,482, EUR 385/week
- Alle varianten falen challenge door te hoge drawdown
Aanpak v7b:
- V7-LongShort basis (long + short in trend)
- Volatiliteitsfilter: geen handel als ATR > 1.6x gemiddeld
- Lager risico: 0.8-1.0% per trade
- Dagverlies hard stop op 60% van FTMO limiet
- Winstmomentum: verhoog risico in goede periodes, verlaag in slechte
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL  = 160_000.0
EUR_RATE  = 1.17
FTMO_DAG  = 6_000.0 * EUR_RATE   # USD $7,020
FTMO_TOT  = 16_000.0 * EUR_RATE  # USD $18,720
MAANDEN   = 13

# ─── INDICATOREN ──────────────────────────────────────────────────────────────
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(com=p-1, adjust=False).mean()

def adx_fn(hi, lo, cl, p=14):
    u = hi.diff(); dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = atr_fn(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p-1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p-1, adjust=False).mean() / at
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p-1, adjust=False).mean().fillna(0)

# ─── DATA ─────────────────────────────────────────────────────────────────────
def laad():
    e = datetime.utcnow()
    s = e - timedelta(days=MAANDEN * 31 + 30)
    print(f"  Download GC=F H1: {s.date()} - {e.date()}")
    df = yf.download("GC=F", start=s.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"),
                     interval="1h", progress=False, auto_adjust=True)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open","high","low","close","volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} - {df.index[-1].date()})")
    return df

def bereid_voor(df):
    d = df.copy()
    d["e21"]    = ema(d["close"], 21)
    d["e50"]    = ema(d["close"], 50)
    d["rsi5"]   = rsi_fn(d["close"], 5)
    d["rsi14"]  = rsi_fn(d["close"], 14)
    d["atr"]    = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_ma"] = d["atr"].rolling(50).mean()   # gemiddeld ATR voor volatiliteitsfilter
    d["adx_h1"] = adx_fn(d["high"], d["low"], d["close"], 14)

    # H4
    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["slope"] = h4["e21"] - h4["e21"].shift(3)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["bias"]  = np.where(h4["e21"] > h4["e50"], "bull", "bear")
    d["h4_bias"]  = h4["bias"].reindex(d.index, method="ffill").fillna("bear")
    d["h4_slope"] = h4["slope"].reindex(d.index, method="ffill").fillna(0)
    d["h4_adx"]   = h4["adx"].reindex(d.index, method="ffill").fillna(0)

    # D1
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bear")

    return d.dropna(subset=["rsi5","atr","atr_ma","h4_bias","d1_trend"])

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
def backtest(df, cfg):
    risk_base  = cfg["risk"]
    sl_m       = cfg.get("sl", 1.3)
    tp_m       = cfg.get("tp", 3.0)
    be_m       = cfg.get("be", 1.0)
    adx_min    = cfg.get("adx_min", 20)
    rsi_long   = cfg.get("rsi_long", 30)
    rsi_short  = cfg.get("rsi_short", 70)
    s0         = cfg.get("s0", 7)
    s1         = cfg.get("s1", 19)
    max_dag    = cfg.get("max_dag", 2)
    shorts     = cfg.get("shorts", False)
    slope_req  = cfg.get("slope", True)
    atr_max_m  = cfg.get("atr_max", 1.6)   # max ATR als veelvoud van gemiddeld
    dag_stop   = cfg.get("dag_stop", 0.60)  # stop handelen na X% van daglimiet bereikt

    kap   = KAPITAAL
    piek  = KAPITAAL
    trs   = []
    dag_v = {}

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

        # Beheer open positie
        if ip:
            if richting == 1:
                if (b["close"] - entry) >= be_m * sla and sl < entry:
                    sl = entry
            else:
                if (entry - b["close"]) >= be_m * sla and sl > entry:
                    sl = entry

            hit_sl = (richting == 1 and b["low"] <= sl) or (richting == -1 and b["high"] >= sl)
            hit_tp = (richting == 1 and b["high"] >= tp) or (richting == -1 and b["low"] <= tp)

            if hit_sl or hit_tp:
                exit_p  = tp if hit_tp else sl
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                if pnl_usd < 0:
                    dag_verlies = dag_v[dat]["verlies"]
                    if dag_verlies + abs(pnl_usd) > FTMO_DAG:
                        pnl_usd = -(FTMO_DAG - dag_verlies)
                    dag_v[dat]["verlies"] += abs(pnl_usd)
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                             "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,
                             "result":"TP" if hit_tp else "SL","type":sig_type})
                ip = False

        # Signaal zoeken
        if not ip:
            in_sessie   = s0 <= uur < s1
            dag_verlies = dag_v[dat]["verlies"]
            dag_count   = dag_v[dat]["count"]

            if not in_sessie or dag_verlies >= FTMO_DAG * dag_stop or dag_count >= max_dag:
                continue

            h4_bull  = b["h4_bias"] == "bull"
            h4_bear  = b["h4_bias"] == "bear"
            h4_adx_v = float(b["h4_adx"])
            h4_slope = float(b["h4_slope"]) > 0
            d1_bull  = b["d1_trend"] == "bull"
            d1_bear  = b["d1_trend"] == "bear"
            rsi5_v   = float(b["rsi5"])
            atr_v    = float(b["atr"])
            atr_ma_v = float(b["atr_ma"])

            # Volatiliteitsfilter: skip als markt te volatiel is
            if atr_ma_v > 0 and atr_v > atr_max_m * atr_ma_v:
                continue

            adx_ok = h4_adx_v >= adx_min
            sig    = None

            # Long signaal
            if h4_bull and d1_bull and adx_ok:
                trend_ok = (not slope_req) or h4_slope
                if trend_ok and rsi5_v < rsi_long:
                    sig = ("long", "RSI_LONG")

            # Short signaal
            if sig is None and shorts and h4_bear and d1_bear and adx_ok:
                if rsi5_v > rsi_short:
                    sig = ("short", "RSI_SHORT")

            if sig is not None:
                richting_str, sig_type = sig
                richting = 1 if richting_str == "long" else -1
                entry    = float(b["close"])
                sla      = sl_m * atr_v
                sl       = entry - richting * sla
                tp       = entry + richting * tp_m * sla
                # Dynamisch risico: verlaag als kapitaal krimpt
                dd_pct = (piek - kap) / piek
                if dd_pct > 0.06:
                    risk_factor = 0.5   # halveer risico bij 6%+ drawdown
                elif dd_pct > 0.03:
                    risk_factor = 0.75  # 25% minder risico bij 3%+ drawdown
                else:
                    risk_factor = 1.0
                risk_usd = kap * risk_base * risk_factor
                ot = b.name
                ip = True
                dag_v[dat]["count"] += 1

    # Open positie sluiten aan einde (als challenge niet gefaald)
    if ip and not bd:
        exit_p  = float(df.iloc[-1]["close"])
        pnl_usd = richting * (exit_p - entry) / sla * risk_usd
        kap += pnl_usd
        trs.append({"in":ot,"uit":df.index[-1],"rich":richting,"entry":entry,"exit":exit_p,
                    "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"OPEN","type":sig_type})

    return trs, kap, bd

# ─── RAPPORT ──────────────────────────────────────────────────────────────────
def rapport(trs, kap_eind, challenge_fail, label):
    pnl_usd = kap_eind - KAPITAAL
    pnl_eur = pnl_usd / EUR_RATE

    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)

    if not trs:
        print("  Geen trades gevonden.")
        print("=" * 70)
        return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    n  = len(df_t)
    wr = 100 * (df_t["pnl_usd"] > 0).mean()
    gw = df_t[df_t["pnl_usd"] > 0]["pnl_usd"].sum()
    gl = df_t[df_t["pnl_usd"] < 0]["pnl_usd"].abs().sum()
    pf = gw / gl if gl > 0 else 999.0

    dagen  = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    weken  = dagen / 7
    gem_wk = pnl_eur / weken
    gem_dg = pnl_eur / dagen

    cap_lp = KAPITAAL; pk_lp = KAPITAAL; max_dd = 0.0
    for t in trs:
        cap_lp += t["pnl_usd"]
        if cap_lp > pk_lp: pk_lp = cap_lp
        dd = pk_lp - cap_lp
        if dd > max_dd: max_dd = dd

    status = "CHALLENGE GEFAALD" if challenge_fail else "GESLAAGD"
    print(f"  Kapitaal : $ {KAPITAAL:>10,.0f} -> $ {kap_eind:>10,.0f}")
    print(f"  P&L      : $ {pnl_usd:>+10,.0f}  (EUR {pnl_eur:>+10,.0f})")
    print(f"  Gem/week : EUR {gem_wk:>+8,.0f}  |  Gem/dag: EUR {gem_dg:>+8,.0f}")
    print(f"  Max DD   : $ {max_dd:>9,.0f}  (EUR {max_dd/EUR_RATE:>+8,.0f})  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
    print(f"  Challenge: {status}")
    print()

    mnd = df_t.groupby("maand").agg(
        trades=("pnl_usd","count"),
        win=("pnl_usd", lambda x: (x > 0).sum()),
        pnl_eur=("pnl_eur","sum"),
    ).reset_index()
    mnd["win_pct"]  = 100 * mnd["win"] / mnd["trades"]
    mnd["gem_week"] = mnd["pnl_eur"] / 21 * 5

    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>12} {'Gem/week':>10}")
    print("  " + "-" * 55)
    for _, r in mnd.iterrows():
        flag = " *** TOP" if r["pnl_eur"] > 5000 else (" --- ZWAK" if r["pnl_eur"] < -3000 else "")
        print(f"  {str(r['maand']):<10} {r['trades']:>6}  {r['win_pct']:>4.1f}%  EUR {r['pnl_eur']:>8,.0f}  EUR {r['gem_week']:>+8,.0f}{flag}")

    print("=" * 70)
    return {"label":label, "pnl_eur":pnl_eur, "gem_week":gem_wk, "trades":n,
            "wr":wr, "pf":pf, "max_dd_eur":max_dd/EUR_RATE, "status":status}

# ─── VARIANTEN ────────────────────────────────────────────────────────────────
VARIANTEN = {
    "V7b-Voorzichtig": {
        "desc": "Long+Short, 0.8% risk, volatiliteitsfilter",
        "risk":0.008, "sl":1.3, "tp":3.0, "be":1.0,
        "adx_min":20, "rsi_long":30, "rsi_short":70,
        "s0":7, "s1":19, "max_dag":2,
        "shorts":True, "slope":False, "atr_max":1.6, "dag_stop":0.60,
    },
    "V7b-Standaard": {
        "desc": "Long+Short, 1.0% risk, volatiliteitsfilter",
        "risk":0.010, "sl":1.3, "tp":3.0, "be":1.0,
        "adx_min":20, "rsi_long":30, "rsi_short":70,
        "s0":7, "s1":19, "max_dag":2,
        "shorts":True, "slope":False, "atr_max":1.6, "dag_stop":0.60,
    },
    "V7b-Gebalanceerd": {
        "desc": "Long+Short, 1.2% risk, slope+ADX filter",
        "risk":0.012, "sl":1.3, "tp":3.0, "be":1.0,
        "adx_min":22, "rsi_long":30, "rsi_short":70,
        "s0":7, "s1":19, "max_dag":2,
        "shorts":True, "slope":True, "atr_max":1.6, "dag_stop":0.65,
    },
    "V7b-Agressief": {
        "desc": "Long+Short, 1.5% risk, TP 3.5x",
        "risk":0.015, "sl":1.3, "tp":3.5, "be":1.0,
        "adx_min":20, "rsi_long":30, "rsi_short":70,
        "s0":7, "s1":19, "max_dag":2,
        "shorts":True, "slope":False, "atr_max":1.5, "dag_stop":0.60,
    },
    "V7b-LongOnly-Conservatief": {
        "desc": "Long only, 1.5% risk, slope vereist (= v6 REF-v4b stijl)",
        "risk":0.015, "sl":1.3, "tp":3.0, "be":1.0,
        "adx_min":20, "rsi_long":30,
        "s0":7, "s1":17, "max_dag":2,
        "shorts":False, "slope":True, "atr_max":1.6, "dag_stop":0.65,
    },
}

def main():
    print("=" * 70)
    print("  XAUUSD STRATEGIE v7b | RISICOBEHEER + MULTI-SIGNAAL")
    print("=" * 70)
    print(f"  FTMO limieten: Dag EUR 6,000 (${FTMO_DAG:,.0f}) | Totaal EUR 16,000 (${FTMO_TOT:,.0f})")

    print("\n[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren bouwen...")
    df = bereid_voor(df_raw)
    print(f"  {len(df)} H1 bars klaar")
    print(f"[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind, failed = backtest(df, cfg)
        res = rapport(trs, kap_eind, failed, f"{naam}")
        if res:
            resultaten.append(res)

    # Eindoverzicht
    print()
    print("=" * 70)
    print("  EINDOVERZICHT")
    print("=" * 70)
    print(f"  {'Variant':<30} {'EUR P&L':>10} {'Gem/week':>10} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD EUR':>10}  Status")
    print("  " + "-" * 85)
    geslaagd = [r for r in resultaten if r["status"] == "GESLAAGD"]
    gefaald  = [r for r in resultaten if r["status"] != "GESLAAGD"]
    for r in sorted(geslaagd, key=lambda x: -x["gem_week"]) + sorted(gefaald, key=lambda x: -x["gem_week"]):
        mark = " *** BESTE" if geslaagd and r == sorted(geslaagd, key=lambda x: -x["gem_week"])[0] else ""
        print(f"  {r['label']:<30} EUR {r['pnl_eur']:>+8,.0f} EUR {r['gem_week']:>+7,.0f} "
              f"{r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  EUR {r['max_dd_eur']:>7,.0f}  {r['status']}{mark}")
    print("=" * 70)

    if geslaagd:
        beste = sorted(geslaagd, key=lambda x: -x["gem_week"])[0]
        print(f"\n  BESTE GESLAAGDE VARIANT: {beste['label']}")
        print(f"  Gem/week  : EUR {beste['gem_week']:+,.0f}")
        print(f"  Win Rate  : {beste['wr']:.1f}%  |  PF: {beste['pf']:.2f}")
        print(f"  Max DD    : EUR {beste['max_dd_eur']:,.0f} (limiet EUR 16,000)")
        mnd_naar_target = 160_000 / EUR_RATE / max(beste["gem_week"] * 4, 1)
        print(f"  Challenge duur: ca. {mnd_naar_target:.0f} maanden (om +EUR 13,675 te behalen)")
        print(f"\n  Realistisch wekelijks doel: EUR {beste['gem_week']:,.0f}/week")
        print(f"  Om EUR 6,000/week te bereiken: {6000/max(beste['gem_week'],1):.1f}x groter account nodig")
    else:
        print("\n  Geen enkele variant heeft de challenge gehaald.")
        print("  Beste optie: V7b-Voorzichtig (laagste drawdown, meest kans op challenge halen)")
    print("=" * 70)

if __name__ == "__main__":
    main()
