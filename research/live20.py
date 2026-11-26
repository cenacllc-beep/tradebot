"""PLAN20 forward logger (research/PLAN20.md, sections 2 and 5): live snapshots of every 15-minute Kalshi market, their
results, and paper bets by PLAN20's frozen rule once its model exists. Research and paper only.

    python research/live20.py run --minutes N     one snapshot of every open market each minute (+5 s), for N minutes
    python research/live20.py settle [--budget-seconds S]   results of logged markets that have closed
    python research/live20.py paper               replay the snapshots with the frozen rule (only once the model exists)
    python research/live20.py status              counts only (minutes, markets, gaps); never a profit figure

What it never does: place, change or cancel an order (no order endpoint exists in this file), import live.py, or touch
paper.db, live.db or trial/. Kalshi's public API only, read-only GETs, through tbcommon's JsonClient (the project's only
User-Agent, retries, a minimum gap between requests).

Files (research/data/live20/, overridable with LIVE20_DATA for tests):
- snap-YYYYMMDD.jsonl: one row per open market per minute (UTC day of the minute). A finished day is gzipped to
  snap-YYYYMMDD.jsonl.gz at the end of a run (readers take both).
  Row: ts (read time), minute (the minute boundary the row stands for: the close of PLAN20's candle ending there),
  ticker, series, event, open, close (epoch seconds), status, yes_bid, yes_ask, no_bid, no_ask, last (dollars),
  volume, oi (contracts; volume is Kalshi's running total for the market). NO is derived as PLAN20 section 2 says:
  no_ask = 1 - yes_bid, no_bid = 1 - yes_ask.
- log.jsonl: run_start / run_end rows, a "gap" row for every minute not read (late or every request failed) and an
  "error" row for every series that failed in a minute.
- results.json: {ticker: {result, yes_pay, no_pay, status, close, settled_ts}} by strategy.payout's rules.
- paper.jsonl: the paper bets (rebuilt in full by each `paper` run from the logged snapshots, so it is idempotent).

The paper rule (PLAN20 sections 2 and 5): windows that opened at or after the model's freeze time; minutes m = 1..13
in order, markets by ticker, YES before NO; a chance is a side whose ask at minute m is 1-10c; the decision comes from
research/plan20.py (imported lazily: features() and decide(), see _rule) and sees only minutes 1..m; the fill is the
side's ask in the snapshot of minute m+1, used only if that snapshot exists, shows 0 < bid < ask and the ask is at most
10c (a quote is never carried forward to a fill); a skipped fill does not use up the side; one bet per window per
series; a $1 bet: C = floor(1 / P) contracts, fee = round-up-to-cent(0.07 x C x P x (1 - P)). Without the model file
or plan20.py, nothing is bet (fail closed). Python 3.8+.
"""
import argparse
import glob
import gzip
import hashlib
import importlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

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

OFFSET = 5            # seconds after each minute boundary that the snapshot is read
LATE = 25             # a minute whose read cannot start within OFFSET + LATE seconds of its boundary is a gap
SETTLE_AFTER = 120    # a market is asked for its result this long after it closes
CHEAP = (0.01, 0.10)  # PLAN20 section 2: a chance's ask, and the most a fill may cost
MINUTES = 15
FEE_RATE = 0.07
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


def log_row(kind, **f):
    row = dict(kind=kind, ts=round(now(), 1))
    row.update(f)
    jsonio.append(_p("log.jsonl"), [row])


def day_of(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d")


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
    while target + OFFSET <= end:
        sleep_until(target + OFFSET)
        late = now() - (target + OFFSET)
        if late > LATE:
            log_row("gap", minute=int(target), why="read could not start in time (%.0f s late)" % late)
            gaps += 1
            target += 60
            continue
        try:
            rows, failed = snapshot(series, target)
            jsonio.append(_p("snap-%s.jsonl" % day_of(target)), rows)
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
def _day_files():
    """{YYYYMMDD: [paths]} (gz before plain)."""
    out = {}
    for f in glob.glob(_p("snap-*.jsonl*")):
        m = re.match(r"snap-(\d{8})\.jsonl(\.gz)?$", os.path.basename(f))
        if m:
            out.setdefault(m.group(1), []).append(f)
    for k in out:
        out[k].sort(key=lambda f: 0 if f.endswith(".gz") else 1)
    return out


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


def compact(today=None):
    """Gzip every finished UTC day's file (days before today); a day with both a .gz and a plain file is merged."""
    today = today or day_of(now())
    for d, paths in _day_files().items():
        plain = _p("snap-%s.jsonl" % d)
        if d >= today or plain not in paths:
            continue
        gz = plain + ".gz"
        seen, rows = set(), []
        for f in paths:
            for r in _read_lines(f):
                k = (r.get("minute"), r.get("ticker"))
                if k not in seen:
                    seen.add(k); rows.append(r)
        tmp = gz + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        os.replace(tmp, gz)
        os.remove(plain)


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
def fee_for(price):
    """(contracts, fee) of a $1 bet at price P (PLAN20 section 2: whole-cent round-up)."""
    c = int(math.floor(1.0 / price + 1e-9))
    return c, math.ceil(FEE_RATE * c * price * (1 - price) * 100 - 1e-9) / 100


def side_quote(row, side):
    """(bid, ask) of one side from a snapshot row."""
    return (row.get("yes_bid"), row.get("yes_ask")) if side == "yes" else (row.get("no_bid"), row.get("no_ask"))


def candle(row, prev):
    """A snapshot row as PLAN20's minute candle (yes quotes, last, the minute's volume from the running total)."""
    vol = None
    if prev is not None and row.get("volume") is not None and prev.get("volume") is not None:
        vol = max(0.0, row["volume"] - prev["volume"])
    return dict(end_period_ts=row["minute"], yes_bid=row.get("yes_bid"), yes_ask=row.get("yes_ask"),
                no_bid=row.get("no_bid"), no_ask=row.get("no_ask"), last=row.get("last"), volume=vol,
                volume_total=row.get("volume"), open_interest=row.get("oi"))


def history(rows_by_min, open_ts, upto):
    """{m: candle} for minutes 1..upto that were logged (nothing after `upto`: no look-ahead)."""
    out = {}
    for m in range(1, upto + 1):
        r = rows_by_min.get(open_ts + 60 * m)
        if r is not None:
            out[m] = candle(r, rows_by_min.get(open_ts + 60 * (m - 1)))
    return out


def _rule(mod, model, hist, m, side, meta, ask):
    """PLAN20's frozen rule through research/plan20.py. Assumed interface (to be matched by plan20.py):
    features(history, m, side, meta) -> the feature values; decide(model, features, ask) -> True to bet.
    `history` holds candles 1..m only; meta = ticker, series, event, open, close, group."""
    return bool(mod.decide(model, mod.features(hist, m, side, meta), ask))


def decide_window(markets, mod, model, groups):
    """The window's one bet (dict) or None. markets: {ticker: {minute: row}} for one series and one open time."""
    any_rows = next(iter(markets.values()))
    first = next(iter(any_rows.values()))
    o, c, series = first["open"], first["close"], first["series"]
    for m in range(1, MINUTES - 1):          # 1..13
        for t in sorted(markets):
            by_min = markets[t]
            row = by_min.get(o + 60 * m)
            if row is None:
                continue
            for side in ("yes", "no"):
                ask = side_quote(row, side)[1]
                if ask is None or not (CHEAP[0] - 1e-9 <= ask <= CHEAP[1] + 1e-9):
                    continue
                meta = dict(ticker=t, series=series, event=row.get("event"), open=o, close=c, group=groups.get(series))
                if not _rule(mod, model, history(by_min, o, m), m, side, meta, ask):
                    continue
                nxt = by_min.get(o + 60 * (m + 1))   # the fill: the next minute's logged ask, never carried forward
                if nxt is None:
                    continue
                bid, fill = side_quote(nxt, side)
                if bid is None or fill is None or not (0 < bid < fill) or fill > CHEAP[1] + 1e-9:
                    continue
                n, fee = fee_for(fill)
                return dict(series=series, event=row.get("event"), ticker=t, side=side, open=o, close=c,
                            group=groups.get(series), decision_minute=m, decision_ask=ask, fill_minute=m + 1,
                            fill_price=fill, contracts=n, fee=fee)
    return None


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


def paper():
    """Rebuild paper.jsonl from the logged snapshots by the frozen rule. Returns the number of bets, or None when
    nothing may be bet (no model, no plan20.py, the kill switch)."""
    try:
        model, sha, frozen = model_info()
        mod = importlib.import_module("plan20")
        if not (callable(getattr(mod, "features", None)) and callable(getattr(mod, "decide", None))):
            raise ValueError("research/plan20.py has no features() and decide()")
    except Exception as ex:
        print("live20 paper: nothing is bet yet (%s)" % ex)
        return None
    k = halted()
    if k:
        print("live20 paper: halted by the kill switch (%s); nothing written" % k)
        return None
    from strategy import settled_pnl
    _, groups = series_from_file()
    res = load_results()
    t_now = now()
    windows = {}     # (series, open) -> {ticker: {minute: row}}
    bets = []

    def finish(key):
        mk = windows.pop(key)
        b = decide_window(mk, mod, model, groups)
        if b is None:
            return
        r = res.get(b["ticker"])
        if r:
            pay = r["yes_pay"] if b["side"] == "yes" else r["no_pay"]
            n = b["contracts"]
            b.update(result=r["result"], pay=pay,
                     pnl_per_contract=round(settled_pnl(r["result"], b["side"], n, n * b["fill_price"], b["fee"], pay) / n, 6))
        b["model_sha256"] = sha
        bets.append(b)

    cur = None
    for r in snapshots():
        o, c = r.get("open"), r.get("close")
        if o is None or c is None or o < frozen:
            continue
        if r["minute"] != cur:   # a new minute: windows closed before it can get no more rows
            cur = r["minute"]
            for k2 in sorted(k3 for k3 in windows if k3[2] + 60 <= cur):
                finish(k2)
        key = (r["series"], o, c)
        windows.setdefault(key, {}).setdefault(r["ticker"], {})[r["minute"]] = r
    for k2 in sorted(k3 for k3 in windows if k3[2] + 60 <= t_now):   # closed by the clock: no more rows can come
        finish(k2)
    bets.sort(key=lambda b: (b["open"], b["series"]))
    tmp = _p("paper.jsonl.tmp")
    os.makedirs(DATA, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for b in bets:
            f.write(json.dumps(b, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp, _p("paper.jsonl"))
    print("live20 paper: %d paper bets (counts only; the verdict is PLAN20 section 5's, at day 42)" % len(bets))
    return len(bets)


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
    sub.add_parser("paper"); sub.add_parser("status")
    a = ap.parse_args(argv)
    os.makedirs(DATA, exist_ok=True)
    if a.cmd == "run":
        return run(a.minutes)
    if a.cmd == "settle":
        settle(a.budget_seconds); return 0
    if a.cmd == "paper":
        paper(); return 0
    if a.cmd == "status":
        status(); return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
