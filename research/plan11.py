"""PLAN11 (research/PLAN11.md, frozen 2026-11-12, SHA-256 in CHANGELOG.md r83): radar and the airport rain gauge during
the market day, against Kalshi's price at that moment. A replay on every settled KXRAIN market with market day
2026-07-15..2026-11-10. Research only: never part of the gate, never connected to live.py, places nothing, never
opens paper.db or live.db. Where this code and the plan differ, the plan wins (plan section 8).

Stages (each refuses to run out of turn; the GitHub workflow cloud/workflows/plan11.yml adds once-only guards by
commit history):
- freeze    once: identity record research/results/plan11_identity.json (SHA-256 of PLAN11.md, this file,
            research/plan15.py (shared helpers), v3's rain table weather.RAIN, and PLAN7's pinned statistics functions
            through PLAN15). Every later stage checks it.
- probe     once, before any bulk download: reads the archive's world file (.wld) for one stamp and compares it with
            GRID below (recorded here before the first frame); then one frame: its size must be 12200 x 5400 and its
            palette length PALETTE_LEN. A difference stops the plan until an amendment (plan section 2).
            research/results/plan11_probe.json.
- markets   once: every settled KXRAIN market (Kalshi's archive and live listing), one per station and day (highest
            volume), stations from v3's rain table by CLI code (PLAN10's rule, KPBI counted as KDJT), the market's own
            day start (close_time - 24 h) compared with research/fetch.py's standard-time table (mismatches counted).
            research/data/plan11/markets.json.gz; prints counts only, never an outcome.
- download [--budget-minutes N] [--only candles|gauge|radar]: resumable, budgeted.
            candles: Kalshi's public one-minute candles (yes bid/ask closes) from the day start to its end, one request
                     per market, research/fetch.py's endpoints; day files research/data/plan11/candles/YYYY-MM-DD.json.gz.
            gauge:   IEM's METAR archive (asos.py, raw report text), routine and special reports requested separately,
                     per station and month: research/data/plan11/metar/STATION_YYYYMM_{routine,special}.json.gz.
            radar:   IEM's N0Q national mosaic, one whole frame per needed stamp (t - 10 and t - 40 minutes of every
                     decision time), decoded in memory (Pillow, numpy; runner only), reduced at once to per-station
                     readings; the frame itself is never stored. research/data/plan11/radar/YYYY-MM-DD.json.gz.
- signals   once, after every download is complete: the three rules on every market (no outcome is read or
            printed); research/results/plan11_signals.json.
- score     once: plan section 5; research/results/plan11_result.md, then plan11_result.json; copied off the folder
            when the off-folder location exists.
- status    counts only.

Network: Kalshi's public API (GETs) and mesonet.agron.iastate.edu (archive files and asos.py), through PLAN15's urllib
client (tbcommon's JsonClient: retries, Retry-After, rate limit, User-Agent tradebot-paper-research/1.0). IEM at most one
request a second (plan section 9).

Readings of the plan's text (stated, not tuned; listed for the code review):
- Pixel centres: the .wld's C and F are the centre of the upper-left pixel (the world-file standard); lon = C + A x col,
  lat = F + E x row. Great-circle (haversine) distance on a sphere of 6,371.0 km.
- "20 dBZ or more" is palette index >= 105 and "25 dBZ or more" index >= 115 (index i = -32.5 + 0.5 i dBZ).
- The price: the candle ending exactly at t + 1 min (included); if there is none, the last candle ending from t - 4 min
  to t (both included), i.e. no more than 5 minutes before t + 1 min, never one ending after t + 1 min. That one
  candle must show 0 < bid < ask < 1.00 (its yes bid and ask closes), or there is no trade at t. A decision time whose
  other conditions hold but has no price is counted and the rule moves on to the next decision time (the price and its
  cap are part of the rule's conditions); the cap is "ask <= cap".
- Gauge: the "first routine report after the day start" is the first routine report with observation time strictly
  after the day start; it and everything before it are ignored; with no routine report in the day, every report is
  ignored. A COR report is dropped; of two non-COR reports of the same type and time, the first in the archive stands.
  Rain known at t: a counted report with valid <= t - 10 min whose own Pxxxx group is 1 or more (hundredths).
- R and P need the gauge condition "not yet met": a market whose gauge reports were lost cannot fire R or P (unknown).
- A market "loses" a source (the 10% rule): radar, read as "t10" (the user's choice of 2026-11-26, made before any
  download): only when no decision time of the market has a usable t - 10 frame (a frame is unusable when it is
  missing: 404, wrong size, wrong palette, or failed in 3 runs). The stricter reading ("strict": any needed frame
  missing) is still counted and shown, as a descriptive figure only (RADAR_LOSS_READING); gauge, if its station-month download failed in 3 runs or the day holds no routine report;
  candles, if its candle request failed in 3 runs or the day has no candle.
- METAR probe: before the bulk download, one station-month (PROBE_METAR) of each report kind must be non-empty, the
  routine reports must sit at minutes :51-:56 (at least PROBE_ROUTINE_SHARE of them) and the specials must not
  (under PROBE_SPECIAL_SHARE of them at :51-:56); otherwise the download refuses.
- West Palm Beach: METAR is fetched for both DJT and PBI in every month and merged in time order with exact duplicate
  reports (same time and text) removed; the codes that returned reports are recorded. Same-time reports are then
  handled by the gauge rule above (the current code's first).
- Once-only: signals and score also refuse when `git log --all` shows their output file was ever committed; without
  git they refuse ("run through the workflow").
- Holm: rules that are not testable keep their place in the family (3 levels) and are ordered last.
- The win-rate bound: one-sided Clopper-Pearson lower bound at the rule's Holm level, from the exact binomial tail.

  python research/plan11.py freeze|probe|markets|signals|score|status
  python research/plan11.py download [--budget-minutes N] [--only candles|gauge|radar]
Python 3.8+. Standard library; Pillow and numpy only for the radar frames (imported inside those functions)."""
import argparse
import ast
import calendar
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import plan15 as P   # noqa: E402  (frozen shared helpers: hashes, gzip JSON, ISO times, the urllib client, PLAN7's stats)
from tbcommon import jsonio   # noqa: E402
from tbcommon.ohlc import field as ohlc_field   # noqa: E402

PLAN = "research/PLAN11.md"
PLAN_SHA256 = "244f408a67232fd78f01aa759e9ccc7ced7e986fa6ef79c0618b165a04dbe3f6"   # CHANGELOG.md r83 (frozen text)
CODE_FILES = ("research/plan11.py", "research/plan15.py")
SERIES = "KXRAIN"
FIRST_DAY, LAST_DAY = date(2026, 7, 15), date(2026, 11, 10)   # market days (plan section 2)

# ---- section 3: decision times and delays ----
STEP = 30 * 60                 # decision times at :00 and :30 UTC
FIRST_AFTER = 30 * 60          # from 30 minutes after the day starts
LAST_BEFORE = 60 * 60          # until 60 minutes before it ends
LAG_NOW, LAG_BEFORE = 10 * 60, 40 * 60   # radar frames stamped exactly t - 10 and t - 40 minutes
GAUGE_LAG = 10 * 60            # gauge reports observed at or before t - 10 minutes
FILL_AFTER = 60                # the candle ending exactly at t + 1 minute ...
FILL_BACK = 5                  # ... else the last one ending no more than 5 minutes before that

# ---- section 4: the three rules ----
RULES = ("G", "R", "P")
CAPS = {"G": 0.95, "R": 0.90, "P": 0.85}
GAUGE_MIN = 1                  # hundredths of an inch: 0.01 inch or more (P0000 is a trace and never counts)
R_KM = 10.0
MIN_PIXELS = 4
DBZ_R, DBZ_P = 20.0, 25.0
P_SEARCH_KM, P_NEAR_KM, P_CLOSE_KM = 150.0, 75.0, 10.0
FEE_RATE = 0.07

# ---- section 2: the radar grid, recorded before the first frame (checked by the probe stage) ----
GRID = dict(width=12200, height=5400, A=0.005, D=0.0, B=0.0, E=-0.005, C=-126.0, F=50.0)
PALETTE_LEN = 256              # IEM's N0Q colour table (index 0 = no data, 1..255 = -32 dBZ upward in 0.5 dBZ steps)
EARTH_KM = 6371.0
PROBE_STAMP = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
PROBE_METAR = ("KNYC", "202607")    # the METAR probe's station-month
ROUTINE_MINUTES = range(51, 57)     # routine (hourly) reports are made at :51-:56
PROBE_ROUTINE_SHARE = 0.90          # at least this share of routine reports at :51-:56
PROBE_SPECIAL_SHARE = 0.50          # specials: under this share at :51-:56
RADAR_LOSS_READINGS = ("strict", "t10")
RADAR_LOSS_READING = "t10"          # the user's choice, 2026-11-26, before any download ("strict" is descriptive only)

# ---- section 5: scoring ----
FAMILY = 0.025
HOLM_LEVELS = tuple(FAMILY / (len(RULES) - i) for i in range(len(RULES)))   # 0.833%, 1.25%, 2.5%
T_FLOOR = 2.0
BOOT_BLOCK, BOOT_DRAWS, BOOT_SEED = 7, 20000, 11
MIN_SIGNALS, MIN_SIGNAL_DAYS = 30, 15
MAX_LOST = 0.10
PRICE_BANDS = (("under 50c", 0.0, 0.50), ("50-79c", 0.50, 0.80), ("80-89c", 0.80, 0.90), ("90c and up", 0.90, 1.01))
VERDICT_LEAD = "lead on past data: justifies a forward paper test"
VERDICT_NONE = "no lag shown"
NOT_TESTABLE = "not testable"

# ---- network ----
IEM = "https://mesonet.agron.iastate.edu"
RADAR_FMT = "/archive/data/%Y/%m/%d/GIS/uscomp/n0q_%Y%m%d%H%M"
IEM_GAP = 1.0                  # at most one request a second (plan section 9)
KALSHI_LIMIT = 1000
TRIES = 3                      # runs an item may fail before it is recorded missing
MAX_FRAME_BYTES = 30 * 1024 * 1024
RETRY_AFTER_CAP = 300.0        # seconds: a longer Retry-After is cut to this
GUARDED = {"signals": ("research/results/plan11_signals.json", "research/results/plan11_result.json",
                       "research/results/plan11_result.md"),
           "score": ("research/results/plan11_result.json", "research/results/plan11_result.md")}
ALIASES = {"KDJT": ("KPBI",)}  # PLAN10's rule (stations as in PLAN10): West Palm Beach re-coded PBI -> DJT in July 2026
# research/fetch.py's TZ (local standard time, hours behind UTC), copied because fetch.py needs `requests`, which is
# not installed on the runner; tests/test_plan11.py checks the copy against fetch.py.
FETCH_TZ = {**{s: 5 for s in "ATL BOS BWI CLT CMH CVG DCA DTW EWR IAD IND JAX JFK LGA LEX MCO MIA ORF PHL PIT PVD RDU RIC SDF TPA TTN CLE BDL BUF ALB NYC DJT".split()},
            **{s: 6 for s in "AUS BNA CLL DAL DFW HOU IAH MCI MDW MEM MKE MSP MSY OKC ORD SAT SGF STL TUL OMA ICT".split()},
            **{s: 7 for s in "ABQ DEN PHX SLC TUS ELP BOI".split()},
            **{s: 8 for s in "LAX LAS PDX SAN SEA SFO SJC SMF OAK".split()}}

RESULTS = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data", "plan11")


def _r(name):
    return os.path.join(RESULTS, name)


def identity_path():
    return _r("plan11_identity.json")


def probe_path():
    return _r("plan11_probe.json")


def signals_path():
    return _r("plan11_signals.json")


def result_paths():
    return _r("plan11_result.json"), _r("plan11_result.md")


def markets_path():
    return os.path.join(DATA, "markets.json.gz")


def state_path():
    return os.path.join(DATA, "state.json")


def candles_path(d):
    return os.path.join(DATA, "candles", "%s.json.gz" % d.isoformat())


def radar_path(d):
    return os.path.join(DATA, "radar", "%s.json.gz" % d.isoformat())


def metar_path(st, ym, kind):
    return os.path.join(DATA, "metar", "%s_%s_%s.json.gz" % (st, ym, kind))


def now_iso(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat()


def utc_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date()


def stamp_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d%H%M")


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- stations (plan section 2) ----------
def rain_table(root=ROOT):
    """{"Kxxx": (CLI code, lat, lon)} from v3's rain table weather.RAIN, read from weather.py's source (weather.py imports
    requests, which the runner does not have)."""
    with open(os.path.join(root, "weather.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "RAIN" for t in node.targets):
            raw = ast.literal_eval(node.value)
            return {"K" + code[3:]: (code, float(lat), float(lon)) for code, lat, lon in raw.values()}
    raise RuntimeError("weather.RAIN not found")


def home_station(st, table):
    if st in table:
        return st
    for cur, olds in ALIASES.items():
        if st in olds:
            return cur
    return st


def station_of(m):
    """research/fetch.py's station_of: "at CLIxxx" or "(CLIxxx)" in rules_primary, else "Data for CLIxxx" in
    rules_secondary."""
    p = m.get("rules_primary") or ""
    s = re.search(r"\bat (CLI[A-Z]{3})\b", p) or re.search(r"\((CLI[A-Z]{3})\)", p) or \
        re.search(r"\bData for (CLI[A-Z]{3})\b", m.get("rules_secondary") or "")
    return ("K" + s.group(1)[3:]) if s else None


def ticker_day(t):
    try:
        return datetime.strptime(t.split("-")[1], "%y%b%d").date()
    except (IndexError, ValueError):
        return None


def fetch_start(d, st):
    """research/fetch.py's start_ts: the market day at 00:00 local standard time, in UTC seconds."""
    h = FETCH_TZ.get(st[1:])
    return None if h is None else calendar.timegm((d.year, d.month, d.day, h, 0, 0))


# ---------- identity (plan section 8) ----------
def identity_now(root=ROOT):
    out = {PLAN: P.file_hash(os.path.join(root, *PLAN.split("/")))}
    out.update({f: P.file_hash(os.path.join(root, *f.split("/"))) for f in CODE_FILES})
    try:
        out["weather.RAIN"] = _sha(canon(rain_table(root)))
    except (OSError, ValueError, SyntaxError, RuntimeError):
        out["weather.RAIN"] = None
    return out


def identity_problems(root=ROOT, path=None):
    """[] when the identity record exists and the plan, the code, the station table and PLAN7's pins still match."""
    rec, ok = P._read_json(path or identity_path())
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("identity"), dict):
        return ["no identity record (run freeze first)" if ok and rec is None else "identity record damaged"]
    now = identity_now(root)
    bad = sorted(k for k, v in rec["identity"].items() if now.get(k) != v)
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        bad.append("research/PLAN11.md differs from its frozen SHA-256")
    return bad + P.plan7_problems(root)


def freeze(root=ROOT, path=None, now=None):
    path = path or identity_path()
    if os.path.exists(path):
        return None, "already frozen (%s); stored once" % path
    if P.bytes_hash(os.path.join(root, *PLAN.split("/"))) != PLAN_SHA256:
        return None, "research/PLAN11.md differs from its frozen SHA-256; nothing saved"
    p7 = P.plan7_problems(root)
    if p7:
        return None, "PLAN7's pinned functions differ (%s); nothing saved" % ", ".join(p7)
    rec = dict(plan=PLAN, plan_sha256=PLAN_SHA256, identity=identity_now(root), frozen=now_iso(now),
               grid=GRID, palette_len=PALETTE_LEN)
    if any(v is None for v in rec["identity"].values()):
        return None, "a frozen file could not be read"
    jsonio.save(path, rec)
    return rec, "frozen: %s" % path


def require(stage, root=ROOT, need_probe=True, need_markets=False):
    """None when the stage may run, else the reason it refuses."""
    bad = identity_problems(root)
    if bad:
        return "%s refused: identity check failed (%s)" % (stage, "; ".join(bad))
    if need_probe:
        pr, ok = P._read_json(probe_path())
        if not ok or not isinstance(pr, dict) or pr.get("passed") is not True:
            return "%s refused: the probe has not passed (run probe; a failed probe needs an amendment)" % stage
    if need_markets and load_markets() is None:
        return "%s refused: no market list (run markets first)" % stage
    return None


# ---------- network ----------
class _HResp(object):
    def __init__(self, code, headers, body, url):
        self.status_code, self.headers, self._body, self.url = code, headers, body, url


class BytesClient(P.UrllibClient):
    """PLAN15's urllib client: the body as bytes (None for 404 when allowed); Retry-After capped at RETRY_AFTER_CAP;
    the final URL (after any redirect) must be on the client's own host."""

    def _transport(self):
        if self._get is not None:
            return self._get
        import urllib.request
        import urllib.parse
        import urllib.error
        import socket

        def get(url, params=None, headers=None, timeout=30):
            q = {k: v for k, v in (params or {}).items() if v is not None}
            full = url + ("?" + urllib.parse.urlencode(q) if q else "")
            req = urllib.request.Request(full, headers=dict(headers or self.headers))
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _HResp(r.status, dict(r.headers), r.read(), r.geturl())
            except urllib.error.HTTPError as ex:
                return _HResp(ex.code, dict(ex.headers or {}), ex.read() or b"", ex.geturl() or full)
        self._get = (get, (urllib.error.URLError, socket.timeout, ConnectionError))
        return self._get

    def host(self):
        from urllib.parse import urlparse
        return urlparse(self.base).hostname

    def get_bytes(self, path, params=None, none_on_404=True):
        from urllib.parse import urlparse
        get, network_error = self._transport()
        for attempt in range(self.tries):
            if self.min_gap:
                wait = self._last + self.min_gap - self._clock()
                if wait > 0:
                    self._sleep(wait)
                self._last = self._clock()
            self.requests += 1
            try:
                r = get(self.base + path, params=params or {}, headers=self.headers, timeout=self.timeout)
            except network_error:
                self._sleep(self.backoff(attempt))
                continue
            final = getattr(r, "url", None) or (self.base + path)
            if urlparse(final).hostname != self.host():
                raise RuntimeError("refused: the answer came from %s, not %s" % (urlparse(final).hostname, self.host()))
            if r.status_code == 200:
                return r._body
            if r.status_code == 404 and none_on_404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                self._sleep(min(RETRY_AFTER_CAP, self._retry_after(r) or self.backoff(attempt)))
                continue
            raise RuntimeError("HTTP %d %s" % (r.status_code, path))
        raise RuntimeError("giving up on %s" % path)


_IEM = []


def http_iem(path, params=None):
    """GET on mesonet.agron.iastate.edu: bytes, or None for 404 (tests replace this function)."""
    if not _IEM:
        _IEM.append(BytesClient(IEM, tries=6, timeout=120, min_gap=IEM_GAP,
                                headers={"User-Agent": P.USER_AGENT}))
    return _IEM[0].get_bytes(path, params)


_KALSHI = []


def kalshi_base():
    try:
        from config import KALSHI_BASE as base
    except Exception:   # noqa: BLE001  (config.py is needed only for its address)
        base = os.environ.get("KALSHI_BASE") or P.KALSHI_PUBLIC
    return base


def http_kalshi(path, params=None):
    """GET on Kalshi's public API (JSON), host-checked, with PLAN15's spacing (tests replace this function)."""
    if not _KALSHI:
        _KALSHI.append(BytesClient(kalshi_base(), tries=6, timeout=60, min_gap=P.KALSHI_GAP,
                                   headers={"User-Agent": P.USER_AGENT}))
    return json.loads(_KALSHI[0].get_bytes(path, params, none_on_404=False).decode("utf-8"))


def kalshi_pages(path, params, key):
    out, cur = [], None
    while True:
        q = dict(params)
        if cur:
            q["cursor"] = cur
        j = http_kalshi(path, q) or {}
        out.extend(j.get(key) or [])
        cur = j.get("cursor")
        if not cur:
            return out


# ---------- probe (plan section 2) ----------
def parse_wld(text):
    vals = [float(x) for x in text.split()]
    if len(vals) != 6:
        raise ValueError("a world file has six numbers")
    return dict(A=vals[0], D=vals[1], B=vals[2], E=vals[3], C=vals[4], F=vals[5])


def grid_problems(wld):
    return ["%s: archive %r, recorded %r" % (k, wld.get(k), GRID[k]) for k in ("A", "D", "B", "E", "C", "F")
            if wld.get(k) is None or abs(wld[k] - GRID[k]) > 1e-9]


def probe(now=None):
    if os.path.exists(probe_path()):
        return None, "probe already stored (%s); stored once" % probe_path()
    why = require("probe", need_probe=False)
    if why:
        return None, why
    base = PROBE_STAMP.strftime(RADAR_FMT)
    rec = dict(stamp=stamp_of(PROBE_STAMP.timestamp()), recorded_grid=GRID, recorded_palette_len=PALETTE_LEN,
               probed=now_iso(now), problems=[])
    body = http_iem(base + ".wld")
    if body is None:
        rec["problems"].append("no world file at %s.wld" % base)
    else:
        try:
            wld = parse_wld(body.decode("ascii", "replace"))
            rec["wld"] = wld
            rec["problems"].extend(grid_problems(wld))
        except ValueError as ex:
            rec["problems"].append("world file unreadable (%s)" % ex)
    if not rec["problems"]:
        png = http_iem(base + ".png")
        if png is None:
            rec["problems"].append("no frame at %s.png" % base)
        else:
            size, pal = png_header(png)
            rec.update(size=list(size) if size else None, palette_len=pal)
            if size != (GRID["width"], GRID["height"]):
                rec["problems"].append("frame size %r, expected %dx%d" % (size, GRID["width"], GRID["height"]))
            if pal != PALETTE_LEN:
                rec["problems"].append("palette length %r, expected %d" % (pal, PALETTE_LEN))
    rec["metar"] = metar_probe(rec["problems"])
    rec["passed"] = not rec["problems"]
    jsonio.save(probe_path(), rec)
    return rec, ("probe passed" if rec["passed"] else "PROBE FAILED: %s; the plan stops until an amendment"
                 % "; ".join(rec["problems"]))


def minute_share(rows):
    if not rows:
        return None
    return sum(1 for ts, _ in rows if datetime.fromtimestamp(ts, timezone.utc).minute in ROUTINE_MINUTES) / float(len(rows))


def metar_probe(problems):
    """One station-month of each report kind: both non-empty, routine at :51-:56, specials off that pattern."""
    st, ym = PROBE_METAR
    out = dict(station=st, month=ym)
    for kind in ("routine", "special"):
        try:
            rows = fetch_metar(metar_id(st), ym, kind)
        except NET_ERRORS as ex:
            problems.append("METAR %s request failed (%s)" % (kind, str(ex)[:80]))
            out[kind] = dict(error=str(ex)[:120])
            continue
        share = minute_share(rows)
        out[kind] = dict(reports=len(rows), share_at_51_56=share)
        if not rows:
            problems.append("METAR probe: no %s reports for %s %s" % (kind, st, ym))
        elif kind == "routine" and share < PROBE_ROUTINE_SHARE:
            problems.append("METAR probe: only %.0f%% of routine reports at :51-:56" % (100 * share))
        elif kind == "special" and share >= PROBE_SPECIAL_SHARE:
            problems.append("METAR probe: %.0f%% of special reports at :51-:56 (routine pattern)" % (100 * share))
    return out


def png_header(body):
    """((width, height), palette entries) from a PNG's IHDR and PLTE chunks; standard library only."""
    if body[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    i, size, pal = 8, None, None
    while i + 8 <= len(body):
        n = int.from_bytes(body[i:i + 4], "big")
        kind = body[i + 4:i + 8]
        if kind == b"IHDR":
            size = (int.from_bytes(body[i + 8:i + 12], "big"), int.from_bytes(body[i + 12:i + 16], "big"))
        elif kind == b"PLTE":
            pal = n // 3
        elif kind == b"IDAT":
            break
        i += 12 + n
    return size, pal


# ---------- markets (plan section 2) ----------
def list_markets(table, now=None):
    """(markets, counts). Kept per (station, day): the highest-volume settled market; results are stored, never printed."""
    seen, counts = {}, dict(listed=0, outside_range=0, no_station=0, not_in_table=0, scalar_or_void=0,
                            duplicates_dropped=0, start_mismatch=0, no_close_time=0)
    not_in = {}
    for path, extra in (("/historical/markets", {}), ("/markets", {"status": "settled"})):
        for m in kalshi_pages(path, dict(series_ticker=SERIES, limit=KALSHI_LIMIT, **extra), "markets"):
            t = m.get("ticker")
            if not t or t in seen:
                continue
            seen[t] = (m, path.startswith("/historical"))
    best = {}
    for t, (m, hist) in sorted(seen.items()):
        counts["listed"] += 1
        d = ticker_day(t)
        if d is None or not FIRST_DAY <= d <= LAST_DAY:
            counts["outside_range"] += 1
            continue
        st = station_of(m)
        if not st:
            counts["no_station"] += 1
            continue
        st = home_station(st, table)
        if st not in table:
            counts["not_in_table"] += 1
            not_in[st] = not_in.get(st, 0) + 1
            continue
        if m.get("result") not in ("yes", "no"):
            counts["scalar_or_void"] += 1
            continue
        close = P.ts_of(m.get("close_time"))
        if close is None:
            counts["no_close_time"] += 1
            continue
        vol = P.num(m.get("volume_fp"))
        vol = vol if vol is not None else (P.num(m.get("volume")) or 0.0)
        rec = dict(ticker=t, day=d.isoformat(), station=st, result=m["result"], close=int(close),
                   start=int(close) - 86400, volume=vol, hist=hist, fetch_start=fetch_start(d, st))
        k = (st, d)
        if k in best:
            counts["duplicates_dropped"] += 1
            if vol <= best[k]["volume"]:
                continue
        best[k] = rec
    out = sorted(best.values(), key=lambda r: (r["day"], r["station"]))
    for r in out:
        if r["fetch_start"] != r["start"]:
            counts["start_mismatch"] += 1
    counts["included"] = len(out)
    counts["stations_not_in_table"] = not_in
    return out, counts


def make_markets(now=None):
    if os.path.exists(markets_path()):
        return None, "market list already stored (%s); listed once" % markets_path()
    why = require("markets")
    if why:
        return None, why
    ms, counts = list_markets(rain_table(), now)
    rec = dict(plan=PLAN, listed_at=now_iso(now), counts=counts, markets=ms)
    P.save_gz(markets_path(), rec)
    return rec, "markets: %s" % json.dumps(counts, sort_keys=True)


def load_markets():
    rec, ok = P._read_json(markets_path())
    if not ok or not isinstance(rec, dict) or not isinstance(rec.get("markets"), list):
        return None
    return rec


# ---------- decision times ----------
def decision_times(start, end):
    """Every :00/:30 UTC time from start + 30 min to end - 60 min, inclusive."""
    first = start + FIRST_AFTER
    t = -(-first // STEP) * STEP
    out = []
    while t <= end - LAST_BEFORE:
        out.append(t)
        t += STEP
    return out


def needed_stamps(m):
    s = set()
    for t in decision_times(m["start"], m["close"]):
        s.add(t - LAG_NOW)
        s.add(t - LAG_BEFORE)
    return s


# ---------- candles (plan section 3) ----------
def parse_candles(cs, start):
    """{minute offset from the day start: [yes bid close, yes ask close]} for candles on whole minutes."""
    out = {}
    for c in cs or []:
        try:
            e = int(c["end_period_ts"])
        except (KeyError, TypeError, ValueError):
            continue
        k, r = divmod(e - int(start), 60)
        if r:
            continue
        out[str(k)] = [ohlc_field(c.get("yes_bid") or {}, "close"), ohlc_field(c.get("yes_ask") or {}, "close")]
    return out


def fetch_candles(m):
    """research/fetch.py's candle requests: the archive one market at a time, the live markets by series path."""
    q = dict(start_ts=int(m["start"]), end_ts=int(m["close"]), period_interval=1, include_latest_before_start="true")
    if m.get("hist"):
        j = http_kalshi("/historical/markets/%s/candlesticks" % m["ticker"], q) or {}
    else:
        j = http_kalshi("/series/%s/markets/%s/candlesticks" % (SERIES, m["ticker"]), q) or {}
    return j.get("candlesticks") or []


def price_at(cmap, start, t):
    """(bid, ask) to pay at decision time t, or None (plan section 3)."""
    if not cmap:
        return None
    target = (t + FILL_AFTER - start) // 60
    for k in range(target, target - FILL_BACK - 1, -1):
        q = cmap.get(str(k))
        if q is None:
            continue
        bid, ask = q
        if bid is None or ask is None or not (0 < bid < ask < 1.0 - 1e-9):
            return None
        return bid, ask
    return None


def fee(price):
    """Kalshi's taker fee for one contract, rounded up to the cent (core.fee)."""
    c = price * 100
    if abs(c - round(c)) < 1e-9:
        c = int(round(c))
        return -(-7 * c * (100 - c) // 10000) / 100.0
    return math.ceil(FEE_RATE * price * (1 - price) * 100) / 100.0


# ---------- gauge (plan section 2) ----------
P_GROUP = re.compile(r"(?:^|\s)P(\d{4})(?=\s|$)")


def p_group(text):
    """Hundredths of an inch in the report's own hourly group (Pxxxx in the remarks), or None."""
    parts = (" " + (text or "") + " ").split(" RMK ", 1)
    if len(parts) < 2:
        return None
    mm = P_GROUP.search(parts[1])
    return int(mm.group(1)) if mm else None


def is_cor(text):
    head = (" " + (text or "") + " ").split(" RMK ", 1)[0]
    return " COR " in head + " "


def parse_metar_csv(body):
    """[[valid_ts, text]] from asos.py's onlycomma output (station,valid,metar)."""
    out = []
    rd = csv.reader(io.StringIO(body.decode("utf-8", "replace")))
    for row in rd:
        if len(row) < 3 or row[0] == "station" or row[0].startswith("#"):
            continue
        try:
            ts = calendar.timegm(datetime.strptime(row[1].strip(), "%Y-%m-%d %H:%M").timetuple())
        except ValueError:
            continue
        out.append([ts, row[2]])
    return out


def metar_id(st):
    return st[1:]


def metar_ids(st):
    return (metar_id(st),) + tuple(metar_id(a) for a in ALIASES.get(st, ()))


def fetch_metar(sid, ym, kind):
    y, mo = int(ym[:4]), int(ym[4:])
    ny, nm = (y + 1, 1) if mo == 12 else (y, mo + 1)
    q = dict(station=sid, data="metar", year1=y, month1=mo, day1=1, hour1=0, minute1=0,
             year2=ny, month2=nm, day2=1, hour2=0, minute2=0, tz="Etc/UTC", format="onlycomma", latlon="no",
             elev="no", missing="M", trace="T", direct="no", report_type=3 if kind == "routine" else 4)
    body = http_iem("/cgi-bin/request/asos.py", q)
    if body is None:
        raise RuntimeError("asos.py answered 404")
    return parse_metar_csv(body)


def merge_rows(parts):
    """Reports of several codes in time order (stable: the current code's first), exact duplicates removed."""
    out, seen = [], set()
    for ts, text in sorted((r for part in parts for r in part), key=lambda r: r[0]):
        if (ts, text) in seen:
            continue
        seen.add((ts, text))
        out.append([ts, text])
    return out


def gauge_reports(rows_routine, rows_special, start, end):
    """(counted [(valid, hundredths)], has_routine) for one market day. The first routine report after the start and
    everything up to it are ignored; COR reports are dropped; amounts are never added."""
    def clean(rows):
        out, seen = [], set()
        for ts, text in sorted(rows, key=lambda r: r[0]):
            if is_cor(text) or ts in seen:
                continue
            seen.add(ts)
            out.append((ts, text))
        return out
    rt = [r for r in clean(rows_routine) if start <= r[0] <= end]
    sp = [r for r in clean(rows_special) if start <= r[0] <= end]
    after = [ts for ts, _ in rt if ts > start]
    if not after:
        return [], False
    boundary = after[0]
    counted = []
    for ts, text in sorted(rt + sp, key=lambda r: r[0]):
        if ts <= boundary:
            continue
        h = p_group(text)
        if h is not None:
            counted.append((ts, h))
    return counted, True


def gauge_known(counted, t):
    return any(ts <= t - GAUGE_LAG and h >= GAUGE_MIN for ts, h in counted)


# ---------- radar readings (plan sections 2 and 4) ----------
def dbz_index(dbz):
    """The lowest palette index whose dBZ (-32.5 + 0.5 i) is at least dbz."""
    return int(math.ceil((dbz + 32.5) / 0.5 - 1e-9))


IDX_R, IDX_P = dbz_index(DBZ_R), dbz_index(DBZ_P)   # 105, 115


def gc_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def window(lat, lon, grid=None):
    """(r0, r1, c0, c1) half-open pixel box surely holding every pixel centre within P_SEARCH_KM of the station."""
    g = grid or GRID
    dlat = P_SEARCH_KM / (math.pi * EARTH_KM / 180.0) * 1.05
    dlon = dlat / max(0.05, math.cos(math.radians(min(89.0, abs(lat) + dlat))))
    r0 = int(math.floor((lat + dlat - g["F"]) / g["E"])) - 1
    r1 = int(math.ceil((lat - dlat - g["F"]) / g["E"])) + 2
    c0 = int(math.floor((lon - dlon - g["C"]) / g["A"])) - 1
    c1 = int(math.ceil((lon + dlon - g["C"]) / g["A"])) + 2
    r0, c0 = min(max(0, r0), g["height"]), min(max(0, c0), g["width"])
    return r0, max(r0, min(g["height"], r1)), c0, max(c0, min(g["width"], c1))


def centre(row, col, grid=None):
    g = grid or GRID
    return g["F"] + g["E"] * row, g["C"] + g["A"] * col


def readings_py(pix, lat, lon, grid=None):
    """Pure Python reference: pix[row][col] palette indices of the whole grid (or a callable (row, col) -> index).
    Returns [pixels >= 20 dBZ within 10 km, echo distance (km of the 4th-nearest >= 25 dBZ pixel within 150 km, or
    None), pixels >= 25 dBZ within 150 km]."""
    r0, r1, c0, c1 = window(lat, lon, grid)
    n_r, near, n_p = 0, [], 0
    for r in range(r0, r1):
        row = pix[r]
        for c in range(c0, c1):
            v = row[c]
            if v < IDX_R:
                continue
            la, lo = centre(r, c, grid)
            d = gc_km(lat, lon, la, lo)
            if d <= R_KM:
                n_r += 1
            if v >= IDX_P and d <= P_SEARCH_KM:
                n_p += 1
                near.append(d)
    near.sort()
    return [n_r, round(near[MIN_PIXELS - 1], 3) if len(near) >= MIN_PIXELS else None, n_p]


_DIST = {}


def _dist_np(np, lat, lon, grid):
    key = (lat, lon, canon(grid))
    if key not in _DIST:
        r0, r1, c0, c1 = window(lat, lon, grid)
        rows = np.arange(r0, r1, dtype=np.float64)
        cols = np.arange(c0, c1, dtype=np.float64)
        la = np.radians(grid["F"] + grid["E"] * rows)[:, None]
        lo = np.radians(grid["C"] + grid["A"] * cols)[None, :]
        p1, l1 = math.radians(lat), math.radians(lon)
        a = np.sin((la - p1) / 2) ** 2 + math.cos(p1) * np.cos(la) * np.sin((lo - l1) / 2) ** 2
        _DIST[key] = ((r0, r1, c0, c1), 2 * EARTH_KM * np.arcsin(np.minimum(1.0, np.sqrt(a))))
    return _DIST[key]


def readings_np(np, arr, lat, lon, grid=None):
    """The same readings with numpy on a 2-D uint8 array of the whole grid (only the station's box is read)."""
    g = grid or GRID
    (r0, r1, c0, c1), dist = _dist_np(np, lat, lon, g)
    crop = arr[r0:r1, c0:c1]
    n_r = int(np.count_nonzero((crop >= IDX_R) & (dist <= R_KM)))
    d = dist[(crop >= IDX_P) & (dist <= P_SEARCH_KM)]
    echo = None
    if d.size >= MIN_PIXELS:
        echo = round(float(np.partition(d, MIN_PIXELS - 1)[MIN_PIXELS - 1]), 3)
    return [n_r, echo, int(d.size)]


def decode_frame(body, grid=None):
    """(uint8 array, None) or (None, reason). Pillow and numpy, imported here (runner only)."""
    import numpy as np
    from PIL import Image
    g = grid or GRID
    try:
        im = Image.open(io.BytesIO(body))
        im.load()
    except Exception as ex:   # noqa: BLE001  (a damaged file is a missing frame)
        return None, "unreadable (%s)" % str(ex)[:60]
    if im.size != (g["width"], g["height"]):
        return None, "size %dx%d" % im.size
    if im.mode != "P":
        return None, "mode %s" % im.mode
    _, pal = png_header(body)
    if pal != PALETTE_LEN:
        return None, "palette %r" % pal
    return np.asarray(im, dtype=np.uint8), None


def frame_readings(body, table, grid=None):
    """({station: readings}, None) or (None, reason) for one frame."""
    arr, why = decode_frame(body, grid)
    if arr is None:
        return None, why
    import numpy as np
    return {st: readings_np(np, arr, lat, lon, grid) for st, (_, lat, lon) in sorted(table.items())}, None


# ---------- download (resumable, budgeted) ----------
def _load_state():
    s, ok = P._read_json(state_path())
    return s if ok and isinstance(s, dict) else {}


def _save_state(s):
    jsonio.save(state_path(), s)


def _gz(path):
    rec, ok = P._read_json(path)
    return rec if ok and isinstance(rec, dict) else None


def markets_by_day(ms):
    out = {}
    for m in ms:
        out.setdefault(m["day"], []).append(m)
    return out


NET_ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError)


def download_candles(ms, deadline, state, log=print, now=None):
    tries = state.setdefault("candle_tries", {})
    for day, items in sorted(markets_by_day(ms).items()):
        path = candles_path(date.fromisoformat(day))
        if os.path.exists(path):
            continue
        if time.time() > deadline:
            return False
        rec, held = dict(day=day, fetched=now_iso(now), markets={}), False
        for m in items:
            try:
                cs = fetch_candles(m)
                rec["markets"][m["ticker"]] = dict(c=parse_candles(cs, m["start"]))
            except NET_ERRORS as ex:
                n = tries[m["ticker"]] = tries.get(m["ticker"], 0) + 1
                if n >= TRIES:
                    rec["markets"][m["ticker"]] = dict(error=str(ex)[:120])
                else:
                    held = True
        if held:
            log("  candles %s held back (a request failed; tried again next run)" % day)
            continue
        P.save_gz(path, rec)
        log("  candles %s: %d markets" % (day, len(items)))
    return True


def station_months(ms):
    """{station: sorted YYYYMM} covering every UTC instant of each market's day."""
    out = {}
    for m in ms:
        for ts in (m["start"], m["close"]):
            out.setdefault(m["station"], set()).add(utc_date(ts).strftime("%Y%m"))
    return {k: sorted(v) for k, v in out.items()}


def download_gauge(ms, deadline, state, log=print, now=None):
    tries = state.setdefault("metar_tries", {})
    for st, months in sorted(station_months(ms).items()):
        for ym in months:
            for kind in ("routine", "special"):
                path = metar_path(st, ym, kind)
                if os.path.exists(path):
                    continue
                if time.time() > deadline:
                    return False
                key = "%s_%s_%s" % (st, ym, kind)
                try:
                    parts, used = [], []
                    for sid in metar_ids(st):   # every code of the station (a re-coded one has two), every month
                        got = fetch_metar(sid, ym, kind)
                        parts.append(got)
                        if got:
                            used.append(sid)
                    rows = merge_rows(parts)
                    P.save_gz(path, dict(station=st, ids=used, asked=list(metar_ids(st)), month=ym, kind=kind,
                                         fetched=now_iso(now), rows=rows))
                    log("  METAR %s %s %s: %d reports" % (st, ym, kind, len(rows)))
                except NET_ERRORS as ex:
                    n = tries[key] = tries.get(key, 0) + 1
                    if n >= TRIES:
                        P.save_gz(path, dict(station=st, month=ym, kind=kind, fetched=now_iso(now), error=str(ex)[:120]))
    return True


def all_stamps(ms):
    s = set()
    for m in ms:
        s |= needed_stamps(m)
    return sorted(s)


def download_radar(ms, table, deadline, state, log=print, now=None, grid=None):
    tries = state.setdefault("radar_tries", {})
    stamps = all_stamps(ms)
    by_day = {}
    for ts in stamps:
        by_day.setdefault(utc_date(ts).isoformat(), []).append(ts)
    for day, sts in sorted(by_day.items()):
        path = radar_path(date.fromisoformat(day))
        rec = _gz(path) or dict(day=day, frames={})
        todo = [ts for ts in sts if stamp_of(ts) not in rec["frames"]]
        if not todo:
            continue
        changed = 0
        for ts in todo:
            if time.time() > deadline:
                if changed:
                    P.save_gz(path, rec)
                return False
            key = stamp_of(ts)
            base = datetime.fromtimestamp(ts, timezone.utc).strftime(RADAR_FMT)
            try:
                body = http_iem(base + ".png")
                if body is None:
                    rec["frames"][key] = dict(missing="not in archive")
                elif len(body) > MAX_FRAME_BYTES:
                    rec["frames"][key] = dict(missing="over %d bytes" % MAX_FRAME_BYTES)
                else:
                    rd, why = frame_readings(body, table, grid)
                    rec["frames"][key] = dict(s=rd) if rd is not None else dict(missing=why)
                changed += 1
            except NET_ERRORS as ex:
                n = tries[key] = tries.get(key, 0) + 1
                if n >= TRIES:
                    rec["frames"][key] = dict(missing="failed %d runs (%s)" % (n, str(ex)[:60]))
                    changed += 1
            if changed and changed % 12 == 0:
                P.save_gz(path, rec)
        if changed:
            rec["updated"] = now_iso(now)
            P.save_gz(path, rec)
            log("  radar %s: %d frames" % (day, len(rec["frames"])))
    return True


def download(budget_minutes=None, only=None, log=print, now=None, grid=None):
    why = require("download", need_markets=True)
    if why:
        return False, why
    ms = load_markets()["markets"]
    deadline = time.time() + (budget_minutes * 60 if budget_minutes is not None else 10 ** 9)
    state = _load_state()
    done = True
    try:
        for kind, fn in (("candles", lambda: download_candles(ms, deadline, state, log, now)),
                         ("gauge", lambda: download_gauge(ms, deadline, state, log, now)),
                         ("radar", lambda: download_radar(ms, rain_table(), deadline, state, log, now, grid))):
            if only and kind != only:
                continue
            if not fn():
                done = False
                break
    finally:
        _save_state(state)
    left = completeness(ms)
    msg = "download %s; still to fetch: %s" % ("finished this pass" if done else "stopped at the time budget",
                                              json.dumps(left, sort_keys=True))
    return done and not any(left.values()), msg


def completeness(ms):
    """Items not yet downloaded or recorded missing, by kind."""
    left = dict(candle_days=0, metar_files=0, radar_frames=0)
    for day in markets_by_day(ms):
        if not os.path.exists(candles_path(date.fromisoformat(day))):
            left["candle_days"] += 1
    for st, months in station_months(ms).items():
        for ym in months:
            for kind in ("routine", "special"):
                if not os.path.exists(metar_path(st, ym, kind)):
                    left["metar_files"] += 1
    have = {}
    for ts in all_stamps(ms):
        d = utc_date(ts).isoformat()
        if d not in have:
            have[d] = (_gz(radar_path(utc_date(ts))) or {}).get("frames", {})
        if stamp_of(ts) not in have[d]:
            left["radar_frames"] += 1
    return left


# ---------- loading the downloaded data ----------
def load_data(ms):
    """(candles {ticker: map or None}, gauge {(station, ym, kind): rows or None}, radar {stamp: {station: readings}
    or None}) from the day files."""
    candles = {}
    for day in markets_by_day(ms):
        rec = _gz(candles_path(date.fromisoformat(day))) or {}
        for t, v in (rec.get("markets") or {}).items():
            candles[t] = v.get("c") if isinstance(v, dict) and "c" in v else None
    gauge = {}
    for st, months in station_months(ms).items():
        for ym in months:
            for kind in ("routine", "special"):
                rec = _gz(metar_path(st, ym, kind))
                gauge[(st, ym, kind)] = rec.get("rows") if rec and "rows" in rec else None
    radar = {}
    days = sorted({utc_date(ts).isoformat() for ts in all_stamps(ms)})
    for d in days:
        rec = _gz(radar_path(date.fromisoformat(d))) or {}
        for k, v in (rec.get("frames") or {}).items():
            radar[k] = v.get("s") if isinstance(v, dict) and "s" in v else None
    return candles, gauge, radar


def market_gauge(m, gauge):
    """(counted reports, lost) for one market."""
    rows = {"routine": [], "special": []}
    lost = False
    for ym in sorted({utc_date(m["start"]).strftime("%Y%m"), utc_date(m["close"]).strftime("%Y%m")}):
        for kind in ("routine", "special"):
            r = gauge.get((m["station"], ym, kind))
            if r is None:
                lost = True
            else:
                rows[kind].extend(r)
    counted, has_routine = gauge_reports(rows["routine"], rows["special"], m["start"], m["close"])
    return (None if lost or not has_routine else counted), (lost or not has_routine)


# ---------- the three rules (plan sections 3 and 4) ----------
def frame_at(radar, ts, st):
    f = radar.get(stamp_of(ts))
    if f is None:
        return None
    return f.get(st)


def market_signals(m, cmap, counted, radar):
    """(signals, no_price) for one market. signals: {rule: dict(t, bid, ask)}; never reads the result."""
    out, no_price = {}, {r: 0 for r in RULES}
    st = m["station"]
    for t in decision_times(m["start"], m["close"]):
        g = counted is not None and gauge_known(counted, t)
        f10 = frame_at(radar, t - LAG_NOW, st)
        f40 = frame_at(radar, t - LAG_BEFORE, st)
        cond = dict(
            G=g,
            R=counted is not None and not g and f10 is not None and f10[0] >= MIN_PIXELS,
            P=(counted is not None and not g and f10 is not None and f40 is not None and f10[0] < MIN_PIXELS
               and f10[1] is not None and f10[1] <= P_NEAR_KM and f40[1] is not None
               and f10[1] <= f40[1] - P_CLOSE_KM))
        q = None
        for rule in RULES:
            if rule in out or not cond[rule]:
                continue
            if q is None:
                q = price_at(cmap, m["start"], t) or False
            if q is False:
                no_price[rule] += 1
                continue
            if q[1] <= CAPS[rule] + 1e-9:
                out[rule] = dict(t=t, bid=q[0], ask=q[1])
    return out, no_price


def radar_lost(m, radar, mode=None):
    """strict: any needed frame missing; t10: no decision time has a usable t - 10 frame."""
    mode = mode or RADAR_LOSS_READING
    if mode == "strict":
        return any(radar.get(stamp_of(ts)) is None for ts in needed_stamps(m))
    if mode == "t10":
        return all(radar.get(stamp_of(t - LAG_NOW)) is None for t in decision_times(m["start"], m["close"]))
    raise ValueError("unknown radar loss reading %r" % mode)


def lost_sources(m, cmap_present, cmap, gauge_lost, radar, mode=None):
    lost = []
    if not cmap_present or not cmap:
        lost.append("candles")
    if gauge_lost:
        lost.append("gauge")
    if radar_lost(m, radar, mode):
        lost.append("radar")
    return lost


def radar_loss_counts(ms, radar):
    return {mode: sum(1 for m in ms if radar_lost(m, radar, mode)) for mode in RADAR_LOSS_READINGS}


def compute_signals(ms, candles, gauge, radar):
    """Every signal of every market, with descriptive extras that need no outcome."""
    sig, lost, no_price = [], {}, {r: 0 for r in RULES}
    for m in ms:
        cmap = candles.get(m["ticker"])
        counted, glost = market_gauge(m, gauge)
        ls = lost_sources(m, m["ticker"] in candles, cmap, glost, radar)
        if ls:
            lost[m["ticker"]] = ls
        s, npr = market_signals(m, cmap, counted, radar)
        for r in RULES:
            no_price[r] += npr[r]
        for rule, x in sorted(s.items()):
            later = price_at(cmap, m["start"], x["t"] + 30 * 60)
            first_gauge = None
            if counted:
                after = [ts for ts, h in counted if h >= GAUGE_MIN and ts > x["t"] - GAUGE_LAG]
                first_gauge = round((min(after) - x["t"]) / 60.0, 1) if after else None
            sig.append(dict(rule=rule, ticker=m["ticker"], day=m["day"], station=m["station"], t=x["t"],
                            minutes_into_day=(x["t"] - m["start"]) // 60, bid=x["bid"], ask=x["ask"],
                            fee=fee(x["ask"]), ask_30min_later=later[1] if later else None,
                            gauge_minutes_after=first_gauge))
    gauge_rain = {}
    for m in ms:
        counted, _ = market_gauge(m, gauge)
        gauge_rain[m["ticker"]] = None if counted is None else any(h >= GAUGE_MIN for _, h in counted)
    return dict(signals=sig, lost=lost, no_price=no_price, gauge_rain=gauge_rain, markets=len(ms),
                radar_loss_reading=RADAR_LOSS_READING, radar_lost_markets=radar_loss_counts(ms, radar))


def git_log(relpath):
    """`git log --all --oneline -- relpath` in the repository, or None when git cannot answer (tests replace this)."""
    import subprocess
    try:
        r = subprocess.run(["git", "log", "--all", "--oneline", "--", relpath], cwd=ROOT, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def committed_guard(stage):
    """None, or why the stage refuses: one of its output files was ever committed, or git could not be asked."""
    for rel in GUARDED[stage]:
        out = git_log(rel)
        if out is None:
            return "%s refused: git history could not be read; run through the workflow" % stage
        if out.strip():
            return "%s refused: %s was committed once (%s)" % (stage, rel, out.strip().splitlines()[0][:60])
    return None


def make_signals(now=None, data=None):
    if os.path.exists(signals_path()):
        return None, "signals already stored (%s); worked out once" % signals_path()
    why = committed_guard("signals")
    if why:
        return None, why
    why = require("signals", need_markets=True)
    if why:
        return None, why
    ms = load_markets()["markets"]
    left = completeness(ms)
    if any(left.values()):
        return None, "signals refused: the download is not complete (%s)" % json.dumps(left, sort_keys=True)
    candles, gauge, radar = data or load_data(ms)
    rec = compute_signals(ms, candles, gauge, radar)
    rec.update(plan=PLAN, made=now_iso(now))
    rec["sha256"] = _sha(canon({k: rec[k] for k in SIG_KEYS}))
    jsonio.save(signals_path(), rec)
    counts = {r: sum(1 for x in rec["signals"] if x["rule"] == r) for r in RULES}
    return rec, "signals: %s; markets with lost data: %d of %d (radar lost, by reading: %s; applied: %s)" % (
        json.dumps(counts, sort_keys=True), len(rec["lost"]), len(ms),
        json.dumps(rec["radar_lost_markets"], sort_keys=True), RADAR_LOSS_READING)


SIG_KEYS = ("signals", "lost", "no_price", "gauge_rain", "markets", "radar_loss_reading", "radar_lost_markets")


def load_signals():
    rec, ok = P._read_json(signals_path())
    if not ok or not isinstance(rec, dict) or "signals" not in rec:
        return None
    if rec.get("sha256") != _sha(canon({k: rec.get(k) for k in SIG_KEYS})):
        return None
    return rec


# ---------- statistics (plan section 5) ----------
def t_p(t, df):
    if t is None:
        return 1.0
    return P.P7.t_upper(t, df) if t >= 0 else 1.0 - P.P7.t_upper(-t, df)


def t_cut(level, df):
    return max(T_FLOOR, P.P7.t_quantile(level, df))


def binom_tail_ge(k, n, p):
    if k <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def cp_lower(k, n, alpha):
    """One-sided exact (Clopper-Pearson) lower bound: the p with P(X >= k | n, p) = alpha; 0 when k = 0."""
    if n <= 0 or k <= 0:
        return 0.0
    if k >= n:
        return alpha ** (1.0 / n)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_tail_ge(k, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def rule_stats(rule, bets, days):
    """bets: [dict(day, profit, win, cost)] of one rule; days: every counted market day, in order."""
    by = {d: 0.0 for d in days}
    sd = {}
    for b in bets:
        by[b["day"]] += b["profit"]
        sd[b["day"]] = sd.get(b["day"], True) and b["win"]
    x = [by[d] for d in days]
    mean, se = P.P7.mean_se(x) if len(x) >= 2 else (None, None)
    df = len(x) - 1
    t = (mean / se) if se else None
    st = dict(rule=rule, signals=len(bets), signal_days=len(sd), days=len(days), mean_day=mean, se=se, df=df, t=t,
              p_t=t_p(t, df), wins=sum(1 for b in bets if b["win"]), winning_days=sum(1 for v in sd.values() if v),
              mean_cost=(sum(b["cost"] for b in bets) / len(bets)) if bets else None,
              profit_total=sum(b["profit"] for b in bets), x=x)
    if len(bets) < MIN_SIGNALS or len(sd) < MIN_SIGNAL_DAYS:
        st["not_testable"] = "%d signals on %d market days (needs %d on %d)" % (len(bets), len(sd), MIN_SIGNALS,
                                                                               MIN_SIGNAL_DAYS)
    return st


def holm(stats, boot=None):
    """Holm over the three rules by their t p-values; each rule needs the t reading, the bootstrap lower bound and the
    win-rate bound at its own level; stop at the first failure. Untestable rules keep a place and come last."""
    boot = boot or (lambda x: P.P7.boot_means(x, block=BOOT_BLOCK, n=BOOT_DRAWS, seed=BOOT_SEED))
    order = sorted(stats, key=lambda s: (1 if "not_testable" in s else 0, s["p_t"], s["rule"]))
    going = True
    for rank, s in enumerate(order):
        lvl = HOLM_LEVELS[rank]
        s["holm_rank"], s["holm_level"] = rank + 1, lvl
        if "not_testable" in s:
            s["passed"], s["verdict"] = False, NOT_TESTABLE + ": " + s["not_testable"]
            going = False
            continue
        cut = t_cut(lvl, s["df"])
        ms = boot(s["x"]) if len(s["x"]) >= BOOT_BLOCK else None
        lower = ms[int(lvl * len(ms))] if ms else None
        wr = cp_lower(s["winning_days"], s["signal_days"], lvl)
        c1 = s["t"] is not None and s["t"] > cut
        c2 = lower is not None and lower > 0
        c3 = s["mean_cost"] is not None and wr > s["mean_cost"]
        s["checks"] = dict(t=s["t"], t_cut=cut, boot_lower=lower, win_rate_lower=wr, mean_cost=s["mean_cost"],
                           t_ok=c1, boot_ok=c2, win_rate_ok=c3)
        ok = going and c1 and c2 and c3
        s["passed"] = bool(ok)
        s["verdict"] = VERDICT_LEAD if ok else VERDICT_NONE
        going = going and ok
    return order


def band(p):
    for name, lo, hi in PRICE_BANDS:
        if lo - 1e-9 <= p < hi - 1e-9:
            return name
    return PRICE_BANDS[-1][0]


def describe(bets_by_rule, ms, srec):
    res = by_y = {m["ticker"]: m["result"] == "yes" for m in ms}
    out = {}
    rain_days = sorted({m["day"] for m in ms if by_y[m["ticker"]]})
    for rule in RULES:
        bets = bets_by_rule[rule]
        def grp(key):
            g = {}
            for b in bets:
                k = key(b)
                x = g.setdefault(k, dict(signals=0, wins=0, profit=0.0))
                x["signals"] += 1
                x["wins"] += 1 if b["win"] else 0
                x["profit"] = round(x["profit"] + b["profit"], 4)
            return g
        fired_days = {b["day"] for b in bets}
        moves = [b["ask_30min_later"] - b["ask"] for b in bets if b.get("ask_30min_later") is not None]
        d = dict(by_month=grp(lambda b: b["day"][:7]), by_price_band=grp(lambda b: band(b["ask"])),
                 win_rate=(sum(1 for b in bets if b["win"]) / float(len(bets))) if bets else None,
                 share_of_rain_days_fired=(sum(1 for d in rain_days if d in fired_days) / float(len(rain_days)))
                 if rain_days else None,
                 ask_move_30min_mean=(sum(moves) / len(moves)) if moves else None, ask_move_30min_n=len(moves))
        if rule == "G":
            late = [b for b in bets if b["minutes_into_day"] > 60]
            d["profit_without_first_hour"] = dict(signals=len(late), profit=round(sum(b["profit"] for b in late), 4))
        if rule == "P":
            lags = sorted(b["gauge_minutes_after"] for b in bets if b.get("gauge_minutes_after") is not None)
            d["gauge_after_signal"] = dict(n=len(lags), never=len(bets) - len(lags),
                                           median_minutes=lags[len(lags) // 2] if lags else None)
        out[rule] = d
    lost = srec.get("lost") or {}
    miss = {}
    for m in ms:
        k = m["result"]
        x = miss.setdefault(k, dict(markets=0, lost=0))
        x["markets"] += 1
        x["lost"] += 1 if m["ticker"] in lost else 0
    agree = [(srec["gauge_rain"].get(m["ticker"]), res[m["ticker"]]) for m in ms]
    agree = [(g, y) for g, y in agree if g is not None]
    out["missing_by_outcome"] = miss
    out["gauge_agrees_with_result"] = dict(n=len(agree), agree=sum(1 for g, y in agree if g == y),
                                           gauge_yes_result_no=sum(1 for g, y in agree if g and not y),
                                           gauge_no_result_yes=sum(1 for g, y in agree if y and not g))
    return out


def score_from(ms, srec):
    by_t = {m["ticker"]: m for m in ms}
    days = sorted({m["day"] for m in ms})
    bets_by_rule = {r: [] for r in RULES}
    for s in srec["signals"]:
        m = by_t.get(s["ticker"])
        if m is None:
            raise ValueError("a signal for a market outside the list")
        y = 1.0 if m["result"] == "yes" else 0.0
        cost = s["ask"] + s["fee"]
        bets_by_rule[s["rule"]].append(dict(s, win=y == 1.0, cost=cost, profit=y - cost))
    stats = [rule_stats(r, bets_by_rule[r], days) for r in RULES]
    lost_share = len(srec.get("lost") or {}) / float(len(ms)) if ms else 1.0
    plan_nt = None
    if not ms:
        plan_nt = "no markets"
    elif lost_share > MAX_LOST:
        plan_nt = "%.1f%% of markets lost radar frames, gauge reports or candles (more than %d%%)" % (
            100 * lost_share, int(100 * MAX_LOST))
    if plan_nt:
        for s in stats:
            s["not_testable"] = plan_nt
    order = holm(stats)
    for s in order:
        s.pop("x", None)
    lost_by = {}
    for ls in (srec.get("lost") or {}).values():
        for k in ls:
            lost_by[k] = lost_by.get(k, 0) + 1
    return dict(plan=PLAN, plan_sha256=PLAN_SHA256, markets=len(ms), market_days=len(days),
                lost_share=lost_share, lost_by_source=lost_by, plan_not_testable=plan_nt,
                radar_loss_reading=srec.get("radar_loss_reading"), radar_lost_markets=srec.get("radar_lost_markets"),
                no_price=srec.get("no_price"), rules=sorted(order, key=lambda s: RULES.index(s["rule"])),
                descriptive=describe(bets_by_rule, ms, srec))


def _f(v, fmt="%+.4f"):
    return "n/a" if v is None else fmt % v


def result_md(res, mrec):
    L = ["# PLAN11 result (scored once)", "",
         "Plan: research/PLAN11.md (SHA-256 %s). Markets listed %s; scored %s." % (PLAN_SHA256[:12], mrec.get("listed_at"),
                                                                                 res["scored"]),
         "Research only: nothing here can justify real money (plan section 5).", "",
         "Markets: %d on %d market days; %.1f%% lost data (%s)." % (
             res["markets"], res["market_days"], 100 * res["lost_share"], json.dumps(res["lost_by_source"], sort_keys=True))]
    if res["plan_not_testable"]:
        L.append("**The whole plan reads not testable: %s.**" % res["plan_not_testable"])
    L.append("Markets losing radar: %s by the applied reading %s; by each reading %s (strict is descriptive only)." % (
        (res.get("radar_lost_markets") or {}).get(res.get("radar_loss_reading")), res.get("radar_loss_reading"),
        json.dumps(res.get("radar_lost_markets"), sort_keys=True)))
    L += ["", "| rule | signals | signal days | wins | mean cost | day mean | t | t cut | bootstrap lower | win-rate lower |"
          " Holm level | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in res["rules"]:
        c = s.get("checks") or {}
        L.append("| %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %.3f%% | %s |" % (
            s["rule"], s["signals"], s["signal_days"], s["wins"], _f(s["mean_cost"], "%.4f"), _f(s["mean_day"]),
            _f(s["t"], "%.2f"), _f(c.get("t_cut"), "%.2f"), _f(c.get("boot_lower")), _f(c.get("win_rate_lower"), "%.4f"),
            100 * s["holm_level"], s["verdict"]))
    L += ["", "No-price decision times (conditions held, no usable candle): %s." % json.dumps(res["no_price"], sort_keys=True),
          "", "## Descriptive only (never used to pick anything)", "", "```",
          json.dumps(res["descriptive"], indent=1, sort_keys=True), "```", "",
          "Leads for R and P on the same storms are not independent. Minute candles show the best bid and ask, not the"
          " size for sale: one contract is assumed to fill at the ask."]
    return "\n".join(L) + "\n"


def offsite_copy(path):
    base = os.environ.get("TRADEBOT_OFFSITE_BACKUPS") or os.path.join(os.path.expanduser("~"), "Documents",
                                                                       "tradebot_backups")
    dst = os.path.join(base, "plan11", "results", os.path.basename(path))
    if os.path.exists(dst) or not os.path.isdir(base):
        return None
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    except OSError as ex:
        return "off-folder copy of %s failed (%s)" % (os.path.basename(path), ex)
    return None


OFFSITE_NOTE = ("NOTE: after the next pull, the PC must copy research/results/plan11_result.json and .md to "
                "Documents\\tradebot_backups\\plan11\\results (plan section 8: a copy outside the tradebot folder).")


def score(now=None):
    jp, mp = result_paths()
    if os.path.exists(jp) or os.path.exists(mp):
        return None, "already scored (%s); the plan is scored once" % (jp if os.path.exists(jp) else mp)
    why = committed_guard("score") or require("score", need_markets=True)
    if why:
        return None, why
    mrec = load_markets()
    srec = load_signals()
    if srec is None:
        return None, "score refused: no intact signals file (run signals first)"
    if srec.get("radar_loss_reading") != RADAR_LOSS_READING:
        return None, "score refused: the signals used the radar loss reading %r, not %r" % (
            srec.get("radar_loss_reading"), RADAR_LOSS_READING)
    res = score_from(mrec["markets"], srec)
    res["scored"] = now_iso(now)
    res["markets_listed_at"] = mrec.get("listed_at")
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        f.write(result_md(res, mrec))
    os.replace(mp + ".tmp", mp)
    jsonio.save(jp, res)
    notes = [n for n in (offsite_copy(mp), offsite_copy(jp)) if n]
    return res, "scored: %s%s\n%s" % ("; ".join("%s %s" % (s["rule"], s["verdict"]) for s in res["rules"]),
                                      (" (" + "; ".join(notes) + ")") if notes else "", OFFSITE_NOTE)


def status():
    lines = ["PLAN11:"]
    lines.append("  identity: %s" % ("; ".join(identity_problems()) or "ok"))
    pr, _ = P._read_json(probe_path())
    lines.append("  probe: %s" % ("not run" if pr is None else ("passed" if pr.get("passed") else "FAILED")))
    lines.append("  radar loss reading applied: %s (strict counted as descriptive only)" % RADAR_LOSS_READING)
    mrec = load_markets()
    if mrec is None:
        lines.append("  markets: not listed")
    else:
        lines.append("  markets: %d included (%s)" % (len(mrec["markets"]), json.dumps(mrec.get("counts"), sort_keys=True)))
        left = completeness(mrec["markets"])
        lines.append("  still to fetch: %s" % json.dumps(left, sort_keys=True))
        if not left["radar_frames"]:
            radar = load_data(mrec["markets"])[2]
            lines.append("  markets losing radar, by reading: %s (applied: %s)" % (
                json.dumps(radar_loss_counts(mrec["markets"], radar), sort_keys=True), RADAR_LOSS_READING))
    lines.append("  signals: %s" % ("stored" if os.path.exists(signals_path()) else "not yet"))
    lines.append("  result: %s" % ("stored" if os.path.exists(result_paths()[0]) else "not yet"))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PLAN11: radar and the gauge against Kalshi's intraday price (research)")
    ap.add_argument("stage", choices=("freeze", "probe", "markets", "download", "signals", "score", "status"))
    ap.add_argument("--budget-minutes", type=float, default=None)
    ap.add_argument("--only", choices=("candles", "gauge", "radar"), default=None)
    a = ap.parse_args(argv)
    if a.stage == "status":
        print(status())
        return 0
    if a.stage == "download":
        ok, msg = download(a.budget_minutes, a.only)
        print(msg)
        return 0 if ("refused" not in msg) else 1
    fn = dict(freeze=freeze, probe=probe, markets=make_markets, signals=make_signals, score=score)[a.stage]
    rec, msg = fn()
    print(msg)
    if a.stage == "probe" and rec is not None and not rec.get("passed"):
        return 1
    return 0 if rec is not None else 1


if __name__ == "__main__":
    sys.exit(main())
