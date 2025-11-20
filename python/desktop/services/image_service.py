#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像管理サービス

画像ファイルのスキャン、JAN抽出、グルーピング、回転などの処理を行う。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, NamedTuple
from datetime import datetime
from PIL import Image, ExifTags
import logging

# バーコード読み取りライブラリ（オプション）
# pyzbar (ZBar-based) - 遅延インポート（インポート時にエラーが出る可能性があるため）
PYZBAR_AVAILABLE = False
pyzbar = None

# pyzxing (ZXing-based, requires Java JRE) - 遅延インポート
PYZXING_AVAILABLE = False
BarCodeReader = None

# 遅延インポート関数
def _try_import_pyzbar():
    """pyzbarを遅延インポート（エラーがあっても無視）"""
    global PYZBAR_AVAILABLE, pyzbar
    if PYZBAR_AVAILABLE:
        return True
    try:
        from pyzbar import pyzbar as _pyzbar
        pyzbar = _pyzbar
        PYZBAR_AVAILABLE = True
        return True
    except Exception as e:
        logger.debug(f"pyzbar is not available: {e}")
        PYZBAR_AVAILABLE = False
        pyzbar = None
        return False

def _try_import_pyzxing():
    """pyzxingを遅延インポート"""
    global PYZXING_AVAILABLE, BarCodeReader
    if PYZXING_AVAILABLE:
        return True
    try:
        from pyzxing import BarCodeReader as _BarCodeReader
        BarCodeReader = _BarCodeReader
        PYZXING_AVAILABLE = True
        return True
    except ImportError:
        PYZXING_AVAILABLE = False
        BarCodeReader = None
        return False

logger = logging.getLogger(__name__)


class ImageRecord(NamedTuple):
    """画像レコード"""
    path: str
    capture_dt: Optional[datetime]
    jan_candidate: Optional[str]
    width: int
    height: int


class JanGroup(NamedTuple):
    """JANグループ"""
    jan: str
    images: List[ImageRecord]


class ImageService:
    """画像管理サービス"""
    
    # 対応する画像拡張子
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'}
    
    def __init__(self):
        pass
    
    def extract_jan_from_text(self, text: str) -> Optional[str]:
        """
        テキストからJANコードを抽出
        
        Args:
            text: 抽出対象のテキスト（ファイル名など）
        
        Returns:
            見つかったJANコード（8桁または13桁）、見つからない場合はNone
        """
        if not text:
            return None
        
        # 8桁または13桁の数字パターンを検索
        pattern = r'\b\d{8}\b|\b\d{13}\b'
        matches = re.findall(pattern, text)
        
        if matches:
            # 最初のマッチを返す
            return matches[0]
        
        return None
    
    def read_barcode_from_image(self, image_path: str) -> Optional[str]:
        """
        画像からバーコード（JANコード）を読み取る
        
        Args:
            image_path: 画像ファイルのパス
        
        Returns:
            読み取ったJANコード（8桁または13桁）、見つからない場合はNone
        
        Note:
            優先順位: pyzxing (ZXing-based) > pyzbar (ZBar-based)
            - pyzxing: Java JREが必要
            - pyzbar: zbarライブラリが必要（Windowsでは依存関係の問題がある場合あり）
        """
        # まずpyzxingを試す（ZXingベース、より確実）
        _try_import_pyzxing()
        if PYZXING_AVAILABLE:
            try:
                reader = BarCodeReader()
                results = reader.decode(image_path)
                
                if results:
                    for result in results:
                        barcode_data = result.get('raw', '')
                        barcode_format = result.get('format', '')
                        
                        # 数字のみを抽出（8桁または13桁）
                        digits = ''.join(c for c in barcode_data if c.isdigit())
                        if len(digits) in [8, 13]:
                            logger.info(f"Found barcode (ZXing): {digits} (type: {barcode_format}) from {image_path}")
                            return digits
                        
                        # バーコードデータがそのままJANコードの可能性
                        if len(barcode_data) in [8, 13] and barcode_data.isdigit():
                            logger.info(f"Found barcode (ZXing): {barcode_data} (type: {barcode_format}) from {image_path}")
                            return barcode_data
                
                logger.debug(f"No valid JAN barcode found in {image_path} (ZXing)")
            except Exception as e:
                logger.warning(f"ZXing barcode reading failed for {image_path}: {e}")
        
        # pyzbarをフォールバックとして試す
        _try_import_pyzbar()
        if PYZBAR_AVAILABLE:
            try:
                # 画像を開く
                with Image.open(image_path) as img:
                    # RGBモードに変換（必要に応じて）
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # バーコードを読み取る
                    barcodes = pyzbar.decode(img)
                    
                    if not barcodes:
                        return None
                    
                    # 最初のバーコードを返す
                    # EAN-13, EAN-8, UPC-A, UPC-Eなどを検出
                    for barcode in barcodes:
                        barcode_data = barcode.data.decode('utf-8')
                        barcode_type = barcode.type
                        
                        # JANコード（EAN-13, EAN-8, UPC-A, UPC-E）の場合
                        if barcode_type in ['EAN13', 'EAN8', 'UPCA', 'UPCE']:
                            # 数字のみを抽出（8桁または13桁）
                            digits = ''.join(c for c in barcode_data if c.isdigit())
                            if len(digits) in [8, 13]:
                                logger.info(f"Found barcode (ZBar): {digits} (type: {barcode_type}) from {image_path}")
                                return digits
                        
                        # その他のバーコードでも数字が8桁または13桁ならJANコードとして扱う
                        digits = ''.join(c for c in barcode_data if c.isdigit())
                        if len(digits) in [8, 13]:
                            logger.info(f"Found barcode (as JAN, ZBar): {digits} (type: {barcode_type}) from {image_path}")
                            return digits
                    
                    # マッチするバーコードが見つからなかった
                    logger.debug(f"No valid JAN barcode found in {image_path} (ZBar)")
                    return None
            except Exception as e:
                logger.warning(f"Failed to read barcode with pyzbar from {image_path}: {e}")
        
        # どちらも利用できない場合
        if not PYZXING_AVAILABLE and not PYZBAR_AVAILABLE:
            logger.warning("Neither pyzxing nor pyzbar is available. Install one of them to read barcodes from images.")
        
        return None
    
    def get_exif_datetime(self, image_path: str) -> Optional[datetime]:
        """
        EXIFから撮影日時を取得
        
        Args:
            image_path: 画像ファイルのパス
        
        Returns:
            撮影日時、取得できない場合はNone
        """
        try:
            with Image.open(image_path) as img:
                exif = img._getexif()
                if exif is None:
                    return None
                
                # DateTimeOriginalを探す
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == 'DateTimeOriginal':
                        # EXIF日時形式: "YYYY:MM:DD HH:MM:SS"
                        try:
                            dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                            return dt
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid EXIF datetime format: {value} at {image_path}")
                            return None
        except Exception as e:
            logger.warning(f"Failed to read EXIF from {image_path}: {e}")
            return None
        
        return None
    
    def scan_directory(self, directory_path: str) -> List[ImageRecord]:
        """
        ディレクトリをスキャンして画像ファイルを取得
        
        Args:
            directory_path: スキャン対象のディレクトリパス
        
        Returns:
            画像レコードのリスト（撮影日時順）
        """
        records: List[ImageRecord] = []
        directory = Path(directory_path)
        
        if not directory.exists() or not directory.is_dir():
            logger.warning(f"Directory does not exist or is not a directory: {directory_path}")
            return records
        
        # 画像ファイルを再帰的に取得
        for ext in self.SUPPORTED_EXTENSIONS:
            for img_path in directory.rglob(f"*{ext}"):
                try:
                    # EXIFから撮影日時を取得
                    capture_dt = self.get_exif_datetime(str(img_path))
                    
                    # JANコードを抽出（優先順位: 画像内のバーコード > ファイル名）
                    jan_candidate = None
                    
                    # まず画像内のバーコードを読み取る（pyzxing優先、pyzbarはフォールバック）
                    _try_import_pyzxing()
                    _try_import_pyzbar()
                    if PYZXING_AVAILABLE or PYZBAR_AVAILABLE:
                        jan_candidate = self.read_barcode_from_image(str(img_path))
                    
                    # バーコードが見つからない場合はファイル名から抽出
                    if not jan_candidate:
                        jan_candidate = self.extract_jan_from_text(img_path.name)
                    
                    # 画像サイズを取得
                    try:
                        with Image.open(img_path) as img:
                            width, height = img.size
                    except Exception:
                        width, height = 0, 0
                    
                    # 撮影日時が取得できない場合はファイル更新日時を使用
                    if capture_dt is None:
                        try:
                            mtime = os.path.getmtime(img_path)
                            capture_dt = datetime.fromtimestamp(mtime)
                        except Exception:
                            capture_dt = None
                    
                    records.append(ImageRecord(
                        path=str(img_path),
                        capture_dt=capture_dt,
                        jan_candidate=jan_candidate,
                        width=width,
                        height=height
                    ))
                except Exception as e:
                    logger.warning(f"Failed to process image {img_path}: {e}")
                    continue
        
        # 撮影日時順にソート
        records.sort(key=lambda r: r.capture_dt if r.capture_dt else datetime.min)
        
        return records
    
    def group_by_jan(self, records: List[ImageRecord]) -> List[JanGroup]:
        """
        画像レコードをJANコードでグルーピング
        
        撮影順に走査し、JANパターン（8桁または13桁数字）で新グループ開始。
        JAN写真が連続するまで次グループに含めない。
        
        Args:
            records: 画像レコードのリスト（撮影日時順）
        
        Returns:
            JANグループのリスト
        """
        if not records:
            return []
        
        groups: List[JanGroup] = []
        current_jan: Optional[str] = None
        current_images: List[ImageRecord] = []
        
        for record in records:
            jan = record.jan_candidate
            
            # JANが変わった場合は新しいグループを開始
            if jan != current_jan:
                # 現在のグループを保存
                if current_images:
                    groups.append(JanGroup(jan=current_jan if current_jan else "unknown", images=current_images))
                
                # 新しいグループを開始
                current_jan = jan
                current_images = [record]
            else:
                # 現在のグループに追加
                current_images.append(record)
        
        # 最後のグループを保存
        if current_images:
            groups.append(JanGroup(jan=current_jan if current_jan else "unknown", images=current_images))
        
        return groups
    
    def rotate_image(self, image_path: str, degrees: int) -> bool:
        """
        画像を90度単位で回転
        
        Args:
            image_path: 画像ファイルのパス
            degrees: 回転角度（90, 180, 270, -90, -180, -270）
        
        Returns:
            成功した場合はTrue、失敗した場合はFalse
        """
        try:
            # 角度を正規化（-270, -180, -90, 0, 90, 180, 270 → 0, 90, 180, 270）
            degrees = degrees % 360
            if degrees < 0:
                degrees = 360 + degrees
            
            # 90度単位でない場合は無視
            if degrees not in [0, 90, 180, 270]:
                logger.warning(f"Invalid rotation angle: {degrees} (must be multiple of 90)")
                return False
            
            if degrees == 0:
                return True  # 回転不要
            
            with Image.open(image_path) as img:
                # 回転
                rotated = img.rotate(-degrees, expand=True)  # PILは時計回りなので-をつける
                
                # EXIF情報を取得
                try:
                    exif = img.info.get('exif')
                except:
                    exif = None
                
                # 回転後の画像を保存
                rotated.save(image_path, exif=exif, quality=95)
                
                logger.info(f"Rotated image {image_path} by {degrees} degrees")
                return True
        except Exception as e:
            logger.error(f"Failed to rotate image {image_path}: {e}")
            return False
    
    @staticmethod
    def is_barcode_reader_available() -> bool:
        """バーコードリーダー（pyzxing または pyzbar）が利用可能か"""
        _try_import_pyzxing()
        _try_import_pyzbar()
        return PYZXING_AVAILABLE or PYZBAR_AVAILABLE

