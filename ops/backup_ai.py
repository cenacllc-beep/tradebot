"""Backup AI operator (added 2026-11-26 at the user's request; ops/README.md). Runs on GitHub Actions
(.github/workflows/backup-ai.yml, once switched on; repository copy cloud/workflows/backup-ai.yml) and watches the
repository's own scheduled jobs when Claude is not around.

    python3 ops/backup_ai.py check | report | rerun | fix | all          (job "operate")
    python3 ops/backup_ai.py status-hash DIR                               (job "operate", output status_sha256)
    python3 ops/backup_ai.py push-status DIR STATUS_SHA256                 (job "status")
    python3 ops/backup_ai.py test-proposal DIR RESULT_DIR DIFF_SHA256 META_SHA256   (job "test")
    python3 ops/backup_ai.py publish DIR RESULT_DIR DIFF_SHA256 META_SHA256         (job "publish")

The hashes are job outputs of "operate" (written to GITHUB_OUTPUT by this file itself); the later jobs check the
downloaded artifacts against them and never against hashes stored inside an artifact, because code run in "test" holds
the runner's artifact credential and could upload artifacts of its own.

check   deterministic, no AI: the latest runs on main of every workflow in .github/workflows against the schedule in
        its cron lines, and the age of the research data the jobs commit. Writes ops/status/status.json and status.md.
report  asks an NVIDIA-hosted model (OpenAI-compatible API) for a plain-English report, then opens, updates or closes ONE
        GitHub issue labelled backup-ai, so GitHub e-mails the user when something is wrong.
rerun   no AI: re-runs a failed run once, only for an allowlist of research and paper logging workflows; never twice.
fix     only PROPOSES: when no commit carrying Claude's co-author trailer reached main in the last 24 hours, asks the
        model for a minimal diff for one failing scheduled or hand-started workflow, refuses any path outside the
        allowlist or on the deny list, and writes the diff and its metadata to a folder (uploaded as an artifact).
        No proposed code ever runs in this job, which holds the NVIDIA key and a GitHub token.
test-proposal  the job with no token, no secret and `permissions: {}`: re-checks the diff, applies it, runs the tests
        (hard limit 300 s) and fails unless the files changed afterwards are exactly the diff's own files.
publish the job that may push a branch and open a pull request: runs NO proposed code. Re-checks the diff, applies it
        to a fresh checkout, stages exactly the diff's paths, commits without hooks, pushes backup-ai/fix-<run id>
        and opens a pull request "Do not merge without review". It never merges.
push-status  copies the status files into ops/status/ and pushes ONE commit to main touching only ops/status/
        (refused otherwise).

Same permissions as Claude minus anything to do with real money: it never imports or runs the order-placing module,
never opens the bot's databases, and never writes outside ops/status/ on main. Its output is advice only.
Python 3.8 syntax; standard library plus requests (only for the NVIDIA API). The API key comes from the environment
variable NVIDIA_API_KEY and is never printed, logged or written. Without it, check, rerun and the issue still run and
the report says the key is missing."""
import ast, base64, hashlib, json, os, posixpath, re, shutil, signal, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_DIR = os.path.join(ROOT, "ops", "status")
WORKFLOW_DIR = os.path.join(ROOT, ".github", "workflows")
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
USER_AGENT = "tradebot-paper-research/1.0"
LABEL = "backup-ai"
MAX_AI_CALLS = 6
AI_TOTAL_SECONDS = 360         # all model calls of one run together (requests, retries and waits)
AI_REQUEST_SECONDS = 90        # one HTTP request to the model
TEST_SECONDS = 300             # the test suite on a proposed fix
LA_PAZ = timezone(timedelta(hours=-4))
SCHEMA = 1
RUNNER_NAME = "tradebot-runner"
RUNNER_EMAIL = "tradebot-runner@users.noreply.github.com"
FIX_EVENTS = ("schedule", "workflow_dispatch")
NOHOOKS = ["-c", "core.hooksPath=/dev/null"]

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
# What a fix proposal may change. First an ALLOWLIST (presentation, monitoring and non-frozen research helpers), then
# the deny list as a second check; both are hard-coded and tests/test_backup_ai.py checks them.
EDITABLE_FILES = ("freshness.py", "check.py", "marks.py", "learn.py", "dashboard.py", "dashboard_assets.py",
                  "control_view.py", "account_view.py")
EDITABLE_PATTERNS = (r"^tbcommon/(?:[a-z0-9_]+/)*[a-z0-9_]+\.py$", r"^research/[a-z0-9_]+\.py$")
NOT_EDITABLE_RESEARCH = (r"^research/plan[^/]*\.py$", r"^research/live[^/]*\.py$", r"^research/nov11\.py$",
                         r"^research/backtest[^/]*\.py$", r"^research/lip\.py$", r"^research/fetch\.py$",
                         r"^research/placebo\.py$")

PROTECTED_FILES = ("live.py", "live.db", "paper.db", "config.py", "strategy.py", "weather.py", "nws.py", "gate.py",
                   "core.py", "claude.md", "run.bat", "ops/backup_ai.py", "tests/test_backup_ai.py",
                   "tests/run_all.py", ".gitignore", "cloud/repo.gitignore", ".gitattributes", ".gitmodules",
                   "pyproject.toml", "setup.cfg", "setup.py", "kalshi.py", "stationfc.py", "shadow.py", "main.py",
                   "backup.py", "jobs.py", "export.py", "joblock.py", "scan_window.py", "audit.py")
PROTECTED_DIRS = (".claude/", ".github/", "cloud/workflows/", "agents/", "tasks/", "backups/", "trial/",
                  "research/results/", "research/data/", "ops/", "tests/", ".git/", ".kalshi/")
PROTECTED_ANYWHERE = ("live.py", "live.db", "paper.db")     # by file name, in any folder
PROTECTED_NAMES = ("sitecustomize.py", "usercustomize.py", "conftest.py", "__init__.py")   # run on import or by tools
PROTECTED_SUFFIXES = (".cmd", ".ps1", ".bat", ".pem", ".key", ".pth", ".sh")


def live_closure(root=None):
    """The repository modules live.py imports, directly or through each other (paths relative to root, lower case),
    found with ast. None when live.py cannot be read or parsed (callers then refuse every path: fail closed)."""
    root = root or ROOT
    seen, todo = set(), ["live.py"]
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=rel)
        except (OSError, SyntaxError, ValueError):
            if rel == "live.py":
                return None
            continue
        pkg = posixpath.dirname(rel)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg
                    for _ in range(node.level - 1):
                        base = posixpath.dirname(base)
                    mod = ".".join(x for x in (base.replace("/", "."), node.module or "") if x)
                else:
                    mod = node.module or ""
                if mod:
                    names.append(mod)
                names += [mod + "." + a.name if mod else a.name for a in node.names if a.name != "*"]
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if fname in ("import_module", "__import__"):
                    names.append(node.args[0].value)
        for name in names:
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                p = "/".join(parts[:i])
                for cand in (p + ".py", p + "/__init__.py"):
                    if os.path.isfile(os.path.join(root, cand)):
                        todo.append(cand)
    return sorted(x.lower() for x in seen)


_CLOSURE = {}


def _live_closure_cached():
    if ROOT not in _CLOSURE:
        _CLOSURE[ROOT] = live_closure(ROOT)
    return _CLOSURE[ROOT]


def _norm(path):
    """(normalised lower-case path, reason) for a path in a diff; reason is set when it is refused outright."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        return None, "empty or invalid path"
    p = path.strip().replace("\\", "/")
    if p.startswith("/") or re.match(r"^[a-zA-Z]:", p) or p.startswith("~"):
        return None, "absolute path"
    if any(part == ".." for part in p.split("/")):
        return None, "path leaves the repository"
    p = posixpath.normpath(p)
    while p.startswith("./"):
        p = p[2:]
    if p in (".", "") or p.startswith("../"):
        return None, "path leaves the repository"
    return p.lower(), None      # the PC is Windows: Live.py and live.py are the same file there


def editable(path):
    """True when a normalised lower-case path is on the allowlist."""
    if path in EDITABLE_FILES:
        return True
    if any(re.match(r, path) for r in NOT_EDITABLE_RESEARCH):
        return False
    return any(re.match(r, path) for r in EDITABLE_PATTERNS)


def protected(path):
    """The reason a path may not be changed by a fix proposal, or None. Fails closed: anything odd is protected."""
    low, why = _norm(path)
    if why:
        return why
    base = low.rsplit("/", 1)[-1]
    if low in PROTECTED_FILES:
        return "protected file"
    for d in PROTECTED_DIRS:
        if low.startswith(d) or low + "/" == d:
            return "protected folder " + d
    if any(part.startswith(".") for part in low.split("/")):
        return "dotfile or dot folder"
    for name in PROTECTED_ANYWHERE:
        if base == name or base.startswith(name + "-") or base.startswith(name + "."):
            return "protected file name"
    if base in PROTECTED_NAMES:
        return "runs on import"
    if "frozen" in base:
        return "frozen file"
    if base.endswith(PROTECTED_SUFFIXES):
        return "protected file type"
    if re.match(r"^research/plan[^/]*\.md$", low):
        return "pre-registered plan"
    if re.match(r"^research/plan\d+[^/]*\.py$", low) or re.match(r"^research/live\d+[^/]*\.py$", low):
        return "frozen research code"
    closure = _live_closure_cached()
    if closure is None:
        return "live.py's imports could not be read (fail closed)"
    if low in closure:
        return "imported by live.py"
    if not editable(low):
        return "not on the list of files a fix may edit"
    return None


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_INDEX = re.compile(r"^index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}( 100644)?$")


def _git_header_path(rest):
    """X from the rest of a `diff --git a/X b/X` line, or None unless both sides name the same X."""
    n = len(rest) - 5
    if n < 2 or n % 2:
        return None
    x = rest[2:2 + n // 2]
    return x if rest == "a/%s b/%s" % (x, x) else None


def diff_paths(diff):
    """(paths, problems): the files a diff changes, and anything about it that is refused outright. Strict, so that
    what this reads is what `git apply` (at -p1) does: every file section starts with `diff --git a/X b/X` (the same X
    on both sides); its `---` / `+++` lines must be exactly `a/X` / `b/X` (`/dev/null` there means a new or deleted
    file, refused); hunks are counted, so a `--- ` line inside a hunk is a removed line, and anything outside a hunk
    other than these headers and `index` lines is refused. New, deleted, renamed and copied files, mode changes and
    binary patches are refused."""
    paths, problems = [], []
    cur, old_n, new_n, seen_minus, seen_plus = None, 0, 0, False, False
    lines = (diff or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if line.endswith("\r"):
            problems.append("carriage return in the diff"); line = line[:-1]
        if old_n > 0 or new_n > 0:                       # inside a hunk
            c = line[:1]
            if c in (" ", ""):
                old_n -= 1; new_n -= 1
            elif c == "-":
                old_n -= 1
            elif c == "+":
                new_n -= 1
            elif c == "\\":
                continue
            else:
                problems.append("malformed hunk (line counts do not match): " + line[:80])
                old_n = new_n = 0
                continue
            if old_n < 0 or new_n < 0:
                problems.append("malformed hunk (line counts do not match)")
                old_n = new_n = 0
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("diff --git "):
            if cur is not None and not (seen_minus and seen_plus):
                problems.append("file section without --- and +++ lines: " + cur[:80])
            rest = line[len("diff --git "):]
            if '"' in rest or "\t" in rest:
                problems.append("quoted path in the diff"); cur = ""
            else:
                x = _git_header_path(rest)
                if x is None:
                    problems.append("diff --git header must name the same a/X and b/X: " + rest[:80]); cur = ""
                else:
                    cur = x
                    if x in paths:
                        problems.append("file appears twice in the diff: " + x[:80])
                    paths.append(x)
            seen_minus = seen_plus = False
            continue
        if cur is None:
            if line.strip():
                problems.append("text before the first diff --git header: " + line[:80])
            continue
        if line.startswith("--- "):
            raw = line[4:]
            if raw == "/dev/null":
                problems.append("new file (--- /dev/null) refused: " + cur[:80])
            elif raw != "a/" + cur:
                problems.append("--- line does not name a/%s: %s" % (cur[:80], raw[:80]))
            seen_minus = True
        elif line.startswith("+++ "):
            raw = line[4:]
            if raw == "/dev/null":
                problems.append("deleted file (+++ /dev/null) refused: " + cur[:80])
            elif raw != "b/" + cur:
                problems.append("+++ line does not name b/%s: %s" % (cur[:80], raw[:80]))
            seen_plus = True
        elif line.startswith("@@"):
            m = _HUNK.match(line)
            if not m or not (seen_minus and seen_plus):
                problems.append("hunk without a valid header or before --- and +++: " + line[:80]); continue
            old_n = int(m.group(2)) if m.group(2) is not None else 1
            new_n = int(m.group(4)) if m.group(4) is not None else 1
        elif line.startswith("new file mode"):
            problems.append("new file refused: " + cur[:80])
        elif line.startswith(("deleted file mode", "old mode", "new mode", "similarity index", "dissimilarity index",
                              "rename from", "rename to", "copy from", "copy to")):
            problems.append("deletes, renames or copies a file or changes a file mode: " + line.strip()[:80])
        elif line.startswith(("GIT binary patch", "Binary files")):
            problems.append("binary patch")
        elif _INDEX.match(line) or not line.strip():
            continue
        else:
            problems.append("unexpected line outside a hunk: " + line[:80])
    if old_n > 0 or new_n > 0:
        problems.append("the diff ends inside a hunk")
    if cur is not None and not (seen_minus and seen_plus):
        problems.append("file section without --- and +++ lines: " + (cur or "?")[:80])
    if not paths:
        problems.append("the diff has no diff --git header and names no file")
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


def kill_present(root=None):
    """A KILL file (any case, any ending) in the repository stops rerun and fix too, as on the PC."""
    try:
        return any(n.upper().startswith("KILL") for n in os.listdir(root or ROOT))
    except OSError:
        return True


def _auth_args():
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not tok:
        return []
    hdr = base64.b64encode(("x-access-token:" + tok).encode()).decode()
    return ["-c", "http.https://github.com/.extraheader=AUTHORIZATION: basic " + hdr]


def add_problem(st, text):
    st.setdefault("problems", []).append(redact(text)[:300])


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
    """One status.json workflow row from the workflow's file facts and its newest runs on main (newest first)."""
    gap = max_gap_minutes(wf["crons"]) if wf["crons"] else None
    lim = limit_minutes(gap)
    row = dict(file=wf["file"], name=wf["name"], schedule=wf["crons"], expected_max_gap_minutes=gap,
               limit_minutes=lim, latest=None, latest_completed=None, age_minutes=None, state="unknown", problem=None)
    if runs is None:
        row["state"], row["problem"] = "unknown", "could not list its runs"
        return row
    runs = [r for r in runs if (r.get("headBranch") or "main") == "main"]     # main only, even if gh ignored --branch
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
            runs = gh_json(["run", "list", "--workflow", wf["file"], "--branch", "main", "--limit", "5", "--json",
                            "databaseId,status,conclusion,createdAt,event,attempt,url,headBranch,displayTitle"], [])
        except RuntimeError as e:
            st["errors"].append(redact(str(e))); runs = None
        st["workflows"].append(judge_workflow(wf, runs, t))
    for spec in DATA:
        st["data"].append(judge_data(spec, git_newest(spec[0]), t))
    st["problems"] = [w["file"] + ": " + w["problem"] for w in st["workflows"] if w["problem"]] + \
                     [d["problem"] for d in st["data"] if d["problem"]]
    save_status(st)
    return st


def save_status(st):
    write_status("status.json", st)
    write_status("status.md", status_md(st, st.get("report_text")))


def status_md(st, report_text=None):
    lines = ["# Backup AI status", "", "Generated %s La Paz (%s UTC). Reads GitHub only; the PC is not reachable from here."
             % (st["generated_at_la_paz"], st["generated_at"]), ""]
    if not st.get("key_present"):
        lines += ["**NVIDIA_API_KEY is missing:** non-AI status check and re-runs only (add it as a repository secret).", ""]
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
    """The model client. Never stores the key anywhere but in the request header. All its calls together get at most
    `total` seconds (AI_TOTAL_SECONDS), one request at most AI_REQUEST_SECONDS."""

    def __init__(self, key=None, base=NVIDIA_BASE, max_calls=MAX_AI_CALLS, sleep=time.sleep, clock=time.monotonic,
                 total=AI_TOTAL_SECONDS):
        self._key = key if key is not None else os.environ.get("NVIDIA_API_KEY", "")
        self.base, self.max_calls, self.calls, self.sleep = base.rstrip("/"), max_calls, 0, sleep
        self.clock, self.deadline = clock, clock() + total
        self._models, self.used = None, []

    def available(self):
        return bool(self._key)

    def remaining(self):
        return self.deadline - self.clock()

    def _headers(self):
        return {"Authorization": "Bearer " + self._key, "Accept": "application/json",
                "Content-Type": "application/json", "User-Agent": USER_AGENT}

    def _request(self, fn, url, *args):
        """fn(url, headers, [body,] timeout) -> (status, headers, text); up to 4 tries on 429 and 5xx, with backoff,
        all inside the run's time budget."""
        last = None
        for i in range(4):
            left = self.remaining()
            if left < 5:
                raise RuntimeError("AI time budget (%d s) spent" % AI_TOTAL_SECONDS)
            try:
                code, headers, text = fn(url, self._headers(), *(args + (min(AI_REQUEST_SECONDS, left),)))
            except Exception as e:  # network errors and timeouts: retried
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
                if wait >= self.remaining() - 5:
                    raise RuntimeError("AI time budget (%d s) spent" % AI_TOTAL_SECONDS)
                self.sleep(wait)
        raise RuntimeError("NVIDIA API answered HTTP %s" % last)

    def models(self):
        if self._models is None:
            text = self._request(http_get, self.base + "/models")
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
        text = self._request(http_post, self.base + "/chat/completions", body)
        msg = json.loads(text)["choices"][0]["message"].get("content") or ""
        msg = re.sub(r"(?s)<think>.*?</think>", "", msg).strip()
        self.used.append(dict(task=task, model=model))
        return model, redact(msg)


SYSTEM_RULES = (
    "You are the backup operator for a small research and paper-trading project on GitHub. Your output is advice only: "
    "a human or another assistant reviews everything before it is used. Hard rules you must follow: never suggest "
    "loosening any limit, lock, threshold, kill switch, stop date, pre-registered plan or rule; never suggest anything "
    "involving real money, order placing, account keys or the files live.py, strategy.py, config.py, gate.py, core.py; "
    "never suggest editing frozen research code, research/results, workflows, tests or CLAUDE.md; never ask for or "
    "repeat secrets. If a fix would need any of those, say so and stop. Plain English, short, no hype.")


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
    """Opens, updates or closes the one issue. A failed gh call is recorded in st["problems"] and the result is
    "error"."""
    try:
        issues = gh_json(["issue", "list", "--label", LABEL, "--state", "open", "--json", "number,title"], []) or []
    except RuntimeError as e:
        st["errors"].append(redact(str(e))); add_problem(st, "backup AI: could not list its issues")
        return "error"
    action, num, extra = issue_action(len(st["problems"]), issues)
    body = status_md(st, report_text) + "\n---\nOpened by ops/backup_ai.py (GitHub Actions). Advice only; it changes no " \
        "rule, limit or lock and never touches real money. It closes this issue itself when everything is green.\n"
    failed = []
    if action in ("create", "update"):
        ensure_label()
        p = _body_file(body)
        try:
            if action == "create":
                rc, _o, err = gh(["issue", "create", "--title", issue_title(st), "--label", LABEL, "--body-file", p])
            else:
                rc, _o, err = gh(["issue", "edit", str(num), "--title", issue_title(st), "--body-file", p])
        finally:
            os.unlink(p)
        if rc != 0:
            failed.append("could not %s its issue: %s" % (action, redact(err.strip())[:200]))
    elif action == "close":
        rc, _o, err = gh(["issue", "close", str(num), "--comment", "All workflows and data are within their limits "
                          "(%s La Paz)." % st["generated_at_la_paz"]])
        if rc != 0:
            failed.append("could not close issue #%s: %s" % (num, redact(err.strip())[:200]))
    for n in extra:
        rc, _o, err = gh(["issue", "close", str(n), "--comment", "Duplicate of #%s." % num])
        if rc != 0:
            failed.append("could not close duplicate issue #%s: %s" % (n, redact(err.strip())[:200]))
    for f in failed:
        add_problem(st, "backup AI: " + f)
    return "error" if failed else action


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
    st["report_text"] = text
    save_status(st)
    write_status("report.md", text + "\n")
    return st, text


def _brief(st):
    return dict(generated_at=st["generated_at"], problems=st["problems"],
                workflows=[dict(file=w["file"], state=w["state"], age_minutes=w["age_minutes"],
                                limit_minutes=w["limit_minutes"], problem=w["problem"]) for w in st["workflows"]],
                data=st["data"])


# ---------------------------------------------------------------------------------------------------------------
# rerun (no AI: runs with or without the key)
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
        if (last.get("branch") or "main") != "main":
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
        if rc != 0:
            add_problem(st, "backup AI: re-run of %s run %s failed: %s" % (c["workflow"], c["run_id"], c["error"]))
    if any(not c["ok"] for c in out) and st.get("generated_at"):
        save_status(st)
    print("rerun: %d re-run(s), %d failed" % (len(out), sum(1 for c in out if not c["ok"])))
    return out


# ---------------------------------------------------------------------------------------------------------------
# fix, step 1 (job "operate"): propose only. Nothing from the model is executed here.
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
    """Workflows with an open fix pull request (found by the backup-ai/fix- branch or the label: the label is added in
    a separate, non-fatal step, so it may be missing)."""
    prs = gh_json(["pr", "list", "--state", "open", "--limit", "200", "--json", "number,title,body,headRefName,labels"],
                  []) or []
    out = set()
    for p in prs:
        labels = [(x or {}).get("name") for x in (p.get("labels") or []) if isinstance(x, dict)]
        if not str(p.get("headRefName") or "").startswith("backup-ai/fix-") and LABEL not in labels:
            continue
        m = re.search(r"backup-ai-workflow:\s*(\S+)", p.get("body") or "")
        if m:
            out.add(m.group(1))
        m = re.search(r"\[([\w.\-]+\.ya?ml)\]", p.get("title") or "")
        if m:
            out.add(m.group(1))
    return out


def fix_candidates(st, attempted, open_wfs):
    """Failed workflows whose latest finished run on main was started by its schedule or by hand."""
    out = []
    tried = set(str(a.get("run_id")) for a in (attempted or []))
    for w in st["workflows"]:
        last = w.get("latest_completed") or {}
        rid = last.get("id")
        if w["state"] != "failed" or not rid or str(rid) in tried or w["file"] in open_wfs:
            continue
        if w["file"] == "backup-ai.yml" or last.get("event") not in FIX_EVENTS or (last.get("branch") or "main") != "main":
            continue
        out.append(dict(workflow=w["file"], run_id=rid))
    return out


def proposal_dir():
    return os.environ.get("BACKUP_AI_PROPOSAL") or os.path.join(tempfile.gettempdir(), "backup-ai-proposal")


def fix(st=None, ai=None, out_dir=None):
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
        rec["result"], rec["model"] = _propose(c, ai, out_dir or proposal_dir())
    except Exception as e:  # noqa: any failure ends this proposal, never the job
        rec["result"] = "failed: " + redact("%s: %s" % (type(e).__name__, e))[:300]
    write_status("fixes.json", attempted)
    return rec["result"]


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def gh_output(name, value):
    """One job output (GITHUB_OUTPUT), written by this trusted job itself. Later jobs check artifacts against these
    values, never against hashes stored inside an artifact (code run in `test` could replace an artifact)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return False
    if not re.match(r"^[a-z_0-9]+$", name) or not re.match(r"^[A-Za-z0-9_./\-]*$", str(value)):
        raise ValueError("refusing an odd job output")
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("%s=%s\n" % (name, value))
    return True


def status_digest(folder):
    """SHA-256 over the status files push-status copies (names matching STATUS_FILE_RE, regular files, not links):
    name and content hash of each, in name order. The same set is hashed in `operate` and checked in `status`."""
    h = hashlib.sha256()
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        p = os.path.join(folder, n)
        if STATUS_FILE_RE.match(n) and os.path.isfile(p) and not os.path.islink(p):
            h.update(("%s\x00%s\n" % (n, _file_sha256(p))).encode("utf-8"))
    return h.hexdigest()


def _propose(c, ai, out_dir):
    log = failed_log(c["run_id"], 200)
    files = related_files(log)
    wf_rel = ".github/workflows/" + c["workflow"]
    if wf_rel not in files and os.path.isfile(os.path.join(ROOT, wf_rel)):
        files = files[:5] + [wf_rel]
    parts = []
    for rel in files[:6]:
        with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as f:
            body = f.read()
        tag = "READ-ONLY (%s)" % protected(rel) if protected(rel) else "editable"
        parts.append("=== %s [%s]\n%s%s" % (rel, tag, body[:12000], "\n... (truncated)" if len(body) > 12000 else ""))
    prompt = ("Workflow %s failed (run %s). Last lines of its log:\n%s\n\nRelevant files:\n%s\n\n"
              "Propose the smallest fix as a unified git diff (diff --git a/... b/... headers, paths relative to the "
              "repository root) in one ```diff block, editing only files marked editable. Do not add, delete or "
              "rename files and do not edit tests. Before the block write one line starting CAUSE: with the cause in "
              "plain English. If the cause is outside the code (GitHub outage, network, a data source down) or a fix "
              "would need a read-only file, answer NO_FIX and the cause only."
              % (c["workflow"], c["run_id"], log, "\n\n".join(parts)))
    model, answer = ai.ask("code-fix", "Write a minimal fix proposal.", prompt)
    m = re.search(r"CAUSE:\s*(.+)", answer)
    cause = redact(m.group(1).strip() if m else "not stated")[:200]
    if "NO_FIX" in answer and "diff --git" not in answer:
        return "no fix proposed: " + cause, model
    diff = extract_diff(answer)
    refused = check_diff(diff)
    if refused:
        return "refused: " + "; ".join(refused)[:400], model
    branch = "backup-ai/fix-%s" % c["run_id"]
    rc, out, _ = run(["git"] + _auth_args() + ["ls-remote", "--heads", "origin", branch], timeout=60)
    if rc == 0 and out.strip():
        return "branch %s already exists" % branch, model
    tmp = tempfile.mkdtemp(prefix="backup_ai_check_")
    try:
        pf = os.path.join(tmp, "fix.diff")
        with open(pf, "w", encoding="utf-8", newline="\n") as f:
            f.write(diff)
        rc, _o, err = run(["git", "apply", "--check", pf])     # reads only; nothing is applied or run here
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if rc != 0:
        return "diff does not apply: " + redact(err)[:300], model
    rc, sha, _e = run(["git", "rev-parse", "HEAD"], timeout=60)
    if rc != 0 or not re.match(r"^[0-9a-f]{40}$", sha.strip()):
        return "could not read the base commit", model
    paths, _p = diff_paths(diff)
    meta = dict(workflow=c["workflow"], run_id=c["run_id"], cause=cause, model=model, base_sha=sha.strip(),
                branch=branch, paths=paths, diff_sha256=_sha256(diff))
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, "fix.diff"), "w", encoding="utf-8", newline="\n") as f:
        f.write(diff)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    # the binding hashes, as job outputs of this job (never trusted from the artifact itself)
    gh_output("diff_sha256", _file_sha256(os.path.join(out_dir, "fix.diff")))
    gh_output("meta_sha256", _file_sha256(os.path.join(out_dir, "meta.json")))
    gh_output("proposed", "true")
    ensure_label()
    return "proposed for testing on branch %s" % branch, model


def load_proposal(pdir, diff_sha256=None, meta_sha256=None):
    """(diff, meta, problems): the proposal re-read and re-checked from scratch. The raw bytes of fix.diff and
    meta.json must match the hashes `operate` gave as job outputs (passed in on the command line); without both, or
    with anything but 64 hex digits, it is refused. Then the path rules, the file set and the branch name."""
    problems = []
    if not (isinstance(diff_sha256, str) and _HEX64.match(diff_sha256)
            and isinstance(meta_sha256, str) and _HEX64.match(meta_sha256)):
        return None, None, ["the expected hashes from the operate job are missing or malformed"]
    try:
        dpath, mpath = os.path.join(pdir, "fix.diff"), os.path.join(pdir, "meta.json")
        if os.path.islink(dpath) or os.path.islink(mpath):
            return None, None, ["proposal files must not be links"]
        if _file_sha256(dpath) != diff_sha256:
            return None, None, ["fix.diff does not match the hash from the operate job"]
        if _file_sha256(mpath) != meta_sha256:
            return None, None, ["meta.json does not match the hash from the operate job"]
        with open(dpath, encoding="utf-8", newline="") as f:
            diff = f.read()
        with open(mpath, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        return None, None, ["proposal unreadable: %s" % type(e).__name__]
    if not isinstance(meta, dict):
        return None, None, ["proposal metadata unreadable"]
    problems += check_diff(diff)
    paths, _p = diff_paths(diff)
    if meta.get("diff_sha256") != diff_sha256:
        problems.append("the metadata names another diff")
    if sorted(meta.get("paths") or []) != paths:
        problems.append("the diff's files do not match its metadata")
    if not re.match(r"^backup-ai/fix-\d+$", str(meta.get("branch") or "")) or \
            meta.get("branch") != "backup-ai/fix-%s" % meta.get("run_id"):
        problems.append("unexpected branch name")
    if not re.match(r"^[0-9a-f]{40}$", str(meta.get("base_sha") or "")):
        problems.append("unexpected base commit")
    return diff, meta, problems


def changed_files(cwd):
    """Every path that differs from HEAD in a work tree: tracked changes, untracked and ignored files. Paths that git
    has to quote are returned as they are and never match a diff path (so they are refused)."""
    out = set()
    rc, s, err = run(["git", "status", "--porcelain", "-z", "--no-renames", "--ignored", "--untracked-files=all"],
                     cwd=cwd, timeout=120)
    if rc != 0:
        raise RuntimeError("git status failed")
    for rec in s.split("\x00"):
        if len(rec) > 3:
            out.add(rec[3:])
    rc, s, err = run(["git", "diff", "--no-renames", "--name-only", "-z", "HEAD"], cwd=cwd, timeout=120)
    if rc != 0:
        raise RuntimeError("git diff failed")
    out.update(x for x in s.split("\x00") if x)
    return sorted(out)


def _apply(diff, cwd):
    tmp = tempfile.mkdtemp(prefix="backup_ai_apply_")
    try:
        pf = os.path.join(tmp, "fix.diff")
        with open(pf, "w", encoding="utf-8", newline="\n") as f:
            f.write(diff)
        rc, _o, err = run(["git", "apply", "--check", pf], cwd=cwd)
        if rc == 0:
            rc, _o, err = run(["git", "apply", pf], cwd=cwd)
        return rc, err
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_env():
    """No token, key or Actions credential reaches the tests, which run the proposed code; no bytecode files either,
    so the work tree after the tests holds only the diff's changes."""
    env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if any(s in ku for s in ("TOKEN", "KEY", "SECRET", "PASSWORD", "ACTIONS_", "NVIDIA")) or ku.startswith("GH_"):
            continue
        env[k] = v
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_tests(cwd, timeout=None):
    """(returncode, output) of tests/run_all.py with a hard time limit (124 at the limit). The tests run in their own
    process group, which is killed both at the limit and after they finish, so a background process they left behind
    cannot keep running (or rewrite files) after the changed-file check. Partial: a process that starts its own
    session escapes the group; the binding check is publish's re-validation on a fresh checkout."""
    timeout = TEST_SECONDS if timeout is None else timeout
    p = subprocess.Popen([sys.executable, os.path.join("tests", "run_all.py")], cwd=cwd, env=_test_env(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)

    def killgroup():
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass

    try:
        out, _e = p.communicate(timeout=timeout)
        rc, text = p.returncode, out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        killgroup()
        try:
            p.kill()
        except OSError:
            pass
        out, _e = p.communicate()
        rc, text = 124, out.decode("utf-8", "replace") + "\n(tests stopped at the %d s limit)" % timeout
    killgroup()                     # always: whatever the tests left running in their group
    return rc, text


def _write_result(rdir, res):
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "result.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, sort_keys=True)


def test_proposal(pdir, rdir, diff_sha256=None, meta_sha256=None, root=None):
    """Job "test" (no token, no secret): re-check, apply, run the tests, compare the changed files with the diff's.
    Returns 0 only when the tests passed and nothing but the diff's own files changed. The changed-file check is
    advisory (the tested code runs in this job and could defeat it); publish's re-validation is the binding one."""
    root = root or ROOT
    res = dict(ok=False, tests_rc=None, tail="", files=[], expected=[], problems=[])
    try:
        if kill_present(root):
            res["problems"].append("KILL file present")
            return 1
        diff, meta, problems = load_proposal(pdir, diff_sha256, meta_sha256)
        if problems:
            res["problems"] += problems
            return 1
        expected = sorted(meta["paths"])
        res["expected"] = expected
        rc, err = _apply(diff, root)
        if rc != 0:
            res["problems"].append("diff does not apply: " + redact(err)[:300]); return 1
        before = changed_files(root)
        if before != expected:
            res["files"] = before
            res["problems"].append("files changed by applying the diff differ from its own files"); return 1
        rc, out = run_tests(root)
        res["tests_rc"], res["tail"] = rc, redact("\n".join(out.splitlines()[-40:]))
        after = changed_files(root)
        res["files"] = after
        if after != expected:
            res["problems"].append("the tests changed files outside the diff: " + ", ".join(sorted(set(after) ^ set(expected)))[:400])
            return 1
        if rc != 0:
            res["problems"].append("tests failed (exit %s)" % rc); return 1
        res["ok"] = True
        return 0
    finally:
        _write_result(rdir, res)


# ---------------------------------------------------------------------------------------------------------------
# fix, step 3 (job "publish"): branch, commit and pull request. Runs nothing from the diff.
def _fence(text):
    return (text or "").replace("```", "'''")


def _trailers(msg):
    out = {}
    for line in (msg or "").splitlines():
        m = re.match(r"^(Backup-AI-Run|Backup-AI-Diff-SHA256):\s*(\S+)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _existing_branch_ok(root, branch, base_sha, run_id, diff_sha256):
    """None when the remote branch is this same run's earlier push of this same diff (a re-run of the publish job after
    a failure between push and pull request), else the reason to refuse. Checks: one commit, by the runner, on the
    base commit, carrying this workflow run id and diff hash, with exactly the tree staged here."""
    rc, _o, _e = run(["git"] + NOHOOKS + _auth_args() + ["fetch", "-q", "--no-tags", "origin",
                      "+refs/heads/%s:refs/backup-ai/existing" % branch], cwd=root, timeout=180)
    if rc != 0:
        return "could not fetch the existing branch"
    rc, info, _e = run(["git", "log", "-1", "--format=%P%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B", "refs/backup-ai/existing"],
                       cwd=root, timeout=60)
    parts = info.split("\x1f", 5) if rc == 0 else []
    if len(parts) != 6:
        return "could not read the existing branch"
    parents, who, body = parts[0].split(), parts[1:5], parts[5]
    if parents != [base_sha]:
        return "the existing branch is not one commit on the base commit"
    if who != [RUNNER_NAME, RUNNER_EMAIL, RUNNER_NAME, RUNNER_EMAIL]:
        return "the existing branch's commit is not the runner's"
    tr = _trailers(body)
    if not run_id or tr.get("Backup-AI-Run") != str(run_id):
        return "the existing branch comes from another workflow run"
    if tr.get("Backup-AI-Diff-SHA256") != diff_sha256:
        return "the existing branch holds another diff"
    rc1, mine, _e = run(["git", "write-tree"], cwd=root, timeout=60)
    rc2, theirs, _e = run(["git", "rev-parse", "refs/backup-ai/existing^{tree}"], cwd=root, timeout=60)
    if rc1 != 0 or rc2 != 0 or mine.strip() != theirs.strip() or not mine.strip():
        return "the existing branch's files differ from this diff applied to the base commit"
    return None


def publish(pdir, rdir, diff_sha256=None, meta_sha256=None, root=None):
    """Re-check the proposal against the operate job's hashes, apply it to a fresh checkout, stage exactly its paths,
    commit without hooks, push the branch and open the pull request. Never merges. Returns 0 on success.
    Idempotent for a re-run of this job: a branch left by an earlier attempt of the SAME workflow run with the SAME
    diff is reused (only the pull request is created); any other existing branch is refused."""
    root = root or ROOT
    if kill_present(root):
        print("publish: KILL file present"); return 1
    diff, meta, problems = load_proposal(pdir, diff_sha256, meta_sha256)
    if problems:
        print("publish: refused: " + "; ".join(problems)[:600]); return 1
    try:
        with open(os.path.join(rdir, "result.json"), encoding="utf-8") as f:
            result = json.load(f)       # written by the job that ran the proposed code: shown as text only
    except (OSError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    branch, paths = meta["branch"], sorted(meta["paths"])
    run_id = os.environ.get("GITHUB_RUN_ID") or ""
    if run_id and not re.match(r"^\d+$", run_id):
        run_id = ""
    rc, head, _ = run(["git", "rev-parse", "HEAD"], cwd=root, timeout=60)
    if rc != 0 or head.strip() != meta["base_sha"]:
        print("publish: the checkout is not the proposal's base commit"); return 1
    rc, err = _apply(diff, root)
    if rc != 0:
        print("publish: diff does not apply: " + redact(err)[:300]); return 1
    if changed_files(root) != paths:
        print("publish: refused: the work tree holds other changes than the diff's"); return 1
    rc, _o, err = run(["git", "checkout", "-q", "-b", branch], cwd=root, timeout=60)
    if rc != 0:
        print("publish: could not create the branch"); return 1
    rc, _o, err = run(["git", "--literal-pathspecs", "add", "--"] + paths, cwd=root, timeout=120)
    rc2, staged, _e = run(["git", "diff", "--cached", "--no-renames", "--name-only", "-z"], cwd=root, timeout=60)
    if rc != 0 or rc2 != 0 or sorted(x for x in staged.split("\x00") if x) != paths:
        print("publish: refused: staged files differ from the diff's"); return 1
    rc, out, _ = run(["git"] + _auth_args() + ["ls-remote", "--heads", "origin", branch], timeout=60, cwd=root)
    if rc != 0:
        print("publish: the remote could not be read"); return 1
    if out.strip():
        why = _existing_branch_ok(root, branch, meta["base_sha"], run_id, diff_sha256)
        if why:
            print("publish: branch %s exists: %s" % (branch, why)); return 1
        rc, stat, _e = run(["git", "show", "--stat", "--format=commit %H%n%s", "refs/backup-ai/existing"], cwd=root,
                           timeout=60)
        print("publish: branch %s is this run's earlier push of the same diff; opening the pull request" % branch)
    else:
        msg = ("Backup AI fix proposal for %s (run %s)\n\nUnreviewed; do not merge without review.\n\n"
               "Backup-AI-Run: %s\nBackup-AI-Diff-SHA256: %s\n" % (meta["workflow"], meta["run_id"], run_id or "none",
                                                                   diff_sha256))
        rc, _o, err = run(["git"] + NOHOOKS + ["-c", "user.name=" + RUNNER_NAME, "-c", "user.email=" + RUNNER_EMAIL,
                           "commit", "-q", "--no-verify", "-m", msg], cwd=root, timeout=120)
        if rc != 0:
            print("publish: commit failed"); return 1
        rc, stat, _e = run(["git", "show", "--stat", "--format=commit %H%n%s", "HEAD"], cwd=root, timeout=60)
        rc, _o, err = run(["git"] + NOHOOKS + _auth_args() + ["push", "-q", "origin", "HEAD:refs/heads/" + branch],
                          cwd=root, timeout=180)
        if rc != 0:
            print("publish: push failed: " + redact(err)[:200]); return 1
    try:
        prs = gh_json(["pr", "list", "--state", "open", "--head", branch, "--json", "number,url"], []) or []
    except RuntimeError as e:
        print("publish: could not list pull requests: " + redact(str(e))[:200]); return 1
    if prs:
        print("publish: pull request already open: %s" % (prs[0].get("url") or prs[0].get("number")))
        _label_pr(branch)
        return 0
    tests = "passed" if result.get("ok") else "NOT passed"
    cause = redact(str(meta.get("cause") or "not stated"))[:200]       # from operate's hash-checked meta.json only
    body = ("<!-- backup-ai-workflow: %s -->\n**Do not merge without review.** Proposed by the backup AI operator "
            "(model %s) because Claude made no commit in the last 24 hours. It never merges anything itself.\n\n"
            "**Read the Files tab**: it shows the real change. Text below is redacted and may be cut short.\n\n"
            "**Failing run:** %s (workflow %s)\n\n**Likely cause (model's words):** %s\n\n"
            "**Commit (`git show --stat`):**\n```\n%s\n```\n\n"
            "**Tests** (`python3 tests/run_all.py` in a job with no token or secret, %d s limit): %s, exit %s; "
            "files changed after the tests: %s\n```\n%s\n```\n\n"
            "Checked against the allowlist and the deny list in ops/backup_ai.py in each of the three jobs.\n"
            % (meta["workflow"], _fence(redact(str(meta.get("model")))), meta["run_id"], meta["workflow"],
               _fence(cause), _fence(stat.strip()), TEST_SECONDS, tests, _fence(str(result.get("tests_rc"))[:20]),
               _fence(", ".join(str(x) for x in (result.get("files") or [])))[:2000],
               _fence(str(result.get("tail") or ""))[-6000:]))
    title = "Backup AI fix proposal: [%s] %s" % (meta["workflow"], " ".join(cause.split())[:80])
    p = _body_file(body)
    try:
        rc, out, err = gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", p])
    finally:
        os.unlink(p)
    if rc != 0:
        print("publish: pull request failed: " + redact(err)[:200]); return 1
    print("publish: pull request opened: " + out.strip())
    _label_pr(branch)
    return 0


def _label_pr(branch):
    """The label in a separate, non-fatal call (the pull request matters, the label is a convenience)."""
    rc, _o, err = gh(["pr", "edit", branch, "--add-label", LABEL])
    if rc != 0:
        print("publish: note: could not add the %s label: %s" % (LABEL, redact(err)[:200]))


# ---------------------------------------------------------------------------------------------------------------
# push-status (job "status"): one commit on main, ops/status/ only
STATUS_FILE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(json|md)$")


def push_guard(cwd):
    """Reasons to refuse pushing to main (empty = allowed): HEAD must be exactly one commit ahead of origin/main, made
    by the runner identity, touching only ops/status/."""
    out = []
    rc, names, _e = run(["git", "diff", "--no-renames", "--name-only", "-z", "origin/main..HEAD"], cwd=cwd, timeout=60)
    if rc != 0:
        return ["could not compare with origin/main"]
    bad = [n for n in names.split("\x00") if n and not n.startswith("ops/status/")]
    if bad:
        out.append("files outside ops/status/: " + ", ".join(bad)[:300])
    rc, revs, _e = run(["git", "rev-list", "origin/main..HEAD"], cwd=cwd, timeout=60)
    revs = [r for r in revs.split() if r]
    if rc != 0 or len(revs) != 1:
        out.append("expected exactly one new commit, found %s" % (len(revs) if rc == 0 else "unknown"))
    else:
        rc, who, _e = run(["git", "log", "-1", "--format=%an%x1f%ae%x1f%cn%x1f%ce", revs[0]], cwd=cwd, timeout=60)
        if rc != 0 or who.strip().split("\x1f") != [RUNNER_NAME, RUNNER_EMAIL, RUNNER_NAME, RUNNER_EMAIL]:
            out.append("the new commit is not the runner's")
    return out


def push_status(src, expected_sha256=None, cwd=None, tries=6, sleep=time.sleep):
    """Copy the status files from src into ops/status/, commit them as the runner and push to main. The downloaded
    files must match the digest the operate job gave as a job output (status_digest). Refuses anything else changed,
    staged or committed. Returns 0 when pushed or nothing changed."""
    cwd = cwd or ROOT
    if not (isinstance(expected_sha256, str) and _HEX64.match(expected_sha256)):
        print("push-status: refusing: the status digest from the operate job is missing or malformed"); return 1
    if status_digest(src) != expected_sha256:
        print("push-status: refusing: the status files do not match the operate job's digest"); return 1
    sdir = os.path.join(cwd, "ops", "status")
    rc, s, _e = run(["git", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all"], cwd=cwd, timeout=60)
    others = [r[3:] for r in s.split("\x00") if len(r) > 3 and not r[3:].startswith("ops/status/")]
    if rc != 0 or others:
        print("push-status: refusing: files outside ops/status changed: %s" % ", ".join(others)[:300]); return 1
    os.makedirs(sdir, exist_ok=True)
    for n in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        p = os.path.join(src, n)
        if STATUS_FILE_RE.match(n) and os.path.isfile(p) and not os.path.islink(p):
            shutil.copyfile(p, os.path.join(sdir, n))
    run(["git", "--literal-pathspecs", "add", "--", "ops/status"], cwd=cwd, timeout=60)
    rc, staged, _e = run(["git", "diff", "--cached", "--no-renames", "--name-only", "-z"], cwd=cwd, timeout=60)
    staged = [x for x in staged.split("\x00") if x]
    if rc != 0 or any(not x.startswith("ops/status/") for x in staged):
        print("push-status: refusing: staged files outside ops/status"); return 1
    if not staged:
        print("push-status: nothing new"); return 0
    rc, _o, _e = run(["git"] + NOHOOKS + ["-c", "user.name=" + RUNNER_NAME, "-c", "user.email=" + RUNNER_EMAIL,
                      "commit", "-q", "--no-verify", "-m", "Backup AI status %s" % iso(now())], cwd=cwd, timeout=60)
    if rc != 0:
        print("push-status: commit failed"); return 1
    auth = _auth_args()
    for i in range(tries):
        why = push_guard(cwd)
        if why:
            print("push-status: refusing to push: " + "; ".join(why)); return 1
        rc, _o, _e = run(["git"] + NOHOOKS + auth + ["push", "-q", "origin", "HEAD:refs/heads/main"], cwd=cwd, timeout=120)
        if rc == 0:
            print("push-status: pushed"); return 0
        sleep((i + 1) * 10)
        rc, _o, _e = run(["git"] + NOHOOKS + auth + ["fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main"],
                         cwd=cwd, timeout=120)
        rc2, _o, _e = run(["git"] + NOHOOKS + ["-c", "user.name=" + RUNNER_NAME, "-c", "user.email=" + RUNNER_EMAIL,
                           "rebase", "-q", "origin/main"], cwd=cwd, timeout=120)
        if rc != 0 or rc2 != 0:
            run(["git", "rebase", "--abort"], cwd=cwd, timeout=60)
            print("push-status: could not rebase onto main"); return 1
    print("push-status: push failed %d times" % tries)
    return 1


# ---------------------------------------------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "all"
    if mode == "status-hash" and len(argv) == 2:
        digest = status_digest(argv[1])
        gh_output("status_sha256", digest)
        print("status-hash: " + digest)
        return 0
    if mode == "push-status" and len(argv) == 3:
        return push_status(argv[1], argv[2])
    if mode == "test-proposal" and len(argv) == 5:
        return test_proposal(argv[1], argv[2], argv[3], argv[4])
    if mode == "publish" and len(argv) == 5:
        return publish(argv[1], argv[2], argv[3], argv[4])
    if mode in ("status-hash", "push-status", "test-proposal", "publish"):
        print(__doc__); return 2
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
    if mode in ("rerun", "all"):
        rerun(st)                      # no AI: runs without the key too
    if mode in ("fix", "all"):
        if not ai.available():
            print("fix: skipped: NVIDIA_API_KEY is missing")
        else:
            print("fix: " + fix(st, ai))
    return 0


if __name__ == "__main__":
    sys.exit(main())
