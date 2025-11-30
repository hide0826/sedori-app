#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像管理サービス

画像ファイルのスキャン、JAN抽出、グルーピング、回転などの処理を行う。
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, NamedTuple, Callable
from datetime import datetime
from PIL import Image, ExifTags, ImageEnhance
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
    
    def _preprocess_image_for_barcode(self, image_path: str, max_size: int = 1024) -> Optional[str]:
        """
        バーコード読み取り用に画像を前処理（リサイズ・グレースケール化・中央クロップ）
        
        Args:
            image_path: 元の画像ファイルのパス
            max_size: リサイズ後の最大幅/高さ（デフォルト: 1024px）
        
        Returns:
            前処理済み画像の一時ファイルパス、エラー時はNone
        """
        try:
            with Image.open(image_path) as img:
                # 画像のオリジナルサイズ
                orig_width, orig_height = img.size
                
                # リサイズ（大きな画像のみ縮小）
                if orig_width > max_size or orig_height > max_size:
                    if orig_width > orig_height:
                        new_width = max_size
                        new_height = int(orig_height * (max_size / orig_width))
                    else:
                        new_height = max_size
                        new_width = int(orig_width * (max_size / orig_height))
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # グレースケール化（カラー情報を減らして処理を軽くする）
                if img.mode != 'L':
                    img = img.convert('L')
                
                # コントラストを少し上げる（バーコードの読み取り精度向上）
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.2)
                
                # 一時ファイルに保存
                temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                os.close(temp_fd)  # ファイルディスクリプタを閉じる（PILが開くため）
                img.save(temp_path, 'JPEG', quality=85)
                return temp_path
        except Exception as e:
            logger.warning(f"Image preprocessing failed for {image_path}: {e}")
            return None
    
    def read_barcode_from_image(self, image_path: str, use_preprocessing: bool = True) -> Optional[str]:
        """
        画像からバーコード（JANコード）を読み取る
        
        Args:
            image_path: 画像ファイルのパス
            use_preprocessing: Trueの場合、画像を前処理してから読み取る（高速化）
        
        Returns:
            読み取ったJANコード（8桁または13桁）、見つからない場合はNone
        
        Note:
            優先順位: pyzxing (ZXing-based) > pyzbar (ZBar-based)
            - pyzxing: Java JREが必要
            - pyzbar: zbarライブラリが必要（Windowsでは依存関係の問題がある場合あり）
        """
        # 前処理済み画像の一時ファイル（使用後は削除）
        temp_image_path = None
        
        try:
            # 画像の前処理（高速化のためリサイズ・グレースケール化）
            if use_preprocessing:
                temp_image_path = self._preprocess_image_for_barcode(image_path)
                if temp_image_path:
                    image_to_decode = temp_image_path
                else:
                    image_to_decode = image_path  # 前処理失敗時は元の画像を使用
            else:
                image_to_decode = image_path
            
            # まずpyzxingを試す（ZXingベース、より確実）
            _try_import_pyzxing()
            if PYZXING_AVAILABLE:
                try:
                    reader = BarCodeReader()
                    results = reader.decode(image_to_decode)
                    
                    if results:
                        for result in results:
                            # pyzxingのrawフィールドは整数または文字列の可能性があるため、文字列に変換
                            raw_value = result.get('raw', '')
                            barcode_data = str(raw_value) if raw_value is not None else ''
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
                
                # ZXingで見つからなかった場合、前処理なしで再試行
                if temp_image_path:
                    try:
                        reader = BarCodeReader()
                        results = reader.decode(image_path)  # 元の画像で再試行
                        if results:
                            for result in results:
                                raw_value = result.get('raw', '')
                                barcode_data = str(raw_value) if raw_value is not None else ''
                                barcode_format = result.get('format', '')
                                digits = ''.join(c for c in barcode_data if c.isdigit())
                                if len(digits) in [8, 13]:
                                    logger.info(f"Found barcode (ZXing, original): {digits} (type: {barcode_format}) from {image_path}")
                                    return digits
                                if len(barcode_data) in [8, 13] and barcode_data.isdigit():
                                    logger.info(f"Found barcode (ZXing, original): {barcode_data} (type: {barcode_format}) from {image_path}")
                                    return barcode_data
                    except Exception:
                        pass  # 再試行失敗は無視
            
            # pyzbarをフォールバックとして試す
            _try_import_pyzbar()
            if PYZBAR_AVAILABLE:
                try:
                    # 前処理済み画像があれば使用、なければ元の画像を使用
                    image_to_open = temp_image_path if temp_image_path and os.path.exists(temp_image_path) else image_path
                    
                    # 画像を開く
                    with Image.open(image_to_open) as img:
                        # グレースケール化（pyzbarはグレースケールで精度が高い）
                        if img.mode != 'L':
                            img = img.convert('L')
                        
                        # バーコードを読み取る
                        barcodes = pyzbar.decode(img)
                        
                        if not barcodes:
                            pass  # 次の処理へ
                        else:
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
                            
                            logger.debug(f"No valid JAN barcode found in {image_path} (ZBar)")
                except Exception as e:
                    logger.warning(f"Failed to read barcode with pyzbar from {image_path}: {e}")
            
            # どちらも利用できない場合
            if not PYZXING_AVAILABLE and not PYZBAR_AVAILABLE:
                logger.warning("Neither pyzxing nor pyzbar is available. Install one of them to read barcodes from images.")
            
            return None
        
        finally:
            # 一時ファイルを削除
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.unlink(temp_image_path)
                except Exception as e:
                    logger.debug(f"Failed to delete temp image file {temp_image_path}: {e}")
    
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
    
    def scan_directory(
        self,
        directory_path: str,
        skip_barcode_reading: bool = True,
        skip_exif: bool = True,
        skip_image_size: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        file_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ImageRecord]:
        """
        ディレクトリをスキャンして画像ファイルを取得
        
        Args:
            directory_path: スキャン対象のディレクトリパス
            skip_barcode_reading: Trueの場合、バーコード読み取りをスキップ（ファイル名のみチェック）
            skip_exif: Trueの場合、EXIF読み取りをスキップ（ファイル更新日時を使用、高速化）
            skip_image_size: Trueの場合、画像サイズ取得をスキップ（0,0で登録、高速化）
            progress_callback: 進捗コールバック
            file_cache: ファイルパスをキーとするキャッシュ情報（mtime, recordを含む）
        
        Returns:
            画像レコードのリスト（撮影日時順）
        """
        records: List[ImageRecord] = []
        directory = Path(directory_path)
        
        if not directory.exists() or not directory.is_dir():
            logger.warning(f"Directory does not exist or is not a directory: {directory_path}")
            return records
        
        # 画像ファイルを再帰的に取得（高速化のため先に全ファイルリストを作成）
        image_paths = []
        for ext in self.SUPPORTED_EXTENSIONS:
            image_paths.extend(directory.rglob(f"*{ext}"))
        
        total_images = len(image_paths)
        if progress_callback:
            progress_callback(0, total_images)
        
        # 各画像を処理
        for index, img_path in enumerate(image_paths, start=1):
            try:
                path_str = str(img_path)
                current_mtime = 0.0
                try:
                    current_mtime = os.path.getmtime(path_str)
                except Exception:
                    pass

                # キャッシュヒット判定
                cached_data = file_cache.get(path_str) if file_cache else None
                if cached_data:
                    cached_mtime = cached_data.get("mtime")
                    # mtimeが指定されていない(None)、または一致すればキャッシュを利用
                    if cached_mtime is None or abs(current_mtime - cached_mtime) < 0.001:
                        # キャッシュからレコードを復元
                        cached_record = cached_data.get("record")
                        if cached_record:
                            records.append(cached_record)
                            continue
                        
                        # レコードそのものがなければdictから復元を試みる
                        db_row = cached_data.get("db_row")
                        if db_row:
                            capture_time_str = db_row.get("capture_time")
                            capture_dt = datetime.fromisoformat(capture_time_str) if capture_time_str else None
                            
                            # DBにはwidth/heightがない場合があるので注意（必要なら追加スキャン）
                            # ここでは高速化優先で0を入れるか、キャッシュにあればそれを使う
                            # ImageRecordはNamedTupleなので後から変更不可。
                            # DBスキーマにwidth/heightがないため、キャッシュデータに含める必要がある
                            # 呼び出し元が `record` オブジェクトを渡してくれることを期待する
                            pass

                # キャッシュミスまたは更新あり：通常スキャン
                # EXIFから撮影日時を取得（スキップ可能）
                capture_dt = None
                if not skip_exif:
                    capture_dt = self.get_exif_datetime(path_str)
                
                # JANコードを抽出（優先順位: 画像内のバーコード > ファイル名）
                jan_candidate = None
                
                # ファイル名からまず抽出（高速）
                jan_candidate = self.extract_jan_from_text(img_path.name)
                
                # バーコード読み取りが有効な場合のみ画像内のバーコードを読み取る（低速）
                if not jan_candidate and not skip_barcode_reading:
                    _try_import_pyzxing()
                    _try_import_pyzbar()
                    if PYZXING_AVAILABLE or PYZBAR_AVAILABLE:
                        jan_candidate = self.read_barcode_from_image(path_str)
                
                # 画像サイズを取得（スキップ可能）
                width, height = 0, 0
                if not skip_image_size:
                    try:
                        with Image.open(img_path) as img:
                            width, height = img.size
                    except Exception:
                        width, height = 0, 0
                
                # 撮影日時が取得できない場合はファイル更新日時を使用（高速）
                if capture_dt is None:
                    if current_mtime > 0:
                        capture_dt = datetime.fromtimestamp(current_mtime)
                    else:
                        capture_dt = None
                
                # 全画像を追加（JANコードなしも含む）
                records.append(ImageRecord(
                    path=path_str,
                    capture_dt=capture_dt,
                    jan_candidate=jan_candidate,
                    width=width,
                    height=height
                ))
            except Exception as e:
                logger.warning(f"Failed to process image {img_path}: {e}")
                continue
            finally:
                if progress_callback:
                    progress_callback(index, total_images)
        
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
    
    def is_barcode_only_image(self, image_path: str) -> bool:
        """
        画像がJANコード（バーコード）のみか判定
        
        判定基準:
        1. バーコードが検出される
        2. OCRテキストが数字・記号のみ、または商品名らしい文字列がない
        
        Args:
            image_path: 画像ファイルのパス
            
        Returns:
            True: バーコードのみの画像（除外対象）
            False: 商品写真など（アップロード対象）
        """
        import re
        
        # 1. バーコード検出
        jan = self.read_barcode_from_image(image_path)
        if not jan:
            return False  # バーコードなし = 商品写真
        
        # 2. OCR実行（商品名などのテキスト検出）
        try:
            from services.ocr_service import OCRService
            ocr_service = OCRService()
            ocr_result = ocr_service.extract_text(image_path, use_preprocessing=True)
            ocr_text = ocr_result.get("text", "").strip()
            
            # 3. テキスト分析
            # 数字・記号・空白のみの場合はバーコードのみと判定
            text_without_digits = re.sub(r'[0-9\s\-・]', '', ocr_text)
            
            # 商品名らしい文字列（ひらがな、カタカナ、漢字、英字）が少ない
            if len(text_without_digits) < 10:  # 意味のある文字が10文字未満
                return True  # バーコードのみ
            
            # 商品名らしいキーワードがない場合も除外
            product_keywords = ['商品', '品名', 'タイトル', 'title', 'name', '商品名']
            has_product_info = any(kw in ocr_text.lower() for kw in product_keywords)
            if not has_product_info and len(text_without_digits) < 20:
                return True
            
        except Exception as e:
            # OCR失敗時はバーコード検出のみで判定
            # バーコードが検出された = バーコードのみの可能性が高い
            logger.debug(f"OCR failed for barcode detection: {e}, assuming barcode-only image")
            return True
        
        return False  # 商品写真

