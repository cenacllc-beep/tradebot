"""Learning report: what is working and what is not, including every losing trade (added 2026-10-14 at the user's request:
"we need to identify patterns, even for the trades we lost, so we continuously learn what works and doesn't").
Read-only: opens paper.db and live.db in read-only mode and writes only research/results/learning.md (+ .json).

  python learn.py          live record: paper trades, the forecast-vs-market log, the limit-order test, the Kalshi account
  python learn.py --past   also the 1,711 past rain markets (research/data; slower)

Every settled trade gets a story, decided only from what was known when it was placed and how it ended:
  forecast beat the market   our side: forecast said likely (over 50%), market said unlikely; it happened
  market beat the forecast   our side: forecast said likely, market said unlikely; it did not happen
  favourite won / upset      forecast and market both said likely; it happened / did not
  long shot hit / missed     forecast and market both said unlikely; it happened / did not
Then wins, losses and profit per contract are broken down by side, price, edge size, city and story, next to what the
market price implied (a 30c contract should win about 30% of the time if the market is right).

Guards against fooling ourselves (CLAUDE.md sections 6 and 11a; statistics review 2026-10-14):
  - results are averaged by market day (cities on one day share weather), with standard errors across days;
  - groups under 30 trades, 10 market days or 4 weeks are "too few";
  - a group is flagged only if its profit after fees is away from zero AND away from the rest of its breakdown, each by
    the Student-t cutoff for G groups (Bonferroni, alpha 0.05/(2G), G = every group in this report that is not "too few"),
    and both still hold with weekly clusters (runs of similar weather across days);
  - the overall rows are never flagged here (each has its own plan); past-data items are tagged "[past, post-hoc]".
This report runs after every settle, so a flag is a screen, not a test: a pattern found here is a hypothesis. It may only
change the bot after a plan is written (research/PLAN3.md) and it holds on markets after the day it was found."""
import os, sys, json, sqlite3, math
from statistics import NormalDist
from pathlib import Path
from datetime import datetime
HERE=os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0,HERE)
from config import DB
OUTDIR=os.getenv("TRADEBOT_RESULTS") or os.path.join(HERE,"research","results")   # tests point this at a temporary folder
MIN_N,MIN_DAYS,MIN_WEEKS,ALPHA=30,10,4,0.05


def ro(path):
    p=path if os.path.isabs(path) else os.path.join(HERE,path)
    return sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True) if os.path.exists(p) else None
def rows(c,sql,args=()):
    try: cur=c.execute(sql,args); names=[d[0] for d in cur.description]; return [dict(zip(names,r)) for r in cur.fetchall()]
    except sqlite3.Error: return []
def city(t):
    p=t.split("-")
    return p[-1] if t.startswith("KXRAIN") else p[0].replace("KXHIGH","")
def mday(t):
    p=t.split("-"); return p[1] if len(p)>1 else "?"
def bucket(x,edges,labels):
    for e,l in zip(edges,labels):
        if x<e: return l
    return labels[-1]
def price_b(p): return bucket(p,[0.2,0.4,0.6,0.8],["under 20c","20-40c","40-60c","60-80c","80c+"])
def edge_b(e): return bucket(e,[0.12,0.2],["8-12 pts","12-20 pts","20+ pts"])
def story(fc_side,mkt_side,won):
    f,m=fc_side>0.5,mkt_side>0.5
    if f and not m: return "forecast beat the market" if won else "market beat the forecast"
    if f and m: return "favourite won" if won else "upset"
    if not f and not m: return "long shot hit" if won else "long shot missed"
    return "forecast doubted, market liked: won" if won else "forecast doubted, market liked: lost"

# ---------- Student-t without scipy (the PC has plain Python) ----------
def _betacf(a,b,x):
    """Continued fraction for the incomplete beta function (Numerical Recipes, betacf)."""
    tiny=1e-300; qab,qap,qam=a+b,a+1,a-1
    c=1.0; d=1-qab*x/qap; d=1/(d if abs(d)>tiny else tiny); h=d
    for m in range(1,300):
        m2=2*m
        for aa in (m*(b-m)*x/((qam+m2)*(a+m2)),-(a+m)*(qab+m)*x/((a+m2)*(qap+m2))):
            d=1+aa*d; d=1/(d if abs(d)>tiny else tiny)
            c=1+aa/c; c=c if abs(c)>tiny else tiny
            de=d*c; h*=de
        if abs(de-1)<3e-14: break
    return h
def betainc(a,b,x):
    if x<=0: return 0.0
    if x>=1: return 1.0
    lb=math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log(1-x)
    return math.exp(lb)*_betacf(a,b,x)/a if x<(a+1)/(a+b+2) else 1-math.exp(lb)*_betacf(b,a,1-x)/b
def tsf(t,df):
    """P(T > t) for Student-t with df degrees of freedom, t >= 0."""
    return 0.5*betainc(df/2,0.5,df/(df+t*t))
def tcrit(p,df):
    """The t value with upper-tail probability p."""
    lo,hi=0.0,1e3
    for _ in range(200):
        mid=(lo+hi)/2
        if tsf(mid,df)>p: lo=mid
        else: hi=mid
    return (lo+hi)/2

# ---------- day-averaged estimates with cluster-robust errors ----------
def as_date(day):
    for fmt in ("%y%b%d","%Y-%m-%d"):
        try: return datetime.strptime(str(day),fmt).date()
        except ValueError: pass
    return None
def week(day):
    d=as_date(day); return "%d-W%02d"%d.isocalendar()[:2] if d else str(day)
def daymeans(ts,f):
    by={}
    for t in ts: by.setdefault(t["day"],[]).append(f(t))
    return {k:sum(v)/len(v) for k,v in by.items()}
def level(ts,f):
    """Mean of the day means, and each day's influence on it (for the errors)."""
    a=daymeans(ts,f); D=len(a); m=sum(a.values())/D
    return m,{c:(v-m)/D for c,v in a.items()}
def versus(g,r,f):
    """Group minus the rest of its breakdown (each day-averaged), and each day's influence on that difference."""
    mg,ug=level(g,f); mr,ur=level(r,f); u=dict(ug)
    for c,v in ur.items(): u[c]=u.get(c,0)-v
    return mg-mr,u
def cse(u,key=None):
    """Cluster-robust standard error from day influences; clusters are days, or weeks with key=week."""
    s={}
    for c,v in u.items(): k=key(c) if key else c; s[k]=s.get(k,0)+v
    C=len(s)
    return (C/(C-1)*sum(v*v for v in s.values()))**0.5 if C>1 else None
def ratio(x,se):
    if se: return x/se
    if se==0 and x!=0: return math.copysign(float("inf"),x)   # identical results every day: not noise
    return None
def stats(ts,rest=None):
    """ts: list of dicts with day, win (0/1), price (paid for our side), pnl (profit per contract after fees), fair (the
    50/50 blend of forecast and market for our side, if known). The reading uses profit per contract AFTER fees, averaged
    within each market day first. rest: the other trades in the same breakdown (None for an overall row)."""
    n=len(ts)
    if not n: return None
    pnl=lambda t:t["pnl"]
    pm,u=level(ts,pnl); ex,_=level(ts,lambda t:t["win"]-t["price"]); nd=len(u); nw=len({week(c) for c in u})
    fk=[t["fair"] for t in ts if t.get("fair") is not None]
    s=dict(n=n,days=nd,weeks=nw,won=sum(t["win"] for t in ts),win_rate=sum(t["win"] for t in ts)/n,market_implied=sum(t["price"] for t in ts)/n,
           blend_said=(sum(fk)/len(fk)) if fk else None,profit=pm,profit_se=cse(u),profit_se_week=cse(u,week),excess=ex,overall=rest is None)
    s["t"]=ratio(pm,s["profit_se"]); s["t_week"]=ratio(pm,s["profit_se_week"])
    if rest:
        dv,uv=versus(ts,rest,pnl); s.update(vs_rest=dv,vs_rest_se=cse(uv),vs_rest_se_week=cse(uv,week),vs_rest_days=len(uv))
        s["t_vs_rest"]=ratio(dv,s["vs_rest_se"]); s["t_vs_rest_week"]=ratio(dv,s["vs_rest_se_week"])
    s["too_few"]=n<MIN_N or nd<MIN_DAYS or nw<MIN_WEEKS
    return s
def judge(s,G):
    """The reading, once G (the number of groups screened in this report) is known."""
    if s["too_few"]: return "too few"
    if s["overall"]: return "overall: judged by its own plan"
    p=ALPHA/(2*max(G,1)); zc=NormalDist().inv_cdf(1-p)
    t,tv,tw,tvw=s["t"],s.get("t_vs_rest"),s["t_week"],s.get("t_vs_rest_week")
    ok=(t is not None and tv is not None and tw is not None and tvw is not None and t*tv>0
        and abs(t)>=tcrit(p,s["days"]-1) and abs(tv)>=tcrit(p,s["vs_rest_days"]-1) and abs(tw)>=zc and abs(tvw)>=zc)
    return "worth a written test" if ok else "noise so far"

def table(title,ts,keyf,order=None):
    g={}
    for t in ts: g.setdefault(keyf(t),[]).append(t)
    keys=[k for k in (order or sorted(g,key=lambda k:-len(g[k]))) if k in g]
    return dict(title=title,groups={k:stats(g[k],[t for t in ts if keyf(t)!=k]) for k in keys})
def render_table(tb):
    L=["","### "+tb["title"],"","| Group | Trades | Days | Won | Win rate | Market implied | Blend said (50/50 forecast and market) | Edge over price (before fees) | Profit per contract after fees (+/- SE) | Vs rest of this breakdown (+/- SE) | Reading |",
       "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for k,s in tb["groups"].items():
        L.append("| %s | %d | %d | %d | %.0f%% | %.0f%% | %s | %+.1f pts | %+.1fc%s | %s | %s |"%(k,s["n"],s["days"],s["won"],100*s["win_rate"],100*s["market_implied"],
                 "%.0f%%"%(100*s["blend_said"]) if s["blend_said"] is not None else "-",100*s["excess"],100*s["profit"],(" +/- %.1f"%(100*s["profit_se"])) if s["profit_se"] else "",
                 ("%+.1fc%s"%(100*s["vs_rest"],(" +/- %.1f"%(100*s["vs_rest_se"])) if s["vs_rest_se"] else "")) if "vs_rest" in s else "-",s["verdict"]))
    return L
STORIES=["forecast beat the market","market beat the forecast","favourite won","upset","long shot hit","long shot missed","forecast doubted, market liked: won","forecast doubted, market liked: lost"]
SITUATIONS=["forecast said likely, market said unlikely","both said likely","both said unlikely","forecast said unlikely, market said likely"]
def situation(t):
    """What the forecast and the market said BEFORE the outcome (stories add the outcome, so their win rates are 100% or 0%)."""
    s=t["story"]
    return SITUATIONS[0] if s in STORIES[0:2] else SITUATIONS[1] if s in STORIES[2:4] else SITUATIONS[2] if s in STORIES[4:6] else SITUATIONS[3]
def section(key,name,ts,note="",posthoc=False):
    """A section's numbers; render_section() turns them into text once every group in the report has been counted."""
    sec=dict(key=key,name=name,note=note,posthoc=posthoc,n=len(ts))
    if not ts: return sec
    sec["all"]=stats(ts)
    sec["tables"]=[table(title,ts,kf,order) for title,kf,order in (
        ("By situation (what the forecast and the market said for our side when the trade was placed)",situation,SITUATIONS),
        ("By side",lambda t:t["side"].upper(),None),("By price paid",lambda t:price_b(t["price"]),["under 20c","20-40c","40-60c","60-80c","80c+"]),
        ("By blend edge at entry",lambda t:edge_b(t["fair"]-t["price"]) if t.get("fair") is not None else "?",["8-12 pts","12-20 pts","20+ pts","?"]),
        ("By city",lambda t:t["city"],None))]
    losses=[t for t in ts if not t["win"]]
    sec["losses"]={k:sum(1 for t in losses if t["story"]==k) for k in STORIES if any(t["story"]==k for t in losses)}
    return sec
def groups_of(sec):
    for tb in sec.get("tables",[]):
        for k,s in tb["groups"].items(): yield tb["title"],k,s
def render_section(sec):
    L=["","## "+sec["name"],""]+([sec["note"],""] if sec["note"] else [])
    if not sec.get("all"): return L+["Nothing settled yet."]
    s=sec["all"]
    L.append("All: %d trades over %d market days, won %d (%.0f%%) vs %.0f%% implied by the prices paid; %+.1fc per contract after fees (day-averaged)%s; reading: %s."%(
        s["n"],s["days"],s["won"],100*s["win_rate"],100*s["market_implied"],100*s["profit"],(" +/- %.1f"%(100*s["profit_se"])) if s["profit_se"] else "",s["verdict"]))
    for tb in sec["tables"]: L+=render_table(tb)
    if sec["losses"]: L+=["","Losses by story: "+", ".join("%s %d"%kv for kv in sec["losses"].items())+". (These mirror how many trades of each kind there were and the prices paid; compare win rate with market implied above.)"]
    return L
def sec_data(sec):
    if not sec.get("all"): return {}
    d={"all":sec["all"],"posthoc":sec["posthoc"]}
    for tb in sec["tables"]: d[tb["title"]]=tb["groups"]
    return d

# ---------- the live record ----------
def live_record():
    """A list of report items: lists of text lines, and sections (dicts) that are rendered after the screen is counted."""
    c=ro(DB); out=[]
    if c is None: return [["","No paper.db yet."]],{}
    data={}
    obs={(r["ticker"],r["version"]):r for r in rows(c,"select ticker,version,fc,mid,result,market_type from obs")}
    for k,r in obs.items(): r["version"]=k[1]
    tr=[]; dropped=0
    for r in rows(c,"select ticker,side,price,fair,n,pnl,result,version from trades where status='settled'"):
        o=obs.get((r["ticker"],r["version"])) or {}   # the scan's log row: forecast and market mid at the trade's scan
        fc=o.get("fc"); mid=o.get("mid")
        if fc is None or mid is None or not r["n"]: dropped+=1; continue
        yes=r["side"]=="yes"; won=r["result"]==r["side"]
        tr.append(dict(day=mday(r["ticker"]),city=city(r["ticker"]),side=r["side"],price=r["price"],fair=r["fair"],win=1 if won else 0,
                       pnl=(r["pnl"] or 0)/r["n"],story=story(fc if yes else 1-fc,mid if yes else 1-mid,won),version=r["version"],
                       kind="rain" if r["ticker"].startswith("KXRAIN") else "temperature"))
    out.append(section("paper_v3_rain","Paper trades, v3 rain (the gate's trades)",[t for t in tr if t["version"]=="v3" and t["kind"]=="rain"],
                       ("%d settled trade(s) left out: no forecast-log row to say what the forecast and market said."%dropped) if dropped else ""))
    other=[t for t in tr if not (t["version"]=="v3" and t["kind"]=="rain")]
    if other: out.append(section("paper_other","Paper trades, other (temperature and older versions; not in the gate)",other))
    # forecast vs market on every logged market (more cases than trades): when they disagreed, who was right?
    res=[r for r in obs.values() if r.get("version")=="v3" and r.get("result") in ("yes","no") and r.get("fc") is not None and r.get("mid") is not None]
    txt=["","## Forecast vs market on every logged market (v3, resolved)",""]; out.append(txt)
    if not res: txt.append("Nothing resolved yet.")
    else:
        for mt in ("rain","temp"):
            rs=[r for r in res if r.get("market_type")==mt]
            if not rs: continue
            txt+=["","### "+("Rain" if mt=="rain" else "Temperature"),"","| Disagreement (forecast - market) | Markets | Forecast closer to the outcome | Market closer | Brier forecast | Brier market |","|---|---:|---:|---:|---:|---:|"]
            for lab,lo,hi in (("under 5 pts",0,0.05),("5-15 pts",0.05,0.15),("15-30 pts",0.15,0.30),("30+ pts",0.30,2)):
                g=[r for r in rs if lo<=abs(r["fc"]-r["mid"])<hi]
                if not g: continue
                y=lambda r:1.0 if r["result"]=="yes" else 0.0
                fbet=sum(abs(r["fc"]-y(r))<abs(r["mid"]-y(r)) for r in g); mbet=sum(abs(r["fc"]-y(r))>abs(r["mid"]-y(r)) for r in g)
                txt.append("| %s | %d | %d | %d | %.3f | %.3f |"%(lab,len(g),fbet,mbet,sum((r["fc"]-y(r))**2 for r in g)/len(g),sum((r["mid"]-y(r))**2 for r in g)/len(g)))
            data["obs_"+mt]=len(rs)
    # limit-order test (shadow ledger)
    so=rows(c,"select ticker,side,price,fair,fc,bid,ask,n,status,result,pnl from shadow_orders where status='settled'")
    ts=[]
    for r in so:   # the ledger keeps its own forecast and quote from when the order was placed
        if r.get("fc") is None or r.get("bid") is None or r.get("ask") is None or not r.get("n"): continue
        yes=r["side"]=="yes"; won=r["result"]==r["side"]; mid=(r["bid"]+r["ask"])/2
        ts.append(dict(day=mday(r["ticker"]),city=city(r["ticker"]),side=r["side"],price=r["price"],fair=r.get("fair"),win=1 if won else 0,pnl=(r["pnl"] or 0)/r["n"],
                       story=story(r["fc"] if yes else 1-r["fc"],mid if yes else 1-mid,won)))
    out.append(section("shadow","Limit-order test (shadow ledger; research only)",ts))
    c.close()
    # the Kalshi account: execution, not forecasting (fills, prices vs paper, why orders were skipped)
    lc=ro(os.getenv("LIVE_DB") or os.path.join(os.path.dirname(os.path.abspath(DB if os.path.isabs(DB) else os.path.join(HERE,DB))),"live.db"))
    txt=["","## Kalshi account (execution)",""]; out.append(txt)
    if lc is None: txt.append("Not connected.")
    else:
        for env in ("demo","prod"):
            o=rows(lc,"select status,count,fill_count,limit_cents,cost,fees,pnl,note,paper_id from orders where env=?",(env,))
            if not o: continue
            placed=[r for r in o if r["status"] in ("executed","partial","canceled","filled (from position)")]; filled=[r for r in o if (r["fill_count"] or 0)>0]
            other={}
            for r in o:
                if r["status"] in ("rejected","not placed","unknown","sending"): other[r["status"]]=other.get(r["status"],0)+1
            asked=sum(r["count"] or 0 for r in placed); got=sum(r["fill_count"] or 0 for r in filled)
            avg_vs_limit=[(r["cost"]/r["fill_count"])-(r["limit_cents"]/100) for r in filled if r["fill_count"]]
            skips={}
            for r in o:
                if r["status"]=="skipped": k=(r["note"] or "?").split(":")[0][:40]; skips[k]=skips.get(k,0)+1
            txt.append("%s: %d orders placed, %g of %d contracts filled (%.0f%%), average fill %+.1fc vs the limit, settled net %+.2f; not placed: %s; skipped: %s."%(
                env,len(placed),got,asked,100*got/asked if asked else 0,100*sum(avg_vs_limit)/len(avg_vs_limit) if avg_vs_limit else 0,
                sum(r["pnl"] or 0 for r in o),", ".join("%s %d"%kv for kv in sorted(other.items())) or "none",
                ", ".join("%s %d"%kv for kv in sorted(skips.items(),key=lambda x:-x[1])) or "none"))
        lc.close()
    return out,data

# ---------- past data (research/data) ----------
def past_record():
    sys.path.insert(0,os.path.join(HERE,"research"))
    import backtest as bt
    runs=bt.load_nbs(); mp=os.path.join(bt.OUT,"rain_model.json")   # the frozen model, never refit here
    if not os.path.exists(mp): return [["","## Past rain markets","","No frozen rain model yet (research/results/rain_model.json)."]]
    b=json.load(open(mp,encoding="utf-8"))["coef"]
    taker,maker=[],[]
    for l in open(os.path.join(bt.DATA,"kalshi_rain.jsonl"),encoding="utf-8"):
        m=json.loads(l); bid,ask=m.get("scan_bid"),m.get("scan_ask")
        if bid is None or ask is None or not (0<=bid<ask<=1) or ask-bid>bt.SPREAD+1e-9: continue
        day=bt.d(m["day"]); f=bt.features(runs,m["station"],day)
        if not f: continue
        y=1 if m["result"]=="yes" else 0; mid=(bid+ask)/2; cfc=bt.C(b,f); fair=bt.BLEND*cfc+(1-bt.BLEND)*mid
        side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
        if q-price>=bt.EDGE-1e-9:   # the same rule as backtest.trades(): one contract, paying the ask, taker fee
            won=(y==1)==(side=="yes"); yes=side=="yes"
            taker.append(dict(day=m["day"],city=m["station"],side=side,price=price,fair=q,win=1 if won else 0,pnl=(1 if won else 0)-price-bt.fee(price),
                              story=story(cfc if yes else 1-cfc,mid if yes else 1-mid,won)))
        yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
        side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
        if q-price>=bt.EDGE-1e-9 and 0<price<1:
            if side=="yes": lo=m.get("lo_after"); filled=lo is not None and (lo<=price+1e-9 if imp else lo<price-1e-9)
            else: hi=m.get("hi_after"); a=1-price; filled=hi is not None and (hi>=a-1e-9 if imp else hi>a+1e-9)
            if filled:
                won=(y==1)==(side=="yes"); yes=side=="yes"
                maker.append(dict(day=m["day"],city=m["station"],side=side,price=price,fair=q,win=1 if won else 0,pnl=(1 if won else 0)-price,
                                  story=story(cfc if yes else 1-cfc,mid if yes else 1-mid,won)))
    note="Past data, Jul 15 to Oct 12 (the same markets and rule as research/backtest.py, scored once on 2026-10-14). These breakdowns were looked at AFTER that test, so any pattern here is a hypothesis for PLAN3, never evidence by itself."
    return [section("past_taker","Past rain markets, paying the ask (taker)",taker,note,posthoc=True),
            section("past_maker","Past rain markets, limit orders (maker)",maker,note,posthoc=True)]

def main():
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    past="--past" in sys.argv
    items,data=live_record()
    if past: items+=past_record()
    secs=[x for x in items if isinstance(x,dict)]
    G=sum(1 for sec in secs for _,_,s in groups_of(sec) if not s["too_few"])   # groups screened in this report
    p=ALPHA/(2*max(G,1))
    for sec in secs:
        if sec.get("all"): sec["all"]["verdict"]=judge(sec["all"],G)
        for _,_,s in groups_of(sec): s["verdict"]=judge(s,G)
    L=["# Learning report","","Generated %s. Read-only. Wins and losses broken down by what the forecast and the market said when the trade was placed, and what happened."%datetime.now().strftime("%Y-%m-%d %H:%M"),"",
       "How to read it: \"market implied\" is the average price paid, which is the win rate the market expected. Winning more often than that is an edge; less is a leak. "
       "\"Too few\" means under %d trades, %d market days or %d weeks. \"Worth a written test\" means profit after fees is away from zero AND from the rest of its breakdown, "
       "each by the Student-t cutoff for the %d groups screened in this report (about %.1f standard errors; Bonferroni, alpha %.2f/(2G)), and both still hold with weekly clusters. "
       "Otherwise \"noise so far\". This screen runs after every settle, so a flag is not a test: it is a pattern to test on NEW markets under a written plan (research/PLAN3.md), never a reason to change the bot directly. "
       "Overall rows are never flagged here; each has its own plan."%(MIN_N,MIN_DAYS,MIN_WEEKS,G,NormalDist().inv_cdf(1-p),ALPHA)]
    for x in items: L+=render_section(x) if isinstance(x,dict) else x
    hyp=[]
    for sec in secs:
        for title,k,s in groups_of(sec):
            if s["verdict"]=="worth a written test":
                hyp.append("%s%s / %s / %s: %+.1fc per contract after fees, %+.1fc vs the rest (t %.1f and %.1f; %d trades, %d days)"%(
                    "[past, post-hoc] " if sec["posthoc"] else "",sec["key"],title.split(" (")[0],k,100*s["profit"],100*s["vs_rest"],s["t"],s["t_vs_rest"],s["n"],s["days"]))
    L+=["","## Patterns worth a written test (a screen of %d groups, not a test)"%G,""]+(["- "+h for h in hyp] or ["None yet. That is the normal result while samples are small."])
    for sec in secs: data[sec["key"]]=sec_data(sec)
    data["screen"]=dict(groups=G,alpha_one_side=p,flagged=hyp)
    os.makedirs(OUTDIR,exist_ok=True)
    open(os.path.join(OUTDIR,"learning.md"),"w",encoding="utf-8").write("\n".join(L)+"\n")
    json.dump(data,open(os.path.join(OUTDIR,"learning.json"),"w",encoding="utf-8"),indent=1,default=str)
    s=(data.get("paper_v3_rain") or {}).get("all")
    print("LEARNING: "+("paper v3 rain %d settled, won %d (%.0f%% vs %.0f%% implied), %+.1fc per contract after fees"%(s["n"],s["won"],100*s["win_rate"],100*s["market_implied"],100*s["profit"]) if s else "no settled paper trades yet")
          +"; %d of %d groups flagged (a screen, not a test); full report %s"%(len(hyp),G,rel(os.path.join(OUTDIR,"learning.md"))))
def rel(p):
    try: return os.path.relpath(p,HERE)
    except ValueError: return p   # another drive (Windows)
if __name__=="__main__": main()
