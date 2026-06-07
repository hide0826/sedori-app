#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIの案件別チャットウィンドウ（別ウィンドウ）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from services.customer_support_settings import apply_intro_outro
    from services.gemini_customer_support_service import GeminiCustomerSupportService
except ImportError:
    from desktop.services.customer_support_settings import apply_intro_outro  # type: ignore
    from desktop.services.gemini_customer_support_service import (  # type: ignore
        GeminiCustomerSupportService,
    )


class _GenerateReplyThread(QThread):
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(
        self,
        service: GeminiCustomerSupportService,
        *,
        customer_message: str,
        product_context: Optional[Dict[str, Any]],
        policy_key: str,
        extra_instructions: str,
        customer_name: str,
        chat_history: List[Dict[str, str]],
        parent=None,
    ):
        super().__init__(parent)
        self._service = service
        self._customer_message = customer_message
        self._product_context = product_context
        self._policy_key = policy_key
        self._extra_instructions = extra_instructions
        self._customer_name = customer_name
        self._chat_history = chat_history

    def run(self) -> None:
        try:
            if not self._service.is_available():
                self.finished_error.emit(
                    "Gemini APIが利用できません。設定タブでAPIキーを確認してください。"
                )
                return
            body = self._service.generate_reply(
                customer_message=self._customer_message,
                product_context=self._product_context,
                policy_key=self._policy_key,
                extra_instructions=self._extra_instructions,
                customer_name=self._customer_name,
                chat_history=self._chat_history,
            )
            if not body:
                self.finished_error.emit("返信文案の生成に失敗しました。")
                return
            self.finished_ok.emit(body)
        except Exception as exc:
            self.finished_error.emit(str(exc))


class CustomerSupportChatWindow(QMainWindow):
    """1案件＝1ウィンドウのカスタマー対応チャット。"""

    window_closed = Signal(str)

    def __init__(
        self,
        case_id: str,
        *,
        sku: str = "",
        policy_key: str = "",
        policy_label: str = "",
        extra_instructions: str = "",
        customer_name: str = "",
        intro_text: str = "",
        outro_text: str = "",
        product_context: Optional[Dict[str, Any]] = None,
        initial_customer_message: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.case_id = case_id
        self.customer_name = (customer_name or "").strip()
        self.sku = (sku or "").strip()
        self.policy_key = policy_key or ""
        self.policy_label = policy_label or ""
        self.extra_instructions = (extra_instructions or "").strip()
        self.intro_text = (intro_text or "").strip()
        self.outro_text = (outro_text or "").strip()
        self.product_context = product_context
        self._service = GeminiCustomerSupportService()
        self._history: List[Dict[str, str]] = []
        self._worker: Optional[_GenerateReplyThread] = None

        title_bits = ["カスタマー対応"]
        if self.sku:
            title_bits.append(self.sku)
        self.setWindowTitle(" / ".join(title_bits))
        self.resize(760, 640)
        self._build_ui()

        if (initial_customer_message or "").strip():
            self._append_message("customer", initial_customer_message.strip())
            self._generate_reply(initial_customer_message.strip())

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        meta_parts = []
        if self.customer_name:
            meta_parts.append(f"カスタマー: {self.customer_name}")
        if self.sku:
            meta_parts.append(f"SKU: {self.sku}")
        if self.policy_label:
            meta_parts.append(f"方針: {self.policy_label}")
        meta_label = QLabel(" / ".join(meta_parts) if meta_parts else "案件チャット")
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)

        self.transcript_edit = QTextEdit()
        self.transcript_edit.setReadOnly(True)
        self.transcript_edit.setPlaceholderText("会話とAI返信案がここに表示されます")
        layout.addWidget(self.transcript_edit, 1)

        layout.addWidget(QLabel("カスタマーの追加メッセージ:"))
        self.followup_edit = QTextEdit()
        self.followup_edit.setPlaceholderText("ラリーが続く場合、カスタマーの追いメッセージを入力")
        self.followup_edit.setMaximumHeight(100)
        layout.addWidget(self.followup_edit)

        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("返信を生成")
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        self.generate_btn.setStyleSheet("background-color: #28a745; color: white; padding: 6px 14px;")
        btn_row.addWidget(self.generate_btn)

        self.copy_btn = QPushButton("最新返信をコピー")
        self.copy_btn.clicked.connect(self._copy_latest_reply)
        btn_row.addWidget(self.copy_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        btn_row.addWidget(self.status_label, 1)
        layout.addLayout(btn_row)

        self._latest_full_reply = ""

    def closeEvent(self, event) -> None:
        self.window_closed.emit(self.case_id)
        super().closeEvent(event)

    def _append_message(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._history.append({"role": role, "text": text})
        if role == "customer":
            header = "【カスタマー】"
        else:
            header = "【AI返信案】"
        block = f"{header}\n{text}\n"
        cursor = self.transcript_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.transcript_edit.setTextCursor(cursor)
        self.transcript_edit.insertPlainText(block + "\n")
        self.transcript_edit.ensureCursorVisible()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.generate_btn.setEnabled(not busy)
        self.followup_edit.setEnabled(not busy)
        self.status_label.setText(message)

    def _on_generate_clicked(self) -> None:
        message = self.followup_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "入力", "カスタマーのメッセージを入力してください。")
            return
        self.followup_edit.clear()
        self._append_message("customer", message)
        self._generate_reply(message)

    def _generate_reply(self, customer_message: str) -> None:
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "処理中", "生成中です。しばらくお待ちください。")
            return

        history_for_api = self._history[:-1] if self._history else []

        self._set_busy(True, "AIが返信文案を生成しています...")
        self._worker = _GenerateReplyThread(
            self._service,
            customer_message=customer_message,
            product_context=self.product_context,
            policy_key=self.policy_key,
            extra_instructions=self.extra_instructions,
            customer_name=self.customer_name,
            chat_history=history_for_api,
            parent=self,
        )
        self._worker.finished_ok.connect(self._on_generate_ok)
        self._worker.finished_error.connect(self._on_generate_error)
        self._worker.finished.connect(lambda: self._set_busy(False, ""))
        self._worker.start()

    def _on_generate_ok(self, body: str) -> None:
        full_reply = apply_intro_outro(
            body,
            self.intro_text,
            self.outro_text,
            self.customer_name,
        )
        self._latest_full_reply = full_reply
        self._append_message("assistant", full_reply)

    def _on_generate_error(self, message: str) -> None:
        QMessageBox.warning(self, "生成エラー", message)

    def _copy_latest_reply(self) -> None:
        if not self._latest_full_reply:
            QMessageBox.information(self, "コピー", "まだコピーできる返信がありません。")
            return
        QGuiApplication.clipboard().setText(self._latest_full_reply)
        self.status_label.setText("クリップボードにコピーしました")
