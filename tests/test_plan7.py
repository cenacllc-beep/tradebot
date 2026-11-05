"""research/plan7.py (PLAN7): the corrected v3 forecast, fitted once and judged on new market days. Fake databases with
the real schema (core.db, the audit ledger's scans and decisions tables). No network: sockets are blocked, and candles
come from a fake fetch.
Checks:
- the pinned rule: every copied value and function still equals its source (config, strategy, gate, shadow, learn);
- read-only: paper.db never changes; the source never writes to it or imports the bot's modules;
- the fit waits (stop date, results, the Nov 13 fallback), recovers a planted lean, records model versions and its
  descriptive checks, and is never refitted; a fit that cannot be trusted stops the test;
- the forward filter: scan start inside the window, MARKET_STARTED, spread, model version, first usable row;
- the candle store: each market once, retried after a network error, "none" after 7 days;
- the looks: an early look refused, the final look only after a futility look that said continue, each look once,
  an early end and the backstop read "not confirmed", a planted edge is confirmed and none is found in the null case.
python test_plan7.py WORK OUT"""
import os, sys, shutil, json, math, random, hashlib, io, contextlib, socket, sqlite3
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "unused.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off")
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))
import core, audit, config, gate, shadow, strategy, learn, plan7 as P
P.MODEL = os.path.join(OUT, "res", "plan7_model.json"); P.CANDLES = os.path.join(OUT, "candles"); P.RESULTS = os.path.join(OUT, "res")
STOP = gate.STOP_DATE
rng = random.Random(5)

# 0. the pinned rule equals its sources today, and the module stays read-only and self-contained
assert (P.BLEND, P.MIN_EDGE, P.MAX_SPREAD) == (config.BLEND, config.MIN_EDGE, config.MAX_SPREAD)
assert P.VETO_MAX_GAP == strategy.VETO_MAX_GAP and P.STRATEGY == strategy.STRATEGY_RAIN and P.FORWARD_FIRST == STOP
assert P.T975 == gate.T975 and all(P.tcrit(n) == gate.tcrit(n) for n in range(1, 140))
for _ in range(300):
    o = [("KXRAIN-26NOV%02d-C%d" % (rng.randint(11, 30), rng.randint(0, 9)), rng.random(), rng.random(), rng.choice(["yes", "no"]))
         for _ in range(rng.randint(0, 60))]
    assert P.margin(o) == gate.margin(o)
for _ in range(2000):
    cs = sorted(({"end_period_ts": 1000 + 60 * k, "price": {"low_dollars": "%.2f" % rng.random(), "high_dollars": "%.2f" % rng.random()},
                  "yes_ask": {"low_dollars": "%.2f" % rng.random()}, "yes_bid": {"high_dollars": rng.choice(["%.2f" % rng.random(), "", None])}}
                 for k in range(rng.randint(0, 8))), key=lambda x: x["end_period_ts"])
    args = (rng.choice(["yes", "no"]), round(rng.random(), 2), rng.random() < 0.5, 1000 + rng.randint(-60, 200), 1000 + rng.randint(0, 600), cs)
    assert P.fill_time(*args) == shadow.fill_time(*args)
for _ in range(20):
    x = [rng.uniform(-1, 1) for _ in range(rng.randint(14, 120))]
    assert tuple(P.boot_interval(P.boot_means(x))) == tuple(shadow._boot(x))
for p in [i / 100 for i in range(101)]:
    assert P.taker_fee(p) == shadow._taker_fee(p)
for df in (5, 59, 109):
    assert abs(P.t_quantile(0.0125, df) - learn.tcrit(0.0125, df)) < 1e-9
assert abs(P.t_quantile(0.0125, 109) - 2.27) < 0.01
from tbcommon import parse as _parse, clock as _clock
for t in ("KXRAIN-26NOV11-NYC", "KXRAIN-27FEB28-SEA", "KXRAIN-BAD-X", None, "", "KXRAIN"):
    assert P.market_day(t) == _parse.market_day(t), t
for ts in (1.7e9, 1.8e9, 1793000000.5, 1793050000.0):
    assert P.bot_date(ts) == _clock.bot_date(ts)
for bad in ("from tbcommon.parse", "clock.bot_date(", "tbcommon import stats"):
    assert bad not in open(os.path.join(WORK, "research", "plan7.py"), encoding="utf-8").read(), bad
src = open(os.path.join(WORK, "research", "plan7.py"), encoding="utf-8").read()
for bad in ("import config", "import gate", "import shadow", "import strategy", "import live", "import core", "insert into",
            "update ", "delete from", "create table", "commit(", "import socket", "subprocess"):
    assert bad not in src, "plan7.py must stay pinned, read-only and self-contained: %s" % bad
print("pinned rule: values, gate statistic, fill rule, bootstrap, fee and t quantile equal their sources: ok")

def tk(d, city): return "KXRAIN-%s-%s" % (d.strftime("%y%b%d").upper(), city)
def at(d, minutes): return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() + 60 * minutes
def start_ts(d): return at(d, 5 * 60)
def market_day(t): return datetime.strptime(t.split("-")[1], "%y%b%d").date()
def fresh(name):
    p = os.path.join(OUT, name); core.DB = p; c = core.db()
    for t in ("scans", "decisions"): c.execute(audit.TABLES[t])
    c.commit(); return p, c
def scan(c, sid, began): c.execute("insert into scans(scan_id,started_ts,kind,code_hash,config,host) values(?,?,'scan','x','{}','nt')", (sid, began))
def decide(c, t, ts, p, bid, ask, reason="INSUFFICIENT_EDGE", sid="s", mv="v3@x", start=None, version="v3", strat=None):
    c.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,strategy_version,model_version,mode,ticker,action,"
              "reason,bid,ask,p_model,day_start_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (os.urandom(8).hex(), sid, ts, strat or P.STRATEGY, version, mv, "paper", t, "abstain", reason, bid, ask, p,
               start if start is not None else start_ts(market_day(t))))
def obs(c, t, fc, mid, result, ts=None):
    c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,?,?,?,?,?,?)",
              (t, "v3", at(market_day(t), 60) if ts is None else ts, fc, mid, result, "rain"))
def h(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
@contextlib.contextmanager
def offline():
    real = socket.socket
    def blocked(*a, **k): raise AssertionError("plan7 tried to open a network connection")
    socket.socket = blocked
    try: yield
    finally: socket.socket = real
def sig(z): return 1 / (1 + math.exp(-z))

CITIES = ["C%02d" % i for i in range(30)]
TEST_DAYS = [date(2026, 10, 14) + timedelta(days=i) for i in range(28)]
A0, B0 = 0.6, 0.8   # the planted lean: v3 says p, the truth is sigmoid(A0 + B0 * logit(p)), so v3 runs low

# 1. the fit
Pdb, c = fresh("paper.db")
for d in TEST_DAYS:
    for city in CITIES:
        p = rng.choice([0.01, 0.02, 0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 0.97])
        y = rng.random() < sig(A0 + B0 * P.logit(P.clip(p)))
        obs(c, tk(d, city), p, 0.5, "yes" if y else "no")
    decide(c, tk(d, CITIES[0]), at(d, 60), 0.3, 0.4, 0.42, mv="v3@x" if d >= TEST_DAYS[10] else "v3@old")
decide(c, tk(TEST_DAYS[5], "X"), at(TEST_DAYS[5], 60), 0.3, 0.4, 0.42, reason="MARKET_STARTED", mv="v3@started")
obs(c, tk(TEST_DAYS[-1], "LATE"), 0.5, 0.5, None)                                  # one test-day market still open
c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values('KXHIGHNY-26OCT20-T60','v3',0,.5,.5,'yes','temp')")
c.execute("insert into obs(ticker,version,ts,fc,mid,result,market_type) values(?,'v2',0,.99,.5,'no','rain')", (tk(TEST_DAYS[3], "OLD"),))
c.commit(); c.close()
with offline():
    c = P.connect_ro(Pdb)
    m, msg = P.fit(c, today=STOP - timedelta(days=1)); assert m is None and "on or after" in msg and not os.path.exists(P.MODEL)
    m, msg = P.fit(c, today=STOP); assert m is None and "1 v3 rain markets" in msg and not os.path.exists(P.MODEL), msg
    c.close()
w = sqlite3.connect(Pdb); w.execute("update obs set result='no' where ticker=?", (tk(TEST_DAYS[-1], "LATE"),)); w.commit(); w.close()
before = h(Pdb)
with offline():
    c = P.connect_ro(Pdb)
    m, msg = P.fit(c, today=STOP, now=1.8e9)
    assert m and "fitted and frozen" in msg and abs(m["a"] - A0) < 0.25 and abs(m["b"] - B0) < 0.25, (m, msg)
    assert m["markets"] == 28 * 30 + 1 and m["days"] == 28 and (m["first_day"], m["last_day"]) == ("2026-10-14", "2026-11-10")
    assert m["model_versions"] == ["v3@old", "v3@x"] and m["left_out"] == [] and m["at_bounds"] > 0
    assert len(m["se_clustered"]) == 2 and m["leave_one_day_out"]["fits"] == 28
    assert set(m["code_sha256"]) == {"weather.py", "nws.py", "strategy.py"} and all(m["code_sha256"].values())
    lo, hi = m["leave_one_day_out"]["b"]; assert lo <= m["b"] <= hi
    saved = json.load(open(P.MODEL)); assert saved["rows_sha256"] == m["rows_sha256"] and saved["a"] == m["a"]
    m2, msg2 = P.fit(c, today=STOP + timedelta(days=30)); assert "never refitted" in msg2 and m2["a"] == m["a"]
    assert P.corrected(0.4, m) > 0.45, "the correction lifts v3's middle range when v3 runs low"
    assert P.corrected(0.0, m) == P.corrected(0.01, m) and 0.01 <= P.corrected(1.0, m) <= 0.99
    c.close()
assert h(Pdb) == before
MODEL = m
P.bot_date = lambda ts: date(2027, 3, 31)   # "today" for the looks below: every forward day's results are in
assert os.path.exists(os.path.join(OUT, "off", "plan7", "results", "plan7_model.json")), "the frozen model is copied off the folder"
print("fit: waits, recovers the planted lean (a=%.2f, b=%.2f), records model versions and checks, frozen: ok" % (m["a"], m["b"]))

# 1b. the Nov 13 fallback, calibrated data, and fits that cannot be trusted
p_, c2 = fresh("late.db")
for d in TEST_DAYS[:10]:
    for city in CITIES[:20]:
        fc = rng.uniform(0.05, 0.95); obs(c2, tk(d, city), fc, 0.5, "yes" if rng.random() < fc else "no")
    decide(c2, tk(d, "C00"), at(d, 60), 0.3, 0.4, 0.42)
obs(c2, tk(TEST_DAYS[9], "VOID"), 0.5, 0.5, None); c2.commit(); c2.close()
mp = os.path.join(OUT, "res", "late.json")
with offline():
    c2 = P.connect_ro(p_)
    r, msg = P.fit(c2, today=P.FIT_LATEST - timedelta(days=1), model_path=mp); assert r is None and "anyway from" in msg
    r, msg = P.fit(c2, today=P.FIT_LATEST, model_path=mp); c2.close()
assert r and r["left_out"] == [tk(TEST_DAYS[9], "VOID")] and "1 left out" in msg and abs(r["b"] - 1) < 0.35, (r, msg)
xs, ys = [], []
for i in range(4000):
    p = rng.uniform(0.02, 0.98); xs.append(P.logit(p)); ys.append(1.0 if rng.random() < p else 0.0)
a, b, _ = P.fit_logistic(xs, ys); assert abs(a) < 0.15 and abs(b - 1) < 0.15, (a, b)
assert P.fit_logistic([-2, -1, 1, 2], [0, 0, 1, 1]) is None, "perfect separation does not converge"
for name, n_days, n_city, versions in (("few.db", 3, 10, True), ("sep.db", 10, 20, True), ("nover.db", 10, 20, False)):
    p_, c2 = fresh(name)
    for d in TEST_DAYS[:n_days]:
        for city in CITIES[:n_city]:
            fc = rng.choice([0.05, 0.95]) if name == "sep.db" else rng.uniform(0.05, 0.95)
            obs(c2, tk(d, city), fc, 0.5, ("yes" if fc > 0.5 else "no") if name == "sep.db" else rng.choice(["yes", "no"]))
        if versions: decide(c2, tk(d, "C00"), at(d, 60), 0.3, 0.4, 0.42)
    c2.commit(); c2.close()
    mp = os.path.join(OUT, "res", name + ".model.json")
    with offline():
        c2 = P.connect_ro(p_); r, msg = P.fit(c2, today=STOP, model_path=mp); c2.close()
    assert r is None and "does not run" in msg and P.load_model(mp) is None and "failed" in json.load(open(mp)), msg
print("fit: the Nov 13 fallback lists what it leaves out; calibrated data gives a=0, b=1; too few markets, separation"
      " or no model version stop the test: ok")

# 2. forward rows: the filter
FWD = [STOP + timedelta(days=i) for i in range(115)]
w = sqlite3.connect(Pdb); d0 = FWD[0]
scan(w, "early", at(d0, 45)); scan(w, "ok", at(d0, 55)); scan(w, "late", at(d0, 295))
decide(w, tk(d0, "WIN"), at(d0, 46), 0.4, 0.40, 0.42, sid="early")      # its scan began 00:45: outside
decide(w, tk(d0, "WIN"), at(d0, 60), 0.5, 0.40, 0.42, sid="ok")         # the row used
decide(w, tk(d0, "WIN"), at(d0, 70), 0.9, 0.40, 0.42, sid="ok")         # a later row: never used
decide(w, tk(d0, "SLOW"), at(d0, 301), 0.5, 0.40, 0.42, sid="late")     # logged 05:01, its scan began 04:55: inside
decide(w, tk(d0, "LATE"), at(d0, 300), 0.5, 0.40, 0.42, sid="nosuch")   # no scan row: its own time, 05:00: outside
decide(w, tk(d0, "STARTED"), at(d0, 60), 0.5, 0.40, 0.42, reason="MARKET_STARTED", sid="ok")
decide(w, tk(d0, "WIDE"), at(d0, 60), 0.5, 0.30, 0.40, sid="ok")
decide(w, tk(d0, "NEWCODE"), at(d0, 60), 0.5, 0.40, 0.42, sid="ok", mv="v3@new")
w.execute("insert into decisions(decision_id,scan_id,ts,strategy_id,strategy_version,model_version,mode,ticker,action,reason,bid,ask,"
          "p_model,day_start_ts) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("nostart", "ok", at(d0, 60), P.STRATEGY, "v3", "v3@x", "paper", tk(d0, "NOSTART"), "abstain", "INSUFFICIENT_EDGE", .4, .42, .5, None))
decide(w, tk(TEST_DAYS[-1], "TEST"), at(TEST_DAYS[-1], 60), 0.5, 0.40, 0.42, sid="ok")
decide(w, tk(d0, "TEMP"), at(d0, 60), 0.5, 0.40, 0.42, strat="forecast_alpha.temp.v3", sid="ok")
decide(w, tk(d0, "V2"), at(d0, 60), 0.5, 0.40, 0.42, version="v2", sid="ok")
obs(w, tk(d0, "WIN"), 0.5, 0.41, "yes"); obs(w, tk(d0, "NEWCODE"), 0.5, 0.41, "no"); w.commit(); w.close()
with offline():
    c = P.connect_ro(Pdb); ex = {}
    fr = P.forward_rows(c, set(MODEL["model_versions"]), ex); allv = P.forward_rows(c); c.close()
assert set(fr) == {tk(d0, "WIN"), tk(d0, "SLOW")} and fr[tk(d0, "WIN")]["p"] == 0.5 and fr[tk(d0, "WIN")]["result"] == "yes", fr
assert set(allv) == set(fr) | {tk(d0, "NEWCODE")}
assert ex == {"outside_window": 2, "market_started": 1, "spread": 1, "model_version": 1, "no_day_start": 1}, ex
assert P.signals(0.70, 0.40, 0.42) == (("yes", 0.42), ("yes", 0.41, True))          # fair .555: edges .135 / .145
assert P.signals(0.71, 0.40, 0.42)[0] == ("yes", 0.42), "exactly 30 points from the mid: allowed"
assert P.signals(0.72, 0.40, 0.42) == (None, None), "more than 30 points from the mid: vetoed"
assert P.signals(0.55, 0.40, 0.42) == (None, None), "edge below 8 points"
assert P.signals(0.05, 0.30, 0.31) == (("no", 0.7), ("no", 0.69, False))            # 1c spread: joins at 1 - ask
print("forward rows: scan start inside the window, first usable row, MARKET_STARTED, spread, model version; signals: ok")

# 3. forward data: with a real edge for the corrected forecast (the market leans away from the truth), and without
def forward_db(name, edge):
    p_, c3 = fresh(name)
    c3.execute("attach database ? as src", (Pdb,))
    for t in ("obs", "decisions", "scans"): c3.execute("insert into %s select * from src.%s" % (t, t))
    c3.commit(); c3.execute("detach database src")
    r3 = random.Random(11 if edge else 12)
    for d in FWD:
        sid = "f%s" % d; scan(c3, sid, at(d, 55))
        for city in CITIES[:12]:
            p = r3.choice([0.1, 0.25, 0.4, 0.55, 0.7])
            truth = sig(A0 + B0 * P.logit(P.clip(p))) if edge else p
            mid = min(0.9, max(0.1, (truth - 0.22 if edge else truth) + r3.uniform(-0.03, 0.03)))
            bid, ask = round(mid - 0.01, 2), round(mid + 0.01, 2); t = tk(d, city)
            decide(c3, t, at(d, 56), p, bid, ask, sid=sid); obs(c3, t, p, (bid + ask) / 2, "yes" if r3.random() < truth else "no")
    c3.commit(); c3.close(); return p_
calls = []
def fetch(tickers, start, end):
    """Fake candles: the price trades through any limit within the evening; the first call fails; C11 never has any."""
    calls.append(len(tickers))
    if len(calls) == 1: raise RuntimeError("network down")
    return {t: [dict(end_period_ts=start + 600, price=dict(low_dollars="0.01", high_dollars="0.99"), extra="dropped")]
            for t in tickers if not t.endswith("C11")}

for name, edge in (("fwd_edge.db", True), ("fwd_null.db", False)):
    p_ = forward_db(name, edge); before = h(p_)
    P.CANDLES = os.path.join(OUT, "candles_" + name); P.RESULTS = os.path.join(OUT, "res_" + name); calls.clear()
    os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off_" + name)   # each scenario its own off-folder copy
    with offline():
        c = P.connect_ro(p_)
        assert P.store_candles(c, now=start_ts(FWD[0]) + 100, fetch=fetch)[0] == 0, "nothing before its day starts"
        late = start_ts(FWD[-1]) + 3600
        s1 = P.store_candles(c, now=late, fetch=fetch)            # day 1 fails (network), the rest are stored; C11 waits
        _r = P.score(c, 60, MODEL)
        assert _r[0] is None and _r[1].startswith("candles not stored yet"), _r[1]
        s2 = P.store_candles(c, now=late + 8 * 86400, fetch=fetch)   # day 1 retried; after 7 days C11 is listed as none
        s3 = P.store_candles(c, now=late + 9 * 86400, fetch=fetch)   # the third try: C11 is listed as none
        assert s3 == (0, 0) and s1[0] + s2[0] == 115 * 11 + 3, (s1, s2, s3)   # 11 cities a day, plus WIN, SLOW, NEWCODE
        st = P.load_day(FWD[5]); assert tk(FWD[5], "C11") in st["none"] and "extra" not in st["candles"][tk(FWD[5], "C00")][0]
        status = P.status(c, MODEL); assert "115 forward market days" in status and "both looks' day counts reached" in status, status
        for bad in ("cents", "Brier", "mean", " won", "rained", "%"): assert bad not in status, "status shows counts only"
        assert status.endswith("rows not counted: market_started 1, model_version 1, no_day_start 1, outside_window 2, spread 1"), status
        assert "futility look first" in P.score(c, 110, MODEL)[1]
        pend = P.score(c, 60, MODEL, today=FWD[0] + timedelta(days=3))
        assert pend[0] is None and "results still pending for 1 markets" in pend[1], pend[1]
        r60, v60 = P.score(c, 60, MODEL)
        assert r60 and r60["markets"] == 60 * 12 + 1 and r60["last_day"] == str(FWD[59]), (r60 and r60["markets"])
        assert r60["left_out_no_result"] == [tk(d0, "SLOW")]
        assert tk(FWD[5], "C11") in r60["no_candles"] and r60["excluded"].get("model_version") == 1
        assert "already taken" in P.score(c, 60, MODEL)[1]
        if edge:
            assert v60.startswith("continue"), v60
            keep_r = P.RESULTS
            P.RESULTS = os.path.join(OUT, "res_ended"); os.makedirs(P.RESULTS)
            assert "futility look first" in P.score(c, 110, MODEL, ended="stopped")[1], "60+ days: the futility look first"
            shutil.copy(os.path.join(keep_r, "plan7_score_60.json"), P.RESULTS)
            P.RESULTS = keep_r
            r110, v110 = P.score(c, 110, MODEL)
            A = r110["accuracy"]["A"]
            assert A["reading"].startswith("the corrected forecast was clearly more accurate") and A["boot"][1] < 0, A
            assert r110["accuracy"]["A3"]["reading"] == "the correction clearly improved on v3"
            assert r110["trading"]["maker"]["boot"][0] > 0 and v110.startswith("correction confirmed"), (r110["trading"], v110)
            assert "lag1" in A and "bonferroni" in r110 and "maker_raw_v3" in r110["trading"]
            md = open(os.path.join(P.RESULTS, "plan7_score_110.md"), encoding="utf-8").read()
            assert "Verdict" in md and "paper only" in md.lower() and "placebo" in md
            # the backstop: market days after it never count, and a shortfall then reads "not confirmed"
            keep_r, keep_b, keep_l = P.RESULTS, P.BACKSTOP, P.BACKSTOP_LOOK
            P.RESULTS = os.path.join(OUT, "res_backstop"); os.makedirs(P.RESULTS)
            shutil.copy(os.path.join(keep_r, "plan7_score_60.json"), P.RESULTS)
            P.BACKSTOP, P.BACKSTOP_LOOK = FWD[99], FWD[99] + timedelta(days=7)
            assert "early look refused: 100 forward market days" in P.score(c, 110, MODEL, today=FWD[99] + timedelta(days=6))[1]
            rb, vb = P.score(c, 110, MODEL, today=FWD[99] + timedelta(days=7))
            assert rb and rb["days"] == 100 and vb.startswith("not confirmed") and "backstop" in vb, (rb and rb["days"], vb)
            # an amendment adds a version (rows of v3@new then count); nothing in plan7.py writes the list
            P.RESULTS = os.path.join(OUT, "res_amend"); os.makedirs(P.RESULTS)
            P.BACKSTOP, P.BACKSTOP_LOOK = keep_b, keep_l
            json.dump({"versions": [{"version": "v3@new", "reason": "test", "recorded": "now"}]},
                      open(os.path.join(P.RESULTS, "plan7_versions.json"), "w"))
            ra, _ = P.score(c, 60, MODEL)
            assert ra["markets"] == 60 * 12 + 2 and "v3@new" in ra["model"]["versions"] and not ra["excluded"].get("model_version"), ra["markets"]
            P.RESULTS = keep_r
        else:
            assert v60.startswith("stop"), v60
            r110, v110 = P.score(c, 110, MODEL)
            assert r110 is None and "stopped at its futility look" in v110, v110
        c.close()
    assert h(p_) == before, "paper.db never changes"
print("candles and looks: stored once, retried, 'none' after 7 days; early and out-of-order looks refused; each look once;"
      " a planted edge confirmed, none found in the null case: ok")

# 4. an early end and the backstop read "not confirmed" (fail closed)
p_, c4 = fresh("short.db")
c4.execute("attach database ? as src", (Pdb,))
for t in ("obs", "decisions", "scans"): c4.execute("insert into %s select * from src.%s" % (t, t))
c4.commit(); c4.execute("detach database src")
r4 = random.Random(3)
for d in FWD[:20]:
    scan(c4, "g%s" % d, at(d, 55))
    for city in CITIES[:5]:
        t = tk(d, city); decide(c4, t, at(d, 56), 0.4, 0.40, 0.42, sid="g%s" % d); obs(c4, t, 0.4, 0.41, r4.choice(["yes", "no"]))
c4.commit(); c4.close()
P.CANDLES = os.path.join(OUT, "candles_short"); P.RESULTS = os.path.join(OUT, "res_short")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off_short")
with offline():
    c = P.connect_ro(p_)
    for k in range(3): P.store_candles(c, now=start_ts(FWD[30]) + (8 + k) * 86400, fetch=lambda t, s, e: {})   # 3 tries: none
    assert "early look refused" in P.score(c, 110, MODEL, today=P.BACKSTOP_LOOK - timedelta(days=1))[1]
    rb, vb = P.score(c, 110, MODEL, today=P.BACKSTOP_LOOK); assert rb and vb.startswith("not confirmed") and "backstop" in vb, vb
    os.remove(os.path.join(P.RESULTS, "plan7_score_110.json"))
    re_, ve = P.score(c, 110, MODEL, ended="the user stopped the bot", today=STOP + timedelta(days=40))
    assert re_ and ve.startswith("not confirmed") and "ended early" in ve, ve
    c.close()
print("an early end and the backstop date: 'not confirmed' (fail closed): ok")

# 4b. the candle store fails closed: a request that keeps failing counts as no candles after 7 days, and an unreadable
#     day file is moved aside (never deleted) and fetched again
P.CANDLES = os.path.join(OUT, "candles_fail"); OFF = os.path.join(OUT, "off_fail"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = OFF
def down(t, s, e): raise RuntimeError("HTTP 410 Gone")
with offline():
    c = P.connect_ro(p_)
    assert P.store_candles(c, now=start_ts(FWD[0]) + 3600, fetch=down)[0] == 0
    P.store_candles(c, now=start_ts(FWD[25]) + 8 * 86400, fetch=down)
    assert P.load_day(FWD[0])["none"] == [], "two tries: still waiting"
    P.store_candles(c, now=start_ts(FWD[25]) + 9 * 86400, fetch=down)
    st = P.load_day(FWD[0]); assert len(st["none"]) == 8 and all("request failed" in st["why"][t] for t in st["none"]), st
    f = P.day_file(FWD[1]); open(f, "wb").write(b"not gzip")
    st = P.load_day(FWD[1])   # moved aside; the off-folder copy (two tries so far, no candles) is read instead
    assert st["candles"] == {} and set(st["tries"].values()) == {2} and not os.path.exists(f), st
    assert any(x.startswith(os.path.basename(f) + ".unreadable-") for x in os.listdir(os.path.dirname(f)))
    n, _ = P.store_candles(c, now=start_ts(FWD[25]) + 8 * 86400, fetch=lambda t, s, e: {x: [dict(end_period_ts=s + 60)] for x in t})
    assert n == 19 * 5 and tk(FWD[1], "C00") in P.load_day(FWD[1])["candles"], n   # days 1-19 had 2 tries, day 1 restarted
    assert os.path.exists(os.path.join(OFF, "plan7", "candles", os.path.basename(P.day_file(FWD[1])))), "copied off the folder"
    # damage that only zlib notices (header intact, body zeroed, as a power cut can leave it): moved aside, and the
    # off-folder copy is used instead of starting empty
    f2 = P.day_file(FWD[2]); good = open(f2, "rb").read(); cut = len(good) // 3
    open(f2, "wb").write(good[:cut] + b"\0" * (len(good) - cut))
    st2 = P.load_day(FWD[2]); assert tk(FWD[2], "C00") in st2["candles"] and not os.path.exists(f2), "off-folder copy used"
    # the local copy lost: the off-folder copy is read, and a smaller store never replaces it there
    os.remove(P.day_file(FWD[3]))
    st3 = P.load_day(FWD[3]); assert len(st3["candles"]) == 5, st3
    P.save_day(FWD[3], dict(candles={}, none=[], why={}, tries={}))
    assert len(P._read_day(os.path.join(OFF, "plan7", "candles", os.path.basename(P.day_file(FWD[3]))))["candles"]) == 5
    # a Windows lock on the target is retried, and a temp file is never left behind
    real_replace, n_calls = os.replace, []
    def locked(a, b):
        n_calls.append(1)
        if len(n_calls) < 3: raise PermissionError("held by an indexer")
        return real_replace(a, b)
    os.replace = locked
    try: P.save_day(FWD[4], P.load_day(FWD[4]), sleep=lambda s: None)
    finally: os.replace = real_replace
    assert len(n_calls) == 3 and not [x for x in os.listdir(os.path.dirname(P.day_file(FWD[4]))) if x.endswith(".tmp")]
    os.replace = lambda a, b: (_ for _ in ()).throw(PermissionError("held"))
    try: P.save_day(FWD[4], P.load_day(FWD[4]), sleep=lambda s: None); raise AssertionError("gives up after 5 tries")
    except PermissionError: pass
    finally: os.replace = real_replace
    assert not [x for x in os.listdir(os.path.dirname(P.day_file(FWD[4]))) if x.endswith(".tmp")], "no temp file left"
    c.close()
pages = []
def big(url, params):
    """A fake GET near the 10,000-candle cap for groups of more than 4 tickers: the request is split into smaller ones."""
    ts = params["market_tickers"].split(","); pages.append(len(ts))
    class R:
        def raise_for_status(self): pass
        def json(self): return {"markets": [{"market_ticker": t, "candlesticks": [{"end_period_ts": 1}] * (9000 // len(ts) + 1 if len(ts) > 4 else 3)} for t in ts]}
    return R()
got = P.fetch_candles(["T%02d" % i for i in range(20)], 0, 1, get=big)
assert len(got) == 20 and pages[0] == 20 and max(pages[1:]) <= 4 and all(len(v) == 3 for v in got.values()), pages
print("candle store: a failing request counts as no candles after 7 days; an unreadable day file is moved aside and"
      " fetched again; requests near the candle cap are split: ok")

# 4c. auto runs the fit itself, keeps going when a step fails, and a failed fit is reported every time
P.MODEL = os.path.join(OUT, "res_auto", "plan7_model.json"); P.RESULTS = os.path.join(OUT, "res_auto")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off_auto")
P.CANDLES = os.path.join(OUT, "candles_auto0")
real_store, real_bot = P.store_candles, P.bot_date
P.store_candles = lambda c: (_ for _ in ()).throw(PermissionError("locked by an antivirus"))
P.bot_date = lambda ts: STOP + timedelta(days=1)
buf = io.StringIO()
with contextlib.redirect_stdout(buf), offline():
    rc = P.main(["auto", "--db", Pdb])
out = buf.getvalue(); P.store_candles = real_store
assert rc == 0 and "PLAN7 candles failed" in out and "fitted and frozen" in out and os.path.exists(P.MODEL), out
# the local model lost (folder wiped): restored from the off-folder copy, never refitted
frozen = json.load(open(P.MODEL)); os.remove(P.MODEL)
with offline():
    c = P.connect_ro(Pdb); m3, msg3 = P.fit(c, today=STOP + timedelta(days=40)); c.close()
assert "never refitted" in msg3 and json.load(open(P.MODEL)) == frozen and m3["a"] == frozen["a"], msg3
P.MODEL = os.path.join(OUT, "res_bad", "plan7_model.json")
json.dump({"failed": "too few markets"}, open(os.makedirs(os.path.dirname(P.MODEL)) or P.MODEL, "w"))
buf = io.StringIO()
with contextlib.redirect_stdout(buf), offline():
    assert P.main(["status", "--db", Pdb]) == 0 and P.main(["fit", "--db", Pdb]) == 2
assert buf.getvalue().count("the fit failed") == 2 and "too few markets" in buf.getvalue(), buf.getvalue()
P.bot_date = real_bot
# a database without the ledger: no versions (a failed fit), and auto still finishes
p_, c5 = fresh("noledger.db"); c5.execute("drop table decisions"); c5.execute("drop table scans"); c5.commit(); c5.close()
with offline():
    c = P.connect_ro(p_)
    assert P.fit_versions(c) == []
    try: P.forward_rows(c); raise AssertionError("no decisions table: forward_rows reports it")
    except sqlite3.OperationalError: pass
    c.close()
print("auto: runs the fit itself and each step on its own; a failed fit is reported every time; no ledger: no versions: ok")

# 5. the settle job's entry never fails and prints counts only; a missing database is refused
buf = io.StringIO()
with contextlib.redirect_stdout(buf), offline():
    P.CANDLES = os.path.join(OUT, "candles_auto")
    rc = P.main(["auto", "--db", os.path.join(OUT, "fwd_null.db")])   # the real candle fetch meets the blocked network
out = buf.getvalue()
assert rc == 0 and "PLAN7 (research, not in gate)" in out, out
try:
    P.main(["status", "--db", os.path.join(OUT, "missing.db")]); raise AssertionError("a missing database must be refused")
except SystemExit as ex: assert "not found" in str(ex)
print("status and auto: counts only, never fail the settle job, a missing database refused: ok")
print("PLAN7: all checks passed")
