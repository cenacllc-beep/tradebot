"""Synthetic paper.db with ~45 days of trades to exercise the account view. python acct_mock.py WORK OUT"""
import os, sys, random, time
WORK,OUT=sys.argv[1],sys.argv[2]; os.chdir(OUT); os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"off")
sys.path.insert(0,WORK); import core, shadow
c=core.db(); shadow.tables(c); random.seed(5); now=time.time(); t0=now-46*86400
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)",("KXRAIN-26AUG30-NYC","v3",t0,0.3,0.3,"rain"))
cities=["NYC","PHIL","MIA","CHI","DEN","SEA","ATL","BOS"]
for i in range(60):
    ts=t0+random.uniform(0,45.5*86400); city=random.choice(cities); d=time.strftime("%y%b%d",time.localtime(ts+86400)).upper()
    side=random.choice(["yes","no"]); price=round(random.uniform(0.2,0.7),2); n=random.randint(1,4); cost=n*price; fee=round(-(-0.07*n*price*(1-price)*100//1)/100,2)
    st=ts+1.6*86400; settled=st<now
    res=random.choice(["yes","no"]) if settled else None
    pnl=((n if res==side else 0)-cost-fee) if settled else None
    c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,status,result,pnl,version,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (ts,"KXRAIN-%s-%s"%(d,city),side,price,price+0.1,n,cost,fee,"settled" if settled else "open",res,pnl,"v3",st if settled else None))
    if random.random()<0.6:
        filled=random.random()<0.75; ok=filled and st<now; r2=random.choice(["yes","no"]) if ok else None; p2=price-0.01
        c.execute("insert into shadow_orders(ts,ticker,strategy,version,side,price,fair,fc,bid,ask,improved,n,cost,fee,cancel_ts,status,fill_ts,result,pnl,settle_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (ts,"KXRAIN-%s-%s"%(d,city),"maker","v3",side,p2,p2+0.1,0.5,p2,p2+0.03,1,n,n*p2,0.0,ts+4*3600,("settled" if ok else ("filled" if filled else "unfilled")),ts+3600 if filled else None,r2,((n if r2==side else 0)-n*p2) if ok else None,st if ok else None))
c.commit(); print("ok")
