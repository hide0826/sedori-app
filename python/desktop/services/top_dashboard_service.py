#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOPダッシュボード用データ取得サービス

ルートサマリー・登録ルートから未完了タスク・前回ルート・次回候補を集計する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase

FLAG_LABELS = {
    "listing_completed": "出品",
    "evidence_completed": "証憑",
    "images_completed": "画像",
}


class TopDashboardService:
    """TOP画面表示用のデータをDBから集計する"""

    def __init__(
        self,
        route_db: Optional[RouteDatabase] = None,
        store_db: Optional[StoreDatabase] = None,
    ):
        self.route_db = route_db or RouteDatabase()
        self.store_db = store_db or StoreDatabase()

    def _resolve_route_name(self, route: Dict[str, Any]) -> str:
        route_code = route.get("route_code", "") or ""
        display = route.get("route_display_name")
        if display:
            return str(display)
        if route_code:
            name = self.store_db.get_route_name_by_code(route_code)
            if name:
                return name
            return route_code
        return ""

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """チェック未完了のタスク（出品・証憑・画像）をルートごとに返す"""
        routes = self.route_db.list_route_summaries()
        tasks: List[Dict[str, Any]] = []
        for route in routes:
            pending = [
                label
                for key, label in FLAG_LABELS.items()
                if not bool(route.get(key) or 0)
            ]
            if not pending:
                continue
            tasks.append(
                {
                    "route_id": route.get("id"),
                    "route_date": route.get("route_date", "") or "",
                    "route_name": self._resolve_route_name(route),
                    "pending_labels": pending,
                }
            )
        return tasks

    def get_last_route(self) -> Optional[Dict[str, str]]:
        """直近のルートサマリー1件"""
        routes = self.route_db.list_route_summaries()
        if not routes:
            return None
        route = routes[0]
        return {
            "route_date": route.get("route_date", "") or "",
            "route_name": self._resolve_route_name(route),
            "route_id": route.get("id"),
        }

    def get_next_route_candidates(self, limit: int = 3) -> List[Dict[str, Any]]:
        """
        登録ルートのうち、最終巡回日が最も古い順に候補を返す。
        一度も巡回していないルートは最優先。
        """
        registered = self.store_db.list_routes_with_store_count()
        summaries = self.route_db.list_route_summaries()

        last_visit: Dict[str, str] = {}
        for summary in summaries:
            code = (summary.get("route_code") or "").strip()
            date = (summary.get("route_date") or "").strip()
            if not code or not date:
                continue
            if code not in last_visit or date > last_visit[code]:
                last_visit[code] = date

        candidates: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()
        for route in registered:
            code = (route.get("route_code") or "").strip()
            name = (route.get("route_name") or "").strip()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            candidates.append(
                {
                    "route_code": code,
                    "route_name": name or code,
                    "last_visit_date": last_visit.get(code),
                }
            )

        def _sort_key(item: Dict[str, Any]) -> tuple:
            last = item.get("last_visit_date")
            if not last:
                return ("", item.get("route_name") or "")
            return (last, item.get("route_name") or "")

        candidates.sort(key=_sort_key)
        return candidates[:limit]

    def build_dashboard_data(self) -> Dict[str, Any]:
        """TOP画面用のデータをまとめて返す"""
        return {
            "pending_tasks": self.get_pending_tasks(),
            "last_route": self.get_last_route(),
            "next_route_candidates": self.get_next_route_candidates(),
        }
