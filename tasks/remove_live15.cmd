@echo off
rem Removes the 15-minute PAPER bets job (tasks\install_live15.cmd). Its ledger, research\data\live15.db, is kept.
schtasks /Delete /F /TN "Tradebot\15-minute paper bets"
pause
