"""Live prices for open paper trades (marks.py) and the marked account chart (account_view, dashboard): fake Kalshi
answers, a temporary paper.db, no network. python test_marks.py WORK OUT"""
import os, sys, json, sqlite3, subprocess, time
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); sys.path.insert(0,WORK)
import marks, account_view as AV, dashboard
src=open(os.path.join(WORK,"marks.py"),encoding="utf-8").read()
assert "requests.post" not in src and "portfolio" not in src and "import live" not in src, "marks.py must only read prices"
c=sqlite3.connect(os.environ["PAPER_DB"])
c.execute("create table if not exists trades(id integer primary key,ts real,ticker text,side text,price real,fair real,n integer,cost real,fee real,status text default 'open',result text,pnl real,version text default 'v1',settled_ts real)")
now=time.time(); t0=now-3*86400
rows=[(t0+100,"KXRAIN-A","yes",0.40,3,1.20,0.05,"open",None,None,"v3",None),     # id 1: YES, bid 0.55 -> 1.65
      (t0+200,"KXRAIN-B","no",0.30,2,0.60,0.03,"open",None,None,"v3",None),      # id 2: NO, yes_ask 0.62 -> 2 x 0.38
      (t0+300,"KXRAIN-C","yes",0.50,1,0.50,0.02,"open",None,None,"v3",None),     # id 3: settled on Kalshi as no -> 0
      (t0+400,"KXRAIN-D","yes",0.50,1,0.50,0.02,"open",None,None,"v3",None),     # id 4: trading closed, no result -> left out
      (t0+500,"KXRAIN-E","no",0.50,1,0.50,0.02,"open",None,None,"v3",None),      # id 5: missing from the batch answer -> asked alone
      (t0+50,"KXRAIN-F","yes",0.50,2,1.00,0.03,"settled","yes",0.97,"v3",t0+1000)]   # settled in paper.db: not priced
c.executemany("insert into trades(ts,ticker,side,price,n,cost,fee,status,result,pnl,version,settled_ts,fair) values(?,?,?,?,?,?,?,?,?,?,?,?,0.6)",rows)
c.execute("create table shadow_orders(id integer primary key,ts real,ticker text,strategy text,version text,side text,price real,fair real,fc real,bid real,ask real,improved integer,n integer,cost real,fee real,cancel_ts real,status text,fill_ts real,result text,pnl real,settle_ts real)")
c.execute("insert into shadow_orders(ts,ticker,side,price,n,cost,fee,status,fill_ts) values(?,?,?,?,?,?,?,?,?)",(t0+150,"KXRAIN-A","yes",0.38,1,0.38,0,"filled",t0+160))
c.execute("insert into shadow_orders(ts,ticker,side,price,n,cost,fee,status) values(?,?,?,?,?,?,?,?)",(t0+150,"KXRAIN-B","yes",0.30,1,0.30,0,"pending"))
c.commit(); c.close()
asked=[]
class R:
    def __init__(s,j,code=200): s.j=j; s.status_code=code
    def json(s): return s.j
    def raise_for_status(s):
        if s.status_code!=200: raise RuntimeError("HTTP %d"%s.status_code)
MK={"KXRAIN-A":dict(ticker="KXRAIN-A",status="active",yes_bid_dollars="0.5500",yes_ask_dollars="0.5700"),
    "KXRAIN-B":dict(ticker="KXRAIN-B",status="active",yes_bid=60,yes_ask=62),   # cents only
    "KXRAIN-C":dict(ticker="KXRAIN-C",status="finalized",result="no",yes_bid_dollars="0",yes_ask_dollars="0"),
    "KXRAIN-D":dict(ticker="KXRAIN-D",status="closed",result="",yes_bid_dollars="0",yes_ask_dollars="0"),
    "KXRAIN-E":dict(ticker="KXRAIN-E",status="active",yes_bid_dollars="0.2000",yes_ask_dollars="0.2500")}
def get(url,params):
    asked.append((url.rsplit("/",1)[-1],dict(params)))
    if url.endswith("/markets"): return R(dict(markets=[MK[t] for t in params["tickers"].split(",") if t in MK and t!="KXRAIN-E"]))
    t=url.rsplit("/",1)[-1]; return R(dict(market=MK[t])) if t in MK else R({},404)
assert sorted(p[0] for p in marks.positions())==["main:1","main:2","main:3","main:4","main:5","maker:1"]
s=marks.snapshot(get=get,now=now-600)
assert s["marks"]=={"main:1":1.65,"main:2":0.76,"main:3":0.0,"main:5":0.75,"maker:1":0.55} and s["open"]==6, s
assert [a for a,_ in asked]==["markets","KXRAIN-E"], asked   # one batch, then the one the batch missed
assert marks.value(dict(status="active",yes_bid_dollars="0.1",yes_ask_dollars=None),"no",1) is None   # no YES offer: no NO bid
# marks.main writes one line; a failure writes nothing and exits 0
import requests
def boom(*a,**k): raise requests.ConnectionError("offline (test)")
requests.get=boom; assert marks.main()==0 and not os.path.exists("marks.jsonl")
with open("marks.jsonl","w") as f:
    f.write(json.dumps(s)+"\n"+"not json\n"+json.dumps(dict(ts=now-300,marks={"main:1":1.80,"main:2":0.70,"main:5":0.80,"maker:1":0.60}))+"\n")
    old=(now-5*86400)//3600*3600+600   # two marks inside one clock hour, 5 days ago (fixed 2026-10-22: the test used now-5d and
    f.write(json.dumps(dict(ts=old,marks={}))+"\n"+json.dumps(dict(ts=old+60,marks={}))+"\n"+json.dumps(dict(ts=now+3600,marks={}))+"\n")   # +60 s, which straddled an hour in the last minute of each hour)
rm=dashboard.read_marks(now=now)
assert [round(x["ts"],1) for x in rm]==[round(old,1),round(now-600,1),round(now-300,1)], [x["ts"] for x in rm]   # one per hour before 48 h; none from the future; bad line skipped
# (compared at 0.1 s since 2026-10-23: snapshot() stores ts rounded to 0.1 s, and rounding that again to whole seconds
#  failed whenever the clock's fraction was in [0.45, 0.5), about 1 run in 20: the suite's occasional single failure)
# the chart's numbers
conn=sqlite3.connect(os.environ["PAPER_DB"]); conn.row_factory=sqlite3.Row
tr=[dict(r) for r in conn.execute("select * from trades")]; so=[dict(r) for r in conn.execute("select * from shadow_orders")]
L=AV.main_ledger(tr,25.0,t0); pts,last=AV.mark_points(L,rm,"main",now)
assert abs(last-(now-300))<0.2 and len(pts)==2 and all(abs(p[0]-e)<0.2 for p,e in zip(pts,[now-600,now-300])), (last,pts)   # within 0.2 s (2026-10-29: whole-second rounding of a stored x.5 flipped either way)
u1=(1.65-1.20)+(0.76-0.60)+(0.0-0.50)+(0.75-0.50); u2=(1.80-1.20)+(0.70-0.60)+(0.0-0.50)+(0.80-0.50)   # main:3 keeps its earlier mark
assert abs(pts[0][1]-u1)<1e-9 and abs(pts[1][1]-u2)<1e-9, (pts,u1,u2)
# a trade that settles after a price snapshot drops out at once (never counted twice)
tr2=[dict(r) for r in tr]
for r in tr2:
    if r["id"]==1: r.update(status="settled",result="yes",pnl=1.75,settled_ts=now-200)
L2=AV.main_ledger(tr2,25.0,t0); pts2,_=AV.mark_points(L2,rm,"main",now)
assert len(pts2)==3 and all(abs(p[0]-e)<=0.2 for p,e in zip(pts2,(now-600,now-300,now-200))) and abs(pts2[-1][1]-(u2-(1.80-1.20)))<1e-9, pts2   # 0.2 s tolerance: snapshot times are stored rounded to 0.1 s (as on line 58)
v=AV.value_at(L2,now)+pts2[-1][1]; v_cost=AV.value_at(L2,now)
assert abs(v-(v_cost+u2-0.60))<1e-9
html=AV.section(tr,so,25.0,t0,now,marks=rm,live=True)
assert "at their Kalshi bid" in html and "refresh every 5 minutes" in html and '"marks":[[' in html
assert ("$%.2f"%(AV.value_at(L,now)+u2)) in html.split("acct-v>")[1][:12], html.split("acct-v>")[1][:12]   # the headline counts the marks
html0=AV.section(tr,so,25.0,t0,now)
assert "at what they cost" in html0 and "run watch" in html0
# dashboard: --live adds the self-refresh flag and the chip; a normal build does not
for args,want in ((["--no-open"],False),(["--no-open","--live"],True)):
    r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py")]+args,capture_output=True,text=True,cwd=OUT,env=dict(os.environ,PYTHONPATH=WORK)); assert r.returncode==0, r.stderr
    page=open(os.path.join(OUT,"dashboard_live.html" if want else "dashboard.html"),encoding="utf-8").read()
    assert ("<body data-live=1>" in page)==want and ("chip live" in page)==want and "at their Kalshi bid" in page, args
assert marks.value(dict(status="active",yes_bid_dollars="0",yes_ask_dollars="0.02"),"yes",3) is None   # no bid: unknown, not worthless
assert marks.value(dict(status="active",yes_bid_dollars="0.98",yes_ask_dollars="1.00"),"no",3) is None  # no YES offer: no NO bid
assert not os.path.exists(os.path.join(OUT,"dashboard.tmp")) and not os.path.exists(os.path.join(OUT,"dashboard_live.tmp"))
print("marks: all checks passed")
