#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日本語OCR動作確認用の簡易スクリプト。

1. 日本語テキストを含むテスト画像を生成
2. OCRService を使ってテキスト抽出
3. 認識結果を標準出力に表示

実行方法:

    cd python
    python scripts/ocr_japanese_test.py

"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from desktop.services.ocr_service import OCRService  # noqa: E402


def _find_japanese_font() -> ImageFont.ImageFont:
    """Windows環境で利用可能そうな日本語フォントを優先的に探す。"""
    candidate_paths = [
        Path(r"C:/Windows/Fonts/meiryo.ttc"),
        Path(r"C:/Windows/Fonts/MSMINCHO.TTC"),
        Path(r"C:/Windows/Fonts/msgothic.ttc"),
    ]

    for font_path in candidate_paths:
        if font_path.exists():
            try:
                # truetype の第2引数はフォントサイズ
                return ImageFont.truetype(str(font_path), 48)
            except Exception:
                continue

    # フォントが見つからなければ PIL のデフォルトを利用（日本語は豆腐になる可能性あり）
    return ImageFont.load_default()


def create_sample_image(dest_path: Path) -> Path:
    """日本語テキストを含むテスト画像を生成する。"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (1200, 360), color="white")
    draw = ImageDraw.Draw(image)
    font = _find_japanese_font()

    messages = [
        "レシートOCRテスト",
        "日付: 2025年11月07日",
        "店舗名: ブックオフ池袋店",
        "電話: 03-5950-XXXX",
        "点数: 5点 / 合計 4,580円",
    ]

    y = 40
    for msg in messages:
        draw.text((60, y), msg, fill="black", font=font)
        y += 70

    image.save(dest_path)
    return dest_path


def run_ocr(image_path: Path) -> None:
    ocr_service = OCRService()
    result = ocr_service.extract_text(image_path, use_preprocessing=True)

    print("=== OCR 認識結果 ===")
    print(f"プロバイダ: {result.get('provider')}")
    print(result.get("text") or "(テキストなし)")


def main() -> None:
    output_dir = ROOT_DIR / "desktop" / "data" / "receipts"
    sample_image = output_dir / "ocr_japanese_sample.png"

    print(f"テスト画像を生成: {sample_image}")
    image_path = create_sample_image(sample_image)

    print("OCR を実行します...")
    run_ocr(image_path)


if __name__ == "__main__":
    main()

