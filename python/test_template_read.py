#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AmazonテンプレートExcel読み込みテスト"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.amazon_inventory_loader_service import AmazonInventoryLoaderService

template_path = Path(__file__).parent / "ListingLoader.xlsm"

print("=" * 60)
print("Amazon Template Excel 読み込みテスト")
print("=" * 60)
print(f"\nファイル: {template_path}")
print(f"ファイル存在確認: {template_path.exists()}")

if not template_path.exists():
    print("エラー: ファイルが見つかりません")
    sys.exit(1)

try:
    print("\n読み込み中...")
    result = AmazonInventoryLoaderService.read_amazon_template_excel(str(template_path))
    
    print("\n✓ 読み込み成功！")
    print(f"\n利用可能なシート: {result['sheet_names']}")
    
    if result["template_sheet"]:
        ts = result["template_sheet"]
        print(f"\n✓ 「テンプレート」シートが見つかりました！")
        print(f"  最大行: {ts['max_row']}")
        print(f"  最大列: {ts['max_column']}")
        print(f"  ヘッダー数: {len(ts['headers'])}")
        
        print(f"\n【ヘッダー一覧（最初の30列）】")
        for col_idx, header in ts["headers"][:30]:
            print(f"  列{col_idx:2d}: {header}")
        
        if len(ts["headers"]) > 30:
            print(f"  ... (他 {len(ts['headers']) - 30} 列)")
    else:
        print("\n✗ 「テンプレート」シートが見つかりませんでした")
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ エラーが発生しました: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)




