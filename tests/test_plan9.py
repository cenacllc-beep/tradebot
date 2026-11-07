"""research/plan9.py (PLAN9): v3's hourly chances combined in 6-hour blocks, judged on new market days. Fake databases
with core.py's real obs schema; no network (sockets are blocked).
Checks:
- the pins: every PLAN7 function and constant PLAN9 reuses still has the source hash PLAN8 froze; the identity is stored
  once and a difference stops the looks until an amendment covers it;
- the forecast: chances() accepts exactly 24 numbers from 0 to 100; v3_6h's formula;
- the forward filter: the first forward day, the evening window, a missing forecast, price or hourly chances, the
  backstop, and a result taken from market_results;
- the looks: refused until the first n counted days are ready (all resolved, or 7 days old); each stored once; a planted
  improvement over v3 is confirmed while the price stays better; futility stops a test; the backstop reads "not
  confirmed" with fewer than 110 days;
- status prints counts only; paper.db never changes.
python test_plan9.py WORK OUT"""
import os, sys, shutil, json, random, hashlib, io, contextlib, socket
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "unused.db")
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))


def _no_net(*a, **k):
    raise AssertionError("network used in a test")


socket.socket.connect = _no_net
import core, plan8 as P8, plan9 as P9   # noqa: E402,E401


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# 1. pins and identity
for n, h in P9.PINNED_PLAN7.items():
    assert P8.PINNED_PLAN7["research/plan7.py:" + n] == h, n
ident = P9.identity(WORK)
assert all(ident.values()), ident
assert all(ident["research/plan7.py:" + n] == h for n, h in P9.PINNED_PLAN7.items()), "plan7's reused functions are as pinned"
assert ident["research/plan7.py:constants"] == P9.PINNED_CONSTANTS, "plan7's constants, with its t table, are as pinned"
print("pins: PLAN7's reused functions unchanged since PLAN8's freeze; the identity covers the forecast and the plan: ok")

# 2. the forecast
h = P9.chances(json.dumps([10] * 6 + [20] * 6 + [0] * 6 + [50] * 6))
assert h is not None and abs(P9.v3_6h(h) - (1 - 0.9 * 0.8 * 1.0 * 0.5)) < 1e-12
for bad in ("[1,2]", json.dumps([10] * 23), json.dumps([10] * 23 + [101]), json.dumps([10] * 23 + [-1]), json.dumps([10] * 23 + [True]),
            json.dumps([10] * 23 + [None]), "junk", None, json.dumps({"a": 1})):
    assert P9.chances(bad) is None, bad
assert P9.v3_6h([0.0] * 24) == 0.01 and P9.v3_6h([1.0] + [0.0] * 23) == 0.99, "clipped like v3"
print("forecast: exactly 24 chances from 0 to 100; 1 - product of the four 6-hour maxima, clipped to [0.01, 0.99]: ok")


# 3. fake paper.db
def fresh(name):
    p = os.path.join(OUT, name + ".db")
    if os.path.exists(p):
        os.remove(p)
    os.environ["PAPER_DB"] = p; core.DB = p
    c = core.db()
    c.execute("create table if not exists market_results(ticker text primary key,result text not null,recorded_ts real not null)")
    c.commit()
    return c, p


def scan_ts(d, minute=55):
    """An evening scan at 8:55 PM La Paz the evening before market day d (00:55 UTC on d)."""
    return datetime(d.year, d.month, d.day, 0, minute, tzinfo=timezone.utc).timestamp()


def slices_for(q):
    """Hourly chances (whole percent) whose v3-6h is close to q: the same maximum in every block."""
    b = 1 - (1 - q) ** 0.25
    return json.dumps([int(round(b * 100))] * 24)


def add(c, t, ts, fc, mid, result, slices):
    c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type,slices) values(?,?,?,?,?,?,?,?)",
              (t, "v3", ts, fc, mid, result, "rain", slices))


def tk(d, city):
    return "KXRAIN-%s-%s" % (d.strftime("%y%b%d").upper(), city)


c, p = fresh("filter")
d0 = P9.FORWARD_FIRST
add(c, tk(d0 - timedelta(days=1), "OLD"), scan_ts(d0 - timedelta(days=1)), 0.3, 0.3, "no", slices_for(0.3))   # before the first day
add(c, tk(d0, "OK1"), scan_ts(d0), 0.3, 0.4, "yes", slices_for(0.5))
add(c, tk(d0, "LATE"), scan_ts(d0) + 5 * 3600, 0.3, 0.4, "yes", slices_for(0.5))     # 05:55 UTC: outside the window
add(c, tk(d0, "NOFC"), scan_ts(d0), None, 0.4, "yes", slices_for(0.5))
add(c, tk(d0, "NOMID"), scan_ts(d0), 0.3, None, "yes", slices_for(0.5))
add(c, tk(d0, "NOSL"), scan_ts(d0), 0.3, 0.4, "yes", None)
add(c, tk(d0, "MR"), scan_ts(d0), 0.3, 0.4, None, slices_for(0.5))
add(c, tk(d0 + timedelta(days=1), "LATE2"), scan_ts(d0 + timedelta(days=1)) + 5 * 3600, 0.3, 0.4, "yes", slices_for(0.5))
add(c, tk(date(2027, 7, 1), "AFT"), scan_ts(date(2027, 7, 1)), 0.3, 0.4, "no", slices_for(0.5))
c.execute("insert into market_results values(?,?,?)", (tk(d0, "MR"), "no", 1.0)); c.commit()
ex = {}
rows = P9.forward_rows(c, ex)
assert sorted(r["ticker"].split("-")[2] for r in rows) == ["MR", "OK1"], rows
assert ex == {"outside_window": 2, "no_forecast": 1, "no_price": 1, "no_hourly_chances": 1, "after_backstop": 1}, ex
ex = {}
P9.forward_rows(c, ex, {d0})
assert ex == {"outside_window": 1, "no_forecast": 1, "no_price": 1, "no_hourly_chances": 1}, "exclusions for the look's own days"
assert [r["result"] for r in rows if r["ticker"].endswith("MR")] == ["no"], "a result from market_results"
c.close()
print("forward filter: first day, window, forecast, price, hourly chances, backstop, results from the settle record: ok")


# 4. the looks
DEADLINE = P9.identity_deadline()
BEFORE = DEADLINE - 3600


def scenario(name):
    """A fresh results folder and off-folder copy per scenario."""
    d = os.path.join(OUT, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "res"))
    os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
    return os.path.join(d, "res")


def world(c, first, ndays, rng, better_than_v3=True, cities=24):
    """ndays market days from day index `first`. Truth p; the price is p itself (the best possible); v3-6h is p with
    noise; v3 is biased low (like the real v3), unless better_than_v3 is False, when v3 is p and v3-6h runs wet."""
    for i in range(first, first + ndays):
        d = P9.FORWARD_FIRST + timedelta(days=i)
        for k in range(cities):
            p_true = rng.random()
            y = "yes" if rng.random() < p_true else "no"
            q = min(0.99, max(0.01, p_true + rng.uniform(-0.15, 0.15)))
            fc = p_true * 0.55 if better_than_v3 else p_true
            add(c, tk(d, "C%02d" % k), scan_ts(d), fc, p_true, y, slices_for(q if better_than_v3 else min(0.99, p_true + 0.35)))
    c.commit()


def settle_mark(c, ts):
    """The settle's own record of a result at ts (the evidence that a settle ran)."""
    c.execute("insert or replace into market_results values(?,?,?)", ("KXRAIN-MARK-%d" % int(ts), "no", ts)); c.commit()


res_dir = scenario("looks")
c, p = fresh("looks")
world(c, 0, 59, random.Random(9))
rec, prob = P9.ensure_identity(res_dir, WORK, now=BEFORE)
assert rec and not prob and os.path.exists(P9.offsite_path(os.path.join(res_dir, P9.IDENTITY))), "stored once, copied off the folder"
today = P9.FORWARD_FIRST + timedelta(days=200)
r, msg = P9.look(c, 60, today, res_dir, WORK)
assert r is None and msg == "not due", "59 days: no look"
d60 = P9.FORWARD_FIRST + timedelta(days=59)
for k in range(24):   # day 60: half resolved, half never
    add(c, tk(d60, "C%02d" % k), scan_ts(d60), 0.2, 0.5, "yes" if k < 12 else None, slices_for(0.5))
c.commit()
r, msg = P9.look(c, 60, d60 + timedelta(days=3), res_dir, WORK)
assert r is None and msg == "not due", "the 60th day is not ready yet"
r, msg = P9.look(c, 60, d60 + timedelta(days=8), res_dir, WORK)
assert r is None and msg == "not due", "7 days passed but no settle has run since the mark: still not ready"
_, out = quiet(P9.status, c, d60 + timedelta(days=8), res_dir, WORK)
assert "60 forward market days logged (59 ready)" in out and "Brier" not in out and "mean" not in out and "CODE CHANGED" not in out, out
settle_mark(c, P9.P7.midnight(d60 + timedelta(days=7)) + 3600)
before = hashlib.sha256(open(p, "rb").read()).hexdigest()
r, msg = P9.look(c, 60, d60 + timedelta(days=8), res_dir, WORK)
assert r and msg == "stored" and r["days"] == 60 and r["unresolved_left_out"] == 12, (msg, r and r["days"])
assert hashlib.sha256(open(p, "rb").read()).hexdigest() == before, "plan9 never writes paper.db"
A, B = r["tests"]["A"], r["tests"]["B"]
assert set(A) == set(B) == {"markets", "days", "mean_below_zero", "verdict"}, "the futility look shows only signs and counts"
assert A["verdict"] == "not confirmed (futility)" and not A["mean_below_zero"], A   # the price is the truth: v3-6h is worse
assert B["verdict"] == "continues to the final look" and B["mean_below_zero"], B
md = open(os.path.join(res_dir, "plan9_look60.md")).read()
assert "only its sign is shown" in md and "+/-" not in md, md
r2, msg2 = P9.look(c, 60, d60 + timedelta(days=30), res_dir, WORK)
assert msg2 == "already stored" and r2["stored"] == r["stored"], "stored once"
# a lost local look is restored from the off-folder copy, never recomputed
os.remove(os.path.join(res_dir, "plan9_look60.json"))
r3, msg3 = P9.look(c, 60, d60 + timedelta(days=30), res_dir, WORK)
assert msg3 == "already stored" and r3["stored"] == r["stored"] and os.path.exists(os.path.join(res_dir, "plan9_look60.json"))
# 110 days: B is confirmed, A stays stopped
world(c, 60, 50, random.Random(60))
settle_mark(c, P9.P7.midnight(P9.FORWARD_FIRST + timedelta(days=130)))
r, msg = P9.look(c, 110, P9.FORWARD_FIRST + timedelta(days=130), res_dir, WORK)
assert r and r["days"] == 110, msg
assert r["tests"]["B"]["verdict"] == "confirmed", r["tests"]["B"]
assert r["tests"]["A"]["verdict"] == "not confirmed (stopped at the futility look)", r["tests"]["A"]
assert "the gate's own line, not this plan's verdict" in r["tests"]["B"]["gate_line_reading"]
assert set(r["descriptive"]) == {"calibration_30_80", "logged_0050_0130"} and "v3-6h" in r["descriptive"]["calibration_30_80"]
assert r["markets"] == 110 * 24 - 12, "the futility look's 12 left-out markets stay out of the final look"
c.close()
print("looks: not due until the first n days are ready (with a settle past the 7-day mark); the futility look shows signs only;"
      " stored once and restored from off the folder; B confirmed first, A stopped at futility: ok")

# 5. null case: v3-6h worse than v3 -> both stop at futility; a final look then judges neither
res2 = scenario("null")
c, p = fresh("null")
world(c, 0, 60, random.Random(3), better_than_v3=False)
P9.ensure_identity(res2, WORK, now=BEFORE)
r, _ = P9.look(c, 60, P9.FORWARD_FIRST + timedelta(days=90), res2, WORK)
assert r["tests"]["B"]["verdict"] == "not confirmed (futility)" and r["tests"]["A"]["verdict"] == "not confirmed (futility)", r["tests"]
c.close()
print("null case: no improvement found: ok")

# 6. identity: stored only before the first window; a damaged or changed record stops the looks; an amendment covers a change
res3 = scenario("ident")
c, p = fresh("ident")
world(c, 0, 60, random.Random(4))
rec, prob = P9.ensure_identity(res3, WORK, now=DEADLINE + 1)
assert rec is None and "first forward window has opened" in prob, prob
r, msg = P9.look(c, 60, P9.FORWARD_FIRST + timedelta(days=90), res3, WORK, now=DEADLINE + 1)
assert r is None and "looks stopped" in msg, msg
P9.ensure_identity(res3, WORK, now=BEFORE)
ipath = os.path.join(res3, P9.IDENTITY)
os.remove(ipath)   # lost locally: restored from the off-folder copy even after the deadline
rec, prob = P9.ensure_identity(res3, WORK, now=DEADLINE + 1)
assert rec and not prob and os.path.exists(ipath)
open(ipath, "w").write("{damaged")
rec, prob = P9.ensure_identity(res3, WORK, now=DEADLINE + 1)
assert rec is None and "damaged" in prob, prob
r, msg = P9.look(c, 60, P9.FORWARD_FIRST + timedelta(days=90), res3, WORK)
assert r is None and "damaged" in msg, msg
st = json.load(open(P9.offsite_path(ipath)))
st["file:nws.py"] = "0" * 64
json.dump(st, open(ipath, "w"))
r, msg = P9.look(c, 60, P9.FORWARD_FIRST + timedelta(days=90), res3, WORK)
assert r is None and "looks stopped" in msg and "file:nws.py" in msg, msg
_, out = quiet(P9.status, c, P9.FORWARD_FIRST + timedelta(days=90), res3, WORK)
assert "CODE CHANGED: file:nws.py" in out, out
json.dump({"amendments": [{"name": "file:nws.py", "sha256": ident["file:nws.py"], "approved_by": "user", "why": "test"}]},
          open(os.path.join(res3, P9.AMEND), "w"))
r, msg = P9.look(c, 60, P9.FORWARD_FIRST + timedelta(days=90), res3, WORK)
assert r is not None, msg
open(os.path.join(res3, "plan9_look60.json"), "w").write("{damaged")
_, out = quiet(P9.auto, p, P9.FORWARD_FIRST + timedelta(days=200), res3, WORK)
assert "plan9_look60.json is damaged" in out, out
c.close()
print("identity: stored once before the first window, restored from off the folder, a damaged or changed record stops the"
      " looks until the user's amendment; a damaged look stops them too: ok")

# 7. the backstop: fewer than 110 counted days by 2027-07-07 -> the final look, "not confirmed", once
res4 = scenario("backstop")
c, p = fresh("backstop")
world(c, 0, 30, random.Random(5))
c.close()
P9.ensure_identity(res4, WORK, now=BEFORE)
_, out = quiet(P9.auto, p, P9.BACKSTOP_LOOK, res4, WORK)
got = json.load(open(os.path.join(res4, "plan9_look110.json")))
assert got["backstop"] and got["days"] == 30 and all("fewer than 110" in v["verdict"] for v in got["tests"].values()), got["tests"]
assert "PLAN9 look at 110 days stored" in out, out
_, out = quiet(P9.auto, p, P9.BACKSTOP_LOOK + timedelta(days=1), res4, WORK)
assert "stored" not in out.split("\n", 1)[-1] and "the final look is stored" in out, out
print("backstop: the final look with fewer than 110 days reads not confirmed, once: ok")

# 8. main never fails the settle job, even without paper.db
os.environ["PAPER_DB"] = os.path.join(OUT, "missing.db")
rc, out = quiet(P9.main, ["status"])
assert rc == 0 and "PLAN9:" in out, out
print("PLAN9: all checks passed")
