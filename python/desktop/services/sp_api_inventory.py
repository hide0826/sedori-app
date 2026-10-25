#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API Reports から出品一覧を取得し、価格改定用のプライスター互換 DataFrame / CSV にする。

入口レポート: GET_MERCHANT_LISTINGS_ALL_DATA
priceTrace は常に 0（SP-API 直結ではプライスター追従を使わない）。
"""

from __future__ import annotations

import csv
import io
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

try:
    from services.sp_api_orders import build_sp_api_client
except ImportError:
    from desktop.services.sp_api_orders import build_sp_api_client  # type: ignore

try:
    from services.sp_api_refunds import (
        download_report_document,
        wait_report_done,
    )
except ImportError:
    from desktop.services.sp_api_refunds import (  # type: ignore
        download_report_document,
        wait_report_done,
    )


REPORT_MERCHANT_LISTINGS_ALL = "GET_MERCHANT_LISTINGS_ALL_DATA"
LISTINGS_REPORT_REUSE_MAX_AGE_SEC = 90 * 60
LISTINGS_REPORT_LOOKBACK_HOURS = 6
LISTINGS_REPORT_TIMEOUT_SEC = 1800.0

# 既存 /repricer/preview が期待する列（pwa/test_repricer.csv と同順）
PRICETAR_COLUMNS: Tuple[str, ...] = (
    "SKU",
    "ASIN",
    "title",
    "number",
    "price",
    "cost",
    "akaji",
    "takane",
    "condition",
    "conditionNote",
    "priceTrace",
    "leadtime",
    "amazon-fee",
    "shipping-price",
    "profit",
    "add-delete",
)

# 列名ゆれ（英日・スペース・ハイフン差）を正規化して照合する
_SKU_HEADER_KEYS = frozenset(
    {
        "seller-sku",
        "sellersku",
        "sku",
        "出品者sku",
        "出品sku",
        "商品管理番号",
        "merchant-sku",
        "merchantsku",
        "sellersku",
    }
)
_ASIN_HEADER_KEYS = frozenset(
    {
        "asin1",
        "asin",
        "product-id",
        "productid",
        "商品id",
        "asinコード",
    }
)
_TITLE_HEADER_KEYS = frozenset(
    {
        "item-name",
        "itemname",
        "title",
        "product-name",
        "productname",
        "商品名",
        "タイトル",
    }
)
_PRICE_HEADER_KEYS = frozenset(
    {
        "price",
        "listing-price",
        "listingprice",
        "価格",
        "販売価格",
    }
)
_QTY_HEADER_KEYS = frozenset(
    {
        "quantity",
        "qty",
        "数量",
        "在庫数",
    }
)
_CONDITION_HEADER_KEYS = frozenset(
    {
        "item-condition",
        "itemcondition",
        "condition",
        "コンディション",
        "商品のコンディション",
    }
)
_STATUS_HEADER_KEYS = frozenset(
    {
        "status",
        "ステータス",
        "出品ステータス",
    }
)


def _payload(body: Dict[str, Any]) -> Dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return payload
    return body if isinstance(body, dict) else {}


def extract_report_list(body: Any) -> List[Dict[str, Any]]:
    """list_reports の応答から reports 配列を取り出す。"""
    if not isinstance(body, dict):
        return []
    reports = body.get("reports")
    if not isinstance(reports, list):
        payload = body.get("payload")
        if isinstance(payload, dict):
            reports = payload.get("reports")
    if not isinstance(reports, list):
        return []
    return [row for row in reports if isinstance(row, dict)]


def parse_report_created_epoch(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def pick_reusable_listings_report(
    reports: Sequence[Mapping[str, Any]],
    *,
    now_epoch: Optional[float] = None,
    max_age_sec: float = LISTINGS_REPORT_REUSE_MAX_AGE_SEC,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """新しい順に見て、再利用できる DONE と進行中レポートを返す。"""
    now = float(now_epoch if now_epoch is not None else time.time())
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for row in reports:
        created = parse_report_created_epoch(row.get("createdTime")) or 0.0
        scored.append((created, dict(row)))
    scored.sort(key=lambda item: item[0], reverse=True)
    done: Optional[Dict[str, Any]] = None
    inflight: Optional[Dict[str, Any]] = None
    for created, row in scored:
        status = str(row.get("processingStatus") or "").upper()
        if (
            status == "DONE"
            and str(row.get("reportDocumentId") or "").strip()
            and created
            and (now - created) <= float(max_age_sec)
        ):
            if done is None:
                done = row
        elif status in ("IN_QUEUE", "IN_PROGRESS") and inflight is None:
            inflight = row
    return done, inflight


def humanize_listings_report_error(exc: BaseException) -> str:
    text = str(exc)
    low = text.lower()
    if "secret token" in low and "expired" in low:
        return (
            "LWAクライアントシークレットの期限切れです。"
            "Amazon開発者コンソールでシークレットを再発行し、"
            ".env の SP_API_CLIENT_SECRET を更新してください。"
            f" 詳細: {text}"
        )
    return text


def _normalize_header(name: Any) -> str:
    """列名を照合用に正規化する（英日・空白・記号差を吸収）。"""
    text = str(name or "").replace("\ufeff", "").strip().lower()
    text = text.replace("　", "").replace(" ", "").replace("_", "-")
    text = re.sub(r"-+", "-", text)
    return text


def _build_norm_map(row: Mapping[str, Any]) -> Dict[str, Any]:
    """正規化キー → 値。同一正規化キーが複数ある場合は先勝ち。"""
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        nk = _normalize_header(key)
        if not nk or nk in out:
            continue
        out[nk] = value
    return out


def _row_get_by_aliases(row: Mapping[str, Any], aliases: frozenset) -> str:
    norm = _build_norm_map(row)
    for alias in aliases:
        raw = norm.get(_normalize_header(alias))
        if raw is None:
            continue
        text = str(raw).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    # 部分一致（例: 「出品者SKU（必須）」など）
    for nk, raw in norm.items():
        for alias in aliases:
            a = _normalize_header(alias)
            if a and (a in nk or nk in a):
                text = str(raw).strip()
                if text and text.lower() not in ("nan", "none"):
                    return text
    return ""


def _row_get(row: Mapping[str, Any], *keys: str) -> str:
    """後方互換: 明示キー列挙でも取得できるようにする。"""
    return _row_get_by_aliases(row, frozenset(keys))


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("¥", "").replace("円", "")
    if not text or text.lower() in ("nan", "none", "-"):
        return default
    try:
        return int(round(float(text)))
    except (TypeError, ValueError):
        return default


def _is_inactive_status(status: str) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return False
    # Active / アクティブ は残す。明らかに無効なものだけ除外
    if s in {"active", "アクティブ", "有効"}:
        return False
    return s in {
        "inactive",
        "incomplete",
        "detail page removed",
        "blocked",
        "削除",
        "非表示",
        "無効",
        "インアクティブ",
    }


def _detect_delimiter(header_line: str) -> str:
    tabs = header_line.count("\t")
    commas = header_line.count(",")
    if tabs >= commas and tabs > 0:
        return "\t"
    if commas > 0:
        return ","
    return "\t"


def _looks_like_listings_header(line: str) -> bool:
    """出品一覧のヘッダ行らしいか（英日両対応）。"""
    n = _normalize_header(line)
    has_sku = ("seller-sku" in n) or ("sellersku" in n) or ("出品者sku" in n) or (
        n.startswith("sku") or "\tsku\t" in f"\t{n}\t" or ",sku," in f",{n},"
    )
    # 単独 sku 列のケース: 行内トークンに sku / 出品者sku
    tokens = {_normalize_header(t) for t in re.split(r"[\t,]", line) if t.strip()}
    if tokens & _SKU_HEADER_KEYS:
        return True
    if "seller-sku" in n or "出品者sku" in n:
        return True
    return bool(has_sku and (("price" in n) or ("価格" in n) or ("asin" in n) or ("item-name" in n) or ("商品名" in n)))


def parse_merchant_listings_text(text: str) -> List[Dict[str, str]]:
    """
    出品一覧レポート本文を dict 行にする。

    - 先頭の説明行をスキップしてヘッダを探す
    - タブ / カンマを自動判定
    - 列名の BOM・空白を除去
    """
    raw = (text or "").lstrip("\ufeff")
    if not raw.strip():
        return []
    lines = raw.splitlines()
    header_idx = 0
    for i, line in enumerate(lines[:50]):
        if _looks_like_listings_header(line):
            header_idx = i
            break
    body = "\n".join(lines[header_idx:])
    if not body.strip():
        return []
    first = lines[header_idx] if header_idx < len(lines) else ""
    delimiter = _detect_delimiter(first)
    reader = csv.DictReader(io.StringIO(body), delimiter=delimiter)
    rows: List[Dict[str, str]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        cleaned: Dict[str, str] = {}
        for k, v in row.items():
            if k is None:
                continue
            key = str(k).replace("\ufeff", "").strip()
            if not key:
                continue
            # Deprecated column も列位置フォールバック用に残す（同名は連番化）
            if key.lower().startswith("deprecated"):
                n = 1
                base = key
                while key in cleaned:
                    n += 1
                    key = f"{base}#{n}"
            cleaned[key] = "" if v is None else str(v).strip()
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def summarize_report_columns(rows: Sequence[Mapping[str, Any]], *, limit: int = 20) -> str:
    """デバッグ用: 先頭行の列名を短く返す。"""
    if not rows:
        return "(行なし)"
    keys = [str(k) for k in rows[0].keys()]
    head = keys[:limit]
    more = f" …+{len(keys) - limit}" if len(keys) > limit else ""
    return ", ".join(head) + more


def _load_purchase_cost_map(skus: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """仕入DBから cost / condition などを SKU マップで取得。"""
    result: Dict[str, Dict[str, Any]] = {}
    unique = []
    seen = set()
    for sku in skus:
        s = str(sku or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique.append(s)
    if not unique:
        return result
    try:
        try:
            from database.purchase_db import PurchaseDatabase
        except ImportError:
            from desktop.database.purchase_db import PurchaseDatabase  # type: ignore

        db = PurchaseDatabase()
        for sku in unique:
            rec = db.get_by_sku(sku) or {}
            cost = _to_int(
                rec.get("purchase_price")
                or rec.get("仕入れ価格")
                or rec.get("仕入価格")
                or rec.get("cost"),
                0,
            )
            condition = rec.get("condition_code")
            if condition in (None, ""):
                condition = rec.get("condition") or ""
            note = str(rec.get("condition_note") or rec.get("コンディション説明") or "")
            # Amazon コンディション説明は改行非対応のため1行化
            if note:
                import re
                note = note.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
                note = re.sub(r"\n+", " ", note)
                note = re.sub(r"[ \t　]+", " ", note).strip()
            result[sku] = {
                "cost": cost,
                "condition": condition if condition not in (None, "") else "",
                "conditionNote": note,
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[sp_api_inventory] 仕入DB読込スキップ: {exc}")
    return result


def _find_sku_value(row: Mapping[str, Any]) -> str:
    """SKU を列名ゆれ・部分一致で探す。"""
    direct = _row_get_by_aliases(row, _SKU_HEADER_KEYS)
    if direct:
        return direct
    norm = _build_norm_map(row)
    for nk, raw in norm.items():
        if "sku" not in nk and "商品管理番号" not in nk:
            continue
        # 誤検出回避: asin / image 等は除外
        if any(bad in nk for bad in ("asin", "image", "listing-id", "listingid")):
            continue
        text = str(raw).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return ""


# 公式ドキュメント上の All Listings Report 列順（0始まり）
# 列名が壊れている場合のフォールバック用
_POS_ITEM_NAME = 0
_POS_SELLER_SKU = 3
_POS_PRICE = 4
_POS_QUANTITY = 5
_POS_ASIN1 = 16
_POS_PRODUCT_ID = 22
_POS_CONDITION = 12
_POS_STATUS = 28


def _row_values_in_order(row: Mapping[str, Any]) -> List[str]:
    """Dict 行を元の列順に近いリストにする（挿入順を利用）。"""
    return ["" if v is None else str(v).strip() for v in row.values()]


def _merchant_row_from_positions(values: Sequence[str]) -> Optional[Dict[str, Any]]:
    """列位置フォールバックでプライスター互換 dict を作る。"""
    if len(values) <= _POS_SELLER_SKU:
        return None
    sku = str(values[_POS_SELLER_SKU] or "").strip()
    if not sku:
        return None
    status = values[_POS_STATUS] if len(values) > _POS_STATUS else ""
    if _is_inactive_status(status):
        return None
    title = values[_POS_ITEM_NAME] if len(values) > _POS_ITEM_NAME else ""
    price = _to_int(values[_POS_PRICE] if len(values) > _POS_PRICE else 0, 0)
    number = _to_int(values[_POS_QUANTITY] if len(values) > _POS_QUANTITY else 0, 0)
    asin = ""
    if len(values) > _POS_ASIN1:
        asin = str(values[_POS_ASIN1] or "").strip()
    if not asin and len(values) > _POS_PRODUCT_ID:
        asin = str(values[_POS_PRODUCT_ID] or "").strip()
    condition = values[_POS_CONDITION] if len(values) > _POS_CONDITION else "11"
    return {
        "SKU": sku,
        "ASIN": asin,
        "title": title,
        "number": number,
        "price": price,
        "cost": 0,
        "akaji": 0,
        "takane": 0,
        "condition": condition or "11",
        "conditionNote": "",
        "priceTrace": 0,
        "leadtime": "",
        "amazon-fee": 0,
        "shipping-price": 0,
        "profit": 0,
        "add-delete": "",
    }


def merchant_listing_row_to_pricetar(
    row: Mapping[str, Any],
    *,
    purchase: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """出品レポート1行 → プライスター互換 dict。SKU が無ければ None。"""
    sku = _find_sku_value(row)
    if not sku:
        return None
    status = _row_get_by_aliases(row, _STATUS_HEADER_KEYS)
    if _is_inactive_status(status):
        return None

    asin = _row_get_by_aliases(row, _ASIN_HEADER_KEYS)
    title = _row_get_by_aliases(row, _TITLE_HEADER_KEYS)
    price = _to_int(_row_get_by_aliases(row, _PRICE_HEADER_KEYS), 0)
    number = _to_int(_row_get_by_aliases(row, _QTY_HEADER_KEYS), 0)
    condition = _row_get_by_aliases(row, _CONDITION_HEADER_KEYS)
    purchase = purchase or {}
    cost = _to_int(purchase.get("cost"), 0)
    if not condition:
        condition = str(purchase.get("condition") or "") or "11"
    note = str(purchase.get("conditionNote") or "")

    return {
        "SKU": sku,
        "ASIN": asin,
        "title": title,
        "number": number,
        "price": price,
        "cost": cost,
        "akaji": 0,
        "takane": 0,
        "condition": condition,
        "conditionNote": note,
        "priceTrace": 0,
        "leadtime": "",
        "amazon-fee": 0,
        "shipping-price": 0,
        "profit": 0,
        "add-delete": "",
    }


def listings_rows_to_dataframe(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """レポート行リストをプライスター互換 DataFrame にする。"""
    skus = [_find_sku_value(r) for r in rows]
    purchase_map = _load_purchase_cost_map(skus)
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sku = _find_sku_value(row)
        if sku and sku not in seen:
            mapped = merchant_listing_row_to_pricetar(row, purchase=purchase_map.get(sku))
            if mapped:
                seen.add(sku)
                records.append(mapped)
                continue
        # 列名でSKUが取れない場合: 公式列順フォールバック
        if not sku:
            mapped = _merchant_row_from_positions(_row_values_in_order(row))
            if mapped and mapped["SKU"] not in seen:
                purchase = purchase_map.get(mapped["SKU"]) or {}
                if purchase.get("cost"):
                    mapped["cost"] = _to_int(purchase.get("cost"), 0)
                if purchase.get("condition"):
                    mapped["condition"] = str(purchase.get("condition"))
                if purchase.get("conditionNote"):
                    mapped["conditionNote"] = str(purchase.get("conditionNote"))
                seen.add(mapped["SKU"])
                records.append(mapped)
    if not records:
        return pd.DataFrame(columns=list(PRICETAR_COLUMNS))
    df = pd.DataFrame(records)
    for col in PRICETAR_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ("conditionNote", "leadtime", "add-delete", "title", "ASIN") else 0
    return df[list(PRICETAR_COLUMNS)]


def write_pricetar_temp_csv(df: pd.DataFrame, *, prefix: str = "hirio_sp_api_listings_") -> str:
    """価格改定 API 用の一時 CSV を書き、パスを返す。"""
    out_dir = Path(tempfile.gettempdir()) / "hirio_sp_api_reprice"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prefix}{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    export = df.copy()
    for col in PRICETAR_COLUMNS:
        if col not in export.columns:
            export[col] = ""
    export[list(PRICETAR_COLUMNS)].to_csv(path, index=False, encoding="utf-8-sig")
    return str(path)


def _list_recent_listings_reports(client: Any) -> List[Dict[str, Any]]:
    if not hasattr(client, "list_reports"):
        return []
    since = (
        datetime.now(timezone.utc) - timedelta(hours=LISTINGS_REPORT_LOOKBACK_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = client.list_reports(
        report_types=[REPORT_MERCHANT_LISTINGS_ALL],
        created_since=since,
        page_size=10,
    )
    return extract_report_list(body)


def _download_listings_document(
    client: Any,
    done: Mapping[str, Any],
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, str]]:
    doc_id = str(done.get("reportDocumentId") or "").strip()
    if not doc_id:
        raise RuntimeError(f"{REPORT_MERCHANT_LISTINGS_ALL}: reportDocumentId がありません")
    if on_progress:
        on_progress("レポートダウンロード中…")
    doc = client.get_report_document(doc_id)
    text = download_report_document(doc)
    rows = parse_merchant_listings_text(text)
    if on_progress:
        cols = summarize_report_columns(rows)
        on_progress(f"出品レポート取得完了: {len(rows)} 行（列: {cols}）")
    return rows


def fetch_merchant_listings_report(
    client: Any,
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    timeout_sec: float = LISTINGS_REPORT_TIMEOUT_SEC,
) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    GET_MERCHANT_LISTINGS_ALL_DATA を作成→完了待ち→TSV行取得。

    直近90分以内の DONE があれば再利用し、進行中があれば新規作成せず待つ。
    待ち切れても完了済みがあればそれを使う。

    Returns:
        (rows, error_message_or_None)
    """
    try:
        done_payload: Optional[Dict[str, Any]] = None
        done_rep: Optional[Dict[str, Any]] = None
        inflight_rep: Optional[Dict[str, Any]] = None
        try:
            listed = _list_recent_listings_reports(client)
            done_rep, inflight_rep = pick_reusable_listings_report(listed)
        except Exception as list_exc:  # noqa: BLE001
            if on_progress:
                on_progress(f"既存レポート検索をスキップ: {list_exc}")

        if done_rep:
            if on_progress:
                on_progress(
                    f"直近の出品レポートを再利用: {done_rep.get('reportId')} "
                    f"({done_rep.get('createdTime') or '時刻不明'})"
                )
            done_payload = dict(done_rep)
        elif inflight_rep and str(inflight_rep.get("reportId") or "").strip():
            report_id = str(inflight_rep.get("reportId")).strip()
            if on_progress:
                on_progress(
                    f"作成済みレポートの完了を待ちます: {report_id} "
                    f"{inflight_rep.get('processingStatus')}"
                )
            try:
                done_payload = wait_report_done(
                    client,
                    report_id,
                    timeout_sec=timeout_sec,
                    should_cancel=should_cancel,
                    on_progress=on_progress,
                )
            except Exception as wait_exc:  # noqa: BLE001
                if on_progress:
                    on_progress(f"進行中レポート待ち失敗、新規作成します: {wait_exc}")
                done_payload = None

        if done_payload is None:
            if on_progress:
                on_progress(f"レポート作成: {REPORT_MERCHANT_LISTINGS_ALL}")
            created = None
            last_create_exc: Optional[BaseException] = None
            for attempt in range(2):
                try:
                    created = client.create_report(REPORT_MERCHANT_LISTINGS_ALL)
                    last_create_exc = None
                    break
                except Exception as create_exc:  # noqa: BLE001
                    last_create_exc = create_exc
                    if attempt == 0:
                        if on_progress:
                            on_progress(f"レポート作成を再試行します: {create_exc}")
                        time.sleep(3.0)
            if last_create_exc is not None:
                raise last_create_exc
            report_id = str(
                _payload(created or {}).get("reportId") or (created or {}).get("reportId") or ""
            ).strip()
            if not report_id:
                return [], f"{REPORT_MERCHANT_LISTINGS_ALL}: reportId がありません"
            try:
                done_payload = wait_report_done(
                    client,
                    report_id,
                    timeout_sec=timeout_sec,
                    should_cancel=should_cancel,
                    on_progress=on_progress,
                )
            except Exception as wait_exc:  # noqa: BLE001
                fallback = None
                try:
                    listed = _list_recent_listings_reports(client)
                    fallback, _ = pick_reusable_listings_report(listed)
                except Exception:  # noqa: BLE001
                    fallback = None
                if fallback:
                    if on_progress:
                        on_progress(
                            f"待ちタイムアウト後、完了済みレポートを再利用: "
                            f"{fallback.get('reportId')}（原因: {wait_exc}）"
                        )
                    done_payload = dict(fallback)
                else:
                    raise wait_exc

        rows = _download_listings_document(client, done_payload, on_progress=on_progress)
        return rows, None
    except Exception as exc:  # noqa: BLE001
        return [], humanize_listings_report_error(exc)


def fetch_listings_dataframe_for_repricer(
    client: Optional[Any] = None,
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[pd.DataFrame, str, Optional[str]]:
    """
    出品一覧を取得してプライスター互換 DF と一時 CSV パスを返す。

    Returns:
        (df, csv_path, error_or_None)
    """
    api = client or build_sp_api_client()
    api.ensure_credentials()
    rows, err = fetch_merchant_listings_report(
        api,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    if err:
        return pd.DataFrame(columns=list(PRICETAR_COLUMNS)), "", err
    df = listings_rows_to_dataframe(rows)
    if df.empty:
        cols = summarize_report_columns(rows)
        sample_sku = _find_sku_value(rows[0]) if rows else ""
        return (
            df,
            "",
            "有効な出品行がありません（SKU列を認識できない、または Inactive のみ）。\n"
            f"取得行数: {len(rows)}\n"
            f"検出列: {cols}\n"
            f"先頭行SKU候補: {sample_sku or '(空)'}",
        )
    csv_path = write_pricetar_temp_csv(df)
    return df, csv_path, None
