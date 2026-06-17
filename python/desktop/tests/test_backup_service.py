#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup_service のユニットテスト。"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from services.backup_service import (
    BACKUP_FILE_PREFIX,
    create_backup,
    inspect_sqlite_db,
    list_backup_archives,
    prune_old_backups,
    restore_from_zip,
)


def _create_minimal_hirio_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE stores (id INTEGER PRIMARY KEY, store_code TEXT, store_name TEXT)"
        )
        conn.execute(
            "INSERT INTO stores (store_code, store_name) VALUES ('TST01', 'テスト店舗')"
        )
        conn.commit()
    finally:
        conn.close()


def test_inspect_sqlite_db_valid(tmp_path: Path) -> None:
    db_path = tmp_path / "hirio.db"
    _create_minimal_hirio_db(db_path)
    info = inspect_sqlite_db(db_path)
    assert info["valid"] is True
    assert info["stores"] == 1


def test_create_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    restore_data_dir = tmp_path / "restore_data"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "inventory_settings.json").write_text('{"test": true}', encoding="utf-8")

    _create_minimal_hirio_db(data_dir / "hirio.db")
    (data_dir / "missing_keywords.json").write_text("{}", encoding="utf-8")

    # config パスを差し替え
    import services.backup_service as backup_service

    original_get_config_dir = backup_service.get_config_dir
    backup_service.get_config_dir = lambda: config_dir
    try:
        result = create_backup(backup_dir, include_config=True, data_dir=data_dir, keep_count=7)
    finally:
        backup_service.get_config_dir = original_get_config_dir

    assert result.success is True
    assert result.zip_path is not None
    assert result.zip_path.exists()

    with zipfile.ZipFile(result.zip_path, "r") as zf:
        names = zf.namelist()
        assert "data/hirio.db" in names
        assert "manifest.json" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["hirio_db"]["stores"] == 1

    restore_data_dir.mkdir()
    restore_result = restore_from_zip(
        result.zip_path,
        data_dir=restore_data_dir,
        include_config_override=False,
    )
    assert restore_result.success is True
    restored_info = inspect_sqlite_db(restore_data_dir / "hirio.db")
    assert restored_info["valid"] is True
    assert restored_info["stores"] == 1


def test_prune_old_backups(tmp_path: Path) -> None:
    for i in range(5):
        path = tmp_path / f"{BACKUP_FILE_PREFIX}2026010{i}_120000.zip"
        path.write_bytes(b"zip")
    removed = prune_old_backups(tmp_path, keep_count=2)
    assert len(removed) == 3
    remaining = list_backup_archives(tmp_path)
    assert len(remaining) == 2
