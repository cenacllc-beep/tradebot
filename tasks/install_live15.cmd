@echo off
rem Registers "Tradebot\15-minute paper bets" in Windows Task Scheduler (research/PLAN15F.md). Double-click it once.
rem It runs research\live15.py with no window every 15 minutes (at :01, :16, :31 and :46) while you are signed in, on
rem battery too, never two at once, at most 14 minutes a run, and never wakes the PC (a missed window is skipped). Paper only: it
rem places no orders. To stop it for good, double-click tasks\remove_live15.cmd. Safe to run again.
setlocal
set "D=%~dp0"
if not exist "%D%..\logs" mkdir "%D%..\logs"
powershell -NoProfile -ExecutionPolicy Bypass -File "%D%install_live15.ps1" > "%D%..\logs\live15_install.txt" 2>&1
set "RC=%errorlevel%"
type "%D%..\logs\live15_install.txt"
echo.
if "%RC%"=="0" (echo Done. The first paper run starts at the next quarter hour plus one minute.) else (echo FAILED: see the lines above. Nothing else was changed.)
pause
exit /b %RC%
