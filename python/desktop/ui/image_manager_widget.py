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
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog
)
from PySide6.QtGui import QPixmap, QFont

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# デスクトップ側servicesを優先して読み込む
try:
    from services.image_service import ImageService, ImageRecord, JanGroup  # python/desktop/services
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.image_service import ImageService, ImageRecord, JanGroup

from database.image_db import ImageDatabase

logger = logging.getLogger(__name__)


class ImageLoadThread(QThread):
    """画像読み込みスレッド（大量画像対応）"""
    progress = Signal(int, int)  # 現在の進捗、総数
    finished = Signal(list)  # 読み込み完了
    
    def __init__(self, image_paths: List[str], max_size: int = 256):
        super().__init__()
        self.image_paths = image_paths
        self.max_size = max_size
        self.results = []
    
    def run(self):
        """画像を読み込んでサムネイルを生成"""
        total = len(self.image_paths)
        for i, path in enumerate(self.image_paths):
            try:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    # サイズ調整（最大256px）
                    if pixmap.width() > self.max_size or pixmap.height() > self.max_size:
                        pixmap = pixmap.scaled(
                            self.max_size, self.max_size,
                            Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                    self.results.append((path, pixmap))
            except Exception:
                pass
            
            self.progress.emit(i + 1, total)
        
        self.finished.emit(self.results)


class ImageManagerWidget(QWidget):
    """画像管理ウィジェット"""
    
    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.image_service = ImageService()
        self.image_db = ImageDatabase()
        self.product_widget = None  # ProductWidgetへの参照
        
        # データ
        self.current_directory = ""
        self.image_records: List[ImageRecord] = []
        self.jan_groups: List[JanGroup] = []
        self.selected_group: Optional[JanGroup] = None
        self.selected_image_path: Optional[str] = None
        
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
        layout = QVBoxLayout(self)
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
        
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_path_label, stretch=1)
        folder_layout.addWidget(self.select_folder_btn)
        folder_layout.addWidget(self.scan_btn)
        
        layout.addWidget(folder_group)
        
        # メインエリア：三分割レイアウト
        splitter = QSplitter(Qt.Horizontal)
        
        # 左：JANグループツリー
        left_group = QGroupBox("JANグループ")
        left_layout = QVBoxLayout(left_group)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("JANグループ")
        self.tree_widget.itemSelectionChanged.connect(self.on_tree_selection_changed)
        left_layout.addWidget(self.tree_widget)
        splitter.addWidget(left_group)
        
        # 中央：画像リスト
        center_group = QGroupBox("画像一覧（撮影時間順）")
        center_layout = QVBoxLayout(center_group)
        self.image_list = QListWidget()
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setIconSize(QSize(256, 256))
        self.image_list.setSpacing(10)
        self.image_list.itemClicked.connect(self.on_image_clicked)
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
        
        # 初期状態でボタンを無効化
        self.rotate_left_btn.setEnabled(False)
        self.rotate_right_btn.setEnabled(False)
        self.read_barcode_btn.setEnabled(False)
        self.save_jan_btn.setEnabled(False)
        
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
            self.save_last_directory()
    
    def scan_directory(self):
        """ディレクトリをスキャンして画像を取得"""
        if not self.current_directory:
            QMessageBox.warning(self, "エラー", "フォルダを選択してください。")
            return
        
        try:
            # プログレスダイアログを表示
            self.progress_dialog = QProgressDialog("画像をスキャン中...", "キャンセル", 0, 0, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.show()
            
            # スキャン実行（高速化のためEXIF・画像サイズ・バーコード読み取りをスキップ）
            self.image_records = self.image_service.scan_directory(
                self.current_directory, 
                skip_barcode_reading=True,
                skip_exif=True,  # EXIF読み取りをスキップ（ファイル更新日時を使用）
                skip_image_size=True  # 画像サイズ取得をスキップ（後で必要に応じて取得）
            )
            
            if not self.image_records:
                QMessageBox.information(self, "結果", "画像ファイルが見つかりませんでした。")
                self.progress_dialog.close()
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
            self.progress_dialog.close()
            
            # 全画像を一覧表示（遅延読み込み：スキャン完了後に非同期で実行）
            # 画像読み込みは重いので、まずスキャン完了を通知してから実行
            QMessageBox.information(
                self, "スキャン完了",
                f"{len(self.image_records)}件の画像をスキャンしました。\n"
                f"JANグループ数: {len(self.jan_groups)}"
            )
            
            # スキャン完了後、バックグラウンドで画像一覧を更新（ユーザーが待たない）
            self.update_image_list(self.image_records)
        except Exception as e:
            self.progress_dialog.close()
            QMessageBox.critical(self, "エラー", f"スキャン中にエラーが発生しました:\n{str(e)}")
    
    def update_tree_widget(self):
        """ツリービジェットを更新"""
        self.tree_widget.clear()
        
        for group in self.jan_groups:
            # 親ノード（JANグループ）
            jan_text = group.jan if group.jan != "unknown" else "（JAN不明）"
            parent_item = QTreeWidgetItem([f"{jan_text} ({len(group.images)}枚)"])
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
    
    def on_tree_selection_changed(self):
        """ツリー選択変更時の処理"""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        
        item = selected_items[0]
        group = item.data(0, Qt.UserRole)
        
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
        
        self.load_thread = ImageLoadThread(image_paths, max_size=256)
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
        for path, pixmap in results:
            item = QListWidgetItem(Path(path).name)
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
            
            # 選択された画像の撮影日時を取得
            if not selected_record.capture_dt:
                QMessageBox.warning(self, "エラー", "撮影日時が取得できませんでした。")
                return
            
            # DBを更新
            self.image_db.update_jan(self.selected_image_path, jan if jan else None)
            
            # 選択された画像のJANコードを更新
            selected_record = ImageRecord(
                path=selected_record.path,
                capture_dt=selected_record.capture_dt,
                jan_candidate=jan,
                width=selected_record.width,
                height=selected_record.height
            )
            
            # 4分以内に撮影された画像を検索して同じJANコードを付与
            time_window = 4 * 60  # 4分 = 240秒
            selected_time = selected_record.capture_dt
            
            updated_count = 0
            updated_records = []
            for record in self.image_records:
                if record.path == self.selected_image_path:
                    # 選択された画像を更新
                    updated_records.append(selected_record)
                    continue
                
                # 撮影日時が4分以内の画像を同じJANグループに追加
                if record.capture_dt:
                    time_diff = abs((record.capture_dt - selected_time).total_seconds())
                    if time_diff <= time_window:
                        # この画像も同じJANコードを付与
                        updated_record = ImageRecord(
                            path=record.path,
                            capture_dt=record.capture_dt,
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
            
            # UIを更新
            self.update_tree_widget()
            
            # JANコードでSKU候補を検索して提示
            sku_candidates = []
            if jan and self.product_widget:
                sku_candidates = self._search_sku_candidates_by_jan(jan)
            
            # メッセージ表示
            message = f"JANコードを保存しました。\n"
            if updated_count > 0:
                message += f"4分以内に撮影された{updated_count}件の画像を同じグループに追加しました。\n"
            
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

