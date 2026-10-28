"""Read-only dashboard: python dashboard.py [--no-open] [--live]  ->  dashboard.html
Opens paper.db read-only (sqlite URI mode=ro), only lists backup file names and dates (never opens or changes them),
and writes only dashboard.html. The page makes no network requests (system fonts only). It reads marks.jsonl (live prices
of open paper trades, written by marks.py) when it exists, for the account chart. --live (used by `run watch`) makes the
page reload itself every 5 minutes when opened from this PC. It also reads live.db (the Kalshi
account ledger written by live.py) read-only for one tile.
Also shows the shadow tests from shadow.py (research only, never part of the gate) when their tables exist, and the
past-data test summary from research/results/rain_backtest.json when it exists (read-only).
Python 3.8+, no dependencies.
(Rebuilt 2026-10-13 after the original project folder was lost; same read-only contract and same gate rules.)"""
import sqlite3, os, sys, html, webbrowser, json, glob
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
try: import config as C
except Exception: C=None
try: from core import killed, kill_file   # the bot's own kill-switch rule (KILL, KILL.txt, any case, in the tradebot folder)
except Exception:   # core.py missing or broken: the same rule (tests/test_kill.py checks this copy), failing closed
    def kill_file():
        here=os.path.dirname(os.path.abspath(__file__))
        for d in (here,os.getcwd()):
            try: names=sorted(os.listdir(d))
            except OSError:
                if d==here: return os.path.join(here,"KILL (the tradebot folder could not be read)")
                continue
            for n in names:
                if n.lower()=="kill" or n.lower().startswith("kill."): return os.path.join(d,n)
        return None
    def killed(): return kill_file() is not None
try: import control_view as CV   # control center: strategies, selector, calibration, risk, audit (presentation only)
except Exception as ex: CV=None; print("control center unavailable:",ex)
try: from dashboard_assets import CSS, JS   # static page assets (text only)
except Exception as ex: CSS=JS=""; print("page styles unavailable (dashboard_assets.py: %s); the page is written unstyled"%ex)
try: import account_view as AV   # paper account chart, activity, statements, gains report (presentation only)
except Exception as ex: AV=None; print("account view unavailable:",ex)
try: import freshness as FR   # data freshness checks (read-only; added 2026-10-23)
except Exception as ex: FR=None; print("freshness checks unavailable:",ex)
# Times on the page are in the bot's zone, La Paz (UTC-4 all year), whatever zone this PC uses (2026-10-23).
try: from tbcommon.clock import BOT_TZ
except Exception: BOT_TZ=timezone(timedelta(hours=-4))
def g(k,d): return getattr(C,k,d) if C else d
BANK=g("BANKROLL",25.0); CAP=g("MAX_OPEN_PCT",0.15); DLL=g("DAILY_LOSS_LIMIT",0.10); DB=g("DB","paper.db")
EDGE=g("MIN_EDGE",0.08); BLEND=g("BLEND",0.5)
GV=os.getenv("GATE_VERSION","v3"); e=html.escape
RESTART=date(2026,10,13)    # the test restarted this day after the data loss; its first market day is the next day
OFFSITE=os.getenv("TRADEBOT_OFFSITE_BACKUPS",os.path.join(os.path.expanduser("~"),"Documents","tradebot_backups"))
DAY_START_UTC=5             # Kalshi's day starts at local standard midnight; Eastern cities are first, at 05:00 UTC

# ---------- data helpers ----------
def load(c,t,where="",args=()):
    cols=[r[1] for r in c.execute("pragma table_info(%s)"%t)]
    out=[dict(zip(cols,r)) for r in c.execute("select * from %s %s"%(t,where),args)] if cols else []
    for r in out:
        r["version"]=r.get("version") or "v1"
        r["mtype"]=r.get("market_type") or ("rain" if str(r.get("ticker","")).startswith("KXRAIN") else "temp")
    return out
def brier(rs,k): return sum(((r["result"]=="yes")-r[k])**2 for r in rs)/len(rs) if rs else None
def mean(x): return sum(x)/len(x) if x else None
# The gate's rules come from gate.py: standard library only, so the page renders even when the trading modules cannot
# be imported. strategy.py keeps an identical copy until stage 2 (tests/test_fix.py checks they agree).
try:
    import gate as _gate
    GATE_OK=True
except Exception as ex:   # gate.py missing or broken: never show a pass, and say so on the page
    _gate=None; GATE_OK=False; print("gate rules unavailable (gate.py could not be imported: %s)"%ex)
STOP=_gate.STOP_DATE if _gate else date(2026,11,11)
T975=_gate.T975 if _gate else {}
def tcrit(days): return _gate.tcrit(days) if _gate else float("inf")
def clear(mg): return _gate.clear(mg) if _gate else False
def margin(rg):
    """The gate's 'clear margin' on dashboard rows: (mean, standard error, days), or None under 5 days."""
    return _gate.margin([(r["ticker"],r["fc"],r["mid"],r["result"]) for r in rg]) if _gate else None
def final(): return date.today()>=STOP   # the gate is judged once, on the stop date
def f3(x): return "n/a" if x is None else "%.3f"%x
def usd(x): return ("-$%.2f"%-x) if x<-0.004 else "$%.2f"%abs(x)
def plus(x): return ("+"+usd(x)) if x>0.004 else usd(x)
def pct(x): return "%.0f%%"%(x*100)
def mdate(t):
    try: return datetime.strptime(t.split("-")[1],"%y%b%d").date()
    except Exception: return None
def dstr(d): return d.strftime("%b ")+str(d.day)            # "Oct 14" (no zero padding; works on Windows)
def tstr(dt): return dt.strftime("%I:%M %p").lstrip("0")    # "10:25 PM"
def when(dt): return "%s, %s"%(dstr(dt),tstr(dt))
def loc(ts): return datetime.fromtimestamp(ts,BOT_TZ)        # bot time (UTC-4); before 2026-10-23, this PC's zone
def dstart(d): return datetime(d.year,d.month,d.day,DAY_START_UTC,tzinfo=timezone.utc)
def days_list(ds): return ", ".join(dstr(d) for d in ds)
def city(t):   # Kalshi's renamed daily-high series put a T before the city (KXHIGHTSEA): shown as SEA
    s=t.split("-")[0]
    return t.split("-")[-1] if t.startswith("KXRAIN") else (s[7:] if s.startswith("KXHIGHT") else s.replace("KXHIGH",""))+" "+t.split("-")[-1]
def won(r): return bool(r.get("side")) and r.get("result")==r.get("side")
def tip(s): return ' data-tip="%s"'%e(s,quote=True)
def s_(n,word): return "%d %s%s"%(n,word,"" if n==1 else "s")

# ---------- small components ----------
def table(heads,rows,empty="Nothing yet.",num=()):
    th="".join("<th%s>%s</th>"%(" class=n" if i in num else "",h) for i,h in enumerate(heads))
    if not rows: body="<tr><td colspan=%d class=empty>%s</td></tr>"%(len(heads),empty)
    else:
        body=""
        for r in rows:
            tds=""
            for i,cell in enumerate(r):
                txt,cl=cell if isinstance(cell,tuple) else (cell,"")
                k=" ".join(x for x in (("n" if i in num else ""),cl) if x)
                tds+="<td%s>%s</td>"%(' class="%s"'%k if k else "",txt)
            body+="<tr>%s</tr>"%tds
    return "<div class=scroll><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"%(th,body)
def meter(frac,over=False):
    return '<div class=meter><i class="%s" style="width:%.1f%%"></i></div>'%("over" if over else "",max(0,min(1,frac))*100)

# ---------- sections ----------
def verdict(rg,bf,bm,rain,passed,mg,look=None):
    n=len(rg)
    if passed: return "All four gate checks pass on paper. Real money still needs your go-ahead, starting tiny."
    if final() and not look: return ("The gate's single look is pending: it is taken once every market of the test's days has settled,"
                                     " by the next report or scan. Until then the rain bot opens no paper trades for new market days.")
    if look: return ("The gate's single look (%s) did not pass: no edge demonstrated. The rain bot opens no new paper trades,"
                     " so live.py has nothing to copy."%dstr(datetime.fromtimestamp(look[0]["ts"]).date()))
    if n==0:
        pend=sorted({d for d in (mdate(r["ticker"]) for r in rain if r.get("result") not in ("yes","no")) if d})
        if pend:
            k=sum(1 for r in rain if mdate(r["ticker"])==pend[0])
            return "No answer yet. The first %d rain markets settle on %s."%(k,dstr(pend[0]+timedelta(days=1)))
        return "No answer yet. Run the first scan in the evening, before 1:00 AM."
    sc="(%s vs %s, lower is better)"%(f3(bf),f3(bm))
    lead="The forecast leads" if bf<bm else "The market leads"
    if n<100: return "Too early to tell. %s after %d of 100 markets %s."%(lead,n,sc)
    if clear(mg): return ("The forecast beat the market by a clear margin over %d markets %s."%(n,sc)) if final() else ("So far the forecast leads by more than the noise over %d markets %s. The gate is judged once, on %s."%(n,sc,dstr(STOP)))
    if bf<bm: return "The forecast leads over %d markets %s, but not yet by more than the day-to-day noise."%(n,sc)
    return "So far the market's prices score better than the forecast over %d markets %s."%(n,sc)
def gate_chips(rg,bf,bm,sg,pnl,left,mg):
    def pace(n,target,unit):
        if n>=target or left<=0: return ""
        k=max(1,int(round((target-n)/float(left)))); return "<small>About %d %s a day to pass by %s</small>"%(k,unit if k!=1 else unit[:-1],dstr(STOP))
    items=[("Resolved rain markets","%d <small>of 100</small>"%len(rg),len(rg)>=100,meter(len(rg)/100.0)+pace(len(rg),100,"markets")),
           ("Forecast beats market",("%s <small>vs %s</small>"%(f3(bf),f3(bm))) if bf is not None else "<small>no results yet</small>",clear(mg) and final(),mtext(rg,mg)),
           ("Settled rain trades","%d <small>of 50</small>"%len(sg),len(sg)>=50,meter(len(sg)/50.0)+pace(len(sg),50,"trades")),
           ("Net paper P&amp;L",plus(pnl),pnl>0 and len(sg)>0,"<small>Rain trades, after fees</small>")]
    out="".join('<li class="%s"><span class=ic aria-hidden=true>%s</span><span class=gl>%s</span><b class=gv>%s</b>%s<span class=sr>%s</span></li>'
                %("ok" if ok else "wait","✓" if ok else "○",lab,val,extra,"passes" if ok else "not yet") for lab,val,ok,extra in items)
    return '<ul class=gate>%s</ul>'%out, sum(1 for x in items if x[2])
def mtext(rg,mg):
    if mg is None: return "<small>Brier score, lower is better. Needs a clear margin over 5+ market days (%d so far), judged once on %s.</small>"%(len({r["ticker"].split("-")[1] for r in rg}),dstr(STOP))
    if mg[0]>=0: return "<small>Market ahead by %.3f a market over %d days. Judged once on %s.</small>"%(mg[0],mg[2],dstr(STOP))
    return "<small>Lead %.3f a market; clear above %.3f (%.2f standard errors, %d days). Judged once on %s.</small>"%(-mg[0],tcrit(mg[2])*mg[1],tcrit(mg[2]),mg[2],dstr(STOP))
def calendar(rain,nd):
    days=[RESTART+timedelta(days=i) for i in range(1,(STOP-RESTART).days)]   # market days that can settle by the stop date
    by={}
    for r in rain: by.setdefault(mdate(r["ticker"]),[]).append(r)
    now=datetime.now(timezone.utc); cells=""
    for d in days:
        rs=by.get(d,[]); nres=sum(r.get("result") in ("yes","no") for r in rs)
        if rs and nres==len(rs): st,t="settled","%s: %s, all settled"%(dstr(d),s_(len(rs),"market"))
        elif rs: st,t="logged","%s: %s logged, %d settled"%(dstr(d),s_(len(rs),"market"),nres)
        elif dstart(d)<=now: st,t="missed","%s: no scan before the day started"%dstr(d)
        else: st,t="upcoming","%s: upcoming"%dstr(d)
        nx=" next" if d==nd else ""
        cells+='<li class="%s%s" tabindex=0%s><i></i><span>%d</span></li>'%(st,nx,tip(t+(". Next scan is for this day." if nx else "")),d.day)
    today=date.today(); dn=max(1,min((today-RESTART).days+1,(STOP-RESTART).days+1))
    legend=('<p class=calkey><span><i class=settled></i>Settled</span><span><i class=logged></i>Waiting for results</span>'
            '<span><i class=missed></i>Missed scan</span><span><i class=upcoming></i>Upcoming</span><span><i class="upcoming next"></i>Next scan</span></p>')
    head='<div class=calhead><b>Day %d of %d</b><span>%s market days can settle before the %s stop date. %s left.</span></div>'%(
        dn,(STOP-RESTART).days+1,len(days),dstr(STOP),s_(max((STOP-today).days,0),"day"))
    return '<div class=cal>%s<ol class=days style="--n:%d">%s</ol>%s</div>'%(head,min(len(days),15),cells,legend)   # up to 15 a row; 60 days wrap into 4 rows
def plan(obs):
    now=datetime.now(timezone.utc); today=date.today()
    nd=now.date() if now<dstart(now.date()) else now.date()+timedelta(days=1)   # next market day that has not begun
    ds=[d for d in (mdate(r["ticker"]) for r in obs) if d]
    if ds and max(ds)>=nd: nd=max(ds)+timedelta(days=1)                          # already scanned: the next one is the day after
    pend=sorted({d for d in (mdate(r["ticker"]) for r in obs if r.get("result") not in ("yes","no")) if d})
    due=[d for d in pend if d<today]; later=[d for d in pend if d>=today]; rows=[]
    if due: rows.append(("Settle %s markets"%days_list(due),"Results should be in now",".\\run settle",True))
    if later: rows.append(("Settle %s markets"%days_list(later),"On the afternoon of %s"%dstr(max(later)+timedelta(days=1)),".\\run settle",False))
    rows.append(("Scan for %s markets"%dstr(nd),"In the evening, before %s"%when(dstart(nd).astimezone().replace(tzinfo=None)),".\\run scan",False))
    return nd,rows
def newest(path):
    try: fs=[f.stat().st_mtime for f in os.scandir(path) if f.is_file() and f.name.lower().endswith(".db")]
    except OSError: return None,0
    return (max(fs) if fs else None),len(fs)
def backups():
    dbm=os.path.getmtime(DB) if os.path.exists(DB) else 0; parts=[]; missing=stale=False; newest_all=0
    for label,path in (("backups","backups"),(os.path.join(*Path(OFFSITE).parts[-2:]),OFFSITE)):
        m,n=newest(path)
        if not m: parts.append("none in %s"%e(label)); missing=True; continue
        parts.append("%d in %s"%(n,e(label))); newest_all=max(newest_all,m)
        if m<dbm-5: stale=True
    detail=", ".join(parts)+(". Newest %s."%when(loc(newest_all)) if newest_all else ".")
    if missing: return "warn","Missing",detail+" Back up paper.db, including the off-folder copy, before the next scan."
    if stale: return "warn","Behind",detail+" paper.db has changed since then."
    return "ok","Up to date",detail
def rules_tile(rw,ra):
    """Settlement-rules watch from shadow.py: has a market's station or wording changed?"""
    if not rw: return '<div><dt>Market rules</dt><dd>Not checked yet</dd><p>Checked at each evening scan: the station each market settles on, and its wording.</p></div>'
    last=max(r.get("last_seen") or 0 for r in rw); wk=datetime.now().timestamp()-7*86400
    rec=[r for r in ra if (r.get("ts") or 0)>=wk]
    if rec:
        notes="; ".join(sorted({"%s %s: %s"%(r["series"],(r["key"] or "").replace("station:","").replace("wording:","wording "),r["note"]) for r in rec}))
        return '<div><dt>Market rules</dt><dd class=warn><span class=ic aria-hidden=true>!</span>Changed</dd><p>%s. Check before trusting those markets.</p></div>'%e(notes)
    return '<div><dt>Market rules</dt><dd class=ok><span class=ic aria-hidden=true>✓</span>Unchanged</dd><p>Stations and wording match what the bot assumes. Checked %s.</p></div>'%when(loc(last))
def backtest_panel(v4p=()):
    """Summary of research/backtest.py (past Kalshi rain markets). Empty string until it has run."""
    try: r=json.load(open(os.path.join("research","results","rain_backtest.json"),encoding="utf-8"))
    except (OSError,ValueError): return ""
    h=r["holdout"]; vm=r["vs_market"]; b=r["brier"]; tk=r["trading"]["taker"]; mk=r["trading"]["maker"]; cm=vm["C"]
    acc=("The airport forecast scored clearly better than Kalshi&#8217;s prices" if cm["clear"] else
         "The airport forecast scored slightly better than Kalshi&#8217;s prices, but within the day-to-day noise" if cm["mean"]<0 else
         "Kalshi&#8217;s prices were as accurate as the airport forecast")
    if r["verdict"].startswith("edge"): say="On past data the airport forecast beat Kalshi&#8217;s prices by a clear margin and paper trading made money after fees. That is evidence, not proof: it still has to hold up live."
    else:
        say=acc+", so by the rules set in advance no edge is demonstrated."
        if mk.get("clear") or tk.get("clear"): say+=" One lead: %s on the bot&#8217;s blend made money on past markets. It was the best of several looks, so after allowing for that it is at best a 3&ndash;6&cent; edge, and paper fills flatter it. It is being re-tested on new markets before anyone trusts it."%("limit orders" if mk.get("clear") else "paying the ask")
        else: say+=" Paper trading on it would not have made money reliably."
    pc=lambda v:(fpts(100*v["per_contract"])+"&cent;") if v.get("n") else "\u2013"
    tiles=statrow([("Markets tested","{:,}".format(h["markets"]),"%d market days, %s to %s"%(h["days"],dstr(datetime.strptime(h["first"],"%Y-%m-%d")),dstr(datetime.strptime(h["last"],"%Y-%m-%d"))),""),
                   ("Airport forecast","%.3f"%b["C"],"Brier score; market %.3f"%b["M"],"pos" if cm["clear"] else ""),
                   ("Paying the ask",pc(tk),("a contract over %d trades; %s"%(tk["n"],"clear of the noise" if tk.get("clear") else "within the noise")) if tk.get("n") else "no trades",sgn(tk.get("per_contract") or 0) if tk.get("clear") else ""),
                   ("Limit orders",pc(mk),("a contract over %d fills of %d tried; %s"%(mk["n"],mk.get("attempts",0),"clear of the noise" if mk.get("clear") else "within the noise")) if mk.get("n") else "%d tried, none filled"%mk.get("attempts",0),sgn(mk.get("per_contract") or 0) if mk.get("clear") else "")])
    rows=[[lab,"%.4f"%b[k],"<span%s>%s</span>"%(tip("Lead %+.4f per market; noise (2 standard errors over %d days) %.4f"%(-vm[k]["mean"],vm[k]["days"],2*vm[k]["se"])),("%+.4f"%(-vm[k]["mean"])).replace("-","\u2212")),
           ('<span class="tag %s">%s</span>'%(("won","Yes") if vm[k]["clear"] else ("excluded","No")),"")]
          for k,lab in (("R","Airport, raw"),("C","Airport, calibrated"),("B","Bot&#8217;s blend"))]
    rows.insert(0,["Market price","%.4f"%b["M"],"",""])
    fw=[]
    for kind,lab in (("maker","Limit orders, live"),("taker","Paying the ask, live")):
        ks=[x for x in v4p if x.get("kind")==kind]; done=[x for x in ks if x.get("filled") and x.get("pnl") is not None]
        days=len({mdate(x["ticker"]) for x in done})
        if done: fw.append((lab,fpts(100*mean([x["pnl"] for x in done]))+"&cent;","a contract over %s%s, %s"%(s_(len(done),"fill" if kind=="maker" else "trade"),(" of %d orders"%len(ks)) if kind=="maker" else "",s_(days,"market day")),sgn(mean([x["pnl"] for x in done]))))
        else: fw.append((lab,"\u2013","%s so far; results start after the Oct 15 markets settle"%s_(len(ks),"order" if kind=="maker" else "signal"),""))
    fwd=('<h3 class=fwh>Forward test on new markets <span>same rules; dropped at 60 market days if not ahead, verdict at 110</span></h3>'+statrow(fw))
    return ('<section class="panel bt"><h2>Past-data test <span>research only, never part of the gate</span></h2><p class=lead>%s</p>%s%s'
            '<p class=note>Kalshi&#8217;s own prices at 8:55 PM the evening before each market day, against the airport forecast that was available then. '
            'The calibration was fitted on July 2025 to June 2026 only, and these markets were scored once, by a plan written before any data was fetched '
            '(research/PLAN.md). It tests the next-version candidate, not the bot&#8217;s current model. Cities share weather, so the real sample is the %d days, '
            'not the market count. Lead = how much lower the forecast&#8217;s Brier score is than the market&#8217;s, per market; clear = at least twice the day-to-day noise.</p>%s</section>')%(
            say,tiles+table(["Forecast","Brier","Lead","Clear?"],rows,num=(1,2)),fwd,h["days"],plan2_block())
def live_tile():
    """Kalshi account tile (live.py's ledger, live.db), read-only. Added 2026-10-14 with live.py."""
    p=os.getenv("LIVE_DB",os.path.join(os.path.dirname(os.path.abspath(DB)),"live.db"))   # next to paper.db, as live.py finds it when run from this folder
    lock=("Real money locked until %s, then your call (<code>.\\run live unlock</code>)."%dstr(STOP)) if date.today()<STOP else "Real money stays locked until you run <code>.\\run live unlock</code>."
    if not os.path.exists(p):
        return '<div><dt>Kalshi account</dt><dd>Not connected</dd><p>Paper only so far. Demo account first (fake money): <code>.\\run live setup</code>. %s</p></div>'%lock
    try:
        c=sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True)
        rows=c.execute("select env,status,fill_count,cost,fees,pnl,settled_ts,result from orders").fetchall()
        ev=c.execute("select env,kind from events where kind in ('unlock','lock') and env='prod' order by id desc limit 1").fetchone()
        nsetup=c.execute("select count(*) from events where kind='setup'").fetchone()[0]; c.close()
    except Exception as ex: return '<div><dt>Kalshi account</dt><dd class=neg>Unreadable</dd><p>%s</p></div>'%e(str(ex))
    if not rows and not nsetup:
        return '<div><dt>Kalshi account</dt><dd>Not connected</dd><p>Paper only so far. Demo account first (fake money): <code>.\\run live setup</code>. %s</p></div>'%lock
    out=[]
    for env,lab in (("prod","Real"),("demo","Demo")):
        r=[x for x in rows if x[0]==env and x[1] not in ("skipped","rejected","not placed")]
        if not r: continue
        net=sum(x[5] or 0 for x in r if x[6]); opn=sum((x[3] or 0)+(x[4] or 0) for x in r if (x[2] or 0)>0 and x[7] is None)
        out.append((lab,"%s: %s, %d contracts, open %s, settled %s"%(lab,s_(len(r),"order"),sum(x[2] or 0 for x in r),usd(opn),plus(net)),net))
    unl=ev is not None and ev[1]=="unlock" and date.today()>=STOP
    head=("%s <small>settled, %s</small>"%(plus(out[0][2]),"real money" if out[0][0]=="Real" else "demo, fake money")) if out else "Connected"
    detail=" ".join(x[1]+"." for x in out) or "No orders yet."
    return '<div><dt>Kalshi account</dt><dd class="%s">%s</dd><p>%s %s At most $25 at risk at once.</p></div>'%(
        "neg" if out and out[0][2]<-0.004 else ("pos" if out and out[0][2]>0.004 else ""),head,e(detail),
        ("Real money is unlocked, but the kill switch halts all orders." if killed() else
         "<b class=neg>Real money is unlocked.</b> Orders go out while the exchange is set to prod (<code>.\\run live status</code> shows it). Stop: <code>.\\run live lock</code>.") if unl else lock)
def plan2_block():
    """Summary of research/backtest2.py (temperature, overnight drift, later scan). Empty until it has run."""
    try: r=json.load(open(os.path.join("research","results","plan2.json"),encoding="utf-8"))
    except (OSError,ValueError): return ""
    A=r["A_temperature"]; tk=A["trading"]["taker"]; mk=A["trading"]["maker"]; B=r["B_drift"]; Cl=r["C_later"]
    pc=lambda v:(fpts(100*v["per_contract"])+"&cent;") if v.get("n") else "\u2013"
    lead=("Nothing in these three tests beat the market." if not r["clear_results"] else
          "Clear on past data, so only re-tested forward: %s."%e(", ".join(r["clear_results"])))
    def later_txt(k):
        v=Cl[k]
        return ("%s: %s a market day (2 SE %.1f&cent;)"%(k,fpts(100*v["diff_day_mean"])+"&cent;",200*v["diff_day_se"])) if "diff_day_mean" in v else "%s: not enough data"%k
    tiles=statrow([("Temperature markets","%.3f"%A["brier"]["F"],"Brier of the weather-service model; market %.3f (lower wins). %s markets, %d days"%(A["brier"]["M"],"{:,}".format(A["markets"]),A["days"]),""),
                   ("Temperature trades",pc(tk),"a contract paying the ask over {:,} trades; limit orders {}".format(tk.get("n",0),pc(mk)),""),
                   ("Overnight drift",pc(B["rain"]["taker"]),"a contract on rain (buy at 8:55 PM, sell at midnight); temperature %s"%pc(B["temperature"]["taker"]),""),
                   ("Scanning later","No better","11:30 PM vs 8:55 PM, limit orders: "+"; ".join(later_txt(k) for k in ("rain","temperature")),"")])
    return ('<div class=p2><h3 class=fwh>More past-data tests, Oct 14 <span>temperature, overnight drift, later scan (research/PLAN2.md)</span></h3><p class=note>%s '
            'Kalshi&#8217;s temperature prices were clearly more accurate than the weather service&#8217;s station forecast, so trading temperature on that forecast lost money. '
            'Several questions were asked at once, which makes a lucky &#8220;clear&#8221; more likely; none was clear.</p>%s</div>')%(lead,tiles)
def results(st):
    if not st: return '<p class=empty>Appears after the first paper trades settle. A rain trade settles the afternoon after its market day ends.</p>'
    w=[r for r in st if won(r)]; lo=[r for r in st if not won(r)]
    gn=sum(r["pnl"] or 0 for r in w); ls=sum(r["pnl"] or 0 for r in lo); net=gn+ls; nc=sum(r["n"] or 0 for r in st)
    sign=lambda x:"pos" if x>0.004 else ("neg" if x<-0.004 else "")
    cells=[("Win rate",pct(len(w)/float(len(st))),"%d won, %d lost"%(len(w),len(lo)),""),
           ("Gains",plus(gn),"from "+s_(len(w),"winning trade"),sign(gn)),
           ("Losses",usd(ls),"from "+s_(len(lo),"losing trade"),sign(ls)),
           ("Net",plus(net),"after approximate fees",sign(net))]
    out='<div class=stats>'+"".join('<div><span class=sl>%s</span><b class="sv %s">%s</b><small>%s</small></div>'%(a,c,b,d) for a,b,d,c in cells)+'</div>'
    if nc:
        be=sum((r["cost"] or 0)+(r["fee"] or 0) for r in st)/nc
        out+='<p class=note>At the prices paid so far (about %d&cent; a contract with fees), trades need to win about %s of the time just to break even, so the win rate alone can mislead. Net P&amp;L after fees is what counts.</p>'%(round(be*100),pct(be))
    groups=[("Rain (%s gate)"%e(GV),[r for r in st if r["version"]==GV and r["mtype"]=="rain"]),("Temperature",[r for r in st if r["mtype"]=="temp"]),
            ("Rain, older versions",[r for r in st if r["mtype"]=="rain" and r["version"]!=GV]),("All trades",st)]
    rows=[]
    for lab,rs in groups:
        if not rs: continue
        ww=[r for r in rs if won(r)]; a=sum(r["pnl"] or 0 for r in ww); b=sum(r["pnl"] or 0 for r in rs if not won(r))
        rows.append([lab,str(len(rs)),str(len(ww)),str(len(rs)-len(ww)),pct(len(ww)/float(len(rs))),(plus(a),"pos" if a>0.004 else ""),(usd(b),"neg" if b<-0.004 else ""),(plus(a+b),sign(a+b))])
    return out+table(["Type","Trades","Won","Lost","Win rate","Gains","Losses","Net"],rows,num=(1,2,3,4,5,6,7))
def dumbbell(rows):
    if not rows: return "<p class=empty>No %s rain markets logged yet. Run a scan before a market's day begins.</p>"%e(GV)
    thr=EDGE/BLEND*100 if BLEND else 100
    L,W,R,RH,T=64,520,118,26,28; H=T+RH*len(rows)+8; X=lambda p:L+p*W
    s=['<svg viewBox="0 0 %d %d" role="img" aria-label="Forecast and market price for each rain market">'%(L+W+R,H)]
    for gp in (0,.25,.5,.75,1):
        s.append('<line class=grid x1="%.1f" x2="%.1f" y1="%d" y2="%d"/><text class=ax x="%.1f" y="%d" text-anchor="middle">%d%%</text>'%(X(gp),X(gp),T-8,H-2,X(gp),T-14,gp*100))
    s.append('<text class=ax x="%d" y="%d" text-anchor="end">gap</text><text class=ax x="%d" y="%d" text-anchor="middle">result</text>'%(L+W+56,T-14,L+W+94,T-14))
    for i,r in enumerate(rows):
        y=T+RH*i+RH/2; fc,md=r["fc"],r["mid"]; gap=(fc-md)*100; gi=int(round(gap)); res=r.get("result")
        big=abs(gap)>=25; cand=abs(gap)>=thr and not big
        st=" (%s)"%r["station"] if r.get("station") else ""
        t="%s%s: forecast %s, market %s, gap %+.1f points, %s%s"%(city(r["ticker"]),st,pct(fc),pct(md),gap,("result "+res.upper()) if res in ("yes","no") else "not settled yet",
          ". A gap this big usually means a data or definition problem, not an edge." if big else (". Big enough to trade if the bid/ask spread is tight." if cand else ""))
        s.append('<g class=row%s><rect class=hit x=0 y="%.1f" width="%d" height="%d"/>'%(tip(t),y-RH/2,L+W+R,RH))
        s.append('<text class=lb x="%d" y="%.1f" text-anchor="end">%s</text>'%(L-12,y+4,e(city(r["ticker"]))))
        s.append('<line class=link x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'%(X(fc),X(md),y,y))
        s.append('<circle class=mk cx="%.1f" cy="%.1f" r="5"/><circle class=fc cx="%.1f" cy="%.1f" r="5"/>'%(X(md),y,X(fc),y))
        lab=(("%+d"%gi).replace("-","−") if gi else "0")+(" ⚠" if big else "")
        s.append('<text class="gap%s" x="%d" y="%.1f" text-anchor="end">%s</text>'%(" warn" if big else (" cand" if cand else ""),L+W+56,y+4,lab))
        s.append('<text class="res%s" x="%d" y="%.1f" text-anchor="middle">%s</text></g>'%("" if res in ("yes","no") else " p",L+W+94,y+4,res.upper() if res in ("yes","no") else "–"))
    s.append("</svg>")
    return "".join(s)
def brier_view(bf,bm,n,mg):
    if bf is None: return "<p class=empty>No resolved %s rain markets yet. The first ones resolve after their day ends.</p>"%e(GV)
    top=max(0.30,max(bf,bm)*1.15); ref=0.25/top*100; out="<div class=bars>"
    for name,v,cl in (("NWS forecast",bf,"fc"),("Market price",bm,"mk")):
        out+='<div class=bar%s><span class=bl>%s</span><div class=track><i class=%s style="width:%.1f%%"></i><b class=refm style="left:%.1f%%"></b></div><span class=bv>%.3f</span></div>'%(
            tip("%s: Brier %.3f over %d markets (lower is better)"%(name,v,n)),name,cl,v/top*100,ref,v)
    lead="The forecast is ahead" if bf<bm else "The market is ahead"
    if mg is None: m=" The gate also needs the lead to be clear of day-to-day noise, judged once on %s (needs 5+ market days)."%dstr(STOP)
    else: m=" Counting each market day once, the forecast&#8217;s lead is %.3f against a bar of %.3f (%.2f standard errors): %s. The gate looks once, on %s, because checking every day would let luck through more often."%(-mg[0],tcrit(mg[2])*mg[1],tcrit(mg[2]),"clear so far" if clear(mg) else "not clear",dstr(STOP))
    return out+"</div><p class=note>%s over %d resolved markets. Lower is better. The thin line marks 0.25, the score for always guessing 50%%.%s Early samples are noise.</p>"%(lead,n,m)
def statrow(cells): return '<div class=stats>'+"".join('<div><span class=sl>%s</span><b class="sv %s">%s</b><small>%s</small></div>'%(a,c,b,d) for a,b,d,c in cells)+'</div>'
def sgn(x,eps=0.004): return "pos" if x>eps else ("neg" if x<-eps else "")
def fpts(x): return ("%+.1f"%x).replace("-","−")
def shadow_view(so,sm,tr,v4=(),obs=()):
    """Shadow tests from shadow.py: research only, never part of the gate."""
    thr=EDGE/BLEND if BLEND else 1.0
    mv=[r for r in sm if r.get("status")=="ok" and None not in (r.get("mid_start"),r.get("mid_scan"),r.get("fc")) and r["version"]==GV and r["mtype"]=="rain"]
    for r in mv:
        r["gap"]=r["fc"]-r["mid_scan"]; r["tw"]=(r["mid_start"]-r["mid_scan"])*(1 if r["gap"]>0 else -1)
    big=[r for r in mv if abs(r["gap"])>=0.05]
    if not mv: a='<p class=empty>Measured from Kalshi&#8217;s price history at each afternoon settle, once a market&#8217;s day has started. Nothing measured yet.</p>'
    else:
        avg=sum(r["tw"] for r in big)/len(big)*100 if big else None
        cells=[("Toward the forecast",("%d <small>of %d</small>"%(sum(r["tw"]>0.004 for r in big),len(big))) if big else "–","markets with a gap of 5+ points",""),
               ("Average move",fpts(avg) if big else "–","points toward the forecast",sgn(avg or 0,0.05)),
               ("Measured",str(len(mv)),"%s rain markets"%e(GV),"")]
        ms={r["ticker"]:r["mid_start"] for r in mv}
        cl=[((ms[r["ticker"]] if r["side"]=="yes" else 1-ms[r["ticker"]])-r["price"])*100 for r in tr if r["version"]==GV and r["ticker"] in ms and r.get("price") is not None]
        if cl: cells.append(("Main bot&#8217;s trades",fpts(sum(cl)/len(cl))+"&cent;","day-start value vs price paid, %s"%s_(len(cl),"trade"),sgn(sum(cl)/len(cl),0.05)))
        a=statrow(cells); rows=[]
        for lo,hi,lab in ((0.05,0.10,"5–10 pts"),(0.10,thr,"10–%d pts"%round(thr*100)),(thr,9,"%d+ pts"%round(thr*100))):
            rs=[r for r in big if lo<=abs(r["gap"])<hi]
            if not rs: continue
            m=sum(r["tw"] for r in rs)/len(rs)*100
            rows.append([lab,str(len(rs)),str(sum(r["tw"]>0.004 for r in rs)),str(sum(r["tw"]<-0.004 for r in rs)),(fpts(m),sgn(m,0.05))])
        a+=table(["Gap at scan","Markets","Toward","Away","Avg move"],rows,"No market has differed from the forecast by 5 or more points yet.",num=(1,2,3,4))
    a+=('<p class=note>Compares each market&#8217;s mid price when we scanned with its mid when the market&#8217;s day started, in points toward the forecast '
        '(below zero means away). A noisy evening price tends to drift back toward any sensible forecast, so movement toward the forecast alone does not prove it knows more; the money tests decide.</p>')
    now=datetime.now(timezone.utc).timestamp()
    mo=[r for r in so if (r.get("strategy") or "maker")=="maker"]
    if not mo: b='<p class=empty>Each evening scan also places hypothetical limit orders on a separate $%d paper ledger. None yet.</p>'%round(BANK)
    else:
        stl=[r for r in mo if r.get("status")=="settled"]; fil=[r for r in mo if r.get("status") in ("filled","settled")]
        dec=[r for r in mo if r.get("status") in ("filled","settled","unfilled")]; rest=[r for r in mo if r.get("status")=="pending"]
        w=[r for r in stl if r.get("result")==r.get("side")]; pnl=sum(r.get("pnl") or 0 for r in stl)
        mst=[r for r in tr if r.get("status")=="settled" and r["version"]==GV]; mp=sum(r.get("pnl") or 0 for r in mst)
        b=statrow([("Orders",str(len(mo)),("%d resting now"%len(rest)) if rest else "placed so far",""),
                   ("Filled",("%d <small>of %d</small>"%(len(fil),len(dec))) if dec else "–",("fill rate "+pct(len(fil)/float(len(dec)))) if dec else "decided when each day starts",""),
                   ("Win rate",pct(len(w)/float(len(stl))) if stl else "–",("%d won, %d lost"%(len(w),len(stl)-len(w))) if stl else "after filled orders settle",""),
                   ("Net P&amp;L",plus(pnl) if stl else "–","main bot: %s"%plus(mp),sgn(pnl) if stl else "")])
        rows=[]
        for r in sorted(mo,key=lambda r:-(r.get("ts") or 0))[:12]:
            st=r.get("status"); d=mdate(r["ticker"])
            if st=="settled": tg=("won","Won") if r.get("result")==r.get("side") else ("lost","Lost")
            elif st=="filled": tg=("filled","Filled")
            elif st=="unfilled": tg=("excluded","Not filled")
            else: tg=("rest","Resting") if (r.get("cancel_ts") or 0)>now else ("rest","Checked at settle")
            pl=(plus(r["pnl"]),sgn(r["pnl"])) if st=="settled" and r.get("pnl") is not None else "–"
            q="1¢ better than the best bid" if r.get("improved") else "joined the best bid"
            rows.append(["%s <small>%s</small>"%(e(city(r["ticker"])),dstr(d) if d else ""),
                         '<span%s>%s %d at %d&cent;</span>'%(tip("%s: %d contracts at %d¢, %s, fair value %d¢"%(city(r["ticker"]),r.get("n") or 0,round((r.get("price") or 0)*100),q,round((r.get("fair") or 0)*100))),
                                                          e((r.get("side") or "").upper()),r.get("n") or 0,round((r.get("price") or 0)*100)),
                         '<span class="tag %s">%s</span>'%tg,pl])
        b+=table(["Market","Order","Status","P&amp;L"],rows,num=(3,))
        imp=[r for r in dec if r.get("improved")]; jn=[r for r in dec if not r.get("improved")]
        fr=lambda rs:"%d of %d"%(sum(r.get("status") in ("filled","settled") for r in rs),len(rs))
        if dec: b+='<p class=note>Filled by queue position: 1&cent; better than the best bid %s, joined the best bid %s.</p>'%(fr(imp),fr(jn))
    b+=('<p class=note>Same forecasts, blend, %d-point edge and size limits as the main bot, on its own hypothetical $%d. Instead of paying the ask it rests a limit order '
        '1&cent; better than the best bid (or joins the best bid when the spread is 1&cent;) and cancels it when the market&#8217;s day starts. It counts as filled only if Kalshi&#8217;s '
        'minute-by-minute history shows a trade or an offer reaching that price after the order, or going through it when the order only joined the queue. Makers pay no Kalshi fee on '
        'weather markets. Read the fill rate with the win rate: resting orders tend to fill when the price moves against them.</p>')%(round(EDGE*100),round(BANK))
    rs=[r for r in v4 if r.get("result") in ("yes","no") and None not in (r.get("fc"),r.get("mid"),r.get("bid"),r.get("ask")) and r["ask"]-r["bid"]<=0.06+1e-9]
    if not v4: c4='<p class=empty>Starts with the next evening scan: a forecast made for the exact airport each rain market settles on (the National Blend of Models), calibrated on a year of history, logged for every rain market.</p>'
    elif not rs: c4='<p class=empty>%s logged so far. The first results come the afternoon after their market day.</p>'%s_(len(v4),"forecast")
    else:
        y=lambda r:1.0 if r["result"]=="yes" else 0.0; bs=lambda k,xs:mean([(x[k]-y(x))**2 for x in xs])
        o3={x["ticker"]:x["fc"] for x in obs if x["version"]==GV and x.get("fc") is not None}
        both=[dict(r,v3=o3[r["ticker"]]) for r in rs if r["ticker"] in o3]; mg=margin(rs)
        bv,bm=bs("fc",rs),bs("mid",rs)
        c4=statrow([("Resolved",str(len(rs)),"rain markets",""),
                    ("Airport forecast","%.3f"%bv,"Brier score; market %.3f"%bm,"pos" if bv<bm else ""),
                    ("Current model (v3)",("%.3f"%bs("v3",both)) if both else "\u2013",("on the same %s; airport forecast %.3f"%(s_(len(both),"market"),bs("fc",both))) if both else "no shared markets yet",""),
                    ("Clear margin",("Yes" if clear(mg) else "Not yet") if mg else "\u2013","vs the market, needs 5+ market days" if not mg else "lead %.3f vs bar %.3f"%(-mg[0],tcrit(mg[2])*mg[1]),"")])
    c4+=('<p class=note>The candidate for a future version: the National Blend of Models forecast for the airport named in each market&#8217;s rules, '
         'calibrated on July 2025 to June 2026 and then frozen. Lower Brier is better. It never trades and never counts toward the gate; switching the bot to it needs your go-ahead and a fresh test.</p>')
    return ('<section class="panel shadow"><h2>Shadow tests <span>research only, never part of the gate</span></h2>'
            '<div class=sub><h3>Do prices move toward the forecast?</h3>%s</div><div class=sub><h3>Limit orders instead of paying the ask</h3>%s</div>'
            '<div class=sub><h3>Airport forecast (candidate for the next version)</h3>%s</div></section>')%(a,b,c4)
def read_marks(path="marks.jsonl",now=None):
    """Price snapshots from marks.py, oldest first: all of the last 48 hours, one per hour before that (keeps the page
    small). Unreadable lines are skipped; no file means no live prices."""
    now=now or datetime.now().timestamp(); out=[]; hours=set()
    try: lines=open(path,encoding="utf-8").read().splitlines()
    except OSError: return []
    rows=[]
    for ln in lines:
        try:
            x=json.loads(ln)
            if isinstance(x,dict) and isinstance(x.get("ts"),(int,float)) and isinstance(x.get("marks"),dict): rows.append(x)
        except ValueError: continue
    rows.sort(key=lambda x:x["ts"])
    for x in rows:
        if x["ts"]>now+60: continue
        if x["ts"]<now-48*3600:
            h=int(x["ts"]//3600)
            if h in hours: continue
            hours.add(h)
        out.append(x)
    return out
# ---------- page assembly: read (read-only I/O) -> numbers -> HTML -> atomic write ----------
def read_db(db=None):
    """Every table the page shows, from paper.db opened read-only. Exits with a message if the file cannot be opened."""
    db=db or DB
    try:
        c=sqlite3.connect(Path(db).resolve().as_uri()+"?mode=ro",uri=True)
        D={t:load(c,t) for t in ("obs","trades","shadow_orders","shadow_moves","rules_watch","rules_alerts","v4_obs","v4_paper","gate_look")}
        AU={t:load(c,t) for t in ("scans","scan_ends","decision_events","market_results")}
        # decisions grow by about 300 rows a scan: the page needs the last few days and every trade's own row
        AU["decisions"]=load(c,"decisions","where ts>=? or trade_ref is not null",(datetime.now().timestamp()-4*86400,)) if AU["scans"] else []
        AU["decisions_total"]=c.execute("select count(*) from decisions").fetchone()[0] if AU["scans"] else 0; c.close()
    except Exception as ex: sys.exit("Cannot open %s read-only: %s"%(db,ex))
    D["audit"]=AU
    return D
def read_research():
    """(last market-structure run, research summaries, PLAN5 L sample count): text read for display, never acted on."""
    sr=[]
    try: sr=[json.loads(x) for x in open(os.path.join("research","data","structure","runs.jsonl"),encoding="utf-8").read().splitlines()[-1:]]
    except (OSError,ValueError): pass
    notes=[]; lip_n=None
    for f,_ in (CV.RESEARCH_FILES if CV else ()):
        p=os.path.join("research","results",f)
        try:
            al=[x.strip() for x in open(p,encoding="utf-8").read().splitlines() if x.strip() and not x.startswith(("#","|"))]
            txt=al[:4]+([al[-1]] if len(al)>4 else [])   # the first lines and the closing caveat
            notes.append((f,os.path.getmtime(p),txt))
        except OSError: pass
    try:
        with open(os.path.join("research","data","lip","MOVED.txt"),encoding="utf-8") as fh:   # sampling moved to GitHub (2026-10-28)
            lip_n=(fh.read().strip().splitlines() or ["sampled elsewhere"])[0]
    except OSError:
        for f in sorted(glob.glob(os.path.join("research","data","lip","samples*.jsonl"))):   # samples.jsonl and the daily files (2026-10-28)
            try:
                with open(f,encoding="utf-8") as fh: lip_n=(lip_n or 0)+sum(1 for _ in fh)
            except OSError: pass
    return sr,notes,lip_n
def last_scan_line(obs,tr):
    last=max([r["ts"] or 0 for r in obs] or [0])
    if not last: return "No scan yet."
    b=[r for r in obs if (r["ts"] or 0)>=last-900]; bt=[r for r in tr if (r["ts"] or 0)>=last-900]; nr=sum(r["mtype"]=="rain" for r in b)
    return "Last scan %s logged %s (%d rain, %d temperature) and opened %s."%(when(loc(last)),s_(len(b),"market"),nr,len(b)-nr,"no paper trades" if not bt else s_(len(bt),"paper trade"))
def money_panel(ocost,capusd,allpnl,today,stopped,kill,rw,ra):
    bcls,btitle,bdetail=backups()
    return ('<dl class=facts>'
           '<div><dt>Open positions</dt><dd>%s <small>of %s cap</small></dd>%s<p>%s of the bankroll can be in open trades at once.</p></div>'
           '<div><dt>Paper P&amp;L, all trades</dt><dd class="%s">%s</dd><p>%s</p></div>'
           '<div><dt>Backups</dt><dd class="%s"><span class=ic aria-hidden=true>%s</span>%s</dd><p>%s</p></div>'
           '<div><dt>Kill switch</dt><dd class="%s">%s</dd><p>%s</p></div>%s%s</dl>')%(
           usd(ocost),usd(capusd),meter(ocost/capusd if capusd else 0,ocost>capusd+1e-9),pct(CAP),
           "pos" if allpnl>0.004 else ("neg" if allpnl<-0.004 else ""),plus(allpnl),("<b class=neg>Daily stop on.</b> The last 24 hours lost %s, past the %s limit, so new paper trades pause for about a day. Markets are still logged."%(usd(-today),usd(BANK*DLL))) if stopped else
           ("Last 24 hours %s. At %s new paper trades pause for a day; markets are still logged."%(plus(today),usd(-BANK*DLL))),
           bcls,"✓" if bcls=="ok" else "!",btitle,bdetail,
           "neg" if kill else "","On: the bot is halted" if kill else "Off",("No scans, paper trades or Kalshi orders. Resume: <code>.\\run unkill</code> (or delete %s)."%e(os.path.basename(kill_file() or "KILL"))) if kill else "Halt all trading: <code>.\\run kill</code> (or create a file named KILL in the tradebot folder).",live_tile(),rules_tile(rw,ra))
def latest_day(rain):
    """(market day, its rows by largest gap, subtitle, explanation, table) for the forecast-vs-market chart."""
    v3=[r for r in rain if r.get("fc") is not None and r.get("mid") is not None]
    lday=max([d for d in (mdate(r["ticker"]) for r in v3) if d] or [None]) if v3 else None
    lrows=sorted([r for r in v3 if mdate(r["ticker"])==lday],key=lambda r:-abs(r["fc"]-r["mid"]))
    nres=sum(r.get("result") in ("yes","no") for r in lrows); thr=EDGE/BLEND*100 if BLEND else 0
    dsub=("%s markets, %d cities. %s"%(dstr(lday),len(lrows),"All settled." if lrows and nres==len(lrows) else ("%d of %d settled."%(nres,len(lrows)) if nres else "Not settled yet."))) if lday else ""
    why=("A paper trade needs the blended value (%d%% forecast, %d%% market) to beat the price by %d or more points, so the forecast has to differ from the market by at least %d points plus the bid/ask spread. Bold gaps clear %d points; ⚠ marks 25 or more, which usually means a data problem."
         %(round(BLEND*100),round((1-BLEND)*100),round(EDGE*100),round(thr),round(thr)))
    if lrows: why+=" Largest gap for %s: %.1f points (%s)."%(dstr(lday),abs(lrows[0]["fc"]-lrows[0]["mid"])*100,e(city(lrows[0]["ticker"])))
    trows=[[e(city(r["ticker"])),e(r.get("station") or ""),pct(r["fc"]),pct(r["mid"]),("%+.1f"%((r["fc"]-r["mid"])*100)).replace("-","−"),(r.get("result") or "–").upper()] for r in lrows]
    chart_table=("<details><summary>Show these markets as a table</summary>%s</details>"%table(["City","Station","Forecast","Market","Gap (pts)","Result"],trows,num=(2,3,4))) if lrows else ""
    return lrows,dsub,why,chart_table
def record_rows(obs,tr,res,rg,st,op):
    """(calibration, open positions, recent settled trades, data by version) table rows."""
    bk={}
    for r in rg: bk.setdefault(min(int(r["fc"]*10),9),[]).append(r)
    cal_rows=[["%d–%d%%"%(b*10,b*10+10),str(len(v)),pct(sum(x["fc"] for x in v)/len(v)),pct(sum(x["result"]=="yes" for x in v)/len(v)),pct(sum(x["mid"] for x in v)/len(v))] for b,v in sorted(bk.items())]
    open_rows=[[e(r["ticker"]),e(r["version"]),r["side"].upper(),str(r["n"]),"$%.2f"%r["price"],pct(r["fair"]),usd((r["cost"] or 0)+(r["fee"] or 0))] for r in op]
    done_rows=[[e(r["ticker"]),e(r["version"]),r["side"].upper(),(r["result"] or "").upper(),('<span class="tag %s">%s</span>'%(("won","Won") if won(r) else ("lost","Lost")),""),(plus(r["pnl"] or 0),"pos" if (r["pnl"] or 0)>0 else "neg")] for r in sorted(st,key=lambda r:-(r["ts"] or 0))[:15]]
    ver_rows=[]
    for v in sorted({r["version"] for r in obs+tr}) or [GV]:
        for mt in ("rain","temp"):
            o=[r for r in obs if r["version"]==v and r["mtype"]==mt]
            if not o: continue
            rv=[r for r in res if r["version"]==v and r["mtype"]==mt]; sv=[r for r in st if r["version"]==v and r["mtype"]==mt]
            role="Gate" if (v==GV and mt=="rain") else ("Exploratory" if mt=="temp" else "Excluded")
            ver_rows.append(["%s %s"%(e(v),"rain" if mt=="rain" else "temperature"),'<span class="tag %s">%s</span>'%(role.lower(),role),str(len(o)),str(len(rv)),f3(brier(rv,"fc")),f3(brier(rv,"mid")),str(len(sv)),usd(sum(r["pnl"] or 0 for r in sv))])
    return cal_rows,open_rows,done_rows,ver_rows
def fresh_chip(rows):
    """A header chip when a freshness check failed or is stale (the page's own age is left out: it is being rebuilt)."""
    bad=[r for r in (rows or []) if r.get("key")!="page" and r.get("status") in ("stale","fail")]
    if not bad: return ""
    nf=sum(r["status"]=="fail" for r in bad)
    txt=", ".join(x for x in ("%d failed"%nf if nf else "","%d out of date"%(len(bad)-nf) if len(bad)>nf else "") if x)
    return '<a class="chip %s" href="#freshness" title="%s"><span aria-hidden=true>!</span> Data checks: %s</a>'%(
        "halt" if nf else "warn",e("; ".join(r["name"] for r in bad[:6]),quote=True),txt)
def status_chips(kill,live,stopped,AU,obs,ra,fresh=None):
    killchip='<span class="chip halt"><span aria-hidden=true>✕</span> Bot halted (kill switch)</span>' if kill else ""
    livechip='<span class="chip live" id=pricechip title="Prices of open paper trades and this page refresh every 5 minutes while run watch is open">Prices update every 5 min</span>' if live else ""
    if stopped and not kill: killchip='<span class="chip warn"><span aria-hidden=true>!</span> Daily loss stop: no new paper trades</span>'
    if not GATE_OK: killchip+='<span class="chip halt"><span aria-hidden=true>!</span> Gate rules unavailable: the gate is not judged on this page</span>'
    try:
        if CV and CV.blocked(dict(AU,obs=obs)): killchip+='<span class="chip halt"><span aria-hidden=true>!</span> Trades blocked: audit ledger</span>'
    except Exception as ex: print("ledger check failed:",ex)
    if [r for r in ra if (r.get("ts") or 0)>=datetime.now().timestamp()-7*86400]: killchip+='<span class="chip warn"><span aria-hidden=true>!</span> Market rules changed</span>'
    return killchip+fresh_chip(fresh)+livechip
def write_page(page,live):
    """Atomic write: a reader never sees a half-written page. run watch writes its own file, so the phone page is never
    the live one. One temp file per process, because scan, hourly and watch can overlap."""
    out=Path("dashboard_live.html" if live else "dashboard.html")
    tmp=out.with_name("%s.%d.tmp"%(out.stem,os.getpid())); tmp.write_text(page,encoding="utf-8")
    for k in range(5):   # an antivirus scan can hold the file a moment
        try: os.replace(str(tmp),str(out)); break
        except PermissionError:
            if k==4: raise
            import time as _t; _t.sleep(1+k)
    print("wrote",out.name)
    return out
def build_page(D,live=False):
    """The whole page as one HTML string, from read_db()'s tables. No writes."""
    obs,tr,so,sm,rw,ra,v4,v4p,AU=(D[k] for k in ("obs","trades","shadow_orders","shadow_moves","rules_watch","rules_alerts","v4_obs","v4_paper","audit"))
    res=[r for r in obs if r.get("result") in ("yes","no") and r.get("fc") is not None and r.get("mid") is not None]
    st=[r for r in tr if r.get("status")=="settled"]; op=[r for r in tr if r.get("status")=="open"]
    rain=[r for r in obs if r["version"]==GV and r["mtype"]=="rain"]
    rg=[r for r in res if r["version"]==GV and r["mtype"]=="rain"]; sg=[r for r in st if r["version"]==GV and r["mtype"]=="rain"]
    bf,bm=brier(rg,"fc"),brier(rg,"mid"); pnl=sum(r["pnl"] or 0 for r in sg); allpnl=sum(r["pnl"] or 0 for r in st)
    ocost=sum((r["cost"] or 0)+(r["fee"] or 0) for r in op); capusd=BANK*CAP
    now=datetime.now(timezone.utc)
    today=sum(r["pnl"] or 0 for r in st if (r.get("settled_ts") or 0)>=now.timestamp()-86400); kill=killed()   # core.killed: KILL, KILL.txt, any case, in this folder
    mg=margin(rg); stopped=today<=-BANK*DLL+1e-9   # the same daily stop as strategy.scan
    passed=final() and len(rg)>=100 and bf is not None and bf<bm and clear(mg) and len(sg)>=50 and pnl>0   # single look on the stop date
    look=[r for r in D.get("gate_look") or [] if r.get("stop_date")==str(STOP)]
    if final(): passed=bool(look[0]["passed"]) if look else False   # judged once (2026-10-28): only the look stored by strategy.py decides
    left=(STOP-date.today()).days
    gate,npass=gate_chips(rg,bf,bm,sg,pnl,left,mg)
    nd,todo=plan(obs)
    lastline=last_scan_line(obs,tr)
    todo_html="".join('<li class="%s"><div><b>%s</b><span>%s</span></div><code>%s</code></li>'%("due" if u else "",a,w_,c_) for a,w_,c_,u in todo)
    money=money_panel(ocost,capusd,allpnl,today,stopped,kill,rw,ra)
    lrows,dsub,why,chart_table=latest_day(rain)
    cal_rows,open_rows,done_rows,ver_rows=record_rows(obs,tr,res,rg,st,op)
    marks=[]   # read once for both views, and only when a view uses it; an unreadable file must not stop the page
    if AV or CV:
        try: marks=read_marks()
        except Exception as ex: print("live prices unreadable:",ex)
    fresh=None   # one read of every freshness check, for the chip and the control center
    if FR:
        try: fresh=FR.checks(root=os.getcwd(),db=os.path.abspath(DB))
        except Exception as ex: print("freshness check failed:",ex)
    acct=""
    if AV:
        try: acct=AV.section(tr,so,BANK,min([r["ts"] for r in obs+tr if r.get("ts")] or [now.timestamp()]),now.timestamp(),marks=marks,live=live)
        except Exception as ex: print("account view failed:",ex)
    ctl=""
    if CV:
        try:
            sr,notes,lip_n=read_research()
            ctl=CV.section(dict(AU,trades=tr,shadow_orders=so,obs=obs,v4_paper=v4p,v4_obs=v4,marks=marks,structure_runs=sr,research_notes=notes,lip_samples=lip_n,freshness=fresh),table,now.timestamp())
        except Exception as ex: print("control center failed:",ex)
    chips=status_chips(kill,live,stopped,AU,obs,ra,fresh)
    body=('<div class=wrap>'
      '<header class=top><div><h1>Tradebot</h1><p>Kalshi weather test on paper. Orders on a Kalshi account come only from live.py: demo (fake money) now, real money locked until Nov 11.</p></div>'
      '<div class=meta>%s<span>Updated %s</span></div></header>%s'
      '<section class=hero><p class=q>Does the NWS forecast beat Kalshi&#8217;s prices on rain markets?</p><p class=answer>%s</p>'
      '<div class=gatehead><span>Go-live gate, %s rain markets only</span><b>%d of 4 checks pass</b></div>%s%s</section>'
      '<div class=two><section class="panel"><h2>What to do next</h2><ol class=todo>%s</ol><p class=foot>%s Run commands from the tradebot folder.</p></section>'
      '<section class="panel"><h2>Money and safety</h2>%s</section></div>'
      '%s<section class=panel><h2>Win rate and P&amp;L <span>settled paper trades</span></h2>%s</section>'
      '<section class=panel><h2>Forecast vs market price <span>%s</span></h2>'
      '<p class=legend><span><i class=fc></i>NWS forecast</span><span><i class=mk></i>Market price (mid)</span></p><p class=swipe>Swipe sideways to see the whole chart, or open the table below it.</p><div class=chart>%s</div><p class=note>%s</p>%s</section>'
      '<section class=panel><h2>Score <span>%s rain, resolved markets</span></h2>%s</section>%s%s'
      '<section class="panel records"><h2>Calibration <span>%s rain</span></h2><p class=note>When the forecast says X%%, how often did it rain, and what did the market say?</p>%s'
      '<h2>Open paper positions</h2>%s<h2>Recent settled trades</h2>%s'
      '<details><summary>Data by estimator version</summary>%s</details></section>'
      '<p class=fine><b>Read with caution.</b> Early samples are noise. Cities share weather systems, so the effective sample is far smaller than the market count. Paper results ignore slippage and use approximate fees. The shadow tests are research only and never count toward the gate. Not financial advice. Data before Oct 13, 2026 was lost when the project folder was deleted; the test restarted that day.</p>'
      '</div><div id=tip role=tooltip></div>')%(
      chips,when(datetime.now(BOT_TZ))+" (UTC-4)",acct,verdict(rg,bf,bm,rain,passed,mg,look),e(GV),npass,gate,calendar(rain,nd),
      todo_html,lastline,money,backtest_panel(v4p),results(st),
      dsub,dumbbell(lrows),why,chart_table,
      e(GV),brier_view(bf,bm,len(rg),mg),shadow_view(so,sm,tr,v4,obs),ctl,
      e(GV),table(["Forecast","Markets","Avg forecast","Actual rain","Avg market"],cal_rows,"Appears after %s rain markets resolve."%e(GV),num=(1,2,3,4)),
      table(["Market","Ver","Side","Contracts","Price","Fair","Cost incl. fee"],open_rows,"No open paper positions.",num=(3,4,5,6)),
      table(["Market","Ver","Side","Result","Outcome","P&amp;L"],done_rows,"No settled trades yet.",num=(5,)),
      table(["Version and type","Role","Logged","Resolved","Brier forecast","Brier market","Settled trades","P&amp;L"],ver_rows,"Nothing yet.",num=(2,3,4,5,6,7)))
    return ('<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
          '<title>Tradebot Dashboard</title><style>'+CSS+(AV.ACCT_CSS if AV else "")+(CV.CSS if CV else "")+'</style></head><body'+(' data-live=1' if live else '')+'>'+body+'<script>'+JS+(AV.ACCT_JS if AV else "")+'</script></body></html>')
def main():
    live="--live" in sys.argv
    out=write_page(build_page(read_db(),live),live)
    if "--no-open" not in sys.argv: webbrowser.open(out.resolve().as_uri())

if __name__=="__main__": main()
