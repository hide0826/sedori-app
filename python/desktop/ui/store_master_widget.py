#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗マスタ管理ウィジェット

店舗マスタの追加・編集・削除機能
- Excelインポート機能
- カスタムフィールド対応
- 検索・フィルタ機能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QTabWidget,
    QProgressDialog, QApplication, QListWidget, QListWidgetItem,
    QSplitter
)
from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QColor, QDrag
from typing import Tuple, List, Dict, Any, Optional
import sys
import os
import webbrowser

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from utils.excel_importer import ExcelImporter
from ui.company_master_widget import CompanyMasterWidget
from ui.store_score_widget import StoreScoreWidget

# デスクトップ側servicesを優先して読み込む
try:
    from services.google_maps_service import get_store_info_from_google, recover_store_info_with_japanese  # python/desktop/services
except Exception:
    # 明示的パス指定のフォールバック
    try:
        service_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'services'))
        if service_path not in sys.path:
            sys.path.insert(0, service_path)
        from google_maps_service import get_store_info_from_google, recover_store_info_with_japanese
    except Exception:
        get_store_info_from_google = None
        recover_store_info_with_japanese = None


class StoreEditDialog(QDialog):
    """店舗編集ダイアログ"""
    
    def __init__(self, parent=None, store_data=None, custom_fields_def=None, initial_route_name: str = None):
        super().__init__(parent)
        self.store_data = store_data
        self.custom_fields_def = custom_fields_def or []
        self.db = StoreDatabase()
        self.initial_route_name = initial_route_name
        # カスタムフィールド編集ウィジェットのマップは必ず初期化しておく
        self.custom_field_edits = {}
        
        self.setWindowTitle("店舗編集" if store_data else "店舗追加")
        self.setModal(True)
        self.setup_ui()
        
        if store_data:
            self.load_data()
        else:
            # 新規追加時に初期ルートが与えられていれば自動入力
            if self.initial_route_name:
                idx = self.affiliated_route_name_combo.findText(self.initial_route_name)
                if idx >= 0:
                    self.affiliated_route_name_combo.setCurrentIndex(idx)
                else:
                    self.affiliated_route_name_combo.setCurrentText(self.initial_route_name)
                # ルートコードを自動設定（店舗コードは店舗名入力時に自動生成）
                self.on_route_name_changed(self.initial_route_name)
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # 基本情報フォーム
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        # 所属ルート名: 編集可能なQComboBox
        self.affiliated_route_name_combo = QComboBox()
        self.affiliated_route_name_combo.setEditable(True)  # 編集可能に設定
        self.affiliated_route_name_combo.setInsertPolicy(QComboBox.NoInsert)  # 新規入力時は追加しない
        # 既存ルート名一覧をロード
        self.load_route_names()
        # ルート選択変更時のシグナル接続
        self.affiliated_route_name_combo.currentTextChanged.connect(self.on_route_name_changed)
        # 編集時のシグナル接続（テキスト入力時）
        self.affiliated_route_name_combo.lineEdit().textChanged.connect(self.on_route_name_text_changed)
        form_layout.addRow("所属ルート名:", self.affiliated_route_name_combo)
        
        self.route_code_edit = QLineEdit()
        self.route_code_edit.setReadOnly(True)  # 自動挿入なので読み取り専用
        form_layout.addRow("ルートコード:", self.route_code_edit)
        
        self.store_code_edit = QLineEdit()
        form_layout.addRow("店舗コード:", self.store_code_edit)
        
        self.store_name_edit = QLineEdit()
        self.store_name_edit.setPlaceholderText("必須項目")
        # 店舗名変更時に仕入れ先コードを自動生成
        self.store_name_edit.textChanged.connect(self.on_store_name_changed)
        form_layout.addRow("店舗名:", self.store_name_edit)

        # 住所・電話番号の追加
        self.address_edit = QLineEdit()
        form_layout.addRow("住所:", self.address_edit)
        self.phone_edit = QLineEdit()
        form_layout.addRow("電話番号:", self.phone_edit)
        
        layout.addWidget(form_group)
        
        # カスタムフィールドフォーム
        if self.custom_fields_def:
            custom_group = QGroupBox("カスタムフィールド")
            custom_layout = QFormLayout(custom_group)
            for field_def in self.custom_fields_def:
                if field_def.get('is_active', 1):
                    field_name = field_def['field_name']
                    display_name = field_def['display_name']
                    field_type = field_def['field_type']
                    
                    if field_type in ['TEXT', 'DATE']:
                        edit = QLineEdit()
                    elif field_type == 'INTEGER':
                        edit = QLineEdit()
                        edit.setPlaceholderText("数値")
                    elif field_type == 'REAL':
                        edit = QLineEdit()
                        edit.setPlaceholderText("小数")
                    else:
                        edit = QLineEdit()
                    
                    custom_layout.addRow(f"{display_name}:", edit)
                    self.custom_field_edits[field_name] = edit
            
            layout.addWidget(custom_group)
        
        # ボタン
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_route_names(self):
        """既存のルート名一覧をロード"""
        route_names = self.db.get_route_names()
        self.affiliated_route_name_combo.clear()
        self.affiliated_route_name_combo.addItems(route_names)
    
    def on_route_name_changed(self, route_name: str):
        """ルート名が変更された時（プルダウン選択時）"""
        if not route_name:
            self.route_code_edit.clear()
            # 店舗コードは店舗名が入力されるまで空のままにする
            if not self.store_name_edit.text().strip():
                self.store_code_edit.clear()
            return
        
        # ルートコードを自動挿入
        route_code = self.db.get_route_code_by_name(route_name)
        if route_code:
            self.route_code_edit.setText(route_code)
        else:
            self.route_code_edit.clear()
        
        # 店舗名から店舗コードを自動生成（店舗名が入力されている場合のみ）
        store_name = self.store_name_edit.text().strip()
        if store_name:
            next_store_code = self.db.get_next_store_code_from_store_name(store_name)
            if next_store_code:
                self.store_code_edit.setText(next_store_code)
        # 店舗名がない場合は店舗コードを空のままにする
        # （店舗名入力時にon_store_name_changedで自動生成される）
    
    def on_route_name_text_changed(self, text: str):
        """ルート名が入力された時（テキスト編集時）"""
        # 既存ルート名と一致するかチェック
        current_index = self.affiliated_route_name_combo.findText(text)
        if current_index >= 0:
            # 既存ルートが見つかった場合は選択状態にする
            self.affiliated_route_name_combo.setCurrentIndex(current_index)
    
    def on_store_name_changed(self, store_name: str):
        """店舗名が変更された時に店舗コードを自動生成（新規追加時のみ）"""
        # 既存データの編集時は自動生成しない
        if self.store_data:
            return
        
        # 店舗名が入力されている場合のみ自動生成
        if store_name and store_name.strip():
            next_store_code = self.db.get_next_store_code_from_store_name(store_name.strip())
            if next_store_code:
                # 店舗コードが既に入力されている場合は上書きしない
                current_code = self.store_code_edit.text().strip()
                if not current_code:
                    self.store_code_edit.setText(next_store_code)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.store_data:
            return
        
        route_name = self.store_data.get('affiliated_route_name', '')
        if route_name:
            # 既存ルート名がリストにあるかチェック
            index = self.affiliated_route_name_combo.findText(route_name)
            if index >= 0:
                self.affiliated_route_name_combo.setCurrentIndex(index)
            else:
                # リストにない場合は現在のテキストとして設定
                self.affiliated_route_name_combo.setCurrentText(route_name)
        else:
            self.affiliated_route_name_combo.setCurrentText('')
        
        self.route_code_edit.setText(self.store_data.get('route_code', ''))
        # store_codeを優先し、なければsupplier_codeをフォールバック（互換性のため）
        store_code = self.store_data.get('store_code', '') or self.store_data.get('supplier_code', '')
        self.store_code_edit.setText(store_code)
        self.store_name_edit.setText(self.store_data.get('store_name', ''))
        self.address_edit.setText(self.store_data.get('address', ''))
        self.phone_edit.setText(self.store_data.get('phone', ''))
        
        # カスタムフィールドの読み込み
        custom_fields = self.store_data.get('custom_fields', {})
        # self.custom_field_edits は空の可能性があるため安全に処理
        if hasattr(self, 'custom_field_edits') and isinstance(self.custom_field_edits, dict):
            for field_name, edit in self.custom_field_edits.items():
                value = custom_fields.get(field_name, '')
                edit.setText(str(value))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        # 所属ルート名はQComboBoxから取得（編集可能なので現在のテキスト）
        route_name = self.affiliated_route_name_combo.currentText().strip()
        
        store_code = self.store_code_edit.text().strip()
        data = {
            'affiliated_route_name': route_name,
            'route_code': self.route_code_edit.text().strip(),
            'store_code': store_code if store_code else None,
            'store_name': self.store_name_edit.text().strip(),
            'address': self.address_edit.text().strip(),
            'phone': self.phone_edit.text().strip(),
            'supplier_code': None,  # 互換性のためNULL（store_codeを使用）
            'custom_fields': {}
        }
        
        # カスタムフィールドの取得
        for field_name, edit in self.custom_field_edits.items():
            data['custom_fields'][field_name] = edit.text().strip()
        
        return data
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        # 店舗名は必須
        if not data['store_name']:
            return False, "店舗名を入力してください"
        
        # 店舗コードの重複チェック
        store_code = data['store_code']
        if store_code:
            exclude_id = self.store_data.get('id') if self.store_data else None
            if self.db.check_store_code_exists(store_code, exclude_id):
                return False, f"店舗コード '{store_code}' は既に使用されています"
        
        return True, ""


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
                existing_routes = self.db.list_routes_with_store_count()
                max_code_num = 0
                for route in existing_routes:
                    route_code_str = route.get('route_code', '')
                    if route_code_str:
                        # ルートコードから数値部分を抽出（例: "R001" -> 1）
                        import re
                        match = re.search(r'(\d+)', route_code_str)
                        if match:
                            code_num = int(match.group(1))
                            max_code_num = max(max_code_num, code_num)
                route_code = f"R{max_code_num + 1:03d}"
            
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
                store = self.db.get_store(store_id)
                if store:
                    allow_duplicate = duplicate_flags.get(store_id, False)
                    
                    # 既存のルートコードを取得（カンマ区切りの文字列をリストに変換）
                    existing_route_code_str = store.get('route_code') or ''
                    existing_codes = [
                        code.strip()
                        for code in existing_route_code_str.split(',')
                        if code.strip()
                    ]
                    
                    if allow_duplicate:
                        # 既存のルートコードを維持したまま、このルートコードを追加
                        if route_code not in existing_codes:
                            existing_codes.append(route_code)
                        new_route_code_str = ",".join(existing_codes) if existing_codes else None
                        
                        update_data = {
                            'route_code': new_route_code_str,
                        }
                        # まだ所属ルート名が設定されていない場合のみ、このルート名を設定
                        if not store.get('affiliated_route_name'):
                            update_data['affiliated_route_name'] = route_name
                        self.db.update_store(store_id, update_data)
                    else:
                        # このルートをメインとし、ルートコードはこのルートのみとする
                        self.db.update_store(store_id, {
                            'affiliated_route_name': route_name,
                            'route_code': route_code
                        })
            
            # このルートから外れた店舗のルート情報を更新
            if self.is_edit_mode:
                all_stores = self.db.list_stores()
                for store in all_stores:
                    store_id = store.get('id')
                    if not store_id:
                        continue
                    
                    existing_route_code_str = store.get('route_code') or ''
                    existing_codes = [
                        code.strip()
                        for code in existing_route_code_str.split(',')
                        if code.strip()
                    ]
                    
                    if not existing_codes:
                        continue
                    
                    # このルートコードを持っているが、今回の選択から外れている店舗については、このルートコードだけを削除
                    if route_code in existing_codes and store_id not in selected_store_ids:
                        new_codes = [code for code in existing_codes if code != route_code]
                        new_route_code_str = ",".join(new_codes) if new_codes else None
                        
                        update_data = {
                            'route_code': new_route_code_str
                        }
                        # このルート名がaffiliated_route_nameとして設定されていた場合はクリア
                        if store.get('affiliated_route_name') == self.route_name:
                            update_data['affiliated_route_name'] = None
                        
                        self.db.update_store(store_id, update_data)
            
            # routesテーブルにルート情報を保存
            self.db.upsert_route(route_name, route_code)
            
            QMessageBox.information(self, "完了", "ルートを保存しました。")
            super().accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ルートの保存に失敗しました:\n{str(e)}")


class CustomFieldEditDialog(QDialog):
    """カスタムフィールド編集ダイアログ"""
    
    def __init__(self, parent=None, field_data=None):
        super().__init__(parent)
        self.field_data = field_data
        
        self.setWindowTitle("カスタムフィールド編集" if field_data else "カスタムフィールド追加")
        self.setModal(True)
        self.setup_ui()
        
        if field_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.field_name_edit = QLineEdit()
        self.field_name_edit.setPlaceholderText("field_name（英数字、アンダースコア）")
        form_layout.addRow("フィールド名:", self.field_name_edit)
        
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("表示名（日本語OK）")
        form_layout.addRow("表示名:", self.display_name_edit)
        
        self.field_type_combo = QComboBox()
        self.field_type_combo.addItems(["TEXT", "INTEGER", "REAL", "DATE"])
        form_layout.addRow("フィールドタイプ:", self.field_type_combo)
        
        self.is_active_check = QCheckBox("有効")
        self.is_active_check.setChecked(True)
        form_layout.addRow("状態:", self.is_active_check)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.field_data:
            return
        
        self.field_name_edit.setText(self.field_data.get('field_name', ''))
        self.field_name_edit.setEnabled(False)  # フィールド名は変更不可
        self.display_name_edit.setText(self.field_data.get('display_name', ''))
        self.field_type_combo.setCurrentText(self.field_data.get('field_type', 'TEXT'))
        self.is_active_check.setChecked(bool(self.field_data.get('is_active', 1)))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        return {
            'field_name': self.field_name_edit.text().strip(),
            'display_name': self.display_name_edit.text().strip(),
            'field_type': self.field_type_combo.currentText(),
            'is_active': 1 if self.is_active_check.isChecked() else 0
        }
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        if not data['field_name']:
            return False, "フィールド名を入力してください"
        
        if not data['display_name']:
            return False, "表示名を入力してください"
        
        # フィールド名の形式チェック（英数字とアンダースコアのみ）
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', data['field_name']):
            return False, "フィールド名は英数字とアンダースコアのみ使用できます"
        
        return True, ""


class StoreListWidget(QWidget):
    """店舗一覧管理ウィジェット（店舗マスタタブ用）"""
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self.excel_importer = ExcelImporter()
        self.current_filtered_route = None  # 現在フィルタリング中のルート名
        self.current_selected_route = None  # 現在選択中のルート名
        # ルート情報リスト（コンボボックスの並び順と完全に一致させる）
        # 各要素は {'route_name': str, 'route_code': str, 'store_count': int, 'google_map_url': str} の辞書
        self.route_data = []
        
        self.setup_ui()
        self.load_routes()
        self.load_stores()
        self.load_custom_fields()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：操作ボタン
        self.setup_action_buttons(layout)
        
        # 中部：検索・フィルタ
        self.setup_search_filter(layout)
        
        # ルート一覧テーブル
        self.setup_route_table(layout)
        
        # 下部：店舗一覧テーブル
        self.setup_store_table(layout)
        
        # 統計情報
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # Excelインポートボタン
        import_btn = QPushButton("Excelインポート")
        import_btn.clicked.connect(self.import_excel)
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(import_btn)
        
        # 追加ボタン
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_store)
        button_layout.addWidget(add_btn)
        
        # 編集ボタン
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_store)
        button_layout.addWidget(edit_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_store)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        # カスタムフィールド管理ボタン
        custom_fields_btn = QPushButton("カスタムフィールド管理")
        custom_fields_btn.clicked.connect(self.manage_custom_fields)
        button_layout.addWidget(custom_fields_btn)
        
        # 新規ルート作成ボタン
        new_route_btn = QPushButton("新規ルート作成")
        new_route_btn.clicked.connect(self.create_new_route)
        new_route_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(new_route_btn)
        
        # ルート編集ボタン
        edit_route_btn = QPushButton("ルート編集")
        edit_route_btn.clicked.connect(self.edit_route)
        edit_route_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: black;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(edit_route_btn)
        
        # 選択ルート削除ボタン
        delete_route_btn = QPushButton("選択ルート削除")
        delete_route_btn.clicked.connect(self.delete_selected_route)
        delete_route_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(delete_route_btn)
        
        parent_layout.addWidget(button_group)
    
    def setup_search_filter(self, parent_layout):
        """検索・フィルタの設定"""
        search_group = QGroupBox("検索")
        search_layout = QHBoxLayout(search_group)
        
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("店舗名、店舗コード、ルート名で検索...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.search_edit.clear)
        search_layout.addWidget(clear_btn)
        
        parent_layout.addWidget(search_group)
    
    def setup_route_table(self, parent_layout):
        """ルート選択の設定（一行形式）"""
        route_group = QGroupBox("ルート選択")
        route_layout = QHBoxLayout(route_group)
        
        # ルート呼び出しボタン
        self.call_route_btn = QPushButton("ルート呼び出し")
        self.call_route_btn.clicked.connect(self.on_call_route_clicked)
        self.call_route_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        route_layout.addWidget(self.call_route_btn)
        
        # ルート解除ボタン
        self.clear_filter_btn_route = QPushButton("ルート解除")
        self.clear_filter_btn_route.clicked.connect(self.clear_route_filter)
        self.clear_filter_btn_route.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #545b62;
            }
        """)
        self.clear_filter_btn_route.setEnabled(False)  # 初期状態は無効
        route_layout.addWidget(self.clear_filter_btn_route)
        
        # ルート選択プルダウン
        route_label = QLabel("ルート選択:")
        route_layout.addWidget(route_label)
        
        self.route_combo = QComboBox()
        self.route_combo.setMinimumWidth(200)
        route_layout.addWidget(self.route_combo)
        
        # ルート選択変更時のシグナル接続
        self.route_combo.currentTextChanged.connect(self.on_route_selection_changed)
        
        # Google Map URL ラベルと入力欄
        url_label = QLabel("Google Map URL:")
        route_layout.addWidget(url_label)
        
        self.google_map_url_edit = QLineEdit()
        self.google_map_url_edit.setPlaceholderText("https://...")
        self.google_map_url_edit.setMinimumWidth(300)
        route_layout.addWidget(self.google_map_url_edit)
        
        # Google Map URL保存ボタン
        save_url_btn = QPushButton("URL保存")
        save_url_btn.clicked.connect(self.save_google_map_url)
        save_url_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                padding: 8px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        route_layout.addWidget(save_url_btn)
        
        # ブラウザで開くボタン
        open_browser_btn = QPushButton("ブラウザで開く")
        open_browser_btn.clicked.connect(self.open_url_in_browser)
        open_browser_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                padding: 8px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        route_layout.addWidget(open_browser_btn)
        
        # 情報取得ボタン（住所・電話番号の自動補完）
        fetch_info_btn = QPushButton("情報取得")
        fetch_info_btn.clicked.connect(self.fetch_missing_store_info)
        fetch_info_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: #212529;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0a800;
            }
        """)
        route_layout.addWidget(fetch_info_btn)
        
        # データリカバリーボタン（英語住所を日本語に修正）
        recover_info_btn = QPushButton("データリカバリー")
        recover_info_btn.clicked.connect(self.recover_japanese_store_info)
        recover_info_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        route_layout.addWidget(recover_info_btn)
        
        # 店舗コード再付番ボタン
        assign_store_code_btn = QPushButton("店舗コード再付番")
        assign_store_code_btn.clicked.connect(self.assign_store_codes)
        assign_store_code_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        route_layout.addWidget(assign_store_code_btn)
        
        route_layout.addStretch()
        
        parent_layout.addWidget(route_group)
    
    def load_routes(self):
        """ルート一覧を読み込む"""
        routes = self.db.list_routes_with_store_count()
        self.update_route_combo(routes)
    
    def update_route_combo(self, routes: list):
        """ルート選択プルダウンを更新"""
        self.route_combo.clear()
        # ルート情報リストをそのまま保持（順序を維持）
        self.route_data = list(routes) if routes else []
        
        for route in self.route_data:
            route_name = route.get('route_name', '')
            route_code = route.get('route_code', '')
            store_count = route.get('store_count', 0)
            display_text = f"{route_name} ({route_code}) - {store_count}店舗"
            
            self.route_combo.addItem(display_text)
        
        # 現在選択中のルートのGoogle Map URLを表示
        if self.current_selected_route:
            for route in self.route_data:
                if route.get('route_name') == self.current_selected_route:
                    url = route.get('google_map_url', '')
                    self.google_map_url_edit.setText(url)
                    break
    
    def on_route_selection_changed(self, text: str):
        """ルート選択変更時の処理"""
        index = self.route_combo.currentIndex()
        if 0 <= index < len(self.route_data):
            route_info = self.route_data[index]
            selected_route_name = route_info.get('route_name', '')
            self.current_selected_route = selected_route_name
            url = route_info.get('google_map_url', '')
            self.google_map_url_edit.setText(url)
    
    def save_google_map_url(self):
        """Google Map URLを保存"""
        if self.route_combo.currentIndex() < 0:
            QMessageBox.warning(self, "警告", "ルートを選択してください")
            return
        
        index = self.route_combo.currentIndex()
        if not (0 <= index < len(self.route_data)):
            QMessageBox.warning(self, "警告", "選択されたルートが見つかりません。")
            return
        
        route_info = self.route_data[index]
        selected_route = route_info.get('route_name', '')
        google_map_url = self.google_map_url_edit.text().strip()
        
        try:
            self.db.update_route_google_map_url(selected_route, google_map_url)
            # データも更新
            self.route_data[index]['google_map_url'] = google_map_url
            QMessageBox.information(self, "完了", f"ルート '{selected_route}' のGoogle Map URLを保存しました")
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"Google Map URLの保存に失敗しました:\n{str(e)}")
    
    def open_url_in_browser(self):
        """ブラウザでURLを開く"""
        url = self.google_map_url_edit.text().strip()
        
        if not url:
            QMessageBox.warning(self, "警告", "Google Map URLが入力されていません")
            return
        
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"ブラウザで開くのに失敗しました:\n{str(e)}")
    
    def on_call_route_clicked(self):
        """ルート呼び出しボタンクリック時の処理"""
        if self.route_combo.currentIndex() < 0:
            QMessageBox.warning(self, "警告", "ルートを選択してください")
            return
        
        index = self.route_combo.currentIndex()
        if not (0 <= index < len(self.route_data)):
            QMessageBox.warning(self, "警告", "選択されたルートが見つかりません。")
            return
        
        # 現在選択されているルート名を取得
        route_info = self.route_data[index]
        selected_route = route_info.get('route_name', '')
        self.current_selected_route = selected_route
        
        self.call_route(selected_route)
        
        # 解除ボタンを有効化
        self.clear_filter_btn_route.setEnabled(True)
    
    def call_route(self, route_name: str):
        """ルート呼び出し処理"""
        self.current_filtered_route = route_name
        self.load_stores()  # フィルタリングされた店舗一覧を表示
    
    def clear_route_filter(self):
        """ルート呼び出し解除処理"""
        self.current_filtered_route = None
        self.current_selected_route = None
        self.load_stores()  # 全店舗一覧を表示
        self.clear_filter_btn_route.setEnabled(False)  # ルート解除ボタンの無効化
    
    def fetch_missing_store_info(self):
        """住所・電話番号が欠けている店舗の情報をGoogle Maps APIから取得"""
        # ヘルパー関数: Noneまたは文字列でない場合は空文字列を返す
        def safe_strip(value):
            """Noneまたは文字列でない場合は空文字列を返す"""
            if value is None:
                return ''
            return str(value).strip() if isinstance(value, str) else ''
        
        # モジュールがインポートできていない場合
        if get_store_info_from_google is None:
            QMessageBox.warning(
                self,
                "エラー",
                "Google Mapsサービスモジュールが読み込めませんでした。\n"
                "googlemapsライブラリがインストールされているか確認してください。"
            )
            return
        
        # 現在表示されている店舗一覧を取得
        stores = self.db.list_stores()
        
        # ルートフィルタが設定されている場合はフィルタリング
        if self.current_filtered_route:
            stores = [store for store in stores if store.get('affiliated_route_name') == self.current_filtered_route]
        
        # 住所または電話番号が空の店舗を抽出
        missing_info_stores = []
        for store in stores:
            if not store:  # storeがNoneの場合はスキップ
                continue
            
            address = safe_strip(store.get('address'))
            phone = safe_strip(store.get('phone'))
            store_name = safe_strip(store.get('store_name'))
            
            if store_name and (not address or not phone):
                missing_info_stores.append(store)
        
        if not missing_info_stores:
            QMessageBox.information(
                self, 
                "情報", 
                "住所・電話番号が欠けている店舗はありません。"
            )
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(missing_info_stores)}件の店舗の情報を取得しますか？\n"
            f"（Google Maps APIを使用します）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # プログレスダイアログを表示
        progress = QProgressDialog("店舗情報を取得中...", "キャンセル", 0, len(missing_info_stores), self)
        progress.setWindowTitle("情報取得中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        updated_count = 0
        failed_count = 0
        
        for i, store in enumerate(missing_info_stores):
            if progress.wasCanceled():
                break
            
            if not store:  # storeがNoneの場合はスキップ
                continue
            
            store_id = store.get('id')
            store_name = safe_strip(store.get('store_name'))
            current_address = safe_strip(store.get('address'))
            current_phone = safe_strip(store.get('phone'))
            
            progress.setValue(i)
            progress.setLabelText(f"取得中: {store_name}")
            QApplication.processEvents()  # UIを更新
            
            # Google Maps APIから情報を取得（日本語で取得）
            info = get_store_info_from_google(store_name, language_code='ja')
            
            if info:
                # データベースを更新
                update_data = {}
                
                # 住所が空の場合のみ更新
                if not current_address and info.get('address'):
                    update_data['address'] = info['address']
                
                # 電話番号が空の場合のみ更新
                if not current_phone and info.get('phone'):
                    update_data['phone'] = info['phone']
                
                if update_data:
                    try:
                        # 既存のデータを取得してマージ
                        existing_store = self.db.get_store(store_id)
                        if existing_store:
                            for key, value in update_data.items():
                                existing_store[key] = value
                            
                            # データベースを更新
                            self.db.update_store(store_id, existing_store)
                            updated_count += 1
                    except Exception as e:
                        print(f"店舗情報の更新エラー (ID: {store_id}): {e}")
                        failed_count += 1
            else:
                failed_count += 1
        
        progress.setValue(len(missing_info_stores))
        progress.close()
        
        # 結果を表示
        QMessageBox.information(
            self,
            "完了",
            f"情報取得が完了しました。\n\n"
            f"更新: {updated_count}件\n"
            f"失敗: {failed_count}件"
        )
        
        # テーブルを再読み込み
        self.load_stores(self.search_edit.text())
    
    def recover_japanese_store_info(self):
        """住所に'Japan'が含まれている店舗の情報を日本語で再取得して更新、および住所から「日本、」を削除"""
        # モジュールがインポートできていない場合
        if recover_store_info_with_japanese is None:
            QMessageBox.warning(
                self,
                "エラー",
                "Google Mapsサービスモジュールが読み込めませんでした。\n"
                "googlemapsライブラリがインストールされているか確認してください。"
            )
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "確認",
            "住所に'Japan'が含まれている店舗の情報を日本語で再取得し、\n"
            "住所から「日本、」を削除しますか？\n"
            "（Google Maps APIを使用します）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # プログレスダイアログを表示（件数は後で更新）
        progress = QProgressDialog("店舗情報をリカバリー中...", "キャンセル", 0, 100, self)
        progress.setWindowTitle("データリカバリー中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        QApplication.processEvents()  # UIを更新
        
        # リカバリー処理を実行
        try:
            result = recover_store_info_with_japanese(self.db)
            
            # 住所から「日本、」を削除する処理
            stores = self.db.list_stores()
            removed_count = 0
            
            for store in stores:
                address = store.get('address', '')
                if address and address.startswith('日本、'):
                    # 「日本、」を削除
                    new_address = address.replace('日本、', '', 1).strip()
                    if new_address != address:
                        try:
                            store_data = self.db.get_store(store['id'])
                            if store_data:
                                store_data['address'] = new_address
                                self.db.update_store(store['id'], store_data)
                                removed_count += 1
                        except Exception as e:
                            print(f"住所更新エラー (ID: {store['id']}): {e}")
            
            progress.close()
            
            # 結果を表示
            message = f"データリカバリーが完了しました。\n\n"
            message += f"対象: {result['total']}件\n"
            message += f"更新成功: {result['updated']}件\n"
            message += f"失敗: {result['failed']}件"
            if removed_count > 0:
                message += f"\n\n住所から「日本、」を削除: {removed_count}件"
            
            QMessageBox.information(
                self,
                "完了",
                message
            )
            
            # テーブルを再読み込み
            self.load_stores(self.search_edit.text())
            
        except Exception as e:
            progress.close()
            QMessageBox.warning(
                self,
                "エラー",
                f"データリカバリー中にエラーが発生しました:\n{str(e)}"
            )
    
    def assign_store_codes(self):
        """店舗コードを再付番

        - 以前は「空の店舗コード」にのみ付与していたが、
          チェーン店コードマッピング（設定タブ）を見直したあとに
          変更が反映されるよう、必要な店舗には再付与を行う。
        """
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "確認",
            "現在のチェーン店コードマッピングに基づいて、店舗コードを再付番しますか？\n"
            "（プレフィックスが変更された店舗は新しいプレフィックスで再付与されます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # プログレスダイアログを表示
        progress = QProgressDialog("店舗コードを再付番中...", "キャンセル", 0, 100, self)
        progress.setWindowTitle("店舗コード再付番中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        QApplication.processEvents()  # UIを更新
        
        try:
            # 店舗コード再付番処理を実行（マッピングを考慮）
            result = self.db.reassign_store_codes_using_mappings()
            
            progress.close()
            
            # 結果を表示
            QMessageBox.information(
                self,
                "完了",
                f"店舗コード再付番が完了しました。\n\n"
                f"対象: {result['total']}件\n"
                f"更新成功: {result['updated']}件\n"
                f"エラー: {result['errors']}件"
            )
            
            # テーブルを再読み込み
            self.load_stores(self.search_edit.text())
            
        except Exception as e:
            progress.close()
            QMessageBox.warning(
                self,
                "エラー",
                f"店舗コード再付番中にエラーが発生しました:\n{str(e)}"
            )
    
    def setup_store_table(self, parent_layout):
        """店舗一覧テーブルの設定"""
        table_group = QGroupBox("店舗一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.store_table = QTableWidget()
        self.store_table.setAlternatingRowColors(True)
        self.store_table.setSelectionBehavior(QTableWidget.SelectRows)
        # ダブルクリックで編集可能に（備考欄のみ編集可能）
        self.store_table.setEditTriggers(QTableWidget.DoubleClicked)
        # テキストの省略（...）を無効化
        self.store_table.setTextElideMode(Qt.ElideNone)
        # テキストを折り返して全文表示
        self.store_table.setWordWrap(True)
        
        # ソート機能を有効化
        self.store_table.setSortingEnabled(True)
        
        # ヘッダー設定
        header = self.store_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsClickable(True)  # ヘッダークリックでソート可能に
        
        # 備考欄の変更を監視
        self.store_table.cellChanged.connect(self.on_store_cell_changed)
        
        table_layout.addWidget(self.store_table)
        
        # 統計情報ラベル
        self.stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.stats_label)
        
        parent_layout.addWidget(table_group)
    
    def load_stores(self, search_term: str = ""):
        """店舗一覧を読み込む"""
        stores = self.db.list_stores(search_term)
        
        # ルートフィルタが設定されている場合は店舗一覧をフィルタリング
        if self.current_filtered_route:
            stores = [store for store in stores if store.get('affiliated_route_name') == self.current_filtered_route]
        
        self.update_table(stores)
        self.update_statistics()
    
    def load_custom_fields(self):
        """カスタムフィールド定義を読み込む"""
        self.custom_fields_def = self.db.list_custom_fields(active_only=True)
    
    def update_table(self, stores: list):
        """テーブルを更新"""
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.store_table.setSortingEnabled(False)
        
        # カスタムフィールド定義を取得
        self.load_custom_fields()
        
        # 基本カラム + カスタムフィールドカラム
        # 「登録番号」カラムを追加
        basic_columns = ["ID", "所属ルート名", "ルートコード", "店舗コード", "店舗名", "住所", "電話番号", "登録番号", "備考"]
        custom_columns = [field['display_name'] for field in self.custom_fields_def]
        columns = basic_columns + custom_columns
        
        self.store_table.setRowCount(len(stores))
        self.store_table.setColumnCount(len(columns))
        self.store_table.setHorizontalHeaderLabels(columns)
        
        # cellChangedシグナルを一時的にブロック
        self.store_table.blockSignals(True)
        
        # データの設定
        for i, store in enumerate(stores):
            store_id = store.get('id', 0)
            
            # 基本カラム
            # IDは数値としてソートできるように設定
            id_item = QTableWidgetItem()
            id_item.setData(Qt.EditRole, store_id)  # 数値として設定
            id_item.setText(str(store_id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)  # 編集不可
            self.store_table.setItem(i, 0, id_item)
            
            # 編集不可のカラム（登録番号以外）＋ 登録番号カラム（編集可）
            # store_codeを優先し、なければsupplier_codeをフォールバック（互換性のため）
            store_code = store.get('store_code', '') or store.get('supplier_code', '')

            # ルートコードがカンマ区切りで複数ある場合は、それぞれのルート名を取得してカンマ区切りで表示
            base_affiliated_route_name = store.get('affiliated_route_name', '') or ''
            route_code_str = store.get('route_code', '') or ''
            display_route_name = base_affiliated_route_name

            if route_code_str:
                codes = [code.strip() for code in route_code_str.split(',') if code.strip()]
                route_names: list[str] = []
                for code in codes:
                    try:
                        name = self.db.get_route_name_by_code(code) or ''
                    except Exception:
                        name = ''
                    if name:
                        route_names.append(name)

                # ルートコードから名前が取得できた場合はそれらを優先して表示
                if route_names:
                    # 重複を除去し、コードの並び順で表示
                    seen = set()
                    ordered_names = []
                    for name in route_names:
                        if name not in seen:
                            seen.add(name)
                            ordered_names.append(name)
                    display_route_name = ",".join(ordered_names)

            registration_col_index = basic_columns.index("登録番号")
            for col, value in enumerate([
                display_route_name,
                route_code_str,
                store_code,  # 店舗コード
                store.get('store_name', ''),
                store.get('address', ''),
                store.get('phone', ''),
                store.get('registration_number', '')
            ], start=1):
                item = QTableWidgetItem(str(value) if value else '')
                if col == registration_col_index:
                    # 登録番号カラムは編集可能 + store_idをUserRoleに保持
                    item.setData(Qt.UserRole, store_id)
                else:
                    # それ以外は編集不可
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.store_table.setItem(i, col, item)
            
            # 備考欄（最後の基本カラム）は編集可能
            notes_text = store.get('notes', '') or ''
            notes_item = QTableWidgetItem(notes_text)
            notes_item.setData(Qt.UserRole, store_id)  # 店舗IDを保存（更新時に使用）
            notes_item.setToolTip(notes_text)  # ツールチップで全文表示
            # 編集可能（フラグはそのまま）
            # 備考カラムのインデックスは basic_columns の最後
            notes_col_index = len(basic_columns) - 1
            self.store_table.setItem(i, notes_col_index, notes_item)
            
            # カスタムフィールド（編集不可）
            custom_fields = store.get('custom_fields', {})
            for j, field_def in enumerate(self.custom_fields_def):
                col_idx = len(basic_columns) + j
                field_name = field_def['field_name']
                value = custom_fields.get(field_name, '')
                field_type = field_def.get('field_type', 'TEXT')
                
                # フィールドタイプに応じてデータ型を設定
                item = QTableWidgetItem()
                if field_type == 'INTEGER':
                    try:
                        int_value = int(value) if value else 0
                        item.setData(Qt.EditRole, int_value)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0)
                    item.setText(str(value) if value else '')
                elif field_type == 'REAL':
                    try:
                        float_value = float(value) if value else 0.0
                        item.setData(Qt.EditRole, float_value)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0.0)
                    item.setText(str(value) if value else '')
                else:
                    item.setText(str(value) if value else '')
                
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 編集不可
                self.store_table.setItem(i, col_idx, item)
        
        # cellChangedシグナルのブロックを解除
        self.store_table.blockSignals(False)
        
        # データ投入完了後、ソート機能を再有効化
        self.store_table.setSortingEnabled(True)
        
        # 店舗コードカラムで昇順ソート（店舗コードは3列目、0-indexedで3）
        store_code_col_index = basic_columns.index("店舗コード")
        self.store_table.sortItems(store_code_col_index, Qt.AscendingOrder)
        
        # 列幅の自動調整
        self.store_table.resizeColumnsToContents()
        
        # 備考カラム（8列目）の設定
        if self.store_table.columnCount() > 8:
            # 備考カラムはStretchモードで残りのスペースを使用
            header = self.store_table.horizontalHeader()
            header.setSectionResizeMode(8, QHeaderView.Stretch)
        
        # 行の高さを内容に合わせて自動調整（折り返しテキスト対応）
        self.store_table.resizeRowsToContents()
    
    def update_statistics(self):
        """統計情報を更新"""
        stats = self.db.get_statistics()
        self.stats_label.setText(
            f"統計: 店舗数 {stats['total_stores']}件, "
            f"カスタムフィールド {stats['active_custom_fields']}件"
        )
    
    def on_store_cell_changed(self, row: int, column: int):
        """セルが変更されたときの処理（登録番号・備考欄を保存）"""
        # 登録番号列と備考列のみ保存対象
        basic_columns = ["ID", "所属ルート名", "ルートコード", "店舗コード", "店舗名", "住所", "電話番号", "登録番号", "備考"]
        registration_column_index = basic_columns.index("登録番号")
        notes_column_index = len(basic_columns) - 1
        if column not in (registration_column_index, notes_column_index):
            return
        
        try:
            item = self.store_table.item(row, column)
            if not item:
                return
            
            # 店舗IDを取得（UserRoleに保存されている）
            store_id = item.data(Qt.UserRole)
            if not store_id:
                # UserRoleにIDがない場合は、ID列から取得を試みる
                id_item = self.store_table.item(row, 0)
                if id_item:
                    try:
                        store_id = int(id_item.text())
                    except ValueError:
                        return
                else:
                    return
            
            # 列ごとに保存先を切り替え
            if column == notes_column_index:
                # 新しい備考の値
                new_notes = item.text()
                # データベースに保存
                self.db.update_store_notes(store_id, new_notes)
            elif column == registration_column_index:
                new_reg_no = item.text()
                self.db.update_registration_number(store_id, new_reg_no)
            
        except Exception as e:
            print(f"店舗マスタセル保存エラー: {e}")
    
    def on_search_changed(self, text):
        """検索テキスト変更時の処理"""
        self.load_stores(text)
    
    def import_excel(self):
        """Excelインポート"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Excelファイルを選択",
            r"D:\HIRIO\docs\参考データ",
            "Excelファイル (*.xlsx *.xlsm);;すべてのファイル (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Excelファイルを読み込む
            stores = self.excel_importer.read_store_master_sheet(file_path)
            
            if not stores:
                QMessageBox.information(self, "インポート", "読み込めるデータがありませんでした")
                return
            
            # データ検証
            validation = self.excel_importer.validate_store_data(stores)
            
            if validation['error_count'] > 0:
                error_msg = "\n".join(validation['errors'])
                QMessageBox.warning(
                    self,
                    "インポートエラー",
                    f"{validation['error_count']}件のエラーが見つかりました:\n\n{error_msg}"
                )
                return
            
            # 確認ダイアログ
            warning_msg = ""
            if validation['warning_count'] > 0:
                warning_msg = f"\n\n警告 {validation['warning_count']}件:\n" + "\n".join(validation['warnings'][:5])
            
            reply = QMessageBox.question(
                self,
                "インポート確認",
                f"{validation['valid_count']}件のデータをインポートしますか？{warning_msg}",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # データをインポート
            imported_count = 0
            skipped_count = 0
            
            for store in stores:
                supplier_code = store.get('supplier_code')
                
                # 重複チェック
                if supplier_code and self.db.check_supplier_code_exists(supplier_code):
                    skipped_count += 1
                    continue
                
                try:
                    self.db.add_store(store)
                    imported_count += 1
                except Exception as e:
                    print(f"インポートエラー: {e}")
                    skipped_count += 1
            
            # 結果表示
            message = f"インポート完了\n\n追加: {imported_count}件"
            if skipped_count > 0:
                message += f"\nスキップ: {skipped_count}件（重複など）"
            
            QMessageBox.information(self, "インポート完了", message)
            
            # 一覧を再読み込み
            self.load_stores(self.search_edit.text())
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"Excelインポートに失敗しました:\n{str(e)}")
    
    def add_store(self):
        """店舗追加"""
        dialog = StoreEditDialog(self, custom_fields_def=self.custom_fields_def, initial_route_name=self.current_selected_route)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                # 店舗コードが空の場合は自動生成
                if not data.get('store_code'):
                    store_name = data.get('store_name', '')
                    if store_name:
                        data['store_code'] = self.db.get_next_store_code_from_store_name(store_name)
                self.db.add_store(data)
                QMessageBox.information(self, "完了", "店舗を追加しました")
                self.load_stores(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_store(self):
        """店舗編集"""
        selected = self.store_table.selectionModel().selectedRows() if self.store_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "編集する店舗を選択してください")
            return
        
        row = selected[0].row()
        id_item = self.store_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            QMessageBox.warning(self, "エラー", "選択行のIDが取得できません")
            return
        try:
            store_id = int(id_item.text())
        except ValueError:
            QMessageBox.warning(self, "エラー", "不正なID形式です")
            return
        store_data = self.db.get_store(store_id)
        
        if not store_data:
            QMessageBox.warning(self, "エラー", "店舗データが見つかりません")
            return
        
        dialog = StoreEditDialog(self, store_data=store_data, custom_fields_def=self.custom_fields_def)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.update_store(store_id, data)
                QMessageBox.information(self, "完了", "店舗を更新しました")
                self.load_stores(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_store(self):
        """店舗削除"""
        selected = self.store_table.selectionModel().selectedRows() if self.store_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "削除する店舗を選択してください")
            return
        
        row = selected[0].row()
        id_item = self.store_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            QMessageBox.warning(self, "エラー", "選択行のIDが取得できません")
            return
        try:
            store_id = int(id_item.text())
        except ValueError:
            QMessageBox.warning(self, "エラー", "不正なID形式です")
            return
        store_name = self.store_table.item(row, 4).text()
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"店舗 '{store_name}' を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            self.db.delete_store(store_id)
            QMessageBox.information(self, "完了", "店舗を削除しました")
            self.load_stores(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def manage_custom_fields(self):
        """カスタムフィールド管理"""
        from ui.custom_fields_dialog import CustomFieldsDialog
        dialog = CustomFieldsDialog(self, self.db)
        dialog.exec()
        self.load_stores(self.search_edit.text())  # カスタムフィールドが変わったので再読み込み
    
    def create_new_route(self):
        """新規ルート作成"""
        dialog = RouteManagementDialog(self, self.db, route_name=None)
        if dialog.exec() == QDialog.Accepted:
            # ルート一覧を再読み込み
            self.load_routes()
            # 店舗一覧を再読み込み
            self.load_stores(self.search_edit.text())
    
    def edit_route(self):
        """ルート編集"""
        # ルート選択プルダウンから選択中のルートを取得
        current_index = self.route_combo.currentIndex()
        if current_index < 0:
            QMessageBox.warning(self, "警告", "編集するルートを選択してください。")
            return
        
        # route_dataから実際のルート名を取得（コンボボックスと同じ順序で保持）
        if current_index >= len(self.route_data):
            QMessageBox.warning(self, "警告", "選択されたルートが見つかりません。")
            return
        
        selected_route = self.route_data[current_index]
        selected_route_name = selected_route.get('route_name', '')
        
        dialog = RouteManagementDialog(self, self.db, route_name=selected_route_name)
        if dialog.exec() == QDialog.Accepted:
            # ルート一覧を再読み込み
            self.load_routes()
            # 店舗一覧を再読み込み
            self.load_stores(self.search_edit.text())

    def delete_selected_route(self):
        """選択中のルートを削除"""
        current_index = self.route_combo.currentIndex()
        if current_index < 0:
            QMessageBox.warning(self, "警告", "削除するルートを選択してください。")
            return
        
        if current_index >= len(self.route_data):
            QMessageBox.warning(self, "警告", "選択されたルートが見つかりません。")
            return
        
        route_info = self.route_data[current_index]
        route_name = route_info.get('route_name', '')
        route_code = route_info.get('route_code', '')
        
        if not route_name:
            QMessageBox.warning(self, "警告", "ルート名が空のため削除できません。")
            return
        
        reply = QMessageBox.question(
            self,
            "選択ルート削除の確認",
            f"ルート「{route_name}（{route_code}）」を削除しますか？\n\n"
            f"このルートに属している店舗のルートコードから「{route_code}」を削除します。\n"
            f"削除後、どのルートにも属さない店舗はルートコードカラムが空白になります。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        
        try:
            # すべての店舗を取得し、該当ルートコードを除去
            stores = self.db.list_stores()
            for store in stores:
                store_id = store.get('id')
                if not store_id:
                    continue
                
                route_code_str = store.get('route_code') or ''
                
                # パターン1: 選択ルートコードがカンマ区切り（複数コードをまとめた表示）の場合は、
                #           文字列として完全一致する店舗のみを対象にし、丸ごと削除する。
                if "," in route_code:
                    if route_code_str != route_code:
                        continue
                    
                    new_route_code_str = None
                    new_codes = []
                else:
                    # パターン2: 単一コードの場合は、カンマ区切りリストからそのコードだけを取り除く
                    codes = [code.strip() for code in route_code_str.split(',') if code.strip()]
                    if not codes or route_code not in codes:
                        continue
                    
                    # このルートコードを削除
                    new_codes = [code for code in codes if code != route_code]
                    new_route_code_str = ",".join(new_codes) if new_codes else None
                
                update_data = {
                    'route_code': new_route_code_str,
                }
                
                # もしこの店舗が削除対象ルート名を「所属ルート名」として持っていて、
                # かつ他にルートコードが残っていなければ、所属ルート名もクリア
                if store.get('affiliated_route_name') == route_name and not new_codes:
                    update_data['affiliated_route_name'] = None
                
                self.db.update_store(store_id, update_data)
            
            # routes テーブルからも該当ルートを削除（存在しない場合はスキップ）
            self.db.delete_route(route_name, route_code)
            
            QMessageBox.information(self, "完了", f"ルート「{route_name}（{route_code}）」を削除しました。")
            
            # ルート一覧と店舗一覧を更新
            self.current_filtered_route = None
            self.current_selected_route = None
            self.load_routes()
            self.load_stores(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ルートの削除に失敗しました:\n{str(e)}")


class ExpenseDestinationEditDialog(QDialog):
    """経費先編集ダイアログ（名称入力時にチェーン店コードマッピングを参照して経費先コードを自動入力）"""
    
    def __init__(self, parent=None, dest_data=None):
        super().__init__(parent)
        self.dest_data = dest_data
        self.account_db = AccountTitleDatabase()
        self.store_db = StoreDatabase()
        self.setWindowTitle("経費先編集" if dest_data else "経費先追加")
        self.setModal(True)
        self.setup_ui()
        if dest_data:
            self.load_data()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        self.journal_combo = QComboBox()
        self.journal_combo.setEditable(True)
        titles = self.account_db.list_titles()
        for t in titles:
            self.journal_combo.addItem(t.get("name", ""))
        form_layout.addRow("科目（勘定科目）:", self.journal_combo)
        
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("経費先コード（任意）")
        form_layout.addRow("経費先コード:", self.code_edit)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("名称（例: コーナン本羽田店）")
        self.name_edit.textChanged.connect(self._on_name_changed_for_code)
        form_layout.addRow("名称:", self.name_edit)
        
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("住所")
        form_layout.addRow("住所:", self.address_edit)
        
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("電話番号")
        form_layout.addRow("電話番号:", self.phone_edit)
        
        self.registration_edit = QLineEdit()
        self.registration_edit.setPlaceholderText("登録番号（任意）")
        form_layout.addRow("登録番号:", self.registration_edit)
        
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("備考")
        form_layout.addRow("備考:", self.notes_edit)
        
        layout.addWidget(form_group)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _on_name_changed_for_code(self, name: str):
        """名称入力時にチェーン店コードマッピングを参照し、経費先コードを自動入力（既存は連番）"""
        name = (name or "").strip()
        if not name:
            return
        try:
            code = self.store_db.get_next_expense_destination_code_from_name(name)
            if code:
                self.code_edit.setText(code)
        except Exception:
            pass
    
    def load_data(self):
        if not self.dest_data:
            return
        self.journal_combo.setCurrentText(self.dest_data.get("journal") or "")
        self.code_edit.setText(self.dest_data.get("code") or "")
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self.dest_data.get("name") or "")
        self.name_edit.blockSignals(False)
        self.address_edit.setText(self.dest_data.get("address") or "")
        self.phone_edit.setText(self.dest_data.get("phone") or "")
        self.registration_edit.setText(self.dest_data.get("registration_number") or "")
        self.notes_edit.setText(self.dest_data.get("notes") or "")
    
    def get_data(self) -> Dict[str, Any]:
        name = self.name_edit.text().strip()
        if not name:
            return {}
        return {
            "journal": self.journal_combo.currentText().strip(),
            "code": self.code_edit.text().strip(),
            "name": name,
            "address": self.address_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "registration_number": self.registration_edit.text().strip(),
            "notes": self.notes_edit.text().strip(),
        }


class ExpenseDestinationListWidget(QWidget):
    """経費先一覧ウィジェット（店舗一覧と同様のUI、ルート関連なし・科目列あり）"""
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self.setup_ui()
        self.load_destinations()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setup_action_buttons(layout)
        self.setup_search_filter(layout)
        self.setup_info_bar(layout)
        self.setup_destinations_table(layout)
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_destination)
        button_layout.addWidget(add_btn)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_destination)
        button_layout.addWidget(edit_btn)
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_destination)
        delete_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; padding: 8px 16px; border-radius: 4px; }")
        button_layout.addWidget(delete_btn)
        button_layout.addStretch()
        parent_layout.addWidget(button_group)
    
    def setup_search_filter(self, parent_layout):
        search_group = QGroupBox("検索")
        search_layout = QHBoxLayout(search_group)
        search_layout.addWidget(QLabel("検索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("名称、経費先コード、科目で検索...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.search_edit.clear)
        search_layout.addWidget(clear_btn)
        parent_layout.addWidget(search_group)
    
    def setup_info_bar(self, parent_layout):
        info_group = QGroupBox("情報取得")
        info_layout = QHBoxLayout(info_group)
        fetch_info_btn = QPushButton("情報取得")
        fetch_info_btn.clicked.connect(self.fetch_missing_destination_info)
        fetch_info_btn.setStyleSheet("""
            QPushButton { background-color: #ffc107; color: #212529; padding: 8px 16px; border-radius: 4px; min-width: 120px; font-weight: bold; }
            QPushButton:hover { background-color: #e0a800; }
        """)
        info_layout.addWidget(fetch_info_btn)
        info_layout.addStretch()
        parent_layout.addWidget(info_group)
    
    def setup_destinations_table(self, parent_layout):
        table_group = QGroupBox("経費先一覧")
        table_layout = QVBoxLayout(table_group)
        self.dest_table = QTableWidget()
        self.dest_table.setAlternatingRowColors(True)
        self.dest_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dest_table.setEditTriggers(QTableWidget.DoubleClicked)
        self.dest_table.setTextElideMode(Qt.ElideNone)
        self.dest_table.setWordWrap(True)
        self.dest_table.setSortingEnabled(True)
        header = self.dest_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsClickable(True)
        self.dest_table.cellChanged.connect(self.on_dest_cell_changed)
        table_layout.addWidget(self.dest_table)
        self.dest_stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.dest_stats_label)
        parent_layout.addWidget(table_group)
    
    def load_destinations(self, search_term: str = ""):
        destinations = self.db.list_expense_destinations(search_term)
        self.update_destinations_table(destinations)
        self.update_statistics()
    
    def on_search_changed(self, text):
        self.load_destinations(text)
    
    def update_destinations_table(self, destinations: list):
        columns = ["ID", "科目", "経費先コード", "名称", "住所", "電話番号", "登録番号", "備考"]
        self.dest_table.setSortingEnabled(False)
        self.dest_table.setRowCount(len(destinations))
        self.dest_table.setColumnCount(len(columns))
        self.dest_table.setHorizontalHeaderLabels(columns)
        self.dest_table.blockSignals(True)
        for i, d in enumerate(destinations):
            self.dest_table.setItem(i, 0, QTableWidgetItem(str(d.get("id", ""))))
            self.dest_table.setItem(i, 1, QTableWidgetItem(d.get("journal") or ""))
            self.dest_table.setItem(i, 2, QTableWidgetItem(d.get("code") or ""))
            self.dest_table.setItem(i, 3, QTableWidgetItem(d.get("name") or ""))
            self.dest_table.setItem(i, 4, QTableWidgetItem(d.get("address") or ""))
            self.dest_table.setItem(i, 5, QTableWidgetItem(d.get("phone") or ""))
            self.dest_table.setItem(i, 6, QTableWidgetItem(d.get("registration_number") or ""))
            notes_item = QTableWidgetItem(d.get("notes") or "")
            notes_item.setData(Qt.UserRole, d.get("id"))
            self.dest_table.setItem(i, 7, notes_item)
        self.dest_table.blockSignals(False)
        self.dest_table.setSortingEnabled(True)
        self.dest_table.resizeColumnsToContents()
        if self.dest_table.columnCount() > 7:
            self.dest_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.dest_table.resizeRowsToContents()
    
    def update_statistics(self):
        destinations = self.db.list_expense_destinations()
        self.dest_stats_label.setText(f"統計: 経費先 {len(destinations)} 件")
    
    def add_destination(self):
        dialog = ExpenseDestinationEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                QMessageBox.warning(self, "入力エラー", "名称を入力してください。")
                return
            try:
                if data.get("code") and self.db.check_expense_destination_code_exists(data["code"]):
                    QMessageBox.warning(self, "重複", "その経費先コードは既に登録されています。")
                    return
                self.db.add_expense_destination(data)
                QMessageBox.information(self, "完了", "経費先を追加しました。")
                self.load_destinations(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_destination(self):
        selected = self.dest_table.selectionModel().selectedRows() if self.dest_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "編集する経費先を選択してください。")
            return
        row = selected[0].row()
        id_item = self.dest_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            return
        try:
            dest_id = int(id_item.text())
        except ValueError:
            return
        dest_data = self.db.get_expense_destination(dest_id)
        if not dest_data:
            return
        dialog = ExpenseDestinationEditDialog(self, dest_data=dest_data)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                return
            try:
                if data.get("code") and self.db.check_expense_destination_code_exists(data["code"], exclude_id=dest_id):
                    QMessageBox.warning(self, "重複", "その経費先コードは既に登録されています。")
                    return
                self.db.update_expense_destination(dest_id, data)
                QMessageBox.information(self, "完了", "経費先を更新しました。")
                self.load_destinations(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_destination(self):
        selected = self.dest_table.selectionModel().selectedRows() if self.dest_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "削除する経費先を選択してください。")
            return
        row = selected[0].row()
        id_item = self.dest_table.item(row, 0)
        if not id_item:
            return
        try:
            dest_id = int(id_item.text())
        except ValueError:
            return
        name = self.dest_table.item(row, 3).text() if self.dest_table.item(row, 3) else ""
        if QMessageBox.question(self, "削除確認", f"経費先「{name}」を削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.db.delete_expense_destination(dest_id)
            QMessageBox.information(self, "完了", "経費先を削除しました。")
            self.load_destinations(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def fetch_missing_destination_info(self):
        """住所・電話番号が欠けている経費先の情報をGoogle Maps APIから取得（店舗一覧と同じ機能）"""
        def safe_strip(value):
            if value is None:
                return ''
            return str(value).strip() if isinstance(value, str) else ''
        if get_store_info_from_google is None:
            QMessageBox.warning(self, "エラー", "Google Mapsサービスモジュールが読み込めませんでした。\ngooglemapsライブラリがインストールされているか確認してください。")
            return
        destinations = self.db.list_expense_destinations(self.search_edit.text())
        missing = [d for d in destinations if d.get("name") and (not safe_strip(d.get("address")) or not safe_strip(d.get("phone")))]
        if not missing:
            QMessageBox.information(self, "情報", "住所・電話番号が欠けている経費先はありません。")
            return
        if QMessageBox.question(self, "確認", f"{len(missing)}件の経費先の情報を取得しますか？\n（Google Maps APIを使用します）", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        progress = QProgressDialog("経費先情報を取得中...", "キャンセル", 0, len(missing), self)
        progress.setWindowTitle("情報取得中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        updated_count = 0
        failed_count = 0
        for i, d in enumerate(missing):
            if progress.wasCanceled():
                break
            dest_id = d.get("id")
            name = safe_strip(d.get("name"))
            current_address = safe_strip(d.get("address"))
            current_phone = safe_strip(d.get("phone"))
            progress.setValue(i)
            progress.setLabelText(f"取得中: {name}")
            QApplication.processEvents()
            info = get_store_info_from_google(name, language_code='ja')
            if info:
                addr = (info.get("address") or "") if not current_address else current_address
                phone = (info.get("phone") or "") if not current_phone else current_phone
                if addr or phone:
                    try:
                        self.db.update_expense_destination_address_phone(dest_id, addr, phone)
                        updated_count += 1
                    except Exception as e:
                        print(f"経費先情報更新エラー (ID: {dest_id}): {e}")
                        failed_count += 1
            else:
                failed_count += 1
        progress.setValue(len(missing))
        progress.close()
        QMessageBox.information(self, "完了", f"情報取得が完了しました。\n\n更新: {updated_count}件\n失敗: {failed_count}件")
        self.load_destinations(self.search_edit.text())
    
    def on_dest_cell_changed(self, row: int, column: int):
        """備考列の変更時のみDBに保存"""
        if column != 7:
            return
        try:
            item = self.dest_table.item(row, 7)
            if not item:
                return
            id_item = self.dest_table.item(row, 0)
            if not id_item:
                return
            dest_id = int(id_item.text())
            dest = self.db.get_expense_destination(dest_id)
            if not dest:
                return
            new_notes = item.text()
            self.db.update_expense_destination(dest_id, {
                "journal": dest.get("journal") or "",
                "code": dest.get("code") or "",
                "name": dest.get("name") or "",
                "address": dest.get("address") or "",
                "phone": dest.get("phone") or "",
                "registration_number": dest.get("registration_number") or "",
                "notes": new_notes,
            })
        except Exception as e:
            print(f"経費先備考保存エラー: {e}")


class StoreMasterWidget(QWidget):
    """店舗マスタ管理ウィジェット（タブコンテナ）"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """UIの設定（タブウィジェット）"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # タブウィジェットの作成
        self.tab_widget = QTabWidget()
        
        # 店舗一覧タブ
        self.store_list_widget = StoreListWidget()
        self.tab_widget.addTab(self.store_list_widget, "店舗一覧")
        
        # 店舗スコアタブ（想定粗利・仕入点数・評価の蓄積を店舗別に集計・スコア表示）
        self.store_score_widget = StoreScoreWidget()
        self.tab_widget.addTab(self.store_score_widget, "店舗スコア")
        
        # 経費先タブ（店舗一覧と法人マスタの間）
        self.expense_destination_widget = ExpenseDestinationListWidget()
        self.tab_widget.addTab(self.expense_destination_widget, "経費先")
        
        # 法人マスタタブ
        self.company_master_widget = CompanyMasterWidget()
        self.tab_widget.addTab(self.company_master_widget, "法人マスタ")
        
        layout.addWidget(self.tab_widget)

