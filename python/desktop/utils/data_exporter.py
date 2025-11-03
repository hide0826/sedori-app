#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データエクスポートユーティリティ

ルートサマリー・店舗訪問詳細・仕入リストのデータエクスポート
- CSV形式エクスポート
- Excel形式エクスポート
- 期間指定エクスポート
- Looker Studio連携用フォーマット
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import json


class DataExporter:
    """データエクスポートクラス"""
    
    @staticmethod
    def export_route_summaries(
        routes: List[Dict[str, Any]],
        output_path: str,
        format: str = 'csv'
    ) -> bool:
        """
        ルートサマリーをエクスポート
        
        Args:
            routes: ルートサマリーリスト
            output_path: 出力ファイルパス
            format: 出力形式（'csv' または 'excel'）
        
        Returns:
            エクスポート成功時True
        """
        try:
            # DataFrameに変換
            df = pd.DataFrame(routes)
            
            # 列順序を整理
            columns = [
                'id', 'route_date', 'route_code', 'departure_time', 'return_time',
                'toll_fee_outbound', 'toll_fee_return', 'parking_fee',
                'meal_cost', 'other_expenses', 'remarks',
                'total_working_hours', 'estimated_hourly_rate',
                'total_gross_profit', 'purchase_success_rate', 'avg_purchase_price',
                'created_at', 'updated_at'
            ]
            
            # 存在する列のみ選択
            available_columns = [col for col in columns if col in df.columns]
            df = df[available_columns]
            
            if format.lower() == 'excel':
                df.to_excel(output_path, index=False, engine='openpyxl')
            else:
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(output_path))
                df.to_csv(str(target), index=False, encoding='utf-8-sig')
            
            return True
            
        except Exception as e:
            print(f"ルートサマリーエクスポートエラー: {e}")
            return False
    
    @staticmethod
    def export_store_visits(
        visits: List[Dict[str, Any]],
        output_path: str,
        format: str = 'csv'
    ) -> bool:
        """
        店舗訪問詳細をエクスポート
        
        Args:
            visits: 店舗訪問詳細リスト
            output_path: 出力ファイルパス
            format: 出力形式（'csv' または 'excel'）
        
        Returns:
            エクスポート成功時True
        """
        try:
            # category_breakdownをJSON文字列に変換（エクスポート時）
            export_visits = []
            for visit in visits:
                export_visit = visit.copy()
                if 'category_breakdown' in export_visit and isinstance(export_visit['category_breakdown'], dict):
                    export_visit['category_breakdown'] = json.dumps(export_visit['category_breakdown'], ensure_ascii=False)
                export_visits.append(export_visit)
            
            # DataFrameに変換
            df = pd.DataFrame(export_visits)
            
            # 列順序を整理
            columns = [
                'id', 'route_summary_id', 'store_code', 'visit_order',
                'store_in_time', 'store_out_time', 'stay_duration',
                'travel_time_from_prev', 'distance_from_prev',
                'store_gross_profit', 'store_item_count',
                'purchase_success', 'no_purchase_reason',
                'store_rating', 'store_notes', 'next_visit_recommendation',
                'category_breakdown', 'competitor_present',
                'inventory_level', 'trouble_occurred', 'trouble_details',
                'created_at', 'updated_at'
            ]
            
            # 存在する列のみ選択
            available_columns = [col for col in columns if col in df.columns]
            df = df[available_columns]
            
            if format.lower() == 'excel':
                df.to_excel(output_path, index=False, engine='openpyxl')
            else:
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(output_path))
                df.to_csv(str(target), index=False, encoding='utf-8-sig')
            
            return True
            
        except Exception as e:
            print(f"店舗訪問詳細エクスポートエラー: {e}")
            return False
    
    @staticmethod
    def export_for_looker_studio(
        routes: List[Dict[str, Any]],
        visits: List[Dict[str, Any]],
        output_path: str
    ) -> bool:
        """
        Looker Studio連携用フォーマットでエクスポート
        
        Args:
            routes: ルートサマリーリスト
            visits: 店舗訪問詳細リスト
            output_path: 出力ファイルパス
        
        Returns:
            エクスポート成功時True
        """
        try:
            # ルートサマリーと店舗訪問詳細を結合
            combined_data = []
            
            for route in routes:
                route_id = route.get('id')
                route_visits = [v for v in visits if v.get('route_summary_id') == route_id]
                
                for visit in route_visits:
                    row = {
                        # ルート情報
                        'route_id': route.get('id'),
                        'route_date': route.get('route_date'),
                        'route_code': route.get('route_code'),
                        'departure_time': route.get('departure_time'),
                        'return_time': route.get('return_time'),
                        'total_working_hours': route.get('total_working_hours'),
                        'estimated_hourly_rate': route.get('estimated_hourly_rate'),
                        'total_gross_profit': route.get('total_gross_profit'),
                        
                        # 店舗訪問情報
                        'store_code': visit.get('store_code'),
                        'visit_order': visit.get('visit_order'),
                        'store_in_time': visit.get('store_in_time'),
                        'store_out_time': visit.get('store_out_time'),
                        'stay_duration': visit.get('stay_duration'),
                        'store_gross_profit': visit.get('store_gross_profit'),
                        'store_item_count': visit.get('store_item_count'),
                        'purchase_success': visit.get('purchase_success'),
                        'store_rating': visit.get('store_rating')
                    }
                    combined_data.append(row)
            
            # DataFrameに変換
            df = pd.DataFrame(combined_data)
            
            # CSV形式で出力（UTF-8 BOM付き、Google Sheets対応）
            from pathlib import Path
            from desktop.utils.file_naming import resolve_unique_path
            target = resolve_unique_path(Path(output_path))
            df.to_csv(str(target), index=False, encoding='utf-8-sig')
            
            return True
            
        except Exception as e:
            print(f"Looker Studio用エクスポートエラー: {e}")
            return False
    
    @staticmethod
    def export_all_data(
        routes: List[Dict[str, Any]],
        visits: List[Dict[str, Any]],
        output_dir: str,
        format: str = 'csv'
    ) -> bool:
        """
        全データを一括エクスポート
        
        Args:
            routes: ルートサマリーリスト
            visits: 店舗訪問詳細リスト
            output_dir: 出力ディレクトリ
            format: 出力形式（'csv' または 'excel'）
        
        Returns:
            エクスポート成功時True
        """
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # ルートサマリー
            route_file = output_path / f'route_summaries_{timestamp}.{format}'
            DataExporter.export_route_summaries(routes, str(route_file), format)
            
            # 店舗訪問詳細
            visit_file = output_path / f'store_visits_{timestamp}.{format}'
            DataExporter.export_store_visits(visits, str(visit_file), format)
            
            # Looker Studio用
            looker_file = output_path / f'looker_studio_data_{timestamp}.csv'
            DataExporter.export_for_looker_studio(routes, visits, str(looker_file))
            
            return True
            
        except Exception as e:
            print(f"一括エクスポートエラー: {e}")
            return False

