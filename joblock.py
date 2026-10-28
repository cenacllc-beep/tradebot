"""Run one Tradebot step while holding the job lock (added 2026-10-23, outage review). Writes only logs/job.lock.

Why: since 2026-10-23 Windows Task Scheduler makes up a missed run as soon as the PC is available. When the PC was
off or asleep through both 2:51 PM and 8:55 PM, the afternoon settle and the evening run start at the same moment, and
two settles (each with live.py sync and backups) would write paper.db and live.db at once. tasks/settle.cmd and
tasks/evening.cmd run their steps through this file (since 2026-10-24 through jobs.py, which uses it), so steps from different jobs take turns.

  python joblock.py run.bat settle      -> runs `run.bat settle` once the lock is free; exit code = the step's

The lock is an operating-system lock on logs/job.lock (msvcrt on Windows, fcntl elsewhere), not the file's existence,
so a crashed or killed job never leaves a stale lock: the system releases it with the process. A step waits up to
WAIT_S for the lock; if it is still held, the step does not run, a JOB LOCK line explains it, and the exit code is 75.
Python 3.8+, standard library only."""
import os, sys, time, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = os.path.join(HERE, "logs", "job.lock")
OWNER = os.path.join(HERE, "logs", "job.owner")   # which step holds the lock, for the JOB LOCK message (text only)
WAIT_S = 45 * 60      # a settle takes minutes and a scan about 10; 45 minutes means something is stuck
POLL_S = 5
BUSY = 75             # exit code when the lock stayed held (EX_TEMPFAIL)


def _try_lock(fh):
    """Take the lock without waiting; OSError when another process holds it."""
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def release(fh):
    """Unlock explicitly, then close. Windows also unlocks on close or process exit, but its documentation advises an
    explicit unlock because that cleanup can be delayed (LockFile/UnlockFile remarks)."""
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        fh.close()


def acquire(path=None, wait=WAIT_S, poll=POLL_S, sleep=time.sleep, clock=time.monotonic):
    """An open handle that holds the lock (LOCK unless `path` is given), or None after `wait` seconds. release() it."""
    path = path or LOCK
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, "a+")
    deadline = clock() + wait
    while True:
        try:
            _try_lock(fh)
            return fh
        except OSError:
            if clock() >= deadline:
                fh.close()
                return None
            sleep(poll)


def command(args):
    """The step to run: a .bat or .cmd file needs cmd.exe on Windows (the system's own, from ComSpec, never a cmd
    file that happens to sit in the current folder)."""
    if os.name == "nt" and args and args[0].lower().endswith((".bat", ".cmd")):
        return [os.environ.get("ComSpec") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"), "/c"] + list(args)
    return list(args)


def _owner(args=None):
    """Write who holds the lock (args given) or read it back (args None). Text only, never trusted for locking."""
    try:
        if args is not None:
            with open(OWNER, "w", encoding="utf-8") as f:
                f.write("`%s`, process %d, since %s" % (" ".join(args), os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")))
            return None
        with open(OWNER, encoding="utf-8") as f:
            return f.read().strip()[:200]
    except OSError:
        return None


def main(args, wait=WAIT_S):
    if not args:
        print(__doc__)
        return 2
    sys.stdout.flush()
    fh = acquire(wait=wait)
    if fh is None:
        held = _owner()
        print("JOB LOCK: another Tradebot step held the lock for %d minutes (%s), so `%s` did not run this time. "
              "The lock frees itself when that step's process ends; if it is stuck, end that process "
              "(Task Manager) or restart the PC." % (wait // 60, held or "holder unknown", " ".join(args)))
        sys.stdout.flush()
        return BUSY
    try:
        _owner(args)
        sys.stdout.flush()
        # the step writes to the same place as this process (logs\tasks.log under the scheduled jobs), explicitly
        return subprocess.call(command(args), stdout=sys.stdout, stderr=sys.stderr)
    finally:
        release(fh)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
