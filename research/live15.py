"""PLAN15F: live PAPER bets on Kalshi's 15-minute BTC and ETH up-or-down markets (research/PLAN15F.md).

    python research/live15.py tick      settle finished paper bets, then follow the current window to minute 10
    python research/live15.py settle    settle finished paper bets only
    python research/live15.py report    print the record (descriptive)

Paper only. It never sends an order, never imports live.py, never writes paper.db or live.db. Its own ledger is
research/data/live15.db; its log is logs/live15.log. The model, the fee and the request helpers are PLAN15's own
(research/plan15.py, frozen; imported, never changed): the same model, edge and fee as PLAN15. It fills at the live
ask read within 60 s of the minute (PLAN15 uses the ask at the close of minute k+1), bets only on "above" windows and
only when the book shows a contract at the ask. Started every 15
minutes by Windows Task Scheduler (tasks\\live15.cmd, installed by the user with tasks\\install_live15.cmd).
"""
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import plan15 as P   # noqa: E402  (PLAN15's frozen helpers: rw_prob, sigma_from, fee, http_kalshi, http_coinbase)
from strategy import payout, settled_pnl   # noqa: E402  (the project's settlement rule; read-only use)

DB = os.environ.get("LIVE15_DB") or os.path.join(HERE, "data", "live15.db")
LOG = os.environ.get("LIVE15_LOG") or os.path.join(ROOT, "logs", "live15.log")
KS = P.KS                    # decision minutes 2, 5, 10
EDGE = P.EDGE                # 4 points
WAIT_SPOT = 45               # seconds after a minute ends that Coinbase's candle may take to appear
LATE = 60                    # a decision is skipped when it cannot be made within this many seconds of its minute's end
RUN_LIMIT = 14 * 60          # a run never lasts longer than this (the next one starts 15 minutes after it)
SETTLE_AFTER = 120           # a window is asked for its result this long after it closes

SCHEMA = """
create table if not exists bets(
  id integer primary key, window text not null, asset text not null, k integer not null, ts real not null,
  open_ts real not null, close_ts real not null, strike real, strike_type text, s_k real, sigma real, p_up real,
  yes_ask real, no_ask real, yes_size real, no_size real, side text, price real, fee real, status text not null,
  note text, result text, pnl real, settled_ts real, book_ts real, unique(window, k));
create table if not exists runs(id integer primary key, ts real not null, kind text not null, note text);
"""


def now():
    return time.time()


def sleep_until(t):
    while True:
        d = t - now()
        if d <= 0:
            return
        time.sleep(min(d, 5.0))


def log(msg):
    line = "%s %s" % (datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), msg)
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.executescript(SCHEMA)
    return c


# ---------- Kalshi ----------
def _price(v):
    """A price level's price in dollars: a dollar string ("0.4500"), or integer cents (older shape)."""
    if isinstance(v, str):
        return P.num(v)
    x = P.num(v)
    return None if x is None else x / 100.0   # the older shape gives whole cents


def best_bid(levels):
    """(best price, size) from [[price, size], ...] (any order); (None, 0) when empty or unreadable."""
    best = (None, 0.0)
    for lv in levels or []:
        try:
            p, n = _price(lv[0]), P.num(lv[1]) or 0.0
        except (TypeError, IndexError):
            continue
        if p is not None and 0 < p < 1 and n > 0 and (best[0] is None or p > best[0]):
            best = (p, n)
    return best


def asks(book):
    """(yes ask, its size, no ask, its size) from Kalshi's order book (bids only: a NO bid at x is a YES ask at 1 - x)."""
    ob = book.get("orderbook_fp") or book.get("orderbook") or {}
    yes = ob.get("yes_dollars") if "yes_dollars" in ob else ob.get("yes")
    no = ob.get("no_dollars") if "no_dollars" in ob else ob.get("no")
    yb, yn = best_bid(yes)
    nb, nn = best_bid(no)
    return (None if nb is None else round(1 - nb, 4), nn, None if yb is None else round(1 - yb, 4), yn)


def current_market(asset, t):
    """The asset's window open at time t: dict(ticker, open, close, strike, strike_type), or None."""
    r = P.http_kalshi("/markets", dict(series_ticker=P.SERIES[asset], status="open", limit=50))
    for m in (r or {}).get("markets") or []:
        o, c = P.ts_of(m.get("open_time")), P.ts_of(m.get("close_time"))
        if o is None or c is None or not (o <= t < c) or abs((c - o) - P.T_MIN * 60) > 1:
            continue
        return dict(ticker=m["ticker"], open=o, close=c, strike=P.num(m.get(P.REF_FIELD)), strike_type=m.get("strike_type"))
    return None


def fee_mult(asset):
    """The series' fee multiplier when its fee type is quadratic (PLAN15), else None: no bet without a known fee."""
    r = P.http_kalshi("/series/%s" % P.SERIES[asset]) or {}
    s = r.get("series") or r
    return P.num(s.get("fee_multiplier")) if s.get("fee_type") in P.QUADRATIC else None


# ---------- the rule ----------
def decide(p_up, ya, ysz, na, nsz):
    """(side, price, note) by PLAN15's rule: model minus the ask on one side at least EDGE; one contract, only if the
    book shows one at that ask. The larger edge wins if both sides qualify (they cannot both, short of a crossed book)."""
    cands = []
    if ya is not None and p_up - ya >= EDGE - 1e-9:
        cands.append((p_up - ya, "yes", ya, ysz))
    if na is not None and (1 - p_up) - na >= EDGE - 1e-9:
        cands.append(((1 - p_up) - na, "no", na, nsz))
    if not cands:
        return None, None, "no signal"
    e, side, price, size = max(cands)
    if not (0 < price < 1) or size < 1:
        return side, price, "no fill: nothing for sale at the ask"
    return side, price, "filled"


def spot_close(asset, end_ts):
    """Coinbase's one-minute close for the minute ending at end_ts, waiting up to WAIT_SPOT seconds for it."""
    deadline = end_ts + WAIT_SPOT
    sleep_until(end_ts + 2)   # Coinbase serves the minute in progress; ask once it has ended
    while True:
        got = P.fetch_spot(asset, end_ts, end_ts).get(int(end_ts))
        if got:
            return got[3]
        if now() >= deadline:
            return None
        time.sleep(3)


def sigma(asset, open_ts):
    sp = P.fetch_spot(asset, open_ts - 60 * P.SIGMA_MIN, open_ts)
    return P.sigma_from([(sp.get(int(open_ts) + 60 * i) or [None] * 4)[3] for i in range(-P.SIGMA_MIN, 1)])


def record(c, w, asset, k, **f):
    cols = dict(window=w["ticker"], asset=asset, k=k, ts=now(), open_ts=w["open"], close_ts=w["close"],
                strike=w["strike"], strike_type=w["strike_type"])
    cols.update(f)
    try:
        c.execute("insert into bets(%s) values(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(cols.values()))
        c.commit()
    except sqlite3.IntegrityError:   # this window and minute were already decided (a second copy of the job)
        pass


def safe_record(c, w, asset, k, **f):
    """record(), but a database error (for example a lock held too long) is logged, never raised."""
    try:
        record(c, w, asset, k, **f)
    except Exception as ex:
        log("%s %s minute %d: could not be recorded (%s)" % (asset, w["ticker"], k, ex))


def skip(c, w, asset, why):
    """A window found but not bet on: each of its decisions is recorded as missed, with the reason."""
    log("%s %s: %s; skipped" % (asset, w["ticker"], why))
    for k in KS:
        safe_record(c, w, asset, k, status="missed", note=why)


def follow(c, start):
    """Follow the window open at `start` for both assets to minute 10, deciding at minutes 2, 5 and 10."""
    plan = []
    for a in P.ASSETS:
        w = None
        try:
            w = current_market(a, start)
            if not w:
                log("%s: no open 15-minute window found" % a)
                continue
            if w["strike"] is None:
                skip(c, w, a, "no reference price on the market")
                continue
            if w["strike_type"] not in ("greater", "greater_or_equal"):   # the model reads "above the reference"
                skip(c, w, a, "strike type %s is not an 'above' question" % w["strike_type"])
                continue
            mult, sig = fee_mult(a), sigma(a, w["open"])
            if mult is None or sig is None:
                skip(c, w, a, "fee type not quadratic or unreadable" if mult is None else "no volatility (Coinbase minutes missing)")
                continue
            plan.append((a, w, mult, sig))
        except Exception as ex:   # one asset's failure never stops the other
            log("%s: could not set up the window (%s)" % (a, ex))
            if w:
                skip(c, w, a, "set-up error: %s" % str(ex)[:150])
    for k in KS:
        for a, w, mult, sig in plan:
            end = w["open"] + 60 * k
            if c.execute("select 1 from bets where window=? and k=?", (w["ticker"], k)).fetchone():
                continue
            if halted():
                safe_record(c, w, a, k, status="missed", note="halted by the kill switch")
                continue
            if now() > end + LATE or now() > start + RUN_LIMIT:
                safe_record(c, w, a, k, status="missed", note="the run reached minute %d too late" % k)
                continue
            sleep_until(end)
            try:
                s_k = spot_close(a, end)
                if s_k is None:
                    record(c, w, a, k, sigma=sig, status="missed", note="no Coinbase price for minute %d" % k)
                    continue
                p_up = P.rw_prob(s_k, w["strike"], sig, k)
                if now() > end + LATE:
                    record(c, w, a, k, s_k=s_k, sigma=sig, p_up=p_up, status="missed", note="the price came too late")
                    continue
                ya, ysz, na, nsz = asks(P.http_kalshi("/markets/%s/orderbook" % w["ticker"]) or {})
                book_ts = now()
                if book_ts > end + LATE:   # a slow read would bet minutes later on the minute-k model
                    record(c, w, a, k, s_k=s_k, sigma=sig, p_up=p_up, book_ts=book_ts, status="missed",
                           note="the order book came too late (%.0f s after minute %d)" % (book_ts - end, k))
                    continue
                side, price, note = decide(p_up, ya, ysz, na, nsz)
                f = P.fee(price, mult) if note == "filled" else None
                record(c, w, a, k, s_k=s_k, sigma=sig, p_up=p_up, yes_ask=ya, no_ask=na, yes_size=ysz, no_size=nsz,
                       side=side, price=price if note == "filled" else None, fee=f,
                       status="open" if note == "filled" else ("no signal" if note == "no signal" else "no fill"), note=note,
                       book_ts=book_ts)
                log("%s %s minute %d: model %.1f%% up; YES ask %s, NO ask %s; %s%s" % (
                    a, w["ticker"], k, 100 * p_up, "-" if ya is None else "%.0fc" % (100 * ya), "-" if na is None else "%.0fc" % (100 * na),
                    note, (": paper %s at %.0fc + fee %.2f" % (side.upper(), 100 * price, f)) if note == "filled" else ""))
            except Exception as ex:
                safe_record(c, w, a, k, status="missed", note="error: %s" % str(ex)[:200])
                log("%s %s minute %d: error (%s)" % (a, w["ticker"], k, ex))


def settle(c):
    """Record the result of every paper bet whose window closed at least SETTLE_AFTER seconds ago."""
    n = 0
    for t, in c.execute("select distinct window from bets where status='open' and close_ts<=?", (now() - SETTLE_AFTER,)).fetchall():
        try:
            m = (P.http_kalshi("/markets/%s" % t) or {}).get("market") or {}
        except Exception as ex:
            log("settle %s: %s (tried again next run)" % (t, ex))
            continue
        for bid, side, price, fee in c.execute("select id,side,price,fee from bets where window=? and status='open'", (t,)).fetchall():
            got = payout(m, side)   # the project's settlement rule (strategy.payout): yes/no, scalar or void
            if got is None:
                continue            # not settled yet
            res, pay = got
            pnl = round(settled_pnl(res, side, 1, price, fee, pay), 4)
            c.execute("update bets set status='settled', result=?, pnl=?, settled_ts=? where id=?", (res, pnl, now(), bid))
            n += 1
        c.commit()
    return n


def halted():
    """The project's kill switch (core.killed): a KILL file stops these paper bets too. Fails closed."""
    try:
        import core
        return core.kill_file()
    except Exception as ex:
        return "the kill-switch check failed (%s)" % ex


def tick():
    start = now()
    k = halted()
    c = db()
    c.execute("insert into runs(ts,kind) values(?,?)", (start, "tick")); c.commit()
    if k:
        log("halted by the kill switch (%s): no paper bets this run" % k)
    else:
        follow(c, start)   # first, so a slow settlement never delays minute 2
    try:                   # results are still recorded while the kill switch is on (it stops betting only)
        n = settle(c)
        if n:
            log("settled %d paper bet%s" % (n, "" if n == 1 else "s"))
    except Exception as ex:
        log("settle: %s" % ex)
    log("run done: %s" % summary(c))
    c.close()


# ---------- the record (descriptive) ----------
def rows(c):
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute("select * from bets order by ts")]


def stats(bets):
    """Descriptive numbers: counts, net, per-bet mean and its standard error over UTC days (each day counts once)."""
    filled = [b for b in bets if b["status"] in ("open", "settled")]
    done = [b for b in filled if b["status"] == "settled"]
    days = {}
    for b in done:
        days.setdefault(datetime.fromtimestamp(b["close_ts"], timezone.utc).date(), []).append(b["pnl"])
    means = [sum(v) / len(v) for v in days.values()]
    se = None
    if len(means) >= 2:
        mu = sum(means) / len(means)
        se = math.sqrt(sum((m - mu) ** 2 for m in means) / (len(means) - 1) / len(means))
    return dict(decisions=len(bets), filled=len(filled), open=len(filled) - len(done), settled=len(done),
                won=sum(1 for b in done if b["pnl"] > 0), net=round(sum(b["pnl"] for b in done), 4),
                fees=round(sum(b["fee"] or 0 for b in done), 4),
                per_bet=(sum(b["pnl"] for b in done) / len(done)) if done else None,
                day_mean=(sum(means) / len(means)) if means else None, day_se=se, days=len(means),
                no_signal=sum(1 for b in bets if b["status"] == "no signal"),
                no_fill=sum(1 for b in bets if b["status"] == "no fill"),
                missed=sum(1 for b in bets if b["status"] == "missed"))


def summary(c):
    s = stats(rows(c))
    return ("%d decisions, %d paper bets (%d open), %d settled: %d won, net %+.2f after %.2f of fees; %d no signal, "
            "%d no fill, %d missed" % (s["decisions"], s["filled"], s["open"], s["settled"], s["won"], s["net"],
                                       s["fees"], s["no_signal"], s["no_fill"], s["missed"]))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "tick":
        try:
            tick()
        except Exception:   # the scheduled run has no console (pythonw): the traceback goes to the log
            import traceback
            log("run failed:\n" + traceback.format_exc())
            sys.exit(1)
    elif cmd == "settle":
        c = db(); log("settled %d" % settle(c))
    elif cmd == "report":
        print("PLAN15F (paper, research; descriptive):", summary(db()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
