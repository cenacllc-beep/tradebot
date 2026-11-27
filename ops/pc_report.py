"""PC-side backup reporter (added 2026-11-27; ops/README.md "When Claude is unavailable").

    python ops/pc_report.py settle | evening [--log FILE]     the report for the latest job block (jobs.py's final step)
    python ops/pc_report.py latenight [--log FILE]             11 PM to 1 AM: a report only when tonight's scan is
                                                               missing or still waiting (jobs.py's hourly job)

It does on the PC what Claude's afternoon report, evening report and late-night scan check do in the cloud, so they go
on when Claude hits its usage limit: it reads ONLY logs\\tasks.log (the latest block of that job), lists the same facts
(markets and trades, the Brier line, the gate verdict as stored, the FRESHNESS line, live demo and prod lines, and every
problem line from a narrow list: KILL SWITCH, TRADES BLOCKED, AUDIT, JOB LOCK, job failures, WAITING FOR NETWORK), and
writes logs\\report_latest.md plus logs\\reports\\YYYY-MM-DD-<job>.md (the newest 30 are kept). logs\\ is git-ignored.
Lines are attributed to a job by jobs.py's step markers ("----- <job> step: ..." / "----- <job> step end (exit N)");
older logs without markers fall back to the most recently started job.

The plain report is written first. Then, only when the user chose to keep the NVIDIA key on this PC (settings page;
ops/pc_key.py), the job's status lines go to NVIDIA's API (integrate.api.nvidia.com, approved 2026-11-26) through
ops/backup_ai.py's own client and model picker, within this script's budget (AI_CALLS calls, AI_SECONDS seconds, a
thread with a join timeout). Never sent: real-money or account lines (live demo/prod, the real-money trial), settled
P&L, the LEARNING profit line, any line with a dollar figure, and anything that looks like a key, token or e-mail
address. The AI text replaces the plain summary only if every signed number in it appears in what was sent (dates,
times, exit codes and tickers do not count) and it names every problem; the deterministic problem list always comes
first. The report says which wording was used and why.

When the report shows a problem, a Windows toast is shown (PowerShell's built-in Windows.UI.Notifications; never waits,
failures ignored). The phone page cannot be refreshed: it is a claude.ai page that only Claude can update.

Never opens paper.db or live.db, never imports live.py, never runs anything that trades. Python 3.8 syntax, standard
library (plus requests through backup_ai, only when a key is kept)."""
import os, re, sys, glob, subprocess, threading, time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
LOG = os.path.join(ROOT, "logs", "tasks.log")
KEEP = 30
TAIL = 2 * 1024 * 1024
AI_SECONDS = 150          # this script's own AI budget: all model calls together (jobs.py stops it after 4 minutes)
AI_CALLS = 3
MAX_AI_CHARS = 3000

MARK = re.compile(r"^=====\s+(?:(\S+)\s+)?(evening|settle|hourly)(\s+done \(exit (-?\d+)\))?\s*$")   # as freshness.py
STEP = re.compile(r"^-----\s+(evening|settle|hourly|job)\s+step(?:: .*| end \(exit \S+\))\s*$")
SCAN_DONE = re.compile(r"(\d+) markets in shadow log, (\d+) paper trades logged")
# Problem lines: a narrow list (code review 2026-11-27), so per-market errors that are retried never raise a toast.
PROBLEMS = tuple(re.compile(p) for p in (
    r"^KILL SWITCH", r"^KILL file present", r"^TRADES BLOCKED", r"^NOT TRADED ",
    r"^AUDIT( UNAVAILABLE)?:(?! scan ).*(could not|unavailable|not recorded|failed)",
    r"^JOB LOCK", r"^WAITING FOR NETWORK", r"^network: still not reachable",
    r"^Backup failed", r"^The live\.db backup failed", r"^Could not check the kill switch",
    r"^scan: all \d+ tries failed", r"^Scan not run", r"^jobs\.py \w+ failed", r"could not start: Python not found",
    r"ORDER OUTCOME UNKNOWN", r"^SETTLE: \d+ of \d+ markets could not be read", r"^SETTLE WARNING",
    r"account snapshot failed", r"^GATE LOOK not stored", r"^WARNING: \d+ markets had a close time",
    r"^live \((demo|prod)\): no orders: (could not read|\d+ earlier order)", r"^Real-money trial: ENDED"))
# Lines about the Kalshi account or money: kept in the facts, never sent to the AI.
ACCOUNT = re.compile(r"^(live\b|Real-money|ORDER OUTCOME|SETTLED |TRADES v3|LEARNING:|Kalshi)|\$|P&L|pnl|account snapshot", re.I)


# ---------- reading the log ----------
def read_tail(path, tail=TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _say_job(s, jobs, step_job):
    """jobs.py's own lines (never step output) by their content: which open job wrote it, or None."""
    m = re.match(r"^JOB LOCK:.*`run\.bat (\w+)", s)
    if m:
        w = m.group(1)
        if w == "hourly":
            return "hourly"
        if w == "scan":
            return "evening"
        return "settle" if "settle" in jobs else "evening"
    if s.startswith(("Scan skipped", "Scan not run", "scan: ")):
        return "evening"
    if s.startswith("schedule settings:"):
        return "hourly"
    m = re.match(r"^jobs\.py (\w+) failed", s)
    if m:
        return m.group(1)
    if s.startswith(("WAITING FOR NETWORK", "network: ")):
        others = [j for j in jobs if j != step_job]   # a job inside a step is not waiting for the network
        return others[0] if others else None          # the longest-open job (the settle or evening job waits longest)
    return None


def blocks(text):
    """Every job block in the log, oldest first: dict(job, start, end, finished, exit, lines).
    Attribution: jobs.py's own lines by content; then lines between "----- <job> step: ..." and "----- <job> step end"
    belong to that job; otherwise (older logs) to the most recently started job that has not finished. A job started
    again before its done line closes the old block as unfinished. Lines this reporter wrote ("PC REPORT:") are
    skipped."""
    out, open_, step_job, sticky = [], [], None, None
    for raw in text.splitlines():
        s = raw.strip()
        m = MARK.match(s)
        if m:
            job, done = m.group(2), bool(m.group(3))
            if not done:
                open_ = [b for b in open_ if b["job"] != job]
                b = dict(job=job, start=m.group(1), end=None, finished=False, exit=None, lines=[])
                out.append(b)
                open_.append(b)
            else:
                for b in reversed(open_):
                    if b["job"] == job:
                        try:
                            code = int(m.group(4))
                        except ValueError:
                            code = 1
                        b.update(finished=True, end=m.group(1), exit=code)
                        open_.remove(b)
                        break
                if step_job == job:
                    step_job = None
            sticky = None
            continue
        st = STEP.match(s)
        if st:
            step_job = None if " step end " in s else st.group(1)
            sticky = None
            continue
        if s.startswith("PC REPORT:") or not open_:
            continue
        names = [b["job"] for b in open_]
        who = _say_job(s, names, step_job)
        if who is None and sticky and (raw[:1].isspace() or s.startswith("Traceback")):
            who = sticky      # a traceback under "jobs.py X failed:"
        if who is None and step_job in names:
            who = step_job
        if who not in names:
            who = names[-1]
        if s.startswith("jobs.py "):
            sticky = who
        for b in reversed(open_):
            if b["job"] == who:
                b["lines"].append(s)
                break
    return out


def latest(text, job):
    bl = [b for b in blocks(text) if b["job"] == job]
    return bl[-1] if bl else None


def parse_stamp(s):
    """A jobs.py time (ISO with its UTC offset; older lines without one are this PC's local time) as epoch seconds."""
    if not s or s == "no-time":
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else time.mktime(d.timetuple())


# ---------- the facts (deterministic) ----------
def is_problem(s):
    return any(p.search(s) for p in PROBLEMS)


def facts(block, job, now=None):
    """What the Claude reports quote, from one job block. Returns a dict; render() turns it into text."""
    F = dict(job=job, found=block is not None, problems=[], notes=[], live_demo=[], live_prod=[], live_other=[],
             settled=[], paper=[], gate=[], brier=[], trades_line=[], margin=[], freshness=None, scan=None,
             learning=None, shadow=None, skipped=None)
    if block is None:
        F["problems"].append("No %s job is in logs\\tasks.log yet." % job)
        return F
    F.update(start=block["start"], end=block["end"], finished=block["finished"], exit=block["exit"])
    for s in block["lines"]:
        if s.startswith("SETTLED "):
            F["settled"].append(s)
        elif s.startswith("PAPER "):
            F["paper"].append(s)
        if SCAN_DONE.search(s):
            F["scan"] = s
        if s.startswith("SHADOW v3 rain:"):
            F["brier"].append(s)
        if s.startswith("TRADES v3 rain"):
            F["trades_line"].append(s)
        if s.startswith("CLEAR MARGIN"):
            F["margin"].append(s)
        if s.startswith("GATE"):
            F["gate"].append(s)
        if s.startswith("FRESHNESS:"):
            F["freshness"] = s
        if s.startswith("LEARNING:"):
            F["learning"] = s
        if s.startswith("shadow maker:") and "orders placed" in s:
            F["shadow"] = s
        if s.startswith("live (demo)"):
            F["live_demo"].append(s)
        elif s.startswith("live (prod)") or s.startswith("Real-money trial"):
            F["live_prod"].append(s)
        elif s.startswith("live:"):
            F["live_other"].append(s)
        if s.startswith(("daily loss limit hit", "network: back", "scan: try ", "scan: succeeded")):
            F["notes"].append(s)
        if s.startswith("Scan skipped"):
            F["skipped"] = s
            F["notes"].append(s)
        if is_problem(s):
            F["problems"].append(s)
    if F["freshness"] and not F["freshness"].startswith("FRESHNESS: all current"):
        F["problems"].append(F["freshness"])
    if not block["finished"]:
        F["problems"].append("The %s job has no done line yet: it is still running (or was cut off)." % job)
    elif block["exit"] not in (0, None):
        F["problems"].append("The %s job finished with exit %s (not 0)." % (job, block["exit"]))
    if job == "evening" and not F["scan"] and not F["skipped"] and block["finished"]:
        why = [p for p in F["problems"] if "scan" in p.lower() or "kill switch" in p.lower()]
        F["problems"].append("Tonight's scan did not log the next market day" + (": " + why[0] if why else "."))
    F["problems"] = _uniq(F["problems"])
    return F


def _uniq(rows):
    seen, out = set(), []
    for p in rows:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def latenight_facts(text, now=None):
    """Tonight's evening job, read between 11 PM and 1 AM. Returns (facts, night date), or (None, date) when tonight's
    scan ran. With no scan tonight there is always a problem, with its reason."""
    now = time.time() if now is None else now
    lt = time.localtime(now)
    night = (datetime.fromtimestamp(now) - (timedelta(days=1) if lt.tm_hour < 12 else timedelta(0))).date()
    bl = [b for b in blocks(text) if b["job"] == "evening"]
    b = bl[-1] if bl else None
    t0 = parse_stamp(b["start"]) if b else None
    if b is not None and t0 is None:
        F = facts(b, "evening", now)
        F["job"] = "latenight"
        first = (b["lines"] or ["no lines"])[0]
        F["problems"] = _uniq(["The latest evening job has no time in the log (%s), so tonight's scan cannot be confirmed."
                               % first[:200]] + F["problems"])
        return F, night
    if b is None or now - t0 > 6 * 3600 or t0 > now + 300:
        F = facts(None, "evening", now)
        F["problems"] = ["Tonight's evening job (8:55 PM) has not started: no scan yet, and the scan window closes at "
                         "1:00 AM. Is the PC on, awake and online?"]
        F["job"] = "latenight"
        return F, night
    F = facts(b, "evening", now)
    if F["scan"]:
        return None, night
    F["job"] = "latenight"
    if not b["finished"]:
        waiting = [p for p in F["problems"] if p.startswith("WAITING FOR NETWORK")]
        lead = ("Tonight's scan has not run yet and the evening job is still " +
                ("waiting for the network." if waiting else "running.") + " The scan window closes at 1:00 AM.")
    elif F["skipped"]:
        lead = "Tonight's scan was skipped: " + F["skipped"]
    else:
        lead = "Tonight's scan did not run: the evening job finished without logging the next market day."
    F["problems"] = _uniq([lead] + F["problems"])
    return F, night


def _lines(title, rows):
    return ["", "%s:" % title] + ["- " + r for r in rows] if rows else []


def render(F, ai=False):
    """The deterministic text: every fact, nothing added. ai=True leaves out every account and money line (they stay
    in the report's facts) and replaces account problem lines with a neutral mention."""
    job = F["job"]
    out = []
    if not F["found"]:
        out.append("Job: %s (no block found in logs\\tasks.log)" % job)
    else:
        out.append("Job: %s, started %s, %s" % (
            job, F.get("start") or "no-time",
            ("finished %s, exit %s" % (F.get("end") or "no-time", F.get("exit"))) if F.get("finished") else "not finished"))
    out.append("Problems: %s" % (len(F["problems"]) if F["problems"] else "none"))
    probs = [("A Kalshi account problem (the line is kept on the PC)" if ai and ACCOUNT.search(p) else p)
             for p in F["problems"]]
    out += _lines("Problem lines", probs)
    if F["found"]:
        if job in ("settle", "evening", "latenight"):
            out += ["", "Trades settled: %d" % len(F["settled"])]
            if not ai:
                out += ["- " + s for s in F["settled"][:20]]
                if len(F["settled"]) > 20:
                    out.append("- (%d more in logs\\tasks.log)" % (len(F["settled"]) - 20))
        if job in ("evening", "latenight"):
            out += ["", "Scan: " + (F["scan"] or "no scan line (tonight's market day was not logged)")]
            out += ["- " + s for s in F["paper"]]
        out += _lines("Brier (v3 rain, resolved markets)", F["brier"])
        if not ai:
            out += _lines("Paper trades (v3 rain)", F["trades_line"])
        out += _lines("Clear margin", F["margin"])
        out += _lines("Gate (as stored; only the stored look is a verdict)", F["gate"])
        if not ai:
            out += _lines("Kalshi demo (fake money)", F["live_demo"])
            out += _lines("Kalshi prod (real money)", F["live_prod"])
            out += _lines("Kalshi", F["live_other"])
        if F["shadow"]:
            out += ["", "Limit-order ledger: " + F["shadow"]]
        if F["learning"] and not ai:
            out += ["", F["learning"]]
        out += _lines("Notes", F["notes"])
        out += ["", F["freshness"] or "FRESHNESS: no line in this job"]
    if ai:   # a last guard: no line with a money or account figure leaves the PC
        out = [l for l in out if not (l.strip() and ACCOUNT.search(l.lstrip("- ")) and not l.startswith("- A Kalshi account problem"))]
    return "\n".join(out)


# ---------- AI wording, checked ----------
NUM = re.compile(r"\d+(?:[.,]\d+)*")
NOT_ALLOWED = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[-+]\d{2}:\d{2})?)?"   # dates and stamps
    r"|\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?"                                # clock times
    r"|\(?\bexit -?\d+\)?"                                                     # exit codes
    r"|\b[A-Z][A-Z0-9]*(?:-[A-Z0-9.]+)+\b"                                     # tickers
    r"|\bv\d+\b")                                                              # version tags


def signed(text):
    """[(token, canonical signed value)] for every number; a sign counts when it stands before the number (or its $)."""
    out = []
    for m in NUM.finditer(text or ""):
        j = m.start()
        if j > 0 and text[j - 1] == "$":
            j -= 1
        neg = j > 0 and text[j - 1] in "-−" and (j == 1 or not text[j - 2].isalnum())
        raw = m.group(0).replace(",", "")
        try:
            v = Decimal(raw)
        except InvalidOperation:
            out.append((m.group(0), ("-" if neg else "") + raw))
            continue
        if neg:
            v = -v
        out.append((m.group(0), str(int(v)) if v == v.to_integral_value() else format(v.normalize(), "f")))
    return out


def allowed(facts_text):
    return set(c for _, c in signed(NOT_ALLOWED.sub(" ", facts_text or "")))


def unknown_numbers(ai_text, facts_text):
    """The numbers in the AI's text (with their signs) that are not among the facts' numbers; dates, times, exit codes,
    tickers and version tags in the facts do not count."""
    have = allowed(facts_text)
    ai_text = re.sub(r"\bv\d+\b", " ", ai_text or "")   # "v3" names the model version; it is not a figure
    return [("-" if c.startswith("-") else "") + t for t, c in signed(ai_text) if c not in have]


ALL_CLEAR = re.compile(r"\b(all clear|nothing needs|no problems?|0 problems?|zero problems?|no issues?|everything (is )?"
                       r"(fine|ok|normal|green))\b", re.I)
_WORDS = (("kalshi account problem", ("kalshi", "account")), ("kill", ("kill",)), ("trades blocked", ("block",)),
          ("audit", ("audit", "decision")), ("not traded", ("not traded", "decision")), ("job lock", ("lock",)),
          ("network", ("network", "offline", "internet", "connection")), ("freshness", ("fresh", "stale", "out of date")),
          ("backup", ("backup",)), ("no done line", ("running", "finish", "cut off")), ("has not started", ("not started", "start")),
          ("exit", ("exit", "fail", "error")), ("close time", ("close time", "format")), ("gate look", ("gate",)),
          ("python", ("python",)), ("settle", ("settle",)), ("scan", ("scan",)), ("order outcome", ("order",)))


def problem_words(p):
    low = p.lower()
    if ACCOUNT.search(p) or low.startswith("a kalshi account problem"):
        return ("kalshi", "account")
    for key, words in _WORDS:
        if key in low:
            return words
    w = [x for x in re.findall(r"[a-z]{4,}", low)]
    return (w[0],) if w else ()


def missing_problems(ai_text, problems):
    low = (ai_text or "").lower()
    return [p for p in problems if problem_words(p) and not any(w in low for w in problem_words(p))]


SUMMARY_SYSTEM = (
    "Below are the status lines of one scheduled job of a small paper-trading research bot, read from its log on the "
    "owner's PC. Write a short plain-English summary for the owner (at most 8 sentences). Start with whether anything "
    "needs attention and name every problem line. Use only these facts: copy numbers exactly as written, with their "
    "signs, and add no other number, no date, no time, no estimate and no arithmetic. Quote the gate verdict only as "
    "stored. No advice about trading or money, no hype.")


def ai_summary(sent, problems, key, ai_factory=None):
    """(text or None, label, calls used). text is None when the deterministic text must be used."""
    try:
        import backup_ai as B
    except Exception as ex:  # noqa: BLE001
        return None, "deterministic (backup_ai unavailable: %s)" % type(ex).__name__, 0
    ai = None
    try:
        ai = (ai_factory or (lambda k: B.AI(key=k, max_calls=AI_CALLS, total=AI_SECONDS)))(key)
        model, text = ai.ask("check-summary", SUMMARY_SYSTEM, sent)
    except Exception as ex:  # noqa: BLE001  (ApiError, no model, budget): never the key or the body
        return None, "deterministic (NVIDIA API: %s)" % B.redact(str(ex))[:160], getattr(ai, "calls", 0)
    calls = getattr(ai, "calls", 0)
    text = B.redact((text or "").strip())[:MAX_AI_CHARS]
    if key:
        text = text.replace(key, "[REDACTED]")
    if not text:
        return None, "deterministic (the model gave no answer)", calls
    if problems and ALL_CLEAR.search(text):
        return None, "deterministic (the AI text called it clear while there are problems)", calls
    miss = missing_problems(text, problems)
    if miss:
        return None, "deterministic (the AI text left out a problem: %s)" % miss[0][:80], calls
    bad = unknown_numbers(text, sent)
    if bad:
        return None, "deterministic (the AI text had numbers not in the facts: %s)" % ", ".join(bad[:5]), calls
    return text, "AI (NVIDIA %s; every number and problem checked against the facts)" % model, calls


# ---------- files and the toast ----------
def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def prune(folder, keep=KEEP):
    files = sorted(glob.glob(os.path.join(folder, "????-??-??-*.md")))
    for p in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(p)
        except OSError:
            pass


TOAST_PS = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$x=$t.GetElementsByTagName('text');"
    "$x.Item(0).AppendChild($t.CreateTextNode($env:TB_TOAST_TITLE))|Out-Null;"
    "$x.Item(1).AppendChild($t.CreateTextNode($env:TB_TOAST_BODY))|Out-Null;"
    "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)")


def toast(title, body, popen=subprocess.Popen):
    """A Windows notification. The text goes in environment variables (never into the command); the call does not
    wait for PowerShell, and any failure is ignored. Returns True when PowerShell was started."""
    if os.name != "nt" and popen is subprocess.Popen:
        return False
    try:
        env = dict(os.environ, TB_TOAST_TITLE=title[:120], TB_TOAST_BODY=body[:240])
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", TOAST_PS],
              env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              creationflags=flags if os.name == "nt" else 0)
        return True
    except Exception:  # noqa: BLE001
        return False


NAMES = dict(settle="Afternoon settle", evening="Evening run", latenight="Late-night scan check")


def plain_summary(F):
    """The deterministic summary: the main facts, all copied from the log (the problems are listed above it)."""
    out = ["Nothing needs attention." if not F["problems"] else "See the problems above."]
    if F["found"]:
        if F["job"] in ("evening", "latenight"):
            out.append("- Scan: " + (F["scan"] or "tonight's market day was not logged"))
        out.append("- Trades settled: %d" % len(F["settled"]))
        look = [g for g in F["gate"] if g.startswith("GATE LOOK")]
        if look:
            out.append("- " + look[-1])
        for s in F["live_demo"][-1:] + F["live_prod"][-1:]:
            out.append("- " + s)
        out.append("- " + (F["freshness"] or "FRESHNESS: no line in this job"))
    return "\n".join(out)


def compose(F, summary, label, budget, now):
    """The report: the deterministic problem list first, then the summary (AI or plain), then every fact."""
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    status = ("PROBLEMS: %d" % len(F["problems"])) if F["problems"] else "All clear"
    md = ["# Tradebot PC report: %s" % NAMES.get(F["job"], F["job"]), "",
          "Written %s by this PC (ops/pc_report.py), whether or not Claude is available." % stamp,
          "Status: %s" % status, "Wording: %s" % label, "AI budget: %s" % budget, "",
          "## Problems", ""] + (["- " + p for p in F["problems"]] or ["None."]) + [
          "", "## Summary", "", summary,
          "", "## Facts from logs\\tasks.log", "", render(F), "",
          "Read only from logs\\tasks.log. The phone page is not updated by this report (only Claude can update it)."]
    return "\n".join(md) + "\n"


def _key(loader):
    """(key or None, status text or None)."""
    try:
        res = loader()
    except Exception:  # noqa: BLE001
        return None, "the key could not be loaded"
    if isinstance(res, tuple):
        key, st = res
    else:
        key, st = res, None
    if key:
        return key, None
    try:
        import pc_key
        return None, pc_key.STATUS_TEXT.get(st, "no NVIDIA key kept on this PC")
    except Exception:  # noqa: BLE001
        return None, "no NVIDIA key kept on this PC"


def report(job, log=None, key_loader=None, ai_factory=None, popen=subprocess.Popen, now=None, out_dir=None,
           ai_seconds=None):
    """Write the report for `job`: the plain one first, then (with a key) the AI wording if it passes the checks.
    Returns (path or None, status line)."""
    now = time.time() if now is None else now
    log = log or LOG
    logs_dir = out_dir or os.path.dirname(os.path.abspath(log))
    text = read_tail(log)
    if job == "latenight":
        lt = time.localtime(now)
        if not (lt.tm_hour >= 23 or lt.tm_hour < 1):
            return None, "late-night check: only between 11 PM and 1 AM"
        F, night = latenight_facts(text, now)
        if F is None:
            return None, "late-night check: tonight's scan ran; no report"
        day = night.isoformat()
    else:
        b = latest(text, job)
        F = facts(b, job, now)
        t0 = parse_stamp(b["start"]) if b else None
        day = time.strftime("%Y-%m-%d", time.localtime(t0 if t0 else now))
    rep_dir = os.path.join(logs_dir, "reports")
    path = os.path.join(rep_dir, "%s-%s.md" % (day, F["job"]))
    latest_path = os.path.join(logs_dir, "report_latest.md")
    before = None
    if job == "latenight" and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                before = f.read()
        except OSError:
            before = None
    key, why = _key(key_loader or _load_key)
    limit = AI_SECONDS if ai_seconds is None else ai_seconds
    budget0 = "at most %d calls and %d s (this script); %s" % (AI_CALLS, limit, "not used" if not key else "trying")
    plain = plain_summary(F)
    label0 = "deterministic (%s)" % why if not key else "deterministic (AI wording being tried)"
    md = compose(F, plain, label0, budget0, now)
    write_atomic(path, md)              # the plain report first: nothing below can lose it
    write_atomic(latest_path, md)
    prune(rep_dir)
    toasted = False
    if F["problems"]:
        same = before is not None and _problem_block(before) == _problem_block(md)
        if not same:   # the 00:20 check does not repeat the 23:20 toast for the same problems
            toasted = toast("Tradebot: %s needs a look" % NAMES.get(F["job"], F["job"]),
                            "%d problem%s. %s" % (len(F["problems"]), "" if len(F["problems"]) == 1 else "s",
                                                  F["problems"][0]), popen=popen)
    label = label0
    if key:
        sent = render(F, ai=True)
        try:
            import backup_ai as B
            sent = B.redact(sent)
        except Exception:  # noqa: BLE001
            pass
        probs = [("A Kalshi account problem (the line is kept on the PC)" if ACCOUNT.search(p) else p) for p in F["problems"]]
        res = {}
        t0 = time.time()

        def work():
            res["r"] = ai_summary(sent, probs, key, ai_factory)
        th = threading.Thread(target=work, name="pc-report-ai", daemon=True)
        th.start()
        th.join(limit + 10)
        took = int(time.time() - t0)
        if th.is_alive():
            text_, label, calls = None, "deterministic (the AI took longer than %d s)" % limit, "?"
        else:
            text_, label, calls = res.get("r", (None, "deterministic (AI step failed)", 0))
        budget = "at most %d calls and %d s (this script); used %s call%s in %d s" % (
            AI_CALLS, limit, calls, "" if calls == 1 else "s", took)
        md = compose(F, text_ if text_ is not None else plain, label, budget, now)
        write_atomic(path, md)
        write_atomic(latest_path, md)
    key = None
    return path, "%s report written (%s; %s%s)" % (
        NAMES.get(F["job"], F["job"]), label.split(" (")[0], "%d problems" % len(F["problems"]) if F["problems"] else "all clear",
        ", toast shown" if toasted else "")


def _problem_block(md):
    m = re.search(r"## Problems\n\n((?:- .*\n?)*)", md)
    return m.group(1) if m else ""


def _load_key():
    import pc_key
    return pc_key.load_status()


def main(argv):
    args = list(argv)
    log = None
    if "--log" in args:
        i = args.index("--log")
        log = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if len(args) != 1 or args[0] not in ("settle", "evening", "latenight"):
        print(__doc__)
        return 2
    path, line = report(args[0], log=log)
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
