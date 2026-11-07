# Refactor: problem areas, strategy and stages 1 to 4 (2026-10-22 to 2026-11-06)

Brief from the user: improve code quality, scalability and maintainability **without changing functionality**. This
file is the senior-engineer review that drove the work. docs/ARCHITECTURE.md describes the system itself.

## Constraints that shape every change
- **Frozen until the 2026-11-11 verdict:** strategy.py, weather.py, nws.py, kalshi.py, core.py and config.py. Changing them
  mid-test would change the experiment being judged. They are reviewed and only described here.
- **live.py** is the only order path. It is not refactored without the user's explicit instruction, whatever the
  code-quality gain.
- **Pre-registered research scorers** (backtest*.py, plan3.py, plan4.py, placebo.py) keep their code. Their results
  must be reproducible from the code that was registered.
- **Proof of "no functional change"** (section 5) is required before anything ships.

## 1. Critical problem areas (most severe first)
| # | Area | Problem | Impact | Status |
|---|---|---|---|---|
| 1 | Reliability of the scan | kalshi.py, nws.py and weather.py make single-attempt HTTP calls with no retry. One timeout or 503 aborts `main.py scan`, and a market day is lost. | Lost forward-test days: the single biggest risk to the experiment | Frozen path. Stage 2 (section 3) |
| 2 | Duplicated HTTP clients | 11 hand-written request loops with drifted behaviour: different backoffs, one crashed on a date-valued Retry-After, no keep-alive anywhere. | Bugs fixed in one copy stay in the others; slower runs | Stage 1: the 5 newest research modules moved onto tbcommon.httpclient. The rest are in stage 2 and 3 |
| 3 | Duplicated business rules | The gate's stop date, clear-margin rule, t-table and final() were copied into dashboard.py with only one parity check. Taker-fee formulas were copied into 3 research modules. | The page could silently disagree with the bot; fee drift | Stage 1: a dependency-free gate.py feeds the dashboard and is locked to strategy.py's frozen copy by a parity test on 300 random inputs. The fee copies call fees.taker (proved identical on 1.68M inputs) |
| 4 | Quadratic hot loops | micro.analyze rescanned every trade and every earlier snapshot for each snapshot, and searched snapshots with Python loops (about a million lookups). | 72 s for a 36,000-snapshot recording, growing with the square of its length | Stage 1: bisect indexes. 7.9 s, linear, identical results |
| 5 | One-file presentation | dashboard.py was 680 lines with one 130-line main() mixing database reads, file reads, statistics, markup and the file write, plus 115 lines of inline CSS and JS. | Hard to change safely; slow to review | Stage 2 (done 2026-10-23): read_db, read_research, build_page (pure) and write_page, with named section builders; CSS and JS moved to dashboard_assets.py. HTML byte-identical |
| 6 | Import plumbing | 11 `sys.path.insert` calls; `from config import *` in strategy, core and shadow; scripts run from different working directories. | Fragile imports, hidden globals | Stage 3: one package, run with `python -m` |
| 7 | Hidden module state | Caches in nws.py (_pts, _fc, _gr), weather.RAW and nws.GRID_META are process-wide dicts. | Order-dependent behaviour; harder tests | Documented. Stage 2 moves them into explicit objects |
| 8 | Unbounded files | research JSONL logs, marks.jsonl and discovery.db grow forever; the ledger adds about 300 rows a scan. | Slow page builds and backups over months | The dashboard reads only 4 days of decisions. Stage 4: rotation and archive |
| 9 | Logs as interfaces | The cloud reporters parse printed lines ("AUDIT:", "TRADES BLOCKED", exit codes). | A wording change can break a report | Stage 3: structured JSON log lines next to the human ones |
| 10 | Dense one-line style | Many statements per line, single-letter names in the older modules. | Readability | New code (tbcommon) follows PEP 8. Old code is reformatted only when it is changed for another reason, to avoid big diffs in frozen or pre-registered files |

**What is already sound** (keep it):
- The order path is isolated in one file with its own locks.
- The decision ledger is append-only and enforced by triggers.
- Trades and their decisions are written in one savepoint (fail closed).
- Backups run before every migration.
- Every module has deterministic tests on fakes, and each research scorer has a planted-edge test and a null test.

## 2. Stage 1: what changed
| File | Change | Why |
|---|---|---|
| tbcommon/httpclient.py (new) | `JsonClient`: one GET client with per-module tuning (tries, timeout, spacing, pause, backoff), Retry-After handling (numeric or not), a keep-alive session and a request counter. Constructor-injected clock and sleep make it testable. | Problem 2 |
| tbcommon/parse.py, stats.py, jsonio.py (new) | One copy each of num, px, rts and cents; Wilson interval and clustered mean/SE; atomic JSON save and crash-tolerant JSONL. | Problem 2 |
| research/structure.py, lip.py, discover.py, micro.py, combo.py, longshot.py | Use tbcommon and fees.taker. Each keeps its module-level `http()`, `num()` and the other public names, so tests and callers are unaffected. Each keeps its own request tuning exactly. | Problems 2, 3 |
| research/micro.py | `BookIndex` (snapshot times, tops and mids; bisect lookups) and trade-time indexes. The fill walk starts at the first later trade, and nothing is copied. | Problem 4 |
| gate.py (new), dashboard.py | The gate rules live in gate.py (standard library only), which the dashboard imports. The page still renders when the trading modules are broken, exactly as before. If gate.py itself fails, a red "Gate rules unavailable" chip says so and no pass is ever shown. | Problem 3 |
| tests/test_fix.py | Adds a parity check: gate.py and strategy.py give identical answers. | |
| tests/test_tbcommon.py (new) | The client's retries, backoff, Retry-After, rate limit, errors and session fallback; parsing; statistics against the replaced formulas; file safety. | |
| tests/test_marks.py | A fixture fix, not a behaviour change. It wrote two marks 60 s apart 5 days ago and expected one per clock hour, which failed whenever the test ran in the last minute of an hour. Both marks now sit inside one hour. | |

Not changed: the frozen core, live.py, shadow.py, audit.py, selector.py, marks.py, control_view.py, account_view.py,
learn.py and the pre-registered scorers. (Verified by file comparison.)

## 2b. Stage 2 (2026-10-23): what changed
| File | Change |
|---|---|
| dashboard.py | main() split into: read_db() (read-only reads); read_research() (research summaries); build_page(tables, live) (the page, no writes); write_page() (atomic write); main(). The big block became named builders: last_scan_line, money_panel, latest_day, record_rows, status_chips. marks.jsonl is now read once per page instead of twice. 678 lines down to 583. |
| dashboard_assets.py (new) | The page's CSS and JavaScript, moved unchanged. |
| tests/golden.py (new) | The golden-master tool, now part of the project (`capture` and `compare`; standard library only) so any future refactor can be proven the same way. |
| tests/test_kill.py | Its no-core.py scenario copies the dashboard's own files into a bare folder; the list now includes dashboard_assets.py. The scenario still proves the page renders and shows the kill switch without core.py. |

**Proof.**
- golden.py on the original tree versus stages 1+2: 144,021 fields, 0 differences.
- The dashboard rendered from a copy of the PC's real paper.db is byte-identical (99,193 bytes once clock times are masked).
- The full suite passed in 6 of 7 runs. The exception was one failure in the run just after the test_kill fix, with no message kept. It did not recur in 4 more full runs or in 40 targeted reruns of the timing-sensitive tests.

**Stage 2 review (2026-10-23).** No MUST items. Fixed:
- A corrupt marks.jsonl could stop the page; that read is now guarded.
- golden.py skipped the whole page body as volatile. It now splits long lines, masks clock tokens and aligns text
  with difflib. A rerun compared 7,874 body pieces with 0 differences.
- A missing dashboard_assets.py now gives an unstyled page.
- test_kill now checks the gate without core.py.
- golden.py fixes for Windows.

The suite's occasional single failure was test_marks rounding a 0.1 s timestamp to whole seconds (failed for 1 clock
fraction in 20); fixed.

## 3. Strategy for the next stages
- **Stage 2, after the Nov 11 verdict, or earlier only with the user's OK:**
  - Have strategy.py import gate.py and delete its copy of the rules (the parity test then becomes trivial).
  - Move kalshi.py, nws.py and weather.py onto tbcommon.httpclient (retries and keep-alive). Proof: the v3 old-vs-new
    differential (60 random scans, identical trades and obs) plus fault injection.
  - Move shadow.py and marks.py onto tbcommon.
  - Turn the nws and weather caches into an explicit `ForecastCache` object.
- **Stage 3, structure:**
  - One `tradebot` package with `python -m tradebot.<module>` entry points; remove the sys.path inserts and the star
    imports.
  - Next for the dashboard: move the section builders into their own module once their inputs are typed (a
    PageData dataclass).
  - Write JSON log lines next to the human ones, for the reporters.
- **Stage 4, data lifecycle:**
  - Rotate research JSONL logs monthly.
  - Prune discovery.db rows settled more than 90 days ago (lifecycle rows kept).
  - Have the dashboard aggregate in SQL once obs passes about 100,000 rows.
- **Never:**
  - refactor live.py without the user's explicit instruction;
  - change a pre-registered scorer after its outcomes began.

## 4. Scalability notes
- **SQLite fits.** One writer at a time (the scan, then shadow, then backups, all in sequence), and readers open the
  file read-only. The hourly job writes only its own files.
- **Kalshi limits.** Every research client is spaced at 8 or fewer requests a second and backs off on 429.
- **A market-wide scan** (tens of thousands of markets) goes through discover.py's catalogue, never through the frozen
  scan. That is the extension point for future strategies, together with the registry and the ledger.

## 5. Proof that functionality did not change
Identical means identical within 1e-9 relative for floating-point values, with 0 and 0.0 treated as equal. Known
edge cases are listed after the proofs.

1. **Golden master.** Every output of 12 scenario suites (structure, lip, discover, micro, combo, longshot, engines,
   marks, audit, end-to-end, fix, shadow) was flattened into 144,068 fields: database rows, JSON results, Markdown
   reports, dashboards and printed output. It was compared before and after the refactor; fields that differ between
   two runs of the same code (timestamps, uuids) were excluded. Result: identical. The only differences were the
   names of backup files in one test's printout, which depend on the clock second.
2. **Large recording.** micro.analyze on a 12,000-snapshot recording: all 1,323 result values identical. Speed
   10.6 s before, 2.6 s after; at 36,000 snapshots, 72.1 s before, 7.9 s after.
3. **Fee formulas.** fees.taker equals the three removed copies on 1,681,576 price and multiplier inputs.
4. **Full suite.** 29 tests pass.
5. **Request pattern** (independent review). Each module's old and new `http()` was driven with a fake `requests`
   and a fake clock over 10 scenarios (200, 404, bad JSON, 429 with and without Retry-After, 5xx, network errors,
   running out of tries). URL, params, User-Agent, timeout, every sleep and every error text match.
6. **Fuzzing** (independent review). micro on 300 random recordings: equal timestamps, empty and crossed books,
   unordered trades. The dashboard is byte-identical on the same database once clock times are masked.

**Known edge cases (all deliberate and harmless):**
- **A Retry-After header of "0"** used to make structure.py retry at once; it now waits the 2 s backoff, as lip,
  discover, micro and combo always did. A non-numeric Retry-After no longer crashes structure.py.
- **Invalid JSON on a 200** now raises at once, instead of after the 0.1 s pause (structure.py) or 0.12 s (lip.py).
- **The clustered SE** uses math.sqrt rather than **0.5, so micro's values can differ in the last bit.**
- **Wilson bounds** at the extremes print as 0.0 and 1.0 in longshot.json, where they printed 0 and 1.
- **micro.fee1(None)** now returns None instead of raising. No call site passes None.
- **Keep-alive:** the research modules reuse one connection per run (faster, fewer TLS handshakes).

## 6. Stage 3 (2026-11-05): second review and changes
Brief from the user (2026-11-05): "act like a senior engineer who just joined a massive unfamiliar codebase ... do not
change functionality". The review below starts from the system as it runs today (docs/ARCHITECTURE.md, rewritten the
same day).

**Honest scale check.**
- **Size.** About 11,000 lines of application code and 6,000 of tests. It is not a massive codebase, and stages 1 and 2
  already removed most accidental duplication.
- **Where the risk is.** Most of what remains is in the frozen path, or is duplication on purpose. The rest is
  operations: data growth, three copies of the code, and logs that are read as an interface.

### 6.1 Critical problem areas, most severe first
| # | Area | Problem | Impact | Status |
|---|---|---|---|---|
| 1 | Code identity across three copies | The working copy, the public repository and the PC folder are kept the same by hand. On 2026-10-30 a stale file was deployed and only a test run caught it. There is no single command that says "these are the same code". | A silent mismatch between the PC (the official record) and the cloud copy, or an untested file in production | **Fixed:** manifest.py writes and checks a SHA-256 list of every code file, and docs/ARCHITECTURE.md section 6 makes it part of each deploy |
| 2 | Backup growth | Every evening writes 4 copies of paper.db plus a JSON export, inside and outside the folder. paper.db grows about 0.3 MB a day, so the daily backup volume grows too and the total grows with the square of time. backups\ held 187 files after 23 days. At a year: about 110 MB per copy and about 0.5 GB of new backups per day in each folder. | The laptop disk, the off-folder copy and the nightly phone-page upload | **Proposal, needs the user's decision:** keep every backup of the last 14 days, then one a day, plus every predeploy, premigration and gate-look copy; compress older copies. Deleting backups is the user's call, and the device bridge cannot delete anyway |
| 3 | Frozen-path reliability | kalshi.py, nws.py and weather.py make single-attempt HTTP calls. jobs.py retries the whole scan 3 times, which covers most network trouble, but one NWS timeout still costs a whole attempt. | A lost market day when the network is flaky for 15 minutes | Stage 2 item, now waits until PLAN7 ends (v3's code must not change while it runs; research/PLAN7.md section 3) |
| 4 | The gate's rules in two places | strategy.py keeps its frozen copy; gate.py feeds the dashboard and PLAN6. test_fix.py checks they are identical on 300 random inputs. | Drift if one is edited alone | Waits with item 3; the parity test stays until then |
| 5 | Logs read as an interface | The cloud reporters parse printed lines ("FRESHNESS:", "AUDIT:", "=====" job lines). | A wording change can break a report silently | Documented. Changing the reporters needs scheduled-task edits, which this environment cannot make; when it can, add a structured logs\last_runs.json next to the text |
| 6 | Research catalogue growth | research/data/discovery.db is 214 MB after about two weeks of 6-hourly refreshes. | Slower backups of the research folder and the PC disk; no effect on the bot | Stage 4 (unchanged): prune rows of markets settled more than 90 days ago, keeping the lifecycle rows. A deletion, so it needs the user's OK |
| 7 | Business values copied in presentation code | control_view.py had its own copy of the stop date (date(2026, 11, 11)). | The page could disagree with the gate if the date ever moved | **Fixed:** it reads gate.STOP_DATE |
| 8 | Hand-built read-only connections and ticker-date parsing | The same read-only SQLite URI was written out 8 times in 7 modules, and the market-day parser in about a dozen. | One fix had to be made many times | **Fixed where the rules allow it:** see 6.3. The remaining copies are deliberate (6.2) |
| 9 | Import plumbing | 19 `sys.path.insert` calls and `from config import *` in the frozen modules. | Fragile imports and hidden globals | Stage 3b: one package with `python -m` entry points. It touches every entry point that Task Scheduler and GitHub call, so it waits until the v3 freeze ends |
| 10 | Dense one-line style | Older modules (strategy, shadow, live, dashboard) pack many statements on a line. | Slower, riskier review | New code follows PEP 8. Old code is reformatted only when it changes for another reason, never in frozen or pre-registered files |

**Performance.** No bottleneck matters at this scale:
- the evening job takes about 3 minutes, most of it about 105 NWS calls and the candle reads;
- the hourly job takes 20 seconds to 3 minutes;
- the page builds in under a second.

The one quadratic hot loop found earlier (micro.analyze) was fixed in stage 1. Data growth (items 2 and 6) is the only
scaling risk.

**What is already sound (keep it):**
- the single order path with its own locks;
- the append-only decision ledger;
- trades and their decisions written together or not at all;
- backups before every migration;
- one job lock;
- the scan window and network waits;
- fail-closed defaults everywhere;
- deterministic tests for every module, with planted-edge and null tests for every scorer.

### 6.2 Duplication that stays on purpose
- **The stop date:**
  - strategy.py and gate.py: the frozen copy, with the parity test;
  - dashboard.py's fallback, used only when gate.py cannot be imported.
- **The read-only connection and the ticker-date parser:**
  - backup.py, export.py and check.py: operations scripts on the standard library only, which must work when anything
    else is broken;
  - dashboard.py and account_view.py: the page renders from a bare folder (tests/test_kill.py).
- **The bot's time zone** in account_view.py, for the same reason.
- **risk.py's own parser.** The frozen strategy.py imports risk.py, and the v3 path must not depend on tbcommon. A
  partial deploy would otherwise switch off the shadow selector's risk clusters without a word (code review).
- **marks.py's own connection and constants.** It was written to run with only the standard library and an optional
  config.py, for `run watch`.
- **Pinned copies in pre-registered scorers:** plan7.py copies the gate's statistic, the fill rule, the bootstrap, the
  fee and the rule values. nov11.py, shadow.py's forward-test blocks, lip.py, plan3.py and plan4.py keep their own
  code. A pre-registered rule must not change when a shared module changes later. Their copies are checked against the
  source by tests instead.

### 6.3 What changed (no functional change)
| File | Change | Why |
|---|---|---|
| tbcommon/db.py (new) | `connect_ro(path, row_factory=None)` and `uri_ro(path)`: one read-only SQLite connection. | Item 8 |
| tbcommon/parse.py | `market_day(ticker)`: one parser for the ticker's market day. | Item 8 |
| learn.py, freshness.py | Use tbcommon.db.connect_ro. | Item 8 |
| postmortem.py | day_start() uses tbcommon.parse.market_day; same results. (risk.py and marks.py were changed too, then restored after the code review; see 6.2.) | Item 8 |
| control_view.py | The stop date comes from gate.STOP_DATE. | Item 7 |
| manifest.py (new), tests/test_manifest.py (new) | The code manifest and its test. | Item 1 |
| tests/golden.py | The golden scenarios now include learn, freshness and ohlc. | Proof |
| tests/test_tbcommon.py | market_day, its agreement with risk.day_of's old parser on 500 tickers, and read-only connections. | |
| docs/ARCHITECTURE.md | Rewritten for the system as it runs (scheduling, cloud, gate look, PLAN7, deploys). | Maintainability |

PLAN7 (research/PLAN7.md, research/plan7.py, tests/test_plan7.py, one line in run.bat settle) is new research, not a
refactor. It was reviewed under its own plan.

**Known edge cases (deliberate and harmless):**
- `postmortem.day_start(None)` now returns None. Before, it raised AttributeError. No call site passes None: tickers
  come from database rows that always have one.
- The read-only URI is now percent-encoded the same way everywhere (pathlib's as_uri). Before, nov11.py used
  pathname2url, and it keeps its own.

**Proof.**
- **Golden master.** Captured on a copy of the code before the change, then on the change, then on the copy again, back
  to back.
  - 148,974 data fields: 0 differences.
  - 15,404 text pieces: 1 changed stretch. It is the shadow scenario's "per $ per day" figure, which rounds to +60.4% or
    +60.5% depending on how long the test runs. The code before the change gave both values on reruns (3 runs each),
    so it is timing, not the change.
- **Full suite:** 40 tests pass.
- **Parity:** tbcommon.parse.market_day matches risk.day_of's own parser on 500 random tickers.
- **Independent code review (agents/code-reviewer.md):** no functional change. Its own golden run gave 149,027 fields
  and 0 differences. It found:
  - one MUST: manifest.py dropped killswitch.py through a "KILL*" filter. Fixed: core.kill_file's own rule, top
    folder only, and the test checks every Python file of the project is listed;
  - SHOULD items, applied:
    - risk.py restored (the frozen path must not load tbcommon), and marks.py restored;
    - manifest.py includes the frozen research/results/rain_model.json, skips a manifest written into the folder and
      Windows clutter, and compares .github/workflows and .gitignore with their cloud/ copies in the repository.

### 6.4 Strategy for what is left
- **Now:** run manifest.py on every deploy. Decide on backup retention (item 2): this is the one growing risk.
- **When PLAN7 ends or is stopped** (its futility look is due about 2027-01-09 at the earliest):
  - stage 2's frozen-path work: retries and keep-alive for kalshi.py, nws.py and weather.py; strategy.py importing
    gate.py; the ForecastCache object;
  - then stage 3b: the package and `python -m` entry points.
  
  Proof: the v3 old-vs-new differential (60 random scans with identical trades and obs), plus fault injection.
- **Stage 4:** data lifecycle (rotation and pruning, with the user's OK), and the structured job-status file for the
  reporters.
- **Never:**
  - refactor live.py without the user's explicit instruction;
  - change a pre-registered scorer after its outcomes began.



## 7. Stage 4 (2026-11-06): third review and changes
The same brief came again on 2026-11-06 ("act like a senior engineer ... do not change functionality"), five days
before the first possible real-money orders. That timing sets the bar: only changes that can be proved to change no
output, and nothing on the order path or in the frozen forecast.

### 7.1 Scale and data flow, measured
- **Code:** about 6,200 lines of application code, 6,300 of research code and 5,800 of tests (41 test files).
- **Data on the PC:**
  - paper.db 3.4 MB;
  - backups\ 180 files, 105 MB;
  - research/data/discovery.db 238 MB, up from 214 MB a day earlier;
  - logs 1.1 MB.
- **Data flow:** unchanged from docs/ARCHITECTURE.md. Task Scheduler starts jobs.py. jobs.py runs the run.bat steps:
  the scan (main.py to strategy.py, the decision ledger and paper.db), then shadow.py, then `live.py mirror`. Backups,
  the export and dashboard.html follow; the cloud reporters read the log and the page.

### 7.2 Critical problem areas, most severe first
| # | Area | Problem | Impact | Status |
|---|---|---|---|---|
| 1 | Real money on a strategy with no demonstrated edge | Not a code problem, but the largest production risk. v3 runs low on rain; 27 of its 29 paper bets were "no rain", net -$6.91 of $15.98 staked. From Nov 11, live.py copies these bets (the user's decision of 2026-11-06). | Expected losses, capped at $25 at risk and a $2.50 daily loss stop | Told plainly. A live-only filter was offered (open). Every lock is unchanged |
| 2 | Research catalogue growth | discovery.db grows about 24 MB a day, about 9 GB a year | PC disk and backups of the research folder | Pruning is a deletion: proposal 6.1 item 6 waits for the user |
| 3 | Backup growth | 105 MB in 180 files after 24 days, growing with paper.db | Same | Retention proposal (6.1 item 2) waits for the user |
| 4 | Frozen-path reliability | kalshi.py, nws.py and weather.py still make single-attempt calls | A lost market day on a flaky network | Waits until PLAN7 ends (6.4) |
| 5 | Logs read as an interface | Unchanged (6.1 item 5) | | Documented |
| 6 | Long multi-panel functions | freshness.checks (96 lines), control_view.section (99) and dashboard.shadow_view (75) each built several independent panels in one body, and this week's fixes kept landing in them | Slow, risky review; one panel's variables leak into the next | **Fixed** (7.3) |
| 7 | Two new rule values in two places | TRADE_AFTER_LOOK and LOOK_DEADLINE live in strategy.py (the frozen copy) and gate.py (the dashboard's copy) | Drift | tests/test_fix.py checks they agree, the same pattern as the stop date |
| 8 | Golden-master false alarms | Backup copies named by the clock second, and 24-hour labels such as "Nov 07 00:22", showed as thousands of differences | A real difference could hide in the noise | **Fixed**: golden.py skips paper_YYYYMMDD_HHMMSS copies (the databases they copy are compared directly), masks those labels, and runs the gatelook scenario too |
| 9 | live.py (651 lines, dense style) | The only order path | A defect costs real money | Not refactored (rule). A static scan found no defect: the closure `skip` inside the order loop is called in the same iteration, so it binds the right order. Recommended instead: `.\run live status` and `test` on Nov 11, before the unlock |

**Static scan.** ruff (pyflakes, bugbear and pylint error rules) over every editable module found no latent defect.
The broad `except Exception` clauses are deliberate: the page and the jobs must fail safe. The remaining duplicated
functions sit in frozen or pre-registered code (backtest, plan3, plan4, plan7, plan8, stationfc, nov11) and stay on
purpose (6.2).

### 7.3 What changed (no functional change)
| File | Change |
|---|---|
| freshness.py | checks() now lists named sections in order: _backup_rows, _page_row, _marks_row, _lip_rows, _research_rows, _report_rows (19 lines instead of 96). |
| dashboard.py | shadow_view() is assembled from moves_panel, maker_panel and airport_panel. |
| control_view.py | section() is assembled from last_main_scan, status_parts, strategy_parts, latest_scan_parts, calibration_parts, risk_parts, position_parts, audit_items and postmortem_parts, in the same order (16 lines instead of 99). |
| tests/golden.py | The masks and the scenario in 7.2 item 8. |

**Known edge case (deliberate, unreachable):** control_view.section() used to read three tables before checking the
strategy registry, so an empty registry plus a missing table raised KeyError. It now returns "" first.
registry.REGISTRY is a non-empty constant, and dashboard.read_db always supplies the tables.

The same release carries the user's rule decision of 2026-11-06 (strategy.TRADE_AFTER_LOOK, LOOK_DEADLINE). That is
a deliberate behaviour change and is recorded separately in CHANGELOG.md; the proofs below compare code that already
contains it.

### 7.4 Proof
- **Golden master.** Captured on a copy of the old code, then on the new code, then on the old code again, back to
  back, across 16 scenario suites (including end_to_end, engines, freshness, shadow and gatelook):
  - 167,461 data fields: 0 differences;
  - 15,794 text pieces: 0 changed stretches.
- **Real data.** Built from copies of the PC's paper.db, live.db, marks and research files, with old and new code:
  - freshness.checks: identical;
  - the page: 173,399 characters, identical once clock times are masked, in both the normal and the --live build.
- **Full suite:** 41 tests pass.
- **Independent code review** (CHANGELOG.md, 2026-11-06 21:45): no functional change from the refactor. It swapped the old
  functions back in and compared on the real paper.db and 21 scenario databases, plus a symbol-table check. Its one
  MUST was a stale safety text from the rule change, fixed, with a test.

### 7.5 What is left
- The user's decisions:
  - backup retention and discovery.db pruning (7.2 items 2 and 3);
  - whether live.py should skip "no rain" bets when v3 itself says 50% or more (7.2 item 1).
- When PLAN7 ends: stage 2's frozen-path work, then the package and `python -m` entry points (6.4).
- **Never:**
  - refactor live.py without the user's explicit instruction;
  - change a pre-registered scorer after its outcomes began.
