"""Clicks every control of the dashboard built from a fake 45-day ledger (needs Playwright; skipped without it). python test_ui.py WORK OUT"""
import os, sys, subprocess
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True)
try: import playwright  # noqa
except ImportError: print("SKIPPED: Playwright is not installed (optional; the other tests cover the logic)"); sys.exit(0)
HERE=os.path.dirname(os.path.abspath(__file__)); env=dict(os.environ,PAPER_DB=os.path.join(OUT,"paper.db"),TRADEBOT_OFFSITE_BACKUPS=os.path.join(OUT,"off"),PYTHONPATH=WORK)
r=subprocess.run([sys.executable,os.path.join(HERE,"fake_ledger.py"),WORK,OUT],capture_output=True,text=True,env=env); assert r.returncode==0,r.stderr
import sqlite3, json, time   # live prices (marks.jsonl) for the open trades, so the marked chart is clicked too
cn=sqlite3.connect(os.path.join(OUT,"paper.db")); ids=[r[0] for r in cn.execute("select id from trades where status='open'")]; cn.close()
with open(os.path.join(OUT,"marks.jsonl"),"w") as f:
    for k in range(6): f.write(json.dumps(dict(ts=time.time()-3600*(6-k),marks={"main:%d"%i:0.1*(k+1) for i in ids}))+"\n")
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],capture_output=True,text=True,env=env,cwd=OUT); assert r.returncode==0,r.stderr
assert ids and "at their Kalshi bid" in open(os.path.join(OUT,"dashboard.html"),encoding="utf-8").read(), "the fake ledger should have open trades with prices"
bad=0
for args in (["390","dark","touch"],["1100","light"]):
    r=subprocess.run([sys.executable,os.path.join(HERE,"ui_checks.py"),os.path.join(OUT,"dashboard.html")]+args,capture_output=True,text=True)
    last=r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]; print(" ".join(args),"->",last)
    if r.returncode or " 0 failed" not in last: bad+=1; print(r.stdout[-1500:])
sys.exit(1 if bad else 0)
