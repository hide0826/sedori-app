#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini による Amazon カスタマー対応返信文案の生成。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

RESPONSE_POLICY_LABELS: Dict[str, str] = {
    "": "（プルダウン未選択・自由入力のみ）",
    "return_request": "返品を促す",
    "refund": "返金対応",
    "amazon_cs": "Amazonカスタマーセンターへの連絡を促す",
    "decline_claim": "クレーマー対応（要求拒否）",
}

RESPONSE_POLICY_INSTRUCTIONS: Dict[str, str] = {
    "return_request": (
        "【対応方針: 返品を促す】\n"
        "購入者に対し、Amazonの返品手続きに沿って返品いただくよう丁寧に案内する。"
        "必要な確認事項（注文番号・到着状況・返品理由）があれば質問する。"
        "セラーとして誠実に対応する姿勢を示す。"
    ),
    "refund": (
        "【対応方針: 返金対応】\n"
        "返金の方針・手続き・確認事項を整理し、購入者に分かりやすく案内する。"
        "Amazonのルールに沿い、過剰な約束はしない。"
    ),
    "amazon_cs": (
        "【対応方針: Amazonカスタマーセンターへ誘導】\n"
        "セラー単独では解決が難しい案件として、Amazonカスタマーサービスへの連絡を促す。"
        "購入者の不満に共感しつつ、適切な窓口を案内する。"
    ),
    "decline_claim": (
        "【対応方針: クレーマー対応・要求拒否】\n"
        "礼儀正しい敬語を維持しつつ、不当な要求や過剰なクレームには明確に線引きする。"
        "事実関係を整理し、ポリシーに基づく説明を行う。感情的にならない。"
    ),
}

SYSTEM_PROMPT = """
あなたは日本のAmazonマーケットプレイス出品者のカスタマーサポート担当です。
購入者（カスタマー）からの問い合わせ・クレームに対し、セラーが送信する返信文案を作成します。

ルール:
- 日本語の丁寧なビジネス敬語（です・ます調）を使用する。
- 購入者の感情に配慮し、共感の一文を適宜入れる。
- 事実が不明な点は推測で断定せず、確認質問を入れる。
- Amazonのポリシーに反する表現（外部サイト誘導の強要、個人情報の不必要な要求など）は避ける。
- 返信文案の本文のみを出力する（説明・前置き・JSON・マークダウン見出しは不要）。
- 冒頭の「○○様」や自己紹介、締めの定型文は本文に含めない（システム側で付与する）。
- 購入者名で呼びかけない（システム側で「○○様」を付与する）。
""".strip()


def _format_product_block(ctx: Optional[Dict[str, Any]]) -> str:
    if not ctx:
        return "（商品情報: SKUに該当する仕入DBデータなし）"
    lines = [
        f"SKU: {ctx.get('sku', '')}",
        f"ASIN: {ctx.get('asin') or '不明'}",
        f"商品名: {ctx.get('product_name') or '不明'}",
        f"仕入れ価格: {ctx.get('purchase_price') if ctx.get('purchase_price') is not None else '不明'} 円",
        f"販売予定価格: {ctx.get('planned_price') if ctx.get('planned_price') is not None else '不明'} 円",
        f"発送方法: {ctx.get('shipping_method') or '不明'}",
        f"コメント（社内メモ）: {ctx.get('comment') or 'なし'}",
    ]
    paths = ctx.get("image_paths") or []
    for item in paths[:6]:
        slot = item.get("slot", "")
        label = item.get("label") or item.get("path") or ""
        lines.append(f"画像{slot}（ローカル）: {label}")
    return "\n".join(lines)


def _history_to_gemini(history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """UI履歴を Gemini chat history 形式へ。"""
    result: List[Dict[str, Any]] = []
    for item in history:
        role = item.get("role", "")
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if role == "customer":
            result.append({"role": "user", "parts": [{"text": f"【カスタマーからのメッセージ】\n{text}"}]})
        elif role == "assistant":
            result.append({"role": "model", "parts": [{"text": text}]})
    return result


class GeminiCustomerSupportService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name or self._default_model_name()
        self.last_error = ""
        self._configure()

    @staticmethod
    def _default_model_name() -> str:
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        return resolve_gemini_flash_model()

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

    def generate_reply(
        self,
        *,
        customer_message: str,
        product_context: Optional[Dict[str, Any]] = None,
        policy_key: str = "",
        extra_instructions: str = "",
        customer_name: str = "",
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[Optional[str], str]:
        """返信文案（定型文なしの本文）を生成する。戻り値は (本文, エラーメッセージ)。"""
        self.last_error = ""
        if not self.is_available():
            return None, self.last_error or "Gemini API が利用できません。"

        customer_message = (customer_message or "").strip()
        if not customer_message:
            return None, "カスタマーからのメッセージが空です。"

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

        policy_block = RESPONSE_POLICY_INSTRUCTIONS.get(policy_key, "")
        extra = (extra_instructions or "").strip()
        product_block = _format_product_block(product_context)

        context_parts = [
            "【商品情報（社内参考・購入者には直接開示しない数値も含む）】",
            product_block,
        ]
        name = (customer_name or "").strip()
        if name.endswith("様"):
            name = name[:-1].strip()
        if name:
            context_parts.append(f"【購入者名（返信冒頭の呼びかけに使用。本文には書かない）】\n{name}")
        if policy_block:
            context_parts.append(policy_block)
        if extra:
            context_parts.append(f"【追加の対応指示】\n{extra}")

        prompt = (
            "\n\n".join(context_parts)
            + "\n\n【今回のカスタマーからのメッセージ】\n"
            + customer_message
            + "\n\n上記に対するセラー返信文案を作成してください。"
        )

        history = _history_to_gemini(chat_history or [])
        generation_config = {
            "temperature": 0.35,
            "max_output_tokens": 2048,
        }

        def _invoke(model_name: str) -> Optional[str]:
            model = genai.GenerativeModel(
                model_name,
                generation_config=generation_config,
                system_instruction=SYSTEM_PROMPT,
            )
            if history:
                chat = model.start_chat(history=history)
                response = chat.send_message(prompt)
            else:
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
