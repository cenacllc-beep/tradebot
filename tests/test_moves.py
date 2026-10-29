"""Moves of 2026-10-28 and 29, no network: (1) the renamed daily-high temperature series (logged, not traded) are asked for
by their current names; (2) PLAN5 L is sampled on GitHub Actions and, since Oct 29, on the PC too: the PC's copy
(SECONDARY.txt) is merged into the repository's (PRIMARY.txt) before the single score; (3) the GitHub trial scan starts
several times and scans once an evening. python test_moves.py WORK OUT"""
import os, sys, io, re, json, shutil, contextlib, sqlite3
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
root2 = os.path.join(OUT, "pc2"); os.makedirs(os.path.join(root2, "research", "data", "lip"))
for d in ("backups", "logs", "offsite", os.path.join("research", "results")): os.makedirs(os.path.join(root2, d), exist_ok=True)
open(os.path.join(root2, "research", "data", "lip", "SECONDARY.txt"), "w").write("merged into the repository's copy\n")
rows2 = {r["key"]: r for r in F.checks(root=root2, db=os.path.join(root2, "paper.db"), now=NOW, offsite=os.path.join(root2, "offsite"))}
assert rows2["lip_samples"]["status"] == "stale" and "alongside GitHub" in rows2["lip_samples"]["detail"], rows2["lip_samples"]   # nothing sampled there at all
P.append(os.path.join(root2, "research", "data", "lip", "samples-20261030.jsonl"), [dict(ts=NOW - 20 * 3600, hour=int((NOW - 20 * 3600) // 3600), ticker="X")])
rows2 = {r["key"]: r for r in F.checks(root=root2, db=os.path.join(root2, "paper.db"), now=NOW, offsite=os.path.join(root2, "offsite"))}
assert rows2["lip_samples"]["status"] == "ok", rows2["lip_samples"]   # 20 hours without a sample here is fine: GitHub samples too
print("freshness: the PC shows PLAN5 L as moved (information), not as stale; as the second sampler, flagged only after a day without a sample: ok")
# dashboard and the control center's safety line
import dashboard, control_view
os.chdir(root); _, _, lip_n = dashboard.read_research(); os.chdir(OUT)
assert lip_n == note, lip_n
line = control_view.safety_line(NOW, lip_n)
assert note in line and "%d" not in line
assert "market-hours sampled so far" in control_view.safety_line(NOW, 12)
print("dashboard: the safety line says where PLAN5 L is sampled: ok")
# since 2026-10-29 both sample: run.bat runs lip.py again; the GitHub workflow samples on its own concurrency group, never
# scores (the score runs once, by hand, after the PC's hours are merged), and every push retries on a race
bat = open(os.path.join(WORK, "run.bat"), encoding="utf-8").read()
code = re.sub(r"(?m)^rem .*$", "", bat)
hourly = code[code.index(":hourly"):code.index("exit /b 0", code.index(":hourly"))]
assert 'research\\lip.py sample' in hourly and 'research\\lip.py settle' in hourly and "score" not in hourly, hourly
wf = open(os.path.join(WORK, "cloud", "workflows", "plan5-lip.yml"), encoding="utf-8").read()
assert '- cron: "5,20,35,50 * * * *"' in wf and "python research/lip.py sample" in wf and "python research/lip.py settle" in wf
assert "group: tradebot-lip" in wf and "main.py" not in wf and "live.py" not in wf and "MOVED.txt" in wf and "plan5_L.json" in wf
assert "lip.py score" not in re.sub(r"(?m)^\s*#.*$", "", wf), "the workflow never scores"
for f in ("plan5-lip.yml", "tradebot-scan.yml", "tradebot-settle.yml"):
    s_ = open(os.path.join(WORK, "cloud", "workflows", f), encoding="utf-8").read()
    assert "git pull --rebase origin main" in s_ and "git push origin HEAD:main && exit 0" in s_, f
sc = open(os.path.join(WORK, "cloud", "workflows", "tradebot-scan.yml"), encoding="utf-8").read()
assert '- cron: "55 0 * * *"' in sc and '- cron: "25,55 1-3 * * *"' in sc and '- cron: "25 4 * * *"' in sc
assert sc.index("scan_window.py") < sc.index("python ../check.py") < sc.index("python ../main.py scan"), "one scan an evening: the check comes first"
st = open(os.path.join(WORK, "cloud", "workflows", "tradebot-settle.yml"), encoding="utf-8").read()
assert '- cron: "40 18-22 * * *"' in st
gi = open(os.path.join(WORK, "cloud", "repo.gitignore"), encoding="utf-8").read().splitlines()
assert "/research/data/*" in gi and "!/research/data/lip/" in gi and "/research/data/lip/MOVED.txt*" in gi and "/paper.db" in gi and "/live.db" in gi
assert "/research/data/lip/SECONDARY.txt" in gi and not any("PRIMARY" in x or "merged" in x for x in gi if not x.startswith("#"))
for f in ("plan5-lip.yml", "tradebot-scan.yml", "tradebot-settle.yml"):   # a run that waited its turn checks out the newest main
    s_ = open(os.path.join(WORK, "cloud", "workflows", f), encoding="utf-8").read()
    assert re.search(r"uses: actions/checkout@v5\n\s+with:\n\s+ref: main", s_), f
print("both copies sample; the workflow never scores; several start times with one scan an evening; pushes retry: ok")
# merge: the hours only the other copy took come over (samples, fills, log, hours.json), the target keeps any hour it has
# rows for, results are united, a second merge changes nothing, and wrong folders or directions are refused
A = os.path.join(OUT, "repo_lip"); B = os.path.join(OUT, "pc_lip"); os.makedirs(A); os.makedirs(B)
H = lambda h, n=1: dict(ts=h * 3600 + 300, universe=3, sampled=n, skipped={})
P.DATA = A
P.save(os.path.join(A, "hours.json"), {"100": H(100), "101": H(101), "104": H(104, 0)})
P.append(os.path.join(A, "samples.jsonl"), [dict(hour=100, ts=360300, ticker="A1"), dict(hour=101, ts=363900, ticker="A2")])
P.save(os.path.join(A, "results.json"), {"A1": "yes", "B2": "yes"})
open(os.path.join(A, "PRIMARY.txt"), "w").write("the scored copy\n")
P.save(os.path.join(B, "hours.json"), {"100": H(100), "102": H(102), "103": H(103), "104": H(104), "105": H(105, 0)})
P.append(os.path.join(B, "samples.jsonl"), [dict(hour=100, ts=360000, ticker="B0"), dict(hour=102, ts=367500, ticker="B2")])
P.append(os.path.join(B, "samples-19700105.jsonl"), [dict(hour=103, ts=371100, ticker="B3"), dict(hour=104, ts=374700, ticker="B4")])
P.append(os.path.join(B, "fills-19700105.jsonl"), [dict(hour=102, ticker="B2", trades=1), dict(hour=100, ticker="B0", trades=9)])
P.append(os.path.join(B, "sample_log.jsonl"), [dict(ts=367500, universe=3, sampled=1, skipped={}), dict(ts=360000, universe=3, sampled=1, skipped={})])
P.save(os.path.join(B, "results.json"), {"A1": "no", "B2": "yes", "B3": "no"})
def refused(*a, **k):
    try: quiet(P.merge, *a, **k)
    except SystemExit as ex: return str(ex)
    raise AssertionError("expected a refusal")
def snapshot(skip=()): return {f: open(os.path.join(A, f), "rb").read() for f in os.listdir(A) if f not in skip}
before = snapshot()
assert "no SECONDARY.txt" in refused(B), "the second copy must be marked"
assert "not a PLAN5 L data folder" in refused(os.path.join(OUT, "nowhere")) and "not a PLAN5 L data folder" in refused(OUT)
open(os.path.join(B, "SECONDARY.txt"), "w").write("merged into the repository's copy\n")
E = os.path.join(OUT, "empty_lip"); os.makedirs(E); P.save(os.path.join(E, "hours.json"), {}); open(os.path.join(E, "SECONDARY.txt"), "w").write("x\n")
assert "no sampled hours" in refused(E)
bad = os.path.join(OUT, "dup_lip"); shutil.copytree(B, bad); P.append(os.path.join(bad, "samples.jsonl"), [dict(hour=102, ts=367600, ticker="B2")])
assert "same market-hour twice" in refused(bad)
assert before == snapshot(), "a refused merge changes nothing"
P.DATA = B; assert "secondary one" in refused(A), "never merge into the secondary copy"; P.DATA = A
_, out = quiet(P.merge, B)
assert sorted(P.load(os.path.join(A, "hours.json")), key=int) == ["100", "101", "102", "103", "104", "105"] and "4 hours added" in out, out
assert [(r["hour"], r["ticker"]) for r in P.rows_of("samples")] == [(100, "A1"), (101, "A2"), (102, "B2"), (103, "B3"), (104, "B4")], \
    "hour 100 stays the target's; hour 104 (taken here with no rows) gives way to the PC's rows"
assert [(r["hour"], r["ticker"]) for r in P.rows_of("fills")] == [(102, "B2")] and [r["ts"] for r in P.rows_of("sample_log")] == [367500]
assert P.load(os.path.join(A, "results.json")) == {"A1": "yes", "B2": "yes", "B3": "no"} and "WARNING 1 markets have different results" in out
m = P.load(os.path.join(A, "merged.json")); assert m["hours_added"] == ["102", "103", "104", "105"] and m["results_differ"] == ["A1"], m
before = snapshot(skip=("merged.json",))
_, out = quiet(P.merge, B)
assert "0 hours added" in out and before == snapshot(skip=("merged.json",)), "a second merge changes nothing"
# a merge interrupted after the rows were written (hours.json not saved): a re-run never adds those rows twice
P.save(os.path.join(A, "hours.json"), {k: v for k, v in P.load(os.path.join(A, "hours.json")).items() if k not in ("102", "103")})
quiet(P.merge, B)
assert [(r["hour"], r["ticker"]) for r in P.rows_of("samples")].count((102, "B2")) == 1
assert [(r["hour"], r["ticker"]) for r in P.rows_of("fills")].count((102, "B2")) == 1
# the score: never in the secondary copy; in the primary copy only after a merge taken once the window has ended
P.DATA = B
try: P.score(now=P.SCORE_FROM + 86400); raise AssertionError("expected an exit")
except SystemExit as ex: assert "after lip.py merge" in str(ex), ex
P.DATA = A
assert P.primary() and not P.secondary()
try: P.score(now=P.SCORE_FROM + 86400); raise AssertionError("expected an exit")
except SystemExit as ex: assert "Merge the PC's copy first" in str(ex), ex   # merged.json is from before END
quiet(P.merge, None, none_reason="test: the PC copy was lost")
assert P.load(os.path.join(A, "merged.json"))["src"] is None
P.save(os.path.join(A, "merged.json"), dict(P.load(os.path.join(A, "merged.json")), ts=P.END + 60))
try: quiet(P.score, now=P.SCORE_FROM + 86400)
except SystemExit as ex: assert "Merge the PC's copy first" not in str(ex), ex
except Exception: pass   # past the merge check: the scorer itself then runs on this tiny fake data
print("merge: checked before writing, only the other copy's own hours, never twice, wrong folders and directions refused;"
      " the primary copy scores only after a merge taken once the window ended: ok")
# check.py, run from a trial/ folder as the workflow does: NOT SCANNED (3) before tonight's markets are logged, SCANNED (0) after
import subprocess
T = os.path.join(OUT, "trial"); os.makedirs(T)
env = dict(os.environ); env.pop("PAPER_DB", None)
def check(): return subprocess.run([sys.executable, os.path.join(WORK, "check.py")], cwd=T, env=env, capture_output=True, text=True)
r = check(); assert r.returncode == 3 and "NOT SCANNED" in r.stdout, (r.returncode, r.stdout, r.stderr)
now_utc = datetime.now(timezone.utc); dday = now_utc.date() if now_utc.hour < 5 else now_utc.date() + timedelta(days=1)
c = sqlite3.connect(os.path.join(T, "paper.db")); c.execute("create table obs(ticker,version,ts,fc,mid,market_type,result)"); c.commit()
r = check(); assert r.returncode == 3, r.stdout
c.execute("insert into obs values(?,?,?,?,?,?,?)", ("KXRAIN-%s-NYC" % dday.strftime("%y%b%d").upper(), "v3", 0, 0.5, 0.5, "rain", None)); c.commit(); c.close()
r = check(); assert r.returncode == 0 and r.stdout.startswith("SCANNED"), (r.returncode, r.stdout, r.stderr)
print("check.py from a trial folder: NOT SCANNED before tonight's markets are logged, SCANNED after: ok")
print("temperature series and the PLAN5 L move: all checks passed")
