"""POWER22 (research/PLAN22.md section 7): the day-to-day SD of Brier(RW) - Brier(mid) on Jun-Aug 2026, per asset.

Read-only. No network, no DVOL. Reads only PLAN18's saved day files (research/results/plan18/comp and kalshi, windows
closing 2026-06-01 to 2026-08-31, already read by PLAN18) and writes only research/results/power22.json and .md.

For each asset and each row (window, k in 2, 5, 10, 13) with a mid at minute k (plan15.quote, plan15.mid_of), a yes/no
result (plan15.y_of) and Coinbase closes for the 60 minutes before the open and at minute k (PLAN18's comp files,
"CB", labelled by the end of the minute):
    p_rw = plan15.rw_prob(S_k, S_0, sigma, k), sigma = plan15.sigma_from(the 61 closes ending at the open),
    S_0 = Coinbase's close of the minute ending at the open, S_k = its close of the minute ending at open + 60k.
Day value = mean over the day's rows of (p_rw - y)^2 - (mid - y)^2 (day = the UTC day of the window's close, i.e. the
Kalshi file's day). Printed: the SD (n - 1) of the day values, SE = SD / sqrt(days), the day count, coverage counts and
the detectable Brier difference for stage 2. The mean is not printed or saved (PLAN22 section 7).

Python 3.8 syntax; standard library plus plan15/plan7 functions.
"""
import json
import math
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import plan15 as P   # noqa: E402
import plan7 as P7   # noqa: E402

DATA = os.path.join(ROOT, "research", "results", "plan18")
OUT_JSON = os.path.join(ROOT, "research", "results", "power22.json")
OUT_MD = os.path.join(ROOT, "research", "results", "power22.md")
ASSETS = ("BTC", "ETH")
KS = (2, 5, 10, 13)
COMP_FIRST, FIRST, LAST = date(2026, 5, 31), date(2026, 6, 1), date(2026, 8, 31)
FORBIDDEN = (date(2026, 11, 1), date(2026, 12, 31))   # PLAN15's check period: never read
STAGE2_DAYS = 59                                      # windows closing 2027-01-01 to 2027-02-28
STAGE2_LEVEL = 0.025                                  # stage 2's family level (one test: the first Holm level)
Z80 = 0.8416                                          # one-sided 80% power
T_FLOOR = 2.0


def path(kind, asset, d):
    assert not (FORBIDDEN[0] <= d <= FORBIDDEN[1]), "PLAN15's Nov-Dec check period must not be read: %s" % d
    assert COMP_FIRST <= d <= LAST, "outside POWER22's months: %s" % d
    return os.path.join(DATA, kind, asset, "%s.json.gz" % d.isoformat())


def load(kind, asset, first, last):
    out, missing = {}, []
    for d in P.days_of(first, last):
        o, ok = P._read_json(path(kind, asset, d))
        if ok and isinstance(o, dict) and o.get("complete"):
            out[d] = o
        else:
            missing.append(d.isoformat())
    return out, missing


def coinbase_closes(comps):
    cb = {}
    for d, c in comps.items():
        t0 = int(P.day_start(d))
        for j, v in enumerate(c["CB"]):
            if v is not None:
                cb[t0 + 60 * (j + 1)] = v
    return cb


def asset_rows(asset):
    comps, miss_c = load("comp", asset, COMP_FIRST, LAST)
    kal, miss_k = load("kalshi", asset, FIRST, LAST)
    cb = coinbase_closes(comps)
    cov = dict(comp_days=len(comps), comp_days_missing=miss_c, kalshi_days=len(kal), kalshi_days_missing=miss_k,
               comp_minutes=len(cb), comp_minutes_expected=1440 * len(comps), windows=0, days_with_96_windows=0,
               rows=0, rows_possible=0, no_result=0, no_mid=0, no_coinbase=0, s0_matches_spot_close=0, s0_checked=0)
    by_day = {}
    for d in sorted(kal):
        ws = kal[d]["windows"]
        cov["windows"] += len(ws)
        cov["days_with_96_windows"] += int(len(ws) == P.WINDOWS_PER_DAY)
        for w in ws:
            o = int(w["open"])
            y = P.y_of(w)
            look = [cb.get(o - 60 * i) for i in range(P.SIGMA_MIN, -1, -1)]   # closes ending at open-60 .. open
            sig = P.sigma_from(look)
            s0 = cb.get(o)
            sc0 = P.spot_close(w, 0)
            if s0 is not None and sc0 is not None:
                cov["s0_checked"] += 1
                cov["s0_matches_spot_close"] += int(abs(s0 - sc0) < 0.01 + 1e-9)
            for k in KS:
                cov["rows_possible"] += 1
                if y is None:
                    cov["no_result"] += 1
                    continue
                mid = P.mid_of(P.quote(w, k))
                if mid is None:
                    cov["no_mid"] += 1
                    continue
                sk = cb.get(o + 60 * k)
                if not (sig and s0 and sk):
                    cov["no_coinbase"] += 1
                    continue
                p = P.rw_prob(sk, s0, sig, k)
                by_day.setdefault(d, []).append((p - y) ** 2 - (mid - y) ** 2)
                cov["rows"] += 1
    return by_day, cov


def summarise(by_day):
    v = [sum(x) / len(x) for _, x in sorted(by_day.items())]
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    tq = max(T_FLOOR, P7.t_quantile(STAGE2_LEVEL, STAGE2_DAYS - 1))
    se2 = sd / math.sqrt(STAGE2_DAYS)
    return dict(days=n, sd_day_means=sd, se=sd / math.sqrt(n), stage2_days=STAGE2_DAYS, stage2_t=tq,
                stage2_se=se2, detectable_stage2=(tq + Z80) * se2)


def main():
    res = dict(plan="research/PLAN22.md section 7 (POWER22)", period="windows closing 2026-06-01 to 2026-08-31",
               model="plan15.rw_prob with plan15.sigma_from of the 60 Coinbase returns before the open; "
                     "S_0 = Coinbase close at the open; mid = plan15.mid_of(plan15.quote(w, k)); k = 2, 5, 10, 13",
               assets={})
    for a in ASSETS:
        by_day, cov = asset_rows(a)
        res["assets"][a] = dict(coverage=cov, **summarise(by_day))
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    os.replace(tmp, OUT_JSON)
    lines = ["# POWER22 (PLAN22 section 7)", "", "Read-only on PLAN18's saved Jun-Aug files; no DVOL, no network. "
             "Day values: mean of Brier(RW, PLAN15's 60-minute SD) - Brier(mid) over rows (window, k = 2, 5, 10, 13).",
             "", "| Asset | Days | Rows | SD of day means | SE (these days) | Stage 2 t (58 df) | "
             "Detectable at 80% power, stage 2 (59 days, 2.5%) |", "|---|---|---|---|---|---|---|"]
    for a in ASSETS:
        r = res["assets"][a]
        lines.append("| %s | %d | %d | %.5f | %.5f | %.3f | %.5f |" % (
            a, r["days"], r["coverage"]["rows"], r["sd_day_means"], r["se"], r["stage2_t"], r["detectable_stage2"]))
    lines += ["", "Coverage:"]
    for a in ASSETS:
        c = res["assets"][a]["coverage"]
        lines.append("- %s: Kalshi days %d (missing %s), composite days %d (missing %s), Coinbase minutes %d of %d; "
                     "windows %d, days with 96 windows %d; rows %d of %d (no result %d, no mid %d, no Coinbase %d); "
                     "S_0 equals plan15.spot_close(w, 0) in %d of %d windows." % (
                         a, c["kalshi_days"], c["kalshi_days_missing"] or "none", c["comp_days"],
                         c["comp_days_missing"] or "none", c["comp_minutes"], c["comp_minutes_expected"],
                         c["windows"], c["days_with_96_windows"], c["rows"], c["rows_possible"], c["no_result"],
                         c["no_mid"], c["no_coinbase"], c["s0_matches_spot_close"], c["s0_checked"]))
    lines += ["", "The mean difference is deliberately not computed for display (PLAN22 section 7)."]
    with open(OUT_MD + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(OUT_MD + ".tmp", OUT_MD)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
