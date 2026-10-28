"""POST-HOC checks of the rain limit-order lead (not pre-registered; asked for by an independent statistical review on
2026-10-14). Research only; never touches paper.db. Python 3.8+, no dependencies. Fixed random seed, so re-runs agree.
  python research/placebo.py   ->  research/results/rain_placebo.json and rain_placebo.md
Same holdout rows and the same trading and fill rules as research/backtest.py (PLAN.md). Questions:
 1. Permutation: shuffle the calibrated forecast across cities within each market day (1,000 times) and re-run the
    limit-order rule. If the shuffled forecasts earn about as much, the profit is not coming from the forecast.
 2. No-forecast benchmark: rest a NO limit order (an offer 1c under the YES ask) on every market whose mid is 30-80%.
 3. Profit by side (YES / NO fills) for the real rule.
 4. Serial correlation of the daily profit and a weekly block bootstrap interval for the mean daily profit."""
import os, sys, json, random, math
from datetime import date, timedelta
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import backtest as bt
OUT=bt.OUT; DATA=bt.DATA
def holdout():
    """The holdout rows exactly as backtest.main builds them (frozen rain model, 00:55 UTC quotes, 6-point spread cap)."""
    runs=bt.load_nbs(); coef=json.load(open(os.path.join(OUT,"rain_model.json"),encoding="utf-8"))["coef"]; rows=[]
    for l in open(os.path.join(DATA,"kalshi_rain.jsonl"),encoding="utf-8"):
        m=json.loads(l); bid,ask=m.get("scan_bid"),m.get("scan_ask")
        if bid is None or ask is None or not (0<=bid<ask<=1) or ask-bid>bt.SPREAD+1e-9: continue
        day=bt.d(m["day"]); f=bt.features(runs,m["station"],day)
        if not f: continue
        mid=(bid+ask)/2; c=bt.C(coef,f)
        rows.append(dict(day=m["day"],station=m["station"],y=1 if m["result"]=="yes" else 0,M=mid,C=c,B=bt.BLEND*c+(1-bt.BLEND)*mid,
                         bid=bid,ask=ask,lo=m.get("lo_after"),hi=m.get("hi_after")))
    return rows
def maker_fills(rows):
    """The limit-order part of backtest.trades, returning each fill (day, side, price, pnl)."""
    out=[]
    for r in rows:
        bid,ask,fair,y=r["bid"],r["ask"],r["B"],r["y"]
        yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
        side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
        if q-price>=bt.EDGE-1e-9 and 0<price<1:
            if side=="yes": lo=r["lo"]; filled=lo is not None and (lo<=price+1e-9 if imp else lo<price-1e-9)
            else: a=1-price; hi=r["hi"]; filled=hi is not None and (hi>=a-1e-9 if imp else hi>a+1e-9)
            if filled: win=(y==1)==(side=="yes"); out.append(dict(day=r["day"],side=side,price=price,pnl=(1 if win else 0)-price))
    return out
def daily(fills,days):
    by={d:0.0 for d in days}
    for f in fills: by[f["day"]]+=f["pnl"]
    return [by[d] for d in days]
def mean(x): return sum(x)/len(x) if x else 0.0
def se(x): m=mean(x); return (sum((v-m)**2 for v in x)/(len(x)-1)/len(x))**0.5 if len(x)>1 else float("inf")
def ar1(x):
    m=mean(x); num=sum((x[i]-m)*(x[i-1]-m) for i in range(1,len(x))); den=sum((v-m)**2 for v in x)
    return num/den if den else 0.0
def block_boot(x,block=7,n=5000,seed=11):
    """Moving-block bootstrap of the mean (blocks of consecutive market days). Returns (2.5th, 97.5th percentile)."""
    rnd=random.Random(seed); L=len(x); k=math.ceil(L/block); ms=[]
    for _ in range(n):
        s=[]
        for _ in range(k): i=rnd.randrange(0,L-block+1); s.extend(x[i:i+block])
        ms.append(mean(s[:L]))
    ms.sort(); return ms[int(0.025*n)],ms[int(0.975*n)-1]
def main():
    rows=holdout(); days=sorted({r["day"] for r in rows})
    real=maker_fills(rows); rd=daily(real,days); obs=mean(rd)
    # 1. permutation within day
    rnd=random.Random(7); byday={}
    for r in rows: byday.setdefault(r["day"],[]).append(r)
    perm=[]
    for _ in range(1000):
        pr=[]
        for d,rs in byday.items():
            cs=[r["C"] for r in rs]; rnd.shuffle(cs)
            for r,c in zip(rs,cs): pr.append(dict(r,B=bt.BLEND*c+(1-bt.BLEND)*r["M"]))
        perm.append(mean(daily(maker_fills(pr),days)))
    p_perm=(1+sum(v>=obs-1e-12 for v in perm))/(1+len(perm))
    # 2. no-forecast benchmark: NO limit order (YES offer 1c under the ask) when the mid is 30-80%
    nf=[]
    for r in rows:
        if not 0.30<=r["M"]<=0.80: continue
        ya=round(r["ask"]-0.01,2); ino=ya>round(r["bid"],2); price=round(1-(ya if ino else r["ask"]),2); a=1-price; hi=r["hi"]
        if hi is not None and (hi>=a-1e-9 if ino else hi>a+1e-9): nf.append(dict(day=r["day"],side="no",price=price,pnl=(1 if r["y"]==0 else 0)-price))
    nd=daily(nf,days)
    side={s:[f["pnl"] for f in real if f["side"]==s] for s in ("yes","no")}
    lo,hi=block_boot(rd)
    res=dict(kind="POST-HOC, not pre-registered (independent review 2026-10-14)",markets=len(rows),days=len(days),
             real=dict(fills=len(real),per_contract=mean([f["pnl"] for f in real]),day_mean=obs,day_se=se(rd),z=obs/se(rd) if se(rd) else None,
                       ar1=ar1(rd),block_bootstrap_95=[lo,hi]),
             permutation=dict(runs=len(perm),mean_of_shuffled=mean(perm),p95_of_shuffled=sorted(perm)[949],share_at_least_real=p_perm),
             no_forecast=dict(fills=len(nf),per_contract=mean([f["pnl"] for f in nf]),day_mean=mean(nd),day_se=se(nd)),
             by_side={s:dict(fills=len(v),per_contract=mean(v),total=sum(v)) for s,v in side.items()})
    os.makedirs(OUT,exist_ok=True)
    json.dump(res,open(os.path.join(OUT,"rain_placebo.json"),"w",encoding="utf-8"),indent=1)
    c=lambda x:"%+.1fc"%(100*x); u=lambda x:"%.1fc"%(100*x)
    L=["# Rain limit-order lead: post-hoc checks","","**POST-HOC, not pre-registered.** Asked for by an independent statistical review on 2026-10-14. Same holdout and rules as PLAN.md.","",
       "- Real rule: %d fills, %s a contract, %s per market day (SE %s, z %.2f) over %d days. Day-to-day correlation (lag 1): %.2f. Weekly block bootstrap 95%% interval for the daily mean: %s to %s."%(
         len(real),c(res["real"]["per_contract"]),c(obs),u(se(rd)),res["real"]["z"] or 0,len(days),res["real"]["ar1"],c(lo),c(hi)),
       "- Shuffled forecasts (forecast swapped between cities on the same day, 1,000 times): average %s per market day, 95th percentile %s. Share of shuffles earning at least the real rule: %.3f."%(
         c(res["permutation"]["mean_of_shuffled"]),c(res["permutation"]["p95_of_shuffled"]),p_perm),
       "- No forecast at all (NO limit order on every market with a 30-80%% mid): %d fills, %s a contract, %s per market day (SE %s)."%(
         len(nf),c(res["no_forecast"]["per_contract"]),c(res["no_forecast"]["day_mean"]),u(res["no_forecast"]["day_se"])),
       "- Real rule by side: "+"; ".join("%s %d fills, %s a contract, total $%.2f"%(s.upper(),v["fills"],c(v["per_contract"]),v["total"]) for s,v in res["by_side"].items())+".",
       "","Reading: if the shuffled forecasts or the no-forecast rule earn about as much as the real rule, the lead comes from the limit-order mechanics or a market-wide lean, not from the forecast."]
    open(os.path.join(OUT,"rain_placebo.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))
if __name__=="__main__": main()
