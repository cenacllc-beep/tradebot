"""Shadow tests: paper research only. They never count toward the gate and never write to the trades or obs tables.
1. Price moves: for every market the v3 scan logged, the market's mid price when its Kalshi day began
   (close_time - 24h) against the mid when we scanned. If prices drift toward the forecast after the scan, the
   forecast knew something the price did not yet; if they drift away, the market knew more. Uses Kalshi's public
   minute candlesticks (GET /markets/candlesticks), read once per market after its day has started.
2. Limit orders ("maker"): the same v3 forecasts, 50/50 blend, 8-point edge, quarter Kelly, 6% per trade, 15% open
   cap and 10% daily stop, but on a separate hypothetical $25 ledger and entering with a resting limit order instead
   of paying the ask: 1 cent better than the best bid when the spread allows, otherwise joining the best bid.
   The order is cancelled when the market's day starts. It counts as filled only if Kalshi's minute candles show a
   trade or an offer reaching our price in a whole minute after the order was placed (strictly through our price
   when we only joined the queue, because others were ahead of us). Maker fee = 0: Kalshi's fee schedule charges
   makers only on listed markets, and weather markets are not listed.
4. Station forecast (v4 candidate, see stationfc.py): each scan logs a calibrated NBM station forecast for every open
   rain market (one Iowa Environmental Mesonet request per station), so it can be scored against the market and v3.
3. Rules watch: each scan compares every weather market's settlement rules with what the estimators assume (the
   station named in the rules) and with the wording seen before, and records a warning when either changes.
Usage: python shadow.py scan | settle | report. run.bat runs it right after main.py; a failure here never stops the
backups or the dashboard. Its two tables are created on first use, after a backup of paper.db. Python 3.8+."""
import sys, os, re, math, time, subprocess
from datetime import datetime, timezone
import requests
from config import *
import core, kalshi, audit

VERSION="v3"        # forecasts are read from the v3 rows in obs (rain and temperature, the same markets the main bot sees)
STRATEGY="maker"
TABLES={"shadow_orders":"create table shadow_orders(id integer primary key,ts real,ticker text,strategy text,version text,"
            "side text,price real,fair real,fc real,bid real,ask real,improved integer,n integer,cost real,fee real,"
            "cancel_ts real,status text default 'pending',fill_ts real,result text,pnl real,settle_ts real)",
        "shadow_moves":"create table shadow_moves(ticker text,version text,scan_ts real,fc real,mid_scan real,start_ts real,"
            "bid_start real,ask_start real,mid_start real,status text,primary key(ticker,version))",
        "rules_watch":"create table rules_watch(series text,key text,value text,first_seen real,last_seen real,primary key(series,key))",
        "rules_alerts":"create table rules_alerts(ts real,series text,key text,old text,new text,note text)",
        "v4_obs":"create table v4_obs(ticker text primary key,ts real,station text,run text,R real,q real,fc real,mid real,bid real,ask real,result text,start_ts real,paper_done integer default 0)",
        "v4_paper":"create table v4_paper(ticker text,kind text,side text,price real,improved integer,filled integer,result text,pnl real,primary key(ticker,kind))"}
# shadow_orders.status: pending (resting) -> filled -> settled, or pending -> unfilled (cancelled at the day start)
# shadow_moves.status: ok | wide (spread above MAX_SPREAD at the day start, mid not used) | no_data

def has_tables(c,names=("shadow_orders","shadow_moves")): return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}>=set(names)
def tables(c):
    have={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    need=[k for k in TABLES if k not in have]
    if not need: return
    here=os.path.dirname(os.path.abspath(__file__))   # back up paper.db before adding tables (CLAUDE.md: back up before migrations)
    if subprocess.run([sys.executable,os.path.join(here,"backup.py"),"preshadow"]).returncode not in (0,3):   # 3 = only live.db failed
        raise SystemExit("shadow: the backup failed, so the shadow tables were not created")
    for k in need: c.execute(TABLES[k])
    c.commit(); print("shadow: added tables %s to %s"%(", ".join(need),DB))
def _t(s): return datetime.strptime(s,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
def _f(d,k):
    v=(d or {}).get(k)
    try: return None if v in (None,"") else float(v)
    except (TypeError,ValueError): return None
def _state(c):
    pnl=c.execute("select coalesce(sum(pnl),0) from shadow_orders where status='settled'").fetchone()[0]
    opn=c.execute("select coalesce(sum(cost+fee),0) from shadow_orders where status in ('pending','filled')").fetchone()[0]
    lost=c.execute("select coalesce(sum(pnl),0) from shadow_orders where status='settled' and settle_ts>=?",(time.time()-86400,)).fetchone()[0]
    return BANKROLL+pnl-opn,opn,lost      # resting orders reserve cash and count toward the cap, like real ones would

def _after_stop_allowed(c):
    """The main bot's rule (strategy.py, pre-committed 2026-10-28): market days from the stop date on only after the gate's
    stored single look passed. Read only here (the main scan, which runs first, stores the look). Any error: no."""
    try:
        import strategy
        return strategy._after_stop_allowed(c,record=False)
    except Exception as ex:
        print("shadow maker: the gate look could not be read (%s): no orders for market days from the stop date on"%ex); return False
def _before_stop(t):
    try:
        import strategy
        return strategy.before_stop(t)
    except Exception: return False   # fail closed: treated as a market day from the stop date on
def scan(c):
    if core.killed(): return print("shadow: KILL file present: halted")
    tables(c)
    mk=kalshi.markets()
    rules_check(c,mk)
    try: v4_log(c,mk)
    except Exception as ex: print("v4 station forecast skipped (the main bot is not affected): %r"%ex)
    cash,opn,lost=_state(c)
    if lost<=-DAILY_LOSS_LIMIT*BANKROLL: return print("shadow maker: daily loss limit hit, no new orders")
    after=_after_stop_allowed(c)   # mirrors the main bot: market days from the stop date on only after a passed gate look
    fc={t:p for t,p in c.execute("select ticker,fc from obs where version=? and fc is not null",(VERSION,))}
    done={r[0] for r in c.execute("select ticker from shadow_orders where strategy=?",(STRATEGY,))}
    k=seen=0
    sid=None; stats={}
    if audit.ensure(c):   # decision audit ledger (2026-10-22): every rain market this ledger evaluates, with its reason
        try: sid=audit.start_scan(c,"shadow_maker",dict(STRATEGY=STRATEGY,VERSION=VERSION,MIN_EDGE=MIN_EDGE,MAX_SPREAD=MAX_SPREAD,BLEND=BLEND))
        except Exception as ex: print("shadow: audit scan record failed (%s); no limit orders this scan"%ex)
    R=audit.Recorder(c,sid,"maker_spread.rain.v3",VERSION,VERSION,"paper",stats)
    for m in mk:
        t=m.get("ticker","")
        if t not in fc or t in done: continue
        if not t.startswith("KXRAIN"): continue                # mirrors the main bot: rain only since 2026-10-14
        try: w0=_t(m["close_time"])-86400
        except (KeyError,TypeError,ValueError): R.abstain(m,"CLOSE_TIME_UNREADABLE",market_type="rain",p_model=fc[t]); continue
        now=time.time()
        if now>=w0: R.abstain(m,"MARKET_STARTED",market_type="rain",p_model=fc[t],close_ts=w0+86400,day_start_ts=w0); continue   # same rule as the main bot: only before the day starts
        bid,ask=kalshi.quote(m)
        if bid is None or ask is None or not 0<ask<1 or ask-bid>MAX_SPREAD:
            R.abstain(m,"WIDE_SPREAD" if (bid is not None and ask is not None and 0<ask<1) else "NO_QUOTE",market_type="rain",p_model=fc[t],bid=bid,ask=ask,close_ts=w0+86400,day_start_ts=w0); continue
        seen+=1
        mid=(bid+ask)/2; fair=BLEND*fc[t]+(1-BLEND)*mid
        yb=round(bid+0.01,2); iy=yb<round(ask,2)              # YES: bid 1c above the best bid if that stays below the ask
        ya=round(ask-0.01,2); ino=ya>round(bid,2)             # NO: a NO bid is a YES offer; offer 1c under the best ask
        opts=[("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)]
        side,price,q,imp=max(opts,key=lambda x:x[2]-x[1])
        ctx=dict(market_type="rain",p_model=fc[t],p_fair=fair,p_win=q,price=price,bid=bid,ask=ask,close_ts=w0+86400,day_start_ts=w0,detail=dict(improved=bool(imp),order="limit"))
        if q-price<MIN_EDGE: R.abstain(m,"INSUFFICIENT_EDGE",side=side,**ctx); continue
        if not after and not _before_stop(t): R.abstain(m,"GATE_NOT_PASSED",side=side,**ctx); continue
        if not 0<price<1: R.abstain(m,"LIMIT_PRICE_INVALID",side=side,**ctx); continue
        n=int(core.kelly_stake(q,price,cash)//price)
        if n<1: R.abstain(m,"SIZE_BELOW_ONE",side=side,**ctx); continue
        cost=n*price; f=0.0
        if cost+f>cash: R.abstain(m,"CASH_LIMIT",side=side,n=n,cost=cost,fee=f,**ctx); continue
        if opn+cost+f>BANKROLL*MAX_OPEN_PCT: R.abstain(m,"EXPOSURE_CAP",side=side,n=n,cost=cost,fee=f,**ctx); continue   # this ledger's own 15% cap
        c.execute("savepoint shadow_order")   # the order and its decision row together, or neither (fail closed)
        try:
            cur=c.execute("insert into shadow_orders(ts,ticker,strategy,version,side,price,fair,fc,bid,ask,improved,n,cost,fee,cancel_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (now,t,STRATEGY,VERSION,side,price,q,fc[t],bid,ask,int(imp),n,cost,f,w0))
            R.trade(m,side,n=n,cost=cost,fee=f,trade_ref="shadow_orders:%d"%cur.lastrowid,**ctx)
            c.execute("release shadow_order")
        except Exception as ex:
            c.execute("rollback to shadow_order"); c.execute("release shadow_order"); print("shadow maker: %s not placed: its decision could not be recorded (%s)"%(t,ex)); continue
        cash-=cost+f; opn+=cost+f; k+=1
        print("SHADOW maker %s %s x%d limit @%.2f (%s) fair=%.2f, cancelled at %s"%(side,t,n,price,
              "1c better than the best bid" if imp else "joins the best bid",q,datetime.fromtimestamp(w0).strftime("%b %d %H:%M")))
    try: audit.end_scan(c,sid,dict(checked=seen,orders=k,reasons=stats))
    except Exception as ex: print("shadow: audit scan end not recorded (%s)"%ex)
    c.commit(); print("shadow maker: %d markets checked, %d limit orders placed (separate paper ledger, not in gate)"%(seen,k))

def _template(m):
    t=(m.get("rules_primary") or "")+" || "+(m.get("rules_secondary") or "")
    for x in {m.get("yes_sub_title"),m.get("no_sub_title")}:
        if x: t=t.replace(x,"<CITY>")
    t=re.sub(r"\bCLI[A-Z]{3}\b","<STATION>",t); t=re.sub(r"\b[A-Z][a-z]{2} \d{1,2}, \d{4}\b","<DATE>",t)
    return re.sub(r"\s+"," ",re.sub(r"\d+(\.\d+)?","<N>",t)).strip()
def rules_check(c,markets):
    """Warn when a market settles on a different station than the estimator uses, or when a series' rules wording changes."""
    import weather
    now=time.time(); seen={}; tm={}; alerts=[]
    for m in markets:
        p=(m.get("ticker") or "").split("-")
        if len(p)<3: continue
        s=p[0]; st=re.search(r"\b(CLI[A-Z]{3})\b",m.get("rules_primary") or ""); st=st.group(1) if st else None
        if s=="KXRAIN": city=p[2]; want=weather.RAIN.get(city,(None,))[0]
        elif s.startswith("KXHIGH"): city=weather.SERIES_CITY.get(s,s[6:]); want=weather.TEMP_STATION.get(city)
        else: continue
        tm.setdefault((s,"wording:"+(m.get("strike_type") or "")),set()).add(_template(m))
        if st: seen[(s,"station:"+city)]=st
        if want and st and st!=want: alerts.append((s,"station:"+city,want,st,"the estimator uses %s but the market settles on %s"%(want,st)))
    seen.update({k:"\n".join(sorted(v)) for k,v in tm.items()})
    for (s,k),v in seen.items():
        old=c.execute("select value from rules_watch where series=? and key=?",(s,k)).fetchone()
        if old is None: c.execute("insert into rules_watch values(?,?,?,?,?)",(s,k,v,now,now))
        elif old[0]!=v:
            alerts.append((s,k,old[0],v,"settlement rules changed"))
            c.execute("update rules_watch set value=?,last_seen=? where series=? and key=?",(v,now,s,k))
        else: c.execute("update rules_watch set last_seen=? where series=? and key=?",(now,s,k))
    for a in alerts:
        if not c.execute("select 1 from rules_alerts where series=? and key=? and new=? and ts>=?",(a[0],a[1],a[3],now-6*86400)).fetchone():
            c.execute("insert into rules_alerts values(?,?,?,?,?,?)",(now,)+a)
        print("RULES WARNING %s %s: %s"%(a[0],a[1],a[4]))
    c.commit()
    if not alerts: print("rules watch: %d markets checked, no changes"%len(markets))
    return alerts
def v4_log(c,mk):
    """Log the v4 candidate (stationfc.py) for every open rain market whose day has not started. Research only."""
    import stationfc
    from datetime import timedelta
    coef=stationfc.load_coef()
    if not coef: return print("v4 station forecast: no fitted model yet (research/backtest.py writes it)")
    have={r[0] for r in c.execute("select ticker from v4_obs")}; now=time.time(); n=0; cache={}
    for m in mk:
        t=m.get("ticker") or ""; p=t.split("-")
        if not t.startswith("KXRAIN-") or t in have or len(p)<3: continue
        try: w0=_t(m["close_time"])-86400; day=datetime.strptime(p[1],"%y%b%d").date()
        except (KeyError,TypeError,ValueError): continue
        if now>=w0: continue
        s=re.search(r"\bat CLI([A-Z]{3})\b",m.get("rules_primary") or ""); bid,ask=kalshi.quote(m)
        if not s or bid is None or ask is None or not 0<=bid<ask<=1: continue
        k=("K"+s.group(1),day)
        if k not in cache:
            try: cache[k]=stationfc.evening_run(k[0],day-timedelta(days=1)); time.sleep(3)
            except Exception as ex: print("v4: forecast lookup failed for",k[0],ex); cache[k]=None
        f=stationfc.features(cache[k][0],day) if cache[k] else None
        if not f: continue
        c.execute("insert into v4_obs(ticker,ts,station,run,R,q,fc,mid,bid,ask,start_ts) values(?,?,?,?,?,?,?,?,?,?,?)",(t,now,k[0],cache[k][1],f["R"],f["q"],stationfc.predict(coef,f),(bid+ask)/2,bid,ask,w0)); n+=1
    c.commit(); print("v4 station forecast: %d rain markets logged (research only, not in gate)"%n)
def _markets(ts):
    out={}
    for i in range(0,len(ts),50):
        part=ts[i:i+50]
        try:
            r=requests.get(f"{KALSHI_BASE}/markets",params={"tickers":",".join(part),"limit":100},headers=kalshi.UA,timeout=30); r.raise_for_status()
            out.update({m["ticker"]:m for m in r.json().get("markets",[]) if m.get("ticker")})
        except Exception as ex: print("shadow: market lookup failed:",ex)
    for t in ts:
        if t not in out:
            try: out[t]=kalshi.get(t)
            except Exception as ex: print("shadow: lookup failed for",t,ex)
    return out
def _candles(ts,start,end,size=20):
    """{ticker: minute candles sorted by end time}, starting with Kalshi's latest candle before `start`.
    Network errors propagate, so the caller leaves things as they are and retries on the next run."""
    out={}
    for i in range(0,len(ts),size):
        part=ts[i:i+size]
        r=requests.get(f"{KALSHI_BASE}/markets/candlesticks",params={"market_tickers":",".join(part),"start_ts":int(start),
            "end_ts":int(end),"period_interval":1,"include_latest_before_start":"true"},headers=kalshi.UA,timeout=60)
        r.raise_for_status(); ms=r.json().get("markets",[])
        if size>1 and sum(len(x.get("candlesticks") or []) for x in ms)>=9000:   # close to the 10,000-candle cap: smaller groups
            out.update(_candles(part,start,end,max(1,size//5))); continue
        for x in ms: out[x["market_ticker"]]=sorted(x.get("candlesticks") or [],key=lambda k:k["end_period_ts"])
        time.sleep(0.2)
    return out
def _groups(rows,i):   # one group per market day, so each candle request spans one evening-to-morning stretch
    g={}
    for r in rows:
        p=r[i].split("-"); g.setdefault(p[1] if len(p)>1 else "",[]).append(r)
    return list(g.values())
def fill_time(side,price,imp,t0,t1,cs):
    """End of the first whole minute after the order (t0) and up to its cancellation (t1) in which a trade or an offer
    reached our limit price; None if that never happened. 1c better than the best bid = first in line, so reaching our
    price is enough. Joined the best bid = others were ahead, so the market had to go strictly through our price."""
    for x in cs:
        e=x["end_period_ts"]
        if e-60<t0 or e>t1: continue
        if side=="yes":
            v=[p for p in (_f(x.get("price"),"low_dollars"),_f(x.get("yes_ask"),"low_dollars")) if p is not None and p>0]
            if v and (min(v)<=price+1e-9 if imp else min(v)<price-1e-9): return e
        else:                                                  # our NO bid at `price` = a YES offer at 1-price
            a=1-price
            v=[p for p in (_f(x.get("price"),"high_dollars"),_f(x.get("yes_bid"),"high_dollars")) if p is not None and p<1]
            if v and (max(v)>=a-1e-9 if imp else max(v)>a+1e-9): return e
    return None

def _audit_event(c,ref,kind,detail):
    try:
        if "decision_events" in {r[0] for r in c.execute("select name from sqlite_master where type='table'")}:   # only once the ledger exists
            d=audit.decision_for(c,ref)
            if d: audit.event(c,d,kind,detail)
    except Exception as ex: print("shadow: audit event for %s not recorded (%s)"%(ref,ex))
def settle(c):
    tables(c); now=time.time(); nf=nu=ns=nm=0
    # 1. resting orders whose day has started: filled or not?
    pend=c.execute("select id,ticker,side,price,improved,ts,cancel_ts from shadow_orders where status='pending' and cancel_ts<=?",(now-180,)).fetchall()
    for g in _groups(pend,1):
        try: cs=_candles(sorted({o[1] for o in g}),min(o[5] for o in g)-60,max(o[6] for o in g))
        except Exception as ex: print("shadow: price history not available (%s); will retry at the next settle"%ex); continue
        for i,t,side,price,imp,t0,t1 in g:
            if t not in cs: continue
            e=fill_time(side,price,imp,t0,t1,cs[t])
            c.execute("update shadow_orders set status=?,fill_ts=? where id=?",("filled" if e else "unfilled",e,i))
            _audit_event(c,"shadow_orders:%d"%i,"filled" if e else "unfilled",dict(fill_ts=e))
            nf+=bool(e); nu+=not e
    # 2. filled orders: outcome
    fil=c.execute("select id,ticker,side,n,cost,fee from shadow_orders where status='filled'").fetchall()
    ms=_markets(sorted({r[1] for r in fil})) if fil else {}
    for i,t,side,n,cost,f in fil:
        r=(ms.get(t) or {}).get("result")
        if r in ("yes","no"):
            c.execute("update shadow_orders set status='settled',result=?,pnl=?,settle_ts=? where id=?",(r,(n if r==side else 0)-cost-f,now,i)); ns+=1
            _audit_event(c,"shadow_orders:%d"%i,"settled",dict(result=r,pnl=(n if r==side else 0)-cost-f,won=r==side))
    # 3. price moves for every logged market whose day has started
    have={r[0] for r in c.execute("select ticker from shadow_moves where version=?",(VERSION,))}
    todo=[r for r in c.execute("select ticker,ts,fc,mid from obs where version=? and fc is not null and mid is not null",(VERSION,)).fetchall() if r[0] not in have]
    ms=_markets(sorted({r[0] for r in todo})) if todo else {}
    ready=[]
    for t,ts,fc,mid in todo:
        try: w0=_t(ms[t]["close_time"])-86400
        except (KeyError,TypeError,ValueError): continue
        if now>=w0+180: ready.append((t,ts,fc,mid,w0))
    for g in _groups(ready,0):
        try: cs=_candles(sorted({x[0] for x in g}),min(x[1] for x in g)-60,max(x[4] for x in g))
        except Exception as ex: print("shadow: price history not available (%s); will retry at the next settle"%ex); continue
        for t,ts,fc,mid,w0 in g:
            if t not in cs: continue
            last=None
            for x in cs[t]:
                if x["end_period_ts"]<=w0: last=x
            b=_f((last or {}).get("yes_bid"),"close_dollars"); a=_f((last or {}).get("yes_ask"),"close_dollars")
            ok=b is not None and a is not None and 0<=b<a<=1 and a-b<=MAX_SPREAD+1e-9
            c.execute("insert or replace into shadow_moves(ticker,version,scan_ts,fc,mid_scan,start_ts,bid_start,ask_start,mid_start,status) values(?,?,?,?,?,?,?,?,?,?)",
                      (t,VERSION,ts,fc,mid,w0,b,a,(a+b)/2 if ok else None,"ok" if ok else ("wide" if last else "no_data"))); nm+=1
    # 4. v4 station forecast outcomes (from obs when v3 logged the same market, else from Kalshi)
    nv=0; todo=[t for (t,) in c.execute("select ticker from v4_obs where result is null")]
    if todo:
        res=dict(c.execute("select ticker,result from obs where result in ('yes','no')").fetchall())
        ms=_markets([t for t in todo if t not in res])
        for t in todo:
            r=res.get(t) or (ms.get(t) or {}).get("result")
            if r in ("yes","no"): c.execute("update v4_obs set result=? where ticker=?",(r,t)); nv+=1
    # 5. forward test of the past-data lead (research/PLAN.md): the bot's rule on the 50/50 blend of the airport forecast and
    #    the market, one contract per signal, paying the ask (taker) or resting a limit order until the day starts (maker).
    #    Computed here from the logged scan-time quote and Kalshi's minute candles; nothing is ever placed.
    np_=0; due=c.execute("select ticker,ts,fc,mid,bid,ask,start_ts from v4_obs where paper_done=0 and start_ts is not null and start_ts<=?",(now-180,)).fetchall()
    out_=[r for r in due if not in_window(r[1])]
    for r in out_: c.execute("update v4_obs set paper_done=2 where ticker=?",(r[0],))   # logged outside 00:50-01:30 UTC: kept, not counted
    due=[r for r in due if in_window(r[1])]
    for g in _groups(due,0):
        sig_=[]
        for t,ts,fc,mid,bid,ask,w0 in g:
            if bid is None or ask is None or not 0<=bid<ask<=1 or ask-bid>MAX_SPREAD+1e-9: sig_.append((t,None,None)); continue
            fair=BLEND*fc+(1-BLEND)*mid
            side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
            tk=(side,price) if q-price>=MIN_EDGE-1e-9 else None
            yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
            side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
            mk=(side,price,imp,ts,w0) if q-price>=MIN_EDGE-1e-9 and 0<price<1 else None
            sig_.append((t,tk,mk))
        need=[t for t,_,mk in sig_ if mk]
        try: cs=_candles(need,min(x[1] for x in g)-60,max(x[6] for x in g)) if need else {}
        except Exception as ex: print("shadow: price history not available (%s); will retry at the next settle"%ex); continue
        if any(t not in cs for t in need): continue
        for t,tk,mk in sig_:
            if tk: c.execute("insert or replace into v4_paper(ticker,kind,side,price,improved,filled) values(?,?,?,?,?,?)",(t,"taker",tk[0],tk[1],None,1))
            if mk:
                e=fill_time(mk[0],mk[1],mk[2],mk[3],mk[4],cs[t])
                c.execute("insert or replace into v4_paper(ticker,kind,side,price,improved,filled) values(?,?,?,?,?,?)",(t,"maker",mk[0],mk[1],int(mk[2]),1 if e else 0))
            c.execute("update v4_obs set paper_done=1 where ticker=?",(t,)); np_+=1
    for t,kind,side,price,r in c.execute("select p.ticker,p.kind,p.side,p.price,v.result from v4_paper p join v4_obs v on v.ticker=p.ticker where p.filled=1 and p.result is null and v.result in ('yes','no')").fetchall():
        c.execute("update v4_paper set result=?,pnl=? where ticker=? and kind=?",(r,(1 if r==side else 0)-price-(_taker_fee(price) if kind=="taker" else 0),t,kind))
    c.commit()
    print("shadow settle: %d limit orders filled, %d not filled, %d settled; %d price moves measured; %d v4 forecasts resolved; %d v4 forward signals checked"%(nf,nu,ns,nm,nv,np_))
def _taker_fee(p): return math.ceil(0.07*p*(1-p)*100-1e-9)/100   # one contract, Kalshi taker fee rounded up to the cent
WINDOW=(50*60,90*60)   # the forward test counts only forecasts logged 00:50-01:30 UTC, the 8:55 PM scan (research/PLAN.md amendment)
def in_window(ts): s=int(ts)%86400; return WINDOW[0]<=s<=WINDOW[1]
def _mday(t):
    try: return datetime.strptime(t.split("-")[1],"%y%b%d").date()
    except (IndexError,ValueError): return None
def _boot(x,block=7,n=5000,seed=11):
    """Moving-block bootstrap of the mean over consecutive market days: (2.5th, 97.5th percentile)."""
    import random
    rnd=random.Random(seed); L=len(x); k=-(-L//block); ms=[]
    for _ in range(n):
        s=[]
        for _ in range(k): i=rnd.randrange(0,L-block+1); s.extend(x[i:i+block])
        ms.append(sum(s[:L])/L)
    ms.sort(); return ms[int(0.025*n)],ms[int(0.975*n)-1]
def forward_stats(c,kind):
    """Daily profit of the forward test (research/PLAN.md amendment): every counted market day, zero on days without fills."""
    days=sorted({d for (t,) in c.execute("select ticker from v4_obs where paper_done=1 and result in ('yes','no')") for d in [_mday(t)] if d})
    by={d:0.0 for d in days}; n=0
    for t,p in c.execute("select ticker,pnl from v4_paper where kind=? and filled=1 and pnl is not null",(kind,)):
        d=_mday(t)
        if d in by: by[d]+=p; n+=1
    x=[by[d] for d in days]
    if len(x)<2: return dict(days=len(x),fills=n)
    m=sum(x)/len(x); se=(sum((v-m)**2 for v in x)/(len(x)-1)/len(x))**0.5
    out=dict(days=len(x),fills=n,mean=m,se=se)
    if len(x)>=14: out["boot"]=_boot(x)
    return out

def report(c):
    if not has_tables(c): return print("SHADOW maker: not started yet (separate paper ledger, not in gate)")
    for ts,s,k,note in (c.execute("select ts,series,key,note from rules_alerts where ts>=? order by ts",(time.time()-7*86400,)) if has_tables(c,("rules_alerts",)) else []):
        print("RULES WARNING (%s) %s %s: %s"%(datetime.fromtimestamp(ts).strftime("%b %d"),s,k,note))
    rows=c.execute("select status,side,result,pnl from shadow_orders where strategy=?",(STRATEGY,)).fetchall()
    cnt=lambda s:sum(r[0]==s for r in rows)
    st=[r for r in rows if r[0]=="settled"]; won=sum(r[2]==r[1] for r in st); pnl=sum(r[3] or 0 for r in st)
    filled=cnt("filled")+len(st); decided=filled+cnt("unfilled")
    print("SHADOW maker (limit orders, separate paper ledger, not in gate): %d placed, %d resting, %d filled of %d%s, %d settled%s"%(
        len(rows),cnt("pending"),filled,decided," (%.0f%%)"%(100.0*filled/decided) if decided else "",len(st),
        (": %d won, %d lost, pnl=$%.2f"%(won,len(st)-won,pnl)) if st else ""))
    mv=c.execute("select ticker,fc,mid_scan,mid_start from shadow_moves where version=? and status='ok'",(VERSION,)).fetchall()
    for rain,lab in ((True,"rain"),(False,"temperature")):
        rs=[r for r in mv if r[0].startswith("KXRAIN")==rain]
        if not rs: print("PRICE MOVES %s %s: none measured yet (not in gate)"%(VERSION,lab)); continue
        big=[(r[3]-r[2])*(1 if r[1]>r[2] else -1) for r in rs if abs(r[1]-r[2])>=0.05]
        print("PRICE MOVES %s %s (not in gate): %d markets. Where forecast and market differed by 5+ pts (%d): toward the forecast %d, away %d, flat %d%s"%(
            VERSION,lab,len(rs),len(big),sum(x>0.004 for x in big),sum(x<-0.004 for x in big),sum(abs(x)<=0.004 for x in big),
            (", average %+.1f pts toward"%(100*sum(big)/len(big))) if big else ""))
    if has_tables(c,("v4_obs",)):
        import strategy
        v=c.execute("select v.ticker,v.fc,v.mid,v.result,o.fc from v4_obs v left join obs o on o.ticker=v.ticker and o.version=? "
                    "where v.result in ('yes','no') and v.ask-v.bid<=?",(VERSION,MAX_SPREAD+1e-9)).fetchall()
        if not v: print("V4 STATION FORECAST (research, not in gate): none resolved yet")
        else:
            y=lambda r:1.0 if r[3]=="yes" else 0.0; b=lambda k,rs:sum((r[k]-y(r))**2 for r in rs)/len(rs); both=[r for r in v if r[4] is not None]
            mg=strategy.margin([(r[0],r[1],r[2],r[3]) for r in v])
            print("V4 STATION FORECAST (research, not in gate): %d resolved. Brier v4=%.4f vs market=%.4f%s; clear margin: %s"%(len(v),b(1,v),b(2,v),
                  ("; on the %d markets v3 also priced: v4=%.4f v3=%.4f market=%.4f"%(len(both),b(1,both),b(4,both),b(2,both))) if both else "",
                  "needs 5+ market days" if mg is None else ("yes" if strategy.clear(mg) else "no")))
    if has_tables(c,("v4_paper",)):
        for kind,lab in (("maker","limit orders"),("taker","paying the ask")):
            ps=c.execute("select pnl from v4_paper where kind=? and filled=1 and pnl is not null",(kind,)).fetchall(); tried=c.execute("select count(*) from v4_paper where kind=?",(kind,)).fetchone()[0]
            fs=forward_stats(c,kind)
            print("V4 FORWARD (past-data lead, 1 contract per signal, research only): %s: %d settled%s%s; %d market days%s%s. Futility look at 60 days, verdict at 110 (PLAN.md)."%(
                  lab,len(ps),(" of %d orders"%tried) if kind=="maker" else " trades",(", net %+.1f cents a contract"%(100*sum(x for (x,) in ps)/len(ps))) if ps else "",fs["days"],
                  (", %+.1f cents per market day (SE %.1f)"%(100*fs["mean"],100*fs["se"])) if "mean" in fs else "",
                  (", weekly block bootstrap 95%%: %+.1f to %+.1f"%(100*fs["boot"][0],100*fs["boot"][1])) if "boot" in fs else ""))
        no=c.execute("select count(*) from v4_obs where paper_done=2").fetchone()[0]
        if no: print("V4 FORWARD: %d forecasts logged outside the 00:50-01:30 UTC quote window are kept but not counted"%no)
    ms={r[0]:r[3] for r in mv}
    tr=[(s,p,ms[t]) for t,s,p in c.execute("select ticker,side,price from trades where version=?",(VERSION,)) if t in ms]
    if tr:
        v=[(m if s=="yes" else 1-m)-p for s,p,m in tr]
        print("PRICE MOVES after %s paper trades: %d trades, value at the day start minus price paid: average %+.1f cents"%(VERSION,len(v),100*sum(v)/len(v)))

if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd not in ("scan","settle","report"): sys.exit("usage: python shadow.py scan | settle | report")
    c=core.db()
    try: globals()[cmd](c)
    except SystemExit: raise
    except Exception as ex: print("shadow %s failed (the main bot is not affected): %r"%(cmd,ex)); sys.exit(1)
