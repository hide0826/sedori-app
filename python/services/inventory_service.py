import pandas as pd
import io
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any
from datetime import datetime

from core.csv_utils import read_csv_with_fallback, normalize_dataframe_for_cp932
from utils.csv_io import write_listing_csv

# コンディションマッピング（Amazonコンディション番号）
CONDITION_MAP = {
    "中古(ほぼ新品)": "1",
    "中古(非常に良い)": "2", 
    "中古(良い)": "3",
    "中古(可)": "4",
    "コレクター商品(ほぼ新品)": "5",
    "コレクター商品(非常に良い)": "6",
    "コレクター商品(良い)": "7",
    "コレクター商品(可)": "8",
    "再生品": "10",
    "新品(新品)": "11",
    "新品": "11",
}

class InventoryService:
    @staticmethod
    async def process_inventory_csv(content: bytes) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        アップロードされたCSVファイルを処理し、DataFrameと統計情報を返却する。
        """
        df = read_csv_with_fallback(content)
        df = normalize_dataframe_for_cp932(df)

        # Debugging: Print DataFrame columns and a sample of data
        print(f"DEBUG: DataFrame columns after normalization: {list(df.columns)}")
        print(f"DEBUG: DataFrame head after normalization:\n{df.head().to_string()}")

        # ここでCSVの内容に基づいた統計情報を生成する（モック）
        stats = {
            "total_rows": len(df),
            "processed_headers": list(df.columns),
            "message": f"CSVファイルを正常に読み込み、{len(df)}件のデータを処理しました。"
        }
        
        return df, stats

    @staticmethod
    def generate_sku_bulk(products: List[dict]) -> dict:
        """SKUを一括生成"""
        
        # コンディションコード変換マップ
        CONDITION_MAP = {
            "新品": "N",
            "中古": "C",
            "ほぼ新品": "V",
            "非常に良い": "V",
            "良い": "G",
            "可": "A"
        }
        
        # 今日の日付を取得（YYYYMMDD形式）
        today = datetime.now().strftime("%Y%m%d")
        
        # 既存SKUから最大連番を取得（実装済みの場合）
        # 今回は簡易的に001から開始
        start_number = 1
        
        results = []
        for idx, product in enumerate(products):
            # 連番生成（3桁ゼロパディング）
            seq_number = str(start_number + idx).zfill(3)
            
            # コンディションコード取得
            condition = product.get("condition", "新品")
            condition_code = CONDITION_MAP.get(condition, "N")
            
            # Qタグ（デフォルトで付与、将来的にユーザー選択可能に）
            q_tag = "Q"
            
            # SKU生成
            sku = f"{q_tag}{today}-{seq_number}-{condition_code}"
            
            # 結果に追加
            results.append({
                "jan": product.get("jan"),
                "product_name": product.get("product_name"),
                "purchase_price": product.get("purchase_price"),
                "condition": condition,
                "sku": sku,
                "condition_code": condition_code,
                "q_tag": q_tag
            })
        
        return {
            "success": True,
            "processed": len(results),
            "results": results
        }

    @staticmethod
    def generate_listing_csv_content(products: List[dict]) -> bytes:
        """
        商品リストから出品用CSVコンテンツを生成する（Shift-JISエンコーディング）。
        参考フォーマット: D:\HIRIO\docs\参考データ\20250928_出品用CSV.csv
        """
        if not products:
            return b""

        # DataFrameに変換
        df = pd.DataFrame(products)

        # Apply condition mapping
        if 'condition' in df.columns:
            df['condition'] = df['condition'].map(CONDITION_MAP).fillna(df['condition'])

        # Column mapping from frontend to output format
        column_mapping = {
            'sku': 'SKU',
            'asin': 'ASIN', 
            'jan': 'JAN',
            'productName': 'title',
            'quantity': 'add_number',
            'plannedPrice': 'price',
            'purchasePrice': 'cost',
            'breakEven': 'akaji',
            'conditionNote': 'conditionNote',
            'priceTrace': 'priceTrace'
        }

        # Create output DataFrame with required columns
        output_data = {}
        
        # Map existing columns
        for old_col, new_col in column_mapping.items():
            if old_col in df.columns:
                output_data[new_col] = df[old_col]
            else:
                output_data[new_col] = ''
        
        # Add condition (already mapped above)
        if 'condition' in df.columns:
            output_data['condition'] = df['condition']
        else:
            output_data['condition'] = ''
            
        # Add empty columns as per reference format
        output_data['takane'] = ''
        output_data['leadtime'] = ''
        output_data['merchant_shipping_group_name'] = ''

        # Create final DataFrame
        df_output = pd.DataFrame(output_data)

        # If ASIN exists, JAN should be empty
        if 'ASIN' in df_output.columns and 'JAN' in df_output.columns:
            df_output['JAN'] = df_output.apply(lambda row: '' if pd.notna(row['ASIN']) and row['ASIN'] != '' else row['JAN'], axis=1)

        # Define final column order matching reference format
        final_columns = [
            'SKU', 'ASIN', 'JAN', 'title', 'add_number', 'price', 'cost', 'akaji', 'takane',
            'condition', 'conditionNote', 'priceTrace', 'leadtime', 'merchant_shipping_group_name'
        ]
        
        # Reorder columns
        df_final = df_output.reindex(columns=final_columns, fill_value='')

        # Generate CSV content with header note
        output = io.StringIO()
        # Add header note as in reference file
        output.write('ASIN、JANはどちらか一方のみ記載してください。,,,,,,,,,,,,,\n')
        df_final.to_csv(output, index=False)
        csv_content = output.getvalue()

        return csv_content.encode('cp932', errors='replace')
