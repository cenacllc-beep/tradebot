"""Data freshness and timestamp consistency monitor (added 2026-10-23, reliability work).

Every dataset the bot depends on has an expected refresh interval. This module reads each one's latest timestamp,
compares its age with that limit, and checks that timestamps agree with each other and with the clock. It is
read-only: paper.db is opened mode=ro, other files are only read, and nothing here changes a decision (the shadow
selector's own STALE_DATA rule is separate and unchanged).

- `python freshness.py`: a table on screen, research/results/freshness.json and freshness.md, and one summary line
  starting "FRESHNESS:" for logs\\tasks.log and the cloud reporters. Exit code 0, because monitoring never stops a
  batch; with --strict, 1 when a check failed.
- `python freshness.py --clock`: also measures this PC's clock against Kalshi's server clock (one public GET to the
  Kalshi API the bot already uses, read from the HTTP Date header) and keeps it in research/data/clock.json. The
  day-start guard and every stored timestamp depend on the PC clock.
- The dashboard's control center calls checks() and shows the same table, with a chip when a check failed.

Statuses:
- ok: within its limit.
- stale: older than its limit.
- fail: broken, for example a job ended with an error or a timestamp is in the future.
- waiting: not started yet, or not expected now.
- info: worth knowing, never alarming.

Checks:
- **Cache freshness:**
  - the evening scan;
  - overdue settlements;
  - backups in the folder and off the folder;
  - the JSON export;
  - the dashboard page;
  - live prices;
  - PLAN5 L programs, samples and fee types;
  - the structure scan;
  - the market catalogue;
  - the forecast's age at the last scan;
  - each scheduled job in logs\\tasks.log.
- **Timestamp consistency:**
  - timestamps in the future;
  - reports older than the data they describe;
  - the PC's time zone vs the bot's (UTC-4);
  - measured clock skew.

Python 3.8+, standard library (requests only for --clock)."""
import os, sys, re, json, glob, sqlite3, time
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from tbcommon import clock
from tbcommon.jsonio import load as _load_json, save
from tbcommon.parse import rts

H = 3600
LIMITS = {   # seconds: how old each dataset may be, from the job that refreshes it and how often that job runs
    "scan": 26 * H,             # evening scan, daily at 8:55 PM
    "settle": 24 * H,           # an open trade should be settled within a day of its market's close
    "backup": 26 * H,           # every scan and settle backs up
    "export": 26 * H,           # export.py after each scan
    "page": 26 * H,             # dashboard.html after every run
    "marks": 2 * H,             # marks.py hourly, while anything is open
    "lip_programs": 7 * H,      # lip.py re-reads programs older than 6 h
    "lip_samples": 2 * H,       # one sample an hour inside the PLAN5 L window
    "structure": 7 * H,         # every 6 h from the hourly job
    "discovery": 7 * H,         # every 6 h from the hourly job
    "forecast_at_scan": 3 * H,  # the shadow selector's own STALE_DATA limit
    "tasks_evening": 26 * H, "tasks_settle": 26 * H, "tasks_hourly": 2 * H,
    "task_running": 2 * H,      # a job that started this long ago without a finish line died (PC asleep, closed window)
    "task_running_evening": 6.5 * H,   # the evening job may wait for the network until 1 AM (jobs.py; 6-hour task limit)
    "task_running_settle": 3.5 * H,    # the settle may wait an hour for the network, then for the lock (3-hour task limit)
    "task_running_hourly": 2.5 * H,    # 2-hour task limit, plus a margin
    "clock_skew": 60,           # seconds off Kalshi's clock before it is flagged; past FAIL_SKEW it fails
    "clock_measured": 26 * H,
}
FAIL_SKEW = 300                 # the day-start guard and fill times have no margin for this much
FUTURE_TOLERANCE = 300          # a timestamp this far ahead of the PC clock is an error, not rounding
PAGE_LAG = 120                  # the page may be built this long before the data it shows was written
BOT_OFFSET_HOURS = -4
STATUSES = ("ok", "stale", "fail", "waiting", "info")
TASK_LINE = re.compile(r"^=====\s+(?:(\S+)\s+)?(evening|settle|hourly)(\s+done \(exit (-?\d+)\))?\s*$")
FULL_READ_CAP = 64 * 1024 * 1024   # tasks.log is read whole only below this size


# ---------- reading timestamps (read-only) ----------
def _ro(db):
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)


def _one(c, sql, args=()):
    """First column of the first row, or None (also when the table does not exist yet)."""
    try:
        r = c.execute(sql, args).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None


def load(p, default=None):
    """A JSON file, or default when it is missing or unreadable (a monitor must not crash on the file it monitors)."""
    try:
        return _load_json(p, default)
    except (OSError, ValueError):
        return default


def _ts(v):
    """A usable epoch timestamp, or None: numbers only (not bool, not NaN or infinite). A file whose field holds text
    or anything else counts as having no timestamp instead of crashing the monitor (review 2026-10-23)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if v == v and abs(v) != float("inf") else None


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def _newest(pattern):
    ts = [t for t in (_mtime(p) for p in glob.glob(pattern)) if t]
    return max(ts) if ts else None


def last_jsonl_ts(p, key="ts"):
    """The timestamp of the last readable line of a JSONL file. Reads the end of the file first (64 KB, then 1 MB,
    16 MB, then all of it) until a whole line parses, so it stays fast as files grow and still works when one line is
    longer than the first read (a structure-scan line can pass 70 KB; review 2026-10-23)."""
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            for tail in (65536, 1 << 20, 1 << 24, size):
                start = max(0, size - tail)
                f.seek(start)
                lines = f.read().decode("utf-8", "replace").splitlines()
                if start > 0 and lines:
                    lines = lines[1:]   # the first line read may be cut
                for ln in reversed(lines):
                    try:
                        v = _ts(json.loads(ln).get(key))
                    except (ValueError, AttributeError):
                        continue
                    if v is not None:
                        return v
                if start == 0:
                    return None
    except OSError:
        return None
    return None


def task_runs(path, tail=4 * 1024 * 1024):
    """{job: dict(started, done, finished, exit, notime)} for the latest run of each job in logs\\tasks.log. Lines are
    written by tasks\\*.cmd: "===== <time> <job>" and "===== <time> <job> done (exit N)". Times with an offset are
    exact; older lines without one were written in this PC's local time, which is how rts() reads them. When
    PowerShell does not answer, the time is missing or "no-time": the run still counts, with notime set. The log only
    grows, so the last `tail` bytes are read first, and the whole file only when a job is missing from them and the
    file is under FULL_READ_CAP (a deleted schedule must not make every page build read a huge log)."""
    def scan(text):
        out = {}
        for ln in text.splitlines():
            m = TASK_LINE.match(ln.strip())
            if not m:
                continue
            t, job = (rts(m.group(1)) if m.group(1) else None), m.group(2)
            if m.group(3):
                r = out.setdefault(job, dict(started=None, notime=False))
                r.update(done=t, finished=True, exit=int(m.group(4)), notime=r.get("notime") or t is None)
            else:
                out[job] = dict(started=t, done=None, finished=False, exit=None, notime=t is None)
        return out
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail))
            out = scan(f.read().decode("utf-8", "replace"))
            if tail < size <= FULL_READ_CAP and len(out) < 3:
                f.seek(0)
                out = scan(f.read().decode("utf-8", "replace"))
    except OSError:
        return {}
    return out


# ---------- one result row ----------
def check(key, name, last, limit, now, detail="", action="", status=None):
    """A result row. Without an explicit status: waiting (no timestamp), fail (in the future), ok or stale (by age).
    The action is kept only when something needs doing or has not started (ok and info rows have none)."""
    last = _ts(last)
    age = clock.age(last, now) if last else None
    if status is None:
        if last is None:
            status = "waiting"
        elif age < -FUTURE_TOLERANCE:
            status = "fail"
            detail = "timestamp is %s ahead of this PC's clock. %s" % (clock.human_age(-age), detail)
            action = action or "Check the PC clock and time zone."
        else:
            status = "ok" if age <= limit else "stale"
    return dict(key=key, name=name, status=status, last=last, last_label=clock.label(last),
                last_iso=clock.iso(last) if last else None, age_s=age, limit_s=limit, detail=detail.strip(),
                action=action if status in ("stale", "fail", "waiting") else "")


# ---------- the checks ----------
def _kill_file(root):
    """The kill file in the tradebot folder, by core.kill_file's rule (KILL or KILL.<anything>, any case), or None. Only
    changes how a stale scan is described; an unreadable folder counts as no kill file here (core fails closed)."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    for n in names:
        if n.lower() == "kill" or n.lower().startswith("kill."):
            return os.path.join(root, n)
    return None


def _paper(db, now, root):
    """Rows for the scan, settlements and forecast age, the latest data time, and whether anything is open."""
    rows, last, has_open = [], None, False
    try:
        c = _ro(db) if os.path.exists(db) else None
    except sqlite3.Error:
        c = None
    if c is None:
        rows.append(check("scan", "Evening scan", None, LIMITS["scan"], now, "paper.db not found or unreadable",
                          "Check that paper.db is in the tradebot folder.", status="fail"))
        return rows, None, False
    try:
        last_obs = _ts(_one(c, "select max(ts) from obs"))
        last_scan = _ts(_one(c, "select max(started_ts) from scans where kind='scan'"))
        last = max([t for t in (last_obs, last_scan) if t] or [None])
        row = check("scan", "Evening scan", last, LIMITS["scan"], now,
                    "markets last logged %s" % clock.label(last_obs) if last_obs else "no market logged yet",
                    "Run tasks\\evening.cmd between 8:50 PM and 1:00 AM, or check that the 8:55 PM schedule exists.")
        kill = _kill_file(root)
        if kill and row["status"] in ("stale", "waiting"):   # scans are halted on purpose: not a fault, and no advice to run one
            row.update(status="info", action="", detail="kill switch on (%s, since %s): scans are halted until you run .\\run unkill. %s" % (
                os.path.basename(kill), clock.label(_mtime(kill)), row["detail"]))
        rows.append(row)
        # open trades past their market's close
        try:
            opened = [r[0] for r in c.execute("select ticker from trades where status='open'")]
        except sqlite3.Error:
            opened = []
        has_open = bool(opened) or bool(_one(c, "select count(*) from shadow_orders where status='filled'"))
        try:
            import postmortem
            closes = [(t, postmortem.day_start(t or "")) for t in opened]
        except Exception:   # an approximate close needs postmortem.py; without it, say so instead of guessing
            closes = [(t, None) for t in opened]
        overdue = [(t, ds + 86400) for t, ds in closes if ds and now > ds + 86400 + LIMITS["settle"]]
        if not opened:
            rows.append(check("settle", "Settlements", None, LIMITS["settle"], now, "no open paper trades", status="ok"))
        else:
            oldest = min((cl for _, cl in overdue), default=None)
            r = check("settle", "Settlements", oldest, LIMITS["settle"], now,
                      ("%d open trade%s past close by more than a day: %s" % (len(overdue), "" if len(overdue) == 1 else "s", ", ".join(t for t, _ in overdue[:4])))
                      if overdue else "%d open, none overdue" % len(opened),
                      "Run tasks\\settle.cmd (results wait at Kalshi; nothing is lost).",
                      status="stale" if overdue else "ok")
            rows.append(r)
        # the forecast's age when the last ledger scan used it
        sid = _one(c, "select scan_id from scans where kind='scan' order by started_ts desc limit 1")
        if sid:
            worst = None
            try:
                for ts, inputs in c.execute("select ts,inputs from decisions where scan_id=? and inputs is not null", (sid,)):
                    g = (json.loads(inputs) or {}).get("grid") or {}
                    f, t = _ts(g.get("fetched")), _ts(ts)
                    if f and t:
                        worst = max(worst or 0.0, t - f)
            except (sqlite3.Error, ValueError, AttributeError):
                pass
            rows.append(check("forecast_at_scan", "Forecast data at the last scan", None, LIMITS["forecast_at_scan"], now,
                              "oldest NWS forecast used was %s old" % clock.human_age(worst) if worst is not None else "no forecast inputs recorded",
                              "Trades on stale forecasts are already rejected by the selector; check that NWS was reachable.",
                              status="waiting" if worst is None else ("ok" if worst <= LIMITS["forecast_at_scan"] else "stale")))
    finally:
        c.close()
    return rows, last, has_open


def _tasks(root, now):
    rows = []
    runs = task_runs(os.path.join(root, "logs", "tasks.log"))
    for job, name in (("evening", "Scheduled evening run"), ("settle", "Scheduled settle"), ("hourly", "Scheduled hourly research")):
        key, r = "tasks_" + job, runs.get(job)
        if not r:
            rows.append(check(key, name, None, LIMITS[key], now, "no run in logs\\tasks.log yet",
                              "Double-click tasks\\install_schedules.cmd once.", status="waiting"))
            continue
        if r.get("finished"):
            row = check(key, name, r.get("done"), LIMITS[key], now, "last run finished with exit code %s" % r.get("exit"),
                        "Check that the schedule exists (logs\\schedules.txt).")
            if r.get("exit") != 0 and row["status"] != "fail":
                row.update(status="fail", action="Read the end of logs\\tasks.log for the error.")
            elif r.get("done") is None:   # it ran, but PowerShell gave no time, so its age is unknown
                row.update(status="info", detail="last run finished with exit code 0, but its log line has no time (PowerShell did not answer)")
        elif r.get("started") is None:
            row = check(key, name, None, LIMITS[key], now, "a run started, but its log line has no time (PowerShell did not answer)", status="info")
        else:
            row = check(key, name, r.get("started"), LIMITS[key], now, "started %s, still running" % clock.label(r.get("started")))
            if r.get("started") and now - r["started"] > LIMITS.get("task_running_" + job, LIMITS["task_running"]):
                row.update(status="fail", detail="started %s and never finished" % clock.label(r["started"]),
                           action="The PC may have slept or the window was closed mid-run; run it again.")
        rows.append(row)
    return rows


def _clock_rows(root, now):
    off = clock.pc_offset_hours(now)
    rows = [check("pc_zone", "PC time zone", None, 0, now,
                  "this PC is at UTC%+g; the bot's reports use UTC%+d" % (off, BOT_OFFSET_HOURS),
                  "Optional: set Windows to (UTC-04:00) Georgetown, La Paz, Manaus, San Juan. Reports name their zone either way.",
                  status="ok" if abs(off - BOT_OFFSET_HOURS) < 1e-6 else "info")]
    ck = load(os.path.join(root, "research", "data", "clock.json"), None)
    sk = _ts(ck.get("skew_s")) if isinstance(ck, dict) else None
    if sk is None:
        rows.append(check("clock_skew", "PC clock vs Kalshi", None, LIMITS["clock_measured"], now,
                          "not measured yet (freshness.py --clock runs hourly)", status="waiting"))
        return rows
    fix = "Turn on automatic time sync in Windows (Settings > Time & language > Date & time > Sync now)."
    row = check("clock_skew", "PC clock vs Kalshi", ck.get("measured"), LIMITS["clock_measured"], now,
                "PC was %+.0f s from Kalshi's clock when measured" % sk, "Run freshness.py --clock (the hourly job does).")
    if row["status"] == "ok" and abs(sk) > LIMITS["clock_skew"]:
        row.update(status="fail" if abs(sk) > FAIL_SKEW else "stale", action=fix)
    rows.append(row)
    return rows


def checks(root=None, db=None, now=None, offsite=None):
    """Every check as a list of rows (see check()). Read-only. Arguments exist for tests; the defaults are this folder,
    PAPER_DB, the clock, and TRADEBOT_OFFSITE_BACKUPS as backup.py uses them."""
    root = root or HERE
    now = clock.now() if now is None else now
    if db is None:
        env = os.getenv("PAPER_DB", "paper.db")
        db = env if os.path.isabs(env) else os.path.join(root, env)
    offsite = offsite or os.getenv("TRADEBOT_OFFSITE_BACKUPS", os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups"))
    out, data_last, has_open = _paper(db, now, root)
    # backups and the export
    out.append(check("backup", "Backups in the folder", _newest(os.path.join(root, "backups", "paper_*.db")), LIMITS["backup"], now,
                     "newest backups\\paper_*.db", "Scans and settles back up; if they ran and this is stale, run .\\run backup and read its message."))
    out.append(check("offsite", "Backups outside the folder", _newest(os.path.join(offsite, "paper_*.db")), LIMITS["backup"], now,
                     "newest in %s" % offsite, "Check that this folder exists and can be written."))
    out.append(check("export", "JSON export", _mtime(os.path.join(root, "backups", "paper_latest.json")), LIMITS["export"], now,
                     "backups\\paper_latest.json (the off-laptop copy)", "export.py runs after each scan; run .\\run export."))
    # the page, and whether it was built before the data it shows
    page = _mtime(os.path.join(root, "dashboard.html"))
    row = check("page", "Dashboard page", page, LIMITS["page"], now, "dashboard.html", "Run .\\run dashboard.")
    if page and data_last and page < data_last - PAGE_LAG and row["status"] == "ok":
        row.update(status="stale", detail="dashboard.html was built before the latest scan data (%s)" % clock.label(data_last),
                   action="Run .\\run dashboard.")
    out.append(row)
    # live prices, needed only while something is open
    out.append(check("marks", "Live prices of open positions", last_jsonl_ts(os.path.join(root, "marks.jsonl")), LIMITS["marks"], now,
                     "marks.jsonl" + ("" if has_open else " (nothing open, so not needed)"), "The hourly job runs marks.py; check tasks\\hourly.cmd.",
                     status=None if has_open else "info"))
    # research caches
    lip_dir = os.path.join(root, "research", "data", "lip")
    start, end = _lip_window(root)
    in_window = start is not None and start <= now < end
    progs = load(os.path.join(lip_dir, "programs.json"), None)
    fetched = _ts(progs.get("fetched")) if isinstance(progs, dict) else None
    moved = lip_moved(root)
    second = os.path.exists(os.path.join(lip_dir, "SECONDARY.txt")) and not moved
    if second:   # since 2026-10-29 this PC samples alongside GitHub: an hour missed here can be taken there, so only a
        # sampler that has stopped altogether (nothing for a day inside the window) is flagged
        detail = ("this PC samples alongside GitHub Actions; the two copies are merged before the single score, so an hour"
                  " missed here (laptop asleep) can still be taken there")
        last = _lip_last(lip_dir)
        base = last if (last and start and last >= start) else start   # inside the window, age counts from its start
        out.append(check("lip_samples", "PLAN5 L hourly samples (this PC)", base if in_window else last, 24 * H, now, detail,
                         "Nothing sampled here for a day: check tasks\\hourly.cmd and logs\\tasks.log.",
                         status=None if in_window else "info"))
    if moved:   # sampling runs elsewhere since 2026-10-28 (GitHub Actions): this copy's age says nothing
        out.append(check("lip_samples", "PLAN5 L hourly samples", _lip_last(lip_dir), LIMITS["lip_samples"], now,
                         moved, status="info"))
    for key, name, last, detail, action in () if (moved or second) else (
            ("lip_programs", "PLAN5 L reward programs", fetched, "cached list of liquidity programs", "The hourly job refreshes it; check tasks\\hourly.cmd."),
            ("lip_samples", "PLAN5 L hourly samples", _lip_last(lip_dir),
             "window %s to %s" % (clock.label(start), clock.label(end)) if start else "", "Missed hours count against the test; check the hourly schedule.")):
        if not in_window:   # outside the window nothing refreshes these, by design
            out.append(check(key, name, last, LIMITS[key], now, detail, status="waiting" if start is None or now < start else "info"))
        elif last is None or last < start:   # inside the window: age counts from the window's start until the first refresh
            row = check(key, name, start, LIMITS[key], now, "nothing since the window opened. " + detail, action)
            row.update(last=last, last_label=clock.label(last), last_iso=clock.iso(last) if last else None)
            out.append(row)
        else:
            out.append(check(key, name, last, LIMITS[key], now, detail, action))
    # lip.py reads each series' fee type once and keeps it; it rewrites the file every sample, so the file's date says
    # nothing about the age of its entries (review 2026-10-23). Shown as information, not as an age check.
    fee = os.path.exists(os.path.join(lip_dir, "series.json"))
    out.append(check("fee_types", "Fee types cached by PLAN5 L", None, 0, now,
                     "each series' fee type is read once and kept; to re-read them, delete research\\data\\lip\\series.json"
                     if fee else "not cached yet", status="info" if fee else "waiting"))
    st_last = last_jsonl_ts(os.path.join(root, "research", "data", "structure", "runs.jsonl"))
    out.append(check("structure", "Market-structure scan", st_last, LIMITS["structure"], now,
                     "research\\data\\structure\\runs.jsonl", "The hourly job runs it every 6 h."))
    d_last = None
    dsc = os.path.join(root, "research", "data", "discovery.db")
    if os.path.exists(dsc):
        try:
            cd = _ro(dsc)
            d_last = _ts(_one(cd, "select max(ts) from runs where note is null"))
            cd.close()
        except sqlite3.Error:
            pass
    out.append(check("discovery", "Market catalogue", d_last, LIMITS["discovery"], now, "research\\data\\discovery.db",
                     "The hourly job refreshes it every 6 h."))
    out += _tasks(root, now)
    out += _clock_rows(root, now)
    # reports older than the data they describe
    sm = _mtime(os.path.join(root, "research", "results", "structure.md"))
    if sm and st_last and sm < st_last - PAGE_LAG:
        out.append(check("report_structure", "Structure report", sm, 0, now, "structure.md is older than its last scan (%s)" % clock.label(st_last),
                         "The scan stopped before writing its report; run .\\run structure.", status="stale"))
    dm = _mtime(os.path.join(root, "research", "results", "discovery.md"))
    if dm and d_last and dm < d_last - PAGE_LAG:
        out.append(check("report_discovery", "Catalogue summary", dm, 0, now,
                         "discovery.md was written before the latest catalogue refresh (%s); the hourly job refreshes without summarizing" % clock.label(d_last),
                         status="info"))
    return out


def _lip_last(lip_dir):
    """The newest sample time: research/lip.py keeps samples.jsonl and, since 2026-10-28, adds one samples-YYYYMMDD.jsonl a day."""
    try:
        daily = sorted(f for f in os.listdir(lip_dir) if re.match(r"samples-\d{8}\.jsonl$", f))
    except OSError:
        daily = []
    ts = [last_jsonl_ts(os.path.join(lip_dir, f)) for f in ["samples.jsonl"] + daily[-1:]]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def lip_moved(root):
    """The first line of research/data/lip/MOVED.txt under root, or None (PLAN5 L sampling moved to GitHub on 2026-10-28)."""
    try:
        with open(os.path.join(root, "research", "data", "lip", "MOVED.txt"), encoding="utf-8") as fh:
            return (fh.read().strip().splitlines() or ["sampling moved"])[0]
    except OSError:
        return None


def _lip_window(root=None):
    """PLAN5 test L's sampling window (epoch start, end) from this code's research/lip.py, or (None, None). The window is
    part of the code, so it is read from here even when the data folder (root) is elsewhere, as in tests."""
    rp = os.path.join(HERE, "research")
    try:
        if rp not in sys.path:
            sys.path.insert(0, rp)
        import lip
        return lip.START, lip.END
    except Exception:
        return None, None


# ---------- output ----------
def problems(rows):
    return [r for r in rows if r["status"] in ("stale", "fail")]


def summary_line(rows):
    bad = sorted(problems(rows), key=lambda r: r["status"] != "fail")   # failures first, then by check order
    if not bad:
        return "FRESHNESS: all current (%d checks)" % len(rows)
    fails = sum(r["status"] == "fail" for r in bad)
    parts = ["%s (%s)" % (r["name"], clock.human_age(r["age_s"]) + " old" if r["age_s"] is not None and r["status"] == "stale" else r["status"]) for r in bad[:5]]
    return "FRESHNESS: %d stale, %d failed: %s" % (len(bad) - fails, fails, "; ".join(parts))


def write_reports(rows, root=None, now=None):
    root = root or HERE
    now = clock.now() if now is None else now
    res = os.path.join(root, "research", "results")
    os.makedirs(res, exist_ok=True)
    save(os.path.join(res, "freshness.json"), dict(made=clock.iso(now), made_ts=now, zone=clock.ZONE_NOTE, summary=summary_line(rows), checks=rows))
    cell = lambda s: str(s).replace("|", "/").replace("\n", " ")
    L = ["# Data freshness", "", "Checked %s, %s." % (clock.label(now), clock.ZONE_NOTE), "", summary_line(rows), "",
         "| Check | Status | Last | Age | Limit | Detail | What to do |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s |" % " | ".join(cell(x) for x in (
            r["name"], r["status"], r["last_label"], clock.human_age(r["age_s"]) if r["age_s"] is not None else "",
            clock.human_age(r["limit_s"]) if r["limit_s"] else "", r["detail"], r["action"])))
    L += ["", "Read-only monitor: nothing here changes a decision. All times are %s." % clock.ZONE_NOTE]
    with open(os.path.join(res, "freshness.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def measure_clock(root=None, get=None):
    """One public GET to the Kalshi API: skew = this PC's clock at the request midpoint minus the server's Date header
    (1-second resolution, so up to about 1 s of the result is rounding). Kept in research/data/clock.json."""
    from email.utils import parsedate_to_datetime
    from tbcommon.httpclient import KALSHI_PUBLIC, USER_AGENT
    root = root or HERE
    if get is None:
        import requests
        get = requests.get
    t0 = time.time()
    r = get(KALSHI_PUBLIC + "/exchange/status", headers={"User-Agent": USER_AGENT}, timeout=20)
    t1 = time.time()
    server = parsedate_to_datetime(r.headers["Date"]).timestamp()
    rec = dict(measured=t1, skew_s=round((t0 + t1) / 2 - server, 1), rtt_s=round(t1 - t0, 3), source="Kalshi Date header")
    save(os.path.join(root, "research", "data", "clock.json"), rec)
    return rec


def main(argv):
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    if "--clock" in argv:
        try:
            print("clock: this PC is %+.1f s from Kalshi's clock" % measure_clock()["skew_s"])
        except Exception as ex:   # no network: the other checks still run
            print("clock: not measured (%s)" % str(ex)[:120])
    rows = checks()
    try:
        write_reports(rows)
    except OSError as ex:
        print("freshness report not written (%s)" % ex)
    for r in rows:
        print("%-8s %-34s %-20s %s" % (r["status"].upper(), r["name"], r["last_label"], r["detail"]))
    print(summary_line(rows))
    return 1 if ("--strict" in argv and any(r["status"] == "fail" for r in rows)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
