# -*- coding: utf-8 -*-
"""ネット仕入用の日付箱（仕入CSV / 商品画像 / 証憑スクショ）を作る。"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

CSV_DIR_NAME = "仕入CSV"
PRODUCT_DIR_NAME = "商品画像"
EVIDENCE_DIR_NAME = "証憑スクショ"
PHOTO_CANDIDATES_FILE = "photo_candidates.json"
ONLINE_ROUTE_CODE = "NET"
ONLINE_BOX_KIND = "online"

ONLINE_BOX_SUBDIRS: Sequence[str] = (
    CSV_DIR_NAME,
    PRODUCT_DIR_NAME,
    EVIDENCE_DIR_NAME,
)

# ユーザー環境の実フォルダ名は「ネット仕入れリスト」（「れ」あり）。
# 表記ゆれにも対応する。
DEFAULT_ONLINE_ROOT_CANDIDATES: Sequence[Path] = (
    Path(r"D:\せどり総合\ネット仕入れリスト"),
    Path(r"D:\せどり総合\ネット仕入リスト"),
)

_UNSAFE_FOLDER_CHARS = '\\/:*?"<>|'


@dataclass(frozen=True)
class OnlineBoxResult:
    box_dir: Path
    evidence_dir: Path
    csv_dir: Path
    product_dir: Path
    created_box: bool
    created_subdirs: List[str]
    web_id: str = ""
    route_json: Optional[Path] = None


def sanitize_folder_label(label: str) -> str:
    """フォルダ名に使えない文字を _ に置換する。"""
    text = (label or "").strip() or "フリマ"
    return "".join("_" if ch in _UNSAFE_FOLDER_CHARS else ch for ch in text)


def format_box_date(value: Optional[Union[date, datetime, str]] = None) -> str:
    """箱名用の YYYYMMDD を返す。"""
    if value is None:
        return date.today().strftime("%Y%m%d")
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return date.today().strftime("%Y%m%d")


def box_date_iso(value: Optional[Union[date, datetime, str]] = None) -> str:
    """YYYY-MM-DD。"""
    ymd = format_box_date(value)
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def build_online_box_name(
    label: str = "フリマ",
    box_date: Optional[Union[date, datetime, str]] = None,
) -> str:
    """例: フリマ20261001"""
    return f"{sanitize_folder_label(label)}{format_box_date(box_date)}"


def resolve_default_online_root(
    candidates: Optional[Iterable[Path]] = None,
) -> Optional[Path]:
    """存在するデフォルト親フォルダを返す。無ければ None。"""
    for path in candidates or DEFAULT_ONLINE_ROOT_CANDIDATES:
        try:
            if Path(path).is_dir():
                return Path(path)
        except OSError:
            continue
    return None


def _ensure_route_web_importable() -> None:
    """desktop/services から route_web を import できるようにする。"""
    desktop_dir = Path(__file__).resolve().parents[1]
    python_dir = desktop_dir.parent
    for path in (str(python_dir), str(desktop_dir)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def create_online_purchase_box(
    base_dir: Union[str, Path],
    *,
    label: str = "フリマ",
    box_date: Optional[Union[date, datetime, str]] = None,
    box_name: Optional[str] = None,
    register_web: bool = True,
) -> OnlineBoxResult:
    """
    親フォルダ配下に日付箱とサブフォルダを作る。

    既にあっても不足サブだけ追加する（exist_ok）。
    register_web=True のとき route.json を書き route_web に登録する。
    """
    root = Path(base_dir)
    if not str(root).strip():
        raise ValueError("親フォルダが空です")

    if box_name and str(box_name).strip():
        name = "".join(
            "_" if ch in _UNSAFE_FOLDER_CHARS else ch for ch in str(box_name).strip()
        )
        if not name:
            name = build_online_box_name(label=label, box_date=box_date)
    else:
        name = build_online_box_name(label=label, box_date=box_date)

    box_dir = root / name
    created_box = not box_dir.exists()
    box_dir.mkdir(parents=True, exist_ok=True)

    created_subdirs: List[str] = []
    sub_paths = {}
    for sub in ONLINE_BOX_SUBDIRS:
        sub_dir = box_dir / sub
        if not sub_dir.exists():
            created_subdirs.append(sub)
        sub_dir.mkdir(exist_ok=True)
        sub_paths[sub] = sub_dir

    web_id = ""
    route_json: Optional[Path] = None
    if register_web:
        web_id, route_json = ensure_online_route_registration(
            box_dir,
            box_date=box_date or format_box_date(name[-8:] if len(name) >= 8 else None),
            route_name=name,
        )

    return OnlineBoxResult(
        box_dir=box_dir,
        evidence_dir=sub_paths[EVIDENCE_DIR_NAME],
        csv_dir=sub_paths[CSV_DIR_NAME],
        product_dir=sub_paths[PRODUCT_DIR_NAME],
        created_box=created_box,
        created_subdirs=created_subdirs,
        web_id=web_id,
        route_json=route_json,
    )


def ensure_online_route_registration(
    box_dir: Union[str, Path],
    *,
    box_date: Optional[Union[date, datetime, str]] = None,
    route_name: Optional[str] = None,
) -> tuple[str, Path]:
    """ネット箱に route.json を書き、route_web の index に登録する。"""
    _ensure_route_web_importable()
    from route_web.registry import make_web_id, register_route, route_json_path
    from route_web.schema import build_route_document, stamp_updated

    folder = Path(box_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = route_name or folder.name
    ymd = format_box_date(box_date)
    if box_date is None:
        # 箱名末尾の YYYYMMDD を優先
        digits = "".join(ch for ch in name if ch.isdigit())
        if len(digits) >= 8:
            ymd = digits[-8:]
    iso = box_date_iso(ymd)
    web_id = make_web_id(ymd, name)

    existing: Dict[str, Any] = {}
    path = route_json_path(folder)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except (OSError, json.JSONDecodeError):
            existing = {}

    doc = build_route_document(
        web_id=web_id,
        folder_path=str(folder),
        route_date=iso,
        route_code=ONLINE_ROUTE_CODE,
        route_name=name,
        stores=[],
        notes=str(existing.get("notes") or ""),
        box_kind=ONLINE_BOX_KIND,
    )
    if isinstance(existing.get("product_files"), list):
        doc["product_files"] = existing["product_files"]
    if isinstance(existing.get("no_image_products"), list):
        doc["no_image_products"] = existing["no_image_products"]
    if isinstance(existing.get("photo_candidates"), list):
        doc["photo_candidates"] = existing["photo_candidates"]
    doc = stamp_updated(doc)

    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    register_route(web_id, str(folder), route_name=name, route_date=iso)
    return web_id, path


def _cell(record: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return ""


_SKU_YMD_RE = re.compile(r"^(\d{8})(?:-|_|$)")
_ASIN_EXCEL_RE = re.compile(r'^="?([A-Za-z0-9]+)"?$')


def extract_ymd_from_text(value: Any) -> str:
    """文字列から箱用 YYYYMMDD を取り出す。無ければ空文字。"""
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    # Excel 由来の ="20261113-..." や ="B0..." を剥がす
    if text.startswith("="):
        text = text.lstrip("=").strip().strip('"').strip("'")
    match = _SKU_YMD_RE.match(text)
    if match:
        return match.group(1)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        ymd = digits[:8]
        try:
            datetime.strptime(ymd, "%Y%m%d")
            return ymd
        except ValueError:
            return ""
    return ""


def extract_record_box_ymd(record: Dict[str, Any]) -> str:
    """
    仕入1行から紐付け先の箱日付 YYYYMMDD を決める。

    優先順: SKU先頭8桁 → 仕入れ日系の列。
    """
    if not isinstance(record, dict):
        return ""
    sku = _cell(record, "SKU", "sku")
    ymd = extract_ymd_from_text(sku)
    if ymd:
        return ymd
    for key in (
        "仕入れ日",
        "仕入日",
        "purchase_date",
        "purchased_at",
        "purchase_datetime",
    ):
        ymd = extract_ymd_from_text(_cell(record, key))
        if ymd:
            return ymd
    return ""


def extract_box_ymd_from_name(name: str) -> str:
    """フォルダ名（例: フリマ20261113）から YYYYMMDD を取る。"""
    text = str(name or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        ymd = digits[-8:]
        try:
            datetime.strptime(ymd, "%Y%m%d")
            return ymd
        except ValueError:
            return ""
    return ""


def group_records_by_box_ymd(
    records: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """箱日付ごとに仕入行を分ける。日付不明はキー ''。"""
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, dict):
            continue
        grouped[extract_record_box_ymd(record)].append(record)
    return dict(grouped)


def find_online_box_dir_for_ymd(
    base_dir: Union[str, Path],
    ymd: str,
    *,
    label: str = "フリマ",
) -> Optional[Path]:
    """親フォルダ配下で YYYYMMDD に対応する箱を探す。無ければ None。"""
    root = Path(base_dir)
    needle = format_box_date(ymd)
    if not root.is_dir() or len(needle) != 8:
        return None
    preferred = root / build_online_box_name(label=label, box_date=needle)
    if preferred.is_dir():
        return preferred
    matches: List[Path] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        if extract_box_ymd_from_name(child.name) == needle and looks_like_online_box_dir(child):
            matches.append(child)
    if not matches:
        return None
    matches.sort(key=lambda p: (0 if p.name.startswith(sanitize_folder_label(label)) else 1, p.name))
    return matches[0]


def resolve_or_create_online_box_for_ymd(
    base_dir: Union[str, Path],
    ymd: str,
    *,
    label: str = "フリマ",
    register_web: bool = True,
) -> OnlineBoxResult:
    """YYYYMMDD に対応する箱を取得（無ければ作成）。"""
    needle = format_box_date(ymd)
    existing = find_online_box_dir_for_ymd(base_dir, needle, label=label)
    if existing is not None:
        return create_online_purchase_box(
            base_dir,
            label=label,
            box_date=needle,
            box_name=existing.name,
            register_web=register_web,
        )
    return create_online_purchase_box(
        base_dir,
        label=label,
        box_date=needle,
        register_web=register_web,
    )


def normalize_listing_asin(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    match = _ASIN_EXCEL_RE.match(text)
    if match:
        text = match.group(1)
    return "".join(ch for ch in text.upper() if ch.isalnum())[:16]


# 出品CSVの condition 番号 → 短い表示名（コンディション説明文は使わない）
_LISTING_CONDITION_BY_CODE = {
    1: "中古(ほぼ新品)",
    2: "中古(非常に良い)",
    3: "中古(良い)",
    4: "中古(可)",
    5: "コレクター商品(ほぼ新品)",
    6: "コレクター商品(非常に良い)",
    7: "コレクター商品(良い)",
    8: "コレクター商品(可)",
    10: "再生品",
    11: "新品",
}


def looks_like_condition_note(value: Any) -> bool:
    """Amazon出品の長いコンディション説明かどうか。"""
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) > 40:
        return True
    if text.startswith("[") and ("動作確認" in text or "付属品" in text or "発送" in text):
        return True
    return False


def short_condition_label(value: Any = "", *, code: Any = None) -> str:
    """撮影候補用の短い Cond. 表示。説明文は捨てる。"""
    for raw in (value, code):
        text = str(raw or "").strip()
        if not text or text.lower() in ("nan", "none"):
            continue
        if looks_like_condition_note(text):
            continue
        if text.isdigit():
            mapped = _LISTING_CONDITION_BY_CODE.get(int(text))
            if mapped:
                return mapped
            return f"中古({text})"
        return text
    return ""


def _read_text_auto(path: Path) -> str:
    """UTF-8 / CP932 を自動判定して読む（出品CSVは CP932 が多い）。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # 置換文字が多い読みは失敗扱い
        if text.count("\ufffd") > 0 and enc.startswith("utf"):
            continue
        return text
    return raw.decode("cp932", errors="replace")


def _parse_csv_table(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    """CSVをヘッダ＋行dictに。見つからなければ ([], [])。"""
    try:
        raw = _read_text_auto(path)
    except OSError:
        return [], []
    rows = list(csv.reader(raw.splitlines()))
    if not rows:
        return [], []
    header_idx = None
    for i, row in enumerate(rows):
        if not row:
            continue
        head = [str(c).strip().lower() for c in row]
        head_raw = [str(c).strip() for c in row]
        # 出品CSV
        if "sku" in head and ("asin" in head or "jan" in head or "title" in head):
            header_idx = i
            break
        # アマサーチ仕入れ済み／StockList 系
        if ("asin" in head or "jan" in head) and (
            "商品名" in head_raw or "title" in head or "product_name" in head
        ):
            header_idx = i
            break
        if "asin" in head and "コンディション" in head_raw:
            header_idx = i
            break
    if header_idx is None:
        return [], []
    headers = [str(c).strip() for c in rows[header_idx]]
    out: List[Dict[str, Any]] = []
    for row in rows[header_idx + 1 :]:
        if not row or all(not str(c).strip() for c in row):
            continue
        out.append(
            {
                headers[i]: (row[i] if i < len(row) else "")
                for i in range(len(headers))
            }
        )
    return headers, out


def records_from_listing_export(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """出品CSV（listing_export / *_出品用CSV）から撮影候補用レコードを読む。"""
    return records_from_purchase_csv(path)


def records_from_purchase_csv(
    path: Union[str, Path],
    *,
    fallback_ymd: str = "",
) -> List[Dict[str, Any]]:
    """
    出品CSV／アマサーチ仕入れ済みCSV／StockList から撮影候補用レコードを読む。

    SKUが空のときは TMP-YYYYMMDD-NNN を仮付け（あとで HIRIO 仕入処理で差し替え可）。
    """
    file_path = Path(path)
    if not file_path.is_file():
        return []
    _headers, data_rows = _parse_csv_table(file_path)
    if not data_rows:
        return []
    box_ymd = format_box_date(fallback_ymd) if fallback_ymd else extract_ymd_from_text(
        file_path.stem
    )
    out: List[Dict[str, Any]] = []
    for index, data in enumerate(data_rows, start=1):
        sku = _cell(data, "SKU", "sku")
        asin = normalize_listing_asin(_cell(data, "ASIN", "asin"))
        jan = "".join(ch for ch in _cell(data, "JAN", "jan", "JANコード") if ch.isdigit())
        title = _cell(data, "title", "商品名", "product_name", "name")
        if not (sku or asin or jan or title):
            continue
        purchase_ymd = (
            extract_ymd_from_text(sku)
            or extract_ymd_from_text(_cell(data, "仕入れ日", "purchase_date", "仕入日"))
            or box_ymd
        )
        if not sku:
            ymd = purchase_ymd or format_box_date()
            sku = f"TMP-{ymd}-{index:03d}"
        condition = short_condition_label(
            _cell(data, "コンディション", "状態"),
            code=_cell(data, "condition", "condition_code"),
        )
        out.append(
            {
                "SKU": sku,
                "ASIN": asin,
                "JAN": jan,
                "商品名": title,
                "コンディション": condition,
                "仕入れ日": purchase_ymd,
            }
        )
    return out


def iter_box_csv_sources(box_dir: Union[str, Path]) -> List[Path]:
    """撮影候補の元になるCSVを新しい順で返す（出品CSV優先、次に仕入CSV）。"""
    folder = Path(box_dir)
    found: List[Path] = []
    seen = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not path.is_file():
            return
        if path.name == PHOTO_CANDIDATES_FILE:
            return
        if path.suffix.lower() != ".csv":
            return
        seen.add(resolved)
        found.append(path)

    for candidate in (
        folder / "listing_export.csv",
        *sorted(folder.glob("*_出品用CSV.csv"), reverse=True),
    ):
        _add(candidate)
    csv_dir = folder / CSV_DIR_NAME
    if csv_dir.is_dir():
        for candidate in sorted(csv_dir.glob("*.csv"), reverse=True):
            _add(candidate)
    for candidate in sorted(folder.glob("*.csv"), reverse=True):
        _add(candidate)
    return found


def _is_tmp_sku(value: Any) -> bool:
    return str(value or "").strip().upper().startswith("TMP-")


def _record_match_keys(record: Dict[str, Any]) -> List[Tuple[str, str]]:
    """同一商品判定用キー（本SKU → ASIN → JAN）。"""
    keys: List[Tuple[str, str]] = []
    sku = _cell(record, "SKU", "sku")
    if sku and not _is_tmp_sku(sku):
        keys.append(("sku", sku.upper()))
    asin = normalize_listing_asin(_cell(record, "ASIN", "asin"))
    if asin:
        keys.append(("asin", asin))
    jan = "".join(ch for ch in _cell(record, "JAN", "jan") if ch.isdigit())
    if jan:
        keys.append(("jan", jan))
    return keys


def _prefer_purchase_record(
    left: Dict[str, Any],
    right: Dict[str, Any],
) -> Dict[str, Any]:
    """重複時は本SKU付き・埋まった項目を優先して1行にまとめる。"""
    out = dict(left)
    left_sku = _cell(left, "SKU", "sku")
    right_sku = _cell(right, "SKU", "sku")
    if _is_tmp_sku(left_sku) and right_sku and not _is_tmp_sku(right_sku):
        out["SKU"] = right_sku
    for key in ("ASIN", "JAN", "商品名", "コンディション", "仕入れ日"):
        if not _cell(out, key) and _cell(right, key):
            out[key] = _cell(right, key)
    return out


def merge_purchase_records(
    batches: Iterable[Iterable[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """複数CSVの行を同一商品でまとめる（出品CSVの本SKUを優先）。"""
    merged: List[Dict[str, Any]] = []
    index_by_key: Dict[Tuple[str, str], int] = {}
    for batch in batches:
        for raw in batch:
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            hit: Optional[int] = None
            for key in _record_match_keys(record):
                if key in index_by_key:
                    hit = index_by_key[key]
                    break
            if hit is None:
                idx = len(merged)
                merged.append(record)
                for key in _record_match_keys(record):
                    index_by_key[key] = idx
                # 仮SKU同士の取り違え防止用にも索引
                sku = _cell(record, "SKU", "sku")
                if sku:
                    index_by_key[("sku", sku.upper())] = idx
                continue
            merged[hit] = _prefer_purchase_record(merged[hit], record)
            for key in _record_match_keys(merged[hit]):
                index_by_key[key] = hit
    return merged


def collect_box_csv_records(
    box_dir: Union[str, Path],
    *,
    fallback_ymd: str = "",
) -> Tuple[List[Dict[str, Any]], float, List[Path]]:
    """
    箱内の読めるCSVをすべて読み、商品行を合算する。

    Returns:
        (records, newest_mtime, used_paths)
    """
    folder = Path(box_dir)
    ymd = fallback_ymd or extract_box_ymd_from_name(folder.name) or ""
    batches: List[List[Dict[str, Any]]] = []
    used: List[Path] = []
    newest = 0.0
    for path in iter_box_csv_sources(folder):
        rows = records_from_purchase_csv(path, fallback_ymd=ymd)
        if not rows:
            continue
        batches.append(rows)
        used.append(path)
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return merge_purchase_records(batches), newest, used


def pick_best_box_csv(box_dir: Union[str, Path]) -> Optional[Path]:
    """互換用。合算対象のうち先頭（出品CSV優先）を返す。"""
    _records, _mtime, used = collect_box_csv_records(box_dir)
    return used[0] if used else None


def ensure_photo_candidates_from_csvs(
    box_dir: Union[str, Path],
    *,
    force: bool = False,
    register_web: bool = True,
) -> Optional[Tuple[Path, List[Dict[str, Any]]]]:
    """
    仕入CSV／出品CSVが候補より新しければ photo_candidates を自動生成する。

    複数CSVがあるときは中身を合算して表示する。
    HIRIOのDB保存前でも、スマホ撮影一覧を出せるようにする。
    """
    folder = Path(box_dir)
    if not folder.is_dir():
        return None
    ymd = extract_box_ymd_from_name(folder.name) or ""
    records, src_mtime, used = collect_box_csv_records(folder, fallback_ymd=ymd)
    if not records or not used:
        return None
    candidates_path = folder / PHOTO_CANDIDATES_FILE
    if candidates_path.is_file() and not force:
        try:
            cand_mtime = candidates_path.stat().st_mtime
        except OSError:
            cand_mtime = 0.0
        # 候補の方が新しい／同じなら触らない（HIRIO仕入後のSKU付きを守る）
        if cand_mtime >= src_mtime - 0.01:
            existing = load_photo_candidates(folder)
            if existing:
                return candidates_path, existing
    if not ymd:
        ymd = extract_record_box_ymd(records[0]) or format_box_date()

    route_name = folder.name
    route_code = ONLINE_ROUTE_CODE
    box_kind = ONLINE_BOX_KIND
    is_online_box = True
    route_path = folder / "route.json"
    if route_path.is_file():
        try:
            existing = json.loads(route_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict):
            route_name = str(existing.get("route_name") or route_name).strip() or route_name
            existing_code = str(existing.get("route_code") or "").strip()
            existing_kind = str(existing.get("box_kind") or "").strip().lower()
            if existing_code:
                route_code = existing_code
            if existing_kind and existing_kind != ONLINE_BOX_KIND:
                box_kind = existing_kind
                is_online_box = False
            elif existing_code.upper() not in ("", ONLINE_ROUTE_CODE):
                is_online_box = False
                box_kind = existing_kind or "store"
            iso_existing = str(existing.get("route_date") or "").strip()
            if iso_existing and not ymd:
                ymd = format_box_date(iso_existing)

    if register_web and is_online_box:
        try:
            ensure_online_route_registration(
                folder, box_date=ymd or None, route_name=route_name
            )
        except Exception:
            pass
    return write_photo_candidates(
        folder,
        records,
        route_date=box_date_iso(ymd) if ymd else "",
        route_name=route_name,
        route_code=route_code,
        box_kind=box_kind,
    )


def rebuild_photo_candidates_from_listing_export(
    box_dir: Union[str, Path],
    *,
    listing_path: Optional[Union[str, Path]] = None,
) -> Tuple[Path, List[Dict[str, Any]]]:
    """箱内の出品CSV／仕入CSVから撮影候補を作り直す（複数CSVは合算）。"""
    folder = Path(box_dir)
    ymd = extract_box_ymd_from_name(folder.name) or ""
    if listing_path is not None:
        path = Path(listing_path)
        if not path.is_file():
            raise FileNotFoundError(f"仕入／出品CSVが見つかりません: {path}")
        records = records_from_purchase_csv(path, fallback_ymd=ymd)
        if not records:
            raise ValueError(f"CSVから商品を読めませんでした: {path}")
    else:
        records, _mtime, used = collect_box_csv_records(folder, fallback_ymd=ymd)
        if not records or not used:
            raise FileNotFoundError(f"仕入／出品CSVが見つかりません: {folder}")
    if not ymd:
        ymd = extract_record_box_ymd(records[0]) or format_box_date()
    ensure_online_route_registration(folder, box_date=ymd or None, route_name=folder.name)
    return write_photo_candidates(
        folder,
        records,
        route_date=box_date_iso(ymd) if ymd else "",
        route_name=folder.name,
    )


def write_photo_candidates_grouped_by_box(
    base_dir: Union[str, Path],
    records: Iterable[Dict[str, Any]],
    *,
    label: str = "フリマ",
    fallback_ymd: str = "",
    register_web: bool = True,
) -> List[Tuple[Path, List[Dict[str, Any]], str]]:
    """
    仕入行を箱日付ごとに分け、各 フリマYYYYMMDD へ撮影候補を書く。

    Returns:
        [(box_dir, rows, ymd), ...]
    """
    grouped = group_records_by_box_ymd(records)
    unknown = grouped.pop("", [])
    if unknown:
        fb = format_box_date(fallback_ymd) if fallback_ymd else format_box_date()
        grouped.setdefault(fb, []).extend(unknown)

    results: List[Tuple[Path, List[Dict[str, Any]], str]] = []
    for ymd in sorted(grouped.keys()):
        rows_in = grouped[ymd]
        created = resolve_or_create_online_box_for_ymd(
            base_dir,
            ymd,
            label=label,
            register_web=register_web,
        )
        _path, rows = write_photo_candidates(
            created.box_dir,
            rows_in,
            route_date=box_date_iso(ymd),
            route_name=created.box_dir.name,
        )
        results.append((created.box_dir, rows, ymd))
    return results


def build_photo_candidate_rows(
    records: Iterable[Dict[str, Any]],
    *,
    route_date: str = "",
    route_name: str = "",
    route_code: str = ONLINE_ROUTE_CODE,
) -> List[Dict[str, Any]]:
    """仕入一覧行から撮影候補を作る。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        sku = _cell(record, "SKU", "sku")
        jan = "".join(ch for ch in _cell(record, "JAN", "jan") if ch.isdigit())
        asin = "".join(
            ch for ch in _cell(record, "ASIN", "asin").upper() if ch.isalnum()
        )[:16]
        name = _cell(record, "商品名", "product_name", "title")
        if not (sku or jan or asin or name):
            continue
        key = (sku, jan, asin, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "sku": sku,
                "jan": jan,
                "asin": asin,
                "product_name": name,
                "condition": short_condition_label(
                    _cell(record, "コンディション", "condition"),
                    code=_cell(record, "condition_code"),
                ),
                "store_code": ONLINE_ROUTE_CODE,
                "store_name": "ネット仕入",
                "purchase_date": route_date or _cell(record, "仕入れ日", "purchase_date"),
                "route_name": route_name,
                "route_code": route_code,
                "route_date": route_date,
            }
        )
    return rows


def _candidate_match_keys(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    """仮SKU→本SKU付け替えの突き合わせキー。"""
    keys: List[Tuple[str, str]] = []
    asin = normalize_listing_asin(_cell(row, "ASIN", "asin"))
    if asin:
        keys.append(("asin", asin))
    jan = "".join(ch for ch in _cell(row, "JAN", "jan") if ch.isdigit())
    if jan:
        keys.append(("jan", jan))
    sku = _cell(row, "SKU", "sku")
    if sku:
        keys.append(("sku", sku.upper()))
    return keys


def _sku_upgrades_from_rows(
    old_rows: Iterable[Dict[str, Any]],
    new_rows: Iterable[Dict[str, Any]],
) -> List[Tuple[str, str]]:
    """
    旧候補／画像メタの仮SKUが、新候補の本SKUに置き換わる組を返す。
    本SKU→仮SKU や 本SKU同士の無関係な変更は含めない。
    """
    old_by_key: Dict[Tuple[str, str], str] = {}
    for row in old_rows:
        if not isinstance(row, dict):
            continue
        sku = _cell(row, "SKU", "sku")
        if not sku:
            continue
        for key in _candidate_match_keys(row):
            # 同じキーに本SKUと仮SKUが両方来る場合は本SKUを優先保持
            prev = old_by_key.get(key)
            if prev and not _is_tmp_sku(prev) and _is_tmp_sku(sku):
                continue
            old_by_key[key] = sku

    upgrades: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for row in new_rows:
        if not isinstance(row, dict):
            continue
        new_sku = _cell(row, "SKU", "sku")
        if not new_sku or _is_tmp_sku(new_sku):
            continue
        old_sku = ""
        for key in _candidate_match_keys(row):
            candidate = old_by_key.get(key) or ""
            if candidate and _is_tmp_sku(candidate):
                old_sku = candidate
                break
        if not old_sku or old_sku.upper() == new_sku.upper():
            continue
        pair = (old_sku, new_sku)
        if pair in seen:
            continue
        seen.add(pair)
        upgrades.append(pair)
    return upgrades


def _product_file_sku_rows(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """route.json の product_files から sku/jan/asin 行を拾う。"""
    rows: List[Dict[str, Any]] = []
    lists: List[Any] = [doc.get("product_files") or []]
    for store in doc.get("stores") or []:
        if isinstance(store, dict):
            lists.append(store.get("product_files") or [])
    for files in lists:
        for item in files:
            if not isinstance(item, dict):
                continue
            sku = _cell(item, "sku", "SKU")
            if not sku:
                continue
            rows.append(
                {
                    "sku": sku,
                    "jan": _cell(item, "jan", "JAN"),
                    "asin": _cell(item, "asin", "ASIN"),
                }
            )
    return rows


def write_photo_candidates(
    box_dir: Union[str, Path],
    records: Iterable[Dict[str, Any]],
    *,
    route_date: str = "",
    route_name: str = "",
    route_code: str = ONLINE_ROUTE_CODE,
    box_kind: str = ONLINE_BOX_KIND,
) -> tuple[Path, List[Dict[str, Any]]]:
    """撮影候補を photo_candidates.json と route.json に書く。"""
    folder = Path(box_dir)
    name = route_name or folder.name
    code = (route_code or ONLINE_ROUTE_CODE).strip() or ONLINE_ROUTE_CODE
    kind = (box_kind or ONLINE_BOX_KIND).strip() or ONLINE_BOX_KIND
    iso = route_date or box_date_iso(name[-8:] if len(name) >= 8 else None)
    rows = build_photo_candidate_rows(
        records,
        route_date=iso,
        route_name=name,
        route_code=code,
    )
    # 候補行の店舗コードはルート記号に合わせる（店舗箱でも仮撮影できる）
    for row in rows:
        row["store_code"] = code if code != ONLINE_ROUTE_CODE else ONLINE_ROUTE_CODE
        if code != ONLINE_ROUTE_CODE:
            row["store_name"] = name

    old_rows = load_photo_candidates(folder)
    route_path = folder / "route.json"
    doc: Dict[str, Any] = {}
    if route_path.is_file():
        try:
            loaded = json.loads(route_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except (OSError, json.JSONDecodeError):
            doc = {}
    old_rows = list(old_rows) + _product_file_sku_rows(doc)
    upgrades = _sku_upgrades_from_rows(old_rows, rows)
    if upgrades:
        try:
            from route_web.product_images import apply_sku_upgrades_to_box
        except ImportError:
            try:
                from desktop.route_web.product_images import (  # type: ignore
                    apply_sku_upgrades_to_box,
                )
            except ImportError:
                apply_sku_upgrades_to_box = None  # type: ignore
        if apply_sku_upgrades_to_box is not None:
            doc, _renamed = apply_sku_upgrades_to_box(folder, doc, upgrades)

    payload = {
        "box_kind": kind,
        "route_date": iso,
        "route_name": name,
        "candidates": rows,
    }
    candidates_path = folder / PHOTO_CANDIDATES_FILE
    candidates_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if route_path.is_file() or doc:
        if not isinstance(doc, dict):
            doc = {}
        doc["photo_candidates"] = rows
        # 店舗ルートを online に潰さない（未設定のときだけ補う）
        if not str(doc.get("box_kind") or "").strip():
            doc["box_kind"] = kind
        try:
            route_path.parent.mkdir(parents=True, exist_ok=True)
            route_path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return candidates_path, rows


def _ensure_candidate_sku(
    row: Dict[str, Any],
    *,
    route_date: str = "",
    index: int = 1,
) -> Dict[str, Any]:
    """候補にSKUが無いときは仮SKUを補う（仕入CSVだけの撮影用）。"""
    out = dict(row)
    sku = _cell(out, "SKU", "sku")
    if sku and sku != "未実装":
        out["sku"] = sku
        return out
    ymd = "".join(ch for ch in str(route_date or "") if ch.isdigit())[:8]
    if len(ymd) != 8:
        ymd = format_box_date() or date.today().strftime("%Y%m%d")
    asin = normalize_listing_asin(_cell(out, "ASIN", "asin"))
    jan = "".join(ch for ch in _cell(out, "JAN", "jan") if ch.isdigit())
    if asin:
        tail = asin[-6:]
    elif jan:
        tail = jan[-6:]
    else:
        tail = f"{index:03d}"
    out["sku"] = f"TMP-{ymd}-{tail}"
    return out


def load_photo_candidates(
    box_dir: Optional[Union[str, Path]] = None,
    doc: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """route.json または photo_candidates.json から候補を読む。"""
    route_date = ""
    raw_rows: List[Dict[str, Any]] = []
    if isinstance(doc, dict):
        route_date = str(doc.get("route_date") or "")
        embedded = doc.get("photo_candidates")
        if isinstance(embedded, list) and embedded:
            raw_rows = [row for row in embedded if isinstance(row, dict)]

    folder: Optional[Path] = None
    if not raw_rows:
        if box_dir is not None:
            folder = Path(box_dir)
        elif isinstance(doc, dict) and doc.get("folder_path"):
            folder = Path(str(doc.get("folder_path")))
        if folder is None or not folder.is_dir():
            return []

        path = folder / PHOTO_CANDIDATES_FILE
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(raw, list):
            raw_rows = [row for row in raw if isinstance(row, dict)]
        elif isinstance(raw, dict):
            if not route_date:
                route_date = str(raw.get("route_date") or "")
            rows = raw.get("candidates")
            if isinstance(rows, list):
                raw_rows = [row for row in rows if isinstance(row, dict)]
    if not route_date and folder is not None:
        route_date = box_date_iso(extract_box_ymd_from_name(folder.name) or "") or ""
    return [
        _ensure_candidate_sku(row, route_date=route_date, index=i)
        for i, row in enumerate(raw_rows, start=1)
    ]


def is_online_box_doc(doc: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(doc, dict):
        return False
    kind = str(doc.get("box_kind") or "").strip().lower()
    if kind == ONLINE_BOX_KIND:
        return True
    return str(doc.get("route_code") or "").strip().upper() == ONLINE_ROUTE_CODE


def looks_like_online_box_dir(path: Path) -> bool:
    """ネット仕入の日付箱っぽいか。"""
    if not path.is_dir():
        return False
    name = path.name.strip()
    if not name or name.startswith("."):
        return False
    if (path / "route.json").is_file():
        return True
    if (path / PRODUCT_DIR_NAME).is_dir() or (path / CSV_DIR_NAME).is_dir():
        return True
    if (path / EVIDENCE_DIR_NAME).is_dir():
        return True
    # フリマ20261001 のような日付入り名
    digits = "".join(ch for ch in name if ch.isdigit())
    return len(digits) >= 8


def sync_online_boxes_into_registry(
    root: Optional[Union[str, Path]] = None,
) -> List[str]:
    """
    ネット仕入れリスト配下の箱を route.json 付きで Web 一覧に載せる。
    戻り値は登録した web_id のリスト。
    """
    base = Path(root) if root else resolve_default_online_root()
    if base is None or not Path(base).is_dir():
        return []

    registered: List[str] = []
    for child in sorted(Path(base).iterdir(), key=lambda p: p.name, reverse=True):
        if not looks_like_online_box_dir(child):
            continue
        # サブフォルダが無ければ揃える（既存フリマ箱向け）
        for sub in ONLINE_BOX_SUBDIRS:
            (child / sub).mkdir(exist_ok=True)
        try:
            web_id, _ = ensure_online_route_registration(child, route_name=child.name)
        except Exception:
            continue
        try:
            ensure_photo_candidates_from_csvs(child, register_web=False)
        except Exception:
            pass
        if web_id:
            registered.append(web_id)
    return registered
