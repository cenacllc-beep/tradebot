"""research/plan18.py (PLAN18: index exchanges, GARCH, shift detector), on synthetic data. No network.
Needs arch, ruptures and numpy (as on the GitHub runner). python test_plan18.py WORK OUT"""
import os, sys, json, math, random, tempfile
from datetime import date, timedelta
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
import plan18 as Q
P = Q.P
src = open(os.path.join(WORK, "research", "plan18.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "paper.db" not in src, "research only"
assert "create_order" not in src and "apiKey" not in src
assert P.bytes_hash(os.path.join(WORK, "research", "PLAN18.md")) == Q.PLAN_SHA256, "PLAN18.md is the frozen text"
assert (Q.K_G, Q.K_R, Q.K_M, Q.EDGE, Q.BAND, Q.R_N, Q.R_MIN, Q.R_LAST, Q.R_CUT, Q.RIDGE, Q.FAMILY, Q.T_FLOOR,
        Q.BOOT_BLOCK_DAYS, Q.BOOT_DRAWS, Q.PLACEBO_DRAWS, Q.SEED, Q.MIN_SIGNALS, Q.MIN_DAYS, Q.MIN_EXCHANGES,
        Q.GUARD_FROM, Q.COVERAGE_MIN) == \
       ((2, 5, 10, 13), (5, 10, 13), (2, 5, 10, 13), 0.04, (0.20, 0.80), 30, 3, 5, 2.0, 1.0, 0.025, 2.0, 2, 20000,
        2000, 18, 200, 20, 3, -30, 0.90), "the plan's numbers"
assert abs(Q.R_PEN - 3 * math.log(30)) < 1e-12
assert Q.FIT == (date(2026, 6, 1), date(2026, 7, 31)) and Q.TEST == (date(2026, 8, 1), date(2026, 8, 31))
assert Q.PINS == {"ccxt": "4.5.85", "arch": "8.0.0", "ruptures": "1.1.10"}
assert Q.REQUIRED == ("bitstamp", "coinbase", "cryptocom") and set(Q.OHLCV_EXCHANGES + Q.TRADES_EXCHANGES) == \
       {"bitstamp", "coinbase", "cryptocom", "bullish", "kraken"}

# ---------- 1. exchange reading ----------
class FakeEx(object):
    def __init__(self, rows=None, trades=None, step=1000):
        self.rows, self.trades, self.step, self.calls = rows or [], trades or [], step, 0
    def fetch_ohlcv(self, sym, tf, since=None, limit=None):
        self.calls += 1
        return [r for r in self.rows if r[0] >= since][:min(limit, self.step)]
    def fetch_trades(self, sym, since=None, limit=None, params=None):
        """Kraken-like: params since = seconds or a nanosecond cursor; whole-second resolution for seconds; the last
        row's info ends with the next cursor (the last trade's time in ns)."""
        self.calls += 1
        cur = int(params["since"])
        ms = cur // 10 ** 6 if cur > 10 ** 12 else cur * 1000
        strict = cur > 10 ** 12
        out = [dict(t) for t in self.trades if (t["timestamp"] > ms if strict else t["timestamp"] >= ms)][:min(limit, self.step)]
        if out:
            out[-1]["info"] = ["p", "a", out[-1]["timestamp"] / 1000.0, str(out[-1]["timestamp"] * 10 ** 6)]
        return out
t0 = 1_780_000_000 // 60 * 60
rows = [[(t0 + 60 * i) * 1000, 0, 0, 0, 100.0 + i, 1] for i in range(0, 200)]   # ccxt: start of minute
c = Q.ohlcv_closes(FakeEx(rows, step=37), "X", t0, t0 + 60 * 150, page=37)
assert c[t0 + 60] == 100.0 and c[t0 + 60 * 150] == 249.0 and len(c) == 150 and t0 not in c     # end = start + 60
trades = [dict(id=i, timestamp=(t0 + 10 * i) * 1000 + (0 if i % 6 else 0), price=float(i)) for i in range(1, 400)]
k = Q.trade_closes(FakeEx(trades=trades, step=50), "X", t0, t0 + 3000)
# a burst: 120 trades in one second, pages of 50 (seconds-based paging would stall; the cursor does not)
burst = [dict(id=1000 + j, timestamp=(t0 + 100) * 1000 + j, price=float(j)) for j in range(120)] + \
        [dict(id=2000 + j, timestamp=(t0 + 200 + 30 * j) * 1000, price=500.0 + j) for j in range(120)]
kb = Q.trade_closes(FakeEx(trades=burst, step=50), "X", t0, t0 + 3000)
assert kb[t0 + 120] == 119.0                                            # the burst's last trade closes its minute
# an empty middle page in the candles moves on instead of ending the day
gap = [r for r in rows if not (40 <= (r[0] // 1000 - t0) // 60 < 60)]
cg = Q.ohlcv_closes(FakeEx(gap, step=20), "X", t0, t0 + 60 * 150, page=20)
assert t0 + 60 * 41 not in cg and cg[t0 + 60 * 150] == 249.0 and len(cg) == 130
assert k[t0 + 60] == 6.0 and k[t0 + 120] == 12.0 and k[t0 + 3000] == 300.0   # trade at 60 s belongs to the minute ending then
try:
    Q.trade_closes(FakeEx(trades=trades[:100], step=50), "X", t0, t0 + 3000)
    raise AssertionError("an incomplete day must not give Kraken closes")
except RuntimeError:
    pass
d0 = date(2026, 6, 1)
T0 = int(P.day_start(d0))
def fake_fetch(fail=()):
    def f(name, a, b):
        if name in fail:
            raise RuntimeError("down")
        base = dict(bitstamp=100.0, coinbase=100.2, cryptocom=99.9, bullish=100.1, kraken=100.05)[name]
        return {a + 60 * i: base for i in range(1, 1441) if not (name == "bullish" and i % 2)}
    return f
comp = Q.build_comp("BTC", d0, fake_fetch())
assert comp["S"][0] == round(100.025, 2) and comp["N"][0] == 4 and comp["N"][1] == 5 and comp["S"][1] == 100.05
assert comp["CB"][0] == 100.2 and abs(comp["DISP"][0] - (math.sqrt(sum((v - 100.0333333) ** 2 for v in (100.0, 100.2, 99.9)) / 2) / comp["S"][0])) < 1e-9
comp2 = Q.build_comp("BTC", d0, fake_fetch(("bullish", "kraken")))
import ccxt
def net(name, a, b):
    if name == "kraken":
        raise ccxt.RequestTimeout("slow")
    return fake_fetch()(name, a, b)
try:
    Q.build_comp("BTC", d0, net)
    raise AssertionError("a transient Kraken fault must not save the day without Kraken")
except RuntimeError:
    pass
def nearly(name, a, b):
    out = fake_fetch()(name, a, b)
    if name == "coinbase":
        for e in list(out)[:20]:
            del out[e]
    return out
try:
    Q.build_comp("BTC", d0, nearly)
    raise AssertionError("a required exchange missing 20 minutes must not save the day")
except Q.Short as sh:
    assert sh.name == "coinbase" and sh.n == 1420
assert Q.build_comp("BTC", d0, nearly, accept_short=True)["CB"][0] is None   # after SHORT_TRIES runs: saved as it is
class Back(FakeEx):
    def fetch_trades(self, sym, since=None, limit=None, params=None):
        out = FakeEx.fetch_trades(self, sym, since, limit, params)
        if out:
            out[-1]["info"][-1] = "7"   # a cursor that does not grow
        return out
try:
    Q.trade_closes(Back(trades=trades, step=50), "X", t0, t0 + 3000)
    raise AssertionError("a cursor that does not grow must stop the day")
except RuntimeError:
    pass
assert set(comp2["absent"]) == {"bullish", "kraken"} and comp2["N"][0] == 3 and comp2["S"][0] == 100.0
for f in ("coinbase",):
    try:
        Q.build_comp("BTC", d0, fake_fetch((f,)))
        raise AssertionError("a required exchange failing must not save the day")
    except RuntimeError:
        pass
def thin(name, a, b):
    return {a + 60: 1.0} if name == "bitstamp" else fake_fetch()(name, a, b)
try:
    Q.build_comp("BTC", d0, thin)
    raise AssertionError("a required exchange with too few minutes must not save the day")
except RuntimeError:
    pass
assert Q.mcnemar(0, 0) == 1.0 and abs(Q.mcnemar(0, 5) - 2 / 32.0) < 1e-12
print("exchanges ok")

# ---------- 2. GARCH, horizon, shift detector ----------
g = dict(omega=1.0, alpha=0.1, beta=0.8, backcast=10.0)
v = 1.0 / 0.1
assert abs(Q.horizon_var(g, v, 10) - (15 - 10 - 2 / 3.0) * v) < 1e-9                       # at the long-run level
hv = Q.horizon_var(g, 20.0, 13)
assert abs(hv - (15 - 13 - 2 / 3.0) * (20.0 + (v + 0.9 * (20 - v))) / 2) < 1e-9
assert abs(Q.horizon_var(dict(omega=1.0, alpha=0.5, beta=0.5), 4.0, 13) - (4 / 3.0) * (4.0 + 5.0) / 2) < 1e-9   # IGARCH

# ---------- 3. synthetic months: fit and score ----------
Q.FIRST_COMP_DAY = date(2026, 5, 31)
Q.FIT = (date(2026, 6, 1), date(2026, 6, 10))
Q.TEST = (date(2026, 6, 11), date(2026, 7, 2))
Q.BOOT_DRAWS, Q.PLACEBO_DRAWS = 2000, 400   # 1/401 < Holm's first level 0.42%
P.multiplier_at = lambda insp, a, t: 1.0
P.fee_problem = lambda insp, a: None
INSP = {"x": 1}
rng = random.Random(5)


def make(planted, seed):
    rng = random.Random(seed)
    comps, kal = {}, {}
    price = 30000.0
    sig = 3.0   # bp a minute
    allS = []
    for d in P.days_of(Q.FIRST_COMP_DAY, Q.TEST[1]):
        S = []
        for i in range(1440):
            price *= math.exp(rng.gauss(0, sig) / 1e4)
            S.append(round(price, 2))
        comps[d] = dict(S=S, CB=[s * 1.0001 for s in S], DISP=[0.0002] * 1440, N=[5] * 1440, present={}, absent={},
                        complete=True)
        allS.append((int(P.day_start(d)), S))
    def at(ts):
        for st, S in allS:
            j = int((ts - st) / 60) - 1
            if 0 <= j < 1440:
                return S[j]
        return None
    for d in P.days_of(Q.FIT[0], Q.TEST[1]):
        ws = []
        for j in range(96):
            cl = int(P.day_start(d)) + 900 * (j + 1)
            o = cl - 900
            s0 = at(o)
            sc = at(cl)
            c = {}
            for m in range(1, 16):
                sm = at(o + 60 * m)
                left = max(15 - m - 2 / 3.0, 1 / 3.0)
                p = P.phi(1e4 * math.log(sm / s0) / (sig * math.sqrt(left)))
                if planted:
                    p = 0.5   # a stale market: always 49/51
                bid = min(max(round(p - 0.01, 2), 0.01), 0.97)
                c[str(m)] = [bid, round(bid + 0.02, 2), 10.0]
            ws.append(dict(ticker="T%s-%d" % (d, j), open=o, close=cl, strike=s0, strike_type="greater_or_equal",
                           result="yes" if sc >= s0 else "no", c=c, t={str(m): 30.0 for m in range(1, 16)}))
        kal[d] = dict(windows=ws, complete=True)
    return comps, kal


for planted, name in ((True, "planted"), (False, "fair")):
    datas = {}
    for a in Q.ASSETS:
        comps, kal = make(planted, 11 if a == "BTC" else 12)
        datas[a] = (comps, kal)
    fitdata = {a: ({d: v for d, v in datas[a][0].items() if d <= Q.FIT[1]},
                   {d: v for d, v in datas[a][1].items() if d <= Q.FIT[1]}) for a in Q.ASSETS}
    mp = os.path.join(OUT, "model_%s.json" % name)
    model, msg = Q.fit(path=mp, data=fitdata)
    assert model, msg
    g = model["assets"]["BTC"]["garch"]
    assert 0 <= g["alpha"] < 1 and 0 <= g["beta"] < 1 and g["n"] > 10000, g
    assert Q.fit(path=mp, data=fitdata)[0] is None
    testdata = {a: (datas[a][0], {d: v for d, v in datas[a][1].items() if d >= Q.TEST[0]}) for a in Q.ASSETS}
    rp = os.path.join(OUT, "result_%s.json" % name)
    res, verdict = Q.score(out_path=rp, data=testdata, insp=INSP, model=model)
    assert res, verdict
    byname = {x["name"]: x for x in res["tests"]}
    print(name, verdict, {n: (x["stats"]["signals"], round(x["stats"].get("mean") or 0, 4), x.get("verdict")) for n, x in byname.items()})
    q = res["assets"]["BTC"]["q1"]
    assert q["windows"] > 1000 and q["composite_agree"] == 1.0
    if planted:
        assert byname["BTC G"]["passed"] and byname["ETH G"]["passed"], verdict
    else:
        assert not byname["BTC G"].get("passed") and not byname["ETH G"].get("passed"), verdict
    assert os.path.exists(rp) and os.path.exists(rp[:-5] + ".md")
    assert Q.score(out_path=rp, data=testdata, insp=INSP, model=model)[0] is None
    json.load(open(rp))

# shift detector on a planted jump at the end of a window
comps, kal = make(False, 3)
ser = Q.Series({d: v for d, v in comps.items() if d <= date(2026, 6, 3)}, "S")
ser.run_filter(dict(omega=0.9, alpha=0.05, beta=0.85, backcast=9.0))
w = kal[date(2026, 6, 2)]["windows"][40]
ik = ser.idx(int(w["open"]) + 60 * 10)
for i in range(ik - 3, ik + 1):
    ser.r[i] = 25.0
rr = Q.r_reading(ser, w, 10)
assert rr[0] and rr[1] > 2.0, rr
ser.r[ik - 10] = None
assert Q.r_reading(ser, w, 10) is None

# placebo: an unpayable flip keeps its own side; Holm keeps a not-testable test in the family, ranked last
fs = [dict(day=date(2026, 8, 1), ticker="A", profit=0.5, flip=None), dict(day=date(2026, 8, 1), ticker="B", profit=0.5, flip=-0.5)]
assert Q.placebo_p(fs, 0.5, draws=200) > 0.3
tests = [dict(name="X G", stats=dict(not_testable="few", signals=0)), dict(name="X R", stats=dict(p_t=0.0, t=9.0, df=30, mean=0.1), dm={date(2026, 8, 1): 0.1}, fs=[dict(day=date(2026, 8, 1), ticker="A", profit=0.1, flip=-0.1)])]
order = Q.holm(tests, [date(2026, 8, 1)])
assert order[-1]["name"] == "X G" and order[-1]["verdict"] == Q.NOT_TESTABLE and order[0]["holm_level"] == 0.025 / 2
# guard: raw Kalshi candles missing in more than 10% of windows
ser_g = Q.Series({d: v for d, v in comps.items() if d <= date(2026, 6, 4)}, "S")
kg = {date(2026, 6, 3): dict(windows=[dict(w, c={}) if i < 20 else w for i, w in enumerate(kal[date(2026, 6, 3)]["windows"])])}
why, share = Q.guard(ser_g, kg)
assert why and abs(share - 20 / 96.0) < 1e-9, (why, share)

# amendments: an approved chain from the recorded hash to the current one is accepted; anything else is refused
st = {"f": {"a": "b", "b": "c"}}
assert Q._reaches(st["f"], "a", "c") and Q._reaches({}, "x", "x") and not Q._reaches(st["f"], "a", "d")
assert not Q._reaches({"a": "b", "b": "a"}, "a", "z")
am = os.path.join(OUT, "am.json")
json.dump(dict(amendments=[dict(id="A1", approved_by_user=True, files={"f": {"old": "a", "new": "b"}}),
                           dict(id="X", approved_by_user=False, files={"g": {"old": "a", "new": "b"}})]), open(am, "w"))
assert Q.amendment_steps(am) == {"f": {"a": "b"}} and Q.amendment_ids(am) == ["A1"]
open(am, "w").write("{broken")
assert Q.amendment_steps(am) == {} and Q.amendment_ids(am) == []
json.dump(dict(amendments=[dict(id="A1", approved_by_user="no", files={"f": {"old": "a", "new": "b"}}),
                           dict(id="", approved_by_user=True, files={"f": {"old": "a", "new": "b"}})]), open(am, "w"))
assert Q.amendment_steps(am) == {} and Q.amendment_ids(am) == []          # only a literal True with an id approves
json.dump(dict(amendments=[dict(id="A1", approved_by_user=True, files={"f": {"old": "a", "new": "b"}}),
                           dict(id="A2", approved_by_user=True, files={"f": {"old": "a", "new": "c"}})]), open(am, "w"))
assert Q.amendment_steps(am) == {}                                         # two steps from one hash: damaged
# identity_problems end to end: a changed file passes only through an approved chain
idp = os.path.join(OUT, "id.json")
now = Q.identity_now(WORK)
rec = dict(identity=dict(now, **{"research/plan18.py": "old-hash"}))
json.dump(rec, open(idp, "w"))
def probs(amend):
    return [b for b in Q.identity_problems(WORK, path=idp, pins=False, amend_path=amend) if "plan18.py" in b]
json.dump(dict(amendments=[dict(id="A1", approved_by_user=True,
                                files={"research/plan18.py": {"old": "old-hash", "new": now["research/plan18.py"]}})]), open(am, "w"))
assert probs(am) == []
open(am, "w").write("{broken")
assert probs(am) == ["research/plan18.py"]
json.dump(dict(amendments=[dict(id="A1", approved_by_user=False,
                                files={"research/plan18.py": {"old": "old-hash", "new": now["research/plan18.py"]}})]), open(am, "w"))
assert probs(am) == ["research/plan18.py"]
# an integrated GARCH within tolerance is kept (integrated=True); an explosive one is refused
import arch.univariate.base as AB
class FakeRes(object):
    def __init__(self, a, b):
        import pandas as pd
        self.params = pd.Series({"omega": 0.117, "alpha[1]": a, "beta[1]": b})
        self.loglikelihood, self.convergence_flag = -1.0, 0
real_fit = AB.ARCHModel.fit
AB.ARCHModel.fit = lambda self, **kw: FakeRes(0.0588, 0.94122)
g1 = Q.fit_garch([1.0, -2.0, 0.5] * 100)
assert g1["integrated"] is True and abs(g1["alpha"] + g1["beta"] - 1.00002) < 1e-9
AB.ARCHModel.fit = lambda self, **kw: FakeRes(0.3, 1.0)
try:
    Q.fit_garch([1.0, -2.0, 0.5] * 100)
    raise AssertionError("an explosive GARCH must be refused")
except RuntimeError:
    pass
AB.ARCHModel.fit = lambda self, **kw: FakeRes(0.05, 0.9)
assert Q.fit_garch([1.0, -2.0, 0.5] * 100)["integrated"] is False
AB.ARCHModel.fit = real_fit
# the horizon variance joins smoothly at alpha + beta = 1
for k in (2, 5, 10):
    lo = Q.horizon_var(dict(omega=0.117, alpha=0.0588, beta=1 - 0.0588 - 1e-10), 30.0, k)
    hi = Q.horizon_var(dict(omega=0.117, alpha=0.0588, beta=0.94122), 30.0, k)
    assert abs(lo - hi) / hi < 1e-3, (k, lo, hi)

# a model fitted under another plan is refused
bad = dict(model, plan_sha256="x")
assert Q.score(out_path=os.path.join(OUT, "r_bad.json"), data=testdata, insp=INSP, model=bad)[0] is None

# August (here: the test period) is not downloaded before the fit
Q.identity_problems = lambda root=None, path=None, pins=True: []
Q.DATA = os.path.join(OUT, "dl")
Q.MODEL = os.path.join(OUT, "dl_model.json")
seen = []
Q.build_comp = lambda a, d, accept_short=False: seen.append(d) or dict(S=[1.0] * 1440, complete=True)
P.market_list = lambda a, f, l, n: {}
P.build_day = lambda a, d, ms, u: dict(windows=[], complete=True)
ok, msg = Q.download(log=lambda m: None)
assert ok and "waits for the fit" in msg and max(seen) == Q.FIT[1], (msg, max(seen))
print("plan18 tests ok")
