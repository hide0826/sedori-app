#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reprice_discord_notify の単体テスト（ネットワーク無し）。"""

from __future__ import annotations

from desktop.services.reprice_discord_notify import (
    build_reprice_discord_payload,
    notify_reprice_result,
)


def test_build_payload_success():
    payload = build_reprice_discord_payload(
        "follow",
        success_count=10,
        failed_count=0,
        targets=10,
        extra={"transport": "feed", "feedId": "F1", "at": "2026-10-26T21:00:00"},
    )
    embed = payload["embeds"][0]
    assert "全件価格改定完了" in embed["title"]
    assert "追従" in embed["title"]
    assert "成功: 10 件" in embed["description"]
    assert "feedId: F1" in embed["description"]
    assert embed["color"] == 0x2ECC71


def test_build_payload_partial_failure():
    payload = build_reprice_discord_payload(
        "weekly369",
        success_count=8,
        failed_count=2,
        targets=10,
        failed_skus=["SKU-A", "SKU-B"],
        extra={"failed_csv": "C:/tmp/fail.csv"},
    )
    embed = payload["embeds"][0]
    assert "一部失敗" in embed["title"]
    assert "週次3-6-9" in embed["title"]
    assert "失敗SKU: SKU-A, SKU-B" in embed["description"]
    assert embed["color"] == 0xE67E22


def test_build_payload_fatal_error():
    payload = build_reprice_discord_payload(
        "follow",
        success_count=0,
        failed_count=0,
        targets=0,
        error="レポートタイムアウト",
    )
    embed = payload["embeds"][0]
    assert "エラー発生" in embed["title"]
    assert "レポートタイムアウト" in embed["description"]
    assert embed["color"] == 0xE74C3C


def test_notify_dry_run_skips():
    assert (
        notify_reprice_result(
            "follow",
            dry_run=True,
            success_count=1,
            webhook_url="https://example.invalid/webhook",
        )
        is False
    )


def test_notify_empty_webhook_skips():
    assert (
        notify_reprice_result(
            "follow",
            dry_run=False,
            success_count=1,
            webhook_url="",
        )
        is False
    )


if __name__ == "__main__":
    test_build_payload_success()
    test_build_payload_partial_failure()
    test_build_payload_fatal_error()
    test_notify_dry_run_skips()
    test_notify_empty_webhook_skips()
    print("ALL OK")
