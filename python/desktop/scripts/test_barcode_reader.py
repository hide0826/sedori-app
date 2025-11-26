#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バーコードリーダー動作確認スクリプト

pyzbarとzbarライブラリが正しく連携できているか確認します。
"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_pyzbar_import():
    """pyzbarモジュールのインポートをテスト"""
    print("=" * 60)
    print("1. pyzbarモジュールのインポートテスト")
    print("=" * 60)
    
    try:
        import pyzbar
        print("✓ pyzbarモジュールのインポート成功")
        print(f"  バージョン: {pyzbar.__version__ if hasattr(pyzbar, '__version__') else '不明'}")
        return True
    except ImportError as e:
        print(f"✗ pyzbarモジュールのインポート失敗: {e}")
        print("  解決方法: pip install pyzbar")
        return False

def test_pyzbar_decode():
    """pyzbar.decode関数のテスト"""
    print("\n" + "=" * 60)
    print("2. pyzbar.decode関数のテスト")
    print("=" * 60)
    
    try:
        from pyzbar import pyzbar
        print("✓ pyzbar.decode関数のインポート成功")
        
        # decode関数が存在するか確認
        if hasattr(pyzbar, 'decode'):
            print("✓ pyzbar.decode関数が存在します")
            return True
        else:
            print("✗ pyzbar.decode関数が見つかりません")
            return False
    except Exception as e:
        print(f"✗ エラー: {e}")
        return False

def test_zbar_library():
    """zbarライブラリの動作テスト"""
    print("\n" + "=" * 60)
    print("3. zbarライブラリの動作テスト")
    print("=" * 60)
    
    try:
        from pyzbar import pyzbar
        from PIL import Image
        import numpy as np
        
        # 簡単なテスト画像を作成（実際にはバーコードが含まれていない）
        # これはzbarライブラリが正しくリンクされているかを確認するため
        test_image = Image.new('RGB', (100, 100), color='white')
        
        try:
            # decode関数を呼び出す（バーコードが見つからなくても正常）
            barcodes = pyzbar.decode(test_image)
            print("✓ zbarライブラリが正しくリンクされています")
            print(f"  読み取ったバーコード数: {len(barcodes)}（期待値: 0）")
            return True
        except Exception as e:
            # 特定のエラーメッセージをチェック
            error_msg = str(e)
            if "zbar" in error_msg.lower() or "dll" in error_msg.lower() or "so" in error_msg.lower():
                print(f"✗ zbarライブラリが見つかりません: {e}")
                print("  解決方法:")
                print("  - Windows: zbar-w64をダウンロードしてインストール")
                print("  - Linux: sudo apt-get install libzbar0")
                print("  - macOS: brew install zbar")
                return False
            else:
                print(f"✗ 予期しないエラー: {e}")
                return False
    except ImportError as e:
        print(f"✗ 必要なモジュールが見つかりません: {e}")
        return False
    except Exception as e:
        print(f"✗ エラー: {e}")
        return False

def test_image_service():
    """ImageServiceのバーコード読み取り機能テスト"""
    print("\n" + "=" * 60)
    print("4. ImageServiceのバーコード読み取り機能テスト")
    print("=" * 60)
    
    try:
        from services.image_service import ImageService
        
        service = ImageService()
        
        # バーコードリーダーの利用可能性を確認
        is_available = service.is_barcode_reader_available()
        
        if is_available:
            print("✓ ImageServiceのバーコードリーダーが利用可能です")
            return True
        else:
            print("✗ ImageServiceのバーコードリーダーが利用できません")
            print("  解決方法: pyzbarとzbarライブラリをインストールしてください")
            return False
    except Exception as e:
        print(f"✗ エラー: {e}")
        return False

def test_with_sample_image():
    """サンプル画像（存在する場合）でのテスト"""
    print("\n" + "=" * 60)
    print("5. サンプル画像でのテスト（オプション）")
    print("=" * 60)
    
    # テスト画像のパスを探す（実際にバーコードが含まれている画像）
    test_dirs = [
        Path(__file__).parent.parent.parent / "data" / "test_images",
        Path(__file__).parent.parent.parent.parent / "test_images",
        Path.home() / "Pictures",
        Path.home() / "Desktop",
    ]
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']
    test_images = []
    
    for test_dir in test_dirs:
        if test_dir.exists() and test_dir.is_dir():
            for ext in image_extensions:
                test_images.extend(list(test_dir.glob(f"*{ext}")))
                test_images.extend(list(test_dir.glob(f"*{ext.upper()}")))
            if test_images:
                break
    
    if not test_images:
        print("  テスト画像が見つかりません。スキップします。")
        print("  （実際のバーコード画像でテストしたい場合は、")
        print("  スクリプトに画像パスを指定してください）")
        return None
    
    try:
        from services.image_service import ImageService
        
        service = ImageService()
        
        if not service.is_barcode_reader_available():
            print("  バーコードリーダーが利用できないため、スキップします。")
            return None
        
        # 最初のテスト画像で試す
        test_image = test_images[0]
        print(f"  テスト画像: {test_image}")
        
        jan = service.read_barcode_from_image(str(test_image))
        
        if jan:
            print(f"  ✓ JANコードを読み取りました: {jan}")
            return True
        else:
            print(f"  バーコードが見つかりませんでした（画像にバーコードが含まれていない可能性があります）")
            return None
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def main():
    """メイン処理"""
    print("\n" + "=" * 60)
    print("バーコードリーダー動作確認")
    print("=" * 60)
    print()
    
    results = []
    
    # 1. pyzbarモジュールのインポート
    results.append(("pyzbarインポート", test_pyzbar_import()))
    
    # 2. pyzbar.decode関数のテスト
    if results[0][1]:
        results.append(("pyzbar.decode関数", test_pyzbar_decode()))
        
        # 3. zbarライブラリの動作テスト
        results.append(("zbarライブラリ", test_zbar_library()))
        
        # 4. ImageServiceのテスト
        results.append(("ImageService", test_image_service()))
        
        # 5. サンプル画像でのテスト（オプション）
        result = test_with_sample_image()
        if result is not None:
            results.append(("サンプル画像テスト", result))
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n合計: {passed}/{total} テスト成功")
    
    if passed == total:
        print("\n✓ すべてのテストが成功しました！")
        print("  バーコードリーダーは正常に動作しています。")
        return 0
    else:
        print("\n✗ 一部のテストが失敗しました。")
        print("  上記のエラーメッセージを確認して、必要なライブラリをインストールしてください。")
        return 1

if __name__ == "__main__":
    sys.exit(main())

