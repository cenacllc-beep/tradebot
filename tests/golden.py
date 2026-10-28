"""Golden-master check for refactors: proves that a code change did not change what the program produces.

  python tests/golden.py capture TREE OUT       run the scenario tests of TREE (a copy of the project), outputs -> OUT
  python tests/golden.py compare BASE BASE2 NEW  compare NEW with BASE, field by field

Typical use (added 2026-10-23, refactor stage 2):
  1. copy the project before the change to OLD; make the change in the project;
  2. capture OLD -> B1, the project -> N, OLD again -> B2 (back to back, so clock-based values differ only by seconds);
  3. compare B1 B2 N.
Every output file (SQLite rows, JSON and JSONL values, Markdown/HTML/text lines, printed output) is flattened into
path -> value. Fields that differ between B1 and B2 (two runs of the same code: timestamps, uuids) are volatile and
skipped. Timestamps, clock times and epoch seconds inside text are masked, and a long line (a page body) is split at
tag and JSON-item boundaries so each piece is compared on its own (review 2026-10-23: before, the whole body was one
line and always volatile). Text files are aligned with difflib, so an intended inserted line shows as one change
instead of shifting every later line. Numbers are equal within 1e-9 relative (0 equals 0.0). Exit code 1
if anything else differs. Uses temporary folders and fake data only (the scenario tests never touch the network or the
real databases). Python 3.8+, standard library only."""
import os, sys, re, json, math, shutil, sqlite3, subprocess

SCENARIOS = ("structure", "lip", "discover", "micro", "combo", "longshot", "engines", "marks", "audit", "end_to_end",
             "fix", "shadow")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?|\d{8}_\d{6}|backed up -> .*"
                 r"|WARNING: only \d of \d backups.*|skipped, already exists: .*")


_NOISE = re.compile(r"(backed up -> |skipped, already exists: |WARNING: only \d of \d backups|backups: \[)")
# Inside a line: clock times on pages ("10:25 PM", "Updated Oct 23, 10:25 AM") and epoch seconds in embedded page data
# ("now":1792771200.5). Masked token by token, so one changing number no longer hides a whole page line.
_CLOCK = re.compile(r"\b\d{1,2}:\d{2} ?[AP]M\b|\b1[6-9]\d{8}(\.\d+)?\b|\b1[6-9]\d{11}\b")
# A page body is one long line: split it at tag and JSON-item boundaries so it compares piece by piece.
_SPLIT = re.compile(r"(?<=>)(?=<)|(?<=,)(?=\")")


def capture(tree, out):
    """Run every scenario; returns the number that failed (the exit code), so a broken run is never compared silently."""
    shutil.rmtree(out, ignore_errors=True)
    if os.path.exists(out) and os.listdir(out):   # Windows can hold a lock on a file for a moment
        print("warning: %s could not be fully emptied; old files may remain" % out)
    os.makedirs(out, exist_ok=True)
    failed = 0
    for t in SCENARIOS:
        d = os.path.join(out, t)
        env = dict(os.environ, PAPER_DB=os.path.join(d, "paper.db"), TRADEBOT_OFFSITE_BACKUPS=os.path.join(d, "offsite"),
                   PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")
        with open(os.path.join(out, t + ".stdout"), "w", encoding="utf-8") as f:
            rc = subprocess.run([sys.executable, os.path.join(tree, "tests", "test_%s.py" % t), tree, d],
                                stdout=f, stderr=subprocess.STDOUT, env=env).returncode
        print("%-12s %s" % (t, "ok" if rc == 0 else "FAILED (exit %d)" % rc))
        failed += rc != 0
    return failed


def _walk(out, key, v):
    if isinstance(v, dict):
        for a, b in v.items():
            _walk(out, key + (a,), b)
    elif isinstance(v, list):
        for i, b in enumerate(v):
            _walk(out, key + (i,), b)
    else:
        out[key] = v


def flatten(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root)
            if "offsite" in rel or "backups" in rel or "__pycache__" in rel or rel.endswith((".tmp", ".png")):
                continue
            try:
                if f.endswith(".db"):
                    c = sqlite3.connect(p)
                    for (t,) in c.execute("select name from sqlite_master where type='table' order by name"):
                        try:   # one unreadable table is reported on its own, not as the whole file
                            cols = [r[1] for r in c.execute("pragma table_info(%s)" % t)]
                            for i, row in enumerate(c.execute("select * from %s order by rowid" % t)):
                                for k, v in zip(cols, row):
                                    out[(rel, t, i, k)] = v
                        except sqlite3.Error as ex:
                            out[(rel, t, "ERROR")] = str(ex)
                    c.close()
                elif f.endswith(".json"):
                    with open(p, encoding="utf-8") as fh:
                        _walk(out, (rel,), json.load(fh))
                elif f.endswith(".jsonl"):
                    with open(p, encoding="utf-8") as fh:
                        for i, ln in enumerate(fh):
                            try:
                                _walk(out, (rel, i), json.loads(ln))
                            except ValueError:
                                out[(rel, i)] = ln
                else:   # backup.py's own messages depend on the clock second (name clashes): left out before indexing
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        kept = [ln.rstrip("\n") for ln in fh if not _NOISE.match(ln)]
                    for i, ln in enumerate(kept):
                        parts = _SPLIT.split(ln) if len(ln) > 2000 else [ln]
                        if len(parts) == 1:
                            out[(rel, i)] = ln
                        else:
                            for j, part in enumerate(parts):
                                out[(rel, i, j)] = part
            except Exception as ex:
                out[(rel, "ERROR")] = str(ex)
    return out


def _mask(s):
    return _CLOCK.sub("<C>", _TS.sub("<T>", s))


def same(a, b):
    if isinstance(a, str):
        a = _mask(a)
    if isinstance(b, str):
        b = _mask(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or (math.isfinite(a) and math.isfinite(b) and abs(a - b) <= 1e-9 * max(1, abs(a), abs(b)))
    return a == b


DATA_FILES = (".db", ".json", ".jsonl")


def _texts(flat):
    """Text files as {file: [masked piece, ...]} in reading order."""
    by = {}
    for k, v in flat.items():
        if not k[0].endswith(DATA_FILES):
            by.setdefault(k[0], []).append((k[1:], v))
    order = lambda key: tuple((0, x, "") if isinstance(x, int) else (1, 0, str(x)) for x in key)
    return {f: [_mask(v) if isinstance(v, str) else repr(v) for _, v in sorted(kv, key=lambda x: order(x[0]))] for f, kv in by.items()}


def _text_changes(b1, b2, nw):
    """Changed stretches of text, aligned with difflib so one inserted line does not shift every later line. A stretch
    that replaces only pieces which already differ between the two old runs (same count) is run-to-run noise."""
    import difflib
    out = []
    for f in sorted(set(b1) | set(nw)):
        a, b, c = b1.get(f, []), b2.get(f, []), nw.get(f, [])
        noisy = set()
        for op, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op != "equal":
                noisy.update(range(i1, i2))
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, c, autojunk=False).get_opcodes():
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1 and all(i in noisy for i in range(i1, i2))):
                continue
            out.append((f, op, a[i1:i2], c[j1:j2]))
    return out


def compare(base, base2, new):
    """Data files (SQLite, JSON, JSONL) field by field; text files (pages, reports, printed output) as aligned
    sequences. Prints what differs; returns 1 when anything does."""
    b1, b2, nw = flatten(base), flatten(base2), flatten(new)
    data = lambda k: k[0].endswith(DATA_FILES)
    volatile = {k for k in set(b1) | set(b2) if data(k) and not same(b1.get(k), b2.get(k))}
    bad = [(k, b1.get(k), nw.get(k)) for k in set(b1) | set(nw) if data(k) and k not in volatile and not same(b1.get(k), nw.get(k))]
    tb1, tnw = _texts(b1), _texts(nw)
    changes = _text_changes(tb1, _texts(b2), tnw)
    print("data fields compared: %d (volatile skipped: %d), differences: %d" % (
        len([k for k in b1 if data(k)]) - len(volatile), len(volatile), len(bad)))
    print("text pieces compared: %d in %d files, changed stretches: %d" % (sum(map(len, tb1.values())), len(tb1), len(changes)))
    errors = sorted((k for k in set(b1) | set(nw) if "ERROR" in k), key=str)
    if errors:   # an unreadable file or table compares equal when both runs fail the same way: say so
        print("unreadable in a run (compared only as error text): %s" % ", ".join(ascii(k) for k in errors[:10]))
    for k, x, y in sorted(bad, key=str)[:40]:   # ascii(): a Windows console cannot print every page character
        print("  %s\n    before: %s\n    after:  %s" % (ascii(k), ascii(str(x)[:160]), ascii(str(y)[:160])))
    for f, op, x, y in changes[:40]:
        print("  %s (%s)\n    before: %s\n    after:  %s" % (ascii(f), op, ascii(" / ".join(x)[:300]), ascii(" / ".join(y)[:300])))
    return 1 if (bad or changes) else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["capture"] and len(a) == 3:
        sys.exit(1 if capture(os.path.abspath(a[1]), os.path.abspath(a[2])) else 0)
    elif a[:1] == ["compare"] and len(a) == 4:
        sys.exit(compare(*a[1:]))
    else:
        sys.exit(__doc__)
