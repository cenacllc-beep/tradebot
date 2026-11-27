"""Win/loss attribution ("learn from every bet"; added 2026-11-26). READ-ONLY and descriptive only: it changes no rule.

For every settled bet it can find on this computer it asks three questions, per source:
  1. Calibration: when the model said X%, how often did the side win, and the same for the market's price at entry
     (reliability table by tenths, Brier score and its Murphy decomposition: reliability, resolution, uncertainty and
     the within-bin remainder that makes the identity exact), over everything and over a rolling 14-day window.
  2. Luck, skill or cost: the profit split exactly into
        claimed edge   n x (model chance - decision price)        what the model said it was getting
        market's view  n x (market chance - model chance)         the part of that claim the market's own chance did not grant
        luck           n x (outcome - market chance)              what happened against the market's odds; its standard error
                                                                   is sqrt(sum n^2 p(1-p)) with p the market's chance
        execution      -n x (fill price - decision price)
        fees           -fee
        other          whatever is left (void/scalar payouts, rounding)
     claimed edge + market's view = n x (market chance - price): the spread paid over the market's own chance.
  3. Edge decay: rolling 14-day profit per contract and the Brier gap against the market, each with standard errors
     clustered by day (cities on one day share weather; 15-minute windows on one day share a market mood).
Sources (each optional; a missing file is noted, never an error): paper.db v3 rain trades (with their decision rows or
obs for the chance used), the shadow limit-order ledger, the airport-forecast forward rows (v4_paper with v4_obs),
research/data/live15.db, research/data/live20/paper.jsonl and logs/account.json (descriptive: the bot's fills and
settlements next to the ones made outside it). Also, for calibration only, every resolved v3 and airport-forecast rain
market (YES chances), not just the ones bet on.
No network. Databases are opened read-only (SQLite mode=ro). It writes only research/results/attribution.md and
attribution.json (TRADEBOT_RESULTS points tests elsewhere).  python attribution.py      (or: run attribution)
Nothing here is a test: a reading is a description of what happened, never a reason to change the bot. Python 3.8+."""
import os, sys, json, math, sqlite3
from datetime import date, datetime, timedelta, timezone
HERE=os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0,HERE)
from config import DB, BLEND
from tbcommon.db import connect_ro
from tbcommon.parse import market_day
import calibration as CAL
OUTDIR=os.getenv("TRADEBOT_RESULTS") or os.path.join(HERE,"research","results")
LIVE15_DB=os.getenv("LIVE15_DB") or os.path.join(HERE,"research","data","live15.db")
LIVE20_DATA=os.getenv("LIVE20_DATA") or os.path.join(HERE,"research","data","live20")
ACCOUNT_JSON=os.getenv("TRADEBOT_ACCOUNT_JSON") or os.path.join(HERE,"logs","account.json")
WINDOW_DAYS=14; MIN_BETS,MIN_DAYS=30,5; Z=2.0
NOTE="Descriptive only: this report changes no rule, threshold or model. Patterns here are hypotheses for a written plan, never a reason to change the bot directly."

# ---------- reading (read-only) ----------
def _abs(p): return p if os.path.isabs(p) else os.path.join(HERE,p)
def ro(path):
    p=_abs(path)
    return connect_ro(p) if os.path.exists(p) else None
def rows(c,sql,args=()):
    try: cur=c.execute(sql,args); names=[d[0] for d in cur.description]; return [dict(zip(names,r)) for r in cur.fetchall()]
    except sqlite3.Error: return []
def num(x):
    try: x=float(x)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None
def side_p(p_yes,side): return None if p_yes is None else (p_yes if side=="yes" else 1-p_yes)
def bet(day,ticker,side,n,dprice,fill,p_model,p_mkt,win,fee,pnl,p_raw=None):
    """One settled bet, every chance for the side bought. day: ISO date string. Without a logged market chance (p_mkt
    None) the decision price stands for it (marked mkt_from_price): the spread term is then zero for that bet.
    win None: a scalar or void result (not yes/no). Such a bet keeps its ledger P&L; it is left out of calibration and
    luck, and what its payout adds goes to "other". p_raw: v3's own forecast for the side (paper bets), before the blend."""
    return dict(day=day,ticker=ticker,side=side,n=n,dprice=dprice,fill=fill,p_model=p_model,p_mkt=dprice if p_mkt is None else p_mkt,
                mkt_from_price=p_mkt is None,win=win,fee=fee or 0.0,pnl=pnl,p_raw=p_raw)
def outcome(result,side):
    """(ok, win): yes/no gives 1/0; another recorded result (scalar, void) gives win None; nothing recorded is not ok."""
    if result in ("yes","no"): return True,(1 if result==side else 0)
    return (bool(result) and isinstance(result,str)),None
def _iso(d): return d.isoformat() if d else None

def paper_sources(c):
    """{key: (bets, skipped)} from paper.db, and {key: [(p_model_yes, p_market_yes, y, day)]} for calibration-only."""
    out={}; allm={}
    dec={}
    for r in rows(c,"select trade_ref,p_win,mid,price from decisions where trade_ref is not null order by ts"): dec[r["trade_ref"]]=r
    obs={r["ticker"]:r for r in rows(c,"select ticker,fc,mid,result from obs where version='v3'")}
    b=[]; sk=0
    for t in rows(c,"select id,ticker,side,price,fair,n,fee,result,pnl from trades where version='v3' and status='settled' and ticker like 'KXRAIN%' order by id"):
        d=dec.get("trades:%d"%t["id"]) or {}; o=obs.get(t["ticker"]) or {}
        mid=num(d.get("mid")) if d.get("mid") is not None else num(o.get("mid"))
        pm=num(d.get("p_win")) if d.get("p_win") is not None else num(t["fair"])
        price=num(t["price"]); n=t["n"] or 0; ok,w=outcome(t["result"],t["side"]); day=_iso(market_day(t["ticker"]))
        if not ok or not day or t["side"] not in ("yes","no") or None in (price,pm,num(t["pnl"])) or n<1: sk+=1; continue
        b.append(bet(day,t["ticker"],t["side"],n,num(d.get("price")) or price,price,pm,side_p(mid,t["side"]),
                     w,num(t["fee"]),num(t["pnl"]),p_raw=side_p(num(o.get("fc")),t["side"])))
    out["paper_v3"]=(b,sk)
    b=[]; sk=0
    for r in rows(c,"select ticker,side,price,fair,bid,ask,n,fee,result,pnl from shadow_orders where status='settled' order by id"):
        price,pm,bid,ask=num(r["price"]),num(r["fair"]),num(r["bid"]),num(r["ask"]); n=r["n"] or 0
        ok,w=outcome(r["result"],r["side"]); day=_iso(market_day(r["ticker"]))
        if not ok or not day or r["side"] not in ("yes","no") or None in (price,pm,bid,ask,num(r["pnl"])) or n<1: sk+=1; continue
        b.append(bet(day,r["ticker"],r["side"],n,price,price,pm,side_p((bid+ask)/2,r["side"]),w,num(r["fee"]),num(r["pnl"])))
    out["shadow_maker"]=(b,sk)
    for kind in ("taker","maker"):
        b=[]; sk=0
        for r in rows(c,"select p.ticker,p.side,p.price,p.result,p.pnl,v.fc,v.mid from v4_paper p join v4_obs v on v.ticker=p.ticker "
                        "where p.kind=? and p.filled=1 and p.pnl is not null",(kind,)):
            price,fc,mid,pnl=num(r["price"]),num(r["fc"]),num(r["mid"]),num(r["pnl"])
            day=_iso(market_day(r["ticker"]))
            if r["result"] not in ("yes","no") or not day or r["side"] not in ("yes","no") or None in (price,fc,mid,pnl): sk+=1; continue
            w=1 if r["result"]==r["side"] else 0
            fee=max(0.0,round((w-price)-pnl,6))   # the forward rule's taker fee (maker 0), recovered from its own P&L
            b.append(bet(day,r["ticker"],r["side"],1,price,price,side_p(BLEND*fc+(1-BLEND)*mid,r["side"]),side_p(mid,r["side"]),w,fee,pnl))
        out["v4_"+kind]=(b,sk)
    allm["obs_v3"]=[(num(r["fc"]),num(r["mid"]),1 if r["result"]=="yes" else 0,_iso(market_day(k))) for k,r in obs.items()
                    if k.startswith("KXRAIN") and r["result"] in ("yes","no") and num(r["fc"]) is not None and num(r["mid"]) is not None]
    allm["obs_v4"]=[(num(r["fc"]),num(r["mid"]),1 if r["result"]=="yes" else 0,_iso(market_day(r["ticker"])))
                    for r in rows(c,"select ticker,fc,mid,result from v4_obs where result in ('yes','no')") if num(r["fc"]) is not None and num(r["mid"]) is not None]
    return out,allm

def live15_bets(c):
    b=[]; sk=0
    for r in rows(c,"select \"window\" as w,asset,side,price,fee,p_up,yes_ask,no_ask,result,pnl,close_ts from bets where status='settled' order by id"):
        price,pu,pnl,ct=num(r["price"]),num(r["p_up"]),num(r["pnl"]),num(r["close_ts"])
        ok,w=outcome(r["result"],r["side"])
        if not ok or r["side"] not in ("yes","no") or None in (price,pu,pnl,ct): sk+=1; continue
        ya,na=num(r["yes_ask"]),num(r["no_ask"])
        mid=min(1.0,max(0.0,(ya+1-na)/2)) if ya is not None and na is not None else None
        pm=side_p(mid,r["side"])   # None without a two-sided quote: the ask paid then stands for the market's chance (bet())
        b.append(bet(datetime.fromtimestamp(ct,timezone.utc).date().isoformat(),"%s %s"%(r["asset"],r["w"]),r["side"],1,price,price,
                     side_p(pu,r["side"]),pm,w,num(r["fee"]),pnl))
    return b,sk

def live20_bets(path):
    b=[]; sk=0
    with open(path,encoding="utf-8") as f:
        for ln in f:
            try: r=json.loads(ln)
            except ValueError: sk+=1; continue
            if not isinstance(r,dict): sk+=1; continue
            p,price,ask,win,prof=num(r.get("p")),num(r.get("price")),num(r.get("ask")),num(r.get("win")),num(r.get("profit"))
            n=num(r.get("contracts"))
            if None in (p,price,win,prof,n) or n<1 or win not in (0.0,1.0) or _d(r.get("day")) is None: sk+=1; continue
            dp=ask if ask is not None else price
            b.append(bet(str(r.get("day")),r.get("ticker"),r.get("side"),n,dp,price,p,None,int(win),num(r.get("fee")) or 0.0,prof*n))
    return b,sk

def account_view(path):
    """Kalshi's own fills and settlements (live.py snapshot), grouped by live.py's own "who" mark: bot, mixed (a manual trade
    on a bot market) or you (made outside the bot). A row without the mark falls back to its bot flag. Descriptive only."""
    with open(path,encoding="utf-8") as f: a=json.load(f)
    out=dict(env=a.get("env"),ts=a.get("ts"),days=a.get("days"),ok=a.get("ok"),groups={})
    def who_of(x):
        w=x.get("who")
        return w if w in ("bot","mixed","you") else ("bot" if x.get("bot") else "you")
    for who in ("bot","mixed","you"):
        fl=[x for x in a.get("fills") or [] if isinstance(x,dict) and who_of(x)==who]
        st=[x for x in a.get("settlements") or [] if isinstance(x,dict) and who_of(x)==who]
        out["groups"][who]=dict(fills=len(fl),contracts=sum(num(x.get("count")) or 0 for x in fl),fill_fees=sum(num(x.get("fee")) or 0 for x in fl),
                                settlements=len(st),cost=sum(num(x.get("cost")) or 0 for x in st),revenue=sum(num(x.get("revenue")) or 0 for x in st),
                                won=sum(1 for x in st if (num(x.get("revenue")) or 0)>(num(x.get("cost")) or 0)))
        g=out["groups"][who]; g["settled_net_before_fees"]=g["revenue"]-g["cost"]
    return out

# ---------- arithmetic ----------
def brier_parts(pairs,k=10):
    """Murphy decomposition by tenths: brier = reliability - resolution + uncertainty + within_bin (exact).
    within_bin is zero when every forecast in a bin is the same; it is the spread of forecasts inside the bins."""
    N=len(pairs)
    if not N: return None
    ob=sum(y for _,y in pairs)/N; bins={}
    for p,y in pairs: bins.setdefault(CAL.bin_of(p,k),[]).append((p,y))
    rel=res=wb=0.0
    for v in bins.values():
        nk=len(v); fk=sum(p for p,_ in v)/nk; ok=sum(y for _,y in v)/nk
        rel+=nk*(fk-ok)**2; res+=nk*(ok-ob)**2
        wb+=sum((p-fk)**2-2*(p-fk)*(y-ok) for p,y in v)
    return dict(n=N,brier=sum((p-y)**2 for p,y in pairs)/N,reliability=rel/N,resolution=res/N,uncertainty=ob*(1-ob),within_bin=wb/N,base_rate=ob)
def ratio_cse(groups):
    """groups: [(sum_y, sum_n)] per cluster (day). (mean = total y / total n, cluster-robust standard error or None)."""
    T=sum(n for _,n in groups)
    if not T: return None,None
    m=sum(y for y,_ in groups)/T; D=len(groups)
    if D<2: return m,None
    return m,math.sqrt(D/(D-1.0)*sum((y-m*n)**2 for y,n in groups))/T
def by_day(bs,f,w=lambda b:1.0):
    g={}
    for b in bs: s=g.setdefault(b["day"],[0.0,0.0]); s[0]+=f(b); s[1]+=w(b)
    return list(g.values())
def gap(b): return (b["p_model"]-b["win"])**2-(b["p_mkt"]-b["win"])**2
def binary(bs): return [b for b in bs if b["win"] is not None]
def split(bs):
    """The exact profit split (dollars) and its standard errors. Luck covers yes/no bets only; a scalar or void bet's
    payout lands in "other", so the net always equals the ledger's own P&L."""
    S=lambda f,xs=bs:sum(f(b) for b in xs); yn=binary(bs)
    pnl=S(lambda b:b["pnl"]); claimed=S(lambda b:b["n"]*(b["p_model"]-b["dprice"])); mview=S(lambda b:b["n"]*(b["p_mkt"]-b["p_model"]))
    luck=S(lambda b:b["n"]*(b["win"]-b["p_mkt"]),yn); ex=-S(lambda b:b["n"]*(b["fill"]-b["dprice"])); fees=-S(lambda b:b["fee"])
    other=pnl-(claimed+mview+luck+ex+fees)
    lse=math.sqrt(S(lambda b:b["n"]**2*b["p_mkt"]*(1-b["p_mkt"]),yn))
    mluck=S(lambda b:b["n"]*(b["win"]-b["p_model"]),yn); mse=math.sqrt(S(lambda b:b["n"]**2*b["p_model"]*(1-b["p_model"]),yn))
    return dict(pnl=pnl,claimed_edge=claimed,market_view=mview,spread_vs_market=claimed+mview,luck=luck,luck_se=lse,
                luck_z=(luck/lse) if lse>0 else None,execution=ex,fees=fees,other=other,
                vs_model=mluck,vs_model_se=mse,vs_model_z=(mluck/mse) if mse>0 else None)
def verdict(sp,n,days,who="model"):
    """Plain words: is the loss mostly miscalibration, fees and costs, or chance? Two-sided, |z| >= 2 to name a direction.
    who: what made the chance used for the bet (for the weather ledgers, the 50/50 blend of forecast and market)."""
    if n<MIN_BETS or days<MIN_DAYS: return "Too few bets to say (%d bets on %d days; at least %d bets on %d days are needed)."%(n,days,MIN_BETS,MIN_DAYS)
    lz,mz=sp["luck_z"],sp["vs_model_z"]; cost=sp["spread_vs_market"]+sp["execution"]+sp["fees"]+sp["other"]
    s=["The %s claimed %s of edge; at the market's own chances the same bets were worth %s before fees, so %s of the claim was the %s disagreeing with the market."%(
        who,usd(sp["claimed_edge"]),usd(sp["spread_vs_market"]),usd(-sp["market_view"]),who)]
    if mz is not None and mz<=-Z: s.append("The sides bought won less often than the %s said, by %.1f standard errors: its chances were too high (miscalibration)."%(who,-mz))
    elif mz is not None and mz>=Z: s.append("The sides bought won more often than the %s said, by %.1f standard errors."%(who,mz))
    else: s.append("Wins matched the chances of the %s within chance (%s standard errors)."%(who,"-" if mz is None else "%.1f"%mz))
    if lz is not None and lz<=-Z: s.append("Against the market's chances the outcomes were worse by more than chance explains (%.1f standard errors): the bets leaned the wrong way."%lz)
    elif lz is not None and lz>=Z: s.append("Against the market's chances the outcomes were better by more than chance explains (%.1f standard errors). That is a pattern to test on new data, not proof of skill."%lz)
    else: s.append("Against the market's chances the outcomes were within what chance alone gives (%s standard errors), so there is no sign of skill or of anti-skill."%("-" if lz is None else "%.1f"%lz))
    if sp["pnl"]>=0: s.append("Net %s: a gain, which on this evidence is %s."%(usd(sp["pnl"]),"more than chance" if lz is not None and lz>=Z else "within chance"))
    elif lz is not None and lz<=-Z and abs(sp["luck"])>=abs(min(cost,0)): s.append("Bottom line: the loss of %s is mostly miscalibration (outcomes worse than the market's odds), with %s of fees and costs on top."%(usd(-sp["pnl"]),usd(-min(cost,0))))
    elif cost<0 and (sp["luck"]>=0 or abs(cost)>=abs(sp["luck"])): s.append("Bottom line: the loss of %s is mostly fees and costs (%s: the price paid over the market's own chance, fees and execution); chance added %s."%(usd(-sp["pnl"]),usd(-cost),usd(sp["luck"])))
    else: s.append("Bottom line: the loss of %s is mostly chance (%s against the market's odds, within %.1f standard errors), with %s of fees and costs."%(usd(-sp["pnl"]),usd(sp["luck"]),abs(lz or 0),usd(-min(cost,0))))
    return " ".join(s)
def usd(x): return ("-$%.2f"%-x) if x<-0.004 else "$%.2f"%(x if x>0 else 0.0)
def _d(s):
    try: return date.fromisoformat(str(s)[:10])
    except ValueError: return None
def rolling(bs,pairs_fn):
    """Windows of WINDOW_DAYS days ending on each day that has data: bets, days, profit per contract (day-clustered SE),
    Brier model and market, and the gap model minus market (day-clustered SE). pairs_fn gives (p_model, p_mkt, y, day)."""
    rs=[x for x in pairs_fn(bs) if _d(x[3])]; days=sorted({_d(x[3]) for x in rs}); out=[]
    for end in days:
        lo=end-timedelta(days=WINDOW_DAYS-1)
        w=[x for x in rs if lo<=_d(x[3])<=end]; wb=[b for b in bs if _d(b["day"]) and lo<=_d(b["day"])<=end]
        g={}
        for pm,pk,y,dd in w: s=g.setdefault(dd,[0.0,0.0]); s[0]+=(pm-y)**2-(pk-y)**2; s[1]+=1
        gm,gse=ratio_cse(list(g.values()))
        row=dict(end=end.isoformat(),days=len(g),n=len(w),brier_model=sum((pm-y)**2 for pm,_,y,_ in w)/len(w),
                 brier_market=sum((pk-y)**2 for _,pk,y,_ in w)/len(w),gap=gm,gap_se=gse)
        if wb:
            pp,pse=ratio_cse(by_day(wb,lambda b:b["pnl"],lambda b:b["n"]))
            row.update(bets=len(wb),profit_per_contract=pp,profit_se=pse)
        out.append(row)
    return out
def bet_pairs(bs): return [(b["p_model"],b["p_mkt"],b["win"],b["day"]) for b in binary(bs)]
def calib(pairs,raw=None):
    """Reliability tables and Brier parts for the model and the market; raw [(p, y)] adds v3's own forecast (paper bets)."""
    m=[(p,y) for p,_,y,_ in pairs]; k=[(q,y) for _,q,y,_ in pairs]
    tab=lambda r:[dict(bin="%d-%d%%"%(10*i,10*i+10),n=n,said=mp,happened=of,low=lo,high=hi) for i,n,mp,of,lo,hi in CAL.reliability(r)]
    out=dict(model=dict(table=tab(m),parts=brier_parts(m)),market=dict(table=tab(k),parts=brier_parts(k)))
    if raw: out["raw"]=dict(table=tab(raw),parts=brier_parts(raw))
    return out
def analyse(bs,skipped,key=None):
    if not bs: return dict(bets=0,skipped=skipped,model_label=MODEL.get(key,"model"))
    who=MODEL.get(key,"model"); days=len({b["day"] for b in bs}); sp=split(bs); yn=binary(bs)
    pp,pse=ratio_cse(by_day(bs,lambda b:b["pnl"],lambda b:b["n"])); gm,gse=ratio_cse(by_day(yn,gap))
    raw=[(b["p_raw"],b["win"]) for b in yn if b["p_raw"] is not None]
    return dict(bets=len(bs),skipped=skipped,model_label=who,not_yes_no=len(bs)-len(yn),mkt_from_price=sum(1 for b in bs if b["mkt_from_price"]),
                contracts=sum(b["n"] for b in bs),days=days,won=sum(b["win"] for b in yn),
                profit_per_contract=pp,profit_se=pse,brier_gap=gm,brier_gap_se=gse,split=sp,verdict=verdict(sp,len(bs),days,who),
                calibration=calib(bet_pairs(bs),raw if raw and len(raw)==len(yn) else None),rolling=rolling(bs,bet_pairs))

# ---------- report ----------
LABEL={"paper_v3":"Paper bot, v3 rain (paper.db trades; model = blend (50/50 model+market))","shadow_maker":"Limit-order ledger (shadow, paper; model = blend (50/50 model+market))",
       "v4_taker":"Airport-forecast forward test, paying the ask (model = blend (50/50 model+market))","v4_maker":"Airport-forecast forward test, limit orders (model = blend (50/50 model+market))",
       "live15":"15-minute BTC/ETH paper bets (PLAN15F, live15.db)","live20":"PLAN20 cheap-side paper bets (live20 paper.jsonl)",
       "obs_v3":"v3 forecast vs price, every resolved rain market (YES chances)","obs_v4":"Airport forecast vs price, every resolved rain market (YES chances)"}
BLEND_LABEL="blend (50/50 model+market)"   # the chance the weather ledgers bet on: BLEND x forecast + (1 - BLEND) x mid
MODEL={"paper_v3":BLEND_LABEL,"shadow_maker":BLEND_LABEL,"v4_taker":BLEND_LABEL,"v4_maker":BLEND_LABEL,
       "live15":"model (PLAN15 random walk)","live20":"model (PLAN20 ridge)","obs_v3":"v3 forecast","obs_v4":"airport forecast"}
def collect():
    """({source: analysis or dict(missing=why)}, account view or None, notes)."""
    S={}; notes=[]
    c=ro(DB)
    if c is None:
        for k in ("paper_v3","shadow_maker","v4_taker","v4_maker","obs_v3","obs_v4"): S[k]=dict(missing="no paper.db")
    else:
        try: got,allm=paper_sources(c)
        finally: c.close()
        for k,(bs,sk) in got.items(): S[k]=analyse(bs,sk,k)
        for k,ps in allm.items():
            S[k]=dict(markets=len(ps),days=len({x[3] for x in ps}),calibration=calib(ps),rolling=rolling([],lambda _:ps)) if ps else dict(markets=0)
    c=ro(LIVE15_DB)
    if c is None: S["live15"]=dict(missing="no research/data/live15.db")
    else:
        try: S["live15"]=analyse(*live15_bets(c),key="live15")
        finally: c.close()
    p=os.path.join(LIVE20_DATA,"paper.jsonl")
    if os.path.exists(p):
        try: S["live20"]=analyse(*live20_bets(p),key="live20")
        except OSError as ex: S["live20"]=dict(missing="unreadable (%s)"%ex)
    else: S["live20"]=dict(missing="no research/data/live20/paper.jsonl")
    acct=None
    if os.path.exists(ACCOUNT_JSON):
        try: acct=account_view(ACCOUNT_JSON)
        except (OSError,ValueError) as ex: notes.append("logs/account.json unreadable (%s)"%ex)
    return S,acct,notes
def f3(x): return "-" if x is None else "%.4f"%x
def pc(x): return "-" if x is None else "%.0f%%"%(100*x)
def cents(x,se=None): return "-" if x is None else ("%+.1fc"%(100*x))+("" if se is None else " (SE %.1fc)"%(100*se))
def render(S,acct,notes,now):
    L=["# Win/loss attribution","","Generated %s. Read-only. %s"%(now,NOTE),"",
       "How to read it. *Calibration*: when a source said X%%, how often did the side (or YES) happen; the Brier score is the average squared miss (lower is better) "
       "and splits into reliability (how far the said chances sit from what happened; lower is better), resolution (how much the chances tell days apart; higher is better) "
       "and uncertainty (how hard the questions were), plus a small within-bin remainder that makes the sum exact. "
       "*Luck, skill or cost*: the profit is split exactly into the edge the model claimed, the part of that claim the market's own chance did not grant, "
       "luck (outcomes against the market's chances, with its standard error), execution, fees and other. "
       "*Edge decay*: rolling %d-day windows; standard errors count each day once. The window's Brier gap is pooled per market (each market weighs the same), "
       "so it is not the gate's day-mean statistic (each market day weighs the same). A direction is named only at 2 or more standard errors, and even then it is a description, not a test. "
       "For the weather ledgers (paper, shadow, airport test) the chance bet on is the %s, not the raw forecast."%(WINDOW_DAYS,BLEND_LABEL),""]
    for k in ("paper_v3","shadow_maker","v4_taker","v4_maker","live15","live20"):
        a=S.get(k) or {}; L+=["## "+LABEL[k],""]
        if a.get("missing"): L+=["Not available here: %s."%a["missing"],""]; continue
        if not a.get("bets"): L+=["No settled bets yet%s."%(" (%d rows left out: unreadable or not yes/no)"%a["skipped"] if a.get("skipped") else ""),""]; continue
        sp=a["split"]; who=a.get("model_label") or "model"
        L+=["Chance bet on: the %s. %d settled bets (%s contracts) on %d days, %d won%s%s. Bets on the %s: profit per contract %s; Brier gap minus market per bet %s."%(
              who,a["bets"],("%g"%a["contracts"]),a["days"],a["won"],"; %d scalar or void (kept with their ledger P&L, left out of calibration and luck)"%a["not_yes_no"] if a.get("not_yes_no") else "",
              "; %d left out (unreadable, no day or no result)"%a["skipped"] if a["skipped"] else "",who,
              cents(a["profit_per_contract"],a["profit_se"]),"-" if a["brier_gap"] is None else "%+.4f%s"%(a["brier_gap"],"" if a["brier_gap_se"] is None else " (SE %.4f)"%a["brier_gap_se"]))
            +(" For %d of them no market chance was logged, so the price paid stands for it."%a["mkt_from_price"] if a["mkt_from_price"] else ""),"",
            "**In words:** "+a["verdict"],"",
            "| Part of the profit | Dollars |","|---|---:|",
            "| Edge the %s claimed | %s |"%(who,usd(sp["claimed_edge"])),"| Part of the claim the market's chance did not grant | %s |"%usd(sp["market_view"]),
            "| = Price paid vs the market's own chance (spread) | %s |"%usd(sp["spread_vs_market"]),
            "| Luck: outcomes vs the market's chances, SE (not clustered) | %s (SE %s, %s standard errors) |"%(usd(sp["luck"]),usd(sp["luck_se"]),"-" if sp["luck_z"] is None else "%+.1f"%sp["luck_z"]),
            "| Execution: fill vs decision price | %s |"%usd(sp["execution"]),"| Fees | %s |"%usd(sp["fees"]),"| Other (void/scalar payouts, rounding) | %s |"%usd(sp["other"]),
            "| **Net profit** | **%s** |"%usd(sp["pnl"]),"",
            "Outcomes vs the chances of the %s: %s (SE %s, %s standard errors)."%(who,usd(sp["vs_model"]),usd(sp["vs_model_se"]),"-" if sp["vs_model_z"] is None else "%+.1f"%sp["vs_model_z"]),""]
        L+=calib_md(a["calibration"],"side bought",who)+rolling_md(a["rolling"],True)
    for k in ("obs_v3","obs_v4"):
        a=S.get(k) or {}; L+=["## "+LABEL[k],""]
        if a.get("missing"): L+=["Not available here: %s."%a["missing"],""]; continue
        if not a.get("markets"): L+=["No resolved markets yet.",""]; continue
        L+=["%d resolved markets on %d market days. Calibration only (no bets)."%(a["markets"],a["days"]),""]+calib_md(a["calibration"],"YES",MODEL.get(k,"model"))+rolling_md(a["rolling"],False)
    L+=["## Kalshi account (logs/account.json), descriptive",""]
    if not acct: L+=["Not available here (no account snapshot).",""]
    else:
        L+=["Kalshi's own fills and settlements (%s exchange) over its last %s days, grouped by live.py's own mark: bot, mixed (a manual trade on a bot market) or you (outside the bot). "
            "Trades outside the bot are not counted by its loss stops or by any line above."%(acct.get("env") or "unknown",acct.get("days") or "?"),"",
            "| Who | Fills | Contracts | Fees on fills | Settlements | Won | Cost | Paid out | Net before fees |","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for who,g in acct["groups"].items():
            L.append("| %s | %d | %g | %s | %d | %d | %s | %s | %s |"%(who,g["fills"],g["contracts"],usd(g["fill_fees"]),g["settlements"],g["won"],usd(g["cost"]),usd(g["revenue"]),usd(g["settled_net_before_fees"])))
        L.append("")
    L+=["## Notes",""]+["- "+n for n in notes]+["- Market chance at entry: the mid of the quote where one was logged (paper, shadow, airport test, 15-minute bets with both asks); "
        "where none was logged (PLAN20, which logs only the ask, and bets without a forecast-log row) the price paid stands for it, so the spread term is zero there.",
        "- Luck's standard error assumes bets settle independently; cities on one day share weather, so the true error is larger and |z| here is generous. The day-clustered errors in the windows allow for that.",
        "- "+NOTE]
    return L
def calib_md(cb,frame,who="model"):
    L=["Calibration (%s): said vs happened, by tenths; \"%s\" is the %s."%(frame,"Model",who),"","| Said | Model: bets | Model said | Happened | Market: bets | Market said | Happened |","|---|---:|---:|---:|---:|---:|---:|"]
    m={r["bin"]:r for r in cb["model"]["table"]}; k={r["bin"]:r for r in cb["market"]["table"]}
    for b in sorted(set(m)|set(k),key=lambda s:int(s.split("-")[0])):
        x,y=m.get(b),k.get(b)
        L.append("| %s | %s | %s | %s | %s | %s | %s |"%(b,x["n"] if x else 0,pc(x and x["said"]),pc(x and x["happened"]),y["n"] if y else 0,pc(y and y["said"]),pc(y and y["happened"])))
    L+=["","| Brier | Score | Reliability | Resolution | Uncertainty | Within-bin |","|---|---:|---:|---:|---:|---:|"]
    for key,name in (("model","Model: %s"%who),("market","Market"),("raw","v3 raw forecast (before the blend)")):
        p=(cb.get(key) or {}).get("parts")
        if p: L.append("| %s | %s | %s | %s | %s | %s |"%(name,f3(p["brier"]),f3(p["reliability"]),f3(p["resolution"]),f3(p["uncertainty"]),f3(p["within_bin"])))
    return L+[""]
def rolling_md(rw,bets):
    if not rw: return []
    show=rw[-10:]
    L=["Rolling %d-day windows (latest %d of %d; descriptive, no trend test):"%(WINDOW_DAYS,len(show),len(rw)),"",
       "| Window ending | Days | %sBrier model | Brier market | Gap (SE) |"%("Bets | Profit per contract (SE) | " if bets else "Markets | "),
       "|---|---:|"+("---:|---:|" if bets else "---:|")+"---:|---:|---:|"]
    for r in show:
        g="-" if r["gap"] is None else "%+.4f%s"%(r["gap"],"" if r["gap_se"] is None else " (%.4f)"%r["gap_se"])
        mid=("%d | %s | "%(r.get("bets",0),cents(r.get("profit_per_contract"),r.get("profit_se")))) if bets else "%d | "%r["n"]
        L.append("| %s | %d | %s%s | %s | %s |"%(r["end"],r["days"],mid,f3(r["brier_model"]),f3(r["brier_market"]),g))
    return L+[""]
def main():
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    S,acct,notes=collect(); now=datetime.now().strftime("%Y-%m-%d %H:%M")
    L=render(S,acct,notes,now)
    os.makedirs(OUTDIR,exist_ok=True)
    tmp=os.path.join(OUTDIR,"attribution.md.tmp")
    with open(tmp,"w",encoding="utf-8") as f: f.write("\n".join(L)+"\n")
    os.replace(tmp,os.path.join(OUTDIR,"attribution.md"))
    tmp=os.path.join(OUTDIR,"attribution.json.tmp")
    with open(tmp,"w",encoding="utf-8") as f: json.dump(dict(generated=now,note=NOTE,window_days=WINDOW_DAYS,labels=LABEL,model_labels=MODEL,sources=S,account=acct,notes=notes),f,indent=1,default=str)
    os.replace(tmp,os.path.join(OUTDIR,"attribution.json"))
    got=[k for k in ("paper_v3","shadow_maker","v4_taker","v4_maker","live15","live20") if (S.get(k) or {}).get("bets")]
    print("ATTRIBUTION: "+("; ".join("%s %d bets, net %s"%(k,S[k]["bets"],usd(S[k]["split"]["pnl"])) for k in got) or "no settled bets found")
          +" (descriptive only; research/results/attribution.md)")
if __name__=="__main__": main()
