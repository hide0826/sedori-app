#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルート管理ダイアログ・ドラッグ可能店舗リスト。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QTabWidget,
    QProgressDialog, QApplication, QListWidget, QListWidgetItem,
    QSplitter, QDoubleSpinBox, QAbstractItemView, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QSettings
from PySide6.QtGui import QColor, QDrag
from typing import Tuple, List, Dict, Any, Optional
import sys
import os
import re
import webbrowser

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from utils.excel_importer import ExcelImporter
from utils.ui_utils import reapply_table_column_widths
from services.store_route_membership_service import (
    apply_store_to_route_membership,
    detach_store_from_route_if_not_selected,
)


class DraggableStoreListWidget(QListWidget):
    """ドラッグ&ドロップ対応の店舗リストウィジェット"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
    
    def startDrag(self, supportedActions):
        """ドラッグ開始時の処理"""
        items = self.selectedItems()
        if not items:
            return
        
        drag = QDrag(self)
        mime_data = QMimeData()
        # 選択されたアイテムのデータを保存
        item_data = []
        for item in items:
            store_data = item.data(Qt.UserRole)
            if store_data:
                item_data.append(store_data)
        mime_data.setProperty("store_data", item_data)
        drag.setMimeData(mime_data)
        drag.exec_(supportedActions)


class RouteManagementDialog(QDialog):
    """ルート管理ダイアログ（新規作成・編集）"""
    
    def __init__(self, parent=None, db: StoreDatabase = None, route_name: Optional[str] = None):
        super().__init__(parent)
        self.db = db or StoreDatabase()
        self.route_name = route_name  # Noneの場合は新規作成、指定されている場合は編集
        self.is_edit_mode = route_name is not None
        # 新規作成時に一度だけ自動採番したかどうかのフラグ
        self._route_code_generated = False
        
        self.setWindowTitle("ルート編集" if self.is_edit_mode else "新規ルート作成")
        self.setMinimumSize(900, 600)
        self.setup_ui()
        
        if self.is_edit_mode:
            self.load_route_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # ルート名入力
        route_name_group = QGroupBox("ルート情報")
        route_name_layout = QFormLayout(route_name_group)
        
        self.route_name_edit = QLineEdit()
        self.route_name_edit.setPlaceholderText("ルート名を入力してください")
        # ルート名入力時にルートコードを自動採番（新規作成時のみ）
        self.route_name_edit.textChanged.connect(self.on_route_name_text_changed)
        route_name_layout.addRow("ルート名:", self.route_name_edit)
        
        self.route_code_edit = QLineEdit()
        self.route_code_edit.setReadOnly(True)
        self.route_code_edit.setPlaceholderText("ルートコード（自動生成）")
        route_name_layout.addRow("ルートコード:", self.route_code_edit)
        
        layout.addWidget(route_name_group)
        
        # 店舗選択エリア（左右分割）
        splitter = QSplitter(Qt.Horizontal)
        
        # 左側：選択された店舗リスト
        left_group = QGroupBox("このルートに所属する店舗")
        left_layout = QVBoxLayout(left_group)
        
        self.selected_stores_list = DraggableStoreListWidget(self)
        self.selected_stores_list.setDragDropMode(QListWidget.InternalMove)
        left_layout.addWidget(self.selected_stores_list)
        
        # 左側の操作ボタン
        left_buttons = QHBoxLayout()
        remove_btn = QPushButton("選択店舗を削除")
        remove_btn.clicked.connect(self.remove_selected_store)
        left_buttons.addWidget(remove_btn)
        left_buttons.addStretch()
        left_layout.addLayout(left_buttons)
        
        splitter.addWidget(left_group)
        
        # 右側：全店舗リスト
        right_group = QGroupBox("店舗一覧")
        right_layout = QVBoxLayout(right_group)
        
        # 検索フィールド
        search_layout = QHBoxLayout()
        search_label = QLabel("検索:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("店舗名、店舗コードで検索...")
        self.search_edit.textChanged.connect(self.filter_stores)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_edit)
        right_layout.addLayout(search_layout)
        
        self.all_stores_list = DraggableStoreListWidget(self)
        self.all_stores_list.setDragDropMode(QListWidget.DragOnly)
        right_layout.addWidget(self.all_stores_list)
        
        # 右側の操作ボタン
        right_buttons = QHBoxLayout()
        
        # 通常追加ボタン（このルートに「移動」するイメージ）
        add_btn = QPushButton("選択店舗を追加")
        add_btn.setToolTip("選択した店舗をこのルートに追加します（所属ルートをこのルートに変更します）")
        add_btn.clicked.connect(self.add_selected_store)
        right_buttons.addWidget(add_btn)
        
        # 重複追加ボタン（他ルートとの重複所属を許可）
        duplicate_add_btn = QPushButton("選択店舗の重複追加")
        duplicate_add_btn.setToolTip("既に他のルートに所属している店舗を、このルートにも追加します（ルートコードはカンマ区切りで複数保持されます）")
        duplicate_add_btn.clicked.connect(lambda: self.add_selected_store(allow_duplicate=True))
        right_buttons.addWidget(duplicate_add_btn)
        
        right_buttons.addStretch()
        right_layout.addLayout(right_buttons)
        
        splitter.addWidget(right_group)
        
        # 分割比率を設定（左:右 = 1:1）
        splitter.setSizes([450, 450])
        
        layout.addWidget(splitter)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 店舗一覧を読み込み
        self.load_all_stores()

    def _get_next_route_code(self) -> Optional[str]:
        """既存ルートから次のルートコードを採番（例: R001 → R002）"""
        try:
            return self.db.generate_next_route_code()
        except Exception:
            return None

    def on_route_name_text_changed(self, text: str):
        """ルート名入力時にルートコードを自動で埋める（新規作成時のみ）"""
        if self.is_edit_mode:
            # 既存ルート編集時はコードを変えない
            return
        
        text = (text or "").strip()
        if not text:
            # ルート名が空になったらコードもクリアして再採番可にする
            self.route_code_edit.clear()
            self._route_code_generated = False
            return
        
        # すでに手動で何か入力されていれば上書きしない
        if self.route_code_edit.text().strip():
            return
        
        # まだ採番していない場合のみ採番
        if not self._route_code_generated:
            next_code = self._get_next_route_code()
            if next_code:
                self.route_code_edit.setText(next_code)
                self._route_code_generated = True
    
    def load_all_stores(self):
        """全店舗を読み込み"""
        stores = self.db.list_stores()
        self.all_stores_list.clear()
        
        # 編集モード時に、このルートに既に所属している店舗を除外するためのルートコード
        current_route_code = None
        if self.is_edit_mode:
            current_route_code = self.db.get_route_code_by_name(self.route_name)
        
        for store in stores:
            store_code = store.get('store_code') or store.get('supplier_code') or ''
            store_name = store.get('store_name') or ''
            current_route = store.get('affiliated_route_name') or ''
            route_codes_str = store.get('route_code') or ''
            route_codes = [code.strip() for code in route_codes_str.split(',') if code.strip()]
            
            # 編集モードの場合、既にこのルートに所属している店舗は右側に表示しない
            if self.is_edit_mode:
                if current_route_code:
                    # route_codeベースで判定
                    if current_route_code in route_codes:
                        continue
                else:
                    # 互換性のため、古いデータではaffiliated_route_nameで判定
                    if current_route == self.route_name:
                        continue
            
            display_text = f"{store_code} - {store_name}"
            if current_route:
                display_text += f" [{current_route}]"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, store)
            self.all_stores_list.addItem(item)
    
    def load_route_data(self):
        """既存ルートのデータを読み込み"""
        if not self.route_name:
            return
        
        # ルート名を設定
        self.route_name_edit.setText(self.route_name)
        
        # ルートコードを取得
        route_code = self.db.get_route_code_by_name(self.route_name)
        if route_code:
            self.route_code_edit.setText(route_code)
        
        # このルートに所属する店舗を読み込み
        stores = self.db.list_stores()
        self.selected_stores_list.clear()
        
        # 現在編集中のルートコードを取得（なければ後で自動生成される）
        current_route_code = self.db.get_route_code_by_name(self.route_name)
        
        for store in stores:
            belongs_to_route = False
            
            route_codes_str = store.get('route_code') or ''
            route_codes = [code.strip() for code in route_codes_str.split(',') if code.strip()]
            
            if current_route_code:
                # route_codeが設定されている場合は、route_codeに含まれているかで判定
                if current_route_code in route_codes:
                    belongs_to_route = True
            else:
                # 互換性のため、古いデータではaffiliated_route_nameで判定
                store_route_name = store.get('affiliated_route_name') or ''
                if store_route_name == self.route_name:
                    belongs_to_route = True
            
            if belongs_to_route:
                store_code = store.get('store_code') or store.get('supplier_code') or ''
                store_name = store.get('store_name') or ''
                display_text = f"{store_code} - {store_name}"
                
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, store)
                # 既存データについては、重複追加フラグは False として扱う
                item.setData(Qt.UserRole + 1, False)
                self.selected_stores_list.addItem(item)
        
        # 右側の店舗一覧を再読み込み（このルートに所属する店舗を除外）
        self.load_all_stores()
    
    def filter_stores(self):
        """店舗一覧をフィルタリング"""
        search_term = self.search_edit.text().lower()
        
        for i in range(self.all_stores_list.count()):
            item = self.all_stores_list.item(i)
            if item:
                text = item.text().lower()
                item.setHidden(search_term not in text)
    
    def add_selected_store(self, allow_duplicate: bool = False):
        """選択された店舗を左側のリストに追加
        
        Args:
            allow_duplicate: Trueの場合、このルート以外のルートへの所属を維持したまま
                             このルートにも所属させる（ルートコードをカンマ区切りで複数保持）
        """
        selected_items = self.all_stores_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "追加する店舗を選択してください。")
            return
        
        for item in selected_items:
            store = item.data(Qt.UserRole)
            if not store:
                continue
            
            # 既に左側のリストに存在するかチェック
            store_id = store.get('id')
            exists = False
            for i in range(self.selected_stores_list.count()):
                existing_item = self.selected_stores_list.item(i)
                if existing_item:
                    existing_store = existing_item.data(Qt.UserRole)
                    if existing_store and existing_store.get('id') == store_id:
                        exists = True
                        break
            
            # 同じルート内での二重追加は避けるため、左側リスト上の重複は許可しない
            if exists:
                continue
            
            store_code = store.get('store_code') or store.get('supplier_code') or ''
            store_name = store.get('store_name') or ''
            display_text = f"{store_code} - {store_name}"
            
            new_item = QListWidgetItem(display_text)
            new_item.setData(Qt.UserRole, store)
            # UserRole+1 に「重複追加かどうか」のフラグを保存（True/False）
            new_item.setData(Qt.UserRole + 1, bool(allow_duplicate))
            self.selected_stores_list.addItem(new_item)
            
            # 右側のリストから削除
            self.all_stores_list.takeItem(self.all_stores_list.row(item))
    
    def remove_selected_store(self):
        """選択された店舗を左側のリストから削除"""
        selected_items = self.selected_stores_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "削除する店舗を選択してください。")
            return
        
        for item in selected_items:
            store = item.data(Qt.UserRole)
            if store:
                # 右側のリストに戻す
                store_code = store.get('store_code') or store.get('supplier_code') or ''
                store_name = store.get('store_name') or ''
                current_route = store.get('affiliated_route_name') or ''
                
                display_text = f"{store_code} - {store_name}"
                if current_route:
                    display_text += f" [{current_route}]"
                
                new_item = QListWidgetItem(display_text)
                new_item.setData(Qt.UserRole, store)
                self.all_stores_list.addItem(new_item)
            
            # 左側のリストから削除
            self.selected_stores_list.takeItem(self.selected_stores_list.row(item))
    
    def accept(self):
        """OKボタンがクリックされたときの処理"""
        route_name = self.route_name_edit.text().strip()
        if not route_name:
            QMessageBox.warning(self, "警告", "ルート名を入力してください。")
            return
        
        try:
            # ルートコードを生成または取得
            route_code = self.route_code_edit.text().strip()
            if not route_code:
                # ルートコードを自動生成（既存のルートコードの最大値+1）
                route_code = self._get_next_route_code()
                if not route_code:
                    QMessageBox.warning(self, "エラー", "ルートコードの自動生成に失敗しました。")
                    return
                # UI側にも反映しておく
                self.route_code_edit.setText(route_code)
            
            # 選択された店舗のIDを取得
            selected_store_ids = []
            duplicate_flags = {}
            for i in range(self.selected_stores_list.count()):
                item = self.selected_stores_list.item(i)
                if item:
                    store = item.data(Qt.UserRole)
                    if store and store.get('id'):
                        store_id = store.get('id')
                        selected_store_ids.append(store_id)
                        # UserRole+1 に保存した「重複追加フラグ」を取得
                        duplicate_flags[store_id] = bool(item.data(Qt.UserRole + 1))
            
            # 店舗のルート情報を更新
            for store_id in selected_store_ids:
                allow_duplicate = duplicate_flags.get(store_id, False)
                apply_store_to_route_membership(
                    self.db,
                    store_id,
                    route_name,
                    route_code,
                    allow_duplicate=allow_duplicate,
                )

            # このルートから外れた店舗のルート情報を更新
            if self.is_edit_mode:
                all_stores = self.db.list_stores()
                for store in all_stores:
                    detach_store_from_route_if_not_selected(
                        self.db,
                        store,
                        self.route_name,
                        route_code,
                        selected_store_ids,
                    )
            
            # routesテーブルにルート情報を保存
            self.db.upsert_route(route_name, route_code)
            
            QMessageBox.information(self, "完了", "ルートを保存しました。")
            super().accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ルートの保存に失敗しました:\n{str(e)}")
