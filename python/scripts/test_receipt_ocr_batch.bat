@echo off
chcp 65001 >nul
REM レシートOCRテスト用バッチファイル
REM 使用方法: このファイルに画像ファイルをドラッグ&ドロップ

cd /d "%~dp0.."

if "%~1"=="" (
    echo 使用方法: このファイルに画像ファイルをドラッグ^&ドロップするか、
    echo またはコマンドラインで画像ファイルパスを指定してください。
    echo.
    echo 例: test_receipt_ocr_batch.bat "D:\receipts\receipt.jpg"
    echo.
    pause
    exit /b 1
)

python scripts\test_receipt_ocr.py %*

REM エラーコードに関係なく一時停止
echo.
pause

