"""PLAN16 (research/PLAN16.md): four fixed rules for Kalshi's 15-minute BTC and ETH markets, scored once on past
windows (PLAN15's find period, windows closing 2026-09-01 to 2026-10-31). Research and paper only: never part of the
gate, never connected to live.py, places nothing, never reads PLAN15's check period (Nov-Dec).

Rules (plan section 2), decided at minutes 2, 5 and 10 and paid exactly as PLAN15 pays (plan15.fill: the ask at the
close of minute k + 1, PLAN15's fee and no-trade rules):
  A  PLAN15's random walk with a 15-minute sigma (the 15 one-minute returns ending at minute k), edge >= 4 points
  B  PLAN15's random walk (its 60-minute sigma), edge >= 10 points
  C  trend: Coinbase candles k-2, k-1, k with higher highs and higher lows (up) or lower (down); ask 20c-80c
  D  order flow: Kalshi taker imbalance over the 3 minutes ending at minute k, >= 50 contracts, |I| >= 0.4; ask 20c-80c

Stages (each refuses to run out of turn):
- freeze: the identity record (SHA-256 of research/PLAN16.md, research/plan16.py and research/plan15.py), stored once
  in research/results/plan16_identity.json; refuses afterwards. Every other stage refuses until it matches.
- download [--max-days N] [--budget-minutes M]: for each asset-day PLAN15 has saved (complete) in the find period,
  Coinbase's one-minute candles for that day (kept in memory, never written) and each window's Kalshi trades from its
  open to minute 10; only the derived values per window and minute are saved, in research/results/plan16/days/.
  A saved day is final. Prints counts only, never a profit or a result.
- score: once (refuses when a result exists here, and the workflow refuses when one was ever committed: the public
  commit is the off-folder copy), and until every find-period day has both PLAN15's and PLAN16's file; writes
  research/results/plan16_result.md, then plan16_result.json.
- status: counts only.

Standard library only. Network: Kalshi's public API and api.exchange.coinbase.com through PLAN15's own clients
(User-Agent tradebot-paper-research/1.0, retries, rate limits).

  python research/plan16.py freeze|score|status
  python research/plan16.py download [--max-days N] [--budget-minutes M]
Python 3.8+."""
import argparse
import json
import http.client
import math
import os
import random
import sys
import time
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import plan15 as P   # noqa: E402  (PLAN15's frozen helpers: data files, quotes, fills, fees, RW, PLAN7's statistics)
from tbcommon import jsonio   # noqa: E402

PLAN = "research/PLAN16.md"
PLAN_SHA256 = "5e82af19f0dda166aa53f48654b5f8d7fe2f6f50519f5c4d4f8a7238b16f3e1d"   # frozen 2026-11-13 (CHANGELOG)
FROZEN_FILES = ("research/PLAN16.md", "research/plan16.py", "research/plan15.py")
ASSETS = P.ASSETS
KS = P.KS                                  # 2, 5, 10
RULES = ("A", "B", "C", "D")
EDGE_A = 0.04
EDGE_B = 0.10
BAND = (0.20, 0.80)                        # C and D: the chosen side's ask at minute k, inclusive
RECENT_RETURNS = 15                        # A: one-minute returns ending at minute k
TREND_CANDLES = 3                          # C: candles k-2, k-1, k
FLOW_MINUTES = 3                           # D: trades after the close of minute k-3, up to the close of minute k
FLOW_MIN_CONTRACTS = 50.0
FLOW_CUT = 0.4
FILL_DELAY = P.FILL_DELAY                  # 1
LATE_DELAYS = P.LATE_DELAYS                # 3, 5 (descriptive)
FAMILY = 0.025
T_FLOOR = 2.0
BOOT_BLOCK_DAYS, BOOT_DRAWS = 2, 20000
PLACEBO_DRAWS = 2000
SEED = 16
MIN_SIGNALS, MIN_SIGNAL_DAYS = 200, 20
MAX_MISSING, MIN_AGREE = 0.10, 0.97
WINDOWS_PER_DAY = P.WINDOWS_PER_DAY        # 96
VERDICT_PASS = "lead on past data: justifies a forward paper test"
VERDICT_FAIL = "no edge shown"
NOT_TESTABLE = "not testable"

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(RESULTS, "plan16")
IDENTITY = os.path.join(RESULTS, "plan16_identity.json")
RESULT = os.path.join(RESULTS, "plan16_result.json")


# ---------- identity ----------
def identity_now(root=ROOT):
    out = {f: P.file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES}
    out["research/results/plan15/inspect.json"] = P.file_hash(P.INSPECT)   # fee multipliers, the reference field
    return out


def identity_problems(root=ROOT, path=None):
    """[] when the identity record exists and the plan and the code still match it (and the plan its frozen hash)."""
    rec, ok = P._read_json(path or IDENTITY)
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        bad.append("research/PLAN16.md differs from its frozen SHA-256")
    return bad + P.plan7_problems(root)   # PLAN7's statistics functions, pinned by PLAN15


def freeze(root=ROOT, path=None, now=None):
    path = path or IDENTITY
    if os.path.exists(path):
        return None, "already frozen (%s); stored once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN16.md differs from its frozen SHA-256; nothing saved"
    p15 = P.identity_problems(root)
    if p15:   # PLAN15's inspect.json and code must be frozen first, or they could still change under this record
        return None, "PLAN15 is not frozen or differs from its record (%s); nothing saved" % ", ".join(p15)
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, identity=identity_now(root),
               frozen=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat())
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read"
    jsonio.save(path, rec)
    return rec, "frozen: %s" % path


# ---------- per-window inputs (plan section 2; only what is known at the close of minute k) ----------
def candle(spot, o, i):
    """Coinbase's [open, high, low, close] for window minute i (the minute ending at open + 60 i), or None."""
    return spot.get(int(o) + 60 * i)


def recent_sigma(spot, o, k):
    """A: SD (n - 1) of the 15 one-minute log returns ending at minute k (closes of minutes k-15..k); None if any
    close is missing or the SD is 0 (no signal)."""
    closes = [(candle(spot, o, i) or [None] * 4)[3] for i in range(k - RECENT_RETURNS, k + 1)]
    return P.sigma_from(closes)


def trend(spot, o, k):
    """C: "up" (each high and each low above the one before over candles k-2..k), "down" (each below), "none", or None
    when a candle is missing."""
    cs = [candle(spot, o, i) for i in range(k - TREND_CANDLES + 1, k + 1)]
    if any(c is None for c in cs):
        return None
    hs, ls = [c[1] for c in cs], [c[2] for c in cs]
    if all(hs[i] > hs[i - 1] for i in range(1, len(cs))) and all(ls[i] > ls[i - 1] for i in range(1, len(cs))):
        return "up"
    if all(hs[i] < hs[i - 1] for i in range(1, len(cs))) and all(ls[i] < ls[i - 1] for i in range(1, len(cs))):
        return "down"
    return "none"


def flow(trades, o, k):
    """D: (YES-taker contracts, NO-taker contracts) of the trades after the close of minute k-3 and after the open,
    at or before the close of minute k."""
    lo, hi = int(o) + 60 * max(0, k - FLOW_MINUTES), int(o) + 60 * k
    yes = no = 0.0
    for r in trades:
        t = P.ts_of(r.get("created_time"))
        n = P.num(r.get("count_fp"))
        n = n if n is not None else P.num(r.get("count"))
        if t is None or not n or not (lo < t <= hi):
            continue
        s = r.get("taker_side")
        if s == "yes":
            yes += n
        elif s == "no":
            no += n
    return yes, no


def fetch_trades(m):
    """A window's trades, read with PLAN15's own fetch_trades (plan section 3: open to close + 60 s, archive and live
    endpoints merged by trade id); D uses only those up to the close of minute k."""
    return P.fetch_trades(m)


def derive_window(w, spot, trades):
    """The values a window keeps: per decision minute, the close S_k, the 15-minute sigma, the trend pattern and the
    taker flow. trades None = the fetch failed (no D signal, counted missing)."""
    o = int(w["open"])
    out = dict(ticker=w["ticker"], trades_ok=trades is not None, k={})
    for k in KS:
        c = candle(spot, o, k)
        v = dict(sk=c[3] if c else None, sig15=recent_sigma(spot, o, k), trend=trend(spot, o, k))
        if trades is not None:
            v["yes"], v["no"] = flow(trades, o, k)
        out["k"][str(k)] = v
    return out


def day_path(asset, d):
    return os.path.join(DATA, "days", asset, "%s.json.gz" % d.isoformat())


def find_days():
    p, ok = P._read_json(P.PERIODS)
    first, last = P.FIND
    if ok and isinstance(p, dict) and p.get("find"):
        first, last = date.fromisoformat(p["find"][0]), date.fromisoformat(p["find"][1])
    return P.days_of(first, last)


def build_day(asset, d, p15):
    t0 = P.day_start(d) - P.T_MIN * 60 - 75 * 60   # from 75 minutes before the first window (plan section 3)
    spot = P.fetch_spot(asset, t0 + 60, P.day_start(d) + 86400)
    wins = []
    for w in sorted(p15["windows"], key=lambda x: x["close"]):
        try:
            tr = fetch_trades(w)
        except (RuntimeError, ValueError, OSError, http.client.HTTPException) as ex:   # the day is not saved
            raise RuntimeError("trades for %s: %s" % (w["ticker"], ex))
        wins.append(derive_window(w, spot, tr))
    return dict(asset=asset, day=d.isoformat(), windows=wins, complete=True)


def download(max_days=None, budget_minutes=None, log=print, now=None):
    bad = identity_problems()
    if bad:
        return False, "not frozen or changed (%s); no download" % ", ".join(bad)
    start = time.time() if now is None else now
    done = waiting = 0
    for a in ASSETS:
        for d in find_days():
            path = day_path(a, d)
            if os.path.exists(path):
                continue
            p15, ok = P._read_json(P.day_path(a, d))
            if not (ok and isinstance(p15, dict) and p15.get("complete")):
                waiting += 1
                continue
            if (max_days is not None and done >= max_days) or \
                    (budget_minutes is not None and time.time() - start > 60 * budget_minutes):
                waiting += 1
                continue
            try:
                obj = build_day(a, d, p15)
            except (RuntimeError, ValueError, OSError, http.client.HTTPException) as ex:
                log("PLAN16 %s %s: not saved (%s); run again to retry" % (a, d, ex))
                waiting += 1
                continue
            P.save_gz(path, obj)
            done += 1
            log("PLAN16 %s %s: %d windows saved (%d with trades)" % (a, d, len(obj["windows"]),
                                                                      sum(1 for x in obj["windows"] if x["trades_ok"])))
    return True, "download: %d asset-days saved this run, %d waiting (PLAN15's day not saved yet, or the next run)" % (done, waiting)


# ---------- signals (plan section 2) ----------
def book_ok(q):
    """The minute-k quote is present and neither crossed nor locked (0 <= bid < ask <= 1)."""
    return P.mid_of(q) is not None


def edge_side(p_up, q, edge):
    """A and B: the side whose model chance beats its ask by at least `edge` (YES: p - YES ask; NO: (1 - p) - NO ask)."""
    ya, na = P.side_ask(q, "yes"), P.side_ask(q, "no")
    if ya is not None and p_up - ya >= edge - 1e-9:
        return "yes"
    if na is not None and (1.0 - p_up) - na >= edge - 1e-9:
        return "no"
    return None


def in_band(q, side):
    a = P.side_ask(q, side)
    return a is not None and BAND[0] - 1e-9 <= a <= BAND[1] + 1e-9


def decide(rule, w, v, k, ur):
    """(side or None, missing): the rule's signal at minute k for one window. missing=True when an input the rule
    needs is absent (counted, plan section 2)."""
    q = P.quote(w, k)
    if rule == "REF":   # PLAN15's own rule exactly as PLAN15 computes it (plan15.signal: no crossed-book check)
        if not P.spot_complete(w):
            return None, True
        rw = P.window_inputs(w, k, ur)["rw"]
        return (P.signal(rw, q), rw is None)
    if not book_ok(q):
        return None, True
    if rule == "A":
        s0, sk, sg = P.reference(w, ur), v.get("sk"), v.get("sig15")
        if not (s0 and sk and sg) or s0 <= 0 or sk <= 0:
            return None, True
        return edge_side(P.rw_prob(sk, s0, sg, k), q, EDGE_A), False
    if rule == "B":
        rw = P.window_inputs(w, k, ur)["rw"]
        if rw is None:
            return None, True
        return edge_side(rw, q, EDGE_B), False
    if rule == "C":
        t = v.get("trend")
        if t is None:
            return None, True
        side = {"up": "yes", "down": "no"}.get(t)
        return (side if side and in_band(q, side) else None), False
    if rule == "D":
        if "yes" not in v:
            return None, True
        n = v["yes"] + v["no"]
        if n < FLOW_MIN_CONTRACTS:
            return None, False
        imb = (v["yes"] - v["no"]) / n
        side = "yes" if imb >= FLOW_CUT - 1e-12 else "no" if imb <= -FLOW_CUT + 1e-12 else None
        return (side if side and in_band(q, side) else None), False
    raise ValueError(rule)


def rows_for(asset, p15days, p16days, insp):
    """Every (day, window, k, rule) signal with its fills, plus counts. Windows without a yes/no result are counted
    (PLAN15's saved files keep only yes/no results, so a void or scalar window appears here as one without a result)."""
    ur = P.use_reference(insp, asset)
    sig = {r: [] for r in RULES + ("REF",)}
    cnt = dict(windows=0, no_result=0, missing_spot=0, missing_kalshi=0, bad_abc=0, bad_d=0, agree=0, agree_n=0,
               missing_input={r: 0 for r in RULES + ("REF",)})
    for d in sorted(p15days):
        mine = {x["ticker"]: x for x in (p16days.get(d) or {}).get("windows", [])}
        for w in sorted(p15days[d]["windows"], key=lambda x: x["close"]):
            cnt["windows"] += 1
            x = mine.get(w["ticker"])
            y = P.y_of(w)
            sc = P.spot_complete(w) and x is not None and all(x["k"][str(k)]["sk"] is not None for k in KS)
            kc = P.candles_complete(w) and x is not None and x["trades_ok"]
            cnt["missing_spot"] += int(not (sc and P.candles_complete(w)))
            cnt["missing_kalshi"] += int(not kc)
            cnt["bad_abc"] += int(y is None or not (sc and P.candles_complete(w)))   # each window counted once
            cnt["bad_d"] += int(y is None or not kc)
            if y is None:
                cnt["no_result"] += 1
                continue
            if P.spot_complete(w):
                u = P.spot_up(w, ur)
                if u is not None:
                    cnt["agree_n"] += 1
                    cnt["agree"] += int(u == (y == 1.0))
            mult = P.multiplier_at(insp, asset, w["close"])
            for k in KS:
                v = (x or {}).get("k", {}).get(str(k)) or {}
                for rule in RULES + ("REF",):
                    side, missing = decide(rule, w, v, k, ur) if x is not None or rule in ("B", "REF") else (None, True)
                    if missing:
                        cnt["missing_input"][rule] += 1
                    if side is None:
                        continue
                    other = "no" if side == "yes" else "yes"
                    sig[rule].append(dict(day=d, ticker=w["ticker"], k=k, side=side, y=y,
                                          fills={dl: P.fill(w, k, side, dl, mult) for dl in (FILL_DELAY,) + LATE_DELAYS},
                                          flip=P.fill(w, k, other, FILL_DELAY, mult),
                                          capacity=(w.get("t") or {}).get(str(k + FILL_DELAY), 0.0)))
    return sig, cnt


# ---------- statistics (plan section 4) ----------
def profit(side, price, f, y):
    return P.profit(side, price, f, y)


def filled_of(sigs, delay=FILL_DELAY):
    out, why = [], {}
    for s in sigs:
        price, f, reason = s["fills"][delay]
        if price is None:
            why[reason] = why.get(reason, 0) + 1
            continue
        fp, ff, _ = s["flip"]
        other = "no" if s["side"] == "yes" else "yes"
        flip = profit(other, fp, ff, s["y"]) if fp is not None else None
        out.append(dict(day=s["day"], k=s["k"], side=s["side"], price=price, fee=f,
                        profit=profit(s["side"], price, f, s["y"]), flip=flip, capacity=s["capacity"]))
    return out, why


def day_means(filled, key="profit"):
    g = {}
    for t in filled:
        g.setdefault(t["day"], []).append(t[key])
    return {d: sum(v) / len(v) for d, v in g.items()}


def boot_p(dm, period_days, draws=BOOT_DRAWS, seed=SEED, level=None):
    """Bootstrap of non-overlapping 2-day calendar blocks over the period; a resampled block contributes only its days
    with a value; a draw is the mean of those values. Returns (share of draws <= 0, the draws' `level` quantile)."""
    blocks = [period_days[i:i + BOOT_BLOCK_DAYS] for i in range(0, len(period_days), BOOT_BLOCK_DAYS)]
    blocks = [[dm[d] for d in b if d in dm] for b in blocks]
    if not any(blocks):
        return None, None
    rnd = random.Random(seed)
    out = []
    while len(out) < draws:
        vals = []
        for _ in range(len(blocks)):
            vals.extend(blocks[rnd.randrange(len(blocks))])
        if vals:
            out.append(sum(vals) / len(vals))
    out.sort()
    p = sum(1 for m in out if m <= 0) / float(len(out))
    q = out[min(len(out) - 1, max(0, int(math.floor(level * len(out)))))] if level is not None else None
    return p, q


def placebo_p(filled, real, draws=PLACEBO_DRAWS, seed=SEED):
    """Side-flip placebo: each filled signal's side flipped by a fair coin, paid at the flipped side's own ask and fee
    at the same minute (a signal whose flipped side cannot be paid keeps its own side, as in PLAN15); statistic = the
    mean of day means; p = (1 + draws at least as profitable) / (1 + draws)."""
    rnd = random.Random(seed)
    days = sorted({t["day"] for t in filled})
    idx = {d: i for i, d in enumerate(days)}
    hit = 0
    for _ in range(draws):
        s, n = [0.0] * len(days), [0] * len(days)
        for t in filled:
            i = idx[t["day"]]
            alt = t["flip"] if t["flip"] is not None else t["profit"]
            s[i] += alt if rnd.random() < 0.5 else t["profit"]
            n[i] += 1
        if sum(s[i] / n[i] for i in range(len(days))) / len(days) >= real - 1e-12:
            hit += 1
    return (1.0 + hit) / (1.0 + draws)


def rule_stats(sigs):
    filled, why = filled_of(sigs)
    dm = day_means(filled)
    vals = [dm[d] for d in sorted(dm)]
    st = dict(signals=len(sigs), signal_days=len({s["day"] for s in sigs}), filled=len(filled), days=len(vals),
              no_trade=why, sides=dict(yes=sum(1 for t in filled if t["side"] == "yes"),
                                       no=sum(1 for t in filled if t["side"] == "no")))
    if st["signals"] < MIN_SIGNALS or st["signal_days"] < MIN_SIGNAL_DAYS:
        st["not_testable"] = "fewer than %d signals or fewer than %d days with a signal" % (MIN_SIGNALS, MIN_SIGNAL_DAYS)
    m, se = P.P7.mean_se(vals)
    if m is None:
        st.setdefault("not_testable", "fewer than 2 days with a filled trade")
        return st, filled, dm
    st.update(mean=m, se=se, t=(m / se) if se else None, df=len(vals) - 1,
              per_contract=sum(t["profit"] for t in filled) / len(filled),
              win_rate=sum(1 for t in filled if t["profit"] > 0) / float(len(filled)),
              mean_price=sum(t["price"] for t in filled) / len(filled),
              capacity_median=P.median([t["capacity"] for t in filled]),
              capacity_note="upper bound: contracts traded in the minute after the signal, both sides counted")
    st["p_t"] = P.p_one_sided(st["t"], st["df"]) if st["t"] is not None else (0.0 if m > 0 else 1.0)
    st["by_minute"] = {}
    for k in KS:
        fk = [t for t in filled if t["k"] == k]
        st["by_minute"][str(k)] = dict(filled=len(fk), per_contract=(sum(t["profit"] for t in fk) / len(fk)) if fk else None)
    late = {}
    for dl in LATE_DELAYS:
        f2, _ = filled_of(sigs, dl)
        d2 = day_means(f2)
        late["k+%d" % dl] = dict(filled=len(f2), mean=(sum(d2.values()) / len(d2)) if d2 else None)
    st["delayed_fills"] = late
    return st, filled, dm


def holm(tests, period_days):
    """Each test's p = max(t p, bootstrap p, placebo p); Holm at FAMILY over all tests (m = 8; a not-testable test stays
    in the count and never passes). A test passes at its level when t > max(2.0, the one-sided t value), the bootstrap's
    lower bound at that level is above 0, the placebo p is at most the level, and every test before it passed."""
    for x in tests:
        st = x["stats"]
        if "not_testable" in st:
            x["p"] = None
            continue
        bp, _ = boot_p(x["dm"], period_days)
        pp = placebo_p(x["filled"], st["mean"])
        st["p_boot"], st["p_placebo"] = bp, pp
        x["p"] = max(st["p_t"], bp if bp is not None else 1.0, pp)
    m = len(tests)
    order = sorted(tests, key=lambda x: (x["p"] if x["p"] is not None else 2.0, x["name"]))
    going = True
    for rank, x in enumerate(order):
        st = x["stats"]
        lvl = FAMILY / (m - rank)
        x["holm_rank"], x["holm_level"] = rank + 1, lvl
        if x["p"] is None:
            x["passed"], x["verdict"] = False, NOT_TESTABLE
            going = False
            continue
        tcut = max(T_FLOOR, P.P7.t_quantile(lvl, st["df"]))
        _, lo = boot_p(x["dm"], period_days, level=lvl)
        c1 = st["t"] is not None and st["t"] > tcut
        c2 = lo is not None and lo > 0
        c3 = st["p_placebo"] <= lvl
        x["checks"] = dict(t=st["t"], t_cut=tcut, t_ok=c1, boot_low=lo, boot_ok=c2, placebo_p=st["p_placebo"], placebo_ok=c3)
        x["passed"] = bool(going and c1 and c2 and c3)
        if not x["passed"]:
            going = False
        x["verdict"] = VERDICT_PASS if x["passed"] else VERDICT_FAIL
    return order


def asset_guard(cnt, n_days, rule):
    """None when the asset is testable for the rule, else why not (plan section 4)."""
    exp = WINDOWS_PER_DAY * n_days
    if not exp:
        return "no windows"
    absent = max(0, exp - cnt["windows"])
    if rule == "D":
        miss = (absent + cnt["bad_d"]) / float(exp)
        return None if miss <= MAX_MISSING else "%.1f%% of windows miss Kalshi candles or trades (more than 10%%)" % (100 * miss)
    miss = (absent + cnt["bad_abc"]) / float(exp)
    if miss > MAX_MISSING:
        return "%.1f%% of windows miss Coinbase or Kalshi data (more than 10%%)" % (100 * miss)
    if not cnt["agree_n"] or cnt["agree"] / float(cnt["agree_n"]) < MIN_AGREE:
        return "Coinbase's up-or-down agrees with Kalshi's result in fewer than 97% of windows"
    return None


def load_all():
    """{asset: (PLAN15 days, PLAN16 days)} for the find period, or (None, why) when PLAN16 is not complete."""
    out = {}
    for a in ASSETS:
        p15, p16 = {}, {}
        for d in find_days():
            o15, ok = P._read_json(P.day_path(a, d))
            if not (ok and isinstance(o15, dict) and o15.get("complete")):
                return None, "PLAN15's %s %s is not saved yet" % (a, d)
            o16, ok = P._read_json(day_path(a, d))
            if not (ok and isinstance(o16, dict) and o16.get("complete")):
                return None, "PLAN16's %s %s is not saved yet" % (a, d)
            p15[d], p16[d] = o15, o16
        out[a] = (p15, p16)
    return out, None


def score(out_path=None, data=None, insp=None, root=ROOT):
    out_path = out_path or RESULT
    md_path = out_path[:-5] + ".md"
    for f in (out_path, md_path):
        if os.path.exists(f):
            return None, "already scored (%s exists); the plan is scored once" % f
    bad = identity_problems(root)
    if bad:
        return None, "not frozen or changed (%s); no score" % ", ".join(bad)
    insp = insp or P.load_inspect()
    if not insp:
        return None, "PLAN15's inspect.json is missing"
    for a in ASSETS:
        fp = P.fee_problem(insp, a)
        if fp:
            return None, "fee multiplier unknown (%s)" % fp
    if data is None:
        data, why = load_all()
        if data is None:
            return None, why
    period = find_days()
    res = dict(plan=PLAN, plan_sha256=PLAN_SHA256, scored=datetime.now(timezone.utc).isoformat(),
               period=[period[0].isoformat(), period[-1].isoformat()], assets={}, tests=[], reference={},
               settings=dict(edge_a=EDGE_A, edge_b=EDGE_B, band=list(BAND), recent_returns=RECENT_RETURNS,
                             flow_minutes=FLOW_MINUTES, flow_min_contracts=FLOW_MIN_CONTRACTS, flow_cut=FLOW_CUT,
                             family=FAMILY, boot_block_days=BOOT_BLOCK_DAYS, boot_draws=BOOT_DRAWS,
                             placebo_draws=PLACEBO_DRAWS, seed=SEED, fill_delay=FILL_DELAY,
                             carry_forward_quote=P.CARRY_FORWARD_QUOTE,
                             placebo_unpaid_flip="a signal whose flipped side cannot be paid keeps its own side (as PLAN15)",
                             no_result_windows="PLAN15's day files keep only yes/no results: a void or scalar window "
                                               "counts as one without a result (missing)"))
    tests = []
    for a in ASSETS:
        p15, p16 = data[a]
        sig, cnt = rows_for(a, p15, p16, insp)
        res["assets"][a] = dict(counts=cnt, agreement=(cnt["agree"] / float(cnt["agree_n"])) if cnt["agree_n"] else None)
        for rule in RULES:
            st, filled, dm = rule_stats(sig[rule])
            g = asset_guard(cnt, len(p15), rule)
            if g:
                st["not_testable"] = g
            tests.append(dict(name="%s %s" % (a, rule), asset=a, rule=rule, stats=st, filled=filled, dm=dm))
        st, _, _ = rule_stats(sig["REF"])
        st.pop("not_testable", None)
        res["reference"][a] = dict(stats=st, note="PLAN15's own rule (RW, 4 points) on the same windows: a free preview "
                                   "of PLAN15's Q2 on its find period; not a test, says nothing about PLAN15's verdict, "
                                   "and is not to be used to change PLAN15 or PLAN15F")
    holm(tests, period)
    for x in sorted(tests, key=lambda x: (ASSETS.index(x["asset"]), x["rule"])):
        res["tests"].append({k: v for k, v in x.items() if k not in ("filled", "dm")})
    passed = [x["name"] for x in res["tests"] if x.get("passed")]
    res["verdict"] = (VERDICT_PASS + " (%s)" % ", ".join(passed)) if passed else VERDICT_FAIL
    json.dumps(res)      # checked first: a value that cannot be saved stops here, before anything is written
    md = markdown(res)   # built first: a crash here saves nothing, so the single score can still run
    with open(md_path + ".tmp", "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(md_path + ".tmp", md_path)
    jsonio.save(out_path, res)
    return res, res["verdict"]


def _f(v, fmt="%+.4f"):
    return "-" if v is None else fmt % v


def markdown(res):
    names = dict(A="A recent volatility", B="B choosier (10 points)", C="C trend (3 candles)", D="D order flow")
    out = ["# PLAN16 result (scored once)", "",
           "Plan: %s (SHA-256 %s). Windows closing %s to %s. Scored %s." % (res["plan"], res["plan_sha256"][:16],
                                                                          res["period"][0], res["period"][1], res["scored"]),
           "", "**Verdict: %s**" % res["verdict"], "",
           "| Test | Signals | Days | Filled | Win rate | Avg price | Profit / contract | Day mean (SE) | t | p | Holm level | Verdict |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in res["tests"]:
        st = x["stats"]
        out.append("| %s %s | %d | %d | %d | %s | %s | %s | %s (%s) | %s | %s | %s | %s |" % (
            x["asset"], names[x["rule"]], st["signals"], st["signal_days"], st["filled"], _f(st.get("win_rate"), "%.3f"),
            _f(st.get("mean_price"), "%.3f"), _f(st.get("per_contract")), _f(st.get("mean")), _f(st.get("se"), "%.4f"),
            _f(st.get("t"), "%.2f"), _f(x.get("p"), "%.4f"), _f(x.get("holm_level"), "%.5f"),
            x.get("verdict", "") + (" (%s)" % st["not_testable"] if st.get("not_testable") else "")))
    out += ["", "## Per minute and delayed fills (descriptive)", ""]
    for x in res["tests"]:
        st = x["stats"]
        bm = st.get("by_minute") or {}
        out.append("- %s %s: by minute %s; fills 3 and 5 minutes later: %s" % (
            x["asset"], names[x["rule"]], ", ".join("k=%s %s (%d)" % (k, _f(v["per_contract"]), v["filled"]) for k, v in sorted(bm.items(), key=lambda kv: int(kv[0]))) or "-",
            ", ".join("%s %s" % (k, _f(v["mean"])) for k, v in sorted((st.get("delayed_fills") or {}).items())) or "-"))
    out += ["", "## Reference (not a test): PLAN15's own rule on the same windows", ""]
    for a, r in res["reference"].items():
        st = r["stats"]
        out.append("- %s: %d signals, %d filled, profit per contract %s, win rate %s at an average price %s." % (
            a, st["signals"], st["filled"], _f(st.get("per_contract")), _f(st.get("win_rate"), "%.3f"), _f(st.get("mean_price"), "%.3f")))
    out += ["", "## Data", ""]
    for a, info in res["assets"].items():
        c = info["counts"]
        out.append("- %s: %d windows, %d without a yes/no result, %d missing Coinbase or candles, %d missing Kalshi trades; "
                   "Coinbase agrees with Kalshi's result in %s of windows." % (
                       a, c["windows"], c["no_result"], c["missing_spot"], c["missing_kalshi"], _f(info["agreement"], "%.3f")))
    out += ["", "A pass is a lead on past data, not a working system: it earns a place in the live paper bot with a forward "
            "rule written first. Real money would need a new live.py path that only the user can approve. Not financial advice.", ""]
    return "\n".join(out)


def status():
    rec, _ = P._read_json(IDENTITY)
    n = {a: sum(1 for d in find_days() if os.path.exists(day_path(a, d))) for a in ASSETS}
    p15 = {a: sum(1 for d in find_days() if os.path.exists(P.day_path(a, d))) for a in ASSETS}
    return "PLAN16: frozen %s; days saved %s of PLAN15's %s (of %d); scored: %s" % (
        bool(rec), n, p15, len(find_days()), os.path.exists(RESULT))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["freeze", "download", "score", "status"])
    ap.add_argument("--max-days", type=int)
    ap.add_argument("--budget-minutes", type=float)
    a = ap.parse_args(argv)
    if a.stage == "freeze":
        rec, msg = freeze()
    elif a.stage == "download":
        rec, msg = download(a.max_days, a.budget_minutes)
    elif a.stage == "score":
        rec, msg = score()
    else:
        rec, msg = True, status()
    print(msg)
    return 0 if rec else 1


if __name__ == "__main__":
    sys.exit(main())
