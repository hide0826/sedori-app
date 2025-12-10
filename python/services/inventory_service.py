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
    def _normalize_asin_jan(value):
        """
        ASIN/JANコードの科学的記数法を正規化
        
        ASIN: 10桁の数字または10文字の英数字（例: 4048965379, B0085PIHM0）
        JAN: 13桁の数字（例: 4901234567890）
        
        Args:
            value: ASINまたはJANの値（文字列、数値、科学的記数法など）
            
        Returns:
            正規化されたASIN/JANコード（文字列）
        """
        if value is None or pd.isna(value):
            return ''
        
        # 文字列に変換
        str_value = str(value).strip()
        if not str_value:
            return ''
        
        # 科学的記数法のパターンをチェック（例: 4.05E+09, 4.8E+09）
        import re
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

    @staticmethod
    def generate_listing_csv_content(products: List[dict]) -> bytes:
        """
        商品リストから出品用CSVコンテンツを生成する（Shift-JISエンコーディング）。
        参考フォーマット: D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20251102つくばルート\20251102_出品用CSV.csv
        """
        if not products:
            return b""

        # ASIN/JANコードの科学的記数法を正規化
        for product in products:
            if 'asin' in product:
                product['asin'] = InventoryService._normalize_asin_jan(product['asin'])
            if 'jan' in product:
                product['jan'] = InventoryService._normalize_asin_jan(product['jan'])

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
            'product_name': 'title',
            'quantity': 'add_number',
            'plannedPrice': 'price',
            'purchasePrice': 'cost',
            'breakEven': 'akaji',
            'takane': 'takane',
            'condition': 'condition',
            'conditionNote': 'conditionNote',
            'condition_note': 'conditionNote',
            'priceTrace': 'priceTrace',
            'price_trace': 'priceTrace'
        }

        # Create output DataFrame with required columns
        output_data = {}
        
        # Map existing columns
        for old_col, new_col in column_mapping.items():
            if old_col in df.columns:
                output_data[new_col] = df[old_col]
        
        # conditionNoteが存在しない場合は空文字列のSeriesを作成
        if 'conditionNote' not in output_data:
            # DataFrameの行数に合わせて空文字列のSeriesを作成
            output_data['conditionNote'] = pd.Series([''] * len(df), index=df.index)
        
        # Add required columns with default values if missing
        final_columns = [
            'SKU', 'ASIN', 'JAN', 'title', 'add_number', 'price', 'cost', 'akaji', 'takane',
            'condition', 'conditionNote', 'priceTrace', 'leadtime', 'merchant_shipping_group_name'
        ]
        
        for col in final_columns:
            if col not in output_data:
                output_data[col] = ''
        
        # Create final DataFrame
        df_output = pd.DataFrame(output_data)

        # ASIN/JAN列の科学的記数法を正規化（DataFrame変換後も念のため）
        if 'ASIN' in df_output.columns:
            df_output['ASIN'] = df_output['ASIN'].apply(
                lambda x: InventoryService._normalize_asin_jan(x) if pd.notna(x) else ''
            )
        if 'JAN' in df_output.columns:
            df_output['JAN'] = df_output['JAN'].apply(
                lambda x: InventoryService._normalize_asin_jan(x) if pd.notna(x) else ''
            )

        # If ASIN exists, JAN should be empty (逆も同様)
        if 'ASIN' in df_output.columns and 'JAN' in df_output.columns:
            df_output['JAN'] = df_output.apply(
                lambda row: '' if pd.notna(row['ASIN']) and str(row['ASIN']).strip() != '' else (row['JAN'] if pd.notna(row['JAN']) else ''), 
                axis=1
            )
            df_output['ASIN'] = df_output.apply(
                lambda row: '' if pd.notna(row['JAN']) and str(row['JAN']).strip() != '' else (row['ASIN'] if pd.notna(row['ASIN']) else ''), 
                axis=1
            )
        
        # Reorder columns
        df_final = df_output.reindex(columns=final_columns, fill_value='')

        # Replace NaN with empty string for all columns
        df_final = df_final.fillna('')

        # Shift-JIS 向けの正規化（文字化け対策）
        try:
            df_final = normalize_dataframe_for_cp932(df_final)
        except Exception:
            # 正規化で問題が出てもフォールバックして続行
            pass

        # Generate CSV content using csv_io module for consistency
        from utils.csv_io import write_listing_csv
        
        # Convert to list of dicts
        records = df_final.to_dict(orient='records')
        
        # ASIN/JAN列の科学的記数法を正規化（辞書変換後にも念のため）
        for record in records:
            if 'ASIN' in record:
                record['ASIN'] = InventoryService._normalize_asin_jan(record['ASIN'])
            if 'JAN' in record:
                record['JAN'] = InventoryService._normalize_asin_jan(record['JAN'])
        
        # Debug: conditionNoteが含まれているか確認
        if records:
            first_record = records[0]
            if 'conditionNote' in first_record:
                print(f"DEBUG: conditionNote value in first record: {repr(first_record['conditionNote'])}")
            else:
                print("DEBUG: conditionNote not found in first record")
                print(f"DEBUG: Available keys: {list(first_record.keys())}")
        
        # Generate CSV using write_listing_csv
        csv_bytes = write_listing_csv(records, final_columns, excel_formula_cols=None)
        
        return csv_bytes
