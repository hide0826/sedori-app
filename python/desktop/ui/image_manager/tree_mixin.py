#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JANツリー・グループ操作 mixin。"""
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


from .support import (
    ScanCancelledError,
    CandidateSelectionDialog,
    PurchaseCandidateDialog,
    JanGroupTreeWidget,
    ImageListWidget,
    RegistrationTableWidget,
    ImageLoadThread,
    _WORKFLOW_PIPELINE_SEGMENTS,
    _WORKFLOW_PIPELINE_SEP,
    _ACTION_TO_PIPELINE_STEP,
    _REGISTRATION_WORKFLOW_PIPELINE_SEGMENTS,
    _REGISTRATION_ACTION_TO_PIPELINE_STEP,
    _AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS,
    _UNLINKED_HIGHLIGHT_BG,
    _UNLINKED_HIGHLIGHT_FG,
    _PURCHASE_IMAGE_COLUMNS,
    _normalize_jan_for_match,
    _normalize_image_path,
    _record_has_any_image_paths,
    _apply_unlinked_item_style,
    _record_jan_matches_group,
    _candidate_is_known_linked_product,
    _candidate_should_highlight_in_dialog,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
)

class ImageManagerTreeMixin:
    def _group_image_paths(self, group: JanGroup) -> List[str]:
        return [img.path for img in (group.images or []) if img.path]


    def update_tree_widget(self):
        """ツリービジェットを更新"""
        self._ensure_product_widget_data_loaded()
        self._updating_tree_checks = True
        try:
            self.tree_widget.clear()

            purchase_records: Optional[List[Dict[str, Any]]] = None
            if self.product_widget:
                try:
                    purchase_records = self.product_widget.get_all_purchase_records()
                except Exception:
                    purchase_records = None

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
                needs_highlight = self._should_highlight_jan_group(group, purchase_records)
                if needs_highlight:
                    _apply_unlinked_item_style(parent_item)
                self.tree_widget.addTopLevelItem(parent_item)
                
                # 子ノード（各画像）
                for idx, record in enumerate(group.images):
                    file_name = Path(record.path).name
                    capture_text = record.capture_dt.strftime("%Y/%m/%d %H:%M:%S") if record.capture_dt else "（日時不明）"
                    child_item = QTreeWidgetItem([f"{file_name} - {capture_text}"])
                    # 各JANグループの1枚目画像にチェックボックスを表示（デフォルトは除外＝チェックON）
                    if idx == 0:
                        flag = self.first_image_flags.get(record.path, True)
                        child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        child_item.setCheckState(0, Qt.Checked if flag else Qt.Unchecked)
                        if not needs_highlight:
                            # テキストは白字にして見やすくする（要確認グループは黄色背景＋黒字）
                            child_item.setForeground(0, Qt.white)
                        # 状態を保存
                        self.first_image_flags[record.path] = flag
                    if needs_highlight:
                        _apply_unlinked_item_style(child_item)
                    child_item.setData(0, Qt.UserRole, record.path)
                    parent_item.addChild(child_item)
            
            self.tree_widget.expandAll()
        finally:
            self._updating_tree_checks = False
        has_valid_groups = any(g.jan != "unknown" for g in self.jan_groups)
        self.rename_btn.setEnabled(has_valid_groups)
        # 確定処理は全グループ対象のため、JAN付きグループが1つでもあれば有効にする
        # （ツリー再構築で選択が外れると on_tree_selection_changed だけでは ON にならない）
        can_confirm = any(g.jan != "unknown" and g.images for g in self.jan_groups)
        self.confirm_btn.setEnabled(can_confirm)


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
            self._clear_image_preview_panels()
            self.jan_edit.clear()
            self.capture_time_label.setText("-")
            self.file_name_label.setText("-")
            self.file_size_label.setText("-")
            self.selected_image_path = None
            
            # ボタンの状態を更新
            self.rename_btn.setEnabled(False)
            self.confirm_btn.setEnabled(False)

            self._update_workflow_status("ワークフロー: 未実行", emphasize=False)
            
            QMessageBox.information(self, "完了", "JANグループエリアの画像をクリアしました。")


    def on_tree_selection_changed(self):
        """ツリー選択変更時の処理"""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        
        item = selected_items[0]
        group = item.data(0, Qt.UserRole)
        
        is_valid_group = isinstance(group, JanGroup) and group.jan != "unknown"
        if not is_valid_group and item.parent():
            parent_group = item.parent().data(0, Qt.UserRole)
            is_valid_group = isinstance(parent_group, JanGroup) and parent_group.jan != "unknown"
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


    def on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """JANグループツリー内のチェックボックス変更時（1枚目を送る/送らない）"""
        if self._updating_tree_checks:
            return
        if not item:
            return
        # 親ノード（JANグループ名）は無視し、子ノード（画像行）のみ対象
        if not item.parent():
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return
        # True = 除外（送らない）、False = 送る
        self.first_image_flags[path] = (item.checkState(0) == Qt.Checked)


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


    def add_images_to_group(self, image_paths: List[str], target_item: QTreeWidgetItem):
        """複数画像をJANグループに一括追加（ドラッグアンドドロップ時）"""
        if not image_paths or not target_item:
            return
        
        # ターゲットアイテムからJANグループを取得
        group = target_item.data(0, Qt.UserRole)
        if isinstance(group, JanGroup):
            jan = group.jan
        else:
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
        
        success_count = 0
        for image_path in image_paths:
            if self.assign_image_to_jan(image_path, jan, show_message=False, refresh_tree=False):
                success_count += 1
        if success_count > 0:
            self.update_tree_widget()
            QMessageBox.information(self, "完了", f"{success_count}枚の画像をJANグループ {jan} に追加しました。")


    def assign_image_to_jan(self, image_path: str, jan: str, capture_dt: Optional[datetime] = None, show_message: bool = False, refresh_tree: bool = True) -> bool:
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
        if refresh_tree:
            self.update_tree_widget()
        
        if show_message:
            QMessageBox.information(self, "完了", f"画像をJANグループ {jan} に登録しました。")
        
        return True


    def _sorted_group_images(self, group: JanGroup) -> List[ImageRecord]:
        return sorted(
            group.images,
            key=lambda r: r.capture_dt if r.capture_dt else datetime.min,
        )


    def _collect_image_paths_for_group(self, group: JanGroup) -> List[str]:
        """確定処理で仕入DBへ保存する画像パス（1枚目除外設定を反映）。"""
        image_paths: List[str] = []
        sorted_images = self._sorted_group_images(group)
        for idx, img in enumerate(sorted_images):
            img_path = img.path
            if idx == 0 and self.first_image_flags.get(img_path, True):
                continue
            if not Path(img_path).exists():
                db_record = self.image_db.get_by_file_path(img_path)
                if db_record and db_record["file_path"] != img_path:
                    img_path = db_record["file_path"]
            image_paths.append(img_path)
        return image_paths


    def _is_group_first_image_excluded(self, group: JanGroup) -> bool:
        """JANグループ1枚目が「送信しない」チェックONか（デフォルトON＝バーコード用として除外）"""
        if not group or not group.images:
            return False
        return bool(self.first_image_flags.get(group.images[0].path, True))


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

            rerename_action = menu.addAction("このグループを再リネーム")
            rerename_action.setToolTip(
                "_1 画像削除などで _2 から始まっている場合、"
                "2枚目以降を _1, _2… に振り直します"
            )
            rerename_action.triggered.connect(lambda: self.rerename_images_for_group(group))

            menu.addSeparator()

            delete_action = menu.addAction("JANグループを削除")
            delete_action.triggered.connect(lambda: self.delete_jan_group(group))
        else:
            # 個別画像が選択された
            remove_action = menu.addAction("グループから削除")
            remove_action.triggered.connect(lambda: self.remove_image_from_group(item))

        menu.exec_(self.tree_widget.mapToGlobal(position))


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


