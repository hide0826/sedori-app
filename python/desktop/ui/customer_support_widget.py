#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIタブ（チャット履歴サイドバー＋同一画面で完結）。"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_IMAGE_ROW_STYLE = """
QFrame#customerSupportImageRow {
    background-color: #1e2a36;
    border: 1px solid #4a6fa5;
    border-radius: 6px;
}
QLabel#customerSupportImageSlot {
    color: #b0c4de;
    font-weight: bold;
    padding: 6px 8px;
    min-width: 52px;
}
QLabel#customerSupportImageLink {
    color: #ffffff;
    background-color: transparent;
    padding: 6px 4px;
    font-size: 13px;
}
QLabel#customerSupportImageLink:hover {
    color: #7ec8ff;
}
QLabel#customerSupportImageHint {
    color: #9aa8b5;
    font-size: 12px;
    padding: 4px 2px;
}
"""

_SIDEBAR_STYLE = """
QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #444;
    border-radius: 4px;
}
QListWidget::item {
    padding: 8px 6px;
    border-bottom: 1px solid #333;
}
QListWidget::item:selected {
    background-color: #2d4a6f;
    color: #ffffff;
}
"""


class _ClickableImageLink(QLabel):
    """画像ファイル名のクリック可能ラベル（QPushButtonのグローバルスタイルを避ける）。"""

    clicked = Signal()

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setObjectName("customerSupportImageLink")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = self.font()
        font.setUnderline(True)
        self.setFont(font)
        self.setWordWrap(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

try:
    from services.customer_support_settings import (
        load_customer_support_settings,
        save_customer_support_settings,
    )
    from services.customer_support_session_store import (
        is_persistable_session,
        load_customer_support_sessions,
        save_customer_support_sessions,
        touch_session,
    )
    from services.customer_support_sku_lookup import (
        format_sku_context_for_display,
        lookup_sku_context,
    )
    from services.gemini_customer_support_service import (
        RESPONSE_POLICY_LABELS,
        GeminiCustomerSupportService,
    )
    from ui.customer_support_chat_window import CustomerSupportChatPanel
except ImportError:
    from desktop.services.customer_support_settings import (  # type: ignore
        load_customer_support_settings,
        save_customer_support_settings,
    )
    from desktop.services.customer_support_session_store import (  # type: ignore
        is_persistable_session,
        load_customer_support_sessions,
        save_customer_support_sessions,
        touch_session,
    )
    from desktop.services.customer_support_sku_lookup import (  # type: ignore
        format_sku_context_for_display,
        lookup_sku_context,
    )
    from desktop.services.gemini_customer_support_service import (  # type: ignore
        RESPONSE_POLICY_LABELS,
        GeminiCustomerSupportService,
    )
    from desktop.ui.customer_support_chat_window import CustomerSupportChatPanel  # type: ignore


def _session_list_title(session: Dict[str, Any]) -> str:
    name = (session.get("customer_name") or "").strip() or "（名前なし）"
    sku = (session.get("sku") or "").strip()
    preview = ""
    for item in session.get("history") or []:
        if item.get("role") == "customer":
            preview = str(item.get("text") or "").strip().replace("\n", " ")
            break
    if preview:
        preview = preview[:28] + ("…" if len(preview) > 28 else "")
    parts = [name]
    if sku:
        parts.append(sku)
    if preview:
        parts.append(preview)
    return " / ".join(parts)


class CustomerSupportWidget(QWidget):
    def __init__(self, product_widget: Any = None, parent=None):
        super().__init__(parent)
        self.product_widget = product_widget
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._session_order: List[str] = []
        self._current_case_id: Optional[str] = None
        self._sku_lookup_timer = QTimer(self)
        self._sku_lookup_timer.setSingleShot(True)
        self._sku_lookup_timer.timeout.connect(self._refresh_sku_panel)
        self._current_product_context: Optional[Dict[str, Any]] = None
        self._build_ui()
        self._load_saved_settings()
        self._load_persisted_sessions()

    def set_product_widget(self, product_widget: Any) -> None:
        self.product_widget = product_widget
        self._refresh_sku_panel()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        settings_group = QGroupBox("設定（毎回使う定型文・保存されます）")
        settings_form = QFormLayout(settings_group)
        self.intro_edit = QLineEdit()
        self.intro_edit.setPlaceholderText("例）○○ストア　商品担当の○○です。")
        settings_form.addRow("最初のテキスト:", self.intro_edit)
        self.outro_edit = QLineEdit()
        self.outro_edit.setPlaceholderText("例）今後とも○○ストアをよろしくお願いいたします。")
        settings_form.addRow("最後のテキスト:", self.outro_edit)
        save_settings_btn = QPushButton("定型文を保存")
        save_settings_btn.clicked.connect(self._save_settings)
        settings_form.addRow("", save_settings_btn)
        layout.addWidget(settings_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- 左: チャット履歴 ---
        sidebar = QWidget()
        sidebar.setMinimumWidth(200)
        sidebar.setMaximumWidth(320)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 8, 0)

        sidebar_header = QLabel("チャット履歴")
        sidebar_header.setStyleSheet("font-weight: bold; padding: 4px 0;")
        sidebar_layout.addWidget(sidebar_header)

        new_chat_btn = QPushButton("＋ 新規チャット")
        new_chat_btn.clicked.connect(self._show_new_chat_form)
        new_chat_btn.setStyleSheet(
            "background-color: #007bff; color: white; padding: 6px 12px; border-radius: 4px;"
        )
        sidebar_layout.addWidget(new_chat_btn)

        self.session_list = QListWidget()
        self.session_list.setStyleSheet(_SIDEBAR_STYLE)
        self.session_list.itemClicked.connect(self._on_session_item_clicked)
        sidebar_layout.addWidget(self.session_list, 1)

        self.session_count_label = QLabel("0件")
        self.session_count_label.setStyleSheet("color: #888; font-size: 11px;")
        sidebar_layout.addWidget(self.session_count_label)

        splitter.addWidget(sidebar)

        # --- 右: 新規入力 or チャット ---
        self.right_stack = QStackedWidget()

        self.new_case_page = QWidget()
        self._build_new_case_page(self.new_case_page)
        self.right_stack.addWidget(self.new_case_page)

        self.chat_panel = CustomerSupportChatPanel()
        self.chat_panel.session_updated.connect(self._on_active_session_updated)
        self.right_stack.addWidget(self.chat_panel)

        splitter.addWidget(self.right_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 720])

        layout.addWidget(splitter, 1)

        api_hint = QLabel(
            "※ AI生成には設定タブの Gemini APIキーが必要です。生成文案は下書きです。送信前に必ず内容を確認してください。"
        )
        api_hint.setWordWrap(True)
        api_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(api_hint)

        self._show_new_chat_form()

    def _build_new_case_page(self, page: QWidget) -> None:
        case_layout = QVBoxLayout(page)

        case_group = QGroupBox("新規案件入力")
        form_layout = QVBoxLayout(case_group)

        customer_name_row = QHBoxLayout()
        customer_name_row.addWidget(QLabel("カスタマー名:"))
        self.customer_name_edit = QLineEdit()
        self.customer_name_edit.setPlaceholderText("例）田中（「様」は自動で付きます）")
        customer_name_row.addWidget(self.customer_name_edit, 1)
        form_layout.addLayout(customer_name_row)

        sku_row = QHBoxLayout()
        sku_row.addWidget(QLabel("SKU:"))
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("SKUを入力すると仕入DBの商品情報を表示")
        self.sku_edit.textChanged.connect(self._on_sku_changed)
        sku_row.addWidget(self.sku_edit, 1)
        form_layout.addLayout(sku_row)

        self.product_info_label = QLabel("SKUに一致する商品があればここに表示されます")
        self.product_info_label.setWordWrap(True)
        self.product_info_label.setAlignment(Qt.AlignTop)
        self.product_info_label.setStyleSheet("padding: 4px;")
        form_layout.addWidget(self.product_info_label)

        self.product_images_group = QGroupBox("商品画像（クリックでプレビュー）")
        self.product_images_group.setStyleSheet(_IMAGE_ROW_STYLE)
        self.product_images_layout = QVBoxLayout(self.product_images_group)
        self.product_images_layout.setContentsMargins(8, 10, 8, 8)
        self.product_images_layout.setSpacing(6)
        self.product_images_empty_label = QLabel("SKUを入力するとローカル画像リンクが表示されます")
        self.product_images_empty_label.setObjectName("customerSupportImageHint")
        self.product_images_layout.addWidget(self.product_images_empty_label)
        form_layout.addWidget(self.product_images_group)

        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("対応方針:"))
        self.policy_combo = QComboBox()
        for key, label in RESPONSE_POLICY_LABELS.items():
            self.policy_combo.addItem(label, key)
        policy_row.addWidget(self.policy_combo, 1)
        form_layout.addLayout(policy_row)

        form_layout.addWidget(QLabel("対応方法（追加指示）:"))
        self.extra_instructions_edit = QTextEdit()
        self.extra_instructions_edit.setPlaceholderText(
            "プルダウン未選択時や、より細かい指示がある場合に入力"
        )
        self.extra_instructions_edit.setMaximumHeight(80)
        form_layout.addWidget(self.extra_instructions_edit)

        form_layout.addWidget(QLabel("カスタマーメッセージ:"))
        self.customer_message_edit = QTextEdit()
        self.customer_message_edit.setPlaceholderText(
            "カスタマーからのメッセージをコピペまたは入力"
        )
        self.customer_message_edit.setMinimumHeight(120)
        form_layout.addWidget(self.customer_message_edit)

        action_row = QHBoxLayout()
        start_btn = QPushButton("チャットを開始")
        start_btn.clicked.connect(self._start_chat)
        start_btn.setStyleSheet(
            "background-color: #28a745; color: white; padding: 8px 16px; border-radius: 4px;"
        )
        action_row.addWidget(start_btn)

        clear_btn = QPushButton("入力をクリア")
        clear_btn.clicked.connect(self._clear_case_inputs)
        clear_btn.setStyleSheet(
            "background-color: #6c757d; color: white; padding: 8px 16px; border-radius: 4px;"
        )
        action_row.addWidget(clear_btn)
        form_layout.addLayout(action_row)

        case_layout.addWidget(case_group, 1)

    def _load_saved_settings(self) -> None:
        data = load_customer_support_settings()
        self.intro_edit.setText(data.get("intro_text", ""))
        self.outro_edit.setText(data.get("outro_text", ""))

    def _save_settings(self) -> None:
        save_customer_support_settings(
            self.intro_edit.text(),
            self.outro_edit.text(),
        )
        QMessageBox.information(self, "保存", "最初・最後のテキストを保存しました。")

    def _on_sku_changed(self) -> None:
        self._sku_lookup_timer.stop()
        self._sku_lookup_timer.start(350)

    def _clear_image_links(self) -> None:
        while self.product_images_layout.count():
            item = self.product_images_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_image_links_placeholder(self, text: str) -> None:
        self._clear_image_links()
        hint = QLabel(text)
        hint.setObjectName("customerSupportImageHint")
        hint.setWordWrap(True)
        self.product_images_layout.addWidget(hint)

    def _rebuild_image_links(self, image_paths: List[Dict[str, Any]]) -> None:
        self._clear_image_links()
        if not image_paths:
            self._set_image_links_placeholder("ローカル画像が見つかりませんでした")
            return
        for entry in image_paths:
            slot = entry.get("slot", "")
            path = entry.get("path", "")
            label = entry.get("label") or Path(path).name
            if not path:
                continue

            row = QFrame()
            row.setObjectName("customerSupportImageRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 8, 4)
            row_layout.setSpacing(10)

            slot_label = QLabel(f"画像{slot}")
            slot_label.setObjectName("customerSupportImageSlot")
            row_layout.addWidget(slot_label, 0)

            link_label = _ClickableImageLink(label)
            link_label.setToolTip(f"クリックで画像を開く\n{path}")
            link_label.clicked.connect(
                lambda p=path, s=slot: self._open_image_preview(p, s)
            )
            row_layout.addWidget(link_label, 1)

            self.product_images_layout.addWidget(row)

    def _open_image_preview(self, file_path: str, slot: Any = "") -> None:
        image_file = Path(file_path)
        if not image_file.is_file():
            QMessageBox.warning(self, "警告", f"画像ファイルが見つかりません:\n{file_path}")
            return
        dialog = QDialog(self)
        title = f"画像{slot}: {image_file.name}" if slot else image_file.name
        dialog.setWindowTitle(title)
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(image_file))
        if pixmap.isNull():
            label.setText("画像を読み込めませんでした。")
        else:
            scaled = pixmap.scaled(
                800, 600,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
        layout.addWidget(label)
        dialog.exec()

    def _refresh_sku_panel(self) -> None:
        sku = self.sku_edit.text().strip()
        if not sku:
            self._current_product_context = None
            self.product_info_label.setText("SKUに一致する商品があればここに表示されます")
            self._set_image_links_placeholder("SKUを入力するとローカル画像リンクが表示されます")
            return
        ctx = lookup_sku_context(sku, product_widget=self.product_widget)
        self._current_product_context = ctx
        if ctx:
            self.product_info_label.setText(format_sku_context_for_display(ctx))
            self._rebuild_image_links(ctx.get("image_paths") or [])
        else:
            self.product_info_label.setText(
                f"SKU「{sku}」に一致する仕入DBデータが見つかりませんでした。\n"
                "チャット自体は開始できます（商品情報なし）。"
            )
            self._set_image_links_placeholder("SKUを入力するとローカル画像リンクが表示されます")

    def _update_session_count_label(self) -> None:
        n = len(self._session_order)
        self.session_count_label.setText(f"{n}件（最大10件保存）")

    def _load_persisted_sessions(self) -> None:
        self._sessions, self._session_order = load_customer_support_sessions()
        self._rebuild_session_list_ui()
        self._update_session_count_label()

    def _persist_sessions(self) -> None:
        order = [
            cid
            for cid in self._session_order
            if is_persistable_session(self._sessions.get(cid) or {})
        ]
        save_customer_support_sessions(self._sessions, order)

    def _rebuild_session_list_ui(self, select_case_id: Optional[str] = None) -> None:
        self.session_list.blockSignals(True)
        self.session_list.clear()
        for case_id in self._session_order:
            session = self._sessions.get(case_id)
            if not session:
                continue
            list_item = QListWidgetItem(_session_list_title(session))
            list_item.setData(Qt.ItemDataRole.UserRole, case_id)
            self.session_list.addItem(list_item)
        if select_case_id:
            for i in range(self.session_list.count()):
                item = self.session_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == select_case_id:
                    self.session_list.setCurrentItem(item)
                    break
        self.session_list.blockSignals(False)

    def _refresh_product_context_for_session(self, session: Dict[str, Any]) -> None:
        sku = (session.get("sku") or "").strip()
        if sku:
            session["product_context"] = lookup_sku_context(
                sku, product_widget=self.product_widget
            )
        else:
            session["product_context"] = None

    def _on_active_session_updated(self) -> None:
        if not self._current_case_id:
            return
        self._session_order = touch_session(
            self._sessions, self._session_order, self._current_case_id
        )
        self._rebuild_session_list_ui(select_case_id=self._current_case_id)
        self._update_session_count_label()
        self._persist_sessions()

    def _show_new_chat_form(self) -> None:
        self.session_list.clearSelection()
        self._current_case_id = None
        self.right_stack.setCurrentWidget(self.new_case_page)

    def _open_session(self, case_id: str) -> None:
        session = self._sessions.get(case_id)
        if not session:
            return
        self._refresh_product_context_for_session(session)
        self._current_case_id = case_id
        self.chat_panel.bind_session(session)
        self.right_stack.setCurrentWidget(self.chat_panel)

    def _on_session_item_clicked(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        case_id = item.data(Qt.ItemDataRole.UserRole)
        if not case_id:
            return
        self.session_list.setCurrentItem(item)
        self._open_session(str(case_id))

    def _clear_case_inputs(self) -> None:
        """案件入力エリアをクリア（設定の定型文は残す）。"""
        self.customer_name_edit.clear()
        self.sku_edit.clear()
        self.product_info_label.setText("SKUに一致する商品があればここに表示されます")
        self._set_image_links_placeholder("SKUを入力するとローカル画像リンクが表示されます")
        self._current_product_context = None
        self.policy_combo.setCurrentIndex(0)
        self.extra_instructions_edit.clear()
        self.customer_message_edit.clear()

    def _start_chat(self) -> None:
        customer_message = self.customer_message_edit.toPlainText().strip()
        if not customer_message:
            QMessageBox.warning(self, "入力", "カスタマーメッセージを入力してください。")
            return

        service = GeminiCustomerSupportService()
        if not service.is_available():
            QMessageBox.warning(
                self,
                "API未設定",
                service.last_error
                or "Gemini APIキーが設定されていません。\n"
                "設定タブの「Gemini APIキー」を入力して保存してください。",
            )
            return

        case_id = str(uuid.uuid4())[:8]
        policy_key = self.policy_combo.currentData() or ""
        policy_label = self.policy_combo.currentText()

        session: Dict[str, Any] = {
            "case_id": case_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "customer_name": self.customer_name_edit.text().strip(),
            "sku": self.sku_edit.text().strip(),
            "policy_key": policy_key,
            "policy_label": policy_label,
            "extra_instructions": self.extra_instructions_edit.toPlainText().strip(),
            "intro_text": self.intro_edit.text().strip(),
            "outro_text": self.outro_edit.text().strip(),
            "product_context": self._current_product_context,
            "history": [],
            "latest_full_reply": "",
        }
        self._sessions[case_id] = session
        self._session_order = touch_session(self._sessions, self._session_order, case_id)

        self._rebuild_session_list_ui(select_case_id=case_id)
        self._open_session(case_id)
        self.chat_panel.begin_with_customer_message(customer_message)

        self._update_session_count_label()
        self._persist_sessions()
        self._clear_case_inputs()

    def save_sessions(self) -> None:
        """チャット履歴をディスクへ保存（アプリ終了時にも呼ばれる）。"""
        self._persist_sessions()

    def closeEvent(self, event) -> None:
        self.save_sessions()
        super().closeEvent(event)
