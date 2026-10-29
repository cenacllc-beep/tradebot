"""research/nov11.py (PLAN6): the Nov 11 report next to the gate. Fake databases with the real schema (core.db, the audit
tables), and the look stored by the real strategy.gate_look. No network: sockets are blocked while the report runs.
Checks:
- read-only: neither database changes;
- nothing is shown before the look is stored, and a finished report is never replaced;
- the stored look is quoted, passed or failed;
- A is the gate's own statistic and matches the stored margin;
- B takes a missed day wholly from the cloud copy, only with a model the PC ran and inside the scan window;
- a bad trial copy loses only B;
- the fixed readings and the interval in plain words;
- the trades split at the first veto scan, with total net per contract.
python test_nov11.py WORK OUT"""
import os, sys, shutil, sqlite3, json, hashlib, random, io, contextlib, socket
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "unused.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off")
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))
import core, audit, strategy, gate, nov11 as N
strategy._backup_first = lambda: True   # the look's backup is tested in test_gatelook.py; here only what nov11 reads matters
STOP = gate.STOP_DATE
src = open(os.path.join(WORK, "research", "nov11.py"), encoding="utf-8").read()
for bad in ("import strategy", "gate_look(", "urlopen", "import requests", "import socket", "http.client", "httpclient", "subprocess"):
    assert bad not in src, "nov11.py must not compute a look or reach the network: %s" % bad

def tk(d, city, kind="KXRAIN"): return "%s-%s-%s" % (kind, d.strftime("%y%b%d").upper(), city)
def ts_in_window(d, minutes=10): return datetime(d.year, d.month, d.day, 0, 55, tzinfo=timezone.utc).timestamp() + 60 * minutes
def fresh(name):
    p = os.path.join(OUT, name); core.DB = p; c = core.db()
    for t in ("scans", "decisions"): c.execute(audit.TABLES[t])
    c.commit(); return p, c
def decide(c, ticker, mv, ts, reason="INSUFFICIENT_EDGE"):
    c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,model_version,mode,ticker,action,reason) values(?,?,?,?,?,?,?,?,?)",
              (os.urandom(8).hex(), "s", ts, N.RAIN_STRATEGY, mv, "paper", ticker, "abstain", reason))
def h(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def run(*args):
    real = socket.socket
    def blocked(*a, **k): raise AssertionError("nov11.py tried to open a network connection")
    socket.socket = blocked; buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): rc = N.main(list(args))
    finally: socket.socket = real
    return rc, buf.getvalue()
def store_look(c):
    lk = strategy.gate_look(c, today=STOP); assert lk.get("recorded") and lk["passed"] in (True, False), lk; return lk

rng = random.Random(7)
CITIES = ["NYC", "CHI", "SEA", "MIA", "DEN", "BOS"]
DAYS = [date(2026, 10, 14) + timedelta(days=i) for i in range(28)]   # the test's own days, Oct 14 .. Nov 10
assert DAYS[-1] == date(2026, 11, 10) and DAYS[-1] + timedelta(days=1) == STOP
PC_DAYS = [d for i, d in enumerate(DAYS) if i % 3 != 1]   # the PC misses every third night (Oct 15, ..., Oct 30, Nov 2, 5, 8)
MISSED = [d for d in DAYS if d not in PC_DAYS and d >= date(2026, 10, 29)]
assert MISSED == [date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 8)]
MV, OTHER = "v3@aaaaaaaaaaaa", "v3@bbbbbbbbbbbb"

# 1. before the look is stored: exit 2, only that is said, nothing written to the database
P0, c = fresh("empty.db"); c.close(); before = h(P0)
rc, out = run("--db", P0, "--out", os.path.join(OUT, "r0"))
assert rc == 2 and "not stored yet" in out and not os.path.exists(os.path.join(OUT, "r0", "nov11.json")) and h(P0) == before
try: N.ro(os.path.join(OUT, "missing.db")); raise AssertionError("a missing database must be refused")
except SystemExit as ex: assert "not found" in str(ex)
print("before the look: nothing shown, nothing written: ok")

# 2. the PC's data (a forecast clearly better than the market), rows that must never count, trades on both sides of the veto
P, c = fresh("paper.db")
pc_rows = []
for d in PC_DAYS:
    for city in CITIES:
        y = rng.random() < 0.3; m = min(0.95, max(0.05, (0.7 if y else 0.2) + rng.uniform(-0.15, 0.15)))
        f = min(0.99, max(0.01, (0.85 if y else 0.08) + rng.uniform(-0.05, 0.05)))
        pc_rows.append((tk(d, city), "v3", ts_in_window(d), f, m, "yes" if y else "no", "rain")); decide(c, tk(d, city), MV, ts_in_window(d))
noise = [(tk(DAYS[3], "LAX", "KXHIGHLAX"), "v3", 0, 0.9, 0.1, "no", "temp"),          # temperature never counts
         (tk(DAYS[3], "SEA"), "v2", 0, 0.9, 0.1, "no", "rain"),                       # v2 never counts
         (tk(STOP, "NYC"), "v3", 0, 0.99, 0.01, "no", "rain"),                        # after the test's days
         ("KXRAIN-BADDAY-NYC", "v3", 0, 0.99, 0.01, "no", "rain")]                     # unreadable day: never a test day
c.executemany("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)", pc_rows + noise)
VETO = ts_in_window(date(2026, 10, 29), 0)
c.execute("insert into scans(scan_id,started_ts,kind,code_hash,config,host) values('a',?, 'scan','x','{\"VERSION\":\"v3\"}','nt')", (VETO - 86400,))
c.execute("insert into scans(scan_id,started_ts,kind,code_hash,config,host) values('b',?, 'scan','x','{\"VETO_MAX_GAP\":0.3}','nt')", (VETO,))
c.execute("insert into scans(scan_id,started_ts,kind,code_hash,config,host) values('c',?, 'shadow_maker','x','{\"VETO_MAX_GAP\":0.3}','nt')", (VETO - 999999,))
tr = [  # (ticker, opened, side, n, cost, fee, status, result, pnl, version)
    (tk(date(2026, 10, 16), "NYC"), VETO - 9e5, "yes", 10, 4.0, 0.17, "settled", "yes", 10 - 4.0 - 0.17, "v3"),
    (tk(date(2026, 10, 16), "CHI"), VETO - 9e5, "no", 4, 2.0, 0.07, "settled", "yes", -2.07, "v3"),
    (tk(date(2026, 10, 29), "SEA"), VETO - 60, "yes", 5, 1.0, 0.06, "settled", "no", -1.06, "v3"),      # an Oct 29 market opened before the veto scan
    (tk(date(2026, 11, 2), "MIA"), VETO + 7 * 86400, "no", 3, 1.8, 0.06, "settled", "no", 3 - 1.8 - 0.06, "v3"),
    (tk(date(2026, 10, 25), "SEA"), VETO - 3e5, "yes", 2, 0.6, 0.03, "settled", "yes", 1.37, "v2"),    # v2: not counted
    (tk(date(2026, 11, 2), "LAX", "KXHIGHLAX"), VETO, "yes", 2, 0.6, 0.03, "settled", "yes", 1.37, "v3"),  # temperature
    (tk(STOP, "NYC"), VETO + 13 * 86400, "yes", 2, 0.6, 0.03, "settled", "yes", 1.37, "v3")]  # after the test
c.executemany("insert into trades(ticker,ts,side,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?)", tr)
c.commit()
lk = store_look(c); c.close()
assert lk["passed"] is False and lk["trades"] == 4
o_test = [(r[0], r[3], r[4], r[5]) for r in pc_rows]; mg = gate.margin(o_test)

# the cloud copy: a model the PC ran on Oct 30 and Nov 2 (badly wrong forecasts, visible if used), another model on Nov 5,
# a scan outside the window on Nov 8, plus rows for days the PC logged (ignored), an unresolved row on a used day
T, t = fresh("trial.db")
def cloud_day(d, mv, when, wrong=True, extra=(), step=0):
    for i, city in enumerate(CITIES + list(extra)):
        y = rng.random() < 0.3; res = None if city == "XXX" else ("yes" if y else "no")
        t.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",
                  (tk(d, city), "v3", when + i * step, (0.01 if y else 0.99) if wrong else 0.5, 0.5, res, "rain"))
        decide(t, tk(d, city), mv, when + i * step)
        decide(t, tk(d, city), OTHER, when + 86400, "MARKET_STARTED")   # the next evening's scan: a later model, not checked
cloud_day(date(2026, 10, 30), MV, ts_in_window(date(2026, 10, 30)), extra=("XXX",))
cloud_day(date(2026, 11, 2), MV, ts_in_window(date(2026, 11, 2), 240), step=120)   # began 04:55 UTC, last rows after 05:00: counted
cloud_day(date(2026, 11, 5), OTHER, ts_in_window(date(2026, 11, 5)))
cloud_day(date(2026, 11, 8), MV, ts_in_window(date(2026, 11, 8), 5 * 60))   # began 05:55 UTC: after the window
cloud_day(date(2026, 11, 9), MV, ts_in_window(date(2026, 11, 9)))            # the PC logged Nov 9: ignored
t.commit(); t.close()
hp, ht = h(P), h(T)
R1 = os.path.join(OUT, "r1"); rc, out = run("--db", P, "--trial", T, "--trial-commit", "abc1234", "--out", R1)
assert rc == 0 and h(P) == hp and h(T) == ht, "read-only: neither database changes"
R = json.load(open(os.path.join(R1, "nov11.json"), encoding="utf-8")); md = open(os.path.join(R1, "nov11.md"), encoding="utf-8").read()
assert not [f for f in os.listdir(OUT) if f.endswith(("-journal", "-wal", "-shm"))], "no journal files from a read-only run"

# A: the gate's own statistic on the test's resolved v3 rain rows, and it matches the stored look
A = R["A"]; assert A["markets"] == len(o_test) and A["days"] == len(PC_DAYS) and R["mismatch"] is None
assert abs(A["mean"] - mg[0]) < 1e-12 and abs(A["se"] - mg[1]) < 1e-12 and A["tcrit"] == gate.tcrit(mg[2])
assert abs(A["mean"] - lk["margin"][0]) < 1e-12 and A["markets"] == lk["markets"]
assert A["reading"] == "the forecast was clearly more accurate than Kalshi's prices"
assert "26OCT17: PC, 6 resolved, 0 unresolved, first logged Oct 17 01:05 UTC" in md
assert "Its error, measured by the Brier score, was plausibly between" in md and "lower than Kalshi's prices" in md
assert "a more accurate forecast is not the same as a profitable one" in md and "The gate was not passed, so the rules say no real money" in md
print("A: the gate's own statistic on the test's days, matching the stored look; the limits of 'clearly more accurate' stated: ok")

# B: a missed day is the cloud copy's alone, only with a model the PC ran and only inside the scan window
B = R["B"]; L = B["listing"]
assert L["26OCT30"]["source"] == "cloud" and L["26OCT30"]["unresolved"] == 1 and L["26NOV02"]["source"] == "cloud"
assert L["26NOV05"]["source"].startswith("cloud, not used (model v3@bbbbbbbbbbbb not run by the PC")
assert L["26NOV08"]["source"] == "cloud, not used (its scan began outside the evening scan window; not counted)" and L["26NOV09"]["source"] == "PC"
assert L["26NOV02"]["first_log"] == ts_in_window(date(2026, 11, 2), 240) and not N.in_window(date(2026, 11, 2), ts_in_window(date(2026, 11, 2), 250))
assert B["days"] == len(PC_DAYS) + 2 and B["markets"] == len(o_test) + 2 * len(CITIES)
assert B["trial_sha256"] == ht and "commit abc1234" in md and "does not change the gate" in md and "skips the eastern markets" in md
assert B["reading"] != A["reading"] and "A and B disagree" in md and "Secondary (PC days plus cloud days the PC missed; does not change the gate)" in md
print("B: missed days from the cloud copy only, same model, inside the window; the rest listed as not used; disagreement reported: ok")

# C: settled v3 rain trades of the test's days, split by open time at the first scan that recorded the veto
C = R["C"]; assert C["veto_scan"] == VETO
assert C["before_veto"]["trades"] == 3 and C["after_veto"]["trades"] == 1 and C["total"]["trades"] == 4
net = 10 - 4.0 - 0.17 - 2.07 - 1.06 + 3 - 1.8 - 0.06
assert abs(C["total"]["net"] - net) < 1e-9 and C["total"]["contracts"] == 22 and abs(C["total"]["per_contract"] - net / 22) < 1e-12
assert "se" not in C["total"] and "optimistic fills; not a test" in md
print("C: settled v3 rain trades only, split by open time at the veto scan, total net per contract, no SE: ok")

# the summary: the stored verdict first, its unmet checks, the real-money rule as it is
assert "1. **Gate (the single look, stored" in md and "): not passed.** Checks not met: at least 50 settled trades (4); net P&L" not in md
assert "Checks not met: at least 50 settled trades (4)." in md and "at least 100 resolved markets" not in md
assert "The rules (CLAUDE.md section 11) say no real money after a failed look" in md and "Real money stays locked" not in md
assert "live.py's unlock still leaves the decision to you: it says plainly that the gate did not pass, and asks for the typed phrase" in md
assert "too few to conclude anything" in md
for bad in ("re-run", "rerun", "guarantee"): assert bad not in md.lower(), bad
print("summary: the stored verdict and its unmet checks, the real-money rule as it is: ok")

# again: identical numbers; a bad or missing trial copy loses only B; a later pending run never replaces the report
rc, _ = run("--db", P, "--trial", T, "--trial-commit", "abc1234", "--out", os.path.join(OUT, "r2"))
R2 = json.load(open(os.path.join(OUT, "r2", "nov11.json"), encoding="utf-8"))
assert {k: v for k, v in R2.items() if k != "made"} == {k: v for k, v in R.items() if k != "made"}
bad = os.path.join(OUT, "pointer.db"); open(bad, "w").write("version https://git-lfs.github.com/spec/v1\n")
T2 = os.path.join(OUT, "trial_nulls.db"); shutil.copy(T, T2); t = sqlite3.connect(T2)
t.execute("update obs set fc=null where ticker=?", (tk(date(2026, 10, 30), "NYC"),)); t.commit(); t.close()
T3 = os.path.join(OUT, "trial_nullmodel.db"); shutil.copy(T, T3); t = sqlite3.connect(T3)
t.execute("update decisions set model_version=null where ticker=? and reason!='MARKET_STARTED'", (tk(date(2026, 10, 30), "NYC"),)); t.commit(); t.close()
for tri in (bad, os.path.join(OUT, "nope.db"), T2):   # a git-LFS pointer, a missing file, a NULL forecast: only B is lost
    rc, out = run("--db", P, "--trial", tri, "--out", os.path.join(OUT, "r4")); Rb = json.load(open(os.path.join(OUT, "r4", "nov11.json"), encoding="utf-8"))
    assert rc == 0 and Rb["B"]["reading"].startswith("not available (the trial copy could not be read") and Rb["A"] == R["A"], (tri, Rb["B"]["reading"])
rc, out = run("--db", P, "--trial", T3, "--out", os.path.join(OUT, "r4")); Rb = json.load(open(os.path.join(OUT, "r4", "nov11.json"), encoding="utf-8"))
assert Rb["B"]["listing"]["26OCT30"]["source"] == "cloud, not used (model None not run by the PC; not counted)", Rb["B"]["listing"]["26OCT30"]
rc, out = run("--db", P, "--trial", P0, "--out", os.path.join(OUT, "r4")); Rb = json.load(open(os.path.join(OUT, "r4", "nov11.json"), encoding="utf-8"))
assert Rb["B"]["reading"] == R["A"]["reading"] and set(Rb["B"]["listing"]) == set(R["A"]["listing"]), "an empty trial copy adds no day"
rows, lst = N.with_cloud([], [(tk(date(2026, 11, 5), "NYC"), 0.5, 0.5, "no", ts_in_window(date(2026, 11, 5)))], {"x": {MV}}, {})
assert rows == [] and lst["26NOV05"]["source"] == "cloud, not used (no rain decisions to check its model; not counted)"
d0 = date(2026, 10, 30); w0 = datetime(2026, 10, 30, 0, 50, tzinfo=timezone.utc).timestamp()
assert N.in_window(d0, w0) and N.in_window(d0, w0 + 4 * 3600 + 599) and not N.in_window(d0, w0 + 4 * 3600 + 600) and not N.in_window(d0, w0 - 1)
rc, out = run("--db", P0, "--out", R1); assert rc == 3 and "it was kept" in out and json.load(open(os.path.join(R1, "nov11.json"), encoding="utf-8"))["A"] == R["A"]
assert open(os.path.join(R1, "nov11.md"), encoding="utf-8").read() == md.replace(md.split("\n")[2], md.split("\n")[2]), "the finished report stays"
# no scans table (no veto scan recorded): every trade counts as before the veto
P4, c = fresh("noscans.db"); c.execute("drop table scans")
c.executemany("insert into trades(ticker,ts,side,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?)", [x for x in tr if x[9] == "v3"])
c.commit(); C4 = N.trades(c); c.close()
assert C4["veto_scan"] is None and C4["before_veto"]["trades"] == 4 and C4["after_veto"]["trades"] == 0
print("again: identical numbers; a bad trial copy loses only B; a pending run never replaces a finished report: ok")

# a passed look: paper only, real money still needs the user's typed unlock
P3, c = fresh("passed.db"); rows = []
for d in DAYS[:20]:
    for city in CITIES:
        y = rng.random() < 0.3
        rows.append((tk(d, city), "v3", ts_in_window(d), 0.9 if y else 0.05, 0.5, "yes" if y else "no", "rain"))
c.executemany("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)", rows)
c.executemany("insert into trades(ticker,ts,side,n,cost,fee,status,result,pnl,version) values(?,?,?,?,?,?,?,?,?,?)",
              [(tk(DAYS[i % 20], "NYC"), 0, "yes", 1, 0.5, 0.02, "settled", "yes", 0.48, "v3") for i in range(55)])
c.commit(); lk3 = store_look(c); c.close(); assert lk3["passed"] is True
rc, out = run("--db", P3, "--out", os.path.join(OUT, "r5")); md5 = open(os.path.join(OUT, "r5", "nov11.md"), encoding="utf-8").read()
assert rc == 0 and "): passed (paper only).**" in md5 and "Checks not met" not in md5 and "The gate passed on paper only" in md5
assert "typed unlock" in md5 and "capped at $25" in md5 and "The gate was not passed" not in md5
print("a passed look: paper only; real money still needs the typed unlock, tiny, $25 cap: ok")

# the fixed readings and the interval in plain words (PLAN6 section 2)
def rows_(delta, sd, days=12):
    r, out = random.Random(3), []
    for i in range(days):
        for city in CITIES:   # forecast minus market Brier per market = delta + noise
            e = delta + r.gauss(0, sd); f = max(0.0, (0.25 + e)) ** 0.5
            out.append((tk(DAYS[i], city), f, 0.5, "no", 0))
    return out
s = N.summary(rows_(-0.05, 0.01)); g = N.plain_interval(s)
assert s["reading"] == "the forecast was clearly more accurate than Kalshi's prices" and g.startswith("Its error, measured by the Brier score, was plausibly between") and "lower than" in g and "higher" not in g, g
s = N.summary(rows_(+0.05, 0.01)); g = N.plain_interval(s)
assert s["reading"] == "Kalshi's prices were clearly more accurate than the forecast" and "higher than Kalshi's prices" in g and "lower" not in g, g
s = N.summary(rows_(0.0, 0.05)); g = N.plain_interval(s)
assert s["reading"] == "no clear difference" and "lower to" in g and "higher error" in g and "do not show the two are equal" in g, g
g = N.plain_interval(dict(reading="no clear difference", low=-0.1, high=0.05, mkt_day=0.07))   # wider than the market's own error
assert "from 100% lower to 71% higher" in g and "too wide to mean much" in g, g
d = dict(reading="no clear difference", low=0.0, high=0.0, mkt_day=0.07); assert "fit anything from 0% higher to 0% higher" in N.plain_interval(d)  # follows the reading
w = N.summary([(tk(DAYS[i], c), 0.5, 0.2 if i else 0.6, "no", 0) for i in range(6) for c in (CITIES if i else CITIES[:1])])
assert abs(w["mkt_day"] - (0.36 + 5 * 0.04) / 6) < 1e-12 and abs(w["brier_mkt"] - (0.36 + 30 * 0.04) / 31) < 1e-12, "days weighted equally"
assert N.summary(rows_(-0.05, 0.01, days=4))["reading"].startswith("too few market days")
print("readings: clearly better, clearly worse, no clear difference with its interval, too few days: ok")
# the checks a stored look did not meet; a missing stored number is n/a, never a made-up zero
assert N.failed_checks(dict(markets=134, brier_fc=0.06, brier_mkt=0.07, margin=[-0.01, 0.001, 10], trades=60, pnl=2.0)) == []
f = N.failed_checks(dict(markets=90, brier_fc=0.08, brier_mkt=0.07, margin=None, trades=18, pnl=-1.0))
assert len(f) == 5 and f[3] == "at least 50 settled trades (18)", f
f = N.failed_checks(dict(margin=None)); assert "at least 100 resolved markets (n/a)" in f and "net P&L above zero (n/a)" in f, f
print("unmet checks from the stored numbers; missing numbers shown as n/a: ok")
