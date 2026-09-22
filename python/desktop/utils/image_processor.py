#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像前処理ユーティリティ

OCR精度向上のための画像前処理（グレースケール、コントラスト調整、傾き補正など）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union
from PIL import Image, ImageEnhance, ImageFilter

try:
    from utils.ocr_runtime import OCR_MAX_IMAGE_SIDE, limit_image_side, register_heif_opener
except ImportError:
    from desktop.utils.ocr_runtime import OCR_MAX_IMAGE_SIDE, limit_image_side, register_heif_opener  # type: ignore


def preprocess_image_for_ocr(
    image_path: Union[str, Path, Image.Image],
    output_path: Optional[str | Path] = None,
    max_side: int = OCR_MAX_IMAGE_SIDE,
) -> Image.Image:
    """
    OCR用に画像を前処理
    
    Args:
        image_path: 入力画像パス、または開済みの PIL Image
        output_path: 処理後画像の保存先（Noneの場合は保存しない）
        max_side: 長辺の上限（ミニPC向けに原寸を縮小する）
    
    Returns:
        処理済みPIL Image
    """
    register_heif_opener()
    if isinstance(image_path, Image.Image):
        img = image_path
    else:
        img = Image.open(image_path)

    # EXIFの向きを反映（スマホ撮影のレシートが横倒しのままOCRされないようにする）
    try:
        img = _apply_exif_orientation(img)
    except Exception:
        pass

    # ミニPCのメモリ対策: 4000px超のスマホ写真を縮小
    new_size = limit_image_side(img.size, max_side=max_side)
    if new_size != img.size:
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # グレースケール変換
    if img.mode != 'L':
        img = img.convert('L')
    
    # コントラスト調整
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)  # 1.5倍に強化
    
    # 明度調整
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)
    
    # ガウシアンブラーでノイズ除去後にシャープ化
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
    img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=3))

    # シャープ化（オプション、必要に応じて）
    # enhancer = ImageEnhance.Sharpness(img)
    # img = enhancer.enhance(1.2)
    
    # 二値化（オプション、必要に応じてコメントアウト解除）
    # threshold = 128
    # img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
    
    if output_path:
        img.save(output_path)
    
    return img


def _apply_exif_orientation(image: Image.Image) -> Image.Image:
    """EXIF Orientation に従って回転する。無い・失敗ならそのまま。"""
    try:
        exif = image.getexif()
        orientation = exif.get(274) if exif else None  # 274 = Orientation
    except Exception:
        orientation = None
    if orientation == 3:
        return image.rotate(180, expand=True)
    if orientation == 6:
        return image.rotate(270, expand=True)
    if orientation == 8:
        return image.rotate(90, expand=True)
    return image


def auto_rotate_image(image: Image.Image) -> Image.Image:
    """
    画像の傾きを自動補正（簡易版）
    
    Note: より高度な傾き検出が必要な場合は、TesseractのOSD機能や
          OpenCVのHough変換などを使用することを検討
    """
    # 現時点ではそのまま返す（将来拡張用）
    return image

