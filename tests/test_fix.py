"""Tests for the 2026-10-14 fixes: settled_ts migration, daily loss stop, clear margin. No network.
python test_fix.py WORK OUT"""
import os, sys, sqlite3, time as _time, io, contextlib, subprocess, importlib
WORK=sys.argv[1]; OUT=sys.argv[2]
os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
# 1. an old-schema paper.db (exactly the pre-fix CREATE statements) with one open v3 trade
old=sqlite3.connect("paper.db")
old.execute("create table if not exists trades(id integer primary key,ts real,ticker text,side text,price real,fair real,n integer,cost real,fee real,status text default 'open',result text,pnl real,version text default 'v1')")
old.execute('create table if not exists obs(ticker text,version text,ts real,fc real,mid real,result text,nws_prev real,nws_day real,nws_night real,market_type text,p_a real,p_b real,slices text,mu real,station text,primary key(ticker,version))')
NOW=_time.time()
old.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)",(NOW-86400,"KXRAIN-26OCT14-AAA","yes",0.60,0.70,5,3.00,0.06,"v3"))
old.commit(); old.close()
import config, core, kalshi, strategy, weather
c=core.db()
cols=[r[1] for r in c.execute("pragma table_info(trades)")]
assert "settled_ts" in cols, cols
assert c.execute("select count(*) from trades where status='open'").fetchone()[0]==1
assert any("premigration" in f for f in os.listdir("backups")) and any("premigration" in f for f in os.listdir("offsite")), "no backup before migration"
n_bk=len(os.listdir("backups")); c.close(); c=core.db(); assert len(os.listdir("backups"))==n_bk, "migration ran twice"
print("migration: column added after a backup, runs once: ok")
# 2. settle a losing trade -> settled_ts set, daily stop active
kalshi.get=lambda t:{"result":"no"}
strategy.settle(c)
r=c.execute("select status,pnl,settled_ts from trades").fetchone(); print("  settled:",r)
assert r[0]=="settled" and abs(r[1]+3.06)<1e-9 and abs(r[2]-_time.time())<5
cash,today=core.state(c); print("  state: cash=%.2f last24h=%.2f"%(cash,today))
assert abs(today+3.06)<1e-9 and today<=-config.DAILY_LOSS_LIMIT*config.BANKROLL
# 3. scan while stopped: markets still logged, no trades
from datetime import datetime, timedelta, timezone
close=(datetime.now(timezone.utc)+timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
mk=[{"ticker":"KXRAIN-26OCT15-BBB","close_time":close,"yes_bid_dollars":"0.50","yes_ask_dollars":"0.52"},
    {"ticker":"KXRAIN-26OCT15-CCC","close_time":close,"yes_bid_dollars":"0.50","yes_ask_dollars":"0.52"}]
kalshi.markets=lambda *a,**k:mk
strategy.estimate=lambda m:{"KXRAIN-26OCT15-BBB":0.80,"KXRAIN-26OCT15-CCC":0.51}[m["ticker"]]   # BBB has a big edge (a 29-point gap: under the 30-point veto of 2026-10-28)
out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
print("  scan while stopped:",out.getvalue().strip().replace("\n"," | "))
assert "daily loss limit hit" in out.getvalue()
assert c.execute("select count(*) from obs where ticker like 'KXRAIN-26OCT15%'").fetchone()[0]==2, "markets not logged while stopped"
assert c.execute("select count(*) from trades").fetchone()[0]==1, "traded while stopped"
# 4. 25 hours later the stop has expired -> BBB trades
real=_time.time; core.time.time=lambda:real()+25*3600
cash,today=core.state(c); assert today==0, today
c.execute("delete from obs where ticker like 'KXRAIN-26OCT15%'"); c.commit()
out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
core.time.time=real
print("  scan 25h later:",out.getvalue().strip().replace("\n"," | "))
assert "daily loss limit" not in out.getvalue() and c.execute("select count(*) from trades where ticker='KXRAIN-26OCT15-BBB'").fetchone()[0]==1
print("daily stop: triggers on losses settled in the last 24h, keeps logging, expires: ok")
# 5. clear margin: 6 days x 5 markets, forecast better on 5 days, worse on 1
c.execute("delete from obs"); c.commit()
import random; random.seed(3); rows=[]
for di,day in enumerate(["26OCT1%d"%i for i in range(4,10)]):
    for k in range(5):
        y=random.random()<0.4; r="yes" if y else "no"
        fc=(0.7 if y else 0.3) if di!=5 else (0.45 if y else 0.55); mid=0.5
        c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",("KXRAIN-%s-C%d"%(day,k),"v3",NOW,fc,mid,r,"rain")); rows.append((day,(fc-y)**2-(mid-y)**2))
c.commit()
import statistics as S
dm=[S.mean([d for dd,d in rows if dd==day]) for day in sorted({dd for dd,_ in rows})]
mu=S.mean(dm); se=S.stdev(dm)/len(dm)**0.5
mg=strategy.margin(c.execute("select ticker,fc,mid,result from obs").fetchall())
print("  margin: mean %.4f se %.4f days %d (by hand %.4f %.4f)"%(mg[0],mg[1],mg[2],mu,se))
assert abs(mg[0]-mu)<1e-12 and abs(mg[1]-se)<1e-12 and mg[2]==6 and strategy.clear(mg)==(mu<0 and -mu>=2.571*se) and strategy.tcrit(6)==2.571 and strategy.tcrit(200)==2.0
assert strategy.margin([("KXRAIN-26OCT14-A",0.5,0.5,"yes")]*4) is None
sys.path.insert(0,WORK); import dashboard
rg=[{"ticker":t,"fc":f,"mid":m,"result":r} for t,f,m,r in c.execute("select ticker,fc,mid,result from obs")]
assert dashboard.margin(rg)==mg, (dashboard.margin(rg),mg)
# gate.py (used by the dashboard) and strategy.py's frozen copy must give identical answers (docs/REFACTOR.md stage 2)
import gate, random as _r, datetime as _dt0
assert gate.STOP_DATE==strategy.STOP_DATE and gate.T975==strategy.T975 and all(gate.tcrit(d)==strategy.tcrit(d) for d in range(0,60))
_rng=_r.Random(11)
for _ in range(300):
    rows=[("KXRAIN-26OCT%02d-C%d"%(_rng.randint(10,30),k),_rng.random(),_rng.random(),_rng.choice(("yes","no"))) for k in range(_rng.randint(0,60))]
    assert gate.margin(rows)==strategy.margin(rows) and gate.clear(gate.margin(rows))==strategy.clear(strategy.margin(rows))
    mg=(_rng.uniform(-0.1,0.05),_rng.uniform(0,0.05),_rng.randint(1,40)); assert gate.clear(mg)==strategy.clear(mg)
assert gate.final(strategy.STOP_DATE) and not gate.final(strategy.STOP_DATE-_dt0.timedelta(days=1))
import datetime as _dt
class _B(_dt.date):   # the day before the stop date, so this check also holds after Nov 11, 2026
    @classmethod
    def today(cls): return strategy.STOP_DATE-_dt.timedelta(days=1)
strategy.date=_B; out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.report(c)
lines=[l for l in out.getvalue().splitlines() if "CLEAR" in l or "GATE (" in l]; print("  report:",lines)
assert "interim, not acted on" in lines[0] and "judged once on" in lines[1], lines
class _D(_dt.date):
    @classmethod
    def today(cls): return strategy.STOP_DATE+_dt.timedelta(days=1)
strategy.date=_D; out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.report(c)
lines=[l for l in out.getvalue().splitlines() if "CLEAR" in l or "GATE (" in l]; print("  report after the stop date:",lines)
assert "the gate is the single look below" in lines[0] and (lines[1].endswith("not passed") or lines[1].endswith("not judged yet (the single look is pending)")), lines   # single look, stored (2026-10-28)
strategy.date=_dt.date
c.close()
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,cwd=OUT,env=dict(os.environ,PYTHONPATH=WORK))
assert r.returncode==0, r.stderr
html=open("dashboard.html",encoding="utf-8").read()
assert ("Last 24 hours" in html or "Daily stop on" in html) and "Daily loss stop" in html and ("clear margin" in html or "Lead " in html), "dashboard text missing"
print("dashboard ok:", r.stdout.strip())
print("ALL FIX TESTS PASSED")
