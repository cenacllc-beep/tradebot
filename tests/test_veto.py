"""The 30-point veto and the two new rain cities (user decisions, 2026-10-28). No network.
python test_veto.py WORK OUT"""
import os, sys, io, contextlib, sqlite3, json
from datetime import datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off")
sys.path.insert(0, WORK)
import core, kalshi, strategy, weather, selector, risk, account_view, shadow, nws
strategy.STOP_DATE=strategy.date(2099,1,1)   # not a stop-date test (tests/test_gatelook.py is): its markets stay "before the stop date" after Nov 11 too

# 1. The veto is the shadow selector's frozen gap bound, applied to rain trades only
assert strategy.VETO_MAX_GAP == selector.EXPERIMENTS["accuracy_first.v1"]["max_gap"] == 0.30
now = datetime.now(timezone.utc)
D = (now + timedelta(days=1)).strftime("%y%b%d").upper()
def mk(city, bid, ask):
    return dict(ticker="KXRAIN-%s-%s" % (D, city), event_ticker="KXRAIN-%s" % D, close_time=(now + timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                yes_bid_dollars="%.2f" % bid, yes_ask_dollars="%.2f" % ask, rules_primary="")
#        city   bid   ask   forecast   gap to mid                      expected
CASES = [("AAA", 0.40, 0.42, 0.71,      0.30,                           "TRADE"),      # exactly 30 points: allowed
         ("BBB", 0.40, 0.42, 0.72,      0.31,                           "ANOMALOUS_MODEL_MARKET_GAP"),
         ("CCC", 0.88, 0.90, 0.60,      0.29,                           "TRADE"),      # forecast below the market: buys NO
         ("DDD", 0.92, 0.94, 0.55,      0.38,                           "ANOMALOUS_MODEL_MARKET_GAP"),   # like Seattle, Oct 25
         ("EEE", 0.50, 0.52, 0.55,      0.04,                           "INSUFFICIENT_EDGE")]           # small gap, no edge
M = [mk(c, b, a) for c, b, a, _, _, _ in CASES]
F = {"KXRAIN-%s-%s" % (D, c): f for c, _, _, f, _, _ in CASES}
for c, b, a, f, g, _ in CASES:
    assert abs(abs(f - (b + a) / 2) - g) < 1e-9, (c, f, b, a, g)
kalshi.markets = lambda *a, **k: M
strategy.estimate = lambda m: F[m["ticker"]]
c = core.db(); out = io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
got = {r[0].split("-")[-1]: r[1] for r in c.execute("select ticker,reason from decisions where strategy_id='forecast_alpha.rain.v3'")}
assert got == {c_: want for c_, _, _, _, _, want in CASES}, (got, out.getvalue())
traded = {r[0].split("-")[-1]: r[1] for r in c.execute("select ticker,side from trades")}
assert traded == {"AAA": "yes", "CCC": "no"}, traded
assert c.execute("select count(*) from obs").fetchone()[0] == len(CASES), "vetoed markets are still logged for the forecast test"
assert "ANOMALOUS_MODEL_MARKET_GAP 2" in out.getvalue()
c.close()
print("veto: more than 30 points apart -> no trade (both sides), 30 or less trades, markets still logged: ok")
# the boundary in floating point: 0.99 against a mid of 0.69 computes as 0.30000000000000004, which is 30 points: trades
os.environ["PAPER_DB"] = os.path.join(OUT, "paper_b.db"); core.DB = os.environ["PAPER_DB"]
M = [mk("FFF", 0.68, 0.70), mk("GGG", 0.40, 0.42)]
F = {"KXRAIN-%s-FFF" % D: 0.99, "KXRAIN-%s-GGG" % D: 0.80}
assert 0.99 - 0.69 > 0.30, "the float case this checks"
c = core.db()
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)", (0, "KXRAIN-%s-GGG" % D, "yes", 0.4, 0.5, 1, 0.4, 0.02, "v3"))
c.commit(); out = io.StringIO()
with contextlib.redirect_stdout(out): strategy.scan(c)
got = {r[0].split("-")[-1]: r[1] for r in c.execute("select ticker,reason from decisions where strategy_id='forecast_alpha.rain.v3'")}
assert got == {"FFF": "TRADE", "GGG": "ALREADY_HELD"}, (got, out.getvalue())   # a held market reports ALREADY_HELD, not the veto
cfg = json.loads(c.execute("select config from scans where kind='scan'").fetchone()[0])
assert cfg["VETO_MAX_GAP"] == 0.30, cfg
print("veto boundary: 30 points up to float rounding trades; a held market is reported as held; the scan records the bound: ok")

# 2. Detroit and West Palm Beach: in the rain table with the stations Kalshi's rules name, priced by the same v3 formula
assert weather.RAIN["DTW"][0] == "CLIDTW" and weather.RAIN["WPB"][0] == "CLIDJT"
assert len(weather.RAIN) == 35 and all(len(v) == 3 and v[0].startswith("CLI") for v in weather.RAIN.values())
d = now + timedelta(days=1); close = (now + timedelta(hours=30)).replace(minute=0, second=0, microsecond=0)
seen = []
def fake_slices(lat, lon):
    seen.append((lat, lon)); w0 = close - timedelta(hours=24)
    return [(w0 + timedelta(hours=h), w0 + timedelta(hours=h + 1), 40 if h < 12 else 20) for h in range(-2, 26)]
nws.grid_slices = fake_slices; nws.rain_raw = lambda *a: {}
for city in ("DTW", "WPB"):
    m = dict(ticker="KXRAIN-%s-%s" % (d.strftime("%y%b%d").upper(), city), close_time=close.strftime("%Y-%m-%dT%H:%M:%SZ"))
    p = weather.estimator(m)
    assert abs(p - (0.40 + 1 - 0.60 * 0.80) / 2) < 1e-9, (city, p)   # same formula: (max + union) / 2
    assert weather.RAW[m["ticker"]]["station"] == weather.RAIN[city][0]
assert seen == [weather.RAIN["DTW"][1:], weather.RAIN["WPB"][1:]], seen
# the rules watch accepts the stations Kalshi names (no RULES WARNING), and the dashboard and risk clusters know them
c = core.db(); out = io.StringIO()
mkts = [dict(ticker="KXRAIN-%s-DTW" % D, rules_primary="If the total precipitation at CLIDTW in Detroit in Oct 28, 2026 is strictly greater than 0 inches", strike_type="greater"),
        dict(ticker="KXRAIN-%s-WPB" % D, rules_primary="If the total precipitation at CLIDJT in West Palm Beach in Oct 28, 2026 is strictly greater than 0 inches", strike_type="greater")]
with contextlib.redirect_stdout(out):
    shadow.tables(c)
    shadow.rules_check(c, mkts)
assert "RULES WARNING" not in out.getvalue() and "station" not in out.getvalue(), out.getvalue()
c.close()
assert risk.cluster("KXRAIN-%s-DTW" % D).endswith(":midwest") and risk.cluster("KXRAIN-%s-WPB" % D).endswith(":southeast")
assert account_view.label("KXRAIN-26OCT28-DTW") == "Detroit rain, Oct 28" and account_view.label("KXRAIN-26OCT28-WPB") == "West Palm Beach rain, Oct 28"
print("Detroit and West Palm Beach: stations match Kalshi's rules, same v3 formula, named on the dashboard, in risk clusters: ok")
print("veto and new cities: all checks passed")
