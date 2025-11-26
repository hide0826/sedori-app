#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pyzbarディレクトリ内のすべてのDLLを確認"""
import os
from pathlib import Path

pyzbar_dir = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar")

print("=" * 60)
print("pyzbarディレクトリ内のすべてのファイル")
print("=" * 60)

if pyzbar_dir.exists():
    for item in sorted(pyzbar_dir.iterdir()):
        if item.is_file():
            size = item.stat().st_size
            print(f"{item.name:40} {size:>12,} bytes")
        elif item.is_dir():
            print(f"{item.name}/ (ディレクトリ)")
else:
    print(f"ディレクトリが見つかりません: {pyzbar_dir}")

print("\n" + "=" * 60)
print("DLLファイルの詳細確認")
print("=" * 60)

dlls = ["libzbar-64.dll", "libiconv.dll", "intl.dll", "zlib1.dll"]
for dll_name in dlls:
    dll_path = pyzbar_dir / dll_name
    if dll_path.exists():
        print(f"✓ {dll_name}: 存在")
        size = dll_path.stat().st_size
        print(f"    サイズ: {size:,} bytes")
    else:
        print(f"✗ {dll_name}: 見つかりません")

print("\n" + "=" * 60)
print("推奨: 不足している可能性のあるDLL")
print("=" * 60)
print("ZBarの完全なインストールには以下が必要です:")
print("- libzbar-64.dll")
print("- libiconv.dll")
print("- intl.dll (GNU gettext)")
print("- zlib1.dll (圧縮ライブラリ)")
print("\nintl.dllとzlib1.dllが見つからない場合、")
print("ZBarの公式インストーラーからbinディレクトリ内の")
print("すべてのDLLをpyzbarディレクトリにコピーしてください。")



