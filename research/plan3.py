"""PLAN3 tests A and B (research only; never touches paper.db or live.db; places no orders). Follows research/PLAN3.md.
Python 3.8+; the fetch commands need requests. Each test is scored once: a scorer refuses to run if its result file exists.
  python research/plan3.py asos       IEM airport readings (routine + special METARs), 24 plan-2 stations -> data/asos/
  python research/plan3.py candlesA   Kalshi quotes at the three looks, only for markets decided at some look
                                      -> data/kalshi_temp_looks.jsonl
  python research/plan3.py scoreA     Test A, scored once -> results/plan3_A.md and .json
  python research/plan3.py lowlist    settled KXLOWT markets and their stations (no prices) -> data/low_markets.json
  python research/plan3.py lowiem     NBS and CLI files for low-market stations not fetched before
  python research/plan3.py fitB       low model, training year only -> results/low_model.json (frozen, never refit)
  python research/plan3.py candlesB   KXLOWT quote at 00:55 UTC and trades until the day starts -> data/kalshi_low.jsonl
  python research/plan3.py scoreB     Test B, scored once -> results/plan3_B.md and .json
Fetching is polite and resumable (fetch.py's get(): one request at a time, pauses, backs off on 429/5xx). User-Agent
tradebot-paper-research/1.0, no personal data (CLAUDE.md)."""
import os, sys, json, glob, math, csv, io, calendar, bisect
from datetime import date, datetime, timedelta
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
for p in (HERE,ROOT):
    if p not in sys.path: sys.path.insert(0,p)
import backtest as bt, backtest2 as b2
from learn import betainc   # plain-Python incomplete beta (the PC has no scipy)
DATA=bt.DATA; OUT=bt.OUT
HOLD=(date(2026,7,1),date(2026,10,13))   # the plan-2 window
LOOKS=(13,15,17); LAG=300; FRESH=3600; CAP=0.97; MIN_REPORTS=3; BAR=2.5
def fx():
    """fetch.py, imported only when needed (needs requests). Its get() is replaced once, for plan 3 only, by one that
    does not retry 4xx answers other than 429 (a ticker moved to the archive answers the same way every time)."""
    import fetch
    if not getattr(fetch,"_plan3",False):
        import requests, time
        def get(url,params=None,pause=0.25,tries=6):
            err=""
            for k in range(tries):
                try: r=requests.get(url,params=params,headers=fetch.UA,timeout=90)
                except requests.RequestException as ex: r=None; err=str(ex)
                if r is not None and r.status_code==200: time.sleep(pause); return r
                if r is not None and 400<=r.status_code<500 and r.status_code!=429: raise RuntimeError("HTTP %d (not retried) %s"%(r.status_code,url[-80:]))
                wait=min(300,10*2**k); err=err if r is None else "HTTP %d"%r.status_code
                print("  retry in %ds (%s) %s"%(wait,err,url[-60:])); time.sleep(wait)
            raise RuntimeError("giving up on "+url)
        fetch.get=get; fetch._plan3=True
    return fetch
def jsonl(name):
    """Rows of a data file; a half-written last line (an interrupted run) is skipped. Other bad lines stop the run."""
    p=os.path.join(DATA,name)
    if not os.path.exists(p): return []
    lines=[l for l in open(p,encoding="utf-8") if l.strip()]; out=[]
    for i,l in enumerate(lines):
        try: out.append(json.loads(l))
        except ValueError:
            if i==len(lines)-1: print("note: skipped a half-written last line in",name); continue
            raise
    return out
def best_rows(rows):
    """One row per ticker: the one with the most candles (a market with none is fetched again on the next run)."""
    out={}
    for r in rows:
        if r["ticker"] not in out or (r.get("n_candles") or 0)>=(out[r["ticker"]].get("n_candles") or 0): out[r["ticker"]]=r
    return out
MAX_NO_CANDLES=0.02   # at most 2% of markets may come back from Kalshi with no candles (after a retry); they are listed
def now(): return datetime.now().isoformat(timespec="minutes")
def once(name):
    p=os.path.join(OUT,name)
    if os.path.exists(p): sys.exit("%s already exists: PLAN3 scores each test once. A re-score after a bug fix must be logged in CHANGELOG and written under a new name."%p)
    return p
def utc0(d): return calendar.timegm((d.year,d.month,d.day,0,0,0))

# ---------- statistics ----------
def daystat(ts,key="pnl"):
    """Mean of the market-day means, standard error over days, and their ratio."""
    by={}
    for t in ts: by.setdefault(t["day"],[]).append(t[key])
    dm=[sum(v)/len(v) for v in by.values()]; D=len(dm)
    if not D: return dict(n=len(ts),days=0,mean=None,se=None,t=None)
    mu=sum(dm)/D; se=(sum((x-mu)**2 for x in dm)/(D-1)/D)**0.5 if D>1 else None
    t=(mu/se) if se else (math.copysign(float("inf"),mu) if se==0 and mu!=0 else None)
    return dict(n=len(ts),days=D,mean=mu,se=se,t=t)
def upper95(k,n):
    """One-sided 95% upper bound on a binomial rate (exact, Clopper-Pearson): the p with P(X <= k | n, p) = 0.05."""
    if n==0 or k>=n: return 1.0
    lo,hi=k/n,1.0
    for _ in range(100):
        p=(lo+hi)/2
        if betainc(n-k,k+1,1-p)>0.05: lo=p   # P(X <= k) = I_{1-p}(n-k, k+1)
        else: hi=p
    return (lo+hi)/2
def c(x,d=1): return "n/a" if x is None else ("%+."+str(d)+"fc")%(100*x)
def f2(x): return "n/a" if x is None else ("%.2f"%x if abs(x)!=float("inf") else ("inf" if x>0 else "-inf"))

# ================= Test A: late-day temperature =================
def stations_A(): return json.load(open(os.path.join(OUT,"temp_model.json"),encoding="utf-8"))["stations"]
def asos():
    F=fx()
    for st in stations_A():
        out=os.path.join(DATA,"asos",st+".json")
        if os.path.exists(out) and json.load(open(out,encoding="utf-8")): continue
        r=F.get(F.IEM+"/cgi-bin/request/asos.py",[("station",st[1:]),("data","tmpf"),("sts","2026-06-30T00:00:00Z"),("ets","2026-10-15T00:00:00Z"),
                ("tz","Etc/UTC"),("format","onlycomma"),("latlon","no"),("elev","no"),("missing","empty"),("trace","empty"),("direct","no"),
                ("report_type","3"),("report_type","4")],pause=3)
        rows=[]
        for x in csv.DictReader(io.StringIO(r.text)):
            v,t=x.get("tmpf"),x.get("valid")
            try: rows.append([calendar.timegm(datetime.strptime(t[:16],"%Y-%m-%d %H:%M").timetuple()),float(v)])
            except (TypeError,ValueError): continue
        if rows: F.save(out,rows)
        print("  ASOS",st,len(rows),"readings" if rows else "readings (nothing saved; run again)")
    have=load_asos(); miss=[st for st in stations_A() if not have.get(st)]
    for st in stations_A():
        if have.get(st): print("  %s: %.1f reports a day"%(st,len(have[st])/((HOLD[1]-HOLD[0]).days+3)))
    if miss: sys.exit("asos incomplete: no readings for %s (run again)"%", ".join(miss))
    print("asos done")
def load_asos():
    return {os.path.basename(p)[:-5]:sorted(tuple(x) for x in json.load(open(p,encoding="utf-8"))) for p in glob.glob(os.path.join(DATA,"asos","*.json"))}
def markets_A():
    sts=set(stations_A())
    return [m for m in jsonl("kalshi_temp.jsonl") if m["station"] in sts and HOLD[0]<=bt.d(m["day"])<=HOLD[1] and m.get("result") in ("yes","no")]
def decided(kind,fl,cap,M):
    """The side that the running maximum M already settles (only calls a rising maximum can make), else None."""
    if M is None: return None
    if kind=="greater" and fl is not None and M>=fl+2: return "yes"
    if kind=="between" and cap is not None and M>=cap+2: return "no"
    if kind=="less" and cap is not None and M>=cap+1: return "no"
    return None
def looks(m,obs,tz):
    """The three looks for one market: decision time (UTC), M so far, reports in the 3 hours before, decided side."""
    d=bt.d(m["day"]); mid=utc0(d)+tz[m["station"][1:]]*3600; out=[]   # local-standard-time midnight
    for L in LOOKS:
        dec=mid+L*3600; seg=obs[bisect.bisect_left(obs,(mid,-1e9)):bisect.bisect_right(obs,(dec,1e9))] if obs else []
        M=max(v for _,v in seg) if seg else None; n3=len({t for t,_ in seg if t>dec-3*3600})   # distinct report times
        side=decided(m.get("strike_type"),b2.flt(m.get("floor")),b2.flt(m.get("cap")),M) if n3>=MIN_REPORTS else None
        out.append(dict(look=L,dec=dec,M=M,reports3h=n3,thin=n3<MIN_REPORTS,side=side))
    return out
def quote_at(cs,t):
    """The standing quote at t: the last candle ending at or before t -> (end, yes_bid close, yes_ask close)."""
    F=fx(); s=[k for k in cs if k["end_period_ts"]<=t]
    if not s: return dict(end=None,bid=None,ask=None)
    k=s[-1]; return dict(end=k["end_period_ts"],bid=F._v(k.get("yes_bid"),"close"),ask=F._v(k.get("yes_ask"),"close"))
def fetch_candles(F,req):
    """fetch.candles for a day's markets; if the batch fails, or a market comes back missing or empty, that market is
    asked for again on its own (live, then the historical archive, where Kalshi moves old markets)."""
    try: cs=F.candles(req)
    except Exception as ex: print("  batch request failed (%s): asking one market at a time"%ex); cs={}
    for t,h,s0,e0 in req:
        if cs.get(t): continue
        got=[]
        for hist in ([True] if h else [False,True]):
            try: got=F.candles([(t,hist,s0,e0)]).get(t) or []
            except Exception as ex: print("  no candles for %s from the %s endpoint: %s"%(t,"historical" if hist else "live",ex))
            if got: break
        cs[t]=got
    return cs
def candlesA():
    F=fx(); obs=load_asos(); path=os.path.join(DATA,"kalshi_temp_looks.jsonl"); done=set()
    if not obs: sys.exit("No airport readings yet: python research/plan3.py asos")
    done={t for t,r in best_rows(jsonl("kalshi_temp_looks.jsonl")).items() if r.get("n_candles")}   # markets with no candles are asked again
    byday={}; n=0
    for m in markets_A():
        if m["ticker"] in done: continue
        lk=looks(m,obs.get(m["station"]),F.TZ); first=[x for x in lk if x["side"]]
        if first: byday.setdefault(m["day"],[]).append((m,lk,first[0]["dec"])); n+=1
    print("markets decided at some look, quotes to fetch:",n)
    with open(path,"a",encoding="utf-8") as f:
        for day,items in sorted(byday.items()):
            # Kalshi stamps the "latest candle before the start" at the window's start, so the window starts an hour before
            # the 60-minute freshness limit: a quote older than that limit can never look fresh
            cs=fetch_candles(F,[(m["ticker"],m.get("hist",False),d0+LAG-FRESH-3600,lk[-1]["dec"]+LAG) for m,lk,d0 in items])
            for m,lk,d0 in items:
                k=sorted(cs.get(m["ticker"]) or [],key=lambda x:x["end_period_ts"])
                f.write(json.dumps(dict(ticker=m["ticker"],n_candles=len(k),quotes=[dict(look=x["look"],**quote_at(k,x["dec"]+LAG)) for x in lk]))+"\n")
            f.flush(); print("  day",day,len(items))
    print("candlesA done ->",path)
def scoreA():
    F=fx(); res_json=once("plan3_A.json")
    obs=load_asos(); ms=markets_A(); Q=best_rows(jsonl("kalshi_temp_looks.jsonl")); cli=b2.load_cli()
    if not obs or not Q: sys.exit("Fetch first: python research/plan3.py asos, then candlesA")
    # completeness, before anything is scored (PLAN3 revision 2026-10-15)
    miss=[st for st in stations_A() if not obs.get(st)]
    if miss: sys.exit("Not scored: no airport readings for %s. Run asos again."%", ".join(miss))
    dec_ms=[m for m in ms if any(x["side"] for x in looks(m,obs[m["station"]],F.TZ))]
    noq=[m["ticker"] for m in dec_ms if m["ticker"] not in Q]
    if noq: sys.exit("Not scored: %d decided markets have no quote row yet (e.g. %s). Run candlesA again."%(len(noq),", ".join(noq[:5])))
    empty=[m["ticker"] for m in dec_ms if not Q[m["ticker"]].get("n_candles")]
    if len(empty)>MAX_NO_CANDLES*len(dec_ms): sys.exit("Not scored: %d of %d decided markets came back with no candles (more than 2%%). Run candlesA again."%(len(empty),len(dec_ms)))
    bad=[t for t,r in Q.items() for z in r["quotes"] for v in (z.get("bid"),z.get("ask")) if v is not None and not 0<=v<=1]
    if bad: sys.exit("Not scored: quotes outside 0..1 (a format problem), e.g. %s"%bad[:3])
    looks_n=dict(total=0,thin_reports=0); look_skip=dict(no_quote=0,stale_quote=0,no_offer=0,above_cap=0)
    trades=[]; never=dict(no_asos=0,no_candles=0,above_cap_every_look=0,other=0); decided_n=0; dlost=[]
    for m in ms:
        o=obs.get(m["station"])
        if not o: never["no_asos"]+=1; continue
        lk=looks(m,o,F.TZ); looks_n["total"]+=len(lk); looks_n["thin_reports"]+=sum(x["thin"] for x in lk)
        dl=[x for x in lk if x["side"]]
        if not dl: continue
        decided_n+=1; q=Q.get(m["ticker"])
        dl0=dl[0]; dlost.append(dict(day=m["day"],station=m["station"],lost=m["result"]!=dl0["side"],ticker=m["ticker"],side=dl0["side"],look=dl0["look"],M=dl0["M"]))
        if q is None or not q.get("n_candles"): never["no_candles"]+=1; continue
        qq={z["look"]:z for z in q["quotes"]}; taken=None; why=[]
        for x in dl:
            z=qq.get(x["look"]) or {}
            if z.get("end") is None: why.append("no_quote"); continue
            if z["end"]<x["dec"]+LAG-FRESH: why.append("stale_quote"); continue
            if x["side"]=="yes": a=z.get("ask"); p=a if a is not None and 0<a<1 else None
            else: b=z.get("bid"); p=round(1-b,4) if b is not None and 0<b<1 else None
            if p is None: why.append("no_offer"); continue
            if p>CAP+1e-9: why.append("above_cap"); continue
            taken=(x,p); break
        for w in why: look_skip[w]+=1
        if not taken:
            never["above_cap_every_look" if why and all(w=="above_cap" for w in why) else "other"]+=1; continue
        x,p=taken; won=m["result"]==x["side"]; fe=bt.fee(p); ch=cli.get((m["station"],bt.d(m["day"])))
        fl,cp=b2.flt(m.get("floor")),b2.flt(m.get("cap")); hi=ch[1] if ch else None; cy=b2.cli_yes(m["strike_type"],fl,cp,hi)
        trades.append(dict(ticker=m["ticker"],day=m["day"],station=m["station"],kind=m["strike_type"],floor=fl,cap=cp,look=x["look"],M=x["M"],
                           side=x["side"],price=p,fee=fe,won=won,pnl=(1 if won else 0)-p-fe,cli_high=hi,
                           cli_agrees=None if cy is None else (cy==(x["side"]=="yes"))))
    n=len(trades); S=daystat(trades); lost=[t for t in trades if not t["won"]]
    mp=bt.mean([t["price"] for t in trades]) if n else None; mf=bt.mean([t["fee"] for t in trades]) if n else None
    be=(1-mp-mf) if n else None; ub=upper95(len(lost),n)
    loso={s:daystat([t for t in trades if t["station"]!=s]) for s in sorted({t["station"] for t in trades})}
    ok1=S["t"] is not None and S["mean"]>0 and S["t"]>=BAR
    ok2=n>=200 and S["days"]>=40
    ok3=n>0 and len(lost)/n<0.02 and ub<be
    ok4=ok1 and all(v["t"] is not None and v["mean"]>0 and v["t"]>=BAR for v in loso.values())
    by=lambda f:{k:daystat([t for t in trades if f(t)==k]) for k in sorted({f(t) for t in trades},key=str)}
    sd={}   # losses cluster by station-day (one bad reading decides several strikes): count station-days too
    for t in trades: sd.setdefault((t["station"],t["day"]),[]).append(t["won"])
    sd_lost=sum(1 for v in sd.values() if not all(v))
    R=dict(plan="research/PLAN3.md test A",scored=now(),markets=len(ms),decided_markets=decided_n,looks=looks_n,look_skips=look_skip,not_traded=never,
           trades=n,days=S["days"],profit_per_contract=S["mean"],se=S["se"],t=S["t"],lost=len(lost),loss_rate=(len(lost)/n if n else None),
           loss_rate_upper95=ub,break_even_loss_rate=be,mean_price=mp,mean_fee=mf,leave_one_station_out=loso,
           by_look=by(lambda t:t["look"]),by_kind=by(lambda t:t["kind"]),by_station=by(lambda t:t["station"]),
           cli_disagrees=[t for t in trades if t["cli_agrees"] is False],losses=lost,
           decided_all=dict(markets=len(dlost),lost=sum(x["lost"] for x in dlost),lost_list=[x for x in dlost if x["lost"]]),
           station_days=dict(traded=len(sd),with_a_loss=sd_lost,upper95=upper95(sd_lost,len(sd))),trade_list=trades,
           conditions=dict(profit_2_5_se=ok1,enough_trades_and_days=ok2,rare_losses=ok3,survives_leaving_out_each_station=ok4),
           verdict="PASS" if ok1 and ok2 and ok3 and ok4 else "FAIL")
    os.makedirs(OUT,exist_ok=True); json.dump(R,open(res_json,"w",encoding="utf-8"),indent=1,default=str)
    L=["# PLAN3 test A: late-day temperature (scored once, %s)"%R["scored"],"",
       "Rules: research/PLAN3.md. %d settled KXHIGH markets (2026-07-01..2026-10-13, 24 stations); %d were decided at some look by the airport readings; %d trades (one contract each) on %d market days."%(len(ms),decided_n,n,S["days"]),"",
       "**Verdict: %s.**"%R["verdict"],"",
       "| Condition | Needed | Result | Met |","|---|---|---|---|",
       "| Profit per contract after fees (day-averaged) | above 0 by 2.5 SE | %s +/- %s (t %s) | %s |"%(c(S["mean"],2),c(S["se"],2).lstrip("+"),f2(S["t"]),"yes" if ok1 else "no"),
       "| Trades and market days | 200 and 40 | %d and %d | %s |"%(n,S["days"],"yes" if ok2 else "no"),
       "| Losses | under 2%%, and the 95%% upper bound below break-even | %d of %d (%s), upper bound %s vs break-even %s | %s |"%(len(lost),n,"%.2f%%"%(100*len(lost)/n) if n else "n/a",
            "%.2f%%"%(100*ub),"%.2f%%"%(100*be) if be is not None else "n/a","yes" if ok3 else "no"),
       "| Leave out each station | condition 1 still holds | weakest t %s | %s |"%(f2(min((v["t"] for v in loso.values() if v["t"] is not None),default=None)),"yes" if ok4 else "no"),"",
       "Mean price paid %s, mean fee %s. Decided markets never traded: %s. Looks skipped (a market can count at several looks): %s; looks with fewer than 3 reports in the 3 hours before: %d of %d."%(
           "%.1fc"%(100*mp) if mp is not None else "n/a","%.2fc"%(100*mf) if mf is not None else "n/a",", ".join("%s %d"%kv for kv in never.items()),", ".join("%s %d"%kv for kv in look_skip.items()),looks_n["thin_reports"],looks_n["total"]),"",
       "## Descriptive (not part of the verdict)",""]
    for title,key in (("By look (local standard time)","by_look"),("By strike type","by_kind"),("By station","by_station")):
        L+=["### "+title,"","| Group | Trades | Days | Profit per contract (+/- SE) |","|---|---:|---:|---:|"]
        L+=["| %s | %d | %d | %s%s |"%(k,v["n"],v["days"],c(v["mean"],2),(" +/- %s"%c(v["se"],2).lstrip("+")) if v["se"] else "") for k,v in R[key].items()]; L.append("")
    L+=["### Losses (read by hand; nothing is excluded after scoring)","","| Ticker | Side | Look | M | CLI high | Price | Kalshi result |","|---|---|---:|---:|---:|---:|---|"]
    L+=["| %s | %s | %d:00 | %.1f | %s | %.2f | %s |"%(t["ticker"],t["side"].upper(),t["look"],t["M"],t["cli_high"],t["price"],"NO" if t["side"]=="yes" else "YES") for t in lost] or ["| none | | | | | | |"]
    L+=["","Trades where the NWS climate report disagrees with the decided side: %d%s."%(len(R["cli_disagrees"]),(" ("+", ".join(t["ticker"] for t in R["cli_disagrees"][:20])+")") if R["cli_disagrees"] else ""),
        "Every decided market, traded or not (first decided look): %d, of which %d settled against the decided side%s."%(len(dlost),R["decided_all"]["lost"],
            (" ("+", ".join(x["ticker"] for x in R["decided_all"]["lost_list"][:20])+")") if R["decided_all"]["lost"] else ""),
        "Station-days traded: %d, with at least one loss: %d (95%% upper bound %.2f%%; losses can cluster within a station-day)."%(len(sd),sd_lost,100*R["station_days"]["upper95"])]
    open(os.path.join(OUT,"plan3_A.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L[:16]))

# ================= Test B: low-temperature markets with limit orders =================
LOWM=os.path.join(DATA,"low_markets.json")
def low_series(F):
    """KXLOWT series from Kalshi's series list, merged with the inventory snapshot's (either may be incomplete)."""
    s=set()
    try:
        j=F.get(F.KALSHI_BASE+"/series",dict(category="Climate and Weather")).json()
        s|={x["ticker"] for x in j.get("series",[]) if x.get("ticker","").startswith("KXLOWT")}
    except Exception as ex: print("series list failed:",ex)
    inv=os.path.join(OUT,"inventory.json")
    if os.path.exists(inv): s|={x["series"] for x in json.load(open(inv,encoding="utf-8"))["series"] if x["series"].startswith("KXLOWT")}
    return sorted(s)
def lowlist():
    F=fx(); best={}; series=low_series(F); print("low-temperature series:",len(series),series)
    for se in series:
        n=0
        for path_,extra in (("/historical/markets",{}),("/markets",{"status":"settled"})):
            cur=None
            while True:
                j=F.get(F.KALSHI_BASE+path_,dict(series_ticker=se,limit=1000,cursor=cur,**extra)).json()
                for m in j.get("markets",[]):
                    try: d=F.mday(m["ticker"])
                    except (ValueError,IndexError): continue
                    st=F.station_of(m)
                    if d<HOLD[0] or d>HOLD[1] or m.get("result") not in ("yes","no") or not st: continue
                    m["_hist"]=path_.startswith("/historical"); n+=1
                    k=(d.isoformat(),st,m.get("strike_type"),m.get("floor_strike"),m.get("cap_strike"))
                    if k not in best or float(m.get("volume_fp") or 0)>float(best[k].get("volume_fp") or 0): best[k]=m
                cur=j.get("cursor")
                if not cur: break
        print("  ",se,n,"markets")
    rows=[dict(ticker=m["ticker"],series=m["ticker"].split("-")[0],day=k[0],station=k[1],result=m["result"],strike_type=k[2],floor=k[3],cap=k[4],
               rule_numbers=F.rules_strikes(m),volume=float(m.get("volume_fp") or 0),hist=m["_hist"],rules=(m.get("rules_primary") or "")[:300]) for k,m in best.items()]
    F.save(LOWM,rows)
    print("unique contracts:",len(rows),"| stations:",sorted({r["station"] for r in rows}),"| no time zone known (left out):",sorted({r["station"] for r in rows if r["station"][1:] not in F.TZ}))
def low_stations(F=None):
    tz=(F or fx()).TZ
    return sorted({r["station"] for r in json.load(open(LOWM,encoding="utf-8")) if r["station"][1:] in tz})
def lowiem():
    F=fx(); sts=low_stations(F)
    print("stations:",sts)
    F.stations=lambda:sts; F.nbs()   # nbs() skips months already fetched, so an interrupted run resumes
    for st in sts:
        for y in (bt.TRAIN[0].year,HOLD[1].year):
            out=os.path.join(DATA,"cli","%s_%d.json"%(st,y))
            if os.path.exists(out): continue
            j=F.get(F.IEM+"/json/cli.py",dict(station=st,year=str(y)),pause=3).json()
            F.save(out,[{k:x.get(k) for k in ("valid","precip","high","low","product")} for x in j.get("results",[])]); print("  CLI",st,y,len(j.get("results",[])))
    print("lowiem done")
def low_f(run,day):
    """(TXN, XND) valid 12 UTC on `day` (the overnight minimum) from one run. None if missing."""
    r=(run or {}).get("%s 12:00"%day)
    if not r: return None
    t,x=bt.num(r.get("txn")),bt.num(r.get("xnd"))
    return None if t is None or x is None else (t,x)
def load_cli_low():
    out={}
    for p in glob.glob(os.path.join(DATA,"cli","*.json")):
        st=os.path.basename(p).split("_")[0]
        for r in json.load(open(p,encoding="utf-8")):
            if r.get("valid"): out[(st,bt.d(r["valid"]))]=bt.num(r.get("low"))
    return out
def months(a,b):
    out=[]; d=date(a.year,a.month,1)
    while d<=b: out.append(d.strftime("%Y%m")); d=date(d.year+(d.month==12),d.month%12+1,1)
    return out
def low_files_missing(sts,days=None):
    """NBS month files and CLI year files that are not there yet. fetch.nbs names a file by the month of the market days
    it serves (each file starts with the last evening of the month before). days: [(station, date)] for the holdout
    markets; without it, every training month for every station."""
    if days is None: need={(st,m) for st in sts for m in months(*bt.TRAIN)}; years={(st,y) for st in sts for y in (bt.TRAIN[0].year,bt.TRAIN[1].year)}
    else: need={(st,d.strftime("%Y%m")) for st,d in days}; years={(st,d.year) for st,d in days}
    paths=[os.path.join("nbs","%s_%s.json"%k) for k in sorted(need)]+[os.path.join("cli","%s_%d.json"%k) for k in sorted(years)]
    return [p for p in paths if not os.path.exists(os.path.join(DATA,p))]
def fitB():
    mp=os.path.join(OUT,"low_model.json")
    if os.path.exists(mp): sys.exit("low_model.json is frozen (%s); PLAN3 never refits it."%json.load(open(mp,encoding="utf-8")).get("created"))
    sts=low_stations(); miss=low_files_missing(sts)
    if miss: sys.exit("Not frozen: data files missing (run lowiem): %s"%", ".join(miss[:12]))
    ev=b2.load_runs("nbs",b2.EVENING); tr=[]
    for (st,day),low in load_cli_low().items():   # the training year only; no holdout market is read here
        if st in sts and bt.TRAIN[0]<=day<=bt.TRAIN[1] and low is not None:
            tx=low_f(ev.get((st,day-timedelta(days=1))),day)
            if tx: tr.append((tx[0],tx[1],low))
    if len(tr)<1000: sys.exit("not enough training data: %d station-days (run lowiem?)"%len(tr))
    m=b2.fit_T(tr)
    model=dict(m,training="%s..%s"%bt.TRAIN,station_days=len(tr),stations=sts,form="low ~ Normal(TXN valid 12 UTC + a, s0 + s1*XND)",
               train_mean_error=bt.mean([h-t for t,x,h in tr]),train_mean_xnd=bt.mean([x for t,x,h in tr]),created=now())
    os.makedirs(OUT,exist_ok=True); json.dump(model,open(mp,"w",encoding="utf-8"),indent=1); print("frozen ->",mp,model)
def candlesB():
    F=fx()
    if not os.path.exists(os.path.join(OUT,"low_model.json")): sys.exit("Fit and freeze the low model first: python research/plan3.py fitB")
    path=os.path.join(DATA,"kalshi_low.jsonl")
    done={t for t,r in best_rows(jsonl("kalshi_low.jsonl")).items() if r.get("n_candles")}   # markets with no candles are asked again
    byday={}
    for r in json.load(open(LOWM,encoding="utf-8")):
        if r["station"][1:] in F.TZ and r["ticker"] not in done: byday.setdefault(r["day"],[]).append(r)
    with open(path,"a",encoding="utf-8") as f:
        for day,items in sorted(byday.items()):
            d=bt.d(day); scan=F.utc(d,0,55)
            cs=fetch_candles(F,[(r["ticker"],r["hist"],scan-3600,F.utc(d,F.TZ[r["station"][1:]])) for r in items])
            for r in items:
                k=sorted(cs.get(r["ticker"]) or [],key=lambda x:x["end_period_ts"]); w0=F.utc(d,F.TZ[r["station"][1:]]); q=quote_at(k,scan)
                after=[x for x in k if x["end_period_ts"]-60>=scan and x["end_period_ts"]<=w0]   # whole minutes after the scan, to the day start
                lo=[v for v in (F._v(x.get("price"),"low") for x in after) if v is not None]; hi=[v for v in (F._v(x.get("price"),"high") for x in after) if v is not None]
                f.write(json.dumps(dict(ticker=r["ticker"],scan_ts=scan,start_ts=w0,scan_bid=q["bid"],scan_ask=q["ask"],scan_age=(scan-q["end"]) if q["end"] else None,
                                        trade_lo=min(lo) if lo else None,trade_hi=max(hi) if hi else None,n_candles=len(k)))+"\n")
            f.flush(); print("  day",day,len(items))
    print("candlesB done ->",path)
def maker(fair,bid,ask,tlo,thi):
    """The bot's limit-order rule (backtest2.entries): 1c better than the best bid when the spread allows, else join;
    filled only if a later trade went through our price (quotes do not count)."""
    yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
    side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
    if q-price<b2.EDGE-1e-9 or not 0<price<1: return None
    filled=(tlo is not None and tlo<price-1e-9) if side=="yes" else (thi is not None and thi>(1-price)+1e-9)
    return side,price,filled
def taker(fair,bid,ask):
    side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
    return (side,price) if q-price>=b2.EDGE-1e-9 else None
def scoreB():
    res_json=once("plan3_B.json"); mp=os.path.join(OUT,"low_model.json")
    if not os.path.exists(mp): sys.exit("No frozen low model: python research/plan3.py fitB")
    model=json.load(open(mp,encoding="utf-8")); meta={r["ticker"]:r for r in json.load(open(LOWM,encoding="utf-8"))}
    tz=fx().TZ; want=[t for t,m in meta.items() if m["station"][1:] in tz]; Q=best_rows(jsonl("kalshi_low.jsonl"))
    # completeness and data checks, before anything is scored (PLAN3 revision 2026-10-15)
    noq=[t for t in want if t not in Q]
    if noq: sys.exit("Not scored: %d low markets have no quote row yet (e.g. %s). Run candlesB again."%(len(noq),", ".join(noq[:5])))
    empty=[t for t in want if not Q[t].get("n_candles")]
    if len(empty)>MAX_NO_CANDLES*len(want): sys.exit("Not scored: %d of %d low markets came back with no candles (more than 2%%). Run candlesB again."%(len(empty),len(want)))
    miss=low_files_missing(None,[(meta[t]["station"],bt.d(meta[t]["day"])) for t in want])
    if miss: sys.exit("Not scored: data files missing (run lowiem): %s"%", ".join(miss[:12]))
    lows=load_cli_low(); agree=[0,0]; rules_bad=0; byday={}
    for t in want:
        m=meta[t]; fl,cp=b2.flt(m.get("floor")),b2.flt(m.get("cap")); lo=lows.get((m["station"],bt.d(m["day"])))
        cy=b2.cli_yes(m["strike_type"],fl,cp,lo)
        if cy is not None: agree[0]+=1; agree[1]+=(cy==(m["result"]=="yes"))
        w={"greater":[fl],"less":[cp],"between":[fl,cp]}.get(m["strike_type"])
        if w is not None and [float(x) for x in (m.get("rule_numbers") or [])]!=w: rules_bad+=1
        byday.setdefault((m["day"],m["station"]),[]).append(m["result"]=="yes")
    yes={}
    for v in byday.values():
        if len(v)>=5: k=sum(v); yes[k]=yes.get(k,0)+1
    checks=dict(cli_compared=agree[0],cli_agrees=agree[1],cli_agree_rate=(agree[1]/agree[0]) if agree[0] else None,rules_strike_mismatch=rules_bad,
                yes_count_in_city_days_with_5_or_more_markets={str(k):v for k,v in sorted(yes.items())},no_candles=len(empty))
    print("data checks:",checks)
    if agree[0] and agree[1]/agree[0]<0.95: sys.exit("Not scored: Kalshi's results agree with the climate-report lows in only %.1f%% of markets, so the strike reading is probably wrong. Fix the code (not the rule) first."%(100*agree[1]/agree[0]))
    ev=b2.load_runs("nbs",b2.EVENING); rows=[]; skip=dict(strikes=0,quote=0,forecast=0,no_candles=0)
    for t in want:
        q=Q[t]; m=meta[t]; kind=m["strike_type"]; fl,cp=b2.flt(m.get("floor")),b2.flt(m.get("cap"))
        if not q.get("n_candles"): skip["no_candles"]+=1; continue
        if b2.p_temp(kind,fl,cp,50.0,3.0) is None: skip["strikes"]+=1; continue
        b,a=q.get("scan_bid"),q.get("scan_ask")
        if not (b is not None and a is not None and 0<b<a<1): skip["quote"]+=1; continue
        day=bt.d(m["day"]); tx=low_f(ev.get((m["station"],day-timedelta(days=1))),day)
        if not tx: skip["forecast"]+=1; continue
        P=b2.p_temp(kind,fl,cp,tx[0]+model["a"],model["s0"]+model["s1"]*tx[1])
        rows.append(dict(ticker=m["ticker"],day=m["day"],station=m["station"],y=1 if m["result"]=="yes" else 0,P=P,M=(a+b)/2,bid=b,ask=a,lo=q.get("trade_lo"),hi=q.get("trade_hi")))
    days=sorted({r["day"] for r in rows})
    R=dict(plan="research/PLAN3.md test B",scored=now(),model={k:model[k] for k in ("a","s0","s1","station_days","created")},usable_markets=len(rows),days=len(days),skipped=skip,data_checks=checks,
           spread_median=sorted(r["ask"]-r["bid"] for r in rows)[len(rows)//2] if rows else None)
    L=["# PLAN3 test B: low-temperature markets with limit orders (scored once, %s)"%R["scored"],"","Rules: research/PLAN3.md. Frozen model %s (a %.2f, s0 %.2f, s1 %.2f; fitted on %d training station-days)."%(
        model.get("created"),model["a"],model["s0"],model["s1"],model["station_days"]),""]
    if len(days)<40:
        R["verdict"]="NOT TESTABLE"; R["note"]="fewer than 40 market days with a usable quote and forecast; the window is not extended (PLAN3)"
        json.dump(R,open(res_json,"w",encoding="utf-8"),indent=1,default=str)
        L+=["**Verdict: not testable.** Only %d market days had a usable quote and forecast (%d markets); PLAN3 needs 40 and does not extend the window. Skipped: %s."%(len(days),len(rows),skip)]
        open(os.path.join(OUT,"plan3_B.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L)); return
    fills=[]; plac=[]; tak=[]; sig=0; psig=0
    for r in rows:
        fair=b2.BLEND*r["P"]+(1-b2.BLEND)*r["M"]
        e=maker(fair,r["bid"],r["ask"],r["lo"],r["hi"])
        if e: sig+=1
        if e and e[2]: won=(r["y"]==1)==(e[0]=="yes"); fills.append(dict(day=r["day"],side=e[0],price=e[1],pnl=(1 if won else 0)-e[1]))
        z=maker(r["M"],r["bid"],r["ask"],r["lo"],r["hi"])   # placebo: the forecast replaced by the mid
        if z: psig+=1
        if z and z[2]: won=(r["y"]==1)==(z[0]=="yes"); plac.append(dict(day=r["day"],side=z[0],price=z[1],pnl=(1 if won else 0)-z[1]))
        t=taker(fair,r["bid"],r["ask"])
        if t: won=(r["y"]==1)==(t[0]=="yes"); tak.append(dict(day=r["day"],pnl=(1 if won else 0)-t[1]-bt.fee(t[1])))
    S=daystat(fills); ok1=S["n"]>=150 and S["days"]>=40 and S["t"] is not None and S["mean"]>0 and S["t"]>=BAR
    br=[dict(day=r["day"],d=(r["P"]-r["y"])**2-(r["M"]-r["y"])**2) for r in rows]; Bs=daystat(br,"d")
    ok2=Bs["t"] is not None and Bs["mean"]<0 and Bs["t"]<=-2
    usable={}; gain={}; pg={}
    for r in rows: usable[r["day"]]=usable.get(r["day"],0)+1
    for x in fills: gain[x["day"]]=gain.get(x["day"],0)+x["pnl"]
    for x in plac: pg[x["day"]]=pg.get(x["day"],0)+x["pnl"]
    Ds=daystat([dict(day=d,v=(gain.get(d,0)-pg.get(d,0))/usable[d]) for d in days],"v"); ok3=Ds["t"] is not None and Ds["mean"]>0 and Ds["t"]>=2
    P0=daystat(plac); T0=daystat(tak)
    R.update(maker=dict(signals=sig,fills=len(fills),fill_rate=len(fills)/sig if sig else None,profit_per_order_posted=sum(x["pnl"] for x in fills)/sig if sig else None,**S),
             maker_by_side={s:daystat([x for x in fills if x["side"]==s]) for s in ("yes","no")},
             brier=dict(forecast=bt.mean([(r["P"]-r["y"])**2 for r in rows]),market=bt.mean([(r["M"]-r["y"])**2 for r in rows]),**Bs),
             vs_placebo=Ds,placebo=dict(signals=psig,fills=len(plac),**P0),taker=T0,
             conditions=dict(maker_profit_2_5_se=ok1,brier_clear=ok2,beats_placebo=ok3),verdict="PASS" if ok1 and ok2 and ok3 else "FAIL")
    json.dump(R,open(res_json,"w",encoding="utf-8"),indent=1,default=str)
    L+=["%d usable markets on %d market days (quote 0 < bid < ask < 1 at 00:55 UTC, forecast present); median spread %.0fc. Skipped: %s."%(len(rows),len(days),100*R["spread_median"],", ".join("%s %d"%kv for kv in skip.items())),"",
        "**Verdict: %s.**"%R["verdict"],"","| Condition | Needed | Result | Met |","|---|---|---|---|",
        "| Limit-order profit per contract (day-averaged) | above 0 by 2.5 SE, 150 fills, 40 days | %s +/- %s (t %s), %d fills on %d days | %s |"%(c(S["mean"]),c(S["se"]).lstrip("+"),f2(S["t"]),S["n"],S["days"],"yes" if ok1 else "no"),
        "| Forecast Brier minus market Brier | below 0 by 2 SE | %+.4f +/- %.4f (t %s); forecast %.4f, market %.4f | %s |"%(Bs["mean"],Bs["se"] or 0,f2(Bs["t"]),R["brier"]["forecast"],R["brier"]["market"],"yes" if ok2 else "no"),
        "| Beats the placebo (forecast replaced by the mid), per usable market and day | above 0 by 2 SE | %s +/- %s (t %s) | %s |"%(c(Ds["mean"],2),c(Ds["se"],2).lstrip("+"),f2(Ds["t"]),"yes" if ok3 else "no"),"",
        "Limit orders: %d signals, %d filled (%s), profit per order posted %s. A fail cannot rule out a 2-3c edge (PLAN3 power note)."%(sig,len(fills),"%.0f%%"%(100*len(fills)/sig) if sig else "n/a",c(R["maker"]["profit_per_order_posted"],2)),"",
        "## Descriptive (not part of the verdict)","",
        "- By side: "+"; ".join("%s %d fills %s"%(s.upper(),v["n"],c(v["mean"])) for s,v in R["maker_by_side"].items()),
        "- Placebo: %d signals, %d filled, %s per contract."%(psig,len(plac),c(P0["mean"])),
        "- Paying the ask (taker, with fees): %d trades, %s per contract%s."%(T0["n"],c(T0["mean"]),(" +/- %s"%c(T0["se"]).lstrip("+")) if T0["se"] else "")]
    open(os.path.join(OUT,"plan3_B.md"),"w",encoding="utf-8").write("\n".join(L)+"\n"); print("\n".join(L))

if __name__=="__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    cmds=dict(asos=asos,candlesA=candlesA,scoreA=scoreA,lowlist=lowlist,lowiem=lowiem,fitB=fitB,candlesB=candlesB,scoreB=scoreB)
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd not in cmds: sys.exit(__doc__)
    cmds[cmd]()
