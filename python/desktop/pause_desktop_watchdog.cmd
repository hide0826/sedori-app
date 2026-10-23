@echo off
REM Intentional stop: watchdog will not relaunch HIRIO desktop while this flag exists.
cd /d "%~dp0"
echo paused> "desktop.paused"
echo HIRIO desktop watchdog paused. Remove desktop.paused or run resume_desktop_watchdog.cmd to resume.
pause
