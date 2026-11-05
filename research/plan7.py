"""PLAN7: v3 with its rain lean corrected (the "v5 candidate"). Research and paper only; follows research/PLAN7.md,
written 2026-11-05 before any of its forward data and before the fit, and revised the same day after its statistics
review (still before any forward data).

The scoring rule is pinned in this file. The values and functions it shares with the bot (the blend, edge, spread and
veto values; the gate's day-mean statistic and t-table; the shadow ledger's fill rule and bootstrap; the taker fee) are
copied here rather than imported, so a later change to config.py, gate.py or shadow.py cannot change how this test is
judged. tests/test_plan7.py checks that each copy still equals its source at the time the plan was frozen.

Commands:
- candles: store Kalshi's public minute candles for every forward market once its day has started (each market once,
  compacted to the fields the fill rule reads, one gzip file per market day under research/data/plan7/candles).
- fit: once, frozen in research/results/plan7_model.json and never refitted: logit(q) = a + b * logit(p) on the
  resolved v3 rain markets of the test's own days.
- status: counts only (forward days, markets, candles); no outcome-based number.
- score --look 60|110 [--ended REASON]: the plan's two looks, run by hand, each once (section 5 of the plan).
- auto: candles, then the fit when its day has come. The settle job runs it (run.bat settle); it never scores and never
  fails the job.

Boundaries:
- paper.db is opened read-only (sqlite mode=ro) and only read;
- it writes only its own files: the model, the candle store, and research/results/plan7_score_<look>.md/.json;
- its only network use is GET /markets/candlesticks on Kalshi's public API (the domain the bot already reads);
- it places nothing, and nothing here can reach live.py.

  python research/plan7.py candles|fit|status|auto [--db PAPER_DB]
  python research/plan7.py score --look 60|110 [--ended "why v3 logging ended"] [--db PAPER_DB]
Python 3.8+, standard library (requests for the candles only)."""
import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tbcommon import clock, db, jsonio   # noqa: E402  (file input and output only, never the rule)
from tbcommon.httpclient import KALSHI_PUBLIC, USER_AGENT   # noqa: E402

PLAN = "research/PLAN7.md"
STRATEGY = "forecast_alpha.rain.v3"     # the audit ledger's id for v3 rain decisions (strategy.STRATEGY_RAIN)
FORWARD_FIRST = date(2026, 11, 11)      # the first forward market day (the gate's stop date)
FIT_LATEST = date(2026, 11, 13)         # from this date the fit runs even if a test-day market never got a result
BACKSTOP = date(2027, 6, 30)            # market days after this date never count
BACKSTOP_LOOK = date(2027, 7, 7)        # from here, a test short of 110 counted days reads "not confirmed"
BOT_TZ = timezone(timedelta(hours=-4))  # La Paz, UTC-4 all year (tbcommon.clock.BOT_TZ)
LOOKS = (60, 110)

# ---------- the pinned rule (copies; tests/test_plan7.py checks them against their sources) ----------
BLEND, MIN_EDGE, MAX_SPREAD = 0.5, 0.08, 0.06   # config.BLEND, MIN_EDGE, MAX_SPREAD
VETO_MAX_GAP = 0.30                              # strategy.VETO_MAX_GAP
EPS = 0.01                                       # p and q clipped to [EPS, 1 - EPS] (research/PLAN.md's calibration)
MIN_MARKETS, MIN_DAYS, MAX_STEPS = 100, 5, 50
WINDOW = (50 * 60, 5 * 3600)                     # a scan that began 00:50 (incl.) to 05:00 UTC (excl.) on the market day
DAY_START_MARGIN = 180                           # candles are read 3 minutes after the day start, as shadow.py does
NO_CANDLES_AFTER = 7 * 86400                     # a market without candles 7 days after its day start, after
NO_CANDLES_TRIES = 3                             # at least 3 tries on separate runs, counts as not filled
BOOT_BLOCK, BOOT_DRAWS, BOOT_SEED, BOOT_MIN_DAYS = 7, 5000, 11, 14
UNUSABLE = ("MARKET_STARTED",)
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,   # gate.T975
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data", "plan7")
MODEL = os.path.join(RESULTS, "plan7_model.json")
CANDLES = os.path.join(DATA, "candles")
RESULTS_PENDING_DAYS = 7   # a counted day's market still without a result this many days later is left out and listed


def offsite():
    """The off-folder backup location backup.py uses (TRADEBOT_OFFSITE_BACKUPS, else Documents\\tradebot_backups)."""
    return os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups")


def offsite_path(path, sub):
    return os.path.join(offsite(), "plan7", sub, os.path.basename(path))


def mirror(path, sub, keep=None):
    """Copy one of this test's own files to the off-folder backup (plan section 8): the candles cannot be fetched
    again once Kalshi drops old history, and this folder was wiped once. keep(existing copy) -> True leaves an
    existing off-folder copy alone (the frozen model; a day file holding more markets). A failure only prints a
    warning."""
    try:
        dst = offsite_path(path, sub)
        if os.path.exists(dst) and keep is not None and keep(dst):
            return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    except OSError as ex:
        print("PLAN7: off-folder copy of %s failed (%s)" % (os.path.basename(path), ex))


def market_day(ticker):
    """The market day in a ticker ("KXRAIN-26NOV11-NYC" -> 2026-11-11), or None (tbcommon.parse.market_day)."""
    try:
        return datetime.strptime(ticker.split("-")[1], "%y%b%d").date()
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def bot_date(ts):
    """The date in the bot's zone (tbcommon.clock.bot_date)."""
    return datetime.fromtimestamp(ts, BOT_TZ).date()


def tcrit(days):
    """gate.tcrit: Student-t 97.5% for the day means (df = days - 1), never below 2.0."""
    return max(2.0, T975.get(days - 1, 2.0))


def day_means(o):
    """{day key: mean of forecast Brier minus market Brier} for o = [(ticker, forecast, market, result)] (gate.margin's
    grouping: one value per market day)."""
    days = {}
    for t, f, m, r in o:
        y = 1.0 if r == "yes" else 0.0
        days.setdefault(t.split("-")[1], []).append((f - y) ** 2 - (m - y) ** 2)
    return {k: sum(v) / len(v) for k, v in days.items()}


def margin(o):
    """gate.margin: (mean, SE, days) of the day means, or None with fewer than 5 days."""
    d = list(day_means(o).values())
    if len(d) < 5:
        return None
    mu = sum(d) / len(d)
    return mu, (sum((x - mu) ** 2 for x in d) / (len(d) - 1) / len(d)) ** 0.5, len(d)


def _f(d, k):
    """shadow._f: a number from a candle field, or None."""
    v = (d or {}).get(k)
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def fill_time(side, price, imp, t0, t1, cs):
    """shadow.fill_time: end of the first whole minute after the order (t0) and up to its cancellation (t1) in which a
    trade or an offer reached the limit price (strictly through it when the order joined the bid); None if never."""
    for x in cs:
        e = x["end_period_ts"]
        if e - 60 < t0 or e > t1:
            continue
        if side == "yes":
            v = [p for p in (_f(x.get("price"), "low_dollars"), _f(x.get("yes_ask"), "low_dollars")) if p is not None and p > 0]
            if v and (min(v) <= price + 1e-9 if imp else min(v) < price - 1e-9):
                return e
        else:
            a = 1 - price
            v = [p for p in (_f(x.get("price"), "high_dollars"), _f(x.get("yes_bid"), "high_dollars")) if p is not None and p < 1]
            if v and (max(v) >= a - 1e-9 if imp else max(v) > a + 1e-9):
                return e
    return None


def taker_fee(p):
    """shadow._taker_fee: Kalshi's taker fee for one contract, rounded up to the cent."""
    return math.ceil(0.07 * p * (1 - p) * 100 - 1e-9) / 100


def boot_means(x, block=BOOT_BLOCK, n=BOOT_DRAWS, seed=BOOT_SEED):
    """shadow._boot's moving-block bootstrap of the mean over consecutive counted market days; the sorted draws."""
    import random
    rnd = random.Random(seed)
    L = len(x)
    k = -(-L // block)
    ms = []
    for _ in range(n):
        s = []
        for _ in range(k):
            i = rnd.randrange(0, L - block + 1)
            s.extend(x[i:i + block])
        ms.append(sum(s[:L]) / L)
    ms.sort()
    return ms


def boot_interval(ms, low=0.025, high=0.975):
    """The percentile interval of sorted draws, read as shadow._boot reads its 2.5th and 97.5th."""
    n = len(ms)
    return ms[int(low * n)], ms[int(high * n) - 1]


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (learn.py's copy, Numerical Recipes betacf)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c = 1.0
    d = 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            de = d * c
            h *= de
        if abs(de - 1) < 3e-14:
            break
    return h


def t_upper(t, df):
    """P(T > t) for Student-t with df degrees of freedom, t >= 0."""
    x = df / (df + t * t)
    a, b = df / 2, 0.5
    if x <= 0:
        return 0.0
    if x >= 1:
        return 0.5
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    ib = math.exp(lb) * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - math.exp(lb) * _betacf(b, a, 1 - x) / b
    return 0.5 * ib


def t_quantile(p, df):
    """The t value with upper-tail probability p (bisection)."""
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_upper(mid, df) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------- small helpers ----------
def default_db():
    p = os.environ.get("PAPER_DB") or "paper.db"
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def connect_ro(path):
    """A read-only connection; a missing file is refused rather than created."""
    if not os.path.isfile(path):
        raise SystemExit("not found: %s" % path)
    return db.connect_ro(path)


def clip(p):
    return min(1.0 - EPS, max(EPS, p))


def logit(p):
    return math.log(p / (1.0 - p))


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def corrected(p, model):
    """The frozen correction: logit(q) = a + b * logit(clip(p)), q clipped to [EPS, 1 - EPS]."""
    return clip(sigmoid(model["a"] + model["b"] * logit(clip(p))))


def midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()


def in_window(ts, day):
    """A scan that began inside the market day's evening window: 00:50 to 05:00 UTC, which is 8:50 PM to 1 AM La Paz
    the evening before (scan_window.py)."""
    return WINDOW[0] <= ts - midnight(day) < WINDOW[1]


# ---------- 1. the fit (once) ----------
def fit_rows(c):
    """(ticker, v3 forecast, result, logged ts) of every resolved v3 rain market of the test's days (before
    FORWARD_FIRST: the gate look's own rows), and the tickers still waiting for a result (an unreadable day waits too)."""
    rows, pending = [], []
    for t, fc, r, ts in c.execute("select ticker,fc,result,ts from obs where version='v3' and market_type='rain'"):
        d = market_day(t)
        if d is not None and d >= FORWARD_FIRST:
            continue
        if r in ("yes", "no") and d is not None and fc is not None:
            rows.append((t, float(fc), r, ts))
        else:
            pending.append(t)
    return sorted(rows), sorted(pending)


def fit_versions(c):
    """The model versions (v3@hash of weather.py, nws.py and strategy.py) of the test days' rain decisions with a
    forecast. Forward rows count only with one of these (PLAN7 section 3)."""
    try:
        got = c.execute("select ticker,model_version from decisions where strategy_id=? and p_model is not null and "
                        "reason not in (%s)" % ",".join("?" * len(UNUSABLE)), (STRATEGY,) + UNUSABLE).fetchall()
    except sqlite3.OperationalError as ex:   # no ledger: no versions known; any other error (a lock) propagates
        if "no such table" in str(ex):
            return []
        raise
    return sorted({v for t, v in got if v and market_day(t) is not None and market_day(t) < FORWARD_FIRST})


def fit_logistic(xs, ys, steps=MAX_STEPS, tol=1e-10):
    """Maximum-likelihood (a, b, steps) for P(y=1) = sigmoid(a + b x) by Newton's method from a=0, b=1; None when it
    does not converge (for example perfect separation) or the curvature is singular."""
    a, b = 0.0, 1.0
    for k in range(steps):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = sigmoid(a + b * x)
            w = p * (1.0 - p)
            ga += y - p
            gb += (y - p) * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if not det > 0:
            return None
        da = (hbb * ga - hab * gb) / det
        db_ = (haa * gb - hab * ga) / det
        a, b = a + da, b + db_
        if not (math.isfinite(a) and math.isfinite(b)):
            return None
        if abs(da) < tol and abs(db_) < tol:
            return a, b, k + 1
    return None


def clustered_se(xs, ys, groups, a, b):
    """Day-clustered (sandwich) standard errors of (a, b): descriptive only (PLAN7 section 2)."""
    haa = hab = hbb = 0.0
    score = {}
    for x, y, g in zip(xs, ys, groups):
        p = sigmoid(a + b * x)
        w = p * (1 - p)
        haa += w
        hab += w * x
        hbb += w * x * x
        s = score.setdefault(g, [0.0, 0.0])
        s[0] += y - p
        s[1] += (y - p) * x
    det = haa * hbb - hab * hab
    inv = ((hbb / det, -hab / det), (-hab / det, haa / det))
    g = len(score)
    adj = g / (g - 1.0) if g > 1 else 1.0   # small-sample correction for few clusters
    m00 = sum(s[0] * s[0] for s in score.values())
    m01 = sum(s[0] * s[1] for s in score.values())
    m11 = sum(s[1] * s[1] for s in score.values())
    meat = ((m00, m01), (m01, m11))
    v = [[sum(inv[i][k] * meat[k][j2] * inv[j2][j] for k in range(2) for j2 in range(2)) for j in range(2)] for i in range(2)]
    return math.sqrt(max(adj * v[0][0], 0.0)), math.sqrt(max(adj * v[1][1], 0.0))


def file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def rows_hash(rows):
    return hashlib.sha256(json.dumps([list(r[:3]) for r in rows], separators=(",", ":")).encode("utf-8")).hexdigest()


def fit(c, today=None, model_path=None, now=None):
    """Fit and freeze the correction once (PLAN7 section 2). Returns (model dict or None, message)."""
    model_path = model_path or MODEL
    saved = offsite_path(model_path, "results")
    if not os.path.exists(model_path) and os.path.exists(saved):   # the local copy was lost: restore it, never refit
        try:
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            shutil.copy2(saved, model_path)
            print("PLAN7: the frozen model was missing here; restored from %s (never refitted)" % saved)
        except OSError as ex:
            return None, "the frozen model is missing here and could not be restored from %s (%s); restore it by hand" % (
                saved, ex)
    if os.path.exists(model_path):
        m = jsonio.load(model_path) or {}
        if "failed" in m:
            return None, "the fit failed earlier and that is frozen, so the test does not run: %s" % m["failed"]
        return m, "already fitted (frozen; never refitted)"
    now = time.time() if now is None else now
    today = today or bot_date(now)
    if today < FORWARD_FIRST:
        return None, "waiting: the fit runs on or after %s" % FORWARD_FIRST
    rows, pending = fit_rows(c)
    if pending and today < FIT_LATEST:
        return None, "waiting: %d v3 rain markets of the test's days have no result yet (the fit runs anyway from %s)" % (
            len(pending), FIT_LATEST)
    days = sorted({market_day(t) for t, _, _, _ in rows})
    versions = fit_versions(c)
    base = dict(plan=PLAN, eps=EPS, markets=len(rows), days=len(days), rows_sha256=rows_hash(rows),
                first_day=str(days[0]) if days else None, last_day=str(days[-1]) if days else None,
                left_out=pending, model_versions=versions,
                form="logit(q) = a + b * logit(clip(p, %g, %g)); q clipped to the same range" % (EPS, 1 - EPS),
                at_bounds=sum(1 for _, f, _, _ in rows if f <= EPS or f >= 1 - EPS),
                outside_window=sum(1 for t, _, _, ts in rows if ts is None or not in_window(ts, market_day(t))),
                fitted_ts=now, fitted=clock.iso(now),
                code_sha256={f: file_sha256(os.path.join(ROOT, f)) for f in ("weather.py", "nws.py", "strategy.py")})
    xs = [logit(clip(f)) for _, f, _, _ in rows]
    ys = [1.0 if r == "yes" else 0.0 for _, _, r, _ in rows]
    res = None
    if len(rows) < MIN_MARKETS or len(days) < MIN_DAYS:
        base["failed"] = "too few markets or days (%d markets, %d days; %d and %d needed)" % (
            len(rows), len(days), MIN_MARKETS, MIN_DAYS)
    elif not versions:
        base["failed"] = "no model version recorded for the test days' decisions, so forward rows cannot be matched"
    else:
        res = fit_logistic(xs, ys)
        if res is None:
            base["failed"] = "Newton's method did not converge in %d steps" % MAX_STEPS
        else:
            base.update(a=res[0], b=res[1], steps=res[2])
            if not res[1] > 0:
                base["failed"] = "b <= 0 (b = %.4f)" % res[1]
    if res is not None and "failed" not in base:   # descriptive checks, stored with the frozen model
        groups = [market_day(t) for t, _, _, _ in rows]
        base["se_clustered"] = list(clustered_se(xs, ys, groups, res[0], res[1]))
        lodo = []
        for d in days:
            keep = [i for i, g in enumerate(groups) if g != d]
            r = fit_logistic([xs[i] for i in keep], [ys[i] for i in keep])
            if r is not None:
                lodo.append((r[0], r[1]))
        if lodo:
            base["leave_one_day_out"] = dict(a=[min(x[0] for x in lodo), max(x[0] for x in lodo)],
                                             b=[min(x[1] for x in lodo), max(x[1] for x in lodo)], fits=len(lodo))
    jsonio.save(model_path, base)
    mirror(model_path, "results", keep=lambda dst: True)   # frozen: an existing off-folder model is never replaced
    if "failed" in base:
        return None, "fit failed, so the test does not run: %s" % base["failed"]
    return base, "fitted and frozen: a=%.4f b=%.4f on %d markets, %d market days%s" % (
        base["a"], base["b"], len(rows), len(days), (" (%d left out without a result)" % len(pending)) if pending else "")


def load_model(path=None):
    m = jsonio.load(path or MODEL)
    return None if (not m or "failed" in m) else m


def allowed_versions(model, path=None):
    """The fit days' model versions, plus any added by a recorded amendment (research/results/plan7_versions.json:
    {"versions": [{"version", "reason", "recorded"}]}; plan section 3). Nothing in this file writes that list."""
    extra = jsonio.load(path or os.path.join(RESULTS, "plan7_versions.json")) or {}
    return set(model["model_versions"]) | {v.get("version") for v in extra.get("versions", []) if v.get("version")}


# ---------- 2. forward rows and signals ----------
def forward_rows(c, versions=None, excluded=None, only_days=None):
    """{ticker: row} of forward markets (PLAN7 section 3): the first v3 rain decision row of each market from Nov 11 on
    with a forecast, a usable quote and a reason other than MARKET_STARTED, from a scan that began inside its window,
    with a model version the fit days carried (when versions is given). excluded, a dict, receives counts by reason of
    the rows passed over (a market can have several), for only_days when given."""
    ex = excluded if excluded is not None else {}
    try:
        starts = dict(c.execute("select scan_id,started_ts from scans").fetchall())
    except sqlite3.OperationalError as ex:   # no scans table: each row is judged on its own time; a lock propagates
        if "no such table" not in str(ex):
            raise
        starts = {}
    res = dict(c.execute("select ticker,result from obs where version='v3' and market_type='rain'").fetchall())
    out = {}
    for t, ts, p, bid, ask, start, reason, sid, mv in c.execute(
            "select ticker,ts,p_model,bid,ask,day_start_ts,reason,scan_id,model_version from decisions where strategy_id=? and "
            "strategy_version='v3' and p_model is not null and bid is not null and ask is not null "
            "order by ts,decision_id", (STRATEGY,)):
        d = market_day(t)
        if t in out or d is None or d < FORWARD_FIRST:
            continue
        began = starts.get(sid) or ts
        why = ("market_started" if reason in UNUSABLE else
               "no_day_start" if start is None else
               "outside_window" if not in_window(began, d) else
               "spread" if not (0 <= bid < ask <= 1 and ask - bid <= MAX_SPREAD + 1e-9) else
               "model_version" if versions is not None and mv not in versions else None)
        if why:
            if only_days is None or d in only_days:
                ex[why] = ex.get(why, 0) + 1
            continue
        r = res.get(t)
        out[t] = dict(ticker=t, day=d, ts=ts, began=began, p=float(p), bid=float(bid), ask=float(ask), start=start,
                      result=r if r in ("yes", "no") else None)
    return out


def signals(q, bid, ask):
    """(taker, maker) one-contract signals of the live bot's rule on forecast q (PLAN7 section 4, T): taker = (side,
    price) or None; maker = (side, limit price, improved) or None. The construction is the airport-forecast test's
    (shadow.settle step 5) plus the bot's veto."""
    mid = (bid + ask) / 2
    if abs(q - mid) > VETO_MAX_GAP + 1e-9:
        return None, None
    fair = BLEND * q + (1 - BLEND) * mid
    side, price, win = max([("yes", ask, fair), ("no", 1 - bid, 1 - fair)], key=lambda x: x[2] - x[1])
    taker = (side, price) if win - price >= MIN_EDGE - 1e-9 else None
    yb = round(bid + 0.01, 2)
    iy = yb < round(ask, 2)
    ya = round(ask - 0.01, 2)
    ino = ya > round(bid, 2)
    side, price, win, imp = max([("yes", yb if iy else round(bid, 2), fair, iy),
                                 ("no", round(1 - (ya if ino else ask), 2), 1 - fair, ino)], key=lambda x: x[2] - x[1])
    maker = (side, price, imp) if win - price >= MIN_EDGE - 1e-9 and 0 < price < 1 else None
    return taker, maker


def pnl(side, price, result, fee=0.0):
    return (1.0 if result == side else 0.0) - price - fee


# ---------- 3. the candle store (each market once, before and after the fit) ----------
def _compact(x):
    """Only the fields fill_time reads, in their original shape."""
    out = dict(end_period_ts=x["end_period_ts"])
    for k, sub in (("price", ("low_dollars", "high_dollars")), ("yes_ask", ("low_dollars",)), ("yes_bid", ("high_dollars",))):
        v = {s: (x.get(k) or {}).get(s) for s in sub if (x.get(k) or {}).get(s) not in (None, "")}
        if v:
            out[k] = v
    return out


def day_file(day, folder=None):
    return os.path.join(folder or CANDLES, "%s.json.gz" % day)


def load_day(day, folder=None):
    """One market day's stored candles. An unreadable file (a power cut mid-write) is moved aside, never deleted, and
    the day starts again empty, so its candles are fetched again."""
    p = day_file(day, folder)
    st = _read_day(p)
    if st is None:   # unreadable: moved aside, never deleted
        aside = "%s.unreadable-%d-%d" % (p, os.getpid(), int(time.time() * 1000))
        try:
            os.replace(p, aside)
        except OSError:
            pass
        print("PLAN7: %s was unreadable; moved aside to %s" % (os.path.basename(p), os.path.basename(aside)))
    if st is None or not os.path.exists(p):   # missing or unreadable here: the off-folder copy, if there is one
        st = _read_day(offsite_path(p, "candles")) or dict(candles={}, none=[], why={}, tries={})
    return st


def _read_day(p):
    """A day file's store, or None when it is missing or unreadable (any damage: gzip, zlib or JSON)."""
    if not os.path.exists(p):
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            st = json.load(f)
        for k in ("candles", "none"):
            if k not in st:
                raise ValueError("no %s" % k)
        st.setdefault("why", {})
        st.setdefault("tries", {})
        return st
    except Exception:   # zlib.error and anything else a damaged file can raise
        return None


def _size(st):
    return len(st["candles"]) + len(st["none"])


def save_day(day, store, folder=None, attempts=5, sleep=time.sleep):
    """Write a day file atomically: a temp file of its own (pid and time), then os.replace, retried while Windows (an
    antivirus or indexer) holds the target, as tbcommon.jsonio.save does. Then the off-folder copy."""
    p = day_file(day, folder)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d-%d.tmp" % (p, os.getpid(), int(time.time() * 1000))
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(store, f, separators=(",", ":"))
    for k in range(attempts):
        try:
            os.replace(tmp, p)
            break
        except PermissionError:
            if k == attempts - 1:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            sleep(1 + k)
    mirror(p, "candles", keep=lambda dst: _size(_read_day(dst) or dict(candles={}, none=[])) > _size(store))


def fetch_candles(tickers, start, end, size=20, get=None):
    """{ticker: minute candles sorted by end time} from GET /markets/candlesticks, with the latest candle before start
    (shadow._candles' request). Network errors propagate, so the caller retries on the next run."""
    if get is None:
        import requests

        def get(url, params):
            return requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    out = {}
    for i in range(0, len(tickers), size):
        part = tickers[i:i + size]
        r = get((os.environ.get("KALSHI_BASE") or KALSHI_PUBLIC) + "/markets/candlesticks",
                dict(market_tickers=",".join(part), start_ts=int(start), end_ts=int(end), period_interval=1,
                     include_latest_before_start="true"))
        r.raise_for_status()
        ms = r.json().get("markets", [])
        if size > 1 and sum(len(x.get("candlesticks") or []) for x in ms) >= 9000:   # near the 10,000-candle cap
            out.update(fetch_candles(part, start, end, max(1, size // 5), get))
            continue
        for x in ms:
            out[x["market_ticker"]] = sorted(x.get("candlesticks") or [], key=lambda k: k["end_period_ts"])
        time.sleep(0.2)
    return out


def store_candles(c, now=None, fetch=None, folder=None):
    """Store candles for every forward market whose day has started, each once (PLAN7 sections 3 and 8). A market
    still without candles NO_CANDLES_AFTER its day start, after NO_CANDLES_TRIES tries (failed requests included), is
    listed under "none" with the reason (it then counts as unfilled). Returns (stored, waiting)."""
    now = time.time() if now is None else now
    fetch = fetch or fetch_candles
    by_day = {}
    for r in forward_rows(c).values():   # every model version: the store is a superset, filtered at the look
        by_day.setdefault(r["day"], []).append(r)
    stored = waiting = 0
    for day, rows in sorted(by_day.items()):
        st = load_day(day, folder)
        todo = [r for r in rows if r["ticker"] not in st["candles"] and r["ticker"] not in st["none"]]
        ready = [r for r in todo if r["start"] is not None and now >= r["start"] + DAY_START_MARGIN]
        waiting += len(todo) - len(ready)
        if not ready:
            continue
        error = None
        try:
            got = fetch(sorted(r["ticker"] for r in ready), min(r["ts"] for r in ready) - 60, max(r["start"] for r in ready))
        except Exception as ex:   # network or format trouble: retried at the next run, up to the 7-day rule
            error = str(ex)[:120]
            print("PLAN7: price history for %s not available (%s); will retry" % (day, error))
            got = {}
        changed = False
        for r in ready:
            cs = got.get(r["ticker"])
            if cs:
                st["candles"][r["ticker"]] = [_compact(x) for x in cs]
                stored += 1
                changed = True
            else:   # no candles this time: counted; the plan's rule applies whatever the cause
                t = r["ticker"]
                st["tries"][t] = st["tries"].get(t, 0) + 1
                st["why"][t] = ("request failed: %s" % error) if error is not None else "no candles returned"
                changed = True
                if now >= r["start"] + NO_CANDLES_AFTER and st["tries"][t] >= NO_CANDLES_TRIES:
                    st["none"].append(t)   # counts as not filled
                else:
                    waiting += 1
        if changed:
            save_day(day, st, folder)
    return stored, waiting


# ---------- 4. scoring (two looks, each once) ----------
def mean_se(x):
    if len(x) < 2:
        return None, None
    m = sum(x) / len(x)
    return m, (sum((v - m) ** 2 for v in x) / (len(x) - 1) / len(x)) ** 0.5


def lag1(x):
    if len(x) < 3:
        return None
    m = sum(x) / len(x)
    den = sum((v - m) ** 2 for v in x)
    return None if den == 0 else sum((x[i] - m) * (x[i - 1] - m) for i in range(1, len(x))) / den


def reading(mg, better, worse):
    if mg is None:
        return "too few market days for a reading (5 needed)"
    mu, se, nd = mg
    tc = tcrit(nd)
    if mu < 0 and -mu >= tc * se:
        return better
    if mu > 0 and mu >= tc * se:
        return worse
    return "no clear difference"


def accuracy(rows, model):
    """A, A2 and A3 (PLAN7 section 4). A also gets its day series' lag-1 autocorrelation, its block-bootstrap interval
    and the Bonferroni line (t at 1.25% one-sided)."""
    q = [(r["ticker"], corrected(r["p"], model), (r["bid"] + r["ask"]) / 2, r["result"], r["p"], r["day"]) for r in rows]
    order = {}
    for x in q:
        order[x[0].split("-")[1]] = x[5]
    out = {}
    for key, pick, better, worse in (
            ("A", lambda x: (x[0], x[1], x[2], x[3]), "the corrected forecast was clearly more accurate than Kalshi's prices",
             "Kalshi's prices were clearly more accurate than the corrected forecast"),
            ("A2", lambda x: (x[0], x[4], x[2], x[3]), "v3 was clearly more accurate than Kalshi's prices",
             "Kalshi's prices were clearly more accurate than v3"),
            ("A3", lambda x: (x[0], x[1], x[4], x[3]), "the correction clearly improved on v3",
             "v3 was clearly more accurate than its correction")):
        o = [pick(x) for x in q]
        mg = margin(o)
        d = dict(reading=reading(mg, better, worse))
        if mg:
            tc = tcrit(mg[2])
            d.update(mean=mg[0], se=mg[1], days=mg[2], tcrit=tc, low=mg[0] - tc * mg[1], high=mg[0] + tc * mg[1],
                     t=(mg[0] / mg[1]) if mg[1] else None)
            if key == "A":
                dm = day_means(o)
                series = [dm[k] for k in sorted(dm, key=lambda k: order[k])]   # day order
                d["lag1"] = lag1(series)
                if len(series) >= BOOT_MIN_DAYS:
                    ms = boot_means(series)
                    d["boot"] = list(boot_interval(ms))
                    d["boot_bonferroni_high"] = boot_interval(ms, 0.0125, 0.9875)[1]
                d["bonferroni_t"] = t_quantile(0.0125, mg[2] - 1)
                d["bonferroni_clear"] = d["t"] is not None and d["t"] <= -d["bonferroni_t"]
        out[key] = d
    return out


def trading(rows, model, candles, days):
    """Taker and maker daily series (PLAN7 section 4, T), plus the maker arm on raw v3 as a descriptive placebo."""
    def taker_value(r):
        tk, _ = signals(corrected(r["p"], model), r["bid"], r["ask"])
        return None if tk is None else pnl(tk[0], tk[1], r["result"], taker_fee(tk[1]))

    def maker_with(fc):
        def value(r):
            _, mk = signals(fc(r), r["bid"], r["ask"])
            if mk is None:
                return None
            cs = candles.get(r["ticker"])   # None: no candles ever came (listed; counts as unfilled)
            e = fill_time(mk[0], mk[1], mk[2], r["ts"], r["start"], cs) if cs else None
            return None if e is None else pnl(mk[0], mk[1], r["result"])
        return value

    out = {}
    for key, value in (("taker", taker_value), ("maker", maker_with(lambda r: corrected(r["p"], model))),
                       ("maker_raw_v3", maker_with(lambda r: r["p"]))):
        by = {d: 0.0 for d in days}
        n = 0
        for r in rows:
            v = value(r)
            if v is not None:
                by[r["day"]] += v
                n += 1
        x = [by[d] for d in days]
        m, se = mean_se(x)
        d = dict(days=len(x), contracts=n, mean=m, se=se, total=sum(x))
        if len(x) >= BOOT_MIN_DAYS:
            ms = boot_means(x)
            d["boot"] = list(boot_interval(ms))
            d["boot_bonferroni_low"] = boot_interval(ms, 0.0125, 0.9875)[0]
        out[key] = d
    return out


def score(c, look, model, ended=None, today=None, out_dir=None, folder=None):
    """One of the two looks (PLAN7 section 5). Returns (result dict or None, message)."""
    out_dir = out_dir or RESULTS
    today = today or bot_date(time.time())
    if look not in LOOKS:
        return None, "the plan has two looks only: %s" % ", ".join(map(str, LOOKS))
    target = os.path.join(out_dir, "plan7_score_%d.json" % look)
    if os.path.exists(target):
        return None, "look %d was already taken (%s); each look is taken once" % (look, target)
    versions = allowed_versions(model, os.path.join(out_dir, "plan7_versions.json"))
    allr = [r for r in forward_rows(c, versions).values() if r["result"] and r["day"] <= BACKSTOP]
    days = sorted({r["day"] for r in allr})
    early = None
    if look == LOOKS[1]:
        first = jsonio.load(os.path.join(out_dir, "plan7_score_%d.json" % LOOKS[0]))
        if first and not first["verdict"].startswith("continue"):
            return None, "the test stopped at its futility look (%s); there is no final look" % first["verdict"]
        if len(days) >= LOOKS[0] and not first:
            return None, "take the futility look first (--look %d)" % LOOKS[0]
        if len(days) < look:
            if ended:
                early = "v3 logging ended early (%s)" % ended
            elif today >= BACKSTOP_LOOK:
                early = "fewer than %d forward market days on or before the backstop date %s" % (look, BACKSTOP)
            else:
                return None, "early look refused: %d forward market days so far, %d needed" % (len(days), look)
    elif len(days) < look:
        return None, "early look refused: %d forward market days so far, %d needed" % (len(days), look)
    days = days[:look]
    keep = set(days)
    rows = sorted((r for r in allr if r["day"] in keep), key=lambda r: (r["day"], r["ticker"]))
    unresolved = [r for r in forward_rows(c, versions).values() if days and r["day"] <= days[-1] and not r["result"]]
    recent = [r["ticker"] for r in unresolved if (today - r["day"]).days < RESULTS_PENDING_DAYS]
    if recent:
        return None, "results still pending for %d markets of the counted days; take the look once they settle" % len(recent)
    candles, none, missing = {}, [], []
    for d in days:
        st = load_day(d, folder)
        candles.update(st["candles"])
        none += st["none"]
    for r in rows:
        if r["ticker"] not in candles and r["ticker"] not in none and any(
                signals(f, r["bid"], r["ask"])[1] for f in (corrected(r["p"], model), r["p"])):
            missing.append(r["ticker"])
    if missing:
        return None, "candles not stored yet for %d markets: run plan7.py candles first" % len(missing)
    excluded = {}
    forward_rows(c, versions, excluded, keep)
    res = dict(plan=PLAN, look=look, scored=clock.iso(), first_day=str(days[0]) if days else None,
               last_day=str(days[-1]) if days else None, days=len(days), markets=len(rows), excluded=excluded,
               no_candles=sorted(t for t in none if t in {r["ticker"] for r in rows}),
               left_out_no_result=sorted(r["ticker"] for r in unresolved),
               model=dict(a=model["a"], b=model["b"], rows_sha256=model["rows_sha256"],
                          fit_rows_outside_window=model.get("outside_window"), versions=sorted(versions)),
               accuracy=accuracy(rows, model), trading=trading(rows, model, candles, days))
    a, mk = res["accuracy"]["A"], res["trading"]["maker"]
    if look == LOOKS[0]:
        stop = not (a.get("mean") is not None and a["mean"] < 0) or not (mk["mean"] is not None and mk["mean"] > 0)
        res["verdict"] = ("stop: no edge demonstrated (futility look)" if stop
                          else "continue to the final look at %d forward market days" % LOOKS[1])
    elif early:
        res["verdict"] = "not confirmed: %s (fail closed, CLAUDE.md section 11a)" % early
    else:
        ok = (a["reading"].startswith("the corrected forecast was clearly more accurate") and "boot" in a and a["boot"][1] < 0
              and "boot" in mk and mk["boot"][0] > 0)
        res["verdict"] = ("correction confirmed on paper (paper only: real money needs the user's explicit rule change)"
                          if ok else "no edge demonstrated: the idea stops (CLAUDE.md section 11a)")
        if ok:
            res["bonferroni"] = ("also passes at 1.25%% one-sided (the airport-forecast test runs on the same markets): %s"
                                 % ("yes" if a.get("bonferroni_clear") and a.get("boot_bonferroni_high", 1) < 0
                                    and mk.get("boot_bonferroni_low", -1) > 0 else "no"))
    jsonio.save(target, res)
    with open(target[:-5] + ".md", "w", encoding="utf-8") as f:
        f.write(markdown(res))
    return res, res["verdict"]


def markdown(res):
    def fmt(d):
        if d.get("mean") is None:
            return d.get("reading", "n/a")
        s = "%s (mean %+.4f, SE %.4f, %d days, interval %+.4f to %+.4f" % (
            d["reading"], d["mean"], d["se"], d["days"], d["low"], d["high"])
        if "boot" in d:
            s += "; 7-day block bootstrap 95%%: %+.4f to %+.4f" % tuple(d["boot"])
        if d.get("lag1") is not None:
            s += "; day-to-day correlation %+.2f" % d["lag1"]
        return s + ")"
    L = ["# PLAN7 look at %d forward market days" % res["look"], "",
         "Research and paper only (%s). Scored %s on %d market days (%s to %s), %d markets." % (
             res["plan"], res["scored"], res["days"], res["first_day"], res["last_day"], res["markets"]), "",
         "**Verdict:** %s" % res["verdict"]]
    if "bonferroni" in res:
        L.append("**Read together with the airport-forecast test:** %s" % res["bonferroni"])
    L += ["", "- A (primary, corrected forecast vs Kalshi): " + fmt(res["accuracy"]["A"]),
          "- A2 (v3 vs Kalshi, descriptive): " + fmt(res["accuracy"]["A2"]),
          "- A3 (corrected vs v3, descriptive): " + fmt(res["accuracy"]["A3"])]
    for k, lab in (("maker", "maker (primary for trading)"), ("taker", "taker (never decisive)"),
                   ("maker_raw_v3", "maker on raw v3 (placebo, descriptive)")):
        t = res["trading"][k]
        L.append("- %s: %d contracts, %s per market day%s" % (
            lab, t["contracts"], "n/a" if t["mean"] is None else "%+.1f cents (SE %.1f)" % (100 * t["mean"], 100 * t["se"]),
            ("; bootstrap 95%%: %+.1f to %+.1f cents" % (100 * t["boot"][0], 100 * t["boot"][1])) if "boot" in t else ""))
    if res["excluded"]:
        L.append("- Rows not counted, by reason: " + ", ".join("%s %d" % kv for kv in sorted(res["excluded"].items())))
    if res["no_candles"]:
        L.append("- Markets with no candles (counted as unfilled): " + ", ".join(res["no_candles"]))
    if res["model"].get("fit_rows_outside_window"):
        L.append("- The fit used %d markets logged outside the scan window (forward rows are always inside it)."
                 % res["model"]["fit_rows_outside_window"])
    L += ["", "Paper fills are optimistic (no queue sizes); cities on one day share weather, so the effective sample is"
          " the number of days. Even a confirmed result is paper only."]
    return "\n".join(L) + "\n"


# ---------- 5. status and the settle job's entry ----------
def status(c, model, folder=None):
    """Counts only, never an outcome-based number (PLAN7 section 5: no look between the two). Rows not counted are
    shown by reason, so a code change that stops the forward data shows the next day, not at the look."""
    ex = {}
    rows = list(forward_rows(c, allowed_versions(model) if model else None, ex).values())
    resolved = [r for r in rows if r["result"]]
    days = sorted({r["day"] for r in resolved})
    stored = 0
    for d in sorted({r["day"] for r in rows}):
        st = load_day(d, folder)
        stored += sum(1 for r in rows if r["day"] == d and (r["ticker"] in st["candles"] or r["ticker"] in st["none"]))
    nxt = next((k for k in LOOKS if len(days) < k), None)
    raw = jsonio.load(MODEL) or {}
    if "failed" in raw:
        return "PLAN7 (research, not in gate): the fit failed, so the test does not run: %s" % raw["failed"]
    return ("PLAN7 (research, not in gate): model %s; %d forward market days with results, %d markets; candles stored for"
            " %d of %d; %s" % (
                "a=%.3f b=%.3f (frozen)" % (model["a"], model["b"]) if model else "not fitted yet",
                len(days), len(resolved), stored, len(rows),
                "next look at %d forward market days" % nxt if nxt else "both looks' day counts reached")) + (
        "; rows not counted: %s" % ", ".join("%s %d" % kv for kv in sorted(ex.items())) if ex else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN7: v3 with its rain lean corrected (research/PLAN7.md)")
    ap.add_argument("cmd", choices=("candles", "fit", "status", "score", "auto"))
    ap.add_argument("--db", default=None)
    ap.add_argument("--look", type=int, default=None)
    ap.add_argument("--ended", default=None, help="why v3 logging ended (final look only; reads 'not confirmed')")
    a = ap.parse_args(argv)
    c = connect_ro(a.db or default_db())
    try:
        if a.cmd == "auto":   # the settle job: never fails it
            model = None
            for step in ("candles", "fit", "status"):   # each step on its own: one failing never skips the others
                try:
                    if step == "candles":
                        n, _ = store_candles(c)
                        if n:
                            print("PLAN7: candles stored for %d forward markets" % n)
                    elif step == "fit":
                        model, msg = fit(c)
                        if not msg.startswith("already fitted"):
                            print("PLAN7: " + msg)
                    else:
                        print(status(c, model))
                except Exception as ex:
                    print("PLAN7 %s failed (research only; nothing else is affected): %r" % (step, ex))
            return 0
        if a.cmd == "candles":
            n, wait = store_candles(c)
            print("PLAN7: candles stored for %d markets, %d waiting" % (n, wait))
            return 0
        if a.cmd == "fit":
            model, msg = fit(c)
            print("PLAN7: " + msg)
            return 0 if model else 2
        model = load_model()
        if a.cmd == "status":
            print(status(c, model))
            return 0
        if not model:
            print("PLAN7: no usable model (not fitted yet, or the fit failed: see %s)" % MODEL)
            return 2
        if a.look is None:
            ap.error("score needs --look 60 or --look 110")
        res, msg = score(c, a.look, model, ended=a.ended)
        print("PLAN7: " + msg)
        return 0 if res else 2
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
