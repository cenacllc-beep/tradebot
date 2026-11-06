"""PLAN8: Kalshi's price first, the airport forecast as a small correction. Research only; follows research/PLAN8.md,
written 2026-11-06 before any of its forward data.

A logistic mix, logit(q) = a + b_m * logit(m) + b_s * logit(s), of Kalshi's mid price m and the calibrated airport
forecast s (stationfc.py) is fitted once on research/PLAN.md's 1,711 past markets and frozen. It is then judged on new
market days from FORWARD_FIRST: is it more accurate (the gate's day-mean Brier statistic) than the price, and is the
gain the forecast's rather than a recalibration of the price (the control, logit(q0) = a0 + c * logit(m))?

Commands:
- fit: once, on the PC (research/data holds the past data); frozen in research/results/plan8_model.json, copied off
  the folder, never refitted.
- status: counts only; no outcome-based number.
- score --look 60|110 [--ended REASON]: the plan's two looks, run by hand, each once (plan section 5).
- auto: the settle job's step (run.bat settle): restores a lost or damaged model from the off-folder copy (or makes that
  copy when it is missing) and prints the status line. It never fits, never scores and never fails the job.

Boundaries:
- paper.db (the PC's, never the cloud trial copy) is opened read-only; only v4_obs (shadow.py's nightly airport-forecast
  log) and market_results (results missing from v4_obs, and the settle check) are read;
- it writes only research/results/plan8_model.json and plan8_score_<look>.json/.md, plus their off-folder copies (never
  replaced once written);
- no network; it places nothing and has no trading rule; nothing here can reach live.py.

The day statistics, bootstrap, t quantile and window test are PLAN7's pinned copies, imported from research/plan7.py.
Their source text is hashed (Python's ast module, line endings normalized) and must equal PINNED_PLAN7, so a later
change to PLAN7 cannot change how this test is judged; tests/test_plan8.py checks the pins.

  python research/plan8.py fit|status|auto [--db PAPER_DB]
  python research/plan8.py score --look 60|110 [--ended "why the nightly log ended"] [--db PAPER_DB]
Python 3.8+, standard library (fit also imports stationfc.py, which imports requests)."""
import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tbcommon import clock, jsonio   # noqa: E402  (file input and output only, never the rule)
import plan7 as P7   # noqa: E402  (pinned functions only; see PINNED_PLAN7)

PLAN = "research/PLAN8.md"
FORWARD_FIRST = date(2026, 11, 7)      # the first forward market day (its scan begins 8:55 PM on Nov 6, after the freeze)
BACKSTOP = date(2027, 6, 30)           # market days after this date never count
BACKSTOP_LOOK = date(2027, 7, 7)       # from here, a final look short of 110 counted days reads "not confirmed"
LOOKS = (60, 110)
EPS = 0.01                             # logit inputs and the mix's output clipped to [EPS, 1 - EPS]
MAX_SPREAD = 0.06                      # ask - bid at most 6c (the bot's and research/PLAN.md's quote rule)
PRIMARY = (50 * 60, 90 * 60)           # counted: logged 00:50 (incl.) to 01:30 UTC (excl.) on the market day (plan section 3)
MIN_FIT_MARKETS, MIN_FIT_DAYS, MAX_STEPS = 1000, 50, 50
HOLDOUT = (1711, 81)                   # research/PLAN.md's holdout: the fit refuses any other data (plan section 2)
BOOT_MIN_DAYS = 14
RESULTS_PENDING_DAYS = 7
BONF = 0.025 / 3                       # three forward tests on the same markets (plan section 7)

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data")
MODEL = os.path.join(RESULTS, "plan8_model.json")
AMEND = os.path.join(RESULTS, "plan8_amendments.json")

# ---------- code identity (plan section 3) ----------
REUSED = ("tcrit", "day_means", "margin", "boot_means", "boot_interval", "_betacf", "t_upper", "t_quantile",
          "market_day", "midnight", "in_window", "clip", "logit", "sigmoid", "mean_se", "lag1", "reading", "connect_ro",
          "default_db", "bot_date")
PINNED_PLAN7 = {   # research/plan7.py as frozen on 2026-11-05 (SHA-256 of each function's source; tests/test_plan8.py)
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
FORECAST = [("stationfc.py", n) for n in ("sig", "logit", "num", "evening_run", "features", "predict", "load_coef")] + [
    ("shadow.py", "v4_log"), ("shadow.py", "_t"), ("kalshi.py", "quote"), ("kalshi.py", "_p")]
FROZEN_FILES = ("research/plan8.py", "research/PLAN8.md")   # this plan's own rule and text, checked at each look


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_hash(path, name):
    """SHA-256 of a top-level function's source text (line endings normalized), or None when it is not there."""
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
    """{name: sha} of the PLAN7 functions and constants this plan reuses."""
    p = os.path.join(root, "research", "plan7.py")
    out = {"research/plan7.py:%s" % n: source_hash(p, n) for n in REUSED}
    out["research/plan7.py:constants"] = _sha(json.dumps(dict(
        T975=sorted(P7.T975.items()), EPS=P7.EPS, WINDOW=list(P7.WINDOW), BOOT_BLOCK=P7.BOOT_BLOCK,
        BOOT_DRAWS=P7.BOOT_DRAWS, BOOT_SEED=P7.BOOT_SEED, BOT_TZ=str(P7.BOT_TZ)), sort_keys=True))
    return out


def file_hash(path):
    """SHA-256 of a text file with line endings normalized, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            return _sha(f.read().replace("\r\n", "\n"))
    except (OSError, ValueError):
        return None


def forecast_identity(root=ROOT):
    """{name: sha} stored at the fit and checked at each look: the airport forecast's code, the functions that log it and
    its prices, its frozen coefficients, and this plan's own code and text (plan section 3)."""
    out = {"%s:%s" % (f, n): source_hash(os.path.join(root, f), n) for f, n in FORECAST}
    out.update({"file:%s" % f: file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES})
    coef = _read_json(os.path.join(root, "research", "results", "rain_model.json"))[0]
    coef = coef.get("coef") if isinstance(coef, dict) else None
    out["research/results/rain_model.json:coef"] = _sha(json.dumps(coef)) if coef else None
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


def amended(path=None):
    """{(name, sha)} accepted by a recorded amendment (research/results/plan8_amendments.json; plan section 3). Nothing
    in this file writes that list. A damaged list accepts nothing."""
    a = _read_json(path or AMEND)[0]
    a = a if isinstance(a, dict) else {}
    return {(x.get("name"), x.get("sha256")) for x in a.get("amendments", []) if x.get("name") and x.get("sha256")}


def identity_problems(model=None, root=ROOT, amend_path=None):
    """Names whose code differs from what this plan was frozen with (PINNED_PLAN7) or fitted with (the model's
    stored forecast identity), and is not covered by an amendment. [] when everything holds."""
    ok = amended(amend_path)
    bad = [k for k, v in plan7_identity(root).items() if (v is None or v != PINNED_PLAN7.get(k)) and (k, v) not in ok]
    if model is not None:
        want = model.get("identity") or {}
        bad += [k for k, v in forecast_identity(root).items() if (v is None or v != want.get(k)) and (k, v) not in ok]
    return sorted(bad)


# ---------- small helpers ----------
def offsite():
    """The off-folder backup location backup.py uses (TRADEBOT_OFFSITE_BACKUPS, else Documents\\tradebot_backups)."""
    return os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups")


def offsite_path(path):
    return os.path.join(offsite(), "plan8", "results", os.path.basename(path))


def keep_offsite(path):
    """Copy a written file off the folder unless a copy is already there (a frozen result is never replaced). Returns
    an error message or None."""
    saved = offsite_path(path)
    if os.path.exists(saved):
        return None
    try:
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        shutil.copy2(path, saved)
        return None
    except OSError as ex:
        return "PLAN8: off-folder copy of %s failed (%s)" % (os.path.basename(path), ex)


def L(p):
    return P7.logit(P7.clip(p))


def mix(m, s, model):
    """The frozen mix q (plan section 2)."""
    return P7.clip(P7.sigmoid(model["a"] + model["b_m"] * L(m) + model["b_s"] * L(s)))


def control(m, model):
    """The frozen control q0: the price recalibrated alone."""
    return P7.clip(P7.sigmoid(model["a0"] + model["c"] * L(m)))


def solve(A, b):
    """x with A x = b by Gaussian elimination with partial pivoting, or None when A is singular."""
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


def fit_logit(X, Y, start, steps=MAX_STEPS, tol=1e-10):
    """Maximum-likelihood weights for P(y=1) = sigmoid(w . x) by Newton's method from start: (weights, steps), or
    None when it does not converge (for example perfect separation) or the curvature is singular."""
    w = list(start)
    k = len(w)
    for it in range(steps):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for x, y in zip(X, Y):
            p = P7.sigmoid(sum(a * b for a, b in zip(w, x)))
            r, v = y - p, p * (1.0 - p)
            for i in range(k):
                g[i] += r * x[i]
                for j in range(k):
                    H[i][j] += v * x[i] * x[j]
        step = solve(H, g)
        if step is None:
            return None
        w = [a + s for a, s in zip(w, step)]
        if not all(math.isfinite(a) for a in w):
            return None
        if max(abs(s) for s in step) < tol:
            return w, it + 1
    return None


def clustered_se(X, Y, groups, w):
    """Day-clustered (sandwich) standard errors of the weights, with the G/(G-1) correction: descriptive only."""
    k = len(w)
    H = [[0.0] * k for _ in range(k)]
    score = {}
    for x, y, g in zip(X, Y, groups):
        p = P7.sigmoid(sum(a * b for a, b in zip(w, x)))
        v = p * (1.0 - p)
        s = score.setdefault(g, [0.0] * k)
        for i in range(k):
            s[i] += (y - p) * x[i]
            for j in range(k):
                H[i][j] += v * x[i] * x[j]
    inv = []
    for i in range(k):
        e = [1.0 if j == i else 0.0 for j in range(k)]
        col = solve(H, e)
        if col is None:
            return None
        inv.append(col)
    inv = [[inv[j][i] for j in range(k)] for i in range(k)]   # columns -> matrix
    meat = [[sum(s[i] * s[j] for s in score.values()) for j in range(k)] for i in range(k)]
    G = len(score)
    adj = G / (G - 1.0) if G > 1 else 1.0
    out = []
    for i in range(k):
        v = sum(inv[i][a] * meat[a][b] * inv[b][i] for a in range(k) for b in range(k))
        out.append(math.sqrt(max(adj * v, 0.0)))
    return out


def brier(pairs):
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


# ---------- 1. the fit (once, on past data) ----------
def fit_rows(jsonl=None, runs=None, coef=None):
    """[(ticker, day, m, s, y)] of research/PLAN.md's holdout rows (plan section 2), each ticker once (its first line),
    and a count of rows where the archive's formula (research/backtest.py) and the live one (stationfc.py) disagree
    (0 expected)."""
    import stationfc
    import backtest as B   # research/backtest.py: its archive loaders and formula, read-only use
    jsonl = jsonl or os.path.join(DATA, "kalshi_rain.jsonl")
    runs = B.load_nbs() if runs is None else runs
    coef = coef or stationfc.load_coef()
    if not coef:
        raise SystemExit("no airport-forecast coefficients (research/results/rain_model.json)")
    rows, disagree, seen = [], 0, set()
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            x = json.loads(line)
            bid, ask, r = x.get("scan_bid"), x.get("scan_ask"), x.get("result")
            if bid is None or ask is None or not (0 <= bid < ask <= 1) or ask - bid > MAX_SPREAD + 1e-9 or r not in ("yes", "no"):
                continue
            if x["ticker"] in seen:
                continue
            day = datetime.strptime(x["day"][:10], "%Y-%m-%d").date()
            run = runs.get((x["station"], day - timedelta(days=1)))
            feat = stationfc.features(run, day) if run else None
            if not feat:
                continue
            seen.add(x["ticker"])
            s = stationfc.predict(coef, feat)
            fb = B.features(runs, x["station"], day)
            if fb is None or abs(B.C(coef, fb) - s) > 1e-12:
                disagree += 1
            rows.append((x["ticker"], day, (bid + ask) / 2, s, 1.0 if r == "yes" else 0.0))
    return sorted(rows), disagree


def rows_hash(rows):
    return _sha(json.dumps([[t, str(d), round(m, 6), round(s, 9), y] for t, d, m, s, y in rows], separators=(",", ":")))


def first_window(day=None):
    """When the first forward market day's primary window opens (00:50 UTC on FORWARD_FIRST): the fit must come before."""
    return P7.midnight(day or FORWARD_FIRST) + PRIMARY[0]


def fit(model_path=None, rows=None, disagree=0, now=None, root=ROOT, expect=HOLDOUT):
    """Fit and freeze the mix and the control once (plan section 2). Returns (model dict or None, message).

    Nothing is saved when the data is not research/PLAN.md's holdout (expect: its markets and days, with 0 formula
    disagreements), when the first forward window has opened, or when PLAN7's shared code differs from the pins: those
    are fixable. Only a fit that does not converge or gives a weight that is not positive is frozen as failed."""
    model_path = model_path or MODEL
    msg = ensure_model(model_path)
    if msg:
        print(msg)
    if os.path.exists(model_path):
        m, ok = _read_json(model_path)
        if not ok or not isinstance(m, dict):
            return None, "the frozen model %s is damaged and no good off-folder copy exists; restore it by hand" % model_path
        if "failed" in m:
            return None, "the fit failed earlier and that is frozen, so the test does not run: %s" % m["failed"]
        return m, "already fitted (frozen; never refitted)"
    now = time.time() if now is None else now
    if now >= first_window():
        return None, ("too late: the first forward window (%s, 00:50 UTC) has opened; FORWARD_FIRST must move first (plan"
                      " section 3); nothing saved" % FORWARD_FIRST)
    bad = identity_problems(None, root)
    if bad:
        return None, "PLAN7's shared code differs from this plan's pins (%s); nothing saved" % ", ".join(bad)
    if rows is None:
        rows, disagree = fit_rows()
    days = sorted({d for _, d, _, _, _ in rows})
    if expect and ((len(rows), len(days)) != tuple(expect) or disagree):
        return None, ("the fit data is not research/PLAN.md's holdout: %d markets on %d days with %d formula disagreements"
                      " (%d on %d with 0 expected); nothing saved" % (len(rows), len(days), disagree, expect[0], expect[1]))
    if len(rows) < MIN_FIT_MARKETS or len(days) < MIN_FIT_DAYS:
        return None, "too few markets or days (%d markets, %d days; %d and %d needed); nothing saved" % (
            len(rows), len(days), MIN_FIT_MARKETS, MIN_FIT_DAYS)
    X = [[1.0, L(m), L(s)] for _, _, m, s, _ in rows]
    X0 = [[1.0, L(m)] for _, _, m, _, _ in rows]
    Y = [y for _, _, _, _, y in rows]
    base = dict(plan=PLAN, forward_first=str(FORWARD_FIRST), eps=EPS, markets=len(rows), days=len(days),
                first_day=str(days[0]), last_day=str(days[-1]), rows_sha256=rows_hash(rows), formula_disagreements=disagree,
                form="logit(q) = a + b_m * L(m) + b_s * L(s); control logit(q0) = a0 + c * L(m); "
                     "L(x) = logit(clip(x, %g, %g)); q and q0 clipped to the same range" % (EPS, 1 - EPS),
                fitted_ts=now, fitted=clock.iso(now), identity=forecast_identity(root),
                code_sha256={f: P7.file_sha256(os.path.join(root, f)) for f in ("stationfc.py", "shadow.py",
                                                                                  "research/backtest.py", "research/plan8.py")})
    r1, r0 = fit_logit(X, Y, (0.0, 1.0, 0.0)), fit_logit(X0, Y, (0.0, 1.0))
    if r1 is None or r0 is None:
        base["failed"] = "Newton's method did not converge in %d steps (%s)" % (MAX_STEPS, "mix" if r1 is None else "control")
    else:
        (a, bm, bs), st = r1
        (a0, c), st0 = r0
        base.update(a=a, b_m=bm, b_s=bs, a0=a0, c=c, steps=st, steps_control=st0)
        if not (bm > 0 and bs > 0):
            base["failed"] = "a weight is not positive (b_m = %.4f, b_s = %.4f)" % (bm, bs)
    if "failed" not in base:   # descriptive checks, stored with the frozen model
        groups = [d for _, d, _, _, _ in rows]
        base["se_clustered"] = dict(mix=clustered_se(X, Y, groups, [base["a"], base["b_m"], base["b_s"]]),
                                    control=clustered_se(X0, Y, groups, [base["a0"], base["c"]]))
        weeks = sorted({d.isocalendar()[:2] for d in days})
        lowo = []
        for wk in weeks:
            keep = [i for i, d in enumerate(groups) if d.isocalendar()[:2] != wk]
            r = fit_logit([X[i] for i in keep], [Y[i] for i in keep], (0.0, 1.0, 0.0))
            if r is not None:
                lowo.append(r[0])
        if lowo:
            base["leave_one_week_out"] = dict(fits=len(lowo), **{k: [min(x[i] for x in lowo), max(x[i] for x in lowo)]
                                                                  for i, k in enumerate(("a", "b_m", "b_s"))})
        base["brier_in_sample"] = dict(
            price=brier([(m, y) for _, _, m, _, y in rows]), forecast=brier([(s, y) for _, _, _, s, y in rows]),
            mix=brier([(mix(m, s, base), y) for _, _, m, s, y in rows]),
            control=brier([(control(m, base), y) for _, _, m, _, y in rows]))
    jsonio.save(model_path, base)
    err = keep_offsite(model_path)   # frozen: an existing off-folder model is never replaced
    if err:
        print(err)
    if "failed" in base:
        return None, "fit failed, so the test does not run: %s" % base["failed"]
    return base, "fitted and frozen: a=%.4f b_m=%.4f b_s=%.4f (control a0=%.4f c=%.4f) on %d markets, %d market days" % (
        base["a"], base["b_m"], base["b_s"], base["a0"], base["c"], len(rows), len(days))


def load_model(path=None):
    m, ok = _read_json(path or MODEL)
    return m if (ok and isinstance(m, dict) and m and "failed" not in m) else None


def ensure_model(path=None, now=None):
    """Keep the frozen model and its off-folder copy whole, never refitting (plan section 2):
    - a lost local copy is restored from the off-folder copy;
    - a damaged local copy is moved aside (renamed, never deleted) and restored, when the off-folder copy is good;
    - a missing off-folder copy is made from a good local one (an existing off-folder copy is never replaced).
    Returns a message, or None when nothing was done."""
    path = path or MODEL
    saved = offsite_path(path)
    local, lok = _read_json(path)
    off, ook = _read_json(saved)
    good_off = ook and isinstance(off, dict) and bool(off)
    try:
        if not os.path.exists(path) and good_off:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copy2(saved, path)
            return "PLAN8: the frozen model was missing here; restored from %s (never refitted)" % saved
        if os.path.exists(path) and not (lok and isinstance(local, dict) and local) and good_off:
            aside = "%s.damaged-%d" % (path, int(time.time() if now is None else now))
            os.replace(path, aside)
            shutil.copy2(saved, path)
            return "PLAN8: the frozen model here was damaged (kept as %s); restored from %s" % (aside, saved)
        if lok and isinstance(local, dict) and local and not os.path.exists(saved):
            err = keep_offsite(path)
            return err or "PLAN8: the off-folder copy of the frozen model was missing; made it from this folder's copy"
    except OSError as ex:
        return "PLAN8: could not repair the frozen model or its off-folder copy (%s)" % ex
    return None


# ---------- 2. forward rows ----------
def in_primary(ts, day):
    """Logged inside the primary window: 00:50 to 01:30 UTC on the market day, 8:50 to 9:30 PM La Paz the evening before."""
    return PRIMARY[0] <= ts - P7.midnight(day) < PRIMARY[1]


def settle_records(c):
    """({ticker: result} and the newest recorded_ts) from paper.db's market_results, the settle's own record; ({}, None)
    when the table does not exist. Any other error (a lock) propagates."""
    try:
        got = c.execute("select ticker,result,recorded_ts from market_results").fetchall()
    except sqlite3.OperationalError as ex:
        if "no such table" in str(ex):
            return {}, None
        raise
    res = {t: r for t, r, _ in got if r in ("yes", "no")}
    ts = [x for _, _, x in got if isinstance(x, (int, float))]
    return res, (max(ts) if ts else None)


def forward_rows(c, excluded=None, only_days=None, late=False):
    """{ticker: row} of forward markets (plan section 3) from v4_obs: market day from FORWARD_FIRST to BACKSTOP, logged
    inside the primary window and before the day start, with a forecast and a usable quote. With late=True, markets
    logged later inside the scan window (01:30 to 05:00 UTC) are returned instead (the sensitivity reading). excluded, a
    dict, receives counts by reason of the rows passed over (for only_days when given). A result missing from v4_obs is
    taken from market_results."""
    ex = excluded if excluded is not None else {}
    settled, _ = settle_records(c)
    out = {}
    for t, ts, fc, bid, ask, start, result in c.execute(
            "select ticker,ts,fc,bid,ask,start_ts,result from v4_obs order by ts,ticker"):
        d = P7.market_day(t)
        if d is None or d < FORWARD_FIRST or t in out:
            continue
        why = ("after_backstop" if d > BACKSTOP else
               "no_day_start" if start is None else
               "outside_window" if ts is None or not P7.in_window(ts, d) else
               "late_window" if not in_primary(ts, d) else
               "after_day_start" if ts >= start else
               "no_forecast" if fc is None else
               "spread" if bid is None or ask is None or not (0 <= bid < ask <= 1 and ask - bid <= MAX_SPREAD + 1e-9) else None)
        if late:   # the sensitivity rows: logged late, otherwise usable
            if why != "late_window" or ts >= start or fc is None or bid is None or ask is None or not (
                    0 <= bid < ask <= 1 and ask - bid <= MAX_SPREAD + 1e-9):
                continue
            why = None
        if why:
            if only_days is None or d in only_days:
                ex[why] = ex.get(why, 0) + 1
            continue
        r = result if result in ("yes", "no") else settled.get(t)
        out[t] = dict(ticker=t, day=d, ts=ts, s=float(fc), bid=float(bid), ask=float(ask), m=(float(bid) + float(ask)) / 2,
                      result=r)
    return out


# ---------- 3. the looks ----------
def _reading_stats(o, better, worse, order, boot=True):
    mg = P7.margin(o)
    d = dict(reading=P7.reading(mg, better, worse))
    if mg:
        tc = P7.tcrit(mg[2])
        d.update(mean=mg[0], se=mg[1], days=mg[2], tcrit=tc, low=mg[0] - tc * mg[1], high=mg[0] + tc * mg[1],
                 t=(mg[0] / mg[1]) if mg[1] else None)
        dm = P7.day_means(o)
        series = [dm[k] for k in sorted(dm, key=lambda k: order[k])]
        d["lag1"] = P7.lag1(series)
        if boot and len(series) >= BOOT_MIN_DAYS:
            ms = P7.boot_means(series)
            d["boot"] = list(P7.boot_interval(ms))
            d["boot_bonferroni_high"] = P7.boot_interval(ms, BONF, 1 - BONF)[1]
        d["bonferroni_t"] = P7.t_quantile(BONF, mg[2] - 1)
        d["bonferroni_clear"] = d["t"] is not None and d["t"] <= -d["bonferroni_t"]
        d["clear"] = d["reading"] == better and "boot" in d and d["boot"][1] < 0   # own line: reading and bootstrap
        d["three_test"] = bool(d["bonferroni_clear"] and d.get("boot_bonferroni_high", 1) < 0)
    return d


def accuracy(rows, model, late_rows=()):
    """A, B, A0 and A-late (plan section 4) and the pooled Brier scores."""
    q = [(r["ticker"], mix(r["m"], r["s"], model), control(r["m"], model), r["m"], r["s"], r["result"]) for r in rows]
    order = {x["ticker"].split("-")[1]: x["day"] for x in rows}
    y = lambda r: 1.0 if r == "yes" else 0.0   # noqa: E731
    return dict(
        A=_reading_stats([(t, qq, m, r) for t, qq, _, m, _, r in q], "the mix was clearly more accurate than Kalshi's prices",
                         "Kalshi's prices were clearly more accurate than the mix", order),
        B=_reading_stats([(t, qq, q0, r) for t, qq, q0, _, _, r in q], "the mix was clearly more accurate than the control",
                         "the control was clearly more accurate than the mix", order),
        A0=_reading_stats([(t, q0, m, r) for t, _, q0, m, _, r in q], "the control was clearly more accurate than Kalshi's prices",
                          "Kalshi's prices were clearly more accurate than the control", order, boot=False),
        A_late=_late(rows, late_rows, model),
        pooled=dict(price=brier([(m, y(r)) for _, _, _, m, _, r in q]), forecast=brier([(s, y(r)) for _, _, _, _, s, r in q]),
                    mix=brier([(qq, y(r)) for _, qq, _, _, _, r in q]), control=brier([(q0, y(r)) for _, _, q0, _, _, r in q])))


def _late(rows, late_rows, model):
    """A on the same days with the late-window markets added (descriptive)."""
    allr = list(rows) + list(late_rows)
    order = {x["ticker"].split("-")[1]: x["day"] for x in allr}
    d = _reading_stats([(r["ticker"], mix(r["m"], r["s"], model), r["m"], r["result"]) for r in allr],
                       "the mix was clearly more accurate than Kalshi's prices",
                       "Kalshi's prices were clearly more accurate than the mix", order, boot=False)
    d["late_markets"] = len(late_rows)
    return d


def refit(rows):
    """The mix refitted on the counted forward markets (final look, descriptive; never used for the verdict)."""
    X = [[1.0, L(r["m"]), L(r["s"])] for r in rows]
    Y = [1.0 if r["result"] == "yes" else 0.0 for r in rows]
    got = fit_logit(X, Y, (0.0, 1.0, 0.0)) if len(rows) >= 30 else None
    return dict(zip(("a", "b_m", "b_s"), got[0])) if got else None


def rows_digest(rows):
    """SHA-256 of the counted markets' logged inputs (not their results): the futility look stores it for its days, and
    the final look checks that its first 60 days are the same markets (plan section 5)."""
    return _sha(json.dumps(sorted([r["ticker"], round(r["ts"], 3), round(r["s"], 9), r["bid"], r["ask"]] for r in rows),
                           separators=(",", ":")))


def score(c, look, model, ended=None, today=None, out_dir=None, root=ROOT, db=None):
    """One of the two looks (plan section 5). Returns (result dict or None, message). db: the database path, recorded."""
    out_dir = out_dir or RESULTS
    today = today or P7.bot_date(time.time())
    if look not in LOOKS:
        return None, "the plan has two looks only: %s" % ", ".join(map(str, LOOKS))
    if ended and look != LOOKS[1]:
        return None, "--ended applies to the final look only"
    target = os.path.join(out_dir, "plan8_score_%d.json" % look)
    if os.path.exists(target):
        return None, "look %d was already taken (%s); each look is taken once" % (look, target)
    if os.path.exists(offsite_path(target)):
        return None, ("look %d was already taken: its off-folder copy %s exists; restore it to %s (each look is taken once)"
                      % (look, offsite_path(target), out_dir))
    bad = identity_problems(model, root, os.path.join(out_dir, "plan8_amendments.json"))
    if bad:
        return None, ("code differs from what this plan was frozen or fitted with (%s); the look waits for an amendment "
                      "(plan section 3)" % ", ".join(bad))
    counted = forward_rows(c)
    days = sorted({r["day"] for r in counted.values()})   # the day set, fixed from counted markets (plan section 3)
    early = None
    if look == LOOKS[1]:
        first, ok = _read_json(os.path.join(out_dir, "plan8_score_%d.json" % LOOKS[0]))
        if not ok or (first is not None and not isinstance(first, dict)):
            return None, "the futility look's result file is damaged; restore it from %s" % offsite_path(
                os.path.join(out_dir, "plan8_score_%d.json" % LOOKS[0]))
        if first and not first["verdict"].startswith("continue"):
            return None, "the test stopped at its futility look (%s); there is no final look" % first["verdict"]
        if len(days) >= LOOKS[0] and not first:
            return None, "take the futility look first (--look %d)" % LOOKS[0]
        if len(days) < look:
            if ended:
                early = "the nightly airport-forecast log ended early (%s)" % ended
            elif today >= BACKSTOP_LOOK:
                early = "fewer than %d forward market days on or before the backstop date %s" % (look, BACKSTOP)
            else:
                return None, "early look refused: %d forward market days so far, %d needed" % (len(days), look)
    elif len(days) < look:
        return None, "early look refused: %d forward market days so far, %d needed" % (len(days), look)
    if look == LOOKS[1] and first:   # the final look's first 60 days must be the futility look's markets
        d60 = set(days[:LOOKS[0]])
        if rows_digest([r for r in counted.values() if r["day"] in d60]) != first.get("rows_sha256"):
            return None, ("the first %d forward days' markets differ from those the futility look used (another database, or"
                          " changed rows); the look waits for an amendment (plan section 5)" % LOOKS[0])
    days = days[:look]
    keep = set(days)
    if days and (today - days[-1]).days < RESULTS_PENDING_DAYS:
        return None, "the last counted day (%s) is fewer than %d days ago; take the look from %s" % (
            days[-1], RESULTS_PENDING_DAYS, days[-1] + timedelta(days=RESULTS_PENDING_DAYS))
    unresolved = sorted(r["ticker"] for r in counted.values() if r["day"] in keep and not r["result"])
    if unresolved:   # left out only after a settle ran past the 7-day mark (plan section 5)
        mark = P7.midnight(days[-1] + timedelta(days=RESULTS_PENDING_DAYS))
        _, newest = settle_records(c)
        if newest is None or newest < mark:
            return None, ("%d markets of the counted days have no result, and no settle has recorded a result since %s; "
                          "run the settle, then take the look" % (len(unresolved), days[-1] + timedelta(days=RESULTS_PENDING_DAYS)))
    rows = sorted((r for r in counted.values() if r["day"] in keep and r["result"]), key=lambda r: (r["day"], r["ticker"]))
    late = sorted((r for r in forward_rows(c, late=True).values() if r["day"] in keep and r["result"]),
                  key=lambda r: (r["day"], r["ticker"]))
    excluded = {}
    forward_rows(c, excluded, keep)
    res = dict(plan=PLAN, look=look, scored=clock.iso(), db=db, first_day=str(days[0]) if days else None,
               last_day=str(days[-1]) if days else None, days=len(days), markets=len(rows), excluded=excluded,
               left_out_no_result=unresolved, rows_sha256=rows_digest([r for r in counted.values() if r["day"] in keep]),
               model={k: model.get(k) for k in ("a", "b_m", "b_s", "a0", "c", "rows_sha256", "markets", "days")})
    if look == LOOKS[0]:   # the futility rule uses A's sign only, and only that is shown (plan section 5)
        mg = P7.margin([(r["ticker"], mix(r["m"], r["s"], model), r["m"], r["result"]) for r in rows]) if rows else None
        res["accuracy"] = dict(A=dict(mean=mg[0], days=mg[2]) if mg else dict(mean=None))   # no SE: no interim t
    else:
        res["accuracy"] = accuracy(rows, model, late) if rows else None
    a = (res["accuracy"] or {}).get("A") or {}
    if look == LOOKS[0]:
        stop = not (a.get("mean") is not None and a["mean"] < 0)
        res["verdict"] = ("stop: no edge demonstrated (futility look)" if stop
                          else "continue to the final look at %d forward market days" % LOOKS[1])
    elif early:
        res["verdict"] = "not confirmed: %s (fail closed, CLAUDE.md section 11a)" % early
        if res["accuracy"]:
            res["accuracy"]["B"] = dict(not_judged="B is judged only after A passes (plan section 5)")
    else:
        res["refit_descriptive"] = refit(rows)
        if a.get("clear"):   # 1. A, then 2. B only after A, then 3. the HRRR condition (plan section 5)
            b = res["accuracy"]["B"]
            share = "clear" if b.get("clear") else "not clear"
            res["hrrr_condition"] = bool(a.get("three_test") and b.get("clear") and b.get("three_test"))
            res["verdict"] = ("confirmed on paper: the mix was more accurate than Kalshi's prices; the forecast's own share"
                              " (against the control): %s; the HRRR condition (A and B at the three-test line): %s. Accuracy"
                              " only, not profit (plan section 8)" % (share, "met" if res["hrrr_condition"] else "not met"))
        else:
            res["verdict"] = "no edge demonstrated: the idea stops (CLAUDE.md section 11a)"
            if res["accuracy"]:
                res["accuracy"]["B"] = dict(not_judged="B is judged only after A passes (plan section 5)")
    jsonio.save(target, res)
    with open(target[:-5] + ".md", "w", encoding="utf-8") as f:
        f.write(markdown(res))
    for f in (target, target[:-5] + ".md"):
        err = keep_offsite(f)
        if err:
            print(err)
    return res, res["verdict"]


def markdown(res):
    def fmt(d):
        if d and d.get("not_judged"):
            return "not judged: " + d["not_judged"]
        if not d or d.get("mean") is None:
            return (d or {}).get("reading", "n/a")
        s = "%s (mean %+.4f, SE %.4f, %d days, interval %+.4f to %+.4f" % (
            d["reading"], d["mean"], d["se"], d["days"], d["low"], d["high"])
        if "boot" in d:
            s += "; 7-day block bootstrap 95%%: %+.4f to %+.4f" % tuple(d["boot"])
        if d.get("lag1") is not None:
            s += "; day-to-day correlation %+.2f" % d["lag1"]
        return s + ")"
    acc = res["accuracy"] or {}
    L_ = ["# PLAN8 look at %d forward market days" % res["look"], "",
          "Research only (%s). Scored %s on %d market days (%s to %s), %d markets." % (
              res["plan"], res["scored"], res["days"], res["first_day"], res["last_day"], res["markets"]), "",
          "**Verdict:** %s" % res["verdict"]]
    if res["look"] == LOOKS[0]:   # the futility look shows A's mean only (plan section 5)
        a = acc.get("A") or {}
        L_ += ["", "- A (the mix vs Kalshi's price), mean of the day means: %s; the futility rule uses only its sign" % (
            "%+.4f over %d days" % (a["mean"], a["days"]) if a.get("mean") is not None else "n/a")]
        if res["excluded"]:
            L_.append("- Rows not counted, by reason: " + ", ".join("%s %d" % kv for kv in sorted(res["excluded"].items())))
        if res["left_out_no_result"]:
            L_.append("- Left out without a result: " + ", ".join(res["left_out_no_result"]))
        return "\n".join(L_) + "\n"
    L_ += ["", "- A (primary, the mix vs Kalshi's price): " + fmt(acc.get("A")),
           "- B (attribution, the mix vs the price recalibrated alone): " + fmt(acc.get("B")),
           "- A0 (descriptive, the control vs Kalshi's price): " + fmt(acc.get("A0")),
           "- A-late (sensitivity, %d late-window markets added): " % (acc.get("A_late") or {}).get("late_markets", 0)
           + fmt(acc.get("A_late"))]
    for k in ("A", "B"):
        d = acc.get(k) or {}
        if d.get("mean") is not None and not d.get("not_judged"):
            L_.append("- %s at the three-test line (0.833%% one-sided, bootstrap 99.17%%): %s" % (k, "passes" if d.get("three_test") else "does not pass"))
    if res.get("refit_descriptive"):
        L_.append("- The mix refitted on these markets (descriptive, never the verdict): " + ", ".join(
            "%s %.3f" % kv for kv in res["refit_descriptive"].items()))
    if acc.get("pooled"):
        L_.append("- Pooled Brier: " + ", ".join("%s %.4f" % (k, v) for k, v in acc["pooled"].items() if v is not None))
    if res["excluded"]:
        L_.append("- Rows not counted, by reason: " + ", ".join("%s %d" % kv for kv in sorted(res["excluded"].items())))
    if res["left_out_no_result"]:
        L_.append("- Left out without a result: " + ", ".join(res["left_out_no_result"]))
    L_ += ["", "Accuracy only: this plan has no trading rule, and even a confirmed gain is far smaller than the edge a"
           " trade needs after the spread and fees. Cities on one day share weather, so the effective sample is the"
           " number of days."]
    return "\n".join(L_) + "\n"


# ---------- 4. status and the settle job's entry ----------
def status(c, model):
    """Counts only, never an outcome-based number (plan section 5). Rows not counted are shown by reason, so a code
    change that stops the forward data shows the next day, not at the look."""
    raw = _read_json(MODEL)[0]
    raw = raw if isinstance(raw, dict) else {}
    if "failed" in raw:
        return "PLAN8 (research, not in gate): the fit failed, so the test does not run: %s" % raw["failed"]
    ex = {}
    rows = list(forward_rows(c, ex).values())
    resolved = [r for r in rows if r["result"]]
    days = sorted({r["day"] for r in rows})   # the day set comes from counted markets, not results (plan section 3)
    nxt = next((k for k in LOOKS if len(days) < k), None)
    bad = identity_problems(model) if model else identity_problems(None)
    return ("PLAN8 (research, not in gate): model %s; %d forward market days logged, %d markets (%d with results); %s" % (
                "fitted (frozen)" if model else "not fitted yet: run research\\plan8.py fit",
                len(days), len(rows), len(resolved),
                "next look at %d forward market days" % nxt if nxt else "both looks' day counts reached")) + (
        "; rows not counted: %s" % ", ".join("%s %d" % kv for kv in sorted(ex.items())) if ex else "") + (
        "; CODE CHANGED: %s (the looks wait for an amendment)" % ", ".join(bad) if bad else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN8: Kalshi's price first, the airport forecast as a small correction")
    ap.add_argument("cmd", choices=("fit", "status", "score", "auto"))
    ap.add_argument("--db", default=None)
    ap.add_argument("--look", type=int, default=None)
    ap.add_argument("--ended", default=None, help="why the nightly log ended (final look only; reads 'not confirmed')")
    a = ap.parse_args(argv)
    if a.cmd == "fit":
        model, msg = fit()
        print("PLAN8: " + msg)
        return 0 if model else 2
    if a.cmd == "auto":   # the settle job: never fails it
        try:
            msg = ensure_model()
            if msg:
                print(msg)
            c = P7.connect_ro(a.db or P7.default_db())
            try:
                print(status(c, load_model()))
            finally:
                c.close()
        except (Exception, SystemExit) as ex:   # SystemExit: a missing paper.db (connect_ro refuses to create one)
            print("PLAN8 status failed (research only; nothing else is affected): %r" % (ex,))
        return 0
    c = P7.connect_ro(a.db or P7.default_db())
    try:
        model = load_model()
        if a.cmd == "status":
            print(status(c, model))
            return 0
        if not model:
            print("PLAN8: no usable model (not fitted yet, or the fit failed: see %s)" % MODEL)
            return 2
        if a.look is None:
            ap.error("score needs --look 60 or --look 110")
        res, msg = score(c, a.look, model, ended=a.ended, db=os.path.abspath(a.db or P7.default_db()))
        print("PLAN8: " + msg)
        return 0 if res else 2
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
