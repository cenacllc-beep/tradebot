"""Test for the 2026-10-14 off-hours guard: markets whose Kalshi day has begun are neither logged nor traded. No network.
python test_started.py WORK OUT"""
import os, sys, io, contextlib
WORK=sys.argv[1]; OUT=sys.argv[2]
os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import core, kalshi, strategy
from datetime import datetime, timedelta, timezone
c=core.db()
now=datetime.now(timezone.utc); f=lambda h:(now+timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
mk=[{"ticker":"KXHIGHDEN-26OCT14-T48","close_time":f(15),"strike_type":"greater","yes_bid_dollars":"0.00","yes_ask_dollars":"0.01"},  # day began 9h ago
    {"ticker":"KXHIGHDEN-26OCT15-T60","close_time":f(30),"strike_type":"greater","yes_bid_dollars":"0.10","yes_ask_dollars":"0.12"},  # starts in 6h
    {"ticker":"KXHIGHMIA-26OCT15-T84","close_time":None,"strike_type":"greater","yes_bid_dollars":"0.10","yes_ask_dollars":"0.12"},  # unreadable close
    {"ticker":"KXRAIN-26OCT15-PHIL","close_time":f(24.0),"yes_bid_dollars":"0.10","yes_ask_dollars":"0.12"}]   # starts exactly now
kalshi.markets=lambda *a,**k:mk
strategy.estimate=lambda m:0.60   # big edge on every market
out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
print(out.getvalue().strip())
logged={r[0] for r in c.execute("select ticker from obs")}; traded={r[0] for r in c.execute("select ticker from trades")}
assert logged=={"KXHIGHDEN-26OCT15-T60"}, logged
assert traded==set(), traded   # temperature is logged, not traded (2026-10-14)
assert "(2 skipped: their day had already begun)" in out.getvalue() and "WARNING: 1 markets had a close time" in out.getvalue()
assert strategy.started({"close_time":f(24.01)}) is False and strategy.started({"close_time":(datetime.now(timezone.utc)+timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S.123Z")}) is False and strategy.started({"close_time":f(23.99)}) is True and strategy.started({}) is True
print("off-hours guard: started markets are not logged or traded; unreadable close time is skipped: ok")
