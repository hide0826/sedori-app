#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像管理サービス

画像ファイルのスキャン、JAN抽出、グルーピング、回転などの処理を行う。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, NamedTuple, Callable, Set
from datetime import datetime
from PIL import Image, ExifTags, ImageEnhance, ImageOps
import logging

logger = logging.getLogger(__name__)

# バーコード読み取りライブラリ（オプション・遅延インポート）
# zxing-cpp: Java不要。このPCの主力
# pyzxing: Java JRE が必要
# pyzbar: Windows では VC++2013 と zbar DLL が必要
PYZBAR_AVAILABLE = False
pyzbar = None
PYZXING_AVAILABLE = False
BarCodeReader = None
ZXINGCPP_AVAILABLE = False
zxingcpp = None


def _try_import_zxingcpp() -> bool:
    """zxing-cpp を遅延インポート（Java不要）"""
    global ZXINGCPP_AVAILABLE, zxingcpp
    if ZXINGCPP_AVAILABLE:
        return True
    try:
        import zxingcpp as _zxingcpp
        zxingcpp = _zxingcpp
        ZXINGCPP_AVAILABLE = True
        return True
    except Exception as e:
        logger.debug("zxing-cpp is not available: %s", e)
        ZXINGCPP_AVAILABLE = False
        zxingcpp = None
        return False


def _try_import_pyzbar():
    """pyzbarを遅延インポート（エラーがあっても無視）"""
    global PYZBAR_AVAILABLE, pyzbar
    if PYZBAR_AVAILABLE:
        return True
    try:
        import importlib.util
        spec = importlib.util.find_spec("pyzbar")
        if spec and spec.origin and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(os.path.dirname(spec.origin))
        from pyzbar import pyzbar as _pyzbar
        pyzbar = _pyzbar
        PYZBAR_AVAILABLE = True
        return True
    except Exception as e:
        logger.debug("pyzbar is not available: %s", e)
        PYZBAR_AVAILABLE = False
        pyzbar = None
        return False


def _try_import_pyzxing():
    """pyzxingを遅延インポート（Java が無い場合は使わない）"""
    global PYZXING_AVAILABLE, BarCodeReader
    if PYZXING_AVAILABLE:
        return True
    try:
        if not shutil.which("java"):
            logger.debug("pyzxing skipped: Java JRE not found")
            PYZXING_AVAILABLE = False
            BarCodeReader = None
            return False
        from pyzxing import BarCodeReader as _BarCodeReader
        BarCodeReader = _BarCodeReader
        PYZXING_AVAILABLE = True
        return True
    except Exception as e:
        logger.debug("pyzxing is not available: %s", e)
        PYZXING_AVAILABLE = False
        BarCodeReader = None
        return False


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


class AutoCorrectPreset(NamedTuple):
    """出品向け自動補正プリセット（contrast / brightness / sharpness の倍率）"""
    contrast: float
    brightness: float
    sharpness: float


AUTO_CORRECT_PRESETS: Dict[str, AutoCorrectPreset] = {
    "weak": AutoCorrectPreset(contrast=1.08, brightness=1.03, sharpness=1.10),
    "standard": AutoCorrectPreset(contrast=1.18, brightness=1.06, sharpness=1.22),
    "strong": AutoCorrectPreset(contrast=1.28, brightness=1.10, sharpness=1.35),
}
DEFAULT_AUTO_CORRECT_PRESET = "standard"


class ImageService:
    """画像管理サービス"""
    
    # 対応する画像拡張子
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'}
    
    def __init__(self):
        pass
    
    @staticmethod
    def normalize_barcode_to_jan(
        raw: Any,
        known_jans: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """
        バーコード生データ／数字列を仕入DB照合用の JAN にする。

        - 13桁・8桁はそのまま
        - 12桁（UPC-A）は先頭0を付けて EAN-13 にする
        - known_jans があれば、その集合と一致する形を優先する
        """
        digits = "".join(c for c in str(raw or "") if c.isdigit())
        if not digits:
            return None

        candidates: List[str] = []
        if len(digits) in (8, 13):
            candidates.append(digits)
        if len(digits) == 12:
            candidates.append("0" + digits)
            candidates.append(digits)
        if len(digits) == 14 and digits.startswith("0"):
            candidates.append(digits[1:])
        if len(digits) == 13 and digits.startswith("0"):
            candidates.append(digits[1:])

        known = known_jans or set()
        for cand in candidates:
            if cand in known:
                return cand
        for jan in known:
            if len(jan) < 8:
                continue
            if jan == digits or jan.endswith(digits) or digits.endswith(jan):
                if abs(len(jan) - len(digits)) <= 1:
                    return jan

        for cand in candidates:
            if len(cand) in (8, 13):
                return cand
        return None

    def extract_jan_from_text(
        self,
        text: str,
        known_jans: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """
        テキストからJANコードを抽出
        
        Args:
            text: 抽出対象のテキスト（ファイル名など）
            known_jans: 仕入DBのJAN集合。あればファイル名内の一致を優先する
        
        Returns:
            見つかったJANコード（8桁または13桁）、見つからない場合はNone
        """
        if not text:
            return None

        known = known_jans or set()
        if known:
            for jan in sorted(known, key=len, reverse=True):
                if jan and jan in text:
                    return jan
        
        # 8桁または13桁の数字パターンを検索
        pattern = r'\b\d{8}\b|\b\d{13}\b'
        matches = re.findall(pattern, text)
        
        if matches:
            return self.normalize_barcode_to_jan(matches[0], known)
        
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
    
    def _decode_jan_with_zxingcpp(
        self,
        image_path: str,
        known_jans: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """zxing-cpp で画像から JAN を読む（Java 不要）"""
        if not _try_import_zxingcpp() or zxingcpp is None:
            return None
        try:
            import numpy as np
            with Image.open(image_path) as img:
                arr = np.ascontiguousarray(np.array(img.convert("RGB")), dtype=np.uint8)
            results = zxingcpp.read_barcodes(arr)
            for result in results or []:
                jan = self.normalize_barcode_to_jan(getattr(result, "text", None), known_jans)
                if jan:
                    fmt = getattr(result, "format", "")
                    logger.info(
                        "Found barcode (zxing-cpp): %s (type: %s) from %s",
                        jan, fmt, image_path,
                    )
                    return jan
        except Exception as e:
            logger.warning("zxing-cpp barcode reading failed for %s: %s", image_path, e)
        return None

    def read_barcode_from_image(
        self,
        image_path: str,
        use_preprocessing: bool = True,
        known_jans: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """
        画像からバーコード（JANコード）を読み取る
        
        Args:
            image_path: 画像ファイルのパス
            use_preprocessing: Trueの場合、画像を前処理してから読み取る（高速化）
        
        Returns:
            読み取ったJANコード（8桁または13桁）、見つからない場合はNone
        
        Note:
            優先順位: zxing-cpp（Java不要）> pyzxing（Java必要）> pyzbar
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

            jan = self._decode_jan_with_zxingcpp(image_to_decode, known_jans)
            if jan:
                return jan
            if temp_image_path:
                jan = self._decode_jan_with_zxingcpp(image_path, known_jans)
                if jan:
                    return jan
            
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
                            jan = self.normalize_barcode_to_jan(barcode_data, known_jans)
                            if jan:
                                logger.info(f"Found barcode (ZXing): {jan} (type: {barcode_format}) from {image_path}")
                                return jan
                    
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
                                jan = self.normalize_barcode_to_jan(barcode_data, known_jans)
                                if jan:
                                    logger.info(f"Found barcode (ZXing, original): {jan} (type: {barcode_format}) from {image_path}")
                                    return jan
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
                                jan = self.normalize_barcode_to_jan(barcode_data, known_jans)
                                if jan:
                                    logger.info(f"Found barcode (ZBar): {jan} (type: {barcode_type}) from {image_path}")
                                    return jan
                            
                            logger.debug(f"No valid JAN barcode found in {image_path} (ZBar)")
                except Exception as e:
                    logger.warning(f"Failed to read barcode with pyzbar from {image_path}: {e}")

                if temp_image_path and os.path.exists(image_path):
                    try:
                        with Image.open(image_path) as img:
                            if img.mode != "L":
                                img = img.convert("L")
                            barcodes = pyzbar.decode(img)
                            for barcode in barcodes or []:
                                jan = self.normalize_barcode_to_jan(
                                    barcode.data.decode("utf-8"), known_jans
                                )
                                if jan:
                                    logger.info(
                                        "Found barcode (ZBar, original): %s (type: %s) from %s",
                                        jan, barcode.type, image_path,
                                    )
                                    return jan
                    except Exception:
                        pass
            
            if not ImageService.is_barcode_reader_available():
                logger.warning(
                    "No barcode backend is available (zxing-cpp / pyzxing / pyzbar)."
                )
            
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
        known_jans: Optional[Set[str]] = None,
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
            known_jans: 仕入DBのJAN集合。照合と12桁UPC変換に使う
        
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
                # JAN不明のキャッシュはバーコード再読取を妨げるので使わない
                cached_data = file_cache.get(path_str) if file_cache else None
                if cached_data:
                    cached_mtime = cached_data.get("mtime")
                    mtime_ok = cached_mtime is None or abs(current_mtime - cached_mtime) < 0.001
                    cached_record = cached_data.get("record") if mtime_ok else None
                    cached_jan = getattr(cached_record, "jan_candidate", None) if cached_record else None
                    has_jan = bool(cached_jan) and str(cached_jan) not in ("unknown", "None") and str(cached_jan).replace(".0", "").isdigit()
                    if cached_record and (has_jan or skip_barcode_reading):
                        records.append(cached_record)
                        continue

                # キャッシュミスまたは JAN 未確定：通常スキャン
                # EXIFから撮影日時を取得（スキップ可能）
                capture_dt = None
                if not skip_exif:
                    capture_dt = self.get_exif_datetime(path_str)
                
                # JANコードを抽出（優先順位: 仕入DB照合つきファイル名 > 画像内のバーコード）
                jan_candidate = self.extract_jan_from_text(img_path.name, known_jans)
                
                # バーコード読み取りが有効な場合のみ画像内のバーコードを読み取る（低速）
                if not jan_candidate and not skip_barcode_reading:
                    if self.is_barcode_reader_available():
                        jan_candidate = self.read_barcode_from_image(
                            path_str, known_jans=known_jans
                        )
                
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

    @staticmethod
    def resolve_auto_correct_preset(preset_id: Optional[str]) -> AutoCorrectPreset:
        key = (preset_id or DEFAULT_AUTO_CORRECT_PRESET).strip().lower()
        return AUTO_CORRECT_PRESETS.get(key, AUTO_CORRECT_PRESETS[DEFAULT_AUTO_CORRECT_PRESET])

    @staticmethod
    def apply_product_auto_correct(
        img: Image.Image,
        preset_id: str = DEFAULT_AUTO_CORRECT_PRESET,
    ) -> Image.Image:
        """
        出品向けの簡易自動補正（AIなし: 明るさ・コントラスト・シャープ）。
        """
        preset = ImageService.resolve_auto_correct_preset(preset_id)
        if img.mode not in ("RGB", "L"):
            work = img.convert("RGB")
        else:
            work = img.convert("RGB") if img.mode == "L" else img.copy()

        work = ImageEnhance.Contrast(work).enhance(preset.contrast)
        work = ImageEnhance.Brightness(work).enhance(preset.brightness)
        work = ImageEnhance.Sharpness(work).enhance(preset.sharpness)
        return work

    def load_image_for_auto_correct_preview(
        self,
        image_path: str,
        preset_id: str = DEFAULT_AUTO_CORRECT_PRESET,
    ) -> Image.Image:
        """EXIF補正後にプリセットを適用したプレビュー用画像を返す。"""
        with Image.open(image_path) as src:
            img = ImageOps.exif_transpose(src)
            return self.apply_product_auto_correct(img, preset_id)

    @staticmethod
    def _save_format_for_path(dest_path: str, lightweight: bool) -> tuple[str, dict]:
        """保存先パスから PIL 保存形式とオプションを決める。"""
        ext = Path(dest_path).suffix.lower()
        if lightweight or ext in (".jpg", ".jpeg"):
            return "JPEG", {"quality": 85 if lightweight else 92, "optimize": True}
        if ext == ".png":
            return "PNG", {}
        if ext == ".webp":
            return "WEBP", {"quality": 90}
        return "JPEG", {"quality": 92, "optimize": True}

    def rename_image_file(
        self,
        source_path: str,
        dest_path: str,
        *,
        lightweight: bool = False,
        auto_correct: bool = False,
        auto_correct_preset: str = DEFAULT_AUTO_CORRECT_PRESET,
        max_long_edge: int = 1600,
        jpeg_quality: int = 85,
    ) -> None:
        """
        リネーム（必要なら自動補正・軽量化）を行う。
        lightweight / auto_correct がともに False のときは os.rename のみ。
        """
        source_path = os.path.normpath(source_path)
        dest_path = os.path.normpath(dest_path)
        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"source not found: {source_path}")

        if not lightweight and not auto_correct:
            if os.path.normcase(os.path.abspath(source_path)) != os.path.normcase(
                os.path.abspath(dest_path)
            ):
                os.rename(source_path, dest_path)
            return

        size_before = os.path.getsize(source_path)
        dest_dir = os.path.dirname(os.path.abspath(dest_path))
        if not dest_dir:
            dest_dir = os.path.abspath(os.path.curdir)

        tmp_path: Optional[str] = None
        try:
            with Image.open(source_path) as src:
                img = ImageOps.exif_transpose(src)
                if auto_correct:
                    img = self.apply_product_auto_correct(img, auto_correct_preset)
                if lightweight:
                    img = img.convert("RGB")
                    w, h = img.size
                    long_edge = max(w, h)
                    if long_edge > max_long_edge:
                        scale = max_long_edge / float(long_edge)
                        new_w = max(1, int(round(w * scale)))
                        new_h = max(1, int(round(h * scale)))
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    save_format = "JPEG"
                    save_kwargs = {"quality": jpeg_quality, "optimize": True}
                else:
                    if img.mode in ("RGBA", "LA", "P"):
                        if img.mode == "P" and "transparency" in img.info:
                            img = img.convert("RGBA")
                        elif img.mode == "P":
                            img = img.convert("RGB")
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    save_format, save_kwargs = self._save_format_for_path(dest_path, lightweight=False)

                fd, tmp_path = tempfile.mkstemp(
                    suffix=".tmp",
                    prefix="hir_rename_",
                    dir=dest_dir,
                )
                os.close(fd)
                img.save(tmp_path, save_format, **save_kwargs)

            size_after = os.path.getsize(tmp_path)
            if size_after == 0:
                raise ValueError("rename image output is empty")

            with Image.open(tmp_path) as chk:
                chk.load()

            os.replace(tmp_path, dest_path)
            tmp_path = None

            logger.info(
                "Rename image (lightweight=%s, auto_correct=%s, preset=%s): %.3f MB -> %.3f MB %s -> %s",
                lightweight,
                auto_correct,
                auto_correct_preset if auto_correct else "-",
                size_before / (1024.0 * 1024.0),
                size_after / (1024.0 * 1024.0),
                source_path,
                dest_path,
            )

            if os.path.normcase(os.path.abspath(source_path)) != os.path.normcase(
                os.path.abspath(dest_path)
            ):
                try:
                    os.remove(source_path)
                except OSError as exc:
                    logger.warning("Could not remove source after rename: %s (%s)", source_path, exc)
        except Exception:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def lightweight_jpeg_rename(
        self,
        source_path: str,
        dest_path: str,
        max_long_edge: int = 1600,
        jpeg_quality: int = 85,
    ) -> None:
        """
        リネーム先パスへ JPEG を書き出す（軽量化・EXIF なし）。
        一時ファイルに保存し検証後、os.replace で dest に反映する。
        source と dest が異なるパスなら、成功後に source を削除する。
        """
        self.rename_image_file(
            source_path,
            dest_path,
            lightweight=True,
            auto_correct=False,
            max_long_edge=max_long_edge,
            jpeg_quality=jpeg_quality,
        )
    
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
    def barcode_backend_names() -> List[str]:
        """実際に使えるバーコード読取バックエンド名"""
        names: List[str] = []
        if _try_import_zxingcpp():
            names.append("zxing-cpp")
        if _try_import_pyzxing():
            names.append("pyzxing")
        if _try_import_pyzbar():
            names.append("pyzbar")
        return names

    @staticmethod
    def is_barcode_reader_available() -> bool:
        """バーコードリーダー（zxing-cpp / pyzxing / pyzbar）が利用可能か"""
        return bool(ImageService.barcode_backend_names())
    
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

