#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルート地図から Webテンプレート作成するダイアログ。

ルート選択画面に近い左右分割レイアウト。
開いた時点で Google マップを「再読込」相当で表示する。
"""
from __future__ import annotations

import html as html_lib
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDate, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None  # type: ignore
    WEBENGINE_AVAILABLE = False

try:
    from services.route_web_template_create import create_web_template
except Exception:
    from route_web_template_create import create_web_template  # type: ignore

try:
    from services.google_maps_route_url_service import generate_route_map_urls
except Exception:
    try:
        from google_maps_route_url_service import generate_route_map_urls  # type: ignore
    except Exception:
        generate_route_map_urls = None  # type: ignore

try:
    from services.google_maps_service import resolve_maps_api_key
except Exception:
    try:
        from google_maps_service import resolve_maps_api_key  # type: ignore
    except Exception:
        resolve_maps_api_key = None  # type: ignore


class WebTemplateFromMapDialog(QDialog):
    """ルート選択画面に近い構成で Webテンプレートを作成する。"""

    def __init__(
        self,
        parent=None,
        *,
        route_code: str,
        route_name: str,
        stores: List[Dict[str, Any]],
    ):
        super().__init__(parent)
        self.route_code = (route_code or "").strip()
        self.route_name = (route_name or "").strip() or self.route_code
        self.stores = list(stores or [])
        self._map_segments: List[Any] = []
        self._pending_map_segment = None
        self._last_load_was_embed = False
        self._embed_error_notified = False

        self.setWindowTitle("Webテンプレート作成")
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(
            """
            QDialog { background: #2b2b2b; color: #f0f0f0; }
            QGroupBox {
                border: 1px solid #555; margin-top: 10px; padding-top: 10px;
                color: #e0e0e0; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #e0e0e0; }
            QLineEdit, QDateEdit, QTextEdit, QComboBox, QTableWidget {
                background: #1e1e1e; color: #f0f0f0;
                border: 1px solid #555; padding: 4px; border-radius: 3px;
            }
            QHeaderView::section {
                background: #333; color: #eee; padding: 4px; border: 1px solid #555;
            }
            QPushButton {
                background: #2e7d32; color: white; border: none;
                padding: 6px 12px; border-radius: 4px;
            }
            QPushButton:hover:!disabled { background: #388e3c; }
            QPushButton:disabled { background: #424242; color: #9e9e9e; }
            QCheckBox { color: #e0e0e0; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self._build_left_panel()
        self._build_right_panel()
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([480, 780])

        # 開いたらすぐ地図を「再読込」相当で表示
        QTimer.singleShot(80, self._reload_map)

    # ------------------------------------------------------------------ UI
    def _build_left_panel(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)

        op = QGroupBox("操作")
        op_layout = QVBoxLayout(op)
        btn_row = QHBoxLayout()
        self.create_btn = QPushButton("Webテンプレート作成")
        self.create_btn.setStyleSheet(
            "QPushButton { background: #0d6efd; color: white; font-weight: bold;"
            " padding: 8px 14px; border-radius: 4px; }"
            "QPushButton:hover:!disabled { background: #0b5ed7; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
        )
        self.create_btn.setToolTip(
            "日付と訪問店舗で Webテンプレート（route.json 等）を作成します"
        )
        self.create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(self.create_btn)
        self.reverse_order_btn = QPushButton("訪問順序反転")
        self.reverse_order_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; padding: 8px 12px;"
            " border-radius: 4px; }"
            "QPushButton:hover:!disabled { background: #1e88e5; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
        )
        self.reverse_order_btn.setToolTip(
            "周回順を逆にします（スタート⇔ゴール）。\n"
            "高速道路の都合などで帰り道を先に回りたいときに使います。\n"
            "反転後、店舗一覧・地図・GoogleマップURLを更新します。"
        )
        self.reverse_order_btn.clicked.connect(self._reverse_visit_order)
        self.reverse_order_btn.setEnabled(len(self.stores) >= 2)
        btn_row.addWidget(self.reverse_order_btn)
        self.reload_map_btn = QPushButton("地図再読込")
        self.reload_map_btn.setToolTip("右の Google マップを、いまの店舗順で再表示します")
        self.reload_map_btn.clicked.connect(self._reload_map)
        btn_row.addWidget(self.reload_map_btn)
        btn_row.addStretch()
        op_layout.addLayout(btn_row)
        hint = QLabel(
            "右の地図は開いた時点で表示されます（ルート選択の「再読込」と同じ）。\n"
            "高速道路の都合などで逆回りにしたいときは「訪問順序反転」→内容確認→作成。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9e9e9e; font-weight: normal;")
        op_layout.addWidget(hint)
        left_layout.addWidget(op)

        info = QGroupBox("ルート情報")
        form = QFormLayout(info)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        form.addRow("ルート日付:", self.date_edit)

        self.code_edit = QLineEdit(self.route_code)
        self.code_edit.setReadOnly(True)
        form.addRow("ルートコード:", self.code_edit)

        self.name_edit = QLineEdit(self.route_name)
        self.name_edit.setReadOnly(True)
        form.addRow("ルート名:", self.name_edit)

        self.web_url1_edit, row1 = self._url_row("作成後に Web一覧URL が入る")
        form.addRow("生成ルート URL 1:", row1)
        self.web_url2_edit, row2 = self._url_row("作成後に個別URL が入る")
        form.addRow("生成ルート URL 2:", row2)
        self.gmap1_edit, grow1 = self._url_row("地図再読込で生成")
        form.addRow("Googleマップ URL 1:", grow1)
        self.gmap2_edit, grow2 = self._url_row("分割時の2本目")
        form.addRow("Googleマップ URL 2:", grow2)
        left_layout.addWidget(info)

        visit = QGroupBox("店舗訪問詳細（出力対象）")
        visit_layout = QVBoxLayout(visit)
        self.store_table = QTableWidget(0, 4)
        self.store_table.setHorizontalHeaderLabels(
            ["訪問順序", "店舗コード", "店舗名", "備考"]
        )
        self.store_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.store_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.store_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.store_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.store_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.store_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.store_table.setAlternatingRowColors(True)
        self._fill_store_table()
        visit_layout.addWidget(self.store_table, 1)
        count = QLabel(f"{len(self.stores)} 店（チェックON＝訪問する店）")
        count.setStyleSheet("color: #90caf9; font-weight: normal;")
        visit_layout.addWidget(count)
        left_layout.addWidget(visit, 1)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(110)
        self.log_edit.setPlaceholderText("作成結果がここに表示されます")
        left_layout.addWidget(self.log_edit)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_btn = QPushButton("閉じる")
        self.close_btn.setStyleSheet(
            "QPushButton { background: #546e7a; color: white; padding: 6px 16px;"
            " border-radius: 4px; }"
            "QPushButton:hover { background: #607d8b; }"
        )
        self.close_btn.clicked.connect(self.reject)
        close_row.addWidget(self.close_btn)
        left_layout.addLayout(close_row)

        self.splitter.addWidget(left)

    def _build_right_panel(self) -> None:
        right = QGroupBox("地図")
        right_layout = QVBoxLayout(right)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("表示ルート:"))
        self.map_segment_combo = QComboBox()
        self.map_segment_combo.setMinimumWidth(180)
        self.map_segment_combo.currentIndexChanged.connect(self._on_segment_changed)
        toolbar.addWidget(self.map_segment_combo)
        self.map_reload_btn = QPushButton("再読込")
        self.map_reload_btn.clicked.connect(self._reload_map)
        toolbar.addWidget(self.map_reload_btn)
        self.map_browser_btn = QPushButton("ブラウザで開く")
        self.map_browser_btn.setStyleSheet(
            "QPushButton { background: #0d6efd; color: white; padding: 6px 12px;"
            " border-radius: 4px; }"
            "QPushButton:hover:!disabled { background: #0b5ed7; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
        )
        self.map_browser_btn.setEnabled(False)
        self.map_browser_btn.clicked.connect(self._open_browser)
        toolbar.addWidget(self.map_browser_btn)

        self.map_embed_checkbox = QCheckBox("Embed API")
        self.map_embed_checkbox.setChecked(True)
        self.map_embed_checkbox.setToolTip(
            "ON: 設定タブの Google Maps APIキーで Embed 表示\n"
            "OFF: 通常の Google マップページを表示"
        )
        self.map_embed_checkbox.toggled.connect(self._on_embed_toggled)
        toolbar.addWidget(self.map_embed_checkbox)
        toolbar.addStretch()
        right_layout.addLayout(toolbar)

        self.segment_legend = QLabel("")
        self.segment_legend.setStyleSheet("color: #9e9e9e; font-weight: normal;")
        right_layout.addWidget(self.segment_legend)

        if WEBENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.map_view.loadFinished.connect(self._on_map_load_finished)
            self.map_view.setHtml(self._placeholder_html("地図を読み込み中…"))
            right_layout.addWidget(self.map_view, 1)
        else:
            self.map_view = None
            fallback = QLabel(
                "地図表示には PySide6-WebEngine が必要です。\n"
                "「ブラウザで開く」で Google マップを確認してください。"
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setWordWrap(True)
            fallback.setStyleSheet("color: #adb5bd;")
            right_layout.addWidget(fallback, 1)

        self.splitter.addWidget(right)

    def _url_row(self, placeholder: str):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setReadOnly(True)
        lay.addWidget(edit, 1)
        copy_btn = QPushButton("コピー")
        copy_btn.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; padding: 4px 10px;"
            " border-radius: 3px; }"
            "QPushButton:hover { background: #388e3c; }"
        )
        copy_btn.clicked.connect(lambda _=False, e=edit: self._copy_text(e.text()))
        lay.addWidget(copy_btn)
        return edit, row

    def _fill_store_table(self) -> None:
        self.store_table.setRowCount(len(self.stores))
        for i, store in enumerate(self.stores):
            code = str(store.get("store_code") or store.get("supplier_code") or "")
            name = str(store.get("store_name") or "")
            notes = str(store.get("notes") or "")
            order = store.get("visit_order")
            try:
                order_s = str(int(order)) if order is not None else str(i + 1)
            except (TypeError, ValueError):
                order_s = str(i + 1)
            for col, text in enumerate([order_s, code, name, notes]):
                item = QTableWidgetItem(text)
                self.store_table.setItem(i, col, item)

    def _reverse_visit_order(self) -> None:
        """訪問順を反転し、一覧・地図・URLを更新する。"""
        if len(self.stores) < 2:
            QMessageBox.information(
                self, "訪問順序反転", "反転する店舗が足りません（2店以上必要）。"
            )
            return
        self.stores = list(reversed(self.stores))
        for i, store in enumerate(self.stores, start=1):
            store["visit_order"] = i
        self._fill_store_table()
        self._reload_map()
        first = str(self.stores[0].get("store_name") or "")
        last = str(self.stores[-1].get("store_name") or "")
        self.log_edit.setPlainText(
            f"訪問順序を反転しました（{len(self.stores)}店）。\n"
            f"スタート: {first}\nゴール: {last}\n"
            "地図と Googleマップ URL を更新済みです。"
        )

    # ------------------------------------------------------------------ map
    def _placeholder_html(self, message: str) -> str:
        msg = html_lib.escape(message)
        return (
            "<html><body style='background:#2b2b2b;color:#adb5bd;padding:28px;"
            "font-family:Segoe UI,Meiryo,sans-serif;text-align:center;'>"
            f"<p style='margin-top:40px;'>{msg}</p></body></html>"
        )

    def _build_embed_html(self, embed_url: str) -> str:
        safe_src = html_lib.escape(embed_url, quote=True)
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;height:100%;width:100%;overflow:hidden;"
            "background:#1a1a1a;}"
            "iframe{border:0;width:100%;height:100%;display:block;}</style></head><body>"
            f"<iframe id='gmap' src='{safe_src}' allowfullscreen loading='lazy' "
            "referrerpolicy='no-referrer-when-downgrade'></iframe>"
            "</body></html>"
        )

    def _api_key(self) -> str:
        if resolve_maps_api_key is None:
            return ""
        try:
            return str(resolve_maps_api_key() or "").strip()
        except Exception:
            return ""

    def _reload_map(self) -> None:
        """ルート選択の『再読込』と同じ：店舗から Google マップ URL を生成して表示。"""
        if not self.stores:
            if self.map_view:
                self.map_view.setHtml(
                    self._placeholder_html("表示する店舗がありません（チェックONの店を確認）")
                )
            return
        if generate_route_map_urls is None:
            QMessageBox.warning(self, "エラー", "地図URL生成サービスを読み込めません。")
            return

        api_key = self._api_key()
        result = generate_route_map_urls(self.stores, api_key=api_key or None)
        self._map_segments = list(result.segments or [])

        self.map_segment_combo.blockSignals(True)
        self.map_segment_combo.clear()
        for seg in self._map_segments:
            label = f"ルート{seg.index}（{len(seg.store_codes)}地点）"
            self.map_segment_combo.addItem(label, seg.url)
        self.map_segment_combo.blockSignals(False)

        self.gmap1_edit.clear()
        self.gmap2_edit.clear()
        if self._map_segments:
            self.gmap1_edit.setText(self._map_segments[0].url or "")
        if len(self._map_segments) >= 2:
            self.gmap2_edit.setText(self._map_segments[1].url or "")

        if len(self._map_segments) > 1:
            self.segment_legend.setText(
                f"色分け: ルートが {len(self._map_segments)} 本に分割されています"
                "（上の「表示ルート」で切替）"
            )
        else:
            self.segment_legend.setText("")

        if not api_key and self.map_embed_checkbox.isChecked():
            self.segment_legend.setText(
                (self.segment_legend.text() + " ｜ " if self.segment_legend.text() else "")
                + "※ Embed には設定→API設定の Google Maps APIキーが必要です"
            )

        if self._map_segments:
            self.map_segment_combo.setCurrentIndex(0)
            self._apply_map_segment(0)
            self.map_browser_btn.setEnabled(True)
        else:
            self.map_browser_btn.setEnabled(False)
            if self.map_view:
                self.map_view.setHtml(
                    self._placeholder_html(
                        "ルート URL を生成できませんでした。\n店舗の緯度経度を確認してください。"
                    )
                )

        notes = []
        if result.skipped_duplicates:
            notes.append(
                f"同一地点まとめ: {len(result.skipped_duplicates)}件"
            )
        if result.missing_coordinates:
            notes.append(f"座標なし: {len(result.missing_coordinates)}件")
        if notes:
            self.log_edit.setPlainText("地図読込: " + " / ".join(notes))

    def _on_segment_changed(self, index: int) -> None:
        if index < 0:
            return
        self._apply_map_segment(index)

    def _on_embed_toggled(self, _checked: bool) -> None:
        idx = self.map_segment_combo.currentIndex()
        if idx >= 0:
            self._apply_map_segment(idx)

    def _apply_map_segment(self, index: int) -> None:
        if index < 0 or index >= len(self._map_segments):
            return
        seg = self._map_segments[index]
        self._load_map_for_segment(seg)
        self.map_browser_btn.setEnabled(bool(seg.url))

    def _load_map_for_segment(self, seg) -> None:
        if not self.map_view:
            return
        self._pending_map_segment = seg
        use_embed = self.map_embed_checkbox.isChecked()
        if use_embed and getattr(seg, "embed_url", ""):
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
        self.map_view.setHtml(self._placeholder_html("ルート URL を生成できませんでした。"))

    def _on_map_load_finished(self, ok: bool) -> None:
        if self._last_load_was_embed and self.map_embed_checkbox.isChecked():
            seg = self._pending_map_segment
            if not seg or not getattr(seg, "embed_url", ""):
                return

            def _check(text: str) -> None:
                if not text:
                    return
                lowered = text.lower()
                if (
                    "rejected" not in lowered
                    and "not activated" not in lowered
                    and "iframe" not in lowered
                ):
                    return
                self._fallback_legacy(seg)

            try:
                self.map_view.page().runJavaScript(
                    "document.body ? document.body.innerText : ''",
                    _check,
                )
            except Exception:
                pass
            return

        if not ok and not self._last_load_was_embed and self.map_view:
            self.map_view.setHtml(
                self._placeholder_html(
                    "埋め込み表示に失敗しました。\n"
                    "「ブラウザで開く」か「Embed API」ON＋APIキーを試してください。"
                )
            )

    def _fallback_legacy(self, seg) -> None:
        if not seg or not seg.url or not self.map_view:
            return
        self._last_load_was_embed = False
        self.map_view.load(QUrl(seg.url))
        if self._embed_error_notified:
            return
        self._embed_error_notified = True
        QMessageBox.warning(
            self,
            "Maps Embed API",
            "Embed 表示に失敗したため、従来表示に切り替えました。\n\n"
            "設定 → API設定 → Google Maps APIキー を確認し、\n"
            "Cloud Console で Maps Embed API を有効化してください。",
        )

    def _open_browser(self) -> None:
        idx = self.map_segment_combo.currentIndex()
        url = ""
        if 0 <= idx < len(self._map_segments):
            url = self._map_segments[idx].url or ""
        if not url:
            url = self.gmap1_edit.text().strip()
        if not url:
            QMessageBox.information(self, "Googleマップ", "開けるURLがありません。")
            return
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------ create
    def _copy_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        try:
            QGuiApplication.clipboard().setText(text)
        except Exception:
            pass

    def _qdate_to_date(self) -> date:
        qd = self.date_edit.date()
        return date(qd.year(), qd.month(), qd.day())

    def _on_create(self) -> None:
        if not self.stores:
            QMessageBox.warning(self, "警告", "出力する店舗がありません。")
            return
        self.create_btn.setEnabled(False)
        try:
            result = create_web_template(
                route_code=self.route_code,
                route_name=self.route_name,
                route_date=self._qdate_to_date(),
                stores=self.stores,
            )
        finally:
            self.create_btn.setEnabled(True)

        if not result.ok:
            QMessageBox.warning(
                self, "Webテンプレート作成", result.error or "失敗しました"
            )
            self.log_edit.setPlainText(result.error or "失敗")
            return

        self.web_url1_edit.setText(result.home_url or "")
        self.web_url2_edit.setText(result.route_url or "")
        if result.home_url:
            self._copy_text(result.home_url)
        self.log_edit.setPlainText(result.detail)

        warn = (not result.server_ok) or (not result.excel_ok) or (not result.insurance_dir)
        if warn:
            QMessageBox.warning(self, "Webテンプレート作成（要確認）", result.detail)
        else:
            QMessageBox.information(self, "Webテンプレート作成", result.detail)
