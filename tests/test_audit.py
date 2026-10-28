"""Decision audit ledger, strategy registry, calibration and the shadow selector, on fake markets (no network).
python test_audit.py WORK OUT"""
import os, sys, json, sqlite3, io, contextlib, re
from datetime import datetime, timedelta, timezone
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"off"); sys.path.insert(0,WORK)
import core, strategy, kalshi, audit, registry, calibration, selector, weather
strategy.STOP_DATE=strategy.date(2099,1,1)   # not a stop-date test (tests/test_gatelook.py is): its markets stay "before the stop date" after Nov 11 too
now=datetime.now(timezone.utc)
def ct(h): return (now+timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
def mk(t,close_h,bid,ask,**k): return dict(ticker=t,event_ticker=t.rsplit("-",1)[0],close_time=ct(close_h),yes_bid_dollars=bid,yes_ask_dollars=ask,rules_primary="Rule for "+t,**k)
D=(now+timedelta(days=1)).strftime("%y%b%d").upper()
M=[mk("KXRAIN-%s-NYC"%D,30,0.41,0.43),       # forecast 0.70: a 28-point gap, big edge -> TRADE
   mk("KXRAIN-%s-PHX"%D,30,0.30,0.32),       # forecast 0.70: a 39-point gap -> vetoed (2026-10-28)
   mk("KXRAIN-%s-BOS"%D,30,0.50,0.52),       # forecast 0.52: no edge
   mk("KXRAIN-%s-ATL"%D,30,0.20,0.40),       # spread 20c
   mk("KXRAIN-%s-MIA"%D,30,None,0.40),       # no bid
   mk("KXRAIN-%s-SEA"%D,10,0.30,0.32),       # day already begun
   dict(mk("KXRAIN-%s-CHI"%D,30,0.30,0.32),close_time="garbage"),
   mk("KXRAIN-%s-ZZZ"%D,30,0.30,0.32),       # model has no estimate
   mk("KXHIGHDEN-%s-T48"%D,30,0.01,0.02,strike_type="greater")]   # temperature: logged, not traded
P={"NYC":0.70,"PHX":0.70,"BOS":0.52,"ATL":0.6,"MIA":0.6,"SEA":0.9,"CHI":0.9,"DEN":0.12}
kalshi.markets=lambda *a,**k: M
def est(m):
    key=m["ticker"].split("-")[-1]
    if key.startswith("T"): key="DEN"
    p=P.get(key)
    if p is not None: weather.RAW[m["ticker"]]={"type":"rain","station":"CLI"+key,"p_a":p,"p_b":p,"slices":[int(p*100)]*24}
    return p
strategy.estimate=est
c=core.db(); out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
txt=out.getvalue()
dec=c.execute("select ticker,strategy_id,action,reason,side,price,p_win,n,trade_ref,mode,rules_hash,detail,inputs from decisions").fetchall()
by={r[0].split("-")[-1]:r for r in dec}
assert len(dec)==len(M), (len(dec),txt)   # every market evaluated has exactly one decision
want={"NYC":"TRADE","PHX":"ANOMALOUS_MODEL_MARKET_GAP","BOS":"INSUFFICIENT_EDGE","ATL":"WIDE_SPREAD","MIA":"NO_QUOTE","SEA":"MARKET_STARTED","CHI":"CLOSE_TIME_UNREADABLE","ZZZ":"MODEL_UNAVAILABLE","T48":"STRATEGY_DISABLED"}
assert {k:v[3] for k,v in by.items()}==want, {k:v[3] for k,v in by.items()}
assert by["T48"][1]=="forecast_alpha.temp.v3" and by["T48"][9]=="research" and by["NYC"][1]=="forecast_alpha.rain.v3" and by["NYC"][9]=="paper"
tr=c.execute("select id,ticker,side,price,n,fair from trades").fetchall()
assert len(tr)==1 and by["NYC"][8]=="trades:%d"%tr[0][0] and by["NYC"][2]=="TRADE_YES" and abs(by["NYC"][5]-tr[0][3])<1e-12 and by["NYC"][7]==tr[0][4] and abs(by["NYC"][6]-tr[0][5])<1e-12
# the v3 trade: the shadow selector has no settled history yet, so it would not trade it
det=json.loads(by["NYC"][11]); assert det["meta"]["reason"]=="INSUFFICIENT_HISTORY" and det["market"]["ticker"].endswith("NYC") and by["NYC"][10]
# the 39-point gap is vetoed (user decision 2026-10-28): no trade, and the selector agrees
dp=json.loads(by["PHX"][11]); assert by["PHX"][2]=="ABSTAIN" and dp["meta"]["reason"]=="ANOMALOUS_MODEL_MARKET_GAP"
assert json.loads(by["NYC"][12])["slices"]==[70]*24
assert c.execute("select count(*) from scans").fetchone()[0]==1 and c.execute("select count(*) from scan_ends").fetchone()[0]==1
assert "AUDIT: scan" in txt
# append-only: no update, no delete, no second decision for the same market in the same scan
for sql in ("update decisions set reason='TRADE'","delete from decisions","update scans set kind='x'"):
    try: c.execute(sql); raise SystemExit("allowed: "+sql)
    except sqlite3.DatabaseError as e: assert "append-only" in str(e) or "no such" in str(e), e
sid=c.execute("select scan_id from scans").fetchone()[0]
try: audit.decide(c,sid,"forecast_alpha.rain.v3",M[0],"ABSTAIN","NO_QUOTE"); raise SystemExit("duplicate decision allowed")
except sqlite3.IntegrityError: pass
for bad in (("BUY","TRADE"),("ABSTAIN","MADE_UP")):
    try: audit.decide(c,sid,"x",dict(ticker="X"),*bad); raise SystemExit("bad code allowed")
    except ValueError: pass
# settle: event on the trade's decision, market results recorded once
res={m["ticker"]:"yes" for m in M}; kalshi.get=lambda t: {"result":res.get(t)}
with contextlib.redirect_stdout(io.StringIO()): strategy.settle(c)
ev=c.execute("select e.kind,e.detail from decision_events e join decisions d on d.decision_id=e.decision_id where d.trade_ref like 'trades:%'").fetchall()
assert len(ev)==1 and ev[0][0]=="settled" and json.loads(ev[0][1])["won"] is True, ev
assert c.execute("select count(*) from market_results").fetchone()[0]>=3
for sql in ("delete from market_results","update market_results set result='no'","delete from decision_events"):   # row triggers: tables have rows now
    try: c.execute(sql); raise SystemExit("allowed: "+sql)
    except sqlite3.DatabaseError as e: assert "append-only" in str(e), e
c.close()
# the dashboard's control center shows the trade's snapshot in plain words (paper.db opened read-only)
import subprocess
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,cwd=OUT,env=dict(os.environ,PYTHONPATH=WORK))
page=open(os.path.join(OUT,"dashboard.html"),encoding="utf-8").read()
assert r.returncode==0 and "control center failed" not in r.stdout and "id=control" in page and "Audit trail" in page and "Forecast said YES 70%" in page and "INTERIM - NOT ACTIONABLE" in page, r.stdout[-500:]
assert "would not trade. Not enough settled history" in page and "forecast_alpha.temp.v3" in page
# fail closed: if the trade's decision cannot be written, the trade is rolled back (the market is still logged in obs)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper2.db"); import importlib, config; importlib.reload(config); core.DB=config.DB
c=core.db(); real=audit.decide
def broken(c_,sid_,*a,**k):
    if k.get("action","").startswith("TRADE") or (len(a)>2 and str(a[2]).startswith("TRADE")): raise sqlite3.OperationalError("disk full (test)")
    return real(c_,sid_,*a,**k)
audit.decide=broken
with contextlib.redirect_stdout(io.StringIO()) as o2: strategy.scan(c)
audit.decide=real
assert c.execute("select count(*) from trades").fetchone()[0]==0 and c.execute("select count(*) from obs").fetchone()[0]>=3 and "NOT TRADED" in o2.getvalue(), o2.getvalue()
c.close()
# the same scan with the ledger stubbed out opens the same trades (the audit never changes a v3 decision)
import time; time.sleep(1.2)   # backup names have one-second resolution, and backup.py never overwrites (a clash fails closed)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper3.db"); importlib.reload(config); core.DB=config.DB
c=core.db(); audit.decide=lambda *a,**k: "stub"
with contextlib.redirect_stdout(io.StringIO()): strategy.scan(c)
audit.decide=real
assert c.execute("select ticker,side,price,n,fair from trades").fetchall()==[t[1:] for t in tr], "audit changed a decision"
c.close()
# if the ledger cannot be created at all, markets are still logged but nothing is traded
os.environ["PAPER_DB"]=os.path.join(OUT,"paper4.db"); importlib.reload(config); core.DB=config.DB
c=core.db(); ens=audit.ensure; audit.ensure=lambda *a,**k: False
with contextlib.redirect_stdout(io.StringIO()) as o4: strategy.scan(c)
audit.ensure=ens
assert c.execute("select count(*) from trades").fetchone()[0]==0 and c.execute("select count(*) from obs").fetchone()[0]>=3 and "TRADES BLOCKED" in o4.getvalue()
c.close()
# broken or missing research helpers never change the v3 scan: same obs, same trades (code review 2026-10-22)
time.sleep(1.2); os.environ["PAPER_DB"]=os.path.join(OUT,"paper5.db"); importlib.reload(config); core.DB=config.DB
c=core.db(); keep=(selector.evaluate,strategy._ctx_fields,strategy.risk)
def boom(*a,**k): raise RuntimeError("broken helper (test)")
selector.evaluate=boom; strategy._ctx_fields=boom; strategy.risk=None
with contextlib.redirect_stdout(io.StringIO()) as o5: strategy.scan(c)
selector.evaluate,strategy._ctx_fields,strategy.risk=keep
assert c.execute("select ticker,side,price,n,fair from trades").fetchall()==[t[1:] for t in tr], o5.getvalue()
assert c.execute("select count(*) from obs").fetchone()[0]==c.execute("select count(*) from obs").fetchone()[0] and c.execute("select count(*) from decisions").fetchone()[0]==len(M)
d5=json.loads(c.execute("select detail from decisions where reason='TRADE'").fetchone()[0]); assert "broken helper" in d5["meta"]["error"], d5
c.close()
# an older or foreign ledger schema is refused untouched: trades blocked, markets still logged
time.sleep(1.2); os.environ["PAPER_DB"]=os.path.join(OUT,"paper6.db"); importlib.reload(config); core.DB=config.DB
c=core.db(); c.execute("create table decisions(decision_id text primary key,scan_id text)"); c.commit()
with contextlib.redirect_stdout(io.StringIO()) as o6: strategy.scan(c)
assert c.execute("select count(*) from trades").fetchone()[0]==0 and c.execute("select count(*) from obs").fetchone()[0]>=3, o6.getvalue()
assert "TRADES BLOCKED" in o6.getvalue() and "differ from audit.py" in o6.getvalue() and [r[1] for r in c.execute("pragma table_info(decisions)")]==["decision_id","scan_id"] and not c.execute("select name from sqlite_master where name='scans'").fetchone()
c.close()
import control_view as CV
T6=dict(obs=[dict(version="v3",ts=CV.LEDGER_FROM+100)],scans=[])
assert CV.blocked(T6) and not CV.blocked(dict(T6,scans=[dict(kind="scan",started_ts=CV.LEDGER_FROM+50)])) and not CV.blocked(dict(obs=[dict(version="v3",ts=CV.LEDGER_FROM-10)],scans=[]))
# ---- registry ----
assert registry.check() and not any(registry.may_trade_live(s["id"]) for s in registry.REGISTRY)
assert registry.may_paper_trade("forecast_alpha.rain.v3") and not registry.may_paper_trade("forecast_alpha.temp.v3") and not registry.may_paper_trade("meta_selector.accuracy_first.v1")
assert not registry.transition_ok("BACKTEST","LIVE_ELIGIBLE") and registry.transition_ok("FORWARD_TEST","FAILED")
src=open(os.path.join(WORK,"live.py"),encoding="utf-8").read()
assert "version='v3' and ticker like 'KXRAIN%'" in src and "import registry" not in src and "import selector" not in src   # live.py stays v3-rain-only
for f in ("audit.py","registry.py","selector.py","calibration.py"):
    s_=open(os.path.join(WORK,f),encoding="utf-8").read()
    assert not re.search(r"portfolio|import live|requests\.post",s_), f   # no order paths in the new modules
c=sqlite3.connect(os.path.join(OUT,"paper.db")); registry.log_states(c); registry.log_states(c); c.commit()
assert c.execute("select count(*) from strategy_log").fetchone()[0]==len(registry.REGISTRY)   # logged once, not again when unchanged
try: c.execute("delete from strategy_log"); raise SystemExit("strategy_log deletable")
except sqlite3.DatabaseError: pass
c.close()
# ---- calibration ----
lo,hi=calibration.wilson(7,10); assert abs(lo-0.3968)<1e-3 and abs(hi-0.8922)<1e-3, (lo,hi)
rows=[(0.65,1)]*70+[(0.65,0)]*30
cal=calibration.Calib(rows); q,n=cal.conservative(0.66,"yes"); assert n==100 and abs(q-calibration.wilson(70,100)[0])<1e-12
q2,_=cal.conservative(0.66,"no"); assert abs(q2-(1-calibration.wilson(70,100)[1]))<1e-12
assert calibration.Calib(rows[:20]).conservative(0.66,"yes")==(None,20)
s_=calibration.summary(rows); assert abs(s_["brier"]-(0.7*0.35**2+0.3*0.65**2))<1e-9 and abs(s_["ece"]-0.05)<1e-9
# ---- selector ----
base=dict(side="yes",p_win=0.66,p_yes=0.66,p_model_yes=0.70,mid=0.60,price=0.62,fee_pc=0.02,spread=0.02,data_age_s=600)
w=calibration.wilson(70,100)
r=selector.evaluate(base,cal); assert r["action"]=="ABSTAIN" and r["reason"]=="NEGATIVE_NET_EV" and abs(r["q_cons"]-w[0])<1e-12, r   # 0.604 passes the 0.60 floor; 0.604 - 0.62 - 0.02 < 0.01
r=selector.evaluate(dict(base,price=0.55),cal); assert r["action"]=="TRADE_YES" and abs(r["stake_frac"]-min((w[0]-0.55)/0.45*0.25,0.06))<1e-12, r
assert selector.evaluate(dict(base,side="no",price=0.38),cal)["reason"]=="LOW_WIN_PROBABILITY"
assert selector.evaluate(dict(base,data_age_s=4*3600),cal)["reason"]=="STALE_DATA"
assert selector.evaluate(dict(base,spread=0.10),cal)["reason"]=="WIDE_SPREAD"
assert selector.evaluate(dict(base,p_model_yes=0.95),cal)["reason"]=="ANOMALOUS_MODEL_MARKET_GAP"
assert selector.evaluate(base,calibration.Calib(rows[:20]))["reason"]=="INSUFFICIENT_HISTORY"
assert selector.evaluate(dict(base,price=None),cal)["reason"]=="NO_QUOTE"
assert set(audit.REASONS)>={"LOW_WIN_PROBABILITY","NEGATIVE_NET_EV","STALE_DATA","WIDE_SPREAD","ANOMALOUS_MODEL_MARKET_GAP","INSUFFICIENT_HISTORY","CORRELATION_LIMIT","RESEARCH_ONLY"}
print("audit, registry, calibration, selector: all checks passed")
