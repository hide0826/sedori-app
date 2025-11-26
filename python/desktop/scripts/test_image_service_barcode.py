#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageServiceのバーコード読み取り機能テスト"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

print("=" * 60)
print("ImageServiceバーコード読み取り機能テスト")
print("=" * 60)

# 1. ImageServiceのインポート
print("\n1. ImageServiceのインポート...")
try:
    from services.image_service import ImageService
    print("   ✓ ImageServiceインポート成功")
except Exception as e:
    print(f"   ✗ ImageServiceインポート失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 2. ImageServiceのインスタンス作成
print("\n2. ImageServiceのインスタンス作成...")
try:
    service = ImageService()
    print("   ✓ ImageService作成成功")
except Exception as e:
    print(f"   ✗ ImageService作成失敗: {e}")
    sys.exit(1)

# 3. バーコードリーダーの利用可能性確認
print("\n3. バーコードリーダーの利用可能性確認...")
is_available = service.is_barcode_reader_available()
if is_available:
    print("   ✓ バーコードリーダーが利用可能です")
    
    # どのライブラリが利用可能か確認
    try:
        from pyzxing import BarCodeReader
        print("     - pyzxing (ZXing): 利用可能")
    except:
        print("     - pyzxing (ZXing): 利用不可")
    
    try:
        from pyzbar import pyzbar
        print("     - pyzbar (ZBar): 利用可能")
    except:
        print("     - pyzbar (ZBar): 利用不可")
else:
    print("   ✗ バーコードリーダーが利用できません")
    print("   インストール方法:")
    print("   - pyzxing: pip install pyzxing (Java JRE必要)")
    print("   - pyzbar: pip install pyzbar (zbarライブラリ必要)")

# 4. read_barcode_from_imageメソッドの存在確認
print("\n4. read_barcode_from_imageメソッドの確認...")
if hasattr(service, 'read_barcode_from_image'):
    print("   ✓ read_barcode_from_imageメソッドが存在します")
else:
    print("   ✗ read_barcode_from_imageメソッドが見つかりません")

print("\n" + "=" * 60)
if is_available:
    print("✓ ImageServiceのバーコード読み取り機能は準備完了です！")
    print("=" * 60)
    print("\n次のステップ:")
    print("- 実際のバーコード画像でテストしてください")
    print("- 画像管理タブから「バーコード読み取り」ボタンでテストできます")
else:
    print("✗ バーコードリーダーが利用できません")
    print("=" * 60)
    print("\n解決方法:")
    print("1. Java JRE 8以上をインストール")
    print("2. pip install pyzxing")



