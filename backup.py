"""Back up paper.db (and live.db, the Kalshi account ledger, once it exists) into backups\\ and into a copy OUTSIDE this
folder. Reads them only; never deletes or overwrites.
python backup.py [label]  ->  backups\\paper_YYYYmmdd_HHMMSS_<label>.db (and live_...db) plus the same files off-folder.
Exit code 0 = all written; 1 = a paper.db backup failed; 3 = paper.db is backed up but live.db failed.
Off-folder default: %USERPROFILE%\\Documents\\tradebot_backups (override with TRADEBOT_OFFSITE_BACKUPS). Python 3.8+."""
import os, sys, sqlite3, time
from pathlib import Path
try: from config import DB
except Exception: DB="paper.db"
OFFSITE=os.getenv("TRADEBOT_OFFSITE_BACKUPS",os.path.join(os.path.expanduser("~"),"Documents","tradebot_backups"))
LIVE_DB=os.getenv("LIVE_DB",os.path.join(os.path.dirname(os.path.abspath(DB)),"live.db"))   # next to paper.db; run.bat runs from this folder, so this is live.py's ledger
def copy(path,prefix,label):
    name="%s_%s_%s.db"%(prefix,time.strftime("%Y%m%d_%H%M%S"),label); ok=0
    try: src=sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)   # consistent snapshot via SQLite's backup API
    except Exception as ex: print("BACKUP FAILED: cannot open %s: %s"%(path,ex)); return 0
    for d in ("backups",OFFSITE):
        try:
            os.makedirs(d,exist_ok=True); dst=os.path.join(d,name)
            if os.path.exists(dst): print("skipped, already exists:",dst); continue
            out=sqlite3.connect(dst); src.backup(out); out.close(); ok+=1; print("backed up ->",dst)
        except Exception as ex: print("BACKUP FAILED in %s: %s"%(d,ex))
    src.close(); return ok
def main():
    label="".join(ch for ch in (sys.argv[1] if len(sys.argv)>1 else "manual") if ch.isalnum() or ch in "-_") or "manual"
    if not os.path.exists(DB): sys.exit("No %s yet, so there is nothing to back up."%DB)
    ok=copy(DB,"paper",label)
    if ok<2: sys.exit("WARNING: only %d of 2 backups of paper.db were written."%ok)   # exit code 1: callers stop
    if os.path.exists(LIVE_DB) and copy(LIVE_DB,"live",label)<2:
        print("WARNING: the live.db (Kalshi ledger) backup failed; paper.db is backed up. Kalshi orders are skipped this time.")
        sys.exit(3)   # exit code 3: only live.db failed; run.bat still scans on paper but skips live.py mirror
if __name__=="__main__": main()
