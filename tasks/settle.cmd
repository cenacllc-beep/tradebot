@echo off
rem Afternoon settle: record results (never trades). Started by Windows Task Scheduler on this PC (tasks\README.md),
rem so it runs even when Claude is closed or out of usage. Output is appended to logs\tasks.log. Never places
rem real-money orders: live.py's own locks apply (demo only until Nov 11 and your typed unlock).
rem The steps are in jobs.py (since 2026-10-24): it waits up to an hour for the network, then runs settle and
rem report, taking turns with the other jobs (joblock.py).
rem jobs.py writes the start and done lines and every step's output into logs\tasks.log itself (2026-10-24), a line
rem at a time, so this file does not redirect: a long wait never locks the log against the other jobs.
cd /d "%~dp0.."
set "PY=%USERPROFILE%\Python313\python.exe"
if not exist "%PY%" goto nopython
"%PY%" jobs.py settle
exit /b %errorlevel%
:nopython
if not exist logs mkdir logs
echo ===== no-time settle >> logs\tasks.log
echo settle could not start: Python not found at %PY% >> logs\tasks.log
echo ===== no-time settle done (exit 9009) >> logs\tasks.log
exit /b 9009
