#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
価格改定ジョブの Discord Webhook 通知。

設定（QSettings reprice/discord_webhook_url）が空なら何もしない。
通知失敗は例外を外へ出さず、呼び出し側ログ用に False を返す。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

_MODE_LABELS = {
    "follow": "追従",
    "weekly369": "週次3-6-9",
    "weekly": "週次3-6-9",
}

# Discord embed colors
_COLOR_OK = 0x2ECC71
_COLOR_PARTIAL = 0xE67E22
_COLOR_ERROR = 0xE74C3C


def _ensure_shared_on_path() -> None:
    # .../python/desktop/services -> parents[4] = C:\HIRIO
    hirio_shared = Path(__file__).resolve().parents[4] / "shared"
    text = str(hirio_shared)
    if hirio_shared.is_dir() and text not in sys.path:
        sys.path.insert(0, text)


def mode_label(mode: str) -> str:
    key = str(mode or "").strip()
    return _MODE_LABELS.get(key, key or "価格改定")


def build_reprice_discord_payload(
    mode: str,
    *,
    success_count: int = 0,
    failed_count: int = 0,
    targets: int = 0,
    extra: Optional[Mapping[str, Any]] = None,
    error: Optional[str] = None,
    failed_skus: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Discord webhook 用 JSON（content + embeds）を組み立てる。"""
    label = mode_label(mode)
    extra = dict(extra or {})
    err_text = str(error or extra.get("error") or "").strip()
    failed = int(failed_count or 0)
    success = int(success_count or 0)
    total = int(targets or 0)

    if err_text and success == 0 and failed == 0:
        title = f"価格改定でエラー発生（{label}）"
        color = _COLOR_ERROR
        status_line = "ジョブが途中で失敗しました。"
    elif failed > 0 and success > 0:
        title = f"価格改定でエラー（一部失敗・{label}）"
        color = _COLOR_PARTIAL
        status_line = "一部のSKUで反映に失敗しました。"
    elif failed > 0:
        title = f"価格改定でエラー発生（{label}）"
        color = _COLOR_ERROR
        status_line = "価格反映に失敗しました。"
    else:
        title = f"全件価格改定完了（{label}）"
        color = _COLOR_OK
        status_line = "対象SKUの価格反映が完了しました。"

    lines: List[str] = [status_line, ""]
    lines.append(f"対象: {total} 件")
    lines.append(f"成功: {success} 件")
    lines.append(f"失敗: {failed} 件")
    transport = str(extra.get("transport") or "").strip()
    if transport:
        lines.append(f"方式: {transport}")
    feed_id = str(extra.get("feedId") or "").strip()
    if feed_id:
        lines.append(f"feedId: {feed_id}")
    failed_csv = str(extra.get("failed_csv") or "").strip()
    if failed_csv:
        lines.append(f"失敗CSV: {failed_csv}")
    if err_text:
        lines.append("")
        lines.append(f"エラー: {err_text[:500]}")
    sku_list = [str(s).strip() for s in (failed_skus or []) if str(s).strip()]
    if sku_list:
        shown = sku_list[:8]
        more = len(sku_list) - len(shown)
        sku_line = ", ".join(shown)
        if more > 0:
            sku_line += f" ほか{more}件"
        lines.append("")
        lines.append(f"失敗SKU: {sku_line}")

    at = str(extra.get("at") or datetime.now().isoformat(timespec="seconds"))
    lines.append("")
    lines.append(f"時刻: {at}")

    return {
        "username": "HIRIO 価格改定",
        "embeds": [
            {
                "title": title,
                "description": "\n".join(lines),
                "color": color,
            }
        ],
    }


def notify_reprice_result(
    mode: str,
    *,
    dry_run: bool = False,
    success_count: int = 0,
    failed_count: int = 0,
    targets: int = 0,
    extra: Optional[Mapping[str, Any]] = None,
    error: Optional[str] = None,
    failed_skus: Optional[Sequence[str]] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """
    価格改定結果を Discord に送る。

    Returns:
        True=送信成功、False=スキップまたは失敗
    """
    if dry_run:
        return False
    try:
        if webhook_url is None:
            try:
                from utils.settings_helper import get_reprice_discord_webhook_url
            except ImportError:
                from desktop.utils.settings_helper import (  # type: ignore
                    get_reprice_discord_webhook_url,
                )
            url = get_reprice_discord_webhook_url()
        else:
            url = str(webhook_url or "").strip()
        if not url:
            return False

        payload = build_reprice_discord_payload(
            mode,
            success_count=success_count,
            failed_count=failed_count,
            targets=targets,
            extra=extra,
            error=error,
            failed_skus=failed_skus,
        )
        _ensure_shared_on_path()
        from hit_actions import post_discord_webhook

        response = post_discord_webhook(url, payload, timeout=15)
        status = int(getattr(response, "status_code", 0) or 0)
        return 200 <= status < 300
    except Exception:  # noqa: BLE001
        return False


def send_reprice_discord_test(webhook_url: Optional[str] = None) -> str:
    """
    設定画面のテスト送信。成功時は空文字、失敗時は理由文字列。
    """
    try:
        if webhook_url is None:
            try:
                from utils.settings_helper import get_reprice_discord_webhook_url
            except ImportError:
                from desktop.utils.settings_helper import (  # type: ignore
                    get_reprice_discord_webhook_url,
                )
            url = get_reprice_discord_webhook_url()
        else:
            url = str(webhook_url or "").strip()
        if not url:
            return "Webhook URL が空です。設定を保存してから再試行してください。"
        payload = {
            "username": "HIRIO 価格改定",
            "embeds": [
                {
                    "title": "価格改定 Discord 通知テスト",
                    "description": (
                        "テスト送信に成功しました。\n"
                        "無人ジョブ（追従・週次3-6-9）の完了・エラーもここに届きます。"
                    ),
                    "color": _COLOR_OK,
                }
            ],
        }
        _ensure_shared_on_path()
        from hit_actions import post_discord_webhook

        response = post_discord_webhook(url, payload, timeout=15)
        status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status < 300:
            return ""
        body = ""
        try:
            body = str(getattr(response, "text", "") or "")[:200]
        except Exception:  # noqa: BLE001
            pass
        return f"Discord が拒否しました: HTTP {status} {body}"
    except Exception as exc:  # noqa: BLE001
        return str(exc)
