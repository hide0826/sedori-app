#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SP-API 価格改定タブ用の定数・ワーカー。"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QTableWidgetItem

_SP_API_WORKFLOW_PIPELINE_SEGMENTS = [
    "①SP-API取得",
    "②価格改定プレビュー",
    "③価格確認（目視）",
    "④価格改定実行",
    "⑤Amazonへ価格反映",
]
_SP_API_WORKFLOW_PIPELINE_SEP = "\u2010"
_SP_API_ACTION_TO_PIPELINE_STEP = {
    "SP-API取得": 1,
    "価格改定プレビュー": 2,
    "価格改定実行": 4,
    "Amazonへ価格反映": 5,
    "結果をCSV保存": 5,
}


def _format_status_prefix_html(text: str, emphasize: bool) -> str:
    if not emphasize:
        return f'<span style="color:#cccccc;">{escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{escape(text)}</span>'


def _format_workflow_pipeline_html(active_step: Optional[int]) -> str:
    parts: List[str] = []
    for i, seg in enumerate(_SP_API_WORKFLOW_PIPELINE_SEGMENTS, start=1):
        esc = escape(seg)
        if active_step == i:
            parts.append(f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>')
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _SP_API_WORKFLOW_PIPELINE_SEP.join(parts)


class NumericTableWidgetItem(QTableWidgetItem):
    def __init__(self, value):
        super().__init__()
        try:
            self.numeric_value = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            self.numeric_value = 0.0

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class InventoryFetchWorker(QThread):
    """出品一覧レポート取得ワーカー。"""

    progress_message = Signal(str)
    result_ready = Signal(object, str)  # df, csv_path
    error_occurred = Signal(str)

    def run(self):
        try:
            try:
                from services.sp_api_inventory import fetch_listings_dataframe_for_repricer
            except ImportError:
                from desktop.services.sp_api_inventory import (  # type: ignore
                    fetch_listings_dataframe_for_repricer,
                )

            def _prog(msg: str) -> None:
                self.progress_message.emit(msg)

            df, csv_path, err = fetch_listings_dataframe_for_repricer(on_progress=_prog)
            if err:
                self.error_occurred.emit(err)
                return
            self.result_ready.emit(df, csv_path)
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))


class RepriceCalcWorker(QThread):
    """既存 FastAPI /repricer/preview|apply 呼び出し。"""

    progress_updated = Signal(int)
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, csv_path: str, api_client, *, is_preview: bool = True, mode: str = "369"):
        super().__init__()
        self.csv_path = csv_path
        self.api_client = api_client
        self.is_preview = is_preview
        self.mode = mode

    def run(self):
        try:
            self.progress_updated.emit(10)
            if not self.api_client.test_connection():
                raise RuntimeError(
                    "FastAPIサーバーに接続できません。サーバーが起動しているか確認してください。"
                )
            self.progress_updated.emit(20)
            if self.is_preview:
                result = self.api_client.repricer_preview(self.csv_path, mode=self.mode)
            else:
                result = self.api_client.repricer_apply(self.csv_path, mode=self.mode)
            self.progress_updated.emit(100)
            self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))


class AmazonPatchWorker(QThread):
    """Listings PATCH 一括反映ワーカー。"""

    progress_message = Signal(str)
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, targets: List[Dict[str, Any]], *, max_items: Optional[int] = None):
        super().__init__()
        self.targets = targets
        self.max_items = max_items

    def run(self):
        try:
            try:
                from services.sp_api_reprice import apply_price_patches
            except ImportError:
                from desktop.services.sp_api_reprice import apply_price_patches  # type: ignore

            def _prog(msg: str) -> None:
                self.progress_message.emit(msg)

            result = apply_price_patches(
                self.targets,
                on_progress=_prog,
                max_items=self.max_items,
            )
            self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))


class FollowRepriceWorker(QThread):
    """同コンディション最安追従（取得→計算→任意で PATCH）。"""

    progress_message = Signal(str)
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(
        self,
        listings_rows: Optional[List[Dict[str, Any]]] = None,
        *,
        apply_amazon: bool = False,
        chase_yen: int = 100,
        early_days: int = 150,
        runs_per_day: int = 3,
        max_listings: Optional[int] = None,
        patch_max_items: Optional[int] = None,
    ):
        super().__init__()
        self.listings_rows = list(listings_rows or [])
        self.apply_amazon = apply_amazon
        self.chase_yen = chase_yen
        self.early_days = early_days
        self.runs_per_day = runs_per_day
        self.max_listings = max_listings
        self.patch_max_items = patch_max_items

    def run(self):
        try:
            try:
                from services.sp_api_follow_reprice import run_follow_repricer
            except ImportError:
                from desktop.services.sp_api_follow_reprice import run_follow_repricer  # type: ignore

            rows = self.listings_rows
            if not rows:
                try:
                    from services.sp_api_inventory import fetch_listings_dataframe_for_repricer
                except ImportError:
                    from desktop.services.sp_api_inventory import (  # type: ignore
                        fetch_listings_dataframe_for_repricer,
                    )

                def _prog(msg: str) -> None:
                    self.progress_message.emit(msg)

                df, _csv_path, err = fetch_listings_dataframe_for_repricer(on_progress=_prog)
                if err:
                    self.error_occurred.emit(err)
                    return
                rows = df.to_dict(orient="records")

            def _prog2(msg: str) -> None:
                self.progress_message.emit(msg)

            result = run_follow_repricer(
                rows,
                apply_amazon=self.apply_amazon,
                chase_yen=self.chase_yen,
                early_days=self.early_days,
                runs_per_day=self.runs_per_day,
                max_listings=self.max_listings,
                patch_max_items=self.patch_max_items,
                on_progress=_prog2,
            )
            self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))
