import requests, time
from config import *
UA={"User-Agent":"tradebot-paper-research/1.0"}   # the only User-Agent allowed (CLAUDE.md section 3); added 2026-10-14 after a code review
def _p(m,k):
    v=m.get(k+"_dollars")
    if v is not None: return float(v)
    v=m.get(k); return None if v is None else float(v)/100
def markets(limit=1000,pages=6,series=None):
    """Open markets closing within MAX_HOURS_TO_CLOSE, asked for by series: KXRAIN plus the daily-high series of the cities
    the temperature estimator knows (the same markets the estimators can price). Fixed 2026-10-14: this used to read the
    first 6,000 of ALL open markets, which are now mostly multivariate combos (40,000+), so it could return no weather
    markets at all. Fixed 2026-10-28: Kalshi renamed most daily-high series (KXHIGHNY, KXHIGHT<city>), so the names now
    come from weather.TEMP_SERIES instead of "KXHIGH"+city (temperature is logged, not traded)."""
    if series is None:
        import weather
        series=["KXRAIN"]+list(weather.TEMP_SERIES.values())
    out=[]
    for s in series:
        cur=None
        for _ in range(pages):
            r=requests.get(f"{KALSHI_BASE}/markets",params={"series_ticker":s,"status":"open","limit":limit,"cursor":cur,"max_close_ts":int(time.time()+MAX_HOURS_TO_CLOSE*3600)},headers=UA,timeout=20)
            r.raise_for_status(); j=r.json(); out+=j.get("markets",[]); cur=j.get("cursor")
            if not cur: break
        time.sleep(0.1)
    return [m for m in out if not m.get('ticker','').startswith('KXMVE')]  # drop combo markets
def quote(m): return _p(m,"yes_bid"),_p(m,"yes_ask")
def get(t): return requests.get(f"{KALSHI_BASE}/markets/{t}",headers=UA,timeout=20).json()["market"]
