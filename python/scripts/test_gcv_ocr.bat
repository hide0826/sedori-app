@echo off
chcp 65001 >nul 2>&1
REM Google Cloud Vision API Test Batch File

REM Debug: Show current directory
echo [DEBUG] Current directory: %CD%
echo [DEBUG] Script path: %~dp0
echo.

REM Change to script directory
cd /d "%~dp0.."
if errorlevel 1 (
    echo [ERROR] Failed to change directory
    pause
    exit /b 1
)
echo [DEBUG] Changed to: %CD%
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo.
    echo Solution:
    echo 1. Install Python
    echo 2. Add Python to PATH
    echo.
    pause
    exit /b 1
)
echo [DEBUG] Python found
python --version
echo.

REM Check if script file exists
if not exist "scripts\test_gcv_ocr.py" (
    echo [ERROR] Script file not found: scripts\test_gcv_ocr.py
    echo [DEBUG] Current directory: %CD%
    echo.
    pause
    exit /b 1
)
echo [DEBUG] Script file found
echo.

REM Check arguments
if "%~1"=="" (
    echo ============================================================
    echo Google Cloud Vision API Test
    echo ============================================================
    echo.
    echo Usage: Drag and drop an image file onto this file,
    echo or specify image file path on command line.
    echo.
    echo Example: test_gcv_ocr.bat "D:\receipts\receipt.jpg"
    echo.
    pause
    exit /b 1
)

echo [DEBUG] Arguments: %*
echo [DEBUG] Image file: %~1
echo [DEBUG] Full path: %~f1
echo.

REM Check if image file exists (use absolute path)
if not exist "%~f1" (
    echo [ERROR] Image file not found
    echo [DEBUG] Specified path: %~1
    echo [DEBUG] Full path: %~f1
    echo.
    pause
    exit /b 1
)
echo [DEBUG] Image file found
echo.

echo ============================================================
echo Running Python script...
echo ============================================================
echo.

REM Run Python script (include error output)
REM Quote argument properly
python scripts\test_gcv_ocr.py "%~1" 2>&1
set PYTHON_EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
echo [DEBUG] Python script exit code: %PYTHON_EXIT_CODE%
echo ============================================================

REM If error occurred
if %PYTHON_EXIT_CODE% NEQ 0 (
    echo.
    echo [ERROR] An error occurred
    echo Please check the messages above
    echo.
)

REM Always pause (backup in case Python script's input() doesn't work)
echo.
echo ============================================================
echo Press Enter to exit...
echo ============================================================
pause >nul
if errorlevel 1 pause

exit /b %PYTHON_EXIT_CODE%
