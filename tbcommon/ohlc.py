"""Checks for Kalshi candlesticks (OHLC), added 2026-10-23 (reliability work).

Several parts of the bot read prices from one-minute candles: shadow.py's price moves, research/fetch.py and plan3.py
(past data), and lip.py's adverse-selection check. Each takes "the latest candle at or before t" and trusts it. These
checks say when that trust is misplaced. They only report: no caller changes its numbers because of them, so
pre-registered tests stay as registered.

A candle is a dict with end_period_ts and three OHLC blocks, yes_bid, yes_ask and price (trades). Each block holds
open, low, high and close, as dollar strings (*_dollars) or as cents. Any field can be missing; a block with no
trades has no prices.

Anomaly codes (per candle unless noted):
- TIME_NOT_INCREASING: end_period_ts not after the previous candle's (series level).
- OFF_GRID: end_period_ts not a whole multiple of the period.
- FUTURE: ends after `now` plus one period (clock or data error).
- OUT_OF_RANGE: a price below 0 or above 1 dollar.
- HIGH_BELOW_LOW: high < low in a block.
- OPEN_CLOSE_OUTSIDE: open or close outside [low, high] in a block.
- EMPTY_SIDE: the bid or ask close sits at 0 or 1: no real order rests at those prices, so that side of the book was
  empty (or the market was settling). Informational, and CROSSED, LOCKED and TRADE_OUTSIDE_QUOTE are not tested on such a candle,
  because Kalshi's placeholder prices for an empty side are not quotes (review 2026-10-23).
- CROSSED: yes bid close above yes ask close, both sides present (a mid from it is meaningless).
- LOCKED: yes bid close equal to yes ask close, both sides present (an exchange that matches orders cannot rest there).
- NEGATIVE_VOLUME: volume below 0.
- TRADE_OUTSIDE_QUOTE: the trade close is more than 1c outside that candle's [bid low, ask high].
- JUMP: the mid moves more than JUMP between consecutive candles. Informational: weather markets can jump when an
  observation lands, but a jump next to an anomaly is worth a look.
- GAP: no candle for more than MAX_GAP seconds inside the window (series level, informational: Kalshi only sends
  candles for minutes when something changed, so "the latest candle" can be old).
Format (Kalshi's API reference, read 2026-10-23): yes_bid, yes_ask and price blocks with open/low/high/close as
*_dollars strings; price fields are null when nothing traded; volume_fp is a count string. Older answers used integer
cents without the suffix; both are read.
Python 3.8+, standard library only."""

JUMP = 0.50
INFO_CODES = ("JUMP", "GAP", "EMPTY_SIDE")   # worth counting, not evidence of broken data
MAX_GAP = 6 * 3600


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def field(block, k):
    """One OHLC value in dollars from a candle block: k_dollars if present, else k (integer cents / 100, or a dollar
    string such as "0.4500" as some Kalshi endpoints send without the suffix)."""
    if not isinstance(block, dict):
        return None
    v = _num(block.get(k + "_dollars"))
    if v is None:
        raw = block.get(k)
        c = _num(raw)
        if c is not None:
            v = c if (isinstance(raw, str) and "." in raw) else c / 100
    return v


def empty_side(b, a):
    """True when either price sits at 0 or 1 (or beyond): no real order rests there, so it is the placeholder for an
    empty side, whichever way Kalshi encodes it (a missing ask as 0 or as 1, a missing bid as 0)."""
    return any(x is not None and (x <= 0 or x >= 1) for x in (b, a))


def ohlc(c, name):
    """(open, low, high, close) of block `name` (yes_bid, yes_ask or price) in dollars; None where missing."""
    b = c.get(name) or {}
    return tuple(field(b, k) for k in ("open", "low", "high", "close"))


def mid(c):
    """Mid from the bid and ask closes, or None when either is missing or empty (0 bid, 1 ask), or the quote is crossed
    or locked: a mid against an empty side is a placeholder, not a price."""
    b, a = ohlc(c, "yes_bid")[3], ohlc(c, "yes_ask")[3]
    if b is None or a is None or not (0 < b < a < 1):
        return None
    return (a + b) / 2


def check_candle(c, period=60, now=None):
    """Anomaly codes for one candle (see the module docstring)."""
    out = []
    t = c.get("end_period_ts")
    if isinstance(t, (int, float)):
        if period and t % period:
            out.append("OFF_GRID")
        if now is not None and t > now + period:
            out.append("FUTURE")
    for name in ("yes_bid", "yes_ask", "price"):
        o, lo, hi, cl = ohlc(c, name)
        vals = [v for v in (o, lo, hi, cl) if v is not None]
        if any(v < 0 or v > 1 for v in vals):
            out.append("OUT_OF_RANGE")
        if lo is not None and hi is not None:
            if hi < lo:
                out.append("HIGH_BELOW_LOW")
            elif any(v is not None and not (lo - 1e-9 <= v <= hi + 1e-9) for v in (o, cl)):
                out.append("OPEN_CLOSE_OUTSIDE")
    b, a = ohlc(c, "yes_bid")[3], ohlc(c, "yes_ask")[3]
    empty = empty_side(b, a)
    if empty:
        out.append("EMPTY_SIDE")
    elif b is not None and a is not None:
        if b > a + 1e-9:
            out.append("CROSSED")
        elif abs(b - a) <= 1e-9:
            out.append("LOCKED")
    vol = _num(c.get("volume_fp")) if c.get("volume_fp") is not None else _num(c.get("volume"))
    if vol is not None and vol < 0:
        out.append("NEGATIVE_VOLUME")
    tc = ohlc(c, "price")[3]
    blo, ahi = ohlc(c, "yes_bid")[1], ohlc(c, "yes_ask")[2]
    if not empty and not empty_side(blo, ahi) and tc is not None and blo is not None and ahi is not None \
            and not (blo - 0.01 - 1e-9 <= tc <= ahi + 0.01 + 1e-9):
        out.append("TRADE_OUTSIDE_QUOTE")
    return sorted(set(out))


def check_series(cs, period=60, now=None, start=None, end=None):
    """[(index or None, code)] for a candle list in the order received. Series-level codes have index None."""
    out = []
    last_t = None
    last_mid = None
    times = []
    for i, c in enumerate(cs):
        for code in check_candle(c, period, now):
            out.append((i, code))
        t = c.get("end_period_ts")
        if isinstance(t, (int, float)):
            if last_t is not None and t <= last_t:
                out.append((i, "TIME_NOT_INCREASING"))
            last_t = t
            times.append(t)
        m = mid(c)
        if m is not None and last_mid is not None and abs(m - last_mid) > JUMP:
            out.append((i, "JUMP"))
        if m is not None:
            last_mid = m
    edges = sorted(times)
    if start is not None:
        edges = [start] + edges
    if end is not None:
        edges = edges + [end]
    if any(b - a > MAX_GAP for a, b in zip(edges, edges[1:])):
        out.append((None, "GAP"))
    return out


def summary(results):
    """results: [codes per series] -> {code: count}."""
    out = {}
    for codes in results:
        for _, code in codes:
            out[code] = out.get(code, 0) + 1
    return out
