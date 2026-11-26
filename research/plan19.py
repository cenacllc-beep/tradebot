"""PLAN19: resting bids at Kalshi's reference price on markets that pay liquidity rewards (forward paper test; research only).
Follows research/PLAN19.md (frozen 2026-11-25 22:39 La Paz; SHA-256 in PLAN_SHA below and in CHANGELOG.md). Where this
code and the text differ, the text wins (by an amendment before any number is computed).
Read-only: Kalshi public API GETs only (tbcommon's client, the project's User-Agent). It never places, changes or cancels
an order and never opens paper.db or live.db. Python 3.8+, needs requests.
  python research/plan19.py sample   one hourly sample (2026-11-28 .. 2026-12-27 local), then the fill checks of
                                     samples whose hour is over -> research/data/plan19/
  python research/plan19.py settle   results of sampled markets that have closed
  python research/plan19.py status   counts only (PLAN19 section 5: no reward or P&L figure before the score)
  python research/plan19.py score    scored once, from 2026-12-29 00:00 local -> research/results/plan19_result.md/.json
  python research/plan19.py auto-score   the score, once every sample is checked and every closed market has a result
                                     (or from the 2027-01-05 backstop); nothing before 2026-12-29 (the hourly job runs it)
Each step is safe to rerun: a sample hour is taken once, and a failed request is retried on the next run."""
import os, sys, time, random, re, math, hashlib
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if HERE not in sys.path: sys.path.insert(0, HERE)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.parse import num, rts
from tbcommon.jsonio import load, save, lines, append
from tbcommon import clock

DATA = os.path.join(HERE, "data", "plan19"); OUT = os.path.join(HERE, "results")
PLAN = os.path.join(HERE, "PLAN19.md")
PLAN_SHA = "ff25310ad62f9af77b9e2f330b907777b0098cf17aa37757c7d66b08e79144cf"
LOCAL = timezone(timedelta(hours=-4))   # America/La_Paz, UTC-4 all year
START = datetime(2026, 11, 28, 0, 0, tzinfo=LOCAL).timestamp()      # section 1
END = datetime(2026, 12, 28, 0, 0, tzinfo=LOCAL).timestamp()        # samples up to 2026-12-27 23:59 local
CLOSE_MAX = datetime(2026, 12, 27, 23, 59, 59, tzinfo=LOCAL).timestamp()   # scored markets close by then
SCORE_FROM = datetime(2026, 12, 29, 0, 0, tzinfo=LOCAL).timestamp()
SCORE_BACKSTOP = datetime(2027, 1, 5, 0, 0, tzinfo=LOCAL).timestamp()   # the automatic score stops waiting for results
CLOSE_GAP = 6 * 3600; PER = 40; Q = 100; QS = (10, 100, 1000); PROG_MAX_AGE = 6 * 3600
UNIT = 1e-4   # period_reward is 1/10,000 dollar (PLAN5's check; section 3 unit check)
# Section 5: which verdict applies was fixed before the first sample, from CHANGELOG.md 2026-11-25 22:39 La Paz: the user
# answered "Yes, eligible" (US member, not opened through a broker or FCM, SSN on file). Never changed after that.
REWARDS_APPLY = True
ELIGIBILITY_RECORD = "CHANGELOG.md, 2026-11-25 22:39 La Paz (the user's 'Yes, eligible')"
CLIENT = JsonClient(KALSHI_PUBLIC, tries=6, timeout=30, pause_after=0.12, backoff_base=3.0, backoff_cap=60.0, verbose=True)

def http(path, params=None, tries=6): return CLIENT.get(path, params, tries=tries)
def path(name): return os.path.join(DATA, name)
def rows_of(name):
    """All rows of samples, fills or sample_log: one file per UTC day, name-YYYYMMDD.jsonl, in date order."""
    try: daily = sorted(f for f in os.listdir(DATA) if re.match(re.escape(name) + r"-\d{8}\.jsonl$", f))
    except OSError: daily = []
    return [r for f in daily for r in lines(path(f))]
def add_rows(name, rows, now):
    if rows: append(path("%s-%s.jsonl" % (name, time.strftime("%Y%m%d", time.gmtime(now)))), rows)
def series_of(t): return (t or "").split("-")[0]
def day_of(ts): return datetime.fromtimestamp(ts, LOCAL).date().isoformat()   # section 1: the La Paz date of the sample
def mils(p): return int(round(p * 10000))   # dollars -> 1/100 cent (Kalshi has sub-cent ticks on some markets)

# ---------------- the quote and reward rules (sections 2 and 3) ----------------
def ladder(book, side):
    """[(price in mils, size)] of one side's bids, best first."""
    out = []
    for p, q in (book.get(side) or []):
        p, q = num(p), num(q)
        if p is not None and q and q > 0: out.append((mils(p), q))
    return sorted(out, key=lambda x: -x[0])
def reference(lad, target):
    """Kalshi's Reference Price: the first level from the best bid down where the cumulative size reaches target/5;
    None if it never does (section 2: the side is skipped)."""
    cum = 0.0
    for p, s in lad:
        cum += s
        if cum >= target / 5.0: return p
    return None
def qualifying(lad, ref, d):
    """Section 3: the sum of each level's size x d^k, k = cents below the reference (0 at or above it)."""
    return sum(s * (d ** (max(0, ref - p) / 100.0)) for p, s in lad)
def hourly_pool(prog):
    """Dollars per hour of a program (section 3), or None when it is unreadable."""
    t0, t1 = rts(prog.get("start_date")), rts(prog.get("end_date")); r = num(prog.get("period_reward"))
    if not t0 or not t1 or t1 <= t0 or r is None: return None
    return r * UNIT * 3600.0 / (t1 - t0)
def quote(book, prog):
    """The hypothetical quote for one sampled book (sections 2-3): (dict, None) or (None, skip reason)."""
    y, n = ladder(book, "yes"), ladder(book, "no")
    target = num(prog.get("target_size_fp")) or 0; d = (num(prog.get("discount_factor_bps")) or 0) / 10000.0
    pool = hourly_pool(prog)
    if not target or pool is None or not (0 < d <= 1): return None, "unreadable program"
    if y and n and y[0][0] + n[0][0] >= 10000: return None, "locked or crossed book"
    valid = bool(y and n and sum(s for _, s in y) >= target and sum(s for _, s in n) >= target)
    sides = {}; skips = []
    for side, lad in (("yes", y), ("no", n)):
        if not lad: skips.append("side without bids"); continue
        ref = reference(lad, target)
        if ref is None: skips.append("side never reaches the reference size"); continue
        if ref <= 0 or ref >= 10000: skips.append("quote at 0c or 100c"); continue
        qual = qualifying(lad, ref, d)
        sides[side] = dict(price=ref / 10000.0, best=lad[0][0] / 10000.0, queue=sum(s for p, s in lad if p == ref), qual=qual,
                           share={str(q): q / (qual + q) for q in QS})
    if not sides: return None, (skips[0] if skips else "no side quoted")
    return dict(sides=sides, valid=valid, target=target, d=d, pool=pool, usd_per_day=pool * 24, side_skips=skips), None

# ---------------- fills (section 4) and the weight drift (section 3) ----------------
def tprice(r, key):
    p = num(r.get(key + "_price_dollars"))
    if p is None:
        c = num(r.get(key + "_price")); p = c / 100 if c is not None else None
    return p
TAKER = {"yes": ("no", "yes"), "no": ("yes", "no")}   # our side -> (taker side that sells to us, price field)
def fills(trades, side, price, queue, q):
    """(contracts filled, time of the first fill) for one side's bid at `price` (section 4): trades below it fill us in
    full up to their size; trades at exactly it only after their cumulative size passes the queue; capped at q."""
    taker, key = TAKER[side]; b = mils(price); got = 0.0; at = 0.0; first = None
    for r in sorted(trades, key=lambda r: rts(r.get("created_time")) or 0):
        if got >= q: break
        if (r.get("taker_side") or "").lower() != taker: continue
        p = tprice(r, key)
        if p is None: continue
        pm = mils(p); n = num(r.get("count_fp")) or num(r.get("count")) or 0
        if n <= 0: continue
        if pm < b: add = n
        elif pm == b:
            before = max(0.0, at - queue); at += n; add = max(0.0, at - queue) - before
        else: continue
        if add > 0:
            got += add
            if first is None: first = rts(r.get("created_time"))
    return int(min(q, math.floor(got + 1e-9))), first
def cpx(c, k):
    d = c.get(k) or {}; v = num(d.get("close_dollars"))
    if v is None:
        x = num(d.get("close")); v = x / 100 if x is not None else None
    return v
def side_bid(c, side):
    """The side's best bid in a one-minute candle: YES = yes_bid close; NO = 1 - yes_ask close."""
    if side == "yes": return cpx(c, "yes_bid")
    a = cpx(c, "yes_ask")
    return None if a is None else 1.0 - a
def weight_sum(cs, side, ts, b0, d, t_fill):
    """Section 3: the sum over the minutes before the side's first fill of d^max(0, B_t - B_0) (cents). B_t = the side's
    best bid from the latest one-minute candle in the hour ending at or before the minute's end; minutes before the first
    candle carry B_0 (the last known); no candle at all in the hour for this side: weight 0.5 every minute. A minute
    counts only if it ends at or before the first fill (the minute in which the fill happens is not before it)."""
    inh = [c for c in cs if ts < (c.get("end_period_ts") or 0) <= ts + 3600 and side_bid(c, side) is not None]
    tot = 0.0
    for m in range(60):
        t0 = ts + 60 * m
        if t_fill is not None and t0 + 60 > t_fill: break
        if not inh: tot += 0.5; continue
        bt = b0
        for c in inh:
            if c["end_period_ts"] <= t0 + 60: bt = side_bid(c, side)
        tot += d ** (max(0.0, (bt - b0) * 100.0))
    return tot
def mid_at(cs, t):
    last = None
    for c in cs:
        if (c.get("end_period_ts") or 0) <= t: last = c
    if not last: return None
    b = cpx(last, "yes_bid"); a = cpx(last, "yes_ask")
    return (a + b) / 2 if (a is not None and b is not None and 0 <= b < a <= 1) else None
def adverse(cs, side, t_fill, price, lags=(60, 300)):
    """Reported only (section 4): the mid 1 and 5 minutes after a fill, in the filled side's favour, minus our price."""
    out = {}
    for l in lags:
        m = mid_at(cs, t_fill + l) if t_fill else None
        out[str(l)] = None if m is None else round((m if side == "yes" else 1 - m) - price, 4)
    return out

# ---------------- steps ----------------
def programs(now):
    """Every active liquidity program (re-read when older than 6 hours, section 1)."""
    c = load(path("programs.json"))
    if c and now - c["fetched"] < PROG_MAX_AGE: return c["rows"]
    rows = []; cur = None
    for _ in range(1000):
        prm = dict(status="active", limit=1000)
        if cur: prm["cursor"] = cur
        j = http("/incentive_programs", prm); page = j.get("incentive_programs") or []
        rows += [{k: x.get(k) for k in ("market_ticker", "start_date", "end_date", "period_reward", "target_size_fp", "discount_factor_bps")}
                 for x in page if (x.get("incentive_type") or "") == "liquidity"]
        cur = j.get("next_cursor") or j.get("cursor")
        if not cur or not page: break
    save(path("programs.json"), dict(fetched=now, rows=rows)); return rows
def series_info(series):
    """{series: {fee_type, category}}, cached (one GET per new series)."""
    c = load(path("series.json"), {})
    new = sorted(set(series) - set(c))
    for s in new:
        try: j = http("/series/" + s).get("series") or {}
        except RuntimeError: continue   # asked again next run; the market is left out this hour
        c[s] = dict(fee_type=j.get("fee_type"), category=j.get("category"))
    if new: save(path("series.json"), c)
    return c
def markets(tickers):
    out = {}; ts = sorted(set(tickers))
    for i in range(0, len(ts), 100):
        for m in (http("/markets", dict(tickers=",".join(ts[i:i + 100]), limit=1000)).get("markets") or []): out[m.get("ticker")] = m
    return out
def bump(why, k, n=1): why[k] = why.get(k, 0) + n
def last_sampled(ss):
    """{ticker: time of its latest sample}, from the sample rows themselves (section 1's open-window rule)."""
    last = {}
    for s in ss: last[s["ticker"]] = max(last.get(s["ticker"], -1e18), s["ts"])
    return last
def sample(now=None):
    now = now or time.time(); hour = int(now // 3600)
    took = load(path("hours.json"), {})
    ss = rows_of("samples") if START <= now < END else []
    if not (START <= now < END): print("plan19 sample: outside the sampling window (2026-11-28 .. 2026-12-27 local)")
    elif str(hour) in took or any(s["hour"] == hour for s in ss): print("plan19 sample: this hour was already sampled")
    else: take(now, hour, took, last_sampled(ss))
    fill_step(now)
def take(now, hour, took, last):
    live = [x for x in programs(now) if (rts(x["start_date"]) or 1e18) <= now < (rts(x["end_date"]) or 0)]
    by = {}; why = {}
    for x in live: by.setdefault(x["market_ticker"], []).append(x)
    pick_prog = {}
    for t, ps in by.items():
        ok = [p for p in ps if hourly_pool(p) is not None]
        if not ok: bump(why, "unreadable program"); continue
        pick_prog[t] = min(ok, key=hourly_pool)   # section 3: the lowest hourly rate when programs overlap
        if len(ps) > 1: bump(why, "markets with overlapping programs (lowest rate used)")
    ms = markets(list(pick_prog)); info = series_info([series_of(t) for t in pick_prog])
    uni = []; long_n = 0; long_usd = 0.0; long_total = 0.0
    for t in sorted(pick_prog):
        m = ms.get(t) or {}
        if (m.get("status") or "").lower() != "active": bump(why, "not active"); continue
        ct = rts(m.get("close_time"))
        if not ct or ct <= now + CLOSE_GAP: bump(why, "closes within 6 hours"); continue
        fee = (info.get(series_of(t)) or {}).get("fee_type")
        if fee is None: bump(why, "fee type unknown (series lookup failed)"); continue
        if fee != "quadratic": bump(why, "fee type not quadratic"); continue
        if ct > CLOSE_MAX:   # section 1: long-dated programs are reported descriptively only
            long_n += 1; long_usd += hourly_pool(pick_prog[t]) * 24; long_total += (num(pick_prog[t].get("period_reward")) or 0) * UNIT; continue
        if now - last.get(t, -1e18) < 3600: bump(why, "previous sample's window still open"); continue
        uni.append(t)
    pick = random.Random(hour).sample(uni, min(PER, len(uni)))   # uni is sorted by ticker; seed = the UTC epoch hour
    rows = []
    for t in sorted(pick):
        try: book = http("/markets/%s/orderbook" % t).get("orderbook_fp") or {}
        except RuntimeError as ex: bump(why, "order book failed"); print("  book failed", t, ex); continue
        b = {"yes": book.get("yes_dollars") or [], "no": book.get("no_dollars") or []}
        qt, skip = quote(b, pick_prog[t])
        if qt is None: bump(why, skip); continue
        for s in qt.pop("side_skips"): bump(why, s)
        m = ms.get(t) or {}
        rows.append(dict(ts=round(now, 1), hour=hour, ticker=t, series=series_of(t), event=m.get("event_ticker") or t.rsplit("-", 1)[0],
                         category=(info.get(series_of(t)) or {}).get("category"), close=rts(m.get("close_time")),
                         program=pick_prog[t], book=b, quote=qt))
    add_rows("samples", rows, now)
    rec = dict(ts=now, day=day_of(now), universe=len(uni), sampled=len(rows), skipped=why, long_dated_programs=long_n,
               long_dated_usd_per_day=round(long_usd, 2), long_dated_total_reward=round(long_total, 2))
    took[str(hour)] = rec; save(path("hours.json"), took); add_rows("sample_log", [rec], now)
    print("plan19 sample: %d markets in the universe, %d sampled, %d long-dated left out; skipped %s" % (len(uni), len(rows), long_n, why))
def candles(series, ticker, t0, t1):
    j = http("/series/%s/markets/%s/candlesticks" % (series, ticker), dict(start_ts=int(t0), end_ts=int(t1), period_interval=1))
    return sorted(j.get("candlesticks") or [], key=lambda c: c.get("end_period_ts") or 0)
def fill_step(now):
    """For each sample whose hour (plus 7 minutes for the 5-minute check) is over: the hour's trades, each side's fills
    for every size, the candles for the weight drift, and the mid after each fill. Each sample once; a failed trade list
    or a failed candle request is retried on the next run (a failed request is not "no candle": the 0.5 weight of
    section 3 is only for a side with no candle in an answer that came back)."""
    have = {(r["hour"], r["ticker"]) for r in rows_of("fills")}
    n = 0
    for s in rows_of("samples"):
        if s["ts"] + 3600 + 420 > now or (s["hour"], s["ticker"]) in have: continue
        try:
            tr = []; cur = None
            for _ in range(100):
                prm = dict(ticker=s["ticker"], min_ts=int(s["ts"]), max_ts=int(s["ts"] + 3600), limit=1000)
                if cur: prm["cursor"] = cur
                j = http("/markets/trades", prm); tr += j.get("trades") or []; cur = j.get("cursor")
                if not cur: break
        except Exception as ex: print("  trades failed (retried next run)", s["ticker"], str(ex)[:120]); continue
        try: cs = candles(s["series"], s["ticker"], s["ts"] - 60, s["ts"] + 3600 + 420)
        except Exception as ex: print("  candles failed (retried next run)", s["ticker"], str(ex)[:120]); continue
        qt = s["quote"]; rec = dict(hour=s["hour"], ticker=s["ticker"], trades=len(tr), candles=len(cs), sides={})
        for side, sd in qt["sides"].items():
            per = {}
            for q in QS:
                f, t_f = fills(tr, side, sd["price"], sd["queue"], q)
                w = weight_sum(cs, side, s["ts"], sd["best"], qt["d"], t_f if f else None)
                rew = qt["pool"] * sd["share"][str(q)] * w / 60.0 / 2.0 if qt["valid"] else 0.0
                per[str(q)] = dict(filled=f, t_fill=t_f if f else None, weight_minutes=round(w, 4), reward=rew)
            f100 = per[str(Q)]
            rec["sides"][side] = dict(per_q=per, adverse=adverse(cs, side, f100["t_fill"], sd["price"]) if f100["filled"] else None)
        add_rows("fills", [rec], now); n += 1
    if n: print("plan19 fills: %d sample hours checked" % n)
def settle(now=None):
    """Kalshi's market for each sampled market that has closed and has no final result yet (results.json)."""
    import strategy
    now = now or time.time(); res = load(path("results.json"), {})
    todo = sorted({s["ticker"] for s in rows_of("samples") if (s.get("close") or 1e18) <= now and s["ticker"] not in res})
    got = markets(todo) if todo else {}
    for t in todo:
        m = got.get(t)
        if m is None:
            try: m = http("/markets/" + t).get("market") or {}
            except RuntimeError: m = {}
        if strategy.payout(m, "yes") is not None:
            res[t] = {k: m.get(k) for k in ("result", "status", "settlement_value_dollars", "settlement_value")}
    save(path("results.json"), res); print("plan19 settle: %d results (%d asked)" % (len(res), len(todo)))
def status(now=None):
    """Counts only: no reward or P&L figure before the score (section 5)."""
    took = load(path("hours.json"), {}); ss = rows_of("samples"); fl = rows_of("fills")
    filled = sum(1 for r in fl for sd in r["sides"].values() if sd["per_q"][str(Q)]["filled"])
    days = {}
    for h in took.values(): days[h["day"]] = days.get(h["day"], 0) + 1
    print("plan19: %d sampled hours over %d days (days with 12+ hours: %d), %d sampled market-hours, %d fill checks, "
          "%d filled market-hour-sides, %d results" % (len(took), len(days), sum(1 for v in days.values() if v >= 12), len(ss), len(fl),
                                                       filled, len(load(path("results.json"), {}))))

# ---------------- the score (section 5) ----------------
def taker_fee(c, p):
    """Kalshi's taker fee for c contracts at price p, rounded up to the centicent (conservative)."""
    return math.ceil(0.07 * c * p * (1 - p) * 10000 - 1e-9) / 10000.0
def sell_value(book_side, c):
    """What selling c contracts into a side's bid ladder brings, level by level, minus the taker fee (section 4)."""
    left = c; val = 0.0
    for pm, s in sorted(ladder({"x": book_side}, "x"), key=lambda x: -x[0]):
        if left <= 0: break
        k = min(left, s); p = pm / 10000.0
        val += k * p - taker_fee(k, p); left -= k
    return val
def se_units(units):
    """units: [(net, capital, day, event, series, null sd)]. m = sum(net) / sum(capital); SE = the largest of two-way
    (day x event, Cameron-Gelbach-Miller), day, event, series and the no-edge SE of the fills (section 5)."""
    W = sum(u[1] for u in units)
    if not units or W <= 0: return None, None
    m = sum(u[0] for u in units) / W
    def var(key):
        g = {}
        for u in units: g[key(u)] = g.get(key(u), 0.0) + (u[0] - m * u[1])
        C = len(g)
        return C / (C - 1) * sum(v * v for v in g.values()) / W ** 2 if C > 1 else float("inf")
    vd, ve, vs = var(lambda u: u[2]), var(lambda u: u[3]), var(lambda u: u[4])
    vde = var(lambda u: (u[2], u[3]))
    two = max(0.0, vd + ve - vde)
    ev = {}
    for u in units: ev[u[3]] = ev.get(u[3], 0.0) + u[5]
    v0 = sum(v * v for v in ev.values()) / W ** 2
    return m, max(two, vd, ve, vs, v0) ** 0.5
def band(p): return "1-5c" if p <= 0.055 else "6-20c" if p <= 0.205 else "21-50c" if p <= 0.505 else "51-99c"
def finite(x): return None if x is None or not math.isfinite(x) else x
def score(now=None, marks=None):
    """Scored once (section 5). marks: {ticker: order book} for markets with open (unsettled, unpaired) fills at scoring
    (fetched here when None)."""
    import strategy
    now = now or time.time(); out = os.path.join(OUT, "plan19_result.json")
    if os.path.exists(out): sys.exit("plan19_result.json exists: PLAN19 is scored once.")
    if now < SCORE_FROM: sys.exit("PLAN19 is scored from 2026-12-29 00:00 La Paz.")
    with open(PLAN, "rb") as fh: h = hashlib.sha256(fh.read()).hexdigest()
    if h != PLAN_SHA: sys.exit("research/PLAN19.md differs from its frozen hash: the score waits for an approved amendment.")
    took = load(path("hours.json"), {}); ss = rows_of("samples"); fl = {(r["hour"], r["ticker"]): r for r in rows_of("fills")}
    res = load(path("results.json"), {})
    hours_by_day = {}
    for hr, rec in took.items(): hours_by_day.setdefault(rec["day"], set()).add(int(hr))
    d0 = datetime.fromtimestamp(START, LOCAL).date(); n_days = int(round((END - START) / 86400.0))
    sampled_by_day = {}
    for i in range(n_days):   # section 1: missed hours are reported by day
        dd = (d0 + timedelta(days=i)).isoformat(); k = len(hours_by_day.get(dd, ()))
        sampled_by_day[dd] = dict(sampled=k, missed=24 - k)
    skipped = {}
    for rec in took.values():
        for k, v in (rec.get("skipped") or {}).items(): bump(skipped, k, v)
    left = {"no fill check": 0, "day with under 12 sampled hours": 0}
    U = []; checked = []
    for s in ss:
        f = fl.get((s["hour"], s["ticker"]))
        if not f: left["no fill check"] += 1; continue
        checked.append((s, f))
        if len(hours_by_day.get(day_of(s["ts"]), ())) < 12: left["day with under 12 sampled hours"] += 1; continue
        U.append((s, f))
    # the $1 minimum per market program (section 3), for each size: mean sampled hourly reward of that market (every
    # sample with a fill check) x the hours the market was eligible in the window
    def pkey(s): return (s["ticker"], s["program"]["start_date"], s["program"]["end_date"])
    def elig_hours(s):
        p = s["program"]; a = max(rts(p["start_date"]) or START, START); b = min(rts(p["end_date"]) or END, END, (s["close"] or END) - CLOSE_GAP)
        return max(0.0, (b - a) / 3600.0)
    rws = {}; first = {}
    for s, f in checked:
        first.setdefault(pkey(s), s)
        for q in QS: rws.setdefault((pkey(s), q), []).append(sum(sd["per_q"][str(q)]["reward"] for sd in f["sides"].values()))
    paid = {k: (sum(v) / len(v)) * elig_hours(first[k[0]]) >= 1.0 for k, v in rws.items()}
    # positions (section 4): settled markets pay strategy.payout; otherwise a YES and a NO fill of the same market-hour
    # lock in 1.00 minus both prices, and the rest is sold into that side's bid ladder at scoring (all open contracts of
    # a market, side and size together, so one ladder level is never sold twice)
    pos = []; openc = {}
    for s, f in U:
        settled = s["ticker"] in res; P = {}
        for q in QS:
            fq = {side: f["sides"][side]["per_q"][str(q)]["filled"] for side in s["quote"]["sides"]}
            lk = 0 if settled else min(fq.get("yes", 0), fq.get("no", 0))
            P[q] = {side: (c, lk, 0 if settled else c - lk) for side, c in fq.items()}
            for side, (c, l_, op) in P[q].items():
                if op: openc[(s["ticker"], side, q)] = openc.get((s["ticker"], side, q), 0) + op
        pos.append(P)
    need = sorted({k[0] for k in openc})
    if marks is None:
        marks = {}
        for t in need:
            try: b = http("/markets/%s/orderbook" % t).get("orderbook_fp") or {}
            except RuntimeError: b = {}
            marks[t] = {"yes": b.get("yes_dollars") or [], "no": b.get("no_dollars") or []}
    per_contract = {k: sell_value((marks.get(k[0]) or {}).get(k[1]) or [], n) / n for k, n in openc.items()}
    def side_pnl(s, side, q, c, lk, op):
        if not c: return 0.0
        sides = s["quote"]["sides"]; p = sides[side]["price"]; r = res.get(s["ticker"])
        if r is not None:
            po = strategy.payout(r, side)
            if po is not None: return 0.0 if po[1] is None else c * (po[1] - p)
        locked = lk * (1.0 - sides["yes"]["price"] - sides["no"]["price"]) / 2.0 if lk else 0.0   # the pair's P&L, half on each side
        return locked + (op * (per_contract[(s["ticker"], side, q)] - p) if op else 0.0)
    tot = dict(reward=0.0, fillpnl=0.0, capital=0.0, units=0, valid=0); qv = {str(q): dict(reward=0.0, fillpnl=0.0, capital=0.0) for q in QS}
    units_net = []; units_half = []; units_fill = []; days = set(); fill_sides = 0; fill_events = set()
    contracts = 0; contracts_marked = 0; byser = {}; bycat = {}; byband = {}; adv = {"60": [], "300": []}; prices = []
    bad_units = sorted({s["ticker"] for s in ss if not (1.0 <= s["quote"]["usd_per_day"] <= 1000.0)})   # section 3's unit check
    for (s, f), P in zip(U, pos):
        qt = s["quote"]; u_rew = u_pnl = u_cap = 0.0; sdv = 0.0
        for side, sd in qt["sides"].items():
            fr = f["sides"][side]
            for q in QS:
                pq = fr["per_q"][str(q)]; c, lk, op = P[q][side]
                rew = pq["reward"] if paid[(pkey(s), q)] else 0.0; cap = q * sd["price"]
                pnl = side_pnl(s, side, q, c, lk, op)
                qv[str(q)]["reward"] += rew; qv[str(q)]["fillpnl"] += pnl; qv[str(q)]["capital"] += cap
                if q == Q:
                    u_rew += rew; u_pnl += pnl; u_cap += cap; prices.append(sd["price"])
                    b = byband.setdefault(band(sd["price"]), dict(sides=0, reward=0.0, fillpnl=0.0, capital=0.0))
                    b["sides"] += 1; b["reward"] += rew; b["fillpnl"] += pnl; b["capital"] += cap
                    if c:
                        fill_sides += 1; fill_events.add(s["event"]); contracts += c; contracts_marked += op
                        sdv += c * (sd["price"] * (1 - sd["price"])) ** 0.5
                        for l in adv:
                            a = (fr.get("adverse") or {}).get(l)
                            if a is not None: adv[l].append(a)
        if u_cap <= 0: continue
        day = day_of(s["ts"]); days.add(day)
        units_net.append((u_rew + u_pnl, u_cap, day, s["event"], s["series"], sdv))
        units_half.append((0.5 * u_rew + u_pnl, u_cap, day, s["event"], s["series"], sdv))
        units_fill.append((u_pnl, u_cap, day, s["event"], s["series"], sdv))
        tot["reward"] += u_rew; tot["fillpnl"] += u_pnl; tot["capital"] += u_cap; tot["units"] += 1; tot["valid"] += bool(qt["valid"])
        for d_, k in ((byser, s["series"]), (bycat, s.get("category") or "?")):
            b = d_.setdefault(k, dict(units=0, reward=0.0, fillpnl=0.0, capital=0.0))
            b["units"] += 1; b["reward"] += u_rew; b["fillpnl"] += u_pnl; b["capital"] += u_cap
    def stat(units):
        m_, se_ = se_units(units); se_ = finite(se_)   # a single cluster gives no SE: no t, so no PASS
        return m_, se_, (m_ / se_ if (m_ is not None and se_) else None)
    m, se, t = stat(units_net); mh, seh, th = stat(units_half); mf, sef, tf = stat(units_fill)
    floors = len(days) >= 20 and fill_sides >= 100 and len(fill_events) >= 30
    marked_ok = contracts_marked <= 0.05 * contracts
    spread = "NOT TESTABLE" if not (floors and marked_ok) else ("PASS" if tf is not None and tf >= 2.5 else "FAIL")
    c3 = tot["fillpnl"] > -0.5 * tot["reward"]
    rew = "NOT TESTABLE" if not (floors and marked_ok) or bad_units else (
        "PASS" if t is not None and t >= 2.5 and th is not None and th >= 2.5 and c3 else "FAIL")
    sides_n = sum(b["sides"] for b in byband.values())
    med = sorted(prices)[len(prices) // 2] if prices else None
    n25 = int(25 // (Q * med)) if med else 0
    illus = n25 * ((tot["reward"] + tot["fillpnl"]) / sides_n) * 24 if sides_n else None
    top = lambda d_: dict(sorted(d_.items(), key=lambda kv: -kv[1]["units"])[:10])
    hrs = list(took.values())
    mean_h = lambda k: (sum(h.get(k, 0) for h in hrs) / len(hrs)) if hrs else None
    R = dict(plan="research/PLAN19.md", plan_sha256=PLAN_SHA, scored=clock.iso(seconds=False),
             spread_only=dict(verdict=spread, mean_return_per_dollar_hour=mf, se=sef, t=tf),
             with_rewards=dict(verdict=rew, applies=REWARDS_APPLY, eligibility=ELIGIBILITY_RECORD, mean_return_per_dollar_hour=m, se=se, t=t,
                               t_with_rewards_halved=th, fills_not_eating_rewards=c3, unit_problem_tickers=bad_units[:20]),
             days=len(days), filled_market_hour_sides=fill_sides, events_with_fills=len(fill_events), contracts_filled=contracts,
             contracts_valued_at_ladder=contracts_marked, totals=tot, left_out=left, skipped_at_sample=skipped,
             sampled_hours=len(took), hours_by_day=sampled_by_day,
             programs_under_1_dollar=sum(1 for k, v in paid.items() if k[1] == Q and not v), programs=sum(1 for k in paid if k[1] == Q),
             exploratory=dict(by_series_top10=top(byser), by_category=bycat, by_quote_price_band=byband, by_size=qv,
                              valid_share=(tot["valid"] / tot["units"]) if tot["units"] else None,
                              adverse_selection={l: dict(n=len(v), mean=(sum(v) / len(v)) if v else None) for l, v in adv.items()},
                              long_dated=dict(hours=len(hrs), mean_programs=mean_h("long_dated_programs"), mean_usd_per_day=mean_h("long_dated_usd_per_day"),
                                              mean_total_reward=mean_h("long_dated_total_reward")),
                              illustration_25=dict(sides_funded=n25, median_quote_price=med, dollars_per_day=illus)))
    os.makedirs(OUT, exist_ok=True); save(out, R)
    pc = lambda x: "n/a" if x is None else "%+.4f%%" % (100 * x)
    tt = lambda x: "n/a" if x is None else "%.2f" % x
    L = ["# PLAN19: resting bids for Kalshi's liquidity rewards (scored once, %s)" % R["scored"], "",
         "**With rewards: %s** (t %s; with rewards halved, t %s). %s." % (rew, tt(t), tt(th), ("This verdict applies: " + ELIGIBILITY_RECORD)
                                                                          if REWARDS_APPLY else "Reported only: eligibility was not on record before the first sample"),
         "**Spread alone: %s** (t %s)." % (spread, tt(tf)),
         "%d days, %d counted market-hours (%d valid for rewards), %d filled market-hour-sides in %d events, %d contracts filled "
         "(%d valued at the bid ladder, not a settlement)." % (len(days), tot["units"], tot["valid"], fill_sides, len(fill_events), contracts, contracts_marked),
         "Return per dollar of capital per hour: %s with rewards, %s from fills alone. Rewards $%.2f, fill P&L $%.2f over $%.2f of capital-hours." % (
             pc(m), pc(mf), tot["reward"], tot["fillpnl"], tot["capital"]),
         "%d sampled hours; missed hours by day are in the .json." % len(took),
         "Illustration at $25 (an upper bound): %d sides of 100 at the median quote price, about $%s a day." % (n25, "n/a" if illus is None else "%.2f" % illus),
         "Paper estimate only, and the rewards are modelled: Kalshi's own fills and reward statement are the real test. "
         "A FAIL means the test could not tell, not that there is no edge. The breakdowns in the .json are exploratory."]
    with open(os.path.join(OUT, "plan19_result.md"), "w", encoding="utf-8") as fh: fh.write("\n".join(L) + "\n")
    print("\n".join(L))
def score_ready(now=None):
    """The automatic score waits (from 2026-12-29) until every sampled market that has closed has a result and every
    sample has its fill check, or until the backstop (2027-01-05); prints the reason and returns False while waiting."""
    now = now or time.time()
    if now < SCORE_FROM or os.path.exists(os.path.join(OUT, "plan19_result.json")): return False
    if now >= SCORE_BACKSTOP: return True
    ss = rows_of("samples"); fl = {(r["hour"], r["ticker"]) for r in rows_of("fills")}; res = load(path("results.json"), {})
    if any((s["hour"], s["ticker"]) not in fl for s in ss): print("plan19: waiting for fill checks"); return False
    open_ = sorted({s["ticker"] for s in ss if (s.get("close") or 1e18) <= now and s["ticker"] not in res})
    if open_: print("plan19: waiting for %d closed markets' results" % len(open_)); return False
    return True

if __name__ == "__main__":
    try: sys.stdout.reconfigure(errors="replace")
    except AttributeError: pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample": sample()
    elif cmd == "settle": settle()
    elif cmd == "status": status()
    elif cmd == "score": score()
    elif cmd == "auto-score":
        if score_ready(): score()
    else: sys.exit(__doc__)
