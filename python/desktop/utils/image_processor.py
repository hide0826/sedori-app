#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像前処理ユーティリティ

OCR精度向上のための画像前処理（グレースケール、コントラスト調整、傾き補正など）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from PIL import Image, ImageEnhance


def preprocess_image_for_ocr(image_path: str | Path, output_path: Optional[str | Path] = None) -> Image.Image:
    """
    OCR用に画像を前処理
    
    Args:
        image_path: 入力画像パス
        output_path: 処理後画像の保存先（Noneの場合は保存しない）
    
    Returns:
        処理済みPIL Image
    """
    img = Image.open(image_path)
    
    # グレースケール変換
    if img.mode != 'L':
        img = img.convert('L')
    
    # コントラスト調整
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)  # 1.5倍に強化
    
    # 明度調整
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)
    
    # シャープ化（オプション、必要に応じて）
    # enhancer = ImageEnhance.Sharpness(img)
    # img = enhancer.enhance(1.2)
    
    # 二値化（オプション、必要に応じてコメントアウト解除）
    # threshold = 128
    # img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
    
    if output_path:
        img.save(output_path)
    
    return img


def auto_rotate_image(image: Image.Image) -> Image.Image:
    """
    画像の傾きを自動補正（簡易版）
    
    Note: より高度な傾き検出が必要な場合は、TesseractのOSD機能や
          OpenCVのHough変換などを使用することを検討
    """
    # 現時点ではそのまま返す（将来拡張用）
    return image

