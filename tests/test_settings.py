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

# the opt-in box (2026-11-27): unticked by default; ticked, the key is also kept on this PC with DPAPI (fake here),
# outside the folder; "Remove the key from this PC" deletes it; the key is never on the page
sys.path.insert(0, os.path.join(WORK, "ops"))
import pc_key as K
class FakeDPAPI(object):
    def protect(self, b): return b"FAKEDPAPI" + bytes(x ^ 0x5A for x in b)
    def unprotect(self, b): return bytes(x ^ 0x5A for x in b[9:])
KP = os.path.join(OUT, "home", ".tradebot", "nvidia.key")
class Store(object):   # pc_key with a fake DPAPI and a key file under OUT
    def supported(self): return True
    def exists(self): return K.exists(KP)
    def store(self, k): return K.store(k, dpapi=FakeDPAPI(), path=KP)
    def remove(self): return K.remove(KP)
assert not K.supported() and S.PCKEY is not None   # off Windows the real store is not offered
body = S.page("t", status=(True, "ok"))
assert 'type=checkbox name=keep value=1 style="width:auto" disabled' in body and "checked" not in body
assert "Remove the key from this PC" in body and "No key is kept on this PC. (Keeping one here needs Windows.)" in body
done2 = threading.Event()
srv = S.Server(("127.0.0.1", 0), S.make_handler(tok, done2, keystore=Store()))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
code, body = req("/%s/" % tok)
import html as _html
assert code == 200 and _html.escape(S.KEEP_LABEL) in body and "checked" not in body
assert "saved on this PC only if you tick the box" in body and "not saved on this PC" not in body   # the label follows the box
assert "never sends money figures, Kalshi account lines" in S.KEEP_LABEL and "status" in S.KEEP_LABEL
assert 'name=keep value=1 style="width:auto" >' in body and "No key is kept on this PC." in body
n = sum(1 for l in open(log) if l.startswith("['secret'"))
code, body = req("/%s/key" % tok, b"key=" + KEY.encode())   # box unticked: GitHub only, nothing kept here
assert code == 200 and not os.path.exists(KP) and sum(1 for l in open(log) if l.startswith("['secret'")) == n + 1
done2.clear()
code, body = req("/%s/key" % tok, b"key=" + KEY.encode() + b"&keep=1", origin=base)
assert code == 200 and "Saved" in body and "Kept on this PC" in body and KEY not in body and done2.is_set(), body
assert os.path.exists(KP) and KEY.encode() not in open(KP, "rb").read() and K.load(dpapi=FakeDPAPI(), path=KP) == KEY
assert "A key is kept on this PC" in body
code, body = req("/%s/remove" % tok, b"remove=1", origin="http://evil.example")
assert code == 403 and os.path.exists(KP)
code, body = req("/%s/remove" % tok, b"remove=1", origin=base)
assert code == 200 and "Removed the key from this PC" in body and not os.path.exists(KP) and "No key is kept on this PC." in body
srv.shutdown()

# no key file anywhere in the work tree, and the module never touches the trading files
src = open(os.path.join(WORK, "settings.py")).read()
for bad in ("live.py", "paper.db", "live.db", "/portfolio", "import live", ".kalshi"):
    assert bad not in src.replace("It never touches live.py, paper.db, live.db or the Kalshi key", ""), bad
assert "log_message" in src and "127.0.0.1" in src and " open(" not in src.replace("webbrowser.open(", "") and "write(" not in src.replace("self.wfile.write(", "")
print("settings tests passed")
