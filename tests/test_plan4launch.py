"""research/plan4_launch.py: the hourly job starts a PLAN4 finishing chain from a flag file, once, detached, and never
while that chain is still running. No network, no real process started. python test_plan4launch.py WORK OUT"""
import os, sys, shutil, re
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, os.path.join(WORK, "research"))
import plan4_launch as L
R = os.path.join(OUT, "results"); os.makedirs(R)
calls = []
class P:
    pid = 4242
def popen(cmd, **kw): calls.append((cmd, kw)); return P()
def flag(c): open(os.path.join(R, "plan4_go_%s.txt" % c), "w").write("go\n")
def status(c, *lines): open(os.path.join(R, "plan4_status_%s.txt" % c), "w").write("".join(l + "\n" for l in lines))
# nothing to do without a flag
assert L.main(results=R, root=WORK, popen=popen) == [] and calls == []
# KS flagged and idle; PS flagged but its chain is mid-step: only KS starts, PS keeps its flag
flag("KS"); flag("PS"); status("PS", "2026-10-29T02:20:00 start pselect")
assert L.running("PS", R) and not L.running("KS", R)
assert L.main(results=R, root=WORK, popen=popen) == ["KS"]
assert calls[0][0] == [L.powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(WORK, "research", "plan4_run.ps1"), "KS"]
assert calls[0][1]["stdout"] is L.subprocess.DEVNULL and calls[0][1]["close_fds"] and calls[0][1]["cwd"] == WORK
assert not os.path.exists(os.path.join(R, "plan4_go_KS.txt")) and os.path.exists(os.path.join(R, "plan4_go_KS.started.txt"))
assert os.path.exists(os.path.join(R, "plan4_go_PS.txt"))
# PS's step ends: the next hourly run starts it; KS is not started twice even if flagged again
status("PS", "2026-10-29T02:20:00 start pselect", "2026-10-29T02:50:00 end pselect exit 0")
flag("KS"); calls.clear()
assert L.main(results=R, root=WORK, popen=popen) == ["PS"] and [c[0][-1] for c in calls] == ["PS"]
status("KS", "x start scoreK", "x end scoreK exit 0", "stopped")
assert not L.running("KS", R)
# a flag next to an earlier start is set aside (not started, logged once)
flag("KS"); calls.clear()
assert L.main(results=R, root=WORK, popen=popen) == [] and calls == []
assert not os.path.exists(os.path.join(R, "plan4_go_KS.txt")) and os.path.exists(os.path.join(R, "plan4_go_KS.ignored.txt"))
# only the two finishing chains can be started; a flag for anything else is ignored
open(os.path.join(R, "plan4_go_P.txt"), "w").write("go\n"); calls.clear()
assert L.main(results=R, root=WORK, popen=popen) == [] and calls == []
# on Windows: detached, no window, new process group; breakaway from the task's job when allowed, else without it
real = L.os.name; L.os.name = "nt"; got = []
def strict(cmd, **kw):
    assert kw["stdin"] is kw["stdout"] is kw["stderr"] is L.subprocess.DEVNULL and kw["close_fds"] and not kw.get("shell"), kw   # only DEVNULL is passed on
    got.append(kw["creationflags"])
    if kw["creationflags"] & L.CREATE_BREAKAWAY_FROM_JOB: raise OSError(5, "Access is denied")
    return P()
try:
    L.start(["x"], cwd=WORK, popen=strict)
    assert L.powershell().lower().endswith(os.path.join("system32", "windowspowershell", "v1.0", "powershell.exe")), L.powershell()
finally: L.os.name = real
base = L.CREATE_NEW_PROCESS_GROUP | L.CREATE_NO_WINDOW   # no DETACHED_PROCESS: it would cancel CREATE_NO_WINDOW
assert got == [base | L.CREATE_BREAKAWAY_FROM_JOB, base], got
# run.bat's hourly job runs the launcher before anything long, and nothing else starts PLAN4
bat = open(os.path.join(WORK, "run.bat"), encoding="utf-8").read()
code = re.sub(r"(?m)^rem .*$", "", bat); hourly = code[code.index(":hourly"):code.index("exit /b 0", code.index(":hourly"))]
assert hourly.index("research\\plan4_launch.py") < hourly.index("research\\lip.py sample"), hourly
assert "plan4.py" not in code and "plan4_run.ps1" not in code
# a started process does not hold its parent's output pipe: the reader sees the end at once (the hourly job's case)
import subprocess, time, textwrap
child = textwrap.dedent("""
    import sys; sys.path.insert(0, %r)
    import plan4_launch as L
    L.start([sys.executable, "-c", "import time; time.sleep(20)"], cwd=%r)
    print("launched")
""" % (os.path.join(WORK, "research"), OUT))
t0 = time.time(); r = subprocess.run([sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
assert b"launched" in r.stdout and time.time() - t0 < 5, (r.stdout, time.time() - t0)
# the runner can be started again after a failure: a step whose single result exists is skipped; each run has its own logs
ps = open(os.path.join(WORK, "research", "plan4_run.ps1"), encoding="utf-8").read()
assert '"pselect" = "research\\results\\plan4_selected.json"' in ps and '"scoreK" = "research\\results\\plan4_K.json"' in ps and "${stamp}" in ps
print("plan4 launcher: a flag starts its chain once, detached; a running chain is left alone; only KS and PS: ok")
