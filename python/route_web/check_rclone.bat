@echo off
REM Check rclone for HIRIO route Drive push
chcp 65001 >nul
echo === HIRIO rclone check ===
where rclone 2>nul
if errorlevel 1 (
  echo rclone が PATH にありません。
  echo 例: winget install Rclone.Rclone
  echo または tools\rclone\rclone.exe に配置
) else (
  rclone version
)
echo.
echo config: config\rclone_route_drive.json
if exist "%~dp0..\..\config\rclone_route_drive.json" (
  echo found rclone_route_drive.json
) else (
  echo missing - copy from rclone_route_drive.example.json
)
echo.
echo Setup:
echo   1. rclone config  ^(create Google Drive remote, e.g. gdrive^)
echo   2. copy config\rclone_route_drive.example.json to rclone_route_drive.json
echo   3. set "enabled": true and "remote": "gdrive"
pause
