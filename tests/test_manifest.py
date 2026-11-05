"""manifest.py: one list of the code files and their SHA-256, and a check of a folder against it.
Checks: data, logs, backups, research data and results, the trial copy, databases, dashboards, KILL files and dot
entries are never listed; a check finds changed, missing and extra files (a line-ending change counts); it never changes
a file; the real project lists its code. python test_manifest.py WORK OUT"""
import os, sys, shutil, json, io, contextlib, hashlib
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, WORK)
import manifest as M

T = os.path.join(OUT, "tree")
def put(rel, data=b"x\n"):
    p = os.path.join(T, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(data)
code = ["main.py", "run.bat", "CLAUDE.md", "tbcommon/clock.py", "tests/test_x.py", "research/plan7.py", "research/PLAN7.md",
        "cloud/workflows/a.yml", "cloud/repo.gitignore", "tasks/evening.cmd", "docs/ARCHITECTURE.md", "agents/statistician.md",
        "killswitch.py", "tests/test_kill.py", "research/results/rain_model.json"]
data = ["paper.db", "paper.db-journal", "live.db", "marks.jsonl", "dashboard.html", "dashboard_live.html", "KILL.txt", "Kill",
        "manifest_pc.json", "desktop.ini", "docs/Thumbs.db", "run.bat.bak", "notes.md~", "research/results/temp_model.json",
        "logs/tasks.log", "backups/paper_1.db", "backups/code_pre_r1/main.py", "research/data/lip/hours.json",
        "research/results/learning.md", "trial/paper.db", "__pycache__/main.cpython-313.pyc", "tbcommon/__pycache__/clock.pyc",
        ".git/HEAD", "research/x.json.tmp"]
for r in code: put(r, ("print(%r)\n" % r).encode())
for r in data: put(r)
put(".github/workflows/a.yml", ("print(%r)\n" % "cloud/workflows/a.yml").encode())   # the repository's copies, equal
put(".gitignore", ("print(%r)\n" % "cloud/repo.gitignore").encode())
assert M.code_files(T) == sorted(code), M.code_files(T)
mf = os.path.join(OUT, "m.json"); assert M.write(mf, T) == len(code)
doc = json.load(open(mf)); assert sorted(doc["files"]) == sorted(code) and doc["files"]["main.py"] == hashlib.sha256(b"print('main.py')\n").hexdigest()
def run(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = M.check(mf, root)
    return rc, buf.getvalue()
before = {r: open(os.path.join(T, *r.split("/")), "rb").read() for r in code + data}
rc, out = run(T); assert rc == 0 and out.strip().endswith("%d files the same, 0 changed, 0 missing here, 0 only here" % len(code)), out
put(".github/workflows/a.yml", b"drifted\n")
rc, out = run(T); assert rc == 1 and "not the same  .github/workflows/a.yml and cloud/workflows/a.yml" in out and "1 repository copies differ" in out, out
put(".github/workflows/a.yml", ("print(%r)\n" % "cloud/workflows/a.yml").encode())
os.makedirs(os.path.join(T, ".github", "workflows", "sub"))            # a folder there is skipped, not a crash
assert M.repo_copies(T) == []
put("cloud/workflows/b.yml", b"only in cloud/\n")                         # a workflow GitHub never got
assert M.repo_copies(T) == [(".github/workflows/b.yml", "cloud/workflows/b.yml")], M.repo_copies(T)
os.remove(os.path.join(T, "cloud", "workflows", "b.yml"))
put("main.py", b"print('main.py')\r\n")                     # a line-ending change is a change
os.remove(os.path.join(T, "docs", "ARCHITECTURE.md"))
put("research/plan8.py", b"new\n")
put("backups/ignored.py", b"never listed\n")
rc, out = run(T)
assert rc == 1 and "changed       main.py" in out and "missing here  docs/ARCHITECTURE.md" in out and "only here     research/plan8.py" in out, out
assert "ignored" not in out
for r in data: assert open(os.path.join(T, *r.split("/")), "rb").read() == before[r], "check never changes a file"
print("manifest: data and generated files never listed; changed, missing and extra files found; read-only: ok")

# the real project: its code is listed, nothing it must leave out is
real = M.code_files(WORK)
assert "manifest.py" in real and "strategy.py" in real and "research/plan7.py" in real and "run.bat" in real and "killswitch.py" in real
skip = ("research/data/", "research/results/", "backups/", "logs/", "trial/", ".")
for d, dirs, files in os.walk(WORK):   # every Python file of the project is listed
    for f in files:
        rel = os.path.relpath(os.path.join(d, f), WORK).replace(os.sep, "/")
        if f.endswith(".py") and "__pycache__" not in rel and not rel.startswith(skip):
            assert rel in real, rel
for p in real:
    assert not p.endswith((".db", ".pyc", ".jsonl")) and not p.startswith(("research/data/", "backups/", "logs/", "trial/", ".")), p
    assert not p.startswith("research/results/") or p in M.INCLUDE, p
assert M.main(["nonsense"]) == 2
print("manifest: the real project lists %d code files and no data: ok" % len(real))
