#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入行編集ダイアログで証憑貼付パネルが出ること。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QLineEdit, QPushButton

from desktop.ui.inventory.row_edit_dialog import InventoryRowEditDialog


class _DummyTemplateDb:
    def load_missing_keywords(self):
        return {"custom_labels": {}, "keywords": {}}

    def get_condition_description_text(self, _key):
        return ""


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_evidence_panel_is_shown_and_hidden_columns_are_not_line_edits():
    _app()
    headers = [
        "ASIN",
        "仕入先",
        "仕入れ日",
        "証憑フォルダ",
        "証憑画像1",
        "証憑画像2",
        "証憑画像3",
        "証憑URL1",
        "証憑URL2",
        "証憑URL3",
        "価格改定",
    ]
    dlg = InventoryRowEditDialog(
        headers,
        {"仕入先": "HA01", "ASIN": "B00NMM0VI"},
        _DummyTemplateDb(),
        lambda text: text,
    )
    assert dlg.evidence_panel is not None
    assert dlg.evidence_panel.isVisibleTo(dlg)
    assert isinstance(dlg.evidence_panel, QGroupBox)
    assert "フリマ仕入証憑" in dlg.evidence_panel.title()
    paste_buttons = [
        b for b in dlg.evidence_panel.findChildren(QPushButton) if b.text() == "貼り付け"
    ]
    assert len(paste_buttons) == 3
    for col in (
        "証憑フォルダ",
        "証憑画像1",
        "証憑画像2",
        "証憑画像3",
        "証憑URL1",
        "証憑URL2",
        "証憑URL3",
    ):
        assert col not in dlg._widgets
        assert not any(
            isinstance(w, QLineEdit) and w.objectName() == col for w in dlg.findChildren(QLineEdit)
        )
    dlg.close()


def test_online_inventory_headers_put_channel_next_to_comment():
    from desktop.ui.inventory.table_mixin import InventoryTableMixin

    class _Headers(InventoryTableMixin):
        def __init__(self):
            self.purchase_mode = "online"
            self.dev_mode = False

    headers = _Headers()._build_inventory_column_headers()
    assert headers.index("コメント") + 1 == headers.index("仕入チャネル")
    assert headers.index("仕入チャネル") + 1 == headers.index("発送方法")
    assert headers.index("発送方法") + 1 == headers.index("販売チャネル")
    assert "プラットフォーム" not in headers
    assert "取引ID" in headers


def test_store_inventory_headers_keep_platform_column():
    from desktop.ui.inventory.table_mixin import InventoryTableMixin

    class _Headers(InventoryTableMixin):
        def __init__(self):
            self.purchase_mode = "store"
            self.dev_mode = False

    headers = _Headers()._build_inventory_column_headers()
    assert "仕入チャネル" not in headers
    assert "プラットフォーム" in headers
    assert headers.index("コメント") + 1 == headers.index("発送方法")
