"""ops/pc_report.py (the PC's own report when Claude is unavailable), ops/pc_key.py (the DPAPI key file) and the jobs.py
steps that run it: fake logs, a fake NVIDIA transport, a fake DPAPI and fake icacls. No network, no Windows needed.
python test_pc_report.py WORK OUT"""
import os, sys, json, re, subprocess, time, threading
WORK, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
os.environ["TRADEBOT_PC_REPORT"] = ""   # never the PC's real report
sys.path.insert(0, WORK)
sys.path.insert(0, os.path.join(WORK, "ops"))
import pc_report as P
import pc_key as K
import backup_ai as B
assert "live" not in sys.modules, "live.py was imported"

src = open(os.path.join(WORK, "ops", "pc_report.py"), encoding="utf-8").read()
for bad in ("import live", "from live", "sqlite3", "connect(", "/portfolio", "run.bat\"", "paper.db\""):
    assert bad not in src, bad
assert "import backup_ai" in src and "def pick" not in src and "PREFERENCES" not in src, "reuse backup_ai, do not copy it"

def L(s):   # a local time stamp as jobs.py writes it (offset left out: read as this PC's local time)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s))
def at(h, m, day=27):
    return time.mktime((2026, 11, day, h, m, 0, 0, 0, -1))

def logfile(name, text):
    d = os.path.join(OUT, name, "logs")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "tasks.log")
    with open(p, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    return p

SETTLE = """===== {a} settle
----- settle step: run.bat settle
SETTLED KXRAIN-26NOV26-NYC no x2: Kalshi settled it no, P&L +0.31
SETTLED KXRAIN-26NOV26-SEA yes x1: Kalshi settled it yes, P&L +0.62
live (demo): 0 settled now; 3 settled in all, net -$0.20 after fees
live (prod): 1 settled now; 5 settled in all, net -$1.10 after fees
LEARNING: paper v3 rain 40 settled, won 9 (22% vs 25% implied), -4.1c per contract after fees
FRESHNESS: all current (12 checks)
----- settle step end (exit 0)
----- settle step: run.bat report
SHADOW v3 rain: 210 resolved. Brier forecast=0.083 vs market=0.067 (lower wins) [GATE]
TRADES v3 rain: settled=40 pnl=$-6.91 win=22%  [GATE]
CLEAR MARGIN (gate, final): forecast minus market Brier +0.0160 per market day, needs a lead of 2.06 SE over 26 days = 0.0090: not clear
GATE (v3 rain only): not passed
GATE LOOK (single look, stored 2026-11-18 14:00): did not pass
----- settle step end (exit 0)
===== {b} settle done (exit 0)
"""
EVE_OK = """===== {a} evening
----- evening step: run.bat scan
AUDIT: scan 1a2b3c4d recorded 52 decisions (NO_EDGE 50, TRADED 2, _failed 0)
estimator error KXRAIN-26NOV28-PHX timeout
v4: forecast lookup failed for KXRAIN-26NOV28-BOS boom
shadow: price history not available (HTTP 500); will retry at the next settle
PAPER no KXRAIN-26NOV28-NYC x3 @0.12 fair=0.30
52 markets in shadow log, 1 paper trades logged (rain only; temperature is logged, not traded)
live (demo): no new paper rain trades to copy
live (prod): cash $8.15, at risk $0.36 of $50.00
FRESHNESS: all current (12 checks)
----- evening step end (exit 0)
===== {b} evening done (exit 0)
"""
now = at(15, 10)
p = logfile("settle", SETTLE.format(a=L(at(14, 51)), b=L(at(14, 58))))
F = P.facts(P.latest(P.read_tail(p), "settle"), "settle", now)
assert F["problems"] == [], F["problems"]
assert len(F["settled"]) == 2 and F["brier"] and "0.083" in F["brier"][0] and F["gate"][-1].startswith("GATE LOOK (single look, stored")
assert F["live_demo"] and F["live_prod"] and F["freshness"] == "FRESHNESS: all current (12 checks)"
txt = P.render(F)
for want in ("Trades settled: 2", "Brier forecast=0.083 vs market=0.067", "GATE LOOK (single look, stored 2026-11-18 14:00): did not pass",
             "live (demo): 0 settled now", "live (prod): 1 settled now", "FRESHNESS: all current", "Problems: none", "P&L +0.31", "LEARNING:"):
    assert want in txt, want
ai_txt = P.render(F, ai=True)   # what may go to NVIDIA: no account or money line
for bad in ("live (", "SETTLED ", "P&L", "$", "LEARNING", "pnl", "net -"):
    assert bad not in ai_txt, (bad, ai_txt)
assert "Trades settled: 2" in ai_txt and "0.083" in ai_txt and "GATE LOOK" in ai_txt

# per-market errors that are retried never become problems (narrow list); a retried scan try is a note
p = logfile("eve_ok", EVE_OK.format(a=L(at(20, 55)), b=L(at(21, 5))))
F = P.facts(P.latest(P.read_tail(p), "evening"), "evening", at(21, 6))
assert F["problems"] == [] and F["scan"].startswith("52 markets in shadow log, 1 paper") and len(F["paper"]) == 1, F["problems"]

# every problem line
BAD = """===== {a} evening
WAITING FOR NETWORK since 20:55: api.elections.kalshi.com is not reachable (the PC may be in standby with its network off)
network: back after 12 min
----- evening step: run.bat settle
SETTLE: 2 of 9 markets could not be read from Kalshi; they stay open and are checked again at the next settle. First: KXRAIN-Y
----- evening step end (exit 0)
----- evening step: run.bat scan
KILL SWITCH ON (C:\\t\\KILL.txt): scan halted. No paper trades, no shadow orders, no Kalshi orders. Resume: run unkill
TRADES BLOCKED: the audit ledger is unavailable. Markets are logged as before, but no paper trade can open without its decision record
AUDIT: could not start the scan record (disk full); no paper trades this scan
Backup failed, so the scan did not run.
  ORDER OUTCOME UNKNOWN KXRAIN-X: timeout (sync will look it up; no new orders until then)
FRESHNESS: 1 stale, 1 failed: scan 26 hours old
----- evening step end (exit 1)
scan: try 1 of 3 failed (exit 1); trying again in 5 min
JOB LOCK: another Tradebot step held the lock (run.bat hourly), so `run.bat scan` did not run this time.
scan: all 3 tries failed
===== {b} evening done (exit 1)
"""
p = logfile("bad", BAD.format(a=L(at(20, 55)), b=L(at(23, 59))))
F = P.facts(P.latest(P.read_tail(p), "evening"), "evening", at(23, 59))
pr = "\n".join(F["problems"])
for want in ("WAITING FOR NETWORK", "KILL SWITCH ON", "TRADES BLOCKED", "AUDIT: could not start", "JOB LOCK", "Backup failed",
             "all 3 tries failed", "ORDER OUTCOME UNKNOWN", "SETTLE: 2 of 9", "FRESHNESS: 1 stale", "exit 1",
             "Tonight's scan did not log"):
    assert want in pr, (want, pr)
assert "network: back after 12 min" in F["notes"] and any(n.startswith("scan: try 1") for n in F["notes"])
assert "scan: try 1" not in pr and len(F["problems"]) == len(set(F["problems"]))
ai_txt = P.render(F, ai=True)
assert "ORDER OUTCOME" not in ai_txt and "A Kalshi account problem" in ai_txt

# ---- attribution (the review's blocker): step markers keep each job's lines apart ----
# (a) an hourly job opened during the evening scan step, (b) another during the pause between scan tries
INTER = """===== {e} evening
----- evening step: run.bat settle
FRESHNESS: all current (12 checks)
----- evening step end (exit 0)
----- evening step: run.bat scan
estimator error KXRAIN-X timeout
===== {h1} hourly
schedule settings: applied
WAITING FOR NETWORK since 21:20: api.elections.kalshi.com is not reachable
Traceback (most recent call last):
  File "main.py", line 1, in scan
RuntimeError: NWS 503
----- evening step end (exit 1)
scan: try 1 of 3 failed (exit 1); trying again in 5 min
network: back after 1 min
JOB LOCK: another Tradebot step held the lock (run.bat scan), so `run.bat hourly` did not run this time.
===== {h1d} hourly done (exit 0)
===== {h2} hourly
----- hourly step: run.bat hourly
plan20 sample: 14 markets
----- hourly step end (exit 0)
===== {h2d} hourly done (exit 0)
----- evening step: run.bat scan
===== {h3} hourly
40 markets in shadow log, 0 paper trades logged (rain only; temperature is logged, not traded)
JOB LOCK: another Tradebot step held the lock (run.bat scan), so `run.bat hourly` did not run this time.
FRESHNESS: all current (12 checks)
----- evening step end (exit 0)
scan: succeeded on try 2
===== {h3d} hourly done (exit 0)
===== {ed} evening done (exit 0)
"""
txt = INTER.format(e=L(at(20, 55)), h1=L(at(21, 20)), h1d=L(at(21, 31)), h2=L(at(21, 32)), h2d=L(at(21, 33)),
                   h3=L(at(22, 20)), h3d=L(at(22, 31)), ed=L(at(22, 25)))
ev = P.latest(txt, "evening")
F = P.facts(ev, "evening", at(22, 40))
assert F["scan"] and F["scan"].startswith("40 markets"), ev["lines"]
assert F["problems"] == [], F["problems"]   # no false "scan missing", and the hourly job's lock and network lines stay its own
assert "RuntimeError: NWS 503" in ev["lines"] and "plan20 sample: 14 markets" not in ev["lines"]
hrs = [b for b in P.blocks(txt) if b["job"] == "hourly"]
assert any(s.startswith("JOB LOCK") for s in hrs[0]["lines"]) and any("schedule settings" in s for s in hrs[0]["lines"])
assert "plan20 sample: 14 markets" in hrs[1]["lines"] and any(s.startswith("JOB LOCK") for s in hrs[2]["lines"])
assert any(s.startswith("WAITING FOR NETWORK") for s in hrs[0]["lines"]), "the hourly job's wait is its own"
# the same log written before the markers existed: the old rule would credit the scan to the hourly job
legacy = "\n".join(l for l in txt.splitlines() if not l.startswith("-----"))
assert P.latest(legacy, "evening") is not None   # still parsed (fallback)
# (c) the settle job overlapping the 15:20 hourly job
SOVER = """===== {s} settle
WAITING FOR NETWORK since 14:51: api.elections.kalshi.com is not reachable
===== {h} hourly
network: back after 30 min
----- settle step: run.bat settle
SETTLED KXRAIN-A no x1: Kalshi settled it no, P&L +0.10
FRESHNESS: all current (12 checks)
----- settle step end (exit 0)
JOB LOCK: another Tradebot step held the lock (run.bat settle), so `run.bat hourly` did not run this time.
===== {hd} hourly done (exit 0)
----- settle step: run.bat report
GATE LOOK (single look, stored 2026-11-18 14:00): did not pass
----- settle step end (exit 0)
===== {sd} settle done (exit 0)
"""
txt = SOVER.format(s=L(at(14, 51)), h=L(at(15, 20)), hd=L(at(15, 31)), sd=L(at(15, 35)))
F = P.facts(P.latest(txt, "settle"), "settle", at(15, 40))
assert len(F["settled"]) == 1 and F["gate"] and not any("JOB LOCK" in p for p in F["problems"]), F["problems"]
assert any(s.startswith("JOB LOCK") for s in P.latest(txt, "hourly")["lines"])
cut = "===== %s settle\nSETTLED A no x1: Kalshi settled it no, P&L +0.10\n===== %s settle\nFRESHNESS: all current (3 checks)\n===== %s settle done (exit 0)\n" % (
    L(at(14, 51, 26)), L(at(14, 51)), L(at(14, 55)))
b = P.latest(cut, "settle")
assert b["finished"] and b["lines"] == ["FRESHNESS: all current (3 checks)"]
assert P.facts(None, "settle")["problems"]   # no block at all is a problem

# ---- late-night check: only 11 PM to 1 AM; every way tonight's scan can be missing has a problem and its reason ----
calls = []
fake_popen = lambda *a, **k: calls.append((a, k))
none_key = lambda: (None, K.MISSING)
p = logfile("late_none", SETTLE.format(a=L(at(14, 51)), b=L(at(14, 58))))
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(15, 0))
assert path is None and "only between" in line
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(23, 41))
md = open(path, encoding="utf-8").read()
assert path.endswith("2026-11-27-latenight.md") and "has not started" in md and "PROBLEMS: 1" in md and len(calls) == 1
path2, _ = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(0, 20, 28))
assert path2 == path and len(calls) == 1, "the 00:20 check does not repeat the 23:20 toast for the same problem"
p = logfile("late_wait", "===== %s evening\nWAITING FOR NETWORK since 20:55: api.elections.kalshi.com is not reachable\n" % L(at(20, 55)))
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(23, 41))
md = open(path, encoding="utf-8").read()
assert "still waiting for the network" in md and "WAITING FOR NETWORK" in md and "1:00 AM" in md, md
p = logfile("late_skip", "===== %s evening\nScan skipped: outside the evening scan window (8:50 PM to 1:00 AM). The next 8:55 PM run scans.\n===== %s evening done (exit 0)\n" % (L(at(23, 2)), L(at(23, 3))))
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(23, 41))
md = open(path, encoding="utf-8").read()
assert "Tonight's scan was skipped: Scan skipped" in md and "PROBLEMS: 1" in md, md
F = P.facts(P.latest(P.read_tail(p), "evening"), "evening")
assert F["problems"] == [], "a make-up run that only settles is not a problem in the evening report itself"
p = logfile("late_notime", "===== no-time evening\nevening could not start: Python not found at C:\\x\\python.exe\n===== no-time evening done (exit 9009)\n")
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(23, 41))
md = open(path, encoding="utf-8").read()
assert "has no time in the log (evening could not start: Python not found" in md and "exit 9009" in md, md
p = logfile("late_ok", EVE_OK.format(a=L(at(20, 55)), b=L(at(21, 5))))
path, line = P.report("latenight", log=p, key_loader=none_key, popen=fake_popen, now=at(23, 41))
assert path is None and "scan ran" in line and not os.path.exists(os.path.join(OUT, "late_ok", "logs", "report_latest.md"))

# ---- files: report_latest.md and one per day and job, newest 30 kept, no temp files left ----
p = logfile("files", SETTLE.format(a=L(at(14, 51)), b=L(at(14, 58))))
rep = os.path.join(OUT, "files", "logs", "reports")
os.makedirs(rep, exist_ok=True)
for i in range(35):
    open(os.path.join(rep, "2026-10-%02d-settle.md" % (i % 28 + 1) if i < 28 else "2026-09-%02d-evening.md" % i), "w").close()
path, line = P.report("settle", log=p, key_loader=none_key, popen=fake_popen, now=now)
assert os.path.basename(path) == "2026-11-27-settle.md" and "deterministic" in line
assert len([f for f in os.listdir(rep) if f.endswith(".md")]) == 30 and os.path.exists(path)
assert not [f for f in os.listdir(rep) + os.listdir(os.path.dirname(rep)) if f.endswith(".tmp")]
latest_md = open(os.path.join(OUT, "files", "logs", "report_latest.md"), encoding="utf-8").read()
assert "Status: All clear" in latest_md and "Wording: deterministic (no NVIDIA key kept on this PC)" in latest_md
assert "AI budget: at most 3 calls and 150 s (this script); not used" in latest_md
assert latest_md.index("## Problems") < latest_md.index("## Summary") < latest_md.index("## Facts")
# each key status reads differently on the Wording line
for st, want in ((K.DECRYPT, "could not be decrypted"), (K.PERMISSION, "permissions are not limited"), (K.MISSING, "no NVIDIA key")):
    P.report("settle", log=p, key_loader=lambda st=st: (None, st), popen=fake_popen, now=now)
    assert ("Wording: deterministic (" + K.STATUS_TEXT[st]) in open(path, encoding="utf-8").read() and want in K.STATUS_TEXT[st]
P.report("settle", log=p, key_loader=lambda: 1 / 0, popen=fake_popen, now=now)
assert "Wording: deterministic (the key could not be loaded)" in open(path, encoding="utf-8").read()

# ---- AI wording through backup_ai's own client, with a fake NVIDIA transport ----
KEY = "nvapi-" + "Zq9Xw8Vu7" * 5
sent = []
def fake_get(url, headers, timeout):
    assert url.startswith("https://integrate.api.nvidia.com/v1/")
    return 200, {}, json.dumps(dict(data=[dict(id="nvidia/nv-embedqa-e5-v5"), dict(id="meta/llama-3.1-8b-instruct")]))
answer = {"text": ""}
def fake_post(url, headers, body, timeout):
    sent.append((url, headers, body))
    return 200, {}, json.dumps(dict(choices=[dict(message=dict(content=answer["text"]))]))
B.http_get, B.http_post = fake_get, fake_post
fac = lambda k: B.AI(key=k, sleep=lambda s: None)
LEAK = SETTLE.replace("FRESHNESS: all current", "note from owner@example.com token=ghp_ABCDEFGHIJKLMNOPQRSTuvwx1234\nFRESHNESS: all current")
p = logfile("ai", LEAK.format(a=L(at(14, 51)), b=L(at(14, 58))))
def run_ai(text, log=p):
    answer["text"] = text
    path, line = P.report("settle", log=log, key_loader=lambda: (KEY, K.OK), ai_factory=fac, popen=fake_popen, now=now)
    return open(path, encoding="utf-8").read()
md = run_ai("<think>x 77</think>All clear. 2 trades settled; v3 Brier 0.083 against the market's 0.067. The stored gate look did not pass.")
assert "Wording: AI (NVIDIA meta/llama-3.1-8b-instruct; every number and problem checked" in md and "2 trades settled" in md and "77" not in md, md
assert re.search(r"AI budget: at most 3 calls and 150 s \(this script\); used 1 call in \d+ s", md), md
assert "live (prod): 1 settled now" in md and "P&L +0.31" in md, "account lines stay in the report's facts"
url, headers, body = sent[-1]
assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer " + KEY and headers["User-Agent"] == "tradebot-paper-research/1.0"
bodytxt = json.dumps(body)
for bad in ("owner@example.com", "ghp_ABCDEF", KEY, "live (", "SETTLED ", "P&L", "$", "LEARNING", "-6.91", "-1.10", "net -"):
    assert bad not in bodytxt, bad
assert "0.083" in bodytxt and body["model"] == "meta/llama-3.1-8b-instruct"   # the picker skipped the embedding model
md = run_ai("All clear. 17 trades settled and the bot made $12.40.")   # numbers the facts do not have
assert "Wording: deterministic (the AI text had numbers not in the facts: 17, 12.40)" in md and "made $12.40" not in md, md
md = run_ai("All clear. The clear margin was -0.0160 per market day.")   # a sign flip (the facts say +0.0160)
assert "numbers not in the facts: -0.0160" in md, md
assert P.unknown_numbers("+0.0160 and 0.0160", "Brier +0.0160") == [] and P.unknown_numbers("-0.31", "P&L +0.31") == ["-0.31"]
md = run_ai("All clear. The gate look stored on 2026-11-18 did not pass.")   # dates in the facts allow nothing
assert "numbers not in the facts: 2026" in md, md
assert P.unknown_numbers("27", "started 2026-11-27T14:51:00, exit 27, KXRAIN-26NOV27-NYC, v27") == ["27"]
assert P.unknown_numbers("Brier 0.0830 on 210 markets, 1,200 days", "Brier=0.083 210 1200") == []
assert P.unknown_numbers("5 trades", "fee 0.05") == ["5"], "parts of a number do not count"
md = run_ai("Nothing needs attention; the stored gate look did not pass and the data is current.")   # no numbers at all
assert "Wording: AI" in md and "Nothing needs attention; the stored" in md, md
# with problems: "0 problems", or a summary that leaves a problem out, is rejected; the problem list always comes first
KILLED = SETTLE.replace("SHADOW v3 rain", "KILL SWITCH ON (C:\\t\\KILL): settling only records results (it never trades); scans stay halted until run unkill.\nSHADOW v3 rain")
pk = logfile("ai_kill", KILLED.format(a=L(at(14, 51)), b=L(at(14, 58))))
md = run_ai("0 problems today. 2 trades settled.", pk)
assert "Wording: deterministic (the AI text called it clear" in md, md
md = run_ai("2 trades settled and the Brier was 0.083.", pk)
assert "Wording: deterministic (the AI text left out a problem: KILL SWITCH" in md, md
md = run_ai("The kill switch is on, so scans are halted. 2 trades settled.", pk)
assert "Wording: AI" in md and md.index("## Problems") < md.index("- KILL SWITCH ON") < md.index("## Summary") < md.index("The kill switch is on"), md
# an API failure: the plain text, and the reason (never the key)
B.http_post = lambda url, headers, body, timeout: (500, {}, "server error")
md = run_ai("unused")
assert "Wording: deterministic (NVIDIA API" in md and "HTTP 500" in md and KEY not in md, md
B.http_post = fake_post
# the plain report is written first, and a slow model cannot hold the job: a thread with a join timeout
pslow = logfile("slow", SETTLE.format(a=L(at(14, 51)), b=L(at(14, 58))))
seen_first = []
release = threading.Event()
class Slow(object):
    calls = 0
    def ask(self, *a):
        seen_first.append(os.path.exists(os.path.join(OUT, "slow", "logs", "report_latest.md")))
        release.wait(30)
        raise RuntimeError("late")
t0 = time.time()
path, line = P.report("settle", log=pslow, key_loader=lambda: (KEY, K.OK), ai_factory=lambda k: Slow(), popen=fake_popen,
                      now=now, ai_seconds=1)
release.set()
md = open(path, encoding="utf-8").read()
assert time.time() - t0 < 30 and seen_first == [True] and "Wording: deterministic (the AI took longer than 1 s)" in md, md

# ---- the key file: DPAPI (fake), outside the project folder, permissions for this user only, never in output ----
class FakeDPAPI(object):
    def protect(self, b): return b"FAKEDPAPI" + bytes(x ^ 0x5A for x in b)
    def unprotect(self, b):
        if not b.startswith(b"FAKEDPAPI"): raise OSError("bad blob")
        return bytes(x ^ 0x5A for x in b[9:])
fd = FakeDPAPI()
assert K.FLAGS & K.CRYPTPROTECT_LOCAL_MACHINE and K.FLAGS & K.CRYPTPROTECT_UI_FORBIDDEN
home = os.path.join(OUT, "home", ".tradebot")
kp = os.path.join(home, "nvidia.key")
ok, msg = K.store(KEY, dpapi=fd, path=os.path.join(WORK, "logs", "nvidia.key"))
assert not ok and "inside the project folder" in msg and not os.path.exists(os.path.join(WORK, "logs", "nvidia.key"))
if os.name != "nt":
    link = os.path.join(OUT, "into_work")   # a link into the project folder is refused too (realpath)
    if not os.path.exists(link):
        os.symlink(WORK, link)
    assert not K.store(KEY, dpapi=fd, path=os.path.join(link, "logs", "nvidia.key"))[0]
    assert K.store(KEY, path=kp) == (False, "Keeping the key on this PC needs Windows (DPAPI).") and not os.path.exists(kp)
    assert K.load_status(path=kp) == (None, K.MISSING) and not K.supported()
ok, msg = K.store(KEY, dpapi=fd, path=kp)   # POSIX permissions here: 0600, checked
assert ok and KEY not in msg and os.path.exists(kp) and not [f for f in os.listdir(home) if f.endswith(".tmp")]
raw = open(kp, "rb").read()
assert KEY.encode() not in raw and raw.startswith(b"FAKEDPAPI")
assert K.load_status(dpapi=fd, path=kp) == (KEY, K.OK) and K.load(dpapi=fd, path=kp) == KEY
if os.name != "nt":
    os.chmod(kp, 0o644)
    assert K.load_status(dpapi=fd, path=kp) == (None, K.PERMISSION)
    os.chmod(kp, 0o600)
class Broken(object):
    def unprotect(self, b): raise OSError("DPAPI unprotect failed (Windows error 13)")
assert K.load_status(dpapi=Broken(), path=kp) == (None, K.DECRYPT)
assert K.load_status(dpapi=fd, path=kp + ".none") == (None, K.MISSING)
deny = (lambda p: (False, "BUILTIN\\Users"), lambda p: (False, "x"))
ok, msg = K.store(KEY, dpapi=fd, path=kp + "3", acl=deny)
assert not ok and "permissions could not be limited" in msg and not os.path.exists(kp + "3") and KEY not in msg
assert K.load_status(dpapi=fd, path=kp, acl=deny) == (None, K.PERMISSION)
class Same(object):
    def protect(self, b): return b
assert K.store(KEY, dpapi=Same(), path=kp + "2")[0] is False and not os.path.exists(kp + "2"), "an unencrypted result is refused"
# icacls: a fixed argv, and the check reads back only this user (SYSTEM tolerated), nothing inherited
class Run(object):
    def __init__(self, outputs): self.outputs, self.argv = list(outputs), []
    def __call__(self, argv, **k):
        self.argv.append(argv); rc, out = self.outputs.pop(0)
        return type("R", (), {"returncode": rc, "stdout": out, "stderr": ""})()
F_ = r"C:\Users\me\.tradebot\nvidia.key"
good = F_ + " DESK\\me:(F)\n                                NT AUTHORITY\\SYSTEM:(F)\n\nSuccessfully processed 1 files; Failed processing 0 files\n"
r = Run([(0, "processed"), (0, good)])
assert K.win_restrict(F_, run=r, user="DESK\\me") == (True, "permissions: only your account")
assert r.argv[0] == ["icacls", F_, "/inheritance:r", "/grant:r", "DESK\\me:(F)"] and r.argv[1] == ["icacls", F_]
wide = F_ + " DESK\\me:(F)\n    BUILTIN\\Users:(RX)\n\nSuccessfully processed 1 files; Failed processing 0 files\n"
assert not K.win_check(F_, run=Run([(0, wide)]), user="DESK\\me")[0]
inh = F_ + " DESK\\me:(I)(F)\n\nSuccessfully processed 1 files\n"
assert not K.win_check(F_, run=Run([(0, inh)]), user="DESK\\me")[0]
assert not K.win_check(F_, run=Run([(0, F_ + " DESK\\other:(F)\n")]), user="DESK\\me")[0]
assert not K.win_restrict(F_, run=Run([(5, "Access is denied.")]), user="DESK\\me")[0]
# a report with the key: it goes only in the request header
sent[:] = []
answer["text"] = "All clear. 2 trades settled."
p = logfile("keyrun", SETTLE.format(a=L(at(14, 51)), b=L(at(14, 58))))
path, line = P.report("settle", log=p, key_loader=lambda: K.load_status(dpapi=fd, path=kp), ai_factory=fac, popen=fake_popen, now=now)
assert sent and sent[-1][1]["Authorization"] == "Bearer " + KEY and KEY not in line
for root_, dirs, files in os.walk(os.path.join(OUT, "keyrun")):
    for f in files:
        assert KEY.encode() not in open(os.path.join(root_, f), "rb").read(), f
r = subprocess.run([sys.executable, os.path.join(WORK, "ops", "pc_report.py"), "settle", "--log", p], capture_output=True, text=True)
assert r.returncode == 0 and "report written" in r.stdout and KEY not in r.stdout + r.stderr, r.stdout + r.stderr
assert subprocess.run([sys.executable, os.path.join(WORK, "ops", "pc_report.py"), "bogus"], capture_output=True, text=True).returncode == 2
ok, msg = K.remove(kp)
assert ok and not os.path.exists(kp) and K.remove(kp)[0]
skip = {".git", "research", "graphify-out", "backups", "node_modules", "__pycache__", "trial"}
for root_, dirs, files in os.walk(WORK):
    dirs[:] = [d for d in dirs if d not in skip]
    for f in files:
        fp = os.path.join(root_, f)
        try:
            if os.path.isfile(fp) and os.path.getsize(fp) < 5 * 1024 * 1024:
                assert KEY.encode() not in open(fp, "rb").read(), fp
        except OSError:
            pass

# ---- the toast: never waits, text only in the environment, failures ignored ----
calls[:] = []
class NoWait(object):
    def __init__(self, *a, **k): calls.append((a, k))
    def wait(self, *a): raise AssertionError("the toast must not be waited for")
assert P.toast("Title <x>", "Body; $(rm -rf)", popen=NoWait)
args, kw = calls[-1]
cmd = " ".join(args[0])
assert "Windows.UI.Notifications" in cmd and "Body" not in cmd and "Title" not in cmd
assert kw["env"]["TB_TOAST_TITLE"] == "Title <x>" and kw["env"]["TB_TOAST_BODY"].startswith("Body")
assert kw["stdout"] == subprocess.DEVNULL and kw["stdin"] == subprocess.DEVNULL
def boom(*a, **k): raise OSError("no powershell")
assert P.toast("t", "b", popen=boom) is False
if os.name != "nt":
    assert P.toast("t", "b") is False   # off Windows: nothing started

# ---- jobs.py: step markers; the report step never changes the exit code, never raises ----
import jobs as JB
JB.LOG = os.path.join(OUT, "jobs", "logs", "tasks.log")
import joblock
joblock.LOCK = os.path.join(OUT, "jobs", "logs", "job.lock"); joblock.OWNER = os.path.join(OUT, "jobs", "logs", "job.owner")
JB._job[0] = "evening"
assert JB.step([sys.executable, "-c", "print('52 markets in shadow log, 1 paper trades logged')"], wait=5) == 0
assert JB.step([sys.executable, "-c", "import sys; sys.exit(4)"], wait=5) == 4
lg = open(JB.LOG, encoding="utf-8").read()
assert re.search(r"----- evening step: \S+ -c print\(.*\)\r?\n52 markets in shadow log.*\r?\n----- evening step end \(exit 0\)", lg), lg
assert "----- evening step end (exit 4)" in lg
def r_timeout(*a, **k): raise subprocess.TimeoutExpired(a[0], 240)
def r_crash(*a, **k): raise RuntimeError("boom")
class R(object):
    def __init__(self, rc, out="", err=""): self.returncode, self.stdout, self.stderr = rc, out, err
JB.pc_report("settle", runner=r_timeout)
JB.pc_report("settle", runner=r_crash)
JB.pc_report("settle", runner=lambda *a, **k: R(1, "", "Traceback\nValueError: x"))
seen = []
JB.pc_report("evening", runner=lambda *a, **k: seen.append((a, k)) or R(0, "Evening run report written (deterministic; all clear)\n"))
lg = open(JB.LOG, encoding="utf-8").read()
assert lg.count("PC REPORT: not written") == 3 and "TimeoutExpired" in lg and "ValueError: x" in lg and "PC REPORT: Evening run report written" in lg
a, k = seen[-1]
assert a[0][1].endswith(os.path.join("ops", "pc_report.py")) and a[0][2] == "evening" and k["timeout"] == JB.REPORT_TIMEOUT_S <= 300
real = JB.pc_report
for rc in (0, 1, 7):
    JB.JOBS["settle"] = lambda rc=rc: rc
    JB.pc_report = lambda job: (_ for _ in ()).throw(RuntimeError("report crashed"))
    assert JB.main(["settle"]) == rc and JB._job[0] == "settle"
    JB.pc_report = lambda job, runner=r_timeout: real(job, runner=runner)
    assert JB.main(["settle"]) == rc
JB.pc_report = real
JB._deadline[0] = None
JB.JOBS["evening"] = lambda: 3
assert JB.main(["evening"]) == 3   # the real script, on this test's log
assert os.path.exists(os.path.join(OUT, "jobs", "logs", "report_latest.md"))
lg = open(JB.LOG, encoding="utf-8").read()
assert re.search(r"evening done \(exit 3\)\r?\nPC REPORT: Evening run report written", lg), lg[-600:]
assert "finished with exit 3" in open(os.path.join(OUT, "jobs", "logs", "report_latest.md"), encoding="utf-8").read()
import freshness as FR
assert FR.task_runs(JB.LOG)["evening"]["exit"] == 3   # the PC REPORT and step lines do not confuse the monitor
JB._deadline[0] = None
got = []
JB.late_night(report=got.append, clock=lambda: at(23, 20))
JB.late_night(report=got.append, clock=lambda: at(0, 20, 28))
JB.late_night(report=got.append, clock=lambda: at(15, 20))
JB.late_night(report=got.append, clock=lambda: at(1, 20, 28))
assert got == ["latenight", "latenight"]
JB.late_night(report=r_crash, clock=lambda: at(23, 20))
order = []
assert JB.hourly(run=lambda a, **k: order.append(a[1]) or 4, net=lambda k: True, settings=lambda: order.append("s"),
                 late=lambda: order.append("late")) == 4 and order == ["late", "s", "hourly"]

# ---- the dashboard panel: escaped, read only from the configured file ----
import dashboard as D
evil = os.path.join(OUT, "evil.md")
with open(evil, "w", encoding="utf-8") as f:
    f.write("# Tradebot PC report: x\n\nStatus: PROBLEMS: 1\nWording: AI <b>bold</b>\n\n## Problems\n\n- <svg onload=alert(3)>\n\n## Summary\n\n<script>alert(1)</script> & <img src=x onerror=alert(2)>\n\n## Facts from logs\\tasks.log\n\nJob: <iframe>\n")
h = D.pc_report_section(evil)
assert "<script>" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "<img" not in h and "<iframe>" not in h and "<svg" not in h
assert "&lt;b&gt;bold" in h and 'class="note neg"' in h and "<details>" in h and "<b>Problems</b>" in h
assert D.pc_report_path() == "" and "No PC report yet" in D.pc_report_section(), "the environment variable keeps tests off the real logs"
assert "No PC report yet" in D.pc_report_section(os.path.join(OUT, "missing.md"))
D.PC_REPORT_PATH = evil
assert D.pc_report_path() == evil and "alert(1)" in D.pc_report_section()
D.PC_REPORT_PATH = None
del os.environ["TRADEBOT_PC_REPORT"]
assert D.pc_report_path() == os.path.join(os.path.dirname(os.path.abspath(D.DB)), "logs", "report_latest.md")
os.environ["TRADEBOT_PC_REPORT"] = ""
D._build_page_core = lambda d, live=False: "<html><head><style>a</style></head><body x><header class=top>h</header><section>r</section></body></html>"
page = D.build_page({}, False)
assert "</header><div class=panel id=pcreport" in page and page.count("class=panel id=pcreport ") == 1
dsrc = open(os.path.join(WORK, "dashboard.py"), encoding="utf-8").read()
blk = dsrc[dsrc.index("def pc_report_section"):dsrc.index("_build_page_core=build_page")]
assert "sqlite" not in blk and "urlopen" not in blk and "e(" in blk
print("pc_report tests passed")
