#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geminiベースのレシート解析サービス

GeminiのマルチモーダルAPIを利用して、レシート画像から構造化データを抽出する。
APIキーやモデル名はQSettings（ocr/gemini_*）から自動取得し、未設定の場合は無効化される。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:  # pragma: no cover - ランタイム依存
    genai = None
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """
You are an assistant that extracts structured data from Japanese retail receipts.
Look at the image and return ONLY a JSON object (no prose) that matches the schema below.

Output schema (all keys required, use null if unknown):
{
  "purchase_date": "YYYY/MM/DD or null",
  "purchase_time": "HH:MM or null",
  "store_name": "string or null",
  "phone_number": "string or null",
  "subtotal": integer or null,
  "tax": integer or null,
  "discount_amount": integer or null,
  "total_amount": integer or null,
  "paid_amount": integer or null,
  "items_count": integer or null,
  "raw_text": "entire OCR text as a single string (UTF-8). Null is allowed."
}

Rules:
- Dates must be normalized to YYYY/MM/DD.
- Times must be HH:MM in 24-hour time.
- All numeric fields are integer yen amounts (no currency symbols).
- Use null (not empty string) when a field cannot be found.
- Return valid JSON only. Do not add comments or explanations.
"""


class GeminiReceiptService:
    """Gemini APIを用いたレシート構造化サービス"""

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
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name or self._default_model_name()
        self.prompt = prompt
        self.last_error = ""
        self._configure()

    def _configure(self) -> None:
        """QSettingsと環境から設定を読み込む"""
        self.last_error = ""
        if not GEMINI_AVAILABLE:
            logger.debug("google-generativeai is not installed; GeminiReceiptService disabled")
            return

        if not self.api_key:
            try:
                from PySide6.QtCore import QSettings  # type: ignore

                settings = QSettings("HIRIO", "DesktopApp")
                self.api_key = (settings.value("ocr/gemini_api_key", "") or "").strip() or None
            except Exception as exc:
                logger.debug("Failed to load Gemini settings from QSettings: %s", exc)

        if not self.api_key:
            logger.info("Gemini API key is not configured; AI receipt parsing disabled")
            return

        logger.info("Gemini receipt parsing enabled (model=%s)", self.model_name)

    def is_available(self) -> bool:
        return bool(GEMINI_AVAILABLE and self.api_key)

    def extract_structured_data(self, image_path: str | Path) -> Optional[Dict[str, Any]]:
        """レシート画像から構造化データを抽出"""
        if not self.is_available():
            return None

        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        mime_type = self._guess_mime_type(path)
        image_bytes = path.read_bytes()

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

        generation_config = {
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "response_mime_type": "application/json",
        }
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": self.prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_bytes,
                        }
                    },
                ],
            }
        ]

        def _invoke(model_name: str) -> Optional[str]:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(contents)
            return extract_gemini_response_text(response) or None

        try:
            text, error, used_model = run_with_flash_model_fallback(
                self.api_key or "",
                _invoke,
                configured_model=self.model_name,
            )
            if not text:
                self.last_error = error
                logger.warning("Gemini receipt extraction failed: %s", error)
                return None
            self.model_name = used_model or self.model_name
            payload = json.loads(text)
            return self._normalize_payload(payload)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini response was not valid JSON: %s", exc)
        except Exception as exc:  # pragma: no cover - 外部API依存
            logger.warning("Gemini receipt extraction failed: %s", exc)
        return None

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in (".png",):
            return "image/png"
        if suffix in (".webp",):
            return "image/webp"
        if suffix in (".bmp",):
            return "image/bmp"
        return "image/jpeg"

    def _normalize_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """GeminiのJSON結果をアプリ向けに正規化"""
        return {
            "provider": "gemini",
            "raw_text": self._safe_str(data.get("raw_text")),
            "purchase_date": self._normalize_date(data.get("purchase_date")),
            "purchase_time": self._normalize_time(data.get("purchase_time")),
            "store_name_raw": self._safe_str(data.get("store_name") or data.get("store_name_raw")),
            "phone_number": self._normalize_phone(data.get("phone_number")),
            "subtotal": self._to_int(data.get("subtotal")),
            "tax": self._to_int(data.get("tax")),
            "discount_amount": self._to_int(data.get("discount_amount")),
            "total_amount": self._to_int(data.get("total_amount")),
            "paid_amount": self._to_int(data.get("paid_amount")),
            "items_count": self._to_int(data.get("items_count")),
        }

    @staticmethod
    def _safe_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value in (None, "", "null"):
            return None
        try:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return int(value)
            text = str(value).strip().replace(",", "")
            if not text:
                return None
            return int(float(text))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalize_date(value: Any) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip()
        text = text.replace("年", "/").replace("月", "/").replace("日", "")
        text = text.replace("-", "/").replace(".", "/")
        match = re.search(r"(20\d{2})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            y, m, d = match.groups()
            return f"{int(y):04d}/{int(m):02d}/{int(d):02d}"
        return None

    @staticmethod
    def _normalize_time(value: Any) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip()
        match = re.search(r"(\d{1,2})[:：時hH](\d{2})", text)
        if match:
            h, m = match.groups()
            return f"{int(h):02d}:{int(m):02d}"
        match = re.search(r"(\d{1,2})(\d{2})", text)
        if match:
            h, m = match.groups()
            hour = int(h)
            minute = int(m)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        return None

    @staticmethod
    def _normalize_phone(value: Any) -> Optional[str]:
        if not value:
            return None
        text = re.sub(r"[^\d-]", "", str(value))
        digits = re.sub(r"-", "", text)
        if len(digits) in (10, 11) and "-" not in text:
            if len(digits) == 10:
                return f"{digits[0:2]}-{digits[2:6]}-{digits[6:]}"
            return f"{digits[0:3]}-{digits[3:7]}-{digits[7:]}"
        return text or None



