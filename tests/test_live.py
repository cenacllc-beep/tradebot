"""live.py against a fake Kalshi exchange: signatures (Ed25519 and RSA-PSS), every lock, the $25 cap, copying rules,
no double orders (also after a lost ledger), unknown outcomes, partial fills, missing fields, settlement, loss stops,
setup input checks; paper.db never changes. python test_live.py WORK OUT"""
import os, sys, json, time, base64, hashlib, io, contextlib, uuid, math, subprocess, re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ.setdefault("PAPER_DB",os.path.join(OUT,"paper.db")); os.environ.setdefault("TRADEBOT_OFFSITE_BACKUPS",os.path.join(OUT,"offsite"))
os.environ["TRADEBOT_KALSHI_DIR"]=os.path.join(OUT,"kalshi"); os.environ.pop("LIVE_DB",None)
for v in ("KALSHI_ENV","KALSHI_KEY_ID","KALSHI_KEY_FILE"): os.environ.pop(v,None)
assert os.path.isabs(os.environ["PAPER_DB"]) and not os.environ["PAPER_DB"].startswith(WORK), "tests must never use the real paper.db"
sys.path.insert(0,WORK)
try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
except ImportError:
    print("SKIPPED: the cryptography package is not installed"); sys.exit(0)
import requests, core, live
UA="tradebot-paper-research/1.0"
assert live.LIVE_DB==os.path.join(OUT,"live.db"), live.LIVE_DB

# ---------- keys ----------
os.makedirs("keys",exist_ok=True)
def write_key(k,name,fmt):
    p=os.path.join(OUT,"keys",name)
    with open(p,"wb") as f: f.write(k.private_bytes(serialization.Encoding.PEM,fmt,serialization.NoEncryption()))
    return p
ed=ed25519.Ed25519PrivateKey.generate(); rs=rsa.generate_private_key(public_exponent=65537,key_size=2048)
ED_FILE=write_key(ed,"demo-key.txt",serialization.PrivateFormat.PKCS8)
RS_FILE=write_key(rs,"prod-key.txt",serialization.PrivateFormat.TraditionalOpenSSL)   # "BEGIN RSA PRIVATE KEY", like Kalshi's RSA keys
ED_TEXT=open(ED_FILE).read()

# ---------- fake exchange ----------
class Resp:
    def __init__(s,code,obj,text=None): s.status_code=code; s._o=obj; s.text=json.dumps(obj) if text is None else text
    def json(s):
        if s._o is None: raise ValueError("not JSON")
        return s._o
def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
def mk(t,bid=0.40,ask=0.42,hours=30,status="active",result=""):
    m={"ticker":t,"close_time":iso(datetime.now(timezone.utc)+timedelta(hours=hours)),
       "yes_bid_dollars":"%.4f"%bid,"yes_ask_dollars":"%.4f"%ask,"result":result}
    if status is not None: m["status"]=status
    return m
class Fake:
    def __init__(s):
        s.calls=[]; s.markets={}; s.balance=100000; s.pos={}; s.extra=0.0; s.orders=[]; s.otime={}; s.mode=None
        s.fail_get=set(); s.check_ts=True; s.rename=False; s.depth={}; s.hide_orders=False; s.badpos=False
        s.pub={"ed-key-1":ed.public_key(),"rsa-key-1":rs.public_key()}
    def posts(s): return [c for c in s.calls if c[0]=="POST"]
    def total(s): return sum(e for _,e in s.pos.values())+s.extra
    def set_total(s,x): s.extra=0.0 if x is None else x-sum(e for _,e in s.pos.values())
    def request(s,method,url,headers=None,params=None,json=None,timeout=None):
        params=params or {}
        u=urlparse(url); assert u.scheme=="https" and u.netloc in ("external-api.demo.kalshi.co","api.elections.kalshi.com"), url
        assert headers.get("User-Agent")==UA, headers
        assert not any("@" in str(v) for v in headers.values()), "personal data in headers"
        assert timeout, "every request needs a timeout"
        auth="KALSHI-ACCESS-KEY" in headers
        s.calls.append((method,u.path,params,json,auth,u.netloc))
        if auth:
            ts=headers["KALSHI-ACCESS-TIMESTAMP"]; assert ts.isdigit() and len(ts)==13, ts
            if s.check_ts: assert abs(int(ts)-time.time()*1000)<5000, "timestamp must be milliseconds now"
            assert "?" not in u.path
            if headers["KALSHI-ACCESS-KEY"] not in s.pub: return Resp(401,{"error":{"code":"unauthorized"}})
            msg=(ts+method+u.path).encode(); sig=base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]); pub=s.pub[headers["KALSHI-ACCESS-KEY"]]
            if isinstance(pub,ed25519.Ed25519PublicKey): pub.verify(sig,msg)
            else: pub.verify(sig,msg,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())   # salt = SHA-256 digest length
        ep=u.path.split("/trade-api/v2",1)[1]
        if method=="GET" and ep in s.fail_get: return Resp(500,{"error":"down"})
        if method=="GET" and ep.startswith("/markets/"):
            m=s.markets.get(ep[len("/markets/"):]); return Resp(200,{"market":m}) if m else Resp(404,{"error":{"code":"not_found"}})
        if method=="GET" and ep=="/markets":
            ms=[m for m in s.markets.values() if not params.get("series_ticker") or m["ticker"].startswith(params["series_ticker"])]
            return Resp(200,{"markets":ms,"cursor":""})
        assert auth, "portfolio calls must be signed: "+ep
        if ep=="/portfolio/balance": return Resp(200,{"balance":s.balance})
        if ep=="/portfolio/positions":
            k="exposure_dollars" if s.rename else "market_exposure_dollars"
            mp=[{"ticker":t,"position_fp":"%.2f"%n,k:"%.4f"%e} for t,(n,e) in s.pos.items()]
            if s.badpos: mp=[{"exposure":1} for _ in mp] or [{"exposure":1}]
            if s.extra: mp.append({"ticker":"OTHER","position_fp":"1.00",k:"%.4f"%s.extra})
            if params.get("ticker"): mp=[m for m in mp if m["ticker"]==params["ticker"]]
            return Resp(200,{"market_positions":mp,"event_positions":[],"cursor":""})
        if ep=="/portfolio/orders" and method=="GET":
            os_=[] if s.hide_orders else [o for o in s.orders if (not params.get("ticker") or o["ticker"]==params["ticker"]) and (not params.get("status") or o["status"]==params["status"])
                 and s.otime.get(o["order_id"],0)>=params.get("min_ts",0)]
            return Resp(200,{"orders":os_,"cursor":""})
        if ep=="/portfolio/orders" and method=="POST": return Resp(410,{"error":{"code":"deprecated_v1_order_endpoint","message":"Please switch to the V2 endpoints"}})
        if ep=="/portfolio/events/orders" and method=="POST":   # Kalshi's V2 create-order shape (docs.kalshi.com, Oct 2026)
            b=json; assert set(b)=={"ticker","side","count","price","time_in_force","self_trade_prevention_type","client_order_id"}, b
            assert b["side"] in ("bid","ask") and b["time_in_force"]=="immediate_or_cancel" and b["self_trade_prevention_type"]=="taker_at_cross"
            assert isinstance(b["count"],str) and re.fullmatch(r"\d+\.00",b["count"]) and float(b["count"])>=1, b["count"]
            assert isinstance(b["price"],str) and re.fullmatch(r"0\.\d{4}",b["price"]) and 0.01<=float(b["price"])<=0.99, b["price"]
            assert b["client_order_id"].startswith("tb-") and len(b["client_order_id"])<=64
            if s.mode=="reject": return Resp(400,None,text="r\u00e9jected \u2013 test")   # non-JSON, non-ASCII error text
            if s.mode=="timeout_before": raise requests.exceptions.ConnectTimeout("x")
            if s.mode=="500": return Resp(503,{})
            m=s.markets[b["ticker"]]; cnt=int(float(b["count"])); px=round(float(b["price"])*100)
            if b["side"]=="bid": fillpx=round(float(m["yes_ask_dollars"])*100); ok=px>=fillpx; side="yes"; paid=fillpx   # buy YES at the ask
            else: fillpx=round(float(m["yes_bid_dollars"])*100); ok=px<=fillpx; side="no"; paid=100-fillpx            # sell YES at the bid = buy NO
            n=min(cnt,s.depth.get(b["ticker"],10**6)) if ok else 0; cost=n*paid; fee=math.ceil(0.07*n*(paid/100)*(1-paid/100)*100) if n else 0
            oid=str(uuid.uuid4())
            listed={"order_id":oid,"client_order_id":b["client_order_id"],"ticker":b["ticker"],"side":side,"action":"buy",   # as GET /portfolio/orders lists it
                    "status":"executed" if n==cnt else "canceled","fill_count_fp":"%.2f"%n,"remaining_count_fp":"0.00"}
            s.orders.append(listed); s.otime[oid]=time.time(); s.balance-=cost+fee
            if n: p=s.pos.get(b["ticker"],(0,0.0)); s.pos[b["ticker"]]=(p[0]+(n if side=="yes" else -n),p[1]+cost/100)
            o={"order_id":oid,"client_order_id":b["client_order_id"],"fill_count":"%.2f"%n,"remaining_count":"0.00","ts_ms":int(time.time()*1000)}
            if n: o["average_fill_price"]="%.4f"%(fillpx/100); o["average_fee_paid"]="%.4f"%(fee/100/n)
            if s.mode=="badavg" and n: o["average_fill_price"]="0.9900"
            if s.mode=="timeout_after": raise requests.exceptions.ReadTimeout("x")
            if s.mode=="noid": return Resp(201,{k:v for k,v in o.items() if k!="order_id"})
            if s.mode=="nofill": return Resp(201,{k:v for k,v in o.items() if k not in ("fill_count","average_fill_price","average_fee_paid")})
            return Resp(201,o)
        raise AssertionError("unexpected call %s %s"%(method,ep))
F=Fake(); live.HTTP=F
def run(f,*a):
    h=ph(); buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        try: f(*a); code=0
        except SystemExit as e: code=e.code
    assert ph()==h, "live.py changed paper.db"
    return buf.getvalue(),code
def settings(env,mirror_from=0):
    os.makedirs(os.environ["TRADEBOT_KALSHI_DIR"],exist_ok=True)
    keys={"demo":{"key_id":"ed-key-1","key_file":ED_FILE},"prod":{"key_id":"rsa-key-1","key_file":RS_FILE}}
    json.dump({"env":env,"keys":keys,"mirror_from":{"demo":mirror_from,"prod":mirror_from}},open(live.SETTINGS,"w"))
c=core.db()
SAME=object()
def paper(t,side="yes",price=0.42,n=3,version="v3",age=60,status="open",fc=0.30,slices=None,mid=None,decision=True,dec_fc=SAME):
    """A paper trade as the scan writes it: v3's forecast, the YES mid and the 24 hourly chances in obs (first snapshot
    kept), and, once the decision ledger exists, the trade's decision row (p_model = dec_fc, default fc). By default the
    hourly chances agree with the trade's side (the 6-hour filter passes): one 6-hour block 23 points above the YES mid
    for YES or 23 below it for NO, the rest 0% (an edge of about 11 points, inside the 30-point veto)."""
    if mid is None: mid=price if side=="yes" else 1-price
    if slices is None: slices=[0]*12+[max(0,min(100,round((mid+(0.23 if side=="yes" else -0.23))*100)))]+[0]*11
    if fc is not None:   # the scan logs v3's forecast for every market it trades (obs); the no-rain filter reads it
        c.execute("insert or ignore into obs(ticker,version,ts,fc,mid,market_type,slices) values(?,?,?,?,?,?,?)",(t,version,time.time()-age,fc,mid,"rain",json.dumps(slices)))
    cur=c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version,status,pnl,result) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (time.time()-age,t,side,price,0.6,n,n*price,core.fee(price,n),version,status,
                   -n*price-core.fee(price,n) if status=="settled" else None,"no" if status=="settled" else None)); pid=cur.lastrowid
    if decision and c.execute("select 1 from sqlite_master where type='table' and name='decisions'").fetchone():
        c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,mode,ticker,action,side,reason,mid,price,p_model,inputs,trade_ref) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("auto-%d"%pid,"auto-%d"%pid,time.time(),"forecast_alpha.rain.v3","paper",t,"TRADE_"+side.upper(),side,"TRADE",mid,price,
                   fc if dec_fc is SAME else dec_fc,json.dumps({"slices":slices}),"trades:%d"%pid))
    c.commit(); return pid
ph=lambda: hashlib.sha256(open(os.environ["PAPER_DB"],"rb").read()).hexdigest()
def rows(): return live.ldb().execute("select paper_id,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,client_order_id,env,note from orders order by id").fetchall()
def row(t): return [x for x in rows() if x[1]==t][-1]
def new(t,**kw): F.markets[t]=mk(t,**{k:v for k,v in kw.items() if k in ("bid","ask","hours","status")}); return paper(t,**{k:v for k,v in kw.items() if k not in ("bid","ask","hours","status")})

# 1. signing: both key types, path without the query; key file checks; paths never depend on the current folder
for kf,kid in ((ED_FILE,"ed-key-1"),(RS_FILE,"rsa-key-1")):
    k=live.load_key(kf); cl=live.Client("demo",kid,k); cl.get("/portfolio/positions",{"limit":5})
assert F.calls[-1][1]=="/trade-api/v2/portfolio/positions" and F.calls[-1][2]=={"limit":5}
proj=os.path.join(OUT,"proj"); os.makedirs(proj,exist_ok=True); inside=os.path.join(proj,"k.txt"); open(inside,"wb").write(open(ED_FILE,"rb").read())
old=live.HERE; live.HERE=proj
try: live.load_key(inside); raise AssertionError("key inside the project must be refused")
except live.ExchangeError as e: assert "inside the project" in str(e) and proj not in str(e)
live.HERE=old
bom=os.path.join(OUT,"keys","bom.txt"); open(bom,"wb").write(b"\xef\xbb\xbf"+open(ED_FILE,"rb").read().replace(b"\n",b"\r\n")); live.load_key(bom)
for bad in ("bad.txt","missing.txt"):
    if bad=="bad.txt": open(os.path.join(OUT,"keys",bad),"w").write("hello")
    try: live.load_key(os.path.join(OUT,"keys",bad)); raise AssertionError
    except live.ExchangeError as e: assert OUT not in str(e), "error messages must not show paths"
assert live._abs("paper.db")==os.path.join(live.HERE,"paper.db") and os.path.isabs(live.LIVE_DB)
assert live.cents_for(0.427)==42 and live.cents_for(0.595)==59 and live.cents_for(0.42)==42 and live.cents_for(0.58)==58 and live.cents_for(0.07)==7
assert live.valid_key_id("a952bcbe-ec3b-4b5b-b8f9-11dae589608c") and not live.valid_key_id("-----BEGIN PRIVATE KEY-----") and not live.valid_key_id("")
for line in ED_TEXT.splitlines()+["MC4CAQAwBQYDK2VwBCIEIAbcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQR"]: assert not live.valid_key_id(line), line
for line in ED_TEXT.splitlines(): assert live.looks_like_key_text(line), "key line not caught"
for p in ("",r"C:\Users\u\.kalshi\kalshi-demo-key.txt",r"%USERPROFILE%\.kalshi\kalshi-demo-key.txt","~/k.txt",r"D:\keys\my key (1).txt"): assert not live.looks_like_key_text(p), p
print("signing ok")

# 2. not set up: nothing happens, no network; status before setup leaves the dashboard tile at "Not connected"
F.calls.clear(); out,_=run(live.mirror); assert "no Kalshi account" in out and not F.calls, out
out,_=run(live.status); assert "none yet" in out and not F.calls, out
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=WORK),encoding="utf-8",errors="replace"); assert r.returncode==0, r.stderr
assert "Not connected" in open("dashboard.html",encoding="utf-8").read(), "tile before setup"

# 3. demo copy of a paper rain trade; temperature, old, v2 and settled trades are ignored; never twice
settings("demo")
p1=new("KXRAINNYC-26OCT15-T0"); new("KXHIGHNY-26OCT15-T60"); new("KXRAINCHI-26OCT15-T0",age=13*3600)
new("KXRAINMIA-26OCT15-T0",version="v2"); new("KXRAINSEA-26OCT15-T0",status="settled")
out,_=run(live.mirror); P=F.posts(); assert len(P)==1, out
b=P[0][3]; pts=int(c.execute("select ts from trades where id=?",(p1,)).fetchone()[0])
assert b["ticker"]=="KXRAINNYC-26OCT15-T0" and b["side"]=="bid" and b["count"]=="3.00" and b["price"]=="0.4200" and b["client_order_id"]=="tb-demo-%d-%d"%(p1,pts), b
assert P[0][1]=="/trade-api/v2/portfolio/events/orders", "V2 order endpoint (the old one answers HTTP 410)"
assert P[0][5]=="external-api.demo.kalshi.co"
r=row("KXRAINNYC-26OCT15-T0"); assert r[5]=="executed" and r[6]==3 and abs(r[7]-1.26)<1e-9 and abs(r[8]-0.06)<1e-9, r
out,_=run(live.mirror); assert len(F.posts())==1 and "no new paper rain trades" in out, out
print("copy ok")

# 4. price moved up, NO side, market day begun, not listed, closed market, missing status, sub-cent paper price
t="KXRAINBOS-26OCT15-T0"; new(t,ask=0.45,price=0.42)
t2="KXRAINDEN-26OCT15-T0"; new(t2,bid=0.40,side="no",price=0.60,n=2)
t3="KXRAINLAX-26OCT15-T0"; new(t3,hours=10)
paper("KXRAINPHX-26OCT15-T0")
t5="KXRAINAUS-26OCT15-T0"; new(t5,status="closed")
t6="KXRAINELP-26OCT15-T0"; new(t6,status=None)
t7="KXRAINBUF-26OCT15-T0"; new(t7,ask=0.42,price=0.427)          # paper paid 42.7c: the limit must be 42c, not 43c
out,_=run(live.mirror)
assert row(t)[5]=="skipped" and "price moved" in row(t)[13]
b2=[p for p in F.posts() if p[3]["ticker"]==t2][0][3]   # NO at 60c = sell YES at no less than 40c, opening a NO position
assert row(t2)[5]=="executed" and row(t2)[4]==60 and row(t2)[2]=="no" and b2["side"]=="ask" and b2["price"]=="0.4000", b2
assert abs(row(t2)[7]-1.20)<1e-9 and abs(row(t2)[8]-0.04)<1e-9 and F.pos[t2][0]==-2, (row(t2),F.pos[t2])
assert row(t3)[5]=="skipped" and row("KXRAINPHX-26OCT15-T0")[5]=="skipped" and row(t5)[5]=="skipped" and row(t6)[5]=="skipped", out
assert row(t7)[5]=="executed" and [p for p in F.posts() if p[3]["ticker"]==t7][0][3]["price"]=="0.4200", out
assert len(F.posts())==3, out
print("skips ok")

# 5. the $25 cap uses Kalshi's own exposure (resting buys too); cash; missing fields and exchange errors stop everything
F.set_total(24.5); t="KXRAINDCA-26OCT15-T0"; new(t,n=5)
out,_=run(live.mirror); assert row(t)[5]=="executed" and row(t)[3]==1, (out,row(t))
F.set_total(24.9); t="KXRAINATL-26OCT15-T0"; new(t)
out,_=run(live.mirror); assert row(t)[5]=="skipped" and "no room" in out, out
F.set_total(None); F.balance=30; t="KXRAINHOU-26OCT15-T0"; new(t)
out,_=run(live.mirror); assert row(t)[5]=="skipped", out
F.balance=100000
cl,_=live.client(); base=live.at_risk(cl)
F.orders.append({"order_id":"u1","client_order_id":"mine-1","ticker":"KXOTHER","side":"no","action":"buy","status":"resting","remaining_count":2,"no_price":40,"yes_price":60})
assert abs(live.at_risk(cl)-base-0.80)<1e-9, "resting buy orders count toward the cap"
F.orders.pop()
t="KXRAINPHL-26OCT15-T0"; new(t); n0=len(F.posts())
for setup_fail in ("get","rename"):
    if setup_fail=="get": F.fail_get={"/portfolio/positions"}
    else: F.rename=True
    out,_=run(live.mirror); assert len(F.posts())==n0 and "could not read the account" in out and not [x for x in rows() if x[1]==t], out
    F.fail_get=set(); F.rename=False
out,_=run(live.mirror); assert row(t)[5]=="executed", out
t="KXRAINRIC-26OCT15-T0"; new(t,n=4); F.depth[t]=1
out,_=run(live.mirror); assert row(t)[5]=="partial" and row(t)[6]==1 and row(t)[3]==4 and abs(row(t)[7]-0.42)<1e-9, (out,row(t))   # partial fill: 1 of 4
F.mode="badavg"; t="KXRAINMEM-26OCT15-T0"; new(t); out,_=run(live.mirror); F.mode=None   # an average price above the limit is not believed
assert abs(row(t)[7]-1.26)<1e-9 and "did not fit the limit" in row(t)[13], row(t)
print("cap ok")

# 6. rejected, unknown (answer lost after Kalshi placed it), unknown (never arrived), 5xx, incomplete answers, a crash mid-send
F.mode="reject"; t="KXRAINSFO-26OCT15-T0"; new(t); out,_=run(live.mirror)
assert row(t)[5]=="rejected" and "?" in row(t)[13] and all(ord(ch)<128 for ch in out), out   # non-ASCII error text is made printable
F.mode=None; n0=len(F.posts()); run(live.mirror); assert len(F.posts())==n0
F.mode="timeout_after"; t="KXRAINMSP-26OCT15-T0"; new(t); t_b="KXRAINSAT-26OCT15-T0"; new(t_b)
out,_=run(live.mirror); assert row(t)[5]=="unknown" and not [x for x in rows() if x[1]==t_b], out   # stops after an unknown
F.mode=None; out,_=run(live.mirror); assert row(t)[5]=="executed" and row(t_b)[5]=="executed", out
assert sum(1 for o in F.orders if o["ticker"]==t)==1, "an unknown order must never be sent again"
for mode in ("noid","nofill"):
    F.mode=mode; t="KXRAINOMA-26OCT15-T0" if mode=="noid" else "KXRAINBNA-26OCT15-T0"; new(t); out,_=run(live.mirror); F.mode=None
    assert row(t)[5]=="unknown" and "incomplete" in out, out
    out,_=run(live.mirror); assert row(t)[5]=="executed" and row(t)[6]==3, out
# an answer with fills but no cost or fee fields is stored at limit x fills plus the fee formula, never $0
L=live.ldb(); rid=L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,client_order_id,status) values(?,?,?,?,?,?,?,?)",(time.time(),"demo","KXNOCOST","yes",3,42,"tb-demo-x-2","sending")).lastrowid; L.commit()
live.record(L,rid,{"order_id":"z","status":"executed","fill_count":3})
r=L.execute("select cost,fees from orders where id=?",(rid,)).fetchone(); assert abs(r[0]-1.26)<1e-9 and abs(r[1]-0.06)<1e-9, r
L.execute("update orders set status='not placed',fill_count=0 where id=?",(rid,)); L.commit()
# an order found later through GET: its average price is not trusted (unverified for V2 orders), cost at the limit
rid=L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,client_order_id,status) values(?,?,?,?,?,?,?,?)",(time.time(),"demo","KXNOCOST2","no",3,60,"tb-demo-x-3","sending")).lastrowid; L.commit()
x=live.record(L,rid,{"order_id":"z","fill_count_fp":"3.00","average_fill_price":"0.5800"})
assert abs(L.execute("select cost from orders where id=?",(rid,)).fetchone()[0]-1.80)<1e-9 and abs(x-1.80-live.fee(0.6,3))<1e-9
# a fractional fill from the V2 answer is kept as a fraction and marked partial; a $0 price never lowers the money counted
rid=L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,client_order_id,status) values(?,?,?,?,?,?,?,?)",(time.time(),"demo","KXFRAC","yes",3,50,"tb-demo-x-4","sending")).lastrowid; L.commit()
x=live.record(L,rid,{"order_id":"z","fill_count":"1.37","average_fill_price":"0.0000","average_fee_paid":"0.0000"},v2=True)
r=L.execute("select status,fill_count from orders where id=?",(rid,)).fetchone(); assert r==("partial",1.37) and x>=1.37*0.5, (r,x)
L.execute("update orders set status='not placed',fill_count=0 where id in (select id from orders where ticker in ('KXNOCOST2','KXFRAC'))"); L.commit()
F.mode="timeout_before"; t="KXRAINPDX-26OCT15-T0"; new(t); run(live.mirror); F.mode=None
L=live.ldb(); L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,client_order_id,status) values(?,?,?,?,?,?,?,?)",(time.time(),"demo","KXRAINCRASH","yes",1,50,"tb-demo-x-1","sending")); L.commit()
out,_=run(live.mirror); assert "2 earlier order(s) have an unknown outcome" in out, out
real=live.now; live.now=lambda: real()+1801; F.check_ts=False
out,_=run(live.sync); live.now=real; F.check_ts=True
assert row(t)[5]=="not placed" and row("KXRAINCRASH")[5]=="not placed", out
F.mode="500"; t="KXRAINDTW-26OCT15-T0"; new(t); run(live.mirror); F.mode=None
assert row(t)[5]=="unknown"
out,_=run(live.sync); assert row(t)[5]=="unknown", out   # not on Kalshi yet, under 30 minutes: stays unknown
live.ldb().execute("update orders set status='not placed' where ticker=?",(t,)).connection.commit()
# answer lost, order not listed by Kalshi, but a position exists: recorded from the position, not as "not placed"
F.mode="timeout_after"; t="KXRAINCLT-26OCT15-T0"; new(t); run(live.mirror); F.mode=None; F.hide_orders=True
live.now=lambda: real()+1801; F.check_ts=False; out,_=run(live.sync); live.now=real; F.check_ts=True; F.hide_orders=False
assert row(t)[5]=="filled (from position)" and row(t)[6]==3, (out,row(t))
print("unknown outcomes ok")

# 7. one bot order per market even if live.db loses rows (restored backup), checked on Kalshi; place() re-checks everything
t="KXRAINTUL-26OCT15-T0"; pt=new(t); run(live.mirror); assert row(t)[5]=="executed"; n0=len(F.posts())
live.ldb().execute("delete from orders where ticker=?",(t,)).connection.commit()
out,_=run(live.mirror); assert len(F.posts())==n0 and row(t)[5]=="skipped" and "already has a bot order" in row(t)[13], out
live.ldb().execute("delete from orders where ticker=?",(t,)).connection.commit(); F.hide_orders=True
out,_=run(live.mirror); F.hide_orders=False; assert len(F.posts())==n0 and "already holds" in row(t)[13], out
cl,_=live.client(); L=live.ldb(); t="KXRAINABQ-26OCT15-T0"; pid=new(t,n=2)
for args,why in (((t,"yes",3,42),"more contracts"),((t,"yes",2,43),"higher price"),((t,"no",2,42),"other side"),(("KXRAINNYC-26OCT15-T0","yes",2,42),"other market")):
    try: live.place(cl,L,"demo",pid,*args,note="x"); raise AssertionError(why)
    except live.ExchangeError as e: assert "does not match" in str(e), e
tid=new("KXHIGHDEN-26OCT15-T50")
try: live.place(cl,L,"demo",tid,"KXHIGHDEN-26OCT15-T50","yes",1,42,note="x"); raise AssertionError("temperature")
except live.ExchangeError: pass
try: live.place(cl,L,"demo",None,t,"yes",2,42,note="x"); raise AssertionError("no paper trade")
except live.ExchangeError: pass
assert len(F.posts())==n0
print("duplicates ok")

# 8. settlement and P&L
F.markets["KXRAINNYC-26OCT15-T0"]["result"]="yes"; F.markets["KXRAINDEN-26OCT15-T0"]["result"]="yes"
out,_=run(live.sync)
assert abs(row("KXRAINNYC-26OCT15-T0")[10]-(3-1.26-0.06))<1e-9 and abs(row("KXRAINDEN-26OCT15-T0")[10]-(0-1.2-0.04))<1e-9, out
assert "mismatch" not in out, out   # every open market's Kalshi position agrees with the ledger
# a fill the ledger does not know about (or a manual trade) stops new orders until positions agree again
F.pos["KXRAINDCA-26OCT15-T0"]=(F.pos["KXRAINDCA-26OCT15-T0"][0]+2,F.pos["KXRAINDCA-26OCT15-T0"][1]+0.84)
out,_=run(live.sync); assert "WARNING position mismatch" in out and "KXRAINDCA-26OCT15-T0: Kalshi 3, ledger 1" in out, out
t="KXRAINLIT-26OCT15-T0"; new(t); n0=len(F.posts()); out,_=run(live.mirror); assert "position mismatch" in out and len(F.posts())==n0, out
F.pos["KXRAINDCA-26OCT15-T0"]=(F.pos["KXRAINDCA-26OCT15-T0"][0]-2,F.pos["KXRAINDCA-26OCT15-T0"][1]-0.84)
out,_=run(live.sync); assert "agree with the ledger again" in out, out
out,_=run(live.mirror); assert row(t)[5]=="executed", out
# the position check fails closed when Kalshi's answer lacks the fields (a NO copy is a YES sell)
F.badpos=True
try: live.holding(live.client()[0],"KXRAINDCA-26OCT15-T0"); raise AssertionError("holding() must fail closed")
except live.ExchangeError: pass
F.badpos=False
# Kalshi's scalar and void settlements (2026-11-06): the order closes with Kalshi's value, so its loss reaches the daily
# stop and the drawdown pause and its cost stops counting as at risk; an unreadable value leaves it open, with a warning
t="KXRAINDCA-26OCT15-T0"; r0=row(t); assert r0[6]>0 and r0[9] is None, r0
risk0=live.local_at_risk(L,"demo"); day0=live.day_pnl(L,"demo")
F.markets[t].update(status="finalized",result="scalar")   # no value yet
out,_=run(live.sync); assert row(t)[9] is None and "no usable settlement value; left open" in out, out
F.markets[t]["settlement_value_dollars"]="0.0100"
out,_=run(live.sync); r1=row(t)
side=r1[2]; exp=round(r1[6]*(0.01 if side=="yes" else 0.99)-r1[7]-r1[8],4)
assert r1[9]=="scalar" and abs(r1[10]-exp)<1e-9, (r1, exp, out)
assert abs(live.local_at_risk(L,"demo")-(risk0-r1[7]-r1[8]))<1e-9 and abs(live.day_pnl(L,"demo")-(day0+exp))<1e-9
t2="KXRAINLIT-26OCT15-T0"; r2=row(t2); assert r2[6]>0 and r2[9] is None, r2
F.markets[t2].update(status="finalized",result="void")
out,_=run(live.sync); r2=row(t2); assert r2[9]=="void" and abs(r2[10]+r2[8])<1e-9, (r2, out)
print("settle ok")

# 8b. the user's no-rain filter (2026-11-06): a NO copy is skipped when v3 itself says rain 50%+, or when its forecast
# cannot be read (fail closed); YES copies and NO copies under 50% go ahead; place() blocks it too, so no caller can skip it
cases=(("KXRAINF1-26OCT15-T0","no",0.67,"skipped"),("KXRAINF2-26OCT15-T0","no",0.50,"skipped"),("KXRAINF3-26OCT15-T0","no",None,"skipped"),
       ("KXRAINF4-26OCT15-T0","no",0.49,"executed"),("KXRAINF5-26OCT15-T0","yes",0.90,"executed"))
ids={}
for t,side,fc,_ in cases:
    ids[t]=new(t,side=side,price=0.60 if side=="no" else 0.42,n=1,fc=fc)
out,_=run(live.mirror)
for t,side,fc,want in cases:
    assert row(t)[5]==want, (t,row(t),out)
assert "no-rain filter: v3 itself says rain 67%" in row("KXRAINF1-26OCT15-T0")[13] and "could not be read" in row("KXRAINF3-26OCT15-T0")[13], out
n0=len(F.posts()); out,_=run(live.mirror); assert len(F.posts())==n0, "a skipped copy is never retried"
t="KXRAINF6-26OCT15-T0"; pid=new(t,side="no",price=0.60,n=1,fc=0.80)
try: live.place(live.client()[0],live.ldb(),"demo",pid,t,"no",1,60,note="x"); raise AssertionError("place() must apply the filter")
except live.ExchangeError as e: assert "order blocked: no-rain filter" in str(e), e
assert len(F.posts())==n0
out,_=run(live.status); assert "Filter: 'no rain' paper bets are not copied when v3 itself says rain 50% or more" in out, out
# the trade's own decision row (written with the trade) wins over an older first snapshot in obs
import audit
audit.ensure(c)
for t,fc_obs,fc_dec in (("KXRAINF7-26OCT15-T0",0.30,0.70),("KXRAINF8-26OCT15-T0",0.70,0.30)):
    pid=new(t,side="no",price=0.60,n=1,fc=fc_obs,dec_fc=fc_dec)
    assert abs(live.v3_forecast(t,pid)-fc_dec)<1e-12 and abs(live.v3_forecast(t)-fc_obs)<1e-12
# while the ledger exists, a NO trade without its decision row, or with an empty forecast in it, is not copied (review)
t9="KXRAINF9-26OCT15-T0"; new(t9,side="no",price=0.60,n=1,fc=0.20,decision=False)   # obs says 20%, but no decision row
t10="KXRAINFA-26OCT15-T0"; pid10=new(t10,side="no",price=0.60,n=1,fc=0.20,dec_fc=None)
out,_=run(live.mirror)
assert row("KXRAINF7-26OCT15-T0")[5]=="skipped" and row("KXRAINF8-26OCT15-T0")[5]=="executed", out
assert row(t9)[5]=="skipped" and row(t10)[5]=="skipped" and "could not be read" in row(t9)[13] and "could not be read" in row(t10)[13], out
t="KXRAINFB-26OCT15-T0"; pid=new(t,side="no",price=0.60,n=1,fc=0.20,dec_fc=0.55)
n0=len(F.posts())
try: live.place(live.client()[0],live.ldb(),"demo",pid,t,"no",1,60,note="x"); raise AssertionError("place() must read the decision row")
except live.ExchangeError as e: assert "says rain 55%" in str(e), e
assert len(F.posts())==n0
print("no-rain filter ok")

# 8c. the 6-hour filter (built 2026-11-07, shipped OFF by the user's choice; tested here switched on, then off again): a copy only when v3's hours in 6-hour blocks (PLAN9's v3-6h) give the paper
# bot's own 8-point edge on the same side, against the price paid, from the trade's own decision row; fails closed
assert live.AGREE_6H is False, "shipped off: the user's choice of 2026-11-07 22:11"
live.AGREE_6H=True
import importlib.util
_path=list(sys.path)
spec=importlib.util.spec_from_file_location("plan9_for_test",os.path.join(WORK,"research","plan9.py")); p9=importlib.util.module_from_spec(spec); spec.loader.exec_module(p9)
sys.path[:]=_path
import random
rng=random.Random(7)
for _ in range(2000):   # the same number as PLAN9's frozen definition (read-only import), on random hours
    h=[rng.choice((0,0,5,10,20,30,40,50,60,70,80,90,100,rng.uniform(0,100))) for _ in range(24)]
    assert abs(live.six_hour(h)-p9.v3_6h(p9.chances(json.dumps(h))))<1e-12, h
assert live.six_hour([0]*24)==0.01 and live.six_hour([100]*24)==0.99 and abs(live.six_hour([30]*24)-(1-0.7**4))<1e-12
assert abs(live.six_hour(json.dumps([0]*12+[50]+[0]*11))-0.5)<1e-12
for bad in ([0]*23,[0]*25,[0]*23+[True],[0]*23+[float("nan")],[0]*23+[101],[0]*23+[-1],[0]*23+["5"],[0]*23+[None],"not json",None,{"a":1}):
    assert live.six_hour(bad) is None, bad
def tr(t,**kw):   # a market whose live price still lets the copy fill at the paper price
    p=kw.get("price",0.42)
    F.markets[t]=mk(t,bid=p-0.02,ask=p) if kw.get("side","yes")=="yes" else mk(t,bid=1-p,ask=1-p+0.02)
    return paper(t,n=1,**kw)
cases=(("KXRAING1-26OCT15-T0",dict(side="yes",price=0.31,mid=0.30,slices=[0]*12+[50]+[0]*11),"executed"),   # v3-6h 50%: +9 points
       ("KXRAING2-26OCT15-T0",dict(side="yes",price=0.33,mid=0.30,slices=[0]*12+[50]+[0]*11),"skipped"),    # +7 points: not enough
       ("KXRAING3-26OCT15-T0",dict(side="no",price=0.60,mid=0.40,fc=0.30,slices=[30]*24),"skipped"),        # v3 30%, but v3-6h 76%
       ("KXRAING4-26OCT15-T0",dict(side="no",price=0.60,mid=0.40,fc=0.30,slices=[0]*12+[17]+[0]*11),"executed"),     # v3-6h 17%: +11.5 points
       ("KXRAING5-26OCT15-T0",dict(side="yes",slices=[50]*23),"skipped"),                                  # 23 hours: unreadable
       ("KXRAING6-26OCT15-T0",dict(side="yes",decision=False),"skipped"))                                  # no decision row
line_ok=(live.BLEND*0.5+(1-live.BLEND)*0.30)-0.32>=live.MIN_EDGE   # exactly at the 8-point line: decided as strategy.scan does
cases+=(("KXRAING9-26OCT15-T0",dict(side="yes",price=0.32,mid=0.30,slices=[0]*12+[50]+[0]*11),"executed" if line_ok else "skipped"),
        ("KXRAINGV-26OCT15-T0",dict(side="yes",price=0.10,mid=0.10,slices=[0]*12+[50]+[0]*11),"skipped"),   # +20 points, but 40 from the mid: the veto
        ("KXRAINGW-26OCT15-T0",dict(side="yes",price=0.20,mid=0.20,slices=[0]*12+[50]+[0]*11),"executed" if abs(0.5-0.20)<=live.VETO_MAX_GAP+1e-9 else "skipped"),   # 30 points: at the veto's line, decided as strategy.scan does
        ("KXRAINGX-26OCT15-T0",dict(side="yes",price=0.19,mid=0.19,slices=[0]*12+[50]+[0]*11),"skipped"),   # 31 points: vetoed
        ("KXRAINGH-26OCT15-T0",dict(side="yes",slices=[10**400]+[0]*23),"skipped"))                        # an integer too large for a float
ids={}
for t,kw,_ in cases: ids[t]=tr(t,**kw)
# the decision row wins over an older first snapshot in obs (both ways)
for t,obs_sl,dec_sl in (("KXRAINGO-26OCT15-T0",[30]*24,[0]*12+[17]+[0]*11),("KXRAINGP-26OCT15-T0",[0]*12+[17]+[0]*11,[30]*24)):
    c.execute("insert into obs(ticker,version,ts,fc,mid,market_type,slices) values(?,?,?,?,?,?,?)",(t,"v3",time.time()-999,0.30,0.40,"rain",json.dumps(obs_sl)))
    ids[t]=tr(t,side="no",price=0.60,mid=0.40,fc=0.30,slices=dec_sl)
t7="KXRAING7-26OCT15-T0"; pid7=tr(t7,side="yes",decision=False)   # its decision row names the other side
c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,mode,ticker,action,side,reason,mid,price,p_model,inputs,trade_ref) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("d-"+t7,"s1",time.time(),"forecast_alpha.rain.v3","paper",t7,"TRADE_NO","no","TRADE",0.42,0.58,0.30,json.dumps({"slices":[50]*24}),"trades:%d"%pid7))
t8="KXRAING8-26OCT15-T0"; pid8=tr(t8,side="yes",decision=False)   # its decision row has no inputs
c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,mode,ticker,action,side,reason,mid,price,p_model,inputs,trade_ref) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("d-"+t8,"s1",time.time(),"forecast_alpha.rain.v3","paper",t8,"TRADE_YES","yes","TRADE",0.42,0.42,0.30,None,"trades:%d"%pid8)); c.commit()
out,_=run(live.mirror)
for t,_,want in cases: assert row(t)[5]==want, (t,row(t),out)
assert row(t7)[5]=="skipped" and row(t8)[5]=="skipped", out
assert row("KXRAINGO-26OCT15-T0")[5]=="executed" and row("KXRAINGP-26OCT15-T0")[5]=="skipped", out
assert "the bot's veto" in row("KXRAINGV-26OCT15-T0")[13] and "could not be read" in row("KXRAINGH-26OCT15-T0")[13], out
assert "6-hour filter: v3's hours in 6-hour blocks say rain 50%, an edge of +7.0 points on YES at 33c" in row("KXRAING2-26OCT15-T0")[13], row("KXRAING2-26OCT15-T0")
assert "say rain 76%" in row("KXRAING3-26OCT15-T0")[13] and "could not be read" in row("KXRAING5-26OCT15-T0")[13], out
assert "could not be read" in row("KXRAING6-26OCT15-T0")[13] and "could not be read" in row(t7)[13] and "could not be read" in row(t8)[13], out
assert all(r[5]!="skipped" or "6-hour filter" in r[13] for r in rows() if r[1].startswith("KXRAING")), "only the 6-hour filter skipped these"
# place() applies it too, so no caller can skip it; the no-rain filter still comes first
t="KXRAINGA-26OCT15-T0"; pid=tr(t,side="no",price=0.60,mid=0.40,fc=0.30,slices=[30]*24); n0=len(F.posts())
try: live.place(live.client()[0],live.ldb(),"demo",pid,t,"no",1,60,note="x"); raise AssertionError("place() must apply the 6-hour filter")
except live.ExchangeError as e: assert "order blocked: 6-hour filter" in str(e), e
t="KXRAINGB-26OCT15-T0"; pid=tr(t,side="no",price=0.60,mid=0.40,fc=0.55,slices=[30]*24)
try: live.place(live.client()[0],live.ldb(),"demo",pid,t,"no",1,60,note="x"); raise AssertionError("place() must apply the no-rain filter")
except live.ExchangeError as e: assert "order blocked: no-rain filter" in str(e), e
assert len(F.posts())==n0
# without the decision ledger (an old paper.db), the scan's log gives the mid and the hours, and the trade its price
import sqlite3
old=os.path.join(OUT,"old_paper.db"); o=sqlite3.connect(old)
o.execute("create table obs(ticker text,version text,mid real,slices text)"); o.execute("create table trades(id integer primary key,ticker text,side text,price real)")
o.execute("insert into obs values('KXRAINH1-26OCT15-T0','v3',0.30,?)",(json.dumps([0]*12+[50]+[0]*11),)); o.execute("insert into trades values(1,'KXRAINH1-26OCT15-T0','yes',0.31)")
o.execute("insert into trades values(2,'KXRAINH2-26OCT15-T0','yes',0.31)"); o.commit(); o.close()
real_paper=live.PAPER; live.PAPER=old
assert live.trade_inputs("KXRAINH1-26OCT15-T0","yes",1)==(0.30,0.31,json.dumps([0]*12+[50]+[0]*11)) and live.agree_reason("KXRAINH1-26OCT15-T0","yes",1) is None
assert live.trade_inputs("KXRAINH1-26OCT15-T0","no",1) is None and live.trade_inputs("KXRAINH2-26OCT15-T0","yes",2) is None   # wrong side; no log row
assert live.trade_inputs("KXRAINH1-26OCT15-T0","yes",None) is None and "could not be read" in live.agree_reason("KXRAINH1-26OCT15-T0","maybe",1)
live.PAPER=real_paper
# the switch: with AGREE_6H off, the same skipped trade would be copied (only the user can change it)
real_agree=live.agree_reason; live.agree_reason=lambda *a: (_ for _ in ()).throw(RecursionError("deep"))
assert "could not be checked (RecursionError)" in live.filter_reason("KXRAING1-26OCT15-T0","yes",ids["KXRAING1-26OCT15-T0"]); live.agree_reason=real_agree
live.AGREE_6H=False; assert live.filter_reason("KXRAING2-26OCT15-T0","yes",ids["KXRAING2-26OCT15-T0"]) is None; live.AGREE_6H=True
assert live.filter_reason("KXRAING2-26OCT15-T0","yes",ids["KXRAING2-26OCT15-T0"])
out,_=run(live.status); assert "Filter: a paper bet is copied only if v3's hours in 6-hour blocks also give the bot's 8-point edge on the same side, within its 30-point veto" in out and "End rule:" in out, out
live.AGREE_6H=False   # as shipped: the same trade is copied, and status says the check is off
assert live.filter_reason("KXRAING2-26OCT15-T0","yes",ids["KXRAING2-26OCT15-T0"]) is None
out,_=run(live.status); assert "the 6-hour check is off" in out and "6-hour blocks also give" not in out, out
assert "End rule: on real money, a 25% drawdown" in out and "%%" not in out, out   # no unformatted percent signs
t="KXRAINGZ-26OCT15-T0"; tr(t,side="no",price=0.60,mid=0.40,fc=0.30,slices=[30]*24); out,_=run(live.mirror); assert row(t)[5]=="executed", out
print("6-hour filter ok")

# 9. daily loss stop ($2.50) and drawdown pause
L=live.ldb(); L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(),"demo","X1","yes",1,50,"executed",1,3,0,"no",-3.0,time.time())); L.commit()
t="KXRAINJAX-26OCT15-T0"; new(t); n0=len(F.posts()); out,_=run(live.mirror); assert "daily loss stop" in out and len(F.posts())==n0, out
L.execute("update orders set settled_ts=? where ticker='X1'",(time.time()-3*86400,)); L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"demo","X2","yes",1,50,"executed",1,4,0,"no",-4.0,time.time()-2*86400)); L.commit()
v,p,paused=live.value_track(L,"demo"); assert paused and p>=25, (v,p)
out,_=run(live.mirror); assert "drawdown pause" in out and "TRIAL ENDED" not in out and "ends the real-money trial" not in out, out
assert L.execute("select count(*) from events where kind in ('trial_end','lock')").fetchone()[0]==0, "a demo drawdown never locks real money"
live.event(L,"demo","resume"); assert not live.value_track(L,"demo")[2]
out,_=run(live.mirror); assert row(t)[5]=="executed", out
print("stops ok")

# 10. KILL file
t="KXRAINMCI-26OCT15-T0"; new(t); open("KILL","w").close(); n0=len(F.posts())
out,_=run(live.mirror); assert "KILL" in out and len(F.posts())==n0; os.remove("KILL")
# KILL.txt in the tradebot folder stops orders even when started from another folder; place() refuses on its own
home=os.path.join(OUT,"kill_home"); os.makedirs(home,exist_ok=True); real_here=core.HERE; core.HERE=home; os.chdir(os.path.join(OUT,"keys"))
open(os.path.join(home,"KILL.txt"),"w").close()
out,_=run(live.mirror); assert "KILL" in out and len(F.posts())==n0, out
td="KXRAINDSM-26OCT15-T0"; pid=new(td)
try: live.place(live.client()[0],live.ldb(),"demo",pid,td,"yes",1,42,note="x"); raise AssertionError("place() must refuse while the kill switch is on")
except live.ExchangeError as e: assert "KILL" in str(e), e
out,code=run(live.demo_order); assert code and len(F.posts())==n0, (out,code)
os.remove(os.path.join(home,"KILL.txt")); core.HERE=real_here; os.chdir(OUT)
# a kill file created while mirror is running stops the orders after it
t1="KXRAINBUF-26OCT15-T0"; t2="KXRAINALB-26OCT15-T0"; new(t1); new(t2); n0=len(F.posts()); orig=F.request
def hook(method,*a,**kw):
    r=orig(method,*a,**kw)
    if method=="POST": open("KILL","w").close()
    return r
F.request=hook
out,_=run(live.mirror); del F.request; os.remove("KILL")
assert len(F.posts())==n0+1 and "KILL file appeared" in out, out
print("kill ok")

# 11. real money: locked before the stop date, locked without an unlock, unlock needs a person, lock works again,
#     and restoring an old live.db cannot undo a later lock
settings("prod"); real_today=live.today; F.calls.clear()
live.today=lambda: date(2026,11,10); out,_=run(live.mirror); assert "locked until 2026-11-11" in out and not F.calls, out
live.today=lambda: date(2026,11,11); out,_=run(live.mirror); assert "run .\\run live unlock" in out and not F.calls, out
real_inter=live.interactive; live.interactive=lambda: False; out,code=run(live.unlock); assert code and "typed by you" in str(code), code
live.today=lambda: date(2026,11,10); live.interactive=lambda: True; out,code=run(live.unlock); assert code and "locked until" in str(code), code
live.today=lambda: date(2026,11,11)
import builtins; answers=iter(["wrong"]); builtins.input=lambda prompt="": next(answers)
out,code=run(live.unlock); assert code and "Not unlocked" in str(code) and "GATE" in out, (out,code)
answers=iter(["UNLOCK REAL MONEY"]); out,code=run(live.unlock); assert not code and "Unlocked" in out and "did NOT pass" in out, (out,code)
assert json.load(open(live.SETTINGS)).get("prod_unlock")
out,_=run(live.mirror); assert not F.posts() and "no new paper rain trades" in out, out   # trades from before the unlock are not copied
t="KXRAINSLC-26OCT15-T0"; new(t,age=0); out,_=run(live.mirror)
P=F.posts(); assert len(P)==1 and P[0][5]=="api.elections.kalshi.com" and P[0][3]["client_order_id"].split("-")[1]=="prod", out
run(live.lock); t="KXRAINOKC-26OCT15-T0"; new(t,age=0); out,_=run(live.mirror); assert len(F.posts())==1 and "unlock" in out, out
live.ldb().execute("delete from events where kind='lock'").connection.commit()   # as if an old live.db (before the lock) were restored
out,_=run(live.mirror); assert len(F.posts())==1 and "locked" in out, out
try: live.place(live.client()[0],live.ldb(),"prod",None,t,"yes",1,42,note="x"); raise AssertionError("place() must re-check the lock")
except live.ExchangeError as e: assert "locked" in str(e)
live.today=real_today
print("real-money locks ok")

# 11b. the user's end rule (2026-11-07): on real money the 25% drawdown ends the trial: real money locks again (once per
#      pause), restarting needs both typed commands (resume and unlock); a failed lock still leaves the pause in charge
live.today=lambda: date(2026,11,11); L=live.ldb()
F.pos.clear(); F.extra=0.0   # room under the $25 cap: the shared fake holds every earlier section's positions
def ends(): return L.execute("select count(*) from events where env='prod' and kind='trial_end'").fetchone()[0]
answers=iter(["UNLOCK REAL MONEY"]); out,code=run(live.unlock); assert not code and "Unlocked" in out and "trial ENDED" not in out and "a 25% drawdown ends the trial" in out, (out,code)
L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"prod","X3","yes",1,50,"executed",1,7,0,"no",-7.0,time.time()-2*86400)); L.commit()   # value $18 < 75% of $25
assert live.value_track(L,"prod")[2] and live.unlocked(L) and ends()==0
t="KXRAINEND1-26OCT15-T0"; new(t,age=0); n0=len(F.posts())
real_save=live.save_settings; live.save_settings=lambda s: (_ for _ in ()).throw(PermissionError("denied"))
real_event=live.event; live.event=lambda *a,**k: (_ for _ in ()).throw(live.sqlite3.OperationalError("disk I/O error"))
out,_=run(live.mirror); live.event=real_event   # neither lock could be written: the pause still stops it; tried again next run
assert "WARNING: could not lock real money" in out and "drawdown pause" in out and len(F.posts())==n0 and ends()==0, out
out,_=run(live.mirror); live.save_settings=real_save   # only the settings file fails: live.db's lock alone holds (review)
assert "REAL-MONEY TRIAL ENDED" in out and "could not write the settings file (PermissionError)" in out and "run .\\run live lock to clear" in out and len(F.posts())==n0 and ends()==1, out
assert json.load(open(live.SETTINGS)).get("prod_unlock") and not live.unlocked(L)
run(live.lock); assert json.load(open(live.SETTINGS)).get("prod_unlock") is None
out,_=run(live.mirror); assert "TRIAL ENDED" not in out and ends()==1 and len(F.posts())==n0, out   # once per pause
out,_=run(live.status); assert "Real-money trial: ENDED" in out and "ends the real-money trial" in out, out
# unlocking again alone is not enough: the pause stays until resume, and it does not lock a second time
answers=iter(["UNLOCK REAL MONEY"]); out,code=run(live.unlock); assert not code and "trial ENDED at the 25% drawdown" in out, (out,code)
out,_=run(live.mirror); assert "trial ended at the 25% drawdown" in out and "resume" in out and len(F.posts())==n0 and ends()==1 and live.unlocked(L), out
# open bets that settle as wins can lift the pause by itself: real money stays locked until resume (review MUST 1)
L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"prod","X5","yes",1,50,"executed",1,1,0,"yes",2.0,time.time())); L.commit()
assert not live.value_track(L,"prod")[2] and live.unlocked(L)
t="KXRAINEND0-26OCT15-T0"; new(t,age=0,n=1); out,_=run(live.mirror); assert "trial ended" in out and len(F.posts())==n0, out
try: live.place(live.client()[0],live.ldb(),"prod",None,t,"yes",1,42,note="x"); raise AssertionError("place() must refuse after the trial ended")
except live.ExchangeError as e: assert "trial ended" in str(e), e
answers=iter(["RESUME"]); out,code=run(live.resume); assert not code and "Resumed on prod" in out and "still locked" not in out, (out,code)
t="KXRAINEND2-26OCT15-T0"; new(t,age=0,n=1); out,_=run(live.mirror)   # END0 too: it was opened after the unlock
assert len(F.posts())==n0+2 and F.posts()[-1][5]=="api.elections.kalshi.com" and row(t)[12]=="prod" and row("KXRAINEND0-26OCT15-T0")[5]=="executed", out   # both typed: orders again
# a later drawdown found by sync ends it again; resume alone then says real money is still locked
L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"prod","X4","yes",1,50,"executed",1,6,0,"no",-6.0,time.time())); L.commit()
out,_=run(live.sync); assert "REAL-MONEY TRIAL ENDED" in out and ends()==2 and not live.unlocked(L), out
answers=iter(["RESUME"]); out,code=run(live.resume); assert not code and "Real money is still locked" in out, (out,code)
t="KXRAINEND3-26OCT15-T0"; new(t,age=0); out,_=run(live.mirror); assert len(F.posts())==n0+2 and "locked" in out, out
L.execute("update orders set settled_ts=? where env='prod' and ticker in ('X4','X5')",(time.time()-2*86400,)); L.commit()   # out of the daily loss stop's 24 hours
answers=iter(["UNLOCK REAL MONEY"]); out,code=run(live.unlock); assert not code and "trial ENDED" not in out, (out,code)   # resume, then unlock: orders again
F.pos.clear(); F.extra=0.0   # room under the $25 cap (the shared fake holds every earlier section's positions)
t="KXRAINEND4-26OCT15-T0"; new(t,age=0,n=1); out,_=run(live.mirror); assert len(F.posts())==n0+3 and row(t)[12]=="prod", out
# the lock event written but its trial_end record not: locked, said plainly, and the next run records it
L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"prod","X6","yes",1,50,"executed",1,8,0,"no",-8.0,time.time())); L.commit()
def only_trial_end(c_,env_,kind,detail=""):
    if kind=="trial_end": raise live.sqlite3.OperationalError("disk full")
    return real_event(c_,env_,kind,detail)
live.event=only_trial_end; out,_=run(live.mirror); live.event=real_event
assert "TRIAL ENDED" in out and "trial_end record" in out and ends()==2 and not live.unlocked(L) and len(F.posts())==n0+3, out
out,_=run(live.mirror); assert "TRIAL ENDED" in out and ends()==3, out
# resume runs the end rule first: a drawdown whose locks could not be written still ends the trial before the resume
answers=iter(["RESUME"]); out,code=run(live.resume); assert not code and "Real money is still locked" in out, (out,code)
answers=iter(["UNLOCK REAL MONEY"]); run(live.unlock); assert live.unlocked(L)
L.execute("insert into orders(ts,env,ticker,side,count,limit_cents,status,fill_count,cost,fees,result,pnl,settled_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (time.time(),"prod","X7","yes",1,50,"executed",1,9,0,"no",-9.0,time.time())); L.commit()
live.save_settings=lambda s: (_ for _ in ()).throw(PermissionError("denied")); live.event=lambda *a,**k: (_ for _ in ()).throw(live.sqlite3.OperationalError("disk I/O error"))
out,_=run(live.mirror); live.save_settings=real_save; live.event=real_event; assert "WARNING: could not lock" in out and ends()==3, out
answers=iter(["RESUME"]); out,code=run(live.resume)
assert not code and out.index("REAL-MONEY TRIAL ENDED")<out.index("Resumed on prod") and "still locked" in out and ends()==4 and not live.unlocked(L), (out,code)
run(live.lock); live.today=real_today
print("end rule ok")

# 12. demo test order refuses on prod, works on demo; use; setup never echoes a pasted key; status; piped unlock refused
F.pos.clear(); F.extra=0.0   # room under the $25 cap: the earlier sections' fake positions are not this section's subject (review)
out,code=run(live.demo_order); assert code and "only on the demo" in str(code)
out,code=run(live.use,"nope"); assert code
out,code=run(live.use,"demo"); assert not code and json.load(open(live.SETTINGS))["env"]=="demo"
F.calls.clear(); out,code=run(live.demo_order); assert not code and len(F.posts())==1 and F.posts()[0][3]["count"]=="1.00" and F.posts()[0][3]["client_order_id"].startswith("tb-demo-x-") and "as expected" in out, (out,code)
F.markets["KXRAINZZZ-26OCT15-T0"]=mk("KXRAINZZZ-26OCT15-T0",bid=0.30,ask=0.33)
out,code=run(live.demo_order,"KXRAINZZZ-26OCT15-T0","no")   # "no" counts wherever it is typed
assert not code and F.posts()[-1][3]["side"]=="ask" and F.posts()[-1][3]["price"]=="0.3000" and "position -1" in out and "as expected" in out, (out,code)
n0=len(F.posts())   # a named market the account already holds (or the bot copied) is refused: a NO test there would sell YES
for args in (("no","KXRAINZZZ-26OCT15-T0"),("no","KXRAINLIT-26OCT15-T0")):
    out,code=run(live.demo_order,*args); assert code and "No order on" in str(code) and len(F.posts())==n0, (args,code)
key_lines=ED_TEXT.strip().splitlines()
# from PowerShell ISE on Windows (not a terminal), setup opens its own console window instead of failing
opened=[]; real_popen=live.subprocess.Popen; live.subprocess.Popen=lambda args,**kw: opened.append((args,kw))
live.windows=lambda: True; live.interactive=lambda: False
out,code=run(live.setup); assert not code and "new black window" in out and opened and opened[0][0][-2:]==["setup","--window"] and opened[0][1]["creationflags"]==0x10, (out,opened)
out,code=run(live.unlock); assert code and len(opened)==1, "unlock must never open a window by itself"
live.subprocess.Popen=real_popen; live.windows=lambda: False; live.interactive=lambda: True
answers=iter(["demo","-----BEGIN PRIVATE KEY-----"]); out,code=run(live.setup); assert code and "not a Key ID" in str(code) and "BEGIN" not in out+str(code), (out,code)
answers=iter(["demo","a952bcbe-ec3b-4b5b-b8f9-11dae589608c"]+key_lines[1:3]+[ED_FILE])
F.pub["a952bcbe-ec3b-4b5b-b8f9-11dae589608c"]=ed.public_key()
out,code=run(live.setup); assert not code and "Connected to Kalshi demo" in out, (out,code)
assert not any(l in out for l in key_lines[1:3]) and "looks like the key itself" in out, out
s=json.load(open(live.SETTINGS)); assert s["keys"]["demo"]["key_id"].startswith("a952") and s["env"]=="demo"
# pressing Enter finds the key even with Windows' hidden double ending, or as the only key file in the folder
kd=live.KDIR; os.makedirs(kd,exist_ok=True); d=os.path.join(kd,"kalshi-demo-key.txt")
open(d+".txt","w").write(ED_TEXT); assert live.find_key_file(d,"demo")==d+".txt"; os.remove(d+".txt")
open(os.path.join(kd,"My Kalshi key.txt"),"w").write(ED_TEXT); open(os.path.join(kd,"kalshi-prod-key.txt"),"w").write("x")
assert live.find_key_file(d,"demo")==os.path.join(kd,"My Kalshi key.txt")
answers=iter(["demo","a952bcbe-ec3b-4b5b-b8f9-11dae589608c","",""]); out,code=run(live.setup)   # Enter, then "yes, that is my key"
assert not code and "Connected to Kalshi demo" in out and json.load(open(live.SETTINGS))["keys"]["demo"]["key_file"].endswith("My Kalshi key.txt"), (out,code)
answers=iter(["demo","a952bcbe-ec3b-4b5b-b8f9-11dae589608c","","n",ED_FILE]); out,code=run(live.setup)   # "no, not that one": drag the right file
assert not code and json.load(open(live.SETTINGS))["keys"]["demo"]["key_file"]==ED_FILE, (out,code)
os.remove(os.path.join(kd,"kalshi-prod-key.txt"))
# a key Kalshi does not accept is never saved
before=open(live.SETTINGS).read()
answers=iter(["demo","b952bcbe-ec3b-4b5b-b8f9-11dae589608c",ED_FILE]); out,code=run(live.setup)
assert code and "did not accept" in str(code) and open(live.SETTINGS).read()==before, (out,code)
# connecting the real account keeps the demo copy running when asked (and orders stay locked)
F.pub["c952bcbe-ec3b-4b5b-b8f9-11dae589608c"]=rs.public_key()
answers=iter(["prod","c952bcbe-ec3b-4b5b-b8f9-11dae589608c",RS_FILE,""]); out,code=run(live.setup)
s=json.load(open(live.SETTINGS)); assert not code and "Connected to Kalshi prod (real money)" in out and s["env"]=="demo" and s["keys"]["prod"]["key_id"].startswith("c952") and "keeps copying to the demo" in out, (out,code)
# the --window wrapper keeps the exit code (a refused unlock is still a failure)
live.interactive=lambda: False; answers=iter([""]); out,code=run(live.main,["unlock","--window"]); assert code==1, (out,code)
live.interactive=lambda: True
live.interactive=real_inter
out,code=run(live.status); assert not code and "Exchange: demo" in out and "Paper gate" in out and "a952..." in out and "a952bcbe-ec3b" not in out, out
out,code=run(live.test_connection); assert not code and "Connected to Kalshi demo" in out, out
nunl=live.ldb().execute("select count(*) from events where kind='unlock'").fetchone()[0]
env=dict(os.environ,PYTHONPATH=WORK,KALSHI_ENV="prod")
r=subprocess.run([sys.executable,os.path.join(WORK,"live.py"),"unlock"],input="UNLOCK REAL MONEY\n",capture_output=True,text=True,env=env)
assert r.returncode!=0 and live.ldb().execute("select count(*) from events where kind='unlock'").fetchone()[0]==nunl, r.stdout+r.stderr
# the same with the date set to Nov 11, so the refusal comes from the piped (non-terminal) input itself
wrap=os.path.join(OUT,"unlock_nov11.py"); open(wrap,"w").write("import sys,datetime\nsys.path.insert(0,%r)\nimport live\nlive.today=lambda: datetime.date(2026,11,11)\nlive.main(['unlock'])\n"%WORK)
r=subprocess.run([sys.executable,wrap],input="UNLOCK REAL MONEY\n",capture_output=True,text=True,env=env)
assert r.returncode!=0 and "typed by you" in r.stderr and live.ldb().execute("select count(*) from events where kind='unlock'").fetchone()[0]==nunl, r.stdout+r.stderr
# lock works from the settings file alone, even when live.db cannot be written
s=json.load(open(live.SETTINGS)); s["prod_unlock"]=123.0; json.dump(s,open(live.SETTINGS,"w"))
real_ldb=live.ldb; live.ldb=lambda: (_ for _ in ()).throw(live.sqlite3.OperationalError("disk I/O error"))
out,code=run(live.lock); live.ldb=real_ldb
assert not code and json.load(open(live.SETTINGS))["prod_unlock"] is None and "could not record" in out, (out,code)
print("commands ok")

# 13. backups include live.db, inside and outside the folder; a live.db problem never stops the paper backup (exit 3);
#     the dashboard shows the account tile
env=dict(os.environ,PYTHONPATH=WORK)
r=subprocess.run([sys.executable,os.path.join(WORK,"backup.py"),"livetest"],capture_output=True,text=True,env=env); assert r.returncode==0, r.stdout+r.stderr
for d in ("backups",os.environ["TRADEBOT_OFFSITE_BACKUPS"]): assert any(f.startswith("live_") and "livetest" in f for f in os.listdir(d)), d
r=subprocess.run([sys.executable,os.path.join(WORK,"backup.py"),"badlive"],capture_output=True,text=True,env=dict(env,LIVE_DB=os.path.join(OUT,"keys")))
assert r.returncode==3 and any("badlive" in f and f.startswith("paper_") for f in os.listdir("backups")), r.stdout+r.stderr
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,env=env,encoding="utf-8",errors="replace"); assert r.returncode==0, r.stderr
html=open("dashboard.html",encoding="utf-8").read(); assert "Kalshi account" in html and "Demo:" in html and "Real:" in html, "account tile"

# run() checked after every command that paper.db did not change; the fake checked every request's headers and signature
assert all(r[12] in ("demo","prod") for r in rows())
print("live.py: all checks passed")
