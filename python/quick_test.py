import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from services.amazon_inventory_loader_service import AmazonInventoryLoaderService

template = Path(__file__).parent / "ListingLoader.xlsm"
result = AmazonInventoryLoaderService.read_amazon_template_excel(str(template))

print("シート名:", result['sheet_names'])
if result['template_sheet']:
    ts = result['template_sheet']
    print(f"最大行: {ts['max_row']}, 最大列: {ts['max_column']}")
    print(f"ヘッダー数: {len(ts['headers'])}")
    print("\n最初の20ヘッダー:")
    for col, hdr in ts['headers'][:20]:
        print(f"  列{col}: {hdr}")
else:
    print("テンプレートシートが見つかりません")




