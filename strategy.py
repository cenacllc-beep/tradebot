import time, json
from datetime import date, datetime, timedelta, timezone
from config import *
import core, kalshi, weather, nws
# Audit and research helpers (2026-10-22). None of them decides a v3 trade, so a missing or broken one must not stop
# the scan: obs logging carries on, and without the ledger no paper trade opens (fail closed).
try: import audit
except Exception as _ex: audit=None; print("AUDIT UNAVAILABLE: audit.py could not be loaded (%s)"%_ex)
try: import selector, calibration, risk
except Exception as _ex: selector=calibration=risk=None; print("shadow selector unavailable (%s)"%_ex)
class _NoLedger:
    """Stand-in when audit.py cannot be loaded: records nothing, and refuses trades so none opens unrecorded."""
    def __init__(self,stats): self.stats=stats
    def abstain(self,m,reason,**kw): self.stats[reason]=self.stats.get(reason,0)+1
    def trade(self,*a,**kw): raise RuntimeError("audit.py could not be loaded")
def _cluster(t):
    try: return risk.cluster(t)
    except Exception: return "unknown"
VERSION="v3"   # v1 = Open-Meteo peak-hourly rain; v2 = NWS 12h periods (6am-6am); v3 = NWS hourly slices aligned to Kalshi day
ESTIMATORS=[weather.estimator]   # add more fn(market)->P(YES) or None
STOP_DATE=date(2026,11,11)   # 28 market days (Oct 14 - Nov 10), judged once; moved from Oct 26 by the user on 2026-10-14, before any result
def started(m):
    """True once the market's Kalshi day has begun: close_time - 24h (close_time is local standard-time midnight for rain and
    temperature alike). CLAUDE.md section 6: scans run before that and the market is skipped otherwise (not logged, not
    traded). The rain estimator always did this; temperature markets did not until 2026-10-14 (a run at 9:22 AM opened two
    same-day temperature trades). An unreadable close time counts as started (scan() counts those separately)."""
    close=close_time(m)
    return close is None or datetime.now(timezone.utc)>=close-timedelta(hours=24)
def close_time(m):
    for f in ("%Y-%m-%dT%H:%M:%SZ","%Y-%m-%dT%H:%M:%S.%fZ"):
        try: return datetime.strptime(m.get("close_time") or "",f).replace(tzinfo=timezone.utc)
        except (TypeError,ValueError): pass
    return None
def estimate(m):
    for f in ESTIMATORS:
        try: p=f(m)
        except Exception as e: print("estimator error",m.get("ticker"),e); p=None
        if p is not None: return min(max(p,0.01),0.99)
    return None
STRATEGY_RAIN="forecast_alpha.rain.v3"; STRATEGY_TEMP="forecast_alpha.temp.v3"
# Veto (user decision 2026-10-28, after the audit): no rain trade when the forecast and the market mid are more than
# 30 points apart. The bound is the accuracy-first selector's ANOMALOUS_MODEL_MARKET_GAP check, frozen 2026-10-22
# (selector.EXPERIMENTS["accuracy_first.v1"]["max_gap"]). "More than 30 points": a gap that is 30 points up to float
# rounding (0.30000000000000004) is allowed here, while the shadow selector, which has no tolerance, flags it.
# The forecast, blend, edge and limits are unchanged. Each scan records VETO_MAX_GAP in its config row.
VETO_MAX_GAP=0.30
def _ctx(m,t,raw=None,bid=None,ask=None):
    """The fields every decision row carries (audit only; never used to decide). Never raises: a failure here only
    thins the record."""
    try: return _ctx_fields(m,t,raw,bid,ask)
    except Exception as ex: return dict(bid=bid,ask=ask,p_model=raw,detail=dict(ctx_error=str(ex)[:200]))
def _ctx_fields(m,t,raw,bid,ask):
    close=close_time(m); w=weather.RAW.get(t) or {}
    st=w.get("station"); lat_lon=None
    try: key=t.split("-")[2]; lat_lon=weather.RAIN[key][1:] if t.startswith("KXRAIN") and key in weather.RAIN else None
    except IndexError: pass
    meta=nws.GRID_META.get(lat_lon) if lat_lon else None
    inputs=dict(w,grid=meta) if (w or meta) else None
    return dict(market_type="rain" if t.startswith("KXRAIN") else "temp",close_ts=close.timestamp() if close else None,
                day_start_ts=(close-timedelta(hours=24)).timestamp() if close else None,bid=bid,ask=ask,p_model=raw,station=st,inputs=inputs)
def scan(c):
    if core.killed(): return print("KILL file present: halted")
    ready=audit.ensure(c) if audit else False
    if not ready: print("TRADES BLOCKED: the audit ledger is unavailable. Markets are logged as before, but no paper trade can open without its decision record")
    sid=None
    if ready:
        try: sid=audit.start_scan(c,"scan",dict(BANKROLL=BANKROLL,KELLY_FRACTION=KELLY_FRACTION,MAX_POS_PCT=MAX_POS_PCT,MAX_OPEN_PCT=MAX_OPEN_PCT,
                                                 MIN_EDGE=MIN_EDGE,MAX_SPREAD=MAX_SPREAD,BLEND=BLEND,DAILY_LOSS_LIMIT=DAILY_LOSS_LIMIT,VERSION=VERSION,VETO_MAX_GAP=VETO_MAX_GAP))
        except Exception as ex: print("AUDIT: could not start the scan record (%s); no paper trades this scan"%ex)
    stats={}
    if audit:
        mv="%s@%s"%(VERSION,audit.code_hash(("weather.py","nws.py","strategy.py")))
        RR=audit.Recorder(c,sid,STRATEGY_RAIN,VERSION,mv,"paper",stats); RT=audit.Recorder(c,sid,STRATEGY_TEMP,VERSION,mv,"research",stats)
    else: RR=RT=_NoLedger(stats)
    try: cal=calibration.Calib(calibration.v3_rain_rows(c))
    except Exception as ex: cal=None; print("shadow selector: calibration unavailable (%s)"%ex)
    cash,today=core.state(c)
    stop=today<=-DAILY_LOSS_LIMIT*BANKROLL   # daily loss stop: no new paper trades, but keep logging markets for the forecast test
    if stop: print("daily loss limit hit: no new paper trades this scan (markets are still logged)")
    held={r[0] for r in c.execute("select ticker from trades where status='open'")}
    try: clus=risk.exposure(c.execute("select ticker,cost+fee from trades where status='open'").fetchall())   # shadow selector only
    except Exception: clus={}
    opn=c.execute("select coalesce(sum(cost+fee),0) from trades where status='open'").fetchone()[0]   # all versions
    k=seen=late=bad=0
    for m in kalshi.markets():
        t=m["ticker"]; R=RR if t.startswith("KXRAIN") else RT
        if close_time(m) is None: bad+=1; R.abstain(m,"CLOSE_TIME_UNREADABLE",**_ctx(m,t)); continue   # unreadable close time: skipped, and reported below
        if started(m): late+=1; R.abstain(m,"MARKET_STARTED",**_ctx(m,t)); continue   # its day has begun: too late to log or trade (section 6)
        bid,ask=kalshi.quote(m)
        if bid is None or ask is None or not 0<ask<1: R.abstain(m,"NO_QUOTE",**_ctx(m,t,bid=bid,ask=ask)); continue
        if ask-bid>MAX_SPREAD: R.abstain(m,"WIDE_SPREAD",**_ctx(m,t,bid=bid,ask=ask)); continue
        weather.RAW.pop(t,None); raw=estimate(m)
        if raw is None: R.abstain(m,"MODEL_UNAVAILABLE",**_ctx(m,t,bid=bid,ask=ask)); continue
        mid=(bid+ask)/2
        w=weather.RAW.get(t,{}); sl=w.get("slices")
        c.execute("insert or ignore into obs(ticker,version,ts,fc,mid,nws_prev,nws_day,nws_night,market_type,p_a,p_b,slices,mu,station) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t,VERSION,time.time(),raw,mid,w.get("prev"),w.get("day"),w.get("night"),"rain" if t.startswith("KXRAIN") else "temp",w.get("p_a"),w.get("p_b"),json.dumps(sl) if sl else None,w.get("mu"),w.get("station"))); seen+=1
        fair=BLEND*raw+(1-BLEND)*mid
        side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
        ctx=_ctx(m,t,raw,bid,ask); ctx.update(side=side,p_fair=fair,p_win=q,price=price)
        try:   # the shadow selector watches only; its failure never changes the v3 decision
            g=(ctx.get("inputs") or {}).get("grid") or {}
            shadow=selector.evaluate(dict(side=side,p_win=q,p_yes=fair,p_model_yes=raw,mid=mid,price=price,fee_pc=core.fee(price,1),spread=ask-bid,
                                          data_age_s=(time.time()-g["fetched"]) if g.get("fetched") else None,
                                          cluster_open=clus.get(_cluster(t),0.0),bankroll=BANKROLL),cal)
        except Exception as ex: shadow=dict(error=str(ex)[:200])
        ctx["detail"]=dict(meta=shadow,blend=BLEND,min_edge=MIN_EDGE)
        if stop: R.abstain(m,"DAILY_LOSS_STOP",**ctx); continue
        if t in held: R.abstain(m,"ALREADY_HELD",**ctx); continue
        if not t.startswith("KXRAIN"): R.abstain(m,"STRATEGY_DISABLED",**ctx); continue   # temperature: logged, not traded (user decision 2026-10-14, research/PLAN2.md result)
        if q-price<MIN_EDGE: R.abstain(m,"INSUFFICIENT_EDGE",**ctx); continue
        if abs(raw-mid)>VETO_MAX_GAP+1e-9: R.abstain(m,"ANOMALOUS_MODEL_MARKET_GAP",**ctx); continue   # veto since 2026-10-28 (user)
        n=int(core.kelly_stake(q,price,cash)//price)
        if n<1: R.abstain(m,"SIZE_BELOW_ONE",**ctx); continue
        f=core.fee(price,n); cost=n*price
        if cost+f>cash: R.abstain(m,"CASH_LIMIT",fee=f,n=n,cost=cost,**ctx); continue
        if opn+cost+f>BANKROLL*MAX_OPEN_PCT: R.abstain(m,"EXPOSURE_CAP",fee=f,n=n,cost=cost,**ctx); continue   # exposure cap, counts all open trades
        c.execute("savepoint paper_trade")   # the trade and its decision row are written together or not at all (fail closed)
        try:
            cur=c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)",(time.time(),t,side,price,q,n,cost,f,VERSION))
            ctx.pop("side",None); R.trade(m,side,fee=f,n=n,cost=cost,trade_ref="trades:%d"%cur.lastrowid,**ctx)
            c.execute("release paper_trade")
        except Exception as ex:
            c.execute("rollback to paper_trade"); c.execute("release paper_trade")
            stats["AUDIT_UNAVAILABLE"]=stats.get("AUDIT_UNAVAILABLE",0)+1; print("NOT TRADED %s: its decision could not be recorded (%s)"%(t,ex)); continue
        cash-=cost+f; opn+=cost+f; k+=1; clus[_cluster(t)]=clus.get(_cluster(t),0.0)+cost+f; print(f"PAPER {side} {t} x{n} @{price:.2f} fair={q:.2f}")
    try:
        if audit: audit.end_scan(c,sid,dict(markets_logged=seen,trades=k,late=late,unreadable=bad,reasons=stats))
    except Exception as ex: print("AUDIT: could not close the scan record (%s)"%ex)
    c.commit(); print(f"{seen} markets in shadow log, {k} paper trades logged (rain only; temperature is logged, not traded)"+(f" ({late} skipped: their day had already begun)" if late else ""))
    if bad: print(f"WARNING: {bad} markets had a close time the bot cannot read and were skipped (Kalshi may have changed the format)")
    if sid: print("AUDIT: scan %s recorded %d decisions (%s)"%(sid[:8],sum(v for k_,v in stats.items() if not k_.startswith("_")),
                   ", ".join("%s %d"%kv for kv in sorted(stats.items()))))
SETTLE_TRIES=3; SETTLE_PAUSE_S=5.0; SETTLE_BUDGET_S=15*60
class Unreached(Exception):
    """A market whose result could not be read. network=True when the last try failed to reach Kalshi at all."""
    def __init__(self,msg,network=False): Exception.__init__(self,msg); self.network=network
def _network_error(ex):
    try: return isinstance(ex,(kalshi.requests.exceptions.ConnectionError,kalshi.requests.exceptions.Timeout))
    except AttributeError: return False
def result_of(t,tries=SETTLE_TRIES,pause=SETTLE_PAUSE_S,sleep=time.sleep):
    """Kalshi's result for one market: 'yes' or 'no' once decided, else whatever Kalshi says (often ''). Retries a
    failed lookup; after `tries` failures raises Unreached (added 2026-10-28: a single network error used to stop the
    whole settle, losing every result found before it, on Oct 26 and Oct 27)."""
    last=None
    for k in range(tries):
        try:
            m=kalshi.get(t)
            if not isinstance(m,dict): raise ValueError("no market in Kalshi's answer")
            r=m.get("result")
            if r not in ("yes","no") and str(m.get("status") or "").lower() in ("settled","finalized","determined"):
                print("SETTLE WARNING: %s is %s with result %r; its paper trade stays open (check it by hand: a voided market refunds)"%(t,m.get("status"),r))
            return r
        except Exception as ex:
            last=ex
            if k<tries-1: sleep(pause*(k+1))
    raise Unreached("%s: %s"%(t,str(last)[:160]),network=_network_error(last))
def settle(c,lookup=None,clock=time.time,budget=SETTLE_BUDGET_S):
    """Record results for open paper trades and logged markets (made robust 2026-10-28, audit):
    - a market that cannot be read is skipped and checked again at the next settle;
    - each result is committed as soon as it is recorded, a trade together with its audit event (one savepoint);
    - a trade is settled only while still open, so two settles at once cannot record it twice;
    - after 3 network failures in a row, or `budget` seconds, the remaining markets wait for the next settle;
    - exits 1 only when no market could be read at all, so the scheduled job shows a failed settle."""
    lookup=lookup or result_of; ready=audit.ensure(c) if audit else False
    got={}; missed=[]; run=[0]; t0=clock()   # run[0]: network failures in a row
    def res(t):
        if t not in got:
            if run[0]>=3: got[t]=None; missed.append("%s: not tried, Kalshi was unreachable 3 times in a row"%t); return None
            if clock()-t0>budget: got[t]=None; missed.append("%s: not tried, settle's %d-minute budget was used"%(t,budget//60)); return None
            try: got[t]=lookup(t); run[0]=0
            except Unreached as ex:
                got[t]=None; missed.append(str(ex)); run[0]=run[0]+1 if getattr(ex,"network",False) else 0
        return got[t]
    def atomic(fn):
        c.execute("savepoint settle_one")
        try: fn()
        except BaseException:
            c.execute("rollback to settle_one"); c.execute("release settle_one"); raise
        c.execute("release settle_one"); c.commit()
    try:
        for i,t,side,n,cost,f in c.execute("select id,ticker,side,n,cost,fee from trades where status='open'").fetchall():
            r=res(t)
            if r in ("yes","no"):
                def one(i=i,t=t,side=side,n=n,cost=cost,f=f,r=r):
                    pnl=(n if r==side else 0)-cost-f
                    cur=c.execute("update trades set status='settled',result=?,pnl=?,settled_ts=? where id=? and status='open'",(r,pnl,time.time(),i))
                    if cur.rowcount==1 and ready:
                        try:
                            audit.record_result(c,t,r); d=audit.decision_for(c,"trades:%d"%i)
                            if d: audit.event(c,d,"settled",dict(result=r,pnl=pnl,won=r==side))
                        except Exception as ex: print("AUDIT: settlement of %s not recorded (%s)"%(t,ex))
                atomic(one)
        for (t,) in c.execute("select distinct ticker from obs where result is null").fetchall():
            r=res(t)
            if r in ("yes","no"):
                def one(t=t,r=r):
                    c.execute("update obs set result=? where ticker=? and result is null",(r,t))
                    if ready:
                        try: audit.record_result(c,t,r)
                        except Exception as ex: print("AUDIT: result of %s not recorded (%s)"%(t,ex))
                atomic(one)
    finally:
        c.commit()
    if missed:
        print("SETTLE: %d of %d markets could not be read from Kalshi; they stay open and are checked again at the next settle. First: %s"%(len(missed),len(got),missed[0]))
        if len(missed)==len(got): raise SystemExit(1)
def _brier(o,k): return sum(((r[2]=="yes")-r[k])**2 for r in o)/len(o)
def margin(o):
    """Gate's 'clear margin' (defined 2026-10-14): forecast Brier minus market Brier for each market, averaged within each
    market day, because cities on the same day share weather, so each day counts once. Returns (mean, standard error,
    days), or None with fewer than 5 days. Clear = mean below zero by at least 2 standard errors."""
    days={}
    for t,f,m,r in o:
        y=1.0 if r=="yes" else 0.0; days.setdefault(t.split("-")[1],[]).append((f-y)**2-(m-y)**2)
    d=[sum(v)/len(v) for v in days.values()]
    if len(d)<5: return None
    mu=sum(d)/len(d); return mu,(sum((x-mu)**2 for x in d)/(len(d)-1)/len(d))**0.5,len(d)
T975={1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,
      16:2.120,17:2.110,18:2.101,19:2.093,20:2.086,21:2.080,22:2.074,23:2.069,24:2.064,25:2.060,26:2.056,27:2.052,28:2.048,29:2.045,30:2.042}
def tcrit(days):
    """Student-t 97.5% critical value for the day means (df = days - 1), never below the old 2.0 (2026-10-14, user approved)."""
    return max(2.0,T975.get(days-1,2.0))
def clear(mg): return mg is not None and mg[0]<0 and -mg[0]>=tcrit(mg[2])*mg[1]
def final(): return date.today()>=STOP_DATE   # the gate is judged once, on the stop date (2026-10-14, user approved)
def report(c):
    try:
        import registry; registry.log_states(c); c.commit()   # append-only history of each strategy's lifecycle state
    except Exception as ex: print("registry log not written (%s)"%ex)
    # GATE = v3 RAIN markets only. Temperature is exploratory. Earlier versions are excluded.
    bf=bm=None; no=0
    for v in ("v1","v2","v3"):
        for mt,tag in (("rain","[GATE]" if v=="v3" else "[excluded from gate]"),("temp","[exploratory, not in gate]")):
            o=c.execute("select fc,mid,result from obs where result is not null and version=? and market_type=?",(v,mt)).fetchall()
            if o:
                f,m=_brier(o,0),_brier(o,1)
                print(f"SHADOW {v} {mt}: {len(o)} resolved. Brier forecast={f:.3f} vs market={m:.3f} (lower wins) {tag}")
                if v=="v3" and mt=="rain": bf,bm,no=f,m,len(o)
            else: print(f"SHADOW {v} {mt}: no resolved markets yet {tag}")
    n3=pnl3=0
    for v in ("v1","v2","v3"):
        for mt in ("rain","temp"):
            rows=c.execute("select side,result,pnl from trades where status='settled' and version=? and (ticker like 'KXRAIN%')=?",(v,1 if mt=="rain" else 0)).fetchall(); n=len(rows)
            if n:
                pnl=sum(r[2] for r in rows); print(f"TRADES {v} {mt}: settled={n} pnl=${pnl:.2f} win={sum(r[1]==r[0] for r in rows)/n:.0%}"+("  [GATE]" if v=="v3" and mt=="rain" else "  [excluded/exploratory]"))
                if v=="v3" and mt=="rain": n3,pnl3=n,pnl
    if not n3: print("TRADES v3 rain: none settled yet [GATE]")
    mg=margin(c.execute("select ticker,fc,mid,result from obs where result is not null and version='v3' and market_type='rain'").fetchall())
    nd=len({t.split("-")[1] for (t,) in c.execute("select ticker from obs where result is not null and version='v3' and market_type='rain'")})
    when="final look" if final() else f"interim, not acted on; judged once on {STOP_DATE}"
    if mg is None: print(f"CLEAR MARGIN (gate): needs 5+ resolved market days ({nd} so far); judged once on {STOP_DATE}")
    else: print(f"CLEAR MARGIN (gate, {when}): forecast minus market Brier {mg[0]:+.4f} per market day, needs a lead of {tcrit(mg[2]):.2f} SE over {mg[2]} days = {tcrit(mg[2])*mg[1]:.4f}: "+("clear" if clear(mg) else "not clear"))
    ok=final() and n3>=50 and pnl3>0 and bf is not None and bf<bm and clear(mg) and no>=100
    print("GATE (v3 rain only):",("passed (paper only)" if ok else "not passed") if final() else f"judged once on {STOP_DATE} (single look); the numbers above are interim")
    left=(STOP_DATE-date.today()).days
    print(f"STOP DATE: {STOP_DATE} ({left} days left). If not clearly passed by then: no edge demonstrated, no live trading.")
    if no>=100 and clear(mg) and n3<50: print("NOTE: Brier looks good but <50 settled v3 trades: no live money; the user decides on an extension.")
