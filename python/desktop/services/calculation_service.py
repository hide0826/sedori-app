#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
計算処理サービス

ルートサマリー関連の各種計算処理
- 滞在時間計算
- 実働時間計算
- 時給計算
- 仕入れ成功率計算
- 平均仕入れ単価計算
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import math


class CalculationService:
    """計算処理サービスクラス"""
    
    @staticmethod
    def calculate_stay_duration(in_time: Optional[datetime], out_time: Optional[datetime]) -> Optional[float]:
        """
        滞在時間を計算（時間単位）
        
        Args:
            in_time: 入店時間
            out_time: 退店時間
        
        Returns:
            滞在時間（時間）、計算できない場合はNone
        """
        if not in_time or not out_time:
            return None
        
        if out_time < in_time:
            return None  # 時間の逆転はエラー
        
        duration = out_time - in_time
        return duration.total_seconds() / 3600.0  # 時間単位
    
    @staticmethod
    def calculate_total_working_hours(departure_time: Optional[datetime], return_time: Optional[datetime]) -> Optional[float]:
        """
        実働時間を計算（時間単位）
        
        Args:
            departure_time: 出発時間
            return_time: 帰宅時間
        
        Returns:
            実働時間（時間）、計算できない場合はNone
        """
        if not departure_time or not return_time:
            return None
        
        if return_time < departure_time:
            return None  # 時間の逆転はエラー
        
        duration = return_time - departure_time
        return duration.total_seconds() / 3600.0  # 時間単位
    
    @staticmethod
    def calculate_hourly_rate(total_gross_profit: Optional[float], total_working_hours: Optional[float]) -> Optional[float]:
        """
        時給を計算
        
        Args:
            total_gross_profit: 総粗利
            total_working_hours: 実働時間（時間）
        
        Returns:
            時給（円/時間）、計算できない場合はNone
        """
        if total_gross_profit is None or total_working_hours is None:
            return None
        
        if total_working_hours <= 0:
            return None
        
        return total_gross_profit / total_working_hours
    
    @staticmethod
    def calculate_purchase_success_rate(store_visits: List[Dict[str, Any]]) -> Optional[float]:
        """
        仕入れ成功率を計算
        
        Args:
            store_visits: 店舗訪問詳細リスト
        
        Returns:
            仕入れ成功率（0.0-1.0）、計算できない場合はNone
        """
        if not store_visits:
            return None
        
        success_count = sum(1 for visit in store_visits if visit.get('purchase_success', False))
        total_count = len(store_visits)
        
        if total_count == 0:
            return None
        
        return success_count / total_count
    
    @staticmethod
    def calculate_avg_purchase_price(total_gross_profit: Optional[float], total_item_count: Optional[int]) -> Optional[float]:
        """
        平均仕入れ単価を計算
        
        Args:
            total_gross_profit: 総粗利
            total_item_count: 仕入れ総点数
        
        Returns:
            平均仕入れ単価（円/点）、計算できない場合はNone
        """
        if total_gross_profit is None or total_item_count is None:
            return None
        
        if total_item_count <= 0:
            return None
        
        return total_gross_profit / total_item_count
    
    @staticmethod
    def calculate_route_statistics(route_data: Dict[str, Any], store_visits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        ルート統計情報を一括計算
        
        Args:
            route_data: ルートサマリーデータ
            store_visits: 店舗訪問詳細リスト
        
        Returns:
            計算結果の辞書
        """
        # 日時文字列をdatetimeオブジェクトに変換
        departure_time = None
        return_time = None
        if route_data.get('departure_time'):
            if isinstance(route_data['departure_time'], str):
                try:
                    departure_time = datetime.fromisoformat(route_data['departure_time'].replace('Z', '+00:00'))
                except:
                    pass
        
        if route_data.get('return_time'):
            if isinstance(route_data['return_time'], str):
                try:
                    return_time = datetime.fromisoformat(route_data['return_time'].replace('Z', '+00:00'))
                except:
                    pass
        
        # 実働時間計算
        total_working_hours = CalculationService.calculate_total_working_hours(departure_time, return_time)
        
        # 総粗利計算（店舗毎粗利の合計）
        total_gross_profit = sum(
            visit.get('store_gross_profit', 0) or 0
            for visit in store_visits
            if visit.get('store_gross_profit')
        )
        
        # 総仕入れ点数計算
        total_item_count = sum(
            visit.get('store_item_count', 0) or 0
            for visit in store_visits
            if visit.get('store_item_count')
        )
        
        # 時給計算
        estimated_hourly_rate = CalculationService.calculate_hourly_rate(total_gross_profit, total_working_hours)
        
        # 仕入れ成功率計算
        purchase_success_rate = CalculationService.calculate_purchase_success_rate(store_visits)
        
        # 平均仕入れ単価計算
        avg_purchase_price = CalculationService.calculate_avg_purchase_price(total_gross_profit, total_item_count)
        
        # 各店舗の滞在時間を計算
        for visit in store_visits:
            in_time = None
            out_time = None
            
            if visit.get('store_in_time'):
                if isinstance(visit['store_in_time'], str):
                    try:
                        in_time = datetime.fromisoformat(visit['store_in_time'].replace('Z', '+00:00'))
                    except:
                        pass
            
            if visit.get('store_out_time'):
                if isinstance(visit['store_out_time'], str):
                    try:
                        out_time = datetime.fromisoformat(visit['store_out_time'].replace('Z', '+00:00'))
                    except:
                        pass
            
            stay_duration = CalculationService.calculate_stay_duration(in_time, out_time)
            visit['calculated_stay_duration'] = stay_duration
        
        return {
            'total_working_hours': total_working_hours,
            'total_gross_profit': total_gross_profit,
            'total_item_count': total_item_count,
            'estimated_hourly_rate': estimated_hourly_rate,
            'purchase_success_rate': purchase_success_rate,
            'avg_purchase_price': avg_purchase_price
        }
    
    @staticmethod
    def parse_datetime_string(datetime_str: str) -> Optional[datetime]:
        """
        日時文字列をパース
        
        Args:
            datetime_str: 日時文字列（様々な形式に対応）
        
        Returns:
            datetimeオブジェクト、パースできない場合はNone
        """
        if not datetime_str or not isinstance(datetime_str, str):
            return None
        
        # 様々な形式を試行
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M',
            '%Y-%m-%d',
            '%Y/%m/%d'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(datetime_str.strip(), fmt)
            except ValueError:
                continue
        
        # ISO形式も試行
        try:
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except ValueError:
            pass
        
        return None

