#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テーブル UI ユーティリティ

- 全列をユーザーがドラッグでリサイズ可能にする
- 列幅を QSettings に保存し、次回起動時に復元する
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, TYPE_CHECKING

from PySide6.QtCore import QObject, QEvent, QSettings, QTimer
from PySide6.QtWidgets import QHeaderView, QTableView, QTableWidget, QTabWidget, QGroupBox, QWidget

if TYPE_CHECKING:
    pass

SETTINGS_ORG = "HIRIO"
SETTINGS_APP = "SedoriDesktopApp"
SETTINGS_PREFIX = "table_column_widths/"


def table_column_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _normalize_width_list(raw: Any, column_count: int) -> Optional[List[int]]:
    """QSettings から読み込んだ列幅を列インデックスに対応づけて返す。"""
    if raw is None:
        return None
    if hasattr(raw, "__iter__") and not isinstance(raw, (str, bytes)):
        items = list(raw)
    else:
        return None
    if not items:
        return None
    widths: List[int] = []
    for col_idx in range(column_count):
        if col_idx >= len(items):
            break
        try:
            w = int(items[col_idx])
        except (TypeError, ValueError):
            w = 0
        widths.append(w)
    return widths if any(w > 0 for w in widths) else None


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u3040-\u9fff-]+", "_", (text or "").strip())
    return (s[:48] or "section").strip("_")


def _widget_contains(ancestor: QWidget, widget: QWidget) -> bool:
    w: Optional[QWidget] = widget
    while w is not None:
        if w is ancestor:
            return True
        w = w.parentWidget()
    return False


def _table_column_count(table: QTableView) -> int:
    """QTableWidget / QTableView 両対応の列数取得。"""
    if hasattr(table, "columnCount"):
        try:
            count = int(table.columnCount())
            if count > 0:
                return count
        except (TypeError, ValueError):
            pass
    return int(table.horizontalHeader().count())


def build_table_column_settings_key(table: QTableView) -> str:
    """
    タブ名・グループボックス名などから安定した設定キーを生成する。
    明示指定は table._hirio_table_column_settings_key を優先する。
    """
    explicit = getattr(table, "_hirio_table_column_settings_key", None)
    if explicit:
        return str(explicit)

    segments: List[str] = []
    w: Optional[QWidget] = table.parentWidget()
    while w is not None:
        if isinstance(w, QTabWidget):
            for i in range(w.count()):
                tab_widget = w.widget(i)
                if tab_widget is not None and _widget_contains(tab_widget, table):
                    segments.append(_slug(w.tabText(i)))
                    break
        elif isinstance(w, QGroupBox):
            title = _slug(w.title())
            if title:
                segments.append(title)
        elif w.objectName():
            segments.append(w.objectName())
        w = w.parentWidget()

    parent = table.parentWidget()
    if parent is not None:
        siblings = [c for c in parent.children() if isinstance(c, QTableView)]
        if len(siblings) > 1 and table in siblings:
            segments.append(f"table{siblings.index(table)}")

    cls_name = table.__class__.__name__
    if cls_name not in ("QTableWidget", "QTableView"):
        segments.append(cls_name)

    if not segments:
        segments.append(f"table_{id(table)}")

    return SETTINGS_PREFIX + "/".join(segments)


class TableColumnWidthPersistence:
    """1つのテーブルの列幅保存・復元を担当する。"""

    _registry: List["TableColumnWidthPersistence"] = []

    def __init__(
        self,
        table: QTableView,
        settings_key: str,
        default_widths: Optional[Sequence[int]] = None,
        legacy_keys: Optional[Sequence[str]] = None,
    ):
        self.table = table
        self.settings_key = settings_key
        self.default_widths = list(default_widths) if default_widths else None
        self.legacy_keys = list(legacy_keys) if legacy_keys else []
        self._connected = False
        self._memory_widths: Optional[List[int]] = None
        TableColumnWidthPersistence._registry.append(self)

    @classmethod
    def save_all(cls) -> None:
        for item in cls._registry:
            item.save()

    def _load_widths(self, column_count: int) -> Optional[List[int]]:
        settings = table_column_settings()
        keys = [self.settings_key, *self.legacy_keys]
        for key in keys:
            widths = _normalize_width_list(settings.value(key), column_count)
            if widths:
                return widths
        # 旧 ui_utils（SedoriApp）からの移行
        legacy_app = QSettings(SETTINGS_ORG, "SedoriApp")
        for key in keys:
            widths = _normalize_width_list(legacy_app.value(key), column_count)
            if widths:
                return widths
        return None

    def save(self) -> None:
        table = self.table
        if table is None:
            return
        column_count = _table_column_count(table)
        if column_count <= 0:
            return
        widths = [table.columnWidth(i) for i in range(column_count)]
        self._memory_widths = widths
        table_column_settings().setValue(self.settings_key, widths)
        table_column_settings().sync()

    def apply(self, *, deferred: bool = True, allow_defaults: bool = True) -> None:
        """列数確定後に呼び出し、Interactive 化と幅復元を行う。"""
        if deferred:
            QTimer.singleShot(0, lambda: self._apply_now(allow_defaults=allow_defaults))
            return
        self._apply_now(allow_defaults=allow_defaults)

    def _resolve_widths_to_apply(
        self, column_count: int, *, allow_defaults: bool
    ) -> Optional[List[int]]:
        saved_widths = self._load_widths(column_count)
        if saved_widths:
            return saved_widths[:column_count]
        memory_widths = self._memory_widths
        if memory_widths and len(memory_widths) >= column_count:
            return memory_widths[:column_count]
        if allow_defaults and self.default_widths:
            return list(self.default_widths[:column_count])
        return None

    def _apply_now(self, *, allow_defaults: bool = True) -> None:
        table = self.table
        if table is None:
            return
        header = table.horizontalHeader()
        column_count = _table_column_count(table)
        if column_count <= 0:
            return

        if not self._connected:
            header.sectionResized.connect(self._on_section_resized)
            self._connected = True

        widths_to_apply = self._resolve_widths_to_apply(
            column_count, allow_defaults=allow_defaults
        )
        header.blockSignals(True)
        try:
            header.setStretchLastSection(False)
            for col_idx in range(column_count):
                header.setSectionResizeMode(col_idx, QHeaderView.Interactive)

            if widths_to_apply:
                for col_idx, width in enumerate(widths_to_apply):
                    if col_idx < column_count and width > 0:
                        table.setColumnWidth(col_idx, width)
            self._memory_widths = [
                table.columnWidth(i) for i in range(column_count)
            ]
        finally:
            header.blockSignals(False)

    def _on_section_resized(self, *_args) -> None:
        self.save()


def attach_table_column_width_persistence(
    table: QTableView,
    settings_key: Optional[str] = None,
    *,
    default_widths: Optional[Sequence[int]] = None,
    legacy_keys: Optional[Sequence[str]] = None,
) -> TableColumnWidthPersistence:
    """テーブルに列幅永続化を取り付ける（二重取り付けはしない）。"""
    existing = getattr(table, "_hirio_column_width_persistence", None)
    if existing is not None:
        return existing

    key = settings_key or build_table_column_settings_key(table)
    persistence = TableColumnWidthPersistence(
        table,
        key,
        default_widths=default_widths,
        legacy_keys=legacy_keys,
    )
    table._hirio_column_width_persistence = persistence  # type: ignore[attr-defined]
    _wrap_table_column_mutators(table, persistence)
    return persistence


def _wrap_table_column_mutators(table: QTableView, persistence: TableColumnWidthPersistence) -> None:
    """QTableWidget 専用: setColumnCount 変更時に列幅を再適用する。"""
    if getattr(table, "_hirio_col_width_wrapped", False):
        return
    if not isinstance(table, QTableWidget):
        return
    if not hasattr(table, "setColumnCount") or not hasattr(table, "setHorizontalHeaderLabels"):
        return
    table._hirio_col_width_wrapped = True  # type: ignore[attr-defined]

    original_set_column_count = table.setColumnCount
    original_set_header_labels = table.setHorizontalHeaderLabels
    original_set_row_count = getattr(table, "setRowCount", None)

    def setColumnCount(columns: int) -> None:
        original_set_column_count(columns)
        persistence.apply(allow_defaults=False, deferred=False)

    def setHorizontalHeaderLabels(labels) -> None:
        original_set_header_labels(labels)
        persistence.apply(allow_defaults=False, deferred=False)

    def setRowCount(rows: int) -> None:
        if original_set_row_count is not None:
            original_set_row_count(rows)
            persistence.apply(allow_defaults=False, deferred=False)

    table.setColumnCount = setColumnCount  # type: ignore[method-assign]
    table.setHorizontalHeaderLabels = setHorizontalHeaderLabels  # type: ignore[method-assign]
    if original_set_row_count is not None:
        table.setRowCount = setRowCount  # type: ignore[method-assign]


def reapply_table_column_widths(
    table: QTableView,
    *,
    deferred: bool = True,
    allow_defaults: bool = False,
) -> None:
    """データ再描画後に列幅を再適用する（Stretch / resizeColumnsToContents の代わりに使用）。"""
    persistence = getattr(table, "_hirio_column_width_persistence", None)
    if persistence is not None:
        persistence.apply(deferred=deferred, allow_defaults=allow_defaults)
    else:
        attach_table_column_width_persistence(table).apply(
            deferred=deferred, allow_defaults=allow_defaults
        )


def save_all_table_column_widths() -> None:
    TableColumnWidthPersistence.save_all()
    table_column_settings().sync()


class _TableColumnWidthShowFilter(QObject):
    """初回表示時に QTableWidget へ列幅永続化を自動取り付けする。"""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(obj, QTableWidget):
            try:
                persistence = getattr(obj, "_hirio_column_width_persistence", None)
                if persistence is None:
                    legacy = getattr(obj, "_hirio_table_column_legacy_keys", None)
                    persistence = attach_table_column_width_persistence(
                        obj,
                        legacy_keys=legacy,
                    )
                    persistence.apply(deferred=False, allow_defaults=True)
                elif _table_column_count(obj) > 0:
                    persistence.apply(deferred=False, allow_defaults=False)
            except Exception as exc:
                print(f"[WARN] テーブル列幅の復元をスキップしました: {exc}")
        return super().eventFilter(obj, event)


_show_filter: Optional[_TableColumnWidthShowFilter] = None


def install_global_table_column_width_persistence(app) -> None:
    """QApplication にイベントフィルタを登録し、全テーブルを対象にする。"""
    global _show_filter
    if _show_filter is not None:
        return
    _show_filter = _TableColumnWidthShowFilter(app)
    app.installEventFilter(_show_filter)


# --- 後方互換（QTableView 向けヘッダー状態保存） ---

def save_table_header_state(table_view: QTableView, settings_key: str):
    if not table_view:
        return
    QSettings(SETTINGS_ORG, "SedoriApp").setValue(
        settings_key, table_view.horizontalHeader().saveState()
    )


def restore_table_header_state(table_view: QTableView, settings_key: str):
    if not table_view:
        return
    header_state = QSettings(SETTINGS_ORG, "SedoriApp").value(settings_key)
    if header_state:
        table_view.horizontalHeader().restoreState(header_state)


def save_table_column_widths(table_view: QTableView, settings_key: str):
    persistence = getattr(table_view, "_hirio_column_width_persistence", None)
    if persistence is not None:
        persistence.save()
        return
    if not table_view:
        return
    header = table_view.horizontalHeader()
    column_count = header.count()
    if column_count == 0:
        return
    widths = [header.sectionSize(col_idx) for col_idx in range(column_count)]
    table_column_settings().setValue(settings_key, widths)


def restore_table_column_widths(table_view: QTableView, settings_key: str):
    attach_table_column_width_persistence(
        table_view,
        settings_key=SETTINGS_PREFIX + settings_key.lstrip("/"),
        legacy_keys=[settings_key],
    ).apply()
