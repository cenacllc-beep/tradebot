# CHANGELOG (every change, with timestamp)

(The original CHANGELOG was lost with the folder on 2026-10-13. Summary of the lost history, from the session record: v2 NWS-period rain estimator and version columns (Oct 12); dashboard.py added; exposure cap MAX_OPEN_PCT=0.15; v3 rain estimator with NWS hourly slices, station audit (Chicago rain corrected to O'Hare, 19 rain cities added), logging columns, gate = v3 rain only (Oct 13 ~00:00 local).)

## 2026-10-13 midday (local) - rebuild after data loss
- Found the project folder empty (modified 01:16), no paper.db, no backups, Python 3.8 stripped of its Lib folder (00:46). Searched user profile and Recycle Bin: nothing. User states they did not do it. Cause unknown.
- Recreated from the session record: config.py (with MAX_OPEN_PCT=0.15), core.py (fresh schema, version/market_type/logging columns), kalshi.py, nws.py, weather.py (v3 rain, 33-city RAIN table, temperature unchanged), strategy.py (VERSION v3, exposure cap, v3-rain-only gate, stop-date line), main.py (scan/settle/report only), requirements.txt, CLAUDE.md.
- Not rebuilt: peek.py, wallets.py, memecoin.py, sentiment.py (originals never reviewed this session).
- dashboard.py rewritten with a new design (still read-only: sqlite mode=ro, writes only dashboard.html). Replaces the user-supplied original; same gate rules.
- No estimator change: v3 logic is identical to the frozen version. Data before this entry is lost and is not reconstructed.
- Not yet run: no Python interpreter is available; nothing has been executed or tested since the rebuild.

## 2026-10-13 22:45 (local) - Python installed, test restarted, dashboard v2
- Environment (outside this folder, user-approved): Python 3.13.16 from python.org (embeddable build, PSF-signed) + pip 26.2.1 + requests 2.34.2 at %USERPROFILE%\Python313. The regular installer fails when started from the Claude app (its AppData writes are sandboxed), so this copy lives outside AppData. Lib\site-packages\tradebot.pth adds this folder to that Python's import path (its ._pth file otherwise hides the script folder). Desktop Commander: python/python.exe removed from blockedCommands at the user's request; delete commands and shells stay blocked.
- Tested before the real run, in a scratch copy with fake network data: scan/settle/report/dashboard run end to end; rain estimates make 0 Open-Meteo calls; the exposure cap held.
- 22:25: fresh paper.db created; backed up (backups\ and Documents\tradebot_backups); first scan of the restarted test: 41 markets logged (33 v3 rain, 8 temperature), all for Oct 14; 0 paper trades (largest gap 15.6 pts, below the ~16 pts plus spread needed); backed up again.
- dashboard.py (presentation only; gate rules, thresholds and the read-only contract unchanged): local times instead of UTC; "Last scan" tile; "what's next" line (settle day, next scan deadline = 05:00 UTC when Eastern markets start their day); backup status line (only lists backup file names/dates); forecast-vs-market chart limited to the latest market day with a result column; note explaining the edge needed for a paper trade; pace needed to reach the gate counts by the stop date; calibration now uses v3 rain only (it silently fell back to all markets before); cost column for open positions; P&L chart labels; chart scrolls on phones; fixed two Python 3.12+ deprecation warnings (utcnow/utcfromtimestamp).
- New backup.py: copies paper.db (SQLite backup API, read-only on the source) to backups\ and the off-folder directory with timestamped names; never deletes or overwrites.
- New run.bat: .\run scan | settle | report | dashboard | backup, using %USERPROFILE%\Python313. scan = backup, scan, backup, dashboard (stops if the pre-scan backup fails); settle = settle, backup, dashboard.
- README.md updated for run.bat. No change to config.py, the estimators, strategy or core.

## 2026-10-13 22:50 (local) - dashboard on the phone
- dashboard.py CSS only: dark colors now also follow an explicit light/dark setting (data-theme), not just the device setting; side padding written as padding-inline/block; layout children can shrink on narrow screens; on phones the Last scan tile spans the full width so no tile sits alone. Looks the same on the PC.
- A copy of dashboard.html is published as a private, pinned page in the user's Claude account so it can be opened on the phone. It is a snapshot: it changes only when someone republishes it after a scan or settle (the page's header shows when it was generated).

## 2026-10-13 23:20 (local) - win rate and gains/losses on the dashboard (user request)
- dashboard.py (presentation only): new "Win rate and P&L" section after the gate checks: win rate (won/lost counts), gains from winning trades, losses from losing trades, net after approximate fees, the break-even win rate implied by the prices paid, and a breakdown for rain (gate), temperature and all trades. Recent settled trades now show a Won/Lost column. Gate rules unchanged.

## 2026-10-13 23:40 (local) - dashboard redesign (user request)
- dashboard.py presentation rewrite. Data, gate rules, thresholds and the read-only contract are unchanged.
- Order of the page: a plain-language answer to the core question; the four gate checks with progress and the daily pace needed; a test calendar of the 12 market days that can settle by Oct 26 (settled, waiting for results, missed scan, upcoming, next scan); "What to do next" with times and the run.bat command; "Money and safety" (open positions vs the cap, P&L and the daily stop, backup status, kill switch); win rate and P&L; forecast vs market chart (gaps of 16+ points in bold, 25+ flagged, station in the tooltip, table view); score bars with the 0.25 coin-flip mark; cumulative P&L; records tables.
- Chart colors checked with a palette validator in light and dark; all text 4.5:1 contrast or better. System fonts only (Bahnschrift on Windows), so the page makes no network requests. Works at phone width.

## 2026-10-13 23:45 (local) - desktop shortcut (user request)
- Outside this folder, at the user's request: a "Tradebot Dashboard" shortcut on the Desktop that runs `run.bat dashboard` (rebuilds dashboard.html from paper.db, read-only, then opens it). No project files changed.

## 2026-10-13 23:55 (local) - automation, fee check
- Scheduled tasks created at the user's request (outside this folder): "Tradebot evening scan" daily 8:55 PM and "Tradebot afternoon settle" daily 2:51 PM, America/La_Paz. They run `run.bat scan` / `run.bat settle` + `run.bat report` on this PC, refresh the phone page and push a short summary. No code changes.
- Fee formula checked against Kalshi's fee schedule (July 2026 update): general taker fee round up(0.07 x C x P x (1-P)), weather markets on the general schedule, maker fee multiplier 0 by default. core.fee matches; whole-cent rounding is slightly conservative. CLAUDE.md section 8 updated; no code change.

## 2026-10-14 00:15 (local) - shadow tests (user request: "intelligently implement")
- New shadow.py (research only; never counts toward the gate; never writes to trades or obs; config, strategy, core, estimators unchanged and byte-identical):
  1. Price moves: each v3 market's mid at the start of its Kalshi day vs the mid at our scan, from Kalshi's public minute candlesticks (GET /markets/candlesticks on the existing API domain). Computed at settle.
  2. Limit-order (maker) ledger on a separate hypothetical $25 with the same blend, edge and size limits (own 15% cap and 10% daily stop): rests an order 1c better than the best bid (or joins it), cancelled at the day start, filled only if the minute candles show a trade or offer reaching our price after the order (strictly through it when joined). Maker fee 0 per Kalshi's fee schedule.
  New tables shadow_orders and shadow_moves in paper.db, created after a backup (preshadow). Tested with fake data: prices and sides, queue rules, fills before the order time and after cancellation ignored, cap, settle P&L, re-runs add nothing, v3 rows unchanged.
- run.bat: scan/settle/report run shadow.py after main.py; a shadow failure does not stop the backup or dashboard steps.
- dashboard.py (presentation only, still read-only): new "Shadow tests" section (price moves, limit orders vs the main bot); stat cells align to the top.
- Backed up before deploying (predeploy, preshadow). First shadow scan 00:07 local for Oct 14 markets: 39 checked, 1 limit order (NO PHIL x2 at 61c, cancelled at 01:00 local).
- Scheduled task prompts now include one line on the shadow results. Phone page republished.
- Found, not changed (main bot, user decides): core.state() measures the daily loss from trades opened since 00:00 UTC, so the 10% daily stop can never trigger at scan time.

## 2026-10-14 00:21 (local) - daily loss stop fixed (user approved), gate's clear margin measured
- Bug: core.state() measured the day's loss from trades opened since 00:00 UTC. Scans run at about 00:55 UTC and trades settle a day or more later, so that sum was always $0 and the 10% daily stop could never trigger.
- core.py: trades gets a settled_ts column (one-time ALTER TABLE, run only after a successful premigration backup; new databases get it in CREATE TABLE). state() now returns the net P&L of trades settled in the last 24 hours.
- strategy.py: settle() records settled_ts. scan(): when the daily stop is hit it opens no new paper trades but still logs every market to obs, so the forecast-vs-market test does not lose a day (before, the stop returned before logging).
- strategy.py report(): new CLEAR MARGIN line and the gate now requires it: forecast minus market Brier per market, averaged per market day, at least 5 days, mean below zero by 2+ standard errors. Before, any lead passed, which was looser than the written rule. Estimators and limits unchanged (still v3).
- dashboard.py (read-only): 'Last 24 hours' P&L with the same rule as the bot; a 'Daily loss stop' chip and note when it is on; the 'Forecast beats market' check uses the clear margin and shows the lead against the noise; verdict and score notes updated.
- Tested with fake data: migration on an old-schema copy (backup first, runs once), a losing settle turns the stop on, a stopped scan logs markets but opens no trade, the stop expires after 24 hours, margin math matches a hand calculation, full scan/settle/report/dashboard and shadow tests still pass.
- On the PC: backup (prefix) 00:21, files committed and hashes checked, run.bat report migrated paper.db after its own premigration backup; integrity_check ok; 41 obs, 0 trades, 1 shadow order intact. Phone page republished.

## 2026-10-14 02:00-02:40 (local) - market discovery fix, rules watch, backup scan, past-data test (user: "intelligently implement your recommendations")
- Bug fixed in kalshi.markets(): it read the first 6,000 of ALL open markets closing within 36 hours and dropped combo markets. Kalshi now lists 40,000+ open combo (KXMVE) markets, so at 02:10 it returned 0 weather markets; tonight's scan could have logged nothing. It now asks for KXRAIN and KXHIGH<city> for the cities the temperature estimator knows (exactly the markets the estimators can price): 77 markets at 02:12 (41 rain, 36 temperature). Estimators unchanged.
- shadow.py: rules watch. Each scan compares every weather market's settlement rules with the estimators' stations and with the wording seen before; changes are printed as RULES WARNING, stored in new tables rules_watch and rules_alerts (created after a backup), and shown on the dashboard. First live check: all 77 markets match (Houston rain settles on CLIHOU; it was CLIIAH until mid-August). Kalshi also lists Detroit rain now, which v3 does not cover.
- check.py + `run.bat check`: read-only, prints SCANNED / NOT SCANNED for the next market day. New scheduled task "Tradebot backup scan" 11:41 PM: scans only if the evening scan was missed and it is before 1:00 AM.
- dashboard.py: "Market rules" tile and a header chip when rules changed in the last 7 days.
- research/ (new, never touches paper.db): PLAN.md written before any data was fetched; fetch.py collects settled Kalshi rain markets with prices around scan time, NBM station forecasts (NBS) and NWS daily climate reports from the Iowa Environmental Mesonet (approved new source); backtest.py scores the holdout once by the plan.
- Scheduled task prompts mention RULES WARNING lines and treat a 0-market scan as a problem.

## 2026-10-14 02:40-03:15 (local) - past-data test result, airport forecast log, forward test
- Data collected on the PC (research/data): 1,972 settled KXRAIN markets with prices around 8:55 PM (Kalshi), NBS evening runs for 34 stations Jul 2025-Oct 2026 and NWS daily climate reports 2025-2026 (IEM). IEM's archive labels the evening run 19 UTC before 2026 and 18 UTC after: handled before scoring (PLAN.md amendment 1).
- research/backtest.py scored the holdout once (03:04): no edge demonstrated by the pre-set rule. Market Brier 0.0730, calibrated airport forecast 0.0740, blend 0.0711 (not clear); taker +6.9c a contract over 125 trades (not clear); limit orders +9.6c a contract over 153 fills (clear on its own). CLI and Kalshi outcomes agree on all 1,711 markets. Post-hoc checks written separately and labelled as such.
- stationfc.py (new) and shadow.py: the calibrated airport forecast is logged at each evening scan for every open rain market (v4_obs; polite retries, about 40 IEM requests), and the past-data strategy is worked out forward at each settle from Kalshi minute candles (v4_paper). Tested: identical numbers to backtest.py on the same inputs; re-runs add nothing.
- research/PLAN.md: result recorded; forward test of the lead pre-registered (judged after 60 market days, confirmed only if the limit-order P&L per day is above zero by 2 standard errors).
- dashboard.py (read-only): Past-data test panel (verdict, scores, trading results, forward-test tiles) and an airport-forecast block in Shadow tests; numbers are coloured only when they clear the noise. Phone page republished.
- Scheduled scan prompts allow up to 10 minutes and mention the airport-forecast count.

## 2026-10-14 09:40 (local) - off-hours guard for temperature markets; plan 2 written; fetch.py extended
- What happened: when the laptop reconnected, the "Tradebot evening scan" task ran at 09:22 local. Today's markets were still open, but their Kalshi day had begun at 01:00-03:00 local. The rain estimator skips such markets (v3 rule); the temperature estimator did not, so the bot opened 2 v3 paper trades on same-day temperature markets: KXHIGHDEN-26OCT14-T48 YES x53 at 1c and KXHIGHMIA-26OCT14-T84 YES x101 at 1c ($1.65 with fees). They stay in paper.db unchanged (temperature is exploratory and never in the gate) and are listed here so they are not mistaken for evening-scan trades. obs rows were not affected (the first snapshot is kept).
- strategy.py: new started(m); scan() skips any market whose Kalshi day has begun (close_time - 24h; close_time is local standard-time midnight for rain and temperature alike, checked on today's markets) and reports how many it skipped. This is the rule already written in CLAUDE.md section 6; shadow.py already followed it. Estimators, limits and config.py unchanged. Tested with fake markets (started, not started, unreadable close time) and the earlier fix tests.
- research/PLAN2.md (written 08:20 local, before any plan-2 data was fetched): temperature past-data test, overnight drift test, later-scan test, and the multiple-testing caution.
- research/fetch.py: new commands temp (settled KXHIGH markets since Jul 1 with quotes at the scan, the later scan and the day start), late (rain quotes at 03:30 UTC) and nbslate (00/01 UTC NBS runs, Jul-Oct 2026); wider station time-zone table; station read from the rules text when needed.

## 2026-10-14 10:00-12:20 (local) - plan 2 scored, temperature no longer traded, account view on the dashboard
- research/fetch.py: station also read from rules_secondary ("Data for CLIHOU ..."); candle requests that come back near Kalshi's 10,000-candle cap are asked again in halves; temp_stations.json lets the IEM downloads start early; shorter pause for historical candles. Data collected on the PC: 11,946 settled KXHIGH markets (Jul 1 to Oct 13), rain quotes at 03:30 UTC for 1,972 markets, NBS 00/01 UTC runs Jul-Oct 2026, NBS and CLI for the new temperature stations (KMDW, KSAN, KSDF ...).
- research/PLAN2.md amendments (10:10, before scoring): a temperature market needs its station named in its rules (primary or secondary); earlier markets that name only a place are left out. Forecasts for drift and later scan named.
- research/backtest2.py (new) scored plan 2 once (11:59): nothing clear. Temperature: market Brier 0.102 vs calibrated station forecast 0.122; paying the ask -4.4c a contract over 1,654 trades, limit orders -2.7c. Overnight drift: rain +0.1c, temperature -5.0c. Later scan: not better. Data checks: NWS reports agree with Kalshi on all 11,940 checked temperature markets; one YES in every complete city-day. results/plan2.json, plan2.md; frozen research/results/temp_model.json.
- strategy.py (user approved, 12:07): temperature markets are still logged but no longer traded; the scan line says so. shadow.py: the limit-order ledger mirrors this (rain only). v3 rain logic, estimators, limits and config.py unchanged. The two temperature trades from 09:22 stay open and settle normally.
- account_view.py (new, presentation only) and dashboard.py: "Paper account" panel at the top (value, change with arrow, step chart with a dotted start-of-range line, drag or arrow keys to read past values, 1D/1W/1M/3M/ALL, main bot or limit-order test), and an "Activity / Statements / Tax report" panel: every paper trade, monthly statements that reconcile (start, fees, gains, losses, end), a yearly gains-and-losses list; each downloads as CSV or a printable HTML copy, marked "Paper trading - not a tax document". Downloads use the phone page's downloads capability or a normal browser download on the PC. The old cumulative P&L chart is replaced by the account chart. Past-data panel gains a plan 2 summary. Read-only contract unchanged.
- CLAUDE.md: rain-only trading, off-hours guard, plan 2 result, tools decision (Herbie, ECMWF open data and scikit-learn not installed; Polymarket feed not pursued after plan 2), stop rules (section 11a).
- Tested with fake data: off-hours guard, rain-only trading and limit orders, earlier fix/shadow/end-to-end tests, backtest2 on synthetic data with and without an edge (recovers the model, verdict logic), fetch commands against a fake Kalshi, the account view on the real paper.db and on a 45-day fake ledger (chart ranges, scrubbing, statements reconcile, CSV/HTML downloads in browser and phone-page modes, 360-1100 px, light and dark).

## 2026-10-14 12:20-13:15 (local) - independent reviews by two agents from agency-agents (user: "consider github repo agency-agents as a multi ai agent")
- agency-agents (github.com/msitarzewski/agency-agents, MIT): a library of about 300 role prompts, no trading agents. Two adopted into agents/ unchanged with the license: statistician.md and code-reviewer.md. Each reviewed today's work as a fresh agent that had not seen it (read-only).
- Code review findings, fixed: (1) blocker: Kalshi and Open-Meteo requests sent python-requests' default User-Agent, against section 3 - kalshi.py, shadow.py and weather.py now send tradebot-paper-research/1.0 (weather.py's forecast logic unchanged; only the request header). (2) The data block in the dashboard escaped only "</", so an odd ticker could hide most of the page: now <, > and & are escaped and non-finite numbers are refused. (3) Nits: a two-part ticker no longer drops the account view; a settled trade without a recorded settle time says "date not recorded"; the limit-order ledger's cash counts money held by resting orders (as shadow.py does); CSV downloads start with a byte-order mark (Excel shows the degree sign) and text starting with = + - @ cannot run as a formula; the first left-arrow press steps back; save buttons hide if the phone page refuses downloads; unreadable close times are counted and reported separately from late markets, and close times with fractions of a second are read; fetch.py says when Kalshi returns no candles for a market; unused CSS removed. Verified: nothing can place an order, dashboard.py stays read-only, statements reconcile in every case built.
- Statistician findings and actions: (1) the forward test as written (60 market days) had about a 60% chance of confirming even a real 9.6c edge and about 20% for 5c: amended before any forward data (research/PLAN.md): quote window 00:50-01:30 UTC, futility look at 60 market days, verdict at 110 with a weekly block bootstrap; shadow.py now prints that statistic. (2) Many tests were run, so +9.6c is at best a 3-6c hypothesis: said so in PLAN.md, CLAUDE.md and on the dashboard. (3) No forecast-free control: research/placebo.py (post-hoc, labelled) shuffles the forecast between cities and runs a no-forecast rule. (4) The overnight-drift count is not evidence (mean reversion): qualified in CLAUDE.md and on the dashboard. (5) Gate checked daily with 2 standard errors from 5 days inflates false alarms: proposed to the user, not changed. (6) Reporting: temperature agreement is 99.98%, not 100%. Confirmed fine: no look-ahead, training and holdout separate, temperature result robust.

## 2026-10-14 13:30 (local) - gate judged once on the stop date (user approved), laptop-offline alert
- strategy.py and dashboard.py: the gate's clear margin now uses a Student-t critical value for the number of market days (never below the old 2.0) and the gate is judged once, on the stop date (Oct 26). Before that the report says "interim, not acted on" and the gate cannot pass. Reason (independent statistical review): checking 2 standard errors every day from day 5 lets a false pass through about 11% of the time instead of about 2.5%. This makes the gate stricter, not looser; thresholds unchanged.
- New Claude scheduled task "Tradebot laptop check" (runs in the cloud, needs no PC) at 3:25 PM and 9:25 PM: reads the phone page and sends a push notification only if the afternoon settle or the evening scan did not refresh it (laptop off, asleep or the app closed).
- Settle task prompt: the gate line is described as interim until the stop date.

## 2026-10-14 13:35-13:50 (local) - stop date Nov 11, off-laptop backup, tests folder, lid setting, notes cleanup
- Stop date moved from Oct 26 to Nov 11 by the user (28 market days, gate judged once on Nov 11), decided before any result existed. strategy.py STOP_DATE and dashboard.py STOP; the calendar wraps into rows of up to 15 days. "About 1 trade a day" wording fixed.
- export.py (new, read-only on paper.db): writes backups\paper_latest.json (and a dated copy) with every table; `export.py restore FILE NEW.db` rebuilds a database and refuses to overwrite anything. Round trip tested identical on a copy of the real paper.db. run.bat: scan now runs the export; new commands `run export` and `run test`. The evening scan task uploads the JSON to the phone page's private file storage (assets capability), so a copy lives off the laptop.
- tests/ (new): the automated tests used today (fix, off-hours guard, rain-only, end to end, shadow, forward test, export, fetch, plan-2 scorer, every dashboard control) with tests/run_all.py. All use fake data in temporary folders and never the real paper.db, the backup folders or the network. The dashboard click test needs Playwright and is skipped without it.
- Laptop power (user approved): lid close on AC changed from Sleep to Do nothing (powercfg, Balanced plan); on battery it still sleeps. Revert: Control Panel > Power Options > Choose what closing the lid does.
- CLAUDE.md: section 9 rewritten as a short current status; layout, routine and stop-date sections updated.

## 2026-10-14 14:30-15:30 (local) - Kalshi account connection and order placing (user request)
- User: "i need kalshi fully integrated by november 11 to fund, open and verify the Kalshi account". Answers: build it now and test on Kalshi's demo exchange first (cryptography install approved); real money unlocked by "my call on Nov 11" (the bot shows the gate verdict first); at most $25 at risk; skip the wipe-log check. This replaces the hard rule "No live order execution" (CLAUDE.md section 3 and new 3a).
- live.py (new, the only file that can place orders): signed Kalshi client (Ed25519 or RSA-PSS keys, as Kalshi documents), setup / test / status / demo-order / use / unlock / lock / resume / mirror / sync. Mirror copies new v3 paper rain trades: buy only, limit = paper price, immediate-or-cancel, count <= paper count, re-reads the market and skips if the price moved up or the day has begun. Limits: $25 at risk across the account (Kalshi's position exposure plus resting buys), cash check, daily loss stop $2.50, pause after a 25% drawdown until the user types resume. Real money: only on or after Nov 11, exchange set to prod, and `live unlock` typed by the user in a terminal (refuses scripts). Each paper trade is copied once; unknown outcomes are looked up, never re-sent, and block new orders until resolved. Key file outside the project folder (%USERPROFILE%\.kalshi), never printed; settings in %USERPROFILE%\.kalshi\settings.json or environment variables.
- live.db (new ledger next to paper.db). backup.py now also backs up live.db (both places). run.bat: scan runs `live.py mirror` right after main.py scan, settle runs `live.py sync`, new `run live ...`; a live.py failure never stops the backups or the dashboard. dashboard.py: read-only "Kalshi account" tile and header wording. config.py: comments only (LIVE_ENABLED is unused; KALSHI_BASE comment).
- tests/test_live.py (new): fake exchange that verifies every signature (both key types), header and order body; covers every lock, the cap, cash, skips, no double orders, unknown outcomes, rejections, settlement, loss stops, KILL, the unlock flow, backups of live.db, the dashboard tile, and that paper.db never changes. All 13 tests pass.
- Independent code review (fresh agent, agents/code-reviewer.md) before deploying. Found sound: the date lock, typed unlock, buy only, immediate-or-cancel, rain/v3 only, count cap, no resend after an unknown outcome, KILL, loss stops, signing and request format. Fixed: (1) a lost or restored live.db could let the same paper trade be sent twice, and could undo a later lock: the client order id is now fixed per paper trade, each copy first checks Kalshi for an earlier bot order or a position on that market, and the real-money unlock must also match a record in the settings file that `lock` clears. (2) `python live.py lock` run from another folder wrote to a different ledger: all paths now resolve to the project folder, and lock/unlock print the ledger path. (3) The $25 cap could read a renamed or missing Kalshi field as $0: missing exposure, balance or resting-order fields now stop the run, money used is never counted below fills x limit + fee, and an order answer without an order id or fill count is treated as unknown. (4) setup could print a private key pasted at the wrong prompt: key-looking input is refused without being shown, the key ID is validated, and key-file errors no longer show paths. (5) A live.db backup failure stopped the paper scan: backup.py now exits 3 for that case and run.bat scans on paper but skips the Kalshi copy (core.py and shadow.py accept 3). Minor: limit price rounds down (42.7c paper -> 42c, never above); unknown orders are looked up over the past hour and checked against positions before being marked never placed (after 30 minutes); daily stop uses the $25 cap ($2.50); a market with no status is skipped; Kalshi's error text is made printable on any Windows console; dashboard wording. place() now re-checks every lock and the match with the paper trade itself. Tests added for each (sub-cent prices, missing fields, partial fills, resting orders, crash mid-send, lost ledger, restored ledger after lock, setup input, piped unlock); a mutation check confirmed the tests fail when key safeguards are removed. Noted, not code: on Windows the terminal check on unlock is a speed bump; the real guard is the CLAUDE.md rule that Claude never runs unlock.
- Re-check by the same reviewer: findings 1, 2, 5-8 and 10 confirmed fixed. Fixed after it: an order answer with fills but no cost or fee fields is now stored at fills x limit plus the fee formula (never $0, so the loss stops see it), a looked-up order without a fill count stays unknown, and rows recorded from a position get an estimated fee; `lock` clears the settings mark first, so it locks even if live.db cannot be written; setup throws away the rest of a pasted key (Windows console) before exiting or asking again, so PowerShell never runs or saves those lines, and Key IDs must be UUIDs; run.bat treats backup exit codes of 4 or more as a failure (only exactly 3 means "live.db only"). Tests: piped unlock refused even with the date set to Nov 11; lock with a broken live.db; missing cost fields.
- Deployed 14:32-14:50 after a backup (paper_20261014_143224_predeploy_live.db); file hashes checked; `cryptography` 50.0.2 installed on the PC; all tests pass on the PC (the dashboard click test needs Playwright and is skipped there), paper.db unchanged; run.bat's backup exit-code branches (0, 1, 3, 4, 120) checked under cmd.exe on the PC. Polish: `live status` says "none (no account set up yet)" before setup, and the dashboard tile stays "Not connected" until setup. Scheduled tasks (settle, evening scan, backup scan) updated and re-signed: they mention any Kalshi account lines, never run unlock/resume/use prod, and after the stop date the evening scan keeps running only if the user has unlocked real money themselves.
- 16:10: setup, unlock and resume now say plainly that PowerShell ISE cannot answer typed questions and show the exact commands for a normal PowerShell window (the user's first setup attempt was in ISE).
- 17:40-20:47: setup opens its own console window when started from PowerShell ISE (only setup does this; unlock and resume never open windows), and pressing Enter at the key-file question finds the key (default name, the hidden double ".txt.txt" ending, or the only key file in %USERPROFILE%\.kalshi). The user connected the demo account at 20:40 (key file kept in Downloads; connection test OK, $25.00 fake cash).
- 20:45: Kalshi's demo exchange refused the first demo order with HTTP 410 "deprecated_v1_order_endpoint": the old POST /portfolio/orders is retired. live.py now uses Kalshi's V2 order endpoint POST /portfolio/events/orders (side bid/ask on the YES leg, fixed-point count and price strings, required self_trade_prevention_type taker_at_cross). Buying NO at p is sent as an ask (sell YES) at 1 - p, which opens a NO position. The V2 answer has fill_count, average_fill_price (YES terms) and average_fee_paid but no status or cost totals, so status is derived (executed/partial/canceled), cost = fills x price (1 - price for NO), fee = fills x average fee; missing or implausible values fall back to fills x limit + the fee formula (never less). Fractional contract counts are kept. demo-order takes "no" and reads the position back. run.bat passes a third argument to live.py. Tests: the fake exchange now speaks V2 and returns 410 on the old endpoint. Backed up (paper/live_20261014_204655_predeploy_v2.db), deployed 20:47 before the 8:55 PM scan, all tests pass on the PC.
- 20:52: real demo check: 1 YES at 39c filled (position +1, cost $0.39, fee $0.0167) and 1 NO at 11c filled as an ask at 89c (position -1, cost $0.11, fee $0.0069). This confirms the V2 shape, that average_fill_price is in YES terms, and that an ask from no position opens NO. Kalshi's actual fees were below core.fee's whole-cent round-up, as expected. An independent review of the V2 change was started after deployment (deployed first so tonight's demo copies would not be refused).
- Noted from Kalshi's changelog (June 30, 2026): API keys can carry a write::trade scope (orders without transfer/withdrawal access). Advised the user to choose trading-only for the real key if offered.
- 20:59: first mirrored demo order from the evening scan: KXRAIN-26OCT15-DEN NO, 5 asked at 12c, 1 filled at 11c (partial, fee $0.0069); PIT skipped (no demo price).
- 21:00-21:15: independent review of the V2 change (fresh agent, agents/code-reviewer.md): no blocker; all locks and limits hold (date lock, typed unlock, duplicates, unknown outcomes, price on both sides, count, $25 cap). Fixed: (1) holding() now fails closed when Kalshi's position answer lacks its fields (a NO copy is a YES sell, so this check guards against selling YES the account holds); reduce_only deliberately not used (it would forbid opening positions). (2) demo-order: "no" counts wherever it is typed, and a named market that the account holds or the bot copied is refused (a NO test there would sell the copy); auto-picked markets skip those too. (3) record() trusts average_fill_price only in the V2 create answer (verified YES terms); orders found later through GET are costed at the limit (upper bound). New: each sync compares Kalshi's position in every open market with the ledger and stops new orders on a difference until a later sync agrees or the user types resume. (4) the in-run risk tally never counts less than fills x limit + fee. (5) a 201 answer that is not an object counts as unknown, not a crash. (6) setup --window keeps the exit code. (7) setup tests the key with Kalshi before saving anything, re-reads the settings just before saving, asks before using a key file it found, skips files named for the other exchange or already used by it, and when connecting the real account asks whether to keep copying to demo (default yes). (8) at_risk counts resting sells/asks (which can open NO) as well as buys, in both the V2 and the older listing shapes. CLAUDE.md section 3 updated for the write::trade key scope. Tests added for each; all pass.
- 21:19: the user connected the real Kalshi account (setup with prod; key file in %USERPROFILE%\.kalshi; Kalshi accepted the key; cash $0.00, not funded yet). The user chose to keep copying to demo, so the active exchange stays demo. 21:20: read-only check on prod (balance, positions, resting orders) passed. Trading permission can only be confirmed by an order, which stays locked until Nov 11 and the user's unlock; a missing permission would show as a refused order, not a loss.

## 2026-10-14 21:55-22:40 (local) - learning report, market research, PLAN3 (user: "we need to identify patterns, even for the trades we lost... apply your recommendations... obtain the Polymarket price gaps")
- learn.py (new, read-only on paper.db and live.db): every settled trade gets a story (forecast beat the market, market beat the forecast, favourite won, upset, long shot hit/missed) and a situation known before the outcome; wins, losses and profit per contract by situation, side, price, edge and city, next to the win rate the price implied; day-clustered errors; "too few" under 30 trades or 10 days; "worth a written test" only at |z| >= 3 (many groups). Covers paper trades, the forecast-vs-market log, the shadow limit-order ledger, the Kalshi account's execution (fills, prices vs limit, skip reasons) and, with --past, the 1,711 past rain markets (labelled post-hoc). run.bat: `run learn`, and settle runs it after the shadow settle. tests/test_learn.py.
- Past-data findings (hypotheses only): taker losses were mostly "market beat the forecast" (29) and long shots that missed (23); the forecast said 28% on long shots that happened 16-21% of the time; 12-20 point edges did worse than 8-12; maker NO side and maker "both said likely" at z 2.7, below the bar.
- research/markets.py (new, read-only public data; Polymarket gamma API approved by the user): Kalshi snapshot (138,793 open markets in 4,692 series, combos excluded) and inventory (research/results/inventory.md; weather: KXRAIN about 1.4M contracts a day at 1c, KXHIGH* at 1c, KXLOWT* thin at 3-20c spreads); Polymarket snapshot (2,100 busiest markets; the API refuses offsets past about 2,000); candidate matching and 99 hand-checked pairs (research/data/pairs.json). Result (research/results/gaps.md): identical questions (Fed Oct/Dec, House/Senate 2026, Ballon d'Or, LoL Worlds) within 0.3-2 points, no pair under $1.00 after both venues' fees; small locked gaps only on long-dated political markets (Vance 2028 nomination 2.4c per dollar, AOC 1.2c, TIME Person of the Year about 0.6c); temperature pairs are different measurements (Polymarket airport hourly readings vs Kalshi's NWS climate report), not mispricing.
- research/PLAN3.md (new), written before any of its data: A late-day temperature ("already happened", 2-degree margin, three fixed looks, 2.5 SE bar), B low-temperature markets with limit orders (model frozen before the holdout), C three forward checks of learning-report patterns on trades from Oct 15 (scored once on Dec 15). Independent statistical and code reviews started before anything is scored.


## 2026-10-14 22:40-23:30 (local) - review findings applied before anything in PLAN3 was fetched or scored
- Independent code review of learn.py (applied): the shadow ledger is read with its own forecast and quote; the reading uses profit after fees, not the edge before fees; identical results every day count as a signal, not as "no error"; the forecast-vs-market table uses v3 only; the Kalshi section separates placed, not placed and skipped orders; the past section uses the frozen rain model; tests run in a temporary results folder (TRADEBOT_RESULTS).
- Independent statistics review of PLAN3 and learn.py. Findings and what was done:
  - learn.py flagged too easily. It runs after every settle and compared each group with zero, so a lucky streak, or the overall lead seen in its biggest slices, would eventually be flagged. Now a group is flagged only if its profit after fees is away from zero AND from the rest of its breakdown, each by a Student-t cutoff with a Bonferroni correction for the G groups screened in the report (alpha 0.05/(2G)), and both still hold with weekly clusters (runs of similar weather). Overall rows are never flagged; groups need 30 trades, 10 market days and 4 weeks. Past-data items are tagged "[past, post-hoc]". The report and the LEARNING line say it is a screen, not a test. "Our forecast said" is renamed "Blend said" (it is the 50/50 blend). The Student-t is computed in plain Python (the PC has no scipy); tests check it against table values.
  - Two earlier readings withdrawn: "the forecast overrates long shots" was a selection effect (trades are chosen where the blend is above the price); the maker "NO side" and "both said likely" groups were the overall limit-order lead in its largest slices.
  - PLAN3 revised before any Test A or B data (the changes are listed at the end of PLAN3.md). A: all three strike types ("less than" markets were missing), plan-2 market set and dedupe, exact definition of the running maximum M and the 3-report rule (no 6/24-hour groups), the price is a candle close never a low, a one-sided 95% bound on the loss rate below break-even, and a leave-one-station-out check. B: no spread cap, TXN at 12 UTC (TNN is not an NBS element), a fill needs a trade through our price, a placebo (forecast replaced by the mid) that B must beat, the taker version descriptive only, a power note. C: moved to the lead's own ledger (v4_paper), made descriptive (no pass/fail), C1 dropped.
- research/markets.py (code review, applied): retries only rate limits, server errors and dropped connections, and gives up after repeated 429s; a missing 24h volume no longer stops paging; Polymarket markets with fees on but no published rate are charged a conservative 7%, and the fee schedule's exponent is applied; pairs whose Polymarket market is missing from the snapshot are read one by one; both venues' prices must satisfy 0 <= bid < ask <= 1; gaps.md shows the snapshot times and says results are for one contract at the best ask; pairs.json may carry a byte-order mark; console output cannot crash on unusual characters. tests/test_markets.py (fake network).
- No change to the bot, v3, config.py, live.py, the limits or the gate.

## 2026-10-15 10:00 (local) - kill switch fixed (user: "the kill switch is not wired/working")
- What was wrong: each file checked for a file named exactly "KILL" in the folder it was started from. A file made in Explorer with New > Text Document is really "KILL.txt" (Windows hides the ending), so it did nothing; and running a script from another folder ignored a KILL file in the tradebot folder. run.bat also went on to start every step, relying on each one to notice. Settling never checked it (it does not trade).
- Now: core.kill_file() is the one rule, used by main.py (strategy.scan), shadow.py, live.py (before any order and again before each one), dashboard.py and check.py. It finds KILL in the tradebot folder (and the current folder), in any letter case and with any ending (KILL, KILL.txt, kill.txt.txt).
- run.bat scan checks the switch first. When it is on (or cannot be checked) it runs only a backup and the dashboard: no scan, no paper trades, no Kalshi copy, no shadow orders. It prints "KILL SWITCH ON ...".
- run.bat settle prints the same line and still records results, because settling never trades.
- New: killswitch.py with `.\run kill` (on), `.\run kill status` and `.\run unkill` (off; typed by the user). check.py reports HALTED (exit 0), so the 11:41 PM backup scan does not try to make up a halted scan. The dashboard tile and chip say "kill switch" and how to resume.
- tests/test_kill.py: names and folders; that halted scans of the main bot and shadow tests read no markets and open no trades; live.py's lock; the dashboard; check.py. On Windows it also runs run.bat in a scratch copy: scan halted, kill, kill status, unkill. Kalshi points at a closed port in that copy, so nothing could trade even if the switch failed.
- CLAUDE.md section 3: the kill-switch rule. Claude turns it on when asked and never turns it off.
- Scheduled tasks: the evening scan, backup scan and settle prompts now report a halted bot plainly and never turn the switch off.
- Independent code review (10:05) before shipping. It confirmed that no path places a paper trade, a shadow order or a Kalshi order while the switch is on (the only POST is in live.py place(), which re-checks), and found six problems, all fixed:
  - MUST: an unreadable tradebot folder read as "off". It now counts as ON (fail closed).
  - MUST: `unkill` could delete files outside the tradebot folder, or any kill.* file. It now removes only files named KILL or KILL.txt in the tradebot folder; anything else is listed for the user to delete.
  - `kill` and `kill status` looked at the current folder. They now use the tradebot folder only.
  - The test suite failed in confusing ways while the switch was on. It now stops first and says so.
  - A failed check halted the scan but exited 0. It now exits 1 with "Could not check the kill switch", and the halted message is ASCII-safe for piped output.
  - `unkill` now refuses scripts and asks the user to type yes. The halted scan also runs export.py, so the off-laptop copy stays current.
  - Tests added for each, plus live.py checks: place() called directly, demo-order, a kill file in the tradebot folder while started elsewhere, and a kill file appearing mid-mirror (orders after it stop). On Windows the run.bat test now also covers the switch-off path, "Could not check", refusing a piped unkill, and `kill off`.
  - Left as is (noted): a kill file made in the middle of a scan stops Kalshi orders at once, but the paper and shadow steps check only when they start. While halted the forecast log does not run, so each halted evening loses a market day for the test.
- No change to v3, the limits, the gate or live.py's other locks.
- 10:40: on the PC, the run.bat test showed two things. (1) A scratch copy of the code imports the real tradebot folder through tradebot.pth (the embeddable Python ignores PYTHONPATH and the script's folder), so the Windows test now runs only commands that cannot write into the real folder unless the copy is isolated. (2) A NUL input counts as a console on Windows, so `unkill` now requires both input and output to be a console, the same rule as `live unlock`.

## 2026-10-15 11:00 (local) - PLAN3 tests A and B: code written and reviewed, nothing fetched or scored yet
- research/plan3.py (new, research only; never touches paper.db or live.db; no orders). Commands:
  - Test A: asos, candlesA, scoreA.
  - Test B: lowlist, lowiem, fitB, candlesB, scoreB.
  - Each scorer refuses to run a second time, and fitB never refits.
- tests/test_plan3.py (new): synthetic edge and null runs, both in `.\run test`. In the B null case the limit orders "profit" from the spread alone; the placebo and the forecast-accuracy check (Brier) correctly fail it.
- Independent code and statistics review. It confirmed:
  - the scoring matches PLAN3;
  - the exact binomial bound (checked against a direct sum);
  - the order rules (identical to backtest2.entries over 200,000 cases);
  - the time arithmetic.
- The review's fixes, all applied:
  - **Stale quotes:** a stale quote could pass the freshness test through Kalshi's "latest candle before the start". The window now starts an hour earlier. Plan-2 data confirms Kalshi stamps that candle exactly at the start.
  - **Completeness:** nothing is scored or frozen until every market's data is in (at most 2% of markets may have no candles after a retry; those are listed).
  - **Candle requests:** a failed batch or an empty answer is asked again one market at a time (live, then the archive), and a market with no candles is asked again on the next run.
  - **No retry on fixed errors:** 4xx answers other than 429 are not retried.
  - **NBS fetching** now resumes for every low-market station.
  - **Data checks for B:** Kalshi's results are checked against the climate-report lows. If they agree in under 95% of markets, B is not scored.
  - **Two more:** the 3-report rule counts distinct report times, and duplicate rows are removed.
  - **Report additions (descriptive):**
    - losses among every decided market;
    - losses by station-day;
    - the climate-report disagreements listed.
- PLAN3.md's revision notes record each change. All were made before any A or B data was fetched.
- **Format check, IEM:** its airport temperature is the whole-degree F value the METAR's tenths-of-a-degree-C group encodes, so the rule is unchanged.

## 2026-10-15 11:19 (local) - PLAN3 test A scored once: FAIL (nothing to buy)
- Data: airport readings for all 24 stations (about 27-31 reports a day); Kalshi quotes at the three looks for the 2,727 KXHIGH markets the readings had decided by 13:00, 15:00 or 17:00 local standard time. Every completeness check passed (no missing quote rows, no market without candles).
- Result (research/results/plan3_A.md): 0 trades.
  - In 6,176 decided looks with a fresh quote, the decided side could not be bought below $1.00: YES asks were at 1.00, and YES bids for decided-NO markets were 0.
  - One look was at 99c, above the 97c cap. 592 looks had a stale quote; 132 had too few airport reports.
- Descriptive: all 2,727 decided markets settled on the decided side (0 against). The readings were right every time, but the market had already priced every one in fully.
- Conclusion: there is no lag to trade at these look times. Faster looks would be a race against Kalshi's existing bots, which was not tested and is not planned.
- PLAN3 test B: model frozen 11:16 (research/results/low_model.json: a -0.56, s0 1.20, s1 0.93; 8,745 training station-days); low-market quotes downloading.

## 2026-10-15 14:50 (local) - PLAN3 test B scored once: FAIL
- Data checks passed:
  - Kalshi's results agree with the NWS climate-report lows in 13,786 of 13,788 markets.
  - No rule-strike mismatch, and exactly one YES per city-day (2,299 city-days).
  - 46 markets came back with no candles (0.3%).
- 11,398 usable markets on 105 market days (median spread 4c).
- Results:
  - Limit orders lost 3.6c per contract (t -3.75; 2,317 fills, 50% of 4,629 signals).
  - The market beat the frozen forecast on Brier (0.119 vs 0.144; t 18).
  - The orders did worse than the placebo by 0.8c per usable market per day.
  - Paying the ask lost 6.3c per contract.
- Descriptive only: the placebo (posting at the mid on wide spreads) made +4.9c over 179 fills. That is spread capture seen after scoring; it is a hypothesis, not a result.
- Conclusion: no edge on low-temperature markets. As with the highs in plan 2, Kalshi's prices beat the station forecast.

## 2026-10-15 15:15 (local) - PLAN4 code review applied (before any PLAN4 data)
- An independent code review of research/plan4.py found these problems. All were fixed before any PLAN4 data was fetched. PLAN4.md now states each rule exactly (its 15:10 revision notes):
  - **Placebo reweighting:** per-copy weights by price tenth, with sparse tenths pooled. One weighted SE over the placebo's events. A test caught that the first version averaged events equally, which ignored the weights; core statistic cl_se now takes weights.
  - **Position coverage:** counts only the scored rows (CLOSED and REDEEMABLE). Markets still open leave the denominator. A resolved holding missing from the scored walk counts against the wallet.
  - **Format check:** also checks that losing rows are present, that REDEEMABLE_LOST is a subset, and that there are no duplicate rows. It also reads whether total_pnl includes fees; if not, they are subtracted.
  - **Eligibility:** split/merge activity is checked for every eligible wallet, not only the top ones.
  - **Kalshi:**
    - fee written out as 0.07 x multiplier;
    - the series list is not frozen with a missing or off-scale fee multiplier, or missing volumes;
    - the next order may not be a block trade;
    - one copy per hour by copy time;
    - market date falls back to the close date;
    - zero-price orders dropped.
  - **P2 copy price:**
    - the highest fill in the first matching second;
    - each copy's hour must be inside the walked trade list. A newest-first walk covers everything after its oldest row; the first version wrongly dropped copies in a market's last hour.
  - **Failures are not cached:** a failed position, trade or Kalshi trade fetch is not saved and is retried. Unresolved markets are asked again at scoring.
- tests/test_plan4.py rewritten. New coverage:
  - time formats;
  - weighted SEs;
  - wallet-events;
  - format and coverage checks;
  - trade-list walks in both directions and the 200-page limit;
  - copy prices;
  - placebo pooling;
  - Kalshi orders, copies, series and trade fetches against fake pages.
- Tests: edge world passes P1, P2, P2c and K1; null world fails all four. 20 extra null seeds: no pass (largest t 1.09). Full suite passes.

## 2026-10-15 15:35 (local) - PLAN4 format check: combo flag (before any PLAN4 data)
- The first fetch (pmarkets) stopped with HTTP 422. A format check of Gamma's market list showed why: every market carries comboStatus "enabled" or "disabled". That field says whether a normal market may be a combo leg, so the code had treated every market as a combo and paged on to an offset Gamma refuses.
- Fix: a combo is a market with cyom set, or a combo condition ID (31 bytes, 62 hex digits instead of 64). This is used for the formation markets, the P2 market details and P1 positions (counted). PLAN4.md revision note 9.
- Fee schedule checked on live markets: feeSchedule {rate, exponent}, for example sports 0.03 and finance 0.04 with exponent 1. This matches Polymarket's published formula: fee = C x rate x p x (1-p).
- Tests now use real-length condition IDs, plus Gamma-shaped fake pages for pmarkets and gamma_meta. Both worlds and the full suite pass.

## 2026-10-15 15:55 (local) - PLAN4 second code review and format checks (before any PLAN4 data was scored)
- A second independent code review (agents/code-reviewer.md) and a format request to each source found these problems. All are fixed in research/plan4.py; PLAN4.md has the rules and its 15:55 revision notes.
- **MUST, fixed:**
  - **Resolutions:** /v2/resolutions has no resolved_at field. The old code would have found no resolved markets, so P1, P2 and P2c would have been burned as "not testable". Now it uses the resolved record's last_update_timestamp, plus epoch time parsing.
  - **Selection:** it could freeze an empty selection. Now nothing is frozen with fewer than 250 eligible wallets, and the format check verifies first_entry_at units, end dates and event IDs.
  - **Data checks before saving any score:** resolution records, payouts, Gamma details, and Kalshi prices (cents read too).
- **SHOULD, fixed:**
  - fresh snapshots for the format and coverage checks;
  - a CLOSED-row check;
  - split/merge counts only those types;
  - no formation buys counts as a coverage failure;
  - both Kalshi trade endpoints merged by trade_id (new folder data/k1/trades2);
  - the fee type is checked (KXMLBGAME has quadratic_with_maker_fees, multiplier 0.5);
  - the next-order search stops after an hour (it was quadratic);
  - (condition, outcome) duplicates are informational only.
- **NOTES, fixed:**
  - unresolved wallet-events are counted;
  - coverage and the subset test are matched by (condition, outcome);
  - a trade list failing 3 runs counts as "no trade list";
  - Gamma misses are asked again;
  - a cursor with has_more missing is followed;
  - orders are sorted by (time, created_time);
  - positions without a token are deduplicated by (condition, outcome, status).
- **Format check findings:**
  - CLOSED rows' total_size is the total bought, so cost = total_size x avg_price is right.
  - Rows from splits, conversions or transfers have total_size 0; they are now left out and counted.
  - Activity type filter works.
  - Resolutions and tokens have no pagination object.
  - Kalshi trades have trade_id and dollar prices; the archive cutoff is 2026-08-16.
- **Process:** the Kalshi series listing (old code) was stopped by hand before it saved anything. The Polymarket fills download (ppool) kept running; it is unaffected by these changes. New file research/plan4_formatcheck.py. research/plan4_run.ps1 runs the fetch chains detached.
- Tests: tests/test_plan4.py covers each fix. Edge world passes, null world fails.

## 2026-10-15 16:20 (local) - PLAN4 fetch limits (before any data was scored)
- ppositions finished only 4 of 2,000 wallets in 19 minutes. The pool's top wallets are heavy bots; one positions file is 114 MB.
  - New eligibility rule (PLAN4.md, 16:20 revision): a wallet with more than 10,000 rows in its CLOSED or REDEEMABLE walk is not eligible, and is counted.
  - The walk stops at that point. The 4 wallets already fetched in full are judged by the same counts.
- The Kalshi series listing passed 2.5 million markets and 1.5 GB of memory. It now runs in two passes:
  - pass 1: volume per series only;
  - pass 2: the 40 chosen series one by one, with a count check.
  - It was stopped before saving anything.
- Long walks print progress every 50 pages.
- Both fetch chains were stopped and restarted with this code. Fills (ppool) and the 4 position files are kept.
- Tests cover the cap, truncated files and the two-pass listing.

## 2026-10-15 to 2026-10-22 - what happened while the session was paused
- The account hit its weekly usage limit on Oct 15 at about 8 PM. Every scheduled scan, settle and backup scan failed from the Oct 15 evening scan until Oct 21.
- After that the PC-bound tasks were suspended as "device absent".
- paper.db shows no scan after the Oct 14 evening scan: 81 obs rows, the last at 2026-10-15 00:56 UTC. The forward test has 2 market days, not 9.
- The PLAN4 fetch had finished, apart from pselect. pselect stopped at its format check: 12 REDEEMABLE_LOST rows were not in the REDEEMABLE walk.
- 2026-10-22 09:10: all three PC tasks re-enabled. The kill switch is OFF; an earlier "KILL present" reading was a false match on killswitch.py.

## 2026-10-22 (local) - platform upgrade, part 1 (user's brief: audit, selection, calibration, risk, research engines)
- Backups first: paper.db and live.db (backups/paper_20261022_091242_manual.db, also in Documents\tradebot_backups), plus a code snapshot in backups/code_20261022_*.
- docs/ARCHITECTURE.md: the system as found, the trade path, and the root problems.
  - Selection was by value only.
  - obs keeps the first snapshot only.
  - No record of rejected markets.
  - Fills are optimistic.
  - Correlation is ignored.
  - The scheduled runs were a single point of failure.
- **audit.py (new):** an append-only decision ledger in paper.db. New tables: scans, scan_ends, decisions, decision_events, market_results, audit_meta. Triggers refuse UPDATE and DELETE.
  - strategy.scan records one decision per market evaluated, with a reason code. The codes are TRADE, MARKET_STARTED, NO_QUOTE, WIDE_SPREAD, MODEL_UNAVAILABLE, DAILY_LOSS_STOP, ALREADY_HELD, STRATEGY_DISABLED, INSUFFICIENT_EDGE, SIZE_BELOW_ONE, CASH_LIMIT, EXPOSURE_CAP and CLOSE_TIME_UNREADABLE.
  - Each decision also records the quote, the model inputs (NWS slices, the station, and the grid's fetch and issue time), the rules hash, the strategy and model version, and the shadow selector's verdict.
  - A paper trade and its decision row are written in one savepoint. If the row cannot be written, the trade is rolled back (fail closed).
  - If the ledger cannot be created, markets are still logged but no trade opens.
  - Creating the tables backs up paper.db first.
  - shadow.py's maker ledger is recorded the same way. strategy.settle and shadow.settle add settlement and fill events.
  - **v3 decisions are unchanged.** tests/test_audit.py runs the same scan with the ledger stubbed out and gets identical trades. obs and trades keep their schema.
- **nws.py:** records each grid's fetch time and NWS updateTime (GRID_META). Logging only; the values returned are unchanged.
- **registry.py (new):** strategy ids, versions and lifecycle states (IDEA..RETIRED) with allowed transitions. may_trade_live() is false for every strategy. An append-only strategy_log is written at report time.
- **selector.py (new), shadow only:** the accuracy-first meta selector (experiment accuracy_first.v1, frozen 2026-10-22). It abstains on:
  - stale data;
  - a wide spread;
  - a model-market gap above 30 points;
  - a full risk cluster;
  - fewer than 30 settled markets in the probability range;
  - a conservative win chance under 60%;
  - conservative EV after fees under 1c.
  It never trades.
- **New measurement and research modules:**
  - **calibration.py:** Brier, log loss, ECE, Wilson reliability.
  - **risk.py:** weather clusters by date and region; capital efficiency.
  - **fees.py:** taker and maker by fee type. Incentives count only when INCENTIVES_ELIGIBLE, which stays False until the user confirms eligibility.
  - **resolution.py:** settlement-certainty states with a station-match guard and revision risk.
  - **research/structure.py:** ladder and bucket-basket inconsistencies at executable prices after fees, confirmed in the live order book. Descriptive.
  - **research/longshot.py:** favorite/longshot calibration on K1's trades. Exploratory; it refuses to run before K1 is scored.
- **Dashboard:**
  - New control_view.py, the control center: strategies and their states (INTERIM - NOT ACTIONABLE), the latest scan's reasons and the best rejected candidates in plain words, v3 rain calibration, risk clusters, capital efficiency, open positions at Kalshi prices (best and worst moments), the market-structure summary, and an audit trail per trade.
  - Live prices (marks.py, from Oct 15), with the reviewer's fixes:
    - `run watch` writes dashboard_live.html, so the phone page is never the self-refreshing one;
    - atomic page writes;
    - the reader's place is kept across reloads;
    - "Prices update every 5 min", and "Not updating" once the watch window is closed;
    - a missing bid is unknown, not $0;
    - one bad price no longer drops a snapshot;
    - the watch loop stops on any non-zero exit.
- **PLAN4:** the format check's subset test now accepts lost rows that the scored walks list as CLOSED. One token can be in both walks and is kept once, and the old check counted those as missing. Recorded as lost_listed_as_closed. This must be confirmed on the PC before pselect runs again.
- **PLAN5:**
  - Test L window moved to Oct 23 - Nov 19 before any sample.
  - Spread-only verdict added; rewards count only with confirmed eligibility.
  - Adverse selection at 1 and 5 minutes added.
- **run.bat:** `hourly` (L sample and settle, the structure scan every 6 hours, prices, dashboard) and `structure`.
- **Tests:** test_audit, test_structure, test_longshot, test_engines and test_lip added. The full suite passes (25 tests).


## 2026-10-22 (local) - PLAN5 test L revised after its statistics review (before any sample)
- An independent statistics review (agents/statistician.md) of test L ran today. All its required fixes and most of its suggested ones are in. Full list in research/PLAN5.md, "Second revision on 2026-10-22".
- **Dates:** the window is now 2026-10-24..2026-11-20 and scoring is on or after 2026-11-25. Only markets that close before 2026-11-23 are sampled.
- **Score:** total net over total capital. Its SE is the largest of three: by day, by event, and the no-edge SE.
  - At least 100 filled contracts across at least 20 events.
  - A day counts only with 12 or more sampled hours.
  - NOT TESTABLE if over 2% of filled market-hours are unsettled. The rewards verdict is also NOT TESTABLE if a program's reward is outside $1-$1,000 a day, which would mean a unit error.
- **Rewards:**
  - They count only if the user's eligibility confirmation is logged with its date before the window ends. fees.py gains ELIGIBILITY_CONFIRMED_ON (None).
  - A side's reward stops when it fills.
- **Adverse selection:** measured from Kalshi's one-minute candle mid at +1 and +5 minutes. Fills are checked 7 minutes after the hour.
- **Settlement:** falls back to one market at a time when the batch call leaves a market out.
- **Headline:** "dollars a day at the $25 cap" replaces the monthly figure, and is the spread-only figure unless the rewards verdict applies.
- research/lip.py and tests/test_lip.py are updated to match. The full suite passes (25 tests).
- Still needed on the PC before Oct 24:
  - a dry format check of the order book, trades and candlestick answers;
  - an hourly runner, which needs the user's approval because it is created outside this folder.

## 2026-10-22 (local) - code review applied; metrics, discovery, order-flow and combo research added
An independent code review (agents/code-reviewer.md) of part 1 found 1 MUST and 4 SHOULD items. A 60-scan old-vs-new comparison found v3 trades and obs identical, and live.py byte-identical to the PC's copy. Part 1 also added postmortem.py (loss-cause codes per settled trade), which the previous entry left out.

**MUST fixed**
- **strategy.py: research helpers can no longer stop the v3 scan.**
  - audit, selector, calibration and risk are imported inside try. Without audit.py, a stand-in records nothing and refuses trades (fail closed).
  - The decision-record fields (`_ctx`), the selector, calibration and the cluster sums are each guarded. A failure is stored in the decision row, not raised.
  - v3 decisions are unchanged (tests/test_audit.py runs the scan with these helpers broken and gets the same trades).

**SHOULD fixed**
- **audit.py: an older or foreign ledger is refused untouched.**
  - It checks every existing table's columns against its own definitions before creating anything.
  - The scan prints TRADES BLOCKED, and the dashboard shows a red "Trades blocked: audit ledger" chip plus a status line when a scan logged markets without its ledger. The check counts scans from 2026-10-23 12:00 UTC on.
  - Trades still fail closed without the ledger, by design: every paper trade must have its decision record.
- **Wording of the real-money lock** (registry.py, control_view.py, docs). live.py copies to Kalshi's demo now, and to real money only on or after Nov 11 after the user's typed unlock. The gate verdict is shown at unlock, not enforced. The old text implied the gate blocked it.
- **postmortem.py: MODEL_CALIBRATION_ERROR** now needs the model's chance to be above the top of the 95% range of how often that side won in its bin (new calibration.Calib.interval). The old rule fired on well-calibrated bins.
- **research/plan4.py: format check.** It fails if more than 2% of lost positions appear only as CLOSED rows: their P&L would miss the unsold remainder's loss and flatter the scores. This still has to be checked on real data on the PC.

**NOTES fixed**
- audit.py: TRADE is counted only after its decision row is written. A duplicate ticker in one scan is documented: one decision row, so no second trade.
- strategy_log moved into the audit ledger. It is created by audit.ensure() after its backup, and registry.py no longer creates tables.
- dashboard.py writes a per-process temp file, so hourly, scan and watch cannot collide. It reads only the last 4 days of decisions plus every trade's own row, keeping the page small; the total count is still shown.
- fees.py: the note now says core.fee can be 1c higher in rare float cases.
- research/structure.py: the exhaustive-bucket check is strict, so a missing whole number at a tail is no longer accepted. A different encoding fails safe, and the all-YES check is then skipped.
- lip.py, discover.py, micro.py: ISO timestamps with any fraction length parse on Python 3.8-3.10 too.
- postmortem.day_start uses each city's standard-time offset (Central, Mountain, Pacific) instead of Eastern for all.

**Added (research only; public GETs; nothing places orders)**
- **metrics.py** (phase 32), shown in a new "Metrics by strategy" table:
  - settled count;
  - win rate with its count;
  - profitable rate;
  - net and per-contract P&L;
  - realized vs expected;
  - Brier;
  - max drawdown and largest loss;
  - holding time and turnover;
  - profit per dollar per day;
  - daily ratio (5+ days);
  - worst risk cluster;
  - the correlation of daily P&L between the main bot and the limit-order test.
- **research/discover.py** (phase 29): a catalogue of every open Kalshi market (single and combo) in research/data/discovery.db, never paper.db.
  - Daily series cache, paginated open listing, upserts by ticker.
  - An append-only lifecycle table for status changes.
  - Rate limit of 8 a second, backoff, and an --every cache.
  - run.bat hourly refreshes it every 6 hours; `run discover` runs it by hand.
- **research/micro.py** (phases 13-16, exploratory): `run micro [minutes]` records up to 12 weather markets' books and trades every 5 seconds. analyze reports:
  - book imbalance against the later mid (5 s to 30 min);
  - join, improve or cross with a queue-aware fill model, P(fill) at 5 s to 5 min, value at fill, and expected value per decision;
  - spread capture and the mid after fills;
  - P(toxic fill) by state;
  - lead-lag within events, after spread and fee.
- **research/combo.py** (phase 10, exploratory): open combos priced from their legs with a one-factor Gaussian copula: independence price, combo mid and implied correlation. After settlement, it compares the Brier of each, with the correlation fitted only on earlier combos. `run combo` runs it.
- **registry.py:** orderflow.micro.v1 and combo.copula.v1 (IDEA, research). Test L shows its dates.
- **Control center:**
  - each strategy's start date and verdict point;
  - a safety line (date lock, typed unlock, live.py scope);
  - the test L sample count;
  - "Research results (exploratory, not actionable)" with the latest summary of each research tool.
- **docs/UPGRADE_REPORT.md:** the 12-section engineering report the brief asked for. The PC-only checks are marked [PC].
- **Tests:** test_discover, test_micro and test_combo added. test_audit, test_engines, test_structure and test_lip extended. The full suite passes (28 tests).

## 2026-10-22 (local) - second code review applied (before deployment)
The re-review found no MUST items. It confirmed:
- all 14 earlier fixes;
- identical v3 trades over 60 old-vs-new scans, also with the selector broken or audit.py missing;
- live.py byte-identical;
- GETs only, Python 3.8 compatible, run.bat CRLF throughout.

**SHOULD fixed**
- **micro.py:** "later" prices use the first snapshot at or after the target time, never the starting one. The report uses the measured polling cycle, since 12 markets take more than 5 seconds. Lead-lag compares each leader update with the follower's next one.
- **lip.py:** if the candles fail, the fills are still recorded, with the adverse-selection check left empty (candles_failed). Any error is handled per sample, and each record is written as soon as it is worked out.
- **discover.py:**
  - Pages are written as they arrive, and a run is logged when it starts, so --every still holds after a crash.
  - The hourly job skips combos (--singles).
  - One-by-one lookups are capped at 300 a run.
  - A ticker Kalshi answers 404 for is marked not_found and not retried.
- **Research notes on the dashboard** show each file's closing caveat. structure.md puts "Not arbitrage..." on its second line and says "still in the book at scan time" instead of "confirmed".

**NOTES fixed**
- The "Trades blocked" check starts at 2026-10-22 23:00 UTC (after this install) and allows a 2-hour scan.
- audit.ensure() fails closed on any error, not only database errors.
- combo.py settle falls back to one-by-one lookups (capped at 200).
- micro.py opens discovery.db by a proper file URI.
- lip.py treats an unreadable ELIGIBILITY_CONFIRMED_ON as not confirmed.

**Tests** cover candle failures, singles runs, not-found tickers and the later-snapshot rule. The full suite passes (28 tests).

## 2026-10-22 17:46-18:15 (local) - r55 installed on the PC; scans now run from Windows Task Scheduler
- **Backups first.** paper.db and live.db were copied to backups\paper_20261022_174637_predeploy_r55.db and backups\live_20261022_174637_predeploy_r55.db, and the copy's hash was checked. paper.db had not changed since Oct 15 14:52: 81 obs and 4 trades, 2 of them still open from Oct 15. `PRAGMA integrity_check` on copies of both databases: ok.
- **Migration rehearsed** on a copy of the real paper.db with the new code:
  - audit.ensure() created the ledger tables and strategy_log;
  - integrity ok, 12 triggers;
  - the obs, trades, shadow_orders and v4_obs row counts are unchanged;
  - running it again is a no-op;
  - the dashboard renders with the control center.
  The real migration happens at the next settle or scan, after backup.py's preaudit backup.
- **41 files installed** (backups\MANIFEST_r55.json); each was read back from the PC and its sha256 matched. live.py was not touched (hash unchanged).
- **Desktop Commander fails to start on the PC** (an npm error launching it), so the cloud tasks could not run run.bat. The user chose to run the bot from Windows Task Scheduler instead.
  - New tasks\evening.cmd, settle.cmd and hourly.cmd write to logs\tasks.log with ISO timestamps and exit codes.
  - The user creates the schedules with schtasks (tasks\README.md).
  - The cloud tasks were changed to read-only reporters: "Tradebot afternoon report" 3:21 PM, "Tradebot evening report" 9:25 PM and "Tradebot late-night scan check" 11:41 PM. They use only the device file tools.
  - The duplicate "Tradebot laptop check" is disabled.
  - CLAUDE.md section 10 updated.

## 2026-10-22 22:50-23:40 (local) - refactor stage 1: shared code, one gate source, faster analysis (no functional change)
The user asked for an architecture review and a code-quality refactor that changes no behaviour. The review and plan are in docs/REFACTOR.md, and docs/ARCHITECTURE.md is rewritten to describe the current system.

**Not touched:** the frozen v3 path (strategy, weather, nws, kalshi, core, config), live.py, shadow.py, audit.py, marks.py and the pre-registered scorers. File comparison confirms it.

**Changed:**
- **tbcommon/ (new):**
  - httpclient.JsonClient is one GET client that keeps each module's own tuning. It handles Retry-After whether numeric or not, keeps the connection alive and counts requests. Sleep and clock can be injected.
  - parse (num, px, rts, cents), stats (wilson, cl_mean_se) and jsonio (atomic save, crash-tolerant JSONL).
- **research/structure.py, lip.py, discover.py, micro.py, combo.py and longshot.py** use tbcommon, and their taker-fee copies call fees.taker (identical on 1,681,576 inputs). Their public names stay, so tests and callers are unaffected.
- **research/micro.py:** the quadratic loops are replaced by bisect indexes (BookIndex, trade-time index). A 12,000-snapshot recording takes 2.6 s instead of 10.6 s, and 36,000 snapshots take 7.9 s instead of 72.1 s, with identical results.
- **gate.py (new, standard library only)** holds the gate rules for the dashboard, replacing dashboard.py's private copy. tests/test_fix.py checks on 300 random inputs that gate.py and strategy.py's frozen copy agree. The dashboard no longer imports anything that needs `requests`. If gate.py itself fails, a red "Gate rules unavailable" chip shows and no pass is ever shown.
- **Tests:**
  - test_tbcommon added.
  - test_fix gains the gate parity check.
  - test_marks fixture fixed: it failed whenever it ran in the last minute of an hour, because two marks 60 s apart straddled the hour.

**Proof of no functional change:**
- **Golden master:** 144,065 output fields of 12 scenario suites (database rows, JSON, Markdown, dashboards, printed output) are identical before and after. Clock-dependent fields were excluded by running the old code twice.
- **Independent code review** (agents/code-reviewer.md): no MUST. Its SHOULD is fixed: the first version imported strategy.py into the dashboard, which hid the gate when a trading module was broken; gate.py replaced that. Its notes are listed in REFACTOR.md as known edge cases:
  - Retry-After "0" in structure.py;
  - immediate errors on invalid JSON;
  - last-bit SE differences;
  - 0.0 vs 0 in longshot.json;
  - micro.fee1(None).
  
  It also verified the request pattern of every migrated module against the old code with a fake clock (10 scenarios), fuzzed micro on 300 random recordings, and confirmed the dashboard is byte-identical once clock times are masked.
- **The library was renamed to tbcommon/httpclient** to avoid clashing with the PyPI package "tblib" and the standard library's "http".
- **Full suite:** 29 tests pass. One earlier run had a single failure that did not repeat in three reruns, consistent with the known one-second backup-name clash in test_audit.

## 2026-10-23 (local) - refactor stage 2: dashboard structure, golden-master tool (no functional change)
- **dashboard.py:** the 130-line main() is split into:
  - read_db() (read-only reads) and read_research() (research summaries);
  - build_page() (the page, pure);
  - write_page() (atomic write);
  - named section builders: last_scan_line, money_panel, latest_day, record_rows, status_chips.
  
  CSS and JavaScript moved unchanged to dashboard_assets.py. marks.jsonl is read once per page instead of twice. 678 lines down to 583.
- **tests/golden.py (new):** the golden-master tool as part of the project. `capture` runs 12 scenario suites against a copy of the code; `compare` checks every output field. It ignores clock-dependent values and backup.py's own name-clash messages.
- **tests/test_kill.py:** its no-core.py scenario copies the dashboard's own files and now includes dashboard_assets.py. Without it the page could not load its CSS in that bare folder. The scenario's purpose (the page shows the kill switch without core.py) is unchanged.
- **Proof:**
  - golden.py, original tree vs stages 1+2: 144,021 fields, 0 differences.
  - The dashboard rendered from a copy of the PC's real paper.db is byte-identical once clock times are masked.
  - The full suite passed in 6 of 7 runs. The other run had one failure, right after the test_kill fix, whose message was not kept; it did not recur in 4 more full runs or in 40 targeted reruns of audit, shadow, end_to_end, fix and kill.

## 2026-10-23 (local) - refactor stage 2: review applied
Independent review (agents/code-reviewer.md) found no MUST items. Its findings and what was done:
- **SHOULD, fixed:** dashboard.py read marks.jsonl outside every guard. One bad byte in that file stopped the whole page, so the phone page went stale. The read is now guarded, and runs only when a view uses it. A corrupt file now loses the live prices only. tests/test_kill.py checks this.
- **SHOULD, fixed:** tests/golden.py never compared the dashboard body. The body is one long line holding a timestamp, so it was always skipped as volatile. Long lines are now split at tag and JSON-item boundaries, and clock times and epoch seconds are masked token by token. A rerun compared 151,948 fields, 7,874 of them dashboard-body pieces, with 0 differences.
- **NOTE, fixed:**
  - A missing dashboard_assets.py now gives an unstyled page, not no page.
  - test_kill's no-core folder includes gate.py and checks that the gate is still judged without core.py.
  - golden.py now prints ASCII only (Windows consoles).
  - `capture` exits non-zero when a scenario fails.
  - A Windows file lock no longer stops `capture`.
  - One unreadable table no longer hides the rest of its file.
- **tests/test_marks.py:** the suite's occasional single failure is explained and fixed. marks.snapshot() stores ts rounded to 0.1 s, and the test rounded that again to whole seconds. That failed whenever the clock's fraction was in [0.45, 0.5): 50 of 1,000 fractions. The comparison is now at 0.1 s: 0 of 1,000.

## 2026-10-23 (local) - reliability: data freshness, historical OHLC anomalies, one time zone for reports (user request)
Details in docs/RELIABILITY.md. Nothing here changes a decision, threshold, score or safety control. live.py, strategy.py, core.py, config.py, weather.py, nws.py, kalshi.py, shadow.py, audit.py, marks.py, gate.py and the pre-registered scorers are unchanged.
- **freshness.py (new, read-only):** a refresh limit for each dataset the bot depends on:
  - scan, settlements, forecast age at the last scan;
  - backups in and outside the folder, the export, the page;
  - live prices, PLAN5 L caches, structure scan, market catalogue;
  - each scheduled job's last result in logs\tasks.log;
  - the PC clock against Kalshi's Date header.
  
  Statuses are ok, stale, fail, waiting and info. Output: research/results/freshness.md and .json, and a one-line "FRESHNESS:" summary.
  - `.\run freshness [--clock]`.
  - The scan and settle steps end with it; the hourly job runs it with --clock.
  - Exit 0 always (`--strict` for 1 on failure).
  - paper.db is opened read-only, and the test checks its bytes are unchanged.
- **Dashboard:**
  - a "Data freshness" table in the control center, problems first;
  - a header chip, "Data checks: N failed, M out of date", linking to it.
- **tbcommon/ohlc.py (new):** candle checks with codes OFF_GRID, FUTURE, OUT_OF_RANGE, HIGH_BELOW_LOW, OPEN_CLOSE_OUTSIDE, CROSSED, LOCKED, NEGATIVE_VOLUME, TRADE_OUTSIDE_QUOTE, TIME_NOT_INCREASING, JUMP and GAP.
- **research/ohlc_audit.py (new, research only, public GETs):**
  - What it reads: the one-minute candles of every market the bot logged, once each market's window is over.
  - What it reports:
    - anomaly rates;
    - how old the "latest candle at or before t" was at each minute the bot logged the market;
    - how far the candle mid was from the live order-book mid the bot read.
  - Output: research/results/ohlc_audit.md and .json.
  - How it runs: `.\run ohlc`; daily from the hourly job, at most 60 markets per run.
- **research/lip.py (PLAN5 L, before its first sample on Oct 24):** fill records gain a descriptive `candle_check` (anomaly codes, and the age of the candle behind each adverse-selection mid). score() never reads it, the adverse numbers are unchanged, and PLAN5.md says so.
- **tbcommon/clock.py (new):** one zone, America/La_Paz (UTC-4, no daylight saving), in three forms:
  - `iso()` for files, offset always written;
  - `label()` for people, the zone named once per page;
  - `bot_date()` for grouping.
- **Applied to:**
  - **Reports:** the structure.md and discovery.md headers, PLAN5 L's `scored`, longshot's `made`.
  - **Dashboard:**
    - server-side times, and "Updated ... (UTC-4)";
    - the account view's script: dates, times, month statements, year reports, CSV columns "Opened (UTC-4)" and "Closed (UTC-4)".
    
    Before, these followed the viewing device's zone, so a page rendered in UTC or Tokyo showed other times than the phone; checked in four zones with Chromium.
  - **metrics.daily:** settle dates in bot time.
  - **tasks\*.cmd:** `Get-Date -Format o`, so each log line carries its offset.
  
  When the PC is set to La Paz time, as now, every shown time is unchanged.
- **Tests:**
  - New tests/test_freshness.py and tests/test_ohlc.py; tests/test_lip.py checks the candle record.
  - **Full suite: 31 of 31 pass** (Python 3.12, Linux).
  - **Golden master, back-to-back runs (old, new, old):**
    - Data fields: the only difference is the offset in PLAN5 L's `scored` stamp.
    - Text: only the intended changes (report time formats, the account view script, CSV headers, the freshness panel and chip, one CSS rule).
    - One "Per $ per day" cell differs by 0.1 point. It depends on the wall-clock seconds between test steps, and its inputs were confirmed to vary run to run.

## 2026-10-23 (local) - reliability work: independent reviews applied
Two reviews with agents/code-reviewer.md. The first ran out of time after finding four problems; a second, fresh review finished: no MUST, 2 SHOULD, 6 NOTE. The 16 protected files (live, strategy, core, config, weather, nws, kalshi, shadow, audit, marks, gate and the pre-registered scorers) were confirmed byte-identical, and 31 of 31 tests passed on its copy.
- **First review, fixed:**
  - freshness missed a log's last line when it was longer than 64 KB. Structure-scan lines can pass 70 KB. It now reads further back.
  - Text or true/false where a timestamp belongs crashed the monitor. Timestamps are now read as numbers only.
  - With the kill switch on, a stale scan said "run evening.cmd". It is now info: scans are halted on purpose.
  - The PLAN5 L fee-type "age" came from series.json's date, but lip.py rewrites that file every sample. It is now info only.
- **Second review, SHOULD, fixed:**
  - tasks\settle.cmd and evening.cmd logged only the last step's exit code, so a failed settle followed by a successful report read "done (exit 0)". The done line now keeps any failing step's code.
  - The candle checks read empty-book placeholders (a bid or ask at 0 or 1) as real quotes. That gave false CROSSED, LOCKED and TRADE_OUTSIDE_QUOTE codes, and a 0.50 "mid" across an empty side. These are now EMPTY_SIDE, informational, with no mid.
  - The audit compares a candle mid with the bot's own reading only when the candle's spread is at most 6 cents (config.MAX_SPREAD).
- **Second review, NOTE, fixed:**
  - `run freshness` passes both options.
  - The scan's kill-switch and failure paths and the settle failure path also write the FRESHNESS line.
  - A log line with no time (PowerShell did not answer, now written "no-time") still counts as a run.
  - The whole tasks.log is read only under 64 MB.
  - The OHLC audit gives a market three tries (errors or no candles), then leaves it.
  - A later error no longer replaces a good audit record.
- **Second review, NOTE, kept:** a missing paper.db shows as "fail". In the tradebot folder that is a real emergency (CLAUDE.md section 3).
- **Not verifiable here**, as the reviewer noted: Kalshi's live encoding of empty sides (handled either way now), Task Scheduler itself, and a real Python 3.8 (syntax checked with feature_version 3.8).
- **Also:**
  - The candle field names were checked against Kalshi's API reference: yes_bid, yes_ask and price with *_dollars strings, and volume_fp.
  - tbcommon/ohlc.field also reads a dollar string sent without the suffix.
  - tests/golden.py aligns text outputs with difflib, so an intended inserted line shows as one change. The final before/after comparison showed only the intended differences.
- **The two cloud reports** (afternoon, evening) quote the FRESHNESS line when it is not "all current". Their prompts were updated, and the PC re-signed them.

## 2026-10-23 15:35-15:45 (local) - r57 installed on the PC
- **Before:**
  - paper.db and live.db were copied to backups\paper_20261023_193653_predeploy_r57.db and live_..._predeploy_r57.db (file names use UTC). Each copy is byte-identical to its source and passed integrity ok; paper.db holds 81 obs and 4 trades.
  - A first attempt with SQLite's backup API failed on the mounted folder ("disk I/O error"). Its partial file was renamed incomplete_paper_20261023_193627_predeploy_r57.db, so it is never mistaken for a backup. paper.db was not touched.
  - The 22 files being replaced were copied to backups\code_pre_r57\ for rollback.
- **Installed:** 31 files, listed with their hashes in backups\MANIFEST_r57.json; all matched when read back. run.bat and tasks\*.cmd keep Windows line endings.
- **Unchanged:** the 16 protected files (live, strategy, core, config, weather, nws, kalshi, shadow, audit, marks, gate, the scorers) have the same hashes as before.
- **Tests on the installed files** (the PC's Linux sandbox, Python 3.10): 30 of 30 pass. test_ui needs Playwright and passes in the cloud. test_live and test_learn first failed only because the sandbox's temp folder name began with the code folder's name; they pass from a separate folder.
- **dashboard.html rebuilt from here** with the new freshness panel. It reports 3 datasets out of date (last scan Oct 14, two Oct 15 trades not settled, export 8 days old) and no scheduled run yet.
  - Its "Backups outside the folder" line cannot see Documents\tradebot_backups from here, so it reads "none". The next run on the PC rebuilds the page with the real answer.
  - The phone page was not republished from here; the evening report does that after the PC runs.

## 2026-10-23 18:20-19:00 (local) - outage investigation: no scans since Oct 15 (user request)
Full analysis: docs/INCIDENT_2026-10-23.md. Nothing that trades was changed: run.bat, live.py, strategy.py, the gate, the kill switch, the limits and the frozen v3 model are untouched.
- **Root cause, with evidence read on the PC:**
  - No `logs` folder and no `logs\schedules.txt`: tasks\install_schedules.cmd was never run, so Windows Task Scheduler has never started the bot.
  - Before Oct 22 the scans depended on cloud sessions. Those stopped at the usage limit on Oct 15, and Desktop Commander no longer starts on the PC (npm cannot rename its cache folder).
  - paper.db was last written Oct 15 at 2:52 PM.
- **Nothing in the code blocks trading.** Tonight's first run was rehearsed on a copy of the real paper.db with fake Kalshi and NWS answers: ledger migration with its backup first, the two Oct 15 settlements, a scan that opened 4 paper trades on planted edges, the dashboard and freshness. Integrity ok.
- **Hidden failure modes fixed:**
  - **No runs on battery.** schtasks.exe cannot set power options. Windows' defaults (Task Scheduler schema: DisallowStartIfOnBatteries=true, StopIfGoingOnBatteries=true) skip the run while the laptop is unplugged, and kill it when the charger is pulled out. The new tasks\install_schedules.ps1 sets both to false.
  - **Missed runs were never made up** (StartWhenAvailable=false). It is now true.
  - **A make-up run at the wrong hour.** With make-up runs on, a run missed at 8:55 PM could start the next morning and permanently replace the evening snapshot that obs keeps and the gate's Brier score reads. The new scan_window.py lets the scheduled evening run scan only from 8:50 PM to 0:59 AM; otherwise it settles and logs "Scan skipped". `.\run scan` by hand is unchanged.
  - **Two settles at once.** Missed afternoon and evening runs could start together and write paper.db and live.db at once. The new joblock.py is an OS file lock (msvcrt or fcntl), so a crashed job leaves no stale lock. settle.cmd and evening.cmd run each step through it; after 45 minutes a JOB LOCK line and exit 75.
  - **The installer's outcome was easy to miss.** install_schedules.cmd now:
    - checks each schtasks call;
    - says plainly whether the battery and make-up settings were applied;
    - writes logs\schedules.txt;
    - tells the user to "Run as administrator" if access is denied.
- **Checked, unchanged:**
  - The daily loss stop: the two open trades can lose at most $1.72, under the $2.50 stop, so they cannot pause tonight's scan. The rule is a safety control and stays as written.
  - live.db: nothing pending or mismatched.
  - No kill file.
- **Tests:** new tests/test_schedule.py, which checks:
  - the scan window;
  - the batch and PowerShell files' structure: CRLF, step order, exit codes, no password, no wake, no admin;
  - the job lock with real processes: waiting, release after a killed holder, exit codes, the busy path.
  
  **Full suite: 32 of 32 pass.**
- **Independent review of the fix (agents/code-reviewer.md): 0 MUST, 2 SHOULD, 6 NOTE. All fixed:**
  - **SHOULD:**
    - The window opened at 6 PM. A make-up scan before 8:50 PM would cost shadow.py's v4 forward test that market day: it logs a market's airport forecast once and counts it only from 00:50 to 01:30 UTC. The window now opens at 8:50 PM.
    - The skip message invited a morning scan by hand. It now says to wait for 8:55 PM.
  - **NOTE:**
    - Any answer but "inside" now skips the scan (fail closed).
    - The JOB LOCK line names the step holding the lock (logs\job.owner) and no longer promises that Task Scheduler's time limit ends it.
    - joblock passes its output handles to the step explicitly and starts the system's cmd.exe (ComSpec).
    - The installer quotes each task's path and explains that "Run as administrator" helps only when your own account is an administrator.
    - evening/settle/hourly.cmd end with `exit /b %RC%`, so Task Scheduler's Last Run Result shows failures.
    - freshness.py's scan hint gives the window.
  - **Not verifiable here, as the reviewer noted:** real cmd.exe, Task Scheduler and PowerShell. Their structure is checked by tests/test_schedule.py, and the lock's Windows branch (msvcrt) runs only on the PC.

## 2026-10-24 03:31-04:30 (local) - the Oct 23 evening run failed: no network in standby (user: "we need this to happen automatically")
- **Evidence (logs\tasks.log, read on the PC):**
  - The 8:55 PM job ran its settle, then the scan failed on `getaddrinfo failed` for api.elections.kalshi.com (exit 1, 2 seconds).
  - Every hourly job from 12:20 to 3:20 AM failed the same way. The laptop was in standby with its network off; the Claude app's link to the PC dropped at 9:20 PM.
  - At 3:30 AM evening.cmd was double-clicked. It logged 6 western markets outside the designed time; 59 others had already begun. 0 trades.
- **New jobs.py: the three task files now only log and call it.**
  - It waits for the network: the evening job as long as the 8:50 PM to 1:00 AM window is open, the settle up to an hour, the hourly job up to 10 minutes.
  - It retries a failed scan up to 3 times, 5 minutes apart, inside the window only.
  - It runs every step under joblock.
  - The hourly job applies install_schedules.ps1's battery and missed-run settings once, by itself (Windows only). No second double-click is needed.
- **The evening task's time limit was raised** so it can wait until 1 AM (5 hours at first; 6 after the review below, with 6.5 in freshness.py).
- **Steps, thresholds, model, gate, kill switch and live.py are unchanged:** still run.bat settle, scan, report and hourly.
- **Tests:** test_schedule.py now also covers jobs.py with fakes (network down then up; the window closing; scan retries; a failed settle kept; settings applied once, failure retried, never raising). The task files are checked by structure.
- **Still needs the laptop awake with internet at some point between 8:50 PM and 1 AM.** Fully laptop-independent runs need the cloud runner (cloud/README.md), which waits on a GitHub repository from the user.
- **Independent review of jobs.py (agents/code-reviewer.md): 1 MUST, 3 SHOULD, 4 NOTE. All fixed before deployment:**
  - **MUST: a scan could start after 1 AM.** The window was checked before the lock wait, which can take up to 45 minutes; the reviewer reproduced a start 4 s after the window closed. Now step() asks the window again once it holds the lock (exit 3 when closed, no retry), and a scan never waits for the lock past 1 AM.
  - **SHOULD: the task files' `>> logs\tasks.log` held the log locked against other writers for the whole run.** A job waiting hours for the network would have stopped every other job from starting. Now jobs.py writes the start and done lines and each step's output itself, appending a line at a time, and the .cmd files no longer redirect.
  - **SHOULD: the network check required api.weather.gov as well and ignored a Windows proxy.** It now checks Kalshi only, and is skipped when an HTTPS proxy is set.
  - **SHOULD: the settings script rebuilt each task's settings,** which would re-enable a task the user disabled. It now changes the four settings in place.
  - **NOTE:**
    - The evening task limit is 6 hours, so it covers a wait until 1 AM plus a lock wait and the settle. freshness allows 6.5 hours.
    - An hourly run that finds the lock busy for 10 minutes skips that hour with exit 0 instead of 75.
    - A distinct "WAITING FOR NETWORK since HH:MM" line marks the wait for the cloud reports.
    - A crash inside jobs.py still writes its traceback and a done line.
- **Tests:** test_schedule.py covers the held-lock guard, the busy lock, the log lines, crash logging and the proxy skip, and freshness reads jobs.py's lines.

## 2026-10-24 03:49 (local) - r58 installed on the PC
- **Before:** paper.db and live.db were copied to backups\*_20261024_074933_predeploy_r58.db (byte-identical). The 10 replaced files went to backups\code_pre_r58\.
- **Installed:** 16 files, listed in backups\MANIFEST_r58.json; all hashes matched when read back. The .cmd and .ps1 files keep CRLF.
- **Unchanged:** live.py, strategy.py, core.py, config.py, weather.py, nws.py, kalshi.py, shadow.py, audit.py, marks.py, gate.py and run.bat.
- **Tests on the installed files** (the PC's Linux sandbox): test_schedule, test_freshness, test_kill and test_ohlc pass.
- **Not testable here:** the first Windows run of jobs.py and the settings script is the 4:20 AM hourly job. Checked afterwards.

## 2026-10-24 04:00 (local) - r58b: follow-up review of jobs.py (0 MUST, 1 SHOULD, 4 NOTE), all fixed
- **SHOULD: the settle task's 2-hour limit was shorter than the settle job could run** (an hour's network wait, then up to 45 minutes for the lock before the settle and again before the report). Windows would have stopped it partway.
  - The settle limit is now 3 hours (install_schedules.ps1). freshness.py allows it 3.5 hours before calling it stuck.
  - **Each job now has a wait budget** below its limit: evening 5.5 h (limit 6), settle 2.5 h (limit 3), hourly 1.5 h (limit 2). Network and lock waits end when it is spent. A step whose lock is free still runs; one whose lock is still busy does not, and the log says why. A test checks every budget against its task's limit and freshness's allowance.
- **NOTE: the settings were applied only once, ever.** A later change to install_schedules.ps1 (like the settle limit above) would never reach Windows. logs\schedules_applied.txt now starts with the script's SHA-256, and a different script is applied again at the next hourly run. The read-back also checks the time limit.
- **NOTE: with Python missing, the task files wrote a line freshness could not read.** They now write the job's start line, the reason, and `===== no-time <job> done (exit 9009)`, so freshness shows a failed run.
- **NOTE: the test of "the window is checked after the lock" now proves the order:** the check itself tries to take the lock and must find it held.
- **NOTE: "window closed" used exit 3, which run.bat scan can also return** (backup.py: only live.db failed). That failure would have skipped the retries. The internal code is now 103; a 3 from run.bat is retried like any failure.
- **Unchanged:** steps, thresholds, model, gate, kill switch, live.py and run.bat.
- **Tests:** full suite 32 of 32 pass.
- **Independent review of r58b (agents/code-reviewer.md): 0 MUST, 0 SHOULD, 5 NOTE. All fixed:**
  - Re-running install_schedules.cmd resets the tasks to Windows' defaults, so it now forgets logs\schedules_applied.txt first; the next hourly job applies the settings again.
  - The settings read-back compares the time limit as a duration, not as text, so a different spelling from Windows cannot make it re-apply every hour.
  - The lock wait counts wall-clock time (time.time), like the network wait, so time spent in standby counts against the budget.
  - Wording: jobs.py's description, the "no network" message when the budget ended the wait, and this entry.
  - Tests: main() setting the budget is checked; the missing-Python test reads its lines from the .cmd files themselves; freshness allows the hourly job 2.5 hours (limit 2).
- **The first Windows run of jobs.py (r58, 4:20 AM hourly job) worked:** start and done lines with -04:00 times, the step output in tasks.log, exit 0. The settings script reported OK for all three tasks (enabled, next runs 8:55 PM, 2:51 PM and 5:20 AM).
- **r58b installed on the PC (04:32-04:45 local).** paper.db and live.db were copied to backups\*_20261024_083242_predeploy_r58b.db (byte-identical); the 13 replaced files are in backups\code_pre_r58b\ and the new hashes in backups\MANIFEST_r58b.json. Protected files unchanged. On the PC, test_schedule failed once for a test reason only: one joblock test read the real logs\job.owner, which exists on the PC since the 4:20 AM run (it said "holder unknown" only where no job had run yet). The test now points at a file of its own.

## 2026-10-25 00:00 (local) - r59: wake the laptop for the 8:55 PM scan, keep it awake during a step (user: "you know the desired end results needed... intelligently update the system with what is needed")
- **Evidence (logs\tasks.log, Oct 24):** the laptop slept from 11:39 AM to 11:53 PM. At 11:53 PM the missed settle, evening and hourly jobs all started by themselves (the r58 settings worked) and the scan logged 40 markets and opened 2 paper trades. Had the laptop woken after 1 AM, the market day would have been lost. Earlier, from 8:20 to 11:39 AM, the hourly jobs found no network (standby).
- **The 8:55 PM Evening scan task now wakes the PC** (WakeToRun, install_schedules.ps1, applied by the next hourly job because the script changed). Only that task; the settle and the hourly job never wake it. It was off before because a laptop could wake in a bag. That is still possible, but the job only keeps it awake while a step runs.
  - Windows honours the wake only if the power plan's "Allow wake timers" is on. The script only reads that setting (powercfg /q) and reports it in logs\schedules_settings.txt; nothing changes it.
  - To stop the wake: Task Scheduler, Tradebot, Evening scan, Conditions, clear "Wake the computer to run this task". A manual change stays until the script itself changes.
- **jobs.py keeps the PC awake while it works** (Windows' SetThreadExecutionState, held by a helper thread that drops it at a cap or when the block ends): during a run.bat step (at most an hour), for up to 6 minutes after the evening job starts while Wi-Fi reconnects, and in the 5-minute pause between scan tries. Never during a long network wait, the settle job or the hourly job.
- **Independent review of r59 (agents/code-reviewer.md): 1 MUST, 4 SHOULD, 2 NOTE. All fixed before deployment:**
  - **MUST: the battery risk was not stated.** This laptop never sleeps when plugged in, so the wake matters on battery, where it can wake with the lid closed, even in a bag. The README, the settings report and the message to the user now say so, and how to limit the wake to plugged in (power plan, "On battery": Disable) or stop it.
  - **SHOULD: after a timer wake Windows sleeps again after about 2 minutes,** so Wi-Fi might not reconnect and the 2nd and 3rd scan tries would wait for another wake. The job now keeps the PC awake for up to 6 minutes at the start of the evening job and in each retry pause.
  - **SHOULD: a hung step would keep the PC awake until Windows' 6-hour limit.** The request is now capped at an hour per step.
  - **SHOULD: on a Windows in another language the wake-timer report would say "not shown".** It now finds the setting by its GUID and reads the two values after it; `powercfg /qh` (hidden settings, also read-only) is tried when `/q` does not list it; "not present" and "could not read" are reported separately. A test checks English and Spanish output.
  - **SHOULD: the docs promised a wake that may not happen on this PC** (it may use Modern Standby, where a timer wake can leave the network off). They now say "may wake", the report adds `powercfg /a` (read-only sleep states), and the first night's log is the check.
  - **NOTE:** an unexpected setting value prints "value N"; stay_awake reports whether Windows accepted the request; the README says a manual "don't wake" lasts until the script changes or the installer runs again.
- **Unchanged:** steps, thresholds, model, gate, kill switch, live.py and run.bat.

## 2026-10-28 02:30-03:00 (local) - r60: audit of missed opportunities and orders; settle survives network errors (user: "fully investigate/ audit ... why we are not being successful at ordering/ identifying the buying opportunities")
- **Full report: docs/AUDIT_2026-10-28.md.** Read from the PC's logs, paper.db and a copy of live.db.
- **Scans ran for 5 of 15 market days (Oct 14-28).** The rest were missed: no network in standby on Oct 25, the laptop asleep on Oct 27, and the earlier cloud outage.
- **Per scan, 1-2 of about 35 next-day rain markets pass the fixed rule** (16+ points of forecast-market disagreement). On 101 resolved markets the market's Brier score is 0.069 against the forecast's 0.090. In 15 of 17 large disagreements the market was closer. All 4 settled rain trades lost (-$3.51).
- **The shadow accuracy-first selector abstained on all three recent trades.** Nothing acts on it (shadow by design).
- **Research engines are not wired to orders, by design** (the Oct 22 brief). The structure scan found no fee-positive bucket basket. Its one repeated gap (USCLIMATE, +1.2c, 15 contracts) is on long-dated markets.
- **Demo copies:** 2 of 3 skipped because the demo book had no YES bids (correct fail-closed behaviour).
- **Fixed: one network error stopped the whole settle** (Oct 26 and Oct 27). Nothing was committed, and run.bat skipped live sync, the shadow settle, learn and the backup.
  - strategy.settle now retries each market (3 tries), isolates failures and commits results as found and in a finally block.
  - It looks each market up once and stops after 3 failures in a row.
  - It exits 1 only when Kalshi could not be read at all.
  - It warns when a market is decided without yes or no.
  - The scan and every v3 decision are unchanged. New test: tests/test_settle.py.
- **Added: install_schedules.ps1 reports the power plan's "Network connectivity in Standby"** (read-only, with the PC's own value names).
- **Test fix:** tests/test_ohlc.py had started failing on Oct 26 because its --every check read the real clock. The clock is now pinned.
- **Waiting on the user (not changed):**
  - DTW and WPB rain markets missing from v3's city table;
  - 10 renamed temperature series (temperature is logged, not traded);
  - the selector as a veto;
  - "Network connectivity in Standby" on the laptop;
  - a runner that does not need the laptop.
- **Independent review of r60 (agents/code-reviewer.md): 0 MUST, 3 SHOULD, 5 NOTE. All fixed before deployment:**
  - **SHOULD:**
    - Two settles at once (a manual `.\run settle` takes no job lock) could record a trade twice, with a second permanent "settled" event. A trade is now settled only while still open (`where ... and status='open'`), and the audit records are written only when that update changed the row.
    - Markets Kalshi answers for without a result (an unknown ticker) counted toward "3 failures in a row", so they could stop every later market. Only network failures (connection errors, timeouts) count now.
    - Tests now cover a trade with its decision row: one "settled" event and one market result however many settles run, and the open-only guard.
  - **NOTE:**
    - A settle now stops looking after a 15-minute budget; the rest wait for the next settle.
    - Each trade and its audit records go in one savepoint (as the scan already does), and logged markets are committed one by one, so neither Ctrl+C nor Windows' time limit leaves half a record.
    - The settings script reports "could not be read" with the reason instead of "not present" when powercfg fails, and queries settings by GUID.
    - test_ohlc asserts that the second --every run is skipped.
    - Decision rows' model version reads v3@<hash of weather.py, nws.py and strategy.py>, so it changes with this release although the model did not.
- **Tests:** full suite 33 of 33 pass.
- **r60 (with r59) installed on the PC at 03:00 local.**
  - **Before:** paper.db and live.db were copied to backups\*_20261028_070023_predeploy_r60.db (byte-identical); the 11 replaced files are in backups\code_pre_r60\.
  - **Installed:** 13 files, hashes in backups\MANIFEST_r60.json, all verified.
  - **Unchanged:** weather.py, nws.py, kalshi.py, core.py, config.py, live.py, shadow.py, audit.py, marks.py, gate.py and run.bat.
  - **Tests on the installed files (the PC's Linux sandbox):** test_settle, test_schedule, test_freshness, test_kill, test_ohlc and test_end_to_end pass.
  - **Next:** the next hourly job applies the changed settings script (wake for the 8:55 PM scan) and writes the power-plan report to logs\schedules_settings.txt.

## 2026-10-28 03:15-03:45 (local) - r61: user decisions after the audit (user: "please implement all 3")
- **Detroit (DTW) and West Palm Beach (WPB) added to v3's rain table.** Same formula as the other 33 cities, so their forecasts are logged and can trade from the next scan. Stations are the ones Kalshi's rules name:
  - DTW is CLIDTW, Detroit Metro: 42.23, -83.33, IEM station DTW.
  - WPB is CLIDJT, West Palm Beach. Palm Beach International was renamed and re-coded from PBI to DJT in July 2026. IEM station DJT: 26.6847, -80.0994.
  - The coordinates come from the Iowa Environmental Mesonet because api.weather.gov's station pages cannot be read from Claude's tools. The bot itself only uses them to ask api.weather.gov for the forecast grid.
  - These markets count toward the v3 rain gate from Oct 29 (the first scan after this change). Earlier days had no forecast for them.
  - risk.py regions (midwest, southeast) and the dashboard's city names include them.
- **Veto: no rain trade when the forecast and the market mid are more than 30 points apart.**
  - The bound is the accuracy-first selector's ANOMALOUS_MODEL_MARKET_GAP check, frozen 2026-10-22. The user chose this version over the full selector, which would have blocked nearly every trade.
  - Replayed on the 5 rain trades so far, it would have blocked Seattle, Oct 25 (lost) and Oklahoma City, Oct 27 (open).
  - Forecast, blend, 8-point edge, sizing and limits are unchanged. Vetoed markets are still logged for the forecast test, with the reason ANOMALOUS_MODEL_MARKET_GAP.
  - **This changes a pre-registered rule mid-test, at the user's explicit request.** Trades opened before and after Oct 28 follow different rules; the decision ledger's reason codes and this entry let the Nov 11 review separate them.
- **Not changed:** the limit-order ledger in shadow.py keeps its pre-registered rules (no veto there), and live.py copies whatever paper trades the scan opens, as before.
- **Tests:**
  - New tests/test_veto.py: the bound at exactly 30 points (allowed) and 31 (vetoed), both sides, the edge check first, vetoed markets still logged, the two cities' stations against Kalshi's rules text, the same v3 formula, risk clusters and names.
  - Three older tests had fixtures with gaps over 30 points; they now use gaps of 24-29 points, and test_audit adds a vetoed market.
- **Runner without the laptop:** waiting for the user to create the empty private repository `tradebot` on GitHub.
- **Independent review of r61 (agents/code-reviewer.md): 0 MUST, 3 SHOULD, NOTEs. All fixed:**
  - **SHOULD:**
    - "More than 30 points" allows a gap that is 30 points up to float rounding (0.99 against 0.69 computes as 0.30000000000000004). The shadow selector has no such tolerance, so in that one case it can say "would not trade" next to a trade. This is now documented in strategy.py, and a test proves the boundary (it fails without the tolerance).
    - Each scan's config row in the decision ledger now records VETO_MAX_GAP, so scans before and after the veto can be told apart without reading code hashes. The unused VETO_FROM constant was removed.
    - Tests now cover the float boundary and a held market with a big gap (reported as ALREADY_HELD, not the veto).
  - **NOTE:**
    - The limit-order ledger (shadow.py) takes its markets from v3's logged markets, so it also covers DTW and WPB from Oct 29.
    - research/fetch.py's time-zone table gains DJT (Eastern) for any future past-data runs.
    - The DTW point is sent to api.weather.gov with 2 decimals (DAL and AUS already use 3); it may land in the neighbouring 2.5 km grid cell. Replace it with NWS station coordinates when those can be read.
    - The weather.py, registry.py and CLAUDE.md notes were updated (about 105 NWS calls per scan).
- **Tests:** full suite 34 of 34 pass.

## 2026-10-28 03:30 (local) - the laptop's power report (first run of the r60 settings script)
- **Schedules:** all three updated; the Evening scan now "wakes the PC to run".
- **Allow wake timers:** plugged in on, on battery off.
- **Network connectivity in Standby:** plugged in Enable, on battery "Managed by Windows".
- **Sleep states:** Modern Standby (S0 Low Power Idle, Network Connected) and Hibernate.
- **What this means:** plugged in, the 8:55 PM scan can wake the laptop and reach Kalshi. On battery it cannot wake it, and Windows may turn Wi-Fi off in standby, which matches Oct 25 and 26 (jobs on time, no network for hours).
- **Told the user:** keep the laptop plugged in overnight, or change the two on-battery values themselves (the powercfg commands were given). Claude does not change power settings.
- **r61 installed on the PC at 03:39 local.**
  - **Before:** paper.db and live.db were copied to backups\*_20261028_073859_predeploy_r61.db (byte-identical); the 15 replaced files are in backups\code_pre_r61\.
  - **Installed:** 16 files, hashes in backups\MANIFEST_r61.json, all verified.
  - **Tests on the installed files (the PC's Linux sandbox):** test_veto, test_fix, test_rainonly, test_audit, test_end_to_end and test_settle pass.
  - **First scan with the veto and the two new cities:** tonight at 8:55 PM. Its scan row in the ledger records VETO_MAX_GAP 0.3.

## 2026-10-28 11:35 (local) - the runner without the laptop: code pushed, blocked by GitHub billing
- **Pushed to the user's new private repository cenacllc-beep/tradebot** (commit a85430c). It contains:
  - the code, plus research/results/rain_model.json;
  - .gitignore: no paper.db, live.db, backups, logs or research/data, and no key files;
  - trial/ with its own .gitignore;
  - the two workflows in .github/workflows.

  The scan now runs at 00:55 UTC = 8:55 PM La Paz, as on the PC, and only inside scan_window.py's 8:50 PM-1 AM window (TZ=America/La_Paz). A run started by hand at another time checks the setup and does not scan.
- **A test run (11:36) never started.** GitHub said: "The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings." Nothing ran and nothing was changed.
- **Needs the user:** fix the billing in GitHub Settings > Billing & plans, or decide to make the repository public. Public repositories run Actions free. The repository has no keys, but its notes describe the setup.
- **11:45: the user made the repository public** (Actions are free there). A test run by hand at 11:45 went through every step: checkout, Python 3.12, requests, the scan step and the save step. Outside the 8:50 PM-1 AM window it did not scan, as designed, so nothing was committed.
- **First real runs:** the settle at 2:40 PM today does nothing yet (no trial database). The first scan is tonight at 8:55 PM La Paz (00:55 UTC). GitHub can start scheduled runs late; the scan still runs if it starts before 1 AM.
- The repository holds no keys and no account email, but its notes (CLAUDE.md, CHANGELOG.md) are now readable by anyone.

## 2026-10-28 afternoon (local) - r62: the recommendations (user: "intelligently implement all your recommendations")
- **Stop date single look (strategy.py; pre-committed before the verdict, CLAUDE.md section 11):**
  - The gate is judged once, on the test's own 28 market days only: at the first report or scan on or after Nov 11 when every v3 rain market and trade of those days has its result. A market that never settles (for example a voided one) keeps the look pending, so v3 stays closed. A cutoff after which such markets are left out (strategy.LOOK_DEADLINE) is the user's decision and is not set. The look is stored in paper.db (new table gate_look, one row, created only then, after a backup) and never recomputed.
  - v3 rain paper-trades market days from Nov 11 on only after a stored look that passed. Otherwise the market is logged and the decision ledger records GATE_NOT_PASSED (new reason). Pending look, failed look or an error: no trade (fail closed). The Nov 10 evening scan therefore opens no trades for Nov 11 markets, which lie outside the test's 28 days.
  - The limit-order ledger (shadow.py) follows the same rule. live.py copies only new paper trades, so after a failed look it has nothing to copy. Its own locks, the $25 cap and the typed unlock are unchanged.
  - Before Nov 11, report() states the interim numbers with the same formula as before (gate_ok(gate_inputs), checked against the old code on 300 random cases). From Nov 11 its verdict is the look's only: "not judged yet" while the look is pending. It prints a "GATE LOOK" line, which live.py status and unlock show. The dashboard and the control center show the stored look (or "pending").
  - Unchanged: the gate's thresholds, the clear-margin rule, v3, the limits and the kill switch.
- **Temperature series (logged, not traded):** Kalshi renamed 10 of the 14 daily-high series the scan asked for (KXHIGHNY, KXHIGHT<city>). weather.TEMP_SERIES now names the current ones, and kalshi.markets() asks for them. The estimator and the rules watch map each series to its city. NYC, PHX, SEA, BOS, HOU and MIN are logged again (about 12 more temperature markets a day). STL, MKE, PVD and IND have no daily-high series now.
- **PLAN5 L sampling moved to GitHub Actions:**
  - Storage (logistics; the rows are unchanged): new rows of samples, fills and sample_log go to one file per UTC day (samples-YYYYMMDD.jsonl). Every reader takes the original file first, then the daily ones in order. The hourly commit therefore rewrites a small file, not one that would reach about 40 MB by Nov 20 (63 KB a sampled hour, measured on the PC).
  - cloud/workflows/plan5-lip.yml samples at :20 every hour, settles, and scores once from Nov 25, in the repository. It uses its own concurrency group.
  - Same code and rules (research/PLAN5.md logistics note). The PC's samples were copied into the repository at the cutover.
  - The PC's research\data\lip\MOVED.txt stops research\lip.py there (no sample, settle or score), and run.bat's hourly job no longer runs it. freshness.py and the dashboard show "moved" instead of stale.
  - cloud/repo.gitignore (the repository's .gitignore) lets research/data/lip/ in (public Kalshi market data) but never MOVED.txt.
  - The scan and settle workflows now replay their commit and retry the push on a race. This was tested on a shallow clone.
- **Detroit and West Palm Beach:** NWS station coordinates (KDTW 42.2314,-83.3308; KDJT 26.6851,-80.0992), read on GitHub's runner from api.weather.gov on Oct 28. Both fall in the same NWS grid cells as the earlier values, so the forecasts are the same.
- **Re-check of the fixes (same reviewer): no MUST or SHOULD left.** NOTES:
  - The deadline needed the user's OK, so it was left unset (above).
  - report() reads the date once, so a run crossing midnight on Nov 11 cannot fail.
  - The dashboard counts the daily sample files.
  - Left as they are:
    - A cutoff, if set, would not tell a voided market from settles that failed for a week.
    - live.py's read-only status can show a look worked out but not yet stored. It is the same 28 days, so it matches the one that will be stored.
- **Tests:**
  - New: tests/test_gatelook.py and tests/test_moves.py.
  - test_schedule now checks run.bat's CRLF line endings.
  - test_shadow, test_audit, test_veto and test_fix no longer depend on the real date being before Nov 11.
  - The full suite passes, 36 of 36. A copy with the stop date moved into the past fails only where tests assert the stop date itself.
- **Independent review (agents/code-reviewer.md, fresh agent): 2 MUST, 5 SHOULD, 10 NOTES.**
  - **MUST (both fixed):**
    - M1: the stored look counted every resolved market and settled trade. A look delayed by a failed settle would have included days from Nov 11 on. The look now counts only market days before Nov 11, so it is the same whenever it is taken. It records the first and last day, and a test proves it.
    - M2: an edit had turned run.bat's line endings into LF. cmd's goto label search is unreliable without CRLF. Restored, and test_schedule now checks it.
  - **SHOULD:**
    - S1 (fixed): while the look was pending, report(), live.py unlock and the dashboard could show "passed" from the current numbers. From Nov 11 they now show only the look's verdict, or "not judged yet".
    - S2 (left to the user): a test-day market that never settles keeps the look pending forever, so v3 stays closed (fail closed) and report says "not judged yet". A cutoff, for example Nov 18, after which such markets are left out and listed, is coded but unset (LOOK_DEADLINE=None). The reviewer's re-check advised the user's explicit OK before adding a new gate detail, so the user is asked.
    - S3 (fixed): three older tests (and one check in test_fix) would have failed after Nov 11 because of the real date.
    - S4 (fixed): see the daily files above.
    - S5 (followed in the deploy order): the repository's .gitignore goes in with the workflow; the repository's lip.py, tbcommon and fees.py match this release; on the PC, r62 goes in before MOVED.txt.
  - **NOTES:**
    - Fixed:
      - paper.db is backed up before the new table, and never for a read-only look.
      - A failed store rolls back.
      - "Stored by the next report or scan" wording.
      - Labels after the stop date ("every market day so far").
      - The extension path is noted.
      - Open test-day trades keep the look pending.
      - SEA rather than TSEA in the dashboard and learn.py.
      - A failed fetch in the push retry is retried.
      - run.bat's stale comment.
    - Left as they are:
      - The dashboard's gate chips keep showing the numbers for every market day after the look. The verdict line shows the look.
      - TEMP_STATION does not list the 6 re-added cities: the rules watch records their stations but cannot flag a change.
      - If the score's commit fails all 6 pushes, the next hour scores again from the same data.
      - After it scores, the workflow keeps starting hourly and stops at once. A follow-up on Nov 25 checks the score and turns it off.
      - Hours the PC sampled between the copy and GitHub's first run stay only on the PC.
- **r62 installed on the PC at 15:33 local.**
  - **Before:**
    - paper.db and live.db were copied to backups\*_20261028_192240_predeploy_r62.db (byte-identical).
    - An earlier attempt with SQLite's backup API failed on the bridge's file mount with "disk I/O error". It left paper_20261028_192219_predeploy_r62.db, now renamed *.incomplete: do not restore from it.
    - The 25 replaced files are in backups\code_pre_r62\.
  - **Installed:** 29 files, hashes in backups\MANIFEST_r62.json, all verified.
  - **Tests on the installed files (the PC's Linux sandbox):** test_gatelook, test_moves, test_veto, test_fix, test_end_to_end, test_settle, test_rainonly, test_lip, test_freshness, test_audit and test_shadow pass.
  - **The PC's sampling stopped:** research\data\lip\MOVED.txt was written at 15:33, after the PC's 3:20 PM sample.
- **Repository:**
  - Commit f7ad0f5: the same files, the three workflows, the .gitignore, and the PC's PLAN5 L data up to the 3:20 PM sample. The one-off station-check workflow is removed.
  - A run started by hand at 15:35 went through every step. It committed the fill checks for the 2:20 PM sample in the first daily file (4ad6270).
  - The hourly schedule samples from 4:20 PM.
- **Follow-ups scheduled:**
  - Oct 29: the first GitHub scan (set earlier).
  - Nov 1: compare the two runners, and decide whether the phone page should read GitHub's results.
  - Nov 25: report PLAN5 L's single score, then turn its hourly workflow off.

## 2026-10-28 20:50 (local) - PLAN5 L: four chances an hour on GitHub
- **What happened:** on its first evening GitHub started the hourly :20 sample only once in four hours (the 23:20 UTC run started at 00:04 UTC), and the trial settle due at 18:40 UTC started at 22:48 UTC. Hours 21, 22 and 23 UTC were not sampled.
- **Change (logistics only):** plan5-lip.yml now starts at :05, :20, :35 and :50. The first run in an hour takes that hour's sample. hours.json keeps it to one per hour, so the rules are unchanged. The other runs only do the fill checks and results, and commit only when something changed.
- **Also changed:** test_moves checks the new schedule. cloud/README.md is updated.

## 2026-10-29 00:30 (local) - r63: GitHub's scheduler started almost nothing (user: "investigate and resolve all issues")
- **What happened, from GitHub's run list (Oct 28-29):**
  - The 00:55 UTC trial scan was never started by GitHub. At 03:56 UTC it was started by hand. It scanned inside the window and logged 55 markets (35 rain, 20 temperature, all 10 daily-high series). It opened 3 paper trades (ABQ yes @0.06, MKE yes @0.62, WPB no @0.43), against the PC's 1 at 8:55 PM. The difference comes from timing: prices had three hours to move.
  - The trial settle due at 18:40 UTC started at 22:48 UTC.
  - PLAN5 L: one of 16 scheduled runs started (00:04 UTC). Hours 21, 22, 23 and 01 UTC were missed; 02 and 03 UTC were taken by runs started by hand.
  - All three workflows show "active". The runs carry the repository owner as actor, and runs started by hand begin at once. So this is GitHub's scheduler dropping or delaying scheduled runs, which its documentation allows under load, not a fault in the workflows.
  - The PC ran every job on time (FRESHNESS: all current).
- **Fixes (logistics only; no rule, threshold or verdict changed):**
  - **PLAN5 L, two samplers:**
    - The PC's hourly job runs lip.py sample and settle again, and GitHub keeps sampling.
    - New `lip.py merge DIR` adds to the repository's copy the hours only the other copy took, with their samples, fill records, log row, hours.json entry and settled results. The repository's copy keeps any hour both took. A second merge changes nothing.
    - The PC's copy holds research\data\lip\SECONDARY.txt, so it is never scored. The workflow no longer scores by itself; the single score runs by hand after the merge (the Nov 25 follow-up). PLAN5.md logistics note.
    - On the PC, research\data\lip\MOVED.txt is renamed (not deleted) to MOVED.txt.off-2026-10-29.
  - **Trial scan:** it starts at 00:55 UTC and then every half hour until 04:25 UTC. The first run that gets going scans; later ones stop when check.py reports tonight's markets as logged (one scan an evening).
  - **Trial settle:** it starts hourly from 18:40 to 22:40 UTC.
- **Tests:** test_moves covers the merge (only the other copy's own hours, shared hours kept, idempotent), the secondary marker, run.bat sampling again, no score step, and the scan's start times and one-scan check.
- **Independent review (agents/code-reviewer.md, fresh agent): 1 MUST, 4 SHOULD, 8 NOTES.**
  - **MUST, fixed:** a scheduled run that waited for another in its concurrency group checked out the commit from when GitHub created it. It would then not see the previous run's push, so check.py could miss tonight's scan, the run would scan a second time, and its push would conflict and fail. All three workflows now check out `ref: main` at job start.
  - **SHOULD, all fixed:**
    - merge reads and checks everything before writing. It never adds a market-hour, fill or log row twice, including on a re-run after an interrupted merge, and refuses a source holding the same market-hour twice.
    - merge refuses a folder without hours.json or SECONDARY.txt, the copy itself, an empty source, and merging into the secondary copy.
    - The repository's copy holds research/data/lip/PRIMARY.txt. Its score requires data/lip/merged.json, written by a merge taken after the window ends (or `lip.py merge-none REASON` if the PC copy is lost). The order is written down: merge, push, one hourly run for fill checks and results, then score.
    - repo.gitignore keeps MOVED.txt* and SECONDARY.txt out of the repository.
  - **NOTES:**
    - Fixed:
      - merge prints any market whose result differs between the copies.
      - PLAN5 wording: the copies can hold different markets for an hour. The choice of copy is fixed in advance. Overlapping fill windows are noted.
      - An hour taken here with no rows gives way to the PC's rows.
      - Freshness and the dashboard on the PC say it samples alongside GitHub.
      - Stale text.
      - New tests: merge edge cases, check.py from a trial folder, the checkout ref, the second-sampler freshness row.
    - Left as they are:
      - Scan and settle share one concurrency group, so a late settle could cancel a pending last scan (04:25 UTC).
      - The settle commits up to 5 times a day.
      - check.py counts temperature rows too, as on the PC.
- **Re-check of the fixes (same reviewer): 1 SHOULD and 4 NOTES, all fixed.**
  - `score()` now refuses any copy without PRIMARY.txt, not only one marked secondary. An unmarked copy (a rebuilt PC folder, or a repository missing the marker) can never be scored. test_lip's scoring uses a primary, merged copy. The hourly workflow fails at once if the repository's PRIMARY.txt is missing.
  - merge writes fills and log rows first, samples next and hours.json last, so a re-run after an interruption finishes the job.
  - merge refuses a source with the same fill record twice.
  - On the PC, freshness flags the PLAN5 L sampler only after a day inside the window without a sample. A missed hour can be taken on GitHub, but a sampler that has stopped is still caught.
  - tests/test_marks.py: an occasional failure, not from r63, came from whole-second rounding of a snapshot time stored to 0.1 s (x.5 rounds either way). It now compares within 0.2 s.

## 2026-10-29 01:50 (local) - PLAN4: finishing the copy-trading tests (user: "intelligently continue until the next 29 steps are completed")
- **State found on the PC:**
  - The Polymarket chain had stopped on Oct 15 at pselect's format check: 12 REDEEMABLE_LOST rows listed as CLOSED, a check fixed on Oct 22 before any selection.
  - The Kalshi K1 trade lists were complete on Oct 16 (9.7 GB).
  - Nothing has been selected or scored.
- **These steps need Kalshi's and Polymarket's APIs from the laptop itself.** Its Linux sandbox and the cloud container cannot reach them.
- **research/plan4_run.ps1 has two finishing chains:**
  - KS: scoreK, then kquotes.
  - PS: pselect, pcopies twice, then scoreP.
  
  They are started detached with one PowerShell line (in the file). The scorers run only after every earlier step succeeded. Each refuses (nothing saved) on PLAN4's data guards, and each test is scored once.
- **PLAN4.md:** dated logistics note added. No rule, window or threshold changed.
- **02:00: the chains start themselves (user: "we need to intelligently complete all steps").**
  - New research/plan4_launch.py runs first in the hourly job. It starts a finishing chain from a flag file (research\results\plan4_go_KS.txt or plan4_go_PS.txt), once, detached from the job, and returns at once.
  - So the hours-long fetches never hold the job lock that the 8:55 PM scan needs, and nobody has to type a command.
  - Only the chains KS and PS can be started this way. A chain whose status file shows a step still running is not started again.
  - New test: tests/test_plan4launch.py.
  - **Independent review (agents/code-reviewer.md): 0 MUST, 4 SHOULD, 5 NOTES.**
    - Fixed:
      - The chain gets its own hidden console. DETACHED_PROCESS would have cancelled CREATE_NO_WINDOW and left a visible window for each step.
      - PowerShell is called by its full System32 path.
      - A flag that cannot be renamed is retried next hour, instead of stopping the launcher.
      - The test now checks the Windows path's handles and that the parent's pipe is released at once.
      - The status line is shown when a chain is still running.
      - plan4_run.ps1 skips a step whose single result already exists (pselect, scoreK, scoreP), so a failed chain can be started again.
      - Each finishing run writes its own log names.
      - A flag next to an earlier start is set aside, so it is logged once rather than every hour.
    - Left as they are:
      - Whether the chain survives the task ending is checked on the PC after the first launch.
      - The chain holds no stay-awake request. The laptop never sleeps on AC power.

## 2026-10-29 02:40 (local) - PLAN4: each finishing chain ran twice; one-copy lock (research only)
- **What happened.** Both finishing chains were started twice, at 02:21:52 and again at 02:21:58. Neither start came from the hourly launcher: its flags were still unclaimed, and at 02:22 it reported both chains as running. Nothing in the folder starts plan4_run.ps1 apart from the launcher, so this was almost certainly Claude's own direct start, run twice.
  - **PS:** the first copy crashed at 02:26:43 in pselect. The two copies wrote the same cache file (plan4.py save() uses path + ".tmp"), giving a PermissionError. The second copy carried on normally. Cache files are replaced whole, so nothing was left half written.
  - **KS:** two scoreK copies ran side by side. scoreK reads only the frozen trade files and uses a fixed random seed, so both work out the same verdict; the result is checked when they finish.
  - The crashed copy's "stopped at pselect" line ended the PS status file while the other copy was still running. The next hourly run would therefore have taken the flag and started a third copy.
  - **02:37:** both flags were renamed to plan4_go_*.started.txt by hand, with a note, so nothing starts another copy.
- **Fix (for any later start):**
  - research/plan4_run.ps1 holds research\results\plan4_lock_<chain>.txt open with no sharing for its whole run. The handle can be inherited, so a python step started by the runner holds the lock too.
  - A second copy retries for 5 seconds. It then stops (exit 3) before writing to the status file and notes why in research\results\plan4_refused.txt.
  - research/plan4_launch.py also counts a held lock as "still running", probed once per chain.
  - tests/test_plan4launch.py covers the lock, including a real exclusive handle when run on Windows.
  - cloud/repo.gitignore ignores the lock files.
- **Independent review (agents/code-reviewer.md): nothing must be fixed; 3 SHOULD and 5 nits.** Applied:
  - the inheritable handle, so ending only the runner does not free the lock while its step runs;
  - retries, plus the real reason in the refusal note;
  - the real-handle Windows test;
  - one probe per chain;
  - the test wording;
  - the gitignore entry;
  - the refusal note can no longer fail the exit code.
- **Left as is:** the chains started before this change hold no lock, so they are checked by hand until they finish.
- No PLAN4 rule, window, threshold or scorer changed.

## 2026-10-29 05:00 (local) - PLAN6: what the Nov 11 report shows next to the gate (user: "we can't move the november 11th deadline. do whats needed without weakening the test. use historical data and patterns")
- **No change to the bot, v3, the gate, the stop date, the single look, live.py or any limit.**
- **What was found:**
  - In the first 16 market days the PC logged only 5 full days, plus 4 markets of Oct 24. The other evenings it was asleep, off or offline: the 8:55 PM job wakes it only on AC power.
  - The bot opens about one trade per scanned night, so the gate's 50-trade check cannot be met by Nov 11. Even every night scanned would give about 28 trades. So the stored look is expected to fail on that check.
- **Past data cannot fill the gap without weakening the test:**
  - Kalshi's rain markets begin on Jul 15, and Jul 15 to Oct 12 was PLAN.md's holdout, already scored once.
  - v3's hourly NWS gridpoint inputs are not archived. The public NDFD archive keeps 12-hour chances, which would make a different estimator.
- **New research/PLAN6.md, written before the last 12 market days.** Its author did not look at the interim Brier numbers; the trade count and the 5 settled trades' net (-$1.67) were seen. It fixes what the Nov 11 report shows next to the stored look, which stays the only verdict:
  - **A:** the gate's own day-clustered Brier statistic, with a fixed three-way reading and its interval in plain words. An expected-precision statement, made before the data, says "no clear difference" is the likely reading.
  - **B (secondary):** the same, with whole days the PC missed taken from the GitHub trial copy. Only when it ran a model version the PC ran, and its scan began in the 00:50 to 05:00 UTC window.
  - **C:** the paper trades, descriptive. Split at the veto by open time; total net per contract; no standard error.
  - **D:** past results, quoted.
- **New research/nov11.py:**
  - read-only (sqlite mode=ro, no network, never computes a look);
  - writes research/results/nov11.md and .json;
  - a damaged trial copy loses only B;
  - a pending run never replaces a finished report.
- New tests/test_nov11.py: the real schema, the real strategy.gate_look, sockets blocked.
- tests/test_marks.py: a timestamp tolerance of 0.2 s, fixing a flake.
- **Independent statistics review (agents/statistician.md), two rounds: 2 MUST, 6 SHOULD; then 0 MUST, 2 SHOULD.** All applied:
  - the real-money wording: live.py's unlock leaves the decision to the user after a failed look, so the report says the rules say no real money and live.py has nothing to copy, rather than "locked";
  - the limits that go with "clearly more accurate";
  - the precision statement;
  - the interval as Brier-score error, measured against the day-averaged market Brier and capped at 100% lower;
  - B's model and window rules, hash and commit;
  - the veto split by open time;
  - per-contract P&L as total over total.
  - Checked, hashes only: PC and trial both ran v3@ecb9ddc276bf on Oct 29.
- **Independent code review (agents/code-reviewer.md), three rounds.** The first two MUSTs followed the plan's revision. All findings applied:
  - B survives any trial error;
  - the window is judged at scan start, as in scan_window.py;
  - the model check excludes later MARKET_STARTED rows;
  - the JSON is written first and fsynced, and a pending copy keeps the finished report (exit 3);
  - missing stored numbers show as n/a;
  - UNC paths are refused;
  - the tests cover every rule.
- **Left as is:** a raw copy of paper.db could be torn during a commit. The Nov 11 task copies it while no job runs, checks it with pragma quick_check, and confirms the gate_look row before running the report.

## 2026-10-29 14:30 (local) - "Data checks: 2 out of date": a stale phone page and a Windows Update restart (user: "intelligently investigate and resolve")
- **What the chip showed.** The phone page was the Oct 28, 3:20 PM version. It flagged the evening scan and the JSON export, because the Oct 27 evening scan was missed: the laptop was in standby from that evening until 2:25 AM on Oct 28, and the 2:31 AM make-up run only settled. The Oct 28 8:56 PM scan fixed both checks. But the 9:25 PM evening report did not republish the page, so the old warning stayed on it.
- **A new gap found while checking.** Windows Update restarted the PC at 4:59 AM and again at 5:03 AM on Oct 29 (System log events 1074: a planned service-pack restart, then an OS upgrade restart). Nobody signed in again until 1:28 PM.
  - The three Tradebot tasks run only while the user is signed in. install_schedules.ps1 stores no password, by design.
  - So the hourly job missed 9 runs, from 5:20 AM to 1:20 PM. Task Scheduler did not make them up after sign-in.
  - The PLAN4 PS chain was killed mid-pcopies at 4:59 AM.
  - The settle and evening jobs were not due during the gap, so the paper test lost nothing.
- **Done:**
  - The 2:20 PM hourly run brought every check current (FRESHNESS: all current, 17 checks), and the phone page was republished from it (version 17).
  - The PS chain's status was marked interrupted, its .started flag set aside (plan4_go_PS.started-1.txt) and a new flag set. The 2:20 PM hourly job restarted it under the new one-copy lock: pselect was skipped (frozen) and pcopies resumed.
- **Found too:** the phone page's file storage holds only the Oct 14 JSON backup. The evening report's nightly upload (CLAUDE.md section 10, step 4) has not landed since then. Today's copy was uploaded by hand (tradebot-paper-2026-10-29.json). Tonight's evening report is checked to see whether its publish and upload work unattended.
- **Not changed (the user's decision, and Windows settings Claude does not change):**
  - letting the jobs run after an update restart without sign-in, either through Windows' option to finish setting up after an update with the user's sign-in info, or through the tasks' "run whether the user is signed in or not";
  - Windows Update active hours.
- No code, rule or threshold changed.

## 2026-10-29 21:45 (local) - the phone page and nightly backup work unattended
- **The 9:25 PM evening report did both of its steps without help.**
  - It republished the phone page: "Updated Oct 29, 8:58 PM", with no data-check warning.
  - It uploaded tonight's JSON backup to the page's file storage (1,010,457 bytes, 9:26 PM).
- **Why uploads were missing.** The report stops before both steps on any night the evening scan did not run, so most of the missing uploads since Oct 14 match nights the laptop was asleep. The Oct 28 evening, when the scan did run, is the one miss with no known cause.
- **A sturdier report prompt is not applied.** It would copy files to the run's scratchpad first and report exact errors. Changing a scheduled task's prompt needs the user's approval, which was not given, so it stays as it is.
- **Tonight's scan:** 55 markets logged; 3 paper trades opened (Oct 30 rain: SEA, DAL and WPB, all NO); FRESHNESS all current.
- The switch to running whether or not signed in waits for the user to run tasks\run_signed_out.cmd (it needs administrator permission). A try without that permission was refused by Windows, and nothing changed.

## 2026-10-29 23:20 (local) - the trial scan was started by hand again
- **GitHub missed every scheduled start again.** None of the tradebot-scan.yml starts (00:55 UTC, then every half hour to 04:25) ran by 03:16 UTC. Only two PLAN5 L samples ran in that time.
- **Started by hand at 03:16 UTC (11:16 PM La Paz):** `gh api .../tradebot-scan.yml/dispatches`.
  - The trial copy logged 35 Oct 30 rain markets, starting at 03:16 UTC, inside the window.
  - It ran model v3@ecb9ddc276bf, the same as the PC's, so the day is usable for PLAN6 B.
  - It opened 1 paper trade (SEA NO).
- **The PC's own scan ran at 8:56 PM:** 55 markets, 3 trades, FRESHNESS all current.
- **Not set up (needs the user's approval):** a nightly cloud scheduled task that starts the trial scan when GitHub has not started it by 9:12 PM. Creating scheduled tasks was not approved.

## 2026-10-30 07:45 (local) - PLAN4 scored: K1 FAIL, Polymarket not scored (research only)
- **K1 (copying large Kalshi trades): FAIL.** -2.2c a contract after fees over 37,669 copies on 92 market dates (t -0.49; 95% interval about -11c to +7c). No edge shown.
- **P1, P2 and P2c (copying Polymarket wallets): NOT SCORED.** 11 of 100 checked wallets failed the pre-set 98% position-coverage check, and the rule allows at most 10. Final: no re-run, no re-check, no relaxed threshold.
- **Independent statistics review (agents/statistician.md): both verdicts correct.** Recorded in research/PLAN4.md "Results":
  - K1's SE is the null floor per market date, about 4.5c, so the power table's 3-4c never applied (about 15c detectable).
  - P2c is left unscored with P1 and P2 (an interpretation).
  - The duplicate runs and the restart changed no output. The coverage snapshots were written only by the surviving pselect copy.
  - The coverage pattern is descriptive only; its cause is unknown.
- **registry.py:** copy_trading.kalshi_large.plan4 is FAILED; copy_trading.polymarket.plan4 is RETIRED (not testable with this data).
- pcopies finished at 05:28: 64,564 candidate copies in 29,664 markets, no trade list failed.
- No bot code, rule or threshold changed. The PLAN4 data stays on the PC.

## 2026-10-30 13:40 (local) - a backstop for the trial scan on GitHub (logistics, paper only)
- **Why.** On Oct 28 and Oct 29 GitHub's scheduler started none of tradebot-scan.yml's scheduled runs inside the evening window, and both nights the trial scan was started by hand. Other workflows did run in that window (the PLAN5 L sample). Creating a cloud scheduled task to do the restart was not approved, so this lives inside the repository instead.
- **New workflow cloud/workflows/trial-scan-backstop.yml** (copied to .github/workflows/). It never scans, trades, commits or touches a database. It only starts "tradebot evening scan (trial)" (workflow_dispatch) when all of these hold:
  - it is inside the 8:50 PM to 1 AM La Paz window (scan_window.py), and not in the last 20 minutes before 1 AM (05:00 UTC, when the Eastern markets start);
  - tonight's markets are not logged in trial/paper.db yet, and the kill switch is off (check.py);
  - no trial scan or settle is queued or running (they share one concurrency group, so a second start could replace a pending run). If GitHub's answer cannot be read, it starts nothing (fails closed).
- **When it checks:** right after every PLAN5 L sample run finishes (workflow_run, which has no scheduler delay), and on its own schedule at :10 and :40 past 1, 2 and 3 AM UTC plus 4:10 AM UTC (9:10 PM to 12:10 AM La Paz). Its own concurrency group means it never queues behind or cancels the scan or settle.
- **Started by hand with test=true** it skips the window and late-start checks only. Outside the window the scan it starts stops at its own window check, which proves the chain without scanning.
- **Independent code review (agents/code-reviewer.md): nothing that must be fixed.** Applied:
  - the settle busy check;
  - the 1 AM cutoff (with a NOW_UTC override for tests);
  - an unreadable answer from GitHub fails closed;
  - checkout without stored credentials (persist-credentials: false);
  - README notes;
  - script tests: tests/test_moves.py runs the workflow's own script with stand-ins for python3 and gh (outside the window, the cutoff, already scanned, busy, unreadable answer, all clear = exactly one start, test=true), and checks that every scheduled start falls inside the window.
- **Checked end to end at 1:40 PM:** a test=true start ran the backstop (16 seconds). It started the trial scan as the workflow's own bot, and that scan stopped at its own window check (no scan, no commit). The script test needs bash, so on the Windows PC test_moves.py runs only the text checks (passed there).
- **Not changed:** the trial scan itself, v3, the gate, live.py, any limit. The PC's own scan is unaffected. The trial copy stays secondary (PLAN6 B uses its days only when the PC missed a night and the scan began inside the window).

## 2026-11-04 02:30 (local) - status check after four idle days; why the rain trades lost (descriptive); backstop waits for the window
- **Scheduled jobs, Oct 30 to Nov 3:** the PC scanned every evening at 8:55-8:57 PM (55 markets; 2-4 paper trades a night) and settled every afternoon; FRESHNESS all current. The settle on Nov 3 needed retries (Kalshi connection resets and timeouts) and still finished.
- **Cloud trial copy:** the backstop started the trial scan on Oct 30 (8:52 PM), Nov 1 (9:46 PM), Nov 2 (9:21 PM) and Nov 3 (10:10 PM). It missed Oct 31 (market day Nov 1): no triggering run finished inside the window (PLAN5 L ran at 8:23 PM, then not until 2:45 AM), and the backstop's own crons ran 5 to 8 hours late every night.
- **Runner comparison (the Nov 1 follow-up, done late):** the PC was complete and on time on every evening since Oct 29; GitHub was not (two nights by hand, one missed, the rest 9:20-10:10 PM). PLAN5 L hours Oct 28 19Z to Nov 4 05Z: 155 hours, the PC took 131, GitHub 32, together 138 (gaps of 17 hours, mostly Oct 29). The phone page stays on the PC's dashboard; the PC's jobs remain the primary runner.
- **v4 airport forecast, Nov 3 evening: 0 logged** (34 on other nights). The Iowa Environmental Mesonet archive has no NBS 18/19 UTC run for Nov 3 (only 00 and 06 UTC, checked at 06:10 UTC Nov 4), so stationfc found nothing to log. Not a bot fault; that market day is simply missing from the v4 forward test.
- **Backstop change (cloud/workflows/trial-scan-backstop.yml, also in .github/workflows/):**
  - It now also follows the trial settle (workflow_run).
  - A check that starts from 4:50 PM until the window opens waits until 8:56 PM. Waking then lets a scheduled 8:55 PM trial scan that GitHub did start go first.
  - After the wait it takes the newest main (it never writes trial/paper.db back) and runs the usual guards.
  - It waits only while the repository reads as public, because the wait costs about 4 runner-hours a night. Each network call has its own time limit. timeout-minutes is 260.
- **Independent code review (agents/code-reviewer.md): nothing that must be fixed.** Applied:
  - time limits on every gh and git call, so a hung call cannot hold the group for hours;
  - the public-repository condition for the wait;
  - waking at 8:56 PM instead of 8:51 PM, so the trial scan keeps its 8:55 PM design time when GitHub starts it;
  - one date call (no hour-change race) and a 6-minute wait at exactly 8:50 PM;
  - a failed fetch goes on (the scan re-checks tonight and the kill switch on the newest main), and a failed checkout starts nothing;
  - the whole tree, not just paper.db, is refreshed after the wait;
  - comments, README and CLAUDE.md section 9 updated;
  - tests: a date stand-in exercises the real time arithmetic, the logged order of calls is checked, plus private-repository, checkout-failure and job-timeout checks.
  
  Left as is: the seconds-wide gap between the busy check and the start, which already existed. Any duplicate start stops at tradebot-scan.yml's own check.
- **Why the rain paper trades lost (user question, Oct 30; descriptive, interim, no rule changed).** From a read-only copy of paper.db after the Nov 3 scan:
  - 18 settled v3 rain trades: 2 won, 16 lost, net -$6.74 on paper.
  - 16 of the 18 were NO bets made because v3 gave a lower chance of rain than Kalshi; it rained in 14 of them.
  - Across all 305 resolved v3 rain markets (10 market days), v3 runs low on rain in its middle range (said about 41%, rained 59%; said 59%, rained 75%). Kalshi's prices were close to calibrated.
  - Where Kalshi was 16+ points above v3, it rained in 30 of 35 markets. The 8-point blend edge (16-point disagreement) therefore selects v3's misses.
  - Day-clustered: v3 is low by +0.116 (SE 0.061, 7 of 9 days above zero) in the 15-85% range; Kalshi by +0.016 (SE 0.050).
  - Interim pooled Brier: v3 0.094, Kalshi 0.069. The gate is still judged once on Nov 11 (section 11). Nothing here changes v3 (frozen), the gate or any threshold.
  - Likely cause: v3's fixed rule combining two 12-hour chances was never calibrated on outcomes. A correction would be a new version with its own written plan and a test on new markets.

## 2026-11-05 16:25 (local) - PLAN7 (v3 with its rain lean corrected) and refactor stage 3 (no functional change)
User: "intelligently implement your recommendations above" and "act like a senior engineer who just joined a massive
unfamiliar codebase ... do not change functionality. only upgrade the code quality, scalability and maintainability."

**PLAN7 (research/PLAN7.md, research/plan7.py, tests/test_plan7.py; one line in run.bat settle).**
- **What it is.** Research and paper only, written before its forward data and before the fit. A correction
  logit(q) = a + b logit(v3) is fitted once on the test's own days (from Nov 11, or from Nov 13 if a test-day market
  never resolves) and frozen. It is judged on market days from Nov 11:
  - the gate's day-mean Brier statistic (primary);
  - maker and taker arms, one contract per signal.
  
  Futility look at 60 forward market days, final look at 110, backstop 2027-06-30. Never part of the gate, never
  connected to live.py.
- **First statistics review (agents/statistician.md): 3 MUST, 5 SHOULD, 6 NICE, all applied before any forward data.**
  - pinned rule: copies of the rule values, the gate statistic, the fill rule, the bootstrap and the fee, checked
    against their sources;
  - forward rows only from the fit days' model versions; v3's code stays unchanged while PLAN7 runs;
  - the final look is refused unless the futility look said "continue";
  - an honest power statement (A's pass threshold about 7% of the market's Brier, power about 15% for a blend-sized
    edge, the maker arm about 6c a contract to pass);
  - an early end or a shortfall by the backstop reads "not confirmed";
  - fit timing that cannot be blocked forever, and candles stored as each day starts (unfilled after 7 days without
    any);
  - a Bonferroni line with the airport-forecast test;
  - A's day-to-day correlation, with its block bootstrap required for "confirmed";
  - descriptive fit checks (clustered SEs, leave-one-day-out), the window judged on the scan's start, and a raw-v3 maker
    placebo.
- **Statistics re-check: M1-M3, S1 and S3-S5 resolved; power arithmetic and the PLAN6 erratum correct.** Applied:
  - **MUST:** the backstop enforced in code (market days after 2027-06-30 never count; a shortfall reads "not
    confirmed" from 2027-07-07);
  - **SHOULD:**
    - the model-version rule's brittleness stated (any edit to weather.py, nws.py or strategy.py, including
      LOOK_DEADLINE, ends PLAN7's data), with one narrow amendment procedure (research/results/plan7_versions.json,
      the user's approval, evidence the forecast code is unchanged);
    - status shows rows not counted by reason;
    - the calendar states the scan rate needed (about 47% of nights);
  - **NICE:** a Bonferroni line including A's bootstrap; "2.5%" called an upper bound; exclusions counted on the look's
    days; market_day and the bot's date pinned; the fit-versus-forward window difference reported; the joint power
    stated.
- **Erratum to PLAN6** (found by the review): its precision guide used two standard errors as one (0.0039 is 2 SE of
  blend minus market). This changes no rule and no reading; a note was added to PLAN6's revision notes.

**Refactor stage 3 (docs/REFACTOR.md section 6; docs/ARCHITECTURE.md rewritten for the system as it runs).**
- **Review findings, most severe first:**
  1. code identity across three copies;
  2. backup growth (quadratic);
  3. single-attempt HTTP in the frozen path;
  4. the gate's rules in two places;
  5. logs read as an interface;
  6. discovery.db growth (214 MB);
  7. a stop date copied in presentation code;
  8. duplicated read-only connections and ticker-date parsing;
  9. import plumbing;
  10. dense style.
  
  Performance: no bottleneck at this scale.
- **Changed, with no functional change:**
  - tbcommon/db.py (connect_ro);
  - tbcommon.parse.market_day;
  - learn, freshness and postmortem use them (risk.py and marks.py keep their own copies, after the code review);
  - control_view reads gate.STOP_DATE;
  - manifest.py (new: `manifest.py write|check`, for every deploy);
  - golden.py covers learn, freshness and ohlc.
- **Kept on purpose:** the copies in the operations scripts and the dashboard (resilience boundaries), and in the frozen
  and pre-registered code.
- **Waits:**
  - the frozen-path work, until PLAN7 ends;
  - backup retention and discovery.db pruning, for the user's decision (both delete data).
- **Proof.**
  - Golden master: 148,974 data fields, 0 differences.
  - 15,404 text pieces, 1 changed stretch: the shadow scenario's "per $ per day" rounds to +60.4% or +60.5% depending
    on test timing, and the old code also gave both values on reruns.
  - The full suite passes.

**Independent code review (agents/code-reviewer.md) of the refactor and plan7.py.**
- Its own golden run: 149,027 fields, 0 differences; the pinned copies faithful; the fit's numerics checked. Its first
  golden run differed only because this working copy lacked research/results/rain_model.json (now copied from the
  repository: the same file as on the PC).
- **MUST:**
  - manifest.py dropped killswitch.py through a "KILL*" filter. Fixed: core.kill_file's rule, top folder only.
  - A decision row without a day start could block both PLAN7 looks. Fixed: not counted (no_day_start).
- **SHOULD, applied:**
  - the no-candles rule after 3 tries, whatever the cause;
  - auto's steps each on their own;
  - day files: their own temp names, retry on Windows locks, an unreadable file moved aside and fetched again;
  - only a missing table means "no versions";
  - a failed fit reported every run;
  - the model and the candles copied to Documents\tradebot_backups\plan7;
  - the backstop filter (already in place);
  - risk.py restored, because the frozen strategy.py imports it and the v3 path must not load tbcommon; marks.py
    restored too;
  - manifest.py covers rain_model.json and compares .github and .gitignore with their cloud/ copies;
  - tests for each.
- **NICE, applied:** looks wait for pending results (left out and listed after 7 days); KALSHI_BASE honoured; the
  small-sample correction on the clustered SEs; Windows clutter and a manifest written into the folder skipped.
- **Left as is (documented):**
  - control_view imports gate.py at load (gate.py has no dependencies);
  - plan7 auto runs before the evening scan inside the settle step, and each pending day can wait up to 60 seconds on
    a hung network.
- **Code re-check: the earlier items fixed.** Two new MUST items, both fixed:
  - damage only zlib notices now counts as an unreadable day file;
  - the off-folder copy is never overwritten by an emptier store or a refit (a lost local file is read or restored
    from it).
  
  Also applied: workflow copies compared in both directions, the remaining small items, and tests for each.
- **New off-folder files.** PLAN7 copies its model and candle files to Documents\tradebot_backups\plan7 (the place
  backup.py already uses for paper.db).


## 2026-11-05 22:40 (local) - two tests made to hold on the PC too (tests only)
- **Why.** The full suite run on the PC after today's deploy failed 2 of 40 tests. Neither failure came from today's
  changes; both had been in place since Oct 23 and Oct 25.
  - **tests/test_kill.py:** the bare-folder dashboard check expected the "unstyled" fallback. On the PC, Python finds the
    real tradebot folder through tradebot.pth (CHANGELOG 2026-10-14), so a bare copy still imports the real
    dashboard_assets.py. The check now expects the fallback only where that import fails.
  - **tests/test_schedule.py:** the "nothing off Windows" check now runs only off Windows.
- **Result:** 40 of 40 pass on the PC and in the working copy. The evening scan at 8:55 PM ran normally with today's
  code: 54 markets, 2 paper trades, FRESHNESS all current, and PLAN7 waiting for Nov 11.


## 2026-11-06 01:30 (local) - freshness: a running PLAN5 L sampler with nothing to sample is not a stopped one
- **Found while reviewing the trades (user: "any recommendation for more successful orders?", then "intelligently
  resolve the issues").** Since Nov 5 the hourly PLAN5 L sampler has found no market it may sample: Kalshi's
  liquidity programs on daily weather markets covered 400-700 markets an hour on Oct 24-28, 40-90 on Oct 29 to Nov 3,
  7 on Nov 4 and none since; the 12 programs left are on long-dated markets (KXLOWA Feb 2027, a Paris rain market) that
  settle after the score date. research/lip.py logs every such hour (sample_log, universe 0) but writes no sample row,
  so freshness.py read the PC's sampler as stopped: "1 stale: PLAN5 L hourly samples (this PC)" from 00:21 on Nov 6.
- **freshness.py (read-only monitor; nothing that trades or scores changed):** _lip_seen() counts the newest
  sample_log entry when it is later than the last sample row, found an empty universe (exactly the integer 0) and
  lists its reasons; the check's detail then shows them ("settles after the score date: 12") and the last sample row.
  No credit, so the check still goes stale, for a run that found markets but wrote no row, a log that lists no
  program at all (that could also mean lip.py no longer reads Kalshi's program list; the detail says so), any other
  universe value, or a log that stops. last_jsonl_ts() is now a wrapper of the new last_jsonl_row() (same reading
  rule); _ts() returns None for an integer too large for a float instead of raising. research/lip.py is unchanged (a
  pre-registered scorer).
- **tests/test_freshness.py:** both copies of the check (this PC's and the repository's): an empty universe, the older
  single-file log name, several log files (the newest entry decides; only the newest daily file is read), markets
  found but nothing written, a stopped log, no program listed, five malformed universe values, no sample row ever, a
  newer sample row, after the window, and an oversized timestamp. Three code changes that the first version of these
  tests missed (code review) are now caught. 40 of 40 tests pass.
- **What it means for PLAN5 L (no rule changed):** its pass rule needs at least 15 days. Only Oct 28 to Nov 4 (8 days,
  perhaps 9 with Nov 5's one hour) had both reward programs and 12 or more sampled hours, so unless Kalshi reopens
  programs on daily weather markets for about 6 more days before Nov 20, the single score from Nov 25 will read "not
  testable" by its own rule. Changing that rule now would change a pre-registered test after its samples began, which
  is the user's decision; Claude recommends leaving it.
- **Also checked, no change:** the fee rounding (core.fee rounds each order up to a whole cent; Kalshi charged the demo
  fills to 1/100 cent): $0.80 vs about $0.70 over the 23 settled rain trades, so the paper record overstates fees by
  about $0.10. It is the gate's pre-set "approximate fees" and in the frozen core, so it stays. The demo copies skipped
  "no price to buy at" (25 of 29) because Kalshi's demo exchange has almost no sellers; the real exchange is unaffected.
  logs\signed_out.txt does not exist, so tasks\run_signed_out.cmd has not been run yet.
- **Reviews (three fresh code reviewers, agents/code-reviewer.md):**
  - **First review:** nothing must be fixed; applied:
    - tests now cover several log files and the newest-daily-file pick (three code changes had passed the old tests);
    - no credit when a log lists no program at all, because it may mean lip.py no longer reads Kalshi's program list;
    - the reasons appear in the detail, with exact wording;
    - the check is not run in the MOVED branch;
    - OverflowError is caught.
  - **Second review:** a finite but absurd timestamp could still crash the monitor. Every stored timestamp now passes
    through _epoch() (0 < ts < 4e9, late 2096). _ts() stays unbounded for the signed clock skew; a first attempt that
    bounded _ts() broke the clock-skew test.
  - **Third review:** must-fix: Windows cannot label dates after the year 3000, so the bound came down from 1e11 to 4e9.
    Also applied: tasks.log times go through _job_time(); RecursionError, a damaged exit code and the KILL file's mtime
    are guarded.
  - **Left as they are** (theoretical, and they fail closed): a deeply nested decisions.inputs value.
  - **Tests:** test_freshness covers all of the above; 41 of 41 tests pass.


## 2026-11-06 17:45 (local) - PLAN8: Kalshi's price first, the airport forecast as a small correction (research only)
- **Why (user: "would you implement other forecast skills, tools or resources for a higher success?", then
  "intelligently implement your recommendations above"):** Claude recommended one test before any new data source.
  Starting from Kalshi's price, does mixing in the forecast the bot already logs make it more accurate? Only if it does
  is a short-range model such as HRRR worth proposing (that needs the user's approval for a new data site and a
  package).
- **What changed from the recommendation, and why:**
  - **No climatology figure:** one November per city is too noisy, and the price already reflects it.
  - **The weights are fitted on Kalshi's 1,711 past markets (81 days), not the ~14 test days.** That is steadier, can be
    frozen before any forward data exists, and keeps PLAN8 apart from PLAN7.
  - **v3 is left out:** correcting it is PLAN7's job.
  - **No trading section:** the airport forecast's own forward test already trades on the same forecast.
- **Added:**
  - research/PLAN8.md (written before any forward data);
  - research/plan8.py (fit | status | score | auto);
  - tests/test_plan8.py;
  - one line in run.bat settle (`plan8.py auto`, after PLAN7's);
  - its entry in tests/run_all.py;
  - docs/ARCHITECTURE.md and CLAUDE.md updated.
- **The design:**
  - **Inputs:** read-only on paper.db's v4_obs and market_results; no network.
  - **Primary measure (A):** the gate's day-mean Brier statistic, the mix against the price.
  - **Attribution (B):** the mix against a recalibrated price, judged only after A.
  - **Looks:** futility at 60 forward days; final at 110, which needs the reading and the 7-day block bootstrap.
  - **HRRR condition:** A and B both pass at the three-test line (0.833%).
  - **Backstop:** 2027-06-30.
  - **Code it relies on:** PLAN7's pinned functions are imported, and their source hashes are pinned. The forecast's
    code, its logging, kalshi.quote, and plan8.py and PLAN8.md themselves are hashed at the fit and checked at each
    look.
- **Exploration on past data (disclosed in the plan):**
  - fitted on all days: weight on the price 0.753, on the forecast 0.447; -0.0028 Brier against the price (t about
    -1.66);
  - fitted on the first half, scored on the second: -0.0012 (t about -1.25);
  - the price-only control: about 0.
  - So this is a new idea, not a confirmed lead. It barely beats PLAN.md's 50/50 mix, which was judged "not clear".
- **Power, honestly:** about 42% for A (13% if the noise is as large as in summer), about 20% for A and B together, and
  about 11% for the HRRR condition.
- **Dry run on the PC (saved nothing):** 1,711 markets, 81 days, 0 formula disagreements. Weights -0.0467 / 0.7527 /
  0.4473; control -0.1485 / 1.2167. The code identity matched.
- **Statistics review** (agents/statistician.md):
  - **Must-fix:** B's rule was incomplete.
  - **Should-fix, five items:**
    - the past evidence was weaker than written;
    - power was not given for correlated days or for A and B together;
    - the log window did not match the fit, so it is now 00:50-01:30 UTC, with the late window as a sensitivity
      reading;
    - the day set must come from logged markets, not results, with a settle-proof rule;
    - the plan did not say which multiplicity line governs.
  - All applied before any forward data.
- **Statistics re-check:**
  - **Must-fix:** the power table counted the t condition only. It now uses the full rule.
  - **Should-fix:** check the plan's own code at each look; fix the data a look uses; enforce FORWARD_FIRST in the fit;
    show A's mean only at 60; state the coverage needed. All applied.
  - **Notes applied:** the clipping wording; the docstring; each ticker counted once.
- **Code review** (agents/code-reviewer.md):
  - **Must-fix:** a missing data folder would have frozen the test as failed forever. The fit now refuses, saving
    nothing, unless the data is exactly the holdout.
  - **Should-fix:** the fit refuses once the first window opens; a damaged model is restored from the off-folder copy.
    Both applied.
  - **Notes applied:** result files are copied off the folder; the plan's own code is in the identity; PLAN7's BOT_TZ
    and kalshi.quote are pinned; --ended is final-look only; the docstring.
  - **Left as is:** malformed v4_obs rows make a look or the status raise (fail closed; auto catches it).
- **Correction to the record:** the first draft of PLAN8.md stated "written 02:30" and "revised 04:30". The file times
  show about 01:35 and 01:45; the plan now says so.
- **Final verification** (a fresh reviewer, both roles): no must-fix; it re-simulated power and found it matches.
  Applied four should-fix items:
  - B is "not judged" on an early end too;
  - the futility look stores no standard error;
  - kalshi._p and shadow._t are pinned;
  - results never go into PLAN8.md.

  Before the fit it asked for two confirmations: that no off-folder PLAN8 model exists, and that the past data is
  present (the dry run had read it).
- **Frozen** 17:24 local: research/plan8.py SHA-256 2c0d027d400a4a702a6d400dfcb06aad2cbb02b7c3d354ef001613f2e6ff1bad.
- **PLAN5 L (no rule changed):** see the 01:30 entry. It will most likely read "not testable".


## 2026-11-06 19:30 (local) - "bet with confident markets" checked on past data: not pursued (research only, no code change)
- **Why (user, after another losing day: "intelligently implement recommendations to improve the system"):** the
  interim calibration table showed Kalshi's confident rain prices coming true slightly more often than priced (70-90%
  priced, 89% rained; 46 markets). Before writing a forward test, the idea was checked on past data, after fees.
- **Exploration** (read-only, on the PC; research/data kalshi_rain.jsonl and kalshi_temp.jsonl, scan-time quotes with a
  6c spread at most; buy the side priced above 50c at the ask; one contract; fee at the bot's whole-cent rule and at
  Kalshi's finer rounding; SE clustered by day):
  - **Rain** (1,711 markets, 81 days):
    - favourites costing 70-95c: -1.9c a contract (SE 1.8c);
    - 95c and up: +0.8c (SE 0.3c), one positive band among 12 looks.
  - **Temperature** (10,885 markets, 105 days):
    - 70-95c: -1.2c a contract (SE 0.4c, about three standard errors below zero);
    - 95c and up: -0.6c.
- **Decision:** not pursued and no PLAN9. The pattern does not survive paying the spread and the fee on past data. The
  one positive band is consistent with the number of looks, and the temperature side contradicts it. Recorded here so
  it is not re-tried without a genuinely new reason (CLAUDE.md section 11a).
- **research/longshot.py** (Kalshi-wide favourite/longshot report) was not run:
  - it requires research/results/plan4_K.json, which is not on the PC;
  - its trade data (PLAN4 K1) has sports, crypto and commodities series but no weather series, so it cannot answer the
    weather question.
  - Left unchanged.
- **Phone page:** republished from the PC's 6:23 PM dashboard, using the report tasks' own steps. It had been showing
  the 3:20 PM snapshot with the old false "PLAN5 L hourly samples" warning ("1 of 16 checks need attention"). The PC has
  read "FRESHNESS: all current (17 checks)" since its 6:20 PM run, the first with the freshness fix.

## 2026-11-06 19:29 (local) - the scheduled jobs now run whether or not the user is signed in
- **The user ran tasks\run_signed_out.cmd** (written 2026-10-29) and answered Yes to Windows' permission prompt.
- **logs\signed_out.txt:** "OK" for all three jobs: Evening scan, Afternoon settle and Hourly research now run whether
  or not the user is signed in.
  - The logon is Task Scheduler's S4U: no password is asked for or stored, the jobs keep normal (not administrator)
    rights, and they run in the background with no window.
- **What it fixes:** a Windows Update restart (as on Oct 29) no longer stops the jobs until someone signs in.
- **Undo:** `.\tasks\run_signed_out.cmd undo`.
- **No code changed.** The first runs under the new setting are tonight's 8:20 PM hourly and the 8:55 PM scan.

## 2026-11-06 20:00 (local) - dashboard: each calendar day shows its paper result (presentation only)
- **What (user: "i'd like the calendar dates to show the total amounts made/ lost on the day"):** under each market day
  in the test calendar, the dashboard shows the net result of the main bot's paper bets for that day, after fees. Gains
  are green with "+" and losses red with a minus sign; a day with only open bets reads "open"; a day with no bets is
  blank. Each day's tip adds the amount with the number of bets won and lost, and a legend line explains it.
- **Phones:** below 820px the calendar shows 7 days a row instead of 15, so each amount fits.
- **Code:**
  - dashboard.py: day_pnl() and day_amt(); calendar() takes the trades;
  - dashboard_assets.py: the amount styles and the narrow-screen grid.
  - The day totals use every main-bot paper trade, as the paper account does. On today's data they sum to -$8.56: rain
    -$6.91 and the two Oct 14 temperature bets -$1.65.
- **Checks:**
  - Rendered from a copy of the PC's paper.db at 390, 780 and 1100px: no amount wider than its day, no sideways scroll.
  - 41 of 41 tests pass.
- **Code review** (agents/code-reviewer.md): fine to ship. Two should-fix items applied:
  - won and lost use the page's own won() rule;
  - a day with nothing counted (a void trade, or a settled one without P&L) stays blank instead of "open".

  Notes left as they are: usd()'s +/-0.004 cutoff (P&L is whole cents), and the narrow grid's columns are not
  weekdays.
- **Known test flake:** tests/test_gatelook.py failed once in a full run because two backups landed in the same second
  ("skipped, already exists"; backup.py never overwrites). It passed three times alone, and in the next full run. It is
  a timing issue in the test only; fix later by waiting a second between its backups.
- **Found while checking:** Kalshi settled KXRAIN-26OCT30-PHX as "scalar" (no yes/no result) at 2026-11-06 20:36 UTC,
  and KXRAIN-26NOV03-PHX and -26NOV05-PHX are still "closed" with no result. Because a test-day market without a yes/no
  result keeps the gate look pending (CLAUDE.md section 11; strategy.LOOK_DEADLINE unset), the Nov 11 look would stay
  "not judged yet". That is the user's decision; nothing was changed.

## 2026-11-06 20:15 (local) - why the paper bets lose (read-only analysis, no code change)
- User: "investigate and identify patterns to detect future losses based on our losing orders". Read-only on a copy of
  paper.db: 29 settled v3 rain bets (6 won, -$6.91 of $15.98 staked, $0.93 fees) and 407 resolved logged v3 rain
  markets over 13 market days.
- **v3 runs low on rain from about 20% to 90%.** It said 30-40%: rained 53%; 60-70%: rained 89% (18 markets, 10 days;
  +25 points +/- 7, day-clustered). Kalshi's mid was calibrated at every level.
- **Disagreements are one-sided.** Of the 8+ point disagreements, v3 was the drier side 95 times and the wetter side 23.
  When v3 was drier, it rained 75% of the time (market 71%, v3 51%). So 27 of the 29 bets were "no rain". The 14 bets
  bought under 20c all lost (13% implied). At the prices paid about 7.5 wins were expected; there were 6.
- **Cause, from the definition** (weather._rain_v3): each half-day's chance is the highest single hourly chance. Several
  hours at a moderate chance add up to more, so v3 comes out low. This is the lean PLAN7 corrects and tests forward.
- **Candidate screen, found after looking:** "no-rain bets when v3 itself says 50%+" won 1 of 22 (-12.0c +/- 4.3 a
  contract, 9 days, at the mid). The rest were +5.6c +/- 11.2 (10 days). The 40% and 60% cutoffs point the same way.
  In-sample, few days, and zero wins in 12 cheap bets happens about 1 time in 4 at fair prices: a screen, not a test.
- Nothing changed. Offered the user: paper only until PLAN7's first look, or a live-only filter. The question was
  answered with a new request; the earlier decision (copy every bet) stands.

## 2026-11-06 20:40 (local) - the user's decisions: a Nov 18 cutoff for the gate look, and real money from Nov 11
- Asked plainly, with the paper record, the user chose "option 1" (the cutoff) "but we change to real money trading by
  11th november", then "Real money from Nov 11". This changes the rule pre-committed on 2026-10-28, before the verdict.
- strategy.py:
  - LOOK_DEADLINE = 2026-11-18 (was None). From then, test-day markets still without a yes/no result are left out of
    the single look and listed with it. Found earlier today: Kalshi settled KXRAIN-26OCT30-PHX as "scalar", and two
    later Phoenix markets were unsettled, so without a cutoff the look could stay pending for good.
  - TRADE_AFTER_LOOK = True (new): v3 rain keeps paper-trading market days from Nov 11 on whatever the stored look
    says, including while it is pending or cannot be worked out. False restores the Oct 28 rule.
  - The look is still taken once, stored and reported as the only verdict. report(), look_line and the error message
    say what now happens.
- Unchanged:
  - shadow.py's limit-order ledger keeps the old rule (no orders after a failed or pending look).
  - live.py, with all of its locks: no real money before Nov 11, the user's own `live use prod` and typed unlock, the
    $25 cap, the $2.50 daily loss stop, the drawdown pause and the kill switch.
- gate.py mirrors both values for the dashboard; tests/test_fix.py checks they agree.
- Texts updated for the new rule: dashboard.py (the verdict), research/nov11.py (money_line), audit.py (the
  GATE_NOT_PASSED reason), registry.py (v3's note) and docs/ARCHITECTURE.md.
- tests/test_gatelook.py: sections 1-10 still prove the old rule with the flag off. A new section 11 proves the new
  one: trades continue after a pending, failed or unworkable look; the look is stored once; the ledger stays stopped;
  the Nov 18 cutoff leaves a never-settled test-day market out. tests/test_nov11.py follows the flag.
- PLAN7: strategy.py's change gives v3 a new model_version. Deployed before the Nov 9 evening scan, it appears on a test
  day, which PLAN7's fit_versions accepts; weather.py and nws.py are unchanged. PLAN8's frozen identity does not
  include strategy.py.

## 2026-11-06 21:00 (local) - refactor stage 4 (no functional change)
- User: "act like a senior engineer ... do not change functionality". docs/REFACTOR.md section 7 has the review: data
  growth, the problem areas ranked, what stays frozen and why.
- Changed:
  - freshness.checks() is split into six named sections;
  - control_view.section() is split into nine;
  - dashboard.shadow_view() is split into three panels.
  - tests/golden.py: skips backup copies named by the clock second, masks 24-hour clock labels, and runs the gatelook
    scenario.
- Proof:
  - golden master (old, new, old again): 167,461 data fields and 15,794 text pieces, 0 differences;
  - the page and the freshness checks built from copies of the PC's real files are identical (clock times masked);
  - 41 tests pass.
- Not touched: live.py, the forecast (weather.py, nws.py, kalshi.py, core.py, config.py), shadow.py, stationfc.py and
  the pre-registered scorers.

## 2026-11-06 21:45 (local) - independent code review of the two changes above (agents/code-reviewer.md)
- Verdict:
  - live.py is untouched. Its locks, limits and kill switch are not loosened or bypassed, and real orders still need
    the user's deposit, `live use prod` and typed unlock.
  - The look is stored once.
  - The limit-order ledger stays stopped after a pending, failed or unworkable look.
  - PLAN8's identity is unchanged.
  - The refactor changes no output. The reviewer swapped the old functions back in and compared on the real paper.db
    and 21 scenario databases, plus a symbol-table check. The only exceptions are the documented empty-registry case
    and which KeyError is raised for a missing table.
- MUST, fixed: the control center's safety line (control_view.safety_line) still said the bot paper-trades after Nov 11
  "only if the gate's single look passes", contradicting the verdict on the same page. A user could read that and
  believe the unlock does nothing. It now follows gate.TRADE_AFTER_LOOK, and test_gatelook checks the page for the old
  phrases.
- SHOULD:
  - Fixed: the limit-order ledger's rule text in registry.py.
  - Applied, deploy timing:
    - PLAN7 and PLAN6 B count the new model version only once a PC scan logs it for a test day (market day up to
      Nov 10).
    - Deploy to the PC and the repository together, byte-identical, before the Nov 8 evening scan.
    - Afterwards, check the decisions ledger for the new version. If it has not appeared by the Nov 9 scan, ask the
      user about PLAN7's amendment.
    - All strategy.py text fixes are in this same release.
  - Left, as a ticket: a market Kalshi settles as neither yes nor no (KXRAIN-26OCT30-PHX was "scalar") leaves a paper
    trade open for good in strategy.settle. live.py sync records P&L only for yes or no, so such a loss would never
    reach the daily loss stop or the drawdown pause, and stays counted as at risk. The $25 cap still bounds it. A live.py
    change needs the user's instruction; he is told.
- COULD:
  - Fixed: look_line wording ("Then v3 rain keeps paper-trading ...; live.py copies them with real money only after you
    switch it to prod and type the unlock"; no doubled phrase; not "an account you funded", since demo needs no unlock).
  - Fixed: report()'s stop-date line no longer says "no live trading" when TRADE_AFTER_LOOK is on.
  - Fixed: the dashboard's failed-look text, the same way.
  - Fixed: golden.py masks only the time in "Nov 07 00:22", and counts backup copies per folder and tag instead of
    dropping them, so a missing backup still shows.
  - Added: a test that no state other than a pass gives live.py's unlock its "passed (paper only)" text.
  - Added: notes in CLAUDE.md sections 5 and 11a.
  - Left: if gate.py cannot be imported, the page falls back to the old rule's wording (text only).
- After the fixes:
  - 41 tests pass.
  - The refactor's golden comparison is still 0 differences with the tightened masks: 167,461 data fields and 15,798
    text pieces.

## 2026-11-06 22:00 (local) - incident: Kalshi's "scalar" and "void" settlements were not understood (fixed)
- User: "act as a senior debugging engineer investigating a live production issue". Full write-up:
  docs/INCIDENT_2026-11-06.md.
- Found: KXRAIN-26OCT30-PHX is finalized with result "scalar" at $0.99 (Kalshi's API, read on the PC with kalshi.get).
  The Nov 3, 4 and 5 Phoenix markets are still closed with no result.
- Root cause: paper (strategy.settle), the limit-order ledger (shadow.settle) and live.py (sync) each settled only "yes"
  and "no". Kalshi also reports "scalar" (YES pays the settlement value, NO the rest) and "void" (cost returned), so a
  trade or order on such a market would have stayed open for good:
  - its cost held room under the 15% cap and the live $25 at-risk count;
  - its loss never reached the paper daily stop or live.py's daily loss stop and drawdown pause.
  - The bot held nothing on the affected markets (checked in paper.db and live.db).
- Fix: one rule in strategy.py, used by all three ledgers and the account view:
  - settle_value, payout, settled_pnl and market_of (result_of wraps it).
  - yes/no: unchanged, to the bit.
  - scalar: only once finalized and with a value from 0 to 1.
  - void: only once finalized, P&L -fee.
  - An unreadable final result stays open with a warning.
  - The gate's log (obs) and the ledger's market results stay yes/no.
  - dashboard.won and account_view show scalar and void by their P&L.
  - live.py: only sync changed, and only so these losses reach the stops; no lock or limit changed.
- Tests: tests/test_settle.py section 8 and tests/test_live.py section 8; the full suite passes (41). PLAN8's frozen
  identity is unchanged; pre-registered scorers are untouched.
- Tonight's run (20:55-20:58, exit 0) was otherwise healthy: 3 paper trades (Nov 7 ABQ YES, SATX NO, PVD NO); the demo
  copies were skipped for "no price to buy at" on the demo exchange; FRESHNESS all current.

## 2026-11-06 22:30 (local) - independent code review of the settlement fix (agents/code-reviewer.md)
- Verdict:
  - Safe for real money: no lock, limit or kill-switch path changed. Settling scalar and void can only bring the daily
    loss stop and the drawdown pause into play sooner.
  - yes/no P&L is unchanged to the bit: 200,000 random cases, paper and live rounding.
  - PLAN8's identity is unchanged (41 keys).
  - The full suite passes.
- MUST: none.
- SHOULD:
  - Deploy timing: done. It ships with the earlier changes in one deploy (scheduled 2026-11-07 10:00). Afterwards the
    decisions ledger must show the new model version on a test market day by the Nov 9 scan. The new version is
    v3@ca1cc9fd54b0 before the final text edits; the deploy notes the final hash.
  - The limit-order ledger test: added to tests/test_settle.py (scalar NO, void, yes, scalar without a value).
  - Left, told to the user:
    - The gate's single look now counts a scalar or void trade as settled, by definition: it counts toward the 50 and
      its real P&L toward the net. Before, it would have kept the look waiting. No test-day trade is on such a market.
    - Win counts in report(), control_view, metrics, postmortem, learn and shadow's report still call scalar and void
      "not won", while the dashboard and the account view go by P&L. Money figures are right everywhere. A shared
      helper is the follow-up. nov11.py (PLAN6) is frozen.
- COULD:
  - Fixed: the older cents field must hold a whole number (fail closed).
  - Fixed: the warning no longer says "its paper trade" when there is none.
  - Left:
    - "Refunded" label for void;
    - a side table so never-binary markets stop being re-queried at each settle (one request each, as before);
    - shadow's local import of strategy.
  - The void fee assumption is noted above and in docs/INCIDENT_2026-11-06.md.
- After the fixes: 41 tests pass.

## 2026-11-06 21:30 (local) - assessment of the decision process, and the user's no-rain filter for live.py
- User: "fully assess. do we have a better decision making process?" Read-only on paper.db, 334 resolved rain markets
  with all three sources (11 days).
- Accuracy, Brier score (lower is better; day-clustered difference against the price):
  - Kalshi's price: 0.0584;
  - v3: 0.0806, worse by 0.020 +/- 0.006;
  - the airport forecast: 0.0761, worse by 0.016 +/- 0.007;
  - the bot's 50/50 blend: 0.0659;
  - 80/20 price and airport: 0.0602, worse by 0.0016 +/- 0.0011.
- Rules so far, per contract:
  - v3 paying the ask: -3.4c +/- 8.2 (29 bets);
  - limit orders: -0.2c +/- 12.9 (29);
  - airport-forecast signals: -3.6c taker and -5.1c maker (35 and 38);
  - the watch-only selector: +8.1c, 8 of 8 won. It buys favourites at 87-95c; 8 of 8 at those prices happens about half
    the time, and buying favourites lost after fees on 81 past days.
  - Told: none of these is better than trusting the price. The improvements are to anchor on the price (PLAN8), correct
    v3's lean (PLAN7), use limit orders (a new strategy for real money, which needs its own test), bet only on a
    forward-tested edge, and pre-commit an end rule for real money.
- The user: "november 12 we start real money trading (not negotiable)", then "yes" to the filter.
- live.py changes:
  - SKIP_NO_FROM = 0.50, v3_forecast(t, paper_id) and filter_reason(t, side, paper_id).
  - A NO paper trade is not copied when v3's own forecast for it is 50% or more.
  - The forecast comes from the trade's own decision row (written with the trade); obs is the fallback, since obs keeps
    the first snapshot, which can come from an earlier evening.
  - It fails closed: an unreadable, NaN or out-of-range forecast means no copy.
  - mirror() records a skipped row with the reason (never retried), and place() checks it again before anything is
    written or sent.
  - status() prints the rule.
  - It applies on demo and prod alike, and it only removes orders.
  - No lock or limit changed.
- tests/test_live.py:
  - section 8b: the 50% boundary, a missing forecast, YES unaffected, under 50% copied, no retry, place() blocked, the
    status line, and the decision row beating an older obs snapshot;
  - the paper() helper now logs an obs forecast (0.30 by default) as the scan does.

## 2026-11-06 21:45 (local) - independent code review of the no-rain filter (agents/code-reviewer.md)
- Verdict:
  - The filter is safe and can only remove orders. It runs before anything is written to "sending" or sent to Kalshi.
  - No lock, limit or kill-switch check moved.
  - The data is right: decisions.p_model is the exact forecast the trade was decided on, written in the trade's own
    savepoint.
- MUST: none.
- SHOULD, both fixed:
  - A "database is locked" error on the decision read fell back to obs, which can hold an older first snapshot.
  - A decision row with an empty forecast also fell back to obs.
  - Now, while the decision ledger exists, a paper trade's forecast comes only from its own decision row. A missing
    row, an empty value or any read error counts as unreadable, so the copy is skipped (fail closed). obs is used only
    when there is no ledger at all.
- COULD:
  - Applied: the strategy id comes from strategy.STRATEGY_RAIN; live.py's docstring lists the filter; tests cover a
    missing row, an empty forecast and place() blocking on the decision row's value.
  - Left: paper_ro() outside the try (it fails closed, as paper_trade() does), and the permanent skip after a passing
    read failure (the same as the other skips).
- Checked on the PC's real paper.db:
  - Of 34 v3 rain trades, only the two of Oct 15 (before the ledger existed) lack a decision row.
  - Every later decision forecast equals obs.
  - The filter would have skipped Nov 5 TTN and PHIL, Nov 6 DC and tonight's SATX and PVD "no rain" bets, and copied
    tonight's ABQ YES.
- Side note: the reviewer's probe wrote a 16 KB backup of its own scratch database into the cloud container's
  /root/Documents/tradebot_backups. It is not on the PC and holds no project data.

## 2026-11-07 10:10 (local) - PLAN9 written, reviewed and frozen before its forward data
- User, 2026-11-06 evening: "use/implement your recommendations above. use open source options if available", then
  "we need a fully free option/alternative".
- Open-Meteo's ensemble API was approved for research and a logger was drafted (research/ensfc.py). Both were dropped
  before any use: its free tier is non-commercial only. The logger was deleted before any deploy, and no call was made
  except one format check of the API.
- research/PLAN9.md and research/plan9.py: v3's own 24 hourly NWS chances combined in four 6-hour blocks ("v3-6h",
  clipped like v3).
  - Tests in a fixed order: B (v3-6h vs v3), then A (v3-6h vs the price) only if B is confirmed. Each at the one-sided
    2.5% line, t plus the block bootstrap.
  - Futility at 60 counted market days, showing only the signs; final at 110; backstop 2027-06-30.
  - Market days from Nov 8. Fully free data the bot already logs; no new source, address or package.
  - tests/test_plan9.py; run.bat's settle runs `plan9.py auto` (its CRLF line endings were restored after an edit had
    turned them into LF in the work copy; caught before any deploy).
- Statistics review (agents/statistician.md):
  - Verdict: the forward test is valid; choosing among six rules only inflates the in-sample numbers.
  - Applied:
    - B's wording: v3-6h is never below v3, so B passes whenever v3 runs low and cannot show why.
    - Expected results stated honestly.
    - Readiness: a day with missing results counts after 7 days only once a settle recorded a result past that mark,
      and a day with no resolved market takes no slot.
    - The identity record is stored once before the first window and never re-created.
    - The fixed sequence (B then A at 2.5%) instead of Bonferroni at 1.25%.
    - The four-test line (0.625%) for any trading proposal.
    - The futility look shows only signs and counts.
    - The gate's reading is labelled "not this plan's verdict".
    - Section 7 says plainly that B without A has no trading value.
    - A power section, all six rules with their in-sample Brier, and the window wording (each row's own log time).
    - Clipping like v3.
    - Two descriptive readings at the final look: calibration 30-80%, and the 00:50-01:30 UTC subset.
  - Left: the other descriptive splits (Brier decomposition, by time zone, against PLAN7's q).
- Code review (agents/code-reviewer.md):
  - Applied:
    - MUST 1: a lost or damaged identity record could be silently re-created. Now a damaged file stops the looks, a lost
      one is restored from its off-folder copy, and none is created after the first window opens.
    - MUST 2: looks could be recomputed. Now they are stored once with an off-folder copy, a damaged one stops the
      looks, and the final look needs the stored futility look.
    - SHOULDs: main catches SystemExit; PLAN7's t table is pinned (the constants hash); amendments cover PLAN7 pins too,
      in PLAN8's format; status shows "CODE CHANGED" and exclusions; signs only at futility.
    - COULDs: exclusions only for the look's days; the Markdown is written atomically before the JSON; the final look
      keeps the futility look's counted markets.
  - Left: identity coverage of weather.RAIN, the obs insert and kalshi.quote (wider than the plan states).
- Frozen (SHA-256):
  - research/PLAN9.md 2383e0d5fe1d75ab7e94c50d40d11a86e64261ffccfd8dddd21d0295b946502e
  - research/plan9.py fd1454af16fe07ef294a7d4f2ca1667c5ab1a4cfd7764bd79e272d1b307edb64
  - The identity record is stored on the PC at the deploy, before 2026-11-08 00:50 UTC.

## 2026-11-07 22:00 (local) - two live-only rules: the 6-hour filter and the end of the real-money trial at the drawdown
- User: "does this mean our system still needs improvements? what would you recommend?", then "implement your
  recommendations to improve the bot". The recommendations: leave v3 unchanged (gate, PLAN7); keep the no-rain filter;
  a second live-only filter from v3's own hours in 6-hour blocks (my lean: yes); the 25% drawdown as the end of the
  real-money trial; then wait for PLAN7, PLAN8 and PLAN9 without tuning. Taken as his yes to the two open choices.
- Told before building: by the bot's real rule (edge against the ask, not the mid that my first screen used), the
  6-hour filter passes only 3 of the 36 v3 rain paper trades (2 settled: won 1, -$0.38), against 14 settled (won 5,
  -$1.21) for the no-rain filter alone. So real money will be quiet (about one bet every 4-5 nights), and the filter
  would not have made more money on the trades so far; its point is fewer bets while the price beats v3.
- live.py (the only file changed in code):
  - AGREE_6H: filter_reason() now applies, after the no-rain filter, agree_reason(): v3-6h (six_hour(), PLAN9's
    definition, checked against plan9.v3_6h on 2,000 random cases) blended 50/50 with the mid must give the paper bot's
    8-point edge (config.BLEND, config.MIN_EDGE, strategy.scan's own test) on the same side against the price paid.
    trade_inputs() reads the trade's own decision row (it must name the same market and side); without the decision
    ledger, obs and the trade, as v3_forecast() does. Unreadable inputs or hours: no copy. Checked in mirror() and in
    place(), on demo and prod.
  - END_ON_DRAWDOWN: end_trial() locks real money (settings mark, then a lock event, then a trial_end event) the first
    time the 25% drawdown pause is on since the last resume; mirror() runs it before the lock check and sync() after
    settlements. A failed lock prints a warning; the pause still stops every order and the next run tries again.
    stops() says on prod that the trial ended and that restarting needs resume and unlock; status() shows both rules
    and an ended trial; unlock() and resume() print the facts (unlock's disclosure now names the filters and the end
    rule). No requirement of unlock, resume, lock or any limit changed.
- Not changed: strategy.py, weather.py, nws.py (model_version and PLAN7/PLAN9 identities), shadow.py and kalshi.py
  (PLAN8 identity), config.py, paper trading, the gate, the dashboard.
- Checks: tests/test_live.py sections 8c (filter: pass/skip at the 8-point line, side flip, unreadable hours, no
  decision row, wrong side, no inputs, place() blocks, the obs path, the switch, status) and 11b (end rule: failed lock
  then lock, once per pause, unlock alone not enough, resume then unlock restarts orders, a drawdown found by sync ends
  it again, resume alone says still locked, demo untouched); the paper() helper now writes the hourly chances and a
  decision row as the scan does. Full suite: 42 tests pass. On a copy of the PC's paper.db (read-only, unchanged), the
  deployed code skips exactly the trades counted by hand: 3 of 36 would be copied.

## 2026-11-07 22:45 (local) - independent code review of the two live-only rules (agents/code-reviewer.md)
- MUST 1 (fixed): after the trial ended, the drawdown pause could lift by itself when open bets settled as wins, and
  then a typed unlock alone restarted real money, against the rule's "resume and unlock". Now lock_reason() keeps real
  money locked while trial_end stands (until a resume), so place() enforces it too. New test: trial ends, unlock alone,
  a winning settlement lifts the pause, mirror and place() still refuse. A mutation check (the new line removed) makes
  the test fail.
- SHOULD 2 (fixed): a failed settings write stopped end_trial() before live.db's lock. The settings mark and the live.db
  lock event are now separate tries (either alone locks); the message says which could not be written. Tests: both
  fail (warning, pause still stops orders, nothing recorded), only the settings file fails (live.db lock holds).
- SHOULD 3 (fixed): the test's $25-cap headroom in section 12 was thin after the new fixtures; section 12 now starts
  with the fake exchange's positions cleared.
- COULD 4 (fixed): an integer too large for a float in the stored hours crashed mirror(); _num() now rejects it, and
  any unexpected error in the 6-hour check becomes "could not be checked; not copied" without stopping other copies.
- COULD 5 (applied, only removes orders): the 6-hour check now also applies the bot's 30-point veto (VETO_MAX_GAP,
  imported from strategy.py, which is unchanged) to v3-6h, so "the same bet by the bot's own rule" is the whole rule.
  On the real record it changes nothing: still 3 of 36 trades pass. The test fixtures' default hours were moved inside
  the veto.
- COULD 6 (fixed): tests at the exact 8-point line (decided as strategy.scan decides), the decision row winning over
  obs both ways, live.db unwritable, and the demo check moved to section 9 where a demo drawdown really runs mirror.
- COULD 7: stops() no longer claims "locked again" (it may not be). Left: the dashboard tile and the control center's
  safety line do not mention the two filters (live status does); presentation only, left to keep this release to
  live.py. Also left: the demo pause lifts by itself on recovery (older behaviour; CLAUDE.md 3a says "until resume").
- After the fixes: full suite 42 tests pass; on the copy of the PC's paper.db the code copies the same 3 of 36.
- Re-review of the fixes (same reviewer): no MUST left; nothing loosens a lock; both restart orders work. Its COULDs,
  applied (each only tightens or clarifies): end_trial names the record it could not write (the lock or the trial_end
  record) and, when only the settings file failed, tells you to run `.\run live lock` (which retries it); resume() on
  real money runs the end rule before writing the resume, so a drawdown whose locks failed earlier still ends the
  trial; tests at the veto's exact 30-point line and 31 points, resume-then-unlock restarting orders, the trial_end
  record failing (locked, retried next run), and resume ending the trial first. Left (very unlikely): live.db
  unwritable for the whole time the pause lasts, while only the settings file can be written: the settings mark keeps
  real money locked, but then a typed unlock alone (without resume) would restart it. Full suite: 42 tests pass.

## 2026-11-07 22:20 (local) - the 6-hour filter ships off (the user's choice)
- User, 22:11: "we don't need fewer bets... we need more successful winning bets". live.AGREE_6H = False before the
  deploy; the code stays, reviewed and tested both ways (tests/test_live.py 8c switches it on for its checks, then off,
  and asserts the shipped value). status() says "the 6-hour check is off". The end rule (END_ON_DRAWDOWN) and the
  no-rain filter stay on. No threshold, limit or lock changed.
- On a copy of the PC's paper.db, with the shipped settings, live.py would copy 16 of 36 v3 rain paper trades (14
  settled: won 5, where the prices paid implied 5.5 wins; -$1.21 on paper) and skip 20 by the no-rain filter (17
  settled: won 1, where the prices implied 2.5; -$6.65). Full suite: 42 tests pass.
- Deploy check (01:12): `live.py status` on the PC printed "25%%" in the new end-rule line (a literal string, not
  %-formatted). Fixed, with a test that status shows no "%%"; redeployed before any scan used it.

## 2026-11-11 11:30 (local) - r81: paper research continues after the look; learning report judges the filters; PLAN10 written
- User, 2026-11-09: "implement your recommendations above. we also want to continue paper trade research even when we
  switch to real money ... write the HRRR plan with a $1000000 target ... investigate why we lost [Providence Nov 7,
  Seattle Nov 8] ... are we learning from trades won and lost?". Work stopped on Nov 9 at a usage limit and resumed
  on Nov 11 ("intelligently resume the above").
- The two losses (read-only): both "no rain" at 7c with the price at 94% rain; v3 said 72% and 70%; v3's 6-hour
  version (90%, 88%) and the airport forecast (91%, 99%) agreed with the price. v3's low lean. Real money would not
  have made either bet (no-rain filter; moved price).
- shadow.py: MAKER_AFTER_LOOK = True. The limit-order paper ledger keeps placing its hypothetical orders after the
  gate's look (False restores the Oct 28 rule). v4_log and _t (PLAN8's identity) are byte-identical. strategy.py is
  untouched (model_version, PLAN7); its comments about the old ledger rule are left on purpose. registry.py: the
  ledger's note updated.
- learn.py: new read-only section "Real-money filters, judged on paper": passes the filters / filtered out / inputs
  unreadable, before and from market day Nov 7 (when the filters were chosen), with wins against the wins the prices
  implied; and the 10 newest settled trades explained (v3, price, v3 6-hour, airport forecast, and how many of the
  other two views would have made the same bet by the bot's rule, veto included). It asks live.py's own functions;
  the pattern screen is unchanged (same group count on the same database).
- research/PLAN10.md (HRRR on PLAN.md's past markets), written before any HRRR data. SHA-256 at its freeze:
  69208ee2904271f79d185f31c6a24598da67fe29dbcf7666aa09291fa234ff08. Its code, the install and the download wait for the user's yes.
- Independent statistics review of PLAN10 (agents/statistician.md): MUST 1, the holdout was scored before with a
  correlated blend, so a pass is at most "a lead on reused past data: justifies PLAN10F only" (false-pass rate about
  4-7%, not 2.5%); a paired comparison with the airport-forecast blend added. MUST 2, the base market set N0, the 10%
  rules and the West Palm Beach re-code defined. SHOULDs applied: T is descriptive (the money test moves to PLAN10F);
  power for realistic gains stated; section 10 labels the 5-a-night column an upper bound, drops the long-shot row and
  adds that the 25% end rule stops the road to $1,000,000 (34% within a year of nightly bets even with a very good
  edge); the fitted model is committed before any holdout download; HRRR version and retirement checks; the five-test
  line is a report only. The money table was recomputed by the reviewer and matches.
- Independent code review of r81 (agents/code-reviewer.md): no MUST. Fixed: the "others that would bet too" column
  now applies the 30-point veto; trades whose inputs cannot be read are their own group, not counted as the filter's
  skips; labels say "passes the filters", not "copied" (a real copy also needs price, seller, cap and unlock); the
  registry text; result shown as it is for scalar or void. Left: the airport column uses the first log of the market
  (footnoted). Verified by the reviewer: frozen files and PLAN8's function hashes identical, importing live.py has no
  side effects, both databases unchanged, mutation check on the ledger switch.
- Seen on the PC: on the demo exchange every copy since Nov 8 was skipped ("no price to buy at", or a price unrelated
  to the real market). Demo books are thin; noted in CLAUDE.md section 8. The gate look is still pending (no stored
  look yet). Full suite: 42 tests pass.

## 2026-11-11 16:45 (local) - r82: live.py's at-risk cap raised from $25 to $50 (the user's explicit instruction)
- User, 11:06: "we need to use the $25 promotional credit given, so raise it to $50 for placing orders."
  A limit in live.py loosened at his explicit instruction (CLAUDE.md section 3).
- live.py: MAX_AT_RISK = 50.0. Only the cap moved. A new constant STAKE = 25.0 (his own money) keeps everything else
  that used the old value as its base exactly as before: the daily loss stop (DAILY_STOP = $2.50), the bot's value and
  drawdown peak (the 25% end rule still trips after about $6.25 of net loss), and the doubling reminder.
  dashboard.py: the account tile says $50. README.md and docs/ARCHITECTURE.md updated.
- Told plainly: this changes no order the bot places today. Copies never exceed the paper count, and paper holds at
  most $3.75 open at once (MAX_OPEN_PCT x BANKROLL), so the cap only matters next to his own manual positions. Making
  bets bigger is a separate sizing decision and was not taken.
- Left on purpose, still saying $25: research/nov11.py (the pre-registered Nov 11 report, pinned by its test),
  strategy.py comments (model_version, PLAN7), research/PLAN10.md (frozen). research/lip.py's $25 is a research figure.
- Independent code review (agents/code-reviewer.md): the live.py change is correct and only the cap moves; mutation
  checks (cap removed, room on STAKE, daily stop on the cap, value on the cap, cash check removed) each fail the tests.
  Its findings, applied: deploy the three code files apart from the dashboard redesign (reviewed separately as r83);
  CLAUDE.md sections 3a and 12 and this entry; the cash test restored to the fake's $0.30 with the note asserted; a
  test that the dashboard tile names live.py's cap; stale "$25 cap" wording in tests. Full suite: 42 tests pass.

## 2026-11-12 08:30 (local) - r83: dashboard redesign layer reviewed and fixed; PLAN11 revised after its statistics review and frozen
- **r83 (dashboard_assets.py, presentation only; no text or number on the page changes).** Independent review (fresh agent, Chromium at 320 to 1100 px, light and dark): 3 MUST, 7 SHOULD, 4 COULD.
  - Fixed (MUST): a very tall section could stay invisible on a small or zoomed window (observer threshold 0 plus a backstop in the scroll handler); the printed page lost its title (print rule resets the gradient text); the sticky menu covered anchor targets and focused controls (`html{scroll-padding-top}`).
  - Fixed (SHOULD): the wrong menu link was marked when two sections sit side by side (first of the row, or the clicked one); fallbacks for browsers without `background-clip:text` or `color-mix`; the back-to-top button is not focusable while hidden and hands focus to the menu; a menu click moves focus to its section and sets `aria-current`; the tooltip sits above the button; the title's gradient now spans the word (inline-block).
  - Left: menu entries per sub-heading, hover rules under `(hover:hover)`, the fixed page gradient on iOS, the dead `#tbsecN` hashes on load (all cosmetic).
  - Tests: tests/ui_checks.py has 6 new checks (menu click, no hidden section at 341x150, back-to-top shown/returns/hides, print title): 65 checks pass at 390 dark touch and 1100 light; full suite passes.
- **PLAN11 (research/PLAN11.md), statistics review: 4 MUST, 7 SHOULD, 3 COULD, all applied before any of its data.**
  - M1: a third pass condition, the exact win-rate lower bound over signal days against the mean cost, because many small wins and no loss would pass the t and bootstrap by luck; the power it implies is stated (G is almost surely not confirmable in 119 days).
  - M2: the gauge rule pinned (hourly Pxxxx group only, no summing, the boundary report ignored, traces and corrections out).
  - M3: the price pinned (candle ending at t + 1, else within 5 minutes, else no trade; 0 < bid < ask) and the day start read from the market itself.
  - M4: radar readings pinned (colour table to dBZ, index 0 = no echo, great-circle distance, 150 km search, exact stamps, a 4-pixel minimum against clutter; P cannot fire on a newly formed cell). The grid is 12200 x 5400 per IEM's documentation, not "about 1 km".
  - SHOULD/COULD: Holm's order spelled out with one bootstrap, the denominator, one market per station and day, the gauge-is-not-the-settlement cases, adverse selection, the conservative delays, the disclosure of earlier price reads, three more descriptive lines.
  - Frozen. SHA-256: 244f408a67232fd78f01aa759e9ccc7ced7e986fa6ef79c0618b165a04dbe3f6
- No rule, limit, lock or threshold changed. v3 (weather.py, nws.py, strategy.py) and live.py untouched.

## 2026-11-12 08:45 (local) - r84: closing-price scorecard in the learning report (read-only)
- learn.py: new section "Closing-price scorecard (v3 rain)" (moves_data, move_stats, move_reading, moves_record): for each
  v3 rain paper trade, how many cents Kalshi's mid moved toward the side the bot bought between the evening scan and the
  market's day start (shadow_moves, already measured at each settle). Mean over market days with its day-clustered
  standard error, split by side, plus the same for every logged market where the raw forecast and the mid differed by 8+
  points. Numbers also go to learning.json (closing_price). It reads paper.db read-only and cannot stop the report.
- Independent code review (agents/code-reviewer.md): 2 MUST, 3 SHOULD, 5 COULD, all applied.
  - MUST: a trade bought at a later scan than the market's first snapshot was credited with a move from before it
    bought; now only trades within 10 minutes of that snapshot count, the rest are listed as not measured.
  - MUST: the wording presented a positive average as skill. It now says a noisy evening price drifting back toward
    any sensible forecast gives a positive move with no skill, and that the bot pays the ask plus the fee.
  - Also: a coverage line, first trade per market only, an infinite t no longer written to JSON, the Student-t line
    (never below 2.0) with 20+ market days, stronger tests (8 mutations each fail).
- Descriptive, not a test: it changes nothing in the bot. No rule, limit or threshold changed; v3 and live.py untouched.
- Same release, dashboard_assets.py (presentation only): yesterday's menu check failed on today's test data. When the
  last section is too short to reach the top of the window, clicking its menu link marked the section above it. Now the
  clicked link stays marked while the page sits at the bottom with that section in view; scrolling by hand (wheel,
  touch, keys outside the menu) releases it. Independent review (agents/code-reviewer.md): 1 MUST (a clicked link could
  stay marked after scrolling by hand), fixed with a lower bound and the release on hand scrolling, plus a test that
  fails without the fix. tests/ui_checks.py waits for smooth scrolls by polling instead of fixed pauses.
  66 checks pass at 390 dark touch and 1100 light; full suite passes.

## 2026-11-13 01:50 (local) - PLAN14 and PLAN15 written before their data, reviewed and frozen; new sources approved
- The user's request of 2026-11-12 11:41 (skill vs luck on sports and crypto: trade patterns, reaction speed, one
  league's rating model, placebos and many-tries control, costs and capacity, plain reporting, penny-stock hype as a
  risk only) became research/PLAN14.md; the request of 18:57 (an AI system for Kalshi's 15-minute up-or-down markets)
  became research/PLAN15.md. Both written before any price, trade, result or report for them was read.
- Independent statistics review (agents/statistician.md). PLAN14: 6 MUST (in-play trades after the reference price;
  timing buckets that used the actual close; power recomputed from the code's own standard error, about 20c a
  copy-day at Holm's first step; the "reachable" rule read noise as reachable, now signed and baseline-corrected with a
  pre-event window; placebo matched on timing bucket and price band; the injury version's multiplicity and Elo
  details), 6 SHOULD, 3 COULD. PLAN15: 5 MUST (signal at k against the ask at k, fill at k + 1, candle labels; the
  reference window and price from the market's own fields; a side-flip placebo matched on prices and fees; power
  about 5c a contract, not 1.5-2c; ETH in the same 12-test family, one model per asset and minute), 3 SHOULD, 3 COULD.
  All applied.
- The user's answers of 2026-11-12 (asked in so many words): Coinbase's public market-data feed approved (PLAN14
  Part 2, PLAN15); the NBA's official results, schedule and injury reports approved (PLAN14 Parts 2 and 3); no paid
  sportsbook odds (Kalshi's close is the benchmark); penny stocks as a written summary only. Recorded in CLAUDE.md
  section 3.
- Frozen. SHA-256: research/PLAN14.md 87dfae21c419d9bb7a2d6dbee308810c00f65ff5f0d65ae6fa754e001354f144;
  research/PLAN15.md f185768108ae6bc324bad673f81b637374f5952b9984038bfbcf320090eae30d. Their code (plan14.py,
  plan15.py) is written, code-reviewed and frozen before the first download.
- Lost work, logistics only: the cloud workspace was reset on 2026-11-12 between 08:45 and 18:57 La Paz, and the first
  draft of research/plan10.py (written that morning, reviewed by no one, never deployed or pushed) was lost with it. It
  will be written again; no data had been downloaded. Drafts are now kept in the PC folder as well as the cloud.
- No rule, limit, lock or threshold changed; v3 and live.py untouched.

## 2026-11-13 10:45 (local) - r86: PLAN10 and PLAN15 code written, code-reviewed, fixed; the user's 7 clarifications applied (not frozen yet)
- research/plan10.py (HRRR; rewritten after the lost draft), research/plan15.py (15-minute BTC/ETH markets), their
  workflows (cloud/workflows/plan10.yml, plan15.yml; started by hand only; actions pinned to release commits) and
  tests (tests/test_plan10.py, tests/test_plan15.py). Nothing downloaded yet.
- Independent code reviews (agents/code-reviewer.md), all MUST and SHOULD items fixed:
  - plan10: the holdout download now always needs the committed model; network and decode errors are counted, not
    fatal; four scoring mutations that slipped past the tests are now caught; ecCodes pinned with a one-field check
    stage; the commit guard allows only features and the model; the score re-checks the training rows.
  - plan15: the archive's dollar prices were read as cents (100 times too small); the market listing used a filter
    Kalshi refuses; numpy (not approved for PLAN15) removed; missing windows counted against 96 a day; fee history
    fails closed; Coinbase requests overlap by a minute; three scoring mutations now caught; freeze runs on the PC.
    Raw Coinbase prices are never stored (market-data terms); only the per-window numbers the test needs.
- The user's "yes" of 2026-11-13 10:30 to seven clarifications, asked in so many words before any data:
  - PLAN10: (1) the NOAA files are fetched with the project's own byte-range requests instead of Herbie, so every
    request carries the User-Agent rule's string (same files, same decoding library); (2) "within 40 km" = great-circle
    distance on the HRRR sphere (6,371.229 km) of 40.0 km or less, "0.01 inch" = 0.254 mm or more, the station's own
    amount at the nearest grid point within 40 km, and no "confirmed" with fewer than 14 days; (3) the scored days'
    per-station forecast numbers are committed publicly after the model is frozen (no prices or results); (4) West
    Palm Beach markets under its old code KPBI count under KDJT (plan10.home_station, tested).
  - PLAN15: (5) the spot "up or down" for the 97% check = the mean of minute 15's open, high, low and close against
    S_0 (SPOT_AGREE_MEASURE = "ohlc15"); (6) the ridge on the summed log-likelihood (RIDGE_SCALE = "sum"); (7) a minute
    with no Kalshi candle uses the last quote of the previous 5 minutes within the window (CARRY_FORWARD_QUOTE = True,
    CARRY_MAX_MIN = 5). The other choices stay in the code as named constants and in the result record.
- Still to do before the first download, on the PC: plan15 inspect and freeze; plan10 freeze and request. Their hashes
  go into this log at the freeze.
- No rule, limit, lock or threshold changed; v3, live.py and paper.db untouched.
- 11:20 (local), same release: the PC link was down, so PLAN15's inspect and freeze can now run once on the GitHub
  runner (workflow stage inspect-freeze; it refuses once an identity record is committed, and freeze() refuses too).
  The public, timestamped commit of research/results/plan15_identity.json is its off-folder copy; the PC receives a
  copy at the next deploy. The score stage also refuses if a result file was ever committed (full history checked),
  so a deleted result cannot allow a second score. Reviewed (agents/code-reviewer.md): no MUST; both SHOULD items
  applied.
- Found the same morning: the 9:25 PM report and the 11:41 PM late-night check of Nov 12 fired about four hours late
  (after 1 AM), so no reminder to wake the laptop arrived in time. Making the late-night check also run at 10:41 PM
  needs the user's say-so (the change was not allowed from this session).
