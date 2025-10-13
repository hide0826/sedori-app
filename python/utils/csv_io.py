"""
HIRIO専用 CSV I/Oエンジン
標準ライブラリ版 - Pandas依存なし
"""
import csv
import io
from typing import List, Dict

def write_listing_csv(data: List[Dict], 
                     columns: List[str],
                     excel_formula_cols: List[str] = None) -> bytes:
    """
    出品用CSV生成（Shift-JIS、Excel数式記法対応）
    
    Args:
        data: 辞書のリスト（各行のデータ）
        columns: 列名リスト（出力順序）
        excel_formula_cols: Excel数式記法を適用する列名リスト
        
    Returns:
        CSV bytes (CP932/Shift-IS)
    """
    excel_cols = set(excel_formula_cols or [])
    
    # StringIO でCSV生成
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n')
    
    # 説明行（1行目）
    writer.writerow(['ASIN、JANはどちらか一方のみ記載してください。'])
    
    # ヘッダー行（2行目）
    writer.writerow(columns)
    
    # データ行
    for row_dict in data:
        row = []
        for col in columns:
            value = row_dict.get(col, '')
            
            # Excel数式記法適用
            if col in excel_cols and value:
                value = f'="{value}"'
            
            row.append(str(value) if value is not None else '')
        
        writer.writerow(row)
    
    # CP932 (Windows Shift-JIS) bytes変換
    csv_str = output.getvalue()
    csv_bytes = csv_str.encode('cp932', errors='replace')
    
    return csv_bytes