"""Live prices for open paper positions: python marks.py  ->  appends one line to marks.jsonl
Read-only: opens paper.db read-only (sqlite URI mode=ro), never places, changes or cancels orders, and makes only Kalshi
public API reads (GET /markets, the same domain and User-Agent as kalshi.py). For every open paper trade of the main bot
and every filled, unsettled position of the limit-order test it records what the position could be sold for now: the
best bid for its side (YES: yes_bid; NO: 1 - yes_ask), times the contracts. A market that has already settled on Kalshi
counts at its payout. Unknown prices are left out (the dashboard then keeps that trade's last known price, or its cost).
Added 2026-10-15 at the user's request ("the graph is not in real time"): dashboard.py draws these marks on the account
chart. `run watch` runs this every 5 minutes; `run marks` runs it once and rebuilds the dashboard. Python 3.8+."""
import os, sys, json, time, sqlite3
from pathlib import Path
HERE=os.path.dirname(os.path.abspath(__file__))
try: import config as C
except Exception: C=None
DB=getattr(C,"DB","paper.db") if C else os.getenv("PAPER_DB","paper.db")
BASE=getattr(C,"KALSHI_BASE","https://api.elections.kalshi.com/trade-api/v2") if C else "https://api.elections.kalshi.com/trade-api/v2"
UA={"User-Agent":"tradebot-paper-research/1.0"}
OUT="marks.jsonl"
def _p(m,k):
    v=m.get(k+"_dollars")
    if v not in (None,""): return float(v)
    v=m.get(k); return None if v in (None,"") else float(v)/100
def positions(db=None):
    """[(key, ticker, side, n)] for open main-bot trades ('main:<id>') and filled, unsettled limit-order positions
    ('maker:<id>'), read-only."""
    c=sqlite3.connect(Path(db or DB).resolve().as_uri()+"?mode=ro",uri=True); c.row_factory=sqlite3.Row
    out=[("main:%d"%r["id"],r["ticker"],(r["side"] or "").lower(),int(r["n"] or 0)) for r in c.execute("select id,ticker,side,n from trades where status='open'")]
    try: out+=[("maker:%d"%r["id"],r["ticker"],(r["side"] or "").lower(),int(r["n"] or 0)) for r in c.execute("select id,ticker,side,n from shadow_orders where status='filled'")]
    except sqlite3.Error: pass   # no shadow tables yet
    c.close(); return [p for p in out if p[1] and p[2] in ("yes","no") and p[3]>0]
def fetch(tickers,get=None):
    """ticker -> market dict, 50 tickers per GET /markets?tickers=; any missing ticker is asked for on its own."""
    import requests
    get=get or (lambda url,params: requests.get(url,params=params,headers=UA,timeout=20))
    out={}; ts=sorted(set(tickers))
    for i in range(0,len(ts),50):
        r=get(BASE+"/markets",dict(tickers=",".join(ts[i:i+50]),limit=1000)); r.raise_for_status()
        for m in r.json().get("markets") or []: out[m.get("ticker")]=m
        time.sleep(0.1)
    for t in ts:
        if t in out: continue
        r=get(BASE+"/markets/"+t,{})
        if r.status_code==200: out[t]=(r.json() or {}).get("market") or {}
        time.sleep(0.1)
    return out
def value(m,side,n):
    """What the position could be sold for now (dollars), or None if Kalshi gives no usable price."""
    if not m: return None
    res=(m.get("result") or "").lower()
    if res in ("yes","no"): return float(n if res==side else 0)   # settled on Kalshi, not yet in paper.db
    if (m.get("status") or "active").lower() not in ("active","open"): return None   # trading over, no result yet
    bid,ask=_p(m,"yes_bid"),_p(m,"yes_ask")
    if side=="yes": b=bid if (bid is not None and bid>0) else None   # no bid at all: unknown, not worthless (thin books overnight)
    else: b=(1-ask) if (ask is not None and 0<ask<1) else None       # no YES offer means no NO bid either
    if b is None or not (0<b<=1): return None
    return round(n*b,4)
def snapshot(db=None,get=None,now=None):
    ps=positions(db); ms=fetch([p[1] for p in ps],get) if ps else {}
    marks={}
    for k,t,side,n in ps:
        try: v=value(ms.get(t),side,n)
        except (TypeError,ValueError): v=None   # one malformed price never costs the whole snapshot
        if v is not None: marks[k]=v
    return dict(ts=round(now or time.time(),1),marks=marks,open=len(ps))
def main():
    try: s=snapshot()
    except Exception as ex:   # no network, Kalshi down: the dashboard keeps the last prices and says when they are from
        print("marks: no prices this time (%s)"%str(ex)[:120]); return 0
    with open(OUT,"a",encoding="utf-8") as f: f.write(json.dumps(s,separators=(",",":"))+"\n")
    print("marks: %d of %d open positions priced"%(len(s["marks"]),s["open"])); return 0
if __name__=="__main__": sys.exit(main())
