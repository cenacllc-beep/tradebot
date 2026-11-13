"""research/plan10.py (PLAN10): HRRR features, the fit and the single score, on synthetic grids and fake markets.
No network (sockets are blocked), no ecCodes, no HRRR file: the GRIB decoder and the HTTP session are fakes.
Checks:
- the pins: PLAN7's reused functions as PLAN8 pins them, PLAN10.md's frozen hash; Python 3.8 syntax;
- the fetcher: exactly one "APCP:surface:0-N hour acc fcst" line of this run, its byte range, the project's
  User-Agent on every request, a Range request answered 206 only, 404 = missing, retries, temporary files deleted;
- the features: 40.0 km by haversine on the 6,371.229 km sphere (inclusive), D >= 0.254 mm (inclusive), negative D as 0,
  A in inches at the nearest point; the request: quote rule, period, stations not in v3's table, one day-start hour,
  West Palm Beach's two codes, no price or result in the public files;
- the order: freeze once, request once, holdout refused before the fitted model, fit refused before the training
  download is complete, after holdout features exist, and a second time; the training download is resumable, counts
  missing fields and retries network errors; holdout prints counts only; the fit reads only committed public files;
- the score: a planted gain is confirmed ("lead ... PLAN10F only"), none in the null case (A not judged), "not
  testable" for a failed fit and for more than 10% missing fields; scored once, copied off the folder;
- identity: changed code stops every step until an amendment accepts it;
- the code review of 2026-11-13: body-read and ecCodes errors are Transient (a field counted missing after 3 runs),
  the committed-model check is always on, one holdout row's H, M and B, the veto on H, the bootstrap's direction and
  the five-test line on known series, the score refuses changed training rows, `check` prints no value;
- the workflow: manual only, five stages (check first), never Herbie, ecCodes pinned, commits only the features and
  the model.
python test_plan10.py WORK OUT"""
import os, sys, shutil, json, math, random, io, contextlib, socket, re, ast, glob
from datetime import date, timedelta
WORK, OUT = sys.argv[1], sys.argv[2]; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); os.chdir(OUT)
sys.path.insert(0, WORK); sys.path.insert(0, os.path.join(WORK, "research"))


def _no_net(*a, **k):
    raise AssertionError("network used in a test")


socket.socket.connect = _no_net
socket.create_connection = _no_net
import plan10 as P, plan8 as P8, plan7 as P7, backtest as B, weather   # noqa: E402,E401


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def refused(fn, *a, **k):
    try:
        quiet(fn, *a, **k)
    except P.Refused as ex:
        return str(ex)
    raise AssertionError("not refused: %s" % fn.__name__)


# ---------- 1. pins, frozen text, syntax ----------
assert P.PINNED_PLAN7 == P8.PINNED_PLAN7
assert P.plan7_identity(WORK) == P.PINNED_PLAN7
assert P.file_hash(os.path.join(WORK, "research", "PLAN10.md")) == P.PLAN_SHA256
src = open(os.path.join(WORK, "research", "plan10.py"), encoding="utf-8").read()
ast.parse(src, feature_version=(3, 8))
for bad in ("import eccodes", "import requests", "import numpy", "import xarray", "import cfgrib", "herbie"):
    assert not any(l.startswith(bad) for l in src.splitlines()), "top-level import: " + bad   # lazy imports only
assert P.USER_AGENT == "tradebot-paper-research/1.0"
print("pins ok")

# ---------- 2. the index and the fetcher ----------
rd = date(2025, 6, 30)
IDX = "\n".join(["1:0:d=2025063012:REFC:entire atmosphere:17 hour fcst:",
                 "2:1000:d=2025063012:APCP:surface:16-17 hour acc fcst:",
                 "3:2000:d=2025063012:APCP:surface:0-17 hour acc fcst:",
                 "4:3500:d=2025063012:APCP:surface:0-170 hour acc fcst:",
                 "5:4000:d=2025063012:WEASD:surface:0-17 hour acc fcst:"])
assert P.parse_idx(IDX, rd, 12, 17) == (2000, 3499)
last = IDX + "\n6:5000:d=2025063012:APCP:surface:0-18 hour acc fcst:"
assert P.parse_idx(last, rd, 12, 18) == (5000, None)
for text, why in ((IDX.replace("0-17 hour acc", "1-17 hour acc"), "0 lines"),
                  (IDX + "\n6:6000:d=2025063012:APCP:surface:0-17 hour acc fcst:", "2 lines")):
    try:
        P.parse_idx(text, rd, 12, 17); raise AssertionError("parsed")
    except P.Missing as ex:
        assert why in str(ex), ex
try:
    P.parse_idx(IDX, rd, 18, 17); raise AssertionError("wrong run accepted")
except P.Missing as ex:
    assert "run" in str(ex)
assert P.grib_url(rd, 12, 17) == "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20250630/conus/hrrr.t12z.wrfsfcf17.grib2"


class Resp(object):
    def __init__(self, code, body=b""):
        self.status_code, self.content, self.closed = code, body, False

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        self.closed = True


class Sess(object):
    def __init__(self, answers):
        self.headers = {"User-Agent": "python-requests/x"}
        self.answers, self.calls = list(answers), []

    def get(self, url, headers=None, timeout=None, stream=None):
        self.calls.append((url, dict(headers or {}), dict(self.headers)))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


s = Sess([Resp(206, b"GRIBxx"), Resp(404), Resp(500), Resp(500), Resp(206, b"ok"), Resp(200, b"whole file"),
          Resp(503), Resp(503), Resp(503), IOError("reset"), Resp(200, b"idx")])
sleeps = []
F = P.Fetcher(s, tries=3, sleep=sleeps.append)
assert F.get("u1", (10, 15)).content == b"GRIBxx"
assert F.get("u2", (10, None)) is None                                   # 404: not there
assert F.get("u3", (1, 2)).content == b"ok" and len(sleeps) == 2         # two retries
try:
    F.get("u4", (1, 2)); raise AssertionError("200 for a range accepted")
except P.Transient as ex:
    assert "ignored the byte range" in str(ex)
try:
    F.get("u5", (1, 2)); raise AssertionError("503 accepted")
except P.Transient:
    pass
assert F.get("u6").content == b"idx"                                     # after a connection error
for url, h, sh in s.calls:
    assert h["User-Agent"] == "tradebot-paper-research/1.0" and sh["User-Agent"] == "tradebot-paper-research/1.0", (h, sh)
    assert not any("@" in str(v) for v in list(h.values()) + list(sh.values()))
assert s.calls[0][1]["Range"] == "bytes=10-15" and s.calls[1][1]["Range"] == "bytes=10-" and "Range" not in s.calls[-1][1]

seen = {}


def fake_decode(path, run_day, cycle, fh):
    seen["path"], seen["bytes"] = path, open(path, "rb").read()
    return dict(values=[0.0], missing_value=None, sig={"centre": 7}, grid="g", latlon=lambda: ([0.0], [0.0]))


idx = IDX.encode()
s2 = Sess([Resp(200, idx), Resp(206, b"G" * 1500)])
got = P.HRRR(P.Fetcher(s2, sleep=lambda x: None), tmpdir=OUT, decoder=fake_decode).field(rd, 12, 17)
assert seen["bytes"] == b"G" * 1500 and not os.path.exists(seen["path"]), "temporary GRIB file not deleted"
assert s2.calls[0][0].endswith("wrfsfcf17.grib2.idx") and s2.calls[1][1]["Range"] == "bytes=2000-3499"
s3 = Sess([Resp(200, idx), Resp(206, b"G" * 10)])
try:
    P.HRRR(P.Fetcher(s3, sleep=lambda x: None), tmpdir=OUT, decoder=fake_decode).field(rd, 12, 17)
    raise AssertionError("short body accepted")
except P.Transient:
    pass
assert not [f for f in os.listdir(OUT) if f.endswith(".grib2")], "temporary GRIB files left behind"
# a network error while reading a body is Transient, the response is closed and no temporary file is left
import requests   # only to prove its body-read errors are OSErrors, which plan10 maps to Transient
for E in (requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
    assert issubclass(E, OSError), E


class BadBody(Resp):
    def iter_content(self, n):
        yield b"G" * 100
        raise requests.exceptions.ChunkedEncodingError("cut off")


class BadIdx(Resp):
    @property
    def content(self):
        raise requests.exceptions.ReadTimeout("slow")

    @content.setter
    def content(self, v):
        pass


bb = BadBody(206, b"")
s5 = Sess([Resp(200, idx), bb])
try:
    P.HRRR(P.Fetcher(s5, sleep=lambda x: None), tmpdir=OUT, decoder=fake_decode).field(rd, 12, 17)
    raise AssertionError("cut-off body accepted")
except P.Transient as ex:
    assert "reading the GRIB message failed" in str(ex)
assert bb.closed and not [f for f in os.listdir(OUT) if f.endswith(".grib2")]
bi = BadIdx(200)
try:
    P.HRRR(P.Fetcher(Sess([bi]), sleep=lambda x: None), decoder=fake_decode).field(rd, 12, 17)
    raise AssertionError("index read error accepted")
except P.Transient:
    assert bi.closed
big = Resp(206, b"G" * 1500)
P.MAX_FIELD_BYTES, keep_max = 1000, P.MAX_FIELD_BYTES
try:
    P.HRRR(P.Fetcher(Sess([Resp(200, idx), big]), sleep=lambda x: None), tmpdir=OUT, decoder=fake_decode).field(rd, 12, 17)
    raise AssertionError("oversized message accepted")
except P.Transient:
    assert big.closed
P.MAX_FIELD_BYTES = keep_max


# decode_grib against a fake ecCodes module: its errors are Transient, the wrong message is Missing, keys are checked
class CodesInternalError(Exception):
    pass


class FakeEc(object):
    CodesInternalError = CodesInternalError

    def __init__(self, keys, n_msgs=1, fail=False):
        self.keys, self.n, self.fail, self.released = keys, n_msgs, fail, []

    def codes_grib_new_from_file(self, f):
        if self.fail:
            raise CodesInternalError("bad GRIB")
        if self.n:
            self.n -= 1
            return 1 + self.n
        return None

    def codes_get(self, gid, k, ktype=None):
        if k not in self.keys:
            raise CodesInternalError("no key " + k)
        if k == "typeOfFirstFixedSurface" and ktype is not int:
            return "sfc"   # as real ecCodes does: coded keys come back as text unless read as numbers (2026-11-13)
        return self.keys[k]

    def codes_get_values(self, gid):
        return [0.0, 1.0]

    def codes_get_array(self, gid, k):
        class L(list):
            def tolist(self):
                return list(self)
        return L([40.0, 40.1])

    def codes_release(self, gid):
        self.released.append(gid)

    def codes_get_api_version(self):
        return "fake"


good = dict(discipline=0, parameterCategory=1, parameterNumber=8, typeOfFirstFixedSurface=1, dataDate=20250630,
            dataTime=1200, stepRange="0-17", centre=7, Ni=2, Nj=1, bitmapPresent=0)
gf = os.path.join(OUT, "fake.grib2")
open(gf, "wb").write(b"GRIB")
for ec, want in ((FakeEc(good), "ok"), (FakeEc(dict(good, stepRange="16-17")), P.Missing),
                 (FakeEc(good, n_msgs=2), P.Missing), (FakeEc(good, fail=True), P.Transient)):
    sys.modules["eccodes"] = ec
    try:
        got = P.decode_grib(gf, rd, 12, 17)
        assert want == "ok", want
        assert got["sig"]["centre"] == 7 and got["sig"]["subCentre"] is None and got["missing_value"] is None
        assert got["latlon"]() == ([40.0, 40.1], [40.0, 40.1]) and ec.released
    except (P.Missing, P.Transient) as ex:
        assert want != "ok" and isinstance(ex, want), (want, ex)
del sys.modules["eccodes"]
s4 = Sess([Resp(404)])
try:
    P.HRRR(P.Fetcher(s4, sleep=lambda x: None), decoder=fake_decode).field(rd, 12, 17); raise AssertionError
except P.Missing as ex:
    assert "index" in str(ex)
print("fetcher ok")

# ---------- 3. features ----------
assert abs(P.haversine_km(40, -100, 41, -100) - 6371.229 * math.pi / 180) < 1e-9
st0 = {"KX": dict(lat=40.0, lon=-100.0)}
deg = 180.0 / (math.pi * 6371.229)
lats = [40.0 + 39.9999 * deg, 40.0 + 40.0001 * deg, 40.0 - 3.0 * deg, 40.0, 40.0 - 20 * deg]
lons = [-100.0, -100.0, -100.0, 260.05, -100.0]   # 0..360 longitudes work too
g = P.geometry(lats, lons, st0)["KX"]
assert g["idx"] == [0, 2, 3, 4] and g["near"] == 2 and abs(g["near_km"] - 3.0) < 1e-6, g
start = [1.0, 9.0, 0.0, 0.0, 2.0]
end = [1.254, 9.0, 0.2539, 0.0, 1.9]   # +0.254 (counts), far point (ignored), 0.2539 (not), 0, negative -> 0
(Fv, Av), why = P.station_features(start, end, g)
assert why is None and abs(Fv - 1 / 4.0) < 1e-12 and abs(Av - 0.2539 / 25.4) < 1e-12, (Fv, Av)
assert P.station_features([9999.0] * 5, end, g, 9999.0)[0] is None
assert P.station_features(start, end, dict(idx=[], n=0, near=None))[0] is None
assert P.fh_pair(12, 5) == (17, 41) and P.fh_pair(18, 8) == (14, 38) and max(P.fh_pair(12, 8)) <= 48
assert abs(P.H_of(dict(a=0.0, b=1.0, c=0.0), 0.0, 0.0) - 0.02) < 1e-12   # F clipped at 0.02
assert P.H_of(dict(a=-50.0, b=1.0, c=0.0), 0.5, 0.0) == 0.01 and P.H_of(dict(a=50.0, b=1.0, c=0.0), 0.5, 0.0) == 0.99
print("features ok")

# ---------- fake world ----------
TAB = P.rain_table()
KEYS = {"KNYC": "NYC", "KORD": "CHI", "KDEN": "DEN", "KSEA": "SEA", "KATL": "ATL", "KAUS": "AUS", "KPHX": "PHX",
        "KLAX": "LAX", "KBOS": "BOS", "KMIA": "MIA"}
HOURS = {"KNYC": 5, "KORD": 6, "KDEN": 7, "KSEA": 8, "KATL": 5, "KAUS": 6, "KPHX": 7, "KLAX": 8, "KBOS": 5, "KMIA": 5}
P.TRAIN = (date(2025, 7, 1), date(2025, 8, 31))
HDAYS = [date(2026, 7, 15) + timedelta(days=i) for i in range(30)]
rng = random.Random(10)
TRUTH = {}
for st in KEYS:
    d = date(2025, 7, 1)
    while d <= date(2026, 10, 12):
        TRUTH[(st, d.isoformat())] = 1 if rng.random() < 0.35 else 0
        d += timedelta(days=1)


def utc(d, h):
    return P.utc_midnight(d) + h * 3600


def tick(d, key):
    return "KXRAIN-%s-%s" % (d.strftime("%y%b%d").upper(), key)


def write_world(data, prices="noise", extra=True):
    os.makedirs(os.path.join(data, "cli"), exist_ok=True)
    r = random.Random(prices)
    lines = []
    for d in HDAYS:
        for st, key in sorted(KEYS.items()):
            y = TRUTH[(st, d.isoformat())]
            if prices == "noise":
                M = 0.3 + r.uniform(-0.1, 0.1)
            else:   # a very good price
                M = 0.93 if y else 0.07
            bid, ask = round(M - 0.01, 2), round(M + 0.01, 2)
            lines.append(dict(ticker=tick(d, key), day=d.isoformat(), station=st, result="yes" if y else "no",
                              scan_bid=bid, scan_ask=ask, start_ts=utc(d, HOURS[st]), lo_after=bid - 0.02, hi_after=ask + 0.02))
    if extra:
        for i in range(3):   # a station outside v3's table, and quote failures, and a market outside the period
            d = HDAYS[i]
            lines.append(dict(ticker=tick(d, "XYZ"), day=d.isoformat(), station="KXYZ", result="no", scan_bid=0.1,
                              scan_ask=0.12, start_ts=utc(d, 5), lo_after=None, hi_after=None))
        lines.append(dict(lines[0], ticker=tick(HDAYS[0], "ZZ1"), scan_bid=0.1, scan_ask=0.3))
        lines.append(dict(lines[0], ticker="KXRAIN-26OCT13-NYC", day="2026-10-13"))
        lines.append(lines[5])   # a duplicate line
    with open(os.path.join(data, "kalshi_rain.jsonl"), "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    for st in KEYS:
        recs = []
        for (s_, d), y in sorted(TRUTH.items()):
            if s_ == st:
                recs.append(dict(valid=d, precip=("0.%02d" % (1 + int(d[-2:]))) if y else ["0.00", "T", "M"][int(d[-1]) % 3]))
        json.dump(recs, open(os.path.join(data, "cli", "%s_2025.json" % st), "w"))


class FakeHRRR(object):
    """Blocks of grid points around each station; APCP accumulates 0.5 mm before the day and `amt` during it."""

    def __init__(self, informative=True, missing=(), transient=None):
        self.lats, self.lons, self.owner = [], [], []
        for st in sorted(KEYS):
            code, la, lo = TAB[st]
            for i in range(-5, 6):
                for j in range(-5, 6):
                    self.lats.append(la + 0.06 * i)
                    self.lons.append(lo + 0.06 * j / math.cos(math.radians(la)))
                    self.owner.append(st)
        u = random.Random(3)
        self.u = [u.random() for _ in self.owner]
        self.informative, self.missing, self.transient = informative, set(missing), dict(transient or {})
        self.calls = 0

    def frac(self, st, day):
        r = random.Random("%s%s%s" % (st, day, self.informative))
        if not self.informative and day >= "2026":
            return r.uniform(0, 1)
        return r.uniform(0.25, 1.0) if TRUTH[(st, day)] else r.uniform(0.0, 0.4)

    def field(self, run_day, cycle, fh):
        self.calls += 1
        key = (run_day, cycle, fh)
        if key in self.missing:
            raise P.Missing("not in the fake archive")
        if self.transient.get(key, 0) > 0:
            self.transient[key] -= 1
            raise P.Transient("fake network error")
        day = (run_day + timedelta(days=1)).isoformat()
        fr = {st: self.frac(st, day) for st in KEYS}
        vals = []
        for i, st in enumerate(self.owner):
            fs = P.fh_pair(cycle, HOURS[st])[0]
            amt = 2.0 if self.u[i] < fr[st] else 0.0
            vals.append(0.5 * min(fh, fs) / float(fs) + amt * min(max((fh - fs) / 24.0, 0.0), 1.0))
        return dict(values=vals, missing_value=None, sig=dict(centre=7, generatingProcessIdentifier=83), grid="fake",
                    latlon=lambda: (self.lats, self.lons))


def scenario(name, prices="noise", extra=True):
    d = os.path.join(OUT, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "res"))
    P.RESULTS, P.DATA = os.path.join(d, "res"), os.path.join(d, "data")
    os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
    write_world(P.DATA, prices, extra)
    return d


# ---------- 4. CLI rule and the request ----------
scenario("req")
B.DATA = P.DATA
assert P.load_cli() == B.load_cli(), "plan10's climate-report rule differs from research/backtest.py's"
req, outs, passed = P.build_request()
c = req["counts"]
assert c["outside_period"] == 1 and c["quote"] == 1 and c["duplicate_lines"] == 1 and c["passed_quote"] == 303, c
assert req["excluded_stations"] == {"KXYZ": dict(markets=3, reason="not in v3's rain table")}
assert c["n0"] == 300 and abs(c["excluded_share"] - 3 / 303.0) < 1e-12
assert req["stations"]["KNYC"]["start_hour"] == 5 and req["stations"]["KSEA"]["lat"] == TAB["KSEA"][1]
txt = json.dumps(req) + json.dumps(outs)
assert "scan_bid" not in txt and "result" not in txt and '"yes"' not in txt, "price or result in the public files"
assert all(P.TRAIN[0].isoformat() <= d <= P.TRAIN[1].isoformat() for o in outs["outcomes"].values() for d in o)
d0 = "2025-07-0"
assert any(v == 1 for k, v in outs["outcomes"]["KNYC"].items()) and len(outs["outcomes"]["KNYC"]) == 62
# one day-start hour per station; West Palm Beach's two codes
lines = [json.loads(l) for l in open(os.path.join(P.DATA, "kalshi_rain.jsonl"))]
bad = [dict(l, start_ts=l["start_ts"] + 3600) if l["station"] == "KSEA" and l["day"] == "2026-07-20" else l for l in lines]
wpb = [dict(ticker=tick(d, "WPB"), day=d.isoformat(), station="KDJT", result="no", scan_bid=0.1, scan_ask=0.12,
            start_ts=utc(d, 5)) for d in HDAYS[:2]]
with open(os.path.join(P.DATA, "kalshi_rain.jsonl"), "w") as f:
    for l in bad + wpb:
        f.write(json.dumps(l) + "\n")
json.dump([dict(valid="2025-07-01", precip="0.10"), dict(valid="2025-07-02", precip="0.00")],
          open(os.path.join(P.DATA, "cli", "KPBI_2025.json"), "w"))
json.dump([dict(valid="2025-07-02", precip="0.20"), dict(valid="2025-07-03", precip="T")],
          open(os.path.join(P.DATA, "cli", "KDJT_2026.json"), "w"))
req2, outs2, _ = P.build_request()
assert "KSEA" in req2["excluded_stations"] and "day-start" in req2["excluded_stations"]["KSEA"]["reason"]
assert req2["counts"]["excluded_share"] > 0.10   # SEA + XYZ: above 10%, so the verdict would be "not testable"
assert outs2["outcomes"]["KDJT"] == {"2025-07-01": 1, "2025-07-02": 1, "2025-07-03": 0}, outs2["outcomes"]["KDJT"]
assert req2["counts"]["train_alias_days"] == 1 and req2["counts"]["train_alias_conflicts"] == 1
# a holdout market under West Palm Beach's old code counts under KDJT, not as an excluded station (2026-11-13)
old = [dict(w, ticker=w["ticker"] + "P", station="KPBI") for w in wpb[:1]]
with open(os.path.join(P.DATA, "kalshi_rain.jsonl"), "w") as f:
    for l in bad + wpb + old:
        f.write(json.dumps(l) + "\n")
req3 = P.build_request()[0]
assert "KPBI" not in req3["excluded_stations"] and req3["stations"]["KDJT"]["markets"] == len(wpb) + 1, req3["stations"]["KDJT"]
assert req3["counts"]["holdout_alias_markets"] == 1
assert P.home_station("KPBI", {"KDJT": 1}) == "KDJT" and P.home_station("KPBI", {"KPBI": 1}) == "KPBI"
assert P.home_station("KXYZ", {"KDJT": 1}) == "KXYZ"
with open(os.path.join(P.DATA, "kalshi_rain.jsonl"), "w") as f:
    for l in bad + wpb:
        f.write(json.dumps(l) + "\n")
print("request ok")

# ---------- 5. the order of the steps, on the edge world ----------
base = scenario("edge")
assert "no identity record" in refused(P.make_request)
rec, msg = quiet(P.freeze)[0]
assert rec and "frozen" in msg and os.path.exists(P.offsite_path(P.rpath(P.IDENTITY)))
assert quiet(P.freeze)[0][0] is None
quiet(P.make_request)
assert "already exists" in refused(P.make_request)
assert "no fitted model" in refused(P.download, "holdout", source=FakeHRRR())
assert "not complete" in refused(P.fit)
# a time budget stops cleanly; a missing field is counted; a network error is retried on the next run
first = date(2025, 6, 30)
src = FakeHRRR(missing={(first, 12, 17)}, transient={(first + timedelta(days=1), 18, 12): 1})
tk = [0.0]


def clock():
    tk[0] += 40.0
    return tk[0]


m1, out1 = quiet(P.download, "train", source=src, budget_minutes=2, clock=clock)
assert "stopped at the time budget" in m1 and "1 fields missing" in m1, m1
m2, _ = quiet(P.download, "train", source=src)
assert "(incomplete)" in m2 and "1 units with network errors" in m2, m2
m2, _ = quiet(P.download, "train", source=src)   # the next dispatch tries that unit again
assert re.search(r"(\d+) of \1 units done;", m2) and "1 fields missing" in m2, m2
lg = json.load(open(P.log_path("train")))
assert lg["attempts"] == {"2025-07-01 18Z": 1} and lg["missing"] == {"2025-06-30 12Z": {"17": "missing: not in the fake archive"}}
nyc = json.load(open(os.path.join(P.feat_dir("train"), "KNYC.json")))
assert nyc["days"]["2025-07-01"]["12"] is None and nyc["days"]["2025-07-01"]["18"] is not None   # NYC's 12Z start hour is 17
assert json.load(open(os.path.join(P.feat_dir("train"), "KORD.json")))["days"]["2025-07-01"]["12"] is not None
calls = src.calls
m3, _ = quiet(P.download, "train", source=src)
assert src.calls == calls, "a finished unit was downloaded again"
# the fit reads only the committed public files: research/data is not there on the runner
data_saved = P.DATA
P.DATA = os.path.join(base, "no_data_on_the_runner")
model, fmsg = quiet(P.fit)[0]
assert model and model["b"] > 0 and model["station_days"] == 616, (fmsg, model and model["station_days"])
assert model["left_out_missing_fields"] == 4 and model["rows_sha256"] and model["request_sha256"] == req["sha256"]
assert os.path.exists(P.offsite_path(P.rpath(P.MODEL)))
assert "fitted once" in refused(P.fit)
assert "fixed" in refused(P.download, "train", source=src)
P.DATA = data_saved
try:
    with contextlib.redirect_stderr(io.StringIO()):
        quiet(P.main, ["holdout-download", "--require-committed"])
    raise AssertionError("the old switch still parses")
except SystemExit:
    pass
snap = os.path.join(OUT, "after_fit")
shutil.copytree(base, snap)
assert "not committed" in refused(P.download, "holdout", source=FakeHRRR())   # always on, outside a git working copy
P._TEST_SKIP_GIT_CHECK = True   # the fake worlds below are not git working copies
hm, hout = quiet(P.download, "holdout", source=FakeHRRR())
assert "60 of 60 units done" in hm and "300 station-days" in hm, hm
assert not re.search(r"\d\.\d", hout + hm), "a holdout value reached the log: " + hout + hm
_, _, passed_e = P.build_request()
rows_e, _ = P.holdout_rows(json.load(open(P.rpath(P.REQUEST))), model, passed_e, {})
r0 = [r for r in rows_e if r["ticker"] == tick(HDAYS[3], "DEN")][0]
line = [x for x in passed_e if x["ticker"] == r0["ticker"]][0]
fa = P.combine(json.load(open(os.path.join(P.feat_dir("holdout"), "KDEN.json")))["days"][HDAYS[3].isoformat()])
assert r0["M"] == (line["scan_bid"] + line["scan_ask"]) / 2 and r0["H"] == P.H_of(model, fa[0], fa[1])
assert r0["B"] == 0.5 * r0["H"] + 0.5 * r0["M"] and (r0["F"], r0["A"]) == fa
res, verdict = quiet(P.score)[0]
assert verdict == P.VERDICT_LEAD, (verdict, res.get("B"))
assert res["T"]["vetoed_markets"] == len(rows_e) - len(P.t_rows(rows_e))
assert res["B"]["confirmed"] and res["B"]["mean"] < 0 and "five_test" in res["B"] and res["A"].get("reading")
assert res["scored_markets"] == 300 and res["n0"] == 300 and res["cli_vs_kalshi"] == dict(checked=300, agree=300)
assert res["T"]["taker"]["n"] >= 1 and "vetoed_markets" in res["T"] and res["N"]["markets"] == 0
assert list(res["data_checks"]["signatures"].values())[0]["fields"] > 0
assert os.path.exists(P.offsite_path(P.rpath(P.SCORE))) and os.path.exists(P.rpath(P.SCORE)[:-5] + ".md")
assert "scored once" in refused(P.score)
os.remove(P.rpath(P.SCORE))
assert "already scored" in refused(P.score)   # the off-folder copy still counts
# fit refused once any holdout feature exists (copy without the model)
x = os.path.join(OUT, "leak")
shutil.copytree(base, x)
P.RESULTS = os.path.join(x, "res"); os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(x, "off2")
os.remove(P.rpath(P.MODEL))
assert "holdout features exist" in refused(P.fit)
print("edge ok:", verdict)

# ---------- 6. the null world: a very good price, an uninformative HRRR in the holdout ----------
d = os.path.join(OUT, "null")
shutil.copytree(snap, d)
P.RESULTS, P.DATA = os.path.join(d, "res"), os.path.join(d, "data")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
write_world(P.DATA, prices="good")   # same markets, days and outcomes: the same request
quiet(P.download, "holdout", source=FakeHRRR(informative=False))
runs = {}   # a fake airport forecast (research/backtest.py's NBS format) for the first 20 days
for day in HDAYS[:20]:
    nx = day + timedelta(days=1)
    for st in KEYS:
        p = 60.0 if TRUTH[(st, day.isoformat())] else 10.0
        runs[(st, day - timedelta(days=1))] = {k: (p, 5.0 if p > 50 else 0.0) for k in (
            "%s 12:00" % day, "%s 18:00" % day, "%s 00:00" % nx, "%s 06:00" % nx)}
res, verdict = quiet(P.score, runs=runs, coef=[-2.0, 1.0, 0.5])[0]
assert verdict == P.VERDICT_NONE and not res["B"]["confirmed"] and "not_judged" in res["A"], res["B"]
assert res["N"]["markets"] == 200 and res["N"]["days"] == 20 and res["N"]["mean"] is not None and res["N"]["corr"] is not None
assert res["C_blend_own_set"]["markets"] == 200 and "five_test" in res["B"]
print("null ok:", res["B"]["reading"])

# ---------- 7. not testable: more than 10% of N0 misses a field ----------
d = os.path.join(OUT, "missing")
shutil.copytree(snap, d)
P.RESULTS, P.DATA = os.path.join(d, "res"), os.path.join(d, "data")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
gone = {(day - timedelta(days=1), 18, P.fh_pair(18, 5)[1]) for day in HDAYS[:8]}   # 8 days of the 5 o'clock stations
quiet(P.download, "holdout", source=FakeHRRR(missing=gone))
res, verdict = quiet(P.score)[0]
assert verdict.startswith("not testable") and "miss a field" in verdict and len(res["left_out_missing_fields"]) == 32, verdict
# and a request that changed under the score is refused
d = os.path.join(OUT, "changed")
shutil.copytree(snap, d)
P.RESULTS, P.DATA = os.path.join(d, "res"), os.path.join(d, "data")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
quiet(P.download, "holdout", source=FakeHRRR())
with open(os.path.join(P.DATA, "kalshi_rain.jsonl"), "a") as f:
    f.write(json.dumps(dict(ticker=tick(HDAYS[0], "PIT"), day=HDAYS[0].isoformat(), station="KPIT", result="no",
                            scan_bid=0.1, scan_ask=0.12, start_ts=utc(HDAYS[0], 5))) + "\n")
assert "no longer gives the committed request" in refused(P.score)
d = os.path.join(OUT, "trainchanged")
shutil.copytree(snap, d)
P.RESULTS, P.DATA = os.path.join(d, "res"), os.path.join(d, "data")
os.environ["TRADEBOT_OFFSITE_BACKUPS"] = os.path.join(d, "off")
quiet(P.download, "holdout", source=FakeHRRR())
fp = os.path.join(P.feat_dir("train"), "KDEN.json")
f = json.load(open(fp))
f["days"]["2025-07-10"]["12"][0] = 0.123
json.dump(f, open(fp, "w"))
assert "rows_sha256" in refused(P.score)
chk = P.check(source=FakeHRRR(), out=lambda *a: None)
assert "decoded" in chk and "1210 grid points" in chk and not re.search(r"\d\.\d", chk), chk
print("not testable ok")

# ---------- 7b. network errors on three runs: the field is counted missing ----------
scenario("errors", extra=False)
quiet(P.freeze); quiet(P.make_request)
bad_key = (date(2025, 7, 9), 18, 13)
srcx = FakeHRRR(transient={bad_key: 99})
msgs = [quiet(P.download, "train", source=srcx)[0] for _ in range(3)]
assert "(incomplete)" in msgs[0] and "(incomplete)" in msgs[1] and "1 fields missing" in msgs[2] and "(incomplete)" not in msgs[2] and "1 units with network errors" in msgs[2], msgs
assert "error after 3 attempts" in json.load(open(P.log_path("train")))["missing"]["2025-07-09 18Z"]["13"]
print("errors ok")

# ---------- 8. a failed fit: frozen as failed, the holdout is refused, the score reads "not testable" ----------
scenario("failed", extra=False)
for k in list(TRUTH):
    if k[1] < "2026":
        TRUTH[k] = 0   # every training day dry: the likelihood has no maximum
quiet(P.freeze); quiet(P.make_request)
quiet(P.download, "train", source=FakeHRRR())
model, fmsg = quiet(P.fit)[0]
assert model is None and "not testable" in fmsg and "failed" in json.load(open(P.rpath(P.MODEL)))
assert "fit failed" in refused(P.download, "holdout", source=FakeHRRR())
res, verdict = quiet(P.score)[0]
assert verdict.startswith("not testable: the fit failed"), verdict
print("failed fit ok")

# ---------- 8b. the statistic's direction, the bootstrap and the five-test line on known series ----------
def series_o(diffs):
    o, order = [], {}
    for i, dd in enumerate(diffs):
        day = date(2026, 7, 1) + timedelta(days=i)
        t = tick(day, "NYC")
        o.append((t, math.sqrt(0.25 + dd), 0.5, "no"))   # Brier(X) - Brier(M) = dd
        order[t.split("-")[1]] = day.isoformat()
    return o, order


n = 20
alt = [0.01 if i % 2 else -0.01 for i in range(n)]
se1 = (sum(x * x for x in alt) / (n - 1) / n) ** 0.5
strong, _ = series_o([-0.05 + e for e in alt])
mid, morder = series_o([-2.5 * se1 + e for e in alt])   # t = -2.5: past the 2.5% line, short of the 0.5% line
pos, _ = series_o([0.05 + e for e in alt])
order = morder
j = P.judge(strong, order, "better", "worse", five=True)
assert j["reading"] == "better" and j["confirmed"] and j["boot"][0] < j["boot"][1] < 0 and j["five_test"]["passes"], j
assert j["five_test"]["t_needed"] < -2.0 and j["mean"] < 0
j = P.judge(mid, order, "better", "worse", five=True)
assert abs(j["t"] + 2.5) < 1e-6 and j["reading"] == "better" and not j["five_test"]["passes"], j
j = P.judge(pos, order, "better", "worse", five=True)
assert j["reading"] == "worse" and not j["confirmed"] and not j["five_test"]["passes"], j
keep_bi = P.P7.boot_interval
try:   # the bootstrap's upper bound decides with the t reading: both must be below zero
    P.P7.boot_interval = lambda ms, low=0.025, high=0.975: (-0.02, 0.0)
    assert not P.judge(strong, order, "better", "worse")["confirmed"]
    P.P7.boot_interval = lambda ms, low=0.025, high=0.975: (-0.02, -1e-9)
    assert P.judge(strong, order, "better", "worse")["confirmed"]
    assert not P.judge(series_o([e for e in alt])[0], order, "better", "worse")["confirmed"]   # t not past the line
    assert not P.judge(pos, order, "better", "worse")["confirmed"]
    P.P7.boot_interval = lambda ms, low=0.025, high=0.975: (-0.02, -1e-9) if high > 0.99 else (-0.02, -0.01)
    assert P.judge(mid, order, "better", "worse", five=True)["five_test"]["boot_high"] == -1e-9
finally:
    P.P7.boot_interval = keep_bi
vrows = [dict(H=0.9, M=0.5, B=0.7), dict(H=0.75, M=0.5, B=0.625), dict(H=0.2, M=0.5, B=0.35), dict(H=0.19, M=0.5, B=0.345)]
assert P.t_rows(vrows) == vrows[1:3], "the veto must use H (|H - M| > 0.30), not the blend"
print("statistics ok")

# ---------- 9. identity: changed code stops every step until an amendment accepts it ----------
root = os.path.join(OUT, "root")
for f in P.FROZEN_FILES + ("research/plan7.py",):
    os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
    shutil.copy2(os.path.join(WORK, f), os.path.join(root, f))
assert P.identity_problems(root) == []
with open(os.path.join(root, "research", "plan10.py"), "a") as f:
    f.write("\n# changed\n")
bad = P.identity_problems(root)
assert bad == ["file:research/plan10.py"], bad
assert "amendment" in refused(P.fit, root=root)
P.save_json(P.rpath(P.AMEND), dict(amendments=[dict(name="file:research/plan10.py",
                                                    sha256=P.identity(root)["file:research/plan10.py"], approved="test")]))
assert P.identity_problems(root) == []
open(P.rpath(P.AMEND), "w").write("{damaged")
assert P.identity_problems(root) == ["file:research/plan10.py"]
open(P.rpath(P.IDENTITY), "w").write("{damaged")
assert "damaged" in P.identity_problems()[0]
print("identity ok")

# ---------- 10. the workflow ----------
wf = open(os.path.join(WORK, "cloud", "workflows", "plan10.yml"), encoding="utf-8").read()
try:
    import yaml
    y = yaml.safe_load(wf)
    on = y.get("on", y.get(True))
    assert list(on) == ["workflow_dispatch"], on
    assert on["workflow_dispatch"]["inputs"]["stage"]["options"] == ["check", "train-download", "fit", "holdout-download", "score"]
except ImportError:
    pass
assert "schedule" not in wf and "herbie" not in wf.lower() and "eccodes==2.50.0 eccodeslib==2.50.0.33" in wf
assert "--require-committed" not in wf and "plan10.py check" in wf and "plan10_model.json exists" in wf and "runs once on the PC" in wf
assert "grep -Ev '^(research/results/plan10_features/|research/results/plan10_model\\.json$)'" in wf and "grib2?|idx|nc" in wf
assert "research/data" not in [l.split()[-1] for l in wf.splitlines() if "git add" in l]
print("workflow ok")
print("PASS")
