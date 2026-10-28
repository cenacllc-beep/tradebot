# Reliability checks (added 2026-10-23)

Three gaps, each with its fix. None of them changes a decision, a threshold or a score: they report, so that a
stale file, a broken candle or a mislabelled time is seen instead of silently trusted.

## 1. Data freshness: `freshness.py`

**The gap.** The bot depends on about fifteen datasets, each refreshed by a different job:
- the evening scan;
- settlements;
- two backups (in the folder and outside it);
- the JSON export;
- the dashboard page;
- live prices;
- PLAN5 test L's caches;
- the structure scan;
- the market catalogue;
- the forecast behind each decision;
- the PC clock.

When a job stopped, nothing flagged it. Every scan from Oct 15 evening to Oct 21 failed, and the only sign was the
date on the dashboard's "Last scan" line.

**The fix.** `freshness.py` gives each dataset a refresh limit, set by the job that refreshes it and how often that job
runs. It reads each dataset's latest timestamp and reports one status:

| Status | Meaning |
|---|---|
| ok | within its limit |
| stale | older than its limit |
| fail | broken: a job ended with an error, a job started and never finished, a timestamp is in the future, or the clock is more than 5 minutes off Kalshi's |
| waiting | not started yet, or not expected now (for example PLAN5 L outside its window) |
| info | worth knowing, never alarming (for example the PC's time zone differs from the bot's) |

| Dataset | Source of its timestamp | Limit |
|---|---|---|
| Evening scan | newest of paper.db obs.ts and the ledger's scans.started_ts; while the kill switch is on, a stale scan is shown as info (halted on purpose) | 26 h |
| Settlements | open trades whose market closed more than a day ago (close from the ticker date) | 24 h after close |
| Forecast at the last scan | the oldest NWS grid behind the last ledger scan's decisions | 3 h (the selector's STALE_DATA limit) |
| Backups, in and outside the folder | newest `paper_*.db` file | 26 h |
| JSON export | backups\paper_latest.json | 26 h |
| Dashboard page | dashboard.html; also stale when built more than 2 minutes before the latest scan data | 26 h |
| Live prices | last line of marks.jsonl, only while something is open | 2 h |
| PLAN5 L programs and samples | programs.json `fetched`; last line of samples.jsonl; inside the window, counted from its start until the first one | 7 h, 2 h |
| PLAN5 L fee types | info only: lip.py reads each series' fee type once and keeps it, and rewrites series.json every sample, so the file's date says nothing about its entries | none |
| Structure scan | last line of research/data/structure/runs.jsonl | 7 h |
| Market catalogue | discovery.db's last finished run (a run that only started does not count) | 7 h |
| Scheduled jobs | logs\tasks.log: the last finish line of each job, and its exit code | 26 h, 26 h, 2 h |
| PC clock | research/data/clock.json, measured from Kalshi's Date header | off by 60 s is stale, 300 s fails; re-measured within 26 h |
| Reports vs their data | structure.md written before its scan's line; discovery.md before the latest catalogue refresh (info: the hourly job refreshes without summarizing) | 2 min |

**Where it shows:**
- `.\run freshness` prints the table, writes research/results/freshness.md and .json, and ends with one line:
  `FRESHNESS: all current (20 checks)`, or `FRESHNESS: 1 stale, 2 failed: ...` with failures first.
  `.\run freshness --clock` also measures the clock.
- The scan and settle steps run it at the end, so the line lands in logs\tasks.log for the cloud reports. The hourly
  job runs it with `--clock`.
- The dashboard's control center has a "Data freshness" table with problems first. A header chip, "Data checks: 2
  failed, 1 out of date", links to it.

**Robustness.** Timestamps are read as numbers only: text, true/false or NaN in a field counts as missing, never as
a crash. The last line of a log is found even when it is longer than the first read (structure-scan lines can pass
70 KB). logs\tasks.log is read from its end first.

**Safety.** Read-only: paper.db is opened mode=ro (tests/test_freshness.py checks its bytes are unchanged), and other
files are only read. Exit code 0 so a batch never stops for it; `--strict` returns 1 on a failure. The clock
measurement is one public GET to the Kalshi API the bot already uses, with the project's User-Agent. A corrupt or
missing file gives "waiting" or "stale", never a crash.

## 2. Historical OHLC anomalies: `tbcommon/ohlc.py`, `research/ohlc_audit.py`

**The gap.** Several parts of the bot take "the latest one-minute candle at or before t" and trust it:
- plan3.py and fetch.py, for past data;
- shadow.py, for price moves;
- PLAN5 test L, for the mid after each fill.

Kalshi sends a candle only for minutes when something changed, so that candle can be hours old. A candle can also be
broken: crossed, high below low, or prices outside 0-1. Nothing checked either.

**The fix.**
- **tbcommon/ohlc.py** checks candles. It reads dollar or cent fields. Per candle:
  - OFF_GRID, FUTURE, OUT_OF_RANGE;
  - HIGH_BELOW_LOW, OPEN_CLOSE_OUTSIDE;
  - CROSSED, LOCKED;
  - NEGATIVE_VOLUME, TRADE_OUTSIDE_QUOTE;
  - EMPTY_SIDE: a bid or ask at 0 or 1. No real order rests there, so it is the placeholder for an empty side. Such a
    candle is informational and is not tested for CROSSED, LOCKED or TRADE_OUTSIDE_QUOTE, and it has no mid.
  
  The field names match Kalshi's API reference (yes_bid, yes_ask and price with *_dollars strings, volume_fp).
  
  Per series: TIME_NOT_INCREASING, JUMP (mid moves over 50 points between candles) and GAP (no candle for over 6 hours).
- **research/ohlc_audit.py** fetches the candles of every market the bot logged, once its window is over (36 hours
  before to 30 hours after the market day starts). It records per market:
  - anomaly counts;
  - the largest gap between candles;
  - at each minute the bot logged the market: how old the "latest" candle was, and how far its mid was from the mid
    the bot read from the live order book.
  
  Settled candles do not change, so each market is audited once. A failed fetch, or an answer with no candles, is
  retried on later runs, three tries in all, so a market that always fails cannot hold a slot for weeks.
  `.\run ohlc` runs it. The hourly job runs it once a day, at most 60 markets a run.
- **The report**, research/results/ohlc_audit.md and .json, gives by market type:
  - anomaly rates per 1,000 candles;
  - markets with a broken candle;
  - the median and 90th-percentile age of the candle a backtest would have used;
  - how often history and the live quote disagree by more than 5 points (only where the candle's spread was 6 cents
    or less, the bot's own MAX_SPREAD; a mid across a wide spread is not a price).
- **PLAN5 test L:** each fill record also keeps a descriptive `candle_check`: anomaly codes, and the age of the candle
  behind each adverse-selection mid. It was added before the first sample (the window opens Oct 24). score() never
  reads it, tests/test_ohlc.py checks that, and the adverse-selection numbers are unchanged. PLAN5.md says so.

**Not changed.** The pre-registered scorers (backtest*.py, plan3.py, plan4.py) and shadow.py keep reading candles as
before. The audit measures how much their data can be trusted; it does not alter them.

## 3. Report timestamp consistency: `tbcommon/clock.py`

**The gap.** Each module stamped times its own way, mostly in whatever zone the PC used and without saying which:
- `2026-10-22T21:05` in lip and longshot;
- `2026-10-22 21:05` in structure and discovery;
- `Oct 22, 9:05 PM` on the dashboard.

The account view's script used the viewing device's zone, so a page rendered in the cloud (UTC) showed different
times and month boundaries than the same page on the phone. The daily P&L grouping in metrics.py used the PC's
calendar date.

**The fix.** One zone, America/La_Paz (UTC-4 all year, no daylight saving, so a fixed offset is exact), and three
formats:
- `clock.iso(ts)`, `2026-10-23T10:33:00-04:00`, for files and logs. The offset is always written.
- `clock.label(ts)`, `Oct 23, 10:33 AM`, for people. Each page or report names the zone once ("La Paz time (UTC-4)").
- `clock.bot_date(ts)` for grouping by day.

**Applied to:**
- **Research reports:** structure.md and discovery.md headers, PLAN5 L's `scored`, longshot's `made`, the freshness
  and OHLC reports.
- **Dashboard:**
  - every server-side time (the last scan line, the control center, the audit trail, the price note);
  - "Updated ... (UTC-4)";
  - the account view's script (dates, times, month statements, year reports and CSV columns, now headed "Opened
    (UTC-4)" and "Closed (UTC-4)"), through `timeZone: 'America/La_Paz'` and UTC-shifted dates.
- **metrics.daily:** settlement dates in bot time.
- **logs\tasks.log:** `Get-Date -Format o`, so each line carries its offset. Older lines without one are read as the
  PC's local time, which is what they were. If PowerShell does not answer, the line says "no-time" and the run still
  counts (shown as info). The "done (exit N)" code is now that of any failing step, not only the last one: before,
  a failed settle followed by a successful report was logged as exit 0.

**Not changed:**
- Stored timestamps: epoch seconds, already zone-free.
- Kalshi market days: by definition the city's local standard midnight.
- Backup and export file names, and the KILL file's text.
- The pre-registered scorers' stamps.
- The gate's own date (gate.py and frozen strategy.py use the PC's calendar date, kept identical to each other).

When the PC is set to La Paz time, as it is now, every shown time is the same as before. freshness.py reports the PC
zone as "info" if that ever changes.

## Tests
- **tests/test_freshness.py.** Every status for every check, overdue settlements, a page older than its data,
  job exits and runs that never finished, offset and offset-less log lines, clock skew from a fake Date header,
  future timestamps, corrupt files, the PLAN5 L window, and that paper.db is never written. It also checks the clock
  formats.
- **tests/test_ohlc.py.** Every anomaly code with dollar and cent fields, market selection, chunked fetching with
  duplicates, retry after a failed fetch, staleness and snapshot agreement, the report, `--every`, and PLAN5 L's
  candle record leaving the adverse numbers unchanged.
- **tests/test_lip.py** also checks that fill records carry `candle_check`.
