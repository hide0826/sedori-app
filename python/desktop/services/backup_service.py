#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HIRIO データのバックアップ・復元（ZIP形式）。"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

BACKUP_FILE_PREFIX = "HIRIO_backup_"
BACKUP_FILE_SUFFIX = ".zip"

_DATA_DB_NAMES = (
    "hirio.db",
    "hirio_product_purchase.db",
    "hirio_inventory_route.db",
)
_DATA_JSON_NAMES = (
    "missing_keywords.json",
    "image_registration_snapshot.json",
    "customer_support_sessions.json",
)
_DATA_DIR_NAMES = ("receipt_snapshots",)
_CONFIG_NAMES = (
    "inventory_settings.json",
    "reprice_rules.json",
)


@dataclass
class BackupResult:
    success: bool
    zip_path: Optional[Path] = None
    message: str = ""
    manifest: Optional[Dict[str, Any]] = None


@dataclass
class RestoreResult:
    success: bool
    message: str = ""
    restored_files: Optional[List[str]] = None
    safety_backup_dir: Optional[Path] = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _settings():
    try:
        from utils.settings_helper import _settings as get_settings
    except ImportError:
        from desktop.utils.settings_helper import _settings as get_settings  # type: ignore
    return get_settings()


def get_data_dir() -> Path:
    try:
        from utils.db_paths import get_data_dir as _get_data_dir
    except ImportError:
        from desktop.utils.db_paths import get_data_dir as _get_data_dir  # type: ignore
    return _get_data_dir()


def get_config_dir() -> Path:
    return _repo_root() / "config"


def get_backup_folder() -> str:
    return str(_settings().value("backup/folder", "") or "").strip()


def is_auto_backup_on_exit_enabled() -> bool:
    return _settings().value("backup/auto_on_exit", False, type=bool)


def get_backup_keep_count() -> int:
    value = int(_settings().value("backup/keep_count", 7) or 7)
    return max(1, min(value, 30))


def is_backup_include_config_enabled() -> bool:
    return _settings().value("backup/include_config", True, type=bool)


def inspect_sqlite_db(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "path": str(path),
        "size": path.stat().st_size if path.is_file() else 0,
        "valid": False,
        "stores": None,
        "routes": None,
    }
    if not path.is_file():
        return info
    try:
        header = path.read_bytes()[:16]
        if not header.startswith(b"SQLite format 3"):
            return info
        info["valid"] = True
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM stores")
                info["stores"] = cur.fetchone()[0]
            except sqlite3.Error:
                info["stores"] = None
            try:
                cur.execute("SELECT COUNT(*) FROM route_summaries")
                info["routes"] = cur.fetchone()[0]
            except sqlite3.Error:
                info["routes"] = None
        finally:
            conn.close()
    except Exception:
        info["valid"] = False
    return info


def backup_sqlite_file(src_path: Path, dst_path: Path) -> None:
    """起動中でも一貫した SQLite コピーを作成する。"""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if dst_path.exists():
        dst_path.unlink()
    src_conn = sqlite3.connect(str(src_path))
    dst_conn = sqlite3.connect(str(dst_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _copy_plain_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)


def _iter_backup_zip_paths(
    data_dir: Path,
    *,
    include_config: bool,
) -> List[Tuple[Path, str]]:
    """(ソースパス, ZIP内相対パス) の一覧。"""
    pairs: List[Tuple[Path, str]] = []

    for name in _DATA_DB_NAMES:
        src = data_dir / name
        if src.is_file():
            pairs.append((src, f"data/{name}"))

    for name in _DATA_JSON_NAMES:
        src = data_dir / name
        if src.is_file():
            pairs.append((src, f"data/{name}"))

    for dir_name in _DATA_DIR_NAMES:
        src = data_dir / dir_name
        if src.is_dir():
            for child in src.rglob("*"):
                if child.is_file():
                    rel = child.relative_to(data_dir)
                    pairs.append((child, f"data/{rel.as_posix()}"))

    if include_config:
        config_dir = get_config_dir()
        for name in _CONFIG_NAMES:
            src = config_dir / name
            if src.is_file():
                pairs.append((src, f"config/{name}"))

    return pairs


def _build_manifest(
    *,
    data_dir: Path,
    include_config: bool,
    files: Sequence[str],
) -> Dict[str, Any]:
    hirio_info = inspect_sqlite_db(data_dir / "hirio.db")
    return {
        "app": "HIRIO Desktop",
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "include_config": include_config,
        "files": list(files),
        "hirio_db": {
            "valid": hirio_info.get("valid"),
            "stores": hirio_info.get("stores"),
            "routes": hirio_info.get("routes"),
            "size": hirio_info.get("size"),
        },
    }


def _create_zip_from_staging(staging_dir: Path, zip_path: Path) -> None:
    """ZIP 作成（DB は無圧縮で高速化）。"""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in sorted(staging_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() == zip_path.resolve():
                continue
            arcname = path.relative_to(staging_dir).as_posix()
            zf.write(path, arcname)


def record_backup_success(zip_path: Path) -> None:
    """バックアップ成功を QSettings に記録（メインスレッドから呼ぶ）。"""
    _settings().setValue("backup/last_success_at", datetime.now().isoformat(timespec="seconds"))
    _settings().setValue("backup/last_success_path", str(zip_path))


def create_backup(
    dest_dir: Path,
    *,
    include_config: Optional[bool] = None,
    data_dir: Optional[Path] = None,
    keep_count: Optional[int] = None,
) -> BackupResult:
    """バックアップ ZIP を作成して dest_dir に保存する。"""
    dest_dir = Path(dest_dir)
    data_dir = data_dir or get_data_dir()
    include_config = (
        is_backup_include_config_enabled() if include_config is None else include_config
    )

    if not (data_dir / "hirio.db").is_file():
        return BackupResult(False, message="hirio.db が見つかりません。バックアップを中止しました。")

    pairs = _iter_backup_zip_paths(data_dir, include_config=include_config)
    if not pairs:
        return BackupResult(False, message="バックアップ対象ファイルがありません。")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{BACKUP_FILE_PREFIX}{stamp}{BACKUP_FILE_SUFFIX}"

    try:
        with tempfile.TemporaryDirectory(prefix="hirio_backup_") as tmp:
            work_dir = Path(tmp)
            staging = work_dir / "staging"
            staging.mkdir(parents=True, exist_ok=True)

            for src, arc_rel in pairs:
                dst = staging / arc_rel
                if src.suffix == ".db":
                    backup_sqlite_file(src, dst)
                elif src.is_file():
                    _copy_plain_file(src, dst)

            manifest = _build_manifest(
                data_dir=data_dir,
                include_config=include_config,
                files=[arc for _, arc in pairs],
            )
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            temp_zip = work_dir / zip_name
            _create_zip_from_staging(staging, temp_zip)

            dest_dir.mkdir(parents=True, exist_ok=True)
            final_zip = dest_dir / zip_name
            shutil.move(str(temp_zip), str(final_zip))

        prune_old_backups(
            dest_dir,
            keep_count if keep_count is not None else get_backup_keep_count(),
        )

        return BackupResult(
            success=True,
            zip_path=final_zip,
            message=f"バックアップを保存しました:\n{final_zip}",
            manifest=manifest,
        )
    except Exception as exc:
        logger.exception("backup failed")
        return BackupResult(False, message=f"バックアップに失敗しました:\n{exc}")


def list_backup_archives(folder: Path) -> List[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [
        p
        for p in folder.glob(f"{BACKUP_FILE_PREFIX}*{BACKUP_FILE_SUFFIX}")
        if p.is_file()
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_old_backups(folder: Path, keep_count: int) -> List[Path]:
    """古いバックアップ ZIP を削除し、削除したパス一覧を返す。"""
    keep_count = max(1, keep_count)
    archives = list_backup_archives(folder)
    removed: List[Path] = []
    for old in archives[keep_count:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError as exc:
            logger.warning("failed to remove old backup %s: %s", old, exc)
    return removed


def _validate_backup_zip(zf: zipfile.ZipFile) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    names = zf.namelist()
    if "data/hirio.db" not in names:
        return False, "バックアップ ZIP に data/hirio.db が含まれていません。", None

    manifest: Optional[Dict[str, Any]] = None
    if "manifest.json" in names:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except Exception:
            manifest = None

    with tempfile.TemporaryDirectory(prefix="hirio_restore_check_") as tmp:
        extract_path = Path(tmp) / "data" / "hirio.db"
        extract_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open("data/hirio.db") as src, open(extract_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        info = inspect_sqlite_db(extract_path)
        if not info["valid"]:
            return False, "バックアップ内の hirio.db が SQLite として読めません。", manifest

    return True, "", manifest


def restore_from_zip(
    zip_path: Path,
    *,
    data_dir: Optional[Path] = None,
    include_config_override: Optional[bool] = None,
    close_connections: Optional[Callable[[], None]] = None,
) -> RestoreResult:
    """バックアップ ZIP から data/（と config/）を復元する。"""
    zip_path = Path(zip_path)
    data_dir = data_dir or get_data_dir()
    config_dir = get_config_dir()

    if not zip_path.is_file():
        return RestoreResult(False, message="バックアップファイルが見つかりません。")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            ok, err, manifest = _validate_backup_zip(zf)
            if not ok:
                return RestoreResult(False, message=err)

            include_config = is_backup_include_config_enabled()
            if include_config_override is not None:
                include_config = include_config_override
            elif manifest is not None:
                include_config = bool(manifest.get("include_config", include_config))

            if close_connections is not None:
                close_connections()

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_dir = data_dir.parent / f"data_before_restore_{stamp}"
            safety_dir.mkdir(parents=True, exist_ok=True)

            restored: List[str] = []
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                if name == "manifest.json":
                    continue
                if name.startswith("data/"):
                    rel = Path(name).relative_to("data")
                    target = data_dir / rel
                elif name.startswith("config/") and include_config:
                    rel = Path(name).relative_to("config")
                    target = config_dir / rel
                else:
                    continue

                if target.is_file():
                    safety_copy = safety_dir / name
                    safety_copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, safety_copy)

                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored.append(name)

        after = inspect_sqlite_db(data_dir / "hirio.db")
        if not after["valid"]:
            return RestoreResult(
                False,
                message="復元後の hirio.db を検証できませんでした。",
                safety_backup_dir=safety_dir,
            )

        return RestoreResult(
            success=True,
            message=(
                "データを復元しました。\n"
                "変更を反映するため、アプリを再起動してください。"
            ),
            restored_files=restored,
            safety_backup_dir=safety_dir,
        )
    except PermissionError:
        return RestoreResult(
            False,
            message=(
                "ファイルが使用中のため復元できませんでした。\n"
                "HIRIO を一度終了してから、再度お試しください。"
            ),
        )
    except Exception as exc:
        logger.exception("restore failed")
        return RestoreResult(False, message=f"復元に失敗しました:\n{exc}")


def run_auto_backup_on_exit() -> BackupResult:
    """終了時自動バックアップ（設定が有効かつ保存先が設定されている場合のみ）。"""
    if not is_auto_backup_on_exit_enabled():
        return BackupResult(False, message="自動バックアップは無効です。")

    folder_text = get_backup_folder()
    if not folder_text:
        return BackupResult(False, message="バックアップ保存先が未設定です。")

    dest = Path(folder_text)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("auto backup folder unavailable: %s", exc)
        return BackupResult(False, message=f"バックアップ保存先を作成できません: {exc}")

    return create_backup(dest)


def close_db_connection(db: Any) -> None:
    if db is None:
        return
    conn = getattr(db, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db.conn = None


def close_db_connections_in_object(root: Any, *, seen: Optional[set[int]] = None) -> None:
    """オブジェクト配下の *_db 接続を再帰的に閉じる。"""
    if root is None:
        return
    if seen is None:
        seen = set()
    obj_id = id(root)
    if obj_id in seen:
        return
    seen.add(obj_id)

    if hasattr(root, "conn"):
        close_db_connection(root)

    for attr_name in dir(root):
        if not attr_name.endswith("_db"):
            continue
        if attr_name.startswith("__"):
            continue
        try:
            child = getattr(root, attr_name)
        except Exception:
            continue
        close_db_connection(child)

    children_getter = getattr(root, "children", None)
    if callable(children_getter):
        try:
            for child in children_getter():
                close_db_connections_in_object(child, seen=seen)
        except Exception:
            pass
