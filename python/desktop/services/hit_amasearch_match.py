#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アマサーチCSV取込 × Discord購入一覧の突合。

- 同じ ASIN・日付差 ±3日以内の未登録購入から出品URLを埋める
- 画像を使用する=ON なら採用画像をネット仕入箱の商品画像へ保存
- URLを埋めた購入は Amazon登録済みにする
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

DATE_MATCH_DAYS = 3
CSV_DIR_NAME = "仕入CSV"
ONLINE_ROUTE_CODE = "NET"

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


@dataclass
class MatchResult:
    url_filled: int = 0
    images_saved: int = 0
    image_files: int = 0
    registered: int = 0
    skipped_no_match: int = 0
    errors: List[str] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines = [
            f"出品URL自動入力: {self.url_filled}件",
            f"画像保存: {self.images_saved}件（ファイル {self.image_files}枚）",
            f"Amazon登録済み: {self.registered}件",
        ]
        if self.skipped_no_match:
            lines.append(f"照合なし: {self.skipped_no_match}件")
        if self.errors:
            lines.append("注意: " + " / ".join(self.errors[:5]))
            if len(self.errors) > 5:
                lines.append(f"…他 {len(self.errors) - 5}件")
        return lines


def _ensure_shared_on_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    candidates: List[Path] = []
    for parent in here.parents:
        candidates.append(parent / "shared")
        if parent.name.upper() == "HIRIO":
            candidates.append(parent / "shared")
    candidates.extend([Path(r"C:\HIRIO\shared"), Path(r"D:\HIRIO\shared")])
    for shared in candidates:
        if shared.is_dir() and (shared / "hit_snapshot.py").is_file():
            text = str(shared)
            if text not in sys.path:
                sys.path.insert(0, text)
            return shared
    return None


def _ensure_route_web_importable() -> None:
    desktop_dir = Path(__file__).resolve().parents[1]
    python_dir = desktop_dir.parent
    for path in (str(python_dir), str(desktop_dir)):
        if path not in sys.path:
            sys.path.insert(0, path)


def normalize_asin(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    if _ASIN_RE.match(text):
        return text
    return text[:16] if text else ""


def parse_inventory_date(value: Any) -> Optional[date]:
    """仕入れ日セルから日付だけ取る。"""
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None
    # 2026/10/15 22:53 / 2026-10-15T22:53:00+09:00
    digits = re.findall(r"\d+", text)
    if len(digits) >= 3 and len(digits[0]) == 4:
        try:
            y, m, d = int(digits[0]), int(digits[1]), int(digits[2])
            return date(y, m, d)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("/", "-")[:19]).date()
    except ValueError:
        return None


def parse_purchase_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        return dt.date()
    except ValueError:
        return parse_inventory_date(text)


def resolve_box_from_csv_path(csv_path: Optional[str]) -> Optional[Path]:
    """…/箱/仕入CSV/file.csv → 箱。"""
    if not csv_path:
        return None
    path = Path(csv_path)
    parent = path.parent
    if parent.name == CSV_DIR_NAME and parent.parent.is_dir():
        return parent.parent
    # 箱直下の CSV
    if (parent / "商品画像").is_dir() or (parent / "route.json").is_file():
        return parent
    return None


def resolve_target_box(
    csv_paths: Optional[Sequence[str]] = None,
) -> Optional[Path]:
    for raw in csv_paths or []:
        box = resolve_box_from_csv_path(raw)
        if box is not None and box.is_dir():
            return box
    try:
        from utils.settings_helper import get_online_purchase_last_box
    except ImportError:
        try:
            from desktop.utils.settings_helper import get_online_purchase_last_box  # type: ignore
        except ImportError:
            get_online_purchase_last_box = None  # type: ignore
    if get_online_purchase_last_box is not None:
        last = (get_online_purchase_last_box() or "").strip()
        if last and Path(last).is_dir():
            return Path(last)
    return None


def _cell(row: Any, *keys: str) -> str:
    for key in keys:
        try:
            if hasattr(row, "get"):
                value = row.get(key)
            else:
                value = row[key] if key in row else None
        except Exception:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return ""


def _load_purchases() -> List[Dict[str, Any]]:
    shared = _ensure_shared_on_path()
    if shared is None:
        return []
    from hit_snapshot import list_purchases

    return list_purchases(limit=0)


def _is_registered_row(row: Dict[str, Any]) -> bool:
    return bool(str(row.get("amazon_registered_at") or "").strip())


def _pick_purchase(
    asin: str,
    inv_date: Optional[date],
    purchases: Sequence[Dict[str, Any]],
    used_tokens: Set[str],
) -> Optional[Dict[str, Any]]:
    best: Optional[Tuple[int, str, Dict[str, Any]]] = None
    for row in purchases:
        token = str(row.get("token") or "").strip()
        if not token or token in used_tokens:
            continue
        if _is_registered_row(row):
            continue
        row_asin = normalize_asin(row.get("asin"))
        if not row_asin or row_asin != asin:
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        pur_date = parse_purchase_date(row.get("at"))
        if inv_date is None or pur_date is None:
            # 日付が片方無いときは候補にしない（誤爆防止）
            continue
        delta = abs((inv_date - pur_date).days)
        if delta > DATE_MATCH_DAYS:
            continue
        at = str(row.get("at") or "")
        # 差が小さいほど良い。同差なら新しい at を優先
        if best is None:
            best = (delta, at, row)
            continue
        b_delta, b_at, _ = best
        if delta < b_delta or (delta == b_delta and at > b_at):
            best = (delta, at, row)
    return best[2] if best else None


def _route_meta(box: Path) -> Tuple[str, str]:
    """(route_date ISO, route_code)"""
    route_date = ""
    route_code = ONLINE_ROUTE_CODE
    path = box / "route.json"
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                route_date = str(doc.get("route_date") or "").strip()
                code = str(doc.get("route_code") or "").strip()
                if code:
                    route_code = code
        except (OSError, json.JSONDecodeError):
            pass
    if not route_date:
        # 箱名末尾 YYYYMMDD
        digits = "".join(ch for ch in box.name if ch.isdigit())
        if len(digits) >= 8:
            ymd = digits[-8:]
            route_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        else:
            route_date = date.today().isoformat()
    return route_date, route_code


def _copy_selected_images(
    *,
    token: str,
    purchase: Dict[str, Any],
    box: Path,
    asin: str,
    jan: str = "",
    sku: str = "",
) -> int:
    """採用画像を箱の商品画像へ保存。保存枚数を返す。"""
    _ensure_shared_on_path()
    from hit_studio import enrich_purchase_with_studio
    from hit_snapshot import snapshots_dir

    enriched = enrich_purchase_with_studio(purchase)
    if not enriched.get("use_images"):
        return 0
    rels = list(enriched.get("effective_image_paths") or [])
    if not rels:
        return 0

    _ensure_route_web_importable()
    from route_web.product_images import (
        append_route_product_file,
        save_product_upload,
    )
    from route_web.registry import route_json_path
    from route_web.schema import stamp_updated

    snap_root = snapshots_dir()
    route_date, route_code = _route_meta(box)
    saved = 0

    try:
        route_path = route_json_path(box)
    except Exception:
        route_path = box / "route.json"

    doc: Dict[str, Any] = {}
    if route_path.is_file():
        try:
            raw = json.loads(route_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                doc = raw
        except (OSError, json.JSONDecodeError):
            doc = {}

    for rel in rels:
        text = str(rel or "").replace("\\", "/").strip().lstrip("/")
        if not text:
            continue
        src = snap_root / text
        if not src.is_file():
            alt = snap_root / Path(text).name
            if alt.is_file():
                src = alt
            else:
                logger.warning("採用画像が無い: token=%s path=%s", token, text)
                continue
        try:
            raw_bytes = src.read_bytes()
            filename = save_product_upload(
                box,
                route_date,
                route_code,
                raw_bytes,
                original_name=src.name,
            )
            doc = append_route_product_file(
                doc,
                filename,
                jan=jan,
                asin=asin,
                sku=sku if sku and sku != "未実装" else "",
            )
            saved += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("画像保存失敗 token=%s: %s", token, exc)
            continue

    if saved and doc:
        try:
            doc = stamp_updated(doc)
            route_path.parent.mkdir(parents=True, exist_ok=True)
            route_path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("route.json 更新失敗: %s", exc)
    return saved


def apply_hit_purchase_match(
    inventory_data: Any,
    *,
    csv_paths: Optional[Sequence[str]] = None,
    row_indices: Optional[Sequence[int]] = None,
) -> MatchResult:
    """
    ネット仕入 DataFrame に購入一覧を突合して副作用（URL埋め・画像・登録済み）を行う。

    inventory_data は pandas.DataFrame（呼び出し側の self.inventory_data）。
    row_indices が無いときは全行を対象（出品URLが空の行のみ更新）。
    """
    result = MatchResult()
    if inventory_data is None or len(inventory_data) == 0:
        return result

    shared = _ensure_shared_on_path()
    if shared is None:
        result.errors.append("shared フォルダが見つかりません")
        return result

    from hit_snapshot import mark_amazon_registered

    try:
        purchases = _load_purchases()
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"購入一覧の読込失敗: {exc}")
        return result

    box = resolve_target_box(csv_paths)
    if box is None:
        logger.info("ネット仕入箱が未確定（画像保存はスキップ、URL埋めは続行）")

    indices: List[int]
    if row_indices is not None:
        indices = [int(i) for i in row_indices]
    else:
        indices = list(inventory_data.index)

    used_tokens: Set[str] = set()
    if "出品URL" not in inventory_data.columns:
        inventory_data["出品URL"] = ""

    for idx in indices:
        try:
            row = inventory_data.loc[idx]
        except Exception:
            continue
        existing_url = _cell(row, "出品URL", "listing_url")
        if existing_url:
            continue
        asin = normalize_asin(_cell(row, "ASIN", "asin"))
        if not asin:
            continue
        inv_date = parse_inventory_date(row.get("仕入れ日") if hasattr(row, "get") else row["仕入れ日"] if "仕入れ日" in row else None)
        purchase = _pick_purchase(asin, inv_date, purchases, used_tokens)
        if purchase is None:
            result.skipped_no_match += 1
            continue

        token = str(purchase.get("token") or "").strip()
        url = str(purchase.get("url") or "").strip()
        if not token or not url:
            result.skipped_no_match += 1
            continue

        inventory_data.at[idx, "出品URL"] = url
        result.url_filled += 1
        used_tokens.add(token)

        if box is not None:
            try:
                n = _copy_selected_images(
                    token=token,
                    purchase=purchase,
                    box=box,
                    asin=asin,
                    jan=_cell(row, "JAN", "jan"),
                    sku=_cell(row, "SKU", "sku"),
                )
                if n > 0:
                    result.images_saved += 1
                    result.image_files += n
            except Exception as exc:  # noqa: BLE001
                logger.exception("画像コピー失敗 token=%s", token)
                result.errors.append(f"画像:{token[:8]}… {exc}")

        inv_date_txt = inv_date.isoformat() if inv_date else ""
        try:
            status, _ = mark_amazon_registered(
                token,
                asin=asin,
                inventory_date=inv_date_txt,
            )
            if status in ("ok", "already"):
                result.registered += 1
            else:
                result.errors.append(f"登録済み更新失敗:{token[:8]}… ({status})")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Amazon登録済み更新失敗 token=%s", token)
            result.errors.append(f"登録済み:{token[:8]}… {exc}")

    return result
