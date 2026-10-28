"""The stop date's single look (pre-committed by the user on 2026-10-28, before the verdict). No network.
From 2026-11-11 the gate is judged once, stored in paper.db, and v3 rain paper-trades market days from Nov 11 on only
after a stored look that passed; the limit-order ledger mirrors it; live.py then has nothing new to copy.
python test_gatelook.py WORK OUT"""
import os, sys, io, json, random, sqlite3, contextlib, shutil
import datetime as _dt
from datetime import datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "off")
sys.path.insert(0, WORK)
import core, kalshi, strategy, shadow, audit
STOP = strategy.STOP_DATE
assert str(STOP) == "2026-11-11" and "GATE_NOT_PASSED" in audit.REASONS

class FakeDate(_dt.date):
    T = None
    @classmethod
    def today(cls): return cls.T
def today(d): FakeDate.T = d; strategy.date = FakeDate   # final() and report() read strategy.date.today()
def fresh(name):
    p = os.path.join(OUT, name); os.environ["PAPER_DB"] = p; core.DB = p
    return core.db()
def quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): r = fn(*a, **k)
    return r, out.getvalue()
now = datetime.now(timezone.utc)   # close times follow the real clock (so the markets have not "started"); market days come from the ticker
def mk(day, city, bid=0.40, ask=0.42):
    return dict(ticker="KXRAIN-%s-%s" % (day.strftime("%y%b%d").upper(), city), event_ticker="KXRAIN-%s" % day.strftime("%y%b%d").upper(),
                close_time=(now + timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"), yes_bid_dollars="%.2f" % bid, yes_ask_dollars="%.2f" % ask, rules_primary="")
D10, D11, D12 = STOP - timedelta(days=1), STOP, STOP + timedelta(days=1)
def scan_with(c, markets, fc=0.71):
    kalshi.markets = lambda *a, **k: markets
    strategy.estimate = lambda m: fc
    _, out = quiet(strategy.scan, c)
    got = {r[0]: r[1] for r in c.execute("select ticker,reason from decisions where strategy_id='forecast_alpha.rain.v3' and scan_id=(select scan_id from scans where kind='scan' order by started_ts desc limit 1)")}
    return got, out
def look_rows(c):
    try: return c.execute("select stop_date,passed from gate_look").fetchall()
    except sqlite3.OperationalError: return None

# 1. the helpers
assert strategy.market_day("KXRAIN-26NOV10-NYC") == D10 and strategy.before_stop("KXRAIN-26NOV10-NYC") and not strategy.before_stop("KXRAIN-26NOV11-NYC")
assert strategy.market_day("junk") is None and not strategy.before_stop("junk") and strategy.market_day(None) is None
assert not strategy.final(D10) and strategy.final(STOP) and strategy.final(D12)
assert strategy.gate_look(None, today=D10) is None, "before the stop date nothing is read or stored"
assert "pre-committed" in strategy.look_line(None)
print("helpers: market day from the ticker, unreadable days fail closed, no look before the stop date: ok")

# 2. before the stop date: the test's market days trade as before; a market day from Nov 11 on waits for the look
today(D10)
c = fresh("before.db")
got, out = scan_with(c, [mk(D10, "AAA"), mk(D11, "BBB")])
assert got == {"KXRAIN-%s-AAA" % D10.strftime("%y%b%d").upper(): "TRADE", "KXRAIN-%s-BBB" % D11.strftime("%y%b%d").upper(): "GATE_NOT_PASSED"}, (got, out)
assert c.execute("select count(*) from trades").fetchone()[0] == 1 and c.execute("select count(*) from obs").fetchone()[0] == 2, "both markets logged"
assert look_rows(c) is None, "nothing is stored before the stop date"
_, rep = quiet(strategy.report, c)
assert "GATE LOOK (pre-committed 2026-10-28): judged once from 2026-11-11" in rep, rep
c.close()
print("before Nov 11: the test's days trade as before, Nov 11 markets are logged but wait for the look: ok")

# 3. on the stop date, while a market of the test's days has no result: pending, no trades, nothing stored
today(STOP)
c = fresh("pending.db")
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)", ("KXRAIN-26NOV10-ZZZ", "v3", 0, 0.3, 0.4, "rain"))
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)", ("KXRAIN-26NOV11-YYY", "v3", 0, 0.3, 0.4, "rain"))   # a later day: not waited for
c.commit()
lk = strategy.gate_look(c)
assert lk == dict(passed=None, pending=1, recorded=False), lk
got, out = scan_with(c, [mk(D12, "AAA")])
assert list(got.values()) == ["GATE_NOT_PASSED"] and "waiting for 1 v3 rain markets" in out, (got, out)
assert not look_rows(c) and c.execute("select count(*) from trades").fetchone()[0] == 0
# 4. results in: report() takes the look and stores it (not passed: too few markets and trades)
c.execute("update obs set result='no' where ticker='KXRAIN-26NOV10-ZZZ'"); c.commit()
_, rep = quiet(strategy.report, c)
assert look_rows(c) == [("2026-11-11", 0)], look_rows(c)
assert "GATE (v3 rain only): not passed" in rep and "GATE LOOK (single look, stored" in rep and "not passed: no edge demonstrated" in rep, rep
got, out = scan_with(c, [mk(D12, "AAA"), mk(D12, "BBB", 0.62, 0.64)])
assert set(got.values()) == {"GATE_NOT_PASSED", "INSUFFICIENT_EDGE"} and c.execute("select count(*) from trades").fetchone()[0] == 0, (got, out)
assert c.execute("select count(*) from obs where ticker like 'KXRAIN-%s-%%'" % D12.strftime("%y%b%d").upper()).fetchone()[0] == 2, "still logged"
# the limit-order ledger mirrors the bot: no order for a Nov 12 market after a failed look
shadow.v4_log = lambda c_, mk_: None
kalshi.markets = lambda *a, **k: [mk(D12, "AAA")]
_, out = quiet(shadow.scan, c)
assert c.execute("select count(*) from shadow_orders").fetchone()[0] == 0, out
assert c.execute("select reason from decisions where strategy_id='maker_spread.rain.v3'").fetchall() == [("GATE_NOT_PASSED",)], out
print("on Nov 11: pending until the test's markets settle, then one stored failed look; no paper trades or limit orders after it: ok")
# 5. the stored look is never recomputed: data that would now pass leaves it failed
def passing_data(c, n_days=20, per_day=6, trades=50, pnl=0.10):
    for i in range(n_days):
        d = (STOP - timedelta(days=n_days + 1 - i)).strftime("%y%b%d").upper()
        for j in range(per_day):
            y = (i + j) % 3 != 0
            c.execute("insert or ignore into obs(ticker,version,ts,fc,mid,market_type,result) values(?,?,?,?,?,?,?)",
                      ("KXRAIN-%s-C%02d" % (d, j), "v3", 0, 0.9 if y else 0.1, 0.6 if y else 0.4, "rain", "yes" if y else "no"))
    for k in range(trades):
        c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version,status,result,pnl) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (0, "KXRAIN-26OCT20-T%02d" % k, "yes", 0.5, 0.6, 1, 0.5, 0.02, "v3", "settled", "yes", pnl))
    c.commit()
passing_data(c)
assert strategy.gate_ok(strategy.gate_inputs(c)), "the data alone would pass now"
lk = strategy.gate_look(c)
assert lk["passed"] is False and lk["recorded"], lk
_, rep = quiet(strategy.report, c)
assert "GATE (v3 rain only): not passed" in rep, "the stored look decides, not today's numbers"
got, _ = scan_with(c, [mk(D12, "CCC")])
assert list(got.values()) == ["GATE_NOT_PASSED"]
c.close()
print("judged once: later data that would pass does not reopen trading: ok")

# 6. a look that passed: v3 keeps paper trading new market days, and the ledger places orders; later losses do not undo it
c = fresh("passed.db")
passing_data(c)
got, out = scan_with(c, [mk(D12, "AAA")])
assert list(got.values()) == ["TRADE"], (got, out)
assert look_rows(c) == [("2026-11-11", 1)]
_, rep = quiet(strategy.report, c)
assert "GATE (v3 rain only): passed (paper only)" in rep and "passed on paper" in rep, rep
kalshi.markets = lambda *a, **k: [mk(D12, "DDD")]
c.execute("insert into obs(ticker,version,ts,fc,mid,market_type) values(?,?,?,?,?,?)", ("KXRAIN-%s-DDD" % D12.strftime("%y%b%d").upper(), "v3", 0, 0.71, 0.41, "rain")); c.commit()
_, out = quiet(shadow.scan, c)
assert c.execute("select count(*) from shadow_orders").fetchone()[0] == 1, out
c.execute("update trades set pnl=-1 where version='v3' and ticker like 'KXRAIN-26OCT20-%'"); c.commit()
assert not strategy.gate_ok(strategy.gate_inputs(c)) and strategy.gate_look(c)["passed"] is True
c.close()
print("a passed look: v3 keeps paper trading and the ledger keeps quoting; later numbers do not undo the single look: ok")

# 6b. the look counts only the test's own market days, so a late look gives the same verdict (review M1)
def backups(tag): return sorted(f for f in os.listdir(os.path.join(OUT, "backups")) if tag in f)
c = fresh("late.db")
passing_data(c)
for i in range(3):   # market days from the stop date on, settled before a late look: they must not count
    d = (STOP + timedelta(days=i)).strftime("%y%b%d").upper()
    for j in range(40):
        c.execute("insert into obs(ticker,version,ts,fc,mid,market_type,result) values(?,?,?,?,?,?,?)", ("KXRAIN-%s-L%02d" % (d, j), "v3", 0, 0.99, 0.01, "rain", "no"))
    c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version,status,result,pnl) values(?,?,?,?,?,?,?,?,?,?,?,?)",
              (0, "KXRAIN-%s-L00" % d, "yes", 0.5, 0.6, 100, 50, 1, "v3", "settled", "no", -51.0))
c.commit()
assert not strategy.gate_ok(strategy.gate_inputs(c)), "all days together would fail"
g = strategy.gate_inputs(c, until=STOP)
assert g["markets"] == 120 and g["trades"] == 50 and strategy.gate_ok(g), g
nb = len(backups("pregatelook"))
lk = strategy.gate_look(c, today=STOP + timedelta(days=3))
assert lk["passed"] is True and lk["recorded"] and lk["markets"] == 120 and lk["last_day"] == str(STOP - timedelta(days=2)) == "2026-11-09" and lk["unresolved"] == [], lk
assert len(backups("pregatelook")) == nb + 1, "paper.db is backed up before the new table"
c.close()
print("a late look judges the same 28 days (later market days excluded), after a backup: ok")
# 6c. while the look is pending, nothing says "passed", even when today's numbers would (review S1); open trades also wait
c = fresh("wait.db")
passing_data(c)
c.execute("insert into trades(ts,ticker,side,price,fair,n,cost,fee,version) values(?,?,?,?,?,?,?,?,?)", (0, "KXRAIN-26NOV10-OPN", "yes", 0.5, 0.6, 1, 0.5, 0.02, "v3"))
c.commit()
assert strategy.gate_ok(strategy.gate_inputs(c)), "today's numbers alone pass"
lk = strategy.gate_look(c)
assert lk == dict(passed=None, pending=1, recorded=False), lk
_, rep = quiet(strategy.report, c)
assert "GATE (v3 rain only): not judged yet (the single look is pending)" in rep and "passed (paper only)" not in rep and "waiting for 1" in rep, rep
os.chdir(OUT); import dashboard
real_final = dashboard.final; dashboard.final = lambda *a: True   # the page reads the real date; here it is the stop date
D = dashboard.read_db(os.path.join(OUT, "wait.db")); html = dashboard.build_page(D)
dashboard.final = real_final
assert "single look is pending" in html and "All four gate checks pass" not in html
# 6d. a market of the test's days that never settles (voided) keeps the look pending: no cutoff unless the user sets one
assert strategy.LOOK_DEADLINE is None
assert strategy.gate_look(c, today=STOP + timedelta(days=60))["passed"] is None, "still pending two months later (fail closed)"
strategy.LOOK_DEADLINE = STOP + timedelta(days=7)   # the mechanism, if the user ever chooses a cutoff
assert strategy.gate_look(c, today=strategy.LOOK_DEADLINE - timedelta(days=1))["passed"] is None
lk = strategy.gate_look(c, today=strategy.LOOK_DEADLINE)
assert lk["passed"] is True and lk["recorded"] and lk["unresolved"] == ["KXRAIN-26NOV10-OPN"], lk
strategy.LOOK_DEADLINE = None
c.close()
print("pending: no verdict anywhere until the look; open test-day trades wait too; a voided market keeps it pending (no cutoff set): ok")

# 7. a read-only connection (live.py status): worked out, never stored, never an error; scans would not trade on it
c = fresh("ro.db"); passing_data(c, pnl=-0.1); c.close()
nb = len(backups("pregatelook"))
ro = sqlite3.connect("file:%s?mode=ro" % os.path.join(OUT, "ro.db"), uri=True)
lk = strategy.gate_look(ro)
assert lk["passed"] is False and lk["recorded"] is False, lk
_, rep = quiet(strategy.report, ro)
assert "GATE LOOK (worked out now, stored by the next report or scan): not passed" in rep, rep
assert strategy._after_stop_allowed(ro, record=False) is False
ro.close()
c = sqlite3.connect(os.path.join(OUT, "ro.db")); assert look_rows(c) is None; c.close()
assert len(backups("pregatelook")) == nb, "no backup is made for a read-only look"
import live
live.PAPER = os.path.join(OUT, "ro.db")
gl = live.gate_lines()
assert any(l.startswith("GATE LOOK") for l in gl) and any(l.startswith("GATE (v3 rain only)") for l in gl), gl
print("read-only (live.py status): the look is shown, not stored, and shown at unlock: ok")

# 8. an error while taking the look closes v3 for market days from Nov 11 on (fail closed)
c = fresh("err.db")
real = strategy.gate_inputs
strategy.gate_inputs = lambda c_: (_ for _ in ()).throw(RuntimeError("disk"))
got, out = scan_with(c, [mk(D12, "AAA")])
assert list(got.values()) == ["GATE_NOT_PASSED"] and "could not be worked out" in out, (got, out)
strategy.gate_inputs = real
c.close()
print("an error while judging: no trades for market days from Nov 11 on: ok")

# 9. gate_ok(gate_inputs) is the rule report() used before 2026-10-28, on random data (both outcomes)
def old_ok(c):   # report()'s gate before 2026-10-28, verbatim
    bf = bm = None; no = 0
    o = c.execute("select fc,mid,result from obs where result is not null and version=? and market_type=?", ("v3", "rain")).fetchall()
    if o: bf, bm, no = strategy._brier(o, 0), strategy._brier(o, 1), len(o)
    n3 = pnl3 = 0
    rows = c.execute("select side,result,pnl from trades where status='settled' and version=? and (ticker like 'KXRAIN%')=?", ("v3", 1)).fetchall()
    if rows: n3, pnl3 = len(rows), sum(r[2] for r in rows)
    mg = strategy.margin(c.execute("select ticker,fc,mid,result from obs where result is not null and version='v3' and market_type='rain'").fetchall())
    return strategy.final() and n3 >= 50 and pnl3 > 0 and bf is not None and bf < bm and strategy.clear(mg) and no >= 100
seen = set()
for seed in range(150):
    R = random.Random(seed); c = sqlite3.connect(":memory:")
    c.execute("create table obs(ticker,version,ts,fc,mid,market_type,result)"); c.execute("create table trades(ticker,version,status,side,result,pnl)")
    skill = R.random() < 0.5
    for i in range(R.randint(110, 220)):
        d = (STOP - timedelta(days=R.randint(1, 28))).strftime("%y%b%d").upper(); y = R.random() < 0.3
        f = min(0.99, max(0.01, (0.85 if y else 0.15) + R.uniform(-0.1, 0.1))) if skill else R.random()
        c.execute("insert into obs values(?,?,?,?,?,?,?)", ("KXRAIN-%s-X%d" % (d, i), R.choice(["v3"] * 8 + ["v2"]), 0, f, R.uniform(0.2, 0.8), R.choice(["rain"] * 8 + ["temp"]), R.choice(["yes" if y else "no"] * 9 + [None])))
    for k in range(R.randint(120, 220)):
        c.execute("insert into trades values(?,?,?,?,?,?)", (R.choice(["KXRAIN-26OCT20-T%d" % k, "KXHIGHNY-26OCT20-T%d" % k]), R.choice(["v3"] * 5 + ["v1"]), R.choice(["settled"] * 5 + ["open"]), "yes", "yes", R.uniform(-0.2, 0.4 if skill else 0.1)))
    for t in (D10, STOP):
        today(t)
        new = strategy.gate_ok(strategy.gate_inputs(c)); assert new == bool(old_ok(c)), (seed, t)
        seen.add(new)
    c.close()
assert seen == {True, False}, seen
print("gate_ok(gate_inputs) gives report()'s verdict on 300 random cases, passing and failing: ok")

# 10. the dashboard shows a stored failed look as the verdict
today(STOP)
os.chdir(OUT)
D = dashboard.read_db(os.path.join(OUT, "pending.db"))
assert [r["passed"] for r in D["gate_look"]] == [0]
page = dashboard.build_page(D)
html = page if isinstance(page, str) else json.dumps(page)
assert "single look" in html and "did not pass" in html
print("dashboard: a stored failed look is the verdict: ok")
print("stop date single look: all checks passed")
