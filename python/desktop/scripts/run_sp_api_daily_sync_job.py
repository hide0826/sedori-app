#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
毎朝の SP-API 同期。

1. FBA残在庫の一番古い受領日を仕入DBの出品日へ書く
2. 直近の注文を販売DBへ入れ、仕入を販売済みにする
3. 返品を返金総額へ入れ、全額返金は仕入を返金にする

使い方（リポジトリ直下）:
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_daily_sync_job.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def _desktop_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_root() -> Path:
    return _desktop_root().parent


def _repo_root() -> Path:
    return _python_root().parent


def _setup_paths() -> None:
    desktop = str(_desktop_root())
    python = str(_python_root())
    shared = str(_repo_root().parents[1] / "shared")
    for path in (desktop, python, shared):
        if path in sys.path:
            sys.path.remove(path)
    sys.path.insert(0, shared)
    sys.path.insert(0, python)
    sys.path.insert(0, desktop)


def _log(path: Path, message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def run_daily_sync(
    log_path: Path,
    *,
    sales_days: int,
    refund_days: int,
    receipt_lookback_days: int,
) -> int:
    from database.purchase_db import PurchaseDatabase
    from database.sales_db import SalesDatabase
    from services.sp_api_orders import build_sp_api_client
    from services.sp_api_receipt_date import (
        apply_receipt_listed_dates,
        fetch_fba_warehouse_on_hand,
        fetch_receipt_events,
        listed_dates_for_fba_stock,
    )
    from services.sp_api_sales_sync import sync_refunds_from_client, sync_sales_from_client

    on_progress = lambda msg: _log(log_path, msg)  # noqa: E731
    client = build_sp_api_client()
    client.ensure_credentials()
    purchase_db = PurchaseDatabase()
    sales_db = SalesDatabase()
    for db in (purchase_db, sales_db):
        if db.conn is not None:
            db.conn.execute("PRAGMA busy_timeout = 30000")
    summary: Dict[str, Any] = {}
    failed = False
    try:
        # 出品レポートの在庫数は FBA だと空欄なので、倉庫在庫レポートを使う。
        try:
            on_hand = fetch_fba_warehouse_on_hand(client, on_progress=on_progress)
            summary["fba_on_hand"] = len(on_hand)
        except Exception as exc:  # noqa: BLE001
            on_hand = {}
            failed = True
            summary["fba_on_hand_error"] = str(exc)
            on_progress(f"ERROR fba inventory: {exc}")
        on_progress("受領レポートを取得中…")
        try:
            events = fetch_receipt_events(
                client,
                on_progress=on_progress,
                lookback_days=receipt_lookback_days,
            )
        except Exception as exc:  # noqa: BLE001
            events = []
            failed = True
            summary["receipts_error"] = str(exc)
            on_progress(f"ERROR receipts: {exc}")
        listed = listed_dates_for_fba_stock(on_hand, events)
        on_progress(f"受領日が決まったSKU: {len(listed)}")
        receipt_summary = apply_receipt_listed_dates(purchase_db, listed)
        on_progress(f"出品日更新: {receipt_summary}")
        summary["receipts"] = receipt_summary
        summary["listed_resolved"] = len(listed)

        on_progress(f"注文を取得中… 過去{sales_days}日")
        try:
            sales_result = sync_sales_from_client(
                client,
                sales_db,
                purchase_db,
                days=sales_days,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            failed = True
            summary["sales_error"] = str(exc)
            on_progress(f"ERROR sales: {exc}")
            sales_result = None
        if sales_result is not None:
            on_progress(
                "販売反映 "
                f"inserted={sales_result['upsert'].get('inserted')} "
                f"updated={sales_result['upsert'].get('updated')} "
                f"sold={sales_result['status'].get('updated_sold')} "
                f"partial={sales_result['status'].get('updated_partial')}"
            )
            summary["sales"] = {
                "upsert": sales_result["upsert"],
                "status": sales_result["status"],
                "orders_seen": (sales_result.get("fetch") or {}).get("orders_seen"),
                "errors": (sales_result.get("fetch") or {}).get("errors") or [],
            }

        on_progress(f"返品を取得中… 過去{refund_days}日")
        try:
            refund_result = sync_refunds_from_client(
                client,
                sales_db,
                purchase_db,
                days=refund_days,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            failed = True
            summary["refunds_error"] = str(exc)
            on_progress(f"ERROR refunds: {exc}")
            refund_result = None
        if refund_result is not None:
            on_progress(
                "返金反映 "
                f"updated={refund_result['applied'].get('updated')} "
                f"refunded={refund_result['refunded'].get('updated_refunded')}"
            )
            summary["refunds"] = {
                "applied": refund_result["applied"],
                "refunded": refund_result["refunded"],
                "errors": (refund_result.get("fetch") or {}).get("errors") or [],
            }
    finally:
        try:
            purchase_db.close()
        except Exception:
            pass
        try:
            sales_db.close()
        except Exception:
            pass

    summary["at"] = datetime.now().isoformat(timespec="seconds")
    out = log_path.with_suffix(".summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(log_path, f"summary {summary}")
    return 1 if failed else 0


def main(argv: Optional[list] = None) -> int:
    _setup_paths()
    parser = argparse.ArgumentParser(description="HIRIO SP-API 日次同期")
    parser.add_argument("--sales-days", type=int, default=2)
    parser.add_argument("--refund-days", type=int, default=14)
    parser.add_argument("--receipt-lookback-days", type=int, default=540)
    args = parser.parse_args(argv)
    log_path = _desktop_root() / "logs" / "sp_api_daily_sync.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _log(log_path, "=== start daily sync ===")
    try:
        code = run_daily_sync(
            log_path,
            sales_days=max(1, int(args.sales_days)),
            refund_days=max(1, int(args.refund_days)),
            receipt_lookback_days=max(1, int(args.receipt_lookback_days)),
        )
    except Exception as exc:  # noqa: BLE001
        _log(log_path, f"ERROR {exc}")
        _log(log_path, traceback.format_exc())
        code = 1
    _log(log_path, f"=== end code={code} ===")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
