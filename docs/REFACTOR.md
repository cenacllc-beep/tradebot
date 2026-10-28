# Refactor: problem areas, strategy and stage 1 (2026-10-22)

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
