"""Backup AI operator (added 2026-11-26 at the user's request; ops/README.md). Runs on GitHub Actions
(.github/workflows/backup-ai.yml) and watches the repository's own scheduled jobs when Claude is not around.

    python3 ops/backup_ai.py check | report | rerun | fix | all

check   deterministic, no AI: the latest runs of every workflow in .github/workflows against the schedule in its cron
        lines, and the age of the research data the jobs commit. Writes ops/status/status.json and status.md.
report  asks an NVIDIA-hosted model (OpenAI-compatible API) for a plain-English report, then opens, updates or closes ONE
        GitHub issue labelled backup-ai, so GitHub e-mails the user when something is wrong.
rerun   re-runs a failed run once, only for an allowlist of research and paper logging workflows; never twice.
fix     only when no commit carrying Claude's co-author trailer reached main in the last 24 hours: asks the model for a
        minimal diff for one failing workflow, refuses any protected path, applies it on a branch in a separate
        worktree, runs the tests and opens a pull request for a human or Claude to review. It never merges.

Same permissions as Claude minus anything to do with real money: it never imports or runs the order-placing module,
never opens the bot's databases, and never writes outside ops/status/ on main. Its output is advice only.
Python 3.8 syntax; standard library plus requests (only for the NVIDIA API). The API key comes from the environment
variable NVIDIA_API_KEY and is never printed, logged or written. Without it, only the non-AI check (and the issue)
runs and the report says the key is missing."""
import base64, json, os, posixpath, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_DIR = os.path.join(ROOT, "ops", "status")
WORKFLOW_DIR = os.path.join(ROOT, ".github", "workflows")
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
USER_AGENT = "tradebot-paper-research/1.0"
LABEL = "backup-ai"
MAX_AI_CALLS = 6
LA_PAZ = timezone(timedelta(hours=-4))
SCHEMA = 1

# ---------------------------------------------------------------------------------------------------------------
# What may be re-run automatically (once). Research and paper logging only, whose steps are safe to repeat:
#   live20     PLAN20's forward logger (research/live20.py: public reads, a paper ledger; not the order module)
#   plan19     PLAN19's hourly sample, settle and auto-score (the score is written once and the job no-ops after)
#   plan5-lip  PLAN5 L's sample (scored; the job now stops at its first line)
#   probe18/19 read-only probes that only count markets
#   tradebot-scan / tradebot-settle  the trial paper bot on trial/paper.db; the scan is guarded by its window and
#              check.py (one scan an evening), settling again is safe
# Never: plan10, plan15-18, plan20 (one-time stages: freeze, fit, map, download, score), the backstop (it starts
# scans), this workflow itself, or anything not listed.
RERUN_ALLOW = ("live20.yml", "plan19.yml", "plan5-lip.yml", "probe18.yml", "probe19.yml",
               "tradebot-scan.yml", "tradebot-settle.yml")
RERUN_MAX_AGE_H = 12
FAILED = ("failure", "timed_out", "startup_failure")

# Research data the jobs commit: (path, limit in hours or None for information only, active from, active until (UTC),
# a file whose presence means the job is finished).
DATA = (
    ("research/data/live20", 6, None, None, None),
    ("research/data/plan19", 3, "2026-11-28T06:00:00Z", "2026-12-28T06:00:00Z", "research/results/plan19_result.json"),
    ("research/data/plan20", None, None, None, None),
    ("research/results", None, None, None, None),
    ("trial", 30, None, None, None),
)

# ---------------------------------------------------------------------------------------------------------------
# Protected paths: a fix proposal touching any of these is refused (hard-coded; tests/test_backup_ai.py checks it).
PROTECTED_FILES = ("live.py", "live.db", "paper.db", "config.py", "strategy.py", "weather.py", "nws.py", "gate.py",
                   "core.py", "claude.md", "run.bat", "ops/backup_ai.py", "tests/test_backup_ai.py",
                   "tests/run_all.py", ".gitignore", "cloud/repo.gitignore")
PROTECTED_DIRS = (".claude/", ".github/", "cloud/workflows/", "agents/", "tasks/", "backups/", "trial/",
                  "research/results/", "ops/status/", ".git/", ".kalshi/")
PROTECTED_ANYWHERE = ("live.py", "live.db", "paper.db")     # by file name, in any folder
PROTECTED_SUFFIXES = (".cmd", ".ps1", ".bat", ".pem", ".key")


def protected(path):
    """The reason a path may not be changed by a fix proposal, or None. Fails closed: anything odd is protected."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        return "empty or invalid path"
    p = path.strip().replace("\\", "/")
    if p.startswith("/") or re.match(r"^[a-zA-Z]:", p) or p.startswith("~"):
        return "absolute path"
    if any(part == ".." for part in p.split("/")):
        return "path leaves the repository"
    p = posixpath.normpath(p)
    while p.startswith("./"):
        p = p[2:]
    if p in (".", "") or p.startswith("../"):
        return "path leaves the repository"
    low = p.lower()      # the PC is Windows: Live.py and live.py are the same file there
    base = low.rsplit("/", 1)[-1]
    if low in PROTECTED_FILES:
        return "protected file"
    for d in PROTECTED_DIRS:
        if low.startswith(d) or low + "/" == d:
            return "protected folder " + d
    for name in PROTECTED_ANYWHERE:
        if base == name or base.startswith(name + "-") or base.startswith(name + "."):
            return "protected file name"
    if "frozen" in base:
        return "frozen file"
    if base.endswith(PROTECTED_SUFFIXES):
        return "protected file type"
    if re.match(r"^research/plan[^/]*\.md$", low):
        return "pre-registered plan"
    if re.match(r"^research/plan\d+[^/]*\.py$", low) or re.match(r"^research/live\d+[^/]*\.py$", low):
        return "frozen research code"
    return None


def diff_paths(diff):
    """(paths, problems): every path a unified diff could touch, and anything about it that is refused outright."""
    paths, problems = [], []

    def add(raw):
        raw = raw.rstrip("\n").split("\t", 1)[0].strip()
        if raw == "/dev/null" or not raw:
            return
        if raw.startswith('"'):
            problems.append("quoted path in the diff: " + raw[:80]); return
        if raw[:2] in ("a/", "b/"):
            raw = raw[2:]
        paths.append(raw)

    for line in (diff or "").splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            if '"' in rest:
                problems.append("quoted path in the diff"); continue
            m = re.match(r"^a/(.+) b/(.+)$", rest)
            if m:
                add("a/" + m.group(1)); add("b/" + m.group(2))
            else:
                problems.append("unreadable diff header: " + rest[:80])
        elif line.startswith("--- ") or line.startswith("+++ "):
            add(line[4:])
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            add(line.split(" ", 2)[2])
        elif line.startswith(("deleted file mode", "old mode", "new mode")):
            problems.append("deletes a file or changes a file mode: " + line.strip())
        elif line.startswith("new file mode") and not line.strip().endswith(("100644",)):
            problems.append("new file with an unusual mode: " + line.strip())
        elif line.startswith(("GIT binary patch", "Binary files")):
            problems.append("binary patch")
    if not paths:
        problems.append("the diff names no file")
    return sorted(set(paths)), problems


def check_diff(diff):
    """List of reasons to refuse a diff (empty = allowed)."""
    paths, problems = diff_paths(diff)
    out = list(problems)
    for p in paths:
        why = protected(p)
        if why:
            out.append("%s: %s" % (p, why))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Redaction: nothing that looks like a key, a token or an e-mail address goes to the model, an issue or a file.
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"(?i)\b(authorization|api[_-]?key|access[_-]?key|secret|token|password|passwd|private[_-]?key)"
               r"(\s*[:=]\s*|\s+)['\"]?[^\s'\",;]{6,}"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
)


def _long_mixed(m):
    s = m.group(0)
    if re.search(r"[a-z]", s) and re.search(r"[A-Z]", s) and re.search(r"[0-9]", s):
        return "[REDACTED]"
    return s


def redact(text):
    if not text:
        return text or ""
    text = str(text)
    for name in ("NVIDIA_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(name)
        if v and len(v) >= 6:
            text = text.replace(v, "[REDACTED]")
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    # long random-looking strings (mixed case and digits); git hashes are lower-case hex and stay readable
    return re.sub(r"[A-Za-z0-9+/_\-]{32,}={0,2}", _long_mixed, text)


# ---------------------------------------------------------------------------------------------------------------
# Small helpers (tests replace run, now, http_get and http_post)
def now():
    return datetime.now(timezone.utc)


def _clean_env():
    """The environment for gh and git: the tokens gh needs, nothing else secret."""
    env = dict(os.environ)
    env.pop("NVIDIA_API_KEY", None)
    return env


def run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    """(returncode, stdout, stderr). Commands are never printed (a push carries an auth header)."""
    try:
        r = subprocess.run(cmd, cwd=cwd or ROOT, env=env if env is not None else _clean_env(), input=input_text,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ss" % timeout
    except OSError as e:
        return 127, "", str(e)


def gh(args, **kw):
    return run(["gh"] + list(args), **kw)


def gh_json(args, default=None):
    rc, out, err = gh(args)
    if rc != 0:
        raise RuntimeError("gh %s failed: %s" % (args[0] if args else "", redact(err.strip())[:300]))
    try:
        return json.loads(out or "null")
    except ValueError:
        return default


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_time(s):
    if not s:
        return None
    try:
        s = str(s).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def status_path(name):
    """A file under ops/status/; refuses anything else (this tool writes nowhere else on main)."""
    p = os.path.abspath(os.path.join(STATUS_DIR, name))
    if os.path.commonpath([p, os.path.abspath(STATUS_DIR)]) != os.path.abspath(STATUS_DIR):
        raise ValueError("refusing to write outside ops/status: " + name)
    return p


def write_status(name, data):
    p = status_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        if isinstance(data, str):
            f.write(redact(data))
        else:
            f.write(redact(json.dumps(data, indent=1, sort_keys=True)) + "\n")
    os.replace(tmp, p)


def read_status(name, default=None):
    try:
        with open(status_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def kill_present():
    """A KILL file (any case, any ending) in the repository stops rerun and fix too, as on the PC."""
    try:
        return any(n.upper().startswith("KILL") for n in os.listdir(ROOT))
    except OSError:
        return True


# ---------------------------------------------------------------------------------------------------------------
# Cron schedules
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _field(spec, lo, hi, dow=False):
    vals = set()
    for part in spec.split(","):
        step, stepped = 1, "/" in part
        if stepped:
            part, s = part.split("/", 1); step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = [int(x) for x in part.split("-", 1)]
        else:
            a = b = int(part)
            if stepped:
                b = hi
        for v in range(a, b + 1, step):
            vals.add(0 if dow and v == 7 else v)
    return vals


def cron_minutes(expr, days=14):
    """Fire times (minutes since a fixed Monday 00:00 UTC) of one five-field cron line over `days` days."""
    f = expr.split()
    if len(f) != 5:
        raise ValueError("not a five-field cron line: " + expr)
    mins, hours, doms, mons, dows = [_field(x, lo, hi, i == 4) for i, (x, (lo, hi)) in enumerate(zip(f, _RANGES))]
    dom_star, dow_star = f[2] == "*", f[4] == "*"
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)   # a Monday
    out = []
    for d in range(days):
        day = start + timedelta(days=d)
        if day.month not in mons:
            continue
        dow = (day.weekday() + 1) % 7
        if dom_star or dow_star:
            ok = day.day in doms and dow in dows
        else:
            ok = day.day in doms or dow in dows
        if not ok:
            continue
        for h in sorted(hours):
            for m in sorted(mins):
                out.append(d * 1440 + h * 60 + m)
    return out


def max_gap_minutes(crons):
    """The longest wait between two scheduled starts (minutes), or None without a schedule."""
    times = sorted(set(t for c in crons for t in cron_minutes(c)))
    if len(times) < 2:
        return None
    return max(b - a for a, b in zip(times, times[1:]))


def limit_minutes(gap):
    """How old the latest run may be: the longest scheduled gap plus a grace for GitHub's late or skipped starts."""
    if gap is None:
        return None
    return gap + max(120, min(gap, 360))


def read_workflows(folder=None):
    folder = folder or WORKFLOW_DIR
    out = []
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not n.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(folder, n), encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"^name:\s*(.+?)\s*$", text, re.M)
        crons = re.findall(r"""^\s*-\s*cron:\s*["']([^"']+)["']""", text, re.M)
        out.append(dict(file=n, name=(m.group(1).strip("\"'") if m else n), crons=crons,
                        dispatch="workflow_dispatch" in text, workflow_run="workflow_run" in text))
    return out


# ---------------------------------------------------------------------------------------------------------------
# check
def _run_summary(r):
    return dict(id=r.get("databaseId"), status=r.get("status"), conclusion=r.get("conclusion") or None,
                created_at=r.get("createdAt"), event=r.get("event"), attempt=r.get("attempt") or 1,
                url=r.get("url"), branch=r.get("headBranch"), title=redact(r.get("displayTitle") or "")[:120])


def judge_workflow(wf, runs, t):
    """One status.json workflow row from the workflow's file facts and its newest runs (newest first)."""
    gap = max_gap_minutes(wf["crons"]) if wf["crons"] else None
    lim = limit_minutes(gap)
    row = dict(file=wf["file"], name=wf["name"], schedule=wf["crons"], expected_max_gap_minutes=gap,
               limit_minutes=lim, latest=None, latest_completed=None, age_minutes=None, state="unknown", problem=None)
    if runs is None:
        row["state"], row["problem"] = "unknown", "could not list its runs"
        return row
    runs = sorted(runs, key=lambda r: r.get("createdAt") or "", reverse=True)
    if not runs:
        row["state"] = "no-runs" if lim else "manual-only"
        if lim:
            row["problem"] = "scheduled but has never run"
        return row
    latest = runs[0]
    row["latest"] = _run_summary(latest)
    created = parse_time(latest.get("createdAt"))
    age = int((t - created).total_seconds() // 60) if created else None
    row["age_minutes"] = age
    done = [r for r in runs if r.get("status") == "completed"]
    last = done[0] if done else None
    row["latest_completed"] = _run_summary(last) if last else None
    if last and last.get("conclusion") in FAILED:
        row["state"] = "failed"
        row["problem"] = "latest finished run %s (%s)" % (last.get("conclusion"), last.get("url") or last.get("databaseId"))
    elif lim is not None and age is not None and age > lim:
        row["state"] = "stale"
        row["problem"] = "no run for %.1f h (schedule allows %.1f h)" % (age / 60.0, lim / 60.0)
    elif latest.get("status") != "completed":
        row["state"] = "running"
    else:
        row["state"] = "ok" if lim is not None else "manual-only"
    return row


def git_newest(path):
    rc, out, err = run(["git", "log", "-1", "--format=%cI", "--", path], timeout=120)
    return parse_time(out.strip()) if rc == 0 and out.strip() else None


def judge_data(spec, newest, t, root=None):
    path, lim, frm, until, done_file = spec
    row = dict(path=path, newest_commit_at=iso(newest), age_hours=None, limit_hours=lim, state="info", problem=None)
    if newest:
        row["age_hours"] = round((t - newest).total_seconds() / 3600.0, 1)
    if lim is None:
        return row
    if done_file and os.path.exists(os.path.join(root or ROOT, done_file)):
        row["state"] = "finished"; return row
    if (frm and t < parse_time(frm)) or (until and t > parse_time(until)):
        row["state"] = "inactive"; return row
    if newest is None:
        row["state"], row["problem"] = "missing", "%s has no commit" % path
    elif row["age_hours"] > lim:
        row["state"], row["problem"] = "stale", "%s last committed %.1f h ago (limit %d h)" % (path, row["age_hours"], lim)
    else:
        row["state"] = "ok"
    return row


def check():
    t = now()
    st = dict(schema=SCHEMA, generated_at=iso(t), generated_at_la_paz=t.astimezone(LA_PAZ).strftime("%Y-%m-%d %H:%M"),
              repository=os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPO") or "",
              key_present=bool(os.environ.get("NVIDIA_API_KEY")), workflows=[], data=[], problems=[], errors=[],
              ai=dict(used=False, task=None, model=None, note=None), note="Reads GitHub only; the PC is not reachable from here.")
    for wf in read_workflows():
        try:
            runs = gh_json(["run", "list", "--workflow", wf["file"], "--limit", "5", "--json",
                            "databaseId,status,conclusion,createdAt,event,attempt,url,headBranch,displayTitle"], [])
        except RuntimeError as e:
            st["errors"].append(redact(str(e))); runs = None
        st["workflows"].append(judge_workflow(wf, runs, t))
    for spec in DATA:
        st["data"].append(judge_data(spec, git_newest(spec[0]), t))
    st["problems"] = [w["file"] + ": " + w["problem"] for w in st["workflows"] if w["problem"]] + \
                     [d["problem"] for d in st["data"] if d["problem"]]
    write_status("status.json", st)
    write_status("status.md", status_md(st))
    return st


def status_md(st, report_text=None):
    lines = ["# Backup AI status", "", "Generated %s La Paz (%s UTC). Reads GitHub only; the PC is not reachable from here."
             % (st["generated_at_la_paz"], st["generated_at"]), ""]
    if not st.get("key_present"):
        lines += ["**NVIDIA_API_KEY is missing:** non-AI status check only (add it as a repository secret).", ""]
    lines += ["Problems: %d" % len(st["problems"])] + ["- " + p for p in st["problems"]] + [""]
    lines += ["| Workflow | State | Age (h) | Limit (h) |", "|---|---|---|---|"]
    for w in st["workflows"]:
        lines.append("| %s | %s | %s | %s |" % (w["file"], w["state"],
                     "%.1f" % (w["age_minutes"] / 60.0) if w["age_minutes"] is not None else "-",
                     "%.1f" % (w["limit_minutes"] / 60.0) if w["limit_minutes"] else "-"))
    lines += ["", "| Data | State | Newest commit | Age (h) | Limit (h) |", "|---|---|---|---|---|"]
    for d in st["data"]:
        lines.append("| %s | %s | %s | %s | %s |" % (d["path"], d["state"], d["newest_commit_at"] or "-",
                     d["age_hours"] if d["age_hours"] is not None else "-", d["limit_hours"] or "-"))
    if st.get("errors"):
        lines += ["", "Errors while checking:"] + ["- " + e for e in st["errors"]]
    if report_text:
        model = st.get("ai", {}).get("model")
        lines += ["", "## Report" + (" (model: %s; advice only)" % model if model else " (no AI)"), "", report_text]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------------
# The NVIDIA API: model choice, calls, budget
PREFERENCES = {
    # a small, fast instruct model for the routine summary
    "check-summary": dict(ids=["meta/llama-3.1-8b-instruct", "meta/llama-3.2-3b-instruct",
                               "mistralai/mistral-7b-instruct-v0.3", "google/gemma-2-9b-it",
                               "microsoft/phi-3-mini-128k-instruct", "nvidia/llama-3.1-nemotron-nano-8b-v1"],
                          pattern=r"(llama-3\.\d+-(1b|3b|8b)-instruct|mistral-7b-instruct|gemma-\d+-\d+b-it|phi-3|phi-4-mini|nemotron-nano)"),
    # a strong reasoning model for failure analysis
    "diagnose": dict(ids=["deepseek-ai/deepseek-r1", "nvidia/llama-3.3-nemotron-super-49b-v1.5",
                          "nvidia/llama-3.3-nemotron-super-49b-v1", "nvidia/llama-3.1-nemotron-ultra-253b-v1",
                          "qwen/qwq-32b", "meta/llama-3.3-70b-instruct", "meta/llama-3.1-405b-instruct"],
                     pattern=r"(deepseek-r1|nemotron-(super|ultra)|qwq|qwen3-235b|llama-3\.\d+-(70b|405b)-instruct)"),
    # a code-specialised model for diff writing
    "code-fix": dict(ids=["qwen/qwen3-coder-480b-a35b-instruct", "qwen/qwen2.5-coder-32b-instruct",
                          "mistralai/codestral-22b-instruct-v0.1", "deepseek-ai/deepseek-coder-6.7b-instruct",
                          "meta/codellama-70b"],
                     pattern=r"(coder|codestral|codellama|starcoder|codegemma)"),
}
MAX_TOKENS = {"check-summary": 1200, "diagnose": 2000, "code-fix": 3000}


def pick(task, available):
    """The model id for a task from the ids the API lists: the first preferred id that is listed, else the first listed
    id matching the tier's family pattern, else None. Nothing is trusted until the API lists it."""
    pref = PREFERENCES[task]
    avail = [a for a in (available or []) if isinstance(a, str)]
    for mid in pref["ids"]:
        if mid in avail:
            return mid
    pat = re.compile(pref["pattern"], re.I)
    for mid in sorted(avail):
        if pat.search(mid):
            return mid
    return None


def http_get(url, headers, timeout):
    import requests
    r = requests.get(url, headers=headers, timeout=timeout)
    return r.status_code, r.headers, r.text


def http_post(url, headers, body, timeout):
    import requests
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    return r.status_code, r.headers, r.text


class AI(object):
    """The model client. Never stores the key anywhere but in the request header."""

    def __init__(self, key=None, base=NVIDIA_BASE, max_calls=MAX_AI_CALLS, sleep=time.sleep):
        self._key = key if key is not None else os.environ.get("NVIDIA_API_KEY", "")
        self.base, self.max_calls, self.calls, self.sleep = base.rstrip("/"), max_calls, 0, sleep
        self._models, self.used = None, []

    def available(self):
        return bool(self._key)

    def _headers(self):
        return {"Authorization": "Bearer " + self._key, "Accept": "application/json",
                "Content-Type": "application/json", "User-Agent": USER_AGENT}

    def _request(self, fn, *args):
        """fn(...) -> (status, headers, text); up to 4 tries on 429 and 5xx, with backoff."""
        last = None
        for i in range(4):
            try:
                code, headers, text = fn(*args)
            except Exception as e:  # network errors: retried
                code, headers, text = 0, {}, type(e).__name__
            if code == 200:
                return text
            last = code
            if code not in (0, 429) and not 500 <= code < 600:
                break
            wait = 2 ** (i + 1)
            try:
                wait = max(wait, min(60, int((headers or {}).get("Retry-After", 0))))
            except (TypeError, ValueError):
                pass
            if i < 3:
                self.sleep(wait)
        raise RuntimeError("NVIDIA API answered HTTP %s" % last)

    def models(self):
        if self._models is None:
            text = self._request(http_get, self.base + "/models", self._headers(), 30)
            data = json.loads(text).get("data") or []
            self._models = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
        return self._models

    def ask(self, task, system, user):
        """(model, text). Raises RuntimeError when no model fits, the budget is spent or the API fails."""
        if not self._key:
            raise RuntimeError("NVIDIA_API_KEY is missing")
        if self.calls >= self.max_calls:
            raise RuntimeError("AI call budget (%d) spent" % self.max_calls)
        model = pick(task, self.models())
        if not model:
            raise RuntimeError("no model for %s is listed by the API" % task)
        self.calls += 1
        body = dict(model=model, temperature=0.2, top_p=0.9, max_tokens=MAX_TOKENS[task], stream=False,
                    messages=[dict(role="system", content=SYSTEM_RULES + "\n\n" + system),
                              dict(role="user", content=redact(user))])
        text = self._request(http_post, self.base + "/chat/completions", self._headers(), body, 180)
        msg = json.loads(text)["choices"][0]["message"].get("content") or ""
        msg = re.sub(r"(?s)<think>.*?</think>", "", msg).strip()
        self.used.append(dict(task=task, model=model))
        return model, redact(msg)


SYSTEM_RULES = (
    "You are the backup operator for a small research and paper-trading project on GitHub. Your output is advice only: "
    "a human or another assistant reviews everything before it is used. Hard rules you must follow: never suggest "
    "loosening any limit, lock, threshold, kill switch, stop date, pre-registered plan or rule; never suggest anything "
    "involving real money, order placing, account keys or the files live.py, strategy.py, config.py, gate.py, core.py; "
    "never suggest editing frozen research code, research/results, workflows or CLAUDE.md; never ask for or repeat "
    "secrets. If a fix would need any of those, say so and stop. Plain English, short, no hype.")


# ---------------------------------------------------------------------------------------------------------------
# GitHub issue (one, labelled backup-ai)
def issue_action(n_problems, open_issues):
    """(action, number, extra numbers to close): create, update, close or none."""
    nums = sorted(i["number"] for i in (open_issues or []))
    if n_problems:
        return ("update", nums[0], nums[1:]) if nums else ("create", None, [])
    return ("close", nums[0], nums[1:]) if nums else ("none", None, [])


def issue_title(st):
    n = len(st["problems"])
    return "Backup AI: %s %d problem%s" % (st["generated_at_la_paz"][:10], n, "" if n == 1 else "s")


def ensure_label():
    gh(["label", "create", LABEL, "--color", "B60205", "--description", "Opened by the backup AI operator", "--force"])


def _body_file(text):
    fd, p = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(redact(text)[:60000])
    return p


def sync_issue(st, report_text):
    try:
        issues = gh_json(["issue", "list", "--label", LABEL, "--state", "open", "--json", "number,title"], []) or []
    except RuntimeError as e:
        st["errors"].append(redact(str(e))); return "error"
    action, num, extra = issue_action(len(st["problems"]), issues)
    body = status_md(st, report_text) + "\n---\nOpened by ops/backup_ai.py (GitHub Actions). Advice only; it changes no " \
        "rule, limit or lock and never touches real money. It closes this issue itself when everything is green.\n"
    if action in ("create", "update"):
        ensure_label()
        p = _body_file(body)
        try:
            if action == "create":
                gh(["issue", "create", "--title", issue_title(st), "--label", LABEL, "--body-file", p])
            else:
                gh(["issue", "edit", str(num), "--title", issue_title(st), "--body-file", p])
        finally:
            os.unlink(p)
    elif action == "close":
        gh(["issue", "close", str(num), "--comment", "All workflows and data are within their limits (%s La Paz)."
            % st["generated_at_la_paz"]])
    for n in extra:
        gh(["issue", "close", str(n), "--comment", "Duplicate of #%s." % num])
    return action


def failed_log(run_id, lines=200):
    rc, out, err = gh(["run", "view", str(run_id), "--log-failed"], timeout=180)
    text = out if rc == 0 else err
    return redact("\n".join(text.splitlines()[-lines:]))


def report(ai=None):
    st = read_status("status.json") or check()
    ai = ai or AI()
    failed = [w for w in st["workflows"] if w["state"] == "failed"][:3]
    logs = {}
    for w in failed:
        rid = (w.get("latest_completed") or {}).get("id")
        if rid:
            logs[w["file"]] = failed_log(rid)
    text = None
    if not ai.available():
        text = "NVIDIA_API_KEY is missing, so there is no AI report: the table above is the non-AI status check. " \
               "Add the key as a repository secret named NVIDIA_API_KEY."
        st["ai"] = dict(used=False, task=None, model=None, note="key missing")
    else:
        task = "diagnose" if st["problems"] else "check-summary"
        prompt = ("Status of the project's GitHub Actions jobs (JSON):\n%s\n\nLast lines of each failed run's log:\n%s\n\n"
                  "Write a short plain-English report: what works, what failed or is stale, the likely cause, and one "
                  "suggested next step for each problem. The user's PC is not visible from here; say so if a problem "
                  "may be on the PC." % (json.dumps(_brief(st), indent=1)[:20000],
                                         "\n\n".join("== %s\n%s" % (k, v) for k, v in logs.items())[:24000] or "(none)"))
        try:
            model, text = ai.ask(task, "Write the status report.", prompt)
            st["ai"] = dict(used=True, task=task, model=model, note=None)
        except (RuntimeError, ValueError, KeyError) as e:
            text = "No AI report (%s). The table above is the non-AI status check." % redact(str(e))
            st["ai"] = dict(used=False, task=task, model=None, note=redact(str(e)))
    st["issue"] = sync_issue(st, text)
    write_status("status.json", st)
    write_status("status.md", status_md(st, text))
    write_status("report.md", text + "\n")
    return st, text


def _brief(st):
    return dict(generated_at=st["generated_at"], problems=st["problems"],
                workflows=[dict(file=w["file"], state=w["state"], age_minutes=w["age_minutes"],
                                limit_minutes=w["limit_minutes"], problem=w["problem"]) for w in st["workflows"]],
                data=st["data"])


# ---------------------------------------------------------------------------------------------------------------
# rerun
def rerun_candidates(st, done, t):
    """Failed runs that may be re-run: allowlisted workflow, the newest run of its workflow, first attempt, recent, and
    never re-run before."""
    out = []
    seen = set(str(r.get("run_id")) for r in (done or []))
    for w in st["workflows"]:
        if w["file"] not in RERUN_ALLOW or w["state"] != "failed":
            continue
        last, latest = w.get("latest_completed") or {}, w.get("latest") or {}
        rid = last.get("id")
        if not rid or str(rid) in seen or latest.get("id") != rid or int(last.get("attempt") or 1) > 1:
            continue
        created = parse_time(last.get("created_at"))
        if created is None or (t - created) > timedelta(hours=RERUN_MAX_AGE_H):
            continue
        out.append(dict(workflow=w["file"], run_id=rid))
    return out


def rerun(st=None):
    st = st or read_status("status.json") or check()
    if kill_present():
        print("rerun: KILL file present, nothing re-run"); return []
    done = read_status("reruns.json", []) or []
    out = []
    for c in rerun_candidates(st, done, now()):
        rc, _o, err = gh(["run", "rerun", str(c["run_id"]), "--failed"])
        c.update(at=iso(now()), ok=(rc == 0), error=None if rc == 0 else redact(err.strip())[:300])
        done.append(c); out.append(c)
        write_status("reruns.json", done)   # recorded at once: never the same run twice, even if this run stops
    print("rerun: %d re-run(s)" % len(out))
    return out


# ---------------------------------------------------------------------------------------------------------------
# fix
CLAUDE_TRAILER = re.compile(r"^\s*co-authored-by:\s*claude\b", re.I | re.M)


def claude_active(t=None, ref=None):
    """True when a commit with Claude's co-author trailer reached main in the last 24 hours. Fails closed: if git
    cannot answer, Claude counts as active and no fix is proposed."""
    t = t or now()
    since = iso(t - timedelta(hours=24))
    for r in ([ref] if ref else ["origin/main", "main", "HEAD"]):
        rc, out, err = run(["git", "log", r, "--since=" + since, "--format=%cI%x1f%B%x1e"], timeout=120)
        if rc != 0:
            continue
        for rec in out.split("\x1e"):
            if "\x1f" not in rec:
                continue
            when, body = rec.split("\x1f", 1)
            dt = parse_time(when.strip())
            if dt and t - dt <= timedelta(hours=24) and CLAUDE_TRAILER.search(body):
                return True
        return False
    return True


_PATH_RE = re.compile(r"""(?:File ")([^"]+\.py)"|(?<![\w/.])((?:[\w\-]+/)*[\w\-]+\.(?:py|yml|json|txt|md))\b""")


def related_files(log, root=None, limit=6):
    """Repository files named in a failure log (traceback paths first), at most `limit`."""
    root = root or ROOT
    out = []
    for m in _PATH_RE.finditer(log or ""):
        p = (m.group(1) or m.group(2) or "").replace("\\", "/")
        if "site-packages" in p or "/lib/python" in p:
            continue
        cand = None
        if p.startswith("/"):
            parts = p.split("/")
            for i in range(len(parts)):
                rel = "/".join(parts[i:])
                if rel and os.path.isfile(os.path.join(root, rel)):
                    cand = rel; break
        elif os.path.isfile(os.path.join(root, p)):
            cand = posixpath.normpath(p)
        if cand and cand not in out:
            out.append(cand)
        if len(out) >= limit:
            break
    return out


def extract_diff(text):
    m = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", text or "", re.S)
    d = m.group(1) if m else (text or "")
    i = d.find("diff --git ")
    if i < 0:
        i = d.find("--- ")
    return (d[i:].rstrip() + "\n") if i >= 0 else ""


def open_fix_workflows():
    prs = gh_json(["pr", "list", "--state", "open", "--label", LABEL, "--json", "number,title,body,headRefName"], []) or []
    out = set()
    for p in prs:
        m = re.search(r"backup-ai-workflow:\s*(\S+)", p.get("body") or "")
        if m:
            out.add(m.group(1))
        m = re.search(r"\[([\w.\-]+\.ya?ml)\]", p.get("title") or "")
        if m:
            out.add(m.group(1))
    return out


def _test_env():
    """No token, key or Actions credential reaches the tests, which run the proposed code."""
    env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if any(s in ku for s in ("TOKEN", "KEY", "SECRET", "PASSWORD", "ACTIONS_")) or ku.startswith("GH_"):
            continue
        env[k] = v
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _auth_args():
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not tok:
        return []
    hdr = base64.b64encode(("x-access-token:" + tok).encode()).decode()
    return ["-c", "http.https://github.com/.extraheader=AUTHORIZATION: basic " + hdr]


def fix_candidates(st, attempted, open_wfs):
    out = []
    tried = set(str(a.get("run_id")) for a in (attempted or []))
    for w in st["workflows"]:
        rid = (w.get("latest_completed") or {}).get("id")
        if w["state"] != "failed" or not rid or str(rid) in tried or w["file"] in open_wfs:
            continue
        if w["file"] == "backup-ai.yml":
            continue
        out.append(dict(workflow=w["file"], run_id=rid))
    return out


def fix(st=None, ai=None):
    st = st or read_status("status.json") or check()
    ai = ai or AI()
    if kill_present():
        return "skipped: KILL file present"
    if not ai.available():
        return "skipped: NVIDIA_API_KEY is missing"
    if claude_active():
        return "skipped: Claude committed to main in the last 24 hours (or git could not tell)"
    try:
        open_wfs = open_fix_workflows()
    except RuntimeError as e:
        return "skipped: " + redact(str(e))
    attempted = read_status("fixes.json", []) or []
    cands = fix_candidates(st, attempted, open_wfs)
    if not cands:
        return "nothing to fix"
    c = cands[0]                       # one failing workflow at a time
    rec = dict(c, at=iso(now()), result=None, model=None)
    attempted.append(rec)
    write_status("fixes.json", attempted)   # never the same run twice
    try:
        rec["result"], rec["model"] = _propose(c, ai)
    except Exception as e:  # noqa: any failure ends this proposal, never the job
        rec["result"] = "failed: " + redact("%s: %s" % (type(e).__name__, e))[:300]
    write_status("fixes.json", attempted)
    return rec["result"]


def _propose(c, ai):
    log = failed_log(c["run_id"], 200)
    files = related_files(log)
    wf_rel = ".github/workflows/" + c["workflow"]
    if wf_rel not in files and os.path.isfile(os.path.join(ROOT, wf_rel)):
        files = files[:5] + [wf_rel]
    parts = []
    for rel in files[:6]:
        with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
            body = f.read()
        tag = "READ-ONLY (protected: %s)" % protected(rel) if protected(rel) else "editable"
        parts.append("=== %s [%s]\n%s%s" % (rel, tag, body[:12000], "\n... (truncated)" if len(body) > 12000 else ""))
    prompt = ("Workflow %s failed (run %s). Last lines of its log:\n%s\n\nRelevant files:\n%s\n\n"
              "Propose the smallest fix as a unified git diff (diff --git a/... b/... headers, paths relative to the "
              "repository root) in one ```diff block, editing only files marked editable. Before the block write one "
              "line starting CAUSE: with the cause in plain English. If the cause is outside the code (GitHub outage, "
              "network, a data source down) or a fix would need a protected file, answer NO_FIX and the cause only."
              % (c["workflow"], c["run_id"], log, "\n\n".join(parts)))
    model, answer = ai.ask("code-fix", "Write a minimal fix proposal.", prompt)
    m = re.search(r"CAUSE:\s*(.+)", answer)
    cause = (m.group(1).strip() if m else "not stated")[:200]
    if "NO_FIX" in answer and "diff --git" not in answer:
        return "no fix proposed: " + cause, model
    diff = extract_diff(answer)
    refused = check_diff(diff)
    if refused:
        return "refused: " + "; ".join(refused)[:400], model
    return _apply_and_open(c, diff, cause, model), model


def _apply_and_open(c, diff, cause, model):
    branch = "backup-ai/fix-%s" % c["run_id"]
    rc, out, _ = run(["git", "ls-remote", "--heads", "origin", branch], timeout=60)
    if rc == 0 and out.strip():
        return "branch %s already exists" % branch
    wt = tempfile.mkdtemp(prefix="backup_ai_fix_")
    os.rmdir(wt)
    rc, _o, err = run(["git", "worktree", "add", "-q", "-b", branch, wt, "HEAD"], timeout=180)
    if rc != 0:
        return "could not create a worktree: " + redact(err)[:200]
    try:
        pf = os.path.join(tempfile.mkdtemp(prefix="backup_ai_diff_"), "fix.diff")
        with open(pf, "w", encoding="utf-8", newline="\n") as f:
            f.write(diff)
        rc, _o, err = run(["git", "apply", "--check", "--recount", pf], cwd=wt)
        if rc != 0:
            return "diff does not apply: " + redact(err)[:300]
        rc, _o, err = run(["git", "apply", "--recount", pf], cwd=wt)
        if rc != 0:
            return "diff did not apply: " + redact(err)[:300]
        rc, out, _ = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=wt)
        changed = [l[3:].split(" -> ")[-1].strip('"') for l in out.splitlines() if l.strip()]
        bad = [p for p in changed if protected(p)]
        if bad or not changed:
            return "refused after apply: " + (", ".join(bad) or "no change")
        rc, tout, terr = run([sys.executable, os.path.join("tests", "run_all.py")], cwd=wt, env=_test_env(), timeout=540)
        test_tail = "\n".join((tout + terr).splitlines()[-40:])
        run(["git", "add", "-A"], cwd=wt)
        run(["git", "-c", "user.name=tradebot-backup-ai", "-c", "user.email=tradebot-runner@users.noreply.github.com",
             "commit", "-q", "-m", "Backup AI fix proposal for %s (run %s)\n\nUnreviewed; do not merge without review."
             % (c["workflow"], c["run_id"])], cwd=wt)
        rc, _o, err = run(["git"] + _auth_args() + ["push", "-q", "origin", "HEAD:refs/heads/" + branch], cwd=wt, timeout=180)
        if rc != 0:
            return "push failed: " + redact(err)[:200]
        body = ("<!-- backup-ai-workflow: %s -->\n**Do not merge without review.** Proposed by the backup AI operator "
                "(model %s) because Claude made no commit in the last 24 hours. It never merges anything itself.\n\n"
                "**Failing run:** %s (workflow %s)\n\n**Likely cause:** %s\n\n**Diff:**\n```diff\n%s```\n\n"
                "**Tests** (`python3 tests/run_all.py`, exit %s; test_ui.py skips without Playwright):\n```\n%s\n```\n\n"
                "Checked against the protected-path list in ops/backup_ai.py before it was applied.\n"
                % (c["workflow"], model, c["run_id"], c["workflow"], cause, diff[:30000], rc, test_tail))
        title = "Backup AI fix proposal: [%s] %s" % (c["workflow"], cause[:80])
        ensure_label()
        p = _body_file(body)
        try:
            rc2, out2, err2 = gh(["pr", "create", "--base", "main", "--head", branch, "--title", title,
                                  "--body-file", p, "--label", LABEL])
        finally:
            os.unlink(p)
        return ("pull request opened: " + out2.strip()) if rc2 == 0 else ("pull request failed: " + redact(err2)[:200])
    finally:
        run(["git", "worktree", "remove", "--force", wt], timeout=120)


# ---------------------------------------------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "all"
    if mode not in ("check", "report", "rerun", "fix", "all"):
        print(__doc__); return 2
    st = check()
    print("check: %d problem(s)%s" % (len(st["problems"]), "" if st["key_present"] else "; NVIDIA_API_KEY is missing"))
    for p in st["problems"]:
        print("  - " + p)
    if mode == "check":
        return 0
    ai = AI()
    if mode in ("report", "all"):
        st, _t = report(ai)
        print("report: issue %s; model %s" % (st.get("issue"), st["ai"].get("model") or "none"))
    if not ai.available():
        print("NVIDIA_API_KEY is missing: rerun and fix skipped (non-AI status check only)")
        return 0
    if mode in ("rerun", "all"):
        rerun(st)
    if mode in ("fix", "all"):
        print("fix: " + fix(st, ai))
    return 0


if __name__ == "__main__":
    sys.exit(main())
