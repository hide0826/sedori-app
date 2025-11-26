#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pyzbarの簡単な動作テスト"""
try:
    from pyzbar import pyzbar
    from PIL import Image
    
    print("✓ モジュールのインポート成功")
    
    # テスト画像を作成
    img = Image.new('RGB', (100, 100), color='white')
    print("✓ テスト画像の作成成功")
    
    # バーコードを読み取ろうとする（バーコードがなくてもエラーにならないはず）
    try:
        result = pyzbar.decode(img)
        print(f"✓ pyzbar.decode実行成功（バーコード数: {len(result)}）")
        print("✓ バーコードリーダーは正常に動作しています！")
    except Exception as e:
        print(f"✗ pyzbar.decode実行失敗: {type(e).__name__}: {e}")
        print("  詳細:")
        import traceback
        traceback.print_exc()
        
except ImportError as e:
    print(f"✗ モジュールのインポート失敗: {e}")




