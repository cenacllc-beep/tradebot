"""research/plan20.py (PLAN20: cheap sides of every Kalshi 15-minute series), on synthetic data. No network.
python test_plan20.py WORK OUT"""
import os, sys, json, math, random, itertools, tempfile
from datetime import date, timedelta
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])   # a fresh folder each run
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import plan20 as Q
P = Q.P
Q.RESULTS = os.path.join(OUT, "results")
Q.DATA = os.path.join(OUT, "data", "plan20")
os.makedirs(Q.RESULTS, exist_ok=True)

src = open(os.path.join(WORK, "research", "plan20.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "paper.db" not in src and "live.db" not in src, \
    "research only"
assert "coinbase" not in src.lower().replace("no coinbase", ""), "Kalshi only"
assert P.bytes_hash(os.path.join(WORK, "research", "PLAN20.md")) == Q.PLAN_SHA256, "PLAN20.md is the frozen text"
assert Q.MINUTES == tuple(range(1, 14)) and Q.LAST_CANDLE == 14 and Q.CHEAP == (0.01, 0.10) and Q.MARGIN == 0.01
assert len(Q.STRENGTHS) == 13 and abs(Q.STRENGTHS[0] - 1e-4) < 1e-18 and abs(Q.STRENGTHS[-1] - 100) < 1e-9
assert all(abs(math.log10(Q.STRENGTHS[i + 1]) - math.log10(Q.STRENGTHS[i]) - 0.5) < 1e-9 for i in range(12))
assert Q.FOLDS == 5 and Q.BOOT_BLOCK_DAYS == 2 and Q.BOOT_DRAWS == 10000 and Q.PLACEBO_DRAWS == 4000
assert (Q.MIN_BETS, Q.MIN_DAYS) == (300, 30) and Q.TESTED == ("crypto", "metals", "energy", "fx")
assert [round(x, 6) for x in Q.HOLM_LEVELS] == [0.00625, 0.008333, 0.0125, 0.025]
assert Q.FIT_PERIOD == (date(2026, 6, 1), date(2026, 7, 31)) and Q.SCORE_PERIOD == (date(2026, 8, 1), date(2026, 10, 31))
assert Q.HARD_END == date(2026, 11, 1)

NOV1 = Q.lapaz_start(date(2026, 11, 1))
QUIET = lambda *_: None   # noqa: E731
assert NOV1 == 1793505600.0                                  # 2026-11-01 04:00 UTC = midnight La Paz
assert Q.allowed_close(NOV1 - 1) and not Q.allowed_close(NOV1) and not Q.allowed_close(NOV1 + 86400 * 4)
assert not Q.allowed_close(Q.lapaz_start(date(2026, 6, 1)) - 1) and Q.allowed_close(Q.lapaz_start(date(2026, 6, 1)))

# ---------- 1. groups ----------
for t, title, g in (("KXBTC15M", "", "btceth"), ("KXETH15M", "", "btceth"), ("KXSOL15M", "", "crypto"),
                    ("KXXRP15M", "", "crypto"), ("KXGOLD15M", "", "metals"), ("KXSILVER15M", "", "metals"),
                    ("KXWTI15M", "", "energy"), ("KXEURUSD15M", "", "fx"), ("KXUSDJPY15M", "", "fx"),
                    ("KXINX15M", "S&P 500 up or down", "other"), ("KXBITCOIN15M", "Bitcoin up or down", "btceth"),
                    ("KXFOO15M", "Crude oil price in 15 minutes", "energy"), ("KXBAR15M", "Gold price", "metals")):
    assert Q.group_of(t, title)[0] == g, (t, Q.group_of(t, title))
print("groups ok")

# ---------- 2. candles: indexing and the NO side ----------
O = int(Q.lapaz_start(date(2026, 6, 10)) + 3600 * 5)


def kc(m, yb, ya, vol=1, oi=100, cents=False, o=O):
    blk = (lambda v: dict(close=int(round(v * 100)), high=int(round(v * 100)), low=int(round(v * 100)))) if cents else \
        (lambda v: dict(close_dollars="%.4f" % v, high_dollars="%.4f" % (v + 0.01), low_dollars="%.4f" % (v - 0.005)))
    return dict(end_period_ts=o + 60 * m, yes_bid=blk(yb), yes_ask=blk(ya), price=dict(close_dollars="%.4f" % ya),
                volume_fp=str(vol), open_interest_fp=str(oi))


cs = [kc(m, 0.02, 0.03) for m in range(0, 16)] + [dict(kc(3, 0.5, 0.6), end_period_ts=O + 60 * 3 + 30)]
pc = Q.parse_candles(cs, O)
assert sorted(int(k) for k in pc) == list(range(1, 15)), "candle m ends at open + 60 m; only 1..14 kept"
assert pc["3"][Q.YB] == 0.02 and pc["3"][Q.YA] == 0.03, "a candle not on a minute boundary is ignored"
assert abs(pc["5"][Q.YAH] - 0.04) < 1e-12 and abs(pc["5"][Q.YBL] - 0.015) < 1e-12 and pc["5"][Q.VOL] == 1.0 and pc["5"][Q.OI] == 100.0
pcc = Q.parse_candles([kc(2, 0.95, 0.97, cents=True)], O)
assert pcc["2"][Q.YB] == 0.95 and pcc["2"][Q.YA] == 0.97, "integer cents read as dollars"
c = [0.95, 0.97, 0.96, 0.93, 0.98, 0.96, 0.97, 5.0, 10.0]
b, a, h, l = Q.side_prices(c, "no")
assert abs(b - 0.03) < 1e-9 and abs(a - 0.05) < 1e-9 and abs(h - 0.07) < 1e-9 and abs(l - 0.04) < 1e-9, "NO = 1 - YES legs"
assert Q.side_prices(c, "yes") == (0.95, 0.97, 0.98, 0.96)
f = Q.features({"1": c}, "no", 1, dict(open=O, series="KXSOL15M", group="crypto"))
assert abs(f["ask"] - 0.05) < 1e-9 and abs(f["spread"] - 0.02) < 1e-9 and abs(f["high"] - 0.07) < 1e-9 and abs(f["low"] - 0.04) < 1e-9
print("candles ok")

# ---------- 3. features: no look-ahead ----------
rnd = random.Random(5)


def rcandle(r):
    yb = r.choice([None, round(r.uniform(0.0, 0.95), 2)])
    ya = None if yb is None and r.random() < 0.5 else round(min(1.0, (yb or 0) + r.uniform(0.01, 0.1)), 2)
    return [yb, ya, yb, None if yb is None else yb - 0.01, ya, None if ya is None else ya - 0.01, ya,
            float(r.randint(0, 50)), float(r.randint(0, 900))]


for trial in range(200):
    full = {str(m): rcandle(rnd) for m in range(1, 15) if rnd.random() < 0.85}
    meta = dict(open=O + 900 * trial, series="KXSOL15M", group="crypto")
    for m in Q.MINUTES:
        for side in ("yes", "no"):
            base = Q.features(full, side, m, meta)
            alt = {k: v for k, v in full.items() if int(k) <= m}
            for k in range(m + 1, 15):
                if rnd.random() < 0.7:
                    alt[str(k)] = rcandle(rnd)
            assert Q.features(alt, side, m, meta) == base, "a candle after m changed the features at m"
            alt[str(m + 1)] = [0.5, 0.51, 0.9, 0.1, 0.9, 0.1, 0.5, 1e6, 1e6]
            assert Q.features(alt, side, m, meta) == base
# carry-forward for features, worked example
cs2 = {"1": [0.20, 0.25, 0.21, 0.19, 0.30, 0.24, 0.25, 10.0, 50.0], "2": [0.04, 0.06, 0.05, 0.03, 0.07, 0.05, 0.06, 5.0, 60.0],
       "4": [0.02, 0.05, 0.03, 0.01, 0.06, 0.04, 0.05, 20.0, 80.0]}
f = Q.features(cs2, "yes", 5, dict(open=O, series="X", group="crypto"))     # candle 5 missing: minute 4 carried
assert f["ask"] == 0.05 and abs(f["d1"] - 0.0) < 1e-12 and abs(f["d3"] - (0.05 - 0.06)) < 1e-12 and f["d5"] == 0.0
assert f["minutes_left"] == 10.0 and abs(f["high"] - 0.30) < 1e-12 and abs(f["low"] - 0.04) < 1e-12
assert abs(f["pos"] - (0.05 - 0.04) / (0.30 - 0.04)) < 1e-12 and abs(f["spread"] - 0.03) < 1e-12
assert abs(f["vol_ratio"] - 20.0 / 35.0) < 1e-12 and f["oi_d3"] == 80.0 - 60.0 and f["hhhl"] == 0.0
hh = {"1": [0.01, 0.02, 0.0, 0.0, 0.03, 0.01, 0, 0, 0], "2": [0.02, 0.03, 0, 0, 0.04, 0.02, 0, 0, 0], "3": [0.03, 0.04, 0, 0, 0.05, 0.03, 0, 0, 0]}
assert Q.features(hh, "yes", 3, dict(open=O, series="X", group="crypto"))["hhhl"] == 1.0
assert Q.features(hh, "yes", 2, dict(open=O, series="X", group="crypto"))["hhhl"] == 0.0
lp = Q.features(hh, "yes", 3, dict(open=O, series="X", group="crypto"))
assert lp["hour_band"] == 1 and lp["weekday"] == date(2026, 6, 10).weekday()   # 05:03 La Paz -> band 4-8
assert Q.features({"2": [None, None, None, None, None, None, None, 0, 0]}, "yes", 3, dict(open=O, series="X", group="x")) is None
print("features ok")

# ---------- 4. fill rule ----------
cs3 = {"5": [0.02, 0.04, 0, 0, 0, 0, 0, 1, 1], "6": [0.02, 0.05, 0, 0, 0, 0, 0, 1, 1], "8": [0.03, 0.06, 0, 0, 0, 0, 0, 1, 1]}
assert Q.fill(cs3, 5, "yes") == (0.05, None), "fill at the side's ask in candle m + 1"
assert Q.fill(cs3, 6, "yes")[0] is None, "candle m + 1 missing: no fill (never carried from m)"
assert Q.fill(cs3, 7, "yes")[0] == 0.06 and Q.fill(cs3, 6, "no")[0] is None, "only candle m + 1 itself (8 is not 7)"
assert Q.fill({"2": [0.0, 0.03, 0, 0, 0, 0, 0, 0, 0]}, 1, "yes")[0] is None, "bid 0: no fill"
assert Q.fill({"2": [0.03, 0.03, 0, 0, 0, 0, 0, 0, 0]}, 1, "yes")[0] is None, "locked: no fill"
assert Q.fill({"2": [0.03, None, 0, 0, 0, 0, 0, 0, 0]}, 1, "yes")[0] is None, "ask missing: no fill"
assert Q.fill({"2": [0.08, 0.11, 0, 0, 0, 0, 0, 0, 0]}, 1, "yes")[0] is None, "ask above 10c: no fill"
assert Q.fill({"2": [0.08, 0.10, 0, 0, 0, 0, 0, 0, 0]}, 1, "yes")[0] == 0.10
p, why = Q.fill({"2": [0.93, 0.95, 0, 0, 0, 0, 0, 0, 0]}, 1, "no")
assert abs(p - 0.07) < 1e-9 and why is None, "NO bought at 1 - yes bid"
assert Q.fill({"2": [0.93, 1.0, 0, 0, 0, 0, 0, 0, 0]}, 1, "no")[0] is None, "NO bid = 1 - yes ask = 0: no fill"
print("fill ok")

# ---------- 5. fees on a $1 bet ----------
assert Q.contracts(0.03) == 33 and Q.contracts(0.05) == 20 and Q.contracts(0.10) == 10 and Q.contracts(0.01) == 100
assert Q.contracts(0.07) == 14 and Q.contracts(0.033) == 30
assert Q.fee(0.03) == math.ceil(0.07 * 33 * 0.03 * 0.97 * 100 - 1e-9) / 100 == 0.07
assert Q.fee(0.03, True) == 0.0673 and Q.fee(0.10) == 0.07 and Q.fee(0.01) == 0.07 and Q.fee(0.05) == 0.07
assert abs(Q.threshold(0.03) - (0.03 + 0.07 / 33 + 0.01)) < 1e-15
r = Q.bet_row(date(2026, 8, 1), "S", "crypto", 5, "yes", 0.03, 0.03, 1.0)
assert abs(r["profit"] - (1 - 0.03 - 0.07 / 33)) < 1e-12 and abs(r["profit_cc"] - (1 - 0.03 - 0.0673 / 33)) < 1e-12
assert abs(r["breakeven"] - (0.03 + 0.07 / 33)) < 1e-12 and r["contracts"] == 33
r0 = Q.bet_row(date(2026, 8, 1), "S", "crypto", 5, "yes", 0.03, 0.04, 0.0)
assert abs(r0["profit"] - (-0.04 - 0.07 / 25)) < 1e-12, "paid at the fill price, fee at the fill price"
assert Q.ask_band(0.01) == "1-2c" and Q.ask_band(0.02) == "1-2c" and Q.ask_band(0.03) == "3-5c" and Q.ask_band(0.05) == "3-5c"
assert Q.ask_band(0.06) == "6-10c" and Q.ask_band(0.10) == "6-10c"
assert Q.left_band(13) == "1-4" and Q.left_band(11) == "1-4" and Q.left_band(10) == "5-9" and Q.left_band(6) == "5-9"
assert Q.left_band(5) == "10-14" and Q.left_band(1) == "10-14"
print("fees ok")


# ---------- 6. a model, decide() and one bet per window ----------
def hand_model(series=(), **coef):
    names = Q.input_names(list(series))
    return dict(plan_sha256=Q.PLAN_SHA256, series=list(series), mean=[0.0] * len(Q.CONT), sd=[1.0] * len(Q.CONT),
                intercept=coef.pop("intercept", 0.0), coef=[coef.get(n, 0.0) for n in names])


always = hand_model(intercept=20.0)
never = hand_model(intercept=-20.0)
d = Q.decide(always, Q.features({"1": [0.02, 0.03, 0, 0, 0, 0, 0, 0, 0]}, "yes", 1, dict(open=O, series="X", group="crypto")))
assert d["bet"] and d["p"] > 0.99 and abs(d["threshold"] - Q.threshold(0.03)) < 1e-15
assert not Q.decide(never, Q.features({"1": [0.02, 0.03, 0, 0, 0, 0, 0, 0, 0]}, "yes", 1, dict(open=O, series="X", group="crypto")))["bet"]
assert not Q.decide(always, dict(Q.features({"1": [0.5, 0.6, 0, 0, 0, 0, 0, 0, 0]}, "yes", 1, dict(open=O, series="X", group="crypto"))))["bet"]
# p exactly at the line: bet; just below: no bet
fz = Q.features({"1": [0.02, 0.03, 0, 0, 0, 0, 0, 0, 0]}, "yes", 1, dict(open=O, series="X", group="crypto"))
thr = Q.threshold(0.03)
at = hand_model(intercept=math.log(thr / (1 - thr)))
assert Q.decide(at, fz)["bet"]
below = hand_model(intercept=math.log((thr - 1e-6) / (1 - thr + 1e-6)))
assert not Q.decide(below, fz)["bet"]
# the truth value of decide() is the bet (a logger may write `if decide(...)`); no features never bets
assert bool(Q.decide(at, fz)) is True and bool(Q.decide(below, fz)) is False and bool(Q.decide(always, None)) is False
assert json.loads(json.dumps(Q.decide(at, fz)))["bet"] is True
# a live logger's dict candles (scalars, no highs and lows) give the same features as records with highs = lows = close
live = {1: dict(yes_bid=0.20, yes_ask=0.25, last=0.25, volume=10, open_interest=50),
        2: dict(yes_bid=0.04, yes_ask=0.06, last=None, volume=5, open_interest=60),
        4: dict(yes_bid=0.02, yes_ask=0.05, last=0.05, volume=20, open_interest=80)}
recs = {k: [v["yes_bid"], v["yes_ask"], None, None, None, None, v["last"], float(v["volume"]), float(v["open_interest"])]
        for k, v in live.items()}
for side in ("yes", "no"):
    for m in (1, 3, 5):
        assert Q.features(live, side, m, dict(open=O, series="X", group="crypto")) == \
            Q.features(recs, side, m, dict(open=O, series="X", group="crypto"))
assert Q.fill({5: dict(yes_bid=0.02, yes_ask=0.05)}, 4, "yes") == (0.05, None)


def mk(ticker, close, result, quotes):
    """quotes: {m: (yes bid, yes ask)}."""
    return dict(ticker=ticker, close=close, open=close - 900, open_listed=close - 900, result=result,
                c={str(m): [yb, ya, yb, yb, ya, ya, ya, 1.0, 10.0] for m, (yb, ya) in quotes.items()})


close = Q.lapaz_start(date(2026, 8, 3)) + 3600 * 10
# market B: YES cheap from m=1; market A: NO cheap from m=1 (yes bid 0.96). A sorts first.
A = mk("KXSOL15M-A", close, "no", {m: (0.96, 0.98) for m in range(1, 15)})
B = mk("KXSOL15M-B", close, "yes", {m: (0.02, 0.04) for m in range(1, 15)})
day = date(2026, 8, 3)
data = {("KXSOL15M", day): dict(markets=[B, A], complete=True)}
groups = {"KXSOL15M": "crypto"}
bets, cands, calib, cnt = Q.collect(data, groups, always)
assert len(bets) == 1 and bets[0]["ticker"] == "KXSOL15M-A" and bets[0]["side"] == "no" and bets[0]["m"] == 1, bets
assert cnt["windows"] == 1 and cnt["windows_with_bet"] == 1 and cnt["passed"] == 1
assert abs(bets[0]["price"] - 0.04) < 1e-9 and bets[0]["win"] == 1.0
# A cannot fill at m = 2 (candle 2 missing): B's YES at m = 1 is next in order
A2 = mk("KXSOL15M-A", close, "no", {m: (0.96, 0.98) for m in range(1, 15) if m != 2})
bets, _, _, cnt = Q.collect({("KXSOL15M", day): dict(markets=[B, A2], complete=True)}, groups, always)
assert bets[0]["ticker"] == "KXSOL15M-B" and bets[0]["m"] == 1 and cnt["passed"] == 2 and cnt["passed_unfilled"]
# a skipped fill does not use up the side: alone, A is bought at m = 2 (fill in candle 3)
bets, _, _, _ = Q.collect({("KXSOL15M", day): dict(markets=[A2], complete=True)}, groups, always)
assert bets[0]["ticker"] == "KXSOL15M-A" and bets[0]["m"] == 2
# YES before NO within a market: a market with both sides cheap is impossible (yes ask <= 10c means yes bid < 10c),
# so the order is checked on two windows of two series at one close: one bet each
C = mk("KXGOLD15M-C", close, "yes", {m: (0.02, 0.04) for m in range(1, 15)})
bets, _, _, cnt = Q.collect({("KXSOL15M", day): dict(markets=[B, A], complete=True),
                             ("KXGOLD15M", day): dict(markets=[C], complete=True)},
                            {"KXSOL15M": "crypto", "KXGOLD15M": "metals"}, always)
assert len(bets) == 2 and cnt["windows"] == 2 and {b["series"] for b in bets} == {"KXSOL15M", "KXGOLD15M"}
bets, cands, _, _ = Q.collect(data, groups, never)
assert not bets and len(cands) == 2 * 13, "every filled chance is a placebo candidate"
print("one bet per window ok")

# ---------- 7. statistics ----------
assert Q.holm([dict(name="a", p=0.001), dict(name="b", p=0.02), dict(name="c", p=0.007), dict(name="d", p=None)])
hs = {x["name"]: x for x in Q.holm([dict(name="a", p=0.001), dict(name="b", p=0.02), dict(name="c", p=0.007),
                                     dict(name="d", p=None)])}
assert hs["a"]["passed"] and hs["a"]["holm_level"] == 0.00625 and hs["c"]["passed"] and abs(hs["c"]["holm_level"] - 0.025 / 3) < 1e-15
assert not hs["b"]["passed"] and hs["b"]["holm_level"] == 0.0125 and not hs["d"]["passed"] and hs["d"]["holm_rank"] == 4
hs = {x["name"]: x for x in Q.holm([dict(name="a", p=0.009), dict(name="b", p=0.001), dict(name="c", p=0.0095),
                                     dict(name="d", p=0.02)])}
assert hs["b"]["passed"] and not hs["a"]["passed"] and not hs["c"]["passed"] and not hs["d"]["passed"], "step-down stops"
# Poisson-binomial bound against brute force
rr = random.Random(3)
rows = [dict(win=float(rr.random() < 0.3), breakeven=rr.uniform(0.02, 0.5)) for _ in range(12)]
w = int(sum(r["win"] for r in rows))
brute = 0.0
for combo in itertools.product((0, 1), repeat=len(rows)):
    if sum(combo) >= w:
        pr = 1.0
        for k, r in zip(combo, rows):
            pr *= r["breakeven"] if k else 1 - r["breakeven"]
        brute += pr
assert abs(Q.pb_tail(rows) - brute) < 1e-12
assert Q.pb_tail([dict(win=0.0, breakeven=0.1)]) == 1.0
# clustered t, bootstrap
D0 = date(2026, 8, 1)
period = [D0 + timedelta(days=i) for i in range(92)]
pos = [dict(day=period[i % 92], profit=0.5 + 0.01 * (i % 3)) for i in range(400)]
assert Q.boot_p(pos, period, draws=500) == 0.0
neg = [dict(day=period[i % 92], profit=-0.1) for i in range(400)]
assert Q.boot_p(neg, period, draws=500) == 1.0
tr = Q.t_reading([dict(day=period[i % 40], profit=(1.0 if i % 2 else 0.0)) for i in range(400)])
assert tr["df"] == 39 and abs(tr["mean"] - 0.5) < 1e-12
# placebo cells: same (day, ask band, minute); other cells never drawn
bets_ = [dict(day=D0, band="3-5c", m=6, profit=1.0) for _ in range(2)]
pool = bets_ + [dict(day=D0, band="3-5c", m=6, profit=-0.05) for _ in range(6)]
other = [dict(day=D0, band="3-5c", m=7, profit=99.0) for _ in range(50)] + [dict(day=D0, band="6-10c", m=6, profit=99.0)]
assert Q.placebo_cells(bets_) == {(D0, "3-5c", 6): 2}
p1 = Q.placebo_p(bets_, pool, 1.0, draws=4000)
p2 = Q.placebo_p(bets_, pool + other, 1.0, draws=4000)
assert p1 == p2, "only the bets' own cells are drawn from"
assert abs(p1 - 1.0 / 28) < 0.02, p1        # both draws hit the two winners: 1 / C(8, 2)
assert Q.placebo_p(bets_, bets_, 1.0, draws=100) == 1.0, "a pool of only the rule's bets: p = (N + 1) / (N + 1)"
try:
    Q.placebo_p(bets_ + bets_, pool[:3], 1.0, draws=10)
    raise AssertionError("a pool smaller than the bets must be refused")
except ValueError:
    pass
print("statistics ok")

# ---------- 8. series table and identity: once only ----------
CALLS = []
LATE_OK = []


def fake_series(path, params=None):
    CALLS.append((path, dict(params or {})))
    if path == "/series":
        if not (params or {}).get("cursor"):
            return dict(series=[dict(ticker="KXSOL15M", title="Solana 15 min", category="Crypto"),
                                dict(ticker="KXBTC15M", title="Bitcoin 15 min"), dict(ticker="KXBTCD", title="BTC daily")],
                        cursor="p2")
        return dict(series=[dict(ticker="KXGOLD15M", title="Gold 15 min"), dict(ticker="KXOLD15M", title="old",
                                                                               status="inactive")], cursor="")
    raise AssertionError("unexpected request %s" % path)


Q.http_kalshi = fake_series
rec, msg = Q.make_series()
assert rec and [s["ticker"] for s in rec["series"]] == ["KXBTC15M", "KXGOLD15M", "KXOLD15M", "KXSOL15M"], msg
assert rec["groups"]["btceth"] == ["KXBTC15M"] and rec["groups"]["other"] == ["KXOLD15M"]
assert Q.make_series()[0] is None, "the series table is written once"
assert Q.download()[0] is False, "no download before the freeze"
assert Q.make_map()[0] is None and Q.fit()[0] is None and Q.score()[0] is None, "nothing before the freeze"
idp = Q.identity_path()
rec, msg = Q.freeze(root=WORK)
assert rec and os.path.exists(idp), msg
assert Q.freeze(root=WORK)[0] is None, "frozen once"
assert Q.identity_problems(WORK) == []
spath = Q.series_path()
keep = open(spath, encoding="utf-8").read()
with open(spath, "a", encoding="utf-8") as fh:
    fh.write(" ")
assert Q.identity_problems(WORK), "a changed series table is caught"
with open(spath, "w", encoding="utf-8") as fh:
    fh.write(keep)
assert Q.identity_problems(WORK) == []
print("series and freeze ok")

# ---------- 9. download: nothing closing on or after 2026-11-01 La Paz is read ----------
JUN = Q.lapaz_start(date(2026, 6, 2)) + 3600 * 3


def lst(ticker, close, result="yes"):
    return dict(ticker=ticker, close_time=_iso(close), open_time=_iso(close - 900), result=result, status="finalized")


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


LISTED = {"KXSOL15M": [lst("KXSOL15M-J1", JUN), lst("KXSOL15M-J2", JUN + 900, "no"), lst("KXSOL15M-J3", JUN + 1800, ""),
                       lst("KXSOL15M-A1", Q.lapaz_start(date(2026, 8, 5)) + 7200),
                       lst("KXSOL15M-O31", NOV1 - 900), lst("KXSOL15M-N1", NOV1), lst("KXSOL15M-N5", NOV1 + 4 * 86400),
                       lst("KXSOL15M-M31", Q.lapaz_start(date(2026, 6, 1)) - 900)]}


def fake_kalshi(path, params=None):
    params = dict(params or {})
    CALLS.append((path, params))
    if path in ("/markets", "/historical/markets"):
        if path == "/markets":
            assert params["max_close_ts"] < NOV1, "the live listing is bounded before Nov 1"
        return dict(markets=LISTED.get(params["series_ticker"], []) if path == "/historical/markets" else [], cursor="")
    if path.endswith("/candlesticks"):
        t = path.split("/")[-2]
        assert not any(x in t for x in ("N1", "N5", "M31")), "candles of a market outside the period were requested"
        o = int(params["start_ts"])
        return dict(candlesticks=[kc(m, 0.02, 0.04, o=o) for m in range(1, 16)])
    raise AssertionError("unexpected request %s" % path)


Q.http_kalshi = fake_kalshi
recs, skipped = Q.market_list("KXSOL15M", date(2026, 6, 1), date(2026, 12, 31))
assert sorted(recs) == ["KXSOL15M-A1", "KXSOL15M-J1", "KXSOL15M-J2", "KXSOL15M-O31"] and skipped["not_yes_no"] == 1
try:
    Q.fetch_candles(dict(ticker="KXSOL15M-N1", close=NOV1, open=NOV1 - 900, hist=True))
    raise AssertionError("a November market must be refused")
except ValueError:
    pass
del CALLS[:]
ok, msg = Q.download(now=Q.lapaz_start(date(2026, 11, 25)), log=QUIET)
assert ok, msg
cpaths = [c[0] for c in CALLS if c[0].endswith("/candlesticks")]
assert sorted(p.split("/")[-2] for p in cpaths) == ["KXSOL15M-J1", "KXSOL15M-J2"], cpaths   # Aug waits for the fit
assert all(int(c[1]["max_close_ts"]) < Q.lapaz_start(date(2026, 8, 1)) for c in CALLS if "max_close_ts" in c[1])
dj = P._read_json(Q.day_path("KXSOL15M", date(2026, 6, 2)))[0]
assert [m["ticker"] for m in dj["markets"]] == ["KXSOL15M-J1", "KXSOL15M-J2"] and dj["markets"][0]["c"]["1"][Q.YA] == 0.04
assert sorted(int(k) for k in dj["markets"][0]["c"]) == list(range(1, 15))
assert os.path.exists(Q.day_path("KXGOLD15M", date(2026, 7, 31))) and not os.path.exists(Q.day_path("KXSOL15M", date(2026, 8, 5)))
n_days = sum(1 for s in ("KXSOL15M", "KXGOLD15M", "KXBTC15M", "KXOLD15M") for d in P.days_of(date(2026, 6, 1), date(2026, 7, 31))
             if os.path.exists(Q.day_path(s, d)))
assert n_days == 4 * 61
assert Q.download(now=Q.lapaz_start(date(2026, 11, 25)), log=QUIET)[1].startswith("download: 0 "), "a saved day is final"


class NoResult(dict):
    def __getitem__(self, k):
        if k == "result":
            raise AssertionError("the format check read an outcome")
        return dict.__getitem__(self, k)

    def get(self, k, default=None):
        if k == "result":
            raise AssertionError("the format check read an outcome")
        return dict.get(self, k, default)


real_read = P._read_json


def guarded_read(path):
    obj, ok = real_read(path)
    if isinstance(obj, dict) and isinstance(obj.get("markets"), list):
        obj["markets"] = [NoResult(m) for m in obj["markets"]]
    return obj, ok


P._read_json = guarded_read
chk = Q.format_check()
P._read_json = real_read
assert chk["summary"]["markets"] == 2 and chk["summary"]["candles"] == 28 and chk["summary"]["late"] == 0
assert chk["summary"]["crossed"] == 0 and chk["series"]["KXSOL15M"]["fit_days"] == 61
# windows_of drops any market closing outside the period even if one were in a file
bad = {("KXSOL15M", date(2026, 10, 31)): dict(markets=[mk("KXSOL15M-N1", NOV1, "yes", {1: (0.02, 0.04)}),
                                                        mk("KXSOL15M-O31", NOV1 - 900, "yes", {1: (0.02, 0.04)})])}
assert [w[4][0]["ticker"] for w in Q.windows_of(bad, groups)] == ["KXSOL15M-O31"]
# after the fit exists, August-October downloads (still nothing from November)
with open(Q.model_path(), "w") as fh:
    fh.write("{}")
del CALLS[:]
ok, msg = Q.download(now=Q.lapaz_start(date(2026, 11, 25)), log=QUIET)
cpaths = [c[0].split("/")[-2] for c in CALLS if c[0].endswith("/candlesticks")]
assert sorted(cpaths) == ["KXSOL15M-A1", "KXSOL15M-O31"], cpaths
assert all(int(c[1]["max_close_ts"]) < NOV1 for c in CALLS if "max_close_ts" in c[1])
os.remove(Q.model_path())
print("download ok")

# ---------- 10. map, fit, score on synthetic data (stages in order, each once) ----------
assert Q.fit(data={}, srec=P._read_json(spath)[0])[0] is None, "the fit waits for the map"
assert Q.score(data={}, srec=P._read_json(spath)[0])[0] is None, "the score waits for the model"
SREC = dict(series=[dict(ticker="KXSOL15M", group="crypto"), dict(ticker="KXGOLD15M", group="metals"),
                    dict(ticker="KXBTC15M", group="btceth")], groups={})
GROUPS = {s["ticker"]: s["group"] for s in SREC["series"]}
WIN_R = {"KXSOL15M": 0.6, "KXGOLD15M": 0.045, "KXBTC15M": 0.9}


def synth(first, last, seed):
    """8 windows a day per series; half 'rising' (cheap YES whose ask rises from minute 5), half 'falling'. Rising
    YES wins with WIN_R[series], falling with 3%."""
    r = random.Random(seed)
    out = {}
    for d in P.days_of(first, last):
        for s in WIN_R:
            ms = []
            for j in range(8):
                cl = Q.lapaz_start(d) + 3600 * (1 + 3 * j)
                rising = j % 2 == 0
                q = {}
                for m in range(1, 15):
                    if m <= 4:
                        a = 0.30
                    else:
                        a = round(0.04 + 0.005 * (m - 5), 4) if rising else round(0.05 - 0.005 * (m - 5), 4)
                    q[m] = (round(a - 0.01, 4), a)
                y = "yes" if r.random() < (WIN_R[s] if rising else 0.03) else "no"
                ms.append(mk("%s-%s-%d" % (s, d.isoformat(), j), cl, y, q))
            out[(s, d)] = dict(markets=ms, complete=True)
    return out


fitdata = synth(date(2026, 6, 1), date(2026, 6, 20), 1)
res, msg = Q.make_map(data=fitdata, srec=SREC)
assert res and res["map"]["overall"]["n"] > 0 and "crypto" in res["map"]["group"] and "btceth" in res["map"]["group"], msg
assert set(res["map"]["band"]) <= {"1-2c", "3-5c", "6-10c"} and set(res["map"]["left"]) <= {"1-4", "5-9", "10-14"}
assert set(res["map"]["move"]) <= {"falling", "flat", "rising"} and res["map"]["group"]["crypto"]["win_rate_ci95"]
md_p, js_p, sha_p = Q.map_paths()
assert P._read_json(sha_p)[0]["map_md"] == Q.file_sha(md_p) and Q.map_problems() is None
assert Q.make_map(data=fitdata, srec=SREC)[0] is None, "the map is written once"

# ridge: determinism, numpy and pure Python agree, CV grouped by day
rows = Q.fit_rows(synth(date(2026, 6, 1), date(2026, 6, 6), 2), GROUPS)
sl = sorted({r[1][Q.FEAT_KEYS.index("series")] for r in rows})
small = rows[::12]
Xs = Q.design_matrix(small, sl, "python")
Ys = [r[2] for r in small]
g1 = Q.ridge_fit(Xs, Ys, 0.1, "python")
g2 = Q.ridge_fit(Xs, Ys, 0.1, "python")
assert g1 is not None and g1 == g2, "deterministic"
if Q._np() is not None:
    g3 = Q.ridge_fit(Q.design_matrix(small, sl, "numpy"), Ys, 0.1, "numpy")
    assert abs(g3[0] - g1[0]) < 1e-6 and max(abs(a - b) for a, b in zip(g3[1], g1[1])) < 1e-6, "numpy = pure Python"
    assert max(abs(a - b) for a, b in zip(g3[2], g1[2])) < 1e-12 and max(abs(a - b) for a, b in zip(g3[3], g1[3])) < 1e-12
big = Q.ridge_fit(Xs, Ys, 100.0, "python")
assert sum(b * b for b in big[1]) < sum(b * b for b in g1[1]), "a larger strength shrinks the slopes"
Ds = [r[0] for r in small]
fo = Q.fold_of(Ds)
days_sorted = sorted(set(Ds))
assert all(fo[d] == i % 5 for i, d in enumerate(days_sorted)), "days dealt round-robin into 5 folds"
assert len(set(fo.values())) == 5
seen_split = []
real_fit = Q.ridge_fit


def spy(X, Y, lam, backend="python"):
    seen_split.append(len(Y))
    return real_fit(X, Y, lam, backend)


Q.ridge_fit = spy
best, table = Q.cross_validate(Xs, Ys, Ds, "python")
Q.ridge_fit = real_fit
assert len(table) == 13 and [e["strength"] for e in table] == list(Q.STRENGTHS) and best is not None
assert all(len(e["fold_losses"]) == 5 for e in table)
for f_ in range(5):
    n_tr = sum(1 for d in Ds if fo[d] != f_)
    assert seen_split[f_] == n_tr, "each training fold holds whole days"
assert best["mean"] == min(e["mean"] for e in table)

model, msg = Q.fit(data=fitdata, srec=SREC, backend=("numpy" if Q._np() is not None else "python"), log=lambda *_: None)
assert model, msg
assert model["series"] == ["KXBTC15M", "KXGOLD15M", "KXSOL15M"] and model["strength"] in Q.STRENGTHS
assert len(model["coef"]) == len(model["inputs"]) and model["map_sha256"] == Q.file_sha(md_p)
assert model["plan_sha256"] == Q.PLAN_SHA256 and model["frozen"] == model["fitted"]
assert Q.fit(data=fitdata, srec=SREC)[0] is None, "fitted once"
# an unseen series keeps its group indicator only
fx = Q.features({"5": [0.03, 0.04, 0.04, 0.03, 0.04, 0.04, 0, 0, 0]}, "yes", 5, dict(open=O, series="KXNEW15M", group="crypto"))
row = Q.design_row(fx, model["series"])
assert row[-3:] == [0.0, 0.0, 0.0] and row[len(Q.CONT) + 1 + 6 + 7 + Q.GROUPS.index("crypto")] == 1.0

# score with a planted, selective edge (bets only rising YES sides at m = 6; random sides in the same cells are worse)
scoredata = synth(date(2026, 8, 1), date(2026, 10, 31), 7)
pick = hand_model(series=model["series"], intercept=-3.0, d1=400.0)
pick["plan_sha256"] = Q.PLAN_SHA256
res, verdict = Q.score(data=scoredata, srec=SREC, model=pick)
assert res, verdict
T_ = {x["name"]: x for x in res["tests"]}
assert T_["crypto"]["stats"]["bets"] == 92 * 4 and T_["crypto"]["passed"] and T_["crypto"]["holm_level"] == 0.00625, T_["crypto"]
assert T_["crypto"]["checks"]["p_placebo"] < 0.002 and T_["crypto"]["checks"]["p_boot"] == 0.0
assert T_["metals"]["stats"]["bets"] == 92 * 4 and not T_["metals"]["passed"] and T_["metals"]["verdict"] == Q.VERDICT_FAIL
assert T_["energy"]["verdict"].startswith(Q.NOT_TESTABLE) and T_["fx"]["verdict"].startswith(Q.NOT_TESTABLE)
assert res["descriptive"]["btceth"]["bets"] == 92 * 4, "BTC/ETH shown only as a descriptive row"
assert res["verdict"].startswith(Q.VERDICT_PASS) and "crypto" in res["verdict"] and "metals" not in res["verdict"]
assert sum(x["stats"]["bets"] for x in res["tests"]) == 2 * 92 * 4, "no BTC/ETH bet in any test"
assert res["counts"]["windows"] == 3 * 92 * 8 and res["counts"]["windows_with_bet"] == 3 * 92 * 4
assert res["exploratory"]["calibration_deciles"] and res["exploratory"]["by_ask_band"]["3-5c"]["bets"] == 2 * 92 * 4
assert os.path.exists(Q.result_paths()[0]) and os.path.exists(Q.result_paths()[1])
assert Q.score(data=scoredata, srec=SREC, model=pick)[0] is None, "scored once"
# BTC/ETH never in a test: the same data with only BTC is not testable everywhere
os.remove(Q.result_paths()[0]); os.remove(Q.result_paths()[1])
only_btc = {k: v for k, v in scoredata.items() if k[0] == "KXBTC15M"}
res2, v2 = Q.score(data=only_btc, srec=SREC, model=pick)
assert all(x["verdict"].startswith(Q.NOT_TESTABLE) for x in res2["tests"]) and v2 == Q.VERDICT_FAIL
assert res2["descriptive"]["btceth"]["bets"] == 92 * 4
os.remove(Q.result_paths()[1])
assert Q.score(data=only_btc, srec=SREC, model=pick)[0] is None, "a result .md alone also blocks a second score"
bad_model = dict(pick, plan_sha256="x")
os.remove(Q.result_paths()[0])
assert Q.score(data=only_btc, srec=SREC, model=bad_model)[0] is None, "a model from another plan is refused"
print("map, fit, score ok")

assert "PLAN20:" in Q.status()
print("PLAN20 tests passed")
