"""research/live15.py (PLAN15F, live PAPER bets on the 15-minute markets), on fake Kalshi and Coinbase answers and a
fake clock. No network. python test_live15.py WORK OUT"""
import os, sys, math, json
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
os.environ["LIVE15_DB"] = os.path.join(OUT, "live15.db"); os.environ["LIVE15_LOG"] = os.path.join(OUT, "live15.log")
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import live15 as L
P = L.P
src = open(os.path.join(WORK, "research", "live15.py"), encoding="utf-8").read()
assert "import live" not in src.replace("import live15", "") and "paper.db" not in src.split('"""', 2)[2], "live15 must not touch live.py or paper.db"
assert "/portfolio" not in src, "live15 must never call an order endpoint"
assert L.KS == (2, 5, 10) and L.EDGE == 0.04

# order book: Kalshi's documented shape (dollar strings) and the older one (cents)
assert L.asks({"orderbook_fp": {"yes_dollars": [["0.4100", "5.00"], ["0.4400", "2.00"]], "no_dollars": [["0.5200", "3.00"]]}}) == (0.48, 3.0, 0.56, 2.0)
assert L.asks({"orderbook": {"yes": [[41, 5], [44, 2]], "no": [[52, 3]]}}) == (0.48, 3.0, 0.56, 2.0)
assert L.asks({"orderbook": {"yes": [[1, 5]], "no": []}}) == (None, 0.0, 0.99, 5.0)   # a 1c level in the older shape
assert L.asks({"orderbook_fp": {"yes_dollars": [], "no_dollars": None}}) == (None, 0.0, None, 0.0)
# the rule: model minus the ask at least 4 points; one contract only if one is for sale
assert L.decide(0.60, 0.55, 3, 0.47, 3) == ("yes", 0.55, "filled")
assert L.decide(0.58, 0.55, 3, 0.47, 3) == (None, None, "no signal")
assert L.decide(0.40, 0.70, 3, 0.55, 3) == ("no", 0.55, "filled")
assert L.decide(0.60, 0.55, 0, 0.47, 3)[2].startswith("no fill")
assert L.decide(0.60, None, 0, None, 0) == (None, None, "no signal")
print("rule ok")

# a fake world: one BTC window opening at T0, ETH window missing its reference price
T0 = 1794600000.0 - (1794600000.0 % 900)
clock = [T0 + 60]
L.now = lambda: clock[0]
L.time.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
spot = {}
DELAY = [0]
for i in range(-70, 16):   # a steady climb: BTC ends minute k well above the reference
    spot[int(T0 + 60 * i)] = 68000.0 * math.exp(0.0004 * i + (0.0003 if i % 2 else -0.0003))
calls = []
def kalshi(path, params=None):
    calls.append(path)
    if path == "/markets":
        s = params["series_ticker"]
        o = datetime_iso(T0); c = datetime_iso(T0 + 900)
        if s == "KXBTC15M":
            return {"markets": [dict(ticker="KXBTC15M-W1", open_time=o, close_time=c, floor_strike=68000.0, strike_type="greater_or_equal"),
                                dict(ticker="KXBTC15M-W2", open_time=datetime_iso(T0 + 900), close_time=datetime_iso(T0 + 1800), floor_strike=None)]}
        return {"markets": [dict(ticker="KXETH15M-W1", open_time=o, close_time=c, floor_strike=None)]}
    if path.startswith("/series/"):
        return {"series": dict(fee_type="quadratic", fee_multiplier=1)}
    if path.endswith("/orderbook"):
        return {"orderbook_fp": {"yes_dollars": [["0.5000", "10.00"]], "no_dollars": [["0.4000", "10.00"]]}}   # YES ask 0.60, NO ask 0.50
    if path.startswith("/markets/"):
        return {"market": dict(result="yes")}
    raise AssertionError(path)
from datetime import datetime, timezone
def datetime_iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def coinbase(path, params):
    s = int(datetime.strptime(params["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    e = int(datetime.strptime(params["end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    out = []
    for end, v in spot.items():
        start = end - 60
        if s <= start <= e and end + DELAY[0] <= clock[0]:   # a candle appears DELAY seconds after its minute ends
            out.append([start, v * 0.999, v * 1.001, v, v, 1.0])
    return sorted(out, reverse=True)
P.http_kalshi = kalshi; P.http_coinbase = coinbase

L.tick()
c = L.db(); bets = L.rows(c)
btc = [b for b in bets if b["asset"] == "BTC"]
assert [b["k"] for b in btc] == [2, 5, 10], [(b["k"], b["status"], b["note"]) for b in btc]
eth = [b for b in bets if b["asset"] == "ETH"]
assert [b["k"] for b in eth] == [2, 5, 10] and all(b["status"] == "missed" and "reference" in b["note"] for b in eth), eth
for b in btc:
    want = P.rw_prob(spot[int(T0 + 60 * b["k"])], 68000.0, b["sigma"], b["k"])
    assert abs(b["p_up"] - want) < 1e-12 and b["yes_ask"] == 0.6 and b["no_ask"] == 0.5
    if b["status"] == "open":
        assert b["side"] == "yes" and b["price"] == 0.6 and b["fee"] == P.fee(0.6, 1.0)
assert any(b["status"] == "open" for b in btc), [(b["k"], round(b["p_up"], 3)) for b in btc]
assert clock[0] <= T0 + 60 + L.RUN_LIMIT and clock[0] >= T0 + 600   # followed to minute 10, within the run limit
print("tick ok:", [(b["k"], b["status"], round(b["p_up"], 3)) for b in btc])

# the same window again: nothing doubled
L.tick(); assert len(L.rows(L.db())) == len(bets)
# settlement after the close
clock[0] = T0 + 900 + L.SETTLE_AFTER + 1
n = L.settle(L.db()); s = L.stats(L.rows(L.db()))
op = [b for b in btc if b["status"] == "open"]
assert n == len(op) and s["settled"] == len(op) and abs(s["net"] - sum(1 - 0.6 - P.fee(0.6, 1.0) for _ in op)) < 1e-9
print("settle ok:", L.summary(L.db()))

# a run that starts too late records misses, places nothing
c.close(); L.DB = os.path.join(OUT, "live15b.db")
clock[0] = T0 + 60 * 12
L.tick(); late = L.rows(L.db())
assert late and all(b["status"] == "missed" for b in late), [(b["k"], b["status"]) for b in late]
assert not any(p.startswith("/portfolio") for p in calls)

# a window that asks "below the reference" is skipped (the model reads "above"); recorded as missed
BOOK = {}
def kalshi2(path, params=None):
    if path == "/markets":
        return {"markets": [dict(ticker=params["series_ticker"] + "-W3", open_time=datetime_iso(T0), close_time=datetime_iso(T0 + 900),
                                 floor_strike=68000.0, strike_type="less")]}
    return kalshi(path, params)
P.http_kalshi = kalshi2; L.DB = os.path.join(OUT, "live15c.db"); clock[0] = T0 + 60
L.tick(); r = L.rows(L.db())
assert len(r) == 6 and all(b["status"] == "missed" and "strike type" in b["note"] for b in r), r

# an order book that arrives too late is a miss, not a bet on an old model price
def kalshi3(path, params=None):
    if path.endswith("/orderbook"):
        clock[0] += 90
    return kalshi(path, params)
P.http_kalshi = kalshi3; L.DB = os.path.join(OUT, "live15d.db"); clock[0] = T0 + 60
L.tick(); r = [b for b in L.rows(L.db()) if b["asset"] == "BTC"]
assert r and r[0]["k"] == 2 and r[0]["status"] == "missed" and "too late" in r[0]["note"] and r[0]["book_ts"], r[0]
assert not any(b["status"] == "open" for b in r)

# void and scalar results follow the project's rule (strategy.payout): void = minus the fee; scalar pays its value
P.http_kalshi = kalshi; L.DB = os.path.join(OUT, "live15e.db"); clock[0] = T0 + 60
L.tick(); c = L.db(); op = [b for b in L.rows(c) if b["status"] == "open"]
assert op
def kalshi_void(path, params=None):
    if path.startswith("/markets/") and not path.endswith("/orderbook"):
        return {"market": dict(result="void", status="finalized")}
    return kalshi(path, params)
P.http_kalshi = kalshi_void; clock[0] = T0 + 900 + L.SETTLE_AFTER + 1
assert L.settle(c) == len(op)
assert all(b["result"] == "void" and abs(b["pnl"] + b["fee"]) < 1e-9 for b in L.rows(c) if b["status"] == "settled")
c.close()

# the kill switch stops the run before anything is read or written
import core
calls.clear(); core.kill_file = lambda: "KILL"; L.DB = os.path.join(OUT, "live15f.db")
L.tick(); assert not [x for x in calls if x != "/markets/KXBTC15M-W1"] and not L.rows(L.db())   # no bet; settling only
core.kill_file = lambda: (_ for _ in ()).throw(OSError("unreadable"))
assert L.halted(), "a failed kill-switch check halts (fail closed)"
# Coinbase's candles come out about 46 s after the minute (seen on the first live run): both assets are still decided
def kalshi_both(path, params=None):
    if path == "/markets":
        s = params["series_ticker"]
        return {"markets": [dict(ticker=s + "-W9", open_time=datetime_iso(T0), close_time=datetime_iso(T0 + 900),
                                 floor_strike=68000.0, strike_type="greater_or_equal")]}
    return kalshi(path, params)
core.kill_file = lambda: None
P.http_kalshi = kalshi_both; DELAY[0] = 46; L.DB = os.path.join(OUT, "live15g.db"); clock[0] = T0 + 60
L.tick(); r = L.rows(L.db())
assert sorted((b["asset"], b["k"]) for b in r) == [("BTC", 2), ("BTC", 5), ("BTC", 10), ("ETH", 2), ("ETH", 5), ("ETH", 10)], r
assert not [b for b in r if b["status"] == "missed"], [(b["asset"], b["k"], b["note"]) for b in r]
assert all(46 <= b["book_ts"] - (T0 + 60 * b["k"]) <= L.LATE for b in r)
DELAY[0] = 0

# the dashboard panel: a "not started yet" note on the PC before the first run, nothing on the cloud runner
sys.path.insert(0, WORK)
import dashboard as D
os.environ["LIVE15_DB"] = os.path.join(OUT, "none.db")
os.environ.pop("GITHUB_ACTIONS", None)
h = D.live15_section(); assert "Not started yet" in h and "tasks\\install_live15.cmd" in h and "\\\\" not in h, h
os.environ["GITHUB_ACTIONS"] = "true"; assert D.live15_section() == ""
os.environ.pop("GITHUB_ACTIONS")
os.environ["LIVE15_DB"] = os.path.join(OUT, "live15.db"); assert "Paper bets" in D.live15_section()
print("live15: all checks passed")
