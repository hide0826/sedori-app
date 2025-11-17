@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
REM Google Cloud Vision API Test Batch File
REM This batch file is designed to work with drag-and-drop execution
REM Ensure window stays open even on errors

REM Debug: Show current directory and arguments
echo [DEBUG] Current directory: %CD%
echo [DEBUG] Script path: %~dp0
echo [DEBUG] All arguments: %*
echo [DEBUG] First argument (raw): %1
echo [DEBUG] First argument (expanded): %~1
echo.

REM Check arguments FIRST before changing directory
if "%~1"=="" (
    echo ============================================================
    echo Google Cloud Vision API Test
    echo ============================================================
    echo.
    echo [ERROR] No image file specified
    echo.
    echo Usage: Drag and drop an image file onto this file,
    echo or specify image file path on command line.
    echo.
    echo Example: test_gcv_ocr.bat "D:\receipts\receipt.jpg"
    echo.
    echo [DEBUG] If you dragged and dropped a file, the path may not have been passed correctly.
    echo [DEBUG] Try right-clicking the file and selecting "Open with" -^> this batch file.
    echo.
    echo [DEBUG] Press any key to close this window...
    pause >nul 2>&1
    if errorlevel 1 (
        timeout /t 5 >nul 2>&1
    )
    pause
    exit /b 1
)

REM Store the image path BEFORE changing directory
set "DRAGGED_FILE=%~f1"
echo [DEBUG] Stored image path: %DRAGGED_FILE%
echo.

REM Change to script directory
cd /d "%~dp0.."
if errorlevel 1 (
    echo [ERROR] Failed to change directory
    echo [DEBUG] Press any key to close this window...
    pause >nul 2>&1
    if errorlevel 1 (
        timeout /t 5 >nul 2>&1
    )
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
    echo [DEBUG] Press any key to close this window...
    pause >nul 2>&1
    if errorlevel 1 (
        timeout /t 5 >nul 2>&1
    )
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
    echo [DEBUG] Press any key to close this window...
    pause >nul 2>&1
    if errorlevel 1 (
        timeout /t 5 >nul 2>&1
    )
    pause
    exit /b 1
)
echo [DEBUG] Script file found
echo.

REM Check if image file exists (use the stored path)
if not exist "%DRAGGED_FILE%" (
    echo [ERROR] Image file not found
    echo [DEBUG] Specified path: %DRAGGED_FILE%
    echo.
    echo [TROUBLESHOOTING]
    echo 1. Make sure the file path does not contain special characters
    echo 2. Try copying the file to a path without spaces or Japanese characters
    echo 3. Check that the file exists and is accessible
    echo.
    echo [DEBUG] Press any key to close this window...
    pause >nul 2>&1
    if errorlevel 1 (
        timeout /t 5 >nul 2>&1
    )
    pause
    exit /b 1
)
echo [DEBUG] Image file found: %DRAGGED_FILE%
echo.

echo ============================================================
echo Running Python script...
echo ============================================================
echo.

REM Run Python script (include error output)
REM Use the stored path from drag-and-drop
echo [DEBUG] Running Python script with image: %DRAGGED_FILE%
python "scripts\test_gcv_ocr.py" "%DRAGGED_FILE%" 2>&1
set PYTHON_EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
if %PYTHON_EXIT_CODE% EQU 0 (
    echo [SUCCESS] Python script completed successfully
) else (
    echo [ERROR] Python script exited with code %PYTHON_EXIT_CODE%
    echo Please check the error messages above
    echo.
    echo If you see encoding errors, try:
    echo 1. Ensure the image file path does not contain special characters
    echo 2. Check that Python can access the file
    echo 3. Verify OCR service is properly configured
)
echo ============================================================

REM Always pause to show results
REM This ensures the window stays open even when launched via drag-and-drop
echo.
echo ============================================================
echo Press any key to exit...
echo ============================================================
REM Use pause without redirection - this works in drag-and-drop scenarios
pause

endlocal
exit /b %PYTHON_EXIT_CODE%
