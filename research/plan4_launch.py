"""Start a PLAN4 chain on this PC from a flag file (added 2026-10-29; research only, places no orders).

PLAN4's remaining steps need Kalshi's and Polymarket's public APIs, which only this PC's own Python can reach, and they
run for hours. So they cannot be a step of a scheduled job: the jobs take turns through joblock.py, and a long step
would hold up the evening scan. Instead the hourly job runs this script, which only STARTS a chain and returns at once:

  research/results/plan4_go_<CHAIN>.txt   (CHAIN is one of KS, PS) -> renamed to plan4_go_<CHAIN>.started.txt, then
  powershell -NoProfile -ExecutionPolicy Bypass -File research\\plan4_run.ps1 <CHAIN>, detached from the job

Each flag starts its chain once. The chain writes its own progress (research/results/plan4_status_<CHAIN>.txt) and logs.
A chain whose status file shows it still running (a start line with no end or stop after it) is not started again.
Python 3.8+, standard library only."""
import os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); RESULTS = os.path.join(HERE, "results")
CHAINS = ("KS", "PS")   # the finishing chains of research/plan4_run.ps1; nothing else can be started from here
DETACHED_PROCESS = 0x00000008; CREATE_NEW_PROCESS_GROUP = 0x00000200; CREATE_BREAKAWAY_FROM_JOB = 0x01000000; CREATE_NO_WINDOW = 0x08000000


def last_line(chain, results=RESULTS):
    try:
        lines = [l.strip() for l in open(os.path.join(results, "plan4_status_%s.txt" % chain), encoding="utf-8", errors="replace") if l.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def running(chain, results=RESULTS):
    """True when the chain's status file ends with a 'start' line (a step began and has not ended)."""
    return " start " in last_line(chain, results)


def powershell():
    """Windows PowerShell by its full path, so a stray powershell.exe beside python.exe or in this folder is never run."""
    if os.name != "nt":
        return "powershell"
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def command(chain, root=ROOT):
    return [powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(root, "research", "plan4_run.ps1"), chain]


def start(cmd, cwd=ROOT, popen=subprocess.Popen):
    """Start cmd in its own hidden console (CREATE_NO_WINDOW: the python steps the chain starts with -NoNewWindow share it,
    so no window appears; DETACHED_PROCESS would cancel CREATE_NO_WINDOW and give each step a visible console), in a new
    process group, outside the scheduled task's job object where Windows allows it, and with only DEVNULL handles passed
    on (close_fds), so the hourly job neither waits for it nor ends it."""
    if os.name != "nt":
        return popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    try:
        return popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=flags | CREATE_BREAKAWAY_FROM_JOB)
    except OSError:   # the task's job object does not allow breaking away: start it inside the job instead
        return popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)


def main(results=RESULTS, root=ROOT, popen=subprocess.Popen):
    started = []
    for chain in CHAINS:
        flag = os.path.join(results, "plan4_go_%s.txt" % chain)
        if not os.path.exists(flag):
            continue
        if running(chain, results):
            print("plan4: chain %s is still running (%s); flag kept for later" % (chain, last_line(chain, results)))
            continue
        done = os.path.join(results, "plan4_go_%s.started.txt" % chain)
        if os.path.exists(done):
            print("plan4: chain %s was started before (%s exists); this flag is set aside, not started" % (chain, os.path.basename(done)))
            try: os.replace(flag, os.path.join(results, "plan4_go_%s.ignored.txt" % chain))
            except OSError: pass
            continue
        try:
            os.replace(flag, done)   # the claim: one start per flag, even if starting fails below
        except OSError as ex:
            print("plan4: flag for %s not claimed (%s); tried again next hour" % (chain, ex))
            continue
        try:
            p = start(command(chain, root), cwd=root, popen=popen)
            print("plan4: started chain %s (process %s); progress in research\\results\\plan4_status_%s.txt" % (chain, getattr(p, "pid", "?"), chain))
            started.append(chain)
        except OSError as ex:
            print("plan4: could not start chain %s (%s)" % (chain, ex))
    return started


if __name__ == "__main__":
    main()
