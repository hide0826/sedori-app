#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像管理ウィジェット

画像ファイルの管理、JAN抽出、グルーピング、回転などの処理を行う。
"""
from __future__ import annotations

import sys
import os
import json
import re
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QMimeData, QUrl, QSettings
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog,
    QInputDialog, QMenu, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget
)
from PySide6.QtGui import QPixmap, QFont, QDrag, QDropEvent, QImageReader, QImage, QDesktopServices, QCursor

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# デスクトップ側servicesを優先して読み込む
try:
    from services.image_service import ImageService, ImageRecord, JanGroup  # python/desktop/services
    from services.ocr_service import OCRService
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.image_service import ImageService, ImageRecord, JanGroup
    from desktop.services.ocr_service import OCRService

from database.image_db import ImageDatabase

logger = logging.getLogger(__name__)


class ScanCancelledError(Exception):
    """スキャン処理がユーザーによりキャンセルされたことを示す例外"""


class CandidateSelectionDialog(QDialog):
    """OCR候補選択ダイアログ"""
    
    def __init__(self, candidates_map, parent=None):
        """
        Args:
            candidates_map: {image_path: [{"jan": str, "title": str, "score": float}, ...]}
        """
        super().__init__(parent)
        self.candidates_map = candidates_map
        self.selected_results = {}  # {image_path: jan}
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("JAN不明画像のOCR検索結果")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel("以下の画像に対してOCR検索により候補が見つかりました。\n割り当てるJANコードを選択してください。")
        layout.addWidget(info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["画像", "OCRテキスト", "候補商品", "選択"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.table)
        
        self.populate_table()
        
        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("選択した項目を適用")
        apply_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(apply_btn)
        
        layout.addLayout(btn_layout)
        
    def populate_table(self):
        self.table.setRowCount(0)
        row = 0
        
        for image_path, data in self.candidates_map.items():
            ocr_text = data.get("ocr_text", "")
            candidates = data.get("candidates", [])
            
            if not candidates:
                continue
                
            # 画像ごとに候補の数だけ行を追加するか、コンボボックスにするか
            # ここではコンボボックスを使う
            
            self.table.insertRow(row)
            
            # 画像名
            file_name = Path(image_path).name
            self.table.setItem(row, 0, QTableWidgetItem(file_name))
            self.table.item(row, 0).setToolTip(image_path)
            
            # OCRテキスト（先頭部分のみ表示）
            short_text = ocr_text[:20] + "..." if len(ocr_text) > 20 else ocr_text
            self.table.setItem(row, 1, QTableWidgetItem(short_text))
            self.table.item(row, 1).setToolTip(ocr_text)
            
            # 候補商品コンボボックス
            from PySide6.QtWidgets import QComboBox
            combo = QComboBox()
            combo.addItem("（選択しない）", None)
            
            # スコア順などでソートされている前提
            for cand in candidates:
                jan = cand["jan"]
                title = cand["title"]
                score = cand["score"]
                label = f"[{score}pt] {title} ({jan})"
                combo.addItem(label, jan)
            
            # デフォルトでトップ候補を選択
            if candidates:
                combo.setCurrentIndex(1)
                
            self.table.setCellWidget(row, 2, combo)
            
            # 適用チェックボックス
            chk = QCheckBox()
            chk.setChecked(True)
            self.table.setCellWidget(row, 3, chk)
            
            # データ保存用に行番号とパスを紐付け（行番号は変わる可能性があるので注意だが、今回は再構築しない）
            self.table.item(row, 0).setData(Qt.UserRole, image_path)
            
            row += 1
            
    def accept(self):
        # 選択結果を収集
        self.selected_results = {}
        for row in range(self.table.rowCount()):
            # チェックボックス
            chk = self.table.cellWidget(row, 3)
            if not chk.isChecked():
                continue
                
            # コンボボックス
            combo = self.table.cellWidget(row, 2)
            jan = combo.currentData()
            if not jan:
                continue
                
            # 画像パス
            image_path = self.table.item(row, 0).data(Qt.UserRole)
            self.selected_results[image_path] = jan
            
        super().accept()


class PurchaseCandidateDialog(QDialog):
    """JANグループと仕入DBを手動で紐付けるための候補選択ダイアログ"""

    def __init__(self, jan_group: JanGroup, base_dt: datetime, candidates: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.jan_group = jan_group
        self.base_dt = base_dt
        self.candidates = candidates
        self.selected_record: Optional[Dict[str, Any]] = None
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("仕入DB候補の選択")
        self.resize(900, 500)

        layout = QVBoxLayout(self)

        # JANコードの.0を削除（表示用の正規化）
        if self.jan_group.jan != "unknown":
            jan_text = str(self.jan_group.jan).strip()
            if jan_text.endswith(".0"):
                jan_text = jan_text[:-2]
        else:
            jan_text = "（JAN不明）"
        info_label = QLabel(
            f"JANグループ: {jan_text}\n"
            f"基準日時: {self.base_dt.strftime('%Y/%m/%d %H:%M:%S')} 付近の仕入データ候補を表示しています。"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["日差", "仕入れ日", "SKU", "ASIN", "JAN", "商品名", "店舗", "仕入価格"]
        )
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        layout.addWidget(self.table)

        self.populate_table()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("この仕入レコードと紐付け")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def populate_table(self):
        self.table.setRowCount(len(self.candidates))
        for row, record in enumerate(self.candidates):
            diff = record.get("_date_diff", "")
            purchase_date = str(record.get("仕入れ日") or record.get("purchase_date") or "")
            sku = str(record.get("SKU") or record.get("sku") or "")
            asin = str(record.get("ASIN") or record.get("asin") or "")
            # JANコードの.0を削除（表示用の正規化）
            jan_raw = record.get("JAN") or record.get("jan") or ""
            jan = str(jan_raw) if jan_raw else ""
            if jan:
                # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                if jan.endswith(".0"):
                    jan = jan[:-2]
            title = str(record.get("商品名") or record.get("product_name") or record.get("title") or "")
            store = str(record.get("仕入先") or record.get("store_name") or "")
            price = str(record.get("仕入れ価格") or record.get("purchase_price") or "")

            values = [diff, purchase_date, sku, asin, jan, title, store, price]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == 5 and title:
                    item.setToolTip(title)
                self.table.setItem(row, col, item)

            # 行全体に元レコードを紐付け
            self.table.item(row, 0).setData(Qt.UserRole, record)

    def on_cell_double_clicked(self, row: int, column: int):
        item = self.table.item(row, 0)
        if not item:
            return
        record = item.data(Qt.UserRole)
        if record:
            self.selected_record = record
            self.accept()

    def accept(self):
        if self.selected_record is None:
            current_row = self.table.currentRow()
            if current_row >= 0:
                item = self.table.item(current_row, 0)
                if item:
                    record = item.data(Qt.UserRole)
                    if record:
                        self.selected_record = record
        super().accept()


class JanGroupTreeWidget(QTreeWidget):
    """JANグループツリーウィジェット（ドロップ対応）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent  # ImageManagerWidgetへの参照
    
    def dragEnterEvent(self, event):
        """ドラッグエンターイベント"""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """ドラッグムーブイベント"""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event):
        """ドロップイベント"""
        if event.mimeData().hasText():
            image_path = event.mimeData().text()
            # ドロップされた位置のアイテムを取得
            item = self.itemAt(event.pos())
            if item and self.parent_widget:
                # 親ウィジェットのメソッドを呼び出し
                self.parent_widget.add_image_to_group(image_path, item)
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageListWidget(QListWidget):
    """画像リストウィジェット（ドラッグ対応）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent  # ImageManagerWidgetへの参照
    
    def startDrag(self, supportedActions):
        """ドラッグ開始時の処理"""
        items = self.selectedItems()
        if not items:
            return
        
        # 最初に選択されたアイテムの画像パスを取得
        item = items[0]
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return
        
        # MIMEデータを作成
        mime_data = QMimeData()
        mime_data.setText(image_path)
        
        # ドラッグを開始
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec_(supportedActions)


class RegistrationTableWidget(QTableWidget):
    """画像登録タブ用テーブル（ドラッグ＆ドロップ対応）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return super().startDrag(supportedActions)
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return super().startDrag(supportedActions)

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(image_path)])
        mime_data.setText(image_path)

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec_(supportedActions)


class ImageLoadThread(QThread):
    """画像読み込みスレッド（大量画像対応・並列化）"""
    progress = Signal(int, int)  # 現在の進捗、総数
    finished = Signal(list)  # 読み込み完了
    
    def __init__(self, image_paths: List[str], max_size: int = 192):
        super().__init__()
        self.image_paths = image_paths
        self.max_size = max_size
        self.results = []
        # 強制terminate()はQt内部のリソース破壊につながるため、
        # フラグで安全にキャンセルできるようにする
        self._cancelled = False
    
    def cancel(self):
        """スレッド処理を安全にキャンセルするためのフラグを立てる"""
        self._cancelled = True
    
    def run(self):
        """画像を読み込んでサムネイルを生成（並列処理）"""
        total = len(self.image_paths)
        sorted_results = [None] * total
        completed_count = 0
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # 各タスクにインデックスを紐付ける
            futures = {
                executor.submit(self._load_image, path): i 
                for i, path in enumerate(self.image_paths)
            }
            
            for future in concurrent.futures.as_completed(futures):
                # キャンセル要求が来ていたら残りは無視して終了
                if self._cancelled:
                    break
                
                index = futures[future]
                try:
                    img = future.result()
                    if img and not img.isNull():
                        sorted_results[index] = (self.image_paths[index], img)
                except Exception:
                    pass
                
                completed_count += 1
                self.progress.emit(completed_count, total)
        
        # Noneを除去
        self.results = [r for r in sorted_results if r is not None]
        self.finished.emit(self.results)

    def _load_image(self, path: str) -> Optional[QImage]:
        """QImageReaderで縮小読み込みし、QImageを返す（スレッドセーフ）"""
        if self._cancelled:
            return None
        try:
            reader = QImageReader(path)
            # 自動回転に対応
            reader.setAutoTransform(True)
            
            if self.max_size:
                original_size = reader.size()
                if original_size.isValid():
                    max_dim = max(original_size.width(), original_size.height())
                    if max_dim > self.max_size:
                        scale = self.max_size / float(max_dim)
                        new_width = max(1, int(original_size.width() * scale))
                        new_height = max(1, int(original_size.height() * scale))
                        reader.setScaledSize(QSize(new_width, new_height))
            
            image = reader.read()
            return image
        except Exception:
            return None


class ImageManagerWidget(QWidget):
    """画像管理ウィジェット"""
    
    # URL画像プレビュー用シグナル（バックグラウンド→メインスレッド）
    _preview_image_ready = Signal(str, bytes)  # (token, image_data)
    _preview_image_error = Signal(str, str)    # (token, error_message)
    
    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.image_service = ImageService()
        self.ocr_service = OCRService()
        self.image_db = ImageDatabase()
        self.product_widget = None  # ProductWidgetへの参照
        
        # データ
        self.current_directory = ""
        self.image_records: List[ImageRecord] = []
        self.jan_groups: List[JanGroup] = []
        self.selected_group: Optional[JanGroup] = None
        self.selected_image_path: Optional[str] = None
        self._scan_cancelled = False
        self._jan_title_cache: Dict[str, str] = {}
        self.registration_records: List[Dict[str, Any]] = []
        # 画像登録タブ用の簡易スナップショット保存先
        base_dir = Path(__file__).parent.parent
        self.registration_snapshot_path = base_dir / "data" / "image_registration_snapshot.json"
        
        # 設定ファイルのパス
        self.config_path = Path(__file__).parent.parent.parent.parent / "config" / "inventory_settings.json"
        
        # スレッド
        self.load_thread: Optional[ImageLoadThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        
        self.setup_ui()
        self.load_last_directory()

        # テーブルの列幅を復元
        # 列構成を変更したのでキーを更新（古い保存状態を無効化）
        restore_table_header_state(self.registration_table, "ImageManagerWidget/RegistrationTableState/v3")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.registration_table, "ImageManagerWidget/RegistrationTableState/v3")

    
    def set_product_widget(self, product_widget):
        """ProductWidgetへの参照を設定"""
        self.product_widget = product_widget
    
    def setup_ui(self):
        """UIのセットアップ"""
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.tab_widget = QTabWidget()
        root_layout.addWidget(self.tab_widget)

        self.main_tab = QWidget()
        layout = QVBoxLayout(self.main_tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 上部：フォルダ選択エリア（最小サイズ）
        folder_group = QGroupBox("フォルダ選択")
        folder_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)  # 高さを最小限に
        folder_layout = QHBoxLayout(folder_group)
        folder_layout.setSpacing(5)
        folder_layout.setContentsMargins(5, 5, 5, 5)  # マージンを小さく
        
        folder_label = QLabel("フォルダ:")
        self.folder_path_label = QLabel("（未選択）")
        self.folder_path_label.setMinimumHeight(20)  # 高さを小さく
        self.folder_path_label.setMaximumHeight(20)  # 最大高さも制限
        self.folder_path_label.setStyleSheet("border: 1px solid gray; padding: 2px;")  # パディングを小さく
        self.folder_path_label.setWordWrap(False)  # 折り返しを無効化（1行に）
        
        self.select_folder_btn = QPushButton("フォルダ選択")
        self.select_folder_btn.clicked.connect(self.select_directory)
        self.scan_btn = QPushButton("スキャン実行")
        self.scan_btn.clicked.connect(self.scan_directory)
        self.scan_btn.setEnabled(False)

        self.scan_unknown_btn = QPushButton("JAN不明検索")
        self.scan_unknown_btn.clicked.connect(self.scan_unknown_jan_images)
        self.scan_unknown_btn.setEnabled(False)
        
        self.clear_images_btn = QPushButton("画像クリア")
        self.clear_images_btn.clicked.connect(self.clear_jan_groups)
        self.clear_images_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_path_label, stretch=1)
        folder_layout.addWidget(self.select_folder_btn)
        folder_layout.addWidget(self.scan_btn)
        folder_layout.addWidget(self.scan_unknown_btn)
        folder_layout.addWidget(self.clear_images_btn)
        
        layout.addWidget(folder_group)
        
        # メインエリア：三分割レイアウト
        splitter = QSplitter(Qt.Horizontal)
        
        # 左：JANグループツリー
        left_group = QGroupBox("JANグループ")
        left_layout = QVBoxLayout(left_group)
        
        # JANグループ追加ボタン
        add_group_btn = QPushButton("JANグループ追加")
        add_group_btn.clicked.connect(self.add_jan_group_manually)
        left_layout.addWidget(add_group_btn)
        
        self.tree_widget = JanGroupTreeWidget(self)
        self.tree_widget.setHeaderLabel("JANグループ")
        self.tree_widget.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.tree_widget.setAcceptDrops(True)  # ドロップを受け入れる
        self.tree_widget.setDragDropMode(QTreeWidget.DropOnly)  # ドロップのみ許可
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.on_tree_context_menu)
        left_layout.addWidget(self.tree_widget)

        # グループ操作ボタン
        group_action_layout = QHBoxLayout()
        self.rename_btn = QPushButton("全画像リネーム")
        self.rename_btn.clicked.connect(self.rename_all_images)
        self.confirm_btn = QPushButton("確定処理")
        self.confirm_btn.clicked.connect(self.confirm_image_links)
        group_action_layout.addWidget(self.rename_btn)
        group_action_layout.addWidget(self.confirm_btn)
        left_layout.addLayout(group_action_layout)

        splitter.addWidget(left_group)
        
        # 中央：画像リスト
        center_group = QGroupBox("画像一覧（撮影時間順）")
        center_layout = QVBoxLayout(center_group)
        self.image_list = ImageListWidget(self)
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setIconSize(QSize(192, 192))
        self.image_list.setSpacing(10)
        self.image_list.itemClicked.connect(self.on_image_clicked)
        self.image_list.setDragDropMode(QListWidget.DragOnly)  # ドラッグのみ許可
        self.image_list.setDefaultDropAction(Qt.MoveAction)  # ドラッグ時の動作
        self.image_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self.on_image_list_context_menu)
        center_layout.addWidget(self.image_list)
        splitter.addWidget(center_group)
        
        # 右：詳細パネル
        right_group = QGroupBox("詳細情報")
        right_layout = QVBoxLayout(right_group)
        
        # プレビュー
        preview_label = QLabel("プレビュー")
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(256, 256)
        self.preview_label.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setText("画像を選択してください")
        self.preview_label.setScaledContents(True)
        
        # 詳細情報フォーム
        detail_form = QFormLayout()
        
        self.jan_edit = QLineEdit()
        self.jan_edit.setPlaceholderText("JANコード（8桁または13桁）")
        detail_form.addRow("JANコード:", self.jan_edit)
        
        self.capture_time_label = QLabel("-")
        detail_form.addRow("撮影日時:", self.capture_time_label)
        
        self.file_name_label = QLabel("-")
        detail_form.addRow("ファイル名:", self.file_name_label)
        
        self.file_size_label = QLabel("-")
        detail_form.addRow("サイズ:", self.file_size_label)
        
        # 操作ボタン
        button_layout = QHBoxLayout()
        self.rotate_left_btn = QPushButton("左回転（-90°）")
        self.rotate_left_btn.clicked.connect(lambda: self.rotate_image(-90))
        self.rotate_right_btn = QPushButton("右回転（+90°）")
        self.rotate_right_btn.clicked.connect(lambda: self.rotate_image(90))
        
        # バーコード読み取りボタン
        self.read_barcode_btn = QPushButton("バーコード読み取り")
        self.read_barcode_btn.clicked.connect(self.read_barcode_from_image)
        
        self.save_jan_btn = QPushButton("JAN保存")
        self.save_jan_btn.clicked.connect(self.save_jan)
        
        button_layout.addWidget(self.rotate_left_btn)
        button_layout.addWidget(self.rotate_right_btn)
        button_layout.addWidget(self.read_barcode_btn)
        button_layout.addWidget(self.save_jan_btn)
        
        right_layout.addWidget(preview_label)
        right_layout.addWidget(self.preview_label)
        right_layout.addLayout(detail_form)
        right_layout.addLayout(button_layout)
        right_layout.addStretch()
        
        splitter.addWidget(right_group)
        
        # 分割の比率を設定（左:中央:右 = 1:2:1）
        splitter.setSizes([250, 500, 250])
        
        layout.addWidget(splitter)

        self.tab_widget.addTab(self.main_tab, "画像管理")
        self.setup_registration_tab()
        self.tab_widget.addTab(self.registration_tab, "画像登録")
        
        # 初期状態でボタンを無効化
        self.rotate_left_btn.setEnabled(False)
        self.rotate_right_btn.setEnabled(False)
        self.read_barcode_btn.setEnabled(False)
        self.save_jan_btn.setEnabled(False)
        self.rename_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)
        
        # バーコードリーダーの利用可能性を確認
        if not self.image_service.is_barcode_reader_available():
            self.read_barcode_btn.setToolTip(
                "バーコードリーダーを使用するには、pyzbarとzbarライブラリが必要です。\n"
                "pip install pyzbar\n"
                "Windows: zbar-w64をダウンロードしてインストール\n"
                "Linux: sudo apt-get install libzbar0\n"
                "macOS: brew install zbar"
            )
    
    def load_last_directory(self):
        """最後に開いたフォルダパスを読み込む"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'image_manager_last_directory' in config:
                        last_dir = config['image_manager_last_directory']
                        if os.path.exists(last_dir) and os.path.isdir(last_dir):
                            self.current_directory = last_dir
                            self.folder_path_label.setText(last_dir)
                            self.scan_btn.setEnabled(True)
                            self.scan_unknown_btn.setEnabled(True)
        except Exception as e:
            print(f"Failed to load last directory: {e}")
    
    def save_last_directory(self):
        """最後に開いたフォルダパスを保存"""
        try:
            # 設定ファイルを読み込む（存在しない場合は新規作成）
            config = {}
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 最後に開いたフォルダパスを保存
            config['image_manager_last_directory'] = self.current_directory
            
            # 設定ファイルを保存
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save last directory: {e}")
    
    def select_directory(self):
        """フォルダ選択ダイアログを表示"""
        last_dir = self.current_directory if self.current_directory else str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "画像フォルダを選択", last_dir)
        
        if directory:
            self.current_directory = directory
            self.folder_path_label.setText(directory)
            self.scan_btn.setEnabled(True)
            self.scan_unknown_btn.setEnabled(True)
            self.save_last_directory()
    
    def scan_directory(self):
        """ディレクトリをスキャンして画像を取得"""
        if not self.current_directory:
            QMessageBox.warning(self, "エラー", "フォルダを選択してください。")
            return
        
        self._scan_cancelled = False
        
        try:
            # プログレスダイアログを表示（％表示対応）
            self.progress_dialog = QProgressDialog("画像をスキャン中...", "キャンセル", 0, 1, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False)
            self.progress_dialog.setValue(0)
            self.progress_dialog.show()
            
            def handle_cancel():
                self._scan_cancelled = True
            
            self.progress_dialog.canceled.connect(handle_cancel)
            
            def progress_callback(current: int, total: int):
                if self._scan_cancelled:
                    raise ScanCancelledError()
                
                if not self.progress_dialog:
                    return
                
                if total <= 0:
                    self.progress_dialog.setMaximum(1)
                    self.progress_dialog.setValue(1)
                    self.progress_dialog.setLabelText("画像をスキャン中... 対象画像が見つかりません")
                else:
                    if self.progress_dialog.maximum() != total:
                        self.progress_dialog.setMaximum(total)
                    self.progress_dialog.setValue(current)
                    percent = (current / total) * 100 if total else 0
                    self.progress_dialog.setLabelText(
                        f"画像をスキャン中... {current}/{total}枚（{percent:.1f}%）"
                    )
                QApplication.processEvents()
            
            # スキャン実行（高速化のためEXIF・画像サイズ・バーコード読み取りをスキップ）
            # DBキャッシュを構築（スマートスキャン）
            db_records = self.image_db.list_all()
            file_cache = {}
            for r in db_records:
                path = r['file_path']
                # mtimeはDBにないので含めない（無条件ヒットさせる）
                # ただしファイルが存在しない場合はキャッシュに含めない方が安全だが、
                # Service側でファイル存在チェックをしているのでここでは単純に構築する
                rec = ImageRecord(
                    path=path,
                    capture_dt=datetime.fromisoformat(r['capture_time']) if r['capture_time'] else None,
                    jan_candidate=r['jan'],
                    width=0,  # DBにないので0（表示時にロードされる）
                    height=0
                )
                file_cache[path] = {"record": rec}

            self.image_records = self.image_service.scan_directory(
                self.current_directory, 
                skip_barcode_reading=False,  # JANを自動判別
                skip_exif=False,             # EXIF撮影日時を取得
                skip_image_size=False,       # 画像サイズも取得
                progress_callback=progress_callback,
                file_cache=file_cache        # キャッシュを渡す
            )
            self._jan_title_cache = {}
            
            # DBに保存済みのJANがある場合は反映（過去の割当てを復元）
            enriched_records: List[ImageRecord] = []
            for record in self.image_records:
                db_record = self.image_db.get_by_file_path(record.path)
                jan_from_db = db_record.get("jan") if db_record else None
                if jan_from_db:
                    enriched_records.append(ImageRecord(
                        path=record.path,
                        capture_dt=record.capture_dt,
                        jan_candidate=jan_from_db,
                        width=record.width,
                        height=record.height
                    ))
                else:
                    enriched_records.append(record)
            self.image_records = enriched_records

            # タイムスタンプに基づく自動紐付け（JAN画像から3分以内の画像を自動追加）
            time_window = 3 * 60  # 3分
            current_jan = None
            current_jan_time = None
            
            auto_linked_records: List[ImageRecord] = []
            
            for record in self.image_records:
                # JANコードを持っている画像（数字のみ）
                if record.jan_candidate and record.jan_candidate.isdigit():
                    current_jan = record.jan_candidate
                    current_jan_time = record.capture_dt
                    auto_linked_records.append(record)
                
                # JANコードがない画像
                elif current_jan and current_jan_time and record.capture_dt:
                    time_diff = (record.capture_dt - current_jan_time).total_seconds()
                    # 0 < diff <= 3分
                    if 0 < time_diff <= time_window:
                        # 自動紐付け
                        new_record = ImageRecord(
                            path=record.path,
                            capture_dt=record.capture_dt,
                            jan_candidate=current_jan,
                            width=record.width,
                            height=record.height
                        )
                        auto_linked_records.append(new_record)
                    else:
                        # 時間外なら紐付けない
                        auto_linked_records.append(record)
                        # 時間外になったらカレントJANの効果を切るべきか？
                        # 要望は「JAN画像の後3分以内」なので、3分経過したら紐付け終了で良いはず。
                        if time_diff > time_window:
                            current_jan = None
                            current_jan_time = None
                else:
                    auto_linked_records.append(record)
            
            self.image_records = auto_linked_records
            
            self._close_progress_dialog()
            
            if not self.image_records:
                QMessageBox.information(self, "結果", "画像ファイルが見つかりませんでした。")
                return
            
            # JANでグルーピング（JANコードなしも含む）
            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            
            # DBに保存
            for group in self.jan_groups:
                for i, record in enumerate(group.images):
                    self.image_db.upsert({
                        "file_path": record.path,
                        "jan": group.jan if group.jan != "unknown" else None,
                        "group_index": i,
                        "capture_time": record.capture_dt.isoformat() if record.capture_dt else None,
                        "rotation": 0
                    })
            
            # UI更新
            self.update_tree_widget()
            
            # 全画像を一覧表示（遅延読み込み：スキャン完了後に非同期で実行）
            # 画像読み込みは重いので、まずスキャン完了を通知してから実行
            QMessageBox.information(
                self, "スキャン完了",
                f"{len(self.image_records)}件の画像をスキャンしました。\n"
                f"JANグループ数: {len(self.jan_groups)}"
            )
            
            # スキャン完了後、バックグラウンドで画像一覧を更新（ユーザーが待たない）
            self.update_image_list(self.image_records)
        except ScanCancelledError:
            QMessageBox.information(self, "キャンセル", "画像スキャンを中止しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"スキャン中にエラーが発生しました:\n{str(e)}")
        finally:
            self._close_progress_dialog()
    
    def update_tree_widget(self):
        """ツリービジェットを更新"""
        self.tree_widget.clear()
        
        for group in self.jan_groups:
            # 親ノード（JANグループ）
            if group.jan != "unknown":
                # JANコードの.0を削除（表示用の正規化）
                jan_text = str(group.jan).strip()
                if jan_text.endswith(".0"):
                    jan_text = jan_text[:-2]
            else:
                jan_text = "（JAN不明）"
            title = self._get_product_title_by_jan(group.jan) if group.jan != "unknown" else ""
            title_text = f" - {title}" if title else ""
            parent_item = QTreeWidgetItem([f"{jan_text}{title_text} ({len(group.images)}枚)"])
            parent_item.setData(0, Qt.UserRole, group)
            self.tree_widget.addTopLevelItem(parent_item)
            
            # 子ノード（各画像）
            for record in group.images:
                file_name = Path(record.path).name
                capture_text = record.capture_dt.strftime("%Y/%m/%d %H:%M:%S") if record.capture_dt else "（日時不明）"
                child_item = QTreeWidgetItem([f"{file_name} - {capture_text}"])
                child_item.setData(0, Qt.UserRole, record.path)
                parent_item.addChild(child_item)
        
        self.tree_widget.expandAll()
        has_valid_groups = any(g.jan != "unknown" for g in self.jan_groups)
        self.rename_btn.setEnabled(has_valid_groups)
    
    def clear_jan_groups(self):
        """JANグループエリアに展開されている画像をクリア"""
        if not self.jan_groups:
            QMessageBox.information(self, "情報", "クリアする画像がありません。")
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "確認",
            f"JANグループエリアに展開されている画像（{len(self.jan_groups)}グループ）をクリアしますか？\n"
            "この操作は画像ファイル自体を削除するものではありません。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # JANグループツリーをクリア
            self.tree_widget.clear()
            
            # JANグループデータをクリア
            self.jan_groups = []
            self.selected_group = None
            
            # 画像一覧をクリア
            self.image_list.clear()
            
            # 詳細パネルをクリア
            self.preview_label.clear()
            self.preview_label.setText("画像を選択してください")
            self.jan_edit.clear()
            self.capture_time_label.setText("-")
            self.file_name_label.setText("-")
            self.file_size_label.setText("-")
            self.selected_image_path = None
            
            # ボタンの状態を更新
            self.rename_btn.setEnabled(False)
            self.confirm_btn.setEnabled(False)
            
            QMessageBox.information(self, "完了", "JANグループエリアの画像をクリアしました。")
    
    def on_tree_selection_changed(self):
        """ツリー選択変更時の処理"""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        
        item = selected_items[0]
        group = item.data(0, Qt.UserRole)
        
        is_valid_group = isinstance(group, JanGroup) and group.jan != "unknown"
        self.confirm_btn.setEnabled(is_valid_group)

        if isinstance(group, JanGroup):
            # JANグループが選択された（該当グループの画像のみ表示）
            self.selected_group = group
            if group.jan != "unknown":
                # JANコードがあるグループの場合、そのグループの画像のみ表示
                # 画像読み込みダイアログは不要なため、プログレス表示なしで更新
                self.update_image_list(group.images, show_progress=False)
            else:
                # JAN不明グループの場合は全画像を表示
                self.update_image_list(self.image_records, show_progress=False)
        else:
            # 個別の画像が選択された
            image_path = item.data(0, Qt.UserRole)
            if image_path:
                # 親グループを探す
                parent = item.parent()
                if parent:
                    group = parent.data(0, Qt.UserRole)
                    if isinstance(group, JanGroup):
                        self.selected_group = group
                        self.update_image_list(group.images)
                        # 選択された画像をハイライト
                        for i in range(self.image_list.count()):
                            list_item = self.image_list.item(i)
                            if list_item.data(Qt.UserRole) == image_path:
                                self.image_list.setCurrentItem(list_item)
                                self.on_image_clicked(list_item)
                                break
    
    def update_image_list(self, records: List[ImageRecord], show_progress: bool = False):
        """画像リストを更新
        
        Args:
            records: 画像レコードのリスト
            show_progress: Trueの場合、プログレスダイアログを表示（デフォルト: False）
        """
        self.image_list.clear()
        
        if not records:
            return
        
        # 画像読み込みをスレッドで実行
        image_paths = [r.path for r in records]
        
        # 既存のスレッドがあれば終了を待つ
        if self.load_thread:
            if self.load_thread.isRunning():
                # 強制terminate()は不安定要因になるため、キャンセルフラグ＋waitで終了させる
                try:
                    if hasattr(self.load_thread, "cancel"):
                        self.load_thread.cancel()
                    self.load_thread.wait(3000)  # 最大3秒待つ
                except Exception as e:
                    logger.debug(f"Failed to gracefully stop ImageLoadThread: {e}")
            self.load_thread = None
        
        # プログレスダイアログは必要に応じて表示（通常は非表示で高速化）
        if show_progress:
            if self.progress_dialog:
                self.progress_dialog.close()
            self.progress_dialog = QProgressDialog(
                "画像を読み込み中...", "キャンセル", 0, len(image_paths), self
            )
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.show()
        else:
            # プログレスダイアログなしでバックグラウンド読み込み
            self.progress_dialog = None
        
        self.load_thread = ImageLoadThread(image_paths, max_size=192)
        if show_progress:
            self.load_thread.progress.connect(self.on_load_progress)
        self.load_thread.finished.connect(self.on_load_finished)
        self.load_thread.start()
    
    def on_load_progress(self, current: int, total: int):
        """画像読み込み進捗更新"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.setValue(current)
    
    def on_load_finished(self, results: List[tuple]):
        """画像読み込み完了"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # 結果を画像一覧に追加
        for path, image in results:
            item = QListWidgetItem(Path(path).name)
            pixmap = QPixmap.fromImage(image)
            item.setIcon(pixmap)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.image_list.addItem(item)
    
    def on_image_clicked(self, item: QListWidgetItem):
        """画像クリック時の処理"""
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return
        
        self.selected_image_path = image_path
        
        # プレビューを更新
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            # プレビューサイズに調整
            preview_size = self.preview_label.size()
            scaled_pixmap = pixmap.scaled(
                preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
        else:
            self.preview_label.setText("画像を読み込めませんでした")
        
        # 詳細情報を更新
        record = next((r for r in self.image_records if r.path == image_path), None)
        if record:
            # JANコード
            jan = record.jan_candidate or ""
            if self.selected_group:
                jan = self.selected_group.jan if self.selected_group.jan != "unknown" else ""
            self.jan_edit.setText(jan)
            
            # 撮影日時
            if record.capture_dt:
                self.capture_time_label.setText(record.capture_dt.strftime("%Y/%m/%d %H:%M:%S"))
            else:
                self.capture_time_label.setText("（不明）")
            
            # ファイル名
            self.file_name_label.setText(Path(image_path).name)
            
            # サイズ
            self.file_size_label.setText(f"{record.width} × {record.height} px")
        else:
            # DBから取得を試みる
            db_record = self.image_db.get_by_file_path(image_path)
            if db_record:
                self.jan_edit.setText(db_record.get("jan", "") or "")
                self.capture_time_label.setText(db_record.get("capture_time", "（不明）"))
                self.file_name_label.setText(Path(image_path).name)
                self.file_size_label.setText("-")
        
        # ボタンを有効化
        self.rotate_left_btn.setEnabled(True)
        self.rotate_right_btn.setEnabled(True)
        self.read_barcode_btn.setEnabled(self.image_service.is_barcode_reader_available())
        self.save_jan_btn.setEnabled(True)
    
    def rotate_image(self, degrees: int):
        """画像を回転"""
        if not self.selected_image_path:
            return
        
        try:
            success = self.image_service.rotate_image(self.selected_image_path, degrees)
            if success:
                # DBを更新
                db_record = self.image_db.get_by_file_path(self.selected_image_path)
                if db_record:
                    current_rotation = db_record.get("rotation", 0)
                    new_rotation = (current_rotation + degrees) % 360
                    self.image_db.update_rotation(self.selected_image_path, new_rotation)
                
                # プレビューとリストを更新
                self.on_image_clicked(self.image_list.currentItem())
                QMessageBox.information(self, "完了", f"画像を{degrees}度回転しました。")
            else:
                QMessageBox.warning(self, "エラー", "画像の回転に失敗しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"回転中にエラーが発生しました:\n{str(e)}")
    
    def read_barcode_from_image(self):
        """画像からバーコードを読み取る"""
        if not self.selected_image_path:
            return
        
        if not self.image_service.is_barcode_reader_available():
            QMessageBox.warning(
                self,
                "バーコードリーダー未インストール",
                "バーコードリーダーを使用するには、以下のいずれかをインストールしてください:\n\n"
                "【推奨】pyzxing（ZXingベース）:\n"
                "1. Java JRE 8以上をインストール\n"
                "   https://www.java.com/ja/download/\n"
                "2. pip install pyzxing\n\n"
                "【代替】pyzbar（ZBarベース）:\n"
                "1. pip install pyzbar\n"
                "2. zbarライブラリをインストール:\n"
                "   - Windows: zbar-w64をダウンロードしてインストール\n"
                "   - Linux: sudo apt-get install libzbar0\n"
                "   - macOS: brew install zbar"
            )
            return
        
        try:
            # プログレスダイアログを表示
            QMessageBox.information(self, "読み取り中", "バーコードを読み取っています...")
            
            # バーコードを読み取る
            jan = self.image_service.read_barcode_from_image(self.selected_image_path)
            
            if jan:
                # JANコードを入力欄に設定
                self.jan_edit.setText(jan)
                QMessageBox.information(self, "読み取り完了", f"JANコードを読み取りました: {jan}")
            else:
                QMessageBox.information(self, "読み取り失敗", "画像からバーコードを読み取れませんでした。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"バーコード読み取り中にエラーが発生しました:\n{str(e)}")
    
    def save_jan(self):
        """JANコードを保存し、4分以内に撮影された画像を同じグループにまとめる"""
        if not self.selected_image_path:
            return
        
        jan = self.jan_edit.text().strip()
        
        # JANコードの検証（8桁または13桁の数字）
        if jan and not re.match(r'^\d{8}$|^\d{13}$', jan):
            QMessageBox.warning(self, "エラー", "JANコードは8桁または13桁の数字である必要があります。")
            return
        
        try:
            # 選択された画像のレコードを取得
            selected_record = next((r for r in self.image_records if r.path == self.selected_image_path), None)
            if not selected_record:
                QMessageBox.warning(self, "エラー", "画像レコードが見つかりませんでした。")
                return
            
            # 選択された画像のEXIFから撮影日時を取得（正確な撮影日時を使用）
            selected_capture_dt = self.image_service.get_exif_datetime(self.selected_image_path)
            if not selected_capture_dt:
                # EXIFが取得できない場合は、既存の撮影日時を使用（フォールバック）
                selected_capture_dt = selected_record.capture_dt
                if not selected_capture_dt:
                    QMessageBox.warning(self, "エラー", "撮影日時が取得できませんでした。")
                    return
            
            # DBを更新
            self.image_db.update_jan(self.selected_image_path, jan if jan else None)
            
            # 選択された画像のJANコードを更新（EXIFから取得した撮影日時を使用）
            selected_record = ImageRecord(
                path=selected_record.path,
                capture_dt=selected_capture_dt,
                jan_candidate=jan,
                width=selected_record.width,
                height=selected_record.height
            )
            
            # JAN画像の撮影時間の後3分以内に撮影された画像を検索して同じJANコードを付与
            time_window = 3 * 60  # 3分 = 180秒
            selected_time = selected_capture_dt
            
            updated_count = 0
            updated_records = []
            for record in self.image_records:
                if record.path == self.selected_image_path:
                    # 選択された画像を更新
                    updated_records.append(selected_record)
                    continue
                
                # 撮影日時がJAN画像の後3分以内の画像を同じJANグループに追加（前は含めない）
                # 各画像のEXIFから撮影日時を取得（正確な撮影日時を使用）
                record_capture_dt = self.image_service.get_exif_datetime(record.path)
                if not record_capture_dt:
                    # EXIFが取得できない場合は、既存の撮影日時を使用（フォールバック）
                    record_capture_dt = record.capture_dt
                
                if record_capture_dt:
                    time_diff = (record_capture_dt - selected_time).total_seconds()
                    if 0 < time_diff <= time_window:
                        db_record = self.image_db.get_by_file_path(record.path)
                        assigned_jan = db_record.get("jan") if db_record else None
                        if assigned_jan:
                            updated_records.append(record)
                            continue
                        # この画像も同じJANコードを付与（EXIFから取得した撮影日時を使用）
                        updated_record = ImageRecord(
                            path=record.path,
                            capture_dt=record_capture_dt,  # EXIFから取得した撮影日時を使用
                            jan_candidate=jan,
                            width=record.width,
                            height=record.height
                        )
                        updated_records.append(updated_record)
                        # DBも更新
                        self.image_db.update_jan(record.path, jan)
                        updated_count += 1
                    else:
                        updated_records.append(record)
                else:
                    updated_records.append(record)
            
            # image_recordsを更新（撮影日時順にソート）
            self.image_records = sorted(
                updated_records, 
                key=lambda r: r.capture_dt if r.capture_dt else datetime.min
            )
            
            # JANグループを再構築
            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            self._jan_title_cache.pop(jan, None)
            
            # UIを更新
            self.update_tree_widget()
            
            # JANコードでSKU候補を検索して提示
            sku_candidates = []
            if jan and self.product_widget:
                sku_candidates = self._search_sku_candidates_by_jan(jan)
            
            # メッセージ表示用のベース文言を組み立て
            message = f"JANコードを保存しました。\n"
            if updated_count > 0:
                message += f"JAN画像の後3分以内に撮影された{updated_count}件の画像を同じグループに追加しました。\n"
            
            if sku_candidates:
                message += f"\n仕入DBから{len(sku_candidates)}件のSKU候補が見つかりました:\n"
                for i, candidate in enumerate(sku_candidates[:5], 1):  # 最大5件表示
                    sku = candidate.get("SKU") or candidate.get("sku") or "（SKUなし）"
                    product_name = candidate.get("商品名") or candidate.get("product_name") or "（商品名なし）"
                    message += f"{i}. {sku} - {product_name}\n"
                if len(sku_candidates) > 5:
                    message += f"... 他{len(sku_candidates) - 5}件"

            QMessageBox.information(self, "完了", message)

            # SKU候補が複数ある場合は、ユーザーにどの仕入レコードと紐付けるか選択してもらう
            if jan and sku_candidates and self.product_widget:
                # 現在のJANグループを特定
                current_group = None
                for group in self.jan_groups:
                    if group.jan == jan:
                        # 選択中の画像を含むグループを優先
                        if any(img.path == self.selected_image_path for img in group.images):
                            current_group = group
                            break
                        if current_group is None:
                            current_group = group

                if current_group and current_group.images:
                    # 選択画像の撮影日時を基準日時として使用
                    base_dt = selected_capture_dt

                    # SKU候補選択ダイアログを表示
                    dialog = PurchaseCandidateDialog(current_group, base_dt, sku_candidates, parent=self)
                    if dialog.exec_() == QDialog.Accepted and dialog.selected_record:
                        selected_record = dialog.selected_record
                        target_sku = str(
                            selected_record.get("SKU") or selected_record.get("sku") or ""
                        ).strip()

                        if target_sku:
                            try:
                                all_records = self.product_widget.get_all_purchase_records()
                                image_paths = [img.path for img in current_group.images]
                                success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                                    jan,
                                    image_paths,
                                    all_records,
                                    skip_existing=True,
                                    target_sku=target_sku,
                                )
                                if success and added_count > 0 and record_snapshot:
                                    # 画像登録タブ用の一覧に1件追加
                                    self.add_registration_entry(record_snapshot)
                            except Exception as e:
                                QMessageBox.critical(
                                    self,
                                    "エラー",
                                    f"仕入DBへの画像紐付け中にエラーが発生しました:\n{str(e)}",
                                )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存中にエラーが発生しました:\n{str(e)}")
    
    def _search_sku_candidates_by_jan(self, jan: str) -> List[Dict[str, Any]]:
        """仕入DBからJANコードでSKU候補を検索"""
        if not self.product_widget or not jan:
            return []
        
        try:
            # purchase_all_recordsからJANコードで検索
            candidates = []
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            
            for record in purchase_records:
                record_jan = str(record.get("JAN") or record.get("jan") or "").strip()
                if record_jan.upper() == jan.upper():
                    candidates.append(record)
            
            return candidates
        except Exception as e:
            logger.warning(f"SKU候補検索エラー: {e}")
            return []
    
    def _get_product_title_by_jan(self, jan: str) -> str:
        """JANコードに紐づく候補商品タイトルを取得"""
        if not jan or jan == "unknown":
            return ""
        
        if jan in self._jan_title_cache:
            return self._jan_title_cache[jan]
        
        title = ""
        try:
            if self.product_widget:
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                for record in purchase_records:
                    record_jan = str(record.get("JAN") or record.get("jan") or "").strip()
                    if record_jan.upper() == jan.upper():
                        title = (
                            record.get("商品名") or
                            record.get("product_name") or
                            record.get("title") or
                            ""
                        )
                        if title:
                            break
        except Exception as e:
            logger.warning(f"商品タイトル取得エラー: {e}")
            title = ""
        
        self._jan_title_cache[jan] = title
        return title
    
    def add_jan_group_manually(self):
        """JANグループを手動で追加"""
        jan, ok = QInputDialog.getText(
            self, 
            "JANグループ追加", 
            "JANコードを入力してください（8桁または13桁）:"
        )
        
        if not ok or not jan:
            return
        
        jan = jan.strip()
        
        # JANコードの検証
        if not re.match(r'^\d{8}$|^\d{13}$', jan):
            QMessageBox.warning(self, "エラー", "JANコードは8桁または13桁の数字である必要があります。")
            return
        
        # 新しいJANグループを作成（画像なし）
        new_group = JanGroup(jan=jan, images=[])
        
        # 既存のグループに同じJANコードがあるか確認
        existing_group = next((g for g in self.jan_groups if g.jan == jan), None)
        if existing_group:
            QMessageBox.information(self, "情報", f"JANコード {jan} のグループは既に存在します。")
            return
        
        # グループを追加
        self.jan_groups.append(new_group)
        self._jan_title_cache.pop(jan, None)
        
        # UIを更新
        self.update_tree_widget()
        
        QMessageBox.information(self, "完了", f"JANグループ {jan} を追加しました。")
    
    def add_image_to_group(self, image_path: str, target_item: QTreeWidgetItem):
        """画像をJANグループに追加（ドラッグアンドドロップ時）"""
        if not image_path or not target_item:
            return
        
        # 画像レコードを取得
        image_record = next((r for r in self.image_records if r.path == image_path), None)
        if not image_record:
            QMessageBox.warning(self, "エラー", "画像レコードが見つかりませんでした。")
            return
        
        # ターゲットアイテムからJANグループを取得
        group = target_item.data(0, Qt.UserRole)
        
        if isinstance(group, JanGroup):
            # JANグループが選択された
            jan = group.jan
        else:
            # 子ノード（個別画像）が選択された場合、親グループを取得
            parent = target_item.parent()
            if parent:
                group = parent.data(0, Qt.UserRole)
                if isinstance(group, JanGroup):
                    jan = group.jan
                else:
                    QMessageBox.warning(self, "エラー", "JANグループが見つかりませんでした。")
                    return
            else:
                QMessageBox.warning(self, "エラー", "JANグループが見つかりませんでした。")
                return
        
        if jan == "unknown":
            QMessageBox.warning(self, "エラー", "JAN不明グループには画像を追加できません。")
            return
        
        # 画像のJANコードを更新
        if self.assign_image_to_jan(image_path, jan):
            QMessageBox.information(self, "完了", f"画像をJANグループ {jan} に追加しました。")
    
    def assign_image_to_jan(self, image_path: str, jan: str, capture_dt: Optional[datetime] = None, show_message: bool = False) -> bool:
        """画像に指定JANを割り当て"""
        record = next((r for r in self.image_records if r.path == image_path), None)
        if not record:
            if show_message:
                QMessageBox.warning(self, "エラー", "画像レコードが見つかりませんでした。")
            return False
        
        updated_record = ImageRecord(
            path=record.path,
            capture_dt=capture_dt or record.capture_dt,
            jan_candidate=jan,
            width=record.width,
            height=record.height
        )
        
        for i, r in enumerate(self.image_records):
            if r.path == image_path:
                self.image_records[i] = updated_record
                break
        
        self.image_db.update_jan(image_path, jan)
        self.jan_groups = self.image_service.group_by_jan(self.image_records)
        if jan:
            self._jan_title_cache.pop(jan, None)
        self.update_tree_widget()
        
        if show_message:
            QMessageBox.information(self, "完了", f"画像をJANグループ {jan} に登録しました。")
        
        return True
    
    def rename_all_images(self):
        """すべてのJANグループの画像をSKUベースで一括リネームする"""
        if not any(g for g in self.jan_groups if g.jan != "unknown"):
            QMessageBox.information(self, "情報", "リネーム対象のJANグループがありません。")
            return

        reply = QMessageBox.question(
            self,
            "リネーム確認",
            "すべてのJANグループの画像をSKUベースでリネームしますか？\n（既にリネーム済みのファイルはスキップされます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 1. リネーム計画を作成
        rename_operations = []  # List of (old_record, new_path_str)
        failed_skus = set()

        for group in self.jan_groups:
            if group.jan == "unknown":
                continue

            # 画像の撮影日時を取得（最も古い画像の日時を基準にする）
            image_capture_times = []
            for record in group.images:
                if record.capture_dt:
                    image_capture_times.append(record.capture_dt)
            base_capture_dt = min(image_capture_times) if image_capture_times else None
            
            sku_candidates = self._search_sku_candidates_by_jan(group.jan)
            if not sku_candidates or not (sku_candidates[0].get("SKU") or sku_candidates[0].get("sku")):
                failed_skus.add(group.jan)
                continue
            
            # 画像の撮影日時に近いSKUを選択
            if base_capture_dt and len(sku_candidates) > 1:
                # 各候補の仕入れ日と画像の撮影日時の差を計算
                for candidate in sku_candidates:
                    purchase_date_str = str(candidate.get("仕入れ日") or candidate.get("purchase_date") or "")
                    if purchase_date_str:
                        try:
                            # 日付文字列をパース
                            date_str_clean = purchase_date_str.strip()
                            if " " in date_str_clean:
                                date_part, time_part = date_str_clean.split(" ", 1)
                                date_part = date_part.replace("/", "-")
                                datetime_str = f"{date_part} {time_part}"
                                try:
                                    purchase_dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                except:
                                    purchase_dt = datetime.strptime(date_part, "%Y-%m-%d")
                            else:
                                date_part = date_str_clean.replace("/", "-")
                                purchase_dt = datetime.strptime(date_part, "%Y-%m-%d")
                            
                            # 画像の撮影日時との差を計算（絶対値）
                            time_diff = abs((purchase_dt - base_capture_dt).total_seconds())
                            candidate["_time_diff"] = time_diff
                        except Exception:
                            # パースに失敗した場合は大きな値を設定（優先度を下げる）
                            candidate["_time_diff"] = float('inf')
                    else:
                        # 仕入れ日がない場合は大きな値を設定
                        candidate["_time_diff"] = float('inf')
                
                # 時間差が小さい順にソート
                sku_candidates.sort(key=lambda x: x.get("_time_diff", float('inf')))
            
            sku = sku_candidates[0].get("SKU") or sku_candidates[0].get("sku")

            # 撮影日時順にソートしてからリネーム
            sorted_images = sorted(group.images, key=lambda r: r.capture_dt if r.capture_dt else datetime.min)

            for i, record in enumerate(sorted_images):
                original_path = Path(record.path)
                extension = original_path.suffix
                
                # 既にリネーム済みかチェック
                if re.match(f"^{re.escape(sku)}_\\d+{re.escape(extension)}$", original_path.name):
                    continue
                
                new_name = f"{sku}_{i+1}{extension}"
                new_path = original_path.parent / new_name
                
                if str(original_path) != str(new_path):
                    rename_operations.append((record, str(new_path)))

        if not rename_operations:
            QMessageBox.information(self, "情報", "リネーム対象のファイルはありませんでした。")
            return

        # 2. リネーム処理の実行
        progress = QProgressDialog("リネーム処理中...", "キャンセル", 0, len(rename_operations), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        renamed_count = 0
        new_records_map = {}  # old_path -> new_record

        for i, (record, new_path_str) in enumerate(rename_operations):
            progress.setValue(i)
            if progress.wasCanceled():
                break
            
            old_path_str = record.path
            try:
                os.rename(old_path_str, new_path_str)
                
                # DBレコードを更新
                db_record = self.image_db.get_by_file_path(old_path_str)
                if db_record:
                    self.image_db.delete_by_file_path(old_path_str)
                    db_record['file_path'] = new_path_str
                    self.image_db.upsert(db_record)

                # メモリ更新用のマップを作成
                new_record_data = record._asdict()
                new_record_data['path'] = new_path_str
                new_records_map[old_path_str] = ImageRecord(**new_record_data)
                
                renamed_count += 1
            except Exception as e:
                logger.error(f"リネームエラー: {old_path_str} -> {new_path_str}: {e}")
                # エラーが出ても続行
        
        progress.close()

        # 3. メモリ上の`image_records`を更新
        if new_records_map:
            updated_image_records = []
            for record in self.image_records:
                if record.path in new_records_map:
                    updated_image_records.append(new_records_map[record.path])
                else:
                    updated_image_records.append(record)
            self.image_records = updated_image_records
        
        # 4. UIの全体更新と結果報告
        self.jan_groups = self.image_service.group_by_jan(self.image_records)
        self.update_tree_widget()
        self.update_image_list(self.image_records)

        message = f"{renamed_count}件の画像をリネームしました。"
        if failed_skus:
            message += f"\n\n以下のJANコードに対応するSKUが見つからず、関連するグループはスキップされました:\n" + ", ".join(failed_skus)
        QMessageBox.information(self, "完了", message)

    def _extract_sku_from_image_path(self, image_path: str) -> Optional[str]:
        """
        画像ファイル名からSKUを抽出する
        
        Args:
            image_path: 画像ファイルのパス
            
        Returns:
            抽出されたSKU、またはNone
        """
        try:
            file_name = Path(image_path).stem  # 拡張子を除いたファイル名
            # SKU_数字 の形式を想定（例: 20260124-SS-22-027_1）
            match = re.match(r"^(.+?)_\d+$", file_name)
            if match:
                sku = match.group(1)
                # SKUとして妥当かチェック（空でない、適切な長さなど）
                if sku and len(sku) > 0:
                    return sku
        except Exception as e:
            logger.debug(f"SKU抽出エラー ({image_path}): {e}")
        return None

    def _get_target_sku_for_group(self, group: JanGroup, all_records: List[Dict[str, Any]]) -> Optional[str]:
        """
        JANグループに対応するSKUを取得する
        
        1. 画像ファイル名からSKUを抽出を試みる
        2. 抽出できない場合は、仕入DBからJANで検索して、画像の撮影日時に最も近いSKUを取得
        
        Args:
            group: JANグループ
            all_records: 仕入DBの全レコード
            
        Returns:
            対象SKU、またはNone
        """
        jan_norm = str(group.jan).strip().upper()
        
        # 1. 画像ファイル名からSKUを抽出を試みる
        for img in group.images:
            sku = self._extract_sku_from_image_path(img.path)
            if sku:
                # 抽出したSKUが仕入DBに存在するか確認
                for record in all_records:
                    record_jan = str(record.get("JAN") or record.get("jan") or "").strip().upper()
                    record_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                    if record_sku == sku and record_jan == jan_norm:
                        return sku
        
        # 2. 画像ファイル名から抽出できない場合は、仕入DBからJANで検索
        # まず、JANで直接検索を試みる
        matching_records = []
        for record in all_records:
            record_jan = str(record.get("JAN") or record.get("jan") or "").strip().upper()
            if record_jan == jan_norm:
                record_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if record_sku:
                    matching_records.append(record)
        
        if matching_records:
            # 画像の撮影日時を基準に最も近いレコードを選択
            if group.images:
                base_capture_dt = None
                for img in group.images:
                    if img.capture_dt:
                        if base_capture_dt is None or img.capture_dt < base_capture_dt:
                            base_capture_dt = img.capture_dt
                
                if base_capture_dt:
                    # 撮影日時に最も近いレコードを選択
                    best_record = None
                    min_time_diff = None
                    
                    for record in matching_records:
                        purchase_date_str = record.get("仕入日") or record.get("purchase_date") or ""
                        if purchase_date_str:
                            try:
                                purchase_dt = datetime.strptime(str(purchase_date_str), "%Y-%m-%d")
                                time_diff = abs((base_capture_dt - purchase_dt).total_seconds())
                                if min_time_diff is None or time_diff < min_time_diff:
                                    min_time_diff = time_diff
                                    best_record = record
                            except Exception:
                                pass
                    
                    if best_record:
                        target_sku = str(best_record.get("SKU") or best_record.get("sku") or "").strip()
                        if target_sku:
                            return target_sku
            
            # 撮影日時が取得できない、または時間差で判定できない場合は最初のレコードを使用
            if matching_records:
                target_sku = str(
                    matching_records[0].get("SKU") or matching_records[0].get("sku") or ""
                ).strip()
                if target_sku:
                    return target_sku
        
        return None

    def confirm_image_links(self):
        """JANグループエリアに登録されている全てのJANグループの画像パスを仕入DBに登録（既に登録済みはスキップ）"""
        if not self.product_widget:
            QMessageBox.warning(self, "エラー", "データベース管理タブが見つかりません。")
            return

        # 有効なJANグループを抽出（JAN不明グループは除外）
        valid_groups = [g for g in self.jan_groups if g.jan != "unknown" and g.images]

        if not valid_groups:
            QMessageBox.information(self, "情報", "確定処理対象のJANグループがありません。")
            return

        # 常に最新のレコードリストを取得
        all_records = self.product_widget.get_all_purchase_records()

        # プログレスダイアログを表示
        progress = QProgressDialog("確定処理中...", "キャンセル", 0, len(valid_groups), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        success_count = 0
        skipped_count = 0
        failed_groups = []

        try:
            for i, group in enumerate(valid_groups):
                if progress.wasCanceled():
                    break

                progress.setValue(i)
                progress.setLabelText(f"確定処理中... ({i+1}/{len(valid_groups)}) - JAN: {group.jan}")
                QApplication.processEvents()

                jan = group.jan
                image_paths = [img.path for img in group.images]

                if not image_paths:
                    continue

                try:
                    # 対象SKUを取得
                    target_sku = self._get_target_sku_for_group(group, all_records)
                    
                    # 更新処理を実行（既存画像はスキップ）
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        jan, image_paths, all_records, skip_existing=True, target_sku=target_sku
                    )

                    if success:
                        if added_count > 0:
                            success_count += 1
                            skipped = len(image_paths) - added_count
                            if skipped > 0:
                                skipped_count += skipped
                        else:
                            skipped_count += len(image_paths)
                        if record_snapshot:
                            self.add_registration_entry(record_snapshot)
                    else:
                        failed_groups.append(jan)

                except Exception as e:
                    logger.error(f"JAN '{jan}' の確定処理中にエラー: {e}")
                    failed_groups.append(jan)

            progress.close()

            # 結果メッセージを表示
            message_parts = []
            if success_count > 0:
                message_parts.append(f"{success_count}件のJANグループを確定処理しました。")
            if skipped_count > 0:
                message_parts.append(f"{skipped_count}件の画像は既に登録済みのためスキップしました。")
            if failed_groups:
                message_parts.append(f"\n以下のJANグループの処理に失敗しました:\n{', '.join(failed_groups)}")

            if message_parts:
                QMessageBox.information(self, "確定処理完了", "\n".join(message_parts))
            else:
                QMessageBox.information(self, "確定処理完了", "処理が完了しました。")

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "エラー", f"確定処理中にエラーが発生しました:\n{e}")

    def setup_registration_tab(self):
        """画像登録タブのセットアップ"""
        self.registration_tab = QWidget()
        layout = QVBoxLayout(self.registration_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        description = QLabel(
            "確定処理で仕入DBに登録した商品の情報を表示します。\n"
            "アプリ再起動時に自動でクリアされる一時的なリストです。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.registration_table = RegistrationTableWidget()
        self.registration_columns = [
            "コンディション", "SKU", "ASIN", "JAN", "商品名",
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
            # Amazon Lファイル用追加列（URLのみ残す）
            "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5"
        ]
        self.registration_table.setColumnCount(len(self.registration_columns))
        self.registration_table.setHorizontalHeaderLabels(self.registration_columns)
        header = self.registration_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # 全列を手動リサイズ可能に
        header.setTextElideMode(Qt.ElideNone)  # ヘッダー文字列を省略しない
        self.registration_table.setTextElideMode(Qt.ElideNone)  # セル文字列も省略しない
        # 初期幅の目安を設定（後から手動リサイズ可能）
        self.registration_table.setColumnWidth(1, 180)  # SKU
        self.registration_table.setColumnWidth(2, 150)  # ASIN
        self.registration_table.setColumnWidth(3, 150)  # JAN
        self.registration_table.setColumnWidth(4, 320)  # 商品名
        for col in range(5, 11):  # 画像1～6
            self.registration_table.setColumnWidth(col, 180)
        for col in range(11, 16):  # 画像URL1～5
            self.registration_table.setColumnWidth(col, 220)
        # 編集トリガー:
        # - シングルクリックは「プレビュー表示」に使いたいので、SelectedClickedは使わない
        # - 編集は「ダブルクリック」または「F2キー」で開始
        self.registration_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.registration_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.registration_table.setSelectionMode(QTableWidget.SingleSelection)
        self.registration_table.verticalHeader().setVisible(False)
        self.registration_table.setDragEnabled(True)
        self.registration_table.cellDoubleClicked.connect(self.on_registration_cell_double_clicked)
        self.registration_table.cellClicked.connect(self.on_registration_cell_clicked)
        # 環境によってはcellClickedが発火しない/分かりにくい場合があるため、
        # カレントセル変更でもプレビュー更新を行う（保険）
        self.registration_table.currentCellChanged.connect(self.on_registration_current_cell_changed)
        # 行選択モードでも確実に拾えるよう、itemClicked/itemPressedでもプレビュー更新（保険）
        self.registration_table.itemClicked.connect(self.on_registration_item_clicked)
        self.registration_table.itemPressed.connect(self.on_registration_item_clicked)
        self.registration_table.cellChanged.connect(self.on_registration_cell_changed)
        # 右クリックメニュー（画像URL削除用）
        self.registration_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.registration_table.customContextMenuRequested.connect(self.on_registration_table_context_menu)
        layout.addWidget(self.registration_table)

        preview_group = QGroupBox("プレビュー")
        preview_layout = QVBoxLayout(preview_group)
        self.registration_preview_label = QLabel("画像を選択してください")
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setMinimumHeight(200)
        # ダークテーマ時でもメッセージが見えるように文字色を固定（背景は白）
        self.registration_preview_label.setStyleSheet(
            "border: 1px solid gray; background-color: #f8f8f8; color: #111;"
        )
        self.registration_preview_label.setScaledContents(False)
        preview_layout.addWidget(self.registration_preview_label)
        layout.addWidget(preview_group)

        # URL画像プレビュー用（非同期・urllibで取得して確実に表示）
        self._registration_preview_pending_url = ""
        self._registration_preview_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._registration_preview_future = None
        # シグナル接続（バックグラウンドスレッドからメインスレッドへ）
        self._preview_image_ready.connect(self._on_preview_image_ready)
        self._preview_image_error.connect(self._on_preview_image_error)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # テンプレートファイル指定
        template_label = QLabel("テンプレート:")
        button_layout.addWidget(template_label)
        
        self.template_file_edit = QLineEdit()
        self.template_file_edit.setPlaceholderText("AmazonテンプレートExcelファイルを選択...")
        self.template_file_edit.setMinimumWidth(300)
        self.template_file_edit.setReadOnly(True)
        button_layout.addWidget(self.template_file_edit)
        
        self.template_file_browse_btn = QPushButton("参照...")
        self.template_file_browse_btn.setToolTip("AmazonテンプレートExcelファイルを選択します")
        self.template_file_browse_btn.clicked.connect(self.browse_template_file)
        button_layout.addWidget(self.template_file_browse_btn)
        
        # スナップショット保存／読込（実行テスト用）
        self.save_registration_snapshot_btn = QPushButton("スナップ保存")
        self.save_registration_snapshot_btn.setToolTip("現在の一覧を一時保存します（再起動後のテスト用）")
        self.save_registration_snapshot_btn.clicked.connect(self.save_registration_snapshot)
        button_layout.addWidget(self.save_registration_snapshot_btn)

        self.load_registration_snapshot_btn = QPushButton("スナップ読込")
        self.load_registration_snapshot_btn.setToolTip("前回保存したスナップデータを読み込みます")
        self.load_registration_snapshot_btn.clicked.connect(self.load_registration_snapshot)
        button_layout.addWidget(self.load_registration_snapshot_btn)

        self.clear_registration_btn = QPushButton("一覧をクリア")
        self.clear_registration_btn.setToolTip("画像登録リストをすべて削除します")
        self.clear_registration_btn.clicked.connect(self.clear_registration_records)
        button_layout.addWidget(self.clear_registration_btn)

        # 選択行の削除ボタン
        self.delete_registration_row_btn = QPushButton("選択行を削除")
        self.delete_registration_row_btn.setToolTip("選択されている行だけを画像登録リストから削除します")
        self.delete_registration_row_btn.clicked.connect(self.delete_selected_registration_rows)
        button_layout.addWidget(self.delete_registration_row_btn)

        self.upload_to_gcs_btn = QPushButton("GCSアップロード")
        self.upload_to_gcs_btn.setToolTip("選択行（未選択の場合は確認後に全行）の商品画像をGCSにアップロードします")
        self.upload_to_gcs_btn.clicked.connect(self.upload_images_to_gcs)
        button_layout.addWidget(self.upload_to_gcs_btn)

        # GCS一括アップロード（全行）
        self.upload_all_to_gcs_btn = QPushButton("GCS一括アップロード")
        self.upload_all_to_gcs_btn.setToolTip("表示中の全行の未アップロード画像をGCSに一括アップロードします")
        self.upload_all_to_gcs_btn.clicked.connect(self.upload_all_images_to_gcs)
        button_layout.addWidget(self.upload_all_to_gcs_btn)

        # GCS存在チェック（全行 or 選択行）
        self.check_existing_gcs_btn = QPushButton("GCS存在チェック")
        self.check_existing_gcs_btn.setToolTip("GCSに既に存在する画像があれば検索し、画像URL欄に自動入力します（ファイル名で検索）")
        self.check_existing_gcs_btn.clicked.connect(self.check_existing_images_in_gcs)
        button_layout.addWidget(self.check_existing_gcs_btn)

        # 仕入DBに保存ボタン（画像URL1〜6を永続化）
        self.save_to_db_btn = QPushButton("DBに保存")
        self.save_to_db_btn.setToolTip("一覧のSKUごとに、画像URL1〜6を仕入DBに保存します")
        self.save_to_db_btn.clicked.connect(self.save_registration_to_purchase_db)
        button_layout.addWidget(self.save_to_db_btn)

        # AmazonテンプレートExcelに書き込み
        self.write_amazon_template_btn = QPushButton("amazon（出品ファイルL）テンプレートに書き込み")
        self.write_amazon_template_btn.setToolTip("AmazonテンプレートExcelファイル（出品ファイルL）にSKUと画像URLを書き込みます。")
        self.write_amazon_template_btn.clicked.connect(self.write_to_amazon_template)
        button_layout.addWidget(self.write_amazon_template_btn)

        # Amazonアップロードリンクボタン
        self.amazon_upload_link_btn = QPushButton("Amazonアップロードページを開く")
        self.amazon_upload_link_btn.setToolTip("Amazon Seller Centralの出品ファイルアップロードページをブラウザで開きます")
        self.amazon_upload_link_btn.clicked.connect(self.open_amazon_upload_page)
        button_layout.addWidget(self.amazon_upload_link_btn)

        layout.addLayout(button_layout)
        
        # 設定からテンプレートファイルパスを読み込む
        self.load_template_file_setting()

    def _get_record_value(self, record: Dict[str, Any], keys: List[str], default: str = "") -> str:
        """複数の候補キーから値を取得"""
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
        return default

    def add_registration_entry(self, record: Dict[str, Any]):
        """仕入DBレコード情報を画像登録タブに追加（画像を商品画像とバーコード画像に分類）"""
        entry = {
            "condition": self._get_record_value(record, ["コンディション", "condition"]),
            "sku": self._get_record_value(record, ["SKU", "sku"]),
            "asin": self._get_record_value(record, ["ASIN", "asin"]),
            "jan": self._get_record_value(record, ["JAN", "jan"]),
            "product_name": self._get_record_value(record, ["商品名", "product_name", "title"]),
            "images": [],  # 元の画像パス（表示用）
            "product_images": [],  # 商品画像（Amazon Lファイル用、最大5枚）
            "barcode_image": None,  # バーコード画像（識別用）
            # Amazon Lファイル用フィールド
            "price": self._get_record_value(record, ["販売価格", "price", "plannedPrice"]),
            "quantity": self._get_record_value(record, ["在庫数", "quantity", "add_number"], default="0"),
            "condition_type": self._get_record_value(record, ["コンディション番号", "condition_type", "condition-type"]),
            "condition_note": self._get_record_value(record, ["コンディション説明", "condition_note", "conditionNote"]),
            "image_urls": []  # GCSアップロード後のURL（最大5枚）
        }
        
        # 元の画像パスを取得
        for i in range(1, 7):
            img_path = self._get_record_value(
                record,
                [f"画像{i}", f"image_{i}", f"画像 {i}"]
            )
            if img_path:
                entry["images"].append(img_path)
        
        # 画像を商品画像とバーコード画像に分類
        product_images = []
        barcode_image = None
        
        for img_path in entry["images"]:
            if not img_path:
                continue
            
            # バーコード画像判定
            try:
                if self.image_service.is_barcode_only_image(img_path):
                    # バーコード画像（最初の1枚のみ保存）
                    if not barcode_image:
                        barcode_image = img_path
                else:
                    # 商品画像（最大5枚）
                    if len(product_images) < 5:
                        product_images.append(img_path)
            except Exception as e:
                logger.warning(f"Failed to check if image is barcode-only: {e}, treating as product image")
                # エラー時は商品画像として扱う
                if len(product_images) < 5:
                    product_images.append(img_path)
        
        entry["product_images"] = product_images
        entry["barcode_image"] = barcode_image
        
        # 画像URLを取得（優先順位: record > 仕入DB）
        # 1. まずrecordから画像URLを取得（確定処理直後の場合）
        image_urls_from_record = []
        for i in range(1, 7):
            img_url_key = f"画像URL{i}"
            img_url_alt_key = f"image_url_{i}"
            img_url = record.get(img_url_key) or record.get(img_url_alt_key)
            image_urls_from_record.append(img_url if img_url else "")
        
        # 2. recordに画像URLがない場合は、仕入DBから取得
        if not any(image_urls_from_record) and entry["sku"]:
            try:
                from database.purchase_db import PurchaseDatabase
                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(entry["sku"])
                if purchase_record:
                    # image_url_1からimage_url_6まで取得
                    for i in range(1, 7):
                        img_url = purchase_record.get(f"image_url_{i}")
                        if img_url:
                            image_urls_from_record[i - 1] = img_url
            except Exception as e:
                logger.debug(f"Failed to get image URLs from purchase DB: {e}")
        
        # 画像URLリストを設定（空文字列を除く）
        entry["image_urls"] = [url for url in image_urls_from_record if url]

        self.registration_records.append(entry)
        self.update_registration_table()

    def update_registration_table(self):
        """画像登録タブのテーブルを更新"""
        self.registration_table.setRowCount(len(self.registration_records))

        for row, entry in enumerate(self.registration_records):
            # 基本情報（既存カラム）
            values = [
                entry.get("condition", ""),
                entry.get("sku", ""),
                entry.get("asin", ""),
                entry.get("jan", ""),
                entry.get("product_name", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                # JANのみ編集可
                if col == 3:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, col, item)

            # 元の画像パス（既存カラム、表示用）
            for idx, image_path in enumerate(entry.get("images", [])):
                col = 5 + idx
                if col >= len(self.registration_columns):
                    break
                display_text = Path(image_path).name if image_path else ""
                item = QTableWidgetItem(display_text)
                if image_path:
                    item.setData(Qt.UserRole, image_path)
                    item.setToolTip(image_path)
                    item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
                self.registration_table.setItem(row, col, item)
            
            # 画像URL1～5（編集可能、GCSアップロード後のURL）
            col_offset = 11  # 既存カラム数（コンディション、SKU、ASIN、JAN、商品名、画像1～6）
            for idx in range(5):
                col = col_offset + idx
                img_url = entry.get("image_urls", [])[idx] if idx < len(entry.get("image_urls", [])) else ""
                item = QTableWidgetItem(img_url)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, col, item)

    def clear_registration_records(self):
        """画像登録リストをクリア"""
        if not self.registration_records:
            return
        reply = QMessageBox.question(
            self,
            "確認",
            "画像登録リストをクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.registration_records = []
            self.registration_table.setRowCount(0)
            self._set_registration_preview(None)

    def delete_selected_registration_rows(self):
        """選択されている行だけを画像登録リストから削除"""
        if not self.registration_records:
            QMessageBox.information(self, "情報", "削除する行がありません。")
            return

        selected_rows = set()
        for item in self.registration_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, "情報", "削除する行が選択されていません。")
            return

        reply = QMessageBox.question(
            self,
            "確認",
            f"選択されている {len(selected_rows)} 行を画像登録リストから削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # インデックスがずれないように降順で削除
        for row in sorted(selected_rows, reverse=True):
            if row < len(self.registration_records):
                del self.registration_records[row]

        # テーブルを再描画
        self.update_registration_table()
        self._set_registration_preview(None)

    def save_registration_to_purchase_db(self):
        """
        画像登録タブの内容を仕入DB（PurchaseDatabase）に保存する。

        - SKUごとに image_url_1〜image_url_6 を更新（PurchaseDatabase）
        - さらに、最新の仕入DBスナップショット（ProductPurchaseDatabase）にも
          画像URL1〜6を反映し、新しいスナップショットとして保存する
        """
        if not self.registration_records:
            QMessageBox.information(self, "情報", "保存するデータがありません。")
            return

        try:
            from database.purchase_db import PurchaseDatabase
        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"仕入DBモジュールの読み込みに失敗しました:\n{e}",
            )
            return

        purchase_db = PurchaseDatabase()

        # 商品マスタ（products）にも画像パス・URLを保存するためにProductDatabaseを使用
        try:
            from database.product_db import ProductDatabase
            product_db = ProductDatabase()
        except Exception as e:
            product_db = None
            logger.warning(f"ProductDatabaseの初期化に失敗しました（商品DBへの画像保存はスキップされます）: {e}")
        updated_count = 0
        skipped_count = 0

        # SKU -> image_urls / image_paths のマップを作成（後でスナップショットにも反映）
        sku_to_image_urls: Dict[str, List[str]] = {}
        sku_to_image_paths: Dict[str, List[str]] = {}

        for entry in self.registration_records:
            sku = (entry.get("sku") or "").strip()
            if not sku:
                skipped_count += 1
                continue

            # 仕入DBから最新の画像URLを取得（常に最新の状態を反映）
            image_urls = []
            try:
                purchase_record = purchase_db.get_by_sku(sku)
                if purchase_record:
                    for i in range(1, 7):
                        img_url = purchase_record.get(f"image_url_{i}")
                        if img_url:
                            image_urls.append(img_url)
            except Exception as e:
                logger.debug(f"Failed to get image URLs from purchase DB for SKU {sku}: {e}")
                # エラー時はentryから取得を試みる
                image_urls = entry.get("image_urls", []) or []

            # 商品画像パス（バーコード以外の画像1〜6）
            image_paths_raw = entry.get("product_images") or entry.get("images") or []
            # 最大6件に正規化
            norm_paths: List[str] = []
            for i in range(6):
                norm_paths.append(image_paths_raw[i] if i < len(image_paths_raw) else "")

            # image_url_1〜6 を構築（不足分は空文字）
            update_data: Dict[str, Any] = {"sku": sku}
            for i in range(6):
                key = f"image_url_{i + 1}"
                if i < len(image_urls) and image_urls[i]:
                    update_data[key] = image_urls[i]
                else:
                    update_data[key] = ""

            sku_to_image_urls[sku] = [update_data[f"image_url_{i+1}"] for i in range(6)]
            sku_to_image_paths[sku] = norm_paths

            try:
                purchase_db.upsert(update_data)
                updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to save image URLs to purchase DB for SKU {sku}: {e}")
                skipped_count += 1

            # products テーブルの image_1〜6 / image_url_1〜6 も更新
            if product_db is not None:
                try:
                    product_db.update_images_and_urls(sku, sku_to_image_paths[sku], sku_to_image_urls[sku])
                except Exception as e:
                    logger.warning(f"Failed to update products table images for SKU {sku}: {e}")

        # 商品DBタブの仕入DBスナップショットにも反映
        snapshot_updated = False
        try:
            from database.product_purchase_db import ProductPurchaseDatabase

            pp_db = ProductPurchaseDatabase()
            snapshots = pp_db.list_snapshots()
            if snapshots:
                latest_id = snapshots[0]["id"]
                snapshot = pp_db.get_snapshot(latest_id)
                if snapshot and isinstance(snapshot.get("data"), list):
                    data = snapshot["data"]
                    for row in data:
                        sku = (row.get("SKU") or row.get("sku") or "").strip()
                        if not sku:
                            continue

                        # 画像URL1〜6
                        urls = sku_to_image_urls.get(sku)
                        if urls:
                            for i in range(6):
                                col_name = f"画像URL{i + 1}"
                                url_val = urls[i] if i < len(urls) else ""
                                row[col_name] = url_val

                        # 画像1〜6（ファイル名）もスナップショットに直接保存
                        paths = sku_to_image_paths.get(sku)
                        if paths:
                            for i in range(6):
                                col_name = f"画像{i + 1}"
                                path_val = paths[i] if i < len(paths) else ""
                                row[col_name] = path_val

                    # 新しいスナップショットとして保存（最新が自動的に使われる）
                    pp_db.save_snapshot("image_urls_synced", data)
                    snapshot_updated = True
        except Exception as e:
            logger.warning(f"Failed to update purchase snapshot DB with image URLs: {e}")

        QMessageBox.information(
            self,
            "DBに保存",
            f"仕入DBへの保存が完了しました。\n\n"
            f"更新されたSKU: {updated_count}件\n"
            f"スキップ/エラー: {skipped_count}件\n"
            f"スナップショット更新: {'あり' if snapshot_updated else 'なし'}",
        )

    def save_registration_snapshot(self):
        """画像登録タブの現在の一覧をJSONファイルにスナップ保存（テスト用）"""
        if not self.registration_records:
            QMessageBox.information(self, "スナップ保存", "保存するデータがありません。")
            return

        try:
            self.registration_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "record_count": len(self.registration_records),
                "records": self.registration_records,
            }
            with open(self.registration_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "スナップ保存",
                f"画像登録一覧をスナップ保存しました。\n"
                f"ファイル: {self.registration_snapshot_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップ保存エラー", f"スナップ保存に失敗しました:\n{e}")

    def load_registration_snapshot(self):
        """前回保存したスナップショットを読み込んで一覧に復元"""
        if not self.registration_snapshot_path.exists():
            QMessageBox.information(
                self,
                "スナップ読込",
                "スナップショットファイルが見つかりませんでした。\n"
                "先に「スナップ保存」を実行してください。",
            )
            return

        try:
            with open(self.registration_snapshot_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            records = payload.get("records", [])
            if not isinstance(records, list):
                raise ValueError("records フィールドの形式が不正です。")

            self.registration_records = records
            self.update_registration_table()
            self._set_registration_preview(None)

            saved_at = payload.get("saved_at", "不明な日時")
            QMessageBox.information(
                self,
                "スナップ読込",
                f"スナップショットを読み込みました。\n"
                f"保存日時: {saved_at}\n"
                f"件数: {len(self.registration_records)}件",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップ読込エラー", f"スナップ読込に失敗しました:\n{e}")

    def on_registration_cell_double_clicked(self, row: int, column: int):
        """画像列ダブルクリックでファイルを開く"""
        col_offset = 11
        # 画像URL1～5 はダブルクリックで別窓表示
        if col_offset <= column <= col_offset + 4:
            item = self.registration_table.item(row, column)
            if not item:
                return
            url = (item.text() or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                self._show_remote_image_dialog(url)
            return

        if column < 4:
            return
        item = self.registration_table.item(row, column)
        if not item:
            return
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return
        file_path = Path(image_path)
        if not file_path.exists():
            QMessageBox.warning(self, "エラー", f"画像ファイルが見つかりません:\n{image_path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))

    def on_registration_cell_clicked(self, row: int, column: int):
        """画像選択時にプレビュー表示"""
        col_offset = 11
        # 画像URL1～5 はクリックでプレビュー表示（リモート画像）
        if col_offset <= column <= col_offset + 4:
            item = self.registration_table.item(row, column)
            if not item:
                return
            url = (item.text() or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                self._set_registration_preview_url(url)
            return

        if column < 4:
            self._set_registration_preview(None)
            return
        item = self.registration_table.item(row, column)
        if not item:
            self._set_registration_preview(None)
            return
        image_path = item.data(Qt.UserRole)
        self._set_registration_preview(image_path)

    def on_registration_current_cell_changed(self, current_row: int, current_col: int, prev_row: int, prev_col: int):
        """カレントセル変更時にもプレビュー更新（クリックが取れない環境の保険）"""
        if current_row < 0 or current_col < 0:
            return
        self.on_registration_cell_clicked(current_row, current_col)

    def on_registration_item_clicked(self, item: QTableWidgetItem):
        """itemClicked/itemPressed用（行選択でも確実に拾う）"""
        try:
            row = item.row()
            col = item.column()
        except Exception:
            return
        self.on_registration_cell_clicked(row, col)
    
    def on_registration_cell_changed(self, row: int, column: int):
        """テーブルセル編集時にregistration_recordsを更新"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        item = self.registration_table.item(row, column)
        if not item:
            return
        
        col_offset = 11  # 既存カラム数（コンディション、SKU、ASIN、JAN、商品名、画像1～6）
        
        # 編集可能なカラムのみ更新
        if column == 1:  # SKU（将来の直接編集にも対応）
            entry["sku"] = item.text()
        elif column == 3:  # JAN
            entry["jan"] = item.text()
        elif col_offset <= column <= col_offset + 4:  # 画像URL1～5
            idx = column - col_offset
            if "image_urls" not in entry:
                entry["image_urls"] = [""] * 5
            while len(entry["image_urls"]) <= idx:
                entry["image_urls"].append("")
            entry["image_urls"][idx] = item.text()

    def on_registration_table_context_menu(self, pos):
        """画像登録テーブルの右クリックメニュー"""
        item = self.registration_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        column = item.column()

        # SKU列（1）: JANから仕入DB検索してSKU候補を選択
        if column == 1:
            self.change_sku_for_registration_row(row)
            return

        # 画像1～6の列（5～10）: 右クリックでローカル画像操作メニュー
        if 5 <= column <= 10:
            image_idx = column - 5  # 0～5
            menu = QMenu(self)
            delete_local_action = menu.addAction("この画像を削除（後続の画像をスライド）")
            force_action = menu.addAction("この画像をGCSに強制アップロード（バーコード判定を無視）")
            action = menu.exec_(self.registration_table.viewport().mapToGlobal(pos))
            if action == delete_local_action:
                self.delete_and_slide_local_image(row, image_idx)
            elif action == force_action:
                self.force_upload_single_image_to_gcs(row, image_idx)
            return

        # 画像URL1～5の列（11～15）のみURL編集メニュー表示
        col_offset = 11  # 画像URL1の列インデックス
        if not (col_offset <= column <= col_offset + 4):
            return

        url_idx = column - col_offset  # 0～4
        url_label = f"画像URL{url_idx + 1}"

        menu = QMenu(self)
        delete_action = menu.addAction(f"{url_label} を削除（後続URLをスライド）")
        clear_action = menu.addAction(f"{url_label} をクリア（スライドなし）")

        action = menu.exec_(self.registration_table.viewport().mapToGlobal(pos))

        if action == delete_action:
            self._delete_and_slide_image_url(row, url_idx)
        elif action == clear_action:
            self._clear_image_url(row, url_idx)

    def force_upload_single_image_to_gcs(self, row: int, image_idx: int):
        """
        画像1〜6セルを右クリックしたときに呼び出される、
        単一画像のGCS「強制」アップロード処理。

        - バーコードかどうかの判定は一切行わない
        - 既にURLが入っていても上書きしたい場合に使える
        """
        if row >= len(self.registration_records):
            return

        # 対象セルからローカル画像パスを取得
        column = 5 + image_idx  # 画像1〜6列
        item = self.registration_table.item(row, column)
        if not item:
            QMessageBox.warning(self, "エラー", "画像パスが見つかりません。")
            return

        image_path = item.data(Qt.UserRole)
        if not image_path:
            QMessageBox.warning(self, "エラー", "画像パスが設定されていません。")
            return

        image_path = str(image_path)
        if not Path(image_path).exists():
            QMessageBox.warning(self, "エラー", f"画像ファイルが見つかりません:\n{image_path}")
            return

        entry = self.registration_records[row]
        sku = entry.get("sku") or ""

        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "GCS強制アップロード",
            f"この画像をGCSに強制アップロードしますか？\n\n"
            f"SKU: {sku or '（未設定）'}\n"
            f"画像: {Path(image_path).name}\n\n"
            f"※ バーコード画像かどうかに関係なくアップロードします。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # gcs_uploaderの読み込み（通常アップロードと同等の処理を簡略化）
        try:
            import sys
            import os
            import importlib.util

            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            python_dir = os.path.abspath(os.path.join(current_file_dir, "..", ".."))
            candidate_paths = [python_dir, os.path.join(python_dir, "python")]

            found_path = None
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, "utils", "gcs_uploader.py")
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break

            if found_path:
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                sys.path[0] = found_path

                gcs_uploader_file = os.path.join(found_path, "utils", "gcs_uploader.py")
                if not os.path.exists(gcs_uploader_file):
                    raise ImportError(f"gcs_uploader.py not found at {gcs_uploader_file}")

                spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                gcs_uploader_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gcs_uploader_module)
                upload_image_to_gcs = gcs_uploader_module.upload_image_to_gcs
                GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                find_existing_public_url_for_local_file = getattr(
                    gcs_uploader_module, "find_existing_public_url_for_local_file", None
                )
            else:
                from utils.gcs_uploader import upload_image_to_gcs, GCS_AVAILABLE, check_gcs_authentication
                try:
                    from utils.gcs_uploader import find_existing_public_url_for_local_file
                except Exception:
                    find_existing_public_url_for_local_file = None

            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self,
                    "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。",
                )
                return

            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self,
                    "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。",
                )
                return
        except ImportError as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"GCSアップロード機能の読み込みに失敗しました:\n\n{str(e)}",
            )
            return

        # 実際のアップロード処理（既存URLチェックも実施）
        try:
            if find_existing_public_url_for_local_file:
                try:
                    existing_url = find_existing_public_url_for_local_file(image_path)
                except Exception:
                    existing_url = None
                if existing_url:
                    public_url = existing_url
                else:
                    public_url = upload_image_to_gcs(image_path)
            else:
                public_url = upload_image_to_gcs(image_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "アップロード失敗",
                f"GCSへのアップロードに失敗しました:\n{e}",
            )
            logger.error(f"Force upload failed for {image_path}: {e}", exc_info=True)
            return

        # registration_records の image_urls を更新
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        while len(entry["image_urls"]) <= image_idx:
            entry["image_urls"].append("")
        entry["image_urls"][image_idx] = public_url

        # テーブル（画像URL列）にも反映
        url_col_offset = 11
        url_col = url_col_offset + image_idx
        if url_col < self.registration_table.columnCount():
            url_item = self.registration_table.item(row, url_col)
            if url_item:
                url_item.setText(public_url)
            else:
                url_item = QTableWidgetItem(public_url)
                url_item.setFlags(url_item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, url_col, url_item)

        # 仕入DB（purchase_db）の image_url_n も更新
        try:
            if sku:
                from database.purchase_db import PurchaseDatabase

                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(sku)

                image_url_key = f"image_url_{image_idx + 1}"
                if purchase_record:
                    update_data = dict(purchase_record)
                    update_data[image_url_key] = public_url
                    purchase_db.upsert(update_data)
                else:
                    new_data = {"sku": sku, image_url_key: public_url}
                    purchase_db.upsert(new_data)
        except Exception as e:
            logger.warning(f"Failed to update purchase DB for SKU {sku or 'N/A'}: {e}")

        QMessageBox.information(
            self,
            "アップロード完了",
            f"画像をGCSにアップロードしました。\n\n"
            f"SKU: {sku or '（未設定）'}\n"
            f"画像URL: {public_url}",
        )

    def delete_and_slide_local_image(self, row: int, image_idx: int):
        """
        画像1〜6のセルで選択された画像を削除し、
        後ろの画像を左にスライドさせる。

        - registration_records.product_images を編集
        - 対応する image_urls もスライド
        - テーブルの画像1〜6 / 画像URL1〜5 を更新
        - 仕入DB（purchase_db）の image_url_n も反映
        """
        if row >= len(self.registration_records):
            return

        entry = self.registration_records[row]
        product_images = entry.get("product_images", [])

        if image_idx >= len(product_images):
            QMessageBox.information(self, "情報", "削除対象の画像がありません。")
            return

        target_path = product_images[image_idx]
        file_name = Path(target_path).name if target_path else f"画像{image_idx + 1}"

        reply = QMessageBox.question(
            self,
            "画像削除の確認",
            f"画像{image_idx + 1} を削除して、後ろの画像を左に詰めますか？\n\n"
            f"対象: {file_name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # product_images をスライド
        if product_images:
            del product_images[image_idx]
        # 最大6枚に制限しておく
        while len(product_images) < 6:
            product_images.append("")
        entry["product_images"] = product_images[:6]

        # image_urls も同じようにスライド
        image_urls = entry.get("image_urls", [])
        if image_idx < len(image_urls):
            del image_urls[image_idx]
        while len(image_urls) < 5:
            image_urls.append("")
        entry["image_urls"] = image_urls[:5]

        # テーブル上の画像1〜6 / 画像URL1〜5 を更新
        # 画像1〜6列は5〜10、画像URL1〜5列は11〜15
        for idx in range(6):
            col = 5 + idx
            if col >= self.registration_table.columnCount():
                continue
            img_path = entry["product_images"][idx] if idx < len(entry["product_images"]) else ""
            item = self.registration_table.item(row, col)
            if img_path:
                file_name = Path(img_path).name
                if not item:
                    item = QTableWidgetItem(file_name)
                    self.registration_table.setItem(row, col, item)
                else:
                    item.setText(file_name)
                item.setData(Qt.UserRole, img_path)
                item.setToolTip(img_path)
            else:
                if item:
                    item.setText("")
                    item.setData(Qt.UserRole, "")
                    item.setToolTip("")

        for idx in range(5):
            col = 11 + idx
            if col >= self.registration_table.columnCount():
                continue
            url = entry["image_urls"][idx] if idx < len(entry["image_urls"]) else ""
            item = self.registration_table.item(row, col)
            if url:
                if not item:
                    item = QTableWidgetItem(url)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.registration_table.setItem(row, col, item)
                else:
                    item.setText(url)
            else:
                if item:
                    item.setText("")

        # 仕入DBの image_url_n を更新
        try:
            sku = entry.get("sku")
            if sku:
                from database.purchase_db import PurchaseDatabase

                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(sku)
                update_data = {}

                # 現在の image_urls から image_url_1〜6 を再構築
                for i in range(6):
                    key = f"image_url_{i + 1}"
                    if i < len(entry["image_urls"]) and entry["image_urls"][i]:
                        update_data[key] = entry["image_urls"][i]
                    else:
                        update_data[key] = ""

                if purchase_record:
                    base = dict(purchase_record)
                    base.update(update_data)
                    base["sku"] = sku
                    purchase_db.upsert(base)
                else:
                    update_data["sku"] = sku
                    purchase_db.upsert(update_data)
        except Exception as e:
            logger.warning(f"Failed to update purchase DB after local image delete for SKU {entry.get('sku', 'N/A')}: {e}")

        QMessageBox.information(self, "削除完了", "画像を削除し、後続の画像をスライドしました。")

    def change_sku_for_registration_row(self, row: int):
        """
        SKU列を右クリックしたときに、JANから仕入DBを検索して
        SKU候補を一覧表示し、選択または直接入力できるようにする。
        """
        if row >= len(self.registration_records):
            return

        entry = self.registration_records[row]
        jan = (entry.get("jan") or "").strip()
        if not jan:
            # テーブルのJANセルからも試す
            item = self.registration_table.item(row, 3)
            if item:
                jan = (item.text() or "").strip()

        if not jan:
            QMessageBox.warning(self, "エラー", "JANコードが設定されていないため、SKU候補を検索できません。")
            return

        # 仕入DBからJANで候補検索
        sku_candidates = self._search_sku_candidates_by_jan(jan)
        if not sku_candidates:
            # 候補がない場合は手入力のみ
            sku, ok = QInputDialog.getText(
                self,
                "SKU変更",
                f"JAN {jan} に対応するSKU候補が見つかりませんでした。\n"
                f"手動でSKUを入力してください：",
            )
            if not ok or not sku:
                return
            sku = sku.strip()
        else:
            # 「SKU - 商品名」を一覧表示
            items = []
            sku_map: Dict[str, Dict[str, Any]] = {}
            for record in sku_candidates:
                cand_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if not cand_sku:
                    continue
                name = (
                    record.get("商品名")
                    or record.get("product_name")
                    or record.get("title")
                    or ""
                )
                label = cand_sku if not name else f"{cand_sku} - {name}"
                if label not in sku_map:
                    items.append(label)
                    sku_map[label] = record

            dlg = QInputDialog(self)
            dlg.setWindowTitle("SKU変更")
            dlg.setLabelText(
                f"JAN {jan} に対応するSKU候補を選択するか、直接SKUを入力してください："
            )
            dlg.setComboBoxEditable(True)
            dlg.setComboBoxItems(items)
            dlg.setStyleSheet(
                "QComboBox, QLineEdit, QListView {"
                "  color: black;"
                "  background-color: white;"
                "}"
                "QListView::item:selected {"
                "  color: black;"
                "  background-color: #cce4ff;"
                "}"
            )

            if dlg.exec_() != QDialog.Accepted:
                return

            selected_text = dlg.textValue().strip()
            if selected_text in sku_map:
                sku = str(sku_map[selected_text].get("SKU") or sku_map[selected_text].get("sku") or "").strip()
                # 商品名が空なら、候補の名称を登録しておく
                if not entry.get("product_name"):
                    name = (
                        sku_map[selected_text].get("商品名")
                        or sku_map[selected_text].get("product_name")
                        or sku_map[selected_text].get("title")
                        or ""
                    )
                    entry["product_name"] = name
                    name_item = self.registration_table.item(row, 4)
                    if name_item:
                        name_item.setText(name)
            else:
                # 直接入力されたとみなす
                sku = selected_text.split()[0] if selected_text else ""

        if not sku:
            QMessageBox.warning(self, "エラー", "有効なSKUが入力されませんでした。")
            return

        # registration_records と テーブルを更新
        entry["sku"] = sku
        sku_item = self.registration_table.item(row, 1)
        if sku_item:
            sku_item.setText(sku)
        else:
            self.registration_table.setItem(row, 1, QTableWidgetItem(sku))

        QMessageBox.information(
            self,
            "SKU変更",
            f"SKUを「{sku}」に変更しました。",
        )

    def _delete_and_slide_image_url(self, row: int, url_idx: int):
        """指定した画像URLを削除し、後続URLを前にスライド"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        
        # URLリストを5要素に揃える
        while len(entry["image_urls"]) < 5:
            entry["image_urls"].append("")
        
        # 指定インデックス以降を前にスライド
        for i in range(url_idx, 4):
            entry["image_urls"][i] = entry["image_urls"][i + 1]
        entry["image_urls"][4] = ""  # 最後は空に
        
        # テーブルUIを更新
        self._update_image_url_cells(row, entry)
    
    def _clear_image_url(self, row: int, url_idx: int):
        """指定した画像URLをクリア（スライドなし）"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        
        while len(entry["image_urls"]) <= url_idx:
            entry["image_urls"].append("")
        
        entry["image_urls"][url_idx] = ""
        
        # テーブルUIを更新
        self._update_image_url_cells(row, entry)
    
    def _update_image_url_cells(self, row: int, entry: Dict[str, Any]):
        """画像URL1～5のセルを更新"""
        col_offset = 11  # 画像URL1の列インデックス
        self.registration_table.blockSignals(True)
        try:
            for idx in range(5):
                col = col_offset + idx
                url = entry.get("image_urls", [])[idx] if idx < len(entry.get("image_urls", [])) else ""
                item = self.registration_table.item(row, col)
                if item:
                    item.setText(url)
                else:
                    item = QTableWidgetItem(url)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.registration_table.setItem(row, col, item)
        finally:
            self.registration_table.blockSignals(False)

    def _set_registration_preview(self, image_path: Optional[str]):
        """プレビュー画像の更新"""
        if not image_path:
            self.registration_preview_label.setText("画像を選択してください")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        file_path = Path(image_path)
        if not file_path.exists():
            self.registration_preview_label.setText("画像ファイルが見つかりません")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            self.registration_preview_label.setText("画像を読み込めませんでした")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        max_width = self.registration_preview_label.width() - 20
        max_height = self.registration_preview_label.height() - 20
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.registration_preview_label.setPixmap(scaled)
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setText("")

    def _set_registration_preview_url(self, url: str):
        """URL画像を下のプレビュー枠に表示（非同期・シグナル経由でメインスレッドに通知）"""
        url = (url or "").strip()
        if not url:
            self.registration_preview_label.setText("画像URLが空です")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        # よくある誤入力（https://...）を検出
        if url.endswith("...") or url.endswith("…") or url == "https://..." or url == "http://...":
            self.registration_preview_label.setText("画像URLが省略表示のままです（https://...）。\n実際のURLを入力してください。")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        self._registration_preview_pending_url = url
        self.registration_preview_label.setPixmap(QPixmap())
        self.registration_preview_label.setText("画像を読み込み中...")

        token = url

        def _fetch_and_emit():
            """バックグラウンドで画像取得してシグナルで通知"""
            try:
                req = Request(url, headers={"User-Agent": "HIRIO-DesktopApp/1.0"})
                with urlopen(req, timeout=15) as resp:
                    data = resp.read()
                self._preview_image_ready.emit(token, data)
            except HTTPError as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました（HTTP {e.code}）")
            except URLError as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました（通信エラー）\n{e}")
            except Exception as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました\n{e}")

        try:
            self._registration_preview_executor.submit(_fetch_and_emit)
        except Exception as e:
            self.registration_preview_label.setText(f"URLの読み込みに失敗しました:\n{e}")
            self.registration_preview_label.setPixmap(QPixmap())

    def _on_preview_image_ready(self, token: str, data: bytes):
        """シグナル受信: 画像データをプレビューに表示（メインスレッド）"""
        if token != self._registration_preview_pending_url:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.registration_preview_label.setText("画像を読み込めませんでした（形式不明）")
            self.registration_preview_label.setPixmap(QPixmap())
            return
        max_width = self.registration_preview_label.width() - 20
        max_height = self.registration_preview_label.height() - 20
        if max_width < 10:
            max_width = 400
        if max_height < 10:
            max_height = 200
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.registration_preview_label.setPixmap(scaled)
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setText("")

    def _on_preview_image_error(self, token: str, error_message: str):
        """シグナル受信: エラーメッセージを表示（メインスレッド）"""
        if token != self._registration_preview_pending_url:
            return
        self.registration_preview_label.setText(error_message)
        self.registration_preview_label.setPixmap(QPixmap())
    
    def upload_images_to_gcs(self):
        """選択行（未選択の場合は確認後に全行）の商品画像をGCSにアップロード"""
        return self._upload_images_to_gcs_impl(force_all=False)

    def upload_all_images_to_gcs(self):
        """全行の商品画像をGCSにアップロード"""
        return self._upload_images_to_gcs_impl(force_all=True)

    def _upload_images_to_gcs_impl(self, force_all: bool = False):
        """GCSアップロードの共通実装（force_all=Trueで全行）"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # 対象行を決定
        if force_all:
            selected_rows = set(range(len(self.registration_records)))
        else:
            # 選択行を取得（選択がない場合は確認して全行）
            selected_rows = set()
            for item in self.registration_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                reply = QMessageBox.question(
                    self,
                    "確認",
                    "選択された行がありません。全行の画像をアップロードしますか？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
                selected_rows = set(range(len(self.registration_records)))
        
        # GCSアップロードユーティリティのインポート
        import sys
        import os
        # python/utils/gcs_uploader.py へのパスを追加
        # このファイルは python/desktop/ui/ 配下なので、2つ上の python/ をsys.pathに追加する
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        python_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..'))
        
        # パス候補を複数試す（PyInstaller等で__file__が期待通りでない場合に対応）
        candidate_paths = [
            python_dir,  # 通常の開発環境
            os.path.join(python_dir, 'python'),  # プロジェクトルートから実行している場合
        ]
        
        # 実際にutils/gcs_uploader.pyが存在するパスを探す
        found_path = None
        try:
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break
            
            if found_path:
                # sys.pathの先頭を強制的にfound_pathに設定（他のコードが先頭を書き換えても確実にインポートできるように）
                # 既に存在する場合は削除してから先頭に追加
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                # さらに、sys.path[0]を強制的にfound_pathに設定（念のため）
                sys.path[0] = found_path
            elif python_dir:
                # found_pathが見つからない場合でも、python_dirを試す
                if python_dir in sys.path:
                    sys.path.remove(python_dir)
                sys.path.insert(0, python_dir)
                sys.path[0] = python_dir
            
            # インポート前にsys.pathの先頭を確認（デバッグ用）
            # logger.debug(f"Importing from sys.path[0]: {sys.path[0]}")
            
            # importlibを使って直接ファイルパスからインポート（sys.pathの問題を回避）
            if found_path:
                import importlib.util
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_file):
                    spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                    gcs_uploader_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(gcs_uploader_module)
                    upload_image_to_gcs = gcs_uploader_module.upload_image_to_gcs
                    GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                    check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                    find_existing_public_url_for_local_file = getattr(
                        gcs_uploader_module, "find_existing_public_url_for_local_file", None
                    )
                else:
                    raise ImportError(f"gcs_uploader.py not found at {gcs_uploader_file}")
            else:
                # フォールバック: 通常のインポートを試す
                from utils.gcs_uploader import upload_image_to_gcs, GCS_AVAILABLE, check_gcs_authentication
                try:
                    from utils.gcs_uploader import find_existing_public_url_for_local_file
                except Exception:
                    find_existing_public_url_for_local_file = None
            
            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self, "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。"
                )
                return
            
            # 認証確認
            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self, "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。"
                )
                return
        except ImportError as e:
            # デバッグ情報を収集
            debug_info = []
            debug_info.append(f"エラー: {str(e)}")
            debug_info.append(f"現在のファイル: {__file__}")
            debug_info.append(f"計算されたpython_dir: {python_dir}")
            debug_info.append(f"見つかったfound_path: {found_path if found_path else 'None'}")
            debug_info.append(f"試したパス候補:")
            for candidate in candidate_paths:
                gcs_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                exists = os.path.exists(gcs_path)
                debug_info.append(f"  - {candidate} (utils/gcs_uploader.py存在: {exists})")
            debug_info.append(f"sys.path[0] (インポート時に使用): {sys.path[0] if sys.path else '空'}")
            if found_path:
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                debug_info.append(f"importlibで使用するファイルパス: {gcs_uploader_file}")
                debug_info.append(f"ファイル存在確認: {os.path.exists(gcs_uploader_file)}")
            debug_info.append(f"sys.pathの先頭5件:")
            for i, path in enumerate(sys.path[:5]):
                marker = " ← これがインポート時に使用される" if i == 0 else ""
                debug_info.append(f"  {i+1}. {path}{marker}")
            
            QMessageBox.critical(
                self, "エラー",
                f"GCSアップロード機能の読み込みに失敗しました:\n\n{str(e)}\n\n"
                f"デバッグ情報:\n" + "\n".join(debug_info)
            )
            return
        
        # 進捗ダイアログ
        total_images = 0
        upload_tasks = []  # (row, entry, image_index, image_path)
        
        for row in selected_rows:
            if row >= len(self.registration_records):
                continue
            entry = self.registration_records[row]
            product_images = entry.get("product_images", [])
            
            for idx, image_path in enumerate(product_images):
                if image_path and Path(image_path).exists():
                    # 既にURLが設定されている場合はスキップ
                    existing_urls = entry.get("image_urls", [])
                    if idx < len(existing_urls) and existing_urls[idx]:
                        continue
                    upload_tasks.append((row, entry, idx, image_path))
                    total_images += 1
        
        if not upload_tasks:
            QMessageBox.information(
                self, "情報",
                "アップロード対象の画像がありません。\n"
                "（既にアップロード済み、または画像ファイルが見つかりません）"
            )
            return
        
        # 進捗ダイアログ
        progress = QProgressDialog("GCSに画像をアップロード中...", "キャンセル", 0, total_images, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        uploaded_count = 0
        failed_count = 0
        errors = []
        
        try:
            for row, entry, image_idx, image_path in upload_tasks:
                if progress.wasCanceled():
                    break
                
                progress.setValue(uploaded_count + failed_count)
                progress.setLabelText(f"アップロード中: {Path(image_path).name}")
                QApplication.processEvents()
                
                try:
                    # 既にGCSに存在する場合は、アップロードせずURLを設定（重複アップロード防止）
                    if find_existing_public_url_for_local_file:
                        try:
                            existing_url = find_existing_public_url_for_local_file(image_path)
                        except Exception:
                            existing_url = None
                        if existing_url:
                            public_url = existing_url
                        else:
                            public_url = upload_image_to_gcs(image_path)
                    else:
                    # GCSにアップロード
                        public_url = upload_image_to_gcs(image_path)
                    
                    # entryのimage_urlsを更新
                    if "image_urls" not in entry:
                        entry["image_urls"] = [""] * 5
                    while len(entry["image_urls"]) <= image_idx:
                        entry["image_urls"].append("")
                    entry["image_urls"][image_idx] = public_url
                    
                    # テーブルに反映
                    col_offset = 11  # URL1列の開始位置
                    col = col_offset + image_idx
                    if col < self.registration_table.columnCount():
                        item = self.registration_table.item(row, col)
                        if item:
                            item.setText(public_url)
                        else:
                            item = QTableWidgetItem(public_url)
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            self.registration_table.setItem(row, col, item)
                    
                    # 仕入DBの画像URLにも保存
                    try:
                        sku = entry.get("sku")
                        if sku:
                            from database.purchase_db import PurchaseDatabase
                            purchase_db = PurchaseDatabase()
                            purchase_record = purchase_db.get_by_sku(sku)
                            
                            if purchase_record:
                                # 既存レコードを更新
                                update_data = dict(purchase_record)
                                # image_idxは0始まりなので、image_url_1～6に保存（1始まりに変換）
                                image_url_key = f"image_url_{image_idx + 1}"
                                update_data[image_url_key] = public_url
                                purchase_db.upsert(update_data)
                                logger.info(f"Updated purchase DB image_url_{image_idx + 1} for SKU {sku}")
                            else:
                                # レコードが存在しない場合は新規作成（最小限の情報で）
                                new_data = {
                                    "sku": sku,
                                    f"image_url_{image_idx + 1}": public_url
                                }
                                purchase_db.upsert(new_data)
                                logger.info(f"Created new purchase DB record with image_url_{image_idx + 1} for SKU {sku}")
                    except Exception as e:
                        # 仕入DBへの保存に失敗してもアップロード処理は続行
                        logger.warning(f"Failed to update purchase DB for SKU {entry.get('sku', 'N/A')}: {e}")
                    
                    uploaded_count += 1
                    logger.info(f"Uploaded {image_path} -> {public_url}")
                
                except (ValueError, FileNotFoundError) as e:
                    # 認証エラーやファイルエラーの場合は処理を停止
                    failed_count += 1
                    error_msg = str(e)
                    errors.append(error_msg)
                    logger.error(f"Critical error during upload: {e}", exc_info=True)
                    
                    # 認証エラーの場合は即座に停止
                    if "認証エラー" in error_msg or "権限エラー" in error_msg or "authentication" in error_msg.lower():
                        progress.close()
                        QMessageBox.critical(
                            self, "認証エラー",
                            f"GCSへの認証に失敗しました。\n\n{error_msg}\n\n"
                            f"処理を中断しました。"
                        )
                        return
                
                except Exception as e:
                    failed_count += 1
                    error_msg = f"SKU {entry.get('sku', 'N/A')}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(f"Failed to upload {image_path}: {e}", exc_info=True)
            
            progress.setValue(total_images)
            
            # 仕入DBに保存
            try:
                from database.purchase_db import PurchaseDatabase
                purchase_db = PurchaseDatabase()
                
                for row in selected_rows:
                    if row >= len(self.registration_records):
                        continue
                    entry = self.registration_records[row]
                    sku = entry.get("sku")
                    if not sku:
                        continue
                    
                    # 仕入DBのレコードを取得
                    purchase_record = purchase_db.get_by_sku(sku)
                    if purchase_record:
                        # 画像URLを更新
                        update_data = {}
                        image_urls = entry.get("image_urls", [])
                        for i in range(5):
                            if i < len(image_urls) and image_urls[i]:
                                update_data[f"image_url_{i + 1}"] = image_urls[i]
                        
                        # バーコード画像URLも保存
                        if entry.get("barcode_image"):
                            # バーコード画像はアップロードしない（識別用のみ）
                            # 必要に応じてここでアップロードも可能
                            pass
                        
                        if update_data:
                            update_data["sku"] = sku
                            purchase_db.upsert(update_data)
                            logger.info(f"Updated purchase DB for SKU {sku} with image URLs")
            
            except Exception as e:
                logger.warning(f"Failed to save image URLs to purchase DB: {e}")
            
            # 結果表示
            result_msg = f"アップロード完了\n\n"
            result_msg += f"成功: {uploaded_count}件\n"
            if failed_count > 0:
                result_msg += f"失敗: {failed_count}件\n"
                if errors:
                    result_msg += "\nエラー詳細:\n" + "\n".join(errors[:5])
                    if len(errors) > 5:
                        result_msg += f"\n... 他 {len(errors) - 5}件"
            
            if failed_count > 0:
                QMessageBox.warning(self, "アップロード完了", result_msg)
            else:
                QMessageBox.information(self, "アップロード完了", result_msg)
        
        finally:
            progress.close()

    def check_existing_images_in_gcs(self):
        """GCSに既に存在する画像を検索して画像URL欄に反映（選択行/未選択なら全行）"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return

        # 対象行（選択がなければ全行）
        selected_rows = set()
        for item in self.registration_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            selected_rows = set(range(len(self.registration_records)))

        # gcs_uploaderを読み込む（uploadと同じパス解決）
        try:
            import sys
            import os
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            python_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..'))
            candidate_paths = [python_dir, os.path.join(python_dir, 'python')]

            found_path = None
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break

            if found_path:
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                sys.path[0] = found_path

                import importlib.util
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                gcs_uploader_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gcs_uploader_module)
                GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                find_existing_public_url_for_local_file = getattr(
                    gcs_uploader_module, "find_existing_public_url_for_local_file", None
                )
            else:
                from utils.gcs_uploader import GCS_AVAILABLE, check_gcs_authentication, find_existing_public_url_for_local_file

            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self, "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。"
                )
                return

            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self, "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。"
                )
                return
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"GCS存在チェック機能の初期化に失敗しました:\n{e}")
            return

        if not find_existing_public_url_for_local_file:
            QMessageBox.warning(self, "警告", "GCS存在チェック機能が利用できません（関数が見つかりません）。")
            return

        # 進捗
        tasks = []
        for row in sorted(selected_rows):
            if row >= len(self.registration_records):
                continue
            entry = self.registration_records[row]
            product_images = entry.get("product_images", [])
            existing_urls = entry.get("image_urls", []) if isinstance(entry.get("image_urls"), list) else []
            for idx, image_path in enumerate(product_images):
                if not image_path:
                    continue
                # URLが既に埋まっているならスキップ
                if idx < len(existing_urls) and existing_urls[idx]:
                    continue
                tasks.append((row, entry, idx, image_path))

        if not tasks:
            QMessageBox.information(self, "情報", "チェック対象がありません（既にURLが入っている、または画像がありません）。")
            return

        progress = QProgressDialog("GCSの既存画像を確認中...", "キャンセル", 0, len(tasks), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        found_count = 0
        try:
            from database.purchase_db import PurchaseDatabase
            purchase_db = PurchaseDatabase()

            for i, (row, entry, image_idx, image_path) in enumerate(tasks):
                if progress.wasCanceled():
                    break
                progress.setValue(i)
                progress.setLabelText(f"確認中: {Path(image_path).name}")
                QApplication.processEvents()

                url = find_existing_public_url_for_local_file(image_path)
                if not url:
                    continue

                # entry更新
                if "image_urls" not in entry:
                    entry["image_urls"] = [""] * 5
                while len(entry["image_urls"]) <= image_idx:
                    entry["image_urls"].append("")
                entry["image_urls"][image_idx] = url

                # テーブル反映（画像URL1～5は col_offset=11, +0..+4）
                col_offset = 11
                col = col_offset + image_idx
                if col < self.registration_table.columnCount():
                    self.registration_table.blockSignals(True)
                    try:
                        item = self.registration_table.item(row, col)
                        if item:
                            item.setText(url)
                        else:
                            item = QTableWidgetItem(url)
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            self.registration_table.setItem(row, col, item)
                    finally:
                        self.registration_table.blockSignals(False)

                # 仕入DBへ保存（SKUがあれば）
                sku = entry.get("sku")
                if sku:
                    try:
                        purchase_db.upsert({"sku": sku, f"image_url_{image_idx + 1}": url})
                    except Exception:
                        pass

                found_count += 1

        finally:
            progress.close()

        QMessageBox.information(self, "完了", f"GCS存在チェック完了：URL反映 {found_count} 件")

    def _show_remote_image_dialog(self, url: str):
        """URLの画像をダイアログ表示"""
        if not url:
            return
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read()
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                QMessageBox.warning(self, "エラー", f"画像を読み込めませんでした:\n{url}")
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("画像プレビュー")
            layout = QVBoxLayout(dialog)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)

            # 最大表示サイズ
            scaled = pixmap.scaled(1000, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled)
            dialog.resize(min(1100, scaled.width() + 40), min(900, scaled.height() + 60))
            dialog.exec()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"画像の取得に失敗しました:\n{url}\n\n{e}")
    
    def write_to_amazon_template(self):
        """AmazonテンプレートExcelファイルに商品データを書き込む"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # テーブルから最新のデータを取得
        products = []
        for row in range(self.registration_table.rowCount()):
            if row >= len(self.registration_records):
                continue
            
            entry = self.registration_records[row]
            
            # SKUを取得
            sku = entry.get("sku", "")
            if not sku:
                continue
            
            # 画像URLを取得（最大6枚まで）
            # GCSアップロード後のURLをエントリから取得
            image_urls = []
            
            # 1. image_urlsリスト形式を優先的に確認
            if 'image_urls' in entry and isinstance(entry.get('image_urls'), list):
                image_urls = [url for url in entry['image_urls'] if url]
            else:
                # 2. image_url_1～6の個別キー形式を確認
                for i in range(1, 7):  # 6枚まで取得
                    img_key = f'image_url_{i}'
                    img_url = entry.get(img_key, '')
                    if img_url:
                        image_urls.append(img_url)
            
            # 3. テーブルの画像URL列からも取得（画像URL1～5列、列15-19）
            for img_idx in range(5):  # 画像URL1～5
                col = 15 + img_idx  # 画像URL1列は15列目（0-indexed）
                item = self.registration_table.item(row, col)
                if item and item.text():
                    image_url = item.text().strip()
                    if image_url and image_url not in image_urls:
                        image_urls.append(image_url)
            
            # 商品データを作成（SKUと画像URLのみ）
            product = {
                "sku": sku,
            }
            
            # 画像URLを追加（最大6枚まで）
            if image_urls:
                product["image_urls"] = image_urls[:6]  # 最大6枚まで
            
            products.append(product)
        
        if not products:
            QMessageBox.warning(self, "警告", "有効な商品データがありません。")
            return
        
        # テンプレートファイルのパスを取得
        try:
            import sys
            import os
            from pathlib import Path
            
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
            from services.amazon_inventory_loader_service import AmazonInventoryLoaderService
            
            # テンプレートファイルのパス（設定から読み込む）
            template_path_str = self.template_file_edit.text().strip()
            if not template_path_str:
                QMessageBox.warning(
                    self, "警告",
                    "テンプレートファイルが指定されていません。\n"
                    "「参照...」ボタンからテンプレートファイルを選択してください。"
                )
                return
            
            template_path = Path(template_path_str)
            
            if not template_path.exists():
                QMessageBox.critical(
                    self, "エラー",
                    f"Amazonテンプレートファイルが見つかりません:\n{template_path}\n\n"
                    f"テンプレートファイルを配置してください。"
                )
                return
            
            # 出力ファイルの保存先を選択
            from datetime import datetime
            default_filename = f"ListingLoader_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsm"
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "AmazonテンプレートExcelファイルを保存",
                default_filename,
                "Excelマクロ有効ファイル (*.xlsm);;すべてのファイル (*)"
            )
            
            if not file_path:
                return  # ユーザーがキャンセル
            
            # テンプレートに書き込み
            output_path = AmazonInventoryLoaderService.write_to_amazon_template_excel(
                template_path=str(template_path),
                products=products,
                output_path=file_path,
                start_row=7
            )
            
            QMessageBox.information(
                self, "完了",
                f"AmazonテンプレートExcelファイルを保存しました:\n{output_path}\n\n"
                f"商品数: {len(products)}件\n\n"
                f"書き込まれたデータ:\n"
                f"  - SKU: A7列から\n"
                f"  - 画像URL: P7列から（1枚目）\n"
                f"  - 画像URL: Q7列から（2枚目）\n"
                f"  - 画像URL: R7列から（3枚目）\n"
                f"  - 画像URL: S7列から（4枚目）\n"
                f"  - 画像URL: T7列から（5枚目）\n"
                f"  - 画像URL: U7列から（6枚目）\n\n"
                f"👉 このファイルをAmazon Seller Centralにアップロードしてください。"
            )
        
        except Exception as e:
            logger.error(f"Failed to write to Amazon template Excel: {e}", exc_info=True)
            QMessageBox.critical(
                self, "エラー",
                f"AmazonテンプレートExcelファイルの書き込み中にエラーが発生しました:\n{str(e)}"
            )

    def browse_template_file(self):
        """テンプレートファイルを選択する"""
        settings = QSettings("HIRIO", "SedoriApp")
        last_dir = settings.value("amazon_template_last_dir", str(Path.home()))
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "AmazonテンプレートExcelファイルを選択",
            last_dir,
            "Excelマクロ有効ファイル (*.xlsm);;すべてのファイル (*)"
        )
        
        if file_path:
            template_path = Path(file_path)
            if template_path.exists():
                self.template_file_edit.setText(str(template_path))
                # 設定に保存
                self.save_template_file_setting(str(template_path))
                # 最後に開いたディレクトリを保存
                settings.setValue("amazon_template_last_dir", str(template_path.parent))
            else:
                QMessageBox.warning(
                    self, "警告",
                    f"選択したファイルが見つかりません:\n{file_path}"
                )
    
    def load_template_file_setting(self):
        """設定からテンプレートファイルパスを読み込む"""
        settings = QSettings("HIRIO", "SedoriApp")
        template_path = settings.value("amazon_template_file_path", "")
        
        if template_path:
            template_path_obj = Path(template_path)
            if template_path_obj.exists():
                self.template_file_edit.setText(template_path)
            else:
                # ファイルが存在しない場合は設定をクリア
                settings.remove("amazon_template_file_path")
                self.template_file_edit.clear()
        else:
            # デフォルトパスを試す
            default_path = Path(__file__).parent.parent.parent / "ListingLoader.xlsm"
            if default_path.exists():
                self.template_file_edit.setText(str(default_path))
                self.save_template_file_setting(str(default_path))
    
    def save_template_file_setting(self, template_path: str):
        """テンプレートファイルパスを設定に保存する"""
        settings = QSettings("HIRIO", "SedoriApp")
        settings.setValue("amazon_template_file_path", template_path)
        settings.sync()

    def open_amazon_upload_page(self):
        """Amazon Seller Centralの出品ファイルアップロードページをブラウザで開く"""
        amazon_url = "https://sellercentral-japan.amazon.com/product-search/bulk"
        try:
            QDesktopServices.openUrl(QUrl(amazon_url))
        except Exception as e:
            QMessageBox.critical(
                self, "エラー",
                f"ブラウザでAmazonアップロードページを開けませんでした:\n{str(e)}\n\n"
                f"手動で以下のURLにアクセスしてください:\n{amazon_url}"
            )

    def on_tree_context_menu(self, position):
        """ツリーのコンテキストメニュー"""
        item = self.tree_widget.itemAt(position)
        if not item:
            return

        menu = QMenu(self)

        group = item.data(0, Qt.UserRole)
        if isinstance(group, JanGroup):
            # JANグループが選択された
            # 仕入DB候補表示（画像日時に近い仕入レコードから手動で紐付け）
            link_action = menu.addAction("仕入DB候補を表示して紐付け")
            link_action.triggered.connect(lambda: self.show_purchase_candidates_for_group(group))

            # SKUを指定してこのグループの画像をリネーム
            rename_with_sku_action = menu.addAction("SKUを指定してこのJANグループの画像をリネーム")
            rename_with_sku_action.triggered.connect(lambda: self.rename_images_for_group_with_sku(group))

            menu.addSeparator()

            delete_action = menu.addAction("JANグループを削除")
            delete_action.triggered.connect(lambda: self.delete_jan_group(group))
        else:
            # 個別画像が選択された
            remove_action = menu.addAction("グループから削除")
            remove_action.triggered.connect(lambda: self.remove_image_from_group(item))

        menu.exec_(self.tree_widget.mapToGlobal(position))
    
    def on_image_list_context_menu(self, position):
        """画像リストのコンテキストメニュー"""
        item = self.image_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        delete_action = menu.addAction("画像を削除")
        delete_action.triggered.connect(lambda: self.delete_image_from_list(item))
        
        assign_menu = menu.addMenu("JANグループに追加")
        has_assignable = False
        image_path = item.data(Qt.UserRole)
        for group in self.jan_groups:
            if group.jan == "unknown":
                continue
            has_assignable = True
            title = self._get_product_title_by_jan(group.jan)
            label = f"{group.jan}"
            if title:
                label += f" - {title}"
            action = assign_menu.addAction(label)
            jan_value = group.jan
            action.triggered.connect(lambda _, j=jan_value, path=image_path: self.assign_image_to_jan(path, j, show_message=True))
        if not has_assignable:
            assign_menu.setEnabled(False)
        
        menu.exec_(self.image_list.mapToGlobal(position))

    def rename_images_for_group_with_sku(self, group: JanGroup):
        """
        指定したJANグループ内の画像を、ユーザーが入力したSKUベースでリネームする

        例: SKUが hmk-20251108-used2-029 の場合
            hmk-20251108-used2-029_1.jpg, hmk-20251108-used2-029_2.jpg, ...
        """
        if not group or not group.images:
            QMessageBox.information(self, "情報", "画像が含まれていないJANグループです。")
            return

        # まずJANコードから仕入DBのSKU候補を検索
        sku = ""
        candidates = []
        if group.jan and group.jan != "unknown":
            candidates = self._search_sku_candidates_by_jan(group.jan)

        if candidates:
            # 「SKU - 商品名」の形で候補リストを作成
            items = []
            sku_map: Dict[str, str] = {}
            for record in candidates:
                cand_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if not cand_sku:
                    continue
                name = (
                    record.get("商品名")
                    or record.get("product_name")
                    or record.get("title")
                    or ""
                )
                label = cand_sku if not name else f"{cand_sku} - {name}"
                if label not in sku_map:
                    items.append(label)
                    sku_map[label] = cand_sku

            if items:
                # QInputDialogインスタンスを使って、選択時の文字色が見えるように明示的にスタイルを指定
                dlg = QInputDialog(self)
                dlg.setWindowTitle("SKU指定リネーム")
                dlg.setLabelText("JANコードから見つかったSKU候補を選択するか、直接SKUを入力してください：")
                dlg.setComboBoxEditable(True)
                dlg.setComboBoxItems(items)
                # ダークテーマでも選択文字が見えるように白背景＋黒文字を強制
                dlg.setStyleSheet(
                    "QComboBox, QLineEdit, QListView {"
                    "  color: black;"
                    "  background-color: white;"
                    "}"
                    "QListView::item:selected {"
                    "  color: black;"
                    "  background-color: #cce4ff;"
                    "}"
                )

                if dlg.exec_() != QDialog.Accepted:
                    return

                selected_text = dlg.textValue().strip()
                if selected_text in sku_map:
                    sku = sku_map[selected_text]
                else:
                    # 「SKU - 商品名」形式でない場合は、先頭の単語をSKUとみなす
                    sku = selected_text.split()[0]
            else:
                # 候補があってもSKUが空なら手入力にフォールバック
                sku, ok = QInputDialog.getText(
                    self,
                    "SKU指定リネーム",
                    "このJANグループの画像に使用するSKUを入力してください：",
                )
                if not ok or not sku:
                    return
        else:
            # 候補がない場合はSKUを直接入力
            sku, ok = QInputDialog.getText(
                self,
                "SKU指定リネーム",
                "このJANグループの画像に使用するSKUを入力してください：",
            )
            if not ok or not sku:
                return

        sku = sku.strip()
        if not sku:
            QMessageBox.warning(self, "エラー", "SKUが入力されていません。")
            return

        reply = QMessageBox.question(
            self,
            "リネーム確認",
            f"JANグループ「{group.jan}」の画像を\nSKU「{sku}」ベースの名前にリネームしますか？\n"
            "（既にこのSKU名パターンでリネーム済みのファイルはスキップされます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 撮影日時順にソートしてリネーム順を決定
        sorted_images = sorted(group.images, key=lambda r: r.capture_dt if r.capture_dt else datetime.min)

        rename_operations: List[Tuple[ImageRecord, str]] = []
        for i, record in enumerate(sorted_images):
            original_path = Path(record.path)
            extension = original_path.suffix

            # 既にこのSKUパターンでリネーム済みならスキップ
            if re.match(f"^{re.escape(sku)}_\\d+{re.escape(extension)}$", original_path.name):
                continue

            new_name = f"{sku}_{i + 1}{extension}"
            new_path = original_path.parent / new_name
            if str(original_path) != str(new_path):
                rename_operations.append((record, str(new_path)))

        if not rename_operations:
            QMessageBox.information(self, "情報", "リネーム対象のファイルはありませんでした。")
            return

        # 実際のリネーム処理
        progress = QProgressDialog("リネーム処理中...", "キャンセル", 0, len(rename_operations), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        renamed_count = 0
        new_records_map: Dict[str, ImageRecord] = {}

        for i, (record, new_path_str) in enumerate(rename_operations):
            progress.setValue(i)
            if progress.wasCanceled():
                break

            old_path_str = record.path
            try:
                os.rename(old_path_str, new_path_str)

                # DBレコードを更新
                db_record = self.image_db.get_by_file_path(old_path_str)
                if db_record:
                    self.image_db.delete_by_file_path(old_path_str)
                    db_record["file_path"] = new_path_str
                    self.image_db.upsert(db_record)

                # メモリ上のレコードを差し替え
                new_record_data = record._asdict()
                new_record_data["path"] = new_path_str
                new_records_map[old_path_str] = ImageRecord(**new_record_data)

                renamed_count += 1
            except Exception as e:
                logger.error(f"SKU指定リネームエラー: {old_path_str} -> {new_path_str}: {e}")

        progress.close()

        # image_records を更新
        if new_records_map:
            updated_image_records: List[ImageRecord] = []
            for rec in self.image_records:
                if rec.path in new_records_map:
                    updated_image_records.append(new_records_map[rec.path])
                else:
                    updated_image_records.append(rec)
            self.image_records = updated_image_records

        # JANグループを再構築してUI反映
        self.jan_groups = self.image_service.group_by_jan(self.image_records)
        self.update_tree_widget()
        self.update_image_list(self.image_records)

        # 仕入DBへの紐付け処理
        linked_count = 0
        if self.product_widget and group.jan != "unknown":
            try:
                # リネーム後の新しい画像パスを取得（グループ内の全画像）
                updated_group = next((g for g in self.jan_groups if g.jan == group.jan), None)
                if updated_group:
                    # リネーム後の新しいパスを取得
                    new_image_paths = [img.path for img in updated_group.images]
                    
                    # 仕入DBの全レコードを取得
                    all_records = self.product_widget.get_all_purchase_records()
                    
                    # 指定したSKUのレコードに画像パスを紐付け
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        group.jan,
                        new_image_paths,
                        all_records,
                        skip_existing=False,  # 既存の画像を上書きする
                        target_sku=sku,
                    )
                    
                    if success and added_count > 0:
                        linked_count = added_count
                        # 画像登録タブに追加（Amazon画像更新ワークフロー用）
                        if record_snapshot:
                            self.add_registration_entry(record_snapshot)
            except Exception as e:
                logger.error(f"SKU指定リネーム後の紐付けエラー: {e}")
                # エラーが出てもリネームは成功しているので続行

        # 完了メッセージ
        message = f"{renamed_count}件の画像をSKU「{sku}」でリネームしました。"
        if linked_count > 0:
            message += f"\n仕入DBのSKU「{sku}」に{linked_count}件の画像を紐付けました。"
        QMessageBox.information(self, "完了", message)

    def show_purchase_candidates_for_group(self, group: JanGroup):
        """
        JANグループを右クリックしたときに、
        画像の撮影日時に近い仕入DBレコード候補を表示して手動で紐付ける
        """
        if not self.product_widget:
            QMessageBox.warning(self, "エラー", "仕入DBタブ（商品データベース）への参照がありません。")
            return

        if not group or not group.images:
            QMessageBox.information(self, "情報", "画像が含まれていないJANグループです。")
            return

        # グループ内の画像から代表となる撮影日時を決定（最も古いものを基準にする）
        capture_times: List[datetime] = []
        for record in group.images:
            if record.capture_dt:
                capture_times.append(record.capture_dt)
            else:
                # EXIF優先で取得できれば上書き
                exif_dt = self.image_service.get_exif_datetime(record.path)
                if exif_dt:
                    capture_times.append(exif_dt)

        if not capture_times:
            QMessageBox.warning(self, "エラー", "このJANグループの画像から撮影日時を取得できませんでした。")
            return

        base_dt = min(capture_times)

        # 画像撮影日時 ±7日以内の仕入DB候補を取得
        try:
            candidates = self.product_widget.find_purchase_candidates_by_datetime(base_dt, days_window=7)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"仕入DB候補の取得中にエラーが発生しました:\n{e}")
            return

        if not candidates:
            QMessageBox.information(
                self,
                "候補なし",
                "撮影日時付近の仕入データ候補が見つかりませんでした。\n"
                "（仕入DBの取り込み状況や日付を確認してください）",
            )
            return

        dialog = PurchaseCandidateDialog(group, base_dt, candidates, parent=self)
        if dialog.exec_() != QDialog.Accepted or not dialog.selected_record:
            return

        selected = dialog.selected_record
        target_jan = str(selected.get("JAN") or selected.get("jan") or "").strip()
        target_sku = str(selected.get("SKU") or selected.get("sku") or "").strip()

        if not target_jan:
            reply = QMessageBox.question(
                self,
                "確認",
                "選択した仕入レコードにはJANが設定されていません。\n"
                "それでもこのレコードに画像を紐付けますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        image_paths = [img.path for img in group.images]

        try:
            all_records = self.product_widget.get_all_purchase_records()
            # JANが空の場合でも一応処理を行う（update_image_paths_for_jan側で弾く可能性あり）
            success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                target_jan,
                image_paths,
                all_records,
                skip_existing=True,
                target_sku=target_sku or None,
            )
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"画像パスの紐付け中にエラーが発生しました:\n{e}")
            return

        if not success:
            QMessageBox.warning(
                self,
                "紐付け失敗",
                "選択したJANに対応する仕入レコードが見つかりませんでした。\n"
                "（仕入DB側のJANを確認してください）",
            )
            return

        if record_snapshot:
            # 画像登録タブに追加（Amazon画像更新ワークフロー用）
            self.add_registration_entry(record_snapshot)

        # 必要であればJANグループのJANを仕入DB側のJANに合わせる
        if target_jan and group.jan != target_jan:
            reply = QMessageBox.question(
                self,
                "JANグループJAN更新の確認",
                f"このJANグループのJANを仕入DBのJAN {target_jan} に更新しますか？\n"
                f"（グループ内の全画像が新しいJANで再グルーピングされます）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                for img_record in list(group.images):
                    self.assign_image_to_jan(img_record.path, target_jan)

        msg = "仕入DBレコードと画像グループを紐付けました。"
        if added_count > 0:
            msg += f"\n新しく登録された画像数: {added_count}枚"
        else:
            msg += "\nすべての画像は既に仕入DB側に登録済みでした。"

        QMessageBox.information(self, "完了", msg)
    
    def delete_jan_group(self, group: JanGroup):
        """JANグループを削除"""
        if group.jan == "unknown":
            QMessageBox.warning(self, "エラー", "JAN不明グループは削除できません。")
            return
        
        reply = QMessageBox.question(
            self,
            "確認",
            f"JANグループ {group.jan} を削除しますか？\n（画像は削除されず、JAN不明グループに移動します）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # グループ内の画像のJANコードをクリア
            jan_value = group.jan
            for record in group.images:
                # image_recordsを更新
                for i, r in enumerate(self.image_records):
                    if r.path == record.path:
                        updated_record = ImageRecord(
                            path=r.path,
                            capture_dt=r.capture_dt,
                            jan_candidate=None,
                            width=r.width,
                            height=r.height
                        )
                        self.image_records[i] = updated_record
                        break
                
                # DBを更新
                self.image_db.update_jan(record.path, None)
            
            # JANグループを再構築
            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            if jan_value:
                self._jan_title_cache.pop(jan_value, None)
            
            # UIを更新
            self.update_tree_widget()
            
            QMessageBox.information(self, "完了", f"JANグループ {group.jan} を削除しました。")
    
    def remove_image_from_group(self, item: QTreeWidgetItem):
        """画像をグループから削除"""
        image_path = item.data(0, Qt.UserRole)
        if not image_path:
            return
        
        # 画像レコードを取得
        image_record = next((r for r in self.image_records if r.path == image_path), None)
        if not image_record:
            return
        
        # JANコードをクリア
        original_jan = image_record.jan_candidate
        updated_record = ImageRecord(
            path=image_record.path,
            capture_dt=image_record.capture_dt,
            jan_candidate=None,
            width=image_record.width,
            height=image_record.height
        )
        
        # image_recordsを更新
        for i, record in enumerate(self.image_records):
            if record.path == image_path:
                self.image_records[i] = updated_record
                break
        
        # DBを更新
        self.image_db.update_jan(image_path, None)
        
        # JANグループを再構築
        self.jan_groups = self.image_service.group_by_jan(self.image_records)
        if original_jan:
            self._jan_title_cache.pop(original_jan, None)
        
        # UIを更新
        self.update_tree_widget()
        
        QMessageBox.information(self, "完了", "画像をグループから削除しました。")
    
    def delete_image_from_list(self, item: QListWidgetItem):
        """画像一覧から画像を削除（ファイルも削除）"""
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return

        file_name = Path(image_path).name
        reply = QMessageBox.question(
            self,
            "削除の確認",
            f"画像ファイル '{file_name}' を完全に削除しますか？\n\nこの操作は元に戻せません。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # 1. ファイルを物理的に削除
                if os.path.exists(image_path):
                    os.remove(image_path)

                # 2. データベースから削除
                self.image_db.delete_by_file_path(image_path)

                # 3. メモリ上のデータから削除
                record = next((r for r in self.image_records if r.path == image_path), None)
                original_jan = record.jan_candidate if record and record.jan_candidate else None
                self.image_records = [r for r in self.image_records if r.path != image_path]

                # 4. UIを更新
                self.jan_groups = self.image_service.group_by_jan(self.image_records)
                if original_jan:
                    self._jan_title_cache.pop(original_jan, None)

                self.update_tree_widget()
                self.update_image_list(self.image_records)

                # 5. 詳細パネルをクリア
                if self.selected_image_path == image_path:
                    self.selected_image_path = None
                    self.preview_label.setText("画像を選択してください")
                    self.jan_edit.clear()
                    self.capture_time_label.setText("-")
                    self.file_name_label.setText("-")
                    self.file_size_label.setText("-")
                    self.rotate_left_btn.setEnabled(False)
                    self.rotate_right_btn.setEnabled(False)
                    self.read_barcode_btn.setEnabled(False)
                    self.save_jan_btn.setEnabled(False)
                
                QMessageBox.information(self, "完了", f"画像 '{file_name}' を削除しました。")

            except Exception as e:
                QMessageBox.critical(self, "エラー", f"画像の削除中にエラーが発生しました:\n{str(e)}")

    def scan_unknown_jan_images(self):
        """JAN不明画像に対してOCRを実行し、候補を検索"""
        # JAN不明画像を抽出
        unknown_images = [
            r for r in self.image_records 
            if not r.jan_candidate or r.jan_candidate == "unknown" or not r.jan_candidate.isdigit()
        ]
        
        if not unknown_images:
            QMessageBox.information(self, "情報", "JAN不明な画像はありません。")
            return
        
        # OCRサービスの利用可能性チェック
        if not self.ocr_service.is_tesseract_available() and not self.ocr_service.is_gcv_available():
            QMessageBox.warning(
                self, 
                "OCR利用不可", 
                "OCR機能を使用するには、Tesseract OCRのインストールまたはGoogle Cloud Vision APIの設定が必要です。"
            )
            return

        # 仕入データの準備
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "情報", "照合対象の仕入データがありません。")
            return

        # 簡易インデックス作成（商品名をトークン化）
        product_index = []
        for p in purchase_records:
            jan = str(p.get("JAN") or p.get("jan") or "").strip()
            title = str(p.get("商品名") or p.get("product_name") or "").strip()
            if not jan or not title:
                continue
            
            # トークン化（簡易的）
            tokens = set(re.split(r'\s+', title.lower()))
            tokens = {t for t in tokens if len(t) > 1} # 1文字は除外
            product_index.append({
                "jan": jan,
                "title": title,
                "tokens": tokens
            })

        # プログレスダイアログ
        progress = QProgressDialog("JAN不明画像をOCR解析中...", "キャンセル", 0, len(unknown_images), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        candidates_map = {} # {image_path: {"ocr_text": str, "candidates": [...]}}
        
        for i, record in enumerate(unknown_images):
            if progress.wasCanceled():
                break
                
            progress.setValue(i)
            progress.setLabelText(f"OCR解析中... ({i+1}/{len(unknown_images)})")
            QApplication.processEvents()
            
            try:
                # OCR実行
                ocr_result = self.ocr_service.extract_text(record.path)
                text = ocr_result.get("text", "")
                
                if not text:
                    continue
                    
                # マッチング処理
                text_lower = text.lower()
                # OCRテキストからトークン抽出
                ocr_tokens = set(re.split(r'\s+|[^\w]+', text_lower))
                ocr_tokens = {t for t in ocr_tokens if len(t) > 2} # 2文字以下は除外（ノイズ対策）
                
                matches = []
                for prod in product_index:
                    # スコア計算: 共通トークン数
                    common = ocr_tokens.intersection(prod["tokens"])
                    if common:
                        # マッチしたトークンの数や割合でスコア化
                        score = len(common) * 10 # 基本点
                        # さらに、OCRテキスト全体に商品名が含まれているか（完全一致ボーナス）
                        # if prod["title"].lower() in text_lower:
                        #    score += 50
                        matches.append({
                            "jan": prod["jan"],
                            "title": prod["title"],
                            "score": score
                        })
                
                # スコア順にソートして上位を抽出
                matches.sort(key=lambda x: x["score"], reverse=True)
                top_matches = matches[:5] # 上位5件
                
                if top_matches and top_matches[0]["score"] >= 10: # 最低スコア閾値
                    candidates_map[record.path] = {
                        "ocr_text": text,
                        "candidates": top_matches
                    }
                    
            except Exception as e:
                logger.warning(f"OCR processing failed for {record.path}: {e}")
                continue
        
        progress.close()
        
        if not candidates_map:
            QMessageBox.information(self, "結果", "OCR解析を行いましたが、商品名と一致する候補は見つかりませんでした。")
            return
            
        # 結果表示ダイアログ
        dialog = CandidateSelectionDialog(candidates_map, self)
        if dialog.exec_() == QDialog.Accepted:
            selected = dialog.selected_results
            if not selected:
                return
                
            count = 0
            for image_path, jan in selected.items():
                if self.assign_image_to_jan(image_path, jan):
                    count += 1
            
            QMessageBox.information(self, "完了", f"{count}件の画像にJANコードを割り当てました。")

    def _close_progress_dialog(self):
        """プログレスダイアログを安全に閉じる"""
        if self.progress_dialog:
            try:
                self.progress_dialog.reset()
            except Exception:
                pass
            self.progress_dialog.close()
            self.progress_dialog = None

