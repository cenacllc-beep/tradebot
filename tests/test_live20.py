"""research/live20.py (PLAN20's forward logger), on fake Kalshi answers and a fake clock. No network.
python test_live20.py WORK OUT"""
import os, sys, json, types, gzip, shutil
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
DATA = os.path.join(OUT, "live20")
os.environ["LIVE20_DATA"] = DATA
os.environ["LIVE20_SERIES"] = os.path.join(OUT, "plan20_series.json")
os.environ["LIVE20_MODEL"] = os.path.join(OUT, "plan20_model.json")
os.environ["LIVE20_MODEL_SHA"] = os.path.join(OUT, "plan20_model_sha256.json")
os.environ["LIVE20_RESULT"] = os.path.join(OUT, "plan20_result.json")
sys.path.insert(0, os.path.join(WORK, "research")); sys.path.insert(0, WORK)
sys.modules.pop("plan20", None)
import live20 as L
from datetime import datetime, timezone

# ---- the module never touches orders, live.py or the bot's databases
src = open(os.path.join(WORK, "research", "live20.py"), encoding="utf-8").read()
assert "/portfolio" not in src, "live20 must never call an order endpoint"
assert "import live\n" not in src and "import live " not in src and "from live " not in src and "import live," not in src
code = src.split('"""', 2)[2]
for bad in ("paper.db", "live.db", "trial/", "post(", "delete(", ".put("):
    assert bad not in code, bad
assert "live" not in [m.split(".")[0] for m in sys.modules if m == "live"], "live.py was imported"

def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---- one snapshot row and the NO side (PLAN20 section 2: no_ask = 1 - yes_bid, no_bid = 1 - yes_ask)
T0 = 1795000500 - (1795000500 % 900)   # a window boundary
m = dict(ticker="KXSOL15M-A-00", event_ticker="KXSOL15M-A", open_time=iso(T0), close_time=iso(T0 + 900),
         status="active", yes_bid_dollars="0.0300", yes_ask_dollars="0.0500", last_price_dollars="0.0400",
         volume_fp="120.00", open_interest_fp="80.00")
r = L.snap_row(m, "KXSOL15M", T0 + 60, T0 + 65.04)
assert r["yes_bid"] == 0.03 and r["yes_ask"] == 0.05 and r["no_bid"] == 0.95 and r["no_ask"] == 0.97, r
assert r["last"] == 0.04 and r["volume"] == 120.0 and r["oi"] == 80.0 and r["open"] == T0 and r["close"] == T0 + 900
assert r["minute"] == T0 + 60 and r["ts"] == 65.0 + T0 and r["series"] == "KXSOL15M" and r["event"] == "KXSOL15M-A"
old = L.snap_row(dict(ticker="X", yes_bid=3, yes_ask=5, last_price=4, volume=7, open_interest=2), "S", T0, T0)   # cents shape
assert (old["yes_bid"], old["yes_ask"], old["no_bid"], old["no_ask"], old["last"], old["volume"], old["oi"]) == (0.03, 0.05, 0.95, 0.97, 0.04, 7.0, 2.0), old
emp = L.snap_row(dict(ticker="X"), "S", T0, T0)
assert emp["no_bid"] is None and emp["no_ask"] is None and L.snap_row(dict(), "S", T0, T0) is None
assert L._epoch("2026-12-01") == datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()
assert L._epoch("2026-12-01T05:00:00") == L._epoch("2026-12-01T05:00:00Z") == L._epoch("2026-12-01T01:00:00-04:00")
print("rows ok")

# ---- series: the file first (several shapes), else /series filtered to 15M
json.dump({"series": [{"ticker": "KXSOL15M", "group": "crypto"}, {"ticker": "KXGOLD15M", "group": "metals"}]},
          open(os.environ["LIVE20_SERIES"], "w"))
assert L.series_from_file() == (["KXGOLD15M", "KXSOL15M"], {"KXSOL15M": "crypto", "KXGOLD15M": "metals"})
json.dump({"KXSOL15M": "crypto"}, open(os.environ["LIVE20_SERIES"], "w"))
assert L.series_from_file() == (["KXSOL15M"], {"KXSOL15M": "crypto"})
os.remove(os.environ["LIVE20_SERIES"])
calls = []
def api_series(path, params=None):
    calls.append((path, params))
    if path == "/series":
        if not params:
            return {"series": [{"ticker": "KXSOL15M"}, {"ticker": "KXBTCD"}], "cursor": "c2"}
        return {"series": [{"ticker": "KXGOLD15M"}, {"ticker": "KXGOLD"}], "cursor": ""}
    raise AssertionError(path)
L.http = api_series
assert L.series_list()[:2] == (["KXGOLD15M", "KXSOL15M"], {}) and len(calls) == 2
print("series ok")

# ---- a fake world: two series, a fake clock that sleeps by moving forward
clock = [T0 + 30.0]
L.now = lambda: clock[0]
L.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
FAIL, SLOW = set(), {}
def market(series, k, o, yb, ya):
    return dict(ticker="%s-W%d-%02d" % (series, o, k), event_ticker="%s-W%d" % (series, o), open_time=iso(o),
                close_time=iso(o + 900), status="active", yes_bid_dollars="%.4f" % yb, yes_ask_dollars="%.4f" % ya,
                last_price_dollars="%.4f" % ya, volume_fp="%.2f" % (clock[0] // 60), open_interest_fp="10.00")
def kalshi(path, params=None):
    calls.append((path, params))
    if path == "/series":
        return {"series": [{"ticker": "KXSOL15M"}, {"ticker": "KXGOLD15M"}]}
    if path == "/markets":
        s = params["series_ticker"]
        minute = int(clock[0] // 60) * 60
        if (s, minute) in FAIL:
            raise RuntimeError("giving up on /markets")
        clock[0] += SLOW.get((s, minute), 0.3)
        o = int(minute // 900) * 900
        return {"markets": [market(s, 0, o, 0.03, 0.05), market(s, 1, o, 0.40, 0.45)]}
    raise AssertionError(path)
L.http = kalshi
calls.clear()
FAIL.add(("KXGOLD15M", T0 + 120))               # one failing request at minute 2
SLOW[("KXSOL15M", T0 + 180)] = 100               # minute 3's read takes 100 s: minute 4 cannot start in time
assert L.run(6) == 0
snaps = list(L.snapshots())
mins = sorted(set(x["minute"] for x in snaps))
assert mins == [T0 + 60, T0 + 120, T0 + 180, T0 + 300, T0 + 360], [(x - T0) // 60 for x in mins]
assert len([x for x in snaps if x["minute"] == T0 + 120]) == 2 and all(x["series"] == "KXSOL15M" for x in snaps if x["minute"] == T0 + 120)
assert len([x for x in snaps if x["minute"] == T0 + 60]) == 4
logs = [json.loads(l) for l in open(os.path.join(DATA, "log.jsonl"))]
gaps = [x for x in logs if x["kind"] == "gap"]
errs = [x for x in logs if x["kind"] == "error"]
assert [g["minute"] for g in gaps] == [T0 + 240] and "late" in gaps[0]["why"], gaps
assert len(errs) == 1 and errs[0]["series"] == "KXGOLD15M" and errs[0]["minute"] == T0 + 120, errs
assert all(abs(x["ts"] - x["minute"] - L.OFFSET) < 105 for x in snaps)
assert all(p in ("/series", "/markets") for p, _ in calls) and not any(p.startswith("/portfolio") for p, _ in calls)
# snapshots: one small gzip file per 30-minute UTC chunk; nothing left plain after the run, no whole-day file
assert os.path.exists(os.path.join(DATA, "snap-%s.jsonl.gz" % L.chunk_of(T0 + 60)))
assert not os.path.exists(os.path.join(DATA, "snap-%s.jsonl" % L.chunk_of(T0 + 60)))
assert not [f for f in os.listdir(DATA) if f.startswith("snap-") and not f.endswith(".gz")], os.listdir(DATA)
assert not os.path.exists(os.path.join(DATA, "snap-%s.jsonl" % L.day_of(T0 + 60)))
assert L.chunk_of(1795000500 - 1795000500 % 1800) == L.chunk_of(1795000500 - 1795000500 % 1800 + 1799)
assert L.chunk_of(1795000500 - 1795000500 % 1800 + 1800) != L.chunk_of(1795000500 - 1795000500 % 1800)
assert L.chunk_of(datetime(2026, 12, 1, 10, 47, tzinfo=timezone.utc).timestamp()) == "20261201-1030"
print("run ok: minutes", [(x - T0) // 60 for x in mins], "gap at minute 4, one failed request logged")

# every request failing: the minute is a gap row, the loop goes on and ends on time
def down(path, params=None):
    if path == "/series":
        return kalshi(path, params)
    raise RuntimeError("network down")
L.http = down
start = clock[0]; assert L.run(2) == 0
assert clock[0] <= start + 125
logs = [json.loads(l) for l in open(os.path.join(DATA, "log.jsonl"))]
assert sum(1 for x in logs if x["kind"] == "gap" and x["why"] == "every request failed") == 2
st = L.status()
assert st["minutes_logged"] == 5 and st["gap_rows"] == 3 and st["markets"] == 4 and st["series"] == 2 and st["paper_bets"] is None
assert not any(k for k in st if "pnl" in k or "profit" in k or "net" in k)
print("resilience ok")

# ---- torn-line appends: a line torn by a crash never swallows the next row
MAIN_DATA = L.DATA
L.DATA = os.path.join(OUT, "live20_side"); os.makedirs(L.DATA)
tp = os.path.join(L.DATA, "log.jsonl")
with open(tp, "w", encoding="utf-8") as fh:
    fh.write('{"kind":"run_start","ts":1}\n{"kind":"gap","mi')          # crash mid-line
L.log_row("gap", minute=5)
got = [json.loads(x) for x in open(tp, encoding="utf-8").read().splitlines() if x.startswith("{") and x.endswith("}")]
assert [g["kind"] for g in got] == ["run_start", "gap"] and got[1]["minute"] == 5, open(tp).read()
from tbcommon import jsonio as _jio
assert len(_jio.lines(tp)) == 2, "the torn line alone is skipped, both whole rows are read"
L.append_rows(tp, [dict(kind="x")]); L.append_rows(tp, [])
assert open(tp, "rb").read().endswith(b'{"kind":"x"}\n') and b"\n\n" not in open(tp, "rb").read()
L.append_rows(os.path.join(L.DATA, "new.jsonl"), [dict(a=1)])
assert open(os.path.join(L.DATA, "new.jsonl"), "rb").read() == b'{"a":1}\n', "an empty file gets no leading newline"
tsnap = os.path.join(L.DATA, "snap-%s.jsonl" % L.chunk_of(T0))
with open(tsnap, "w", encoding="utf-8") as fh:
    fh.write('{"minute":%d,"ticker":"A","series":"S"}\n{"minute":%d,"tick' % (T0, T0 + 60))
L.append_rows(tsnap, [dict(minute=T0 + 60, ticker="B", series="S")])
assert [(r["minute"], r["ticker"]) for r in L.snapshots()] == [(T0, "A"), (T0 + 60, "B")]

# a chunk written by two runs: the .gz is merged, a (minute, ticker) kept once
L.compact()
assert os.path.exists(tsnap + ".gz") and not os.path.exists(tsnap)
L.append_rows(tsnap, [dict(minute=T0 + 60, ticker="B", series="S"), dict(minute=T0 + 120, ticker="C", series="S")])
L.compact(keep=L.chunk_of(T0))
assert os.path.exists(tsnap), "the chunk being written is not compacted"
L.compact()
assert [(r["minute"], r["ticker"]) for r in L.snapshots()] == [(T0, "A"), (T0 + 60, "B"), (T0 + 120, "C")]
# old formats are still read: a whole-day plain file and a whole-day gz, next to the chunks
old_day = L.day_of(T0 - 86400)
with gzip.open(os.path.join(L.DATA, "snap-%s.jsonl.gz" % old_day), "wt", encoding="utf-8") as fh:
    fh.write(json.dumps(dict(minute=T0 - 86400, ticker="OLDGZ", series="S")) + "\n")
with open(os.path.join(L.DATA, "snap-%s.jsonl" % L.day_of(T0)), "w", encoding="utf-8") as fh:
    fh.write(json.dumps(dict(minute=T0 - 60, ticker="OLDPLAIN", series="S")) + "\n")
assert {r["ticker"] for r in L.snapshots()} == {"OLDGZ", "OLDPLAIN", "A", "B", "C"}
assert L.compact(today=L.day_of(T0)) is None and os.path.exists(os.path.join(L.DATA, "snap-%s.jsonl" % L.day_of(T0))), \
    "an old-format plain file of today is not compacted"

# a run crossing a 30-minute boundary closes the first chunk while it runs
shutil.rmtree(L.DATA); os.makedirs(L.DATA)
L.http = kalshi
FAIL.clear(); SLOW.clear()
b0 = (int(clock[0] // 1800) + 1) * 1800
clock[0] = b0 - 3 * 60 - 10
seen_files = []
real_snapshot = L.snapshot
def spy_snapshot(series, minute):
    seen_files.append(sorted(os.listdir(L.DATA)))
    return real_snapshot(series, minute)
L.snapshot = spy_snapshot
assert L.run(6) == 0
L.snapshot = real_snapshot
first, second = L.chunk_of(b0 - 60), L.chunk_of(b0)
assert first != second
assert any(("snap-%s.jsonl.gz" % first) in fs and ("snap-%s.jsonl" % first) not in fs for fs in seen_files), \
    "the finished chunk is gzipped during the run"
assert sorted(f for f in os.listdir(L.DATA) if f.startswith("snap-")) == \
    ["snap-%s.jsonl.gz" % first, "snap-%s.jsonl.gz" % second]
L.DATA = MAIN_DATA
print("torn lines and 30-minute chunks ok")

# ---- settle: closed markets only, strategy.payout's rules, undecided ones asked again later
asked = []
def settle_api(path, params=None):
    asked.append(path)
    t = path.split("/")[-1]
    if t.endswith("-00"):
        return {"market": dict(ticker=t, result="no", status="finalized")}
    return {"market": dict(ticker=t, result="", status="closed")}
L.http = settle_api
clock[0] = T0 + 600
assert L.settle() == 0 and asked == []          # nothing has closed yet
clock[0] = T0 + 900 + L.SETTLE_AFTER + 1
assert L.settle() == 2
res = json.load(open(os.path.join(DATA, "results.json")))
assert set(res) == {"KXSOL15M-W%d-00" % T0, "KXGOLD15M-W%d-00" % T0}
assert all(v["result"] == "no" and v["yes_pay"] == 0.0 and v["no_pay"] == 1.0 for v in res.values())
asked.clear(); assert L.settle() == 0 and len(asked) == 2   # the two undecided markets are asked again, not the settled
print("settle ok")

# ---- paper refuses without a model, and with a model not fitted under PLAN20.md's frozen text
assert L.paper() is None and not os.path.exists(os.path.join(DATA, "paper.jsonl"))
json.dump({"frozen": iso(T0 - 86400), "coef": [1.0]}, open(os.environ["LIVE20_MODEL"], "w"))
sys.modules.pop("plan20", None)
assert L.paper() is None and not os.path.exists(os.path.join(DATA, "paper.jsonl"))
os.remove(os.environ["LIVE20_MODEL"])
print("paper refuses without a model ok")

# ---- paper: plan20's own replay on Kalshi's one-minute candles (fake candles, no network)
import random, importlib
sys.modules.pop("plan20", None)
Q = importlib.import_module("plan20")
assert L.NEEDED and all(hasattr(Q, k) for k in L.NEEDED)
IDENT = [[]]                                    # plan20's identity check, as the test sets it (the real one needs a freeze)
real_identity = Q.identity_problems
def fake_identity(*a, **k):
    if IDENT[0] == "raise":
        raise RuntimeError("identity check crashed")
    return IDENT[0]
Q.identity_problems = fake_identity
MF, MSHA = os.environ["LIVE20_MODEL"], os.environ["LIVE20_MODEL_SHA"]
assert L.MODEL_SHA_FILE == MSHA and L.RESULT_FILE == os.environ["LIVE20_RESULT"]


def put_model(m):
    """Write the model file and its fit-time SHA-256 record (as plan20's fit does)."""
    json.dump(m, open(MF, "w"))
    if os.path.exists(MSHA):
        os.remove(MSHA)
    assert Q.record_model_hash(MF, MSHA) is None
    assert Q.record_model_hash(MF, MSHA) is not None, "the hash record is written once"
shutil.rmtree(DATA); os.makedirs(DATA)
SERIES = {"KXSOL15M": "crypto", "KXGOLD15M": "metals"}
json.dump({"series": [{"ticker": k, "group": v} for k, v in SERIES.items()]}, open(os.environ["LIVE20_SERIES"], "w"))
rnd = random.Random(7)
slist = sorted(SERIES)
width = len(Q.input_names(slist))
k = len(Q.CONT)
coef = [rnd.uniform(-0.4, 0.4) for _ in range(width)]
coef[Q.CONT.index("minutes_left")] = 0.05
coef[Q.CONT.index("oi_d3")] = 0.002            # open interest moves by hundreds of contracts here
coef[k] = 2.5                                    # hhhl: the candle highs and lows matter to the bets
FREEZE = Q.lapaz_start(Q.date(2026, 10, 1))
model = dict(plan_sha256=Q.PLAN_SHA256, series=slist, mean=[0.0] * k, sd=[1.0] * k, intercept=-4.5, coef=coef,
             fitted=iso(FREEZE), frozen=iso(FREEZE))
put_model(model)

def raw_candle(end, yb, ya, rnd):
    """One Kalshi candlestick (dollar strings), with highs and lows around the closes."""
    bh, bl = min(0.99, yb + rnd.choice((0, 0.01, 0.02))), max(0.0, yb - rnd.choice((0, 0.01)))
    ah, al = min(1.0, ya + rnd.choice((0, 0.01, 0.02))), max(0.01, ya - rnd.choice((0, 0.01)))
    d = lambda v: "%.4f" % v   # noqa: E731
    return dict(end_period_ts=end, yes_bid=dict(close_dollars=d(yb), high_dollars=d(bh), low_dollars=d(bl)),
                yes_ask=dict(close_dollars=d(ya), high_dollars=d(ah), low_dollars=d(al)),
                price=dict(close_dollars=d(ya)), volume_fp="%.2f" % rnd.randint(0, 50),
                open_interest_fp="%.2f" % rnd.randint(10, 500))

RAW, RESULTS, SNAP = {}, {}, []
first_close = int(FREEZE) + 86400 * 3 + 900
closes = [first_close + 900 * i for i in range(60)]
for s in slist:
    for c in closes:
        o = c - 900
        for j in range(rnd.choice((1, 2, 3))):
            t = "%s-%d-%02d" % (s, c, j)
            mid = rnd.choice((0.04, 0.07, 0.5, 0.93, 0.96))
            cs = []
            for m in range(1, 15):
                mid = min(0.985, max(0.015, mid + rnd.choice((-0.02, -0.01, 0, 0.01, 0.02))))
                if rnd.random() < 0.08:
                    continue                     # a minute with no candle
                yb = round(max(0.0, mid - 0.01), 2)
                ya = round(min(1.0, mid + 0.01), 2)
                cs.append(raw_candle(o + 60 * m, yb, ya, rnd))
            RAW[t] = cs
            RESULTS[t] = dict(result=rnd.choice(("yes", "no")), yes_pay=None, no_pay=None)
            SNAP.append(dict(ts=o + 65, minute=o + 60, ticker=t, series=s, event="%s-%d" % (s, c), open=o, close=c,
                             status="active", yes_bid=0.5, yes_ask=0.51, no_bid=0.49, no_ask=0.5, last=0.5, volume=1.0, oi=1.0))
# one void market (left out of the replay, as plan20's download leaves it out), one window without a result yet,
# one window that opened before the freeze, one window still open by the clock
RESULTS["KXSOL15M-%d-00" % closes[5]]["result"] = "void"
pending = "KXGOLD15M-%d-00" % closes[7]
del RESULTS[pending]
early_c = int(FREEZE) - 3600
late_c = closes[-1] + 900 * 10
for t, c in (("KXSOL15M-early-00", early_c), ("KXSOL15M-late-00", late_c)):
    RAW[t] = []
    RESULTS[t] = dict(result="yes")
    SNAP.append(dict(ts=c - 835, minute=c - 840, ticker=t, series="KXSOL15M", event="E", open=c - 900, close=c,
                     status="active", yes_bid=0.5, yes_ask=0.51, no_bid=0.49, no_ask=0.5, last=0.5, volume=1.0, oi=1.0))
SNAP.sort(key=lambda x: x["minute"])
for x in SNAP:
    with open(os.path.join(DATA, "snap-%s.jsonl" % L.day_of(x["minute"])), "a") as f:
        f.write(json.dumps(x) + "\n")
json.dump(RESULTS, open(os.path.join(DATA, "results.json"), "w"))

got_calls = []
def candles_api(path, params=None):
    got_calls.append((path, params))
    assert not path.startswith("/portfolio")
    parts = path.split("/")
    if path.startswith("/series/") and parts[3] == "markets" and parts[5] == "candlesticks":
        s, t = parts[2], parts[4]
        assert t.startswith(s + "-")
        if t == "KXGOLD15M-%d-01" % closes[3]:
            raise RuntimeError("past the historical cutoff")   # the archive endpoint is tried next
    elif path.startswith("/historical/markets/") and path.endswith("/candlesticks"):
        t = parts[3]
    else:
        raise AssertionError(path)
    c = int(t.split("-")[1]) if t.split("-")[1].isdigit() else (early_c if "early" in t else late_c)
    assert params == dict(start_ts=c - 900, end_ts=c, period_interval=1), (path, params)
    return {"candlesticks": RAW[t]}
L.http = candles_api
clock[0] = closes[-1] + 3600
n = L.paper()
bets = [json.loads(l) for l in open(os.path.join(DATA, "paper.jsonl"))]
assert n == len(bets) and n > 0
fetched = {p.split("/")[-2] for p, _ in got_calls}
assert "KXSOL15M-early-00" not in fetched and "KXSOL15M-late-00" not in fetched and pending not in fetched
assert any(p.startswith("/historical/") for p, _ in got_calls)
assert all(p.endswith("/candlesticks") for p, _ in got_calls)

# the same windows through plan20's own score stage (collect) on the same candles
data = {}
for s in slist:
    for c in closes:
        o = c - 900
        for t in sorted(x for x in RAW if x.startswith("%s-%d-" % (s, c))):
            if t == pending:
                continue
            r = RESULTS[t]["result"]
            if r not in ("yes", "no"):
                continue
            day = Q.lapaz_date(c)
            data.setdefault((s, day), dict(markets=[]))["markets"].append(
                dict(ticker=t, close=c, open=o, result=r, c=Q.parse_candles(RAW[t], o)))
pend_c = closes[7]
for key in list(data):   # the window waiting for its result is not decided yet by live20
    data[key]["markets"] = [m for m in data[key]["markets"] if not (m["close"] == pend_c and key[0] == "KXGOLD15M")]
KEYS = ("series", "group", "ticker", "m", "side", "ask", "price", "contracts", "fee", "fee_cc", "win", "profit",
        "profit_cc", "breakeven", "band", "left")


def same_as_collect(mdl, mine):
    """live20's bets equal plan20.collect()'s on the same candles; returns collect's counts."""
    ref, _c, _k, cnt = Q.collect(data, SERIES, json.loads(json.dumps(mdl)))
    mine = sorted(mine, key=lambda b: (b["close"], b["series"]))
    theirs = sorted(ref, key=lambda b: (int(b["ticker"].split("-")[1]), b["series"]))
    assert len(mine) == len(theirs), (len(mine), len(theirs))
    for a, b in zip(mine, theirs):
        for kk in KEYS:
            assert a[kk] == b[kk] or (isinstance(b[kk], float) and abs(a[kk] - b[kk]) < 1e-12), (kk, a, b)
        assert abs(a["p"] - b["p"]) < 1e-12 and a["day"] == b["day"].isoformat() and a["fill_minute"] == a["m"] + 1
    return cnt


cnt = same_as_collect(model, bets)
assert cnt["windows"] // 2 > len(bets) > 5, (cnt, len(bets))
# a looser model: passes that cannot fill (the window goes on to a later chance) must match too
loose = dict(model, intercept=-3.0)
put_model(loose)
L.paper()
cnt2 = same_as_collect(loose, [json.loads(l) for l in open(os.path.join(DATA, "paper.jsonl"))])
assert sum(cnt2["passed_unfilled"].values()) > 0 and cnt2["windows_with_bet"] > len(bets), cnt2
put_model(model)
L.paper()
# the candle highs and lows reach the features: some chance has hhhl = 1 (snapshots alone would give 0 everywhere)
hh = [f["hhhl"] for s in slist for c in closes for t in RAW if t.startswith("%s-%d-" % (s, c))
      for m in Q.MINUTES for side in ("yes", "no")
      for f in [Q.features(Q.parse_candles(RAW[t], c - 900), side, m, dict(open=c - 900, series=s, group=SERIES[s]))] if f]
assert 1.0 in hh and 0.0 in hh
assert any(b["side"] == "no" for b in bets) or any(b["side"] == "yes" for b in bets)
print("paper ok: %d bets in %d windows equal plan20.collect's" % (len(bets), cnt["windows"]))

# cached: a second run asks Kalshi for nothing and writes the same file
first = open(os.path.join(DATA, "paper.jsonl"), "rb").read()
got_calls.clear()
assert L.paper() == n and not got_calls and open(os.path.join(DATA, "paper.jsonl"), "rb").read() == first
# candles: one gzip bundle per series and La Paz day of the close; no file per market
b_path = L.bundle_path("KXSOL15M", closes[0])
assert os.path.exists(b_path) and b_path.endswith("%s.json.gz" % L.lapaz_day(closes[0]))
assert not os.path.exists(L.candle_path("KXSOL15M", "KXSOL15M-%d-00" % closes[0]))
assert not [f for f in os.listdir(os.path.join(DATA, "candles", "KXSOL15M")) if not f.endswith(".json.gz")]
bundle = json.load(gzip.open(b_path, "rt", encoding="utf-8"))
t_old = "KXSOL15M-%d-00" % closes[0]
assert bundle["markets"][t_old]["candlesticks"] == RAW[t_old] and bundle["markets"][t_old]["close"] == closes[0]
# the old one-file-a-market cache is still read: move one market out of its bundle into the old format
old_entry = bundle["markets"].pop(t_old)
with gzip.open(b_path, "wt", encoding="utf-8") as fh:
    json.dump(bundle, fh)
os.makedirs(os.path.dirname(L.candle_path("KXSOL15M", t_old)), exist_ok=True)
json.dump(dict(ticker=t_old, series="KXSOL15M", candlesticks=old_entry["candlesticks"]),
          open(L.candle_path("KXSOL15M", t_old), "w"))
got_calls.clear()
assert L.paper() == n and not got_calls and open(os.path.join(DATA, "paper.jsonl"), "rb").read() == first
# the pending window's result arrives: it is now decided (one more candle fetch, nothing else)
RESULTS[pending] = dict(result="no")
json.dump(RESULTS, open(os.path.join(DATA, "results.json"), "w"))
n2 = L.paper()
assert {p.split("/")[-2] for p, _ in got_calls} <= {t for t in RAW if t.startswith("KXGOLD15M-%d-" % pend_c)}, got_calls
assert n2 in (n, n + 1)
# no model plan match: fail closed
put_model(dict(model, plan_sha256="0" * 64))
assert L.paper() is None
put_model(model)
assert L.paper() is not None

# the model file changed after its fit-time SHA-256 was recorded: fail closed (and with no record, or a damaged one)
keep_bytes = open(MF, "rb").read()
with open(MF, "ab") as fh:
    fh.write(b" ")
assert L.paper() is None
open(MF, "wb").write(keep_bytes)
assert L.paper() is not None
os.remove(MSHA)
assert L.paper() is None
open(MSHA, "w").write("{damaged")
assert L.paper() is None
put_model(model)
assert L.paper() is not None

# plan20's identity check must be clean ([]); anything else, or a crash, fails closed
for bad in (["research/plan20.py"], None, "raise", ["no identity record (run freeze first)"]):
    IDENT[0] = bad
    assert L.paper() is None, bad
IDENT[0] = []
assert real_identity is not fake_identity and real_identity(WORK) != [], "the real check is not clean without a freeze"
print("identity and model hash ok")

# stage C: a row counts only for a group the stored result shows passed, from the first full La Paz day after it
def rows_now():
    assert L.paper() is not None
    return [json.loads(l) for l in open(os.path.join(DATA, "paper.jsonl"))]
rows = rows_now()
assert rows and all(r["stage_c"] is False for r in rows), "no result: every row is descriptive"
RF = os.environ["LIVE20_RESULT"]
first_open = closes[0] - 900          # La Paz midnight (FREEZE + 3 days)
assert first_open == Q.lapaz_start(Q.lapaz_date(first_open))
def put_result(scored_ts, tests, plan=Q.PLAN_SHA256):
    json.dump(dict(plan_sha256=plan, scored=datetime.fromtimestamp(scored_ts, timezone.utc).isoformat(), tests=tests),
              open(RF, "w"))
PASS_CRYPTO = [dict(name="crypto", passed=True), dict(name="metals", passed=False), dict(name="energy", passed=False),
               dict(name="fx", passed=False)]
put_result(first_open - 1, PASS_CRYPTO)          # scored one second before the windows' La Paz day begins
rows = rows_now()
assert any(r["group"] == "crypto" for r in rows) and any(r["group"] == "metals" for r in rows)
assert all(r["stage_c"] == (r["group"] == "crypto") for r in rows), "crypto rows from the next La Paz midnight on"
assert min(r["open"] for r in rows if r["group"] == "crypto") >= first_open
put_result(first_open, PASS_CRYPTO)              # scored at that midnight: the first full day after is the next one
assert all(r["stage_c"] is False for r in rows_now())
put_result(first_open - 86400 + 3600 * 20, PASS_CRYPTO)   # 8 PM the evening before: same first day
assert all(r["stage_c"] == (r["group"] == "crypto") for r in rows_now())
put_result(first_open - 1, [dict(name="metals", passed=True), dict(name="btceth", passed=True)])
assert all(r["stage_c"] == (r["group"] == "metals") for r in rows_now()), "only tested groups can pass"
put_result(first_open - 1, PASS_CRYPTO, plan="0" * 64)
assert all(r["stage_c"] is False for r in rows_now()), "a result under another plan text counts for nothing"
put_result(first_open - 1, [dict(name="crypto", passed="yes")])
assert all(r["stage_c"] is False for r in rows_now()), "passed must be True itself"
open(RF, "w").write("{damaged")
assert all(r["stage_c"] is False for r in rows_now()), "a damaged result: every row descriptive"
os.remove(RF)
print("stage C flags ok")

# the kill switch stops paper bets (fails closed)
import core
core.kill_file = lambda: "KILL"
assert L.paper() is None
# the workflow: about 325 minutes of sampling, a 300-second paper budget, every step limited inside the job's 355
import re as _re
wf = open(os.path.join(WORK, "cloud", "workflows", "live20.yml"), encoding="utf-8").read()
_gh = os.path.join(WORK, ".github", "workflows", "live20.yml")   # switched on 2026-11-26: must equal the cloud copy
if os.path.exists(_gh):
    assert open(_gh, "rb").read() == open(os.path.join(WORK, "cloud", "workflows", "live20.yml"), "rb").read()
assert "+ 325 * 60" in wf and "345" not in wf.split("jobs:")[1]
assert "live20.py paper --budget-seconds 300" in wf
job_limit = int(_re.search(r"\n    timeout-minutes: (\d+)", wf).group(1))
steps = wf.split("    steps:\n")[1].split("\n      - ")
step_limits = [int(_re.search(r"\n        timeout-minutes: (\d+)", "\n" + st).group(1)) for st in steps if st.strip()]
assert len(step_limits) == len([st for st in steps if st.strip()]) == 6, step_limits
assert job_limit == 355 and sum(step_limits) <= job_limit, (step_limits, job_limit)
_doc = " ".join(open(os.path.join(WORK, "research", "live20.py"), encoding="utf-8").read().split('"""')[1].split())
assert "The KILL file lives on the PC only" in _doc and "the switch is not seen" in _doc and "harmless" in _doc
print("all live20 tests passed")
