@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
REM Google Cloud Vision API動作確認用バッチファイル（改良版）

REM 現在のディレクトリを保存
set "ORIGINAL_DIR=%CD%"

REM スクリプトのディレクトリに移動
cd /d "%~dp0.."

REM 引数チェック
if "%~1"=="" (
    echo ============================================================
    echo Google Cloud Vision API 動作確認
    echo ============================================================
    echo.
    echo 使用方法: このファイルに画像ファイルをドラッグ^&ドロップするか、
    echo またはコマンドラインで画像ファイルパスを指定してください。
    echo.
    echo 例: test_gcv_ocr_fixed.bat "D:\receipts\receipt.jpg"
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo Google Cloud Vision API 動作確認
echo ============================================================
echo.
echo 画像ファイル: %*
echo.
echo Pythonスクリプトを実行中...
echo.

REM Pythonスクリプトを実行（エラーをキャッチ）
python scripts\test_gcv_ocr.py %* 2>&1
set PYTHON_EXIT_CODE=!ERRORLEVEL!

echo.
echo ============================================================
if !PYTHON_EXIT_CODE! NEQ 0 (
    echo [ERROR] エラーが発生しました（終了コード: !PYTHON_EXIT_CODE!）
    echo ============================================================
    echo 上記のメッセージを確認してください。
    echo.
    echo よくある原因:
    echo 1. Pythonがインストールされていない
    echo 2. google-cloud-visionパッケージがインストールされていない
    echo 3. GCV認証情報が設定されていない
    echo 4. 画像ファイルのパスが正しくない
) else (
    echo [OK] テスト完了
    echo ============================================================
)

REM 必ず一時停止（エラーコードに関係なく）
echo.
echo ============================================================
echo Enterキーを押して終了してください...
echo ============================================================
pause >nul
if errorlevel 1 pause

REM 元のディレクトリに戻る
cd /d "%ORIGINAL_DIR%"
endlocal
exit /b %PYTHON_EXIT_CODE%

