#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像管理サポート（定数・Dialog・Thread・ヘルパー）。"""
from __future__ import annotations

import sys
import os
import json
import re
import io
import uuid
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging
from html import escape
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QMimeData, QUrl, QSettings, QFileInfo
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog,
    QInputDialog, QMenu, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget, QSpinBox, QComboBox, QFrame, QFileIconProvider, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem,
)
from PySide6.QtGui import (
    QPixmap, QFont, QDrag, QDropEvent, QImageReader, QImage, QDesktopServices, QCursor,
    QColor, QBrush, QPainter,
)
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_flags_from_folder
from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget
from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front

try:
    from utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )
except ImportError:
    from desktop.utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )

try:
    from utils.settings_helper import get_amazon_inventory_loader_upload_url
except ImportError:
    from desktop.utils.settings_helper import (  # type: ignore
        get_amazon_inventory_loader_upload_url,
    )

try:
    from services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from services.ocr_service import OCRService
except Exception:
    from desktop.services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from desktop.services.ocr_service import OCRService

from database.image_db import ImageDatabase


# ファイル操作エリア直下の手順ラベル用（①〜⑤）。ハイライトは 1..5 / なしは None
_WORKFLOW_PIPELINE_SEGMENTS = [
    "①フォルダ選択",
    "②スキャン実行",
    "③画像紐付け調整（手動）",
    "④全画像リネーム",
    "⑤確定処理",
]
_WORKFLOW_PIPELINE_SEP = "\u2010"
_ACTION_TO_PIPELINE_STEP = {
    "フォルダ選択": 1,
    "スキャン実行": 2,
    "全画像リネーム": 4,
    "確定処理": 5,
}

# 画像登録タブ用ワークフロー（①〜④）
_REGISTRATION_WORKFLOW_PIPELINE_SEGMENTS = [
    "①GCS一括アップロード",
    "②DBに保存",
    "③amazon（出品ファイルL）テンプレートに書き込み",
    "④Amazonアップロードページを開く",
]
_REGISTRATION_ACTION_TO_PIPELINE_STEP = {
    "GCS一括アップロード": 1,
    "DBに保存": 2,
    "amazon（出品ファイルL）テンプレートに書き込み": 3,
    "Amazonアップロードページを開く": 4,
}

# Amazon Seller Central（出品ファイルアップロード）のブラウザタイトル検索用
_AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS = [
    "seller central",
    "セラーセントラル",
    "sellercentral",
    "amazon seller",
    "imaging",
    "画像",
    "アップロード",
    "出品ファイル",
]

# JAN不明グループ・仕入DB未紐付け候補行のハイライト色
_UNLINKED_HIGHLIGHT_BG = QColor("#ffc107")
_UNLINKED_HIGHLIGHT_FG = QColor("#1a1a1a")
_PURCHASE_IMAGE_COLUMNS = [f"画像{i}" for i in range(1, 7)]


def _normalize_jan_for_match(value: Any) -> str:
    jan = str(value or "").strip()
    if jan.endswith(".0"):
        jan = jan[:-2]
    return "".join(c for c in jan if c.isdigit()).upper()


def _normalize_image_path(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(str(path).strip()))


def _record_has_any_image_paths(record: Dict[str, Any], image_paths: set[str]) -> bool:
    if not record or not image_paths:
        return False
    for col in _PURCHASE_IMAGE_COLUMNS:
        val = str(record.get(col) or "").strip()
        if val and _normalize_image_path(val) in image_paths:
            return True
    return False


def _apply_unlinked_item_style(item: QTreeWidgetItem) -> None:
    brush_bg = QBrush(_UNLINKED_HIGHLIGHT_BG)
    brush_fg = QBrush(_UNLINKED_HIGHLIGHT_FG)
    for col in range(item.columnCount()):
        item.setBackground(col, brush_bg)
        item.setForeground(col, brush_fg)


def _record_jan_matches_group(record: Dict[str, Any], group_jan: str) -> bool:
    """仕入レコードのJANがJANグループのJANと一致するか"""
    if not group_jan or group_jan == "unknown":
        return False
    record_jan = _normalize_jan_for_match(
        record.get("JAN") or record.get("jan") or record.get("JANコード")
    )
    group_norm = _normalize_jan_for_match(group_jan)
    return bool(record_jan and group_norm and record_jan == group_norm)


def _candidate_is_known_linked_product(
    record: Dict[str, Any],
    linked_session_jans: set[str],
) -> bool:
    """
    画像一覧のJANグループで既にJAN+商品名が紐付いている商品か。
    （例: 4543112593023 - 天装戦隊ゴセイジャー… のようなグループ）
    """
    record_jan = _normalize_jan_for_match(
        record.get("JAN") or record.get("jan") or record.get("JANコード")
    )
    if not record_jan or record_jan not in linked_session_jans:
        return False
    title = str(
        record.get("商品名") or record.get("product_name") or record.get("title") or ""
    ).strip()
    return bool(title)


def _candidate_should_highlight_in_dialog(
    record: Dict[str, Any],
    linked_session_jans: set[str],
) -> bool:
    """仕入DB候補で黄色表示するか（既知の紐付け商品以外）"""
    return not _candidate_is_known_linked_product(record, linked_session_jans)


class _PurchaseCandidateItemDelegate(QStyledItemDelegate):
    """仕入DB候補テーブル専用。行ごとの黄色ハイライトをグローバルQSSに負けず描画する。"""

    _DEFAULT_BG = QColor("#2b2b2b")
    _DEFAULT_FG = QColor("#ffffff")
    _SELECTED_BG = QColor("#0078d4")
    _SELECTED_FG = QColor("#ffffff")

    def __init__(self, host: "PurchaseCandidateDialog", parent=None):
        super().__init__(parent)
        self._host = host

    def _row_should_highlight(self, row: int) -> bool:
        rows = getattr(self._host, "_highlight_candidate_rows", None)
        return row in rows if rows is not None else False

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        highlighted = self._row_should_highlight(index.row())

        if selected:
            painter.fillRect(rect, self._SELECTED_BG)
            text_color = self._SELECTED_FG
        elif highlighted:
            painter.fillRect(rect, _UNLINKED_HIGHLIGHT_BG)
            text_color = _UNLINKED_HIGHLIGHT_FG
        else:
            painter.fillRect(rect, self._DEFAULT_BG)
            text_color = self._DEFAULT_FG

        painter.setPen(text_color)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        elided = painter.fontMetrics().elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            max(0, rect.width() - 16),
        )
        painter.drawText(
            rect.adjusted(8, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided,
        )
        painter.restore()


def _format_status_prefix_html(text: str, emphasize: bool) -> str:
    """ワークフロー行の左側（手順リストより前）。"""
    if not emphasize:
        return f'<span style="color:#cccccc;">{escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{escape(text)}</span>'


def _format_workflow_pipeline_html(
    active_step: Optional[int],
    segments: Optional[List[str]] = None,
) -> str:
    segs = segments if segments is not None else _WORKFLOW_PIPELINE_SEGMENTS
    parts: List[str] = []
    for i, seg in enumerate(segs, start=1):
        esc = escape(seg)
        if active_step == i:
            parts.append(
                f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>'
            )
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _WORKFLOW_PIPELINE_SEP.join(parts)


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

    def __init__(
        self,
        jan_group: JanGroup,
        base_dt: datetime,
        candidates: List[Dict[str, Any]],
        group_image_paths: Optional[List[str]] = None,
        linked_session_jans: Optional[set[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.jan_group = jan_group
        self.base_dt = base_dt
        self.candidates = candidates
        self.group_image_paths = {
            _normalize_image_path(p) for p in (group_image_paths or []) if p
        }
        self.linked_session_jans = linked_session_jans or set()
        self.selected_record: Optional[Dict[str, Any]] = None
        self._highlight_candidate_rows: set[int] = set()
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
            f"基準日時: {self.base_dt.strftime('%Y/%m/%d %H:%M:%S')} 付近の仕入データ候補を表示しています。\n"
            "黄色の行は、画像一覧でJAN・商品名がまだ紐付いていない商品の候補です。"
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
        self.table.setAlternatingRowColors(False)
        self.table.setItemDelegate(_PurchaseCandidateItemDelegate(self, self.table))
        self.table.setStyleSheet(
            "QTableWidget {"
            "  background-color: #2b2b2b;"
            "  color: #ffffff;"
            "  gridline-color: #444444;"
            "  border: 1px solid #555555;"
            "  alternate-background-color: #2b2b2b;"
            "}"
            "QTableWidget::item {"
            "  padding: 4px 8px;"
            "  border: none;"
            "  background: transparent;"
            "  color: transparent;"
            "}"
            "QHeaderView::section {"
            "  background-color: #3c3c3c;"
            "  color: #ffffff;"
            "  border: 1px solid #555555;"
            "  padding: 4px 8px;"
            "}"
        )
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
        self._highlight_candidate_rows = set()
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

            if _candidate_should_highlight_in_dialog(record, self.linked_session_jans):
                self._highlight_candidate_rows.add(row)

            values = [diff, purchase_date, sku, asin, jan, title, store, price]
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == 5 and title:
                    item.setToolTip(title)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

            # 行全体に元レコードを紐付け
            self.table.item(row, 0).setData(Qt.UserRole, record)

        self.table.viewport().update()

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
        """ドロップイベント（複数画像の改行区切りテキストに対応）"""
        if event.mimeData().hasText():
            text = event.mimeData().text().strip()
            image_paths = [p.strip() for p in text.split("\n") if p.strip()]
            item = self.itemAt(event.pos())
            if item and self.parent_widget and image_paths:
                if len(image_paths) == 1:
                    self.parent_widget.add_image_to_group(image_paths[0], item)
                else:
                    self.parent_widget.add_images_to_group(image_paths, item)
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageListWidget(QListWidget):
    """画像リストウィジェット（ドラッグ対応）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent  # ImageManagerWidgetへの参照
    
    def startDrag(self, supportedActions):
        """ドラッグ開始時の処理（複数選択時は全選択画像のパスを渡す）"""
        items = self.selectedItems()
        if not items:
            return
        
        paths = []
        for item in items:
            image_path = item.data(Qt.UserRole)
            if image_path:
                paths.append(image_path)
        if not paths:
            return
        
        # MIMEデータを作成（複数パスは改行区切り）
        mime_data = QMimeData()
        mime_data.setText("\n".join(paths))
        
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


