"""
HIRIO 仕入管理システム
inventory_service.py

作成日: 2025-10-06
"""
import pandas as pd
import chardet
import io
from typing import Tuple

async def process_inventory_csv(file_content: bytes) -> Tuple[pd.DataFrame, dict]:
    """
    仕入リストCSVを処理
    
    Args:
        file_content: CSVファイルのバイトデータ
    
    Returns:
        DataFrame: 処理済みデータ
        dict: 処理結果の統計情報
    """
    # 1. エンコーディング自動判定
    detected = chardet.detect(file_content)
    encoding = detected['encoding']
    
    # 2. CSV読み込み（JAN列を文字列として保持）
    df = pd.read_csv(
        io.BytesIO(file_content),
        encoding=encoding,
        dtype={'JAN': str}
    )
    
    # 3. JAN列の科学的記数法を数値文字列に変換
    if 'JAN' in df.columns:
        def fix_jan(val):
            if pd.isna(val) or val is None:
                return None
            try:
                # 科学的記数法（例: 4.9016E+12）を数値に変換後、整数文字列化
                if 'E' in str(val).upper():
                    return str(int(float(val)))
                return str(val)
            except:
                return str(val)
        
        df['JAN'] = df['JAN'].apply(fix_jan)
    
    # 4. NaN/Infinity値をNoneに変換（JSON互換性のため）
    df = df.replace({float('nan'): None, float('inf'): None, float('-inf'): None})
    
    # 5. 統計情報
    stats = {
        "total_rows": len(df),
        "columns": list(df.columns),
        "encoding": encoding
    }
    
    return df, stats