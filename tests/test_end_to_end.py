"""Mocked end-to-end test of the rebuilt tradebot: scan -> settle -> report -> dashboard.
No network: Kalshi, NWS and Open-Meteo are replaced with fakes. Writes only into a temp folder."""
import os, sys, json, random, sqlite3, subprocess, collections
from datetime import datetime, timedelta, timezone
WORK = sys.argv[1]; OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "offsite")
sys.path.insert(0, WORK)
import requests
calls = collections.Counter(); phase = {"now": None}
def fake_get(url, *a, **k):
    host = url.split("/")[2]; calls[(phase["now"], host)] += 1
    if "open-meteo" in host:
        today = datetime.now(timezone.utc).date()
        days = [(today + timedelta(days=i)).isoformat() for i in range(-1, 4)]
        class R:
            def json(self): return {"daily": {"time": days, "temperature_2m_max": [70.0, 66.0, 63.0, 61.0, 60.0], "precipitation_probability_max": [10, 20, 30, 40, 50]}}
        return R()
    raise AssertionError("unexpected real network call: " + url)
requests.get = fake_get
import config, core, kalshi, nws, weather, strategy
random.seed(7)
now = datetime.now(timezone.utc)
# Kalshi day for tomorrow (local standard time); Eastern/Central/Mountain/Pacific offsets
OFF = {"NYC": 5, "BOS": 5, "ATL": 5, "MIA": 5, "CHI": 6, "HOU": 6, "DAL": 6, "DEN": 7, "PHX": 7, "LAX": 8, "SEA": 8, "SFO": 8}
D = (now - timedelta(hours=5)).date() + timedelta(days=1)
def close_for(city): return datetime(D.year, D.month, D.day, tzinfo=timezone.utc) + timedelta(days=1, hours=OFF[city])
tag = D.strftime("%y%b%d").upper()
markets = []
pop_by_city = {"NYC": 70, "BOS": 55, "ATL": 10, "MIA": 40, "CHI": 85, "HOU": 5, "DAL": 15, "DEN": 3, "PHX": 1, "LAX": 2, "SEA": 90, "SFO": 30}
mid_by_city = {"NYC": .52, "BOS": .60, "ATL": .30, "MIA": .45, "CHI": .70, "HOU": .08, "DAL": .12, "DEN": .05, "PHX": .03, "LAX": .03, "SEA": .66, "SFO": .20}
for city in pop_by_city:
    m = mid_by_city[city]
    markets.append({"ticker": "KXRAIN-%s-%s" % (tag, city), "close_time": close_for(city).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "yes_bid_dollars": round(m - .02, 2), "yes_ask_dollars": round(m + .02, 2)})
for city, thr, st, b, a in (("CHI", 65, "greater", .30, .34), ("DEN", 60, "less", .40, .44), ("LAX", 75, "greater", .20, .24), ("MIA", 88, "less", .50, .53)):
    markets.append({"ticker": "KXHIGH%s-%s-T%d" % (city, tag, thr), "close_time": close_for(city if city in OFF else "NYC").strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "strike_type": st, "yes_bid_dollars": b, "yes_ask_dollars": a})
markets.append({"ticker": "KXRAIN-%s-ZZZ" % tag, "close_time": close_for("NYC").strftime("%Y-%m-%dT%H:%M:%SZ"), "yes_bid_dollars": .4, "yes_ask_dollars": .44})  # unknown city -> skipped
markets.append({"ticker": "KXRAIN-%s-BOS" % (now - timedelta(days=1)).strftime("%y%b%d").upper(), "close_time": (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), "yes_bid_dollars": .4, "yes_ask_dollars": .44})  # window already started -> skipped
kalshi.markets = lambda *a, **k: markets
def fake_slices(lat, lon):
    city = [c for c, v in weather.RAIN.items() if (v[1], v[2]) == (lat, lon)][0]; p = pop_by_city[city]
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=3); out = []
    for h in range(72):
        s = start + timedelta(hours=h); out.append((s, s + timedelta(hours=1), max(0, min(100, p + random.choice((-10, -5, 0, 5))))))
    return out
nws.grid_slices = fake_slices
def fake_periods(lat, lon):
    out = []; base = (now - timedelta(hours=5)).date()
    for i in range(6):
        d = base + timedelta(days=i // 2)
        out.append({"startTime": d.isoformat() + ("T06:00:00-05:00" if i % 2 == 0 else "T18:00:00-05:00"), "isDaytime": i % 2 == 0, "probabilityOfPrecipitation": {"value": 40 if i % 3 else None}})
    return out
nws.periods = fake_periods
# rain estimates must not touch Open-Meteo
phase["now"] = "rain-estimate"
for m in markets:
    if m["ticker"].startswith("KXRAIN"): weather.estimator(m)
assert not any(h for (p, h) in calls if p == "rain-estimate" and "open-meteo" in h), "rain estimator called Open-Meteo!"
print("rain path Open-Meteo calls: 0 (ok)")
phase["now"] = "scan"
c = core.db(); strategy.scan(c)
obs = c.execute("select ticker,market_type,fc,mid,p_a,p_b,station,slices is not null from obs").fetchall()
tr = c.execute("select ticker,side,price,fair,n,cost,fee,status,version from trades").fetchall()
print("obs rows:", len(obs), "| rain:", sum(r[1] == "rain" for r in obs), "| temp:", sum(r[1] == "temp" for r in obs))
for r in tr: print("  trade", r)
opn = sum(r[5] + r[6] for r in tr); print("open cost+fee = %.2f (cap %.2f)" % (opn, config.BANKROLL * config.MAX_OPEN_PCT))
assert opn <= config.BANKROLL * config.MAX_OPEN_PCT + 1e-9
assert all(r[8] == "v3" for r in tr)
# settle: everything resolves
res = {}
for t, mt, fc, *_ in obs: res[t] = "yes" if random.random() < fc else "no"
kalshi.get = lambda t: {"result": res.get(t)}
strategy.settle(c)
print("settled trades:", c.execute("select count(*), round(sum(pnl),2) from trades where status='settled'").fetchone())
strategy.report(c); c.close()
r = subprocess.run([sys.executable, os.path.join(WORK, "dashboard.py"), "--no-open"], capture_output=True, text=True, cwd=OUT, env=dict(os.environ, PYTHONPATH=WORK))
print("dashboard.py exit", r.returncode, r.stdout.strip(), r.stderr.strip()[-600:])
