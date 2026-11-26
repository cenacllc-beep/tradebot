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
GH_COPY = os.path.join(WORK, ".github", "workflows", "backup-ai.yml")
CLOUD_COPY = os.path.join(WORK, "cloud", "workflows", "backup-ai.yml")
assert os.path.exists(CLOUD_COPY), CLOUD_COPY
if os.path.exists(GH_COPY):      # created only when the operator is switched on; then it must equal the cloud copy
    assert open(GH_COPY, "rb").read() == open(CLOUD_COPY, "rb").read(), "the two workflow copies must be identical"
wf = open(CLOUD_COPY, encoding="utf-8").read()
for need in ('cron: "37 */3 * * *"', "group: tradebot-backup-ai", "cancel-in-progress: false", "timeout-minutes: 30",
             "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}", "requests==2.32.3", "persist-credentials: false",
             "issues: write", "pull-requests: write", "actions: write", "TZ: America/La_Paz", "push-status",
             "test-proposal", "publish", "backup-ai-proposal"):
    assert need in wf, need
assert "@v" not in wf.replace("# v", ""), "actions pinned by SHA"
for u in re.findall(r"uses:\s*(\S+)", wf):
    assert re.match(r"^actions/[a-z\-]+@[0-9a-f]{40}$", u), u
assert "git add -A" not in wf and "pr merge" not in wf


def job(name):
    """The text of one job of the workflow (from '  name:' to the next job)."""
    m = re.search(r"(?ms)^  %s:\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)" % re.escape(name), wf.split("\njobs:\n", 1)[1])
    assert m, name
    return m.group(1)


assert re.search(r"(?m)^permissions: \{\}$", wf), "nothing granted at the workflow level"
ops_job, st_job, test_job, pub_job = job("operate"), job("status"), job("test"), job("publish")
# (a) the job that runs proposed code: no permissions, no secret, no token, no stored credentials
assert re.search(r"(?m)^    permissions: \{\}$", test_job), "test job: permissions: {}"
for bad in ("secrets.", "github.token", "GH_TOKEN", "GITHUB_TOKEN", "NVIDIA", "contents: write", "persist-credentials: true"):
    assert bad not in test_job, "test job must not have " + bad
assert "persist-credentials: false" in test_job and "test-proposal" in test_job and "needs: [operate, status]" in test_job
# the jobs holding a token or the key never run the tests or apply anything themselves
for j in (ops_job, st_job, pub_job):
    assert "run_all" not in j and "test-proposal" not in j
assert "pip install" not in pub_job and "pip install" not in st_job
assert "NVIDIA" not in st_job and "NVIDIA" not in pub_job and "secrets." not in pub_job and "secrets." not in st_job
assert "contents: read" in ops_job and "contents: write" not in ops_job
assert "contents: write" in pub_job and "pull-requests: write" in pub_job and "needs.test.result == 'success'" in pub_job
assert "contents: write" in st_job and "pull-requests" not in st_job
for j in (ops_job, st_job, test_job, pub_job):
    assert "persist-credentials: false" in j
# 1(a)-(c): artifacts are checked against operate's job outputs; status runs before test; no upload overwrites
assert not re.search(r"(?m)^\s*overwrite\s*:", wf), "no artifact upload may overwrite"
for o in ("diff_sha256: ${{ steps.op.outputs.diff_sha256 }}", "meta_sha256: ${{ steps.op.outputs.meta_sha256 }}",
          "status_sha256: ${{ steps.sh.outputs.status_sha256 }}", "status-hash ops/status"):
    assert o in ops_job, o
assert re.search(r"(?m)^    needs: \[operate, status\]", test_job), "test runs after status"
assert "STATUS_SHA256: ${{ needs.operate.outputs.status_sha256 }}" in st_job and '"$STATUS_SHA256"' in st_job
for j in (test_job, pub_job):
    assert "DIFF_SHA256: ${{ needs.operate.outputs.diff_sha256 }}" in j and "META_SHA256: ${{ needs.operate.outputs.meta_sha256 }}" in j
    assert '"$DIFF_SHA256" "$META_SHA256"' in j
    assert "needs.operate.result == 'success'" in j
assert "${{" not in "".join(l for l in wf.splitlines(True) if l.strip().startswith("run:")), "no expressions inside run lines"

# ---- (e) live.py's import closure is computed with ast and denied, whatever the allowlist says
cl = B.live_closure(WORK)
for m in ("live.py", "config.py", "kalshi.py", "core.py", "strategy.py"):
    assert m in cl, (m, cl)
for m in cl:
    assert B.protected(m), "imported by live.py, must be protected: " + m
fake = os.path.join(OUT, "closure"); os.makedirs(os.path.join(fake, "tbcommon")); os.makedirs(os.path.join(fake, "research"))
open(os.path.join(fake, "live.py"), "w").write("import os\nimport freshness\nfrom tbcommon import clock\n"
                                              "def f():\n    import importlib\n    importlib.import_module('research.micro')\n")
open(os.path.join(fake, "freshness.py"), "w").write("from marks import x\n")
open(os.path.join(fake, "marks.py"), "w").write("x = 1\n")
open(os.path.join(fake, "check.py"), "w").write("x = 1\n")
open(os.path.join(fake, "tbcommon", "__init__.py"), "w").write("")
open(os.path.join(fake, "tbcommon", "clock.py"), "w").write("from . import http\n")
open(os.path.join(fake, "tbcommon", "http.py"), "w").write("")
open(os.path.join(fake, "research", "micro.py"), "w").write("")
assert B.live_closure(fake) == ["freshness.py", "live.py", "marks.py", "research/micro.py", "tbcommon/__init__.py",
                                "tbcommon/clock.py", "tbcommon/http.py"], B.live_closure(fake)
_root = B.ROOT
B.ROOT = fake
for m in ("freshness.py", "marks.py", "tbcommon/clock.py", "tbcommon/http.py", "research/micro.py"):
    assert B.protected(m) == "imported by live.py", (m, B.protected(m))
assert B.protected("check.py") is None, "not imported by live.py: still editable"
os.remove(os.path.join(fake, "live.py"))
B._CLOSURE.clear()
assert B.live_closure(fake) is None and "fail closed" in B.protected("check.py"), "missing live.py: refuse all"
open(os.path.join(fake, "live.py"), "w").write("def (:\n")
B._CLOSURE.clear()
assert "fail closed" in B.protected("check.py"), "unparsable live.py: refuse all"
B.ROOT = _root
B._CLOSURE.clear()


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
# 2: strict sections: diff --git a/X b/X with the same X, ---/+++ exactly a/X and b/X, hunks counted
assert B.check_diff(d("freshness.py", "check.py")), "different a/ and b/ names"
assert B.check_diff("diff --git a/check.py b/check.py\n--- check.py\n+++ check.py\n@@ -1 +1 @@\n-x\n+y\n"), "no a/ b/ prefix"
assert B.check_diff("diff --git a/check.py b/check.py\n--- a/check.py\n+++ b/marks.py\n@@ -1 +1 @@\n-x\n+y\n")
assert B.check_diff("diff --git a/check.py b/check.py\n--- a/live.py\n+++ b/live.py\n@@ -1 +1 @@\n-x\n+y\n")
assert B.check_diff("--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n-x\n+y\n"), "no diff --git header"
assert B.check_diff("junk\n" + d("check.py")), "text before the first header"
assert B.check_diff(d("check.py") + "--- a/live.py\n+++ b/live.py\n@@ -1 +1 @@\n-x\n+y\n"), "a second file without a header"
assert B.check_diff(d("check.py") + d("check.py")), "the same file twice"
assert B.check_diff("diff --git a/check.py b/check.py\n--- a/check.py\n+++ b/check.py\n@@ -1,2 +1,2 @@\n-x\n+y\n"), "short hunk"
assert B.check_diff("diff --git a/check.py b/check.py\n--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n-x\n+y\n+z\n"), "long hunk"
# a removed line that starts with "-- " is a hunk line, not a file header
ok = "diff --git a/check.py b/check.py\n--- a/check.py\n+++ b/check.py\n@@ -1,2 +1,2 @@\n--- a/live.py\n+x\n \n"
assert B.diff_paths(ok) == (["check.py"], []), B.diff_paths(ok)
assert B.check_diff("diff --git a/check.py b/check.py\nindex 0123456..89abcde 100644\n--- a/check.py\n+++ b/check.py\n"
                    "@@ -1 +1 @@\n-x\n+y\n\\ No newline at end of file\n") == []
# 3: new files are refused outright
assert any("new file" in p for p in B.check_diff("diff --git a/check.py b/check.py\nnew file mode 100644\n--- /dev/null\n+++ b/check.py\n@@ -0,0 +1 @@\n+x\n"))
assert any("new file" in p for p in B.check_diff("diff --git a/marks.py b/marks.py\n--- /dev/null\n+++ b/marks.py\n@@ -0,0 +1 @@\n+x\n"))
assert B.check_diff("diff --git a/marks.py b/marks.py\n--- a/marks.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
# the review's scratch repository: a `--- tbcommon/config.py` diff that git applies at -p1 to the root config.py
scr = os.path.join(OUT, "scratch_p1"); os.makedirs(os.path.join(scr, "tbcommon"))
subprocess.run(["git", "init", "-q", scr], check=True)
open(os.path.join(scr, "config.py"), "w").write("LIMIT = 1\n")
open(os.path.join(scr, "tbcommon", "x.py"), "w").write("\n")
p1 = "--- tbcommon/config.py\n+++ tbcommon/config.py\n@@ -1 +1 @@\n-LIMIT = 1\n+LIMIT = 9\n"
open(os.path.join(OUT, "p1.diff"), "w").write(p1)
r = subprocess.run(["git", "apply", "--check", os.path.join(OUT, "p1.diff")], cwd=scr, capture_output=True, text=True)
assert r.returncode == 0, "git applies it to the root config.py at -p1: " + r.stderr
assert B.check_diff(p1), "must be refused"
p1g = "diff --git a/tbcommon/config.py b/tbcommon/config.py\n" + p1
assert B.check_diff(p1g), "must be refused with a diff --git header too"
assert B.check_diff("diff --git a/tbcommon/config.py b/tbcommon/config.py\n--- a/config.py\n+++ b/config.py\n@@ -1 +1 @@\n-LIMIT = 1\n+LIMIT = 9\n")
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
assert all("--branch" in c and c[c.index("--branch") + 1] == "main" for c in calls if c[:3] == ["gh", "run", "list"]), "S2: main only"
assert B.judge_workflow(hourly, [dict(runrec(5, concl="failure"), headBranch="feature")], T)["state"] == "no-runs"
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

class Clock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


clk = Clock()
timeouts = []


def slow_post(url, headers, body, timeout):
    timeouts.append(timeout); clk.t += timeout
    return 0, {}, "timeout"


api4 = FakeAPI(ALL); B.http_get, B.http_post = api4.get, slow_post
ai4 = B.AI(key="k123456789", sleep=lambda w: setattr(clk, "t", clk.t + w), clock=clk)
try:
    ai4.ask("diagnose", "s", "u"); raise SystemExit("time budget not enforced")
except RuntimeError as e:
    assert "budget" in str(e) or "HTTP" in str(e)
assert timeouts and max(timeouts) <= B.AI_REQUEST_SECONDS == 90, timeouts
assert clk.t <= B.AI_TOTAL_SECONDS == 360, clk.t
try:
    ai4.ask("diagnose", "s", "u"); raise SystemExit("time budget not enforced")
except RuntimeError as e:
    assert "budget" in str(e)
B.http_get, B.http_post = api.get, api.post

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

def failing_issue_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    if cmd[:3] in (["gh", "issue", "create"], ["gh", "issue", "edit"], ["gh", "issue", "close"]):
        return 1, "", "HTTP 403: Resource not accessible by integration"
    return issue_run(cmd, cwd, env, timeout, input_text)


B.run = failing_issue_run
OPEN_ISSUES[:] = []
fst0 = dict(generated_at="x", generated_at_la_paz="2026-11-26 14:00", key_present=False, workflows=[], data=[],
            problems=["live20.yml: failed"], errors=[])
assert B.sync_issue(fst0, "t") == "error" and any("could not create its issue" in p for p in fst0["problems"])
OPEN_ISSUES[:] = [dict(number=5, title="old")]
fst0["problems"] = []
assert B.sync_issue(fst0, "t") == "error" and any("could not close issue #5" in p for p in fst0["problems"])
OPEN_ISSUES[:] = []
B.run = issue_run

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
def failing_rerun(cmd, cwd=None, env=None, timeout=300, input_text=None):
    if cmd[:3] == ["gh", "run", "rerun"]:
        calls.append(list(cmd)); return 1, "", "HTTP 403"
    return fake_run(cmd, cwd, env, timeout, input_text)


B.run = failing_rerun
fst1 = dict(generated_at=None, workflows=[wrow("probe18.yml", runrec(32, concl="failure"), runrec(32, concl="failure"))], problems=[])
out = B.rerun(fst1)
assert out and out[0]["ok"] is False and any("re-run of probe18.yml run 32 failed" in p for p in fst1["problems"])
# S4: rerun needs no AI, so main() re-runs without the key
B.run = fake_run
GH["live20.yml"] = [runrec(33, concl="failure", ago_min=20)]
B.WORKFLOW_DIR = wfdir
del calls[:]
assert B.main(["rerun"]) == 0 and ["gh", "run", "rerun", "33", "--failed"] in calls, "rerun without NVIDIA_API_KEY"
open(os.path.join(root, "kill.txt"), "w").close()
assert B.kill_present() and B.rerun(dict(workflows=[wrow("live20.yml", runrec(31, concl="failure"), runrec(31, concl="failure"))])) == []
os.remove(os.path.join(root, "kill.txt"))


# ---- fix: propose (operate job), test (no token), publish (no proposed code run), on throwaway git repositories
def git(args, cwd, env=None):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


ID = ["-c", "user.name=t", "-c", "user.email=t@t"]
repo, bare = os.path.join(OUT, "repo"), os.path.join(OUT, "origin.git")
os.makedirs(os.path.join(repo, "tests")); os.makedirs(os.path.join(repo, "research"))
git(["init", "-q", "--bare", bare], OUT)
git(["symbolic-ref", "HEAD", "refs/heads/main"], bare)
git(["init", "-q", "-b", "main"], repo)
open(os.path.join(repo, "freshness.py"), "w").write("def f():\n    return 1 / 0\n")
open(os.path.join(repo, "live.py"), "w").write("X = 1\n")
open(os.path.join(repo, ".gitignore"), "w").write("*.log\n")
open(os.path.join(repo, "tests", "run_all.py"), "w").write(
    "import os, sys\nassert not any('TOKEN' in k or 'NVIDIA' in k for k in os.environ), 'secret in test env'\n"
    "sys.path.insert(0, os.getcwd())\nimport freshness\nprint('All tests passed', freshness.f())\n")
git(ID + ["add", "-A"], repo)
git(ID + ["commit", "-q", "-m", "start"], repo)
git(["remote", "add", "origin", bare], repo)
git(["push", "-q", "origin", "main"], repo)
B.ROOT = repo
B._CLOSURE.clear()
B.STATUS_DIR = os.path.join(OUT, "status_fix")


def commit_at(msg, when):
    open(os.path.join(repo, "note.txt"), "a").write(msg + "\n")
    env = dict(os.environ, GIT_COMMITTER_DATE=B.iso(when), GIT_AUTHOR_DATE=B.iso(when))
    git(["add", "-A"], repo)
    subprocess.run(["git"] + ID + ["commit", "-q", "-m", msg], cwd=repo, env=env, check=True)
    git(["push", "-q", "origin", "main"], repo)


GOOD = "CAUSE: division by zero in f\n```diff\ndiff --git a/freshness.py b/freshness.py\n--- a/freshness.py\n+++ b/freshness.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1 / 0\n+    return 1\n```\n"
BAD = "CAUSE: x\n```diff\ndiff --git a/live.py b/live.py\n--- a/live.py\n+++ b/live.py\n@@ -1 +1 @@\n-X = 1\n+X = 2\n```\n"
PRS, PR_CREATES, ALLCMDS, FAIL_PR, OPEN_PR_HEADS = [], [], [], [], []


def fix_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    ALLCMDS.append(list(cmd))
    if cmd[0] == "gh":
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            if "--head" in cmd:
                h = cmd[cmd.index("--head") + 1]
                return 0, json.dumps([dict(number=3, url="u")] if h in OPEN_PR_HEADS else []), ""
            return 0, json.dumps(PRS), ""
        if cmd[:3] == ["gh", "pr", "create"]:
            if FAIL_PR:
                FAIL_PR.pop(); return 1, "", "HTTP 502"
            body = open(cmd[cmd.index("--body-file") + 1]).read()
            PR_CREATES.append((cmd, body)); return 0, "https://github.com/o/r/pull/1\n", ""
        if cmd[:3] == ["gh", "run", "view"]:
            return 0, 'Traceback\n  File "/home/runner/work/tradebot/tradebot/freshness.py", line 2, in f\nZeroDivisionError\n', ""
        return 0, "", ""
    return real_run(cmd, cwd=cwd or B.ROOT, env=env, timeout=timeout, input_text=input_text)


B.run = fix_run
os.environ["GH_TOKEN"] = "ghs_faketoken1234567890abcdef"
fst = dict(workflows=[dict(file="live20.yml", state="failed", latest_completed=dict(id=41, event="schedule"), latest=dict(id=41)),
                      dict(file="plan19.yml", state="failed", latest_completed=dict(id=42, event="workflow_dispatch"), latest=dict(id=42)),
                      dict(file="probe18.yml", state="failed", latest_completed=dict(id=43, event="push"), latest=dict(id=43)),
                      dict(file="probe19.yml", state="failed", latest_completed=dict(id=44, event="schedule", branch="dev"), latest=dict(id=44))])
# S2: only scheduled or hand-started runs on main
assert [c["run_id"] for c in B.fix_candidates(fst, [], set())] == [41, 42]

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


def answer(text):
    def post(url, headers, body, timeout):
        api.posts.append((url, headers, body))
        return 200, {}, json.dumps(dict(choices=[dict(message=dict(content=text))]))
    return post


prop = os.path.join(OUT, "proposal")
# the model proposes a change to live.py: refused, nothing written
B.http_post = answer(BAD)
res = B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append), out_dir=prop)
assert res.startswith("refused") and "live.py" in res, res
assert not os.path.exists(prop) and not PR_CREATES
assert api.posts[-1][2]["model"] == "qwen/qwen3-coder-480b-a35b-instruct", "code-fix tier"

# next failing workflow (live20's run 41 is recorded as tried): a good diff is only PROPOSED in the operate job
B.http_post = answer(GOOD)
del ALLCMDS[:]
GHOUT = os.path.join(OUT, "github_output"); os.environ["GITHUB_OUTPUT"] = GHOUT
res = B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append), out_dir=prop)
del os.environ["GITHUB_OUTPUT"]
assert res.startswith("proposed for testing on branch backup-ai/fix-42"), res
outs = dict(l.split("=", 1) for l in open(GHOUT).read().split())
assert outs["proposed"] == "true" and outs["diff_sha256"] == B._file_sha256(os.path.join(prop, "fix.diff"))
assert outs["meta_sha256"] == B._file_sha256(os.path.join(prop, "meta.json"))
H = (outs["diff_sha256"], outs["meta_sha256"])


def hashes(pdir):
    """What operate would have output for this proposal folder."""
    return B._file_sha256(os.path.join(pdir, "fix.diff")), B._file_sha256(os.path.join(pdir, "meta.json"))
meta = json.load(open(os.path.join(prop, "meta.json")))
assert meta["paths"] == ["freshness.py"] and meta["branch"] == "backup-ai/fix-42" and meta["workflow"] == "plan19.yml"
assert meta["model"] == "qwen/qwen3-coder-480b-a35b-instruct" and meta["base_sha"] == git(["rev-parse", "HEAD"], repo).strip()
assert not any("run_all.py" in " ".join(c) or c[:2] == ["git", "commit"] or "push" in c or c[:3] == ["gh", "pr", "create"]
               or (c[:2] == ["git", "apply"] and "--check" not in c) for c in ALLCMDS), "operate runs and applies nothing"
assert "1 / 0" in open(os.path.join(repo, "freshness.py")).read() and git(["status", "--porcelain"], repo) == "", \
    "the operate job's work tree is untouched"
assert "backup-ai" not in git(["ls-remote", "--heads", bare], repo) and not PR_CREATES
tried = json.load(open(os.path.join(B.STATUS_DIR, "fixes.json")))
assert [t["run_id"] for t in tried] == [41, 42] and tried[1]["model"] == "qwen/qwen3-coder-480b-a35b-instruct"
assert B.fix(fst, B.AI(key="k123456789", sleep=sleeps.append), out_dir=os.path.join(OUT, "p2")) == "nothing to fix"


def checkout(name, sha=None):
    d = os.path.join(OUT, name)
    git(["clone", "-q", bare, d], OUT)
    if sha:
        git(["checkout", "-q", sha], d)
    return d


# test job: a fresh checkout at the base commit, no token in the tests' environment
res_dir = os.path.join(OUT, "result")
tj = checkout("testjob", meta["base_sha"])
assert B.test_proposal(prop, res_dir, *H, root=tj) == 0, open(os.path.join(res_dir, "result.json")).read()
result = json.load(open(os.path.join(res_dir, "result.json")))
assert result["ok"] and result["tests_rc"] == 0 and result["files"] == ["freshness.py"] and "All tests passed" in result["tail"]

# (b) tests that change another file (tracked, untracked or ignored) are refused
for k, extra in enumerate(("open('extra.txt','w').write('x')\n", "open('debug.log','w').write('x')\n",
                           "open('live.py','a').write('#')\n")):
    cj = checkout("changes%d" % k)
    open(os.path.join(cj, "tests", "run_all.py"), "a").write(extra)
    git(ID + ["commit", "-q", "-am", "tests write a file"], cj)
    r_dir = os.path.join(OUT, "r%d" % k)
    assert B.test_proposal(prop, r_dir, *H, root=cj) == 1, extra
    rr = json.load(open(os.path.join(r_dir, "result.json")))
    assert not rr["ok"] and any("outside the diff" in p for p in rr["problems"]) and len(rr["files"]) == 2, rr
# failing tests are not passed on
fj = checkout("failing")
open(os.path.join(fj, "tests", "run_all.py"), "a").write("raise SystemExit(1)\n")
git(ID + ["commit", "-q", "-am", "fail"], fj)
assert B.test_proposal(prop, os.path.join(OUT, "rf"), *H, root=fj) == 1
# the 300 s limit: the whole process group is stopped
sj = checkout("slow")
open(os.path.join(sj, "tests", "run_all.py"), "w").write("import subprocess, time\nsubprocess.Popen(['sleep', '60'])\ntime.sleep(60)\n")
import time as _time
t0 = _time.time()
rc, outp = B.run_tests(sj, timeout=2)
assert rc == 124 and _time.time() - t0 < 20 and "limit" in outp
assert B.TEST_SECONDS == 300
# 1(d): the process group is killed after the tests finish normally too (a background child left behind)
kj = checkout("leftover")
pidf = os.path.join(OUT, "leftover.pid")
open(os.path.join(kj, "tests", "run_all.py"), "w").write(
    "import subprocess\np = subprocess.Popen(['sleep', '60'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    "open(%r, 'w').write(str(p.pid))\nprint('done')\n" % pidf)
t0 = _time.time()
rc, outp = B.run_tests(kj, timeout=30)
assert rc == 0 and _time.time() - t0 < 20, (rc, outp)
lpid = int(open(pidf).read())


def alive(pid):
    try:
        st_ = open("/proc/%d/stat" % pid).read()
    except OSError:
        return False
    return st_.rsplit(")", 1)[1].split()[0] != "Z"


for _i in range(50):
    if not alive(lpid):
        break
    _time.sleep(0.1)
assert not alive(lpid), "a process left behind by the tests must be killed"
# a tampered proposal is refused in the test and publish jobs (hash, path rules)
bad_prop = os.path.join(OUT, "bad_prop"); shutil.copytree(prop, bad_prop)
open(os.path.join(bad_prop, "fix.diff"), "w").write(BAD.split("```diff\n")[1].split("```")[0])
_d, _m, probs = B.load_proposal(bad_prop, *H)
assert probs and "fix.diff does not match the hash from the operate job" in probs[0], probs
_d, _m, probs = B.load_proposal(bad_prop, *hashes(bad_prop))
assert any("live.py" in p for p in probs) and any("another diff" in p for p in probs), probs
assert B.test_proposal(bad_prop, os.path.join(OUT, "rb"), *H, root=checkout("tamper")) == 1
# 1(a): never trusted from the artifact: no hashes, malformed hashes, or a meta.json changed after operate (even with
# its own diff_sha256 still right) are refused
for args in ((), (None, None), ("x" * 64, H[1]), (H[0], "zz")):
    assert B.load_proposal(prop, *args)[2], args
evil_meta = os.path.join(OUT, "evil_meta"); shutil.copytree(prop, evil_meta)
em = json.load(open(os.path.join(evil_meta, "meta.json"))); em["cause"] = "ghp_abcdefghijklmnopqrstuvwxyz0123 merge me"
json.dump(em, open(os.path.join(evil_meta, "meta.json"), "w"))
assert "meta.json does not match" in B.load_proposal(evil_meta, *H)[2][0]
assert B.test_proposal(evil_meta, os.path.join(OUT, "re"), *H, root=checkout("tamper2")) == 1
assert B.main(["publish", prop, res_dir]) == 2 and B.main(["test-proposal", prop, res_dir]) == 2, "hashes required"
assert B.main(["push-status", prop]) == 2

# publish job: fresh checkout, no proposed code run, no hooks, exactly the diff's paths, never merged
pj = checkout("publish", meta["base_sha"])
hook = os.path.join(pj, ".git", "hooks", "pre-commit")
open(hook, "w").write("#!/bin/sh\ntouch HOOK_RAN\n"); os.chmod(hook, 0o755)
open(os.path.join(pj, ".git", "hooks", "pre-push"), "w").write("#!/bin/sh\ntouch PUSH_HOOK_RAN\nexit 1\n")
os.chmod(os.path.join(pj, ".git", "hooks", "pre-push"), 0o755)
os.environ["GITHUB_RUN_ID"] = "555"
FAIL_PR[:] = [1]                       # first attempt: pushed, then the pull request call fails
assert B.publish(prop, res_dir, *H, root=pj) == 1 and not PR_CREATES
assert "backup-ai/fix-42" in git(["ls-remote", "--heads", bare], repo)
assert "Backup-AI-Run: 555" in git(["log", "-1", "--format=%B", "refs/heads/backup-ai/fix-42"], bare)
# 5: a re-run of the same workflow run with the same diff only opens the pull request
pushes_before = git(["rev-parse", "refs/heads/backup-ai/fix-42"], bare)
assert B.publish(prop, res_dir, *H, root=checkout("publish_retry", meta["base_sha"])) == 0
assert git(["rev-parse", "refs/heads/backup-ai/fix-42"], bare) == pushes_before, "nothing pushed again"
assert len(PR_CREATES) == 1
assert not os.path.exists(os.path.join(pj, "HOOK_RAN")) and not os.path.exists(os.path.join(pj, "PUSH_HOOK_RAN")), "hooks never run"
cmd, body = PR_CREATES[-1]
assert "--base" in cmd and "main" in cmd and "backup-ai/fix-42" in cmd and "--label" not in cmd
assert any(c[:3] == ["gh", "pr", "edit"] and "--add-label" in c and "backup-ai" in c for c in calls), "label added separately"
assert "Do not merge without review" in body and "qwen/qwen3-coder-480b-a35b-instruct" in body and "Files tab" in body
assert "backup-ai-workflow: plan19.yml" in body and "All tests passed" in body and "passed, exit 0" in body
assert "freshness.py | 2" in body, "git show --stat of the real commit"
assert "[plan19.yml]" in cmd[cmd.index("--title") + 1] and cmd[cmd.index("--title") + 1].startswith("Backup AI fix proposal: ")
assert "backup-ai/fix-42" in git(["ls-remote", "--heads", bare], repo)
assert git(["diff", "--name-only", meta["base_sha"], "origin/backup-ai/fix-42"], pj).split() == ["freshness.py"]
assert git(["log", "-1", "--format=%an %ae", "origin/backup-ai/fix-42"], pj).strip() == "tradebot-runner tradebot-runner@users.noreply.github.com"
assert "Co-Authored-By: Claude" not in git(["log", "-1", "--format=%B", "origin/backup-ai/fix-42"], pj)
git(["fetch", "-q", "origin"], repo)
assert "1 / 0" in git(["show", "origin/main:freshness.py"], repo), "main is never changed"
assert not any(c[:3] == ["gh", "pr", "merge"] for c in calls)
n = len(PR_CREATES)
OPEN_PR_HEADS.append("backup-ai/fix-42")
assert B.publish(prop, res_dir, *H, root=checkout("publish_open", meta["base_sha"])) == 0 and len(PR_CREATES) == n, \
    "already open: nothing new"
del OPEN_PR_HEADS[:]
os.environ["GITHUB_RUN_ID"] = "556"
assert B.publish(prop, res_dir, *H, root=checkout("publish2", meta["base_sha"])) == 1 and len(PR_CREATES) == n, \
    "branch exists from another workflow run"
os.environ["GITHUB_RUN_ID"] = "555"
other_prop = os.path.join(OUT, "other_prop"); shutil.copytree(prop, other_prop)
od = GOOD.split("```diff\n")[1].split("```")[0].replace("+    return 1\n", "+    return 2\n")
open(os.path.join(other_prop, "fix.diff"), "w", newline="\n").write(od)
om = dict(meta, diff_sha256=B._sha256(od)); json.dump(om, open(os.path.join(other_prop, "meta.json"), "w"))
assert B.publish(other_prop, res_dir, *hashes(other_prop), root=checkout("publish5", meta["base_sha"])) == 1 \
    and len(PR_CREATES) == n, "same run, another diff: refused"
os.environ.pop("GITHUB_RUN_ID", None)
assert B.publish(prop, res_dir, *H, root=checkout("publish6", meta["base_sha"])) == 1 and len(PR_CREATES) == n, \
    "no run id: refused"
assert B.publish(bad_prop, res_dir, *H, root=checkout("publish3", meta["base_sha"])) == 1 and len(PR_CREATES) == n
assert B.publish(evil_meta, res_dir, *H, root=checkout("publish7", meta["base_sha"])) == 1 and len(PR_CREATES) == n
prop77 = os.path.join(OUT, "prop77"); shutil.copytree(prop, prop77)
m77 = dict(meta, run_id=77, branch="backup-ai/fix-77"); json.dump(m77, open(os.path.join(prop77, "meta.json"), "w"))
p4 = checkout("publish4"); git(ID + ["commit", "-q", "--allow-empty", "-m", "moved on"], p4)
assert B.publish(prop77, res_dir, *hashes(prop77), root=p4) == 1 and len(PR_CREATES) == n, "only on the base commit"
assert "fix-77" not in git(["ls-remote", "--heads", bare], repo)
# 1(e): the cause in the title and body comes from operate's hash-checked meta.json, redacted
prop88 = os.path.join(OUT, "prop88"); shutil.copytree(prop, prop88)
m88 = dict(meta, run_id=88, branch="backup-ai/fix-88", cause="token ghp_abcdefghijklmnopqrstuvwxyz0123 leaked ```")
json.dump(m88, open(os.path.join(prop88, "meta.json"), "w"))
os.environ["GITHUB_RUN_ID"] = "600"
assert B.publish(prop88, res_dir, *hashes(prop88), root=checkout("publish8", meta["base_sha"])) == 0
os.environ.pop("GITHUB_RUN_ID", None)
cmd88, body88 = PR_CREATES[-1]
assert "ghp_" not in body88 and "ghp_" not in cmd88[cmd88.index("--title") + 1] and "[REDACTED]" in body88
assert "leaked '''" in body88, "fences neutralised"
# at most one open pull request per workflow
assert B.fix_candidates(dict(workflows=[dict(file="plan19.yml", state="failed", latest_completed=dict(id=99, event="schedule"))]), [],
                        {"plan19.yml"}) == []
PRS[:] = [dict(number=1, title="Backup AI fix proposal: [live20.yml] x", body="", headRefName="backup-ai/fix-1")]
assert B.open_fix_workflows() == {"live20.yml"}
assert B.fix(fst, B.AI(key="")) == "skipped: NVIDIA_API_KEY is missing"

# ---- (c) pushes to main: ops/status/ only, exactly one runner commit, no hooks, re-checked after each rebase
src = os.path.join(OUT, "status_src"); os.makedirs(src)
open(os.path.join(src, "status.json"), "w").write('{"a": 1}\n')
open(os.path.join(src, "evil.py"), "w").write("x\n")             # never copied
sp = checkout("status_job")
open(os.path.join(sp, ".git", "hooks", "pre-commit"), "w").write("#!/bin/sh\ntouch HOOK_RAN\n")
os.chmod(os.path.join(sp, ".git", "hooks", "pre-commit"), 0o755)
other = checkout("other_writer")                                  # main moves on between commit and push
open(os.path.join(other, "data.txt"), "w").write("x\n")
git(["add", "-A"], other); git(ID + ["commit", "-q", "-m", "data"], other)
pushes = []


def racing_run(cmd, cwd=None, env=None, timeout=300, input_text=None):
    if "push" in cmd and "HEAD:refs/heads/main" in cmd and not pushes:
        pushes.append(1); git(["push", "-q", "origin", "main"], other)     # someone else pushed first
    return real_run(cmd, cwd=cwd, env=env, timeout=timeout, input_text=input_text)


B.run = racing_run
SD = B.status_digest(src)
assert B.push_status(src, None, cwd=sp) == 1 and B.push_status(src, "0" * 64, cwd=sp) == 1, "1(b): digest required"
assert git(["status", "--porcelain"], sp) == "", "nothing copied when the digest is wrong"
assert B.push_status(src, SD, cwd=sp, sleep=lambda s: None) == 0
assert not os.path.exists(os.path.join(sp, "HOOK_RAN")) and not os.path.exists(os.path.join(sp, "ops", "status", "evil.py"))
top = git(["log", "-1", "--format=%an %ae", "origin/main"], sp).strip()
assert top == "tradebot-runner tradebot-runner@users.noreply.github.com", top
assert git(["diff", "--name-only", "origin/main~1", "origin/main"], sp).split() == ["ops/status/status.json"]
assert "data.txt" in git(["ls-tree", "--name-only", "origin/main"], sp), "rebased onto the other push"
assert B.push_status(src, SD, cwd=sp) == 0, "nothing new"
# an extra local commit, a non-status path, or another author: refused
open(os.path.join(src, "status.json"), "w").write('{"a": 2}\n')
assert B.push_status(src, SD, cwd=sp) == 1, "status files changed after operate's digest"
SD = B.status_digest(src)
open(os.path.join(sp, "freshness.py"), "a").write("# x\n")
assert B.push_status(src, SD, cwd=sp) == 1, "dirty file outside ops/status"
git(["checkout", "-q", "--", "freshness.py"], sp)
git(ID + ["-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "extra local commit"], sp)
assert B.push_status(src, SD, cwd=sp) == 1, "two commits ahead"
assert B.push_guard(sp) == ["expected exactly one new commit, found 2"], B.push_guard(sp)
head_before = git(["rev-parse", "origin/main"], sp)
assert git(["ls-remote", bare, "refs/heads/main"], sp).split()[0] == head_before.strip(), "nothing pushed"
gj = checkout("guard")
open(os.path.join(gj, "x.py"), "w").write("x\n")
git(["add", "-A"], gj)
git(["-c", "user.name=tradebot-runner", "-c", "user.email=tradebot-runner@users.noreply.github.com", "commit", "-q", "-m", "x"], gj)
assert any("outside ops/status" in r for r in B.push_guard(gj))
gk = checkout("guard2")
os.makedirs(os.path.join(gk, "ops", "status"), exist_ok=True)
open(os.path.join(gk, "ops", "status", "s.json"), "w").write("{}\n")
git(["add", "-A"], gk); git(ID + ["commit", "-q", "-m", "s"], gk)
assert any("not the runner" in r for r in B.push_guard(gk)), "another identity"
os.environ.pop("GH_TOKEN", None)
B.run = real_run

print("backup AI operator: all checks passed")
