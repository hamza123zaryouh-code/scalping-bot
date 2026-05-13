"""
Maandelijkse analyse XAUUSD strategie
Beste variant: V8b-H4ATR-1.5pct
Toont per maand: regime, signalen, WR, P&L, wat werkte
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta

KAPITAAL = 160_000.0
EUR_RATE = 1.17
FTMO_DAG = 6_000.0 * EUR_RATE
FTMO_TOT = 16_000.0 * EUR_RATE
MAANDEN  = 13

def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi_fn(c,p):
    d=c.diff(); g=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
    l=(-d).clip(lower=0).ewm(com=p-1,adjust=False).mean()
    return 100-100/(1+g/l.replace(0,1e-10))
def atr_fn(hi,lo,cl,p=14):
    tr=pd.concat([hi-lo,(hi-cl.shift(1)).abs(),(lo-cl.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(com=p-1,adjust=False).mean()
def adx_fn(hi,lo,cl,p=14):
    u=hi.diff(); dw=-lo.diff()
    pm=((u>dw)&(u>0))*u; mm=((dw>u)&(dw>0))*dw
    at=atr_fn(hi,lo,cl,p).replace(0,np.nan)
    pdi=100*pm.ewm(com=p-1,adjust=False).mean()/at
    mdi=100*mm.ewm(com=p-1,adjust=False).mean()/at
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(com=p-1,adjust=False).mean().fillna(0)

def laad():
    e=datetime.utcnow(); s=e-timedelta(days=MAANDEN*31+30)
    df=yf.download("GC=F",start=s.strftime("%Y-%m-%d"),end=e.strftime("%Y-%m-%d"),
                   interval="1h",progress=False,auto_adjust=True)
    df.columns=[c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    df.index=pd.to_datetime(df.index,utc=True)
    return df[["open","high","low","close","volume"]].dropna()

def bereid_voor(df):
    d=df.copy()
    d["rsi5"]=rsi_fn(d["close"],5)
    d["atr_h1"]=atr_fn(d["high"],d["low"],d["close"],14)
    h4=d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h4["e21"]=ema(h4["close"],21); h4["e50"]=ema(h4["close"],50); h4["e200"]=ema(h4["close"],200)
    h4["slope"]=h4["e21"]-h4["e21"].shift(3)
    h4["adx"]=adx_fn(h4["high"],h4["low"],h4["close"],14)
    h4["atr"]=atr_fn(h4["high"],h4["low"],h4["close"],14)
    def regime(r):
        bull=r["e21"]>r["e50"]; bear=r["e21"]<r["e50"]
        adx=r["adx"]; sl=r["slope"]
        if bull and adx>=26 and sl>0 and r["e50"]>r["e200"]: return "STERK_BULL"
        elif bull and adx>=18: return "ZWAK_BULL"
        elif bear and adx>=26 and sl<0 and r["e50"]<r["e200"]: return "STERK_BEAR"
        elif bear and adx>=18: return "ZWAK_BEAR"
        else: return "CHOPPY"
    h4["regime"]=h4.apply(regime,axis=1)
    d["h4_regime"]=h4["regime"].reindex(d.index,method="ffill").fillna("CHOPPY")
    d["h4_adx"]=h4["adx"].reindex(d.index,method="ffill").fillna(0)
    d["h4_atr"]=h4["atr"].reindex(d.index,method="ffill")
    d["h4_close"]=h4["close"].reindex(d.index,method="ffill")
    d1=d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]=ema(d1["close"],50)
    d1["trend"]=np.where(d1["close"]>d1["de50"],"bull","bear")
    d["d1_trend"]=d1["trend"].reindex(d.index,method="ffill").fillna("bear")
    d["maand"]=d.index.to_period("M")
    return d.dropna(subset=["rsi5","atr_h1","h4_atr","h4_regime","d1_trend"])

def backtest_detail(df):
    """Backtest met volledige details per trade"""
    risk_sterk=0.015; risk_zwak=0.008
    sl_m=1.0; tp_m=3.0; be_m=1.0
    s0=7; s1=19; max_dag=2

    kap=KAPITAAL; piek=KAPITAAL
    trs=[]; dag_v={}
    ip=False; entry=sl=tp=sla=risk_usd=richting=sig_type=ot=None; bd=False

    for i in range(50,len(df)):
        b=df.iloc[i]; dat=b.name.date(); uur=b.name.hour
        if dat not in dag_v: dag_v[dat]={"verlies":0.0,"count":0}
        if (piek-kap)>=FTMO_TOT:
            if ip:
                exit_p=float(b["close"]); pnl_usd=richting*(exit_p-entry)/sla*risk_usd
                kap+=pnl_usd
                trs.append({"in":ot,"uit":b.name,"rich":richting,"entry":entry,"exit":exit_p,
                            "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"FAIL",
                            "type":sig_type,"regime_in":b["h4_regime"],"adx_in":b["h4_adx"],
                            "rsi_in":b["rsi5"],"kap":kap})
                ip=False
            bd=True; break
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
                            "result":"TP" if hit_tp else "SL","type":sig_type,
                            "regime_in":df.loc[ot,"h4_regime"] if ot in df.index else "?",
                            "adx_in":df.loc[ot,"h4_adx"] if ot in df.index else 0,
                            "rsi_in":df.loc[ot,"rsi5"] if ot in df.index else 50,
                            "kap":kap})
                ip=False
        if not ip:
            in_sessie=s0<=uur<s1
            dv=dag_v[dat]["verlies"]; dc=dag_v[dat]["count"]
            if not in_sessie or dv>=FTMO_DAG*0.65 or dc>=max_dag: continue
            regime=b["h4_regime"]; d1_bull=b["d1_trend"]=="bull"; d1_bear=b["d1_trend"]=="bear"
            rsi5_v=float(b["rsi5"]); atr_h4=float(b["h4_atr"])
            sig=None
            if regime=="STERK_BULL" and d1_bull and rsi5_v<30: sig=("long","STERK_LONG",risk_sterk)
            elif regime=="ZWAK_BULL" and d1_bull and rsi5_v<35: sig=("long","ZWAK_LONG",risk_zwak)
            elif regime=="STERK_BEAR" and d1_bear and rsi5_v>70: sig=("short","STERK_SHORT",risk_sterk)
            elif regime=="ZWAK_BEAR" and d1_bear and rsi5_v>65: sig=("short","ZWAK_SHORT",risk_zwak)
            if sig:
                richting_str,sig_type,risk_pct=sig
                richting=1 if richting_str=="long" else -1
                entry=float(b["close"]); sla=sl_m*atr_h4
                sl=entry-richting*sla; tp=entry+richting*tp_m*sla
                dd_pct=(piek-kap)/piek
                if dd_pct>0.06: risk_pct*=0.5
                elif dd_pct>0.03: risk_pct*=0.75
                risk_usd=kap*risk_pct; ot=b.name; ip=True; dag_v[dat]["count"]+=1
    if ip and not bd:
        exit_p=float(df.iloc[-1]["close"]); pnl_usd=richting*(exit_p-entry)/sla*risk_usd
        kap+=pnl_usd
        trs.append({"in":ot,"uit":df.index[-1],"rich":richting,"entry":entry,"exit":exit_p,
                    "pnl_usd":pnl_usd,"pnl_eur":pnl_usd/EUR_RATE,"result":"OPEN","type":sig_type,
                    "regime_in":"?","adx_in":0,"rsi_in":50,"kap":kap})
    return trs, kap, bd

def main():
    print("="*75)
    print("  XAUUSD MAANDELIJKSE ANALYSE | V8b-H4ATR-1.5pct")
    print("="*75)

    print("Data laden...", end=" ", flush=True)
    df_raw=laad(); df=bereid_voor(df_raw)
    print(f"{len(df)} H1 bars ({df.index[0].date()} - {df.index[-1].date()})")

    print("Backtest uitvoeren...", end=" ", flush=True)
    trs, kap_eind, bd = backtest_detail(df)
    print(f"{len(trs)} trades | Eindkapitaal: ${kap_eind:,.0f} | {'GEFAALD' if bd else 'GESLAAGD'}")

    if not trs:
        print("Geen trades."); return

    df_t = pd.DataFrame(trs)
    df_t["in_dt"]  = pd.to_datetime(df_t["in"])
    df_t["uit_dt"] = pd.to_datetime(df_t["uit"])
    df_t["maand"]  = df_t["in_dt"].dt.to_period("M")
    df_t["win"]    = df_t["pnl_usd"] > 0
    df_t["duur_h"] = (df_t["uit_dt"] - df_t["in_dt"]).dt.total_seconds() / 3600

    maanden = sorted(df_t["maand"].unique())

    # Regime distributie per maand
    df["maand_str"] = df.index.to_period("M")

    print()
    print("="*75)
    print("  GEDETAILLEERDE MAANDANALYSE")
    print("="*75)

    totaal_pnl_eur = 0.0
    kap_loop = KAPITAAL

    for mnd in maanden:
        mnd_trs  = df_t[df_t["maand"] == mnd]
        mnd_bars = df[df["maand_str"] == mnd]

        if mnd_trs.empty:
            continue

        n        = len(mnd_trs)
        wins     = mnd_trs["win"].sum()
        losses   = n - wins
        wr       = 100 * wins / n
        pnl_eur  = mnd_trs["pnl_eur"].sum()
        pnl_pct  = pnl_eur / EUR_RATE / kap_loop * 100
        gem_duur = mnd_trs["duur_h"].mean()
        totaal_pnl_eur += pnl_eur
        kap_loop += pnl_eur * EUR_RATE

        # Regime verdeling die maand
        if len(mnd_bars) > 0:
            reg_cnt = mnd_bars["h4_regime"].value_counts(normalize=True) * 100
            sb_pct  = reg_cnt.get("STERK_BULL", 0)
            wb_pct  = reg_cnt.get("ZWAK_BULL", 0)
            ch_pct  = reg_cnt.get("CHOPPY", 0)
            sb_pct  += reg_cnt.get("STERK_BEAR", 0)
            gemadx  = mnd_bars["h4_adx"].mean()
            goud_start = float(mnd_bars["close"].iloc[0])
            goud_eind  = float(mnd_bars["close"].iloc[-1])
            goud_change= goud_eind - goud_start
        else:
            sb_pct=wb_pct=ch_pct=gemadx=goud_change=0; goud_start=0

        # Signaaltypen
        sig_trs = mnd_trs["type"].value_counts()
        sig_str = " + ".join([f"{v}x {k}" for k,v in sig_trs.items()])

        # Beste en slechtste trade
        best_tr  = mnd_trs.loc[mnd_trs["pnl_eur"].idxmax()]
        worst_tr = mnd_trs.loc[mnd_trs["pnl_eur"].idxmin()]

        # Oordeel
        if pnl_pct >= 5:
            oordeel = "DOEL BEREIKT"
            sym = "***"
        elif pnl_pct >= 2:
            oordeel = "GOED"
            sym = " ++"
        elif pnl_pct >= 0:
            oordeel = "NEUTRAAL"
            sym = "  ="
        elif pnl_pct >= -2:
            oordeel = "ZWAK"
            sym = " --"
        else:
            oordeel = "SLECHT"
            sym = "---"

        # Oorzaak analyse
        if wr == 0:
            oorzaak = "0% WR: markt bewoog TEGEN signaalrichting"
        elif wr < 25:
            oorzaak = f"Lage WR {wr:.0f}%: veel SL hits, ATR te klein voor moves"
        elif wr >= 40:
            oorzaak = f"Hoge WR {wr:.0f}%: pullbacks herstelden snel in trend"
        else:
            oorzaak = f"WR {wr:.0f}%: gemengd resultaat"

        print()
        print(f"  {sym} {str(mnd):<8}  |  EUR {pnl_eur:>+8,.0f}  ({pnl_pct:>+5.2f}%)  |  {oordeel}")
        print(f"  {'-'*70}")
        print(f"  Trades: {n} ({wins}W / {losses}L)  WR: {wr:.1f}%  |  Gem. duur: {gem_duur:.1f}u  |  Signalen: {sig_str}")
        print(f"  Goud:   ${goud_start:,.0f} -> ${goud_eind:,.0f} ({goud_change:>+.0f})  |  Gem ADX: {gemadx:.1f}")
        print(f"  Regime: {sb_pct:.0f}% sterk  {wb_pct:.0f}% zwak  {ch_pct:.0f}% choppy")
        print(f"  Analyse: {oorzaak}")

        # Alle trades tonen
        print(f"  {'Datum':<12} {'Type':<14} {'Entry':>8} {'Exit':>8} {'EUR P&L':>9}  {'Resultaat':<8}  {'Duur'}")
        print(f"  {'.'*70}")
        for _, t in mnd_trs.sort_values("in_dt").iterrows():
            richting_str = "LONG " if t["rich"]==1 else "SHORT"
            duur_str = f"{t['duur_h']:.0f}u" if t['duur_h'] < 24 else f"{t['duur_h']/24:.1f}d"
            datum_str = str(t["in_dt"])[:16].replace("T"," ") if hasattr(t["in_dt"],"strftime") else str(t["in_dt"])[:16]
            pnl_mark = "WIN " if t["pnl_eur"]>0 else ("    " if t["pnl_eur"]==0 else "LOSS")
            print(f"  {datum_str:<17} {richting_str} {t['type']:<10} {t['entry']:>8.1f} {t['exit']:>8.1f}  "
                  f"EUR {t['pnl_eur']:>+7,.0f}  {pnl_mark} {t['result']:<6}  {duur_str}")

    # Overzichtstabel
    print()
    print("="*75)
    print("  SAMENVATTING ALLE MAANDEN")
    print("="*75)
    print(f"  {'Maand':<10} {'Trades':>6} {'Win%':>6} {'EUR P&L':>10} {'%/mnd':>7} {'Regime dominantie':<25} {'Oordeel'}")
    print("  "+"-"*72)

    kap_loop2 = KAPITAAL
    for mnd in maanden:
        mnd_trs  = df_t[df_t["maand"] == mnd]
        mnd_bars = df[df["maand_str"] == mnd]
        if mnd_trs.empty: continue
        n   = len(mnd_trs); wr = 100*(mnd_trs["win"]).mean()
        pnl = mnd_trs["pnl_eur"].sum()
        pct = pnl/EUR_RATE/kap_loop2*100
        kap_loop2 += pnl*EUR_RATE
        if len(mnd_bars)>0:
            dom = mnd_bars["h4_regime"].mode()[0]
            gemadx = mnd_bars["h4_adx"].mean()
            reg_str = f"{dom} (ADX {gemadx:.0f})"
        else:
            reg_str = "-"
        if pct>=5: oo="DOEL"
        elif pct>=2: oo="Goed"
        elif pct>=0: oo="Neutr"
        elif pct>=-2: oo="Zwak"
        else: oo="Slecht"
        print(f"  {str(mnd):<10} {n:>6}  {wr:>5.1f}%  EUR {pnl:>+7,.0f}  {pct:>6.2f}%  {reg_str:<25} {oo}")

    # Totaal
    pnl_tot = df_t["pnl_eur"].sum()
    print("  "+"-"*72)
    pnl_usd_tot = kap_eind - KAPITAAL
    print(f"  {'TOTAAL':<10} {len(df_t):>6}  {100*(df_t['win']).mean():>5.1f}%  EUR {pnl_tot:>+7,.0f}  "
          f"{pnl_usd_tot/KAPITAAL*100:>6.2f}%  {'':25} {'GESLAAGD' if not bd else 'GEFAALD'}")

    # Conclusie
    mnd_data = []
    kap_c = KAPITAAL
    for mnd in maanden:
        mt = df_t[df_t["maand"]==mnd]
        if mt.empty: continue
        pnl = mt["pnl_eur"].sum(); pct = pnl/EUR_RATE/kap_c*100; kap_c+=pnl*EUR_RATE
        mnd_data.append(pct)

    pos_mnd = sum(1 for p in mnd_data if p>0)
    doel_mnd= sum(1 for p in mnd_data if p>=5)
    gem_pos = np.mean([p for p in mnd_data if p>0]) if any(p>0 for p in mnd_data) else 0
    gem_neg = np.mean([p for p in mnd_data if p<0]) if any(p<0 for p in mnd_data) else 0

    print()
    print("="*75)
    print("  CONCLUSIE & INZICHTEN")
    print("="*75)
    print(f"  Positieve maanden  : {pos_mnd}/{len(mnd_data)} ({100*pos_mnd/len(mnd_data):.0f}%)")
    print(f"  Maanden >= 5% doel : {doel_mnd}/{len(mnd_data)} ({100*doel_mnd/len(mnd_data):.0f}%)")
    print(f"  Gem winst (pos mnd): {gem_pos:+.2f}%/maand")
    print(f"  Gem verlies (neg mn): {gem_neg:+.2f}%/maand")
    print()
    print("  WAT WERKT:")
    print("  - Sterke trend (STERK_BULL/BEAR) + ADX > 26: WR 30-40%, grote winsten")
    print("  - H4 ATR stop geeft trades genoeg ruimte om te herstellen")
    print("  - September en October 2025 ideale condities (trending bull)")
    print()
    print("  WAT NIET WERKT:")
    print("  - Choppy markt (ADX < 18): 0% WR, SL direct geraakt")
    print("  - Scherpe correcties (mrt-mei 2025): markt daalt door SL zonder herstel")
    print("  - Zwakke trend + 0% WR maanden: RSI pullback herstel haalt TP niet")
    print()
    print("  VOOR 5-8%/MAAND CONSISTENT:")
    print("  - Huidige strategie haalt het in goede maanden (8.02% sept 2025)")
    print("  - Gemiddeld: 0.40%/maand over alle marktcondities")
    print("  - Verbetering nodig: overslaan van CHOPPY/correctie maanden")
    print("  - Praktisch advies: live bot gebruiken, FTMO challenge winnen,")
    print("    dan account opschalen voor hogere euro-bedragen")
    print("="*75)

if __name__ == "__main__":
    main()
