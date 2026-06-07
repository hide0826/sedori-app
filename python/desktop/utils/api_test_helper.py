#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部API接続テストと、エラー時の日本語解説ヘルパー"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ApiTestResult:
    success: bool
    summary: str
    details: str = ""


def _norm_error_text(error: Any) -> str:
    if error is None:
        return ""
    if isinstance(error, Exception):
        parts = [str(error).strip()]
        for attr in ("message", "reason", "status"):
            val = getattr(error, attr, None)
            if val and str(val).strip() not in parts:
                parts.append(str(val).strip())
        return " ".join(p for p in parts if p)
    return str(error).strip()


def explain_api_error(
    api_name: str,
    error: Any,
    *,
    model: Optional[str] = None,
    url: Optional[str] = None,
    http_status: Optional[int] = None,
    response_body: Optional[str] = None,
) -> str:
    """APIエラーを初心者向けに解説"""
    text = _norm_error_text(error).lower()
    body = (response_body or "").lower()
    combined = f"{text} {body}"

    lines = [f"【エラー内容】\n{_norm_error_text(error)}"]
    if http_status:
        lines.append(f"HTTPステータス: {http_status}")
    if response_body and response_body.strip():
        snippet = response_body.strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        lines.append(f"【サーバー応答】\n{snippet}")

    hints: list[str] = []

    if api_name == "fastapi":
        if "connection refused" in combined or "10061" in combined or "actively refused" in combined:
            hints.append(
                "FastAPIサーバーが起動していない可能性があります。\n"
                "ターミナルでバックエンド（uvicorn 等）を起動してから再テストしてください。"
            )
        if "timed out" in combined or "timeout" in combined:
            hints.append(
                "指定URLへの接続がタイムアウトしました。\n"
                "APIベースURL・ファイアウォール・VPN を確認してください。"
            )
        if "name or service not known" in combined or "getaddrinfo failed" in combined:
            hints.append("URLのホスト名が解決できません。スペルミスや http/https の誤りを確認してください。")
        if url:
            hints.append(f"接続先: {url}\n/health エンドポイントが 200 を返す必要があります。")
        if not hints:
            hints.append(
                "FastAPI が http://localhost:8000/health で応答しているか確認してください。\n"
                "localhost で失敗する場合は 127.0.0.1 も自動で試します。"
            )

    elif api_name == "gemini":
        if "google.generativeai" in combined or "no module named" in combined:
            hints.append("Gemini用パッケージが未インストールです。\n`pip install google-generativeai` を実行してください。")
        if not _norm_error_text(error) and not hints:
            hints.append("Gemini APIキーが未入力です。API設定 → 外部APIキー にキーを入力してください。")
        if "api key not valid" in combined or "invalid api key" in combined or "api_key_invalid" in combined:
            hints.append(
                "APIキーが無効です。\n"
                "Google AI Studio（https://aistudio.google.com/apikey）でキーを再発行し、"
                "コピー漏れ・前後の空白がないか確認してください。"
            )
        if "permission_denied" in combined or "403" in combined:
            hints.append(
                "キーの権限または API 有効化に問題があります。\n"
                "Google Cloud Console で「Generative Language API」が有効か、"
                "キーの「API の制限」に Generative Language API が含まれているか確認してください。"
            )
        if "not found" in combined and (model or "model" in combined):
            hints.append(
                f"モデル名「{model or '（指定モデル）'}」が見つかりません。\n"
                "HIRIO は `gemini-2.0-flash-lite`（最安 Flash）を自動使用します。"
                "アプリを再起動してから再テストしてください。"
            )
        if "429" in combined or "resource_exhausted" in combined or "quota" in combined:
            hints.append(
                "利用上限（クォータ）に達した可能性があります。\n"
                "しばらく待ってから再試行するか、Google Cloud の課金・クォータ設定を確認してください。"
            )
        if "billing" in combined:
            hints.append("課金が有効化されていないプロジェクトのキーの可能性があります。Cloud Console の課金設定を確認してください。")

    elif api_name == "maps":
        if "requests" in combined and "no module named" in combined:
            hints.append("`pip install requests` を実行してください。")
        if "request_denied" in combined or "api key not valid" in combined or "invalid" in combined and "key" in combined:
            hints.append(
                "Maps APIキーが拒否されました。\n"
                "・Gemini 用キーではなく Maps 専用キーか確認\n"
                "・Cloud Console で Maps Embed API / Places API (New) を有効化\n"
                "・キー制限に上記 API が含まれているか確認"
            )
        if "permission_denied" in combined or "403" in combined:
            hints.append(
                "Places API (New) が有効化されていない、またはキー制限でブロックされている可能性があります。"
            )
        if "billing" in combined:
            hints.append("Google Maps Platform では課金アカウントの有効化が必要な場合があります。")

    elif api_name == "keepa":
        if "invalid" in combined and "key" in combined:
            hints.append(
                "Keepa APIキーが無効です。\n"
                "Keepa サイト（https://keepa.com/#!api）で正しい Access Key を確認してください。"
            )
        if "403" in combined or "401" in combined:
            hints.append("Keepa APIキーの権限がありません。サブスクリプション状態を Keepa で確認してください。")

    elif api_name == "ocr_tesseract":
        if "no module named 'pytesseract'" in combined or "pytesseract" in combined:
            hints.append("`pip install pytesseract` を実行し、Tesseract OCR 本体もインストールしてください。")
        if "not found" in combined or "no such file" in combined:
            hints.append("Tesseract 実行ファイルのパスが間違っています。参照ボタンで正しい tesseract.exe を選んでください。")

    elif api_name == "ocr_gcv":
        if "no module named" in combined and "google" in combined:
            hints.append("`pip install google-cloud-vision` を実行してください。")
        if "not found" in combined:
            hints.append("GCV 認証情報 JSON ファイルのパスが存在しません。参照ボタンで正しいファイルを選んでください。")

    if not hints:
        hints.append("上記のエラー内容を確認し、キー・URL・ネットワーク接続を見直してください。")

    lines.append("【対処方法】\n" + "\n\n".join(hints))
    return "\n\n".join(lines)


def test_fastapi_connection(base_url: str, *, test_fn) -> ApiTestResult:
    """FastAPI 接続テスト（test_fn は bool を返す callable）"""
    url = (base_url or "").strip() or "http://localhost:8000"
    try:
        if test_fn():
            return ApiTestResult(
                True,
                "FastAPIサーバーに正常に接続できました",
                f"接続先: {url.rstrip('/')}/health",
            )
        return ApiTestResult(
            False,
            "FastAPIサーバーに接続できませんでした",
            explain_api_error("fastapi", "接続失敗", url=url),
        )
    except Exception as exc:
        return ApiTestResult(
            False,
            "FastAPI接続テスト中にエラーが発生しました",
            explain_api_error("fastapi", exc, url=url),
        )


def test_gemini_api(api_key: str, model_name: Optional[str] = None) -> ApiTestResult:
    """Gemini APIキーの接続テスト（最安 Flash モデルを順に試行）"""
    try:
        from utils.gemini_model_helper import (
            gemini_flash_model_candidates,
            resolve_gemini_flash_model,
        )
    except ImportError:
        from desktop.utils.gemini_model_helper import (
            gemini_flash_model_candidates,
            resolve_gemini_flash_model,
        )

    key = (api_key or "").strip()
    if not key:
        return ApiTestResult(
            False,
            "Gemini APIキーが未入力です",
            explain_api_error("gemini", "APIキー未設定", model=resolve_gemini_flash_model()),
        )
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as exc:
        return ApiTestResult(
            False,
            "google-generativeai がインストールされていません",
            explain_api_error("gemini", exc, model=resolve_gemini_flash_model()),
        )

    candidates = gemini_flash_model_candidates(model_name)
    last_error: Optional[Exception] = None
    for model in candidates:
        try:
            genai.configure(api_key=key)
            generation_config = {"temperature": 0.0, "max_output_tokens": 16}
            model_client = genai.GenerativeModel(model, generation_config=generation_config)
            response = model_client.generate_content("Reply with exactly the word: OK")
            reply = (getattr(response, "text", None) or "").strip()
            return ApiTestResult(
                True,
                f"Gemini API接続成功（モデル: {model}）",
                f"HIRIO は最安 Flash モデル `{resolve_gemini_flash_model()}` を使用します。\n"
                f"テスト応答: {reply or '（空応答）'}",
            )
        except Exception as exc:
            last_error = exc
            continue

    return ApiTestResult(
        False,
        "Gemini API接続に失敗しました",
        explain_api_error("gemini", last_error or "不明", model=candidates[0] if candidates else None),
    )


def test_maps_api(api_key: str) -> ApiTestResult:
    """Google Maps（Places API New）キーの接続テスト"""
    key = (api_key or "").strip()
    if not key:
        return ApiTestResult(
            False,
            "Google Maps APIキーが未入力です",
            explain_api_error("maps", "APIキー未設定"),
        )
    try:
        import requests  # type: ignore
    except ImportError as exc:
        return ApiTestResult(
            False,
            "requests がインストールされていません",
            explain_api_error("maps", exc),
        )
    try:
        resp = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.id",
            },
            json={"textQuery": "東京駅", "languageCode": "ja", "maxResultCount": 1},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            count = len(data.get("places") or [])
            return ApiTestResult(
                True,
                "Google Maps API（Places API New）接続成功",
                f"テスト検索「東京駅」: {count} 件取得\nMaps Embed API も同じキーで利用できます。",
            )
        body = resp.text
        try:
            err_json = resp.json()
            err_msg = err_json.get("error", {}).get("message") or body
        except Exception:
            err_msg = body
        return ApiTestResult(
            False,
            f"Google Maps API接続に失敗しました（HTTP {resp.status_code}）",
            explain_api_error("maps", err_msg, http_status=resp.status_code, response_body=body),
        )
    except Exception as exc:
        return ApiTestResult(
            False,
            "Google Maps API接続テスト中にエラーが発生しました",
            explain_api_error("maps", exc),
        )


def test_keepa_api(api_key: str) -> ApiTestResult:
    """Keepa APIキーの接続テスト（トークン残量確認・消費なし）"""
    key = (api_key or "").strip()
    if not key:
        return ApiTestResult(
            False,
            "Keepa APIキーが未入力です",
            explain_api_error("keepa", "APIキー未設定"),
        )
    try:
        import requests  # type: ignore
    except ImportError as exc:
        return ApiTestResult(
            False,
            "requests がインストールされていません",
            explain_api_error("keepa", exc),
        )
    try:
        resp = requests.get(
            "https://api.keepa.com/token",
            params={"key": key},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            tokens_left = data.get("tokensLeft")
            refill_in = data.get("refillIn")
            detail_lines = ["Keepa APIキーは有効です。"]
            if tokens_left is not None:
                detail_lines.append(f"残りトークン: {tokens_left}")
            if refill_in is not None:
                detail_lines.append(f"次回リフィルまで: 約 {refill_in} 秒")
            return ApiTestResult(True, "Keepa API接続成功", "\n".join(detail_lines))
        body = resp.text
        try:
            err_msg = resp.json().get("error", body)
        except Exception:
            err_msg = body
        return ApiTestResult(
            False,
            f"Keepa API接続に失敗しました（HTTP {resp.status_code}）",
            explain_api_error("keepa", str(err_msg), http_status=resp.status_code, response_body=body),
        )
    except Exception as exc:
        return ApiTestResult(
            False,
            "Keepa API接続テスト中にエラーが発生しました",
            explain_api_error("keepa", exc),
        )
