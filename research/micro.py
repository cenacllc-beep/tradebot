"""Order flow, fills and lead-lag (research only; added 2026-10-22, platform upgrade phases 13-16). Exploratory: it
cannot pass or fail, and it places no orders. A pattern found here earns only a pre-registered forward test.

Kalshi's real-time feed (websocket) needs an API key, so this uses public REST polling. The finest horizon it can
see is the real polling cycle (asked for every 5 seconds; with 12 markets it is usually longer, and the report uses the
measured cycle). Book times come from the PC's clock and trade times from Kalshi's, so a clock difference shifts
the shortest horizons.

  python research/micro.py record [--minutes 30] [--every 5] [TICKER ...]
      Polls up to 12 markets' order books every few seconds, plus their new trades. Default markets: the 12 open
      weather markets with the most volume in research/data/discovery.db. Output: research/data/micro/<start>.jsonl
  python research/micro.py analyze [FILE ...]   -> research/results/micro.md and .json

What analyze measures (settlement forecasts are a different question and are not mixed in):
1. **Order-flow features → later mid.** Features per snapshot: spread, top-3 depth each side, book imbalance, signed
   taker flow over the last minute, mid change over the last 30 seconds, seconds since the last trade. Targets: the
   mid 5 s, 30 s, 1 min, 5 min and 30 min later. Reported by book imbalance (sell-heavy below -0.2, balanced,
   buy-heavy above +0.2; imbalance = (YES depth - NO depth) / both, top 3 levels): mean move and the share of up and
   down moves, with an SE clustered by market.
2. **Fill and queue model.** At each snapshot, a 1-contract buy of YES and of NO under three policies:
   - JOIN the best bid, behind the size already there;
   - IMPROVE it by 1 cent (if that does not cross), first in line;
   - CROSS the spread now, paying the taker fee.
   A resting order fills when later taker volume at its price exceeds the queue ahead, or a trade goes through its
   price, within 5 minutes; otherwise it is cancelled. Reported: P(fill within 5 s, 30 s, 1 min, 5 min), queue
   depletion per minute at the best bid, value at fill (the mid 1 minute later minus the price, minus any fee), and
   the expected net value per decision = P(fill) x value at fill. Doing nothing is worth 0.
3. **Adverse selection and toxicity.** For every simulated fill: spread capture (mid at fill minus price) and the mid's
   move 5 s, 30 s, 1 min and 5 min after, in the order's favour. P(toxic fill | state) = the share of fills followed
   by an adverse 1-minute move, by imbalance (seen from the order's side) and spread.
4. **Lead-lag between related markets** (same event). Correlation of one market's mid change with the other's mid
   change dt seconds later, for dt = 0, 5, 30 and 60. A lead is only worth anything if the follower's move beats its
   spread plus fees, so the share of leader moves followed by a follower move larger than half the follower's spread
   plus the taker fee is reported too. A price difference is never treated as arbitrage.
Read-only Kalshi public GETs, same domain and User-Agent as kalshi.py. Python 3.8+, needs requests (record only)."""
import os, sys, json, time, sqlite3
from bisect import bisect_left, bisect_right
from datetime import datetime
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import num, rts
from tbcommon.stats import cl_mean_se
import fees
DATA=os.path.join(HERE,"data","micro"); OUT=os.path.join(HERE,"results")
IMB_CUTS=(-0.2,0.2); HORIZONS=(5,30,60,300,1800); FILL_H=(5,30,60,300); MAX_MARKETS=12; MIN_GAP=0.125
CLIENT=JsonClient(KALSHI_PUBLIC,tries=4,timeout=15,min_gap=MIN_GAP,backoff_base=2.0,backoff_cap=30.0)
def http(path,params=None,tries=4): return CLIENT.get(path,params,tries=tries)
def fee1(p): return fees.taker(p)   # taker fee for one contract, rounded up to the cent
# ---------------- recording ----------------
def ladder(levels,n=5):
    out=[]
    for p,q in levels or []:
        p,q=num(p),num(q)
        if p is not None and q: out.append([round(p,4),q])
    return sorted(out,key=lambda x:-x[0])[:n]
def default_markets(n=MAX_MARKETS):
    db=os.path.join(HERE,"data","discovery.db")
    if not os.path.exists(db): sys.exit("micro: give tickers, or run 'discover.py refresh' first")
    from pathlib import Path
    c=sqlite3.connect(Path(db).resolve().as_uri()+"?mode=ro",uri=True)
    return [t for (t,) in c.execute("select ticker from markets where status in ('open','active') and mve=0 and (series like 'KXRAIN%' or series like 'KXHIGH%' or series like 'KXLOW%') "
                                    "and yes_bid>0 and yes_ask<1 order by volume desc limit ?",(n,))]
def record(tickers=None,minutes=30,every=5,now=time.time):
    tickers=(tickers or default_markets())[:MAX_MARKETS]
    if not tickers: sys.exit("micro: no markets to record")
    os.makedirs(DATA,exist_ok=True); t0=now(); p=os.path.join(DATA,datetime.fromtimestamp(t0).strftime("%Y%m%d-%H%M")+".jsonl")
    info={}
    for i in range(0,len(tickers),50):
        for m in (http("/markets",dict(tickers=",".join(tickers[i:i+50]))).get("markets") or []):
            info[m["ticker"]]=dict(event=m.get("event_ticker"),close=rts(m.get("close_time")))
    seen={t:set() for t in tickers}; last={t:int(t0) for t in tickers}; n=0
    with open(p,"a",encoding="utf-8") as f:
        f.write(json.dumps(dict(kind="header",start=t0,every=every,markets=info))+"\n")
        while now()<t0+minutes*60:
            cyc=now()
            for t in tickers:
                try:
                    b=(http("/markets/%s/orderbook"%t).get("orderbook_fp") or {}); ts=now()
                    f.write(json.dumps(dict(kind="book",t=round(ts,2),k=t,y=ladder(b.get("yes_dollars")),n=ladder(b.get("no_dollars"))),separators=(",",":"))+"\n")
                    tr=http("/markets/trades",dict(ticker=t,min_ts=last[t]-1,limit=1000)).get("trades") or []
                    new=[r for r in tr if r.get("trade_id") not in seen[t]]
                    for r in new:
                        seen[t].add(r.get("trade_id"))
                        f.write(json.dumps(dict(kind="trade",t=rts(r.get("created_time")),k=t,side=r.get("taker_side"),
                                                yes=num(r.get("yes_price_dollars")),q=num(r.get("count_fp")) or num(r.get("count"))),separators=(",",":"))+"\n")
                    if tr: last[t]=int(max(rts(r.get("created_time")) or last[t] for r in tr))
                    n+=1
                except RuntimeError as ex: print("  skipped",t,ex)
            f.flush(); w=cyc+every-now()
            if w>0: time.sleep(w)
    print("micro: %d book snapshots of %d markets in %s"%(n,len(tickers),p)); return p
# ---------------- analysis ----------------
def load(paths):
    books={}; trades={}; info={}
    for p in paths:
        for ln in open(p,encoding="utf-8"):
            try: r=json.loads(ln)
            except ValueError: continue
            if r.get("kind")=="header": info.update(r.get("markets") or {})
            elif r.get("kind")=="book": books.setdefault(r["k"],[]).append(r)
            elif r.get("kind")=="trade" and r.get("t") and r.get("yes") is not None: trades.setdefault(r["k"],[]).append(r)
    for v in books.values(): v.sort(key=lambda r:r["t"])
    for v in trades.values(): v.sort(key=lambda r:r["t"])
    return books,trades,info
def top(b):
    """(yes bid, yes ask, size at yes bid, size at no bid) from one snapshot; None when one side is empty or crossed."""
    if not b["y"] or not b["n"]: return None
    yb,ys=b["y"][0]; nb,ns=b["n"][0]; ya=round(1-nb,4)
    return (yb,ya,ys,ns) if 0<yb<ya<1 else None
def trade_times(trs):
    """The sorted time index of a market's trades (load() sorts trades by time), for bisect lookups."""
    return [r["t"] for r in trs]
def features(bs,trs,i,times=None,book=None):
    """Order-flow features of snapshot i. `times` is trade_times(trs) and `book` its BookIndex; passing them keeps this
    O(log n) per snapshot."""
    b=bs[i]; tp=top(b)
    if not tp: return None
    times=trade_times(trs) if times is None else times
    yb,ya,ys,ns=tp; t=b["t"]; mid=(yb+ya)/2
    dy=sum(q for _,q in b["y"][:3]); dn=sum(q for _,q in b["n"][:3])
    lo,hi=bisect_right(times,t-60),bisect_right(times,t)   # trades with t-60 < time <= t, in time order
    flow=sum((r["q"] or 0)*(1 if r["side"]=="yes" else -1) for r in trs[lo:hi])
    if book is not None: pt=book.top_at(t-30); prev=pt is not None
    else:
        prev=snap_at(bs,t-30); pt=top(prev) if prev is not None else None   # the latest snapshot at least 30 s old
    pm=((pt[0]+pt[1])/2) if (prev and pt) else None
    return dict(t=t,mid=mid,yb=yb,ya=ya,spread=ya-yb,qy=ys,qn=ns,imb=(dy-dn)/(dy+dn) if dy+dn>0 else 0.0,flow=flow,
                vel=(mid-pm) if pm is not None else None,since=(t-times[hi-1]) if hi else None)
def snap_at(bs,t):
    """The latest snapshot at or before t, or None."""
    lo,hi=0,len(bs)
    while lo<hi:
        m=(lo+hi)//2
        if bs[m]["t"]<=t: lo=m+1
        else: hi=m
    return bs[lo-1] if lo else None
def mid_after(bs,t,tol):
    """The mid of the first snapshot at or after t, if it came within tol seconds of t. Used for every 'later' value,
    so a slow polling cycle never reuses the starting snapshot as the later one."""
    lo,hi=0,len(bs)
    while lo<hi:
        m=(lo+hi)//2
        if bs[m]["t"]<t: lo=m+1
        else: hi=m
    if lo>=len(bs) or bs[lo]["t"]-t>tol: return None
    tp=top(bs[lo])
    return ((tp[0]+tp[1])/2) if tp else None
def mid_at(bs,t,tol):
    """The mid of the latest snapshot at or before t, if it is no older than tol seconds."""
    b=snap_at(bs,t)
    if b is None: return None
    tp=top(b)
    return ((tp[0]+tp[1])/2) if (tp and t-b["t"]<=tol) else None
class BookIndex:
    """One market's snapshots with a time index and precomputed tops and mids: the same answers as snap_at, mid_at and
    mid_after, by C-speed bisect instead of a Python loop per lookup (analyze makes about a million of them)."""
    def __init__(self,bs):
        self.bs=bs; self.times=[b["t"] for b in bs]; self.tops=[top(b) for b in bs]
        self.mids=[((tp[0]+tp[1])/2) if tp else None for tp in self.tops]
    def top_at(self,t):
        i=bisect_right(self.times,t); return self.tops[i-1] if i else None
    def mid_at(self,t,tol):
        i=bisect_right(self.times,t)
        if not i: return None
        j=i-1; return self.mids[j] if (self.tops[j] and t-self.times[j]<=tol) else None
    def mid_after(self,t,tol):
        i=bisect_left(self.times,t)
        if i>=len(self.times) or self.times[i]-t>tol: return None
        return self.mids[i]
def tercile(x,cuts): return 0 if x<cuts[0] else (1 if x<=cuts[1] else 2)
def simulate(bs,trs,i,side,policy,horizon=300,times=None):
    """One 1-contract buy of `side` at snapshot i. Returns dict(price, fill_t or None, fee) or None if not possible.
    `times` is trade_times(trs): the walk then starts at the first trade after the snapshot instead of the first one."""
    tp=top(bs[i])
    if not tp: return None
    yb,ya,ys,ns=tp; t=bs[i]["t"]
    bid=yb if side=="yes" else round(1-ya,4); ask=ya if side=="yes" else round(1-yb,4); queue=ys if side=="yes" else ns
    if policy=="CROSS": return dict(price=ask,fill_t=t,fee=fee1(ask))
    price=bid if policy=="JOIN" else round(bid+0.01,4)
    if policy=="IMPROVE" and price>=ask-1e-9: return None
    ahead=queue if policy=="JOIN" else 0.0
    start=bisect_right(times,t) if times is not None else 0
    for j in range(start,len(trs)):   # index walk: no copy of the trade list
        r=trs[j]
        if r["t"]<=t: continue
        if r["t"]>t+horizon: break
        if r["side"]==side: continue   # a taker buying our side does not trade with our bid
        p=r["yes"] if side=="yes" else 1-r["yes"]
        if p<price-1e-9: return dict(price=price,fill_t=r["t"],fee=0.0)
        if abs(p-price)<1e-9:
            ahead-=r["q"] or 0
            if ahead<0: return dict(price=price,fill_t=r["t"],fee=0.0)
    return dict(price=price,fill_t=None,fee=0.0)
def analyze(paths,stride=1):
    books,trades,info=load(paths)
    gaps=sorted(b["t"]-a["t"] for bs in books.values() for a,b in zip(bs,bs[1:]) if b["t"]>a["t"])
    every=gaps[len(gaps)//2] if gaps else 5.0   # the real polling cycle (24 requests can take longer than the 5 s asked for)
    tol=3*every; F=[]
    tindex={k:trade_times(v) for k,v in trades.items()}
    B={k:BookIndex(bs) for k,bs in books.items()}
    for k,bs in books.items():
        trs=trades.get(k,[]); times=tindex.get(k,[])
        for i in range(0,len(bs),stride):
            f=features(bs,trs,i,times,B[k])
            if f: f["k"]=k; f["i"]=i; F.append(f)
    if not F: return None
    cuts=IMB_CUTS
    # 1. features -> later mid
    feat={}
    for h in HORIZONS:
        for g in range(3):
            v=[]
            for f in F:
                if tercile(f["imb"],cuts)!=g: continue
                m=B[f["k"]].mid_after(f["t"]+h,tol)
                if m is not None: v.append((m-f["mid"],f["k"]))
            mean,se=cl_mean_se(v)
            feat["%d:%d"%(h,g)]=dict(n=len(v),mean=mean,se=se,up=(sum(1 for x,_ in v if x>0)/len(v)) if v else None,down=(sum(1 for x,_ in v if x<0)/len(v)) if v else None)
    # 2-3. fills, value and toxicity
    pol={}; tox={}
    for f in F:
        bs=books[f["k"]]; trs=trades.get(f["k"],[]); times=tindex.get(f["k"],[])
        for side in ("yes","no"):
            for policy in ("JOIN","IMPROVE","CROSS"):
                s=simulate(bs,trs,f["i"],side,policy,times=times)
                if not s: continue
                P=pol.setdefault((policy,side),dict(n=0,filled={str(h):0 for h in FILL_H},values=[],capture=[],adverse={str(h):[] for h in FILL_H}))
                P["n"]+=1
                if s["fill_t"] is None: continue
                d=s["fill_t"]-f["t"]
                for h in FILL_H:
                    if d<=h: P["filled"][str(h)]+=1
                bk=B[f["k"]]; m0=bk.mid_at(s["fill_t"],tol); m60=bk.mid_after(s["fill_t"]+60,tol)
                if m0 is None: continue
                v0=m0 if side=="yes" else 1-m0; P["capture"].append(v0-s["price"])
                for h in FILL_H:
                    mh=bk.mid_after(s["fill_t"]+h,tol)
                    if mh is not None: P["adverse"][str(h)].append(((mh if side=="yes" else 1-mh)-v0,f["k"]))
                if m60 is not None:
                    val=(m60 if side=="yes" else 1-m60)-s["price"]-s["fee"]; P["values"].append((val,f["k"]))
                    if policy!="CROSS":
                        key="%s, spread %s"%(("against the order","balanced","with the order")[tercile(f["imb"]*(1 if side=="yes" else -1),cuts)],"1c" if f["spread"]<=0.015 else "2c+")
                        T=tox.setdefault(key,[0,0]); T[0]+=1; T[1]+=((m60 if side=="yes" else 1-m60)-v0)<0
    polrep={}
    for (policy,side),P in pol.items():
        vm,vse=cl_mean_se(P["values"]); pf=P["filled"]["300"]/P["n"] if P["n"] else 0
        polrep["%s %s"%(policy,side)]=dict(decisions=P["n"],p_fill={h:(c/P["n"] if P["n"] else None) for h,c in P["filled"].items()},
            value_at_fill=vm,value_se=vse,fills_valued=len(P["values"]),expected_net=(pf*vm) if vm is not None else None,
            spread_capture=(sum(P["capture"])/len(P["capture"])) if P["capture"] else None,
            after_fill={h:cl_mean_se(v)[0] for h,v in P["adverse"].items()})
    # queue depletion at the best bid
    dep=[]
    for k,bs in books.items():
        trs=trades.get(k,[]); times=tindex.get(k,[])
        if len(bs)<2: continue
        span=(bs[-1]["t"]-bs[0]["t"])/60.0
        vol=0.0
        for b in bs:
            tp=top(b)
            if not tp: continue
            nxt=trs[bisect_right(times,b["t"]):bisect_right(times,b["t"]+every)]   # b.t < time <= b.t + every
            vol+=sum(r["q"] or 0 for r in nxt if r["side"]=="no" and abs(r["yes"]-tp[0])<1e-9)
        if span>0: dep.append((k,vol/span))
    # 4. lead-lag within events
    ll=[]; ev={}
    for k,v in info.items():
        if v.get("event"): ev.setdefault(v["event"],[]).append(k)
    for e,ks in ev.items():
        ks=[k for k in ks if k in books]
        for a in ks:
            for b in ks:
                if a>=b: continue
                for lead,fol in ((a,b),(b,a)):
                    res={}
                    for dt in (0,5,30,60):
                        x=[]; y=[]; hit=n_big=0
                        bl=books[lead]; BL=B[lead]; BF=B[fol]
                        for j_,s in enumerate(bl[:-1]):
                            t=s["t"]; gap=bl[j_+1]["t"]-t
                            if gap<=0 or gap>tol: continue
                            ma=BL.mid_at(t,tol); ma2=BL.mid_at(t+gap,tol)   # the leader's next snapshot
                            mb=BF.mid_at(t+dt,tol); mb2=BF.mid_after(t+dt+gap,tol)
                            if None in (ma,ma2,mb,mb2): continue
                            x.append(ma2-ma); y.append(mb2-mb)
                            if abs(ma2-ma)>=0.01:
                                n_big+=1; fb=BF.top_at(t+dt)
                                if fb and abs(mb2-mb)>(fb[1]-fb[0])/2+fee1((fb[0]+fb[1])/2): hit+=1
                        res[str(dt)]=dict(n=len(x),corr=corr(x,y),leader_moves=n_big,beats_costs=(hit/n_big) if n_big else None)
                    ll.append(dict(event=e,leader=lead,follower=fol,lags=res))
    R=dict(files=[os.path.basename(p) for p in paths],markets=len(books),snapshots=len(F),every=every,imbalance_cuts=cuts,
           features={k:v for k,v in feat.items()},policies=polrep,toxicity={k:dict(fills=v[0],adverse_share=v[1]/v[0]) for k,v in tox.items()},
           queue_depletion_per_min=dict(dep),lead_lag=ll)
    os.makedirs(OUT,exist_ok=True); json.dump(R,open(os.path.join(OUT,"micro.json"),"w"),indent=1,default=str)
    write_md(R); return R
def corr(x,y):
    n=len(x)
    if n<10: return None
    mx=sum(x)/n; my=sum(y)/n; sx=sum((a-mx)**2 for a in x)**0.5; sy=sum((b-my)**2 for b in y)**0.5
    return (sum((a-mx)*(b-my) for a,b in zip(x,y))/(sx*sy)) if sx>0 and sy>0 else None
def write_md(R):
    f=lambda x,d=1:"n/a" if x is None else ("%+."+str(d)+"fc")%(100*x)
    pc=lambda x:"n/a" if x is None else "%.0f%%"%(100*x)
    L=["# Order flow, fills and lead-lag (research, exploratory)","","%d markets, %d snapshots every %.0f seconds (%s)."%(R["markets"],R["snapshots"],R["every"],", ".join(R["files"])),"",
       "## Book imbalance and the later mid (YES side)","","| Horizon | Imbalance | Snapshots | Mean move | Up | Down |","|---|---|---:|---:|---:|---:|"]
    for h in HORIZONS:
        for g,name in enumerate(("sell-heavy","balanced","buy-heavy")):
            v=R["features"]["%d:%d"%(h,g)]; L.append("| %d s | %s | %d | %s | %s | %s |"%(h,name,v["n"],f(v["mean"],2),pc(v["up"]),pc(v["down"])))
    L+=["","## Join, improve or cross (1 contract, cancelled after 5 minutes)","","| Policy | Decisions | Fill in 5 s | 30 s | 1 min | 5 min | Value at fill (1 min) | Expected per decision |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k,v in sorted(R["policies"].items()):
        L.append("| %s | %d | %s | %s | %s | %s | %s | %s |"%(k,v["decisions"],*[pc(v["p_fill"][h]) for h in ("5","30","60","300")],f(v["value_at_fill"]),f(v["expected_net"],2)))
    L+=["","Doing nothing is worth 0. A policy with a negative expected value per decision loses to doing nothing.","","## Toxic fills (resting orders)","",
        "| State | Fills | Adverse 1-minute move |","|---|---:|---:|"]+["| %s | %d | %s |"%(k,v["fills"],pc(v["adverse_share"])) for k,v in sorted(R["toxicity"].items())]
    L+=["","## Lead-lag within events","","| Leader | Follower | Lag | Pairs | Correlation | Leader moves of 1c+ | Follower move beat its costs |","|---|---|---:|---:|---:|---:|---:|"]
    for x in R["lead_lag"]:
        for dt,v in x["lags"].items():
            L.append("| %s | %s | %s s | %d | %s | %d | %s |"%(x["leader"],x["follower"],dt,v["n"],"n/a" if v["corr"] is None else "%.2f"%v["corr"],v["leader_moves"],pc(v["beats_costs"])))
    L+=["","Exploratory. Polling sees changes only every few seconds; cancellations ahead in the queue are not seen, so fills of joined orders are optimistic. Nothing here is a rule or a trade."]
    open(os.path.join(OUT,"micro.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L[:3]))
if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    a=sys.argv[1:]
    if a[:1]==["record"]:
        mins=float(a[a.index("--minutes")+1]) if "--minutes" in a else 30; ev=float(a[a.index("--every")+1]) if "--every" in a else 5
        ts=[x for i,x in enumerate(a[1:],1) if not x.startswith("--") and a[i-1] not in ("--minutes","--every")]
        record(ts or None,mins,ev)
    elif a[:1]==["analyze"]:
        ps=a[1:] or sorted(os.path.join(DATA,x) for x in os.listdir(DATA) if x.endswith(".jsonl"))
        if not ps: sys.exit("micro: nothing recorded yet")
        analyze(ps)
    else: sys.exit(__doc__)
