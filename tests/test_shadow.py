"""Mocked test of shadow.py: no network, temp folder only.
python test_shadow.py WORK OUT"""
import os, sys, json, sqlite3, hashlib, subprocess, time as _time
from datetime import datetime, timedelta, timezone
WORK=sys.argv[1]; OUT=sys.argv[2]
os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import requests
import config, core, kalshi, shadow
import strategy; strategy.STOP_DATE=strategy.date(2099,1,1)   # not a stop-date test (tests/test_gatelook.py is): its markets stay "before the stop date" after Nov 11 too
NOW=_time.time()
def iso(ts): return datetime.fromtimestamp(ts,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
W0=int(NOW//60*60)+4*3600          # day starts in 4 hours
CLOSE=W0+86400
tag=datetime.fromtimestamp(W0,timezone.utc).strftime("%y%b%d").upper()
T=lambda city:"KXRAIN-%s-%s"%(tag,city)
# obs rows as the v3 scan would have written them 30 minutes ago
c=core.db()
rows=[  # city, fc, bid, ask
 ("AAA",0.60,0.30,0.34),   # YES edge, spread 4c -> improved bid at 0.31
 ("BBB",0.75,0.40,0.41),   # YES edge, spread 1c -> joins bid at 0.40
 ("CCC",0.10,0.50,0.53),   # NO edge, spread 3c -> YES offer 0.52 -> NO bid 0.48 improved
 ("DDD",0.45,0.44,0.46),   # no edge -> no order
 ("EEE",0.80,0.20,0.30),   # spread 10c > MAX_SPREAD -> skipped
 ("FFF",0.70,0.35,0.38),   # YES improved at 0.36; fill only BEFORE the order time -> unfilled
 ("GGG",0.05,0.30,0.31),   # NO joined: YES offer 0.31 -> NO bid 0.69; needs YES above 0.31 strictly
]
for city,fc,b,a in rows:
    c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)",(T(city),"v3",NOW-1800,fc,(b+a)/2,"rain"))
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)",("KXRAIN-25JAN01-OLD","v3",NOW-90000,0.5,0.5,"rain"))
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)",(NOW-1800,T("AAA"),"yes",0.34,0.47,2,0.68,0.02,"v3"))
c.commit()
def h(c): return hashlib.sha256(json.dumps([c.execute("select * from obs order by ticker").fetchall(),c.execute("select * from trades order by id").fetchall()]).encode()).hexdigest()
before=h(c)
mk=[{"ticker":T(city),"close_time":iso(CLOSE),"yes_bid_dollars":"%.4f"%b,"yes_ask_dollars":"%.4f"%a} for city,fc,b,a in rows]
mk.append({"ticker":"KXRAIN-25JAN01-OLD","close_time":iso(NOW+3600),"yes_bid_dollars":"0.4000","yes_ask_dollars":"0.4200"})  # day already started
kalshi.markets=lambda *a,**k:mk
calls=[]
# ---- cap check on a copy first: default 15% cap ($3.75) must block FFF and GGG
import shutil
c.commit(); shutil.copy("paper.db","cap.db"); cc=sqlite3.connect("cap.db")
shadow.subprocess=type("S",(),{"run":staticmethod(lambda *a,**k:type("R",(),{"returncode":0})())})   # skip backups for the copy
shadow.scan(cc)
oc=cc.execute("select ticker,n,cost from shadow_orders").fetchall(); print("  cap test:",oc)
assert {r[0].split("-")[-1] for r in oc}=={"AAA","BBB","CCC"} and sum(r[2] for r in oc)<=3.75+1e-9, oc
cc.close(); import subprocess as _sp; shadow.subprocess=_sp
# ---- scan (cap lifted so every scenario gets an order)
shadow.MAX_OPEN_PCT=1.0
shadow.scan(c)
o=c.execute("select ticker,side,price,improved,n,cost,fee,status,cancel_ts,fair from shadow_orders order by ticker").fetchall()
for r in o: print("  order",r)
got={r[0].split("-")[-1]:(r[1],round(r[2],2),r[3]) for r in o}
exp={"AAA":("yes",0.31,1),"BBB":("yes",0.40,0),"CCC":("no",0.48,1),"FFF":("yes",0.36,1),"GGG":("no",0.69,0)}
assert got==exp, got
assert all(r[8]==W0 for r in o) and all(r[6]==0 for r in o) and all(r[7]=="pending" for r in o)
# sizing check on AAA: fair = .5*.6+.5*.32=.46, price .31 -> f=(.46-.31)/.69*.25=.0543 -> stake=25*.0543=1.359 -> n=4
assert dict((r[0].split("-")[-1],r[4]) for r in o)["AAA"]==4
shadow.scan(c); assert c.execute("select count(*) from shadow_orders").fetchone()[0]==len(o), "duplicate orders"
assert os.listdir("backups") and os.listdir("offsite"), "no pre-migration backup"
print("backups:",os.listdir("backups"),os.listdir("offsite"))
# ---- candles for settle
OT=o[0][8]-W0   # unused
ots={r[0]:c.execute("select ts from shadow_orders where ticker=?",(r[0],)).fetchone()[0] for r in o}
def cd(end,bid,ask,lo=None,hi=None,**kw):
    p={"previous_dollars":"0.5"}
    if lo is not None: p.update(low_dollars="%.4f"%lo,high_dollars="%.4f"%(hi if hi is not None else lo))
    return {"end_period_ts":int(end),"yes_bid":{"open_dollars":"%.4f"%bid,"low_dollars":"%.4f"%bid,"high_dollars":"%.4f"%kw.get("bidhi",bid),"close_dollars":"%.4f"%bid},
            "yes_ask":{"open_dollars":"%.4f"%ask,"low_dollars":"%.4f"%kw.get("asklo",ask),"high_dollars":"%.4f"%ask,"close_dollars":"%.4f"%ask},"price":p,"volume_fp":"1.00","open_interest_fp":"10.00"}
after=lambda t,m:(int(ots[t]//60)*60)+60*(m+1)   # end of the m-th whole minute after the order
C={T("AAA"):[cd(NOW-1900,.30,.34),cd(after(T("AAA"),3),.30,.34,asklo=.31),cd(W0,.33,.36)],        # offer reaches 0.31 -> filled (improved)
   T("BBB"):[cd(NOW-1900,.40,.41),cd(after(T("BBB"),1),.40,.41,lo=.40),cd(W0,.42,.43)],            # trade AT 0.40 only -> joined: not filled
   T("CCC"):[cd(NOW-1900,.50,.53),cd(after(T("CCC"),5),.50,.53,bidhi=.52),cd(W0,.45,.47)],          # YES bid reaches 0.52 -> NO filled
   T("DDD"):[cd(NOW-1900,.44,.46)],                                                                 # unchanged -> move 0
   T("FFF"):[cd(ots[T("FFF")]+30,.35,.38,lo=.30),cd(W0+600,.20,.25,lo=.20)],                       # through price only in the order's own minute and after cancel -> unfilled
   T("GGG"):[cd(NOW-1900,.30,.31),cd(after(T("GGG"),2),.31,.32,lo=.32,hi=.32),cd(W0-60,.30,.40)],  # YES traded 0.32 > 0.31 -> NO filled; spread 10c at start -> wide
   }
def fake_get(url,params=None,timeout=None,**k):
    calls.append((url,dict(params or {})))
    class R:
        status_code=200
        def raise_for_status(self): pass
        def json(self_):
            if url.endswith("/markets/candlesticks"):
                ts=params["market_tickers"].split(","); s,e=params["start_ts"],params["end_ts"]
                return {"markets":[{"market_ticker":t,"candlesticks":[x for x in C.get(t,[]) if x["end_period_ts"]<=e]} for t in ts]}
            if url.endswith("/markets"):
                ts=params["tickers"].split(",")
                return {"markets":[{"ticker":t,"close_time":iso(CLOSE),"result":RES.get(t,"")} for t in ts if t in RES or t.startswith("KXRAIN-"+tag)]}
            raise AssertionError(url)
    return R()
shadow.requests.get=fake_get
RES={}
class FT:
    v=W0+3600
    @staticmethod
    def time(): return FT.v
    @staticmethod
    def sleep(x): pass
shadow.time=FT
kalshi.get=lambda t:(_ for _ in ()).throw(AssertionError("per-market lookup not expected: "+t))
# settle before results are in
shadow.settle(c)
st={r[0].split("-")[-1]:(r[1],r[2]) for r in c.execute("select ticker,status,fill_ts from shadow_orders")}
print("  after settle 1:",{k:v[0] for k,v in st.items()})
assert {k:v[0] for k,v in st.items()}=={"AAA":"filled","BBB":"unfilled","CCC":"filled","FFF":"unfilled","GGG":"filled"}, st
mv={r[0].split("-")[-1]:r[1:] for r in c.execute("select ticker,mid_scan,mid_start,status from shadow_moves")}
print("  moves:",mv)
assert abs(mv["AAA"][1]-0.345)<1e-9 and mv["AAA"][2]=="ok"
assert abs(mv["DDD"][1]-0.45)<1e-9 and mv["GGG"][2]=="wide" and mv["GGG"][1] is None
assert "OLD" not in mv   # its market lookup returned nothing -> skipped
# results arrive
RES.update({T("AAA"):"yes",T("CCC"):"yes",T("GGG"):"no"})
FT.v=CLOSE+3600
shadow.settle(c)
s=c.execute("select ticker,status,result,pnl from shadow_orders where status='settled' order by ticker").fetchall()
print("  settled:",s)
pn={r[0].split("-")[-1]:round(r[3],4) for r in s}
N={r[0].split("-")[-1]:(r[4],r[5]) for r in o}
assert pn=={"AAA":round(N["AAA"][0]-N["AAA"][1],4),"CCC":round(-N["CCC"][1],4),"GGG":round(N["GGG"][0]-N["GGG"][1],4)}, pn
n_moves=c.execute("select count(*) from shadow_moves").fetchone()[0]
shadow.settle(c); assert c.execute("select count(*) from shadow_moves").fetchone()[0]==n_moves
assert h(c)==before, "v3 obs/trades changed!"
print("v3 obs and trades unchanged: ok")
shadow.report(c)
# cancel boundaries: order times are inclusive-minute based
print("candle calls:",sum(1 for u,p in calls if u.endswith("candlesticks")),"market lookups:",sum(1 for u,p in calls if u.endswith("/markets")))
c.close()
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,cwd=OUT,env=dict(os.environ,PYTHONPATH=WORK))
print("dashboard exit",r.returncode,r.stdout.strip(),r.stderr.strip()[-500:])
r=subprocess.run([sys.executable,os.path.join(WORK,"shadow.py"),"report"],capture_output=True,text=True,cwd=OUT,env=dict(os.environ,PYTHONPATH=WORK))
print("cli report exit",r.returncode,r.stdout.strip()[:800],r.stderr.strip()[-300:])
print("ALL SHADOW TESTS PASSED")
