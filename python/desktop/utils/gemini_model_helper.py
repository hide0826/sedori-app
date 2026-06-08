#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini モデル名の統一。

方針:
- 第一候補は Google のエイリアス ``gemini-flash-latest``（常に最新 Flash へ追従）
- 次に flash-lite 系（コスト重視のフォールバック）
- 404 時は API の list_models() で利用可能モデルを追加探索
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Google がメンテする「最新 Flash」エイリアス（モデル廃止時も Google 側で差し替え）
LATEST_GEMINI_FLASH_ALIAS = "gemini-flash-latest"

# 明示的な flash-lite（エイリアスが使えない環境・コスト優先のフォールバック）
CHEAPEST_GEMINI_FLASH_MODEL = "gemini-2.5-flash-lite"

# 固定フォールバック（list_models 失敗時用）
GEMINI_FLASH_MODEL_FALLBACKS: List[str] = [
    LATEST_GEMINI_FLASH_ALIAS,
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def resolve_gemini_flash_model(configured: Optional[str] = None) -> str:
    """UI 表示用の代表モデル名（常に最新 Flash エイリアス）。"""
    _ = configured
    return LATEST_GEMINI_FLASH_ALIAS


def _normalize_model_name(model_name_full: str) -> str:
    normalized = (model_name_full or "").strip()
    if normalized.startswith("models/"):
        normalized = normalized.split("/", 1)[1]
    return normalized


def discover_generate_content_models(api_key: str) -> List[str]:
    """
    API キーで利用可能な generateContent 対応モデルを取得する。
    Keepa AI タブにあった探索ロジックを共通化。
    """
    key = (api_key or "").strip()
    if not key:
        return []
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        discovered: List[str] = []
        for model_info in genai.list_models():
            methods = getattr(model_info, "supported_generation_methods", None) or []
            if "generateContent" not in methods:
                continue
            normalized = _normalize_model_name(str(getattr(model_info, "name", "") or ""))
            if normalized and normalized not in discovered:
                discovered.append(normalized)
        return discovered
    except Exception as exc:
        logger.debug("Gemini list_models failed: %s", exc)
        return []


def _sort_discovered_flash_models(models: List[str]) -> List[str]:
    """flash 系を lite → 数値版の新しめ順に並べる。"""

    def _rank(name: str) -> Tuple[int, str]:
        lower = name.lower()
        if "flash" not in lower:
            return (9, name)
        if "lite" in lower:
            return (0, name)
        if "latest" in lower:
            return (1, name)
        return (2, name)

    return sorted(models, key=_rank)


def gemini_flash_model_candidates(
    configured: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
) -> List[str]:
    """
    API 呼び出しで順に試す Flash モデル候補（重複なし）。

    優先順:
    1. 固定候補（flash-latest → lite → その他）
    2. list_models で見つかった flash 系
    3. list_models で見つかったその他（最後の手段）
    """
    _ = configured
    ordered: List[str] = []
    for name in [resolve_gemini_flash_model(), *GEMINI_FLASH_MODEL_FALLBACKS]:
        n = (name or "").strip()
        if n and n not in ordered:
            ordered.append(n)

    discovered = discover_generate_content_models(api_key or "")
    flash_discovered = _sort_discovered_flash_models(
        [m for m in discovered if "flash" in m.lower()]
    )
    other_discovered = [m for m in discovered if m not in flash_discovered]
    for m in flash_discovered + other_discovered:
        if m not in ordered:
            ordered.append(m)
    return ordered


def extract_gemini_response_text(response: Any) -> str:
    """Gemini 応答からテキストを取り出す（candidates 経由のフォールバック付き）。"""
    try:
        text = (getattr(response, "text", None) or "").strip()
        if text:
            return text
    except Exception:
        pass

    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(candidates[0].content, "parts", None) or []
            chunks: List[str] = []
            for part in parts:
                chunk = getattr(part, "text", None)
                if chunk:
                    chunks.append(str(chunk).strip())
            if chunks:
                return "\n".join(chunks).strip()
    except Exception:
        pass
    return ""


def explain_gemini_error(exc: Exception, model_name: str = "") -> str:
    try:
        from utils.api_test_helper import explain_api_error
    except ImportError:
        from desktop.utils.api_test_helper import explain_api_error
    return explain_api_error("gemini", exc, model=model_name)


def run_with_flash_model_fallback(
    api_key: str,
    invoke: Callable[[str], Optional[str]],
    *,
    configured_model: Optional[str] = None,
) -> Tuple[Optional[str], str, str]:
    """
    Flash モデル候補を順に試し、最初に成功した結果を返す。

    Returns:
        (テキスト, エラーメッセージ, 使用したモデル名)
    """
    key = (api_key or "").strip()
    if not key:
        return None, "Gemini APIキーが未設定です。設定タブで API キーを登録してください。", ""

    try:
        import google.generativeai as genai
    except ImportError:
        return (
            None,
            "google-generativeai がインストールされていません。\n"
            "`pip install google-generativeai` を実行してください。",
            "",
        )

    last_exc: Optional[Exception] = None
    last_model = ""
    try:
        genai.configure(api_key=key)
        candidates = gemini_flash_model_candidates(configured_model, api_key=key)
        for model_name in candidates:
            last_model = model_name
            try:
                text = invoke(model_name)
                if text and str(text).strip():
                    return str(text).strip(), "", model_name
                last_exc = RuntimeError("Gemini から空の応答が返されました。")
            except Exception as exc:
                last_exc = exc
                logger.debug("Gemini model %s failed: %s", model_name, exc)
                continue
    except Exception as exc:
        last_exc = exc

    if last_exc is not None:
        return None, explain_gemini_error(last_exc, last_model), last_model
    return None, "Gemini API の呼び出しに失敗しました。", last_model
