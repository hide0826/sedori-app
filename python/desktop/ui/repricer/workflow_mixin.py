
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QTextEdit, QGroupBox, QSplitter, QApplication,
    QMessageBox, QFrame, QMenu, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from utils.error_handler import ErrorHandler, validate_csv_file, safe_execute
from utils.settings_helper import get_pricetar_repricing_url
try:
    from desktop.services.keepa_service import KeepaService
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore

from .support import (
    NumericTableWidgetItem,
    RepricerWorker,
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _REPRICER_ACTION_TO_PIPELINE_STEP,
    _REPRICER_WORKFLOW_PIPELINE_SEGMENTS,
    _REPRICER_WORKFLOW_PIPELINE_SEP,
    _format_repricer_status_prefix_html,
    _format_repricer_workflow_pipeline_html,
)


class RepricerWorkflowMixin:
    """価格改定ウィジェットの分割ミックスイン。"""

    def _sync_workflow_status_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑤ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_repricer_status_prefix_html(text, emph)
        pipe = _format_repricer_workflow_pipeline_html(step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)

    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """ワークフロー状態ラベルを更新"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "価格確認" in text:
            self._workflow_active_step = 3
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_status_label()

    def _run_action_with_status(self, action_name: str, action_func):
        """押したボタン名をワークフロー表示に反映してから処理を実行"""
        step = _REPRICER_ACTION_TO_PIPELINE_STEP.get(action_name)
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
