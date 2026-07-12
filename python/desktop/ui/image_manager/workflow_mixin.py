#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ワークフロー表示 mixin。"""
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

class ImageManagerWorkflowMixin:
    def _sync_workflow_status_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑤ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_status_prefix_html(text, emph)
        pipe = _format_workflow_pipeline_html(step, _WORKFLOW_PIPELINE_SEGMENTS)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)


    def _mark_route_images_completed_for_folders(self, *folder_paths: str | Path) -> None:
        """フォルダ候補からルートサマリーの「画像」チェックをONにする（Lファイル書き込みと同様）。"""
        seen: set[str] = set()
        for raw in folder_paths:
            folder = str(raw or "").strip()
            if not folder or folder in seen:
                continue
            seen.add(folder)
            try:
                if mark_route_flags_from_folder(folder, images_completed=True):
                    return
            except Exception as e:
                logger.warning(f"画像フラグ更新エラー ({folder}): {e}")


    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """ワークフロー状態ラベルを更新（手順リストと1行に結合）"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "画像紐付け調整" in text:
            self._workflow_active_step = 3
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_status_label()


    def _run_action_with_status(self, action_name: str, action_func):
        """押したボタン名をワークフロー表示に反映してから処理を実行"""
        step = _ACTION_TO_PIPELINE_STEP.get(action_name)
        self._workflow_post_step = None
        try:
            if step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            post_step = getattr(self, "_workflow_post_step", None)
            if post_step is not None:
                self._workflow_active_step = post_step
                self._workflow_post_step = None
            elif step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)


    def _sync_registration_workflow_status_label(self) -> None:
        """画像登録タブ: ワークフロー行を更新"""
        if not hasattr(self, "registration_workflow_status_label"):
            return
        if self.registration_workflow_status_label is None:
            return
        text = getattr(self, "_registration_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_registration_workflow_emphasize", False)
        step = getattr(self, "_registration_workflow_active_step", None)
        prefix = _format_status_prefix_html(text, emph)
        pipe = _format_workflow_pipeline_html(step, _REGISTRATION_WORKFLOW_PIPELINE_SEGMENTS)
        sep = '<span style="color:#cccccc;">　</span>'
        self.registration_workflow_status_label.setText(prefix + sep + pipe)


    def _update_registration_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """画像登録タブのワークフロー状態を更新"""
        self._registration_workflow_status_text = text
        self._registration_workflow_emphasize = emphasize
        if text.strip() == "ワークフロー: 未実行":
            self._registration_workflow_active_step = None
        self._sync_registration_workflow_status_label()


    def _run_registration_action_with_status(self, action_name: str, action_func):
        """画像登録タブ: ボタン操作をワークフロー表示に反映してから実行"""
        step = _REGISTRATION_ACTION_TO_PIPELINE_STEP.get(action_name)
        try:
            if step is not None:
                self._registration_workflow_active_step = step
            self._update_registration_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            if step is not None:
                self._registration_workflow_active_step = step
            self._update_registration_workflow_status("ワークフロー: 待機", emphasize=False)


    def _reset_image_manager_folder_state(self) -> None:
        """画像管理タブ表示時にフォルダ選択状態を初期化（前回パスは残さない）"""
        self.current_directory = ""
        if hasattr(self, "folder_path_label"):
            self.folder_path_label.setText("（未選択）")
        if hasattr(self, "scan_btn"):
            self.scan_btn.setEnabled(False)
        if hasattr(self, "scan_unknown_btn"):
            self.scan_unknown_btn.setEnabled(False)


    def _on_inner_tab_changed(self, index: int) -> None:
        """サブタブ「画像管理」を開いたときにフォルダ情報をクリア"""
        if index == 0:
            self._reset_image_manager_folder_state()


