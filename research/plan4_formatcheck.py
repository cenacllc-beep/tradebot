"""PLAN4 format check (no scoring, prints field shapes only): one wallet from the formation fills, a few rows of each
Data API walk, resolutions vs tokens on three formation markets, and Kalshi series/trade fields."""
import os, sys, json, glob, collections, time
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import requests
UA={"User-Agent":"tradebot-paper-research/1.0"}; PM="https://data-api.polymarket.com"; K="https://api.elections.kalshi.com/trade-api/v2"
def get(url,p):
    r=requests.get(url,params=p,headers=UA,timeout=60); time.sleep(0.5)
    try: j=r.json()
    except ValueError: j=r.text[:300]
    return r.status_code,j
def shape(j,n=2,drop=("name","pseudonym","bio","profile_image","profile_image_optimized","x_username","user_name","icon","title","slug","outcome","event_slug","question")):
    if isinstance(j,dict):
        out={k:(v if not isinstance(v,list) else "list[%d]"%len(v)) for k,v in j.items() if k not in ("data",)}
        rows=j.get("data") if isinstance(j.get("data"),list) else None
        return dict(top=out,rows=[{k:v for k,v in r.items() if k not in drop} for r in (rows or [])[:n]])
    if isinstance(j,list): return [{k:v for k,v in r.items() if k not in drop} if isinstance(r,dict) else r for r in j[:n]]
    return j
files=sorted(glob.glob(os.path.join(HERE,"data","pm","fills","*.json")))
cnt=collections.Counter(r["w"] for f in files[:5] for r in json.load(open(f)))
w=cnt.most_common(3)[2][0]; print("wallet",w[:6],"fills in first 5 markets:",cnt[w])
for st,ex in (("CLOSED",{}),("REDEEMABLE",{"include_archived":"true"}),("OPEN",{"include_archived":"true"}),("REDEEMABLE_LOST",{"include_archived":"true"})):
    c,j=get(PM+"/v2/positions",dict(user=w,status=st,limit=3,**ex)); print("\n== positions",st,c); print(json.dumps(shape(j,3),default=str)[:2500])
c,j=get(PM+"/v2/trades",dict(user=w,taker_only="false",side="BUY",start=1704067200,end=1759276800,limit=2)); print("\n== trades user",c); print(json.dumps(shape(j),default=str)[:1500])
c,j=get(PM+"/v2/activity",dict(user=w,type="SPLIT,MERGE,CONVERSION",limit=5)); print("\n== activity",c); print(json.dumps(shape(j,5),default=str)[:1500])
c,j=get(PM+"/v2/activity",dict(user=w,limit=5)); print("\n== activity (no type)",c, collections.Counter(r.get("type") for r in (j.get("data") or [])) if isinstance(j,dict) else j)
F=json.load(open(os.path.join(HERE,"data","pm","formation_markets.json")))["markets"][:3]; cs=",".join(m["condition_id"] for m in F)
c,j=get(PM+"/v2/resolutions",dict(condition=cs)); print("\n== resolutions",c); print(json.dumps(shape(j,6),default=str)[:2500])
c,j=get(PM+"/v2/tokens",dict(condition=cs)); print("\n== tokens",c); print(json.dumps(shape(j,8),default=str)[:2500])
c,j=get(PM+"/v2/trades",dict(condition=F[0]["condition_id"],side="BUY",limit=2)); print("\n== trades condition",c); print(json.dumps(shape(j),default=str)[:1200])
for s in ("KXHIGHNY","KXBTCD","KXMLBGAME"):
    c,j=get(K+"/series/"+s,{}); sr=(j or {}).get("series",{}) if isinstance(j,dict) else {}; print("\n== series",s,c,{k:sr.get(k) for k in ("fee_type","fee_multiplier","frequency","category")})
c,j=get(K+"/historical/cutoff",{}); print("\n== cutoff",c,j)
c,j=get(K+"/markets",dict(series_ticker="KXHIGHNY",status="settled",limit=1)); t=(j.get("markets") or [{}])[0].get("ticker") if isinstance(j,dict) else None
print("market",t)
for path in ("/markets/trades","/historical/trades"):
    c,j=get(K+path,dict(ticker=t,limit=2)); print("\n== kalshi",path,c); print(json.dumps(j,default=str)[:1200])
