"""PLAN6: the Nov 11 report shown next to the gate (research only; follows research/PLAN6.md, written 2026-10-29 before the
test's last 12 market days).

Read-only:
- it opens the PC's paper.db and the cloud trial copy read-only (sqlite mode=ro);
- it makes no network call;
- it never computes or stores the gate's look; it only quotes the stored one;
- it writes only research/results/nov11.md and nov11.json.

The test's market days are settled when it runs, so running it again on the same files gives the same numbers.
  python research/nov11.py [--db PAPER_DB] [--trial TRIAL_DB [--trial-commit SHA]] [--out DIR]
Defaults: paper.db next to the code, no trial copy (secondary B then says so), research/results.
Exit 0: report written; 2: the look is not stored yet (only that is reported); 3: this copy's look is not stored, but a
finished report already exists and was kept. Python 3.8+, standard library only."""
import os, sys, json, sqlite3, argparse, hashlib
from datetime import datetime, date, timezone, timedelta
from urllib.request import pathname2url
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import gate   # the gate's own rules (margin, tcrit, clear, STOP_DATE), identical to strategy.py's frozen copy (tests/test_fix.py)
from tbcommon import clock

STOP = gate.STOP_DATE
RAIN_STRATEGY = "forecast_alpha.rain.v3"   # the audit ledger's id for v3 rain decisions (strategy.STRATEGY_RAIN)
CONTEXT = [   # PLAN6 section 5: quoted, never re-scored
    "Past-data test (research/PLAN.md, scored once on 2026-10-14, 1,711 KXRAIN markets Jul 15 to Oct 12): market Brier 0.0730,"
    " calibrated airport forecast 0.0740, 50/50 blend 0.0711 (not clear). Verdict: no edge demonstrated.",
    "Continuing research tests, each with its own pre-set end (not scored here): the airport-forecast limit-order forward test"
    " (futility look at 60 market days, verdict at 110) and PLAN5 test L (scored once from Nov 25).",
    "Expected precision (PLAN6, stated before the data): with 12 to 20 market days the interval was expected to be at least about"
    " +/-0.016 to +/-0.022 Brier, about a quarter of the market's own Brier score, so 'no clear difference' was the expected reading"
    " even for a forecast as good as the best seen in past data. The 50-trade check was out of reach from the start (about one trade"
    " per scanned night).",
]


def ro(path):
    """A read-only connection; a missing file is refused."""
    if not os.path.isfile(path):
        raise SystemExit("not found: %s" % path)
    ap = os.path.abspath(path)
    if ap.startswith("\\\\") and not ap.startswith("\\\\?\\"):
        raise SystemExit("network (UNC) paths are not supported: copy the file to a local folder first: %s" % path)
    return sqlite3.connect("file:%s?mode=ro" % pathname2url(os.path.abspath(path)), uri=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def mday(t):
    try:
        return datetime.strptime(t.split("-")[1], "%y%b%d").date()
    except (AttributeError, IndexError, ValueError):
        return None


def test_day(t):
    """A market of the test's own days (before the stop date), the gate's rule (strategy._day_before)."""
    d = mday(t)
    return d is not None and d < STOP


def day_of(t):
    return t.split("-")[1]


def utc(ts):
    return "n/a" if ts is None else datetime.fromtimestamp(ts, timezone.utc).strftime("%b %d %H:%M UTC")


def stored_look(c):
    try:
        row = c.execute("select ts,passed,detail from gate_look where stop_date=?", (str(STOP),)).fetchone()
    except sqlite3.OperationalError:   # no table: no look stored
        return None
    if not row:
        return None
    d = json.loads(row[2]); d.update(passed=bool(row[1]), ts=row[0])
    return d


def v3_rain(c):
    """(ticker, forecast, market mid, result, logged ts) of every v3 rain obs row of the test's days, resolved or not."""
    rows = c.execute("select ticker,fc,mid,result,ts from obs where version='v3' and market_type='rain'").fetchall()
    return [r for r in rows if test_day(r[0])]


def brier(rows, k):
    return sum(((r[3] == "yes") - r[k]) ** 2 for r in rows) / len(rows) if rows else None


def listing(rows, source=None):
    """Per market day: resolved and unresolved markets and the first log time (PLAN6 sections 2 and 3)."""
    out = {}
    for r in rows:
        d = out.setdefault(day_of(r[0]), dict(source=source, resolved=0, unresolved=0, first_log=None))
        d["resolved" if r[3] is not None else "unresolved"] += 1
        if r[4] is not None and (d["first_log"] is None or r[4] < d["first_log"]):
            d["first_log"] = r[4]
    return out


def summary(o):
    """PLAN6 sections 2 and 3: the gate's clear-margin statistic on resolved rows o, and its fixed reading."""
    mg = gate.margin([r[:4] for r in o])
    by = {}
    for r in o:
        by.setdefault(day_of(r[0]), []).append(((r[3] == "yes") - r[2]) ** 2)
    res = dict(markets=len(o), days=len(by), brier_fc=brier(o, 1), brier_mkt=brier(o, 2),
               mkt_day=(sum(sum(v) / len(v) for v in by.values()) / len(by)) if by else None)   # market Brier, days weighted equally
    if mg is None:
        res.update(reading="too few market days for a reading (5 needed)")
        return res
    mu, se, nd = mg; tc = gate.tcrit(nd)
    res.update(mean=mu, se=se, t=(mu / se) if se > 0 else None, tcrit=tc, low=mu - tc * se, high=mu + tc * se)
    if gate.clear(mg):
        res["reading"] = "the forecast was clearly more accurate than Kalshi's prices"
    elif mu > 0 and mu >= tc * se:
        res["reading"] = "Kalshi's prices were clearly more accurate than the forecast"
    else:
        res["reading"] = "no clear difference"
    return res


def plain_interval(s):
    """PLAN6 section 2: the interval in plain words, as a share of the market's Brier score averaged over market days (the same
    day weighting as the interval). Lower error is capped at 100% (a Brier score cannot go below 0). The wording follows the
    reading, so it can never contradict it."""
    if "low" not in s or not s.get("mkt_day"):
        return ""
    raw = lambda v: 100 * abs(v) / s["mkt_day"]
    low = lambda v: "%.0f%% lower" % min(100.0, raw(v))
    high = lambda v: "%.0f%% higher" % raw(v)
    side = lambda v: low(v) if v < 0 else high(v)
    lo, hi, r = s["low"], s["high"], s["reading"]
    if r.startswith("the forecast was clearly"):
        return "Its error, measured by the Brier score, was plausibly between %s and %s than Kalshi's prices." % (low(min(hi, 0.0)), low(lo))
    if r.startswith("Kalshi's prices were clearly"):
        return "Its error, measured by the Brier score, was plausibly between %s and %s than Kalshi's prices." % (high(max(lo, 0.0)), high(hi))
    wide = " (capped at 100%: the interval is too wide to mean much)" if lo < 0 and raw(lo) > 100 else ""
    return ("The data fit anything from %s to %s error than Kalshi's prices, measured by the Brier score%s; they do not show the"
            " two are equal, and they rule out only differences beyond that range." % (side(lo), side(hi), wide))


def model_versions(c):
    """{market day: set of model versions} of the audit ledger's v3 rain decisions made while the market was still open to
    the scan (every reason but MARKET_STARTED, which a later evening's scan records); {} when there is no ledger."""
    try:
        rows = c.execute("select ticker,model_version from decisions where strategy_id=? and reason!='MARKET_STARTED'",
                         (RAIN_STRATEGY,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for t, mv in rows:
        if test_day(t):
            out.setdefault(day_of(t), set()).add(str(mv))   # a missing version reads "None": never one the PC ran
    return out


def in_window(d, ts):
    """The evening scan window for market day d: from 00:50 (inclusive) to 05:00 UTC (exclusive) on d, 8:50 PM to 1 AM La Paz
    the evening before, as scan_window.py. Judged on the day's earliest logged row, i.e. when the scan began (PLAN6 section 3)."""
    start = datetime(d.year, d.month, d.day, 0, 50, tzinfo=timezone.utc).timestamp()
    return ts is not None and start <= ts < start + 4 * 3600 + 10 * 60


def with_cloud(pc, cloud, pc_models, cloud_models):
    """PLAN6 section 3. A day the PC logged (any v3 rain row) is the PC's alone. Any other test day is the cloud copy's alone,
    if its rain decisions all carry a model version the PC also ran and all its rows were logged inside the scan window;
    otherwise it is listed as not used. Returns (resolved rows, listing by day)."""
    pc_days = {day_of(r[0]) for r in pc}
    ran = set().union(*pc_models.values()) if pc_models else set()
    lst = listing(pc, "PC"); rows = [r for r in pc if r[3] is not None]
    by_day = {}
    for r in cloud:
        if day_of(r[0]) not in pc_days:
            by_day.setdefault(day_of(r[0]), []).append(r)
    for d, rs in by_day.items():
        e = listing(rs, "cloud")[d]; dd = mday("x-" + d); mv = cloud_models.get(d, set())
        why = None
        if not mv:
            why = "no rain decisions to check its model"
        elif not mv <= ran:
            why = "model %s not run by the PC" % ",".join(sorted(mv - ran))
        elif not in_window(dd, e["first_log"]):
            why = "its scan began outside the evening scan window"
        if why:
            e.update(source="cloud, not used (%s; not counted)" % why)
        else:
            rows += [r for r in rs if r[3] is not None]
        lst[d] = e
    return rows, dict(sorted(lst.items(), key=lambda kv: mday("x-" + kv[0])))


def veto_ts(c):
    """Start of the first scan whose recorded config contains VETO_MAX_GAP (PLAN6 section 4); None if there is none."""
    try:
        rows = c.execute("select started_ts,config from scans where kind='scan'").fetchall()
    except sqlite3.OperationalError:
        return None
    ts = [t for t, cfg in rows if cfg and "VETO_MAX_GAP" in cfg]
    return min(ts) if ts else None


def trade_group(tr):
    """PLAN6 section 4: count, wins, net paper P&L, contracts and total net per contract (no standard error)."""
    n = sum(x[3] for x in tr); net = sum(x[4] for x in tr)
    return dict(trades=len(tr), wins=sum(1 for x in tr if x[2] == x[1]), losses=sum(1 for x in tr if x[2] != x[1]),
                net=net, contracts=n, days=len({day_of(x[0]) for x in tr}), per_contract=(net / n) if n else None)


def trades(c):
    tr = [r for r in c.execute("select ticker,side,result,n,pnl,ts from trades where status='settled' and version='v3'"
                               " and ticker like 'KXRAIN%'").fetchall() if test_day(r[0])]
    v = veto_ts(c)
    before = [r for r in tr if v is None or r[5] is None or r[5] < v]; after = [r for r in tr if v is not None and r[5] is not None and r[5] >= v]
    return dict(veto_scan=v, before_veto=trade_group(before), after_veto=trade_group(after), total=trade_group(tr))


def failed_checks(lk):
    """The gate's checks (CLAUDE.md section 5) that the stored look did not meet, from its stored numbers."""
    mg = tuple(lk["margin"]) if lk.get("margin") else None
    out = []
    if (lk.get("markets") or 0) < 100: out.append("at least 100 resolved markets (%s)" % ("n/a" if lk.get("markets") is None else lk["markets"]))
    if lk.get("brier_fc") is None or lk.get("brier_mkt") is None or not lk["brier_fc"] < lk["brier_mkt"]:
        out.append("forecast Brier below market Brier")
    if not gate.clear(mg): out.append("a clear margin")
    if (lk.get("trades") or 0) < 50: out.append("at least 50 settled trades (%s)" % ("n/a" if lk.get("trades") is None else lk["trades"]))
    if not (lk.get("pnl") or 0) > 0: out.append("net P&L above zero (%s)" % money(lk.get("pnl")))
    return out


def consistency(a, lk):
    """PLAN6 section 2: A must match the stored look's margin; a mismatch is reported, never resolved silently."""
    m = lk.get("margin")
    if not m and "mean" not in a:
        return None
    if not m or "mean" not in a:
        return "A and the stored look disagree on whether there are 5 market days (stored margin %s)" % ("none" if not m else "present")
    if abs(m[0] - a["mean"]) > 1e-9 or abs(m[1] - a["se"]) > 1e-9 or int(m[2]) != a["days"]:
        return "A (mean %s, SE %.6f, %d days) differs from the stored look's margin (mean %s, SE %.6f, %d days)" % (
            f4(a["mean"]), a["se"], a["days"], f4(m[0]), m[1], int(m[2]))
    return None


def f4(x):
    return "n/a" if x is None else "%+.4f" % x


def money(x):
    return "n/a" if x is None else ("-$%.2f" % -x if x < 0 else "$%.2f" % x)


def build(db, trial=None, trial_commit=None):
    c = ro(db)
    try:
        lk = stored_look(c)
        if lk is None:
            return None, ["# Nov 11 report (research/PLAN6.md)", "",
                          "The gate's single look is not stored yet (before %s, or a test-day market or trade is still without a result)."
                          " Nothing else is shown until it is (PLAN6 section 1)." % STOP]
        pc = v3_rain(c); a = summary([r for r in pc if r[3] is not None]); a["listing"] = listing(pc, "PC")
        pc_models = model_versions(c); tr = trades(c)
    finally:
        c.close()
    b = dict(reading="not available (no trial copy given)", listing={})
    if trial:
        try:   # a missing, damaged or different trial copy loses only B, never the primary or A
            t = ro(trial)
            try: cloud = v3_rain(t); cloud_models = model_versions(t)
            finally: t.close()
            rows, lst = with_cloud(pc, cloud, pc_models, cloud_models)
            b = summary(rows); b.update(listing=lst, trial=os.path.basename(trial), trial_sha256=sha256(trial), trial_commit=trial_commit)
        except (SystemExit, Exception) as ex:   # anything wrong in the trial copy loses only B
            b = dict(reading="not available (the trial copy could not be read: %s)" % str(ex)[:200], listing={})
    R = dict(plan="research/PLAN6.md", made=clock.iso(), look=lk, failed=failed_checks(lk), A=a, B=b, C=tr, D=CONTEXT,
             mismatch=consistency(a, lk))
    return R, lines(R)


def stat_line(s):
    if "mean" not in s:
        return "%d resolved markets over %d market days: %s." % (s["markets"], s["days"], s["reading"])
    return ("%d resolved markets over %d market days. Brier (pooled, for reference): forecast %.4f, market %.4f. Forecast minus market,"
            " averaged within each market day: %s (SE %.4f, t %s; the gate's cutoff %.2f SE; interval %s to %s). Reading, from the day"
            " means: **%s**. %s" % (s["markets"], s["days"], s["brier_fc"], s["brier_mkt"], f4(s["mean"]), s["se"],
                                    "n/a" if s["t"] is None else "%+.2f" % s["t"], s["tcrit"], f4(s["low"]), f4(s["high"]),
                                    s["reading"], plain_interval(s)))


def day_lines(lst):
    return ["- %s: %s, %d resolved, %d unresolved, first logged %s" % (d, e["source"], e["resolved"], e["unresolved"], utc(e["first_log"]))
            for d, e in lst.items()]


def trade_line(name, g):
    if not g["trades"]:
        return "- %s: none." % name
    pc = "n/a" if g["per_contract"] is None else "%+.1fc" % (100 * g["per_contract"])
    return ("- %s: %d settled (%d won, %d lost) over %d market day%s, %d contracts; net paper P&L %s after approximate fees;"
            " paper P&L per contract %s (optimistic fills; not a test)." % (name, g["trades"], g["wins"], g["losses"], g["days"],
                                                                           "" if g["days"] == 1 else "s", g["contracts"], money(g["net"]), pc))


def money_line(ok):
    """PLAN6 section 1: what the stored look means for real money."""
    if ok:
        return ("The gate passed on paper only. Real money still needs your own typed unlock (.\\run live unlock), starts tiny and is"
                " capped at $25 at risk.")
    return ("The rules (CLAUDE.md section 11) say no real money after a failed look. live.py's unlock still leaves the decision to"
            " you: it says plainly that the gate did not pass, and asks for the typed phrase. v3 opens no new paper trades for market"
            " days from %s on, so live.py has nothing to copy." % STOP)


def lines(R):
    lk, a, b, tr = R["look"], R["A"], R["B"], R["C"]
    ok = lk["passed"]
    L = ["# Nov 11 report (research/PLAN6.md)", "", "Made %s. Research only: nothing here changes the gate's verdict." % R["made"], "",
         "## Summary", ""]
    L.append("1. **Gate (the single look, stored %s): %s.**%s" % (clock.label(lk["ts"]), "passed (paper only)" if ok else "not passed",
             "" if not R["failed"] else " Checks not met: %s." % "; ".join(R["failed"])))
    s2 = "2. On the core question (does the forecast beat Kalshi's prices?), over %d market days: %s." % (a["days"], a["reading"])
    if plain_interval(a):
        s2 += " " + plain_interval(a)
    if a["reading"].startswith("the forecast was clearly"):
        s2 += (" This covers only these market days, and a more accurate forecast is not the same as a profitable one: the bot trades"
               " few markets and pays the spread and fees.") + ("" if ok else " The gate was not passed, so the rules say no real money.")
    L.append(s2)
    if b.get("listing") and b["reading"] != a["reading"]:
        L.append("   Secondary (PC days plus cloud days the PC missed; does not change the gate), over %d market days: %s." % (b["days"], b["reading"]))
    L.append("3. %d settled paper trades: too few to conclude anything." % tr["total"]["trades"])
    L.append("4. " + money_line(ok))
    if R.get("mismatch"):
        L.append("5. CHECK: " + R["mismatch"] + ".")
    L += ["", "## 1. The gate's single look (primary, as stored)", ""]
    mg = lk.get("margin"); na = lambda k: "n/a" if lk.get(k) is None else lk[k]
    L.append("Passed: %s. Resolved markets %s; Brier forecast %s, market %s; margin %s; settled trades %s; net P&L %s; market days %s to %s."
             % ("yes" if ok else "no", na("markets"), "n/a" if lk.get("brier_fc") is None else "%.4f" % lk["brier_fc"],
                "n/a" if lk.get("brier_mkt") is None else "%.4f" % lk["brier_mkt"],
                "n/a (fewer than 5 market days)" if not mg else "%s per day over %d days (SE %.4f): %s" % (
                    f4(mg[0]), int(mg[2]), mg[1], "clear" if gate.clear(tuple(mg)) else "not clear"),
                na("trades"), money(lk.get("pnl")), na("first_day"), na("last_day")))
    L += ["", money_line(ok), "", "## 2. Secondary A: the core question on the PC's data", "", stat_line(a), ""] + day_lines(a["listing"])
    L += ["", "## 3. Secondary B: PC days plus cloud days the PC missed (does not change the gate)", ""]
    if b.get("listing"):
        L.append(stat_line(b)); L.append("")
        L += day_lines(b["listing"]); L.append("")
        L.append("Trial copy: %s, SHA-256 %s%s." % (b["trial"], b["trial_sha256"], ", commit %s" % b["trial_commit"] if b.get("trial_commit") else ""))
        L.append("Caveat: the cloud copy's evening scan can start later than the PC's, so its prices and forecasts can be a few hours newer;"
                 " a scan after 05:00 UTC skips the eastern markets (see the first-log times).")
        if b["reading"] != a["reading"]:
            L.append("A and B disagree; neither changes the primary.")
    else:
        L.append(b["reading"] + ".")
    v = tr.get("veto_scan")
    L += ["", "## 4. Descriptive C: the paper trades (too few for any conclusion)", "",
          trade_line("Before the veto (opened before %s)" % utc(v) if v else "All trades (no veto scan recorded)", tr["before_veto"]),
          trade_line("After the veto (opened from %s)" % utc(v) if v else "After the veto (no veto scan recorded)", tr["after_veto"]),
          trade_line("Total", tr["total"]), "", "## 5. Context D (quoted, not re-scored)", ""]
    L += ["- " + x for x in R["D"]]
    return L


def save(path, text):
    tmp = path + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN6 Nov 11 report (read-only)")
    ap.add_argument("--db", default=os.path.join(ROOT, "paper.db"))
    ap.add_argument("--trial", default=None)
    ap.add_argument("--trial-commit", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    a = ap.parse_args(argv)
    R, L = build(a.db, a.trial, a.trial_commit)
    os.makedirs(a.out, exist_ok=True)
    md, js = os.path.join(a.out, "nov11.md"), os.path.join(a.out, "nov11.json")
    if R is None:
        if os.path.exists(js):   # e.g. a retry on an older copy: a finished report is never replaced by "not stored yet"
            try:
                done = lines(json.load(open(js, encoding="utf-8")))
            except (ValueError, KeyError, TypeError) as ex:
                print("\n".join(L)); print("(an earlier nov11.json in %s could not be read (%s); nothing was changed)" % (a.out, ex)); return 2
            save(md, "\n".join(done) + "\n")   # rebuilt from the finished JSON, so the two always match
            print("\n".join(L)); print("(this copy's look is not stored, but a finished report already exists in %s; it was kept)" % a.out)
            return 3
        save(md, "\n".join(L) + "\n"); print("\n".join(L)); return 2
    save(js, json.dumps(R, indent=1, default=lambda x: sorted(x) if isinstance(x, set) else str(x)))   # the JSON first: its
    save(md, "\n".join(L) + "\n")                                                                     # .md always matches it
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
