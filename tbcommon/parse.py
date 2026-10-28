"""Tolerant parsing of API values. Kalshi sends prices both as dollar strings ("0.4500", the *_dollars fields) and,
in older fields, as integer cents; counts as "12.00" strings; times as ISO 8601 with 0-9 fraction digits."""
import re
from datetime import datetime

_FRACTION = re.compile(r"(.*T\d\d:\d\d:\d\d)\.(\d+)(.*)$")


def num(v):
    """float(v), or None for None, "" and anything unparseable."""
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def px(m, k):
    """Price field k of a market or quote dict in dollars: k+"_dollars" if present, else k (in cents) / 100."""
    v = num(m.get(k + "_dollars"))
    if v is None:
        c = num(m.get(k))
        v = c / 100 if c is not None else None
    return v


def rts(s):
    """ISO time -> epoch seconds, or None. Fractions are padded to 6 digits first: Python 3.8-3.10 accept only 3 or 6."""
    try:
        x = str(s).replace("Z", "+00:00")
        m = _FRACTION.match(x)
        if m:
            x = "%s.%s%s" % (m.group(1), (m.group(2) + "000000")[:6], m.group(3))
        return datetime.fromisoformat(x).timestamp()
    except (TypeError, ValueError):
        return None


def cents(p):
    """Dollars -> whole cents (rounded)."""
    return int(round(p * 100))
