#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini によるフリマ出品文案の生成（メルカリ・ヤフフリ等向け）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    GEMINI_AVAILABLE = False

try:
    from desktop.services.flea_market_record_utils import (
        build_product_description_block,
        extract_condition_label_from_record,
        extract_condition_note_from_record,
        extract_jan_from_record,
    )
    from desktop.services.flea_market_settings import (
        apply_mandatory_footer,
        load_flea_market_ai_settings,
    )
except ImportError:
    from services.flea_market_record_utils import (  # type: ignore
        build_product_description_block,
        extract_condition_label_from_record,
        extract_condition_note_from_record,
        extract_jan_from_record,
    )
    from services.flea_market_settings import (  # type: ignore
        apply_mandatory_footer,
        load_flea_market_ai_settings,
    )

logger = logging.getLogger(__name__)

FLEA_MARKET_PROMPT = """
あなたは日本のフリマアプリ（メルカリ・ヤフフリ・ラクマ等）向けの出品文案を作成するアシスタントです。
次の商品データを読み、JSONのみを返してください（説明文やマークダウンは不可）。

出力スキーマ（すべて必須。不明は null）:
{
  "title": "出品タイトル（40文字以内、魅力的で検索されやすい）",
  "listing_description": "出品説明（商品の魅力・状態・梱包発送・注意事項を1本にまとめた本文。500〜1000文字程度。JANコード行は含めない）",
  "suggested_price": 整数または null（円。仕入・相場を踏まえた提案販売価格）
}

ルール:
- タイトルは40文字以内。絵文字は控えめ。
- コンディション説明に書かれた欠品・傷・動作確認などは listing_description に正確に反映する（嘘や過剰な美品表現はしない）。
- JANコードは本文に書かない（アプリ側で別行として付与する）。
- 中古品であることを明記する。
- 返答は有効なJSONオブジェクト1つのみ。
"""

# UI表示名 → 内部キー
FLEA_STYLE_LABELS: Dict[str, str] = {
    "標準": "standard",
    "簡潔": "concise",
    "丁寧": "polite",
}

FLEA_STYLE_INSTRUCTIONS: Dict[str, str] = {
    "standard": (
        "【文案スタイル: 標準】\n"
        "バランスの取れた丁寧さで、商品の魅力・状態・発送を分かりやすく書く。"
        "listing_description は500〜1000文字程度。"
    ),
    "concise": (
        "【文案スタイル: 簡潔】\n"
        "情報は最小限に絞る。listing_description は箇条書き（・で始める行）を中心に、"
        "200〜400文字程度。挨拶や冗長な装飾は省く。事実（状態・欠品・動作）を優先する。"
    ),
    "polite": (
        "【文案スタイル: 丁寧】\n"
        "非常に丁寧な敬語（です・ます調）で、購入者への感謝と配慮を随所に入れる。"
        "listing_description は800〜1200文字程度。冒頭の挨拶・結びの礼を丁寧に書く。"
    ),
}


class GeminiFleaMarketService:
    @staticmethod
    def _default_model_name() -> str:
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        return resolve_gemini_flash_model()

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name or self._default_model_name()
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

    def generate_listing(
        self,
        record: Dict[str, Any],
        *,
        style: str = "standard",
        one_time_text: str = "",
    ) -> Optional[Dict[str, Any]]:
        """仕入レコードからフリマ出品文案を生成。JAN・コンディション説明は後処理で出品説明に付与。"""
        if not self.is_available():
            return None

        jan = extract_jan_from_record(record)
        condition_note = extract_condition_note_from_record(record)
        condition_label = extract_condition_label_from_record(record)

        product_name = _first_str(
            record,
            "商品名",
            "product_name",
            "title",
            "name",
        )
        purchase_price = _first_number(record, "仕入れ価格", "purchase_price", "仕入価格")
        sale_price = _first_number(record, "販売予定価格", "expected_price", "sale_price")
        comment = _first_str(record, "コメント", "comment")

        ai_settings = load_flea_market_ai_settings()
        extra_prompt = (ai_settings.get("additional_prompt") or "").strip()
        style_key = style if style in FLEA_STYLE_INSTRUCTIONS else "standard"
        system_prompt = FLEA_MARKET_PROMPT + "\n\n" + FLEA_STYLE_INSTRUCTIONS[style_key]
        if extra_prompt:
            system_prompt = system_prompt + "\n\n【追加指示（必ず守ること）】\n" + extra_prompt

        one_time = (one_time_text or "").strip()
        user_text = (
            f"商品名: {product_name or '（不明）'}\n"
            f"コンディション: {condition_label or '（不明）'}\n"
            f"コンディション説明（出品に反映必須）:\n{condition_note or '（なし）'}\n"
            f"仕入れ価格: {int(purchase_price) if purchase_price else '（不明）'} 円\n"
            f"販売予定価格（参考）: {int(sale_price) if sale_price else '（不明）'} 円\n"
            f"コメント（参考）: {comment or '（なし）'}\n"
            f"JANコード（商品説明欄に別途記載するため文案本文には含めない）: {jan or '（なし）'}\n"
        )
        if one_time:
            user_text += f"\n【今回だけ必ず含める文言（出品説明に反映すること）】\n{one_time}\n"

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

        prompt = f"{system_prompt}\n\n{user_text}"
        generation_config = {
            "temperature": 0.4,
            "max_output_tokens": 2048,
            "response_mime_type": "application/json",
        }

        def _invoke(model_name: str) -> Optional[str]:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(prompt)
            return extract_gemini_response_text(response) or None

        text, error, used_model = run_with_flash_model_fallback(
            self.api_key or "",
            _invoke,
            configured_model=self.model_name,
        )
        if not text:
            self.last_error = error
            logger.warning("Gemini flea market generation failed: %s", error)
            return None
        self.model_name = used_model or self.model_name
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini flea market JSON parse error: %s", exc)
            self.last_error = f"AI応答のJSON解析に失敗しました: {exc}"
            return None

        title = _safe_str(data.get("title")) or (product_name[:40] if product_name else "")
        if len(title) > 40:
            title = title[:40]

        body_raw = _safe_str(data.get("listing_description")) or ""
        if not body_raw:
            short_raw = _safe_str(data.get("short_description")) or ""
            detailed_raw = _safe_str(data.get("detailed_description")) or ""
            body_raw = _merge_description_parts(short_raw, detailed_raw)

        listing_description = build_product_description_block(body_raw, jan, condition_note)

        mandatory = (ai_settings.get("mandatory_text") or "").strip()
        listing_description = apply_mandatory_footer(listing_description, mandatory)
        listing_description = apply_mandatory_footer(listing_description, one_time)

        suggested = _to_int(data.get("suggested_price"))
        if suggested is None and sale_price > 0:
            suggested = int(round(sale_price))

        return {
            "title": title,
            "listing_description": listing_description,
            "suggested_price": suggested,
            "jan": jan,
            "condition_note": condition_note,
        }


def _merge_description_parts(short_part: str, detailed_part: str) -> str:
    """旧スキーマ（短い説明+詳細）の互換用に1本へ結合。"""
    parts = [p.strip() for p in (short_part, detailed_part) if p and p.strip()]
    return "\n\n".join(parts)


def _response_text(response: Any) -> Optional[str]:
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None)
    if candidates:
        parts = candidates[0].content.parts
        if parts:
            return parts[0].text
    return None


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _first_str(record: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = record.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _first_number(record: Dict[str, Any], *keys: str) -> float:
    for k in keys:
        v = record.get(k)
        if v is None or str(v).strip() == "":
            continue
        try:
            return float(str(v).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
    return 0.0
