#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API 無人価格改定ジョブ（週次 3-6-9 / 最安追従）。

使い方（HIRIO リポジトリ直下、venv）:
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_reprice_job.py --mode weekly369 --dry-run
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_reprice_job.py --mode follow --dry-run
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_reprice_job.py --mode follow --transport feed --max-patch 1
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_reprice_job.py --mode weekly369 --transport patch --max-patch 1
  .\\.venv\\Scripts\\python.exe python\\desktop\\scripts\\run_sp_api_reprice_job.py --mode smoke
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _desktop_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_root() -> Path:
    return _desktop_root().parent


def _repo_root() -> Path:
    return _python_root().parent


def _log_dir() -> Path:
    path = _desktop_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _setup_paths() -> None:
    desktop = str(_desktop_root())
    python = str(_python_root())
    # C:\HIRIO\repo\sedori-app.github -> C:\HIRIO\shared
    shared = str(_repo_root().parents[1] / "shared")
    for path in (desktop, python, shared):
        if path in sys.path:
            sys.path.remove(path)
    # desktop 先頭: services = desktop/services（在庫・PATCH）
    sys.path.insert(0, shared)
    sys.path.insert(0, python)
    sys.path.insert(0, desktop)


@contextmanager
def _python_services_precedence():
    """apply_repricing_rules 用に python/services を優先する。"""
    desktop = str(_desktop_root())
    python = str(_python_root())
    saved_mods = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "services" or key.startswith("services.")
    }
    # python を先頭へ
    for path in (desktop, python):
        if path in sys.path:
            sys.path.remove(path)
    sys.path.insert(0, desktop)
    sys.path.insert(0, python)
    try:
        yield
    finally:
        for key in list(sys.modules):
            if key == "services" or key.startswith("services."):
                sys.modules.pop(key, None)
        sys.modules.update(saved_mods)
        for path in (desktop, python):
            if path in sys.path:
                sys.path.remove(path)
        sys.path.insert(0, python)
        sys.path.insert(0, desktop)


def _log(path: Path, message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _write_failed_csv(rows: List[Dict[str, Any]], mode: str) -> Optional[Path]:
    if not rows:
        return None
    out = _log_dir() / f"sp_api_reprice_{mode}_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    keys = sorted({k for row in rows for k in row.keys()})
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    return out


def _progress(log_path: Path):
    def _inner(msg: str) -> None:
        _log(log_path, msg)

    return _inner


def run_smoke(log_path: Path) -> int:
    """認証・メソッド有無・疎通の軽い確認（価格は書き換えない）。"""
    from sp_api_client import SpApiClient

    api = SpApiClient()
    api.ensure_credentials()
    for name in (
        "create_report",
        "get_report",
        "get_report_document",
        "get_listing_item",
        "patch_listing_price",
        "get_item_offers_batch",
        "get_orders",
        "create_feed_document",
        "upload_feed_document",
        "create_feed",
        "get_feed",
        "wait_feed_done",
        "get_feed_document",
        "submit_json_listings_feed",
    ):
        if not hasattr(api, name):
            _log(log_path, f"SMOKE FAIL missing method: {name}")
            return 2
    _log(log_path, "methods ok")
    try:
        body = api.ping_sellers()
        _log(log_path, f"ping_sellers ok keys={list(body.keys())[:8]}")
    except Exception as exc:  # noqa: BLE001
        _log(log_path, f"ping_sellers failed: {exc}")
        return 3
    seller = (api.credentials.seller_id or "").strip()
    _log(log_path, f"seller_id={'set' if seller else 'MISSING'}")
    if not seller:
        _log(log_path, "SMOKE WARN: SP_API_SELLER_ID / amazon/seller_id が空です（Feeds/PATCH に必要）")
        return 4
    _log(log_path, "SMOKE OK")
    return 0


def run_weekly369(
    *,
    dry_run: bool,
    max_patch: Optional[int],
    log_path: Path,
    transport: str = "feed",
) -> int:
    from services.sp_api_inventory import fetch_listings_dataframe_for_repricer
    from services.sp_api_orders import build_sp_api_client
    from services.sp_api_reprice import apply_price_patches, collect_price_patch_targets
    from services.sp_api_reprice_band import load_369_config, sku_is_in_follow_band

    on_progress = _progress(log_path)
    client = build_sp_api_client()
    client.ensure_credentials()
    on_progress("出品一覧を取得中…")
    df, csv_path, err = fetch_listings_dataframe_for_repricer(
        client, on_progress=on_progress
    )
    if err:
        on_progress(f"ERROR fetch: {err}")
        summary = _save_summary(
            log_path,
            "weekly369",
            dry_run=dry_run,
            targets=0,
            patched=0,
            failed=0,
            extra={"error": err},
        )
        _notify_discord(
            log_path,
            "weekly369",
            dry_run=dry_run,
            summary=summary,
            error=err,
        )
        return 1
    on_progress(f"取得完了 rows={len(df)} csv={csv_path}")

    with _python_services_precedence():
        from services.repricer_common import preprocess_dataframe
        from services.repricer_weekly import apply_repricing_rules

        prepared = preprocess_dataframe(df.copy())
        outputs = apply_repricing_rules(prepared, datetime.now(), mode="369")
        items = list(outputs.items or [])

    config = load_369_config()
    before = len(items)
    listed_map: Dict[str, str] = {}
    try:
        with _python_services_precedence():
            from services.repricer_purchase_db import load_listed_date_map_from_purchase_db

            listed_map = load_listed_date_map_from_purchase_db(
                [str(it.get("sku") or "").strip() for it in items]
            )
    except Exception as exc:  # noqa: BLE001
        on_progress(f"出品日の読込をスキップ: {exc}")
    items = [
        it
        for it in items
        if not sku_is_in_follow_band(
            str(it.get("sku") or ""),
            config=config,
            listed_date=listed_map.get(str(it.get("sku") or "").strip()),
        )
    ]
    on_progress(f"追従帯除外: {before} → {len(items)}（週次対象）")

    targets = collect_price_patch_targets(items, only_changed=True)
    on_progress(f"変更SKU: {len(targets)}")
    if dry_run:
        on_progress(f"DRY-RUN: 反映しません transport={transport}（先頭3件={targets[:3]}）")
        _save_summary(log_path, "weekly369", dry_run=True, targets=len(targets), patched=0, failed=0)
        return 0

    limit = max_patch
    on_progress(f"反映 transport={transport}")
    patch = apply_price_patches(
        targets,
        client=client,
        on_progress=on_progress,
        max_items=limit,
        transport=transport,
    )
    failed = list(patch.get("failed") or [])
    failed_path = _write_failed_csv(failed, "weekly369")
    if failed_path:
        on_progress(f"失敗CSV: {failed_path}")
    summary = _save_summary(
        log_path,
        "weekly369",
        dry_run=False,
        targets=len(targets),
        patched=int(patch.get("success_count") or 0),
        failed=int(patch.get("failed_count") or 0),
        extra={
            "failed_csv": str(failed_path) if failed_path else "",
            "transport": patch.get("transport") or transport,
            "feedId": patch.get("feedId") or "",
        },
    )
    _notify_discord(
        log_path,
        "weekly369",
        dry_run=False,
        summary=summary,
        failed_rows=failed,
    )
    try:
        from services.repricer_execution_store import record_repricer_execution

        record_repricer_execution("369")
    except Exception as exc:  # noqa: BLE001
        on_progress(f"execution store skip: {exc}")
    return 0 if int(patch.get("failed_count") or 0) == 0 else 5


def run_follow(
    *,
    dry_run: bool,
    max_patch: Optional[int],
    max_listings: Optional[int],
    log_path: Path,
    transport: str = "feed",
) -> int:
    from services.sp_api_follow_reprice import run_follow_repricer
    from services.sp_api_inventory import fetch_listings_dataframe_for_repricer
    from services.sp_api_orders import build_sp_api_client

    on_progress = _progress(log_path)
    client = build_sp_api_client()
    client.ensure_credentials()
    on_progress("出品一覧を取得中…")
    df, csv_path, err = fetch_listings_dataframe_for_repricer(
        client, on_progress=on_progress
    )
    if err:
        on_progress(f"ERROR fetch: {err}")
        summary = _save_summary(
            log_path,
            "follow",
            dry_run=dry_run,
            targets=0,
            patched=0,
            failed=0,
            extra={"error": err},
        )
        _notify_discord(
            log_path,
            "follow",
            dry_run=dry_run,
            summary=summary,
            error=err,
        )
        return 1
    on_progress(f"取得完了 rows={len(df)} csv={csv_path}")
    rows = df.to_dict(orient="records")
    on_progress(f"反映 transport={transport}")
    result = run_follow_repricer(
        rows,
        client=client,
        apply_amazon=not dry_run,
        max_listings=max_listings,
        patch_max_items=max_patch,
        only_follow_band=True,
        on_progress=on_progress,
        transport=transport,
    )
    items = list(result.get("items") or [])
    changed = sum(1 for it in items if it.get("new_price") != it.get("price"))
    patch = result.get("patch") or {}
    if dry_run:
        on_progress(f"DRY-RUN: 追従計算のみ changed={changed}/{len(items)}")
        _save_summary(log_path, "follow", dry_run=True, targets=changed, patched=0, failed=0)
        return 0
    failed = list(patch.get("failed") or [])
    failed_path = _write_failed_csv(failed, "follow")
    if failed_path:
        on_progress(f"失敗CSV: {failed_path}")
    summary = _save_summary(
        log_path,
        "follow",
        dry_run=False,
        targets=changed,
        patched=int(patch.get("success_count") or 0),
        failed=int(patch.get("failed_count") or 0),
        extra={
            "failed_csv": str(failed_path) if failed_path else "",
            "transport": patch.get("transport") or transport,
            "feedId": patch.get("feedId") or "",
        },
    )
    _notify_discord(
        log_path,
        "follow",
        dry_run=False,
        summary=summary,
        failed_rows=failed,
    )
    return 0 if int(patch.get("failed_count") or 0) == 0 else 5


def _save_summary(
    log_path: Path,
    mode: str,
    *,
    dry_run: bool,
    targets: int,
    patched: int,
    failed: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    summary = {
        "mode": mode,
        "dry_run": dry_run,
        "targets": targets,
        "patched": patched,
        "failed": failed,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        summary.update(extra)
    out = log_path.with_suffix(".summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(log_path, f"summary {summary}")
    return summary


def _failed_skus_from_rows(rows: List[Dict[str, Any]], *, limit: int = 12) -> List[str]:
    out: List[str] = []
    for row in rows:
        sku = str(row.get("sku") or row.get("SKU") or "").strip()
        if sku and sku not in out:
            out.append(sku)
        if len(out) >= limit:
            break
    return out


def _notify_discord(
    log_path: Path,
    mode: str,
    *,
    dry_run: bool,
    summary: Optional[Dict[str, Any]] = None,
    failed_rows: Optional[List[Dict[str, Any]]] = None,
    error: Optional[str] = None,
) -> None:
    """Discord 通知。失敗してもジョブは継続。"""
    if mode == "smoke" or dry_run:
        return
    try:
        from services.reprice_discord_notify import notify_reprice_result
    except Exception as exc:  # noqa: BLE001
        _log(log_path, f"discord notify import skip: {exc}")
        return
    data = dict(summary or {})
    try:
        ok = notify_reprice_result(
            mode,
            dry_run=False,
            success_count=int(data.get("patched") or 0),
            failed_count=int(data.get("failed") or 0),
            targets=int(data.get("targets") or 0),
            extra=data,
            error=error or (str(data.get("error") or "").strip() or None),
            failed_skus=_failed_skus_from_rows(list(failed_rows or [])),
        )
        if ok:
            _log(log_path, "discord notify: sent")
        else:
            _log(log_path, "discord notify: skipped or failed")
    except Exception as exc:  # noqa: BLE001
        _log(log_path, f"discord notify error: {exc}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HIRIO SP-API 無人価格改定")
    parser.add_argument(
        "--mode",
        choices=("weekly369", "follow", "smoke"),
        required=True,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Amazon へ価格を送らない（計算・取得のみ）",
    )
    parser.add_argument(
        "--max-patch",
        type=int,
        default=None,
        help="反映する最大件数（安全弁）",
    )
    parser.add_argument(
        "--max-listings",
        type=int,
        default=400,
        help="follow モードで調査する最大出品数",
    )
    parser.add_argument(
        "--transport",
        choices=("feed", "patch"),
        default="feed",
        help="価格反映方式（既定: feed = JSON_LISTINGS_FEED 一括）",
    )
    args = parser.parse_args(argv)

    _setup_paths()
    mode = args.mode
    log_path = _log_dir() / (
        "sp_api_reprice_smoke.log"
        if mode == "smoke"
        else f"sp_api_reprice_{'weekly' if mode == 'weekly369' else 'follow'}.log"
    )
    _log(
        log_path,
        f"=== start mode={mode} dry_run={args.dry_run} max_patch={args.max_patch} "
        f"transport={args.transport} ===",
    )
    try:
        if mode == "smoke":
            code = run_smoke(log_path)
        elif mode == "weekly369":
            code = run_weekly369(
                dry_run=bool(args.dry_run),
                max_patch=args.max_patch,
                log_path=log_path,
                transport=str(args.transport),
            )
        else:
            code = run_follow(
                dry_run=bool(args.dry_run),
                max_patch=args.max_patch,
                max_listings=args.max_listings,
                log_path=log_path,
                transport=str(args.transport),
            )
    except Exception as exc:  # noqa: BLE001
        _log(log_path, f"FATAL: {exc}")
        _log(log_path, traceback.format_exc())
        if mode != "smoke":
            fatal_summary = _save_summary(
                log_path,
                mode,
                dry_run=bool(args.dry_run),
                targets=0,
                patched=0,
                failed=0,
                extra={"error": str(exc)},
            )
            _notify_discord(
                log_path,
                mode,
                dry_run=bool(args.dry_run),
                summary=fatal_summary,
                error=str(exc),
            )
        return 99
    _log(log_path, f"=== end code={code} ===")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
