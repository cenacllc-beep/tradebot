"""research/lip.py (PLAN5 test L) on fake Kalshi answers, no network: the reward rule, the queue-aware fill rule, one
sample per hour, the sampling window, the close-date cap, fills with prorated rewards and the mid after each fill,
settlement with a per-market fallback, and the single score with its conditions.
python test_lip.py WORK OUT"""
import os, sys, json, shutil
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import lip as P
P.DATA=os.path.join(OUT,"data"); P.OUT=os.path.join(OUT,"results")
def boom(*a,**k): raise AssertionError("no network in tests: %s"%(a[:1],))
P.http=boom
# ---- the reward rule ----
book={"yes":[["0.4000","100"],["0.4200","150"],["0.4500","50"]],"no":[["0.5000","900"],["0.5300","300"]]}
prog=dict(target_size_fp="1000.00",discount_factor_bps=5000,period_reward=1000000,start_date="2026-10-15T00:00:00Z",end_date="2026-10-22T00:00:00Z")
# YES: best 45 (50), 42 (150) -> cumulative 200 = target/5 at 42: reference 42; qualifying 50 + 150 + 100 x 0.5^2 = 225
lad=P.ladder(book,"yes"); qual,share,tot=P.side_score(lad,1000,0.5,10)
assert lad==[(45,50.0),(42,150.0),(40,100.0)] and qual==225 and abs(share-10/235)<1e-12 and tot==300, (lad,qual,share)
qt,why=P.quote(book,prog)
assert why is None and qt["yes_bid"]==45 and qt["no_bid"]==53 and qt["yes_queue"]==50 and qt["no_queue"]==300 and not qt["valid"], qt   # YES side holds only 300 < 1000
assert qt["reward_10"]==0.0 and abs(qt["capital_10"]-10*(0.45+0.53))<1e-9
book2={"yes":[["0.4000","800"],["0.4500","300"]],"no":[["0.5000","700"],["0.5300","400"]]}
qt,why=P.quote(book2,prog); assert qt["valid"], qt
sy=10/(300+800*0.5**5+10)   # reference 45 (300 >= 200); 40 is 5 cents below
sn=10/(400+700*0.5**3+10)   # reference 53 (400 >= 200); 50 is 3 cents below
rate=1000000*3600/(7*86400)
assert abs(qt["reward_10"]-rate*1e-4*(sy+sn)/2)<1e-12 and abs(qt["share_10"]-(sy+sn)/2)<1e-12, (qt,sy,sn)
assert abs(rate*1e-4*7*24-100.0)<1e-9   # 1,000,000 units a week = $100 a week at 1/10,000 dollar
assert P.quote({"yes":[["0.6000","5"]],"no":[["0.4000","5"]]},prog)==(None,"locked or crossed book")
assert P.quote({"yes":[],"no":[]},prog)==(None,"no bids")
# ---- the fill rule ----
qt=dict(yes_bid=45,no_bid=53,yes_queue=300,no_queue=400)
def tr(side,yes,n,t=None): return dict(taker_side=side,yes_price_dollars="%.4f"%yes,no_price_dollars="%.4f"%(1-yes),count_fp="%.2f"%n,
                                       **({"created_time":__import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",__import__("time").gmtime(t))} if t else {}))
assert P.fills([tr("no",0.45,250)],qt,10)=={"yes":0,"no":0}          # still behind the 300 ahead of us
assert P.fills([tr("no",0.45,200),tr("no",0.45,105)],qt,10)=={"yes":5,"no":0}   # 305 traded at our price: 5 reach us
assert P.fills([tr("no",0.44,1)],qt,10)=={"yes":10,"no":0}           # traded through our price: filled in full
assert P.fills([tr("yes",0.46,500)],qt,10)=={"yes":0,"no":0}         # NO price 54: above our 53 bid, never reaches us
assert P.fills([tr("yes",0.47,405)],qt,10)=={"yes":0,"no":5}         # NO price 53 = our bid: 5 beyond the 400 ahead
assert P.fills([tr("yes",0.48,1),tr("no",0.44,1)],qt,10)=={"yes":10,"no":10} and P.fills([tr("yes",0.48,1)],qt,1)=={"yes":0,"no":1}
assert P.fills([dict(taker_side="no",yes_price=44,count=2)],qt,10)=={"yes":10,"no":0}   # cents fields read too
# fill moment and the price move after it (adverse selection)
seq=[tr("no",0.45,200,1000),tr("no",0.45,105,1010),tr("yes",0.40,3,1080),tr("yes",0.38,2,1320)]   # YES fell after our YES fill
f,w=P.fills(seq,qt,10,detail=True); assert f=={"yes":5,"no":0} and w["yes"]==1010, (f,w)
def cd(t,b,a,cents=False): return dict(end_period_ts=t,yes_bid={"close":b} if cents else {"close_dollars":"%.4f"%(b/100)},yes_ask={"close":a} if cents else {"close_dollars":"%.4f"%(a/100)})
cs=[cd(960,45,47),cd(1070,40,42),cd(1310,37,39,cents=True)]   # the mid falls after our YES fill at 1010
assert P.mid_at(cs,900) is None and abs(P.mid_at(cs,1069)-0.46)<1e-9 and abs(P.mid_at(cs,5000)-0.38)<1e-9
a=P.adverse_mid(cs,"yes",w["yes"],45); assert abs(a["60"]+0.04)<1e-9 and abs(a["300"]+0.07)<1e-9, a   # mid 41 after 1 minute, 38 after 5: against us
b=P.adverse_mid(cs,"no",1010,53); assert abs(b["60"]-0.06)<1e-9, b   # the NO side gained: 1 - 0.41 - 0.53
assert P.adverse_mid(cs,"yes",None,45)=={"60":None,"300":None} and P.adverse_mid([cd(960,50,49)],"yes",1010,45)["60"] is None   # crossed candle: unreadable
# ---- an end-to-end run on a fake exchange and a fake clock ----
import random
T0=P.START+1800   # 2026-10-24 00:30 local
progs=[dict(market_ticker="KXRAIN-26OCT20-C%d"%i,start_date="2026-10-22T00:00:00Z",end_date="2026-10-29T00:00:00Z",period_reward=1000000,
            target_size_fp="1000.00",discount_factor_bps=5000,incentive_type="liquidity") for i in range(60)]
progs+=[dict(progs[0],market_ticker="KXRAIN-26NOV30-C1"),dict(progs[0],market_ticker="KXBTCD-X"),dict(progs[0],market_ticker="KXHIGHNY-26OCT20-T60"),dict(progs[0],market_ticker="KXLOWTDEN-26OCT20-T40",incentive_type="volume")]
MK={p["market_ticker"]:dict(ticker=p["market_ticker"],status="active",close_time="2026-10-28T05:00:00Z",result="") for p in progs}
MK["KXRAIN-26OCT20-C59"]["status"]="closed"; MK["KXRAIN-26OCT20-C58"]["close_time"]="2026-10-24T05:00:00Z"
MK["KXRAIN-26NOV30-C1"]["close_time"]="2026-11-30T05:00:00Z"   # settles after the score date: left out
HIDE={"KXRAIN-26OCT20-C3","KXRAIN-26OCT20-C4"}   # the batch call leaves these out once settled; asked one by one
FEE={"KXRAIN":"quadratic","KXHIGHNY":"quadratic_with_maker_fees"}
calls={"programs":0,"books":0,"trades":0,"candles":0,"single":0}
def fake(path,params=None,**k):
    params=params or {}
    if path=="/incentive_programs":
        calls["programs"]+=1; i=int(params.get("cursor") or 0); page=progs[i*40:(i+1)*40]
        return dict(incentive_programs=page,next_cursor=str(i+1) if (i+1)*40<len(progs) else "")
    if path.endswith("/candlesticks"):
        calls["candles"]+=1; assert params["period_interval"]==1 and params["end_ts"]-params["start_ts"]>=3600+420, params
        return dict(candlesticks=[cd(params["start_ts"]+60,45,47),cd(params["end_ts"]-60,30,32)])
    if path.startswith("/series/"): return dict(series=dict(fee_type=FEE.get(path[8:])))
    if path=="/markets": return dict(markets=[MK[t] for t in params["tickers"].split(",") if t in MK and not (t in HIDE and MK[t]["result"])])
    if path.startswith("/markets/") and path[9:] in MK: calls["single"]+=1; return dict(market=MK[path[9:]])
    if path.endswith("/orderbook"):
        calls["books"]+=1; return dict(orderbook_fp=dict(yes_dollars=[["0.4000","800"],["0.4500","300"]],no_dollars=[["0.5000","700"],["0.5300","400"]]))
    if path=="/markets/trades":
        calls["trades"]+=1; t=params["ticker"]; k=int(t.split("C")[-1])
        ts=params["min_ts"]+600
        return dict(trades=[tr("no",0.44,1,ts)] if k%3==0 else ([tr("yes",0.48,1,ts)] if k%3==1 else []),cursor="")
    raise AssertionError(path)
P.http=fake
P.sample(now=P.START-60); assert not P.rows_of("samples")   # before the window: nothing
P.sample(now=T0); ss=P.rows_of("samples")
H=json.load(open(os.path.join(P.DATA,"hours.json")))[str(int(T0//3600))]
assert len(ss)==40 and H["universe"]==58 and H["skipped"]=={"not active":1,"closes within 2 hours":1,"settles after the score date":1,"fee type not quadratic":1}, H   # BTC and volume programs never listed
assert all(s["ticker"].startswith("KXRAIN") for s in ss) and calls["books"]==40
want=sorted(random.Random(int(T0//3600)).sample(sorted(t for t in MK if t.startswith("KXRAIN") and t not in ("KXRAIN-26OCT20-C59","KXRAIN-26OCT20-C58","KXRAIN-26NOV30-C1")),40))
assert [s["ticker"] for s in ss]==want   # the hour seeds the draw
P.sample(now=T0+600); assert len(P.rows_of("samples"))==40 and calls["programs"]==2   # same hour: not again; programs cached
assert not P.rows_of("fills")   # the hour is not over yet
real_fake=fake
def fake_c(path,params=None,**k):   # candles fail for one market: its fills are still recorded
    if path.endswith("/candlesticks") and "C0/" in path: raise RuntimeError("HTTP 500 (test)")
    return real_fake(path,params,**k)
P.http=fake_c
P.sample(now=T0+3700); assert not P.rows_of("fills")   # 7 more minutes for the 5-minute check
P.sample(now=T0+4100); fl=P.rows_of("fills")
assert len(fl)==40 and len(P.rows_of("samples"))==80, len(fl)
P.sample(now=T0+4200); assert len(P.rows_of("fills"))==40   # each hour checked once
P.http=real_fake
c0=[r for r in fl if r["ticker"]=="KXRAIN-26OCT20-C0"]
if c0: assert c0[0]["candles_failed"] and c0[0]["fill_10"]=={"yes":10,"no":0} and c0[0]["adverse_10"]["yes"]=={"60":None,"300":None}, c0
fl=[r for r in fl if not r.get("candles_failed")]
r0=[r for r in fl if int(r["ticker"].split("C")[-1])%3==0][0]; r2=[r for r in fl if int(r["ticker"].split("C")[-1])%3==2][0]
assert r0["fill_10"]=={"yes":10,"no":0} and r0["adverse_10"]["yes"]["60"]==0.01 and r0["adverse_10"]["yes"]["300"]==0.01, r0   # mid 46 standing
assert calls["candles"]==len([r for r in fl if r["fill_10"]["yes"] or r["fill_10"]["no"]])   # candles only where something filled (the failed call is not counted)
assert r0["candle_check"]["codes"]=={} and r0["candle_check"]["age"]["yes"]["60"]>=0 and "candle_check" not in r2, (r0, r2)   # descriptive record (2026-10-23); none where nothing filled
assert not c0 or "candle_check" not in c0[0]
q0=[s for s in ss if s["ticker"]==r0["ticker"]][0]["quote"]
assert abs(r0["reward_10"]-q0["rate_units"]*1e-4*(q0["share_yes_10"]*600/3600+q0["share_no_10"])/2)<1e-12, r0   # YES side earns until its fill 10 minutes in
assert r2["reward_10"]==[s for s in ss if s["ticker"]==r2["ticker"]][0]["quote"]["reward_10"]   # nothing filled: the whole hour
# settle: results when markets close; score once, not early
for t in MK: MK[t].update(result="yes" if int(t[-1]) % 2 else "no") if t.startswith("KXRAIN") else None
P.settle(now=T0+6*86400); res=json.load(open(os.path.join(P.DATA,"results.json")))
assert len(res)==len({s["ticker"] for s in P.rows_of("samples")}) and calls["single"]==len(HIDE & set(res)), (len(res),calls)
try: P.score(now=T0); raise SystemExit("scored early")
except SystemExit as e: assert "2026-11-25" in str(e), e
P.score(now=P.SCORE_FROM+1); R=json.load(open(os.path.join(P.OUT,"plan5_L.json")))
assert R["spread_only"]["verdict"]=="NOT TESTABLE" and R["with_rewards"]["verdict"]=="NOT TESTABLE" and R["totals"]["samples"]==0, R   # one day, 2 sampled hours
assert R["left_out"]=={"no fill check":40,"market not settled":0,"day with under 12 sampled hours":40}, R["left_out"]   # the second hour is not checked yet
try: P.score(now=P.SCORE_FROM+2); raise SystemExit("scored twice")
except SystemExit as e: assert "once" in str(e), e
# ---- the score's rule on a synthetic 20-day record (no network) ----
def world(edge,usd=None,unsettled=0):
    shutil.rmtree(P.DATA,ignore_errors=True); os.makedirs(P.DATA); [os.remove(os.path.join(P.OUT,f)) for f in os.listdir(P.OUT)]
    rnd=random.Random(5); ss=[]; fl=[]; res={}
    for d in range(20):
        for h in range(12):
            for k in range(10):
                t="KXRAIN-D%d-H%d-M%d"%(d,h,k); ts=P.START+d*86400+h*3600+60
                q=dict(yes_bid=45,no_bid=50,yes_queue=0,no_queue=0,valid=True,reward_1=0.0003,reward_10=0.003,reward_100=0.02,capital_1=0.95,capital_10=9.5,capital_100=95,share_10=0.1)
                if usd is not None: q["usd_per_day"]=usd
                ss.append(dict(ts=ts,hour=int(ts//3600),ticker=t,series="KXRAIN",quote=q))
                yes=rnd.random()<(0.45+edge)   # edge > 0: our YES fills win more often than the price says
                f={"yes":2 if rnd.random()<0.5 else 0,"no":0}
                fl.append(dict(hour=int(ts//3600),ticker=t,fill_1={"yes":min(1,f["yes"]),"no":0},fill_10=f,fill_100=f)); res[t]="yes" if yes else "no"
    for t in sorted(res)[:unsettled]: del res[t]
    P.append(os.path.join(P.DATA,"samples.jsonl"),ss); P.append(os.path.join(P.DATA,"fills.jsonl"),fl); P.save(os.path.join(P.DATA,"results.json"),res)
    P.score(now=P.SCORE_FROM+1); return json.load(open(os.path.join(P.OUT,"plan5_L.json")))
G=world(0.15); B=world(-0.30)
assert G["spread_only"]["verdict"]=="PASS" and G["with_rewards"]["verdict"]=="PASS" and G["totals"]["filled"]>=100 and G["events_with_fills"]>=20, (G["spread_only"],G["with_rewards"],G["totals"])
assert G["with_rewards"]["applies"] is False and G["headline_return_per_dollar_hour"]==G["spread_only"]["mean_return_per_dollar_hour"]   # not eligible: the spread-only figure is the headline
assert abs(G["dollars_per_day_at_25"]-G["headline_return_per_dollar_hour"]*25*24)<1e-12
assert B["with_rewards"]["verdict"]=="FAIL" and not B["with_rewards"]["fills_not_eating_rewards"] and B["spread_only"]["verdict"]=="FAIL", B
# the SE is never below the null SE: 2 contracts of one event move together
units=[(0.1,9.5,"d1","e%d"%i,2*(0.45*0.55)**0.5) for i in range(30)]; m,se=P.ratio_se(units)
assert abs(m-0.1/9.5)<1e-12 and se>=(30*(2*(0.45*0.55)**0.5)**2)**0.5/(30*9.5)-1e-12, (m,se)
U=world(0.15,usd=5000.0); assert U["with_rewards"]["verdict"]=="NOT TESTABLE" and U["spread_only"]["verdict"]=="PASS", U["with_rewards"]   # $5,000 a day is outside Kalshi's $1-$1,000: a unit error
N=world(0.15,unsettled=200); assert N["spread_only"]["verdict"]=="NOT TESTABLE" and N["unsettled_filled_samples"]>0.02*N["totals"]["samples"], N   # too many filled samples unsettled
import fees
fees.INCENTIVES_ELIGIBLE=True; fees.ELIGIBILITY_CONFIRMED_ON="2026-11-01"
E=world(0.15); assert E["with_rewards"]["applies"] is True and E["headline_return_per_dollar_hour"]==E["with_rewards"]["mean_return_per_dollar_hour"]
fees.ELIGIBILITY_CONFIRMED_ON="2026-11-22"; L=world(0.15); assert L["with_rewards"]["applies"] is False   # confirmed after the window ended: reported only
fees.INCENTIVES_ELIGIBLE=False; fees.ELIGIBILITY_CONFIRMED_ON=None
print("lip.py: all checks passed")
