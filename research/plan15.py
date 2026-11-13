"""PLAN15 (research/PLAN15.md): Kalshi's 15-minute BTC and ETH "up or down" markets. Can a model call the direction
better than the price? Research and paper only: never part of the gate, never connected to live.py, places nothing.

Stages (run in this order; each refuses to run out of turn):
- inspect (ON THE PC): reads a handful of open and not-yet-open KXBTC15M / KXETH15M market records (metadata only:
  never a candle, a trade or a result; anything else is dropped before it is kept) and the two series records with
  their fee history, to confirm the reference window, the reference price field and open_time (plan section 2).
  Writes research/results/plan15/inspect.json. Allowed before the freeze (the plan asks for it before the freeze).
- freeze (ON THE PC, then commit): the identity record (SHA-256 of research/PLAN15.md, research/plan15.py,
  inspect.json and PLAN7's reused functions), stored once in research/results/plan15_identity.json and copied off the
  folder (the PC's off-folder copy is the one that lasts: a runner's vanishes); refuses afterwards. The GitHub
  workflow refuses every stage until this record is committed.
- download find|check: Kalshi's windows of the two series for the period, their one-minute candles and trades
  (reduced to contracts per window minute), and Coinbase Exchange's public one-minute candles (BTC-USD, ETH-USD;
  granularity 60, at most 300 a request with a one-minute overlap, at most 3 requests a second). One compressed file
  per asset and UTC day under research/results/plan15/days/; a saved day is final. Coinbase's raw candles are never
  stored: each window keeps only derived spot values (sigma, completeness, and the OHLC of the few minutes the
  models and the spot-agreement check read; KEEP_MINUTES). Nothing outcome-based is printed. Needs the freeze.
- fit: the six logistic models of plan section 4 on the find period only (ridge 1.0 on standardised inputs), frozen in
  research/results/plan15_model.json with its SHA-256 in plan15_model.sha256; refuses if the model exists.
- score: once, on the check period (from 2027-01-01 UTC, every check day downloaded); refuses a second time, refuses
  unless the model file is present with its recorded hash; writes research/results/plan15_result.json and .md and a
  copy of each off the folder.
- status: counts only.

Statistics: PLAN7's pinned functions (t quantile, bootstrap, clip/logit/sigmoid), imported from research/plan7.py and
checked by source hash (PINNED_PLAN7), as research/plan8.py does. Standard library only (no numpy needed anywhere, so
every stage also runs on the PC). Network: Kalshi's public API (KALSHI_BASE from config) and api.exchange.coinbase.com,
User-Agent tradebot-paper-research/1.0 only, through tbcommon.httpclient.JsonClient (retries, rate limit) with a
urllib transport (no third-party package).

  python research/plan15.py inspect|freeze|fit|score|status
  python research/plan15.py download find|check
Python 3.8+."""
import argparse
import ast
import gzip
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tbcommon import jsonio   # noqa: E402  (crash-safe file writes)
from tbcommon.httpclient import JsonClient, USER_AGENT, KALSHI_PUBLIC   # noqa: E402
from tbcommon.ohlc import field as ohlc_field   # noqa: E402  (Kalshi candle prices: _dollars, cents, or a dollar string)
import plan7 as P7   # noqa: E402  (pinned functions only; see PINNED_PLAN7)

PLAN = "research/PLAN15.md"
SERIES = {"BTC": "KXBTC15M", "ETH": "KXETH15M"}        # primary BTC, secondary ETH (plan section 2)
SPOT = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
ASSETS = ("BTC", "ETH")
FIND = (date(2026, 9, 1), date(2026, 10, 31))           # windows closing on these UTC dates, inclusive (plan section 2)
CHECK = (date(2026, 11, 1), date(2026, 12, 31))
SCORE_FROM = date(2027, 1, 1)                           # the check period's last windows close on Dec 31 (UTC)
SETTLE_LAG = 6 * 3600                                   # a day is downloaded only this long after its last close
T_MIN = 15                                              # window length, minutes
KS = (2, 5, 10)                                         # decision minutes (plan section 3)
FILL_DELAY = 1                                          # paid at the ask at the close of minute k + 1
LATE_DELAYS = (3, 5)                                    # the delayed-fill placebo (descriptive)
SIGMA_MIN = 60                                          # sigma: one-minute log returns over the 60 minutes before the window
EDGE = 0.04                                             # signal: model - ask on one side at least 4 points
RIDGE = 1.0                                             # on the standardised inputs, not the intercept
MAX_STEPS = 100
FAMILY = 0.025                                          # Holm, one-sided, over the 12 tests
BOOT_BLOCK, BOOT_DRAWS, BOOT_SEED = 2, 20000, 15        # 2-day blocks of days
PLACEBO_DRAWS, PLACEBO_SEED = 2000, 15                  # side-flip placebo (seed: not given by the plan; 15 used)
T_FLOOR = 2.0
MIN_SIGNALS, MIN_SIGNAL_DAYS = 200, 20                  # not testable below these, for a rule
MAX_MISSING = 0.10                                      # not testable above this share of windows missing data, for an asset
MIN_AGREE = 0.97                                        # spot stand-in's up/down must match Kalshi's result this often
WINDOWS_PER_DAY = 96                                    # expected windows a UTC day: an absent or unsettled one is missing data
# --- three choices the plan leaves open; each is one named constant, so an amendment changes one line (user's call) ---
SPOT_AGREE_MEASURE = "ohlc15"   # the spot's "up or down" for the 97% check: "close15" = close of minute 15 vs S_0;
                                 # "oc15" = mean of minute 15's open and close vs S_0; "ohlc15" = mean of minute 15's
                                 # open, high, low and close vs S_0 (the closest stand-in for Kalshi's 60-s average)
RIDGE_SCALE = "sum"              # "sum": maximise sum log-lik - RIDGE/2 x sum(b^2); "mean": mean log-lik - RIDGE/2 x sum(b^2)
CARRY_FORWARD_QUOTE = True       # False: a minute with no Kalshi candle has no quote; True: the last quote of the
                                 # CARRY_MAX_MIN minutes before it stands (never from before the window opened)
CARRY_MAX_MIN = 5
# Spot minutes kept per window (relative to the open): S_0 fallback (0), each decision minute k, k + 1, k - 1, k - 5,
# and minute 15 for the agreement check. OHLC kept for each, so the agreement measure can change by amendment.
KEEP_MINUTES = tuple(sorted({0, T_MIN} | {k + d for k in (2, 5, 10) for d in (0, 1, -1, -5)}))
VERDICT_PASS = "lead on past data: justifies a forward paper test"
VERDICT_FAIL = "no edge shown"
NOT_TESTABLE = "not testable"
INPUTS = ("rw_logit", "mid_logit", "ret1_over_sigma", "ret5_over_sigma", "log_sigma", "hour_sin", "hour_cos",
          "log1p_volume")
REF_FIELD = "floor_strike"                              # the market record's reference price field (confirmed by inspect)
QUADRATIC = ("quadratic", "quadratic_with_maker_fees")
COINBASE = "https://api.exchange.coinbase.com"
COINBASE_GAP = 1.0 / 3 + 0.01                           # at most 3 requests a second
COINBASE_MAX = 300
KALSHI_GAP = 0.1
MAX_FILE = 50 * 1024 * 1024

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(RESULTS, "plan15")
INSPECT = os.path.join(DATA, "inspect.json")
PERIODS = os.path.join(DATA, "periods.json")
IDENTITY = os.path.join(RESULTS, "plan15_identity.json")
MODEL = os.path.join(RESULTS, "plan15_model.json")
MODEL_SHA = os.path.join(RESULTS, "plan15_model.sha256")
RESULT = os.path.join(RESULTS, "plan15_result.json")
RESULT_MD = os.path.join(RESULTS, "plan15_result.md")

# ---------- code identity (plan section 9) ----------
REUSED = ("t_quantile", "t_upper", "_betacf", "boot_means", "boot_interval", "clip", "logit", "sigmoid", "mean_se")
PINNED_PLAN7 = {   # research/plan7.py as frozen on 2026-11-05 (the same hashes research/plan8.py pins)
    'research/plan7.py:_betacf': 'e25864fc49eeb91b5de301c142f8df84c3ca2d93a5f0048097a4e803d484d71c',
    'research/plan7.py:boot_interval': 'f3f54b2cd974f83ef90dfeda1a21930a4a432f51990d4ca744ac890074088a63',
    'research/plan7.py:boot_means': '6f8c0cd3d077359f637cc381d1cbbdcf34fd9bd7460d692ea5284403329e9a2b',
    'research/plan7.py:clip': '85d3d12068cdaf82316978a5bce623d68f32dc178a8216872cb9f91999679094',
    'research/plan7.py:logit': '004b949e96f1c38790c62a1debd20ea7fb2aa9b4640591b2e3406af2c694b859',
    'research/plan7.py:mean_se': '92db35ba154a25b04a146f04d2ceb8f99ad927a824ca27e7a16f6993d6e82fd3',
    'research/plan7.py:sigmoid': 'bd0d78efc6adac4fbc22925b1a7dc83f14225254c1564925112f291e6b9b2a5f',
    'research/plan7.py:t_quantile': 'ca188669a12be647eed259b72d78bba97a55ed07b86e8aff80df6aedeea4592a',
    'research/plan7.py:t_upper': '882e3706a702e674974e655ee23d8e8688c770713d6247d8c244ceee049b7eed',
}
PLAN7_EPS = 0.01   # P7.EPS, the clip used for every logit input here (pinned with the functions)
FROZEN_FILES = ("research/PLAN15.md", "research/plan15.py")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path):
    """SHA-256 of a text file with line endings normalized, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            return _sha(f.read().replace("\r\n", "\n"))
    except (OSError, ValueError):
        return None


def bytes_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


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


def plan7_problems(root=ROOT):
    """PLAN7 functions this plan reuses whose source differs from the pins (or the clip constant): [] when all hold."""
    p = os.path.join(root, "research", "plan7.py")
    bad = sorted(k for k in PINNED_PLAN7 if source_hash(p, k.split(":")[1]) != PINNED_PLAN7[k])
    if P7.EPS != PLAN7_EPS:
        bad.append("research/plan7.py:EPS")
    return bad


def identity_now(root=ROOT, inspect_path=None):
    out = {"file:%s" % f: file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES}
    out["file:research/results/plan15/inspect.json"] = file_hash(inspect_path or INSPECT)
    p = os.path.join(root, "research", "plan7.py")
    out.update({k: source_hash(p, k.split(":")[1]) for k in PINNED_PLAN7})
    return out


def identity_problems(root=ROOT, identity_path=None, inspect_path=None):
    """[] when the stored identity record exists and the code, the plan and inspect.json still match it."""
    rec, ok = _read_json(identity_path or IDENTITY)
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root, inspect_path)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    return bad + plan7_problems(root)


# ---------- small helpers ----------
def _read_json(path):
    """(object, True) for a readable JSON file (gzip by name); (None, False) damaged; (None, True) missing."""
    if not os.path.exists(path):
        return None, True
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f), True
        with open(path, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError, EOFError, RecursionError):
        return None, False


def save_gz(path, obj):
    """Write compressed JSON through a temp file and os.replace (a reader never sees half a file); refuse over 50 MB."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    if os.path.getsize(tmp) > MAX_FILE:
        os.remove(tmp)
        raise RuntimeError("%s would exceed 50 MB; not saved" % path)
    os.replace(tmp, path)


def offsite():
    """The off-folder backup location backup.py uses (TRADEBOT_OFFSITE_BACKUPS, else Documents\\tradebot_backups)."""
    return os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents", "tradebot_backups")


def offsite_path(path):
    return os.path.join(offsite(), "plan15", "results", os.path.basename(path))


def keep_offsite(path):
    """Copy a written file off the folder unless a copy is already there (a frozen file is never replaced)."""
    saved = offsite_path(path)
    if os.path.exists(saved):
        return None
    try:
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        shutil.copy2(path, saved)
        return None
    except OSError as ex:
        return "PLAN15: off-folder copy of %s failed (%s)" % (os.path.basename(path), ex)


def num(v):
    try:
        x = None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None
    return x if x is not None and math.isfinite(x) else None


def ts_of(v):
    """Unix seconds from an ISO time ("2026-11-01T00:15:00Z") or a number; None if unreadable."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:   # Python 3.8's fromisoformat takes neither "Z" nor fractions other than 3 or 6 digits: parsed by hand
        s = str(v).strip()
        if s.endswith("Z"):
            s = s[:-1]
        elif s.endswith("+00:00"):
            s = s[:-6]
        if "+" in s or "-" in s.split("T", 1)[-1]:
            return None   # an explicit offset other than UTC: refused rather than guessed
        frac = 0.0
        if "." in s:
            s, f = s.split(".", 1)
            frac = float("0." + f) if f.isdigit() else 0.0
        d = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return d.timestamp() + frac
    except ValueError:
        return None


def utc_day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date()


def day_start(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def days_of(first, last):
    out, d = [], first
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def L(p):
    return P7.logit(P7.clip(p))


def fee(p, mult):
    """Kalshi's taker fee for one contract at price p: round up(multiplier x 0.07 x C x P x (1 - P)) to the cent, C = 1
    (plan section 3)."""
    return math.ceil(mult * 0.07 * p * (1 - p) * 100 - 1e-9) / 100


# ---------- 1. candle labels (plan section 3) ----------
def coinbase_end(row):
    """Coinbase Exchange candle [time, low, high, open, close, volume]: time is the START of the minute. Returns
    (end of minute, close), the label used here ("minute k" = the candle that closes at k minutes)."""
    return int(row[0]) + 60, float(row[4])


def coinbase_ohlc(row):
    """(end of minute, [open, high, low, close]) from a Coinbase row [start, low, high, open, close, volume]."""
    return int(row[0]) + 60, [float(row[3]), float(row[2]), float(row[1]), float(row[4])]


def kalshi_end(c):
    """Kalshi's candlestick end_period_ts is already the end of its minute (inclusive end); returned unchanged."""
    return int(c["end_period_ts"])


def _cfield(c, k, sub):
    """A Kalshi candle price in dollars (tbcommon.ohlc.field): sub_dollars, else sub as integer cents, or as a dollar
    string ("0.5600") as the archive endpoint sends it."""
    return ohlc_field(c.get(k), sub)


def kalshi_minutes(cs, open_ts):
    """{minute index m: [yes bid close, yes ask close, volume]} for the candles that end at open + 60 m, 1 <= m <= 15
    (plus m = 0, the candle ending at the window's open, when present)."""
    out = {}
    for c in cs:
        e = kalshi_end(c)
        m, r = divmod(e - int(open_ts), 60)
        if r or not 0 <= m <= T_MIN:
            continue
        vol = num(c.get("volume_fp"))
        vol = vol if vol is not None else num(c.get("volume"))
        out[str(m)] = [_cfield(c, "yes_bid", "close"), _cfield(c, "yes_ask", "close"), vol or 0.0]
    return out


def trade_minutes(trades, open_ts):
    """{minute index m: contracts traded} with the trade's time in (open + 60 (m - 1), open + 60 m], 1 <= m <= 15."""
    out = {}
    for r in trades:
        t = ts_of(r.get("created_time"))
        n = num(r.get("count_fp"))
        n = n if n is not None else num(r.get("count"))
        if t is None or not n:
            continue
        m = int(math.ceil((t - open_ts) / 60.0))
        if 1 <= m <= T_MIN:
            out[str(m)] = out.get(str(m), 0.0) + n
    return out


# ---------- 2. network (only in inspect and download) ----------
class _Resp(object):
    def __init__(self, code, headers, body):
        self.status_code, self.headers, self._body = code, headers, body

    def json(self):
        return json.loads(self._body.decode("utf-8"))


class UrllibClient(JsonClient):
    """tbcommon's JsonClient (retries, Retry-After, rate limit, the project's User-Agent) over urllib, so no
    third-party package is needed on the PC or the runner."""

    def _transport(self):
        import urllib.request
        import urllib.parse
        import urllib.error
        import socket

        def get(url, params=None, headers=None, timeout=30):
            q = {k: v for k, v in (params or {}).items() if v is not None}
            full = url + ("?" + urllib.parse.urlencode(q) if q else "")
            req = urllib.request.Request(full, headers=dict(headers or self.headers))
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _Resp(r.status, dict(r.headers), r.read())
            except urllib.error.HTTPError as ex:
                return _Resp(ex.code, dict(ex.headers or {}), ex.read() or b"")
        return get, (urllib.error.URLError, socket.timeout, ConnectionError)


_CLIENTS = {}


def _client(name):
    if name not in _CLIENTS:
        if name == "kalshi":
            try:
                from config import KALSHI_BASE as base
            except Exception:   # config.py needs nothing here but its address; fall back to the same default
                base = os.environ.get("KALSHI_BASE") or KALSHI_PUBLIC
            _CLIENTS[name] = UrllibClient(base, tries=6, timeout=60, min_gap=KALSHI_GAP,
                                          headers={"User-Agent": USER_AGENT})
        else:
            _CLIENTS[name] = UrllibClient(COINBASE, tries=6, timeout=60, min_gap=COINBASE_GAP,
                                          headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    return _CLIENTS[name]


def http_kalshi(path, params=None):
    """GET on Kalshi's public API (tests replace this function)."""
    return _client("kalshi").get(path, params)


def http_coinbase(path, params=None):
    """GET on Coinbase Exchange's public market data (tests replace this function)."""
    return _client("coinbase").get(path, params)


def kalshi_pages(path, params, key):
    out, cur = [], None
    while True:
        q = dict(params)
        if cur:
            q["cursor"] = cur
        j = http_kalshi(path, q) or {}
        out.extend(j.get(key) or [])
        cur = j.get("cursor")
        if not cur:
            return out


# ---------- 3. inspect (metadata only; plan section 2) ----------
META_KEYS = ("ticker", "event_ticker", "series_ticker", "market_type", "title", "subtitle", "yes_sub_title",
             "no_sub_title", "open_time", "close_time", "expected_expiration_time", "expiration_time",
             "latest_expiration_time", "created_time", "strike_type", "floor_strike", "cap_strike", "functional_strike",
             "custom_strike", "rules_primary", "rules_secondary", "settlement_timer_seconds", "can_close_early",
             "early_close_condition", "price_level_structure", "status")


def metadata(m):
    """Only the allow-listed metadata of a market record: no result, settlement value, price or volume."""
    return {k: m.get(k) for k in META_KEYS if k in m}


OLD_MULT_KEYS = ("old_fee_multiplier", "previous_fee_multiplier", "prior_fee_multiplier")


def parse_fee_changes(j, series):
    """([(effective ts, fee_type, multiplier, old multiplier or None)] oldest first, ok). ok is False when the
    answer is not a dict, carries an error, or lists entries none of which could be read (fail closed)."""
    rows, seen = [], 0
    if not isinstance(j, dict) or "error" in j:
        return rows, False
    for k, v in j.items():
        if isinstance(v, list):
            for x in v:
                if not isinstance(x, dict) or (x.get("series_ticker") not in (None, series)):
                    continue
                seen += 1
                t = ts_of(x.get("scheduled_ts") or x.get("effective_ts") or x.get("scheduled_time"))
                mult = num(x.get("fee_multiplier"))
                old = next((num(x.get(q)) for q in OLD_MULT_KEYS if num(x.get(q)) is not None), None)
                if t is not None and mult is not None:
                    rows.append((t, x.get("fee_type"), mult, old))
    return sorted(rows, key=lambda r: r[0]), not (seen and not rows)


def inspect(path=None, now=None, per_series=4):
    """Read a handful of market records per series (open and not-yet-open ones only; metadata only) and the series
    records with their fee history; write inspect.json. Returns (dict, message)."""
    path = path or INSPECT
    if os.path.exists(IDENTITY):
        return None, "the code is frozen; inspect.json is part of the identity record and is not re-made"
    now = time.time() if now is None else now
    out = dict(plan=PLAN, inspected=datetime.fromtimestamp(now, timezone.utc).isoformat(), inspected_ts=now, series={})
    confirmed = True
    for a in ASSETS:
        s = SERIES[a]
        rec = (http_kalshi("/series/%s" % s) or {}).get("series") or {}
        try:
            fc = http_kalshi("/series/fee_changes", dict(series_ticker=s, show_historical="true"))
        except RuntimeError as ex:
            fc = {"error": str(ex)}
        parsed, fc_ok = parse_fee_changes(fc, s)
        samples = []
        for status in ("open", "unopened"):   # never settled ones: their records carry the result
            try:
                j = http_kalshi("/markets", dict(series_ticker=s, status=status, limit=per_series)) or {}
            except RuntimeError as ex:
                samples.append(dict(status_asked=status, error=str(ex)))
                continue
            for m in (j.get("markets") or [])[:per_series]:
                x = metadata(m)
                x["status_asked"] = status
                o, c = ts_of(m.get("open_time")), ts_of(m.get("close_time"))
                x["close_minus_open_s"] = (c - o) if (o is not None and c is not None) else None
                x["reference_field_set"] = num(m.get(REF_FIELD)) is not None
                samples.append(x)
        good = [x for x in samples if "error" not in x]
        live = [x for x in good if x["status_asked"] == "open"]
        checks = dict(
            open_time_is_window_start=bool(good) and all(x["close_minus_open_s"] == T_MIN * 60 for x in good),
            reference_set_on_open_markets=bool(live) and all(x["reference_field_set"] for x in live),
            fee_type=rec.get("fee_type"), fee_multiplier=num(rec.get("fee_multiplier")),
            fee_type_quadratic=rec.get("fee_type") in QUADRATIC, fee_history_read=fc_ok)
        checks["use_reference_field"] = bool(checks["reference_set_on_open_markets"])
        out["series"][a] = dict(fee_changes_parsed=parsed, checks=checks)
        checks["fee_known_for_periods"] = fee_problem(dict(out, inspected_ts=now), a) is None
        confirmed = confirmed and checks["open_time_is_window_start"] and checks["fee_type_quadratic"] and \
            checks["fee_multiplier"] is not None and fc_ok and checks["fee_known_for_periods"]
        out["series"][a] = dict(series=s, record={k: rec.get(k) for k in ("ticker", "title", "frequency", "fee_type",
                                                                          "fee_multiplier", "settlement_sources",
                                                                          "contract_url", "category")},
                                fee_changes=fc, fee_changes_parsed=parsed, samples=samples,
                                checks=checks)
    try:   # the S&P 500 15-minute series, reported descriptively only (plan section 2): found by name, metadata only
        allser = kalshi_pages("/series", dict(), "series")
        out["spx_series"] = sorted(x.get("ticker") for x in allser if "15" in (x.get("ticker") or "") and
                                   ("S&P" in (x.get("title") or "") or "INX" in (x.get("ticker") or "")))
    except RuntimeError as ex:
        out["spx_series"] = []
        out["spx_error"] = str(ex)
    out["confirmed"] = bool(confirmed)
    jsonio.save(path, out)
    msg = ("inspect written (%s): window start = close - 15 min %s; reference field %s: BTC %s, ETH %s; fee types %s" % (
        path, "confirmed" if all(out["series"][a]["checks"]["open_time_is_window_start"] for a in ASSETS) else
        "NOT confirmed (an amendment is needed before the freeze)", REF_FIELD,
        out["series"]["BTC"]["checks"]["use_reference_field"], out["series"]["ETH"]["checks"]["use_reference_field"],
        [out["series"][a]["checks"]["fee_type"] for a in ASSETS]))
    return out, msg


def load_inspect(path=None):
    d, ok = _read_json(path or INSPECT)
    return d if ok and isinstance(d, dict) else None


def use_reference(insp, asset):
    """True: S_0 is the market record's reference field; False: the spot price at the window's open (plan section 4)."""
    try:
        return bool(insp["series"][asset]["checks"]["use_reference_field"])
    except (KeyError, TypeError):
        return False


def fee_schedule(insp, asset):
    """(series multiplier, [(ts, type, multiplier, old multiplier)]) from inspect.json."""
    s = insp["series"][asset]
    rows = [tuple(x) + (None,) * (4 - len(x)) for x in s.get("fee_changes_parsed") or []]
    return s["checks"]["fee_multiplier"], rows


def multiplier_at(insp, asset, ts):
    """The fee multiplier in force at ts, or None when it is not known:
    - the latest listed change at or before ts;
    - else, when a change took effect after ts (and before inspect read the series record), that change's documented
      old multiplier, or None if the listing does not give it (the series record's value is the new one);
    - else the series record's multiplier."""
    base, changes = fee_schedule(insp, asset)
    done = [c for c in changes if c[0] <= ts]
    if done:
        return done[-1][2]
    seen_at = insp.get("inspected_ts") or float("inf")
    later = [c for c in changes if ts < c[0] <= seen_at]
    if later:
        return later[0][3]
    return base


def fee_problem(insp, asset):
    """None when the multiplier is known for every window of both periods, else why not (fail closed)."""
    try:
        if multiplier_at(insp, asset, day_start(FIND[0])) is None:
            return "a fee change for %s took effect during Sep-Dec 2026 and the listing gives no old multiplier" % asset
        base, _ = fee_schedule(insp, asset)
        if base is None:
            return "no fee multiplier on the %s series record" % asset
    except (KeyError, TypeError):
        return "no fee information for %s" % asset
    return None


# ---------- 4. freeze ----------
def freeze(path=None, root=ROOT, now=None):
    """Store the identity record once (refuses afterwards). Returns (record or None, message)."""
    path = path or IDENTITY
    if os.path.exists(path) or os.path.exists(offsite_path(path)):
        return None, "already frozen (%s); the identity record is stored once and never re-made" % path
    insp = load_inspect()
    if not insp:
        return None, "run inspect first (plan section 2: the market fields are confirmed before the code is frozen)"
    if not insp.get("confirmed"):
        return None, "inspect did not confirm the window, the fee type or the fee multiplier; an amendment comes first"
    bad = plan7_problems(root)
    if bad:
        return None, "PLAN7's shared code differs from the pins (%s); nothing saved" % ", ".join(bad)
    rec = dict(plan=PLAN, frozen=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(),
               identity=identity_now(root))
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read: %s" % [k for k, v in rec["identity"].items() if v is None]
    jsonio.save(path, rec)
    err = keep_offsite(path)
    return rec, "frozen: %s" % path + ("; " + err if err else "")


# ---------- 5. download ----------
def day_path(asset, d):
    return os.path.join(DATA, "days", asset, "%s.json.gz" % d.isoformat())


def market_list(asset, first, last, now):
    """The series' windows closing on first..last (UTC dates), from Kalshi's archive and its live listing
    (archive first, as research/fetch.py does), reduced to what the scoring reads. The result field is kept, never
    printed."""
    s = SERIES[asset]
    lo, hi = day_start(first), day_start(last) + 86400
    hi = min(hi, now)
    out = {}
    # GET /markets takes min_close_ts/max_close_ts only with no status (or "closed"), never with "settled": no status
    # here; a window not settled yet has no result and is counted as missing data.
    for path, extra in (("/historical/markets", {}), ("/markets", dict(min_close_ts=int(lo), max_close_ts=int(hi)))):
        for m in kalshi_pages(path, dict(series_ticker=s, limit=1000, **extra), "markets"):
            c = ts_of(m.get("close_time"))
            if c is None or not (lo <= c < hi) or m.get("ticker") in out:
                continue
            out[m["ticker"]] = dict(ticker=m["ticker"], close=c, open_listed=ts_of(m.get("open_time")),
                                    open=c - T_MIN * 60, strike=num(m.get(REF_FIELD)), strike_type=m.get("strike_type"),
                                    result=m.get("result") if m.get("result") in ("yes", "no") else None,
                                    hist=path.startswith("/historical"))
    return out


def window_day(close_ts):
    """The UTC day a window belongs to: the UTC date of its close (plan section 2: "windows closing" on a date; the
    day unit of section 5 uses the same date)."""
    return utc_day(close_ts)


def fetch_candles(m):
    """A window's Kalshi minute candles from 60 s before its open to its close (archive or live endpoint)."""
    start, end = int(m["open"]) - 60, int(m["close"])
    if m["hist"]:
        j = http_kalshi("/historical/markets/%s/candlesticks" % m["ticker"],
                        dict(start_ts=start, end_ts=end, period_interval=1)) or {}
        return j.get("candlesticks") or []
    j = http_kalshi("/series/%s/markets/%s/candlesticks" % (m["ticker"].split("-")[0], m["ticker"]),
                    dict(start_ts=start, end_ts=end, period_interval=1)) or {}
    return j.get("candlesticks") or []


def fetch_trades(m):
    """A window's trades from both the archive and the live endpoint, merged by trade_id (as research/plan4.py)."""
    rows = {}
    for path in ("/historical/trades", "/markets/trades"):
        for r in kalshi_pages(path, dict(ticker=m["ticker"], min_ts=int(m["open"]), max_ts=int(m["close"]) + 60,
                                         limit=1000), "trades"):
            rows[r.get("trade_id") or (r.get("created_time"), r.get("taker_side"), r.get("count_fp"),
                                       r.get("yes_price_dollars"))] = r
    return list(rows.values())


def fetch_spot(asset, start_end, stop_end):
    """{end of minute: [open, high, low, close]} for minutes ending in [start_end, stop_end], from Coinbase's
    one-minute candles. Each request asks one minute more on each side than it keeps (whether the end is inclusive
    is not documented), so it covers at most 300 candles and keeps at most 298; labels converted to the minute's end.
    Kept in memory only: the raw candles are never written to disk."""
    out = {}
    s = int(start_end) - 60   # bucket start of the first wanted minute
    last_start = int(stop_end) - 60
    while s <= last_start:
        e = min(s + (COINBASE_MAX - 3) * 60, last_start)
        rows = http_coinbase("/products/%s/candles" % SPOT[asset], dict(
            granularity=60, start=datetime.fromtimestamp(s - 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=datetime.fromtimestamp(e + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        if not isinstance(rows, list):
            raise RuntimeError("Coinbase answered without a candle list")
        for row in rows:
            if isinstance(row, list) and len(row) >= 5 and s <= int(row[0]) <= e:
                t, v = coinbase_ohlc(row)
                out[t] = v
        s = e + 60
    return out


def sigma_from(closes):
    """SD (n - 1) of the one-minute log returns between consecutive closes; None when a close is missing or the SD
    is 0."""
    if len(closes) < 3 or any(x is None or x <= 0 for x in closes):
        return None
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    m = sum(r) / len(r)
    v = sum((a - m) ** 2 for a in r) / (len(r) - 1)
    return math.sqrt(v) if v > 0 else None


def derive_spot(spot, open_ts):
    """The derived spot values a window keeps (no raw series): complete (every minute from 60 before the open to
    minute 15 present), sigma (the 60 returns before the open), and {minute: [o, h, l, c]} for KEEP_MINUTES."""
    o = int(open_ts)
    complete = all(spot.get(o + 60 * i) is not None for i in range(-SIGMA_MIN, T_MIN + 1))
    sig = sigma_from([(spot.get(o + 60 * i) or [None] * 4)[3] for i in range(-SIGMA_MIN, 1)])
    keep = {str(i): spot[o + 60 * i] for i in KEEP_MINUTES if spot.get(o + 60 * i) is not None}
    return dict(complete=complete, sigma=sig, m=keep)


def build_day(asset, d, markets, use_ref=True):
    """One asset-day: every window closing that day with its compact Kalshi candles and trade minutes and its derived
    spot values (Coinbase read from 61 minutes before the first window's open to the day's end, never stored raw)."""
    t0 = day_start(d) - T_MIN * 60 - (SIGMA_MIN + 1) * 60
    t1 = day_start(d) + 86400
    spot = fetch_spot(asset, t0 + 60, t1)
    wins = []
    for m in sorted(markets, key=lambda x: x["close"]):
        cs = fetch_candles(m)
        tr = fetch_trades(m)
        wins.append(dict(ticker=m["ticker"], open=m["open"], close=m["close"], open_listed=m["open_listed"],
                         strike=m["strike"], strike_type=m.get("strike_type"), result=m["result"],
                         s0_source="reference" if (use_ref and m["strike"] is not None) else "spot",
                         c=kalshi_minutes(cs, m["open"]), t=trade_minutes(tr, m["open"]),
                         spot=derive_spot(spot, m["open"]), n_candles=len(cs), n_trades=len(tr)))
    return dict(asset=asset, day=d.isoformat(), windows=wins, expected=WINDOWS_PER_DAY, complete=True)


def periods(now, find_markets=None):
    """The fixed periods; the find period's first day is recorded once, before any price is read (plan section 2)."""
    p, ok = _read_json(PERIODS)
    if ok and isinstance(p, dict):
        return p
    if find_markets is None:
        return None
    firsts = [window_day(m["close"]) for ms in find_markets.values() for m in ms.values()]
    first = max(FIND[0], min(firsts)) if firsts else FIND[0]
    p = dict(find=[first.isoformat(), FIND[1].isoformat()], check=[CHECK[0].isoformat(), CHECK[1].isoformat()],
             recorded=datetime.fromtimestamp(now, timezone.utc).isoformat(),
             note="find starts at the first available window when Kalshi's history does not reach Sep 1")
    jsonio.save(PERIODS, p)
    return p


def download(which, now=None, log=print, max_days=None):
    """Download the find or the check period, day by day; a saved day is final. Prints counts only."""
    now = time.time() if now is None else now
    bad = identity_problems()
    if bad:
        return False, "the code is not frozen or differs from the frozen record (%s); no download" % ", ".join(bad)
    insp = load_inspect()
    first, last = FIND if which == "find" else CHECK
    lists = {}
    for a in ASSETS:
        lp = os.path.join(DATA, "markets", "%s_%s.json.gz" % (a, which))
        saved, ok = _read_json(lp)
        if which == "find" and ok and isinstance(saved, dict):
            lists[a] = saved
            continue
        lists[a] = market_list(a, first, last, now)
        save_gz(lp, lists[a])
    if which == "find":
        p = periods(now, lists)
        first = date.fromisoformat(p["find"][0])
    done = 0
    pending = 0
    for a in ASSETS:
        by_day = {}
        for m in lists[a].values():
            by_day.setdefault(window_day(m["close"]), []).append(m)
        for d in days_of(first, last):
            path = day_path(a, d)
            if os.path.exists(path):
                continue
            if day_start(d) + 86400 + SETTLE_LAG > now:
                pending += 1
                continue
            if max_days is not None and done >= max_days:
                pending += 1
                continue
            ms = by_day.get(d, [])
            try:
                obj = build_day(a, d, ms, use_reference(insp, a))
            except RuntimeError as ex:
                log("PLAN15 %s %s %s: not saved (%s); run again to retry" % (which, a, d, ex))
                continue
            obj["fee_multiplier"] = multiplier_at(insp, a, day_start(d)) if insp else None
            save_gz(path, obj)
            done += 1
            log("PLAN15 %s %s %s: %d windows saved" % (which, a, d, len(ms)))
    if which == "check":
        spx(insp, now, log)
    return True, "download %s: %d asset-days saved this run, %d waiting (not yet settled or for the next run)" % (
        which, done, pending)


def spx(insp, now, log=print):
    """The S&P 500 15-minute series, descriptive only (plan section 2): count, volume and the minute-5 spread."""
    names = (insp or {}).get("spx_series") or []
    out = {}
    for s in names:
        rows = []
        for path, extra in (("/historical/markets", {}), ("/markets", dict(status="settled"))):
            for m in kalshi_pages(path, dict(series_ticker=s, limit=1000, **extra), "markets"):
                c = ts_of(m.get("close_time"))
                if c is None or not (day_start(FIND[0]) <= c < day_start(CHECK[1]) + 86400):
                    continue
                v = num(m.get("volume_fp"))
                rows.append(dict(ticker=m["ticker"], close=c, volume=v if v is not None else num(m.get("volume")),
                                 hist=path.startswith("/historical")))
        spreads = []
        for r in rows[:200]:
            try:
                cs = fetch_candles(dict(r, open=r["close"] - T_MIN * 60))
            except RuntimeError:
                continue
            q = kalshi_minutes(cs, r["close"] - T_MIN * 60).get("5")
            if q and q[0] is not None and q[1] is not None:
                spreads.append(q[1] - q[0])
        out[s] = dict(markets=len({r["ticker"] for r in rows}), volume=sum(r["volume"] or 0 for r in rows),
                      median_spread_minute5=median(spreads), spreads_read=len(spreads))
    jsonio.save(os.path.join(DATA, "spx.json"), out)
    log("PLAN15 S&P 500 15-minute series (descriptive): %s" % ({k: v["markets"] for k, v in out.items()} or "none found"))


def load_days(asset, first, last):
    """{day: day object} for the asset's saved days in first..last, and the days missing."""
    got, missing = {}, []
    for d in days_of(first, last):
        obj, ok = _read_json(day_path(asset, d))
        if ok and isinstance(obj, dict) and obj.get("complete"):
            got[d] = obj
        else:
            missing.append(d)
    return got, missing


# ---------- 6. the per-window computation (plan sections 3 and 4) ----------
def median(x):
    x = sorted(v for v in x if v is not None)
    if not x:
        return None
    n = len(x)
    return x[n // 2] if n % 2 else (x[n // 2 - 1] + x[n // 2]) / 2.0


def spot_close(w, i):
    """The spot close of window minute i (one of KEEP_MINUTES), or None."""
    v = ((w.get("spot") or {}).get("m") or {}).get(str(i))
    return v[3] if v else None


def rw_prob(s_k, s_0, sigma, k):
    """p_up = Phi(ln(S_k / S_0) / (sigma x sqrt(T - k - 0.5))) (plan section 4)."""
    return phi(math.log(s_k / s_0) / (sigma * math.sqrt(T_MIN - k - 0.5)))


def quote(w, m):
    """(yes bid, yes ask) at the close of window minute m, or None when there is no candle ending then (with
    CARRY_FORWARD_QUOTE, the last candle at or before m stands instead)."""
    c = w.get("c") or {}
    q = c.get(str(m))
    if q is None and CARRY_FORWARD_QUOTE:
        q = next((c[str(i)] for i in range(m - 1, max(-1, m - 1 - CARRY_MAX_MIN), -1) if str(i) in c), None)
    return (q[0], q[1]) if q else None


def mid_of(q):
    """The mid (bid + ask) / 2 when both sides are present and bid < ask; else None."""
    if not q or q[0] is None or q[1] is None or not (0 <= q[0] < q[1] <= 1):
        return None
    return (q[0] + q[1]) / 2.0


def side_ask(q, side):
    """The ask on a side from a yes quote: YES at the yes ask, NO at 1 - the yes bid. None when missing."""
    if not q:
        return None
    if side == "yes":
        return q[1]
    return None if q[0] is None else round(1.0 - q[0], 6)


def fill(w, k, side, delay, mult):
    """(price, fee, None) when the ask on the side at the close of minute k + delay can be paid, else (None, None,
    reason). No trade when that ask is missing or $1.00, or the candle does not show 0 < bid < ask (plan section 3)."""
    m = k + delay
    if m > T_MIN:
        return None, None, "after the window"
    q = quote(w, m)
    if q is None:
        return None, None, "no candle at the fill minute"
    p = side_ask(q, side)
    if p is None:
        return None, None, "ask missing"
    if p >= 1.0 - 1e-9:
        return None, None, "ask $1.00"
    if q[0] is None or q[1] is None or not (0 < q[0] < q[1]):
        return None, None, "candle does not show 0 < bid < ask"
    return p, fee(p, mult), None


def signal(p_up, qk):
    """The side whose model chance beats its ask at minute k by at least 4 points, or None."""
    if p_up is None or qk is None:
        return None
    ya, na = side_ask(qk, "yes"), side_ask(qk, "no")
    if ya is not None and p_up - ya >= EDGE - 1e-9:
        return "yes"
    if na is not None and (1.0 - p_up) - na >= EDGE - 1e-9:
        return "no"
    return None


def reference(w, use_ref):
    """S_0: the market record's reference price when inspect confirmed the field (plan section 4); the spot price at
    the window's open when the field is not used, or is empty on this window's record (counted as a fallback)."""
    if use_ref and w.get("strike") is not None:
        return w["strike"]
    return spot_close(w, 0)


def window_inputs(w, k, use_ref):
    """The per-window values at decision minute k: None fields when not available. Never reads anything after the
    close of minute k except through fill() and the result (scoring only)."""
    o = int(w["open"])
    sig = (w.get("spot") or {}).get("sigma")
    s0 = reference(w, use_ref)
    sk, s1, s5 = spot_close(w, k), spot_close(w, k - 1), spot_close(w, k - 5)
    rw = None
    if sig and s0 and sk and s0 > 0 and sk > 0:
        rw = rw_prob(sk, s0, sig, k)
    qk = quote(w, k)
    mid = mid_of(qk)
    vol = sum((w.get("c") or {}).get(str(m), [None, None, 0.0])[2] or 0.0 for m in range(1, k + 1))
    t_dec = o + 60 * k
    hour = datetime.fromtimestamp(t_dec, timezone.utc).hour
    x = None
    if rw is not None and mid is not None and s1 and s5 and sig:
        x = [L(rw), L(mid), math.log(sk / s1) / sig, math.log(sk / s5) / sig, math.log(sig),
             math.sin(2 * math.pi * hour / 24.0), math.cos(2 * math.pi * hour / 24.0), math.log1p(vol)]
    return dict(rw=rw, mid=mid, qk=qk, x=x)


def spot_complete(w):
    return bool((w.get("spot") or {}).get("complete")) and (w.get("spot") or {}).get("sigma") is not None


def candles_complete(w):
    return all(quote(w, k) is not None for k in KS)


def spot_up(w, use_ref):
    """The spot stand-in's own "up or down" (SPOT_AGREE_MEASURE) against S_0 as the RW model uses it; at or above
    when the market's strike_type is greater_or_equal, strictly above otherwise."""
    s0 = reference(w, use_ref)
    v = ((w.get("spot") or {}).get("m") or {}).get(str(T_MIN))
    if s0 is None or not v:
        return None
    if SPOT_AGREE_MEASURE == "close15":
        s15 = v[3]
    elif SPOT_AGREE_MEASURE == "oc15":
        s15 = (v[0] + v[3]) / 2.0
    elif SPOT_AGREE_MEASURE == "ohlc15":
        s15 = (v[0] + v[1] + v[2] + v[3]) / 4.0
    else:
        raise ValueError("unknown SPOT_AGREE_MEASURE %r" % SPOT_AGREE_MEASURE)
    return s15 >= s0 if w.get("strike_type") == "greater_or_equal" else s15 > s0


def windows(days_obj):
    """[(day, window, the day's recorded fee multiplier)] in time order."""
    out = []
    for d in sorted(days_obj):
        obj = days_obj[d]
        for w in sorted(obj["windows"], key=lambda x: x["close"]):
            out.append((d, w, obj.get("fee_multiplier")))
    return out


def y_of(w):
    return 1.0 if w.get("result") == "yes" else 0.0 if w.get("result") == "no" else None


# ---------- 7. the learned model (plan section 4) ----------
def _solve(A, b):
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if not abs(M[piv][col]) > 1e-300:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(n):
            if r != col:
                f = M[r][col] / M[col][col]
                if f:
                    for j in range(col, n + 1):
                        M[r][j] -= f * M[col][j]
    return [M[i][n] / M[i][i] for i in range(n)]


def standardise(X):
    """Column means and sample SDs (n - 1); a column with no spread keeps SD 1 (its coefficient is then shrunk to 0)."""
    k = len(X[0])
    n = len(X)
    mu = [sum(r[j] for r in X) / n for j in range(k)]
    sd = []
    for j in range(k):
        v = sum((r[j] - mu[j]) ** 2 for r in X) / (n - 1) if n > 1 else 0.0
        sd.append(math.sqrt(v) if v > 0 else 1.0)
    return mu, sd


def fit_ridge_logit(Z, Y, ridge=RIDGE, steps=MAX_STEPS, tol=1e-10):
    """Maximum penalised likelihood (RIDGE_SCALE): sum (or mean) of log-likelihoods - ridge/2 x sum of squared slopes
    (intercept free), by Newton's method. Z: standardised inputs (no intercept column). Returns (intercept, slopes, steps) or None."""
    k = len(Z[0]) + 1
    w = [0.0] * k
    for it in range(steps):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for z, y in zip(Z, Y):
            x = [1.0] + list(z)
            p = P7.sigmoid(sum(a * b for a, b in zip(w, x)))
            r, v = y - p, p * (1.0 - p)
            for i in range(k):
                g[i] += r * x[i]
                xi = v * x[i]
                Hi = H[i]
                for j in range(i, k):
                    Hi[j] += xi * x[j]
        for i in range(k):
            for j in range(i):
                H[i][j] = H[j][i]
        lam = ridge
        if RIDGE_SCALE == "mean":   # mean log-lik - ridge/2 b^2  ==  sum log-lik - n ridge/2 b^2
            lam = ridge * len(Y)
        elif RIDGE_SCALE != "sum":
            raise ValueError("unknown RIDGE_SCALE %r" % RIDGE_SCALE)
        for i in range(1, k):
            g[i] -= lam * w[i]
            H[i][i] += lam
        step = _solve(H, g)
        if step is None:
            return None
        w = [a + s for a, s in zip(w, step)]
        if not all(math.isfinite(a) for a in w):
            return None
        if max(abs(s) for s in step) < tol:
            return w[0], w[1:], it + 1
    return None


def lm_prob(model_ak, x):
    z = [(v - m) / s for v, m, s in zip(x, model_ak["mean"], model_ak["sd"])]
    return P7.sigmoid(model_ak["intercept"] + sum(c * v for c, v in zip(model_ak["coef"], z)))


def fit_rows(days_obj, k, use_ref):
    rows = []
    for d, w, _ in windows(days_obj):
        y = y_of(w)
        if y is None or not spot_complete(w):
            continue
        v = window_inputs(w, k, use_ref)
        if v["x"] is not None:
            rows.append((d, w["ticker"], v["x"], y))
    return rows


def fit(model_path=None, now=None, root=ROOT, data=None, insp=None):
    """Fit the six models once on the find period (plan section 4) and freeze them. Returns (model or None, message).
    data: {asset: {day: day object}} for tests; otherwise the saved find days (all must be there)."""
    model_path = model_path or MODEL
    if os.path.exists(model_path) or os.path.exists(offsite_path(model_path)):
        return None, "already fitted (%s or its off-folder copy exists); the models are fitted once" % model_path
    bad = identity_problems(root)
    if bad:
        return None, "the code is not frozen or differs from the frozen record (%s); nothing fitted" % ", ".join(bad)
    insp = insp or load_inspect()
    p, _ = _read_json(PERIODS)
    first = date.fromisoformat(p["find"][0]) if isinstance(p, dict) else FIND[0]
    if data is None:
        data = {}
        for a in ASSETS:
            got, missing = load_days(a, first, FIND[1])
            if missing:
                return None, "find period not fully downloaded for %s (%d days missing, first %s)" % (a, len(missing), missing[0])
            data[a] = got
    now = time.time() if now is None else now
    out = dict(plan=PLAN, fitted=datetime.fromtimestamp(now, timezone.utc).isoformat(), inputs=list(INPUTS),
               ridge=RIDGE, ridge_scale=RIDGE_SCALE,
               ridge_form="maximise %s of log-likelihood - ridge/2 x sum of squared standardised slopes" % RIDGE_SCALE,
               find=[first.isoformat(), FIND[1].isoformat()], models={})
    for a in ASSETS:
        ur = use_reference(insp, a)
        out["models"][a] = {}
        for k in KS:
            rows = fit_rows(data[a], k, ur)
            if len(rows) < 2:
                out["models"][a][str(k)] = dict(failed="too few rows (%d)" % len(rows), n=len(rows))
                continue
            X = [r[2] for r in rows]
            Y = [r[3] for r in rows]
            mu, sd = standardise(X)
            Z = [[(v - m) / s for v, m, s in zip(x, mu, sd)] for x in X]
            got = fit_ridge_logit(Z, Y)
            if got is None:
                out["models"][a][str(k)] = dict(failed="Newton's method did not converge in %d steps" % MAX_STEPS,
                                                n=len(rows))
                continue
            b0, b, st = got
            out["models"][a][str(k)] = dict(intercept=b0, coef=b, mean=mu, sd=sd, steps=st, n=len(rows),
                                            days=len({r[0] for r in rows}), use_reference_field=ur,
                                            rows_sha256=_sha(json.dumps([[str(r[0]), r[1]] for r in rows])))
    jsonio.save(model_path, out)
    sha = bytes_hash(model_path)
    with open(model_path[:-5] + ".sha256", "w", encoding="utf-8") as f:
        f.write(sha + "\n")
    msgs = [keep_offsite(model_path), keep_offsite(model_path[:-5] + ".sha256")]
    for m in msgs:
        if m:
            print(m)
    failed = ["%s k=%s" % (a, k) for a in out["models"] for k, v in out["models"][a].items() if "failed" in v]
    return out, "fitted and frozen (%s, sha256 %s)%s" % (model_path, sha[:12],
                                                          "; failed fits (their LM tests read not testable): %s" % failed
                                                          if failed else "")


def load_model(model_path=None):
    """(model, None) when the model file is present and matches its recorded hash, else (None, why)."""
    model_path = model_path or MODEL
    sha_path = model_path[:-5] + ".sha256"
    if not os.path.exists(model_path):
        return None, "no model file %s" % model_path
    try:
        with open(sha_path, encoding="utf-8") as f:
            want = f.read().strip()
    except OSError:
        return None, "no recorded model hash %s" % sha_path
    got = bytes_hash(model_path)
    if got != want:
        return None, "the model file's hash %s differs from the recorded %s" % (got, want)
    off = offsite_path(model_path)
    if os.path.exists(off) and bytes_hash(off) != want:
        return None, "the off-folder model copy differs from the recorded hash"
    m, ok = _read_json(model_path)
    return (m, None) if ok and isinstance(m, dict) else (None, "model file damaged")


# ---------- 8. scoring (plan section 5) ----------
def day_series(vals):
    """vals: [(day, value)] -> [(day, mean of that day's values)] in day order."""
    g = {}
    for d, v in vals:
        g.setdefault(d, []).append(v)
    return [(d, sum(g[d]) / len(g[d])) for d in sorted(g)]


def p_one_sided(t, df):
    """P(T > t), one-sided, from PLAN7's pinned Student-t tail."""
    if t is None or df < 1:
        return None
    return P7.t_upper(t, df) if t >= 0 else 1.0 - P7.t_upper(-t, df)


def accuracy(rows, key):
    """Day-mean Brier(model) - Brier(mid), two-sided reading (plan section 5, Q1 and Q3's accuracy; not tested)."""
    vals = [(d, (r[key] - r["y"]) ** 2 - (r["mid"] - r["y"]) ** 2) for d, r in rows if r.get(key) is not None]
    ser = [v for _, v in day_series(vals)]
    out = dict(windows=len(vals), days=len(ser))
    m, se = P7.mean_se(ser)
    if m is None:
        out["reading"] = "too few days"
        return out
    df = len(ser) - 1
    tq = P7.t_quantile(0.025, df)
    out.update(mean=m, se=se, t=(m / se) if se else None, low=m - tq * se, high=m + tq * se)
    out["reading"] = ("the model beat Kalshi's price" if out["high"] < 0 else
                      "Kalshi's price beat the model" if out["low"] > 0 else "no clear difference")
    return out


def evaluate(asset, k, data, insp, model):
    """Per-window rows at decision minute k for the scored period: the RW and LM chances, the mid, the result, and for
    each rule its signal, fill (k+1) and delayed fills (k+3, k+5), the flipped side's fill, and the capacity."""
    ur = use_reference(insp, asset)
    mk = ((model or {}).get("models") or {}).get(asset, {}).get(str(k))
    mk = mk if mk and "failed" not in mk else None
    rows, counts = [], dict(windows=0, missing_spot=0, missing_candles=0, no_result=0, agree=0, agree_n=0,
                            reference_fallback=0)
    for d, w, _ in windows(data):
        counts["windows"] += 1
        if ur and w.get("strike") is None:
            counts["reference_fallback"] += 1
        sc, cc = spot_complete(w), candles_complete(w)
        if not sc:
            counts["missing_spot"] += 1
        if not cc:
            counts["missing_candles"] += 1
        y = y_of(w)
        if y is None:
            counts["no_result"] += 1
            continue
        if sc:
            u = spot_up(w, ur)
            if u is not None:
                counts["agree_n"] += 1
                counts["agree"] += int(u == (y == 1.0))
        if not sc:
            continue
        v = window_inputs(w, k, ur)
        lm = lm_prob(mk, v["x"]) if (mk and v["x"] is not None) else None
        mult = multiplier_at(insp, asset, w["close"])   # never None here: score() refuses unknown multipliers first
        r = dict(ticker=w["ticker"], y=y, rw=v["rw"], lm=lm, mid=v["mid"], trades={})
        for rule, p in (("RW", v["rw"]), ("LM", lm)):
            side = signal(p, v["qk"])
            if side is None:
                continue
            other = "no" if side == "yes" else "yes"
            tr = dict(side=side, fills={}, flip=None, capacity=(w.get("t") or {}).get(str(k + FILL_DELAY), 0.0))
            for delay in (FILL_DELAY,) + LATE_DELAYS:
                price, f, why = fill(w, k, side, delay, mult)
                tr["fills"][delay] = (price, f, why)
            price, f, why = fill(w, k, other, FILL_DELAY, mult)
            tr["flip"] = (price, f, why)
            r["trades"][rule] = tr
        rows.append((d, r))
    return rows, counts


def profit(side, price, f, y):
    win = (y == 1.0) if side == "yes" else (y == 0.0)
    return (1.0 if win else 0.0) - price - f


def trading(rows, rule, delay=FILL_DELAY):
    """The rule's filled trades [(day, profit, row, trade)] at the given fill delay, and no-trade counts by reason."""
    filled, why = [], {}
    for d, r in rows:
        tr = r["trades"].get(rule)
        if not tr:
            continue
        price, f, reason = tr["fills"][delay]
        if price is None:
            why[reason] = why.get(reason, 0) + 1
            continue
        filled.append((d, profit(tr["side"], price, f, r["y"]), r, tr))
    return filled, why


def placebo_share(filled, real_mean, draws=PLACEBO_DRAWS, seed=PLACEBO_SEED):
    """Side-flip placebo (plan section 5): each filled signal's side flipped by a fair coin, paid at that side's own
    ask at the same minute (with its fee); the share of draws whose mean of day means is at least the real one. A
    signal whose flipped side cannot be paid keeps its own side (its ask is the only one there)."""
    rnd = random.Random(seed)
    alt = []
    for d, pr, r, tr in filled:
        fp, ff, why = tr["flip"]
        other = "no" if tr["side"] == "yes" else "yes"
        alt.append((d, pr, profit(other, fp, ff, r["y"]) if fp is not None else pr))
    days = sorted({d for d, _, _ in alt})
    idx = {d: i for i, d in enumerate(days)}
    hit = 0
    for _ in range(draws):
        s = [0.0] * len(days)
        n = [0] * len(days)
        for d, a, b in alt:
            i = idx[d]
            s[i] += b if rnd.random() < 0.5 else a
            n[i] += 1
        m = sum(s[i] / n[i] for i in range(len(days))) / len(days)
        if m >= real_mean - 1e-12:
            hit += 1
    return hit / float(draws)


def rule_stats(rows, rule):
    """Everything the pass rule reads, before Holm assigns its level."""
    signals = [(d, r) for d, r in rows if rule in r["trades"]]
    filled, why = trading(rows, rule)
    ser = day_series([(d, pr) for d, pr, _, _ in filled])
    vals = [v for _, v in ser]
    out = dict(signals=len(signals), signal_days=len({d for d, _ in signals}), filled=len(filled), days=len(vals),
               no_trade=why, sides=dict(yes=sum(1 for *_, tr in filled if tr["side"] == "yes"),
                                        no=sum(1 for *_, tr in filled if tr["side"] == "no")))
    if len(signals) < MIN_SIGNALS or out["signal_days"] < MIN_SIGNAL_DAYS:
        out["not_testable"] = "fewer than %d signals or fewer than %d days with a signal" % (MIN_SIGNALS, MIN_SIGNAL_DAYS)
    m, se = P7.mean_se(vals)
    if m is None:
        out.setdefault("not_testable", "fewer than 2 days with a filled trade")
        return out, filled, vals
    out.update(mean=m, se=se, t=(m / se) if se else None, df=len(vals) - 1,
               per_contract=sum(pr for _, pr, _, _ in filled) / len(filled),
               win_rate=sum(1 for _, pr, _, _ in filled if pr > 0) / float(len(filled)),
               mean_price=sum(tr["fills"][FILL_DELAY][0] for *_, tr in filled) / len(filled))
    out["p"] = p_one_sided(out["t"], out["df"]) if out["t"] is not None else (0.0 if m > 0 else 1.0)
    cap = median([tr["capacity"] for *_, tr in filled])
    out["capacity_median"] = cap
    out["capacity_note"] = "upper bound: contracts traded in the minute after the signal, both sides counted"
    out["profit_at_capacity_per_trade"] = (m * cap) if cap is not None else None
    late = {}
    for dl in LATE_DELAYS:
        f2, _ = trading(rows, rule, dl)
        s2 = [v for _, v in day_series([(d, pr) for d, pr, _, _ in f2])]
        late["k+%d" % dl] = dict(filled=len(f2), days=len(s2), mean=(sum(s2) / len(s2)) if s2 else None)
    out["delayed_fill_placebo"] = late
    return out, filled, vals


def holm(tests):
    """Holm step-down at FAMILY over every test (not-testable tests stay in the count and never pass). Each test's
    level is FAMILY / (m - rank); a test passes only if (1) t > max(2.0, the one-sided t value at that level, df =
    days - 1), (2) the block bootstrap's lower bound at that level is above 0, (3) the side-flip placebo share is at
    most that level, and every test before it passed."""
    m = len(tests)
    order = sorted(tests, key=lambda x: (x["stats"].get("p") if x["stats"].get("p") is not None and
                                         "not_testable" not in x["stats"] else 2.0, x["name"]))
    going = True
    for rank, x in enumerate(order):
        st = x["stats"]
        lvl = FAMILY / (m - rank)
        x["holm_rank"], x["holm_level"] = rank + 1, lvl
        if "not_testable" in st:
            x["verdict"] = NOT_TESTABLE
            x["passed"] = False
            going = False
            continue
        tcut = max(T_FLOOR, P7.t_quantile(lvl, st["df"]))
        ms = P7.boot_means(x["series"], block=BOOT_BLOCK, n=BOOT_DRAWS, seed=BOOT_SEED)
        lo = P7.boot_interval(ms, lvl, 1 - lvl)[0]
        share = placebo_share(x["filled"], st["mean"])
        c1 = st["t"] is not None and st["t"] > tcut
        c2 = lo > 0
        c3 = share <= lvl
        x["checks"] = dict(t=st["t"], t_cut=tcut, t_ok=c1, boot_low=lo, boot_ok=c2, placebo_share=share, placebo_ok=c3)
        x["passed"] = bool(going and c1 and c2 and c3)
        if not x["passed"]:
            going = False
        x["verdict"] = VERDICT_PASS if x["passed"] else VERDICT_FAIL
    return order


def asset_testable(counts):
    """(True, None) or (False, why) for an asset (plan section 5: missing data, spot stand-in agreement). Missing is
    counted against WINDOWS_PER_DAY a day: a window absent from Kalshi's listing, one without a yes/no result after
    the settle lag, and one missing spot or candle data all count."""
    n = counts.get("expected") or counts["windows"]
    if not n:
        return False, "no windows"
    miss = counts["missing"] / float(n)
    if miss > MAX_MISSING:
        return False, "%.1f%% of windows miss spot or candle data (more than 10%%)" % (100 * miss)
    if not counts["agree_n"] or counts["agree"] / float(counts["agree_n"]) < MIN_AGREE:
        return False, "the spot stand-in agrees with Kalshi's result in fewer than 97%% of windows (RW and LM mis-specified)"
    return True, None


def score(today=None, root=ROOT, data=None, insp=None, model_path=None, out_path=None):
    """The single scoring (plan section 5). Returns (result or None, message)."""
    out_path = out_path or RESULT
    md_path = out_path[:-5] + ".md"
    today = today or datetime.now(timezone.utc).date()
    for f in (out_path, md_path):
        if os.path.exists(f) or os.path.exists(offsite_path(f)):
            return None, "already scored (%s or its off-folder copy exists); the plan is scored once" % f
    bad = identity_problems(root)
    if bad:
        return None, "the code is not frozen or differs from the frozen record (%s); no score" % ", ".join(bad)
    model, why = load_model(model_path)
    if model is None:
        return None, "no usable frozen model: %s" % why
    insp = insp or load_inspect()
    for a in ASSETS:
        ft = insp["series"][a]["checks"]["fee_type"]
        if ft not in QUADRATIC:
            return None, "fee type for %s is %r, not quadratic; an amendment comes first" % (a, ft)
    for a in ASSETS:
        fp = fee_problem(insp, a)
        if fp:
            return None, "fee multiplier unknown (%s); an amendment comes first" % fp
    if today < SCORE_FROM:
        return None, "the check period runs to 2026-12-31; score from %s" % SCORE_FROM
    if data is None:
        data = {}
        for a in ASSETS:
            got, missing = load_days(a, CHECK[0], CHECK[1])
            if missing:
                return None, "check period not fully downloaded for %s (%d days missing, first %s)" % (a, len(missing), missing[0])
            data[a] = got
    res = dict(plan=PLAN, scored=datetime.now(timezone.utc).isoformat(), check=[CHECK[0].isoformat(), CHECK[1].isoformat()],
               model_sha256=bytes_hash(model_path or MODEL), assets={}, tests=[],
               settings=dict(placebo_draws=PLACEBO_DRAWS, placebo_seed=PLACEBO_SEED, boot_block_days=BOOT_BLOCK,
                             boot_draws=BOOT_DRAWS, boot_seed=BOOT_SEED, family=FAMILY, edge=EDGE,
                             windows_per_day=WINDOWS_PER_DAY, spot_agree_measure=SPOT_AGREE_MEASURE,
                             ridge_scale=RIDGE_SCALE, carry_forward_quote=CARRY_FORWARD_QUOTE))
    tests = []
    for a in ASSETS:
        info = dict(minutes={})
        cnt = None
        per_k = {}
        for k in KS:
            rows, counts = evaluate(a, k, data[a], insp, model)
            per_k[k] = rows
            if cnt is None:
                cnt = counts
        good = sum(1 for d, w, _ in windows(data[a]) if y_of(w) is not None and spot_complete(w) and candles_complete(w))
        cnt["missing_spot_or_candles"] = sum(1 for d, w, _ in windows(data[a])
                                             if not (spot_complete(w) and candles_complete(w)))
        cnt["expected"] = WINDOWS_PER_DAY * len(data[a])
        cnt["absent"] = max(0, cnt["expected"] - cnt["windows"])
        cnt["missing"] = max(0, cnt["expected"] - good)
        ok, why = asset_testable(cnt)
        info["counts"] = cnt
        info["agreement"] = (cnt["agree"] / float(cnt["agree_n"])) if cnt["agree_n"] else None
        info["testable"] = ok
        if why:
            info["not_testable"] = why
        for k in KS:
            rows = per_k[k]
            acc_rows = [(d, r) for d, r in rows if r["mid"] is not None]
            info["minutes"][str(k)] = dict(Q1=accuracy(acc_rows, "rw"), Q3_accuracy=accuracy(acc_rows, "lm"))
            for rule in ("RW", "LM"):
                st, filled, vals = rule_stats(rows, rule)
                if not ok:
                    st["not_testable"] = why
                if rule == "LM" and not (model["models"].get(a, {}).get(str(k)) or {}).get("coef"):
                    st["not_testable"] = "the learned model's fit failed"
                tests.append(dict(name="%s k=%d %s" % (a, k, rule), asset=a, k=k, rule=rule,
                                  question="Q2" if rule == "RW" else "Q3", stats=st, filled=filled, series=vals))
        res["assets"][a] = info
    holm(tests)
    for x in sorted(tests, key=lambda x: (ASSETS.index(x["asset"]), x["k"], x["rule"])):
        res["tests"].append({k: v for k, v in x.items() if k not in ("filled", "series")})
    passed = [x["name"] for x in res["tests"] if x.get("passed")]
    res["verdict"] = (VERDICT_PASS + " (%s)" % ", ".join(passed)) if passed else VERDICT_FAIL
    spx_d, _ = _read_json(os.path.join(DATA, "spx.json"))
    res["spx_descriptive"] = spx_d
    jsonio.save(out_path, res)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown(res))
    for f in (out_path, md_path):
        err = keep_offsite(f)
        if err:
            print(err)
    return res, res["verdict"]


def _f(v, fmt="%+.4f"):
    return "n/a" if v is None else fmt % v


def markdown(res):
    L_ = ["# PLAN15 result (scored once)", "",
          "Research only (%s); never part of the gate, never connected to live.py. Check period %s to %s (UTC)." % (
              res["plan"], res["check"][0], res["check"][1]), "",
          "**Verdict:** %s" % res["verdict"], ""]
    for a, info in res["assets"].items():
        c = info["counts"]
        L_ += ["## %s" % a, "",
               "- Windows %d of %d expected (absent %d); missing spot or candle data %d; without a yes/no result %d;"
               " counted missing %d; S_0 from the spot because the record's reference field was empty %d; spot"
               " stand-in agrees with Kalshi's result in %s of %d windows%s" % (
                   c["windows"], c["expected"], c["absent"], c["missing_spot_or_candles"], c["no_result"],
                   c["missing"], c.get("reference_fallback", 0),
                   _f(info["agreement"], "%.4f"), c["agree_n"],
                   "" if info["testable"] else " -> tests %s: %s" % (NOT_TESTABLE, info.get("not_testable")))]
        for k, mm in info["minutes"].items():
            for q, d in (("Q1 RW vs mid", mm["Q1"]), ("Q3 LM vs mid", mm["Q3_accuracy"])):
                L_.append("- minute %s, %s (day-mean Brier difference, reported, not tested): %s; mean %s, SE %s, 95%% %s"
                          " to %s, %d days" % (k, q, d.get("reading"), _f(d.get("mean")), _f(d.get("se")),
                                               _f(d.get("low")), _f(d.get("high")), d.get("days", 0)))
        L_.append("")
    L_ += ["## The 12 trading tests (Holm, 2.5% one-sided family)", "",
           "| test | verdict | signals | signal days | filled | day-mean profit | SE | t | t needed | boot low |"
           " placebo share | Holm level | k+3 | k+5 | capacity (upper bound) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in res["tests"]:
        st, ch = x["stats"], x.get("checks") or {}
        late = st.get("delayed_fill_placebo") or {}
        L_.append("| %s | %s%s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            x["name"], x["verdict"], (" (%s)" % st["not_testable"]) if "not_testable" in st else "",
            st["signals"], st["signal_days"], st["filled"], _f(st.get("mean")), _f(st.get("se")),
            _f(st.get("t"), "%.2f"), _f(ch.get("t_cut"), "%.2f"), _f(ch.get("boot_low")),
            _f(ch.get("placebo_share"), "%.4f"), _f(x.get("holm_level"), "%.5f"),
            _f((late.get("k+3") or {}).get("mean")), _f((late.get("k+5") or {}).get("mean")),
            _f(st.get("capacity_median"), "%.0f")))
    L_ += ["", "Settings: %s" % json.dumps(res.get("settings"))]
    L_ += ["", "No-trade cases by test: " + "; ".join("%s %s" % (x["name"], x["stats"].get("no_trade")) for x in res["tests"]),
           "", "Profit is per contract after Kalshi's taker fee, paid at the ask one minute after the signal. Fills"
           " ignore queue and size; the capacity is an upper bound (it counts both sides). The spot price is a"
           " stand-in for Kalshi's settlement index. A pass is a lead on past data only: it earns a forward paper"
           " test, never real money directly (CLAUDE.md section 11a)."]
    if res.get("spx_descriptive"):
        L_ += ["", "S&P 500 15-minute series (descriptive only): %s" % json.dumps(res["spx_descriptive"])]
    return "\n".join(L_) + "\n"


# ---------- 9. status ----------
def status():
    parts = ["PLAN15 (research, not in gate)"]
    parts.append("inspect %s" % ("done" if os.path.exists(INSPECT) else "not run"))
    parts.append("frozen" if os.path.exists(IDENTITY) else "not frozen")
    for a in ASSETS:
        for name, (f, l) in (("find", FIND), ("check", CHECK)):
            n = sum(1 for d in days_of(f, l) if os.path.exists(day_path(a, d)))
            parts.append("%s %s days saved %d of %d" % (a, name, n, len(days_of(f, l))))
    parts.append("model %s" % ("fitted" if os.path.exists(MODEL) else "not fitted"))
    parts.append("scored" if os.path.exists(RESULT) else "not scored")
    if os.path.exists(IDENTITY):
        bad = identity_problems()
        if bad:
            parts.append("CODE CHANGED since the freeze: %s" % ", ".join(bad))
    return "; ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN15: Kalshi's 15-minute BTC and ETH up-or-down markets (research only)")
    ap.add_argument("cmd", choices=("inspect", "freeze", "download", "fit", "score", "status"))
    ap.add_argument("period", nargs="?", choices=("find", "check"))
    ap.add_argument("--max-days", type=int, default=None, help="download at most this many asset-days in this run")
    a = ap.parse_args(argv)
    if a.cmd == "inspect":
        r, msg = inspect()
    elif a.cmd == "freeze":
        r, msg = freeze()
    elif a.cmd == "download":
        if not a.period:
            ap.error("download needs find or check")
        r, msg = download(a.period, max_days=a.max_days)
    elif a.cmd == "fit":
        r, msg = fit()
    elif a.cmd == "score":
        r, msg = score()
    else:
        print(status())
        return 0
    print("PLAN15: " + msg)
    return 0 if r else 2


if __name__ == "__main__":
    sys.exit(main())
