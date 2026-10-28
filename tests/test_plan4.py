"""research/plan4.py on synthetic data with every network cache pre-filled (no network): time parsing, the SE rules,
trade-list walks and coverage, copy prices, the reweighted placebo, Kalshi orders, copies, series and trade fetches
(fake pages), then a full Polymarket and Kalshi world. python test_plan4.py WORK OUT MODE  (edge: must PASS; null: must FAIL)"""
import os, sys, json, random, shutil, calendar, hashlib
from datetime import datetime, timezone
WORK,OUT,MODE=sys.argv[1],sys.argv[2],sys.argv[3]
shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import plan4 as P
D=os.path.join(OUT,"data"); R=os.path.join(OUT,"results"); os.makedirs(R)
P.DATA=D; P.OUT=R; P.D_PM=os.path.join(D,"pm"); P.D_K=os.path.join(D,"k1")
def boom(*a,**k): raise AssertionError("no network in tests: a cache is missing for %s"%(a[:1],))
P.http=boom
def J(path,obj): os.makedirs(os.path.dirname(path),exist_ok=True); json.dump(obj,open(path,"w"))
def cid(name): return "0x"+hashlib.sha256(name.encode()).hexdigest()   # a 32-byte condition ID (a combo's has 31)
def ymd(t): return datetime.fromtimestamp(t,timezone.utc).strftime("%Y-%m-%d")
def exits(f,text):
    try: f()
    except SystemExit as e: assert text in str(e), e; return
    raise AssertionError("expected an exit containing %r"%text)
rnd=random.Random(11 if MODE=="edge" else 12)

# ---- times ----
E=calendar.timegm((2026,4,9,0,28,21,0,0,0))
for s in ("2026-04-09T00:28:21Z","2026-04-09 00:28:21+00","2026-04-09T00:28:21+00:00","2026-04-09T00:28:21.123456789Z",
          "2026-04-09T00:28:21.12Z","2026-04-09T00:28:21","2026-04-09T02:28:21+02:00","2026-04-08T19:28:21-05"):
    assert P.rts(s)==E, (s,P.rts(s))
assert P.rts("")is None and P.rts(None) is None and P.rts("junk") is None and P.rts("2026-04-09")==calendar.timegm((2026,4,9,0,0,0,0,0,0))
assert P.rts(E)==E and P.rts(str(E))==E and P.rts(E*1000)==E and P.rts(float(E))==E and P.rts(True) is None   # epoch seconds or ms
assert P.cn("0X"+"AB"*32)=="0x"+"ab"*32 and P.cn("ab"*32)=="0x"+"ab"*32 and P.cn(None)==""
assert P.is_combo("0x"+"a"*62) and P.is_combo("a"*62) and not P.is_combo("0x"+"a"*64) and not P.is_combo("A"*64) and P.is_combo(dict(conditionId="0x"+"a"*64,cyom=True))

# ---- the SE rules ----
m,se=P.cl_se([(1.0,0.0,1),(1.0,0.0,2),(1.0,0.0,3)]); assert m==1.0 and se==0.0
m,se=P.cl_se([(0.03,0.04,1),(0.03,0.04,2),(0.03,0.04,3),(0.03,0.04,4)]); assert abs(se-0.1)<1e-12, se   # the null SE floors identical wins
m,se=P.cl_se([(1.0,0,1),(0.0,0,1),(1.0,0,2),(0.0,0,2)]); assert se>0
u=[(0.2,0.01,1),(-0.1,0.02,2),(0.4,0.0,2),(0.0,0.05,3)]
assert P.cl_se(u)==P.cl_se([x+(1.0,) for x in u])                      # weight 1 is the plain formula
m,se=P.cl_se([x+(2.0,) for x in u]); assert abs(m-P.cl_se(u)[0])<1e-12 and abs(se-P.cl_se(u)[1])<1e-12   # equal weights change nothing
m,_=P.cl_se([(1.0,0,1,3.0),(0.0,0,2,1.0)]); assert abs(m-0.75)<1e-12   # weights move the mean

# ---- wallet-events ----
day=86400
def prow(ev,end,first,cond,p,won,size=None,fees=0.0,status="REDEEMABLE",oi=0,pnl=None):
    size=size or 100/p
    return dict(condition_id=cond,token_id="%s-%d"%(cond,oi),outcome_index=oi,event_id=ev,end_date=ymd(end),first_entry_at=first,avg_price=p,
                total_size=size,entry_fees_usdc=fees,entry_cost_usdc=size*p,total_pnl=(size*won-size*p) if pnl is None else pnl,
                current_price=won,realized_pnl=0,status=status,negative_risk=False)
e0=P.F0+30*day; skip={}
rows=[prow("x",e0,e0-day,cid("c1"),0.5,1,fees=2.0),prow("x",e0,e0-day,cid("c2"),0.4,0),prow("y",e0,e0-day,cid("c3"),0.98,1),prow("z",e0,e0-day,cid("c4"),0.5,1,size=10),
      dict(prow("w",e0,e0-day,cid("c5"),0.5,1),end_date="1970-01-01"),prow("x",e0,e0-day,cid("c6")[:-2],0.5,1),
      dict(prow("x",e0,0,cid("c7"),0.5,1),total_size=0.0,avg_price=0.0),prow("x",P.F1+day,e0-day,cid("c8"),0.5,1),prow("v",e0,P.F1+day,cid("c9"),0.5,1)]
we=P.wallet_events(rows,"formation",1.0,skip)
assert set(we)=={"x"} and skip=={"avg_price 0.97 or more":1,"wallet-event under $10":1,"no end date (1970)":1,"combo position":1,"no buys (split, merge, conversion or transfer)":1,"end date outside the window":1}, (we,skip)
x=we["x"]; assert abs(x["cost"]-202)<1e-9 and abs(x["profit"]-(100-100-2))<1e-9, x   # 200 shares at 0.5 won, 250 at 0.4 lost; fees subtracted
assert abs(x["var"]-((200*0.5+250*(0.24**0.5))/202)**2)<1e-12, x

# ---- format check and coverage ----
def walletfiles(w,pos,lost=(),opn=(),buys=()):
    for f in ("positions","fmt_positions","cov_positions"): J(os.path.join(D,"pm",f,w+".json"),dict(fetched="t",rows=list(pos)))
    for f in ("lost_positions","fmt_lost"): J(os.path.join(D,"pm",f,w+".json"),dict(fetched="t",rows=list(lost)))
    for f in ("open_positions","cov_open"): J(os.path.join(D,"pm",f,w+".json"),dict(fetched="t",rows=list(opn)))
    J(os.path.join(D,"pm","buys",w+".json"),dict(fetched="t",rows=list(buys)))
good=[prow("x",e0,e0-day,"g%d"%i,0.5,i%2,fees=1.0,pnl=(200-100-1.0) if i%2 else -100) for i in range(10)]   # winners' total_pnl includes the fee
walletfiles("0xf1",good,lost=[r for r in good if r["current_price"]==0])
ok,fmt=P.format_check(["0xf1"]); assert ok and fmt["fee_adjust"]==0.0 and fmt["pnl_includes_fees"]==5, fmt
walletfiles("0xf2",[dict(r,total_pnl=100.0 if r["current_price"] else -100) for r in good])   # total_pnl leaves the fee out
ok,fmt=P.format_check(["0xf2"]); assert ok and fmt["fee_adjust"]==1.0, fmt
walletfiles("0xf3",good,lost=[prow("x",e0,e0-day,"other",0.5,0)])        # a lost row that the REDEEMABLE walk did not return
ok,fmt=P.format_check(["0xf3"]); assert not ok and fmt["lost_not_in_redeemable"]==1, fmt
walletfiles("0xf4",[dict(r,entry_cost_usdc=r["entry_cost_usdc"]*1.5) for r in good])   # cost does not match size x price
ok,fmt=P.format_check(["0xf4"]); assert not ok and fmt["bad"]==10, fmt
nob=[dict(prow("x",e0,0,cid("n%d"%i),0.5,0),total_size=0.0,avg_price=0.0,entry_cost_usdc=0.0) for i in range(30)]   # tokens from splits: no buys
cl=[dict(prow("x",e0,e0-day,cid("k%d"%i),0.5,1),status="CLOSED",realized_pnl=100.0,total_pnl=100.0) for i in range(5)]
walletfiles("0xf6",good+nob+cl,lost=[r for r in good if r["current_price"]==0])
ok,fmt=P.format_check(["0xf6"]); assert ok and fmt["rows_without_buys"]==30 and fmt["closed_rows"]==5 and fmt["closed_bad"]==0, fmt
walletfiles("0xf7",good+[dict(r,total_pnl=40.0) for r in cl],lost=[r for r in good if r["current_price"]==0])   # CLOSED: total_pnl is not realized_pnl
ok,fmt=P.format_check(["0xf7"]); assert not ok and fmt["closed_bad"]==5, fmt
walletfiles("0xf8",[dict(r,first_entry_at=r["first_entry_at"]*1000) for r in good],lost=[r for r in good if r["current_price"]==0])   # milliseconds
ok,fmt=P.format_check(["0xf8"]); assert not ok and fmt["plausible_fields"]==0, fmt
b=lambda c,v,t=P.F0+day:dict(condition_id=c,token_id=c+"-0",outcome_index=0,price=0.5,size=2*v,timestamp=t,transaction_hash="h"+c)
walletfiles("0xc1",[prow("x",e0,e0-day,"A",0.5,1)],opn=[dict(prow("x",e0,e0-day,"B",0.5,0),status="OPEN"),dict(prow("x",e0,e0-day,"C",0.5,0),status="REDEEMABLE")],
            buys=[b("A",60),b("B",20),b("C",20),b("A",500,t=P.F1+day)])
assert abs(P.coverage("0xc1","formation")-0.75)<1e-12   # B is still open (left out); C resolved but is missing from the scored walk
walletfiles("0xc2",[prow("x",e0,e0-day,"A",0.5,1)],buys=[b("A",60,t=P.F1+day)])
assert P.coverage("0xc2","formation")==0.0 and P.coverage("0xc2","evaluation")==1.0   # no formation buys: a broken walk
walletfiles("0xc3",[prow("x",e0,e0-day,"A",0.5,1,oi=1)],buys=[b("A",60)])   # the scored row is the other outcome
assert P.coverage("0xc3","formation")==0.0

# ---- trade lists: walk direction, early stop, None rows, coverage of each copy's hour ----
def fake_pages(pages):
    def h(url,params,**k):
        i=int(params.get("cursor") or 0); last=i==len(pages)-1
        return dict(data=pages[i],pagination=dict(has_more=not last,next_cursor=None if last else str(i+1)))
    return h
newest=[[dict(timestamp=100000-(k*10+i)*100,outcome_index=i%2,price=0.5) for i in range(10)] for k in range(5)]
newest[0][3]["price"]=None
P.http=fake_pages(newest); tp=P.tape("tn",98500,99000); P.http=boom
assert tp["from_newest"] and not tp["complete"] and tp["lo"]==98100 and tp["hi"]==100000, tp
assert [r[0] for r in tp["rows"]]==sorted(r[0] for r in tp["rows"]) and len(tp["rows"])==16-1, tp["rows"]   # 98500..100000, one None price dropped
assert P.covered(tp,98500) and P.covered(tp,99900) and not P.covered(tp,98000)
P.MAXPAGES=1; P.http=fake_pages(newest); tp=P.tape("tm",98500,99000); P.http=boom; P.MAXPAGES=200
assert not P.covered(tp,98500), tp   # 200 pages (here 1) did not reach the copy
oldest=[[dict(timestamp=(k*10+i)*100,outcome_index=0,price=0.5) for i in range(10)] for k in range(10)]
P.http=fake_pages(oldest); tp=P.tape("to",1000,5000); P.http=boom
assert tp["from_oldest"] and tp["hi"]>5000 and P.covered(tp,1000), tp
P.http=fake_pages(newest[:1]); tp=P.tape("tc",0,10**6); P.http=boom
assert tp["complete"] and P.covered(tp,0)

# ---- Data API paging, resolutions and payouts (fake pages, shapes from the 2026-10-15 format check) ----
def fake_pages2(pages,nomore=False):
    def h(url,params,**k):
        i=int(params.get("cursor") or 0); last=i==len(pages)-1
        pg=dict(next_cursor=None if last else str(i+1)) if nomore else dict(has_more=not last,next_cursor=None if last else str(i+1))
        return dict(data=pages[i],pagination=pg)
    return h
P.http=fake_pages2([[dict(a=1)],[dict(a=2)],[dict(a=3)]],nomore=True); rows,ok=P.pm_pages("/x",{}); P.http=boom
assert [r["a"] for r in rows]==[1,2,3] and ok   # has_more missing but a cursor given: keep walking
keepcap=P.POSCAP; P.POSCAP=5
P.http=fake_pages2([[dict(token_id="k%d"%(3*i+j),condition_id=cid("q"),outcome_index=0,status="CLOSED") for j in range(3)] for i in range(4)])
o=P.positions_of("0xbig"); P.http=boom; P.POSCAP=keepcap
assert o["rows"]==[] and o["truncated"]=="CLOSED", o   # a walk past the cap is saved as truncated, with no rows
R1,R2,R3=cid("r1"),cid("r2"),cid("r3")
def rfake(url,params,**k):
    if url.endswith("/v2/resolutions"):
        return dict(data=[dict(condition_id=R1.upper().replace("0X","0x"),status="resolved",last_update_timestamp="1775694501",price="1000000000000000000"),
                          dict(condition_id=R1,status="resolved",last_update_timestamp="1775699999"),
                          dict(condition_id=R2,status="proposed",last_update_timestamp="1775694501")])   # no pagination object, as the API answers
    if url.endswith("/v2/tokens"):
        return dict(data=[dict(condition_id=R1,outcome_index=0,final_price=1.0,module="v1_ctf"),dict(condition_id=R1,outcome_index=1,final_price=0.0,module="v1_ctf"),
                          dict(condition_id=R1,outcome_index=0,final_price=1.0,module="polymarket_v2"),
                          dict(condition_id=R3,outcome_index=0,final_price=1.0),dict(condition_id=R3,outcome_index=0,final_price=0.0)])
    raise AssertionError(url)
P.http=rfake; RS=P.resolutions([R1,R2,R3]); PY=P.payouts([R1,R3]); P.http=boom
assert RS=={R1:1775694501,R2:None,R3:None} and PY[R1]=={"0":1.0,"1":0.0} and PY[R3]=={"0":None}, (RS,PY)   # the earliest resolved record; two token families must agree
os.remove(os.path.join(D,"pm","resolutions.json")); os.remove(os.path.join(D,"pm","payouts.json"))

# ---- copy price ----
J(os.path.join(D,"pm","tapes","cp.json"),dict(since=0,until=1e9,complete=True,rows=[[1200,0,0.5],[1350,1,0.4],[1400,0,0.52],[1400,1,0.3],[1400,0,0.55],[1500,0,0.6]]))
c=dict(cond="cp",oi=0,t=1000)
assert P.copy_price(c,300,{},{})==(0.55,None)                          # the highest fill of the first order after +5 min
assert P.copy_price(c,300,{"cp":1390},{})[1]=="after close or resolution"
assert P.copy_price(c,300,{},{"cp":dict(closed_at=1400)})[1]=="after close or resolution"
assert P.copy_price(dict(c,t=-5000),300,{},{})[1]=="no buy within the hour"
assert P.copy_price(dict(c,oi=1,t=1100),300,{},{})==(0.3,None)
J(os.path.join(D,"pm","tapes","cq.json"),dict(since=0,until=1e9,complete=True,rows=[[1400,0,0.97]]))
assert P.copy_price(dict(cond="cq",oi=0,t=1000),300,{},{})[1]=="price 0.97 or more"

# ---- the reweighted placebo ----
def cr(ev,price,profit): return dict(event=ev,price=price,profit=profit,var=0.01,end=0)
sel=[cr("s%d"%i,0.25,0.1) for i in range(10)]   # every selected copy in the 0.2 tenth
pl=[cr("a%d"%i,0.22,1.0) for i in range(3)]+[cr("b%d"%i,0.35,0.0) for i in range(10)]+[cr("c%d"%i,0.75,-1.0) for i in range(10)]
m,se,pool=P.reweighted(sel,pl); assert pool=={2:3} and abs(m-3/13)<1e-12, (m,pool)   # 3 placebo events in 0.2: pooled with 0.3
sel=[cr("s%d"%i,0.35,0.1) for i in range(5)]+[cr("t%d"%i,0.75,0.1) for i in range(5)]
pl=[cr("b%d"%i,0.35,0.0) for i in range(10)]+[cr("c%d"%i,0.75,-1.0) for i in range(20)]
m,se,pool=P.reweighted(sel,pl); assert pool=={} and abs(m+0.5)<1e-12 and se>0, (m,se,pool)   # 0.5 x 0 + 0.5 x -1, not the raw -2/3

# ---- Kalshi orders and copies ----
assert P.kdate("KXMLBGAME-26OCT01NYYBOS")=="2026-10-01" and P.kdate("KXODD",calendar.timegm((2026,8,2,3,0,0,0,0,0)))=="2026-08-02"
assert P.kfee(0.5,1.0)==0.02 and P.kfee(0.5,0.5)==0.01 and P.kfee(0.5,0.0)==0.0
od=P.korders([dict(ts=10,ct="a",side="yes",n=500,yes=0.6,no=0.4,block=False),dict(ts=10,ct="a",side="yes",n=1500,yes=0.61,no=0.39,block=False),dict(ts=20,ct="b",side="no",n=5,yes=0.6,no=0.4,block=True)])
assert len(od)==2 and abs(od[0]["notional"]-(300+915))<1e-9 and od[0]["max_price"]==0.61 and od[1]["block"], od
assert P.korders([dict(ts=5,ct="z",side="yes",n=10,yes=0.0,no=1.0,block=False),dict(ts=6,ct="y",side="no",n=0,yes=0.5,no=0.5,block=False),
                  dict(ts=7,ct="x",side="no",n=3,yes=None,no=None,block=False),dict(ts=None,ct="w",side="yes",n=3,yes=0.5,no=0.5,block=False)])==[]
od=[dict(ts=0,side="yes",notional=2000,max_price=0.5,block=False),
    dict(ts=30,side="yes",notional=5,max_price=0.55,block=False),      # under 60 s: not the copy
    dict(ts=100,side="yes",notional=5,max_price=0.6,block=True),       # a block trade is never the copy
    dict(ts=200,side="yes",notional=5,max_price=0.62,block=False),     # the copy of the order at 0
    dict(ts=300,side="yes",notional=3000,max_price=0.63,block=False),  # its copy (at 400) is within the hour of the copy at 200
    dict(ts=400,side="yes",notional=5,max_price=0.64,block=False),
    dict(ts=500,side="no",notional=5000,max_price=0.3,block=True),     # a block trade is never a signal
    dict(ts=5000,side="yes",notional=1500,max_price=0.5,block=False)]  # no later order
why={}; cc=P.kcopies(od,"yes",1.0,1000,1e18,why)
assert len(cc)==1 and cc[0]["price"]==0.62 and cc[0]["t"]==0 and abs(cc[0]["profit"]-(1-0.62-P.kfee(0.62,1.0)))<1e-12, cc
assert why=={"copied within the hour":1,"no later order":1}, why
assert abs(cc[0]["own_excess"]-0.5)<1e-12

# ---- Kalshi series and trade fetches (fake pages, a separate folder) ----
KT=os.path.join(OUT,"kfetch"); keep=(P.OUT,P.D_K); P.OUT=os.path.join(KT,"results"); P.D_K=os.path.join(KT,"k1")
inwin=P.K0+10*day; iso=lambda t:datetime.fromtimestamp(t,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def km(t,close,vol,res="yes"): return dict(ticker=t,event_ticker=t.rsplit("-",1)[0],close_time=iso(close),result=res,volume_fp=None if vol is None else "%.2f"%vol,name="dropped")
live=[km("KXA-26JUL25-%d"%i,inwin,1000) for i in range(5)]+[km("KXB-26JUL25-%d"%i,inwin,100) for i in range(3)]+[km("KXCOMBOX-26JUL25-1",inwin,10**7),
      km("KXC-26JUL25-1",inwin,50),km("KXA-26JUN01-9",P.K0-5*day,10**6),km("KXA-26JUL25-V",inwin,10**6,res="")]
arch={"KXA":[km("KXA-26JUL20-1",inwin-5*day,10),km("KXA-26MAY01-1",P.K0-60*day,10)],"KXB":[],"KXC":[]}
fees={"KXA":1.0,"KXB":0.07,"KXC":0.5}; ftypes={"KXA":"quadratic","KXB":"quadratic","KXC":"flat"}
def kfake(url,params,**k):
    path=url[len(P.KALSHI):]
    if path=="/markets":
        if "series_ticker" in params: return dict(markets=[m for m in livepages if m["event_ticker"].startswith(params["series_ticker"]+"-")],cursor="")
        i=int(params.get("cursor") or 0); pages=[livepages[0:4],livepages[4:]]
        return dict(markets=pages[i],cursor="" if i==1 else "1")
    if path=="/historical/markets": return dict(markets=arch[params["series_ticker"]],cursor="")
    if path.startswith("/series/"): return dict(series=dict(ticker=path[8:],fee_multiplier=fees[path[8:]],fee_type=ftypes[path[8:]]))
    raise AssertionError(path)
livepages=[dict(m,volume_fp=None) for m in live]; P.http=kfake
exits(P.kseries,"no volume field"); assert not os.path.exists(os.path.join(P.D_K,"live_volume.json"))   # not cached
livepages=live
exits(P.kseries,"fee multipliers"); assert not os.path.exists(os.path.join(P.OUT,"plan4_series.json"))   # 0.07 is the old absolute scale
fees["KXB"]=1.0
exits(P.kseries,"fee type not quadratic"); assert not os.path.exists(os.path.join(P.OUT,"plan4_series.json"))
ftypes["KXC"]="quadratic_with_maker_fees"; P.kseries(); P.http=boom
SS=json.load(open(os.path.join(P.OUT,"plan4_series.json"))); MS=json.load(open(os.path.join(P.D_K,"markets.json")))
assert SS["series"]==["KXA","KXB","KXC"] and SS["ranking_volume"]["KXA"]==5000, SS   # the combo, the out-of-window and the unsettled market are left out
assert sorted(MS)==sorted(["KXA-26JUL25-%d"%i for i in range(5)]+["KXA-26JUL20-1"]+["KXB-26JUL25-%d"%i for i in range(3)]+["KXC-26JUL25-1"]), sorted(MS)
assert all("name" not in m and m["close"] for m in MS.values())
exits(P.kseries,"frozen")
tr=lambda ts,side,n,p,blk=False,tid=None:dict(trade_id=tid or "t%d%s"%(ts,side),created_time=iso(ts),taker_side=side,count_fp="%.2f"%n,yes_price_dollars="%.4f"%(p if side=="yes" else 1-p),no_price_dollars="%.4f"%(p if side=="no" else 1-p),is_block_trade=blk)
calls={}
def tfake(url,params,**k):
    path=url[len(P.KALSHI):]; t=params["ticker"]; calls[t]=calls.get(t,0)+1
    if t=="KXB-26JUL25-0" and calls[t]==2: raise RuntimeError("HTTP 500 (test)")   # the live walk fails after the archive answered
    if path=="/markets/trades": return dict(trades=[tr(inwin-9000,"no",7,0.3,True,tid="dup")] if t=="KXA-26JUL20-1" else [tr(inwin-100,"yes",3,0.4)],cursor="")
    if path=="/historical/trades": return dict(trades=[tr(inwin-9000,"no",7,0.3,True,tid="dup"),dict(tr(inwin-9500,"yes",2,0.6),yes_price_dollars=None,no_price_dollars=None,yes_price=60,no_price=40)] if t=="KXA-26JUL20-1" else [],cursor="")
    raise AssertionError(path)
P.http=tfake; P.ktrades()
assert not os.path.exists(os.path.join(P.D_K,"trades2","KXB-26JUL25-0.json"))   # one failed walk: nothing saved
P.ktrades(); P.http=boom
a=sorted(json.load(open(os.path.join(P.D_K,"trades2","KXA-26JUL20-1.json"))),key=lambda r:r["ts"]); bb=json.load(open(os.path.join(P.D_K,"trades2","KXB-26JUL25-0.json")))
assert a==[dict(id="t%dyes"%(inwin-9500),ts=inwin-9500,ct=iso(inwin-9500),side="yes",n=2.0,yes=0.6,no=0.4,block=False),
           dict(id="dup",ts=inwin-9000,ct=iso(inwin-9000),side="no",n=7.0,yes=0.7,no=0.3,block=True)] and bb[0]["n"]==3.0 and bb[0]["yes"]==0.4, (a,bb)   # merged by trade_id; prices in cents read too
P.OUT,P.D_K=keep

# ---- Gamma shapes (fake pages): comboStatus is not a combo flag; fees ----
def gm(name,vol,**k):
    m=dict(conditionId=cid(name).upper().replace("0X","0x"),endDate="2026-03-01T00:00:00Z",volumeNum=vol,comboStatus="enabled",cyom=False,closedTime="2026-03-01 00:28:21+00",
           events=[dict(id=77)],feesEnabled=True,feeType="sports_fees_v2",feeSchedule=dict(exponent=1,rate=0.03,takerOnly=True),question="dropped"); m.update(k); return m
glist=[gm("g%d"%i,10**6-i) for i in range(250)]+[gm("cy",5,cyom=True),gm("short",4,conditionId="0x"+"a"*62)]+[gm("h%d"%i,100-i,comboStatus="disabled") for i in range(80)]
def gfake(url,params,**k):
    assert url.startswith(P.GAMMA)
    if "condition_ids" in params:
        want=set(params["condition_ids"]); closed=params["closed"]=="true"
        return [m for m in glist if m["conditionId"].lower() in want and closed]
    off=int(params["offset"]); return glist[off:off+int(params["limit"])]
P.http=gfake; P.pmarkets()
FM=json.load(open(os.path.join(D,"pm","formation_markets.json")))["markets"]
assert len(FM)==300 and FM[0]["condition_id"]==cid("g0") and cid("cy") not in [m["condition_id"] for m in FM], (len(FM),FM[:2])
GM=P.gamma_meta([cid("g1"),cid("cy"),"0x"+"a"*62,cid("nowhere")]); P.http=boom
assert GM[cid("g1")]==dict(end="2026-03-01",event="77",closed_at=calendar.timegm((2026,3,1,0,28,21,0,0,0)),rate=0.03,exp=1.0,combo=False), GM[cid("g1")]
assert GM[cid("cy")]["combo"] and GM["0x"+"a"*62]["combo"] and GM[cid("nowhere")] is None, GM
os.remove(os.path.join(D,"pm","gamma_meta.json")); os.remove(os.path.join(D,"pm","formation_markets.json"))
glist=[gm("z",1,feesEnabled=False,feeType=None,feeSchedule=None),gm("zz",1,feeSchedule=dict(rate=0,exponent=1)),gm("zd",1,feeSchedule={})]
P.http=gfake; GM=P.gamma_meta([cid("z"),cid("zz"),cid("zd")]); P.http=boom
assert GM[cid("z")]["rate"]==0.0 and GM[cid("zz")]["rate"]==0.0 and GM[cid("zd")]["rate"]==0.07, GM   # fees on with no published rate: 0.07
os.remove(os.path.join(D,"pm","gamma_meta.json"))

c3=P.consensus([dict(w=w,cond="c",oi=0,t=t,event="e",end=0) for w,t in (("a",0),("b",100),("a",200),("c",90000),("d",90100))])
assert c3==[], c3   # c and d come more than 24 hours after a and b: never 3 different wallets within a day
c3=P.consensus([dict(w=w,cond="c",oi=0,t=t,event="e",end=0) for w,t in (("a",0),("a",50),("b",100),("c",80000),("d",80100))])
assert len(c3)==1 and c3[0]["w"]=="c", c3   # the 3rd different wallet within 24 hours

# ---- Polymarket world ----
W=["0x%040x"%i for i in range(400)]; skilled=set(W[:60]) if MODE=="edge" else set()
FE=[("fe%d"%i,P.F0+5*day+int(i*170*day/300)) for i in range(300)]; EE=[("ee%d"%i,P.EEND0+3*day+int(i*95*day/120)) for i in range(120)]
meta={}; res={}; pay={}; tapes={}; market={}
for w in W:
    rows=[]; buys=[]
    for ev,end in rnd.sample(FE,40):
        p=round(rnd.uniform(0.2,0.8),2); edge=0.25 if w in skilled else 0.0; won=1 if rnd.random()<p+edge else 0
        cond=cid("c_"+ev+"_"+w[-4:]); rows.append(prow(ev,end,end-10*day,cond,p,won))
        buys.append(dict(condition_id=cond,token_id=cond+"-0",outcome_index=0,price=p,size=100/p,timestamp=end-10*day,transaction_hash="h"+cond))
    for ev,end in rnd.sample(EE,20):
        cond=cid("c_"+ev)   # one shared market per evaluation event, with a fair price q and outcome Y ~ Bernoulli(q)
        if cond not in market: q=round(rnd.uniform(0.3,0.7),2); market[cond]=(q,1 if rnd.random()<q else 0)
        q,Y=market[cond]
        if w in skilled: side=Y if rnd.random()<0.8 else 1-Y   # skill: picks the winning side 4 times in 5
        else: side=1 if rnd.random()<0.5 else 0
        p=q if side==1 else round(1-q,2); oi=0 if side==1 else 1; won=1 if side==Y else 0
        pay[cond]={"0":Y,"1":1-Y}
        t=end-6*day+int(rnd.random()*3600)
        rows.append(prow(ev,end,t,cond,p,won,oi=oi))
        buys.append(dict(condition_id=cond,token_id=cond+"-%d"%oi,outcome_index=oi,price=p,size=100/p,timestamp=t,transaction_hash="h"+cond+w))
        meta[cond]=dict(end=ymd(end),event=ev,closed_at=None,rate=0.0,exp=1.0,combo=False)
        res[cond]=end+3600
        tapes.setdefault(cond,[]).append((t+600,oi,min(0.96,round(p+0.01,2))))
    walletfiles(w,rows,lost=[r for r in rows if r["current_price"]==0],buys=buys)
    J(os.path.join(D,"pm","taker",w+".json"),["%s:%s"%(b["transaction_hash"],b["token_id"]) for b in buys])
    J(os.path.join(D,"pm","activity",w+".json"),0)
J(os.path.join(D,"pm","positions","0xtrunc.json"),dict(fetched="t",rows=[],truncated="CLOSED"))
walletfiles("0xmany",[prow(ev,end,end-10*day,cid("m%d"%i),0.5,1) for i,(ev,end) in enumerate(FE[:150])])
P.POSCAP=100   # the world's wallets hold 60 rows each; 0xmany holds 150
J(os.path.join(D,"pm","pool.json"),W+["0xtrunc","0xmany"]); J(os.path.join(D,"pm","gamma_meta.json"),meta); J(os.path.join(D,"pm","resolutions.json"),res); J(os.path.join(D,"pm","payouts.json"),pay)
for cond,rows in tapes.items():
    J(os.path.join(D,"pm","tapes",cond+".json"),dict(since=0,until=1e18,complete=True,rows=sorted(rows)))
P.pselect()
S=json.load(open(os.path.join(R,"plan4_selected.json")))
assert S["skipped"]["too_many_to_fetch"]==2 and "0xmany" not in S["eligible"], S["skipped"]
assert len(S["selected"])==50 and len(S["placebo"])==200 and not S["coverage_failed"] and S["format_check"]["rows"]>0, (len(S["selected"]),S["skipped"],S["format_check"])
assert set(S["formation_all"])==set(S["eligible"]) and all(len(x["wallet"])==6 for x in S["formation"]+S["coverage"])
if MODE=="edge": assert len(set(S["selected"])&skilled)>=40, len(set(S["selected"])&skilled)
exits(P.pselect,"frozen")
P.pcopies(); P.scoreP()
RP=json.load(open(os.path.join(R,"plan4_P.json")))
exits(P.scoreP,"already exists")
d1=RP["P1"]["descriptive"]; assert d1["rank_corr_formation_t_vs_evaluation"] is not None, d1
if MODE=="edge": assert d1["rank_corr_formation_t_vs_evaluation"]>0.2, d1
print("P1",RP["P1"]["verdict"],RP["P1"]["mean"],RP["P1"]["t"],"| P2",RP["P2"]["verdict"],RP["P2"]["copies"],RP["P2"]["mean"],RP["P2"]["t"],RP["P2"]["vs_placebo"],"| P2c",RP["P2c"]["verdict"],RP["P2c"]["copies"])
# ---- Kalshi world ----
series=["KXA","KXB","KXC"]; ms={}
for s in series:
    for i in range(200):
        d=P.K0+int(i*85*day/200); dt=datetime.fromtimestamp(d,timezone.utc).strftime("%y%b%d").upper()
        t="%s-%s-M%d"%(s,dt,i); ms[t]=dict(ticker=t,event="%s-%s"%(s,dt),series=s,result=None,volume=1,close=d)
J(os.path.join(R,"plan4_series.json"),dict(series=series,fee_multiplier={s:1.0 for s in series},fee_type={s:"quadratic" for s in series}))
for t,m in ms.items():
    p=round(rnd.uniform(0.3,0.7),2); side=rnd.choice(["yes","no"]); edge=0.2 if MODE=="edge" else 0.0
    win=rnd.random()<p+edge; m["result"]=side if win else ("no" if side=="yes" else "yes")
    t0=1000
    def row(ts,sd,n,pr): return dict(ts=ts,ct=str(ts),side=sd,n=n,yes=pr if sd=="yes" else round(1-pr,2),no=pr if sd=="no" else round(1-pr,2),block=False)
    J(os.path.join(D,"k1","trades2",t+".json"),[row(t0,side,4000,p),row(t0+120,side,10,p),row(t0+300,side,5,p)])
J(os.path.join(D,"k1","markets.json"),ms)
P.scoreK(); RK=json.load(open(os.path.join(R,"plan4_K.json")))
exits(P.scoreK,"already exists")
assert RK["small_orders"]["copies"]==len(ms) and RK["dates_from_close_time"]==0, RK["small_orders"]
print("K1",RK["verdict"],RK["copies"],RK["dates"],RK["mean"],RK["t"])
if MODE=="edge":
    assert RP["P1"]["verdict"]=="PASS" and RP["P2"]["verdict"]=="PASS" and RK["verdict"]=="PASS", (RP["P1"],RP["P2"]["verdict"],RK["verdict"])
else:
    assert RP["P1"]["verdict"]!="PASS" and RP["P2"]["verdict"]!="PASS" and RP["P2c"]["verdict"]!="PASS" and RK["verdict"]!="PASS", (RP["P1"]["verdict"],RP["P2"]["verdict"],RP["P2c"],RK["verdict"])
assert "Verdict" in open(os.path.join(R,"plan4_K.md"),encoding="utf-8").read() and "P2 copy" in open(os.path.join(R,"plan4_P.md"),encoding="utf-8").read()
print("plan4.py (%s): all checks passed"%MODE)
