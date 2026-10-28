"""Risk clusters and capital efficiency (added 2026-10-22, platform upgrade phases 17-18). Read-only helpers.

Positions are not independent just because their tickers differ. Weather markets on the same day in the same region
share one weather system, so they form one risk cluster: weather:<date>:<region>. Exposure is summed per cluster.
The shadow selector applies a research cap per cluster. The frozen v3 rules are unchanged; they have only the 15%
total cap.

Capital efficiency: a small edge that frees its money quickly can beat a large one that locks it up for days. For
settled trades: capital = cost + fee, hours held = settle time - entry time, and profit per dollar per day = pnl /
capital / days. Python 3.8+."""
from datetime import datetime
REGION={}
for r,cities in (("northeast",("NYC","NY","BOS","PHIL","EWR","TTN","PVD","DC","PIT")),
                 ("southeast",("ATL","MIA","TPA","NOLA","WPB")),
                 ("midwest",("CHI","IND","CMH","MKE","MIN","STL","LEX","SDF","DET","DTW","SGF")),
                 ("south_central",("DAL","HOU","AUS","SATX","OKC","CLL")),
                 ("mountain_southwest",("DEN","PHX","ABQ","LV")),
                 ("west_coast",("LAX","SFO","SEA","SAN"))):
    for c in cities: REGION[c]=r
def city_of(ticker):
    p=(ticker or "").split("-")
    if not p or len(p)<2: return None
    if p[0]=="KXRAIN": return p[2] if len(p)>2 else None
    for pre in ("KXHIGHT","KXLOWT","KXHIGH","KXLOW"):
        if p[0].startswith(pre): return p[0][len(pre):] or None
    return None
def day_of(ticker):
    try: return datetime.strptime(ticker.split("-")[1],"%y%b%d").date().isoformat()
    except (IndexError,ValueError): return None
def cluster(ticker):
    """weather:<date>:<region> for daily weather markets, else event:<event ticker> (one event = one latent outcome)."""
    c=city_of(ticker); d=day_of(ticker)
    if c and d: return "weather:%s:%s"%(d,REGION.get(c,"other:"+c))
    return "event:"+(ticker or "").rsplit("-",1)[0]
def exposure(positions):
    """positions: [(ticker, dollars at risk)] -> {cluster: dollars}."""
    out={}
    for t,x in positions: out[cluster(t)]=out.get(cluster(t),0.0)+(x or 0.0)
    return out
def capital_rows(trades):
    """Settled trades -> [(ticker, capital, hours held, pnl, profit per dollar per day)]."""
    out=[]
    for r in trades:
        if r.get("status")!="settled" or not r.get("settled_ts") or not r.get("ts"): continue
        cap=(r.get("cost") or 0)+(r.get("fee") or 0); h=max((r["settled_ts"]-r["ts"])/3600.0,1e-9)
        out.append((r.get("ticker"),cap,h,r.get("pnl") or 0.0,((r.get("pnl") or 0.0)/cap/(h/24.0)) if cap>0 else None))
    return out
def capital_summary(trades):
    rows=capital_rows(trades)
    if not rows: return None
    cap_h=sum(c*h for _,c,h,_,_ in rows); pnl=sum(p for _,_,_,p,_ in rows)
    return dict(trades=len(rows),capital=sum(c for _,c,_,_,_ in rows),avg_hours=sum(h for _,_,h,_,_ in rows)/len(rows),
                pnl=pnl,per_dollar_day=(pnl/(cap_h/24.0)) if cap_h>0 else None)
