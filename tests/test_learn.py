"""learn.py: stories, breakdowns and the pattern screen on fake trades; read-only on paper.db and live.db. python test_learn.py WORK OUT"""
import os, sys, json, time, hashlib, subprocess, random, sqlite3
from datetime import date, timedelta
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite"); os.environ.pop("LIVE_DB",None)
assert not os.path.abspath(os.environ["PAPER_DB"]).startswith(os.path.abspath(WORK)), "tests must never use the real paper.db"
sys.path.insert(0,WORK)
import core, learn
assert learn.story(0.7,0.3,True)=="forecast beat the market" and learn.story(0.7,0.3,False)=="market beat the forecast"
assert learn.story(0.7,0.8,False)=="upset" and learn.story(0.2,0.1,False)=="long shot missed" and learn.story(0.2,0.1,True)=="long shot hit"
# Student-t cutoffs without scipy (reference values from t tables)
for df,p,want in ((10,0.025,2.228),(4,0.025,2.776),(30,0.005,2.750),(20,0.0005,3.850)): assert abs(learn.tcrit(p,df)-want)<0.003,(df,p,learn.tcrit(p,df))
assert learn.week("26OCT15")==learn.week("2026-10-12") and learn.week("26OCT15")!=learn.week("26OCT19")
# too few
s=learn.stats([dict(day="D%d"%(i%5),win=i%2,price=0.5,pnl=0,fair=0.6) for i in range(20)]); assert learn.judge(s,10)=="too few", s
# a group that profits exactly as much as the rest of its breakdown is not a pattern, however steady
D=[(date(2026,8,1)+timedelta(days=i)).isoformat() for i in range(40)]
g=[dict(day=d,win=1,price=0.5,pnl=0.5,fair=0.6) for d in D]; r=[dict(day=d,win=1,price=0.5,pnl=0.5,fair=0.6) for d in D]
s=learn.stats(g,r); assert learn.judge(s,10)=="noise so far", s
# the overall row is never flagged
assert learn.judge(learn.stats(g+r),10)=="overall: judged by its own plan"
# a group far above the rest, every day: flagged
r2=[dict(day=d,win=k%2,price=0.5,pnl=(k%2)-0.52,fair=0.6) for d in D for k in range(2)]
s=learn.stats(g,r2); assert learn.judge(s,10)=="worth a written test", s
# ...but not when it is too short to cover 4 weeks
g3=[dict(day=d,win=1,price=0.5,pnl=0.5,fair=0.6) for d in D[2:16] for k in range(3)]   # 42 trades on 14 days, 2 weeks
s=learn.stats(g3,r2); assert s["n"]>=30 and s["days"]>=10 and s["weeks"]<4 and learn.judge(s,10)=="too few", s
c=core.db(); rnd=random.Random(7)
cities=["NYC","CHI","MIA","SEA","DEN"]; start=date(2026,9,10)
def tk(d,ci): return "KXRAIN-%s-%s"%((start+timedelta(days=d)).strftime("%y%b%d").upper(),ci)
for d in range(35):
    for ci in cities:
        t=tk(d,ci); fc=rnd.random(); mid=min(max(fc+rnd.uniform(-0.3,0.3),0.03),0.97); y="yes" if rnd.random()<mid else "no"
        c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",(t,"v3",time.time(),fc,mid,y,"rain"))
        side="yes" if fc>mid else "no"; price=round(mid+0.01,2) if side=="yes" else round(1-mid+0.01,2); n=3
        pnl=(n if y==side else 0)-n*price-core.fee(price,n)
        c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (time.time(),t,side,price,min(price+0.1,0.99),n,n*price,core.fee(price,n),"settled",y,pnl,"v3",time.time()))
# one city that wins every day at a low price: must be flagged against the rest (5 weeks of market days)
for d in range(35):
    t=tk(d,"WIN")
    c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",(t,"v3",time.time(),0.6,0.3,"yes","rain"))
    c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (time.time(),t,"yes",0.31,0.45,1,0.31,0.02,"settled","yes",1-0.31-0.02,"v3",time.time()))
# a settled trade without its forecast-log row is counted as left out
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"KXRAIN-26SEP01-BOS","yes",0.5,0.6,1,0.5,0.02,"settled","no",-0.52,"v3",time.time()))
# the shadow limit-order ledger keeps its own forecast and quote
c.execute(open(os.path.join(WORK,"shadow.py")).read().split('"shadow_orders":"',1)[1].split('",\n',1)[0].replace('"\n            "','').replace('" "',''))
c.execute("insert into shadow_orders(ts,ticker,strategy,version,side,price,fair,fc,bid,ask,improved,n,cost,fee,status,result,pnl) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"KXRAIN-26OCT15-NYC","maker","v3","no",0.40,0.55,0.35,0.58,0.62,1,2,0.80,0,"settled","no",1.20))
# the real-money filters judged on paper (2026-11-09): three trades with their decision rows and airport forecasts
import audit; assert audit.ensure(c)
c.execute(open(os.path.join(WORK,"shadow.py")).read().split('"v4_obs":"',1)[1].split('",\n',1)[0])
for t,side,price,v3,mid,hours,air,res in (("KXRAIN-26NOV08-FLA","no",0.07,0.70,0.94,[50]*24,0.99,"yes"),    # v3 alone: skipped by the no-rain filter
                                          ("KXRAIN-26NOV08-FLB","yes",0.07,0.25,0.06,[0]*12+[31]+[0]*11,0.02,"yes"),   # copied; the 6-hour view agrees
                                          ("KXRAIN-26NOV06-FLC","no",0.48,0.27,0.54,[0]*24,0.16,"no")):   # copied, before the fair-read date
    n=2; pnl=(n if res==side else 0)-n*price-core.fee(price,n)
    c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",(t,"v3",time.time(),v3,mid,res,"rain"))
    pid=c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (time.time(),t,side,price,0.5,n,n*price,core.fee(price,n),"settled",res,pnl,"v3",time.time())).lastrowid
    c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,mode,ticker,action,side,reason,mid,price,p_model,inputs,trade_ref) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("d-"+t,"s-"+t,time.time(),"forecast_alpha.rain.v3","paper",t,"TRADE_"+side.upper(),side,"TRADE",mid,price,v3,json.dumps({"slices":hours}),"trades:%d"%pid))
    c.execute("insert into v4_obs(ticker,ts,station,fc,mid) values(?,?,?,?,?)",(t,time.time(),"K"+t[-3:],air,mid))
c.commit(); c.close()
L=sqlite3.connect(os.path.join(OUT,"live.db")); L.execute("create table orders(id integer primary key,ts real,env text,paper_id integer,ticker text,side text,count integer,limit_cents integer,client_order_id text,order_id text,status text,fill_count real,cost real,fees real,note text,result text,pnl real,settled_ts real)")
L.execute("insert into orders(env,ticker,side,count,limit_cents,status,fill_count,cost,fees) values('demo','KXRAIN-26OCT15-DEN','no',5,12,'partial',1,0.11,0.0069)")
L.execute("insert into orders(env,ticker,side,count,limit_cents,status,note) values('demo','KXRAIN-26OCT15-PIT','yes',2,52,'skipped','no price to buy at')"); L.commit(); L.close()
h=hashlib.sha256(open("paper.db","rb").read()).hexdigest(); hl=hashlib.sha256(open("live.db","rb").read()).hexdigest()
res=os.path.join(OUT,"results")
r=subprocess.run([sys.executable,os.path.join(WORK,"learn.py")],capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=WORK,TRADEBOT_RESULTS=res),cwd=OUT)
assert r.returncode==0, r.stdout+r.stderr
assert hashlib.sha256(open("paper.db","rb").read()).hexdigest()==h and hashlib.sha256(open("live.db","rb").read()).hexdigest()==hl, "learn.py must not change the databases"
md=open(os.path.join(res,"learning.md"),encoding="utf-8").read(); js=json.load(open(os.path.join(res,"learning.json"),encoding="utf-8"))
assert ("LEARNING: paper v3 rain %d settled"%(35*6+3)) in r.stdout and "groups flagged (a screen, not a test)" in r.stdout, r.stdout
flags=md.split("## Patterns worth a written test")[1]
for want in ("By situation","Losses by story","By city","Forecast vs market on every logged market","demo: 1 orders placed, 1 of 5 contracts filled",
             "Limit-order test","| NO | 1 |","Patterns worth a written test","no price to buy at 1","1 settled trade(s) left out","overall: judged by its own plan",
             "Blend said","Vs rest of this breakdown"):
    assert want in md, (want,md[:3000])
assert "By city / WIN:" in flags and " / all" not in flags and "[past" not in flags, flags
assert js["screen"]["groups"]>0 and any("WIN" in f for f in js["screen"]["flagged"]), js["screen"]
fl=md.split("## Real-money filters, judged on paper (v3 rain)")[1].split("## Patterns worth")[0]
assert "| from 26NOV07 (fair read) | filtered out (no-rain filter) | 1 | 1 | 0 | 0.1 | -0.15 |" in fl, fl
assert "| from 26NOV07 (fair read) | passes the filters (would be copied) | 1 | 1 | 1 | 0.1 | +1.85 |" in fl and "passes the filters, and the 6-hour check (off) would pass | 1 | 1 | 1 |" in fl, fl
assert "| before 26NOV07 (where the filters were found) | passes the filters (would be copied) |" in fl, fl
assert "| before 26NOV07 (where the filters were found) | filtered out (inputs unreadable) |" in fl and "filtered out (no-rain filter) | 7" not in fl, fl   # old trades without a decision row are their own group
rows_=[l for l in fl.splitlines() if l.startswith("| KXRAIN-26NOV0")]
assert rows_[0].startswith("| KXRAIN-26NOV06-FLC | NO x2 at 48c | 27% | 54% | 1% | 16% | won |") and rows_[0].endswith("| passes | 0 of 2 |"), rows_   # newest first by trade id; both other views are outside the 30-point veto
assert "| KXRAIN-26NOV08-FLA | NO x2 at 7c | 70% | 94% | 94% | 99% | lost | -0.15 | filtered out: no-rain filter | 0 of 2 |" in fl, fl
assert "| KXRAIN-26NOV08-FLB | YES x2 at 7c | 25% | 6% | 31% | 2% | won | +1.85 | passes | 1 of 2 |" in fl, fl
assert js["filters"] and "screen" in js
shadow=[l for l in md.split("## Limit-order test")[1].splitlines() if l.startswith("| NO | 1 |")][0]
assert "| 55% |" in shadow, shadow   # the ledger's own blend, not 0%
print("learn.py: all checks passed")
