import pandas as pd
import io
import json
from pathlib import Path
from typing import List, Tuple, Dict, Any
from datetime import datetime
import json
from pathlib import Path

# 新しいSKUテンプレートレンダラ
try:
    from services.sku_template import SKUTemplateRenderer
except Exception:
    # 相対パスでの実行環境向けフォールバック
    from .sku_template import SKUTemplateRenderer

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
        """
        SKUを一括生成（店舗マスタ連携対応）
        
        productsには以下の情報が含まれる可能性がある:
        - supplier_code: 仕入れ先コード（店舗マスタから取得）
        - store_name: 店舗名
        - store_id: 店舗ID
        """
        
        # 設定ファイル読み込み（無ければ初期値）
        # 設定ファイルはリポジトリ直下の config/ に統一
        # services/ からは parents[2] がリポジトリルート
        config_path = Path(__file__).resolve().parents[2] / "config" / "inventory_settings.json"
        default_settings = {
            "skuTemplate": "{date:YYYYMMDD}-{ASIN|JAN}-{supplier}-{seq:3}-{condNum}",
            "seqScope": "day",
            "seqStart": 1
        }
        try:
            if config_path.exists():
                settings = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                settings = default_settings
        except Exception:
            settings = default_settings

        renderer = SKUTemplateRenderer(settings)

        results = []
        for idx, product in enumerate(products):
            try:
                sku = renderer.render_sku(product, seq_offset=idx)
            except Exception:
                sku = ""

            # 補助値
            condition = product.get("condition") or product.get("コンディション", "")
            supplier_code = product.get("supplier_code", "")
            store_name = product.get("store_name", "")
            store_id = product.get("store_id")

            results.append({
                "asin": product.get("asin") or product.get("ASIN", ""),
                "jan": product.get("jan") or product.get("JAN", ""),
                "product_name": product.get("product_name") or product.get("商品名", ""),
                "purchase_price": product.get("purchase_price") or product.get("仕入れ価格", 0),
                "condition": condition,
                "sku": sku,
                # 店舗情報
                "supplier_code": supplier_code,
                "store_name": store_name,
                "store_id": store_id
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
