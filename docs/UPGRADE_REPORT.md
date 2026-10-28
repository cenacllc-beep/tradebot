# Platform upgrade: engineering report (2026-10-22)

The 12 sections the brief asked for. Items marked **[PC]** need the PC to be reachable and are filled in after
deployment. Everything else was verified in the cloud working copy.

## 1. Current architecture (before the changes)
See docs/ARCHITECTURE.md for the full map. In short:
- main.py runs strategy.scan, which lists open weather markets (kalshi.py) and estimates rain from NWS hourly slices
  (weather.py, nws.py). It blends 50/50 with the market mid, trades when the edge is at least 8 points, sizes by
  quarter Kelly capped at 6%, and checks cash and a 15% open cap.
- paper.db held obs (first snapshot per market) and trades (price and blended chance only).
- shadow.py ran research ledgers.
- live.py was, and is, the only order path. It copies v3 rain paper trades: to demo now, to real money from Nov 11
  after the user's typed unlock, under $25 at risk.
- dashboard.py was read-only.
- Scans ran from scheduled cloud sessions that drive the PC.

## 2. Root problems
1. **Value-only selection.** Any side whose blended chance beat the price by 8 points qualified, at any win
   probability. A 9% temperature contract at 1c was bought 53 times on Oct 14.
2. **No record of why.** Rejected markets left nothing. A trade could not be traced to the exact quote, forecast and
   data age behind it.
3. **Optimistic fills.** Paper trades take full size at the listed ask; the maker ledger ignores the queue.
4. **Correlation ignored.** Same-day cities share weather; the only portfolio limit was 15% open in total.
5. **No calibration check** on the chance a trade would win.
6. **Operational single point of failure.** Every scan from Oct 15 evening to Oct 21 failed when the account hit its
   weekly usage limit. The forward test has two market days logged.

## 3. Changes made (file by file)
| File | Change |
|---|---|
| audit.py (new) | Append-only decision ledger. One row per market evaluated, with its reason code. A trade and its decision row are written together or not at all. Refuses an existing ledger whose columns differ. |
| strategy.py | Records every decision. Research helpers are guarded, so a broken one cannot stop the scan. Prints TRADES BLOCKED when the ledger is unavailable. **v3 decisions are unchanged:** checked by tests and by a 60-scan old-vs-new comparison. |
| shadow.py | The maker ledger records decisions and fill or settle events. |
| nws.py | Records each grid's fetch time and NWS update time. Values unchanged. |
| registry.py (new) | Strategy ids, versions, lifecycle states and modes. Nothing is live-eligible. |
| selector.py (new) | Accuracy-first meta selector, shadow only (experiment accuracy_first.v1, thresholds frozen). |
| calibration.py, risk.py, fees.py, resolution.py, metrics.py, postmortem.py (new) | Calibration with Wilson intervals; risk clusters and capital efficiency; fees and incentives (rewards gated on eligibility); settlement-certainty states; per-strategy metrics; loss-cause codes. |
| control_view.py (new), dashboard.py, account_view.py, marks.py | Control center, metrics, audit drill-down, live prices, and the "Trades blocked" chip. |
| research/structure.py (new) | Ladder and bucket-basket inconsistencies at executable prices after fees, confirmed in the order book. |
| research/longshot.py (new) | Favorite/longshot calibration by category, side and price (runs after K1 is scored). |
| research/lip.py, research/PLAN5.md | PLAN5 test L rebuilt after its statistics review, before any sample. |
| research/discover.py (new) | Market catalogue with lifecycle tracking, in its own database. |
| research/micro.py (new) | Order flow, a queue-aware fill model, toxic fills and lead-lag. |
| research/combo.py (new) | Combos: implied correlation from a one-factor copula. |
| research/plan4.py | Format check: lost positions listed only as CLOSED are capped at 2%. |
| run.bat | New commands: hourly, structure, watch, marks, discover, micro, combo. |
| tests/ | New tests: audit, structure, longshot, engines, lip, discover, micro and combo. |

## 4. Database changes
- **paper.db (additive only; obs and trades untouched):**
  - New tables: audit_meta, scans, scan_ends, decisions, decision_events, market_results and strategy_log.
  - Every one except audit_meta has UPDATE and DELETE triggers that abort ("append-only").
  - Indexes: unique decisions(scan_id, strategy_id, ticker); decisions(ticker); decisions(trade_ref);
    decision_events(decision_id).
  - Created once by audit.ensure(), after a "preaudit" backup. If the backup fails, nothing is created.
- **research/data/discovery.db (new, separate):** series, markets, lifecycle (append-only) and runs.
- **Research files (JSONL/JSON under research/data/):** lip, structure, micro and combo.
- **Migration rehearsed** on a copy of the PC's real paper.db (2026-10-22 17:46): tables, indexes and 12 triggers
  created; integrity ok; obs (81), trades (4), shadow_orders and v4_obs row counts unchanged; a second run changes
  nothing; the dashboard renders. On the PC itself the tables are created at the first settle or scan after
  install, right after backup.py's "preaudit" backup.

## 5. Strategy engines and their lifecycle state
From registry.py:

| Strategy | State | Mode |
|---|---|---|
| forecast_alpha.rain.v3 | forward test (gate on 2026-11-11) | paper |
| forecast_alpha.temp.v3 | failed | research |
| maker_spread.rain.v3 | forward test | paper |
| forecast_alpha.rain.v4 | forward test | research |
| settlement_certainty.temp.plan3a | failed | research |
| maker_spread.lowtemp.plan3b | failed | research |
| copy_trading.polymarket.plan4 | backtest | research |
| copy_trading.kalshi_large.plan4 | backtest | research |
| maker_incentive.weather.plan5 (test L) | idea; sampling starts 2026-10-24 | research |
| station_gap.temp.plan5 | idea | research |
| cross_strike.structure.v1 | forward test (descriptive) | research |
| meta_selector.accuracy_first.v1 | forward test (shadow) | research |
| orderflow.micro.v1 | idea (exploratory) | research |
| combo.copula.v1 | idea (exploratory) | research |

## 6. Dashboard upgrade
The control center sits below the existing sections:
- **Status line:** last ledger scan, last settle, decisions recorded, and a red TRADES BLOCKED line when a scan ran
  without its ledger.
- **Strategies:** every strategy with its state, win rate and count, and P&L. Labelled INTERIM - NOT ACTIONABLE.
- **Metrics by strategy:** settled count; win rate with count; profitable rate; net and per-contract P&L; realized vs
  expected; Brier; max drawdown; largest loss; holding time; profit per dollar per day; daily ratio; worst cluster;
  daily P&L correlation.
- **Latest scan:** reason counts in plain words, the shadow selector's verdict, and the best rejected candidates.
- **Calibration** of the v3 rain forecast, with 95% ranges.
- **Risk clusters and capital.**
- **Open positions at Kalshi prices:** best, worst and now, with research-only exit notes.
- **Market structure summary.**
- **Why settled trades won or lost** (post-mortem codes).
- **Audit trail:** each recent trade's exact snapshot.
- **Header chips:** kill switch, daily loss stop, rules changed, "Trades blocked: audit ledger", and live prices
  ("Prices update every 5 min", or "Not updating").

## 7. Test results
- **Cloud working copy (Python 3.12, Linux): 31 of 31 tests pass, 0 fail (2026-10-23, after refactor stages 1 and 2 and
  the reliability checks; the two new tests are test_freshness and test_ohlc).**
  - That includes the 19 tests that were on the PC before the upgrade. Their assertions are unchanged; test_ui.py
    now also writes a price snapshot first.
  - It also includes 12 new tests: audit, structure, longshot, engines, lip, discover, micro, combo, marks, tbcommon,
    freshness and ohlc.
- **On the PC's installed files** (r56, copied into the PC's Linux sandbox, Python 3.10; 2026-10-22 23:30 and
  2026-10-23 10:40): 28 of 28 pass. Not run there: test_ui, which needs Playwright and passes in the cloud. The run
  under Windows, `.\run.bat test`, still waits for the user: Desktop Commander cannot start on the PC, and computer
  use cannot open File Explorer.

## 8. Data integrity
- **`PRAGMA integrity_check`:** ok on paper.db and live.db (copies, 2026-10-22 17:46), and ok on paper.db read on
  the PC (23:00).
- **Backups:** backups\paper_20261022_174637_predeploy_r55.db and live_..._predeploy_r55.db were written, and their
  hash matches paper.db. Earlier backups are all kept.
- **Installed files:** r55 (41 files) and r56 (21 files) were read back on the PC and matched their manifests
  (backups\MANIFEST_r55.json, MANIFEST_r56.json).
- **Data:** paper.db is unchanged since Oct 15: 81 obs and 4 trades, 2 of them open from Oct 15, waiting for the
  first settle.

## 9. Forward test status
- **No test yet:**
  - station_gap.temp.plan5;
  - orderflow.micro.v1 and combo.copula.v1 (exploratory tools);
  - market discovery (a catalogue, not a strategy).
- **Backtest only:** copy_trading.polymarket.plan4 and copy_trading.kalshi_large.plan4 (data fetched, not yet scored).
- **Active forward tests:**
  - forecast_alpha.rain.v3 (gate on Nov 11; two market days logged before the outage);
  - maker_spread.rain.v3;
  - forecast_alpha.rain.v4;
  - meta_selector.accuracy_first.v1 (shadow);
  - cross_strike.structure.v1 (descriptive);
  - PLAN5 test L from Oct 24, if the hourly runner is approved.
- **Failed:** forecast_alpha.temp.v3, settlement_certainty.temp.plan3a, maker_spread.lowtemp.plan3b.
- **Confirmed:** none.

## 10. Safety status
- **Real-money lock unchanged.** live.py is byte-identical to the deployed version. Prod orders need a date on or
  after 2026-11-11 and the user's own typed unlock, recorded in live.db and the settings file.
- **Kill switch unchanged.** core.killed() is checked first by every trading step (tests/test_kill.py).
- **live.py not widened.** It still filters version v3 and KXRAIN, and imports none of the new modules
  (tests/test_audit.py checks this).
- **New strategies cannot place real orders.**
  - registry.may_trade_live() is false for every strategy.
  - No new module contains an order call (no POST, no portfolio endpoint; checked by tests).
  - Every research tool uses public GETs only.
- **$25 cap, limits and the frozen v3 rain model unchanged.**

## 11. Remaining limitations
- **Not yet run on the PC [PC]:** deployment, test run, migration, integrity check.
- **Format checks still needed** against live Kalshi answers:
  - The candlestick fields (lip.py, tbcommon/ohlc.py). They match Kalshi's API reference as read on 2026-10-23:
    yes_bid, yes_ask and price blocks with *_dollars strings (price fields null when nothing traded), and volume_fp.
    Not yet seen in a live answer.
  - The mve_filter parameter and mve_selected_legs (discover.py, combo.py).
  - The weather bucket encoding (structure.py's exhaustive check fails safe if it differs).
- **No websocket.** It needs an API key the user would enter, so order-flow research sees only 5-second polls and
  no cancellations. Joined-queue fills are therefore optimistic.
- **Not built:**
  - an inventory-managing dynamic quoting simulator (micro.py compares join, improve and cross per decision);
  - external lead-lag against Polymarket, futures or releases;
  - RFQ research (needs an API key);
  - PLAN5 test S (Polymarket keeps about 60 days of history, so it shortens daily);
  - depth-aware slippage on paper trades (v3 is frozen);
  - resolution, maker and test-L panels on the dashboard.
- **Liquidity rewards:** the account's eligibility is unknown, so rewards are reported but never counted.
- **The v3 gate's 50-settled-trades condition** is unlikely to be met by Nov 11 after the lost week.
- **A ticker listed twice in one scan** gets one decision row and cannot trade twice (documented in audit.py).

**Reliability checks (2026-10-23, docs/RELIABILITY.md):**
- **Data freshness:** freshness.py gives every dataset a refresh limit. It reports on the dashboard and in logs\tasks.log.
- **Historical candle anomalies:** research/ohlc_audit.py.
- **One time zone for every shown time:** La Paz, UTC-4.
- **Not yet seen against live data:** the OHLC audit's first real run and the clock measurement. Both run on the PC once
  the hourly schedule is installed.

## 12. Next best action
Move the scheduled scan, settle and hourly jobs onto the PC's own Windows Task Scheduler (with the user's approval,
since it is outside the folder). The cloud tasks would only publish the phone page. The largest loss of evidence so
far was not a model error: a usage limit stopped every scan for a week. Every forward test above depends on the PC
running on time.
