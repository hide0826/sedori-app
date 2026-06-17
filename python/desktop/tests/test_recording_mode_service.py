#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デモモード（仮想DB）の安全性テスト。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services.recording_mode_service import (
    create_recording_databases,
    delete_recording_databases,
    set_recording_mode_enabled,
)


def _create_prod_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE stores (id INTEGER PRIMARY KEY, store_code TEXT, store_name TEXT)"
        )
        conn.execute(
            "CREATE TABLE purchases (id INTEGER PRIMARY KEY, sku TEXT, asin TEXT)"
        )
        conn.execute(
            "INSERT INTO stores (store_code, store_name) VALUES ('PROD01', '本番店舗')"
        )
        conn.execute(
            "INSERT INTO purchases (sku, asin) VALUES ('PROD-SKU-1', 'B000000001')"
        )
        conn.commit()
    finally:
        conn.close()


def _count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


@pytest.fixture()
def isolated_data_dirs(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    recording_dir = data_dir / "recording"
    prod_db = data_dir / "hirio.db"
    _create_prod_db(prod_db)

    monkeypatch.setattr(
        "services.recording_mode_service.get_data_dir",
        lambda: data_dir,
    )
    monkeypatch.setattr(
        "services.recording_mode_service.get_recording_data_dir",
        lambda: recording_dir,
    )
    monkeypatch.setattr(
        "services.recording_mode_service.get_recording_hirio_db_path",
        lambda: str(recording_dir / "hirio.db"),
    )
    monkeypatch.setattr(
        "services.recording_mode_service.get_recording_product_purchase_db_path",
        lambda: str(recording_dir / "hirio_product_purchase.db"),
    )
    monkeypatch.setattr(
        "services.recording_mode_service.get_recording_inventory_route_db_path",
        lambda: str(recording_dir / "hirio_inventory_route.db"),
    )

    return {
        "data_dir": data_dir,
        "recording_dir": recording_dir,
        "prod_db": prod_db,
    }


def test_recording_db_copies_master_only(isolated_data_dirs) -> None:
    create_recording_databases()
    recording_db = isolated_data_dirs["recording_dir"] / "hirio.db"
    assert recording_db.is_file()

    prod_conn = sqlite3.connect(str(isolated_data_dirs["prod_db"]))
    rec_conn = sqlite3.connect(str(recording_db))
    try:
        assert _count(prod_conn, "stores") == 1
        assert _count(prod_conn, "purchases") == 1
        assert _count(rec_conn, "stores") == 1
        assert _count(rec_conn, "purchases") == 0
    finally:
        prod_conn.close()
        rec_conn.close()


def test_enable_recording_does_not_modify_production(isolated_data_dirs) -> None:
    prod_db = isolated_data_dirs["prod_db"]
    before = prod_db.read_bytes()

    set_recording_mode_enabled(True, False)

    assert prod_db.read_bytes() == before
    prod_conn = sqlite3.connect(str(prod_db))
    try:
        assert _count(prod_conn, "purchases") == 1
    finally:
        prod_conn.close()


def test_disable_recording_deletes_virtual_db_only(isolated_data_dirs) -> None:
    set_recording_mode_enabled(True, False)
    recording_dir = isolated_data_dirs["recording_dir"]
    assert recording_dir.exists()

    set_recording_mode_enabled(False, True)
    assert not recording_dir.exists()

    prod_conn = sqlite3.connect(str(isolated_data_dirs["prod_db"]))
    try:
        assert _count(prod_conn, "stores") == 1
        assert _count(prod_conn, "purchases") == 1
    finally:
        prod_conn.close()


def test_writing_to_recording_db_does_not_touch_production(isolated_data_dirs) -> None:
    create_recording_databases()
    recording_db = isolated_data_dirs["recording_dir"] / "hirio.db"

    rec_conn = sqlite3.connect(str(recording_db))
    try:
        rec_conn.execute("INSERT INTO purchases (sku, asin) VALUES ('DEMO-SKU', 'B999')")
        rec_conn.commit()
        assert _count(rec_conn, "purchases") == 1
    finally:
        rec_conn.close()

    prod_conn = sqlite3.connect(str(isolated_data_dirs["prod_db"]))
    try:
        assert _count(prod_conn, "purchases") == 1
        cur = prod_conn.cursor()
        cur.execute("SELECT sku FROM purchases")
        assert cur.fetchone()[0] == "PROD-SKU-1"
    finally:
        prod_conn.close()
