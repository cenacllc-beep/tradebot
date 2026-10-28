"""research/markets.py: retries, price checks, fees and missing pairs against a fake network. python test_markets.py WORK OUT"""
import os, sys, json
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import requests, markets
markets.DATA=os.path.join(OUT,"data"); markets.SNAP=os.path.join(markets.DATA,"snap"); markets.OUT=os.path.join(OUT,"results")
markets.time.sleep=lambda s:None
class R:
    def __init__(s,code,body=None): s.status_code=code; s.body=body
    def json(s): return s.body
    def raise_for_status(s):
        if s.status_code>=400: raise requests.HTTPError(response=s)
calls=[]
def fake(answers):
    def g(url,params=None,headers=None,timeout=None):
        calls.append(url); assert headers=={"User-Agent":"tradebot-paper-research/1.0"}, headers
        return answers.pop(0)
    return g
# 404 is not retried; repeated 429 gives up with an error; a 503 then 200 succeeds
calls.clear(); markets.requests.get=fake([R(404)])
try: markets.get("https://x/a"); raise SystemExit("404 should raise")
except requests.HTTPError: pass
assert len(calls)==1, calls
calls.clear(); markets.requests.get=fake([R(429)]*4)
try: markets.get("https://x/b"); raise SystemExit("429s should raise")
except requests.HTTPError: pass
assert len(calls)==4, calls
calls.clear(); markets.requests.get=fake([R(503),R(200,{"ok":1})]); assert markets.get("https://x/c")=={"ok":1} and len(calls)==2
# fees: Kalshi rounds up to the cent; Polymarket uses its schedule's exponent; fees on with no rate -> 7%
assert markets.kfee(0.5)==0.02 and markets.kfee(0.97)==0.01
assert abs(markets.pfee(0.5,0.04,2)-0.04*0.0625)<1e-12 and abs(markets.pfee(0.5,0.04)-0.01)<1e-12
r=markets.poly_row({"id":"9","feesEnabled":True,"feeSchedule":{},"bestBid":"0.4","bestAsk":"0.45"}); assert r["fee_rate"]==0.07 and r["fee_exp"]==1.0
r=markets.poly_row({"id":"9","feesEnabled":False,"bestBid":"0.4","bestAsk":"0.45"}); assert r["fee_rate"]==0.0
# a missing volume does not stop Polymarket paging
pages=[[{"id":"1","volume24hr":None,"bestBid":"0.1","bestAsk":"0.2"},{"id":"2","volume24hr":"900","bestBid":"0.1","bestAsk":"0.2"}],
       [{"id":"3","volume24hr":"10"}]]
markets.requests.get=fake([R(200,pages[0]),R(200,pages[1])]); markets.stamp=lambda:"20261015_0202"; markets.poly()
got=[json.loads(l)["id"] for l in open(os.path.join(markets.SNAP,"poly_20261015_0202.jsonl"))]; assert got==["1","2"], got
# gaps: one good pair, one with a crossed book, one whose Polymarket market is read separately
markets.stamp=lambda:"20261015_0201"
with open(os.path.join(markets.SNAP,"kalshi_20261015_0201.jsonl"),"w") as f:
    for t,b,a in (("KA",0.40,0.42),("KB",0.50,0.50),("KC",0.30,0.33)): f.write(json.dumps(dict(ticker=t,bid=b,ask=a))+"\n")
with open(os.path.join(markets.SNAP,"poly_20261015_0202.jsonl"),"w") as f:
    for i,b,a in (("1",0.45,0.47),("2",0.4,0.5)): f.write(json.dumps(dict(id=i,slug="s"+i,bid=b,ask=a,fee_rate=0.0,fee_exp=1.0))+"\n")
json.dump([dict(kalshi="KA",poly_id="1",same_side=True,identical=True,note="good"),dict(kalshi="KB",poly_id="2",identical=True),
           dict(kalshi="KC",poly_id="77",identical=False)],open(os.path.join(markets.DATA,"pairs.json"),"w",encoding="utf-8-sig"))
calls.clear(); markets.requests.get=fake([R(200,{"id":"77","slug":"s77","bestBid":"0.20","bestAsk":"0.25","feesEnabled":False})])
markets.gaps()
md=open(os.path.join(markets.OUT,"gaps.md"),encoding="utf-8").read()
assert calls==["https://gamma-api.polymarket.com/markets/77"], calls
assert "| KB | - | - | - | - | yes | no usable prices now |" in md, md
# KA: A = 0.42 + 0.02 (Kalshi fee) + (1 - 0.45) = 0.99 ; B = 0.47 + (1 - 0.40) + kfee(0.60)=0.02 -> 1.09 ; best 0.99
assert "| KA / s1 | 0.410 | 0.460 | +0.050 | $0.990 | yes | good |" in md, md
assert "KC / s77" in md and "ONE contract" in md and "20261015_0201" in md and "1 market(s) read separately" in md, md
print("markets.py: all checks passed")
