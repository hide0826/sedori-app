#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AmazonテンプレートExcel書き込みテスト"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.amazon_inventory_loader_service import AmazonInventoryLoaderService

# テストデータ
test_products = [
    {
        'sku': 'TEST-SKU-001',
        'image_urls': [
            'https://example.com/image1.jpg',
            'https://example.com/image2.jpg',
            'https://example.com/image3.jpg',
        ]
    },
    {
        'sku': 'TEST-SKU-002',
        'image_url_1': 'https://example.com/img1.jpg',
        'image_url_2': 'https://example.com/img2.jpg',
        'image_url_3': 'https://example.com/img3.jpg',
        'image_url_4': 'https://example.com/img4.jpg',
        'image_url_5': 'https://example.com/img5.jpg',
        'image_url_6': 'https://example.com/img6.jpg',
    },
    {
        'sku': 'TEST-SKU-003',
        'image_urls': [
            'https://example.com/single.jpg',
        ]
    }
]

template_path = Path(__file__).parent / "ListingLoader.xlsm"
output_path = Path(__file__).parent / "ListingLoader_test_output.xlsm"

print("=" * 60)
print("Amazon Template Excel 書き込みテスト")
print("=" * 60)
print(f"\nテンプレートファイル: {template_path}")
print(f"出力ファイル: {output_path}")
print(f"商品数: {len(test_products)}")

if not template_path.exists():
    print(f"\nエラー: テンプレートファイルが見つかりません: {template_path}")
    sys.exit(1)

try:
    print("\n書き込み中...")
    result_path = AmazonInventoryLoaderService.write_to_amazon_template_excel(
        template_path=str(template_path),
        products=test_products,
        output_path=str(output_path),
        start_row=7
    )
    
    print(f"\n✓ 書き込み成功！")
    print(f"  出力ファイル: {result_path}")
    print(f"\n書き込まれたデータ:")
    print(f"  - SKU: A7列から")
    print(f"  - 画像URL: O7列から（1枚目）")
    print(f"  - 画像URL: P7列から（2枚目）")
    print(f"  - 画像URL: Q7列から（3枚目）")
    print(f"  - 画像URL: R7列から（4枚目）")
    print(f"  - 画像URL: S7列から（5枚目）")
    print(f"  - 画像URL: T7列から（6枚目）")
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ エラーが発生しました: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)




