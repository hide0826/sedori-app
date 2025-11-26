#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
証憑管理ウィジェット

- レシート／保証書を統合管理
- レシートタブ: フォルダ選択→OCR→DB保存→仕入データとのマッチング補助
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QFileDialog, QTextEdit,
    QTabWidget, QMessageBox, QDialog, QDialogButtonBox, QScrollArea
)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ui.receipt_widget import ReceiptWidget
from ui.warranty_widget import WarrantyWidget
from database.route_visit_db import RouteVisitDatabase


IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp')


class ClickableLabel(QLabel):
    """ダブルクリック可能なラベル（サムネイル用）"""
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class EvidenceManagerWidget(QWidget):
    """証憑管理タブ"""

    def __init__(self, api_client=None, inventory_widget=None, product_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.product_widget = product_widget
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        self.receipt_panel = ReceiptBatchPanel(
            api_client=self.api_client,
            inventory_widget=self.inventory_widget,
            product_widget=self.product_widget,
        )
        self.tab_widget.addTab(self.receipt_panel, "レシート管理")

        # 既存保証書ウィジェットをそのままサブタブとして配置
        self.warranty_widget = WarrantyWidget(self.api_client)
        self.tab_widget.addTab(self.warranty_widget, "保証書管理")


class ReceiptBatchPanel(QWidget):
    """レシート一括処理パネル"""

    def __init__(self, api_client=None, inventory_widget=None, product_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.product_widget = product_widget
        self.current_folder: Optional[Path] = None
        self.ocr_queue: List[str] = []
        self.batch_running = False
        self.route_db = RouteVisitDatabase()
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # 左: フォルダ&ファイルリスト
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        folder_layout = QHBoxLayout()
        self.folder_btn = QPushButton("フォルダ選択")
        self.folder_btn.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_btn)
        folder_layout.addStretch()
        left_layout.addLayout(folder_layout)

        self.folder_label = QLabel("未選択")
        self.folder_label.setStyleSheet("color: #bbb;")
        left_layout.addWidget(self.folder_label)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selection_changed)
        self.file_list.itemDoubleClicked.connect(self.process_selected_receipt)
        left_layout.addWidget(self.file_list, 3)

        btn_layout = QHBoxLayout()
        self.process_btn = QPushButton("OCR処理")
        self.process_btn.clicked.connect(self.process_selected_receipt)
        btn_layout.addWidget(self.process_btn)

        self.batch_btn = QPushButton("全件OCR")
        self.batch_btn.clicked.connect(self.start_batch_processing)
        btn_layout.addWidget(self.batch_btn)
        left_layout.addLayout(btn_layout)

        # サムネイル表示エリア
        self.thumb_label = ClickableLabel("画像サムネイル")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setMinimumHeight(160)
        self.thumb_label.setStyleSheet("background-color: #202020; border: 1px solid #444; color: #888;")
        self.thumb_label.double_clicked.connect(self.on_thumb_double_clicked)
        left_layout.addWidget(self.thumb_label, 2)

        rotate_layout = QHBoxLayout()
        self.rotate_left_btn = QPushButton("⟲ 左回転")
        self.rotate_left_btn.clicked.connect(lambda: self.rotate_current_image(-90))
        rotate_layout.addWidget(self.rotate_left_btn)
        self.rotate_right_btn = QPushButton("右回転 ⟳")
        self.rotate_right_btn.clicked.connect(lambda: self.rotate_current_image(90))
        rotate_layout.addWidget(self.rotate_right_btn)
        rotate_layout.addStretch()
        left_layout.addLayout(rotate_layout)

        # ログエリア（小さめ）
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("処理ログがここに表示されます。")
        self.log_view.setFixedHeight(120)
        left_layout.addWidget(self.log_view)

        splitter.addWidget(left_widget)

        # 右: 既存レシートウィジェット
        self.receipt_widget = ReceiptWidget(self.api_client, inventory_widget=self.inventory_widget)
        self.receipt_widget.set_notifications_enabled(False)
        if self.product_widget:
            self.receipt_widget.set_product_widget(self.product_widget)
        # レイアウトをフラットに見せるためアップロードセクションを非表示
        if hasattr(self.receipt_widget, "upload_group"):
            self.receipt_widget.upload_group.hide()
        self.receipt_widget.receipt_processed.connect(self.on_receipt_processed)
        splitter.addWidget(self.receipt_widget)
        splitter.setStretchFactor(1, 3)

    # -------------------- フォルダ処理 --------------------
    def select_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "レシートフォルダを選択", str(self.current_folder or Path.home()))
        if directory:
            self.current_folder = Path(directory)
            self.folder_label.setText(str(self.current_folder))
            self.refresh_file_list()

    def refresh_file_list(self):
        self.file_list.clear()
        if not self.current_folder or not self.current_folder.exists():
            return
        files = sorted([p for p in self.current_folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS])
        for path in files:
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            self.file_list.addItem(item)
        self.append_log(f"{len(files)} 件の画像を読み込みました。")

    def on_file_selection_changed(self):
        path = self.get_selected_path()
        if not path:
            self.thumb_label.clear()
            self.thumb_label.setText("画像サムネイル")
            return
        from PySide6.QtGui import QPixmap
        pix = QPixmap(path)
        if pix.isNull():
            self.thumb_label.clear()
            self.thumb_label.setText("画像を読み込めませんでした")
            return
        scaled = pix.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setText("")

    def get_selected_path(self) -> Optional[str]:
        item = self.file_list.currentItem()
        if item:
            return item.data(Qt.UserRole)
        QMessageBox.information(self, "情報", "リストから画像を選択してください。")
        return None

    # -------------------- OCR処理 --------------------
    def process_selected_receipt(self):
        path = self.get_selected_path()
        if not path:
            return
        self.append_log(f"OCR開始: {path}")
        self.receipt_widget.process_image(path)

    def start_batch_processing(self):
        if not self.file_list.count():
            QMessageBox.information(self, "情報", "フォルダに画像がありません。")
            return
        self.ocr_queue = [
            self.file_list.item(i).data(Qt.UserRole)
            for i in range(self.file_list.count())
        ]
        if not self.ocr_queue:
            QMessageBox.information(self, "情報", "処理対象がありません。")
            return
        self.batch_running = True
        self.append_log(f"全件OCRを開始します（{len(self.ocr_queue)}件）")
        self.process_next_in_queue()

    def process_next_in_queue(self):
        if not self.ocr_queue:
            if self.batch_running:
                self.append_log("全件OCRが完了しました。")
            self.batch_running = False
            return
        next_path = self.ocr_queue.pop(0)
        self.append_log(f"[{len(self.ocr_queue)+1}件残り] {next_path} を処理中...")
        self.receipt_widget.process_image(next_path)

    # -------------------- OCR結果処理 --------------------
    def on_receipt_processed(self, receipt_data: dict):
        file_path = receipt_data.get("original_file_path") or receipt_data.get("file_path")
        self.append_log(f"OCR完了: {file_path}")
        self.apply_route_matching(receipt_data)
        if self.batch_running:
            # 次のキューを処理
            self.process_next_in_queue()

    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {message}")

    def on_thumb_double_clicked(self):
        """サムネイルをダブルクリックしたときに拡大画像を表示"""
        path = self.get_selected_path()
        if not path:
            return
        self.show_image_popup(path)

    def rotate_current_image(self, angle: int):
        """現在選択中の画像を回転して保存"""
        path = self.get_selected_path()
        if not path:
            return
        from PySide6.QtGui import QPixmap, QTransform
        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "警告", "画像を読み込めませんでした。")
            return
        transform = QTransform().rotate(angle)
        rotated = pix.transformed(transform, Qt.SmoothTransformation)
        if not rotated.save(path):
            QMessageBox.warning(self, "警告", "画像の保存に失敗しました。")
            return
        self.append_log(f"画像を回転しました: {Path(path).name} ({angle}°)")
        # サムネイルを更新
        scaled = rotated.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setText("")

    # -------------------- Route連携 --------------------
    def apply_route_matching(self, receipt_data: dict):
        purchase_date = receipt_data.get("purchase_date")
        purchase_time = receipt_data.get("purchase_time")
        if not purchase_date or not purchase_time:
            return
        try:
            receipt_dt = datetime.strptime(f"{purchase_date} {purchase_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return

        visits = self.route_db.list_route_visits(route_date=purchase_date)
        if not visits:
            return

        best_visit = None
        best_time = None
        for visit in visits:
            out_time = visit.get("store_out_time") or visit.get("store_in_time")
            if not out_time:
                continue
            try:
                visit_dt = datetime.strptime(out_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if visit_dt <= receipt_dt:
                if best_time is None or visit_dt > best_time:
                    best_time = visit_dt
                    best_visit = visit

        if not best_visit:
            return

        store_code = best_visit.get("store_code")
        store_items = best_visit.get("store_item_count")
        store_name = best_visit.get("store_name")

        if store_code:
            idx = self.receipt_widget.store_code_combo.findData(store_code)
            if idx >= 0:
                self.receipt_widget.store_code_combo.setCurrentIndex(idx)
                self.append_log(f"ルート照合: {store_code} ({store_name}) を自動選択")

        if store_items:
            self.receipt_widget.items_count_edit.setText(str(store_items))
            if self.receipt_widget.current_receipt_data is not None:
                self.receipt_widget.current_receipt_data["items_count"] = store_items
            self.append_log(f"ルート照合: 点数 {store_items} を入力")

    # -------------------- 画像ポップアップ --------------------
    def show_image_popup(self, path: str):
        image_file = Path(path)
        if not image_file.exists():
            QMessageBox.warning(self, "警告", f"画像ファイルが存在しません:\n{path}")
            return

        from PySide6.QtGui import QPixmap

        dialog = QDialog(self)
        dialog.setWindowTitle(str(image_file.name))

        pixmap = QPixmap(str(image_file))
        original_width = pixmap.width()
        original_height = pixmap.height()

        screen = dialog.screen().availableGeometry()
        max_dialog_width = int(screen.width() * 0.9)
        max_dialog_height = int(screen.height() * 0.9)

        if original_width > max_dialog_width or original_height > max_dialog_height:
            scaled_pixmap = pixmap.scaled(
                max_dialog_width, max_dialog_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            scaled_pixmap = pixmap

        dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
        dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)
        dialog.setMinimumSize(dialog_width, dialog_height)
        dialog.resize(dialog_width, dialog_height)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignCenter)

        image_label = QLabel()
        image_label.setPixmap(scaled_pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        scroll_area.setWidget(image_label)
        layout.addWidget(scroll_area)

        info_label = QLabel(f"画像サイズ: {original_width} x {original_height} px")
        info_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(info_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.close)
        layout.addWidget(button_box)

        # モデルレスで表示（他の操作をブロックしない）
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()


__all__ = ["EvidenceManagerWidget"]

