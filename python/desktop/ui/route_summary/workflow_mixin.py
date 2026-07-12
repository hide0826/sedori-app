#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryWorkflowMixin."""
from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple
import html
import os
import sys
import re
import logging
import webbrowser
from functools import partial
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd
import openpyxl

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QDateTimeEdit, QLineEdit,
    QTextEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QDialog, QFormLayout, QDialogButtonBox, QTabWidget, QStyledItemDelegate, QStyle, QInputDialog,
    QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QDateTime, QTime, Signal, QSettings, QUrl
from PySide6.QtGui import QColor, QShortcut, QKeySequence, QDrag, QGuiApplication, QBrush

from ui.star_rating_widget import StarRatingWidget

from .support import (
    WEBENGINE_AVAILABLE,
    QWebEngineView,
    ROUTE_SEGMENT_ROW_COLORS,
    COL_VISIT_INCLUDE,
    COL_VISIT_ORDER,
    COL_STORE_CODE,
    COL_STORE_NAME,
    COL_IN_TIME,
    COL_OUT_TIME,
    COL_STAY,
    COL_TRAVEL,
    COL_PROFIT,
    COL_QTY,
    COL_STAR,
    COL_NOTES,
    VISIT_TABLE_VISIBLE_COLUMNS,
    _VISIT_TABLE_DEFAULT_WIDTHS,
    _ROUTE_WORKFLOW_PIPELINE_SEGMENTS,
    _ROUTE_WORKFLOW_PIPELINE_SEP,
    _format_route_workflow_prefix_html,
    _format_route_workflow_pipeline_html,
    _template_include_from_db_value,
    _visit_include_checked,
    SafeInternalMoveTable,
    StoreSelectDialog,
    SavedRoutesDialog,
    RouteDatabase,
    StoreDatabase,
    RouteVisitDatabase,
    attach_table_column_width_persistence,
    reapply_table_column_widths,
    RouteMatchingService,
    CalculationService,
    TemplateGenerator,
    generate_route_map_urls,
    resolve_maps_api_key,
)



class RouteSummaryWorkflowMixin:
    def _sync_workflow_guide_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑤ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_guide_label") or self.workflow_guide_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_route_workflow_prefix_html(text, emph)
        pipe = _format_route_workflow_pipeline_html(step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_guide_label.setText(prefix + sep + pipe)

    def _set_workflow_pipeline_highlight(self, step: Optional[int]) -> None:
        """手順（①〜⑤）のどれを強調するか。None で強調なし。"""
        self._workflow_active_step = step
        self._sync_workflow_guide_label()

    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        """ワークフロー状態ラベルを更新（手順リストと1行に結合）"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_guide_label()

    def _run_workflow_action(self, step: int, action_func):
        """押したボタンに対応する手順をハイライトしてから処理を実行"""
        try:
            self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)

