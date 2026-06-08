#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIのチャットパネル（タブ内埋め込み用）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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
                    self._service.last_error
                    or "Gemini APIが利用できません。設定タブでAPIキーを確認してください。"
                )
                return
            body, error = self._service.generate_reply(
                customer_message=self._customer_message,
                product_context=self._product_context,
                policy_key=self._policy_key,
                extra_instructions=self._extra_instructions,
                customer_name=self._customer_name,
                chat_history=self._chat_history,
            )
            if not body:
                self.finished_error.emit(error or "返信文案の生成に失敗しました。")
                return
            self.finished_ok.emit(body)
        except Exception as exc:
            self.finished_error.emit(str(exc))


class CustomerSupportChatPanel(QWidget):
    """1案件分のチャット表示・生成（親ウィジェットの右ペインに配置）。"""

    session_updated = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._session: Optional[Dict[str, Any]] = None
        self._service = GeminiCustomerSupportService()
        self._worker: Optional[_GenerateReplyThread] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.meta_label = QLabel("チャットを選択するか、新規チャットを開始してください")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: #adb5bd; padding: 4px 0;")
        layout.addWidget(self.meta_label)

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

    def bind_session(self, session: Dict[str, Any]) -> None:
        """案件データを読み込み、会話表示を再構築する。"""
        self._session = session
        session.setdefault("history", [])
        session.setdefault("latest_full_reply", "")
        self._refresh_meta_label()
        self.transcript_edit.clear()
        self.followup_edit.clear()
        for item in session.get("history") or []:
            self._append_message_ui(item.get("role", ""), item.get("text", ""))
        self.status_label.setText("")

    def begin_with_customer_message(self, message: str) -> None:
        """新規案件の初回メッセージで会話を開始し、返信を生成する。"""
        text = (message or "").strip()
        if not text:
            return
        self._append_message("customer", text)
        self._generate_reply(text)

    def _refresh_meta_label(self) -> None:
        if not self._session:
            self.meta_label.setText("チャットを選択するか、新規チャットを開始してください")
            return
        parts: List[str] = []
        name = (self._session.get("customer_name") or "").strip()
        sku = (self._session.get("sku") or "").strip()
        policy = (self._session.get("policy_label") or "").strip()
        if name:
            parts.append(f"カスタマー: {name}")
        if sku:
            parts.append(f"SKU: {sku}")
        if policy:
            parts.append(f"方針: {policy}")
        self.meta_label.setText(" / ".join(parts) if parts else "案件チャット")

    def _history(self) -> List[Dict[str, str]]:
        if not self._session:
            return []
        hist = self._session.get("history")
        if not isinstance(hist, list):
            hist = []
            self._session["history"] = hist
        return hist

    def _append_message(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._history().append({"role": role, "text": text})
        self._append_message_ui(role, text)
        self.session_updated.emit()

    def _append_message_ui(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        header = "【カスタマー】" if role == "customer" else "【AI返信案】"
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
        if not self._session:
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "処理中", "生成中です。しばらくお待ちください。")
            return

        history = self._history()
        history_for_api = history[:-1] if history else []

        self._set_busy(True, "AIが返信文案を生成しています...")
        self._worker = _GenerateReplyThread(
            self._service,
            customer_message=customer_message,
            product_context=self._session.get("product_context"),
            policy_key=self._session.get("policy_key") or "",
            extra_instructions=self._session.get("extra_instructions") or "",
            customer_name=self._session.get("customer_name") or "",
            chat_history=history_for_api,
            parent=self,
        )
        self._worker.finished_ok.connect(self._on_generate_ok)
        self._worker.finished_error.connect(self._on_generate_error)
        self._worker.finished.connect(lambda: self._set_busy(False, ""))
        self._worker.start()

    def _on_generate_ok(self, body: str) -> None:
        if not self._session:
            return
        full_reply = apply_intro_outro(
            body,
            self._session.get("intro_text") or "",
            self._session.get("outro_text") or "",
            self._session.get("customer_name") or "",
        )
        self._session["latest_full_reply"] = full_reply
        self._append_message("assistant", full_reply)

    def _on_generate_error(self, message: str) -> None:
        QMessageBox.warning(self, "生成エラー", message)

    def _copy_latest_reply(self) -> None:
        if not self._session:
            return
        reply = (self._session.get("latest_full_reply") or "").strip()
        if not reply:
            QMessageBox.information(self, "コピー", "まだコピーできる返信がありません。")
            return
        QGuiApplication.clipboard().setText(reply)
        self.status_label.setText("クリップボードにコピーしました")


# 後方互換（他モジュールからの参照用）
CustomerSupportChatWindow = CustomerSupportChatPanel
