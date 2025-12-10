"""
HIRIO専用 CSV I/Oエンジン
標準ライブラリ版 - Pandas依存なし
"""
import csv
import io
import re
from typing import List, Dict

EXCEL_HINT_ROW = ['ASIN、JANはどちらか一方のみ記載してください。'] + [''] * 13  # 14列のCSVなので残り13列を空で埋める

def _normalize_asin_jan_value(value):
    """
    ASIN/JANコードの科学的記数法を正規化
    
    ASIN: 10桁の数字（例: 4048965379）
    JAN: 13桁の数字（例: 4901234567890）
    
    Args:
        value: ASINまたはJANの値（文字列、数値、科学的記数法など）
        
    Returns:
        正規化されたASIN/JANコード（文字列）
    """
    if not value or value == '':
        return ''
    
    # 文字列に変換
    str_value = str(value).strip()
    if not str_value:
        return ''
    
    # 科学的記数法のパターンをチェック（例: 4.05E+09, 4.8E+09）
    scientific_pattern = r'^(\d+\.?\d*)[eE][\+\-]?(\d+)$'
    match = re.match(scientific_pattern, str_value)
    
    if match:
        try:
            # 科学的記数法を数値に変換
            num_value = float(str_value)
            # 整数に変換
            int_value = int(num_value)
            # 文字列に変換（先頭0は保持）
            normalized = str(int_value)
            
            # 桁数でASINかJANかを判定
            # ASINは10桁、JANは13桁
            if len(normalized) == 10:
                # 10桁の場合はASINとして扱う（そのまま返す）
                return normalized
            elif len(normalized) == 13:
                # 13桁の場合はJANとして扱う（そのまま返す）
                return normalized
            elif len(normalized) < 10:
                # 10桁未満の場合は、10桁のASINとして先頭0埋め
                return normalized.zfill(10)
            elif len(normalized) < 13:
                # 10桁以上13桁未満の場合は、13桁のJANとして先頭0埋め
                return normalized.zfill(13)
            else:
                # 13桁を超える場合はそのまま返す
                return normalized
        except (ValueError, OverflowError):
            # 変換に失敗した場合は元の値を返す
            return str_value
    
    # 科学的記数法でない場合は、そのまま返す（ただし文字列として）
    return str_value

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
    # ASIN/JAN は Excel に数値として解釈されると 4.05E+09 形式になるため、
    # 常に Excel 数式記法（=\"...\") で文字列として扱う
    excel_cols.update({"ASIN", "JAN"})
    
    # StringIO でCSV生成
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n', quoting=csv.QUOTE_ALL, doublequote=True)
    
    # 説明行（1行目）
    writer.writerow(EXCEL_HINT_ROW)
    
    # ヘッダー行（2行目）
    writer.writerow(columns)
    
    # データ行
    for row_dict in data:
        row = []
        for col in columns:
            value = row_dict.get(col, '')
            
            # ASIN/JAN列の科学的記数法を正規化
            if col in ['ASIN', 'JAN']:
                value = _normalize_asin_jan_value(value)
            
            # 事前の軽いサニタイズ（改行/タブ→空白）
            if isinstance(value, str):
                value = value.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')

            # Excel数式記法適用
            if col in excel_cols and value:
                value = f'="{value}"'
            
            row.append(str(value) if value is not None else '')
        
        writer.writerow(row)
    
    # CP932 (Windows Shift-JIS) bytes変換
    csv_str = output.getvalue()
    csv_bytes = csv_str.encode('cp932', errors='replace')
    
    return csv_bytes

def write_listing_csv_from_dataframe(df, columns: List[str], excel_formula_cols: List[str]) -> bytes:
    """
    DataFrameから出品用CSVを生成（厳密クォート・CRLF・cp932）。
    """
    records: List[Dict] = []
    for _, row in df.iterrows():
        rec: Dict[str, str] = {}
        for col in columns:
            v = row[col] if col in row else ''
            rec[col] = '' if v is None else str(v)
        records.append(rec)
    return write_listing_csv(records, columns, excel_formula_cols)

def write_repricer_csv(df, columns: List[str], excel_formula_cols: List[str] = None) -> bytes:
    """
    Repricing用CSV生成（説明行なし、ヘッダー+データのみ）。
    - 全列QUOTE_ALL
    - CRLF
    - cp932（errors='replace'）
    - 先頭の説明行や ="..." の付与は行わない
    """
    # records 構築
    records: List[Dict] = []
    for _, row in df.iterrows():
        rec: Dict[str, str] = {}
        for col in columns:
            v = row[col] if col in row else ''
            rec[col] = '' if v is None else str(v)
        records.append(rec)

    # CSV生成（ヘッダー+データのみ）
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n', quoting=csv.QUOTE_ALL, doublequote=True)
    writer.writerow(columns)
    for row_dict in records:
        row = []
        for col in columns:
            value = row_dict.get(col, '')
            if isinstance(value, str):
                value = value.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
            row.append(str(value) if value is not None else '')
        writer.writerow(row)

    csv_str = output.getvalue()
    csv_bytes = csv_str.encode('cp932', errors='replace')
    return csv_bytes