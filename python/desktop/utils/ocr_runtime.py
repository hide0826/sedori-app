#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR実行環境（Tesseract本体・日本語データ・画像収集）

ミニPC移植後も、設定パスが空／前PCのまま／本体未導入でも動くようにする。
Qt に依存しないので pytest で単体確認できる。
"""
from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

RECEIPT_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}

TESSERACT_CANDIDATES = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    Path(r"C:\Tesseract-OCR\tesseract.exe"),
)

LOCAL_TESSDATA_DIR = Path(r"C:\HIRIO\tools\tessdata")
JPN_FAST_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/jpn.traineddata"
JPN_VERT_FAST_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/jpn_vert.traineddata"

# ミニPCのRAM（12GB前後）でも安全な長辺。スマホ原寸（4000px超）をそのまま渡さない。
OCR_MAX_IMAGE_SIDE = 1920


def _is_hidden_or_junk(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("._") or name.startswith("."):
        return True
    if name in {"thumbs.db", "desktop.ini"}:
        return True
    return False


def collect_receipt_image_paths(
    folder: str | Path,
    *,
    recursive_if_empty: bool = True,
    max_depth: int = 3,
    max_files: int = 400,
) -> List[str]:
    """
    フォルダから OCR 対象画像を集める。

    まず直下だけ見る。0件ならサブフォルダを深さ制限つきで探す
    （せどり総合のルートを選んだときに商品写真を数千枚拾わないため）。
    """
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        return []

    top = _collect_images_in_dir(root)
    if top or not recursive_if_empty:
        return top[:max_files]

    found: List[str] = []
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            path = current / name
            if _is_image_file(path):
                found.append(str(path))
                if len(found) >= max_files:
                    found.sort()
                    return found
    found.sort()
    return found


def _collect_images_in_dir(folder: Path) -> List[str]:
    paths: List[str] = []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for entry in entries:
        if _is_image_file(entry):
            paths.append(str(entry))
    return paths


def _is_image_file(path: Path) -> bool:
    if not path.is_file() or _is_hidden_or_junk(path):
        return False
    return path.suffix.lower() in RECEIPT_IMAGE_SUFFIXES


def discover_tesseract_cmd(explicit: Optional[str] = None) -> Optional[str]:
    """設定値 → PATH → よくある Windows インストール先の順で tesseract.exe を探す。"""
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)

    which = shutil.which("tesseract")
    if which:
        which_path = Path(which)
        if which_path.is_file():
            return str(which_path)

    for candidate in TESSERACT_CANDIDATES:
        if candidate and candidate.is_file():
            return str(candidate)
    return None


def discover_tessdata_dir(
    explicit: Optional[str] = None,
    tesseract_cmd: Optional[str] = None,
) -> Optional[str]:
    """jpn.traineddata がある tessdata フォルダを優先して返す。"""
    candidates: List[Path] = []
    if tesseract_cmd:
        candidates.append(Path(tesseract_cmd).parent / "tessdata")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(r"C:\Program Files\Tesseract-OCR\tessdata"))
    candidates.append(Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"))
    candidates.append(LOCAL_TESSDATA_DIR)

    seen = set()
    japanese_hit: Optional[Path] = None
    fallback: Optional[Path] = None
    for cand in candidates:
        if not cand:
            continue
        resolved = cand.resolve() if cand.exists() else cand
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if not cand.is_dir():
            continue
        if tessdata_has_japanese(cand):
            japanese_hit = cand
            break
        if fallback is None:
            fallback = cand
    chosen = japanese_hit or fallback
    return str(chosen) if chosen else None


def tessdata_has_japanese(tessdata_dir: str | Path) -> bool:
    return (Path(tessdata_dir) / "jpn.traineddata").is_file()


def tessdata_prefix_for_env(tessdata_dir: str | Path) -> str:
    """
    Windows の UB-Mannheim Tesseract は TESSDATA_PREFIX を
    tessdata フォルダ自体（jpn.traineddata がある場所）として扱う。
    Linux 公式ドキュメントの「親フォルダ」指定だと、このPCでは言語ファイルを読めない。
    """
    path = Path(tessdata_dir)
    if path.name.lower() == "tessdata":
        return str(path)
    nested = path / "tessdata"
    if nested.is_dir():
        return str(nested)
    return str(path)


def tesseract_lang_string(tessdata_dir: Optional[str]) -> str:
    if tessdata_dir and tessdata_has_japanese(tessdata_dir):
        return "jpn+eng"
    return "eng"


def describe_ocr_readiness(
    tesseract_cmd: Optional[str],
    tessdata_dir: Optional[str],
    *,
    pytesseract_imported: bool,
) -> Tuple[bool, str]:
    """全件OCRを始めてよいか。不可なら理由を日本語で返す。"""
    if not pytesseract_imported:
        return False, (
            "Python パッケージ pytesseract が入っていません。\n"
            "仮想環境で pip install pytesseract を実行してください。"
        )
    if not tesseract_cmd or not Path(tesseract_cmd).is_file():
        return False, (
            "Tesseract OCR 本体（tesseract.exe）が見つかりません。\n"
            "ミニPCへ移植しただけでは入りません。\n"
            "設定 → OCR で tesseract.exe を指定するか、\n"
            "UB-Mannheim の Tesseract-OCR をインストールしてください。"
        )
    if not tessdata_dir or not Path(tessdata_dir).is_dir():
        return False, (
            f"tessdata フォルダが見つかりません。\nTesseract: {tesseract_cmd}"
        )
    if not tessdata_has_japanese(tessdata_dir):
        return False, (
            "日本語 OCR データ（jpn.traineddata）がありません。\n"
            f"場所: {tessdata_dir}\n"
            "英語しか読めないため、レシート全件OCRは開始しません。"
        )
    return True, f"Tesseract: {tesseract_cmd}\n言語: jpn+eng\ntessdata: {tessdata_dir}"


def ensure_japanese_tessdata(tessdata_dir: str | Path, timeout: int = 60) -> bool:
    """jpn.traineddata が無ければ tessdata_fast から取得する。"""
    dest_dir = Path(tessdata_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    jpn = dest_dir / "jpn.traineddata"
    if jpn.is_file() and jpn.stat().st_size > 100_000:
        return True
    try:
        urllib.request.urlretrieve(JPN_FAST_URL, jpn)
    except Exception:
        return False
    vert = dest_dir / "jpn_vert.traineddata"
    if not vert.is_file():
        try:
            urllib.request.urlretrieve(JPN_VERT_FAST_URL, vert)
        except Exception:
            pass
    return jpn.is_file() and jpn.stat().st_size > 100_000


def limit_image_side(size: Tuple[int, int], max_side: int = OCR_MAX_IMAGE_SIDE) -> Tuple[int, int]:
    """縮小後の幅・高さを返す（拡大はしない）。"""
    width, height = size
    longest = max(width, height)
    if longest <= max_side or longest <= 0:
        return width, height
    scale = max_side / float(longest)
    return max(1, int(width * scale)), max(1, int(height * scale))


def register_heif_opener() -> bool:
    """iPhone の HEIC を Pillow で開けるようにする。"""
    try:
        from pillow_heif import register_heif_opener as _register

        _register()
        return True
    except Exception:
        return False
