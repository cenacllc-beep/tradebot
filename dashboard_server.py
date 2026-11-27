"""Live dashboard on this PC: `.\\run dashboard live` (added 2026-11-27 at the user's request: show the real Kalshi
account, including trades made by hand, in near real time).

Serves the dashboard only on 127.0.0.1 (this PC), on a random port, under a random one-time path (the same hardening as
settings.py: Host and Origin checks, a threaded server, an exclusive port, no request logging). Every 2 minutes it runs
`live.py snapshot` (Kalshi GETs only; live.db opened read-only; Claude may run it, CLAUDE.md section 3a) and rebuilds
the page with dashboard.py's own read_db and build_page. The page checks for a new version every 20 seconds and reloads
only when a rebuild succeeded; a failed rebuild keeps the last good page. It stops after 12 hours, or when its window is
closed (or Ctrl+C).

It never runs any other live.py command, never pipes input into live.py (its standard input is empty), never places or
changes an order, and writes nothing but what `live.py snapshot` itself writes (logs/account.json and its history).
Standard library only."""
import html, http.server, json, os, secrets, socket, subprocess, sys, threading, time, webbrowser
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
INTERVAL = 120            # seconds between Kalshi reads and rebuilds
LIFETIME = 12 * 3600      # stops by itself after 12 hours
SNAPSHOT_ARGS = ("live.py", "snapshot")   # the only live.py command this file ever runs
TZ = timezone(timedelta(hours=-4))        # tbcommon.clock: La Paz, UTC-4


def kill_note():
    """The kill switch's state for the bar (core.kill_file; read only). The snapshot still runs while it is on: it places
    nothing. If the check fails, the bar says so."""
    try:
        from core import kill_file
        f = kill_file()
    except Exception:   # noqa: BLE001
        return " Kill switch: could not be checked."
    return " Kill switch ON (%s): no orders go out." % os.path.basename(f) if f else ""


def same(a, b):
    """Constant-time path comparison as bytes, so a non-ASCII request path cannot raise."""
    return secrets.compare_digest(a.encode("latin-1", "replace"), b.encode("latin-1", "replace"))


def clock(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%I:%M %p").lstrip("0")


def run_snapshot(run=subprocess.run):
    """`live.py snapshot` as a separate process, standard input empty, at most 90 seconds. Returns (ok, short text)."""
    try:
        r = run([sys.executable] + list(SNAPSHOT_ARGS), cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=90)
    except Exception as ex:   # noqa: BLE001 - a failed read never stops the page
        return False, "Kalshi read could not run (%s)" % type(ex).__name__
    last = ((r.stdout or "").strip().splitlines() or [""])[-1]
    return (r.returncode == 0 and "failed" not in last and "no snapshot" not in last), last[:200]


def build_page():
    """The page from dashboard.py's own functions (paper.db and live.db read-only), with no file written."""
    import dashboard
    return dashboard.build_page(dashboard.read_db(), False)


class State:
    """The last good page and its version; a rebuild that fails leaves both as they were."""

    def __init__(self):
        self.lock = threading.Lock()
        self.page, self.version, self.built, self.msg = None, 0, None, "Starting"

    def refresh(self, runner, builder, now=time.time):
        ok, text = runner()
        try:
            page = builder()
            if not isinstance(page, str) or "</body>" not in page:
                raise ValueError("no page")
        except (Exception, SystemExit) as ex:   # read_db exits when paper.db cannot be opened
            with self.lock:
                self.msg = "Rebuild failed at %s (%s); showing the page from %s" % (
                    clock(now()), type(ex).__name__, clock(self.built) if self.built else "never") + "." + kill_note()
            return False
        with self.lock:
            self.page, self.version, self.built = page, self.version + 1, now()
            self.msg = "Kalshi read at %s%s.%s" % (clock(self.built), "" if ok else " failed: %s" % (text or "no reason given"), kill_note())
        return True


def live_bits(tok, version, msg):
    """The banner and the reload script added to the served page (text only; the message goes in as escaped text)."""
    bar = ('<div id=livebar role=status style="position:sticky;top:0;z-index:30;padding:6px 16px;font:13px/1.4 system-ui,sans-serif;'
           'background:#1f5fbf;color:#fff">Live: Kalshi&#8217;s account figures are read every 2 minutes while this window is open; open paper-trade prices are as of when it started. '
           '<span id=livemsg>%s</span></div>' % html.escape(msg))
    js = ('<script>(function(){var v=%d,u="/%s/v",bad=0,m=document.getElementById("livemsg"),b=document.getElementById("livebar");'
          'setInterval(function(){fetch(u,{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(j){bad=0;'
          'if(j.v!==v){location.reload();return}m.textContent=j.msg}).catch(function(){if(++bad>=2){b.style.background="#b42318";'
          'm.textContent="Not updating: the live dashboard window is closed. Run .\\\\run dashboard live again."}})},20000)})();</script>'
          % (version, tok))
    return bar, js


def page_with_live(st, tok):
    with st.lock:
        page, v, msg = st.page, st.version, st.msg
    if page is None:
        return '<!doctype html><meta charset=utf-8><title>Tradebot</title><p>Building the dashboard; this page reloads itself.</p>' \
               '<script>setTimeout(function(){location.reload()},5000)</script>'
    bar, js = live_bits(tok, v, msg)
    i = page.find("<div class=wrap>")
    page = page[:i] + bar + page[i:] if i >= 0 else page
    j = page.rfind("</body>")
    return page[:j] + js + page[j:]


class Server(http.server.ThreadingHTTPServer):
    """Threads (an idle browser connection cannot block the page or the shutdown) and an exclusive port: on Windows
    SO_EXCLUSIVEADDRUSE, elsewhere no SO_REUSEADDR, so no other process can bind the same 127.0.0.1 port."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        http.server.HTTPServer.server_bind(self)


CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; "
       "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")


def make_handler(tok, st):
    class H(http.server.BaseHTTPRequestHandler):
        server_version = "tradebot-dashboard"
        timeout = 15

        def log_message(self, *a):   # never log requests
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _ok(self):
            here = "127.0.0.1:%d" % self.server.server_address[1]
            origin = self.headers.get("Origin")
            return (self.headers.get("Host", "") == here and (origin is None or origin == "http://" + here)
                    and self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none"))

        def do_GET(self):
            if not self._ok():
                return self._send(403, "Refused")
            if same(self.path, "/%s/" % tok):
                return self._send(200, page_with_live(st, tok))
            if same(self.path, "/%s/v" % tok):
                with st.lock:
                    body = json.dumps({"v": st.version, "msg": st.msg})
                return self._send(200, body, "application/json; charset=utf-8")
            return self._send(404, "Not found")

        def do_POST(self):
            return self._send(405, "Not allowed")
        do_PUT = do_DELETE = do_PATCH = do_POST
    return H


def main(open_browser=True, runner=run_snapshot, builder=build_page, lifetime=LIFETIME, interval=INTERVAL, stop=None):
    os.chdir(HERE)   # dashboard.py reads its files relative to the tradebot folder
    tok = secrets.token_urlsafe(24)
    st = State()
    stop = stop or threading.Event()
    srv = Server(("127.0.0.1", 0), make_handler(tok, st))
    url = "http://127.0.0.1:%d/%s/" % (srv.server_address[1], tok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Live dashboard: %s" % url)
    print("Kalshi's figures are read every 2 minutes. Close this window (or press Ctrl+C) to stop; it stops by itself after 12 hours.")
    if open_browser:
        webbrowser.open(url)
    end = time.time() + lifetime
    try:
        while not stop.is_set() and time.time() < end:
            st.refresh(runner, builder)
            print("%s  %s" % (clock(time.time()), st.msg))
            nxt = time.time() + max(1.0, min(interval, end - time.time()))
            while not stop.is_set() and time.time() < nxt:   # 1-second slices, so Ctrl+C is handled promptly on Windows
                stop.wait(min(1.0, max(0.05, nxt - time.time())))
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    srv.server_close()
    print("Live dashboard stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
