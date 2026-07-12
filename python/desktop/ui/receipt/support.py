#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシート管理ウィジェット

- 画像アップロード
- OCR結果表示
- マッチング候補表示・修正
- 学習機能
"""
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

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

# ui/receipt/ から desktop/ を import パス先頭へ
_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

# デスクトップ側servicesを優先して読み込む
try:
    from services.receipt_service import ReceiptService  # python/desktop/services
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
    # 明示的パス指定のフォールバック
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

# GCSアップロード機能（画像管理タブと同じ動的インポート方式を使用）
# モジュールレベルではインポートせず、使用時に動的にインポートする
upload_image_to_gcs = None
check_gcs_authentication = None
set_bucket_lifecycle_policy = None
GCS_AVAILABLE = False

# レシート・領収書・保証書タブ用ワークフロー（①〜⑧）
_RECEIPT_WORKFLOW_PIPELINE_SEGMENTS = [
    "①フォルダ選択",
    "②全件OCR",
    "③一括マッチング",
    "④手動調整",
    "⑤一括リネーム",
    "⑥照合チェック",
    "⑦GCSアップロード",
    "⑧確定",
]
_RECEIPT_WORKFLOW_PIPELINE_SEP = "\u2010"
_RECEIPT_ACTION_TO_PIPELINE_STEP = {
    "フォルダ選択": 1,
    "全件OCR": 2,
    "一括マッチング": 3,
    "一括リネーム": 5,
    "照合チェック": 6,
    "GCSアップロード": 7,
    "確定": 8,
}


def _format_receipt_status_prefix_html(text: str, emphasize: bool) -> str:
    from html import escape
    if not emphasize:
        return f'<span style="color:#cccccc;">{escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{escape(text)}</span>'


def _format_receipt_workflow_pipeline_html(active_step: Optional[int]) -> str:
    from html import escape
    parts: List[str] = []
    for i, seg in enumerate(_RECEIPT_WORKFLOW_PIPELINE_SEGMENTS, start=1):
        esc = escape(seg)
        if active_step == i:
            parts.append(f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>')
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _RECEIPT_WORKFLOW_PIPELINE_SEP.join(parts)


class AccountTitleDelegate(QStyledItemDelegate):
    """
    レシート一覧テーブルの「科目」列用デリゲート。
    通常時はテキスト表示のみ、編集時だけプルダウンを表示する。
    """

    def __init__(self, parent, receipt_db: ReceiptDatabase, account_title_db: AccountTitleDatabase):
        super().__init__(parent)
        self.receipt_db = receipt_db
        self.account_title_db = account_title_db

    def _get_titles(self) -> list[str]:
        try:
            titles = [t.get("name", "") for t in self.account_title_db.list_titles()]
        except Exception:
            titles = []
        default = "仕入"
        if default not in titles:
            titles.insert(0, default)
        return [t for t in titles if t]

    def createEditor(self, parent, option, index):
        from PySide6.QtWidgets import QComboBox

        combo = QComboBox(parent)
        for title in self._get_titles():
            combo.addItem(title)
        return combo

    def setEditorData(self, editor, index):
        current_text = index.data() or ""
        titles = self._get_titles()
        # 既存科目、なければデフォルト「仕入」
        if not current_text and titles:
            current_text = titles[0]
        idx = editor.findText(current_text)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        title = editor.currentText().strip()
        model.setData(index, title)

        # 対応するレシートIDを取得し、DBを更新
        row = index.row()
        id_index = model.index(row, 0)
        try:
            receipt_id = int(id_index.data())
        except (TypeError, ValueError):
            receipt_id = None
        if receipt_id:
            try:
                if title:
                    self.receipt_db.update_receipt(receipt_id, {"account_title": title})
                else:
                    self.receipt_db.update_receipt(receipt_id, {"account_title": None})
            except Exception:
                pass


class StoreNameDelegate(QStyledItemDelegate):
    """
    レシート一覧テーブルの「店舗名」列用デリゲート。
    ダブルクリックで店舗コード＋店舗名をプルダウンから選択可能。
    """
    
    def __init__(self, parent, receipt_db: ReceiptDatabase, store_db: StoreDatabase):
        super().__init__(parent)
        self.receipt_db = receipt_db
        self.store_db = store_db
    
    def _get_store_options(self) -> list[tuple[str, str]]:
        """店舗コード＋店舗名のリストを取得（store_code優先・supplier_codeフォールバック）"""
        try:
            stores = self.store_db.list_stores()
            options = []
            for store in stores:
                # 店舗コードを優先し、空の場合は仕入れ先コードをフォールバックとして使用
                code = (store.get('store_code') or '').strip() or (store.get('supplier_code') or '').strip()
                name = store.get('store_name', '') or ''
                if code and name:
                    options.append((code, f"{code} {name}"))
                elif code:
                    options.append((code, code))
                elif name:
                    options.append(('', name))
            return options
        except Exception:
            return []
    
    def createEditor(self, parent, option, index):
        from PySide6.QtWidgets import QComboBox
        
        combo = QComboBox(parent)
        options = self._get_store_options()
        for code, label in options:
            combo.addItem(label, code)
        return combo
    
    def setEditorData(self, editor, index):
        # 現在の値を取得
        current_data = index.data(Qt.UserRole)
        current_code = ""
        if isinstance(current_data, dict):
            current_code = current_data.get('store_code', '') or ''
        else:
            # フォールバック: 表示テキストから店舗コードを抽出
            current_text = index.data() or ""
            if current_text:
                parts = current_text.split(' ', 1)
                if parts:
                    current_code = parts[0]
        
        # コンボボックスで該当する項目を選択
        idx = editor.findData(current_code)
        if idx >= 0:
            editor.setCurrentIndex(idx)
    
    def setModelData(self, editor, model, index):
        selected_code = editor.currentData()
        selected_label = editor.currentText()
        
        # 表示テキストを更新
        model.setData(index, selected_label)
        
        # UserRoleに店舗コードと店舗名を保存
        row = index.row()
        id_index = model.index(row, 0)
        try:
            receipt_id = int(id_index.data())
        except (TypeError, ValueError):
            receipt_id = None
        
        if receipt_id and selected_code:
            try:
                # 店舗コードをDBに保存
                self.receipt_db.update_receipt(receipt_id, {"store_code": selected_code})
                # UserRoleを更新
                store_name_raw = selected_label.replace(selected_code, '').strip() if selected_code in selected_label else selected_label
                model.setData(index, {
                    'store_code': selected_code,
                    'store_name_raw': store_name_raw
                }, Qt.UserRole)
            except Exception:
                pass


class WarrantyProductDelegate(QStyledItemDelegate):
    """保証書一覧の商品名列に表示するデリゲート（ダブルクリックでコンボボックス）"""
    def __init__(self, parent, receipt_db: ReceiptDatabase):
        super().__init__(parent)
        self.receipt_db = receipt_db
        self.product_db = ProductDatabase()

    def _get_products(self) -> list[dict]:
        """商品マスタから商品一覧を取得"""
        products = self.product_db.list_all()
        # SKUと商品名でソート
        return sorted(products, key=lambda p: (p.get('sku', ''), p.get('product_name', '')))

    def createEditor(self, parent, option, index):
        """編集ウィジェットとしてQComboBoxを作成"""
        from PySide6.QtWidgets import QComboBox
        combo = QComboBox(parent)
        products = self._get_products()
        combo.addItem("(選択してください)", None)
        for prod in products:
            # 表示テキスト: SKU | 商品名
            display_text = f"{prod.get('sku', '')} | {prod.get('product_name', '')}"
            combo.addItem(display_text, prod) # ユーザーデータに商品辞書を格納
        return combo

    def setEditorData(self, editor, index):
        """エディタに現在の値を設定"""
        current_sku = index.model().data(index, Qt.UserRole)
        if current_sku:
            for i in range(editor.count()):
                prod_data = editor.itemData(i)
                if prod_data and prod_data.get('sku') == current_sku:
                    editor.setCurrentIndex(i)
                    break
        else:
            editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        """モデル（とDB）に選択された値を設定"""
        prod_data = editor.currentData()
        receipt_id = index.model().data(index.siblingAtColumn(0), Qt.UserRole)
        
        if not receipt_id or not prod_data:
            # (選択してください) が選ばれた場合 or 不正なデータ
            sku = ""
            product_name = ""
        else:
            sku = prod_data.get('sku', '')
            product_name = prod_data.get('product_name', '')

        # モデルの表示テキストを更新
        display_text = f"{sku} | {product_name}" if sku or product_name else ""
        model.setData(index, display_text, Qt.DisplayRole)
        # モデルの内部データを更新
        model.setData(index, sku, Qt.UserRole)

        # データベースを更新
        if receipt_id:
            update_data = {
                'warranty_sku': sku,
                'warranty_product_name': product_name
            }
            self.receipt_db.update_receipt(receipt_id, update_data)


class ReceiptSnapshotDialog(QDialog):
    """レシートスナップショットの一覧から選択して読込するダイアログ"""
    
    def __init__(self, snapshot_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("レシートスナップショット読込")
        self.resize(720, 420)
        self.snapshot_dir = snapshot_dir
        self._selected_file_path = None
        
        layout = QVBoxLayout(self)
        
        # 説明ラベル
        info_label = QLabel("読み込むスナップショットを選択してください:")
        layout.addWidget(info_label)
        
        # 一覧テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["保存名", "ルート名", "保存日時"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # ボタン
        btns = QDialogButtonBox()
        self.load_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btns.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        btns.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(btns)
        
        self.load_btn.clicked.connect(self._on_load)
        self.cancel_btn.clicked.connect(self.reject)
        
        self._reload()
    
    def _reload(self):
        """一覧を再読み込み"""
        try:
            if not self.snapshot_dir or not self.snapshot_dir.exists():
                self.table.setRowCount(0)
                return
            
            snapshot_files = sorted(
                self.snapshot_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            self.table.setRowCount(len(snapshot_files))
            for i, file_path in enumerate(snapshot_files):
                try:
                    # JSONファイルから情報を読み込む
                    with open(file_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    
                    saved_at = payload.get("saved_at", "不明な日時")
                    route_name = payload.get("route_name", "不明")
                    route_date = payload.get("route_date", "")
                    
                    # 保存名（ファイル名から拡張子を除いたもの）
                    snapshot_name = file_path.stem
                    # 日付とルート名を組み合わせて表示名を作成
                    if route_date and route_name:
                        display_name = f"{route_date} {route_name}"
                    else:
                        display_name = snapshot_name
                    
                    self.table.setItem(i, 0, QTableWidgetItem(display_name))
                    self.table.setItem(i, 1, QTableWidgetItem(route_name))
                    self.table.setItem(i, 2, QTableWidgetItem(saved_at))
                    
                    # ファイルパスをUserRoleとして保存
                    self.table.item(i, 0).setData(Qt.UserRole, str(file_path))
                except Exception as e:
                    # 読み込みエラーの場合はファイル名のみ表示
                    self.table.setItem(i, 0, QTableWidgetItem(file_path.stem))
                    self.table.setItem(i, 1, QTableWidgetItem("読み込みエラー"))
                    self.table.setItem(i, 2, QTableWidgetItem(""))
                    self.table.item(i, 0).setData(Qt.UserRole, str(file_path))
            
            self.table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"一覧の読み込みに失敗しました:\n{str(e)}")
    
    def _get_selected_file_path(self):
        """選択されている行のファイルパスを取得"""
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        r = sel[0].row()
        item = self.table.item(r, 0)
        if item:
            return item.data(Qt.UserRole)
        return None
    
    def _on_load(self):
        """読み込みボタンクリック"""
        file_path = self._get_selected_file_path()
        if not file_path:
            QMessageBox.information(self, "情報", "読み込むスナップショットを選択してください")
            return
        self._selected_file_path = file_path
        self.accept()
    
    def get_selected_file_path(self):
        """選択されたファイルパスを取得"""
        return self._selected_file_path


class ReceiptOCRThread(QThread):
    """OCR処理をバックグラウンドで実行するスレッド"""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, receipt_service: ReceiptService, image_path: str):
        super().__init__()
        self.receipt_service = receipt_service
        self.image_path = image_path
    
    def run(self):
        try:
            result = self.receipt_service.process_receipt(self.image_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


