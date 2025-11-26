#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最終的な動作確認テスト"""
import sys
import os
from pathlib import Path

# pyzbarディレクトリをPATHに追加してみる
pyzbar_dir = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar")
if str(pyzbar_dir) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(pyzbar_dir) + os.pathsep + os.environ.get("PATH", "")
    print(f"✓ PATHにpyzbarディレクトリを追加: {pyzbar_dir}")

print("=" * 60)
print("最終的な動作確認テスト")
print("=" * 60)

try:
    print("\n1. pyzbarモジュールのインポート...")
    from pyzbar import pyzbar
    print("   ✓ インポート成功")
except Exception as e:
    print(f"   ✗ インポート失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("\n2. PIL Imageのインポート...")
    from PIL import Image
    print("   ✓ インポート成功")
except Exception as e:
    print(f"   ✗ インポート失敗: {e}")
    sys.exit(1)

try:
    print("\n3. テスト画像の作成...")
    img = Image.new('RGB', (100, 100), color='white')
    print("   ✓ 作成成功")
except Exception as e:
    print(f"   ✗ 作成失敗: {e}")
    sys.exit(1)

try:
    print("\n4. バーコード読み取りテスト...")
    result = pyzbar.decode(img)
    print(f"   ✓ decode実行成功！")
    print(f"   読み取ったバーコード数: {len(result)}（期待値: 0）")
    print("\n" + "=" * 60)
    print("✓✓✓ バーコードリーダーは正常に動作しています！ ✓✓✓")
    print("=" * 60)
except Exception as e:
    print(f"   ✗ decode実行失敗: {type(e).__name__}: {e}")
    print("\n詳細なエラー情報:")
    import traceback
    traceback.print_exc()
    print("\n" + "=" * 60)
    print("✗ バーコードリーダーは動作していません")
    print("=" * 60)
    
    # 追加の診断情報
    print("\n追加の診断情報:")
    print(f"Pythonバージョン: {sys.version}")
    print(f"pyzbarディレクトリ: {pyzbar_dir}")
    print(f"DLLファイルの確認:")
    
    required_dlls = ["libzbar-64.dll", "libiconv.dll", "zlib1.dll"]
    for dll in required_dlls:
        dll_path = pyzbar_dir / dll
        exists = dll_path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {dll}: {exists}")
    
    sys.exit(1)



