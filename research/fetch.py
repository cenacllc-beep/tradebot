"""Backtest data collector (research only; never touches paper.db). Python 3.8+, requests only.
  python research/fetch.py kalshi   settled KXRAIN markets + prices around scan time  -> research/data/kalshi_rain.jsonl
  python research/fetch.py nbs      NBM station guidance (NBS, 18 UTC runs) from IEM   -> research/data/nbs/STATION_YYYYMM.json
  python research/fetch.py cli      NWS daily climate reports (CLI) from IEM           -> research/data/cli/STATION_YEAR.json
  python research/fetch.py temp     settled KXHIGH markets (PLAN2.md), quotes at 00:55 and 03:30 UTC -> research/data/kalshi_temp.jsonl
  python research/fetch.py late     rain markets again, quote at 03:30 UTC (PLAN2.md)   -> research/data/kalshi_rain_late.jsonl
  python research/fetch.py nbslate  NBS 00/01 UTC runs for Jul-Oct 2026 (PLAN2.md)      -> research/data/nbs_late/STATION_YYYYMM.json
Resumable: finished files are skipped. Polite: one request at a time, pauses, backs off on HTTP 429/5xx.
User-Agent is tradebot-paper-research/1.0 and no personal data is sent (CLAUDE.md). See research/PLAN.md."""
import os, sys, json, time, csv, io, re, calendar
from datetime import datetime, date, timedelta, timezone
import requests
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.dirname(HERE))
from config import KALSHI_BASE
DATA=os.path.join(HERE,"data"); IEM="https://mesonet.agron.iastate.edu"; UA={"User-Agent":"tradebot-paper-research/1.0"}
# Local STANDARD time offset (hours behind UTC) for each station, used for the market day (CLI days are local standard time)
TZ={**{s:5 for s in "ATL BOS BWI CLT CMH CVG DCA DTW EWR IAD IND JAX JFK LGA LEX MCO MIA ORF PHL PIT PVD RDU RIC SDF TPA TTN CLE BDL BUF ALB NYC DJT".split()},
    **{s:6 for s in "AUS BNA CLL DAL DFW HOU IAH MCI MDW MEM MKE MSP MSY OKC ORD SAT SGF STL TUL OMA ICT".split()},
    **{s:7 for s in "ABQ DEN PHX SLC TUS ELP BOI".split()},**{s:8 for s in "LAX LAS PDX SAN SEA SFO SJC SMF OAK".split()}}
TRAIN=(date(2025,7,1),date(2026,6,30)); HOLD2=date(2026,7,1)   # plan 2 holdout starts after the training year
def get(url,params=None,pause=0.25,tries=6):
    for k in range(tries):
        try: r=requests.get(url,params=params,headers=UA,timeout=90)
        except requests.RequestException as ex: r=None; err=str(ex)
        if r is not None and r.status_code==200: time.sleep(pause); return r
        wait=min(300,10*2**k); err=err if r is None else "HTTP %d"%r.status_code
        print("  retry in %ds (%s) %s"%(wait,err,url[-60:])); time.sleep(wait)
    raise RuntimeError("giving up on "+url)
def save(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True); tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(obj,f)
    os.replace(tmp,path)
def _v(d,k):
    if not d: return None
    v=d.get(k+"_dollars",d.get(k))
    try: return None if v in (None,"") else float(v)
    except (TypeError,ValueError): return None
def station_of(m):
    """Station from the rules: "at CLIxxx" or "(CLIxxx)" in rules_primary; temperature markets before mid-August 2026
    name only the place there ("at Houston") and give the code in rules_secondary ("Data for CLIHOU can be found")."""
    p=m.get("rules_primary") or ""
    s=re.search(r"\bat (CLI[A-Z]{3})\b",p) or re.search(r"\((CLI[A-Z]{3})\)",p) or re.search(r"\bData for (CLI[A-Z]{3})\b",m.get("rules_secondary") or "")
    return ("K"+s.group(1)[3:]) if s else None
def mday(t): return datetime.strptime(t.split("-")[1],"%y%b%d").date()
def utc(d,h=0,mi=0): return calendar.timegm((d.year,d.month,d.day,h,mi,0))

# ---------------- Kalshi ----------------
def kalshi_markets():
    out={}
    for path,extra in (("/historical/markets",{}),("/markets",{"status":"settled"})):
        cur=None
        while True:
            j=get(KALSHI_BASE+path,dict(series_ticker="KXRAIN",limit=1000,cursor=cur,**extra)).json()
            for m in j.get("markets",[]):
                m["_hist"]=path.startswith("/historical"); out.setdefault(m["ticker"],m)
            cur=j.get("cursor")
            if not cur: break
    return list(out.values())
def summarize(cs,scan,w0):
    """Quote at scan, quote at the day start, and the extremes in whole minutes after the scan up to the day start."""
    cs=sorted(cs,key=lambda c:c["end_period_ts"]); at=lambda t:[c for c in cs if c["end_period_ts"]<=t]
    q=lambda c:(_v(c.get("yes_bid"),"close"),_v(c.get("yes_ask"),"close")) if c else (None,None)
    s=at(scan); w=at(w0); mid=[c for c in cs if c["end_period_ts"]-60>=scan and c["end_period_ts"]<=w0]
    lo=[v for c in mid for v in (_v(c.get("price"),"low"),_v(c.get("yes_ask"),"low")) if v is not None and v>0]
    hi=[v for c in mid for v in (_v(c.get("price"),"high"),_v(c.get("yes_bid"),"high")) if v is not None and v<1]
    vol=sum(float(c.get("volume_fp",c.get("volume")) or 0) for c in mid)
    (sb,sa),(wb,wa)=q(s[-1] if s else None),q(w[-1] if w else None)
    return dict(scan_bid=sb,scan_ask=sa,start_bid=wb,start_ask=wa,lo_after=min(lo) if lo else None,hi_after=max(hi) if hi else None,
                vol_between=vol,n_candles=len(cs),scan_age=(scan-s[-1]["end_period_ts"]) if s else None)
def kalshi():
    path=os.path.join(DATA,"kalshi_rain.jsonl"); done=set()
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: done={json.loads(l)["ticker"] for l in f if l.strip()}
    ms=kalshi_markets(); print("settled KXRAIN markets:",len(ms))
    best={}
    for m in ms:
        st=station_of(m)
        if not st or m.get("result") not in ("yes","no"): continue
        k=(mday(m["ticker"]),st); v=float(m.get("volume_fp") or 0)
        if k not in best or v>float(best[k].get("volume_fp") or 0): best[k]=m
    skip=sorted({k[1] for k in best if k[1][1:] not in TZ})
    todo=sorted([(k,m) for k,m in best.items() if m["ticker"] not in done and k[1][1:] in TZ],key=lambda x:x[0])
    print("unique (day, station):",len(best),"| to fetch:",len(todo),"| skipped, no time zone known:",skip)
    def row(d,st,m,cs):
        scan=utc(d,0,55); w0=utc(d,TZ[st[1:]])
        r=dict(ticker=m["ticker"],day=d.isoformat(),station=st,result=m["result"],close_time=m.get("close_time"),volume=float(m.get("volume_fp") or 0),
               scan_ts=scan,start_ts=w0,hist=m["_hist"]); r.update(summarize(cs,scan,w0)); return r
    os.makedirs(DATA,exist_ok=True)
    with open(path,"a",encoding="utf-8") as f:
        hist=[x for x in todo if x[1]["_hist"]]; live=[x for x in todo if not x[1]["_hist"]]
        for i,((d,st),m) in enumerate(hist):
            scan=utc(d,0,55); w0=utc(d,TZ[st[1:]])
            cs=get(KALSHI_BASE+"/historical/markets/%s/candlesticks"%m["ticker"],dict(start_ts=scan-3600,end_ts=w0,period_interval=1,include_latest_before_start="true")).json().get("candlesticks") or []
            f.write(json.dumps(row(d,st,m,cs))+"\n")
            if i%50==0: f.flush(); print("  historical",i,"/",len(hist))
        byday={}
        for (d,st),m in live: byday.setdefault(d,[]).append((st,m))
        for d,items in sorted(byday.items()):
            scan=utc(d,0,55); end=max(utc(d,TZ[st[1:]]) for st,_ in items)
            for i in range(0,len(items),20):
                part=items[i:i+20]
                j=get(KALSHI_BASE+"/markets/candlesticks",dict(market_tickers=",".join(m["ticker"] for _,m in part),start_ts=scan-3600,end_ts=end,
                      period_interval=1,include_latest_before_start="true")).json()
                got={x["market_ticker"]:(x.get("candlesticks") or []) for x in j.get("markets",[])}
                if sum(len(v) for v in got.values())>=9500: raise RuntimeError("candle cap reached for "+str(d))
                for st,m in part:
                    if m["ticker"] in got: f.write(json.dumps(row(d,st,m,got[m["ticker"]]))+"\n")
            f.flush(); print("  live day",d,len(items))
    print("kalshi done ->",path)

def snap(cs,t,w0):
    """(bid, ask) quoted at t, and the lowest offer/trade and highest bid/trade in whole minutes after t up to w0."""
    cs=sorted(cs,key=lambda c:c["end_period_ts"]); s=[c for c in cs if c["end_period_ts"]<=t]
    after=[c for c in cs if c["end_period_ts"]-60>=t and c["end_period_ts"]<=w0]
    lo=[v for c in after for v in (_v(c.get("price"),"low"),_v(c.get("yes_ask"),"low")) if v is not None and v>0]
    hi=[v for c in after for v in (_v(c.get("price"),"high"),_v(c.get("yes_bid"),"high")) if v is not None and v<1]
    b,a=(_v(s[-1].get("yes_bid"),"close"),_v(s[-1].get("yes_ask"),"close")) if s else (None,None)
    return b,a,(min(lo) if lo else None),(max(hi) if hi else None)
LATE=(3,30)   # 03:30 UTC = 11:30 PM La Paz, before the first market day starts at 05:00 UTC
def candles(items):
    """items: [(ticker, hist, start_ts, end_ts)] for one market day -> {ticker: candles}. Historical markets one by one, others in groups of 20."""
    out={}
    for t,h,s0,e0 in items:
        if h: out[t]=get(KALSHI_BASE+"/historical/markets/%s/candlesticks"%t,dict(start_ts=s0,end_ts=e0,period_interval=1,include_latest_before_start="true"),pause=0.1).json().get("candlesticks") or []
    def batch(part):   # Kalshi returns at most 10,000 candles per request: near the cap, ask again in halves
        j=get(KALSHI_BASE+"/markets/candlesticks",dict(market_tickers=",".join(x[0] for x in part),start_ts=min(x[2] for x in part),end_ts=max(x[3] for x in part),
              period_interval=1,include_latest_before_start="true")).json()
        got={x["market_ticker"]:(x.get("candlesticks") or []) for x in j.get("markets",[])}
        if sum(len(v) for v in got.values())<9500: out.update(got)
        elif len(part)>1: h=len(part)//2; batch(part[:h]); batch(part[h:])
        else: raise RuntimeError("candle cap reached for "+part[0][0])
    live=[x for x in items if not x[1]]
    for i in range(0,len(live),20): batch(live[i:i+20])
    return out
def temp_series():
    try:
        j=get(KALSHI_BASE+"/series",dict(category="Climate and Weather")).json()
        s=sorted({x["ticker"] for x in j.get("series",[]) if x.get("ticker","").startswith("KXHIGH")})
        if s: return s
    except Exception as ex: print("series list failed, using the known list:",ex)
    return sorted(("KXHIGHAUS KXHIGHCHI KXHIGHDEN KXHIGHLAX KXHIGHMIA KXHIGHNY KXHIGHPHIL KXHIGHTATL KXHIGHTBOS KXHIGHTDAL KXHIGHTDC "
                   "KXHIGHTEWR KXHIGHTHOU KXHIGHTLV KXHIGHTMIN KXHIGHTNOLA KXHIGHTOKC KXHIGHTPHX KXHIGHTSAN KXHIGHTSATX KXHIGHTSDF "
                   "KXHIGHTSEA KXHIGHTSFO KXHIGHTTTN").split())
def rules_strikes(m):
    """Strike numbers written in the rules ("greater than 73", "between 72-73"), for a data check against floor/cap."""
    seg=(m.get("rules_primary") or "").split("fahrenheit")[0].split(" is ")[-1]
    return [float(x) for x in re.findall(r"(-?\d+(?:\.\d+)?)\s*(?:-|to|\u00b0|\u00ba)",seg)]
def temp():
    path=os.path.join(DATA,"kalshi_temp.jsonl"); done=set()
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: done={json.loads(l)["ticker"] for l in f if l.strip()}
    series=temp_series(); print("temperature series:",len(series)); best={}; yesterday=date.today()-timedelta(days=1)
    for se in series:
        n=0
        for path_,extra in (("/historical/markets",{}),("/markets",{"status":"settled"})):
            cur=None
            while True:
                j=get(KALSHI_BASE+path_,dict(series_ticker=se,limit=1000,cursor=cur,**extra)).json()
                for m in j.get("markets",[]):
                    try: d=mday(m["ticker"])
                    except (ValueError,IndexError): continue
                    st=station_of(m)
                    if d<HOLD2 or d>yesterday or m.get("result") not in ("yes","no") or not st: continue
                    m["_hist"]=path_.startswith("/historical"); n+=1
                    k=(d,st,m.get("strike_type"),m.get("floor_strike"),m.get("cap_strike"))
                    if k not in best or float(m.get("volume_fp") or 0)>float(best[k].get("volume_fp") or 0): best[k]=m
                cur=j.get("cursor")
                if not cur: break
        print("  ",se,n,"markets")
    skip=sorted({k[1] for k in best if k[1][1:] not in TZ})
    todo=[(k,m) for k,m in best.items() if m["ticker"] not in done and k[1][1:] in TZ]
    print("unique contracts:",len(best),"| to fetch:",len(todo),"| skipped, no time zone known:",skip)
    save(os.path.join(DATA,"temp_stations.json"),sorted({k[1] for k in best}))   # lets the IEM commands start before the candles are done
    byday={}
    for k,m in todo: byday.setdefault(k[0],[]).append((k,m))
    os.makedirs(DATA,exist_ok=True)
    with open(path,"a",encoding="utf-8") as f:
        for d,items in sorted(byday.items()):
            scan=utc(d,0,55); late=utc(d,*LATE)
            cs=candles([(m["ticker"],m["_hist"],scan-3600,utc(d,TZ[k[1][1:]])) for k,m in items])
            miss=[m["ticker"] for k,m in items if m["ticker"] not in cs]
            if miss: print("  no candles returned for %d markets on %s (left out): %s"%(len(miss),d,", ".join(miss[:5])))
            for k,m in items:
                if m["ticker"] not in cs: continue
                c=cs[m["ticker"]]; w0=utc(d,TZ[k[1][1:]])
                sb,sa,lo,hi=snap(c,scan,w0); lb,la,llo,lhi=snap(c,late,w0); wb,wa,_,_=snap(c,w0,w0)
                f.write(json.dumps(dict(ticker=m["ticker"],series=m["ticker"].split("-")[0],day=d.isoformat(),station=k[1],result=m["result"],strike_type=m.get("strike_type"),
                    floor=m.get("floor_strike"),cap=m.get("cap_strike"),rule_numbers=rules_strikes(m),volume=float(m.get("volume_fp") or 0),hist=m["_hist"],
                    scan_ts=scan,late_ts=late,start_ts=w0,scan_bid=sb,scan_ask=sa,lo_after=lo,hi_after=hi,late_bid=lb,late_ask=la,late_lo=llo,late_hi=lhi,
                    start_bid=wb,start_ask=wa,n_candles=len(c)))+"\n")
            f.flush(); print("  day",d,len(items))
    print("temp done ->",path)
def late():
    src=os.path.join(DATA,"kalshi_rain.jsonl"); path=os.path.join(DATA,"kalshi_rain_late.jsonl"); done=set()
    if os.path.exists(path):
        with open(path,encoding="utf-8") as f: done={json.loads(l)["ticker"] for l in f if l.strip()}
    rows=[json.loads(l) for l in open(src,encoding="utf-8") if l.strip()]; byday={}
    for r in rows:
        if r["ticker"] not in done: byday.setdefault(r["day"],[]).append(r)
    with open(path,"a",encoding="utf-8") as f:
        for d,items in sorted(byday.items()):
            dd=date.fromisoformat(d); late_=utc(dd,*LATE)
            cs=candles([(r["ticker"],r["hist"],late_-3600,r["start_ts"]) for r in items])
            miss=[r["ticker"] for r in items if r["ticker"] not in cs]
            if miss: print("  no candles returned for %d markets on %s (left out)"%(len(miss),d))
            for r in items:
                if r["ticker"] not in cs: continue
                lb,la,llo,lhi=snap(cs[r["ticker"]],late_,r["start_ts"])
                f.write(json.dumps(dict(ticker=r["ticker"],late_ts=late_,late_bid=lb,late_ask=la,late_lo=llo,late_hi=lhi))+"\n")
            f.flush(); print("  late day",d,len(items))
    print("late done ->",path)

# ---------------- IEM ----------------
def stations():
    sts=set()
    for name in ("kalshi_rain.jsonl","kalshi_temp.jsonl"):
        p=os.path.join(DATA,name)
        if os.path.exists(p):
            with open(p,encoding="utf-8") as f: sts|={json.loads(l)["station"] for l in f if l.strip()}
    p=os.path.join(DATA,"temp_stations.json")
    if os.path.exists(p): sts|=set(json.load(open(p,encoding="utf-8")))
    import weather
    sts|={"K"+v[0][3:] for v in weather.RAIN.values()}
    return sorted(sts)
KEEP=("runtime","ftime","p06","q06","p12","q12","txn","xnd","tmp")
def nbs():
    first=date(TRAIN[0].year,TRAIN[0].month,1); last=date.today()
    months=[]; d=first
    while d<=last: months.append(d); d=date(d.year+(d.month==12),d.month%12+1,1)
    for st in stations():
        for m in months:
            out=os.path.join(DATA,"nbs","%s_%s.json"%(st,m.strftime("%Y%m")))
            if os.path.exists(out) and json.load(open(out,encoding="utf-8")): continue   # empty files are fetched again
            nxt=date(m.year+(m.month==12),m.month%12+1,1)
            # runs from the last day of the previous month at 18Z, so day 1 of this month has its evening-before run
            sts=(datetime(m.year,m.month,1)-timedelta(hours=6)).strftime("%Y-%m-%dT%H:%MZ"); ets=datetime(nxt.year,nxt.month,1).strftime("%Y-%m-%dT%H:%MZ")
            r=get(IEM+"/cgi-bin/request/mos.py",dict(station=st,model="NBS",sts=sts,ets=ets,format="csv"),pause=3)
            # the evening run: 19 UTC in IEM's archive until 2026, 18 UTC after (the archive's cycle labels changed)
            rows=[{k:x.get(k) for k in KEEP} for x in csv.DictReader(io.StringIO(r.text)) if (x.get("runtime") or "")[11:16] in ("18:00","19:00")]
            save(out,rows); print("  NBS",st,m.strftime("%Y-%m"),len(rows),"rows")
    print("nbs done")
def nbslate():
    """NBS runs labelled 00 or 01 UTC (IEM labels 01 before 2026, 00 after) for the plan 2 later scan, Jul-Oct 2026."""
    months=[date(2026,m,1) for m in range(7,11)]
    for st in stations():
        for m in months:
            out=os.path.join(DATA,"nbs_late","%s_%s.json"%(st,m.strftime("%Y%m")))
            if os.path.exists(out) and json.load(open(out,encoding="utf-8")): continue
            nxt=date(m.year+(m.month==12),m.month%12+1,1)
            r=get(IEM+"/cgi-bin/request/mos.py",dict(station=st,model="NBS",sts=datetime(m.year,m.month,1).strftime("%Y-%m-%dT%H:%MZ"),
                  ets=datetime(nxt.year,nxt.month,1).strftime("%Y-%m-%dT%H:%MZ"),format="csv"),pause=3)
            rows=[{k:x.get(k) for k in KEEP} for x in csv.DictReader(io.StringIO(r.text)) if (x.get("runtime") or "")[11:16] in ("00:00","01:00")]
            save(out,rows); print("  NBS late",st,m.strftime("%Y-%m"),len(rows),"rows")
    print("nbslate done")
def cli():
    for st in stations():
        for y in range(TRAIN[0].year,date.today().year+1):
            out=os.path.join(DATA,"cli","%s_%d.json"%(st,y))
            if os.path.exists(out) and y<date.today().year: continue
            j=get(IEM+"/json/cli.py",dict(station=st,year=str(y)),pause=3).json()
            save(out,[{k:x.get(k) for k in ("valid","precip","high","low","product")} for x in j.get("results",[])]); print("  CLI",st,y,len(j.get("results",[])))
    print("cli done")
if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd not in ("kalshi","nbs","cli","temp","late","nbslate"): sys.exit(__doc__)
    globals()[cmd]()
