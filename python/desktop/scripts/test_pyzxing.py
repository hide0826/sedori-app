#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pyzxing動作確認スクリプト"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

print("=" * 60)
print("pyzxing動作確認テスト")
print("=" * 60)

# 1. pyzxingのインポートテスト
print("\n1. pyzxingモジュールのインポート...")
try:
    from pyzxing import BarCodeReader
    print("   ✓ pyzxingインポート成功")
    PYZXING_AVAILABLE = True
except ImportError as e:
    print(f"   ✗ pyzxingインポート失敗: {e}")
    print("   インストール方法: pip install pyzxing")
    print("   注意: Java JRE 8以上が必要です")
    PYZXING_AVAILABLE = False
    sys.exit(1)

# 2. Javaの確認
print("\n2. Java環境の確認...")
import subprocess
try:
    result = subprocess.run(['java', '-version'], 
                          capture_output=True, 
                          text=True, 
                          stderr=subprocess.STDOUT,
                          timeout=5)
    if result.returncode == 0:
        version_line = result.stdout.split('\n')[0] if result.stdout else ""
        print(f"   ✓ Javaが見つかりました: {version_line}")
    else:
        print("   ✗ Javaが見つかりません")
        print("   インストール: https://www.java.com/ja/download/")
        sys.exit(1)
except FileNotFoundError:
    print("   ✗ Javaが見つかりません")
    print("   インストール: https://www.java.com/ja/download/")
    sys.exit(1)
except Exception as e:
    print(f"   ⚠ Java確認中にエラー: {e}")

# 3. BarCodeReaderのインスタンス作成
print("\n3. BarCodeReaderのインスタンス作成...")
try:
    reader = BarCodeReader()
    print("   ✓ BarCodeReader作成成功")
except Exception as e:
    print(f"   ✗ BarCodeReader作成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 4. テスト画像での読み取り（存在する場合）
print("\n4. テスト画像での読み取り...")
test_dirs = [
    Path(__file__).parent.parent.parent / "data" / "test_images",
    Path.home() / "Pictures",
    Path.home() / "Desktop",
]

image_extensions = ['.jpg', '.jpeg', '.png']
test_images = []

for test_dir in test_dirs:
    if test_dir.exists() and test_dir.is_dir():
        for ext in image_extensions:
            test_images.extend(list(test_dir.glob(f"*{ext}")))
            test_images.extend(list(test_dir.glob(f"*{ext.upper()}")))
        if test_images:
            break

if not test_images:
    print("   テスト画像が見つかりません。スキップします。")
    print("   （実際のバーコード画像でテストしたい場合は、画像を指定してください）")
else:
    test_image = test_images[0]
    print(f"   テスト画像: {test_image}")
    try:
        results = reader.decode(str(test_image))
        if results:
            for result in results:
                print(f"   ✓ バーコードを読み取りました:")
                print(f"     フォーマット: {result.get('format', 'N/A')}")
                print(f"     データ: {result.get('raw', 'N/A')}")
        else:
            print("   バーコードが見つかりませんでした")
    except Exception as e:
        print(f"   ✗ 読み取りエラー: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)
if PYZXING_AVAILABLE:
    print("✓ pyzxingは正常に動作しています！")
    print("=" * 60)
else:
    print("✗ pyzxingの動作確認に失敗しました")
    print("=" * 60)



