"""
CSV I/Oエンジン テストスクリプト
"""
import sys
sys.path.insert(0, '/app/python')

from utils.csv_io import write_listing_csv

# テストデータ作成（辞書のリスト形式）
test_data = [
    {
        'SKU': '20241008-2-001-Q4',
        'ASIN': 'B0TESTSKU001',
        'JAN': '4902370549577',
        'title': 'Nintendo Switch ポケモン',
        'add_number': 1,
        'price': 5000,
        'cost': 3000,
        'akaji': 3800,
        'takane': 5000,
        'condition': 2,
        'conditionNote': '美品',
        'priceTrace': '',
        'leadtime': '',
        'merchant_shipping_group_name': ''
    },
    {
        'SKU': '20241008-3-001',
        'ASIN': 'B0TESTSKU002',
        'JAN': '4959241123456',
        'title': 'DVD アナと雪の女王',
        'add_number': 2,
        'price': 1500,
        'cost': 500,
        'akaji': 900,
        'takane': 1500,
        'condition': 3,
        'conditionNote': '傷あり',
        'priceTrace': '',
        'leadtime': '',
        'merchant_shipping_group_name': ''
    }
]

# 列順序定義
columns = ['SKU', 'ASIN', 'JAN', 'title', 'add_number', 'price', 
           'cost', 'akaji', 'takane', 'condition', 'conditionNote', 
           'priceTrace', 'leadtime', 'merchant_shipping_group_name']

print("=== CSV生成テスト（標準ライブラリ版）===")
try:
    csv_bytes = write_listing_csv(
        data=test_data,
        columns=columns,
        excel_formula_cols=['SKU', 'ASIN', 'JAN']
    )
    
    print(f"成功: {len(csv_bytes)} bytes生成")
    
    # ファイルに保存
    output_path = '/app/test_output.csv'
    with open(output_path, 'wb') as f:
        f.write(csv_bytes)
    
    print(f"保存完了: {output_path}")
    
    # 内容確認
    print("\n=== 生成されたCSV全体 ===")
    print(csv_bytes.decode('shift-jis', errors='replace'))
    
except Exception as e:
    print(f"エラー: {e}")
    import traceback
    traceback.print_exc()