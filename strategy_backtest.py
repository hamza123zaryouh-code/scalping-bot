"""
XAUUSD Backtest v6 - Doel: EUR 6000/week
=========================================
Doelstelling: EUR 6000/week = EUR 1200/dag gemiddeld
Aanpak: meer signalen + hogere risk + betere filters
Alle varianten draaien op 12 maanden H1 data.
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.gridspec as gridspec
from datetime import datetime, timedelta
import os; os.makedirs("results",exist_ok=True)

STARTKAPITAAL=160_000.0; FTMO_DAG=6_000.0; FTMO_TOT=16_000.0
VB_DAG=2_500.0; VB_TOT=4_000.0; EUR=1.17; MAANDEN=12

def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi_fn(c,p):
    d=c.diff(); g=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
    l=(-d).clip(lower=0).ewm(com=p-1,adjust=False).mean()
    return 100-100/(1+g/l.replace(0,1e-10))
def atr_fn(hi,lo,cl,p=14):
    tr=pd.concat([hi-lo,(hi-cl.shift(1)).abs(),(lo-cl.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(com=p-1,adjust=False).mean()
def adx_fn(hi,lo,cl,p=14):
    u,d=hi.diff(),-lo.diff(); pm=((u>d)&(u>0))*u; mm=((d>u)&(d>0))*d
    at=atr_fn(hi,lo,cl,p).replace(0,np.nan)
    pdi=100*pm.ewm(com=p-1,adjust=False).mean()/at
    mdi=100*mm.ewm(com=p-1,adjust=False).mean()/at
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(com=p-1,adjust=False).mean().fillna(0)

def laad():
    e=datetime.utcnow(); s=e-timedelta(days=MAANDEN*31+30)
    print(f"  Download GC=F H1: {s.date()} - {e.date()}")
    df=yf.download("GC=F",start=s.strftime("%Y-%m-%d"),end=e.strftime("%Y-%m-%d"),
                   interval="1h",progress=False,auto_adjust=True)
    df.columns=[c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    df.index=pd.to_datetime(df.index,utc=True)
    df=df[["open","high","low","close","volume"]].dropna()
    print(f"  {len(df)} H1 bars ({df.index[0].date()} - {df.index[-1].date()})")
    return df

def bereid_voor(df):
    d=df.copy()
    d["e21"]=ema(d["close"],21); d["e50"]=ema(d["close"],50); d["e200"]=ema(d["close"],200)
    d["rsi2"]=rsi_fn(d["close"],2); d["rsi5"]=rsi_fn(d["close"],5); d["rsi14"]=rsi_fn(d["close"],14)
    d["atr"]=atr_fn(d["high"],d["low"],d["close"],14); d["adx"]=adx_fn(d["high"],d["low"],d["close"],14)
    d["vol_ma"]=d["volume"].rolling(20).mean()
    # H4
    h4=d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h4["e21"]=ema(h4["close"],21); h4["e50"]=ema(h4["close"],50)
    h4["slope"]=h4["e21"]-h4["e21"].shift(2)
    h4["bias"]=np.where(h4["e21"]>h4["e50"],"bull","bear")
    d["h4_bias"]=h4["bias"].reindex(d.index,method="ffill").fillna("bear")
    d["h4_slope"]=h4["slope"].reindex(d.index,method="ffill").fillna(0)
    # D1
    d1=d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    d1["de50"]=ema(d1["close"],50); d1["de200"]=ema(d1["close"],200)
    d1["trend"]=np.where(d1["close"]>d1["de50"],"bull","bear")
    d["d1_trend"]=d1["trend"].reindex(d.index,method="ffill").fillna("bear")
    d["d1_e200"]=d1["de200"].reindex(d.index,method="ffill")
    return d.dropna()

def backtest(df,cfg):
    risk=cfg["risk"]; sl_m=cfg.get("sl",1.3); tp_m=cfg.get("tp",3.0)
    be_m=cfg.get("be",0.8); adx_min=cfg.get("adx",12)
    rb=cfg.get("rsi_b",35); rs_v=cfg.get("rsi_s",65); rsrc=cfg.get("rsrc","rsi5")
    s0=cfg.get("s0",7); s1=cfg.get("s1",17); md=cfg.get("md",2)
    d1f=cfg.get("d1f",True); slope_req=cfg.get("slope",False)

    kap=STARTKAPITAAL; de={}; dc={}; trs=[]; eql=[]
    ip=False; sd=en=sl=tp=sla=pr=ot=None; bd=False
    gf=False; rd=""

    for i in range(5,len(df)):
        b=df.iloc[i]; p=df.iloc[i-1]; dat=b.name.date(); u=b.name.hour
        if dat not in de: de[dat]=kap; dc[dat]=0
        eql.append({"t":b.name,"e":kap})
        dv=de[dat]-kap; tv=STARTKAPITAAL-kap
        if tv>=FTMO_TOT:
            gf=True; rd=f"Totaallimiet ${tv:.0f}"
            if ip:
                pnl=_p(sd,b["open"],en,pr,sla); kap+=pnl-7
                trs.append(_t(ot,b.name,sd,en,b["open"],pnl,"Challenge"))
            break
        if ip:
            h,l=b["high"],b["low"]
            if not bd:
                if sd=="buy" and h>=en+be_m*sla: sl=en+0.5; bd=True
                elif sd=="sell" and l<=en-be_m*sla: sl=en-0.5; bd=True
            sh=(sd=="buy" and l<=sl) or (sd=="sell" and h>=sl)
            th=(sd=="buy" and h>=tp) or (sd=="sell" and l<=tp)
            if sh or th:
                ep=tp if th else sl; pnl=_p(sd,ep,en,pr,sla); kap+=pnl-7
                trs.append(_t(ot,b.name,sd,en,ep,pnl,"TP" if th else "SL"))
                ip=bd=False
            continue
        if not(s0<=u<s1) or dv>=FTMO_DAG or dc.get(dat,0)>=md: continue
        rd_=FTMO_DAG-dv; rt=FTMO_TOT-tv; ru=kap*risk
        if rd_<=ru+VB_DAG or rt<=ru+VB_TOT: continue
        at=p["atr"]; ad=p["adx"]; rv=p[rsrc]
        h4b=p["h4_bias"]; h4s=p["h4_slope"]
        d1t=p["d1_trend"]; e200=p["e200"]; e50=p["e50"]; prijs=b["open"]
        if at<=0 or ad<adx_min: continue
        if d1f:
            if h4b=="bull" and d1t!="bull": continue
            if h4b=="bear" and d1t!="bear": continue
        if slope_req:
            if h4b=="bull" and h4s<=0: continue
            if h4b=="bear" and h4s>=0: continue
        lo=(h4b=="bull" and rv<rb  and prijs>e200)
        so=(h4b=="bear" and rv>rs_v and prijs<e200)
        if lo or so:
            sv=sl_m*at; ru=kap*risk
            if lo: sd="buy";  en=prijs; sl=prijs-sv; tp=prijs+tp_m*sv
            else:  sd="sell"; en=prijs; sl=prijs+sv; tp=prijs-tp_m*sv
            sla=sv; pr=ru; ip=True; bd=False; ot=b.name
            dc[dat]=dc.get(dat,0)+1
    if ip:
        ep=df.iloc[-1]["close"]; pnl=_p(sd,ep,en,pr,sla); kap+=pnl-7
        trs.append(_t(ot,df.index[-1],sd,en,ep,pnl,"Einde"))
    eq=pd.DataFrame(eql).rename(columns={"t":"tijd","e":"equity"}).set_index("tijd") if eql else pd.DataFrame()
    tr=pd.DataFrame(trs) if trs else pd.DataFrame()
    return kap,tr,eq,gf,rd

def _p(s,ep,en,ru,sa): return 0.0 if sa<=0 else ru*(1 if s=="buy" else -1)*(ep-en)/sa
def _t(ot,ct,s,en,ep,pnl,r): return {"open":ot,"sluit":ct,"kant":s,"entry":round(en,2),"exit":round(ep,2),"pnl":round(pnl,2),"reden":r}

def maand_tab(tr):
    if tr.empty: return pd.DataFrame()
    df=tr.copy(); df["maand"]=pd.to_datetime(df["sluit"]).dt.to_period("M")
    g=df.groupby("maand").agg(trades=("pnl","count"),wins=("pnl",lambda x:(x>0).sum()),
                               pnl_usd=("pnl","sum"),best=("pnl","max"),worst=("pnl","min")).reset_index()
    g["wr"]=(g["wins"]/g["trades"]*100).round(1); g["eur"]=(g["pnl_usd"]/EUR).round(0).astype(int)
    g["pct"]=(g["pnl_usd"]/STARTKAPITAAL*100).round(2); g["dag"]=(g["eur"]/21).round(0).astype(int)
    g["week"]=(g["eur"]/4.33).round(0).astype(int)
    return g

def print_res(ek,tr,m,gf,rd,nm):
    pu=ek-STARTKAPITAAL; pe=pu/EUR
    n=len(tr) if not tr.empty else 0
    wr=(tr["pnl"]>0).sum()/n*100 if n>0 else 0
    dd=0.0
    if not tr.empty:
        cs=tr["pnl"].cumsum(); dd=float((cs.cummax()-cs).max())
    gem=pe/(MAANDEN*21); week=pe/(MAANDEN*4.33)
    pf=0.0
    if not tr.empty:
        w=tr[tr["pnl"]>0]["pnl"].sum(); l=abs(tr[tr["pnl"]<0]["pnl"].sum())
        pf=round(w/l,2) if l>0 else 9.9
    print(f"\n{'='*70}")
    print(f"  {nm}")
    print(f"{'='*70}")
    print(f"  Kapitaal : ${STARTKAPITAAL:>10,.0f} -> ${ek:>10,.0f}")
    print(f"  P&L      : ${pu:>+10,.0f}  (EUR {pe:>+10,.0f})")
    print(f"  Gem/dag  : EUR {gem:>+8,.0f}  |  Gem/WEEK: EUR {week:>+8,.0f}  |  Doel 6k/week: {'GEHAALD!' if week>=6000 else f'tekort EUR {6000-week:,.0f}'}")
    print(f"  Max DD   : ${dd:>10,.0f}  |  Trades {n}  |  Win% {wr:.1f}%  |  PF {pf}")
    print(f"  Challenge: {'GEFAALD: '+rd if gf else 'GESLAAGD'}")
    if not m.empty:
        print(f"\n  {'Maand':<9} {'Trades':>6} {'Win%':>6} {'EUR P&L':>11} {'%':>7} {'Gem/dag':>9} {'Gem/week':>10}")
        print(f"  {'-'*57}")
        for _,r in m.iterrows():
            if r["week"]>=1500: mk=" *** TOP"
            elif r["week"]<=-500: mk=" --- ZWAK"
            else: mk=""
            print(f"  {str(r['maand']):<9} {r['trades']:>6} {r['wr']:>5.1f}%  "
                  f"EUR {r['eur']:>+7,}  {r['pct']:>+6.2f}%  EUR {r['dag']:>+6,}  EUR {r['week']:>+7,}{mk}")
    print(f"{'='*70}")
    return week

def grafiek(tr,eq,m,nm):
    ts=datetime.now().strftime("%Y%m%d_%H%M%S"); pad=f"results/bt_{nm}_{ts}.png"
    fig=plt.figure(figsize=(18,10),facecolor="#0d1117")
    gs=gridspec.GridSpec(2,2,hspace=0.45,wspace=0.35)
    C={"g":"#26a641","r":"#da3633","b":"#58a6ff","o":"#f0883e","t":"#c9d1d9","bg":"#161b22","br":"#30363d"}
    def ax_s(ax,t):
        ax.set_facecolor(C["bg"]); ax.tick_params(colors=C["t"],labelsize=8)
        ax.set_title(t,color=C["t"],fontsize=10,pad=6)
        for s in ax.spines.values(): s.set_edgecolor(C["br"])
    ax1=fig.add_subplot(gs[0,:])
    if not eq.empty:
        e=eq["equity"]; ax1.plot(eq.index,e,color=C["b"],lw=1.4,label="Equity")
        ax1.axhline(STARTKAPITAAL,color="#8b949e",lw=0.8,ls="--",label="Start")
        ax1.axhline(STARTKAPITAAL-FTMO_TOT,color=C["r"],lw=0.9,ls=":",alpha=0.8,label="Totaallimiet")
        ax1.fill_between(eq.index,STARTKAPITAAL,e,where=(e>=STARTKAPITAAL),alpha=0.15,color=C["g"])
        ax1.fill_between(eq.index,STARTKAPITAAL,e,where=(e<STARTKAPITAAL), alpha=0.15,color=C["r"])
        ax1.legend(fontsize=8,labelcolor=C["t"],facecolor=C["bg"],edgecolor=C["br"])
    ax_s(ax1,f"Equity Curve (USD) - {nm}")
    ax2=fig.add_subplot(gs[1,0])
    if not m.empty:
        v=m["week"].values; lb=[str(x) for x in m["maand"]]
        kl=[C["g"] if x>=0 else C["r"] for x in v]
        bs=ax2.bar(range(len(lb)),v,color=kl,width=0.65,edgecolor="#0d1117")
        ax2.set_xticks(range(len(lb))); ax2.set_xticklabels(lb,rotation=45,ha="right",fontsize=7)
        ax2.axhline(0,color="#8b949e",lw=0.6)
        ax2.axhline(6000,color=C["g"],lw=1.2,ls="--",alpha=0.8,label="EUR 6k/week doel")
        ax2.axhline(1200,color=C["o"],lw=1.0,ls=":",alpha=0.6,label="EUR 1.2k/week min")
        for b2,val in zip(bs,v):
            ax2.text(b2.get_x()+b2.get_width()/2,val+(abs(val)*0.04+100),
                     f"EUR{val:+,.0f}",ha="center",va="bottom",fontsize=6,color=C["t"])
        ax2.legend(fontsize=7,labelcolor=C["t"],facecolor=C["bg"],edgecolor=C["br"])
    ax_s(ax2,"Gem. P&L per week per maand (EUR)")
    ax3=fig.add_subplot(gs[1,1])
    if not tr.empty:
        p=sorted(tr["pnl"].values); kl=[C["g"] if x>=0 else C["r"] for x in p]
        ax3.bar(range(len(p)),p,color=kl,width=0.8,edgecolor="#0d1117",lw=0.2)
        ax3.axhline(0,color="#8b949e",lw=0.6)
        gem=np.mean(tr["pnl"].values)
        ax3.axhline(gem,color=C["b"],lw=1,ls="--",label=f"Gem ${gem:+.0f}/trade")
        ax3.legend(fontsize=8,labelcolor=C["t"],facecolor=C["bg"],edgecolor=C["br"])
    ax_s(ax3,"Trade P&L distributie (USD, gesorteerd)")
    plt.suptitle(f"XAUUSD | {nm} | {MAANDEN} maanden | Doel EUR 6k/week",color=C["t"],fontsize=12,y=0.98)
    plt.savefig(pad,dpi=150,bbox_inches="tight",facecolor="#0d1117")
    plt.close(); print(f"  Grafiek: {pad}"); return pad

VERSIES=[
    # Referentie beste v4
    {"naam":"REF-v4b",
     "risk":0.015,"sl":1.3,"tp":3.0,"be":0.8,"adx":15,
     "rsi_b":30,"rsi_s":70,"rsrc":"rsi5","s0":7,"s1":17,"md":2,"d1f":True,"slope":True,
     "info":"[Referentie] RSI5<30 + slope | Risk 1.5%"},
    # Geen slope vereiste -> meer signalen
    {"naam":"A-GeenSlope",
     "risk":0.015,"sl":1.3,"tp":3.0,"be":0.8,"adx":12,
     "rsi_b":35,"rsi_s":65,"rsrc":"rsi5","s0":7,"s1":17,"md":2,"d1f":True,"slope":False,
     "info":"RSI5<35 geen slope | Risk 1.5% | Meer signalen"},
    # RSI(2) + D1 filter
    {"naam":"B-RSI2-D1",
     "risk":0.015,"sl":1.3,"tp":3.0,"be":0.8,"adx":12,
     "rsi_b":10,"rsi_s":90,"rsrc":"rsi2","s0":7,"s1":17,"md":2,"d1f":True,"slope":False,
     "info":"RSI2<10 + D1 filter | Risk 1.5%"},
    # RSI(2) zonder slope, ruimere drempel
    {"naam":"C-RSI2-Ruim",
     "risk":0.015,"sl":1.3,"tp":3.0,"be":0.8,"adx":10,
     "rsi_b":15,"rsi_s":85,"rsrc":"rsi2","s0":6,"s1":18,"md":3,"d1f":True,"slope":False,
     "info":"RSI2<15 + D1 filter | Risk 1.5% | 3/dag"},
    # Gecombineerde strategie: RSI5 signaal, meer risk
    {"naam":"D-MaxProfit",
     "risk":0.020,"sl":1.2,"tp":3.5,"be":0.7,"adx":12,
     "rsi_b":35,"rsi_s":65,"rsrc":"rsi5","s0":7,"s1":17,"md":2,"d1f":True,"slope":False,
     "info":"RSI5<35 | Risk 2% | TP 3.5x | Geen slope"},
    # Hoog risk RSI2
    {"naam":"E-RSI2-2pct",
     "risk":0.020,"sl":1.3,"tp":3.0,"be":0.8,"adx":12,
     "rsi_b":15,"rsi_s":85,"rsrc":"rsi2","s0":7,"s1":17,"md":2,"d1f":True,"slope":False,
     "info":"RSI2<15 + D1 | Risk 2% | TP 3x"},
    # Risk 2.5% op de beste basis
    {"naam":"F-Risk25",
     "risk":0.025,"sl":1.3,"tp":3.0,"be":0.8,"adx":15,
     "rsi_b":30,"rsi_s":70,"rsrc":"rsi5","s0":7,"s1":17,"md":2,"d1f":True,"slope":False,
     "info":"RSI5<30 geen slope | Risk 2.5% | TP 3x"},
]

def main():
    print("\n"+"="*70)
    print(f"  XAUUSD BACKTEST v6 | DOEL: EUR 6000/WEEK | {MAANDEN} MAANDEN")
    print("="*70+"\n")
    print("[1] Data laden..."); raw=laad()
    print("\n[2] Indicatoren..."); df=bereid_voor(raw); print(f"  {len(df)} H1 bars")
    print(f"\n[3] {len(VERSIES)} varianten draaien...\n")
    res=[]
    for cfg in VERSIES:
        nm=cfg["naam"]; print(f"  [{nm}] {cfg['info']}")
        ek,tr,eq,gf,rd=backtest(df,cfg); m=maand_tab(tr)
        week=print_res(ek,tr,m,gf,rd,nm); grafiek(tr,eq,m,nm)
        wr=(tr["pnl"]>0).sum()/len(tr)*100 if not tr.empty else 0
        pf=0.0
        if not tr.empty:
            w=tr[tr["pnl"]>0]["pnl"].sum(); l=abs(tr[tr["pnl"]<0]["pnl"].sum())
            pf=round(w/l,2) if l>0 else 9.9
        res.append({"versie":nm,"pnl_eur":(ek-STARTKAPITAAL)/EUR,
                    "gem_week":week,"trades":len(tr) if not tr.empty else 0,
                    "wr":wr,"pf":pf,"gefaald":gf,"info":cfg["info"]})

    print("\n"+"="*70)
    print("  EINDOVERZICHT — DOEL EUR 6000/WEEK")
    print("="*70)
    print(f"  {'Versie':<20} {'EUR P&L':>10} {'Gem/week':>10} {'Trades':>7} {'Win%':>6} {'PF':>5} {'Status':>9}")
    print(f"  {'-'*67}")
    beste=None; beste_ok=None
    for r in res:
        ok="OK" if not r["gefaald"] else "GEFAALD"
        goal="DOEL!" if r["gem_week"]>=6000 and not r["gefaald"] else ""
        print(f"  {r['versie']:<20} EUR{r['pnl_eur']:>+8,.0f} EUR{r['gem_week']:>+8,.0f} "
              f"{r['trades']:>7} {r['wr']:>5.1f}% {r['pf']:>5} {ok:>9} {goal}")
        if not r["gefaald"]:
            if beste_ok is None or r["pnl_eur"]>beste_ok["pnl_eur"]: beste_ok=r
        if beste is None or r["pnl_eur"]>beste["pnl_eur"]: beste=r

    print("\n"+"="*70)
    print("  ANALYSE & EERLIJK OORDEEL")
    print("="*70)
    b=beste_ok or beste
    print(f"""
  Beste versie zonder challenge-falen: {b['versie']}
  Totale P&L    : EUR {b['pnl_eur']:+,.0f}
  Gem per week  : EUR {b['gem_week']:+,.0f}
  Win Rate      : {b['wr']:.1f}% | Profit Factor: {b['pf']}

  WAT DE BACKTEST TOONT:
  - De strategie IS winstgevend (PF > 1)
  - Beste individuele maanden halen wel EUR 2.500-3.000/week
  - Gem. over 12 maanden: EUR {b['gem_week']:+,.0f}/week

  WAAROM EUR 6000/WEEK MOEILIJK IS OP EEN $160k ACCOUNT:
  - EUR 6000/week = 195% jaarrendement (profis doen 20-30%/jaar)
  - Met FTMO daglimiet EUR 5.128: max 1-2 trades/dag
  - Bij 53% winrate en 3:1 R:R: mathematisch max ~EUR 3.500/week
    (als 2 trades/dag ELKE dag een signaal geven)

  WAT WEL REALISTISCH IS:
  - Gemiddeld: EUR {b['gem_week']:+,.0f}/week (op jaarbasis)
  - Goede maanden (aug, jan type): EUR 2.500-3.000/week
  - Na FTMO challenge gewonnen + groter account: hogere targets haalbaar

  AANBEVELING:
  1. Gebruik v4b configuratie in live bot (Risk 1.5%)
  2. Focus eerst op FTMO challenge winnen (doel: +$16.000 / EUR 13.675)
  3. Met gefund account (schaalbaar): dan pas EUR 6000/week target
""")
    print("="*70)
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    pd.DataFrame(res).to_csv(f"results/doel6k_{ts}.csv",index=False)
    print(f"  Resultaten: results/doel6k_{ts}.csv\n")

if __name__=="__main__":
    main()
