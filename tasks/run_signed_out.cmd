@echo off
rem Lets the three Tradebot schedules run whether or not you are signed in (tasks\run_signed_out.ps1, 2026-10-29).
rem Windows asks for administrator permission: answer Yes. No password is asked for or stored, the jobs keep their
rem normal (not administrator) rights, and nothing else changes. Places no orders.
rem Undo: in PowerShell, from the tradebot folder: .\tasks\run_signed_out.cmd undo
setlocal
set "D=%~dp0"
set "U="
if /i "%~1"=="undo" set "U=,'-Undo'"
rem Windows PowerShell by its full path, so a stray powershell.exe in this folder is never the one Windows asks about
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
rem the last result is removed first, so the window below never shows an old one as if it were new
del "%D%..\logs\signed_out.txt" 2>nul
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PS%' -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"%D%run_signed_out.ps1\"'%U%"
if errorlevel 1 echo Windows did not start it (the permission prompt was refused or closed). Nothing changed.
echo.
if exist "%D%..\logs\signed_out.txt" (type "%D%..\logs\signed_out.txt") else (echo No result was written: nothing was changed, or the change could not be confirmed. Run it again.)
echo.
pause
exit /b 0
