# tradebot (paper test; Kalshi orders only through live.py)
Run these from this folder in PowerShell. run.bat uses %USERPROFILE%\Python313\python.exe, because "python" on PATH is still the broken Python 3.8.
.\run scan        # evening, before 1:00 AM: backup, log shadow rows and paper trades (under the exposure cap), backup, dashboard
.\run settle      # next afternoon: record outcomes, backup, dashboard
.\run report      # Brier scores, trades, gate (v3 rain only), dashboard
.\run dashboard   # read-only HTML dashboard -> dashboard.html (add --no-open to skip the browser)
.\run backup      # copy paper.db to backups\ and Documents\tradebot_backups
.\run check       # did the evening scan log the next market day? (used by the 11:41 PM backup scan)
.\run export      # write backups\paper_latest.json (a copy of every table; the evening scan uploads it off the laptop)
.\run test        # automated tests on fake data in a temporary folder (never touches paper.db)
.\run learn       # learning report: every settled trade, wins and losses by pattern -> research\results\learning.md (add --past for the past rain data)
.\run kill        # kill switch ON: halts all trading until .\run unkill (.\run kill status shows it)
.\run live setup  # connect a Kalshi account (demo first). You type the key ID and the key file location; the key stays in %USERPROFILE%\.kalshi
.\run live test   # signed read-only check: cash and positions
.\run live status # exchange, locks, account, ledger and the paper gate verdict
.\run live demo-order   # demo exchange only: buy 1 YES contract at the ask with fake money, to prove orders work (add: no, for a NO contract)
.\run live use demo | use prod   # switch exchange; .\run live lock stops real-money orders at any time
.\run live unlock # real money, Nov 11 or later only, typed by you; shows the gate verdict first
Without run.bat: & "$env:USERPROFILE\Python313\python.exe" main.py scan   (same for settle / report / dashboard.py / backup.py)
Market research (research only): python research\markets.py kalshi | poly | inventory | match | gaps -> research\results\inventory.md, gaps.md (Kalshi vs Polymarket on hand-checked pairs). New ideas: research\PLAN3.md, run with python research\plan3.py asos, candlesA, scoreA (test A) and lowlist, lowiem, fitB, candlesB, scoreB (test B); each test is scored once.
Past-data tests (research only): research\PLAN.md, then python research\fetch.py kalshi|cli|nbs and python research\backtest.py -> research\results\. Plan 2 (temperature, overnight drift, later scan): research\PLAN2.md, fetch.py temp|late|nbslate, then python research\backtest2.py.
Dashboard: the "Paper account" chart (1D/1W/1M/3M/ALL, main bot or limit-order test) and Activity / Statements / Tax report, with CSV and printable downloads. Paper money only; nothing there is a tax document.
Only rain markets are traded (temperature markets are logged, not traded, since Oct 14, 2026).
Shadow tests (shadow.py, research only, never part of the gate) run automatically inside run.bat: price moves after each scan and a limit-order version on its own $25 paper ledger. By hand: python shadow.py scan | settle | report.
Kalshi account (live.py): once connected, each scan copies the new paper rain trades to the account (same price or better, never more contracts, at most $25 at risk, immediate-or-cancel) and each settle records the results in live.db. Demo (fake money) works now; real money is locked until Nov 11, 2026 and then needs .\run live unlock typed by you. Live results never count toward the paper gate. Not financial advice: real orders can lose money.
Kill switch: `.\run kill` halts all trading (no paper trades, no shadow orders, no Kalshi orders; backups, settling and the dashboard still run). `.\run kill status` shows it, `.\run unkill` resumes (typed by you; it asks to confirm). Creating a file named KILL (KILL.txt is fine) in this folder does the same. See CLAUDE.md (section 3a for the Kalshi account).
