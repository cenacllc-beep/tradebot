"""Fees and incentives (fees.py), resolution-certainty states (resolution.py), research-only enforcement and the
open-position convergence view. python test_engines.py WORK OUT"""
import os, sys, re, time
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); sys.path.insert(0,WORK)
import fees, resolution as R, control_view as CV, core
# ---- fees ----
assert fees.taker(0.5)==0.02 and fees.taker(0.5,10)==0.18 and fees.taker(0.5,1,0.5)==0.01 and fees.taker(0.5,1,1.0,"flat") is None
for p in (0.03,0.3,0.5,0.77):
    for n in (1,7,40): assert fees.taker(p,n)==core.fee(p,n), (p,n)   # the same numbers as the frozen v3 fee for weather
assert fees.maker(0.5)==(0.0,True) and fees.maker(0.5,10,1.0,"quadratic_with_maker_fees")==(0.05,False)
assert abs(fees.net_edge(0.60,0.50)-0.08)<1e-12 and fees.net_edge(0.6,0.5,fee_type="flat") is None
assert fees.INCENTIVES_ELIGIBLE is False and fees.with_incentives(1.0,5.0)==1.0   # rewards never added until eligibility is confirmed
# ---- resolution states (whole-degree CLI values; margin 1 degree, as in PLAN3 test A) ----
c=R.classify
assert c("high","greater",60,None,62,True)["state"]=="MATHEMATICALLY_DETERMINED" and c("high","greater",60,None,62,True)["outcome"]=="yes"
assert c("high","greater",60,None,61,True)["state"]=="HIGH_CONFIDENCE"           # 1 degree past: within the margin
assert c("high","greater",60,None,60,True)["state"]=="UNCERTAIN"                 # can still rise
assert c("high","less",None,60,61,True)["outcome"]=="no" and c("high","less",None,60,61,True)["state"]=="MATHEMATICALLY_DETERMINED"
assert c("high","less",None,60,60,True)["state"]=="HIGH_CONFIDENCE"
assert c("high","between",58,59,61,True)["state"]=="MATHEMATICALLY_DETERMINED" and c("high","between",58,59,60,True)["state"]=="HIGH_CONFIDENCE"
assert c("high","between",58,59,57,True)["state"]=="UNCERTAIN"
assert c("low","less",None,40,38,True)["state"]=="MATHEMATICALLY_DETERMINED" and c("low","less",None,40,38,True)["outcome"]=="yes"
assert c("low","greater",40,None,40,True)["outcome"]=="no" and c("low","greater",40,None,40,True)["state"]=="HIGH_CONFIDENCE"
x=c("high","greater",60,None,70,False); assert x["state"]=="UNCERTAIN" and "SOURCE_MISMATCH" in x["reason"]   # not the settlement station
assert c("high","greater",60,None,None,True,published=61)["state"]=="OFFICIAL_SOURCE_PUBLISHED"
assert c("high","greater",60,None,62,True,settled="no")["state"]=="SETTLED"
assert c("high","greater",60,None,62,True)["revision_risk"]
# ---- research engines cannot place orders ----
for f in ("fees.py","resolution.py","risk.py","control_view.py","marks.py","research/structure.py","research/longshot.py","research/lip.py","research/discover.py","research/micro.py","research/combo.py","metrics.py","postmortem.py"):
    s=open(os.path.join(WORK,f),encoding="utf-8").read()
    assert not re.search(r"portfolio|requests\.post|import live\b|from live\b",s), f
# ---- convergence view ----
now=time.time()
tr=[dict(id=1,ticker="KXRAIN-26OCT23-NYC",side="yes",price=0.30,fair=0.45,n=10,cost=3.0,status="open",ts=now-7200)]
mk=[dict(ts=now-3600,marks={"main:1":2.5}),dict(ts=now-1800,marks={"main:1":4.8}),dict(ts=now-60,marks={"main:1":4.6})]
r=CV.convergence_rows(tr,mk)[0]
assert r[3]=="46%" and r[5]=="$1.80" and r[6]=="-$0.50" and r[7]=="$1.60" and "exit test would sell" in r[8], r
assert "waiting for prices" in CV.convergence_rows(tr,[])[0][8]
# ---- post-mortem ----
import postmortem as PM
den=dict(ticker="KXHIGHDEN-26OCT14-T48",side="yes",price=0.01,fair=0.0945,n=53,status="settled",result="no",ts=__import__("calendar").timegm((2026,10,14,13,22,0,0,0,0)))
c_=PM.classify(den); assert c_[:2]==["TIMING_ERROR","LOW_PROBABILITY_BET"], c_   # the Oct 14 9:22 AM run, a 9% chance bought at 1c
ok=dict(ticker="KXRAIN-26OCT23-NYC",side="no",price=0.4,fair=0.7,status="settled",result="yes",ts=PM.day_start("KXRAIN-26OCT23-NYC")-86400)
assert PM.classify(ok)==["NORMAL_VARIANCE"] and PM.classify(dict(ok,result="no"))==["WON"] and PM.classify(dict(ok,status="open"))==[]
dec=dict(ts=1000.0,day_start_ts=5000.0,p_win=0.7,p_fair=0.7,station="CLINYC",inputs_obj={"grid":{"fetched":1000.0-4*3600}})
assert PM.classify(dict(ok,ts=1000.0),dec,station_expected="CLIJFK")==["STALE_DATA","WRONG_SETTLEMENT_SOURCE"]
cal=__import__("calibration").Calib([(0.75,1)]*40+[(0.75,0)]*60)   # 70-80% range wins only 40%
assert "MODEL_CALIBRATION_ERROR" in PM.classify(dict(ok,ts=1000.0),dict(dec,inputs_obj={}),cal) and PM.summary([["WON"],["WON","TIMING_ERROR"]])=={"WON":2,"TIMING_ERROR":1}
okc=__import__("calibration").Calib([(0.55,1)]*15+[(0.55,0)]*15+[(0.15,1)]*9+[(0.15,0)]*51)   # calibrated bins: a loss there is ordinary
assert PM.classify(dict(ok,side="yes",result="no",ts=1000.0),dict(dec,p_win=0.55,p_fair=0.55,inputs_obj={}),okc)==["NORMAL_VARIANCE"]
assert PM.classify(dict(ok,side="no",result="yes",ts=1000.0),dict(dec,p_win=0.85,p_fair=0.15,inputs_obj={}),okc)==["NORMAL_VARIANCE"]
assert PM.day_start("KXRAIN-26OCT23-LAX")-PM.day_start("KXRAIN-26OCT23-NYC")==3*3600 and PM.day_start("KXHIGHDEN-26OCT14-T48")-PM.day_start("KXRAIN-26OCT14-NYC")==2*3600
# ---- metrics (phase 32) ----
import metrics as MT
assert MT.max_drawdown([1,-2,0.5,-1.5,3])==3.0 and MT.max_drawdown([-1])==1.0 and MT.max_drawdown([1,2])==0.0
assert MT.sharpe_like({"a":1,"b":2,"c":3,"d":4})is None and abs(MT.sharpe_like({str(i):v for i,v in enumerate([1,2,3,4,5])})-3/(2.5**0.5))<1e-12
assert MT.correlation({str(i):i for i in range(6)},{str(i):2*i for i in range(6)})==(1.0,6) and MT.correlation({"a":1},{"a":1})==(None,1)
T0=__import__("calendar").timegm((2026,10,14,12,0,0,0,0,0))
tr=[dict(ticker="KXRAIN-26OCT15-NYC",side="yes",price=0.40,fair=0.55,n=10,cost=4.0,fee=0.17,status="settled",result="yes",pnl=5.83,ts=T0,settled_ts=T0+86400),
    dict(ticker="KXRAIN-26OCT15-BOS",side="no",price=0.97,fair=0.99,n=10,cost=9.7,fee=0.03,status="settled",result="no",pnl=0.27,ts=T0,settled_ts=T0+86400),
    dict(ticker="KXRAIN-26OCT16-CHI",side="yes",price=0.30,fair=0.45,n=10,cost=3.0,fee=0.15,status="settled",result="no",pnl=-3.15,ts=T0+86400,settled_ts=T0+2*86400),
    dict(ticker="KXRAIN-26OCT17-NYC",side="no",price=0.98,fair=0.995,n=1,cost=0.98,fee=0.01,status="settled",result="no",pnl=-0.0,ts=T0,settled_ts=T0+3*86400),
    dict(ticker="KXRAIN-26OCT18-NYC",side="yes",price=0.5,fair=0.6,n=1,cost=0.5,fee=0.02,status="open",ts=T0)]
m=MT.summary(tr)
assert m["n"]==4 and (m["wins"],m["profitable"])==(3,2) and abs(m["pnl"]-2.95)<1e-9 and m["contracts"]==31, m   # a win can still lose money after fees
assert abs(m["expected"]-(10*0.15-0.17+10*0.02-0.03+10*0.15-0.15+0.015-0.01))<1e-9 and m["largest_loss"]==-3.15 and abs(m["max_drawdown"]-3.15)<1e-9
assert m["worst_cluster"]=="weather:2026-10-16:midwest" and m["avg_hours"]==(24*3+72)/4 and m["sharpe_like"] is None and m["days"]==3, m
assert MT.summary([tr[-1]]) is None
print("fees, resolution, convergence, post-mortem, metrics: all checks passed")
