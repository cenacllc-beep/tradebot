"""Off-laptop backup helper (added 2026-10-14). Reads paper.db only (SQLite read-only mode); never changes or overwrites it.
  python export.py                        -> backups\\paper_latest.json (plus a dated copy): every table of paper.db as JSON
  python export.py restore FILE NEW.db    -> rebuilds a database from such a JSON file into NEW.db (refuses to overwrite)
The evening scan runs the export, and the scheduled scan task uploads backups\\paper_latest.json to the private phone
page's file storage, so a copy of the paper record lives off this laptop. Python 3.8+, no dependencies."""
import os, sys, json, sqlite3, time
from pathlib import Path
try: from config import DB
except Exception: DB="paper.db"
def export():
    if not os.path.exists(DB): sys.exit("No %s yet, so there is nothing to export."%DB)
    src=sqlite3.connect(Path(DB).resolve().as_uri()+"?mode=ro",uri=True); tables={}
    for name,sql in src.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
        cols=[r[1] for r in src.execute('pragma table_info("%s")'%name)]
        tables[name]=dict(sql=sql,columns=cols,rows=[list(r) for r in src.execute('select * from "%s"'%name)])
    src.close()
    data=dict(kind="tradebot paper.db export",note="Paper trading only. Restore with: python export.py restore FILE NEW.db",
              created=time.strftime("%Y-%m-%d %H:%M:%S"),tables=tables)
    os.makedirs("backups",exist_ok=True); stamp=time.strftime("%Y%m%d_%H%M%S")
    for p in (os.path.join("backups","paper_%s.json"%stamp),os.path.join("backups","paper_latest.json")):
        tmp=p+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,separators=(",",":"))
        os.replace(tmp,p)
    print("exported %d tables (%s rows) -> backups\\paper_latest.json"%(len(tables),sum(len(t["rows"]) for t in tables.values())))
def restore(src,out):
    if os.path.exists(out): sys.exit("Refusing to overwrite %s. Pick a new file name."%out)
    d=json.load(open(src,encoding="utf-8"))
    if d.get("kind")!="tradebot paper.db export": sys.exit("%s is not a tradebot export."%src)
    c=sqlite3.connect(out)
    for name,t in d["tables"].items():
        c.execute(t["sql"])
        if t["rows"]:
            c.executemany('insert into "%s"(%s) values(%s)'%(name,",".join('"%s"'%x for x in t["columns"]),",".join("?"*len(t["columns"]))),t["rows"])
    c.commit(); c.close(); print("restored %d tables into %s"%(len(d["tables"]),out))
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="restore":
        if len(sys.argv)!=4: sys.exit(__doc__)
        restore(sys.argv[2],sys.argv[3])
    else: export()
