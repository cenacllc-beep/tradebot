"""Plan 2 backtest (research only; never touches paper.db). Follows research/PLAN2.md. Python 3.8+, no dependencies.
  python research/backtest2.py   ->  research/results/plan2.json and research/results/plan2.md
  A. temperature markets   B. overnight drift (rain and temperature)   C. later scan (rain and temperature)
The temperature model is fitted once on 2025-07-01..2026-06-30 and frozen in research/results/temp_model.json (never
refit; a later run that would fit something different keeps the frozen file and says so). The rain model is the frozen
research/results/rain_model.json from plan 1. Holdouts are scored once; any other cut is a separate, labelled analysis."""
import os, sys, json, glob, math
from datetime import date, datetime, timedelta
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.dirname(HERE))
import backtest as bt   # the rain test's helpers, scoring and trading rule, unchanged
DATA=bt.DATA; OUT=bt.OUT
TRAIN=bt.TRAIN; EDGE=bt.EDGE; SPREAD=bt.SPREAD; BLEND=bt.BLEND; HOLD2=date(2026,7,1)
EVENING=("18:00","19:00"); LATE=("00:00","01:00")   # IEM labels: 19/01 UTC before 2026, 18/00 UTC after (PLAN.md amendment 1)
mean=bt.mean; fee=bt.fee

# ---------- data ----------
def load_runs(sub,hours):
    """(station, run date) -> {ftime 'YYYY-MM-DD HH:MM': row} for the latest run on that date whose label hour is in hours."""
    best={}
    for p in glob.glob(os.path.join(DATA,sub,"*.json")):
        st=os.path.basename(p).split("_")[0]
        for r in json.load(open(p,encoding="utf-8")):
            rt=r.get("runtime") or ""
            if rt[11:16] not in hours: continue
            k=(st,bt.d(rt)); cur=best.get(k)
            if cur is None or rt>cur[0]: best[k]=(rt,{})
            if best[k][0]==rt: best[k][1][r["ftime"][:16]]=r
    return {k:v[1] for k,v in best.items()}
def load_cli():
    """(station, day) -> (rained, high F or None). Trace and missing rain count as 0, as in Kalshi's rules."""
    out={}
    for p in glob.glob(os.path.join(DATA,"cli","*.json")):
        st=os.path.basename(p).split("_")[0]
        for r in json.load(open(p,encoding="utf-8")):
            if r.get("valid"): out[(st,bt.d(r["valid"]))]=((bt.num(r.get("precip")) or 0)>0,bt.num(r.get("high")))
    return out
def jsonl(name):
    p=os.path.join(DATA,name)
    return [json.loads(l) for l in open(p,encoding="utf-8") if l.strip()] if os.path.exists(p) else []
def rain_f(run,day):
    """Plan 1's rain features (P06/Q06 ending 12Z and 18Z on the day, 00Z and 06Z the next day) from one run."""
    if not run: return None
    nx=day+timedelta(days=1); v=[]
    for k in ("%s 12:00"%day,"%s 18:00"%day,"%s 00:00"%nx,"%s 06:00"%nx):
        r=run.get(k)
        if r is None: return None
        p,q=bt.num(r.get("p06")),bt.num(r.get("q06"))
        if p is None or q is None: return None
        v.append((p/100,q))
    p=[x[0] for x in v]; pmax=max(p); pind=1-math.prod(1-x for x in p)
    return dict(R=(pmax+pind)/2,pmax=pmax,pind=pind,q=sum(x[1] for x in v)/100)
def temp_f(run,day):
    """(TXN, XND): the daytime maximum for `day` and its spread, valid 00 UTC the next day. None if missing."""
    if not run: return None
    r=run.get("%s 00:00"%(day+timedelta(days=1)))
    if not r: return None
    t,x=bt.num(r.get("txn")),bt.num(r.get("xnd"))
    return None if t is None or x is None else (t,x)
def ok_quote(b,a): return b is not None and a is not None and 0<=b<a<=1 and a-b<=SPREAD+1e-9

# ---------- model T: high ~ Normal(TXN + a, s0 + s1 * XND), maximum likelihood ----------
def nll(rows,s0,s1):
    """Negative log-likelihood with a profiled out (its MLE for this spread is the weighted mean residual)."""
    w=[]
    for t,x,h in rows:
        s=s0+s1*x
        if s<0.3: return None,None
        w.append(1/(s*s))
    a=sum(wi*(h-t) for wi,(t,x,h) in zip(w,rows))/sum(w)
    return sum(math.log(s0+s1*x)+0.5*((h-t-a)/(s0+s1*x))**2 for t,x,h in rows),a
def fit_T(rows):
    best=None
    for i in range(0,33):
        for j in range(0,31):
            v,a=nll(rows,i*0.25,j*0.1)
            if v is not None and (best is None or v<best[0]): best=(v,a,i*0.25,j*0.1)
    step0,step1=0.25,0.1
    for _ in range(4):   # refine around the best point
        step0/=4; step1/=4; _,_,c0,c1=best
        for i in range(-4,5):
            for j in range(-4,5):
                s0,s1=c0+i*step0,c1+j*step1
                if s0<0 or s1<0: continue
                v,a=nll(rows,s0,s1)
                if v is not None and v<best[0]: best=(v,a,s0,s1)
    return dict(a=best[1],s0=best[2],s1=best[3],nll=best[0])
def Phi(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def p_temp(kind,fl,cap,mu,sd):
    """P(YES) for whole-degree CLI highs: greater than F -> X > F+0.5; less than C -> X < C-0.5; between F and C -> F-0.5 < X < C+0.5."""
    if kind=="greater" and fl is not None: p=1-Phi((fl+0.5-mu)/sd)
    elif kind=="less" and cap is not None: p=Phi((cap-0.5-mu)/sd)
    elif kind=="between" and fl is not None and cap is not None: p=Phi((cap+0.5-mu)/sd)-Phi((fl-0.5-mu)/sd)
    else: return None
    return min(max(p,0.01),0.99)
def T(model,tx,kind,fl,cap): return p_temp(kind,fl,cap,tx[0]+model["a"],model["s0"]+model["s1"]*tx[1])
def Traw(tx,kind,fl,cap): return p_temp(kind,fl,cap,tx[0],max(tx[1],1.0))   # reference only: the NBM numbers as published
def cli_yes(kind,fl,cap,high):
    if high is None: return None
    if kind=="greater": return high>fl
    if kind=="less": return high<cap
    if kind=="between": return fl<=high<=cap
    return None
def flt(v):
    try: return None if v in (None,"") else float(v)
    except (TypeError,ValueError): return None

# ---------- trading rules ----------
def entries(r,fair,bid,ask,lo,hi):
    """The bot's rule at one quote: (taker side, price) and (maker side, price, filled) or None. Same as backtest.trades."""
    side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
    tk=(side,price) if q-price>=EDGE-1e-9 else None
    yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
    side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
    mk=None
    if q-price>=EDGE-1e-9 and 0<price<1:
        if side=="yes": filled=lo is not None and (lo<=price+1e-9 if imp else lo<price-1e-9)
        else: a=1-price; filled=hi is not None and (hi>=a-1e-9 if imp else hi>a+1e-9)
        mk=(side,price,filled,imp)
    return tk,mk
def daysum(ts,days):
    if not ts: return dict(n=0)
    by={dd:0.0 for dd in days}
    for t in ts: by[t["day"]]+=t["pnl"]
    dl=list(by.values()); mu=mean(dl); se=(sum((x-mu)**2 for x in dl)/(len(dl)-1)/len(dl))**0.5 if len(dl)>1 else float("inf")
    return dict(n=len(ts),won=sum(t["pnl"]>0 for t in ts),pnl=sum(t["pnl"] for t in ts),per_contract=mean([t["pnl"] for t in ts]),
                avg_price=mean([t["price"] for t in ts]),day_mean=mu,day_se=se,clear=mu>2*se,days=len(dl))
def drift(rows,days):
    """B: enter at the 8:55 PM quote with the bot's rule, sell when the day starts at that moment's bid for the side held
    (YES bid, or 1 - YES ask for NO). Taker fee on each trade; the limit-order entry pays no fee. Skipped if no exit quote."""
    tk=[]; mk=[]; skip={"taker":0,"maker":0}
    for r in rows:
        t,m=entries(r,r["B"],r["bid"],r["ask"],r["lo"],r["hi"])
        ex=lambda side:(r["sb"] if r["sb"] is not None and 0<=r["sb"]<=1 else None) if side=="yes" else ((1-r["sa"]) if r["sa"] is not None and 0<=r["sa"]<=1 else None)
        if t:
            e=ex(t[0])
            if e is None: skip["taker"]+=1
            else: tk.append(dict(day=r["day"],side=t[0],price=t[1],exit=e,pnl=e-t[1]-fee(t[1])-fee(e)))
        if m and m[2]:
            e=ex(m[0])
            if e is None: skip["maker"]+=1
            else: mk.append(dict(day=r["day"],side=m[0],price=m[1],exit=e,pnl=e-m[1]-fee(e)))
    return dict(taker=daysum(tk,days),maker=daysum(mk,days),skipped_no_exit_quote=skip)
def maker_by_day(rows,days):
    by={dd:0.0 for dd in days}; n=0
    for r in rows:
        _,m=entries(r,r["B"],r["bid"],r["ask"],r["lo"],r["hi"])
        if m and m[2]:
            win=(r["y"]==1)==(m[0]=="yes"); by[r["day"]]+=(1 if win else 0)-m[1]; n+=1
    return by,n
def later(early,late_rows):
    """C: same markets at 03:30 UTC vs 8:55 PM. Later is better only if the limit-order profit per market day is higher by
    2+ standard errors of the paired daily differences."""
    E={r["ticker"]:r for r in early}; L={r["ticker"]:r for r in late_rows}
    both=sorted(set(E)&set(L)); e=[E[t] for t in both]; l=[L[t] for t in both]
    days=sorted({r["day"] for r in e})
    if len(days)<2: return dict(markets=len(both),days=len(days))
    be,ne=maker_by_day(e,days); bl,nl=maker_by_day(l,days)
    diff=[bl[dd]-be[dd] for dd in days]; mu=mean(diff); se=(sum((x-mu)**2 for x in diff)/(len(diff)-1)/len(diff))**0.5
    return dict(markets=len(both),days=len(days),early=bt.trades(e,days),late=bt.trades(l,days),
                brier=dict(early_M=bt.brier(e,"M"),early_F=bt.brier(e,"F"),late_M=bt.brier(l,"M"),late_F=bt.brier(l,"F")),
                maker_fills=dict(early=ne,late=nl),diff_day_mean=mu,diff_day_se=se,later_better=mu>2*se)

# ---------- rows ----------
def rain_rows(coef,runs,quote):
    """Rain markets from plan 1's file with the frozen rain model. quote='early' (00:55 UTC, evening run of the day before)
    or a dict ticker -> late quote (03:30 UTC, the 00/01 UTC run of the market day)."""
    out=[]; skip={"spread":0,"forecast":0}
    for m in jsonl("kalshi_rain.jsonl"):
        day=bt.d(m["day"])
        if quote=="early": bid,ask,lo,hi=m.get("scan_bid"),m.get("scan_ask"),m.get("lo_after"),m.get("hi_after"); run=runs.get((m["station"],day-timedelta(days=1)))
        else:
            q=quote.get(m["ticker"])
            if not q: continue
            bid,ask,lo,hi=q.get("late_bid"),q.get("late_ask"),q.get("late_lo"),q.get("late_hi"); run=runs.get((m["station"],day))
        if not ok_quote(bid,ask): skip["spread"]+=1; continue
        f=rain_f(run,day)
        if not f: skip["forecast"]+=1; continue
        mid=(bid+ask)/2; c=bt.C(coef,f)
        out.append(dict(ticker=m["ticker"],day=m["day"],station=m["station"],y=1 if m["result"]=="yes" else 0,M=mid,F=c,B=BLEND*c+(1-BLEND)*mid,
                        bid=bid,ask=ask,lo=lo,hi=hi,sb=m.get("start_bid"),sa=m.get("start_ask")))
    return out,skip
def temp_rows(model,runs,when,cli):
    out=[]; skip={"spread":0,"forecast":0,"strikes":0}; agree=[0,0]
    for m in jsonl("kalshi_temp.jsonl"):
        day=bt.d(m["day"])
        if day<HOLD2: continue
        kind=m.get("strike_type"); fl,cap=flt(m.get("floor")),flt(m.get("cap"))
        if p_temp(kind,fl,cap,70.0,3.0) is None: skip["strikes"]+=1; continue
        y=1 if m["result"]=="yes" else 0
        c=cli.get((m["station"],day))
        if c and c[1] is not None: agree[0]+=1; agree[1]+=(cli_yes(kind,fl,cap,c[1])==(y==1))
        if when=="early": bid,ask,lo,hi=m.get("scan_bid"),m.get("scan_ask"),m.get("lo_after"),m.get("hi_after"); run=runs.get((m["station"],day-timedelta(days=1)))
        else: bid,ask,lo,hi=m.get("late_bid"),m.get("late_ask"),m.get("late_lo"),m.get("late_hi"); run=runs.get((m["station"],day))
        if not ok_quote(bid,ask): skip["spread"]+=1; continue
        tx=temp_f(run,day)
        if not tx: skip["forecast"]+=1; continue
        mid=(bid+ask)/2; p=T(model,tx,kind,fl,cap)
        out.append(dict(ticker=m["ticker"],day=m["day"],station=m["station"],kind=kind,y=y,M=mid,F=p,R=Traw(tx,kind,fl,cap),B=BLEND*p+(1-BLEND)*mid,
                        bid=bid,ask=ask,lo=lo,hi=hi,sb=m.get("start_bid"),sa=m.get("start_ask")))
    return out,skip,agree
def checks():
    """Data checks on the temperature file: one YES per complete city-day, strikes in the rules match the market fields."""
    g={}; bad_rules=0; n=0
    for m in jsonl("kalshi_temp.jsonl"):
        if bt.d(m["day"])<HOLD2: continue
        n+=1; g.setdefault((m["day"],m["station"]),[]).append(m)
        k=m.get("strike_type"); want={"greater":[flt(m.get("floor"))],"less":[flt(m.get("cap"))],"between":[flt(m.get("floor")),flt(m.get("cap"))]}.get(k)
        if want is not None and [float(x) for x in (m.get("rule_numbers") or [])]!=want: bad_rules+=1
    yes={}
    for v in g.values():
        if len(v)>=6: c=sum(x["result"]=="yes" for x in v); yes[c]=yes.get(c,0)+1
    return dict(markets=n,city_days=len(g),complete_city_days=sum(yes.values()),yes_count_in_complete_city_days={str(k):v for k,v in sorted(yes.items())},rules_strike_mismatch=bad_rules)

# ---------- main ----------
def main():
    cli=load_cli(); ev=load_runs("nbs",EVENING); lt=load_runs("nbs_late",LATE)
    coef=json.load(open(os.path.join(OUT,"rain_model.json"),encoding="utf-8"))["coef"]   # frozen in plan 1
    temp_st=sorted({m["station"] for m in jsonl("kalshi_temp.jsonl")})
    if not temp_st: raise SystemExit("no temperature markets yet: run research/fetch.py temp")
    # A. training (temperature stations, the training year only)
    tr=[]
    for (st,day),(_,high) in cli.items():
        if st in temp_st and TRAIN[0]<=day<=TRAIN[1] and high is not None:
            tx=temp_f(ev.get((st,day-timedelta(days=1))),day)
            if tx: tr.append((tx[0],tx[1],high))
    if len(tr)<1000: raise SystemExit("not enough temperature training data yet: %d station-days"%len(tr))
    mp=os.path.join(OUT,"temp_model.json"); fitted=fit_T(tr)
    if os.path.exists(mp):
        model=json.load(open(mp,encoding="utf-8"))
        if max(abs(model[k]-fitted[k]) for k in ("a","s0","s1"))>1e-6: print("NOTE: refit differs from the frozen temp_model.json; keeping the frozen one",model,fitted)
    else:
        model=dict(fitted,training="%s..%s"%TRAIN,station_days=len(tr),stations=temp_st,form="high ~ Normal(TXN + a, s0 + s1*XND)",created=datetime.now().isoformat(timespec="minutes"))
        os.makedirs(OUT,exist_ok=True); json.dump(model,open(mp,"w",encoding="utf-8"),indent=1)
    res=dict(plan="research/PLAN2.md",generated=datetime.now().isoformat(timespec="minutes"),
             temp_model=dict(a=model["a"],s0=model["s0"],s1=model["s1"],station_days=len(tr),train_mean_error=mean([h-t for t,x,h in tr]),
                             train_mean_xnd=mean([x for t,x,h in tr])))
    # A. temperature holdout at 8:55 PM
    te,tskip,agree=temp_rows(model,ev,"early",cli); tdays=sorted({r["day"] for r in te})
    if len(tdays)<2: raise SystemExit("not enough temperature holdout days")
    A=dict(markets=len(te),days=len(tdays),first=tdays[0],last=tdays[-1],skipped=tskip,yes_rate=mean([r["y"] for r in te]),
           cli_agreement=(agree[1]/agree[0]) if agree[0] else None,cli_checked=agree[0],checks=checks(),
           brier={k:bt.brier(te,k) for k in ("M","R","F","B")},vs_market={k:bt.compare(te,k) for k in ("R","F","B")},
           trading=bt.trades(te,tdays),calibration=dict(F=bt.calib(te,"F"),M=bt.calib(te,"M")))
    by={}
    for r in te: by.setdefault(r["kind"],[]).append(r)
    A["by_kind"]={k:dict(n=len(v),brier_F=bt.brier(v,"F"),brier_M=bt.brier(v,"M")) for k,v in sorted(by.items())}
    A["edge"]=bool(any(A["vs_market"][k]["clear"] for k in ("F","B")) and (A["trading"]["taker"].get("clear") or A["trading"]["maker"].get("clear")))
    res["A_temperature"]=A
    # B. overnight drift
    re_,rskip=rain_rows(coef,ev,"early"); rdays=sorted({r["day"] for r in re_})
    res["B_drift"]=dict(rain=dict(markets=len(re_),days=len(rdays),**drift(re_,rdays)),temperature=dict(markets=len(te),days=len(tdays),**drift(te,tdays)))
    # C. later scan
    lq={r["ticker"]:r for r in jsonl("kalshi_rain_late.jsonl")}
    rl,_=rain_rows(coef,lt,lq); tl,_,_=temp_rows(model,lt,"late",cli)
    res["C_later"]=dict(rain=later(re_,rl),temperature=later(te,tl))
    # verdicts and the multiple-testing count
    clear=[]
    if A["edge"]: clear.append("A temperature")
    for k in ("rain","temperature"):
        for s in ("taker","maker"):
            if res["B_drift"][k][s].get("clear"): clear.append("B drift %s %s"%(k,s))
        if res["C_later"][k].get("later_better"): clear.append("C later scan %s"%k)
    res["clear_results"]=clear
    res["verdict"]=("leads to re-test forward (not an edge yet): "+", ".join(clear)) if clear else "nothing clear: no edge demonstrated on past data"
    os.makedirs(OUT,exist_ok=True)
    json.dump(res,open(os.path.join(OUT,"plan2.json"),"w",encoding="utf-8"),indent=1)
    open(os.path.join(OUT,"plan2.md"),"w",encoding="utf-8").write(report(res))
    print(report(res))

# ---------- report ----------
def f4(x): return "n/a" if x is None else "%.4f"%x
def cents(x): return "n/a" if x is None else "%+.1f¢"%(100*x)
def trow(lab,v,extra=""):
    if not v.get("n"): return "| %s | 0 | | | | |"%lab
    return "| %s | %d%s | %d | $%.2f | %s | %s |"%(lab,v["n"],extra,v["won"],v["pnl"],cents(v["per_contract"]),"yes" if v["clear"] else "no")
def report(r):
    A=r["A_temperature"]; m=r["temp_model"]; ck=A["checks"]
    L=["# Plan 2 results: temperature markets, overnight drift, later scan","",
       "Plan: research/PLAN2.md (written before the data was fetched). Generated %s. Research only; the live bot is unchanged."%r["generated"],"",
       "**Result: %s.**"%r["verdict"],"",
       "Several questions were asked at once, so one clear result among them is weaker evidence than it looks; anything clear only earns a forward test (60 market days).","",
       "## A. Temperature markets","",
       "Model (training 2025-07..2026-06, %d station-days, frozen): high ~ Normal(TXN %+.2f, %.2f + %.2f x XND) F."%(m["station_days"],m["a"],m["s0"],m["s1"]),
       "Holdout: %d markets over %d market days (%s to %s); %.0f%% resolved YES. Skipped: %d wide or missing quotes, %d missing forecasts, %d unreadable strikes."%(
         A["markets"],A["days"],A["first"],A["last"],100*(A["yes_rate"] or 0),A["skipped"]["spread"],A["skipped"]["forecast"],A["skipped"]["strikes"]),
       "Data checks: NWS report vs Kalshi result agree on %s of %d checked; YES count in complete city-days %s; strikes in the rules differ from the market fields on %d markets."%(
         "n/a" if A["cli_agreement"] is None else "%.2f%%"%(100*A["cli_agreement"]),A["cli_checked"],ck["yes_count_in_complete_city_days"],ck["rules_strike_mismatch"]),"",
       "| Forecast | Brier | Minus market, per market | 2 standard errors | Clear? |","|---|---|---|---|---|","| Market mid | %s | | | |"%f4(A["brier"]["M"])]
    for k,lab in (("R","NBM as published (reference)"),("F","Calibrated model T"),("B","Bot blend 50/50")):
        v=A["vs_market"][k]; L.append("| %s | %s | %+.4f | %.4f | %s |"%(lab,f4(A["brier"][k]),v["mean"],2*v["se"],"yes" if v["clear"] else "no"))
    L+=["","| Paper trading, 1 contract per signal | Trades | Won | Net P&L | Per contract | Clear? |","|---|---|---|---|---|---|",
        trow("Pay the ask (taker, fees)",A["trading"]["taker"]),trow("Limit order (maker, no fee)",A["trading"]["maker"]," of %d tried"%A["trading"]["maker"].get("attempts",0)),
        "","Edge on temperature by the pre-set rule: **%s**."%("yes" if A["edge"] else "no"),"",
        "## B. Overnight drift (sell when the market's day starts; the weather outcome never matters)","",
        "| Market | Entry | Trades | Profitable | Net P&L | Per contract | Clear? |","|---|---|---|---|---|---|---|"]
    for k in ("rain","temperature"):
        for s,lab in (("taker","pay the ask"),("maker","limit order")):
            v=r["B_drift"][k][s]
            L.append("| %s | %s | %d | %s | %s | %s | %s |"%(k,lab,v.get("n",0),v.get("won","") if v.get("n") else "","$%.2f"%v["pnl"] if v.get("n") else "",cents(v.get("per_contract")) if v.get("n") else "",("yes" if v["clear"] else "no") if v.get("n") else ""))
    L+=["","Skipped for lack of a quote at the day start: rain %s, temperature %s."%(r["B_drift"]["rain"]["skipped_no_exit_quote"],r["B_drift"]["temperature"]["skipped_no_exit_quote"]),"",
        "## C. Later scan (03:30 UTC with the newer forecast) vs 8:55 PM, same markets","",
        "| Market | Markets | Days | Limit-order P&L 8:55 PM | Limit-order P&L 03:30 UTC | Daily difference | 2 SE | Later better? |","|---|---|---|---|---|---|---|---|"]
    for k in ("rain","temperature"):
        v=r["C_later"][k]
        if "early" not in v: L.append("| %s | %d | %d | | | | | not enough data |"%(k,v["markets"],v["days"])); continue
        e,l=v["early"]["maker"],v["late"]["maker"]
        L.append("| %s | %d | %d | %s | %s | %s | %s | %s |"%(k,v["markets"],v["days"],"$%.2f (%d fills)"%(e["pnl"],e["n"]) if e.get("n") else "0 fills",
                 "$%.2f (%d fills)"%(l["pnl"],l["n"]) if l.get("n") else "0 fills",cents(v["diff_day_mean"]),"%.1f¢"%(200*v["diff_day_se"]),"yes" if v["later_better"] else "no"))
    return "\n".join(L)+"\n"
if __name__=="__main__": main()
