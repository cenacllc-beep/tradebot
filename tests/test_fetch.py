"""Offline test of research/fetch.py temp/late/candles with a fake Kalshi. python test_fetch2.py WORK OUT"""
import os, sys, json, shutil, types
from datetime import date, timedelta
WORK=sys.argv[1]; OUT=sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import fetch
fetch.DATA=OUT
calls=[]
def mk(series,d,st,stype,fl,cap,res,vol,cli):
    tag=d.strftime("%y%b%d").upper()
    if stype=="greater": t="%s-%s-T%d"%(series,tag,fl); rule="greater than %d°"%fl
    elif stype=="less": t="%s-%s-T%d"%(series,tag,cap); rule="less than %d°"%cap
    else: t="%s-%s-B%.1f"%(series,tag,fl+0.5); rule="between %d-%d°"%(fl,cap)
    return {"ticker":t,"result":res,"strike_type":stype,"floor_strike":fl,"cap_strike":cap,"volume_fp":str(vol),
            "rules_primary":"If the maximum temperature recorded at Somewhere (%s) for %s, is %s fahrenheit according to The Weather Company"%(cli,d,rule)}
D1=date(2026,7,2); D2=date(2026,9,1); D0=date(2026,6,30)
hist=[mk("KXHIGHNY",D1,"","greater",80,None,"yes",100,"CLINYC"),mk("KXHIGHNY",D1,"","between",78,79,"no",50,"CLINYC"),
      mk("KXHIGHNY",D0,"","greater",80,None,"yes",100,"CLINYC")]   # D0 before the holdout: dropped
live=[mk("KXHIGHNY",D2,"","greater",85,None,"no",10,"CLINYC"),mk("KXHIGHNY",D2,"","less",None,70,"no",10,"CLINYC"),
      mk("KXHIGHTSAN",D2,"","greater",75,None,"yes",30,"CLISAN")]
dup=dict(live[0]); dup["ticker"]=live[0]["ticker"]+"X"; dup["volume_fp"]="5"   # same contract, less volume: dropped
live.append(dup)
def candle(ts,bid,ask,plo=None,phi=None):
    return {"end_period_ts":ts,"yes_bid":{"close_dollars":str(bid),"high_dollars":str(bid)},"yes_ask":{"close_dollars":str(ask),"low_dollars":str(ask)},
            "price":{"low_dollars":None if plo is None else str(plo),"high_dollars":None if phi is None else str(phi)},"volume_fp":"1"}
def series_candles(d,tz):
    s=fetch.utc(d,0,55)
    return [candle(s-120,0.40,0.44),candle(s+60,0.41,0.45),candle(fetch.utc(d,3,30)-60,0.50,0.53),candle(fetch.utc(d,3,30)+120,0.52,0.54,0.51,0.55),candle(fetch.utc(d,tz),0.60,0.62)]
BIG=False
def fake_get(url,params=None,pause=0,tries=6):
    calls.append((url,dict(params or {})))
    r=types.SimpleNamespace()
    p=params or {}
    if url.endswith("/series"): j={"series":[{"ticker":"KXHIGHNY"},{"ticker":"KXHIGHTSAN"},{"ticker":"KXRAIN"}]}
    elif url.endswith("/historical/markets"): j={"markets":[m for m in hist if m["ticker"].startswith(p["series_ticker"]+"-")],"cursor":None}
    elif url.endswith("/markets") and p.get("status")=="settled": j={"markets":[m for m in live if m["ticker"].startswith(p["series_ticker"]+"-")],"cursor":None}
    elif "/historical/markets/" in url:
        t=url.split("/")[-2]; d=fetch.mday(t); j={"candlesticks":series_candles(d,5)}
    elif url.endswith("/markets/candlesticks"):
        ts=p["market_tickers"].split(",")
        if BIG and len(ts)>1: j={"markets":[{"market_ticker":t,"candlesticks":[candle(0,0.1,0.2)]*6000} for t in ts]}
        else: j={"markets":[{"market_ticker":t,"candlesticks":series_candles(fetch.mday(t),{"KSAN":8}.get(fetch.station_of([m for m in live if m["ticker"]==t][0]),5))} for t in ts]}
    else: raise AssertionError(url)
    r.json=lambda j=j:j; return r
fetch.get=fake_get
fetch.temp()
rows=[json.loads(l) for l in open(os.path.join(OUT,"kalshi_temp.jsonl"))]
print(len(rows),"rows"); [print(" ",r["ticker"],r["station"],r["strike_type"],r["floor"],r["cap"],r["rule_numbers"],r["scan_bid"],r["scan_ask"],r["late_bid"],r["late_ask"],r["late_lo"],r["late_hi"],r["start_bid"],r["start_ask"],r["lo_after"],r["hi_after"]) for r in rows]
assert len(rows)==5 and not any(r["ticker"].endswith("X") for r in rows) and not any(r["day"]=="2026-06-30" for r in rows)
r=[x for x in rows if x["station"]=="KSAN"][0]; assert r["start_ts"]==fetch.utc(D2,8)
n=[x for x in rows if x["ticker"]=="KXHIGHNY-26JUL02-T80"][0]
assert (n["scan_bid"],n["scan_ask"])==(0.40,0.44), "quote at scan = last candle ending at or before 00:55"
assert (n["late_bid"],n["late_ask"],n["late_lo"],n["late_hi"])==(0.50,0.53,0.51,0.60) and (n["start_bid"],n["start_ask"])==(0.60,0.62)
assert n["rule_numbers"]==[80.0] and [x for x in rows if x["strike_type"]=="between"][0]["rule_numbers"]==[78.0,79.0], "rule numbers"
assert json.load(open(os.path.join(OUT,"temp_stations.json")))==["KNYC","KSAN"]
# late(): rain rows -> quote at 03:30 UTC
with open(os.path.join(OUT,"kalshi_rain.jsonl"),"w") as f:
    for m in live[:3]:
        d=fetch.mday(m["ticker"]); f.write(json.dumps(dict(ticker=m["ticker"],day=d.isoformat(),station="KNYC",hist=False,start_ts=fetch.utc(d,5)))+"\n")
fetch.late(); L=[json.loads(l) for l in open(os.path.join(OUT,"kalshi_rain_late.jsonl"))]
assert len(L)==3 and (L[0]["late_bid"],L[0]["late_ask"])==(0.50,0.53), L[0]
fetch.late(); assert len(open(os.path.join(OUT,"kalshi_rain_late.jsonl")).readlines())==3, "late() is resumable"
# candle cap: a batch near 10,000 candles is asked again in halves
BIG=True; n0=len(calls)
got=fetch.candles([(m["ticker"],False,0,10) for m in live[:3]])
print("cap split calls:",len(calls)-n0,{k:len(v) for k,v in got.items()})
assert len(got)==3 and len(calls)-n0==5 and all(len(v)==5 for v in got.values())
print("fetch temp/late/candles: ok")
