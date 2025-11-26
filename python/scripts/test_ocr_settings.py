#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR設定テストスクリプト

設定ウィジェットのOCR設定テスト機能を独立してテストするためのスクリプト
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "python" / "desktop"))

def test_ocr_service_import():
    """OCRServiceのインポートテスト"""
    print("=" * 60)
    print("OCR設定テスト")
    print("=" * 60)
    
    try:
        from services.ocr_service import OCRService
        print("✅ OCRServiceのインポートに成功しました")
        return True
    except ImportError as e:
        print(f"❌ OCRServiceのインポートに失敗しました: {e}")
        try:
            from desktop.services.ocr_service import OCRService
            print("✅ フォールバックパスでインポート成功")
            return True
        except ImportError as e2:
            print(f"❌ フォールバックパスでもインポート失敗: {e2}")
            return False

def test_ocr_service_initialization():
    """OCRServiceの初期化テスト"""
    print("\n" + "=" * 60)
    print("OCRService初期化テスト")
    print("=" * 60)
    
    try:
        from services.ocr_service import OCRService
    except ImportError:
        from desktop.services.ocr_service import OCRService
    
    try:
        # デフォルト設定で初期化
        ocr_service = OCRService()
        print("✅ OCRServiceの初期化に成功しました（デフォルト設定）")
        
        # Tesseractが利用可能か確認
        if OCRService.is_tesseract_available():
            print("✅ Tesseract OCRは利用可能です")
        else:
            print("⚠️  Tesseract OCRは利用できません（pytesseractがインストールされていない可能性）")
        
        # GCVが利用可能か確認
        if OCRService.is_gcv_available():
            print("✅ Google Cloud Vision APIは利用可能です")
        else:
            print("ℹ️  Google Cloud Vision APIは利用できません（オプション）")
        
        return True
    except Exception as e:
        print(f"❌ OCRServiceの初期化に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_qsettings_integration():
    """QSettingsとの統合テスト"""
    print("\n" + "=" * 60)
    print("QSettings統合テスト")
    print("=" * 60)
    
    try:
        from PySide6.QtCore import QSettings
        
        settings = QSettings("HIRIO", "DesktopApp")
        
        # 設定値を読み込み
        tesseract_cmd = settings.value("ocr/tesseract_cmd", "")
        tessdata_dir = settings.value("ocr/tessdata_dir", "")
        gcv_credentials = settings.value("ocr/gcv_credentials", "")
        
        print(f"Tesseract実行ファイル: {tesseract_cmd or '（未設定）'}")
        print(f"Tessdataディレクトリ: {tessdata_dir or '（未設定）'}")
        print(f"GCV認証情報: {gcv_credentials or '（未設定）'}")
        
        # OCRServiceで設定を読み込むテスト
        from services.ocr_service import OCRService
    except ImportError:
        from desktop.services.ocr_service import OCRService
    
    try:
        ocr_service = OCRService()
        print("✅ QSettingsから設定を読み込んでOCRServiceを初期化できました")
        return True
    except Exception as e:
        print(f"❌ QSettings統合テストに失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tesseract_path():
    """Tesseractパスの確認"""
    print("\n" + "=" * 60)
    print("Tesseractパス確認")
    print("=" * 60)
    
    import pytesseract
    
    try:
        tesseract_cmd = pytesseract.pytesseract.tesseract_cmd
        print(f"Tesseract実行ファイル: {tesseract_cmd}")
        
        if Path(tesseract_cmd).exists():
            print("✅ Tesseract実行ファイルが存在します")
        else:
            print("⚠️  Tesseract実行ファイルが見つかりません")
        
        # 環境変数TESSDATA_PREFIXを確認
        tessdata_prefix = os.environ.get('TESSDATA_PREFIX')
        if tessdata_prefix:
            print(f"TESSDATA_PREFIX: {tessdata_prefix}")
            if Path(tessdata_prefix).exists():
                print("✅ TESSDATA_PREFIXディレクトリが存在します")
            else:
                print("⚠️  TESSDATA_PREFIXディレクトリが見つかりません")
        else:
            print("ℹ️  TESSDATA_PREFIXは設定されていません（デフォルトを使用）")
        
        return True
    except Exception as e:
        print(f"❌ Tesseractパス確認に失敗しました: {e}")
        return False

def main():
    """メイン関数"""
    print("\n")
    print("HIRIO OCR設定テストスクリプト")
    print("=" * 60)
    
    results = []
    
    # テスト1: インポートテスト
    results.append(("インポートテスト", test_ocr_service_import()))
    
    # テスト2: 初期化テスト
    if results[0][1]:
        results.append(("初期化テスト", test_ocr_service_initialization()))
    
    # テスト3: QSettings統合テスト
    if results[0][1]:
        results.append(("QSettings統合テスト", test_qsettings_integration()))
    
    # テスト4: Tesseractパス確認
    results.append(("Tesseractパス確認", test_tesseract_path()))
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✅ 成功" if result else "❌ 失敗"
        print(f"{test_name}: {status}")
    
    success_count = sum(1 for _, result in results if result)
    total_count = len(results)
    
    print(f"\n成功: {success_count}/{total_count}")
    
    if success_count == total_count:
        print("\n🎉 すべてのテストが成功しました！")
        return 0
    else:
        print("\n⚠️  一部のテストが失敗しました。設定を確認してください。")
        return 1

if __name__ == "__main__":
    sys.exit(main())




