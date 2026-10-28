"""Forward-test window and statistic (research/PLAN.md amendment). No network. python test_forward.py WORK OUT"""
import os, sys, io, contextlib, calendar
WORK=sys.argv[1]; OUT=sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import core, shadow
from datetime import date, timedelta
c=core.db(); shadow.tables(c)
def ts(d,h,m): return calendar.timegm((d.year,d.month,d.day,h,m,0))
D=date(2026,10,10)
for i,(h,m) in enumerate([(0,56),(3,41),(0,49),(1,30)]):
    t="KXRAIN-%s-C%d"%(D.strftime("%y%b%d").upper(),i)
    c.execute("insert into v4_obs(ticker,ts,station,run,R,q,fc,mid,bid,ask,start_ts) values(?,?,?,?,?,?,?,?,?,?,?)",(t,ts(D,h,m),"K","r",0.3,0,0.30,0.30,0.29,0.31,ts(D,5,0)))
c.commit()
shadow._markets=lambda ts_:{t:{"result":"no"} for t in ts_}; shadow._candles=lambda *a,**k:{}
out=io.StringIO()
with contextlib.redirect_stdout(out): shadow.settle(c)
st={t:p for t,p in c.execute("select ticker,paper_done from v4_obs")}
print(out.getvalue().strip().splitlines()[-1]); print(st)
assert [st[k] for k in sorted(st)]==[1,2,2,1], st     # 00:56 and 01:30 counted; 03:41 and 00:49 not
assert shadow.in_window(ts(D,0,50)) and shadow.in_window(ts(D,1,30)) and not shadow.in_window(ts(D,1,31)) and not shadow.in_window(ts(D,0,49))
# statistic over 20 market days with a fill every other day
for k in range(20):
    d=date(2026,10,11)+timedelta(days=k); t="KXRAIN-%s-X"%d.strftime("%y%b%d").upper()
    c.execute("insert into v4_obs(ticker,ts,station,run,R,q,fc,mid,bid,ask,start_ts,result,paper_done) values(?,?,?,?,?,?,?,?,?,?,?,?,1)",(t,ts(d,0,56),"K","r",0.3,0,0.3,0.3,0.29,0.31,ts(d,5,0),"no"))
    if k%2==0: c.execute("insert into v4_paper(ticker,kind,side,price,improved,filled,result,pnl) values(?,?,?,?,?,?,?,?)",(t,"maker","no",0.6,1,1,"no",0.40 if k%4==0 else -0.60))
c.commit()
fs=shadow.forward_stats(c,"maker"); print(fs)
assert fs["days"]==21 and fs["fills"]==10 and abs(fs["mean"]-(5*0.40-5*0.60)/21)<1e-9 and "boot" in fs and fs["boot"][0]<fs["mean"]<fs["boot"][1]
out=io.StringIO()
with contextlib.redirect_stdout(out): shadow.report(c)
print([l for l in out.getvalue().splitlines() if l.startswith("V4 FORWARD")])
print("forward window and statistic: ok")
