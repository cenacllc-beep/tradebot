"""Is it inside the evening scan window? (added 2026-10-23, outage review). Read-only: no file, database or network.

tasks\\evening.cmd asks this before it scans. Windows Task Scheduler now starts a missed evening run as soon as the PC
is available (StartWhenAvailable, see tasks\\install_schedules.ps1), so a run can start at any hour: for example the
next morning, when the laptop was off at 8:55 PM. The scan must not run then:
- paper.db's obs table keeps the FIRST snapshot of each market, and the gate's Brier comparison reads it, so a morning
  scan would replace the evening forecast-vs-price snapshot of the next day's markets for good;
- trades would open about 20 hours before their market day instead of about 4 (the design in CLAUDE.md section 10).
Inside the window (8:50 PM to 0:59 AM, this PC's local time, the same clock Task Scheduler uses) a late run still
scans: markets whose day has begun are skipped by strategy.started as always. The window opens at 8:50 PM, not
earlier (review 2026-10-23): shadow.py logs the airport forecast once per market and counts it for its forward test
only between 00:50 and 01:30 UTC (8:50 to 9:30 PM here), so an earlier make-up scan would cost that test a market day,
and obs would keep a snapshot taken before the designed 8:55 PM one.

  python scan_window.py   -> exit 0 inside the window, 3 outside (and a one-line reason). Only the scheduled evening
                             run asks; a scan by hand belongs in the same window.
Python 3.8+, standard library only."""
import sys, time

START = (20, 50)  # 8:50 PM: the scheduled run is 8:55 PM; the v4 forward test counts forecasts from 00:50 UTC
END_HOUR = 1      # 1:00 AM: Eastern markets start their Kalshi day at 05:00 UTC (1:00 AM at UTC-4)


def inside(hour, minute=0):
    """True from 20:50 to 23:59 and from 0:00 to 0:59 local time."""
    return (hour, minute) >= START or hour < END_HOUR


def main(now=None):
    t = time.localtime(time.time() if now is None else now)
    if inside(t.tm_hour, t.tm_min):
        return 0
    print("Scan skipped: this run started at %02d:%02d, outside the evening scan window (8:50 PM to 1:00 AM). "
          "The PC was probably off or asleep at 8:55 PM. Wait for the next 8:55 PM run; do not scan by hand "
          "outside 8:50 PM to 1:00 AM either: an early scan replaces the evening snapshot the gate uses." % (t.tm_hour, t.tm_min))
    return 3


if __name__ == "__main__":
    sys.exit(main())
