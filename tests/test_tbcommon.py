"""tbcommon, the shared research helpers, on fakes (no network): the HTTP client's retry, Retry-After, rate-limit,
error and session behaviour; tolerant parsing; Wilson and clustered SE against the formulas they replaced; atomic and
crash-tolerant JSON files. python test_tbcommon.py WORK OUT"""
import os, sys, math, types, shutil, random
WORK, OUT = sys.argv[1], sys.argv[2]
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
sys.path.insert(0, WORK)
from tbcommon.httpclient import JsonClient, USER_AGENT
from tbcommon.parse import num, px, rts, cents
from tbcommon.stats import wilson, cl_mean_se
from tbcommon import jsonio

# ---- http: a fake `requests` module with scripted answers and a fake clock ----
class R:
    def __init__(self, status, body=None, headers=None): self.status_code = status; self._b = body or {}; self.headers = headers or {}
    def json(self): return self._b
class NetErr(Exception): pass
def fake_requests(script, with_session=True):
    calls = []
    def get(url, params=None, headers=None, timeout=None):
        calls.append(dict(url=url, params=params, headers=headers, timeout=timeout))
        x = script.pop(0)
        if isinstance(x, Exception): raise x
        return x
    mod = types.SimpleNamespace(get=get, RequestException=NetErr)
    if with_session:
        class Session:
            def __init__(self): self.headers = {}
            def get(self, *a, **k): return get(*a, **k)
        mod.Session = Session
    return mod, calls
class Clock:
    def __init__(self): self.t = 1000.0; self.slept = []
    def time(self): return self.t
    def sleep(self, s): self.slept.append(round(s, 6)); self.t += s
def client(script, **kw):
    mod, calls = fake_requests(script, kw.pop("with_session", True)); sys.modules["requests"] = mod
    ck = Clock(); c = JsonClient("https://x/api", sleep=ck.sleep, clock=ck.time, **kw); return c, calls, ck
c, calls, ck = client([R(200, {"a": 1})], pause_after=0.12)
assert c.get("/m", {"k": 1}) == {"a": 1} and calls[0]["url"] == "https://x/api/m" and calls[0]["params"] == {"k": 1}
assert calls[0]["headers"]["User-Agent"] == USER_AGENT and calls[0]["timeout"] == 30 and ck.slept == [0.12] and c.requests == 1
# 429 with Retry-After, 503 without, a network error, then success: waits 7, then the backoff for attempts 1 and 2
c, calls, ck = client([R(429, headers={"Retry-After": "7"}), R(503), NetErr("reset"), R(200, {"ok": 1})], backoff_base=3.0, backoff_cap=60.0)
assert c.get("/m") == {"ok": 1} and ck.slept == [7.0, 6.0, 12.0] and len(calls) == 4, ck.slept
# a non-numeric Retry-After falls back to the backoff (one old copy crashed here)
c, calls, ck = client([R(429, headers={"Retry-After": "Wed, 21 Oct"}), R(200, {})], backoff_base=2.0, backoff_cap=None)
assert c.get("/m") == {} and ck.slept == [2.0]
# other statuses fail at once; too many failures give up
c, calls, ck = client([R(404)])
try: c.get("/missing"); raise SystemExit("404 not raised")
except RuntimeError as ex: assert str(ex) == "HTTP 404 /missing" and len(calls) == 1
c, calls, ck = client([R(500)] * 3, tries=3, backoff_base=3.0, backoff_cap=5.0)
try: c.get("/m"); raise SystemExit("did not give up")
except RuntimeError as ex: assert str(ex) == "giving up on /m" and ck.slept == [3.0, 5.0, 5.0], ck.slept
c, calls, ck = client([R(500)], tries=5)
try: c.get("/m", tries=1); raise SystemExit("per-call tries ignored")   # a per-call override of tries
except RuntimeError: assert len(calls) == 1
# rate limit: requests are spaced min_gap apart on the client's clock
c, calls, ck = client([R(200, {})] * 3, min_gap=0.125)
for _ in range(3): c.get("/m")
assert ck.slept == [0.125, 0.125], ck.slept
# a `requests` without Session (as some tests fake it) still works
c, calls, ck = client([R(200, {"x": 2})], with_session=False)
assert c.get("/m") == {"x": 2}
# ---- parse ----
assert num("0.45") == 0.45 and num("") is None and num(None) is None and num("x") is None and num(3) == 3.0
assert px({"yes_bid_dollars": "0.4500"}, "yes_bid") == 0.45 and px({"yes_bid": 45}, "yes_bid") == 0.45 and px({}, "yes_bid") is None
assert rts("2026-10-22T13:47:03Z") == 1792676823.0 and abs(rts("2026-10-22T13:47:03.4654Z") - 1792676823.4654) < 1e-6
assert rts("2026-10-22T13:47:03.123456789+00:00") == rts("2026-10-22T13:47:03.123456+00:00") and rts(None) is None and rts("bad") is None
assert cents(0.45) == 45 and cents(0.07) == 7
# ---- stats: the same numbers as the copies they replaced ----
def wilson_old(k, n, z=1.96):
    if n <= 0: return 0.0, 1.0
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return max(0, (c - r) / d), min(1, (c + r) / d)
def se_old(vals):
    n = len(vals)
    if n == 0: return None, None
    m = sum(v for v, _ in vals) / n; g = {}
    for v, c in vals: g[c] = g.get(c, 0.0) + (v - m)
    C = len(g)
    return m, ((C / (C - 1) * sum(x * x for x in g.values())) ** 0.5 / n if C > 1 else None)
rnd = random.Random(4)
for _ in range(2000):
    n = rnd.randint(0, 200); k = rnd.randint(0, n) if n else 0
    assert wilson(k, n) == wilson_old(k, n)
    vals = [(rnd.gauss(0, 1), rnd.randint(0, rnd.randint(0, 6))) for _ in range(rnd.randint(0, 30))]
    a, b = cl_mean_se(vals), se_old(vals)
    assert a[0] == b[0] and (a[1] is None) == (b[1] is None) and (a[1] is None or abs(a[1] - b[1]) <= 1e-15 * max(1, b[1])), (a, b)
# ---- jsonio ----
p = os.path.join(OUT, "sub", "x.json"); jsonio.save(p, {"a": [1, 2]})
assert jsonio.load(p) == {"a": [1, 2]} and jsonio.load(p + ".none", 7) == 7 and not os.path.exists(p + ".tmp")
q = os.path.join(OUT, "log", "r.jsonl"); jsonio.append(q, [{"i": 1}, {"i": 2}]); jsonio.append(q, [])
open(q, "a").write('{"i": 3')   # a crash mid-line
assert jsonio.lines(q) == [{"i": 1}, {"i": 2}] and jsonio.lines(q + ".none") == []
assert open(q).read().startswith('{"i":1}\n')   # compact, one object per line
print("tbcommon: all checks passed")
