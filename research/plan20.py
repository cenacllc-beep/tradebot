"""PLAN20 (research/PLAN20.md): cheap-side reversals on all of Kalshi's 15-minute markets. A descriptive map of
June-July, one frozen ridge logistic model fitted on June-July, scored once on August-October (four group tests,
BTC/ETH descriptive only). Research and paper only: never part of the gate, never connected to live.py, places nothing,
never reads a market closing on or after 2026-11-01 (La Paz).

Stages (each refuses to run out of turn):
- series: every Kalshi series whose ticker ends in 15M (GET /series, metadata only), each with its asset group;
  written once to research/results/plan20_series.json; prints the group counts and the full "other" list.
- freeze: identity record (SHA-256 of research/PLAN20.md, research/plan20.py, research/plan15.py (shared helpers) and
  the series table, plus PLAN7's pinned statistics functions through PLAN15); stored once in
  research/results/plan20_identity.json. It first re-derives every stored series row's group with group_of() and
  refuses on any difference. Every later stage checks the record.
- download [--max-days N] [--budget-minutes M]: settled yes/no markets of every series in the table closing
  2026-06-01..2026-10-31 La Paz, with their one-minute candles, saved as whole La Paz-day files
  research/data/plan20/days/SERIES/YYYY-MM-DD.json.gz (a day = the La Paz date of the market's close). June-July
  first; August-October only after the model exists and matches its fit-time SHA-256. Resumable (a saved day is
  final, except that a day the format check flagged as short is downloaded again once, before any stage has used it).
  A market whose candle request fails in 3 runs (research/data/plan20/candle_failures.json) is saved marked
  candles_error (no candles, never a chance) so its day is not blocked for good. Ends with a format and count check
  (research/results/plan20_counts.json: markets per series-day, short days, candles_error markets) that reads no
  outcome.
- map: stage A on June-July (descriptive): research/results/plan20_map.md and .json, their SHA-256 in
  research/results/plan20_map_sha256.json. Once.
- fit: stage B's ridge logistic on every June-July chance; research/results/plan20_model.json, and its SHA-256 written
  once to research/results/plan20_model_sha256.json. Once. The score, the August-October download and
  research/live20.py's paper bets refuse a model file whose SHA-256 differs from that record.
- score: once, on August-October; research/results/plan20_result.md, then plan20_result.json.
- status: counts only.

features() and decide() are pure and documented so a live paper logger (research/live20.py) can import them.

Network: Kalshi's public API only (read-only GETs), through PLAN15's client (tbcommon.httpclient.JsonClient, User-Agent
tradebot-paper-research/1.0). Standard library; the fit uses numpy when it is installed (pinned on the runner) and an
identical pure-Python Newton solver otherwise.
  python research/plan20.py series|freeze|download|map|fit|score|status
Python 3.8+."""
import argparse
import hashlib
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
import plan15 as P   # noqa: E402  (frozen shared helpers: hashes, gzip JSON, ISO times, Kalshi client, PLAN7's statistics)
from tbcommon import jsonio   # noqa: E402
from tbcommon.ohlc import field as ohlc_field   # noqa: E402

PLAN = "research/PLAN20.md"
PLAN_SHA256 = "abec08145a3f933f49cb434b661511f747490b49e6385efbf5100132e959d8ef"   # frozen 2026-11-25
CODE_FILES = ("research/plan20.py", "research/plan15.py")
LAPAZ = timezone(timedelta(hours=-4), "La Paz")   # UTC-4 all year (tbcommon.clock.BOT_TZ)

# ---------- the plan's numbers ----------
T = 15                                   # window length, minutes
MINUTES = tuple(range(1, 14))            # decision candles m = 1..13 (section 2)
LAST_CANDLE = 14                         # candles kept: 1..14 (14 = the fill candle of m = 13)
FILL_DELAY = 1
CHEAP = (0.01, 0.10)                     # the side's ask, inclusive
MARGIN = 0.01                            # p >= ask + fee per contract + 0.01
FEE_RATE = 0.07
BET = 1.00                               # dollars per bet: C = floor(1.00 / P)
STRENGTHS = tuple(10.0 ** (-4 + 0.5 * i) for i in range(13))   # 13 log-spaced values 1e-4 .. 1e2
FOLDS = 5
MAX_STEPS = 100
SD_MIN = 1e-9                            # a continuous column with SD at or below this has no spread
FIT_PERIOD = (date(2026, 6, 1), date(2026, 7, 31))     # stage A and stage B (La Paz dates of the close)
SCORE_PERIOD = (date(2026, 8, 1), date(2026, 10, 31))
HARD_END = date(2026, 11, 1)                           # nothing closing on or after this La Paz date is ever read
GROUPS = ("crypto", "metals", "energy", "fx", "other", "btceth")
TESTED = ("crypto", "metals", "energy", "fx")
FAMILY = 0.025
HOLM_LEVELS = tuple(FAMILY / (len(TESTED) - i) for i in range(len(TESTED)))   # 0.625%, 0.833%, 1.25%, 2.5%
BOOT_BLOCK_DAYS, BOOT_DRAWS = 2, 10000
PLACEBO_DRAWS = 4000
MIN_BETS, MIN_DAYS = 300, 30
SEED = 20
ASK_BANDS = (("1-2c", 0.0, 0.03), ("3-5c", 0.03, 0.06), ("6-10c", 0.06, 1.0))   # [lo, hi) with 1e-9 tolerance
LEFT_BANDS = (("1-4", 1, 4), ("5-9", 5, 9), ("10-14", 10, 14))
HOUR_BANDS = 6
SETTLE_LAG = 6 * 3600
KALSHI_PAGE_LIMIT = 1000
MAX_PAGES = 2000
VERDICT_PASS = "lead on past data: earns the stage C forward paper test"
VERDICT_FAIL = "no edge shown"
NOT_TESTABLE = "not testable"

# candle record (one list per minute m): yes bid close, yes ask close, yes bid high, yes bid low, yes ask high,
# yes ask low, last price close, volume, open interest (dollars for prices, contracts for the rest; None = missing)
YB, YA, YBH, YBL, YAH, YAL, LAST, VOL, OI = range(9)
CONT = ("ask", "minutes_left", "d1", "d3", "d5", "high", "low", "pos", "vol_ratio", "spread", "oi_d3")

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data", "plan20")


def _r(name):
    return os.path.join(RESULTS, name)


def series_path():
    return _r("plan20_series.json")


def identity_path():
    return _r("plan20_identity.json")


def map_paths():
    return _r("plan20_map.md"), _r("plan20_map.json"), _r("plan20_map_sha256.json")


def model_path():
    return _r("plan20_model.json")


def model_hash_path():
    return _r("plan20_model_sha256.json")


def candle_failures_path():
    return os.path.join(DATA, "candle_failures.json")


def refetched_path():
    return os.path.join(DATA, "refetched.json")


def result_paths():
    return _r("plan20_result.md"), _r("plan20_result.json")


def counts_path():
    return _r("plan20_counts.json")


def day_path(series, d):
    return os.path.join(DATA, "days", series, "%s.json.gz" % d.isoformat())


# ---------- time ----------
def lapaz_date(ts):
    return datetime.fromtimestamp(ts, LAPAZ).date()


def lapaz_start(d):
    return datetime(d.year, d.month, d.day, tzinfo=LAPAZ).timestamp()


def allowed_close(close_ts):
    """True only for closes in 2026-06-01 00:00 .. 2026-11-01 00:00 La Paz (exclusive): nothing later is ever read."""
    return close_ts is not None and lapaz_start(FIT_PERIOD[0]) <= close_ts < lapaz_start(HARD_END)


def now_iso(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat()


def file_sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


# ---------- network (read-only GETs on Kalshi's public API) ----------
def http_kalshi(path, params=None):
    """GET on Kalshi's public API through PLAN15's client (tests replace this function)."""
    return P._client("kalshi").get(path, params)


def kalshi_pages(path, params, key):
    out, cur, n = [], None, 0
    while True:
        q = dict(params)
        if cur:
            q["cursor"] = cur
        j = http_kalshi(path, q) or {}
        out.extend(j.get(key) or [])
        cur = j.get("cursor")
        n += 1
        if not cur or n >= MAX_PAGES:
            return out


# ---------- series and groups (section 1) ----------
CRYPTO_ROOTS = {"SOL", "XRP", "DOGE", "BNB", "ADA", "HYPE", "LTC", "AVAX", "LINK", "SHIB", "SUI", "DOT", "TRX", "XLM",
                "BCH", "TON", "PEPE", "UNI", "NEAR", "APT", "ARB", "OP", "MATIC", "POL", "ATOM", "XMR", "ETC", "FIL",
                "ICP", "HBAR", "ZEC", "AAVE", "BONK", "WIF", "TRUMP", "ENA", "SEI", "TAO", "CRO", "ONDO", "WLD",
                "RENDER", "INJ", "JUP", "PYTH", "TIA", "KAS", "XTZ", "ALGO", "VET", "FTM", "MNT", "CRV"}
METAL_ROOTS = {"GOLD", "SILVER", "XAU", "XAG", "XAUUSD", "XAGUSD", "PLAT", "PLATINUM", "XPT", "PALLADIUM", "XPD",
               "COPPER", "HG", "GC", "SI"}
ENERGY_ROOTS = {"OIL", "WTI", "BRENT", "CRUDE", "CL", "BZ", "NATGAS", "NG", "GAS", "GASOLINE", "RBOB", "HEATINGOIL",
                "HO", "WTIOIL", "CRUDEOIL"}
CURRENCIES = {"USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD", "CNH", "CNY", "MXN", "SEK", "NOK", "HKD", "SGD",
              "KRW", "INR", "BRL", "ZAR", "TRY",
              # added 2026-11-26 before the freeze and before any data: the series stage found eight more USD pairs
              # (PLAN20 section 1: "FX pairs" is a group), which the first list sent to "other"
              "CZK", "HUF", "IDR", "MYR", "PHP", "PLN", "THB", "TWD"}
FX_ROOTS = {"DXY", "EURO", "YEN", "POUND", "CABLE"}
TITLE_WORDS = (("metals", ("gold", "silver", "platinum", "palladium", "copper")),
               ("energy", ("crude", " oil", "oil ", "wti", "brent", "natural gas", "gasoline", "heating oil")),
               ("fx", ("euro", "yen", "pound", "dollar index", "exchange rate", "eur/usd", "usd/jpy", "gbp/usd",
                       "forex", " fx")),
               ("crypto", ("solana", "ripple", "dogecoin", "crypto", "coin", "token", "litecoin", "cardano",
                           "avalanche", "chainlink", "polkadot", "hyperliquid")))


def root_of(ticker):
    t = (ticker or "").upper()
    if t.startswith("KX"):
        t = t[2:]
    if t.endswith("15M"):
        t = t[:-3]
    return t.rstrip("-_")


def group_of(ticker, title=""):
    """(group, the rule that placed it). BTC and ETH (any series on those two assets) form the descriptive btceth row;
    then the root's own name; then a currency pair; then words in the series title; else "other" (never tested)."""
    r = root_of(ticker)
    if r in ("BTC", "ETH") or (r.startswith("BTC") or (r.startswith("ETH") and not r.startswith("ETHFI"))):
        return "btceth", "root %s is BTC or ETH" % r
    for g, roots in (("crypto", CRYPTO_ROOTS), ("metals", METAL_ROOTS), ("energy", ENERGY_ROOTS), ("fx", FX_ROOTS)):
        if r in roots:
            return g, "root %s" % r
    if len(r) == 6 and r[:3] in CURRENCIES and r[3:] in CURRENCIES:
        return "fx", "currency pair %s/%s" % (r[:3], r[3:])
    low = " %s " % (title or "").lower()
    for w in ("bitcoin", "ethereum", " ether "):
        if w in low:
            return "btceth", "title word %r" % w.strip()
    for g, words in TITLE_WORDS:
        for w in words:
            if w in low:
                return g, "title word %r" % w.strip()
    return "other", "no rule matched (root %s)" % r


def list_series():
    """Every series from GET /series (no filter, so inactive ones are listed too) whose ticker ends in 15M."""
    rows = kalshi_pages("/series", {}, "series")
    out = {}
    for s in rows:
        t = (s.get("ticker") or "").strip()
        if t.upper().endswith("15M") and t not in out:
            g, why = group_of(t, s.get("title") or "")
            out[t] = dict(ticker=t, title=s.get("title"), category=s.get("category"), frequency=s.get("frequency"),
                          fee_type=s.get("fee_type"), fee_multiplier=s.get("fee_multiplier"), group=g, group_rule=why)
    return [out[k] for k in sorted(out)]


def make_series(path=None, now=None, root=ROOT):
    path = path or series_path()
    if os.path.exists(path):
        return None, "the series table exists (%s); it is written once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN20.md differs from its frozen SHA-256; nothing saved"
    rows = list_series()
    if not rows:
        return None, "Kalshi listed no series ending in 15M; nothing saved"
    by = {}
    for s in rows:
        by.setdefault(s["group"], []).append(s["ticker"])
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, listed=now_iso(now), source="GET /series (no filter), ticker ends in 15M",
               series=rows, groups={g: by.get(g, []) for g in GROUPS},
               note="fee_type and fee_multiplier are recorded only; the plan's fee is 0.07 x C x P x (1-P) (section 2)")
    jsonio.save(path, rec)
    return rec, "series table written (%s)\n%s" % (path, group_report(rec))


def group_report(rec):
    """Group counts and the full list of series placed in "other" (never tested), for the series stage's output."""
    counts = {g: len(rec["groups"].get(g) or []) for g in GROUPS}
    other = ["%s (%s)" % (s["ticker"], s.get("title") or "") for s in rec["series"] if s.get("group") == "other"]
    return "group counts: %s\n\"other\" (%d, never tested): %s" % (counts, len(other), "; ".join(other) or "none")


def group_mismatches(srec):
    """Series rows whose stored group differs from the frozen grouping code's group_of(ticker, title), and group lists
    that differ from the rows: [] when every row agrees."""
    bad, by = [], {}
    for s in srec.get("series") or []:
        t = s.get("ticker")
        g = group_of(t, s.get("title") or "")[0] if isinstance(t, str) else None
        if g is None or s.get("group") != g:
            bad.append("%s: stored %s, group_of gives %s" % (t, s.get("group"), g))
        if g is not None:
            by.setdefault(g, []).append(t)
    for g in GROUPS:
        if sorted((srec.get("groups") or {}).get(g) or []) != sorted(by.get(g, [])):
            bad.append("group list %s differs from the rows" % g)
    return bad


def load_series(path=None):
    rec, ok = P._read_json(path or series_path())
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("series"), list) or not rec["series"]:
        return None
    return rec


# ---------- identity (section 8) ----------
def identity_now(root=ROOT, spath=None):
    out = {PLAN: P.file_hash(os.path.join(root, *PLAN.split("/")))}
    out.update({f: P.file_hash(os.path.join(root, *f.split("/"))) for f in CODE_FILES})
    out["research/results/plan20_series.json"] = file_sha(spath or series_path())
    return out


def identity_problems(root=ROOT, path=None, spath=None):
    """[] when the identity record exists and the plan, the code and the series table still match it."""
    rec, ok = P._read_json(path or identity_path())
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root, spath)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        bad.append("research/PLAN20.md differs from its frozen SHA-256")
    return bad + P.plan7_problems(root)


def freeze(root=ROOT, path=None, spath=None, now=None):
    path = path or identity_path()
    if os.path.exists(path):
        return None, "already frozen (%s); stored once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN20.md differs from its frozen SHA-256; nothing saved"
    srec = load_series(spath)
    if srec is None:
        return None, "no series table (run series first); nothing saved"
    gm = group_mismatches(srec)
    if gm:
        return None, "the series table's groups differ from group_of (%s); nothing saved" % "; ".join(gm)
    p7 = P.plan7_problems(root)
    if p7:
        return None, "PLAN7's pinned functions differ (%s); nothing saved" % ", ".join(p7)
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, identity=identity_now(root, spath), frozen=now_iso(now))
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read"
    jsonio.save(path, rec)
    return rec, "frozen: %s" % path


# ---------- download (section 1) ----------
def market_list(series, first, last):
    """{ticker: record} for the series' markets closing on La Paz dates first..last (never past 2026-10-31), from Kalshi's
    archive and its live listing. Only settled yes/no markets are kept; the result is kept for the day file, never
    printed. Records outside the dates are dropped as they arrive."""
    lo = lapaz_start(first)
    hi = min(lapaz_start(last + timedelta(days=1)), lapaz_start(HARD_END))
    out, skipped = {}, dict(not_yes_no=0)
    # The archive gets no time filter (as research/plan15.py asks it); the live listing is bounded. Both are filtered
    # here by the close time, so nothing outside first..last or past 2026-10-31 is kept.
    base = dict(series_ticker=series, limit=KALSHI_PAGE_LIMIT)
    for path, q in (("/historical/markets", base),
                    ("/markets", dict(base, min_close_ts=int(lo), max_close_ts=int(hi) - 1))):
        for m in kalshi_pages(path, q, "markets"):
            c = P.ts_of(m.get("close_time"))
            if c is None or not (lo <= c < hi) or not allowed_close(c) or m.get("ticker") in out:
                continue
            if m.get("result") not in ("yes", "no"):
                skipped["not_yes_no"] += 1
                continue
            out[m["ticker"]] = dict(ticker=m["ticker"], close=c, open=c - T * 60, open_listed=P.ts_of(m.get("open_time")),
                                    result=m["result"], hist=path.startswith("/historical"))
    return out, skipped


def parse_candles(cs, open_ts):
    """{str(m): [YB, YA, YBH, YBL, YAH, YAL, LAST, VOL, OI]} for Kalshi candles with end_period_ts = open + 60 m,
    1 <= m <= 14."""
    out = {}
    for c in cs or []:
        try:
            e = int(c["end_period_ts"])
        except (KeyError, TypeError, ValueError):
            continue
        m, r = divmod(e - int(open_ts), 60)
        if r or not 1 <= m <= LAST_CANDLE:
            continue
        yb, ya, pr = c.get("yes_bid") or {}, c.get("yes_ask") or {}, c.get("price") or {}
        vol = P.num(c.get("volume_fp"))
        vol = vol if vol is not None else P.num(c.get("volume"))
        oi = P.num(c.get("open_interest_fp"))
        oi = oi if oi is not None else P.num(c.get("open_interest"))
        out[str(m)] = [ohlc_field(yb, "close"), ohlc_field(ya, "close"), ohlc_field(yb, "high"), ohlc_field(yb, "low"),
                       ohlc_field(ya, "high"), ohlc_field(ya, "low"), ohlc_field(pr, "close"), vol or 0.0, oi]
    return out


def fetch_candles(m):
    """One market's one-minute candles from its window start to its close (archive or live endpoint). Refuses any
    market closing on or after 2026-11-01 La Paz."""
    if not allowed_close(m.get("close")):
        raise ValueError("refused: %s closes outside the plan's period" % m.get("ticker"))
    q = dict(start_ts=int(m["open"]), end_ts=int(m["close"]), period_interval=1)
    if m.get("hist"):
        j = http_kalshi("/historical/markets/%s/candlesticks" % m["ticker"], q) or {}
    else:
        j = http_kalshi("/series/%s/markets/%s/candlesticks" % (m["ticker"].split("-")[0], m["ticker"]), q) or {}
    return j.get("candlesticks") or []


CANDLE_TRIES = 3            # runs a market's candle request may fail before its day is saved without its candles
NET_ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException)
MARKETS_PER_DAY = 96        # format check only: a full day of a 15-minute series


def build_day(series, d, recs, failures=None):
    """The day file. A market whose candle request fails holds its day back (RuntimeError: nothing saved, the next run
    tries again) and adds one to its count in `failures` ({ticker: failed runs}); once it has failed CANDLE_TRIES runs
    it is saved marked candles_error (no candles, so never a chance) and the day is no longer blocked."""
    failures = {} if failures is None else failures
    ms, waiting = [], []
    for m in sorted(recs, key=lambda x: (x["close"], x["ticker"])):
        try:
            cs = fetch_candles(m)
        except NET_ERRORS as ex:
            n = int(failures.get(m["ticker"], 0)) + 1
            failures[m["ticker"]] = n
            if n < CANDLE_TRIES:
                waiting.append("%s (%s; failed run %d of %d)" % (m["ticker"], ex, n, CANDLE_TRIES))
                continue
            ms.append(dict(ticker=m["ticker"], close=m["close"], open=m["open"], open_listed=m["open_listed"],
                           result=m["result"], c={}, n_candles=0, candles_error=True, candle_error=str(ex)[:200]))
            continue
        ms.append(dict(ticker=m["ticker"], close=m["close"], open=m["open"], open_listed=m["open_listed"],
                       result=m["result"], c=parse_candles(cs, m["open"]), n_candles=len(cs)))
    if waiting:
        raise RuntimeError("candles not read: %s" % "; ".join(waiting))
    return dict(series=series, day=d.isoformat(), day_rule="La Paz date of the close", markets=ms, complete=True)


def _load_state(path):
    obj, ok = P._read_json(path)
    return obj if ok and isinstance(obj, dict) else {}


def refetch_short_days(log=print):
    """Series-days the last format check flagged as short (see format_check) are downloaded again, once each: the first
    copy is moved to research/data/plan20/refetched/ and the day is marked in refetched.json before it is moved, so no
    day is re-read twice. Only days whose data no stage has used yet: June-July before the map exists, August-October
    before the result exists. Returns the moved (series, day) pairs."""
    chk, ok = P._read_json(counts_path())
    if not ok or not isinstance(chk, dict):
        return []
    done = _load_state(refetched_path())
    map_made = any(os.path.exists(f) for f in map_paths())
    scored = any(os.path.exists(f) for f in result_paths())
    moved = []
    for e in chk.get("short_days") or []:
        try:
            s, d = e["series"], date.fromisoformat(e["day"])
        except (KeyError, TypeError, ValueError):
            continue
        if d.isoformat() in (done.get(s) or []):
            continue
        if (FIT_PERIOD[0] <= d <= FIT_PERIOD[1] and map_made) or (SCORE_PERIOD[0] <= d <= SCORE_PERIOD[1] and scored) \
                or not (FIT_PERIOD[0] <= d <= SCORE_PERIOD[1]):
            continue
        src = day_path(s, d)
        if not os.path.exists(src):
            continue
        done.setdefault(s, []).append(d.isoformat())
        jsonio.save(refetched_path(), done)
        dst = os.path.join(DATA, "refetched", s, os.path.basename(src))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        moved.append((s, d))
        log("PLAN20 %s %s: %s markets saved; downloading it again (once)" % (s, d, e.get("markets")))
    return moved


def all_series(srec):
    return [s["ticker"] for s in srec["series"]]


def download(max_days=None, budget_minutes=None, log=print, now=None, root=ROOT):
    bad = identity_problems(root)
    if bad:
        return False, "not frozen or changed (%s); no download" % ", ".join(bad)
    srec = load_series()
    start = time.time()
    now = time.time() if now is None else now
    fitted = os.path.exists(model_path())
    if fitted:   # August-October only for the model written at fit time
        mh = model_hash_problem()
        if mh:
            return False, "%s; no download" % mh
    last = SCORE_PERIOD[1] if fitted else FIT_PERIOD[1]
    refetch_short_days(log)
    failures = _load_state(candle_failures_path())
    done = waiting = 0
    for s in all_series(srec):
        want = [d for d in P.days_of(FIT_PERIOD[0], last) if not os.path.exists(day_path(s, d))
                and lapaz_start(d) + 86400 + SETTLE_LAG <= now]
        if not want:
            continue
        if (max_days is not None and done >= max_days) or \
                (budget_minutes is not None and time.time() - start > 60 * budget_minutes):
            waiting += len(want)
            continue
        try:
            recs, skipped = market_list(s, want[0], want[-1])
        except (RuntimeError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as ex:
            log("PLAN20 %s: listing failed (%s); run again to retry" % (s, ex))
            waiting += len(want)
            continue
        by_day = {}
        for m in recs.values():
            by_day.setdefault(lapaz_date(m["close"]), []).append(m)
        for d in want:
            if (max_days is not None and done >= max_days) or \
                    (budget_minutes is not None and time.time() - start > 60 * budget_minutes):
                waiting += 1
                continue
            n_fail = dict(failures)
            try:
                obj = build_day(s, d, by_day.get(d, []), failures)
            except NET_ERRORS as ex:
                if failures != n_fail:
                    jsonio.save(candle_failures_path(), failures)
                log("PLAN20 %s %s: not saved (%s); run again to retry" % (s, d, ex))
                waiting += 1
                continue
            if failures != n_fail:
                jsonio.save(candle_failures_path(), failures)
            obj["listing_skipped"] = skipped
            obj["n_markets"] = len(obj["markets"])
            P.save_gz(day_path(s, d), obj)
            done += 1
            nerr = sum(1 for m in obj["markets"] if m.get("candles_error"))
            log("PLAN20 %s %s: %d markets saved%s" % (s, d, len(obj["markets"]), (
                ", %d marked candles_error after %d failed runs" % (nerr, CANDLE_TRIES)) if nerr else ""))
    chk = format_check(srec)
    jsonio.save(counts_path(), chk)
    for e in chk["short_days"]:
        log("PLAN20 format check: %s %s has %d markets (the days before and after have markets)%s" % (
            e["series"], e["day"], e["markets"], "; already downloaded again once" if e["refetched"] else ""))
    note = "" if fitted else " (August-October waits for the fit)"
    return True, "download: %d series-days saved this run, %d waiting%s; format check: %s" % (
        done, waiting, note, chk["summary"])


def format_check(srec=None):
    """Counts and a format check of the saved day files. Reads no outcome (never the result field)."""
    srec = srec or load_series()
    out = dict(checked=now_iso(), series={}, summary={}, short_days=[])
    tot = dict(days=0, markets=0, candles=0, crossed=0, out_of_range=0, open_differs=0, late=0, damaged=0,
               candles_error=0)
    refetched = _load_state(refetched_path())
    for s in all_series(srec):
        e = dict(fit_days=0, score_days=0, markets=0, candles=0, crossed=0, out_of_range=0, open_differs=0, late=0,
                 damaged=0, candles_error=0, keys_ok=True, day_markets={})
        for d in P.days_of(FIT_PERIOD[0], SCORE_PERIOD[1]):
            p = day_path(s, d)
            if not os.path.exists(p):
                continue
            obj, ok = P._read_json(p)
            if not ok or not isinstance(obj, dict) or not obj.get("complete"):
                e["damaged"] += 1
                continue
            e["fit_days" if d <= FIT_PERIOD[1] else "score_days"] += 1
            e["day_markets"][d.isoformat()] = len(obj.get("markets") or [])
            for m in obj.get("markets") or []:
                e["markets"] += 1
                e["candles_error"] += int(bool(m.get("candles_error")))
                e["keys_ok"] = e["keys_ok"] and all(k in m for k in ("ticker", "close", "open", "c"))
                e["late"] += int(not allowed_close(m.get("close")))
                if m.get("open_listed") is not None and abs(m["open_listed"] - m["open"]) > 0.5:
                    e["open_differs"] += 1
                for c in (m.get("c") or {}).values():
                    e["candles"] += 1
                    px = [c[i] for i in (YB, YA, YBH, YBL, YAH, YAL, LAST) if c[i] is not None]
                    e["out_of_range"] += int(any(v < 0 or v > 1 for v in px))
                    e["crossed"] += int(c[YB] is not None and c[YA] is not None and c[YB] > c[YA])
        out["series"][s] = e
        tot["days"] += e["fit_days"] + e["score_days"]
        for k in ("markets", "candles", "crossed", "out_of_range", "open_differs", "late", "damaged", "candles_error"):
            tot[k] += e[k]
        # a saved day with 0 or fewer than 96 markets while the saved days before and after both have markets
        dm = e["day_markets"]
        for k, n in sorted(dm.items()):
            d = date.fromisoformat(k)
            before, after = dm.get((d - timedelta(days=1)).isoformat()), dm.get((d + timedelta(days=1)).isoformat())
            if n < MARKETS_PER_DAY and before and after:
                out["short_days"].append(dict(series=s, day=k, markets=n, before=before, after=after,
                                              refetched=k in (refetched.get(s) or [])))
    tot["short_days"] = len(out["short_days"])
    tot["candles_per_market"] = (tot["candles"] / float(tot["markets"])) if tot["markets"] else None
    out["summary"] = tot
    return out


# ---------- data loading ----------
def load_days(series_list, first, last):
    """{(series, day): day object} for every series-day in first..last, or (None, why) when one is not saved yet."""
    out = {}
    for s in series_list:
        for d in P.days_of(first, last):
            obj, ok = P._read_json(day_path(s, d))
            if not (ok and isinstance(obj, dict) and obj.get("complete")):
                return None, "%s %s is not saved yet" % (s, d)
            out[(s, d)] = obj
    return out, None


def windows_of(data, groups):
    """[(day, series, group, close, [markets sorted by ticker])] in time order: one window per series and close time.
    Markets closing outside the plan's period are dropped (none should be there)."""
    w = {}
    for (s, d), obj in data.items():
        for m in obj.get("markets") or []:
            if not allowed_close(m.get("close")):
                continue
            w.setdefault((m["close"], s), dict(day=lapaz_date(m["close"]), ms=[]))["ms"].append(m)
    out = []
    for (close, s) in sorted(w):
        e = w[(close, s)]
        out.append((e["day"], s, groups.get(s, "other"), close, sorted(e["ms"], key=lambda m: m["ticker"])))
    return out


def y_of(m):
    return 1.0 if m.get("result") == "yes" else 0.0 if m.get("result") == "no" else None


def wins(side, y):
    return 1.0 if ((y == 1.0) if side == "yes" else (y == 0.0)) else 0.0


# ---------- prices, features and the rule (section 2; pure functions, also for research/live20.py) ----------
def _inv(v):
    return None if v is None else round(1.0 - v, 6)


def as_record(c):
    """A candle as the record [YB, YA, YBH, YBL, YAH, YAL, LAST, VOL, OI]. Accepts the record itself, or a dict of
    scalars as a live logger keeps them: yes_bid, yes_ask (dollars), optional yes_bid_high/low and yes_ask_high/low,
    last, volume (that minute's contracts), open_interest. Missing highs and lows stay None (the close stands in for
    the window's high and low; hhhl is then 0). None stays None."""
    if c is None or isinstance(c, (list, tuple)):
        return c
    g = lambda k: P.num(c.get(k))   # noqa: E731
    return [g("yes_bid"), g("yes_ask"), g("yes_bid_high"), g("yes_bid_low"), g("yes_ask_high"), g("yes_ask_low"),
            g("last"), g("volume") or 0.0, g("open_interest")]


def side_prices(c, side):
    """(bid, ask, ask high, ask low) of a side in one candle record. YES: yes bid, yes ask and the yes ask's high and
    low. NO: bid = 1 - yes ask, ask = 1 - yes bid, ask high = 1 - yes bid low, ask low = 1 - yes bid high."""
    if c is None:
        return None, None, None, None
    if side == "yes":
        return c[YB], c[YA], c[YAH], c[YAL]
    return _inv(c[YA]), _inv(c[YB]), _inv(c[YBL]), _inv(c[YBH])


def _carried(cs, i, side, k):
    """The side's value k (0 bid, 1 ask) at candle i, carried forward from the latest earlier candle (>= 1) that has
    it; None when no candle at or before i has it."""
    for j in range(i, 0, -1):
        c = cs.get(j)
        if c is not None:
            v = side_prices(c, side)[k]
            if v is not None:
                return v
    return None


def _carried_raw(cs, i, idx):
    for j in range(i, 0, -1):
        c = cs.get(j)
        if c is not None and c[idx] is not None:
            return c[idx]
    return None


def is_cheap(ask):
    return ask is not None and CHEAP[0] - 1e-9 <= ask <= CHEAP[1] + 1e-9


def features(candles_so_far, side, m, market_meta):
    """The section 2 features of (market, m, side), from candles 1..m only (later candles in the input are ignored, so
    nothing after the close of candle m can enter). Returns None when the side has no ask at or before candle m.

    candles_so_far: {m (int or str): candle record [YB, YA, YBH, YBL, YAH, YAL, LAST, VOL, OI]} (see parse_candles), or
    a dict of scalars (see as_record).
    side: "yes" or "no". m: 1..13. market_meta: dict(open=window start in Unix seconds, series=ticker, group=group).
    Returned dict: the continuous features CONT (ask; minutes_left = 15 - m; d1, d3, d5 = the side's ask change over the
    last 1, 3, 5 minutes (0 when no earlier ask); high and low of the side's ask so far (candle highs and lows of
    candles 1..m and the current ask); pos = where the ask sits between them (0.5 when equal); vol_ratio = volume of
    candles m-2..m over candles 1..m (0 when none); spread = side ask - side bid (a missing bid counts as 0); oi_d3 =
    open interest change over the last 3 minutes (0 when missing)), hhhl (1 when candles m-2, m-1, m all exist and made
    strictly higher highs and higher lows of the side's ask), hour_band (La Paz hour // 4 at the end of candle m),
    weekday (La Paz, Monday 0), series, group. Quotes may be carried forward; fills never are (fill())."""
    cs = {}
    for k, v in (candles_so_far or {}).items():
        i = int(k)
        if 1 <= i <= m and v is not None:
            cs[i] = as_record(v)
    ask = _carried(cs, m, side, 1)
    if ask is None:
        return None
    bid = _carried(cs, m, side, 0)
    f = dict(ask=ask, minutes_left=float(T - m))
    for j in (1, 3, 5):
        prev = _carried(cs, m - j, side, 1) if m - j >= 1 else None
        f["d%d" % j] = (ask - prev) if prev is not None else 0.0
    his, los = [ask], [ask]
    for j in range(1, m + 1):
        c = cs.get(j)
        if c is None:
            continue
        _, a, h, l = side_prices(c, side)
        h = h if h is not None else a
        l = l if l is not None else a
        if h is not None:
            his.append(h)
        if l is not None:
            los.append(l)
    hi, lo = max(his), min(los)
    f["high"], f["low"] = hi, lo
    f["pos"] = (ask - lo) / (hi - lo) if hi > lo + 1e-12 else 0.5
    v3 = sum((cs[j][VOL] or 0.0) for j in range(max(1, m - 2), m + 1) if j in cs)
    va = sum((cs[j][VOL] or 0.0) for j in range(1, m + 1) if j in cs)
    f["vol_ratio"] = v3 / va if va > 0 else 0.0
    f["spread"] = ask - (bid if bid is not None else 0.0)
    oi_now = _carried_raw(cs, m, OI)
    oi_prev = _carried_raw(cs, m - 3, OI) if m - 3 >= 1 else None
    f["oi_d3"] = (oi_now - oi_prev) if (oi_now is not None and oi_prev is not None) else 0.0
    hh = 0.0
    if all(j in cs for j in (m - 2, m - 1, m)) and m >= 3:
        hl = [side_prices(cs[j], side)[2:] for j in (m - 2, m - 1, m)]
        if all(h is not None and l is not None for h, l in hl):
            if hl[0][0] < hl[1][0] < hl[2][0] and hl[0][1] < hl[1][1] < hl[2][1]:
                hh = 1.0
    f["hhhl"] = hh
    t = datetime.fromtimestamp(int(market_meta["open"]) + 60 * m, LAPAZ)
    f["hour_band"] = t.hour // 4
    f["weekday"] = t.weekday()
    f["series"] = market_meta.get("series")
    f["group"] = market_meta.get("group") or "other"
    return f


def design_row(f, series_list):
    """The model's input row: CONT (raw), hhhl, 6 hour bands, 7 weekdays, 6 groups, then one indicator per series seen
    in the fit (a series never seen gets 0 everywhere there and keeps its group indicator)."""
    row = [float(f[k]) for k in CONT] + [float(f["hhhl"])]
    row += [1.0 if f["hour_band"] == b else 0.0 for b in range(HOUR_BANDS)]
    row += [1.0 if f["weekday"] == w else 0.0 for w in range(7)]
    row += [1.0 if f["group"] == g else 0.0 for g in GROUPS]
    row += [1.0 if f["series"] == s else 0.0 for s in series_list]
    return row


def input_names(series_list):
    return list(CONT) + ["hhhl"] + ["hour_band_%d" % b for b in range(HOUR_BANDS)] + \
        ["weekday_%d" % w for w in range(7)] + ["group_%s" % g for g in GROUPS] + ["series_%s" % s for s in series_list]


def contracts(price):
    """C = floor(1.00 / P): the contracts a $1 bet buys at price P."""
    return int(math.floor(BET / price + 1e-9))


def fee(price, centicent=False):
    """Kalshi's taker fee on a $1 bet at price P: round up(0.07 x C x P x (1 - P)) to the cent (to the centicent for the
    descriptive version), C = floor(1.00 / P)."""
    c = contracts(price)
    unit = 10000 if centicent else 100
    return math.ceil(FEE_RATE * c * price * (1 - price) * unit - 1e-9) / unit


def fee_per_contract(price, centicent=False):
    c = contracts(price)
    return fee(price, centicent) / c if c else None


def threshold(ask):
    """The rule's line: ask + fee per contract (at the decision ask) + 0.01."""
    return ask + fee_per_contract(ask) + MARGIN


def prob(model, row):
    k = len(model["mean"])
    z = [(v - mu) / sd for v, mu, sd in zip(row[:k], model["mean"], model["sd"])] + list(row[k:])
    return P.P7.sigmoid(model["intercept"] + sum(c * v for c, v in zip(model["coef"], z)))


class Decision(dict):
    """dict(p, threshold, bet) whose truth value is `bet` (so `if decide(...)` means "bet")."""

    def __bool__(self):
        return bool(self.get("bet"))

    __nonzero__ = __bool__


def decide(model, feats, ask=None):
    """The frozen rule (section 4): Decision(p, threshold, bet), true only when bet is True. p is the model's chance that
    the side wins; bet is True when the side's ask is 1-10c and p >= ask + fee per contract (whole-cent fee of a $1 bet
    at that ask) + 0.01. ask defaults to feats["ask"]; feats None (no ask yet) never bets."""
    if feats is None:
        return Decision(p=None, threshold=None, bet=False)
    ask = feats["ask"] if ask is None else ask
    if not is_cheap(ask):
        return Decision(p=None, threshold=None, bet=False)
    p = prob(model, design_row(feats, model["series"]))
    thr = threshold(ask)
    return Decision(p=p, threshold=thr, bet=bool(p >= thr - 1e-12))


def fill(candles, m, side):
    """(price, None) when the side can be bought in candle m + 1: that candle exists (no carry-forward), shows
    0 < bid < ask for the side, and the ask is at most 10c; else (None, reason)."""
    c = (candles or {}).get(str(m + FILL_DELAY))
    if c is None:
        c = (candles or {}).get(m + FILL_DELAY)
    if c is None:
        return None, "no candle at the fill minute"
    bid, ask = side_prices(as_record(c), side)[:2]
    if bid is None or ask is None:
        return None, "bid or ask missing"
    if not (0 < bid < ask):
        return None, "candle does not show 0 < bid < ask"
    if ask > CHEAP[1] + 1e-9:
        return None, "ask above 10c"
    return ask, None


def ask_band(ask):
    for name, lo, hi in ASK_BANDS:
        if lo - 1e-9 <= ask < hi - 1e-9:
            return name
    return ASK_BANDS[-1][0]


def left_band(m):
    left = T - m
    for name, lo, hi in LEFT_BANDS:
        if lo <= left <= hi:
            return name
    return None


def move3(d3):
    return "falling" if d3 < -1e-12 else "rising" if d3 > 1e-12 else "flat"


def chances(markets, meta):
    """Every chance of one window in the rule's order: minutes in order, then markets by ticker, YES before NO.
    Yields (m, market, side, features). A market saved as candles_error (its candles could not be read) is never a
    chance."""
    for m in MINUTES:
        for mk in markets:
            if mk.get("candles_error"):
                continue
            cs = mk.get("c") or {}
            for side in ("yes", "no"):
                f = features(cs, side, m, dict(meta, open=mk["open"]))
                if f is not None and is_cheap(f["ask"]):
                    yield m, mk, side, f


def bet_row(day, series, group, m, side, ask, price, win, p=None, ticker=None):
    c = contracts(price)
    fc, fcc = fee(price), fee(price, True)
    return dict(day=day, series=series, group=group, ticker=ticker, m=m, side=side, ask=ask, price=price, contracts=c,
                fee=fc, fee_cc=fcc, win=win, p=p, band=ask_band(ask), left=left_band(m),
                profit=win - price - fc / c, profit_cc=win - price - fcc / c, breakeven=price + fc / c)


# ---------- statistics ----------
def tq(df):
    return P.P7.t_quantile(0.025, df) if df >= 1 else None


def clustered(rows, key="profit"):
    """(mean over rows, day-clustered SE, days)."""
    n = len(rows)
    if not n:
        return None, None, 0
    mean = sum(r[key] for r in rows) / float(n)
    g = {}
    for r in rows:
        g[r["day"]] = g.get(r["day"], 0.0) + (r[key] - mean)
    D = len(g)
    if D < 2:
        return mean, None, D
    return mean, math.sqrt(sum(v * v for v in g.values()) * D / (D - 1.0)) / n, D


def t_reading(rows, key="profit"):
    m, se, D = clustered(rows, key)
    if m is None or se is None:
        return dict(mean=m, se=se, days=D, t=None, df=None, p_t=None)
    t = m / se if se > 0 else (float("inf") if m > 0 else float("-inf"))
    p = P.p_one_sided(t, D - 1) if math.isfinite(t) else (0.0 if t > 0 else 1.0)
    return dict(mean=m, se=se, days=D, t=t, df=D - 1, p_t=p)


def boot_p(rows, period_days, key="profit", draws=None, seed=SEED):
    """2-day calendar blocks of the period (the last day alone when the count is odd), drawn with replacement as many
    times as there are blocks; a draw's statistic is the mean over its bets. Share of draws at or below zero."""
    draws = draws or BOOT_DRAWS
    by = {}
    for r in rows:
        s = by.setdefault(r["day"], [0.0, 0])
        s[0] += r[key]
        s[1] += 1
    blocks = []
    for i in range(0, len(period_days), BOOT_BLOCK_DAYS):
        tot = [0.0, 0]
        for d in period_days[i:i + BOOT_BLOCK_DAYS]:
            if d in by:
                tot[0] += by[d][0]
                tot[1] += by[d][1]
        blocks.append(tot)
    if not any(b[1] for b in blocks):
        return None
    rnd = random.Random(seed)
    nb = len(blocks)
    done = low = 0
    while done < draws:
        s = n = 0
        for _ in range(nb):
            b = blocks[rnd.randrange(nb)]
            s += b[0]
            n += b[1]
        if n:
            done += 1
            low += int(s / n <= 0)
    return low / float(draws)


def placebo_cells(rows):
    """{(day, ask band, m): count} of the rule's bets."""
    out = {}
    for r in rows:
        k = (r["day"], r["band"], r["m"])
        out[k] = out.get(k, 0) + 1
    return out


def placebo_p(rows, cands, real, key="profit", draws=None, seed=SEED):
    """Random cheap sides: each draw takes, for every (day, ask band x minute) cell, as many filled chances of the same
    group as the rule bet there, without replacement; statistic = mean profit per contract over the drawn bets;
    p = (k + 1) / (N + 1), k = draws at or above the rule's mean. The rule's own bets are in the pools."""
    draws = draws or PLACEBO_DRAWS
    need = placebo_cells(rows)
    pools = {}
    for c in cands:
        k = (c["day"], c["band"], c["m"])
        if k in need:
            pools.setdefault(k, []).append(c[key])
    for k, n in need.items():
        if len(pools.get(k, ())) < n:
            raise ValueError("placebo pool smaller than the rule's bets in cell %s" % (k,))
    keys = sorted(need, key=lambda k: (k[0].isoformat(), k[1], k[2]))
    total = sum(need.values())
    rnd = random.Random(seed)
    hit = 0
    for _ in range(draws):
        s = 0.0
        for k in keys:
            s += sum(rnd.sample(pools[k], need[k]))
        if s / total >= real - 1e-12:
            hit += 1
    return (1.0 + hit) / (1.0 + draws)


def pb_tail(rows, key="breakeven"):
    """P(wins >= the rule's wins) when each bet wins independently with its break-even chance (price + fee per
    contract): exact Poisson-binomial, keeping only counts below the observed wins (the rest is absorbed)."""
    w = int(round(sum(r["win"] for r in rows)))
    if w <= 0:
        return 1.0
    dist = [1.0] + [0.0] * (w - 1)   # P(count = i) for i < w
    for r in rows:
        q = min(1.0, max(0.0, r[key]))
        new = [0.0] * w
        for i, v in enumerate(dist):
            if v:
                new[i] += v * (1 - q)
                if i + 1 < w:
                    new[i + 1] += v * q
        dist = new
    return max(0.0, min(1.0, 1.0 - sum(dist)))


def holm(tests):
    """tests: [dict(name, p or None)] for the four groups. Step-down at 0.625%, 0.833%, 1.25%, 2.5%; a not-testable group
    sorts last and stops the step-down."""
    order = sorted(tests, key=lambda x: (x["p"] if x["p"] is not None else 2.0, x["name"]))
    going = True
    for rank, x in enumerate(order):
        lvl = HOLM_LEVELS[rank] if rank < len(HOLM_LEVELS) else FAMILY
        x["holm_rank"], x["holm_level"] = rank + 1, lvl
        if x["p"] is None:
            x["passed"] = False
            going = False
            continue
        ok = going and x["p"] <= lvl
        x["passed"] = bool(ok)
        going = going and ok
    return order


def describe(rows):
    n = len(rows)
    if not n:
        return dict(bets=0, days=0, wins=0)
    out = dict(bets=n, days=len({r["day"] for r in rows}), wins=int(sum(r["win"] for r in rows)),
               win_rate=sum(r["win"] for r in rows) / float(n), mean_price=sum(r["price"] for r in rows) / float(n),
               breakeven=sum(r["breakeven"] for r in rows) / float(n))
    for key in ("profit", "profit_cc"):
        m, se, D = clustered(rows, key)
        out["mean_" + key], out["se_" + key] = m, se
    return out


# ---------- stage A: the map (section 3) ----------
def map_rows(data, groups):
    rows = []
    for day, s, g, close, ms in windows_of(data, groups):
        for m, mk, side, f in chances(ms, dict(series=s, group=g)):
            y = y_of(mk)
            if y is None:
                continue
            rows.append(dict(day=day, series=s, group=g, m=m, ask=f["ask"], win=wins(side, y), band=ask_band(f["ask"]),
                             left=left_band(m), move=move3(f["d3"]), hour="%02d-%02d" % (4 * f["hour_band"],
                                                                                         4 * f["hour_band"] + 4)))
    return rows


def map_cell(rows):
    n = len(rows)
    if not n:
        return dict(n=0)
    for r in rows:
        r["excess"] = r["win"] - r["ask"]
    wr, wse, D = clustered(rows, "win")
    ex, ese, _ = clustered(rows, "excess")
    q = tq(D - 1) if D >= 2 else None
    ci = (lambda m, se: [m - q * se, m + q * se] if (q is not None and se is not None) else None)
    return dict(n=n, days=D, wins=int(sum(r["win"] for r in rows)), win_rate=wr, mean_ask=sum(r["ask"] for r in rows) / n,
                win_rate_ci95=ci(wr, wse), excess=ex, excess_ci95=ci(ex, ese))


def build_map(rows):
    out = dict(overall=map_cell(rows))
    for key in ("group", "series", "band", "left", "move", "hour"):
        cells = {}
        for r in rows:
            cells.setdefault(r[key], []).append(r)
        out[key] = {k: map_cell(v) for k, v in sorted(cells.items())}
    return out


def map_md(res):
    names = dict(group="Asset group", series="Series", band="Ask band", left="Minutes left", move="Last-3-minute move",
                 hour="Hour band (La Paz)")
    out = ["# PLAN20 stage A: the map (June-July 2026, descriptive)", "",
           "Plan: %s (SHA-256 %s). Markets closing %s to %s La Paz. Written %s." % (
               res["plan"], res["plan_sha256"][:16], res["period"][0], res["period"][1], res["written"]), "",
           "Every chance (market, minute 1-13, side) whose ask was 1-10c. Win rate against the average ask; 95% "
           "intervals clustered by day (Student-t, days - 1). **Descriptive only: the features, groups, rule and "
           "threshold are fixed by the plan; nothing here changes them.**", ""]

    def line(name, c):
        if not c.get("n"):
            return "| %s | 0 | | | | | | |" % name
        f = lambda v: "-" if v is None else "[%.4f, %.4f]" % tuple(v)   # noqa: E731
        return "| %s | %d | %d | %d | %.4f | %.4f | %s | %+.4f %s |" % (
            name, c["n"], c["days"], c["wins"], c["win_rate"], c["mean_ask"], f(c["win_rate_ci95"]), c["excess"],
            f(c["excess_ci95"]))
    head = ["| | Chances | Days | Wins | Win rate | Avg ask | Win rate 95% | Win - ask (95%) |", "|---|---|---|---|---|---|---|---|"]
    out += ["## Overall", ""] + head + [line("all", res["map"]["overall"])]
    for key in ("group", "series", "band", "left", "move", "hour"):
        out += ["", "## By %s" % names[key].lower(), ""] + head
        for k, c in res["map"][key].items():
            out.append(line(k, c))
    out += ["", "Cities-style caveat: markets in one window and one asset group move together, so chances are far from "
            "independent; the day clustering allows for that only partly. Not financial advice.", ""]
    return "\n".join(out)


def make_map(data=None, srec=None, root=ROOT, now=None):
    md_p, js_p, sha_p = map_paths()
    for f in (md_p, js_p, sha_p):
        if os.path.exists(f):
            return None, "the map exists (%s); it is written once" % f
    if data is None:
        bad = identity_problems(root)
        if bad:
            return None, "not frozen or changed (%s); no map" % ", ".join(bad)
    srec = srec or load_series()
    if srec is None:
        return None, "no series table"
    groups = {s["ticker"]: s["group"] for s in srec["series"]}
    if data is None:
        data, why = load_days(all_series(srec), FIT_PERIOD[0], FIT_PERIOD[1])
        if data is None:
            return None, why
    rows = map_rows(data, groups)
    res = dict(plan=PLAN, plan_sha256=PLAN_SHA256, written=now_iso(now),
               period=[FIT_PERIOD[0].isoformat(), FIT_PERIOD[1].isoformat()], chances=len(rows), map=build_map(rows))
    with open(md_p + ".tmp", "w", encoding="utf-8") as f:
        f.write(map_md(res))
    os.replace(md_p + ".tmp", md_p)
    jsonio.save(js_p, res)
    rec = dict(map_md=file_sha(md_p), map_json=file_sha(js_p), written=res["written"])
    jsonio.save(sha_p, rec)
    return res, "map written (%d chances); SHA-256 of plan20_map.md %s" % (len(rows), rec["map_md"])


def map_problems():
    md_p, js_p, sha_p = map_paths()
    rec, ok = P._read_json(sha_p)
    if not ok or not isinstance(rec, dict) or not rec.get("map_md"):
        return "no map record (run map first)"
    if file_sha(md_p) != rec["map_md"] or file_sha(js_p) != rec.get("map_json"):
        return "the map differs from its recorded SHA-256"
    return None


# ---------- stage B: the ridge logistic (section 4) ----------
def _np():
    try:
        import numpy
        return numpy
    except ImportError:
        return None


def _loss_py(X, Y, w, lam):
    n = len(Y)
    s = 0.0
    for x, y in zip(X, Y):
        z = w[0] + sum(a * b for a, b in zip(w[1:], x))
        s += (math.log1p(math.exp(-abs(z))) + max(z, 0.0)) - y * z   # -log-lik, stable
    return s / n + 0.5 * lam * sum(b * b for b in w[1:])


def _newton_py(X, Y, lam, steps=MAX_STEPS, tol=1e-10):
    n, k = len(Y), len(X[0]) + 1
    w = [0.0] * k
    cur = _loss_py(X, Y, w, lam)
    for it in range(steps):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for x, y in zip(X, Y):
            xx = [1.0] + list(x)
            p = P.P7.sigmoid(sum(a * b for a, b in zip(w, xx)))
            r, v = p - y, p * (1 - p)
            for i in range(k):
                g[i] += r * xx[i]
                vi = v * xx[i]
                Hi = H[i]
                for j in range(i, k):
                    Hi[j] += vi * xx[j]
        for i in range(k):
            g[i] /= n
            for j in range(i, k):
                H[i][j] /= n
                H[j][i] = H[i][j]
        for i in range(1, k):
            g[i] += lam * w[i]
            H[i][i] += lam
        step = P._solve(H, [-v for v in g])
        if step is None:
            return None
        t = 1.0
        while True:
            nw = [a + t * s for a, s in zip(w, step)]
            nl = _loss_py(X, Y, nw, lam)
            if nl <= cur + 1e-15 or t < 1e-6:
                break
            t /= 2
        w, cur = nw, nl
        if max(abs(t * s) for s in step) < tol:
            return w, it + 1
    return None


def _newton_np(np, X, Y, lam, steps=MAX_STEPS, tol=1e-10):
    X = np.hstack([np.ones((X.shape[0], 1)), X])
    n, k = X.shape
    pen = np.full(k, lam)
    pen[0] = 0.0
    w = np.zeros(k)

    def loss(w):
        z = X @ w
        return float(np.mean(np.logaddexp(0.0, z) - Y * z) + 0.5 * lam * np.sum(w[1:] ** 2))
    cur = loss(w)
    for it in range(steps):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-z))
        g = X.T @ (p - Y) / n + pen * w
        H = (X.T * (p * (1 - p))) @ X / n + np.diag(pen)
        try:
            step = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError:
            return None
        t = 1.0
        while True:
            nw = w + t * step
            nl = loss(nw)
            if nl <= cur + 1e-15 or t < 1e-6:
                break
            t /= 2
        w, cur = nw, nl
        if float(np.max(np.abs(t * step))) < tol:
            return [float(v) for v in w], it + 1
    return None


def standardise(X, k):
    """Means and sample SDs (n - 1) of the first k (continuous) columns; a column with no spread (SD at most 1e-9, which
    is rounding noise for prices in cents) keeps SD 1."""
    n = len(X)
    mu, sd = [], []
    for j in range(k):
        m = math.fsum(r[j] for r in X) / n
        v = math.fsum((r[j] - m) ** 2 for r in X) / (n - 1) if n > 1 else 0.0
        mu.append(m)
        sd.append(math.sqrt(v) if math.sqrt(max(v, 0.0)) > SD_MIN else 1.0)
    return mu, sd


def ridge_fit(X, Y, lam, backend="python"):
    """(intercept, slopes, means, sds, steps) or None: minimise mean log-loss + lam/2 x sum of squared slopes (the
    intercept is not penalised), Newton's method with step halving, on the continuous columns (the first len(CONT))
    standardised here. backend "python": X a list of rows; "numpy": X a 2-D array (same algorithm, vectorised)."""
    k = len(CONT)
    if backend == "numpy":
        np = _np()
        X = np.asarray(X, dtype=float)
        Yv = np.asarray(Y, dtype=float)
        mu = X[:, :k].mean(axis=0)
        sd = X[:, :k].std(axis=0, ddof=1) if X.shape[0] > 1 else np.zeros(k)
        sd = np.where(sd > SD_MIN, sd, 1.0)
        Z = X.copy()
        Z[:, :k] = (Z[:, :k] - mu) / sd
        got = _newton_np(np, Z, Yv, lam)
        mu, sd = [float(v) for v in mu], [float(v) for v in sd]
    else:
        mu, sd = standardise(X, k)
        Z = [[(v - m) / s for v, m, s in zip(r[:k], mu, sd)] + list(r[k:]) for r in X]
        got = _newton_py(Z, Y, lam)
    if got is None:
        return None
    w, steps = got
    return w[0], w[1:], mu, sd, steps


def log_loss(model, X, Y, backend="python"):
    """Mean log-loss of the model's chances (clipped to 1e-15) on rows X with outcomes Y."""
    if backend == "numpy":
        np = _np()
        X = np.asarray(X, dtype=float)
        k = len(model["mean"])
        Z = X.copy()
        Z[:, :k] = (Z[:, :k] - np.asarray(model["mean"])) / np.asarray(model["sd"])
        z = model["intercept"] + Z @ np.asarray(model["coef"])
        p = np.clip(1.0 / (1.0 + np.exp(-z)), 1e-15, 1 - 1e-15)
        Yv = np.asarray(Y, dtype=float)
        return float(-np.mean(Yv * np.log(p) + (1 - Yv) * np.log(1 - p)))
    s = 0.0
    for x, y in zip(X, Y):
        p = min(1 - 1e-15, max(1e-15, prob(model, x)))
        s -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return s / len(Y)


def fold_of(days):
    """Day -> fold: the fit's days in date order, dealt round-robin into 5 folds (every chance of a day in one fold)."""
    return {d: i % FOLDS for i, d in enumerate(sorted(set(days)))}


def _take(X, idx, backend):
    if backend == "numpy":
        return X[_np().asarray(idx, dtype=int)]
    return [X[i] for i in idx]


def cross_validate(X, Y, D, backend="python", log=None):
    """For each of the 13 strengths: fit on four folds, mean log-loss on the fifth, averaged over the five folds.
    Returns (best entry, table); the lowest mean wins, a tie goes to the larger strength."""
    folds = fold_of(D)
    split = []
    for f in range(FOLDS):
        tr = [i for i, d in enumerate(D) if folds[d] != f]
        te = [i for i, d in enumerate(D) if folds[d] == f]
        split.append((tr, te))
    table = []
    for lam in STRENGTHS:
        losses = []
        for tr, te in split:
            got = ridge_fit(_take(X, tr, backend), [Y[i] for i in tr], lam, backend) if tr and te else None
            if got is None:
                losses.append(None)
                continue
            mdl = dict(intercept=got[0], coef=got[1], mean=got[2], sd=got[3])
            losses.append(log_loss(mdl, _take(X, te, backend), [Y[i] for i in te], backend))
        ok = [v for v in losses if v is not None]
        table.append(dict(strength=lam, fold_losses=losses, mean=(sum(ok) / len(ok)) if len(ok) == FOLDS else None))
        if log:
            log("PLAN20 fit: strength %.4g mean log-loss %s" % (lam, table[-1]["mean"]))
    best = None
    for e in table:   # ascending strengths; a tie goes to the larger strength
        if e["mean"] is not None and (best is None or e["mean"] <= best["mean"] + 1e-15):
            best = e
    return best, table


FEAT_KEYS = CONT + ("hhhl", "hour_band", "weekday", "series", "group")


def fit_rows(data, groups):
    """[(day, compact features, win)] for every June-July chance with a yes/no result (all groups, BTC/ETH included)."""
    rows = []
    for day, s, g, close, ms in windows_of(data, groups):
        for m, mk, side, f in chances(ms, dict(series=s, group=g)):
            y = y_of(mk)
            if y is not None:
                rows.append((day, tuple(f[k] for k in FEAT_KEYS), wins(side, y)))
    return rows


def design_matrix(rows, series_list, backend):
    width = len(input_names(series_list))
    if backend == "numpy":
        np = _np()
        X = np.empty((len(rows), width))
        for i, r in enumerate(rows):
            X[i, :] = design_row(dict(zip(FEAT_KEYS, r[1])), series_list)
        return X
    return [design_row(dict(zip(FEAT_KEYS, r[1])), series_list) for r in rows]


def fit(data=None, srec=None, root=ROOT, backend=None, now=None, log=print):
    path = model_path()
    if os.path.exists(path):
        return None, "already fitted (%s); fitted once" % path
    if os.path.exists(model_hash_path()):
        return None, "a model hash record exists without a model (%s); no fit" % model_hash_path()
    if data is None:
        bad = identity_problems(root)
        if bad:
            return None, "not frozen or changed (%s); no fit" % ", ".join(bad)
    mp = map_problems()
    if mp:
        return None, "%s; the fit waits for the map" % mp
    srec = srec or load_series()
    if srec is None:
        return None, "no series table"
    groups = {s["ticker"]: s["group"] for s in srec["series"]}
    if data is None:
        data, why = load_days(all_series(srec), FIT_PERIOD[0], FIT_PERIOD[1])   # June-July only
        if data is None:
            return None, why
    rows = fit_rows(data, groups)
    data = None
    if len(rows) < 50 or len({r[0] for r in rows}) < FOLDS:
        return None, "too few June-July chances (%d) or days for the fit" % len(rows)
    series_list = sorted({r[1][FEAT_KEYS.index("series")] for r in rows})
    used = backend or ("numpy" if _np() is not None else "python")
    if used == "numpy" and _np() is None:
        return None, "numpy is not installed"
    X = design_matrix(rows, series_list, used)
    Y = [r[2] for r in rows]
    D = [r[0] for r in rows]
    rows = None
    best, table = cross_validate(X, Y, D, used, log)
    if best is None:
        return None, "cross-validation failed for every strength; nothing saved"
    got = ridge_fit(X, Y, best["strength"], used)
    if got is None:
        return None, "the final fit did not converge; nothing saved"
    b0, b, mu, sd, steps = got
    mrec, _ = P._read_json(map_paths()[2])
    np = _np() if used == "numpy" else None
    model = dict(plan=PLAN, plan_sha256=PLAN_SHA256, inputs=input_names(series_list), continuous=list(CONT),
                 series=series_list, groups=list(GROUPS), mean=mu, sd=sd, intercept=b0, coef=b,
                 strength=best["strength"], cv=table, folds="days in date order dealt round-robin into 5 folds",
                 objective="mean log-loss + strength/2 x sum(slopes^2); intercept not penalised; continuous inputs "
                           "standardised on the fit data (SD n-1); Newton's method with step halving",
                 steps=steps, rows=len(Y), days=len(set(D)), wins=int(sum(Y)), backend=used,
                 numpy=getattr(np, "__version__", None) if np is not None else None,
                 period=[FIT_PERIOD[0].isoformat(), FIT_PERIOD[1].isoformat()], map_sha256=(mrec or {}).get("map_md"),
                 series_table_sha256=file_sha(series_path()),
                 rule="bet when p >= ask + fee per contract + 0.01; fee = round up to the cent of 0.07 x C x P x (1-P), "
                      "C = floor(1.00 / P)", fitted=now_iso(now))
    model["frozen"] = model["fitted"]   # the model is frozen when it is written (read by research/live20.py)
    jsonio.save(path, model)
    err = record_model_hash(path, now=now)
    return model, "fitted on %d June-July chances (%d days, strength %.4g, %s); saved %s; model SHA-256 %s%s" % (
        len(Y), model["days"], best["strength"], used, path, file_sha(path), ("; " + err) if err else "")


def load_model():
    m, ok = P._read_json(model_path())
    return m if ok and isinstance(m, dict) and m.get("coef") is not None else None


def record_model_hash(model_file=None, hash_file=None, now=None):
    """Write the model file's SHA-256 once, at fit time, to its own file (research/results/plan20_model_sha256.json).
    Returns None, or why it was not written."""
    model_file, hash_file = model_file or model_path(), hash_file or model_hash_path()
    if os.path.exists(hash_file):
        return "the model hash record exists (%s); it is written once" % hash_file
    sha = file_sha(model_file)
    if sha is None:
        return "the model file could not be read"
    jsonio.save(hash_file, dict(model="research/results/plan20_model.json", sha256=sha, recorded=now_iso(now)))
    return None


def model_hash_problem(model_file=None, hash_file=None):
    """None when the model file's SHA-256 equals the one recorded at fit time; else the reason (fails closed: no record,
    a damaged record or an unreadable model is a problem)."""
    model_file, hash_file = model_file or model_path(), hash_file or model_hash_path()
    rec, ok = P._read_json(hash_file)
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("sha256"), str):
        return "no readable model hash record (%s)" % os.path.basename(hash_file)
    sha = file_sha(model_file)
    if sha is None:
        return "the model file could not be read"
    if sha != rec["sha256"]:
        return "the model file differs from the SHA-256 recorded at fit time"
    return None


# ---------- score (section 4) ----------
def collect(data, groups, model):
    """The rule's bets (one per window per series), the filled chances (placebo pools), calibration rows and counts."""
    bets, cands, calib = [], [], []
    cnt = dict(windows=0, windows_with_bet=0, chances=0, passed=0, passed_unfilled={}, by_group_windows={})
    for day, s, g, close, ms in windows_of(data, groups):
        cnt["windows"] += 1
        cnt["by_group_windows"][g] = cnt["by_group_windows"].get(g, 0) + 1
        got = None
        for m, mk, side, f in chances(ms, dict(series=s, group=g)):
            y = y_of(mk)
            if y is None:
                continue
            cnt["chances"] += 1
            d = decide(model, f)
            win = wins(side, y)
            calib.append(dict(group=g, p=d["p"], win=win, ask=f["ask"]))
            price, why = fill(mk.get("c") or {}, m, side)
            if price is not None:
                cands.append(bet_row(day, s, g, m, side, f["ask"], price, win, d["p"], mk["ticker"]))
            if got is not None or not d["bet"]:
                continue
            cnt["passed"] += 1
            if price is None:
                cnt["passed_unfilled"][why] = cnt["passed_unfilled"].get(why, 0) + 1
                continue
            got = bet_row(day, s, g, m, side, f["ask"], price, win, d["p"], mk["ticker"])
        if got is not None:
            bets.append(got)
            cnt["windows_with_bet"] += 1
    return bets, cands, calib, cnt


def group_test(name, bets, cands, period):
    st = describe(bets)
    out = dict(name=name, stats=st, p=None)
    if st["bets"] < MIN_BETS or st["days"] < MIN_DAYS:
        out["not_testable"] = "fewer than %d bets or fewer than %d days with a bet" % (MIN_BETS, MIN_DAYS)
        return out
    tr = t_reading(bets)
    if tr["t"] is None:
        out["not_testable"] = "no day-clustered standard error"
        return out
    pb = boot_p(bets, period)
    pp = placebo_p(bets, cands, tr["mean"])
    pt = pb_tail(bets)
    out["checks"] = dict(t=tr["t"], df=tr["df"], p_t=tr["p_t"], p_boot=pb, p_placebo=pp, p_poisson_binomial=pt)
    out["p"] = max(tr["p_t"], pb if pb is not None else 1.0, pp, pt)
    return out


def score(data=None, srec=None, model=None, root=ROOT, now=None):
    md_p, js_p = result_paths()
    for f in (md_p, js_p):
        if os.path.exists(f):
            return None, "already scored (%s exists); scored once" % f
    if data is None:
        bad = identity_problems(root)
        if bad:
            return None, "not frozen or changed (%s); no score" % ", ".join(bad)
    if model is None:   # the stored model must be the one written at fit time
        mh = model_hash_problem()
        if mh:
            return None, "%s; no score" % mh
    model = model or load_model()
    if model is None:
        return None, "no model yet (run fit first)"
    if model.get("plan_sha256") != PLAN_SHA256:
        return None, "the model was not fitted under this plan; no score"
    srec = srec or load_series()
    if srec is None:
        return None, "no series table"
    groups = {s["ticker"]: s["group"] for s in srec["series"]}
    period = P.days_of(SCORE_PERIOD[0], SCORE_PERIOD[1])
    if data is None:
        data, why = load_days(all_series(srec), SCORE_PERIOD[0], SCORE_PERIOD[1])
        if data is None:
            return None, why
    bets, cands, calib, cnt = collect(data, groups, model)
    res = dict(plan=PLAN, plan_sha256=PLAN_SHA256, scored=now_iso(now), period=[period[0].isoformat(), period[-1].isoformat()],
               model_sha256=P._sha(json.dumps(model, sort_keys=True)), counts=cnt,
               settings=dict(cheap=list(CHEAP), margin=MARGIN, fee_rate=FEE_RATE, bet=BET, holm_levels=list(HOLM_LEVELS),
                             boot_block_days=BOOT_BLOCK_DAYS, boot_draws=BOOT_DRAWS, placebo_draws=PLACEBO_DRAWS,
                             seed=SEED, min_bets=MIN_BETS, min_days=MIN_DAYS, day="La Paz date of the close"))
    tests = []
    for g in TESTED:
        tests.append(group_test(g, [b for b in bets if b["group"] == g], [c for c in cands if c["group"] == g], period))
    holm(tests)
    for x in tests:
        x["verdict"] = (NOT_TESTABLE + " (%s)" % x["not_testable"]) if x.get("not_testable") else \
            (VERDICT_PASS if x["passed"] else VERDICT_FAIL)
    res["tests"] = [tests[i] for i in sorted(range(len(tests)), key=lambda i: TESTED.index(tests[i]["name"]))]
    res["descriptive"] = {g: describe([b for b in bets if b["group"] == g]) for g in ("btceth", "other")}
    tested = [b for b in bets if b["group"] in TESTED]
    res["exploratory"] = dict(
        by_ask_band={k: describe([b for b in tested if b["band"] == k]) for k, _, _ in ASK_BANDS},
        by_minutes_left={k: describe([b for b in tested if b["left"] == k]) for k, _, _ in LEFT_BANDS},
        wins_per_group={g: int(sum(b["win"] for b in bets if b["group"] == g)) for g in GROUPS},
        centicent={g: describe([b for b in bets if b["group"] == g]) for g in TESTED},
        calibration_deciles=deciles([c for c in calib if c["group"] in TESTED]),
        calibration_deciles_btceth=deciles([c for c in calib if c["group"] == "btceth"]))
    passed = [x["name"] for x in res["tests"] if x.get("passed")]
    res["verdict"] = (VERDICT_PASS + " (%s)" % ", ".join(passed)) if passed else VERDICT_FAIL
    json.dumps(res, default=str)
    res = json.loads(json.dumps(res, default=str))
    with open(md_p + ".tmp", "w", encoding="utf-8") as f:
        f.write(result_md(res))
    os.replace(md_p + ".tmp", md_p)
    jsonio.save(js_p, res)
    return res, res["verdict"]


def deciles(rows):
    rs = sorted(rows, key=lambda c: c["p"])
    out = []
    for i in range(10):
        part = rs[i * len(rs) // 10:(i + 1) * len(rs) // 10]
        if part:
            out.append(dict(n=len(part), predicted=sum(c["p"] for c in part) / len(part),
                            actual=sum(c["win"] for c in part) / len(part), mean_ask=sum(c["ask"] for c in part) / len(part)))
    return out


def _f(v, fmt="%+.4f"):
    return "-" if v is None else fmt % v


def _row(name, st):
    return "| %s | %d | %d | %d | %s | %s | %s | %s (%s) | %s (%s) |" % (
        name, st.get("bets", 0), st.get("days", 0), st.get("wins", 0), _f(st.get("win_rate"), "%.4f"),
        _f(st.get("mean_price"), "%.4f"), _f(st.get("breakeven"), "%.4f"), _f(st.get("mean_profit")),
        _f(st.get("se_profit"), "%.4f"), _f(st.get("mean_profit_cc")), _f(st.get("se_profit_cc"), "%.4f"))


def result_md(res):
    out = ["# PLAN20 result (scored once)", "",
           "Plan: %s (SHA-256 %s). Markets closing %s to %s La Paz. Scored %s." % (
               res["plan"], res["plan_sha256"][:16], res["period"][0], res["period"][1], res["scored"]),
           "", "**Verdict: %s**" % res["verdict"], "",
           "Statistic: mean profit per contract after the whole-cent fee on a $1 bet, one bet per window per series. "
           "A group passes at its Holm level only if the day-clustered t reading, the 2-day block bootstrap, the "
           "matched placebo and the Poisson-binomial bound all clear it. BTC/ETH are left out of every test.", "",
           "| Group | Bets | Days | t | p (t) | p (bootstrap) | p (placebo) | p (Poisson-binomial) | Holm level | Verdict |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for x in res["tests"]:
        c = x.get("checks") or {}
        out.append("| %s | %d | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            x["name"], x["stats"].get("bets", 0), x["stats"].get("days", 0), _f(c.get("t"), "%.2f"),
            _f(c.get("p_t"), "%.4f"), _f(c.get("p_boot"), "%.4f"), _f(c.get("p_placebo"), "%.4f"),
            _f(c.get("p_poisson_binomial"), "%.5f"), _f(x.get("holm_level"), "%.5f"), x["verdict"]))
    head = ["| | Bets | Days | Wins | Win rate | Avg price | Break-even | Profit/contract (SE) | Centicent fee (SE) |",
            "|---|---|---|---|---|---|---|---|---|"]
    out += ["", "## Bets by group (BTC/ETH and other: descriptive only)", ""] + head
    for x in res["tests"]:
        out.append(_row(x["name"], x["stats"]))
    for g, st in res["descriptive"].items():
        out.append(_row(g + " (descriptive)", st))
    e = res["exploratory"]
    out += ["", "## Exploratory (tested groups together)", "", "### By ask band", ""] + head
    out += [_row(k, v) for k, v in e["by_ask_band"].items()]
    out += ["", "### By minutes left", ""] + head
    out += [_row(k, v) for k, v in e["by_minutes_left"].items()]
    out += ["", "### Calibration of p (deciles, every chance of the tested groups)", "",
            "| n | Predicted | Actual | Avg ask |", "|---|---|---|---|"]
    out += ["| %d | %.4f | %.4f | %.4f |" % (d["n"], d["predicted"], d["actual"], d["mean_ask"]) for d in e["calibration_deciles"]]
    c = res["counts"]
    out += ["", "## Data", "",
            "- %d windows (%s), %d with a bet; %d chances; the rule passed %d times; passes that could not fill (the "
            "window went on): %s." % (c["windows"], c["by_group_windows"], c["windows_with_bet"], c["chances"],
                                       c["passed"], c["passed_unfilled"] or "none"),
            "- Wins per group: %s." % e["wins_per_group"],
            "- Paper fills are an upper bound: candles show no depth, and a $1 bet at 2-3c is 33-50 contracts.",
            "", "A pass is a lead on past data, not a working system: it earns only the stage C forward paper test "
            "(42 days). Real money would need a new live.py path that only the user can approve. Not financial advice.", ""]
    return "\n".join(out)


# ---------- status ----------
def status():
    srec = load_series()
    if srec is None:
        return "PLAN20: no series table yet"
    fit_days = P.days_of(FIT_PERIOD[0], FIT_PERIOD[1])
    sc_days = P.days_of(SCORE_PERIOD[0], SCORE_PERIOD[1])
    ser = all_series(srec)
    nf = sum(1 for s in ser for d in fit_days if os.path.exists(day_path(s, d)))
    ns = sum(1 for s in ser for d in sc_days if os.path.exists(day_path(s, d)))
    return "PLAN20: %d series %s; frozen %s; series-days saved: June-July %d of %d, August-October %d of %d; map %s; " \
           "fitted %s; scored %s" % (
               len(ser), {g: len(v) for g, v in srec["groups"].items()}, os.path.exists(identity_path()), nf,
               len(ser) * len(fit_days), ns, len(ser) * len(sc_days), os.path.exists(map_paths()[2]),
               os.path.exists(model_path()), os.path.exists(result_paths()[1]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["series", "freeze", "download", "map", "fit", "score", "status"])
    ap.add_argument("--max-days", type=int)
    ap.add_argument("--budget-minutes", type=float)
    a = ap.parse_args(argv)
    if a.stage == "series":
        rec, msg = make_series()
    elif a.stage == "freeze":
        rec, msg = freeze()
    elif a.stage == "download":
        rec, msg = download(a.max_days, a.budget_minutes)
    elif a.stage == "map":
        rec, msg = make_map()
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
