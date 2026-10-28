"""research/plan3.py on synthetic data (no network): decided sides, the quote rules, the single score, and both verdicts.
python test_plan3.py WORK OUT MODE   (MODE: edge = planted edges must PASS; null = no edge must FAIL)"""
import os, sys, json, math, random, calendar, shutil
from datetime import date, timedelta
WORK,OUT,MODE=sys.argv[1],sys.argv[2],sys.argv[3]
shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import plan3 as p3, backtest2 as b2, backtest as bt, fetch
D=os.path.join(OUT,"data"); R=os.path.join(OUT,"results"); os.makedirs(D); os.makedirs(R)
p3.DATA=b2.DATA=D; p3.OUT=b2.OUT=R; p3.LOWM=os.path.join(D,"low_markets.json")
rnd=random.Random(5 if MODE=="edge" else 9)
# ---- unit checks ----
assert p3.decided("greater",80,None,82.0)=="yes" and p3.decided("greater",80,None,81.9) is None
assert p3.decided("between",None,73,75.0)=="no" and p3.decided("between",72,73,74.9) is None
assert p3.decided("less",None,64,65.0)=="no" and p3.decided("less",None,64,64.9) is None and p3.decided("greater",80,None,None) is None
assert abs(p3.upper95(0,200)-0.01487)<2e-4 and abs(p3.upper95(2,200)-0.03106)<3e-4, (p3.upper95(0,200),p3.upper95(2,200))
s=p3.daystat([dict(day="a",pnl=0.1),dict(day="a",pnl=0.3),dict(day="b",pnl=0.0)]); assert abs(s["mean"]-0.1)<1e-12 and s["days"]==2
# decision times are local STANDARD time, fixed per station: 13:00 in New York (UTC-5) = 18:00 UTC; Denver (UTC-7) = 20:00 UTC
lk=p3.looks(dict(day="2026-07-10",station="KNYC",strike_type="greater",floor=80,cap=None),[],fetch.TZ)
assert [x["dec"] for x in lk]==[calendar.timegm((2026,7,10,h,0,0)) for h in (18,20,22)], lk
assert p3.looks(dict(day="2026-07-10",station="KDEN",strike_type="greater",floor=80,cap=None),[],fetch.TZ)[0]["dec"]==calendar.timegm((2026,7,10,20,0,0))
# the 3-report rule counts distinct report times (a corrected duplicate counts once)
dec=calendar.timegm((2026,7,10,18,0,0)); obs=sorted([(dec-600,90.0),(dec-600,90.0),(dec-4000,88.0),(dec-20000,70.0)])
assert p3.looks(dict(day="2026-07-10",station="KNYC",strike_type="greater",floor=80,cap=None),obs,fetch.TZ)[0]["reports3h"]==2
# Kalshi stamps the "latest candle before the start" at the window's start: with the window an hour before the freshness
# limit, an old quote can never look fresh
s0=dec+p3.LAG-p3.FRESH-3600; q=p3.quote_at([dict(end_period_ts=s0,yes_bid=dict(close_dollars="0.02"),yes_ask=dict(close_dollars="0.90"))],dec+p3.LAG)
assert q["end"]<dec+p3.LAG-p3.FRESH and q["ask"]==0.90, q
# candle fetching: a failed batch or an empty answer is asked again one market at a time (live, then the archive)
F=p3.fx(); calls=[]
def fake_candles(items):
    calls.append([(t,h) for t,h,_,_ in items])
    if len(items)>1: raise RuntimeError("HTTP 400 (not retried)")
    t,h,_,_=items[0]
    return {t:([dict(end_period_ts=1)] if (h or t=="LIVE") else [])}
real_candles=F.candles; F.candles=fake_candles
cs=p3.fetch_candles(F,[("LIVE",False,0,1),("MOVED",False,0,1),("OLD",True,0,1)])
F.candles=real_candles
assert cs["LIVE"] and cs["MOVED"] and cs["OLD"] and ("MOVED",True) in sum(calls,[]), (cs,calls)
ST=["KNYC","KMIA","KDEN"]
json.dump(dict(stations=ST,a=0,s0=1,s1=1),open(os.path.join(R,"temp_model.json"),"w"))
def utc(d,h=0,mi=0): return calendar.timegm((d.year,d.month,d.day,0,0,0))+h*3600+mi*60
# ---- Test A data: hourly readings that climb to the day's high by mid-afternoon ----
asos={s:[] for s in ST}; temp=[]; looksq=[]; cli={}
d=date(2026,7,1)
while d<=date(2026,8,29):
    for st in ST:
        off=fetch.TZ[st[1:]]; H=rnd.randint(70,95)   # the CLI high (whole degrees)
        cli.setdefault(st,[]).append(dict(valid=d.isoformat(),precip=0,high=H,low=H-15,product="x"))
        for h in range(24):
            if st=="KDEN" and d.day==5 and 10<=h<=13: continue   # a gap in the reports: the 13:00 and 15:00 looks have too few
            v=H-0.4-max(0,(15-h))*1.5 if h<=15 else H-0.4-(h-15)*1.2
            asos[st].append([utc(d,off+h,51),round(v,1)])
        tag=d.strftime("%y%b%d").upper()
        for kind,fl,cap in (("greater",H-6,None),("greater",H-1,None),("between",H-9,H-8),("between",H-1,H),("less",None,H-5),("less",None,H+2)):
            y=b2.cli_yes(kind,fl,cap,H); res="yes" if y else "no"
            if MODE=="null" and rnd.random()<0.05: res="no" if y else "yes"   # settlement disagrees with the readings 5% of the time
            t="KXHIGHX%s-%s-%s%s"%(st[1:],tag,kind[0].upper(),fl if fl is not None else cap)
            temp.append(dict(ticker=t,day=d.isoformat(),station=st,result=res,strike_type=kind,floor=fl,cap=cap,hist=False))
            qs=[]
            for L in p3.LOOKS:
                dec=utc(d,off+L); px=0.90 if MODE=="edge" else 0.95
                stale=(st=="KMIA" and d.day==7)   # the last quote is 2 hours old: no trade
                side=p3.decided(kind,fl,cap,H-0.4)
                qs.append(dict(look=L,end=dec+p3.LAG-(7200 if stale else 120),bid=round(1-px,2) if side=="no" else 0.5,ask=px if side=="yes" else 0.5))
            looksq.append(dict(ticker=t,n_candles=9,quotes=qs))
    d+=timedelta(days=1)
os.makedirs(os.path.join(D,"asos")); os.makedirs(os.path.join(D,"cli"))
for st,v in asos.items(): json.dump(v,open(os.path.join(D,"asos",st+".json"),"w"))
for st,v in cli.items(): json.dump(v,open(os.path.join(D,"cli","%s_2026.json"%st),"w"))
with open(os.path.join(D,"kalshi_temp.jsonl"),"w") as f:
    for m in temp: f.write(json.dumps(m)+"\n")
with open(os.path.join(D,"kalshi_temp_looks.jsonl"),"w") as f:
    for m in looksq: f.write(json.dumps(m)+"\n")
# a look with too few reports is not decided; a later one can be
m0=sorted([m for m in temp if m["station"]=="KDEN" and m["day"]=="2026-07-05" and m["strike_type"]=="greater"],key=lambda m:m["floor"])[0]
lk=p3.looks(m0,sorted(tuple(x) for x in asos["KDEN"]),fetch.TZ); assert lk[0]["thin"] and lk[0]["side"] is None and lk[2]["side"]=="yes", lk
p3.scoreA(); A=json.load(open(os.path.join(R,"plan3_A.json")))
assert A["look_skips"]["stale_quote"]>0 and A["looks"]["thin_reports"]>0, (A["look_skips"],A["looks"])
try: p3.scoreA(); raise SystemExit("scoreA ran twice")
except SystemExit as e: assert "already exists" in str(e), e
# ---- Test B data ----
LST=["KNYC","KMIA","KDEN","KSEA"]; nbs={}; lows={}
d=date(2025,7,1); markets=[]; lowq=[]
while d<=date(2026,9,15):
    for st in LST:
        txn=55+15*math.sin(d.toordinal()/58.0)+rnd.gauss(0,3); txn=round(txn); xnd=rnd.choice([1,2,2,3])
        e2=rnd.gauss(0,2.5) if MODE=="null" else 0.0   # null: something the forecast misses and the market knows
        low=round(txn-1+e2+rnd.gauss(0,(1+0.5*xnd)*(0.3 if MODE=="null" else 1))); lows.setdefault((st,d.year),[]).append(dict(valid=d.isoformat(),precip=0,high=low+15,low=low,product="x"))
        rt="%s 18:00:00"%(d-timedelta(days=1))
        nbs.setdefault((st,(d-timedelta(days=1)).strftime("%Y%m")),[]).append(dict(runtime=rt,ftime="%s 12:00:00"%d,p06="",q06="",p12="",q12="",txn=str(txn),xnd=str(xnd),tmp="60"))
        if d>=date(2026,7,1):
            mu=txn-1; sd=1+0.5*xnd; tag=d.strftime("%y%b%d").upper()
            for kind,fl,cap in (("less",None,txn-3),("between",txn-3,txn-2),("between",txn-1,txn),("between",txn+1,txn+2),("greater",txn+2,None)):
                p=b2.p_temp(kind,fl,cap,mu,sd); y=b2.cli_yes(kind,fl,cap,low)
                if MODE=="edge": mid=p+rnd.gauss(0,0.20)   # a noisy market, an informed forecast
                else: mid=b2.p_temp(kind,fl,cap,txn-1+e2,0.8)   # an informed market, a forecast that misses e2
                mid=min(max(mid,0.05),0.95); sp=rnd.choice([0.04,0.06,0.10,0.20,0.30]); b=round(max(mid-sp/2,0.01),2); a=round(min(b+sp,0.99),2)
                t="KXLOWTX%s-%s-%s%s"%(st[1:],tag,kind[0].upper(),fl if fl is not None else cap)
                markets.append(dict(ticker=t,series=t.split("-")[0],day=d.isoformat(),station=st,result="yes" if y else "no",strike_type=kind,floor=fl,cap=cap,rule_numbers=[],volume=10,hist=False,rules=""))
                lowq.append(dict(ticker=t,scan_ts=0,start_ts=0,scan_bid=b,scan_ask=a,scan_age=60,n_candles=5,   # some orders fill, some do not
                                 trade_lo=round(b-0.02,2) if rnd.random()<0.6 else round(b+0.01,2),trade_hi=round(a+0.02,2) if rnd.random()<0.6 else round(a-0.01,2)))
    d+=timedelta(days=1)
os.makedirs(os.path.join(D,"nbs"))
for (st,ym),v in nbs.items(): json.dump(v,open(os.path.join(D,"nbs","%s_%s.json"%(st,ym)),"w"))
for (st,y),v in lows.items(): json.dump(v,open(os.path.join(D,"cli","%s_%d.json"%(st,y)),"w"))
json.dump(markets,open(p3.LOWM,"w"))
p3.fitB(); M=json.load(open(os.path.join(R,"low_model.json"))); assert abs(M["a"]+1)<0.3, M
try: p3.fitB(); raise SystemExit("fitB refit")
except SystemExit as e: assert "frozen" in str(e), e
with open(os.path.join(D,"kalshi_low.jsonl"),"w") as f:
    for q in lowq: f.write(json.dumps(q)+"\n")
p3.scoreB(); B=json.load(open(os.path.join(R,"plan3_B.json")))
print("A:",A["verdict"],A["trades"],A["profit_per_contract"],A["conditions"]); print("B:",B["verdict"],B.get("conditions"),B["maker"]["fills"],B["maker"]["mean"])
if MODE=="edge": assert A["verdict"]=="PASS" and B["verdict"]=="PASS", (A["conditions"],B["conditions"])
else: assert A["verdict"]=="FAIL" and B["verdict"]=="FAIL" and B["maker"]["fills"]>=150, (A["conditions"],B["conditions"],B["maker"])
assert B["placebo"]["signals"]>0, B["placebo"]   # wide spreads make the placebo trade
assert "Verdict" in open(os.path.join(R,"plan3_A.md"),encoding="utf-8").read() and "Verdict" in open(os.path.join(R,"plan3_B.md"),encoding="utf-8").read()
print("plan3.py (%s): all checks passed"%MODE)
