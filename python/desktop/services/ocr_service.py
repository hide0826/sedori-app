#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCRサービス

Tesseract OCRを優先使用、精度が低い場合はGoogle Cloud Vision APIにフォールバック
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import os

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
try:
    from utils.ensure_desktop_sys_path import ensure_desktop_on_sys_path
except ImportError:
    from desktop.utils.ensure_desktop_sys_path import ensure_desktop_on_sys_path  # type: ignore

ensure_desktop_on_sys_path()
try:
    from utils.image_processor import preprocess_image_for_ocr
except ImportError:
    try:
        from desktop.utils.image_processor import preprocess_image_for_ocr  # type: ignore
    except ImportError:
        preprocess_image_for_ocr = None

try:
    from utils.ocr_runtime import (
        describe_ocr_readiness,
        discover_tessdata_dir,
        discover_tesseract_cmd,
        ensure_japanese_tessdata,
        tessdata_has_japanese,
        tessdata_prefix_for_env,
        tesseract_lang_string,
        LOCAL_TESSDATA_DIR,
        register_heif_opener,
    )
except ImportError:
    from desktop.utils.ocr_runtime import (  # type: ignore
        describe_ocr_readiness,
        discover_tessdata_dir,
        discover_tesseract_cmd,
        ensure_japanese_tessdata,
        tessdata_has_japanese,
        tessdata_prefix_for_env,
        tesseract_lang_string,
        LOCAL_TESSDATA_DIR,
        register_heif_opener,
    )

logger = logging.getLogger(__name__)


class OCRService:
    """OCRサービス（Tesseract優先、GCVフォールバック）"""
    
    def __init__(self, tesseract_cmd: Optional[str] = None, gcv_credentials_path: Optional[str] = None, tessdata_dir: Optional[str] = None):
        """
        Args:
            tesseract_cmd: Tesseract実行ファイルのパス（Windows等で必要）
            gcv_credentials_path: Google Cloud Vision API認証情報JSONファイルのパス
            tessdata_dir: Tessdataディレクトリのパス（tessdata_best用、環境変数TESSDATA_PREFIXを設定）
        """
        # 設定が指定されていない場合はQSettingsから読み込む
        if tesseract_cmd is None or tessdata_dir is None or gcv_credentials_path is None:
            try:
                from PySide6.QtCore import QSettings
                settings = QSettings("HIRIO", "DesktopApp")
                if tesseract_cmd is None:
                    tesseract_cmd = settings.value("ocr/tesseract_cmd", "") or None
                if tessdata_dir is None:
                    tessdata_dir = settings.value("ocr/tessdata_dir", "") or None
                if gcv_credentials_path is None:
                    gcv_credentials_path = settings.value("ocr/gcv_credentials", "") or None
            except Exception as e:
                logger.debug(f"Failed to load OCR settings from QSettings: {e}")

        # 前PCのパスが残っていても、このPC上に実在するものだけ使う
        if tesseract_cmd and not Path(str(tesseract_cmd)).is_file():
            logger.warning("Configured tesseract_cmd does not exist: %s", tesseract_cmd)
            tesseract_cmd = None
        if tessdata_dir and not Path(str(tessdata_dir)).is_dir():
            logger.warning("Configured tessdata_dir does not exist: %s", tessdata_dir)
            tessdata_dir = None

        tesseract_cmd = discover_tesseract_cmd(tesseract_cmd)
        tessdata_dir = discover_tessdata_dir(tessdata_dir, tesseract_cmd=tesseract_cmd)

        self.tesseract_cmd = tesseract_cmd
        self.tessdata_dir = tessdata_dir
        if tesseract_cmd and TESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        
        # Tessdataディレクトリの設定
        # TESSDATA_PREFIX は tessdata フォルダの「親」を指す必要がある
        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_prefix_for_env(tessdata_dir)
            logger.info("TESSDATA_PREFIX set to: %s (tessdata=%s)", os.environ["TESSDATA_PREFIX"], tessdata_dir)

        if tesseract_cmd or tessdata_dir:
            self._persist_discovered_paths(tesseract_cmd, tessdata_dir)
        
        self.gcv_client = None
        if gcv_credentials_path and GCV_AVAILABLE and Path(str(gcv_credentials_path)).is_file():
            try:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcv_credentials_path
                self.gcv_client = vision.ImageAnnotatorClient()
            except Exception as e:
                logger.warning(f"Failed to initialize GCV client: {e}")
        elif gcv_credentials_path:
            logger.warning("GCV credentials path does not exist: %s", gcv_credentials_path)

    @staticmethod
    def _persist_discovered_paths(tesseract_cmd: Optional[str], tessdata_dir: Optional[str]) -> None:
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("HIRIO", "DesktopApp")
            if tesseract_cmd:
                settings.setValue("ocr/tesseract_cmd", tesseract_cmd)
            if tessdata_dir:
                settings.setValue("ocr/tessdata_dir", tessdata_dir)
        except Exception as exc:
            logger.debug("Could not persist OCR paths: %s", exc)

    def ensure_ready(self) -> Tuple[bool, str]:
        """
        全件OCR前の点検。日本語データが無ければ取得を試みる。
        Returns: (ok, ユーザー向けメッセージ)
        """
        if not self.tesseract_cmd:
            self.tesseract_cmd = discover_tesseract_cmd()
            if self.tesseract_cmd and TESSERACT_AVAILABLE:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        if not self.tessdata_dir:
            self.tessdata_dir = discover_tessdata_dir(tesseract_cmd=self.tesseract_cmd)

        if self.tessdata_dir and not tessdata_has_japanese(self.tessdata_dir):
            target = Path(self.tessdata_dir)
            if not target.is_dir():
                target = LOCAL_TESSDATA_DIR
            if ensure_japanese_tessdata(target):
                self.tessdata_dir = str(target)
            elif ensure_japanese_tessdata(LOCAL_TESSDATA_DIR):
                self.tessdata_dir = str(LOCAL_TESSDATA_DIR)

        if self.tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_prefix_for_env(self.tessdata_dir)

        self._persist_discovered_paths(self.tesseract_cmd, self.tessdata_dir)
        return describe_ocr_readiness(
            self.tesseract_cmd,
            self.tessdata_dir,
            pytesseract_imported=TESSERACT_AVAILABLE,
        )
    
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

        register_heif_opener()
        
        # GCVが利用可能な場合は優先（精度が高いため）
        if GCV_AVAILABLE and self.gcv_client:
            try:
                result = self._extract_with_gcv(image_path)
                if result and result.get('text', '').strip():
                    logger.info("Using Google Cloud Vision API for OCR")
                    return result
            except Exception as e:
                logger.warning(f"GCV OCR failed: {e}, falling back to Tesseract")
        
        # Tesseractフォールバック
        if TESSERACT_AVAILABLE and self.tesseract_cmd:
            try:
                result = self._extract_with_tesseract(image_path, use_preprocessing)
                if result:
                    logger.info("Using Tesseract OCR")
                    return result
            except Exception as e:
                logger.warning(f"Tesseract OCR failed: {e}")
        
        # どちらも失敗
        ready, reason = self.ensure_ready()
        if not ready:
            raise RuntimeError(f"OCR failed: {reason}")
        if GCV_AVAILABLE and self.gcv_client:
            raise RuntimeError("OCR failed: Both GCV and Tesseract failed")
        elif TESSERACT_AVAILABLE:
            raise RuntimeError("OCR failed: Tesseract failed and GCV is not configured")
        else:
            raise RuntimeError("OCR failed: Neither Tesseract nor GCV is available")
    
    def _extract_with_tesseract(self, image_path: Path, use_preprocessing: bool) -> Optional[Dict[str, Any]]:
        """Tesseract OCRで抽出"""
        if not TESSERACT_AVAILABLE or not Image:
            return None
        if not self.tesseract_cmd:
            return None
        
        try:
            if use_preprocessing and preprocess_image_for_ocr:
                img = preprocess_image_for_ocr(image_path)
            else:
                register_heif_opener()
                img = Image.open(image_path)

            lang = tesseract_lang_string(self.tessdata_dir)
            # --tessdata-dir に引用符を付けると Windows でパスが壊れ、
            # 「処理せず完了」と同じ空振りになる。TESSDATA_PREFIX だけ使う。
            config = "--oem 1 --psm 6"

            text = pytesseract.image_to_string(
                img,
                lang=lang,
                config=config,
            )
            
            # OCR結果の正規化
            try:
                from ..utils.ocr_normalizer import normalize_ocr_text
                text = normalize_ocr_text(text)
            except ImportError:
                # 正規化モジュールがない場合はそのまま
                pass

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
            
            # OCR結果の正規化
            try:
                from ..utils.ocr_normalizer import normalize_ocr_text
                full_text = normalize_ocr_text(full_text)
            except ImportError:
                # 正規化モジュールがない場合はそのまま
                pass
            
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
        """pytesseract が import できるか（本体の有無は ensure_ready で見る）"""
        return TESSERACT_AVAILABLE

    def is_tesseract_engine_ready(self) -> bool:
        """tesseract.exe と日本語データが揃っているか"""
        ok, _ = describe_ocr_readiness(
            self.tesseract_cmd,
            self.tessdata_dir,
            pytesseract_imported=TESSERACT_AVAILABLE,
        )
        return ok
    
    @staticmethod
    def is_gcv_available() -> bool:
        """Google Cloud Vision APIが利用可能か"""
        return GCV_AVAILABLE
