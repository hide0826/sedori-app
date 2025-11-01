#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート照合処理サービス

仕入リストと店舗マスタ・ルートサマリーとの照合
- 仕入時間と店舗IN/OUT時間の照合
- 店舗毎粗利からの店舗特定
- 店舗コード自動挿入
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from desktop.database.store_db import StoreDatabase
from desktop.services.calculation_service import CalculationService


class RouteMatchingService:
    """ルート照合処理サービスクラス"""
    
    def __init__(self):
        self.store_db = StoreDatabase()
        self.calc_service = CalculationService()
    
    def match_store_code_by_time_and_profit(
        self,
        purchase_items: List[Dict[str, Any]],
        store_visits: List[Dict[str, Any]],
        time_tolerance_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """
        仕入リストアイテムと店舗訪問詳細を照合して店舗コードを自動挿入
        
        Args:
            purchase_items: 仕入リストアイテムリスト
            store_visits: 店舗訪問詳細リスト
            time_tolerance_minutes: 時間の許容誤差（分）
        
        Returns:
            照合結果リスト
        """
        results = []
        
        for item in purchase_items:
            result_item = item.copy()
            matched = False
            match_confidence = 0.0
            matched_store_code = None
            match_reason = ""
            
            # 仕入日の取得
            purchase_date = item.get('仕入れ日') or item.get('purchase_date')
            if isinstance(purchase_date, str):
                purchase_date = self.calc_service.parse_datetime_string(purchase_date)
            
            # 仕入価格（粗利計算に使用）
            purchase_price = self._safe_float(item.get('仕入れ価格') or item.get('purchase_price', 0))
            planned_price = self._safe_float(item.get('販売予定価格') or item.get('planned_price', 0))
            estimated_profit = planned_price - purchase_price if planned_price and purchase_price else None
            
            # 各店舗訪問と照合
            for visit in store_visits:
                store_code = visit.get('store_code')
                if not store_code:
                    continue
                
                # 店舗IN/OUT時間の取得
                in_time = visit.get('store_in_time')
                out_time = visit.get('store_out_time')
                
                if isinstance(in_time, str):
                    in_time = self.calc_service.parse_datetime_string(in_time)
                if isinstance(out_time, str):
                    out_time = self.calc_service.parse_datetime_string(out_time)
                
                # 照合スコア計算
                score, reason = self._calculate_match_score(
                    purchase_date,
                    purchase_price,
                    planned_price,
                    estimated_profit,
                    in_time,
                    out_time,
                    visit,
                    time_tolerance_minutes
                )
                
                # より高いスコアの照合を採用
                if score > match_confidence:
                    match_confidence = score
                    matched_store_code = store_code
                    match_reason = reason
                    matched = True
            
            # 照合結果を設定
            if matched and match_confidence >= 0.5:  # 閾値: 0.5以上
                result_item['matched_store_code'] = matched_store_code
                result_item['match_confidence'] = match_confidence
                result_item['match_reason'] = match_reason
                result_item['match_status'] = 'auto_matched'
            else:
                # 照合失敗時は候補を複数提示
                candidates = self._find_candidate_stores(
                    purchase_items=[item],
                    store_visits=store_visits,
                    time_tolerance_minutes=time_tolerance_minutes
                )
                result_item['matched_store_code'] = None
                result_item['match_confidence'] = match_confidence if matched else 0.0
                result_item['match_reason'] = match_reason if matched else '照合失敗'
                result_item['match_status'] = 'manual_review_required'
                result_item['candidate_store_codes'] = [c['store_code'] for c in candidates[:3]]  # 上位3候補
            
            results.append(result_item)
        
        return results
    
    def _calculate_match_score(
        self,
        purchase_date: Optional[datetime],
        purchase_price: Optional[float],
        planned_price: Optional[float],
        estimated_profit: Optional[float],
        store_in_time: Optional[datetime],
        store_out_time: Optional[datetime],
        visit: Dict[str, Any],
        time_tolerance_minutes: int
    ) -> Tuple[float, str]:
        """
        照合スコアを計算（0.0-1.0）
        
        Returns:
            (スコア, 理由)
        """
        score = 0.0
        reasons = []
        
        # 1. 時間照合（重要度: 0.5）
        if purchase_date and store_in_time and store_out_time:
            # 滞在時間内かチェック
            is_in_store_duration = store_in_time <= purchase_date <= store_out_time
            
            if is_in_store_duration:
                # 滞在時間内なら高スコア
                time_score = 0.5
                reasons.append(f"滞在時間内")
            else:
                # 滞在時間外の場合、マッチしない
                time_score = 0.0
        else:
            time_score = 0.0
        
        score += time_score
        
        # 2. 粗利照合（重要度: 0.3）
        store_gross_profit = self._safe_float(visit.get('store_gross_profit'))
        if estimated_profit and store_gross_profit:
            # 粗利の誤差が10%以内なら高スコア
            if store_gross_profit > 0:
                profit_diff_ratio = abs(estimated_profit - store_gross_profit) / store_gross_profit
                if profit_diff_ratio <= 0.1:
                    profit_score = 0.3
                    reasons.append("粗利一致（誤差10%以内）")
                elif profit_diff_ratio <= 0.3:
                    profit_score = 0.15
                    reasons.append(f"粗利近接（誤差{profit_diff_ratio * 100:.1f}%）")
                else:
                    profit_score = 0.0
            else:
                profit_score = 0.0
        else:
            profit_score = 0.0
        
        score += profit_score
        
        # 3. 仕入れ成功フラグ（重要度: 0.2）
        purchase_success = visit.get('purchase_success', False)
        if purchase_success:
            success_score = 0.2
            reasons.append("仕入れ成功")
        else:
            success_score = 0.0
        
        score += success_score
        
        reason_text = "; ".join(reasons) if reasons else "照合条件不足"
        
        return score, reason_text
    
    def _find_candidate_stores(
        self,
        purchase_items: List[Dict[str, Any]],
        store_visits: List[Dict[str, Any]],
        time_tolerance_minutes: int
    ) -> List[Dict[str, Any]]:
        """
        候補店舗を検索
        
        Returns:
            候補店舗リスト（スコア降順）
        """
        candidates = []
        
        for visit in store_visits:
            store_code = visit.get('store_code')
            if not store_code:
                continue
            
            # 簡易スコア計算
            score = 0.0
            
            # 仕入れ成功フラグ
            if visit.get('purchase_success', False):
                score += 0.5
            
            # 店舗評価
            store_rating = visit.get('store_rating')
            if store_rating:
                score += store_rating * 0.1
            
            candidates.append({
                'store_code': store_code,
                'score': score,
                'visit': visit
            })
        
        # スコア降順でソート
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        return candidates
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """安全にfloatに変換"""
        if value is None:
            return None
        try:
            if isinstance(value, str):
                # カンマ区切りや空白を除去
                value = value.replace(',', '').strip()
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def update_purchase_items_with_store_codes(
        self,
        purchase_dataframe,
        matched_results: List[Dict[str, Any]],
        store_code_column: str = '店舗コード'
    ):
        """
        仕入リストDataFrameに店舗コードを反映
        
        Args:
            purchase_dataframe: 仕入リストDataFrame
            matched_results: 照合結果リスト
            store_code_column: 店舗コード列名
        """
        import pandas as pd
        
        # 店舗コード列が存在しない場合は作成
        if store_code_column not in purchase_dataframe.columns:
            purchase_dataframe[store_code_column] = ''
        
        # 照合結果を反映
        for result in matched_results:
            matched_store_code = result.get('matched_store_code')
            if matched_store_code:
                # 該当する行を特定（ASINや商品名でマッチング）
                # 簡易実装: インデックスで対応（実際にはより精密なマッチングが必要）
                idx = matched_results.index(result)
                if idx < len(purchase_dataframe):
                    purchase_dataframe.at[purchase_dataframe.index[idx], store_code_column] = matched_store_code

