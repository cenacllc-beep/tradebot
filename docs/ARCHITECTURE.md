# Tradebot architecture (current as of 2026-11-05, refactor stage 3)

docs/REFACTOR.md holds the senior-engineer review: problem areas, the refactoring strategy, what each stage changed, and
how "no change in behaviour" was proved. This file describes the system as it runs. The 2026-10-22 version's "As
found" notes are kept at the end.

## 1. What the system is
Tradebot is a batch-oriented research and paper-trading system for Kalshi's daily weather markets.
- **Size:** about 11,000 lines of Python 3.8+, the standard library plus `requests`, with no framework. Plus about
  6,000 lines of tests (37 test scripts).
- **Where it runs:** one Windows laptop runs it on a schedule. A public GitHub repository runs a second, separate copy
  (the cloud trial) and some research sampling.
- **Its one question:** does a forecast beat Kalshi's prices? Everything else is measurement around that question.

**Hard boundaries, each enforced in code and tests:**
1. **live.py is the only code that can send an order.** It copies new v3 rain paper trades only. It is locked to
   Kalshi's demo exchange until 2026-11-11 and the user's own typed unlock, under a $25 cap.
2. **v3 is frozen.** That covers the estimator, the blend, the edge rule, the veto and the gate:
   strategy.py, weather.py, nws.py, kalshi.py, core.py and config.py. It is judged once, by the stored gate look on the
   stop date. Its code also stays unchanged while PLAN7 runs (research/PLAN7.md section 3).
3. **Research reads only.** It makes public GETs and writes its own files. It never writes paper.db or live.db; it
   opens them read-only.
4. **Pre-registered scorers keep their code.** Once a plan's outcomes have begun, its scoring code is not refactored,
   so its results stay reproducible from the registered code. This covers backtest*.py, plan3.py, plan4.py,
   placebo.py, lip.py, nov11.py, plan7.py, plan8.py, and shadow.py's forward-test blocks.
5. **Operations scripts depend on the standard library only.** These are backup.py, export.py, check.py,
   killswitch.py, manifest.py, joblock.py and scan_window.py. The dashboard can also render without them. Each must
   keep working when anything else in the folder is broken.

## 2. Layers
| Layer | Modules | Writes | May import |
|---|---|---|---|
| **Scheduling and entry points** | Windows Task Scheduler -> tasks\*.cmd -> jobs.py (network wait, retries, job lock, scan window) -> run.bat -> main.py, shadow.py, live.py, research\*.py | logs\tasks.log | everything below |
| **Frozen trading core (v3)** | strategy.py, weather.py, nws.py, kalshi.py, core.py, config.py | paper.db: obs, trades, gate_look | stdlib, requests, audit, selector, calibration, risk |
| **Order path** | live.py | live.db | core, strategy (dates and the stored look), kalshi |
| **Audit and governance** | audit.py (decision ledger, append-only), registry.py (strategy lifecycle) | paper.db: scans, decisions, decision_events, ... | stdlib |
| **Shadow and measurement** | shadow.py (maker ledger, price moves, rules watch, the airport-forecast forward test), stationfc.py, selector.py, calibration.py, risk.py, fees.py, resolution.py, metrics.py, postmortem.py, learn.py, marks.py, freshness.py | paper.db shadow_* and v4_* tables (shadow.py only); marks.jsonl; research/results | core, audit, tbcommon (not shadow.py or stationfc.py) |
| **Presentation** | dashboard.py, dashboard_assets.py, account_view.py, control_view.py | dashboard.html, dashboard_live.html | paper.db read-only; gate.py; optional tbcommon |
| **Research** | research/*.py with their PLAN*.md | research/data, research/results | tbcommon, fees; never paper.db or live.db for writing |
| **Shared library** | tbcommon/: httpclient, parse, stats, jsonio, clock, db, ohlc; gate.py | none (tbcommon.db opens read-only) | stdlib, requests |
| **Operations** | backup.py, export.py, check.py, killswitch.py, joblock.py, scan_window.py, manifest.py | backups\, Documents\tradebot_backups, backups\paper_latest.json | stdlib only |
| **Cloud (GitHub Actions, public repository)** | cloud/workflows: the trial scan and settle on trial/paper.db, the PLAN5 L sample, the trial-scan backstop | trial/paper.db, research/data/lip (repository copies) | the repository's copy of the code |

**Dependency rule.** Arrows point down only:
- nothing imports live.py;
- no research, measurement or presentation module imports strategy.py, except shadow.report, which imports it for one
  statistic, lazily;
- gate.py holds the gate's rules with no dependencies, and tests/test_fix.py keeps it identical to strategy.py's frozen
  copy.

## 3. Data stores
| Store | Writer | Content | Mutability |
|---|---|---|---|
| paper.db obs | strategy.scan; settle fills results | First snapshot per (ticker, version): forecast, mid, inputs | insert-or-ignore; result set once |
| paper.db trades | strategy.scan and settle | Paper trades | status, result, pnl updated at settle |
| paper.db gate_look | strategy.gate_look | The stop date's single look (one row) | written once, after a backup |
| paper.db scans, decisions, decision_events, market_results | audit.py through strategy and shadow | Every evaluation with its reason, inputs, bid, ask, forecast and model version | append-only (triggers) |
| paper.db shadow_*, v4_*, rules_* | shadow.py | Maker ledger, price moves, the airport-forecast test, rules watch | shadow.py only |
| live.db | live.py | Orders, events, locks | live.py only |
| research/data/... | each research module | Samples, catalogue (discovery.db, about 215 MB), PLAN7 candles | append, or replace by that module |
| research/results/... | each scorer or report | Scored results, reports, frozen models | each written once by its plan's rules |
| marks.jsonl | marks.py | Bids of open positions | append |
| logs\tasks.log | jobs.py | Every scheduled step's output, with "=====" start and done lines | append |
| backups\, offsite, paper_latest.json | backup.py, export.py | Copies before and after each scan, settle and migration | new files only, never overwritten |

## 4. Data flow
### 4.1 Evening (8:55 PM, "Tradebot\Evening scan" -> tasks\evening.cmd -> jobs.py evening)
1. jobs.py waits for Kalshi to be reachable while the 8:50 PM to 1 AM window is open, and takes the job lock.
2. **`run.bat settle`** (section 4.2).
3. **`run.bat scan`:**
   1. The kill switch is checked first. If it is on, or cannot be checked, nothing that trades runs; the backups, export,
      dashboard and freshness still run.
   2. Backup (prescan). If the paper.db backup fails, the scan stops. If only the live.db backup fails, the paper scan
      runs and the Kalshi copy is skipped.
   3. **`main.py scan` calls strategy.scan:**
      1. The gate look: from the stop date it is stored once, when every test-day market has its result.
      2. `audit.ensure`, then `kalshi.markets()`: KXRAIN and the KXHIGH series closing within 36 hours.
      3. Per market:
         - close time unreadable, or the day has begun: abstain;
         - no quote, or spread over 6c: abstain;
         - weather.estimator (NWS gridpoint hourly slices, frozen) gives the forecast, and an obs row is written;
         - fair = 0.5 x forecast + 0.5 x mid; the shadow selector's verdict is recorded only;
         - the gates: daily stop, already held, temperature disabled, 8-point edge, 30-point veto, the stop date's look,
           size, cash, 15% cap;
         - a trade and its decision row are written in one savepoint;
         - every evaluation is a decision row.
      4. One commit; the scan summary goes to tasks.log.
   4. `live.py mirror`: new v3 rain paper trades copied to the connected exchange (demo now).
   5. `shadow.py scan`: maker ledger orders, rules watch, the airport forecast's evening log (IEM).
   6. Backup (postscan), `export.py` (JSON copy of every table), `dashboard.py`, `freshness.py` (its "FRESHNESS:" line).
4. The scan is retried up to 3 times inside the window if it fails.

### 4.2 Settle (2:51 PM, and before every evening scan)
`main.py settle` records outcomes, with a retry per market and results committed as found. Then, in order:
- `live.py sync`;
- `shadow.py settle`: fills from minute candles, price moves, the airport-forecast test's paper results;
- `learn.py`;
- `research\plan7.py auto`: PLAN7's candle store, and its one-time fit from Nov 11;
- `research\plan8.py auto`: PLAN8's status line (counts only; its model was fitted once on past data on 2026-11-06);
- backup (postsettle), dashboard, freshness.

The afternoon job then runs `run.bat report` (Brier, gate, shadow).

### 4.3 Hourly research (:20, read-only)
- plan4_launch;
- PLAN5 L sample and settle;
- every 6 hours: the structure scan and the catalogue;
- daily: the OHLC audit;
- marks, freshness with a clock check against Kalshi, dashboard.

### 4.4 Cloud
- **The trial copy** runs the same code on trial/paper.db: a scan from 8:55 PM, once an evening, plus the backstop that
  starts it when GitHub skips it; and settles from 2:40 PM.
- **PLAN5 L** is sampled hourly, merged with the PC's hours before its single score.
- **The cloud scheduled tasks** (Claude) read logs\tasks.log and dashboard.html through the device bridge, republish the
  phone page and message the user. They run nothing on the PC.

### 4.5 The stop date and after
- From Nov 11, report(), live.py and the dashboard quote only the stored look.
- research/nov11.py writes the PLAN6 report next to it.
- After a failed look, v3 still logs every market. Until 2026-11-06 it then opened no paper trades; since the user's decision that day (strategy.TRADE_AFTER_LOOK) it keeps paper-trading, and the limit-order ledger alone stays stopped. Test-day markets still unsettled on 2026-11-18 (strategy.LOOK_DEADLINE) are left out of the look.
- Three forward tests then continue on those logs, each with its own pre-set end:
  - the airport forecast (shadow.py);
  - PLAN7 (research/plan7.py);
  - PLAN8 (research/plan8.py), from market day Nov 7: the price with the airport forecast mixed in, an accuracy test
    only.

## 5. External interfaces
| Service | Used by | Calls |
|---|---|---|
| Kalshi public REST (api.elections.kalshi.com) | kalshi.py, shadow.py, marks.py, research/* (tbcommon.httpclient), plan7.py | GET markets, events, series, orderbook, trades, candlesticks, incentive_programs |
| Kalshi signed REST | live.py only | balance, positions, orders (demo now) |
| api.weather.gov | nws.py | points, forecastGridData |
| Open-Meteo | weather.py (temperature, logged only) | forecast |
| Iowa Environmental Mesonet | stationfc.py (via shadow), research | NBS station guidance, climate reports |
| Polymarket | research only (PLAN4) | read-only history |
| GitHub API | the backstop workflow only (gh, the workflow's own token) | runs list, workflow_dispatch of the trial scan |

The User-Agent everywhere is "tradebot-paper-research/1.0".

## 6. Deploying and verifying a change
**Three copies of the code exist:**
- the working copy, where changes are made and tested;
- the public repository, which runs the cloud workflows;
- the PC folder, which runs the official record.

**Steps:**
1. Make the change and run tests/run_all.py. For a refactor, run tests/golden.py capture and compare against the copy
   before it.
2. A fresh agent reviews it with agents/code-reviewer.md or statistician.md, and CHANGELOG.md records the findings.
3. Push to the repository. Copy the changed files to the PC after backing up the old ones in backups\code_pre_rNN, and
   outside the 8:50 PM to 1 AM window.
4. Verify that the PC matches the repository: `python manifest.py write m.json` in one copy, then
   `python manifest.py check m.json` in the other. It reports changed, missing and extra code files and exits 1 on any
   difference.

## 7. Testing
- **tests/run_all.py** runs 41 deterministic tests from 38 scripts: fake data, temporary folders, no network, never the real
  databases.
- **Research scorers:** each pre-registered scorer has a planted-edge test and a null test.
- **Pinned copies:** tests/test_plan7.py and test_fix.py check that each pinned copy still equals its source.
  research/plan8.py imports PLAN7's pinned functions instead and pins their source hashes; tests/test_plan8.py checks
  them.
- **tests/golden.py** flattens every output of 15 scenario suites into about 150,000 fields to prove that a refactor
  changed nothing.

## As found before the upgrade (2026-10-22 morning)
The analysis that started the platform upgrade, kept as written.
- **Selection was value-only.** Any side 8 points better than its price qualified, whatever its chance of winning. A
  9% temperature contract bought at 1c (53 contracts) on Oct 14 was the result.
- **No record of why.** obs kept only the first snapshot per market. Rejected markets left nothing, and trades stored
  only the price and the blended chance.
- **Timing.** A 9:22 AM catch-up scan traded markets whose day had begun; strategy.started() fixed this on Oct 14.
- **Data freshness was not recorded.**
- **Fills were optimistic.** Paper trades took full size at the ask; the maker ledger ignored the queue.
- **Correlation was ignored.** The only portfolio limit was 15% open.
- **No strategy registry.**
- **Operations had a single point of failure.** The scans ran only through cloud sessions, so the usage limit stopped
  every scan from Oct 15 to Oct 21.
