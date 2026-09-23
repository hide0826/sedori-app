#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ仕入証憑のローカル保存・GCS パス・フリマ判定。"""
from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

EVIDENCE_GCS_PREFIX = "purchase_evidence/"

EVIDENCE_SLOT_SPECS = (
    ("listing", "01_listing.png", "商品ページ（写真・価格）"),
    ("listing_desc", "02_listing_desc.png", "商品ページ（説明文）"),
    ("transaction", "03_transaction.png", "取引画面"),
)

EVIDENCE_FOLDER_COL = "証憑フォルダ"
EVIDENCE_IMAGE_COLS = ("証憑画像1", "証憑画像2", "証憑画像3")
EVIDENCE_URL_COLS = ("証憑URL1", "証憑URL2", "証憑URL3")
EVIDENCE_HIDDEN_COLUMNS = (
    EVIDENCE_FOLDER_COL,
    *EVIDENCE_IMAGE_COLS,
    *EVIDENCE_URL_COLS,
)

PURCHASE_CHANNEL_COL = "仕入チャネル"

FLEA_DETAIL_COLUMNS = (
    PURCHASE_CHANNEL_COL,
    "プラットフォーム",
    "取引ID",
    "ユーザー名",
    "出品URL",
    "伝票番号",
    "受取都道府県",
)

PURCHASE_DB_FLEA_COLUMNS = FLEA_DETAIL_COLUMNS + EVIDENCE_HIDDEN_COLUMNS

_FALLBACK_FLEA_NAMES = frozenset({
    "メルカリ",
    "mercari",
    "ヤフオク",
    "ヤフフリ",
    "ラクマ",
    "paypayフリマ",
    "ペイペイフリマ",
})

_INVALID_FOLDER_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_ASIN_RE = re.compile(r"^[A-Z0-9]{8,12}$", re.IGNORECASE)

UploadFn = Callable[[str, str], str]


@dataclass
class EvidenceSaveResult:
    folder_path: str = ""
    folder_name: str = ""
    local_paths: List[str] = field(default_factory=list)
    gcs_urls: List[str] = field(default_factory=list)
    gcs_error: str = ""


def is_flea_purchase_source(
    store_value: Optional[str],
    flea_markets: Optional[Sequence[Dict[str, Any]]] = None,
) -> bool:
    """仕入先セルがフリマ（メルカリ等）かどうか。"""
    return resolve_flea_market(store_value, flea_markets) is not None or _matches_fallback_name(
        store_value
    )


_CHANNEL_CANONICAL = (
    ("メルカリ", ("メルカリ", "mercari")),
    ("ヤフオク", ("ヤフオク", "yahooオークション", "auctions.yahoo")),
    ("ヤフショ", ("ヤフショ", "yahooショッピング", "ヤフーショッピング")),
    ("楽天", ("楽天", "rakuten")),
    ("Amazon", ("amazon", "アマゾン")),
    ("ラクマ", ("ラクマ", "rakuma")),
    ("PayPayフリマ", ("paypayフリマ", "ペイペイフリマ", "paypayfleamarket")),
)

_FLEA_ROW_SOURCE_KEYS = (
    PURCHASE_CHANNEL_COL,
    "仕入先",
    "店舗コード",
    "store_code",
    "プラットフォーム",
    "source_channel",
)

_MERCARI_ITEM_ID_RE = re.compile(r"^m\d{8,16}$", re.IGNORECASE)


def is_flea_purchase_row(
    record: Optional[Dict[str, Any]],
    flea_markets: Optional[Sequence[Dict[str, Any]]] = None,
) -> bool:
    """仕入行がフリマ仕入かどうか（仕入先・URL・取引IDから判定）。"""
    row = record or {}
    for key in _FLEA_ROW_SOURCE_KEYS:
        if is_flea_purchase_source(str(row.get(key) or ""), flea_markets):
            return True
    listing_url = str(row.get("出品URL") or row.get("listing_url") or "").strip().lower()
    if "mercari.com" in listing_url or "fril.jp" in listing_url or "rakuma" in listing_url:
        return True
    if "auctions.yahoo" in listing_url or "paypayfleamarket" in listing_url:
        return True
    item_id = str(row.get("取引ID") or row.get("transaction_id") or "").strip()
    if _MERCARI_ITEM_ID_RE.match(item_id):
        return True
    comment = str(row.get("コメント") or row.get("comment") or "")
    if "[フリマ:" in comment or "フリマ:メルカリ" in comment:
        return True
    return False


def normalize_purchase_channel(value: Optional[str]) -> str:
    """仕入チャネル名を表示用の正式名に揃える。不明なら元の文字列。"""
    raw = str(value or "").strip()
    if not raw or raw.lower() in ("nan", "none"):
        return ""
    tl = raw.lower()
    tu = raw.upper()
    code_map = {"MRC": "メルカリ", "YAH": "ヤフオク", "RAK": "ラクマ", "PPF": "PayPayフリマ"}
    if tu in code_map:
        return code_map[tu]
    for canon, aliases in _CHANNEL_CANONICAL:
        if tl == canon.lower():
            return canon
        for alias in aliases:
            if len(alias) <= 3:
                if tl == alias:
                    return canon
            elif alias in tl:
                return canon
    return raw


def purchase_channel_from_supplier(record: Optional[Dict[str, Any]]) -> str:
    """仕入先（CSV見出しの仕入れ先を含む）だけから仕入チャネルを取る。コメントは見ない。"""
    row = record or {}
    for key in ("仕入先", "仕入れ先"):
        found = normalize_purchase_channel(str(row.get(key) or ""))
        if found:
            return found
    return ""


def infer_purchase_channel(record: Optional[Dict[str, Any]]) -> str:
    """行データから仕入チャネル（メルカリ・楽天等）を推定する。"""
    row = record or {}
    for key in (PURCHASE_CHANNEL_COL, "プラットフォーム", "仕入先", "コメント"):
        found = normalize_purchase_channel(str(row.get(key) or ""))
        if found:
            return found
    listing_url = str(row.get("出品URL") or row.get("listing_url") or "").strip().lower()
    if "mercari.com" in listing_url:
        return "メルカリ"
    if "auctions.yahoo" in listing_url:
        return "ヤフオク"
    if "shopping.yahoo" in listing_url:
        return "ヤフショ"
    if "rakuten.co.jp" in listing_url:
        return "楽天"
    if "amazon.co.jp" in listing_url or "amazon.com" in listing_url:
        return "Amazon"
    if "fril.jp" in listing_url or "rakuma" in listing_url:
        return "ラクマ"
    if "paypayfleamarket" in listing_url:
        return "PayPayフリマ"
    item_id = str(row.get("取引ID") or row.get("transaction_id") or "").strip()
    if _MERCARI_ITEM_ID_RE.match(item_id):
        return "メルカリ"
    return ""


def resolve_flea_market(
    store_value: Optional[str],
    flea_markets: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """仕入先文字列から flea_markets の1行を特定する。"""
    raw = (store_value or "").strip()
    if not raw:
        return None
    candidates = _source_lookup_tokens(raw)
    markets = list(flea_markets or [])
    for token in candidates:
        tl = token.lower()
        tu = token.upper()
        for m in markets:
            name = str(m.get("platform_name") or "").strip()
            code = str(m.get("platform_code") or "").strip()
            prefix = str(m.get("code_prefix") or "").strip()
            if name and (name == token or name.lower() == tl):
                return m
            if code and code.upper() == tu:
                return m
            if prefix and prefix.upper() == tu:
                return m
    return None


def channel_code_for_source(
    store_value: Optional[str],
    flea_markets: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """フォルダ名用の短いチャネルコード（メルカリなら MRC）。"""
    market = resolve_flea_market(store_value, flea_markets)
    if market:
        token = (
            str(market.get("code_prefix") or "").strip()
            or str(market.get("platform_code") or "").strip()
        )
        if token:
            return sanitize_folder_token(token.upper())
    tokens = _source_lookup_tokens(store_value)
    if tokens:
        first = tokens[0]
        if first.lower() in ("メルカリ", "mercari"):
            return "MRC"
        compact = sanitize_folder_token(first)
        if compact:
            return compact[:8].upper()
    return "FLEA"


def build_evidence_folder_name(
    purchase_datetime: Optional[str],
    channel_code: str,
    asin: Optional[str],
) -> str:
    """YYYY-MM-DD_チャネル_ASIN 形式のフォルダ名。"""
    date_part = _date_part_from_purchase_datetime(purchase_datetime) or datetime.now().strftime(
        "%Y-%m-%d"
    )
    channel = sanitize_folder_token(channel_code or "FLEA") or "FLEA"
    asin_token = _asin_token(asin)
    return f"{date_part}_{channel}_{asin_token}"


def sanitize_folder_token(value: str) -> str:
    """Windows 禁則文字を除いたフォルダ名トークン。"""
    cleaned = _INVALID_FOLDER_CHARS_RE.sub("_", str(value or "").strip())
    cleaned = cleaned.replace(" ", "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned


def resolve_or_create_evidence_dir(root: str, folder_name: str) -> Path:
    """親フォルダ配下に証憑フォルダを作る。既存があれば再利用。"""
    if not str(root or "").strip():
        raise ValueError("証憑の保存先フォルダが未設定です。")
    safe_name = sanitize_folder_token(folder_name) or "evidence"
    dest = Path(root) / safe_name
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def save_slot_images(
    dest_dir: Path,
    slot_sources: Sequence[Optional[str]],
) -> List[str]:
    """3スロットの画像を 01/02/03 ファイル名で保存し、保存できたパスを返す。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = ["", "", ""]
    for i, spec in enumerate(EVIDENCE_SLOT_SPECS):
        filename = spec[1]
        src = slot_sources[i] if i < len(slot_sources) else None
        if not src:
            existing = dest_dir / filename
            if existing.is_file():
                saved[i] = str(existing.resolve())
            continue
        src_path = Path(src)
        if not src_path.is_file():
            continue
        target = dest_dir / filename
        if src_path.resolve() != target.resolve():
            shutil.copy2(src_path, target)
        saved[i] = str(target.resolve())
    return saved


def gcs_blob_name(folder_name: str, filename: str) -> str:
    return f"{EVIDENCE_GCS_PREFIX}{folder_name}/{filename}"


def upload_saved_images_to_gcs(
    folder_name: str,
    local_paths: Sequence[str],
    upload_fn: Optional[UploadFn] = None,
) -> tuple:
    """ローカル保存済み画像を GCS に上げる。失敗しても例外は外に出さない。"""
    urls: List[str] = ["", "", ""]
    errors: List[str] = []
    fn = upload_fn or _default_gcs_upload
    for i, local in enumerate(local_paths):
        if not local:
            continue
        filename = EVIDENCE_SLOT_SPECS[i][1] if i < len(EVIDENCE_SLOT_SPECS) else Path(local).name
        blob = gcs_blob_name(folder_name, filename)
        try:
            urls[i] = fn(local, blob) or ""
        except Exception as exc:
            logger.warning("Evidence GCS upload failed for %s: %s", local, exc)
            errors.append(f"{filename}: {exc}")
    return urls, "; ".join(errors)


def save_evidence_bundle(
    *,
    root: str,
    purchase_datetime: Optional[str],
    store_value: Optional[str],
    asin: Optional[str],
    slot_sources: Sequence[Optional[str]],
    flea_markets: Optional[Sequence[Dict[str, Any]]] = None,
    upload_fn: Optional[UploadFn] = None,
    upload_to_gcs: bool = True,
) -> EvidenceSaveResult:
    """フォルダ作成 → ローカル保存 → 任意で GCS アップロード。"""
    channel = channel_code_for_source(store_value, flea_markets)
    folder_name = build_evidence_folder_name(purchase_datetime, channel, asin)
    dest = resolve_or_create_evidence_dir(root, folder_name)
    local_paths = save_slot_images(dest, slot_sources)
    result = EvidenceSaveResult(
        folder_path=str(dest.resolve()),
        folder_name=folder_name,
        local_paths=local_paths,
        gcs_urls=["", "", ""],
    )
    if upload_to_gcs and any(local_paths):
        urls, err = upload_saved_images_to_gcs(folder_name, local_paths, upload_fn=upload_fn)
        result.gcs_urls = urls
        result.gcs_error = err
    return result


def transaction_id_match_key(record: Dict[str, Any]) -> Optional[str]:
    """仕入DBマージ用。取引IDがあれば同一レコードとみなす。"""
    tx = str(record.get("取引ID") or record.get("transaction_id") or "").strip()
    if not tx or tx.lower() == "nan":
        return None
    return f"TX:{tx}"


def record_fields_from_save(result: EvidenceSaveResult) -> Dict[str, str]:
    """仕入行へ書き戻す証憑列。"""
    fields = {EVIDENCE_FOLDER_COL: result.folder_path}
    for col, path in zip(EVIDENCE_IMAGE_COLS, result.local_paths or ["", "", ""]):
        fields[col] = path or ""
    for col, url in zip(EVIDENCE_URL_COLS, result.gcs_urls or ["", "", ""]):
        fields[col] = url or ""
    return fields


def _source_lookup_tokens(store_value: Optional[str]) -> List[str]:
    raw = (store_value or "").strip()
    if not raw:
        return []
    tokens = [raw]
    if ":" in raw:
        tokens.append(raw.split(":", 1)[-1].strip())
        tokens.append(raw.split(":", 1)[0].strip())
    return [t for t in tokens if t]


def _matches_fallback_name(store_value: Optional[str]) -> bool:
    names = {n.lower() for n in _FALLBACK_FLEA_NAMES}
    for token in _source_lookup_tokens(store_value):
        tl = token.lower()
        tu = token.upper()
        if tl in names:
            return True
        if tu in {"MRC", "YAH", "RAK", "PPF"}:
            return True
        if any(name in tl for name in names):
            return True
    return False


def _date_part_from_purchase_datetime(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "nan":
        return ""
    raw = raw.replace("/", "-")
    date_part = raw.split()[0] if " " in raw else raw
    parts = date_part.split("-")
    if len(parts) >= 3:
        try:
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return ""
    return ""


def _asin_token(asin: Optional[str]) -> str:
    raw = sanitize_folder_token(str(asin or "").strip())
    if raw and _ASIN_RE.match(raw):
        return raw.upper()
    if raw:
        return raw[:12].upper() or "NOASIN"
    return "NOASIN"


_gcs_upload_fn: Optional[UploadFn] = None


def _resolve_gcs_uploader_path() -> Optional[Path]:
    """python/utils/gcs_uploader.py を探す（desktop/utils とは別物）。"""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "utils" / "gcs_uploader.py",  # python/utils
        here.parents[1].parent / "utils" / "gcs_uploader.py",
        Path.cwd() / "python" / "utils" / "gcs_uploader.py",
        Path.cwd() / "utils" / "gcs_uploader.py",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _load_gcs_upload_fn() -> UploadFn:
    """デスクトップ起動時でも python/utils/gcs_uploader.py を直接読む。"""
    global _gcs_upload_fn
    if _gcs_upload_fn is not None:
        return _gcs_upload_fn
    uploader_path = _resolve_gcs_uploader_path()
    if uploader_path is not None:
        spec = importlib.util.spec_from_file_location("hirio_gcs_uploader", str(uploader_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"GCSアップローダーを読み込めません: {uploader_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, "upload_image_to_gcs", None)
        if not callable(fn):
            raise ImportError(f"upload_image_to_gcs が見つかりません: {uploader_path}")
        _gcs_upload_fn = fn
        return fn
    try:
        from utils.gcs_uploader import upload_image_to_gcs as fn  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "GCSアップローダー (python/utils/gcs_uploader.py) が見つかりません。"
        ) from exc
    _gcs_upload_fn = fn
    return fn


def _default_gcs_upload(local_path: str, blob_name: str) -> str:
    fn = _load_gcs_upload_fn()
    return fn(local_path, destination_blob_name=blob_name)
