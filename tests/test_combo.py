"""research/combo.py with fake Kalshi answers, no network: the one-factor copula against the exact two-leg formula,
the implied correlation, snapshots with NO legs, settlement and the out-of-sample report. python test_combo.py WORK OUT"""
import os, sys, math, shutil, random
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research"))
import combo as C
C.DATA=os.path.join(OUT,"data"); C.OUT=os.path.join(OUT,"results")
def boom(*a,**k): raise AssertionError("no network in tests")
C.http=boom
# two legs at 50%: P(both) = 1/4 + arcsin(rho) / (2 pi) exactly
for rho in (0.0,0.3,0.7):
    assert abs(C.joint([0.5,0.5],rho)-(0.25+math.asin(rho)/(2*math.pi)))<1e-4, rho
assert abs(C.joint([0.3,0.6,0.8],0)-0.144)<1e-12 and C.joint([0.3,0.6],0.5)>0.18
r=C.implied_rho([0.5,0.5],0.25+math.asin(0.4)/(2*math.pi)); assert abs(r-0.4)<1e-3, r
assert C.implied_rho([0.5,0.5],0.20) is None   # below independence: negative dependence, outside the model
# snapshot, settle, report on a fake exchange
rnd=random.Random(2); LEGS={}; COMBOS=[]
for i in range(60):
    a,b="KXNBA-G%d-A"%i,"KXNBA-G%d-B"%i; pa,pb=0.4+0.2*rnd.random(),0.4+0.2*rnd.random()
    LEGS[a]=dict(ticker=a,yes_bid_dollars="%.4f"%(pa-0.01),yes_ask_dollars="%.4f"%(pa+0.01)); LEGS[b]=dict(ticker=b,yes_bid_dollars="%.4f"%(pb-0.01),yes_ask_dollars="%.4f"%(pb+0.01))
    jm=C.joint([pa,1-pb],0.5)   # the combo needs A yes and B no; the market prices rho 0.5
    COMBOS.append(dict(ticker="KXMVE-%d"%i,mve_collection_ticker="KXMVENBA",close_time="2026-10-25T00:00:00Z",yes_bid_dollars="%.4f"%(jm-0.005),yes_ask_dollars="%.4f"%(jm+0.005),
                       mve_selected_legs=[dict(event_ticker="KXNBA-G%d"%i,market_ticker=a,side="yes"),dict(event_ticker="KXNBA-G%d"%i,market_ticker=b,side="no")]))
COMBOS.append(dict(COMBOS[0],ticker="KXMVE-X",mve_selected_legs=[dict(market_ticker="KXNBA-MISSING",side="yes")]))   # a leg with no quote: skipped
RES={}
def fake(path,params=None,**k):
    if path=="/markets" and params.get("mve_filter")=="only": return dict(markets=COMBOS,cursor="")
    if path=="/markets": return dict(markets=[dict(LEGS.get(t) or dict(ticker=t),result=RES.get(t,"")) for t in params["tickers"].split(",") if t in LEGS or t in RES])
    raise AssertionError(path)
C.http=fake
rows=C.snapshot(now=1000.0); assert len(rows)==60 and all(abs(r["rho"]-0.5)<0.03 for r in rows), [r["rho"] for r in rows[:5]]
assert all(r["mid"]>r["independent"] for r in rows)
# outcomes drawn from the copula itself (rho 0.5): the copula at the earlier fitted rho scores like the combo's own mid
for r in rows:
    z=rnd.gauss(0,1); ok=all(math.sqrt(0.5)*z+math.sqrt(0.5)*rnd.gauss(0,1)<C.N.inv_cdf(p) for p in r["ps"]); RES[r["ticker"]]="yes" if ok else "no"
C.settle(); sc=C.report()
assert len(sc["combo mid"])==59 and os.path.exists(os.path.join(C.OUT,"combo.md"))
assert abs(sum(sc["copula (earlier rho)"])-sum(sc["combo mid"]))<0.1 and "Implied correlation: median 0.50" in open(os.path.join(C.OUT,"combo.md")).read()
print("combo.py: all checks passed")
