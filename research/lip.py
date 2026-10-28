"""PLAN5 test L: resting quotes on weather markets with Kalshi's liquidity rewards (forward paper test; research only).
Follows research/PLAN5.md. Read-only: Kalshi public API GETs only (same domain and User-Agent as kalshi.py); it never
places, changes or cancels an order and never opens paper.db or live.db. Python 3.8+, needs requests.
  python research/lip.py sample   one hourly sample (2026-10-24 .. 2026-11-20 local): up to 40 markets' order books
                                  -> data/lip/samples.jsonl; trade lists and candles for earlier samples -> fills
  python research/lip.py settle   results of sampled markets that have closed -> data/lip/results.json
  python research/lip.py score    scored once, on or after 2026-11-25 -> results/plan5_L.md and .json
Each step is safe to rerun: a sample hour is taken once, a failed request is retried on the next run."""
import os, sys, time, random
from datetime import datetime, timezone, timedelta
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import num, rts, cents
from tbcommon.jsonio import load, save, lines, append
from tbcommon import ohlc as OHLC   # descriptive candle checks (fill records only)
from tbcommon import clock   # result stamps with their UTC offset (2026-10-23)
DATA=os.path.join(HERE,"data","lip"); OUT=os.path.join(HERE,"results")
CLIENT=JsonClient(KALSHI_PUBLIC,tries=6,timeout=30,pause_after=0.12,backoff_base=3.0,backoff_cap=60.0,verbose=True)
SERIES=("KXRAIN","KXHIGH","KXLOW"); Q=10; QS=(1,10,100); PER=40
LOCAL=timezone(timedelta(hours=-4))   # America/La_Paz: UTC-4 all year
# Window moved 2026-10-22 before any sample was taken (the scheduled runs could not start on Oct 16; PLAN5 revision notes)
START=datetime(2026,10,24,0,0,tzinfo=LOCAL).timestamp(); END=datetime(2026,11,21,0,0,tzinfo=LOCAL).timestamp()
CLOSE_MAX=datetime(2026,11,23,0,0,tzinfo=LOCAL).timestamp()   # only markets that settle before the score date
SCORE_FROM=datetime(2026,11,25,0,0,tzinfo=LOCAL).timestamp()
UNITS={"1/10,000 dollar (used)":1e-4,"cent":1e-2,"1/1,000,000 dollar":1e-6}

def http(path,params=None,tries=6): return CLIENT.get(path,params,tries=tries)
def series_of(t): return (t or "").split("-")[0]
def weather(t): return series_of(t).startswith(SERIES)

# ---------------- the reward and fill rules (PLAN5 test L) ----------------
def ladder(book,side):
    """[(price_cents, size)] of one side's bids, best first."""
    out=[]
    for p,q in (book.get(side) or []):
        p,q=num(p),num(q)
        if p is not None and q and q>0: out.append((cents(p),q))
    return sorted(out,key=lambda x:-x[0])
def side_score(lad,target,d,q):
    """(qualifying size, our share for q contracts at the best bid, total size). Reference = the first level from the best
    bid down where the cumulative size reaches target/5; a level k cents below it counts size x d^k."""
    tot=sum(s for _,s in lad)
    if not lad: return 0.0,0.0,0.0
    cum=0.0; ref=lad[-1][0]
    for p,s in lad:
        cum+=s
        if cum>=target/5: ref=p; break
    qual=sum(s*(d**max(0,ref-p)) for p,s in lad)
    return qual,q/(qual+q),tot
def quote(book,prog,qs=QS):
    """The hypothetical 10-a-side quote and the hour's reward for one sampled order book (None if skipped, with a reason)."""
    y,n=ladder(book,"yes"),ladder(book,"no")
    if not y and not n: return None,"no bids"
    by=y[0][0] if y else None; bn=n[0][0] if n else None
    if by is not None and bn is not None and by+bn>=100: return None,"locked or crossed book"
    target=num(prog.get("target_size_fp")) or 0; d=(num(prog.get("discount_factor_bps")) or 0)/10000.0
    t0,t1=rts(prog.get("start_date")),rts(prog.get("end_date"))
    if not target or not t0 or not t1 or t1<=t0: return None,"unreadable program"
    rate=(num(prog.get("period_reward")) or 0)*3600/(t1-t0)   # program units per hour
    valid=bool(y and n and sum(s for _,s in y)>=target and sum(s for _,s in n)>=target)
    out=dict(yes_bid=by,no_bid=bn,yes_queue=y[0][1] if y else 0,no_queue=n[0][1] if n else 0,valid=valid,target=target,d=d,rate_units=rate,
             usd_per_day=rate*1e-4*24)
    for q in qs:
        sy=side_score(y,target,d,q)[1] if y else 0.0; sn=side_score(n,target,d,q)[1] if n else 0.0
        out["reward_%d"%q]=rate*1e-4*(sy+sn)/2 if valid else 0.0   # dollars, reading period_reward as 1/10,000 dollar
        out["share_%d"%q]=(sy+sn)/2; out["share_yes_%d"%q]=sy; out["share_no_%d"%q]=sn
        out["capital_%d"%q]=q*((by or 0)+(bn or 0))/100.0
    return out,None
def tprice(r,key):
    p=num(r.get(key+"_price_dollars"))
    if p is None:
        c=num(r.get(key+"_price")); p=c/100 if c is not None else None
    return p
def fills(trades,qt,q,detail=False):
    """Contracts of each quoted side filled in the hour: any trade through our price fills us; at our price only the
    volume beyond the size already resting there counts (our place in the queue). With detail, also the moment the
    fill happened, for the adverse-selection check."""
    res={}; when={}
    tr=sorted(trades,key=lambda r:rts(r.get("created_time")) or 0)
    for side,taker,price_key,bid,queue in (("yes","no","yes",qt.get("yes_bid"),qt.get("yes_queue",0)),("no","yes","no",qt.get("no_bid"),qt.get("no_queue",0))):
        if bid is None: res[side]=0; continue
        at=0.0; through=False; t_fill=None
        for r in tr:
            if (r.get("taker_side") or "").lower()!=taker: continue
            p=tprice(r,price_key)
            if p is None: continue
            pc=cents(p); n=num(r.get("count_fp")) or num(r.get("count")) or 0
            if pc<bid: through=True
            elif pc==bid: at+=n
            else: continue
            if t_fill is None and (through or at>queue): t_fill=rts(r.get("created_time"))
        res[side]=q if through else int(min(q,max(0.0,at-queue)))
        when[side]=t_fill if res[side] else None
    return (res,when) if detail else res
# ---------------- steps ----------------
def programs(now):
    p=os.path.join(DATA,"programs.json"); c=load(p)
    if c and now-c["fetched"]<6*3600: return c["rows"]
    rows=[]; cur=None
    for _ in range(500):
        prm=dict(status="active",limit=1000)
        if cur: prm["cursor"]=cur
        j=http("/incentive_programs",prm); page=j.get("incentive_programs") or []
        rows+=[dict(market_ticker=x.get("market_ticker"),start_date=x.get("start_date"),end_date=x.get("end_date"),period_reward=x.get("period_reward"),
                    target_size_fp=x.get("target_size_fp"),discount_factor_bps=x.get("discount_factor_bps"),incentive_type=x.get("incentive_type"))
               for x in page if (x.get("incentive_type") or "")=="liquidity" and weather(x.get("market_ticker"))]
        cur=j.get("next_cursor") or j.get("cursor")
        if not cur or not page: break
    save(p,dict(fetched=now,rows=rows)); return rows
def fee_types(series):
    p=os.path.join(DATA,"series.json"); c=load(p,{})
    for s in sorted(set(series)-set(c)):
        c[s]=(http("/series/"+s).get("series") or {}).get("fee_type")
    save(p,c); return c
def markets(tickers):
    out={}; ts=sorted(set(tickers))
    for i in range(0,len(ts),50):
        for m in (http("/markets",dict(tickers=",".join(ts[i:i+50]),limit=1000)).get("markets") or []): out[m.get("ticker")]=m
    return out
def sample(now=None):
    now=now or time.time(); hour=int(now//3600)
    S=os.path.join(DATA,"samples.jsonl"); L=os.path.join(DATA,"sample_log.jsonl")
    took=load(os.path.join(DATA,"hours.json"),{})
    if START<=now<END and str(hour) not in took:
        progs=[x for x in programs(now) if (rts(x["start_date"]) or 1e18)<=now<(rts(x["end_date"]) or 0)]
        by={}; cnt={}
        for x in progs: by.setdefault(x["market_ticker"],x); cnt[x["market_ticker"]]=cnt.get(x["market_ticker"],0)+1   # the first listed program; overlaps counted
        ft=fee_types([series_of(t) for t in by]); why={}
        if any(v>1 for v in cnt.values()): why["markets with overlapping programs (first used)"]=sum(1 for v in cnt.values() if v>1)
        ms=markets(list(by))
        uni=[]
        for t in sorted(by):
            m=ms.get(t) or {}
            if (m.get("status") or "").lower()!="active": why["not active"]=why.get("not active",0)+1; continue
            ct=rts(m.get("close_time"))
            if not ct or ct<=now+2*3600: why["closes within 2 hours"]=why.get("closes within 2 hours",0)+1; continue
            if ct>CLOSE_MAX: why["settles after the score date"]=why.get("settles after the score date",0)+1; continue
            if ft.get(series_of(t))!="quadratic": why["fee type not quadratic"]=why.get("fee type not quadratic",0)+1; continue
            uni.append(t)
        pick=sorted(random.Random(hour).sample(uni,min(PER,len(uni))))
        rows=[]
        for t in pick:
            try: book=(http("/markets/%s/orderbook"%t).get("orderbook_fp") or {})
            except RuntimeError as ex: why["order book failed"]=why.get("order book failed",0)+1; print("  book failed",t,ex); continue
            b={"yes":book.get("yes_dollars") or [],"no":book.get("no_dollars") or []}
            qt,skip=quote(b,by[t])
            if qt is None: why[skip]=why.get(skip,0)+1; continue
            rows.append(dict(ts=round(now,1),hour=hour,ticker=t,series=series_of(t),close=rts((ms.get(t) or {}).get("close_time")),
                             program={k:by[t][k] for k in ("start_date","end_date","period_reward","target_size_fp","discount_factor_bps")},book=b,quote=qt))
        append(S,rows); took[str(hour)]=dict(ts=now,universe=len(uni),sampled=len(rows),skipped=why); save(os.path.join(DATA,"hours.json"),took)
        append(L,[dict(ts=now,universe=len(uni),sampled=len(rows),skipped=why)])
        print("lip sample: %d markets in the universe, %d sampled, skipped %s"%(len(uni),len(rows),why))
    elif not (START<=now<END): print("lip sample: outside the sampling window (2026-10-24 .. 2026-11-20 local); nothing sampled")
    else: print("lip sample: this hour was already sampled")
    fill_step(now)
def candles(series,ticker,t0,t1):
    j=http("/series/%s/markets/%s/candlesticks"%(series,ticker),dict(start_ts=int(t0),end_ts=int(t1),period_interval=1))
    return sorted(j.get("candlesticks") or [],key=lambda c:c.get("end_period_ts") or 0)
def cpx(c,k):
    d=c.get(k) or {}; v=num(d.get("close_dollars"))
    if v is None:
        x=num(d.get("close")); v=x/100 if x is not None else None
    return v
def mid_at(cs,t):
    """The standing mid at time t: the latest one-minute candle ending at or before t. Candles may be missing for
    minutes when nothing changed, so the candle window starts an hour before the first fill."""
    last=None
    for c in cs:
        if (c.get("end_period_ts") or 0)<=t: last=c
    if not last: return None
    b=cpx(last,"yes_bid"); a=cpx(last,"yes_ask")
    return (a+b)/2 if (a is not None and b is not None and 0<=b<a<=1) else None
def adverse_mid(cs,side,t_fill,price_cents,lags=(60,300)):
    """Mid-price move after a fill, in the filled side's favour (+) or against it (-), at each lag."""
    out={}
    for l in lags:
        m=mid_at(cs,t_fill+l) if t_fill else None
        out[str(l)]=None if m is None else round((m if side=="yes" else 1-m)-price_cents/100,4)
    return out
def candle_check(cs,fill_ts,now,lags=(60,300)):
    """Descriptive record of the candles behind the adverse-selection numbers (added 2026-10-23, before the first
    sample; never read by score()): anomaly codes over the fetched candles (tbcommon/ohlc.py) and, per filled side and
    lag, how old the candle that mid_at() used was. An old candle means no quote change since then, not an error."""
    def age(t):
        last=None
        for c in cs:
            if (c.get("end_period_ts") or 0)<=t: last=c
        return round(t-last["end_period_ts"],1) if last else None
    return dict(codes=OHLC.summary([OHLC.check_series(cs,60,now)]),
                age={sd:{str(l):(age(t+l) if t else None) for l in lags} for sd,t in fill_ts.items()})
def fill_step(now):
    """For samples whose hour (plus 7 minutes for the 5-minute check) is over: the hour's trades, the fills, the
    reward prorated to the time before each side filled, and the mid 1 and 5 minutes after each fill. Each sample once;
    a failed trade list is retried on the next run. Candles only feed the adverse-selection check: if they fail, the
    fills are still recorded, with that check left empty. Each record is written as soon as it is worked out."""
    F=os.path.join(DATA,"fills.jsonl"); have={(r["hour"],r["ticker"]) for r in lines(F)}
    todo=[s for s in lines(os.path.join(DATA,"samples.jsonl")) if s["ts"]+3600+420<=now and (s["hour"],s["ticker"]) not in have]
    n=0
    for s in todo:
        try:
            tr=[]; cur=None
            for _ in range(50):
                prm=dict(ticker=s["ticker"],min_ts=int(s["ts"]),max_ts=int(s["ts"]+3600),limit=1000)
                if cur: prm["cursor"]=cur
                j=http("/markets/trades",prm); tr+=j.get("trades") or []; cur=j.get("cursor")
                if not cur: break
            qt=s["quote"]; f10,w10=fills(tr,qt,Q,detail=True)
        except Exception as ex: print("  trades failed (retried next run)",s["ticker"],str(ex)[:120]); continue
        fill_t=[w10[sd] for sd in ("yes","no") if f10.get(sd) and w10.get(sd)]
        try: cs=candles(s["series"],s["ticker"],min(fill_t)-3600,max(fill_t)+420) if fill_t else []; cok=True
        except Exception as ex: cs=[]; cok=False; print("  candles failed (adverse check left empty)",s["ticker"],str(ex)[:120])
        adv={sd:(adverse_mid(cs,sd,w10[sd],qt["%s_bid"%sd]) if cok else {"60":None,"300":None}) for sd in ("yes","no") if f10.get(sd)}
        rec=dict(hour=s["hour"],ticker=s["ticker"],trades=len(tr),adverse_10=adv,fill_time_10=w10)
        for q in QS:
            fx=fills(tr,qt,q); rec["fill_%d"%q]=fx
            fr={sd:(min(1.0,max(0.0,((w10.get(sd) or s["ts"])-s["ts"])/3600.0)) if fx.get(sd) else 1.0) for sd in ("yes","no")}
            rate=(qt.get("rate_units") or 0)*1e-4
            rec["reward_%d"%q]=(rate*(qt.get("share_yes_%d"%q,0)*fr["yes"]+qt.get("share_no_%d"%q,0)*fr["no"])/2) if qt.get("valid") else 0.0
        if not cok: rec["candles_failed"]=True
        elif cs:
            try: rec["candle_check"]=candle_check(cs,{sd:w10[sd] for sd in adv},now)   # descriptive, never scored
            except Exception as ex: print("  candle check skipped",s["ticker"],str(ex)[:120])
        append(F,[rec]); n+=1
    if n: print("lip fills: %d sample hours checked"%n)
def settle(now=None):
    now=now or time.time(); p=os.path.join(DATA,"results.json"); res=load(p,{})
    ss=lines(os.path.join(DATA,"samples.jsonl"))
    todo=sorted({s["ticker"] for s in ss if s["ticker"] not in res and (s.get("close") or 0)<=now})
    got=markets(todo)
    for t in todo:
        m=got.get(t)
        if m is None:   # the batch call may not return settled markets (CLAUDE.md section 8): ask for it alone
            try: m=(http("/markets/"+t).get("market") or {})
            except RuntimeError: m={}
        r=(m.get("result") or "").lower()
        if r in ("yes","no"): res[t]=r
    save(p,res); print("lip settle: %d results (%d asked)"%(len(res),len(todo)))
def event_of(t): return (t or "").rsplit("-",1)[0]
def ratio_se(units):
    """units: [(net, capital, day, event, null sd)]. Capital-weighted mean m = sum(net) / sum(capital), and its SE =
    the largest of: clustered by day, clustered by event, and the null SE (contracts of one event move together)."""
    W=sum(u[1] for u in units)
    if not units or W<=0: return None,None
    m=sum(u[0] for u in units)/W
    def cl(i):
        g={}
        for u in units: g[u[i]]=g.get(u[i],0.0)+(u[0]-m*u[1])
        C=len(g)
        return (C/(C-1)*sum(v*v for v in g.values()))**0.5/W if C>1 else float("inf")
    ev={}
    for u in units: ev[u[3]]=ev.get(u[3],0.0)+u[4]
    se0=(sum(v*v for v in ev.values()))**0.5/W
    return m,max(cl(2),cl(3),se0)
def score(now=None):
    now=now or time.time()
    out=os.path.join(OUT,"plan5_L.json")
    if os.path.exists(out): sys.exit("plan5_L.json exists: PLAN5 scores each test once.")
    if now<SCORE_FROM: sys.exit("Test L is scored on or after 2026-11-25 (PLAN5).")
    try:
        import fees; eligible=bool(fees.INCENTIVES_ELIGIBLE); confirmed=getattr(fees,"ELIGIBILITY_CONFIRMED_ON",None)
    except ImportError: eligible,confirmed=False,None
    try: rewards_apply=bool(eligible and confirmed and datetime.fromisoformat(str(confirmed)).replace(tzinfo=LOCAL).timestamp()<END)
    except ValueError: rewards_apply=False; confirmed="unreadable: %r"%(confirmed,)
    ss=lines(os.path.join(DATA,"samples.jsonl")); fl={(r["hour"],r["ticker"]):r for r in lines(os.path.join(DATA,"fills.jsonl"))}
    res=load(os.path.join(DATA,"results.json"),{}); left={"no fill check":0,"market not settled":0,"day with under 12 sampled hours":0}
    hours_by_day={}
    for s in ss: hours_by_day.setdefault(datetime.fromtimestamp(s["ts"],LOCAL).date().isoformat(),set()).add(s["hour"])
    filled_samples=unsettled_filled=0; units_r=[]; units_s=[]; ev_filled=set(); adv={"60":[],"300":[]}; bad_units=[]
    tot=dict(reward=0.0,fillpnl=0.0,capital=0.0,filled=0,samples=0,valid=0); byser={}; qv={q:dict(reward=0.0,fillpnl=0.0,capital=0.0) for q in QS}
    for s in ss:
        f=fl.get((s["hour"],s["ticker"]))
        if not f: left["no fill check"]+=1; continue
        qt=s["quote"]; r=res.get(s["ticker"]); fq=f["fill_%d"%Q]; filled=fq["yes"]+fq["no"]
        if filled: filled_samples+=1
        if r is None:
            left["market not settled"]+=1; unsettled_filled+=bool(filled); continue
        day=datetime.fromtimestamp(s["ts"],LOCAL).date().isoformat()
        if len(hours_by_day.get(day,())) <12: left["day with under 12 sampled hours"]+=1; continue
        u=qt.get("usd_per_day")
        if u is not None and not (1<=u<=1000): bad_units.append(s["ticker"])
        def pnl(fx): return (fx["yes"]*((1 if r=="yes" else 0)-qt["yes_bid"]/100) if fx["yes"] else 0)+(fx["no"]*((1 if r=="no" else 0)-qt["no_bid"]/100) if fx["no"] else 0)
        fp=pnl(fq); rw=f.get("reward_%d"%Q,qt["reward_%d"%Q]); cap=qt["capital_%d"%Q]
        if cap<=0: continue
        sd=sum(fq[x]*((qt["%s_bid"%x]/100)*(1-qt["%s_bid"%x]/100))**0.5 for x in ("yes","no") if fq[x])
        units_r.append((rw+fp,cap,day,event_of(s["ticker"]),sd)); units_s.append((fp,cap,day,event_of(s["ticker"]),sd))
        if filled: ev_filled.add(event_of(s["ticker"]))
        for x,a in (f.get("adverse_10") or {}).items():
            for l in adv:
                if a.get(l) is not None: adv[l].append(a[l])
        tot["reward"]+=rw; tot["fillpnl"]+=fp; tot["capital"]+=cap; tot["filled"]+=filled; tot["samples"]+=1; tot["valid"]+=bool(qt["valid"])
        b=byser.setdefault(s["series"],dict(samples=0,reward=0.0,fillpnl=0.0,capital=0.0)); b["samples"]+=1; b["reward"]+=rw; b["fillpnl"]+=fp; b["capital"]+=cap
        for q in QS:
            fx=f["fill_%d"%q]; qv[q]["reward"]+=f.get("reward_%d"%q,qt["reward_%d"%q]); qv[q]["capital"]+=qt["capital_%d"%q]; qv[q]["fillpnl"]+=pnl(fx)
    days=len({u[2] for u in units_s}); m,se=ratio_se(units_r); mf,sef=ratio_se(units_s)
    t=(m/se) if (m is not None and se) else None; tf=(mf/sef) if (mf is not None and sef) else None
    enough=days>=15 and tot["filled"]>=100 and len(ev_filled)>=20
    settled_ok=unsettled_filled<=0.02*max(1,filled_samples)
    spread_only="NOT TESTABLE" if not (enough and settled_ok) else ("PASS" if (tf is not None and tf>=2.5) else "FAIL")
    c3=tot["fillpnl"]>=-0.5*tot["reward"]
    verdict="NOT TESTABLE" if not (enough and settled_ok) or bad_units else ("PASS" if (t is not None and t>=2.5 and c3) else "FAIL")
    head=mf if not rewards_apply else m
    R=dict(plan="research/PLAN5.md L",scored=clock.iso(seconds=False),
           spread_only=dict(verdict=spread_only,mean_return_per_dollar_hour=mf,se=sef,t=tf),
           with_rewards=dict(verdict=verdict,applies=rewards_apply,eligible_flag=eligible,eligibility_confirmed_on=confirmed,mean_return_per_dollar_hour=m,se=se,t=t,
                             fills_not_eating_rewards=c3,unit_problem_tickers=sorted(set(bad_units))[:20]),
           days=days,events_with_fills=len(ev_filled),totals=tot,left_out=left,unsettled_filled_samples=unsettled_filled,by_series=byser,
           by_size={str(q):v for q,v in qv.items()},adverse_selection={l:dict(n=len(v),mean=(sum(v)/len(v)) if v else None) for l,v in adv.items()},
           headline_return_per_dollar_hour=head,dollars_per_day_at_25=(head*25*24 if head is not None else None))
    os.makedirs(OUT,exist_ok=True); save(out,R)
    pc=lambda x:"n/a" if x is None else "%+.3f%%"%(100*x)
    L=["# PLAN5 test L: resting quotes on weather markets (scored once, %s)"%R["scored"],"",
       "**Spread alone (no rewards): %s** (t %s). This is the verdict that applies%s."%(spread_only,"%.2f"%tf if tf is not None else "n/a","" if not rewards_apply else " alongside the rewards verdict"),
       "With rewards: %s (t %s)%s."%(verdict,"%.2f"%t if t is not None else "n/a"," - applies: eligibility confirmed %s"%confirmed if rewards_apply else " - reported only: the account's eligibility was not confirmed before the window ended"),
       "%d days, %d sampled market-hours (%d valid for rewards), %d contracts filled in %d events. Mid move after a fill (in the filled side's favour): %s after 1 minute, %s after 5 minutes."%(days,tot["samples"],tot["valid"],tot["filled"],len(ev_filled),
           *[pc(R["adverse_selection"][l]["mean"]) for l in ("60","300")]),
       "Headline: %s per dollar of capital per hour, about $%s a day at the $25 cap. Capital tied up in filled positions until they settle is not in this figure."%(pc(head),"n/a" if R["dollars_per_day_at_25"] is None else "%.2f"%R["dollars_per_day_at_25"]),
       "A FAIL means the test could not tell, not that there is no edge. Paper estimate only: Kalshi's own fills and reward statement are the real test."]
    open(os.path.join(OUT,"plan5_L.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))

if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd=="sample": sample()
    elif cmd=="settle": settle()
    elif cmd=="score": score()
    else: sys.exit(__doc__)
