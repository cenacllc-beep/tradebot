# Tradebot architecture (current, 2026-10-22, after the platform upgrade and refactor stage 1)

The architecture as it was found before the upgrade, with the root problems that prompted it, is kept at the end
("As found"). docs/REFACTOR.md has the problem areas and the refactoring plan.

## 1. What the system is
Tradebot is a single-PC, batch-oriented research and paper-trading system for Kalshi markets. It is about 7,800 lines of
Python 3.8+ (no framework, the standard library plus `requests`), plus about 2,500 lines of tests.

It has three hard boundaries:
- **live.py is the only code that can send an order.** It copies v3 rain paper trades, and it is locked to Kalshi's demo
  exchange until 2026-11-11 and the user's own typed unlock, under a $25 cap.
- **Research code reads only.** It makes public GET requests and writes its own files; it never writes paper.db or live.db.
- **The v3 rain strategy is frozen** (estimator, blend, edge rule, gate) until its single-look verdict on 2026-11-11.

## 2. Layers
| Layer | Modules | Writes | May import |
|---|---|---|---|
| **Entry points and scheduling** | run.bat (commands), tasks\*.cmd (Windows Task Scheduler), main.py | logs\tasks.log | everything below |
| **Frozen trading core (v3)** | strategy.py, weather.py, nws.py, kalshi.py, core.py, config.py | paper.db: obs, trades | standard library, requests |
| **Order path** | live.py | live.db | core (fee, kill switch), strategy (dates), kalshi |
| **Audit and governance** | audit.py (decision ledger), registry.py (lifecycle) | paper.db: ledger tables, strategy_log (append-only) | standard library |
| **Shadow and measurement** | shadow.py (maker ledger, v4, rules watch), selector.py, calibration.py, risk.py, fees.py, resolution.py, metrics.py, postmortem.py, learn.py, marks.py | paper.db shadow tables; marks.jsonl; research/results/learning.md | core, audit, tbcommon (not shadow.py) |
| **Presentation** | dashboard.py, account_view.py, control_view.py | dashboard.html, dashboard_live.html | opens paper.db read-only; gate.py for the gate rules |
| **Research** | research/*.py with PLAN*.md | research/data, research/results, research/data/discovery.db | tbcommon, fees; never paper.db or live.db for writing |
| **Shared library** | tbcommon/ (httpclient, parse, stats, jsonio), gate.py | none | standard library, requests |
| **Operations** | backup.py, export.py, check.py, killswitch.py | backups\, Documents\tradebot_backups, backups\paper_latest.json | standard library |

Dependency rule: arrows point down only. Nothing imports live.py. No research, measurement or presentation module
imports strategy.py. gate.py holds the gate rules with no dependencies, and a parity test keeps it identical to
strategy.py's frozen copy until stage 2.

## 3. Data stores
| Store | Owner (writer) | Content | Mutability |
|---|---|---|---|
| paper.db obs | strategy.scan | First snapshot per (ticker, version): forecast, mid, inputs | insert-or-ignore; results filled at settle |
| paper.db trades | strategy.scan and settle | Paper trades | status, result, pnl and settled_ts updated at settle |
| paper.db decisions, decision_events, scans, scan_ends, market_results, audit_meta | audit.py (through strategy and shadow) | Every evaluation, its reason and inputs; later events | append-only (triggers) |
| paper.db strategy_log | registry.log_states | Lifecycle history | append-only |
| paper.db shadow_* and v4_* | shadow.py | Maker ledger, price moves, rules watch, v4 forward test | updated by shadow.py only |
| live.db | live.py | Orders, events, locks | live.py only |
| research/data/... | each research module | Samples, fills, results, catalogue (discovery.db) | append or replace by that module |
| marks.jsonl | marks.py | Bids of open positions | append |
| backups\, offsite, paper_latest.json | backup.py, export.py | Copies | new files only, never overwritten |

## 4. Data flow of one evening (tasks\evening.cmd, 8:55 PM)
1. **`run.bat settle`.** It records results for open trades and logged markets: `strategy.settle`, then `live.py sync`,
   `shadow.py settle`, `learn.py`, a backup and the dashboard.
2. **`run.bat scan`**:
   1. The kill switch is checked first. If it is on, nothing that trades runs.
   2. Backup (prescan). If the backup fails, the scan stops.
   3. `main.py scan` calls `strategy.scan`:
      1. `audit.ensure` checks the ledger columns, creating missing tables after a "preaudit" backup. If the ledger
         is unavailable: TRADES BLOCKED (markets are still logged).
      2. `kalshi.markets()` lists KXRAIN and KXHIGH<city> markets closing within 36 h.
      3. For each market:
         - close time unreadable or the market's day has begun: abstain;
         - no usable quote, or spread over 6c: abstain;
         - `weather.estimator` (NWS grid slices, frozen) gives the forecast, and the obs row is inserted;
         - fair = 0.5 x forecast + 0.5 x mid; side = the larger edge; the shadow selector gives its verdict (recorded
           only);
         - the gates (daily stop, already held, temperature disabled, 8-point edge, size, cash, 15% cap) either abstain
           or open a trade. The trade and its decision row are written in one savepoint.
      4. `audit.end_scan` writes the summary, then one commit.
   4. `live.py mirror` copies new v3 rain paper trades: to demo now, to real money only after Nov 11 and the unlock.
   5. `shadow.py scan`: maker ledger, price moves, rules watch and the v4 log.
   6. Backup (postscan), `export.py` (JSON copy), `dashboard.py`.
3. **Hourly (tasks\hourly.cmd, read-only):**
   - `lip.py` samples and fills (PLAN5 L);
   - `structure.py` and `discover.py --singles`, each every 6 hours;
   - `marks.py`, then the dashboard.
4. **Cloud scheduled tasks** read logs\tasks.log and dashboard.html through the device file tools, republish the phone
   page and message the user. They run nothing on the PC.

## 5. External interfaces
| Service | Used by | Calls |
|---|---|---|
| Kalshi public REST (api.elections.kalshi.com) | kalshi.py, shadow.py, marks.py, research/* through tbcommon.httpclient | GET markets, events, series, orderbook, trades, candlesticks, incentive_programs |
| Kalshi signed REST | live.py only | balance, positions, orders (demo now) |
| api.weather.gov | nws.py | points, forecast, forecastGridData |
| Open-Meteo | weather.py (temperature, logged only) | forecast |
| Polymarket and IEM | research/plan4.py, plan3.py, markets.py | read-only history |

The User-Agent everywhere is "tradebot-paper-research/1.0".

## 6. Testing
tests/run_all.py runs 29 deterministic tests on fakes (no network, temporary folders, never the real databases).
Pre-registered research scorers each have a planted-edge test and a null test.

## As found before the upgrade (2026-10-22 morning)
The analysis that started the upgrade, kept as written.
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
