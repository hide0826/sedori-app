#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPIクライアント

既存FastAPI（ポート8000）との通信
- 価格改定API
- 仕入管理API
- 古物台帳API
"""

import requests
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging


class APIClient:
    """FastAPIクライアント"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # ログ設定
        self.logger = logging.getLogger(__name__)
        
    def test_connection(self) -> bool:
        """API接続テスト"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"API接続テスト失敗: {e}")
            return False
    
    # 価格改定API
    def repricer_preview(self, csv_data: pd.DataFrame) -> Dict[str, Any]:
        """価格改定プレビュー"""
        try:
            # ダミー実装（実際はAPI呼び出し）
            return self._simulate_repricer_preview(csv_data)
        except Exception as e:
            self.logger.error(f"価格改定プレビュー失敗: {e}")
            raise
    
    def repricer_apply(self, csv_data: pd.DataFrame) -> Dict[str, Any]:
        """価格改定実行"""
        try:
            # ダミー実装（実際はAPI呼び出し）
            return self._simulate_repricer_apply(csv_data)
        except Exception as e:
            self.logger.error(f"価格改定実行失敗: {e}")
            raise
    
    def _simulate_repricer_preview(self, csv_data: pd.DataFrame) -> Dict[str, Any]:
        """価格改定プレビューのシミュレーション"""
        import random
        
        items = []
        for i, row in csv_data.iterrows():
            days = random.randint(30, 365)
            current_price = random.randint(1000, 10000)
            price_change = random.randint(-500, 500)
            new_price = max(100, current_price + price_change)
            
            item = {
                'sku': f"20250101-{row.get('ASIN', 'UNKNOWN')}-{i+1:04d}",
                'days': days,
                'action': 'price_down_1' if price_change < 0 else 'price_up_1',
                'reason': f"Rule for {days} days ({'price_down_1' if price_change < 0 else 'price_up_1'})",
                'price': current_price,
                'new_price': new_price,
                'priceTrace': 0,
                'new_priceTrace': 0
            }
            items.append(item)
        
        return {
            'summary': {
                'updated_rows': len(items),
                'excluded_rows': 0,
                'q4_switched': 0,
                'date_unknown': 0,
                'log_rows': len(items)
            },
            'items': items
        }
    
    def _simulate_repricer_apply(self, csv_data: pd.DataFrame) -> Dict[str, Any]:
        """価格改定実行のシミュレーション"""
        # プレビューと同じロジック
        return self._simulate_repricer_preview(csv_data)
    
    # 仕入管理API
    def inventory_upload(self, file_path: str) -> Dict[str, Any]:
        """仕入データアップロード"""
        try:
            # ダミー実装
            return {
                'status': 'success',
                'message': 'ファイルアップロード完了',
                'rows': 100,
                'columns': 17
            }
        except Exception as e:
            self.logger.error(f"仕入データアップロード失敗: {e}")
            raise
    
    def inventory_generate_sku(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """SKU生成"""
        try:
            # ダミー実装
            sku_results = []
            for i, item in enumerate(data):
                sku = f"20250101-{item.get('ASIN', 'UNKNOWN')}-{i+1:04d}"
                sku_results.append({
                    'original_data': item,
                    'generated_sku': sku,
                    'q_tag': self._determine_q_tag(item),
                    'status': 'success'
                })
            
            return {
                'status': 'success',
                'generated_count': len(sku_results),
                'results': sku_results
            }
        except Exception as e:
            self.logger.error(f"SKU生成失敗: {e}")
            raise
    
    def _determine_q_tag(self, item: Dict[str, Any]) -> str:
        """Qタグの判定（ダミー実装）"""
        # 実際の実装では、商品名やカテゴリからQタグを判定
        import random
        q_tags = ['Q1', 'Q2', 'Q3', 'Q4', '']
        return random.choice(q_tags)
    
    def inventory_export_listing(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """出品CSV生成"""
        try:
            # ダミー実装
            listing_data = []
            for item in data:
                price = item.get('price', 0)
                takane = int(price * 1.05)  # 5%の利益率
                
                listing_item = {
                    'SKU': item.get('sku', ''),
                    'ASIN': item.get('asin', ''),
                    '商品名': item.get('title', ''),
                    '価格': price,
                    '高値': takane,
                    '状態': item.get('condition', ''),
                    '在庫': 1,
                    '出品日': '2025-01-01',
                    '備考': item.get('notes', ''),
                    '写真': '',
                    'URL': '',
                    'メモ': '',
                    'Q列': item.get('q_tag', ''),
                    '店舗': item.get('store', ''),
                    '仕入日': item.get('purchase_date', ''),
                    '原価': item.get('cost', 0),
                    '利益': price - item.get('cost', 0)
                }
                listing_data.append(listing_item)
            
            return {
                'status': 'success',
                'exported_count': len(listing_data),
                'data': listing_data
            }
        except Exception as e:
            self.logger.error(f"出品CSV生成失敗: {e}")
            raise
    
    # 古物台帳API
    def antique_register_generate(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """古物台帳生成"""
        try:
            # ダミー実装
            register_data = {
                'status': 'success',
                'period': f"{start_date} 〜 {end_date}",
                'items': [
                    {
                        '品名': 'サンプル商品1',
                        '数量': 1,
                        '特徴': '中古品、良好な状態',
                        '相手方': '店舗A',
                        '取引年月日': '2025-01-01',
                        '価格': 1000
                    },
                    {
                        '品名': 'サンプル商品2',
                        '数量': 1,
                        '特徴': '中古品、やや使用感あり',
                        '相手方': '店舗B',
                        '取引年月日': '2025-01-02',
                        '価格': 2000
                    }
                ],
                'total_items': 2,
                'total_value': 3000
            }
            
            return register_data
        except Exception as e:
            self.logger.error(f"古物台帳生成失敗: {e}")
            raise
    
    # ピッキングリストAPI
    def picking_list_generate(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """ピッキングリスト生成"""
        try:
            # ダミー実装
            picking_data = {
                'status': 'success',
                'generated_count': len(data),
                'items': [
                    {
                        'SKU': item.get('sku', ''),
                        '商品名': item.get('title', ''),
                        '場所': f"棚{i+1}",
                        '数量': 1,
                        '備考': item.get('notes', '')
                    }
                    for i, item in enumerate(data)
                ]
            }
            
            return picking_data
        except Exception as e:
            self.logger.error(f"ピッキングリスト生成失敗: {e}")
            raise
    
    # ユーティリティメソッド
    def save_csv(self, data: List[Dict[str, Any]], file_path: str) -> bool:
        """CSVファイル保存"""
        try:
            df = pd.DataFrame(data)
            df.to_csv(file_path, index=False, encoding='utf-8')
            return True
        except Exception as e:
            self.logger.error(f"CSV保存失敗: {e}")
            return False
    
    def load_csv(self, file_path: str) -> Optional[pd.DataFrame]:
        """CSVファイル読み込み"""
        try:
            return pd.read_csv(file_path, encoding='utf-8')
        except Exception as e:
            self.logger.error(f"CSV読み込み失敗: {e}")
            return None
    
    def get_api_status(self) -> Dict[str, Any]:
        """API状態取得"""
        try:
            is_connected = self.test_connection()
            return {
                'connected': is_connected,
                'base_url': self.base_url,
                'status': 'online' if is_connected else 'offline'
            }
        except Exception as e:
            self.logger.error(f"API状態取得失敗: {e}")
            return {
                'connected': False,
                'base_url': self.base_url,
                'status': 'error',
                'error': str(e)
            }
    
    def close(self):
        """セッションのクローズ"""
        if self.session:
            self.session.close()


class APIClientManager:
    """APIクライアント管理"""
    
    def __init__(self):
        self.clients = {}
        self.default_client = None
    
    def get_client(self, base_url: str = "http://localhost:8000") -> APIClient:
        """APIクライアントの取得"""
        if base_url not in self.clients:
            self.clients[base_url] = APIClient(base_url)
            if self.default_client is None:
                self.default_client = self.clients[base_url]
        
        return self.clients[base_url]
    
    def get_default_client(self) -> APIClient:
        """デフォルトクライアントの取得"""
        if self.default_client is None:
            self.default_client = self.get_client()
        return self.default_client
    
    def close_all(self):
        """全クライアントのクローズ"""
        for client in self.clients.values():
            client.close()
        self.clients.clear()
        self.default_client = None


# グローバルインスタンス
api_manager = APIClientManager()
