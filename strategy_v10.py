"""
XAUUSD Strategy v10 — Expert Edition
=====================================
Verbeteringen t.o.v. V9:
  1. FTMO correctie    — €8.000/dag (was €6.000), €16.000 totaal
  2. Partiële exit     — 50% sluiten op 1:1 RR → SL naar BE → rest loopt naar 3:1
  3. Sessie-tiers      — Premium (Londen 08-12 / NY 13-17 UTC) krijgt alle signalen
                         Standard (07-08 / 17-19 UTC) alleen STERK
                         Geblokkeerd (00-07 / 19-24 UTC) geen trades
  4. Weekdag-filter    — Maandag vóór 10 UTC skip (gap-risico)
                         Vrijdag na 14 UTC geen nieuwe trades
  5. ATR-filters       — Volatiliteitspiek skip (H1 ATR > 2.5× 20-bar gem)
                         Minimum H4 ATR ≥ $5 (te vlak = no-trade)
  6. Trade-cap         — Max 3 STERK/dag, max 2 ZWAK/dag (was vaste 2 total)
  7. Drawdown-schaling — Agressievere reductie: >3% DD → 0.65×, >6% DD → 0.40×

Doel: 5–8% netto per maand, FTMO €160k account.
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL  = 160_000.0   # EUR (FTMO funded account)
EUR_RATE  = 1.17        # EUR→USD conversie (backtest gebruikt USD intern)
FTMO_DAG  = 8_000.0 * EUR_RATE   # €8,000 = $9,360   (5% dagelijks)
FTMO_TOT  = 16_000.0 * EUR_RATE  # €16,000 = $18,720  (10% totaal)
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
    d["rsi5"]     = rsi_fn(d["close"], 5)
    d["atr_h1"]   = atr_fn(d["high"], d["low"], d["close"], 14)
    d["atr_h1_ma"]= d["atr_h1"].rolling(20).mean()   # 20-bar gem voor spike-filter

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
        if   bull and adx >= 26 and sl3 > 0 and row["e50"] > row["e200"]: return "STERK_BULL"
        elif bull and adx >= 18:                                            return "ZWAK_BULL"
        elif bear and adx >= 26 and sl3 < 0 and row["e50"] < row["e200"]: return "STERK_BEAR"
        elif bear and adx >= 18:                                            return "ZWAK_BEAR"
        else:                                                                return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)
    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")

    # D1 trend
    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min",
                                 "close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bull")

    return d.dropna(subset=["rsi5","atr_h1","h4_atr","h4_regime","d1_trend"])

# ── Sessie-tier helper ─────────────────────────────────────────────────────────

def sessie_tier(uur):
    """
    'premium'  → Londen (08-12) of NY (13-17) UTC  — alle signalen
    'standard' → 07-08 of 17-19 UTC               — alleen STERK
    'blocked'  → rest (Asian + nacht)              — geen trades
    """
    if 8 <= uur < 12 or 13 <= uur < 17:
        return "premium"
    if uur == 7 or 17 <= uur < 19:
        return "standard"
    return "blocked"

# ── Backtest ───────────────────────────────────────────────────────────────────

def backtest(df, cfg):
    risk_sterk = cfg.get("risk_sterk", 0.015)
    risk_zwak  = cfg.get("risk_zwak",  0.008)
    sl_m    = cfg.get("sl",  1.0)
    tp_m    = cfg.get("tp",  3.0)
    rsi_ov  = cfg.get("rsi_ov", 30)
    rsi_zwk = cfg.get("rsi_zwk", 35)
    partial = cfg.get("partial", True)   # partiële exit aan/uit
    max_sterk = cfg.get("max_sterk", 3)
    max_zwak  = cfg.get("max_zwak",  2)

    kap = KAPITAAL * EUR_RATE   # intern in USD
    piek = kap
    trs = []; dag_info = {}
    ip = False
    entry = sl = tp = tp_partial = sla = risk_usd = richting = sig_type = ot = None
    partial_done = False

    for i in range(50, len(df)):
        b   = df.iloc[i]
        dat = b.name.date()
        uur = b.name.hour
        dow = b.name.weekday()   # 0=Mon, 4=Fri

        if dat not in dag_info:
            dag_info[dat] = {"verlies": 0.0, "n_sterk": 0, "n_zwak": 0}

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
            cur  = float(b["close"])
            hi   = float(b["high"])
            lo   = float(b["low"])

            # Break-even trigger (hele positie)
            if richting == 1  and (cur - entry) >= sla and sl < entry: sl = entry
            if richting == -1 and (entry - cur) >= sla and sl > entry: sl = entry

            # Partiële exit op 1:1
            if partial and not partial_done:
                hit_partial = (richting == 1 and hi >= tp_partial) or (richting == -1 and lo <= tp_partial)
                if hit_partial:
                    pnl_part = richting * (tp_partial - entry) / sla * (risk_usd * 0.5)
                    kap += pnl_part
                    if kap > piek: piek = kap
                    trs.append(_tr(ot, b.name, richting, entry, tp_partial, pnl_part, "PARTIAL", sig_type))
                    partial_done = True
                    sl = entry   # SL naar BE na partiële exit
                    risk_usd *= 0.5   # resterende positie

            # SL / TP check
            hit_sl = (richting ==  1 and lo <= sl) or (richting == -1 and hi >= sl)
            hit_tp = (richting ==  1 and hi >= tp) or (richting == -1 and lo <= tp)

            if hit_sl or hit_tp:
                exit_p  = tp if hit_tp else sl
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
                ip = False; partial_done = False

        # Nieuw signaal
        if not ip:
            dv  = dag_info[dat]["verlies"]
            ns  = dag_info[dat]["n_sterk"]
            nw  = dag_info[dat]["n_zwak"]

            tier = sessie_tier(uur)
            if tier == "blocked": continue

            # Weekdag-filter
            if dow == 0 and uur < 10: continue   # Maandag: wacht op London
            if dow == 4 and uur >= 14: continue  # Vrijdag: geen nieuwe trades na 14 UTC

            # FTMO dag-buffer (stop als 65% van dagbudget op)
            if dv >= FTMO_DAG * 0.65: continue

            regime   = b["h4_regime"]
            d1_bull  = b["d1_trend"] == "bull"
            d1_bear  = b["d1_trend"] == "bear"
            rsi5     = float(b["rsi5"])
            atr_h4   = float(b["h4_atr"])
            atr_h1   = float(b["atr_h1"])
            atr_ma   = float(b["atr_h1_ma"]) if not pd.isna(b["atr_h1_ma"]) else atr_h1

            if regime == "CHOPPY": continue

            # ATR-filters
            if atr_h4 < 5.0: continue                   # te vlak
            if atr_h1 > 2.5 * atr_ma: continue          # volatiliteitspiek (news)

            sig = None
            sterk = regime in ("STERK_BULL", "STERK_BEAR")

            if regime == "STERK_BULL" and d1_bull and rsi5 < rsi_ov  and ns < max_sterk:
                sig = ("long", "STERK_LONG", risk_sterk, True)
            elif regime == "ZWAK_BULL" and d1_bull and rsi5 < rsi_zwk and nw < max_zwak and tier == "premium":
                sig = ("long", "ZWAK_LONG", risk_zwak, False)
            elif regime == "STERK_BEAR" and d1_bear and rsi5 > (100-rsi_ov) and ns < max_sterk:
                sig = ("short", "STERK_SHORT", risk_sterk, True)
            elif regime == "ZWAK_BEAR" and d1_bear and rsi5 > (100-rsi_zwk) and nw < max_zwak and tier == "premium":
                sig = ("short", "ZWAK_SHORT", risk_zwak, False)

            # Standard-sessie: alleen STERK
            if sig and tier == "standard" and not sig[3]: sig = None

            if sig:
                richting_str, sig_type, risk_pct, is_sterk = sig
                richting = 1 if richting_str == "long" else -1
                entry    = float(b["close"])
                sla      = sl_m * atr_h4
                sl       = entry - richting * sla
                tp       = entry + richting * tp_m * sla
                tp_partial = entry + richting * sla   # 1:1 voor partiële exit

                dd_pct = (piek - kap) / piek
                if   dd_pct > 0.06: risk_pct *= 0.40
                elif dd_pct > 0.03: risk_pct *= 0.65

                risk_usd  = kap * risk_pct
                partial_done = False
                ot = b.name; ip = True
                if is_sterk: dag_info[dat]["n_sterk"] += 1
                else:        dag_info[dat]["n_zwak"]  += 1

    return trs, kap / EUR_RATE   # geef kapitaal terug in EUR

def _tr(ti, to, rich, entry, exit_p, pnl_usd, result, stype):
    return {"in": ti, "uit": to, "rich": rich, "entry": entry, "exit": exit_p,
            "pnl_usd": pnl_usd, "pnl_eur": pnl_usd / EUR_RATE,
            "result": result, "type": stype}

# ── Rapport ────────────────────────────────────────────────────────────────────

def rapport(trs, kap_eur_eind, label):
    pnl_eur = kap_eur_eind - KAPITAAL
    print(); print("="*72); print(f"  {label}"); print("="*72)
    if not trs:
        print("  Geen trades."); print("="*72); return {}

    df_t = pd.DataFrame(trs)
    df_t["maand"] = pd.to_datetime(df_t["in"]).dt.to_period("M")
    closed = df_t[df_t["result"] != "PARTIAL"]   # alleen gesloten halve/volledige
    n   = int((df_t["result"].isin(["TP","SL","FAIL","OPEN"])).sum())
    wr  = 100 * (closed[closed["result"] == "TP"]["pnl_eur"].count()) / max(n, 1)
    gw  = closed[closed["pnl_eur"] > 0]["pnl_eur"].sum()
    gl  = closed[closed["pnl_eur"] < 0]["pnl_eur"].abs().sum()
    pf  = gw / gl if gl > 0 else 999.0

    dagen  = max((pd.to_datetime(df_t["uit"].max()) - pd.to_datetime(df_t["in"].min())).days, 1)
    mnd_n  = dagen / 30.44
    gem_mnd= pnl_eur / mnd_n
    mnd_pct= pnl_eur / KAPITAAL * 100 / mnd_n

    # Max drawdown in EUR
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
    print(f"  Max DD   : €{max_dd/EUR_RATE:>8,.0f}  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")

    # Maandoverzicht
    mnd = df_t[df_t["result"] != "PARTIAL"].groupby("maand").agg(
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
    "V10-Basis": {
        "desc": "H4 ATR 1×, TP 3:1, RSI 30/35, Partieel 1:1, Sessie-tiers",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.0, "rsi_ov":30, "rsi_zwk":35,
        "partial":True, "max_sterk":3, "max_zwak":2,
    },
    "V10-TP4": {
        "desc": "TP 4:1, ruimere doelen, partial op 1:1",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":4.0, "rsi_ov":30, "rsi_zwk":35,
        "partial":True, "max_sterk":3, "max_zwak":2,
    },
    "V10-SterkeOnly": {
        "desc": "Alleen STERK regime, TP 3.5:1, risk 1.8%",
        "risk_sterk":0.018, "risk_zwak":0.000,
        "sl":1.0, "tp":3.5, "rsi_ov":30, "rsi_zwk":35,
        "partial":True, "max_sterk":3, "max_zwak":0,
    },
    "V10-RSIStreng": {
        "desc": "RSI 25/30 — alleen extreme pullbacks",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.0, "rsi_ov":25, "rsi_zwk":30,
        "partial":True, "max_sterk":3, "max_zwak":2,
    },
    "V10-GeenPartial": {
        "desc": "Zonder partiële exit (V9-stijl), referentie",
        "risk_sterk":0.015, "risk_zwak":0.008,
        "sl":1.0, "tp":3.0, "rsi_ov":30, "rsi_zwk":35,
        "partial":False, "max_sterk":2, "max_zwak":2,
    },
    "V10-Agressief": {
        "desc": "Risk 2.0%/1.0%, max 4 STERK, TP 3:1",
        "risk_sterk":0.020, "risk_zwak":0.010,
        "sl":1.0, "tp":3.0, "rsi_ov":30, "rsi_zwk":35,
        "partial":True, "max_sterk":4, "max_zwak":2,
    },
}

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("="*72)
    print("  XAUUSD STRATEGIE v10 | EXPERT EDITION | DOEL: 5–8%/MAAND")
    print("  FTMO €160k: Dag-limiet €8.000 | Totaal €16.000")
    print("="*72)

    print("[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren bouwen (H1 + H4 + D1)...")
    df = bereid_voor(df_raw)

    h4_atr_gem = df["h4_atr"].mean()
    regime_cnt = df["h4_regime"].value_counts()
    print(f"  H4 ATR gem: ${h4_atr_gem:.1f}  |  SL ~${1.0*h4_atr_gem:.0f}  TP ~${3.0*h4_atr_gem:.0f}")
    for r, c in regime_cnt.items():
        pct = 100 * c / len(df)
        print(f"    {r:<15}: {c:>5} bars ({pct:>4.1f}%)")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")

    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eur = backtest(df, cfg)
        res = rapport(trs, kap_eur, naam)
        if res: resultaten.append(res)

    # Eindoverzicht
    print(); print("="*72)
    print("  EINDOVERZICHT v10"); print("="*72)
    print(f"  {'Variant':<22} {'EUR P&L':>12} {'%/mnd':>7} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD':>10}")
    print("  "+"-"*75)

    for r in sorted(resultaten, key=lambda x: -x["maand_pct"]):
        doel = " DOEL!" if r["maand_pct"] >= 5 else (" TOP" if r["maand_pct"] >= 3 else "")
        print(f"  {r['label']:<22} €{r['pnl_eur']:>+10,.0f} {r['maand_pct']:>6.2f}%"
              f" {r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  €{r['max_dd_eur']:>7,.0f}{doel}")

    if resultaten:
        beste = sorted(resultaten, key=lambda x: -x["maand_pct"])[0]
        print(f"\n  BESTE VARIANT: {beste['label']}")
        print(f"  {beste['maand_pct']:+.2f}%/mnd | WR {beste['wr']:.1f}% | PF {beste['pf']:.2f} | MaxDD €{beste['max_dd_eur']:,.0f}")
        mnd = beste["mnd"]
        pos = (mnd["pnl_eur"] > 0).sum(); tot = len(mnd)
        doel_mnd = (mnd["pct_mnd"] >= 5).sum()
        print(f"  Positieve maanden: {pos}/{tot}  |  Maanden ≥5%: {doel_mnd}/{tot}")
        if beste["maand_pct"] >= 5:
            print(f"\n  ✓ DOEL 5-8%/MAAND BEREIKT!")
        elif beste["maand_pct"] >= 2:
            print(f"\n  Nog {5-beste['maand_pct']:.1f}% van het 5%-doel.")
    print("="*72)

if __name__ == "__main__":
    main()
