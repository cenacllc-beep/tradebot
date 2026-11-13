@echo off
rem 15-minute PAPER bets (research/PLAN15F.md), one run by hand: settles finished paper bets, then follows the current
rem Kalshi BTC and ETH 15-minute windows to minute 10 and exits. The scheduled job (tasks\install_live15.cmd) runs the
rem same command with no window. Paper only: it places no orders. Its log: logs\live15.log.
cd /d "%~dp0.."
set "PY=%USERPROFILE%\Python313\python.exe"
if not exist "%PY%" (echo Python not found at %PY% & exit /b 9009)
"%PY%" research\live15.py tick
exit /b %errorlevel%
