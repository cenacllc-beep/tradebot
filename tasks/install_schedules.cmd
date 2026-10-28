@echo off
rem Registers the three Tradebot schedules in Windows Task Scheduler (tasks\README.md). Double-click it once.
rem Safe to run again: /F replaces an existing schedule with the same name. Places no orders.
rem Since 2026-10-23 it then runs install_schedules.ps1, which lets the runs start on battery and makes up a run that
rem was missed while the PC was off or asleep (Windows' defaults for schedules made by schtasks do neither). If that
rem step fails, the schedules still exist with Windows' defaults and this window says so.
setlocal
set "D=%~dp0"
if not exist "%D%..\logs" mkdir "%D%..\logs"
set "FAIL=0"
rem /Create resets each task to Windows' defaults, so the hourly job must apply the settings again.
del "%D%..\logs\schedules_applied.txt" 2>nul
schtasks /Create /F /TN "Tradebot\Evening scan" /SC DAILY /ST 20:55 /TR "\"%D%evening.cmd\""
if errorlevel 1 set "FAIL=1"
schtasks /Create /F /TN "Tradebot\Afternoon settle" /SC DAILY /ST 14:51 /TR "\"%D%settle.cmd\""
if errorlevel 1 set "FAIL=1"
schtasks /Create /F /TN "Tradebot\Hourly research" /SC HOURLY /ST 00:20 /TR "\"%D%hourly.cmd\""
if errorlevel 1 set "FAIL=1"
if "%FAIL%"=="1" goto createfailed
powershell -NoProfile -ExecutionPolicy Bypass -File "%D%install_schedules.ps1" > "%D%..\logs\schedules_settings.txt" 2>&1
set "PSRC=%errorlevel%"
schtasks /Query /TN "Tradebot\Evening scan" > "%D%..\logs\schedules.txt" 2>&1
schtasks /Query /TN "Tradebot\Afternoon settle" >> "%D%..\logs\schedules.txt" 2>&1
schtasks /Query /TN "Tradebot\Hourly research" >> "%D%..\logs\schedules.txt" 2>&1
type "%D%..\logs\schedules_settings.txt" >> "%D%..\logs\schedules.txt"
type "%D%..\logs\schedules.txt"
echo.
if "%PSRC%"=="0" goto allok
echo WARNING: the three schedules exist, but the battery and missed-run settings could not be set.
echo Until they are, Windows skips a run while the laptop is unplugged, or while it was off or asleep.
echo The lines above say why. Keep the laptop plugged in at 8:55 PM and 2:51 PM meanwhile.
goto finish
:allok
echo All three schedules are set: they run on battery too, and a run missed while the PC was off is made up.
echo The 8:55 PM scan also wakes the PC if the power plan allows wake timers (see the INFO lines above).
:finish
echo If the 8:55 PM run was missed tonight, double-click evening.cmd in this folder between 8:50 PM and 1:00 AM.
pause
exit /b 0
:createfailed
echo.
echo FAILED: Windows did not create all three schedules. The messages above say why.
echo If one says "Access is denied", right-click install_schedules.cmd and choose "Run as administrator".
echo That works only if your own Windows account is an administrator: schedules made under another account
echo run only while that account is signed in.
pause
exit /b 1
