"""Historical OHLC anomaly audit (research only; added 2026-10-23, reliability work). Read-only: public GETs, no orders.

Several parts of the bot trust Kalshi's one-minute candles: plan3.py and fetch.py build past data from them, shadow.py
measures price moves with them, and PLAN5 test L reads the mid after each fill from them. Each takes "the latest
candle at or before t". This audit fetches the candles of markets the bot already logged (paper.db obs) after they
settle, checks every candle with tbcommon.ohlc, and reports how often the data is broken or old:
- anomaly counts by code (see tbcommon/ohlc.py) per 1,000 candles, for rain and temperature markets;
- staleness: the age of the candle that "latest at or before t" would use, at the minute the bot logged the market;
- agreement: the candle mid at that minute against the mid the bot read from the live order book (paper.db obs.mid).
  Large gaps mean the history and the live quotes disagree, which past-data backtests would not notice.
Descriptive only: nothing reads these results to change a decision or a score.

  python research/ohlc_audit.py run [--days N] [--max M] [--every SECONDS]
      audit settled markets whose day ended 6 h to N days ago (default 21), up to M new markets per run (default 60);
      each market is audited once (settled candles do not change) -> data/ohlc/audit.jsonl
  python research/ohlc_audit.py report                 -> results/ohlc_audit.md and ohlc_audit.json
Python 3.8+. Same domain and User-Agent as kalshi.py."""
import os, sys, time, sqlite3, statistics
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tbcommon.httpclient import JsonClient, KALSHI_PUBLIC
from tbcommon.jsonio import lines, append, save, load
from tbcommon import ohlc, clock

DATA = os.path.join(HERE, "data", "ohlc"); OUT = os.path.join(HERE, "results")
AUDIT = os.path.join(DATA, "audit.jsonl")
CLIENT = JsonClient(KALSHI_PUBLIC, tries=5, timeout=30, min_gap=0.125, backoff_base=2.0, backoff_cap=60.0)
CHUNK = 24 * 3600          # one-minute candles fetched a day at a time (1,440 per request)
BEFORE = 36 * 3600         # window: from 36 h before the market day starts (weather markets list about a day ahead)
AFTER = 30 * 3600          # to 30 h after it starts (the day plus the settlement hours)
SETTLED_AFTER = 30 * 3600  # audit only once the window is over
DISAGREE = 0.05            # snapshot vs candle mid gap worth counting (5 points)
MAX_SPREAD = 0.06          # a candle mid is compared with the bot's snapshot only at this spread or less (config.MAX_SPREAD)
TRIES = 3                  # a market that fails, or answers with no candles, is tried on this many runs, then left


def http(path, params=None):
    return CLIENT.get(path, params)


def day_start(ticker):
    import postmortem
    return postmortem.day_start(ticker)


def candles(series, ticker, t0, t1):
    """One-minute candles in [t0, t1], fetched a day at a time, in time order (duplicates across chunks dropped)."""
    out, seen = [], set()
    a = int(t0)
    while a < t1:
        b = int(min(t1, a + CHUNK))
        j = http("/series/%s/markets/%s/candlesticks" % (series, ticker), dict(start_ts=a, end_ts=b, period_interval=1))
        for c in j.get("candlesticks") or []:
            k = c.get("end_period_ts")
            if k not in seen:
                seen.add(k); out.append(c)
        a = b
    return sorted(out, key=lambda c: c.get("end_period_ts") or 0)


def latest_at(cs, t):
    """The candle "latest at or before t" picks, or None. cs in time order."""
    last = None
    for c in cs:
        if (c.get("end_period_ts") or 0) <= t:
            last = c
        else:
            break
    return last


def audit_market(ticker, mtype, cs, now, snaps=()):
    """One audit record from a market's candles. snaps: [(ts, mid)] the bot read from the live order book."""
    codes = ohlc.check_series(cs, 60, now)
    count = ohlc.summary([codes])
    times = [c["end_period_ts"] for c in cs if isinstance(c.get("end_period_ts"), (int, float))]
    gaps = [b - a for a, b in zip(times, times[1:])]
    with_mid = sum(ohlc.mid(c) is not None for c in cs)
    rec = dict(ticker=ticker, series=ticker.split("-")[0], mtype=mtype, checked=round(now, 1), candles=len(cs),
               with_mid=with_mid, codes=count, first=times[0] if times else None, last=times[-1] if times else None,
               max_gap_s=max(gaps) if gaps else None, bad_minutes=sorted({cs[i]["end_period_ts"] for i, k in codes if i is not None and k not in ohlc.INFO_CODES})[:20])
    rec["snapshots"] = []
    for ts, smid in snaps:
        c = latest_at(cs, ts)
        cm = ohlc.mid(c) if c else None
        sp = (ohlc.ohlc(c, "yes_ask")[3] - ohlc.ohlc(c, "yes_bid")[3]) if cm is not None else None
        rec["snapshots"].append(dict(ts=ts, mid=smid, candle_mid=cm, spread=round(sp, 4) if sp is not None else None,
                                     candle_age_s=round(ts - c["end_period_ts"], 1) if c else None,
                                     gap=round(cm - smid, 4) if (cm is not None and smid is not None and sp <= MAX_SPREAD + 1e-9) else None))
    return rec


def targets(db, now, days, done):
    """Logged markets whose candle window is over, newest first: [(ticker, mtype, [(ts, mid)])]."""
    c = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = c.execute("select ticker,ts,mid,market_type from obs where ts is not null").fetchall()
    finally:
        c.close()
    by = {}
    for t, ts, mid, mt in rows:
        mtype = mt or ("rain" if str(t).startswith("KXRAIN") else "temp")
        by.setdefault(t, [mtype, []])[1].append((ts, mid))
    out = []
    for t, (mtype, snaps) in by.items():
        ds = day_start(t)
        if t in done or not ds or not (now - days * 86400 <= ds <= now - SETTLED_AFTER):
            continue
        out.append((ds, t, mtype, sorted(snaps)))
    return [(t, m, s) for _, t, m, s in sorted(out, reverse=True)]


def run(now=None, days=21, cap=60, db=None):
    now = now or time.time()
    if db is None:
        env = os.getenv("PAPER_DB", "paper.db")
        db = env if os.path.isabs(env) else os.path.join(ROOT, env)
    tries = {}
    done = set()
    for r in lines(AUDIT):   # done: a record with candles; or TRIES runs that failed or found none (review 2026-10-23)
        if not r.get("error") and r.get("candles"):
            done.add(r["ticker"])
        else:
            tries[r["ticker"]] = tries.get(r["ticker"], 0) + 1
    done |= {t for t, k in tries.items() if k >= TRIES}
    ready = targets(db, now, days, done)
    todo = ready[:cap]
    n = 0
    for t, mtype, snaps in todo:
        ds = day_start(t)
        try:
            cs = candles(t.split("-")[0], t, ds - BEFORE, ds + AFTER)
        except Exception as ex:   # recorded as an error and retried on the next run
            append(AUDIT, [dict(ticker=t, mtype=mtype, checked=round(now, 1), error=str(ex)[:200])]); continue
        append(AUDIT, [audit_market(t, mtype, cs, now, snaps)]); n += 1
    print("ohlc audit: %d market%s checked, %d failed (retried on up to %d runs), %d left for later runs" % (
        n, "" if n == 1 else "s", len(todo) - n, TRIES, len(ready) - len(todo)))
    return n


def summarize(recs):
    """Totals by market type: candles, anomaly counts and rates per 1,000 candles, staleness and snapshot agreement."""
    latest = {}
    for r in recs:   # the newest record per market wins (an error or empty row is replaced by a later good one)
        if r.get("error") and r["ticker"] in latest and not latest[r["ticker"]].get("error"):
            continue
        latest[r["ticker"]] = r
    good = [r for r in latest.values() if not r.get("error")]
    out = {}
    for mt in sorted({r["mtype"] for r in good}) + ["all"]:
        rs = [r for r in good if mt == "all" or r["mtype"] == mt]
        nc = sum(r["candles"] for r in rs)
        codes = {}
        for r in rs:
            for k, v in r["codes"].items():
                codes[k] = codes.get(k, 0) + v
        snaps = [s for r in rs for s in r.get("snapshots", [])]
        ages = sorted(s["candle_age_s"] for s in snaps if s.get("candle_age_s") is not None)
        gaps = [abs(s["gap"]) for s in snaps if s.get("gap") is not None]
        out[mt] = dict(markets=len(rs), candles=nc, codes=codes,
                       per_1000={k: round(v * 1000.0 / nc, 2) for k, v in codes.items()} if nc else {},
                       markets_with_issue=sum(any(k not in ohlc.INFO_CODES for k in r["codes"]) for r in rs),
                       no_candles=sum(r["candles"] == 0 for r in rs),
                       snapshots=len(snaps), no_candle_at_snapshot=sum(s.get("candle_age_s") is None for s in snaps),
                       age_median_s=statistics.median(ages) if ages else None,
                       age_p90_s=ages[min(len(ages) - 1, int(0.9 * len(ages)))] if ages else None,
                       age_over_1h=sum(a > 3600 for a in ages),
                       gap_median=round(statistics.median(gaps), 4) if gaps else None,
                       gap_over_5pts=sum(g > DISAGREE for g in gaps), gaps=len(gaps))
    errors = [r for r in latest.values() if r.get("error")]
    return out, errors


def report(now=None):
    now = now or time.time()
    recs = lines(AUDIT)
    S, errors = summarize(recs)
    os.makedirs(OUT, exist_ok=True)
    save(os.path.join(OUT, "ohlc_audit.json"), dict(made=clock.iso(now), zone=clock.ZONE_NOTE, by_type=S, errors=len(errors)))
    L = ["# Historical OHLC anomaly audit", "",
         "Made %s, %s. Descriptive only: no decision or score reads this." % (clock.label(now), clock.ZONE_NOTE), "",
         "One-minute Kalshi candles of markets the bot logged, checked after settlement. Codes are defined in tbcommon/ohlc.py.", ""]
    if not S:
        L.append("No market audited yet. `python research/ohlc_audit.py run` audits markets 30 hours after their day starts.")
    for mt, s in S.items():
        if mt == "all" and len(S) == 2:   # one type only: "all" repeats it
            continue
        L += ["## %s markets" % ("All" if mt == "all" else mt.capitalize()), "",
              "%d markets, %d candles, %d markets with a broken candle (JUMP, GAP and EMPTY_SIDE excluded), %d with no candles at all." % (
                  s["markets"], s["candles"], s["markets_with_issue"], s["no_candles"]), ""]
        if s["codes"]:
            L += ["| Code | Count | Per 1,000 candles |", "|---|---|---|"]
            L += ["| %s | %d | %s |" % (k, v, s["per_1000"].get(k, "")) for k, v in sorted(s["codes"].items(), key=lambda x: -x[1])]
            L.append("")
        if s["snapshots"]:
            L.append("At the %d minutes the bot logged these markets: the candle \"latest at or before\" was %s old at the median "
                     "and %s at the 90th percentile; %d were over an hour old and %d had no candle yet." % (
                         s["snapshots"], clock.human_age(s["age_median_s"]), clock.human_age(s["age_p90_s"]), s["age_over_1h"], s["no_candle_at_snapshot"]))
            if s["gaps"]:
                L.append("Candle mid vs the live order-book mid the bot read, where the candle's spread was %d cents or less: "
                         "median gap %.1f points; %d of %d over %d points." % (
                    round(MAX_SPREAD * 100), s["gap_median"] * 100, s["gap_over_5pts"], s["gaps"], round(DISAGREE * 100)))
            L.append("")
    if errors:
        L += ["%d market%s could not be fetched; retried on the next run." % (len(errors), "" if len(errors) == 1 else "s"), ""]
    L.append("Caveat: candles exist only for minutes when something changed, so an old candle is not by itself an error; "
             "it is the price history a backtest would have used.")
    with open(os.path.join(OUT, "ohlc_audit.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    return S


def main(a):
    def opt(k, d):
        return float(a[a.index(k) + 1]) if k in a and a.index(k) + 1 < len(a) else d
    if a[:1] == ["run"]:
        every = opt("--every", 0)
        st = load(os.path.join(DATA, "state.json"), {}) or {}
        if every and time.time() - (st.get("last_run") or 0) < every:
            print("ohlc audit: ran %s ago, next after %s" % (clock.human_age(time.time() - st["last_run"]), clock.human_age(every)))
            return 0
        save(os.path.join(DATA, "state.json"), dict(last_run=time.time()))   # --every holds even if this run fails
        run(days=opt("--days", 21), cap=int(opt("--max", 60)))
        report()
        return 0
    if a[:1] == ["report"]:
        report()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
