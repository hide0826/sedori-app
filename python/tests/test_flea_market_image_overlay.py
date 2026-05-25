#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ画像テキストオーバーレイのユニットテスト。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.services.flea_market_image_overlay_service import (  # noqa: E402
    DEFAULT_FLEA_SQUARE_SIZE,
    ImageOverlaySettings,
    TextBandStyle,
    apply_text_overlay,
    crop_image_to_square_cover,
    default_overlay_settings,
    export_image_to_square,
    fit_image_to_square_letterbox,
    resolve_meiryo_font_path,
)


@pytest.fixture
def sample_image(tmp_path: Path) -> str:
    path = tmp_path / "sample.jpg"
    img = Image.new("RGB", (800, 600), color=(120, 80, 200))
    img.save(path, format="JPEG")
    return str(path)


def test_resolve_meiryo_or_fallback():
    _ = resolve_meiryo_font_path()


def test_letterbox_has_margins_on_wide_image():
    img = Image.new("RGB", (800, 600), color=(100, 100, 100))
    out = fit_image_to_square_letterbox(img, size=1080, bg_rgb=(255, 255, 255))
    assert out.size == (1080, 1080)
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((540, 540)) != (255, 255, 255)


def test_cover_fills_square_no_corner_margin():
    img = Image.new("RGB", (800, 600), color=(100, 100, 100))
    out = crop_image_to_square_cover(img, size=1080)
    assert out.size == (1080, 1080)
    assert out.getpixel((0, 0)) == (100, 100, 100)
    assert out.getpixel((1079, 1079)) == (100, 100, 100)


def test_apply_overlay_square_cover_default(sample_image: str, tmp_path: Path):
    settings = default_overlay_settings("上部", "新品")
    assert settings.square_fit_mode == "cover"
    result = apply_text_overlay(
        sample_image,
        settings=settings,
        output_path=str(tmp_path / "cover.jpg"),
    )
    with Image.open(result) as img:
        assert img.size == (DEFAULT_FLEA_SQUARE_SIZE, DEFAULT_FLEA_SQUARE_SIZE)


def test_bottom_band_has_gap_from_image_edge(sample_image: str, tmp_path: Path):
    settings = default_overlay_settings("", "新品未開封")
    settings.square_fit_mode = "cover"
    result = apply_text_overlay(
        sample_image,
        settings=settings,
        output_path=str(tmp_path / "bottom_gap.jpg"),
    )
    with Image.open(result) as img:
        w, h = img.size
        bottom_mid = img.getpixel((w // 2, h - 1))
        # 下端ピクセルは帯ではなく写真側の色（紫系サンプル）であること
        assert bottom_mid[0] < 200 or bottom_mid[2] > 100


def test_cover_mode_keeps_top_text_band(sample_image: str, tmp_path: Path):
    """ズーム埋めでも帯は正方形の上下に描画され、中央クロップで消えない。"""
    settings = default_overlay_settings("テスト上部テキスト", "")
    settings.square_fit_mode = "cover"
    settings.top.bg_opacity_percent = 100
    settings.top.bg_color = (255, 255, 255)
    result = apply_text_overlay(
        sample_image,
        settings=settings,
        output_path=str(tmp_path / "cover_text.jpg"),
    )
    with Image.open(result) as img:
        assert img.size == (DEFAULT_FLEA_SQUARE_SIZE, DEFAULT_FLEA_SQUARE_SIZE)
        top_row = img.getpixel((img.width // 2, 2))
        # 上部帯は白背景のため、生写真(紫系)より明るい
        assert top_row[0] > 200 and top_row[1] > 200 and top_row[2] > 200


def test_apply_overlay_square_letterbox(sample_image: str, tmp_path: Path):
    settings = default_overlay_settings("上部", "新品")
    settings.square_fit_mode = "letterbox"
    result = apply_text_overlay(
        sample_image,
        settings=settings,
        output_path=str(tmp_path / "letterbox.jpg"),
    )
    with Image.open(result) as opened:
        assert opened.size == (DEFAULT_FLEA_SQUARE_SIZE, DEFAULT_FLEA_SQUARE_SIZE)
    with Image.open(result) as img:
        corners_white = sum(
            1
            for xy in ((0, 0), (0, 1079), (1079, 0), (1079, 1079))
            if img.getpixel(xy) == (255, 255, 255)
        )
        assert corners_white >= 2


def test_apply_overlay_without_square(sample_image: str, tmp_path: Path):
    settings = default_overlay_settings("上部", "新品")
    settings.export_square = False
    result = apply_text_overlay(
        sample_image,
        settings=settings,
        output_path=str(tmp_path / "nosquare.jpg"),
    )
    with Image.open(result) as img:
        assert img.size == (800, 600)


def test_apply_overlay_requires_text(sample_image: str):
    with pytest.raises(ValueError):
        apply_text_overlay(sample_image, settings=ImageOverlaySettings())


def test_cache_key_differs_by_fit_mode(sample_image: str):
    a = default_overlay_settings("同じ", "同じ")
    b = default_overlay_settings("同じ", "同じ")
    b.square_fit_mode = "letterbox"
    assert a.cache_key(sample_image) != b.cache_key(sample_image)


def test_export_image_to_square_modes():
    img = Image.new("RGB", (400, 200), color=(50, 50, 50))
    side = DEFAULT_FLEA_SQUARE_SIZE
    cover = export_image_to_square(img, size=side, mode="cover")
    letter = export_image_to_square(img, size=side, mode="letterbox")
    assert cover.size == letter.size == (side, side)
    assert cover.getpixel((0, 0)) == (50, 50, 50)
    assert letter.getpixel((0, 0)) == (255, 255, 255)
