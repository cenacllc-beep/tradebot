"""export.py: JSON export is complete, restore rebuilds identical tables, paper.db is never changed. python test_export.py WORK OUT"""
import os, sys, subprocess, sqlite3, hashlib, json, time
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"]=os.path.join(OUT,"offsite")
sys.path.insert(0,WORK)
import core
c=core.db()
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)",(time.time(),"KXRAIN-26OCT15-NYC","yes",0.3,0.45,3,0.9,0.02,"v3"))
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)",("KXRAIN-26OCT15-NYC","v3",time.time(),0.6,0.3,"rain")); c.commit(); c.close()
h=hashlib.sha256(open("paper.db","rb").read()).hexdigest()
env=dict(os.environ,PYTHONPATH=WORK)
r=subprocess.run([sys.executable,os.path.join(WORK,"export.py")],capture_output=True,text=True,env=env); print(r.stdout.strip()); assert r.returncode==0,r.stderr
assert hashlib.sha256(open("paper.db","rb").read()).hexdigest()==h, "paper.db changed"
d=json.load(open(os.path.join("backups","paper_latest.json"),encoding="utf-8")); assert {"trades","obs"}<=set(d["tables"])
r=subprocess.run([sys.executable,os.path.join(WORK,"export.py"),"restore",os.path.join("backups","paper_latest.json"),"copy.db"],capture_output=True,text=True,env=env); assert r.returncode==0,r.stderr
a,b=sqlite3.connect("paper.db"),sqlite3.connect("copy.db")
for t in d["tables"]: assert a.execute("select * from %s"%t).fetchall()==b.execute("select * from %s"%t).fetchall(), t
a.close(); b.close()
r=subprocess.run([sys.executable,os.path.join(WORK,"export.py"),"restore",os.path.join("backups","paper_latest.json"),"paper.db"],capture_output=True,text=True,env=env)
assert r.returncode!=0 and hashlib.sha256(open("paper.db","rb").read()).hexdigest()==h, "restore must refuse to overwrite"
print("export and restore: ok")
