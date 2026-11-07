"""PLAN9 (research/PLAN9.md): v3's hourly chances combined in 6-hour blocks ("v3-6h"), tested on new markets.

Research only: never part of the gate, never connected to live.py. Read-only on paper.db. Uses only data the bot
already logs (NWS, public domain): v3's 24 hourly chances in obs.slices, its forecast obs.fc and the price obs.mid.
Writes only research/results/plan9_*.json and .md, and a copy of each off the folder (TRADEBOT_OFFSITE_BACKUPS, else
Documents\\tradebot_backups, under plan9\\).

Tests (plan section 1), in a fixed order (plan section 6): B, v3-6h vs v3, judged at the one-sided 2.5% line; A, v3-6h
vs Kalshi's price, judged at 2.5% only when B is confirmed. The gate's day-mean Brier statistic (plan section 5); a
futility look at 60 counted market days that shows only the signs of the means, and a final look at 110; each stored
once and copied off the folder.

    python research/plan9.py status     counts only (never accuracy numbers before a look)
    python research/plan9.py auto       the settle job: the identity record, the status, and any look that is due
Python 3.8+, standard library only."""
import os, sys, json, ast, shutil, hashlib, sqlite3
from datetime import date, datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import plan7 as P7   # noqa: E402  (its reused functions are pinned below)

PLAN = "research/PLAN9.md"
FORWARD_FIRST = date(2026, 11, 8)      # the first forward market day (logged by the Nov 7 evening scan, after the freeze)
BACKSTOP = date(2027, 6, 30)           # market days after this never count
BACKSTOP_LOOK = date(2027, 7, 7)       # from here a final look short of 110 days reads "not confirmed"
LOOKS = (60, 110)
READY_AFTER = 7                        # missing results are left out only after a settle ran past this mark (section 6)
ALPHA = 0.025                          # one-sided, B first, then A only if B is confirmed (fixed sequence, section 6)
LO, HI = 0.01, 0.99                    # v3-6h is clipped like v3 (strategy.estimate)
BOOT_MIN_DAYS = 14
RESULTS = os.path.join(HERE, "results")
IDENTITY = "plan9_identity.json"
AMEND = "plan9_amendments.json"
TESTS = (("B", "v3", "v3-6h was more accurate than v3", "v3 was more accurate than v3-6h"),
         ("A", "price", "v3-6h was more accurate than Kalshi's prices", "Kalshi's prices were more accurate than v3-6h"))
REUSED = ("tcrit", "day_means", "margin", "reading", "boot_means", "boot_interval", "_betacf", "t_upper", "t_quantile",
          "market_day", "midnight", "in_window", "mean_se", "lag1", "connect_ro", "default_db")
PINNED_PLAN7 = {   # research/plan7.py as frozen on 2026-11-05 (the same pins as research/plan8.py; tests/test_plan9.py)
    "_betacf": "e25864fc49eeb91b5de301c142f8df84c3ca2d93a5f0048097a4e803d484d71c",
    "boot_interval": "f3f54b2cd974f83ef90dfeda1a21930a4a432f51990d4ca744ac890074088a63",
    "boot_means": "6f8c0cd3d077359f637cc381d1cbbdcf34fd9bd7460d692ea5284403329e9a2b",
    "connect_ro": "6ed2535197dbb0e4451d96e3bb8999c48f8d4e17580ad4d72cae0189a3dbb0c6",
    "day_means": "7c11b28635ae05d82c16458d24555e2419e0a077f901b6fa098659886fb132d9",
    "default_db": "3701e9b48eca69f73b7fee58ea9f2ecbef7b53f7ce0146dccb9501737bc1ea22",
    "in_window": "1c702029f88c824777fcfe04ece72fbce760a27ef09e68058457a6299f50a46f",
    "lag1": "7b3df8f5afdd9c74805acd53bea1056a05ceb8a6f2926a7a7ce40751a7a9e2fb",
    "margin": "edad2e1f24658d291d02c738fc882dd0f51825ce4316cb57dd0d3ef2ac3f3fbc",
    "market_day": "4e7bf1a1416d5e06e5721e9e7a5b76ed130d3f7d4e9d5865437fae1e4c37a98b",
    "mean_se": "92db35ba154a25b04a146f04d2ceb8f99ad927a824ca27e7a16f6993d6e82fd3",
    "midnight": "a90c479c325ae36b1e06b60f78881943c51622015f86b0e8bf55f74a266dc1bc",
    "reading": "c571bf5bfd2a83e781e066314da4f9d1cb427ef31ab70fc0f2cc5e50b951a9a7",
    "t_quantile": "ca188669a12be647eed259b72d78bba97a55ed07b86e8aff80df6aedeea4592a",
    "t_upper": "882e3706a702e674974e655ee23d8e8688c770713d6247d8c244ceee049b7eed",
    "tcrit": "ae71591f2f962c2ad20bb855b1400f604d590dfe328aae978e982efc44e80cf1",
}
# PLAN7's constants that the statistic uses (WINDOW, BOOT_BLOCK, BOOT_DRAWS, BOOT_SEED and the t table T975 behind tcrit
# and reading), as frozen on 2026-11-05: the SHA-256 of current_constants_sha()'s text (tests/test_plan9.py)
PINNED_CONSTANTS = "6e7d4f30c9da82a59c5ece49ba6fa7ae9d555dafe4e32fce493e74b23194421b"


# ---------- files (plan section 8) ----------
def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path):
    """(object, True) for a readable JSON file; (None, False) for a damaged one; (None, True) when it does not exist."""
    if not os.path.exists(path):
        return None, True
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError, RecursionError):
        return None, False


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def offsite():
    """The off-folder backup location backup.py uses (TRADEBOT_OFFSITE_BACKUPS, else Documents\\tradebot_backups)."""
    return os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups")


def offsite_path(path):
    return os.path.join(offsite(), "plan9", "results", os.path.basename(path))


def keep_offsite(path):
    """Copy a written file off the folder unless a copy is already there (a frozen record is never replaced)."""
    saved = offsite_path(path)
    if os.path.exists(saved):
        return None
    try:
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        shutil.copy2(path, saved)
        return None
    except OSError as ex:
        return "PLAN9: off-folder copy of %s failed (%s)" % (os.path.basename(path), ex)


def frozen_record(path):
    """(object, problem) for a once-written record: the local file, else its off-folder copy (restored locally).
    A damaged file is a problem, never overwritten; (None, None) when neither exists."""
    got, ok = _read_json(path)
    if not ok:
        return None, "%s is damaged; the looks wait for the user (restore it from %s)" % (os.path.basename(path), offsite_path(path))
    if got is not None:
        return got, None
    saved = offsite_path(path)
    got, ok = _read_json(saved)
    if not ok:
        return None, "the off-folder copy %s is damaged; the looks wait for the user" % saved
    if got is None:
        return None, None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(saved, path)
    except OSError:
        pass
    return got, None


# ---------- identity (plan section 8) ----------
def file_hash(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _sha(f.read().replace("\r\n", "\n"))
    except (OSError, ValueError):
        return None


def source_hash(path, name):
    """SHA-256 of a top-level function's source (line endings normalized), or None."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("\r\n", "\n")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(text, node)
            return _sha(seg) if seg else None
    return None


def current_constants_sha():
    return _sha(json.dumps(dict(WINDOW=list(P7.WINDOW), BOOT_BLOCK=P7.BOOT_BLOCK, BOOT_DRAWS=P7.BOOT_DRAWS,
                                BOOT_SEED=P7.BOOT_SEED, T975=sorted(P7.T975.items())), sort_keys=True))


def identity(root=ROOT):
    """The forecast's code, this plan's own code and text, and PLAN7's reused functions and constants."""
    p7 = os.path.join(root, "research", "plan7.py")
    out = {"weather.py:_rain_v3": source_hash(os.path.join(root, "weather.py"), "_rain_v3"),
           "file:nws.py": file_hash(os.path.join(root, "nws.py")),
           "file:research/plan9.py": file_hash(os.path.join(root, "research", "plan9.py")),
           "file:research/PLAN9.md": file_hash(os.path.join(root, "research", "PLAN9.md")),
           "research/plan7.py:constants": current_constants_sha()}
    out.update({"research/plan7.py:" + n: source_hash(p7, n) for n in REUSED})
    return out


def identity_deadline():
    """The first forward window opens: no identity may be stored for the first time after this (plan section 8)."""
    return P7.midnight(FORWARD_FIRST) + P7.WINDOW[0]


def ensure_identity(out_dir=None, root=ROOT, now=None):
    """(record, problem). The record is stored once, before the first forward window opens, and copied off the folder;
    a lost local copy is restored from the off-folder one; a missing record is never re-created after the deadline."""
    path = os.path.join(out_dir or RESULTS, IDENTITY)
    got, problem = frozen_record(path)
    if problem:
        return None, problem
    if got is None:
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        if now >= identity_deadline():
            return None, ("no identity record, and the first forward window has opened; the looks wait for the user's"
                          " amendment (plan section 8)")
        got = dict(identity(root), stored=now)
        _write(path, json.dumps(got, indent=1, sort_keys=True))
    err = keep_offsite(path)
    if err:
        print(err)
    return got, None


def amended(out_dir=None):
    """{(name, sha256)} accepted by research/results/plan9_amendments.json (written only by the user's approval; the same
    format as PLAN8's). A damaged list accepts nothing."""
    a = _read_json(os.path.join(out_dir or RESULTS, AMEND))[0]
    a = a if isinstance(a, dict) else {}
    return {(x.get("name"), x.get("sha256")) for x in a.get("amendments", []) if isinstance(x, dict) and x.get("name") and x.get("sha256")}


def identity_problems(out_dir=None, root=ROOT, now=None):
    """Names whose code differs from the stored record or from the PLAN7 pins, not covered by an amendment; [] when all
    holds. A missing or damaged record is a problem too."""
    stored, problem = ensure_identity(out_dir, root, now)
    if problem:
        return [problem]
    ok = amended(out_dir)
    cur = identity(root)
    want = dict(stored)
    want.update({"research/plan7.py:" + n: h for n, h in PINNED_PLAN7.items()})
    want["research/plan7.py:constants"] = PINNED_CONSTANTS
    return sorted(k for k, v in cur.items() if (v is None or v != want.get(k)) and (k, v) not in ok)


# ---------- the forecast (plan section 3) ----------
def chances(slices):
    """v3's 24 hourly chances as fractions, or None unless there are exactly 24 numbers from 0 to 100."""
    try:
        v = json.loads(slices) if isinstance(slices, str) else slices
    except ValueError:
        return None
    if not isinstance(v, list) or len(v) != 24:
        return None
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 100:
            return None
        out.append(float(x) / 100.0)
    return out


def v3_6h(h):
    """1 - (1 - b1)(1 - b2)(1 - b3)(1 - b4), b = the highest chance in hours 0-5, 6-11, 12-17 and 18-23; clipped to
    [0.01, 0.99] like v3."""
    q = 1.0
    for i in range(0, 24, 6):
        q *= 1.0 - max(h[i:i + 6])
    return min(max(1.0 - q, LO), HI)


# ---------- which markets count (plan section 4) ----------
def settle_records(c):
    """({ticker: yes/no} and the newest recorded_ts) from paper.db's market_results; ({}, None) without the table."""
    try:
        got = c.execute("select ticker,result,recorded_ts from market_results").fetchall()
    except sqlite3.OperationalError as ex:
        if "no such table" in str(ex):
            return {}, None
        raise
    return {t: r for t, r, _ in got if r in ("yes", "no")}, max((ts for _, _, ts in got if ts is not None), default=None)


def forward_rows(c, excluded=None, only_days=None):
    """[row] of counted markets (results may still be None). excluded, a dict, gets counts by reason (only for the
    market days in only_days, when given)."""
    ex = excluded if excluded is not None else {}
    settled, _ = settle_records(c)
    out, seen = [], set()
    for t, ts, fc, mid, result, slices in c.execute(
            "select ticker,ts,fc,mid,result,slices from obs where version='v3' and market_type='rain' order by ts,ticker"):
        d = P7.market_day(t or "")
        if d is None or d < FORWARD_FIRST or t in seen:
            continue
        seen.add(t)
        h = chances(slices)
        why = ("after_backstop" if d > BACKSTOP else
               "outside_window" if ts is None or not P7.in_window(ts, d) else
               "no_forecast" if fc is None else
               "no_price" if mid is None else
               "no_hourly_chances" if h is None else None)
        if why:
            if only_days is None or d in only_days:
                ex[why] = ex.get(why, 0) + 1
            continue
        r = result if result in ("yes", "no") else settled.get(t)
        out.append(dict(ticker=t, day=d, ts=float(ts), fc=float(fc), mid=float(mid), q=v3_6h(h), result=r, slices=slices))
    return out


def by_day(rows):
    days = {}
    for r in rows:
        days.setdefault(r["day"], []).append(r)
    return days


def day_state(day_rows, d, today, newest):
    """'ready' (every market resolved, or the 7-day mark passed AND a settle recorded a result after it), 'empty' (ready
    but no market resolved: it takes no slot), or 'waiting' (plan section 6)."""
    resolved = sum(1 for r in day_rows if r["result"] in ("yes", "no"))
    if resolved == len(day_rows):
        return "ready"
    mark = P7.midnight(d + timedelta(days=READY_AFTER))
    if today >= d + timedelta(days=READY_AFTER) and newest is not None and newest >= mark:
        return "ready" if resolved else "empty"
    return "waiting"


def first_days(rows, n, today, newest):
    """The first n counted market days (empty days skipped), if every day up to the n-th is settled one way or the
    other; else None."""
    days = by_day(rows)
    out = []
    for d in sorted(days):
        st = day_state(days[d], d, today, newest)
        if st == "waiting":
            return None
        if st == "ready":
            out.append(d)
            if len(out) == n:
                return out
    return None


def digest(rows):
    """SHA-256 of the counted markets' logged inputs (not their results)."""
    return _sha(json.dumps(sorted([r["ticker"], round(r["ts"], 3), round(r["fc"], 9), round(r["mid"], 9), str(r["slices"])]
                                  for r in rows), separators=(",", ":")))


# ---------- the statistic (plan section 5) ----------
def stats(rows, ref, better, worse):
    field = {"price": "mid", "v3": "fc"}[ref]
    o = [(r["ticker"], r["q"], r[field], r["result"]) for r in rows if r["result"] in ("yes", "no")]
    mg = P7.margin(o)
    d = dict(markets=len(o))
    if mg:
        mu, se, nd = mg
        d.update(mean=mu, se=se, days=nd, t=(mu / se) if se else None, line_t=P7.t_quantile(ALPHA, nd - 1))
        d["gate_line_reading"] = P7.reading(mg, better, worse) + " (the gate's own line, not this plan's verdict)"
        dm = P7.day_means(o)
        order = {r["ticker"].split("-")[1]: r["day"] for r in rows}
        series = [dm[k] for k in sorted(dm, key=lambda k: order[k])]
        d["lag1"] = P7.lag1(series)
        if len(series) >= BOOT_MIN_DAYS:
            ms = P7.boot_means(series)
            d["boot"] = list(P7.boot_interval(ms))
            d["boot_line_high"] = P7.boot_interval(ms, ALPHA, 1 - ALPHA)[1]
        d["passes_line"] = bool(d["t"] is not None and d["t"] <= -d["line_t"] and d.get("boot_line_high", 1) < 0)
    y = lambda r: 1.0 if r == "yes" else 0.0   # noqa: E731
    if o:
        d["brier"] = dict(candidate=sum((f - y(r)) ** 2 for _, f, _, r in o) / len(o),
                          reference=sum((m - y(r)) ** 2 for _, _, m, r in o) / len(o))
    return d


def descriptive(rows):
    """Final look only, never decisive (plan section 6): calibration in the 30-80% range, and A and B on the markets
    logged 00:50-01:30 UTC."""
    res = [r for r in rows if r["result"] in ("yes", "no")]
    y = lambda r: 1.0 if r["result"] == "yes" else 0.0   # noqa: E731
    cal = {}
    for name, key in (("v3", "fc"), ("v3-6h", "q"), ("price", "mid")):
        mid = [r for r in res if 0.3 <= r[key] < 0.8]
        if mid:
            cal[name] = dict(markets=len(mid), said=sum(r[key] for r in mid) / len(mid), rained=sum(y(r) for r in mid) / len(mid))
    early = [r for r in res if 0 <= r["ts"] - P7.midnight(r["day"]) < 5400]
    sub = {}
    for name, ref, _, _ in TESTS:
        field = {"price": "mid", "v3": "fc"}[ref]
        mg = P7.margin([(r["ticker"], r["q"], r[field], r["result"]) for r in early])
        if mg:
            sub[name] = dict(mean=mg[0], se=mg[1], days=mg[2])
    return dict(calibration_30_80=cal, logged_0050_0130=sub)


# ---------- the looks (plan section 6) ----------
def _path(out_dir, n, ext="json"):
    return os.path.join(out_dir or RESULTS, "plan9_look%d.%s" % (n, ext))


def stored(n, out_dir=None):
    """(look record or None, problem or None)."""
    return frozen_record(_path(out_dir, n))


def look(c, n, today=None, out_dir=None, root=ROOT, backstop=False, now=None):
    """The look at n counted days (60 or 110), once. Returns (result or None, message)."""
    today = today or datetime.now(timezone.utc).date()
    have, problem = stored(n, out_dir)
    if problem:
        return None, problem
    if have:
        return have, "already stored"
    bad = identity_problems(out_dir, root, now)
    if bad:
        return None, "PLAN9 looks stopped: %s; needs the user's amendment (plan section 8)" % ", ".join(bad)
    prior = None
    if n == LOOKS[-1]:
        prior, problem = stored(LOOKS[0], out_dir)
        if problem:
            return None, problem
        if prior is None and not backstop:
            return None, "not due"   # the futility look comes first
    rows = forward_rows(c)
    _, newest = settle_records(c)
    days = by_day(rows)
    if backstop:
        use = [d for d in sorted(days) if day_state(days[d], d, today, newest) == "ready"]
    else:
        use = first_days(rows, n, today, newest)
        if use is None:
            return None, "not due"
    keep = [r for d in use for r in days[d]]
    if prior is not None:   # the futility look's markets for its days (plan section 6)
        first = set(prior.get("days_used", []))
        if digest([r for r in keep if str(r["day"]) in first]) != prior.get("digest"):
            return None, ("the futility look's days have other markets or inputs now (another database, or changed rows);"
                          " the final look waits for the user's amendment (plan section 6)")
        counted60 = set(prior.get("counted_tickers", []))
        keep = [r for r in keep if str(r["day"]) not in first or r["ticker"] in counted60]
    ex = {}
    forward_rows(c, ex, set(use))
    scored = [r for r in keep if r["result"] in ("yes", "no")]
    res = dict(plan=PLAN, look=n, backstop=backstop, stored=datetime.now(timezone.utc).isoformat(), today=str(today),
               days=len(use), first_day=str(use[0]) if use else None, last_day=str(use[-1]) if use else None,
               days_used=[str(d) for d in use], excluded=ex, markets=len(scored),
               unresolved_left_out=len(keep) - len(scored), digest=digest(keep),
               counted_tickers=sorted(r["ticker"] for r in scored), tests={})
    b_confirmed = False
    for name, ref, better, worse in TESTS:
        s = stats(scored, ref, better, worse)
        if n == LOOKS[0]:
            below = s.get("mean") is not None and s["mean"] < 0
            res["tests"][name] = dict(markets=s["markets"], days=s.get("days"), mean_below_zero=below,
                                      verdict="continues to the final look" if below else "not confirmed (futility)")
            continue
        stopped = prior is not None and prior["tests"].get(name, {}).get("verdict") == "not confirmed (futility)"
        gated = name == "A" and not b_confirmed
        s["verdict"] = ("not confirmed (stopped at the futility look)" if stopped else
                        "not confirmed (fewer than 110 counted market days by the backstop)" if backstop and len(use) < LOOKS[-1] else
                        "not judged (A is judged only when B is confirmed)" if gated else
                        "confirmed" if s.get("passes_line") else "not confirmed")
        if name == "B":
            b_confirmed = s["verdict"] == "confirmed"
        res["tests"][name] = s
    if n == LOOKS[-1]:
        res["descriptive"] = descriptive(keep)
    _write(_path(out_dir, n, "md"), markdown(res))
    _write(_path(out_dir, n), json.dumps(res, indent=1, sort_keys=True))
    for p in (_path(out_dir, n), _path(out_dir, n, "md")):
        err = keep_offsite(p)
        if err:
            print(err)
    return res, "stored"


def markdown(res):
    out = ["# PLAN9 look at %d market days%s" % (res["look"], " (backstop)" if res.get("backstop") else ""), "",
           "Research only, never part of the gate (research/PLAN9.md). Stored %s; market days %s to %s (%d), %d markets."
           % (res["stored"][:16], res["first_day"], res["last_day"], res["days"], res["markets"]), ""]
    for name, ref, _, _ in TESTS:
        s = res["tests"][name]
        who = "Kalshi's price" if ref == "price" else "v3"
        if res["look"] == LOOKS[0]:
            out.append("- **%s (v3-6h vs %s): %s.** The mean difference is %s zero (only its sign is shown at this look)."
                       % (name, who, s["verdict"], "below" if s["mean_below_zero"] else "not below"))
            continue
        out.append("- **%s (v3-6h vs %s): %s.**" % (name, who, s["verdict"]))
        if s.get("mean") is not None:
            out.append("  Day-mean Brier difference %+.4f +/- %.4f over %d days (t %.2f; this plan's 2.5%% line is %.2f)%s. %s."
                       % (s["mean"], s["se"], s["days"], s["t"] or 0, -s["line_t"],
                          ("; bootstrap 2.5%% upper bound %+.4f" % s["boot_line_high"]) if "boot_line_high" in s else "",
                          s["gate_line_reading"]))
    out += ["", "Left out: %s; unresolved after the 7-day mark: %d."
            % (", ".join("%s %d" % kv for kv in sorted(res["excluded"].items())) or "none", res["unresolved_left_out"])]
    return "\n".join(out) + "\n"


# ---------- status and the settle job ----------
def status(c, today=None, out_dir=None, root=ROOT, now=None):
    today = today or datetime.now(timezone.utc).date()
    ex = {}
    rows = forward_rows(c, ex)
    _, newest = settle_records(c)
    days = by_day(rows)
    nready = sum(1 for d in days if day_state(days[d], d, today, newest) == "ready")
    done = [n for n in LOOKS if stored(n, out_dir)[0]]
    nxt = None if LOOKS[-1] in done else next((n for n in LOOKS if n not in done), None)
    bad = identity_problems(out_dir, root, now)
    msg = ("PLAN9 (research, not in gate): v3-6h vs v3 (B) and vs price (A); %d forward market days logged (%d ready), %d markets; %s%s%s"
           % (len(days), nready, len(rows), ("next look at %d counted market days" % nxt) if nxt else "the final look is stored",
              ("; not counted: " + ", ".join("%s %d" % kv for kv in sorted(ex.items()))) if ex else "",
              ("; CODE CHANGED: " + ", ".join(bad)) if bad else ""))
    print(msg)
    return msg


def auto(db=None, today=None, out_dir=None, root=ROOT, now=None):
    _, problem = ensure_identity(out_dir, root, now)
    if problem:
        print("PLAN9: " + problem)
    c = P7.connect_ro(db or P7.default_db())
    try:
        today = today or datetime.now(timezone.utc).date()
        status(c, today, out_dir, root, now)
        for n in LOOKS:
            if stored(LOOKS[-1], out_dir)[0]:   # the final look (or the backstop's) ends the test
                break
            have, problem = stored(n, out_dir)
            if problem:
                print(problem)
                break
            if have:
                continue
            res, msg = look(c, n, today, out_dir, root, now=now)
            if res is None and msg == "not due" and today >= BACKSTOP_LOOK:   # the backstop: the final look, now
                res, msg = look(c, LOOKS[-1], today, out_dir, root, backstop=True, now=now)
            if res is None:
                if msg != "not due":
                    print(msg)
                break
            print("PLAN9 look at %d days stored: %s" % (res["look"], "; ".join("%s %s" % (k, v["verdict"]) for k, v in res["tests"].items())))
            if res["look"] == LOOKS[-1]:
                break
    finally:
        c.close()


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "status"
    try:
        if cmd == "auto":
            auto()
        elif cmd == "status":
            c = P7.connect_ro(P7.default_db())
            try:
                status(c)
            finally:
                c.close()
        else:
            print(__doc__)
            return 2
    except (Exception, SystemExit) as ex:   # research only: never fail the settle job
        print("PLAN9: %s" % str(ex)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
