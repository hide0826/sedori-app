#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗一覧管理ウィジェット（店舗マスタタブ用）。"""
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
from typing import Tuple, List, Dict, Any, Optional, Set
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

from .support import (
    get_store_info_from_google,
    recover_store_info_with_japanese,
    normalize_stored_japanese_address,
)
from .store_dialogs import StoreEditDialog, CustomFieldEditDialog
from .route_dialogs import RouteManagementDialog
from services.hardoff_collocation_groups import (
    collocation_group_key,
    collocation_toggle_label,
    group_hardoff_family_stores,
)

STORE_LIST_BASIC_COLUMNS = [
    "ID",
    "併設",
    "所属ルート名",
    "ルートコード",
    "店舗コード",
    "店舗名",
    "住所",
    "電話番号",
    "登録番号",
    "タグ",
    "備考",
    "経度緯度",
]


class StoreListWidget(QWidget):
    """店舗一覧管理ウィジェット（店舗マスタタブ用）"""

    routes_changed = Signal()
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self.excel_importer = ExcelImporter()
        self.current_filtered_route = None  # 現在フィルタリング中のルート名
        self.current_selected_route = None  # 現在選択中のルート名
        # ルート情報リスト（コンボボックスの並び順と完全に一致させる）
        # 各要素は {'route_name': str, 'route_code': str, 'store_count': int, 'google_map_url': str} の辞書
        self.route_data = []
        self._all_stores_for_table: List[Dict[str, Any]] = []
        self._expanded_collocations: Set[str] = set()
        self._pending_expand_store_ids: Set[int] = set()
        
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

        csv_import_btn = QPushButton("CSVインポート")
        csv_import_btn.setToolTip(
            "Google Takeout「お気に入りの場所.csv」から未登録店舗を取り込みます。\n"
            "未所属ルートへ登録し、住所・電話・緯度経度を取得して店舗コードを自動付番します。"
        )
        csv_import_btn.clicked.connect(self.import_takeout_csv)
        csv_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #20c997;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(csv_import_btn)
        
        # 店舗追加ボタン
        add_btn = QPushButton("店舗追加")
        add_btn.clicked.connect(self.add_store)
        button_layout.addWidget(add_btn)
        
        # 店舗編集ボタン
        edit_btn = QPushButton("店舗編集")
        edit_btn.clicked.connect(self.edit_store)
        button_layout.addWidget(edit_btn)
        
        # 店舗削除ボタン
        delete_btn = QPushButton("店舗削除")
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

        tags_btn = QPushButton("店舗タグ管理")
        tags_btn.setToolTip("大型店舗・値付け甘い など複数タグを管理します")
        tags_btn.clicked.connect(self.manage_store_tags)
        tags_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(tags_btn)
        
        button_layout.addStretch()
        
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
                background-color: #28a745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #218838;
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
        
        # 経度緯度取得ボタン（既存データ向け）
        fetch_coords_btn = QPushButton("経度緯度取得")
        fetch_coords_btn.clicked.connect(self.fetch_missing_coordinates)
        fetch_coords_btn.setToolTip(
            "緯度経度が未設定の店舗について、Google Maps APIで取得してDBに保存します"
        )
        fetch_coords_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 120px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a32a3;
            }
        """)
        route_layout.addWidget(fetch_coords_btn)
        
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
        self.update_statistics()
    
    def update_route_combo(self, routes: list):
        """ルート選択プルダウンを更新"""
        # clear()/addItem() のたびに currentTextChanged が飛び、先頭ルートで
        # current_selected_route が上書きされるため、再構築前に維持したいルート名を退避する。
        # ルート呼び出し中は current_filtered_route を優先（編集ダイアログから戻った直後も同じルートに戻す）
        preserve_route_name = self.current_filtered_route or self.current_selected_route

        self.route_combo.blockSignals(True)
        self.route_combo.clear()
        # ルート情報リストをそのまま保持（順序を維持）
        self.route_data = list(routes) if routes else []

        for route in self.route_data:
            route_name = route.get('route_name', '')
            route_code = route.get('route_code', '')
            store_count = route.get('store_count', 0)
            display_text = f"{route_name} ({route_code}) - {store_count}店舗"

            self.route_combo.addItem(display_text)

        new_index = 0
        if preserve_route_name and self.route_data:
            for i, route in enumerate(self.route_data):
                if route.get('route_name') == preserve_route_name:
                    new_index = i
                    break

        if self.route_combo.count() > 0:
            self.route_combo.setCurrentIndex(new_index)

        self.route_combo.blockSignals(False)

        # block 中はシグナルが飛ばないため、URL・current_selected_route を同期
        if self.route_combo.count() > 0 and self.route_combo.currentIndex() >= 0:
            self.on_route_selection_changed(self.route_combo.currentText())
    
    def _adjust_route_combo_store_count(self, route_name: str, delta: int) -> None:
        """ルート選択コンボの店舗数表示を delta 件ぶん更新（追加 +1 / 削除 -1 など）"""
        name = (route_name or "").strip()
        if not name or delta == 0:
            return
        for i, r in enumerate(self.route_data):
            if (r.get("route_name") or "").strip() != name:
                continue
            cur = int(r.get("store_count", 0) or 0)
            new_cnt = max(0, cur + delta)
            r["store_count"] = new_cnt
            rn = r.get("route_name", "") or ""
            rc = r.get("route_code", "") or ""
            disp = f"{rn} ({rc}) - {new_cnt}店舗"
            if 0 <= i < self.route_combo.count():
                self.route_combo.blockSignals(True)
                self.route_combo.setItemText(i, disp)
                self.route_combo.blockSignals(False)
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

                # 緯度経度が未設定の場合は同時に更新
                if not self._store_has_coordinates(store):
                    lat = info.get('latitude')
                    lng = info.get('longitude')
                    if lat is not None and lng is not None:
                        update_data['latitude'] = lat
                        update_data['longitude'] = lng
                
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
    
    @staticmethod
    def _store_has_coordinates(store: Dict[str, Any]) -> bool:
        """店舗に緯度経度が保存されているか"""
        lat = store.get('latitude')
        lng = store.get('longitude')
        if lat is None or lng is None or lat == '' or lng == '':
            return False
        try:
            float(lat)
            float(lng)
            return True
        except (TypeError, ValueError):
            return False

    def fetch_missing_coordinates(self):
        """緯度経度が未設定の店舗の座標をGoogle Maps APIから取得"""
        def safe_strip(value):
            if value is None:
                return ''
            return str(value).strip() if isinstance(value, str) else ''

        if get_store_info_from_google is None:
            QMessageBox.warning(
                self,
                "エラー",
                "Google Mapsサービスモジュールが読み込めませんでした。\n"
                "googlemapsライブラリがインストールされているか確認してください。"
            )
            return

        stores = self.db.list_stores()
        if self.current_filtered_route:
            stores = [
                store for store in stores
                if store.get('affiliated_route_name') == self.current_filtered_route
            ]

        missing_coords_stores = []
        for store in stores:
            if not store:
                continue
            store_name = safe_strip(store.get('store_name'))
            if store_name and not self._store_has_coordinates(store):
                missing_coords_stores.append(store)

        if not missing_coords_stores:
            QMessageBox.information(
                self,
                "情報",
                "緯度経度が未設定の店舗はありません。"
            )
            return

        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(missing_coords_stores)}件の店舗の緯度経度を取得しますか？\n"
            f"（Google Maps APIを使用します）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(
            "緯度経度を取得中...", "キャンセル", 0, len(missing_coords_stores), self
        )
        progress.setWindowTitle("経度緯度取得中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        updated_count = 0
        failed_count = 0

        for i, store in enumerate(missing_coords_stores):
            if progress.wasCanceled():
                break

            store_id = store.get('id')
            store_name = safe_strip(store.get('store_name'))

            progress.setValue(i)
            progress.setLabelText(f"取得中: {store_name}")
            QApplication.processEvents()

            info = get_store_info_from_google(store_name, language_code='ja')
            if info and info.get('latitude') is not None and info.get('longitude') is not None:
                try:
                    self.db.update_store(store_id, {
                        'latitude': info['latitude'],
                        'longitude': info['longitude'],
                    })
                    updated_count += 1
                except Exception as e:
                    print(f"緯度経度の更新エラー (ID: {store_id}): {e}")
                    failed_count += 1
            else:
                failed_count += 1

        progress.setValue(len(missing_coords_stores))
        progress.close()

        QMessageBox.information(
            self,
            "完了",
            f"経度緯度取得が完了しました。\n\n"
            f"更新: {updated_count}件\n"
            f"失敗: {failed_count}件"
        )
        self.load_stores(self.search_edit.text())
    
    def recover_japanese_store_info(self):
        """非標準の住所形式（逆順・Japan/日本付き等）を日本式に再取得・整形して更新"""
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
            "住所が 〒郵便番号 都道府県… 形式でない店舗を修正します。\n"
            "（Google Maps APIで再取得し、必要時はローカル整形します）\n"
            "実行しますか？",
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
            
            progress.close()
            
            # 結果を表示
            message = f"データリカバリーが完了しました。\n\n"
            message += f"対象: {result['total']}件\n"
            message += f"更新成功: {result['updated']}件\n"
            message += f"失敗: {result['failed']}件"
            
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
        # ダブルクリックは店舗編集ダイアログに使うため、
        # セル編集は「選択済みセルのクリック」または「F2」に限定
        self.store_table.setEditTriggers(QTableWidget.SelectedClicked | QTableWidget.EditKeyPressed)
        # テキストの省略（...）を無効化
        self.store_table.setTextElideMode(Qt.ElideNone)
        # テキストを折り返して全文表示
        self.store_table.setWordWrap(True)
        
        # 併設グループ表示のため、ヘッダーソートは無効（検索で絞り込み）
        self.store_table.setSortingEnabled(False)
        
        # ヘッダー設定（列幅は ui_utils が永続化）
        header = self.store_table.horizontalHeader()
        header.setSectionsClickable(False)
        
        # 備考欄の変更を監視
        self.store_table.cellChanged.connect(self.on_store_cell_changed)
        self.store_table.cellClicked.connect(self.on_store_table_cell_clicked)
        # 店舗行ダブルクリックで編集ウィンドウを開く
        self.store_table.cellDoubleClicked.connect(self.on_store_table_double_clicked)
        
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

    def refresh_after_external_change(
        self, expand_store_ids: Optional[List[int]] = None
    ) -> None:
        """他タブ（ルート一覧など）での店舗追加・分離後に一覧を再読込する。"""
        if expand_store_ids:
            for sid in expand_store_ids:
                try:
                    self._pending_expand_store_ids.add(int(sid))
                except (TypeError, ValueError):
                    continue
        search = ""
        if hasattr(self, "search_edit") and self.search_edit is not None:
            search = self.search_edit.text()
        self.load_stores(search)
    
    def load_custom_fields(self):
        """カスタムフィールド定義を読み込む"""
        self.custom_fields_def = self.db.list_custom_fields(active_only=True)
    
    def update_table(self, stores: list):
        """テーブルを更新（HA/HO/OF 併設は代表行＋展開）。"""
        self.store_table.setSortingEnabled(False)
        self.load_custom_fields()
        self.db.attach_tags_to_stores(stores)

        def _code_key(s):
            return str(s.get("store_code") or s.get("supplier_code") or "").upper()

        stores_sorted = sorted(list(stores), key=_code_key)
        self._all_stores_for_table = stores_sorted

        def _norm_store_name(name):
            return str(name or "").strip()

        name_counts = {}
        for s in stores_sorted:
            n = _norm_store_name(s.get("store_name", ""))
            if n:
                name_counts[n] = name_counts.get(n, 0) + 1

        basic_columns = list(STORE_LIST_BASIC_COLUMNS)
        custom_columns = [field["display_name"] for field in self.custom_fields_def]
        columns = basic_columns + custom_columns

        display_rows = []
        grouped = group_hardoff_family_stores(stores_sorted)
        # 分離直後など: 対象店舗が属する併設グループを自動展開
        if self._pending_expand_store_ids:
            pending = set(self._pending_expand_store_ids)
            for group in grouped:
                member_ids = set()
                for m in group.members:
                    try:
                        member_ids.add(int(m.get("id") or 0))
                    except (TypeError, ValueError):
                        continue
                if member_ids & pending:
                    self._expanded_collocations.add(collocation_group_key(group.members))
            self._pending_expand_store_ids.clear()

        for group in grouped:
            members = group.members
            gkey = collocation_group_key(members)
            n = group.member_count
            is_group = n > 1
            expanded = bool(is_group and gkey in self._expanded_collocations)
            display_rows.append(
                {
                    "store": group.representative,
                    "kind": "col_header" if is_group else "solo",
                    "group_key": gkey,
                    "member_count": n,
                    "expanded": expanded,
                }
            )
            if is_group and expanded:
                for member in members[1:]:
                    display_rows.append(
                        {
                            "store": member,
                            "kind": "col_member",
                            "group_key": gkey,
                            "member_count": n,
                            "expanded": True,
                        }
                    )

        self.store_table.setRowCount(len(display_rows))
        self.store_table.setColumnCount(len(columns))
        self.store_table.setHorizontalHeaderLabels(columns)
        self.store_table.blockSignals(True)

        colloc_col = basic_columns.index("併設")
        registration_col_index = basic_columns.index("登録番号")
        store_name_col_index = basic_columns.index("店舗名")
        tags_col_index = basic_columns.index("タグ")
        notes_col_index = basic_columns.index("備考")
        coords_col_index = basic_columns.index("経度緯度")
        route_name_col = basic_columns.index("所属ルート名")

        for i, row_info in enumerate(display_rows):
            store = row_info["store"]
            store_id = store.get("id", 0)
            kind = row_info["kind"]
            member_count = int(row_info["member_count"] or 1)
            expanded = bool(row_info["expanded"])

            id_item = QTableWidgetItem()
            id_item.setData(Qt.EditRole, store_id)
            id_item.setText(str(store_id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            id_item.setData(Qt.UserRole + 1, row_info)
            self.store_table.setItem(i, 0, id_item)

            if kind == "col_header":
                badge = collocation_toggle_label(member_count, expanded=expanded)
            elif kind == "col_member":
                badge = "　└"
            else:
                badge = ""
            colloc_item = QTableWidgetItem(badge)
            colloc_item.setFlags(colloc_item.flags() & ~Qt.ItemIsEditable)
            colloc_item.setTextAlignment(Qt.AlignCenter)
            if kind == "col_header":
                colloc_item.setForeground(QColor("#90caf9"))
                colloc_item.setToolTip(
                    f"併設 {member_count} 店舗（ハードオフ／ホビーオフ／オフハウス・30m以内）\n"
                    "クリックで展開・折りたたみ"
                )
            elif kind == "col_member":
                colloc_item.setForeground(QColor("#b0bec5"))
            self.store_table.setItem(i, colloc_col, colloc_item)

            store_code = store.get("store_code", "") or store.get("supplier_code", "")
            base_affiliated_route_name = store.get("affiliated_route_name", "") or ""
            route_code_str = store.get("route_code", "") or ""
            display_route_name = base_affiliated_route_name
            if route_code_str:
                codes = [code.strip() for code in route_code_str.split(",") if code.strip()]
                route_names = []
                for code in codes:
                    try:
                        name = self.db.get_route_name_by_code(code) or ""
                    except Exception:
                        name = ""
                    if name:
                        route_names.append(name)
                if route_names:
                    seen = set()
                    ordered_names = []
                    for name in route_names:
                        if name not in seen:
                            seen.add(name)
                            ordered_names.append(name)
                    display_route_name = ",".join(ordered_names)

            store_name_display = str(store.get("store_name", "") or "")
            if kind == "col_member":
                store_name_display = f"　{store_name_display}"

            values = [
                display_route_name,
                route_code_str,
                store_code,
                store_name_display,
                store.get("address", ""),
                store.get("phone", ""),
                store.get("registration_number", ""),
            ]
            for offset, value in enumerate(values):
                col = route_name_col + offset
                item = QTableWidgetItem(str(value) if value else "")
                if col == store_name_col_index:
                    nm = _norm_store_name(store.get("store_name", ""))
                    if nm and name_counts.get(nm, 0) >= 2:
                        item.setForeground(QColor(200, 0, 0))
                        item.setToolTip(f"店舗名が重複しています: {nm}")
                    elif kind == "col_member":
                        item.setForeground(QColor("#b0bec5"))
                if col == registration_col_index:
                    item.setData(Qt.UserRole, store_id)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.store_table.setItem(i, col, item)

            tag_names = [
                str(t.get("name") or "")
                for t in (store.get("tags") or [])
                if t.get("name")
            ]
            tags_text = " / ".join(tag_names)
            tags_item = QTableWidgetItem(tags_text)
            tags_item.setFlags(tags_item.flags() & ~Qt.ItemIsEditable)
            tags_item.setToolTip(tags_text)
            if tag_names:
                top_color = (store.get("tags") or [{}])[0].get("color") or "#1976d2"
                tags_item.setForeground(QColor(top_color))
            self.store_table.setItem(i, tags_col_index, tags_item)

            notes_text = store.get("notes", "") or ""
            notes_item = QTableWidgetItem(notes_text)
            notes_item.setData(Qt.UserRole, store_id)
            notes_item.setToolTip(notes_text)
            self.store_table.setItem(i, notes_col_index, notes_item)

            has_coords = self._store_has_coordinates(store)
            coords_item = QTableWidgetItem("✓" if has_coords else "")
            coords_item.setTextAlignment(Qt.AlignCenter)
            coords_item.setFlags(coords_item.flags() & ~Qt.ItemIsEditable)
            if has_coords:
                coords_item.setToolTip(
                    f"緯度: {store.get('latitude')}\n経度: {store.get('longitude')}"
                )
            self.store_table.setItem(i, coords_col_index, coords_item)

            custom_fields = store.get("custom_fields", {})
            for j, field_def in enumerate(self.custom_fields_def):
                col_idx = len(basic_columns) + j
                field_name = field_def["field_name"]
                value = custom_fields.get(field_name, "")
                field_type = field_def.get("field_type", "TEXT")
                item = QTableWidgetItem()
                if field_type == "INTEGER":
                    try:
                        item.setData(Qt.EditRole, int(value) if value else 0)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0)
                    item.setText(str(value) if value else "")
                elif field_type == "REAL":
                    try:
                        item.setData(Qt.EditRole, float(value) if value else 0.0)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0.0)
                    item.setText(str(value) if value else "")
                else:
                    item.setText(str(value) if value else "")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.store_table.setItem(i, col_idx, item)

        self.store_table.blockSignals(False)
        self.store_table.setSortingEnabled(False)
        reapply_table_column_widths(self.store_table)
        self.store_table.resizeRowsToContents()

    def on_store_table_cell_clicked(self, row: int, column: int) -> None:
        """併設列クリックで展開・折りたたみ。"""
        basic_columns = list(STORE_LIST_BASIC_COLUMNS)
        if column != basic_columns.index("併設"):
            return
        id_item = self.store_table.item(row, 0)
        if not id_item:
            return
        row_info = id_item.data(Qt.UserRole + 1) or {}
        if not isinstance(row_info, dict):
            return
        if row_info.get("kind") != "col_header":
            return
        if int(row_info.get("member_count") or 0) <= 1:
            return
        gkey = str(row_info.get("group_key") or "")
        if not gkey:
            return
        if gkey in self._expanded_collocations:
            self._expanded_collocations.discard(gkey)
        else:
            self._expanded_collocations.add(gkey)
        self.update_table(self._all_stores_for_table)

    def update_statistics(self):
        """統計情報を更新"""
        stats = self.db.get_statistics()
        self.stats_label.setText(
            f"統計: 店舗数 {stats['total_stores']}件, "
            f"登録ルート数 {stats['registered_routes']}件"
            " ／ 併設列の「＋2店舗併設」「＋3店舗併設」をクリックで展開"
        )
    
    def on_store_cell_changed(self, row: int, column: int):
        """セルが変更されたときの処理（登録番号・備考欄を保存）"""
        # 登録番号列と備考列のみ保存対象
        basic_columns = list(STORE_LIST_BASIC_COLUMNS)
        registration_column_index = basic_columns.index("登録番号")
        notes_column_index = basic_columns.index("備考")
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

    def on_store_table_double_clicked(self, row: int, column: int):
        """店舗一覧の行をダブルクリックしたときに編集ダイアログを開く"""
        _ = column  # どの列でダブルクリックされても同じ処理
        if row < 0:
            return
        self.store_table.selectRow(row)
        self.edit_store()
    
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
            self.load_routes()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"Excelインポートに失敗しました:\n{str(e)}")

    def import_takeout_csv(self):
        """Google Takeout お気に入り CSV から未登録店舗を未所属で取り込む。"""
        try:
            from services.google_takeout_favorites_import import (
                import_takeout_favorites,
                parse_takeout_favorites_csv,
            )
        except Exception:
            try:
                from google_takeout_favorites_import import (  # type: ignore
                    import_takeout_favorites,
                    parse_takeout_favorites_csv,
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "エラー",
                    f"CSVインポートモジュールを読み込めませんでした:\n{e}",
                )
                return

        if get_store_info_from_google is None:
            QMessageBox.warning(
                self,
                "エラー",
                "Google Mapsサービスが読み込めません。\n"
                "設定タブの Maps API キーも確認してください。",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "お気に入りの場所.csv を選択",
            "",
            "CSVファイル (*.csv);;すべてのファイル (*)",
        )
        if not file_path:
            return

        try:
            preview_rows = parse_takeout_favorites_csv(file_path)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"CSVの読み込みに失敗しました:\n{e}")
            return

        if not preview_rows:
            QMessageBox.information(self, "CSVインポート", "取り込める店舗名がありませんでした。")
            return

        reply = QMessageBox.question(
            self,
            "CSVインポート確認",
            f"「お気に入りの場所」形式の CSV を取り込みます。\n\n"
            f"件数: {len(preview_rows)} 件（タイトルあり）\n"
            f"・DBに無い店舗だけ追加\n"
            f"・所属ルートは未所属\n"
            f"・住所・電話・緯度経度を Google Maps から取得\n"
            f"・店舗コードを自動採番\n"
            f"・店名ゆれ／電話／住所／近接座標で重複スキップ\n\n"
            f"API呼び出しのため時間がかかることがあります。続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(
            "CSVインポート中...", "キャンセル", 0, len(preview_rows), self
        )
        progress.setWindowTitle("CSVインポート")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def _on_progress(current: int, total: int, label: str) -> bool:
            if progress.wasCanceled():
                return False
            progress.setMaximum(max(total, 1))
            progress.setValue(min(current, total))
            progress.setLabelText(f"処理中 ({current}/{total}): {label}")
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            result = import_takeout_favorites(
                self.db,
                file_path,
                fetch_info=lambda name: get_store_info_from_google(
                    name, language_code="ja"
                ),
                progress_callback=_on_progress,
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "エラー", f"CSVインポートに失敗しました:\n{e}")
            return

        progress.close()

        lines = [
            f"解析: {result.parsed} 件",
            f"追加: {len(result.added)} 件（未所属）",
            f"スキップ（重複など）: {len(result.skipped)} 件",
            f"失敗: {len(result.failed)} 件",
        ]
        if result.cancelled:
            lines.append("※途中でキャンセルされました")
        if result.added:
            lines.append("\n【追加例】")
            for row in result.added[:8]:
                code = row.store_code or "（コード未採番）"
                lines.append(f"・{row.title} → {code}")
            if len(result.added) > 8:
                lines.append(f"…他 {len(result.added) - 8} 件")
        if result.skipped:
            lines.append("\n【スキップ例】")
            for row in result.skipped[:5]:
                extra = f" → {row.matched_store}" if row.matched_store else ""
                lines.append(f"・{row.title}: {row.reason}{extra}")
            if len(result.skipped) > 5:
                lines.append(f"…他 {len(result.skipped) - 5} 件")
        if result.failed:
            lines.append("\n【失敗例】")
            for row in result.failed[:5]:
                lines.append(f"・{row.title}: {row.reason}")
            if len(result.failed) > 5:
                lines.append(f"…他 {len(result.failed) - 5} 件")

        QMessageBox.information(self, "CSVインポート完了", "\n".join(lines))
        self.load_stores(self.search_edit.text())
        self.load_routes()
        self.routes_changed.emit()
    
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
                # 店舗コードが空の場合は自動生成（チェーン名がマッピングで判別できるときのみ）
                if not data.get('store_code'):
                    store_name = data.get('store_name', '')
                    if store_name:
                        generated = self.db.get_next_store_code_from_store_name(store_name)
                        if generated:
                            data['store_code'] = generated
                tag_ids = data.pop("tag_ids", None) or []
                new_id = self.db.add_store(data)
                if new_id:
                    self.db.set_store_tag_ids(int(new_id), tag_ids)
                added_route = (data.get("affiliated_route_name") or "").strip()
                if added_route:
                    self._adjust_route_combo_store_count(added_route, 1)
                QMessageBox.information(self, "完了", "店舗を追加しました")
                self.load_stores(self.search_edit.text())
                self.routes_changed.emit()
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
                old_route = (store_data.get("affiliated_route_name") or "").strip()
                new_route = (data.get("affiliated_route_name") or "").strip()
                tag_ids = data.pop("tag_ids", None)
                self.db.update_store(store_id, data)
                if tag_ids is not None:
                    self.db.set_store_tag_ids(store_id, tag_ids)
                if old_route != new_route:
                    if old_route:
                        self._adjust_route_combo_store_count(old_route, -1)
                    if new_route:
                        self._adjust_route_combo_store_count(new_route, 1)
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
        store_name_col = STORE_LIST_BASIC_COLUMNS.index("店舗名")
        name_item = self.store_table.item(row, store_name_col)
        store_name = name_item.text().strip() if name_item else ""
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"店舗 '{store_name}' を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            row_store = self.db.get_store(store_id)
            del_route = ((row_store or {}).get("affiliated_route_name") or "").strip()
            self.db.delete_store(store_id)
            if del_route:
                self._adjust_route_combo_store_count(del_route, -1)
            QMessageBox.information(self, "完了", "店舗を削除しました")
            self.load_stores(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def manage_custom_fields(self):
        """カスタムフィールド定義の管理ダイアログを開く。店舗一覧からのボタンは非表示だが、将来メニュー等から再利用可能。"""
        from ui.custom_fields_dialog import CustomFieldsDialog
        dialog = CustomFieldsDialog(self, self.db)
        dialog.exec()
        self.load_stores(self.search_edit.text())  # カスタムフィールドが変わったので再読み込み

    def manage_store_tags(self):
        """店舗タグ管理ダイアログを開く。"""
        from .store_tags_dialog import StoreTagsDialog
        dialog = StoreTagsDialog(self, db=self.db)
        dialog.exec()
        self.load_stores(self.search_edit.text())
    
    def create_new_route(self):
        """新規ルート作成"""
        dialog = RouteManagementDialog(self, self.db, route_name=None)
        if dialog.exec() == QDialog.Accepted:
            # ルート一覧を再読み込み
            self.load_routes()
            # 店舗一覧を再読み込み
            self.load_stores(self.search_edit.text())
            self.routes_changed.emit()
    
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
            self.routes_changed.emit()

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
            self.routes_changed.emit()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ルートの削除に失敗しました:\n{str(e)}")
