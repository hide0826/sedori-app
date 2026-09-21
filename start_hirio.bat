@echo off
cd /d "%~dp0"
echo HIRIO を起動します...
".venv\Scripts\python.exe" python\desktop\main.py
if errorlevel 1 (
  echo.
  echo 起動に失敗しました。python\desktop\desktop_error.log を確認してください。
  pause
)
