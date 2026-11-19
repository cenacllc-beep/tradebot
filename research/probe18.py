"""PROBE18: what data exists for a PLAN18 (the index's own exchanges, read together) - before the plan is written.
Research only, runs on GitHub's runner. It records only whether data exists and how much (row counts, first and last
times, gaps): no price levels, no Kalshi results, no outcome of any kind, so it cannot steer the plan toward a result.

Checks:
1. For each BRTI / ETHUSD_RTI constituent exchange that ccxt supports (Bitstamp, Coinbase, Kraken, Gemini, Crypto.com,
   Bullish; LMAX Digital is not in ccxt), BTC/USD and ETH/USD: can one-minute candles (fetch_ohlcv with since) and
   trades (fetch_trades with since) be read for one hour on sample days from June to October 2026? Rows, first/last
   minute, missing minutes.
2. Kalshi: on which sample days do KXBTC15M and KXETH15M markets exist (count only, from the live and the historical
   market lists), to see how far back an unused period goes.

Approved by the user 2026-11-18 20:32 ("i want all options that will help with research and detection"): ccxt, arch
and ruptures on GitHub's runners, and read-only public market data from the index's constituent exchanges. User-Agent
tradebot-paper-research/1.0, no account, no key. Writes research/results/probe18.json.
  python research/probe18.py"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

UA = "tradebot-paper-research/1.0"
EXCHANGES = ("bitstamp", "coinbase", "kraken", "gemini", "cryptocom", "bullish")
PAIRS = {"BTC": ("BTC/USD",), "ETH": ("ETH/USD",)}
SAMPLE_DAYS = ("2026-06-15", "2026-07-15", "2026-08-15", "2026-09-15", "2026-10-15")
HOUR = 14   # 14:00-15:00 UTC on each sample day
OUT = os.path.join(HERE, "results", "probe18.json")


def ts(day, hour=0):
    return int(datetime.strptime(day, "%Y-%m-%d").replace(hour=hour, tzinfo=timezone.utc).timestamp())


def shape(times_ms, start, end):
    """Counts only: rows inside [start, end), distinct minutes, missing minutes, first/last minute offset."""
    mins = sorted({(t // 1000 - start) // 60 for t in times_ms if start * 1000 <= t < end * 1000})
    want = (end - start) // 60
    return dict(rows=sum(1 for t in times_ms if start * 1000 <= t < end * 1000), minutes=len(mins),
                missing=want - len(mins), first_min=mins[0] if mins else None, last_min=mins[-1] if mins else None)


def probe_exchange(ccxt, name):
    out = dict(exchange=name)
    try:
        ex = getattr(ccxt, name)({"enableRateLimit": True, "userAgent": UA, "headers": {"User-Agent": UA}})
        ex.load_markets()
    except Exception as e:   # noqa: BLE001  (any failure is the finding)
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        return out
    out["has_ohlcv"], out["has_trades"] = bool(ex.has.get("fetchOHLCV")), bool(ex.has.get("fetchTrades"))
    for asset, syms in PAIRS.items():
        sym = next((s for s in syms if s in ex.markets), None)
        res = out.setdefault(asset, dict(symbol=sym, days={}))
        if sym is None:
            res["error"] = "no USD market listed"
            continue
        for day in SAMPLE_DAYS:
            a, b = ts(day, HOUR), ts(day, HOUR + 1)
            d = {}
            if out["has_ohlcv"]:
                try:
                    rows = ex.fetch_ohlcv(sym, "1m", since=a * 1000, limit=60)
                    d["ohlcv"] = shape([r[0] for r in rows], a, b)
                except Exception as e:   # noqa: BLE001
                    d["ohlcv"] = dict(error="%s: %s" % (type(e).__name__, str(e)[:160]))
            if out["has_trades"]:
                try:
                    rows = ex.fetch_trades(sym, since=a * 1000, limit=1000)
                    d["trades"] = shape([r["timestamp"] for r in rows if r.get("timestamp")], a, b)
                except Exception as e:   # noqa: BLE001
                    d["trades"] = dict(error="%s: %s" % (type(e).__name__, str(e)[:160]))
            res["days"][day] = d
            time.sleep(0.5)
    return out


def probe_kalshi():
    import plan15 as P
    out = {}
    for series in ("KXBTC15M", "KXETH15M"):
        s = out.setdefault(series, {})
        for day in ("2025-10-15", "2025-12-15", "2026-02-15", "2026-04-15") + SAMPLE_DAYS:
            a = ts(day)
            q = dict(series_ticker=series, min_close_ts=a, max_close_ts=a + 86400, limit=200)
            row = {}
            for path in ("/markets", "/historical/markets"):
                try:
                    j = P.http_kalshi(path, q) or {}
                    row[path] = len(j.get("markets") or [])
                except Exception as e:   # noqa: BLE001
                    row[path] = "error %s" % type(e).__name__
            s[day] = row
    return out


def main():
    import ccxt
    res = dict(probe="PROBE18", run=datetime.now(timezone.utc).isoformat(), ccxt=ccxt.__version__,
               note="existence and counts only; no prices, no Kalshi results", exchanges=[], kalshi=None)
    for name in EXCHANGES:
        res["exchanges"].append(probe_exchange(ccxt, name))
        print("probed", name)
    res["kalshi"] = probe_kalshi()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    os.replace(OUT + ".tmp", OUT)
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
