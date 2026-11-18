"""research/plan17.py (PLAN17: late reversals on cheap 15-minute contracts), on synthetic data. No network.
python test_plan17.py WORK OUT"""
import os, sys, json, math
from datetime import date, datetime, timezone
import tempfile
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])   # a fresh folder each run
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import plan17 as Q
P = Q.P
src = open(os.path.join(WORK, "research", "plan17.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "paper.db" not in src, "research only"
assert P.bytes_hash(os.path.join(WORK, "research", "PLAN17.md")) == Q.PLAN_SHA256, "PLAN17.md is the frozen text"
assert (Q.KS, Q.CHEAP, Q.EDGE, Q.SPOT_FROM, Q.SPOT_TO, Q.RECENT, Q.MOM, Q.RIDGE, Q.LEVEL, Q.T_FLOOR, Q.BOOT_BLOCK_DAYS,
        Q.BOOT_DRAWS, Q.PLACEBO_DRAWS, Q.SEED, Q.MIN_BETS, Q.MIN_DAYS, Q.FILL_DELAY) == \
       ((10, 11, 12, 13), (0.01, 0.05), 0.02, -16, 13, 15, 3, 1.0, 0.0125, 2.3, 2, 20000, 2000, 17, 100, 15, 1), \
       "the plan's numbers"
assert Q.FIT_PERIOD == (date(2026, 9, 1), date(2026, 9, 30)) and Q.TEST_PERIOD == (date(2026, 10, 1), date(2026, 10, 31))
assert P.RIDGE_SCALE == "sum"


def ts(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


# ---------- 1. fee, cheap side, inputs ----------
assert Q.fee_fine(0.03, 1.0) == math.ceil(0.07 * 0.03 * 0.97 * 10000 - 1e-9) / 10000 == 0.0021
assert P.fee(0.03, 1.0) == 0.01   # whole cent
assert Q.cheap_side((0.02, 0.03)) == "yes" and Q.cheap_side((0.96, 0.98)) == "no"   # NO ask = 1 - 0.96 = 4c
assert Q.cheap_side((0.10, 0.12)) is None and Q.cheap_side((0.0, 0.03)) is None      # not cheap / bid 0 (not 0 < bid)
assert Q.cheap_side((0.03, 0.03)) is None and Q.cheap_side(None) is None              # locked / missing
assert Q.cheap_side((0.005, 0.006)) is None                                           # under 1c
assert Q.cheap_side((0.97, 1.0)) == "no"                                              # yes ask $1.00: NO at 3c counts
o = ts(2026, 9, 10, 12, 0)
spot = {int(o) + 60 * i: [0, 0, 0, 100.0 + 0.01 * i + (0.003 if i % 2 else 0)] for i in range(-16, 14)}
dw = Q.derive_window(dict(ticker="T", open=o), spot)
assert dw["spot_ok"] and dw["k"]["10"]["sk"] == spot[int(o) + 600][3] and dw["k"]["13"]["sk3"] == spot[int(o) + 600][3]
want = P.sigma_from([spot[int(o) + 60 * i][3] for i in range(-5, 11)])
assert abs(dw["k"]["10"]["sig15"] - want) < 1e-15
s2 = dict(spot); del s2[int(o) - 60 * 16]
assert not Q.derive_window(dict(ticker="T", open=o), s2)["spot_ok"]       # minute -16 counts for the guard
s3 = dict(spot); del s3[int(o) + 60 * 7]
d3 = Q.derive_window(dict(ticker="T", open=o), s3)
assert d3["k"]["10"]["sk3"] is None and d3["k"]["10"]["sig15"] is None and d3["k"]["13"]["sig15"] is None


def win(q=(0.02, 0.03), q7=None, strike=100.0, result="no", t0=None, ticker="T"):
    t0 = o if t0 is None else t0
    c = {str(m): [q[0], q[1], 5.0] for m in range(1, 16)}
    if q7 is not None:
        c["7"] = [q7[0], q7[1], 5.0]
    up = result == "yes"
    keep = {str(i): [strike, strike, strike, strike] for i in P.KEEP_MINUTES}
    keep[str(P.T_MIN)] = [strike + (1 if up else -1)] * 4
    return dict(ticker=ticker, open=t0, close=t0 + 900, strike=strike, strike_type="greater_or_equal", result=result,
                c=c, t={str(m): 20.0 for m in range(1, 16)}, spot=dict(complete=True, sigma=0.001, m=keep))


v = dict(sk=99.9, sk3=99.8, sig15=0.001)
side, ask, x = Q.state(win(q7=(0.01, 0.02)), v, 10, True)
assert side == "yes" and ask == 0.03 and len(x) == 5
assert abs(x[0] - P.P7.logit(0.03)) < 1e-12
assert abs(x[1] - max(-6, math.log(99.9 / 100.0) / (0.001 * math.sqrt(4.5)))) < 1e-12   # toward YES, clipped
assert abs(x[2] - math.log(99.9 / 99.8) / (0.001 * math.sqrt(3))) < 1e-9 or x[2] == 6.0
assert abs(x[3] - 0.01) < 1e-12 and x[4] == 5.0                                          # ask 3c now vs 2c at minute 7
side, ask, x = Q.state(win(q=(0.97, 0.98)), dict(sk=100.05, sk3=100.06, sig15=0.001), 10, True)
assert side == "no" and abs(ask - 0.03) < 1e-9 and x[1] < 0 and x[2] > 0                 # NO: signs flipped
assert Q.state(win(), dict(sk=None, sk3=99.8, sig15=0.001), 10, True)[2] is None          # missing input
assert Q.state(win(q=(0.4, 0.5)), v, 10, True) is None                                    # no cheap side
w0 = win()
w0["c"].pop("7"); w0["c"].pop("6"); w0["c"].pop("5"); w0["c"].pop("4"); w0["c"].pop("3"); w0["c"].pop("2"); w0["c"].pop("1")
assert Q.state(w0, v, 10, True)[2][3] == 0.0                                              # no k-3 quote: x4 = 0
w7 = win(q7=(0.01, 0.02)); w7["c"].pop("7")       # k-3 = 7 has no candle: minute 6's quote carries forward
w7["c"]["6"] = [0.005, 0.015, 5.0]
assert abs(Q.state(w7, v, 10, True)[2][3] - (0.03 - 0.015)) < 1e-12
ws = win(); ws["strike"] = None
assert Q.state(ws, v, 10, True)[2] is None                                                # no floor_strike: missing
print("inputs ok")

# ---------- 2. statistics pieces ----------
bets = [dict(price=0.03, fee=0.0, fee_cent=0.01, win=w) for w in (1, 0, 0, 0)]
p2 = Q.exact_p(bets)
assert abs(p2 - (1 - 0.97 ** 4)) < 1e-12
assert Q.exact_p([dict(price=0.03, fee=0.0, fee_cent=0.01, win=0)] * 3) == 1.0
assert abs(Q.exact_p(bets, cent=True) - (1 - 0.96 ** 4)) < 1e-12                         # whole-cent fee: 4% each
# placebo fallbacks: stratum, then cent, then band, then none
cb = [dict(day=1, ticker="a", k=10, cent=3, win=0, price=0.03, fee=0.0, fee_cent=0.01),
      dict(day=1, ticker="b", k=11, cent=3, win=0, price=0.03, fee=0.0, fee_cent=0.01),
      dict(day=1, ticker="c", k=10, cent=4, win=0, price=0.04, fee=0.0, fee_cent=0.01)]
rb = [dict(day=1, ticker="x", k=10, cent=3, win=1, price=0.03, fee=0.0, fee_cent=0.01),
      dict(day=1, ticker="y", k=10, cent=3, win=1, price=0.03, fee=0.0, fee_cent=0.01),
      dict(day=1, ticker="z", k=10, cent=3, win=1, price=0.03, fee=0.0, fee_cent=0.01),
      dict(day=1, ticker="q", k=10, cent=3, win=1, price=0.03, fee=0.0, fee_cent=0.01)]
pp, fb = Q.placebo(rb, cb, 0.97, draws=50)
assert fb == dict(stratum=50, cent=50, band=50, none=50), fb    # one window each, without replacement
assert abs(pp - 51.0 / 51.0) > 0 and pp < 0.05
print("statistics ok")
days = P.days_of(date(2026, 10, 1), date(2026, 10, 31))
assert Q.boot_p({d: 1.0 for d in days}, days, draws=500) == 0.0
assert Q.boot_p({d: -1.0 for d in days}, days, draws=500) == 1.0
print("statistics ok")

# ---------- 3. full run: fit on September, score October ----------
Q.WINDOWS_PER_DAY = 12
Q.PLACEBO_DRAWS = 200
Q.BOOT_DRAWS = 2000


def make_month(first, last, planted):
    data = {}
    for d in P.days_of(first, last):
        ws, mine = [], []
        for j in range(Q.WINDOWS_PER_DAY):
            t0 = P.day_start(d) + 900 * j
            mom = j < 5                                   # 5 windows a day: price rising toward the strike
            n = (d.toordinal() * 12 + j)
            if planted:
                yes = mom and n % 5 < 2                   # 40% of momentum windows reverse; others never
            else:
                yes = n % 37 == 0                         # about 3%, unrelated to momentum
            tk = "W%s-%d" % (d.isoformat(), j)
            ws.append(win(q7=(0.02, 0.03), result="yes" if yes else "no", t0=t0, ticker=tk))
            mine.append(dict(ticker=tk, spot_ok=True,
                             k={str(k): dict(sk=99.9, sk3=(99.7 if mom else 100.05), sig15=0.001) for k in Q.KS}))
        data[d] = (dict(windows=ws, complete=True), dict(windows=mine, complete=True))
    return data


INSP = dict(series={}, inspected_ts=0)
P.use_reference = lambda insp, a: True
P.multiplier_at = lambda insp, a, t: 1.0
P.fee_problem = lambda insp, a: None
for planted, name in ((True, "planted"), (False, "null")):
    sep = {a: make_month(date(2026, 9, 1), date(2026, 9, 30), planted) for a in Q.ASSETS}
    mp = os.path.join(OUT, "model_%s.json" % name)
    model, msg = Q.fit(path=mp, insp=INSP, datas=sep)
    assert model, msg
    assert Q.fit(path=mp, insp=INSP, datas=sep)[0] is None                 # fitted once
    octo = make_month(date(2026, 10, 1), date(2026, 10, 31), planted)
    rp = os.path.join(OUT, "result_%s.json" % name)
    res, verdict = Q.score("BTC", out_path=rp, data=octo, insp=INSP, model=model)
    assert res, verdict
    print(name, verdict, res["rule"]["bets"], res.get("checks") and {k: res["checks"][k] for k in ("p_placebo", "p_exact", "p_boot", "t")})
    if planted:
        planted_model = model
        assert model["coef"][2] > 0                                         # momentum learned
        assert res["checks"]["passed"] and verdict.startswith("lead"), verdict
        assert res["rule"]["by_minute"]["10"]["bets"] == res["rule"]["bets"]   # first firing minute only
        assert res["checks"]["placebo_fallbacks"]["none"] == 0
    else:
        assert not verdict.startswith("lead"), verdict
    assert os.path.exists(rp) and os.path.exists(rp[:-5] + ".md")
    assert Q.score("BTC", out_path=rp, data=octo, insp=INSP, model=model)[0] is None   # scored once
    json.load(open(rp))

# the planted model on October data with no reversals: bets, but no edge
res, verdict = Q.score("BTC", out_path=os.path.join(OUT, "result_fail.json"),
                       data=make_month(date(2026, 10, 1), date(2026, 10, 31), False), insp=INSP, model=planted_model)
assert res["rule"]["bets"] >= 100 and verdict == Q.VERDICT_FAIL, verdict
print("fail path ok", res["rule"]["bets"], res["checks"]["p_exact"])

# first firing minute that does not fill: no later bet; the baseline likewise
wq = win(q7=(0.02, 0.03), result="no", ticker="U")
wq["c"]["11"] = [0.0, 0.03, 5.0]    # minute 11 shows no 0 < bid: k=10 cannot be paid
one = {date(2026, 10, 1): (dict(windows=[wq], complete=True),
                           dict(windows=[dict(ticker="U", spot_ok=True, k={str(k): dict(sk=99.9, sk3=99.7, sig15=0.001)
                                                                            for k in Q.KS})], complete=True))}
b1, c1, _, base1, n1 = Q.collect(one, planted_model, INSP, "BTC")
assert b1 == [] and n1["fired"] == 1 and sum(n1["unpaid"].values()) == 1 and base1 == [] and n1["base_unpaid"] == 1
assert {c["k"] for c in c1} == {12, 13}            # minute 11 has no bid: no cheap side there

# fine-fee-only verdict and the sign note
real_checks = Q.checks
Q.checks = lambda bets, cands, per, cent=False: dict(passed=not cent, days=31, mean=-0.01 if not cent else -0.02)
res, verdict = Q.score("BTC", out_path=os.path.join(OUT, "result_fine.json"),
                       data=make_month(date(2026, 10, 1), date(2026, 10, 31), True), insp=INSP, model=planted_model)
assert verdict == Q.VERDICT_FINE_ONLY and "differ in sign" in res.get("verdict_note", ""), (verdict, res.get("verdict_note"))
Q.checks = real_checks
bad_model = dict(planted_model, plan_sha256="x")
assert Q.score("BTC", out_path=os.path.join(OUT, "r_bad.json"), data=one, insp=INSP, model=bad_model)[0] is None

# October is not downloaded before the fit
Q.DATA = os.path.join(OUT, "dl")
Q.MODEL = os.path.join(OUT, "dl_model.json")
Q.identity_problems = lambda root=None: []
calls = []
def fake_read(path):
    return dict(windows=[dict(ticker="V", open=1e9, close=1e9 + 900)], complete=True), True
P._read_json = fake_read
P.fetch_spot = lambda a, lo, hi: calls.append(lo) or {}
ok, msg = Q.download(log=lambda m: None)
assert ok and "October waits for the fit" in msg, msg
assert len(calls) == 30 * 2                                     # September days only, both assets
assert not os.listdir(os.path.join(OUT, "dl")) if os.path.exists(os.path.join(OUT, "dl")) else True   # no usable minutes: nothing saved

# guard: missing Coinbase in more than 10% of windows -> not testable
octo = make_month(date(2026, 10, 1), date(2026, 10, 31), True)
for d in list(octo)[:5]:
    for m in octo[d][1]["windows"]:
        m["spot_ok"] = False
res, verdict = Q.score("BTC", out_path=os.path.join(OUT, "result_guard.json"), data=octo, insp=INSP, model=model)
assert verdict.startswith(Q.NOT_TESTABLE), verdict
assert Q.score("XRP", out_path=os.path.join(OUT, "x.json"))[0] is None
print("plan17 tests ok")
