"""research/plan19.py (PLAN19: resting bids at the reference price on markets with liquidity rewards), on fake Kalshi
answers and synthetic records. No network. Covers the quote and its skips (sub-cent prices too), the queue-aware fills
with the size cap, the weight drift, the reward arithmetic, the draw (sorted universe minus open windows, seeded by the
UTC epoch hour), overlapping and long-dated programs, the $1 minimum, the ladder valuation with the taker fee, the SE,
the single score with its PASS, FAIL and NOT TESTABLE branches, counts-only status, and that it never orders.
python test_plan19.py WORK OUT"""
import os, sys, json, math, random, shutil, tempfile, hashlib, io, contextlib, time
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])   # a fresh folder each run
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import plan19 as P
P.DATA = os.path.join(OUT, "data"); P.OUT = os.path.join(OUT, "results")
def boom(*a, **k): raise AssertionError("no network in tests: %s" % (a[:1],))
P.http = boom

# ---------- research only, frozen text, fixed numbers ----------
src = open(os.path.join(WORK, "research", "plan19.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "from live" not in src, "research only: never an order"
assert "create_order" not in src and "KALSHI_KEY" not in src
with open(os.path.join(WORK, "research", "PLAN19.md"), "rb") as fh:
    assert hashlib.sha256(fh.read()).hexdigest() == P.PLAN_SHA, "PLAN19.md is the frozen text"
assert P.REWARDS_APPLY is True and "Yes, eligible" in P.ELIGIBILITY_RECORD   # fixed before the first sample (section 5)
assert (P.PER, P.Q, P.QS, P.CLOSE_GAP, P.PROG_MAX_AGE, P.UNIT) == (40, 100, (10, 100, 1000), 6 * 3600, 6 * 3600, 1e-4)
assert P.day_of(P.START) == "2026-11-28" and P.day_of(P.END - 1) == "2026-12-27" and P.day_of(P.CLOSE_MAX) == "2026-12-27"
assert P.day_of(P.SCORE_FROM) == "2026-12-29" and P.START % 3600 == 0
def near(a, b, tol=1e-9): return abs(a - b) < tol

# ---------- section 2: the reference price, the qualifying size and the skips ----------
prog = dict(target_size_fp="1000.00", discount_factor_bps=5000, period_reward=1000000,
            start_date="2026-11-20T00:00:00Z", end_date="2026-11-27T00:00:00Z")
pool = 1000000 * 1e-4 * 3600 / (7 * 86400)
assert near(P.hourly_pool(prog), pool) and near(pool * 24 * 7, 100.0)   # 1,000,000 units a week = $100 a week
assert P.hourly_pool(dict(prog, period_reward=None)) is None and P.hourly_pool(dict(prog, end_date=prog["start_date"])) is None
# sub-cent prices: 4.55c (150), 4.50c (100), 4.00c (500); target/5 = 200 is reached at 4.50c
lad = P.ladder({"yes": [["0.0450", "100"], ["0.0455", "150"], ["0.0400", "500"], ["0.0300", "0"]]}, "yes")
assert lad == [(455, 150.0), (450, 100.0), (400, 500.0)], lad   # mils (1/100 cent), best first, empty level dropped
assert P.reference(lad, 1000) == 450 and P.reference(lad, 5000) is None
assert near(P.qualifying(lad, 450, 0.5), 150 + 100 + 500 * 0.5 ** 0.5)   # 0.5 cent below: d^0.5; at or above: 1
book = {"yes": [["0.4500", "100"], ["0.4400", "150"], ["0.4000", "900"]], "no": [["0.5300", "250"], ["0.5000", "900"]]}
qt, why = P.quote(book, prog)
assert why is None and qt["valid"] and qt["d"] == 0.5 and qt["target"] == 1000 and near(qt["pool"], pool) and near(qt["usd_per_day"], pool * 24)
Y, N = qt["sides"]["yes"], qt["sides"]["no"]
assert Y["price"] == 0.44 and Y["best"] == 0.45 and Y["queue"] == 150 and near(Y["qual"], 100 + 150 + 900 * 0.5 ** 4), Y   # behind the best bid
assert N["price"] == 0.53 and N["best"] == 0.53 and N["queue"] == 250 and near(N["qual"], 250 + 900 * 0.5 ** 3), N
assert near(Y["share"]["100"], 100 / (Y["qual"] + 100)) and near(Y["share"]["10"], 10 / (Y["qual"] + 10)) and set(Y["share"]) == {"10", "100", "1000"}
assert qt["side_skips"] == []
q2, _ = P.quote({"yes": book["yes"], "no": [["0.5300", "250"], ["0.5000", "500"]]}, prog)
assert q2 and not q2["valid"] and set(q2["sides"]) == {"yes", "no"}   # NO holds 750 < 1,000: quoted, but no reward
assert P.quote({"yes": [["0.6000", "500"]], "no": [["0.4000", "500"]]}, prog) == (None, "locked or crossed book")
assert P.quote({"yes": [["0.6000", "500"]], "no": [["0.4100", "500"]]}, prog) == (None, "locked or crossed book")
assert P.quote({"yes": [], "no": []}, prog) == (None, "side without bids")
q3, _ = P.quote({"yes": book["yes"], "no": [["0.5000", "100"]]}, prog)   # NO never reaches 200
assert set(q3["sides"]) == {"yes"} and q3["side_skips"] == ["side never reaches the reference size"] and not q3["valid"]
q4, _ = P.quote({"yes": book["yes"], "no": []}, prog)
assert set(q4["sides"]) == {"yes"} and q4["side_skips"] == ["side without bids"]
assert P.quote({"yes": [["0.0000", "500"]], "no": []}, prog) == (None, "quote at 0c or 100c")
assert P.quote(book, dict(prog, target_size_fp=None)) == (None, "unreadable program")
assert P.quote(book, dict(prog, discount_factor_bps=0)) == (None, "unreadable program")

# ---------- section 4: fills (queue at the quote price, through trades up to their size, the cap) ----------
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
def tr(taker, yes, n, t=1000):
    return dict(taker_side=taker, yes_price_dollars="%.4f" % yes, no_price_dollars="%.4f" % (1 - yes), count_fp="%.2f" % n, created_time=iso(t))
assert P.fills([tr("no", 0.44, 100)], "yes", 0.44, 150, 100) == (0, None)             # still behind the 150 ahead of us
f, t1 = P.fills([tr("no", 0.44, 100, 1000), tr("no", 0.44, 80, 1100)], "yes", 0.44, 150, 100)
assert (f, t1) == (30, 1100), (f, t1)                                                # 180 at our price: 30 reach us
assert P.fills([tr("no", 0.43, 7, 1200)], "yes", 0.44, 150, 100) == (7, 1200)       # through: in full, up to its size
assert P.fills([tr("no", 0.43, 700, 1200)], "yes", 0.44, 150, 100) == (100, 1200)   # capped at q
assert P.fills([tr("no", 0.43, 700, 1200)], "yes", 0.44, 150, 10)[0] == 10
assert P.fills([tr("yes", 0.43, 700)], "yes", 0.44, 150, 100) == (0, None)          # a YES buyer never sells to our YES bid
assert P.fills([tr("no", 0.45, 700)], "yes", 0.44, 0, 100) == (0, None)             # above our price
assert P.fills([tr("yes", 0.48, 9, 1300)], "no", 0.53, 250, 100) == (9, 1300)       # NO price 52 < 53: through
assert P.fills([tr("yes", 0.47, 260, 1300)], "no", 0.53, 250, 100) == (10, 1300)    # NO price 53: 10 past the queue
assert P.fills([tr("no", 0.44, 160, 1500), tr("no", 0.40, 5, 1400)], "yes", 0.44, 150, 100) == (15, 1400)   # time order; first fill 1400
assert P.fills([dict(taker_side="no", yes_price=43, count=3, created_time=iso(1000))], "yes", 0.44, 0, 100) == (3, 1000)   # cents fields
assert P.fills([tr("no", 0.0449, 4)], "yes", 0.045, 0, 100)[0] == 4 and P.fills([tr("no", 0.0451, 4)], "yes", 0.045, 0, 100)[0] == 0   # sub-cent

# ---------- section 3: the weight drift ----------
def cd(t, b, a): return dict(end_period_ts=t, yes_bid={"close_dollars": "%.4f" % b}, yes_ask={"close_dollars": "%.4f" % a})
TS = 10 ** 6
assert near(P.weight_sum([], "yes", TS, 0.45, 0.5, None), 30.0)                    # no candle at all: 0.5 a minute
assert near(P.weight_sum([cd(TS - 30, 0.50, 0.52)], "yes", TS, 0.45, 0.5, None), 30.0)   # a candle before the hour does not count
assert near(P.weight_sum([], "yes", TS, 0.45, 0.5, TS + 600), 5.0)                 # ... until the fill
cs = [cd(TS + 600, 0.47, 0.49)]   # the YES bid moves up 2c, ending in minute 9
assert near(P.weight_sum(cs, "yes", TS, 0.45, 0.5, None), 9 + 51 * 0.25, 1e-6)    # minutes 0-8 carry B_0
assert near(P.weight_sum(cs, "yes", TS, 0.45, 0.5, TS + 1200), 9 + 11 * 0.25, 1e-6)   # minutes ending after the fill excluded
assert near(P.weight_sum(cs, "yes", TS, 0.45, 0.5, TS + 1190), 9 + 10 * 0.25, 1e-6)   # the minute of the fill is not before it
assert near(P.weight_sum(cs, "no", TS, 0.53, 0.5, None), 60.0, 1e-6)              # NO bid = 1 - 0.49 = 0.51: down, weight 1
assert near(P.weight_sum([cd(TS + 60, 0.44, 0.46)], "yes", TS, 0.45, 0.5, None), 60.0)   # bid down: never above 1
assert near(P.weight_sum([cd(TS + 120, 0.46, 0.48), cd(TS + 240, 0.45, 0.47)], "yes", TS, 0.45, 0.5, None), 1 + 2 * 0.5 + 57, 1e-6)   # carried, then back
assert near(P.weight_sum([dict(end_period_ts=TS + 60, yes_bid={"close_dollars": "0.46"})], "no", TS, 0.53, 0.5, None), 30.0)   # no ask: the NO side has no candle
a = P.adverse([cd(TS + 1000, 0.40, 0.42), cd(TS + 1250, 0.36, 0.38)], "yes", TS + 950, 0.44)
assert near(a["60"], 0.41 - 0.44) and near(a["300"], 0.37 - 0.44), a
assert P.adverse([cd(TS + 1000, 0.40, 0.42)], "no", TS + 950, 0.53)["60"] == round(1 - 0.41 - 0.53, 4)

# ---------- section 4: the ladder valuation and the taker fee ----------
assert near(P.taker_fee(10, 0.5), 0.175) and near(P.taker_fee(5, 0.4), 0.0840) and near(P.taker_fee(3, 0.3), 0.0441)
assert near(P.taker_fee(1, 0.01), 0.0007) and P.taker_fee(0, 0.5) == 0
assert near(P.sell_value([["0.30", "10"], ["0.40", "5"]], 8), (5 * 0.40 - 0.084) + (3 * 0.30 - 0.0441))   # best level first
assert near(P.sell_value([["0.30", "10"], ["0.40", "5"]], 100), P.sell_value([["0.30", "10"], ["0.40", "5"]], 15))   # the rest is worth 0
assert P.sell_value([], 50) == 0.0

# ---------- section 5: the SE ----------
rnd = random.Random(3)
units = [(rnd.gauss(0.05, 1.0), 50.0, "d%d" % (i % 20), "e%d" % (i % 37), "s%d" % (i % 7), rnd.random()) for i in range(600)]
m, se = P.se_units(units)
assert near(m, sum(u[0] for u in units) / sum(u[1] for u in units))
W = sum(u[1] for u in units)
def one(key):
    g = {}
    for u in units: g[key(u)] = g.get(key(u), 0.0) + u[0] - m * u[1]
    C = len(g); return (C / (C - 1) * sum(v * v for v in g.values())) ** 0.5 / W
ev = {}
for u in units: ev[u[3]] = ev.get(u[3], 0.0) + u[5]
for piece in (one(lambda u: u[2]), one(lambda u: u[3]), one(lambda u: u[4]), (sum(v * v for v in ev.values())) ** 0.5 / W):
    assert se >= piece - 1e-12, (se, piece)   # never below a one-way piece or the no-edge SE
big0 = [(u[0], u[1], u[2], u[3], u[4], 50.0) for u in units]
assert near(P.se_units(big0)[1], (sum((sum(50.0 for u in units if u[3] == e)) ** 2 for e in ev)) ** 0.5 / W)   # the no-edge SE wins
assert P.se_units([(1.0, 10.0, "d1", "e1", "s1", 0.0), (1.0, 10.0, "d2", "e2", "s1", 0.0)])[1] == float("inf")   # one series: no SE
assert P.se_units([]) == (None, None)
assert [P.band(x) for x in (0.01, 0.05, 0.06, 0.20, 0.21, 0.50, 0.51, 0.99)] == ["1-5c", "1-5c", "6-20c", "6-20c", "21-50c", "21-50c", "51-99c", "51-99c"]

# ---------- sampling on a fake exchange: universe, overlaps, long-dated, open windows, the seeded draw ----------
T0 = P.START + 1800   # 2026-11-28 00:30 La Paz
def mkprog(t, rate=1000000, **k):
    return dict(dict(market_ticker=t, start_date="2026-11-20T00:00:00Z", end_date="2027-01-01T00:00:00Z", period_reward=rate,
                     target_size_fp="1000.00", discount_factor_bps=5000, incentive_type="liquidity"), **k)
A = ["KXA-26DEC10-M%02d" % i for i in range(60)]
OV = sorted(random.Random(int(T0 // 3600)).sample(sorted(A), 40))[0]   # a market the first hour draws
progs = [mkprog(t) for t in A] + [mkprog(OV, rate=500000), mkprog(OV, rate=3000000)]   # OV has three: the lowest rate is used
progs += [mkprog("KXB-26DEC10-X"), mkprog("KXA-27JAN05-L"), mkprog("KXA-26DEC10-C"), mkprog("KXA-26NOV28-S"),
          mkprog("KXA-26DEC10-V", incentive_type="volume"), mkprog("KXA-26DEC10-F", start_date="2026-12-20T00:00:00Z")]
MK = {p["market_ticker"]: dict(ticker=p["market_ticker"], status="active", close_time="2026-12-10T05:00:00Z") for p in progs}
MK["KXA-27JAN05-L"]["close_time"] = "2027-01-05T05:00:00Z"   # long-dated: counted, never scored
MK["KXA-26DEC10-C"]["status"] = "closed"
MK["KXA-26NOV28-S"]["close_time"] = P.datetime.fromtimestamp(T0 + 5 * 3600, P.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")   # closes within 6 hours
FEE = {"KXA": "quadratic", "KXB": "quadratic_with_maker_fees"}
BOOK = dict(yes_dollars=book["yes"], no_dollars=book["no"])
calls = {"programs": 0, "books": 0, "candles": 0, "single": 0}
FAILC = set()
def kidx(t): return int(t.split("M")[-1]) if "-M" in t else -1
def fake(path, params=None, **k):
    params = params or {}
    if path == "/incentive_programs":
        calls["programs"] += not params.get("cursor"); i = int(params.get("cursor") or 0); page = progs[i * 25:(i + 1) * 25]
        return dict(incentive_programs=page, next_cursor=str(i + 1) if (i + 1) * 25 < len(progs) else "")
    if path.endswith("/candlesticks"):
        calls["candles"] += 1; t = path.split("/")[4]
        assert params["period_interval"] == 1 and params["end_ts"] - params["start_ts"] >= 3600 + 420, params
        if t in FAILC: raise RuntimeError("HTTP 500 (test)")
        if kidx(t) % 3 == 2: return dict(candlesticks=[])
        s0 = params["start_ts"] + 60
        return dict(candlesticks=[cd(s0 + 600, 0.46, 0.47)])   # YES bid 45 -> 46 (weight 0.5); NO bid 1 - 0.47 = 0.53: unchanged
    if path.startswith("/series/"): return dict(series=dict(fee_type=FEE.get(path[8:]), category="Test"))
    if path == "/markets": return dict(markets=[MK[t] for t in params["tickers"].split(",") if t in MK])
    if path.endswith("/orderbook"): calls["books"] += 1; return dict(orderbook_fp=BOOK)
    if path.startswith("/markets/") and path[9:] in MK: calls["single"] += 1; return dict(market=MK[path[9:]])
    if path == "/markets/trades":
        k_ = kidx(params["ticker"]); t0 = params["min_ts"]
        if k_ % 3 == 0: return dict(trades=[tr("no", 0.43, 5, t0 + 600)], cursor="")      # YES through, 10 minutes in
        if k_ % 3 == 1: return dict(trades=[tr("no", 0.44, 200, t0 + 300)], cursor="")    # 50 past the YES queue of 150
        return dict(trades=[], cursor="")
    raise AssertionError(path)
P.http = fake
P.sample(now=P.START - 60); assert not P.rows_of("samples") and not os.path.exists(P.path("hours.json"))   # before the window
P.sample(now=T0); ss = P.rows_of("samples")
H = P.load(P.path("hours.json"))[str(int(T0 // 3600))]
assert len(ss) == 40 and H["universe"] == 60 and H["day"] == "2026-11-28" and H["long_dated_programs"] == 1, H
assert H["skipped"] == {"markets with overlapping programs (lowest rate used)": 1, "not active": 1, "closes within 6 hours": 1,
                        "fee type not quadratic": 1}, H["skipped"]   # the volume program and the not-yet-started one are never listed
assert near(H["long_dated_usd_per_day"], round(100.0 / 42, 2)) and near(H["long_dated_total_reward"], 100.0)   # $100 over 42 days
want = sorted(random.Random(int(T0 // 3600)).sample(sorted(A), 40))
assert [s["ticker"] for s in ss] == want and calls["books"] == 40   # sorted universe, seed = the UTC epoch hour
s0 = [s for s in ss if s["ticker"] == OV]
assert s0 and s0[0]["program"]["period_reward"] == 500000   # overlapping programs: the lowest hourly rate
assert all(s["event"] == s["ticker"].rsplit("-", 1)[0] and s["series"] == "KXA" and s["category"] == "Test" for s in ss)
P.sample(now=T0 + 600); assert len(P.rows_of("samples")) == 40 and calls["programs"] == 1   # same hour: not again; programs cached
T1 = T0 + 1800   # the next clock hour: the 40 just sampled still have their window open
P.sample(now=T1); ss1 = [s for s in P.rows_of("samples") if s["hour"] == int(T1 // 3600)]
H1 = P.load(P.path("hours.json"))[str(int(T1 // 3600))]
rest = sorted(set(A) - set(want))
assert H1["universe"] == 20 and H1["skipped"]["previous sample's window still open"] == 40, H1
assert [s["ticker"] for s in ss1] == sorted(random.Random(int(T1 // 3600)).sample(rest, 20))
# a crash after the sample rows but before hours.json: the hour is not taken twice
took = P.load(P.path("hours.json")); del took[str(int(T1 // 3600))]; P.save(P.path("hours.json"), took)
P.sample(now=T1 + 60); assert len(P.rows_of("samples")) == 60
took[str(int(T1 // 3600))] = H1; P.save(P.path("hours.json"), took)
assert calls["programs"] == 1
# fills: not before the hour plus 7 minutes is over; a failed candle request is retried, not read as "no candle"
assert not P.rows_of("fills")
FAILC.add(want[1])
P.sample(now=T0 + 3600 + 419); assert not P.rows_of("fills")
P.sample(now=T0 + 3600 + 421); fl = P.rows_of("fills")
assert len(fl) == 39 and want[1] not in {r["ticker"] for r in fl}, len(fl)
FAILC.clear(); P.sample(now=T0 + 3600 + 500); fl = P.rows_of("fills")
assert len(fl) == 40 and len({(r["hour"], r["ticker"]) for r in fl}) == 40   # each sample once
FR = {r["ticker"]: r for r in fl}; SQ = {s["ticker"]: s for s in ss}
r0 = FR[[t for t in want if kidx(t) % 3 == 0][0]]; r1 = FR[[t for t in want if kidx(t) % 3 == 1][0]]; r2 = FR[[t for t in want if kidx(t) % 3 == 2][0]]
y0 = r0["sides"]["yes"]["per_q"]; n0 = r0["sides"]["no"]["per_q"]
assert [y0[q]["filled"] for q in ("10", "100", "1000")] == [5, 5, 5] and y0["100"]["t_fill"] == int(T0) + 600 and n0["100"]["filled"] == 0
assert near(y0["100"]["weight_minutes"], 9.5, 1e-3) and near(n0["100"]["weight_minutes"], 60.0, 1e-3)   # minute 9 at 0.5; NO bid unchanged
q0 = SQ[r0["ticker"]]["quote"]
for q in ("10", "100", "1000"):   # reward = hourly pool x share x weight minutes / 60 / 2
    assert near(y0[q]["reward"], q0["pool"] * q0["sides"]["yes"]["share"][q] * y0[q]["weight_minutes"] / 60 / 2, 1e-9)
    assert near(n0[q]["reward"], q0["pool"] * q0["sides"]["no"]["share"][q] * n0[q]["weight_minutes"] / 60 / 2, 1e-9)
assert near(q0["pool"], 100.0 * 3600 / (42 * 86400)) and near(y0["100"]["reward"], q0["pool"] * (100 / (Y["qual"] + 100)) * 9.5 / 120, 1e-6)
assert r0["sides"]["yes"]["adverse"] is not None and r0["sides"]["no"]["adverse"] is None
y1 = r1["sides"]["yes"]["per_q"]
assert [y1[q]["filled"] for q in ("10", "100", "1000")] == [10, 50, 50] and near(y1["100"]["weight_minutes"], 5.0, 1e-3)   # first fill 5 minutes in
y2 = r2["sides"]["yes"]["per_q"]
assert y2["100"]["filled"] == 0 and near(y2["100"]["weight_minutes"], 30.0) and near(r2["sides"]["no"]["per_q"]["100"]["weight_minutes"], 30.0)   # no candle: 0.5
# status: counts only (section 5), no reward or P&L figure
buf = io.StringIO()
with contextlib.redirect_stdout(buf): P.status()
st = buf.getvalue().lower()
assert "40 fill checks" in st and "$" not in st and "reward" not in st and "p&l" not in st and "return" not in st, st
# settle: nothing has closed yet (the sampled markets close Dec 10); then results once they have
with contextlib.redirect_stdout(io.StringIO()):
    P.settle(now=T0 + 3600); assert P.load(P.path("results.json")) == {} and not P.score_ready(now=T0 + 3600)
    for t in A: MK[t].update(result="yes" if kidx(t) % 2 else "no", status="finalized")
    MK[A[4]].update(result="scalar", status="determined")   # not final yet: asked again next time
    P.settle(now=P.SCORE_FROM)
res = P.load(P.path("results.json")); sampled = {s["ticker"] for s in P.rows_of("samples")}
assert set(res) == sampled - {A[4]} and all(r["status"] == "finalized" for r in res.values()), len(res)

# ---------- the score on synthetic records ----------
def reset():
    shutil.rmtree(P.DATA, ignore_errors=True); shutil.rmtree(P.OUT, ignore_errors=True); os.makedirs(P.DATA)
def side(price, best, share=0.2): return dict(price=price, best=best, queue=0, qual=400.0, share={"10": share / 10, "100": share, "1000": share * 5})
def world(days=21, hours=12, per=10, edge=0.0, usd=2.4, reward=0.01, results=True, fill_no=0, seed=1, marks=None, now=None, extra=None, fill_p=0.5):
    """days x hours x per sampled market-hours; YES fills of 2 contracts half the time, bought at 40c, winning with
    probability 0.40 + edge; each side's reward per hour `reward` / 2."""
    reset(); rnd = random.Random(seed); took = {}; ss = []; fl = []; res = {}
    for d in range(days):
        for h in range(hours):
            ts = P.START + d * 86400 + h * 3600 + 60; hour = int(ts // 3600)
            took[str(hour)] = dict(ts=ts, day=P.day_of(ts), universe=per, sampled=per, skipped={"not active": 1},
                                   long_dated_programs=2, long_dated_usd_per_day=5.0, long_dated_total_reward=10.0)
            for k in range(per):
                ser = "KXS%d" % (k % 5); ev = "%s-D%02dH%02d" % (ser, d, h); t = "%s-M%d" % (ev, k)
                qt = dict(sides=dict(yes=side(0.40, 0.41), no=side(0.50, 0.50)), valid=True, target=1000.0, d=0.5,
                          pool=0.1, usd_per_day=usd)
                ss.append(dict(ts=ts, hour=hour, ticker=t, series=ser, event=ev, category="C%d" % (k % 2),
                               close=P.CLOSE_MAX - 3600, program=dict(prog, start_date="2026-11-20T00:00:00Z", end_date="2027-01-01T00:00:00Z"),
                               book={}, quote=qt))
                fy = 2 if rnd.random() < fill_p else 0
                sides = {}
                for sd_, c in (("yes", fy), ("no", fill_no)):
                    sides[sd_] = dict(per_q={q: dict(filled=min(int(q), c), t_fill=ts + 600 if c else None, weight_minutes=60.0, reward=reward / 2)
                                             for q in ("10", "100", "1000")},
                                      adverse={"60": -0.01, "300": -0.02} if c else None)
                fl.append(dict(hour=hour, ticker=t, trades=1, candles=1, sides=sides))
                if results: res[t] = dict(result="yes" if rnd.random() < 0.40 + edge else "no", status="finalized")
    if extra: extra(took, ss, fl, res)
    P.save(P.path("hours.json"), took); P.add_rows("samples", ss, P.START); P.add_rows("fills", fl, P.START); P.save(P.path("results.json"), res)
    with contextlib.redirect_stdout(io.StringIO()): P.score(now=now or P.SCORE_FROM + 1, marks=marks if marks is not None else {})
    return json.load(open(os.path.join(P.OUT, "plan19_result.json")))
G = world(edge=0.30)
assert G["spread_only"]["verdict"] == "PASS" and G["with_rewards"]["verdict"] == "PASS", (G["spread_only"], G["with_rewards"])
assert G["days"] == 21 and G["filled_market_hour_sides"] >= 100 and G["events_with_fills"] >= 30 and G["contracts_valued_at_ladder"] == 0
assert G["totals"]["units"] == 21 * 12 * 10 and near(G["totals"]["capital"], 21 * 12 * 10 * 100 * 0.90, 1e-6)   # q x price, both sides
assert near(G["totals"]["reward"], 21 * 12 * 10 * 0.01, 1e-6) and G["programs_under_1_dollar"] == 0
assert G["with_rewards"]["applies"] is True and G["with_rewards"]["t_with_rewards_halved"] <= G["with_rewards"]["t"]
assert G["hours_by_day"]["2026-11-28"] == {"sampled": 12, "missed": 12} and G["hours_by_day"]["2026-12-27"] == {"sampled": 0, "missed": 24}
assert len(G["hours_by_day"]) == 30 and G["skipped_at_sample"] == {"not active": 21 * 12}
ex = G["exploratory"]
assert set(ex["by_quote_price_band"]) == {"21-50c"} and ex["by_quote_price_band"]["21-50c"]["sides"] == 2 * 21 * 12 * 10
assert ex["valid_share"] == 1.0 and set(ex["by_category"]) == {"C0", "C1"} and len(ex["by_series_top10"]) == 5
assert ex["adverse_selection"]["60"]["n"] == G["filled_market_hour_sides"] and near(ex["adverse_selection"]["300"]["mean"], -0.02)
assert ex["long_dated"]["mean_programs"] == 2 and ex["long_dated"]["mean_total_reward"] == 10.0
il = ex["illustration_25"]; assert il["median_quote_price"] == 0.50 and il["sides_funded"] == 0 and il["dollars_per_day"] == 0   # 100 x 50c > $25
assert set(ex["by_size"]) == {"10", "100", "1000"} and near(ex["by_size"]["10"]["capital"], G["totals"]["capital"] / 10, 1e-6)
md = open(os.path.join(P.OUT, "plan19_result.md"), encoding="utf-8").read()
assert "**With rewards: PASS**" in md and "**Spread alone: PASS**" in md and "Yes, eligible" in md
# scored once; not early; not with a changed plan
try: P.score(now=P.SCORE_FROM + 2); raise SystemExit("scored twice")
except SystemExit as e: assert "once" in str(e), e
assert not P.score_ready(now=P.SCORE_FROM + 2)   # the result exists: never again
os.remove(os.path.join(P.OUT, "plan19_result.json"))
try: P.score(now=P.SCORE_FROM - 1); raise SystemExit("scored early")
except SystemExit as e: assert "2026-12-29" in str(e), e
assert not P.score_ready(now=P.SCORE_FROM - 1)
real_plan = P.PLAN; P.PLAN = os.path.join(OUT, "PLAN19_changed.md"); open(P.PLAN, "w").write("changed\n")
try: P.score(now=P.SCORE_FROM + 1); raise SystemExit("scored a changed plan")
except SystemExit as e: assert "frozen hash" in str(e), e
P.PLAN = real_plan
# a losing world: FAIL, and the fills eat the rewards
B = world(edge=-0.30)
assert B["spread_only"]["verdict"] == "FAIL" and B["with_rewards"]["verdict"] == "FAIL" and not B["with_rewards"]["fills_not_eating_rewards"], B["with_rewards"]
# rewards only just pass: with rewards x 0.5 they must still pass (section 5, condition 1)
R2 = world(edge=0.0, reward=0.6, seed=4)
assert R2["spread_only"]["verdict"] == "FAIL" and R2["with_rewards"]["t"] >= 2.5
assert R2["with_rewards"]["verdict"] == ("PASS" if R2["with_rewards"]["t_with_rewards_halved"] >= 2.5 else "FAIL")
# the $1 minimum per market program: each program here is sampled once, so its estimate is reward x eligible hours
elig = (min(P.END, P.CLOSE_MAX - 3600 - P.CLOSE_GAP) - P.START) / 3600.0
S = world(edge=0.30, reward=0.9 / elig)
assert S["programs_under_1_dollar"] == S["programs"] == 21 * 12 * 10 and S["totals"]["reward"] == 0.0, S["totals"]
assert S["with_rewards"]["mean_return_per_dollar_hour"] == S["spread_only"]["mean_return_per_dollar_hour"]   # rewards under $1 contribute 0
S2 = world(edge=0.30, reward=1.1 / elig); assert S2["programs_under_1_dollar"] == 0 and S2["totals"]["reward"] > 0
def same_market(took, ss, fl, res):   # one market sampled every hour of a day: its mean hourly reward decides for all
    for s, f in zip(ss, fl):
        if s["ticker"].endswith("-M0") and s["ts"] < P.START + 86400:
            s["ticker"] = f["ticker"] = "KXS0-ONE-M0"; s["event"] = "KXS0-ONE"
            for sd_ in f["sides"].values():
                for q in sd_["per_q"].values(): q["reward"] = 0.0
    fl[0]["sides"]["yes"]["per_q"]["100"]["reward"] = 12 * 1.001 / elig   # mean 1.001/elig a sample: just over $1 for size 100
S3 = world(edge=0.30, reward=1.1 / elig, extra=same_market)
assert S3["programs"] == 21 * 12 * 10 - 11 and S3["programs_under_1_dollar"] == 0
# not testable: too few days; too many contracts valued at the ladder; a unit problem (rewards verdict only)
F = world(days=15, edge=0.30)
assert F["spread_only"]["verdict"] == "NOT TESTABLE" and F["with_rewards"]["verdict"] == "NOT TESTABLE" and F["days"] == 15
L = world(hours=11, edge=0.30)
assert L["spread_only"]["verdict"] == "NOT TESTABLE" and L["left_out"]["day with under 12 sampled hours"] == 21 * 11 * 10 and L["totals"]["units"] == 0
M = world(edge=0.30, results=False, marks={})
assert M["spread_only"]["verdict"] == "NOT TESTABLE" and M["with_rewards"]["verdict"] == "NOT TESTABLE" and M["contracts_valued_at_ladder"] == M["contracts_filled"] > 0
U = world(edge=0.30, usd=5000.0)
assert U["with_rewards"]["verdict"] == "NOT TESTABLE" and U["spread_only"]["verdict"] == "PASS" and U["with_rewards"]["unit_problem_tickers"], U["with_rewards"]
U2 = world(edge=0.30, usd=0.5); assert U2["with_rewards"]["verdict"] == "NOT TESTABLE"
# fewer than 100 filled sides, or fewer than 30 events with fills
E = world(edge=0.30, fill_p=0.03); assert E["spread_only"]["verdict"] == "NOT TESTABLE" and E["filled_market_hour_sides"] < 100, E["filled_market_hour_sides"]
def by_day(took, ss, fl, res):
    for s in ss: s["event"] = "EV-" + P.day_of(s["ts"])
E2 = world(edge=0.30, extra=by_day); assert E2["spread_only"]["verdict"] == "NOT TESTABLE" and E2["events_with_fills"] == 21 and E2["filled_market_hour_sides"] >= 100
# one series only: the series-clustered SE does not exist, so there is no t and no PASS
E3 = world(edge=0.30, per=1); assert E3["spread_only"]["se"] is None and E3["spread_only"]["t"] is None and E3["spread_only"]["verdict"] == "FAIL", E3["spread_only"]
# open positions at scoring: a YES and a NO fill of the same market-hour lock in 1 - both prices; the rest is sold into
# the ladder (all open contracts of a market and side together) minus the taker fee
def one_market(took, ss, fl, res):
    del ss[2:]; del fl[2:]; res.clear()
    for s, f in zip(ss, fl):
        s["ticker"] = f["ticker"] = "KXS0-OPEN-M0"; s["event"] = "KXS0-OPEN"
        for sd_, c in (("yes", 3), ("no", 2)):
            for q in f["sides"][sd_]["per_q"].values(): q["filled"] = c; q["reward"] = 0.0
O = world(days=1, hours=12, per=1, extra=one_market, marks={"KXS0-OPEN-M0": {"yes": [["0.45", "1"]], "no": []}})
# per hour: 2 pairs lock 2 x (1 - 0.40 - 0.50) = 0.20; 1 YES left in each of the 2 hours, 2 together into a ladder of 1 at 45c
lad_val = (0.45 - P.taker_fee(1, 0.45)) / 2
assert near(O["totals"]["fillpnl"], 2 * (0.20 + (lad_val - 0.40)), 1e-9), O["totals"]
assert O["contracts_filled"] == 10 and O["contracts_valued_at_ladder"] == 2 and O["spread_only"]["verdict"] == "NOT TESTABLE"
# settled markets follow strategy.payout: scalar and void
def settled_kinds(took, ss, fl, res):
    del ss[3:]; del fl[3:]; res.clear()
    for i, (s, f) in enumerate(zip(ss, fl)):
        for q in f["sides"]["yes"]["per_q"].values(): q["filled"] = 2; q["reward"] = 0.0
        for q in f["sides"]["no"]["per_q"].values(): q["filled"] = 0; q["reward"] = 0.0
    res[ss[0]["ticker"]] = dict(result="yes", status="settled")
    res[ss[1]["ticker"]] = dict(result="scalar", status="finalized", settlement_value_dollars="0.7000")
    res[ss[2]["ticker"]] = dict(result="void", status="finalized")
K = world(days=1, hours=12, per=1, extra=settled_kinds)
assert near(K["totals"]["fillpnl"], 2 * (1 - 0.40) + 2 * (0.70 - 0.40) + 0.0, 1e-9) and K["contracts_valued_at_ladder"] == 0, K["totals"]
# score_ready: waits for fill checks and closed markets' results, until the backstop
reset(); P.add_rows("samples", [dict(ts=P.START + 60, hour=int((P.START + 60) // 3600), ticker="KXS0-W-M0", close=P.CLOSE_MAX - 3600)], P.START)
with contextlib.redirect_stdout(io.StringIO()):
    assert not P.score_ready(now=P.SCORE_FROM + 1)   # no fill check yet
    P.add_rows("fills", [dict(hour=int((P.START + 60) // 3600), ticker="KXS0-W-M0", sides={})], P.START)
    assert not P.score_ready(now=P.SCORE_FROM + 1)   # closed, no result yet
    assert P.score_ready(now=P.SCORE_BACKSTOP)
    P.save(P.path("results.json"), {"KXS0-W-M0": dict(result="no")})
    assert P.score_ready(now=P.SCORE_FROM + 1)
print("plan19.py: all checks passed")
