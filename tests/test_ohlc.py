"""Historical OHLC checks, on fake candles (no network): every anomaly code in tbcommon/ohlc.py, dollar and cent
fields, the audit's market selection, chunked fetching, staleness and snapshot agreement, its report, and PLAN5 L's
descriptive candle record (the adverse-selection numbers stay exactly as before). python test_ohlc.py WORK OUT"""
import io, contextlib
import os, sys, json, shutil, sqlite3, importlib
from datetime import datetime, timezone
WORK, OUT = sys.argv[1], sys.argv[2]
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))
from tbcommon import ohlc


def C(t, bid, ask, price=None, vol=0, cents=False, **over):
    """A candle ending at t; bid/ask/price are (open, low, high, close) in dollars or None."""
    def blk(v):
        if v is None:
            return {}
        if cents:
            return dict(zip(("open", "low", "high", "close"), [round(x * 100) for x in v]))
        return {k + "_dollars": "%.4f" % x for k, x in zip(("open", "low", "high", "close"), v)}
    c = dict(end_period_ts=t, yes_bid=blk(bid), yes_ask=blk(ask), price=blk(price), volume=vol)
    c.update(over)
    return c


T0 = 1792800000 - 1792800000 % 60
ok = C(T0, (0.40, 0.39, 0.41, 0.40), (0.43, 0.42, 0.44, 0.43), (0.41, 0.41, 0.42, 0.42), 5)
assert ohlc.check_candle(ok, 60, T0) == [], ohlc.check_candle(ok, 60, T0)
assert ohlc.check_candle(C(T0, (0.40, 0.39, 0.41, 0.40), (0.43, 0.42, 0.44, 0.43), cents=True), 60, T0) == []
assert abs(ohlc.mid(ok) - 0.415) < 1e-12 and ohlc.ohlc(ok, "price") == (0.41, 0.41, 0.42, 0.42)
assert ohlc.field({"close": 45}, "close") == 0.45 and ohlc.field({"close_dollars": "0.4500", "close": 99}, "close") == 0.45
assert ohlc.field(None, "close") is None and ohlc.field({"close": ""}, "close") is None and ohlc.field({"close": "x"}, "close") is None
cases = {
    "OFF_GRID": C(T0 + 7, (0.4,) * 4, (0.43,) * 4),
    "FUTURE": C(T0 + 600, (0.4,) * 4, (0.43,) * 4),
    "OUT_OF_RANGE": C(T0, (0.4, 0.4, 1.2, 0.4), (0.43,) * 4),
    "HIGH_BELOW_LOW": C(T0, (0.4, 0.45, 0.41, 0.4), (0.43,) * 4),
    "OPEN_CLOSE_OUTSIDE": C(T0, (0.30, 0.39, 0.41, 0.40), (0.43,) * 4),
    "CROSSED": C(T0, (0.5,) * 4, (0.43,) * 4),
    "LOCKED": C(T0, (0.43,) * 4, (0.43,) * 4),
    "NEGATIVE_VOLUME": C(T0, (0.4,) * 4, (0.43,) * 4, vol=-1),
    "TRADE_OUTSIDE_QUOTE": C(T0, (0.4,) * 4, (0.43,) * 4, (0.6,) * 4),
}
for code, c in cases.items():
    got = ohlc.check_candle(c, 60, T0)
    assert code in got, (code, got)
assert ohlc.check_candle(cases["CROSSED"], 60, T0) == ["CROSSED", "TRADE_OUTSIDE_QUOTE"] or "CROSSED" in ohlc.check_candle(cases["CROSSED"], 60, T0)
assert ohlc.mid(cases["CROSSED"]) is None and ohlc.mid(cases["LOCKED"]) is None and ohlc.mid(C(T0, None, (0.4,) * 4)) is None
assert ohlc.check_candle(C(T0, None, None), 60, T0) == [], "a minute with no quotes is not an anomaly"
# an empty side (a price at 0 or 1) is a placeholder, not a quote: never CROSSED, LOCKED or TRADE_OUTSIDE_QUOTE (review 2026-10-23)
for b, a in ((0.0, 0.0), (0.98, 0.0), (0.0, 1.0), (1.0, 1.0), (0.97, 1.0)):
    got = ohlc.check_candle(C(T0, (b,) * 4, (a,) * 4, (0.99,) * 4), 60, T0)
    assert got == ["EMPTY_SIDE"], (b, a, got)
    assert ohlc.mid(C(T0, (b,) * 4, (a,) * 4)) is None
assert set(ohlc.INFO_CODES) == {"JUMP", "GAP", "EMPTY_SIDE"}
assert ohlc.field({"close": "0.4500"}, "close") == 0.45 and ohlc.field({"close": 45}, "close") == 0.45   # dollar string without the suffix
assert ohlc.check_candle(dict(end_period_ts=T0, volume_fp="-2.00"), 60, T0) == ["NEGATIVE_VOLUME"]
# trade within a cent of the quote range is fine; 2 cents outside is not
assert "TRADE_OUTSIDE_QUOTE" not in ohlc.check_candle(C(T0, (0.4,) * 4, (0.43,) * 4, (0.44,) * 4), 60, T0)
assert "TRADE_OUTSIDE_QUOTE" in ohlc.check_candle(C(T0, (0.4,) * 4, (0.43,) * 4, (0.45,) * 4), 60, T0)
# series: order, jumps, gaps
s = [C(T0, (0.4,) * 4, (0.43,) * 4), C(T0 + 60, (0.95,) * 4, (0.97,) * 4), C(T0 + 60, (0.95,) * 4, (0.97,) * 4), C(T0 + 30000, (0.4,) * 4, (0.43,) * 4)]
codes = ohlc.check_series(s, 60, T0 + 40000)
assert (1, "JUMP") in codes and (2, "TIME_NOT_INCREASING") in codes and (None, "GAP") in codes and (3, "JUMP") in codes, codes
assert ohlc.summary([codes, [(0, "JUMP")]]) == {"JUMP": 3, "TIME_NOT_INCREASING": 1, "GAP": 1}
assert (None, "GAP") in ohlc.check_series(s[:1], 60, T0, start=T0 - 7 * 3600), "a gap before the first candle counts"
assert ohlc.check_series([], 60, T0) == [] and (None, "GAP") in ohlc.check_series([], 60, T0, start=T0, end=T0 + 7 * 3600)

# ---- the audit, on a fake paper.db and a fake Kalshi ----
os.environ["PAPER_DB"] = os.path.join(OUT, "paper.db")
import ohlc_audit as A
A.DATA = os.path.join(OUT, "data"); A.OUT = os.path.join(OUT, "results"); A.AUDIT = os.path.join(A.DATA, "audit.jsonl")
NOW = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc).timestamp()
c = sqlite3.connect(os.environ["PAPER_DB"])
c.execute("create table obs(ticker text,version text,ts real,mid real,market_type text,primary key(ticker,version))")
rows = [("KXRAINNYC-26OCT27-T0", "v3", "rain", 0.40), ("KXHIGHDEN-26OCT27-T60", "v3", "temp", 0.20),
        ("KXRAINNYC-26OCT30-T0", "v3", "rain", 0.40),    # its window ends after NOW: not yet
        ("KXRAINNYC-26SEP01-T0", "v3", "rain", 0.40),    # older than --days
        ("KXRAINDCA-26OCT26-T0", "v3", "rain", 0.40)]
import postmortem
for t, v, mt, mid in rows:
    c.execute("insert into obs values(?,?,?,?,?)", (t, v, postmortem.day_start(t) - 20 * 3600, mid, mt))
c.commit(); c.close()
calls = []


def fake_http(path, params=None):
    calls.append((path, dict(params or {})))
    t = path.split("/")[4]
    if t.startswith("KXRAINDCA"):
        raise RuntimeError("HTTP 503")
    a, b = params["start_ts"], params["end_ts"]
    assert params["period_interval"] == 1 and b - a <= A.CHUNK
    ds = postmortem.day_start(t); snap = ds - 20 * 3600
    out = []
    for m in range(a - a % 60 + 60, b + 1, 60):
        if m % 600:   # one candle every 10 minutes, as when nothing changes in between
            continue
        if t.startswith("KXHIGHDEN") and m == snap - snap % 600:
            out.append(C(m, (0.30,) * 4, (0.25,) * 4))   # crossed at the snapshot minute
        else:
            mid = 0.40 if t.startswith("KXRAIN") else 0.30
            out.append(C(m, (mid - 0.01,) * 4, (mid + 0.01,) * 4))
    if out and a == params["start_ts"]:
        out.append(out[-1])   # a duplicate inside the chunk is dropped
    return dict(candlesticks=out)


A.http = fake_http
todo = A.targets(os.environ["PAPER_DB"], NOW, 21, set())
assert [t for t, _, _ in todo] == ["KXHIGHDEN-26OCT27-T60", "KXRAINNYC-26OCT27-T0", "KXRAINDCA-26OCT26-T0"], todo   # newest day start first (Denver starts 2 h after New York)
n = A.run(now=NOW, days=21, cap=60)
assert n == 2, n
recs = {r["ticker"]: r for r in A.lines(A.AUDIT)}
assert recs["KXRAINDCA-26OCT26-T0"]["error"].startswith("HTTP 503")
r = recs["KXRAINNYC-26OCT27-T0"]
span = A.BEFORE + A.AFTER
assert r["candles"] == span // 600 and r["codes"] == {} and r["max_gap_s"] == 600 and r["with_mid"] == r["candles"], r
assert len(calls) >= 2 * (span // A.CHUNK) and all(p.startswith("/series/KXRAINNYC/markets/") or p.startswith("/series/KXHIGHDEN/") or p.startswith("/series/KXRAINDCA/") for p, _ in calls)
sn = r["snapshots"][0]
assert sn["mid"] == 0.40 and abs(sn["candle_mid"] - 0.40) < 1e-9 and sn["gap"] == 0 and 0 <= sn["candle_age_s"] < 600, sn
h = recs["KXHIGHDEN-26OCT27-T60"]
assert h["codes"].get("CROSSED") == 1 and h["snapshots"][0]["candle_mid"] is None and h["bad_minutes"], h
# run again: done markets are not fetched again; the failed one is retried
calls.clear(); A.run(now=NOW, days=21, cap=60)
assert {p.split("/")[4] for p, _ in calls} == {"KXRAINDCA-26OCT26-T0"}, calls
S = A.report(now=NOW)
assert S["rain"]["markets"] == 1 and S["temp"]["markets"] == 1 and S["all"]["candles"] == 2 * (span // 600)
assert S["temp"]["codes"] == {"CROSSED": 1} and S["temp"]["markets_with_issue"] == 1 and S["rain"]["markets_with_issue"] == 0
assert S["rain"]["gap_over_5pts"] == 0 and S["temp"]["no_candle_at_snapshot"] == 0 and S["all"]["snapshots"] == 2
md = open(os.path.join(A.OUT, "ohlc_audit.md"), encoding="utf-8").read()
js = json.load(open(os.path.join(A.OUT, "ohlc_audit.json"), encoding="utf-8"))
assert "Oct 30, 12:00 PM, La Paz time (UTC-4)" in md and "| CROSSED | 1 |" in md and "could not be fetched" in md, md
assert js["made"] == "2026-10-30T12:00:00-04:00" and js["errors"] == 1
assert A.latest_at([C(T0, None, None), C(T0 + 60, None, None)], T0 + 59)["end_period_ts"] == T0 and A.latest_at([], T0) is None
# --every: a second run inside the interval does nothing
calls.clear()
# The --every check uses the wall clock. Fixed here to before every fixture market settles, so these two runs audit
# nothing (fixed 2026-10-28: after Oct 26 the real clock made them use up the failing market's retries, and the
# retry check below failed for a reason unrelated to the code under test).
_real_time = A.time.time
A.time.time = lambda: datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
try:
    assert A.main(["run", "--every", "3600"]) == 0
    _out = io.StringIO()
    with contextlib.redirect_stdout(_out):
        assert A.main(["run", "--every", "3600"]) == 0
    assert "ran " in _out.getvalue() and "next after" in _out.getvalue(), ("the second run inside the interval is skipped", _out.getvalue())
finally:
    A.time.time = _real_time
assert A.main(["bogus"]) == 1
# a market that keeps failing is tried TRIES times in all, then left; an error never replaces a good record
calls.clear(); A.run(now=NOW, days=21, cap=60); A.run(now=NOW, days=21, cap=60)
assert [p.split("/")[4] for p, _ in calls].count("KXRAINDCA-26OCT26-T0") >= 1
calls.clear(); A.run(now=NOW, days=21, cap=60)
assert not calls, "after %d failed runs the market is left" % A.TRIES
S, errs = A.summarize(A.lines(A.AUDIT) + [dict(ticker="KXRAINNYC-26OCT27-T0", mtype="rain", error="later failure")])
assert S["rain"]["markets"] == 1 and len(errs) == 1, (S, errs)
# no candles: retried, then left; a wide candle spread does not count in the snapshot comparison
r0 = A.audit_market("KXRAINX-26OCT27-T0", "rain", [], NOW, [(NOW - 100, 0.4)])
assert r0["candles"] == 0 and r0["snapshots"][0]["candle_age_s"] is None
wide = A.audit_market("KXRAINX-26OCT27-T0", "rain", [C(T0, (0.30,) * 4, (0.50,) * 4)], NOW, [(T0 + 30, 0.40)])
assert wide["snapshots"][0]["candle_mid"] == 0.4 and wide["snapshots"][0]["spread"] == 0.2 and wide["snapshots"][0]["gap"] is None, wide
tight = A.audit_market("KXRAINX-26OCT27-T0", "rain", [C(T0, (0.38,) * 4, (0.42,) * 4)], NOW, [(T0 + 30, 0.30)])
assert tight["snapshots"][0]["gap"] == 0.1, tight

# ---- PLAN5 L: the candle record is descriptive; adverse numbers are unchanged ----
import lip
cs = [C(T0, (0.40,) * 4, (0.44,) * 4), C(T0 + 60, (0.41,) * 4, (0.45,) * 4), C(T0 + 3000, (0.50,) * 4, (0.40,) * 4)]
adv_before = lip.adverse_mid(cs, "yes", T0 + 30, 40)
chk = lip.candle_check(cs, {"yes": T0 + 30, "no": None}, T0 + 4000)
assert lip.adverse_mid(cs, "yes", T0 + 30, 40) == adv_before == {"60": 0.03, "300": 0.03}, adv_before
assert chk["codes"].get("CROSSED") == 1 and chk["age"]["yes"] == {"60": 30.0, "300": 270.0} and chk["age"]["no"] == {"60": None, "300": None}, chk
assert "candle_check" not in open(os.path.join(WORK, "research", "lip.py"), encoding="utf-8").read().split("def score")[1], "score() must not read it"
print("ohlc checks and audit: all checks passed")
