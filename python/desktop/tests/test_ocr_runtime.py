#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR実行環境の単体テスト（Tesseract本体なしでもパス収集・縮小は確認できる）。"""
from pathlib import Path

from desktop.utils.ocr_runtime import (
    collect_receipt_image_paths,
    describe_ocr_readiness,
    discover_tesseract_cmd,
    limit_image_side,
    tessdata_prefix_for_env,
)


def test_collect_top_level_images(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"fake")
    (tmp_path / "b.PNG").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_bytes(b"no")
    (tmp_path / "._skip.jpg").write_bytes(b"fake")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "c.webp").write_bytes(b"fake")

    paths = collect_receipt_image_paths(tmp_path, recursive_if_empty=True)
    names = {Path(p).name.lower() for p in paths}
    assert names == {"a.jpg", "b.png"}


def test_collect_recursive_when_top_empty(tmp_path: Path):
    nested = tmp_path / "day1"
    nested.mkdir()
    (nested / "receipt.heic").write_bytes(b"fake")
    paths = collect_receipt_image_paths(tmp_path, recursive_if_empty=True)
    assert len(paths) == 1
    assert paths[0].endswith("receipt.heic")


def test_tessdata_prefix_keeps_tessdata_folder_on_windows():
    assert tessdata_prefix_for_env(r"C:\Program Files\Tesseract-OCR\tessdata") == r"C:\Program Files\Tesseract-OCR\tessdata"


def test_tessdata_prefix_appends_tessdata_when_parent_given(tmp_path: Path):
    tess = tmp_path / "tessdata"
    tess.mkdir()
    assert tessdata_prefix_for_env(tmp_path) == str(tess)


def test_limit_image_side_does_not_upscale():
    assert limit_image_side((800, 600), max_side=1920) == (800, 600)


def test_limit_image_side_shrinks_long_edge():
    width, height = limit_image_side((4000, 3000), max_side=1920)
    assert max(width, height) == 1920
    assert width == 1920
    assert height == 1440


def test_readiness_rejects_missing_binary():
    ok, msg = describe_ocr_readiness(None, r"C:\missing", pytesseract_imported=True)
    assert ok is False
    assert "tesseract.exe" in msg.lower() or "Tesseract" in msg


def test_discover_tesseract_prefers_existing_explicit(tmp_path: Path):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"x")
    assert discover_tesseract_cmd(str(fake)) == str(fake)
    assert discover_tesseract_cmd(str(tmp_path / "nope.exe")) != str(tmp_path / "nope.exe")
