#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Visual C++ Runtimeの確認"""
import os
import winreg

print("=" * 60)
print("Visual C++ Redistributable の確認")
print("=" * 60)

# Visual C++ Runtimeのインストール状況を確認
vc_versions = [
    ("Visual C++ 2015-2022", r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
    ("Visual C++ 2013", r"SOFTWARE\Microsoft\VisualStudio\12.0\VC\Runtimes\x64"),
    ("Visual C++ 2012", r"SOFTWARE\Microsoft\VisualStudio\11.0\VC\Runtimes\x64"),
]

installed = False
for name, key_path in vc_versions:
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        version = winreg.QueryValueEx(key, "Version")[0]
        print(f"✓ {name}: インストール済み (Version: {version})")
        installed = True
        winreg.CloseKey(key)
    except FileNotFoundError:
        print(f"✗ {name}: 見つかりません")
    except Exception as e:
        print(f"  {name}: 確認できませんでした ({e})")

if not installed:
    print("\n⚠ Visual C++ Redistributableが見つかりません")
    print("  ダウンロード: https://aka.ms/vs/17/release/vc_redist.x64.exe")

print("\n" + "=" * 60)
print("追加の確認")
print("=" * 60)

# PATH環境変数にpyzbarディレクトリが含まれているか
pyzbar_dir = r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar"
path_env = os.environ.get("PATH", "")
if pyzbar_dir in path_env:
    print(f"✓ PATHにpyzbarディレクトリが含まれています")
else:
    print(f"✗ PATHにpyzbarディレクトリが含まれていません（通常は問題ありません）")




