"""PLAN10: NOAA's HRRR rain forecast against Kalshi's price, on past markets. Research only; follows research/PLAN10.md
(written 2026-11-09, revised 2026-11-11, frozen; SHA-256 in CHANGELOG.md). Where this code and the plan differ, the plan
wins (plan section 8).

Order of the steps (plan section 8), each refusing to run out of turn:
- freeze            once, on the PC: the identity record (SHA-256 of PLAN10.md, this file, research/backtest.py, and
                    PLAN7's reused functions, pinned as PLAN8 pins them), research/results/plan10_identity.json, copied
                    off the folder. Every later step refuses when the code differs, unless an amendment accepts it
                    (research/results/plan10_amendments.json, PLAN8's format; nothing here writes it).
- request           once, on the PC: from research/data (PLAN.md's holdout file, the climate reports) it writes the two
                    public inputs the runner may use: plan10_request.json (stations, coordinates, day-start hours,
                    holdout days and counts; no prices, no results) and plan10_train_outcomes.json (the climate-report
                    0/1 outcomes of the TRAINING year only). Holdout outcomes and Kalshi prices are never written here.
- train-download    on GitHub's runner: HRRR APCP fields of the training days, reduced to per-station features
                    (research/results/plan10_features/train/<station>.json and train_log.json). Resumable; a time budget
                    stops it cleanly so the workflow can be dispatched again.
- fit               on the runner, once: plan section 4, from the committed public files only; frozen in
                    research/results/plan10_model.json with the SHA-256 of the training rows. Refused when a model
                    exists, when the training download is incomplete, or when any holdout feature exists.
- holdout-download  on the runner, only once the model is committed: the holdout days' features. Prints counts only.
- score             once, on the PC (plan section 9), from research/data (Kalshi's prices and results stay there):
                    plan section 5; stored as research/results/plan10_score.json/.md and copied off the folder; refused
                    a second time.
- status            counts only.

Downloads (plan section 9): the plan names Herbie for the byte-range downloads. Herbie makes its own HTTP requests, so
the project's one allowed User-Agent (tradebot-paper-research/1.0, CLAUDE.md section 3) cannot be guaranteed through it.
This file therefore does the same byte-range download itself: it reads the .idx file of
https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2, finds exactly one line
"APCP:surface:0-FF hour acc fcst", fetches only that message with an HTTP Range request, and decodes it with ecCodes
(the library under cfgrib/xarray) from a temporary file that is deleted at once. Nothing raw is kept.

Clarifications of the plan's text (stated, not tuned; for the plan's confirmation): "within 40 km" is the great-circle
(haversine) distance on HRRR's own sphere (radius 6,371.229 km) from the station to the grid point's centre, <= 40.0 km;
"0.01 inch" is D >= 0.254 mm; A is D at the nearest of those grid points, divided by 25.4.

The day statistic, the bootstrap, the t values and the reading are PLAN7's, imported from research/plan7.py and
pinned by source hash as PLAN8 pins them. The trading rule T reuses research/backtest.py's trades() (PLAN.md's taker and
maker rule and fill model) and its fee; the airport forecast C reuses backtest.py's NBS loader, features and C().

  python research/plan10.py freeze|request|fit|score|status
  python research/plan10.py train-download|holdout-download [--budget-minutes N]
  python research/plan10.py check     one training field downloaded and decoded; prints its keys and grid size only
Python 3.8+. Standard library, except: requests (downloads only) and ecCodes with numpy (decoding, on the runner only),
both imported inside the download functions. Scoring is pure Python."""
import argparse
import ast
import calendar
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import plan7 as P7   # noqa: E402  (pinned functions only; see PINNED_PLAN7)
import backtest as B   # noqa: E402  (research/backtest.py: PLAN.md's loaders, airport forecast and trading rule, read-only use)

PLAN = "research/PLAN10.md"
PLAN_SHA256 = "69208ee2904271f79d185f31c6a24598da67fe29dbcf7666aa09291fa234ff08"   # CHANGELOG.md, r81 (frozen text)
TRAIN = (date(2025, 7, 1), date(2026, 6, 30))       # training outcomes (plan section 2)
HOLDOUT = (date(2026, 7, 15), date(2026, 10, 12))   # PLAN.md's holdout period (plan section 2)
RUNS = (12, 18)                                     # UTC runs of the day before the market day (plan section 2)
RADIUS_KM = 40.0                                    # grid-point centres within 40 km (plan section 3)
EARTH_KM = 6371.229                                 # HRRR's sphere (GRIB shapeOfTheEarth 6)
WET_MM = 0.254                                      # 0.01 inch; D >= WET_MM counts (plan section 3)
MM_PER_INCH = 25.4
F_CLIP = (0.02, 0.98)                               # F clipped before the logit (plan section 4)
H_CLIP = (0.01, 0.99)                               # H clipped (plan section 4)
MAX_SPREAD = 0.06                                   # PLAN.md's quote rule (plan section 2)
EDGE, VETO, BLEND = 0.08, 0.30, 0.5                 # the bot's rule (plan section 5, T)
MAX_LEFT_OUT = 0.10                                 # station exclusions, missing fields: above 10% -> not testable
BOOT_MIN_DAYS = 14                                  # fewer days: no bootstrap, so never "confirmed"
FIVE_P, FIVE_DRAWS = 0.005, 20000                   # the five-test line, reported only (plan section 7)
MAX_STEPS = 50                                      # Newton steps for the fit
MAX_ATTEMPTS = 3                                    # a field that errors on 3 separate runs is counted missing
FLUSH_EVERY = 10                                    # units between saves while downloading
ALIASES = {"KDJT": ("KPBI",)}                       # West Palm Beach re-coded PBI -> DJT in July 2026 (plan section 2)
BUCKET = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
USER_AGENT = "tradebot-paper-research/1.0"          # the only User-Agent allowed (CLAUDE.md section 3)
MAX_FIELD_BYTES = 50 * 1024 * 1024
VERDICT_LEAD = "lead on reused past data: justifies writing PLAN10F only"
VERDICT_NONE = "no gain shown; PLAN10 ends"

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data")
IDENTITY, REQUEST, OUTCOMES = "plan10_identity.json", "plan10_request.json", "plan10_train_outcomes.json"
MODEL, SCORE, AMEND, FEATURES = "plan10_model.json", "plan10_score.json", "plan10_amendments.json", "plan10_features"
STAGES = ("train", "holdout")


def rpath(name):
    return os.path.join(RESULTS, name)


def feat_dir(stage):
    return os.path.join(RESULTS, FEATURES, stage)


def log_path(stage):
    return os.path.join(RESULTS, FEATURES, stage + "_log.json")


# ---------- code identity (plan section 8) ----------
REUSED = ("tcrit", "day_means", "margin", "boot_means", "boot_interval", "_betacf", "t_upper", "t_quantile",
          "market_day", "midnight", "in_window", "clip", "logit", "sigmoid", "mean_se", "lag1", "reading", "connect_ro",
          "default_db", "bot_date")
PINNED_PLAN7 = {   # research/plan7.py as frozen on 2026-11-05: the same pins as research/plan8.py (tests/test_plan10.py)
    'research/plan7.py:_betacf': 'e25864fc49eeb91b5de301c142f8df84c3ca2d93a5f0048097a4e803d484d71c',
    'research/plan7.py:boot_interval': 'f3f54b2cd974f83ef90dfeda1a21930a4a432f51990d4ca744ac890074088a63',
    'research/plan7.py:boot_means': '6f8c0cd3d077359f637cc381d1cbbdcf34fd9bd7460d692ea5284403329e9a2b',
    'research/plan7.py:bot_date': 'f8d57c60aa94df5e1b1b4b43ca6dc280950d7f593bae73b535cd6b624894e765',
    'research/plan7.py:clip': '85d3d12068cdaf82316978a5bce623d68f32dc178a8216872cb9f91999679094',
    'research/plan7.py:connect_ro': '6ed2535197dbb0e4451d96e3bb8999c48f8d4e17580ad4d72cae0189a3dbb0c6',
    'research/plan7.py:constants': '3333dc7661ed57f01694e8bc447a3a67f82ccad06750f910fcf0e18f4db5c539',
    'research/plan7.py:day_means': '7c11b28635ae05d82c16458d24555e2419e0a077f901b6fa098659886fb132d9',
    'research/plan7.py:default_db': '3701e9b48eca69f73b7fee58ea9f2ecbef7b53f7ce0146dccb9501737bc1ea22',
    'research/plan7.py:in_window': '1c702029f88c824777fcfe04ece72fbce760a27ef09e68058457a6299f50a46f',
    'research/plan7.py:lag1': '7b3df8f5afdd9c74805acd53bea1056a05ceb8a6f2926a7a7ce40751a7a9e2fb',
    'research/plan7.py:logit': '004b949e96f1c38790c62a1debd20ea7fb2aa9b4640591b2e3406af2c694b859',
    'research/plan7.py:margin': 'edad2e1f24658d291d02c738fc882dd0f51825ce4316cb57dd0d3ef2ac3f3fbc',
    'research/plan7.py:market_day': '4e7bf1a1416d5e06e5721e9e7a5b76ed130d3f7d4e9d5865437fae1e4c37a98b',
    'research/plan7.py:mean_se': '92db35ba154a25b04a146f04d2ceb8f99ad927a824ca27e7a16f6993d6e82fd3',
    'research/plan7.py:midnight': 'a90c479c325ae36b1e06b60f78881943c51622015f86b0e8bf55f74a266dc1bc',
    'research/plan7.py:reading': 'c571bf5bfd2a83e781e066314da4f9d1cb427ef31ab70fc0f2cc5e50b951a9a7',
    'research/plan7.py:sigmoid': 'bd0d78efc6adac4fbc22925b1a7dc83f14225254c1564925112f291e6b9b2a5f',
    'research/plan7.py:t_quantile': 'ca188669a12be647eed259b72d78bba97a55ed07b86e8aff80df6aedeea4592a',
    'research/plan7.py:t_upper': '882e3706a702e674974e655ee23d8e8688c770713d6247d8c244ceee049b7eed',
    'research/plan7.py:tcrit': 'ae71591f2f962c2ad20bb855b1400f604d590dfe328aae978e982efc44e80cf1',
}
FROZEN_FILES = ("research/PLAN10.md", "research/plan10.py", "research/backtest.py")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def file_hash(path):
    """SHA-256 of a text file with line endings normalized, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            return _sha(f.read().replace("\r\n", "\n"))
    except (OSError, ValueError):
        return None


def source_hash(path, name):
    """SHA-256 of a top-level function's source text (line endings normalized), or None (research/plan8.py's rule)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("\r\n", "\n")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(text, node)
            return _sha(seg) if seg else None
    return None


def plan7_identity(root=ROOT):
    p = os.path.join(root, "research", "plan7.py")
    out = {"research/plan7.py:%s" % n: source_hash(p, n) for n in REUSED}
    out["research/plan7.py:constants"] = _sha(json.dumps(dict(
        T975=sorted(P7.T975.items()), EPS=P7.EPS, WINDOW=list(P7.WINDOW), BOOT_BLOCK=P7.BOOT_BLOCK,
        BOOT_DRAWS=P7.BOOT_DRAWS, BOOT_SEED=P7.BOOT_SEED, BOT_TZ=str(P7.BOT_TZ)), sort_keys=True))
    return out


def identity(root=ROOT):
    out = {"file:%s" % f: file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES}
    out.update(plan7_identity(root))
    return out


def _read_json(path):
    """(object, True) for a readable JSON file; (None, False) for a damaged one; (None, True) when it does not exist."""
    if not os.path.exists(path):
        return None, True
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError, RecursionError):
        return None, False


def save_json(path, obj, indent=None):
    """Crash-safe write (temporary file, then replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, sort_keys=True)
    os.replace(tmp, path)


def offsite():
    """The off-folder backup location backup.py uses (TRADEBOT_OFFSITE_BACKUPS, else Documents\\tradebot_backups)."""
    return os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups")


def offsite_path(path):
    return os.path.join(offsite(), "plan10", "results", os.path.basename(path))


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
        return "PLAN10: off-folder copy of %s failed (%s)" % (os.path.basename(path), ex)


def frozen_record(path):
    """(object, problem) for a once-written record: the local file, else its off-folder copy (restored here). A damaged
    file is a problem and is never overwritten; (None, None) when neither exists."""
    got, ok = _read_json(path)
    if not ok:
        return None, "%s is damaged; restore it from %s" % (os.path.basename(path), offsite_path(path))
    if got is not None:
        return got, None
    saved = offsite_path(path)
    got, ok = _read_json(saved)
    if not ok:
        return None, "the off-folder copy %s is damaged" % saved
    if got is None:
        return None, None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(saved, path)
    except OSError:
        pass
    return got, None


def amended():
    """{(name, sha256)} accepted by research/results/plan10_amendments.json (PLAN8's format, written only with the
    user's approval; nothing in this file writes it). A damaged list accepts nothing."""
    a = _read_json(rpath(AMEND))[0]
    a = a if isinstance(a, dict) else {}
    return {(x.get("name"), x.get("sha256")) for x in a.get("amendments", [])
            if isinstance(x, dict) and x.get("name") and x.get("sha256")}


def identity_problems(root=ROOT):
    """[] when the code is the code the plan was frozen with; otherwise what differs (or why it cannot be checked)."""
    rec, problem = frozen_record(rpath(IDENTITY))
    if problem:
        return [problem]
    if not isinstance(rec, dict) or not rec:
        return ["no identity record: run `plan10.py freeze` first (plan section 8)"]
    ok = amended()
    want = {k: v for k, v in rec.items() if k.startswith("file:")}
    want.update(PINNED_PLAN7)
    return sorted(k for k, v in identity(root).items() if (v is None or v != want.get(k)) and (k, v) not in ok)


def freeze(root=ROOT, now=None):
    """Store the identity record once, before the first download (plan section 8). (record or None, message)."""
    path = rpath(IDENTITY)
    rec, problem = frozen_record(path)
    if problem:
        return None, problem
    if rec is not None:
        return None, "already frozen (%s); the record is stored once and never re-created" % path
    if any(os.path.exists(log_path(s)) for s in STAGES):
        return None, "a download has already started; the identity record must come before it (plan section 8)"
    cur = identity(root)
    ok = amended()
    bad = [k for k, v in cur.items() if k.startswith("research/plan7.py:") and v != PINNED_PLAN7.get(k) and (k, v) not in ok]
    if cur["file:research/PLAN10.md"] != PLAN_SHA256 and ("file:research/PLAN10.md", cur["file:research/PLAN10.md"]) not in ok:
        bad.append("file:research/PLAN10.md (not the frozen text %s)" % PLAN_SHA256[:12])
    if any(v is None for v in cur.values()):
        bad += [k + " (unreadable)" for k, v in cur.items() if v is None]
    if bad:
        return None, "not frozen: %s" % ", ".join(sorted(set(bad)))
    now = time.time() if now is None else now
    rec = dict(cur, stored=now, stored_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"))
    save_json(path, rec, indent=1)
    err = keep_offsite(path)
    if err:
        print(err)
    return rec, "frozen: " + ", ".join("%s %s" % (k, v[:12]) for k, v in sorted(cur.items()) if k.startswith("file:"))


def require_identity(root=ROOT):
    bad = identity_problems(root)
    if bad:
        raise Refused("code differs from the frozen record or cannot be checked (%s); the step waits for an amendment"
                      " (plan section 8)" % ", ".join(bad))


class Refused(Exception):
    """A step that may not run now; nothing was written."""


# ---------- 1. the public inputs: request and training outcomes (plan section 2; on the PC) ----------
def utc_midnight(d):
    return calendar.timegm((d.year, d.month, d.day, 0, 0, 0))


def pday(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def quote_ok(bid, ask):
    return bid is not None and ask is not None and 0 <= bid < ask <= 1 and ask - bid <= MAX_SPREAD + 1e-9


def rain_table():
    """{"Kxxx": (CLI code, lat, lon)} from v3's rain table (weather.RAIN), matched by CLI code (plan section 2)."""
    import weather
    return {"K" + code[3:]: (code, lat, lon) for code, lat, lon in weather.RAIN.values()}


def load_markets(jsonl):
    """PLAN.md's holdout file, each ticker once (its first line), and the number of duplicate lines."""
    out, dup, seen = [], 0, set()
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            m = json.loads(line)
            if m["ticker"] in seen:
                dup += 1
                continue
            seen.add(m["ticker"])
            out.append(m)
    return out, dup


def load_cli(data_dir=None):
    """{(station, date): rained} from research/data/cli, by research/backtest.py's load_cli rule: precipitation above 0
    is yes; trace (T) and missing (M) count as 0, as in Kalshi's rules (tests/test_plan10.py checks they agree)."""
    import glob
    out = {}
    for p in sorted(glob.glob(os.path.join(data_dir or DATA, "cli", "*.json"))):
        st = os.path.basename(p).split("_")[0]
        with open(p, encoding="utf-8") as f:
            for r in json.load(f):
                if r.get("valid"):
                    out[(st, B.d(r["valid"]))] = (B.num(r.get("precip")) or 0) > 0
    return out


def cli_outcome(cli, st, d):
    """(rained or None, code used): the table's code first, else an alias with a report for that date (plan section 2)."""
    if (st, d) in cli:
        return cli[(st, d)], st
    for a in ALIASES.get(st, ()):
        if (a, d) in cli:
            return cli[(a, d)], a
    return None, None


def home_station(st, table):
    """A market's station under its current code: KPBI (West Palm Beach before its July 2026 re-code) counts as
    KDJT when KPBI itself is not in the rain table (the user's clarification of 2026-11-13)."""
    if st in table:
        return st
    for cur, olds in ALIASES.items():
        if st in olds:
            return cur
    return st


def build_request(jsonl=None, cli=None, table=None):
    """(request, train_outcomes, quote-passing markets) from research/data (plan section 2). The request holds no price
    and no result; the outcomes are the training year's climate reports only."""
    markets, dup = load_markets(jsonl or os.path.join(DATA, "kalshi_rain.jsonl"))
    cli = load_cli() if cli is None else cli
    table = rain_table() if table is None else table
    counts = dict(unique_markets=len(markets), duplicate_lines=dup, outside_period=0, other_settlement=0, quote=0)
    passed = []
    for m in markets:
        d = pday(m["day"])
        if not HOLDOUT[0] <= d <= HOLDOUT[1]:
            counts["outside_period"] += 1
        elif m.get("result") not in ("yes", "no"):
            counts["other_settlement"] += 1
        elif not quote_ok(m.get("scan_bid"), m.get("scan_ask")):
            counts["quote"] += 1
        else:
            passed.append(m)
    counts["passed_quote"] = len(passed)
    by, holdout_alias = {}, 0
    for m in passed:
        st = home_station(m["station"], table)
        holdout_alias += st != m["station"]
        by.setdefault(st, []).append(m)
    counts["holdout_alias_markets"] = holdout_alias
    stations, excluded, days = {}, {}, {}
    for st, ms in sorted(by.items()):
        hours = sorted({(m["start_ts"] - utc_midnight(pday(m["day"]))) / 3600.0 for m in ms if m.get("start_ts") is not None})
        if st not in table:
            excluded[st] = dict(markets=len(ms), reason="not in v3's rain table")
        elif len(hours) != 1 or any(m.get("start_ts") is None for m in ms) or hours[0] != int(hours[0]) or not 0 <= hours[0] <= 23:
            excluded[st] = dict(markets=len(ms), reason="no single day-start hour (%s)" % hours)
        else:
            code, lat, lon = table[st]
            stations[st] = dict(cli=code, lat=lat, lon=lon, start_hour=int(hours[0]), markets=len(ms))
            days[st] = sorted({m["day"][:10] for m in ms})
    left = sum(x["markets"] for x in excluded.values())
    outcomes, alias_used, alias_conflicts = {}, 0, 0
    for st in sorted(stations):
        o = {}
        d = TRAIN[0]
        while d <= TRAIN[1]:
            y, code = cli_outcome(cli, st, d)
            if y is not None:
                o[d.isoformat()] = 1 if y else 0
                if code != st:
                    alias_used += 1
                elif any((a, d) in cli and cli[(a, d)] != y for a in ALIASES.get(st, ())):
                    alias_conflicts += 1
            d += timedelta(days=1)
        outcomes[st] = o
    counts.update(stations=len(stations), stations_excluded=len(excluded), excluded_markets=left,
                  excluded_share=(left / float(len(passed))) if passed else None,
                  n0=sum(s["markets"] for s in stations.values()),
                  train_station_days=sum(len(v) for v in outcomes.values()),
                  train_alias_days=alias_used, train_alias_conflicts=alias_conflicts)
    req = dict(plan=PLAN, train=[str(TRAIN[0]), str(TRAIN[1])], holdout=[str(HOLDOUT[0]), str(HOLDOUT[1])],
               runs=list(RUNS), stations=stations, holdout_days=days, excluded_stations=excluded, counts=counts)
    req["sha256"] = _sha(canon(req))
    outs = dict(plan=PLAN, train=[str(TRAIN[0]), str(TRAIN[1])], outcomes=outcomes)
    outs["sha256"] = _sha(canon(outs))
    return req, outs, passed


def make_request(root=ROOT):
    """The `request` command: write the two public inputs once."""
    require_identity(root)
    for name in (REQUEST, OUTCOMES):
        if os.path.exists(rpath(name)):
            raise Refused("%s already exists; the request is written once" % name)
    if any(os.path.exists(log_path(s)) for s in STAGES):
        raise Refused("a download has already started; the request cannot change now")
    req, outs, _ = build_request()
    save_json(rpath(REQUEST), req, indent=1)
    save_json(rpath(OUTCOMES), outs)
    for n in (REQUEST, OUTCOMES):
        err = keep_offsite(rpath(n))
        if err:
            print(err)
    c = req["counts"]
    msg = ("request written: %d stations, %d holdout markets in N0 (%d passed the quote rule, %d left out with %d excluded"
           " stations), %d training station-days" % (c["stations"], c["n0"], c["passed_quote"], c["excluded_markets"],
                                                    c["stations_excluded"], c["train_station_days"]))
    if c["excluded_share"] is not None and c["excluded_share"] > MAX_LEFT_OUT:
        msg += ("; WARNING: excluded stations hold %.1f%% of the markets, above 10%%, so the verdict will read"
                " 'not testable' (plan section 2)" % (100 * c["excluded_share"]))
    return msg


def load_public():
    """(request, train outcomes), both checked against their stored SHA-256."""
    out = []
    for name in (REQUEST, OUTCOMES):
        obj, ok = _read_json(rpath(name))
        if not ok or not isinstance(obj, dict):
            raise Refused("%s is missing or damaged; run `plan10.py request` on the PC and commit it" % name)
        body = {k: v for k, v in obj.items() if k != "sha256"}
        if obj.get("sha256") != _sha(canon(body)):
            raise Refused("%s does not match its own SHA-256 (edited?)" % name)
        out.append(obj)
    return out[0], out[1]


# ---------- 2. HRRR fields: own byte-range fetcher (plan sections 2, 3, 9) ----------
class Missing(Exception):
    """The field is not there, or not exactly the one the plan names: counted missing, never retried."""


class Transient(Exception):
    """A network or server error after retries: the unit is tried again on a later run (MAX_ATTEMPTS in all)."""


def grib_url(run_day, cycle, fh):
    return "%s/hrrr.%s/conus/hrrr.t%02dz.wrfsfcf%02d.grib2" % (BUCKET, run_day.strftime("%Y%m%d"), cycle, fh)


def apcp_line(fh):
    return "APCP:surface:0-%d hour acc fcst" % fh


def parse_idx(text, run_day, cycle, fh):
    """(first byte, last byte or None) of the one message "APCP:surface:0-fh hour acc fcst" of this run. Exactly one
    such line, with this run's date, is required; anything else is Missing."""
    rows = []
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 6 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        rows.append(parts)
    want = apcp_line(fh)
    hits = [i for i, p in enumerate(rows) if ":".join(p[3:6]) == want]
    if len(hits) != 1:
        raise Missing("%d lines '%s' in the index (exactly 1 needed)" % (len(hits), want))
    p = rows[hits[0]]
    if p[2] != "d=%s%02d" % (run_day.strftime("%Y%m%d"), cycle):
        raise Missing("the index line's run is %s, not %s %02dZ" % (p[2], run_day, cycle))
    start = int(p[1])
    later = sorted(int(q[1]) for q in rows if int(q[1]) > start)
    return start, (later[0] - 1 if later else None)


class Fetcher(object):
    """HTTP GETs with the project's User-Agent only, retries with back-off, and 404 read as 'not there'."""

    def __init__(self, session=None, tries=5, sleep=time.sleep):
        if session is None:
            import requests   # downloads only
            session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        self.s, self.tries, self.sleep = session, tries, sleep

    def get(self, url, rng=None):
        headers = {"User-Agent": USER_AGENT}
        if rng is not None:
            headers["Range"] = "bytes=%d-%s" % (rng[0], "" if rng[1] is None else rng[1])
        err = None
        for k in range(self.tries):
            try:
                r = self.s.get(url, headers=headers, timeout=120, stream=True)
            except Exception as ex:   # connection errors of any HTTP library
                r, err = None, repr(ex)
            if r is not None:
                if r.status_code == 404:
                    r.close()
                    return None
                ok = (r.status_code == 206) if rng is not None else (r.status_code == 200)
                if ok:
                    return r
                err = "HTTP %d" % r.status_code
                r.close()
                if r.status_code == 200 and rng is not None:   # the server ignored the range: never pull the whole file
                    raise Transient("the server ignored the byte range for %s" % url)
            if k < self.tries - 1:
                self.sleep(min(120, 5 * 2 ** k))
        raise Transient("%s after %d tries: %s" % (err, self.tries, url))


class HRRR(object):
    """field(run_day, cycle, fh) -> dict(values, missing_value, sig, grid, latlon) for the APCP 0-fh message; the raw
    bytes go to a temporary file that is deleted at once."""

    def __init__(self, fetcher=None, tmpdir=None, decoder=None):
        self.f = fetcher or Fetcher()
        self.tmpdir = tmpdir
        self.decode = decoder or decode_grib

    def field(self, run_day, cycle, fh):
        url = grib_url(run_day, cycle, fh)
        r = self.f.get(url + ".idx")
        if r is None:
            raise Missing("no index file")
        try:
            try:
                text = r.content.decode("utf-8", "replace")
            except OSError as ex:   # requests' ChunkedEncodingError, ConnectionError and ReadTimeout are OSErrors
                raise Transient("reading the index failed: %r" % (ex,))
        finally:
            r.close()
        start, end = parse_idx(text, run_day, cycle, fh)
        r = self.f.get(url, (start, end))
        if r is None:
            raise Missing("no GRIB file")
        fd, tmp = tempfile.mkstemp(suffix=".grib2", dir=self.tmpdir)
        try:
            try:
                size = 0
                with os.fdopen(fd, "wb") as out:
                    for chunk in _chunks(r):
                        size += len(chunk)
                        if size > MAX_FIELD_BYTES:
                            raise Transient("the message is larger than %d bytes" % MAX_FIELD_BYTES)
                        out.write(chunk)
            finally:
                r.close()
            if end is not None and size != end - start + 1:
                raise Transient("got %d bytes, expected %d" % (size, end - start + 1))
            return self.decode(tmp, run_day, cycle, fh)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _chunks(r):
    """The response body in pieces; a network error while reading it is Transient (writing the file is not wrapped)."""
    it = iter(r.iter_content(1 << 20))
    while True:
        try:
            chunk = next(it)
        except StopIteration:
            return
        except OSError as ex:   # requests' ChunkedEncodingError, ConnectionError and ReadTimeout are OSErrors
            raise Transient("reading the GRIB message failed: %r" % (ex,))
        yield chunk


SIG_KEYS = ("centre", "subCentre", "generatingProcessIdentifier", "backgroundProcess", "typeOfGeneratingProcess",
            "productionStatusOfProcessedData", "tablesVersion", "localTablesVersion", "gridDefinitionTemplateNumber",
            "shapeOfTheEarth", "Ni", "Nj", "packingType")
GRID_KEYS = ("gridDefinitionTemplateNumber", "shapeOfTheEarth", "Ni", "Nj", "latitudeOfFirstGridPointInDegrees",
             "longitudeOfFirstGridPointInDegrees", "LaDInDegrees", "LoVInDegrees", "Latin1InDegrees", "Latin2InDegrees",
             "DxInMetres", "DyInMetres")


_LATLON = {}   # grid key -> (latitudes, longitudes) of the grid points, read once per grid


def decode_grib(path, run_day, cycle, fh):
    """Decode one APCP message with ecCodes (runner only). Checks that it is exactly one message, of this run, the
    accumulation 0-fh at the surface (discipline 0, category 1, number 8), and records its signature. An ecCodes
    error (a damaged download) is Transient: tried again on later runs, then counted missing (MAX_ATTEMPTS)."""
    import eccodes   # ecCodes (Apache 2.0), the library under cfgrib/xarray; runner only
    errors = tuple(c for c in (getattr(eccodes, "CodesInternalError", None), getattr(eccodes, "GribInternalError", None))
                   if isinstance(c, type)) or (Exception,)
    try:
        return _decode(eccodes, path, run_day, cycle, fh)
    except (Missing, Transient):
        raise
    except errors as ex:
        raise Transient("ecCodes could not decode the message: %r" % (ex,))


def _decode(eccodes, path, run_day, cycle, fh):
    with open(path, "rb") as f:
        gid = eccodes.codes_grib_new_from_file(f)
        if gid is None:
            raise Missing("no GRIB message in the downloaded range")
        extra = eccodes.codes_grib_new_from_file(f)
        if extra is not None:
            eccodes.codes_release(extra)
            eccodes.codes_release(gid)
            raise Missing("more than one GRIB message in the downloaded range")
    try:
        def get(k, ktype=None):
            try:
                return eccodes.codes_get(gid, k, ktype) if ktype else eccodes.codes_get(gid, k)
            except Exception:
                return None
        want = dict(discipline=0, parameterCategory=1, parameterNumber=8, typeOfFirstFixedSurface=1,
                    dataDate=int(run_day.strftime("%Y%m%d")), dataTime=cycle * 100)
        # read as numbers: ecCodes gives some coded keys as text by default (typeOfFirstFixedSurface "sfc" for 1),
        # found by the one-field check of 2026-11-13 before any bulk download
        got = {k: get(k, int) for k in want}
        if got != want or str(get("stepRange")) != "0-%d" % fh:
            raise Missing("not the APCP 0-%d message: %s stepRange=%s" % (fh, got, get("stepRange")))
        sig = {k: get(k) for k in SIG_KEYS}
        grid = canon({k: get(k) for k in GRID_KEYS})
        values = eccodes.codes_get_values(gid)
        mv = get("missingValue") if get("bitmapPresent") else None
        if grid not in _LATLON:   # once per grid: read now, the handle is released below
            _LATLON[grid] = (eccodes.codes_get_array(gid, "latitudes").tolist(),
                             eccodes.codes_get_array(gid, "longitudes").tolist())
        return dict(values=values, missing_value=mv, sig=sig, grid=grid, latlon=lambda: _LATLON[grid])
    finally:
        eccodes.codes_release(gid)


# ---------- 3. features (plan section 3) ----------
def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def geometry(lats, lons, stations):
    """{station: dict(idx=[grid indices within RADIUS_KM], near=nearest index, near_km, n)} on one grid. Longitudes in
    0..360 or -180..180 both work (haversine uses the difference)."""
    band = RADIUS_KM / (EARTH_KM * math.pi / 180.0) + 0.05   # degrees of latitude, a cheap pre-filter
    out = {st: dict(idx=[], near=None, near_km=None) for st in stations}
    near = {st: (None, float("inf")) for st in stations}
    sts = [(st, s["lat"], s["lon"]) for st, s in sorted(stations.items())]
    for i in range(len(lats)):
        la = lats[i]
        for st, slat, slon in sts:
            if abs(la - slat) > band:
                continue
            km = haversine_km(slat, slon, la, lons[i])
            if km <= RADIUS_KM:
                out[st]["idx"].append(i)
                if km < near[st][1]:
                    near[st] = (i, km)
    for st in out:
        out[st]["near"], out[st]["near_km"] = near[st][0], (near[st][1] if near[st][0] is not None else None)
        out[st]["n"] = len(out[st]["idx"])
    return out


def station_features(start, end, g, missing_value=None):
    """(F_r, A_r in inches) from the APCP fields at the day's start and end hours, or (None, reason). D = end - start,
    negative values counted as 0."""
    if not g or not g["n"]:
        return None, "no grid point within %.0f km" % RADIUS_KM
    ds = []
    for i in g["idx"]:
        a, b = float(start[i]), float(end[i])
        if not (math.isfinite(a) and math.isfinite(b)) or (missing_value is not None and (a == missing_value or b == missing_value)):
            return None, "missing values within %.0f km" % RADIUS_KM
        ds.append(max(0.0, b - a))
    wet = sum(1 for x in ds if x >= WET_MM)
    dn = max(0.0, float(end[g["near"]]) - float(start[g["near"]]))
    return (wet / float(len(ds)), dn / MM_PER_INCH), None


def fh_pair(cycle, hour):
    """Forecast hours of the market day's start and end for a run of the day before at `cycle` UTC (plan section 3)."""
    s = (24 - cycle) + hour
    return s, s + 24


def unit_key(run_day, cycle):
    return "%s %02dZ" % (run_day.isoformat(), cycle)


def stage_plan(stage, req, outs):
    """({station: set of days}, [(run_day, cycle)], {unit key: {fh: [stations]}}) for a stage."""
    sdays = {}
    for st, s in req["stations"].items():
        if stage == "train":
            sdays[st] = set(outs["outcomes"].get(st, {}))
        else:
            sdays[st] = set(req["holdout_days"].get(st, []))
    need = {}
    for st, ds in sdays.items():
        h = req["stations"][st]["start_hour"]
        for d in ds:
            rd = pday(d) - timedelta(days=1)
            for c in RUNS:
                for fh in fh_pair(c, h):
                    need.setdefault((rd, c), {}).setdefault(fh, []).append(st)
    units = sorted(need)
    return sdays, units, {unit_key(*u): need[u] for u in units}


def _sig_id(sig):
    return _sha(canon(sig))[:12]


def load_stage(stage, req):
    lg, ok = _read_json(log_path(stage))
    if not ok:
        raise Refused("%s is damaged" % log_path(stage))
    if lg is None:
        lg = dict(stage=stage, plan=PLAN, request_sha256=req["sha256"], done={}, missing={}, attempts={}, fields={},
                  signatures={}, geometry={})
    if lg.get("request_sha256") != req["sha256"]:
        raise Refused("the %s log was made for another request" % stage)
    files = {}
    for st in req["stations"]:
        p = os.path.join(feat_dir(stage), st + ".json")
        f, ok = _read_json(p)
        if not ok:
            raise Refused("%s is damaged" % p)
        files[st] = f or dict(station=st, stage=stage, days={})
    return lg, files


def save_stage(stage, lg, files):
    for st, f in sorted(files.items()):
        save_json(os.path.join(feat_dir(stage), st + ".json"), f)
    save_json(log_path(stage), lg, indent=None)   # last: a crash before this only re-does units


def complete(stage, req, outs):
    lg, ok = _read_json(log_path(stage))
    if not ok or not isinstance(lg, dict):
        return False, 0, 0
    _, units, _ = stage_plan(stage, req, outs)
    done = sum(1 for u in units if unit_key(*u) in lg.get("done", {}))
    return done == len(units), done, len(units)


_TEST_SKIP_GIT_CHECK = False   # tests/test_plan10.py only (fake worlds are not git working copies); no command sets it


def git_committed(path):
    """True when `path` is tracked by git and the working copy equals HEAD (the holdout steps' precondition)."""
    try:
        rel = os.path.relpath(path, ROOT)
        a = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
        b = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT, capture_output=True)
        return a.returncode == 0 and b.returncode == 0
    except OSError:
        return False


def download(stage, source=None, budget_minutes=None, root=ROOT, clock=time.time, out=print):
    """train-download / holdout-download. Returns a counts-only message. Holdout values are never printed."""
    if stage not in STAGES:
        raise Refused("unknown stage %s" % stage)
    require_identity(root)
    req, outs = load_public()
    model_raw, ok = _read_json(rpath(MODEL))
    if not ok:
        raise Refused("%s is damaged" % MODEL)
    if stage == "train":
        if model_raw is not None:
            raise Refused("the model is fitted; the training features are fixed (plan section 8)")
    else:
        if not isinstance(model_raw, dict) or not model_raw:
            raise Refused("no fitted model: the holdout download waits for the committed model (plan section 8)")
        if "failed" in model_raw:
            raise Refused("the fit failed, so the verdict is 'not testable'; nothing to download (plan section 4)")
        if model_raw.get("request_sha256") != req["sha256"]:
            raise Refused("the model was fitted for another request")
        if not _TEST_SKIP_GIT_CHECK and not git_committed(rpath(MODEL)):
            raise Refused("%s is not committed (or differs from HEAD): commit it before any holdout download" % MODEL)
        full, _, _ = complete("train", req, outs)
        if not full:
            raise Refused("the training download is not complete")
    lg, files = load_stage(stage, req)
    sdays, units, need = stage_plan(stage, req, outs)
    if source is None:
        out("PLAN10 %s: ecCodes API %s" % (stage, eccodes_version()))
    src = source or HRRR()
    geo = {}   # grid key -> geometry (in memory)
    t0 = clock()
    todo = [u for u in units if unit_key(*u) not in lg["done"]]
    n_done = n_err = 0
    stopped = False
    for k, (rd, cyc) in enumerate(todo):
        if budget_minutes is not None and clock() - t0 > budget_minutes * 60:
            stopped = True
            break
        key = unit_key(rd, cyc)
        fields, why = {}, {}
        last_try = lg["attempts"].get(key, 0) + 1 >= MAX_ATTEMPTS
        aborted = False
        for fh in sorted(need[key]):
            try:
                fl = src.field(rd, cyc, fh)
            except Missing as ex:
                why[fh] = "missing: %s" % ex
                continue
            except Transient as ex:
                if not last_try:   # the whole unit is tried again on a later run
                    aborted = True
                    break
                why[fh] = "error after %d attempts: %s" % (MAX_ATTEMPTS, ex)   # only this field; the others are kept
                continue
            if fl["grid"] not in geo:
                lats, lons = fl["latlon"]()
                geo[fl["grid"]] = geometry(lats, lons, req["stations"])
                lg["geometry"][_sha(fl["grid"])[:12]] = {st: [g["n"], g["near_km"]] for st, g in geo[fl["grid"]].items()}
            fields[fh] = fl
            sid = _sig_id(fl["sig"])
            lg["signatures"][sid] = fl["sig"]
            lg["fields"].setdefault(key, {})[str(fh)] = sid
        if aborted or (last_try and any(w.startswith("error") for w in why.values())):
            lg["attempts"][key] = lg["attempts"].get(key, 0) + 1
            n_err += 1
            if aborted:
                continue
        if why:
            lg["missing"][key] = {str(fh): w for fh, w in sorted(why.items())}
        day = (rd + timedelta(days=1)).isoformat()
        for st in sorted({s for v in need[key].values() for s in v}):
            if day not in sdays[st]:
                continue
            fs, fe = fh_pair(cyc, req["stations"][st]["start_hour"])
            val = None
            if fs in fields and fe in fields:
                g = geo[fields[fe]["grid"]] if fields[fs]["grid"] == fields[fe]["grid"] else None
                if g is not None:
                    got, _ = station_features(fields[fs]["values"], fields[fe]["values"], g[st],
                                              fields[fe].get("missing_value"))
                    val = list(got) if got else None
            files[st]["days"].setdefault(day, {})[str(cyc)] = val
        lg["done"][key] = True
        n_done += 1
        if n_done % FLUSH_EVERY == 0:
            save_stage(stage, lg, files)
            out("PLAN10 %s: %d of %d units done" % (stage, len(lg["done"]), len(units)))
    save_stage(stage, lg, files)
    full = all(unit_key(*u) in lg["done"] for u in units)
    have = sum(1 for st in files for d, v in files[st]["days"].items()
               if all(v.get(str(c)) is not None for c in RUNS))
    nmiss = sum(len(v) for v in lg["missing"].values())
    return ("PLAN10 %s: %d of %d units done%s; %d fields missing; %d station-days with all four fields; %d units with"
            " network errors this run" % (stage, len(lg["done"]), len(units), "" if full else (
                " (stopped at the time budget; dispatch again)" if stopped else " (incomplete)"), nmiss, have, n_err))


def eccodes_version():
    import eccodes   # runner only
    return eccodes.codes_get_api_version()


def check(source=None, root=ROOT, out=print):
    """One training field downloaded and decoded before the bulk download: prints the ecCodes version, the field's
    signature keys, its grid keys and the number of grid points, never a value. Writes nothing."""
    require_identity(root)
    req, outs = load_public()
    _, units, need = stage_plan("train", req, outs)
    if not units:
        raise Refused("no training units")
    rd, cyc = units[0]
    fh = sorted(need[unit_key(rd, cyc)])[0]
    if source is None:
        out("PLAN10 check: ecCodes API %s" % eccodes_version())
    try:
        fl = (source or HRRR()).field(rd, cyc, fh)
    except (Missing, Transient) as ex:
        return "PLAN10 check: %s %02dZ f%02d not usable: %s" % (rd, cyc, fh, ex)
    lats, _ = fl["latlon"]()
    return "PLAN10 check: %s %02dZ f%02d decoded; signature %s; grid %s; %d grid points; %d values; missing value %s" % (
        rd, cyc, fh, canon(fl["sig"]), fl["grid"], len(lats), len(fl["values"]),
        "none" if fl.get("missing_value") is None else "set")


# ---------- 4. the fit (plan section 4; on the runner, from committed public files only) ----------
def x_row(F, A):
    f = min(max(F, F_CLIP[0]), F_CLIP[1])
    return [1.0, P7.logit(f), math.log1p(100.0 * A)]


def H_of(model, F, A):
    z = sum(w * x for w, x in zip((model["a"], model["b"], model["c"]), x_row(F, A)))
    return min(max(P7.sigmoid(z), H_CLIP[0]), H_CLIP[1])


def combine(v):
    """(F, A) = means of the two runs, or None when any of the four fields is missing (plan section 3)."""
    if not v or any(v.get(str(c)) is None for c in RUNS):
        return None
    f = [v[str(c)][0] for c in RUNS]
    a = [v[str(c)][1] for c in RUNS]
    return sum(f) / len(f), sum(a) / len(a)


def solve(A, b):
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if not abs(M[piv][col]) > 1e-300:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(n):
            if r != col:
                k = M[r][col] / M[col][col]
                for j in range(col, n + 1):
                    M[r][j] -= k * M[col][j]
    return [M[i][n] / M[i][i] for i in range(n)]


def fit_logit(X, Y, start=(0.0, 1.0, 0.0), steps=MAX_STEPS, tol=1e-10):
    """Maximum likelihood by Newton's method: (weights, steps), or None when it does not converge."""
    w = list(start)
    k = len(w)
    for it in range(steps):
        g = [0.0] * k
        Hm = [[0.0] * k for _ in range(k)]
        for x, y in zip(X, Y):
            p = P7.sigmoid(sum(a * b for a, b in zip(w, x)))
            r, v = y - p, p * (1.0 - p)
            for i in range(k):
                g[i] += r * x[i]
                for j in range(k):
                    Hm[i][j] += v * x[i] * x[j]
        step = solve(Hm, g)
        if step is None:
            return None
        w = [a + s for a, s in zip(w, step)]
        if not all(math.isfinite(a) for a in w):
            return None
        if max(abs(s) for s in step) < tol:
            return w, it + 1
    return None


def train_rows(req, outs):
    """([(station, day, F, A, y)], counts) of the training station-days with all four fields."""
    rows, miss = [], 0
    for st in sorted(req["stations"]):
        f, ok = _read_json(os.path.join(feat_dir("train"), st + ".json"))
        if not ok:
            raise Refused("training features of %s are damaged" % st)
        days = (f or {}).get("days", {})
        for d, y in sorted(outs["outcomes"].get(st, {}).items()):
            fa = combine(days.get(d))
            if fa is None:
                miss += 1
                continue
            rows.append((st, d, fa[0], fa[1], float(y)))
    return rows, miss


def rows_sha(rows):
    return _sha(json.dumps([[st, d, F, A, y] for st, d, F, A, y in rows], separators=(",", ":")))


def edge_counts(vals):
    return dict(n=len(vals), F0=sum(1 for v in vals if v == 0.0), F1=sum(1 for v in vals if v == 1.0))


def fit(root=ROOT, now=None):
    """Fit and freeze H once (plan section 4). Returns (model or None, message)."""
    require_identity(root)
    for p in (rpath(MODEL), offsite_path(rpath(MODEL))):
        if os.path.exists(p):
            raise Refused("a model file exists (%s); the model is fitted once and never refitted" % p)
    if os.path.exists(log_path("holdout")) or (os.path.isdir(feat_dir("holdout")) and os.listdir(feat_dir("holdout"))):
        raise Refused("holdout features exist; the fit must come before any holdout value (plan section 8)")
    req, outs = load_public()
    full, done, total = complete("train", req, outs)
    if not full:
        raise Refused("the training download is not complete (%d of %d units)" % (done, total))
    rows, miss = train_rows(req, outs)
    if not rows:
        raise Refused("no training rows")
    now = time.time() if now is None else now
    X = [x_row(F, A) for _, _, F, A, _ in rows]
    Y = [y for _, _, _, _, y in rows]
    base = dict(plan=PLAN, form="logit(H) = a + b * logit(clip(F, 0.02, 0.98)) + c * log(1 + 100 * A); H clipped to"
                                " [0.01, 0.99]; F, A = means of the 12 and 18 UTC runs",
                training=[str(TRAIN[0]), str(TRAIN[1])], station_days=len(rows), left_out_missing_fields=miss,
                rows_sha256=rows_sha(rows), request_sha256=req["sha256"], outcomes_sha256=outs["sha256"],
                rain_rate=sum(Y) / len(Y), F_counts=edge_counts([F for _, _, F, _, _ in rows]),
                identity=identity(root), fitted_ts=now,
                fitted_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"))
    r = fit_logit(X, Y)
    if r is None:
        base["failed"] = "Newton's method did not converge in %d steps" % MAX_STEPS
    else:
        (a, b, c), st = r
        base.update(a=a, b=b, c=c, steps=st)
        if not b > 0:
            base["failed"] = "b = %.4f is not positive" % b
        else:
            base["brier_in_sample"] = sum((H_of(base, F, A) - y) ** 2 for _, _, F, A, y in rows) / len(rows)
    save_json(rpath(MODEL), base, indent=1)
    err = keep_offsite(rpath(MODEL))
    if err:
        print(err)
    if "failed" in base:
        return None, "fit failed, frozen as failed; the verdict is 'not testable': %s" % base["failed"]
    return base, "fitted and frozen: a=%.4f b=%.4f c=%.4f on %d training station-days (%d left out for missing fields)" % (
        base["a"], base["b"], base["c"], len(rows), miss)


# ---------- 5. the score (plan section 5; once, on the PC) ----------
def judge(o, order, better, worse, five=False):
    """The gate's day-mean statistic for o = [(ticker, X, M, result)], with the 7-day block bootstrap."""
    mg = P7.margin(o)
    d = dict(reading=P7.reading(mg, better, worse))
    if not mg:
        d["confirmed"] = False
        return d
    tc = P7.tcrit(mg[2])
    t = mg[0] / mg[1] if mg[1] else None
    d.update(mean=mg[0], se=mg[1], days=mg[2], tcrit=tc, t=t)
    dm = P7.day_means(o)
    series = [dm[k] for k in sorted(dm, key=lambda k: order[k])]
    d["lag1"] = P7.lag1(series)
    if len(series) >= BOOT_MIN_DAYS:
        d["boot"] = list(P7.boot_interval(P7.boot_means(series)))
    d["confirmed"] = bool(d["reading"] == better and "boot" in d and d["boot"][1] < 0)
    if five:
        tq = P7.t_quantile(FIVE_P, mg[2] - 1)
        hi = P7.boot_interval(P7.boot_means(series, n=FIVE_DRAWS), FIVE_P, 1 - FIVE_P)[1] if len(series) >= BOOT_MIN_DAYS else None
        d["five_test"] = dict(t_needed=-tq, boot_high=hi, passes=bool(t is not None and t <= -tq and hi is not None and hi < 0))
    return d


def holdout_rows(req, model, markets, out_counts):
    """The scored rows: N0 markets with all four fields (plan sections 2 and 3)."""
    feats = {}
    for st in req["stations"]:
        f, ok = _read_json(os.path.join(feat_dir("holdout"), st + ".json"))
        if not ok:
            raise Refused("holdout features of %s are damaged" % st)
        feats[st] = (f or {}).get("days", {})
    rows, miss = [], []
    for m in markets:
        st = home_station(m["station"], req["stations"])
        if st not in req["stations"]:
            continue
        fa = combine(feats[st].get(m["day"][:10]))
        if fa is None:
            miss.append(m["ticker"])
            continue
        bid, ask = float(m["scan_bid"]), float(m["scan_ask"])
        M = (bid + ask) / 2
        H = H_of(model, fa[0], fa[1])
        rows.append(dict(ticker=m["ticker"], station=st, day=m["day"][:10], y=1 if m["result"] == "yes" else 0,
                         result=m["result"], M=M, H=H, B=BLEND * H + (1 - BLEND) * M, F=fa[0], A=fa[1], bid=bid,
                         ask=ask, lo=m.get("lo_after"), hi=m.get("hi_after")))
    out_counts["left_out_missing_fields"] = len(miss)
    return rows, miss


def signatures_summary():
    """Field signatures (model version evidence) by first and last unit, over both stages (plan section 8)."""
    out = {}
    for stage in STAGES:
        lg = _read_json(log_path(stage))[0] or {}
        for key in sorted(lg.get("fields", {})):
            for fh, sid in lg["fields"][key].items():
                s = out.setdefault(sid, dict(signature=lg["signatures"].get(sid), fields=0, first=key, last=key))
                s["fields"] += 1
                s["first"], s["last"] = min(s["first"], key), max(s["last"], key)
    return out


def missing_summary():
    out = {}
    for stage in STAGES:
        lg = _read_json(log_path(stage))[0] or {}
        out[stage] = dict(fields_missing=sum(len(v) for v in lg.get("missing", {}).values()),
                          units_with_missing=len(lg.get("missing", {})), geometry=lg.get("geometry", {}))
    return out


def airport(rows_all, runs, coef):
    """{ticker: C} from research/backtest.py's NBS features and calibration (PLAN.md's airport forecast)."""
    out = {}
    for r in rows_all:
        f = B.features(runs, r["station"], pday(r["day"]))
        if f:
            out[r["ticker"]] = B.C(coef, f)
    return out


def score(root=ROOT, runs=None, coef=None):
    """The single score (plan section 5). Returns (result, verdict)."""
    target = rpath(SCORE)
    for p in (target, offsite_path(target)):
        if os.path.exists(p):
            raise Refused("PLAN10 was already scored (%s); it is scored once" % p)
    require_identity(root)
    req, outs = load_public()
    req2, outs2, passed = build_request()
    if req2["sha256"] != req["sha256"] or outs2["sha256"] != outs["sha256"]:
        raise Refused("research/data no longer gives the committed request or training outcomes; the score waits for the"
                      " user (plan section 8)")
    raw, ok = _read_json(rpath(MODEL))
    if not ok or not isinstance(raw, dict) or not raw:
        raise Refused("no readable model (%s)" % MODEL)
    if raw.get("request_sha256") != req["sha256"]:
        raise Refused("the model was fitted for another request")
    rows_now, _ = train_rows(req, outs)
    if raw.get("rows_sha256") != rows_sha(rows_now):
        raise Refused("the training features no longer give the training rows the model was fitted on (rows_sha256)")
    err = keep_offsite(rpath(MODEL))
    if err:
        print(err)
    res = dict(plan=PLAN, scored_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), request_counts=req["counts"],
               excluded_stations=req["excluded_stations"], model={k: raw.get(k) for k in (
                   "a", "b", "c", "station_days", "rows_sha256", "failed", "F_counts", "left_out_missing_fields")},
               data_checks=dict(signatures=signatures_summary(), missing=missing_summary(),
                                signatures_note="indicative only: GRIB keys can stay the same across a model upgrade"))
    nt = None
    share = req["counts"]["excluded_share"]
    if "failed" in raw:
        nt = "the fit failed (%s)" % raw["failed"]
    elif share is not None and share > MAX_LEFT_OUT:
        nt = "excluded stations hold %.1f%% of the markets passing the quote rule (more than 10%%)" % (100 * share)
    else:
        full, done, total = complete("holdout", req, outs)
        if not full:
            raise Refused("the holdout download is not complete (%d of %d units)" % (done, total))
    if nt is None:
        cnt = {}
        rows, miss = holdout_rows(req, raw, passed, cnt)
        n0 = req["counts"]["n0"]
        res.update(n0=n0, left_out_missing_fields=miss, scored_markets=len(rows))
        if n0 and len(miss) / float(n0) > MAX_LEFT_OUT:
            nt = "%d of %d N0 markets (%.1f%%, more than 10%%) miss a field" % (len(miss), n0, 100.0 * len(miss) / n0)
        elif not rows:
            nt = "no scored markets"
    if nt is not None:
        res["verdict"] = "not testable: %s" % nt
    else:
        res.update(_statistics(rows, passed, req, runs, coef))
        res["verdict"] = VERDICT_LEAD if res["B"]["confirmed"] else VERDICT_NONE
    save_json(target, res, indent=1)
    with open(target[:-5] + ".md", "w", encoding="utf-8") as f:
        f.write(markdown(res))
    for p in (target, target[:-5] + ".md"):
        err = keep_offsite(p)
        if err:
            print(err)
    return res, res["verdict"]


def _statistics(rows, passed, req, runs, coef):
    order = {r["ticker"].split("-")[1]: r["day"] for r in rows}
    days = sorted({r["day"] for r in rows})
    out = dict(days=len(days), first_day=days[0], last_day=days[-1], rain_rate=sum(r["y"] for r in rows) / len(rows))
    out["B"] = judge([(r["ticker"], r["B"], r["M"], r["result"]) for r in rows], order,
                     "the blend 0.5 H + 0.5 M was clearly more accurate than Kalshi's price",
                     "Kalshi's price was clearly more accurate than the blend", five=True)
    if out["B"]["confirmed"]:
        out["A"] = judge([(r["ticker"], r["H"], r["M"], r["result"]) for r in rows], order,
                         "HRRR alone (H) was clearly more accurate than Kalshi's price",
                         "Kalshi's price was clearly more accurate than HRRR alone")
    else:
        out["A"] = dict(not_judged="A is judged only if B is confirmed (plan section 5)")
    # N: the paired comparison with the airport-forecast blend (descriptive)
    runs = B.load_nbs() if runs is None else runs
    if coef is None:
        coef = (_read_json(os.path.join(ROOT, "research", "results", "rain_model.json"))[0] or {}).get("coef")
    n0_rows = [dict(ticker=m["ticker"], station=home_station(m["station"], req["stations"]), day=m["day"][:10], M=(m["scan_bid"] + m["scan_ask"]) / 2,
                    result=m["result"]) for m in passed if home_station(m["station"], req["stations"]) in req["stations"]]
    C = airport(n0_rows, runs, coef) if coef else {}
    both = [r for r in rows if r["ticker"] in C]
    nd = {}
    for r in both:
        bc = BLEND * C[r["ticker"]] + (1 - BLEND) * r["M"]
        y = r["y"]
        nd.setdefault(r["day"], []).append(((r["B"] - y) ** 2 - (bc - y) ** 2, (r["B"] - y) ** 2 - (r["M"] - y) ** 2,
                                            (bc - y) ** 2 - (r["M"] - y) ** 2))
    ser = [[sum(x[i] for x in nd[d]) / len(nd[d]) for d in sorted(nd)] for i in range(3)]
    m_, se_ = P7.mean_se(ser[0]) if ser[0] else (None, None)
    out["N"] = dict(markets=len(both), days=len(nd), mean=m_, se=se_, corr=_corr(ser[1], ser[2]))
    c_own = [(r["ticker"], BLEND * C[r["ticker"]] + (1 - BLEND) * r["M"], r["M"], r["result"]) for r in n0_rows if r["ticker"] in C]
    corder = {r["ticker"].split("-")[1]: r["day"] for r in n0_rows}
    cj = judge(c_own, corder, "the airport-forecast blend was clearly more accurate than the price",
               "the price was clearly more accurate than the airport-forecast blend")
    cj.pop("confirmed", None)
    out["C_blend_own_set"] = dict(markets=len(c_own), **cj)
    # T: the bot's rule with fair = B's blend, the 30-point veto on H (descriptive)
    kept = t_rows(rows)
    out["T"] = B.trades(kept, days)
    out["T"]["vetoed_markets"] = len(rows) - len(kept)
    # descriptive tables
    br = lambda rs, k: sum((r[k] - r["y"]) ** 2 for r in rs) / len(rs)   # noqa: E731
    out["brier"] = dict(M=br(rows, "M"), H=br(rows, "H"), B=br(rows, "B"))
    out["calibration_H"] = B.calib(rows, "H")
    out["calibration_M"] = B.calib(rows, "M")
    out["F_counts"] = edge_counts([r["F"] for r in rows])
    bym, bys = {}, {}
    for r in rows:
        bym.setdefault(r["day"][:7], []).append(r)
        bys.setdefault(r["station"], []).append(r)
    out["by_month"] = {k: dict(n=len(v), brier_M=br(v, "M"), brier_B=br(v, "B"), brier_H=br(v, "H")) for k, v in sorted(bym.items())}
    out["by_station"] = {k: dict(n=len(v), brier_M=br(v, "M"), brier_B=br(v, "B"), brier_H=br(v, "H")) for k, v in sorted(bys.items())}
    cli = load_cli()
    chk = [cli_outcome(cli, r["station"], pday(r["day"]))[0] for r in rows]
    agree = [c == (r["y"] == 1) for c, r in zip(chk, rows) if c is not None]
    out["cli_vs_kalshi"] = dict(checked=len(agree), agree=sum(agree))
    return out


def t_rows(rows):
    """The rows T may bet on: the bot's 30-point veto applied to H (plan section 5), not to the blend."""
    return [r for r in rows if abs(r["H"] - r["M"]) <= VETO + 1e-12]


def _corr(a, b):
    if len(a) < 3 or len(a) != len(b):
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((x - mb) ** 2 for x in b)
    if not sa or not sb:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sa * sb)


def markdown(res):
    def fmt(d):
        if not d:
            return "n/a"
        if d.get("not_judged"):
            return "not judged: " + d["not_judged"]
        if d.get("mean") is None:
            return d.get("reading", "n/a")
        s = "%s (mean %+.5f, SE %.5f, t %s, %d days, t needed %.3f" % (
            d["reading"], d["mean"], d["se"], "n/a" if d.get("t") is None else "%+.2f" % d["t"], d["days"], -d["tcrit"])
        if "boot" in d:
            s += "; 7-day block bootstrap 95%%: %+.5f to %+.5f" % tuple(d["boot"])
        return s + ")"
    L_ = ["# PLAN10 score (HRRR on PLAN.md's past markets)", "",
          "Research only (%s). Scored once, %s." % (res["plan"], res["scored_utc"]), "",
          "**Verdict:** %s" % res["verdict"], ""]
    c = res["request_counts"]
    L_.append("- Markets: %d passed the quote rule; N0 %d; %d left out with %d excluded stations; %s scored." % (
        c["passed_quote"], c["n0"], c["excluded_markets"], c["stations_excluded"], res.get("scored_markets", "none")))
    if res.get("excluded_stations"):
        L_.append("- Stations left out: " + "; ".join("%s (%d markets: %s)" % (k, v["markets"], v["reason"])
                                                     for k, v in sorted(res["excluded_stations"].items())))
    if "B" in res:
        L_ += ["- B (primary, 0.5 H + 0.5 M vs M): " + fmt(res["B"]),
               "- B at the five-test line (0.5%% one-sided, bootstrap %d draws; reported only): %s" % (
                   FIVE_DRAWS, "passes" if res["B"].get("five_test", {}).get("passes") else "does not pass"),
               "- A (H vs M; only if B is confirmed): " + fmt(res["A"])]
        n = res["N"]
        L_.append("- N (descriptive, H's blend minus the airport forecast's blend, %d markets on %d days): %s" % (
            n["markets"], n["days"], "n/a" if n["mean"] is None else "mean %+.5f, SE %.5f, correlation of the day series %s" % (
                n["mean"], n["se"], "n/a" if n["corr"] is None else "%+.2f" % n["corr"])))
        L_.append("- The airport-forecast blend on its own set (%d markets): %s" % (res["C_blend_own_set"]["markets"],
                                                                                  fmt(res["C_blend_own_set"])))
        for k, lab in (("taker", "T, paying the ask"), ("maker", "T, limit orders (PLAN.md's fill model)")):
            v = res["T"][k]
            L_.append("- %s: %s" % (lab, "no trades" if not v.get("n") else
                                    "%d trades, %d won, %+.1f cents a contract, day mean %+.4f (SE %.4f)" % (
                                        v["n"], v["won"], 100 * v["per_contract"], v["day_mean"], v["day_se"])))
        L_.append("- Pooled Brier: " + ", ".join("%s %.4f" % kv for kv in sorted(res["brier"].items())))
        L_.append("- F = 0 / F = 1 among scored markets: %d / %d of %d; in training: %s" % (
            res["F_counts"]["F0"], res["F_counts"]["F1"], res["F_counts"]["n"], res["model"].get("F_counts")))
        L_.append("- Climate report vs Kalshi's result: %d of %d agree" % (res["cli_vs_kalshi"]["agree"], res["cli_vs_kalshi"]["checked"]))
    sig = res["data_checks"]["signatures"]
    L_.append("- HRRR field signatures (indicative only: GRIB keys can stay the same across a model upgrade): %d"
              " distinct (%s)" % (len(sig), "; ".join(
        "%s: %d fields, %s to %s" % (k, v["fields"], v["first"], v["last"]) for k, v in sorted(sig.items()))))
    ms = res["data_checks"]["missing"]
    L_.append("- Fields missing: training %d, holdout %d" % (ms["train"]["fields_missing"], ms["holdout"]["fields_missing"]))
    L_ += ["", "A, N, T, the calibration, the months and the stations are descriptive and never used to pick anything."
           " These markets were scored before (PLAN.md), so even a pass is a lead on reused data that justifies writing"
           " PLAN10F only, never money (plan sections 0 and 11)."]
    return "\n".join(L_) + "\n"


# ---------- 6. status ----------
def status(root=ROOT):
    bad = identity_problems(root)
    parts = ["PLAN10 (research, not in gate)", "identity " + ("ok" if not bad else "PROBLEM: " + ", ".join(bad))]
    try:
        req, outs = load_public()
        parts.append("request: %d stations, %d holdout markets" % (req["counts"]["stations"], req["counts"]["n0"]))
        for s in STAGES:
            full, done, total = complete(s, req, outs)
            parts.append("%s %d of %d units" % (s, done, total))
    except Refused as ex:
        parts.append(str(ex))
    m, ok = _read_json(rpath(MODEL))
    parts.append("model " + ("damaged" if not ok else "not fitted" if not m else "FAILED" if "failed" in m else "fitted"))
    parts.append("scored" if os.path.exists(rpath(SCORE)) else "not scored")
    return "; ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN10: NOAA HRRR vs Kalshi's price on past markets (research only)")
    ap.add_argument("cmd", choices=("freeze", "request", "check", "train-download", "fit", "holdout-download", "score",
                                    "status"))
    ap.add_argument("--budget-minutes", type=float, default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "freeze":
            rec, msg = freeze()
            print("PLAN10: " + msg)
            return 0 if rec else 2
        if a.cmd == "request":
            print("PLAN10: " + make_request())
        elif a.cmd == "check":
            print(check())
        elif a.cmd in ("train-download", "holdout-download"):
            print(download(a.cmd.split("-")[0], budget_minutes=a.budget_minutes))
        elif a.cmd == "fit":
            model, msg = fit()
            print("PLAN10: " + msg)
            return 0 if model else 3
        elif a.cmd == "score":
            _, verdict = score()
            print("PLAN10 verdict: " + verdict + " (details: research/results/plan10_score.md)")
        else:
            print(status())
        return 0
    except Refused as ex:
        print("PLAN10 refused: %s" % ex)
        return 2


if __name__ == "__main__":
    sys.exit(main())
