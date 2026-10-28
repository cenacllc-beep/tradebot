"""Temperature markets are logged but not traded (main bot) and get no limit orders (shadow). No network. python test_rainonly.py WORK OUT"""
import os, sys, io, contextlib
WORK=sys.argv[1]; OUT=sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import core, kalshi, strategy, shadow
from datetime import datetime, timedelta, timezone
c=core.db(); f=lambda h:(datetime.now(timezone.utc)+timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
mk=[{"ticker":"KXHIGHDEN-26OCT15-T60","close_time":f(30),"strike_type":"greater","yes_bid_dollars":"0.10","yes_ask_dollars":"0.12","rules_primary":""},
    {"ticker":"KXRAIN-26OCT15-PHIL","close_time":f(30),"yes_bid_dollars":"0.35","yes_ask_dollars":"0.37","rules_primary":"at CLIPHL"}]   # 24-point gap: under the 30-point veto
kalshi.markets=lambda *a,**k:mk; strategy.estimate=lambda m:0.60
out=io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
print(out.getvalue().strip())
assert {r[0] for r in c.execute("select ticker from obs")}=={"KXHIGHDEN-26OCT15-T60","KXRAIN-26OCT15-PHIL"}, "both logged"
assert {r[0] for r in c.execute("select ticker from trades")}=={"KXRAIN-26OCT15-PHIL"}, "only rain traded"
shadow.rules_check=lambda c,m:None; shadow.v4_log=lambda c,m:None
out=io.StringIO()
with contextlib.redirect_stdout(out): shadow.scan(c)
print(out.getvalue().strip())
assert {r[0] for r in c.execute("select ticker from shadow_orders")}<={"KXRAIN-26OCT15-PHIL"}, "no temperature limit orders"
print("rain only: temperature logged but not traded, no temperature limit orders: ok")
