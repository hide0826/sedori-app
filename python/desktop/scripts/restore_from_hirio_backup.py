#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIRIOold 等のバックアップフォルダから data/*.db を復元する。

使い方（HIRIO を終了してから）:
  python python/desktop/scripts/restore_from_hirio_backup.py
  python python/desktop/scripts/restore_from_hirio_backup.py --source D:/path/to/HIRIOold
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_source_candidates() -> list[Path]:
    root = _repo_root()
    return [
        root / "HIRIOold",
        root / "HIRIO_old",
        root / "hirio_old",
        root.parent / "HIRIOold",
    ]


def _find_hirio_db(source: Path) -> Path | None:
    patterns = [
        "python/desktop/data/hirio.db",
        "desktop/data/hirio.db",
        "data/hirio.db",
        "hirio.db",
    ]
    for rel in patterns:
        candidate = source / rel.replace("/", "\\") if "\\" in str(source) else source / rel
        if candidate.is_file():
            return candidate
    # フォールバック: 最初に見つかった hirio.db（recording 配下は除外）
    for path in source.rglob("hirio.db"):
        if "recording" in path.parts:
            continue
        return path
    return None


def _inspect_db(path: Path) -> dict:
    info = {"path": str(path), "size": path.stat().st_size, "valid": False, "stores": None, "routes": None}
    if path.read_bytes()[:16] != b"SQLite format 3\x00":
        return info
    info["valid"] = True
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stores")
        info["stores"] = cur.fetchone()[0]
        try:
            cur.execute("SELECT COUNT(*) FROM route_summaries")
            info["routes"] = cur.fetchone()[0]
        except sqlite3.Error:
            info["routes"] = None
    finally:
        conn.close()
    return info


def _related_dbs(backup_data_dir: Path) -> list[str]:
    names = [
        "hirio.db",
        "hirio_product_purchase.db",
        "hirio_inventory_route.db",
    ]
    return [name for name in names if (backup_data_dir / name).is_file()]


def restore(source: Path, target_data: Path, include_all: bool, dry_run: bool) -> int:
    backup_db = _find_hirio_db(source)
    if backup_db is None:
        print(f"[ERROR] バックアップ内に hirio.db が見つかりません: {source}")
        return 1

    backup_data_dir = backup_db.parent
    inspect = _inspect_db(backup_db)
    print("=== バックアップ hirio.db ===")
    for k, v in inspect.items():
        print(f"  {k}: {v}")

    if not inspect["valid"]:
        print("[ERROR] バックアップ hirio.db は SQLite として読めません。復元を中止します。")
        return 1

    if inspect["stores"] == 0:
        print("[WARN] 店舗マスタが 0 件です。別のバックアップの可能性があります。")

    files_to_copy = ["hirio.db"]
    if include_all:
        files_to_copy = _related_dbs(backup_data_dir)

    print("\n=== コピー対象 ===")
    for name in files_to_copy:
        src = backup_data_dir / name
        print(f"  {src}  ({src.stat().st_size:,} bytes)")

    if dry_run:
        print("\n[DRY-RUN] 実際のコピーは行いませんでした。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = target_data.parent / f"data_before_restore_{stamp}"
    target_data.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== 現在の data を退避: {backup_dir} ===")
    for item in target_data.iterdir():
        if item.is_file():
            shutil.copy2(item, backup_dir / item.name)
            print(f"  backed up: {item.name}")

    print(f"\n=== 復元先: {target_data} ===")
    for name in files_to_copy:
        src = backup_data_dir / name
        dst = target_data / name
        shutil.copy2(src, dst)
        print(f"  restored: {name}")

    after = _inspect_db(target_data / "hirio.db")
    print("\n=== 復元後 hirio.db ===")
    for k, v in after.items():
        print(f"  {k}: {v}")

    recording_dir = target_data / "recording"
    if recording_dir.exists():
        print("\n[INFO] 撮影用 recording/ フォルダはそのまま残しています。")
        print("       本番DBを確認するには設定で「撮影モード」を OFF にしてください。")

    print("\n[OK] 復元完了。HIRIO を起動して店舗マスタを確認してください。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HIRIOold から DB を復元")
    parser.add_argument("--source", type=Path, help="バックアップフォルダ（HIRIOold 等）")
    parser.add_argument(
        "--target-data",
        type=Path,
        default=_repo_root() / "python" / "desktop" / "data",
        help="復元先 data フォルダ",
    )
    parser.add_argument(
        "--all-dbs",
        action="store_true",
        help="hirio.db 以外の product_purchase / inventory_route もコピー",
    )
    parser.add_argument("--dry-run", action="store_true", help="確認のみ（コピーしない）")
    args = parser.parse_args()

    source = args.source
    if source is None:
        for candidate in _default_source_candidates():
            if candidate.is_dir():
                source = candidate
                break
    if source is None or not source.is_dir():
        print("[ERROR] バックアップフォルダが見つかりません。")
        print("  次のいずれかに HIRIOold をコピーしてください:")
        for c in _default_source_candidates():
            print(f"    {c}")
        return 1

    print(f"[INFO] バックアップ元: {source}")
    return restore(source, args.target_data, args.all_dbs, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
