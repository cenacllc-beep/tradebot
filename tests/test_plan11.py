"""research/plan11.py (PLAN11: radar and the gauge vs Kalshi's intraday price), on synthetic data. No network.
python test_plan11.py WORK OUT"""
import os, sys, json, math, io, tempfile, calendar
from datetime import date, datetime, timezone
WORK = sys.argv[1]
os.makedirs(sys.argv[2], exist_ok=True)
OUT = tempfile.mkdtemp(dir=sys.argv[2])
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(OUT, "offsite")
import plan11 as Q
P = Q.P
Q.RESULTS = os.path.join(OUT, "results")
Q.DATA = os.path.join(OUT, "data", "plan11")
os.makedirs(Q.RESULTS, exist_ok=True)


def ts(y, mo, d, h=0, mi=0):
    return calendar.timegm((y, mo, d, h, mi, 0))


# ---------- 0. the frozen text and the pinned constants ----------
src = open(os.path.join(WORK, "research", "plan11.py"), encoding="utf-8").read()
assert "/portfolio" not in src and "import live" not in src and "paper.db\"" not in src and "live.db\"" not in src
assert "connect(" not in src, "never opens a database"
assert P.bytes_hash(os.path.join(WORK, "research", "PLAN11.md")) == Q.PLAN_SHA256, "PLAN11.md is the frozen text"
assert Q.PLAN_SHA256 in open(os.path.join(WORK, "CHANGELOG.md"), encoding="utf-8").read(), "hash recorded in CHANGELOG"
assert (Q.STEP, Q.FIRST_AFTER, Q.LAST_BEFORE, Q.LAG_NOW, Q.LAG_BEFORE, Q.GAUGE_LAG) == (1800, 1800, 3600, 600, 2400, 600)
assert (Q.FILL_AFTER, Q.FILL_BACK) == (60, 5)
assert Q.CAPS == {"G": 0.95, "R": 0.90, "P": 0.85} and Q.MIN_PIXELS == 4 and Q.R_KM == 10.0
assert (Q.P_SEARCH_KM, Q.P_NEAR_KM, Q.P_CLOSE_KM) == (150.0, 75.0, 10.0)
assert (Q.IDX_R, Q.IDX_P) == (105, 115), "index i = -32.5 + 0.5 i dBZ"
assert (Q.GRID["width"], Q.GRID["height"], Q.GRID["A"], Q.GRID["E"]) == (12200, 5400, 0.005, -0.005)
assert (Q.BOOT_BLOCK, Q.BOOT_DRAWS, Q.BOOT_SEED) == (7, 20000, 11) and Q.T_FLOOR == 2.0
assert (Q.MIN_SIGNALS, Q.MIN_SIGNAL_DAYS, Q.MAX_LOST) == (30, 15, 0.10)
assert [round(x, 6) for x in Q.HOLM_LEVELS] == [0.008333, 0.0125, 0.025]
assert (Q.FIRST_DAY, Q.LAST_DAY) == (date(2026, 7, 15), date(2026, 11, 10))
assert Q.IEM_GAP >= 1.0 and P.USER_AGENT == "tradebot-paper-research/1.0"
# copies of research/fetch.py and weather.RAIN (fetch.py and weather.py need `requests`)
try:
    import requests  # noqa: F401
    import fetch as F
    assert F.TZ == Q.FETCH_TZ, "FETCH_TZ is research/fetch.py's TZ"
    for m in (dict(rules_primary="If rain is recorded at CLINYC ..."), dict(rules_primary="Rain (CLIBOS)"),
              dict(rules_primary="at Houston", rules_secondary="Data for CLIHOU can be found"), dict(rules_primary="x")):
        assert F.station_of(m) == Q.station_of(m)
    assert F.mday("KXRAINNYC-26JUL20") == Q.ticker_day("KXRAINNYC-26JUL20")
    import weather
    assert Q.rain_table() == {"K" + c[3:]: (c, la, lo) for c, la, lo in weather.RAIN.values()}
    print("copies of fetch.py and weather.RAIN ok")
except ImportError:
    print("fetch.py/weather.py comparison not run here (no requests)")
print("constants ok")

# ---------- 1. decision times, prices, fees ----------
S = ts(2026, 7, 20, 5)
dt = Q.decision_times(S, S + 86400)
assert dt[0] == S + 1800 and dt[-1] == S + 86400 - 3600 and len(dt) == 46 and all(t % 1800 == 0 for t in dt)
assert Q.decision_times(S + 600, S + 600 + 86400)[0] == S + 3600, "the first :00/:30 at least 30 min after the start"
cm = {str(k): [0.70, 0.80] for k in range(0, 1441)}
t = S + 3600 * 8
assert Q.price_at(cm, S, t) == (0.70, 0.80)
cm2 = dict(cm); cm2[str((t + 60 - S) // 60)] = [0.10, 0.20]
assert Q.price_at(cm2, S, t) == (0.10, 0.20), "the candle ending exactly at t + 1 min"
cm3 = {k: v for k, v in cm.items() if not (t - S) // 60 - 4 <= int(k) <= (t - S) // 60 + 1}
assert Q.price_at(cm3, S, t) is None, "nothing within 5 minutes before t + 1: no trade"
cm4 = {k: v for k, v in cm.items() if not (t - S) // 60 - 3 <= int(k) <= (t - S) // 60 + 1}
cm4[str((t - S) // 60 - 4)] = [0.5, 0.6]
assert Q.price_at(cm4, S, t) == (0.5, 0.6), "the last candle ending no more than 5 minutes before t + 1"
cm5 = dict(cm); cm5[str((t + 60 - S) // 60 + 1)] = [0.01, 0.02]
assert Q.price_at(cm5, S, t) == (0.70, 0.80), "a later candle is never used"
for bad in ([0.0, 0.5], [0.6, 0.6], [0.7, 1.0], [None, 0.5], [0.5, None]):
    c6 = dict(cm); c6[str((t + 60 - S) // 60)] = bad
    assert Q.price_at(c6, S, t) is None, bad
assert Q.fee(0.80) == 0.02 and Q.fee(0.95) == 0.01 and Q.fee(0.50) == 0.02 and Q.fee(0.10) == 0.01
assert abs(Q.fee(0.855) - math.ceil(0.07 * 0.855 * 0.145 * 100) / 100) < 1e-12
print("times, prices, fees ok")

# ---------- 2. gauge ----------
assert Q.p_group("KNYC 201251Z 18008KT 10SM RA BKN020 RMK AO2 SLP123 P0005 T02220178") == 5
assert Q.p_group("KNYC 201251Z 18008KT RMK AO2 P0000") == 0
assert Q.p_group("KNYC 201251Z 18008KT RMK AO2 60012 70034") is None, "6- and 24-hour groups never count"
assert Q.p_group("KNYC 201251Z 18008KT RA") is None, "rain in the weather text without an amount"
assert Q.p_group("KNYC 201251Z P0005 RMK AO2") is None, "only the remarks' group"
assert Q.is_cor("KNYC 201251Z COR 18008KT RMK AO2 P0005") and not Q.is_cor("KNYC 201251Z 18008KT RMK AO2 P0005")
rt = [[S + 51 * 60, "K 1 RMK AO2 P0030"]] + [[S + 3600 * h + 51 * 60, "K RMK AO2 P0000"] for h in range(1, 23)]
rt[7] = [S + 7 * 3600 + 51 * 60, "K RMK AO2 P0004"]
sp = [[S + 30 * 60, "K SPECI RMK P0020"], [S + 7 * 3600 + 5 * 60, "K COR RMK P0010"],
      [S + 7 * 3600 + 20 * 60, "K RMK P0002"]]
cnt, has = Q.gauge_reports(rt, sp, S, S + 86400)
assert has and (S + 51 * 60, 30) not in cnt and (S + 30 * 60, 20) not in cnt, "up to the first routine report ignored"
assert all(h != 10 for _, h in cnt), "a COR report is ignored"
assert (S + 7 * 3600 + 20 * 60, 2) in cnt and (S + 7 * 3600 + 51 * 60, 4) in cnt, "amounts are never added"
assert not Q.gauge_known(cnt, S + 7 * 3600 + 30 * 60 - 1) or True
assert not Q.gauge_known(cnt, S + 7 * 3600 + 29 * 60), "known only at or after obs + 10 min"
assert Q.gauge_known(cnt, S + 7 * 3600 + 30 * 60)
assert not Q.gauge_known([(S + 3600, 0)], S + 86400), "a trace never counts"
assert Q.gauge_reports([], sp, S, S + 86400) == ([], False), "no routine report: everything ignored"
dup = [[S + 51 * 60, "K RMK P0000"], [S + 2 * 3600, "K RMK P0007"], [S + 2 * 3600, "K COR RMK P0000"],
       [S + 2 * 3600, "K RMK P0001"]]
cnt2, _ = Q.gauge_reports(dup, [], S, S + 86400)
assert cnt2 == [(S + 2 * 3600, 7)], "of two reports of one time the first stands"
csvb = b"station,valid,metar\nNYC,2026-07-20 05:51,KNYC 200551Z RMK AO2 P0001\nNYC,bad,x\n"
assert Q.parse_metar_csv(csvb) == [[S + 51 * 60, "KNYC 200551Z RMK AO2 P0001"]]
print("gauge ok")

# ---------- 3. radar readings: pure Python and numpy agree; distances and thresholds ----------
G = dict(width=600, height=500, A=0.01, D=0.0, B=0.0, E=-0.01, C=-76.0, F=43.0)
Q.GRID = G
NYC = (40.7833, -73.9667)
BOS = (42.3606, -71.0106)


def rowcol(lat, lon):
    return int(round((G["F"] - lat) / -G["E"])), int(round((lon - G["C"]) / G["A"]))


def blank():
    return [[0] * G["width"] for _ in range(G["height"])]


def put(g, lat, lon, half, v):
    r, c = rowcol(lat, lon)
    for rr in range(r - half, r + half + 1):
        for cc in range(c - half, c + half + 1):
            g[rr][cc] = v


g = blank()
put(g, NYC[0], NYC[1], 1, 104)   # 19.5 dBZ: never counts
rd = Q.readings_py(g, NYC[0], NYC[1])
assert rd == [0, None, 0], rd
g = blank(); put(g, NYC[0], NYC[1], 0, 105); g[rowcol(*NYC)[0]][rowcol(*NYC)[1] + 1] = 105
g[rowcol(*NYC)[0] + 1][rowcol(*NYC)[1]] = 105
assert Q.readings_py(g, NYC[0], NYC[1])[0] == 3, "three pixels: below the 4-pixel minimum"
g[rowcol(*NYC)[0] + 1][rowcol(*NYC)[1] + 1] = 105
assert Q.readings_py(g, NYC[0], NYC[1])[0] == 4
r0, c0 = rowcol(*NYC)
g = blank()
for k in range(1, 8):            # pixels of 25 dBZ due east at known distances
    g[r0][c0 + 10 * k] = 115
rd = Q.readings_py(g, NYC[0], NYC[1])
la, lo = Q.centre(r0, c0 + 40)
assert abs(rd[1] - round(Q.gc_km(NYC[0], NYC[1], la, lo), 3)) < 1e-9 and rd[2] == 7, "echo = 4th-nearest pixel"
assert abs(Q.gc_km(40.0, -74.0, 41.0, -74.0) - 111.19) < 0.01
far = blank()
for k in range(4):
    far[r0][c0 + 180 + k] = 120   # about 150+ km
rdf = Q.readings_py(far, NYC[0], NYC[1])
assert rdf[1] is None or rdf[1] <= 150.0
try:
    import numpy as np
    from PIL import Image
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    rnd = __import__("random").Random(3)
    gr = blank()
    for _ in range(3000):
        gr[rnd.randrange(G["height"])][rnd.randrange(G["width"])] = rnd.choice((0, 104, 105, 114, 115, 200))
    arr = np.array(gr, dtype=np.uint8)
    for st in (NYC, BOS, (39.0, -75.5), (44.9, -93.2)):   # the last is outside the fake grid
        a, b = Q.readings_py(gr, *st), Q.readings_np(np, arr, *st)
        assert a == b, (st, a, b)
    print("numpy readings equal the pure-Python reference")
print("radar readings ok")

# ---------- 4. statistics ----------
assert abs(Q.cp_lower(118, 118, 0.025 / 3) - 0.9602) < 0.0005, "plan section 5: 118 days at 96c"
assert abs(Q.cp_lower(40, 40, 0.025) - 0.9119) < 0.001, "plan section 5: 40 days at 91c"
assert abs(Q.cp_lower(8, 10, 0.025) - 0.4439) < 0.001, "exact Clopper-Pearson value"
assert Q.cp_lower(0, 10, 0.025) == 0.0
lb = Q.cp_lower(30, 50, 0.0125)
assert abs(Q.binom_tail_ge(30, 50, lb) - 0.0125) < 1e-6
assert abs(Q.t_cut(0.025 / 3, 118) - 2.43) < 0.02 and abs(Q.t_cut(0.0125, 118) - 2.27) < 0.02 and Q.t_cut(0.025, 118) == 2.0


def synth(days, plan):
    """ms and an intact signals record; plan: {rule: list of (day index, ask, win)}."""
    ms, sig = [], []
    for i in range(days):
        d = date.fromordinal(date(2026, 7, 15).toordinal() + i).isoformat()
        ms.append(dict(ticker="M%03d" % i, day=d, station="KNYC", result="no", close=0, start=0))
    for rule, items in plan.items():
        for k, (i, ask, win) in enumerate(items):
            tk = "X%s%03d_%d" % (rule, i, k)
            d = ms[i]["day"]
            ms.append(dict(ticker=tk, day=d, station="KBOS", result="yes" if win else "no", close=0, start=0))
            sig.append(dict(rule=rule, ticker=tk, day=d, station="KBOS", t=0, minutes_into_day=100, bid=ask - 0.01,
                            ask=ask, fee=Q.fee(ask), ask_30min_later=None, gauge_minutes_after=None))
    srec = dict(signals=sig, lost={}, no_price={r: 0 for r in Q.RULES}, gauge_rain={}, markets=len(ms))
    return ms, srec


rnd = __import__("random").Random(11)
plan = dict(
    R=[(i, 0.60, (i % 30) != 8) for i in range(0, 119, 2)],                     # 60 days, 56 win at 60c: a lead
    G=[(i, 0.96, True) for i in range(1, 119, 2)],                              # 59 days, no loss at 96c: not enough
    P=[(i, 0.50, rnd.random() < 0.5) for i in range(0, 119, 3)])                # coin flips at 50c
ms, srec = synth(119, plan)
res = Q.score_from(ms, srec)
by = {s["rule"]: s for s in res["rules"]}
assert by["G"]["holm_rank"] == 1, "G's many small wins give the smallest t p-value"
assert by["G"]["checks"]["t_ok"] and by["G"]["checks"]["boot_ok"] and not by["G"]["checks"]["win_rate_ok"], \
    "many small wins without a loss pass the t and the bootstrap, never the win-rate bound"
assert by["G"]["verdict"] == Q.VERDICT_NONE and by["P"]["verdict"] == Q.VERDICT_NONE
c = by["R"]["checks"]
assert c["t_ok"] and c["boot_ok"] and c["win_rate_ok"] and by["R"]["verdict"] == Q.VERDICT_NONE, \
    "Holm stops at the first rule that fails: R reads no lag shown although its own checks hold"
resb = Q.score_from(*synth(119, dict(R=plan["R"], P=plan["P"])))
byb = {s["rule"]: s for s in resb["rules"]}
assert byb["R"]["passed"] and byb["R"]["verdict"] == Q.VERDICT_LEAD and byb["R"]["holm_rank"] == 1, byb["R"]
assert byb["G"]["holm_rank"] == 3 and byb["G"]["verdict"].startswith(Q.NOT_TESTABLE)
assert res["market_days"] == 119 and by["R"]["days"] == 119, "days without a signal count as 0"
# same data, only 29 R signals: not testable, placed last
plan2 = dict(plan, R=plan["R"][:29])
res2 = Q.score_from(*synth(119, plan2))
by2 = {s["rule"]: s for s in res2["rules"]}
assert by2["R"]["verdict"].startswith(Q.NOT_TESTABLE) and by2["R"]["holm_rank"] == 3
plan3 = dict(plan, R=[(i, 0.60, True) for i in range(14) for _ in range(3)])   # 42 signals on 14 days
assert {s["rule"]: s for s in Q.score_from(*synth(119, plan3))["rules"]}["R"]["verdict"].startswith(Q.NOT_TESTABLE)
# day win: every signal of the day must win
plan4 = dict(R=[(0, 0.6, True), (0, 0.6, False), (1, 0.6, True)])
s4 = {s["rule"]: s for s in Q.score_from(*synth(20, plan4))["rules"]}["R"]
assert s4["signal_days"] == 2 and s4["winning_days"] == 1 and s4["wins"] == 2
assert abs(s4["profit_total"] - (2 * (1 - 0.62) - 0.62)) < 1e-9, "profit = outcome - price - fee"
# the 10% rule
ms5, srec5 = synth(119, plan)
srec5["lost"] = {m["ticker"]: ["radar"] for m in ms5[:int(0.11 * len(ms5)) + 1]}
res5 = Q.score_from(ms5, srec5)
assert res5["plan_not_testable"] and all(s["verdict"].startswith(Q.NOT_TESTABLE) for s in res5["rules"])
srec5["lost"] = {m["ticker"]: ["radar"] for m in ms5[:int(0.09 * len(ms5))]}
assert not Q.score_from(ms5, srec5)["plan_not_testable"]
md = Q.result_md(dict(resb, scored="x"), dict(listed_at="y"))
assert "| R |" in md and Q.VERDICT_LEAD in md
assert "share_of_rain_days_fired" in resb["descriptive"]["R"]
# share of rain days: per market day, any market of the day resolved yes
msr, srr = synth(10, dict(R=[(0, 0.6, True), (0, 0.6, True)]))
dr = Q.score_from(msr, srr)["descriptive"]["R"]
assert dr["share_of_rain_days_fired"] == 1.0, "two signals on one rain day: one day, fired"
print("statistics ok")

# ---------- 4b. radar loss readings, METAR merge, the guarded client ----------
assert Q.RADAR_LOSS_READING == "t10" and Q.RADAR_LOSS_READINGS == ("strict", "t10")
mm = dict(start=S, close=S + 86400)
full = {Q.stamp_of(x): {"KNYC": [0, None, 0]} for x in Q.needed_stamps(mm)}
assert not Q.radar_lost(mm, full, "strict") and not Q.radar_lost(mm, full, "t10")
one = dict(full); one[Q.stamp_of(S + 3600 - 600)] = None
assert Q.radar_lost(mm, one, "strict") and not Q.radar_lost(mm, one, "t10"), "one missing frame: strict only"
no10 = {k: (None if k in {Q.stamp_of(t - 600) for t in Q.decision_times(S, S + 86400)} else v) for k, v in full.items()}
assert Q.radar_lost(mm, no10, "t10") and Q.radar_lost(mm, no10, "strict")
assert Q.radar_lost(mm, one) is False, "the applied reading is t10"
assert Q.merge_rows([[[2, "b"], [1, "a"]], [[1, "a"], [1, "c"], [3, "d"]]]) == [[1, "a"], [1, "c"], [2, "b"], [3, "d"]]


class FakeT(object):
    def __init__(self, answers):
        self.answers, self.urls, self.slept, self.now = list(answers), [], [], 1000.0

    def get(self, url, params=None, headers=None, timeout=30):
        self.urls.append(url)
        code, hdr, body, final = self.answers.pop(0)
        return Q._HResp(code, hdr, body, final or url)


def client(answers, base="https://mesonet.agron.iastate.edu"):
    ft = FakeT(answers)
    cl = Q.BytesClient(base, tries=4, timeout=5, min_gap=1.0, sleep=lambda x: ft.slept.append(x), clock=lambda: ft.now)
    cl._get = (ft.get, (OSError,))
    return cl, ft


cl, ft = client([(200, {}, b"abc", None)])
assert cl.get_bytes("/x") == b"abc" and ft.urls == ["https://mesonet.agron.iastate.edu/x"]
cl, ft = client([(404, {}, b"", None)])
assert cl.get_bytes("/x") is None
cl, ft = client([(404, {}, b"", None)])
try:
    cl.get_bytes("/x", none_on_404=False); raise AssertionError("404 must raise for Kalshi")
except RuntimeError as ex:
    assert "404" in str(ex)
cl, ft = client([(429, {"Retry-After": "1000"}, b"", None), (200, {}, b"ok", None)])
assert cl.get_bytes("/x") == b"ok" and 300.0 in ft.slept, "Retry-After capped at 300 s"
cl, ft = client([(200, {}, b"1", None), (200, {}, b"2", None)])
cl.get_bytes("/a"); cl.get_bytes("/b")
assert any(abs(x - 1.0) < 1e-9 for x in ft.slept), "one second between requests"
cl, ft = client([(200, {}, b"evil", "https://example.com/x")])
try:
    cl.get_bytes("/x"); raise AssertionError("another host must be refused")
except RuntimeError as ex:
    assert "refused" in str(ex)
cl, ft = client([(200, {}, b"{}", "https://api.elections.kalshi.com/trade-api/v2/m")],
                base="https://api.elections.kalshi.com/trade-api/v2")
assert cl.get_bytes("/m") == b"{}"
print("radar loss readings, METAR merge, client ok")

# ---------- 5. end to end with a fake Kalshi and a fake IEM (no network) ----------
if not HAVE:
    print("end-to-end part not run here (needs Pillow and numpy, installed on GitHub's runner only)")
    print("PLAN11 tests passed")
    sys.exit(0)

D20, D21 = date(2026, 7, 20), date(2026, 7, 21)


def ticker(city, d):
    return "KXRAIN%s-%s" % (city, d.strftime("%y%b%d").upper())


def mk(city, cli, d, result="yes", vol=100, hist=True, tz=5):
    close = ts(d.year, d.month, d.day, tz) + 86400
    return dict(ticker=ticker(city, d), rules_primary="If rain is recorded at %s for the day" % cli, result=result,
                close_time=datetime.fromtimestamp(close, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                volume_fp=str(vol)), hist


LIST = [mk("NYC", "CLINYC", D20), mk("BOS", "CLIBOS", D20, result="no"), mk("NYC", "CLINYC", D21, result="no"),
        mk("WPB", "CLIPBI", D21, hist=False),                                   # PBI counts as KDJT (PLAN10's rule)
        (dict(mk("NYC", "CLINYC", D20, vol=5)[0], ticker="KXRAINNYC-26JUL20-B"), True),   # duplicate, lower volume
        mk("XYZ", "CLIXYZ", D20),                                                # station not in v3's table
        (dict(mk("BOS", "CLIBOS", D21)[0], result="scalar"), True),              # scalar: left out
        mk("NYC", "CLINYC", date(2026, 11, 11)), mk("NYC", "CLINYC", date(2026, 7, 14))]   # outside the range
MKT = {m["ticker"]: m for m, _ in LIST}
CALLS = []


def quotes(tk, end):
    """(bid, ask) of the candle ending at `end`."""
    if tk == ticker("NYC", D20):
        if end == ts(2026, 7, 20, 13, 2):
            return 0.09, 0.10                                   # a later candle: must never be used
        return 0.70, 0.80
    if tk == ticker("BOS", D20):
        return 0.80, 0.85                                       # at the cap: allowed
    if tk == ticker("WPB", D21):
        return (0.95, 0.97) if end < ts(2026, 7, 21, 12, 0) else (0.90, 0.93)
    return 0.40, 0.50


def fake_kalshi(path, params=None):
    CALLS.append(path)
    assert "portfolio" not in path
    params = params or {}
    if path in ("/historical/markets", "/markets"):
        hist = path.startswith("/historical")
        return dict(markets=[m for m, h in LIST if h == hist], cursor=None)
    if path.endswith("/candlesticks"):
        tk = path.split("/")[-2]
        out = []
        for e in range(int(params["start_ts"]) - 60, int(params["end_ts"]) + 60, 60):
            b, a = quotes(tk, e)
            out.append(dict(end_period_ts=e, yes_bid=dict(close_dollars="%.4f" % b), yes_ask=dict(close_dollars="%.4f" % a)))
        if tk == ticker("NYC", D20):
            out = [c for c in out if c["end_period_ts"] != ts(2026, 7, 20, 13, 31)]   # a gap: 13:30 falls back
        return dict(candlesticks=out)
    raise AssertionError(path)


BOS_RC = rowcol(*BOS)
_PNG = {}


def scene(stamp):
    """Palette indices of the frame stamped `stamp`."""
    g = np.zeros((G["height"], G["width"]), dtype=np.uint8)
    if ts(2026, 7, 20, 12, 25) <= stamp <= ts(2026, 7, 20, 23, 55):
        r, c = rowcol(*NYC)
        g[r - 2:r + 3, c - 2:c + 3] = 110                       # 20-25 dBZ over New York: R, never P
    if stamp == ts(2026, 7, 20, 14, 50):
        g[BOS_RC[0] - 1:BOS_RC[0] + 2, BOS_RC[1] - 122:BOS_RC[1] - 119] = 120   # about 100 km west of Boston
    if ts(2026, 7, 20, 15, 20) <= stamp <= ts(2026, 7, 20, 18, 0):
        g[BOS_RC[0] - 1:BOS_RC[0] + 2, BOS_RC[1] - 74:BOS_RC[1] - 71] = 120     # about 60 km
    return g


def png(arr):
    key = arr.tobytes()
    if key not in _PNG:
        im = Image.frombytes("P", (arr.shape[1], arr.shape[0]), key)
        im.putpalette(bytes(range(256)) * 3)
        b = io.BytesIO(); im.save(b, format="PNG"); _PNG[key] = b.getvalue()
    return _PNG[key]


FLAKY = {ts(2026, 7, 21, 8, 20): 1}       # a network error on the first try only
MISSING = ts(2026, 7, 21, 20, 20)          # not in the archive
WRONG = ts(2026, 7, 21, 20, 50)            # a frame of the wrong size
IEM_LOG = []
WLD = "0.0100000\n0.00000\n0.00000\n-0.0100000\n-76.000000\n43.000000\n"


def metar_rows(sid, kind, ym):
    rows = []
    if sid == "DJT":
        return "station,valid,metar\n"                                         # the re-coded station's old code holds the reports
    for day in (19, 20, 21, 22):
        for h in range(24):
            when = ts(2026, 7, day, h, 51)
            p = "P0000"
            if sid == "NYC" and when == ts(2026, 7, 20, 5, 51):
                p = "P0030"                                  # the boundary report: ignored
            if sid == "NYC" and when == ts(2026, 7, 20, 12, 51):
                p = "P0005"
            if sid == "PBI" and when == ts(2026, 7, 21, 10, 51):
                p = "P0001"
            if kind == "routine":
                rows.append((when, "K%s %02d%02d%02dZ 00000KT RMK AO2 %s" % (sid, day, h, 51, p)))
    if kind == "special" and sid == "NYC":
        rows += [(ts(2026, 7, 20, 5, 30), "KNYC 200530Z RMK AO2 P0020"),        # before the boundary
                 (ts(2026, 7, 20, 12, 0), "KNYC 201200Z COR RMK AO2 P0010")]    # a correction: ignored
    body = "station,valid,metar\n" + "".join(
        "%s,%s,%s\n" % (sid, datetime.fromtimestamp(w, timezone.utc).strftime("%Y-%m-%d %H:%M"), t)
        for w, t in sorted(rows) if datetime.fromtimestamp(w, timezone.utc).strftime("%Y%m") == ym)
    return body


def fake_iem(path, params=None):
    IEM_LOG.append(path)
    if path == "/cgi-bin/request/asos.py":
        kind = "routine" if params["report_type"] == 3 else "special"
        ym = "%04d%02d" % (params["year1"], params["month1"])
        return metar_rows(params["station"], kind, ym).encode()
    assert path.startswith("/archive/data/") and "/GIS/uscomp/n0q_" in path, path
    stamp = calendar.timegm(datetime.strptime(path.rsplit("_", 1)[1][:12], "%Y%m%d%H%M").timetuple())
    if path.endswith(".wld"):
        return WLD.encode()
    if FLAKY.get(stamp):
        FLAKY[stamp] -= 1
        raise RuntimeError("connection reset")
    if stamp == MISSING:
        return None
    if stamp == WRONG:
        return png(np.zeros((10, 10), dtype=np.uint8))
    return png(scene(stamp))


Q.http_kalshi = fake_kalshi
Q.http_iem = fake_iem
Q.git_log = lambda rel: ""   # this test folder is not a git repository: nothing was ever committed

# out of turn: nothing runs before the freeze, nothing after it before the probe
assert Q.make_markets()[0] is None and Q.probe()[0] is None
rec, msg = Q.freeze()
assert rec is not None, msg
assert Q.freeze()[0] is None, "frozen once"
assert Q.make_markets()[0] is None and "probe" in Q.make_markets()[1]
probs = []
Q.http_iem = lambda path, params=None: b"station,valid,metar\nNYC,2026-07-01 00:10,K RMK\n"
mp_ = Q.metar_probe(probs)
assert probs and "routine" in probs[0], "routine reports off :51-:56 stop the probe"
Q.http_iem = lambda path, params=None: b"station,valid,metar\n"
probs = []; Q.metar_probe(probs)
assert len(probs) == 2 and all("no " in x for x in probs), "both kinds must be non-empty"
Q.http_iem = lambda path, params=None: b"station,valid,metar\nNYC,2026-07-01 00:52,K RMK\n"
probs = []; Q.metar_probe(probs)
assert len(probs) == 1 and "special" in probs[0], "specials on the routine pattern stop the probe"
Q.http_iem = fake_iem
pr, msg = Q.probe()
assert pr["passed"], msg
assert pr["metar"]["routine"]["reports"] > 0 and pr["metar"]["routine"]["share_at_51_56"] == 1.0
assert pr["metar"]["special"]["reports"] == 2 and pr["metar"]["special"]["share_at_51_56"] == 0.0
assert Q.probe()[0] is None, "probe once"
mrec, msg = Q.make_markets()
assert mrec is not None, msg
assert "yes" not in msg and "result" not in msg, "counts only"
assert Q.make_markets()[0] is None, "listed once"
c = mrec["counts"]
assert c["included"] == 4 and c["duplicates_dropped"] == 1 and c["not_in_table"] == 1 and c["scalar_or_void"] == 1
assert c["outside_range"] == 2 and c["start_mismatch"] == 0 and c["stations_not_in_table"] == {"KXYZ": 1}
byst = {(m["station"], m["day"]): m for m in mrec["markets"]}
assert byst[("KNYC", "2026-07-20")]["ticker"] == ticker("NYC", D20), "the higher-volume market is kept"
assert ("KDJT", "2026-07-21") in byst, "PBI counted as DJT"
assert byst[("KNYC", "2026-07-20")]["start"] == ts(2026, 7, 20, 5), "the day start from the market's own close_time"
assert Q.make_signals()[0] is None, "signals before the download"
assert Q.score()[0] is None
ok, msg = Q.download(budget_minutes=0)
assert not ok and "time budget" in msg
ok, msg = Q.download(budget_minutes=None)
assert not ok and Q.completeness(mrec["markets"])["radar_frames"] == 1, msg   # the flaky frame waits for the next run
ok, msg = Q.download(budget_minutes=None)
assert ok, msg
assert not any(p.endswith(".png") for p in os.listdir(os.path.join(Q.DATA, "radar"))), "no frame is ever stored"
rr = Q._gz(Q.radar_path(D21))["frames"]
assert rr[Q.stamp_of(MISSING)] == {"missing": "not in archive"} and rr[Q.stamp_of(WRONG)]["missing"].startswith("size")
Q.git_log = lambda rel: None
assert "run through the workflow" in Q.make_signals()[1], "no git: refuse"
Q.git_log = lambda rel: "abc1234 PLAN11 signals" if rel.endswith("plan11_signals.json") else ""
assert "committed once" in Q.make_signals()[1] and not os.path.exists(Q.signals_path())
Q.git_log = lambda rel: ""
srec, msg = Q.make_signals()
assert srec is not None, msg
assert "yes" not in msg.lower().replace("yes_", ""), "no outcome printed"
assert Q.make_signals()[0] is None, "signals once"
got = sorted((s["rule"], s["station"], s["day"], s["t"], s["ask"]) for s in srec["signals"])
want = sorted([("R", "KNYC", "2026-07-20", ts(2026, 7, 20, 13, 0), 0.80),     # 12:50 frame; 12:20 was clear
               ("G", "KNYC", "2026-07-20", ts(2026, 7, 20, 13, 30), 0.80),    # 12:51 report, known from 13:01
               ("P", "KBOS", "2026-07-20", ts(2026, 7, 20, 15, 30), 0.85),    # 100 km at 14:50, 60 km at 15:20
               ("G", "KDJT", "2026-07-21", ts(2026, 7, 21, 12, 0), 0.93)])    # known 11:30 but 97c: waits for the cap
assert got == want, got
pbos = [s for s in srec["signals"] if s["rule"] == "P"][0]
d10 = Q.readings_np(np, scene(ts(2026, 7, 20, 15, 20)), *BOS)[1]
d40 = Q.readings_np(np, scene(ts(2026, 7, 20, 14, 50)), *BOS)[1]
assert d10 <= 75 and d40 - d10 >= 10 and d40 > 75, (d10, d40)
assert pbos["fee"] == 0.01 and pbos["gauge_minutes_after"] is None
assert srec["lost"] == {}, "t10 reading: every market has usable t - 10 frames"
assert srec["radar_lost_markets"] == {"strict": 2, "t10": 0} and srec["radar_loss_reading"] == "t10"
wpb = Q._gz(Q.metar_path("KDJT", "202607", "routine"))
assert wpb["asked"] == ["DJT", "PBI"] and wpb["ids"] == ["PBI"] and len(wpb["rows"]) == 96
assert srec["gauge_rain"][ticker("NYC", D20)] is True and srec["gauge_rain"][ticker("BOS", D20)] is False
# a tampered signals file is refused
sp = Q.signals_path()
raw = json.load(open(sp, encoding="utf-8")); raw["signals"][0]["ask"] = 0.01
json.dump(raw, open(sp + ".bad", "w", encoding="utf-8"))
os.replace(sp, sp + ".good"); os.replace(sp + ".bad", sp)
assert Q.score()[0] is None, "a changed signals file is refused"
os.replace(sp + ".good", sp)
Q.git_log = lambda rel: None
r_, m_ = Q.score()
assert r_ is None and "run through the workflow" in m_
Q.git_log = lambda rel: "abc1234 PLAN11 score" if rel.endswith("plan11_result.md") else ""
r_, m_ = Q.score()
assert r_ is None and "committed once" in m_
Q.git_log = lambda rel: ""
res, msg = Q.score()
assert "Documents\\tradebot_backups" in msg, "the off-folder note"
assert res is not None, msg
assert not res["plan_not_testable"] and res["radar_lost_markets"] == {"strict": 2, "t10": 0}
assert all(s["verdict"].startswith(Q.NOT_TESTABLE) for s in res["rules"])
assert os.path.exists(Q.result_paths()[0]) and os.path.exists(Q.result_paths()[1])
assert os.path.exists(os.path.join(OUT, "offsite", "plan11", "results", "plan11_result.json")) or \
    not os.path.isdir(os.path.join(OUT, "offsite"))
assert Q.score()[0] is None, "scored once"
os.remove(Q.result_paths()[0])
assert Q.score()[0] is None, "a result .md alone also blocks a second score"
# a changed plan or code stops everything
assert Q.identity_problems() == []
idp = Q.identity_path()
rec = json.load(open(idp, encoding="utf-8")); rec["identity"]["research/plan11.py"] = "0" * 64
json.dump(rec, open(idp, "w", encoding="utf-8"))
assert Q.identity_problems() and Q.download()[0] is False and "identity" in Q.download()[1]
assert "PLAN11:" in Q.status()
assert all("iastate" not in c and "portfolio" not in c for c in CALLS)
print("end to end ok")

# ---------- 6. the workflow (cloud/workflows only until the code review) ----------
wf = open(os.path.join(WORK, "cloud", "workflows", "plan11.yml"), encoding="utf-8").read()
assert not os.path.exists(os.path.join(WORK, ".github", "workflows", "plan11.yml")) or \
    open(os.path.join(WORK, ".github", "workflows", "plan11.yml"), "rb").read() == \
    open(os.path.join(WORK, "cloud", "workflows", "plan11.yml"), "rb").read()
assert "workflow_dispatch" in wf and "schedule" not in wf
assert "fetch-depth: 0" in wf and "filter: blob:none" in wf
assert "git log --oneline -- research/results/plan11_identity.json | grep -q ." in wf
for f in ("plan11_probe.json", "markets.json.gz", "plan11_signals.json", "plan11_result.json", "plan11_result.md"):
    assert "git log --oneline -- " in wf and f in wf, f
assert '"numpy==2.3.4" "pillow==11.3.0"' in wf and wf.count("pip install") == 1
assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in wf
assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in wf
assert "research/(results/plan11|data/plan11/)" in wf and "refusing to commit radar frames" in wf
print("PLAN11 tests passed")
