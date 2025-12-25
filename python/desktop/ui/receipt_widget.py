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
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# デスクトップ側servicesを優先して読み込む
try:
    from services.receipt_service import ReceiptService  # python/desktop/services
    from services.receipt_matching_service import ReceiptMatchingService
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase


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


class ReceiptWidget(QWidget):
    """レシート管理ウィジェット"""
    receipt_processed = Signal(dict)
    
    def __init__(self, api_client=None, inventory_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.product_widget = None  # ProductWidgetへの参照
        self.receipt_service = ReceiptService()
        self.matching_service = ReceiptMatchingService()
        self.receipt_db = ReceiptDatabase()
        self.inventory_db = InventoryDatabase()
        self.store_db = StoreDatabase()
        self.account_title_db = AccountTitleDatabase()

        # フォルダ一括OCR用
        self.current_folder: Optional[Path] = None
        self.ocr_queue: List[str] = []
        self.batch_running: bool = False
        self.batch_total_count: int = 0  # 一括OCR処理の全体件数
        self.batch_processed_count: int = 0  # 一括OCR処理の処理済み件数
        self._store_name_cache: dict[str, str] = {}
        self.current_receipt_id = None
        self.current_receipt_data = None
        self.notifications_enabled = True
        
        self.setup_ui()

        # テーブルの列幅を復元
        restore_table_header_state(self.receipt_table, "ReceiptWidget/ReceiptTableHeaderState")
        restore_table_header_state(self.warranty_table, "ReceiptWidget/WarrantyTableHeaderState")
    
    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.receipt_table, "ReceiptWidget/ReceiptTableHeaderState")
        save_table_header_state(self.warranty_table, "ReceiptWidget/WarrantyTableHeaderState")
        
        # スプリッターの状態を即座に保存（タイマーを待たずに）
        if hasattr(self, 'receipt_splitter'):
            try:
                s = QSettings("HIRIO", "SedoriDesktopApp")
                sizes = self.receipt_splitter.sizes()
                if len(sizes) >= 2:
                    s.setValue("receipt/splitter_receipt_height", sizes[0])
                    s.setValue("receipt/splitter_warranty_height", sizes[1])
            except Exception as e:
                print(f"レシートスプリッター状態保存エラー: {e}")
    
    def set_product_widget(self, product_widget):
        """ProductWidgetへの参照を設定"""
        self.product_widget = product_widget
    
    def setup_ui(self):
        """UIの設定（シンプルなレイアウト）"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # 処理実行エリア
        self.setup_action_section()
        
        # レシート一覧
        self.setup_receipt_list_simple()
        
        # スプリッターでエリアの高さを調整可能にする
        self.setup_receipt_splitter()
    
    def setup_upload_section(self):
        """画像アップロードセクション"""
        upload_group = QGroupBox("レシート画像アップロード")
        upload_layout = QVBoxLayout(upload_group)
        self.upload_group = upload_group
        
        btn_layout = QHBoxLayout()

        # フォルダ選択ボタン（フォルダ内の全画像を一括OCR）
        self.folder_btn = QPushButton("フォルダ選択")
        self.folder_btn.clicked.connect(self.select_folder_for_batch)
        btn_layout.addWidget(self.folder_btn)

        # 単一画像選択ボタン
        self.upload_btn = QPushButton("画像を選択")
        self.upload_btn.clicked.connect(self.select_image)
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        btn_layout.addWidget(self.upload_btn)

        # 全件OCRボタン（選択フォルダ内の全画像を順番に処理）
        self.batch_btn = QPushButton("全件OCR")
        self.batch_btn.clicked.connect(self.start_batch_ocr)
        btn_layout.addWidget(self.batch_btn)

        btn_layout.addStretch()
        upload_layout.addLayout(btn_layout)
        
        self.image_path_label = QLabel("画像未選択")
        upload_layout.addWidget(self.image_path_label)
        
        self.layout.addWidget(upload_group)
    
    
    def setup_action_section(self):
        """処理実行エリア"""
        action_group = QGroupBox("処理実行")
        action_layout = QHBoxLayout(action_group)  # QVBoxLayoutからQHBoxLayoutに変更
        
        # すべてのボタンを1行に配置
        self.folder_btn = QPushButton("フォルダ選択")
        self.folder_btn.clicked.connect(self.select_folder_for_batch)
        action_layout.addWidget(self.folder_btn)
        
        self.folder_label = QLabel("未選択")
        self.folder_label.setStyleSheet("color: #bbb;")
        self.folder_label.setWordWrap(False)  # 折り返しを無効化
        self.folder_label.setMaximumWidth(150)  # 最大幅を制限
        action_layout.addWidget(self.folder_label)
        
        self.process_btn = QPushButton("OCR処理")
        self.process_btn.clicked.connect(self.process_selected_file)
        action_layout.addWidget(self.process_btn)
        
        self.batch_btn = QPushButton("全件OCR")
        self.batch_btn.clicked.connect(self.start_batch_ocr)
        action_layout.addWidget(self.batch_btn)
        
        self.bulk_match_btn = QPushButton("一括マッチング")
        self.bulk_match_btn.clicked.connect(self.bulk_match_receipts)
        action_layout.addWidget(self.bulk_match_btn)
        
        self.bulk_rename_btn = QPushButton("一括リネーム")
        self.bulk_rename_btn.clicked.connect(self.bulk_rename_receipts)
        action_layout.addWidget(self.bulk_rename_btn)
        
        self.verify_btn = QPushButton("照合チェック")
        self.verify_btn.clicked.connect(self.verify_receipts_with_purchases)
        action_layout.addWidget(self.verify_btn)
        
        self.confirm_btn = QPushButton("確定")
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        self.confirm_btn.clicked.connect(self.confirm_receipt_linkage)
        action_layout.addWidget(self.confirm_btn)
        
        self.delete_row_btn = QPushButton("選択行削除")
        self.delete_row_btn.setEnabled(False)
        self.delete_row_btn.clicked.connect(self.delete_selected_receipts)
        action_layout.addWidget(self.delete_row_btn)
        
        self.delete_all_btn = QPushButton("全件削除")
        self.delete_all_btn.clicked.connect(self.delete_all_receipts)
        action_layout.addWidget(self.delete_all_btn)
        
        action_layout.addStretch()
        
        self.layout.addWidget(action_group)
    
    def setup_receipt_list_simple(self):
        """レシート一覧セクション（シンプル版）"""
        list_group = QGroupBox("レシート一覧")
        list_layout = QVBoxLayout(list_group)

        self.receipt_table = QTableWidget()
        # 0列目のIDは非表示（内部用）、1列目に種別、2列目に科目、3列目に画像ファイル名
        self.receipt_table.setColumnCount(11)
        self.receipt_table.setHorizontalHeaderLabels([
            "ID(内部)", "種別", "科目", "画像ファイル名", "日付",
            "店舗名", "電話番号", "合計", "差額", "店舗コード", "SKU"
        ])
        self.receipt_table.horizontalHeader().setStretchLastSection(True)
        self.receipt_table.itemDoubleClicked.connect(self.on_receipt_double_clicked)
        self.receipt_table.itemSelectionChanged.connect(self.on_receipt_selection_changed)
        # 右クリックメニューを有効化
        self.receipt_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.receipt_table.customContextMenuRequested.connect(self.on_receipt_table_context_menu)
        list_layout.addWidget(self.receipt_table)

        # ID列はユーザーには見せない
        self.receipt_table.setColumnHidden(0, True)

        # 「科目」列はコンボボックスで編集（通常時はテキストだけ表示される）
        self.account_title_delegate = AccountTitleDelegate(
            self.receipt_table, self.receipt_db, self.account_title_db
        )
        self.receipt_table.setItemDelegateForColumn(2, self.account_title_delegate)
        
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_receipt_splitter()で追加される
        self.receipt_list_group = list_group

        # 保証書一覧エリア
        warranty_group = QGroupBox("保証書一覧")
        warranty_layout = QVBoxLayout(warranty_group)

        self.warranty_table = QTableWidget()
        # 0列目は内部ID、ユーザーには非表示
        self.warranty_table.setColumnCount(11)
        self.warranty_table.setHorizontalHeaderLabels([
            "ID(内部)", "種別", "画像ファイル名", "日付",
            "店舗名", "電話番号", "店舗コード", "SKU", "商品名", "保証期間(日)", "保証最終日"
        ])
        self.warranty_table.horizontalHeader().setStretchLastSection(True)
        self.warranty_table.setColumnHidden(0, True)
        # 保証期間編集時の処理
        self.warranty_table.cellChanged.connect(self.on_warranty_cell_changed)
        # 画像名ダブルクリックで拡大表示
        self.warranty_table.itemDoubleClicked.connect(self.on_warranty_item_double_clicked)
        # セルクリックで画像を開く（画像ファイル名列のみ）
        self.warranty_table.cellClicked.connect(self.on_warranty_table_cell_clicked)
        # コンテキストメニューを有効化
        self.warranty_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.warranty_table.customContextMenuRequested.connect(self.on_warranty_table_context_menu)
        warranty_layout.addWidget(self.warranty_table)

        # スプリッターで管理するため、固定高さの設定を削除
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_receipt_splitter()で追加される
        self.warranty_list_group = warranty_group

        # 照合チェック情報表示エリア
        info_group = QGroupBox("照合チェック情報")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(5, 5, 5, 5)
        info_layout.setSpacing(2)
        self.verification_info_text = QTextEdit()
        self.verification_info_text.setReadOnly(True)
        self.verification_info_text.setFixedHeight(50)
        self.verification_info_text.setPlaceholderText("照合チェックボタンをクリックすると、レシートと仕入DBの照合結果が表示されます。")
        info_layout.addWidget(self.verification_info_text)
        self.layout.addWidget(info_group)

        self.refresh_receipt_list()
    
    def setup_receipt_splitter(self):
        """スプリッターでレシート一覧と保証書一覧の高さを調整可能にする"""
        # スプリッターを作成（縦方向）
        self.receipt_splitter = QSplitter(Qt.Vertical)
        
        # エリアをスプリッターに追加
        self.receipt_splitter.addWidget(self.receipt_list_group)
        self.receipt_splitter.addWidget(self.warranty_list_group)
        
        # 初期の高さ比率を設定（レシート一覧: 保証書一覧 = 3:1）
        self.receipt_splitter.setStretchFactor(0, 3)  # レシート一覧
        self.receipt_splitter.setStretchFactor(1, 1)  # 保証書一覧
        
        # スプリッターの状態変更を監視して保存
        self.receipt_splitter.splitterMoved.connect(self.save_receipt_splitter_state)
        
        # レイアウトに追加（照合チェック情報の前に挿入）
        # レシート一覧と保証書一覧が既にレイアウトに追加されている場合は削除
        layout = self.layout
        receipt_index = -1
        warranty_index = -1
        info_group_index = -1
        
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if widget == self.receipt_list_group:
                    receipt_index = i
                elif widget == self.warranty_list_group:
                    warranty_index = i
                elif isinstance(widget, QGroupBox) and widget.title() == "照合チェック情報":
                    info_group_index = i
        
        # 既に追加されている場合は削除
        if receipt_index >= 0:
            layout.removeWidget(self.receipt_list_group)
        if warranty_index >= 0:
            layout.removeWidget(self.warranty_list_group)
        
        # スプリッターを照合チェック情報の前に挿入
        if info_group_index >= 0:
            layout.insertWidget(info_group_index, self.receipt_splitter, 1)  # stretch factor = 1
        else:
            # 見つからない場合は最後に追加
            layout.addWidget(self.receipt_splitter, 1)  # stretch factor = 1
        
        # ウィンドウが表示された後にスプリッターの状態を復元
        restore_timer = QTimer()
        restore_timer.setSingleShot(True)
        restore_timer.timeout.connect(self.restore_receipt_splitter_state)
        restore_timer.start(100)  # 100ms後に復元
    
    def save_receipt_splitter_state(self):
        """スプリッターの状態を保存（デバウンス処理付き）"""
        # 頻繁に呼ばれるので、少し遅延させてから保存
        if not hasattr(self, '_receipt_splitter_save_timer'):
            self._receipt_splitter_save_timer = QTimer()
            self._receipt_splitter_save_timer.setSingleShot(True)
            def _batched_save():
                try:
                    s = QSettings("HIRIO", "SedoriDesktopApp")
                    # スプリッターの各エリアのサイズを保存
                    sizes = self.receipt_splitter.sizes()
                    if len(sizes) >= 2:
                        s.setValue("receipt/splitter_receipt_height", sizes[0])
                        s.setValue("receipt/splitter_warranty_height", sizes[1])
                except Exception as e:
                    print(f"レシートスプリッター状態保存エラー: {e}")
            self._receipt_splitter_save_timer.timeout.connect(_batched_save)
        
        # タイマーをリセット（500ms後に保存）
        self._receipt_splitter_save_timer.stop()
        self._receipt_splitter_save_timer.start(500)
    
    def restore_receipt_splitter_state(self):
        """スプリッターの状態を復元"""
        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            receipt_height = s.value("receipt/splitter_receipt_height", None, type=int)
            warranty_height = s.value("receipt/splitter_warranty_height", None, type=int)
            
            if receipt_height is not None and warranty_height is not None and receipt_height > 0 and warranty_height > 0:
                # 保存されたサイズを復元
                self.receipt_splitter.setSizes([receipt_height, warranty_height])
            else:
                # デフォルトの比率を設定（レシート一覧: 保証書一覧 = 3:1）
                # 実際のサイズはウィンドウサイズに応じて自動調整される
                pass
        except Exception as e:
            print(f"レシートスプリッター状態復元エラー: {e}")
    
    def select_image(self):
        """画像ファイルを選択"""
        # デフォルトディレクトリを設定（暫定的）
        default_dir = str(self.current_folder) if self.current_folder else r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "レシート画像を選択",
            default_dir,
            "画像ファイル (*.jpg *.jpeg *.png *.bmp)"
        )
        if file_path:
            self.current_folder = Path(file_path).parent
            self.image_path_label.setText(f"選択: {Path(file_path).name}")
            self.process_image(file_path)

    def select_folder_for_batch(self):
        """フォルダを選択して、フォルダ内の全画像をOCRキューに追加"""
        default_dir = str(self.current_folder) if self.current_folder else r"D:\せどり総合"
        folder = QFileDialog.getExistingDirectory(
            self,
            "レシート画像フォルダを選択",
            default_dir,
        )
        if not folder:
            return
        self.current_folder = Path(folder)
        
        # OCRキューを更新
        image_paths: List[str] = []
        for entry in sorted(self.current_folder.iterdir()):
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower()
            if suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"):
                image_paths.append(str(entry))
        
        self.ocr_queue = image_paths
        self.folder_label.setText(f"{str(self.current_folder)} ({len(image_paths)}件)")
    
    def process_selected_file(self):
        """OCRキューから最初のファイルを処理（フォルダ選択後）"""
        if not self.ocr_queue:
            QMessageBox.information(self, "情報", "処理する画像がありません。先に「フォルダ選択」を行ってください。")
            return
        # キューから最初のファイルを処理
        path = self.ocr_queue[0]
        self.process_image(path)

    def start_batch_ocr(self):
        """選択されたフォルダ内の画像を順番にOCR処理"""
        if not self.ocr_queue:
            QMessageBox.information(self, "情報", "一括処理する画像がありません。先に「フォルダ選択」を行ってください。")
            return
        if self.batch_running:
            QMessageBox.information(self, "情報", "すでに一括OCR処理を実行中です。")
            return
        self.batch_running = True
        self.batch_total_count = len(self.ocr_queue)
        self.batch_processed_count = 0
        self._process_next_in_queue()

    def _process_next_in_queue(self):
        """OCRキューから次の1枚を取り出して処理"""
        if not self.ocr_queue:
            self.batch_running = False
            self.folder_label.setText(f"{str(self.current_folder)} - 一括OCR完了")
            QMessageBox.information(self, "一括OCR完了", "選択されたフォルダ内のすべての画像の処理が完了しました。")
            return
        next_path = self.ocr_queue.pop(0)
        remaining = len(self.ocr_queue)
        # 進捗率を計算（処理済み件数 / 全体件数）
        # 現在処理中の画像を含めて計算（処理済み + 1）
        current_processed = self.batch_processed_count + 1
        progress_percent = int((current_processed / self.batch_total_count) * 100) if self.batch_total_count > 0 else 0
        self.folder_label.setText(f"{str(self.current_folder)} - 処理中: {Path(next_path).name} （進捗: {progress_percent}% - {current_processed}/{self.batch_total_count}件、残り {remaining} 件）")
        self.process_image(next_path)
    
    def process_image(self, image_path: str):
        """画像を処理（OCR実行）"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(False)
            self.process_btn.setText("処理中...")
        
        self.ocr_thread = ReceiptOCRThread(self.receipt_service, image_path)
        self.ocr_thread.finished.connect(self.on_ocr_finished)
        self.ocr_thread.error.connect(self.on_ocr_error)
        self.ocr_thread.start()
    
    def on_ocr_finished(self, result: Dict[str, Any]):
        """OCR完了時の処理"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(True)
            self.process_btn.setText("OCR処理")
        
        self.current_receipt_id = result.get('id')
        self.current_receipt_data = result
        
        # OCR結果を表示（purchase_dateは yyyy/MM/dd で保存される想定だが、後方互換で両方対応）
        purchase_date = result.get('purchase_date')
        if purchase_date:
            try:
                # まず yyyy/MM/dd を試す
                date = QDate.fromString(purchase_date, "yyyy/MM/dd")
                if not date.isValid():
                    # 古いデータなど yyyy-MM-dd の場合も考慮
                    date = QDate.fromString(purchase_date.replace("/", "-"), "yyyy-MM-dd")
                if date.isValid():
                    if hasattr(self, 'date_edit'):
                        self.date_edit.setDate(date)
            except Exception:
                pass
        
        # 時刻を表示
        purchase_time = result.get('purchase_time')
        if hasattr(self, 'time_edit'):
            self.time_edit.setText(purchase_time or "")
        
        if hasattr(self, 'store_name_edit'):
            self.store_name_edit.setText(result.get('store_name_raw') or "")
        if hasattr(self, 'phone_edit'):
            self.phone_edit.setText(result.get('phone_number') or "")
        if hasattr(self, 'total_edit'):
            self.total_edit.setText(str(result.get('total_amount') or ""))
        if hasattr(self, 'discount_edit'):
            self.discount_edit.setText(str(result.get('discount_amount') or ""))
        
        # レジ袋金額を表示
        plastic_bag_amount = result.get('plastic_bag_amount')
        if hasattr(self, 'plastic_bag_edit'):
            self.plastic_bag_edit.setText(str(plastic_bag_amount) if plastic_bag_amount is not None else "")
        
        # 店舗コード候補を読み込み
        self.load_store_codes()
        
        # 仕入DBから自動検索・入力
        self.search_from_purchase_db()

        # 仕入データから自動マッチング候補を推定してDBにも反映
        try:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', []) if self.product_widget else []
            if purchase_records:
                candidates = self.matching_service.find_match_candidates(
                    self.current_receipt_data or result,
                    purchase_records,
                    preferred_store_code=self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None,
                )
                if candidates:
                    cand = candidates[0]
                    updates = {}
                    if cand.store_code:
                        # 店舗コードをコンボにも反映
                        if hasattr(self, 'store_code_combo'):
                            idx = self.store_code_combo.findData(cand.store_code)
                            if idx >= 0:
                                self.store_code_combo.setCurrentIndex(idx)
                        updates["store_code"] = cand.store_code
                    if updates and self.current_receipt_id:
                        self.receipt_db.update_receipt(self.current_receipt_id, updates)
        except Exception as e:
            # 自動マッチング失敗は致命的ではないのでログのみにする
            try:
                from pathlib import Path
                log_path = Path(__file__).resolve().parents[1] / "desktop_error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ReceiptWidget auto-match error: {e}\n")
            except Exception:
                pass

        if hasattr(self, 'match_btn'):
            self.match_btn.setEnabled(True)
        if hasattr(self, 'view_image_btn'):
            self.view_image_btn.setEnabled(True)
        # 一括処理中でない場合のみ通知を表示
        if self.notifications_enabled and not self.batch_running:
            QMessageBox.information(self, "OCR完了", "レシート情報を抽出しました。")
        self.receipt_processed.emit(result)
        # レシート一覧にも即反映
        self.refresh_receipt_list()

        # 一括処理中であれば次の画像を処理
        if self.batch_running:
            self.batch_processed_count += 1
            self._process_next_in_queue()
    
    def on_ocr_error(self, error_msg: str):
        """OCRエラー時の処理"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(True)
            self.process_btn.setText("OCR処理")
        # 一括処理中でない場合のみ通知を表示
        if self.notifications_enabled and not self.batch_running:
            QMessageBox.critical(self, "OCRエラー", f"OCR処理に失敗しました:\n{error_msg}")
        # 一括処理中ならスキップして次へ
        if self.batch_running:
            self.batch_processed_count += 1
            self._process_next_in_queue()
    
    def load_store_codes(self):
        """店舗コード候補を読み込み"""
        if not hasattr(self, 'store_code_combo'):
            return
        self.store_code_combo.clear()
        stores = self.store_db.list_stores()
        for store in stores:
            code = store.get('supplier_code')
            name = store.get('store_name')
            if code:
                self.store_code_combo.addItem(f"{code} - {name}", code)
    
    def search_from_purchase_db(self):
        """仕入DBから日付・店舗名・電話番号で検索して店舗コードと点数を自動入力"""
        if not self.product_widget:
            return
        
        # OCR結果から日付・店舗名・電話番号を取得
        # 日付は current_receipt_data を優先し、なければ date_edit から取得
        purchase_date = ""
        if self.current_receipt_data and self.current_receipt_data.get("purchase_date"):
            purchase_date = str(self.current_receipt_data.get("purchase_date")).strip()
        else:
            purchase_date = self.date_edit.date().toString("yyyy-MM-dd") if hasattr(self, 'date_edit') else ""
        store_name_raw = self.store_name_edit.text().strip() if hasattr(self, 'store_name_edit') else ""
        phone_number = self.phone_edit.text().strip() if hasattr(self, 'phone_edit') else ""
        
        if not purchase_date or not store_name_raw:
            return
        
        # 仕入DBの全データを取得
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            return
        
        # 店舗マスタから電話番号で店舗を検索
        stores = self.store_db.list_stores()
        
        # 電話番号で店舗を検索（部分一致）
        matched_store_code = None
        if phone_number:
            for store in stores:
                store_phone = store.get('phone') or ''
                if store_phone and (phone_number in store_phone or store_phone in phone_number):
                    # 店舗コード優先、なければ仕入れ先コード（互換性のため）
                    matched_store_code = store.get('store_code') or store.get('supplier_code')
                    break
        
        # 店舗名でも検索（電話番号で見つからない場合）
        if not matched_store_code:
            for store in stores:
                store_name = store.get('store_name') or ''
                # 店舗名の部分一致チェック
                if store_name and store_name_raw and (store_name_raw in store_name or store_name in store_name_raw):
                    # 店舗コード優先、なければ仕入れ先コード（互換性のため）
                    matched_store_code = store.get('store_code') or store.get('supplier_code')
                    break
        
        if not matched_store_code:
            return
        
        # 日付を正規化（yyyy-MM-dd形式に揃えて比較）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # 仕入DBから該当日付・店舗コードで検索
        matched_records = []
        for record in purchase_records:
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            
            # 日付の正規化
            normalized_record_date = record_date.replace('/', '-')
            if ' ' in normalized_record_date:
                normalized_record_date = normalized_record_date.split(' ')[0]
            
            # 日付と店舗コードでマッチング
            if normalized_record_date.startswith(normalized_date) and record_store_code == matched_store_code:
                matched_records.append(record)
        
        if matched_records:
            # 店舗コードを入力
            if hasattr(self, 'store_code_combo'):
                idx = self.store_code_combo.findData(matched_store_code)
                if idx >= 0:
                    self.store_code_combo.setCurrentIndex(idx)
            
            # 仕入れ点数を集計
            total_items = 0
            for record in matched_records:
                quantity = record.get('仕入れ個数') or record.get('quantity') or 0
                try:
                    total_items += int(quantity)
                except (ValueError, TypeError):
                    pass
            

    def set_notifications_enabled(self, enabled: bool):
        """OCR完了・エラー時のメッセージ表示を制御"""
        self.notifications_enabled = enabled
    
    def run_matching(self):
        """マッチングを実行"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 仕入DBデータを取得
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        
        # 仕入DBの全データを取得
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        
        # マッチング実行
        candidates = self.matching_service.find_match_candidates(
            self.current_receipt_data,
            purchase_records,
                    preferred_store_code=self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None,
        )
        
        if candidates:
            candidate = candidates[0]
            diff = candidate.diff
            
            # マッチング結果の点数を点数欄に入力
            if candidate.items_count > 0:
                # current_receipt_dataにも反映
                if self.current_receipt_data:
                    self.current_receipt_data['items_count'] = candidate.items_count
            
            if diff is not None and diff <= 10:
                if hasattr(self, 'match_result_label'):
                    self.match_result_label.setText(
                    f"マッチ成功: 差額 {diff}円（許容範囲内）\n"
                    f"店舗コード: {candidate.store_code}\n"
                    f"アイテム数: {candidate.items_count}"
                )
                if hasattr(self, 'confirm_btn'):
                    self.confirm_btn.setEnabled(True)
            else:
                if hasattr(self, 'match_result_label'):
                    self.match_result_label.setText(
                    f"マッチ候補あり（差額: {diff}円）\n"
                    f"確認してください。"
                )
                if hasattr(self, 'confirm_btn'):
                    self.confirm_btn.setEnabled(True)
        else:
            if hasattr(self, 'match_result_label'):
                self.match_result_label.setText("マッチする候補が見つかりませんでした。")
            if hasattr(self, 'confirm_btn'):
                self.confirm_btn.setEnabled(True)
    
    def confirm_receipt(self):
        """レシートを確定（学習も実行）"""
        if not self.current_receipt_id:
            return
        
        store_code = self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None
        if not store_code:
            QMessageBox.warning(self, "警告", "店舗コードを選択してください。")
            return
        
        # 日付を取得
        purchase_date = self.date_edit.date().toString("yyyy-MM-dd") if hasattr(self, 'date_edit') else ""
        if not purchase_date:
            QMessageBox.warning(self, "警告", "日付が設定されていません。")
            return
        
        # 現在の画像パスを取得
        current_receipt = self.receipt_db.get_receipt(self.current_receipt_id)
        if not current_receipt:
            QMessageBox.warning(self, "警告", "レシートデータが見つかりません。")
            return
        
        old_image_path = current_receipt.get('file_path')
        original_file_path = current_receipt.get('original_file_path')  # 元のファイルパス
        if not old_image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 新しい画像ファイル名を生成
        from pathlib import Path
        import os
        import traceback
        from datetime import datetime
        
        # デバッグログ出力先
        log_path = Path(__file__).resolve().parents[1] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] レシートリネーム処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        # DBのIDを取得（ファイル名に使用）
        db_receipt_id = self.current_receipt_id
        
        # 日付をyyyyMMdd形式に変換
        date_str = purchase_date.replace("-", "").replace("/", "").replace(".", "") if purchase_date else "UNKNOWN"
        if len(date_str) == 10:  # yyyy-MM-dd形式
            date_str = date_str[:4] + date_str[5:7] + date_str[8:10]
        elif len(date_str) != 8:
            date_str = "UNKNOWN"
        
        # 連番を決定（同じ日付・店舗コードのファイル名を検索）
        from pathlib import Path as PathLib
        existing_files = []
        if old_image_path:
            parent_dir = PathLib(old_image_path).parent
            pattern = f"{date_str}_{store_code}_*.jpg"
            for ext in ['.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG']:
                pattern_files = list(parent_dir.glob(f"{date_str}_{store_code}_*{ext}"))
                existing_files.extend(pattern_files)
        
        # 既存ファイルから最大の連番を取得
        max_number = 0
        for file_path in existing_files:
            try:
                stem = file_path.stem  # 拡張子なしのファイル名
                parts = stem.split('_')
                if len(parts) >= 3:
                    number_part = parts[-1]  # 最後の部分が連番
                    if number_part.isdigit():
                        max_number = max(max_number, int(number_part))
            except Exception:
                pass
        
        next_number = max_number + 1
        
        # 新しいファイル名を生成: {YYYYMMDD}_{store_code}_{連番}.{拡張子}
        old_image_file = Path(old_image_path)
        if not old_image_file.is_absolute():
            old_image_file = Path(os.path.abspath(old_image_path))
        
        new_image_name = f"{date_str}_{store_code}_{next_number:02d}{old_image_file.suffix}"
        new_image_path = old_image_file.parent / new_image_name
        
        # 同名のファイル名が存在するか確認
        if new_image_path.exists() and new_image_path != old_image_file:
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル名「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        _write_log(f"開始: DB ID={db_receipt_id}, コピー先パス={old_image_path}, 元のパス={original_file_path}, 新しいファイル名={new_image_name}")
        
        # コピー先ファイルのパスを絶対パスに正規化
        _write_log(f"コピー先パス解析: is_absolute={old_image_file.is_absolute()}, パス={old_image_file}")
        
        # 元のファイルパスを取得（リネーム対象）
        original_file = None
        if original_file_path:
            original_file = Path(original_file_path)
            if not original_file.is_absolute():
                original_file = Path(os.path.abspath(original_file_path))
            _write_log(f"元のファイルパス: {original_file}, 存在={original_file.exists() if original_file else False}")
        
        # コピー先ファイルの存在確認
        file_exists = old_image_file.exists()
        _write_log(f"コピー先ファイル存在確認: {file_exists}, パス={old_image_file}")
        
        if not file_exists:
            error_msg = (
                f"画像ファイルが見つかりません:\n{old_image_file}\n\n"
                f"元のパス: {old_image_path}"
            )
            _write_log(f"エラー: {error_msg}")
            QMessageBox.warning(self, "警告", error_msg)
            return
        
        # 元のファイルの新しいパスも生成
        new_original_path = None
        if original_file and original_file.exists():
            new_original_path = original_file.parent / f"{date_str}_{store_code}_{next_number:02d}{original_file.suffix}"
            _write_log(f"元のファイルの新しいパス: {new_original_path}")
        
        _write_log(f"新しいファイル名生成: {new_image_name}, コピー先パス={new_image_path}")
        
        # 同名ファイルが存在する場合の確認（自分自身でない場合のみ）
        if new_image_path.exists() and new_image_path != old_image_file:
            _write_log(f"同名ファイル存在: {new_image_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが上書きをキャンセル")
                return
        
        # 元のファイルも同名ファイルが存在する場合の確認
        if new_original_path and new_original_path.exists() and new_original_path != original_file:
            _write_log(f"元のファイルの同名ファイル存在: {new_original_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"元の画像ファイル「{new_original_path.name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが元のファイルの上書きをキャンセル")
                return
        
        # コピー先ファイルをリネーム（ファイル名が変更される場合のみ）
        if new_image_path != old_image_file:
            _write_log(f"コピー先リネーム実行: {old_image_file} -> {new_image_path}")
            try:
                import shutil
                # ファイルをリネーム（移動）
                _write_log(f"shutil.move実行前: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                shutil.move(str(old_image_file), str(new_image_path))
                _write_log(f"shutil.move実行後: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                
                # リネーム後のファイルが存在することを確認
                if not new_image_path.exists():
                    raise Exception(f"リネーム後のファイルが見つかりません: {new_image_path}")
                
                _write_log(f"コピー先リネーム成功: {new_image_path}")
            except Exception as e:
                error_detail = traceback.format_exc()
                _write_log(f"コピー先リネームエラー: {str(e)}\n{error_detail}")
                QMessageBox.critical(
                    self, "エラー",
                    f"画像ファイルのリネームに失敗しました:\n\n"
                    f"エラー: {str(e)}\n\n"
                    f"元のファイル: {old_image_file}\n"
                    f"新しいファイル: {new_image_path}\n\n"
                    f"詳細はログファイルを確認してください:\n{log_path}"
                )
                return
        else:
            _write_log(f"コピー先リネーム不要: ファイル名が同じです（{old_image_file} == {new_image_path}）")
        
        # 元のファイルもリネーム（存在する場合）
        if original_file and original_file.exists() and new_original_path:
            if new_original_path != original_file:
                _write_log(f"元のファイルリネーム実行: {original_file} -> {new_original_path}")
                try:
                    import shutil
                    _write_log(f"元のファイルshutil.move実行前: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    shutil.move(str(original_file), str(new_original_path))
                    _write_log(f"元のファイルshutil.move実行後: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    
                    # リネーム後のファイルが存在することを確認
                    if not new_original_path.exists():
                        raise Exception(f"元のファイルのリネーム後のファイルが見つかりません: {new_original_path}")
                    
                    _write_log(f"元のファイルリネーム成功: {new_original_path}")
                except Exception as e:
                    error_detail = traceback.format_exc()
                    _write_log(f"元のファイルリネームエラー: {str(e)}\n{error_detail}")
                    # 元のファイルのリネーム失敗は警告のみ（コピー先は成功しているため）
                    QMessageBox.warning(
                        self, "警告",
                        f"元の画像ファイルのリネームに失敗しました:\n\n"
                        f"エラー: {str(e)}\n\n"
                        f"元のファイル: {original_file}\n"
                        f"新しいファイル: {new_original_path}\n\n"
                        f"コピー先のリネームは成功しています。"
                    )
            else:
                _write_log(f"元のファイルリネーム不要: ファイル名が同じです（{original_file} == {new_original_path}）")
        
        # レシートDBを更新（店舗コード、画像パス）
        # リネームが実行された場合は新しいパス、実行されなかった場合は元のパスを使用
        final_image_path = str(new_image_path) if new_image_path != old_image_file else str(old_image_file)
        final_original_path = str(new_original_path) if (new_original_path and original_file and new_original_path != original_file) else original_file_path
        _write_log(f"DB更新: 最終的なコピー先パス={final_image_path}, 最終的な元のパス={final_original_path}")
        
        # 画像ファイル名を取得（識別子として使用）
        image_file_name = Path(final_image_path).stem  # 拡張子なしのファイル名
        
        # 時刻を取得（HH:MM形式）
        purchase_time = self.time_edit.text().strip()
        # 時刻の形式を検証（HH:MM形式）
        if purchase_time:
            import re
            if not re.match(r"^\d{1,2}:\d{2}$", purchase_time):
                # 形式が正しくない場合は警告（ただし処理は継続）
                QMessageBox.warning(self, "警告", f"時刻の形式が正しくありません（HH:MM形式で入力してください）: {purchase_time}")
                purchase_time = None
        
        updates = {
            "store_code": store_code,
            "file_path": final_image_path
        }
        if purchase_time:
            updates["purchase_time"] = purchase_time
        if final_original_path:
            updates["original_file_path"] = final_original_path
        
        # レジ袋金額を取得
        plastic_bag_text = self.plastic_bag_edit.text().strip() if hasattr(self, 'plastic_bag_edit') else ""
        plastic_bag_amount = None
        if plastic_bag_text:
            try:
                plastic_bag_amount = int(plastic_bag_text)
            except ValueError:
                pass
        if plastic_bag_amount is not None:
            updates["plastic_bag_amount"] = plastic_bag_amount
        
        _write_log(f"DB更新内容: {updates}")
        update_result = self.receipt_db.update_receipt(self.current_receipt_id, updates)
        _write_log(f"DB更新結果: {update_result}")
        
        # 学習
        self.matching_service.learn_store_correction(self.current_receipt_id, store_code)
        
        # レシートDBからファイルパスを取得
        receipt = self.receipt_db.get_receipt(db_receipt_id)
        receipt_image_path = None
        if receipt:
            receipt_image_path = receipt.get('original_file_path') or receipt.get('file_path')
        
        # 仕入DBの該当SKUに画像ファイル名を自動入力
        self._link_receipt_to_purchase_records(
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            store_code=store_code,
            image_file_name=image_file_name,
            db_receipt_id=db_receipt_id,
            receipt_image_path=receipt_image_path
        )
        
        QMessageBox.information(
            self, "確定",
            f"レシートを確定しました。\n画像ファイル: {new_image_name}"
        )
        
        self.refresh_receipt_list()
        self.reset_form()
    
    def _link_receipt_to_purchase_records(
        self,
        purchase_date: str,
        purchase_time: Optional[str],
        store_code: str,
        image_file_name: str,
        db_receipt_id: int,
        receipt_image_path: Optional[str] = None
    ):
        """
        仕入DBの該当SKUに画像ファイル名を自動入力
        
        Args:
            purchase_date: レシート日付（yyyy-MM-dd形式）
            purchase_time: レシート時刻（HH:MM形式、Noneの場合は時刻比較なし）
            store_code: 店舗コード
            image_file_name: 画像ファイル名（拡張子なし、識別子として使用）
            db_receipt_id: レシートDBのID
        """
        from pathlib import Path
        from datetime import datetime
        log_path = Path(__file__).resolve().parents[1] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 画像ファイル名自動入力処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        _write_log(f"開始: 日付={purchase_date}, 時刻={purchase_time}, 店舗コード={store_code}, 画像ファイル名={image_file_name}, DB ID={db_receipt_id}")
        
        # 仕入管理タブのデータを優先的に使用
        inventory_records = []
        inventory_data_exists = False
        if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
            inventory_data_exists = True
            try:
                import pandas as pd
                inventory_records = self.inventory_widget.inventory_data.fillna("").to_dict(orient="records")
                _write_log(f"仕入管理タブから{len(inventory_records)}件のデータを取得")
            except Exception as e:
                _write_log(f"仕入管理タブのデータ取得エラー: {e}")
        else:
            _write_log(f"仕入管理タブのデータが存在しません: inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}")
        
        # 仕入DBの全データを取得（フォールバック）
        purchase_records = []
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            _write_log(f"仕入DBから{len(purchase_records)}件のデータを取得")
        
        # 仕入管理タブのデータを優先、なければ仕入DBを使用
        if inventory_records:
            target_records = inventory_records
            _write_log("仕入管理タブのデータを使用")
        elif purchase_records:
            target_records = purchase_records
            _write_log("仕入DBのデータを使用")
        else:
            _write_log("データが見つかりません")
            return
        
        # 日付を正規化（yyyy-MM-dd形式）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # レシート時刻をdatetimeに変換（比較用）
        receipt_datetime = None
        if purchase_time:
            try:
                from datetime import datetime
                time_parts = purchase_time.split(':')
                if len(time_parts) == 2:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                    receipt_datetime = datetime.strptime(f"{normalized_date} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        
        # ProductDatabaseを取得
        from database.product_db import ProductDatabase
        product_db = ProductDatabase()
        
        matched_count = 0
        updated_count = 0
        
        # 仕入DBから該当するSKUを検索
        matched_skus = []
        for record in target_records:
            # SKUを取得
            sku = record.get('SKU') or record.get('sku') or ''
            if not sku or sku == '未実装':
                continue
            
            # 店舗コードでフィルタリング
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            if record_store_code != store_code:
                continue
            
            # 日付でフィルタリング
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            if not record_date:
                continue
            
            # 日付の正規化（時刻が含まれている場合も対応）
            normalized_record_date = str(record_date).replace('/', '-')
            record_date_only = normalized_record_date
            if ' ' in normalized_record_date:
                record_date_only = normalized_record_date.split(' ')[0]
            
            # 日付が一致しない場合はスキップ
            if not record_date_only.startswith(normalized_date):
                continue
            
            _write_log(f"マッチ候補: SKU={sku}, 日付={record_date}, 店舗コード={record_store_code}")
            
            # レシート時刻より前のSKUのみを対象
            if receipt_datetime:
                try:
                    # 仕入データの時刻を取得
                    record_datetime_str = str(record.get('仕入れ日') or record.get('purchase_date') or '')
                    record_datetime = None
                    
                    if ' ' in record_datetime_str:
                        # 時刻が含まれている場合
                        # フォーマットを正規化（/を-に変換）
                        normalized_datetime_str = record_datetime_str.replace('/', '-')
                        # 複数のフォーマットに対応
                        datetime_formats = [
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M",
                            "%Y/%m/%d %H:%M:%S",
                            "%Y/%m/%d %H:%M",
                        ]
                        for fmt in datetime_formats:
                            try:
                                record_datetime = datetime.strptime(normalized_datetime_str, fmt)
                                break
                            except ValueError:
                                continue
                    else:
                        # 時刻が含まれていない場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    if record_datetime is None:
                        # パースに失敗した場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    # レシート時刻より後の場合はスキップ
                    if record_datetime >= receipt_datetime:
                        _write_log(f"時刻フィルタ: SKU={sku} はレシート時刻より後（{record_datetime} >= {receipt_datetime}）")
                        continue
                except Exception as e:
                    # 時刻の比較に失敗した場合はスキップ
                    _write_log(f"時刻比較エラー: SKU={sku}, エラー={e}, record_datetime_str={record_datetime_str}")
                    continue
            
            # 既にレシートIDが設定されているか確認
            # 仕入管理タブのデータに既にレシートIDがある場合はスキップ
            if inventory_records:
                existing_receipt_id = record.get('レシートID') or record.get('receipt_id') or ''
                if existing_receipt_id:
                    _write_log(f"スキップ: SKU={sku} は既にレシートID={existing_receipt_id}が設定されています")
                    continue
            
            # ProductDatabaseから現在のレシートIDを確認
            product = product_db.get_by_sku(sku)
            product_already_has_receipt_id = False
            if product:
                # productsテーブルに存在する場合
                if product.get('receipt_id'):
                    # 既にレシートIDが設定されている場合でも、UI更新は実行する
                    product_already_has_receipt_id = True
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"情報: SKU={sku} はproductsテーブルに既にレシートID={product.get('receipt_id')}が設定されています（UI更新のみ実行）")
                else:
                    # レシートIDを設定
                    try:
                        # ProductDatabaseのlink_receiptメソッドを使用
                        # receipt_idは整数（DBのID）を使用
                        if product_db.link_receipt(sku, db_receipt_id):
                            updated_count += 1
                            matched_count += 1
                            matched_skus.append(sku)
                            _write_log(f"更新成功: SKU={sku} にレシートID={db_receipt_id}を設定")
                    except Exception as e:
                        # エラーはログに記録して続行
                        _write_log(f"エラー: SKU={sku}, エラー={e}")
            else:
                # productsテーブルに存在しない場合は、仕入DBのデータからproductsテーブルに登録
                try:
                    # 仕入DBのデータから商品情報を構築
                    product_data = {
                        "sku": sku,
                        "jan": record.get('JAN') or record.get('jan') or None,
                        "asin": record.get('ASIN') or record.get('asin') or None,
                        "product_name": record.get('商品名') or record.get('product_name') or None,
                        "purchase_date": record_date_only,
                        "purchase_price": record.get('仕入れ価格') or record.get('purchase_price') or None,
                        "quantity": record.get('仕入れ個数') or record.get('quantity') or None,
                        "store_code": store_code,
                        "store_name": record.get('店舗名') or record.get('store_name') or None,
                        "receipt_id": db_receipt_id,
                    }
                    # 数値型の変換
                    if product_data.get("purchase_price"):
                        try:
                            product_data["purchase_price"] = int(product_data["purchase_price"])
                        except (ValueError, TypeError):
                            product_data["purchase_price"] = None
                    if product_data.get("quantity"):
                        try:
                            product_data["quantity"] = int(product_data["quantity"])
                        except (ValueError, TypeError):
                            product_data["quantity"] = None
                    
                    # productsテーブルに登録
                    product_db.upsert(product_data)
                    updated_count += 1
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"新規登録成功: SKU={sku} をproductsテーブルに登録（レシートID={db_receipt_id}）")
                except Exception as e:
                    # エラーはログに記録して続行
                    _write_log(f"新規登録エラー: SKU={sku}, エラー={e}")
            
            # 仕入管理タブのデータにもレシートIDを設定
            # inventory_dataが存在する場合はinventory_dataを更新
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            _write_log(f"デバッグ: inventory_data_exists={inventory_data_exists}, inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}, filtered_data={self.inventory_widget.filtered_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') else None}")
            
            # inventory_dataが存在する場合
            if inventory_data_exists and self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"仕入管理タブ更新開始: SKU={sku}, inventory_data存在={self.inventory_widget.inventory_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.inventory_data.columns:
                        self.inventory_widget.inventory_data['レシートID'] = ''
                        _write_log("レシートID列を追加しました")
                    
                    # inventory_dataから該当SKUの行を検索
                    matched_in_inventory = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"SKU検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"inventory_data行数: {len(self.inventory_widget.inventory_data)}")
                    
                    for idx, row in self.inventory_widget.inventory_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if idx < 5:  # 最初の5行だけログ出力（デバッグ用）
                            _write_log(f"SKU比較[{idx}]: row_sku='{row_sku}', target_sku='{sku}', 一致={is_match}")
                        
                        if is_match:
                            # 画像ファイル名を設定（識別子として使用）
                            self.inventory_widget.inventory_data.at[idx, 'レシートID'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                if 'レシート画像パス' not in self.inventory_widget.inventory_data.columns:
                                    self.inventory_widget.inventory_data['レシート画像パス'] = ''
                                self.inventory_widget.inventory_data.at[idx, 'レシート画像パス'] = receipt_image_path
                            matched_in_inventory = True
                            _write_log(f"仕入管理タブ更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.inventory_data.at[idx, 'レシートID']
                            _write_log(f"設定確認: idx={idx}の画像ファイル名={updated_value}")
                            break
                    
                    if not matched_in_inventory:
                        _write_log(f"警告: SKU={sku} がinventory_dataに見つかりませんでした（全{len(self.inventory_widget.inventory_data)}行を検索）")
                    
                    # filtered_dataも更新（表示用）
                    if hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                            self.inventory_widget.filtered_data['レシートID'] = ''
                        # filtered_dataからも該当SKUの行を検索して更新
                        matched_in_filtered = False
                        _write_log(f"filtered_data検索開始: target_sku='{sku}', filtered_data行数={len(self.inventory_widget.filtered_data)}")
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            row_sku = str(row.get('SKU') or '').strip()
                            row_sku_normalized = row_sku.lower()
                            is_match = (row_sku == sku or 
                                       row_sku == str(sku).strip() or 
                                       row_sku_normalized == target_sku_normalized)
                            if is_match:
                                self.inventory_widget.filtered_data.at[idx, 'レシートID'] = image_file_name
                                # ファイルパス情報も保存（画像リンク用）
                                if receipt_image_path:
                                    if 'レシート画像パス' not in self.inventory_widget.filtered_data.columns:
                                        self.inventory_widget.filtered_data['レシート画像パス'] = ''
                                    self.inventory_widget.filtered_data.at[idx, 'レシート画像パス'] = receipt_image_path
                                matched_in_filtered = True
                                _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                                # 確認のため、設定後の値をログ出力
                                updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                                _write_log(f"filtered_data設定確認: idx={idx}の画像ファイル名={updated_value}")
                                break
                        
                        if not matched_in_filtered:
                            _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入管理タブ更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
            
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            elif self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"filtered_dataのみ更新開始: SKU={sku}, filtered_data存在={self.inventory_widget.filtered_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                        self.inventory_widget.filtered_data['レシートID'] = ''
                        _write_log("filtered_dataにレシートID列を追加しました")
                    
                    # filtered_dataから該当SKUの行を検索して更新
                    matched_in_filtered = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"filtered_data検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"filtered_data行数: {len(self.inventory_widget.filtered_data)}")
                    
                    for idx, row in self.inventory_widget.filtered_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if is_match:
                            self.inventory_widget.filtered_data.at[idx, 'レシートID'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                if 'レシート画像パス' not in self.inventory_widget.filtered_data.columns:
                                    self.inventory_widget.filtered_data['レシート画像パス'] = ''
                                self.inventory_widget.filtered_data.at[idx, 'レシート画像パス'] = receipt_image_path
                            matched_in_filtered = True
                            _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                            _write_log(f"filtered_data設定確認: idx={idx}の画像ファイル名={updated_value}")
                            break
                    
                    if not matched_in_filtered:
                        _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"filtered_data更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
        
        # 結果をログに記録
        _write_log(f"完了: マッチ={matched_count}件, 更新={updated_count}件, 画像ファイル名={image_file_name}, 対象SKU={matched_skus}")
        
        # 仕入管理タブのテーブル表示を更新（ループの外で一度だけ）
        # inventory_dataが存在する場合、またはfiltered_dataが存在する場合は更新する
        has_filtered_data = self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None
        _write_log(f"テーブル更新チェック: matched_count={matched_count}, inventory_data_exists={inventory_data_exists}, has_filtered_data={has_filtered_data}, inventory_widget={self.inventory_widget is not None}, has_update_table={hasattr(self.inventory_widget, 'update_table') if self.inventory_widget else False}")
        if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'update_table') and (inventory_data_exists or has_filtered_data):
            try:
                _write_log("仕入管理タブのテーブル表示を更新します")
                # 更新前のレシートID値を確認
                sample_skus = matched_skus[:3] if len(matched_skus) > 0 else []
                for sample_sku in sample_skus:
                    if hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                        for idx, row in self.inventory_widget.inventory_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(inventory_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                    elif hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(filtered_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                self.inventory_widget.update_table()
                _write_log("仕入管理タブのテーブル表示を更新しました")
            except Exception as e:
                import traceback
                _write_log(f"テーブル更新エラー: {e}\n{traceback.format_exc()}")
        else:
            _write_log("テーブル更新をスキップしました（条件を満たしていません）")
            # inventory_dataもfiltered_dataもNoneの場合、テーブルから直接レシートIDを設定
            if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'data_table'):
                try:
                    from PySide6.QtWidgets import QTableWidgetItem
                    _write_log("テーブルから直接レシートIDを設定します")
                    data_table = self.inventory_widget.data_table
                    row_count = data_table.rowCount()
                    _write_log(f"テーブル行数: {row_count}")
                    
                    # カラムヘッダーからSKUとレシートIDのインデックスを取得
                    column_headers = []
                    if hasattr(self.inventory_widget, 'column_headers'):
                        column_headers = self.inventory_widget.column_headers
                    else:
                        # カラムヘッダーが取得できない場合は、デフォルトの順序を使用
                        column_headers = [
                            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
                            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
                            "発送方法", "仕入先", "コンディション説明", "保証期間", "レシートID"
                        ]
                    
                    sku_column_idx = column_headers.index("SKU") if "SKU" in column_headers else 2
                    receipt_id_column_idx = column_headers.index("レシートID") if "レシートID" in column_headers else 16
                    _write_log(f"SKU列インデックス: {sku_column_idx}, レシートID列インデックス: {receipt_id_column_idx}")
                    
                    # テーブルの各行を検索して、該当するSKUの行にレシートIDを設定
                    updated_rows = 0
                    for row_idx in range(row_count):
                        sku_item = data_table.item(row_idx, sku_column_idx)
                        if sku_item:
                            row_sku = str(sku_item.text()).strip()
                            # SKUが「未実装」の場合はスキップ
                            if row_sku == "未実装" or not row_sku:
                                continue
                            
                            # マッチしたSKUか確認
                            if row_sku in matched_skus:
                                # 画像ファイル名を設定
                                receipt_id_item = data_table.item(row_idx, receipt_id_column_idx)
                                if receipt_id_item:
                                    receipt_id_item.setText(image_file_name)
                                else:
                                    receipt_id_item = QTableWidgetItem(image_file_name)
                                    data_table.setItem(row_idx, receipt_id_column_idx, receipt_id_item)
                                updated_rows += 1
                                _write_log(f"テーブル直接更新: 行={row_idx}, SKU={row_sku}, 画像ファイル名={image_file_name}")
                    
                    _write_log(f"テーブル直接更新完了: {updated_rows}行を更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"テーブル直接更新エラー: {e}\n{traceback.format_exc()}")
        
        if matched_count > 0 or updated_count > 0:
            # 商品DBタブの表示を更新（メソッドが存在する場合）
            if self.product_widget and hasattr(self.product_widget, 'load_products'):
                try:
                    self.product_widget.load_products()
                except Exception:
                    pass
            
            # 仕入DBタブ（ProductWidget内）のレシートIDを更新
            if self.product_widget and hasattr(self.product_widget, 'purchase_all_records'):
                try:
                    _write_log("仕入DBタブ（ProductWidget）のレシートIDを更新します")
                    updated_purchase_records = 0
                    for record in self.product_widget.purchase_all_records:
                        sku = record.get('SKU') or record.get('sku') or ''
                        if sku in matched_skus:
                            record['レシートID'] = image_file_name
                            # レシート画像列にもファイル名を設定（既存の処理と統一）
                            record['レシート画像'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                record['レシート画像パス'] = receipt_image_path
                            updated_purchase_records += 1
                            _write_log(f"仕入DBタブ更新: SKU={sku}, 画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}")
                    
                    # テーブルを再描画
                    if hasattr(self.product_widget, 'populate_purchase_table'):
                        self.product_widget.populate_purchase_table(self.product_widget.purchase_all_records)
                        _write_log(f"仕入DBタブテーブル再描画完了: {updated_purchase_records}件のレシートIDを更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入DBタブ更新エラー: {e}\n{traceback.format_exc()}")
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_receipt_id = None
        self.current_receipt_data = None
        if hasattr(self, 'date_edit'):
            self.date_edit.setDate(QDate.currentDate())
        if hasattr(self, 'time_edit'):
            self.time_edit.clear()
        if hasattr(self, 'store_name_edit'):
            self.store_name_edit.clear()
        if hasattr(self, 'phone_edit'):
            self.phone_edit.clear()
        if hasattr(self, 'total_edit'):
            self.total_edit.clear()
        if hasattr(self, 'discount_edit'):
            self.discount_edit.clear()
        if hasattr(self, 'plastic_bag_edit'):
            self.plastic_bag_edit.clear()
        if hasattr(self, 'store_code_combo'):
            self.store_code_combo.clear()
        if hasattr(self, 'match_result_label'):
            self.match_result_label.clear()
        if hasattr(self, 'confirm_btn'):
            self.confirm_btn.setEnabled(False)
        if hasattr(self, 'match_btn'):
            self.match_btn.setEnabled(False)
        if hasattr(self, 'view_image_btn'):
            self.view_image_btn.setEnabled(False)

    def _format_store_code_label(self, store_code: Optional[str], fallback_name: str = "") -> str:
        """店舗コードの表示ラベルを生成（新店舗コード + 店舗名）

        引数 store_code には旧仕入先コードが渡ってくる場合もあるため、
        DB から店舗情報を取得した際は stores.store_code を優先的に表示コードとして使用する。
        """
        original_code = (store_code or "").strip()
        code = original_code
        name = ""
        if code:
            if code not in self._store_name_cache:
                try:
                    # 店舗コード(store_code)を優先し、互換性のため仕入れ先コードも許容
                    store = self.store_db.get_store_by_code(code)
                    display_code = code
                    display_name = ""
                    if store:
                        # 表示用コードは stores.store_code を優先（なければ元のコード）
                        display_code = (store.get("store_code") or code).strip() or code
                        display_name = (store.get("store_name") or "").strip()
                    self._store_name_cache[code] = (display_code, display_name)
                except Exception:
                    self._store_name_cache[code] = (code, "")
            cached = self._store_name_cache.get(code)
            if isinstance(cached, tuple):
                code, name = cached
            else:
                name = cached or ""
        if not name:
            name = (fallback_name or "").strip()
        if code and name:
            return f"{code} {name}"
        return code or name

    @staticmethod
    def _normalize_purchase_date_text(value: Any) -> Optional[str]:
        """仕入日を yyyy/MM/dd 形式に正規化"""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("年", "/").replace("月", "/").replace("日", "")
        text = text.replace(".", "/").replace("-", "/")
        if "T" in text:
            text = text.split("T", 1)[0]
        if " " in text:
            text = text.split(" ", 1)[0]
        match = re.search(r"(20\d{2})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            y, m, d = match.groups()
            return f"{int(y):04d}/{int(m):02d}/{int(d):02d}"
        return None

    def _store_code_from_item(self, item: Optional[QTableWidgetItem]) -> str:
        """店舗コードセルから実際のコードのみを取得"""
        if not item:
            return ""
        data = item.data(Qt.UserRole)
        if data:
            return str(data).strip()
        text = item.text().strip()
        return text.split(" ")[0] if text else ""
    
    def refresh_receipt_list(self):
        """レシート一覧を更新"""
        receipts = self.receipt_db.find_by_date_and_store(None)
        self.receipt_table.setRowCount(0)
        if hasattr(self, "warranty_table"):
            self.warranty_table.blockSignals(True)
            self.warranty_table.setRowCount(0)
            self.warranty_table.blockSignals(False)

        from pathlib import Path
        receipt_row = 0
        warranty_row = 0

        # 勘定科目マスタを取得
        try:
            account_titles = [t.get("name", "") for t in self.account_title_db.list_titles()]
        except Exception:
            account_titles = []

        # デフォルト科目
        default_title = "仕入"
        if default_title not in account_titles:
            account_titles.insert(0, default_title)

        for receipt in receipts:
            # 種別判定（OCRテキストから簡易判定）
            doc_type = "レシート"
            ocr_text = receipt.get('ocr_text') or ""
            if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                doc_type = "保証書"

            file_path = receipt.get('original_file_path') or receipt.get('file_path') or ""
            file_name = ""
            if file_path:
                try:
                    file_name = Path(file_path).name
                except Exception:
                    file_name = file_path

            # レシート用テーブル: 種別=レシートのみ
            if doc_type == "レシート":
                row = receipt_row
                self.receipt_table.insertRow(row)
                receipt_id = receipt.get('id')
                self.receipt_table.setItem(row, 0, QTableWidgetItem(str(receipt_id)))
                self.receipt_table.setItem(row, 1, QTableWidgetItem(doc_type))

                # 科目（テキストとしてセット。編集時にデリゲートがプルダウンを出す）
                current_title = receipt.get('account_title') or default_title
                self.receipt_table.setItem(row, 2, QTableWidgetItem(current_title))

                # DBに既存科目がなければ、ここで一度だけデフォルトを保存
                if not receipt.get('account_title') and default_title:
                    try:
                        self.receipt_db.update_receipt(receipt_id, {"account_title": default_title})
                    except Exception:
                        pass

                # 画像ファイル名（識別子として使用）
                self.receipt_table.setItem(row, 3, QTableWidgetItem(file_name))

                # 日付（時刻も含める）
                purchase_date = receipt.get('purchase_date') or ""
                purchase_time = receipt.get('purchase_time') or ""
                date_display = purchase_date
                if purchase_time:
                    date_display = f"{purchase_date} {purchase_time}"
                self.receipt_table.setItem(row, 4, QTableWidgetItem(date_display))
                
                # 店舗名（OCRで取得した店舗名のまま表示）
                self.receipt_table.setItem(row, 5, QTableWidgetItem(receipt.get('store_name_raw') or ""))
                self.receipt_table.setItem(row, 6, QTableWidgetItem(receipt.get('phone_number') or ""))
                self.receipt_table.setItem(row, 7, QTableWidgetItem(str(receipt.get('total_amount') or "")))
                
                # 差額（8列目）- 紐付けSKUの合計金額とレシートの合計金額の差
                difference = receipt.get('price_difference') or None
                if difference is not None:
                    difference_text = f"¥{int(difference):,}"
                    difference_item = QTableWidgetItem(difference_text)
                    # 差額の色分け（プラス: 赤、マイナス: 緑、ゼロ: グレー）
                    if difference > 0:
                        difference_item.setForeground(QColor("#FF6B6B"))
                    elif difference < 0:
                        difference_item.setForeground(QColor("#4CAF50"))
                    else:
                        difference_item.setForeground(QColor("#666666"))
                    self.receipt_table.setItem(row, 8, difference_item)
                else:
                    self.receipt_table.setItem(row, 8, QTableWidgetItem(""))

                # 店舗コード（9列目）
                store_code = receipt.get('store_code') or ""
                store_label = self._format_store_code_label(store_code, receipt.get('store_name_raw') or "")
                store_item = QTableWidgetItem(store_label)
                store_item.setData(Qt.UserRole, store_code)
                self.receipt_table.setItem(row, 9, store_item)
                
                # SKU（10列目）
                linked_skus_text = receipt.get('linked_skus', '') or ''
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
                sku_display = ', '.join(linked_skus) if linked_skus else ''
                self.receipt_table.setItem(row, 10, QTableWidgetItem(sku_display))
                receipt_row += 1

            # 保証書用テーブル: 種別=保証書のみ
            if doc_type == "保証書" and hasattr(self, "warranty_table"):
                from PySide6.QtWidgets import QDateEdit

                self.warranty_table.blockSignals(True)
                row = warranty_row
                self.warranty_table.insertRow(row)
                self.warranty_table.setItem(row, 0, QTableWidgetItem(str(receipt.get('id'))))
                self.warranty_table.setItem(row, 1, QTableWidgetItem(doc_type))
                self.warranty_table.setItem(row, 2, QTableWidgetItem(file_name))
                self.warranty_table.setItem(row, 3, QTableWidgetItem(receipt.get('purchase_date') or ""))
                self.warranty_table.setItem(row, 4, QTableWidgetItem(receipt.get('store_name_raw') or ""))
                self.warranty_table.setItem(row, 5, QTableWidgetItem(receipt.get('phone_number') or ""))
                store_code = receipt.get('store_code') or ""
                store_label = self._format_store_code_label(store_code, receipt.get('store_name_raw') or "")
                store_item = QTableWidgetItem(store_label)
                store_item.setData(Qt.UserRole, store_code)
                self.warranty_table.setItem(row, 6, store_item)
                # SKU・商品名はプルダウンで候補をセット
                sku = receipt.get('sku') or ""
                product_name = receipt.get('product_name') or ""
                self._populate_warranty_product_cell(row, receipt, sku, product_name)

                # 保証期間(日)
                self.warranty_table.setItem(row, 9, QTableWidgetItem(str(receipt.get('warranty_days') or "")))

                # 保証最終日（カレンダー付き日付入力）
                date_edit = QDateEdit()
                date_edit.setCalendarPopup(True)
                
                # デフォルト値の設定順序：
                # 1. 既存の保証最終日があればそれを優先
                # 2. 保証期間(日)があれば日付+保証期間で計算
                # 3. どちらもなければ日付（保証書の日付）をデフォルトにする
                final_str = receipt.get('warranty_until') or ""
                qdate = None
                
                # 日付を取得（receiptから、またはテーブルの日付列から）
                purchase_date_str = receipt.get('purchase_date') or receipt.get('date') or ""
                if purchase_date_str:
                    purchase_date_str = purchase_date_str.replace("/", "-").split(" ")[0]
                
                if final_str:
                    qdate = QDate.fromString(final_str, "yyyy-MM-dd")
                
                # 保証期間(日)があれば日付+保証期間で計算
                if (not qdate or not qdate.isValid()) and purchase_date_str:
                    warranty_days = receipt.get('warranty_days')
                    if warranty_days:
                        try:
                            from datetime import datetime, timedelta
                            base = datetime.strptime(purchase_date_str, "%Y-%m-%d")
                            qdate = QDate.fromString(
                                (base + timedelta(days=int(warranty_days))).strftime("%Y-%m-%d"),
                                "yyyy-MM-dd",
                            )
                        except Exception:
                            pass
                    
                    # 保証期間がない場合は、日付（保証書の日付）をデフォルトにする
                    if not qdate or not qdate.isValid():
                        try:
                            from datetime import datetime
                            qdate = QDate.fromString(purchase_date_str, "yyyy-MM-dd")
                        except Exception:
                            pass
                
                if qdate and qdate.isValid():
                    date_edit.setDate(qdate)
                self.warranty_table.setCellWidget(row, 10, date_edit)

                # 日付変更時の処理
                date_edit.dateChanged.connect(lambda qd, r=row: self.on_warranty_date_changed(r, qd))

                self.warranty_table.blockSignals(False)
                warranty_row += 1

        self.on_receipt_selection_changed()

    def on_receipt_selection_changed(self):
        """レシート表の選択変更を監視"""
        if not hasattr(self, 'delete_row_btn'):
            return
        selection_model = self.receipt_table.selectionModel()
        has_selection = bool(selection_model and selection_model.selectedRows())
        self.delete_row_btn.setEnabled(has_selection)

    def delete_selected_receipts(self):
        """選択したレシートを削除（テスト用途）"""
        selection_model = self.receipt_table.selectionModel()
        if not selection_model:
            return
        rows = selection_model.selectedRows()
        if not rows:
            QMessageBox.information(self, "情報", "削除するレシートを選択してください。")
            return
        receipt_ids = []
        for idx in rows:
            item = self.receipt_table.item(idx.row(), 0)
            if item:
                try:
                    receipt_ids.append(int(item.text()))
                except ValueError:
                    continue
        if not receipt_ids:
            QMessageBox.warning(self, "警告", "選択された行に有効なIDがありません。")
            return
        if QMessageBox.question(
            self,
            "確認",
            f"選択された {len(receipt_ids)} 件のレシートを削除します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        deleted = 0
        for rid in receipt_ids:
            if self.receipt_db.delete_receipt_by_id(rid):
                deleted += 1
                if self.current_receipt_id == rid:
                    self.reset_form()
        self.refresh_receipt_list()
        QMessageBox.information(self, "削除完了", f"{deleted} 件のレシートを削除しました。")

    def delete_all_receipts(self):
        """レシートを全件削除（テスト用途）"""
        if QMessageBox.warning(
            self,
            "確認",
            "レシート情報をすべて削除します。テスト用途以外では実行しないでください。\n続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        deleted = self.receipt_db.delete_all_receipts()
        self.reset_form()
        self.refresh_receipt_list()
        QMessageBox.information(self, "削除完了", f"{deleted} 件のレシートを削除しました。")

    # ===== 一括処理 =====
    def bulk_match_receipts(self):
        """一覧に表示されている全レシートに対してマッチング候補を一括適用"""
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        receipts = self.receipt_db.find_by_date_and_store(None)
        print(f"[一括マッチング] 取得したレシート数: {len(receipts)}")
        updated = 0
        skipped_no_candidates = 0
        skipped_no_updates = 0
        for receipt in receipts:
            try:
                candidates = self.matching_service.find_match_candidates(
                    receipt,
                    purchase_records,
                    preferred_store_code=receipt.get('store_code'),
                )
                if not candidates:
                    skipped_no_candidates += 1
                    print(f"[一括マッチング] スキップ（候補なし）: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}")
                    continue
                cand = candidates[0]
                updates = {}
                # 店舗コード（候補が存在し、現在のレシートに店舗コードがない、または異なる場合に更新）
                current_store_code = receipt.get('store_code') or ""
                matched_store_code = cand.store_code
                # 店舗コードが空の場合は、候補から店舗コードを設定（手動で紐付けした場合も含む）
                if matched_store_code and matched_store_code != current_store_code:
                    updates["store_code"] = matched_store_code
                elif not current_store_code and matched_store_code:
                    # 店舗コードが空の場合、候補から店舗コードを設定
                    updates["store_code"] = matched_store_code
                    # 店舗名も更新（店舗コードから店舗名を取得）※現状はOCR結果を優先するため更新しない
                    try:
                        _ = self.store_db.get_store_by_code(matched_store_code)
                    except Exception:
                        pass
                
                # 紐付き候補SKUを取得
                # 1. 画像ファイル名で紐付けられたSKU（既に画像ファイル名がある場合）
                file_path = receipt.get('file_path') or ""
                image_file_name = Path(file_path).stem if file_path else ""  # 拡張子なしのファイル名
                candidate_skus = []
                if image_file_name and purchase_records:
                    for record in purchase_records:
                        record_receipt_id = record.get('レシートID') or record.get('receipt_id', '')
                        if record_receipt_id == image_file_name:
                            sku = record.get('SKU') or record.get('sku', '')
                            if sku and sku.strip() and sku not in candidate_skus:
                                candidate_skus.append(sku.strip())
                
                # 2. 日付と店舗コードで紐付けられたSKU（レシートIDがない場合のフォールバック）
                # レシート時間より前の時間に登録されたSKUを取得
                if not candidate_skus and purchase_records:
                    purchase_date = receipt.get('purchase_date') or ""
                    purchase_time = receipt.get('purchase_time') or ""  # HH:MM形式
                    store_code_for_match = matched_store_code or receipt.get('store_code') or ""
                    # 店舗コードのみを取得（表示ラベルから抽出）
                    if store_code_for_match and " " in store_code_for_match:
                        store_code_for_match = store_code_for_match.split(" ")[0]
                    
                    if purchase_date and store_code_for_match:
                        # レシートの日時をdatetimeオブジェクトに変換（比較用）
                        receipt_datetime = None
                        if purchase_time:
                            try:
                                from datetime import datetime
                                # 日付と時刻を結合してdatetimeオブジェクトを作成
                                date_str = purchase_date.replace("/", "-")
                                datetime_str = f"{date_str} {purchase_time}"
                                receipt_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                            except Exception:
                                pass
                        
                        # レシートの日付を正規化（yyyy-MM-dd形式に統一）
                        try:
                            from datetime import datetime
                            # レシート日付をdatetimeオブジェクトに変換（日付のみ）
                            receipt_date_obj = None
                            if "/" in purchase_date:
                                receipt_date_obj = datetime.strptime(purchase_date, "%Y/%m/%d").date()
                            elif "-" in purchase_date:
                                receipt_date_obj = datetime.strptime(purchase_date[:10], "%Y-%m-%d").date()
                        except Exception:
                            receipt_date_obj = None
                        
                        for record in purchase_records:
                            record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                            if not record_date:
                                continue
                            
                            # 仕入DBの日付を正規化して比較
                            try:
                                from datetime import datetime
                                record_date_str = str(record_date).strip()
                                
                                # 時刻が含まれている場合は日付部分のみを取得
                                if " " in record_date_str:
                                    record_date_str = record_date_str.split(" ")[0]
                                if "T" in record_date_str:
                                    record_date_str = record_date_str.split("T")[0]
                                
                                # 日付をdateオブジェクトに変換
                                record_date_obj = None
                                if "/" in record_date_str:
                                    record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                                elif "-" in record_date_str:
                                    record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                                
                                # 日付が一致しない場合はスキップ
                                if receipt_date_obj and record_date_obj and receipt_date_obj != record_date_obj:
                                    continue
                                
                                # 日付が一致するか、または日付比較ができない場合は文字列比較
                                date_matches = False
                                if receipt_date_obj and record_date_obj:
                                    date_matches = (receipt_date_obj == record_date_obj)
                                else:
                                    # フォールバック: 文字列比較
                                    normalized_receipt_date = purchase_date.replace("-", "/")
                                    normalized_record_date = str(record_date).replace("-", "/")
                                    date_matches = normalized_receipt_date[:10] in normalized_record_date[:10]
                                
                                # 仕入DBでは「仕入先」カラムに店舗コードが格納されている
                                record_store_code = record.get('仕入先') or record.get('店舗コード') or record.get('store_code', '')
                                # 店舗コードのみを取得（表示ラベルから抽出）
                                if record_store_code and " " in str(record_store_code):
                                    record_store_code = str(record_store_code).split(" ")[0]
                                
                                # 日付と店舗コードが一致する場合
                                if date_matches and record_store_code == store_code_for_match:
                                    # レシート時間より前の時間に登録されたSKUのみを取得
                                    sku = record.get('SKU') or record.get('sku', '')
                                    if not sku or not sku.strip():
                                        continue
                                    sku = sku.strip()
                                    
                                    # 時刻比較が必要な場合のみ実行
                                    should_add = True
                                    if receipt_datetime:
                                        # created_atが存在する場合、時刻比較を行う
                                        record_created_at = record.get('created_at') or record.get('登録日時') or ""
                                        if record_created_at:
                                            try:
                                                from datetime import datetime
                                                # created_atをdatetimeオブジェクトに変換
                                                record_dt = None
                                                if isinstance(record_created_at, str):
                                                    # 文字列の場合、複数の形式に対応
                                                    record_created_at_clean = str(record_created_at).strip()
                                                    if 'T' in record_created_at_clean:
                                                        # ISO形式: "2024-12-05T10:30:00" または "2024-12-05T10:30:00Z"
                                                        if record_created_at_clean.endswith('Z'):
                                                            record_created_at_clean = record_created_at_clean[:-1]
                                                        if len(record_created_at_clean) >= 19:
                                                            record_dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                    elif ' ' in record_created_at_clean:
                                                        # "YYYY-MM-DD HH:MM:SS"形式
                                                        if len(record_created_at_clean) >= 19:
                                                            record_dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                                else:
                                                    # datetimeオブジェクトの場合
                                                    record_dt = record_created_at
                                                
                                                # レシート時間より前の時間に登録されたSKUのみを追加
                                                if record_dt:
                                                    should_add = (record_dt < receipt_datetime)
                                            except Exception as e:
                                                # 時刻比較に失敗した場合は、日付と店舗コードが一致するSKUを全て追加
                                                should_add = True
                                    
                                    if should_add and sku not in candidate_skus:
                                        candidate_skus.append(sku)
                            except Exception:
                                # 日付比較に失敗した場合はスキップ
                                continue
                
                # 紐付き候補SKUを更新（既存のlinked_skusに追加、重複を避ける）
                if candidate_skus:
                    existing_skus_text = receipt.get('linked_skus', '') or ''
                    existing_skus = [s.strip() for s in existing_skus_text.split(',') if s.strip()] if existing_skus_text else []
                    # 既存のSKUと候補SKUをマージ（重複を避ける）
                    merged_skus = list(set(existing_skus + candidate_skus))
                    updates["linked_skus"] = ','.join(merged_skus)
                    
                    # 紐付けSKUの合計金額を計算（仕入れ個数 × 仕入れ価格）
                    sku_total = 0
                    for sku in merged_skus:
                        for record in purchase_records:
                            record_sku = record.get('SKU') or record.get('sku', '')
                            if record_sku and record_sku.strip() == sku:
                                # 仕入れ価格を取得
                                price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                                try:
                                    price = float(price) if price else 0
                                except (ValueError, TypeError):
                                    price = 0
                                # 仕入れ個数を取得
                                quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                                try:
                                    quantity = float(quantity) if quantity else 1
                                except (ValueError, TypeError):
                                    quantity = 1
                                # 金額 = 仕入れ個数 × 仕入れ価格
                                total_amount = price * quantity
                                sku_total += total_amount
                                break
                    
                    # レシートの合計金額を取得
                    receipt_total = receipt.get('total_amount') or 0
                    try:
                        receipt_total = int(receipt_total) if receipt_total else 0
                    except (ValueError, TypeError):
                        receipt_total = 0
                    
                    # 差額を計算
                    difference = sku_total - receipt_total
                    updates["price_difference"] = int(difference)
                
                if updates:
                    # 10円以下の差額の場合は自動修正を提案
                    difference = updates.get("price_difference")
                    if difference is not None and abs(difference) <= 10 and abs(difference) > 0:
                        # 自動修正の確認ダイアログ
                        reply = QMessageBox.question(
                            self,
                            "差額自動修正",
                            f"レシートID: {receipt.get('receipt_id', '不明')}\n"
                            f"差額: ¥{int(difference):,}\n\n"
                            f"10円以下の差額を自動で修正しますか？",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes
                        )
                        
                        if reply == QMessageBox.Yes:
                            # 自動修正を実行
                            # 紐付けSKUの価格を均等に調整
                            merged_skus = [s.strip() for s in updates.get("linked_skus", "").split(',') if s.strip()]
                            if merged_skus and len(merged_skus) > 0:
                                # 差額を均等配分（10円以下の端数は最後のSKUに）
                                adjustment_per_sku = difference // len(merged_skus)
                                remainder = difference % len(merged_skus)
                                
                                # 10円以下の端数は最後のSKUに転嫁
                                small_remainder = 0
                                if abs(remainder) <= 10:
                                    small_remainder = remainder
                                    remainder = 0
                                else:
                                    remainder_per_sku = remainder // len(merged_skus)
                                    small_remainder = remainder % len(merged_skus)
                                    adjustment_per_sku += remainder_per_sku
                                
                                # 各SKUの金額を更新（仕入れ個数 × 仕入れ価格の合計を調整）
                                for idx, sku in enumerate(merged_skus):
                                    # 合計金額に対する調整額
                                    total_adjustment = adjustment_per_sku
                                    if idx == len(merged_skus) - 1:
                                        total_adjustment += small_remainder
                                    
                                    # 仕入DBから該当SKUを検索して価格を更新
                                    for record in purchase_records:
                                        record_sku = record.get('SKU') or record.get('sku', '')
                                        if record_sku and record_sku.strip() == sku:
                                            current_price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                                            try:
                                                current_price = float(current_price) if current_price else 0
                                            except (ValueError, TypeError):
                                                current_price = 0
                                            
                                            # 仕入れ個数を取得
                                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                                            try:
                                                quantity = float(quantity) if quantity else 1
                                            except (ValueError, TypeError):
                                                quantity = 1
                                            
                                            # 現在の合計金額 = 仕入れ個数 × 仕入れ価格
                                            current_total = current_price * quantity
                                            
                                            # 新しい合計金額 = 現在の合計金額 - 調整額
                                            new_total = current_total - total_adjustment
                                            if new_total < 0:
                                                new_total = 0
                                            
                                            # 新しい仕入れ価格 = 新しい合計金額 / 仕入れ個数
                                            if quantity > 0:
                                                new_price = new_total / quantity
                                            else:
                                                new_price = new_total
                                            
                                            # 仕入DBの価格を更新
                                            record['仕入れ価格'] = int(new_price)
                                            
                                            # 見込み利益・損益分岐点・利益率・ROIを再計算
                                            planned_price = record.get('販売予定価格') or record.get('planned_price') or 0
                                            try:
                                                planned_price = float(planned_price) if planned_price else 0
                                            except (ValueError, TypeError):
                                                planned_price = 0
                                            
                                            # 見込み利益 = 販売予定価格 - 仕入れ価格
                                            expected_profit = planned_price - new_price if planned_price > 0 else 0
                                            record['見込み利益'] = expected_profit
                                            
                                            # 損益分岐点の計算
                                            other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                            try:
                                                other_cost = float(other_cost) if other_cost else 0
                                            except (ValueError, TypeError):
                                                other_cost = 0
                                            break_even = new_price + other_cost
                                            record['損益分岐点'] = break_even
                                            
                                            # 利益率 = (見込み利益 / 販売予定価格) * 100
                                            if planned_price > 0:
                                                expected_margin = (expected_profit / planned_price) * 100
                                            else:
                                                expected_margin = 0.0
                                            record['想定利益率'] = round(expected_margin, 2)
                                            
                                            # ROI = (見込み利益 / 仕入れ価格) * 100
                                            if new_price > 0:
                                                expected_roi = (expected_profit / new_price) * 100
                                            else:
                                                expected_roi = 0.0
                                            record['想定ROI'] = round(expected_roi, 2)
                                            break
                                
                                # 差額を0に更新
                                updates["price_difference"] = 0
                    
                    self.receipt_db.update_receipt(receipt.get('id'), updates)
                    updated += 1
                    print(f"[一括マッチング] 更新: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}, updates={updates}")
                else:
                    skipped_no_updates += 1
                    print(f"[一括マッチング] スキップ（更新なし）: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}, 店舗コード={receipt.get('store_code')}, candidate_skus={candidate_skus}")
            except Exception as e:
                import traceback
                print(f"[一括マッチング] エラー: receipt_id={receipt.get('id')}, エラー={e}\n{traceback.format_exc()}")
                continue
        
        # 仕入DBの変更を反映（product_widgetのテーブルを更新）
        if self.product_widget and hasattr(self.product_widget, 'populate_purchase_table'):
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            self.product_widget.populate_purchase_table(purchase_records)
        
        # テーブルを更新（紐付き候補SKUと店舗名を表示）
        self.refresh_receipt_list()
        print(f"[一括マッチング] 完了: 更新={updated}件, 候補なし={skipped_no_candidates}件, 更新なし={skipped_no_updates}件")
        QMessageBox.information(self, "一括マッチング", f"{updated} 件のレシートにマッチング候補を適用しました。\n（候補なし: {skipped_no_candidates}件, 更新なし: {skipped_no_updates}件）")

    def bulk_rename_receipts(self):
        """一括リネーム（簡易版・今後拡張予定）"""
        QMessageBox.information(
            self,
            "一括リネーム",
            "一括リネームは今後のバージョンで、既存の確定処理（レシートID＋画像リネーム）を\n自動で回す形で実装予定です。\n現在は個別の「確定」ボタンでリネームしてください。"
        )

    def verify_receipts_with_purchases(self):
        """レシート一覧と仕入DBの照合チェック"""
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        
        receipts = self.receipt_db.find_by_date_and_store(None)
        if not receipts:
            self.verification_info_text.setText("レシートが登録されていません。")
            return
        
        from datetime import datetime
        from collections import defaultdict
        
        results = []
        total_checked = 0
        total_sku_missing = 0
        total_sku_duplicate = 0
        
        for receipt in receipts:
            receipt_date = receipt.get('purchase_date') or ""
            if not receipt_date:
                continue
            
            # レシートの日付を正規化
            receipt_date_obj = None
            try:
                if "/" in receipt_date:
                    receipt_date_obj = datetime.strptime(receipt_date, "%Y/%m/%d").date()
                elif "-" in receipt_date:
                    receipt_date_obj = datetime.strptime(receipt_date[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            
            if not receipt_date_obj:
                continue
            
            # レシートのSKUを取得
            linked_skus_text = receipt.get('linked_skus', '') or ''
            receipt_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
            
            # 画像ファイル名を取得（識別子として使用）
            file_path = receipt.get('file_path') or ""
            image_file_name = Path(file_path).stem if file_path else ""  # 拡張子なしのファイル名
            
            # レシートに紐付けられている仕入DBレコードを取得
            # 1. 画像ファイル名で紐付けられているSKUを優先
            linked_records = []
            if image_file_name:
                for record in purchase_records:
                    record_receipt_id = record.get('レシートID') or record.get('receipt_id', '')
                    if record_receipt_id == image_file_name:
                        linked_records.append(record)
            
            # 2. レシートに紐付けられているSKUで照合（レシートIDで紐付けられていない場合）
            if not linked_records and receipt_skus:
                for record in purchase_records:
                    sku = record.get('SKU') or record.get('sku', '')
                    if sku and sku.strip() in receipt_skus:
                        # 日付と店舗コードも確認
                        record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                        if not record_date:
                            continue
                        
                        try:
                            record_date_str = str(record_date).strip()
                            if " " in record_date_str:
                                record_date_str = record_date_str.split(" ")[0]
                            if "T" in record_date_str:
                                record_date_str = record_date_str.split("T")[0]
                            
                            record_date_obj = None
                            if "/" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                            elif "-" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                            
                            # 日付が一致する場合のみ追加
                            if receipt_date_obj == record_date_obj:
                                # 店舗コードも確認（あれば）
                                receipt_store_code = receipt.get('store_code') or ""
                                record_store_code = record.get('仕入先') or record.get('店舗コード') or record.get('store_code', '')
                                if receipt_store_code and record_store_code:
                                    # 店舗コードのみを取得（表示ラベルから抽出）
                                    if " " in str(receipt_store_code):
                                        receipt_store_code = str(receipt_store_code).split(" ")[0]
                                    if " " in str(record_store_code):
                                        record_store_code = str(record_store_code).split(" ")[0]
                                    if receipt_store_code != record_store_code:
                                        continue
                                
                                linked_records.append(record)
                        except Exception:
                            continue
            
            # 紐付けられているレコードがない場合はスキップ
            if not linked_records:
                continue
            
            total_checked += 1
            
            # 紐付けられている仕入DBレコードのSKUを取得
            purchase_skus = []
            for record in linked_records:
                sku = record.get('SKU') or record.get('sku', '')
                if sku and sku.strip():
                    purchase_skus.append(sku.strip())
            
            # SKUの漏れと重複をチェック
            receipt_sku_set = set(receipt_skus)
            purchase_sku_set = set(purchase_skus)
            
            missing_skus = purchase_sku_set - receipt_sku_set  # 仕入DBにあるがレシートにない
            duplicate_skus = []
            sku_count = defaultdict(int)
            for sku in receipt_skus:
                sku_count[sku] += 1
            for sku, count in sku_count.items():
                if count > 1:
                    duplicate_skus.append(sku)
            
            # 結果を記録
            receipt_file_path = receipt.get('file_path', '')
            receipt_file_name = Path(receipt_file_path).stem if receipt_file_path else ''
            receipt_file = receipt_file_name or receipt_file_path.split(os.sep)[-1] if receipt_file_path else ''
            
            issues = []
            if missing_skus:
                issues.append(f"SKU漏れ: {', '.join(sorted(missing_skus))}")
                total_sku_missing += len(missing_skus)
            if duplicate_skus:
                issues.append(f"SKU重複: {', '.join(sorted(duplicate_skus))}")
                total_sku_duplicate += len(duplicate_skus)
            
            if issues:
                results.append({
                    'date': receipt_date,
                    'file_name': receipt_file_name,
                    'file': receipt_file,
                    'issues': issues
                })
        
        # 結果を表示
        info_text = f"照合チェック結果\n"
        info_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        info_text += f"チェック対象: {total_checked} 件\n"
        info_text += f"SKU漏れ: {total_sku_missing} 件\n"
        info_text += f"SKU重複: {total_sku_duplicate} 件\n"
        info_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if results:
            info_text += "【問題のあるレシート】\n\n"
            for result in results:
                info_text += f"日付: {result['date']}\n"
                info_text += f"画像ファイル名: {result.get('file_name', result.get('file', ''))}\n"
                info_text += f"ファイル: {result['file']}\n"
                for issue in result['issues']:
                    info_text += f"  ⚠ {issue}\n"
                info_text += "\n"
        else:
            info_text += "問題は見つかりませんでした。\n"
        
        self.verification_info_text.setText(info_text)

    # ===== ダブルクリック挙動 =====
    def on_receipt_table_context_menu(self, position):
        """レシートテーブルの右クリックメニュー"""
        item = self.receipt_table.itemAt(position)
        if not item:
            return
        
        row = item.row()
        id_item = self.receipt_table.item(row, 0)
        if not id_item:
            return
        
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return
        
        menu = QMenu(self)
        
        # もう一度OCR処理
        ocr_action = menu.addAction("もう一度OCR処理")
        ocr_action.triggered.connect(lambda: self.reprocess_ocr_for_receipt(receipt_id, receipt))
        
        menu.exec_(self.receipt_table.viewport().mapToGlobal(position))
    
    def reprocess_ocr_for_receipt(self, receipt_id: int, receipt: Dict[str, Any]):
        """選択されたレシートに対してOCR処理を再実行"""
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 既存のレシートデータを削除（OCR結果を上書きするため）
        try:
            self.receipt_db.delete_receipt(receipt_id)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"既存データの削除に失敗しました: {e}")
            return
        
        # OCR処理を実行
        self.process_image(image_path)
    
    def on_receipt_double_clicked(self, item: QTableWidgetItem):
        """レシート一覧のダブルクリック動作を制御（詳細編集を開く）"""
        # すべての列で詳細編集を開く
        self.load_receipt(item)

    def on_warranty_table_context_menu(self, position):
        """保証書テーブルの右クリックメニュー"""
        item = self.warranty_table.itemAt(position)
        if not item:
            return
        
        row = item.row()
        id_item = self.warranty_table.item(row, 0)
        if not id_item:
            return
        
        menu = QMenu(self)
        
        # コピー機能
        copy_action = menu.addAction("コピー")
        copy_action.triggered.connect(lambda: self.copy_warranty_cell(row, item.column()))
        
        menu.addSeparator()
        
        # 商品の追加メニュー
        add_product_action = menu.addAction("商品の追加")
        add_product_action.triggered.connect(lambda: self.add_warranty_product_row(row))
        
        menu.exec_(self.warranty_table.viewport().mapToGlobal(position))
    
    def add_warranty_product_row(self, source_row: int):
        """選択行の種別〜店舗コードをコピーして新しい行を追加"""
        if not hasattr(self, 'warranty_table'):
            return
        
        # 元の行からデータを取得（列1〜6をコピー）
        # 列インデックス: 0=ID, 1=種別, 2=画像ファイル名, 3=日付, 4=店舗名, 5=電話番号, 6=店舗コード
        source_items = {}
        for col in range(1, 7):  # 列1〜6
            item = self.warranty_table.item(source_row, col)
            if item:
                source_items[col] = item.text()
            else:
                widget = self.warranty_table.cellWidget(source_row, col)
                if widget:
                    # ウィジェットの場合はテキストを取得できないので、対応する列のデータを別途取得
                    pass
        
        # 店舗コード列のデータを取得（UserRoleに保存されている）
        store_code_item = self.warranty_table.item(source_row, 6)
        store_code = ""
        store_label = ""
        if store_code_item:
            store_code = store_code_item.data(Qt.UserRole) or ""
            store_label = store_code_item.text() or ""
        
        # ID列を取得（receipt_idを取得するため）
        id_item = self.warranty_table.item(source_row, 0)
        receipt_id = None
        if id_item:
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                pass
        
        # receiptデータを取得（店舗名や電話番号などの詳細情報を取得するため）
        receipt = None
        if receipt_id:
            receipt = self.receipt_db.get_receipt(receipt_id)
        
        # 新しい行を追加
        self.warranty_table.blockSignals(True)
        new_row = self.warranty_table.rowCount()
        self.warranty_table.insertRow(new_row)
        
        # ID列:
        # 「商品の追加」は“同じ保証書画像に紐づく別商品の行”を作る用途なので、
        # ここでは元のreceipt_idをコピーしない（コピーするとDB保存がスキップされ、再起動で消える）。
        # 空IDにしておき、最後にsave_warranty_row_to_db()で新しいreceiptレコードを作成してIDを採番する。
        self.warranty_table.setItem(new_row, 0, QTableWidgetItem(""))
        
        # 種別（列1）
        doc_type_item = self.warranty_table.item(source_row, 1)
        if doc_type_item:
            self.warranty_table.setItem(new_row, 1, QTableWidgetItem(doc_type_item.text()))
        
        # 画像ファイル名（列2）
        image_item = self.warranty_table.item(source_row, 2)
        if image_item:
            self.warranty_table.setItem(new_row, 2, QTableWidgetItem(image_item.text()))
        
        # 日付（列3）
        date_item = self.warranty_table.item(source_row, 3)
        if date_item:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(date_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(receipt.get('purchase_date') or ""))
        
        # 店舗名（列4）
        store_name_item = self.warranty_table.item(source_row, 4)
        if store_name_item:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(store_name_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(receipt.get('store_name_raw') or ""))
        
        # 電話番号（列5）
        phone_item = self.warranty_table.item(source_row, 5)
        if phone_item:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(phone_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(receipt.get('phone_number') or ""))
        
        # 店舗コード（列6）
        if store_code or store_label:
            store_item = QTableWidgetItem(store_label if store_label else store_code)
            store_item.setData(Qt.UserRole, store_code)
            self.warranty_table.setItem(new_row, 6, store_item)
        elif receipt:
            store_code_from_receipt = receipt.get('store_code') or ""
            store_label_from_receipt = self._format_store_code_label(
                store_code_from_receipt, 
                receipt.get('store_name_raw') or ""
            )
            store_item = QTableWidgetItem(store_label_from_receipt)
            store_item.setData(Qt.UserRole, store_code_from_receipt)
            self.warranty_table.setItem(new_row, 6, store_item)
        
        # SKU・商品名（列7, 8）: 空欄でプルダウンを設定
        if receipt:
            self._populate_warranty_product_cell(new_row, receipt, "", "")
        else:
            # receiptがない場合でも、テーブルのデータから最低限のreceiptオブジェクトを作成
            minimal_receipt = {
                'purchase_date': date_item.text() if date_item else "",
                'store_code': store_code,
                'store_name_raw': store_name_item.text() if store_name_item else "",
            }
            self._populate_warranty_product_cell(new_row, minimal_receipt, "", "")
        
        # 保証期間(日)（列9）: 空欄
        self.warranty_table.setItem(new_row, 9, QTableWidgetItem(""))
        
        # 保証最終日（列10）: 日付をデフォルトに設定
        from PySide6.QtWidgets import QDateEdit
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        
        # 日付列から日付を取得してデフォルトに設定
        date_item = self.warranty_table.item(new_row, 3)
        if date_item:
            purchase_date_str = date_item.text().strip().replace("/", "-").split(" ")[0]
            if purchase_date_str:
                try:
                    from datetime import datetime
                    qdate = QDate.fromString(purchase_date_str, "yyyy-MM-dd")
                    if qdate.isValid():
                        date_edit.setDate(qdate)
                except Exception:
                    pass
        
        self.warranty_table.setCellWidget(new_row, 10, date_edit)
        
        # 日付変更時の処理を接続
        date_edit.dateChanged.connect(lambda qd, r=new_row: self.on_warranty_date_changed(r, qd))
        
        self.warranty_table.blockSignals(False)
        
        # 新しい行を選択状態にする
        self.warranty_table.selectRow(new_row)
        
        # データベースに新しいレシートレコードを作成（永続化のため）
        self.save_warranty_row_to_db(new_row)
    
    def on_warranty_table_cell_clicked(self, row: int, col: int):
        """保証書一覧テーブルのセルクリック処理（画像ファイル名列をクリックで画像を開く）"""
        # 画像ファイル名列（col=2）のみ処理
        if col != 2:
            return
        
        id_item = self.warranty_table.item(row, 0)
        if not id_item:
            return
        
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return
        
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが登録されていません。")
            return
        
        # OSのデフォルトアプリで画像を開く
        from pathlib import Path
        image_file = Path(image_path)
        if image_file.exists() and image_file.is_file():
            file_url = QUrl.fromLocalFile(str(image_file.absolute()))
            if not QDesktopServices.openUrl(file_url):
                QMessageBox.warning(self, "警告", f"画像ファイルを開けませんでした:\n{image_path}")
        else:
            QMessageBox.warning(
                self, "警告",
                f"画像ファイルが見つかりません:\n\n"
                f"ファイルパス: {image_path}\n\n"
                f"ファイルが削除されているか、\n"
                f"パスが変更されている可能性があります。"
            )
    
    def copy_warranty_cell(self, row: int, col: int):
        """保証書テーブルのセルをクリップボードにコピー"""
        if not hasattr(self, 'warranty_table'):
            return
        
        # セルのテキストを取得
        item = self.warranty_table.item(row, col)
        if item:
            text = item.text()
        else:
            # ウィジェットの場合はテキストを取得
            widget = self.warranty_table.cellWidget(row, col)
            if widget:
                if hasattr(widget, 'text'):
                    text = widget.text()
                elif hasattr(widget, 'currentText'):
                    text = widget.currentText()
                elif hasattr(widget, 'date'):
                    qdate = widget.date()
                    if qdate.isValid():
                        text = qdate.toString("yyyy-MM-dd")
                    else:
                        text = ""
                else:
                    text = ""
            else:
                text = ""
        
        # クリップボードにコピー
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
    
    def save_warranty_row_to_db(self, row: int):
        """保証書テーブルの行をデータベースに保存"""
        if not hasattr(self, 'warranty_table'):
            return
        
        try:
            # テーブルからデータを取得
            id_item = self.warranty_table.item(row, 0)
            if not id_item:
                return
            
            # 既存のreceipt_idがある場合は、基本的に新規作成しない（既存行の再保存を避ける）
            receipt_id = None
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                pass
            
            # receipt_idが既に入っている行はここでは新規作成しない
            # （SKU/商品名/保証期間などの編集は別ロジックでupdate_receiptされる）
            if receipt_id:
                return
            
            # テーブルからデータを取得
            doc_type_item = self.warranty_table.item(row, 1)
            image_item = self.warranty_table.item(row, 2)
            date_item = self.warranty_table.item(row, 3)
            store_name_item = self.warranty_table.item(row, 4)
            phone_item = self.warranty_table.item(row, 5)
            store_code_item = self.warranty_table.item(row, 6)
            
            # 店舗コードを取得
            store_code = ""
            if store_code_item:
                store_code = store_code_item.data(Qt.UserRole) or ""
                if not store_code:
                    store_code = store_code_item.text().split(" ")[0] if store_code_item.text() else ""
            
            # 画像ファイル名を取得
            image_file_name = image_item.text() if image_item else ""

            # file_path/original_file_path は可能なら既存レコードから実パスを引き継ぐ（ファイル名だけだと起動後に画像が開けない）
            resolved_file_path = image_file_name
            resolved_original_file_path = image_file_name
            try:
                existing_by_name = self.receipt_db.find_by_file_name(image_file_name)
                if existing_by_name:
                    resolved_file_path = existing_by_name.get("file_path") or resolved_file_path
                    resolved_original_file_path = existing_by_name.get("original_file_path") or resolved_original_file_path
            except Exception:
                pass
            
            # 新しいレシートレコードを作成
            receipt_data = {
                "file_path": resolved_file_path,
                "original_file_path": resolved_original_file_path,
                "purchase_date": date_item.text() if date_item else "",
                "store_name_raw": store_name_item.text() if store_name_item else "",
                "phone_number": phone_item.text() if phone_item else "",
                "store_code": store_code,
                "ocr_text": "保証書",  # 保証書として識別
                "total_amount": 0,
                "items_count": 0,
            }
            
            # データベースに保存
            new_receipt_id = self.receipt_db.insert_receipt(receipt_data)
            
            # テーブルのID列を更新
            if new_receipt_id:
                self.warranty_table.setItem(row, 0, QTableWidgetItem(str(new_receipt_id)))
            
        except Exception as e:
            import traceback
            print(f"保証書行の保存エラー: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "警告", f"保証書行の保存に失敗しました:\n{e}")

    def on_warranty_item_double_clicked(self, item: QTableWidgetItem):
        """保証書一覧のダブルクリック動作（画像ファイル名は拡大表示）"""
        row = item.row()
        col = item.column()
        # 画像ファイル名列のみ対象
        if col != 2:
            return
        id_item = self.warranty_table.item(row, 0)
        if not id_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが登録されていません。")
            return
        self._show_image_popup(image_path)

    # ===== 保証書テーブルの編集 =====
    def on_warranty_cell_changed(self, row: int, column: int):
        """保証期間/店舗コード編集時の処理（保証最終日は on_warranty_date_changed で処理）"""
        # 列インデックス: 0=ID,1=種別,2=画像,3=レシートID,4=日付,5=店舗名,6=電話,7=店舗コード,8=SKU,9=商品名,10=保証期間,11=保証最終日
        # 店舗コード変更時は商品候補を更新
        if column == 7:
            id_item = self.warranty_table.item(row, 0)
            if not id_item:
                return
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                return
            receipt = self.receipt_db.get_receipt(receipt_id)
            if not receipt:
                return
            # テーブル上の店舗コードを優先
            store_code_item = self.warranty_table.item(row, 6)
            if store_code_item:
                new_code = self._store_code_from_item(store_code_item)
                receipt = dict(receipt)
                receipt["store_code"] = new_code
                # 表示をコード+名称に整える
                display_label = self._format_store_code_label(new_code, receipt.get("store_name_raw") or "")
                self.warranty_table.blockSignals(True)
                store_code_item.setText(display_label)
                store_code_item.setData(Qt.UserRole, new_code)
                self.warranty_table.blockSignals(False)
            sku_item = self.warranty_table.item(row, 8)
            name_item = self.warranty_table.item(row, 9)
            current_sku = sku_item.text() if sku_item else ""
            current_name = name_item.text() if name_item else ""
            self._populate_warranty_product_cell(row, receipt, current_sku, current_name)
            return

        # 保証期間(日)列でなければ何もしない（列インデックス9）
        if column != 9:
            return
        if not hasattr(self, "warranty_table"):
            return
        id_item = self.warranty_table.item(row, 0)
        date_item = self.warranty_table.item(row, 3)  # 日付列（列インデックス3）
        days_item = self.warranty_table.item(row, 9)  # 保証期間(日)列（列インデックス9）
        if not id_item or not date_item or not days_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        purchase_date = date_item.text().strip()
        try:
            days = int(days_item.text().strip())
        except (ValueError, TypeError):
            return

        # 日付計算
        from datetime import datetime, timedelta

        # 日付文字列を正規化（yyyy-MM-dd 形式に揃える）
        normalized = purchase_date.replace("/", "-").split(" ")[0]
        try:
            base_date = datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError:
            # 日付形式不正の場合は何もしない
            return
        final_date = base_date + timedelta(days=days)
        final_str = final_date.strftime("%Y-%m-%d")

        # テーブル更新（再帰呼び出し防止のためシグナル一時停止）
        from PySide6.QtWidgets import QDateEdit

        self.warranty_table.blockSignals(True)
        widget = self.warranty_table.cellWidget(row, 10)  # 保証最終日列（列インデックス10）
        if isinstance(widget, QDateEdit):
            widget.setDate(QDate.fromString(final_str, "yyyy-MM-dd"))
        else:
            self.warranty_table.setItem(row, 10, QTableWidgetItem(final_str))
        self.warranty_table.blockSignals(False)

        # DB更新
        updates = {"warranty_days": days, "warranty_until": final_str}
        self.receipt_db.update_receipt(receipt_id, updates)

    def on_warranty_date_changed(self, row: int, qdate: QDate):
        """保証最終日を変更したときに保証期間(日)を逆算してDBに保存"""
        if not hasattr(self, "warranty_table"):
            return
        id_item = self.warranty_table.item(row, 0)
        date_item = self.warranty_table.item(row, 3)  # 日付列（列インデックス3）
        if not id_item or not date_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return

        purchase_date = date_item.text().strip()
        if not purchase_date:
            return

        from datetime import datetime

        # 日付文字列を正規化（yyyy-MM-dd 形式に揃える）
        normalized = purchase_date.replace("/", "-").split(" ")[0]
        try:
            base_date = datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError:
            return

        final_str = qdate.toString("yyyy-MM-dd")
        try:
            final_date = datetime.strptime(final_str, "%Y-%m-%d")
        except ValueError:
            return

        days = (final_date - base_date).days
        if days < 0:
            # マイナスはおかしいので何もしない
            return

        # テーブル更新（cellChanged を発火させないようにシグナルをブロック）
        self.warranty_table.blockSignals(True)
        self.warranty_table.setItem(row, 9, QTableWidgetItem(str(days)))  # 保証期間(日)列（列インデックス9）
        self.warranty_table.blockSignals(False)

        # DB更新
        updates = {"warranty_days": days, "warranty_until": final_str}
        self.receipt_db.update_receipt(receipt_id, updates)

    def _populate_warranty_product_cell(self, row: int, receipt: Dict[str, Any], sku: str, product_name: str):
        """
        保証書一覧の SKU / 商品名セルにプルダウンを設定し、選択した商品からSKUを自動入力
        """
        # 既存テキストをいったん設定（編集途中の値も保持）
        self.warranty_table.setItem(row, 7, QTableWidgetItem(sku))
        self.warranty_table.setItem(row, 8, QTableWidgetItem(product_name))

        # 候補取得：仕入DBの全レコードから、日付＋店舗コードが一致する商品を抽出
        candidates = []
        purchase_date_norm = self._normalize_purchase_date_text(receipt.get("purchase_date"))
        store_code_item = self.warranty_table.item(row, 6)
        store_code = (self._store_code_from_item(store_code_item) or receipt.get("store_code") or "").strip()
        if self.product_widget and hasattr(self.product_widget, "purchase_all_records") and purchase_date_norm and store_code:
            for rec in self.product_widget.purchase_all_records:
                rec_date = (
                    rec.get("仕入れ日")
                    or rec.get("purchase_date")
                    or rec.get("purchaseDate")
                    or rec.get("date")
                )
                rec_date_norm = self._normalize_purchase_date_text(rec_date)
                if not rec_date_norm or rec_date_norm != purchase_date_norm:
                    continue
                rec_store = (
                    rec.get("仕入先コード")
                    or rec.get("仕入先")
                    or rec.get("store_code")
                    or rec.get("店舗コード")
                    or rec.get("supplier_code")
                )
                rec_store = str(rec_store).strip() if rec_store else ""
                if rec_store != store_code:
                    continue
                cand_sku = rec.get("SKU") or rec.get("sku") or ""
                cand_name = rec.get("商品名") or rec.get("title") or ""
                if cand_name:
                    candidates.append((cand_sku, cand_name))

        # プルダウン(商品名)を作成
        combo = QComboBox()
        combo.addItem("（選択してください）", userData=None)
        combo.setMinimumWidth(180)
        # 重複除去
        seen = set()
        for cand_sku, cand_name in candidates:
            key = (cand_sku, cand_name)
            if key in seen:
                continue
            seen.add(key)
            combo.addItem(cand_name, userData={"sku": cand_sku, "name": cand_name})

        # 既存値があれば選択状態にする／候補にない場合は末尾に追加
        selected_index = 0
        if product_name:
            for idx in range(1, combo.count()):
                data = combo.itemData(idx)
                if data and data.get("name") == product_name:
                    selected_index = idx
                    break
            else:
                combo.addItem(product_name, userData={"sku": sku, "name": product_name})
                selected_index = combo.count() - 1
        combo.setCurrentIndex(selected_index)

        # 選択変更時の処理
        def on_combo_changed(index: int, table_row=row):
            data = combo.itemData(index)
            if not data:
                return
            new_sku = data.get("sku") or ""
            new_name = data.get("name") or ""
            id_item = self.warranty_table.item(table_row, 0)
            if not id_item:
                return
            try:
                rec_id = int(id_item.text())
            except ValueError:
                return
            # テーブル更新
            self.warranty_table.blockSignals(True)
            sku_item = self.warranty_table.item(table_row, 7)
            if sku_item:
                sku_item.setText(new_sku)
            else:
                self.warranty_table.setItem(table_row, 7, QTableWidgetItem(new_sku))
            name_item = self.warranty_table.item(table_row, 8)
            if name_item:
                name_item.setText(new_name)
            else:
                self.warranty_table.setItem(table_row, 8, QTableWidgetItem(new_name))
            self.warranty_table.blockSignals(False)
            # DB更新
            self.receipt_db.update_receipt(rec_id, {"sku": new_sku, "product_name": new_name})

        combo.currentIndexChanged.connect(on_combo_changed)
        self.warranty_table.setCellWidget(row, 8, combo)

    def load_receipt(self, item: QTableWidgetItem):
        """レシートを読み込み（レシート情報編集ダイアログを表示）"""
        row = item.row()
        
        # ID列からreceipt_idを取得
        id_item = self.receipt_table.item(row, 0)
        if not id_item:
            return
        
        try:
            receipt_id = int(id_item.text())
        except (ValueError, TypeError):
            return
        
        # レシートデータを取得
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            QMessageBox.warning(self, "警告", "レシートデータが見つかりません。")
            return
        
        # 画像ファイルパスを取得
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # レシート情報編集ダイアログを表示
        self._show_image_popup(image_path, receipt_id)
    
    def view_receipt_image(self):
        """レシート画像を別画面で表示"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 画像パスを取得
        image_path = None
        if self.current_receipt_data:
            image_path = self.current_receipt_data.get('file_path') or self.current_receipt_data.get('original_file_path')
        if not image_path and self.current_receipt_id:
            receipt = self.receipt_db.get_receipt(self.current_receipt_id)
            if receipt:
                image_path = receipt.get('file_path') or receipt.get('original_file_path')

        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルが見つかりません。")
            return

        self._show_image_popup(image_path, self.current_receipt_id)

    def _show_image_popup(self, image_path: str, receipt_id: Optional[int] = None):
        """指定パスの画像をポップアップ表示（回転機能付き・編集パネル付き）"""
        from pathlib import Path
        image_file = Path(image_path)
        if not image_file.exists():
            QMessageBox.warning(self, "警告", f"画像ファイルが存在しません:\n{image_path}")
            return

        # レシートIDが指定されていない場合は画像パスから検索
        if receipt_id is None:
            receipts = self.receipt_db.find_by_date_and_store(None)
            for receipt in receipts:
                if receipt.get('file_path') == str(image_path) or receipt.get('original_file_path') == str(image_path):
                    receipt_id = receipt.get('id')
                    break
        
        # レシートデータを取得
        receipt_data = None
        if receipt_id:
            receipt_data = self.receipt_db.get_receipt(receipt_id)

        # 元の画像を読み込み（回転状態を保持するため）
        original_pixmap = QPixmap(str(image_file))
        if original_pixmap.isNull():
            QMessageBox.warning(self, "警告", "画像を読み込めませんでした。")
            return
        
        # 現在の回転角度を保持（0度から開始）
        current_rotation = [0]  # リストで保持して参照渡しにする
        
        dialog = QDialog(self)
        dialog.setWindowTitle(str(image_file.name))
        dialog.setMinimumSize(1200, 800)

        screen = dialog.screen().availableGeometry()
        max_dialog_width = int(screen.width() * 0.95)
        max_dialog_height = int(screen.height() * 0.95)

        def update_image_display():
            """画像を回転させて表示を更新"""
            # 回転を適用
            transform = QTransform().rotate(current_rotation[0])
            rotated_pixmap = original_pixmap.transformed(transform, Qt.SmoothTransformation)
            
            # サイズ調整
            rotated_width = rotated_pixmap.width()
            rotated_height = rotated_pixmap.height()
            
            if rotated_width > max_dialog_width or rotated_height > max_dialog_height:
                scaled_pixmap = rotated_pixmap.scaled(
                    max_dialog_width, max_dialog_height,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                scaled_pixmap = rotated_pixmap
            
            # ラベルに設定
            image_label.setPixmap(scaled_pixmap)
            
            # ダイアログサイズを調整
            dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
            dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)
            dialog.resize(dialog_width, dialog_height)
            
            # 情報ラベルを更新
            info_label.setText(f"画像サイズ: {rotated_width} x {rotated_height} px (回転: {current_rotation[0]}°)")

        def rotate_image(angle: int):
            """画像を回転"""
            current_rotation[0] = (current_rotation[0] + angle) % 360
            update_image_display()

        def save_rotation():
            """回転を実ファイルに保存"""
            if current_rotation[0] == 0:
                QMessageBox.information(self, "情報", "回転が適用されていません。")
                return
            
            # 回転を適用した画像を作成
            transform = QTransform().rotate(current_rotation[0])
            rotated_pixmap = original_pixmap.transformed(transform, Qt.SmoothTransformation)
            
            # ファイルに保存
            if not rotated_pixmap.save(str(image_file)):
                QMessageBox.warning(self, "警告", "画像の保存に失敗しました。")
                return
            
            # 元の画像を更新（次回表示時に回転済み画像が表示される）
            original_pixmap.load(str(image_file))
            current_rotation[0] = 0  # リセット
            update_image_display()
            
            # レシート一覧を更新（サムネイルが更新される可能性があるため）
            self.refresh_receipt_list()
            
            QMessageBox.information(self, "完了", "画像の回転を保存しました。")

        # 初期表示用のサイズ計算
        original_width = original_pixmap.width()
        original_height = original_pixmap.height()
        
        if original_width > max_dialog_width or original_height > max_dialog_height:
            scaled_pixmap = original_pixmap.scaled(
                max_dialog_width, max_dialog_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            scaled_pixmap = original_pixmap

        dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
        dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)

        # メインレイアウト（横分割）
        main_layout = QHBoxLayout(dialog)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 左側：画像表示エリア
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # 回転ボタン
        rotate_layout = QHBoxLayout()
        rotate_left_btn = QPushButton("⟲ 左回転")
        rotate_left_btn.clicked.connect(lambda: rotate_image(-90))
        rotate_layout.addWidget(rotate_left_btn)
        
        rotate_right_btn = QPushButton("右回転 ⟳")
        rotate_right_btn.clicked.connect(lambda: rotate_image(90))
        rotate_layout.addWidget(rotate_right_btn)
        
        save_rotation_btn = QPushButton("回転を保存")
        save_rotation_btn.clicked.connect(save_rotation)
        save_rotation_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        rotate_layout.addWidget(save_rotation_btn)
        rotate_layout.addStretch()
        left_layout.addLayout(rotate_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignCenter)

        image_label = QLabel()
        image_label.setPixmap(scaled_pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        scroll_area.setWidget(image_label)
        left_layout.addWidget(scroll_area)

        info_label = QLabel(f"画像サイズ: {original_width} x {original_height} px")
        info_label.setStyleSheet("color: #888888; font-size: 10px;")
        left_layout.addWidget(info_label)

        main_layout.addWidget(left_widget, 2)  # 画像エリアは2倍の幅

        # 右側：編集パネル
        if receipt_data:
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(10)

            # 編集フォーム
            form_group = QGroupBox("レシート情報編集")
            form_layout = QFormLayout(form_group)
            
            # 種別
            type_combo = QComboBox()
            type_combo.addItems(["レシート", "保証書", "その他"])
            if receipt_data.get('account_title'):
                # account_titleから種別を推測（簡易版）
                account_title = receipt_data.get('account_title', '')
                if '保証書' in account_title:
                    type_combo.setCurrentText("保証書")
                elif 'レシート' in account_title:
                    type_combo.setCurrentText("レシート")
            form_layout.addRow("種別:", type_combo)
            
            # 科目
            account_title_combo = QComboBox()
            account_title_combo.setEditable(True)
            # 勘定科目を読み込み
            try:
                account_title_db = AccountTitleDatabase()
                titles = account_title_db.get_all_titles()
                for title in titles:
                    account_title_combo.addItem(title.get('name', ''))
                current_title = receipt_data.get('account_title', '')
                if current_title:
                    idx = account_title_combo.findText(current_title)
                    if idx >= 0:
                        account_title_combo.setCurrentIndex(idx)
                    else:
                        account_title_combo.setCurrentText(current_title)
            except Exception:
                pass
            form_layout.addRow("科目:", account_title_combo)
            
            # レシートID
            
            # 日付
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            purchase_date = receipt_data.get('purchase_date')
            if purchase_date:
                try:
                    date = QDate.fromString(purchase_date, "yyyy/MM/dd")
                    if not date.isValid():
                        date = QDate.fromString(purchase_date.replace("/", "-"), "yyyy-MM-dd")
                    if date.isValid():
                        date_edit.setDate(date)
                except Exception:
                    date_edit.setDate(QDate.currentDate())
            else:
                date_edit.setDate(QDate.currentDate())
            form_layout.addRow("日付:", date_edit)
            
            # 時刻
            time_edit = QLineEdit()
            time_edit.setText(receipt_data.get('purchase_time') or '')
            time_edit.setPlaceholderText("HH:MM")
            form_layout.addRow("時刻:", time_edit)
            
            # 店舗名（プルダウンで店舗コード＋店舗名を選択可能）
            store_name_combo = QComboBox()
            store_name_combo.setEditable(False)
            # 店舗マスタから全店舗を読み込み
            try:
                stores = self.store_db.list_stores()
                for store in stores:
                    # 店舗コードを優先し、空の場合は仕入れ先コードをフォールバックとして使用
                    code = (store.get('store_code') or '').strip() or (store.get('supplier_code') or '').strip()
                    name = (store.get('store_name') or '').strip()
                    if code and name:
                        label = f"{code} {name}"
                        store_name_combo.addItem(label, code)
                    elif code:
                        store_name_combo.addItem(code, code)
                    elif name:
                        store_name_combo.addItem(name, '')
                
                # 現在の店舗コードに一致する項目を選択
                current_store_code = receipt_data.get('store_code', '') or ''
                if current_store_code:
                    idx = store_name_combo.findData(current_store_code)
                    if idx >= 0:
                        store_name_combo.setCurrentIndex(idx)
            except Exception:
                pass
            form_layout.addRow("店舗名:", store_name_combo)
            
            # 電話番号
            phone_edit = QLineEdit()
            phone_edit.setText(receipt_data.get('phone_number') or '')
            form_layout.addRow("電話番号:", phone_edit)
            
            # 合計
            total_edit = QLineEdit()
            total_edit.setText(str(receipt_data.get('total_amount') or ''))
            form_layout.addRow("合計:", total_edit)
            
            # 値引
            discount_edit = QLineEdit()
            discount_edit.setText(str(receipt_data.get('discount_amount') or ''))
            form_layout.addRow("値引:", discount_edit)
            
            # 点数
            # 店舗コード（店舗名コンボボックスと連動）
            # 店舗名コンボボックスで選択した店舗コードを表示（読み取り専用）
            store_code_display = QLineEdit()
            store_code_display.setReadOnly(True)
            current_store_code = receipt_data.get('store_code', '') or ''
            store_code_display.setText(current_store_code)
            form_layout.addRow("店舗コード:", store_code_display)
            
            # 店舗名コンボボックスの変更時に店舗コード表示を更新
            def update_store_code_display():
                selected_code = store_name_combo.currentData()
                store_code_display.setText(selected_code if selected_code else '')
            store_name_combo.currentIndexChanged.connect(update_store_code_display)
            
            right_layout.addWidget(form_group)
            
            # SKU紐付けセクション
            sku_group = QGroupBox("紐付けSKU")
            sku_layout = QVBoxLayout(sku_group)
            
            # 現在の紐付けSKUリスト
            linked_skus_list = QListWidget()
            linked_skus_list.setMaximumHeight(150)
            linked_skus_text = receipt_data.get('linked_skus', '') or ''
            
            # SKUと金額・時刻のマッピングを保持（仕入DBから取得：仕入れ個数 × 仕入れ価格）
            sku_info_map = {}  # {sku: {'price': total_amount, 'time': time_str}}
            if self.product_widget:
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                for record in purchase_records:
                    sku = record.get('SKU') or record.get('sku', '')
                    if sku and sku.strip():
                        sku = sku.strip()
                        # 仕入れ価格を取得（複数のカラム名に対応）
                        price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                        try:
                            price = float(price) if price else 0
                        except (ValueError, TypeError):
                            price = 0
                        # 仕入れ個数を取得（複数のカラム名に対応）
                        quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                        try:
                            quantity = float(quantity) if quantity else 1
                        except (ValueError, TypeError):
                            quantity = 1
                        # 金額 = 仕入れ個数 × 仕入れ価格
                        total_amount = price * quantity
                        
                        # 時刻情報を取得
                        time_str = "時刻不明"
                        
                        # 1. 「仕入れ日」カラムから取得（優先）- 「YYYY/MM/DD HH:MM」形式で日付と時刻の両方が含まれる
                        purchase_date_str = record.get('仕入れ日') or record.get('purchase_date') or ""
                        if purchase_date_str:
                            try:
                                from datetime import datetime
                                purchase_date_str_clean = str(purchase_date_str).strip()
                                # 「YYYY/MM/DD HH:MM」形式を想定
                                if ' ' in purchase_date_str_clean:
                                    try:
                                        # 「YYYY/MM/DD HH:MM」形式
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            # 「YYYY-MM-DD HH:MM」形式
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                # 「YYYY/MM/DD HH:MM:SS」形式
                                                dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                try:
                                                    # 「YYYY-MM-DD HH:MM:SS」形式
                                                    dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                                except:
                                                    # パースできない場合はそのまま使用
                                                    time_str = purchase_date_str_clean
                            except Exception as e:
                                print(f"時刻情報取得エラー (仕入れ日): {e}, 値: {purchase_date_str}")
                        
                        # 2. 「日付/時間」または「日付/時刻」カラムから取得
                        if time_str == "時刻不明":
                            datetime_str = record.get('日付/時間') or record.get('日付/時刻') or ""
                            if datetime_str:
                                try:
                                    from datetime import datetime
                                    datetime_str_clean = str(datetime_str).strip()
                                    if ' ' in datetime_str_clean:
                                        try:
                                            dt = datetime.strptime(datetime_str_clean, "%Y/%m/%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                dt = datetime.strptime(datetime_str_clean, "%Y-%m-%d %H:%M")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                time_str = datetime_str_clean
                                    elif 'T' in datetime_str_clean:
                                        try:
                                            if datetime_str_clean.endswith('Z'):
                                                datetime_str_clean = datetime_str_clean[:-1]
                                            if len(datetime_str_clean) >= 19:
                                                dt = datetime.strptime(datetime_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            pass
                                except Exception:
                                    pass
                        
                        # 3. 「仕入れ時刻」または「purchase_time」カラムから取得
                        if time_str == "時刻不明":
                            record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                            if record_time:
                                try:
                                    from datetime import datetime
                                    record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                                    if record_date:
                                        date_str = str(record_date).strip()
                                        if " " in date_str:
                                            date_str = date_str.split(" ")[0]
                                        if "T" in date_str:
                                            date_str = date_str.split("T")[0]
                                        date_str = date_str.replace("/", "-")
                                        datetime_str = f"{date_str} {record_time}"
                                        try:
                                            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = f"{date_str} {record_time}"
                                except Exception:
                                    pass
                        
                        # 4. created_atから時刻を取得（最後のフォールバック）
                        if time_str == "時刻不明":
                            record_created_at = record.get('created_at') or record.get('登録日時') or ""
                            if record_created_at:
                                try:
                                    from datetime import datetime
                                    if isinstance(record_created_at, str):
                                        record_created_at_clean = str(record_created_at).strip()
                                        if 'T' in record_created_at_clean:
                                            if record_created_at_clean.endswith('Z'):
                                                record_created_at_clean = record_created_at_clean[:-1]
                                            if len(record_created_at_clean) >= 19:
                                                dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        elif ' ' in record_created_at_clean:
                                            if len(record_created_at_clean) >= 19:
                                                dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except Exception:
                                    pass
                        
                        sku_info_map[sku] = {
                            'price': total_amount,
                            'time': time_str
                        }
            
            # 紐付けSKUリストに価格情報と時刻情報も表示
            total_price = 0
            if linked_skus_text:
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()]
                for sku in linked_skus:
                    sku_info = sku_info_map.get(sku, {})
                    price = sku_info.get('price', 0)
                    time_str = sku_info.get('time', '時刻不明')
                    
                    if price > 0:
                        display_text = f"{sku} - ¥{int(price):,} - ({time_str})"
                        total_price += price
                    else:
                        display_text = f"{sku} - 価格不明 - ({time_str})"
                    linked_skus_list.addItem(display_text)
                    # UserRoleにSKUを保存（削除時に使用）
                    item = linked_skus_list.item(linked_skus_list.count() - 1)
                    if item:
                        item.setData(Qt.UserRole, sku)
            
            sku_layout.addWidget(QLabel("現在の紐付けSKU:"))
            # ダブルクリックで価格編集可能にする
            linked_skus_list.itemDoubleClicked.connect(lambda item: self._edit_sku_price(item, linked_skus_list, total_edit, discount_edit))
            sku_layout.addWidget(linked_skus_list)
            
            # 合計金額と差額を表示（後で更新できるように変数に保存）
            receipt_total = int(receipt_data.get('total_amount') or 0)
            difference = total_price - receipt_total
            difference_text = f"差額: ¥{int(difference):,}" if difference != 0 else "差額: ¥0"
            difference_color = "#FF6B6B" if difference > 0 else "#4CAF50" if difference < 0 else "#666666"
            
            total_label = QLabel(f"合計: ¥{int(total_price):,} ({difference_text})")
            total_label.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
            total_label.setObjectName("sku_total_label")  # 後で検索できるようにオブジェクト名を設定
            sku_layout.addWidget(total_label)
            
            # 合計が変更されたときに差額を更新（linked_skus_listが定義された後に接続）
            def update_total_on_change():
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                    self._update_sku_total(linked_skus_list, receipt_total)
                except ValueError:
                    self._update_sku_total(linked_skus_list, 0)
            total_edit.textChanged.connect(update_total_on_change)
            
            # SKU削除ボタン
            remove_sku_btn = QPushButton("選択SKUを削除")
            remove_sku_btn.clicked.connect(lambda: self._remove_sku_from_list(linked_skus_list, total_edit))
            sku_layout.addWidget(remove_sku_btn)
            
            # 仕入DBから候補SKUを取得
            candidate_skus_list = QListWidget()
            candidate_skus_list.setMaximumHeight(150)
            candidate_skus_list.setSelectionMode(QListWidget.MultiSelection)
            sku_layout.addWidget(QLabel("仕入DBの候補SKU:"))
            sku_layout.addWidget(candidate_skus_list)
            
            # 候補SKUを読み込み
            def load_candidate_skus():
                candidate_skus_list.clear()
                if not self.product_widget:
                    return
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                if not purchase_records:
                    return
                
                file_path = receipt_data.get('file_path', '') if receipt_data else ''
                image_file_name = Path(file_path).stem if file_path else ''  # 拡張子なしのファイル名
                purchase_date = receipt_data.get('purchase_date', '') if receipt_data else ''
                store_code = receipt_data.get('store_code', '') if receipt_data else ''
                
                existing_skus = {linked_skus_list.item(i).text() for i in range(linked_skus_list.count())}
                
                # 1. 画像ファイル名で紐付けられたSKU（優先）
                if image_file_name:
                    for record in purchase_records:
                        record_receipt_id = record.get('レシートID') or record.get('receipt_id', '')
                        if record_receipt_id == image_file_name:
                            sku = record.get('SKU') or record.get('sku', '')
                            if sku and sku.strip() and sku not in existing_skus:
                                candidate_skus_list.addItem(sku.strip())
                                existing_skus.add(sku.strip())
                
                # 2. 日付と店舗コードで紐付けられたSKU（画像ファイル名がない場合のフォールバック）
                # レシート時間より前の時間に登録されたSKUを取得
                if purchase_date and store_code and (not image_file_name or candidate_skus_list.count() == 0):
                    # 店舗コードのみを取得（表示ラベルから抽出）
                    store_code_clean = str(store_code).strip()
                    if " " in store_code_clean:
                        store_code_clean = store_code_clean.split(" ")[0]
                    
                    # レシートの日時をdatetimeオブジェクトに変換（比較用）
                    purchase_time = receipt_data.get('purchase_time', '') if receipt_data else ''
                    receipt_datetime = None
                    if purchase_time:
                        try:
                            from datetime import datetime
                            # 日付と時刻を結合してdatetimeオブジェクトを作成
                            date_str = purchase_date.replace("/", "-")
                            datetime_str = f"{date_str} {purchase_time}"
                            receipt_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                        except Exception:
                            pass
                    
                    # レシートの日付を正規化（yyyy-MM-dd形式に統一）
                    try:
                        from datetime import datetime
                        # レシート日付をdatetimeオブジェクトに変換（日付のみ）
                        receipt_date_obj = None
                        if "/" in purchase_date:
                            receipt_date_obj = datetime.strptime(purchase_date, "%Y/%m/%d").date()
                        elif "-" in purchase_date:
                            receipt_date_obj = datetime.strptime(purchase_date[:10], "%Y-%m-%d").date()
                    except Exception:
                        receipt_date_obj = None
                    
                    for record in purchase_records:
                        record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                        if not record_date:
                            continue
                        
                        # 仕入DBの日付を正規化して比較
                        try:
                            from datetime import datetime
                            record_date_str = str(record_date).strip()
                            # 時刻が含まれている場合は日付部分のみを取得
                            if " " in record_date_str:
                                record_date_str = record_date_str.split(" ")[0]
                            if "T" in record_date_str:
                                record_date_str = record_date_str.split("T")[0]
                            
                            # 日付をdateオブジェクトに変換
                            record_date_obj = None
                            if "/" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                            elif "-" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                            
                            # 日付が一致しない場合はスキップ
                            if receipt_date_obj and record_date_obj and receipt_date_obj != record_date_obj:
                                continue
                            
                            # 日付が一致するか、または日付比較ができない場合は文字列比較
                            date_matches = False
                            if receipt_date_obj and record_date_obj:
                                date_matches = (receipt_date_obj == record_date_obj)
                            else:
                                # フォールバック: 文字列比較
                                normalized_receipt_date = purchase_date.replace("-", "/")
                                normalized_record_date = str(record_date).replace("-", "/")
                                date_matches = normalized_receipt_date[:10] in normalized_record_date[:10]
                            
                            # 仕入DBでは「仕入先」カラムに店舗コードが格納されている
                            record_store_code = record.get('仕入先') or record.get('店舗コード') or record.get('store_code', '')
                            # 店舗コードのみを取得（表示ラベルから抽出）
                            if record_store_code and " " in str(record_store_code):
                                record_store_code = str(record_store_code).split(" ")[0]
                            
                            # 日付と店舗コードが一致する場合
                            if date_matches and record_store_code == store_code_clean:
                                # レシート時間より前の時間に登録されたSKUのみを取得
                                sku = record.get('SKU') or record.get('sku', '')
                                if not sku or not sku.strip():
                                    continue
                                sku = sku.strip()
                                
                                # 時刻比較が必要な場合のみ実行
                                should_add = True
                                if receipt_datetime:
                                    # created_atが存在する場合、時刻比較を行う
                                    record_created_at = record.get('created_at') or record.get('登録日時') or ""
                                    if record_created_at:
                                        try:
                                            from datetime import datetime
                                            # created_atをdatetimeオブジェクトに変換
                                            record_dt = None
                                            if isinstance(record_created_at, str):
                                                # 文字列の場合、複数の形式に対応
                                                record_created_at_clean = str(record_created_at).strip()
                                                if 'T' in record_created_at_clean:
                                                    # ISO形式: "2024-12-05T10:30:00" または "2024-12-05T10:30:00Z"
                                                    if record_created_at_clean.endswith('Z'):
                                                        record_created_at_clean = record_created_at_clean[:-1]
                                                    if len(record_created_at_clean) >= 19:
                                                        record_dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                elif ' ' in record_created_at_clean:
                                                    # "YYYY-MM-DD HH:MM:SS"形式
                                                    if len(record_created_at_clean) >= 19:
                                                        record_dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                            else:
                                                # datetimeオブジェクトの場合
                                                record_dt = record_created_at
                                            
                                            # レシート時間より前の時間に登録されたSKUのみを追加
                                            if record_dt:
                                                should_add = (record_dt < receipt_datetime)
                                        except Exception as e:
                                            # 時刻比較に失敗した場合は、日付と店舗コードが一致するSKUを全て追加
                                            should_add = True
                                
                                if should_add and sku not in existing_skus:
                                    candidate_skus_list.addItem(sku)
                                    existing_skus.add(sku)
                        except Exception:
                            # 日付比較に失敗した場合はスキップ
                            continue
            
            load_candidate_skus()
            
            # レシートIDが変更されたときに候補SKUを再読み込み
            
            # SKU呼び出しボタン（同じ日付のSKUを時間が近い順から表示）
            fetch_sku_btn = QPushButton("SKU呼び出し")
            fetch_sku_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
            
            def fetch_skus_by_date():
                """同じ日付のSKUを時間が近い順から取得して候補リストに表示"""
                candidate_skus_list.clear()
                if not self.product_widget:
                    QMessageBox.warning(None, "警告", "仕入DBへの参照がありません。")
                    return
                
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                if not purchase_records:
                    QMessageBox.warning(None, "警告", "仕入DBにデータがありません。")
                    return
                
                # レシートの日付を取得
                purchase_date = receipt_data.get('purchase_date', '') if receipt_data else ''
                purchase_time = receipt_data.get('purchase_time', '') if receipt_data else ''  # HH:MM形式
                
                if not purchase_date:
                    QMessageBox.warning(None, "警告", "レシートの日付が設定されていません。")
                    return
                
                # レシートの店舗コード（優先表示用）を取得
                receipt_store_code_raw = receipt_data.get('store_code', '') if receipt_data else ''
                receipt_store_code_clean = str(receipt_store_code_raw).strip()
                if " " in receipt_store_code_clean:
                    receipt_store_code_clean = receipt_store_code_clean.split(" ")[0]
                # 店舗マスタから正規の店舗コード（store_code）を取得して比較に使う
                receipt_store_code_canon = receipt_store_code_clean
                try:
                    if receipt_store_code_clean:
                        store = self.store_db.get_store_by_code(receipt_store_code_clean)
                        if store:
                            receipt_store_code_canon = (store.get("store_code") or receipt_store_code_clean).strip() or receipt_store_code_clean
                except Exception:
                    pass
                
                # レシートの日時をdatetimeオブジェクトに変換（比較用）
                receipt_datetime = None
                if purchase_time:
                    try:
                        from datetime import datetime
                        date_str = purchase_date.replace("/", "-")
                        datetime_str = f"{date_str} {purchase_time}"
                        receipt_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                
                # レシートの日付を正規化
                try:
                    from datetime import datetime
                    receipt_date_obj = None
                    if "/" in purchase_date:
                        receipt_date_obj = datetime.strptime(purchase_date, "%Y/%m/%d").date()
                    elif "-" in purchase_date:
                        receipt_date_obj = datetime.strptime(purchase_date[:10], "%Y-%m-%d").date()
                except Exception:
                    receipt_date_obj = None
                
                # 同じ日付のSKUを取得（時間差も計算）
                candidate_skus_with_time = []
                existing_skus = set()
                # 既に紐付けられているSKUを取得
                for i in range(linked_skus_list.count()):
                    item = linked_skus_list.item(i)
                    if item:
                        sku = item.data(Qt.UserRole)
                        if sku:
                            existing_skus.add(sku)
                
                for record in purchase_records:
                    record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                    if not record_date:
                        continue
                    
                    # 仕入DBの日付を正規化
                    try:
                        from datetime import datetime
                        record_date_str = str(record_date).strip()
                        if " " in record_date_str:
                            record_date_str = record_date_str.split(" ")[0]
                        if "T" in record_date_str:
                            record_date_str = record_date_str.split("T")[0]
                        
                        record_date_obj = None
                        if "/" in record_date_str:
                            record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                        elif "-" in record_date_str:
                            record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                        
                        # 日付が一致しない場合はスキップ
                        if receipt_date_obj and record_date_obj and receipt_date_obj != record_date_obj:
                            continue
                        
                        # 日付が一致するか確認
                        date_matches = False
                        if receipt_date_obj and record_date_obj:
                            date_matches = (receipt_date_obj == record_date_obj)
                        else:
                            normalized_receipt_date = purchase_date.replace("-", "/")
                            normalized_record_date = str(record_date).replace("-", "/")
                            date_matches = normalized_receipt_date[:10] in normalized_record_date[:10]
                        
                        if date_matches:
                            sku = record.get('SKU') or record.get('sku', '')
                            if not sku or not sku.strip() or sku.strip() in existing_skus:
                                continue
                            
                            sku = sku.strip()
                            
                            # 時刻差を計算（レシート時刻に近い順にソートするため）
                            time_diff_seconds = float('inf')  # 時刻がない場合は最後に表示
                            record_datetime = None
                            
                            # 仕入DBの時刻を取得
                            record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                            if not record_time:
                                # created_atから時刻を取得
                                record_created_at = record.get('created_at') or record.get('登録日時') or ""
                                if record_created_at:
                                    try:
                                        from datetime import datetime
                                        if isinstance(record_created_at, str):
                                            record_created_at_clean = str(record_created_at).strip()
                                            if 'T' in record_created_at_clean:
                                                if record_created_at_clean.endswith('Z'):
                                                    record_created_at_clean = record_created_at_clean[:-1]
                                                if len(record_created_at_clean) >= 19:
                                                    record_datetime = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            elif ' ' in record_created_at_clean:
                                                if len(record_created_at_clean) >= 19:
                                                    record_datetime = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                        else:
                                            record_datetime = record_created_at
                                    except Exception:
                                        pass
                            else:
                                # 仕入れ時刻からdatetimeオブジェクトを作成
                                try:
                                    from datetime import datetime
                                    date_str = str(record_date).strip()
                                    if " " in date_str:
                                        date_str = date_str.split(" ")[0]
                                    if "T" in date_str:
                                        date_str = date_str.split("T")[0]
                                    date_str = date_str.replace("/", "-")
                                    datetime_str = f"{date_str} {record_time}"
                                    record_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                except Exception:
                                    pass
                            
                            # 時刻差を計算
                            if receipt_datetime and record_datetime:
                                time_diff = abs((receipt_datetime - record_datetime).total_seconds())
                                time_diff_seconds = time_diff
                            
                            # SKU情報を取得
                            price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                            try:
                                price = float(price) if price else 0
                            except (ValueError, TypeError):
                                price = 0
                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                            try:
                                quantity = float(quantity) if quantity else 1
                            except (ValueError, TypeError):
                                quantity = 1
                            total_amount = price * quantity
                            
                            # 商品名を取得
                            product_name = record.get('商品名') or record.get('product_name') or ''
                            
                            # 店舗コードを取得（新しい店舗コードを優先、なければ旧仕入先コードをフォールバック）
                            raw_store_code = (
                                record.get('店舗コード')
                                or record.get('store_code')
                                or record.get('仕入先')
                                or ''
                            )
                            # 店舗コードのクリーン版（比較用）
                            record_store_code_clean = str(raw_store_code).strip()
                            if " " in record_store_code_clean:
                                record_store_code_clean = record_store_code_clean.split(" ")[0]
                            # 店舗マスタから正規の店舗コード（store_code）を取得
                            record_store_code_canon = record_store_code_clean
                            try:
                                if record_store_code_clean:
                                    r_store = self.store_db.get_store_by_code(record_store_code_clean)
                                    if r_store:
                                        record_store_code_canon = (r_store.get("store_code") or record_store_code_clean).strip() or record_store_code_clean
                            except Exception:
                                pass
                            # 表示ラベル（コード + 店舗名）を生成
                            # ラベルにはクリーンなコード（旧コード含む）から、店舗マスタ経由で新店舗コードを反映する
                            store_label = self._format_store_code_label(record_store_code_clean, "")
                            
                            candidate_skus_with_time.append({
                                'sku': sku,
                                'time_diff': time_diff_seconds,
                                'price': total_amount,
                                'product_name': product_name,
                                'store_label': store_label,
                                # レシートの正規店舗コードと、仕入レコードの正規店舗コードが一致するかで優先度を決定
                                'is_same_store': bool(
                                    receipt_store_code_canon
                                    and record_store_code_canon
                                    and receipt_store_code_canon == record_store_code_canon
                                ),
                                'record_datetime': record_datetime.strftime("%Y/%m/%d %H:%M") if record_datetime else "時刻不明"
                            })
                    except Exception:
                        continue
                
                # 並び順:
                #  1. レシートと同じ店舗コードのSKUを先に表示
                #  2. その中で時間差が小さい順（レシート時刻に近い順）
                candidate_skus_with_time.sort(
                    key=lambda x: (0 if x.get('is_same_store') else 1, x['time_diff'])
                )
                
                # 候補リストに表示
                for sku_info in candidate_skus_with_time:
                    sku = sku_info['sku']
                    price = sku_info['price']
                    product_name = sku_info['product_name']
                    store_label = sku_info['store_label']
                    time_str = sku_info['record_datetime']
                    
                    # 表示テキストを作成
                    display_parts = [sku]
                    if store_label:
                        display_parts.append(f"[{store_label}]")
                    if product_name:
                        # 商品名が長い場合は切り詰め
                        name_display = product_name[:30] + "..." if len(product_name) > 30 else product_name
                        display_parts.append(name_display)
                    display_parts.append(f"¥{int(price):,}")
                    display_parts.append(f"({time_str})")
                    
                    display_text = " - ".join(display_parts)
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.UserRole, sku)  # SKUをUserRoleに保存
                    candidate_skus_list.addItem(item)
                
                if candidate_skus_list.count() == 0:
                    QMessageBox.information(None, "情報", f"日付 {purchase_date} のSKUが見つかりませんでした。")
                else:
                    QMessageBox.information(None, "情報", f"{candidate_skus_list.count()} 件のSKU候補を表示しました。")
            
            fetch_sku_btn.clicked.connect(fetch_skus_by_date)
            sku_layout.addWidget(fetch_sku_btn)
            
            # SKU追加ボタン
            add_sku_btn = QPushButton("選択SKUを追加")
            add_sku_btn.clicked.connect(lambda: self._add_skus_to_list(candidate_skus_list, linked_skus_list, total_edit))
            sku_layout.addWidget(add_sku_btn)
            
            right_layout.addWidget(sku_group)
            
            # 保存ボタン
            save_btn = QPushButton("変更を保存")
            save_btn.setStyleSheet("""
                QPushButton {
                    background-color: #007bff;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0056b3;
                }
            """)
            
            def save_changes():
                """変更を保存"""
                updates = {}
                
                # 種別と科目
                account_title = account_title_combo.currentText()
                if account_title:
                    updates['account_title'] = account_title
                
                # 日付
                date = date_edit.date()
                updates['purchase_date'] = date.toString("yyyy/MM/dd")
                
                # 時刻
                time_str = time_edit.text().strip()
                if time_str:
                    updates['purchase_time'] = time_str
                
                # 店舗名（プルダウンから選択した店舗コード＋店舗名）
                selected_store_code = store_name_combo.currentData()
                selected_store_label = store_name_combo.currentText()
                if selected_store_code:
                    updates['store_code'] = selected_store_code
                    # 店舗名（生）は店舗マスタから取得（store_code優先、互換性のため仕入れ先コードも許容）
                    try:
                        store = self.store_db.get_store_by_code(selected_store_code)
                        if store:
                            updates['store_name_raw'] = store.get('store_name', '') or selected_store_label
                    except Exception:
                        updates['store_name_raw'] = selected_store_label
                
                # 電話番号
                phone = phone_edit.text().strip()
                if phone:
                    updates['phone_number'] = phone
                
                # 合計
                try:
                    total = int(total_edit.text()) if total_edit.text().strip() else None
                    if total is not None:
                        updates['total_amount'] = total
                except ValueError:
                    pass
                
                # 値引
                try:
                    discount = int(discount_edit.text()) if discount_edit.text().strip() else None
                    if discount is not None:
                        updates['discount_amount'] = discount
                except ValueError:
                    pass
                
                # 紐付けSKU（UserRoleからSKUを取得）
                linked_skus = []
                sku_price_updates = {}  # SKUと価格のマッピング（仕入DB更新用）
                for i in range(linked_skus_list.count()):
                    item = linked_skus_list.item(i)
                    if item:
                        sku = item.data(Qt.UserRole)
                        if not sku:
                            # UserRoleがない場合は表示テキストからSKUを抽出
                            text = item.text()
                            if " - " in text:
                                sku = text.split(" - ")[0].strip()
                            else:
                                sku = text.strip()
                        
                        if sku:
                            linked_skus.append(sku)
                            # 価格を取得（UserRole + 1に保存されている場合）
                            new_price = item.data(Qt.UserRole + 1)
                            if new_price is None:
                                # UserRole + 1にない場合は表示テキストから抽出
                                text = item.text()
                                if " - ¥" in text:
                                    try:
                                        price_str = text.split(" - ¥")[1].replace(",", "").strip()
                                        new_price = int(price_str)
                                    except (ValueError, IndexError):
                                        new_price = None
                            
                            if new_price is not None:
                                sku_price_updates[sku] = new_price
                
                updates['linked_skus'] = ','.join(linked_skus) if linked_skus else None
                
                # 差額を再計算（仕入れ個数 × 仕入れ価格）
                sku_total = 0
                if self.product_widget:
                    purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                    for sku in linked_skus:
                        for record in purchase_records:
                            record_sku = record.get('SKU') or record.get('sku', '')
                            if record_sku and record_sku.strip() == sku:
                                # 価格を取得（更新後の価格を優先）
                                price = sku_price_updates.get(sku)
                                if price is None:
                                    price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                                try:
                                    price = float(price) if price else 0
                                except (ValueError, TypeError):
                                    price = 0
                                # 仕入れ個数を取得
                                quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                                try:
                                    quantity = float(quantity) if quantity else 1
                                except (ValueError, TypeError):
                                    quantity = 1
                                # 金額 = 仕入れ個数 × 仕入れ価格
                                total_amount = price * quantity
                                sku_total += total_amount
                                break
                
                # レシートの合計金額を取得
                receipt_total = updates.get('total_amount')
                if receipt_total is None:
                    try:
                        receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                    except ValueError:
                        receipt_total = 0
                
                # 差額を計算
                difference = sku_total - receipt_total
                if abs(difference) == 0:
                    updates['price_difference'] = None  # 差額が0の場合はNoneに設定
                else:
                    updates['price_difference'] = int(difference)
                
                # 仕入DBの価格を更新し、見込み利益・損益分岐点・利益率・ROIを再計算
                if sku_price_updates and self.product_widget:
                    try:
                        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                        updated_count = 0
                        for record in purchase_records:
                            sku = record.get('SKU') or record.get('sku', '')
                            if sku and sku.strip() and sku.strip() in sku_price_updates:
                                new_price = sku_price_updates[sku.strip()]
                                # 仕入れ価格を更新
                                record['仕入れ価格'] = new_price
                                
                                # 見込み利益・損益分岐点・利益率・ROIを再計算
                                planned_price = record.get('販売予定価格') or record.get('planned_price') or 0
                                try:
                                    planned_price = float(planned_price) if planned_price else 0
                                except (ValueError, TypeError):
                                    planned_price = 0
                                
                                # 見込み利益 = 販売予定価格 - 仕入れ価格
                                expected_profit = planned_price - new_price if planned_price > 0 else 0
                                record['見込み利益'] = expected_profit
                                
                                # 損益分岐点の計算（簡易版：仕入れ価格 + その他費用）
                                other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                try:
                                    other_cost = float(other_cost) if other_cost else 0
                                except (ValueError, TypeError):
                                    other_cost = 0
                                break_even = new_price + other_cost
                                record['損益分岐点'] = break_even
                                
                                # 利益率 = (見込み利益 / 販売予定価格) * 100
                                if planned_price > 0:
                                    expected_margin = (expected_profit / planned_price) * 100
                                else:
                                    expected_margin = 0.0
                                record['想定利益率'] = round(expected_margin, 2)
                                
                                # ROI = (見込み利益 / 仕入れ価格) * 100
                                if new_price > 0:
                                    expected_roi = (expected_profit / new_price) * 100
                                else:
                                    expected_roi = 0.0
                                record['想定ROI'] = round(expected_roi, 2)
                                
                                # 実際のDBに保存（ProductDatabaseのproductsテーブル）
                                if hasattr(self.product_widget, 'db'):
                                    try:
                                        # 既存のレコードを取得
                                        existing = self.product_widget.db.get_by_sku(sku.strip())
                                        if existing:
                                            # 既存レコードを更新
                                            db_record = dict(existing)
                                            db_record['purchase_price'] = new_price
                                            # 他のフィールドも保持
                                            self.product_widget.db.upsert(db_record)
                                        else:
                                            # 新規レコードを作成（最小限の情報）
                                            db_record = {
                                                'sku': sku.strip(),
                                                'purchase_price': new_price,
                                            }
                                            self.product_widget.db.upsert(db_record)
                                    except Exception as e:
                                        QMessageBox.warning(self, "警告", f"SKU {sku.strip()} のDB更新中にエラーが発生しました: {str(e)}")
                                
                                updated_count += 1
                        
                        # 仕入DBの変更をスナップショットとして保存
                        if updated_count > 0 and hasattr(self.product_widget, 'purchase_db'):
                            try:
                                from datetime import datetime
                                snapshot_name = f"レシート編集_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                                self.product_widget.purchase_db.save_snapshot(snapshot_name, purchase_records)
                            except Exception as e:
                                QMessageBox.warning(self, "警告", f"スナップショットの保存中にエラーが発生しました: {str(e)}")
                    except Exception as e:
                        QMessageBox.warning(self, "警告", f"仕入DBの更新中にエラーが発生しました: {str(e)}")
                
                # DB更新
                if updates and receipt_id:
                    self.receipt_db.update_receipt(receipt_id, updates)
                    # 仕入DBの変更を反映（product_widgetのテーブルを更新）
                    if self.product_widget and hasattr(self.product_widget, 'populate_purchase_table'):
                        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                        self.product_widget.populate_purchase_table(purchase_records)
                    # レシート一覧を更新（差額も再計算される）
                    self.refresh_receipt_list()
                    QMessageBox.information(self, "完了", "変更を保存しました。")
                    # ウインドウを閉じる
                    dialog.close()
                else:
                    QMessageBox.information(self, "情報", "変更がありません。")
            
            # 再計算ボタンと保存ボタンを横並びに配置
            button_layout = QHBoxLayout()
            
            # 再計算ボタン
            recalc_btn = QPushButton("再計算")
            recalc_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
            
            def recalculate_prices():
                """再計算ボタンの処理"""
                try:
                    # レシート情報編集エリアの値を取得
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                    discount = int(discount_edit.text()) if discount_edit.text().strip() else 0
                    
                    # 調整後の目標金額 = レシート合計 - 値引き
                    target_total = receipt_total - discount
                    
                    # 現在のSKU価格の合計を計算
                    current_total = 0
                    sku_items = []
                    for i in range(linked_skus_list.count()):
                        item = linked_skus_list.item(i)
                        if item:
                            sku = item.data(Qt.UserRole)
                            if not sku:
                                text = item.text()
                                if " - " in text:
                                    sku = text.split(" - ")[0].strip()
                                else:
                                    sku = text.strip()
                            
                            # 現在の金額を取得（仕入れ個数 × 仕入れ価格）
                            text = item.text()
                            if " - ¥" in text:
                                try:
                                    price_str = text.split(" - ¥")[1].replace(",", "").strip()
                                    total_amount = int(price_str)  # これは既に「仕入れ個数 × 仕入れ価格」の合計
                                except (ValueError, IndexError):
                                    total_amount = 0
                            else:
                                total_amount = 0
                            
                            current_total += total_amount
                            sku_items.append((item, sku, total_amount))
                    
                    if not sku_items:
                        QMessageBox.warning(self, "警告", "紐付けSKUがありません。")
                        return
                    
                    # 差額を計算
                    difference = target_total - current_total
                    
                    # 均等配分で価格を調整
                    num_skus = len(sku_items)
                    adjustment_per_sku = difference // num_skus  # 整数部分
                    remainder = difference % num_skus  # 端数
                    
                    # 10円以下の端数は最後のSKUに転嫁、それ以上は均等配分
                    small_remainder = 0
                    if abs(remainder) <= 10:
                        # 10円以下の端数は最後のSKUに転嫁
                        small_remainder = remainder
                        remainder = 0
                    else:
                        # 10円を超える端数は均等配分
                        # 端数を10円単位で均等配分し、残りを最後のSKUに
                        remainder_per_sku = remainder // num_skus
                        small_remainder = remainder % num_skus
                        adjustment_per_sku += remainder_per_sku
                    
                    # 仕入DBから価格情報を取得（更新用）
                    sku_price_map = {}
                    if self.product_widget:
                        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                        for record in purchase_records:
                            sku = record.get('SKU') or record.get('sku', '')
                            if sku and sku.strip():
                                sku_price_map[sku.strip()] = record
                    
                    # 各SKUの金額を更新（仕入れ個数 × 仕入れ価格）
                    for idx, (item, sku, old_total_amount) in enumerate(sku_items):
                        # 均等配分の調整額（合計金額に対する調整）
                        adjustment = adjustment_per_sku
                        # 最後のSKUに10円以下の端数を追加
                        if idx == len(sku_items) - 1:
                            adjustment += small_remainder
                        
                        new_total_amount = old_total_amount + adjustment
                        if new_total_amount < 0:
                            new_total_amount = 0
                        
                        # 仕入DBから仕入れ個数を取得して、仕入れ価格を計算
                        quantity = 1
                        if sku in sku_price_map:
                            record = sku_price_map[sku]
                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                            try:
                                quantity = float(quantity) if quantity else 1
                            except (ValueError, TypeError):
                                quantity = 1
                        
                        # 仕入れ価格 = 合計金額 / 仕入れ個数
                        if quantity > 0:
                            new_price = new_total_amount / quantity
                        else:
                            new_price = new_total_amount
                        
                        # 表示を更新（合計金額を表示）
                        display_text = f"{sku} - ¥{int(new_total_amount):,}"
                        item.setText(display_text)
                        # UserRole + 1に仕入れ価格を保存（仕入DB更新時に使用）
                        item.setData(Qt.UserRole + 1, int(new_price))
                    
                    # 合計と差額を更新（差額は元のレシート合計との差を表示）
                    self._update_sku_total(linked_skus_list, receipt_total)
                    
                    QMessageBox.information(self, "完了", "価格を再計算しました。")
                except Exception as e:
                    QMessageBox.warning(self, "エラー", f"再計算中にエラーが発生しました: {str(e)}")
            
            recalc_btn.clicked.connect(recalculate_prices)
            button_layout.addWidget(recalc_btn)
            
            save_btn.clicked.connect(save_changes)
            button_layout.addWidget(save_btn)
            
            right_layout.addLayout(button_layout)
            
            right_layout.addStretch()
            main_layout.addWidget(right_widget, 1)  # 編集パネルは1倍の幅

        # モーダルではなくモデルレスで表示（アプリ操作をブロックしない）
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()
    
    def _add_skus_to_list(self, source_list: QListWidget, target_list: QListWidget, total_edit=None):
        """選択されたSKUを追加（価格情報も表示）"""
        selected_items = source_list.selectedItems()
        # 既存のSKUを取得（UserRoleから）
        existing_skus = set()
        for i in range(target_list.count()):
            item = target_list.item(i)
            if item:
                sku = item.data(Qt.UserRole)
                if sku:
                    existing_skus.add(sku)
                else:
                    # UserRoleがない場合は表示テキストからSKUを抽出
                    text = item.text()
                    if " - " in text:
                        sku = text.split(" - ")[0].strip()
                        existing_skus.add(sku)
                    else:
                        existing_skus.add(text.strip())
        
        # 仕入DBから金額情報と時刻情報を取得（仕入れ個数 × 仕入れ価格）
        sku_info_map = {}  # {sku: {'price': total_amount, 'time': time_str}}
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            for record in purchase_records:
                sku = record.get('SKU') or record.get('sku', '')
                if sku and sku.strip():
                    sku = sku.strip()
                    # 仕入れ価格を取得（複数のカラム名に対応）
                    price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                    try:
                        price = float(price) if price else 0
                    except (ValueError, TypeError):
                        price = 0
                    # 仕入れ個数を取得（複数のカラム名に対応）
                    quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                    try:
                        quantity = float(quantity) if quantity else 1
                    except (ValueError, TypeError):
                        quantity = 1
                    # 金額 = 仕入れ個数 × 仕入れ価格
                    total_amount = price * quantity
                    
                    # 時刻情報を取得
                    time_str = "時刻不明"
                    
                    # 1. 「仕入れ日」カラムから取得（優先）- 「YYYY/MM/DD HH:MM」形式で日付と時刻の両方が含まれる
                    purchase_date_str = record.get('仕入れ日') or record.get('purchase_date') or ""
                    if purchase_date_str:
                        try:
                            from datetime import datetime
                            purchase_date_str_clean = str(purchase_date_str).strip()
                            # 「YYYY/MM/DD HH:MM」形式を想定
                            if ' ' in purchase_date_str_clean:
                                try:
                                    # 「YYYY/MM/DD HH:MM」形式
                                    dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    try:
                                        # 「YYYY-MM-DD HH:MM」形式
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            # 「YYYY/MM/DD HH:MM:SS」形式
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                # 「YYYY-MM-DD HH:MM:SS」形式
                                                dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                # パースできない場合はそのまま使用
                                                time_str = purchase_date_str_clean
                        except Exception as e:
                            print(f"時刻情報取得エラー (仕入れ日): {e}, 値: {purchase_date_str}")
                    
                    # 2. 「日付/時間」または「日付/時刻」カラムから取得
                    if time_str == "時刻不明":
                        datetime_str = record.get('日付/時間') or record.get('日付/時刻') or ""
                        if datetime_str:
                            try:
                                from datetime import datetime
                                datetime_str_clean = str(datetime_str).strip()
                                if ' ' in datetime_str_clean:
                                    try:
                                        dt = datetime.strptime(datetime_str_clean, "%Y/%m/%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            dt = datetime.strptime(datetime_str_clean, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = datetime_str_clean
                                elif 'T' in datetime_str_clean:
                                    try:
                                        if datetime_str_clean.endswith('Z'):
                                            datetime_str_clean = datetime_str_clean[:-1]
                                        if len(datetime_str_clean) >= 19:
                                            dt = datetime.strptime(datetime_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        pass
                            except Exception:
                                pass
                    
                    # 3. 「仕入れ時刻」または「purchase_time」カラムから取得
                    if time_str == "時刻不明":
                        record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                        if record_time:
                            try:
                                from datetime import datetime
                                record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                                if record_date:
                                    date_str = str(record_date).strip()
                                    if " " in date_str:
                                        date_str = date_str.split(" ")[0]
                                    if "T" in date_str:
                                        date_str = date_str.split("T")[0]
                                    date_str = date_str.replace("/", "-")
                                    datetime_str = f"{date_str} {record_time}"
                                    try:
                                        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        time_str = f"{date_str} {record_time}"
                            except Exception:
                                pass
                    
                    # 4. created_atから時刻を取得（最後のフォールバック）
                    if time_str == "時刻不明":
                        record_created_at = record.get('created_at') or record.get('登録日時') or ""
                        if record_created_at:
                            try:
                                from datetime import datetime
                                if isinstance(record_created_at, str):
                                    record_created_at_clean = str(record_created_at).strip()
                                    if 'T' in record_created_at_clean:
                                        if record_created_at_clean.endswith('Z'):
                                            record_created_at_clean = record_created_at_clean[:-1]
                                        if len(record_created_at_clean) >= 19:
                                            dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    elif ' ' in record_created_at_clean:
                                        if len(record_created_at_clean) >= 19:
                                            dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                            except Exception:
                                pass
                    
                    sku_info_map[sku] = {
                        'price': total_amount,
                        'time': time_str
                    }
        
        for item in selected_items:
            # UserRoleからSKUを取得（優先）
            sku = item.data(Qt.UserRole)
            if not sku:
                # UserRoleがない場合は表示テキストからSKUを抽出
                text = item.text().strip()
                if " - " in text:
                    # 「SKU - [店舗コード] - 商品名 - ¥金額 - (時刻)」形式からSKUを抽出
                    sku = text.split(" - ")[0].strip()
                else:
                    sku = text.strip()
            
            if sku and sku not in existing_skus:
                # 候補リストの表示テキストから価格と時刻を抽出（フォールバック）
                source_text = item.text()
                extracted_price = 0
                extracted_time = "時刻不明"
                
                # 表示テキストから価格を抽出（「¥金額」形式）
                if "¥" in source_text:
                    try:
                        price_parts = source_text.split("¥")
                        if len(price_parts) > 1:
                            price_str = price_parts[1].split()[0].replace(",", "").strip()
                            extracted_price = int(price_str)
                    except (ValueError, IndexError):
                        pass
                
                # 表示テキストから時刻を抽出（「(時刻)」形式）
                if "(" in source_text and ")" in source_text:
                    try:
                        time_start = source_text.rfind("(")
                        time_end = source_text.rfind(")")
                        if time_start < time_end:
                            extracted_time = source_text[time_start+1:time_end]
                    except Exception:
                        pass
                
                # 仕入DBから取得した情報を優先（なければ表示テキストから抽出した値を使用）
                sku_info = sku_info_map.get(sku, {})
                total_amount = sku_info.get('price', extracted_price)
                time_str = sku_info.get('time', extracted_time)
                
                # 表示テキストを作成
                if total_amount > 0:
                    display_text = f"{sku} - ¥{int(total_amount):,} - ({time_str})"
                else:
                    display_text = f"{sku} - 価格不明 - ({time_str})"
                
                # リストに追加
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, sku)  # SKUをUserRoleに保存
                target_list.addItem(list_item)
                existing_skus.add(sku)
        
        # 合計金額を更新
        receipt_total = None
        if total_edit:
            try:
                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
            except ValueError:
                receipt_total = 0
        self._update_sku_total(target_list, receipt_total)
    
    def _remove_sku_from_list(self, sku_list: QListWidget, total_edit=None):
        """選択されたSKUを削除"""
        selected_items = sku_list.selectedItems()
        for item in selected_items:
            row = sku_list.row(item)
            sku_list.takeItem(row)
        
        # 合計金額を更新
        receipt_total = None
        if total_edit:
            try:
                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
            except ValueError:
                receipt_total = 0
        self._update_sku_total(sku_list, receipt_total)
    
    def _edit_sku_price(self, item: QListWidgetItem, sku_list: QListWidget, total_edit, discount_edit):
        """SKU金額を編集（仕入れ個数 × 仕入れ価格の合計金額）"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QSpinBox, QDialogButtonBox
        
        # 現在の金額を取得（仕入れ個数 × 仕入れ価格の合計）
        text = item.text()
        current_total_amount = 0
        if " - ¥" in text:
            try:
                price_str = text.split(" - ¥")[1].replace(",", "").strip()
                current_total_amount = int(price_str)
            except (ValueError, IndexError):
                pass
        
        # SKUを取得
        sku = item.data(Qt.UserRole)
        if not sku:
            if " - " in text:
                sku = text.split(" - ")[0].strip()
            else:
                sku = text.strip()
        
        # 仕入DBから仕入れ個数を取得
        quantity = 1
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            for record in purchase_records:
                record_sku = record.get('SKU') or record.get('sku', '')
                if record_sku and record_sku.strip() == sku:
                    quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                    try:
                        quantity = float(quantity) if quantity else 1
                    except (ValueError, TypeError):
                        quantity = 1
                    break
        
        # カスタム金額入力ダイアログ（文字色を確実に表示）
        dialog = QDialog(self)
        dialog.setWindowTitle("金額編集")
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # ラベル（仕入れ個数も表示）
        label_text = f"SKU: {sku}\n仕入れ個数: {int(quantity)}\n新しい合計金額（仕入れ個数 × 仕入れ価格）を入力してください:"
        label = QLabel(label_text)
        label.setStyleSheet("color: #000000;")  # 黒色で確実に表示
        layout.addWidget(label)
        
        # スピンボックス
        spinbox = QSpinBox()
        spinbox.setMinimum(0)
        spinbox.setMaximum(9999999)
        spinbox.setValue(int(current_total_amount))
        spinbox.setStyleSheet("""
            QSpinBox {
                color: #000000;
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                padding: 5px;
                font-size: 12pt;
            }
            QSpinBox:focus {
                border: 2px solid #007bff;
            }
        """)
        layout.addWidget(spinbox)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # ダイアログを表示
        if dialog.exec() == QDialog.Accepted:
            new_total_amount = spinbox.value()
            
            # 仕入れ価格を計算（合計金額 / 仕入れ個数）
            if quantity > 0:
                new_price = new_total_amount / quantity
            else:
                new_price = new_total_amount
            
            # 表示を更新（合計金額と時刻を表示）
            # 既存の表示テキストから時刻情報を取得
            current_text = item.text()
            time_str = "時刻不明"
            if "(" in current_text and ")" in current_text:
                try:
                    time_start = current_text.rfind("(")
                    time_end = current_text.rfind(")")
                    if time_start < time_end:
                        time_str = current_text[time_start+1:time_end]
                except Exception:
                    pass
            
            display_text = f"{sku} - ¥{int(new_total_amount):,} - ({time_str})"
            item.setText(display_text)
            # UserRole + 1に仕入れ価格を保存（仕入DB更新時に使用）
            item.setData(Qt.UserRole + 1, int(new_price))
            
            # 合計と差額を更新
            receipt_total = None
            if total_edit:
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                except ValueError:
                    receipt_total = 0
            self._update_sku_total(sku_list, receipt_total)
    
    def _update_sku_total(self, sku_list: QListWidget, receipt_total: int = None):
        """SKUリストの合計金額と差額を更新"""
        # 親ウィジェットから合計ラベルを取得
        parent = sku_list.parent()
        if not parent:
            return
        
        # 合計金額を計算（表示テキストから金額を取得：仕入れ個数 × 仕入れ価格の合計）
        total_price = 0
        for i in range(sku_list.count()):
            item = sku_list.item(i)
            if item:
                # 表示テキストから合計金額を抽出
                # 形式: 「SKU - ¥金額 - (時刻)」または「SKU - ¥金額」または「SKU - 価格不明 - (時刻)」
                text = item.text()
                total_amount = 0
                
                if " - ¥" in text:
                    try:
                        # 「 - ¥金額 - (時刻)」または「 - ¥金額」形式から金額を抽出
                        price_part = text.split(" - ¥")[1]
                        # 時刻部分を除去（「 - (時刻)」がある場合）
                        if " - (" in price_part:
                            price_str = price_part.split(" - (")[0].replace(",", "").strip()
                        else:
                            price_str = price_part.replace(",", "").strip()
                        total_amount = int(price_str)
                    except (ValueError, IndexError):
                        total_amount = 0
                elif "¥" in text:
                    # フォールバック: 「¥金額」形式を直接検索
                    try:
                        price_parts = text.split("¥")
                        if len(price_parts) > 1:
                            price_str = price_parts[1].split()[0].replace(",", "").strip()
                            total_amount = int(price_str)
                    except (ValueError, IndexError):
                        total_amount = 0
                
                total_price += total_amount
        
        # レシート合計を取得（引数で指定されていない場合）
        if receipt_total is None:
            # 親ウィジェットから合計入力欄を探す
            total_edit = parent.findChild(QLineEdit)
            if total_edit:
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                except ValueError:
                    receipt_total = 0
            else:
                receipt_total = 0
        
        # 差額を計算
        difference = total_price - receipt_total
        difference_text = f"差額: ¥{int(difference):,}" if difference != 0 else "差額: ¥0"
        difference_color = "#FF6B6B" if difference > 0 else "#4CAF50" if difference < 0 else "#666666"
        
        # 合計ラベルを更新（オブジェクト名で検索）
        total_label = parent.findChild(QLabel, "sku_total_label")
        if total_label:
            total_label.setText(f"合計: ¥{int(total_price):,} ({difference_text})")
            total_label.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
        else:
            # オブジェクト名で見つからない場合はレイアウトから探す
            layout = parent.layout()
            if layout:
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if isinstance(widget, QLabel) and widget.text().startswith("合計:"):
                        widget.setText(f"合計: ¥{int(total_price):,} ({difference_text})")
                        widget.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
                        break
    
    def confirm_receipt_linkage(self):
        """確定ボタン: レシート管理で紐付けられた画像ファイル名を仕入DBのSKUに設定"""
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        
        # デバッグ: メソッドが呼ばれたことを確認
        print(f"[DEBUG] confirm_receipt_linkage が呼ばれました")
        print(f"[DEBUG] product_widget: {self.product_widget}")
        
        # product_widgetが設定されていない場合は警告を表示
        if not hasattr(self, 'product_widget') or not self.product_widget:
            QMessageBox.warning(
                self, "エラー",
                "仕入管理ウィジェットが設定されていません。\n"
                "データベース管理タブを開いてから再度お試しください。"
            )
            return
        
        # レシート一覧から紐付け情報を取得
        updated_count = 0
        warranty_updated_count = 0  # 保証書情報の更新件数
        error_count = 0
        error_messages = []
        
        try:
            # レシート一覧の全レコードを取得
            all_receipts = self.receipt_db.find_by_date_and_store(None, None)
            print(f"[DEBUG] レシート件数: {len(all_receipts)}")
            
            for receipt in all_receipts:
                receipt_id = receipt.get('id')
                
                # 種別判定（OCRテキストから簡易判定）- レシートのみを対象にする
                ocr_text = receipt.get('ocr_text') or ""
                doc_type = "レシート"
                if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                    doc_type = "保証書"
                
                # 保証書はスキップ（レシートのみを処理）
                if doc_type == "保証書":
                    continue
                
                # 画像ファイルパスを取得（original_file_pathを優先、なければfile_path）
                file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
                if not file_path:
                    continue
                
                # ファイルパスが存在するか確認
                image_file = Path(file_path)
                if not image_file.exists():
                    # ファイルが存在しない場合はスキップ（エラーログに記録）
                    error_count += 1
                    error_messages.append(f"レシートID {receipt_id}: 画像ファイルが見つかりません: {file_path}")
                    # デバッグログ
                    try:
                        from pathlib import Path as P
                        log_path = P(__file__).resolve().parents[1] / "desktop_error.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            from datetime import datetime
                            f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 確定ボタン: ファイルが見つかりません\n")
                            f.write(f"  receipt_id: {receipt_id}\n")
                            f.write(f"  file_path: {file_path}\n")
                            f.write(f"  original_file_path: {receipt.get('original_file_path')}\n")
                            f.write(f"  file_path (DB): {receipt.get('file_path')}\n")
                    except Exception:
                        pass
                    continue
                
                # ファイル名（拡張子なし）を取得（表示用）
                # レシート一覧テーブルと同じ方法で取得（Path(file_path).nameから拡張子を除去）
                image_file_name = image_file.stem
                if not image_file_name:
                    continue
                
                # 紐付けられたSKUを取得
                linked_skus_text = receipt.get('linked_skus', '') or ''
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
                
                print(f"[DEBUG] レシートID {receipt_id}: linked_skus_text={linked_skus_text}, linked_skus={linked_skus}")
                
                if not linked_skus:
                    print(f"[DEBUG] レシートID {receipt_id}: SKUが紐付けられていないためスキップ")
                    continue
                
                # 各SKUに対して仕入DBを更新
                for sku in linked_skus:
                    try:
                        # 仕入DBから該当SKUのレコードを取得
                        if not hasattr(self, 'product_widget') or not self.product_widget:
                            continue
                        
                        # まず、purchase_all_recordsを更新（確実に反映）
                        found_in_records = False
                        if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                            for record in self.product_widget.purchase_all_records:
                                record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                if record_sku == sku:
                                    # ファイル名（拡張子なし）を保存（表示用）
                                    # 実際のファイルパスはreceipt_dbから検索できる
                                    record['レシート画像'] = image_file_name
                                    found_in_records = True
                                    break
                        
                        # ProductDatabaseから商品を取得して更新（永続化のため）
                        product = self.product_widget.db.get_by_sku(sku)
                        if product:
                            # レシート画像を更新
                            product['receipt_id'] = image_file_name
                            self.product_widget.db.upsert(product)
                        else:
                            # ProductDatabaseに商品がない場合は、最小限の情報で作成
                            try:
                                # purchase_all_recordsから商品情報を取得
                                product_data = None
                                if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                                    for record in self.product_widget.purchase_all_records:
                                        record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                        if record_sku == sku:
                                            product_data = {
                                                'sku': sku,
                                                'receipt_id': image_file_name,
                                                'product_name': record.get('商品名') or record.get('product_name'),
                                                'jan': record.get('JAN') or record.get('jan'),
                                                'asin': record.get('ASIN') or record.get('asin'),
                                                'purchase_price': record.get('仕入れ価格') or record.get('purchase_price'),
                                                'purchase_date': record.get('仕入れ日') or record.get('purchase_date'),
                                            }
                                            break
                                
                                if product_data:
                                    self.product_widget.db.upsert(product_data)
                            except Exception as e:
                                import traceback
                                print(f"ProductDatabase作成エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
                        
                        if not found_in_records:
                            updated_count += 1
                        
                        # 仕入管理タブのデータを確認
                        if hasattr(self.product_widget, 'inventory_data') and self.product_widget.inventory_data is not None:
                            import pandas as pd
                            for idx, row in self.product_widget.inventory_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    if 'レシート画像' not in self.product_widget.inventory_data.columns:
                                        self.product_widget.inventory_data['レシート画像'] = ''
                                    self.product_widget.inventory_data.at[idx, 'レシート画像'] = image_file_name
                                    if not found_in_records:
                                        updated_count += 1
                                    break
                        
                        # filtered_dataも更新
                        if hasattr(self.product_widget, 'filtered_data') and self.product_widget.filtered_data is not None:
                            for idx, row in self.product_widget.filtered_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    if 'レシート画像' not in self.product_widget.filtered_data.columns:
                                        self.product_widget.filtered_data['レシート画像'] = ''
                                    self.product_widget.filtered_data.at[idx, 'レシート画像'] = image_file_name
                                    break
                        
                        if found_in_records:
                            updated_count += 1
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"SKU {sku}: {str(e)}")
                        import traceback
                        print(f"確定処理エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
            
            # 保証書一覧から情報を取得して仕入DBに反映
            if hasattr(self, 'warranty_table') and self.warranty_table.rowCount() > 0:
                warranty_updated_count = 0
                for warranty_row in range(self.warranty_table.rowCount()):
                    try:
                        # SKUを取得
                        sku_item = self.warranty_table.item(warranty_row, 7)  # SKU列
                        if not sku_item:
                            continue
                        sku = sku_item.text().strip()
                        if not sku:
                            continue
                        
                        # receipt_idから保証書情報を取得
                        id_item = self.warranty_table.item(warranty_row, 0)  # ID列
                        if not id_item:
                            continue
                        try:
                            receipt_id = int(id_item.text())
                        except ValueError:
                            continue
                        
                        # receipt_idからレシートDBから情報を取得
                        receipt_info = self.receipt_db.get_receipt(receipt_id)
                        warranty_image_name = ""
                        if receipt_info:
                            # ファイルパスを取得（original_file_pathを優先、なければfile_path）
                            file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                            if file_path:
                                from pathlib import Path
                                file_path_obj = Path(file_path)
                                if file_path_obj.exists():
                                    # ファイル名（拡張子なし）を取得
                                    warranty_image_name = file_path_obj.stem
                                else:
                                    # ファイルが存在しない場合でも、ファイル名を取得
                                    warranty_image_name = file_path_obj.stem
                        
                        # 保証期間(日)を取得
                        warranty_days_item = self.warranty_table.item(warranty_row, 9)  # 保証期間(日)列
                        warranty_days = None
                        if warranty_days_item:
                            warranty_days_text = warranty_days_item.text().strip()
                            if warranty_days_text:
                                try:
                                    warranty_days = int(warranty_days_text)
                                except ValueError:
                                    pass
                        
                        # 保証最終日を取得
                        warranty_until = None
                        warranty_until_widget = self.warranty_table.cellWidget(warranty_row, 10)  # 保証最終日列（QDateEdit）
                        if warranty_until_widget:
                            from PySide6.QtWidgets import QDateEdit
                            if isinstance(warranty_until_widget, QDateEdit):
                                qdate = warranty_until_widget.date()
                                if qdate.isValid():
                                    warranty_until = qdate.toString("yyyy-MM-dd")
                        
                        # 仕入DBから該当SKUのレコードを取得して更新
                        if not hasattr(self, 'product_widget') or not self.product_widget:
                            continue
                        
                        # purchase_all_recordsを更新
                        found_in_records = False
                        if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                            for record in self.product_widget.purchase_all_records:
                                record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                if record_sku == sku:
                                    # 保証書画像を更新
                                    if warranty_image_name:
                                        record['保証書画像'] = warranty_image_name
                                    # 保証期間を更新
                                    if warranty_days is not None:
                                        record['保証期間'] = warranty_days
                                    # 保証最終日を更新
                                    if warranty_until:
                                        record['保証最終日'] = warranty_until
                                    found_in_records = True
                                    break
                        
                        # ProductDatabaseから商品を取得して更新（永続化のため）
                        product = self.product_widget.db.get_by_sku(sku)
                        if product:
                            # 保証書画像を更新（warranty_imageは使用しない、保証書画像カラムに直接保存）
                            # 保証書画像はpurchase_all_recordsに保存されるため、ここでは特に処理不要
                            
                            # 保証期間を更新
                            if warranty_days is not None:
                                product['warranty_period_days'] = warranty_days
                            
                            # 保証最終日を更新
                            if warranty_until:
                                product['warranty_until'] = warranty_until
                            
                            self.product_widget.db.upsert(product)
                        else:
                            # ProductDatabaseに商品がない場合は、最小限の情報で作成
                            try:
                                product_data = None
                                if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                                    for record in self.product_widget.purchase_all_records:
                                        record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                        if record_sku == sku:
                                            product_data = {
                                                'sku': sku,
                                                'product_name': record.get('商品名') or record.get('product_name'),
                                                'jan': record.get('JAN') or record.get('jan'),
                                                'asin': record.get('ASIN') or record.get('asin'),
                                                'purchase_price': record.get('仕入れ価格') or record.get('purchase_price'),
                                                'purchase_date': record.get('仕入れ日') or record.get('purchase_date'),
                                            }
                                            # 保証書情報を追加
                                            if warranty_image_name:
                                                product_data['warranty_image'] = warranty_image_name
                                            if warranty_days is not None:
                                                product_data['warranty_period_days'] = warranty_days
                                            if warranty_until:
                                                product_data['warranty_until'] = warranty_until
                                            break
                                
                                if product_data:
                                    self.product_widget.db.upsert(product_data)
                            except Exception as e:
                                import traceback
                                print(f"ProductDatabase作成エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
                        
                        # 仕入管理タブのデータを確認
                        if hasattr(self.product_widget, 'inventory_data') and self.product_widget.inventory_data is not None:
                            import pandas as pd
                            for idx, row in self.product_widget.inventory_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    # 保証書画像を更新
                                    if warranty_image_name:
                                        if '保証書画像' not in self.product_widget.inventory_data.columns:
                                            self.product_widget.inventory_data['保証書画像'] = ''
                                        self.product_widget.inventory_data.at[idx, '保証書画像'] = warranty_image_name
                                    # 保証期間を更新
                                    if warranty_days is not None:
                                        if '保証期間' not in self.product_widget.inventory_data.columns:
                                            self.product_widget.inventory_data['保証期間'] = ''
                                        self.product_widget.inventory_data.at[idx, '保証期間'] = warranty_days
                                    # 保証最終日を更新
                                    if warranty_until:
                                        if '保証最終日' not in self.product_widget.inventory_data.columns:
                                            self.product_widget.inventory_data['保証最終日'] = ''
                                        self.product_widget.inventory_data.at[idx, '保証最終日'] = warranty_until
                                    if not found_in_records:
                                        warranty_updated_count += 1
                                    break
                        
                        # filtered_dataも更新
                        if hasattr(self.product_widget, 'filtered_data') and self.product_widget.filtered_data is not None:
                            for idx, row in self.product_widget.filtered_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    # 保証書画像を更新
                                    if warranty_image_name:
                                        if '保証書画像' not in self.product_widget.filtered_data.columns:
                                            self.product_widget.filtered_data['保証書画像'] = ''
                                        self.product_widget.filtered_data.at[idx, '保証書画像'] = warranty_image_name
                                    # 保証期間を更新
                                    if warranty_days is not None:
                                        if '保証期間' not in self.product_widget.filtered_data.columns:
                                            self.product_widget.filtered_data['保証期間'] = ''
                                        self.product_widget.filtered_data.at[idx, '保証期間'] = warranty_days
                                    # 保証最終日を更新
                                    if warranty_until:
                                        if '保証最終日' not in self.product_widget.filtered_data.columns:
                                            self.product_widget.filtered_data['保証最終日'] = ''
                                        self.product_widget.filtered_data.at[idx, '保証最終日'] = warranty_until
                                    break
                        
                        if found_in_records:
                            warranty_updated_count += 1
                        else:
                            warranty_updated_count += 1
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"保証書処理エラー (SKU={sku if 'sku' in locals() else '不明'}): {str(e)}")
                        import traceback
                        print(f"保証書確定処理エラー: {e}\n{traceback.format_exc()}")
                
                updated_count += warranty_updated_count
            
            # 仕入管理タブのテーブル表示を更新
            if updated_count > 0 and hasattr(self, 'product_widget') and self.product_widget:
                # スナップショットを保存（アプリ再起動後も保持されるように）
                if hasattr(self.product_widget, 'save_purchase_snapshot'):
                    try:
                        self.product_widget.save_purchase_snapshot()
                    except Exception as e:
                        import traceback
                        print(f"スナップショット保存エラー: {e}\n{traceback.format_exc()}")
                
                if hasattr(self.product_widget, 'update_table'):
                    try:
                        self.product_widget.update_table()
                    except Exception:
                        pass
                
                if hasattr(self.product_widget, 'populate_purchase_table'):
                    try:
                        if hasattr(self.product_widget, 'purchase_all_records'):
                            self.product_widget.populate_purchase_table(self.product_widget.purchase_all_records)
                    except Exception:
                        pass
            
            # 結果を表示
            receipt_count = updated_count - warranty_updated_count
            warranty_count = warranty_updated_count
            
            print(f"[DEBUG] 確定処理完了: receipt_count={receipt_count}, warranty_count={warranty_count}, error_count={error_count}")
            
            if receipt_count == 0 and warranty_count == 0 and error_count == 0:
                # 処理対象がなかった場合
                QMessageBox.information(
                    self, "確定",
                    "確定するレコードがありませんでした。\n"
                    "レシート一覧にSKUが紐付けられているレコードがあるか確認してください。"
                )
            elif error_count == 0:
                message = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
                if warranty_count > 0:
                    message += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
                QMessageBox.information(
                    self, "確定完了",
                    message
                )
            else:
                message = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
                if warranty_count > 0:
                    message += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
                message += f"\n\nエラー: {error_count} 件\n" + "\n".join(error_messages[:5])
                QMessageBox.warning(
                    self, "確定完了（一部エラー）",
                    message
                )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, "エラー",
                f"確定処理中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
            )

