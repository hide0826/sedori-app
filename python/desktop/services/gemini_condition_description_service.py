#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini による Amazon 出品用コンディション説明の生成。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
あなたは日本のAmazonマーケットプレイス出品者向けに、商品のコンディション説明文を作成するアシスタントです。

ルール:
- 日本語で、Amazon出品の「コンディション説明」欄にそのまま貼れる本文のみを出力する（前置き・解説・マークダウンは不要）。
- 参照テンプレートの文体・構成（見出し【】の使い方など）を踏襲しつつ、欠品・詳細情報を正確に反映する。
- 選択された欠品・詳細、その他詳細の内容は漏れなく記載する。ない情報は捏造しない。
- 過剰な美品表現や、事実と異なる記述はしない。
- {欠品} プレースホルダーがテンプレートにあれば、欠品情報で置き換えた形にする。
- 改行は実際の改行で出力する（\\n という文字列は使わない）。
""".strip()


def _normalize_template_newlines(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("\\n", "\n")


class GeminiConditionDescriptionService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        self.model_name = model_name or resolve_gemini_flash_model()
        self.last_error = ""
        self._configure()

    def _load_api_key(self) -> Optional[str]:
        if self.api_key:
            return str(self.api_key).strip() or None
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings("HIRIO", "DesktopApp")
            key = (settings.value("ocr/gemini_api_key", "") or "").strip()
            return key or None
        except Exception as exc:
            logger.debug("Gemini settings load failed: %s", exc)
            return None

    def _configure(self) -> None:
        self.last_error = ""
        if not GEMINI_AVAILABLE:
            self.last_error = (
                "google-generativeai がインストールされていません。\n"
                "`pip install google-generativeai` を実行してください。"
            )
            return
        self.api_key = self._load_api_key()
        if not self.api_key:
            self.last_error = "Gemini APIキーが未設定です。設定タブで API キーを登録してください。"

    def is_available(self) -> bool:
        return bool(GEMINI_AVAILABLE and self.api_key)

    def generate(
        self,
        *,
        condition_label: str,
        condition_template: str,
        missing_items: List[Dict[str, str]],
        other_details: str,
        product_name: str = "",
    ) -> Tuple[Optional[str], str]:
        """コンディション説明を生成する。戻り値は (本文, エラーメッセージ)。"""
        self.last_error = ""
        if not self.is_available():
            return None, self.last_error or "Gemini API が利用できません。"

        template = _normalize_template_newlines(condition_template or "")
        other = (other_details or "").strip()
        if not other:
            return None, "「その他詳細」が空です。"

        try:
            from utils.gemini_model_helper import (
                extract_gemini_response_text,
                run_with_flash_model_fallback,
            )
        except ImportError:
            from desktop.utils.gemini_model_helper import (  # type: ignore
                extract_gemini_response_text,
                run_with_flash_model_fallback,
            )

        missing_lines: List[str] = []
        for item in missing_items:
            label = (item.get("label") or "").strip()
            body = (item.get("text") or "").strip()
            if label and body:
                missing_lines.append(f"- {label}: {body}")
            elif label:
                missing_lines.append(f"- {label}")
            elif body:
                missing_lines.append(f"- {body}")

        missing_block = "\n".join(missing_lines) if missing_lines else "（チェックなし）"

        user_text = (
            f"商品名: {product_name or '（不明）'}\n"
            f"コンディション: {condition_label or '（不明）'}\n\n"
            f"【参照テンプレート（コンディション説明タブのコメント）】\n"
            f"{template or '（テンプレート未登録）'}\n\n"
            f"【欠品・詳細（チェック済み）】\n{missing_block}\n\n"
            f"【その他詳細（自由入力・必ず反映）】\n{other}\n\n"
            "上記を踏まえ、Amazon出品用のコンディション説明文を生成してください。"
        )
        prompt = f"{SYSTEM_PROMPT}\n\n{user_text}"

        def _invoke(model_name: str) -> Optional[str]:
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.3,
                    "max_output_tokens": 2048,
                },
            )
            response = model.generate_content(prompt)
            return extract_gemini_response_text(response) or None

        text, error, used_model = run_with_flash_model_fallback(
            self.api_key or "",
            _invoke,
            configured_model=self.model_name,
        )
        if text:
            self.model_name = used_model or self.model_name
            return text, ""
        self.last_error = error
        return None, error
