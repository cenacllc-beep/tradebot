"""Shared building blocks for Tradebot's research and measurement code (added 2026-10-22, refactor stage 1).

One implementation of what used to be copied into each research module:
- tbcommon.httpclient: a read-only JSON client for public APIs (rate limit, retries, Retry-After, one keep-alive session);
- tbcommon.parse: tolerant number, price and timestamp parsing;
- tbcommon.stats: Wilson intervals and cluster-robust means;
- tbcommon.jsonio: atomic JSON files and crash-tolerant JSONL logs;
- tbcommon.db: read-only SQLite connections (added 2026-11-05);
- tbcommon.clock: the bot's one time zone and time labels.

Nothing here places orders, writes paper.db or live.db, or knows about any strategy (tbcommon.db only opens
databases read-only). The frozen v3 path (strategy.py,
weather.py, nws.py, kalshi.py, core.py) and live.py do not use it. Python 3.8+.
"""
