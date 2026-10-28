import time, json, sqlite3, os, sys, subprocess
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
    after=_after_stop_allowed(c)   # the stop date's single look (pre-committed 2026-10-28); stores it once it can be taken
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
        if not after and not before_stop(t): R.abstain(m,"GATE_NOT_PASSED",**ctx); continue   # market days from the stop date on need a passed look
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
def final(today=None): return (today or date.today())>=STOP_DATE   # the gate is judged once, on the stop date (2026-10-14, user approved)
def gate_inputs(c,until=None):
    """The numbers the gate is judged on, from the same rows report() prints: resolved v3 rain markets with their Brier
    scores and clear-margin statistic, and settled v3 rain trades with their net P&L. With until (a date), only market
    days before it count: the single look uses until=STOP_DATE, so it judges the test's own 28 days whenever it is taken."""
    o=c.execute("select ticker,fc,mid,result from obs where result is not null and version='v3' and market_type='rain'").fetchall()
    tr=c.execute("select pnl,ticker from trades where status='settled' and version='v3' and ticker like 'KXRAIN%'").fetchall()
    if until is not None:
        o=[x for x in o if _day_before(x[0],until)]; tr=[x for x in tr if _day_before(x[1],until)]
    b=[x[1:] for x in o]
    return dict(markets=len(o),brier_fc=_brier(b,0) if b else None,brier_mkt=_brier(b,1) if b else None,
                trades=len(tr),pnl=sum(r[0] for r in tr),margin=margin(o))
def gate_ok(g,today=None):
    """The gate (CLAUDE.md section 5): on or after the stop date, at least 100 resolved v3 rain markets, forecast Brier
    below market Brier by a clear margin, at least 50 settled v3 rain trades and net P&L above zero."""
    return bool(final(today) and g["trades"]>=50 and g["pnl"]>0 and g["brier_fc"] is not None and g["brier_fc"]<g["brier_mkt"]
                and clear(g["margin"]) and g["markets"]>=100)
# The stop date's single look (pre-committed by the user on 2026-10-28, before the verdict; CLAUDE.md section 11):
# - the gate is judged once, on the test's own market days (before STOP_DATE) only: at the first report or scan on or
#   after STOP_DATE when every v3 rain market and trade of those days has its result. That look is stored in paper.db
#   (table gate_look, one row, after a backup) and is never recomputed;
# - v3 rain opens paper trades for market days from STOP_DATE on only after a look that passed. So after a failed look
#   it opens none (markets are still logged), the limit-order ledger, which mirrors the bot, places none, and live.py,
#   which copies only new paper trades, has nothing to copy. While the look is pending, none either (fail closed);
# - this only adds a stop: live.py's locks, the $25 cap and the user's typed unlock are unchanged.
GATE_LOOK_TABLE="create table if not exists gate_look(stop_date text primary key,ts real not null,passed integer not null,detail text not null)"
def market_day(t):
    try: return datetime.strptime(t.split("-")[1],"%y%b%d").date()
    except (AttributeError,IndexError,ValueError): return None
def _day_before(t,until):
    d=market_day(t); return d is not None and d<until
def before_stop(t):
    """True for a market of the test's own days (before STOP_DATE). An unreadable day counts as after (fail closed)."""
    return _day_before(t,STOP_DATE)
# No cutoff (2026-10-28): a test-day market that never gets a yes/no result (for example a voided one) keeps the look
# pending, so v3 stays closed to new market days (fail closed). A cutoff date after which such markets are left out and
# listed is the user's decision (asked 2026-10-28); set LOOK_DEADLINE to that date only on the user's explicit word.
LOOK_DEADLINE=None
def _writable(c):
    """True when c can write (live.py status opens paper.db read-only). Probes with a rolled-back savepoint."""
    try:
        c.execute("savepoint gate_probe")
        try: c.execute("create table if not exists gate_probe(x)"); return True
        finally: c.execute("rollback to gate_probe"); c.execute("release gate_probe")
    except sqlite3.Error: return False
def _backup_first():
    """paper.db is backed up before its first new table, as for the audit and shadow tables (CLAUDE.md section 3)."""
    here=os.path.dirname(os.path.abspath(__file__))
    for k in range(2):   # backup names have one-second resolution and are never overwritten: a clash is retried once
        if subprocess.run([sys.executable,os.path.join(here,"backup.py"),"pregatelook"]).returncode in (0,3): return True
        time.sleep(1.2)
    return False
def _pending(c,today=None):
    """v3 rain markets of the test's days still without a result, and open v3 rain trades on those days (tickers)."""
    o=[t for (t,) in c.execute("select ticker from obs where result is null and version='v3' and market_type='rain'")]
    tr=[t for (t,) in c.execute("select ticker from trades where status='open' and version='v3' and ticker like 'KXRAIN%'")]
    return sorted({t for t in o+tr if market_day(t) is None or market_day(t)<STOP_DATE})   # an unreadable day waits too (fail closed)
def gate_look(c,today=None,record=True):
    """None before the stop date. After it, a dict: passed True or False with the numbers it was judged on (recorded=True
    once stored), or passed None with pending=N while N v3 rain markets of the test's days have no result yet."""
    if not final(today): return None
    try: row=c.execute("select ts,passed,detail from gate_look where stop_date=?",(str(STOP_DATE),)).fetchone()
    except sqlite3.OperationalError: row=None   # no table yet: no look stored
    if row:
        d=json.loads(row[2]); d.update(passed=bool(row[1]),ts=row[0],recorded=True); return d
    pend=_pending(c)
    if pend and (LOOK_DEADLINE is None or (today or date.today())<LOOK_DEADLINE): return dict(passed=None,pending=len(pend),recorded=False)
    g=gate_inputs(c,until=STOP_DATE); ok=gate_ok(g,today)
    days=sorted({market_day(t) for (t,) in c.execute("select ticker from obs where result is not null and version='v3' and market_type='rain'")
                 if _day_before(t,STOP_DATE)})
    d=dict(g,margin=list(g["margin"]) if g["margin"] else None,first_day=str(days[0]) if days else None,last_day=str(days[-1]) if days else None,
           unresolved=pend)
    if record and _writable(c):   # never on live.py's read-only connection: worked out, not stored
        try:
            if not c.execute("select 1 from sqlite_master where type='table' and name='gate_look'").fetchone() and not _backup_first():
                raise sqlite3.OperationalError("the backup before the new table failed")
            c.execute(GATE_LOOK_TABLE)
            c.execute("insert or ignore into gate_look(stop_date,ts,passed,detail) values(?,?,?,?)",(str(STOP_DATE),time.time(),int(ok),json.dumps(d)))
            c.commit()
            return gate_look(c,today,record=False)   # the stored row decides, even if another run stored it first
        except sqlite3.Error as ex:
            print("GATE LOOK not stored (%s); the next report or scan tries again"%ex)
            try: c.rollback()
            except sqlite3.Error: pass
    d.update(passed=ok,ts=time.time(),recorded=False); return d
def _after_stop_allowed(c,today=None,record=True):
    """May v3 rain trade a market day on or after STOP_DATE? Only after a stored look that passed. Any error: no."""
    if not final(today): return False
    try:
        lk=gate_look(c,today,record)
        if lk.get("passed") is not True or not lk.get("recorded"): print(look_line(lk))
        return lk.get("passed") is True and bool(lk.get("recorded"))
    except Exception as ex:
        print("GATE LOOK: could not be worked out (%s): no v3 rain paper trades for market days from %s on"%(ex,STOP_DATE)); return False
def look_line(lk):
    """One line for report() and live.py status (its filter keeps lines that start with GATE)."""
    if lk is None:
        return ("GATE LOOK (pre-committed 2026-10-28): judged once from %s. Only a look that passes lets v3 rain paper-trade market days from %s on;"
                " if it does not pass, no edge was demonstrated and live.py gets nothing to copy."%(STOP_DATE,STOP_DATE))
    if lk.get("error"): return "GATE LOOK: could not be worked out (%s): v3 rain opens no paper trades for market days from %s on"%(lk["error"],STOP_DATE)
    if lk.get("passed") is None:
        return ("GATE LOOK: waiting for %d v3 rain markets or trades of the test's days to settle%s; until then v3 rain opens"
                " no paper trades for market days from %s on"%(lk.get("pending",0),(" (at most until %s)"%LOOK_DEADLINE) if LOOK_DEADLINE else "",STOP_DATE))
    when=time.strftime("%Y-%m-%d %H:%M",time.localtime(lk["ts"]))
    head="GATE LOOK (single look, stored %s): "%when if lk.get("recorded") else "GATE LOOK (worked out now, stored by the next report or scan): "
    if lk["passed"]: return head+"passed on paper. v3 rain keeps paper trading; real money still needs your own typed unlock, starting tiny."
    return head+("not passed: no edge demonstrated. v3 rain opens no new paper trades (markets are still logged), so live.py has nothing to copy."
                 " Changing that needs your explicit decision.")
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
    when="every market day so far; the gate is the single look below" if final() else f"interim, not acted on; judged once on {STOP_DATE}"
    if mg is None: print(f"CLEAR MARGIN (gate): needs 5+ resolved market days ({nd} so far); judged once on {STOP_DATE}")
    else: print(f"CLEAR MARGIN (gate, {when}): forecast minus market Brier {mg[0]:+.4f} per market day, needs a lead of {tcrit(mg[2]):.2f} SE over {mg[2]} days = {tcrit(mg[2])*mg[1]:.4f}: "+("clear" if clear(mg) else "not clear"))
    ok=gate_ok(gate_inputs(c))   # the same rule as before: final() and n3>=50 and pnl3>0 and bf<bm and clear(mg) and no>=100
    lk=None; fin=final()   # read once: a run that crosses midnight on the stop date stays on one side of it
    if fin:   # judged once (2026-10-28): from the stop date the verdict is the single look's, never today's numbers
        try: lk=gate_look(c)
        except Exception as ex: lk=dict(passed=None,error=str(ex)[:200])
        ok=lk.get("passed") is True
        verdict="passed (paper only)" if ok else ("not passed" if lk.get("passed") is False else "not judged yet (the single look is pending)")
    print("GATE (v3 rain only):",verdict if fin else f"judged once on {STOP_DATE} (single look); the numbers above are interim")
    print(look_line(lk))
    left=(STOP_DATE-date.today()).days
    print(f"STOP DATE: {STOP_DATE} ({left} days left). If not clearly passed by then: no edge demonstrated, no live trading.")
    if no>=100 and clear(mg) and n3<50: print("NOTE: Brier looks good but <50 settled v3 trades: no live money; the user decides on an extension"
                                               " (after a failed look v3 opens no paper trades, so an extension needs the user's explicit rule change).")
