"""PROBE22 (research/PLAN22.md section 7): what Deribit's hourly DVOL history looks like, before PLAN22 is frozen.
Counts, timestamps, ranges, SHA-256 hashes and the endpoint's field names only: no DVOL value is printed, saved or
logged, so the probe cannot steer the plan toward a result.

  (a) hourly candles (resolution 3600) per month per currency, by paging back from 2026-11-01 00:00 UTC;
  (b) whether a candle's timestamp marks the start or the end of its hour;
  (c) revision check: one fixed past week of each currency hashed now and compared with the hash stored by an earlier
      run at least 24 hours before ("same", "different" or "not yet");
  (d) the oldest hourly candle each currency returns, and the page size and continuation the endpoint uses.

PLAN22 section 1 forbids reading anything dated 2026-11-01 to 2026-12-31 (UTC), so every request ends before
2026-11-01 00:00 UTC and the probe stops, saving nothing, if a candle at or after it ever comes back. PLAN22's (b)
says "latest candles against the clock"; the latest candles are dated inside that forbidden period, so (b) is answered
instead from past data only: the hourly candles of 2026-10-15 are compared, in memory, with that day's one-minute
candles (an hour's high and low are the highest and lowest of its minutes), and only the verdict and match counts are
kept. If one-minute history does not reach back that far, (b) reads "undetermined".

Approved by the user 2026-11-26 20:20 La Paz ("Yes, approve Deribit"): www.deribit.com/api/v2/public, read-only, no
account, no key. GETs only, only to www.deribit.com, User-Agent tradebot-paper-research/1.0, at most one request a
second. Standard library only. Writes research/results/probe22.json and probe22.md; runs on GitHub's runner
(cloud/workflows/probe22.yml).
  python research/probe22.py"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")
OUT_JSON = os.path.join(OUT_DIR, "probe22.json")
OUT_MD = os.path.join(OUT_DIR, "probe22.md")

UA = "tradebot-paper-research/1.0"
HOST = "www.deribit.com"
PATH = "/api/v2/public/get_volatility_index_data"
CURRENCIES = ("BTC", "ETH")
HOUR_MS = 3600 * 1000
MIN_MS = 60 * 1000


def ms(y, mo, d, h=0):
    return int(datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp() * 1000)


CUTOFF_MS = ms(2026, 11, 1)            # nothing at or after this is requested or kept (PLAN22 section 1)
START_MS = ms(2019, 1, 1)              # before DVOL existed: the full history request starts here
REV_RANGE = (ms(2026, 10, 1), ms(2026, 10, 8))   # (c): one fixed past week, [start, end)
CONV_RANGE = (ms(2026, 10, 15, 4), ms(2026, 10, 15, 22))   # (b): minute and hour candles of this span
CONV_HOURS = (ms(2026, 10, 15, 6), ms(2026, 10, 15, 20))   # (b): hourly labels judged, [start, end)
REPORT_MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10")
MAX_PAGES = 2000
MIN_GAP_S = 1.0                         # at most one request a second
RETRIES = 3
REVISION_GAP_S = 24 * 3600
COMPLETE_STOPS = ("continuation null", "continuation before the request's start")

MAX_BODY = 20000000                     # a larger response is refused
RETRY_AFTER_CAP_S = 60.0
BUDGET_S = 75 * 60                      # whole-run budget: past it, every request ends with BudgetOut
REV_N = 7 * 24                          # candles in the fixed revision week

# Replaceable in tests: TRANSPORT(url, headers, timeout) -> (status, headers dict, body bytes); CLOCK(); SLEEP(s).
CLOCK = time.time
SLEEP = time.sleep
_last = [None]
RUN_START = [None]


class ProbeStop(Exception):
    """The probe stops and saves nothing (a forbidden date came back, a redirect, a malformed candle, the host
    check failed). Its messages are fixed texts: they never carry a value from a response."""


class BudgetOut(RuntimeError):
    """The whole-run budget is spent: the step that needed the request is recorded as an error, the run ends cleanly."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # never follow: the 3xx comes back as an HTTPError and is refused below


def _read(r):
    body = r.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ProbeStop("response over %d bytes refused" % MAX_BODY)
    return body


def _urllib_transport(url, headers, timeout):
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as r:
            if r.geturl() != url:
                raise ProbeStop("redirect refused")
            return r.status, dict((k.lower(), v) for k, v in r.headers.items()), _read(r)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise ProbeStop("redirect refused (HTTP %d)" % e.code)
        hdrs = dict((k.lower(), v) for k, v in (e.headers.items() if e.headers else []))
        return e.code, hdrs, _read(e)


TRANSPORT = _urllib_transport


def check_url(url):
    """Only https GETs to www.deribit.com's public volatility index endpoint, never past the cutoff."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname != HOST or u.port not in (None, 443) or u.username or u.password:
        raise ProbeStop("host check: only https://%s is allowed" % HOST)
    if u.path != PATH:
        raise ProbeStop("host check: only %s is allowed" % PATH)
    q = dict(urllib.parse.parse_qsl(u.query))
    if set(q) != {"currency", "start_timestamp", "end_timestamp", "resolution"}:
        raise ProbeStop("host check: unexpected query fields")
    if int(q["end_timestamp"]) >= CUTOFF_MS or int(q["start_timestamp"]) >= CUTOFF_MS:
        raise ProbeStop("request would reach 2026-11-01 or later (PLAN22 section 1)")
    return url


def _retry_after(headers):
    try:
        v = float((headers or {}).get("retry-after"))
    except (TypeError, ValueError):
        return None
    return min(max(v, 0.0), RETRY_AFTER_CAP_S)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return (isinstance(x, (int, float))) and not isinstance(x, bool)


def get(currency, start, end, resolution):
    """One GET, rate-limited (one a second, Retry-After honoured up to 60 s), retried on 429, 5xx, Deribit's
    error 10028 (too many requests, any HTTP status) and network errors; no wait after the last try. Returns the
    decoded JSON object. Error texts are fixed and carry no value from the response."""
    url = "https://%s%s?%s" % (HOST, PATH, urllib.parse.urlencode(
        [("currency", currency), ("start_timestamp", str(int(start))), ("end_timestamp", str(int(end))),
         ("resolution", resolution)]))
    check_url(url)
    err = None
    for attempt in range(RETRIES + 1):
        if RUN_START[0] is not None and CLOCK() - RUN_START[0] > BUDGET_S:
            raise BudgetOut("run budget of %d minutes reached" % (BUDGET_S // 60))
        if _last[0] is not None:
            wait = MIN_GAP_S - (CLOCK() - _last[0])
            if wait > 0:
                SLEEP(wait)
        _last[0] = CLOCK()
        last_try = attempt == RETRIES
        try:
            status, headers, body = TRANSPORT(url, {"User-Agent": UA, "Accept": "application/json"}, 30)
        except ProbeStop:
            raise
        except Exception as e:   # noqa: BLE001  (network error: retried)
            err = "network %s" % type(e).__name__
            if not last_try:
                SLEEP(2 * (attempt + 1))
            continue
        try:
            j = json.loads(body.decode("utf-8"))
            if not isinstance(j, dict):
                raise ValueError
        except Exception:   # noqa: BLE001
            j = None
        e = (j or {}).get("error")
        code = e.get("code") if isinstance(e, dict) else None
        if status == 429 or status >= 500 or code == 10028:
            err = "HTTP %d%s" % (status, ", error code 10028" if code == 10028 else "")
            if not last_try:
                ra = _retry_after(headers)
                SLEEP(ra if ra is not None else 5 * (attempt + 1))
            continue
        if j is None:
            raise RuntimeError("HTTP %d, body is not a JSON object" % status)
        if status != 200 or e is not None:
            raise RuntimeError("HTTP %d, error code %s" % (status, code if _is_int(code) else "?"))
        return j
    raise RuntimeError("gave up after %d tries (%s)" % (RETRIES + 1, err))


def fields_of(j):
    """The endpoint's field names only (never their values)."""
    res = j.get("result") if isinstance(j.get("result"), dict) else {}
    data = res.get("data") if isinstance(res.get("data"), list) else []
    return dict(top=sorted(str(k) for k in j), result=sorted(str(k) for k in res),
                candle_lengths=sorted({len(c) for c in data if isinstance(c, list)}))


def check_candle(c, start, end):
    """Strict: [int t, four numbers], t on a whole minute, inside [start - 1 hour, end], before the cutoff."""
    if not (isinstance(c, list) and len(c) == 5 and _is_int(c[0])):
        raise ProbeStop("malformed candle; nothing saved")
    t = c[0]
    if t >= CUTOFF_MS:   # never kept, never counted: stop and save nothing
        raise ProbeStop("a candle at or after 2026-11-01 came back (PLAN22 section 1); nothing saved")
    if t % MIN_MS or not (start - HOUR_MS <= t <= end) or not all(_is_num(x) for x in c[1:5]):
        raise ProbeStop("malformed candle (time off the minute, outside the request, or not numbers); nothing saved")
    return t


def page(currency, start, end, resolution, keep_values=False):
    """Pages back with `continuation` as the next end_timestamp until it is null or stops moving back.
    Returns (candles, info). candles holds timestamps only unless keep_values (then whole candles, kept in memory by
    the caller only, never saved). info: page sizes, continuation direction, why paging stopped, field names."""
    out, sizes, fields, direction, why = {}, [], None, None, None
    cur_end = end
    for _ in range(MAX_PAGES):
        j = get(currency, start, cur_end, resolution)
        try:
            res = j["result"]
            data = res["data"]
            cont = res.get("continuation")
            if not isinstance(data, list) or not (cont is None or _is_int(cont)):
                raise ValueError
        except Exception:   # noqa: BLE001  (fixed text: nothing from the response is passed on)
            raise RuntimeError("malformed response (result, data or continuation)")
        if fields is None:
            fields = fields_of(j)
        for c in data:
            t = check_candle(c, start, cur_end)
            out[t] = c if keep_values else None
        sizes.append(len(data))
        if cont is None:
            why = "continuation null"
            break
        if cont >= cur_end:
            direction = direction or "later"
            why = "continuation did not move back"
            break
        direction = "earlier"
        if not data:
            why = "empty page"
            break
        if cont < start:
            why = "continuation before the request's start"
            break
        cur_end = cont
    else:
        why = "page limit %d reached" % MAX_PAGES
    info = dict(pages=len(sizes), page_sizes=dict(first=sizes[0] if sizes else None, max=max(sizes) if sizes else None,
                                                  min=min(sizes) if sizes else None),
                continuation=direction, stopped=why, fields=fields)
    return out, info


def iso(t_ms):
    return datetime.fromtimestamp(t_ms / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_of(t_ms):
    return datetime.fromtimestamp(t_ms / 1000.0, timezone.utc).strftime("%Y-%m")


def month_hours(m):
    y, mo = int(m[:4]), int(m[5:])
    a = ms(y, mo, 1)
    b = ms(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
    return (min(b, CUTOFF_MS) - a) // HOUR_MS


def history(currency):
    """(a) and (d): timestamps only."""
    cand, info = page(currency, START_MS, CUTOFF_MS - 1, "3600")
    ts = sorted(cand)
    by_month = {}
    for t in ts:
        by_month[month_of(t)] = by_month.get(month_of(t), 0) + 1
    off_hour = sum(1 for t in ts if t % HOUR_MS)
    months = {}
    for m in sorted(by_month):
        months[m] = dict(candles=by_month[m], hours=month_hours(m))
    rep = {}
    for m in REPORT_MONTHS:
        n = by_month.get(m, 0)
        rep[m] = dict(candles=n, hours=month_hours(m), coverage=round(n / float(month_hours(m)), 4))
    gaps = sum(1 for a, b in zip(ts, ts[1:]) if b - a > HOUR_MS)
    return dict(candles=len(ts), oldest=iso(ts[0]) if ts else None, newest=iso(ts[-1]) if ts else None,
                oldest_ms=ts[0] if ts else None, not_on_the_hour=off_hour, gaps_over_an_hour=gaps,
                reached_request_start=bool(ts) and ts[0] - START_MS < HOUR_MS,
                months=months, report_months=rep, paging=info)


def revision(currency):
    """(c): SHA-256 of the fixed week's candles, canonical JSON, sorted by timestamp. Values are hashed, never kept."""
    a, b = REV_RANGE
    cand, info = page(currency, a, b - 1, "3600", keep_values=True)
    rows = [[int(cand[t][0])] + [float(x) for x in cand[t][1:5]] for t in sorted(cand) if a <= t < b]
    h = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()
    n = len(rows)
    del rows, cand
    return dict(range=[iso(a), iso(b)], candles=n, sha256=h, pages=info["pages"])


def _agg(minutes, lo, hi):
    sel = [minutes[t] for t in sorted(minutes) if lo <= t < hi]
    if len(sel) < 55:   # too few minutes in the hour to judge
        return None
    return max(float(c[2]) for c in sel), min(float(c[3]) for c in sel)


def _same(x, y):
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def convention(currency):
    """(b): which hour a timestamp labels, from past data only. Hour T (start convention) covers [T, T+1h); end
    convention covers [T-1h, T). Minute labels may also mark start or end, so four minute offsets are tried. Only the
    verdict and match counts leave this function."""
    a, b = CONV_RANGE
    try:
        minutes, minfo = page(currency, a, b - 1, "60", keep_values=True)
        hours, _ = page(currency, a, b - 1, "3600", keep_values=True)
    except RuntimeError as e:
        return dict(verdict="undetermined", reason="request failed: %s" % str(e)[:160])
    offsets = {"start/minute start": 0, "start/minute end": MIN_MS,
               "end/minute start": -HOUR_MS, "end/minute end": -HOUR_MS + MIN_MS}
    lo_h, hi_h = CONV_HOURS
    labels = [t for t in sorted(hours) if lo_h <= t < hi_h]
    matches = dict((k, 0) for k in offsets)
    judged = 0
    for t in labels:
        c = hours[t]
        aggs = dict((k, _agg(minutes, t + o, t + o + HOUR_MS)) for k, o in offsets.items())
        if any(v is None for v in aggs.values()):
            continue
        judged += 1
        for k, v in aggs.items():
            if _same(v[0], float(c[2])) and _same(v[1], float(c[3])):
                matches[k] += 1
    nmin = len(minutes)
    mold = iso(min(minutes)) if minutes else None   # a timestamp only
    del minutes, hours
    s = matches["start/minute start"] + matches["start/minute end"]
    e = matches["end/minute start"] + matches["end/minute end"]
    best = max(matches.values()) if matches else 0
    if judged < 6:
        verdict = "undetermined"
    elif best >= 0.8 * judged and s > 0 and e == 0:
        verdict = "start"
    elif best >= 0.8 * judged and e > 0 and s == 0:
        verdict = "end"
    else:
        verdict = "undetermined"
    return dict(verdict=verdict, hours_judged=judged, hourly_labels=len(labels), minute_candles=nmin, minute_oldest=mold,
                matches=matches, minute_pages=minfo["pages"],
                rule="an hour's high and low equal the highest and lowest of the 1-minute candles it covers")


def load_previous():
    """The earlier runs' record (hashes, oldest candles). A damaged file stops the probe: the first day's hash must
    never be lost."""
    if not os.path.exists(OUT_JSON):
        return []
    bad = ProbeStop("research/results/probe22.json is damaged: not overwritten; restore it from git first")
    try:
        with open(OUT_JSON, encoding="utf-8") as f:
            j = json.load(f)
    except Exception:   # noqa: BLE001
        raise bad
    if not isinstance(j, dict) or not isinstance(j.get("runs"), list):
        raise bad
    for r in j["runs"]:
        if not isinstance(r, dict) or not isinstance(r.get("run_utc"), str) or not _is_num(r.get("run_s")):
            raise bad
        if not isinstance(r.get("revision"), dict) or not isinstance(r.get("oldest_ms", {}), dict):
            raise bad
        for c in CURRENCIES:
            v = r["revision"].get(c)
            if v is not None and not isinstance(v, dict):
                raise bad
            if isinstance(v, dict) and not (v.get("sha256") is None or isinstance(v.get("sha256"), str)):
                raise bad
            o = r.get("oldest_ms", {}).get(c)
            if o is not None and not _is_int(o):
                raise bad
    return j["runs"]


def compare(runs, now_s, cur):
    """(c) verdict per currency: against every earlier run at least 24 hours before this one."""
    out = {}
    for c in CURRENCIES:
        old = [r for r in runs if now_s - r["run_s"] >= REVISION_GAP_S and (r["revision"].get(c) or {}).get("sha256")]
        n = cur.get(c, {}).get("candles")
        changed = [r["run_utc"] for r in old if r["revision"][c].get("candles") != n]   # reported apart from the hash
        full = [r for r in old if r["revision"][c].get("candles") == REV_N]
        if not cur.get(c, {}).get("sha256"):
            out[c] = dict(verdict="not checked (no hash this run)")
        elif n != REV_N:
            out[c] = dict(verdict="not checked", note="this run has %s of %d candles" % (n, REV_N), count_changed=changed)
        elif not old:
            first = runs[0]["run_utc"] if runs else None
            out[c] = dict(verdict="not yet", note="needs a run 24+ hours after %s" % (first or "this one"))
        elif not full:
            out[c] = dict(verdict="not checked", note="no earlier run 24+ hours before had %d candles" % REV_N,
                          count_changed=changed)
        else:
            diff = [r["run_utc"] for r in full if r["revision"][c]["sha256"] != cur[c]["sha256"]]
            out[c] = dict(verdict="different" if diff else "same", compared_with=[r["run_utc"] for r in full],
                          differs_from=diff, count_changed=changed)
    return out


def rolling(runs, now_s, hist):
    out = {}
    for c in CURRENCIES:
        cur = (hist.get(c) or {}).get("oldest_ms")
        old = [r["oldest_ms"][c] for r in runs if now_s - r["run_s"] >= REVISION_GAP_S and (r.get("oldest_ms") or {}).get(c)]
        if cur is None:
            out[c] = "unknown"
        elif not old:
            out[c] = "not yet (needs a run 24+ hours later)"
        else:
            out[c] = "oldest candle moved later: history is rolling" if cur > min(old) else "oldest candle unchanged"
    return out


def write_md(res):
    L = ["# PROBE22: Deribit hourly DVOL history (counts only)", "",
         "Run %s. research/PLAN22.md section 7. No DVOL value is shown or saved: only counts, timestamps, ranges, "
         "SHA-256 hashes and field names. Nothing dated 2026-11-01 or later was requested." % res["run_utc"], ""]
    for c in CURRENCIES:
        h = res["history"].get(c) or {}
        L.append("## %s" % c)
        if "error" in h:
            L += ["- history: error %s" % h["error"], ""]
        else:
            p = h["paging"]
            if p["stopped"] not in COMPLETE_STOPS:
                L.append("- **incomplete history**: paging stopped (%s), so the oldest candle below is not the oldest" % p["stopped"])
            L += ["- (d) oldest hourly candle: %s; newest before the cutoff: %s; %d candles in all; %s" % (
                      h["oldest"], h["newest"], h["candles"],
                      "reached the request's start (2019-01-01): history may go back further" if h["reached_request_start"] else "stops before the request's start"),
                  "- paging: %d pages, page size first %s / largest %s / smallest %s; continuation moves %s; stopped: %s" % (
                      p["pages"], p["page_sizes"]["first"], p["page_sizes"]["max"], p["page_sizes"]["min"],
                      p["continuation"], p["stopped"]),
                  "- candles not on the hour: %d; gaps over an hour: %d" % (h["not_on_the_hour"], h["gaps_over_an_hour"]),
                  "", "| month | candles | hours | coverage |", "|---|---|---|---|"]
            for m, r in sorted(h["report_months"].items()):
                L.append("| %s | %d | %d | %.1f%% |" % (m, r["candles"], r["hours"], 100 * r["coverage"]))
            L.append("")
        cv = res["convention"].get(c) or {}
        L.append("- (b) timestamp marks the **%s** of the hour (%s)" % (cv.get("verdict"), cv.get("reason") or
                 "%s of %s hours judged; matches %s" % (cv.get("hours_judged"), cv.get("hourly_labels"), cv.get("matches"))))
        rv = res["revision"].get(c) or {}
        cmp_ = res["revision_check"].get(c) or {}
        L.append("- (c) revision week %s: %s candles, SHA-256 %s; against earlier runs: **%s**%s" % (
            " to ".join(rv.get("range") or []), rv.get("candles"), rv.get("sha256") or rv.get("error"),
            cmp_.get("verdict"), (" (%s)" % cmp_["note"]) if cmp_.get("note") else ""))
        if cmp_.get("count_changed"):
            L.append("- (c) candle count differs from earlier runs: %s" % ", ".join(cmp_["count_changed"]))
        if cv.get("minute_oldest"):
            L.append("- oldest 1-minute candle in the (b) span: %s (%s minute candles)" % (cv["minute_oldest"], cv.get("minute_candles")))
        L += ["- history rolling? %s" % res["rolling"].get(c), ""]
    L += ["## Fields", "", "Endpoint fields seen: %s" % json.dumps(res["fields"], sort_keys=True), "",
          "## For the plan (section 7)",
          "A live DVOL recorder is needed for stage 2 if history is rolling and would not reach back to 2027-01-01 when "
          "read on 2027-03-02 (60 days). If the revision check reads \"different\", the plan is amended before the "
          "freeze, or abandoned. The plan records the decision before the freeze.", ""]
    return "\n".join(L)


def atomic(path, text):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def main():
    runs = load_previous()
    now_s = CLOCK()
    RUN_START[0] = now_s
    run_utc = datetime.fromtimestamp(now_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist, conv, rev, fields = {}, {}, {}, None
    for c in CURRENCIES:
        try:
            hist[c] = history(c)
            fields = fields or hist[c]["paging"]["fields"]
        except RuntimeError as e:
            hist[c] = dict(error=str(e)[:200])
        try:
            rev[c] = revision(c)
        except RuntimeError as e:
            rev[c] = dict(error=str(e)[:200])
        conv[c] = convention(c)
        print("probed", c)
    res = dict(probe="PROBE22", run_utc=run_utc, endpoint="https://%s%s" % (HOST, PATH), resolution="3600",
               cutoff=iso(CUTOFF_MS), note="counts, timestamps, ranges, hashes and field names only; no DVOL value",
               history=hist, convention=conv, revision=rev, fields=fields,
               revision_check=compare(runs, now_s, rev), rolling=rolling(runs, now_s, hist))
    this = dict(run_utc=run_utc, run_s=now_s,
                revision=dict((c, dict(sha256=rev[c].get("sha256"), candles=rev[c].get("candles"))) for c in CURRENCIES),
                oldest_ms=dict((c, (hist.get(c) or {}).get("oldest_ms")) for c in CURRENCIES))
    res["runs"] = runs + [this]
    os.makedirs(OUT_DIR, exist_ok=True)
    atomic(OUT_JSON, json.dumps(res, indent=1, sort_keys=True))
    atomic(OUT_MD, write_md(res))
    for c in CURRENCIES:
        print("%s: oldest %s; convention %s; revision %s" % (
            c, (hist.get(c) or {}).get("oldest"), conv[c].get("verdict"), res["revision_check"][c]["verdict"]))
    print("saved", OUT_JSON, "and", OUT_MD)
    return 0


def cli():
    """No traceback ever: a ProbeStop prints its fixed text, anything else only its type name."""
    try:
        rc = main()
    except ProbeStop as e:
        print("PROBE22 stopped: %s" % e)
        rc = 2
    except Exception as e:   # noqa: BLE001
        print("PROBE22 failed: %s" % type(e).__name__)
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    cli()
