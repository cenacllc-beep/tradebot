"""Settle survives network errors (added 2026-10-28, audit of the Oct 26 and Oct 27 settles). No network.
On Oct 26 (name resolution failed) and Oct 27 (TLS handshake timed out) one failed Kalshi lookup stopped strategy.settle:
nothing was committed, run.bat stopped before live sync, the shadow settle, learn and the backup, and the open trade
stayed open (it still counted against the 15% exposure cap and the daily loss stop).
python test_settle.py WORK OUT"""
import os, sys, sqlite3, time, io, contextlib
WORK=sys.argv[1]; OUT=sys.argv[2]
os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import core, kalshi, strategy

def fresh(trades, obs):
    if os.path.exists("paper.db"): os.remove("paper.db")
    c=core.db()
    for t,side,n,cost,fee in trades:
        c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)",(time.time()-86400,t,side,cost/n,0.5,n,cost,fee,"v3"))
    for t in obs:
        c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)",(t,"v3",time.time()-86400,0.3,0.4,"rain"))
    c.commit(); return c
def quiet(fn, *a, **k):
    out=io.StringIO()
    with contextlib.redirect_stdout(out): r=fn(*a, **k)
    return r, out.getvalue()
class Net(Exception): pass

# 1. result_of retries a failed lookup, then answers; never sleeps after the last try
calls=[]; sleeps=[]
seq=iter([Net("getaddrinfo failed"), Net("read timed out"), {"result": "no", "status": "finalized"}])
def flaky(t):
    calls.append(t); x=next(seq)
    if isinstance(x, Exception): raise x
    return x
kalshi.get=flaky
assert strategy.result_of("KXRAIN-A", sleep=sleeps.append)=="no" and len(calls)==3 and sleeps==[5.0, 10.0], (calls, sleeps)
def down(t): raise kalshi.requests.exceptions.ConnectionError("getaddrinfo failed")
kalshi.get=down; sleeps.clear()
try:
    strategy.result_of("KXRAIN-A", sleep=sleeps.append); raise AssertionError("expected Unreached")
except strategy.Unreached as ex:
    assert "KXRAIN-A" in str(ex) and "getaddrinfo" in str(ex) and sleeps==[5.0, 10.0] and ex.network, "a network failure"
def slow(t): raise kalshi.requests.exceptions.ReadTimeout("read timed out")
kalshi.get=slow
try:
    strategy.result_of("KXRAIN-A", sleep=lambda s: None); raise AssertionError("expected Unreached")
except strategy.Unreached as ex:
    assert ex.network, "a timeout counts as a network failure"
kalshi.get=lambda t: {"error": {"code": "not_found"}}["market"]   # an answer without a market counts as a failed lookup
try:
    strategy.result_of("KXRAIN-X", sleep=lambda s: None); raise AssertionError("expected Unreached")
except strategy.Unreached as ex:
    assert not ex.network, "Kalshi answered: not a network failure"
kalshi.get=lambda t: {"result": "", "status": "finalized"}   # decided but neither yes nor no (for example voided): warned, kept open
r, out=quiet(strategy.result_of, "KXRAIN-V", sleep=lambda s: None)
assert r=="" and "SETTLE WARNING" in out and "KXRAIN-V" in out, out
kalshi.get=lambda t: {"result": "", "status": "active"}
r, out=quiet(strategy.result_of, "KXRAIN-W", sleep=lambda s: None)
assert r=="" and out=="", out
print("result_of: retries, gives up with the reason, warns on an undecidable result: ok")

# 2. one unreachable market: every other result is recorded and committed; no exit
c=fresh([("KXRAIN-A","no",3,1.11,0.05),("KXRAIN-B","yes",2,1.00,0.04)],["KXRAIN-A","KXRAIN-B","KXRAIN-C"])
looked=[]
def lookup(t):
    looked.append(t)
    if t=="KXRAIN-B": raise strategy.Unreached("KXRAIN-B: read timed out")
    return {"KXRAIN-A":"yes","KXRAIN-C":"no"}[t]
_, out=quiet(strategy.settle, c, lookup=lookup)
assert sorted(looked)==["KXRAIN-A","KXRAIN-B","KXRAIN-C"], ("one lookup per market, even when it is both traded and logged", looked)
c2=sqlite3.connect("paper.db")
assert c2.execute("select status,result,round(pnl,2) from trades where ticker='KXRAIN-A'").fetchone()==("settled","yes",-1.16)
assert c2.execute("select status from trades where ticker='KXRAIN-B'").fetchone()==("open",), "an unreachable market stays open"
assert dict(c2.execute("select ticker,result from obs").fetchall())=={"KXRAIN-A":"yes","KXRAIN-B":None,"KXRAIN-C":"no"}
assert "SETTLE: 1 of 3 markets could not be read" in out and "KXRAIN-B" in out, out
c2.close(); c.close()
print("one market unreachable: the others settle, nothing is lost: ok")

# 3. Kalshi unreachable: exit 1 after at most 3 lookups, nothing written
c=fresh([("KXRAIN-%02d"%i,"no",1,0.5,0.02) for i in range(10)],["KXRAIN-%02d"%i for i in range(10)]+["KXRAIN-X"])
looked.clear()
def dead(t): looked.append(t); raise strategy.Unreached("%s: getaddrinfo failed"%t, network=True)
try:
    quiet(strategy.settle, c, lookup=dead); raise AssertionError("expected SystemExit")
except SystemExit as ex:
    assert ex.code==1
assert len(looked)==3, ("stops trying after 3 failures in a row", looked)
c2=sqlite3.connect("paper.db"); assert c2.execute("select count(*) from trades where status='open'").fetchone()[0]==10; c2.close(); c.close()
print("Kalshi unreachable: exit 1 after 3 tries, trades untouched: ok")
# markets Kalshi answers for without a result (for example unknown tickers) never stop the others being tried
c=fresh([],["KXHIGHAAA-%d"%i for i in range(5)]+["KXRAIN-Z"])
looked.clear()
def unknown(t):
    looked.append(t)
    if t.startswith("KXHIGH"): raise strategy.Unreached("%s: no market in Kalshi's answer"%t, network=False)
    return "yes"
_, out=quiet(strategy.settle, c, lookup=unknown)
assert len(looked)==6 and "5 of 6" in out, (looked, out)
c2=sqlite3.connect("paper.db"); assert c2.execute("select result from obs where ticker='KXRAIN-Z'").fetchone()==("yes",); c2.close(); c.close()
print("answers without a market do not stop the rest (only network failures do): ok")
# a time budget: after it, the remaining markets wait for the next settle
c=fresh([],["KXRAIN-%02d"%i for i in range(6)])
looked.clear(); t=[0.0]
def slowly(x): looked.append(x); t[0]+=400; return "no"
_, out=quiet(strategy.settle, c, lookup=slowly, clock=lambda: t[0], budget=900)
assert len(looked)==3 and "3 of 6" in out and "budget" in out, (looked, out)
c2=sqlite3.connect("paper.db"); assert c2.execute("select count(*) from obs where result='no'").fetchone()[0]==3; c2.close(); c.close()
print("time budget: the rest wait for the next settle, results so far kept: ok")

# 4. a bug after some results were found still keeps them (committed before the error surfaces)
c=fresh([("KXRAIN-A","no",3,1.11,0.05)],["KXRAIN-A","KXRAIN-Z"])
def boom(t):
    if t=="KXRAIN-Z": raise KeyError("unexpected")
    return "no"
try:
    quiet(strategy.settle, c, lookup=boom); raise AssertionError("expected KeyError")
except KeyError:
    pass
c2=sqlite3.connect("paper.db"); assert c2.execute("select status,result from trades").fetchone()==("settled","no"); c2.close(); c.close()
print("an unexpected error later in the run keeps the results already found: ok")

# 5. undecided markets stay open, and a failure streak resets after a success
c=fresh([("KXRAIN-A","no",3,1.11,0.05)],["KXRAIN-A","KXRAIN-B","KXRAIN-C","KXRAIN-D","KXRAIN-E"])
looked.clear()
pattern={"KXRAIN-A":"","KXRAIN-B":"x","KXRAIN-C":"x","KXRAIN-D":"","KXRAIN-E":"x"}
def mixed(t):
    looked.append(t)
    if pattern[t]=="x": raise strategy.Unreached(t)
    return pattern[t]
_, out=quiet(strategy.settle, c, lookup=mixed)
assert len(looked)==5 and "3 of 5 markets could not be read" in out, (looked, out)
c2=sqlite3.connect("paper.db"); assert c2.execute("select status from trades").fetchone()==("open",); c2.close(); c.close()
print("undecided markets stay open; two failures, a success, then another failure keeps trying: ok")
# with the audit ledger: one settled event and one market result, however many settles run (also two at once)
import audit
c=fresh([("KXRAIN-A","no",3,1.11,0.05)],["KXRAIN-A"])
quiet(audit.ensure, c)
sid=audit.start_scan(c,"scan",{})
did=audit.decide(c,sid,"forecast_alpha.rain.v3",dict(ticker="KXRAIN-A",event_ticker="KXRAIN"),"TRADE_NO","TRADE",side="no",trade_ref="trades:1")
c.commit()
def offline(t): raise strategy.Unreached(t, network=True)
try:
    quiet(strategy.settle, c, lookup=offline); raise AssertionError("expected SystemExit")
except SystemExit:
    pass
assert c.execute("select count(*) from decision_events where decision_id=?",(did,)).fetchone()[0]==0
quiet(strategy.settle, c, lookup=lambda t: "yes")
quiet(strategy.settle, c, lookup=lambda t: "yes")
ev=c.execute("select kind,detail from decision_events where decision_id=?",(did,)).fetchall()
assert len(ev)==1 and ev[0][0]=="settled", ev
assert c.execute("select count(*) from market_results where ticker='KXRAIN-A'").fetchone()[0]==1
# two settles at once: the second still holds the old list of open trades, but cannot settle the trade again
c.execute("update trades set status='open',result=null,pnl=null,settled_ts=null")   # reopen to replay the race
c.commit()
c_other=core.db()
rows_seen_by_other=c_other.execute("select id from trades where status='open'").fetchall()
quiet(strategy.settle, c, lookup=lambda t: "yes")          # the first settle records it
assert rows_seen_by_other==[(1,)]
cur=c_other.execute("update trades set status='settled',result='yes',pnl=-1.16,settled_ts=1 where id=1 and status='open'")
assert cur.rowcount==0, "the guard stops a second settlement"
c_other.rollback(); c_other.close()
src=open(os.path.join(WORK,"strategy.py"),encoding="utf-8").read()
assert "where id=? and status='open'" in src and "cur.rowcount==1 and ready" in src
c.close()
print("audit ledger: one settled event however many settles run, and the open-only guard: ok")

# 8. Kalshi's four settlements (2026-11-06, after KXRAIN-26OCT30-PHX settled "scalar" at $0.99): yes, no, scalar, void
P=strategy.payout
fin=lambda **k: dict(dict(status="finalized"), **k)
assert P(fin(result="yes"), "yes")==("yes", 1.0) and P(fin(result="yes"), "no")==("yes", 0.0) and P("no", "no")==("no", 1.0)
assert P({"result": "yes", "status": "determined"}, "yes")==("yes", 1.0), "yes/no count as soon as Kalshi reports them, as before"
assert P(fin(result="scalar", settlement_value_dollars="0.9900"), "yes")==("scalar", 0.99)
assert P(fin(result="scalar", settlement_value_dollars="0.9900"), "no")==("scalar", 0.01)
assert P(fin(result="scalar", settlement_value=25), "no")==("scalar", 0.75), "the older field, in cents"
for odd in (99.5, "0.99", 0.99):   # cents must be whole: a dollar amount in the cents field would read 100 times too small
    assert P(fin(result="scalar", settlement_value=odd), "yes") is None, odd
assert P({"result": "scalar", "status": "settled", "settlement_value_dollars": "0.5"}, "yes")==("scalar", 0.5)
for bad in (dict(result="scalar", status="determined", settlement_value_dollars="0.99"),   # not final yet: its value may change
            dict(result="scalar", status="closed", settlement_value_dollars="0.99"),
            fin(result="scalar"), fin(result="scalar", settlement_value_dollars=""), fin(result="scalar", settlement_value_dollars="1.5"),
            fin(result="scalar", settlement_value_dollars="-0.01"), fin(result="scalar", settlement_value_dollars="nan"),
            fin(result="scalar", settlement_value_dollars="inf"), fin(result="scalar", settlement_value_dollars="abc"),
            dict(result="void", status="closed"), fin(result=""), fin(result="unknown"), {"result": ""}, "scalar", "", None, {}):
    assert P(bad, "yes") is None and P(bad, "no") is None, bad
assert P(fin(result="void"), "yes")==("void", None) and P(fin(result="scalar", settlement_value_dollars="0.99"), "maybe") is None
SP=strategy.settled_pnl
assert SP("yes", "yes", 3, 1.26, 0.06, 1.0)==3-1.26-0.06 and SP("no", "yes", 3, 1.26, 0.06, 0.0)==0-1.26-0.06, "yes/no: the old formula, to the bit"
assert abs(SP("scalar", "yes", 3, 1.26, 0.06, 0.99)-(2.97-1.32))<1e-12 and abs(SP("scalar", "no", 3, 0.24, 0.02, 0.01)-(0.03-0.26))<1e-12
assert SP("void", "no", 3, 0.24, 0.02, None)==-0.02, "void: the cost comes back, the fee is assumed kept"
c=fresh([("KXRAIN-S1","yes",3,1.26,0.06),("KXRAIN-S2","no",3,0.24,0.02),("KXRAIN-V1","no",2,0.30,0.02),("KXRAIN-S3","yes",1,0.40,0.02),
         ("KXRAIN-S4","yes",1,0.40,0.02),("KXRAIN-Y1","yes",2,0.80,0.03)],["KXRAIN-S1","KXRAIN-Y1"])
mk_={"KXRAIN-S1": fin(result="scalar", settlement_value_dollars="0.9900"), "KXRAIN-S2": fin(result="scalar", settlement_value_dollars="0.9900"),
     "KXRAIN-V1": fin(result="void"), "KXRAIN-S3": dict(result="scalar", status="determined", settlement_value_dollars="0.99"),
     "KXRAIN-S4": fin(result="scalar"), "KXRAIN-Y1": fin(result="yes")}
kalshi.get=lambda t: dict(mk_[t])
_, out=quiet(strategy.settle, c)   # the default lookup reads Kalshi's market (strategy.market_of)
c2=sqlite3.connect("paper.db")
got={t: (s_, r, None if p is None else round(p, 6)) for t, s_, r, p in c2.execute("select ticker,status,result,pnl from trades")}
assert got=={"KXRAIN-S1": ("settled", "scalar", 1.65), "KXRAIN-S2": ("settled", "scalar", -0.23), "KXRAIN-V1": ("settled", "void", -0.02),
             "KXRAIN-S3": ("open", None, None), "KXRAIN-S4": ("open", None, None), "KXRAIN-Y1": ("settled", "yes", 1.17)}, got
assert dict(c2.execute("select ticker,result from obs").fetchall())=={"KXRAIN-S1": None, "KXRAIN-Y1": "yes"}, "the gate scores yes/no only"
assert "SETTLED KXRAIN-S1 yes x3: Kalshi settled it scalar at $0.9900 a contract, P&L +1.65" in out and "KXRAIN-V1 no x2: Kalshi settled it void (cost returned)" in out, out
assert "SETTLE WARNING: KXRAIN-S4 is finalized with result 'scalar'" in out and "KXRAIN-S3" not in out.split("SETTLE WARNING")[-1], out
assert strategy.result_of("KXRAIN-S1", sleep=lambda s: None)=="scalar"
assert c2.execute("select count(*) from market_results where ticker like 'KXRAIN-S%' or ticker like 'KXRAIN-V%'").fetchone()[0]==0, \
    "the ledger's market results stay yes/no"
c2.close()
# what was open no longer holds room under the 15% cap: only the two undecided trades count
assert abs(c.execute("select coalesce(sum(cost+fee),0) from trades where status='open'").fetchone()[0]-0.84)<1e-9
c.close()
# the account view closes them with what they paid (P&L + cost + fee), not as open trades
import account_view
L=account_view.main_ledger([dict(id=1,ts=1,ticker="KXRAIN-26OCT30-PHX",side="yes",n=3,price=0.42,cost=1.26,fee=0.06,status="settled",result="scalar",pnl=1.65,settled_ts=2),
                            dict(id=2,ts=1,ticker="KXRAIN-26OCT30-PHX",side="no",n=2,price=0.15,cost=0.30,fee=0.02,status="settled",result="void",pnl=-0.02,settled_ts=2),
                            dict(id=3,ts=1,ticker="KXRAIN-26OCT31-SEA",side="no",n=2,price=0.10,cost=0.20,fee=0.01,status="settled",result="yes",pnl=-0.21,settled_ts=2)],25.0,0)
assert [(x["status"], round(x["payout"], 6)) for x in L["trades"]]==[("won", 2.97), ("lost", 0.30), ("lost", 0.0)], L["trades"]
assert abs(sum(b for _, b in L["events"])-(1.65-0.02-0.21))<1e-6, L["events"]
# the limit-order ledger (shadow.settle) uses the same rule (review 2026-11-06)
import shadow
if os.path.exists("paper.db"): os.remove("paper.db")
c=core.db(); shadow.tables(c)
for t, side, n, cost in (("KXRAIN-S1", "no", 3, 0.24), ("KXRAIN-V1", "yes", 2, 0.80), ("KXRAIN-Y1", "yes", 2, 0.80), ("KXRAIN-S4", "yes", 1, 0.40)):
    c.execute("insert into shadow_orders(ts,ticker,strategy,version,side,price,fair,n,cost,fee,cancel_ts,status,fill_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (time.time()-86400, t, "maker", "v3", side, cost/n, 0.5, n, cost, 0.0, time.time()-3600, "filled", time.time()-7200))
c.commit()
shadow._markets=lambda ts: {t: dict(mk_[t]) for t in ts}
def no_candles(*a, **k): raise AssertionError("no price history is needed here")
shadow._candles=no_candles
quiet(shadow.settle, c)
got={t: (st, r, None if p is None else round(p, 6)) for t, st, r, p in c.execute("select ticker,status,result,pnl from shadow_orders")}
assert got=={"KXRAIN-S1": ("settled", "scalar", -0.21), "KXRAIN-V1": ("settled", "void", 0.0), "KXRAIN-Y1": ("settled", "yes", 1.2),
             "KXRAIN-S4": ("filled", None, None)}, got
c.close()
print("scalar and void settlements: paper trades and the limit-order ledger close with Kalshi's value, the gate keeps yes/no only, the account view agrees: ok")
print("settle under network errors: all checks passed")
