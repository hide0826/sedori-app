#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amazon Inventory Loader (Lファイル) 生成サービス

Amazon出品用のInventory Loader TSVファイルを生成する。
画像URLを含む出品用ファイルフォーマットに対応。
"""
from __future__ import annotations

import pandas as pd
import io
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

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


class AmazonInventoryLoaderService:
    """Amazon Inventory Loader (Lファイル) 生成サービス"""
    
    @staticmethod
    def generate_inventory_loader_tsv(products: List[dict]) -> bytes:
        """
        Amazon Inventory Loader TSVファイルを生成
        
        Args:
            products: 商品データのリスト
                必須フィールド:
                - sku: SKU
                - price: 販売価格
                - quantity: 在庫数
                - product_id: ASIN または JAN
                - product_id_type: 1=ASIN, 4=JAN
                - condition_type: コンディション番号
                オプションフィールド:
                - condition_note: コンディション説明
                - image_url_1 ～ image_url_5: 商品画像URL（GCSアップロード後）
                
        Returns:
            TSV bytes (cp932/Shift-JIS, タブ区切り)
        """
        if not products:
            return b""
        
        # ヘッダー定義（Amazon Inventory Loader形式）
        headers = [
            'sku',                  # 【必須】商品管理番号
            'price',                # 【必須】販売価格
            'quantity',             # 【必須】在庫数
            'product-id',           # 【必須】ASIN または JAN
            'product-id-type',      # 【必須】1=ASIN, 4=JAN
            'condition-type',       # 【必須】コンディション番号
            'condition-note',       # コンディション説明文
            'fulfillment-center-id', # 【重要】AMAZON_JP = FBA利用
            # 画像更新用フィールド
            'main-image-url',       # メイン画像 (通常は空欄)
            'offer-image-url-1',    # 中古コンディション写真 1枚目
            'offer-image-url-2',    # 中古コンディション写真 2枚目
            'offer-image-url-3',    # 中古コンディション写真 3枚目
            'offer-image-url-4',    # 中古コンディション写真 4枚目
            'offer-image-url-5',    # 中古コンディション写真 5枚目
        ]
        
        # データ変換
        records = []
        for product in products:
            # ===== 必須フィールドのチェック =====
            sku = product.get('sku') or product.get('SKU')
            if not sku:
                logger.warning(f"Skipping product without SKU: {product}")
                continue

            # A案: 画像だけ更新モード
            # 価格・在庫は常に空欄を送る（Amazon側で価格・在庫を更新しない想定）
            price_value: Any = ''
            quantity_value: Any = ''
            
            # product-id と product-id-type
            asin = product.get('asin') or product.get('ASIN') or ''
            jan = product.get('jan') or product.get('JAN') or ''
            
            if asin:
                product_id = asin
                product_id_type = 1  # ASIN
            elif jan:
                product_id = jan
                product_id_type = 4  # JAN
            else:
                logger.warning(f"Skipping product {sku} without ASIN or JAN")
                continue
            
            # コンディション（ここは必須のまま）
            condition_type = product.get('condition_type') or product.get('condition-type')
            if not condition_type:
                # コンディション文字列から変換
                condition_str = product.get('condition') or product.get('コンディション') or ''
                condition_type = CONDITION_MAP.get(condition_str, '')
            
            if not condition_type:
                logger.warning(f"Skipping product {sku} without condition")
                continue
            
            # コンディション説明
            condition_note = product.get('condition_note') or product.get('condition-note') or product.get('conditionNote') or product.get('コンディション説明') or ''
            
            # 画像URL（image_url_1 ～ image_url_5 から offer-image-url-1 ～ 5 へマッピング）
            image_urls = []
            for i in range(1, 6):
                img_key = f'image_url_{i}'
                img_url = product.get(img_key) or product.get(f'画像URL{i}') or ''
                if img_url:
                    image_urls.append(img_url)
            
            # レコード作成
            record = {
                'sku': str(sku),
                # A案: 価格・在庫は空欄を許容（画像だけ更新モード）
                'price': price_value,
                'quantity': quantity_value,
                'product-id': str(product_id),
                'product-id-type': int(product_id_type),
                'condition-type': str(condition_type),
                'condition-note': str(condition_note),
                'fulfillment-center-id': 'AMAZON_JP',  # FBA利用
                'main-image-url': '',  # 通常は空欄
                'offer-image-url-1': image_urls[0] if len(image_urls) > 0 else '',
                'offer-image-url-2': image_urls[1] if len(image_urls) > 1 else '',
                'offer-image-url-3': image_urls[2] if len(image_urls) > 2 else '',
                'offer-image-url-4': image_urls[3] if len(image_urls) > 3 else '',
                'offer-image-url-5': image_urls[4] if len(image_urls) > 4 else '',
            }
            records.append(record)
        
        if not records:
            return b""
        
        # DataFrameに変換
        df = pd.DataFrame(records, columns=headers)
        
        # TSV生成（タブ区切り、cp932エンコーディング）
        output = io.StringIO()
        df.to_csv(output, sep='\t', index=False, encoding='cp932', errors='replace')
        
        # bytes変換
        tsv_str = output.getvalue()
        tsv_bytes = tsv_str.encode('cp932', errors='replace')
        
        logger.info(f"Generated Amazon Inventory Loader TSV: {len(records)} records")
        return tsv_bytes

