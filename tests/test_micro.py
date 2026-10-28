"""research/micro.py on a synthetic recording, no network: the queue-aware fill rule for join, improve and cross; a
planted book-imbalance signal; a planted 30-second lead of one market over another in the same event; the report.
python test_micro.py WORK OUT"""
import os, sys, json, shutil, random
WORK,OUT=sys.argv[1],sys.argv[2]; shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0,os.path.join(WORK,"research"))
import micro as M
M.DATA=os.path.join(OUT,"data"); M.OUT=os.path.join(OUT,"results")
def boom(*a,**k): raise AssertionError("no network in tests")
M.http=boom
# ---- the fill rule on a hand-made book: YES bid 40c (100 ahead), NO bid 58c (so YES ask 42c) ----
bs=[dict(t=0.0,k="X",y=[[0.40,100]],n=[[0.58,50]])]
tr=[dict(t=10.0,k="X",side="no",yes=0.40,q=60),dict(t=20.0,k="X",side="yes",yes=0.40,q=500),dict(t=30.0,k="X",side="no",yes=0.40,q=50)]
assert M.top(bs[0])==(0.40,0.42,100,50)
assert M.simulate(bs,tr,0,"yes","JOIN")=={"price":0.40,"fill_t":30.0,"fee":0.0}        # 60 + 50 sold into the bid: past the 100 ahead at 30 s (the taker YES buy does not count)
assert M.simulate(bs,tr,0,"yes","IMPROVE")=={"price":0.41,"fill_t":10.0,"fee":0.0}     # first in line at 41c: the 40c sale goes through it
assert M.simulate(bs,tr,0,"yes","CROSS")=={"price":0.42,"fill_t":0.0,"fee":0.02}
assert M.simulate(bs,tr,0,"no","JOIN")=={"price":0.58,"fill_t":None,"fee":0.0}         # the only NO sale was at 60c, above our 58c bid: no fill
assert M.simulate([dict(t=0.0,k="X",y=[[0.40,1]],n=[[0.59,1]])],tr,0,"yes","IMPROVE") is None   # 41c would cross a 41c ask
assert M.simulate(bs,[],0,"yes","JOIN")["fill_t"] is None
seq=[dict(t=0.0,y=[[0.40,1]],n=[[0.58,1]]),dict(t=7.0,y=[[0.44,1]],n=[[0.54,1]])]   # a 7-second cycle
assert abs(M.mid_at(seq,5.0,30)-0.41)<1e-9 and abs(M.mid_after(seq,5.0,30)-0.45)<1e-9 and M.mid_after(seq,8.0,30) is None and M.mid_after(seq,-40.0,30) is None   # "5 s later" is the next snapshot, never the starting one
# ---- a synthetic two-hour recording: A leads B by 30 s; the YES-heavy book precedes a rise ----
rnd=random.Random(3); T=7200; step=5
a={}; m=50; nxt=0
for t in range(0,T+1800,step):
    if t%30==0: nxt=rnd.choice((-1,1)) if t>0 else 0
    a[t]=m
    if t%30==25: m=min(80,max(20,m+nxt))
def book(k,t,mid,lead):
    dy,dn=(300,100) if lead>0 else ((100,300) if lead<0 else (200,200))
    return dict(kind="book",t=float(t),k=k,y=[[round((mid-1)/100,4),dy],[round((mid-2)/100,4),50]],n=[[round((100-mid-1)/100,4),dn],[round((100-mid-2)/100,4),50]])
os.makedirs(M.DATA); p=os.path.join(M.DATA,"20261024-1000.jsonl")
with open(p,"w") as f:
    f.write(json.dumps(dict(kind="header",start=0,every=step,markets={"KXRAINNYC-26OCT25-T1":dict(event="KXRAINNYC-26OCT25"),"KXRAINNYC-26OCT25-T2":dict(event="KXRAINNYC-26OCT25")}))+"\n")
    for t in range(0,T,step):
        up=1 if (t%30)>=5 else 0   # the imbalance shows the coming move for the rest of the 30 s window
        nxt_move=(a.get(t-(t%30)+30,a[t])-a[t-(t%30)]) if up else 0
        f.write(json.dumps(book("KXRAINNYC-26OCT25-T1",t,a[t],nxt_move))+"\n")
        f.write(json.dumps(book("KXRAINNYC-26OCT25-T2",t,a.get(t-30,50),0))+"\n")
        if t%60==10: f.write(json.dumps(dict(kind="trade",t=t+1.0,k="KXRAINNYC-26OCT25-T1",side="no",yes=round((a[t]-1)/100,4),q=500))+"\n")
        if t%60==40: f.write(json.dumps(dict(kind="trade",t=t+1.0,k="KXRAINNYC-26OCT25-T1",side="yes",yes=round((a[t]+1)/100,4),q=500))+"\n")
R=M.analyze([p])
assert R["markets"]==2 and R["snapshots"]==2*T//step, (R["markets"],R["snapshots"])
lo,hi=R["features"]["30:0"],R["features"]["30:2"]
assert hi["mean"]>0.003 and lo["mean"]<-0.003 and hi["up"]>0.5 and lo["down"]>0.5, (lo,hi)   # the planted imbalance signal is found
L={(x["leader"],x["follower"]):x["lags"] for x in R["lead_lag"]}
ab=L[("KXRAINNYC-26OCT25-T1","KXRAINNYC-26OCT25-T2")]; ba=L[("KXRAINNYC-26OCT25-T2","KXRAINNYC-26OCT25-T1")]
assert ab["30"]["corr"]>0.9 and abs(ab["0"]["corr"] or 0)<0.3 and abs(ba["30"]["corr"] or 0)<0.3, (ab,ba)   # A leads B by 30 s, not the reverse
assert ab["30"]["beats_costs"] is not None and ab["30"]["leader_moves"]>50
P=R["policies"]
assert P["CROSS yes"]["p_fill"]["5"]==1.0 and P["JOIN yes"]["p_fill"]["300"]<=P["IMPROVE yes"]["p_fill"]["300"], (P["JOIN yes"]["p_fill"],P["IMPROVE yes"]["p_fill"])
assert P["CROSS yes"]["value_at_fill"]<0 and P["CROSS yes"]["spread_capture"]<0   # crossing pays half the spread plus the fee
assert set(R["toxicity"]) and all(0<=v["adverse_share"]<=1 for v in R["toxicity"].values())
md=open(os.path.join(M.OUT,"micro.md"),encoding="utf-8").read()
assert "Join, improve or cross" in md and "Lead-lag within events" in md and "Nothing here is a rule or a trade" in md
print("micro.py: all checks passed")
