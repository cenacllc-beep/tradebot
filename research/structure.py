"""Market-structure scanner (research only; added 2026-10-22, platform upgrade phases 7-9). Descriptive: it records
logical price inconsistencies at EXECUTABLE prices and places no orders.

For each open event in the chosen series (default: Kalshi's "Climate and Weather" category) it checks three things:
1. **Threshold ladders.**
   - P(X > a) >= P(X > b) when a < b. A violation that can be traded means paying YES(a)'s ask plus NO(b), i.e.
     1 - YES(b)'s bid, costs less than $1 after fees. The pair then pays at least $1 whatever happens.
   - The same holds for "less than" ladders.
2. **Mutually exclusive buckets, buying every NO.** At most one bucket can win, so all NOs pay at least n - 1. That
   is an arbitrage when the YES bids sum to more than 1 plus fees.
3. **Exhaustive buckets, buying every YES.** Exactly one wins, so all YESes pay exactly 1. That is an arbitrage when
   the YES asks sum to less than 1 minus fees. It needs the buckets to cover every outcome, which is inferred from the
   strikes and flagged as an inference.
Each leg pays Kalshi's taker fee for one contract (0.07 x the series' multiplier x p x (1-p), rounded up to the cent).

The listing's quotes can be stale. Every flagged case is re-read from the live order book, and its executable size is
the smallest top-of-book size among the legs. Not arbitrage until both checks hold. Even then, legging in one at a
time leaves directional risk until the last leg fills, which is recorded.
  python research/structure.py scan [SERIES ...]   -> data/structure/runs.jsonl, results/structure.md
Read-only Kalshi public GETs (same domain and User-Agent as kalshi.py). Python 3.8+."""
import os, sys, json, time
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import num, px
from tbcommon import clock   # report times in the bot's zone, named (2026-10-23)
import fees
DATA=os.path.join(HERE,"data","structure"); OUT=os.path.join(HERE,"results")
CLIENT=JsonClient(KALSHI_PUBLIC,tries=5,timeout=30,pause_after=0.1,backoff_base=2.0,backoff_cap=None)
def http(path,params=None,tries=5): return CLIENT.get(path,params,tries=tries)
def fee1(p,mult=1.0):
    """Taker fee for one contract at price p (fees.taker); 0 for a missing price."""
    return fees.taker(p,1,mult) if p is not None else 0.0
def ladders(ms):
    """Threshold markets grouped into ladders: ('greater', [(strike, market)]) ascending; ('less', ...) ascending."""
    g=[(num(m.get("floor_strike")),m) for m in ms if (m.get("strike_type") or "") in ("greater","greater_or_equal") and num(m.get("floor_strike")) is not None]
    l=[(num(m.get("cap_strike")),m) for m in ms if (m.get("strike_type") or "") in ("less","less_or_equal") and num(m.get("cap_strike")) is not None]
    return [("greater",sorted(g,key=lambda x:x[0])),("less",sorted(l,key=lambda x:x[0]))]
def ladder_violations(ms,mult=1.0):
    """Pairs whose executable prices break the order. For 'greater' a<b: buy YES(a) at its ask and NO(b) at 1 - bid(b);
    edge = bid(b) - ask(a) - fees. For 'less' a<b: buy YES(b) and NO(a); edge = bid(a) - ask(b) - fees."""
    out=[]
    for kind,lad in ladders(ms):
        for i in range(len(lad)):
            for j in range(i+1,len(lad)):
                (sa,a),(sb,b)=lad[i],lad[j]
                if sa==sb: continue
                lo,hi=(a,b) if kind=="greater" else (b,a)   # lo: the market whose YES we buy; hi: the one whose NO we buy
                ask,bid=px(lo,"yes_ask"),px(hi,"yes_bid")
                if ask is None or bid is None or not (0<ask<1) or not (0<bid<1): continue
                gross=bid-ask; fees=fee1(ask,mult)+fee1(1-bid,mult); net=gross-fees
                if gross>0: out.append(dict(kind="ladder_"+kind,buy_yes=lo.get("ticker"),buy_no=hi.get("ticker"),ask=ask,bid=bid,gross=round(gross,4),fees=fees,net=round(net,4)))
    return out
def exhaustive(ms):
    """Inferred: one 'less' tail (YES below its cap), 'between' buckets of whole numbers (floor to cap inclusive), and one
    'greater' tail (YES above its floor), as in Kalshi's weather buckets: <58, 58-59, 60-61, >61. The low tail's cap
    equals the first bucket's floor, each next bucket starts one above the last one's cap, and the high tail's floor
    equals the last bucket's cap. Anything else (a missing whole number, an overlap, or a different encoding) is
    reported as not exhaustive, so the all-YES check is skipped. Returns (bool, why)."""
    lows=[m for m in ms if (m.get("strike_type") or "") in ("less","less_or_equal")]; highs=[m for m in ms if (m.get("strike_type") or "") in ("greater","greater_or_equal")]
    bs=sorted([m for m in ms if (m.get("strike_type") or "")=="between"],key=lambda m:num(m.get("floor_strike")) or 0)
    if len(lows)!=1 or len(highs)!=1 or not bs: return False,"needs one low tail, one high tail and buckets between"
    if any((m.get("strike_type") or "").endswith("_or_equal") for m in lows+highs): return False,"inclusive tails: encoding not checked"
    x=num(lows[0].get("cap_strike")); step=0
    for b in bs:
        f,c=num(b.get("floor_strike")),num(b.get("cap_strike"))
        if f is None or c is None or x is None or abs(f-x-step)>1e-9 or c<f: return False,"gap or overlap near %s"%b.get("ticker")
        x=c; step=1
    hf=num(highs[0].get("floor_strike"))
    if hf is None or abs(hf-x)>1e-9: return False,"gap or overlap before the high tail"
    return True,"inferred from strikes"
def bucket_checks(ms,mutually_exclusive,mult=1.0):
    out=[]; bids=[px(m,"yes_bid") for m in ms]; asks=[px(m,"yes_ask") for m in ms]
    if mutually_exclusive and len(ms)>=2 and all(b is not None and 0<b<1 for b in bids):
        gross=sum(bids)-1; fees=sum(fee1(1-b,mult) for b in bids)
        out.append(dict(kind="all_no",legs=len(ms),sum_bids=round(sum(bids),4),gross=round(gross,4),fees=round(fees,2),net=round(gross-fees,4)))
    ex,why=exhaustive(ms)
    if mutually_exclusive and ex and all(a is not None and 0<a<1 for a in asks):
        gross=1-sum(asks); fees=sum(fee1(a,mult) for a in asks)
        out.append(dict(kind="all_yes",legs=len(ms),sum_asks=round(sum(asks),4),gross=round(gross,4),fees=round(fees,2),net=round(gross-fees,4),exhaustive=why))
    return out
def book_top(t):
    b=(http("/markets/%s/orderbook"%t).get("orderbook_fp") or {})
    def top(side):
        lv=[(num(p),num(q)) for p,q in (b.get(side+"_dollars") or []) if num(p) is not None and num(q)]
        return max(lv) if lv else (None,0.0)
    (yb,yq),(nb,nq)=top("yes"),top("no")
    return dict(yes_bid=yb,yes_bid_size=yq,yes_ask=(1-nb) if nb is not None else None,yes_ask_size=nq)
def confirm(v,mult=1.0):
    """Re-read the legs' order books: is the violation still there at executable prices, and for how many contracts?"""
    if v["kind"].startswith("ladder"):
        a,b=book_top(v["buy_yes"]),book_top(v["buy_no"])
        if a["yes_ask"] is None or b["yes_bid"] is None: return dict(still=False)
        net=b["yes_bid"]-a["yes_ask"]-fee1(a["yes_ask"],mult)-fee1(1-b["yes_bid"],mult)
        return dict(still=net>0,net=round(net,4),size=min(a["yes_ask_size"],b["yes_bid_size"]))
    return dict(still=None,note="bucket baskets: confirm each leg by hand; legging in leaves directional risk until the last leg fills")
def scan(series=None,now=None):
    now=now or time.time(); os.makedirs(DATA,exist_ok=True)
    if not series:
        series=[x["ticker"] for x in (http("/series",dict(category="Climate and Weather")).get("series") or []) if x.get("ticker")]
    mult={}; events={}; n_m=0
    for s in sorted(set(series)):
        try: mult[s]=num((http("/series/"+s).get("series") or {}).get("fee_multiplier")) or 1.0
        except RuntimeError: mult[s]=1.0
        cur=None
        for _ in range(20):
            p=dict(series_ticker=s,status="open",limit=1000)
            if cur: p["cursor"]=cur
            j=http("/markets",p)
            for m in j.get("markets") or []: events.setdefault(m.get("event_ticker"),[]).append(m); n_m+=1
            cur=j.get("cursor")
            if not cur: break
    found=[]; summ=dict(ts=now,series=len(series),events=len(events),markets=n_m)
    for ev,ms in sorted(events.items()):
        s=(ev or "").split("-")[0]; mu=mult.get(s,1.0)
        try: me=bool((http("/events/"+ev).get("event") or {}).get("mutually_exclusive"))
        except RuntimeError: me=False
        for v in ladder_violations(ms,mu)+bucket_checks(ms,me,mu):
            v.update(event=ev,series=s)
            if v["net"]>0:
                try: v["confirm"]=confirm(v,mu)
                except RuntimeError as ex: v["confirm"]=dict(error=str(ex))
            found.append(v)
    rec=dict(summ,found=found); open(os.path.join(DATA,"runs.jsonl"),"a",encoding="utf-8").write(json.dumps(rec)+"\n")
    pos=[v for v in found if v["net"]>0]; conf=[v for v in pos if (v.get("confirm") or {}).get("still")]
    L=["# Market-structure scan (research, descriptive)","","Not arbitrage: prices can move before every leg fills, and legging in leaves directional risk until the last one does. Nothing was traded.","%s: %d series, %d open events, %d markets."%("%s, %s"%(clock.label(now),clock.ZONE_NOTE),len(series),len(events),n_m),
       "Inconsistencies with a positive gross gap: %d; positive after taker fees at listed prices: %d; still positive in the live order book: %d."%(len(found),len(pos),len(conf)),""]
    for v in sorted(pos,key=lambda v:-v["net"])[:20]:
        L.append("- %s %s: net %+.1fc per set%s"%(v["event"],v["kind"],100*v["net"],(" (still in the book at scan time, size %s)"%v["confirm"].get("size")) if (v.get("confirm") or {}).get("still") else ""))
    L+=["","Listed prices can be stale; a gap still in the book at scan time can vanish before an order arrives. Nothing was traded."]
    os.makedirs(OUT,exist_ok=True); open(os.path.join(OUT,"structure.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))
    return rec
if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    if len(sys.argv)>1 and sys.argv[1]=="scan":
        args=sys.argv[2:]; gap=None
        if "--every" in args:
            i=args.index("--every"); gap=float(args[i+1]); args=args[:i]+args[i+2:]
            try:
                last=json.loads(open(os.path.join(DATA,"runs.jsonl"),encoding="utf-8").read().splitlines()[-1])["ts"]
                if time.time()-last<gap: sys.exit("structure: last scan %.1f hours ago; next after %.1f hours"%((time.time()-last)/3600,gap/3600))
            except (OSError,IndexError,ValueError,KeyError): pass
        scan(args or None)
    else: sys.exit(__doc__)
