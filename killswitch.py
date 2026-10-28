"""The kill switch, as a command (added 2026-10-15 at the user's request: "the kill switch is not wired"):
  python killswitch.py on       halt: creates the KILL file in the tradebot folder        (.\\run kill)
  python killswitch.py status   on or off (exit code 2 when on)                           (.\\run kill status)
  python killswitch.py off      resume: typed by you in a terminal, asks to confirm      (.\\run unkill)
While it is on, a scan does only the backups, the export and the dashboard: no paper trades, no shadow limit orders, no
Kalshi orders (main.py, shadow.py and live.py each check it too, and live.py checks again before every order). Settling
still records what already happened; it never places orders. A file named KILL or KILL.txt (any case, any ending)
created by hand in the tradebot folder works the same way; deleting it by hand resumes.
"off" removes only files named KILL / KILL.txt (any case) in the tradebot folder. Anything else that counts as a kill
file (a folder named KILL, KILL.md, ...) is listed for you to delete by hand, and the bot stays halted until you do."""
import os, sys, re
from datetime import datetime
import core
REMOVABLE=re.compile(r"kill(\.txt)*",re.I)
def ascii_(x): return str(x).encode("ascii","replace").decode("ascii")   # printable on any Windows console, also when piped
def here():
    """Kill files in the tradebot folder; an unreadable folder counts as on."""
    try: return core.kill_names(core.HERE)
    except OSError as ex: return [os.path.join(core.HERE,"KILL (folder could not be read: %s)"%ex)]
def status():
    fs=here()
    if fs: print("Kill switch: ON (%s). Scans place no trades and no orders. Resume: .\\run unkill"%ascii_(fs[0]))
    else: print("Kill switch: off (checked %s). Halt with .\\run kill"%ascii_(core.HERE))
    f=core.kill_file()
    if not fs and f: print("Note: %s also halts commands started from that folder (not the scheduled runs)."%ascii_(f))
    return 2 if fs else 0
def on():
    fs=here()
    if fs: print("Kill switch already ON (%s)."%ascii_(fs[0])); return 0
    p=os.path.join(core.HERE,"KILL")
    with open(p,"w",encoding="utf-8") as fh: fh.write("Kill switch on since %s. Delete this file (or run .\\run unkill) to resume.\n"%datetime.now().strftime("%Y-%m-%d %H:%M"))
    if not here(): sys.exit("Could not turn the kill switch on: %s was not created."%ascii_(p))
    print("Kill switch ON (%s): no paper trades, no shadow orders, no Kalshi orders until you run .\\run unkill."%ascii_(p)); return 0
def off(confirm=True):
    if confirm:
        if not (sys.stdin and sys.stdout and sys.stdin.isatty() and sys.stdout.isatty()):   # a person at a console (as live.py unlock)
            sys.exit("The kill switch is turned off only by you: type .\\run unkill in a normal PowerShell window, or delete the KILL file in %s."%ascii_(core.HERE))
        if not here(): print("Kill switch is already off."); return 0
        if input("Turn the kill switch off and let the bot trade again? Type yes: ").strip().lower()!="yes": sys.exit("Not changed: the kill switch stays ON.")
    removed,keep=0,[]
    for f in here():
        n=os.path.basename(f)
        if REMOVABLE.fullmatch(n) and (os.path.islink(f) or os.path.isfile(f)):
            try: os.remove(f); removed+=1
            except OSError as ex: keep.append("%s (%s)"%(f,ex))
        else: keep.append(f)
    if keep:
        sys.exit("Removed %d. Still halted: delete by hand: %s"%(removed,"; ".join(ascii_(k) for k in keep)))
    print("Kill switch off (%d file(s) removed). The next scan trades normally."%removed if removed else "Kill switch was already off.")
    return 0
if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else "status"
    if cmd not in ("on","off","status"): sys.exit(__doc__)
    sys.exit({"on":on,"off":off,"status":status}[cmd]())
