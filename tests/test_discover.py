"""research/discover.py on a fake Kalshi, no network: pagination, single and combo passes, deduplication, the daily
series cache, lifecycle rows when a market closes, the --every cache, the append-only lifecycle table and the
request rate. python test_discover.py WORK OUT"""
import os, sys, shutil, sqlite3, time
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research"))
import discover as D
D.DATA=os.path.join(OUT,"data"); D.OUT=os.path.join(OUT,"results"); DB=os.path.join(OUT,"data","discovery.db")
def mk(t,st="active",mve=False): return dict(ticker=t,event_ticker=t.rsplit("-",1)[0],status=st,close_time="2026-11-01T00:00:00Z",yes_bid_dollars="0.4000",yes_ask_dollars="0.4300",volume_fp="12.00")
OPEN=[mk("KXRAINNYC-26OCT25-T%d"%i) for i in range(2500)]+[mk("KXRAINNYC-26OCT25-T7")]   # one duplicate across pages
COMBO=[mk("KXMVESPORTS-ABC-%d"%i) for i in range(30)]
CLOSED={}; calls={"series":0,"open":0,"combo":0,"batch":0,"single":0}
def fake(path,params=None,**k):
    params=params or {}
    if path=="/series":
        calls["series"]+=1; return dict(series=[dict(ticker="KXRAINNYC",category="Climate and Weather",fee_type="quadratic"),dict(ticker="KXMVESPORTS",category="Sports",fee_type="quadratic")])
    if path=="/markets" and "tickers" in params:
        calls["batch"]+=1; ts=params["tickers"].split(","); assert len(ts)<=50
        return dict(markets=[CLOSED[t] for t in ts if t in CLOSED and not t.endswith("T5")])
    if path=="/markets/KXRAINNYC-26OCT25-T5": calls["single"]+=1; return dict(market=CLOSED["KXRAINNYC-26OCT25-T5"])
    if path=="/markets":
        assert params["status"]=="open" and params["limit"]==1000
        src=COMBO if params["mve_filter"]=="only" else OPEN; calls["combo" if params["mve_filter"]=="only" else "open"]+=1
        i=int(params.get("cursor") or 0); page=src[i:i+1000]
        return dict(markets=page,cursor=str(i+1000) if i+1000<len(src) else "")
    raise AssertionError(path)
D.http=fake
T=1_800_000_000.0
r=D.refresh(now=T,path=DB)
assert r==dict(open=2530,new=2530,closed=0) and calls["open"]==3 and calls["combo"]==1 and calls["series"]==1, (r,calls)
c=sqlite3.connect(DB)
assert c.execute("select count(*) from markets").fetchone()[0]==2530 and c.execute("select count(*) from markets where mve=1").fetchone()[0]==30
assert c.execute("select yes_bid,yes_ask,volume,series from markets where ticker='KXRAINNYC-26OCT25-T3'").fetchone()==(0.4,0.43,12.0,"KXRAINNYC")
# the --every cache: nothing happens within the window
assert D.refresh(now=T+600,path=DB,every=3600) is None and calls["open"]==3
# two markets close, one is only found one by one; the series list is not re-read within a day
for t in ("KXRAINNYC-26OCT25-T4","KXRAINNYC-26OCT25-T5"): CLOSED[t]=mk(t,"closed")
OPEN=[m for m in OPEN if m["ticker"] not in CLOSED]
r=D.refresh(now=T+7200,path=DB,every=3600)
assert r==dict(open=2528,new=0,closed=2) and calls["series"]==1 and calls["single"]==1, (r,calls)
lc=c.execute("select ticker,old,new from lifecycle where old is not null order by ticker").fetchall()
assert lc==[("KXRAINNYC-26OCT25-T4","active","closed"),("KXRAINNYC-26OCT25-T5","active","closed")], lc
assert c.execute("select status_ts from markets where ticker='KXRAINNYC-26OCT25-T4'").fetchone()[0]==T+7200
assert c.execute("select status_ts from markets where ticker='KXRAINNYC-26OCT25-T3'").fetchone()[0]==T   # unchanged status keeps its time
# closed markets are not looked up again; a day later the series list is re-read
D.refresh(now=T+90000,path=DB); assert calls["batch"]==1 and calls["series"]==2, calls
for sql in ("update lifecycle set new='x'","delete from lifecycle"):
    try: c.execute(sql); raise SystemExit("lifecycle changed: "+sql)
    except sqlite3.DatabaseError as ex: assert "append-only" in str(ex)
# singles only (the hourly job): no combo pages; a ticker Kalshi no longer knows is marked not_found, not retried forever
c.rollback()   # the refused UPDATE/DELETE above left this test connection's transaction open
GONE404={"KXRAINNYC-26OCT25-T6"}; OPEN=[m for m in OPEN if m["ticker"] not in GONE404]; fake0=D.http
def fake404(path,params=None,**k):
    if path=="/markets/KXRAINNYC-26OCT25-T6": raise RuntimeError("HTTP 404 "+path)
    return fake0(path,params,**k)
D.http=fake404; cb=calls["combo"]
r=D.refresh(now=T+100000,path=DB,singles=True); assert calls["combo"]==cb and r["closed"]==1, (r,calls)
assert c.execute("select status,close_ts from markets where ticker='KXRAINNYC-26OCT25-T6'").fetchone()[0]=="not_found"
assert c.execute("select count(*) from markets where mve=1 and status='active'").fetchone()[0]==30   # combos untouched by a singles run
D.refresh(now=T+110000,path=DB,singles=True); assert c.execute("select count(*) from lifecycle where ticker='KXRAINNYC-26OCT25-T6'").fetchone()[0]==2   # not looked up again
D.http=fake0
rows=D.summary(path=DB); assert ("Climate and Weather",0,2497,2497) in rows and ("Sports",1,30,30) in rows, rows
assert os.path.exists(os.path.join(OUT,"results","discovery.md"))
# rate limit: requests are spaced at least MIN_GAP apart
D.http=D.__dict__["http"]; stamps=[]
class R:
    status_code=200; headers={}
    def json(self): return {}
import types; fake_requests=types.SimpleNamespace(get=lambda *a,**k:(stamps.append(time.time()),R())[1],RequestException=Exception)
sys.modules["requests"]=fake_requests
import importlib; importlib.reload(D)
for _ in range(5): D.http("/x")
gaps=[b-a for a,b in zip(stamps,stamps[1:])]; assert min(gaps)>=D.MIN_GAP-0.01, gaps
print("discover.py: all checks passed")
