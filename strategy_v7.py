"""
XAUUSD Strategy v7 - Multi-Signal
===================================
Doel: meer trades per week door:
  1. Short signalen (verkopen in neergaande trends)
  2. London Breakout (Aziatische range breuk om 07:00-09:00 UTC)
  3. RSI crossover entries (meer signalen dan enkel niveau)
  4. ADX momentum filter
Alle varianten testen op 12 maanden H1 GC=F data.
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL   = 160_000.0
EUR_RATE   = 1.17              # 1 EUR = 1.17 USD
FTMO_DAG   = 6_000.0 * EUR_RATE   # EUR 6000 daglimiet verlies -> USD $7,020
FTMO_TOT   = 16_000.0 * EUR_RATE  # EUR 16000 totaallimiet verlies -> USD $18,720
MAANDEN    = 13

# ─── INDICATOREN ──────────────────────────────────────────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi_fn(c, p):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p-1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p-1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))

def atr_fn(hi, lo, cl, p=14):
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs()
    ], axis=1).max(axis=1)
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

# ─── DATA LADEN ───────────────────────────────────────────────────────────────
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

# ─── INDICATOREN BOUWEN ───────────────────────────────────────────────────────
def bereid_voor(df):
    d = df.copy()

    # H1 indicatoren
    d["e21"]   = ema(d["close"], 21)
    d["e50"]   = ema(d["close"], 50)
    d["rsi5"]  = rsi_fn(d["close"], 5)
    d["rsi14"] = rsi_fn(d["close"], 14)
    d["atr"]   = atr_fn(d["high"], d["low"], d["close"], 14)
    d["adx_h1"] = adx_fn(d["high"], d["low"], d["close"], 14)

    # H4 resample
    h4 = d.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
    h4["e21"]   = ema(h4["close"], 21)
    h4["e50"]   = ema(h4["close"], 50)
    h4["slope"] = h4["e21"] - h4["e21"].shift(3)
    h4["adx"]   = adx_fn(h4["high"], h4["low"], h4["close"], 14)
    h4["rsi5"]  = rsi_fn(h4["close"], 5)
    h4["bias"]  = np.where(h4["e21"] > h4["e50"], "bull", "bear")

    d["h4_bias"]  = h4["bias"].reindex(d.index, method="ffill").fillna("bear")
    d["h4_slope"] = h4["slope"].reindex(d.index, method="ffill").fillna(0)
    d["h4_adx"]   = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_rsi5"]  = h4["rsi5"].reindex(d.index, method="ffill").fillna(50)

    # D1 resample
    d1 = d.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")

    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bear")
    d["d1_e50"]   = d1["de50"].reindex(d.index, method="ffill")
    d["d1_e200"]  = d1["de200"].reindex(d.index, method="ffill")

    # Aziatische range voor London Breakout (00:00-07:00 UTC)
    d["uur"]   = d.index.hour
    d["datum"] = d.index.date

    aziatisch = d[d["uur"] < 7].groupby("datum").agg(
        az_hoog=("high", "max"),
        az_laag=("low", "min")
    )
    d["az_hoog"]  = d["datum"].map(aziatisch["az_hoog"])
    d["az_laag"]  = d["datum"].map(aziatisch["az_laag"])
    d["az_range"] = (d["az_hoog"] - d["az_laag"]).fillna(0)

    return d.dropna(subset=["rsi5","h4_bias","d1_trend","atr","az_range"])

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
def backtest(df, cfg, label=""):
    risk      = cfg["risk"]
    sl_m      = cfg.get("sl", 1.3)
    tp_m      = cfg.get("tp", 3.0)
    be_m      = cfg.get("be", 1.0)
    adx_min   = cfg.get("adx_min", 20)
    rsi_long  = cfg.get("rsi_long", 30)
    rsi_short = cfg.get("rsi_short", 70)
    s0        = cfg.get("s0", 7)
    s1        = cfg.get("s1", 19)
    max_dag   = cfg.get("max_dag", 2)
    shorts    = cfg.get("shorts", False)
    london    = cfg.get("london", False)
    lon_buf   = cfg.get("lon_buf", 0.20)
    slope_req = cfg.get("slope", True)
    cross_sig = cfg.get("crossover", False)

    kap    = KAPITAAL
    piek   = KAPITAAL
    trs    = []
    dag_v  = {}   # date -> {"verlies": float, "count": int}

    # posities
    ip = False
    entry = sl = tp = sla = risk_usd = richting = sig_type = ot = None
    bd = False
    prev_rsi5 = 50.0

    for i in range(5, len(df)):
        b    = df.iloc[i]
        p    = df.iloc[i-1]
        dat  = b.name.date()
        uur  = b.name.hour

        if dat not in dag_v:
            dag_v[dat] = {"verlies": 0.0, "count": 0}

        # FTMO totaalcheck
        if (piek - kap) >= FTMO_TOT:
            # Sluit open positie op huidige koers voor correcte P&L
            if ip:
                exit_p = float(b["close"])
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd
                kap += pnl_usd
                if kap > piek: piek = kap
                trs.append({
                    "in": ot, "uit": b.name,
                    "rich": richting, "entry": entry, "exit": exit_p,
                    "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE,
                    "result": "FAIL_CLOSE", "type": sig_type,
                })
                ip = False
            bd = True; break

        # ── Beheer open positie ──
        if ip:
            # Break-even aanpassen
            if richting == 1:
                if (b["close"] - entry) >= be_m * sla and sl < entry:
                    sl = entry
            else:
                if (entry - b["close"]) >= be_m * sla and sl > entry:
                    sl = entry

            hit_sl = (richting == 1 and b["low"] <= sl) or (richting == -1 and b["high"] >= sl)
            hit_tp = (richting == 1 and b["high"] >= tp) or (richting == -1 and b["low"] <= tp)

            if hit_sl or hit_tp:
                exit_p = tp if hit_tp else sl
                pnl_usd = richting * (exit_p - entry) / sla * risk_usd

                # FTMO dagverlies afdwingen
                if pnl_usd < 0:
                    dag_verlies_nu = dag_v[dat]["verlies"]
                    if dag_verlies_nu + abs(pnl_usd) > FTMO_DAG:
                        pnl_usd = -(FTMO_DAG - dag_verlies_nu)
                    dag_v[dat]["verlies"] += abs(pnl_usd)

                kap += pnl_usd
                if kap > piek:
                    piek = kap

                trs.append({
                    "in":   ot,
                    "uit":  b.name,
                    "rich": richting,
                    "entry": entry,
                    "exit": exit_p,
                    "pnl_usd": pnl_usd,
                    "pnl_eur": pnl_usd / EUR_RATE,
                    "result": "TP" if hit_tp else "SL",
                    "type": sig_type,
                })
                ip = False

        # ── Signaal zoeken ──
        if not ip:
            # Sessie- en FTMO-check
            in_sessie   = s0 <= uur < s1
            dag_verlies = dag_v[dat]["verlies"]
            dag_count   = dag_v[dat]["count"]

            if not in_sessie or dag_verlies >= FTMO_DAG * 0.85 or dag_count >= max_dag:
                prev_rsi5 = float(b["rsi5"])
                continue

            h4_bull  = b["h4_bias"] == "bull"
            h4_bear  = b["h4_bias"] == "bear"
            h4_adx_v = float(b["h4_adx"])
            h4_slope = float(b["h4_slope"]) > 0
            d1_bull  = b["d1_trend"] == "bull"
            d1_bear  = b["d1_trend"] == "bear"
            rsi5_v   = float(b["rsi5"])
            atr_v    = float(b["atr"])
            az_hoog  = b["az_hoog"]
            az_laag  = b["az_laag"]
            az_r     = float(b["az_range"])

            adx_ok = h4_adx_v >= adx_min
            sig    = None

            # ── Long RSI pullback ──
            if h4_bull and d1_bull and adx_ok:
                trend_ok = (not slope_req) or h4_slope
                if trend_ok:
                    if cross_sig:
                        # RSI5 was boven drempel, nu eronder (oversold pullback)
                        if prev_rsi5 >= rsi_long and rsi5_v < rsi_long:
                            sig = ("long", "RSI_CROSS")
                    else:
                        if rsi5_v < rsi_long:
                            sig = ("long", "RSI_LEVEL")

            # ── Short RSI pullback ──
            if sig is None and shorts and h4_bear and d1_bear and adx_ok:
                if cross_sig:
                    if prev_rsi5 <= rsi_short and rsi5_v > rsi_short:
                        sig = ("short", "RSI_CROSS")
                else:
                    if rsi5_v > rsi_short:
                        sig = ("short", "RSI_LEVEL")

            # ── London Breakout (07:00-09:00 UTC) ──
            if sig is None and london and 7 <= uur < 9 and az_r > 5.0:
                buf = lon_buf * az_r
                if not pd.isna(az_hoog) and not pd.isna(az_laag):
                    # Long breakout: H4 bullish of neutraal, prijs breekt boven Aziatische hoog
                    if h4_bull and b["close"] > az_hoog + buf:
                        sig = ("long", "LONDON")
                    # Short breakout: H4 bearish, prijs breekt onder Aziatische laag
                    elif shorts and h4_bear and b["close"] < az_laag - buf:
                        sig = ("short", "LONDON")

            # ── Positie openen ──
            if sig is not None:
                richting_str, sig_type = sig
                richting = 1 if richting_str == "long" else -1
                entry    = float(b["close"])
                sla      = sl_m * atr_v
                sl       = entry - richting * sla
                tp       = entry + richting * tp_m * sla
                risk_usd = kap * risk
                ot       = b.name
                ip       = True
                dag_v[dat]["count"] += 1

        prev_rsi5 = float(b["rsi5"])

    # Open positie sluiten op einde (alleen als challenge NIET gefaald)
    if ip and not bd:
        exit_p  = float(df.iloc[-1]["close"])
        pnl_usd = richting * (exit_p - entry) / sla * risk_usd
        kap += pnl_usd
        trs.append({
            "in": ot, "uit": df.index[-1],
            "rich": richting, "entry": entry, "exit": exit_p,
            "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE,
            "result": "OPEN", "type": sig_type,
        })

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
    n = len(df_t)
    wr = 100 * (df_t["pnl_usd"] > 0).mean()
    gw = df_t[df_t["pnl_usd"] > 0]["pnl_usd"].sum()
    gl = df_t[df_t["pnl_usd"] < 0]["pnl_usd"].abs().sum()
    pf = gw / gl if gl > 0 else 999.0

    dagen = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    weken = dagen / 7
    gem_week = pnl_eur / weken
    gem_dag  = pnl_eur / dagen

    # Max drawdown
    cap_loop = KAPITAAL
    piek_loop = KAPITAAL
    max_dd = 0.0
    for t in trs:
        cap_loop += t["pnl_usd"]
        if cap_loop > piek_loop: piek_loop = cap_loop
        dd = piek_loop - cap_loop
        if dd > max_dd: max_dd = dd

    status = "CHALLENGE GEFAALD" if challenge_fail else "GESLAAGD"
    print(f"  Kapitaal : $ {KAPITAAL:>10,.0f} -> $ {kap_eind:>10,.0f}")
    print(f"  P&L      : $ {pnl_usd:>+10,.0f}  (EUR {pnl_eur:>+10,.0f})")
    print(f"  Gem/week : EUR {gem_week:>+8,.0f}  |  Gem/dag: EUR {gem_dag:>+8,.0f}")
    print(f"  Max DD   : $ {max_dd:>9,.0f}  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
    print(f"  Challenge: {status}")

    # Signaalverdeling
    type_cnt = df_t["type"].value_counts()
    print(f"  Signalen : {dict(type_cnt)}")
    print()

    # Maandtabel
    mnd = df_t.groupby("maand").agg(
        trades=("pnl_usd", "count"),
        win=("pnl_usd", lambda x: (x > 0).sum()),
        pnl_eur=("pnl_eur", "sum"),
    ).reset_index()
    mnd["win_pct"] = 100 * mnd["win"] / mnd["trades"]
    mnd["gem_dag"] = mnd["pnl_eur"] / 21
    mnd["gem_week"] = mnd["gem_dag"] * 5

    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>12} {'Gem/week':>10}  Signalen")
    print("  " + "-" * 65)

    for _, r in mnd.iterrows():
        flag = " *** TOP" if r["pnl_eur"] > 5000 else (" --- ZWAK" if r["pnl_eur"] < -3000 else "")
        mnd_str = str(r["maand"])
        mnd_trs = df_t[df_t["maand"] == r["maand"]]
        sig_str = "/".join([f"{k}:{v}" for k,v in mnd_trs["type"].value_counts().items()])
        print(f"  {mnd_str:<10} {r['trades']:>6}  {r['win_pct']:>4.1f}%  EUR {r['pnl_eur']:>8,.0f}  EUR {r['gem_week']:>+8,.0f}  {sig_str}{flag}")

    print("=" * 70)

    return {
        "label": label, "pnl_eur": pnl_eur, "gem_week": gem_week,
        "trades": n, "wr": wr, "pf": pf,
        "max_dd_eur": max_dd / EUR_RATE,
        "status": status,
    }

# ─── VARIANTEN ────────────────────────────────────────────────────────────────
VARIANTEN = {
    "V7-BASE": {
        "desc": "Basis (= REF-v4b, control)",
        "risk": 0.015, "sl": 1.3, "tp": 3.0, "be": 1.0,
        "adx_min": 20, "rsi_long": 30,
        "s0": 7, "s1": 19, "max_dag": 2,
        "shorts": False, "london": False, "slope": True, "crossover": False,
    },
    "V7-LongShort": {
        "desc": "Long + Short (bidirectioneel in trend)",
        "risk": 0.012, "sl": 1.3, "tp": 2.5, "be": 1.0,
        "adx_min": 22, "rsi_long": 32, "rsi_short": 68,
        "s0": 7, "s1": 19, "max_dag": 3,
        "shorts": True, "london": False, "slope": False, "crossover": False,
    },
    "V7-London": {
        "desc": "Long + London Breakout (07:00-09:00 UTC)",
        "risk": 0.015, "sl": 1.3, "tp": 2.5, "be": 1.0,
        "adx_min": 18, "rsi_long": 30, "lon_buf": 0.15,
        "s0": 7, "s1": 19, "max_dag": 2,
        "shorts": False, "london": True, "slope": True, "crossover": False,
    },
    "V7-LondonShort": {
        "desc": "Long + Short + London (alle signalen)",
        "risk": 0.012, "sl": 1.3, "tp": 2.5, "be": 0.8,
        "adx_min": 20, "rsi_long": 32, "rsi_short": 68, "lon_buf": 0.15,
        "s0": 7, "s1": 19, "max_dag": 3,
        "shorts": True, "london": True, "slope": False, "crossover": False,
    },
    "V7-CrossShort": {
        "desc": "RSI crossover + Short + London (max signalen)",
        "risk": 0.010, "sl": 1.2, "tp": 2.5, "be": 0.8,
        "adx_min": 18, "rsi_long": 35, "rsi_short": 65, "lon_buf": 0.15,
        "s0": 6, "s1": 20, "max_dag": 4,
        "shorts": True, "london": True, "slope": False, "crossover": True,
    },
    "V7-Agressief": {
        "desc": "Long only, hogere risk + TP voor grote winsten",
        "risk": 0.020, "sl": 1.2, "tp": 4.0, "be": 1.5,
        "adx_min": 20, "rsi_long": 30,
        "s0": 7, "s1": 19, "max_dag": 2,
        "shorts": False, "london": False, "slope": True, "crossover": False,
    },
}

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  XAUUSD STRATEGIE v7 | MULTI-SIGNAAL | DOEL: EUR 6000/WEEK")
    print("=" * 70)

    print("\n[1] Data laden...")
    df_raw = laad()

    print("[2] Indicatoren bouwen...")
    df = bereid_voor(df_raw)
    print(f"  {len(df)} H1 bars klaar voor backtest")

    print(f"[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind, failed = backtest(df, cfg, naam)
        res = rapport(trs, kap_eind, failed, f"{naam} | {cfg['desc']}")
        if res:
            resultaten.append(res)

    # Eindoverzicht gesorteerd op gem_week
    print()
    print("=" * 70)
    print("  EINDOVERZICHT — gesorteerd op gemiddelde winst/week")
    print("=" * 70)
    print(f"  {'Variant':<18} {'EUR P&L':>10} {'Gem/week':>10} {'Trades':>7} {'Win%':>6} {'PF':>6} {'Max DD EUR':>12}  Status")
    print("  " + "-" * 80)
    for r in sorted(resultaten, key=lambda x: -x["gem_week"]):
        mark = " <-- BESTE" if r == sorted(resultaten, key=lambda x: -x["gem_week"])[0] else ""
        print(f"  {r['label']:<18} EUR {r['pnl_eur']:>+8,.0f} EUR {r['gem_week']:>+7,.0f} "
              f"{r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>6.2f}  EUR {r['max_dd_eur']:>9,.0f}  "
              f"{r['status']}{mark}")
    print("=" * 70)

    # Beste variant analyse
    if resultaten:
        beste = sorted(resultaten, key=lambda x: -x["gem_week"])[0]
        print()
        print("  ANALYSE BESTE VARIANT:")
        print(f"  Variant   : {beste['label']}")
        print(f"  Gem/week  : EUR {beste['gem_week']:+,.0f}")
        print(f"  Win Rate  : {beste['wr']:.1f}%")
        print(f"  PF        : {beste['pf']:.2f}")
        weken_nodig = 160_000 / EUR_RATE / max(beste["gem_week"], 1)
        print(f"  Verwachte FTMO challenge duur: {weken_nodig:.0f} weken ({weken_nodig/4:.1f} maanden)")
        if beste["gem_week"] >= 6000:
            print("  DOEL EUR 6000/WEEK: BEREIKT")
        elif beste["gem_week"] >= 3000:
            print(f"  Realistische doelstelling: EUR {beste['gem_week']:,.0f}/week (niet EUR 6000, maar solide)")
        else:
            print(f"  Realistische doelstelling: EUR {beste['gem_week']:,.0f}/week gemiddeld")
        print("=" * 70)

if __name__ == "__main__":
    main()
