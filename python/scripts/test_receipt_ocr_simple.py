#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシートOCR簡易テストスクリプト（対話型）

画像ファイルを選択してOCRを実行する簡易版
"""
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parents[1]
# desktopディレクトリの親（pythonディレクトリ）をパスに追加
sys.path.insert(0, str(ROOT_DIR))

def main():
    """メイン関数（対話型）"""
    try:
        print("=" * 60)
        print("レシートOCR簡易テスト")
        print("=" * 60)
        print()
        
        # 画像ファイルパスの入力
        image_path = input("レシート画像ファイルのパスを入力してください: ").strip().strip('"')
        
        if not image_path:
            print("❌ エラー: 画像ファイルパスが入力されませんでした")
            input("\nEnterキーを押して終了してください...")
            return 1
        
        image_path = Path(image_path)
        
        if not image_path.exists():
            print(f"❌ エラー: 画像ファイルが見つかりません: {image_path}")
            print(f"   絶対パス: {image_path.resolve()}")
            input("\nEnterキーを押して終了してください...")
            return 1
        
        print(f"\n画像ファイル: {image_path}")
        print(f"ファイルサイズ: {image_path.stat().st_size / 1024:.2f} KB")
        print()
        
        try:
            from desktop.services.ocr_service import OCRService
            from desktop.services.receipt_service import ReceiptService
            
            print("OCR実行中...")
            ocr_service = OCRService()
            receipt_service = ReceiptService()
            
            # OCR実行
            ocr_result = ocr_service.extract_text(image_path, use_preprocessing=True)
            ocr_text = ocr_result.get('text', '')
            
            print("\n" + "=" * 60)
            print("OCR抽出テキスト")
            print("=" * 60)
            print(ocr_text)
            print()
            
            # レシート情報抽出
            parsed = receipt_service.parse_receipt_text(ocr_text)
            
            print("=" * 60)
            print("抽出されたレシート情報")
            print("=" * 60)
            print(f"日付: {parsed.purchase_date or '（抽出できませんでした）'}")
            print(f"店舗名: {parsed.store_name_raw or '（抽出できませんでした）'}")
            print(f"電話番号: {parsed.phone_number or '（抽出できませんでした）'}")
            print(f"小計: {parsed.subtotal or '（抽出できませんでした）'}円")
            print(f"税: {parsed.tax or '（抽出できませんでした）'}円")
            print(f"値引: {parsed.discount_amount or '（抽出できませんでした）'}円")
            print(f"合計: {parsed.total_amount or '（抽出できませんでした）'}円")
            print(f"支払額: {parsed.paid_amount or '（抽出できませんでした）'}円")
            print(f"点数: {parsed.items_count or '（抽出できませんでした）'}点")
            print()
            
            print("✅ OCRテスト完了")
            input("\nEnterキーを押して終了してください...")
            return 0
        
        except KeyboardInterrupt:
            print("\n\n⚠️  ユーザーによって中断されました")
            input("\nEnterキーを押して終了してください...")
            return 1
        except Exception as e:
            print(f"\n❌ エラーが発生しました: {e}")
            print("\n" + "=" * 60)
            print("詳細なエラー情報:")
            print("=" * 60)
            import traceback
            traceback.print_exc()
            print("=" * 60)
            input("\nEnterキーを押して終了してください...")
            return 1
    
    except KeyboardInterrupt:
        print("\n\n⚠️  ユーザーによって中断されました")
        input("\nEnterキーを押して終了してください...")
        return 1
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        print("\n" + "=" * 60)
        print("詳細なエラー情報:")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        print("=" * 60)
        input("\nEnterキーを押して終了してください...")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        input("\nEnterキーを押して終了してください...")
        sys.exit(1)

