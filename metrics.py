"""Strategy metrics (added 2026-10-22, platform upgrade phase 32). Read-only arithmetic on rows the caller passes in.

No single number decides anything. Every figure comes with its sample size, and a win rate is never shown without
its count. Trades are rows with ts, settled_ts, side, price, fair (the model's chance for the chosen side), n, cost,
fee, status, result and pnl, as in paper.db's trades table. Python 3.8+."""
import risk
from tbcommon import clock
def _settled(trades):
    st=[r for r in trades if r.get("status")=="settled" and r.get("pnl") is not None]
    return sorted(st,key=lambda r:(r.get("settled_ts") or r.get("ts") or 0))
def max_drawdown(pnls):
    """Largest fall of cumulative P&L from its running peak (starting at 0), as a positive number."""
    peak=cum=0.0; dd=0.0
    for p in pnls:
        cum+=p; peak=max(peak,cum); dd=max(dd,peak-cum)
    return dd
def daily(trades):
    """{settle date: pnl} for settled trades, by the date of settlement in the bot's zone (UTC-4; before 2026-10-23 it
    was this PC's zone, the same date whenever the PC is set to La Paz time)."""
    out={}
    for r in _settled(trades):
        d=clock.bot_date(r.get("settled_ts") or r.get("ts") or 0).isoformat(); out[d]=out.get(d,0.0)+r["pnl"]
    return out
def sharpe_like(day_pnl,min_days=5):
    """Mean daily P&L / its standard deviation, over settle days. Not annualized; None below min_days or with no spread."""
    x=list(day_pnl.values())
    if len(x)<min_days: return None
    m=sum(x)/len(x); v=sum((a-m)**2 for a in x)/(len(x)-1)
    return m/v**0.5 if v>0 else None
def correlation(a,b,min_days=5):
    """Correlation of two strategies' daily P&L over the days both settled something."""
    ks=sorted(set(a)&set(b))
    if len(ks)<min_days: return None,len(ks)
    x=[a[k] for k in ks]; y=[b[k] for k in ks]; mx=sum(x)/len(x); my=sum(y)/len(y)
    sx=sum((v-mx)**2 for v in x)**0.5; sy=sum((v-my)**2 for v in y)**0.5
    return ((sum((u-mx)*(v-my) for u,v in zip(x,y))/(sx*sy)) if sx>0 and sy>0 else None),len(ks)
def summary(trades):
    """The phase-32 metrics for one strategy's trades. Returns None when nothing has settled."""
    st=_settled(trades)
    if not st: return None
    n=len(st); wins=sum(1 for r in st if r.get("result")==r.get("side")); prof=sum(1 for r in st if r["pnl"]>0)
    pnl=sum(r["pnl"] for r in st); contracts=sum(r.get("n") or 0 for r in st)
    ev=[(r.get("n") or 0)*(r["fair"]-r["price"])-(r.get("fee") or 0) for r in st if r.get("fair") is not None and r.get("price") is not None]
    br=[(r["fair"]-(1.0 if r.get("result")==r.get("side") else 0.0))**2 for r in st if r.get("fair") is not None]
    dp=daily(trades); cap=risk.capital_summary(trades)
    held=[(r["settled_ts"]-r["ts"])/3600.0 for r in st if r.get("settled_ts") and r.get("ts")]
    span=((st[-1].get("settled_ts") or 0)-min(r.get("ts") or 0 for r in st))/86400.0 if st[-1].get("settled_ts") else None
    deployed=sum((r.get("cost") or 0)+(r.get("fee") or 0) for r in st)
    clus={}
    for r in st: clus[risk.cluster(r.get("ticker"))]=clus.get(risk.cluster(r.get("ticker")),0.0)+r["pnl"]
    worst=min(clus.items(),key=lambda x:x[1]) if clus else (None,None)
    return dict(n=n,wins=wins,win_rate=wins/n,profitable=prof,profitable_rate=prof/n,pnl=pnl,per_trade=pnl/n,
                per_contract=(pnl/contracts) if contracts else None,contracts=contracts,
                expected=sum(ev) if ev else None,realized_minus_expected=(pnl-sum(ev)) if ev else None,
                brier=(sum(br)/len(br)) if br else None,max_drawdown=max_drawdown([r["pnl"] for r in st]),
                sharpe_like=sharpe_like(dp),days=len(dp),largest_loss=min(r["pnl"] for r in st),
                avg_hours=(sum(held)/len(held)) if held else None,
                turnover_per_day=(deployed/span) if span and span>0 else None,
                per_dollar_day=cap["per_dollar_day"] if cap else None,
                worst_cluster=worst[0],worst_cluster_pnl=worst[1])
