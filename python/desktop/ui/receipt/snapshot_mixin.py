#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スナップショット保存・読込 mixin。"""
from __future__ import annotations

import os
import re
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication, QCheckBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

try:
    from services.receipt_service import ReceiptService
    from services.receipt_matching_service import ReceiptMatchingService
    from services.purchase_break_even import compute_break_even_for_record
    from services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
except Exception:
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
    from desktop.services.purchase_break_even import compute_break_even_for_record
    from desktop.services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from desktop.services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase
from database.route_db import RouteDatabase

from .support import (
    ReceiptOCRThread,
    ReceiptSnapshotDialog,
    _RECEIPT_ACTION_TO_PIPELINE_STEP,
    _RECEIPT_WORKFLOW_PIPELINE_SEGMENTS,
    _format_receipt_status_prefix_html,
    _format_receipt_workflow_pipeline_html,
    AccountTitleDelegate,
    StoreNameDelegate,
    WarrantyProductDelegate,
)


class ReceiptSnapshotMixin:
    def save_receipt_snapshot(self):
        """現在のレシート一覧をJSONファイルにスナップ保存（最大50件まで保存）"""
        if not self.receipt_snapshot_dir:
            QMessageBox.warning(self, "スナップ保存", "スナップショット保存先ディレクトリを初期化できませんでした。")
            return

        # 現在のレシート一覧・保証書一覧に対応するレシートのみ取得
        try:
            receipts = self._get_current_receipts_from_tables()
        except Exception as e:
            QMessageBox.critical(self, "スナップ保存エラー", f"レシート一覧の取得に失敗しました:\n{e}")
            return

        if not receipts:
            QMessageBox.information(self, "スナップ保存", "保存するレシートデータがありません（現在の一覧が空です）。")
            return

        try:
            # レシート一覧から日付を取得（最も多い日付を使用）
            receipt_dates = {}
            for receipt in receipts:
                purchase_date = receipt.get('purchase_date', '')
                if purchase_date:
                    # 日付を正規化（yyyy-MM-dd形式に統一）
                    date_str = str(purchase_date).strip()
                    # 時刻部分を除去
                    if ' ' in date_str:
                        date_str = date_str.split(' ')[0]
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]
                    # スラッシュをハイフンに変換
                    date_str = date_str.replace('/', '-')
                    # yyyy-MM-dd形式に統一
                    try:
                        from datetime import datetime
                        date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
                        normalized_date = date_obj.strftime("%Y-%m-%d")
                        receipt_dates[normalized_date] = receipt_dates.get(normalized_date, 0) + 1
                    except Exception:
                        pass
            
            # 最も多い日付を取得
            route_date = ""
            route_name = ""
            
            if receipt_dates:
                # 最も多い日付を取得
                most_common_date = max(receipt_dates.items(), key=lambda x: x[1])[0]
                route_date = most_common_date
                
                # その日付でルートサマリーを検索
                route_summaries = self.route_db.list_route_summaries(
                    start_date=route_date,
                    end_date=route_date
                )
                
                if route_summaries:
                    # 該当日付のルートサマリーが見つかった場合、最初のものを使用
                    matched_route = route_summaries[0]
                    route_code = matched_route.get("route_code", "")
                    
                    # ルートコードからルート名を取得
                    if route_code:
                        route_name = self.store_db.get_route_name_by_code(route_code) or route_code
                    else:
                        route_name = "未設定"
                else:
                    # ルートサマリーが見つからない場合
                    route_name = "未設定"
            else:
                # レシートに日付がない場合、最新のルートサマリーを使用（フォールバック）
                route_summaries = self.route_db.list_route_summaries()
                if route_summaries:
                    latest_route = route_summaries[0]
                    route_date = latest_route.get("route_date", "")
                    route_code = latest_route.get("route_code", "")
                    if route_code:
                        route_name = self.store_db.get_route_name_by_code(route_code) or route_code
                    else:
                        route_name = "未設定"
                else:
                    route_date = datetime.now().strftime("%Y-%m-%d")
                    route_name = "未設定"
            
            # ファイル名に使えない文字を置換
            safe_route_name = route_name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_").replace("?", "_").replace("\"", "_").replace("<", "_").replace(">", "_").replace("|", "_")
            
            # 日付-ルート名の形式でファイル名を生成
            if route_date:
                filename = f"{route_date}-{safe_route_name}.json"
            else:
                filename = f"{datetime.now().strftime('%Y-%m-%d')}-{safe_route_name}.json"
            
            snapshot_path = self.receipt_snapshot_dir / filename
            
            # ディレクトリが存在することを確認
            self.receipt_snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            # 最大50件まで保存（古いファイルを削除）
            existing_files = sorted(self.receipt_snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if len(existing_files) >= 50:
                # 古いファイルを削除（最新50件を保持）
                for old_file in existing_files[49:]:
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
            
            payload = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "route_date": route_date,
                "route_name": route_name,
                "record_count": len(receipts),
                "receipts": receipts,
            }
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "スナップ保存",
                f"レシート一覧をスナップ保存しました。\n"
                f"ファイル: {filename}\n"
                f"ルート: {route_name}\n"
                f"件数: {len(receipts)}件",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップ保存エラー", f"スナップ保存に失敗しました:\n{e}")

    def load_receipt_snapshot(self):
        """保存されたレシート一覧スナップショットを読み込んでDBに復元"""
        if not self.receipt_snapshot_dir:
            QMessageBox.warning(self, "スナップ読込", "スナップショット保存先ディレクトリを初期化できませんでした。")
            return

        if not self.receipt_snapshot_dir.exists():
            QMessageBox.information(
                self,
                "スナップ読込",
                "スナップショットディレクトリが見つかりませんでした。\n"
                "先に「スナップ保存」を実行してください。",
            )
            return

        # スナップショットファイル一覧を取得
        snapshot_files = sorted(self.receipt_snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not snapshot_files:
            QMessageBox.information(
                self,
                "スナップ読込",
                "スナップショットファイルが見つかりませんでした。\n"
                "先に「スナップ保存」を実行してください。",
            )
            return

        # カスタムダイアログを使用
        dlg = ReceiptSnapshotDialog(self.receipt_snapshot_dir, self)
        res = dlg.exec()
        if res == QDialog.Accepted:
            file_path = dlg.get_selected_file_path()
            if not file_path:
                return
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)

                receipts = payload.get("receipts", [])
                if not isinstance(receipts, list):
                    raise ValueError("receipts フィールドの形式が不正です。")

                # 既存のレシートデータを削除してから、スナップショットの内容を挿入
                try:
                    self.receipt_db.delete_all_receipts()
                except Exception:
                    # 一括削除が実装されていない場合は、そのまま上書き保存にフォールバック
                    pass

                for rec in receipts:
                    # IDは新しく振り直す（重複防止）
                    rec_id = rec.pop("id", None)
                    try:
                        new_id = self.receipt_db.insert_receipt(rec)
                        rec["id"] = new_id
                    except Exception:
                        continue

                # UIを再読込
                self.refresh_receipt_list()

                saved_at = payload.get("saved_at", "不明な日時")
                route_name = payload.get("route_name", "不明")
                route_date = payload.get("route_date", "不明")
                QMessageBox.information(
                    self,
                    "スナップ読込",
                    f"レシート一覧スナップショットを読み込みました。\n"
                    f"保存日時: {saved_at}\n"
                    f"ルート: {route_name}\n"
                    f"日付: {route_date}\n"
                    f"件数: {len(receipts)}件",
                )
            except Exception as e:
                QMessageBox.critical(self, "スナップ読込エラー", f"スナップ読込に失敗しました:\n{e}")
    
