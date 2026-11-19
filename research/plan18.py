"""PLAN18 (research/PLAN18.md): five of the settlement index's exchanges read together (a median composite), a frozen
GARCH(1,1) volatility model and a PELT shift detector, on Kalshi's 15-minute BTC and ETH markets. Fit on windows
closing 2026-06-01 to 07-31, scored once on August 2026. Research and paper only: never part of the gate, never
connected to live.py, places nothing.

Stages (each refuses to run out of turn):
- freeze: identity record (SHA-256 of research/PLAN18.md, research/plan18.py, research/plan15.py, PLAN15's inspect.json,
  PLAN7's pinned functions) and the pinned package versions; stored once in research/results/plan18_identity.json.
- download [--max-days N] [--budget-minutes M]: per asset-day, the composite day file (exchanges' one-minute closes ->
  median, Coinbase's close, dispersion, count; single-exchange series never saved) and Kalshi's day file (PLAN15's
  build_day: market records, results, minute candles). May 31 to July 31 first; August only after the model exists.
- fit: once; Kalshi coverage check, GARCH per asset (composite and, for the descriptive comparison, Coinbase), then
  model M (and M without gap and dispersion on Coinbase); writes plan18_model.json.
- score: once, both assets (one Holm family); writes plan18_result.md, then plan18_result.json.
- status: counts only.

Network: ccxt (Bitstamp, Coinbase, Crypto.com, Bullish, Kraken public data, User-Agent tradebot-paper-research/1.0)
and Kalshi's public API through PLAN15. Packages: ccxt 4.5.85, arch 8.0.0, ruptures 1.1.10, installed on GitHub's
runner only (approved 2026-11-18).
  python research/plan18.py freeze|download|fit|score|status
Python 3.8+."""
import argparse
import http.client
import json
import math
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import plan15 as P   # noqa: E402
from tbcommon import jsonio   # noqa: E402

PLAN = "research/PLAN18.md"
PLAN_SHA256 = "717909c8aaa78c8d217747d1cd3f75d27a9da5067d4d206e83b4d1b872969cff"   # frozen 2026-11-18 (CHANGELOG)
FROZEN_FILES = ("research/PLAN18.md", "research/plan18.py", "research/plan15.py")
PINS = {"ccxt": "4.5.85", "arch": "8.0.0", "ruptures": "1.1.10"}
UA = "tradebot-paper-research/1.0"
ASSETS = P.ASSETS
SYMBOL = {"BTC": "BTC/USD", "ETH": "ETH/USD"}
OHLCV_EXCHANGES = ("bitstamp", "coinbase", "cryptocom", "bullish")
REQUIRED = ("bitstamp", "coinbase", "cryptocom")        # complete throughout (PROBE18); a failure means retry the day
TRADES_EXCHANGES = ("kraken",)
MIN_EXCHANGES = 3
T = P.T_MIN
FIT = (date(2026, 6, 1), date(2026, 7, 31))
TEST = (date(2026, 8, 1), date(2026, 8, 31))
FIRST_COMP_DAY = date(2026, 5, 31)                      # minutes before June 1's first windows (R needs 30 returns)
COVERAGE_MIN = 0.90
K_G = (2, 5, 10, 13)
K_R = (5, 10, 13)
K_M = (2, 5, 10, 13)
EDGE = 0.04
BAND = (0.20, 0.80)
R_N, R_MIN, R_LAST = 30, 3, 5
R_PEN = 3 * math.log(30)
R_CUT = 2.0
RIDGE = 1.0
CLIP_P = (0.005, 0.995)
FILL_DELAY = 1
LATE = (3, 5)
GUARD_FROM = -30
FAMILY = 0.025
T_FLOOR = 2.0
BOOT_BLOCK_DAYS, BOOT_DRAWS = 2, 20000
PLACEBO_DRAWS = 2000
SEED = 18
MIN_SIGNALS, MIN_DAYS = 200, 20
MAX_MISSING = 0.10
WINDOWS_PER_DAY = P.WINDOWS_PER_DAY
VERDICT_PASS = "lead on past data: justifies a forward paper test"
VERDICT_FAIL = "no edge shown"
NOT_TESTABLE = "not testable"

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(RESULTS, "plan18")
IDENTITY = os.path.join(RESULTS, "plan18_identity.json")
MODEL = os.path.join(RESULTS, "plan18_model.json")
RESULT = os.path.join(RESULTS, "plan18_result.json")


# ---------- identity ----------
def identity_now(root=ROOT):
    out = {f: P.file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES}
    out["research/results/plan15/inspect.json"] = P.file_hash(P.INSPECT)
    return out


def pin_problems():
    bad = []
    for name, want in PINS.items():
        try:
            mod = __import__(name)
            got = str(getattr(mod, "__version__", None) or "")
            got = got[1:] if got.startswith("v") else got   # ruptures reports "v1.1.10"
        except ImportError:
            got = None
        if got != want:
            bad.append("%s %s (pinned %s)" % (name, got, want))
    return bad


def identity_problems(root=ROOT, path=None, pins=True):
    rec, ok = P._read_json(path or IDENTITY)
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        bad.append("research/PLAN18.md differs from its frozen SHA-256")
    return bad + P.plan7_problems(root) + (pin_problems() if pins else [])


def freeze(root=ROOT, path=None, now=None):
    path = path or IDENTITY
    if os.path.exists(path):
        return None, "already frozen (%s); stored once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN18.md differs from its frozen SHA-256; nothing saved"
    p15 = P.identity_problems(root)
    if p15:
        return None, "PLAN15 is not frozen or differs from its record (%s); nothing saved" % ", ".join(p15)
    pb = pin_problems()
    if pb:
        return None, "packages differ from the pins (%s); nothing saved" % ", ".join(pb)
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, identity=identity_now(root), pins=PINS,
               frozen=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat())
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read"
    jsonio.save(path, rec)
    return rec, "frozen: %s" % path


# ---------- composite (plan section 1) ----------
PAGE_MINUTES = dict(bitstamp=1000, coinbase=300, cryptocom=300, bullish=100)   # ccxt's largest one-minute page
REQUIRED_MIN = 1430                                       # a required exchange must give this many of 1440 minutes
SHORT_TRIES = 3                                           # after this many short runs the day is saved as it is


class Short(RuntimeError):
    """A required exchange answered but gave fewer than REQUIRED_MIN minutes."""

    def __init__(self, name, n):
        RuntimeError.__init__(self, "%s returned only %d of 1440 minutes" % (name, n))
        self.name, self.n = name, n
_EX = {}


def _exchange(name):
    """One ccxt instance per exchange for the run (shares its rate limiter), markets loaded once."""
    if name not in _EX:
        import ccxt
        ex = getattr(ccxt, name)({"enableRateLimit": True, "userAgent": UA, "headers": {"User-Agent": UA}})
        ex.load_markets()
        _EX[name] = ex
    return _EX[name]


def _transient(ex):
    """True for network faults, timeouts and rate limits (the day is retried, never saved without the exchange)."""
    try:
        import ccxt
        return isinstance(ex, (ccxt.NetworkError, ccxt.ExchangeNotAvailable))
    except ImportError:
        return False


def ohlcv_closes(ex, sym, t0, t1, tries=3, page=1000):
    """{end of minute: close} for minutes ending in (t0, t1], from fetch_ohlcv paged by since (ccxt's timestamp is the
    minute's start, so the end is start + 60). An empty page (a gap) moves on by one page span, never ends the day."""
    out, since = {}, (t0) * 1000
    while since < t1 * 1000:
        rows = None
        for i in range(tries):
            try:
                rows = ex.fetch_ohlcv(sym, "1m", since=since, limit=page)
                break
            except Exception:   # noqa: BLE001  (retried, then raised)
                if i == tries - 1:
                    raise
                time.sleep(5 * (i + 1))
        rows = [r for r in rows or [] if r and r[0] is not None and r[0] >= since]
        if not rows:
            since += page * 60000   # a gap: try the next page span (gaps stay missing)
            continue
        for r in rows:
            end = int(r[0]) // 1000 + 60
            if t0 < end <= t1 and r[4] is not None:
                out[end] = float(r[4])
        nxt = int(rows[-1][0]) + 60000
        if nxt <= since:
            break
        since = nxt
    return out


def _idkey(r):
    i = r.get("id")
    try:
        return (0, int(i), "")
    except (TypeError, ValueError):
        return (1, 0, str(i))


def trade_closes(ex, sym, t0, t1, tries=3):
    """{end of minute: last trade price} for minutes ending in (t0, t1], from Kraken's public trades paged with its own
    `last` cursor (nanoseconds; ccxt appends it to the last row's info), starting at t0 in seconds; a trade at time t
    belongs to the minute ending at ceil(t / 60) x 60. Raises unless the pages reach past t1 (a day not fully covered
    has no closes); network faults are raised as they are."""
    last, seen, cursor = {}, set(), str(int(t0))
    while True:
        rows = None
        for i in range(tries):
            try:
                rows = ex.fetch_trades(sym, None, 1000, {"since": cursor})
                break
            except Exception:   # noqa: BLE001
                if i == tries - 1:
                    raise
                time.sleep(5 * (i + 1))
        rows = [r for r in rows or [] if r.get("timestamp") is not None]
        nxt = None
        raw = getattr(ex, "last_json_response", None)
        if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and raw["result"].get("last") is not None:
            nxt = str(raw["result"]["last"])             # Kraken's own cursor, independent of row order
        elif rows and isinstance(rows[-1].get("info"), list) and rows[-1]["info"]:
            nxt = str(rows[-1]["info"][-1])
        rows.sort(key=lambda r: (r["timestamp"],) + _idkey(r))
        for r in rows:
            k = (r.get("id"), r["timestamp"], r.get("price"))
            if k in seen:
                continue
            seen.add(k)
            t = r["timestamp"] / 1000.0
            end = int(math.ceil(t / 60.0)) * 60
            if t0 < end <= t1:
                prev = last.get(end)
                if prev is None or (r["timestamp"],) + _idkey(r) >= prev[0]:
                    last[end] = ((r["timestamp"],) + _idkey(r), float(r["price"]))
        top = max((r["timestamp"] for r in rows), default=None)
        if top is not None and top / 1000.0 > t1:
            return {e: v[1] for e, v in last.items()}
        cur_ns = int(cursor) * 10 ** 9 if len(cursor) <= 11 else int(cursor)   # the start is in seconds
        if not nxt or not nxt.isdigit() or int(nxt) <= cur_ns:
            raise RuntimeError("Kraken's trades stopped before the end of the day (day not fully covered)")
        cursor = nxt


def build_comp(asset, d, fetch=None, accept_short=False):
    """One asset-day's derived series: minute ends day_start + 60 .. day_start + 86400. fetch(name, t0, t1) ->
    {end: close} (tests replace it). A failure of a required exchange raises (the day is not saved); Bullish or
    Kraken failing leaves them absent (recorded)."""
    t0 = int(P.day_start(d))
    t1 = t0 + 86400
    if fetch is None:
        def fetch(name, a, b):
            ex = _exchange(name)
            if name in TRADES_EXCHANGES:
                return trade_closes(ex, SYMBOL[asset], a, b)
            return ohlcv_closes(ex, SYMBOL[asset], a, b, page=PAGE_MINUTES[name])
    closes, absent = {}, {}
    for name in OHLCV_EXCHANGES + TRADES_EXCHANGES:
        try:
            closes[name] = fetch(name, t0, t1)
        except Exception as ex:   # noqa: BLE001
            if name in REQUIRED or _transient(ex):   # retried on a later run; never saved without the exchange
                raise RuntimeError("%s: %s: %s" % (name, type(ex).__name__, str(ex)[:200]))
            closes[name], absent[name] = {}, "%s: %s" % (type(ex).__name__, str(ex)[:120])   # it answered: absent
            continue
        if name in REQUIRED and len(closes[name]) < REQUIRED_MIN and not accept_short:
            raise Short(name, len(closes[name]))
    S, CB, DISP, N = [], [], [], []
    for i in range(1, 1441):
        e = t0 + 60 * i
        vals = [closes[n][e] for n in closes if closes[n].get(e) is not None]
        N.append(len(vals))
        S.append(round(median(vals), 2) if len(vals) >= MIN_EXCHANGES else None)
        cb = closes["coinbase"].get(e)
        CB.append(cb)
        three = [closes[n].get(e) for n in REQUIRED]
        if S[-1] is not None and all(v is not None for v in three):
            m = sum(three) / 3.0
            sd = math.sqrt(sum((v - m) ** 2 for v in three) / 2.0)
            DISP.append(sd / S[-1])
        else:
            DISP.append(None)
    present = {n: sum(1 for i in range(1, 1441) if closes[n].get(t0 + 60 * i) is not None) for n in closes}
    return dict(asset=asset, day=d.isoformat(), start=t0, S=S, CB=CB, DISP=DISP, N=N, present=present, absent=absent,
                complete=True)


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def comp_path(asset, d):
    return os.path.join(DATA, "comp", asset, "%s.json.gz" % d.isoformat())


def kal_path(asset, d):
    return os.path.join(DATA, "kalshi", asset, "%s.json.gz" % d.isoformat())


def days(first, last):
    return P.days_of(first, last)


def download(max_days=None, budget_minutes=None, log=print, now=None, markets=None):
    bad = identity_problems()
    if bad:
        return False, "not frozen or changed (%s); no download" % ", ".join(bad)
    start = time.time() if now is None else now
    fitted = os.path.exists(MODEL)
    last = TEST[1] if fitted else FIT[1]
    done = waiting = 0
    cache = {}
    short_path = os.path.join(DATA, "shortfall.json")
    shorts, _ = P._read_json(short_path)
    shorts = shorts if isinstance(shorts, dict) else {}
    for a in ASSETS:
        for d in days(FIRST_COMP_DAY, TEST[1]):
            if d > last:
                waiting += 2
                continue
            for kind in ("comp", "kalshi"):
                if kind == "kalshi" and d < FIT[0]:
                    continue
                path = comp_path(a, d) if kind == "comp" else kal_path(a, d)
                if os.path.exists(path):
                    continue
                if (max_days is not None and done >= max_days) or \
                        (budget_minutes is not None and time.time() - start > 60 * budget_minutes):
                    waiting += 1
                    continue
                try:
                    if kind == "comp":
                        key = "%s %s" % (a, d)
                        try:
                            obj = build_comp(a, d, accept_short=shorts.get(key, {}).get("tries", 0) >= SHORT_TRIES)
                        except Short as sh:
                            e = shorts.setdefault(key, dict(tries=0))
                            e.update(tries=e["tries"] + 1, exchange=sh.name, minutes=sh.n)
                            jsonio.save(short_path, shorts)
                            raise
                        if key in shorts:
                            shorts[key]["saved_short"] = True
                            jsonio.save(short_path, shorts)
                    else:
                        if a not in cache:
                            cache[a] = P.market_list(a, FIT[0], last, time.time() - P.SETTLE_LAG)
                        ms = [m for m in cache[a].values() if P.window_day(m["close"]) == d]
                        obj = P.build_day(a, d, ms, True)
                except (RuntimeError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as ex:
                    log("PLAN18 %s %s %s: not saved (%s); run again to retry" % (a, d, kind, ex))
                    waiting += 1
                    continue
                P.save_gz(path, obj)
                done += 1
                if kind == "comp":
                    log("PLAN18 %s %s composite: %d minutes with a composite" % (a, d, sum(1 for s in obj["S"] if s)))
                else:
                    log("PLAN18 %s %s kalshi: %d windows" % (a, d, len(obj["windows"])))
    note = "" if fitted else " (August waits for the fit)"
    return True, "download: %d files saved this run, %d waiting%s" % (done, waiting, note)


# ---------- series (one continuous minute grid per asset) ----------
class Series(object):
    """The composite (or Coinbase) minute series from FIRST_COMP_DAY on: index i = the minute ending at t0 + 60 (i + 1)."""

    def __init__(self, comps, key="S"):
        ds = sorted(comps)
        self.t0 = int(P.day_start(ds[0]))
        n = 1440 * ((ds[-1] - ds[0]).days + 1)
        self.S = [None] * n
        self.CB = [None] * n
        self.DISP = [None] * n
        for d in ds:
            c = comps[d]
            off = 1440 * (d - ds[0]).days
            src = c[key]
            for j in range(1440):
                self.S[off + j] = src[j]
                self.CB[off + j] = c["CB"][j]
                self.DISP[off + j] = c["DISP"][j]
        self.r = [None] * n
        for i in range(1, n):
            if self.S[i] and self.S[i - 1]:
                self.r[i] = 1e4 * math.log(self.S[i] / self.S[i - 1])
        self.sig2 = [None] * n
        self.rr_cache = {}

    def idx(self, end_ts):
        i = int(round((end_ts - self.t0) / 60.0)) - 1
        return i if 0 <= i < len(self.S) else None

    def fit_returns(self):
        lo, hi = self.idx(P.day_start(FIT[0]) + 60), self.idx(P.day_start(FIT[1]) + 86400)
        return lo, [x for x in self.r[lo:hi + 1] if x is not None]

    def run_filter(self, g):
        lo = self.idx(P.day_start(FIT[0]) + 60)
        self.sig2 = [None] * len(self.S)
        self.rr_cache = {}
        self.sig2[lo] = g["backcast"]
        for i in range(lo, len(self.S) - 1):
            ri = self.r[i]
            self.sig2[i + 1] = self.sig2[i] if ri is None else g["omega"] + g["alpha"] * ri * ri + g["beta"] * self.sig2[i]


def fit_garch(returns):
    """GARCH(1,1), zero mean, normal errors, arch's default backcast; rescale off (returns already in basis points)."""
    import numpy as np
    from arch import arch_model
    r = np.asarray(returns, dtype=float)
    am = arch_model(r, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False)
    res = am.fit(disp="off")
    p = res.params
    g = dict(omega=float(p["omega"]), alpha=float(p["alpha[1]"]), beta=float(p["beta[1]"]),
             backcast=float(am.volatility.backcast(r)), n=len(returns), loglik=float(res.loglikelihood),
             convergence_flag=int(res.convergence_flag))
    if g["convergence_flag"] != 0 or not all(math.isfinite(g[k]) for k in ("omega", "alpha", "beta", "backcast")) \
            or g["omega"] <= 0 or g["alpha"] < 0 or g["beta"] < 0 or g["alpha"] + g["beta"] >= 1:
        raise RuntimeError("GARCH fit not usable: %s" % g)
    return g


def lib_versions():
    out = {}
    for name in ("numpy", "scipy", "pandas", "arch", "ruptures", "ccxt"):
        try:
            out[name] = getattr(__import__(name), "__version__", None)
        except ImportError:
            out[name] = None
    return out


def horizon_var(g, s2next, k):
    """V = (T - k - 2/3) x the mean of E[sigma2_{k+j}], j = 1 .. T - k (plan section 3)."""
    a, b, w = g["alpha"], g["beta"], g["omega"]
    phi = a + b
    n = T - k
    if phi < 1:
        v = w / (1 - phi)
        es = [v + phi ** (j - 1) * (s2next - v) for j in range(1, n + 1)]
    else:
        es = [s2next + (j - 1) * w for j in range(1, n + 1)]
    return (T - k - 2.0 / 3.0) * sum(es) / n


def g_prob(ser, g, w, k, price=None):
    """G's p_up at minute k, or None. price: the S_k to use (the series' own by default)."""
    o = int(w["open"])
    ik = ser.idx(o + 60 * k)
    if ik is None or ik + 1 >= len(ser.S):
        return None
    sk, s0, s2n = ser.S[ik], P.num(w.get("strike")), ser.sig2[ik + 1]
    if not (sk and s0) or s2n is None or s2n <= 0:
        return None
    V = horizon_var(g, s2n, k)
    if V <= 0:
        return None
    return P.phi(1e4 * math.log(sk / s0) / math.sqrt(V))


def r_reading(ser, w, k):
    """(found, stat) with stat = m x sqrt(L) signed when 3 <= L <= 5; (False, 0.0) when no recent change; None when
    any of the 30 returns or their sigma is missing."""
    o = int(w["open"])
    ik = ser.idx(o + 60 * k)
    if ik is None or ik - R_N + 1 < 0:
        return None
    key = (ik, tuple(ser.r[ik - R_N + 1:ik + 1]))   # the reading depends only on these returns and their sigmas
    if key in ser.rr_cache:
        return ser.rr_cache[key]
    ser.rr_cache[key] = out = _r_reading(ser, ik)
    return out


def _r_reading(ser, ik):
    import numpy as np
    import ruptures
    z = []
    for i in range(ik - R_N + 1, ik + 1):
        if ser.r[i] is None or not ser.sig2[i]:
            return None
        z.append(ser.r[i] / math.sqrt(ser.sig2[i]))
    bk = ruptures.Pelt(model="l2", min_size=R_MIN, jump=1).fit(np.asarray(z)).predict(pen=R_PEN)
    if bk == [R_N] or len(bk) < 2:
        return (False, 0.0)
    L = R_N - bk[-2]
    if not R_MIN <= L <= R_LAST:
        return (False, 0.0)
    m = sum(z[-L:]) / L
    return (True, m * math.sqrt(L))


def logit(p):
    p = min(max(p, CLIP_P[0]), CLIP_P[1])
    return math.log(p / (1 - p))


def m_inputs(ser, g, w, k, coinbase=False):
    """M's inputs at minute k, or None when any is missing (R's reading included)."""
    p = g_prob(ser, g, w, k)
    q = P.quote(w, k)
    mid = P.mid_of(q)
    rr = r_reading(ser, w, k)
    if p is None or mid is None or rr is None:
        return None
    ik = ser.idx(int(w["open"]) + 60 * k)
    s2 = ser.sig2[ik]
    if not s2:
        return None
    x = [logit(p), logit(mid)]
    if not coinbase:
        cb, sk, dp = ser.CB[ik], ser.S[ik], ser.DISP[ik]
        if not (cb and sk) or dp is None:
            return None
        x += [1e4 * math.log(cb / sk) / math.sqrt(s2), 1e4 * dp / math.sqrt(s2)]
    x += [rr[1], float(T - k)]
    return x


def m_prob(model, x):
    z = [(v - m) / s for v, m, s in zip(x, model["mean"], model["sd"])]
    return P.P7.sigmoid(model["intercept"] + sum(c * v for c, v in zip(model["coef"], z)))


# ---------- loading ----------
def load_comps(asset, first, last):
    out = {}
    for d in days(first, last):
        o, ok = P._read_json(comp_path(asset, d))
        if not (ok and isinstance(o, dict) and o.get("complete")):
            return None, "composite %s %s is not saved yet" % (asset, d)
        out[d] = o
    return out, None


def load_kalshi(asset, first, last):
    out = {}
    for d in days(first, last):
        o, ok = P._read_json(kal_path(asset, d))
        if not (ok and isinstance(o, dict) and o.get("complete")):
            return None, "Kalshi %s %s is not saved yet" % (asset, d)
        out[d] = o
    return out, None


def windows_of(kal):
    for d in sorted(kal):
        for w in sorted(kal[d]["windows"], key=lambda x: x["close"]):
            yield d, w


def coverage(kal):
    """Windows with Kalshi candles per month, as a share of 96 a day."""
    by = {}
    for d in sorted(kal):
        k = d.strftime("%Y-%m")
        n = sum(1 for w in kal[d]["windows"] if w.get("c"))
        e = by.setdefault(k, [0, 0])
        e[0] += n
        e[1] += WINDOWS_PER_DAY
    return {k: dict(windows=v[0], expected=v[1], share=v[0] / float(v[1])) for k, v in by.items()}


# ---------- fit (plan section 3) ----------
def fit_m(ser, g, kal, coinbase=False):
    rows = []
    for d, w in windows_of(kal):
        y = P.y_of(w)
        if y is None:
            continue
        for k in K_M:
            x = m_inputs(ser, g, w, k, coinbase)
            if x is not None:
                rows.append((x, y))
    if len(rows) < 20:
        return None
    X, Y = [r[0] for r in rows], [r[1] for r in rows]
    mu, sd = P.standardise(X)
    Z = [[(v - m) / s for v, m, s in zip(x, mu, sd)] for x in X]
    got = P.fit_ridge_logit(Z, Y, ridge=RIDGE)
    if got is None:
        return None
    b0, b, steps = got
    return dict(mean=mu, sd=sd, intercept=b0, coef=b, steps=steps, rows=len(rows))


def fit(path=None, data=None, now=None):
    """data (tests): {asset: (comps May31-Jul31, kalshi Jun1-Jul31)}."""
    path = path or MODEL
    if os.path.exists(path):
        return None, "already fitted (%s); fitted once" % path
    if data is None:
        bad = identity_problems()
        if bad:
            return None, "not frozen or changed (%s); no fit" % ", ".join(bad)
    if P.RIDGE_SCALE != "sum":
        return None, "PLAN15's RIDGE_SCALE is not 'sum'"
    model = dict(plan=PLAN, plan_sha256=PLAN_SHA256, pins=PINS, assets={},
                 period=[FIT[0].isoformat(), FIT[1].isoformat()],
                 inputs_m=["logit_g", "logit_mid", "coinbase_gap", "dispersion", "r_stat", "minutes_left"],
                 inputs_m_coinbase=["logit_g", "logit_mid", "r_stat", "minutes_left"],
                 libs=lib_versions(),
                 notes=["the GARCH filter starts at arch's backcast value (arch's own recursion starts at omega + "
                        "(alpha + beta) x backcast; the plan allows either)",
                        "logit(mid) is clipped at 0.5%-99.5% like G's p",
                        "quotes use plan15.quote as the plan says (it carries a candle forward up to 5 minutes); the "
                        "10% guard counts raw candles"],
                 fitted=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat())
    for a in ASSETS:
        if data is None:
            comps, why = load_comps(a, FIRST_COMP_DAY, FIT[1])
            if comps is None:
                return None, why
            kal, why = load_kalshi(a, FIT[0], FIT[1])
            if kal is None:
                return None, why
        else:
            comps, kal = data[a]
        cov = coverage(kal)
        pooled = sum(v["windows"] for v in cov.values()) / float(sum(v["expected"] for v in cov.values()) or 1)
        ent = dict(coverage=cov, coverage_pooled=pooled)
        if pooled < COVERAGE_MIN:
            ent["not_testable"] = "Kalshi candles cover under 90% of June-July windows"
            model["assets"][a] = ent
            continue
        sers = {}
        for key, tag in (("S", ""), ("CB", "_coinbase")):
            ser = sers[key] = Series(comps, key)
            lo, rs = ser.fit_returns()
            try:
                g = fit_garch(rs)
            except RuntimeError as ex:
                return None, "%s %s: %s; nothing saved" % (a, key, ex)
            ser.run_filter(g)
            ent["garch" + tag] = g
            m = fit_m(ser, g, kal, coinbase=(key == "CB"))
            if m is None:
                return None, "model M%s for %s did not fit; nothing saved" % (tag, a)
            ent["m" + tag] = m
        ent["q1_fit_period"] = q1(sers["S"], sers["CB"], kal)
        model["assets"][a] = ent
    jsonio.save(path, model)
    return model, "fitted; saved %s" % path


# ---------- signals and scoring (plan section 4) ----------
def fee_fine(p, mult):
    return math.ceil(mult * 0.07 * p * (1 - p) * 10000 - 1e-9) / 10000


def pay(w, k, side, delay, insp, asset):
    """(price, fine fee, whole-cent fee) at the close of minute k + delay, or None."""
    m = k + delay
    mult = P.multiplier_at(insp, asset, int(w["open"]) + 60 * m)
    if mult is None:
        return None
    price, fc, _ = P.fill(w, k, side, delay, mult)
    if price is None:
        return None
    return price, fee_fine(price, mult), fc


def edge_side(p, q, edge=EDGE):
    ya, na = P.side_ask(q, "yes"), P.side_ask(q, "no")
    if ya is not None and p - ya >= edge - 1e-9:
        return "yes"
    if na is not None and (1.0 - p) - na >= edge - 1e-9:
        return "no"
    return None


def decide(rule, ser, g, mm, w, k, coinbase=False):
    """(side or None, missing)."""
    q = P.quote(w, k)
    if P.mid_of(q) is None:
        return None, True
    if rule == "G":
        p = g_prob(ser, g, w, k)
        return (None, True) if p is None else (edge_side(p, q), False)
    if rule == "R":
        rr = r_reading(ser, w, k)
        if rr is None:
            return None, True
        if not rr[0] or abs(rr[1]) < R_CUT - 1e-12:
            return None, False
        side = "yes" if rr[1] > 0 else "no"
        a = P.side_ask(q, side)
        return (side if a is not None and BAND[0] - 1e-9 <= a <= BAND[1] + 1e-9 else None), False
    if rule == "M":
        x = m_inputs(ser, g, w, k, coinbase)
        if x is None:
            return None, True
        return edge_side(m_prob(mm, x), q), False
    raise ValueError(rule)


KS = dict(G=K_G, R=K_R, M=K_M)


def signals(asset, ser, g, mm, kal, insp, coinbase=False):
    out = {r: [] for r in ("G", "R", "M")}
    miss = {r: 0 for r in out}
    for d, w in windows_of(kal):
        y = P.y_of(w)
        if y is None:
            continue
        for rule in out:
            for k in KS[rule]:
                side, missing = decide(rule, ser, g, mm, w, k, coinbase)
                miss[rule] += int(missing)
                if side is None:
                    continue
                other = "no" if side == "yes" else "yes"
                out[rule].append(dict(day=d, ticker=w["ticker"], k=k, side=side, y=y,
                                      fill=pay(w, k, side, FILL_DELAY, insp, asset),
                                      flip=pay(w, k, other, FILL_DELAY, insp, asset),
                                      late={dl: pay(w, k, side, dl, insp, asset) for dl in LATE if k + dl <= 14},
                                      cap=(w.get("t") or {}).get(str(k + FILL_DELAY), 0.0)))
    return out, miss


def profit(side, f, y, cent=False):
    return P.profit(side, f[0], f[2] if cent else f[1], y)


def filled(sigs, cent=False):
    out = []
    for s in sigs:
        if s["fill"] is None:
            continue
        other = "no" if s["side"] == "yes" else "yes"
        out.append(dict(day=s["day"], ticker=s["ticker"], k=s["k"], price=s["fill"][0], cap=s["cap"],
                        win=float(profit(s["side"], (0, 0, 0), s["y"]) > 0),
                        profit=profit(s["side"], s["fill"], s["y"], cent),
                        flip=profit(other, s["flip"], s["y"], cent) if s["flip"] else None))
    return out


def day_means(fs, key="profit"):
    g = {}
    for t in fs:
        g.setdefault(t["day"], []).append(t[key])
    return {d: sum(v) / len(v) for d, v in g.items()}


def boot_p(dm, period, draws=None, seed=SEED):
    draws = draws or BOOT_DRAWS
    blocks = [period[i:i + BOOT_BLOCK_DAYS] for i in range(0, len(period), BOOT_BLOCK_DAYS)]
    blocks = [[dm[d] for d in b if d in dm] for b in blocks]
    if not any(blocks):
        return None
    rnd = random.Random(seed)
    n = low = 0
    while n < draws:
        vals = []
        for _ in range(len(blocks)):
            vals.extend(blocks[rnd.randrange(len(blocks))])
        if vals:
            n += 1
            low += int(sum(vals) / len(vals) <= 0)
    return low / float(draws)


def placebo_p(fs, real, draws=None, seed=SEED):
    """One coin per window flips all of its signals (an unpayable flip keeps its own side); statistic = mean of day means."""
    draws = draws or PLACEBO_DRAWS
    rnd = random.Random(seed)
    tickers = sorted({t["ticker"] for t in fs})
    days_ = sorted({t["day"] for t in fs})
    di = {d: i for i, d in enumerate(days_)}
    hit = 0
    for _ in range(draws):
        coin = {tk: rnd.random() < 0.5 for tk in tickers}
        s, n = [0.0] * len(days_), [0] * len(days_)
        for t in fs:
            i = di[t["day"]]
            v = t["flip"] if (coin[t["ticker"]] and t["flip"] is not None) else t["profit"]
            s[i] += v
            n[i] += 1
        if sum(s[i] / n[i] for i in range(len(days_))) / len(days_) >= real - 1e-12:
            hit += 1
    return (1.0 + hit) / (1.0 + draws)


def stats(sigs, period):
    fs = filled(sigs)
    fc = filled(sigs, cent=True)
    dm = day_means(fs)
    vals = [dm[d] for d in sorted(dm)]
    st = dict(signals=len(sigs), signal_days=len({s["day"] for s in sigs}), filled=len(fs), days=len(vals))
    if st["signals"] < MIN_SIGNALS or st["signal_days"] < MIN_DAYS:
        st["not_testable"] = "fewer than %d signals or fewer than %d days with a signal" % (MIN_SIGNALS, MIN_DAYS)
    m, se = P.P7.mean_se(vals)
    dmc = day_means(fc)
    mc, sec = P.P7.mean_se([dmc[d] for d in sorted(dmc)])
    st.update(mean=m, se=se, mean_cent=mc, se_cent=sec)
    if m is None:
        st.setdefault("not_testable", "fewer than 2 days with a filled trade")
        return st, fs, dm
    t = (m / se) if se else (float("inf") if m > 0 else float("-inf"))
    st.update(t=t, df=len(vals) - 1,
              per_contract=sum(x["profit"] for x in fs) / len(fs), per_contract_cent=sum(x["profit"] for x in fc) / len(fc),
              win_rate=sum(x["win"] for x in fs) / len(fs), mean_price=sum(x["price"] for x in fs) / len(fs),
              capacity_median=P.median([x["cap"] for x in fs]))
    st["p_t"] = P.p_one_sided(t, st["df"]) if math.isfinite(t) else (0.0 if t > 0 else 1.0)
    st["by_minute"] = {}
    for k in sorted({x["k"] for x in fs}):
        dk = day_means([x for x in fs if x["k"] == k])
        dkc = day_means([x for x in fc if x["k"] == k])
        a, b = P.P7.mean_se([dk[d] for d in sorted(dk)])
        c, e = P.P7.mean_se([dkc[d] for d in sorted(dkc)])
        st["by_minute"][str(k)] = dict(filled=sum(1 for x in fs if x["k"] == k), mean=a, se=b, mean_cent=c, se_cent=e)
    late = {}
    for dl in LATE:
        vals2 = [P.profit(s["side"], s["late"][dl][0], s["late"][dl][1], s["y"]) for s in sigs
                 if dl in s["late"] and s["late"][dl] is not None]
        late["k+%d" % dl] = dict(filled=len(vals2), per_contract=(sum(vals2) / len(vals2)) if vals2 else None)
    st["delayed_fills"] = late
    return st, fs, dm


def holm(tests, period):
    for x in tests:
        st = x["stats"]
        if "not_testable" in st:
            x["p"] = None
            continue
        st["p_boot"] = boot_p(x["dm"], period)
        st["p_placebo"] = placebo_p(x["fs"], st["mean"])
        x["p"] = max(st["p_t"], st["p_boot"] if st["p_boot"] is not None else 1.0, st["p_placebo"])
    m = len(tests)
    order = sorted(tests, key=lambda x: (x["p"] if x["p"] is not None else 2.0, x["name"]))
    going = True
    for rank, x in enumerate(order):
        lvl = FAMILY / (m - rank)
        x["holm_rank"], x["holm_level"] = rank + 1, lvl
        st = x["stats"]
        if x["p"] is None:
            x["passed"], x["verdict"] = False, NOT_TESTABLE
            going = False
            continue
        tcut = max(T_FLOOR, P.P7.t_quantile(lvl, st["df"]))
        ok = going and x["p"] <= lvl and st["t"] > tcut
        x["checks"] = dict(t=st["t"], t_cut=tcut, p_t=st["p_t"], p_boot=st["p_boot"], p_placebo=st["p_placebo"])
        x["passed"] = bool(ok)
        going = going and ok
        x["verdict"] = VERDICT_PASS if ok else VERDICT_FAIL
    return order


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2.0 ** n
    return min(1.0, 2 * tail)


def q1(ser_c, ser_cb, kal):
    """Agreement of the composite's and Coinbase's minute-15 close with Kalshi's result."""
    n = ac = ab = b = c = 0
    for d, w in windows_of(kal):
        y = P.y_of(w)
        s0 = P.num(w.get("strike"))
        if y is None or s0 is None:
            continue
        ik = ser_c.idx(int(w["close"]))
        if ik is None:
            continue
        sc, sb = ser_c.S[ik], ser_cb.S[ik]
        if not (sc and sb):
            continue
        ge = w.get("strike_type") == "greater_or_equal"
        uc = sc >= s0 if ge else sc > s0
        ub = sb >= s0 if ge else sb > s0
        rc, rb = uc == (y == 1.0), ub == (y == 1.0)
        n += 1
        ac += rc
        ab += rb
        b += int(rc and not rb)
        c += int(rb and not rc)
    return dict(windows=n, composite_agree=(ac / float(n)) if n else None, coinbase_agree=(ab / float(n)) if n else None,
                differ=b + c, composite_right_when_differ=b, coinbase_right_when_differ=c, mcnemar_p=mcnemar(b, c))


def guard(ser, kal):
    exp = 0
    miss = 0
    for d in sorted(kal):
        exp += WINDOWS_PER_DAY
        ws = kal[d]["windows"]
        miss += max(0, WINDOWS_PER_DAY - len(ws))
        for w in ws:
            o = int(w["open"])
            comp_ok = all((ser.idx(o + 60 * i) is not None and ser.S[ser.idx(o + 60 * i)]) for i in range(GUARD_FROM, T + 1))
            kal_ok = all(str(k) in (w.get("c") or {}) for k in K_G)   # raw candles (no carry-forward)
            miss += int(not (comp_ok and kal_ok))
    share = miss / float(exp) if exp else 1.0
    return (None if share <= MAX_MISSING else "%.1f%% of August windows miss the composite or Kalshi candles" % (100 * share)), share


def presence(comps):
    by = {}
    for d in sorted(comps):
        k = d.strftime("%Y-%m")
        e = by.setdefault(k, {})
        for n, v in comps[d].get("present", {}).items():
            e[n] = e.get(n, 0) + v
    return by


def score(out_path=None, data=None, insp=None, model=None, root=ROOT):
    """data (tests): {asset: (comps May31-Aug31, kalshi Aug)}."""
    out_path = out_path or RESULT
    md_path = out_path[:-5] + ".md"
    if os.path.exists(out_path):   # the JSON is written last: a stale .md alone is overwritten
        return None, "already scored (%s exists); scored once" % out_path
    if data is None:
        bad = identity_problems(root)
        if bad:
            return None, "not frozen or changed (%s); no score" % ", ".join(bad)
    if model is None:
        model, ok = P._read_json(MODEL)
        if not (ok and isinstance(model, dict) and model.get("assets")):
            return None, "no model yet (run fit first)"
    if model.get("plan_sha256") != PLAN_SHA256:
        return None, "the model was not fitted under this plan; no score"
    insp = insp or P.load_inspect()
    if not insp:
        return None, "PLAN15's inspect.json is missing"
    period = days(TEST[0], TEST[1])
    res = dict(plan=PLAN, plan_sha256=PLAN_SHA256, scored=datetime.now(timezone.utc).isoformat(),
               period=[period[0].isoformat(), period[-1].isoformat()],
               model_sha256=P._sha(json.dumps(model, sort_keys=True)), assets={}, tests=[], coinbase_versions={},
               settings=dict(edge=EDGE, band=list(BAND), k_g=list(K_G), k_r=list(K_R), k_m=list(K_M), r_pen=R_PEN,
                             r_cut=R_CUT, family=FAMILY, boot_draws=BOOT_DRAWS, placebo_draws=PLACEBO_DRAWS,
                             seed=SEED, min_signals=MIN_SIGNALS, min_days=MIN_DAYS, pins=PINS,
                             windows_per_day=WINDOWS_PER_DAY))
    tests = []
    for a in ASSETS:
        ent = model["assets"].get(a) or {}
        info = dict(coverage_fit=ent.get("coverage"), garch=ent.get("garch"), garch_coinbase=ent.get("garch_coinbase"),
                    m=ent.get("m"), m_coinbase=ent.get("m_coinbase"))
        res["assets"][a] = info
        if ent.get("not_testable"):
            for rule in ("G", "R", "M"):
                tests.append(dict(name="%s %s" % (a, rule), asset=a, rule=rule,
                                  stats=dict(signals=0, signal_days=0, filled=0, days=0, not_testable=ent["not_testable"]),
                                  fs=[], dm={}))
            continue
        if data is None:
            comps, why = load_comps(a, FIRST_COMP_DAY, TEST[1])
            if comps is None:
                return None, why
            kal, why = load_kalshi(a, TEST[0], TEST[1])
            if kal is None:
                return None, why
        else:
            comps, kal = data[a]
        unknown = [d for d in days(TEST[0], TEST[1]) if P.multiplier_at(insp, a, P.day_start(d) + 43200) is None]
        if unknown:
            return None, "fee multiplier unknown for %s on %d August days; no score" % (a, len(unknown))
        ser = Series(comps, "S")
        ser.run_filter(ent["garch"])
        cbs = Series(comps, "CB")
        cbs.run_filter(ent["garch_coinbase"])
        why, share = guard(ser, kal)
        info.update(missing_share=share, q1=q1(ser, cbs, kal), presence=presence(comps))
        sig, miss = signals(a, ser, ent["garch"], ent["m"], kal, insp)
        info["missing_inputs"] = miss
        # M's August calibration (descriptive)
        cal = []
        for d, w in windows_of(kal):
            y = P.y_of(w)
            if y is None:
                continue
            for k in K_M:
                x = m_inputs(ser, ent["garch"], w, k)
                if x is not None:
                    cal.append((m_prob(ent["m"], x), y))
        cal.sort()
        info["m_calibration_deciles"] = [dict(n=len(part), predicted=sum(p for p, _ in part) / len(part),
                                              actual=sum(y for _, y in part) / len(part))
                                         for part in (cal[i * len(cal) // 10:(i + 1) * len(cal) // 10] for i in range(10)) if part]
        for rule in ("G", "R", "M"):
            st, fs, dm = stats(sig[rule], period)
            if why:
                st["not_testable"] = why
            tests.append(dict(name="%s %s" % (a, rule), asset=a, rule=rule, stats=st, fs=fs, dm=dm))
        sigc, _ = signals(a, cbs, ent["garch_coinbase"], ent["m_coinbase"], kal, insp, coinbase=True)
        res["coinbase_versions"][a] = {r: {k: v for k, v in stats(sigc[r], period)[0].items()
                                           if k in ("signals", "filled", "days", "mean", "se", "per_contract", "win_rate")}
                                       for r in sigc}
    holm(tests, period)
    first_t = None
    for x in sorted(tests, key=lambda x: (ASSETS.index(x["asset"]), x["rule"])):
        st = x["stats"]
        if st.get("se") is not None and st.get("df"):
            first_t = P.P7.t_quantile(FAMILY / len(tests), st["df"])
            st["power_edge_80"] = (max(T_FLOOR, first_t) + 0.84) * st["se"]
        res["tests"].append({k: v for k, v in x.items() if k not in ("fs", "dm")})
    passed = [x["name"] for x in res["tests"] if x.get("passed")]
    res["verdict"] = (VERDICT_PASS + " (%s)" % ", ".join(passed)) if passed else VERDICT_FAIL
    json.dumps(res)
    md = markdown(res)
    with open(md_path + ".tmp", "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(md_path + ".tmp", md_path)
    jsonio.save(out_path, res)
    return res, res["verdict"]


def _f(v, fmt="%+.4f"):
    return "-" if v is None else fmt % v


def markdown(res):
    names = dict(G="G composite + volatility model", R="R shift detector", M="M learned model")
    out = ["# PLAN18 result (scored once)", "",
           "Plan: %s (SHA-256 %s). Windows closing %s to %s. Scored %s." % (
               res["plan"], res["plan_sha256"][:16], res["period"][0], res["period"][1], res["scored"]),
           "", "**Verdict: %s**" % res["verdict"], "",
           "| Test | Signals | Days | Filled | Win rate | Avg price | Profit / contract (whole-cent) | Day mean (SE) | t | p | Holm level | Verdict |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in res["tests"]:
        st = x["stats"]
        out.append("| %s %s | %d | %d | %d | %s | %s | %s (%s) | %s (%s) | %s | %s | %s | %s |" % (
            x["asset"], names[x["rule"]], st["signals"], st["signal_days"], st["filled"], _f(st.get("win_rate"), "%.3f"),
            _f(st.get("mean_price"), "%.3f"), _f(st.get("per_contract")), _f(st.get("per_contract_cent")),
            _f(st.get("mean")), _f(st.get("se"), "%.4f"), _f(st.get("t"), "%.2f"), _f(x.get("p"), "%.4f"),
            _f(x.get("holm_level"), "%.5f"), x.get("verdict", "") + (" (%s)" % st["not_testable"] if st.get("not_testable") else "")))
    out += ["", "## By minute, delayed fills, power (descriptive)", ""]
    for x in res["tests"]:
        st = x["stats"]
        bm = st.get("by_minute") or {}
        out.append("- %s %s: %s; delayed %s; edge needed for 80%% power at Holm's first level, from the observed SE: %s" % (
            x["asset"], x["rule"],
            ", ".join("k=%s %s (SE %s; whole-cent %s) n=%d" % (k, _f(v["mean"]), _f(v["se"], "%.4f"), _f(v["mean_cent"]), v["filled"])
                      for k, v in sorted(bm.items(), key=lambda kv: int(kv[0]))) or "-",
            ", ".join("%s %s (%d)" % (k, _f(v["per_contract"]), v["filled"]) for k, v in sorted((st.get("delayed_fills") or {}).items())) or "-",
            _f(st.get("power_edge_80"))))
    out += ["", "## Coinbase in place of the composite (descriptive)", ""]
    for a, rs in res["coinbase_versions"].items():
        for r, st in sorted(rs.items()):
            out.append("- %s %s: %d signals, %d filled, day mean %s (SE %s), win rate %s" % (
                a, r, st["signals"], st["filled"], _f(st.get("mean")), _f(st.get("se"), "%.4f"), _f(st.get("win_rate"), "%.3f")))
    out += ["", "## Q1 and data (descriptive)", ""]
    for a, info in res["assets"].items():
        q = info.get("q1") or {}
        out.append("- %s: composite agrees with Kalshi's result in %s of %s windows, Coinbase in %s; they differ in %s, "
                   "composite right %s, Coinbase right %s (McNemar p %s). The minute-15 close is a proxy for the "
                   "final-minute average." % (a, _f(q.get("composite_agree"), "%.4f"), q.get("windows", "-"),
                                              _f(q.get("coinbase_agree"), "%.4f"), q.get("differ", "-"),
                                              q.get("composite_right_when_differ", "-"), q.get("coinbase_right_when_differ", "-"),
                                              _f(q.get("mcnemar_p"), "%.4f")))
        g = info.get("garch") or {}
        out.append("  GARCH omega %s alpha %s beta %s; M slopes %s (the Coinbase gap is partly mechanical: Coinbase is one "
                   "of the composite's exchanges); missing share %s; inputs missing %s; exchange presence by month %s." % (
                       _f(g.get("omega"), "%.4f"), _f(g.get("alpha"), "%.4f"), _f(g.get("beta"), "%.4f"),
                       [round(c, 4) for c in (info.get("m") or {}).get("coef", [])], _f(info.get("missing_share"), "%.3f"),
                       info.get("missing_inputs"), info.get("presence")))
    out += ["", "A pass is a lead on past data, not a working system: it earns a rule in the live paper bot with a forward "
            "rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.", ""]
    return "\n".join(out)


def status():
    rec, _ = P._read_json(IDENTITY)
    n = {a: dict(comp=sum(1 for d in days(FIRST_COMP_DAY, TEST[1]) if os.path.exists(comp_path(a, d))),
                 kalshi=sum(1 for d in days(FIT[0], TEST[1]) if os.path.exists(kal_path(a, d)))) for a in ASSETS}
    sh, _ = P._read_json(os.path.join(DATA, "shortfall.json"))
    return "PLAN18: frozen %s; files %s (of %d composite and %d Kalshi days); fitted %s; scored %s; short days %s" % (
        bool(rec), n, len(days(FIRST_COMP_DAY, TEST[1])), len(days(FIT[0], TEST[1])), os.path.exists(MODEL),
        os.path.exists(RESULT), sh or {})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["freeze", "download", "fit", "score", "status"])
    ap.add_argument("--max-days", type=int)
    ap.add_argument("--budget-minutes", type=float)
    a = ap.parse_args(argv)
    if a.stage == "freeze":
        rec, msg = freeze()
    elif a.stage == "download":
        rec, msg = download(a.max_days, a.budget_minutes)
    elif a.stage == "fit":
        rec, msg = fit()
    elif a.stage == "score":
        rec, msg = score()
    else:
        rec, msg = True, status()
    print(msg)
    return 0 if rec else 1


if __name__ == "__main__":
    sys.exit(main())
