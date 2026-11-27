"""The real-money panel's headline is Kalshi's own account total, the account history is appended safely, the chart reads
it, and `.\\run dashboard live` (dashboard_server.py) serves only on 127.0.0.1 with its Host/Origin/token checks and runs
only `live.py snapshot`. Fake data only: no network, never the real live.py commands. python test_account_live.py WORK OUT"""
import os, sys, json, time, threading, subprocess, urllib.request, urllib.error
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["LIVE_DB"] = os.path.join(OUT, "live.db")
os.environ["TRADEBOT_ACCOUNT_JSON"] = os.path.join(OUT, "logs", "account.json")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "offsite")
sys.path.insert(0, WORK)
import live, real_view as RV
from datetime import date

T0 = 1795000000.0
tab = lambda h, rows, empty, num=(): "<table>%s</table>" % "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % x for x in r) for r in rows) if rows else empty
stop = date(2026, 11, 11)
orders = [dict(id=1, ts=T0, env="prod", paper_id=1, ticker="KXRAIN-26NOV20-STL", side="yes", count=2, limit_cents=30, status="executed",
               fill_count=2, cost=0.6, fees=0.03, result="yes", pnl=1.37, settled_ts=T0 + 40000, note="")]
events = [dict(id=1, ts=T0 - 100, env="prod", kind="unlock", detail="")]
bot_value = RV.value_track(orders, events)[0]
assert abs(bot_value - 26.37) < 1e-9
acct = dict(env="prod", ts=T0 + 50000, ok=True, error=None, cash=8.60, portfolio_value=0.87, positions=[], fills=[], settlements=[], days=14)
NOW = T0 + 50060

# ---------- 1. the headline is Kalshi's total; the bot's value is a labelled second figure ----------
h = RV.section(orders, events, [], NOW, False, stop, tab, acct, [])
top = h.split("<dl class=rtiles>")[0]
assert "$9.47" in top and top.index("$9.47") < top.index("$26.37"), "Kalshi's total comes first"
assert "The bot&#8217;s own value: $26.37" in top and "cash $8.60 + positions $0.87" in top and "read " in top
assert "differ by $16.90" in top and "outside the bot" in top
assert "over two hours old" not in top and "last read failed" not in top
assert "every 2 minutes while <code>.\\run dashboard live</code> is open" in h and "after each scan and settle" in h
assert "account chart starts once two readings" in top   # one reading only: the bot's chart below, with a note
assert "The bot&#8217;s own value over time" in top and top.count("id=rv-v") == 1
# stale and failed snapshots
st_ = RV.section(orders, events, [], acct["ts"] + 3 * 3600, False, stop, tab, acct, [])
assert "This reading is over two hours old" in st_.split("<dl class=rtiles>")[0]
bad = dict(acct, ok=False, error="ConnectionError: x", error_ts=acct["ts"] + 600)
assert "The last read failed (ConnectionError: x)" in RV.section(orders, events, [], NOW, False, stop, tab, bad, []).split("<dl class=rtiles>")[0]
# missing and demo: today's display (the bot's value) with a note
for a, why in ((None, "no usable account snapshot"), (dict(acct, env="demo"), "demo exchange")):
    m = RV.section(orders, events, [], NOW, False, stop, tab, a, [])
    t_ = m.split("<dl class=rtiles>")[0]
    assert "Kalshi&#8217;s own account total is not shown here" in t_ and why in t_, t_[:400]
    assert "<p class=acct-v id=rv-v>$26.37</p>" in t_ and "$9.47" not in t_
assert "No real orders yet" in RV.section([], [], [], NOW, False, stop, tab, None, [])
assert RV.kalshi_now({k_: v_ for k_, v_ in acct.items() if k_ != "env"}) is None   # a missing env is not the real exchange
assert RV.account_points([dict(ts=T0, cash=1.0, portfolio_value=0, ok=True)], None, NOW) == []
assert "portfolio value is taken to exclude cash" in RV.section(orders, events, [], NOW, False, stop, tab, acct, [])
assert RV.static_svg.__doc__ and RV.static_svg.__doc__.startswith("The chart without JavaScript")
assert RV.kalshi_now(dict(acct, cash=float("nan"))) is None and RV.kalshi_now(dict(acct, ts="x")) is None
assert abs(RV.kalshi_now(dict(acct, portfolio_value=None))["total"] - 8.60) < 1e-9
print("headline ok")

# ---------- 2. history: appended by live.py's snapshot path, crash-safe and de-duplicated ----------
H = os.path.join(OUT, "logs", "account_history.jsonl")
live._append_history(dict(ts=1.0, env="prod", cash=9.0, portfolio_value=1.0, ok=True), H)
live._append_history(dict(ts=1.0, env="prod", cash=9.0, portfolio_value=1.0, ok=True), H)   # same ts: skipped
live._append_history(dict(ts=2.0, env="prod", cash=8.5, portfolio_value=1.0, ok=True), H)
assert len(open(H).read().splitlines()) == 2
with open(H, "a") as f: f.write('{"ts":3.0,"env":"pr')                     # a line cut short by a crash
live._append_history(dict(ts=4.0, env="prod", cash=8.0, portfolio_value=1.0, ok=True), H)
L = open(H).read().splitlines()
assert L[-1] == '{"ts":4.0,"env":"prod","cash":8.0,"portfolio_value":1.0,"ok":true}' and L[-2].startswith('{"ts":3.0'), L
live._append_history(dict(ts=5.0), os.path.join(OUT, "nofile", "\0bad"))   # an unwritable path: ignored, never raises
live._append_history(dict(ts=6.0, cash=float("nan"), env="prod", ok=True), os.path.join(OUT, "logs", "nan.jsonl"))   # still no exception
# snapshot() appends one line per success and failure, using a fake client (no network)
class FakeCl:
    def get(self, ep, params=None, auth=True):
        if ep == "/portfolio/balance": return {"balance": 860, "portfolio_value": 87}
        return {{"/portfolio/positions": "market_positions", "/portfolio/fills": "fills", "/portfolio/settlements": "settlements"}[ep]: [], "cursor": ""}
live.load_settings = lambda: ({}, "prod", {"key_id": "k"})
live.ready = lambda k: True
live.client = lambda: (FakeCl(), "prod")
live.now = lambda: T0 + 1
H2 = os.path.join(OUT, "logs", "account_history.jsonl")
os.remove(H2)
live.snapshot(); live.snapshot()                       # the same ts twice: one line
live.now = lambda: T0 + 121; live.snapshot()
def boom(): raise live.ExchangeError("down")
live.client = boom; live.now = lambda: T0 + 241; live.snapshot()
rows = [json.loads(l) for l in open(H2).read().splitlines()]
assert [r["ts"] for r in rows] == [T0 + 1, T0 + 121, T0 + 241], rows
assert rows[0] == dict(ts=T0 + 1, env="prod", cash=8.6, portfolio_value=0.87, ok=True) and rows[2]["ok"] is False and rows[2]["cash"] is None
A = json.load(open(os.environ["TRADEBOT_ACCOUNT_JSON"]))
assert A["ok"] is False and abs(A["cash"] - 8.6) < 1e-9   # the failure keeps the last good figures, as before
# account.json writes: one temp file per process, a refused replace is retried, and a failed write never stops the history
J = os.path.join(OUT, "jw", "account.json"); os.makedirs(os.path.dirname(J), exist_ok=True)
real_replace = os.replace; fails = [2]
def flaky(a, b):
    if fails[0] > 0: fails[0] -= 1; raise PermissionError("in use")
    return real_replace(a, b)
os.replace = flaky
try:
    live._write_json(J, {"a": 1})
    assert json.load(open(J)) == {"a": 1} and fails[0] == 0
    fails[0] = 99
    try: live._write_json(J, {"a": 2}); raise AssertionError("should raise")
    except PermissionError: pass
finally: os.replace = real_replace
assert json.load(open(J)) == {"a": 1} and not [f for f in os.listdir(os.path.dirname(J)) if f.endswith(".tmp")]
code = ("import sys; sys.path.insert(0,%r); import live\nfor i in range(200): live._write_json(%r, {'i': i, 'w': sys.argv[1]})" % (WORK, J))
ps = [subprocess.Popen([sys.executable, "-c", code, str(w)], env=dict(os.environ)) for w in range(2)]
assert all(p_.wait(60) == 0 for p_ in ps), "two writers at once"
assert json.load(open(J))["i"] == 199
live.client = lambda: (FakeCl(), "prod"); live.now = lambda: T0 + 361
wj = live._write_json
def nowrite(path, obj): raise PermissionError("locked")
live._write_json = nowrite
try: live.snapshot()
finally: live._write_json = wj
assert json.loads(open(H2).read().splitlines()[-1])["ts"] == T0 + 361, "the history line still went in"
# size cap: the file rolls over to account_history.1.jsonl above HISTORY_MAX
R = os.path.join(OUT, "roll", "account_history.jsonl")
keep = live.HISTORY_MAX; live.HISTORY_MAX = 300
try:
    for i in range(20): live._append_history(dict(ts=float(i), env="prod", cash=1.0, portfolio_value=0.0, ok=True), R)
finally: live.HISTORY_MAX = keep
R1 = os.path.join(OUT, "roll", "account_history.1.jsonl")
assert os.path.exists(R1) and os.path.getsize(R) <= 300 + 80 and os.path.getsize(R1) > 300
import dashboard as D0
got = D0.read_account_history(folder=os.path.dirname(R))
assert [r["ts"] for r in got] == sorted(r["ts"] for r in got) and len(got) >= 10 and got[-1]["ts"] == 19.0, got
cut = D0.read_account_history(most_bytes=200, folder=os.path.dirname(R))   # read from the end; the partial first line dropped
assert cut and cut[-1]["ts"] == 19.0 and len(cut) < len(got) and all(isinstance(r, dict) for r in cut)
assert D0.read_account_history(folder=os.path.join(OUT, "nothing")) == []
print("history ok")

# ---------- 3. the chart plots the history (Kalshi's total), with the bot's markers ----------
hist = [dict(ts=T0 + 30000 + 120 * i, env="prod", cash=10.0 - 0.1 * i, portfolio_value=0.5, ok=True) for i in range(5)]
hist += [dict(ts=T0 + 30700, env="demo", cash=999.0, portfolio_value=0, ok=True), dict(ts=T0 + 30800, env="prod", cash=None, ok=False),
         "junk", dict(ts=NOW + 99999, env="prod", cash=1.0, portfolio_value=0, ok=True)]
c = RV.section(orders, events, [], NOW, False, stop, tab, acct, hist)
data = json.loads(c.split('<script type="application/json" id=rv-data>')[1].split("</script>")[0])
assert data["what"] == "The Kalshi account's total" and data["all"] == "Since the first saved reading"
assert abs(data["start"] - 10.5) < 1e-9 and abs(RV.value_at(data, NOW) - 9.47) < 1e-9, (data["start"], RV.value_at(data, NOW))
assert len(data["steps"]) == 5 and all(s[0] <= NOW + 60 for s in data["steps"])   # demo, failed, junk and future lines skipped
assert len(data["markers"]) == 2 and "Line: Kalshi account total" in c and "account chart starts" not in c
assert "<p class=acct-v id=rv-v>$9.47</p>" in c and "The bot&#8217;s own value: $26.37" in c
assert 'aria-label="The Kalshi account&#x27;s total, since the first saved reading"' in c
# old readings are thinned to one an hour; the last 48 hours are kept whole
many = [dict(ts=NOW - 10 * 86400 + 120 * i, env="prod", cash=5.0, portfolio_value=0, ok=True) for i in range(7000)]
pts = RV.account_points(many, None, NOW)
assert len(pts) < 7000 and all(pts[i][0] < pts[i + 1][0] for i in range(len(pts) - 1))
k48 = sum(1 for r in many if r["ts"] >= NOW - 48 * 3600); assert k48 > 100 and sum(1 for p in pts if p[0] >= NOW - 48 * 3600) == k48
# escaping: a hostile error text and embedded data never break out
evil = dict(acct, ok=False, error='</script><img src=x onerror=alert(1)>')
x = RV.section(orders, events, [], NOW, False, stop, tab, evil, hist)
assert "<img src=x" not in x and "&lt;/script&gt;" in x
emb = x.split('<script type="application/json" id=rv-data>')[1].split("</script>")[0]
assert "<" not in emb
print("chart ok")

# ---------- 4. the dashboard reads the history file and builds with the account headline ----------
import dashboard as D
D.DB = os.environ["PAPER_DB"]
import core; core.DB = D.DB
import sqlite3; sqlite3.connect(D.DB).close()
assert isinstance(D.read_account_history(), list)
D.read_account = lambda: acct
D.read_account_history = lambda: hist
import dashboard_server
page = dashboard_server.build_page()   # dashboard.py's own read_db + build_page, as the live server runs them
real = page.split("id=real aria-labelledby")[1].split("<dl class=rtiles>")[0]
assert "<p class=acct-v id=rv-v>$9.47</p>" in real and "Kalshi account total: cash $8.60" in real and "real-money view failed" not in page
print("dashboard reader ok")

# ---------- 5. the live server: only 127.0.0.1, one-time path, Host/Origin checks, only `live.py snapshot` ----------
import dashboard_server as S
calls = []
def fake_run(args, **kw):
    calls.append((args, kw))
    class R: returncode = 0; stdout = "live (prod): account snapshot: cash $8.60, 0 open positions"; stderr = ""
    return R()
ok, text = S.run_snapshot(run=fake_run)
assert ok and "cash $8.60" in text
args, kw = calls[-1]
assert args[1:] == ["live.py", "snapshot"] and kw.get("stdin") is subprocess.DEVNULL and "input" not in kw, (args, kw)
assert kw.get("cwd") == S.HERE
def failing_run(args, **kw):
    class R: returncode = 0; stdout = "live (prod): account snapshot failed (x); the dashboard keeps the last one"; stderr = ""
    return R()
assert S.run_snapshot(run=failing_run)[0] is False
def raising_run(args, **kw): raise OSError("x")
assert S.run_snapshot(run=raising_run)[0] is False
src = open(os.path.join(WORK, "dashboard_server.py")).read()
for cmd in ("mirror", "unlock", "resume", "\"use\"", "sync", "demo-order", "setup", "lock\""):
    assert ("\"%s\"" % cmd.strip('"')) not in src.replace("SNAPSHOT_ARGS = (\"live.py\", \"snapshot\")", ""), cmd
assert "import live" not in src and "input=" not in src and "127.0.0.1" in src and "log_message" in src

st = S.State()
n = [0]
def runner(): n[0] += 1; return True, "fine"
pages = ["<html><body><div class=wrap>PAGE ONE</div></body></html>"]
def builder():
    if pages[0] is None: raise RuntimeError("broken")
    return pages[0]
assert st.refresh(runner, builder) and st.version == 1
pages[0] = None
assert not st.refresh(runner, builder) and st.version == 1 and "PAGE ONE" in st.page and "Rebuild failed" in st.msg
def exiting(): raise SystemExit("Cannot open paper.db")
assert not st.refresh(runner, exiting) and st.version == 1   # read_db's sys.exit never kills the server
pages[0] = "<html><body><div class=wrap>PAGE TWO</div></body></html>"
assert st.refresh(runner, builder) and st.version == 2 and n[0] == 4
st.msg = '<b>x</b>'
tok = "T0k3n-abc"
srv = S.Server(("127.0.0.1", 0), S.make_handler(tok, st))
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
assert srv.server_address[0] == "127.0.0.1"
base = "http://127.0.0.1:%d" % port
def req(path, origin=None, host=None, method="GET", site=None):
    r = urllib.request.Request(base + path, method=method, data=b"x" if method == "POST" else None)
    if origin: r.add_header("Origin", origin)
    if host: r.add_header("Host", host)
    if site: r.add_header("Sec-Fetch-Site", site)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as e: return e.code, e.read().decode(), dict(e.headers)
code, body, hd = req("/%s/" % tok)
assert code == 200 and "PAGE TWO" in body and "id=livebar" in body and "&lt;b&gt;x&lt;/b&gt;" in body and '"/%s/v"' % tok in body
assert body.index("id=livebar") < body.index("PAGE TWO") and "location.reload()" in body
assert "no-store" in hd.get("Cache-Control", "") and "frame-ancestors 'none'" in hd.get("Content-Security-Policy", "") and hd.get("X-Frame-Options") == "DENY"
code, body, _ = req("/%s/v" % tok)
assert code == 200 and json.loads(body) == {"v": 2, "msg": "<b>x</b>"}
assert req("/wrong/")[0] == 404 and req("/%s/x" % tok)[0] == 404 and req("/")[0] == 404
assert req("/%s/" % tok, host="evil.example:%d" % port)[0] == 403            # DNS rebinding
assert req("/%s/" % tok, host="localhost:%d" % port)[0] == 403
assert req("/%s/v" % tok, origin="http://evil.example")[0] == 403
assert req("/%s/v" % tok, origin="null")[0] == 403
assert req("/%s/v" % tok, origin=base)[0] == 200
assert req("/%s/" % tok, site="cross-site")[0] == 403
assert req("/%s/" % tok, method="POST")[0] in (403, 405)
srv.shutdown(); srv.server_close()
# main(): rebuilds on its interval, then stops (here after a stop request) and frees the port; no browser
ev = threading.Event(); seen = []
def r2(): seen.append(time.time()); return True, "ok"
def b2():
    if len(seen) >= 2: ev.set()
    return "<html><body><div class=wrap>x</div></body></html>"
here = os.getcwd()
th = threading.Thread(target=S.main, kwargs=dict(open_browser=False, runner=r2, builder=b2, lifetime=30, interval=0.2, stop=ev))
th.start(); th.join(20); os.chdir(here)
assert not th.is_alive() and len(seen) >= 2
# lifetime: it stops by itself
t1 = time.time(); S.main(open_browser=False, runner=r2, builder=b2, lifetime=0.5, interval=0.2); os.chdir(here)
assert time.time() - t1 < 10
assert S.LIFETIME == 12 * 3600 and S.INTERVAL == 120
# a non-ASCII request path is refused, never raises
import socket
srv = S.Server(("127.0.0.1", 0), S.make_handler(tok, st)); threading.Thread(target=srv.serve_forever, daemon=True).start()
sk = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10)
sk.sendall(b"GET /\xc3\xa9" + tok.encode() + b"/ HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % srv.server_address[1])
assert sk.recv(100).startswith(b"HTTP/1.0 404"); sk.close()
assert S.same("/\u00e9/", "/x/") is False and S.same("/a/", "/a/")
srv.shutdown(); srv.server_close()
# the kill switch is shown in the bar, and the Kalshi read still runs
open(os.path.join(OUT, "KILL.txt"), "w").close()
try:
    k_ = S.State(); assert k_.refresh(runner, lambda: "<html><body><div class=wrap>k</div></body></html>")
    assert "Kill switch ON (KILL.txt)" in k_.msg and n[0] == 5
finally: os.remove(os.path.join(OUT, "KILL.txt"))
assert "Kill switch" not in S.kill_note()
assert "paper-trade prices are as of when it started" in S.live_bits("t", 1, "m")[0]
print("live server ok")

# run.bat offers the command, CRLF kept
rb = open(os.path.join(WORK, "run.bat"), "rb").read()
assert rb.count(b"\n") == rb.count(b"\r\n") and b'if /i "%~2"=="live" goto dashlive' in rb and b"run dashboard live" in rb
assert b'"%PY%" dashboard_server.py' in rb
print("account_live: all checks passed")
