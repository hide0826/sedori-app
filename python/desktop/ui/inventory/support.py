#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫 UI の定数・ヘルパー・AI Thread。"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from html import escape

from PySide6.QtCore import QThread, Signal
_PRICETAR_BROWSER_TITLE_KEYWORDS = ["pricetar", "プライスター"]

_WORKFLOW_PIPELINE_SEGMENTS = [
    "①CSV取込",
    "②ルートテンプレート読込",
    "③照合処理実行",
    "④SKU生成",
    "⑤コンディション説明編集",
    "⑥DB保存",
    "⑦古物台帳生成",
    "⑧出品CSV生成",
]
_WORKFLOW_PIPELINE_SEP = "\u2010"
_ACTION_TO_PIPELINE_STEP = {
    "CSV取込": 1,
    "ルートテンプレ読込": 2,
    "照合処理実行": 3,
    "SKU生成": 4,
    "DB保存": 6,
    "古物台帳生成": 7,
    "出品CSV生成": 8,
}


def _format_status_prefix_html(text: str, emphasize: bool) -> str:
    """ワークフロー行の左側（手順リストより前）。"""
    if not emphasize:
        return f'<span style="color:#cccccc;">{escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{escape(text)}</span>'


def _format_workflow_pipeline_html(active_step: Optional[int]) -> str:
    parts: List[str] = []
    for i, seg in enumerate(_WORKFLOW_PIPELINE_SEGMENTS, start=1):
        esc = escape(seg)
        if active_step == i:
            parts.append(
                f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>'
            )
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _WORKFLOW_PIPELINE_SEP.join(parts)


def _normalize_condition_note_newlines(s: str) -> str:
    """DBなどでリテラル '\\n' として保存された改行を実際の改行に変換（表示用）"""
    if not s:
        return ""
    return str(s).replace("\\n", "\n")


def _to_stored_newlines(s: str) -> str:
    """実際の改行をリテラル '\\n' に変換（保存用・1行表示で行区切りに\\nが入る形）"""
    if not s:
        return ""
    return str(s).replace("\r\n", "\n").replace("\n", "\\n").replace("\r", "\\n")


def _is_repricing_enabled_value(value: Any) -> bool:
    """価格改定のON/OFF値をboolに正規化。未設定はON扱い。"""
    if value is None:
        return True
    s = str(value).strip().lower()
    if s == "":
        return True
    return s not in {"0", "off", "false", "無効", "いいえ", "no"}


SALES_CHANNEL_OPTIONS = ["Amazon", "メルカリ", "ヤフオク", "ラクマ", "その他"]
SHIPPING_METHOD_OPTIONS = ["FBA", "自己発送"]

class _ConditionNoteAiGenerateThread(QThread):
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(
        self,
        *,
        condition_label: str,
        condition_template: str,
        missing_items: List[Dict[str, str]],
        other_details: str,
        product_name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._condition_label = condition_label
        self._condition_template = condition_template
        self._missing_items = missing_items
        self._other_details = other_details
        self._product_name = product_name

    def run(self) -> None:
        try:
            try:
                from services.gemini_condition_description_service import (
                    GeminiConditionDescriptionService,
                )
            except ImportError:
                from desktop.services.gemini_condition_description_service import (  # type: ignore
                    GeminiConditionDescriptionService,
                )
            svc = GeminiConditionDescriptionService()
            if not svc.is_available():
                self.finished_error.emit(
                    svc.last_error
                    or "Gemini API が利用できません。\n"
                    "設定タブで API キーを登録するか、pip install google-generativeai を確認してください。"
                )
                return
            result, error = svc.generate(
                condition_label=self._condition_label,
                condition_template=self._condition_template,
                missing_items=self._missing_items,
                other_details=self._other_details,
                product_name=self._product_name,
            )
            if not result:
                self.finished_error.emit(error or "コンディション説明の生成に失敗しました。")
                return
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_error.emit(str(exc))

