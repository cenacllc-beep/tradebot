"""Read-only JSON-over-HTTPS client for public APIs (Kalshi market data and similar).

Every research module used to carry its own copy of the same retry loop, with small differences that had drifted
(one crashed on a non-numeric Retry-After header). JsonClient keeps each module's own tuning (tries, timeout,
spacing, backoff) as constructor arguments, so moving a module onto it does not change its request pattern.

Behaviour, per GET:
- waits until at least `min_gap` seconds have passed since this client's previous request (rate limit);
- 200: returns the decoded JSON, then sleeps `pause_after` seconds (a politeness pause some modules used);
- 429 or 5xx: waits Retry-After seconds when the header is a number, else min(cap, base x 2^attempt), and retries;
- a network error: waits the same backoff and retries (optionally printing the error);
- any other status: raises RuntimeError("HTTP <status> <path>") at once;
- after `tries` attempts: raises RuntimeError("giving up on <path>").
Only GET exists here. The User-Agent is the project's only allowed one (CLAUDE.md section 3).

Testing: modules keep a module-level `http()` that calls their client, so tests replace that function, or swap
`sys.modules["requests"]` before the first request (the client binds `requests` lazily). Patching `requests.get` alone
does not reach a client that already holds a keep-alive Session. Sleep and clock are looked up at call time unless
injected, so patching `time.sleep` still works.
"""
import time

USER_AGENT = "tradebot-paper-research/1.0"
KALSHI_PUBLIC = "https://api.elections.kalshi.com/trade-api/v2"


class JsonClient:
    def __init__(self, base, tries=5, timeout=30, min_gap=0.0, pause_after=0.0, backoff_base=3.0, backoff_cap=60.0,
                 verbose=False, headers=None, sleep=None, clock=None):
        self.base = base
        self.tries = tries
        self.timeout = timeout
        self.min_gap = min_gap
        self.pause_after = pause_after
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.verbose = verbose
        self.headers = dict(headers or {"User-Agent": USER_AGENT})
        self.requests = 0          # attempts made, for run summaries
        self._sleep_fn = sleep     # None: time.sleep, looked up at call time
        self._clock_fn = clock     # None: time.time, looked up at call time
        self._last = 0.0
        self._get = None           # bound lazily, so tests can swap the `requests` module before first use

    def _sleep(self, seconds):
        (self._sleep_fn or time.sleep)(seconds)

    def _clock(self):
        return (self._clock_fn or time.time)()

    def backoff(self, attempt):
        w = self.backoff_base * 2 ** attempt
        return w if self.backoff_cap is None else min(self.backoff_cap, w)

    def _transport(self):
        import requests
        if self._get is None:
            session = requests.Session() if hasattr(requests, "Session") else None   # keep-alive across calls
            if session is not None:
                session.headers.update(self.headers)
            self._get = (session.get if session is not None else requests.get, requests.RequestException)
        return self._get

    @staticmethod
    def _retry_after(response):
        try:
            return float(response.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            return 0.0

    def get(self, path, params=None, tries=None):
        get, network_error = self._transport()
        for attempt in range(tries or self.tries):
            if self.min_gap:
                wait = self._last + self.min_gap - self._clock()
                if wait > 0:
                    self._sleep(wait)
                self._last = self._clock()
            self.requests += 1
            try:
                r = get(self.base + path, params=params or {}, headers=self.headers, timeout=self.timeout)
            except network_error as ex:
                if self.verbose:
                    print("  retry (%s)" % str(ex)[:80])
                self._sleep(self.backoff(attempt))
                continue
            if r.status_code == 200:
                data = r.json()
                if self.pause_after:
                    self._sleep(self.pause_after)
                return data
            if r.status_code == 429 or r.status_code >= 500:
                self._sleep(self._retry_after(r) or self.backoff(attempt))
                continue
            raise RuntimeError("HTTP %d %s" % (r.status_code, path))
        raise RuntimeError("giving up on %s" % path)
