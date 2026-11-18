"""PLAN17 (research/PLAN17.md): can a small frozen model pick cheap (1-5c) sides of Kalshi's 15-minute BTC and ETH
markets at minutes 10-13 that win more often than their price says? Fitted once on September windows, scored once per
asset on October windows. Research and paper only: never part of the gate, never connected to live.py, places
nothing, never reads PLAN15's check period (Nov-Dec).

Stages (each refuses to run out of turn):
- freeze: identity record (SHA-256 of research/PLAN17.md, research/plan17.py, research/plan15.py and PLAN15's
  inspect.json, plus PLAN7's pinned functions), stored once in research/results/plan17_identity.json.
- download [--max-days N] [--budget-minutes M]: for each asset-day PLAN15 has saved in Sep-Oct, Coinbase's one-minute
  candles from 16 minutes before each window opens to minute 13 (in memory, never written); only derived values per
  window and decision minute are saved (research/results/plan17/days/). September first. Prints counts only.
- fit: once, when every September day of both assets is saved; reads September only; writes plan17_model.json.
- score ASSET: once per asset, when the model exists and every October day of that asset is saved; writes
  plan17_result_ASSET.md, then .json.
- status: counts only.

Standard library only; network through PLAN15's own clients (User-Agent tradebot-paper-research/1.0).
  python research/plan17.py freeze|download|fit|status
  python research/plan17.py score BTC|ETH
Python 3.8+."""
import argparse
import http.client
import json
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
import plan15 as P   # noqa: E402  (PLAN15's frozen helpers: day files, quotes, fills, RW, ridge fit, PLAN7's statistics)
from tbcommon import jsonio   # noqa: E402

PLAN = "research/PLAN17.md"
PLAN_SHA256 = "ceee706fb07aac21fa170db5484d5593f8aa82fa12769919b077847c662c1f3c"   # frozen 2026-11-18 (CHANGELOG)
FROZEN_FILES = ("research/PLAN17.md", "research/plan17.py", "research/plan15.py")
ASSETS = P.ASSETS
T = P.T_MIN                                # 15
KS = (10, 11, 12, 13)                      # decision minutes
CHEAP = (0.01, 0.05)                       # the cheap side's ask at minute k, inclusive
EDGE = 0.02                                # model chance - ask at minute k
FILL_DELAY = 1
SPOT_FROM, SPOT_TO = -16, 13               # Coinbase minutes read per window (plan sections 2 and 4)
RECENT = 15                                # sigma15: the 15 one-minute returns ending at minute k
MOM = 3                                    # x3 and x4: 3 minutes back
CLIP_P = (0.005, 0.995)
CLIP_Z = 6.0
RIDGE = 1.0
FIT_PERIOD = (date(2026, 9, 1), date(2026, 9, 30))
TEST_PERIOD = (date(2026, 10, 1), date(2026, 10, 31))
LEVEL = 0.0125                             # per asset (Bonferroni over two assets)
T_FLOOR = 2.3
BOOT_BLOCK_DAYS, BOOT_DRAWS = 2, 20000
PLACEBO_DRAWS = 2000
SEED = 17
MIN_BETS, MIN_DAYS = 100, 15
MAX_MISSING, MIN_AGREE = 0.10, 0.97
WINDOWS_PER_DAY = P.WINDOWS_PER_DAY
FEE_SOURCE = dict(document="Kalshi fee schedule, https://kalshi.com/docs/kalshi-fee-schedule.pdf",
                  effective="Last updated and effective: July 7, 2026",
                  formula="fees = round up(M x 0.07 x C x P x (1-P))",
                  rounding="round up = rounds up such that the fee + positionCost is rounded to a centicent",
                  read="2026-11-18")
VERDICT_PASS = "lead on past data: justifies a forward paper test"
VERDICT_FINE_ONLY = "lead under fine fee rounding only: justifies a forward paper test that records Kalshi's actual fees"
VERDICT_FAIL = "no edge shown"
NOT_TESTABLE = "not testable"

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(RESULTS, "plan17")
IDENTITY = os.path.join(RESULTS, "plan17_identity.json")
MODEL = os.path.join(RESULTS, "plan17_model.json")


def result_path(asset):
    return os.path.join(RESULTS, "plan17_result_%s.json" % asset)


# ---------- identity ----------
def identity_now(root=ROOT):
    out = {f: P.file_hash(os.path.join(root, *f.split("/"))) for f in FROZEN_FILES}
    out["research/results/plan15/inspect.json"] = P.file_hash(P.INSPECT)
    return out


def identity_problems(root=ROOT, path=None):
    rec, ok = P._read_json(path or IDENTITY)
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        bad.append("research/PLAN17.md differs from its frozen SHA-256")
    return bad + P.plan7_problems(root)


def freeze(root=ROOT, path=None, now=None):
    path = path or IDENTITY
    if os.path.exists(path):
        return None, "already frozen (%s); stored once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN17.md differs from its frozen SHA-256; nothing saved"
    p15 = P.identity_problems(root)
    if p15:
        return None, "PLAN15 is not frozen or differs from its record (%s); nothing saved" % ", ".join(p15)
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, identity=identity_now(root),
               frozen=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat())
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read"
    jsonio.save(path, rec)
    return rec, "frozen: %s" % path


# ---------- derived Coinbase values per window (plan section 2) ----------
def close_at(spot, o, i):
    c = spot.get(int(o) + 60 * i)
    return c[3] if c else None


def derive_window(w, spot):
    """Per decision minute: S_k, S_{k-3} and sigma15 (SD n-1 of the 15 returns ending at minute k). spot_ok: every
    Coinbase minute from -16 to 13 present (the 10% guard)."""
    o = int(w["open"])
    out = dict(ticker=w["ticker"], spot_ok=all(spot.get(o + 60 * i) is not None for i in range(SPOT_FROM, SPOT_TO + 1)),
               k={})
    for k in KS:
        out["k"][str(k)] = dict(sk=close_at(spot, o, k), sk3=close_at(spot, o, k - MOM),
                                sig15=P.sigma_from([close_at(spot, o, i) for i in range(k - RECENT, k + 1)]))
    return out


def day_path(asset, d):
    return os.path.join(DATA, "days", asset, "%s.json.gz" % d.isoformat())


def all_days():
    return P.days_of(FIT_PERIOD[0], FIT_PERIOD[1]) + P.days_of(TEST_PERIOD[0], TEST_PERIOD[1])


def build_day(asset, d, p15):
    ws = sorted(p15["windows"], key=lambda x: x["close"])
    if not ws:
        return dict(asset=asset, day=d.isoformat(), windows=[], complete=True)
    lo = min(int(w["open"]) for w in ws) + 60 * SPOT_FROM
    hi = max(int(w["open"]) for w in ws) + 60 * SPOT_TO
    spot = P.fetch_spot(asset, lo, hi)
    return dict(asset=asset, day=d.isoformat(), windows=[derive_window(w, spot) for w in ws], complete=True)


def download(max_days=None, budget_minutes=None, log=print, now=None):
    bad = identity_problems()
    if bad:
        return False, "not frozen or changed (%s); no download" % ", ".join(bad)
    start = time.time() if now is None else now
    done = waiting = 0
    fitted = os.path.exists(MODEL)
    for d in all_days():          # September first: the fit needs it; October only after the model is saved
        if d >= TEST_PERIOD[0] and not fitted:
            waiting += len(ASSETS)
            continue
        for a in ASSETS:
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
            except (RuntimeError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as ex:
                log("PLAN17 %s %s: not saved (%s); run again to retry" % (a, d, ex))
                waiting += 1
                continue
            if obj["windows"] and not any(x["spot_ok"] for x in obj["windows"]):
                log("PLAN17 %s %s: not saved (Coinbase gave no usable minutes); run again to retry" % (a, d))
                waiting += 1
                continue
            P.save_gz(path, obj)
            done += 1
            log("PLAN17 %s %s: %d windows saved (%d with full Coinbase minutes)" % (
                a, d, len(obj["windows"]), sum(1 for x in obj["windows"] if x["spot_ok"])))
    note = "" if fitted else " (October waits for the fit)"
    return True, "download: %d asset-days saved this run, %d waiting%s" % (done, waiting, note)


# ---------- the cheap side and its inputs (plan sections 1-2; only what is known at the close of minute k) ----------
def clip(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def cheap_side(q):
    """The side whose ask at minute k is 1c-5c on an uncrossed candle (0 < bid < ask), or None."""
    if not q or q[0] is None or q[1] is None or not (0 < q[0] < q[1]):
        return None
    for side in ("yes", "no"):
        a = P.side_ask(q, side)
        if a is not None and CHEAP[0] - 1e-9 <= a <= CHEAP[1] + 1e-9:
            return side
    return None


def state(w, v, k, ur):
    """(side, ask, x) at minute k when a cheap side exists and every input is present; (side, ask, None) when a cheap
    side exists but an input is missing (a window without floor_strike counts as missing); None when no cheap side.
    ur is not used here: S_0 is always the market's floor_strike (plan section 2)."""
    q = P.quote(w, k)
    side = cheap_side(q)
    if side is None:
        return None
    ask = P.side_ask(q, side)
    s0, sk, sk3, sg = P.num(w.get("strike")), v.get("sk"), v.get("sk3"), v.get("sig15")   # S_0 = floor_strike only
    if not (s0 and sk and sk3 and sg) or s0 <= 0 or sk <= 0 or sk3 <= 0:
        return side, ask, None
    sign = 1.0 if side == "yes" else -1.0
    q3 = P.quote(w, k - MOM)
    a3 = P.side_ask(q3, side) if q3 else None
    x1 = P.P7.logit(clip(ask, CLIP_P[0], CLIP_P[1]))
    x2 = clip(sign * math.log(sk / s0) / (sg * math.sqrt(T - k - 0.5)), -CLIP_Z, CLIP_Z)
    x3 = clip(sign * math.log(sk / sk3) / (sg * math.sqrt(MOM)), -CLIP_Z, CLIP_Z)
    x4 = (ask - a3) if a3 is not None else 0.0
    x5 = float(T - k)
    return side, ask, [x1, x2, x3, x4, x5]


def wins(side, y):
    return 1.0 if ((y == 1.0) if side == "yes" else (y == 0.0)) else 0.0


def fee_fine(p, mult):
    """Kalshi's taker fee rounded up to a centicent (FEE_SOURCE); the primary fee (plan section 1)."""
    return math.ceil(mult * 0.07 * p * (1 - p) * 10000 - 1e-9) / 10000


def pay(w, k, side, mult):
    """(price, fine fee, whole-cent fee, volume in the fill minute) when minute k + 1 can be paid (plan15.fill), else
    (None, reason)."""
    price, fw, why = P.fill(w, k, side, FILL_DELAY, mult)
    if price is None:
        return None, why
    c = (w.get("c") or {}).get(str(k + FILL_DELAY))
    vol = (c[2] if c and len(c) > 2 and c[2] is not None else 0.0)
    return dict(price=price, fee=fee_fine(price, mult), fee_cent=fw, vol=vol,
                cap=(w.get("t") or {}).get(str(k + FILL_DELAY), 0.0)), None


# ---------- data ----------
def load(asset, days):
    """{day: (PLAN15 day, PLAN17 day)}, or (None, why) when a day is not saved yet."""
    out = {}
    for d in days:
        o15, ok = P._read_json(P.day_path(asset, d))
        if not (ok and isinstance(o15, dict) and o15.get("complete")):
            return None, "PLAN15's %s %s is not saved yet" % (asset, d)
        o17, ok = P._read_json(day_path(asset, d))
        if not (ok and isinstance(o17, dict) and o17.get("complete")):
            return None, "PLAN17's %s %s is not saved yet" % (asset, d)
        out[d] = (o15, o17)
    return out, None


def each_window(data):
    """(day, PLAN15 window, PLAN17 values or None) in time order."""
    for d in sorted(data):
        o15, o17 = data[d]
        mine = {x["ticker"]: x for x in o17.get("windows", [])}
        for w in sorted(o15["windows"], key=lambda x: x["close"]):
            yield d, w, mine.get(w["ticker"])


# ---------- fit (plan section 3) ----------
def fit_rows(data, ur):
    rows = []
    for d, w, x in each_window(data):
        y = P.y_of(w)
        if y is None or x is None:
            continue
        for k in KS:
            st = state(w, x["k"].get(str(k)) or {}, k, ur)
            if st and st[2] is not None:
                rows.append((st[2], wins(st[0], y)))
    return rows


def fit(path=None, insp=None, datas=None, now=None):
    path = path or MODEL
    if os.path.exists(path):
        return None, "already fitted (%s); fitted once" % path
    if datas is None:
        bad = identity_problems()
        if bad:
            return None, "not frozen or changed (%s); no fit" % ", ".join(bad)
    insp = insp or P.load_inspect()
    if not insp:
        return None, "PLAN15's inspect.json is missing"
    rows = []
    for a in ASSETS:
        if datas is None:
            data, why = load(a, P.days_of(FIT_PERIOD[0], FIT_PERIOD[1]))   # September only
            if data is None:
                return None, why
        else:
            data = datas[a]
        if not P.use_reference(insp, a):
            return None, "PLAN15's inspect did not confirm floor_strike for %s; S_0 cannot be read as the plan says" % a
        rows += fit_rows(data, True)
    if len(rows) < 10:
        return None, "too few September rows (%d)" % len(rows)
    X, Y = [r[0] for r in rows], [r[1] for r in rows]
    mu, sd = P.standardise(X)
    Z = [[(v - m) / s for v, m, s in zip(x, mu, sd)] for x in X]
    if P.RIDGE_SCALE != "sum":
        return None, "PLAN15's RIDGE_SCALE is not 'sum'; the plan's penalty would differ"
    got = P.fit_ridge_logit(Z, Y, ridge=RIDGE)
    if got is None:
        return None, "the fit did not converge; nothing saved"
    b0, b, steps = got
    model = dict(plan=PLAN, plan_sha256=PLAN_SHA256, inputs=["logit_ask", "z_toward", "momentum3", "kalshi_move3",
                                                             "minutes_left"],
                 mean=mu, sd=sd, intercept=b0, coef=b, ridge=RIDGE, penalty="sum log-lik - 0.5 x ridge x sum(b^2)",
                 steps=steps, rows=len(rows), period=[FIT_PERIOD[0].isoformat(), FIT_PERIOD[1].isoformat()],
                 fee_source=FEE_SOURCE,
                 fitted=datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat())
    jsonio.save(path, model)
    return model, "fitted on %d September rows; saved %s" % (len(rows), path)


def prob(model, x):
    z = [(v - m) / s for v, m, s in zip(x, model["mean"], model["sd"])]
    return P.P7.sigmoid(model["intercept"] + sum(c * v for c, v in zip(model["coef"], z)))


# ---------- scoring (plan sections 4-5) ----------
def collect(data, model, insp, asset):
    """Bets (the rule), placebo candidates, calibration rows, baseline bets and counts for one asset's test days."""
    ur = P.use_reference(insp, asset)
    bets, cands, calib, base = [], [], [], []
    cnt = dict(windows=0, no_result=0, missing=0, agree=0, agree_n=0, no_input=0, no_strike=0, fired=0, unpaid={},
               base_unpaid=0)
    for d, w, x in each_window(data):
        cnt["windows"] += 1
        y = P.y_of(w)
        kal = all(P.quote(w, m) is not None for m in range(KS[0], KS[-1] + FILL_DELAY + 1))
        cnt["missing"] += int(y is None or x is None or not x.get("spot_ok") or not kal)
        if y is None:
            cnt["no_result"] += 1
            continue
        if P.spot_complete(w):
            u = P.spot_up(w, ur)
            if u is not None:
                cnt["agree_n"] += 1
                cnt["agree"] += int(u == (y == 1.0))
        if x is None:
            continue
        cnt["no_strike"] += int(P.num(w.get("strike")) is None)
        mult = P.multiplier_at(insp, asset, w["close"])
        fired = based = False
        for k in KS:
            st = state(w, x["k"].get(str(k)) or {}, k, ur)
            if not st:
                continue
            side, ask, xs = st
            f, why = pay(w, k, side, mult)
            win = wins(side, y)
            if f is not None:   # a placebo candidate: a cheap side that would fill at k + 1
                cands.append(dict(day=d, ticker=w["ticker"], k=k, cent=int(round(ask * 100)), win=win, **f))
            if not based:       # baseline: the first minute with a cheap side; no bet when it does not fill
                based = True
                if f is not None:
                    base.append(dict(day=d, k=k, win=win, **f))
                else:
                    cnt["base_unpaid"] += 1
            if xs is None:
                cnt["no_input"] += 1
                continue
            p = prob(model, xs)
            calib.append(dict(p=p, ask=ask, win=win, cent=int(round(ask * 100))))
            if not fired and p - ask >= EDGE - 1e-9:
                fired = True
                cnt["fired"] += 1
                if f is None:
                    cnt["unpaid"][why] = cnt["unpaid"].get(why, 0) + 1
                else:
                    bets.append(dict(day=d, ticker=w["ticker"], k=k, cent=int(round(ask * 100)), p=p, win=win, **f))
    return bets, cands, calib, base, cnt


def prof(b, cent=False):
    return b["win"] - b["price"] - (b["fee_cent"] if cent else b["fee"])


def day_means(bets, cent=False):
    g = {}
    for b in bets:
        g.setdefault(b["day"], []).append(prof(b, cent))
    return {d: sum(v) / len(v) for d, v in g.items()}


def mean_of(dm):
    return sum(dm.values()) / len(dm) if dm else None


def boot_p(dm, period_days, draws=None, seed=SEED):
    """Non-overlapping 2-day calendar blocks (the last day alone when the count is odd); a block contributes its days
    with a bet; a draw is the mean of those values. Returns the share of draws at or below zero."""
    blocks = [period_days[i:i + BOOT_BLOCK_DAYS] for i in range(0, len(period_days), BOOT_BLOCK_DAYS)]
    blocks = [[dm[d] for d in b if d in dm] for b in blocks]
    if not any(blocks):
        return None
    draws = draws or BOOT_DRAWS
    rnd = random.Random(seed)
    n = low = 0
    while n < draws:
        vals = []
        for _ in range(len(blocks)):
            vals.extend(blocks[rnd.randrange(len(blocks))])
        if vals:
            n += 1
            low += int(sum(vals) / len(vals) <= 0)
    return low / float(draws)


def band(cent):
    return "1-2c" if cent <= 2 else "3-5c"


def placebo(bets, cands, real, cent=False, draws=None, seed=SEED):
    """Matched random picks (plan section 4.3): each rule bet replaced by a random candidate of its own stratum (day x
    minute x ask cent), else day x ask cent, else day x band; at most one per window within a draw (the rule's own
    windows allowed). When no candidate exists at all, the rule's own bet stands in (not in the plan's text; it can only
    make the placebo more like the rule, so a pass is harder). Returns (p, fallback counts summed over all draws)."""
    draws = draws or PLACEBO_DRAWS
    by = {}
    for i, c in enumerate(cands):
        for key in (("m", c["day"], c["k"], c["cent"]), ("c", c["day"], c["cent"]), ("b", c["day"], band(c["cent"]))):
            by.setdefault(key, []).append(i)
    rnd = random.Random(seed)
    used_fb = dict(stratum=0, cent=0, band=0, none=0)
    hit = 0
    days = sorted({b["day"] for b in bets})
    per_day = {d: [b for b in bets if b["day"] == d] for d in days}
    for _ in range(draws):
        tot = 0.0
        for d in days:
            seen = set()
            vals = []
            order = list(per_day[d])
            rnd.shuffle(order)
            for b in order:
                pick = None
                for name, key in (("stratum", ("m", d, b["k"], b["cent"])), ("cent", ("c", d, b["cent"])),
                                  ("band", ("b", d, band(b["cent"])))):
                    pool = [i for i in by.get(key, ()) if cands[i]["ticker"] not in seen]
                    if pool:
                        pick = cands[rnd.choice(pool)]
                        used_fb[name] += 1
                        break
                if pick is None:
                    used_fb["none"] += 1
                    vals.append(prof(b, cent))
                    continue
                seen.add(pick["ticker"])
                vals.append(prof(pick, cent))
            tot += sum(vals) / len(vals)
        if tot / len(days) >= real - 1e-12:
            hit += 1
    return (1.0 + hit) / (1.0 + draws), used_fb


def exact_p(bets, cent=False):
    """P(wins >= the rule's wins) when each bet wins with probability price + fee (Poisson-binomial, exact). With fixed
    costs, total profit at least the rule's is the same event."""
    dist = [1.0]
    for b in bets:
        q = clip(b["price"] + (b["fee_cent"] if cent else b["fee"]), 0.0, 1.0)
        new = [0.0] * (len(dist) + 1)
        for i, v in enumerate(dist):
            new[i] += v * (1 - q)
            new[i + 1] += v * q
        dist = new
    w = int(round(sum(b["win"] for b in bets)))
    return sum(dist[w:])


def checks(bets, cands, period_days, cent=False):
    dm = day_means(bets, cent)
    vals = [dm[d] for d in sorted(dm)]
    m, se = P.P7.mean_se(vals)
    out = dict(days=len(vals), mean=m, se=se)
    if m is None:
        out.update(passed=False, why="fewer than 2 days with a bet")
        return out
    t = (m / se) if se else (float("inf") if m > 0 else float("-inf"))
    df = len(vals) - 1
    tcut = max(T_FLOOR, P.P7.t_quantile(LEVEL, df))
    bp = boot_p(dm, period_days)
    pp, fb = placebo(bets, cands, m, cent)
    ep = exact_p(bets, cent)
    out.update(t=t, df=df, t_cut=tcut, t_ok=t > tcut, p_t=P.p_one_sided(t, df) if math.isfinite(t) else (0.0 if t > 0 else 1.0),
               p_boot=bp, boot_ok=bp is not None and bp <= LEVEL, p_placebo=pp, placebo_ok=pp <= LEVEL,
               placebo_fallbacks=fb, p_exact=ep, exact_ok=ep <= LEVEL)
    out["passed"] = bool(out["t_ok"] and out["boot_ok"] and out["placebo_ok"] and out["exact_ok"])
    return out


def clustered(bets):
    """Total profit / bets with a day-clustered standard error."""
    n = len(bets)
    if not n:
        return None, None
    mean = sum(prof(b) for b in bets) / n
    g = {}
    for b in bets:
        g.setdefault(b["day"], []).append(prof(b) - mean)
    D = len(g)
    if D < 2:
        return mean, None
    return mean, math.sqrt(sum(sum(v) ** 2 for v in g.values()) * D / (D - 1.0)) / n


def describe(bets):
    n = len(bets)
    if not n:
        return dict(bets=0)
    out = dict(bets=n, wins=int(sum(b["win"] for b in bets)), win_rate=sum(b["win"] for b in bets) / n,
               mean_price=sum(b["price"] for b in bets) / n, per_contract=sum(prof(b) for b in bets) / n,
               per_contract_cent=sum(prof(b, True) for b in bets) / n)
    for key, cent in (("", False), ("_cent", True)):
        dm = day_means(bets, cent)
        m, se = P.P7.mean_se([dm[d] for d in sorted(dm)])
        out["day_mean" + key], out["day_se" + key] = m, se
    return out


def guard(cnt, n_days):
    exp = WINDOWS_PER_DAY * n_days
    miss = (max(0, exp - cnt["windows"]) + cnt["missing"]) / float(exp) if exp else 1.0
    if miss > MAX_MISSING:
        return "%.1f%% of windows miss Coinbase or Kalshi data (more than 10%%)" % (100 * miss)
    if not cnt["agree_n"] or cnt["agree"] / float(cnt["agree_n"]) < MIN_AGREE:
        return "Coinbase's up-or-down agrees with Kalshi's result in fewer than 97% of windows"
    return None


def score(asset, out_path=None, data=None, insp=None, model=None, root=ROOT):
    if asset not in ASSETS:
        return None, "unknown asset %r" % asset
    out_path = out_path or result_path(asset)
    md_path = out_path[:-5] + ".md"
    for f in (out_path, md_path):
        if os.path.exists(f):
            return None, "already scored (%s exists); each asset is scored once" % f
    if data is None:
        bad = identity_problems(root)
        if bad:
            return None, "not frozen or changed (%s); no score" % ", ".join(bad)
    if model is None:
        model, ok = P._read_json(MODEL)
        if not (ok and isinstance(model, dict) and model.get("coef")):
            return None, "no model yet (run fit first)"
    if model.get("plan_sha256") != PLAN_SHA256:
        return None, "the model was not fitted under this plan; no score"
    insp = insp or P.load_inspect()
    if not insp:
        return None, "PLAN15's inspect.json is missing"
    fp = P.fee_problem(insp, asset)
    if fp:
        return None, "fee multiplier unknown (%s)" % fp
    if not P.use_reference(insp, asset):
        return None, "PLAN15's inspect did not confirm floor_strike for %s; S_0 cannot be read as the plan says" % asset
    period = P.days_of(TEST_PERIOD[0], TEST_PERIOD[1])
    if data is None:
        data, why = load(asset, period)
        if data is None:
            return None, why
    bets, cands, calib, base, cnt = collect(data, model, insp, asset)
    res = dict(plan=PLAN, plan_sha256=PLAN_SHA256, asset=asset, scored=datetime.now(timezone.utc).isoformat(),
               period=[period[0].isoformat(), period[-1].isoformat()],
               model_sha256=P._sha(json.dumps(model, sort_keys=True)), counts=cnt,
               agreement=(cnt["agree"] / float(cnt["agree_n"])) if cnt["agree_n"] else None,
               settings=dict(use_reference=True, windows_per_day=WINDOWS_PER_DAY, ks=list(KS), cheap=list(CHEAP), edge=EDGE, level=LEVEL, t_floor=T_FLOOR,
                             boot_block_days=BOOT_BLOCK_DAYS, boot_draws=BOOT_DRAWS, placebo_draws=PLACEBO_DRAWS,
                             seed=SEED, min_bets=MIN_BETS, min_days=MIN_DAYS, fee_source=FEE_SOURCE,
                             carry_forward_quote=P.CARRY_FORWARD_QUOTE))
    rule = describe(bets)
    rule["days"] = len({b["day"] for b in bets})
    rule["by_minute"] = {str(k): describe([b for b in bets if b["k"] == k]) for k in KS}
    rule["bet_weighted"], rule["bet_weighted_se"] = clustered(bets)
    v1 = [b for b in bets if b["vol"] >= 1]
    rule["volume_at_least_1"] = describe(v1)
    rule["capacity_median"] = P.median([b["cap"] for b in bets]) if bets else None
    res["rule"] = rule
    res["baseline"] = describe(base)
    bands = {}
    for c in calib:
        g = bands.setdefault(str(c["cent"]), [0, 0.0, 0.0])
        g[0] += 1
        g[1] += c["win"]
        g[2] += c["ask"]
    res["cheap_calibration"] = {k: dict(n=v[0], win_rate=v[1] / v[0], mean_ask=v[2] / v[0]) for k, v in sorted(bands.items())}
    cs = sorted(calib, key=lambda c: c["p"])
    dec = []
    for i in range(10):
        part = cs[i * len(cs) // 10:(i + 1) * len(cs) // 10]
        if part:
            dec.append(dict(n=len(part), predicted=sum(c["p"] for c in part) / len(part),
                            actual=sum(c["win"] for c in part) / len(part)))
    res["model_calibration_deciles"] = dec
    res["model"] = dict(intercept=model["intercept"], coef=model["coef"], inputs=model.get("inputs"))
    why = guard(cnt, len(period))
    if why is None and (rule["bets"] < MIN_BETS or rule["days"] < MIN_DAYS):
        why = "fewer than %d bets or fewer than %d days with a bet" % (MIN_BETS, MIN_DAYS)
    if why:
        res["checks"], res["verdict"] = None, "%s (%s)" % (NOT_TESTABLE, why)
    else:
        res["checks"] = checks(bets, cands, period)
        res["checks_whole_cent"] = checks(bets, cands, period, cent=True)
        if res["checks"]["passed"]:
            res["verdict"] = VERDICT_PASS if res["checks_whole_cent"]["passed"] else VERDICT_FINE_ONLY
        else:
            res["verdict"] = VERDICT_FAIL
        bw = rule["bet_weighted"]
        dmean = res["checks"].get("mean")
        sgn = lambda v: (v > 0) - (v < 0)   # noqa: E731
        if bw is not None and dmean is not None and sgn(bw) != sgn(dmean):
            res["verdict_note"] = "the bet-weighted profit and the day-mean reading differ in sign"
    json.dumps(res)
    md = markdown(res)
    with open(md_path + ".tmp", "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(md_path + ".tmp", md_path)
    jsonio.save(out_path, res)
    return res, res["verdict"]


def _f(v, fmt="%+.4f"):
    return "-" if v is None else fmt % v


def markdown(res):
    r = res["rule"]
    out = ["# PLAN17 result, %s (scored once)" % res["asset"], "",
           "Plan: %s (SHA-256 %s). Windows closing %s to %s. Scored %s." % (
               res["plan"], res["plan_sha256"][:16], res["period"][0], res["period"][1], res["scored"]),
           "", "**Verdict: %s**" % res["verdict"]]
    if res.get("verdict_note"):
        out.append("Note: %s." % res["verdict_note"])
    out += ["", "## The rule (cheap side at minutes 10-13, model at least 2 points above the ask)", "",
            "- Bets %d on %s days, wins %s (win rate %s at an average price %s); profit per contract %s "
            "(whole-cent fee %s); day mean %s (SE %s; whole-cent %s, SE %s); bet-weighted %s (day-clustered SE %s)." % (
                r["bets"], r.get("days", 0), r.get("wins", "-"), _f(r.get("win_rate"), "%.3f"),
                _f(r.get("mean_price"), "%.3f"), _f(r.get("per_contract")), _f(r.get("per_contract_cent")),
                _f(r.get("day_mean")), _f(r.get("day_se"), "%.4f"), _f(r.get("day_mean_cent")),
                _f(r.get("day_se_cent"), "%.4f"), _f(r.get("bet_weighted")), _f(r.get("bet_weighted_se"), "%.4f"))]
    for k, v in sorted((r.get("by_minute") or {}).items(), key=lambda kv: int(kv[0])):
        out.append("- minute %s: %d bets, day mean %s (SE %s); whole-cent fee %s (SE %s)" % (
            k, v["bets"], _f(v.get("day_mean")), _f(v.get("day_se"), "%.4f"), _f(v.get("day_mean_cent")),
            _f(v.get("day_se_cent"), "%.4f")))
    vv = r.get("volume_at_least_1") or {}
    out.append("- fills with volume in the fill minute: %d bets, profit per contract %s; median contracts traded "
               "there %s (an upper bound)" % (vv.get("bets", 0), _f(vv.get("per_contract")), _f(r.get("capacity_median"), "%.1f")))
    for name, key in (("Fine fee (primary)", "checks"), ("Whole-cent fee", "checks_whole_cent")):
        c = res.get(key)
        if not c:
            continue
        out += ["", "## Checks, %s (each at most %.2f%%)" % (name, 100 * LEVEL), "",
                "- day mean %s (SE %s, %d days): t %s against %s -> %s" % (
                    _f(c.get("mean")), _f(c.get("se"), "%.4f"), c["days"], _f(c.get("t"), "%.2f"),
                    _f(c.get("t_cut"), "%.2f"), c.get("t_ok")),
                "- bootstrap share at or below 0: %s -> %s" % (_f(c.get("p_boot"), "%.4f"), c.get("boot_ok")),
                "- matched placebo p: %s -> %s (fallbacks summed over all draws %s)" % (_f(c.get("p_placebo"), "%.4f"), c.get("placebo_ok"),
                                                                 c.get("placebo_fallbacks")),
                "- exact bound p: %s -> %s" % (_f(c.get("p_exact"), "%.5f"), c.get("exact_ok")),
                "- all four: %s" % c.get("passed")]
    b = res["baseline"]
    out += ["", "## Buy every cheap side at the first eligible minute (baseline, no model)", "",
            "- %d bets, win rate %s at an average price %s, profit per contract %s (whole-cent %s)." % (
                b["bets"], _f(b.get("win_rate"), "%.3f"), _f(b.get("mean_price"), "%.3f"), _f(b.get("per_contract")),
                _f(b.get("per_contract_cent"))),
            "", "## How often cheap sides won (all eligible minutes, descriptive)", "",
            "Counted: every cheap side with all inputs present, at each decision minute 10-13 (up to 4 per window).", "",
            "| Ask | Count | Won | Average ask |", "|---|---|---|---|"]
    for k, v in res["cheap_calibration"].items():
        out.append("| %sc | %d | %.3f | %.3f |" % (k, v["n"], v["win_rate"], v["mean_ask"]))
    out += ["", "## The model's October calibration (deciles)", "", "| n | Predicted | Actual |", "|---|---|---|"]
    for d in res["model_calibration_deciles"]:
        out.append("| %d | %.4f | %.4f |" % (d["n"], d["predicted"], d["actual"]))
    c = res["counts"]
    out += ["", "## Data", "",
            "- %d windows, %d without a yes/no result, %d missing Coinbase or Kalshi data, %d cheap sides without an "
            "input; rule fired %d times, unpaid %s; Coinbase agrees with Kalshi's result in %s of windows." % (
                c["windows"], c["no_result"], c["missing"], c["no_input"], c["fired"], c["unpaid"] or "none",
                _f(res["agreement"], "%.3f")),
            "- The 97%% agreement check is PLAN15's own (plan15.spot_up with PLAN15's reference), as the plan says.",
            "- Windows with a result other than yes or no cannot appear: PLAN15's day files keep only yes/no, so such "
            "windows count as missing (the plan's strategy.payout clause has nothing to apply to).",
            "- Windows without floor_strike: %d (their cheap sides count as missing inputs); baseline first cheap "
            "minutes that did not fill: %d." % (c.get("no_strike", 0), c.get("base_unpaid", 0)),
            "", "A pass is a lead on past data, not a working system: it earns a rule in the live paper bot with a "
            "forward rule written first. Real money would need a new live.py path that only the user can approve. "
            "Not financial advice.", ""]
    return "\n".join(out)


def status():
    rec, _ = P._read_json(IDENTITY)
    sep = P.days_of(FIT_PERIOD[0], FIT_PERIOD[1])
    octo = P.days_of(TEST_PERIOD[0], TEST_PERIOD[1])
    n = {a: dict(sep=sum(1 for d in sep if os.path.exists(day_path(a, d))),
                 oct=sum(1 for d in octo if os.path.exists(day_path(a, d)))) for a in ASSETS}
    return "PLAN17: frozen %s; days saved %s (of %d and %d); fitted %s; scored %s" % (
        bool(rec), n, len(sep), len(octo), os.path.exists(MODEL), {a: os.path.exists(result_path(a)) for a in ASSETS})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["freeze", "download", "fit", "score", "status"])
    ap.add_argument("asset", nargs="?")
    ap.add_argument("--max-days", type=int)
    ap.add_argument("--budget-minutes", type=float)
    a = ap.parse_args(argv)
    if a.stage == "freeze":
        rec, msg = freeze()
    elif a.stage == "download":
        rec, msg = download(a.max_days, a.budget_minutes)
    elif a.stage == "fit":
        rec, msg = fit()
    elif a.stage == "score":
        rec, msg = score(a.asset or "")
    else:
        rec, msg = True, status()
    print(msg)
    return 0 if rec else 1


if __name__ == "__main__":
    sys.exit(main())
