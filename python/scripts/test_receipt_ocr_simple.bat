@echo off
chcp 65001 >nul
REM レシートOCR簡易テスト用バッチファイル

cd /d "%~dp0.."
python scripts\test_receipt_ocr_simple.py

REM エラーコードに関係なく一時停止
pause




