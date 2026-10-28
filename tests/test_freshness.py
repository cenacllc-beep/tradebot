"""Freshness monitor and the shared clock, on fake folders (no network): every check's ok / stale / fail / waiting
status, overdue settlements, a page older than its data, scheduled-job results from logs\\tasks.log, clock skew,
timestamps in the future, reports older than their data, tolerance of corrupt files, and that it never writes to
paper.db. python test_freshness.py WORK OUT"""
import os, sys, json, shutil, sqlite3, hashlib, types
from datetime import datetime, timezone, timedelta
WORK, OUT = sys.argv[1], sys.argv[2]
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, WORK)
from tbcommon import clock
import freshness as F

H = 3600
# ---- clock: one zone, one format ----
t = datetime(2026, 10, 23, 14, 33, 5, tzinfo=timezone.utc).timestamp()   # 10:33:05 AM in La Paz
assert clock.iso(t) == "2026-10-23T10:33:05-04:00", clock.iso(t)
assert clock.iso(t, seconds=False) == "2026-10-23T10:33-04:00"
assert clock.label(t) == "Oct 23, 10:33 AM", clock.label(t)
assert clock.label(t + 2 * H) == "Oct 23, 12:33 PM" and clock.label(t - 10 * H) == "Oct 23, 12:33 AM", (clock.label(t + 2 * H), clock.label(t - 10 * H))
assert clock.label(None) == "never" and clock.label(0) == "never"
early = datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc).timestamp()   # 10 PM the evening before, in bot time
assert str(clock.bot_date(early)) == "2026-10-22" and str(clock.bot_date(t)) == "2026-10-23"
assert clock.human_age(None) == "unknown" and clock.human_age(59) == "0 min" and clock.human_age(3700) == "1 h 1 min"
assert clock.human_age(2 * H) == "2 h" and clock.human_age(3 * 86400) == "3 days" and clock.human_age(-120) == "2 min in the future"
assert clock.age(None) is None and clock.age(100, at=160) == 60
assert isinstance(clock.pc_offset_hours(t), float)

# ---- a fake tradebot folder ----
NOW = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc).timestamp()   # Oct 30, noon bot time: inside PLAN5 L's window


def folder(name):
    root = os.path.join(OUT, name)
    for d in ("backups", "logs", "offsite", os.path.join("research", "data", "lip"), os.path.join("research", "data", "structure"),
              os.path.join("research", "results")):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    return root


def touch(root, rel, ts, text="x"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(p, (ts, ts))
    return p


def paper(root, scan_ts, open_tickers=(), grid_age=H, future=False):
    p = os.path.join(root, "paper.db")
    c = sqlite3.connect(p)
    c.execute("create table obs(ticker text,version text,ts real,mid real,market_type text)")
    c.execute("create table trades(id integer primary key,ts real,ticker text,side text,n integer,status text)")
    c.execute("create table shadow_orders(id integer primary key,status text)")
    c.execute("create table scans(scan_id text primary key,started_ts real,kind text)")
    c.execute("create table decisions(decision_id text,scan_id text,ts real,inputs text)")
    c.execute("insert into obs values('KXRAINNYC-26OCT31-T0','v3',?,0.4,'rain')", (scan_ts + (2 * H if future else 0),))
    c.execute("insert into scans values('s1',?,'scan')", (scan_ts,))
    c.execute("insert into decisions values('d1','s1',?,?)", (scan_ts, json.dumps(dict(grid=dict(fetched=scan_ts - grid_age)))))
    c.execute("insert into decisions values('d2','s1',?,null)", (scan_ts,))
    for k in open_tickers:
        c.execute("insert into trades(ts,ticker,side,n,status) values(?,?,'yes',3,'open')", (scan_ts, k))
    c.commit(); c.close()
    return p


def by_key(rows):
    return {r["key"]: r for r in rows}


def tasks(root, text):
    with open(os.path.join(root, "logs", "tasks.log"), "w", encoding="utf-8") as f:
        f.write(text)


def iso(ts):
    return clock.iso(ts)


# 1. nothing at all: no crash, the missing database fails, everything else waits
root = folder("empty")
rows = F.checks(root=root, db=os.path.join(root, "paper.db"), now=NOW, offsite=os.path.join(root, "offsite"))
K = by_key(rows)
assert K["scan"]["status"] == "fail" and "paper.db" in K["scan"]["detail"], K["scan"]
assert all(r["status"] in F.STATUSES for r in rows)
for k in ("backup", "offsite", "export", "page", "structure", "discovery", "tasks_evening", "tasks_settle", "tasks_hourly", "clock_skew", "fee_types"):
    assert K[k]["status"] == "waiting", (k, K[k])
assert "install_schedules" in K["tasks_hourly"]["action"] and K["clock_skew"]["action"] == "", (K["tasks_hourly"], K["clock_skew"])
assert K["lip_samples"]["status"] == "stale" and "nothing since the window opened" in K["lip_samples"]["detail"], K["lip_samples"]
assert F.summary_line(rows).startswith("FRESHNESS: ") and "failed" in F.summary_line(rows)

# 2. everything current
root = folder("fresh")
scan = NOW - 15 * H   # last night's 9 PM scan
db = paper(root, scan, open_tickers=("KXRAINNYC-26OCT31-T0",))
digest = hashlib.sha256(open(db, "rb").read()).hexdigest()
touch(root, "backups/paper_20261029_210000_postscan.db", scan + 60)
touch(root, "offsite/paper_20261029_210000_postscan.db", scan + 60)
touch(root, "backups/paper_latest.json", scan + 90, "{}")
touch(root, "dashboard.html", NOW - 30 * 60)
touch(root, "marks.jsonl", NOW - 30 * 60, json.dumps(dict(ts=NOW - 30 * 60, marks={})) + "\n")
touch(root, "research/data/lip/programs.json", NOW - 2 * H, json.dumps(dict(fetched=NOW - 2 * H, rows=[])))
touch(root, "research/data/lip/samples.jsonl", NOW - 40 * 60, json.dumps(dict(ts=NOW - 50 * 60)) + "\n" + json.dumps(dict(ts=NOW - 40 * 60)) + "\n")
touch(root, "research/data/lip/series.json", NOW - 5 * 86400, "{}")
touch(root, "research/data/structure/runs.jsonl", NOW - 3 * H, json.dumps(dict(ts=NOW - 3 * H)) + "\n")
touch(root, "research/results/structure.md", NOW - 3 * H + 30)
c = sqlite3.connect(os.path.join(root, "research", "data", "discovery.db"))
c.execute("create table runs(ts real,seconds real,requests integer,open_seen integer,new integer,closed integer,series integer,note text)")
c.execute("insert into runs values(?,1,1,1,1,1,1,null)", (NOW - 4 * H,)); c.execute("insert into runs values(?,null,null,null,null,null,null,'started')", (NOW - H,))
c.commit(); c.close()
tasks(root, "===== %s evening\nlots of output\n===== %s evening done (exit 0)\n"
            "===== %s settle\n===== %s settle done (exit 0)\n"
            "===== %s hourly\n===== %s hourly done (exit 0)\n" % (iso(scan - 300), iso(scan + 900), iso(NOW - 25 * H), iso(NOW - 24 * H), iso(NOW - 45 * 60), iso(NOW - 40 * 60)))
F.save(os.path.join(root, "research", "data", "clock.json"), dict(measured=NOW - 40 * 60, skew_s=1.5))
rows = F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite"))
K = by_key(rows)
for k in ("scan", "settle", "forecast_at_scan", "backup", "offsite", "export", "page", "marks", "lip_programs", "lip_samples",
          "structure", "discovery", "tasks_evening", "tasks_settle", "tasks_hourly", "clock_skew"):
    assert K[k]["status"] == "ok", (k, K[k])
assert K["discovery"]["last"] == NOW - 4 * H, "a started-but-unfinished run is not a refresh"
assert K["fee_types"]["status"] == "info" and K["fee_types"]["age_s"] is None, K["fee_types"]   # lip rewrites the file each sample: its date says nothing
assert K["lip_samples"]["last"] == NOW - 40 * 60 and K["marks"]["last"] == NOW - 30 * 60
assert "1 h 0 min" in K["forecast_at_scan"]["detail"] or "1 h" in K["forecast_at_scan"]["detail"], K["forecast_at_scan"]
assert K["pc_zone"]["status"] in ("ok", "info") and "report_structure" not in K
assert F.summary_line(rows) == "FRESHNESS: all current (%d checks)" % len(rows), F.summary_line(rows)
assert all(r["action"] == "" for r in rows if r["status"] in ("ok", "info"))
F.write_reports(rows, root=root, now=NOW)
md = open(os.path.join(root, "research", "results", "freshness.md"), encoding="utf-8").read()
js = json.load(open(os.path.join(root, "research", "results", "freshness.json"), encoding="utf-8"))
assert "La Paz time (UTC-4)" in md and "Oct 30, 12:00 PM" in md and md.count("\n| ") == len(rows) + 1, md[:400]
assert js["made"] == "2026-10-30T12:00:00-04:00" and len(js["checks"]) == len(rows) and js["summary"] == F.summary_line(rows)
assert hashlib.sha256(open(db, "rb").read()).hexdigest() == digest, "paper.db must never be written"

# 3. stale and failed
root = folder("stale")
scan = NOW - 30 * H
db = paper(root, scan, open_tickers=("KXRAINNYC-26OCT26-T0", "KXRAINNYC-26OCT31-T0"), grid_age=5 * H)
touch(root, "backups/paper_20261028_210000_postscan.db", NOW - 40 * H)
touch(root, "dashboard.html", scan - 600)   # built before the scan's data
touch(root, "research/data/structure/runs.jsonl", NOW - H, json.dumps(dict(ts=NOW - H)) + "\n")
touch(root, "research/results/structure.md", NOW - 8 * H)   # the last scan stopped before writing its report
tasks(root, "===== 2026-10-29T20:55:01 evening\n"   # an old line without an offset: read as this PC's local time
            "===== %s evening\n"                       # started, never finished
            "===== %s settle\n===== %s settle done (exit 1)\n"
            "===== %s hourly\n===== %s hourly done (exit 0)\n" % (iso(NOW - 7 * H), iso(NOW - 20 * H), iso(NOW - 20 * H + 60), iso(NOW - 5 * H), iso(NOW - 5 * H + 60)))   # the evening job may wait 6.5 h (jobs.py)
F.save(os.path.join(root, "research", "data", "clock.json"), dict(measured=NOW - H, skew_s=-420.0))
rows = F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite"))
K = by_key(rows)
assert K["scan"]["status"] == "stale" and K["scan"]["action"], K["scan"]
assert K["settle"]["status"] == "stale" and "KXRAINNYC-26OCT26-T0" in K["settle"]["detail"] and "26OCT31" not in K["settle"]["detail"], K["settle"]
assert K["forecast_at_scan"]["status"] == "stale" and "5 h" in K["forecast_at_scan"]["detail"], K["forecast_at_scan"]
assert K["backup"]["status"] == "stale" and K["offsite"]["status"] == "waiting"
assert K["page"]["status"] == "stale", K["page"]
assert K["tasks_evening"]["status"] == "fail" and "never finished" in K["tasks_evening"]["detail"], K["tasks_evening"]
assert K["tasks_settle"]["status"] == "fail" and "exit code 1" in K["tasks_settle"]["detail"], K["tasks_settle"]
assert K["tasks_hourly"]["status"] == "stale", K["tasks_hourly"]
assert K["clock_skew"]["status"] == "fail" and "-420" in K["clock_skew"]["detail"] and "time sync" in K["clock_skew"]["action"], K["clock_skew"]
assert K["report_structure"]["status"] == "stale", K.get("report_structure")
line = F.summary_line(rows)
assert line.startswith("FRESHNESS: ") and "9 stale, 3 failed: Scheduled evening run (fail)" in line and "Evening scan (30 h old)" in line, line
# a page within 2 minutes of the data is fine; a small skew is only flagged
touch(root, "dashboard.html", scan - 60); F.save(os.path.join(root, "research", "data", "clock.json"), dict(measured=NOW - H, skew_s=75))
K = by_key(F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite")))
assert K["page"]["status"] == "stale" and "built before" not in K["page"]["detail"], K["page"]   # stale only by age (31 h)
assert K["clock_skew"]["status"] == "stale", K["clock_skew"]

# 4. a timestamp in the future fails; corrupt files do not crash the monitor
root = folder("future")
db = paper(root, NOW - 2 * H, future=True)
touch(root, "research/data/lip/programs.json", NOW, "{not json")
touch(root, "research/data/clock.json", NOW, "[1, 2")
touch(root, "marks.jsonl", NOW, "\xff garbage\n{\"ts\": \"x\"}\n")
touch(root, "research/data/structure/runs.jsonl", NOW, json.dumps(dict(ts=NOW + 3 * H)) + "\n")
tasks(root, "random text\n===== not-a-time hourly\n")
K = by_key(F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite")))
assert K["scan"]["status"] == "ok", K["scan"]          # obs is 2 h ahead of the scan row but not ahead of now
assert K["structure"]["status"] == "fail" and "ahead of this PC's clock" in K["structure"]["detail"], K["structure"]
assert K["clock_skew"]["status"] == "waiting" and K["lip_programs"]["status"] == "stale" and K["marks"]["status"] == "info"
assert K["tasks_hourly"]["status"] == "info" and "no time" in K["tasks_hourly"]["detail"], K["tasks_hourly"]   # it ran; its time is unreadable

# 4b. review 2026-10-23: a last line longer than the first read, text where a number belongs, and the kill switch
root = folder("review")
db = paper(root, NOW - 50 * H)
big = dict(ts=NOW - 10 * H, found=[dict(kind="all_yes", legs=6, note="x" * 200) for _ in range(400)])
line = json.dumps(big); assert len(line) > 65536
touch(root, "research/data/structure/runs.jsonl", NOW - 10 * H, json.dumps(dict(ts=NOW - 20 * H)) + "\n" + line + "\n")
touch(root, "research/data/clock.json", NOW, json.dumps(dict(skew_s="1.0", measured="2026-10-30T12:00")))
touch(root, "research/data/lip/programs.json", NOW, json.dumps(dict(fetched="2026-10-30T11:00", rows=[])))
touch(root, "research/data/lip/samples.jsonl", NOW, json.dumps(dict(ts=True)) + "\n" + json.dumps(dict(ts=float("nan"))) + "\n")
K = by_key(F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite")))
assert K["structure"]["last"] == NOW - 10 * H and K["structure"]["status"] == "stale", K["structure"]
assert K["clock_skew"]["status"] == "waiting" and K["lip_programs"]["last"] is None and K["lip_samples"]["last"] is None
assert K["scan"]["status"] == "stale" and "evening.cmd" in K["scan"]["action"], K["scan"]
touch(root, "Kill.txt", NOW - 49 * H)
K = by_key(F.checks(root=root, db=db, now=NOW, offsite=os.path.join(root, "offsite")))
assert K["scan"]["status"] == "info" and "kill switch on (Kill.txt" in K["scan"]["detail"] and K["scan"]["action"] == "", K["scan"]
assert F.last_jsonl_ts(os.path.join(root, "missing.jsonl")) is None

# 5. tasks.log parsing: offsets are exact, naive times are this PC's local time
p = os.path.join(OUT, "tasks.log")
with open(p, "w", encoding="utf-8") as f:
    f.write("===== 2026-10-23T10:00:00-04:00 hourly\n===== 2026-10-23T10:01:30.1234567-04:00 hourly done (exit 0)\n"
            "===== 2026-10-23T20:55:00 evening\n")
R = F.task_runs(p)
assert R["hourly"]["started"] == datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc).timestamp() and R["hourly"]["exit"] == 0
assert abs(R["hourly"]["done"] - R["hourly"]["started"] - 90.1234567) < 1e-3, R["hourly"]
assert R["evening"]["started"] == datetime(2026, 10, 23, 20, 55).timestamp() and R["evening"]["done"] is None
# PowerShell did not answer (review 2026-10-23): the run still counts, without a time; a failure is still a failure
with open(p, "w", encoding="utf-8") as f:
    f.write("=====  settle\n===== no-time settle done (exit 0)\n===== no-time evening\n===== no-time evening done (exit 1)\n")
R = F.task_runs(p)
assert R["settle"]["finished"] and R["settle"]["notime"] and R["settle"]["exit"] == 0 and R["settle"]["done"] is None, R
root = folder("notime"); tasks(root, open(p, encoding="utf-8").read())
K = by_key(F.checks(root=root, db=os.path.join(root, "paper.db"), now=NOW, offsite=os.path.join(root, "offsite")))
assert K["tasks_settle"]["status"] == "info" and K["tasks_evening"]["status"] == "fail" and K["tasks_hourly"]["status"] == "waiting", (K["tasks_settle"], K["tasks_evening"])
# a job missing from the tail: the whole log is read below the cap, not above it
big = os.path.join(OUT, "big.log")
with open(big, "w", encoding="utf-8") as f:
    f.write("===== 2026-10-20T14:51:00-04:00 settle\n===== 2026-10-20T14:55:00-04:00 settle done (exit 0)\n" + ("x" * 99 + "\n") * 3000)
    f.write("===== 2026-10-23T10:20:00-04:00 hourly\n===== 2026-10-23T10:22:00-04:00 hourly done (exit 0)\n")
assert sorted(F.task_runs(big, tail=10000)) == ["hourly", "settle"]
cap = F.FULL_READ_CAP; F.FULL_READ_CAP = 100000
assert sorted(F.task_runs(big, tail=10000)) == ["hourly"]
F.FULL_READ_CAP = cap

# 6. the clock measurement reads Kalshi's Date header (fake response, no network)
root = folder("clock")
seen = {}
def fake_get(url, headers=None, timeout=None):
    seen.update(url=url, headers=headers)
    from email.utils import formatdate
    import time as _t
    return types.SimpleNamespace(headers={"Date": formatdate(_t.time() - 30, usegmt=True)}, status_code=200)
rec = F.measure_clock(root=root, get=fake_get)
assert 28 <= rec["skew_s"] <= 32, rec
assert seen["url"].startswith("https://api.elections.kalshi.com/trade-api/v2/") and seen["headers"] == {"User-Agent": "tradebot-paper-research/1.0"}, seen
assert json.load(open(os.path.join(root, "research", "data", "clock.json")))["skew_s"] == rec["skew_s"]

# 7. outside PLAN5 L's window nothing is expected from it
before = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc).timestamp()
K = by_key(F.checks(root=folder("prewindow"), db=os.path.join(OUT, "none.db"), now=before, offsite=os.path.join(OUT, "none")))
assert K["lip_samples"]["status"] == "waiting" and K["lip_programs"]["status"] == "waiting", (K["lip_samples"], K["lip_programs"])
print("freshness and clock: all checks passed")
