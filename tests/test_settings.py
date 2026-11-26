"""settings.py: the PC settings page that sends the NVIDIA key to GitHub's encrypted secret (fake gh, no network)."""
import os, sys, stat, threading, http.server, urllib.request, urllib.error, tempfile
WORK, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, WORK)
import settings as S
if os.name == "nt":   # the fake gh below is a POSIX script; the cloud test run covers this
    print("settings tests skipped on Windows"); sys.exit(0)

# a fake gh that records its arguments and standard input
bindir = tempfile.mkdtemp(dir=OUT)
log = os.path.join(OUT, "gh.log")
fake = os.path.join(bindir, "gh")
with open(fake, "w") as f:
    f.write("#!/usr/bin/env python3\nimport sys\nopen(%r,'a').write(repr(sys.argv[1:])+' STDIN='+repr(sys.stdin.read() if sys.argv[1:2]==['secret'] else '')+'\\n')\n"
            "sys.exit(0)\n" % log)
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

KEY = "nvapi-" + "A1b2C3d4" * 6
assert S.valid_key(KEY) == KEY and S.valid_key("  " + KEY + "\n") == KEY
assert S.valid_key("short") is None and S.valid_key("a b" * 20) is None and S.valid_key("x" * 600) is None

ok, msg = S.set_secret(KEY)
assert ok, msg
rows = open(log).read().splitlines()
last = rows[-1]
assert "['secret', 'set', 'NVIDIA_API_KEY', '--repo', 'cenacllc-beep/tradebot']" in last and ("STDIN=" + repr(KEY)) in last, last
assert KEY not in last.split(" STDIN=")[0], "the key must never be on gh's command line"

# a refusing gh: the key never appears in the message shown
class R: returncode = 1; stdout = ""; stderr = "bad " + KEY
ok, msg = S.set_secret(KEY, run=lambda *a, **k: R())
assert not ok and KEY not in msg and "[key]" in msg

# the server: one-time path, localhost Host, Origin check, no logging, stops after a save
tok = "T0k3n"
done = threading.Event()
srv = S.Server(("127.0.0.1", 0), S.make_handler(tok, done))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]

def req(path, data=None, origin=None, host=None):
    r = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET")
    if origin: r.add_header("Origin", origin)
    if host: r.add_header("Host", host)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()

code, body = req("/wrong/")
assert code == 404
code, body = req("/%s/" % tok)
assert code == 200 and "text-security:disc" in body and "same-origin" not in body and KEY not in body
code, body = req("/%s/key" % tok, b"key=" + KEY.encode(), origin="http://evil.example")
assert code == 403 and not done.is_set()
code, body = req("/%s/key" % tok, b"key=" + KEY.encode(), origin="null")
assert code == 403 and not done.is_set()
code, body = req("/%s/key" % tok, b"key=" + KEY.encode(), host="evil.com:%d" % srv.server_address[1])
assert code == 403 and not done.is_set()
code, body = req("/nottoken/key", b"key=" + KEY.encode())
assert code == 403
code, body = req("/%s/key" % tok, b"key=short")
assert code == 400 and not done.is_set()
n = sum(1 for l in open(log) if l.startswith("['secret'"))
code, body = req("/%s/key" % tok, b"key=" + KEY.encode(), origin=base)
assert code == 200 and "Saved" in body and KEY not in body and done.is_set()
assert sum(1 for l in open(log) if l.startswith("['secret'")) == n + 1   # exactly one save
srv.shutdown()

# no key file anywhere in the work tree, and the module never touches the trading files
src = open(os.path.join(WORK, "settings.py")).read()
for bad in ("live.py", "paper.db", "live.db", "/portfolio", "import live", ".kalshi"):
    assert bad not in src.replace("It never touches live.py, paper.db, live.db or the Kalshi key", ""), bad
assert "log_message" in src and "127.0.0.1" in src and " open(" not in src.replace("webbrowser.open(", "") and "write(" not in src.replace("self.wfile.write(", "")
print("settings tests passed")
