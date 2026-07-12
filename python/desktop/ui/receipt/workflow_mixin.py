#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ワークフロー表示・ボタン状態 mixin。"""
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


class ReceiptWorkflowMixin:
    def _reset_post_rename_workflow_gate(self) -> None:
        """ワークフロー初期化時: ⑦GCS / ⑧確定を無効化する。"""
        self._bulk_rename_completed = False
        self._gcs_upload_completed = False
        self._sync_post_rename_action_buttons()

    def _mark_bulk_rename_completed(self) -> None:
        """一括リネーム完了後に GCSアップロードを有効化（確定は GCS 完了後）。"""
        self._bulk_rename_completed = True
        self._gcs_upload_completed = False
        self._workflow_post_step = 6
        self._sync_post_rename_action_buttons()

    def _mark_gcs_upload_completed(self) -> None:
        """GCSアップロード完了後に 確定 を有効化する。"""
        self._gcs_upload_completed = True
        self._workflow_post_step = 8
        self._sync_post_rename_action_buttons()

    def _is_batch_ocr_busy(self) -> bool:
        """全件OCRの一括処理が実行中か"""
        return bool(getattr(self, "batch_running", False))

    def _sync_action_buttons_state(self) -> None:
        """ワークフローボタン群の有効/無効を同期（全件OCR中ロック + リネーム/GCSゲート）"""
        ocr_busy = self._is_batch_ocr_busy()
        ocr_busy_tip = "全件OCR実行中は使用できません。完了するまでお待ちください。"

        locked_during_ocr = (
            "folder_btn",
            "bulk_match_btn",
            "bulk_rename_btn",
            "verify_btn",
            "delete_all_btn",
            "default_folder_btn",
            "save_receipt_snapshot_btn",
            "load_receipt_snapshot_btn",
            "process_btn",
        )
        for attr in locked_during_ocr:
            btn = getattr(self, attr, None)
            if btn is None:
                continue
            btn.setEnabled(not ocr_busy)
            if ocr_busy:
                btn.setToolTip(ocr_busy_tip)

        if hasattr(self, "batch_btn") and self.batch_btn:
            self.batch_btn.setEnabled(not ocr_busy)
            if ocr_busy:
                self.batch_btn.setToolTip("全件OCRを実行中です…")

        for table_attr in ("receipt_table", "warranty_table"):
            table = getattr(self, table_attr, None)
            if table is not None:
                table.setEnabled(not ocr_busy)

        rename_done = bool(getattr(self, "_bulk_rename_completed", False))
        gcs_done = bool(getattr(self, "_gcs_upload_completed", False))
        rename_gate_tip = (
            "先に「一括リネーム」（⑤）を実行してください。"
            "リネーム前のファイル名のまま確定するとリンク切れの原因になります。"
        )
        gcs_gate_tip = (
            "先に「GCSアップロード」（⑦）を実行してください。"
            "GCS URL が仕入DBに反映される前に確定すると、レシート画像リンクが正しく保存されません。"
        )
        if hasattr(self, "gcs_upload_btn") and self.gcs_upload_btn:
            self.gcs_upload_btn.setEnabled(rename_done and not ocr_busy)
            if ocr_busy:
                self.gcs_upload_btn.setToolTip(ocr_busy_tip)
            else:
                self.gcs_upload_btn.setToolTip(
                    "レシート一覧の全件をGCSにアップロードします"
                    if rename_done
                    else rename_gate_tip
                )
        if hasattr(self, "confirm_btn") and self.confirm_btn:
            in_progress = bool(getattr(self, "_confirm_in_progress", False))
            confirm_enabled = rename_done and gcs_done and not in_progress and not ocr_busy
            self.confirm_btn.setEnabled(confirm_enabled)
            if ocr_busy:
                self.confirm_btn.setToolTip(ocr_busy_tip)
            elif rename_done and gcs_done:
                self.confirm_btn.setToolTip("レシートと仕入DBの紐付けを確定します")
            elif rename_done:
                self.confirm_btn.setToolTip(gcs_gate_tip)
            else:
                self.confirm_btn.setToolTip(rename_gate_tip)

        if not ocr_busy and hasattr(self, "delete_row_btn") and self.delete_row_btn:
            has_selection = False
            if hasattr(self, "receipt_table") and self.receipt_table:
                has_selection = len(self.receipt_table.selectedItems()) > 0
            self.delete_row_btn.setEnabled(has_selection)

    def _sync_post_rename_action_buttons(self) -> None:
        """⑦GCS / ⑧確定ボタンの有効状態とツールチップを同期。"""
        self._sync_action_buttons_state()

    def _require_bulk_rename_before_post_actions(self, action_label: str) -> bool:
        """GCS / 確定の前に一括リネーム済みか確認。未完了なら False。"""
        if getattr(self, "_bulk_rename_completed", False):
            return True
        QMessageBox.information(
            self,
            action_label,
            "「一括リネーム」（⑤）を実行してから "
            f"「{action_label}」を行ってください。\n\n"
            "リネーム前に GCS アップロードや確定を行うと、"
            "仕入DBのレシート画像リンクが古いファイル名のまま残り、"
            "リンク切れの原因になります。",
        )
        return False

    def _require_gcs_upload_before_confirm(self) -> bool:
        """確定の前に GCSアップロード済みか確認。未完了なら False。"""
        if getattr(self, "_gcs_upload_completed", False):
            return True
        QMessageBox.information(
            self,
            "確定",
            "「GCSアップロード」（⑦）を実行してから「確定」を行ってください。\n\n"
            "GCS URL が仕入DBに反映される前に確定すると、"
            "レシート画像のリンクが正しく保存されません。",
        )
        return False

    def _sync_workflow_status_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑧ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_receipt_status_prefix_html(text, emph)
        pipe = _format_receipt_workflow_pipeline_html(step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)

    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """ワークフロー状態ラベルを更新"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "手動調整" in text:
            self._workflow_active_step = 4
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_status_label()

    def _run_action_with_status(self, action_name: str, action_func):
        """押したボタン名をワークフロー表示に反映してから処理を実行"""
        if action_name != "全件OCR" and self._is_batch_ocr_busy():
            QMessageBox.information(
                self,
                action_name,
                "「全件OCR」実行中は他の操作を行えません。\n"
                "OCRが完了するまでお待ちください。",
            )
            return
        step = _RECEIPT_ACTION_TO_PIPELINE_STEP.get(action_name)
        self._workflow_post_step = None
        try:
            if step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            post_step = getattr(self, "_workflow_post_step", None)
            if post_step is not None:
                self._workflow_active_step = post_step
                self._workflow_post_step = None
            elif step is not None and not self._is_batch_ocr_busy():
                self._workflow_active_step = step
            if not self._is_batch_ocr_busy():
                self._update_workflow_status("ワークフロー: 待機", emphasize=False)
    
