#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCRサービス

Tesseract OCRを優先使用、精度が低い場合はGoogle Cloud Vision APIにフォールバック
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging

# 画像処理
try:
    from PIL import Image
except ImportError:
    Image = None

# Tesseract OCR
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

# Google Cloud Vision API（オプション）
try:
    from google.cloud import vision
    GCV_AVAILABLE = True
except ImportError:
    GCV_AVAILABLE = False
    vision = None

# 画像前処理
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from utils.image_processor import preprocess_image_for_ocr
except ImportError:
    preprocess_image_for_ocr = None

logger = logging.getLogger(__name__)


class OCRService:
    """OCRサービス（Tesseract優先、GCVフォールバック）"""
    
    def __init__(self, tesseract_cmd: Optional[str] = None, gcv_credentials_path: Optional[str] = None):
        """
        Args:
            tesseract_cmd: Tesseract実行ファイルのパス（Windows等で必要）
            gcv_credentials_path: Google Cloud Vision API認証情報JSONファイルのパス
        """
        self.tesseract_cmd = tesseract_cmd
        if tesseract_cmd and TESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        self.gcv_client = None
        if gcv_credentials_path and GCV_AVAILABLE:
            try:
                import os
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcv_credentials_path
                self.gcv_client = vision.ImageAnnotatorClient()
            except Exception as e:
                logger.warning(f"Failed to initialize GCV client: {e}")
    
    def extract_text(self, image_path: str | Path, use_preprocessing: bool = True) -> Dict[str, Any]:
        """
        画像からテキストを抽出
        
        Args:
            image_path: 画像ファイルパス
            use_preprocessing: 画像前処理を使用するか
        
        Returns:
            {
                "text": str,  # 抽出されたテキスト
                "provider": str,  # "tesseract" or "gcv"
                "confidence": float,  # 信頼度（0-1、GCVのみ）
            }
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        # Tesseract優先
        if TESSERACT_AVAILABLE:
            try:
                result = self._extract_with_tesseract(image_path, use_preprocessing)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Tesseract OCR failed: {e}, falling back to GCV")
        
        # GCVフォールバック
        if GCV_AVAILABLE and self.gcv_client:
            try:
                result = self._extract_with_gcv(image_path)
                if result:
                    return result
            except Exception as e:
                logger.error(f"GCV OCR also failed: {e}")
        
        # どちらも失敗
        raise RuntimeError("OCR failed: Both Tesseract and GCV are unavailable or failed")
    
    def _extract_with_tesseract(self, image_path: Path, use_preprocessing: bool) -> Optional[Dict[str, Any]]:
        """Tesseract OCRで抽出"""
        if not TESSERACT_AVAILABLE or not Image:
            return None
        
        try:
            if use_preprocessing and preprocess_image_for_ocr:
                img = preprocess_image_for_ocr(image_path)
            else:
                img = Image.open(image_path)
            
            # 日本語+英語でOCR
            text = pytesseract.image_to_string(img, lang='jpn+eng')
            
            return {
                "text": text.strip(),
                "provider": "tesseract",
                "confidence": None,  # Tesseractは信頼度を直接取得できない
            }
        except Exception as e:
            logger.error(f"Tesseract extraction error: {e}")
            return None
    
    def _extract_with_gcv(self, image_path: Path) -> Optional[Dict[str, Any]]:
        """Google Cloud Vision APIで抽出"""
        if not GCV_AVAILABLE or not self.gcv_client:
            return None
        
        try:
            with open(image_path, 'rb') as f:
                content = f.read()
            
            image = vision.Image(content=content)
            response = self.gcv_client.text_detection(image=image)
            
            if response.error.message:
                raise Exception(f"GCV API error: {response.error.message}")
            
            texts = response.text_annotations
            if not texts:
                return {
                    "text": "",
                    "provider": "gcv",
                    "confidence": 0.0,
                }
            
            # 最初の要素が全文
            full_text = texts[0].description
            
            # 平均信頼度を計算（可能な場合）
            confidences = []
            for annotation in texts[1:]:  # 最初以外は個別文字/単語
                if hasattr(annotation, 'confidence'):
                    confidences.append(annotation.confidence)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else None
            
            return {
                "text": full_text.strip(),
                "provider": "gcv",
                "confidence": avg_confidence,
            }
        except Exception as e:
            logger.error(f"GCV extraction error: {e}")
            return None
    
    @staticmethod
    def is_tesseract_available() -> bool:
        """Tesseract OCRが利用可能か"""
        return TESSERACT_AVAILABLE
    
    @staticmethod
    def is_gcv_available() -> bool:
        """Google Cloud Vision APIが利用可能か"""
        return GCV_AVAILABLE

