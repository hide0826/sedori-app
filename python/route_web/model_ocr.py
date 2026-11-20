# -*- coding: utf-8 -*-
"""商品の箱・本体ラベルから型番を OCR する（Gemini）。

store-cam の値札 OCR とは別プロンプト。価格は読まない。
API キーは watcher/.env → store-cam/.env の順（store-cam と同じ）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_HIRIO_ROOT = Path(__file__).resolve().parents[4]
_WATCHER_ENV = _HIRIO_ROOT / "watcher" / ".env"
_STORE_CAM_ENV = _HIRIO_ROOT / "store-cam" / ".env"

_ENV_LOADED = False

MODEL_LABEL_PROMPT = """あなたは家電・ホビー商品の箱や本体に書かれた「型番（モデル番号）」を読む係です。
値札の価格ではなく、型番ラベル・スペック表・バーコード付近の型番文字を優先します。

やること:
1. 写真に写っている文字を起こす（OCR）。
2. 商品を特定しやすい型番を1つ抽出する。複数あればいちばん具体的なもの。
3. JAN（8桁または13桁）が見えれば拾う。作らない。

出力は JSON だけ。前置き禁止。
{
  "ocr_text": "読めた文字を改行区切り",
  "model": "型番。無ければ空文字",
  "brand": "メーカー・ブランド。無ければ空文字",
  "jan": "8または13桁JAN。無ければ空文字。作らない",
  "confidence": 0から100の整数。型番読取の確度,
  "evidence": "根拠を短く（どこに書いてあったか）"
}

注意:
- 価格や税込は不要。
- 型番はハイフン付きのまま返す（例: WH-1000XM4、WF-C700N）。
- メーカー名だけを型番にしない。
"""

_WEAK_MODELS = {"na", "hg", "mg", "rg", "pg", "yoda", "be1", "bandai"}


@dataclass
class ModelOcrResult:
    ok: bool
    model_raw: str = ""
    model_norm: str = ""
    brand_guess: str = ""
    jan: str = ""
    confidence: int = 0
    evidence: str = ""
    ocr_text: str = ""
    error: str = ""
    elapsed_ms: Optional[int] = None


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_file(_WATCHER_ENV)
        _load_env_file(_STORE_CAM_ENV)
        return
    load_dotenv(_WATCHER_ENV, override=False)
    load_dotenv(_STORE_CAM_ENV, override=True)


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
    except OSError:
        return


def _gemini_settings() -> tuple[str, str]:
    _load_env_once()
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model = (os.getenv("GEMINI_MODEL") or "gemini-flash-latest").strip() or "gemini-flash-latest"
    return key, model


def normalize_for_match(text: str) -> str:
    """型番照合用に空白・ハイフン等を落として小文字化する。"""
    folded = (text or "").casefold()
    return re.sub(r"[\s\-_／/]+", "", folded)


def is_strong_model(token: str) -> bool:
    """短すぎる型番は誤ヒットしやすいので除外する（watcher と同方針）。"""
    text = (token or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[ー\-‐―\\']+", text):
        return False
    norm = normalize_for_match(text)
    if len(norm) < 4:
        return False
    if re.fullmatch(r"\d{1,4}", norm):
        return False
    if norm in _WEAK_MODELS:
        return False
    has_alpha = any(ch.isalpha() for ch in norm)
    has_digit = any(ch.isdigit() for ch in norm)
    if len(norm) < 5 and not (has_alpha and has_digit):
        return False
    return True


def title_has_model(title: str, model: str) -> bool:
    """商品タイトルに型番が含まれるか（ハイフン・空白のゆれを許容）。"""
    if not title or not model:
        return False
    if not is_strong_model(model):
        return False
    norm_title = normalize_for_match(title)
    norm_model = normalize_for_match(model)
    return bool(norm_model) and norm_model in norm_title


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace:
            cleaned = brace.group(0)
    return json.loads(cleaned)


def _to_jan(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) in (8, 13):
        return digits
    return ""


def _redact(text: str) -> str:
    return re.sub(r"([?&]key=)[^&\s]+", r"\1***", text or "", flags=re.IGNORECASE)


def _post_gemini(body: dict[str, Any], *, api_key: str, model: str, timeout: int = 60) -> tuple[int, dict[str, Any]]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    last_status = 0
    last_payload: dict[str, Any] = {}
    for attempt in range(1, 4):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            wait = min(2**attempt, 8)
            logger.warning(
                "Gemini 接続失敗 attempt=%s wait=%ss: %s",
                attempt,
                wait,
                _redact(str(exc))[:200],
            )
            if attempt >= 3:
                raise
            time.sleep(wait)
            continue
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": (response.text or "")[:400]}
        last_status = response.status_code
        last_payload = payload if isinstance(payload, dict) else {"raw": payload}
        if response.status_code in (429, 503) and attempt < 3:
            time.sleep(min(2**attempt, 8))
            continue
        return last_status, last_payload
    return last_status, last_payload


def extract_model_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> ModelOcrResult:
    """箱・本体ラベル写真から型番を Gemini で読む。"""
    started = time.monotonic()
    api_key, model_name = _gemini_settings()
    if not api_key:
        return ModelOcrResult(
            ok=False,
            error="GEMINI_API_KEY がありません。watcher または store-cam の .env を確認してください。",
        )
    if not image_bytes:
        return ModelOcrResult(ok=False, error="画像が空です。")

    mime = mime_type if (mime_type or "").startswith("image/") else "image/jpeg"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": MODEL_LABEL_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    try:
        status_code, payload = _post_gemini(body, api_key=api_key, model=model_name)
    except requests.RequestException as exc:
        logger.exception("Gemini 通信エラー（型番）")
        return ModelOcrResult(
            ok=False,
            error=f"Gemini に接続できません: {_redact(str(exc))}",
            elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
        )

    elapsed = max(1, int((time.monotonic() - started) * 1000))
    if status_code != 200:
        logger.error("Gemini API エラー（型番）: %s %s", status_code, str(payload)[:400])
        return ModelOcrResult(
            ok=False,
            error=f"Gemini API エラー ({status_code})",
            elapsed_ms=elapsed,
        )

    try:
        text = ""
        candidates = payload.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(str(part.get("text") or "") for part in parts)
        data = _parse_json_object(text)
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        logger.warning("型番 JSON パース失敗: %s", exc)
        return ModelOcrResult(
            ok=False,
            error="型番の読み取り結果を解釈できませんでした。",
            elapsed_ms=elapsed,
        )

    model_raw = str(data.get("model") or "").strip()
    jan = _to_jan(data.get("jan"))
    if not model_raw and not jan:
        return ModelOcrResult(
            ok=False,
            ocr_text=str(data.get("ocr_text") or "").strip(),
            error="型番を読み取れませんでした。",
            elapsed_ms=elapsed,
        )

    try:
        confidence = max(0, min(100, int(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0

    return ModelOcrResult(
        ok=True,
        model_raw=model_raw,
        model_norm=normalize_for_match(model_raw),
        brand_guess=str(data.get("brand") or "").strip(),
        jan=jan,
        confidence=confidence,
        evidence=str(data.get("evidence") or "").strip(),
        ocr_text=str(data.get("ocr_text") or "").strip(),
        elapsed_ms=elapsed,
    )
