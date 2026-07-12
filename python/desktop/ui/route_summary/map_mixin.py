#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryMapMixin."""
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



class RouteSummaryMapMixin:
    def _create_route_url_row(self, placeholder: str):
        """URL 表示行（コピーボタン付き）"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        url_edit = QLineEdit()
        url_edit.setReadOnly(True)
        url_edit.setPlaceholderText(placeholder)
        copy_btn = QPushButton("コピー")
        copy_btn.setFixedWidth(56)
        copy_btn.setStyleSheet("padding: 2px 6px;")
        copy_btn.clicked.connect(lambda _checked=False, edit=url_edit: self._copy_route_url(edit))
        row_layout.addWidget(url_edit, 1)
        row_layout.addWidget(copy_btn)
        return row_widget, url_edit

    def _copy_route_url(self, url_edit: QLineEdit) -> None:
        """生成ルート URL をクリップボードにコピー"""
        text = url_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "警告", "コピーする URL がありません。")
            return
        QGuiApplication.clipboard().setText(text)

    def _update_route_url_fields(self) -> None:
        """生成済みセグメント URL をルート1・2欄に反映"""
        if not hasattr(self, "route_url_1_edit"):
            return
        url1 = self._map_route_segments[0].url if len(self._map_route_segments) >= 1 else ""
        url2 = self._map_route_segments[1].url if len(self._map_route_segments) >= 2 else ""
        self.route_url_1_edit.setText(url1)
        self.route_url_2_edit.setText(url2)

    def _create_map_panel(self) -> QGroupBox:
        """地図表示パネル（右半分・全高）"""
        map_group = QGroupBox("地図")
        map_layout = QVBoxLayout(map_group)
        map_layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("表示ルート:"))

        self.map_segment_combo = QComboBox()
        self.map_segment_combo.setMinimumWidth(140)
        self.map_segment_combo.currentIndexChanged.connect(self.on_map_segment_changed)
        toolbar.addWidget(self.map_segment_combo)

        self.map_reload_btn = QPushButton("再読込")
        self.map_reload_btn.setToolTip(
            "出力チェックが入った店舗を訪問順に読み込み、地図と URL を更新します。"
            "チェックのオン/オフを変えたあとに押してください。"
        )
        self.map_reload_btn.clicked.connect(
            lambda: self._run_workflow_action(4, lambda: self.generate_map_urls(silent=True))
        )
        self.map_reload_btn.setStyleSheet(
            "background-color: #28a745; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        toolbar.addWidget(self.map_reload_btn)

        self.map_browser_btn = QPushButton("ブラウザで開く")
        self.map_browser_btn.setToolTip("選択中のルートをブラウザで開きます")
        self.map_browser_btn.clicked.connect(self.open_map_in_browser)
        self.map_browser_btn.setEnabled(False)
        self.map_browser_btn.setStyleSheet(
            "background-color: #17a2b8; color: white; font-weight: bold; "
            "padding: 6px 14px; border-radius: 4px;"
        )
        toolbar.addWidget(self.map_browser_btn)

        self.map_embed_checkbox = QCheckBox("Embed API")
        self.map_embed_checkbox.setToolTip(
            "ON: Maps Embed API で地図のみ表示（要 API キー）\n"
            "Google Cloud Console で「Maps Embed API」を有効化してください。\n"
            "OFF: 従来の Google Maps ページ表示に戻します"
        )
        use_embed = self.settings.value("route_map/use_embed_display", False)
        if isinstance(use_embed, str):
            use_embed = use_embed.lower() in ("1", "true", "yes")
        self.map_embed_checkbox.setChecked(bool(use_embed))
        self.map_embed_checkbox.toggled.connect(self._on_embed_display_toggled)
        toolbar.addWidget(self.map_embed_checkbox)

        toolbar.addStretch()
        map_layout.addLayout(toolbar)

        if WEBENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setMinimumHeight(300)
            self.map_view.loadFinished.connect(self._on_map_view_load_finished)
            map_layout.addWidget(self.map_view, 1)
        else:
            self.map_view = None
            fallback = QLabel(
                "地図の埋め込み表示には PySide6-WebEngine が必要です。\n"
                "「再読込」後に「ブラウザで開く」をご利用ください。"
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setWordWrap(True)
            fallback.setStyleSheet("color: #adb5bd; padding: 16px;")
            map_layout.addWidget(fallback, 1)

        self._clear_map_display()
        return map_group

    def generate_map_urls(self, silent: bool = False) -> None:
        """出力チェック済み店舗から Google Maps ルート URL を生成"""
        if not generate_route_map_urls:
            QMessageBox.warning(self, "エラー", "地図URL生成サービスが読み込めません。")
            return

        stores = self.get_stores_from_table(for_template_output=True)
        if not stores:
            QMessageBox.warning(
                self,
                "警告",
                "出力チェックが入った店舗がありません。\n"
                "店舗訪問詳細の「出力」列にチェックを入れてから再度お試しください。",
            )
            return

        result = generate_route_map_urls(stores)
        self._map_route_segments = result.segments
        self._last_store_code_to_segment = dict(result.store_code_to_segment)

        self.map_segment_combo.blockSignals(True)
        self.map_segment_combo.clear()
        for seg in result.segments:
            label = f"ルート{seg.index}（{len(seg.store_codes)}店舗）"
            self.map_segment_combo.addItem(label, seg.url)
        self.map_segment_combo.blockSignals(False)

        self._update_route_url_fields()
        self._apply_visit_row_segment_colors(result.store_code_to_segment)
        self._update_segment_legend(len(result.segments))

        if result.segments:
            prev_index = self.map_segment_combo.currentIndex()
            target_index = prev_index if 0 <= prev_index < len(result.segments) else 0
            self.map_segment_combo.setCurrentIndex(target_index)
            self._apply_map_segment(target_index)
        else:
            self._clear_map_display()

        self.map_browser_btn.setEnabled(bool(result.segments))

        if silent:
            return

        info_lines = []
        if result.skipped_duplicates:
            dup_lines = [
                f"・{s.store_name}（{s.store_code}）→ {s.kept_store_name} と同一地点"
                for s in result.skipped_duplicates[:8]
            ]
            if len(result.skipped_duplicates) > 8:
                dup_lines.append(f"…他 {len(result.skipped_duplicates) - 8} 件")
            info_lines.append("【同一地点の店舗を1地点にまとめました】\n" + "\n".join(dup_lines))
        if result.missing_coordinates:
            missing_lines = [
                f"・{m['store_name']}（{m['store_code']}）"
                for m in result.missing_coordinates[:8]
            ]
            if len(result.missing_coordinates) > 8:
                missing_lines.append(f"…他 {len(result.missing_coordinates) - 8} 件")
            info_lines.append(
                "【座標未設定（住所または店舗名で代替）】\n"
                + "\n".join(missing_lines)
                + "\n\n店舗マスタの「経度緯度取得」で座標を登録すると精度が上がります。"
            )
        if info_lines:
            QMessageBox.information(self, "地図URL生成", "\n\n".join(info_lines))

    def _use_embed_map_display(self) -> bool:
        if hasattr(self, "map_embed_checkbox"):
            return self.map_embed_checkbox.isChecked()
        val = self.settings.value("route_map/use_embed_display", False)
        if isinstance(val, str):
            return val.lower() in ("1", "true", "yes")
        return bool(val)

    def _on_embed_display_toggled(self, checked: bool) -> None:
        self.settings.setValue("route_map/use_embed_display", checked)
        idx = self.map_segment_combo.currentIndex() if hasattr(self, "map_segment_combo") else -1
        if idx >= 0:
            self._apply_map_segment(idx)

    def _build_embed_html(self, embed_url: str) -> str:
        safe_src = html.escape(embed_url, quote=True)
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;height:100%;width:100%;overflow:hidden;"
            "background:#1a1a1a;}"
            "iframe{border:0;width:100%;height:100%;display:block;}</style></head><body>"
            f"<iframe id='gmap' src='{safe_src}' allowfullscreen loading='lazy' "
            "referrerpolicy='no-referrer-when-downgrade'></iframe>"
            "</body></html>"
        )

    def _load_map_for_segment(self, seg) -> None:
        """Embed API または従来 URL で地図を表示"""
        if not self.map_view:
            return
        self._pending_map_segment = seg
        use_embed = self._use_embed_map_display()
        if use_embed and seg.embed_url:
            self._last_load_was_embed = True
            self.map_view.setHtml(
                self._build_embed_html(seg.embed_url),
                QUrl("https://www.google.com/maps/"),
            )
            return
        self._last_load_was_embed = False
        if seg.url:
            self.map_view.load(QUrl(seg.url))
            return
        self.map_view.setHtml(
            "<html><body style='background:#2b2b2b;color:#ccc;padding:24px;font-family:sans-serif;'>"
            "ルート URL を生成できませんでした。"
            "</body></html>"
        )

    def _on_map_view_load_finished(self, _ok: bool) -> None:
        """Embed API エラー時は従来表示へ自動フォールバック"""
        if not self._last_load_was_embed or not self._use_embed_map_display():
            return
        seg = self._pending_map_segment
        if not seg or not seg.embed_url:
            return

        def _check_embed_error(text: str) -> None:
            if not text:
                return
            lowered = text.lower()
            if (
                "rejected" not in lowered
                and "not activated" not in lowered
                and "iframe" not in lowered
            ):
                return
            self._fallback_to_legacy_map(seg)

        try:
            self.map_view.page().runJavaScript(
                "document.body ? document.body.innerText : ''",
                _check_embed_error,
            )
        except Exception:
            pass

    def _fallback_to_legacy_map(self, seg) -> None:
        """Embed 失敗時に従来の /dir/ URL 表示へ切り替え"""
        if not seg or not seg.url or not self.map_view:
            return
        self._last_load_was_embed = False
        self.map_view.load(QUrl(seg.url))
        if self._embed_error_notified:
            return
        self._embed_error_notified = True
        QMessageBox.warning(
            self,
            "Maps Embed API エラー",
            "Embed API の表示に失敗したため、従来の地図表示に切り替えました。\n\n"
            "【Embed API を使う場合】\n"
            "1. 設定タブ → API設定 → 外部APIキー に「Google Maps APIキー」（HIRIO Maps Key）を入力\n"
            "2. Cloud Console で Maps Embed API / Places API (New) を有効化\n"
            "3. API キーの制限に Maps Embed API を含める\n\n"
            "【今すぐ地図を見るだけ】\n"
            "地図エリアの「Embed API」チェックを OFF にしてください。",
        )

    def _update_segment_legend(self, segment_count: int) -> None:
        if not hasattr(self, "route_segment_legend"):
            return
        if segment_count <= 1:
            self.route_segment_legend.setText("")
            return
        labels = ["ルート1（青）", "ルート2（緑）", "ルート3（黄）", "ルート4（赤）"]
        parts = [labels[i] if i < len(labels) else f"ルート{i + 1}" for i in range(segment_count)]
        self.route_segment_legend.setText("色分け: " + "  /  ".join(parts))

    def _apply_visit_row_segment_colors(self, store_code_to_segment: Dict[str, int]) -> None:
        """出力チェック済み行を分割ルートごとに色分け"""
        if not hasattr(self, "store_visits_table"):
            return
        table = self.store_visits_table
        default_brush = QBrush()
        for row in range(table.rowCount()):
            code_item = table.item(row, COL_STORE_CODE)
            code = code_item.text().strip() if code_item else ""
            seg_idx = None
            if code and _visit_include_checked(table, row):
                seg_idx = store_code_to_segment.get(code)
            brush = default_brush
            container_bg = ""
            if seg_idx:
                color = ROUTE_SEGMENT_ROW_COLORS[(seg_idx - 1) % len(ROUTE_SEGMENT_ROW_COLORS)]
                brush = QBrush(color)
                container_bg = (
                    f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, "
                    f"{max(color.alpha(), 30)});"
                )
            for col in VISIT_TABLE_VISIBLE_COLUMNS:
                item = table.item(row, col)
                if item:
                    item.setBackground(brush)
            container = table.cellWidget(row, COL_VISIT_INCLUDE)
            if container:
                container.setStyleSheet(container_bg)

    def _clear_visit_row_segment_colors(self) -> None:
        self._apply_visit_row_segment_colors({})

    def on_map_segment_changed(self, index: int) -> None:
        """分割ルート切替"""
        if index < 0:
            return
        self._apply_map_segment(index)

    def _apply_map_segment(self, index: int) -> None:
        """選択中セグメントを地図に反映"""
        if index < 0 or index >= len(self._map_route_segments):
            return
        seg = self._map_route_segments[index]
        self._load_map_for_segment(seg)
        if hasattr(self, "map_browser_btn"):
            self.map_browser_btn.setEnabled(bool(seg.url))

    def _clear_map_display(self) -> None:
        """地図・URL 表示をクリア"""
        if hasattr(self, "route_url_1_edit"):
            self.route_url_1_edit.clear()
        if hasattr(self, "route_url_2_edit"):
            self.route_url_2_edit.clear()
        if getattr(self, "map_browser_btn", None):
            self.map_browser_btn.setEnabled(False)
        map_view = getattr(self, "map_view", None)
        if map_view:
            map_view.setHtml(
                "<html><body style='background:#2b2b2b;color:#888;"
                "font-family:sans-serif;text-align:center;padding:48px 16px;'>"
                "「再読込」を押すと、チェック済み店舗のルートが表示されます"
                "</body></html>"
            )

    def _clear_map_route_segments(self) -> None:
        """生成済みルート URL をリセット"""
        self._map_route_segments = []
        self._last_store_code_to_segment = {}
        self._clear_visit_row_segment_colors()
        self._update_segment_legend(0)
        if hasattr(self, "map_segment_combo"):
            self.map_segment_combo.blockSignals(True)
            self.map_segment_combo.clear()
            self.map_segment_combo.blockSignals(False)
        self._clear_map_display()

    def open_map_in_browser(self) -> None:
        """選択中の Google Map URL をブラウザで開く"""
        url = ""
        if hasattr(self, "map_segment_combo") and self.map_segment_combo.currentIndex() >= 0:
            url = str(self.map_segment_combo.currentData() or "")
        if not url and hasattr(self, "route_url_1_edit"):
            url = self.route_url_1_edit.text().strip()
        if not url:
            QMessageBox.warning(
                self,
                "警告",
                "表示する Google Map URL がありません。\n先に「再読込」を実行してください。",
            )
            return
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"ブラウザで開くのに失敗しました:\n{str(e)}")

    def open_google_map_url_in_browser(self) -> None:
        """互換用: 地図横のブラウザで開くと同じ"""
        self.open_map_in_browser()

    def _sync_google_map_url_from_selected_route(self, route_name: Optional[str] = None) -> None:
        """ルート切替時に生成済み地図 URL をクリア（DB 保存 URL は使わない）"""
        self._clear_map_route_segments()

