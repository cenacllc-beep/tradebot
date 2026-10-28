"""research/structure.py on fake markets (no network): ladder order, bucket sums, exhaustiveness, fees, confirmation.
python test_structure.py WORK OUT"""
import os, sys, shutil
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); import structure as S
S.DATA=os.path.join(OUT,"data"); S.OUT=os.path.join(OUT,"results")
def m(t,st,lo=None,hi=None,bid=None,ask=None): return dict(ticker=t,event_ticker="EV",strike_type=st,floor_strike=lo,cap_strike=hi,yes_bid_dollars=bid,yes_ask_dollars=ask)
assert S.fee1(0.5)==0.02 and S.fee1(0.5,0.5)==0.01 and S.fee1(0.02)==0.01
# greater ladder: P(>60) must be >= P(>62). Here >62 bids 0.55 while >60 asks 0.40: buy YES(>60) + NO(>62)
g=[m("G60","greater",60,None,0.38,0.40),m("G62","greater",62,None,0.55,0.57),m("G64","greater",64,None,0.20,0.22)]
v=S.ladder_violations(g); assert len(v)==1 and v[0]["buy_yes"]=="G60" and v[0]["buy_no"]=="G62", v
assert abs(v[0]["gross"]-0.15)<1e-9 and abs(v[0]["net"]-(0.15-S.fee1(0.40)-S.fee1(0.45)))<1e-9
l=[m("L60","less",None,60,0.50,0.52),m("L62","less",None,62,0.40,0.45)]   # P(<60) bid 0.50 > P(<62) ask 0.45: buy YES(<62) + NO(<60)
v=S.ladder_violations(l); assert len(v)==1 and v[0]["buy_yes"]=="L62" and v[0]["buy_no"]=="L60" and abs(v[0]["gross"]-0.05)<1e-9, v
assert S.ladder_violations([m("A","greater",60,None,0.30,0.32),m("B","greater",62,None,0.20,0.22)])==[]   # consistent ladder
# buckets: low tail <58, 58-59, 60-61, high tail >61
bk=[m("T58","less",None,58,0.10,0.12),m("B58","between",58,59,0.30,0.32),m("B60","between",60,61,0.40,0.42),m("T61","greater",61,None,0.25,0.27)]
assert S.exhaustive(bk)[0] and not S.exhaustive([bk[0],m("B59","between",59,60,0.3,0.32),bk[2],bk[3]])[0]   # 58 missing at the low tail
assert not S.exhaustive([bk[0],bk[1],m("B61","between",61,62,0.4,0.42),bk[3]])[0] and not S.exhaustive([bk[0],bk[1],bk[2],m("T62","greater",62,None,0.2,0.3)])[0]   # 60 missing; 62 missing
ex,why=S.exhaustive(bk); assert ex, why
assert not S.exhaustive(bk[:2]+bk[3:])[0]   # a missing bucket breaks exhaustiveness
c=S.bucket_checks(bk,True); k={x["kind"]:x for x in c}
assert abs(k["all_no"]["sum_bids"]-1.05)<1e-9 and abs(k["all_no"]["gross"]-0.05)<1e-9 and k["all_no"]["net"]<0.05, k   # 5c gross, minus four NO fees
assert abs(k["all_yes"]["sum_asks"]-1.13)<1e-9 and k["all_yes"]["gross"]<0
assert S.bucket_checks(bk,False)==[]   # not mutually exclusive: no basket claims
# confirmation reads the books; a stale listing that is gone in the book is not confirmed
books={"G60":{"yes_dollars":[["0.3800","5"]],"no_dollars":[["0.6000","7"]]},"G62":{"yes_dollars":[["0.5500","3"]],"no_dollars":[["0.4300","9"]]}}
S.http=lambda path,params=None: {"orderbook_fp":books[path.split("/")[2]]}
r=S.confirm(dict(kind="ladder_greater",buy_yes="G60",buy_no="G62"))
assert r["still"] and r["size"]==3.0 and abs(r["net"]-(0.55-0.40-S.fee1(0.40)-S.fee1(0.45)))<1e-9, r   # YES ask 1-0.60; size = min(7, 3)
books["G62"]["yes_dollars"]=[["0.3500","3"]]; assert not S.confirm(dict(kind="ladder_greater",buy_yes="G60",buy_no="G62"))["still"]
# a full scan on a fake exchange writes the run and the report
def fake(path,params=None):
    params=params or {}
    if path=="/series": return {"series":[{"ticker":"KXHIGHX"}]}
    if path=="/series/KXHIGHX": return {"series":{"fee_multiplier":1}}
    if path=="/markets": return {"markets":[dict(x,event_ticker="KXHIGHX-26OCT23") for x in g],"cursor":""}
    if path.startswith("/events/"): return {"event":{"mutually_exclusive":False}}
    if path.endswith("/orderbook"): return {"orderbook_fp":books[path.split("/")[2]]}
    raise AssertionError(path)
books["G62"]["yes_dollars"]=[["0.5500","3"]]; S.http=fake
rec=S.scan()
assert rec["events"]==1 and rec["markets"]==3 and any((v.get("confirm") or {}).get("still") for v in rec["found"])
assert "still positive in the live order book: 1" in open(os.path.join(S.OUT,"structure.md"),encoding="utf-8").read()
print("structure.py: all checks passed")
