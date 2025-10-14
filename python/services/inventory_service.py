import pandas as pd
from typing import List, Tuple, Dict, Any
from datetime import datetime

from core.csv_utils import read_csv_with_fallback, normalize_dataframe_for_cp932

class InventoryService:
    @staticmethod
    async def process_inventory_csv(content: bytes) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        アップロードされたCSVファイルを処理し、DataFrameと統計情報を返却する。
        """
        df = read_csv_with_fallback(content)
        df = normalize_dataframe_for_cp932(df)

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
