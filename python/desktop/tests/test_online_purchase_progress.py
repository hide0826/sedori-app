#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

_desktop = Path(__file__).resolve().parents[1]
if str(_desktop) not in sys.path:
    sys.path.insert(0, str(_desktop))

from database.route_db import RouteDatabase
from services.online_purchase_progress import (
    box_has_listing_csv,
    ensure_online_listing_summary,
    sync_online_listing_flags,
)
from services.top_dashboard_service import TopDashboardService, pending_labels_for_route
from utils.route_utils import parse_trailing_date_folder_name


class _DummyStore:
    def get_route_name_by_code(self, code: str) -> str:
        return ""


def test_trailing_date_folder_is_online_box_not_store_route():
    assert parse_trailing_date_folder_name("フリマ20261001") == (
        "2026-10-01",
        "フリマ20261001",
    )
    assert parse_trailing_date_folder_name("20261001つくばルート") is None


def test_online_pending_is_only_images_after_listing_csv():
    assert pending_labels_for_route(
        {
            "route_code": "NET",
            "listing_completed": 1,
            "evidence_completed": 0,
            "images_completed": 0,
        }
    ) == ["画像"]
    assert pending_labels_for_route(
        {
            "route_code": "NET",
            "listing_completed": 0,
            "images_completed": 0,
        }
    ) == []
    assert pending_labels_for_route(
        {
            "route_code": "NET",
            "listing_completed": 1,
            "images_completed": 1,
        }
    ) == []
    assert pending_labels_for_route(
        {
            "route_code": "R001",
            "listing_completed": 1,
            "evidence_completed": 0,
            "images_completed": 0,
        }
    ) == ["証憑", "画像"]


def test_listing_csv_box_shows_on_top(tmp_path: Path):
    root = tmp_path / "ネット仕入れリスト"
    box = root / "フリマ20261007"
    csv_dir = box / "仕入CSV"
    csv_dir.mkdir(parents=True)
    (csv_dir / "20261007_出品用CSV.csv").write_text("sku\n", encoding="utf-8")
    (box / "商品画像").mkdir()
    assert box_has_listing_csv(box) is True

    db = RouteDatabase(str(tmp_path / "hirio.db"))
    assert sync_online_listing_flags(db, [root]) == 1
    # 2回目は同じ箱を更新するだけ
    assert ensure_online_listing_summary(db, box) is not None

    service = TopDashboardService(route_db=db, store_db=_DummyStore())
    service._online_roots = lambda: []  # type: ignore[method-assign]
    tasks = service.get_pending_tasks()
    assert len(tasks) == 1
    assert tasks[0]["route_date"] == "2026-10-07"
    assert tasks[0]["route_name"] == "ネット仕入 フリマ20261007"
    assert tasks[0]["pending_labels"] == ["画像"]

    route_id = tasks[0]["route_id"]
    db.set_route_flag(int(route_id), "images_completed", True)
    assert service.get_pending_tasks() == []
    if db.conn is not None:
        db.conn.close()
        db.conn = None
