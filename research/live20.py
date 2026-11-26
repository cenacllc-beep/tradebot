"""PLAN20 forward logger (research/PLAN20.md, sections 2 and 5): live snapshots of every 15-minute Kalshi market, their
results, and paper bets by PLAN20's frozen rule once its model exists. Research and paper only.

    python research/live20.py run --minutes N     one snapshot of every open market each minute (+5 s), for N minutes
    python research/live20.py settle [--budget-seconds S]   results of logged markets that have closed
    python research/live20.py paper [--budget-seconds S]   PLAN20's rule on Kalshi's one-minute candles of the logged
                                                  windows (only once the model exists)
    python research/live20.py status              counts only (minutes, markets, gaps); never a profit figure

What it never does: place, change or cancel an order (no order endpoint exists in this file), import live.py, or touch
paper.db, live.db or trial/. Kalshi's public API only, read-only GETs, through tbcommon's JsonClient (the project's only
User-Agent, retries, a minimum gap between requests).

Kill switch: `paper` checks the project's KILL file (core.kill_file) and writes nothing while it is on. The KILL file
lives on the PC only (it is never committed), so on GitHub's runner the switch is not seen and `paper` writes there
regardless. That is harmless: paper.jsonl is a research ledger of hypothetical bets, nothing here can place an order,
and the PC's kill switch still stops every step that trades.

Files (research/data/live20/, overridable with LIVE20_DATA for tests):
- snap-YYYYMMDD-HHMM.jsonl.gz: one row per open market per minute, one small file per 30-minute chunk (UTC; HHMM is
  the chunk's start, :00 or :30). Rows are appended to snap-YYYYMMDD-HHMM.jsonl while the chunk is written and the
  finished chunk is gzipped (merged with an earlier .gz of the same chunk, when two runs shared it). Readers also take
  the old one-file-a-day snap-YYYYMMDD.jsonl and snap-YYYYMMDD.jsonl.gz.
  Row: ts (read time), minute (the minute boundary the row stands for: the close of PLAN20's candle ending there),
  ticker, series, event, open, close (epoch seconds), status, yes_bid, yes_ask, no_bid, no_ask, last (dollars),
  volume, oi (contracts; volume is Kalshi's running total for the market). NO is derived as PLAN20 section 2 says:
  no_ask = 1 - yes_bid, no_bid = 1 - yes_ask.
- log.jsonl: run_start / run_end rows, a "gap" row for every minute not read (late or every request failed) and an
  "error" row for every series that failed in a minute.
- Every JSONL append starts a new line first when the file's last byte is not a newline (a line torn by a crash is
  then one unreadable line, skipped by the readers, and never swallows the next row).
- results.json: {ticker: {result, yes_pay, no_pay, status, close, settled_ts}} by strategy.payout's rules.
- candles/SERIES/YYYY-MM-DD.json.gz: Kalshi's one-minute candlesticks of the logged markets, one bundle per series and
  La Paz day of the close ({"markets": {ticker: {open, close, period_interval, fetched, candlesticks}}}), each market
  fetched once after its close. The old one-file-a-market candles/SERIES/TICKER.json is still read.
- paper.jsonl: the paper bets (rebuilt in full by each `paper` run, so it is idempotent). Each row carries stage_c:
  True only when research/results/plan20_result.json (under this plan's text) shows the row's group passed and the
  row's window opened on or after the first full La Paz day after the result's timestamp (PLAN20 section 5); every
  other row is descriptive only.

The paper rule (PLAN20 sections 2 and 5) is research/plan20.py's own code, imported lazily (fail closed without it,
with plan20's identity check not clean, without the model file, with a model whose SHA-256 differs from the one
recorded at fit time, or with a model fitted under another plan text): for every logged window (one series, one
close time; start = close - 15 minutes) that opened at or after the model's freeze time, has closed and whose logged
markets all have a result, Kalshi's one-minute candles of each market are fetched once (the endpoint, interval and
span plan20.py downloads), parsed by plan20.parse_candles, and replayed exactly as plan20's score stage does
(chances(), decide(), fill() at candle m+1, one bet per window per series, bet_row()'s $1 bet and whole-cent fee).
The minute snapshots are a raw record only (they have no per-minute highs and lows). Markets with a scalar or void
result are left out of the replay, as plan20's download leaves them out. Python 3.8+.
"""
import argparse
import glob
import gzip
import hashlib
import importlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC   # noqa: E402
from tbcommon.parse import num, px, rts   # noqa: E402
from tbcommon import jsonio   # noqa: E402

DATA = os.environ.get("LIVE20_DATA") or os.path.join(HERE, "data", "live20")
SERIES_FILE = os.environ.get("LIVE20_SERIES") or os.path.join(HERE, "results", "plan20_series.json")
MODEL_FILE = os.environ.get("LIVE20_MODEL") or os.path.join(HERE, "results", "plan20_model.json")
MODEL_SHA_FILE = os.environ.get("LIVE20_MODEL_SHA") or os.path.join(HERE, "results", "plan20_model_sha256.json")
RESULT_FILE = os.environ.get("LIVE20_RESULT") or os.path.join(HERE, "results", "plan20_result.json")
LAPAZ = timezone(timedelta(hours=-4), "La Paz")   # UTC-4 all year (tbcommon.clock.BOT_TZ), as in plan20.py
CHUNK = 30 * 60       # snapshot files: one per 30-minute UTC chunk

OFFSET = 5            # seconds after each minute boundary that the snapshot is read
LATE = 25             # a minute whose read cannot start within OFFSET + LATE seconds of its boundary is a gap
SETTLE_AFTER = 120    # a market is asked for its result this long after it closes
PAGE = 1000

CLIENT = JsonClient(KALSHI_PUBLIC, tries=3, timeout=10, min_gap=0.06, backoff_base=1.0, backoff_cap=8.0)


def http(path, params=None):
    """GET on Kalshi's public API (tests replace this function)."""
    return CLIENT.get(path, params)


def now():
    return time.time()


def sleep(s):
    time.sleep(s)


def sleep_until(t):
    while True:
        d = t - now()
        if d <= 0:
            return
        sleep(min(d, 5.0))


def _p(name):
    return os.path.join(DATA, name)


def append_rows(path, rows):
    """Append JSONL rows, one compact object per line. When the file's last byte is not a newline (a line torn by a
    crash), a newline is written first so the torn line stays alone and the new rows stay readable. (A local helper:
    tbcommon.jsonio.append keeps its behaviour for its other callers.)"""
    if not rows:
        return
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "ab+") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.seek(0, os.SEEK_END)
                f.write(b"\n")
        f.seek(0, os.SEEK_END)
        f.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode("utf-8"))


def log_row(kind, **f):
    row = dict(kind=kind, ts=round(now(), 1))
    row.update(f)
    append_rows(_p("log.jsonl"), [row])


def day_of(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d")


def chunk_of(t):
    """'YYYYMMDD-HHMM' of the 30-minute UTC chunk holding minute t (HHMM = the chunk's start)."""
    return datetime.fromtimestamp(int(t // CHUNK) * CHUNK, timezone.utc).strftime("%Y%m%d-%H%M")


def _epoch(s):
    """ISO time or date -> epoch seconds (a time without an offset is read as UTC), or None."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    x = str(s).strip().replace("Z", "+00:00")
    if re.match(r"^\d{4}-\d\d-\d\d$", x):
        x += "T00:00:00+00:00"
    if not re.search(r"[+-]\d\d:\d\d$", x):   # no offset: UTC (rts alone would read local time)
        x += "+00:00"
    return rts(x)


# ---------- series ----------
def series_from_file(path=None):
    """(tickers, {ticker: group}) from research/results/plan20_series.json, or (None, {}) when there is no file.
    Shapes read: a list of tickers or of {ticker, group} objects, {"series": that list}, or {ticker: group}."""
    path = path or SERIES_FILE
    if not os.path.exists(path):
        return None, {}
    try:
        j = jsonio.load(path)
    except (OSError, ValueError):
        return [], {}
    if isinstance(j, dict) and "series" in j:
        j = j["series"]
    out, groups = [], {}
    if isinstance(j, dict):
        for k, v in j.items():
            g = v.get("group") if isinstance(v, dict) else v
            out.append(str(k)); groups[str(k)] = g if isinstance(g, str) else None
    elif isinstance(j, list):
        for x in j:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and x.get("ticker"):
                out.append(str(x["ticker"])); groups[str(x["ticker"])] = x.get("group")
    return sorted(set(out)), groups


def series_from_api():
    """Every series whose ticker ends in 15M, from /series (paginated when Kalshi sends a cursor)."""
    out, cur, seen = set(), None, set()
    while True:
        j = http("/series", dict(cursor=cur) if cur else None) or {}
        for s in j.get("series") or []:
            t = str(s.get("ticker") or "")
            if t.upper().endswith("15M"):
                out.add(t)
        cur = j.get("cursor") or j.get("next_cursor")
        if not cur or cur in seen:
            return sorted(out)
        seen.add(cur)


def series_list():
    tickers, groups = series_from_file()
    if tickers:
        return tickers, groups, "file"
    if tickers is not None:
        log_row("error", where="series file", error="research/results/plan20_series.json unreadable or empty; "
                                                    "listing /series instead")
    return series_from_api(), {}, "api"


# ---------- snapshots ----------
def _flip(v):
    return None if v is None else round(1.0 - v, 4)


def _r(v):
    return None if v is None else round(v, 4)


def snap_row(m, series, minute, ts):
    """One snapshot row from Kalshi's market object, or None without a ticker."""
    t = m.get("ticker")
    if not t:
        return None
    yb, ya = _r(px(m, "yes_bid")), _r(px(m, "yes_ask"))
    vol = num(m.get("volume_fp"))
    oi = num(m.get("open_interest_fp"))
    o, c = _epoch(m.get("open_time")), _epoch(m.get("close_time"))
    return dict(ts=round(ts, 1), minute=int(minute), ticker=t, series=series, event=m.get("event_ticker"),
                open=None if o is None else int(o), close=None if c is None else int(c), status=m.get("status"),
                yes_bid=yb, yes_ask=ya, no_bid=_flip(ya), no_ask=_flip(yb), last=_r(px(m, "last_price")),
                volume=vol if vol is not None else num(m.get("volume")),
                oi=oi if oi is not None else num(m.get("open_interest")))


def read_series(series, minute):
    """Rows for every open market of one series (paginated)."""
    rows, cur, seen = [], None, set()
    while True:
        q = dict(series_ticker=series, status="open", limit=PAGE)
        if cur:
            q["cursor"] = cur
        j = http("/markets", q) or {}
        ts = now()
        for m in j.get("markets") or []:
            r = snap_row(m, series, minute, ts)
            if r:
                rows.append(r)
        cur = j.get("cursor")
        if not cur or cur in seen:
            return rows
        seen.add(cur)


def snapshot(series, minute):
    """(rows, failed series) for one minute; a failed series never stops the others."""
    rows, failed = [], []
    for s in series:
        try:
            rows.extend(read_series(s, minute))
        except Exception as ex:   # one series' failure is logged, the minute goes on
            failed.append(s)
            log_row("error", minute=int(minute), series=s, error=str(ex)[:200])
    return rows, failed


def run(minutes):
    """Read every open market of every series at each minute boundary + OFFSET until `minutes` have passed."""
    start = now()
    end = start + 60 * minutes
    try:
        series, groups, source = series_list()
    except Exception as ex:
        log_row("error", where="series list", error=str(ex)[:200])
        print("could not list the series (%s); nothing read" % ex)
        return 1
    log_row("run_start", minutes=minutes, series=series, source=source)
    if not series:
        print("no 15-minute series found; nothing read")
        log_row("run_end", minutes_read=0, rows=0, gaps=0)
        return 1
    target = (int(start // 60) + 1) * 60
    read = gaps = nrows = 0
    chunk = None
    while target + OFFSET <= end:
        if chunk is not None and chunk_of(target) != chunk:
            try:   # the previous 30-minute chunk is finished: gzip it
                compact(keep=chunk_of(target))
            except Exception as ex:
                log_row("error", where="compact", error=str(ex)[:200])
        chunk = chunk_of(target)
        sleep_until(target + OFFSET)
        late = now() - (target + OFFSET)
        if late > LATE:
            log_row("gap", minute=int(target), why="read could not start in time (%.0f s late)" % late)
            gaps += 1
            target += 60
            continue
        try:
            rows, failed = snapshot(series, target)
            append_rows(_p("snap-%s.jsonl" % chunk_of(target)), rows)
        except Exception as ex:   # e.g. a disk error: logged, the loop goes on
            rows, failed = [], list(series)
            log_row("error", minute=int(target), where="write", error=str(ex)[:200])
        if len(failed) == len(series):
            log_row("gap", minute=int(target), why="every request failed")
            gaps += 1
        else:
            read += 1
            nrows += len(rows)
        target += 60
    log_row("run_end", minutes_read=read, rows=nrows, gaps=gaps)
    try:
        compact()
    except Exception as ex:
        log_row("error", where="compact", error=str(ex)[:200])
    print("live20 run: %d minutes read, %d rows, %d gap minutes, %d series" % (read, nrows, gaps, len(series)))
    return 0


# ---------- reading the day files ----------
SNAP_NAME = re.compile(r"snap-(\d{8})(?:-(\d{4}))?\.jsonl(\.gz)?$")


def _day_files():
    """{YYYYMMDD: [paths]}: the old whole-day files first, then the 30-minute chunks in time order; within one name,
    gz before plain."""
    out = {}
    for f in glob.glob(_p("snap-*.jsonl*")):
        m = SNAP_NAME.match(os.path.basename(f))
        if m:
            out.setdefault(m.group(1), []).append((m.group(2) or "", 0 if m.group(3) else 1, f))
    return {k: [f for _, _, f in sorted(v)] for k, v in out.items()}


def _read_lines(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for ln in f:
            try:
                yield json.loads(ln)
            except ValueError:
                continue   # a half-written last line after a crash


def snapshots():
    """Every snapshot row, day by day in time order; a (minute, ticker) seen twice is read once."""
    files = _day_files()
    for d in sorted(files):
        seen = set()
        for f in files[d]:
            for r in _read_lines(f):
                if not isinstance(r, dict) or "minute" not in r or "ticker" not in r:
                    continue
                k = (r["minute"], r["ticker"])
                if k in seen:
                    continue
                seen.add(k)
                yield r


def _merge_gz(plain):
    """Gzip one plain snapshot file into plain + '.gz' (merged with that .gz when it exists; a (minute, ticker) once),
    then remove the plain file."""
    gz = plain + ".gz"
    seen, rows = set(), []
    for f in (gz, plain):
        if not os.path.exists(f):
            continue
        for r in _read_lines(f):
            if not isinstance(r, dict):
                continue
            k = (r.get("minute"), r.get("ticker"))
            if k not in seen:
                seen.add(k); rows.append(r)
    tmp = gz + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, gz)
    os.remove(plain)


def compact(today=None, keep=None):
    """Gzip every plain 30-minute chunk file except the chunk `keep` (the one being written); and, for the old format,
    every finished UTC day's plain file (days before today)."""
    today = today or day_of(now())
    for f in glob.glob(_p("snap-*.jsonl")):
        m = SNAP_NAME.match(os.path.basename(f))
        if not m or m.group(3):
            continue
        if m.group(2):
            if "%s-%s" % (m.group(1), m.group(2)) != keep:
                _merge_gz(f)
        elif m.group(1) < today:
            _merge_gz(f)


# ---------- settle ----------
def load_results():
    try:
        r = jsonio.load(_p("results.json"), {})
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def settle(budget_seconds=240):
    """Results of logged markets that closed at least SETTLE_AFTER seconds ago (strategy.payout's rules: yes/no at
    once, scalar and void once finalized). A market not settled yet, or not reachable, is asked again next time."""
    from strategy import payout   # the project's settlement rule (read-only use)
    res = load_results()
    closes = {}
    for r in snapshots():
        if r.get("close") is not None:
            closes[r["ticker"]] = r["close"]
    t0 = now()
    todo = sorted((c, t) for t, c in closes.items() if t not in res and c <= t0 - SETTLE_AFTER)
    done = failed = 0
    for i, (c, t) in enumerate(todo):
        if now() - t0 > budget_seconds:
            print("settle: time budget used; %d markets left for the next run" % (len(todo) - i))
            break
        try:
            m = (http("/markets/%s" % t) or {}).get("market") or {}
        except Exception as ex:
            failed += 1
            log_row("error", where="settle", ticker=t, error=str(ex)[:200])
            continue
        y, n = payout(m, "yes"), payout(m, "no")
        if y is None or n is None:
            continue
        res[t] = dict(result=y[0], yes_pay=y[1], no_pay=n[1], status=m.get("status"), close=c, settled_ts=round(now()))
        done += 1
        if done % 100 == 0:
            jsonio.save(_p("results.json"), res)
    jsonio.save(_p("results.json"), res)
    print("live20 settle: %d new results (%d total), %d unreachable" % (done, len(res), failed))
    return done


# ---------- paper ----------
# The paper bets are NOT computed from the minute snapshots above (those are a raw record only: they have no
# per-minute highs and lows, so the higher-highs flag and the window's high/low would differ from the fit data).
# Instead, for every logged market whose window has closed, Kalshi's own one-minute candlesticks are fetched once
# (GET /series/{series}/markets/{ticker}/candlesticks, period_interval=1, start_ts = window start, end_ts = close: the
# same endpoint, interval and span research/plan20.py downloads), cached under candles/, parsed by plan20.parse_candles
# and replayed by plan20's own chances(), decide(), fill(), bet_row(), y_of() and wins(), in the same order as its score
# stage (collect()). Live and history therefore share one code path.
# Fill (PLAN20 sections 2 and 5): section 5 words the forward fill as "the live ask about 60 seconds later"; candle
# m+1's closing ask is exactly that quote (candle m closes at the decision minute's end, candle m+1 closes 60 s later),
# so plan20.fill(candles, m, side) is the forward fill too.
CANDLE_AFTER = 120          # candles are fetched this long after a market closes (Kalshi's last candle is written)
EMPTY_FINAL = 6 * 3600      # an empty candle answer is cached as final only for a market closed this long ago
NEEDED = ("features", "decide", "chances", "fill", "bet_row", "parse_candles", "y_of", "wins", "lapaz_date", "T",
          "lapaz_start", "identity_problems", "model_hash_problem", "TESTED", "PLAN_SHA256")
FLUSH_EVERY = 200           # candle bundles are written at least this often (markets fetched) during a paper run


def candle_path(series, ticker):
    """The old one-file-a-market cache (read only)."""
    return os.path.join(DATA, "candles", series, "%s.json" % ticker)


def lapaz_day(ts):
    return datetime.fromtimestamp(ts, LAPAZ).strftime("%Y-%m-%d")


def bundle_path(series, close_ts):
    """candles/SERIES/YYYY-MM-DD.json.gz: one bundle per series and La Paz day of the close."""
    return os.path.join(DATA, "candles", series, "%s.json.gz" % lapaz_day(close_ts))


class CandleStore(object):
    """The candle cache: bundles read once, markets added in memory, written back by flush() (temp file, then
    os.replace, so a reader never sees half a bundle). A damaged bundle reads as empty (its markets are fetched
    again)."""

    def __init__(self):
        self.bundles, self.dirty, self.added = {}, set(), 0

    def _bundle(self, series, close_ts):
        p = bundle_path(series, close_ts)
        if p not in self.bundles:
            ms = {}
            if os.path.exists(p):
                try:
                    with gzip.open(p, "rt", encoding="utf-8") as f:
                        j = json.load(f)
                    if isinstance(j, dict) and isinstance(j.get("markets"), dict):
                        ms = j["markets"]
                except (OSError, ValueError, EOFError):
                    ms = {}
            self.bundles[p] = ms
        return p, self.bundles[p]

    def get(self, series, ticker, close_ts):
        _, ms = self._bundle(series, close_ts)
        e = ms.get(ticker)
        if isinstance(e, dict) and isinstance(e.get("candlesticks"), list):
            return e["candlesticks"]
        p = candle_path(series, ticker)
        if os.path.exists(p):
            try:
                j = jsonio.load(p)
                if isinstance(j, dict) and isinstance(j.get("candlesticks"), list):
                    return j["candlesticks"]
            except (OSError, ValueError):
                pass
        return None

    def add(self, series, ticker, open_ts, close_ts, t_now, cs):
        p, ms = self._bundle(series, close_ts)
        ms[ticker] = dict(open=int(open_ts), close=int(close_ts), period_interval=1, fetched=round(t_now),
                          candlesticks=cs)
        self.dirty.add(p)
        self.added += 1
        if self.added % FLUSH_EVERY == 0:
            self.flush()

    def flush(self):
        for p in sorted(self.dirty):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(dict(markets=self.bundles[p]), f, sort_keys=True, separators=(",", ":"))
            os.replace(tmp, p)
        self.dirty = set()


def fetch_candles(series, ticker, open_ts, close_ts):
    """Kalshi's one-minute candlesticks of one market (raw list), as plan20.fetch_candles asks for them; the archive
    endpoint is tried when the live one fails (a market past Kalshi's historical cutoff)."""
    q = dict(start_ts=int(open_ts), end_ts=int(close_ts), period_interval=1)
    try:
        j = http("/series/%s/markets/%s/candlesticks" % (series, ticker), q) or {}
    except Exception:
        j = http("/historical/markets/%s/candlesticks" % ticker, q) or {}
    return j.get("candlesticks") or []


def candles_of(series, ticker, open_ts, close_ts, t_now, store):
    """The market's raw candles from the cache (its series-day bundle, else the old per-market file), else fetched once
    and added to the bundle; None when not available yet."""
    cs = store.get(series, ticker, close_ts)
    if cs is not None:
        return cs
    cs = fetch_candles(series, ticker, open_ts, close_ts)
    if cs or t_now - close_ts >= EMPTY_FINAL:
        store.add(series, ticker, open_ts, close_ts, t_now, cs)
        return cs
    return None


def stage_c_starts(Q, path=None):
    """{group: epoch} for every group plan20's stored result (research/results/plan20_result.json, scored under this
    plan's text) shows passed: the start (La Paz midnight) of the first full La Paz day after the result's timestamp.
    {} when there is no readable result (fail closed: every row then stays descriptive)."""
    path = path or RESULT_FILE
    try:
        j = jsonio.load(path)
    except (OSError, ValueError):
        return {}
    if not isinstance(j, dict) or j.get("plan_sha256") != Q.PLAN_SHA256:
        return {}
    t = _epoch(j.get("scored"))
    if t is None:
        return {}
    start = Q.lapaz_start(Q.lapaz_date(t) + timedelta(days=1))
    out = {}
    for x in j.get("tests") or []:
        if isinstance(x, dict) and x.get("passed") is True and x.get("name") in Q.TESTED:
            out[x["name"]] = start
    return out


def window_bet(Q, model, day, series, group, markets):
    """The window's one bet, exactly as plan20.collect() makes it for one window: plan20.chances() (minutes in order,
    markets by ticker, YES before NO; a chance's ask 1-10c), decide(), fill() at candle m+1 (a skipped fill does not use
    up the side), first pass that fills wins. markets: plan20's market dicts {ticker, open, close, result, c} sorted
    by ticker. Returns plan20.bet_row(...) or None. tests/test_live20.py checks it against plan20.collect()."""
    for m, mk, side, f in Q.chances(markets, dict(series=series, group=group)):
        y = Q.y_of(mk)
        if y is None:
            continue
        d = Q.decide(model, f)
        if not d["bet"]:
            continue
        price, _why = Q.fill(mk.get("c") or {}, m, side)
        if price is None:
            continue
        return Q.bet_row(day, series, group, m, side, f["ask"], price, Q.wins(side, y), d["p"], mk["ticker"])
    return None


def logged_markets():
    """{ticker: (series, close)} of every market in the snapshots (the window start is close - 15 minutes, as in
    plan20.market_list)."""
    out = {}
    for r in snapshots():
        if r.get("close") is not None and r.get("series"):
            out[r["ticker"]] = (r["series"], int(r["close"]))
    return out


def paper(budget_seconds=600):
    """Rebuild paper.jsonl: PLAN20's frozen rule replayed on Kalshi's one-minute candles of every logged window that
    opened at or after the model's freeze time, has closed, and whose logged markets all have a result. Returns the
    number of bets, or None when nothing may be bet (no model, no plan20.py, plan20's identity check not clean, a model
    whose SHA-256 differs from the fit-time record, a model from another plan, the kill switch). Windows still waiting
    for candles or results are counted, not bet. Each row's stage_c says whether it belongs to a stage C test
    (stage_c_starts); otherwise it is descriptive only."""
    try:
        model, sha, frozen = model_info()
        Q = importlib.import_module("plan20")
        missing = [k for k in NEEDED if not hasattr(Q, k)]
        if missing:
            raise ValueError("research/plan20.py lacks %s" % ", ".join(missing))
        if model.get("plan_sha256") != getattr(Q, "PLAN_SHA256", None):
            raise ValueError("the model was not fitted under research/PLAN20.md's frozen text")
        bad = Q.identity_problems()
        if bad != []:
            raise ValueError("plan20's identity check is not clean (%s)" % (", ".join(map(str, bad or ["no answer"]))))
        mh = Q.model_hash_problem(MODEL_FILE, MODEL_SHA_FILE)
        if mh:
            raise ValueError(mh)
    except Exception as ex:
        print("live20 paper: nothing is bet yet (%s)" % ex)
        return None
    k = halted()
    if k:
        print("live20 paper: halted by the kill switch (%s); nothing written" % k)
        return None
    _, groups = series_from_file()
    res = load_results()
    t0 = now()
    windows = {}     # (close, series) -> [tickers]
    for t, (s, c) in logged_markets().items():
        if c - 60 * Q.T >= frozen and c + CANDLE_AFTER <= t0:
            windows.setdefault((c, s), []).append(t)
    try:
        stage_c = stage_c_starts(Q)
    except Exception:   # fail closed: every row descriptive
        stage_c = {}
    store = CandleStore()
    try:
        bets, waiting, out_of_time, failed = _replay(Q, model, sha, windows, res, groups, t0, budget_seconds, store,
                                                     stage_c)
    finally:
        store.flush()
    bets.sort(key=lambda b: (b["open"], b["series"]))
    tmp = _p("paper.jsonl.tmp")
    os.makedirs(DATA, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for b in bets:
            f.write(json.dumps(b, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp, _p("paper.jsonl"))
    nc = sum(1 for b in bets if b["stage_c"])
    print("live20 paper: %d paper bets (%d in a stage C test, the rest descriptive), %d windows waiting for candles or "
          "results%s%s (counts only; the verdict is PLAN20 section 5's, at day 42)" % (
              len(bets), nc, waiting, ", %d candle requests failed" % failed if failed else "",
              "; time budget used" if out_of_time else ""))
    return len(bets)


def _replay(Q, model, sha, windows, res, groups, t0, budget_seconds, store, stage_c):
    bets, waiting, out_of_time, failed = [], 0, False, 0
    for (c, s) in sorted(windows):
        tickers = sorted(windows[(c, s)])
        o = c - 60 * Q.T
        if any(t not in res for t in tickers):
            waiting += 1
            continue
        ms, ok = [], True
        for t in tickers:
            if out_of_time or now() - t0 > budget_seconds:
                out_of_time, ok = True, False
                break
            try:
                cs = candles_of(s, t, o, c, t0, store)
            except Exception as ex:
                failed += 1
                log_row("error", where="candles", ticker=t, error=str(ex)[:200])
                cs = None
            if cs is None:
                ok = False
                break
            if res[t].get("result") not in ("yes", "no"):   # plan20 keeps settled yes/no markets only
                continue
            ms.append(dict(ticker=t, close=c, open=o, result=res[t]["result"], c=Q.parse_candles(cs, o)))
        if not ok:
            waiting += 1
            continue
        g = groups.get(s) or "other"
        b = window_bet(Q, model, Q.lapaz_date(c), s, g, ms)
        if b is None:
            continue
        b = json.loads(json.dumps(b, default=str))
        b.update(open=o, close=c, fill_minute=b["m"] + 1, model_sha256=sha,
                 stage_c=bool(g in stage_c and o >= stage_c[g]))
        bets.append(b)
    return bets, waiting, out_of_time, failed


def model_info():
    """(model dict, sha256, freeze epoch) or raises ValueError with the reason (fail closed)."""
    if not os.path.exists(MODEL_FILE):
        raise ValueError("no frozen model yet (research/results/plan20_model.json)")
    with open(MODEL_FILE, "rb") as f:
        raw = f.read()
    model = json.loads(raw.decode("utf-8"))
    if not isinstance(model, dict):
        raise ValueError("the model file is not a JSON object")
    frozen = None
    for k in ("frozen", "frozen_at", "freeze_date", "frozen_utc"):
        frozen = _epoch(model.get(k))
        if frozen is not None:
            break
    if frozen is None:
        raise ValueError("the model file gives no readable freeze time")
    return model, hashlib.sha256(raw).hexdigest(), frozen


def halted():
    """The project's kill switch (core.kill_file); fails closed."""
    try:
        import core
        return core.kill_file()
    except Exception as ex:
        return "the kill-switch check failed (%s)" % ex


# ---------- status ----------
def status():
    minutes, markets, series, rows = set(), set(), set(), 0
    for r in snapshots():
        rows += 1
        minutes.add(r["minute"]); markets.add(r["ticker"]); series.add(r["series"])
    logs = jsonio.lines(_p("log.jsonl"))
    gap_rows = sum(1 for x in logs if x.get("kind") == "gap")
    err_rows = sum(1 for x in logs if x.get("kind") == "error")
    runs = sum(1 for x in logs if x.get("kind") == "run_start")
    span_missing = 0
    if minutes:
        span_missing = (max(minutes) - min(minutes)) // 60 + 1 - len(minutes)
    size = sum(os.path.getsize(f) for fs in _day_files().values() for f in fs)
    nres = len(load_results())
    nbets = len(jsonio.lines(_p("paper.jsonl"))) if os.path.exists(_p("paper.jsonl")) else None
    out = dict(runs=runs, minutes_logged=len(minutes), rows=rows, markets=len(markets), series=len(series),
               first_minute=_iso(min(minutes)) if minutes else None, last_minute=_iso(max(minutes)) if minutes else None,
               minutes_missing_in_span=span_missing, gap_rows=gap_rows, error_rows=err_rows, day_files_mb=round(size / 1e6, 2),
               results=nres, paper_bets=nbets)
    for k, v in out.items():
        print("%-24s %s" % (k, v))
    return out


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN20 forward logger (research, paper only)")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run"); r.add_argument("--minutes", type=int, required=True)
    s = sub.add_parser("settle"); s.add_argument("--budget-seconds", type=int, default=240)
    pp = sub.add_parser("paper"); pp.add_argument("--budget-seconds", type=int, default=600)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    os.makedirs(DATA, exist_ok=True)
    if a.cmd == "run":
        return run(a.minutes)
    if a.cmd == "settle":
        settle(a.budget_seconds); return 0
    if a.cmd == "paper":
        paper(a.budget_seconds); return 0
    if a.cmd == "status":
        status(); return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
