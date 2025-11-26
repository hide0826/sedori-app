#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DLLの依存関係を詳細にチェック"""
import os
import ctypes
from pathlib import Path

pyzbar_dir = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar")

print("=" * 60)
print("DLLファイルの存在確認")
print("=" * 60)

dlls = {
    "libzbar-64.dll": pyzbar_dir / "libzbar-64.dll",
    "libiconv.dll": pyzbar_dir / "libiconv.dll",
}

for name, path in dlls.items():
    exists = path.exists()
    status = "✓" if exists else "✗"
    print(f"{status} {name}: {exists}")
    if exists:
        size = path.stat().st_size
        print(f"    サイズ: {size:,} bytes")
        print(f"    パス: {path}")

print("\n" + "=" * 60)
print("DLLの読み込みテスト")
print("=" * 60)

# libiconv.dllの読み込みテスト
if dlls["libiconv.dll"].exists():
    try:
        libiconv = ctypes.WinDLL(str(dlls["libiconv.dll"]))
        print("✓ libiconv.dllの読み込み成功")
    except Exception as e:
        print(f"✗ libiconv.dllの読み込み失敗: {e}")

# libzbar-64.dllの読み込みテスト
if dlls["libzbar-64.dll"].exists():
    try:
        libzbar = ctypes.WinDLL(str(dlls["libzbar-64.dll"]))
        print("✓ libzbar-64.dllの読み込み成功")
    except Exception as e:
        print(f"✗ libzbar-64.dllの読み込み失敗: {e}")
        print(f"  エラー詳細: {type(e).__name__}")

print("\n" + "=" * 60)
print("pyzbarの動作テスト")
print("=" * 60)

try:
    from pyzbar import pyzbar
    from PIL import Image
    
    print("✓ モジュールのインポート成功")
    
    img = Image.new('RGB', (100, 100), color='white')
    print("✓ テスト画像の作成成功")
    
    try:
        result = pyzbar.decode(img)
        print(f"✓ pyzbar.decode実行成功（バーコード数: {len(result)}）")
        print("✓✓✓ バーコードリーダーは正常に動作しています！ ✓✓✓")
    except Exception as e:
        print(f"✗ pyzbar.decode実行失敗: {type(e).__name__}: {e}")
        print("\n詳細なエラー情報:")
        import traceback
        traceback.print_exc()
        
except ImportError as e:
    print(f"✗ モジュールのインポート失敗: {e}")




