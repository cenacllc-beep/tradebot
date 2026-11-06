"""research/plan8.py (PLAN8): Kalshi's price with the airport forecast mixed in, fitted once on past data and judged on
new market days. Fake databases with shadow.py's real v4_obs schema; no network (sockets are blocked).
Checks:
- the pins: every PLAN7 function and constant PLAN8 reuses still has the source hash it was frozen with; a changed one
  stops the fit and the looks until an amendment records it; the forecast's code identity is stored at the fit and
  checked at each look;
- the fit: reads past markets like research/PLAN.md's holdout (spread, forecast present), the archive and live formulas
  agree, a planted mix is recovered, it is frozen and never refitted, a lost local copy is restored from the off-folder
  copy, and a fit that cannot be trusted (too few rows, a weight not positive) stops the test;
- the forward filter: the first forward day, the window, the day start, the forecast, the spread, the backstop;
- the looks: early looks refused, results pending refused, the final look only after a futility look that said
  continue, each look once, an early end and the backstop read "not confirmed", a planted gain is confirmed with its
  share attributed, and none is found in the null case;
- status prints counts only; auto never fits, never scores and never fails; paper.db never changes.
python test_plan8.py WORK OUT"""
import os, sys, shutil, json, math, random, hashlib, io, contextlib, socket, sqlite3
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "unused.db")
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))


def _no_net(*a, **k):
    raise AssertionError("network used in a test")


socket.socket.connect = _no_net
socket.create_connection = _no_net
import plan7 as P7, plan8 as P8   # noqa: E402
rng = random.Random(8)


def scenario(name):
    """A fresh result folder and off-folder backup per scenario."""
    d = os.path.join(OUT, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "res"))
    os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
    P8.MODEL = os.path.join(d, "res", "plan8_model.json"); P8.RESULTS = os.path.join(d, "res")
    P8.AMEND = os.path.join(d, "res", "plan8_amendments.json")
    return d


def quiet(f, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


def sig(z):
    return 1 / (1 + math.exp(-z))


def world(n_days, per_day, first, informative=True, seed=1):
    """Markets with a latent chance z: the price m sees z through heavy noise, the forecast s through light noise
    (informative) or not at all; the outcome follows z (informative) or the price itself (null)."""
    r = random.Random(seed)
    out = []
    for i in range(n_days):
        d = first + timedelta(days=i)
        shared = r.gauss(0, 0.7)   # cities on one day share weather
        for j in range(per_day):
            z = -0.6 + shared + r.gauss(0, 1.3)
            m = sig(z + r.gauss(0, 1.4))
            s = sig(z + r.gauss(0, 0.4)) if informative else sig(r.gauss(-0.6, 1.5))
            y = 1.0 if r.random() < (sig(z) if informative else m) else 0.0
            out.append(("KXRAIN-%s-C%02d" % (d.strftime("%y%b%d").upper(), j), d, m, s, y))
    return out


# 0. the pins hold today; a changed PLAN7 function or forecast function is caught, and an amendment accepts it
assert P8.identity_problems(None) == [], P8.identity_problems(None)
assert set(P8.PINNED_PLAN7) == {"research/plan7.py:%s" % n for n in P8.REUSED} | {"research/plan7.py:constants"}
assert all(P8.PINNED_PLAN7.values()) and P8.FORWARD_FIRST == date(2026, 11, 7) and P8.BONF == 0.025 / 3
alt = os.path.join(OUT, "alt_root")
for sub in ("research", os.path.join("research", "results")):
    os.makedirs(os.path.join(alt, sub), exist_ok=True)
for f in ("stationfc.py", "shadow.py", os.path.join("research", "results", "rain_model.json")):
    shutil.copy(os.path.join(WORK, f), os.path.join(alt, f))
src = open(os.path.join(WORK, "research", "plan7.py"), encoding="utf-8").read()
open(os.path.join(alt, "research", "plan7.py"), "w", encoding="utf-8", newline="\r\n").write(src)   # CRLF: same hashes
assert P8.identity_problems(None, alt) == []
open(os.path.join(alt, "research", "plan7.py"), "w", encoding="utf-8").write(
    src.replace('    return max(2.0, T975.get(days - 1, 2.0))', '    return max(1.96, T975.get(days - 1, 2.0))'))
assert P8.identity_problems(None, alt) == ["research/plan7.py:tcrit"]
new = P8.plan7_identity(alt)["research/plan7.py:tcrit"]
am = os.path.join(alt, "am.json")
json.dump(dict(amendments=[dict(name="research/plan7.py:tcrit", sha256=new, reason="test", recorded="2026-11-06")]), open(am, "w"))
assert P8.identity_problems(None, alt, am) == []
open(os.path.join(alt, "research", "plan7.py"), "w", encoding="utf-8").write(src)
assert P8.source_hash(os.path.join(alt, "research", "plan7.py"), "no_such_function") is None
assert P8.source_hash(os.path.join(alt, "missing.py"), "tcrit") is None
code = open(os.path.join(WORK, "research", "plan8.py"), encoding="utf-8").read()
for bad in ("import requests", "import core", "import strategy", "import live", "import kalshi", "urlopen", "requests.get"):
    assert bad not in code, bad   # no network and no bot module (stationfc is imported by the fit only)

# 1. fit_rows reads past markets like research/PLAN.md's holdout
d1 = scenario("fit_rows")
coef = json.load(open(os.path.join(WORK, "research", "results", "rain_model.json")))["coef"]
runs, lines = {}, []
for i in range(6):
    day = date(2026, 7, 15) + timedelta(days=i)
    nx = day + timedelta(days=1)
    for st in ("KATL", "KBOS"):
        runs[(st, day - timedelta(days=1))] = {"%s 12:00" % day: (20.0 + i, 1.0), "%s 18:00" % day: (40.0, 3.0),
                                               "%s 00:00" % nx: (10.0, 0.0), "%s 06:00" % nx: (5.0 + i, 0.0)}
    lines.append(dict(ticker="KXRAIN-26JUL%02d-ATL" % (15 + i), day=str(day), station="KATL", result="yes", scan_bid=0.40, scan_ask=0.44))
    lines.append(dict(ticker="KXRAIN-26JUL%02d-BOS" % (15 + i), day=str(day), station="KBOS", result="no", scan_bid=0.20, scan_ask=0.30))  # spread 10c
lines.append(dict(ticker="KXRAIN-26JUL30-ATL", day="2026-07-30", station="KATL", result="yes", scan_bid=0.4, scan_ask=0.42))   # no forecast run
lines.append(dict(ticker="KXRAIN-26JUL15-MIA", day="2026-07-15", station="KMIA", result=None, scan_bid=0.4, scan_ask=0.42))   # unsettled
p = os.path.join(d1, "k.jsonl")
open(p, "w").write("\n".join(json.dumps(x) for x in lines) + "\n\n")
rows, dis = P8.fit_rows(p, runs, coef)
assert len(rows) == 6 and dis == 0 and all(t.endswith("-ATL") and abs(m - 0.42) < 1e-12 and y == 1.0 for t, _, m, _, y in rows), rows
import stationfc
f0 = stationfc.features(runs[("KATL", date(2026, 7, 14))], date(2026, 7, 15))
assert abs(rows[0][3] - stationfc.predict(coef, f0)) < 1e-15

# 2. the fit: a planted mix is recovered, frozen, never refitted, restored from the off-folder copy
def FIT(**k):
    """The fit on synthetic rows, before the first forward window, without the holdout's exact counts."""
    k.setdefault("now", 1.0e9)
    k.setdefault("expect", None)
    return quiet(P8.fit, **k)


d2 = scenario("fit")
past = world(80, 25, date(2026, 7, 15), seed=2)
model, msg = FIT(rows=past)[0]
assert model and msg.startswith("fitted and frozen"), msg
assert model["b_m"] > 0 and model["b_s"] > model["b_m"] and model["c"] > 0, model   # the forecast sees more than the price
assert model["markets"] == 2000 and model["days"] == 80 and model["formula_disagreements"] == 0
assert set(model["identity"]) == ({"%s:%s" % x for x in P8.FORECAST} | {"research/results/rain_model.json:coef"}
                                  | {"file:research/plan8.py", "file:research/PLAN8.md"}) and all(model["identity"].values())
assert model["leave_one_week_out"]["fits"] >= 10 and len(model["se_clustered"]["mix"]) == 3
bi = model["brier_in_sample"]
assert bi["mix"] < bi["control"] <= bi["price"] + 1e-9, bi
saved = os.path.join(d2, "off", "plan8", "results", "plan8_model.json")
assert json.load(open(saved)) == json.load(open(P8.MODEL))
again, msg = FIT(rows=world(80, 25, date(2026, 7, 15), seed=99))[0]
assert msg == "already fitted (frozen; never refitted)" and again["b_s"] == model["b_s"]
again, msg = FIT(rows=past, now=P8.first_window() + 3600)[0]   # once frozen, a late call still just reads it
assert again["b_s"] == model["b_s"] and msg.startswith("already fitted")
os.remove(P8.MODEL)
again, out = FIT(rows=world(80, 25, date(2026, 7, 15), seed=99))
assert again[0]["b_s"] == model["b_s"] and "restored" in out
open(P8.MODEL, "w").write('{"a": 1, "b_m": ')   # a damaged local copy: moved aside, never deleted, and restored
r, out = quiet(P8.main, ["auto", "--db", os.path.join(OUT, "none.db")])
assert r == 0 and "was damaged (kept as" in out and P8.load_model()["b_s"] == model["b_s"], out
assert any(f.startswith("plan8_model.json.damaged-") for f in os.listdir(P8.RESULTS))
os.remove(saved)   # a missing off-folder copy is made again from the good local one
assert "made it from this folder's copy" in P8.ensure_model() and json.load(open(saved))["b_s"] == model["b_s"]
open(saved, "w").write(json.dumps(dict(other=1)))   # an existing off-folder copy is never replaced
assert P8.ensure_model() is None and json.load(open(saved)) == dict(other=1)
d2b = scenario("fit_offsite_kept")
os.makedirs(os.path.join(d2b, "off", "plan8", "results"))
open(os.path.join(d2b, "off", "plan8", "results", "plan8_model.json"), "w").write(json.dumps(dict(old=1)))
m2, msg = FIT(rows=past)[0]
assert m2.get("old") == 1 and msg.startswith("already fitted"), msg   # the off-folder copy was restored, not refitted
# fixable problems save nothing
d3 = scenario("fit_refusals")
m3, msg = FIT(rows=past, expect=P8.HOLDOUT)[0]   # not research/PLAN.md's holdout (a missing data folder looks like this)
assert m3 is None and "not research/PLAN.md's holdout: 2000 markets on 80 days" in msg and msg.endswith("nothing saved")
m3, msg = FIT(rows=[], expect=P8.HOLDOUT)[0]
assert m3 is None and "0 markets on 0 days" in msg
m3, msg = FIT(rows=past, disagree=1, expect=(2000, 80))[0]
assert m3 is None and "1 formula disagreements" in msg
assert FIT(rows=past, expect=(2000, 80))[0][1].startswith("fitted and frozen")   # the exact counts pass
d3b = scenario("fit_small")
m3, msg = FIT(rows=past[:500])[0]
assert m3 is None and "too few markets or days" in msg and msg.endswith("nothing saved")
m3, msg = FIT(rows=past, now=P8.first_window())[0]   # the first forward window has opened: too late
assert m3 is None and msg.startswith("too late: the first forward window (2026-11-07, 00:50 UTC)")
assert P8.first_window() == datetime(2026, 11, 7, 0, 50, tzinfo=timezone.utc).timestamp()
assert not os.path.exists(P8.MODEL) and not os.path.exists(os.path.join(d3b, "off", "plan8", "results", "plan8_model.json"))
# a fit that cannot be trusted is frozen as failed and stops the test
d4 = scenario("fit_negative")
anti = [(t, d, m, 1 - s, y) for t, d, m, s, y in past]   # a forecast that points the wrong way
m4, msg = FIT(rows=anti)[0]
assert m4 is None and "not positive" in msg, msg
assert "fit failed earlier" in FIT(rows=past)[0][1] and P8.load_model() is None
d5 = scenario("fit_pins")   # a changed PLAN7 function stops the fit
real = P8.PINNED_PLAN7
P8.PINNED_PLAN7 = dict(real, **{"research/plan7.py:margin": "0" * 64})
m5, msg = FIT(rows=past)[0]
assert m5 is None and "research/plan7.py:margin" in msg and not os.path.exists(P8.MODEL)
P8.PINNED_PLAN7 = real


# 3. the forward filter
def paper_db(path, rows, extra=(), settled=None):
    """settled: [(ticker, result, recorded_ts)] for paper.db's market_results, or None for no such table."""
    c = sqlite3.connect(path)
    c.execute("create table v4_obs(ticker text primary key,ts real,station text,run text,R real,q real,fc real,mid real,"
              "bid real,ask real,result text,start_ts real,paper_done integer default 0)")
    if settled is not None:
        c.execute("create table market_results(ticker text primary key,result text,recorded_ts real)")
        c.executemany("insert into market_results values(?,?,?)", settled)
    for t, d, m, s, y in rows:
        mid0 = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
        h = max(0.005, min(0.03, m * 0.05))
        bid, ask = round(max(0.0, m - h), 4), round(min(1.0, m + h), 4)
        c.execute("insert into v4_obs(ticker,ts,station,run,R,q,fc,mid,bid,ask,result,start_ts) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (t, mid0 + 3600, "KXXX", "run", s, 0.0, s, (bid + ask) / 2, bid, ask,
                   None if y is None else ("yes" if y else "no"), mid0 + 5 * 3600))
    for x in extra:
        c.execute("insert into v4_obs(ticker,ts,fc,bid,ask,result,start_ts) values(?,?,?,?,?,?,?)", x)
    c.commit(); c.close()
    return path


P8.MODEL = os.path.join(d4, "res", "plan8_model.json")   # the failed fit of scenario fit_negative
st = P8.status(P7.connect_ro(paper_db(os.path.join(d4, "p.db"), [])), None)
assert st.startswith("PLAN8 (research, not in gate): the fit failed, so the test does not run: a weight is not positive"), st
d6 = scenario("forward")
F = P8.FORWARD_FIRST
md = lambda d: datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()   # noqa: E731
day = date(2026, 11, 8)
tk = lambda d, s: "KXRAIN-%s-%s" % (d.strftime("%y%b%d").upper(), s)   # noqa: E731
extra = [(tk(date(2026, 11, 6), "EARLY"), md(date(2026, 11, 6)) + 3600, 0.3, 0.2, 0.22, "yes", md(date(2026, 11, 6)) + 5 * 3600),
         (tk(day, "LATE"), md(day) + 5 * 3600 + 60, 0.3, 0.2, 0.22, "yes", md(day) + 6 * 3600),        # after 05:00 UTC
         (tk(day, "PREV"), md(day) - 3600, 0.3, 0.2, 0.22, "yes", md(day) + 5 * 3600),                 # 11 PM UTC: before 00:50
         (tk(day, "STARTED"), md(day) + 3600, 0.3, 0.2, 0.22, "yes", md(day) + 1800),                  # logged after its day start
         (tk(day, "LATER2"), md(day) + 2 * 3600, 0.3, 0.2, 0.22, "yes", md(day) + 5 * 3600),          # 02:00 UTC: late window
         (tk(day, "MRES"), md(day) + 3600, 0.3, 0.2, 0.22, None, md(day) + 5 * 3600),                  # result from market_results
         (tk(day, "NOFC"), md(day) + 3600, None, 0.2, 0.22, "yes", md(day) + 5 * 3600),
         (tk(day, "WIDE"), md(day) + 3600, 0.3, 0.2, 0.27, "yes", md(day) + 5 * 3600),                 # spread 7c
         (tk(day, "NOQUOTE"), md(day) + 3600, 0.3, None, 0.22, "yes", md(day) + 5 * 3600),
         (tk(day, "NOSTART"), md(day) + 3600, 0.3, 0.2, 0.22, "yes", None),
         (tk(date(2027, 7, 1), "LATER"), md(date(2027, 7, 1)) + 3600, 0.3, 0.2, 0.22, "yes", md(date(2027, 7, 1)) + 5 * 3600),
         (tk(day, "OK"), md(day) + 50 * 60, 0.3, 0.2, 0.26, None, md(day) + 5 * 3600),                 # 00:50 exactly, 6c: counts
         ("KXRAIN-BADDATE-X", md(day) + 3600, 0.3, 0.2, 0.22, "yes", md(day) + 5 * 3600)]
db6 = paper_db(os.path.join(d6, "paper.db"), [], extra, settled=[(tk(day, "MRES"), "no", md(day) + 86400)])
c = P7.connect_ro(db6)
ex = {}
fr = P8.forward_rows(c, ex)
assert sorted(fr) == [tk(day, "MRES"), tk(day, "OK")] and fr[tk(day, "OK")]["result"] is None, fr
assert fr[tk(day, "MRES")]["result"] == "no" and abs(fr[tk(day, "OK")]["m"] - 0.23) < 1e-12
assert ex == dict(outside_window=2, late_window=1, after_day_start=1, no_forecast=1, spread=2, no_day_start=1,
                  after_backstop=1), ex
assert list(P8.forward_rows(c, late=True)) == [tk(day, "LATER2")]
st = P8.status(c, None)
assert "not fitted yet" in st and "1 forward market days logged, 2 markets (1 with results)" in st and "late_window 1" in st, st
c.close()
assert P8.settle_records(P7.connect_ro(paper_db(os.path.join(d6, "none.db"), []))) == ({}, None)

# 4. the looks: planted gain confirmed, attribution clear, each look once, the order enforced
d7 = scenario("looks_edge")
model = FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))[0][0]
fwd = world(115, 25, F, seed=3)
late7 = [(tk(F + timedelta(days=i), "LATE"), md(F + timedelta(days=i)) + 3 * 3600, 0.3, 0.2, 0.22, "no",
          md(F + timedelta(days=i)) + 5 * 3600) for i in range(5)]
db7 = paper_db(os.path.join(d7, "paper.db"), fwd, late7)
dig = hashlib.sha256(open(db7, "rb").read()).hexdigest()
c = P7.connect_ro(db7)
today = date(2027, 3, 31)
res = P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)
assert res[0] is None and "futility look first" in res[1], res
st = P8.status(c, model)
assert "115 forward market days logged" in st and "Brier" not in st and "mean" not in st, st
r60, msg = P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)
assert msg.startswith("continue"), msg
assert r60["days"] == 60 and r60["accuracy"]["A"]["mean"] < 0 and r60["first_day"] == str(F)
assert P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)[1].startswith("look 60 was already taken")
r110, msg = P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)
assert msg.startswith("confirmed on paper") and "own share (against the control): clear" in msg, msg
assert "the HRRR condition (A and B at the three-test line): met" in msg and r110["hrrr_condition"] is True, msg
A, B = r110["accuracy"]["A"], r110["accuracy"]["B"]
assert A["days"] == 110 and A["boot"][1] < 0 and A["t"] < -A["tcrit"] and B["reading"].startswith("the mix was clearly"), (A, B)
assert r110["markets"] == 110 * 25 and r110["last_day"] == str(F + timedelta(days=109))
assert A["clear"] and A["three_test"] and B["clear"] and B["three_test"]
assert r110["accuracy"]["A_late"]["late_markets"] == 5 and r110["refit_descriptive"]["b_s"] > 0
assert r110["accuracy"]["pooled"]["mix"] < r110["accuracy"]["pooled"]["price"]
md110 = open(os.path.join(P8.RESULTS, "plan8_score_110.md"), encoding="utf-8").read()
assert "**Verdict:** confirmed on paper" in md110 and "Accuracy only" in md110 and "A-late (sensitivity, 5 late" in md110
assert "B at the three-test line" in md110 and "refitted on these markets" in md110
assert P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)[1].startswith("look 110 was already taken")
assert P8.score(c, 90, model, today=today, out_dir=P8.RESULTS)[1].startswith("the plan has two looks only")
c.close()
assert hashlib.sha256(open(db7, "rb").read()).hexdigest() == dig, "paper.db changed"

# 5. the null case: the forecast adds nothing, the futility look stops the test and there is no final look
d8 = scenario("looks_null")
model = FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))[0][0]
db8 = paper_db(os.path.join(d8, "paper.db"), world(115, 25, F, informative=False, seed=4))
c = P7.connect_ro(db8)
r60, msg = P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)
assert msg.startswith("stop: no edge demonstrated") and r60["accuracy"]["A"]["mean"] > 0, (msg, r60["accuracy"]["A"])
assert "there is no final look" in P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)[1]
c.close()

# 6. early looks, pending results, the backstop, an early end, changed code
d9 = scenario("looks_rules")
model = FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))[0][0]
rows9 = world(70, 25, F, seed=5)
db9 = paper_db(os.path.join(d9, "paper.db"), rows9[:59 * 25])
c = P7.connect_ro(db9)
assert P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)[1].startswith("early look refused: 59")
c.close()
pend = [(t, d, m, s, None if d == F + timedelta(days=60) else y) for t, d, m, s, y in rows9[:61 * 25]]   # day 61 unresolved
db9b = paper_db(os.path.join(d9, "paper_b.db"), pend)
c = P7.connect_ro(db9b)
assert P8.score(c, 60, model, today=F + timedelta(days=62), out_dir=P8.RESULTS)[1].startswith("the last counted day (2027-01-05) is fewer than 7")
r, msg = P8.score(c, 60, model, today=F + timedelta(days=66), out_dir=P8.RESULTS)
assert msg.startswith("continue") and r["days"] == 60 and not r["left_out_no_result"], msg   # day 61 is not in the set
c.close()
d9c = scenario("looks_pending")
pend2 = [(t, d, m, s, None if (d == F + timedelta(days=55) and t.endswith("C00")) else y) for t, d, m, s, y in rows9[:61 * 25]]
miss = tk(F + timedelta(days=55), "C00")
mark = md(F + timedelta(days=59 + 7))
db9c = paper_db(os.path.join(d9c, "paper.db"), pend2, settled=[("KXRAIN-OTHER-1", "yes", mark - 60)])
c = P7.connect_ro(db9c)
assert "no settle has recorded a result since 2027-01-12" in P8.score(c, 60, model, today=F + timedelta(days=70), out_dir=P8.RESULTS)[1]
c.close()
db9c2 = paper_db(os.path.join(d9c, "paper2.db"), pend2, settled=[("KXRAIN-OTHER-1", "yes", mark + 2 * 86400)])
c = P7.connect_ro(db9c2)
r, msg = P8.score(c, 60, model, today=F + timedelta(days=70), out_dir=P8.RESULTS)   # a settle ran after the mark: left out
assert msg.startswith("continue") and r["left_out_no_result"] == [miss], (msg, r and r["left_out_no_result"])
assert P8.score(c, 110, model, today=F + timedelta(days=80), out_dir=P8.RESULTS)[1].startswith("early look refused: 61")
r, msg = P8.score(c, 110, model, today=P8.BACKSTOP_LOOK, out_dir=P8.RESULTS)
assert msg.startswith("not confirmed: fewer than 110") and r["days"] == 61, msg
c.close()
d9d = scenario("looks_ended")
db9d = paper_db(os.path.join(d9d, "paper.db"), rows9)
c = P7.connect_ro(db9d)
FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))
assert P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)[1].startswith("continue")
r, msg = P8.score(c, 110, model, ended="the PC was retired", today=today, out_dir=P8.RESULTS)
assert msg.startswith("not confirmed: the nightly airport-forecast log ended early (the PC was retired)"), msg
assert r["accuracy"]["B"].get("not_judged") and "B at the three-test line" not in open(
    os.path.join(P8.RESULTS, "plan8_score_110.md"), encoding="utf-8").read()
c.close()
d9e = scenario("looks_code")   # the forecast's code changed after the fit: the look waits for an amendment
db9e = paper_db(os.path.join(d9e, "paper.db"), rows9)
c = P7.connect_ro(db9e)
changed = dict(model, identity=dict(model["identity"], **{"shadow.py:v4_log": "1" * 64}))
r, msg = P8.score(c, 60, changed, today=today, out_dir=P8.RESULTS)
assert r is None and "shadow.py:v4_log" in msg and "amendment" in msg and "CODE CHANGED" in P8.status(c, changed)
cur = P8.forecast_identity()["shadow.py:v4_log"]
json.dump(dict(amendments=[dict(name="shadow.py:v4_log", sha256=cur, reason="test: logging unchanged", recorded="2026-12-01")]),
          open(os.path.join(P8.RESULTS, "plan8_amendments.json"), "w"))
assert P8.score(c, 60, changed, today=today, out_dir=P8.RESULTS)[1].startswith("continue")
c.close()

# 6b. the new look rules: --ended only at the final look, once-only survives a lost local result, the final look's first
# 60 days must be the futility look's markets, the futility look shows A's mean only, and B is not judged when A fails
d11 = scenario("looks_more")
model = FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))[0][0]
mixed = world(60, 25, F, seed=7) + world(55, 25, F + timedelta(days=60), informative=False, seed=8)
db11 = paper_db(os.path.join(d11, "paper.db"), mixed)
c = P7.connect_ro(db11)
assert P8.score(c, 60, model, ended="x", today=today, out_dir=P8.RESULTS)[1] == "--ended applies to the final look only"
r60, msg = P8.score(c, 60, model, today=today, out_dir=P8.RESULTS, db=db11)
assert msg.startswith("continue") and set(r60["accuracy"]) == {"A"} and set(r60["accuracy"]["A"]) == {"mean", "days"}
assert r60["db"] == db11 and len(r60["rows_sha256"]) == 64
md60 = open(os.path.join(P8.RESULTS, "plan8_score_60.md"), encoding="utf-8").read()
assert "the futility rule uses only its sign" in md60 and "B (attribution" not in md60 and "clearly" not in md60
off60 = os.path.join(d11, "off", "plan8", "results", "plan8_score_60.json")
assert os.path.exists(off60) and os.path.exists(off60[:-5] + ".md")
os.rename(os.path.join(P8.RESULTS, "plan8_score_60.json"), os.path.join(d11, "aside.json"))
assert "its off-folder copy" in P8.score(c, 60, model, today=today, out_dir=P8.RESULTS)[1]
os.rename(os.path.join(d11, "aside.json"), os.path.join(P8.RESULTS, "plan8_score_60.json"))
good = json.load(open(os.path.join(P8.RESULTS, "plan8_score_60.json")))
json.dump(dict(good, rows_sha256="0" * 64), open(os.path.join(P8.RESULTS, "plan8_score_60.json"), "w"))
assert "differ from those the futility look used" in P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)[1]
open(os.path.join(P8.RESULTS, "plan8_score_60.json"), "w").write("{damaged")
assert "the futility look's result file is damaged" in P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)[1]
json.dump(good, open(os.path.join(P8.RESULTS, "plan8_score_60.json"), "w"))
r110, msg = P8.score(c, 110, model, today=today, out_dir=P8.RESULTS)
assert msg.startswith("no edge demonstrated") and r110["accuracy"]["B"] == dict(
    not_judged="B is judged only after A passes (plan section 5)"), (msg, r110["accuracy"]["A"])
md = open(os.path.join(P8.RESULTS, "plan8_score_110.md"), encoding="utf-8").read()
assert "B (attribution, the mix vs the price recalibrated alone): not judged" in md and "B at the three-test line" not in md
assert "hrrr_condition" not in r110
c.close()

# 7. auto: restores a lost model, prints the status line, never fits or scores, never fails the job
d10 = scenario("auto")
db10 = paper_db(os.path.join(d10, "paper.db"), world(3, 5, F, seed=6))
r, out = quiet(P8.main, ["auto", "--db", db10])
assert r == 0 and "not fitted yet" in out and not os.path.exists(P8.MODEL), out
FIT(rows=world(80, 25, date(2026, 7, 15), seed=2))
os.remove(P8.MODEL)
r, out = quiet(P8.main, ["auto", "--db", db10])
assert r == 0 and "restored" in out and "fitted (frozen)" in out and "3 forward market days logged" in out, out
assert not any(f.startswith("plan8_score") for f in os.listdir(P8.RESULTS))
r, out = quiet(P8.main, ["auto", "--db", os.path.join(d10, "missing.db")])
assert r == 0 and "PLAN8 status failed" in out, out
r, out = quiet(P8.main, ["status", "--db", db10])
assert r == 0 and out.startswith("PLAN8 (research, not in gate)")
print("PLAN8: all checks passed")
