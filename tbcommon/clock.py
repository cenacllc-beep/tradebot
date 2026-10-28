"""One clock and one way to write times (added 2026-10-23, reliability work).

Why: reports stamped times in whatever zone the PC happened to use, without saying which, and the same evening could
read "Oct 22" in one file and "2026-10-23T00:55" in another. The bot's own zone is America/La_Paz, UTC-4 all year
(Bolivia has had no daylight saving since 1932), so a fixed offset is exact and needs no tz database (Windows Python
often has none).

- BOT_TZ: the bot's zone. iso(ts): "2026-10-23T10:33:00-04:00", unambiguous, for files and logs.
- label(ts): "Oct 23, 10:33 AM", for people (always bot time; the zone is named once per page, ZONE_NOTE).
- bot_date(ts): the calendar date in bot time, for grouping by day.
- pc_offset_hours(): this machine's own UTC offset right now; freshness.py warns when it differs from BOT_TZ, because
  pages built from the PC's local time would then disagree with the reports.
Kalshi market days and all stored epoch timestamps are unaffected: they are UTC by definition. Python 3.8+."""
import time
from datetime import datetime, timezone, timedelta

BOT_TZ = timezone(timedelta(hours=-4), "UTC-4")
ZONE_NOTE = "La Paz time (UTC-4)"


def now():
    return time.time()


def iso(ts=None, seconds=True):
    """Epoch seconds -> ISO 8601 in bot time with its offset. None -> now."""
    d = datetime.fromtimestamp(now() if ts is None else ts, BOT_TZ)
    return d.isoformat(timespec="seconds" if seconds else "minutes")


def label(ts):
    """Epoch seconds -> "Oct 23, 10:33 AM" in bot time (no zero padding; works on Windows); "never" for None or 0."""
    if not ts:
        return "never"
    d = datetime.fromtimestamp(ts, BOT_TZ)
    return "%s %d, %d:%02d %s" % (d.strftime("%b"), d.day, (d.hour % 12) or 12, d.minute, "AM" if d.hour < 12 else "PM")


def bot_date(ts):
    """Epoch seconds -> the date in bot time (datetime.date)."""
    return datetime.fromtimestamp(ts, BOT_TZ).date()


def pc_offset_hours(ts=None):
    """This machine's UTC offset in hours at ts (now by default), from the OS time zone settings."""
    t = now() if ts is None else ts
    off = datetime.fromtimestamp(t).astimezone().utcoffset()
    return off.total_seconds() / 3600.0 if off is not None else 0.0


def age(ts, at=None):
    """Seconds since ts (negative when ts is in the future), or None."""
    if ts is None:
        return None
    return (now() if at is None else at) - ts


def human_age(seconds):
    """3,700 -> "1 h 2 min"; None -> "unknown"; negative -> "in the future"."""
    if seconds is None:
        return "unknown"
    if seconds < 0:
        return "%s in the future" % human_age(-seconds)
    m = int(seconds // 60)
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    if h < 48:
        return "%d h %d min" % (h, m) if m else "%d h" % h
    return "%d days" % (h // 24)
