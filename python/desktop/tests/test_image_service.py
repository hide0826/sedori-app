#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageService 純関数まわりの pytest（Track D Phase 0 安全網）。"""

from __future__ import annotations

from datetime import datetime

from PIL import Image

from desktop.services.image_service import (
    AUTO_CORRECT_PRESETS,
    DEFAULT_AUTO_CORRECT_PRESET,
    ImageRecord,
    ImageService,
)


def _rec(path: str, jan: str | None = None) -> ImageRecord:
    return ImageRecord(
        path=path,
        capture_dt=datetime(2026, 1, 1, 12, 0, 0),
        jan_candidate=jan,
        width=100,
        height=100,
    )


def test_extract_jan_13_and_8_digit():
    svc = ImageService()
    assert svc.extract_jan_from_text("4901234567890") == "4901234567890"
    assert svc.extract_jan_from_text("12345678") == "12345678"


def test_extract_jan_from_noisy_text():
    svc = ImageService()
    assert svc.extract_jan_from_text("JAN:4901234567890.jpg") == "4901234567890"
    assert svc.extract_jan_from_text("prefix 12345678 suffix") == "12345678"


def test_extract_jan_no_match():
    svc = ImageService()
    assert svc.extract_jan_from_text("") is None
    assert svc.extract_jan_from_text(None) is None  # type: ignore[arg-type]
    assert svc.extract_jan_from_text("abc") is None
    assert svc.extract_jan_from_text("1234567") is None  # 7桁は非対象
    assert svc.extract_jan_from_text("123456789") is None  # 9桁は非対象


def test_group_by_jan_empty():
    assert ImageService().group_by_jan([]) == []


def test_group_by_jan_consecutive_and_unknown():
    svc = ImageService()
    records = [
        _rec("a.jpg", None),
        _rec("b.jpg", None),
        _rec("c.jpg", "4901234567890"),
        _rec("d.jpg", "4901234567890"),
        _rec("e.jpg", "12345678"),
    ]
    groups = svc.group_by_jan(records)
    assert len(groups) == 3
    assert groups[0].jan == "unknown"
    assert len(groups[0].images) == 2
    assert groups[1].jan == "4901234567890"
    assert len(groups[1].images) == 2
    assert groups[2].jan == "12345678"
    assert len(groups[2].images) == 1


def test_group_by_jan_same_jan_after_other_starts_new_group():
    """連続でない同一 JAN は別グループになる（撮影順走査）。"""
    svc = ImageService()
    records = [
        _rec("a.jpg", "11111111"),
        _rec("b.jpg", "22222222"),
        _rec("c.jpg", "11111111"),
    ]
    groups = svc.group_by_jan(records)
    assert [g.jan for g in groups] == ["11111111", "22222222", "11111111"]


def test_resolve_auto_correct_preset():
    std = ImageService.resolve_auto_correct_preset("standard")
    assert std == AUTO_CORRECT_PRESETS["standard"]
    assert ImageService.resolve_auto_correct_preset("WEAK") == AUTO_CORRECT_PRESETS["weak"]
    assert ImageService.resolve_auto_correct_preset("Strong") == AUTO_CORRECT_PRESETS["strong"]
    assert ImageService.resolve_auto_correct_preset(None) == AUTO_CORRECT_PRESETS[DEFAULT_AUTO_CORRECT_PRESET]
    assert ImageService.resolve_auto_correct_preset("unknown") == AUTO_CORRECT_PRESETS[DEFAULT_AUTO_CORRECT_PRESET]
    assert ImageService.resolve_auto_correct_preset("  ") == AUTO_CORRECT_PRESETS[DEFAULT_AUTO_CORRECT_PRESET]


def test_save_format_for_path():
    assert ImageService._save_format_for_path("/x/a.jpg", False) == (
        "JPEG",
        {"quality": 92, "optimize": True},
    )
    assert ImageService._save_format_for_path("/x/a.jpeg", False)[0] == "JPEG"
    assert ImageService._save_format_for_path("/x/a.png", False) == ("PNG", {})
    assert ImageService._save_format_for_path("/x/a.webp", False) == ("WEBP", {"quality": 90})
    # lightweight は拡張子に関わらず JPEG quality 85
    assert ImageService._save_format_for_path("/x/a.png", True) == (
        "JPEG",
        {"quality": 85, "optimize": True},
    )
    assert ImageService._save_format_for_path("/x/a.bmp", False) == (
        "JPEG",
        {"quality": 92, "optimize": True},
    )


def test_apply_product_auto_correct_keeps_size_and_rgb():
    img = Image.new("RGB", (32, 24), color=(128, 64, 32))
    out = ImageService.apply_product_auto_correct(img, "standard")
    assert out.size == (32, 24)
    assert out.mode == "RGB"

    gray = Image.new("L", (16, 16), color=100)
    out_gray = ImageService.apply_product_auto_correct(gray, "weak")
    assert out_gray.size == (16, 16)
    assert out_gray.mode == "RGB"
