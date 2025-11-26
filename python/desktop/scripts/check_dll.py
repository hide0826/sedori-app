#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DLLの依存関係を確認"""
import ctypes
import os

dll_path = r"C:\Users\user\AppData\Local\Programs\Python\Python313\Lib\site-packages\pyzbar\libzbar-64.dll"

print(f"DLL path: {dll_path}")
print(f"DLL exists: {os.path.exists(dll_path)}")

if os.path.exists(dll_path):
    try:
        # DLLを直接読み込んで依存関係を確認
        dll = ctypes.WinDLL(dll_path)
        print("✓ DLLの読み込みに成功（依存関係も解決できています）")
    except Exception as e:
        print(f"✗ DLLの読み込みに失敗: {e}")
        print("  依存関係（他のDLL）が見つからない可能性があります")
        
        # Dependency Walkerの代わりに、エラーメッセージから依存関係を推測
        error_str = str(e).lower()
        if "dependencies" in error_str or "dependency" in error_str:
            print("  解決方法: Visual C++ Redistributableをインストールしてください")
            print("  https://aka.ms/vs/17/release/vc_redist.x64.exe")
else:
    print("DLLファイルが見つかりません")




