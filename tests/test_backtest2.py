"""Synthetic end-to-end test of research/backtest2.py. python test_bt2.py WORK OUT MODE  (MODE: edge | null)"""
import os, sys, json, math, random, shutil
from datetime import date, timedelta
WORK,OUT,MODE=sys.argv[1],sys.argv[2],sys.argv[3]
shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research")); sys.path.insert(0,WORK)
import backtest2 as b2, backtest as bt
D=os.path.join(OUT,"data"); R=os.path.join(OUT,"results"); os.makedirs(D); os.makedirs(R)
b2.DATA=D; b2.OUT=R
random.seed(7 if MODE=="edge" else 11)
ST=["KAAA","KBBB","KCCC"]; TZ={"KAAA":5,"KBBB":6,"KCCC":8}
def Phi(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
nbs={}; late={}; cli={}
d0=date(2025,7,1); d1=date(2026,9,30)
truth={}
d=d0
while d<=d1:
    for st in ST:
        txn=70+15*math.sin(d.toordinal()/58.0)+random.gauss(0,3); txn=round(txn); xnd=random.choice([1,2,2,3,3,4])
        high=round(txn+1+random.gauss(0,1+0.5*xnd)); rainp=random.choice([0,5,10,20,40,60,80]); rained=random.random()<(0.15+0.7*rainp/100)
        truth[(st,d)]=(txn,xnd,high,rainp,rained)
        cli.setdefault((st,d.year),[]).append(dict(valid=d.isoformat(),precip=0.2 if rained else ("T" if random.random()<0.2 else 0.0),high=high,low=high-15,product="x"))
        rt="%s %s:00:00"%(d-timedelta(days=1),"19" if d.year<2026 else "18")
        nx=d+timedelta(days=1)
        rows=[dict(runtime=rt,ftime="%s 12:00:00"%d,p06=str(rainp),q06="5" if rainp>30 else "0",p12="",q12="",txn="",xnd="",tmp="70"),
              dict(runtime=rt,ftime="%s 18:00:00"%d,p06=str(rainp),q06="0",p12="",q12="",txn="",xnd="",tmp="70"),
              dict(runtime=rt,ftime="%s 00:00:00"%nx,p06=str(rainp//2),q06="0",p12="",q12="",txn=str(txn),xnd=str(xnd),tmp="70"),
              dict(runtime=rt,ftime="%s 06:00:00"%nx,p06=str(rainp//2),q06="0",p12="",q12="",txn="",xnd="",tmp="70")]
        nbs.setdefault((st,(d-timedelta(days=1)).strftime("%Y%m")),[]).extend(rows)
        if d>=date(2026,7,1):   # late run 00Z on the day: sharper (the truth moved a little closer)
            lr="%s 00:00:00"%d
            txl=round(txn+0.5*(high-txn-1)); late.setdefault((st,d.strftime("%Y%m")),[]).extend([dict(r,runtime=lr,txn=(str(txl) if r["txn"] else "")) for r in rows])
    d+=timedelta(days=1)
for (st,ym),v in nbs.items(): os.makedirs(os.path.join(D,"nbs"),exist_ok=True); json.dump(v,open(os.path.join(D,"nbs","%s_%s.json"%(st,ym)),"w"))
for (st,ym),v in late.items(): os.makedirs(os.path.join(D,"nbs_late"),exist_ok=True); json.dump(v,open(os.path.join(D,"nbs_late","%s_%s.json"%(st,ym)),"w"))
for (st,y),v in cli.items(): os.makedirs(os.path.join(D,"cli"),exist_ok=True); json.dump(v,open(os.path.join(D,"cli","%s_%d.json"%(st,y)),"w"))
json.dump(dict(coef=[-0.2,1.2,0.17]),open(os.path.join(R,"rain_model.json"),"w"))
noise=0.10 if MODE=="edge" else 0.0
def quote(p,shift=0.0):
    m=min(max(p+random.gauss(0,noise)+shift,0.02),0.97); sp=random.choice([0.01,0.02,0.03]); b=round(max(m-sp/2,0),2); a=round(min(b+sp,1),2)
    return b,a
tf=open(os.path.join(D,"kalshi_temp.jsonl"),"w"); rf=open(os.path.join(D,"kalshi_rain.jsonl"),"w"); lf=open(os.path.join(D,"kalshi_rain_late.jsonl"),"w")
d=date(2026,7,1)
while d<=date(2026,9,30):
    for st in ST:
        txn,xnd,high,rainp,rained=truth[(st,d)]; mu=txn+1; sd=1+0.5*xnd
        base=txn-4
        strikes=[("less",None,base),("between",base,base+1),("between",base+2,base+3),("between",base+4,base+5),("between",base+6,base+7),("greater",base+7,None)]
        for kind,fl,cap in strikes:
            p=b2.p_temp(kind,fl,cap,mu,sd); y=b2.cli_yes(kind,fl,cap,high)
            sb,sa=quote(p); lb,la=quote(p); wb,wa=quote(0.8*p+0.2*(1.0 if y else 0.0))
            lo=round(sa-random.choice([0,0.01,0.02,0.05]),2); hi=round(sb+random.choice([0,0.01,0.02,0.05]),2)
            tag=d.strftime("%y%b%d").upper(); t="KXHIGHX%s-%s-%s%s"%(st[1:],tag,"T" if kind!="between" else "B",fl if kind=="greater" else (cap if kind=="less" else fl+0.5))
            rn=[float(fl)] if kind=="greater" else ([float(cap)] if kind=="less" else [float(fl),float(cap)])
            tf.write(json.dumps(dict(ticker=t,series=t.split("-")[0],day=d.isoformat(),station=st,result="yes" if y else "no",strike_type=kind,floor=fl,cap=cap,rule_numbers=rn,volume=100,hist=False,
                scan_ts=0,late_ts=0,start_ts=0,scan_bid=sb,scan_ask=sa,lo_after=lo,hi_after=hi,late_bid=lb,late_ask=la,late_lo=lo,late_hi=hi,start_bid=wb,start_ask=wa,n_candles=9))+"\n")
        pr=0.15+0.7*rainp/100; sb,sa=quote(pr); t="KXRAIN-%s-%s"%(d.strftime("%y%b%d").upper(),st[1:])
        rf.write(json.dumps(dict(ticker=t,day=d.isoformat(),station=st,result="yes" if rained else "no",scan_bid=sb,scan_ask=sa,start_bid=sb,start_ask=sa,lo_after=round(sa-0.03,2),hi_after=round(sb+0.03,2),hist=False,start_ts=0))+"\n")
        lb,la=quote(pr); lf.write(json.dumps(dict(ticker=t,late_ts=0,late_bid=lb,late_ask=la,late_lo=round(la-0.03,2),late_hi=round(lb+0.03,2)))+"\n")
    d+=timedelta(days=1)
tf.close(); rf.close(); lf.close()
b2.main()
res=json.load(open(os.path.join(R,"plan2.json"))); m=json.load(open(os.path.join(R,"temp_model.json")))
print("MODEL",{k:round(m[k],3) for k in ("a","s0","s1")},"| verdict:",res["verdict"])
A=res["A_temperature"]; print("checks",A["checks"],"cli",A["cli_agreement"])
assert abs(m["a"]-1)<0.3 and abs(m["s0"]-1)<0.4 and abs(m["s1"]-0.5)<0.25, "model should recover a=1, s0=1, s1=0.5"
assert A["cli_agreement"]==1.0 and A["checks"]["yes_count_in_complete_city_days"]=={"1":A["checks"]["complete_city_days"]} and A["checks"]["rules_strike_mismatch"]==0
if MODE=="edge": assert A["edge"], "noisy market + good forecast should show an edge"
else: assert not A["edge"], "perfect market: no edge"
# frozen: a second run keeps the file
mt=os.path.getmtime(os.path.join(R,"temp_model.json")); b2.main(); assert os.path.getmtime(os.path.join(R,"temp_model.json"))==mt
print("backtest2 synthetic",MODE,": ok")
