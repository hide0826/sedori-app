#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIタブ（案件起動・設定・SKU連携）。"""
from __future__ import annotations

import uuid
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
    QMessageBox,
    QPushButton,
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
    from services.customer_support_sku_lookup import (
        format_sku_context_for_display,
        lookup_sku_context,
    )
    from services.gemini_customer_support_service import (
        RESPONSE_POLICY_LABELS,
        GeminiCustomerSupportService,
    )
    from ui.customer_support_chat_window import CustomerSupportChatWindow
except ImportError:
    from desktop.services.customer_support_settings import (  # type: ignore
        load_customer_support_settings,
        save_customer_support_settings,
    )
    from desktop.services.customer_support_sku_lookup import (  # type: ignore
        format_sku_context_for_display,
        lookup_sku_context,
    )
    from desktop.services.gemini_customer_support_service import (  # type: ignore
        RESPONSE_POLICY_LABELS,
        GeminiCustomerSupportService,
    )
    from desktop.ui.customer_support_chat_window import CustomerSupportChatWindow  # type: ignore


class CustomerSupportWidget(QWidget):
    def __init__(self, product_widget: Any = None, parent=None):
        super().__init__(parent)
        self.product_widget = product_widget
        self._chat_windows: Dict[str, CustomerSupportChatWindow] = {}
        self._sku_lookup_timer = QTimer(self)
        self._sku_lookup_timer.setSingleShot(True)
        self._sku_lookup_timer.timeout.connect(self._refresh_sku_panel)
        self._current_product_context: Optional[Dict[str, Any]] = None
        self._build_ui()
        self._load_saved_settings()

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

        case_group = QGroupBox("案件入力")
        case_layout = QVBoxLayout(case_group)

        customer_name_row = QHBoxLayout()
        customer_name_row.addWidget(QLabel("カスタマー名:"))
        self.customer_name_edit = QLineEdit()
        self.customer_name_edit.setPlaceholderText("例）田中（「様」は自動で付きます）")
        customer_name_row.addWidget(self.customer_name_edit, 1)
        case_layout.addLayout(customer_name_row)

        sku_row = QHBoxLayout()
        sku_row.addWidget(QLabel("SKU:"))
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("SKUを入力すると仕入DBの商品情報を表示")
        self.sku_edit.textChanged.connect(self._on_sku_changed)
        sku_row.addWidget(self.sku_edit, 1)
        case_layout.addLayout(sku_row)

        self.product_info_label = QLabel("SKUに一致する商品があればここに表示されます")
        self.product_info_label.setWordWrap(True)
        self.product_info_label.setAlignment(Qt.AlignTop)
        self.product_info_label.setStyleSheet("padding: 4px;")
        case_layout.addWidget(self.product_info_label)

        self.product_images_group = QGroupBox("商品画像（クリックでプレビュー）")
        self.product_images_group.setStyleSheet(_IMAGE_ROW_STYLE)
        self.product_images_layout = QVBoxLayout(self.product_images_group)
        self.product_images_layout.setContentsMargins(8, 10, 8, 8)
        self.product_images_layout.setSpacing(6)
        self.product_images_empty_label = QLabel("SKUを入力するとローカル画像リンクが表示されます")
        self.product_images_empty_label.setObjectName("customerSupportImageHint")
        self.product_images_layout.addWidget(self.product_images_empty_label)
        case_layout.addWidget(self.product_images_group)

        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("対応方針:"))
        self.policy_combo = QComboBox()
        for key, label in RESPONSE_POLICY_LABELS.items():
            self.policy_combo.addItem(label, key)
        policy_row.addWidget(self.policy_combo, 1)
        case_layout.addLayout(policy_row)

        case_layout.addWidget(QLabel("対応方法（追加指示）:"))
        self.extra_instructions_edit = QTextEdit()
        self.extra_instructions_edit.setPlaceholderText(
            "プルダウン未選択時や、より細かい指示がある場合に入力"
        )
        self.extra_instructions_edit.setMaximumHeight(80)
        case_layout.addWidget(self.extra_instructions_edit)

        case_layout.addWidget(QLabel("カスタマーメッセージ:"))
        self.customer_message_edit = QTextEdit()
        self.customer_message_edit.setPlaceholderText(
            "カスタマーからのメッセージをコピペまたは入力"
        )
        self.customer_message_edit.setMinimumHeight(120)
        case_layout.addWidget(self.customer_message_edit)

        action_row = QHBoxLayout()
        start_btn = QPushButton("チャットを開始（別ウィンドウ）")
        start_btn.clicked.connect(self._start_chat_window)
        start_btn.setStyleSheet(
            "background-color: #007bff; color: white; padding: 8px 16px; border-radius: 4px;"
        )
        action_row.addWidget(start_btn)

        clear_btn = QPushButton("入力をクリア")
        clear_btn.clicked.connect(self._clear_case_inputs)
        clear_btn.setStyleSheet(
            "background-color: #6c757d; color: white; padding: 8px 16px; border-radius: 4px;"
        )
        action_row.addWidget(clear_btn)
        case_layout.addLayout(action_row)

        self.open_cases_label = QLabel("進行中のチャット: 0件")
        self.open_cases_label.setStyleSheet("color: #888;")
        case_layout.addWidget(self.open_cases_label)

        layout.addWidget(case_group, 1)

        api_hint = QLabel(
            "※ AI生成には設定タブの Gemini APIキーが必要です。生成文案は下書きです。送信前に必ず内容を確認してください。"
        )
        api_hint.setWordWrap(True)
        api_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(api_hint)

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
            scaled = pixmap.scaled(800, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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

    def _update_open_cases_label(self) -> None:
        count = len(self._chat_windows)
        self.open_cases_label.setText(f"進行中のチャット: {count}件")

    def _on_chat_window_closed(self, case_id: str) -> None:
        self._chat_windows.pop(case_id, None)
        self._update_open_cases_label()

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

    def _start_chat_window(self) -> None:
        customer_message = self.customer_message_edit.toPlainText().strip()
        if not customer_message:
            QMessageBox.warning(self, "入力", "カスタマーメッセージを入力してください。")
            return

        service = GeminiCustomerSupportService()
        if not service.is_available():
            QMessageBox.warning(
                self,
                "API未設定",
                "Gemini APIキーが設定されていません。\n"
                "設定タブの OCR設定 内「Gemini APIキー」を入力して保存してください。",
            )
            return

        case_id = str(uuid.uuid4())[:8]
        policy_key = self.policy_combo.currentData() or ""
        policy_label = self.policy_combo.currentText()

        window = CustomerSupportChatWindow(
            case_id,
            sku=self.sku_edit.text().strip(),
            policy_key=policy_key,
            policy_label=policy_label,
            extra_instructions=self.extra_instructions_edit.toPlainText(),
            customer_name=self.customer_name_edit.text().strip(),
            intro_text=self.intro_edit.text(),
            outro_text=self.outro_edit.text(),
            product_context=self._current_product_context,
            initial_customer_message=customer_message,
        )
        window.window_closed.connect(self._on_chat_window_closed)
        self._chat_windows[case_id] = window
        self._update_open_cases_label()
        window.show()
        window.raise_()
        window.activateWindow()
