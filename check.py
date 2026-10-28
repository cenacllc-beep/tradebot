"""Did the evening scan log the next market day's markets? Read-only (opens paper.db with mode=ro).
python check.py  ->  prints SCANNED (exit 0), HALTED when the kill switch is on (exit 0: no scan is wanted), or
NOT SCANNED (exit 3). Used by the backup scheduled scan.
The next market day is today's UTC date before 05:00 UTC (when Eastern markets start their Kalshi day), else tomorrow's."""
import sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try: from config import DB
except Exception: DB="paper.db"
def main():
    try:
        from core import kill_file
        f=kill_file()
    except Exception: f=None
    if f: print("HALTED: the kill switch is on (%s), so no scan is wanted. Only you turn it off: .\\run unkill"%f); sys.exit(0)
    now=datetime.now(timezone.utc)
    day=now.date() if now.hour<5 else now.date()+timedelta(days=1)
    tag=day.strftime("%y%b%d").upper()   # ticker date, e.g. 26OCT15 (C locale month names, as in weather.py)
    if not Path(DB).exists(): print("NOT SCANNED: there is no %s"%DB); sys.exit(3)
    c=sqlite3.connect(Path(DB).resolve().as_uri()+"?mode=ro",uri=True)
    n=c.execute("select count(*) from obs where ticker like ?",("%-"+tag+"-%",)).fetchone()[0]; c.close()
    if n: print("SCANNED: %d markets logged for %s"%(n,day)); sys.exit(0)
    print("NOT SCANNED: no markets logged yet for %s"%day); sys.exit(3)
if __name__=="__main__": main()
