"""Control center for the dashboard (added 2026-10-22, platform upgrade phases 24-25). Presentation only.

dashboard.py passes rows it already read from paper.db (opened read-only). This module never opens a database, a file
or the network. Sections:
- strategy status (from registry.py);
- the shadow selector's view of the latest scan, with the best rejected candidates;
- forward tests, labelled INTERIM - NOT ACTIONABLE;
- calibration;
- risk clusters and capital efficiency;
- the audit trail: every trade's decision snapshot, in plain words.
Python 3.8+."""
import json, html
from tbcommon import clock
import registry, calibration, risk, audit, postmortem, metrics
e=html.escape
def _j(s):
    try: return json.loads(s) if s else {}
    except ValueError: return {}
def pct(x,d=0): return "n/a" if x is None else ("%."+str(d)+"f%%")%(100*x)
def usd(x): return "n/a" if x is None else (("-$%.2f"%-x) if x<-0.004 else "$%.2f"%abs(x))
def when(ts): return clock.label(ts)   # bot time, UTC-4 (the page names the zone once); "never" when missing
LEDGER_FROM=1792710000   # 2026-10-22 23:00 UTC (7 PM local), after this upgrade was installed: every later scan should have its ledger
def blocked(T):
    """A message when the latest scan logged markets without its decision ledger (so no paper trade could open)."""
    ot=[r.get("ts") for r in T["obs"] if r.get("version")=="v3" and r.get("ts")]
    if not ot or max(ot)<LEDGER_FROM: return None
    st=[s["started_ts"] for s in T["scans"] if s.get("kind")=="scan"]
    if st and max(ot)<=max(st)+7200: return None   # a scan logs markets within minutes of starting; 2 hours allows a slow one
    return "TRADES BLOCKED: the latest scan (%s) ran without its decision ledger, so no paper trade could open. The scan output says why (look for AUDIT)."%when(max(ot))
STATE_TAG={"FORWARD_TEST":"rest","FAILED":"lost","CONFIRMED":"won","IDEA":"excluded","BACKTEST":"exploratory","SUSPENDED":"lost",
           "RETIRED":"excluded","PAPER_ONLY":"won","LIVE_ELIGIBLE":"won"}
def explain(d):
    """One decision in plain words."""
    side=(d.get("side") or "").upper(); r=d.get("reason"); det=_j(d.get("detail")); meta=det.get("meta") or {}
    bits=[]
    if d.get("p_model") is not None and d.get("bid") is not None and d.get("ask") is not None:
        bits.append("Forecast said YES %s; the market's mid was %s (bid %s, ask %s)."%(pct(d["p_model"]),pct((d["bid"]+d["ask"])/2),
                    pct(d["bid"]),pct(d["ask"])))
    if d.get("p_win") is not None and d.get("price") is not None and side:
        bits.append("Blending the two gave %s a %s chance against a price of %s: an edge of %.1f points%s."%(side,pct(d["p_win"]),
                    pct(d["price"]),100*(d["p_win"]-d["price"]),"" if d.get("net_ev") is None else ", %.1f after fees"%(100*d["net_ev"])))
    bits.append("Decision: %s. %s"%("traded %s"%side if d.get("action","").startswith("TRADE") else "no trade",audit.REASONS.get(r,r)))
    if meta.get("reason"):
        if meta.get("action","").startswith("TRADE"):
            bits.append("Accuracy-first selector (shadow): would trade, with a conservative win chance of %s."%pct(meta.get("q_cons")))
        else:
            bits.append("Accuracy-first selector (shadow): would not trade. %s"%audit.REASONS.get(meta["reason"],meta["reason"])
                        +("" if meta.get("bin_n") is None else " (%d settled markets in this probability range so far)"%meta["bin_n"]))
    return " ".join(bits)
def strategy_rows(T):
    tr=T["trades"]; so=T["shadow_orders"]; obs=T["obs"]; v4p=T["v4_paper"]; v4o=T["v4_obs"]
    def tstats(rows):
        st=[r for r in rows if r.get("status")=="settled"]; w=sum(1 for r in st if r.get("result")==r.get("side"))
        p=sum(r.get("pnl") or 0 for r in st) if st else None
        return len(st),w,p
    out=[]
    for s in registry.REGISTRY:
        n=w=0; pnl=None; extra=""
        if s["id"]=="forecast_alpha.rain.v3":
            n,w,pnl=tstats([r for r in tr if r.get("version")=="v3" and str(r.get("ticker","")).startswith("KXRAIN")])
            rg=[r for r in obs if r.get("version")=="v3" and r.get("mtype")=="rain" and r.get("result") in ("yes","no") and r.get("fc") is not None and r.get("mid") is not None]
            days=len({str(r["ticker"]).split("-")[1] for r in rg})
            bf=calibration.brier([(r["fc"],r["result"]=="yes") for r in rg]); bm=calibration.brier([(r["mid"],r["result"]=="yes") for r in rg])
            extra="%d of 100 markets resolved over %d day%s; Brier forecast %s vs market %s"%(len(rg),days,"" if days==1 else "s","n/a" if bf is None else "%.3f"%bf,"n/a" if bm is None else "%.3f"%bm)
        elif s["id"]=="forecast_alpha.temp.v3":
            n,w,pnl=tstats([r for r in tr if not str(r.get("ticker","")).startswith("KXRAIN")])
        elif s["id"]=="maker_spread.rain.v3":
            n,w,pnl=tstats(so); extra="%d limit orders, %d filled"%(len(so),sum(1 for r in so if r.get("status") in ("filled","settled")))
        elif s["id"]=="forecast_alpha.rain.v4":
            mk=[r for r in v4p if r.get("kind")=="maker" and r.get("filled") and r.get("result") in ("yes","no")]
            n=len(mk); w=sum(1 for r in mk if r.get("result")==r.get("side")); pnl=sum(r.get("pnl") or 0 for r in mk) if mk else None
            extra="%d market days logged of 110"%len({str(r.get("ticker","")).split("-")[1] for r in v4o})
        wr=("%s (%d of %d)"%(pct(w/n),w,n)) if n else "–"
        out.append(['<b>%s</b><br><small>%s</small>'%(e(s["id"]),e(s["family"])),
                    '<span class="tag %s">%s</span><br><small>%s%s%s</small>'%(STATE_TAG.get(s["state"],""),e(s["state"].replace("_"," ").lower()),e(s["mode"]),
                        ("; since %s"%e(s["started"])) if s.get("started") else "",("; verdict: %s"%e(s["horizon"])) if s.get("horizon") and s["state"] in ("FORWARD_TEST","IDEA","BACKTEST") else ""),
                    wr,usd(pnl) if pnl is not None else "–",("%s/trade"%usd(pnl/n)) if (n and pnl is not None) else "–",
                    e(extra or s["rule"])+(("<br><small class=neg>%s</small>"%e(s["why"])) if s.get("why") else "")])
    return out
def metric_rows(T):
    """Phase-32 metrics per strategy that has settled trades, plus the correlation of their daily P&L."""
    sets=[("forecast_alpha.rain.v3",[r for r in T["trades"] if r.get("version")=="v3" and str(r.get("ticker","")).startswith("KXRAIN")]),
          ("forecast_alpha.temp.v3",[r for r in T["trades"] if not str(r.get("ticker","")).startswith("KXRAIN")]),
          ("maker_spread.rain.v3",[dict(r,settled_ts=r.get("settle_ts")) for r in T["shadow_orders"]])]
    rows=[]; days={}
    for sid,tr in sets:
        m=metrics.summary(tr)
        if not m: continue
        days[sid]=metrics.daily(tr)
        hold="n/a" if m["avg_hours"] is None else ("%.0f h"%m["avg_hours"])
        rows.append([e(sid),str(m["n"]),"%s (%d of %d)"%(pct(m["win_rate"]),m["wins"],m["n"]),"%s (%d)"%(pct(m["profitable_rate"]),m["profitable"]),usd(m["pnl"]),
                     "n/a" if m["per_contract"] is None else "%+.1fc"%(100*m["per_contract"]),
                     "n/a" if m["expected"] is None else "%s vs %s"%(usd(m["pnl"]),usd(m["expected"])),
                     "n/a" if m["brier"] is None else "%.3f"%m["brier"],usd(-m["max_drawdown"]),usd(m["largest_loss"]),hold,
                     "n/a" if m["per_dollar_day"] is None else "%+.1f%%"%(100*m["per_dollar_day"]),
                     "n/a" if m["sharpe_like"] is None else "%.2f (%d days)"%(m["sharpe_like"],m["days"]),
                     "%s %s"%(e(m["worst_cluster"] or ""),usd(m["worst_cluster_pnl"]))])
    corr=""
    if "forecast_alpha.rain.v3" in days and "maker_spread.rain.v3" in days:
        r,k=metrics.correlation(days["forecast_alpha.rain.v3"],days["maker_spread.rain.v3"])
        corr="Daily P&amp;L correlation, main bot vs limit-order test: %s."%("needs 5 shared settle days (%d so far)"%k if r is None else "%.2f over %d days"%(r,k))
    return rows,corr
def convergence_rows(trades,marks):
    """Open main-bot trades at Kalshi prices: entry, latest bid, the fair value at entry, the best and worst moments
    (maximum favourable and adverse excursion) and a research-only note."""
    out=[]
    for r in trades:
        if r.get("status")!="open" or not r.get("n"): continue
        k="main:%s"%r.get("id"); vals=[(x["ts"],x["marks"][k]) for x in marks or [] if k in (x.get("marks") or {}) and x["ts"]>=(r.get("ts") or 0)]
        cost=r.get("cost") or 0
        if not vals: out.append([e(r["ticker"]),e((r.get("side") or "").upper()),pct(r.get("price")),"no price yet",pct(r.get("fair")),"–","–","–","waiting for prices (run watch or the hourly refresh)"]); continue
        cur=vals[-1][1]; hi=max(v for _,v in vals); lo=min(v for _,v in vals); bid=cur/r["n"]
        note="price has reached the model's fair value at entry: a paper exit test would sell here (research only)" if r.get("fair") is not None and bid>=r["fair"] else "hold (no exit rule is in force; exits are a future paper test)"
        out.append([e(r["ticker"]),e((r.get("side") or "").upper()),pct(r.get("price")),pct(bid),pct(r.get("fair")),usd(hi-cost),usd(lo-cost),usd(cur-cost),e(note)])
    return out
RESEARCH_FILES=(("plan5_L.md","PLAN5 test L: resting quotes and rewards"),("structure.md","Market structure"),("discovery.md","Market discovery"),
                ("micro.md","Order flow, fills and lead-lag"),("combo.md","Combos and implied correlation"),("longshot.md","Favorite / longshot"))
def research_notes(notes):
    """notes: [(file, modified ts, lines)] read by dashboard.py from research/results: the first lines and the closing
    caveat. Shown as text, never acted on."""
    if not notes: return ""
    names=dict(RESEARCH_FILES); rows=[]
    for f,ts,txt in notes:
        rows.append('<details><summary>%s <small>(%s)</small></summary><p class=note>%s</p></details>'%(e(names.get(f,f)),when(ts),"<br>".join(e(x) for x in txt)))
    return '<h3>Research results (exploratory, not actionable)</h3><p class=note>The latest summary of each research tool. None of them trades; a pattern here earns only a written plan.</p>'+"".join(rows)
def safety_line(now_ts,lip_samples=None):
    from datetime import date
    d=clock.bot_date(now_ts); stop=date(2026,11,11)
    lock=("Real money: locked by date until Nov 11 (%d days). After that it also needs your own typed unlock, and the rain bot keeps paper trading"
          " (so live.py has something to copy) only if the gate's single look passes."%(stop-d).days) if d<stop else \
         "Real money: the date lock has passed; orders still need your own typed unlock (live.py status shows whether you gave it), and the rain bot paper-trades new market days only after a gate look that passed."
    extra=("" if lip_samples is None else (" PLAN5 test L: %s"%lip_samples if isinstance(lip_samples,str) else
           " PLAN5 test L: %d market-hours sampled so far (interim, not actionable)."%lip_samples))
    return lock+" live.py copies v3 rain paper trades only; no research strategy can reach it."+extra
FRESH_TAG={"ok":"won","stale":"exploratory","fail":"lost","waiting":"excluded","info":"rest"}
FRESH_ORDER={"fail":0,"stale":1,"waiting":2,"info":3,"ok":4}
def freshness_panel(rows,table):
    """rows: freshness.checks(), run by dashboard.py. Problems first, then everything else folded away. The page's own
    age is left out (the page is being rebuilt). Read-only: nothing here changes a decision."""
    if not rows: return ""
    rows=sorted([r for r in rows if r.get("key")!="page"],key=lambda r:FRESH_ORDER.get(r.get("status"),5))
    def tr(r):
        return ['<span class="tag %s">%s</span>'%(FRESH_TAG.get(r["status"],"rest"),e(r["status"])),e(r["name"]),e(r["last_label"]),
                e(clock.human_age(r["age_s"])) if r.get("age_s") is not None else "–",e(clock.human_age(r["limit_s"])) if r.get("limit_s") else "–",
                e(r["detail"])+(' <b>%s</b>'%e(r["action"]) if r.get("action") else "")]
    bad=[r for r in rows if r["status"] in ("stale","fail")]; others=[r for r in rows if r["status"] not in ("stale","fail")]
    heads=["Status","Data","Last","Age","Allowed","Detail and what to do"]
    top=('<p class=note><b class=neg>%d of %d checks need attention.</b> Each dataset has a refresh limit set by the job that updates it.</p>'%(len(bad),len(rows))
         +table(heads,[tr(r) for r in bad],num=(3,4))) if bad else '<p class=note>Every dataset is within its refresh limit.</p>'
    more=('<details><summary>%s %d checks</summary>%s</details>'%("The other" if bad else "All",len(others),table(heads,[tr(r) for r in others],num=(3,4)))) if others else ""
    return ('<h3 id=freshness>Data freshness</h3>%s%s<p class=note>All times on this page are %s. These checks only report: none of them changes a decision.</p>'
            %(top,more,e(clock.ZONE_NOTE)))
def structure_note(runs):
    if not runs: return ""
    r=runs[-1]; pos=[v for v in r.get("found",[]) if v.get("net",0)>0]; conf=[v for v in pos if (v.get("confirm") or {}).get("still")]
    return ('<h3>Market structure (research)</h3><p class=note>Last scan %s: %d open weather events, %d markets. Price inconsistencies positive after taker fees at listed prices: %d; still there in the live order book: %d. Nothing is traded: a basket can leave directional risk until every leg fills.</p>'%(
        when(r.get("ts")),r.get("events",0),r.get("markets",0),len(pos),len(conf)))
def section(T,table,now_ts):
    dec=T["decisions"]; scans=T["scans"]; ev=T["decision_events"]
    if not registry.REGISTRY: return ""
    parts=[]
    # status line
    main_scans=[s for s in scans if s.get("kind")=="scan"]; last=max(main_scans,key=lambda s:s["started_ts"]) if main_scans else None
    settled=[r.get("settled_ts") for r in T["trades"] if r.get("settled_ts")]+[r.get("recorded_ts") for r in T["market_results"] if r.get("recorded_ts")]
    lines=["Last scan with the decision ledger: <b>%s</b>; last settle: <b>%s</b>; %d decisions recorded in total."%(when(last["started_ts"]) if last else "not yet",when(max(settled) if settled else None),T.get("decisions_total",len(dec)))]
    b=blocked(T)
    if b: lines.insert(0,"<b class=neg>%s</b>"%e(b))
    if last:
        ld=[d for d in dec if d["scan_id"]==last["scan_id"]]
        ages=[(_j(d.get("inputs")).get("grid") or {}).get("fetched") for d in ld]; ages=[last["started_ts"]-a for a in ages if a]
        if ages: lines.append("Forecast data at that scan was at most %d minutes old."%(max(ages)//60))
    lines.append(e(safety_line(now_ts,T.get("lip_samples"))))
    parts.append('<p class=note>%s</p>'%" ".join(lines))
    parts.append(freshness_panel(T.get("freshness"),table))
    # strategies
    parts.append('<h3>Strategies</h3><p class=note>Each strategy is kept separate. A forward test is <b>INTERIM - NOT ACTIONABLE</b> until its pre-set verdict date. No new strategy here can place orders. live.py copies only v3 rain paper trades: to Kalshi&#39;s demo exchange (fake money) any time, and to real money only on or after Nov 11 after your own typed unlock. The gate verdict is shown when you unlock; it does not stop you, so read it first.</p>'
                 +table(["Strategy","State","Win rate (settled)","Net P&amp;L","Per trade","Progress or rule"],strategy_rows(T),num=(2,3,4)))
    mrows,corr=metric_rows(T)
    if mrows: parts.append('<h3>Metrics by strategy</h3><p class=note>Settled paper trades only. Win rate counts settlements won; profitable counts trades that made money after fees. Expected is what the model\'s own chances said the trades were worth. Drawdown is the largest fall from a running high. The daily ratio is mean over standard deviation of daily P&amp;L, not annualized, and needs 5 days. %s Every figure is interim: read it with its sample size.</p>'%corr
                           +table(["Strategy","Settled","Won","Profitable","Net","Per contract","Realized vs expected","Brier","Max drawdown","Largest loss","Avg hold","Per $ per day","Daily ratio","Worst cluster"],mrows,num=(1,4,5,7,8,9,10,11)))
    # selector on the latest scan
    if last:
        ld=[d for d in dec if d["scan_id"]==last["scan_id"] and d["strategy_id"]=="forecast_alpha.rain.v3"]
        rc={}; mc={}
        for d in ld:
            rc[d["reason"]]=rc.get(d["reason"],0)+1
            m=(_j(d.get("detail")).get("meta") or {})
            if m.get("reason"): mc[m["reason"]]=mc.get(m["reason"],0)+1
        rows=[[e(k),str(v),e(audit.REASONS.get(k,""))] for k,v in sorted(rc.items(),key=lambda x:-x[1])]
        traded=sum(1 for d in ld if d["action"].startswith("TRADE")); meta_t=mc.get("TRADE",0)
        cands=sorted([d for d in ld if d["action"]=="ABSTAIN" and d.get("p_win") is not None and d.get("price") is not None],key=lambda d:-(d["p_win"]-d["price"]))[:5]
        crow=[[e(d["ticker"]),e((d.get("side") or "").upper()),pct(d["p_win"]),pct(d["price"]),"%+.1f"%(100*(d["p_win"]-d["price"])),e(d["reason"]),e(explain(d))] for d in cands]
        parts.append('<h3>Latest scan: what was traded and why not</h3><p class=note>%d rain markets evaluated on %s: %d paper trades (v3 rule). The accuracy-first selector, which only watches, would have traded %d (abstain rate %s). Its most common reasons: %s.</p>'%(
            len(ld),when(last["started_ts"]),traded,meta_t,pct(1-meta_t/len(ld)) if ld else "n/a",", ".join("%s %d"%(e(k.replace("_"," ").lower()),v) for k,v in sorted(mc.items(),key=lambda x:-x[1])[:4]) or "none")
            +table(["Reason (v3 rule)","Markets","Meaning"],rows,"No markets in this scan.",num=(1,))
            +"<details><summary>Best candidates that were not traded</summary>"+table(["Market","Side","Chance","Price","Edge (pts)","Reason","In plain words"],crow,"None.",num=(2,3,4))+"</details>")
    # calibration
    rows=[(r["fc"],1 if r["result"]=="yes" else 0) for r in T["obs"] if r.get("version")=="v3" and r.get("mtype")=="rain" and r.get("result") in ("yes","no") and r.get("fc") is not None]
    mrows=[(r["mid"],1 if r["result"]=="yes" else 0) for r in T["obs"] if r.get("version")=="v3" and r.get("mtype")=="rain" and r.get("result") in ("yes","no") and r.get("mid") is not None]
    if rows:
        S=calibration.summary(rows); M=calibration.summary(mrows)
        trow=[["%d-%d%%"%(b*10,b*10+10),str(n),pct(mp),pct(of),"%s-%s"%(pct(lo),pct(hi))] for b,n,mp,of,lo,hi in S["table"]]
        parts.append('<h3>Calibration: v3 rain forecast</h3><p class=note>When the forecast says X%%, how often does it rain? %d settled markets. Brier %.3f (market %.3f), log loss %.3f (market %.3f), calibration error %s. The range is a 95%% interval: with few markets per row it is wide, so read it before the rate.</p>'%(
            S["n"],S["brier"],M["brier"],S["logloss"],M["logloss"],pct(S["ece"],1))+table(["Forecast","Markets","Average forecast","Rained","95% range"],trow,num=(1,2,3)))
    # risk and capital
    pos=[(r["ticker"],(r.get("cost") or 0)+(r.get("fee") or 0)) for r in T["trades"] if r.get("status")=="open"]
    pos+=[(r["ticker"],(r.get("cost") or 0)) for r in T["shadow_orders"] if r.get("status")=="filled"]
    ex=risk.exposure(pos); cnt={}
    for t,_ in pos: cnt[risk.cluster(t)]=cnt.get(risk.cluster(t),0)+1
    rrow=[[e(k),str(cnt[k]),usd(v),('<span class=neg>several positions share this weather</span>' if cnt[k]>1 else "")] for k,v in sorted(ex.items(),key=lambda x:-x[1])]
    cs=risk.capital_summary(T["trades"])
    parts.append('<h3>Risk clusters and capital</h3><p class=note>Markets on the same day in the same region share one weather system, so they count as one risk. Open paper positions (main bot and limit-order test):</p>'
                 +table(["Cluster","Positions","At risk","Note"],rrow,"No open positions.",num=(1,2))
                 +('<p class=note>Settled trades used %s of capital for %.0f hours on average; profit per dollar per day %s (%d trades).</p>'%(usd(cs["capital"]),cs["avg_hours"],
                   "n/a" if cs["per_dollar_day"] is None else "%+.1f%%"%(100*cs["per_dollar_day"]),cs["trades"]) if cs else ""))
    # open positions at market prices (price convergence, research)
    cv=convergence_rows(T["trades"],T.get("marks"))
    if cv: parts.append('<h3>Open positions at Kalshi prices</h3><p class=note>Best and worst moments since entry, from the price snapshots. Hold, exit and watch notes are research only: no exit rule is in force, and v3 holds every trade to settlement.</p>'
                         +table(["Market","Side","Paid","Bid now","Fair at entry","Best","Worst","Now","Note"],cv,num=(2,3,4,5,6,7)))
    parts.append(structure_note(T.get("structure_runs")))
    parts.append(research_notes(T.get("research_notes")))
    # audit trail
    byref={d.get("trade_ref"):d for d in dec if d.get("trade_ref")}; evs={}
    for x in ev: evs.setdefault(x["decision_id"],[]).append(x)
    items=[]
    for kind,rows_ in (("trades",T["trades"]),("shadow_orders",T["shadow_orders"])):
        for r in sorted(rows_,key=lambda r:-(r.get("ts") or 0))[:12]:
            d=byref.get("%s:%s"%(kind,r.get("id")))
            head="%s %s %s, %s"%("Main bot" if kind=="trades" else "Limit-order test",e((r.get("side") or "").upper()),e(r.get("ticker") or ""),when(r.get("ts")))
            if not d: items.append('<details><summary>%s</summary><p class=note>No decision record: opened before the audit ledger started (Oct 22, 2026).</p></details>'%head); continue
            inp=_j(d.get("inputs")); g=inp.get("grid") or {}
            facts=[("Decision id",d["decision_id"][:12]),("Scan",d["scan_id"][:12]),("Strategy","%s (%s), model %s"%(d["strategy_id"],d["mode"],d.get("model_version") or "")),
                   ("Quote at decision","bid %s, ask %s, spread %s"%(pct(d.get("bid")),pct(d.get("ask")),"n/a" if d.get("spread") is None else "%.0fc"%(100*d["spread"]))),
                   ("Model","forecast YES %s, blended %s, chosen side %s at %s"%(pct(d.get("p_model")),pct(d.get("p_fair")),pct(d.get("p_win")),pct(d.get("price")))),
                   ("Size","%s contracts, cost %s, fee %s"%(d.get("n"),usd(d.get("cost")),usd(d.get("fee")))),
                   ("Settlement source","station %s; rules hash %s"%(d.get("station") or "n/a",d.get("rules_hash") or "n/a")),
                   ("Forecast data","NWS grid fetched %s, issued %s"%(when(g.get("fetched")),g.get("update_time") or "n/a")),
                   ("Inputs","first-half chance %s, second-half %s"%(pct(inp.get("p_a")),pct(inp.get("p_b"))) if inp.get("p_a") is not None else "n/a")]
            outc=["%s: %s"%(x["kind"],e(", ".join("%s %s"%(k,v) for k,v in (_j(x.get("detail")) or {}).items()))) for x in sorted(evs.get(d["decision_id"],[]),key=lambda x:x["ts"])]
            items.append('<details><summary>%s</summary><p class=note>%s</p><dl class=audit>%s</dl>%s</details>'%(head,e(explain(d)),
                         "".join("<dt>%s</dt><dd>%s</dd>"%(e(a),e(str(b))) for a,b in facts),('<p class=note>After the decision: %s.</p>'%"; ".join(outc)) if outc else ""))
    # post-mortem of settled trades (main bot)
    cal=calibration.Calib([(0.5*r["fc"]+0.5*r["mid"],1 if r["result"]=="yes" else 0) for r in T["obs"] if r.get("version")=="v3" and r.get("mtype")=="rain" and r.get("result") in ("yes","no") and r.get("fc") is not None and r.get("mid") is not None])
    pm=[]
    for r in T["trades"]:
        if r.get("status")!="settled": continue
        d=byref.get("trades:%s"%r.get("id")); dd=dict(d,inputs_obj=_j(d.get("inputs"))) if d else None
        pm.append((r,postmortem.classify(r,dd,cal)))
    if pm:
        sm=postmortem.summary([c for _,c in pm])
        prow=[[e(r["ticker"]),e((r.get("side") or "").upper()),pct(r.get("price")),pct(r.get("fair")),usd(r.get("pnl")),e("; ".join(postmortem.TEXT.get(c,c) for c in codes))] for r,codes in sorted(pm,key=lambda x:-(x[0].get("settled_ts") or 0))[:15]]
        parts.append('<h3>Why settled trades won or lost</h3><p class=note>Each settled paper trade, classified from its record. %s. One loss never changes a strategy by itself: changes need enough settled trades and a plan written first.</p>'%(
            ", ".join("%s: %d"%(e(postmortem.TEXT.get(k,k)),v) for k,v in sorted(sm.items(),key=lambda x:-x[1])))
            +table(["Market","Side","Paid","Fair at entry","P&amp;L","Causes"],prow,num=(2,3,4)))
    parts.append('<h3>Audit trail</h3><p class=note>The exact snapshot behind each recent paper trade. Records are never changed; anything learned later is added below them.</p>'+("".join(items) or "<p class=note>No trades yet.</p>"))
    return '<section class="panel control" id=control><h2>Control center <span>strategies, selection, calibration, risk, audit</span></h2>%s</section>'%"".join(parts)
CSS="""
.control h3{font-size:15px;margin:18px 0 6px}
.control dl.audit{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:4px 12px;font-size:13px;margin:8px 0}
.control dl.audit dt{color:var(--ink2)}.control dl.audit dd{margin:0;overflow-wrap:anywhere}
.control td small{color:var(--ink2)}
"""
