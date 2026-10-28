"""The kill switch (core.kill_file, killswitch.py, check.py, the dashboard, run.bat, and every file that trades).
python test_kill.py WORK OUT
On Windows it also runs run.bat in a scratch copy of the code (Kalshi points at a closed local port and the Kalshi
account settings at an unknown exchange name, so nothing could trade even if the switch failed)."""
import os, sys, shutil, glob, subprocess, io, contextlib
WORK,OUT=sys.argv[1],sys.argv[2]; os.makedirs(OUT,exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"]=os.path.join(OUT,"paper.db")
sys.path.insert(0,WORK)
import core, killswitch
REAL_HERE=core.HERE
home=os.path.join(OUT,"home"); other=os.path.join(OUT,"elsewhere"); os.makedirs(home); os.makedirs(other)
core.HERE=home   # the "tradebot folder" for the in-process checks; the real one is never touched
def touch(*p): open(os.path.join(*p),"w").close()
def gone(*p): return not os.path.exists(os.path.join(*p))
def quiet(f,*a):
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        try: r=f(*a)
        except SystemExit as e: r=("exit",e.code)
    return r,buf.getvalue()
# 1. names: any case, any ending (Windows hides .txt); look-alikes do not count
os.chdir(home)
for name in ("KILL","kill","Kill.txt","KILL.txt.txt","kill.md"):
    touch(home,name); assert core.killed() and os.path.basename(core.kill_file())==name, name; os.remove(os.path.join(home,name))
for name in ("killswitch.py","killswitch.md","KILLED","notes_KILL.txt","KILL - Copy.txt"):
    touch(home,name); assert not core.killed(), name; os.remove(os.path.join(home,name))
os.makedirs(os.path.join(home,"KILL")); assert core.killed(); os.rmdir(os.path.join(home,"KILL"))   # a folder counts too
# 2. the tradebot folder counts wherever the bot is started from; the current folder counts too
os.chdir(other); touch(home,"KILL.txt"); assert core.kill_file()==os.path.join(home,"KILL.txt"); os.remove(os.path.join(home,"KILL.txt"))
touch(other,"kill"); assert core.kill_file()==os.path.join(other,"kill"); os.remove(os.path.join(other,"kill")); assert not core.killed()
# 3. an unreadable tradebot folder counts as ON (fail closed); an unreadable current folder is ignored
real_listdir=os.listdir
def broken(d):
    if os.path.abspath(d)==home: raise PermissionError("denied")
    return real_listdir(d)
os.listdir=broken; assert core.killed() and "could not be read" in core.kill_file(); os.listdir=real_listdir
# 4. killswitch.py: on / status / off (off removes only KILL or KILL.txt files in the tradebot folder)
r,out=quiet(killswitch.status); assert r==0 and "off" in out
r,out=quiet(killswitch.on); assert r==0 and os.path.isfile(os.path.join(home,"KILL")) and "ON" in out
r,out=quiet(killswitch.status); assert r==2 and "ON" in out
touch(home,"kill.txt"); touch(home,"killswitch.md"); touch(other,"Kill.docx")   # a hand-made second one; a look-alike; a user file elsewhere
r,out=quiet(killswitch.off,False); assert r==0 and not core.kill_names(home), out
assert os.path.exists(os.path.join(home,"killswitch.md")) and os.path.exists(os.path.join(other,"Kill.docx")), "off() deleted a file it does not own"
os.remove(os.path.join(other,"Kill.docx")); os.remove(os.path.join(home,"killswitch.md"))
touch(home,"KILL"); touch(home,"kill.md")   # kill.md halts, but off() leaves it for a person to delete
r,out=quiet(killswitch.off,False); assert r[0]=="exit" and "kill.md" in str(r[1]) and gone(home,"KILL") and core.killed(), r
os.remove(os.path.join(home,"kill.md"))
os.makedirs(os.path.join(home,"KILL")); r,out=quiet(killswitch.off,False); assert r[0]=="exit" and core.killed(); os.rmdir(os.path.join(home,"KILL"))
try: os.symlink(os.path.join(home,"missing"),os.path.join(home,"KILL")); link=True
except (OSError,NotImplementedError,AttributeError): link=False   # Windows needs a privilege for symlinks
if link: assert core.killed(); r,out=quiet(killswitch.off,False); assert r==0 and not core.killed(), out
touch(other,"KILL.txt"); r,out=quiet(killswitch.on); assert os.path.isfile(os.path.join(home,"KILL")), "on() must create the file in the tradebot folder"
os.remove(os.path.join(other,"KILL.txt"))
# off from a script is refused, and changes nothing (run against the real folder: it stops before reading anything)
r=subprocess.run([sys.executable,os.path.join(WORK,"killswitch.py"),"off"],stdin=subprocess.PIPE,capture_output=True,text=True,cwd=other)
assert r.returncode==1 and "only by you" in r.stderr, r.stdout+r.stderr
r,out=quiet(killswitch.off,False); assert r==0 and not core.killed()
# 5. every file that trades refuses while it is on
os.chdir(OUT); core.HERE=home; touch(home,"KILL.txt")
import strategy, shadow, kalshi, live
def boom(*a,**k): raise AssertionError("a halted scan must not read markets")
kalshi.markets=boom
c=core.db(); r,out=quiet(strategy.scan,c); r2,out2=quiet(shadow.scan,c)
assert "KILL" in out and "KILL" in out2 and c.execute("select count(*) from trades").fetchone()[0]==0, (out,out2)
assert live.lock_reason(None,"demo")=="KILL file present" and live.killed is core.killed
os.remove(os.path.join(home,"KILL.txt")); core.HERE=REAL_HERE
# 6. check.py says HALTED, so the backup scan does not make up a halted scan; the dashboard says halted (also its fallback copy of the rule)
touch(OUT,"KILL.txt")
r=subprocess.run([sys.executable,os.path.join(WORK,"check.py")],cwd=OUT,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=WORK))
assert r.returncode==0 and r.stdout.startswith("HALTED"), r.stdout+r.stderr
r=subprocess.run([sys.executable,os.path.join(WORK,"dashboard.py"),"--no-open"],cwd=OUT,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=WORK))
html=open(os.path.join(OUT,"dashboard.html"),encoding="utf-8").read()
assert "Bot halted (kill switch)" in html and "run unkill" in html, (r.stdout[-500:],r.stderr[-800:])
S2=os.path.join(OUT,"nocore"); os.makedirs(S2)
for f in ("dashboard.py","dashboard_assets.py","gate.py","account_view.py","config.py"): shutil.copy(os.path.join(WORK,f),S2)   # the dashboard's own files (assets split out and gate.py added 2026-10-23), no core.py
shutil.copy(os.path.join(OUT,"paper.db"),S2); touch(S2,"Kill.TXT")
r=subprocess.run([sys.executable,os.path.join(S2,"dashboard.py"),"--no-open"],cwd=S2,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH="",PAPER_DB=os.path.join(S2,"paper.db")))
page2=open(os.path.join(S2,"dashboard.html"),encoding="utf-8").read()
assert "Bot halted (kill switch)" in page2, r.stdout+r.stderr
assert "Gate rules unavailable" not in page2, "gate.py is standard library only: the gate must still be judged without core.py"
# A corrupt price file and missing page styles must not stop the page either (review of refactor stage 2, 2026-10-23)
with open(os.path.join(S2,"marks.jsonl"),"wb") as fh: fh.write(b'{"ts": 1, "marks": {}}\n\xff\xfe broken\n')
os.remove(os.path.join(S2,"dashboard_assets.py")); os.remove(os.path.join(S2,"dashboard.html"))
r=subprocess.run([sys.executable,os.path.join(S2,"dashboard.py"),"--no-open"],cwd=S2,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH="",PAPER_DB=os.path.join(S2,"paper.db")))
assert r.returncode==0 and "Bot halted (kill switch)" in open(os.path.join(S2,"dashboard.html"),encoding="utf-8").read(), r.stdout+r.stderr
assert "unstyled" in r.stdout and "live prices unreadable" in r.stdout, r.stdout
os.remove(os.path.join(OUT,"KILL.txt"))
# 7. run.bat itself (Windows only), in a scratch copy of the code. The PC's Python finds the tradebot folder through
#    tradebot.pth (its ._pth file ignores PYTHONPATH and the script's own folder), so a scratch copy may import the REAL
#    core.py. Then only commands that cannot write into the tradebot folder are run here: a test must never turn the real
#    switch on or off.
if os.name=="nt":
    S=os.path.join(OUT,"scratch"); os.makedirs(S)
    for f in glob.glob(os.path.join(WORK,"*.py"))+[os.path.join(WORK,"run.bat")]: shutil.copy(f,S)
    env=dict(os.environ,KALSHI_BASE="http://127.0.0.1:9/trade-api/v2",KALSHI_ENV="none",PAPER_DB=os.path.join(S,"paper.db"),PYTHONPATH="",
             TRADEBOT_OFFSITE_BACKUPS=os.path.join(OUT,"offsite"))
    def bat(*a):
        r=subprocess.run(["cmd","/c","run.bat"]+list(a),cwd=S,capture_output=True,text=True,env=env,timeout=300,stdin=subprocess.DEVNULL); return r.returncode,r.stdout+r.stderr
    py=os.path.join(os.environ.get("USERPROFILE",""),"Python313","python.exe")
    where=subprocess.run([py if os.path.exists(py) else sys.executable,"-c","import core; print(core.HERE)"],cwd=S,capture_output=True,text=True,env=env).stdout.strip()
    iso=os.path.normcase(where)==os.path.normcase(S)
    touch(S,"KILL.txt")   # found through the current folder whichever core.py is imported
    rc,out=bat("scan"); assert rc==0 and "KILL SWITCH ON" in out and gone(S,"paper.db"), out
    rc,out=bat("unkill"); assert rc!=0 and "only by you" in out and os.path.exists(os.path.join(S,"KILL.txt")), out   # refused before it reads anything
    rc,out=bat("kill","off"); assert rc==1 and "unkill" in out and os.path.exists(os.path.join(S,"KILL.txt")), out   # never runs Python
    if iso:
        rc,out=bat("kill","status"); assert rc==2 and "ON" in out, out
        os.remove(os.path.join(S,"KILL.txt"))
        rc,out=bat("kill"); assert rc==0 and os.path.isfile(os.path.join(S,"KILL")), out
        rc,out=bat("scan"); assert "KILL SWITCH ON" in out and gone(S,"paper.db"), out
        os.remove(os.path.join(S,"KILL"))
        shutil.copy(os.path.join(S,"core.py"),os.path.join(S,"core_ok.py"))
        open(os.path.join(S,"core.py"),"w").write("raise ImportError('broken on purpose')\n")
        rc,out=bat("scan"); assert rc==1 and "Could not check" in out, out   # cannot check: fail closed, and say so
        shutil.copy(os.path.join(S,"core_ok.py"),os.path.join(S,"core.py"))
    else: os.remove(os.path.join(S,"KILL.txt"))
    rc,out=bat("scan")   # switch off: the scan really starts (and fails at the closed Kalshi port, after creating paper.db)
    assert "KILL SWITCH ON" not in out and "Could not check" not in out and os.path.exists(os.path.join(S,"paper.db")), out
    print("run.bat checked" if iso else "run.bat checked partly (this Python imports the tradebot folder itself, so kill/unkill are not run from a test)")
else: print("run.bat not checked here (Windows only; run .\\run test on the PC)")
print("kill switch: all checks passed")
