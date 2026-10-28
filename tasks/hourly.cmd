@echo off
rem Hourly research (read-only): PLAN5 test L samples, structure and discovery scans, prices, dashboard. Started by
rem Windows Task Scheduler on this PC (tasks\README.md). Output is appended to logs\tasks.log. Places no orders.
rem The steps are in jobs.py (since 2026-10-24): it waits up to 10 minutes for the network, takes turns with the
rem other jobs, and, once, applies the battery and missed-run settings to the three schedules (install_schedules.ps1).
rem jobs.py writes the start and done lines and every step's output into logs\tasks.log itself (2026-10-24), a line
rem at a time, so this file does not redirect: a long wait never locks the log against the other jobs.
cd /d "%~dp0.."
set "PY=%USERPROFILE%\Python313\python.exe"
if not exist "%PY%" goto nopython
"%PY%" jobs.py hourly
exit /b %errorlevel%
:nopython
if not exist logs mkdir logs
echo ===== no-time hourly >> logs\tasks.log
echo hourly could not start: Python not found at %PY% >> logs\tasks.log
echo ===== no-time hourly done (exit 9009) >> logs\tasks.log
exit /b 9009
