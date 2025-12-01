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

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QMimeData, QUrl
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog,
    QInputDialog, QMenu, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget
)
from PySide6.QtGui import QPixmap, QFont, QDrag, QDropEvent, QImageReader, QImage, QDesktopServices, QCursor

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
        
        # 設定ファイルのパス
        self.config_path = Path(__file__).parent.parent.parent.parent / "config" / "inventory_settings.json"
        
        # スレッド
        self.load_thread: Optional[ImageLoadThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        
        self.setup_ui()
        self.load_last_directory()
    
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
        
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_path_label, stretch=1)
        folder_layout.addWidget(self.select_folder_btn)
        folder_layout.addWidget(self.scan_btn)
        folder_layout.addWidget(self.scan_unknown_btn)
        
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
            jan_text = group.jan if group.jan != "unknown" else "（JAN不明）"
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
                self.update_image_list(group.images, show_progress=True)
            else:
                # JAN不明グループの場合は全画像を表示
                self.update_image_list(self.image_records, show_progress=True)
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
                self.load_thread.terminate()
                self.load_thread.wait(3000)  # 最大3秒待つ
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
            
            # メッセージ表示
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

            sku_candidates = self._search_sku_candidates_by_jan(group.jan)
            if not sku_candidates or not (sku_candidates[0].get("SKU") or sku_candidates[0].get("sku")):
                failed_skus.add(group.jan)
                continue
            
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
                    # 更新処理を実行（既存画像はスキップ）
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        jan, image_paths, all_records, skip_existing=True
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
            "コンディション", "SKU", "ASIN", "商品名",
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
            # Amazon Lファイル用追加列
            "JAN", "販売価格", "在庫数", "コンディション番号", "コンディション説明",
            "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5"
        ]
        self.registration_table.setColumnCount(len(self.registration_columns))
        self.registration_table.setHorizontalHeaderLabels(self.registration_columns)
        self.registration_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        # 編集可能なカラムを設定（Amazon Lファイル用カラムのみ編集可能）
        self.registration_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
        self.registration_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.registration_table.setSelectionMode(QTableWidget.SingleSelection)
        self.registration_table.verticalHeader().setVisible(False)
        self.registration_table.setDragEnabled(True)
        self.registration_table.cellDoubleClicked.connect(self.on_registration_cell_double_clicked)
        self.registration_table.cellClicked.connect(self.on_registration_cell_clicked)
        self.registration_table.cellChanged.connect(self.on_registration_cell_changed)
        layout.addWidget(self.registration_table)

        preview_group = QGroupBox("プレビュー")
        preview_layout = QVBoxLayout(preview_group)
        self.registration_preview_label = QLabel("画像を選択してください")
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setMinimumHeight(200)
        self.registration_preview_label.setStyleSheet("border: 1px solid gray; background-color: #f8f8f8;")
        self.registration_preview_label.setScaledContents(False)
        preview_layout.addWidget(self.registration_preview_label)
        layout.addWidget(preview_group)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.clear_registration_btn = QPushButton("一覧をクリア")
        self.clear_registration_btn.clicked.connect(self.clear_registration_records)
        button_layout.addWidget(self.clear_registration_btn)
        self.upload_to_gcs_btn = QPushButton("GCSアップロード")
        self.upload_to_gcs_btn.clicked.connect(self.upload_images_to_gcs)
        button_layout.addWidget(self.upload_to_gcs_btn)
        # Lファイルではなく「TSVファイル生成」として表示
        self.generate_amazon_l_btn = QPushButton("Amazon TSVファイル生成")
        self.generate_amazon_l_btn.clicked.connect(self.generate_amazon_l_file)
        button_layout.addWidget(self.generate_amazon_l_btn)
        layout.addLayout(button_layout)

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
        
        # 仕入DBから画像URLを取得（既にアップロード済みの場合）
        if entry["sku"]:
            try:
                from database.purchase_db import PurchaseDatabase
                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(entry["sku"])
                if purchase_record:
                    for i in range(1, 6):
                        img_url = purchase_record.get(f"image_url_{i}")
                        if img_url:
                            entry["image_urls"].append(img_url)
            except Exception as e:
                logger.debug(f"Failed to get image URLs from purchase DB: {e}")

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
                entry.get("product_name", "")
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.registration_table.setItem(row, col, item)

            # 元の画像パス（既存カラム、表示用）
            for idx, image_path in enumerate(entry.get("images", [])):
                col = 4 + idx
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
            
            # Amazon Lファイル用追加カラム
            col_offset = 10  # 既存カラム数（コンディション、SKU、ASIN、商品名、画像1～6）
            # JAN
            col = col_offset
            item = QTableWidgetItem(entry.get("jan", ""))
            self.registration_table.setItem(row, col, item)
            # 販売価格（編集可能）
            col = col_offset + 1
            item = QTableWidgetItem(entry.get("price", ""))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.registration_table.setItem(row, col, item)
            # 在庫数（編集可能）
            col = col_offset + 2
            item = QTableWidgetItem(entry.get("quantity", "0"))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.registration_table.setItem(row, col, item)
            # コンディション番号（編集可能）
            col = col_offset + 3
            item = QTableWidgetItem(entry.get("condition_type", ""))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.registration_table.setItem(row, col, item)
            # コンディション説明（編集可能）
            col = col_offset + 4
            item = QTableWidgetItem(entry.get("condition_note", ""))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.registration_table.setItem(row, col, item)
            # 画像URL1～5（編集可能、GCSアップロード後のURL）
            for idx in range(5):
                col = col_offset + 5 + idx
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

    def on_registration_cell_double_clicked(self, row: int, column: int):
        """画像列ダブルクリックでファイルを開く"""
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
        if column < 4:
            self._set_registration_preview(None)
            return
        item = self.registration_table.item(row, column)
        if not item:
            self._set_registration_preview(None)
            return
        image_path = item.data(Qt.UserRole)
        self._set_registration_preview(image_path)
    
    def on_registration_cell_changed(self, row: int, column: int):
        """テーブルセル編集時にregistration_recordsを更新"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        item = self.registration_table.item(row, column)
        if not item:
            return
        
        col_offset = 10  # 既存カラム数
        
        # 編集可能なカラムのみ更新
        if column == col_offset:  # JAN
            entry["jan"] = item.text()
        elif column == col_offset + 1:  # 販売価格
            entry["price"] = item.text()
        elif column == col_offset + 2:  # 在庫数
            entry["quantity"] = item.text()
        elif column == col_offset + 3:  # コンディション番号
            entry["condition_type"] = item.text()
        elif column == col_offset + 4:  # コンディション説明
            entry["condition_note"] = item.text()
        elif col_offset + 5 <= column <= col_offset + 9:  # 画像URL1～5
            idx = column - (col_offset + 5)
            if "image_urls" not in entry:
                entry["image_urls"] = [""] * 5
            while len(entry["image_urls"]) <= idx:
                entry["image_urls"].append("")
            entry["image_urls"][idx] = item.text()

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
    
    def upload_images_to_gcs(self):
        """選択行の商品画像をGCSにアップロード"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # 選択行を取得（選択がない場合は全行）
        selected_rows = set()
        for item in self.registration_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            # 選択がない場合は全行を対象
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
        try:
            import sys
            import os
            # python/utils/gcs_uploader.py へのパスを追加
            python_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..')
            sys.path.insert(0, python_dir)
            from utils.gcs_uploader import upload_image_to_gcs, GCS_AVAILABLE, check_gcs_authentication
            
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
            QMessageBox.critical(
                self, "エラー",
                f"GCSアップロード機能の読み込みに失敗しました:\n{str(e)}"
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
                    # GCSにアップロード
                    public_url = upload_image_to_gcs(image_path)
                    
                    # entryのimage_urlsを更新
                    if "image_urls" not in entry:
                        entry["image_urls"] = [""] * 5
                    while len(entry["image_urls"]) <= image_idx:
                        entry["image_urls"].append("")
                    entry["image_urls"][image_idx] = public_url
                    
                    # テーブルに反映
                    col_offset = 10
                    col = col_offset + 5 + image_idx
                    if col < self.registration_table.columnCount():
                        item = self.registration_table.item(row, col)
                        if item:
                            item.setText(public_url)
                        else:
                            item = QTableWidgetItem(public_url)
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            self.registration_table.setItem(row, col, item)
                    
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
    
    def generate_amazon_l_file(self):
        """Amazon Lファイル（TSV）を生成・保存"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # テーブルから最新のデータを取得
        products = []
        for row in range(self.registration_table.rowCount()):
            if row >= len(self.registration_records):
                continue
            
            entry = self.registration_records[row]
            
            # テーブルから編集された値を取得
            col_offset = 10  # 既存カラム数
            jan = self.registration_table.item(row, col_offset).text() if self.registration_table.item(row, col_offset) else entry.get("jan", "")
            price = self.registration_table.item(row, col_offset + 1).text() if self.registration_table.item(row, col_offset + 1) else entry.get("price", "")
            quantity = self.registration_table.item(row, col_offset + 2).text() if self.registration_table.item(row, col_offset + 2) else entry.get("quantity", "0")
            condition_type = self.registration_table.item(row, col_offset + 3).text() if self.registration_table.item(row, col_offset + 3) else entry.get("condition_type", "")
            condition_note = self.registration_table.item(row, col_offset + 4).text() if self.registration_table.item(row, col_offset + 4) else entry.get("condition_note", "")
            
            # 画像URLを取得
            image_urls = []
            for idx in range(5):
                col = col_offset + 5 + idx
                item = self.registration_table.item(row, col)
                if item and item.text():
                    image_urls.append(item.text())
            
            # 必須フィールドチェック
            sku = entry.get("sku", "")
            asin = entry.get("asin", "")
            
            if not sku:
                continue
            
            if not asin and not jan:
                QMessageBox.warning(
                    self, "警告",
                    f"SKU {sku} にはASINまたはJANが必要です。"
                )
                continue

            # A案: 価格・在庫は空でもOK（Lファイルは画像だけ更新用途）
            # 空の場合はそのまま '' を渡し、Amazon側に「価格・在庫は更新しない」挙動を期待する
            if not price:
                price = ""
            if not quantity:
                quantity = ""
            
            if not condition_type:
                # コンディション文字列から変換を試みる
                condition_str = entry.get("condition", "")
                condition_map = {
                    "中古(ほぼ新品)": "1",
                    "中古(非常に良い)": "2",
                    "中古(良い)": "3",
                    "中古(可)": "4",
                    "新品(新品)": "11",
                    "新品": "11",
                }
                condition_type = condition_map.get(condition_str, "")
            
            if not condition_type:
                QMessageBox.warning(
                    self, "警告",
                    f"SKU {sku} にはコンディション番号が必要です。"
                )
                continue
            
            # 商品データを作成
            product = {
                "sku": sku,
                "asin": asin,
                "jan": jan,
                "price": price,
                "quantity": quantity,
                "condition_type": condition_type,
                "condition_note": condition_note,
            }
            
            # 画像URLを追加
            for idx, img_url in enumerate(image_urls):
                if img_url:
                    product[f"image_url_{idx + 1}"] = img_url
            
            products.append(product)
        
        if not products:
            QMessageBox.warning(self, "警告", "有効な商品データがありません。")
            return
        
        # TSV生成
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
            from services.amazon_inventory_loader_service import AmazonInventoryLoaderService
            
            tsv_bytes = AmazonInventoryLoaderService.generate_inventory_loader_tsv(products)
            
            if not tsv_bytes:
                QMessageBox.warning(self, "エラー", "TSVファイルの生成に失敗しました。")
                return
            
            # ファイル保存ダイアログ
            from datetime import datetime
            default_filename = f"amazon_inventory_loader_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tsv"
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Amazon TSVファイルを保存",
                default_filename,
                "TSVファイル (*.tsv);;すべてのファイル (*)"
            )
            
            if file_path:
                with open(file_path, 'wb') as f:
                    f.write(tsv_bytes)
                
                QMessageBox.information(
                    self, "完了",
                    f"Amazon TSVファイルを保存しました:\n{file_path}\n\n"
                    f"商品数: {len(products)}件"
                )
        
        except Exception as e:
            logger.error(f"Failed to generate Amazon L file: {e}", exc_info=True)
            QMessageBox.critical(
                self, "エラー",
                f"Amazon TSVファイルの生成中にエラーが発生しました:\n{str(e)}"
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

