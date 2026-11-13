"""research/plan15.py (PLAN15): Kalshi's 15-minute BTC and ETH up-or-down markets. Fake markets, candles, trades and
spot prices only; no network (sockets are blocked, and the module's two HTTP functions are replaced by fakes).
Checks:
- candle labels: Coinbase's start-of-minute label becomes the end of the minute (close and OHLC); Kalshi's
  end_period_ts is kept; Kalshi prices in all three formats (_dollars, integer cents, and the archive's dollar string
  without the suffix); a known example lands on the right decision minute;
- the fee (multiplier from the series record and its change history, failing closed when an old value is unknown),
  the random-walk chance with time left T - k - 0.5, sigma from the 60 minutes before the window, the 4-point
  signal, the fill at the ask one minute later and every no-trade case; ISO times with a non-UTC offset refused;
- no look-ahead: nothing after the close of minute k changes the inputs;
- inspect keeps metadata only and fails closed when the fee history cannot be read; freeze is stored once and
  catches a changed file;
- download (fake Kalshi and Coinbase): GET /markets with the close range and no status; compressed day files whose
  windows equal the generator's (derived spot values only, no raw Coinbase series); the find period's first day
  recorded before any price; no outcome printed; Coinbase asked one minute beyond each side, at most 300 candles;
- fit: six models, frozen with a hash, refused a second time; the ridge scale and the carry-forward switch work;
- score: refused before 2027-01-01, with a changed model file, and a second time; a planted lag edge is found (verdict
  wording, Holm levels, placebo, delayed fills fading), none on a fair market; not-testable rules (missing windows
  counted against 96 a day, spot agreement under 97%, too few signals);
- mutation guards: the bootstrap bound is read at the Holm level, Holm's step-down stops at the first failure, and
  the capacity is read at minute k + 1.
python test_plan15.py WORK OUT"""
import os, sys, shutil, json, math, random, io, contextlib, socket, gzip
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
os.environ["PAPER_DB"] = os.path.join(OUT, "unused.db")
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))


def _no_net(*a, **k):
    raise AssertionError("network used in a test")


socket.socket.connect = _no_net
socket.create_connection = _no_net
import plan7 as P7   # noqa: E402
import plan15 as P   # noqa: E402


def scenario(name):
    d = os.path.join(OUT, name)
    shutil.rmtree(d, ignore_errors=True)
    res = os.path.join(d, "res")
    os.makedirs(res)
    os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
    P.RESULTS = res
    P.DATA = os.path.join(res, "plan15")
    P.INSPECT = os.path.join(P.DATA, "inspect.json")
    P.PERIODS = os.path.join(P.DATA, "periods.json")
    P.IDENTITY = os.path.join(res, "plan15_identity.json")
    P.MODEL = os.path.join(res, "plan15_model.json")
    P.MODEL_SHA = os.path.join(res, "plan15_model.sha256")
    P.RESULT = os.path.join(res, "plan15_result.json")
    P.RESULT_MD = os.path.join(res, "plan15_result.md")
    return d


def quiet(f, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


def ts(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- a fake world ----------------
SIG = 0.0008


def ohlc_of(c):
    """The OHLC the fake Coinbase serves for a close c (open = close, high and low 0.1% away)."""
    return [c, c * 1.001, c * 0.999, c]


def sd_returns(xs):
    r = [math.log(xs[i] / xs[i - 1]) for i in range(1, len(xs))]
    m = sum(r) / len(r)
    return math.sqrt(sum((a - m) ** 2 for a in r) / (len(r) - 1))


class World(object):
    """Per asset: one continuous spot random walk (one close per minute end). Per day: windows at evenly spaced
    15-minute slots, Kalshi quotes that track the fair random-walk chance with the spot `lag` minutes old (lag 0: a
    fair market; lag 3: a planted stale price), and the result from the spot itself."""

    def __init__(self, per_day=24, lag=0, seed=1, flip_share=0.0, drop_spot_share=0.0):
        self.per_day, self.lag, self.seed = per_day, lag, seed
        self.flip_share, self.drop_spot_share = flip_share, drop_spot_share
        self.cache = {}

    def spot(self, asset, t):
        base = int(ts(2026, 8, 30))
        walk = self.cache.setdefault(("walk", asset), [30000.0 if asset == "BTC" else 2000.0])
        rnd = self.cache.setdefault(("rnd", asset), random.Random("%s-%d" % (asset, self.seed)))
        i = (int(t) - base) // 60
        while len(walk) <= i:
            walk.append(walk[-1] * math.exp(rnd.gauss(0, SIG)))
        return round(walk[i], 2)

    def day(self, asset, d):
        key = (asset, d)
        if key in self.cache:
            return self.cache[key]
        r = random.Random("%s-%s-%d" % (asset, d, self.seed))
        d0 = P.day_start(d)
        at = lambda t: self.spot(asset, t)   # noqa: E731
        step = 96 // self.per_day
        wins, raw = [], {}
        for j in range(self.per_day):
            o = d0 + j * step * 900
            c = o + 900
            s0 = at(o)
            y = at(c) > s0
            if r.random() < self.flip_share:
                y = not y
            cs, cm, tm, trades = [], {}, {}, []
            for m in range(0, 16):
                src = at(o + 60 * max(m - self.lag, 0))
                left = 15 - m - 0.5
                p = P.phi(math.log(src / s0) / (SIG * math.sqrt(left))) if left > 0 else (1.0 if src > s0 else 0.0)
                bid = max(0.01, min(0.97, round(p - 0.01, 2)))
                ask = round(bid + 0.02, 2)
                vol = float(r.randint(5, 80))
                fmt = m % 3
                if fmt == 0:     # live endpoint, dollars with the suffix
                    cs.append(dict(end_period_ts=int(o + 60 * m), yes_bid=dict(close_dollars="%.4f" % bid),
                                   yes_ask=dict(close_dollars="%.4f" % ask), volume_fp="%.2f" % vol))
                elif fmt == 1:   # integer cents
                    cs.append(dict(end_period_ts=int(o + 60 * m), yes_bid=dict(close=int(round(bid * 100))),
                                   yes_ask=dict(close=int(round(ask * 100))), volume=int(vol)))
                else:            # the archive endpoint: a dollar string without the suffix
                    cs.append(dict(end_period_ts=int(o + 60 * m), yes_bid=dict(close="%.4f" % bid),
                                   yes_ask=dict(close="%.4f" % ask), volume="%.2f" % vol))
                cm[str(m)] = [bid, ask, vol]
                if m >= 1:
                    for i in range(r.randint(1, 3)):
                        n_ = float(r.randint(1, 40))
                        trades.append(dict(trade_id="%d-%d-%d" % (o, m, i), count_fp="%.2f" % n_,
                                           created_time=iso(o + 60 * (m - 1) + 1 + i * 10)))
                        tm[str(m)] = tm.get(str(m), 0.0) + n_
            tick = "%s-%s%02d" % (P.SERIES[asset], datetime.fromtimestamp(c, timezone.utc).strftime("%y%b%d%H%M").upper(), j)
            res = "yes" if y else "no"
            spot = dict(complete=True, sigma=sd_returns([at(o + 60 * i) for i in range(-60, 1)]),
                        m={str(i): ohlc_of(at(o + 60 * i)) for i in P.KEEP_MINUTES})
            if self.drop_spot_share and r.random() < self.drop_spot_share:
                spot["complete"] = False
            wins.append(dict(ticker=tick, open=o, close=c, open_listed=o, strike=s0, strike_type="greater", result=res,
                             s0_source="reference", c=cm, t=tm, spot=spot, n_candles=len(cs), n_trades=len(trades)))
            raw[tick] = dict(market=dict(ticker=tick, close_time=iso(c), open_time=iso(o), floor_strike=s0,
                                         strike_type="greater", result=res, last_price=55, volume=123),
                             candles=cs, trades=trades)
        obj = dict(asset=asset, day=d.isoformat(), windows=wins, expected=96, complete=True, fee_multiplier=1.0)
        self.cache[key] = (obj, raw)
        return self.cache[key]

    def data(self, asset, first, n):
        return {first + timedelta(days=i): self.day(asset, first + timedelta(days=i))[0] for i in range(n)}


INSP = {"inspected_ts": ts(2026, 11, 13), "confirmed": True, "spx_series": [],
        "series": {a: {"checks": {"use_reference_field": True, "fee_multiplier": 1.0, "fee_type": "quadratic",
                                  "open_time_is_window_start": True, "fee_type_quadratic": True},
                       "fee_changes_parsed": []} for a in P.ASSETS}}

# ---------------- 1. candle labels on a known example ----------------
o = ts(2026, 11, 1, 0, 0)
assert P.coinbase_end([int(o) + 60, 1.0, 2.0, 1.5, 1.75, 3.0]) == (int(o) + 120, 1.75)   # starts 00:01 -> closes 00:02
assert P.coinbase_ohlc([int(o) + 60, 1.0, 2.0, 1.5, 1.75, 3.0]) == (int(o) + 120, [1.5, 2.0, 1.0, 1.75])
assert P.kalshi_end(dict(end_period_ts=int(o) + 120)) == int(o) + 120
km = P.kalshi_minutes([dict(end_period_ts=int(o) + 120, yes_bid=dict(close_dollars="0.41"), yes_ask=dict(close=44), volume=7),
                       dict(end_period_ts=int(o) + 180, yes_bid=dict(close="0.5600"), yes_ask=dict(close="0.5800"),
                            volume="3.00"),
                       dict(end_period_ts=int(o) + 150, yes_bid=dict(close_dollars="0.1"))], o)
assert km == {"2": [0.41, 0.44, 7.0], "3": [0.56, 0.58, 3.0]}, km   # archive's "0.5600" is dollars, not cents
# the Coinbase row starting 00:01 is "minute 2" in the derived per-window values
spot = {}
for i in range(-60, 16):
    t_, v_ = P.coinbase_ohlc([int(o) + 60 * i - 60, 99.0, 101.0, 100.0, 100.0 + i, 0])
    spot[t_] = v_
dv = P.derive_spot(spot, o)
assert dv["complete"] and dv["m"]["2"][3] == 102.0 and dv["m"]["0"][3] == 100.0 and set(dv["m"]) == {str(i) for i in P.KEEP_MINUTES}
assert abs(dv["sigma"] - sd_returns([100.0 + i for i in range(-60, 1)])) < 1e-15
del spot[int(o) + 60 * 7]   # a minute inside the window missing: not complete
assert P.derive_spot(spot, o)["complete"] is False
assert P.KEEP_MINUTES == (-3, 0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 15)
assert P.trade_minutes([dict(created_time="2026-11-01T00:01:00Z", count_fp="2.00"),     # exactly the end of minute 1
                        dict(created_time="2026-11-01T00:01:00.5Z", count=3)], o) == {"1": 2.0, "2": 3.0}
assert P.ts_of("2026-11-01T00:01:00.123456789Z") is not None and P.ts_of("2026-11-01T00:01:00+00:00") == o + 60
assert P.ts_of("2026-11-01T00:01:00-04:00") is None and P.ts_of("2026-11-01T00:01:00+02:00") is None

# ---------------- 2. fee, RW, sigma, signal, fill, quote carry-forward ----------------
assert P.fee(0.5, 1.0) == 0.02 and P.fee(0.8, 1.0) == 0.02 and P.fee(0.5, 0.5) == 0.01 and P.fee(0.99, 1.0) == 0.01
assert abs(P.rw_prob(100.0, 100.0, 0.001, 5) - 0.5) < 1e-12
assert abs(P.rw_prob(100 * math.exp(0.001 * math.sqrt(12.5)), 100.0, 0.001, 2) - P.phi(1.0)) < 1e-12   # T-k-0.5 = 12.5
assert P.sigma_from([100.0] * 61) is None and P.sigma_from([100.0, None, 101.0]) is None
assert P.signal(0.54, (0.40, 0.50)) == "yes" and P.signal(0.539, (0.40, 0.50)) is None
assert P.signal(0.36, (0.40, 0.50)) == "no" and P.signal(0.361, (0.40, 0.50)) is None   # NO ask = 1 - 0.40
w = dict(c={"3": [0.40, 0.45, 1], "4": [0.0, 0.45, 1], "5": [0.40, 1.0, 1], "6": [0.5, 0.5, 1], "7": [None, 0.5, 1]})
# the user's choices of 2026-11-13 are the frozen defaults
assert P.SPOT_AGREE_MEASURE == "ohlc15" and P.RIDGE_SCALE == "sum" and P.CARRY_FORWARD_QUOTE is True and P.CARRY_MAX_MIN == 5
P.CARRY_FORWARD_QUOTE, P.SPOT_AGREE_MEASURE = False, "close15"   # the checks below test the plain rules first
assert P.fill(w, 2, "yes", 1, 1.0) == (0.45, 0.02, None)
assert P.fill(w, 2, "no", 1, 1.0) == (0.60, 0.02, None)
assert P.fill(w, 3, "yes", 1, 1.0)[2] == "candle does not show 0 < bid < ask"
assert P.fill(w, 3, "no", 1, 1.0)[2] == "ask $1.00"
assert P.fill(w, 4, "yes", 1, 1.0)[2] == "ask $1.00"
assert P.fill(w, 5, "yes", 1, 1.0)[2] == "candle does not show 0 < bid < ask"
assert P.fill(w, 6, "no", 1, 1.0)[2] == "ask missing"
assert P.fill(w, 8, "yes", 1, 1.0)[2] == "no candle at the fill minute"
assert P.fill(w, 10, "yes", 5, 1.0)[2] == "no candle at the fill minute" and P.fill(w, 10, "yes", 6, 1.0)[2] == "after the window"
assert P.CARRY_FORWARD_QUOTE is False and P.quote(w, 9) is None
P.CARRY_FORWARD_QUOTE = True
assert P.quote(w, 9) == (None, 0.5)
P.CARRY_FORWARD_QUOTE = False
# the agreement check: strictly above for "greater", at or above for "greater_or_equal"
wa = dict(strike=100.0, strike_type="greater", spot=dict(m={"15": [99.0, 101.0, 98.0, 100.0]}))
assert P.spot_up(wa, True) is False
wa["strike_type"] = "greater_or_equal"
assert P.spot_up(wa, True) is True
P.SPOT_AGREE_MEASURE = "oc15"
assert P.spot_up(dict(wa, strike_type="greater"), True) is False and P.spot_up(dict(wa, strike=99.4), True) is True
P.SPOT_AGREE_MEASURE = "ohlc15"   # (99 + 101 + 98 + 100) / 4 = 99.5
assert P.spot_up(dict(wa, strike_type="greater", strike=99.5), True) is False and P.spot_up(dict(wa, strike=99.5), True) is True
P.SPOT_AGREE_MEASURE = "close15"
# carrying a quote forward stops after CARRY_MAX_MIN minutes
P.CARRY_FORWARD_QUOTE = True
wc = dict(c={"1": [0.40, 0.45, 1]})
assert P.quote(wc, 6) == (0.40, 0.45) and P.quote(wc, 7) is None
P.SPOT_AGREE_MEASURE = "ohlc15"   # back to the approved defaults for everything below
# fee history: a change inside the periods without an old value fails closed; with one, the old value applies before it
fi = dict(INSP, series={a: dict(INSP["series"][a]) for a in P.ASSETS})
fi["series"]["BTC"] = dict(fi["series"]["BTC"], fee_changes_parsed=[[ts(2026, 10, 1), "quadratic", 1.0, None]])
assert P.multiplier_at(fi, "BTC", ts(2026, 9, 15)) is None and P.multiplier_at(fi, "BTC", ts(2026, 10, 2)) == 1.0
assert P.fee_problem(fi, "BTC") is not None
fi["series"]["BTC"]["fee_changes_parsed"] = [[ts(2026, 10, 1), "quadratic", 1.0, 0.5]]
assert P.multiplier_at(fi, "BTC", ts(2026, 9, 15)) == 0.5 and P.fee_problem(fi, "BTC") is None
fi["series"]["BTC"]["fee_changes_parsed"] = [[ts(2027, 3, 1), "quadratic", 2.0, None]]   # scheduled after inspect
assert P.multiplier_at(fi, "BTC", ts(2026, 9, 15)) == 1.0

# ---------------- 3. no look-ahead ----------------
W = World(per_day=8, lag=3, seed=4)
obj = W.day("BTC", date(2026, 9, 3))[0]
for k in P.KS:
    for wn in obj["windows"]:
        a1 = P.window_inputs(wn, k, True)
        w2 = json.loads(json.dumps(wn))
        for m in range(k + 1, 16):
            w2["c"][str(m)] = [0.01, 0.99, 999.0]
            if str(m) in w2["spot"]["m"]:
                w2["spot"]["m"][str(m)] = [1.0, 1.0, 1.0, 1.0]
        w2["result"] = "no" if wn["result"] == "yes" else "yes"
        assert a1 == P.window_inputs(w2, k, True), (k, wn["ticker"])

# ---------------- 4. inspect, freeze ----------------
scenario("freeze")
FEE_FAIL = [False]


def fake_kalshi_meta(path, params=None):
    if path.startswith("/series/fee_changes"):
        if FEE_FAIL[0]:
            raise RuntimeError("HTTP 500 /series/fee_changes")
        return {"series_fee_change_arr": []}
    if path == "/series":
        return {"series": [{"ticker": "KXINXU15M", "title": "S&P 500 15 min"}, {"ticker": "KXBTC15M", "title": "Bitcoin"}]}
    if path.startswith("/series/"):
        return {"series": {"ticker": path.split("/")[2], "fee_type": "quadratic", "fee_multiplier": 1}}
    if path == "/markets":
        assert params.get("status") in ("open", "unopened"), params   # inspect never asks for settled records
        return {"markets": [dict(ticker="%s-X%d" % (params["series_ticker"], i), open_time="2026-11-13T12:00:00Z",
                                 close_time="2026-11-13T12:15:00Z", floor_strike=99.5, result="yes", last_price=50,
                                 yes_bid=40, yes_ask=60, volume=10, expiration_value="100.1", rules_primary="If ...")
                            for i in range(2)]}
    raise AssertionError(path)


P.http_kalshi = fake_kalshi_meta
FEE_FAIL[0] = True
(insp, msg), _ = quiet(P.inspect)
assert insp["confirmed"] is False and P.freeze()[0] is None   # fee history unreadable: fails closed
os.remove(P.INSPECT)
FEE_FAIL[0] = False
(insp, msg), _ = quiet(P.inspect)
assert insp["confirmed"], msg
blob = json.dumps(insp)
for bad in ('"result"', "last_price", "yes_bid", "expiration_value", '"volume"'):
    assert bad not in blob, bad
assert insp["series"]["BTC"]["checks"]["use_reference_field"] and insp["spx_series"] == ["KXINXU15M"]
assert P.identity_problems() == ["no identity record (run freeze first)"]
rec, msg = P.freeze()
assert rec and P.identity_problems() == [], (msg, P.identity_problems())
assert P.freeze()[0] is None and "already frozen" in P.freeze()[1]
assert P.inspect()[0] is None   # inspect.json is part of the identity once frozen
txt = open(P.INSPECT, encoding="utf-8").read()
open(P.INSPECT, "w", encoding="utf-8", newline="\r\n").write(txt + "\n")
open(P.INSPECT, "w", encoding="utf-8", newline="").write(txt.replace("\n", "\r\n"))
assert P.identity_problems() == [], "inspect.json is hashed with line endings normalized"
alt = os.path.join(OUT, "alt")
os.makedirs(os.path.join(alt, "research"))
for f in ("research/PLAN15.md", "research/plan15.py", "research/plan7.py"):
    shutil.copy(os.path.join(WORK, f), os.path.join(alt, f))
assert P.identity_problems(alt) == []
with open(os.path.join(alt, "research", "plan15.py"), "a", encoding="utf-8") as f:
    f.write("\n# changed\n")
assert P.identity_problems(alt) == ["file:research/plan15.py"], P.identity_problems(alt)
assert set(P.PINNED_PLAN7) == {"research/plan7.py:%s" % n for n in P.REUSED} and P.plan7_problems() == []

# ---------------- 5. download with fake Kalshi and Coinbase ----------------
W = World(per_day=6, lag=0, seed=9)
DAYS = (date(2026, 9, 5), date(2026, 9, 6))
calls = dict(coinbase=0, max_rows=0, spans=[])


def fake_kalshi(path, params=None):
    params = params or {}
    if path == "/historical/markets":
        return {"markets": []}
    if path == "/markets":
        if "min_close_ts" in params or params.get("series_ticker") in P.SERIES.values():
            assert "status" not in params and "min_close_ts" in params, params   # the close range only with no status
        out = []
        for a in P.ASSETS:
            if params.get("series_ticker") != P.SERIES[a]:
                continue
            for d in DAYS:
                out += [x["market"] for x in W.day(a, d)[1].values()]
        return {"markets": out}
    if path.endswith("/candlesticks"):
        t = path.split("/")[-2]
        for a in P.ASSETS:
            for d in DAYS:
                raw = W.day(a, d)[1]
                if t in raw:
                    return {"candlesticks": raw[t]["candles"]}
    if path in ("/historical/trades", "/markets/trades"):
        if path == "/historical/trades":
            return {"trades": []}
        for a in P.ASSETS:
            for d in DAYS:
                raw = W.day(a, d)[1]
                if params["ticker"] in raw:
                    return {"trades": raw[params["ticker"]]["trades"]}
    raise AssertionError(path)


def fake_coinbase(path, params=None):
    a = "BTC" if "BTC-USD" in path else "ETH"
    s = P.ts_of(params["start"])
    e = P.ts_of(params["end"])
    assert params["granularity"] == 60 and (e - s) / 60 + 1 <= 300
    calls["coinbase"] += 1
    calls["spans"].append((s, e))
    rows = []
    t = int(s)
    while t <= e:   # every bucket start in [start, end], newest first
        c = W.spot(a, t + 60)
        rows.append([t, c * 0.999, c * 1.001, c, c, 1.0])
        t += 60
    rows.sort(key=lambda r: -r[0])
    calls["max_rows"] = max(calls["max_rows"], len(rows))
    return rows


P.http_kalshi, P.http_coinbase = fake_kalshi, fake_coinbase
now = ts(2026, 11, 13, 12)
(ok, msg), out = quiet(P.download, "find", now=now, max_days=2)
assert ok, msg
per = json.load(open(P.PERIODS))
assert per["find"][0] == "2026-09-05", per   # Kalshi's history (fake) begins Sep 5: recorded before any price
for d in DAYS:
    got = P._read_json(P.day_path("BTC", d))[0]
    want = W.day("BTC", d)[0]
    assert "spot" not in got and set(got) >= {"windows", "expected", "complete"}   # no raw Coinbase series stored
    for g, x in zip(got["windows"], want["windows"]):
        assert g["c"] == x["c"] and g["t"] == x["t"] and g["strike"] == x["strike"] and g["strike_type"] == "greater"
        assert g["spot"]["m"] == x["spot"]["m"] and g["spot"]["complete"] and g["s0_source"] == "reference"
        assert abs(g["spot"]["sigma"] - x["spot"]["sigma"]) < 1e-15
        assert set(g["spot"]["m"]) == {str(i) for i in P.KEEP_MINUTES}
    assert len(got["windows"]) == len(want["windows"]) == 6
    assert gzip.open(P.day_path("BTC", d)).read(2)
assert not os.path.exists(P.day_path("ETH", DAYS[0]))   # --max-days counts across assets
assert " yes" not in out and "result" not in out and calls["max_rows"] <= 300, out
spans = sorted(calls["spans"])
assert all(b[0] <= a[1] - 60 for a, b in zip(spans, spans[1:]) if b[0] - a[1] < 3600), "requests overlap by a minute"
assert "2 asset-days saved" in msg
(ok, msg), out = quiet(P.download, "check", now=ts(2026, 11, 2, 3))   # Nov 1 not settled long enough yet
assert ok and "0 asset-days saved" in msg and not os.path.exists(P.day_path("BTC", date(2026, 11, 1))), msg

# ---------------- 6. fit, score: planted edge ----------------
d = scenario("edge")
P.http_kalshi = fake_kalshi_meta
quiet(P.inspect)
assert P.freeze()[0]
P.WINDOWS_PER_DAY = 24   # the fake world lists 24 windows a day
WE = World(per_day=24, lag=3, seed=21)
find = {a: WE.data(a, date(2026, 9, 1), 25) for a in P.ASSETS}
check = {a: WE.data(a, date(2026, 11, 1), 30) for a in P.ASSETS}
(model, msg), _ = quiet(P.fit, data=find, insp=INSP)
assert model and all(len(model["models"][a]) == 3 for a in P.ASSETS), msg
m2 = model["models"]["BTC"]["10"]
assert len(m2["coef"]) == len(P.INPUTS) == 8 and m2["n"] > 0 and "failed" not in m2 and model["ridge_scale"] == "sum"
assert quiet(P.fit, data=find, insp=INSP)[0][0] is None
rows10 = P.fit_rows(find["BTC"], 10, True)
Z = [r[2] for r in rows10]
mu, sd = P.standardise(Z)
Z = [[(v - m) / s for v, m, s in zip(x, mu, sd)] for x in Z]
Y = [r[3] for r in rows10]
b_sum = P.fit_ridge_logit(Z, Y)[1]
P.RIDGE_SCALE = "mean"
b_mean = P.fit_ridge_logit(Z, Y)[1]
P.RIDGE_SCALE = "sum"
assert sum(x * x for x in b_mean) < sum(x * x for x in b_sum)   # the mean scale shrinks n times harder
assert P.score(today=date(2026, 12, 31), data=check, insp=INSP)[0] is None   # before the check period ends
mp = P.MODEL
saved = open(mp, encoding="utf-8").read()
open(mp, "w", encoding="utf-8").write(saved.replace('"ridge": 1.0', '"ridge": 2.0'))
r, msg = P.score(today=date(2027, 1, 2), data=check, insp=INSP)
assert r is None and "hash" in msg, msg
open(mp, "w", encoding="utf-8").write(saved)
assert "fee multiplier unknown" in P.score(today=date(2027, 1, 2), data=check, insp=dict(
    INSP, series=dict(INSP["series"], ETH=dict(INSP["series"]["ETH"],
                                                fee_changes_parsed=[[ts(2026, 10, 20), "quadratic", 1.0, None]]))))[1]
(r, msg), _ = quiet(P.score, today=date(2027, 1, 2), data=check, insp=INSP)
assert r, msg
assert r["verdict"].startswith(P.VERDICT_PASS), r["verdict"]
assert r["settings"]["placebo_seed"] == 15 and r["settings"]["boot_seed"] == 15
tests = r["tests"]
assert len(tests) == 12
ranks = sorted(tests, key=lambda x: x["holm_rank"])
for i, x in enumerate(ranks):
    assert abs(x["holm_level"] - 0.025 / (12 - i)) < 1e-15
rw10 = [x for x in tests if x["name"] == "BTC k=10 RW"][0]
assert rw10["passed"] and rw10["verdict"] == P.VERDICT_PASS, rw10
assert rw10["checks"]["placebo_share"] <= rw10["holm_level"] and rw10["checks"]["boot_low"] > 0
late = rw10["stats"]["delayed_fill_placebo"]
assert late["k+5"]["mean"] < rw10["stats"]["mean"], late   # the planted stale price fades with delay
assert rw10["stats"]["capacity_median"] is not None and "upper bound" in rw10["stats"]["capacity_note"]
assert r["assets"]["BTC"]["agreement"] == 1.0 and r["assets"]["BTC"]["testable"]
assert r["assets"]["BTC"]["counts"]["expected"] == 24 * 30 and r["assets"]["BTC"]["counts"]["missing"] == 0
md = open(P.RESULT_MD, encoding="utf-8").read()
assert P.VERDICT_PASS in md and "Holm" in md and '"placebo_seed": 15' in md
assert os.path.exists(P.offsite_path(P.RESULT)) and os.path.exists(P.offsite_path(P.MODEL))
assert P.score(today=date(2027, 1, 2), data=check, insp=INSP)[0] is None   # once
os.remove(P.RESULT); os.remove(P.RESULT_MD)
assert "already scored" in P.score(today=date(2027, 1, 2), data=check, insp=INSP)[1]   # the off-folder copy counts

# ---------------- 7. mutation guards ----------------
# (a) the capacity is the contracts traded in minute k + 1
rows5, _ = P.evaluate("BTC", 5, {date(2026, 11, 1): check["BTC"][date(2026, 11, 1)]}, INSP, model)
caps = [(r_["ticker"], tr["capacity"]) for _, r_ in rows5 for tr in r_["trades"].values()]
assert caps
byt = {w_["ticker"]: w_ for w_ in check["BTC"][date(2026, 11, 1)]["windows"]}
assert all(c_ == byt[t_]["t"].get("6", 0.0) for t_, c_ in caps)
assert any(byt[t_]["t"].get("6") != byt[t_]["t"].get("5") for t_, _ in caps)


def synth(name, days, wins, losses, win_price, loss_price, flip_price, noise, seed):
    """A synthetic test for holm(): per day `wins` YES trades that win at win_price and `losses` that lose at
    loss_price; the flipped side costs flip_price."""
    rn = random.Random(seed)
    filled = []
    for i in range(days):
        dd = date(2026, 11, 1) + timedelta(days=i)
        for j in range(wins + losses):
            win = j < wins
            pr = (win_price if win else loss_price) + rn.uniform(-noise, noise)
            tr = dict(side="yes", fills={1: (pr, 0.0, None)}, flip=(flip_price, 0.0, None), capacity=10.0)
            rr = dict(y=1.0 if win else 0.0)
            filled.append((dd, P.profit("yes", pr, 0.0, rr["y"]), rr, tr))
    ser = [v for _, v in P.day_series([(d_, p_) for d_, p_, _, _ in filled])]
    m_, se_ = P7.mean_se(ser)
    st = dict(mean=m_, se=se_, t=m_ / se_, df=len(ser) - 1, p=P.p_one_sided(m_ / se_, len(ser) - 1))
    return dict(name=name, stats=st, filled=filled, series=ser)


fill_nt = [dict(name="z%02d" % i, stats=dict(not_testable="few"), filled=[], series=[]) for i in range(10)]
# A: a very high t, but its losers would have won flipped cheaply: the placebo beats it -> A fails at rank 1
A = synth("A", 30, 5, 5, 0.5, 0.1, 0.01, 0.002, 1)
# B: a clear edge that passes on its own
B = synth("B", 30, 6, 4, 0.45, 0.3, 0.6, 0.08, 2)
alone = P.holm([dict(B, stats=dict(B["stats"]))] + [dict(x) for x in fill_nt] + [dict(name="z99", stats=dict(not_testable="few"), filled=[], series=[])])
b1 = [x for x in alone if x["name"] == "B"][0]
assert b1["holm_rank"] == 1 and b1["passed"], b1.get("checks")
both = P.holm([dict(A, stats=dict(A["stats"])), dict(B, stats=dict(B["stats"]))] + [dict(x) for x in fill_nt])
a2, b2 = [x for x in both if x["name"] == "A"][0], [x for x in both if x["name"] == "B"][0]
assert a2["holm_rank"] == 1 and not a2["passed"] and a2["checks"]["t_ok"] and not a2["checks"]["placebo_ok"]
assert b2["holm_rank"] == 2 and b2["checks"]["t_ok"] and b2["checks"]["boot_ok"] and b2["checks"]["placebo_ok"]
assert not b2["passed"] and b2["verdict"] == P.VERDICT_FAIL   # Holm stops at A's failure
# (b) the bootstrap bound is read at the test's Holm level, not at 2.5%
ms = P7.boot_means(B["series"], block=2, n=20000, seed=15)
assert b2["checks"]["boot_low"] == P7.boot_interval(ms, b2["holm_level"], 1 - b2["holm_level"])[0]
assert b2["checks"]["boot_low"] != P7.boot_interval(ms, 0.025, 0.975)[0]
assert b2["checks"]["t_cut"] == max(2.0, P7.t_quantile(b2["holm_level"], B["stats"]["df"]))

# ---------------- 8. fair market: no edge ----------------
scenario("null")
P.http_kalshi = fake_kalshi_meta
quiet(P.inspect)
assert P.freeze()[0]
WN = World(per_day=24, lag=0, seed=33)
quiet(P.fit, data={a: WN.data(a, date(2026, 9, 1), 25) for a in P.ASSETS}, insp=INSP)
(r, msg), _ = quiet(P.score, today=date(2027, 1, 2), data={a: WN.data(a, date(2026, 11, 1), 30) for a in P.ASSETS},
                    insp=INSP)
assert r and r["verdict"] == P.VERDICT_FAIL, msg
assert all(not x["passed"] for x in r["tests"])
assert any(x["verdict"] == P.NOT_TESTABLE for x in r["tests"])   # a fair 2c market rarely leaves 4 points

# ---------------- 9. not testable: spot agreement, missing data ----------------
scenario("agree")
P.http_kalshi = fake_kalshi_meta
quiet(P.inspect)
assert P.freeze()[0]
WA = World(per_day=24, lag=3, seed=5, flip_share=0.06)
quiet(P.fit, data={a: WA.data(a, date(2026, 9, 1), 25) for a in P.ASSETS}, insp=INSP)
(r, msg), _ = quiet(P.score, today=date(2027, 1, 2), data={a: WA.data(a, date(2026, 11, 1), 25) for a in P.ASSETS},
                    insp=INSP)
assert r and r["verdict"] == P.VERDICT_FAIL and not r["assets"]["BTC"]["testable"], msg
assert "97%" in r["assets"]["BTC"]["not_testable"] and all(x["verdict"] == P.NOT_TESTABLE for x in r["tests"])
assert P.asset_testable(dict(windows=100, expected=100, missing=11, agree=100, agree_n=100))[0] is False
assert P.asset_testable(dict(windows=100, expected=100, missing=10, agree=97, agree_n=100))[0] is True
assert P.asset_testable(dict(windows=24, expected=96, missing=72, agree=24, agree_n=24))[0] is False   # absent windows count
# with the real 96 a day, a 24-window day is mostly missing: the asset is not testable
scenario("absent")
P.http_kalshi = fake_kalshi_meta
quiet(P.inspect)
assert P.freeze()[0]
P.WINDOWS_PER_DAY = 96
quiet(P.fit, data={a: WE.data(a, date(2026, 9, 1), 25) for a in P.ASSETS}, insp=INSP)
(r, msg), _ = quiet(P.score, today=date(2027, 1, 2), data={a: WE.data(a, date(2026, 11, 1), 30) for a in P.ASSETS},
                    insp=INSP)
assert r and not r["assets"]["BTC"]["testable"] and "10%" in r["assets"]["BTC"]["not_testable"], r["assets"]["BTC"]
assert r["assets"]["BTC"]["counts"]["absent"] == 72 * 30 and r["verdict"] == P.VERDICT_FAIL
P.WINDOWS_PER_DAY = 24
WM = World(per_day=12, lag=3, seed=6, drop_spot_share=0.2)
rows, counts = P.evaluate("BTC", 5, WM.data("BTC", date(2026, 11, 1), 3), INSP, None)
assert counts["missing_spot"] > 0 and counts["windows"] == 36 and len(rows) == 36 - counts["missing_spot"]
st, _, _ = P.rule_stats(rows, "RW")
assert "not_testable" in st   # 3 days, few signals

print("PLAN15 tests passed")
