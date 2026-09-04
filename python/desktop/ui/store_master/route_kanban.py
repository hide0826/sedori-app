#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ・ルート一覧カンバン（DnD でルート組み換え）。"""

from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray, QTimer, QPoint
from PySide6.QtGui import QDrag, QColor, QBrush, QCursor, QShortcut, QKeySequence

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from services.store_route_membership_service import (
    UNASSIGNED_COLUMN_KEY,
    add_store_to_route,
    build_kanban_columns_data,
    is_primary_in_route,
    move_store_to_route,
    remove_store_from_route,
    reorder_route_stores,
    store_code_from_store,
    store_in_route,
)
from .store_dialogs import StoreEditDialog

KANBAN_MIME_TYPE = "application/x-hirio-route-kanban"
COLUMN_MIME_TYPE = "application/x-hirio-route-kanban-column"
COLUMNS_PER_ROW = 6
COLUMN_MIN_HEIGHT = 340
AUTO_SCROLL_MARGIN_PX = 56
AUTO_SCROLL_STEP_PX = 18
AUTO_SCROLL_INTERVAL_MS = 16
MAX_UNDO_HISTORY = 40


def _encode_drag_payload(payload: Dict[str, Any]) -> QByteArray:
    return QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _decode_drag_payload(raw: QByteArray) -> Optional[Dict[str, Any]]:
    if raw is None or raw.isEmpty():
        return None
    try:
        return json.loads(bytes(raw).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class MoveToRouteDialog(QDialog):
    """右クリックメニュー用: 移動先ルート選択。"""

    def __init__(
        self,
        routes: List[Dict[str, Any]],
        *,
        exclude_route_code: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("ルートへ移動")
        self._selected_route: Optional[Dict[str, str]] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.route_combo = QComboBox()
        self.route_combo.addItem("（選択してください）", None)
        exclude = (exclude_route_code or "").strip()
        for route in routes:
            code = (route.get("route_code") or "").strip()
            name = (route.get("route_name") or "").strip()
            if not code or code == exclude:
                continue
            label = f"{name or code} ({code})"
            self.route_combo.addItem(
                label,
                {"route_name": name, "route_code": code},
            )
        form.addRow("移動先ルート:", self.route_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_route(self) -> Optional[Dict[str, str]]:
        return self._selected_route

    def accept(self) -> None:
        data = self.route_combo.currentData()
        if not data:
            QMessageBox.warning(self, "警告", "移動先ルートを選択してください。")
            return
        self._selected_route = data
        super().accept()


class RouteKanbanColumnList(QListWidget):
    """カンバン1列の店舗リスト（列内・列間 DnD）。"""

    internal_order_changed = Signal(object)

    def __init__(
        self,
        kanban: "RouteKanbanWidget",
        column_key: str,
        route_name: str = "",
        route_code: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.kanban = kanban
        self.column_key = column_key
        self.route_name = route_name
        self.route_code = route_code
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        store = item.data(Qt.UserRole)
        if not store or not store.get("id"):
            return

        payload = {
            "store_id": int(store["id"]),
            "source_column_key": self.column_key,
            "source_route_name": self.route_name,
            "source_route_code": self.route_code,
            "source_is_primary": bool(item.data(Qt.UserRole + 1)),
        }
        mime = QMimeData()
        mime.setData(KANBAN_MIME_TYPE, _encode_drag_payload(payload))

        drag = QDrag(self)
        drag.setMimeData(mime)
        self.kanban.begin_drag_scroll()
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.kanban.end_drag_scroll()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(KANBAN_MIME_TYPE):
            event.acceptProposedAction()
            self.kanban.auto_scroll_at_global_pos()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(KANBAN_MIME_TYPE):
            event.acceptProposedAction()
            self.kanban.auto_scroll_at_global_pos()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(KANBAN_MIME_TYPE):
            super().dropEvent(event)
            return

        payload = _decode_drag_payload(event.mimeData().data(KANBAN_MIME_TYPE))
        if not payload:
            event.ignore()
            return

        source_widget = event.source()
        same_column = isinstance(source_widget, RouteKanbanColumnList) and (
            source_widget.column_key == self.column_key
        )

        if same_column:
            super().dropEvent(event)
            event.acceptProposedAction()
            self.internal_order_changed.emit(self)
            return

        target_row = self.indexAt(event.position().toPoint()).row()
        if target_row < 0:
            target_row = self.count()

        handled = self.kanban.transfer_store(
            int(payload.get("store_id") or 0),
            source_column_key=str(payload.get("source_column_key") or ""),
            source_route_name=str(payload.get("source_route_name") or ""),
            source_route_code=str(payload.get("source_route_code") or ""),
            target_column_key=self.column_key,
            target_route_name=self.route_name,
            target_route_code=self.route_code,
        )
        if handled:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if not item:
            return
        store = item.data(Qt.UserRole)
        if not store or not store.get("id"):
            return

        menu = QMenu(self)
        move_action = menu.addAction("ルートへ移動...")
        unassign_action = None
        if self.column_key != UNASSIGNED_COLUMN_KEY:
            unassign_action = menu.addAction("未所属へ外す")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == move_action:
            self.kanban.move_store_via_dialog(
                store,
                source_column_key=self.column_key,
                source_route_name=self.route_name,
                source_route_code=self.route_code,
            )
        elif unassign_action and chosen == unassign_action:
            self.kanban.transfer_store(
                int(store["id"]),
                source_column_key=self.column_key,
                source_route_name=self.route_name,
                source_route_code=self.route_code,
                target_column_key=UNASSIGNED_COLUMN_KEY,
                target_route_name="",
                target_route_code="",
            )


class RouteKanbanColumn(QFrame):
    """カンバン1列（ヘッダ + 店舗リスト）。ヘッダDnDで列位置を変更。"""

    def __init__(
        self,
        kanban: "RouteKanbanWidget",
        column_key: str,
        title: str,
        subtitle: str,
        route_name: str = "",
        route_code: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.kanban = kanban
        self.column_key = column_key
        self.route_name = route_name
        self.route_code = route_code
        self._is_unassigned = column_key == UNASSIGNED_COLUMN_KEY

        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(200)
        self.setMinimumHeight(COLUMN_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QFrame { background-color: #2b2b2b; border: 1px solid #444; border-radius: 6px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ヘッダ（列のドラッグハンドル）
        self.header = QFrame()
        self.header.setObjectName("kanbanColumnHeader")
        self.header.setCursor(
            Qt.ForbiddenCursor if self._is_unassigned else Qt.OpenHandCursor
        )
        self.header.setStyleSheet(
            "QFrame#kanbanColumnHeader {"
            " background-color: #363636; border-radius: 4px; padding: 2px;"
            "}"
        )
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e8e8e8;")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet("font-size: 8pt; color: #999;")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.subtitle_label)

        if not self._is_unassigned:
            hint = QLabel("↕ ヘッダをドラッグで列の並び替え")
            hint.setStyleSheet("font-size: 7pt; color: #777;")
            header_layout.addWidget(hint)

        self.header.mousePressEvent = self._header_mouse_press  # type: ignore[method-assign]
        self.header.setContextMenuPolicy(Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._header_context_menu)
        layout.addWidget(self.header)

        self.store_list = RouteKanbanColumnList(
            kanban,
            column_key=column_key,
            route_name=route_name,
            route_code=route_code,
            parent=self,
        )
        self.store_list.internal_order_changed.connect(kanban.on_internal_reorder)
        layout.addWidget(self.store_list, 1)

    def set_store_count(self, count: int) -> None:
        base = self.title_label.text().split(" · ")[0]
        self.title_label.setText(f"{base} · {count}店")

    def _header_context_menu(self, pos) -> None:
        menu = QMenu(self)
        add_action = menu.addAction("このルートに店舗を追加...")
        chosen = menu.exec(self.header.mapToGlobal(pos))
        if chosen == add_action:
            initial = "" if self._is_unassigned else self.route_name
            self.kanban.add_store(initial_route_name=initial)

    def _header_mouse_press(self, event) -> None:
        if self._is_unassigned:
            return
        if event.button() != Qt.LeftButton:
            return
        payload = {
            "column_key": self.column_key,
            "route_code": self.route_code,
        }
        mime = QMimeData()
        mime.setData(COLUMN_MIME_TYPE, _encode_drag_payload(payload))
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.header.setCursor(Qt.ClosedHandCursor)
        self.kanban.begin_drag_scroll()
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.kanban.end_drag_scroll()
            self.header.setCursor(Qt.OpenHandCursor)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(COLUMN_MIME_TYPE):
            event.acceptProposedAction()
            self.kanban.auto_scroll_at_global_pos()
            self.setStyleSheet(
                "QFrame { background-color: #2b2b2b; border: 2px solid #6eb5ff; "
                "border-radius: 6px; }"
            )
            return
        if event.mimeData().hasFormat(KANBAN_MIME_TYPE):
            # 店舗カードはリスト側で処理
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(COLUMN_MIME_TYPE):
            event.acceptProposedAction()
            self.kanban.auto_scroll_at_global_pos()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(
            "QFrame { background-color: #2b2b2b; border: 1px solid #444; border-radius: 6px; }"
        )
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet(
            "QFrame { background-color: #2b2b2b; border: 1px solid #444; border-radius: 6px; }"
        )
        if not event.mimeData().hasFormat(COLUMN_MIME_TYPE):
            event.ignore()
            return
        payload = _decode_drag_payload(event.mimeData().data(COLUMN_MIME_TYPE))
        if not payload:
            event.ignore()
            return
        source_key = str(payload.get("column_key") or "")
        if not source_key or source_key == self.column_key:
            event.ignore()
            return
        if self.kanban.reorder_route_column(source_key, self.column_key):
            event.acceptProposedAction()
        else:
            event.ignore()


class _KanbanScrollArea(QScrollArea):
    """ドラッグ中のオートスクロール用。"""

    def __init__(self, kanban: "RouteKanbanWidget", parent: QWidget | None = None):
        super().__init__(parent)
        self._kanban = kanban

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(KANBAN_MIME_TYPE) or event.mimeData().hasFormat(
            COLUMN_MIME_TYPE
        ):
            event.acceptProposedAction()
            self._kanban.auto_scroll_at_global_pos()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(KANBAN_MIME_TYPE) or event.mimeData().hasFormat(
            COLUMN_MIME_TYPE
        ):
            event.acceptProposedAction()
            self._kanban.auto_scroll_at_global_pos()
            return
        super().dragMoveEvent(event)


class RouteKanbanWidget(QWidget):
    """ルート一覧カンバン（未所属 + 各ルート列）。"""

    routes_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self._columns: Dict[str, RouteKanbanColumn] = {}
        self._all_routes: List[Dict[str, Any]] = []
        self._search_term = ""
        self._focus_mode = False
        self._focus_route_code_1 = ""
        self._focus_route_code_2 = ""
        self._drag_scroll_active = False
        self._auto_scroll_dx = 0
        self._auto_scroll_dy = 0
        self._undo_stack: List[Dict[str, Any]] = []
        self._redo_stack: List[Dict[str, Any]] = []
        self._applying_history = False

        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(AUTO_SCROLL_INTERVAL_MS)
        self._auto_scroll_timer.timeout.connect(self._auto_scroll_tick)

        self.setup_ui()
        self.reload_board()
        self._update_undo_redo_buttons()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel("ルート一覧（カンバン）")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        toolbar.addWidget(title)

        add_store_btn = QPushButton("店舗追加")
        add_store_btn.setToolTip("店舗一覧と同じダイアログで新規店舗を登録します")
        add_store_btn.setStyleSheet(
            "QPushButton { background-color: #28a745; color: white; "
            "font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
        )
        add_store_btn.clicked.connect(lambda: self.add_store())
        toolbar.addWidget(add_store_btn)

        self.undo_btn = QPushButton("戻る")
        self.undo_btn.setToolTip("直前の操作を取り消します（Ctrl+Z）\n対象: 店舗の移動・列の並び替え")
        self.undo_btn.clicked.connect(self.undo_action)
        toolbar.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("進む")
        self.redo_btn.setToolTip("取り消した操作をやり直します（Ctrl+Y）")
        self.redo_btn.clicked.connect(self.redo_action)
        toolbar.addWidget(self.redo_btn)

        toolbar.addStretch()

        toolbar.addWidget(QLabel("検索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("店舗名・店舗コード...")
        self.search_edit.setMinimumWidth(160)
        self.search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_edit)

        reload_btn = QPushButton("再読込")
        reload_btn.clicked.connect(self.reload_board)
        toolbar.addWidget(reload_btn)
        layout.addLayout(toolbar)

        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo_action)
        redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_shortcut.activated.connect(self.redo_action)
        redo_shortcut2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        redo_shortcut2.activated.connect(self.redo_action)

        focus_row = QHBoxLayout()
        self.focus_checkbox = QCheckBox("フォーカスモード")
        self.focus_checkbox.setToolTip(
            "ON: 未所属 + 選んだルート最大2列だけ表示"
        )
        self.focus_checkbox.toggled.connect(self._on_focus_mode_toggled)
        focus_row.addWidget(self.focus_checkbox)

        focus_row.addWidget(QLabel("ルート1:"))
        self.focus_route_combo_1 = QComboBox()
        self.focus_route_combo_1.setMinimumWidth(180)
        self.focus_route_combo_1.currentIndexChanged.connect(self._on_focus_route_changed)
        focus_row.addWidget(self.focus_route_combo_1)

        focus_row.addWidget(QLabel("ルート2:"))
        self.focus_route_combo_2 = QComboBox()
        self.focus_route_combo_2.setMinimumWidth(180)
        self.focus_route_combo_2.currentIndexChanged.connect(self._on_focus_route_changed)
        focus_row.addWidget(self.focus_route_combo_2)

        self.jump_route_btn = QPushButton("ルート1へジャンプ")
        self.jump_route_btn.setToolTip("選択中のルート1列までスクロールします")
        self.jump_route_btn.clicked.connect(self._jump_to_focus_route_1)
        focus_row.addWidget(self.jump_route_btn)

        focus_row.addStretch()
        layout.addLayout(focus_row)

        legend = QLabel(
            f"凡例: 薄色 + [追加] = 副所属 / 右クリックで店舗移動 / "
            f"ヘッダDnDで列並び替え / 戻る・進むは移動・並び替え用 / "
            f"横{COLUMNS_PER_ROW}列折り返し"
        )
        legend.setStyleSheet("color: #999; font-size: 9pt;")
        layout.addWidget(legend)

        self.scroll = _KanbanScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QScrollArea.NoFrame)

        self.board = QWidget()
        self.board_layout = QGridLayout(self.board)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setHorizontalSpacing(10)
        self.board_layout.setVerticalSpacing(12)
        self.board_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll.setWidget(self.board)
        layout.addWidget(self.scroll, 1)

        self._sync_focus_controls_enabled()

    def _capture_membership_snapshot(self) -> Dict[str, Any]:
        """店舗所属・訪問順・ルート並びをスナップショットする。"""
        stores = []
        for store in self.db.list_stores():
            sid = store.get("id")
            if not sid:
                continue
            stores.append(
                {
                    "id": int(sid),
                    "affiliated_route_name": store.get("affiliated_route_name"),
                    "route_code": store.get("route_code"),
                    "display_order": store.get("display_order"),
                }
            )
        routes = []
        for route in self.db.list_routes_with_store_count():
            code = (route.get("route_code") or "").strip()
            if not code:
                continue
            routes.append(
                {
                    "route_code": code,
                    "display_order": int(route.get("display_order") or 0),
                }
            )
        return {"stores": stores, "routes": routes}

    def _restore_membership_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """スナップショットをDBへ復元する。"""
        try:
            for store in snapshot.get("stores") or []:
                sid = store.get("id")
                if not sid:
                    continue
                self.db.update_store(
                    int(sid),
                    {
                        "affiliated_route_name": store.get("affiliated_route_name"),
                        "route_code": store.get("route_code"),
                        "display_order": store.get("display_order"),
                    },
                )
            ordered_codes = [
                r["route_code"]
                for r in sorted(
                    snapshot.get("routes") or [],
                    key=lambda x: int(x.get("display_order") or 0),
                )
                if r.get("route_code")
            ]
            if ordered_codes:
                self.db.update_route_display_orders(ordered_codes)
            return True
        except Exception as e:
            print(f"カンバン履歴復元エラー: {e}")
            return False

    def _push_undo_snapshot(self) -> None:
        if self._applying_history:
            return
        snap = self._capture_membership_snapshot()
        self._undo_stack.append(snap)
        if len(self._undo_stack) > MAX_UNDO_HISTORY:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self) -> None:
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(bool(self._undo_stack))
        if hasattr(self, "redo_btn"):
            self.redo_btn.setEnabled(bool(self._redo_stack))

    def undo_action(self) -> None:
        """直前の店舗移動・列並び替えを取り消す。"""
        if not self._undo_stack:
            return
        current = self._capture_membership_snapshot()
        previous = self._undo_stack.pop()
        self._applying_history = True
        try:
            if not self._restore_membership_snapshot(previous):
                self._undo_stack.append(previous)
                QMessageBox.warning(self, "エラー", "戻る操作に失敗しました。")
                return
            self._redo_stack.append(current)
            self.routes_changed.emit()
            self.reload_board()
        finally:
            self._applying_history = False
            self._update_undo_redo_buttons()

    def redo_action(self) -> None:
        """取り消した操作をやり直す。"""
        if not self._redo_stack:
            return
        current = self._capture_membership_snapshot()
        next_snap = self._redo_stack.pop()
        self._applying_history = True
        try:
            if not self._restore_membership_snapshot(next_snap):
                self._redo_stack.append(next_snap)
                QMessageBox.warning(self, "エラー", "進む操作に失敗しました。")
                return
            self._undo_stack.append(current)
            self.routes_changed.emit()
            self.reload_board()
        finally:
            self._applying_history = False
            self._update_undo_redo_buttons()

    def _default_initial_route_name(self) -> str:
        """フォーカスモード時はルート1の名前を初期値にする。"""
        if not self._focus_mode:
            return ""
        code = (self._focus_route_code_1 or "").strip()
        if not code:
            return ""
        for route in self._all_routes:
            if (route.get("route_code") or "").strip() == code:
                return (route.get("route_name") or "").strip()
        return ""

    def add_store(self, initial_route_name: Optional[str] = None) -> None:
        """店舗一覧と同じダイアログで新規店舗を追加し、カンバンを即更新する。"""
        if initial_route_name is None:
            initial_route_name = self._default_initial_route_name()

        custom_fields_def = self.db.list_custom_fields(active_only=True)
        dialog = StoreEditDialog(
            self,
            custom_fields_def=custom_fields_def,
            initial_route_name=initial_route_name or None,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        is_valid, error_msg = dialog.validate()
        if not is_valid:
            QMessageBox.warning(self, "エラー", error_msg)
            return

        try:
            data = dialog.get_data()
            if not data.get("store_code"):
                store_name = data.get("store_name", "")
                if store_name:
                    generated = self.db.get_next_store_code_from_store_name(store_name)
                    if generated:
                        data["store_code"] = generated
            self.db.add_store(data)
            QMessageBox.information(self, "完了", "店舗を追加しました")
            # カンバン再描画（店舗リスト・店舗数を即反映）
            self.routes_changed.emit()
            self.reload_board()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")

    def begin_drag_scroll(self) -> None:
        self._drag_scroll_active = True
        if self._auto_scroll_dx != 0 or self._auto_scroll_dy != 0:
            self._auto_scroll_timer.start()

    def end_drag_scroll(self) -> None:
        self._drag_scroll_active = False
        self._auto_scroll_dx = 0
        self._auto_scroll_dy = 0
        self._auto_scroll_timer.stop()

    def auto_scroll_at_global_pos(self, global_pos: QPoint | None = None) -> None:
        """ドラッグ中: 端付近なら縦（優先）・横に自動スクロールする。"""
        if global_pos is None:
            global_pos = QCursor.pos()
        viewport = self.scroll.viewport()
        local = viewport.mapFromGlobal(global_pos)
        margin = AUTO_SCROLL_MARGIN_PX
        dx = 0
        dy = 0
        if local.x() < margin:
            dx = -1
        elif local.x() > viewport.width() - margin:
            dx = 1
        if local.y() < margin:
            dy = -1
        elif local.y() > viewport.height() - margin:
            dy = 1

        self._auto_scroll_dx = dx
        self._auto_scroll_dy = dy
        if self._drag_scroll_active and (dx != 0 or dy != 0):
            self._auto_scroll_timer.start()
        elif dx == 0 and dy == 0:
            self._auto_scroll_timer.stop()

    def _auto_scroll_tick(self) -> None:
        if not self._drag_scroll_active:
            return
        self.auto_scroll_at_global_pos()
        if self._auto_scroll_dx == 0 and self._auto_scroll_dy == 0:
            return
        if self._auto_scroll_dx != 0:
            hbar = self.scroll.horizontalScrollBar()
            hbar.setValue(hbar.value() + self._auto_scroll_dx * AUTO_SCROLL_STEP_PX)
        if self._auto_scroll_dy != 0:
            vbar = self.scroll.verticalScrollBar()
            vbar.setValue(vbar.value() + self._auto_scroll_dy * AUTO_SCROLL_STEP_PX)

    def _on_focus_mode_toggled(self, checked: bool) -> None:
        self._focus_mode = bool(checked)
        self._sync_focus_controls_enabled()
        self.reload_board()
        if self._focus_mode and self._focus_route_code_1:
            QTimer.singleShot(0, self._jump_to_focus_route_1)

    def _sync_focus_controls_enabled(self) -> None:
        enabled = self._focus_mode
        self.focus_route_combo_1.setEnabled(enabled)
        self.focus_route_combo_2.setEnabled(enabled)
        self.jump_route_btn.setEnabled(enabled)

    def _on_focus_route_changed(self, _index: int = -1) -> None:
        self._focus_route_code_1 = self.focus_route_combo_1.currentData() or ""
        self._focus_route_code_2 = self.focus_route_combo_2.currentData() or ""
        if self._focus_mode:
            self.reload_board()
            if self._focus_route_code_1:
                QTimer.singleShot(0, self._jump_to_focus_route_1)

    def _refresh_focus_route_combos(self) -> None:
        preserve_1 = self._focus_route_code_1
        preserve_2 = self._focus_route_code_2

        for combo, preserve in (
            (self.focus_route_combo_1, preserve_1),
            (self.focus_route_combo_2, preserve_2),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("（なし）", "")
            for route in self._all_routes:
                code = (route.get("route_code") or "").strip()
                name = (route.get("route_name") or "").strip()
                if not code:
                    continue
                combo.addItem(f"{name or code} ({code})", code)
            idx = combo.findData(preserve)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

        self._focus_route_code_1 = self.focus_route_combo_1.currentData() or ""
        self._focus_route_code_2 = self.focus_route_combo_2.currentData() or ""

    def _routes_to_display(self) -> List[Dict[str, Any]]:
        if not self._focus_mode:
            return list(self._all_routes)

        codes: List[str] = []
        for code in (self._focus_route_code_1, self._focus_route_code_2):
            c = (code or "").strip()
            if c and c not in codes:
                codes.append(c)
        if not codes:
            return []

        by_code = {
            (r.get("route_code") or "").strip(): r
            for r in self._all_routes
            if (r.get("route_code") or "").strip()
        }
        return [by_code[c] for c in codes if c in by_code]

    def _jump_to_focus_route_1(self) -> None:
        code = (self._focus_route_code_1 or "").strip()
        if not code:
            QMessageBox.information(self, "ジャンプ", "フォーカスモードでルート1を選んでください。")
            return
        column = self._columns.get(code)
        if not column:
            QMessageBox.information(self, "ジャンプ", "表示中の列にルート1がありません。")
            return
        self.scroll.ensureWidgetVisible(column, 16, 0)

    def _on_search_changed(self, text: str) -> None:
        self._search_term = (text or "").strip().lower()
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        for column in self._columns.values():
            for row in range(column.store_list.count()):
                item = column.store_list.item(row)
                if not item:
                    continue
                if not self._search_term:
                    item.setHidden(False)
                    continue
                item.setHidden(self._search_term not in item.text().lower())

    def _clear_board_layout(self) -> None:
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_column_to_grid(self, column: RouteKanbanColumn, index: int) -> None:
        """横 COLUMNS_PER_ROW 列で折り返してグリッド配置する。"""
        row = index // COLUMNS_PER_ROW
        col = index % COLUMNS_PER_ROW
        self.board_layout.addWidget(column, row, col)

    def reload_board(self) -> None:
        self._clear_board_layout()
        self._columns.clear()

        self._all_routes = self.db.list_routes_with_store_count()
        self._refresh_focus_route_combos()

        routes = self._routes_to_display()
        stores = self.db.list_stores()
        column_data = build_kanban_columns_data(stores, self._all_routes)

        columns_to_add: List[RouteKanbanColumn] = []

        unassigned = RouteKanbanColumn(
            self,
            column_key=UNASSIGNED_COLUMN_KEY,
            title="未所属",
            subtitle="ルート未設定 / 右クリックで移動",
            parent=self.board,
        )
        self._populate_column_list(
            unassigned,
            column_data.get(UNASSIGNED_COLUMN_KEY, []),
            route_name="",
            is_unassigned=True,
        )
        self._columns[UNASSIGNED_COLUMN_KEY] = unassigned
        columns_to_add.append(unassigned)

        for route in routes:
            code = (route.get("route_code") or "").strip()
            name = (route.get("route_name") or "").strip()
            if not code:
                continue
            column = RouteKanbanColumn(
                self,
                column_key=code,
                title=f"{name or code} ({code})",
                subtitle="店舗: リスト内DnD / 列: ヘッダDnD",
                route_name=name,
                route_code=code,
                parent=self.board,
            )
            self._populate_column_list(
                column,
                column_data.get(code, []),
                route_name=name,
                is_unassigned=False,
            )
            self._columns[code] = column
            columns_to_add.append(column)

        for idx, column in enumerate(columns_to_add):
            self._add_column_to_grid(column, idx)

        # 余白列が潰れないよう、表示列分だけ均等に伸ばす
        for col in range(COLUMNS_PER_ROW):
            self.board_layout.setColumnStretch(col, 1)

        self._apply_search_filter()

    def reorder_route_column(self, source_key: str, target_key: str) -> bool:
        """ルート列を target の位置（直前）へ移動し、display_order を即保存する。

        未所属列は常に先頭固定。target が未所属のときは先頭（ルート1番目）へ移動。
        """
        source_key = (source_key or "").strip()
        target_key = (target_key or "").strip()
        if not source_key or source_key == UNASSIGNED_COLUMN_KEY:
            return False
        if source_key == target_key:
            return False

        ordered = [
            (r.get("route_code") or "").strip()
            for r in self._all_routes
            if (r.get("route_code") or "").strip()
        ]
        if source_key not in ordered:
            return False

        from_idx = ordered.index(source_key)
        ordered.pop(from_idx)

        if target_key == UNASSIGNED_COLUMN_KEY:
            to_idx = 0
        elif target_key in ordered:
            to_idx = ordered.index(target_key)
        else:
            # フォーカス外の列など
            to_idx = len(ordered)

        ordered.insert(to_idx, source_key)

        self._push_undo_snapshot()
        if not self.db.update_route_display_orders(ordered):
            self._discard_last_undo()
            QMessageBox.warning(self, "エラー", "ルートの並び順を保存できませんでした。")
            return False

        # 店舗所属は変わらないが、一覧側のルート順も揃える
        self.routes_changed.emit()
        self.reload_board()
        return True

    def _populate_column_list(
        self,
        column: RouteKanbanColumn,
        stores: List[Dict[str, Any]],
        *,
        route_name: str,
        is_unassigned: bool,
    ) -> None:
        column.store_list.clear()
        for store in stores:
            code = store_code_from_store(store)
            name = (store.get("store_name") or "").strip()
            label = f"{code} {name}".strip()
            is_primary = True
            if not is_unassigned:
                is_primary = is_primary_in_route(store, route_name)
                if not is_primary:
                    label = f"{label} [追加]"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, store)
            item.setData(Qt.UserRole + 1, is_primary)
            if not is_unassigned and not is_primary:
                item.setBackground(QBrush(QColor("#555555")))
            column.store_list.addItem(item)

        column.set_store_count(len(stores))

    def move_store_via_dialog(
        self,
        store: Dict[str, Any],
        *,
        source_column_key: str,
        source_route_name: str,
        source_route_code: str,
    ) -> None:
        store_id = int(store.get("id") or 0)
        if not store_id:
            return

        dialog = MoveToRouteDialog(
            self._all_routes,
            exclude_route_code=source_route_code if source_column_key != UNASSIGNED_COLUMN_KEY else "",
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        target = dialog.selected_route()
        if not target:
            return

        self.transfer_store(
            store_id,
            source_column_key=source_column_key,
            source_route_name=source_route_name,
            source_route_code=source_route_code,
            target_column_key=target["route_code"],
            target_route_name=target["route_name"],
            target_route_code=target["route_code"],
        )

    def transfer_store(
        self,
        store_id: int,
        *,
        source_column_key: str,
        source_route_name: str,
        source_route_code: str,
        target_column_key: str,
        target_route_name: str,
        target_route_code: str,
    ) -> bool:
        if source_column_key == target_column_key:
            return False

        store = self.db.get_store(store_id)
        if not store:
            return False

        store_label = f"{store_code_from_store(store)} {(store.get('store_name') or '')}".strip()

        if target_column_key == UNASSIGNED_COLUMN_KEY:
            if source_column_key == UNASSIGNED_COLUMN_KEY:
                return False
            self._push_undo_snapshot()
            ok = remove_store_from_route(
                self.db,
                store_id,
                source_route_name,
                source_route_code,
            )
            if ok:
                self._after_db_change()
            else:
                self._discard_last_undo()
            return ok

        if source_column_key == UNASSIGNED_COLUMN_KEY:
            self._push_undo_snapshot()
            ok = move_store_to_route(
                self.db,
                store_id,
                target_route_name,
                target_route_code,
            )
            if ok:
                self._after_db_change()
            else:
                self._discard_last_undo()
            return ok

        if store_in_route(store, target_route_name, target_route_code):
            QMessageBox.information(
                self,
                "所属済み",
                f"「{store_label}」はすでにこのルートに所属しています。",
            )
            return False

        action = self._ask_move_or_add(
            store_label,
            target_route_name or target_route_code,
        )
        if action == "cancel":
            return False

        self._push_undo_snapshot()
        if action == "move":
            ok = move_store_to_route(
                self.db,
                store_id,
                target_route_name,
                target_route_code,
            )
        else:
            ok = add_store_to_route(
                self.db,
                store_id,
                target_route_name,
                target_route_code,
            )

        if ok:
            self._after_db_change()
        else:
            self._discard_last_undo()
        return ok

    def on_internal_reorder(self, source_list: RouteKanbanColumnList) -> None:
        if source_list.column_key == UNASSIGNED_COLUMN_KEY:
            return
        if not source_list.route_name:
            return

        ordered_codes: List[str] = []
        for row in range(source_list.count()):
            item = source_list.item(row)
            if not item or not item.data(Qt.UserRole + 1):
                continue
            store = item.data(Qt.UserRole)
            if not store:
                continue
            code = store_code_from_store(store)
            if code:
                ordered_codes.append(code)

        if not ordered_codes:
            return

        self._push_undo_snapshot()
        if reorder_route_stores(self.db, source_list.route_name, ordered_codes):
            self._after_db_change()
        else:
            self._discard_last_undo()

    def _ask_move_or_add(self, store_label: str, target_route: str) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("ルート所属")
        box.setText(f"「{store_label}」を\n「{target_route}」へどうしますか？")
        box.setInformativeText(
            "移動: 主所属を切り替え（元ルートから外れます）\n"
            "追加: 元ルートも残し、このルートにも所属（副所属）"
        )
        move_btn = box.addButton("移動", QMessageBox.AcceptRole)
        add_btn = box.addButton("追加", QMessageBox.ActionRole)
        box.addButton("キャンセル", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == move_btn:
            return "move"
        if clicked == add_btn:
            return "add"
        return "cancel"

    def _discard_last_undo(self) -> None:
        if self._undo_stack:
            self._undo_stack.pop()
        self._update_undo_redo_buttons()

    def _after_db_change(self) -> None:
        self.routes_changed.emit()
        self.reload_board()
        self._update_undo_redo_buttons()
