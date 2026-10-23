@echo off
REM Resume watchdog auto-relaunch for HIRIO desktop.
cd /d "%~dp0"
if exist "desktop.paused" del /f /q "desktop.paused"
echo HIRIO desktop watchdog resumed.
pause
