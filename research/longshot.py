"""Favorite / longshot calibration by category, side and price (research only, exploratory; added 2026-10-22, platform
upgrade phase 6). Uses the Kalshi trade lists already downloaded for PLAN4 test K1. Run it only after K1 has been
scored once, so this look cannot touch that test.

Question: are cheap YES contracts overpriced, and is the bias stronger in some categories, on one side or at some
prices? For every taker fill:
- the price paid for the taker's side, and whether that side won;
- excess = win - price, before and after the taker fee.
Fills are grouped by category (sports, crypto, weather, other: from the series ticker), side (YES or NO) and the tenth
of the price paid. Each group reports:
- fills, mean price, win rate with its 95% Wilson interval;
- the mean excess, with an SE clustered by market date.
This is exploratory and cannot pass or fail. A pattern seen here earns only a pre-registered forward test on later
markets (CLAUDE.md 11a). It is never a rule such as "always buy NO under 30c".
  python research/longshot.py report   -> results/longshot.md and .json
Python 3.8+, no network."""
import os, sys, json, re
from datetime import datetime
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.stats import wilson, cl_mean_se
from tbcommon import clock   # result stamps with their UTC offset (2026-10-23)
import fees
D_K=os.path.join(HERE,"data","k1"); OUT=os.path.join(HERE,"results")
def category(series):
    s=series.upper()
    if re.search(r"BTC|ETH|SOL|XRP|DOGE|HYPE|CRYPTO",s): return "crypto"
    if re.search(r"GOLD|SILVER|WTI|NATGAS|COPPER|PLATINUM|PALLADIUM|USD|EUR|GBP|JPY|AUD|CAD|RATE|SPX|NASDAQ|INX",s): return "markets"
    if re.search(r"RAIN|HIGH|LOW|TEMP|SNOW|HURR",s): return "weather"
    if re.search(r"MLB|NFL|NCAA|NBA|WNBA|NHL|ATP|WTA|ITF|PGA|UFC|EPL|LALIGA|UEFA|MLS|LIGAMX|CS2|T20|SERIEA|BUNDES",s): return "sports"
    return "other"
def fee1(p): return fees.taker(p)   # taker fee for one contract, rounded up to the cent
def kdate(t):
    m=re.search(r"-(\d{2}[A-Z]{3}\d{2})",t or "")
    try: return datetime.strptime(m.group(1),"%y%b%d").date().isoformat() if m else "unknown"
    except ValueError: return "unknown"
def rows(markets,trades_of):
    """Yields (category, side, price, won, date) for every taker fill with a price and a settled market."""
    for t,mk in markets.items():
        y=mk.get("result")
        if y not in ("yes","no"): continue
        cat=category(mk.get("series") or t.split("-")[0])
        for r in trades_of(t):
            side=r.get("side"); p=r.get("yes") if side=="yes" else r.get("no")
            if side not in ("yes","no") or p is None or not 0<p<1 or r.get("block"): continue
            yield cat,side,p,1 if side==y else 0,kdate(mk.get("event") or t)
def summarize(it):
    g={}
    for cat,side,p,w,d in it:
        b=min(9,int(p*10))
        for key in ((cat,side,b),("all",side,b)): g.setdefault(key,[]).append((p,w,d))
    out=[]
    for (cat,side,b),v in sorted(g.items()):
        n=len(v); k=sum(w for _,w,_ in v); lo,hi=wilson(k,n)
        m,se=cl_mean_se([(w-p,d) for p,w,d in v]); mf,sef=cl_mean_se([(w-p-fee1(p),d) for p,w,d in v])
        out.append(dict(category=cat,side=side,tenth=b,fills=n,mean_price=sum(p for p,_,_ in v)/n,win_rate=k/n,win_lo=lo,win_hi=hi,
                        excess=m,se=se,excess_after_fee=mf,se_after_fee=sef,dates=len({d for _,_,d in v})))
    return out
def report():
    if not os.path.exists(os.path.join(OUT,"plan4_K.json")): sys.exit("Run after PLAN4 test K1 is scored (research/plan4.py scoreK), so this look cannot affect it.")
    ms=json.load(open(os.path.join(D_K,"markets.json"),encoding="utf-8"))
    def tr(t):
        p=os.path.join(D_K,"trades2",t+".json")
        return json.load(open(p,encoding="utf-8")) if os.path.exists(p) else []
    S=summarize(rows(ms,tr))
    json.dump(dict(made=clock.iso(seconds=False),groups=S),open(os.path.join(OUT,"longshot.json"),"w"))
    pc=lambda x:"n/a" if x is None else "%+.1fc"%(100*x)
    L=["# Favorite / longshot calibration (exploratory; K1's Kalshi trades)","",
       "Excess = win rate minus price paid: negative means that side was overpriced. SE clustered by market date. Exploratory only: a pattern here earns only a pre-registered forward test.","",
       "| Category | Side | Price | Fills | Dates | Win rate (95%) | Excess | After fee |","|---|---|---|---|---|---|---|---|"]
    for r in S:
        if r["fills"]<200: continue
        L.append("| %s | %s | %d-%dc | %d | %d | %.1f%% (%.1f-%.1f) | %s +/- %s | %s |"%(r["category"],r["side"].upper(),r["tenth"]*10,r["tenth"]*10+10,r["fills"],r["dates"],
                 100*r["win_rate"],100*r["win_lo"],100*r["win_hi"],pc(r["excess"]),"n/a" if r["se"] is None else "%.1fc"%(100*r["se"]),pc(r["excess_after_fee"])))
    open(os.path.join(OUT,"longshot.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L[:40]))
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="report": report()
    else: sys.exit(__doc__)
