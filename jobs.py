"""The three scheduled jobs, step by step (added 2026-10-24 after the Oct 23 evening run failed). Places no orders itself.

tasks\\evening.cmd, settle.cmd and hourly.cmd only call this file:

  python jobs.py evening | settle | hourly      -> exit code: 0, or the last failing step's

It writes the job's start and done lines in logs\\tasks.log itself, and appends every step's output there line by line.
The file is never held open for long. Before, cmd's `>> logs\\tasks.log` kept it locked against other writers for the
whole run, and a job that waits for hours would have stopped every other job from starting (review 2026-10-24).

Why it exists (logs\\tasks.log, Oct 23-24): the 8:55 PM job started on time, but the laptop was in standby with its
network off. The settle needed no network, and the scan failed two seconds later on "getaddrinfo failed" for
api.elections.kalshi.com. Nothing retried it, so the market day was lost. So each job now:
- **Waits for Kalshi to be reachable.**
  - The evening job waits as long as the scan window is open (8:50 PM to 1:00 AM, scan_window.py), so waking the
    laptop at 11 PM still gets that night's scan with no click.
  - The settle waits up to an hour, the hourly job up to 10 minutes.
  - When Windows has a proxy set, the check is skipped: requests uses the proxy, a plain socket would not.
- **Retries a failed scan:** up to 3 times, 5 minutes apart, inside the window only. A retried scan is safe:
  - obs keeps each market's first snapshot;
  - a ticker already held is never bought again (ALREADY_HELD);
  - every attempt backs up first.
- **Takes turns** with the other jobs through joblock.py. A scan checks the window again once it holds the lock, and
  never waits for the lock past 1:00 AM, so it cannot start after the window closes while another job runs.
- **Applies the Task Scheduler settings by itself** (hourly job, Windows only; once per version of the script, and again
  after install_schedules.cmd runs): tasks\\install_schedules.ps1 lets the jobs start on battery and makes up runs
  missed while the PC was off. It changes those settings in place and keeps everything else, including whether you
  disabled a task.
- **Keeps the PC awake while it works** (Windows only, since 2026-10-25): during a step (at most an hour), and for a few
  minutes after the 8:55 PM start and between scan tries, so a laptop woken by the 8:55 PM timer (install_schedules.ps1)
  does not fall asleep again before Wi-Fi is back. Never during a long network wait.
- **Stops waiting before Windows' time limit** for the task (BUDGET_S: evening 5.5 of 6 hours, settle 2.5 of 3,
  hourly 1.5 of 2). A step whose lock is still busy then does not run, and the log says so.

The steps themselves are unchanged: run.bat settle, scan, report and hourly. Nothing here changes a threshold, the
model, the gate, the kill switch or live.py's locks. Python 3.8+, standard library only."""
import os, sys, time, socket, subprocess, threading, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import joblock, scan_window

LOG = os.path.join(HERE, "logs", "tasks.log")
APPLIED = os.path.join(HERE, "logs", "schedules_applied.txt")
KALSHI = "api.elections.kalshi.com"   # the scan cannot do anything without it; NWS is checked by the scan itself
POLL_S = 30
SCAN_TRIES = 3
RETRY_PAUSE_S = 5 * 60
SETTLE_NET_WAIT_S = 60 * 60
HOURLY_NET_WAIT_S = 10 * 60
HOURLY_LOCK_WAIT_S = 10 * 60          # if a settle or scan is running, the research can skip an hour
WINDOW_CLOSED = 103                   # internal: the window closed while a scan waited for the lock (run.bat can exit 3: backup.py)
BUDGET_S = dict(evening=5.5 * 3600, settle=2.5 * 3600, hourly=1.5 * 3600)   # under each task's limit (6, 3, 2 hours)
_deadline = [None]                    # wall-clock end of this job's waits, set by main()


def remaining():
    """Seconds this job may still spend waiting (network or lock) before its Task Scheduler limit; large when unset."""
    return 10 ** 9 if _deadline[0] is None else max(0, _deadline[0] - time.time())


# ---------- the log: appended a line at a time, never held open ----------
def log_bytes(data, path=None):
    path = path or LOG
    for k in range(5):   # another job may be appending at this moment: try again briefly
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "ab") as f:
                f.write(data)
            return True
        except OSError:
            time.sleep(0.2 * (k + 1))
    return False


def say(msg):
    """One line to the console and to logs\\tasks.log."""
    try:
        print(msg)
        sys.stdout.flush()
    except Exception:
        pass
    log_bytes((msg.rstrip("\n") + "\r\n").encode("utf-8", "replace"))


def stamp(ts=None):
    from tbcommon import clock
    return clock.iso(ts)   # with its UTC offset, as freshness.task_runs reads it


# ---------- network ----------
def proxied():
    """True when Windows (or the environment) sets an HTTPS proxy: a direct socket then says nothing about requests."""
    try:
        import urllib.request
        return bool(urllib.request.getproxies().get("https"))
    except Exception:
        return False


def reachable(host=KALSHI, port=443, timeout=5.0):
    """True when the name resolves and a TCP connection to port 443 opens (no data is sent)."""
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def wait_for_network(keep_waiting, poll=POLL_S, sleep=time.sleep, clock=time.time, probe=None):
    """Wait until Kalshi is reachable. keep_waiting(elapsed_s) -> False stops the wait. Returns True when online.
    Uses the wall clock: a laptop in standby is suspended, and the wait must count that time too."""
    if probe is None:
        if proxied():
            return True
        probe = reachable
    t0 = clock()
    if probe():
        return True
    say("WAITING FOR NETWORK since %s: %s is not reachable (the PC may be in standby with its network off)" % (
        time.strftime("%H:%M", time.localtime(t0)), KALSHI))
    while True:
        elapsed = clock() - t0
        if not keep_waiting(elapsed) or remaining() <= 0:
            say("network: still not reachable after %d min; giving up for this run" % (elapsed // 60))
            return False
        sleep(poll)
        if probe():
            say("network: back after %d min" % ((clock() - t0) // 60))
            return True


# ---------- one step: under the job lock, output into the log ----------
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _set_state(flags):
    import ctypes
    return ctypes.windll.kernel32.SetThreadExecutionState(flags)


def stay_awake(on, setter=None):
    """Windows only: SetThreadExecutionState for the calling thread (added 2026-10-25). A request, not a setting: it
    ends when reset, or when the thread or process ends. True when Windows accepted it. Never raises."""
    if os.name != "nt":
        return False
    try:
        return bool((setter or _set_state)(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)))
    except Exception:
        return False


STEP_AWAKE_S = 60 * 60       # a step keeps the PC awake for at most an hour (a scan takes minutes)
EVENING_AWAKE_S = 6 * 60     # after the 8:55 PM wake: time for Wi-Fi to reconnect, and each pause between scan tries


class awake:
    """`with awake(cap_s):` keeps Windows from sleeping for at most cap_s seconds (review 2026-10-25). A helper thread
    holds the request and drops it at the cap or when the block ends, whichever comes first, so a hung step or a long
    wait cannot keep a laptop (perhaps closed, in a bag) awake for hours. Used only around a step, after the evening
    wake while the network reconnects, and in the pause between scan tries. Never raises; does nothing off Windows."""
    def __init__(self, cap_s, setter=None):
        self.cap_s, self.setter = cap_s, setter
        self._stop = threading.Event()
        self._thread = None

    def _hold(self):
        if stay_awake(True, self.setter):
            try:
                self._stop.wait(self.cap_s)
            finally:
                stay_awake(False, self.setter)

    def __enter__(self):
        if os.name == "nt":
            try:
                self._thread = threading.Thread(target=self._hold, name="stay-awake", daemon=True)
                self._thread.start()
            except Exception:
                self._thread = None
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
        return False


def step(args, wait=joblock.WAIT_S, guard=None, busy_ok=False):
    """Run one run.bat step while holding the job lock. guard() is asked again once the lock is held: when it is false
    the step does not run (WINDOW_CLOSED). A lock that stays busy gives exit 75, or 0 with busy_ok (the hourly research)."""
    fh = joblock.acquire(wait=max(0, min(wait, remaining())), clock=time.time)   # wall clock: standby counts too
    if fh is None:
        say("JOB LOCK: another Tradebot step held the lock (%s), so `%s` did not run this time." % (
            joblock._owner() or "holder unknown", " ".join(args)))
        return 0 if busy_ok else joblock.BUSY
    try:
        if guard is not None and not guard():
            say("Scan not run: the scan window closed while another job held the lock.")
            return WINDOW_CLOSED
        joblock._owner(args)
        with awake(STEP_AWAKE_S):   # a scan or settle half done when the laptop dozes off would be lost
            p = subprocess.Popen(joblock.command(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE)
            for line in p.stdout:   # bytes in the console's own encoding, appended as they are
                log_bytes(line)
                try:
                    sys.stdout.buffer.write(line)
                    sys.stdout.flush()
                except Exception:
                    pass
            return p.wait()
    finally:
        joblock.release(fh)


def in_window(clock=time.time):
    t = time.localtime(clock())
    return scan_window.inside(t.tm_hour, t.tm_min)


def seconds_left(clock=time.time):
    """Seconds until the window closes at 1:00 AM local time, or 0 outside it."""
    now = clock()
    if not in_window(lambda: now):
        return 0
    t = time.localtime(now)
    end = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, scan_window.END_HOUR, 0, 0, 0, 0, -1))
    if t.tm_hour >= scan_window.END_HOUR:   # evening: the window closes tomorrow at 1:00
        end = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, scan_window.END_HOUR, 0, 0, 0, 0, -1))
    return max(0, int(end - now))


# ---------- the jobs ----------
def evening(run=step, net=wait_for_network, window=in_window, left=seconds_left, sleep=time.sleep, keep=awake):
    rc = 0
    # Settle first, as before. It needs the network only for open trades: wait while the scan window is open, or up to
    # an hour when the job starts outside it (a make-up run the next morning).
    with keep(EVENING_AWAKE_S):   # woken by the 8:55 PM timer: let Wi-Fi reconnect before Windows sleeps again
        net(lambda s: window() or s < SETTLE_NET_WAIT_S)
    rc = run(["run.bat", "settle"]) or rc
    if not window():
        say("Scan skipped: outside the evening scan window (8:50 PM to 1:00 AM). The next 8:55 PM run scans.")
        return rc
    r = 1
    for attempt in range(1, SCAN_TRIES + 1):
        if not net(lambda s: window()):
            say("Scan not run: no network before the window closed at 1:00 AM." if not window() else
                "Scan not run: no network, and this job's time is used up (it stops before Windows' time limit).")
            return rc or 1
        if not window():
            say("Scan not run: the window closed at 1:00 AM.")
            return rc or 1
        r = run(["run.bat", "scan"], wait=min(joblock.WAIT_S, left()), guard=window)
        if r == 0:
            if attempt > 1:
                say("scan: succeeded on try %d" % attempt)
            return rc
        if r == WINDOW_CLOSED:
            return rc or 1
        if attempt < SCAN_TRIES:
            say("scan: try %d of %d failed (exit %s); trying again in %d min" % (attempt, SCAN_TRIES, r, RETRY_PAUSE_S // 60))
            with keep(EVENING_AWAKE_S):   # otherwise an unattended laptop may sleep before the next try
                sleep(RETRY_PAUSE_S)
    say("scan: all %d tries failed" % SCAN_TRIES)
    return r


def settle(run=step, net=wait_for_network):
    net(lambda s: s < SETTLE_NET_WAIT_S)
    rc = 0
    for args in (["run.bat", "settle"], ["run.bat", "report"]):
        rc = run(args) or rc
    return rc


def _ps1_hash(ps1):
    import hashlib
    try:
        with open(ps1, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def apply_settings(applied=APPLIED, ps1=os.path.join(HERE, "tasks", "install_schedules.ps1"), runner=subprocess.run):
    """On Windows, once per version of install_schedules.ps1: run it so the three schedules start on battery and make up
    missed runs. Success is remembered in logs\\schedules_applied.txt with the script's hash, so a changed script is
    applied again; a failure is retried at the next hourly run. Never fails the job."""
    if os.name != "nt":
        return None
    h = _ps1_hash(ps1)
    try:
        with open(applied, encoding="utf-8") as f:
            if h and f.readline().strip() == h:
                return None
    except OSError:
        pass
    try:
        r = runner(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
                   capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        os.makedirs(os.path.dirname(applied), exist_ok=True)
        with open(os.path.join(os.path.dirname(applied), "schedules_settings.txt"), "w", encoding="utf-8") as f:
            f.write(out)
        if r.returncode == 0:
            with open(applied, "w", encoding="utf-8") as f:
                f.write("%s\n%s\n%s" % (h or "", time.strftime("%Y-%m-%d %H:%M:%S"), out))
            say("schedule settings: applied (runs on battery, makes up missed runs, the 8:55 PM scan wakes the PC); see logs\\schedules_settings.txt")
            return True
        say("schedule settings: not applied yet (exit %s; logs\\schedules_settings.txt says why); retried next hour" % r.returncode)
        return False
    except Exception as ex:   # never let this stop the research job
        say("schedule settings: not applied yet (%s); retried next hour" % str(ex)[:160])
        return False


def hourly(run=step, net=wait_for_network, settings=apply_settings):
    settings()
    net(lambda s: s < HOURLY_NET_WAIT_S)
    # read-only research, under the lock too; it skips an hour rather than wait long for a settle or scan
    return run(["run.bat", "hourly"], wait=HOURLY_LOCK_WAIT_S, busy_ok=True)


JOBS = dict(evening=evening, settle=settle, hourly=hourly)


def main(argv):
    if len(argv) != 1 or argv[0] not in JOBS:
        print(__doc__)
        return 2
    job = argv[0]
    _deadline[0] = time.time() + BUDGET_S.get(job, 3600)
    try:
        say("===== %s %s" % (stamp(), job))
    except Exception:
        say("===== no-time %s" % job)
    rc = 1
    try:
        rc = JOBS[job]()
    except BaseException:   # a bug here must still leave its trace and a done line in the log
        say("jobs.py %s failed:\r\n%s" % (job, traceback.format_exc()))
        rc = 1
    finally:
        try:
            say("===== %s %s done (exit %s)" % (stamp(), job, rc))
        except Exception:
            say("===== no-time %s done (exit %s)" % (job, rc))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
