"""JSON files that survive crashes and Windows file locks.

- save(): writes a temp file then os.replace(), retrying while an antivirus or indexer holds the target (Windows), so
  a reader never sees half a file.
- lines(): reads a JSONL log and skips a half-written last line after a crash.
- append(): appends rows to a JSONL log, one compact JSON object per line.
"""
import os, json, time


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj, attempts=5, sleep=time.sleep):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    for k in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == attempts - 1:
                raise
            sleep(1 + k)


def lines(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln in f.read().splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass   # a half-written last line after a crash
    return out


def append(path, rows):
    if not rows:
        return
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
