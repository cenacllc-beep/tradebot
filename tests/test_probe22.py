"""research/probe22.py (PROBE22, research/PLAN22.md section 7), on a fake Deribit. No network. Covers: no DVOL value is
ever written or printed (only counts, timestamps, ranges, hashes, field names); paging back with `continuation`, the
oldest candle, page sizes and month counts; the timestamp convention from past minute candles; the revision hash
(not yet / same / different, 24 hours apart) and a damaged record left untouched; the host and cutoff checks (nothing
dated 2026-11-01 or later is requested or kept); GETs only, the User-Agent, at most one request a second.
python test_probe22.py WORK OUT"""
import os, sys, json, io, contextlib, tempfile, urllib.parse
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import probe22 as P

P.OUT_DIR = os.path.join(OUT, "results")
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22.json")
P.OUT_MD = os.path.join(P.OUT_DIR, "probe22.md")

# ---------- research only, read-only, one host ----------
src = open(os.path.join(WORK, "research", "probe22.py"), encoding="utf-8").read()
assert "POST" not in src and "private/" not in src and "/portfolio" not in src and "import live" not in src
assert 'method="GET"' in src and P.UA == "tradebot-paper-research/1.0" and P.HOST == "www.deribit.com"
assert "paper.db" not in src and "live.db" not in src
assert P.CUTOFF_MS == P.ms(2026, 11, 1) and P.REV_RANGE[1] <= P.CUTOFF_MS and P.CONV_RANGE[1] <= P.CUTOFF_MS

# ---------- the fake exchange ----------
HOUR, MIN = 3600 * 1000, 60 * 1000
OLDEST = P.ms(2026, 5, 20, 7)
GAP = (P.ms(2026, 7, 4), P.ms(2026, 7, 5))          # one missing day of hourly candles
MIN_SPAN = (P.ms(2026, 10, 14), P.ms(2026, 10, 17))  # minute history exists only here
PAGE = 100
SERVED = set()   # every value the fake ever handed out


class Fake(object):
    def __init__(self, hour_conv="start", min_conv="start", seed=0, rogue=False, minute_error=False):
        self.hour_conv, self.min_conv, self.seed, self.rogue, self.minute_error = hour_conv, min_conv, seed, rogue, minute_error
        self.calls, self.clock_at, self.bump = [], [], set()
        self._hours = None

    def v(self, m, j):   # a distinct value per minute and field, six decimals
        k = ((m // MIN) * 7919 + j * 104729 + self.seed * 31) % 999983
        return round(40 + k / 1e6 * 30, 6)

    def minute(self, m):
        return [self.v(m, 0), self.v(m, 1) + 1, self.v(m, 2) - 1, self.v(m, 3)]   # o, h, l, c

    def hour(self, T):
        ms_ = [self.minute(T + i * MIN) for i in range(60)]
        c = [ms_[0][0], max(x[1] for x in ms_), min(x[2] for x in ms_), ms_[-1][3]]
        if T in self.bump:
            c[3] = round(c[3] + 0.000001, 6)
        return c

    def hours(self):
        if self._hours is None:
            out, T = {}, OLDEST
            while T < P.CUTOFF_MS + 10 * HOUR:   # the fake also holds November: the probe must never ask for it
                if not (GAP[0] <= T < GAP[1]):
                    out[T + (HOUR if self.hour_conv == "end" else 0)] = self.hour(T)
                T += HOUR
            self._hours = out
        return self._hours

    def minutes(self, a, b):
        out, m = {}, max(a - 2 * MIN, MIN_SPAN[0]) // MIN * MIN
        while m < min(b + 2 * MIN, MIN_SPAN[1]):
            lab = m + (MIN if self.min_conv == "end" else 0)
            if a <= lab <= b:
                out[lab] = self.minute(m)
            m += MIN
        return out

    def __call__(self, url, headers, timeout):
        self.calls.append(url); self.clock_at.append(clock[0])
        assert headers["User-Agent"] == "tradebot-paper-research/1.0"
        u = urllib.parse.urlsplit(url); q = dict(urllib.parse.parse_qsl(u.query))
        assert u.hostname == "www.deribit.com" and u.path == "/api/v2/public/get_volatility_index_data"
        a, b, res = int(q["start_timestamp"]), int(q["end_timestamp"]), q["resolution"]
        assert b < P.CUTOFF_MS, "requested past the cutoff"
        if res == "60":
            if self.minute_error:
                return 400, {}, json.dumps({"jsonrpc": "2.0", "error": {"code": 10001, "message": "bad request 47.918273"}}).encode()
            src_ = self.minutes(a, b)
        else:
            src_ = dict((t, c) for t, c in self.hours().items() if a <= t <= b)
            if self.hour_conv == "end":   # a fake that labels the hour's end also has the cutoff-hour candle...
                pass
        ts = sorted(src_)[-PAGE:]
        data = [[t] + src_[t] for t in ts]
        if self.rogue and data:
            data.append([P.CUTOFF_MS] + [55.555555] * 4)
        for row in data:
            SERVED.update(row[1:])
        cont = (ts[0] - 1) if ts and len(src_) > PAGE else None
        body = {"jsonrpc": "2.0", "result": {"data": data, "continuation": cont}, "usIn": 1, "usOut": 2, "usDiff": 1,
                "testnet": False}
        return 200, {}, json.dumps(body).encode()


clock = [P.ms(2026, 11, 26, 12) / 1000.0]
sleeps = []
def fake_sleep(s): sleeps.append(s); clock[0] += s
P.CLOCK = lambda: clock[0]
P.SLEEP = fake_sleep

def run(fake):
    P.TRANSPORT = fake
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = P.main()
        except P.ProbeStop as e:
            rc = ("stop", str(e))
    return rc, buf.getvalue()

def files():
    return open(P.OUT_JSON, encoding="utf-8").read(), open(P.OUT_MD, encoding="utf-8").read()

def no_values(*texts):
    blob = "\n".join(texts)
    for v in SERVED:
        for s in (repr(v), "%.6f" % v, "%.4f" % v):
            if len(s.split(".")[-1]) >= 3:   # short strings say nothing (they could sit inside a clock reading)
                assert s not in blob, "a DVOL value was written: %s" % s

# ---------- host and cutoff checks ----------
good = "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp=1&end_timestamp=2&resolution=3600"
assert P.check_url(good) == good
for bad in (good.replace("https://", "http://"), good.replace("www.deribit.com", "evil.example"),
            good.replace("www.deribit.com", "www.deribit.com.evil.example"), good.replace("www.deribit.com", "test.deribit.com"),
            good.replace("www.deribit.com", "www.deribit.com:8443"), good.replace("www.deribit.com", "u:p@www.deribit.com"),
            good.replace("/public/get_volatility_index_data", "/private/buy"), good + "&extra=1",
            good.replace("end_timestamp=2", "end_timestamp=%d" % P.CUTOFF_MS),
            good.replace("start_timestamp=1", "start_timestamp=%d" % (P.CUTOFF_MS + 5))):
    try:
        P.check_url(bad); raise AssertionError("accepted %s" % bad)
    except P.ProbeStop:
        pass
try:
    P.get("BTC", 0, P.CUTOFF_MS, "3600"); raise AssertionError("asked for the cutoff")
except P.ProbeStop:
    pass

# ---------- first run: paging, months, convention, "not yet" ----------
f1 = Fake()
rc, out = run(f1)
assert rc == 0, (rc, out)
j, md = files()
no_values(j, md, out)
R = json.loads(j)
for c in ("BTC", "ETH"):
    h = R["history"][c]
    assert h["oldest"] == "2026-05-20T07:00:00Z" and h["newest"] == "2026-10-31T23:00:00Z", (h["oldest"], h["newest"])
    want = (P.CUTOFF_MS - OLDEST) // HOUR - 24
    assert h["candles"] == want and h["gaps_over_an_hour"] == 1 and h["not_on_the_hour"] == 0
    assert h["report_months"]["2026-06"] == dict(candles=720, hours=720, coverage=1.0)
    assert h["report_months"]["2026-07"]["candles"] == 744 - 24 and h["report_months"]["2026-10"]["candles"] == 744
    assert h["months"]["2026-05"]["candles"] == 12 * 24 - 7
    p = h["paging"]
    assert p["page_sizes"]["first"] == PAGE and p["continuation"] == "earlier" and p["stopped"] == "continuation null"
    assert p["pages"] == -(-want // PAGE)
    assert p["fields"] == dict(top=["jsonrpc", "result", "testnet", "usDiff", "usIn", "usOut"],
                               result=["continuation", "data"], candle_lengths=[5])
    assert R["convention"][c]["verdict"] == "start", R["convention"][c]
    assert R["revision"][c]["candles"] == 7 * 24 and len(R["revision"][c]["sha256"]) == 64
    assert R["revision_check"][c]["verdict"] == "not yet"
assert all(int(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))["end_timestamp"]) < P.CUTOFF_MS for u in f1.calls)
gaps = [b - a for a, b in zip(f1.clock_at, f1.clock_at[1:])]
assert gaps and min(gaps) >= 1.0 - 1e-9, min(gaps)   # at most one request a second
assert R["convention"]["BTC"]["minute_oldest"] == "2026-10-15T04:00:00Z" and "oldest 1-minute candle" in md
assert "incomplete history" not in md
assert "**start**" in md and "not yet" in md and "2026-06 | 720 | 720 | 100.0%" in md

# ---------- under 24 hours later: still "not yet"; 25 hours: "same"; a revised candle: "different" ----------
clock[0] += 3 * 3600
rc, out = run(Fake()); assert rc == 0
assert json.loads(files()[0])["revision_check"]["BTC"]["verdict"] == "not yet"
clock[0] += 25 * 3600
rc, out = run(Fake()); assert rc == 0
R = json.loads(files()[0])
assert R["revision_check"]["BTC"]["verdict"] == "same" and len(R["revision_check"]["BTC"]["compared_with"]) == 2
assert len(R["runs"]) == 3 and R["rolling"]["BTC"] == "oldest candle unchanged"
clock[0] += 25 * 3600
f4 = Fake(); f4.bump = {P.REV_RANGE[0] + 5 * HOUR}
rc, out = run(f4); assert rc == 0
j, md = files(); no_values(j, md, out)
R = json.loads(j)
assert R["revision_check"]["BTC"]["verdict"] == "different" and len(R["revision_check"]["BTC"]["differs_from"]) == 3
assert "**different**" in md
f5 = Fake(); f5.bump = {P.REV_RANGE[1] + 5 * HOUR}   # a change outside the fixed week does not count
clock[0] += 25 * 3600
rc, out = run(f5); assert rc == 0
assert json.loads(files()[0])["revision_check"]["BTC"]["verdict"] == "different"   # still differs from run 4
assert json.loads(files()[0])["revision_check"]["BTC"]["differs_from"] == [json.loads(files()[0])["runs"][3]["run_utc"]]

# ---------- end-labelled candles, and minute history missing ----------
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22_b.json"); P.OUT_MD = os.path.join(P.OUT_DIR, "probe22_b.md")
rc, out = run(Fake(hour_conv="end", min_conv="end")); assert rc == 0
j, md = files(); no_values(j, md, out)
R = json.loads(j)
assert R["convention"]["ETH"]["verdict"] == "end", R["convention"]["ETH"]
assert R["history"]["BTC"]["newest"] == "2026-10-31T23:00:00Z"   # the hour that ends at the cutoff is not requested
os.remove(P.OUT_JSON)
rc, out = run(Fake(hour_conv="end", min_conv="start")); assert rc == 0
assert json.loads(files()[0])["convention"]["BTC"]["verdict"] == "end"
os.remove(P.OUT_JSON)
rc, out = run(Fake(minute_error=True)); assert rc == 0
R = json.loads(files()[0])
assert R["convention"]["BTC"]["verdict"] == "undetermined" and "error code 10001" in R["convention"]["BTC"]["reason"]
assert R["history"]["BTC"]["candles"] > 0   # the rest of the probe still ran

# ---------- a candle dated 2026-11-01 or later: stop, save nothing ----------
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22_c.json"); P.OUT_MD = os.path.join(P.OUT_DIR, "probe22_c.md")
rc, out = run(Fake(rogue=True))
assert rc[0] == "stop" and "2026-11-01" in rc[1] and not os.path.exists(P.OUT_JSON) and not os.path.exists(P.OUT_MD)
assert "55.555555" not in out

# ---------- a damaged record is never overwritten ----------
with open(P.OUT_JSON, "w", encoding="utf-8") as fh:
    fh.write("{not json")
rc, out = run(Fake())
assert rc[0] == "stop" and "damaged" in rc[1]
assert open(P.OUT_JSON, encoding="utf-8").read() == "{not json"

# ---------- retries: a 429 and a network error are retried, still one request a second ----------
class Flaky(Fake):
    def __init__(self):
        Fake.__init__(self); self.n = 0
    def __call__(self, url, headers, timeout):
        self.n += 1
        if self.n == 1:
            self.calls.append(url); self.clock_at.append(clock[0]); return 429, {"retry-after": "7"}, b"{}"
        if self.n == 2:
            self.clock_at.append(clock[0]); raise OSError("reset")
        return Fake.__call__(self, url, headers, timeout)
fl = Flaky(); P.TRANSPORT = fl
j1 = P.get("BTC", P.REV_RANGE[0], P.REV_RANGE[1] - 1, "3600")
assert "result" in j1 and fl.n == 3
assert min(b - a for a, b in zip(fl.clock_at, fl.clock_at[1:])) >= 1.0 - 1e-9
assert 7 in sleeps   # Retry-After honoured

# ---------- Deribit's error 10028 is retried whatever the HTTP status; Retry-After capped at 60 s; no sleep after the last try ----------
class Busy(object):
    def __init__(self, n_busy): self.n, self.n_busy = 0, n_busy
    def __call__(self, url, headers, timeout):
        self.n += 1
        if self.n <= self.n_busy:
            return 400, {"retry-after": "500"}, json.dumps({"error": {"code": 10028, "message": "too_many_requests"}}).encode()
        return 200, {}, json.dumps({"result": {"data": [], "continuation": None}}).encode()
del sleeps[:]
P.TRANSPORT = Busy(2); assert "result" in P.get("BTC", P.REV_RANGE[0], P.REV_RANGE[1] - 1, "3600")
assert sleeps.count(60.0) == 2, sleeps
del sleeps[:]
P.TRANSPORT = Busy(99)
try:
    P.get("BTC", P.REV_RANGE[0], P.REV_RANGE[1] - 1, "3600"); raise AssertionError("no give-up")
except RuntimeError as e:
    assert "gave up after 4 tries" in str(e) and "10028" in str(e)
assert sleeps.count(60.0) == 3, sleeps   # 4 tries, 3 waits: none after the last

# ---------- malformed answers: fixed texts, no value ever reaches stdout or stderr ----------
SECRET = "47.918273"
def run_cli(fake):
    P.TRANSPORT = fake
    o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
        try:
            P.cli(); code = 0
        except SystemExit as x:
            code = x.code
    return code, o.getvalue() + e.getvalue()
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22_d.json"); P.OUT_MD = os.path.join(P.OUT_DIR, "probe22_d.md")
class Body(object):
    def __init__(self, body): self.body = body
    def __call__(self, url, headers, timeout): return 200, {}, self.body
for body, want in ((('{"result": {"data": [[1, ' + SECRET).encode(), 0),
                   (json.dumps({"result": {"data": [[P.REV_RANGE[0], SECRET, 1.0, 1.0, 1.0]], "continuation": None}}).encode(), 2),
                   (json.dumps({"result": {"data": [[P.REV_RANGE[0] + 1, 1.0, 1.0, 1.0, 1.0]], "continuation": None}}).encode(), 2),
                   (json.dumps({"result": {"data": [[P.REV_RANGE[0], 1.0, 1.0, 1.0]], "continuation": None}}).encode(), 2),
                   (json.dumps({"result": {"data": [[float(P.REV_RANGE[0]), 1.0, 1.0, 1.0, 1.0]], "continuation": None}}).encode(), 2),
                   (json.dumps({"result": {"data": [[P.ms(2025, 1, 1), 1.0, 1.0, 1.0, 1.0]], "continuation": None}}).encode(), 2),   # history accepts it, the week does not
                   (json.dumps({"result": {"data": {"x": SECRET}, "continuation": None}}).encode(), 0),
                   (json.dumps({"result": {"data": [], "continuation": SECRET}}).encode(), 0)):
    for f_ in (P.OUT_JSON, P.OUT_MD):
        if os.path.exists(f_): os.remove(f_)
    code, text = run_cli(Body(body))
    assert SECRET not in text and "Traceback" not in text, text
    if want == 2:
        assert code == 2 and "malformed candle" in text and not os.path.exists(P.OUT_JSON), (body, text)
    else:
        assert code == 0, (body, text)
        j_, md_ = files(); assert SECRET not in j_ + md_
orig = P.history
def leak(c): raise KeyError(SECRET)
P.history = leak
code, text = run_cli(Fake())
assert code == 1 and text.strip().endswith("PROBE22 failed: KeyError") and SECRET not in text, text
P.history = orig
code, text = run_cli(Fake(minute_error=True)); assert code == 0 and SECRET not in text
assert SECRET not in "".join(files())

# ---------- revision counts: "not checked" unless both runs have 168 candles; count changes apart ----------
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22_e.json"); P.OUT_MD = os.path.join(P.OUT_DIR, "probe22_e.md")
assert run(Fake())[0] == 0
clock[0] += 25 * 3600
class Short(Fake):
    def hours(self):
        h = dict(Fake.hours(self)); h.pop(P.REV_RANGE[0] + 3 * HOUR, None); return h
assert run(Short())[0] == 0
R = json.loads(files()[0])
assert R["revision"]["BTC"]["candles"] == 167 and R["revision_check"]["BTC"]["verdict"] == "not checked"
assert R["revision_check"]["BTC"]["count_changed"] == [R["runs"][0]["run_utc"]]
clock[0] += 25 * 3600
assert run(Fake())[0] == 0
R = json.loads(files()[0])
assert R["revision_check"]["BTC"]["verdict"] == "same" and R["revision_check"]["BTC"]["compared_with"] == [R["runs"][0]["run_utc"]]
assert R["revision_check"]["BTC"]["count_changed"] == [R["runs"][1]["run_utc"]] and "candle count differs" in files()[1]

# ---------- the record's checks: each damaged field stops the probe, the file is left as it was ----------
good_rec = json.loads(files()[0])
for mut in (lambda r: r["runs"][0].update(run_s="x"), lambda r: r["runs"][0].update(run_s=True),
            lambda r: r["runs"][0].pop("run_s"), lambda r: r["runs"][0].update(revision=[]),
            lambda r: r["runs"][0].update(run_utc=5), lambda r: r["runs"][0]["revision"].update(BTC="x"),
            lambda r: r["runs"][0].update(oldest_ms=[]), lambda r: r.update(runs={}), lambda r: r["runs"].append(3)):
    rec = json.loads(json.dumps(good_rec)); mut(rec)
    txt = json.dumps(rec)
    with open(P.OUT_JSON, "w", encoding="utf-8") as fh: fh.write(txt)
    rc, out = run(Fake())
    assert rc[0] == "stop" and "damaged" in rc[1] and open(P.OUT_JSON, encoding="utf-8").read() == txt

# ---------- whole-run budget: ends cleanly, history marked incomplete or errored ----------
P.OUT_JSON = os.path.join(P.OUT_DIR, "probe22_f.json"); P.OUT_MD = os.path.join(P.OUT_DIR, "probe22_f.md")
P.BUDGET_S = 10
rc, out = run(Fake()); assert rc == 0, rc
R = json.loads(files()[0])
assert "run budget" in R["history"]["BTC"]["error"] and "run budget" in R["convention"]["ETH"]["reason"]
P.BUDGET_S = 75 * 60
os.remove(P.OUT_JSON)
class Stuck(Fake):   # continuation that does not move back: paging stops early, the md says so
    def __call__(self, url, headers, timeout):
        st, h, b = Fake.__call__(self, url, headers, timeout)
        j = json.loads(b.decode())
        if j["result"]["continuation"] is not None:
            j["result"]["continuation"] = int(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["end_timestamp"])
        return st, h, json.dumps(j).encode()
rc, out = run(Stuck()); assert rc == 0
assert "incomplete history" in files()[1] and "continuation did not move back" in files()[1]

# ---------- the real transport: redirects refused, bodies over the limit refused (a local server, no network) ----------
import threading, http.server
for k in ("no_proxy", "NO_PROXY"): os.environ[k] = "127.0.0.1,localhost"
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/redir"):
            self.send_response(302); self.send_header("Location", "http://127.0.0.1:%d/ok" % self.server.server_port)
            self.send_header("Content-Length", "0"); self.end_headers(); return
        body = b"x" * (2000 if self.path.startswith("/big") else 10)
        self.send_response(200); self.send_header("Retry-After", "3"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_port
st, hd, b = P._urllib_transport(base + "/ok", {"User-Agent": P.UA}, 5)
assert st == 200 and b == b"x" * 10 and hd.get("retry-after") == "3"
try:
    P._urllib_transport(base + "/redir", {"User-Agent": P.UA}, 5); raise AssertionError("followed a redirect")
except P.ProbeStop as e:
    assert "redirect" in str(e)
P.MAX_BODY = 1000
try:
    P._urllib_transport(base + "/big", {"User-Agent": P.UA}, 5); raise AssertionError("accepted a large body")
except P.ProbeStop as e:
    assert "refused" in str(e)
P.MAX_BODY = 20000000
srv.shutdown()

# ---------- the workflow ----------
wf = open(os.path.join(WORK, "cloud", "workflows", "probe22.yml"), encoding="utf-8").read()
assert "workflow_dispatch" in wf and "schedule" not in wf and "pip install" not in wf
assert "f=research/results/probe22.json" in wf and "git diff --quiet HEAD -- \"$f\"" in wf and "research/results/probe22" in wf
assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in wf and "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in wf
assert not os.path.exists(os.path.join(WORK, ".github", "workflows", "probe22.yml"))
print("All PROBE22 checks passed.")
