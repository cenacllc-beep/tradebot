@echo off
rem tradebot launcher. Uses %USERPROFILE%\Python313\python.exe,
rem because "python" on PATH still points at the broken Python 3.8.
rem   run scan       back up, scan, copy new paper rain trades to Kalshi if an account is connected (live.py),
rem                  shadow scan, back up again, refresh dashboard.html
rem   run settle     record outcomes (main bot, Kalshi account, shadow tests), back up, refresh dashboard.html
rem   run report     Brier scores, trades and the gate, shadow results, then refresh dashboard.html
rem   run dashboard  current prices of open paper trades (marks.py), rebuild dashboard.html and open it
rem                  (add --no-open to skip the browser)
rem   run watch      dashboard_live.html: prices and the page refresh every 5 minutes until you close the window
rem   run marks      current prices of open paper trades, then rebuild dashboard.html (no browser)
rem   run hourly     research samples (PLAN5 test L, read-only) and prices, then rebuild dashboard.html (scheduled hourly)
rem   run structure  market-structure scan of open weather events (research, read-only)
rem   run discover   refresh the catalogue of open Kalshi markets and summarize it (research, read-only)
rem   run freshness  how old each dataset is, scheduled-job results and the PC clock (read-only; add --clock to
rem                  measure the clock against Kalshi). Report: research\results\freshness.md
rem   run ohlc       audit Kalshi's one-minute price history of settled markets for broken or old candles (research)
rem   run micro [N]  record order books and trades of up to 12 weather markets for N minutes (default 30), then analyze
rem   run combo      snapshot open combos and their legs, settle earlier ones, report (research, read-only)
rem   run backup     back up paper.db now (inside and outside this folder)
rem   run check      did the evening scan log the next market day? (exit code 3 = not yet)
rem   run export     write backups\paper_latest.json, a copy of every table for the off-laptop backup
rem   run test       run the automated tests (fake data in a temporary folder; never touches paper.db)
rem   run learn      learning report: wins and losses by pattern (read-only; add --past for the past rain data)
rem   run kill       kill switch ON: scans stop trading (no paper trades, no shadow orders, no Kalshi orders)
rem   run unkill     kill switch off (typed by you); "run kill status" shows it
rem   run live ...   Kalshi account: setup, test, status, demo-order, use demo, use prod, unlock, lock, resume, sync
rem                  (live.py; real money stays locked until Nov 11 and then needs "run live unlock" typed by you)
rem The shadow tests (shadow.py) are research only and never count toward the gate. If they or the
rem Kalshi copy step fail, the backups and the dashboard still run.
setlocal
cd /d "%~dp0"
set "PY=%USERPROFILE%\Python313\python.exe"
if not exist "%PY%" (
  echo Python not found at "%PY%"
  exit /b 1
)
if /i "%~1"=="scan" goto scan
if /i "%~1"=="settle" goto settle
if /i "%~1"=="report" goto report
if /i "%~1"=="dashboard" goto dashboard
if /i "%~1"=="watch" goto watch
if /i "%~1"=="marks" goto marks
if /i "%~1"=="hourly" goto hourly
if /i "%~1"=="structure" goto structure
if /i "%~1"=="discover" goto discover
if /i "%~1"=="freshness" goto freshness
if /i "%~1"=="ohlc" goto ohlc
if /i "%~1"=="micro" goto micro
if /i "%~1"=="combo" goto combo
if /i "%~1"=="backup" goto backup
if /i "%~1"=="check" goto check
if /i "%~1"=="export" goto export
if /i "%~1"=="test" goto test
if /i "%~1"=="live" goto live
if /i "%~1"=="learn" goto learn
if /i "%~1"=="kill" goto kill
if /i "%~1"=="unkill" goto unkill
echo Usage: run scan ^| run settle ^| run report ^| run dashboard ^| run watch ^| run marks ^| run hourly ^| run structure ^| run discover ^| run freshness ^| run ohlc ^| run micro ^| run combo ^| run backup ^| run check ^| run export ^| run test ^| run live ^| run learn ^| run kill ^| run unkill
exit /b 1

:scan
set "NOLIVE="
rem kill switch first: when it is on (exit 0), or cannot be checked (exit 1), nothing that trades runs; backups, the
rem export and the dashboard still do
"%PY%" -c "import core,sys; f=core.kill_file(); print(('KILL SWITCH ON (%%s): scan halted. No paper trades, no shadow orders, no Kalshi orders. Resume: run unkill' %% f).encode('ascii','replace').decode('ascii')) if f else None; sys.exit(2 if f else 0)"
set "KS=%errorlevel%"
if not "%KS%"=="0" (
  if not "%KS%"=="2" echo Could not check the kill switch, so the scan did not run.
  if exist paper.db "%PY%" backup.py manual
  if exist paper.db "%PY%" export.py
  "%PY%" dashboard.py --no-open
  "%PY%" freshness.py
  if "%KS%"=="2" exit /b 0
  exit /b 1
)
if exist paper.db (
  "%PY%" backup.py prescan
  if errorlevel 4 (
    echo Backup failed, so the scan did not run.
    exit /b 1
  ) else if errorlevel 3 (
    echo The live.db backup failed: the paper scan runs, Kalshi orders are skipped this time.
    set "NOLIVE=1"
  ) else if errorlevel 1 (
    echo Backup failed, so the scan did not run.
    exit /b 1
  )
)
"%PY%" main.py scan
if errorlevel 1 (
  "%PY%" freshness.py
  exit /b 1
)
if not defined NOLIVE "%PY%" live.py mirror
"%PY%" shadow.py scan
"%PY%" backup.py postscan
"%PY%" export.py
"%PY%" dashboard.py --no-open
"%PY%" freshness.py
exit /b 0

:settle
"%PY%" -c "import core; f=core.kill_file(); print(('KILL SWITCH ON (%%s): settling only records results (it never trades); scans stay halted until run unkill.' %% f).encode('ascii','replace').decode('ascii')) if f else None"
"%PY%" main.py settle
if errorlevel 1 (
  "%PY%" freshness.py
  exit /b 1
)
"%PY%" live.py sync
"%PY%" shadow.py settle
"%PY%" learn.py
"%PY%" backup.py postsettle
"%PY%" dashboard.py --no-open
"%PY%" freshness.py
exit /b 0

:report
"%PY%" main.py report
"%PY%" shadow.py report
"%PY%" dashboard.py --no-open
exit /b 0

:dashboard
"%PY%" marks.py
"%PY%" dashboard.py %2
exit /b 0

:marks
"%PY%" marks.py
"%PY%" dashboard.py --no-open
exit /b 0

:hourly
rem Read-only research and prices: nothing here places orders, so it runs even while the kill switch is on.
rem PLAN5 L: GitHub Actions samples it too since 2026-10-28; this copy (research\data\lip\SECONDARY.txt) is merged into
rem the repository's before the single score, so an hour either one takes counts once.
"%PY%" research\lip.py sample
"%PY%" research\lip.py settle
"%PY%" research\structure.py scan --every 21600
"%PY%" research\discover.py refresh --every 21600 --singles
"%PY%" research\ohlc_audit.py run --every 86400
"%PY%" marks.py
"%PY%" freshness.py --clock
"%PY%" dashboard.py --no-open
exit /b 0

:structure
"%PY%" research\structure.py scan
"%PY%" dashboard.py --no-open
exit /b 0

:discover
"%PY%" research\discover.py refresh
"%PY%" research\discover.py summary
exit /b 0

:freshness
"%PY%" freshness.py %2 %3
exit /b %errorlevel%

:ohlc
"%PY%" research\ohlc_audit.py run
exit /b 0

:micro
rem Read-only polling, about 5 requests a second; nothing is traded.
set MINS=%~2
if "%MINS%"=="" set MINS=30
"%PY%" research\micro.py record --minutes %MINS%
if not "%errorlevel%"=="0" exit /b 1
"%PY%" research\micro.py analyze
exit /b 0

:combo
"%PY%" research\combo.py settle
"%PY%" research\combo.py snapshot
"%PY%" research\combo.py report
exit /b 0

:watch
rem Read-only: marks.py only reads Kalshi prices; nothing here places orders. The pause is a Python sleep, so the loop
rem never spins fast even without a console (timeout.exe fails at once when input is redirected).
echo Live dashboard: prices of open paper trades and the page refresh every 5 minutes. Close this window to stop.
"%PY%" marks.py
"%PY%" dashboard.py --live
:watchloop
"%PY%" -c "import time; time.sleep(300)"
if not "%errorlevel%"=="0" exit /b 1
"%PY%" marks.py
"%PY%" dashboard.py --no-open --live
goto watchloop

:backup
"%PY%" backup.py manual
exit /b %errorlevel%

:check
"%PY%" check.py
exit /b %errorlevel%

:export
"%PY%" export.py
exit /b %errorlevel%

:test
"%PY%" tests\run_all.py
exit /b %errorlevel%

:live
"%PY%" live.py %2 %3 %4
exit /b %errorlevel%

:learn
"%PY%" learn.py %2
exit /b %errorlevel%

:kill
if /i "%~2"=="status" goto killstatus
if /i "%~2"=="off" (
  echo To turn the kill switch off, type .\run unkill yourself in PowerShell.
  exit /b 1
)
"%PY%" killswitch.py on
set "RC=%errorlevel%"
"%PY%" dashboard.py --no-open
exit /b %RC%

:killstatus
"%PY%" killswitch.py status
exit /b %errorlevel%

:unkill
"%PY%" killswitch.py off
set "RC=%errorlevel%"
"%PY%" dashboard.py --no-open
exit /b %RC%
