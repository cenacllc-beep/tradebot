"""research/plan16.py (PLAN16: four rules for the 15-minute markets, scored once on past windows), on synthetic data.
No network. python test_plan16.py WORK OUT"""
import os, sys, json, math, random
from datetime import date, datetime, timedelta, timezone
WORK, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import plan16 as Q
P = Q.P
src = open(os.path.join(WORK, "research", "plan16.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "paper.db" not in src, "research only"
assert Q.FROZEN_FILES == ("research/PLAN16.md", "research/plan16.py", "research/plan15.py")
assert P.bytes_hash(os.path.join(WORK, "research", "PLAN16.md")) == Q.PLAN_SHA256, "PLAN16.md is the frozen text"
assert (Q.EDGE_A, Q.EDGE_B, Q.BAND, Q.RECENT_RETURNS, Q.FLOW_MINUTES, Q.FLOW_MIN_CONTRACTS, Q.FLOW_CUT, Q.FAMILY,
        Q.BOOT_BLOCK_DAYS, Q.BOOT_DRAWS, Q.PLACEBO_DRAWS, Q.SEED, Q.MIN_SIGNALS, Q.MIN_SIGNAL_DAYS, Q.FILL_DELAY) == \
       (0.04, 0.10, (0.20, 0.80), 15, 3, 50.0, 0.4, 0.025, 2, 20000, 2000, 16, 200, 20, 1), "the plan's numbers"

def ts(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()

# ---------- 1. inputs at minute k ----------
o = ts(2026, 9, 10, 12, 0)
spot = {}
for i in range(-20, 16):
    c = 100.0 + i
    spot[int(o) + 60 * i] = [c - 0.5, c + 0.2, c - 0.7, c]   # rising highs and lows
assert Q.trend(spot, o, 5) == "up"
s2 = dict(spot); s2[int(o) + 60 * 4] = [0, 104.0, 98.0, 103.0]   # minute 4's low below minute 3's
assert Q.trend(s2, o, 5) == "none"
s3 = {t: [v[0], 200 - v[1], 200 - v[2], v[3]] for t, v in spot.items()}
assert Q.trend(s3, o, 10) == "down"
s4 = dict(spot); del s4[int(o) + 60 * 9]
assert Q.trend(s4, o, 10) is None and Q.recent_sigma(s4, o, 10) is None   # missing input: no signal, counted
closes = [100.0 + i for i in range(10 - 15, 11)]
want = P.sigma_from(closes)
assert abs(Q.recent_sigma(spot, o, 10) - want) < 1e-15 and len(closes) == 16
assert Q.recent_sigma({t: [1, 1, 1, 5.0] for t in spot}, o, 5) is None   # sigma 0: no signal
# minute 2 reaches back before the open: candles 0, 1, 2 (minute 0 ends at the open) and closes -13..2
assert Q.trend(spot, o, 2) == "up" and Q.recent_sigma(spot, o, 2) is not None
def tr(t, side, n):
    return dict(created_time=datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), taker_side=side, count_fp="%.2f" % n)
trades = [tr(o + 60 * 2, "yes", 10), tr(o + 60 * 2 + 1, "yes", 99),      # at the close of minute 2: in; after: out (k=2)
          tr(o, "no", 7), tr(o - 30, "no", 5),                            # at the open / before it: out
          tr(o + 60 * 2 + 0.5, "no", 4), tr(o + 60 * 5, "yes", 3)]
assert Q.flow(trades, o, 2) == (10.0, 0.0)
assert Q.flow(trades, o, 5) == (102.0, 4.0)   # after the close of minute 2, up to the close of minute 5
assert Q.flow(trades, o, 10) == (0.0, 0.0)
w = dict(ticker="T", open=o)
dw = Q.derive_window(w, spot, trades)
assert dw["trades_ok"] and dw["k"]["5"]["sk"] == spot[int(o) + 300][3] and dw["k"]["5"]["trend"] == "up"
assert Q.derive_window(w, spot, None)["trades_ok"] is False and "yes" not in Q.derive_window(w, spot, None)["k"]["2"]
print("inputs ok")

# ---------- 2. the rules ----------
def win(q=(0.49, 0.51), strike=100.0, sk=100.0, result="yes", sig=0.001):
    keep = {str(i): [sk, sk, sk, sk] for i in P.KEEP_MINUTES}
    return dict(ticker="T", open=o, close=o + 900, strike=strike, strike_type="greater_or_equal", result=result,
                c={str(m): [q[0], q[1], 100.0] for m in range(0, 16)}, t={str(m): 20.0 for m in range(1, 16)},
                spot=dict(complete=True, sigma=sig, m=keep))
q = P.quote(win(), 5)
assert Q.edge_side(0.60, q, 0.04) == "yes" and Q.edge_side(0.54, q, 0.04) is None
assert Q.edge_side(0.38, q, 0.10) == "no" and Q.edge_side(0.42, q, 0.10) is None   # NO: (1 - p) - (1 - bid)
assert Q.decide("C", win(), dict(trend="up"), 5, True) == ("yes", False)
assert Q.decide("C", win(q=(0.85, 0.87)), dict(trend="up"), 5, True) == (None, False)    # ask above 80c
assert Q.decide("C", win(q=(0.85, 0.87)), dict(trend="down"), 5, True) == (None, False)  # NO ask 15c: below 20c
assert Q.decide("C", win(q=(0.70, 0.72)), dict(trend="down"), 5, True) == ("no", False)   # NO ask 30c
assert Q.decide("C", win(), dict(trend=None), 5, True) == (None, True)
assert Q.decide("C", win(q=(0.51, 0.51)), dict(trend="up"), 5, True) == (None, True)     # locked book: no signal
assert Q.decide("D", win(), dict(yes=40.0, no=0.0), 5, True) == (None, False)            # under 50 contracts
assert Q.decide("D", win(), dict(yes=70.0, no=30.0), 5, True) == ("yes", False)          # I = 0.4
assert Q.decide("D", win(), dict(yes=69.0, no=31.0), 5, True) == (None, False)
assert Q.decide("D", win(), dict(yes=10.0, no=90.0), 5, True) == ("no", False)
assert Q.decide("D", win(), {}, 5, True) == (None, True)
# A: S_k above the strike with a small recent sigma: RW_A high, YES signal; B needs 10 points with PLAN15's sigma
up = win(sk=100.3)
assert Q.decide("A", up, dict(sk=100.3, sig15=0.0005), 5, True) == ("yes", False)
assert Q.decide("A", up, dict(sk=100.3, sig15=None), 5, True) == (None, True)
rw = P.window_inputs(up, 5, True)["rw"]
assert rw > 0.61 and Q.decide("B", up, {}, 5, True) == ("yes", False)
assert Q.decide("B", win(sk=100.05), {}, 5, True)[0] is None
print("rules ok")

# ---------- 3. statistics ----------
days = [date(2026, 9, 1) + timedelta(days=i) for i in range(6)]
dm = {days[0]: 1.0, days[1]: -1.0, days[3]: 2.0}
p, qq = Q.boot_p(dm, days, draws=500, seed=1, level=0.025)
assert 0 <= p <= 1 and qq is not None
p_all_pos, lo = Q.boot_p({d: 1.0 for d in days}, days, draws=200, seed=1, level=0.01)
assert p_all_pos == 0.0 and lo == 1.0
fl = [dict(day=days[0], profit=0.5, flip=-0.5), dict(day=days[1], profit=0.5, flip=-0.5)]
pp = Q.placebo_p(fl, 0.5, draws=4000, seed=2)
assert abs(pp - 0.25) < 0.03, pp   # both kept their side in a quarter of the draws
assert Q.placebo_p([dict(day=days[0], profit=0.5, flip=None)], 0.5, draws=10) == 1.0   # unpaid flip keeps its side
print("statistics ok")

# ---------- 4. end to end on synthetic data, with an edge planted in C for BTC only ----------
INSP = {"inspected_ts": ts(2026, 11, 13), "confirmed": True, "spx_series": [],
        "series": {a: {"checks": {"use_reference_field": True, "fee_multiplier": 1.0, "fee_type": "quadratic"},
                       "fee_changes_parsed": []} for a in P.ASSETS}}
NDAYS = 30
period = [date(2026, 9, 1) + timedelta(days=i) for i in range(NDAYS)]
Q.find_days = lambda: period
rnd = random.Random(7)
def make(asset):
    p15, p16 = {}, {}
    for d in period:
        ws, ws16 = [], []
        for i in range(96):
            close = P.day_start(d) + 900 * (i + 1)
            op = close - 900
            pat = rnd.choice(["up", "down", "none", "none", "none"])
            if asset == "BTC" and pat != "none":
                yes = rnd.random() < (0.8 if pat == "up" else 0.2)
            else:
                yes = rnd.random() < 0.5
            keep = {str(m): [100.0, 100.0, 100.0, 100.0] for m in P.KEEP_MINUTES}
            keep["15"] = [101.0] * 4 if yes else [99.0] * 4     # Coinbase agrees with every result
            ws.append(dict(ticker="%s-%s-%d" % (asset, d, i), open=op, close=close, open_listed=op, strike=100.0,
                           strike_type="greater_or_equal", result="yes" if yes else "no",
                           c={str(m): [0.49, 0.51, 100.0] for m in range(0, 16)}, t={str(m): 30.0 for m in range(1, 16)},
                           spot=dict(complete=True, sigma=0.001, m=keep)))
            ws16.append(dict(ticker=ws[-1]["ticker"], trades_ok=True,
                             k={str(k): dict(sk=100.0, sig15=0.001, trend=pat, yes=50.0, no=50.0) for k in P.KS}))
        p15[d] = dict(asset=asset, day=str(d), windows=ws, complete=True, fee_multiplier=1.0)
        p16[d] = dict(asset=asset, day=str(d), windows=ws16, complete=True)
    return p15, p16
data = {a: make(a) for a in P.ASSETS}

Q.IDENTITY = os.path.join(OUT, "plan16_identity.json")
P.INSPECT = os.path.join(OUT, "inspect.json"); json.dump(INSP, open(P.INSPECT, "w"))
out = os.path.join(OUT, "plan16_result.json")
assert Q.score(out_path=out, data=data, insp=INSP)[0] is None   # not frozen: no score
P.identity_problems = lambda *a, **k: ["research/plan15.py"]
assert Q.freeze(root=WORK)[0] is None and not os.path.exists(Q.IDENTITY)   # PLAN15 must be frozen first
P.identity_problems = lambda *a, **k: []
rec, msg = Q.freeze(root=WORK)
assert rec and Q.identity_problems(WORK) == [], msg
assert Q.freeze(root=WORK)[0] is None   # stored once
res, verdict = Q.score(out_path=out, data=data, insp=INSP, root=WORK)
assert res, verdict
T = {x["name"]: x for x in res["tests"]}
assert len(T) == 8 and sorted(T) == sorted("%s %s" % (a, r) for a in P.ASSETS for r in Q.RULES)
assert T["BTC C"]["passed"] and T["BTC C"]["verdict"] == Q.VERDICT_PASS, T["BTC C"]
assert not T["ETH C"]["passed"] and T["ETH C"]["verdict"] == Q.VERDICT_FAIL
for n in ("BTC A", "BTC B", "BTC D", "ETH A", "ETH B", "ETH D"):
    assert T[n]["verdict"] == Q.NOT_TESTABLE and "fewer than 200" in T[n]["stats"]["not_testable"], (n, T[n]["stats"])
st = T["BTC C"]["stats"]
assert abs(st["mean_price"] - 0.51) < 1e-9 and st["signals"] == st["filled"]
assert abs(T["BTC C"]["p"] - max(st["p_t"], st["p_boot"], st["p_placebo"])) < 1e-15
assert T["BTC C"]["holm_level"] == Q.FAMILY / 8   # the strongest test is first, at 2.5% / 8
assert res["assets"]["BTC"]["agreement"] == 1.0 and res["verdict"].startswith(Q.VERDICT_PASS)
assert set(st["by_minute"]) == {"2", "5", "10"} and set(st["delayed_fills"]) == {"k+3", "k+5"}
assert "reference" in res and res["reference"]["BTC"]["stats"]["signals"] == 0
md = open(out[:-5] + ".md", encoding="utf-8").read()
assert "Verdict: lead on past data" in md and "BTC C trend" in md
assert Q.score(out_path=out, data=data, insp=INSP, root=WORK)[0] is None   # scored once
print("end to end ok:", verdict)

# a changed plan or code stops every stage
bad = os.path.join(OUT, "bad_identity.json")
json.dump(dict(identity={"research/plan16.py": "0" * 64}), open(bad, "w"))
assert Q.identity_problems(WORK, bad) == ["research/plan16.py"]
json.dump(dict(INSP, inspected_ts=1.0), open(P.INSPECT, "w"))   # PLAN15's inspect.json is part of the identity
assert Q.identity_problems(WORK) == ["research/results/plan15/inspect.json"]
json.dump(INSP, open(P.INSPECT, "w")); assert Q.identity_problems(WORK) == []

# the data guards (plan section 4): each window counted once; 10% limit; 97% agreement; D only Kalshi
c = dict(windows=96 * 10 - 50, bad_abc=46, bad_d=0, agree=860, agree_n=860)   # 50 absent + 46 = 96 of 960: 10%
assert Q.asset_guard(c, 10, "A") is None and "more than 10%" in Q.asset_guard(dict(c, bad_abc=47), 10, "C")
assert Q.asset_guard(dict(c, bad_abc=0, agree=830), 10, "B").startswith("Coinbase's up-or-down")   # 96.5%
assert Q.asset_guard(dict(c, bad_abc=500, agree=0), 10, "D") is None          # D ignores Coinbase
assert Q.asset_guard(dict(c, bad_d=46), 10, "D") is None and "Kalshi" in Q.asset_guard(dict(c, bad_d=47), 10, "D")
# a window with no result that also lacks data counts once
p15d, p16d = data["ETH"][0][period[0]], data["ETH"][1][period[0]]
w0 = dict(p15d["windows"][0], result=None); w0["spot"] = dict(w0["spot"], complete=False)
one15 = {period[0]: dict(p15d, windows=[w0] + p15d["windows"][1:])}
sg, cn = Q.rows_for("ETH", one15, {period[0]: p16d}, INSP)
assert cn["bad_abc"] == 1 and cn["no_result"] == 1 and cn["missing_spot"] == 1 and cn["bad_d"] == 1

# ---------- 5. download: a network fault never saves a day ----------
Q.DATA = os.path.join(OUT, "data16")
P.DATA = os.path.join(OUT, "data15")
d0 = period[0]
P.save_gz(P.day_path("BTC", d0), data["BTC"][0][d0])
def kalshi_fail(path, params=None):
    raise RuntimeError("giving up on %s" % path)
P.http_kalshi = kalshi_fail
P.http_coinbase = lambda path, params=None: []
Q.find_days = lambda: [d0]
logs = []
ok, msg = Q.download(log=logs.append)
assert ok and not os.path.exists(Q.day_path("BTC", d0)) and "not saved" in logs[0], (msg, logs)
calls = []
def kalshi_ok(path, params=None):
    calls.append(path)
    assert path in ("/historical/trades", "/markets/trades") and params["max_ts"] - params["min_ts"] == 960   # PLAN15's range
    return {"trades": [], "cursor": None}
P.http_kalshi = kalshi_ok
ok, msg = Q.download(log=logs.append)
assert ok and os.path.exists(Q.day_path("BTC", d0)), msg
saved = P._read_json(Q.day_path("BTC", d0))[0]
assert saved["complete"] and len(saved["windows"]) == 96 and all(x["trades_ok"] for x in saved["windows"])
assert not any(p.startswith("/portfolio") for p in calls)
print("plan16: all checks passed")
