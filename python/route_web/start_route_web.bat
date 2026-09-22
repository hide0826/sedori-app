@echo off
cd /d "%~dp0\.."
if exist "%~dp0\..\..\.venv\Scripts\python.exe" (
  "%~dp0\..\..\.venv\Scripts\python.exe" -m route_web
) else (
  py -3 -m route_web
)
