"""Code manifest: proves that two copies of the tradebot code are the same (added 2026-11-05, refactor stage 3).

Why: the code lives in three places, kept the same by hand: this PC's folder, the public GitHub repository, and the
working copy that changes are made in. Deploys were checked with ad-hoc checksums, and on 2026-10-30 a stale copy of
one test was deployed without anyone noticing until the test ran. One command now lists every code file with its
SHA-256, and another compares a folder against such a list.

  python manifest.py write OUT.json      list this folder's code files and their SHA-256 in OUT.json
  python manifest.py check MANIFEST.json  compare this folder with MANIFEST.json; exit 1 when anything differs

What counts as code: every file under this folder except data and generated files. Left out:
- databases and their journals;
- logs, backups, research data and results, except the frozen inputs in INCLUDE (research/results/rain_model.json,
  which the airport-forecast forward test reads);
- the cloud trial copy (trial/);
- caches, the dashboard pages, marks.jsonl and a KILL switch file in this folder;
- a manifest written into this folder, and Windows' desktop.ini, Thumbs.db and editor backups (*.bak, *~);
- anything whose name starts with a dot (.git, .github, .gitignore).

In the repository, `check` also compares .github/workflows with cloud/workflows and .gitignore with cloud/repo.gitignore:
GitHub runs the former, and the latter are the copies kept with the code.

Read-only: it never changes a file. Bytes are hashed as they are, so a line-ending change shows as a difference.
Python 3.8+, standard library only (it must work when anything else in the folder is broken)."""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"__pycache__", "backups", "logs", "trial", os.path.join("research", "data"), os.path.join("research", "results")}
SKIP_FILES = {"marks.jsonl", "dashboard.html", "dashboard_live.html", "paper_latest.json", "desktop.ini", "thumbs.db"}
SKIP_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm", ".pyc", ".tmp", ".incomplete", ".bak", "~")
INCLUDE = ("research/results/rain_model.json",)   # frozen inputs kept with the code (the airport forecast's calibration)


def _skip_file(rel, f):
    """True for a file that is not code (rel: its folder, relative to the root)."""
    low = f.lower()
    if f.startswith(".") or low in SKIP_FILES or low.endswith(SKIP_SUFFIXES):
        return True
    if rel == "" and (low == "kill" or low.startswith("kill.")):   # core.kill_file's rule, in this folder only
        return True
    if rel == "" and low.startswith("manifest") and low.endswith(".json"):   # a manifest written here
        return True
    return False


def code_files(root=HERE):
    """Relative POSIX paths of the code files under root, sorted."""
    out = []
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        rel = "" if rel == "." else rel
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and os.path.join(rel, x) not in SKIP_DIRS
                         and x not in SKIP_DIRS)
        for f in files:
            if not _skip_file(rel, f):
                out.append(os.path.join(rel, f).replace(os.sep, "/"))
    out += [p for p in INCLUDE if os.path.isfile(os.path.join(root, *p.split("/")))]
    return sorted(set(out))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(root=HERE):
    return {p: sha256(os.path.join(root, *p.split("/"))) for p in code_files(root)}


def write(out, root=HERE):
    files = build(root)
    doc = dict(tool="manifest.py", created=time.strftime("%Y-%m-%dT%H:%M:%S%z"), files=files)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    os.replace(tmp, out)
    return len(files)


def compare(expected, actual):
    """(changed, missing, extra) between two {path: sha256} maps; missing = in expected only."""
    changed = sorted(p for p in expected if p in actual and expected[p] != actual[p])
    missing = sorted(p for p in expected if p not in actual)
    extra = sorted(p for p in actual if p not in expected)
    return changed, missing, extra


def repo_copies(root=HERE):
    """[(path GitHub uses, its copy kept with the code)] that differ, in a repository checkout; [] elsewhere."""
    pairs = []
    wf, cw = os.path.join(root, ".github", "workflows"), os.path.join(root, "cloud", "workflows")
    if os.path.isdir(wf):   # both directions: a workflow on either side only is a difference too
        names = {f for d in (wf, cw) if os.path.isdir(d) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))}
        pairs += [(os.path.join(".github", "workflows", f), os.path.join("cloud", "workflows", f)) for f in sorted(names)]
    if os.path.isfile(os.path.join(root, ".gitignore")):
        pairs.append((".gitignore", os.path.join("cloud", "repo.gitignore")))
    bad = []
    for a, b in pairs:
        pa, pb = os.path.join(root, a), os.path.join(root, b)
        if not (os.path.isfile(pa) and os.path.isfile(pb)) or sha256(pa) != sha256(pb):
            bad.append((a.replace(os.sep, "/"), b.replace(os.sep, "/")))
    return bad


def check(manifest, root=HERE):
    with open(manifest, encoding="utf-8") as f:
        expected = json.load(f)["files"]
    changed, missing, extra = compare(expected, build(root))
    for label, items in (("changed", changed), ("missing here", missing), ("only here", extra)):
        for p in items:
            print("%-13s %s" % (label, p))
    copies = repo_copies(root)
    for a, b in copies:
        print("not the same  %s and %s" % (a, b))
    same = len(expected) - len(changed) - len(missing)
    print("MANIFEST: %d files the same, %d changed, %d missing here, %d only here%s" % (
        same, len(changed), len(missing), len(extra), (", %d repository copies differ" % len(copies)) if copies else ""))
    return 1 if (changed or missing or extra or copies) else 0


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) == 2 and a[0] == "write":
        print("MANIFEST: %d code files listed in %s" % (write(a[1]), a[1]))
        return 0
    if len(a) == 2 and a[0] == "check":
        return check(a[1])
    print(__doc__.split("\n\n")[2])
    return 2


if __name__ == "__main__":
    sys.exit(main())
