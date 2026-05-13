"""
XAUUSD Strategy v8b - H4 ATR Stop Placement
=============================================
Probleem geidentificeerd: H1 ATR stop (1.3x ~$26) wordt geraakt
door normale H4-niveau schommelingen (~$80/bar).
Oplossing: gebruik H4 ATR voor SL bepaling -> meer ruimte voor trade,
hogere Win Rate (verwacht 35-45% van 20% nu).

Wiskundige check 5%/maand:
  - 6 trades/maand x 35% WR x 3:1 @ 1.5% risk
  - EV per trade = 0.35 x $7,200 - 0.65 x $2,400 = $960
  - 6 x $960 = $5,760/maand = 3.6% -> bijna 5%
  - 8 trades/maand x 40% WR x 3:1 @ 1.5% = $1,440/trade x 8 = $11,520 = 7.2% -> DOEL!
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta
import os; os.makedirs("results", exist_ok=True)

KAPITAAL  = 160_000.0
EUR_RATE  = 1.17
FTMO_DAG  = 6_000.0 * EUR_RATE
FTMO_TOT  = 16_000.0 * EUR_RATE
MAANDEN   = 13

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
    pm = ((u>dw)&(u>0))*u; mm = ((dw>u)&(dw>0))*dw
    at = atr_fn(hi,lo,cl,p).replace(0,np.nan)
    pdi = 100*pm.ewm(com=p-1,adjust=False).mean()/at
    mdi = 100*mm.ewm(com=p-1,adjust=False).mean()/at
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(com=p-1,adjust=False).mean().fillna(0)

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
    d["rsi5"]    = rsi_fn(d["close"], 5)
    d["rsi14"]   = rsi_fn(d["close"], 14)
    d["atr_h1"]  = atr_fn(d["high"], d["low"], d["close"], 14)

    h4 = d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
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
        if bull and adx >= 26 and sl3 > 0 and row["e50"] > row["e200"]:
            return "STERK_BULL"
        elif bull and adx >= 18:
            return "ZWAK_BULL"
        elif bear and adx >= 26 and sl3 < 0 and row["e50"] < row["e200"]:
            return "STERK_BEAR"
        elif bear and adx >= 18:
            return "ZWAK_BEAR"
        else:
            return "CHOPPY"

    h4["regime"] = h4.apply(regime, axis=1)
    d["h4_regime"] = h4["regime"].reindex(d.index, method="ffill").fillna("CHOPPY")
    d["h4_adx"]    = h4["adx"].reindex(d.index, method="ffill").fillna(0)
    d["h4_atr"]    = h4["atr"].reindex(d.index, method="ffill")   # ← H4 ATR voor SL
    d["h4_rsi14"]  = h4["rsi14"].reindex(d.index, method="ffill").fillna(50)

    d1 = d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]  = ema(d1["close"], 50)
    d1["de200"] = ema(d1["close"], 200)
    d1["trend"] = np.where(d1["close"] > d1["de50"], "bull", "bear")
    d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("bear")
    d["d1_e200"]  = d1["de200"].reindex(d.index, method="ffill")

    return d.dropna(subset=["rsi5","atr_h1","h4_atr","h4_regime","d1_trend"])

def backtest(df, cfg):
    risk_sterk  = cfg.get("risk_sterk", 0.015)
    risk_zwak   = cfg.get("risk_zwak", 0.008)
    sl_m        = cfg.get("sl", 1.0)       # vermenigvuldiger voor H4 ATR
    tp_m        = cfg.get("tp", 3.0)       # R:R ratio
    be_m        = cfg.get("be", 1.0)       # break-even trigger als veelvoud van SL dist
    rsi_sterk   = cfg.get("rsi_sterk", 30)
    rsi_zwak    = cfg.get("rsi_zwak", 35)
    s0, s1      = cfg.get("s0", 7), cfg.get("s1", 19)
    max_dag     = cfg.get("max_dag", 2)
    handel_zwak = cfg.get("handel_zwak", True)
    gebruik_h4_atr = cfg.get("h4_atr_sl", True)  # True = H4 ATR, False = H1 ATR

    kap  = KAPITAAL; piek = KAPITAAL
    trs  = []; dag_v = {}
    ip   = False
    entry=sl=tp=sla=risk_usd=richting=sig_type=ot=None
    bd   = False

    for i in range(50, len(df)):
        b = df.iloc[i]; dat = b.name.date(); uur = b.name.hour
        if dat not in dag_v: dag_v[dat] = {"verlies":0.0,"count":0}

        if (piek - kap) >= FTMO_TOT:
            if ip:
                exit_p = float(b["close"])
                pnl_usd = richting*(exit_p-entry)/sla*risk_usd
                kap += pnl_usd
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                            "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"FAIL","type":sig_type})
                ip = False
            bd = True; break

        if ip:
            if richting==1:
                if (b["close"]-entry)>=be_m*sla and sl<entry: sl=entry
            else:
                if (entry-b["close"])>=be_m*sla and sl>entry: sl=entry
            hit_sl=(richting==1 and b["low"]<=sl)or(richting==-1 and b["high"]>=sl)
            hit_tp=(richting==1 and b["high"]>=tp)or(richting==-1 and b["low"]<=tp)
            if hit_sl or hit_tp:
                exit_p=tp if hit_tp else sl
                pnl_usd=richting*(exit_p-entry)/sla*risk_usd
                if pnl_usd<0:
                    dv=dag_v[dat]["verlies"]
                    if dv+abs(pnl_usd)>FTMO_DAG: pnl_usd=-(FTMO_DAG-dv)
                    dag_v[dat]["verlies"]+=abs(pnl_usd)
                kap+=pnl_usd
                if kap>piek: piek=kap
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                            "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,
                            "result":"TP" if hit_tp else "SL","type":sig_type})
                ip=False

        if not ip:
            in_sessie=s0<=uur<s1
            dv=dag_v[dat]["verlies"]; dc=dag_v[dat]["count"]
            if not in_sessie or dv>=FTMO_DAG*0.65 or dc>=max_dag: continue

            regime  = b["h4_regime"]
            d1_bull = b["d1_trend"]=="bull"
            d1_bear = b["d1_trend"]=="bear"
            rsi5_v  = float(b["rsi5"])
            atr_h1  = float(b["atr_h1"])
            atr_h4  = float(b["h4_atr"])
            sl_base = atr_h4 if gebruik_h4_atr else atr_h1

            sig = None

            if regime=="STERK_BULL" and d1_bull and rsi5_v < rsi_sterk:
                sig = ("long","STERK_LONG",risk_sterk)
            elif handel_zwak and regime=="ZWAK_BULL" and d1_bull and rsi5_v < rsi_zwak:
                sig = ("long","ZWAK_LONG",risk_zwak)
            elif regime=="STERK_BEAR" and d1_bear and rsi5_v > (100-rsi_sterk):
                sig = ("short","STERK_SHORT",risk_sterk)
            elif handel_zwak and regime=="ZWAK_BEAR" and d1_bear and rsi5_v > (100-rsi_zwak):
                sig = ("short","ZWAK_SHORT",risk_zwak)

            if sig:
                richting_str, sig_type, risk_pct = sig
                richting = 1 if richting_str=="long" else -1
                entry    = float(b["close"])
                sla      = sl_m * sl_base
                sl       = entry - richting*sla
                tp       = entry + richting*tp_m*sla
                dd_pct   = (piek-kap)/piek
                if dd_pct>0.06: risk_pct*=0.5
                elif dd_pct>0.03: risk_pct*=0.75
                risk_usd = kap * risk_pct
                ot=b.name; ip=True; dag_v[dat]["count"]+=1

    if ip and not bd:
        exit_p=float(df.iloc[-1]["close"])
        pnl_usd=richting*(exit_p-entry)/sla*risk_usd
        kap+=pnl_usd
        trs.append({"in":ot,"uit":df.index[-1],"rich":richting,"entry":entry,"exit":exit_p,
                    "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"OPEN","type":sig_type})
    return trs, kap, bd

def rapport(trs, kap_eind, failed, label):
    pnl_usd=kap_eind-KAPITAAL; pnl_eur=pnl_usd/EUR_RATE
    print(); print("="*70); print(f"  {label}"); print("="*70)
    if not trs: print("  Geen trades."); print("="*70); return {}
    df_t=pd.DataFrame(trs); df_t["maand"]=pd.to_datetime(df_t["in"]).dt.to_period("M")
    n=len(df_t); wr=100*(df_t["pnl_usd"]>0).mean()
    gw=df_t[df_t["pnl_usd"]>0]["pnl_usd"].sum(); gl=df_t[df_t["pnl_usd"]<0]["pnl_usd"].abs().sum()
    pf=gw/gl if gl>0 else 999.0
    dagen=max((pd.to_datetime(df_t["uit"].max())-pd.to_datetime(df_t["in"].min())).days,1)
    gem_mnd=pnl_eur/(dagen/30.44); gem_wk=pnl_eur/(dagen/7)
    maand_pct=pnl_eur/EUR_RATE/KAPITAAL*100/(dagen/30.44)
    cap_lp=KAPITAAL; pk_lp=KAPITAAL; max_dd=0.0
    for t in trs:
        cap_lp+=t["pnl_usd"]
        if cap_lp>pk_lp: pk_lp=cap_lp
        dd=pk_lp-cap_lp
        if dd>max_dd: max_dd=dd
    status="CHALLENGE GEFAALD" if failed else "GESLAAGD"
    print(f"  Kapitaal : $ {KAPITAAL:>10,.0f} -> $ {kap_eind:>10,.0f}")
    print(f"  P&L      : $ {pnl_usd:>+10,.0f}  (EUR {pnl_eur:>+10,.0f})")
    print(f"  Gem/maand: EUR {gem_mnd:>+8,.0f} ({maand_pct:+.2f}%/mnd)  Doel 5%: {'BEREIKT!' if maand_pct>=5 else f'{5-maand_pct:.1f}% tekort'}")
    print(f"  Max DD   : EUR {max_dd/EUR_RATE:>+8,.0f}  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf:.2f}")
    print(f"  Challenge: {status}")
    sig_cnt=df_t["type"].value_counts(); print(f"  Signalen : {dict(sig_cnt)}")
    print()
    mnd=df_t.groupby("maand").agg(trades=("pnl_usd","count"),
        win=("pnl_usd",lambda x:(x>0).sum()),pnl_eur=("pnl_eur","sum")).reset_index()
    mnd["win_pct"]=100*mnd["win"]/mnd["trades"]
    mnd["pct_mnd"]=mnd["pnl_eur"]/EUR_RATE/KAPITAAL*100
    mnd["gem_week"]=mnd["pnl_eur"]/21*5
    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>12} {'%/mnd':>7} {'Gem/week':>10}")
    print("  "+"-"*60)
    for _,r in mnd.iterrows():
        flag=" *** DOEL" if r["pct_mnd"]>=5 else(" *** TOP" if r["pnl_eur"]>3000 else(" --- ZWAK" if r["pnl_eur"]<-3000 else""))
        print(f"  {str(r['maand']):<10} {r['trades']:>6}  {r['win_pct']:>4.1f}%  EUR {r['pnl_eur']:>8,.0f}  {r['pct_mnd']:>6.2f}%  EUR {r['gem_week']:>+8,.0f}{flag}")
    print("="*70)
    return {"label":label,"pnl_eur":pnl_eur,"gem_mnd":gem_mnd,"gem_wk":gem_wk,
            "maand_pct":maand_pct,"trades":n,"wr":wr,"pf":pf,
            "max_dd_eur":max_dd/EUR_RATE,"status":status,"mnd":mnd}

VARIANTEN = {
    "V8b-H4ATR-1.5pct": {
        "desc":"H4 ATR stop, 1.5%/0.8% risk, long+short",
        "risk_sterk":0.015,"risk_zwak":0.008,
        "sl":1.0,"tp":3.0,"be":1.0,
        "rsi_sterk":30,"rsi_zwak":35,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"h4_atr_sl":True,
    },
    "V8b-H4ATR-2pct": {
        "desc":"H4 ATR stop, 2.0%/1.0% risk, lang+short",
        "risk_sterk":0.020,"risk_zwak":0.010,
        "sl":1.0,"tp":3.0,"be":1.0,
        "rsi_sterk":30,"rsi_zwak":35,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"h4_atr_sl":True,
    },
    "V8b-H4ATR-HogeTP": {
        "desc":"H4 ATR stop, 1.5% risk, TP 4x (hogere winsten)",
        "risk_sterk":0.015,"risk_zwak":0.008,
        "sl":1.0,"tp":4.0,"be":1.5,
        "rsi_sterk":30,"rsi_zwak":35,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"h4_atr_sl":True,
    },
    "V8b-H4ATR-SterkAlleen": {
        "desc":"H4 ATR stop, 2% risk, ALLEEN sterke trend",
        "risk_sterk":0.020,"risk_zwak":0.000,
        "sl":1.0,"tp":3.5,"be":1.2,
        "rsi_sterk":28,"rsi_zwak":35,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":False,"h4_atr_sl":True,
    },
    "V8b-H1ATR-controle": {
        "desc":"H1 ATR stop (controle), 1.5% risk",
        "risk_sterk":0.015,"risk_zwak":0.008,
        "sl":1.3,"tp":3.0,"be":1.0,
        "rsi_sterk":30,"rsi_zwak":35,
        "s0":7,"s1":19,"max_dag":2,
        "handel_zwak":True,"h4_atr_sl":False,
    },
}

def main():
    print("="*70)
    print("  XAUUSD STRATEGIE v8b | H4 ATR STOP | DOEL: 5-8%/MAAND")
    print("="*70)
    print(f"  Hypothese: H4 ATR stop -> hogere WR -> 5%/maand haalbaar")
    print(f"  H4 ATR gemiddeld ~4x H1 ATR = veel meer ruimte voor trade")
    print("\n[1] Data laden...")
    df_raw = laad()
    print("[2] Indicatoren bouwen...")
    df = bereid_voor(df_raw)
    print(f"  {len(df)} H1 bars klaar")

    # Toon H4 ATR vs H1 ATR vergelijking
    h4_atr_gem = df["h4_atr"].mean()
    h1_atr_gem = df["atr_h1"].mean()
    print(f"  H4 ATR gemiddeld: ${h4_atr_gem:.1f}  |  H1 ATR gemiddeld: ${h1_atr_gem:.1f}  |  Ratio: {h4_atr_gem/h1_atr_gem:.1f}x")
    print(f"  Met H4 ATR stop: SL = ${1.0*h4_atr_gem:.1f} | TP = ${3.0*h4_atr_gem:.1f}")
    print(f"  Met H1 ATR stop: SL = ${1.3*h1_atr_gem:.1f} | TP = ${3.0*1.3*h1_atr_gem:.1f}")

    print(f"\n[3] {len(VARIANTEN)} varianten testen...\n")
    resultaten = []
    for naam, cfg in VARIANTEN.items():
        print(f"  [{naam}] {cfg['desc']}")
        trs, kap_eind, failed = backtest(df, cfg)
        res = rapport(trs, kap_eind, failed, naam)
        if res: resultaten.append(res)

    print(); print("="*70)
    print("  EINDOVERZICHT")
    print("="*70)
    print(f"  {'Variant':<28} {'EUR P&L':>10} {'%/mnd':>7} {'Trades':>7} {'Win%':>6} {'PF':>5} {'MaxDD EUR':>10}  Status")
    print("  "+"-"*85)
    geslaagd=[r for r in resultaten if r["status"]=="GESLAAGD"]
    gefaald=[r for r in resultaten if r["status"]!="GESLAAGD"]
    for r in sorted(geslaagd,key=lambda x:-x["maand_pct"])+sorted(gefaald,key=lambda x:-x["maand_pct"]):
        mark=" *** BESTE" if geslaagd and r==sorted(geslaagd,key=lambda x:-x["maand_pct"])[0] else ""
        doel=" DOEL!" if r["maand_pct"]>=5 else""
        print(f"  {r['label']:<28} EUR {r['pnl_eur']:>+8,.0f} {r['maand_pct']:>6.2f}% "
              f"{r['trades']:>7}  {r['wr']:>4.1f}% {r['pf']:>5.2f}  EUR {r['max_dd_eur']:>7,.0f}  {r['status']}{mark}{doel}")
    print("="*70)

    if geslaagd:
        beste=sorted(geslaagd,key=lambda x:-x["maand_pct"])[0]
        mnd=beste["mnd"]
        mnd_doel=(mnd["pct_mnd"]>=5).sum(); mnd_pos=(mnd["pnl_eur"]>0).sum(); mnd_tot=len(mnd)
        print(f"\n  BESTE: {beste['label']}")
        print(f"  WR: {beste['wr']:.1f}%  PF: {beste['pf']:.2f}  Gem/maand: {beste['maand_pct']:+.2f}%")
        print(f"  Positieve maanden: {mnd_pos}/{mnd_tot}  |  Maanden >=5%: {mnd_doel}/{mnd_tot}")
        print(f"  Beste maand: EUR {mnd['pnl_eur'].max():+,.0f} ({mnd['pct_mnd'].max():+.2f}%)")
        if beste["maand_pct"]>=5:
            print(f"\n  DOEL 5-8%/MAAND BEREIKT!")
        elif beste["maand_pct"]>=2:
            print(f"\n  {beste['maand_pct']:.2f}%/maand gemiddeld.")
            print(f"  Beste maanden bereiken {mnd['pct_mnd'].max():.1f}% - dichter bij doel!")
            print(f"  Om consistent 5%/maand te halen: meer signalen nodig in zwakke maanden.")
        else:
            print(f"\n  Strategie verbeterd maar 5%/maand doel nog niet bereikt.")
    print("="*70)

if __name__ == "__main__":
    main()
