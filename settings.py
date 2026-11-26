"""Settings page for the PC: `.\\run settings` (added 2026-11-26 at the user's request, CLAUDE.md section 3).

Opens a page in the browser where the user types the NVIDIA API key for the backup AI. The key goes straight to
GitHub's encrypted repository secret NVIDIA_API_KEY through GitHub's own command-line tool (`gh secret set`, key on
standard input, never on a command line), so the GitHub jobs can use it. The key is never written to disk, a log, the
page, the dashboard or this folder, and it is never shown again.

Safety: the page is served only on 127.0.0.1 (this PC), on a random port, under a random one-time path; a form post must
carry that path's token and come from the same page (Origin check); the helper stops after a successful save, after 10
minutes, or when the window is closed with Ctrl+C. It never touches live.py, paper.db, live.db or the Kalshi key.
Standard library only. Needs GitHub's tool installed and signed in once (`gh auth login`); the page says so if not.
"""
import html, http.server, os, secrets, shutil, socket, subprocess, sys, threading, time, webbrowser
from urllib.parse import parse_qs

REPO = "cenacllc-beep/tradebot"
SECRET = "NVIDIA_API_KEY"
LIFETIME = 600          # seconds before the helper stops by itself
MAX_KEY = 512


def gh_path():
    return shutil.which("gh")


def gh_status():
    """(ok, text): is GitHub's tool installed and signed in? Text is safe to show (no tokens)."""
    exe = gh_path()
    if not exe:
        return False, ("GitHub's tool (gh) is not installed. Install it once with: winget install --id GitHub.cli "
                       "then open a NEW terminal, run: gh auth login, and run .\\run settings again")
    try:
        r = subprocess.run([exe, "auth", "status", "--hostname", "github.com"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except Exception as e:  # noqa: BLE001
        return False, "Could not run gh: %s" % type(e).__name__
    if r.returncode != 0:
        return False, "GitHub's tool is installed but not signed in. Run once in a terminal: gh auth login"
    return True, "GitHub's tool is installed and signed in."


def valid_key(k):
    """A pasted key: one line, printable, 20-512 characters. Returns the cleaned key or None."""
    k = (k or "").strip()
    if not (20 <= len(k) <= MAX_KEY) or any(c.isspace() for c in k) or not k.isprintable():
        return None
    return k


def set_secret(key, run=subprocess.run):
    """Send the key to GitHub's encrypted secret. The key travels only on standard input. Returns (ok, message)."""
    exe = gh_path()
    if not exe:
        return False, "GitHub's tool (gh) is not installed."
    try:
        r = run([exe, "secret", "set", SECRET, "--repo", REPO], input=key, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60)
    except Exception as e:  # noqa: BLE001
        return False, "Could not run gh: %s" % type(e).__name__
    if r.returncode == 0:
        return True, "Saved. GitHub now holds the key encrypted as %s; the backup AI uses it from its next run." % SECRET
    err = (r.stderr or r.stdout or "").replace(key, "[key]")
    return False, "GitHub refused: %s" % err.strip()[:300]


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Tradebot settings</title><style>
:root{--bg:#f6f7f9;--fg:#1b1f24;--card:#fff;--line:#d9dde3;--ok:#1a7f37;--bad:#b42318;--btn:#1f5fbf}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e6e8eb;--card:#1a1e24;--line:#30363d;--ok:#3fb950;--bad:#f85149;--btn:#4c8dff}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:640px;margin:32px auto;padding:0 16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px}
h1{font-size:22px;margin:0 0 12px}h2{font-size:17px;margin:0 0 8px}p{margin:8px 0}.ok{color:var(--ok)}.bad{color:var(--bad)}
input{width:100%%;box-sizing:border-box;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
button{margin-top:12px;padding:10px 16px;border:0;border-radius:6px;background:var(--btn);color:#fff;font:inherit;cursor:pointer}
small{opacity:.8}</style></head><body><main><h1>Tradebot settings</h1><div class=card>
<h2>Backup AI: NVIDIA API key</h2><p class="%(cls)s">%(status)s</p>%(msg)s
<form method=post action="/%(tok)s/key" autocomplete=off>
<label for=k>Paste the key (it is sent to GitHub's encrypted secrets, not saved on this PC, and not shown again)</label>
<input id=k name=key type=text autocomplete=off autocapitalize=off spellcheck=false required minlength=20 maxlength=512 style="-webkit-text-security:disc">
<p><small>If the browser offers to save it as a password, choose Never.</small></p>
<button type=submit %(dis)s>Save to GitHub</button></form>
<p><small>This page works only on this PC and stops after a save or after 10 minutes. Close it with Ctrl+C in the window
that opened it. To change the key later, run <code>.\\run settings</code> again.</small></p></div></main></body></html>"""


def page(tok, msg="", ok=None, status=None):
    gok, gtext = status or gh_status()
    m = ""
    if msg:
        m = '<p class="%s"><b>%s</b></p>' % ("ok" if ok else "bad", html.escape(msg))
    return PAGE % dict(cls="ok" if gok else "bad", status=html.escape(gtext), msg=m, tok=tok, dis="" if gok else "disabled")


class Server(http.server.ThreadingHTTPServer):
    """Threads (an idle browser connection cannot block the page or the shutdown) and an exclusive port: on Windows
    SO_EXCLUSIVEADDRUSE, elsewhere no SO_REUSEADDR, so no other process can bind the same 127.0.0.1 port."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        http.server.HTTPServer.server_bind(self)


def make_handler(tok, done, status=None):
    st = {"v": status}

    def gh_state():
        if st["v"] is None:
            st["v"] = gh_status()
        return st["v"]

    class H(http.server.BaseHTTPRequestHandler):
        server_version = "tradebot-settings"
        timeout = 15

        def log_message(self, *a):   # never log requests (a form body could hold the key)
            pass

        def _send(self, code, body):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "same-origin")   # no-referrer would make the form post Origin: null
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if not secrets.compare_digest(self.path, "/%s/" % tok) or not self._host_ok():
                return self._send(404, "Not found")
            self._send(200, page(tok, status=gh_state()))

        def _host_ok(self):
            return self.headers.get("Host", "") == "127.0.0.1:%d" % self.server.server_address[1]

        def do_POST(self):
            here = "127.0.0.1:%d" % self.server.server_address[1]
            origin = self.headers.get("Origin")
            if (not secrets.compare_digest(self.path, "/%s/key" % tok) or not self._host_ok()
                    or (origin is not None and origin != "http://" + here)):   # "null" and other sites refused
                return self._send(403, "Refused")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > 4096:
                return self._send(400, page(tok, "Nothing usable was sent.", False, gh_state()))
            raw = self.rfile.read(n).decode("utf-8", "replace")
            key = valid_key((parse_qs(raw).get("key") or [""])[0])
            raw = None
            if not key:
                return self._send(400, page(tok, "That does not look like a key (one line, 20-512 characters).", False, gh_state()))
            ok, msg = set_secret(key)
            key = None
            self._send(200 if ok else 502, page(tok, msg, ok, gh_state()))
            if ok:
                done.set()
    return H


def main(open_browser=True):
    tok = secrets.token_urlsafe(24)
    done = threading.Event()
    srv = Server(("127.0.0.1", 0), make_handler(tok, done))
    url = "http://127.0.0.1:%d/%s/" % (srv.server_address[1], tok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Tradebot settings: %s" % url)
    print("This window must stay open while you use the page; it stops after a save or after 10 minutes.")
    if open_browser:
        webbrowser.open(url)
    end = time.time() + LIFETIME
    try:
        while not done.is_set() and time.time() < end:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    try:
        time.sleep(1)   # let the last page finish loading
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    print("Settings closed." + (" The key was saved to GitHub." if done.is_set() else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
