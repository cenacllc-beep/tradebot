"""The v3 gate's rules with no dependencies (added 2026-10-22, refactor stage 1), for code that must work even when the
trading modules cannot be imported: the dashboard.

strategy.py is frozen until the 2026-11-11 verdict, so it keeps its own copy of these rules for now. tests/test_fix.py
checks that the two copies give identical answers (stop date, t-table, tcrit, clear, margin on random inputs). Stage 2
of docs/REFACTOR.md has strategy.py import this module and deletes its copy. Never edit one copy without the other.
Python 3.8+, standard library only."""
from datetime import date

STOP_DATE = date(2026, 11, 11)   # 28 market days (Oct 14 - Nov 10), judged once; moved from Oct 26 by the user on 2026-10-14

# Student-t 97.5% critical values by degrees of freedom
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def margin(o):
    """The gate's 'clear margin' (defined 2026-10-14). o: [(ticker, forecast, market mid, result)]. Forecast Brier minus
    market Brier for each market, averaged within each market day (cities on one day share weather, so each day counts
    once). Returns (mean, standard error, days), or None with fewer than 5 days."""
    days = {}
    for t, f, m, r in o:
        y = 1.0 if r == "yes" else 0.0
        days.setdefault(t.split("-")[1], []).append((f - y) ** 2 - (m - y) ** 2)
    d = [sum(v) / len(v) for v in days.values()]
    if len(d) < 5:
        return None
    mu = sum(d) / len(d)
    return mu, (sum((x - mu) ** 2 for x in d) / (len(d) - 1) / len(d)) ** 0.5, len(d)


def tcrit(days):
    """Student-t 97.5% critical value for the day means (df = days - 1), never below 2.0 (2026-10-14, user approved)."""
    return max(2.0, T975.get(days - 1, 2.0))


def clear(mg):
    """Clear margin: the mean is below zero by at least tcrit standard errors."""
    return mg is not None and mg[0] < 0 and -mg[0] >= tcrit(mg[2]) * mg[1]


def final(today=None):
    """True on or after the stop date, when the gate is judged (once)."""
    return (today or date.today()) >= STOP_DATE
