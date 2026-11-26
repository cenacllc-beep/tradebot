"""ops/backup_ai.py (the backup AI operator) on a fake gh, a fake NVIDIA API and throwaway git repositories. No network.
python test_backup_ai.py WORK OUT"""
import os, sys, json, re, subprocess, shutil
from datetime import datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(WORK, "ops"))
for k in ("NVIDIA_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
    os.environ.pop(k, None)
import backup_ai as B

T = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
B.now = lambda: T
B.STATUS_DIR = os.path.join(OUT, "status")
real_run = B.run

# ---- the module never touches orders, live.py or the bot's databases, and never merges
src = open(os.path.join(WORK, "ops", "backup_ai.py"), encoding="utf-8").read()
assert "/portfolio" not in src, "no order endpoint"
assert not re.search(r"^\s*(import live\b|from live\b)", src, re.M) and "import live" not in src
assert "pr merge" not in src and '"merge"' not in src, "it never merges"
assert "sqlite3" not in src
assert "live" not in sys.modules, "live.py was imported"
for w in (os.path.join(WORK, ".github", "workflows", "backup-ai.yml"), os.path.join(WORK, "cloud", "workflows", "backup-ai.yml")):
    assert os.path.exists(w), w
assert open(os.path.join(WORK, ".github", "workflows", "backup-ai.yml"), "rb").read() == \
    open(os.path.join(WORK, "cloud", "workflows", "backup-ai.yml"), "rb").read(), "the two workflow copies must be identical"
wf = open(os.path.join(WORK, "cloud", "workflows", "backup-ai.yml"), encoding="utf-8").read()
for need in ('cron: "37 */3 * * *"', "group: tradebot-backup-ai", "cancel-in-progress: false", "timeout-minutes: 30",
             "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}", "requests==2.32.3", "persist-credentials: false",
             "refusing: staged files outside ops/status", "issues: write", "pull-requests: write", "actions: write",
             "TZ: America/La_Paz"):
    assert need in wf, need
assert "@v" not in wf.replace("# v", ""), "actions pinned by SHA"

# ---- protected paths (deny list)
blocked = ["live.py", "./live.py", "Live.py", "LIVE.PY", "sub/../live.py", "../live.py", "/etc/passwd", "C:/x.py", "~/x.py",
           "live.db", "paper.db", "trial/paper.db", "backups/paper.db", "research/paper.db-journal", "config.py",
           "strategy.py", "weather.py", "nws.py", "gate.py", "core.py", "CLAUDE.md", ".claude/settings.json",
           ".claude/skills/new/SKILL.md", ".github/workflows/x.yml", "cloud/workflows/new.yml", "agents/x.md",
           "tasks/evening.cmd", "tasks/new.py", "run.bat", "x.cmd", "tools/a.ps1", "research/PLAN7.md",
           "research/PLAN15F.md", "research/plan_new.md", "research/results/plan19_result.json",
           "research/results/new_dir/a.txt", "research/frozen_model.py", "docs/FROZEN.txt", "research/plan7.py",
           "research/plan20.py", "research/plan15.py", "research/live15.py", "research/live20.py",
           "ops/backup_ai.py", "ops/status/status.json", "tests/test_backup_ai.py", "tests/run_all.py", "", "  ",
           "a\x00b", "..", ".", "research\\plan9.py", ".git/config", "keys/k.pem", "x/live.py"]
for p in blocked:
    assert B.protected(p), "should be protected: %r" % p
allowed = ["research/lip.py", "research/discover.py", "freshness.py", "check.py", "tests/test_freshness.py",
           "ops/README.md", "tbcommon/http.py", "research/fetch.py", "docs/notes.md", "research/data_tools.py"]
for p in allowed:
    assert B.protected(p) is None, "should be allowed: %r -> %s" % (p, B.protected(p))


def d(a, b=None, extra=""):
    b = b or a
    return "diff --git a/%s b/%s\n%s--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n-x\n+y\n" % (a, b, extra, a, b)


assert B.check_diff(d("freshness.py")) == []
assert B.check_diff(d("live.py"))
assert B.check_diff(d("./live.py"))
assert B.check_diff(d("research/x/../../live.py"))
assert B.check_diff("diff --git a/check.py b/strategy.py\nsimilarity index 90%\nrename from check.py\nrename to strategy.py\n")
assert B.check_diff("diff --git a/freshness.py b/research/results/x.json\nrename from freshness.py\nrename to research/results/x.json\n")
assert B.check_diff("diff --git a/x.py b/x.py\nnew file mode 100644\n--- /dev/null\n+++ b/research/results/new.json\n@@ -0,0 +1 @@\n+{}\n")
assert B.check_diff("diff --git a/agents/new.md b/agents/new.md\nnew file mode 100644\n--- /dev/null\n+++ b/agents/new.md\n@@ -0,0 +1 @@\n+x\n")
assert B.check_diff("diff --git a/tasks/new/run.py b/tasks/new/run.py\nnew file mode 100644\n--- /dev/null\n+++ b/tasks/new/run.py\n@@ -0,0 +1 @@\n+x\n")
assert B.check_diff("--- a/freshness.py\n+++ b/freshness.py\n@@ -1 +1 @@\n-x\n+y\n--- a/live.py\n+++ b/live.py\n@@ -1 +1 @@\n-x\n+y\n")
assert B.check_diff(d("freshness.py", extra="deleted file mode 100644\n"))
assert B.check_diff(d("freshness.py", extra="old mode 100644\nnew mode 100755\n"))
assert B.check_diff("diff --git a/x b/x\nnew file mode 120000\n--- /dev/null\n+++ b/x\n@@ -0,0 +1 @@\n+/etc\n")
assert B.check_diff('diff --git "a/live.py" "b/live.py"\n')
assert B.check_diff("diff --git a/img.png b/img.png\nGIT binary patch\n")
assert B.check_diff("no diff at all")
assert B.check_diff(d("tests/run_all.py"))
assert B.extract_diff("CAUSE: x\n```diff\n" + d("check.py") + "```\n").startswith("diff --git a/check.py")

# ---- key and token redaction
os.environ["NVIDIA_API_KEY"] = "nvapi-SECRETsecret123456789"
txt = ("key nvapi-SECRETsecret123456789 tok ghp_abcdefghijklmnopqrstuvwxyz0123 pat github_pat_11ABCDEFG0123456789_xyz "
       "Authorization: Bearer abc.def.ghi1234567890 token=hunter2hunter2 mail someone@example.com "
       "aws AKIAABCDEFGHIJKLMNOP -----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY----- "
       "rand Zx9Kq2Lm8Np4Rt6Vw1Yb3Cd5Ef7Gh0Jk sha 0123456789abcdef0123456789abcdef01234567")
r = B.redact(txt)
for bad in ("nvapi-", "SECRETsecret", "ghp_abc", "github_pat_11", "abc.def.ghi", "hunter2", "someone@example.com",
            "AKIAABCDEFGHIJKLMNOP", "MIIabc", "Zx9Kq2Lm8Np4"):
    assert bad not in r, (bad, r)
assert "0123456789abcdef0123456789abcdef01234567" in r, "git hashes stay readable"
del os.environ["NVIDIA_API_KEY"]

# ---- cron schedules
assert B.max_gap_minutes(["7 * * * *"]) == 60
assert B.max_gap_minutes(["5,25,45 * * * *"]) == 20
assert B.max_gap_minutes(["55 0 * * *", "25,55 1-3 * * *", "25 4 * * *"]) == 1230
assert B.max_gap_minutes(["37 */3 * * *"]) == 180
assert B.max_gap_minutes(["0 12 * * 1"]) == 7 * 1440
assert B.max_gap_minutes([]) is None and B.limit_minutes(None) is None
assert B.limit_minutes(60) == 180 and B.limit_minutes(1230) == 1590


# ---- workflow judgement
def runrec(i, status="completed", concl="success", ago_min=10, attempt=1):
    return dict(databaseId=i, status=status, conclusion=concl, createdAt=B.iso(T - timedelta(minutes=ago_min)),
                event="schedule", attempt=attempt, url="https://github.com/o/r/actions/runs/%d" % i, headBranch="main",
                displayTitle="t")


hourly = dict(file="live20.yml", name="x", crons=["7 * * * *"], dispatch=True, workflow_run=False)
manual = dict(file="plan20.yml", name="y", crons=[], dispatch=True, workflow_run=False)
assert B.judge_workflow(hourly, [runrec(1)], T)["state"] == "ok"
assert B.judge_workflow(hourly, [runrec(1, ago_min=200)], T)["state"] == "stale"
assert B.judge_workflow(hourly, [runrec(2, concl="failure")], T)["state"] == "failed"
assert B.judge_workflow(hourly, [runrec(2, concl="timed_out")], T)["state"] == "failed"
assert B.judge_workflow(hourly, [runrec(2, concl="cancelled")], T)["state"] == "ok"
w = B.judge_workflow(hourly, [runrec(3, status="in_progress", concl=None, ago_min=5), runrec(2, concl="failure", ago_min=70)], T)
assert w["state"] == "failed" and w["latest"]["id"] == 3 and w["latest_completed"]["id"] == 2
assert B.judge_workflow(hourly, [runrec(3, status="in_progress", concl=None)], T)["state"] == "running"
assert B.judge_workflow(hourly, [], T)["state"] == "no-runs" and B.judge_workflow(hourly, [], T)["problem"]
assert B.judge_workflow(manual, [], T)["state"] == "manual-only" and not B.judge_workflow(manual, [], T)["problem"]
assert B.judge_workflow(manual, [runrec(1, ago_min=99999)], T)["state"] == "manual-only"
assert B.judge_workflow(hourly, None, T)["state"] == "unknown"

# ---- data freshness
root = os.path.join(OUT, "root"); os.makedirs(os.path.join(root, "research", "results"))
assert B.judge_data(("research/data/live20", 6, None, None, None), T - timedelta(hours=2), T)["state"] == "ok"
assert B.judge_data(("research/data/live20", 6, None, None, None), T - timedelta(hours=7), T)["state"] == "stale"
assert B.judge_data(("research/data/live20", 6, None, None, None), None, T)["state"] == "missing"
p19 = ("research/data/plan19", 3, "2026-11-28T06:00:00Z", "2026-12-28T06:00:00Z", "research/results/plan19_result.json")
assert B.judge_data(p19, None, T, root)["state"] == "inactive"
assert B.judge_data(p19, None, T + timedelta(days=3), root)["state"] == "missing"
open(os.path.join(root, "research", "results", "plan19_result.json"), "w").close()
assert B.judge_data(p19, None, T + timedelta(days=3), root)["state"] == "finished"
assert B.judge_data(("research/results", None, None, None, None), None, T)["state"] == "info"

# ---- check(): status.json schema, with a fake gh and git
wfdir = os.path.join(OUT, "wf"); os.makedirs(wfdir)
open(os.path.join(wfdir, "live20.yml"), "w").write('name: PLAN20 forward logger (research)\non:\n  schedule:\n    - cron: "7 * * * *"\n  workflow_dispatch: {}\n')
open(os.path.join(wfdir, "plan20.yml"), "w").write("name: PLAN20\non:\n  workflow_dispatch:\n")
open(os.path.join(wfdir, "plan19.yml"), "w").write('name: PLAN19\non:\n  schedule:\n    - cron: "5,25,45 * * * *"\n')
B.WORKFLOW_DIR = wfdir
GH = {"live20.yml": [runrec(11, concl="failure", ago_min=30)], "plan20.yml": [], "plan19.yml": [runrec(12)]}
calls = []


def fake_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    calls.append(list(cmd))
    if cmd[:3] == ["gh", "run", "list"]:
        return 0, json.dumps(GH[cmd[cmd.index("--workflow") + 1]]), ""
    if cmd[:3] == ["gh", "run", "view"]:
        return 0, "line\n" * 300 + "Traceback\n  File \"/home/runner/work/tradebot/tradebot/freshness.py\", line 3\nghp_abcdefghijklmnopqrstuvwxyz0123\n", ""
    if cmd[:2] == ["git", "log"] and "-1" in cmd:
        return 0, B.iso(T - timedelta(hours=1)) + "\n", ""
    return 0, "", ""


B.run = fake_run
st = B.check()
saved = json.load(open(os.path.join(B.STATUS_DIR, "status.json")))
for k in ("schema", "generated_at", "generated_at_la_paz", "repository", "key_present", "workflows", "data", "problems",
          "errors", "ai", "note"):
    assert k in saved, k
assert saved["schema"] == 1 and saved["key_present"] is False and saved["generated_at"] == "2026-11-26T18:00:00Z"
assert saved["generated_at_la_paz"] == "2026-11-26 14:00"
for w in saved["workflows"]:
    for k in ("file", "name", "schedule", "expected_max_gap_minutes", "limit_minutes", "latest", "latest_completed",
              "age_minutes", "state", "problem"):
        assert k in w, k
for dd in saved["data"]:
    for k in ("path", "newest_commit_at", "age_hours", "limit_hours", "state", "problem"):
        assert k in dd, k
for k in ("used", "task", "model", "note"):
    assert k in saved["ai"]
assert [w["state"] for w in saved["workflows"]] == ["failed", "ok", "manual-only"], [w["state"] for w in saved["workflows"]]
assert len(saved["problems"]) == 1 and saved["problems"][0].startswith("live20.yml")
assert "NVIDIA_API_KEY is missing" in open(os.path.join(B.STATUS_DIR, "status.md")).read()
try:
    B.write_status("../escape.json", {}); raise SystemExit("wrote outside ops/status")
except ValueError:
    pass

# ---- model selection
ALL = ["meta/llama-3.1-8b-instruct", "deepseek-ai/deepseek-r1", "qwen/qwen2.5-coder-32b-instruct", "nvidia/nv-embed-v1"]
assert B.pick("check-summary", ALL) == "meta/llama-3.1-8b-instruct"
assert B.pick("diagnose", ALL) == "deepseek-ai/deepseek-r1"
assert B.pick("code-fix", ALL) == "qwen/qwen2.5-coder-32b-instruct"
FAM = ["acme/llama-3.2-1b-instruct", "nvidia/llama-3.9-nemotron-super-70b-v9", "bigcode/starcoder2-15b", "x/embed"]
assert B.pick("check-summary", FAM) == "acme/llama-3.2-1b-instruct"
assert B.pick("diagnose", FAM) == "nvidia/llama-3.9-nemotron-super-70b-v9"
assert B.pick("code-fix", FAM) == "bigcode/starcoder2-15b"
for task in ("check-summary", "diagnose", "code-fix"):
    assert B.pick(task, ["nvidia/nv-embed-v1", "x/rerank"]) is None and B.pick(task, []) is None
    assert B.PREFERENCES[task]["ids"]


# ---- the AI client: fake HTTP, retries, budget, no key
class FakeAPI(object):
    def __init__(self, models, fail=0):
        self.models, self.fail, self.posts, self.gets = models, fail, [], []

    def get(self, url, headers, timeout):
        self.gets.append((url, headers))
        return 200, {}, json.dumps(dict(data=[dict(id=m) for m in self.models]))

    def post(self, url, headers, body, timeout):
        self.posts.append((url, headers, body))
        if self.fail:
            self.fail -= 1
            return 429, {"Retry-After": "1"}, "slow down"
        return 200, {}, json.dumps(dict(choices=[dict(message=dict(content="<think>hidden</think>All fine. ghp_abcdefghijklmnopqrstuvwxyz0123"))]))


api = FakeAPI(ALL, fail=2)
B.http_get, B.http_post = api.get, api.post
sleeps = []
ai = B.AI(key="nvapi-testkey123456", sleep=sleeps.append, max_calls=2)
model, text = ai.ask("diagnose", "s", "u someone@example.com")
assert model == "deepseek-ai/deepseek-r1" and text.startswith("All fine.") and "hidden" not in text and "ghp_" not in text
assert len(api.posts) == 3 and len(sleeps) == 2, (len(api.posts), sleeps)
url, headers, body = api.posts[-1]
assert url == "https://integrate.api.nvidia.com/v1/chat/completions" and headers["User-Agent"] == "tradebot-paper-research/1.0"
assert body["temperature"] <= 0.3 and "someone@example.com" not in json.dumps(body)
assert "never suggest loosening" in body["messages"][0]["content"] and "advice only" in body["messages"][0]["content"]
ai.ask("check-summary", "s", "u")
try:
    ai.ask("check-summary", "s", "u"); raise SystemExit("budget not enforced")
except RuntimeError as e:
    assert "budget" in str(e)
try:
    B.AI(key="", sleep=sleeps.append).ask("diagnose", "s", "u"); raise SystemExit("ran without a key")
except RuntimeError as e:
    assert "missing" in str(e)
api2 = FakeAPI(["x/embed"]); B.http_get, B.http_post = api2.get, api2.post
try:
    B.AI(key="k123456789", sleep=sleeps.append).ask("code-fix", "s", "u"); raise SystemExit("no model should fit")
except RuntimeError as e:
    assert "no model" in str(e) and not api2.posts
api3 = FakeAPI(ALL, fail=10); B.http_get, B.http_post = api3.get, api3.post
try:
    B.AI(key="k123456789", sleep=sleeps.append).ask("diagnose", "s", "u"); raise SystemExit("should give up")
except RuntimeError:
    assert len(api3.posts) == 4, "limited retries"

# ---- issue logic
assert B.issue_action(2, []) == ("create", None, [])
assert B.issue_action(2, [dict(number=7)]) == ("update", 7, [])
assert B.issue_action(2, [dict(number=9), dict(number=7)]) == ("update", 7, [9])
assert B.issue_action(0, [dict(number=7)]) == ("close", 7, [])
assert B.issue_action(0, []) == ("none", None, [])
assert B.issue_title(dict(generated_at_la_paz="2026-11-26 14:00", problems=["a", "b"])) == "Backup AI: 2026-11-26 2 problems"
assert B.issue_title(dict(generated_at_la_paz="2026-11-26 14:00", problems=["a"])) == "Backup AI: 2026-11-26 1 problem"

OPEN_ISSUES = []
def issue_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    if cmd[:3] == ["gh", "issue", "list"]:
        calls.append(list(cmd)); return 0, json.dumps(OPEN_ISSUES), ""
    if cmd[:3] in (["gh", "issue", "create"], ["gh", "issue", "edit"]):
        body = open(cmd[cmd.index("--body-file") + 1]).read()
        assert "ghp_" not in body and "nvapi-" not in body
        calls.append(list(cmd) + ["BODY:" + body]); return 0, "", ""
    return fake_run(cmd, cwd, env, timeout, input_text)


B.run = issue_run
del calls[:]
st, text = B.report(B.AI(key=""))     # no key: non-AI report, issue still opened
assert "NVIDIA_API_KEY is missing" in text and st["ai"]["used"] is False and st["issue"] == "create"
assert any(c[:3] == ["gh", "issue", "create"] and "backup-ai" in c for c in calls)
OPEN_ISSUES[:] = [dict(number=5, title="old")]
api = FakeAPI(ALL); B.http_get, B.http_post = api.get, api.post
st, text = B.report(B.AI(key="k123456789", sleep=sleeps.append))
assert st["issue"] == "update" and st["ai"]["model"] == "deepseek-ai/deepseek-r1" and st["ai"]["task"] == "diagnose"
edit = [c for c in calls if c[:3] == ["gh", "issue", "edit"]][-1]
assert "5" in edit and "deepseek-ai/deepseek-r1" in edit[-1], "the model used is named in the issue"
sent = api.posts[-1][2]["messages"][1]["content"]
assert "ghp_" not in sent and "line" in sent, "failed log sent, redacted"
GH["live20.yml"] = [runrec(13)]
B.check()
del calls[:]
st, text = B.report(B.AI(key="k123456789", sleep=sleeps.append))
assert st["issue"] == "close" and st["ai"]["task"] == "check-summary" and st["ai"]["model"] == "meta/llama-3.1-8b-instruct"
assert any(c[:3] == ["gh", "issue", "close"] and "5" in c for c in calls)
assert json.load(open(os.path.join(B.STATUS_DIR, "status.json")))["ai"]["model"] == "meta/llama-3.1-8b-instruct"

# ---- rerun: allowlist, newest run only, first attempt, recent, never twice
assert "live20.yml" in B.RERUN_ALLOW and "plan19.yml" in B.RERUN_ALLOW and "tradebot-settle.yml" in B.RERUN_ALLOW
for never in ("plan10.yml", "plan15.yml", "plan16.yml", "plan17.yml", "plan18.yml", "plan20.yml", "backup-ai.yml",
              "trial-scan-backstop.yml"):
    assert never not in B.RERUN_ALLOW, never


def wrow(f, latest, completed, state="failed"):
    return dict(file=f, state=state, latest=B._run_summary(latest), latest_completed=B._run_summary(completed))


f1 = runrec(21, concl="failure", ago_min=30)
fake_st = dict(workflows=[wrow("live20.yml", f1, f1), wrow("plan20.yml", runrec(22, concl="failure"), runrec(22, concl="failure")),
                          wrow("plan19.yml", runrec(24, status="queued", concl=None), runrec(23, concl="failure")),
                          wrow("probe19.yml", runrec(25, concl="failure", attempt=2), runrec(25, concl="failure", attempt=2)),
                          wrow("tradebot-settle.yml", runrec(26, concl="failure", ago_min=60 * 13), runrec(26, concl="failure", ago_min=60 * 13)),
                          wrow("plan5-lip.yml", runrec(27), runrec(27), state="ok")])
assert B.rerun_candidates(fake_st, [], T) == [dict(workflow="live20.yml", run_id=21)]
assert B.rerun_candidates(fake_st, [dict(run_id=21)], T) == []
B.ROOT = root
del calls[:]
B.run = fake_run
out = B.rerun(fake_st)
assert [c["run_id"] for c in out] == [21] and ["gh", "run", "rerun", "21", "--failed"] in calls
assert B.rerun(fake_st) == [], "never the same run twice"
assert json.load(open(os.path.join(B.STATUS_DIR, "reruns.json")))[0]["run_id"] == 21
open(os.path.join(root, "kill.txt"), "w").close()
assert B.kill_present() and B.rerun(dict(workflows=[wrow("live20.yml", runrec(31, concl="failure"), runrec(31, concl="failure"))])) == []
os.remove(os.path.join(root, "kill.txt"))


# ---- fix: a real throwaway git repository with a bare "origin"
def git(args, cwd):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


repo, bare = os.path.join(OUT, "repo"), os.path.join(OUT, "origin.git")
os.makedirs(os.path.join(repo, "tests")); os.makedirs(os.path.join(repo, "research"))
git(["init", "-q", "--bare", bare], OUT)
git(["init", "-q", "-b", "main"], repo)
open(os.path.join(repo, "freshness.py"), "w").write("def f():\n    return 1 / 0\n")
open(os.path.join(repo, "live.py"), "w").write("X = 1\n")
open(os.path.join(repo, "tests", "run_all.py"), "w").write(
    "import os, sys\nassert not any('TOKEN' in k or 'NVIDIA' in k for k in os.environ), 'secret in test env'\n"
    "sys.path.insert(0, os.getcwd())\nimport freshness\nprint('All tests passed', freshness.f())\n")
git(["-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], repo)
git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "start"], repo)
git(["remote", "add", "origin", bare], repo)
git(["push", "-q", "origin", "main"], repo)
B.ROOT = repo
B.STATUS_DIR = os.path.join(OUT, "status_fix")


def commit_at(msg, when):
    open(os.path.join(repo, "note.txt"), "a").write(msg + "\n")
    env = dict(os.environ, GIT_COMMITTER_DATE=B.iso(when), GIT_AUTHOR_DATE=B.iso(when))
    git(["add", "-A"], repo)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg], cwd=repo, env=env, check=True)
    git(["push", "-q", "origin", "main"], repo)


GOOD = "CAUSE: division by zero in f\n```diff\ndiff --git a/freshness.py b/freshness.py\n--- a/freshness.py\n+++ b/freshness.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1 / 0\n+    return 1\n```\n"
BAD = "CAUSE: x\n```diff\ndiff --git a/live.py b/live.py\n--- a/live.py\n+++ b/live.py\n@@ -1 +1 @@\n-X = 1\n+X = 2\n```\n"
PRS, PR_CREATES = [], []


def fix_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    if cmd[0] == "gh":
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            return 0, json.dumps(PRS), ""
        if cmd[:3] == ["gh", "pr", "create"]:
            body = open(cmd[cmd.index("--body-file") + 1]).read()
            PR_CREATES.append((cmd, body)); return 0, "https://github.com/o/r/pull/1\n", ""
        if cmd[:3] == ["gh", "run", "view"]:
            return 0, 'Traceback\n  File "/home/runner/work/tradebot/tradebot/freshness.py", line 2, in f\nZeroDivisionError\n', ""
        return 0, "", ""
    return real_run(cmd, cwd=cwd or repo, env=env, timeout=timeout, input_text=input_text)


B.run = fix_run
os.environ["GH_TOKEN"] = "ghs_faketoken1234567890abcdef"
fst = dict(workflows=[dict(file="live20.yml", state="failed", latest_completed=dict(id=41), latest=dict(id=41)),
                      dict(file="plan19.yml", state="failed", latest_completed=dict(id=42), latest=dict(id=42))])

assert B.related_files('File "/home/runner/work/tradebot/tradebot/freshness.py", line 2\n  research/none.py tests/run_all.py', repo) == ["freshness.py", "tests/run_all.py"]
commit_at("work\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", T - timedelta(hours=3))
assert B.claude_active(T, "main") is True
api = FakeAPI(ALL + ["qwen/qwen3-coder-480b-a35b-instruct"]); B.http_get, B.http_post = api.get, api.post
assert B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append)).startswith("skipped: Claude"), "Claude active: no fix"
assert not api.posts
commit_at("later work by the runner", T - timedelta(hours=1))
assert B.claude_active(T + timedelta(hours=22), "main") is False, "the Claude commit is now 25 hours old"
assert B.claude_active(T, "no-such-ref") is True, "fails closed"
B.now = lambda: T + timedelta(hours=22)


# the model proposes a change to live.py: refused, nothing pushed
def answer(text):
    def post(url, headers, body, timeout):
        api.posts.append((url, headers, body))
        return 200, {}, json.dumps(dict(choices=[dict(message=dict(content=text))]))
    return post


B.http_post = answer(BAD)
res = B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append))
assert res.startswith("refused") and "live.py" in res, res
assert not PR_CREATES and "backup-ai" not in git(["ls-remote", "--heads", bare], repo)
assert api.posts[-1][2]["model"] == "qwen/qwen3-coder-480b-a35b-instruct", "code-fix tier"

# next failing workflow (live20's run 41 is recorded as tried): a good diff becomes a branch and a pull request
B.http_post = answer(GOOD)
res = B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append))
assert res.startswith("pull request opened"), res
cmd, body = PR_CREATES[-1]
assert "--base" in cmd and "main" in cmd and "backup-ai/fix-42" in cmd and "backup-ai" in cmd
assert "Do not merge without review" in body and "qwen/qwen3-coder-480b-a35b-instruct" in body
assert "backup-ai-workflow: plan19.yml" in body and "All tests passed" in body and "exit 0" in body
assert "[plan19.yml]" in cmd[cmd.index("--title") + 1] and cmd[cmd.index("--title") + 1].startswith("Backup AI fix proposal: ")
assert "backup-ai/fix-42" in git(["ls-remote", "--heads", bare], repo)
assert git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip() == "main" and "1 / 0" in open(os.path.join(repo, "freshness.py")).read(), \
    "main's working tree is untouched"
assert "Co-Authored-By: Claude" not in git(["log", "-1", "--format=%B", "backup-ai/fix-42"], repo)
assert not any(c[:3] == ["gh", "pr", "merge"] for c in calls)
tried = json.load(open(os.path.join(B.STATUS_DIR, "fixes.json")))
assert [t["run_id"] for t in tried] == [41, 42] and tried[1]["model"] == "qwen/qwen3-coder-480b-a35b-instruct"
# never twice, and at most one open pull request per workflow
n = len(PR_CREATES)
assert B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append)) == "nothing to fix" and len(PR_CREATES) == n
assert B.fix_candidates(dict(workflows=[dict(file="plan19.yml", state="failed", latest_completed=dict(id=99))]), [],
                        {"plan19.yml"}) == []
PRS[:] = [dict(number=1, title="Backup AI fix proposal: [live20.yml] x", body="", headRefName="backup-ai/fix-1")]
assert B.open_fix_workflows() == {"live20.yml"}
assert B.fix(fst, B.AI(key="")) == "skipped: NVIDIA_API_KEY is missing"
os.environ.pop("GH_TOKEN", None)
B.run = real_run

print("backup AI operator: all checks passed")
