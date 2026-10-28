"""Rain backtest (research only; never touches paper.db). Follows research/PLAN.md exactly. Python 3.8+, no dependencies.
  python research/backtest.py   ->  research/results/rain_backtest.json and research/results/rain_backtest.md
Training: NBS forecasts + CLI outcomes, 2025-07-01..2026-06-30. Holdout: every settled KXRAIN market, scored once."""
import os, json, glob, math
from datetime import date, datetime, timedelta
HERE=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(HERE,"data"); OUT=os.path.join(HERE,"results")
TRAIN=(date(2025,7,1),date(2026,6,30)); EDGE=0.08; SPREAD=0.06; BLEND=0.5

def sig(z): return 1/(1+math.exp(-max(-30,min(30,z))))
def logit(p): p=min(max(p,0.005),0.995); return math.log(p/(1-p))
def num(v):
    try: return None if v in (None,"","M","T") else float(v)
    except (TypeError,ValueError): return None
def mean(x): return sum(x)/len(x) if x else None
def d(s): return datetime.strptime(s[:10],"%Y-%m-%d").date()

# ---------- data ----------
def load_cli():
    out={}
    for p in glob.glob(os.path.join(DATA,"cli","*.json")):
        st=os.path.basename(p).split("_")[0]
        for r in json.load(open(p,encoding="utf-8")):
            v=r.get("precip")
            if r.get("valid"): out[(st,d(r["valid"]))]=(num(v) or 0)>0   # trace (T) and missing (M) count as 0, as in Kalshi's rules
    return out
def load_nbs():
    """(station, run date) -> {ftime: (p06, q06)} from the evening run (19 UTC in IEM's archive before 2026, 18 UTC after;
    issued well before the 00:55 UTC scan). If a date has both, the later run is used."""
    best={}
    for p in glob.glob(os.path.join(DATA,"nbs","*.json")):
        st=os.path.basename(p).split("_")[0]
        for r in json.load(open(p,encoding="utf-8")):
            rt=r.get("runtime") or ""
            if rt[11:16] not in ("18:00","19:00"): continue
            k=(st,d(rt)); cur=best.get(k)
            if cur is None or rt>cur[0]: best[k]=(rt,{})
            if best[k][0]==rt: best[k][1][r["ftime"][:16]]=(num(r.get("p06")),num(r.get("q06")))
    return {k:v[1] for k,v in best.items()}
def features(runs,st,day):
    """Evening run (18/19 UTC) of the day before; P06/Q06 ending 12Z, 18Z on the day, 00Z, 06Z the next day. None if anything is missing."""
    run=runs.get((st,day-timedelta(days=1)))
    if not run: return None
    nx=day+timedelta(days=1)
    keys=["%s 12:00"%day,"%s 18:00"%day,"%s 00:00"%nx,"%s 06:00"%nx]
    v=[run.get(k) for k in keys]
    if any(x is None or x[0] is None or x[1] is None for x in v): return None
    p=[x[0]/100 for x in v]; q=sum(x[1] for x in v)
    pmax=max(p); pind=1-math.prod(1-x for x in p)   # math.prod: Python 3.8+
    return dict(R=(pmax+pind)/2,pmax=pmax,pind=pind,q=q/100)
def X(f): return [1.0,logit(f["R"]),math.log1p(100*f["q"])]

# ---------- logistic regression (Newton-Raphson) ----------
def solve(A,b):
    n=len(b); M=[A[i][:]+[b[i]] for i in range(n)]
    for c in range(n):
        piv=max(range(c,n),key=lambda r:abs(M[r][c])); M[c],M[piv]=M[piv],M[c]
        for r in range(n):
            if r!=c:
                k=M[r][c]/M[c][c]
                for j in range(c,n+1): M[r][j]-=k*M[c][j]
    return [M[i][n]/M[i][i] for i in range(n)]
def fit(rows):
    b=[0.0,1.0,0.0]
    for _ in range(50):
        g=[0.0]*3; H=[[1e-6 if i==j else 0.0 for j in range(3)] for i in range(3)]
        for x,y in rows:
            p=sig(sum(bi*xi for bi,xi in zip(b,x))); w=p*(1-p)
            for i in range(3):
                g[i]+=(y-p)*x[i]
                for j in range(3): H[i][j]+=w*x[i]*x[j]
        step=solve(H,g); b=[bi+si for bi,si in zip(b,step)]
        if max(abs(s) for s in step)<1e-9: break
    return b
def C(b,f): return min(max(sig(sum(bi*xi for bi,xi in zip(b,X(f)))),0.01),0.99)

# ---------- scoring ----------
def brier(rows,k): return mean([(r[k]-r["y"])**2 for r in rows])
def daywise(rows,val):
    by={}
    for r in rows: by.setdefault(r["day"],[]).append(val(r))
    dm=[mean(v) for v in by.values()]
    if len(dm)<2: return None
    mu=mean(dm); se=(sum((x-mu)**2 for x in dm)/(len(dm)-1)/len(dm))**0.5
    return dict(mean=mu,se=se,days=len(dm))
def compare(rows,k):
    m=daywise(rows,lambda r:(r[k]-r["y"])**2-(r["M"]-r["y"])**2)
    m["clear"]=m["days"]>=5 and m["mean"]<0 and -m["mean"]>=2*m["se"]
    return m
def fee(p): return math.ceil(0.07*p*(1-p)*100-1e-9)/100
def trades(rows,days):
    """One contract per signal with the live rule (fair = 0.5*C + 0.5*mid, 8-point edge). Taker pays the ask (or 1-bid for NO)
    plus the taker fee. Maker posts 1c better than the best bid (or joins it), cancelled at the day start, no fee."""
    tk=[]; mk=[]; tries=0
    for r in rows:
        bid,ask,fair,y=r["bid"],r["ask"],r["B"],r["y"]
        side,price,q=max([("yes",ask,fair),("no",1-bid,1-fair)],key=lambda x:x[2]-x[1])
        if q-price>=EDGE-1e-9:
            win=(y==1)==(side=="yes"); tk.append(dict(day=r["day"],side=side,price=price,pnl=(1 if win else 0)-price-fee(price),win=win,mid=r["M"]))
        yb=round(bid+0.01,2); iy=yb<round(ask,2); ya=round(ask-0.01,2); ino=ya>round(bid,2)
        side,price,q,imp=max([("yes",yb if iy else round(bid,2),fair,iy),("no",round(1-(ya if ino else ask),2),1-fair,ino)],key=lambda x:x[2]-x[1])
        if q-price>=EDGE-1e-9 and 0<price<1:
            tries+=1
            if side=="yes": lo=r["lo"]; filled=lo is not None and (lo<=price+1e-9 if imp else lo<price-1e-9)
            else: a=1-price; hi=r["hi"]; filled=hi is not None and (hi>=a-1e-9 if imp else hi>a+1e-9)
            if filled:
                win=(y==1)==(side=="yes"); mk.append(dict(day=r["day"],side=side,price=price,pnl=(1 if win else 0)-price,win=win,improved=imp))
    def summ(ts):
        if not ts: return dict(n=0)
        by={dd:0.0 for dd in days}
        for t in ts: by[t["day"]]+=t["pnl"]
        dl=list(by.values()); mu=mean(dl); se=(sum((x-mu)**2 for x in dl)/(len(dl)-1)/len(dl))**0.5
        return dict(n=len(ts),won=sum(t["win"] for t in ts),pnl=sum(t["pnl"] for t in ts),per_contract=mean([t["pnl"] for t in ts]),
                    avg_price=mean([t["price"] for t in ts]),day_mean=mu,day_se=se,clear=mu>2*se,yes=sum(t["side"]=="yes" for t in ts))
    out=dict(taker=summ(tk),maker=summ(mk)); out["maker"]["attempts"]=tries
    return out
def calib(rows,k):
    b={}
    for r in rows: b.setdefault(min(int(r[k]*10),9),[]).append(r)
    return [dict(bucket="%d-%d%%"%(i*10,i*10+10),n=len(v),avg=mean([x[k] for x in v]),freq=mean([x["y"] for x in v])) for i,v in sorted(b.items())]

def main():
    cli=load_cli(); runs=load_nbs()
    # training
    tr=[]
    for (st,day),y in cli.items():
        if TRAIN[0]<=day<=TRAIN[1]:
            f=features(runs,st,day)
            if f: tr.append((X(f),1 if y else 0,f["R"]))
    if len(tr)<1000: raise SystemExit("not enough training data yet: %d station-days"%len(tr))
    b=fit([(x,y) for x,y,_ in tr])
    mp=os.path.join(OUT,"rain_model.json"); os.makedirs(OUT,exist_ok=True)
    if os.path.exists(mp):   # frozen once written: the live v4 log (shadow.py) uses it; never overwrite silently
        old=json.load(open(mp,encoding="utf-8"))["coef"]
        if max(abs(x-y) for x,y in zip(old,b))>1e-6: print("NOTE: refit differs from the frozen rain_model.json; keeping the frozen one",old,b)
    else: json.dump(dict(coef=b,training="%s..%s"%TRAIN,station_days=len(tr),features="logit(R), log1p(100*Q in inches)",created=datetime.now().isoformat(timespec="minutes")),open(mp,"w",encoding="utf-8"),indent=1)
    trb_R=mean([(R-y)**2 for _,y,R in tr]); trb_C=mean([(sig(sum(bi*xi for bi,xi in zip(b,x)))-y)**2 for x,y,_ in tr])
    # holdout
    rows=[]; skip={"spread":0,"forecast":0}; agree=[0,0]
    for l in open(os.path.join(DATA,"kalshi_rain.jsonl"),encoding="utf-8"):
        m=json.loads(l); bid,ask=m.get("scan_bid"),m.get("scan_ask")
        if bid is None or ask is None or not (0<=bid<ask<=1) or ask-bid>SPREAD+1e-9: skip["spread"]+=1; continue
        day=d(m["day"]); f=features(runs,m["station"],day)
        if not f: skip["forecast"]+=1; continue
        y=1 if m["result"]=="yes" else 0; mid=(bid+ask)/2; c=C(b,f)
        if (m["station"],day) in cli: agree[0]+=1; agree[1]+=(cli[(m["station"],day)]==(y==1))
        sb,sa=m.get("start_bid"),m.get("start_ask")
        smid=(sb+sa)/2 if sb is not None and sa is not None and 0<=sb<sa<=1 and sa-sb<=SPREAD+1e-9 else None
        rows.append(dict(day=m["day"],station=m["station"],y=y,M=mid,R=f["R"],C=c,B=BLEND*c+(1-BLEND)*mid,bid=bid,ask=ask,lo=m.get("lo_after"),hi=m.get("hi_after"),smid=smid))
    days=sorted({r["day"] for r in rows})
    res=dict(plan="research/PLAN.md",generated=datetime.now().isoformat(timespec="minutes"),
             training=dict(station_days=len(tr),rain_rate=mean([y for _,y,_ in tr]),coef=b,brier_R=trb_R,brier_C=trb_C),
             holdout=dict(markets=len(rows),days=len(days),first=days[0] if days else None,last=days[-1] if days else None,skipped=skip,
                          rain_rate=mean([r["y"] for r in rows]),cli_agreement=(agree[1]/agree[0]) if agree[0] else None,cli_checked=agree[0]),
             brier={k:brier(rows,k) for k in ("M","R","C","B")},
             vs_market={k:compare(rows,k) for k in ("R","C","B")},
             trading=trades(rows,days),
             calibration=dict(C=calib(rows,"C"),M=calib(rows,"M")))
    mv=[(r["smid"]-r["M"])*(1 if r["C"]>r["M"] else -1) for r in rows if r["smid"] is not None and abs(r["C"]-r["M"])>=0.05]
    res["price_moves"]=dict(n=len(mv),toward=sum(x>0.004 for x in mv),away=sum(x<-0.004 for x in mv),mean=mean(mv))
    st={}
    for r in rows: st.setdefault(r["station"],[]).append(r)
    res["by_station"]={k:dict(n=len(v),brier_C=brier(v,"C"),brier_M=brier(v,"M")) for k,v in sorted(st.items())}
    tk,mk=res["trading"]["taker"],res["trading"]["maker"]
    edge=any(res["vs_market"][k]["clear"] for k in ("C","B")) and (tk.get("clear") or mk.get("clear"))
    res["verdict"]="edge demonstrated on past data" if edge else "no edge demonstrated on past data"
    os.makedirs(OUT,exist_ok=True)
    json.dump(res,open(os.path.join(OUT,"rain_backtest.json"),"w",encoding="utf-8"),indent=1)
    open(os.path.join(OUT,"rain_backtest.md"),"w",encoding="utf-8").write(report(res))
    print(report(res))
def f3(x): return "n/a" if x is None else "%.4f"%x
def report(r):
    h=r["holdout"]; t=r["training"]; L=["# Rain backtest results","","Plan: research/PLAN.md (written before any data was fetched). Generated %s."%r["generated"],"",
      "**Verdict (pre-registered rule): %s.**"%r["verdict"],"",
      "Holdout: %d markets over %d market days (%s to %s); %.0f%% rained. Skipped: %d wide/missing quotes, %d missing forecasts. CLI vs Kalshi results agree on %s of %d checked."%(
        h["markets"],h["days"],h["first"],h["last"],100*(h["rain_rate"] or 0),h["skipped"]["spread"],h["skipped"]["forecast"],
        "n/a" if h["cli_agreement"] is None else "%.1f%%"%(100*h["cli_agreement"]),h["cli_checked"]),
      "Training: %d station-days, %.0f%% rained, coefficients a=%.3f b=%.3f c=%.3f; in-sample Brier raw %.4f -> calibrated %.4f."%(
        t["station_days"],100*t["rain_rate"],t["coef"][0],t["coef"][1],t["coef"][2],t["brier_R"],t["brier_C"]),"",
      "| Forecast | Brier | Minus market, per market | 2 standard errors | Clear? |","|---|---|---|---|---|",
      "| Market mid (M) | %s | | | |"%f3(r["brier"]["M"])]
    for k,lab in (("R","Raw station forecast (R)"),("C","Calibrated station forecast (C)"),("B","Bot blend 50/50 (B)")):
        v=r["vs_market"][k]; L.append("| %s | %s | %+.4f | %.4f | %s |"%(lab,f3(r["brier"][k]),v["mean"],2*v["se"],"yes" if v["clear"] else "no"))
    L+=["","| Paper trading, 1 contract per signal | Trades | Won | Net P&L | Per contract | Avg price | Clear (day mean > 2 SE)? |","|---|---|---|---|---|---|---|"]
    for k,lab in (("taker","Pay the ask (taker, fees)"),("maker","Limit order (maker, no fee)")):
        v=r["trading"][k]
        if not v.get("n"): L.append("| %s | 0 | | | | | |"%lab); continue
        L.append("| %s | %d%s | %d | $%.2f | %+.1f¢ | %.0f¢ | %s |"%(lab,v["n"],(" of %d tried"%v["attempts"]) if k=="maker" else "",v["won"],v["pnl"],100*v["per_contract"],100*v["avg_price"],"yes" if v["clear"] else "no"))
    pm=r["price_moves"]
    L+=["","Price moves (5+ point disagreements): %d markets, toward the forecast %d, away %d, average %s points."%(pm["n"],pm["toward"],pm["away"],"n/a" if pm["mean"] is None else "%+.2f"%(100*pm["mean"])),
        "","Calibration (C): "+"; ".join("%s n=%d said %.0f%% rained %.0f%%"%(x["bucket"],x["n"],100*x["avg"],100*x["freq"]) for x in r["calibration"]["C"]),
        "","Calibration (market): "+"; ".join("%s n=%d said %.0f%% rained %.0f%%"%(x["bucket"],x["n"],100*x["avg"],100*x["freq"]) for x in r["calibration"]["M"])]
    return "\n".join(L)+"\n"
if __name__=="__main__": main()
