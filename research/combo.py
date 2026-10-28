"""Combos (multivariate markets): correlation-aware pricing research (research only, exploratory; added 2026-10-22,
platform upgrade phase 10). It places no orders, and nothing here is a rule.

A combo pays if every leg wins. Multiplying the legs' prices assumes the legs are independent, which is wrong when
they share a cause (the same game, team or weather). This module never does only that. For each open combo with
readable legs it records:
- **the independence price:** the product of the legs' mid prices (each leg's chance for the side it needs);
- **the combo's own mid;**
- **the implied correlation:** the equicorrelation rho of a one-factor Gaussian copula that makes the legs' joint
  chance equal the combo's mid. Kalshi's price then says how strongly the legs move together. Above 0 means the market
  prices positive dependence; a price below the independence price implies negative dependence.
Snapshots go to research/data/combo/snapshots.jsonl. Once enough of those combos have settled, `report` compares,
over settled combos, the Brier score of the combo's mid, of the independence price and of the copula price at a
correlation fitted on earlier combos only. That says whether combos are mispriced and in which direction. Exploratory
until a pre-registered forward test.

  python research/combo.py snapshot [--max 300]   open combos and their legs' quotes
  python research/combo.py settle                 outcomes of snapshotted combos that have closed
  python research/combo.py report                 -> research/results/combo.md
Read-only Kalshi public GETs (same domain and User-Agent as kalshi.py). Python 3.8+, needs requests (not for report)."""
import os, sys, json, time, math
from statistics import NormalDist
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import px
from tbcommon.jsonio import lines
DATA=os.path.join(HERE,"data","combo"); OUT=os.path.join(HERE,"results")
N=NormalDist()
CLIENT=JsonClient(KALSHI_PUBLIC,tries=5,timeout=30,min_gap=0.125,backoff_base=3.0,backoff_cap=60.0)
def http(path,params=None,tries=5): return CLIENT.get(path,params,tries=tries)
def mid(m):
    b,a=px(m,"yes_bid"),px(m,"yes_ask")
    return (a+b)/2 if (a is not None and b is not None and 0<b<a<1) else None
# ---------------- the copula ----------------
def joint(ps,rho,steps=400):
    """P(all legs win) when leg i wins with chance ps[i] and the legs share one Gaussian factor with correlation rho
    (0 <= rho < 1): the integral over z of phi(z) x product of Phi((Phi^-1(p_i) + sqrt(rho) z) / sqrt(1 - rho))."""
    ps=[min(max(p,1e-9),1-1e-9) for p in ps]
    if rho<=1e-12: return math.prod(ps)
    a=[N.inv_cdf(p) for p in ps]; s=math.sqrt(rho); d=math.sqrt(1-rho); lo,hi=-8.0,8.0; h=(hi-lo)/steps; tot=0.0
    for i in range(steps+1):
        z=lo+i*h; w=0.5 if i in (0,steps) else 1.0
        tot+=w*N.pdf(z)*math.prod(N.cdf((x+s*z)/d) for x in a)
    return tot*h
def implied_rho(ps,price,tol=1e-4):
    """The rho in [0, 0.99] at which joint(ps, rho) equals price; None if the price is outside that range (a price
    below the independence price implies negative dependence, which this one-factor model does not cover)."""
    lo,hi=0.0,0.99
    if not (joint(ps,lo)-1e-9<=price<=joint(ps,hi)+1e-9): return None
    while hi-lo>tol:
        m=(lo+hi)/2
        if joint(ps,m)<price: lo=m
        else: hi=m
    return (lo+hi)/2
def leg_chance(leg,m):
    p=mid(m) if m else None
    if p is None: return None
    return p if (leg.get("side") or "yes").lower()=="yes" else 1-p
# ---------------- steps ----------------
def snapshot(maximum=300,now=None):
    now=now or time.time(); combos=[]; cur=None
    for _ in range(50):
        p=dict(status="open",limit=1000,mve_filter="only")
        if cur: p["cursor"]=cur
        j=http("/markets",p); combos+=[m for m in (j.get("markets") or []) if mid(m) is not None and m.get("mve_selected_legs")]; cur=j.get("cursor")
        if not cur or len(combos)>=maximum: break
    combos=combos[:maximum]; legs=sorted({l.get("market_ticker") for m in combos for l in m["mve_selected_legs"] if l.get("market_ticker")})
    got={}
    for i in range(0,len(legs),50):
        for m in (http("/markets",dict(tickers=",".join(legs[i:i+50]))).get("markets") or []): got[m["ticker"]]=m
    rows=[]
    for m in combos:
        ps=[leg_chance(l,got.get(l.get("market_ticker"))) for l in m["mve_selected_legs"]]
        if not ps or any(p is None for p in ps): continue
        cm=mid(m); ind=math.prod(ps)
        rows.append(dict(ts=now,ticker=m["ticker"],collection=m.get("mve_collection_ticker"),close=m.get("close_time"),legs=len(ps),ps=[round(p,4) for p in ps],
                         mid=cm,spread=px(m,"yes_ask")-px(m,"yes_bid"),independent=round(ind,6),rho=implied_rho(ps,cm),
                         events=len({l.get("event_ticker") for l in m["mve_selected_legs"]})))
    os.makedirs(DATA,exist_ok=True)
    with open(os.path.join(DATA,"snapshots.jsonl"),"a",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r)+"\n")
    print("combo snapshot: %d combos with readable legs (of %d listed)"%(len(rows),len(combos))); return rows
def settle(now=None):
    p=os.path.join(DATA,"results.json"); res=json.load(open(p)) if os.path.exists(p) else {}
    todo=sorted({r["ticker"] for r in lines(os.path.join(DATA,"snapshots.jsonl")) if r["ticker"] not in res})
    single=0
    for i in range(0,len(todo),50):
        got={m["ticker"]:m for m in (http("/markets",dict(tickers=",".join(todo[i:i+50]))).get("markets") or [])}
        for t in todo[i:i+50]:
            m=got.get(t)
            if m is None and single<200:   # the batch call may not return settled markets (CLAUDE.md section 8)
                single+=1
                try: m=http("/markets/"+t).get("market")
                except RuntimeError: m=None
            r=((m or {}).get("result") or "").lower()
            if r in ("yes","no"): res[t]=r
    os.makedirs(DATA,exist_ok=True); json.dump(res,open(p,"w")); print("combo settle: %d results"%len(res)); return res
def report():
    snaps=lines(os.path.join(DATA,"snapshots.jsonl")); res=json.load(open(os.path.join(DATA,"results.json"))) if os.path.exists(os.path.join(DATA,"results.json")) else {}
    first={}
    for r in sorted(snaps,key=lambda r:r["ts"]):
        first.setdefault(r["ticker"],r)   # each combo once: its first snapshot
    rows=sorted(first.values(),key=lambda r:r["ts"]); rh=[r["rho"] for r in rows if r.get("rho") is not None]
    L=["# Combos: correlation-aware pricing (research, exploratory)","",
       "%d combos snapshotted, %d settled. Implied correlation known for %d; %d priced below the independence price (negative dependence)."%(
           len(rows),sum(1 for r in rows if r["ticker"] in res),len(rh),sum(1 for r in rows if r.get("rho") is None and r["mid"]<r["independent"]))]
    if rh:
        rs=sorted(rh); L.append("Implied correlation: median %.2f, middle half %.2f-%.2f."%(rs[len(rs)//2],rs[len(rs)//4],rs[3*len(rs)//4]))
    # out of sample: rho fitted on combos snapshotted before each one (median of earlier implied values)
    sc={"combo mid":[],"independence":[],"copula (earlier rho)":[]}; hist=[]
    for r in rows:
        y=res.get(r["ticker"])
        if y in ("yes","no") and hist:
            o=1.0 if y=="yes" else 0.0; rho=sorted(hist)[len(hist)//2]
            sc["combo mid"].append((r["mid"]-o)**2); sc["independence"].append((r["independent"]-o)**2); sc["copula (earlier rho)"].append((joint(r["ps"],rho)-o)**2)
        if r.get("rho") is not None: hist.append(r["rho"])
    n=len(sc["combo mid"])
    if n:
        L+=["","| Price | Brier (%d settled combos) |"%n,"|---|---:|"]+["| %s | %.4f |"%(k,sum(v)/len(v)) for k,v in sc.items()]
        yes=sum(1 for r in rows if res.get(r["ticker"])=="yes"); exp=sum(r["mid"] for r in rows if res.get(r["ticker"]) in ("yes","no"))
        L.append("Combos that won: %d; the combo mids expected %.1f."%(yes,exp))
    L+=["","Exploratory: legs in one game or one city share causes, so combos settled on the same day are not independent evidence. Nothing here is a rule or a trade."]
    os.makedirs(OUT,exist_ok=True); open(os.path.join(OUT,"combo.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))
    return sc
if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    a=sys.argv[1:]
    if a[:1]==["snapshot"]: snapshot(int(a[a.index("--max")+1]) if "--max" in a else 300)
    elif a[:1]==["settle"]: settle()
    elif a[:1]==["report"]: report()
    else: sys.exit(__doc__)
