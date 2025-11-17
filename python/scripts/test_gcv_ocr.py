#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Cloud Vision API動作確認スクリプト

GCVが正しく設定されているか、実際の画像でテストする
"""
from __future__ import annotations

import sys
import io
import argparse
from pathlib import Path

# WindowsのコマンドプロンプトでUTF-8出力を有効化
if sys.platform == 'win32':
    try:
        # バッファが存在する場合のみラップ
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        # エラーが発生しても続行
        pass

# プロジェクトルートをパスに追加
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

def test_gcv_ocr(image_path: str):
    """GCV OCRのテスト"""
    try:
        # パスを正規化（クォートを除去）
        image_path_str = str(image_path).strip().strip('"').strip("'")
        image_path = Path(image_path_str)
        
        if not image_path.exists():
            print(f"[ERROR] 画像ファイルが見つかりません")
            print(f"        入力パス: {image_path_str}")
            try:
                abs_path = image_path.resolve()
                print(f"        絶対パス: {abs_path}")
            except Exception:
                pass
            return 1
    except Exception as e:
        print(f"[ERROR] パス解析エラー: {e}")
        print(f"        入力: {image_path}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("=" * 60)
    print("Google Cloud Vision API 動作確認")
    print("=" * 60)
    print(f"画像ファイル: {image_path}")
    print(f"ファイルサイズ: {image_path.stat().st_size / 1024:.2f} KB")
    print()
    
    try:
        print("モジュールをインポート中...")
        from desktop.services.ocr_service import OCRService
        print("[OK] OCRServiceのインポートに成功しました")
        
        print("OCRServiceを初期化中...")
        try:
            ocr_service = OCRService()
            print("[OK] OCRServiceの初期化に成功しました")
        except Exception as init_error:
            print(f"[ERROR] OCRServiceの初期化に失敗しました: {init_error}")
            import traceback
            traceback.print_exc()
            return 1
        
        # GCVが利用可能か確認
        if not OCRService.is_gcv_available():
            print("[ERROR] Google Cloud Vision APIが利用できません")
            print("        pip install google-cloud-vision を実行してください")
            return 1
        
        print("[OK] google-cloud-visionパッケージはインストールされています")
        
        # GCVクライアントが初期化されているか確認
        if not ocr_service.gcv_client:
            print("[WARNING] GCVクライアントが初期化されていません")
            print("          設定画面でGCV認証情報(JSON)を設定してください")
            print()
            print("          設定方法:")
            print("          1. デスクトップアプリを起動")
            print("          2. 「設定」タブ → 「詳細設定」 → 「OCR設定」")
            print("          3. 「GCV認証情報(JSON)」にJSONファイルのパスを指定")
            return 1
        
        print("[OK] GCVクライアントが初期化されています")
        print()
        
        print("-" * 60)
        print("OCR実行中（Google Cloud Vision APIを使用）...")
        print("-" * 60)
        
        # OCR実行
        try:
            print("画像を読み込み中...")
            ocr_result = ocr_service.extract_text(image_path, use_preprocessing=True)
            print("[OK] OCR実行完了")
        except Exception as ocr_error:
            print(f"[ERROR] OCR実行中にエラーが発生しました: {ocr_error}")
            print("\n詳細なエラー情報:")
            import traceback
            traceback.print_exc()
            return 1
        
        provider = ocr_result.get('provider', 'unknown')
        confidence = ocr_result.get('confidence')
        text = ocr_result.get('text', '')
        
        print(f"[OK] OCR完了")
        print(f"プロバイダ: {provider}")
        if confidence is not None:
            print(f"信頼度: {confidence:.2f}")
        print()
        
        if provider == 'gcv':
            print("[SUCCESS] Google Cloud Vision APIが正常に動作しています！")
        elif provider == 'tesseract':
            print("[WARNING] Tesseract OCRが使用されました（GCVが失敗した可能性）")
        else:
            print(f"[WARNING] 予期しないプロバイダ: {provider}")
        
        print()
        print("=" * 60)
        print("OCR抽出テキスト（最初の500文字）")
        print("=" * 60)
        print(text[:500])
        if len(text) > 500:
            print(f"\n... (残り {len(text) - 500} 文字)")
        print()
        
        # レシート情報の抽出テスト
        try:
            from desktop.services.receipt_service import ReceiptService
            receipt_service = ReceiptService()
            parsed = receipt_service.parse_receipt_text(text)
            
            print("=" * 60)
            print("レシート情報抽出結果")
            print("=" * 60)
            print(f"日付: {parsed.purchase_date or '（抽出できませんでした）'}")
            print(f"店舗名: {parsed.store_name_raw or '（抽出できませんでした）'}")
            print(f"電話番号: {parsed.phone_number or '（抽出できませんでした）'}")
            print(f"合計: {parsed.total_amount or '（抽出できませんでした）'}円")
            print(f"点数: {parsed.items_count or '（抽出できませんでした）'}点")
            print()
        except Exception as e:
            print(f"[WARNING] レシート情報抽出でエラー: {e}")
        
        print("=" * 60)
        print("[OK] テスト完了")
        print("=" * 60)
        
        return 0
        
    except ImportError as e:
        print(f"[ERROR] インポートエラー: {e}")
        print("\n解決方法:")
        print("1. pip install google-cloud-vision を実行")
        print("2. 必要なパッケージがインストールされているか確認")
        return 1
        
    except Exception as e:
        print(f"[ERROR] エラーが発生しました: {e}")
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
        description="Google Cloud Vision API動作確認",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python scripts/test_gcv_ocr.py "D:\\receipts\\receipt.jpg"
  python scripts/test_gcv_ocr.py receipt.png
        """
    )
    
    parser.add_argument(
        "image_path",
        help="テスト用の画像ファイルのパス"
    )
    
    try:
        args = parser.parse_args()
    except SystemExit:
        # --help などの場合は正常終了
        return 0
    except Exception as e:
        print(f"[ERROR] 引数解析エラー: {e}")
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        return 1
    
    try:
        exit_code = test_gcv_ocr(args.image_path)
        
        if exit_code != 0:
            print("\n" + "=" * 60)
            print("エラーが発生しました")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("テスト完了")
            print("=" * 60)
        
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        # ドラッグ&ドロップ実行時は標準入力が閉じられている可能性があるため
        
        return exit_code
    except KeyboardInterrupt:
        print("\n\n[WARNING] ユーザーによって中断されました")
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        return 1
    except Exception as e:
        print(f"\n[ERROR] 予期しないエラー: {e}")
        print("\n" + "=" * 60)
        print("詳細なエラー情報:")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        print("=" * 60)
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[WARNING] ユーザーによって中断されました")
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        # バッチファイル側で待機処理を行うため、ここでは待機しない
        sys.exit(1)

