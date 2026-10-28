"""Two moves on 2026-10-28, no network: (1) the renamed daily-high temperature series (logged, not traded) are asked for
by their current names; (2) PLAN5 L's hourly sampling moved from the PC to GitHub Actions, and the PC's copy, marked
by research/data/lip/MOVED.txt, neither samples nor scores again. python test_moves.py WORK OUT"""
import os, sys, io, re, json, shutil, contextlib
from datetime import datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off")
sys.path.insert(0, WORK)
import core, kalshi, weather, strategy, shadow
def quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): r = fn(*a, **k)
    return r, out.getvalue()

# 1. temperature series
TS = weather.TEMP_SERIES
assert set(TS) <= set(weather.CITY) and len(set(TS.values())) == len(TS) and all(v.startswith("KXHIGH") for v in TS.values())
assert weather.SERIES_CITY == {v: k for k, v in TS.items()}
assert TS["NYC"] == "KXHIGHNY" and TS["SEA"] == "KXHIGHTSEA" and TS["HOU"] == "KXHIGHTHOU" and TS["CHI"] == "KXHIGHCHI"
assert not {"STL", "MKE", "PVD", "IND"} & set(TS), "no current daily-high series for these"
asked = []
class R:
    def raise_for_status(self): pass
    def json(self): return {"markets": [], "cursor": ""}
def fake_get(url, params=None, **k): asked.append(params["series_ticker"]); return R()
real_get = kalshi.requests.get; kalshi.requests.get = fake_get
assert kalshi.markets() == [] and asked == ["KXRAIN"] + list(TS.values()), asked
kalshi.requests.get = real_get
print("market list: KXRAIN plus the 10 current daily-high series: ok")
now = datetime.now(timezone.utc); day = (now + timedelta(days=1)).date(); tag = day.strftime("%y%b%d").upper()
cities = []
def fake_daily(city): cities.append(city); return {"time": [str(day)], "temperature_2m_max": [60.0]}
weather._daily = fake_daily
def m(series, strike, st="greater"): return dict(ticker="%s-%s-%s" % (series, tag, strike), strike_type=st, close_time=(now + timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
p = weather.estimator(m("KXHIGHTSEA", "T58"))
assert cities == ["SEA"] and abs(p - (1 - weather._cdf((58.5 - 60.0) / weather.WEATHER_SIGMA_F))) < 1e-12, (cities, p)
assert weather.RAW["KXHIGHTSEA-%s-T58" % tag]["type"] == "temp"
assert weather.estimator(m("KXHIGHCHI", "T70", "less")) is not None and cities[-1] == "CHI", "an unchanged name reads as before"
assert weather.estimator(m("KXHIGHNYC", "T70")) is not None and cities[-1] == "NYC", "the old KXHIGH+city form still maps"
assert weather.estimator(m("KXHIGHNY", "T70")) is not None and cities[-1] == "NYC"
assert weather.estimator(m("KXHIGHTATL", "T70")) is None, "a city the temperature table does not know"
assert weather.estimator(m("KXHIGHTSEA", "B57.5", "between")) is None, "range buckets are not modelled"
print("estimator: KXHIGHTSEA -> Seattle, KXHIGHNY -> New York, older names still read, unknown cities and buckets skipped: ok")
# the scan logs them as temperature and never trades them; the rules watch files them under the city
c = core.db()
mk = dict(m("KXHIGHTSEA", "T58"), event_ticker="KXHIGHTSEA-%s" % tag, yes_bid_dollars="0.10", yes_ask_dollars="0.12",
          rules_primary="If the highest temperature recorded at CLISEA in Seattle on %s is greater than 58" % day)
kalshi.markets = lambda *a, **k: [mk]
quiet(strategy.scan, c)
assert c.execute("select market_type from obs").fetchall() == [("temp",)] and c.execute("select count(*) from trades").fetchone()[0] == 0
assert c.execute("select reason from decisions").fetchall() == [("STRATEGY_DISABLED",)]
_, out = quiet(lambda: (shadow.tables(c), shadow.rules_check(c, [mk])))
assert c.execute("select value from rules_watch where series='KXHIGHTSEA' and key='station:SEA'").fetchone() == ("CLISEA",), out
assert "RULES WARNING" not in out
c.close()
print("scan: Seattle logged as temperature, not traded; the rules watch records its station under SEA: ok")
# Detroit and West Palm Beach: the NWS station coordinates (checked 2026-10-28; same NWS grid cells as before)
assert weather.RAIN["DTW"] == ("CLIDTW", 42.2314, -83.3308) and weather.RAIN["WPB"] == ("CLIDJT", 26.6851, -80.0992)
print("Detroit and West Palm Beach: NWS station coordinates: ok")

# 2. PLAN5 L moved to GitHub
sys.path.insert(0, os.path.join(WORK, "research"))
import lip as P
P.DATA = os.path.join(OUT, "lip"); P.OUT = os.path.join(OUT, "results"); os.makedirs(P.DATA); os.makedirs(P.OUT)
def boom(*a, **k): raise AssertionError("no request may be made from a moved copy")
P.http = boom
assert P.moved() is None
note = "PLAN5 L sampling moved to GitHub Actions on 2026-10-28 16:30 (repository cenacllc-beep/tradebot); this copy stops here."
open(os.path.join(P.DATA, "MOVED.txt"), "w", encoding="utf-8").write(note + "\nmore detail\n")
assert P.moved() == note
_, out = quiet(P.sample, now=datetime(2026, 10, 30, 16, tzinfo=timezone.utc).timestamp())
assert "not sampled here" in out and os.listdir(P.DATA) == ["MOVED.txt"], (out, os.listdir(P.DATA))
_, out = quiet(P.settle)
assert "not here" in out and os.listdir(P.DATA) == ["MOVED.txt"]
try: P.score(now=P.SCORE_FROM + 86400); raise AssertionError("expected an exit")
except SystemExit as ex: assert "score it where the data lives" in str(ex), ex
assert not os.listdir(P.OUT)
print("lip.py: a copy marked as moved neither samples, settles nor scores, and makes no request: ok")
# storage (logistics): the original files stay as they are, new rows go to one file per UTC day, readers take all in order
P.DATA = os.path.join(OUT, "lip2"); os.makedirs(P.DATA)
P.append(os.path.join(P.DATA, "samples.jsonl"), [dict(hour=1)])
day = lambda d: datetime(2026, 10, d, 12, tzinfo=timezone.utc).timestamp()
P.add_rows("samples", [dict(hour=3)], day(30)); P.add_rows("samples", [dict(hour=2)], day(29)); P.add_rows("fills", [dict(hour=2)], day(29))
assert [r["hour"] for r in P.rows_of("samples")] == [1, 2, 3] and [r["hour"] for r in P.rows_of("fills")] == [2]
assert sorted(os.listdir(P.DATA)) == ["fills-20261029.jsonl", "samples-20261029.jsonl", "samples-20261030.jsonl", "samples.jsonl"]
assert P.rows_of("sample_log") == [] and P.lines(os.path.join(P.DATA, "samples.jsonl")) == [dict(hour=1)], "the original file is never rewritten"
import freshness as F0
open(os.path.join(P.DATA, "samples-20261030.jsonl"), "a").write(json.dumps(dict(ts=day(30))) + "\n")
assert F0._lip_last(P.DATA) == day(30)
print("storage: new rows in daily files, read back in order with the original file; freshness sees the newest: ok")
# freshness: one information row instead of stale sampling alarms
import freshness as F
root = os.path.join(OUT, "pc"); lipdir = os.path.join(root, "research", "data", "lip"); os.makedirs(lipdir)
for d in ("backups", "logs", "offsite", os.path.join("research", "results")): os.makedirs(os.path.join(root, d), exist_ok=True)
shutil.copy(os.path.join(OUT, "lip", "MOVED.txt"), lipdir)
NOW = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc).timestamp()   # inside the sampling window
rows = {r["key"]: r for r in F.checks(root=root, db=os.path.join(root, "paper.db"), now=NOW, offsite=os.path.join(root, "offsite"))}
assert rows["lip_samples"]["status"] == "info" and note in rows["lip_samples"]["detail"] and "lip_programs" not in rows, rows.get("lip_samples")
print("freshness: the PC shows PLAN5 L as moved (information), not as stale: ok")
# dashboard and the control center's safety line
import dashboard, control_view
os.chdir(root); _, _, lip_n = dashboard.read_research(); os.chdir(OUT)
assert lip_n == note, lip_n
line = control_view.safety_line(NOW, lip_n)
assert note in line and "%d" not in line
assert "market-hours sampled so far" in control_view.safety_line(NOW, 12)
print("dashboard: the safety line says where PLAN5 L is sampled: ok")
# run.bat no longer samples; the GitHub workflow does, on its own concurrency group, and every push retries on a race
bat = open(os.path.join(WORK, "run.bat"), encoding="utf-8").read()
assert "lip.py" not in re.sub(r"(?m)^rem .*$", "", bat), "run.bat must not run research\\lip.py any more"
wf = open(os.path.join(WORK, "cloud", "workflows", "plan5-lip.yml"), encoding="utf-8").read()
assert '- cron: "20 * * * *"' in wf and "python research/lip.py sample" in wf and "python research/lip.py settle" in wf
assert "group: tradebot-lip" in wf and "main.py" not in wf and "live.py" not in wf and "MOVED.txt" in wf and "plan5_L.json" in wf
for f in ("plan5-lip.yml", "tradebot-scan.yml", "tradebot-settle.yml"):
    s = open(os.path.join(WORK, "cloud", "workflows", f), encoding="utf-8").read()
    assert "git pull --rebase origin main" in s and "git push origin HEAD:main && exit 0" in s, f
gi = open(os.path.join(WORK, "cloud", "repo.gitignore"), encoding="utf-8").read().splitlines()
assert "/research/data/*" in gi and "!/research/data/lip/" in gi and "/research/data/lip/MOVED.txt" in gi and "/paper.db" in gi and "/live.db" in gi
print("run.bat stops sampling; the hourly workflow samples, scores once from Nov 25 and retries pushes: ok")
print("temperature series and the PLAN5 L move: all checks passed")
