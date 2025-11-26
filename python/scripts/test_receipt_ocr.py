#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシートOCRテストスクリプト

実際のレシート画像を読み込んでOCRを実行し、結果を表示する

使用方法:
    python scripts/test_receipt_ocr.py <画像ファイルパス>
    
例:
    python scripts/test_receipt_ocr.py "D:\receipts\receipt_001.jpg"
    python scripts/test_receipt_ocr.py "receipt.png"
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parents[1]
# desktopディレクトリの親（pythonディレクトリ）をパスに追加
sys.path.insert(0, str(ROOT_DIR))

def test_receipt_ocr(image_path: str):
    """レシート画像のOCRテスト"""
    try:
        image_path = Path(image_path)
        
        if not image_path.exists():
            print(f"❌ エラー: 画像ファイルが見つかりません: {image_path}")
            print(f"   絶対パス: {image_path.resolve()}")
            return 1
    
    print("=" * 60)
    print("レシートOCRテスト")
    print("=" * 60)
    print(f"画像ファイル: {image_path}")
    print(f"ファイルサイズ: {image_path.stat().st_size / 1024:.2f} KB")
    print()
    
    try:
        # OCRServiceをインポート
        from desktop.services.ocr_service import OCRService
        from desktop.services.receipt_service import ReceiptService
        
        print("OCRServiceを初期化中...")
        ocr_service = OCRService()
        
        print("ReceiptServiceを初期化中...")
        receipt_service = ReceiptService()
        
        print("\n" + "-" * 60)
        print("OCR実行中...")
        print("-" * 60)
        
        # OCR実行
        ocr_result = ocr_service.extract_text(image_path, use_preprocessing=True)
        
        print(f"✅ OCR完了")
        print(f"プロバイダ: {ocr_result.get('provider', 'unknown')}")
        print(f"信頼度: {ocr_result.get('confidence', 'N/A')}")
        print()
        
        # OCRテキスト表示
        ocr_text = ocr_result.get('text', '')
        print("=" * 60)
        print("OCR抽出テキスト")
        print("=" * 60)
        print(ocr_text)
        print()
        
        # レシート情報の抽出
        print("=" * 60)
        print("レシート情報抽出")
        print("=" * 60)
        
        parsed = receipt_service.parse_receipt_text(ocr_text)
        
        print(f"日付: {parsed.purchase_date or '（抽出できませんでした）'}")
        print(f"店舗名（生）: {parsed.store_name_raw or '（抽出できませんでした）'}")
        print(f"電話番号: {parsed.phone_number or '（抽出できませんでした）'}")
        print(f"小計: {parsed.subtotal or '（抽出できませんでした）'}円")
        print(f"税: {parsed.tax or '（抽出できませんでした）'}円")
        print(f"値引: {parsed.discount_amount or '（抽出できませんでした）'}円")
        print(f"合計: {parsed.total_amount or '（抽出できませんでした）'}円")
        print(f"支払額: {parsed.paid_amount or '（抽出できませんでした）'}円")
        print(f"点数: {parsed.items_count or '（抽出できませんでした）'}点")
        print()
        
        # 完全な処理（画像保存→OCR→抽出→DB保存）
        print("=" * 60)
        print("完全処理テスト（画像保存→OCR→抽出→DB保存）")
        print("=" * 60)
        
        result = receipt_service.process_receipt(image_path)
        
        print(f"✅ 処理完了")
        print(f"保存された画像パス: {result.get('file_path')}")
        print(f"レシートID: {result.get('id')}")
        print(f"日付: {result.get('purchase_date')}")
        print(f"店舗名: {result.get('store_name_raw')}")
        print(f"電話番号: {result.get('phone_number')}")
        print(f"合計: {result.get('total_amount')}円")
        print(f"点数: {result.get('items_count')}点")
        print()
        
        print("=" * 60)
        print("✅ すべてのテストが成功しました！")
        print("=" * 60)
        
        return 0
        
    except ImportError as e:
        print(f"\n❌ インポートエラー: {e}")
        print("\n" + "=" * 60)
        print("解決方法:")
        print("=" * 60)
        print("1. 必要なパッケージがインストールされているか確認してください")
        print("   pip install pytesseract Pillow")
        print("2. Tesseract OCRがインストールされているか確認してください")
        print("   https://github.com/UB-Mannheim/tesseract/wiki")
        print("3. 環境変数PATHにTesseractが登録されているか確認してください")
        import traceback
        traceback.print_exc()
        return 1
        
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        print("\n" + "=" * 60)
        print("詳細なエラー情報:")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="レシート画像のOCRテスト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python scripts/test_receipt_ocr.py "D:\\receipts\\receipt_001.jpg"
  python scripts/test_receipt_ocr.py receipt.png
  python scripts/test_receipt_ocr.py "C:\\Users\\User\\Desktop\\レシート.jpg"
        """
    )
    
    parser.add_argument(
        "image_path",
        help="レシート画像ファイルのパス"
    )
    
    parser.add_argument(
        "--no-preprocessing",
        action="store_true",
        help="画像前処理をスキップ（デフォルト: 前処理あり）"
    )
    
    args = parser.parse_args()
    
    exit_code = test_receipt_ocr(args.image_path)
    
    # エラー時は一時停止
    if exit_code != 0:
        input("\nEnterキーを押して終了してください...")
    
    return exit_code

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  ユーザーによって中断されました")
        input("\nEnterキーを押して終了してください...")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        input("\nEnterキーを押して終了してください...")
        sys.exit(1)

