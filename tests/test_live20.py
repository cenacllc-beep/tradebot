"""research/live20.py (PLAN20's forward logger), on fake Kalshi answers and a fake clock. No network.
python test_live20.py WORK OUT"""
import os, sys, json, types, gzip, shutil
WORK, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True); os.chdir(OUT)
DATA = os.path.join(OUT, "live20")
os.environ["LIVE20_DATA"] = DATA
os.environ["LIVE20_SERIES"] = os.path.join(OUT, "plan20_series.json")
os.environ["LIVE20_MODEL"] = os.path.join(OUT, "plan20_model.json")
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
assert os.path.exists(os.path.join(DATA, "snap-%s.jsonl" % L.day_of(T0 + 60)))
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

# ---- paper refuses without a model (and without plan20.py)
assert L.paper() is None and not os.path.exists(os.path.join(DATA, "paper.jsonl"))
json.dump({"frozen": iso(T0 - 86400), "coef": [1.0]}, open(os.environ["LIVE20_MODEL"], "w"))
sys.modules.pop("plan20", None)
if not os.path.exists(os.path.join(WORK, "research", "plan20.py")):
    assert L.paper() is None and not os.path.exists(os.path.join(DATA, "paper.jsonl"))
os.remove(os.environ["LIVE20_MODEL"])
print("paper refuses without a model ok")

# ---- paper on a hand-made log: no look-ahead, fill at the next minute's logged ask, one bet per window per series
shutil.rmtree(DATA); os.makedirs(DATA)
W = T0 + 900 * 4
def row(series, k, minute, yb, ya, o=W):
    return dict(ts=minute + 5, minute=minute, ticker="%s-W-%02d" % (series, k), series=series, event="%s-W" % series,
                open=o, close=o + 900, status="active", yes_bid=yb, yes_ask=ya, no_bid=round(1 - ya, 4),
                no_ask=round(1 - yb, 4), last=ya, volume=float(minute // 60), oi=5.0)
rows = []
for i in range(1, 15):
    mi = W + 60 * i
    # SOL: market 00 is cheap on YES from minute 2 (ask 4c); at minute 3 the fill snapshot (minute 4) is missing,
    # so the minute-3 chance cannot fill; minute 5's chance fills at minute 6's ask (6c, not the decision ask).
    if i != 4:
        ask = {2: 0.04, 3: 0.04, 5: 0.04, 6: 0.06}.get(i, 0.30)
        rows.append(row("KXSOL15M", 0, mi, round(ask - 0.01, 2), ask))
    rows.append(row("KXSOL15M", 1, mi, 0.50, 0.55))
    # GOLD: two cheap markets in the same window from minute 7; only one bet for the window (ticker order)
    if i >= 7:
        rows.append(row("KXGOLD15M", 0, mi, 0.02, 0.03)); rows.append(row("KXGOLD15M", 1, mi, 0.02, 0.03))
    else:
        rows.append(row("KXGOLD15M", 0, mi, 0.40, 0.45)); rows.append(row("KXGOLD15M", 1, mi, 0.40, 0.45))
# a window that opened before the freeze time: never bet
for i in range(1, 15):
    rows.append(row("KXSOL15M", 0, W - 86400 * 3 + 60 * i, 0.03, 0.04, o=W - 86400 * 3))
rows.sort(key=lambda x: x["minute"])
byday = {}
for x in rows:
    byday.setdefault(L.day_of(x["minute"]), []).append(x)
for d, rs in byday.items():
    with open(os.path.join(DATA, "snap-%s.jsonl" % d), "w") as f:
        for x in rs:
            f.write(json.dumps(x) + "\n")
json.dump({"KXSOL15M-W-00": dict(result="yes", yes_pay=1.0, no_pay=0.0)}, open(os.path.join(DATA, "results.json"), "w"))
seen = []
fake = types.ModuleType("plan20")
def features(hist, m, side, meta):
    assert max(hist) <= m and all(k >= 1 for k in hist), "look-ahead: candles after minute m were passed"
    seen.append((meta["series"], meta["ticker"], m, side, max(hist)))
    c = hist.get(m)
    return dict(ask=c["yes_ask"] if side == "yes" else c["no_ask"], m=m, side=side)
def decide(model, f, ask):
    assert model["coef"] == [1.0]
    return f["side"] == "yes" and f["m"] >= 3 and abs(f["ask"] - ask) < 1e-9
fake.features, fake.decide = features, decide
sys.modules["plan20"] = fake
json.dump({"frozen": iso(W - 86400), "coef": [1.0]}, open(os.environ["LIVE20_MODEL"], "w"))
json.dump({"KXSOL15M": "crypto", "KXGOLD15M": "metals"}, open(os.environ["LIVE20_SERIES"], "w"))
clock[0] = W + 900 + 3600
assert L.paper() == 2
bets = [json.loads(l) for l in open(os.path.join(DATA, "paper.jsonl"))]
sol = [b for b in bets if b["series"] == "KXSOL15M"]
gold = [b for b in bets if b["series"] == "KXGOLD15M"]
assert len(sol) == 1 and len(gold) == 1, bets
b = sol[0]
assert b["open"] == W and b["decision_minute"] == 5 and b["fill_minute"] == 6 and b["fill_price"] == 0.06 and b["decision_ask"] == 0.04, b
assert b["contracts"] == 16 and b["fee"] == 0.07, b          # floor(1/0.06) = 16; 0.07 x 16 x 0.06 x 0.94 = 0.0632 -> 7c
g = gold[0]
assert g["ticker"] == "KXGOLD15M-W-00" and g["decision_minute"] == 7 and g["fill_price"] == 0.03 and g["group"] == "metals", g
assert "pnl_per_contract" not in g and abs(b["pnl_per_contract"] - ((1.0 - 0.06) - b["fee"] / 16)) < 1e-9
assert all(x[2] <= 13 for x in seen) and all(x[4] <= x[2] for x in seen)
assert ("KXSOL15M", "KXSOL15M-W-00", 3, "yes", 3) in seen   # the minute-3 chance was judged; its fill (minute 4) was missing
first = open(os.path.join(DATA, "paper.jsonl"), "rb").read()
assert L.paper() == 2 and open(os.path.join(DATA, "paper.jsonl"), "rb").read() == first   # idempotent
# compaction keeps every row and the replay gives the same bets
L.compact(today="99991231")
assert not any(f.endswith(".jsonl") and f.startswith("snap-") for f in os.listdir(DATA))
assert sum(1 for _ in L.snapshots()) == len(rows)
assert L.paper() == 2 and open(os.path.join(DATA, "paper.jsonl"), "rb").read() == first
# a window still open by the clock is not decided yet
clock[0] = W + 600
assert L.paper() == 0
st = L.status(); assert st["paper_bets"] == 0
print("paper ok:", [(x["series"], x["decision_minute"], x["fill_price"]) for x in bets])

# the kill switch stops paper bets (fails closed)
import core
core.kill_file = lambda: "KILL"
clock[0] = W + 900 + 3600
assert L.paper() is None
print("all live20 tests passed")
