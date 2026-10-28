"""The scheduled runs (tasks\\*.cmd, tasks\\install_schedules.*) and the evening scan window (scan_window.py).
Windows' cmd.exe and Task Scheduler cannot run here, so the batch and PowerShell files are checked by structure: the
fixes from the 2026-10-23 outage review must stay in place. python test_schedule.py WORK OUT"""
import os, sys, re, time, shutil, subprocess
WORK, OUT = sys.argv[1], sys.argv[2]
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, WORK)
import scan_window as W

# ---- the evening scan window: 8:50 PM to 0:59 AM, this PC's local time ----
assert [h for h in range(24) if W.inside(h, 59)] == [0, 20, 21, 22, 23] and not W.inside(20, 49) and W.inside(20, 50)
for h, m, want in ((20, 55, 0), (20, 50, 0), (20, 49, 3), (0, 59, 0), (1, 0, 3), (9, 0, 3), (19, 0, 3), (18, 0, 3), (23, 59, 0)):
    t = time.mktime((2026, 10, 24, h, m, 0, 0, 0, -1))
    assert W.main(t) == want, (h, m, want)
r = subprocess.run([sys.executable, os.path.join(WORK, "scan_window.py")], capture_output=True, text=True)
lt = time.localtime(); assert r.returncode in (0, 3), r   # the minute may tick over between the two readings
assert r.returncode == (0 if W.inside(lt.tm_hour, lt.tm_min) else 3) or lt.tm_sec >= 58, r
assert r.returncode == 0 or r.stdout.startswith("Scan skipped"), r.stdout


def read(rel):
    b = open(os.path.join(WORK, rel), "rb").read()
    assert b.count(b"\r\n") == b.count(b"\n"), rel + ": Windows batch and PowerShell files keep CRLF line endings"
    assert all(x < 128 for x in b), rel + ": ASCII only (the console code page is not UTF-8)"
    return b.decode("ascii").split("\r\n")


# ---- the three task files: no redirect (jobs.py writes the log a line at a time), one call, its exit code ----
for job in ("evening", "settle", "hourly"):
    L = read("tasks/%s.cmd" % job)
    code_lines = [ln for ln in L if ln and not ln.startswith("rem ")]
    assert code_lines == ["@echo off", 'cd /d "%~dp0.."', 'set "PY=%USERPROFILE%\\Python313\\python.exe"',
                          'if not exist "%PY%" goto nopython', '"%%PY%%" jobs.py %s' % job, "exit /b %errorlevel%", ":nopython",
                          "if not exist logs mkdir logs",
                          "echo ===== no-time %s >> logs\\tasks.log" % job,
                          "echo %s could not start: Python not found at %%PY%% >> logs\\tasks.log" % job,
                          "echo ===== no-time %s done (exit 9009) >> logs\\tasks.log" % job,
                          "exit /b 9009"], (job, code_lines)
    # freshness reads the two marker lines as a finished run with exit 9009 (review 2026-10-24)
    import freshness as FR0
    fake_log = os.path.join(OUT, "nopython_%s.log" % job)
    with open(fake_log, "wb") as f:   # what cmd's `echo text >> file` writes: the text, the space before >>, CRLF
        for ln in code_lines:
            if ln.startswith("echo ") and ln.endswith(" >> logs\\tasks.log"):
                f.write((ln[5:-len(">> logs\\tasks.log")].replace("%PY%", "C:\\x\\python.exe") + "\r\n").encode("ascii"))
    R0 = FR0.task_runs(fake_log)[job]
    assert R0["finished"] and R0["exit"] == 9009 and R0["notime"], (job, R0)

# ---- jobs.py: network wait, scan window, retries, lock, log, settings (fakes; no network, no Windows) ----
import jobs as JB
JB.LOG = os.path.join(OUT, "logs", "tasks.log")
class Clock:
    def __init__(self, t=0.0): self.t = t
    def __call__(self): return self.t
    def sleep(self, s): self.t += s
ck = Clock()
ups = iter([False, False, False, True])
assert JB.wait_for_network(lambda s: s < 3600, poll=30, sleep=ck.sleep, clock=ck, probe=lambda: next(ups)) and ck.t == 90
ck = Clock()
assert not JB.wait_for_network(lambda s: s < 100, poll=30, sleep=ck.sleep, clock=ck, probe=lambda: False) and ck.t == 120
assert JB.wait_for_network(lambda s: False, probe=lambda: True)   # online: no wait at all
log = open(JB.LOG, encoding="utf-8").read()
assert "WAITING FOR NETWORK since" in log and "network: back after 1 min" in log and "giving up for this run" in log, log
os.environ["https_proxy"] = "http://127.0.0.1:9"   # a system proxy: the socket check is skipped, requests uses the proxy
assert JB.proxied() and JB.wait_for_network(lambda s: False)
del os.environ["https_proxy"]

def evening_run(results, window_seq, net_ok=True, left=3600):
    calls, slept, kws = [], [], []
    res = iter(results); win = iter(window_seq)
    def run(args, **kw): calls.append(args[1]); kws.append(kw); return next(res)
    rc = JB.evening(run=run, net=lambda keep: net_ok, window=lambda: next(win), left=lambda: left, sleep=slept.append)
    return rc, calls, slept, kws
assert evening_run([0, 0], [True] * 6)[:3] == (0, ["settle", "scan"], [])               # on time
assert evening_run([0], [False] * 3)[:3] == (0, ["settle"], [])                         # a make-up run in the morning
assert evening_run([0, 1, 1, 0], [True] * 12)[:3] == (0, ["settle", "scan", "scan", "scan"], [300, 300])
assert evening_run([0, 1, 1, 1], [True] * 12)[:3] == (1, ["settle", "scan", "scan", "scan"], [300, 300])
assert evening_run([0, 1], [True, True, False])[:3] == (1, ["settle", "scan"], [300])   # window closes during the retries
assert evening_run([0, JB.WINDOW_CLOSED], [True] * 6)[:3] == (1, ["settle", "scan"], [])  # closed while waiting for the lock: no retry
assert evening_run([0, 3, 0], [True] * 9)[:3] == (0, ["settle", "scan", "scan"], [300])  # run.bat's own exit 3 is an ordinary failure
assert JB.WINDOW_CLOSED not in (0, 1, 2, 3, 75, 9009)
rc, calls, _, _ = evening_run([0], [True, True, True], net_ok=False)
assert rc == 1 and calls == ["settle"]                                                   # no network before 1 AM
assert evening_run([1, 0], [True] * 6)[0] == 1                                           # a failed settle is kept
_, _, _, kws = evening_run([0, 0], [True] * 6, left=600)
assert kws[1]["wait"] == 600 and kws[1]["guard"] is not None, kws                       # the scan never waits for the lock past 1 AM
seen = []
assert JB.settle(run=lambda a, **k: seen.append(a[1]) or 0, net=lambda k: True) == 0 and seen == ["settle", "report"]
order = []
def hr(a, **k): order.append((a[1], k.get("busy_ok"))); return 0
assert JB.hourly(run=hr, net=lambda k: order.append("net") or True, settings=lambda: order.append("settings")) == 0
assert order == ["settings", "net", ("hourly", True)]
# seconds left in the window: 1:00 AM tomorrow from the evening, 1:00 AM today after midnight, 0 outside
for (h, m), want in (((22, 0), 3 * 3600), ((0, 30), 30 * 60), ((12, 0), 0), ((20, 49), 0), ((20, 50), 4 * 3600 + 10 * 60)):
    t = time.mktime((2026, 10, 24, h, m, 0, 0, 0, -1))
    assert JB.seconds_left(lambda: t) == want, (h, m, JB.seconds_left(lambda: t), want)
# step(): the window is asked again once the lock is held (review 2026-10-24: a scan could otherwise start after 1 AM)
import joblock
joblock.LOCK = os.path.join(OUT, "logs", "job.lock"); joblock.OWNER = os.path.join(OUT, "logs", "job.owner")
held = []
def guard_sees_lock():   # proves the order: by the time the window is asked, this step holds the lock
    other = joblock.acquire(wait=0)
    held.append(other is None)
    if other is not None:
        joblock.release(other)
    return False
assert JB.step([sys.executable, "-c", "print('ran')"], wait=5, guard=guard_sees_lock) == JB.WINDOW_CLOSED and held == [True], held
r = JB.step([sys.executable, "-c", "import sys; print('step output line'); sys.exit(4)"], wait=5)
assert r == 4 and "step output line" in open(JB.LOG, encoding="utf-8", errors="replace").read()
holder = joblock.acquire(wait=1)
assert JB.step([sys.executable, "-c", "print('x')"], wait=1) == joblock.BUSY
assert JB.step([sys.executable, "-c", "print('x')"], wait=1, busy_ok=True) == 0
assert "JOB LOCK:" in open(JB.LOG, encoding="utf-8").read()
joblock.release(holder)
# main(): start and done lines in the log, also when a job crashes; freshness reads them
def crash(): raise ValueError("boom")
JB.JOBS["crash"] = crash
assert JB.main(["crash"]) == 1
txt = open(JB.LOG, encoding="utf-8").read()
assert "jobs.py crash failed" in txt and "ValueError: boom" in txt and re.search(r"===== \S+ crash done \(exit 1\)", txt)
import freshness as FR
JB.JOBS["evening"] = lambda: 0
t_before = time.time()
assert JB.main(["evening"]) == 0
assert abs(JB._deadline[0] - (t_before + 5.5 * 3600)) < 60, "main() sets the job's wait budget"
JB._deadline[0] = None
R = FR.task_runs(JB.LOG)
assert R["evening"]["finished"] and R["evening"]["exit"] == 0 and R["evening"]["done"] and not R["evening"]["notime"], R
# settings: only on Windows, once; success remembered, failure retried, never raises
applied = os.path.join(OUT, "logs", "schedules_applied.txt")
if os.name != "nt":
    assert JB.apply_settings(applied=applied) is None and not os.path.exists(applied)
    JB.os = type("o", (), {"name": "nt", "path": os.path, "makedirs": os.makedirs})   # pretend, to test the logic
fake = lambda rc: (lambda *a, **k: type("R", (), {"returncode": rc, "stdout": "OK      Evening scan\n", "stderr": ""})())
assert JB.apply_settings(applied=applied, runner=fake(2)) is False and not os.path.exists(applied)
assert JB.apply_settings(applied=applied, runner=fake(0)) is True and os.path.exists(applied)
assert JB.apply_settings(applied=applied, runner=fake(0)) is None, "applied once"
assert open(applied, encoding="utf-8").readline().strip() == JB._ps1_hash(os.path.join(WORK, "tasks", "install_schedules.ps1"))
ps1_copy = os.path.join(OUT, "install_schedules_v2.ps1")
with open(ps1_copy, "w", encoding="ascii") as f:
    f.write("# a changed script\r\n")
assert JB.apply_settings(applied=applied, ps1=ps1_copy, runner=fake(0)) is True, "a changed script is applied again"
assert JB.apply_settings(applied=applied, ps1=ps1_copy, runner=fake(0)) is None
with open(applied, "w", encoding="utf-8") as f:
    f.write("2026-10-24 04:20:11\nOK      Evening scan\n")   # an r58 marker (no hash): applied again
assert JB.apply_settings(applied=applied, runner=fake(0)) is True
os.remove(applied)
def boom(*a, **k): raise OSError("powershell not found")
assert JB.apply_settings(applied=applied, runner=boom) is False
JB.os = os
assert JB.main(["nonsense"]) == 2
# stay awake (2026-10-25): Windows only; a step (capped at an hour), the first minutes of the evening job and the pause
# between scan tries; always released, capped by a helper thread, never fails the job
ON, OFF = JB.ES_CONTINUOUS | JB.ES_SYSTEM_REQUIRED, JB.ES_CONTINUOUS
calls = []
rec = lambda f: calls.append((f, time.time())) or 1
assert JB.stay_awake(True, setter=rec) is (os.name == "nt")
nt = type("o", (), {"name": "nt", "path": os.path, "makedirs": os.makedirs, "environ": os.environ})
JB.os = nt
calls.clear()
assert JB.stay_awake(True, setter=rec) and JB.stay_awake(False, setter=rec) and [c[0] for c in calls] == [ON, OFF], calls
assert JB.stay_awake(True, setter=lambda f: 0) is False, "Windows refused: reported as False"
def broken(flags): raise OSError("no kernel32")
assert JB.stay_awake(True, setter=broken) is False
calls.clear()
with JB.awake(0.2, setter=rec):
    time.sleep(0.7)
    assert [c[0] for c in calls] == [ON, OFF], ("dropped at the cap, before the block ends", calls)
calls.clear(); t_end = None
with JB.awake(30, setter=rec):
    time.sleep(0.1); t_end = time.time()
assert [c[0] for c in calls] == [ON, OFF] and calls[1][1] - t_end < 2, ("dropped when the block ends", calls)
calls.clear()
try:
    with JB.awake(30, setter=rec):
        raise KeyError("step failed")
except KeyError:
    pass
assert [c[0] for c in calls] == [ON, OFF], ("dropped when the block raises", calls)
with JB.awake(30, setter=broken):
    pass
calls.clear()
with JB.awake(30, setter=lambda f: calls.append(f) or 0):   # refused: nothing to undo
    pass
assert calls == [ON], calls
JB.os = os
calls.clear()
with JB.awake(30, setter=rec):
    pass
assert calls == [], "nothing off Windows"
used = []
class FakeAwake:
    def __init__(self, cap, setter=None): self.cap = cap
    def __enter__(self): used.append(("in", self.cap)); return self
    def __exit__(self, *e): used.append(("out", self.cap)); return False
real_awake = JB.awake
JB.awake = FakeAwake
assert JB.step([sys.executable, "-c", "import sys; sys.exit(5)"], wait=5) == 5 and used == [("in", 3600), ("out", 3600)], used
used.clear()
assert JB.step([sys.executable, "-c", "print(1)"], wait=5, guard=lambda: False) == JB.WINDOW_CLOSED and used == [], "nothing when no step runs"
real_popen = JB.subprocess.Popen
def popen_fails(*a, **k): raise OSError("cannot start")
JB.subprocess.Popen = popen_fails
try:
    JB.step([sys.executable, "-c", "print(1)"], wait=5)
    raise AssertionError("expected OSError")
except OSError:
    pass
finally:
    JB.subprocess.Popen = real_popen
assert used == [("in", 3600), ("out", 3600)], ("released even when the step cannot start", used)
JB.awake = real_awake
used.clear()
res = iter([0, 1, 1, 0])
rc = JB.evening(run=lambda a, **k: used.append(a[1]) or next(res), net=lambda keep: used.append("net") or True,
                window=lambda: True, left=lambda: 3600, sleep=lambda s: used.append(("sleep", s)), keep=FakeAwake)
E = JB.EVENING_AWAKE_S
assert rc == 0 and used == [("in", E), "net", ("out", E), "settle", "net", "scan", ("in", E), ("sleep", 300), ("out", E),
                            "net", "scan", ("in", E), ("sleep", 300), ("out", E), "net", "scan"], used
assert JB.STEP_AWAKE_S <= 3600 and JB.RETRY_PAUSE_S < E <= 10 * 60
import inspect
for fn in (JB.settle, JB.hourly, JB.wait_for_network):
    body = inspect.getsource(fn)
    assert "awake(" not in body and "keep(" not in body, (fn.__name__, "never keeps the PC awake")
# the job's time budget: waits stop before the task's Task Scheduler limit (review 2026-10-24)
assert JB.BUDGET_S["evening"] < 6 * 3600 and JB.BUDGET_S["settle"] < 3 * 3600 and JB.BUDGET_S["hourly"] < 2 * 3600
JB._deadline[0] = time.time() - 1   # budget spent
ck = Clock()
assert not JB.wait_for_network(lambda s: True, poll=30, sleep=ck.sleep, clock=ck, probe=lambda: False) and ck.t == 0
holder = joblock.acquire(wait=1)
t0 = time.time()
assert JB.step([sys.executable, "-c", "print('x')"], wait=60) == joblock.BUSY and time.time() - t0 < 10, "no lock wait past the budget"
joblock.release(holder)
JB._deadline[0] = None

# ---- install_schedules.cmd: create, check each create, then the settings script, then say plainly what happened ----
ins = read("tasks/install_schedules.cmd")
creates = [i for i, ln in enumerate(ins) if ln.startswith("schtasks /Create /F /TN \"Tradebot\\")]
assert len(creates) == 3 and all(ins[i + 1] == 'if errorlevel 1 set "FAIL=1"' for i in creates)
assert all(re.search(r'/TR "\\"%D%(evening|settle|hourly)\.cmd\\""$', ins[i]) for i in creates), "the task's path is quoted (spaces)"
assert ins.index('if "%FAIL%"=="1" goto createfailed') > creates[-1]
ps = [i for i, ln in enumerate(ins) if "install_schedules.ps1" in ln and ln.startswith("powershell ")]
assert len(ps) == 1 and "-ExecutionPolicy Bypass -File" in ins[ps[0]] and ins[ps[0] + 1] == 'set "PSRC=%errorlevel%"'
assert ins.count("pause") == 2 and ":createfailed" in ins and ":allok" in ins
# re-running the installer resets the tasks, so it forgets the settings marker first (the hourly job then re-applies)
dl = ins.index('del "%D%..\\logs\\schedules_applied.txt" 2>nul')
assert dl < creates[0], "the marker is forgotten before the tasks are re-created"
assert any("/ST 20:55" in ln and "evening.cmd" in ln for ln in ins) and any("/ST 14:51" in ln for ln in ins) and any("/SC HOURLY /ST 00:20" in ln for ln in ins)

# ---- install_schedules.ps1: only these settings, only these three tasks; nothing that needs a password or wakes the PC ----
p1 = "\n".join(read("tasks/install_schedules.ps1"))
code = "\n".join(ln for ln in p1.split("\n") if not ln.lstrip().startswith("#"))
for k in ("$t.Settings.DisallowStartIfOnBatteries = $false", "$t.Settings.StopIfGoingOnBatteries = $false",
          "$t.Settings.StartWhenAvailable = $true", "$t.Settings.ExecutionTimeLimit = 'PT{0}H' -f $j.Hours",
          "Set-ScheduledTask -InputObject $t", "exit $failed"):
    assert k in code, k
assert "New-ScheduledTaskSettingsSet" not in code and "Enabled" not in code.split("Write-Output")[0], "settings are changed in place: Enabled and the rest are kept"
assert "Name = 'Evening scan';     Hours = 6" in code and "Name = 'Afternoon settle'; Hours = 3" in code
assert "[System.Xml.XmlConvert]::ToTimeSpan($s.ExecutionTimeLimit) -ne [TimeSpan]::FromHours($j.Hours)" in code, "the time limit is read back too, as a duration"
# each job's waits end before its task's time limit (jobs.BUDGET_S), and freshness waits longer than the limit
hours = dict(re.findall(r"Name = '([^']+)';\s+Hours = (\d+)", code))
import freshness as FR1
for task, job in (("Evening scan", "evening"), ("Afternoon settle", "settle"), ("Hourly research", "hourly")):
    lim = int(hours[task]) * 3600
    assert JB.BUDGET_S[job] <= lim - 1800, (job, JB.BUDGET_S[job], lim)
    assert FR1.LIMITS.get("task_running_" + job, FR1.LIMITS["task_running"]) > lim, (job, "freshness would call a running job stuck")
for k in ("-WakeToRun", "Register-ScheduledTask", "Unregister-ScheduledTask", "-Password", "-User ", "-RunLevel", "-Action", "-Trigger",
          "Set-ExecutionPolicy", "New-ScheduledTaskSettingsSet"):
    assert k not in code, k
# wake (2026-10-25): only the 8:55 PM scan wakes the PC; read back; the power plan is only read (powercfg /q), never changed
wake = dict(re.findall(r"Name = '([^']+)';\s+Hours = \d+; Wake = \$(true|false)", code))
assert wake == {"Evening scan": "true", "Afternoon settle": "false", "Hourly research": "false"}, wake
assert "$t.Settings.WakeToRun = [bool]$j.Wake" in code and "[bool]$s.WakeToRun -ne [bool]$j.Wake" in code
opts = re.findall(r"\(powercfg\s+(/\w+)\s", code, re.I)
assert set(opts) == {"/a", "/q", "/qh"} and len(opts) == 5 and code.lower().count("powercfg") == len(opts) + 1, ("powercfg only queries", opts)
# network connectivity in standby (2026-10-28 audit): read with this PC's own value names, by GUID, in any language
assert "Show-PowerSetting 'SUB_NONE' 'CONNECTIVITYINSTANDBY' 'f15576e8-98b7-4186-b944-eafa664402d9'" in code
rx_idx = re.search(r"\[regex\]::Match\(\$lines\[\$k\], '([^']+)'\)", code).group(1)
rx_val = re.search(r"\[regex\]::Matches\(\$t\.Substring\(\$i\), '([^']+)'\)", code).group(1)
def standby_values(text, sguid="f15576e8-98b7-4186-b944-eafa664402d9"):
    i = text.lower().find(sguid)
    if i < 0:
        return None
    lines = text[i:].split("\n"); names = {}
    for k in range(len(lines) - 1):
        mi = re.search(rx_idx, lines[k])
        if mi:
            names[int(mi.group(1))] = lines[k + 1].split(":", 1)[-1].strip()
    m = re.findall(rx_val, text[i:])
    a, d = int(m[-2], 16), int(m[-1], 16)
    return names.get(a, "value"), a, names.get(d, "value"), d
CS = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  Subgroup GUID: fea3413e-7e05-4911-9a71-700331f1c294  (Settings belonging to no subgroup)
    Power Setting GUID: f15576e8-98b7-4186-b944-eafa664402d9  (Networking connectivity in Standby)
      Possible Setting Index: 000
      Possible Setting Friendly Name: Disable
      Possible Setting Index: 001
      Possible Setting Friendly Name: Enable
      Possible Setting Index: 002
      Possible Setting Friendly Name: Managed by Windows
    Current AC Power Setting Index: 0x00000001
    Current DC Power Setting Index: 0x00000000
"""
assert standby_values(CS) == ("Enable", 1, "Disable", 0), standby_values(CS)
assert standby_values(CS.replace("Disable", "Deshabilitar").replace("Possible Setting Index", "Indice posible")) == ("Enable", 1, "Deshabilitar", 0)
assert standby_values("not there") is None
# the wake-timer values are found by the setting's GUID and the last two 0x values after it, in any language
rx = re.search(r"\[regex\]::Matches\(\$q\.Substring\(\$i\), '([^']+)'\)", code).group(1)
guid = re.search(r"\$guid = '([0-9a-f-]+)'", code).group(1)
assert guid == "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
def wake_values(text):
    i = text.lower().find(guid)
    if i < 0:
        return None
    m = re.findall(rx, text[i:])
    return (int(m[-2], 16), int(m[-1], 16)) if len(m) >= 2 else "unreadable"
EN = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (Allow wake timers)
      GUID Alias: RTCWAKE
      Possible Setting Index: 000
      Possible Setting Friendly Name: Disable
      Possible Setting Index: 001
      Possible Setting Friendly Name: Enable
      Possible Setting Index: 002
      Possible Setting Friendly Name: Important Wake Timers Only
    Current AC Power Setting Index: 0x00000001
    Current DC Power Setting Index: 0x00000000
"""
ES = """GUID del plan de energia: 381b4222-f694-41f0-9685-ff5bb260df2e  (Equilibrado)
  GUID del subgrupo: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Suspender)
    GUID de configuracion de energia: BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D  (Permitir temporizadores de reactivacion)
      Indice de configuracion posible: 000
      Nombre descriptivo de configuracion posible: Deshabilitar
    Indice de configuracion de corriente alterna actual: 0x00000002
    Indice de configuracion de corriente continua actual: 0x00000001
"""
assert wake_values(EN) == (1, 0) and wake_values(ES) == (2, 1), (wake_values(EN), wake_values(ES))
assert wake_values("The power scheme, subgroup or setting specified does not exist.") is None
assert wake_values(EN.split("Current AC")[0]) == "unreadable"
assert "$names.ContainsKey($a)" in code and "$names.ContainsKey($d)" in code
assert "On battery" in code and "in a bag" in code, "the battery wake and its risk are stated"
for k in ("/change", "/set", "-set", "/s ", "/import", "/x ", "/h ", "/hibernate", "/requestsoverride", "/duplicatescheme", "/delete"):
    assert k not in code.lower(), k
info = code[code.index("powercfg /q"):]
assert info.count("Write-Output ('INFO") + info.count("Write-Output 'INFO") >= 3 and "$failed++" not in info, "the wake report never fails the script"
assert sorted(re.findall(r"Name = '([^']+)'", code)) == ["Afternoon settle", "Evening scan", "Hourly research"]
# ---- joblock.py: steps from two jobs take turns; a crashed holder leaves no stale lock; exit codes pass through ----
import joblock as J
lock = os.path.join(OUT, "logs", "job.lock")
J.OWNER = os.path.join(OUT, "logs", "job.owner")
holder = subprocess.Popen([sys.executable, "-c", "import sys,time; sys.path.insert(0,%r); import joblock as J; fh=J.acquire(%r, wait=5); "
                           "print('held' if fh else 'none', flush=True); time.sleep(4)" % (WORK, lock)], stdout=subprocess.PIPE, text=True)
assert holder.stdout.readline().strip() == "held"
t0 = time.monotonic(); assert J.acquire(lock, wait=1, poll=0.2) is None and time.monotonic() - t0 >= 0.9, "a held lock makes the other job wait"
t0 = time.monotonic(); fh = J.acquire(lock, wait=10, poll=0.2); waited = time.monotonic() - t0
assert fh is not None and 1 <= waited <= 6, waited; J.release(fh); holder.wait()
killed = subprocess.Popen([sys.executable, "-c", "import sys,time; sys.path.insert(0,%r); import joblock as J; fh=J.acquire(%r, wait=5); "
                           "print('held', flush=True); time.sleep(60)" % (WORK, lock)], stdout=subprocess.PIPE, text=True)
assert killed.stdout.readline().strip() == "held"; killed.kill(); killed.wait()
fh = J.acquire(lock, wait=3, poll=0.2); assert fh is not None, "a killed job's lock is released by the system"; J.release(fh)
J.LOCK = lock
assert J.main([sys.executable, "-c", "import sys; print('step ran'); sys.exit(7)"], wait=5) == 7
fh = J.acquire(lock, wait=1)
no_owner = os.path.join(OUT, "logs", "no_owner_file")   # not the real logs\\job.owner, which exists on the PC after a run
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,%r); import joblock as J; J.LOCK=%r; J.OWNER=%r; sys.exit(J.main(['echo','x'], wait=1))" % (WORK, lock, no_owner)],
                   capture_output=True, text=True)
J.release(fh)
assert r.returncode == J.BUSY and r.stdout.startswith("JOB LOCK:") and "holder unknown" in r.stdout, (r.returncode, r.stdout)
J.main([sys.executable, "-c", "pass"], wait=5)   # the last holder is named next time the lock is busy
assert "process" in open(J.OWNER, encoding="utf-8").read()
fh = J.acquire(lock, wait=1)
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,%r); import joblock as J; J.LOCK=%r; J.OWNER=%r; sys.exit(J.main(['echo','x'], wait=1))" % (WORK, lock, J.OWNER)],
                   capture_output=True, text=True)
J.release(fh)
assert r.returncode == J.BUSY and "since" in r.stdout and sys.executable in r.stdout, r.stdout
cmdline = J.command(["run.bat", "settle"])
if os.name == "nt":   # the system's cmd.exe (ComSpec), never a cmd file in the current folder
    assert cmdline[0].lower().endswith("cmd.exe") and cmdline[1:] == ["/c", "run.bat", "settle"], cmdline
else:
    assert cmdline == ["run.bat", "settle"], cmdline
assert J.main([]) == 2
print("schedules and scan window: all checks passed")
