"""attribution.py: Brier decomposition identity, luck's standard error, the profit split, missing sources, read-only, writes
only its results folder. Fake databases only. python test_attribution.py WORK OUT"""
import os, sys, json, time, hashlib, random, sqlite3, subprocess, math
WORK,OUT=os.path.abspath(sys.argv[1]),os.path.abspath(sys.argv[2]); os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
RES=os.path.join(OUT,"research","results")
os.environ.update(PAPER_DB=os.path.join(OUT,"paper.db"),TRADEBOT_RESULTS=RES,LIVE15_DB=os.path.join(OUT,"live15.db"),
                  LIVE20_DATA=os.path.join(OUT,"live20"),TRADEBOT_ACCOUNT_JSON=os.path.join(OUT,"account.json"),
                  TRADEBOT_OFFSITE_BACKUPS=os.path.join(OUT,"offsite"))
assert not os.path.abspath(os.environ["PAPER_DB"]).startswith(os.path.abspath(WORK)+os.sep), "tests must never use the real paper.db"
sys.path.insert(0,WORK)
import attribution as A
rnd=random.Random(5)

# 1. Brier decomposition: exact identity on any data; the within-bin term vanishes when every forecast in a bin is equal
for _ in range(20):
    ps=[(rnd.random(),1 if rnd.random()<0.4 else 0) for _ in range(rnd.randint(1,200))]
    b=A.brier_parts(ps)
    assert abs(b["brier"]-(b["reliability"]-b["resolution"]+b["uncertainty"]+b["within_bin"]))<1e-12, b
eq=[(0.05+0.1*(i%10),1 if rnd.random()<0.5 else 0) for i in range(300)]
b=A.brier_parts(eq); assert abs(b["within_bin"])<1e-12 and abs(b["brier"]-(b["reliability"]-b["resolution"]+b["uncertainty"]))<1e-12, b
perfect=[(0.0,0)]*10+[(1.0,1)]*10; b=A.brier_parts(perfect); assert b["brier"]==0 and abs(b["resolution"]-b["uncertainty"])<1e-12
assert A.brier_parts([]) is None

# 2. luck and its standard error, by hand
bs=[A.bet("2026-11-0%d"%(1+i%3),"T%d"%i,"yes",n,0.40,0.40,0.55,0.42,w,0.02*n,n*(w-0.40)-0.02*n) for i,(n,w) in enumerate([(1,1),(2,0),(3,1),(1,0)])]
sp=A.split(bs)
luck=sum(b["n"]*(b["win"]-0.42) for b in bs); se=math.sqrt(sum(b["n"]**2*0.42*0.58 for b in bs))
assert abs(sp["luck"]-luck)<1e-12 and abs(sp["luck_se"]-se)<1e-12 and abs(sp["luck_z"]-luck/se)<1e-12, sp
assert abs(sp["vs_model_se"]-math.sqrt(sum(b["n"]**2*0.55*0.45 for b in bs)))<1e-12

# 3. the profit split: parts add up to the net exactly; fees, execution and the spread land where they should
assert abs(sp["fees"]+0.02*7)<1e-12 and abs(sp["execution"])<1e-12 and abs(sp["other"])<1e-9, sp
assert abs(sp["claimed_edge"]-7*(0.55-0.40))<1e-12 and abs(sp["spread_vs_market"]-7*(0.42-0.40))<1e-12
ex=[A.bet("2026-11-01","X","no",4,0.05,0.07,0.09,None,0,0.04,4*(0-0.07)-0.04)]   # filled 2c above the decision price, no market quote
s2=A.split(ex)
assert abs(s2["execution"]+4*0.02)<1e-12 and abs(s2["fees"]+0.04)<1e-12 and ex[0]["mkt_from_price"] and abs(s2["spread_vs_market"])<1e-12
assert abs(sum(s2[k] for k in ("claimed_edge","market_view","luck","execution","fees","other"))-s2["pnl"])<1e-12
# day-clustered standard error of a ratio: two equal days -> zero error; one day -> no error
assert A.ratio_cse([(1.0,2.0),(1.0,2.0)])==(0.5,0.0) and A.ratio_cse([(1.0,2.0)])[1] is None and A.ratio_cse([])==(None,None)
# the words: a fee-sized loss with ordinary luck reads "fees"; outcomes far below the market's odds read "miscalibration"; few bets "too few"
days=["2026-10-%02d"%(1+i%20) for i in range(200)]
fee_case=[A.bet(d,"F%d"%i,"yes",1,0.50,0.50,0.60,0.50,i%2,0.05,(i%2)-0.50-0.05) for i,d in enumerate(days)]
assert "mostly fees and costs" in A.verdict(A.split(fee_case),200,20), A.verdict(A.split(fee_case),200,20)
bad=[A.bet(d,"B%d"%i,"yes",1,0.50,0.50,0.60,0.50,1 if i%10==0 else 0,0.0,(1 if i%10==0 else 0)-0.50) for i,d in enumerate(days)]
v=A.verdict(A.split(bad),200,20); assert "mostly miscalibration" in v and "too high" in v, v
assert A.verdict(A.split(bad[:5]),5,2).startswith("Too few")

# 4. missing sources tolerated: nothing on disk -> both files written, every source "not available", exit 0
r=subprocess.run([sys.executable,os.path.join(WORK,"attribution.py")],capture_output=True,text=True,env=dict(os.environ))
assert r.returncode==0, r.stderr
md=open(os.path.join(RES,"attribution.md"),encoding="utf-8").read(); J=json.load(open(os.path.join(RES,"attribution.json"),encoding="utf-8"))
assert md.count("Not available here")>=7 and "Descriptive only" in md and J["sources"]["paper_v3"]["missing"], md[:500]

# 5. fake databases for every source
sys.path.insert(0,os.path.join(WORK,"research"))
import core, audit
c=core.db(); assert audit.ensure(c)
import ast   # shadow.py's own table definitions, read without importing it
TB=[n.value for n in ast.parse(open(os.path.join(WORK,"shadow.py"),encoding="utf-8").read()).body if isinstance(n,ast.Assign) and getattr(n.targets[0],"id",None)=="TABLES"][0]
TB=ast.literal_eval(TB)
for t in ("shadow_orders","v4_obs","v4_paper"): c.execute(TB[t])
from datetime import date, timedelta
for d in range(25):
    day=(date(2026,10,14)+timedelta(days=d)).strftime("%y%b%d").upper()
    for ci in ("NYC","SEA","MIA"):
        t="KXRAIN-%s-%s"%(day,ci); fc=rnd.random(); mid=min(max(fc+rnd.uniform(-0.25,0.25),0.03),0.97); y="yes" if rnd.random()<mid else "no"
        c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",(t,"v3",time.time(),fc,mid,y,"rain"))
        side="yes" if fc>mid else "no"; price=round((mid if side=="yes" else 1-mid)+0.01,2); n=2; fee=core.fee(price,n)
        pnl=(n if y==side else 0)-n*price-fee
        cur=c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (time.time(),t,side,price,price+0.09,n,n*price,fee,"settled",y,pnl,"v3",time.time()))
        c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,mode,ticker,action,side,reason,mid,p_win,price,trade_ref) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("d%d"%cur.lastrowid,"s",time.time(),"v3_rain","paper",t,"trade",side,"TRADE",mid,price+0.09,price,"trades:%d"%cur.lastrowid))
        c.execute("insert into shadow_orders(ts,ticker,strategy,version,side,price,fair,fc,bid,ask,improved,n,cost,fee,status,result,pnl) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (time.time(),t,"maker","v3",side,price-0.02,price+0.07,fc,mid-0.02,mid+0.02,1,1,price-0.02,0,"settled",y,(1 if y==side else 0)-(price-0.02)))
        c.execute("insert into v4_obs(ticker,ts,station,fc,mid,bid,ask,result) values(?,?,?,?,?,?,?,?)",(t,time.time(),"K"+ci,fc,mid,mid-0.02,mid+0.02,y))
        tf=math.ceil(0.07*price*(1-price)*100-1e-9)/100
        c.execute("insert into v4_paper(ticker,kind,side,price,improved,filled,result,pnl) values(?,?,?,?,?,?,?,?)",(t,"taker",side,price,None,1,y,(1 if y==side else 0)-price-tf))
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"KXRAIN-26OCT30-PHX","yes",0.3,0.4,1,0.3,0.02,"settled","scalar",0.67,"v3"))   # scalar: kept with its ledger P&L
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"KXRAIN-26OCT31-PHX","no",0.6,0.7,2,1.2,0.04,"settled","void",-0.04,"v3"))     # void: kept, -fee
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"KXRAIN-BADDAY-NYC","yes",0.3,0.4,1,0.3,0.02,"settled","yes",0.68,"v3"))     # no readable day: skipped
LEDGER=sum(r[0] for r in c.execute("select pnl from trades where version='v3' and status='settled' and ticker like 'KXRAIN%' and ticker!='KXRAIN-BADDAY-NYC'"))
c.commit(); c.close()
L15=open(os.path.join(WORK,"research","live15.py"),encoding="utf-8").read().split('SCHEMA = """',1)[1].split('"""',1)[0]
c=sqlite3.connect(os.environ["LIVE15_DB"]); c.executescript(L15)
for i in range(40):
    pu=rnd.random(); ya=round(min(max(pu+rnd.uniform(-0.1,0.1),0.02),0.98),2); na=round(1-ya+0.02,2); side="yes" if pu-ya>(1-pu)-na else "no"
    price=ya if side=="yes" else na; res="yes" if rnd.random()<0.5 else "no"; f=0.02
    c.execute("insert into bets(window,asset,k,ts,open_ts,close_ts,p_up,yes_ask,no_ask,side,price,fee,status,result,pnl) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("W%d"%i,"BTC",2,1795000000+i*900,1795000000+i*900,1795000000+i*900+900+86400*(i%6),pu,ya,na,side,price,f,"settled",res,(1 if res==side else 0)-price-f))
c.commit(); c.close()
os.makedirs(os.environ["LIVE20_DATA"],exist_ok=True)
with open(os.path.join(os.environ["LIVE20_DATA"],"paper.jsonl"),"w",encoding="utf-8") as f:
    for i in range(12):
        w=1.0 if i%6==0 else 0.0; c_=20
        f.write(json.dumps(dict(day="2026-11-%02d"%(10+i%4),series="KXS",ticker="KXS-%d"%i,side="yes",ask=0.04,price=0.05,contracts=c_,fee=0.02,win=w,p=0.08,profit=w-0.05-0.02/c_))+"\n")
    f.write("not json\n")
    f.write(json.dumps(dict(day="2026-11-12",ticker="KXS-zero",side="yes",ask=0.04,price=0.05,contracts=0,fee=0.0,win=1.0,p=0.08,profit=0.95))+"\n")   # no contracts: skipped
    f.write(json.dumps(dict(day="soon",ticker="KXS-day",side="yes",ask=0.04,price=0.05,contracts=20,fee=0.02,win=0.0,p=0.08,profit=-0.051))+"\n")   # no day: skipped
json.dump(dict(env="prod",ts=time.time(),ok=True,days=14,fills=[dict(bot=True,count=2,fee=0.02),dict(bot=False,count=5,fee=0.07)],
               settlements=[dict(bot=False,who="mixed",cost=1.0,revenue=0.0),dict(bot=True,who="bot",cost=0.4,revenue=1.0),dict(bot=False,who="you",cost=0.2,revenue=0.0)]),
          open(os.environ["TRADEBOT_ACCOUNT_JSON"],"w"))

# 6. read-only and writes only its results folder
def tree():
    out={}
    for root,_,fs in os.walk(OUT):
        for f in fs:
            p=os.path.join(root,f)
            if os.path.abspath(p).startswith(os.path.abspath(RES)+os.sep): continue
            out[p]=(hashlib.sha256(open(p,"rb").read()).hexdigest(),os.path.getmtime(p))
    return out
def worktree():
    return {os.path.join(r,f) for r,_,fs in os.walk(os.path.join(WORK,"research","results")) for f in fs}
before,wb=tree(),worktree()
r=subprocess.run([sys.executable,os.path.join(WORK,"attribution.py")],capture_output=True,text=True,env=dict(os.environ))
assert r.returncode==0, r.stdout+r.stderr
assert tree()==before, "attribution.py changed a file outside its results folder"
assert worktree()==wb, "attribution.py wrote into the project's own research/results"
assert sorted(os.listdir(RES))==["attribution.json","attribution.md"], os.listdir(RES)
cr=A.ro(os.environ["PAPER_DB"])
try: cr.execute("create table x(a)"); raise AssertionError("connection is not read-only")
except sqlite3.OperationalError: pass
finally: cr.close()

J=json.load(open(os.path.join(RES,"attribution.json"),encoding="utf-8")); S=J["sources"]
for k,n in (("paper_v3",77),("shadow_maker",75),("v4_taker",75),("live15",40),("live20",12)):
    a=S[k]; assert a["bets"]==n, (k,a.get("bets"),a)
    sp=a["split"]; assert abs(sum(sp[x] for x in ("claimed_edge","market_view","luck","execution","fees","other"))-sp["pnl"])<1e-9, (k,sp)
    for who in ("model","market"):
        p=a["calibration"][who]["parts"]; assert abs(p["brier"]-(p["reliability"]-p["resolution"]+p["uncertainty"]+p["within_bin"]))<1e-12
    assert a["rolling"] and all(w["days"]<=14 for w in a["rolling"])
assert S["paper_v3"]["skipped"]==1 and S["paper_v3"]["not_yes_no"]==2 and S["live20"]["skipped"]==3 and S["v4_maker"]["bets"]==0, (S["paper_v3"]["skipped"],S["live20"]["skipped"])
# scalar and void bets keep their ledger P&L: the net equals the ledger; calibration and luck use yes/no bets only
assert abs(S["paper_v3"]["split"]["pnl"]-LEDGER)<1e-9 and S["paper_v3"]["calibration"]["model"]["parts"]["n"]==75
assert S["paper_v3"]["calibration"]["raw"]["parts"]["n"]==75 and S["paper_v3"]["model_label"]=="blend (50/50 model+market)" and S["live15"]["model_label"]!=S["paper_v3"]["model_label"]
sc=[A.bet("2026-11-01","S","yes",1,0.30,0.30,0.40,0.35,None,0.02,0.67)]; s3=A.split(sc)   # scalar: luck 0, the payout in other
assert s3["luck"]==0 and s3["luck_se"]==0 and abs(s3["pnl"]-0.67)<1e-12 and abs(s3["other"]-(0.67-(0.10-0.05+0-0.02)))<1e-12, s3
assert S["paper_v3"]["split"]["fees"]<0 and abs(S["shadow_maker"]["split"]["fees"])<1e-12
assert abs(S["live20"]["split"]["execution"]+12*20*0.01)<1e-9, S["live20"]["split"]["execution"]   # filled 1c above the decision ask
assert S["v4_taker"]["split"]["fees"]<0
assert S["obs_v3"]["markets"]==75 and S["obs_v4"]["markets"]==75
G=J["account"]["groups"]; assert J["account"]["env"]=="prod" and sorted(G)==["bot","mixed","you"]
assert G["bot"]["fills"]==1 and G["you"]["fills"]==1 and G["mixed"]["fills"]==0 and G["bot"]["won"]==1 and G["mixed"]["settlements"]==1 and G["you"]["settlements"]==1, G
md=open(os.path.join(RES,"attribution.md"),encoding="utf-8").read()
for s in ("## Paper bot, v3 rain","In words:","Luck: outcomes vs the market's chances","Rolling 14-day windows","| Brier | Score | Reliability","Kalshi account","prod exchange","| mixed |","| you |","changes no rule","blend (50/50 model+market)","SE (not clustered)","not the gate's day-mean statistic","v3 raw forecast"):
    assert s in md, s

# 7. the dashboard section reads the JSON (presentation only) and is absent without it
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db")
import dashboard
h=dashboard.attribution_section(); assert "id=attribution" in h and "Paper bot, v3 rain" in h and "changes no rule" in h and "blend (50/50 model+market)" in h, h[:300]
assert "SE (not clustered)" in h and "prod exchange" in h, h
# hostile text in the report is escaped on the page
HOS=os.path.join(OUT,"hostile"); os.makedirs(HOS,exist_ok=True)
J2=dict(J); J2["labels"]=dict(J["labels"],paper_v3="<script>alert(1)</script>"); J2["sources"]=dict(S,paper_v3=dict(S["paper_v3"],verdict="<script>bad()</script>",model_label="<img src=x onerror=y>"))
J2["account"]=dict(J["account"],env="<script>env</script>")
json.dump(J2,open(os.path.join(HOS,"attribution.json"),"w",encoding="utf-8"))
os.environ["TRADEBOT_RESULTS"]=HOS; h=dashboard.attribution_section()
assert "<script>" not in h and "<img" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "&lt;script&gt;bad()" in h and "&lt;script&gt;env" in h, h
os.environ["TRADEBOT_RESULTS"]=os.path.join(OUT,"nowhere"); assert dashboard.attribution_section()==""
print("attribution: all checks passed")
